"""Recover three posted Wednesday Bovada CFB matches from exact event URLs."""
import concurrent.futures
import subprocess
from pathlib import Path
out=Path('outputs/bovada_20261111_raw/cfb_events');out.mkdir(exist_ok=True,parents=True)
slugs=['buffalo-ball-state-202611111930',
       'massachusetts-toledo-202611111930',
       'sacramento-state-central-michigan-202611111930']
def fetch(slug):
    p=out/(slug+'.json')
    url='https://www.bovada.lv/services/sports/event/v2/events/A/description/football/college-football/'+slug+'?lang=en'
    r=subprocess.run(['curl','-sSL','--compressed','--retry','2','--max-time','25','-w','%{http_code}','-o',str(p),url],capture_output=True,text=True)
    return slug,r.stdout,p.stat().st_size if p.exists() else 0
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
    for row in pool.map(fetch,slugs):print(*row)
