from __future__ import annotations
from .common import get_html, parse_date, absolutize, latest_date, soup, make_matcher

URL="https://www.suseso.gob.cl/609/w3-propertyvalue-806511.html"

def collect(registry:list[dict], since_year:int=2020):
    html,health=get_html(URL); health.source="SUSESO"
    if not html: return [],health.to_dict()
    match=make_matcher(registry); events=[]; rows_seen=0
    try:
        root=soup(html)
        for tr in root.find_all("tr"):
            tds=tr.find_all("td")
            if len(tds)<6: continue
            vals=[td.get_text(" ",strip=True) for td in tds]
            d=parse_date(vals[0]); name=vals[1] if len(vals)>1 else ""
            if not d or int(d[:4])<since_year or not name: continue
            rows_seen+=1
            m=match(name=name)
            if not m: continue
            resolution=vals[2] if len(vals)>2 else ""; sanction=vals[3] if len(vals)>3 else ""; infraction=vals[4] if len(vals)>4 else ""
            state=vals[5] if len(vals)>5 else ""; resource=vals[6] if len(vals)>6 else ""; resolution_type=vals[7] if len(vals)>7 else ""
            links=[absolutize(URL,a.get("href")) for a in tr.find_all("a") if a.get("href")]
            e={"supervisor":"SUSESO","fecha":d,"resolucion":resolution,"sujeto_fuente":name,"tipo_evento":"Sanción",
               "estado":state or resolution_type or "Publicado","monto":None,"unidad":"","categoria":"Cumplimiento sectorial / seguridad social",
               "laft_directo":False,"resumen":" · ".join(x for x in [sanction,infraction] if x),"source_url":URL,"resolution_url":links[-1] if links else "",
               "event_group":"SUSESO registro de sanciones","notes":("Recurso: "+resource) if resource else "Captura automática SUSESO."}
            e.update(m); e["uaf_registro_actual"]="Sí"
            events.append(e)
        health.rows_seen=rows_seen; health.events_emitted=len(events); health.latest_event_date=latest_date(events); health.parse_status="ok" if rows_seen else "empty"
        if rows_seen and not events: health.message="Registro accesible, pero ningún registro reciente enlazó conservadoramente con el padrón UAF."
    except Exception as exc:
        health.parse_status="error"; health.message=f"{type(exc).__name__}: {exc}"
    return events,health.to_dict()
