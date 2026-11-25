"""Consolidate the frozen 2026-11-11 Bovada quote/scorer snapshot.

Parlays are explicitly shadow-only: multiplying single-leg quotes is not a
verified multi-leg sportsbook offer, nor is an independent Kelly allocation.
"""
import csv
import datetime as dt
import hashlib
import itertools
import json
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'outputs/bovada_20261111_raw'
OUT = ROOT / 'outputs/NOV11_CROSS_SPORT'
OUT.mkdir(parents=True, exist_ok=True)


def dec(american):
    a = float(american)
    return 1 + (a / 100 if a > 0 else 100 / -a)


def pct(x):
    return f'{100*x:+.1f}%' if pd.notna(x) else '—'


def kel(x):
    return f'{100*x:.2f}%' if pd.notna(x) else 'blocked'


def odds(x):
    return f'+{int(x)}' if x > 0 else f'{int(x)}'


boards = {sport: pd.read_csv(SOURCE / f'{sport}_main_board.csv') for sport in ('NFL','NCAAFB','NBA','NCAABB','NHL')}
idx = {}
for sport, df in boards.items():
    for _, r in df.iterrows():
        idx[(sport, str(r.event_id))] = r
        idx[(sport, str(r.game))] = r

rows = []


def add(sport, board, model, role, market, side, price, p, ev, full, adjusted, tier, status, *, notes='', source=''):
    if pd.isna(price):
        return
    rows.append(dict(sport=sport, event_id=str(board.event_id), game=board.game,
        start_central=board.start_central, quote_captured_utc=board.captured_utc,
        model=model, model_role=role, market=market, selection=side,
        american_odds=float(price), model_p=float(p) if pd.notna(p) else None,
        expected_value=float(ev) if pd.notna(ev) else None,
        full_kelly=float(full) if pd.notna(full) else None,
        adjusted_kelly=float(adjusted) if pd.notna(adjusted) else None,
        tier=tier, status=status, notes=notes, source_file=source))


nba_paths = [('R4_champion', 'NBA_R4_PRODUCTION', 'CHAMPION'), ('R3_challenger','NBA_R3_SRS_CHALLENGER','CHALLENGER')]
for folder, model, role in nba_paths:
    nba = pd.read_csv(SOURCE / 'NBA_R4_R3_SCORE' / folder / 'forecasts.csv')
    for _, r in nba.iterrows():
        board = idx.get(('NBA', r.Game))
        if board is None:
            continue
        if str(r.Tier) != 'Pass' and pd.notna(r.EV) and r.EV > 0:
            status = 'PRODUCTION_QUALIFIED' if role == 'CHAMPION' else 'RESEARCH_POSITIVE_EV'
            add('NBA', board, model, role, r.Market, r.Selection, r.Odds, r.Model_P, r.EV,
                r.Full_Kelly, r.Adjusted_Kelly, r.Tier, status,
                notes=str(r.get('Model_Health','')), source=f'NBA_R4_R3_SCORE/{folder}/forecasts.csv')

cbb = pd.read_csv(SOURCE / 'NCAABB_V4_SCORES.csv')
for _, r in cbb.iterrows():
    board = idx.get(('NCAABB', str(r.game_id).removeprefix('BOVADA_')))
    if board is None:
        continue
    if bool(r.stake_eligible) and pd.notna(r.expected_unit_net_at_quote) and r.expected_unit_net_at_quote > 0:
        selection = ((r.home_team if r.selected_side == 'Home' else r.away_team)
                     if r.market != 'Total' else r.selected_side)
        if r.market == 'Spread':
            line = board.home_spread_line if r.selected_side == 'Home' else board.away_spread_line
            selection += f' {float(line):+g}'
        add('NCAABB', board, 'NCAABB_V4_THROUGH_2025', 'CHAMPION',r.market,selection,
            r.quoted_odds,r.selected_probability,r.expected_unit_net_at_quote,r.full_kelly,
            r.final_recommended_kelly,r.tier,'PRODUCTION_QUALIFIED',
            notes=f'{r.health}; model adjusted sizing may not be joint-portfolio validated',
            source='NCAABB_V4_SCORES.csv')

