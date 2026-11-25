"""Score Nov11 Bovada NBA matchups under frozen R4 champion and R3 challenger."""
from pathlib import Path
import csv,json,subprocess,sys
import pandas as pd

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'outputs/bovada_20261111_raw'
H=OUT/'NBA_HISTORY_THROUGH_20261110.csv'
rows=[r for r in csv.DictReader((OUT/'NBA_main_board.csv').open(newline=''))
      if r['start_central'][:10]=='2026-11-11' and r['pregame']=='True']
assert len(rows)==9
quotes=[]
for r in rows:
    away=r['away'].replace('L.A. Clippers','Los Angeles Clippers')
    home=r['home'].replace('L.A. Clippers','Los Angeles Clippers')
    q=['2026-11-11',away+' @ '+home,away,home]
    for k in ('away_spread_line','away_spread_odds','home_spread_odds','away_ml_odds','home_ml_odds','total_line','over_odds','under_odds'):
        assert r[k],(r['game'],k)
        q.append(float(r[k]))
    quotes.append(q)
qp=OUT/'NBA_QUOTES_20261111.json';qp.write_text(json.dumps(quotes,indent=2))
for lane,model in (
    ('R4_champion',ROOT/'recovered_sources/nba_r4_full/nba_previous_production_r4/production/nba.py'),
    ('R3_challenger',ROOT/'recovered_sources/nba_r3/nba_authoritative_r3/nba.py')):
    dest=OUT/'NBA_R4_R3_SCORE'/lane
    subprocess.run([sys.executable,str(model),'score','--quotes',str(qp),'--out',str(dest),'--history',str(H)],check=True)
    df=pd.read_csv(dest/'forecasts.csv')
    qualifying=df[df.Tier.isin(['A','B+','B'])&df.EV.gt(0)]
    print(lane,'ROWS',len(df),'QUALIFIED',len(qualifying))
    if len(qualifying):print(qualifying[['Game','Market','Selection','Odds','Tier','Model_P','EV','Full_Kelly','Adjusted_Kelly']].to_string(index=False))
