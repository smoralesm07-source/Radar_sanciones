from __future__ import annotations
import argparse,json,re,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/'src'))
from radar_sanciones.collectors import uaf,cmf,scj,suseso,sp
from radar_sanciones.collectors.common import merge_preserving_rich,norm
from radar_sanciones.model import entity_id,evidence_id

ap=argparse.ArgumentParser(description='Backfill histórico Radar de Sanciones')
ap.add_argument('--from-year',type=int,default=2020); ap.add_argument('--to-year',type=int,default=2026)
ap.add_argument('--sources',default='UAF,CMF,SCJ,SUSESO,SP'); ap.add_argument('--registry',default='data/silver/uaf_registry.json')
a=ap.parse_args(); registry=json.load(open(a.registry,encoding='utf-8'))
mods={'UAF':uaf,'CMF':cmf,'SUSESO':suseso,'SP':sp}; all_events=[]; health=[]
for src in [x.strip().upper() for x in a.sources.split(',') if x.strip()]:
    if src=='SCJ': ev,hh=scj.collect_historical(registry,a.from_year,a.to_year); all_events+=ev; health+=hh; continue
    mod=mods.get(src)
    if not mod: continue
    ev,h=mod.collect(registry,a.from_year); ev=[e for e in ev if not e.get('fecha') or int(e['fecha'][:4])<=a.to_year]; all_events+=ev; health.append(h)
base_path=ROOT/'data/silver/sanction_events.json'; base=json.load(open(base_path,encoding='utf-8')) if base_path.exists() else []
merged=merge_preserving_rich(base,all_events)
for e in merged:
    rut=e.get('rut') or e.get('rut_fuente') or ''
    name=e.get('nombre_uaf') or e.get('sujeto_fuente') or ''
    e['entity_id']=entity_id(rut,name)
    ident=re.sub(r'[^A-Z0-9]+','-',(rut or norm(name))).strip('-')[:60]
    e['source_record_id']=':'.join([str(e.get('supervisor') or 'SRC'),str(e.get('resolucion') or 'SIN-RES'),str(e.get('fecha') or 'SIN-FECHA'),ident or 'SIN-ID'])
    e['evidence_id']=evidence_id(e['source_record_id'])
    try:e['decision_year']=int(str(e.get('fecha') or '')[:4])
    except:e['decision_year']=None
    e['is_2020_plus']=bool(e.get('decision_year') and e['decision_year']>=2020)
json.dump(merged,open(base_path,'w',encoding='utf-8'),ensure_ascii=False,indent=2)
json.dump(health,open(ROOT/'data/operational/backfill_health.json','w',encoding='utf-8'),ensure_ascii=False,indent=2)
print(json.dumps({'captured':len(all_events),'merged':len(merged),'from_year':a.from_year,'to_year':a.to_year},ensure_ascii=False))
