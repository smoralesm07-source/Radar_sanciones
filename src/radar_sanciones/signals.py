from __future__ import annotations
from collections import defaultdict
from datetime import datetime

def derived_signals(events, as_of=None):
    """Señales explicables; no son score de culpabilidad ni riesgo LA/FT."""
    as_of=as_of or datetime.now().date()
    by=defaultdict(list)
    for e in events:
        if e.get('entity_id'): by[e['entity_id']].append(e)
    out=[]
    for entity,rows in by.items():
        sups={x.get('supervisor') for x in rows if x.get('supervisor')}
        recent=[]
        for x in rows:
            try:
                d=datetime.strptime(x.get('fecha',''),'%Y-%m-%d').date()
                if (as_of-d).days<=365: recent.append(x)
            except Exception: pass
        if len(rows)>=3: out.append({'entity_id':entity,'signal_type':'SAN-REPEAT','severity':'high','why_flagged':f'{len(rows)} eventos sancionatorios/regulatorios registrados.'})
        if len(sups)>=2: out.append({'entity_id':entity,'signal_type':'SAN-MULTI-AUTH','severity':'high','why_flagged':f'Eventos en {len(sups)} autoridades: {", ".join(sorted(sups))}.'})
        if any(x.get('laft_directo') for x in rows): out.append({'entity_id':entity,'signal_type':'SAN-ALA-CFT','severity':'high','why_flagged':'Existe al menos un evento clasificado como ALA/CFT directo.'})
        if len(recent)>=2: out.append({'entity_id':entity,'signal_type':'SAN-RECENT-CLUSTER','severity':'medium','why_flagged':f'{len(recent)} eventos en los últimos 12 meses.'})
    return out
