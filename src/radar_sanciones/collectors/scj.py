from __future__ import annotations
import re
from .common import get_html, parse_date, absolutize, latest_date, soup, make_matcher

URL="https://www.scj.gob.cl/proceso-sancionatorio/"

def collect(registry:list[dict], since_year:int=2020):
    html,health=get_html(URL); health.source="SCJ"
    if not html: return [],health.to_dict()
    match=make_matcher(registry); events=[]; rows_seen=0
    try:
        root=soup(html)
        for tr in root.find_all("tr"):
            tds=tr.find_all("td")
            if len(tds)<3: continue
            vals=[td.get_text(" ",strip=True) for td in tds]
            d=parse_date(vals[0])
            if not d or int(d[:4])<since_year: continue
            rows_seen+=1
            name=vals[1]
            cargos=vals[2] if len(vals)>2 else ""
            sancion=vals[3] if len(vals)>3 else ""
            outcome=vals[4] if len(vals)>4 else ""
            text=" | ".join(x for x in [cargos,sancion,outcome] if x and x!="-")
            links=[absolutize(URL,a.get("href")) for a in tr.find_all("a") if a.get("href")]
            resm=re.search(r"Resoluci[oó]n Exenta N[°º]\s*([0-9]+)", sancion, re.I)
            typ="Sanción / término de procedimiento" if sancion and sancion!="-" else "Formulación de cargos"
            status="Sancionado / resuelto" if sancion and sancion!="-" else "Cargos formulados"
            e={"supervisor":"SCJ","fecha":d,"resolucion":resm.group(1) if resm else "","sujeto_fuente":name,
               "sector_fuente":"Casinos de Juego","tipo_evento":typ,"estado":status,"monto":None,"unidad":"UTM" if "UTM" in text else "",
               "categoria":"Procedimiento sancionatorio casino","laft_directo":bool(re.search(r"lavado|debida diligencia|uaf",text,re.I)),
               "resumen":text or cargos,"source_url":URL,"resolution_url":links[-1] if links else "","event_group":"SCJ proceso sancionatorio",
               "notes":"Captura automática desde registro de procesos SCJ."}
            e.update(match(name=name)); e["uaf_registro_actual"]="Sí" if e.get("rut") else "No encontrado / revisar"
            events.append(e)
        health.rows_seen=rows_seen; health.events_emitted=len(events); health.latest_event_date=latest_date(events); health.parse_status="ok" if events else "empty"
    except Exception as exc:
        health.parse_status="error"; health.message=f"{type(exc).__name__}: {exc}"
    return events,health.to_dict()


def collect_historical(registry:list[dict], from_year:int=2020, to_year:int|None=None, max_pages:int=20):
    from datetime import datetime
    to_year = to_year or datetime.now().year
    match=make_matcher(registry); out=[]; health_rows=[]
    seen=set()
    for page in range(1,max_pages+1):
        url=URL if page==1 else f"{URL}page/{page}/"
        html,h=get_html(url); h.source='SCJ'
        if not html:
            health_rows.append(h.to_dict()); continue
        root=soup(html); page_years=[]; emitted=0
        for tr in root.find_all('tr'):
            tds=tr.find_all('td')
            if len(tds)<3: continue
            vals=[td.get_text(' ',strip=True) for td in tds]
            d=parse_date(vals[0])
            if not d: continue
            y=int(d[:4]); page_years.append(y)
            if y<from_year or y>to_year: continue
            name=vals[1]; cargos=vals[2] if len(vals)>2 else ''; sancion=vals[3] if len(vals)>3 else ''; outcome=vals[4] if len(vals)>4 else ''
            text=' | '.join(x for x in [cargos,sancion,outcome] if x and x!='-')
            links=[absolutize(url,a.get('href')) for a in tr.find_all('a') if a.get('href')]
            resm=re.search(r"Resoluci[oó]n Exenta N[°º]\s*([0-9]+)", sancion, re.I)
            typ='Sanción / término de procedimiento' if sancion and sancion!='-' else 'Formulación de cargos'
            e={'supervisor':'SCJ','fecha':d,'resolucion':resm.group(1) if resm else '', 'sujeto_fuente':name,'sector_fuente':'Casinos de Juego','tipo_evento':typ,'estado':'Sancionado / resuelto' if sancion and sancion!='-' else 'Cargos formulados','monto':None,'unidad':'UTM' if 'UTM' in text else '', 'categoria':'Procedimiento sancionatorio casino','laft_directo':bool(re.search(r'lavado|debida diligencia|uaf',text,re.I)),'resumen':text or cargos,'source_url':url,'resolution_url':links[-1] if links else '', 'event_group':'SCJ proceso sancionatorio','notes':'Backfill histórico desde registro paginado SCJ.'}
            e.update(match(name=name)); e['uaf_registro_actual']='Sí' if e.get('rut') else 'No encontrado / revisar'
            key=(d,name,e['resolucion'],typ)
            if key not in seen: seen.add(key); out.append(e); emitted+=1
        h.rows_seen=len(page_years); h.events_emitted=emitted; h.latest_event_date=latest_date(out); h.parse_status='ok'
        health_rows.append(h.to_dict())
        if page_years and min(page_years)<from_year: break
    return out, health_rows
