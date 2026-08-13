from __future__ import annotations
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/'src'))
import argparse,json,os,re
from collections import defaultdict
ap=argparse.ArgumentParser(); ap.add_argument('--events',default='data/silver/sanction_events.json'); ap.add_argument('--registry',default='data/silver/uaf_registry.json'); ap.add_argument('--sii',default='data/silver/sii_entities.json'); ap.add_argument('--out',default='data/silver/entities.json'); a=ap.parse_args()
events=json.load(open(a.events,encoding='utf-8')); registry=json.load(open(a.registry,encoding='utf-8'))
sii={}
if os.path.exists(a.sii): sii=json.load(open(a.sii,encoding='utf-8'))
by_rut={x.get('rut'):x for x in registry if x.get('rut')}; g=defaultdict(list)
for e in events:
    rut=e.get('rut') or e.get('rut_fuente')
    if rut:g[rut].append(e)
rows=[]
for rut,ev in g.items():
    base=by_rut.get(rut,{}); sups=sorted({x.get('supervisor') for x in ev if x.get('supervisor')}); laft=sum(1 for x in ev if x.get('laft_directo'))
    uf=sum(float(x.get('monto') or 0) for x in ev if str(x.get('unidad') or '').upper()=='UF'); utm=sum(float(x.get('monto') or 0) for x in ev if str(x.get('unidad') or '').upper()=='UTM')
    cats=sorted({x.get('categoria') for x in ev if x.get('categoria')}); sig=[]
    if laft:sig.append('SAN-ALA-CFT')
    if len(ev)>=3:sig.append('SAN-REPEAT')
    if len(sups)>=2:sig.append('SAN-MULTI-AUTH')
    txt=' '.join((x.get('categoria') or '')+' '+(x.get('resumen') or '') for x in ev).lower()
    if 'beneficiario final' in txt or 'debida diligencia' in txt:sig.append('REG-10 DDC/beneficiario final')
    score=min(100,laft*25+(20 if len(sups)>=2 else 0)+min(max(len(ev)-1,0),4)*8+(10 if uf>=1000 else (5 if uf>0 else 0)))
    key=re.sub(r'[^0-9Kk]','',rut).upper(); se=sii.get(key,{}) or sii.get(rut,{})
    rows.append({'entity_id':ev[0].get('entity_id'),'rut':rut,'nombre_uaf':base.get('nombre') or ev[0].get('nombre_uaf') or ev[0].get('sujeto_fuente'),
      'actividad_uaf':base.get('actividad') or ev[0].get('actividad_uaf') or ev[0].get('sector_fuente') or '', 'n_eventos':len(ev),'supervisores':', '.join(sups),'n_supervisores':len(sups),
      'fecha_ultimo_evento':max((x.get('fecha') or '' for x in ev),default=''),'eventos_laft_directo':laft,'uf_conocidas':round(uf,2),'utm_conocidas':round(utm,2),
      'senal_inicial':'; '.join(sig),'categorias':' | '.join(cats),'sii_estado_enriquecimiento':'Cargado' if se else 'Pendiente carga masiva TXT SII',
      'sii_actividades_vigentes':se.get('sii_actividades_raw',[]),'sii_nombre_raw':se.get('sii_nombre_raw',[]),'sii_empresas_raw':se.get('sii_empresas_raw',[]),
      'prioridad_provisional':score,'banda_prioridad':'Alta' if score>=70 else ('Media' if score>=40 else 'Baja')})
rows.sort(key=lambda x:(x['fecha_ultimo_evento'],x['prioridad_provisional']),reverse=True)
json.dump(rows,open(a.out,'w',encoding='utf-8'),ensure_ascii=False,indent=2); print(json.dumps({'entities':len(rows)},ensure_ascii=False))
