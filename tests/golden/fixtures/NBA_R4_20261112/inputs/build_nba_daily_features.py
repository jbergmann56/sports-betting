"""Generate the frozen NBA R4 daily feature CSV directly from a timestamped Bovada quote CSV.

Source historical results: NBA/r4_frozen/data/nba_history_through_2026-11-11.csv.
Outputs: NBA_V27_OCT29_FEATURES.csv and related model artifacts; NEVER invents result rows.
"""
import argparse,csv,json,subprocess,sys
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parent

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--quotes',default=str(ROOT.parent/'20261112_quotes.csv'));ap.add_argument('--date',default='2026-11-12');ap.add_argument('--output',default=str(ROOT/'output_20261112'));ns=ap.parse_args()
 rows=list(csv.DictReader(open(ns.quotes,newline='')))
 grp={}
 for r in rows:
  if r['sport']!='NBA':continue
  grp.setdefault(r['event_id'],{})[r['market'],r['side']]=r
 Q=[]
 for eid,gg in grp.items():
  if len(gg)!=6 or any(x['quote_status']!='OFFERED_PREGAME' for x in gg.values()):continue
  away,home=gg['Moneyline','Away']['description'].split(' @ ')
  day=datetime.fromisoformat(gg['Moneyline','Away']['start_utc'].replace('Z','+00:00')).astimezone(ZoneInfo('America/Chicago')).date().isoformat()
  if day!=ns.date:continue
  if any(x['snapshot_as_of_utc']>=x['start_utc'] for x in gg.values()):raise RuntimeError('Quote not pregame')
  get=lambda m,s,k:float(gg[m,s][k])
  tup=[day,away+' @ '+home,away,home,get('Spread','Away','line'),get('Spread','Away','odds_american'),get('Spread','Home','odds_american'),get('Moneyline','Away','odds_american'),get('Moneyline','Home','odds_american'),get('Total','Over','line'),get('Total','Over','odds_american'),get('Total','Under','odds_american')]
  Q.append(tup)
 dest=Path(ns.output)
 if dest.exists():raise FileExistsError('Do not overwrite immutable output: '+str(dest))
 dest.parent.mkdir(parents=True,exist_ok=True)
 qp=dest.parent/(ns.date+'_nba_quotes.json')
 qp.write_text(json.dumps(Q,indent=2))
 cmd=[sys.executable,str(ROOT/'r4_frozen/nba.py'),'score','--quotes',str(qp),'--history',str(ROOT/'r4_frozen/data/nba_history_through_2026-11-11.csv'),'--out',str(dest)]
 subprocess.run(cmd,check=True)
 print('Generated',dest/'NBA_V27_OCT29_FEATURES.csv','games',len(Q))
if __name__=='__main__':main()
