from __future__ import annotations
import argparse,json,subprocess,sys
from collections import defaultdict
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def load(p,default):
    try:return json.load(open(ROOT/p,encoding='utf-8'))
    except (FileNotFoundError,json.JSONDecodeError):return default

def dump(p,obj):
    q=ROOT/p;q.parent.mkdir(parents=True,exist_ok=True);json.dump(obj,open(q,'w',encoding='utf-8'),ensure_ascii=False,indent=2)

def run(*args):subprocess.check_call([sys.executable,*map(str,args)],cwd=ROOT)

def health_rollup(rows):
    g=defaultdict(list)
    for x in rows:
        if isinstance(x,dict) and x.get('source'):g[x['source']].append(x)
    out=[]
    for src,rr in g.items():
        status='ok';
        states=[str(x.get('parse_status') or '') for x in rr]
        if any('error' in x for x in states):status='error'
        elif any(('degrad' in x or 'empty' in x) for x in states):status='degraded'
        latest=max((x.get('latest_event_date') or '' for x in rr),default='')
        out.append({'source':src,'checked_at':max((x.get('checked_at') or '' for x in rr),default=''),'fetch_status':'ok' if any(x.get('fetch_status')=='ok' for x in rr) else (rr[-1].get('fetch_status') or 'unknown'),'parse_status':status,'rows_seen':sum(int(x.get('rows_seen') or 0) for x in rr),'events_emitted':sum(int(x.get('events_emitted') or 0) for x in rr),'latest_event_date':latest,'documents_read':sum(int(x.get('documents_read') or 0) for x in rr),'documents_cache_hit':sum(int(x.get('documents_cache_hit') or 0) for x in rr),'documents_failed':sum(int(x.get('documents_failed') or 0) for x in rr),'document_entities_emitted':sum(int(x.get('document_entities_emitted') or 0) for x in rr),'message':' | '.join(dict.fromkeys(x.get('message','') for x in rr if x.get('message')))[:1200]})
    return sorted(out,key=lambda x:x['source'])

ap=argparse.ArgumentParser();ap.add_argument('--from-year',type=int,default=2026);ap.add_argument('--to-year',type=int,default=2026);ap.add_argument('--sources',default='UAF,CMF,SCJ,SUSESO,SP');ap.add_argument('--bootstrap',action='store_true');a=ap.parse_args()
old_events=load('data/silver/sanction_events.json',[]);old_entities=load('data/silver/entities.json',[]);old_by={x.get('source_record_id'):x for x in old_events if x.get('source_record_id')};old_ent={x.get('entity_id') or x.get('rut'):x for x in old_entities}
run('scripts/backfill.py','--from-year',a.from_year,'--to-year',a.to_year,'--sources',a.sources)
run('scripts/rebuild_entities.py');run('scripts/build_interop.py');run('scripts/rebuild_coverage.py')
events=load('data/silver/sanction_events.json',[]);entities=load('data/silver/entities.json',[]);now=datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')
new=[x for x in events if x.get('source_record_id') not in old_by];watch=['estado','monto','unidad','categoria','laft_directo','resumen','resolution_url'];updated=[]
for x in events:
    old=old_by.get(x.get('source_record_id'))
    if not old:continue
    changes={k:{'before':old.get(k),'after':x.get(k)} for k in watch if old.get(k)!=x.get(k)}
    if changes:updated.append({'event':x,'changes':changes})
new_ent=[x for x in entities if (x.get('entity_id') or x.get('rut')) not in old_ent]
old_sup={k:int(v.get('n_supervisores') or 0) for k,v in old_ent.items()};new_multi=[x for x in entities if int(x.get('n_supervisores') or 0)>=2 and old_sup.get(x.get('entity_id') or x.get('rut'),0)<2]
health=health_rollup(load('data/operational/backfill_health.json',[]));dump('data/operational/source_health.json',health)
delta={'version':'0.8','run_at':now,'status':'bootstrap' if a.bootstrap else ('changed' if new or updated else 'unchanged'),'counts':{'new_events':len(new),'updated_events':len(updated),'entity_changes':0,'new_entities':len(new_ent),'new_multisupervisor':len(new_multi)},'new_events':new[:60],'updated_events':updated[:40],'entity_changes':[],'source_status':health,'note':'Fecha de detección del radar separada de la fecha del hecho regulatorio.'};dump('data/operational/run_delta.json',delta)
hist=load('data/operational/run_history.json',[]);hist.append({'run_at':now,'status':delta['status'],'from_year':a.from_year,'to_year':a.to_year,'sources':a.sources.split(','),'events_total':len(events),'new_events':len(new),'updated_events':len(updated),'source_health':{x['source']:x['parse_status'] for x in health}});dump('data/operational/run_history.json',hist[-30:])
years=[int(str(x.get('fecha'))[:4]) for x in events if str(x.get('fecha') or '')[:4].isdigit()]
meta=load('data/gold/metadata.json',{});meta.update({'version':'0.8.0','generated_at':now,'target_from_year':2020,'bootstrap_pending':False,'event_count':len(events),'entity_count':len(entities),'current_data_from_year':min(years) if years else None,'latest_event_date':max((x.get('fecha') or '' for x in events),default='')});dump('data/gold/metadata.json',meta);dump('data/gold/backfill_state.json',{'target_from_year':2020,'last_backfill_at':now,'last_from_year':a.from_year,'last_to_year':a.to_year,'sources':a.sources.split(','),'status':'partial_until_validated'})
run('scripts/publish.py');print(json.dumps({'events':len(events),'entities':len(entities),'new':len(new),'updated':len(updated)},ensure_ascii=False))
