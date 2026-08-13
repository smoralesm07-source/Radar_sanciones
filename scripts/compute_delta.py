import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
"""Compara la corrida recién construida con el snapshot anterior.

Genera data/run_delta.json y anota first_seen_at / last_changed_at en events.json.
La comparación usa una huella estable de fuente, resolución, RUT, fecha y sujeto; no
usa el ID secuencial porque éste puede cambiar al reconstruir el dataset.
"""
import argparse, json, os, re, unicodedata
from datetime import datetime

ap=argparse.ArgumentParser()
ap.add_argument('--current', default='data')
ap.add_argument('--previous', default='data/_previous')
ap.add_argument('--out', default='data/run_delta.json')
a=ap.parse_args()

def load(path, default):
    try:
        with open(path, encoding='utf-8') as f: return json.load(f)
    except FileNotFoundError: return default

def norm(v):
    s=unicodedata.normalize('NFD', str(v or '')).encode('ascii','ignore').decode().lower()
    return re.sub(r'\s+',' ',re.sub(r'[^a-z0-9]+',' ',s)).strip()

def fp(e):
    rut=norm(e.get('rut') or e.get('rut_fuente'))
    identity=rut or norm(e.get('sujeto_fuente') or e.get('nombre_uaf'))
    return '|'.join([norm(e.get('supervisor')), norm(e.get('resolucion')), str(e.get('fecha') or ''), identity])


def name_id(v):
    x=norm(v)
    repl={
        ' sociedad anonima ':' sa ', ' limitada ':' ltda ', ' compania ':' cia ',
        ' administradora general de fondos ':' agf ',
    }
    x=' '+x+' '
    for a,b in repl.items(): x=x.replace(a,b)
    return ' '.join(x.split())

def same_prior_identity(cur, old):
    if norm(cur.get('supervisor'))!=norm(old.get('supervisor')): return False
    if norm(cur.get('resolucion'))!=norm(old.get('resolucion')): return False
    if str(cur.get('fecha') or '')!=str(old.get('fecha') or ''): return False
    cr=norm(cur.get('rut') or cur.get('rut_fuente')); orut=norm(old.get('rut') or old.get('rut_fuente'))
    if cr and orut: return cr==orut
    cn=name_id(cur.get('sujeto_fuente') or cur.get('nombre_uaf')); on=name_id(old.get('sujeto_fuente') or old.get('nombre_uaf'))
    return bool(cn and on and (cn==on or cn in on or on in cn))

def event_public(e):
    return {k:e.get(k) for k in ['id','fecha','supervisor','resolucion','rut','rut_fuente','nombre_uaf','sujeto_fuente','tipo_evento','estado','monto','unidad','categoria','laft_directo','actividad_uaf']}

def max_date(events, supervisor):
    xs=[e.get('fecha') or '' for e in events if e.get('supervisor')==supervisor]
    return max(xs) if xs else ''

cur_events=load(os.path.join(a.current,'events.json'),[])
cur_entities=load(os.path.join(a.current,'entities.json'),[])
cur_meta=load(os.path.join(a.current,'metadata.json'),{})
prev_events=load(os.path.join(a.previous,'events.json'),[])
prev_entities=load(os.path.join(a.previous,'entities.json'),[])
prev_meta=load(os.path.join(a.previous,'metadata.json'),{})
now=cur_meta.get('generated_at') or datetime.now().astimezone().isoformat()
prev_run=prev_meta.get('generated_at') or None

