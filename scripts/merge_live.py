from __future__ import annotations
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
import argparse,json
from radar_sanciones.collectors.common import merge_preserving_rich
ap=argparse.ArgumentParser(); ap.add_argument('--base',required=True); ap.add_argument('--live',required=True); ap.add_argument('--out',required=True); a=ap.parse_args()
def load(p):
    try:
        with open(p,encoding='utf-8') as f:return json.load(f)
    except FileNotFoundError:return []
base=load(a.base); live=load(a.live); merged=merge_preserving_rich(base,live)
with open(a.out,'w',encoding='utf-8') as f:json.dump(merged,f,ensure_ascii=False,separators=(',',':'))
print(json.dumps({'base':len(base),'live':len(live),'merged':len(merged)},ensure_ascii=False))
