"""Recover posted Nov11 college basketball offers from individual Bovada game URLs."""
import concurrent.futures
import json
import subprocess
from pathlib import Path
root=Path('outputs/bovada_20261111_raw/cbb_events');root.mkdir(exist_ok=True,parents=True)
slugs=["loyola-chicago-air-force-202611111500","saint-joseph-s-south-florida-202611111500","north-carolina-a-t-east-carolina-202611111600","coll-charleston-temple-202611111830","southern-indiana-iu-indianapolis-202611111830","campbell-east-tennessee-state-202611111900","cornell-st-bonaventure-202611111900","james-madison-delaware-202611111900","kent-state-unc-wilmington-202611111900","marquette-michigan-16-202611111900","st-peter-s-south-carolina-202611111900","stony-brook-princeton-202611111900","william-mary-florida-atlantic-202611111900","wisconsin-milwaukee-indiana-state-202611111900","pepperdine-sam-houston-state-202611111930","jacksonville-state-houston-10-202611112000","oral-roberts-tulsa-202611112000","robert-morris-arkansas-12-202611112000","santa-clara-north-texas-202611112000","valparaiso-south-dakota-state-202611112000","cal-poly-grand-canyon-202611112100","lindenwood-nebraska-202611112100","nevada-uc-santa-barbara-202611112100"]
def fetch(slug):
    dest=root/(slug+'.json')
    url='https://www.bovada.lv/services/sports/event/v2/events/A/description/basketball/college-basketball/'+slug+'?lang=en'
    p=subprocess.run(['curl','-sSL','--compressed','--retry','2','--max-time','25','-w','%{http_code}','-o',str(dest),url],capture_output=True,text=True)
    try:n=sum(len(x.get('events',[])) for x in json.loads(dest.read_text()))
    except Exception:n=0
    return slug,p.stdout,n,dest.stat().st_size if dest.exists() else 0
with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
    for rec in pool.map(fetch,slugs):print(*rec)
