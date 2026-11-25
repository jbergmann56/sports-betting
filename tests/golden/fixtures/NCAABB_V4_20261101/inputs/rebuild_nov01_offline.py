"""Restore the exact original bookmaker capture timestamp before invoking the unchanged source builder.
ZIP extraction does not preserve the source file mtime, but original build inferred its timestamp from it.
"""
from pathlib import Path
from datetime import datetime
import json,os,subprocess,sys
root=Path(__file__).resolve().parent/'nov01_v4_inputs'
meta=json.loads((root/'manifest.json').read_text())
raw=root/'bovada_raw.json'
assert meta['captured_utc']=='2026-11-01T20:34:07.379540+00:00','Unexpected historical capture'
ts=datetime.fromisoformat(meta['captured_utc']).timestamp()
os.utime(raw,(ts,ts))
subprocess.run([sys.executable,str(root/'prepare_and_score.py')],cwd=root,check=True)
