"""Fetch the five current Bovada league snapshots for November 11, 2026."""
import concurrent.futures
import datetime as dt
import json
import subprocess
from pathlib import Path

OUT=Path('outputs/bovada_20261111_raw');OUT.mkdir(exist_ok=True,parents=True)
LEAGUES={'NFL':'football/nfl','NCAAFB':'football/college-football',
         'NBA':'basketball/nba','NCAABB':'basketball/college-basketball','NHL':'hockey/nhl'}

def task(pair):
    sport,slug=pair
    url=f'https://www.bovada.lv/services/sports/event/v2/events/A/description/{slug}?lang=en'
    path=OUT/f'{sport}_league_raw.json'
    res=subprocess.run(['curl','-sSL','--compressed','--retry','2','--max-time','35','-w','%{http_code}',
         '-o',str(path),url],capture_output=True,text=True)
    return {'sport':sport,'http':res.stdout.strip(),'bytes':path.stat().st_size if path.exists() else 0,
       'captured_utc':dt.datetime.fromtimestamp(path.stat().st_mtime,dt.timezone.utc).isoformat() if path.exists() else None,
       'stderr':res.stderr[-160:]}

with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
    results=list(pool.map(task,LEAGUES.items()))
print(json.dumps(results,indent=2))
(OUT/'LEAGUE_CAPTURE_MANIFEST.json').write_text(json.dumps(results,indent=2))
