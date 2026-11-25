"""Attach Nov10 ESPN final scores and hypothetical quote/score grading.

Updates the new ZIP only, preserving all legacy snapshots and imports. Actual
Bovada betting P&L is not inferred from simulated market outcomes.
"""
import csv
import datetime as dt
import json
import sqlite3
import zipfile
from pathlib import Path

import pandas as pd

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'outputs/NOV11_CROSS_SPORT'
NEW=ROOT/'outputs/NOV11_ARCHIVE_V28'
OLD=ROOT/'recovered_sources/GAMBLING_ROLLING_AUTHORITATIVE_QUOTES_AND_SCORES.zip'
DB=NEW/'GAMBLING_ROLLING_SCORING_HISTORY.sqlite'
db=sqlite3.connect(DB)

matches=pd.read_csv(OUT/'NOV10_MATCHED_FINALS_FOR_ROLLING_LEDGER.csv')
prior=set(pd.read_sql_query('SELECT game_key FROM settlements',db)['game_key'])
count=0
for _,r in matches.iterrows():
    if r.game_key in prior:continue
    db.execute('INSERT INTO settlements(game_key,sportsbook_event_id,final_away_score,final_home_score,settled_at_utc,result_source) VALUES (?,?,?,?,?,?)',
        (r.game_key,r.game_key.split(':')[-1],int(r.away_score),int(r.home_score),None,
         f'ESPN scoreboard final {r.espn_game_id}; retrieved {r.observed_utc}'))
    count+=1
db.commit()

def grade(x):
    if pd.isna(x.final_away_score) or pd.isna(x.final_home_score):return ('',None)
    if pd.isna(x.odds_american):return ('',None)
    a=float(x.final_away_score);h=float(x.final_home_score)
    if x.market=='Moneyline':
        signed=(a-h if x.side=='Away' else h-a)
    elif x.market=='Spread':
        if pd.isna(x.line):return ('',None)
        signed=(a-h+float(x.line) if x.side=='Away' else h-a+float(x.line))
    elif x.market=='Total':
        if pd.isna(x.line):return ('',None)
        signed=(a+h-float(x.line))*(1 if x.side=='Over' else -1)
    else:return ('',None)
    if signed==0:return ('Push',0.0)
    if signed<0:return ('Loss',-1.0)
    o=float(x.odds_american)
    return ('Win',o/100 if o>0 else 100/-o)


settled=pd.read_sql_query('SELECT * FROM settlements',db)
quotes=pd.read_sql_query('SELECT * FROM market_quotes',db)
scored=pd.read_sql_query('SELECT * FROM model_scores',db)

graded=quotes.merge(settled[['game_key','final_away_score','final_home_score','result_source']],on='game_key',how='left')
results=graded.apply(grade,axis=1)
graded['graded_result']=[x[0] for x in results]
graded['hypothetical_unit_net']=[x[1] for x in results]
graded.to_csv(NEW/'exports/quote_outcomes.csv',index=False)
grade_by_quote=graded.set_index('quote_id')[['graded_result','hypothetical_unit_net']]
score_grading=scored.join(grade_by_quote,on='quote_id')
score_grading=score_grading.merge(settled[['game_key','final_away_score','final_home_score','result_source']],on='game_key',how='left')
score_grading.to_csv(NEW/'exports/model_score_outcomes.csv',index=False)

results_today=pd.read_csv(OUT/'NOV10_FINAL_RESULTS_ESPN.csv')
prev_results=pd.read_csv(ROOT/'recovered_sources/rolling_master_v27/exports/official_game_results.csv')
official=pd.concat([prev_results,results_today],ignore_index=True)
official=official.drop_duplicates(subset=['sport','espn_game_id'],keep='first')
official.to_csv(NEW/'exports/official_game_results.csv',index=False)

for table in ('settlements',):
    pd.read_sql_query(f'SELECT * FROM {table}',db).to_csv(NEW/f'exports/{table}.csv',index=False)
check=db.execute('PRAGMA integrity_check').fetchone()[0]
fk=db.execute('PRAGMA foreign_key_check').fetchall()
assert check=='ok' and not fk
db.close()

manifest=json.loads((NEW/'MANIFEST.json').read_text())
manifest['counts']['settlements']+=count
manifest['nov10_results_join']={'espn_finals':len(results_today),'matched_to_bovada_games':len(matches),
    'new_game_settlements':count,'unmatched_espn_games':len(results_today)-len(matches),
    'note':'Game score joins and quote outcomes are hypothetical, not actual wager P&L'}
(NEW/'MANIFEST.json').write_text(json.dumps(manifest,indent=2))
with (NEW/'README.md').open('a') as f:
    f.write('\n## November 11 append and November 10 finals\n\n')
    f.write(f'New Nov11 snapshot: 41 games, 246 main-market sides, 289 model score records. ESPN Nov10: {len(results_today)} finals, {len(matches)} matched to archived Bovada games, {count} new settlement keys. Sizing for unquoted parlays remains blocked.\n')
    f.write('The files `exports/quote_outcomes.csv` and `exports/model_score_outcomes.csv` are counterfactual grading of quotes, **not** real ticket returns.\n')

extra=[OUT/'NOV11_CANONICAL_SCORING_IMPORT.json',OUT/'NOV11_THEORETICAL_SAME_DAY_PARLAYS.csv',
       OUT/'NOV11_PRODUCTION_QUALIFIERS.csv',OUT/'NOV11_RESEARCH_ONLY_SIGNALS.csv',
       OUT/'NOV11_CROSS_SPORT_BET_SHEET_AND_PARLAY_RESEARCH.md',
       OUT/'NOV10_FINAL_RESULTS_ESPN.csv',OUT/'NOV10_MATCHED_FINALS_FOR_ROLLING_LEDGER.csv',
       OUT/'NOV10_UNMATCHED_ESPN_FINALS.csv']
archive=NEW/'GAMBLING_ROLLING_AUTHORITATIVE_QUOTES_AND_SCORES.zip'
backup=NEW/'_temporary_repacked.zip'
with zipfile.ZipFile(archive) as source,zipfile.ZipFile(OLD) as old,zipfile.ZipFile(backup,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=7) as dest:
    current={info.filename for info in source.infolist()}
    newroot={'README.md','MANIFEST.json','GAMBLING_ROLLING_SCORING_HISTORY.sqlite'}
    for info in source.infolist():
        if info.filename in newroot or info.filename.startswith('exports/'):
            path=NEW/info.filename
            if path.exists():dest.write(path,info.filename)
            else:dest.writestr(info,source.read(info.filename))
        else:dest.writestr(info,source.read(info.filename))
    for info in old.infolist():
        if info.filename not in current and info.filename not in {x.name for x in extra}:
            dest.writestr(info,old.read(info.filename))
    for path in extra:
        dest.write(path,f'nov11_research/{path.name}')
backup.replace(archive)

with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    assert 'results/NOV9_SETTLEMENTS_CANONICAL.json' in z.namelist()
    assert 'exports/model_score_outcomes.csv' in z.namelist()
    assert 'nov11_research/NOV11_THEORETICAL_SAME_DAY_PARLAYS.csv' in z.namelist()

print(json.dumps(dict(archive=str(archive),appended_results=count,total_results=int(manifest['counts']['settlements']),
    quote_outcomes=len(graded),score_outcomes=len(score_grading),official_game_results=len(official),
    integrity=check,foreign_key_violations=len(fk),archive_bytes=archive.stat().st_size),indent=2))