prev_by={fp(e):e for e in prev_events}
new_events=[]; updated=[]
watch=['estado','tipo_evento','monto','unidad','categoria','laft_directo','resumen','rut','actividad_uaf','resolution_url']
for e in cur_events:
    k=fp(e); old=prev_by.get(k)
    if old is None:
        candidates=[p for p in prev_events if same_prior_identity(e,p)]
        if len(candidates)==1: old=candidates[0]
    if old:
        e['first_seen_at']=old.get('first_seen_at') or prev_run or now
        diffs={field:{'before':old.get(field),'after':e.get(field)} for field in watch if old.get(field)!=e.get(field)}
        if diffs:
            e['last_changed_at']=now
            updated.append({'event':event_public(e),'changes':diffs})
        else:
            e['last_changed_at']=old.get('last_changed_at') or e['first_seen_at']
    else:
        e['first_seen_at']=now; e['last_changed_at']=now
        new_events.append(event_public(e))

with open(os.path.join(a.current,'events.json'),'w',encoding='utf-8') as f:
    json.dump(cur_events,f,ensure_ascii=False,separators=(',',':'))

prev_ent={x.get('rut'):x for x in prev_entities if x.get('rut')}
entity_changes=[]
for e in cur_entities:
    rut=e.get('rut'); old=prev_ent.get(rut)
    if not old: continue
    pcur=e.get('prioridad_provisional',0) or 0; pold=old.get('prioridad_provisional',0) or 0
    evcur=e.get('n_eventos',0) or 0; evold=old.get('n_eventos',0) or 0
    scur=e.get('n_supervisores',0) or 0; sold=old.get('n_supervisores',0) or 0
    lcur=e.get('eventos_laft_directo',0) or 0; lold=old.get('eventos_laft_directo',0) or 0
    if (pcur,pold,evcur,evold,scur,sold,lcur,lold) and (pcur!=pold or evcur!=evold or scur!=sold or lcur!=lold):
        entity_changes.append({'rut':rut,'nombre_uaf':e.get('nombre_uaf'),'actividad_uaf':e.get('actividad_uaf'),
            'priority_before':pold,'priority_after':pcur,'priority_delta':pcur-pold,
            'events_before':evold,'events_after':evcur,'supervisors_before':sold,'supervisors_after':scur,
            'laft_before':lold,'laft_after':lcur})

sources=sorted(set([e.get('supervisor') for e in cur_events if e.get('supervisor')]))
health=load(os.path.join(a.current,'source_health.json'),[])
health_by={x.get('source'):x for x in health}
source_status=[]
for s in sources:
    src_new=sum(1 for e in new_events if e.get('supervisor')==s)
    current_last=max_date(cur_events,s); previous_last=max_date(prev_events,s); h=health_by.get(s,{})
    source_status.append({'supervisor':s,'last_event_date':current_last,'previous_last_event_date':previous_last,
                          'new_events':src_new,'last_checked_at':h.get('checked_at') or now,
                          'pipeline_status':h.get('parse_status') or 'snapshot_processed',
                          'fetch_status':h.get('fetch_status'),'rows_seen':h.get('rows_seen',0),'events_emitted':h.get('events_emitted',0),'message':h.get('message','')})

status='bootstrap' if not prev_events else ('changed' if (new_events or updated or entity_changes) else 'unchanged')
delta={
    'version':'0.8','run_at':now,'previous_run_at':prev_run,'status':status,
    'counts':{'new_events':len(new_events),'updated_events':len(updated),'entity_changes':len(entity_changes),
              'new_entities':sum(1 for e in cur_entities if e.get('rut') and e.get('rut') not in prev_ent),
              'new_multisupervisor':sum(1 for x in entity_changes if x['supervisors_before']<2<=x['supervisors_after'])},
    'new_events':new_events,'updated_events':updated,'entity_changes':sorted(entity_changes,key=lambda x:x['priority_delta'],reverse=True),
    'source_status':source_status,
    'note':'El delta compara snapshots de datos capturados. La fecha de detección (first_seen_at) no sustituye la fecha del hecho regulatorio.'
}
os.makedirs(os.path.dirname(a.out) or '.',exist_ok=True)
with open(a.out,'w',encoding='utf-8') as f: json.dump(delta,f,ensure_ascii=False,indent=2)
print(json.dumps(delta['counts'],ensure_ascii=False))