cbb_v5 = pd.read_csv(SOURCE / 'NCAABB_V5_OPPORTUNITIES.csv')
for _, r in cbb_v5.iterrows():
    board = idx.get(('NCAABB', str(r.game_id).removeprefix('BOVADA_')))
    if board is None or pd.isna(r.shadow_ev) or r.shadow_ev <= 0.01 or pd.isna(r.offered_odds):
        continue
    sel = board.home if r.side=='Home' else board.away if r.side=='Away' else r.side
    if r.market == 'Spread':
        line = board.home_spread_line if r.side=='Home' else board.away_spread_line
        sel += f' {float(line):+g}'
    add('NCAABB',board,'NCAABB_V5_SHADOW','CHALLENGER',r.market,sel,r.offered_odds,
        r.shadow_p,r.shadow_ev,r.shadow_full_kelly,None,r.shadow_research_tier,
        'RESEARCH_POSITIVE_EV', notes='Challenger; sizing blocked',source='NCAABB_V5_OPPORTUNITIES.csv')

nhl = pd.read_csv(SOURCE/'NHL_DAY0_ALL_SCORES.csv')
for _,r in nhl.iterrows():
    if str(r.display_section) != 'Research candidate' or pd.isna(r.model_ev) or r.model_ev <= 0:
        continue
    board = idx.get(('NHL',r.game))
    if board is None:
        continue
    sel = f'{r.selection} {float(r.line):g}' if pd.notna(r.line) else r.selection
    add('NHL',board,'NHL_DAY0','CHAMPION',r.market,sel,r.american_odds,r.model_p_win,
        r.model_ev,r.full_kelly_diagnostic,None,str(r.tier), 'RESEARCH_POSITIVE_EV',
        notes='Day0 positive but not approved; full Kelly only diagnostic',source='NHL_DAY0_ALL_SCORES.csv')

# The Nov9 frozen, Week10-feature NCAAFB dual score contains Pass for all three
# Nov11 games, but those quotes are not today's prices. Keep fresh odds without
# claiming a fresh Nov11 model probability/score.
for _,board in boards['NCAAFB'].iterrows():
    rows.append(dict(sport='NCAAFB',event_id=str(board.event_id),game=board.game,
        start_central=board.start_central,quote_captured_utc=board.captured_utc,
        model='NCAAFB_W8_PLUS', model_role='CHAMPION',market='ALL',selection='Unscored',
        american_odds=None,model_p=None,expected_value=None,full_kelly=None,adjusted_kelly=None,
        tier='Pass (prior Nov9 only)',status='UNSCORED',
        notes='Frozen Nov9 dual-model score was Pass; current odds changed, not reprocessed with fresh Week12 features',
        source_file='NCAAFB_main_board.csv'))

all_df=pd.DataFrame(rows)
all_df=all_df.sort_values(['start_central','sport','game','model_role','market']).reset_index(drop=True)
all_df.to_csv(OUT/'NOV11_ALL_POSITIVE_SIGNALS_AND_BLOCKED.csv', index=False)
production=all_df[all_df.status=='PRODUCTION_QUALIFIED'].copy()
research=all_df[all_df.status=='RESEARCH_POSITIVE_EV'].copy()
production.to_csv(OUT/'NOV11_PRODUCTION_QUALIFIERS.csv',index=False)
research.to_csv(OUT/'NOV11_RESEARCH_ONLY_SIGNALS.csv',index=False)

# Single-game independent research combinations, which are *not* sportsbook quotes.
parlays=[]
excluded_cohort=0
for k in (2,3):
    for members in itertools.combinations(production.to_dict('records'),k):
        if len({(x['sport'],x['event_id']) for x in members}) < k:
            continue
        times=[dt.datetime.fromisoformat(x['quote_captured_utc']) for x in members]
        if (max(times)-min(times)).total_seconds()>120:
            excluded_cohort+=1
            continue
        d=1.0;p=1.0
        for x in members:
            d*=dec(x['american_odds']);p*=x['model_p']
        ev=p*d-1
        parlays.append(dict(legs=k,leg_labels=' | '.join(f"{x['sport']} {x['selection']} {odds(x['american_odds'])}" for x in members),
            games=' | '.join(x['game'] for x in members),
            leg_event_keys='|'.join(f"{x['sport']}:{x['event_id']}" for x in members),
            model_win_probability=p,hypothetical_decimal_odds=d,
            hypothetical_american_odds=((d-1)*100 if d>=2 else -100/(d-1)),
            hypothetical_ev=ev,price_source='PRODUCT_OF_SINGLES_ONLY_NOT_BOVADA_PARLAY',
            model='PARLAY_RESEARCH_V1',authorization='RESEARCH_ONLY',
            quote_status='MULTILEG_OFFER_NOT_VERIFIED',adjusted_kelly_status='SIZING_BLOCKED',
            bonus_qualification_status='UNVERIFIED',same_date=True,distinct_games=True))
parlay=pd.DataFrame(parlays).sort_values(['hypothetical_ev','legs'],ascending=[False,True])
parlay.to_csv(OUT/'NOV11_THEORETICAL_SAME_DAY_PARLAYS.csv',index=False)


def table(df):
    out=[]
    for _,r in df.iterrows():
        start=dt.datetime.fromisoformat(r.start_central).strftime('%-I:%M %p')
        out.append(f"| {start} | {r.sport} | {r.game} | {r.selection} **{odds(r.american_odds)}** | {r.tier} | {r.model} | {pct(r.expected_value)} | {kel(r.full_kelly)} | {kel(r.adjusted_kelly)} |")
    return '\n'.join(out)

lines=[
    '# November 11, 2026 — cross-sport Bovada snapshot and theoretical parlay research',
    '',
    'Captured approximately 12:35–12:39 a.m. CST Nov 11, 2026. Lines change; verify at book.',
    '',
    '## Production-model qualifiers (chronological, not claims of realized profit)',
    '',
    '| Start CT | Sport | Matchup | Selection / quoted single odds | Tier | Model | Model EV | Full Kelly | Model adjusted Kelly |',
    '|---|---|---|---|---|---|---:|---:|---:|',
    table(production),'',
    'The displayed adjusted Kelly values come from individual sport scorers, not a validated joint cross-sport portfolio. Do not interpret them as additive stakes.',
    '',
    '## Research-only positive-EV signals (no approved sizing)',
    '',
    '| Start CT | Sport | Matchup | Selection / quoted single odds | Tier | Model | Model EV | Full Kelly diagnostic | Adjusted Kelly |',
    '|---|---|---|---|---|---|---:|---:|---:|',
    table(research),'',
    '## Research-only theoretical parlays — no book quote, no wagering authorization',
    '',
    '| Legs | Selections (single-book odds) | Hypothetical product price | Independence P | Hypothetical EV |',
    '|---:|---|---:|---:|---:|',
]
for _,r in parlay.head(10).iterrows():
    lines.append(f"| {r.legs} | {r.leg_labels.replace('|',';')} | {r.hypothetical_decimal_odds:.2f}× | {r.model_win_probability:.1%} | {r.hypothetical_ev:+.1%} |")
lines.extend(['','**No actual combined Bovada price obtained.** These illustrative figures omit any distinct-game residual dependence, repricing on pushes, or shared-leg correlation across tickets. Adjusted portfolio Kelly and bonus qualification are blocked.',
              f'Capture-cohort filter: {len(parlay)} hypothetical same-cohort combinations retained; {excluded_cohort} cross-cohort combinations excluded, including all mixed NBA/NCAABB tickets. The separated quote times do not prove simultaneous availability.',
    'Parlay table is ranked by **hypothetical EV** only. Bonus-first rankings are blocked without verified qualifying rollover credit and actual combined prices; no parlay receives a recommended stake.',
              '', '## Coverage and blocked items', '',
              '- NBA: 9 priced games; R4 champion and R3 challenger scored.',
              '- NHL: 6 priced games; Day0 plus V15 inputs, no production-authorized signals.',
              '- NCAABB: 23 Bovada event-page games priced, 19 scorables, 4 model-input blocked. Other ESPN-scheduled games had no captured Bovada prices.',
              '- NCAAFB: 3 priced games; only older Nov9 frozen Pass classifications available. Not counted as refreshed Nov11 scores.',
              '- NFL: No Wednesday Nov11 games.',
              '- Bonus B1 16,000 by Nov18 and B2 2,750 by Nov24 remain unverified rollover assumptions. Hypothetical odds do not establish faster rollover credit.',
              '', 'Research-only signals and parlays are not additional verified wagers.', ''])
(OUT/'NOV11_CROSS_SPORT_BET_SHEET_AND_PARLAY_RESEARCH.md').write_text('\n'.join(lines))

manifest=dict(games_captured={k:int(len(v)) for k,v in boards.items()},
    production_qualifiers=int(len(production)),research_single_signals=int(len(research)),
    parlay_pairs=int((parlay.legs==2).sum()),parlay_triples=int((parlay.legs==3).sum()),
    excluded_cross_cohort_combinations=excluded_cohort,
    original_board_capture_utc={k:str(v.captured_utc.min()) if len(v) else None for k,v in boards.items()},
    status='PARLAY_UNVERIFIED_AND_SIZING_BLOCKED')
(OUT/'NOV11_MANIFEST.json').write_text(json.dumps(manifest,indent=2))
print(json.dumps(manifest,indent=2))
print(production[['start_central','sport','selection','american_odds','tier','expected_value']].to_string(index=False))
print('TOP PARLAYS');print(parlay[['legs','leg_labels','hypothetical_decimal_odds','hypothetical_ev']].head(5).to_string(index=False))
