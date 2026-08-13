from __future__ import annotations
import re
from .common import get_html, parse_date, absolutize, latest_date, soup, make_matcher

ARCHIVE="https://www.spensiones.cl/portal/institucional/594/w3-propertyvalue-5901.html"
PROFILE_URLS={
 "AFP Capital":"https://www.spensiones.cl/portal/institucional/594/w3-propertyvalue-9976.html",
 "AFP Habitat":"https://www.spensiones.cl/portal/institucional/594/w3-propertyvalue-9978.html",
 "AFP Modelo":"https://www.spensiones.cl/portal/institucional/594/w3-propertyvalue-9979.html",
 "AFP PlanVital":"https://www.spensiones.cl/portal/institucional/594/w3-propertyvalue-9980.html",
 "AFP Provida":"https://www.spensiones.cl/portal/institucional/594/w3-propertyvalue-9981.html",
}

def collect(registry:list[dict], since_year:int=2020):
    match=make_matcher(registry); events=[]
    html,health=get_html(ARCHIVE); health.source="SP"; rows_seen=0
    if html:
        try:
            root=soup(html)
            for a in root.find_all("a", href=True):
                title=a.get_text(" ",strip=True)
                low=title.lower()
                if not title or not re.search(r"\b(multa|multas|sanciona|sanciones)\b",low): continue
                rows_seen+=1
                url=absolutize(ARCHIVE,a.get("href"))
                if "afp" not in low: continue
                e={"supervisor":"SP","fecha":"","resolucion":"","sujeto_fuente":"Industria AFP","sector_fuente":"Administradoras de Fondos de Pensiones",
                   "tipo_evento":"Comunicado sancionatorio","estado":"Publicado","monto":None,"unidad":"UF","categoria":"Cumplimiento previsional",
                   "laft_directo":False,"resumen":title,"source_url":url,"resolution_url":"","event_group":"SP noticias sancionatorias",
                   "notes":"Alerta de cobertura. Requiere desagregación por AFP desde el comunicado o resolución."}
                events.append(e)
            health.parse_status="ok" if rows_seen else "empty"
        except Exception as exc:
            health.parse_status="error"; health.message=f"{type(exc).__name__}: {exc}"
    else:
        health.parse_status="not_run"

    for label,url in PROFILE_URLS.items():
        phtml,ph=get_html(url)
        if not phtml: continue
        try:
            root=soup(phtml)
            txt=root.get_text(" ",strip=True)
            rutm=re.search(r"RUT\s+([0-9\.\-Kk]+)",txt)
            rut=rutm.group(1) if rutm else ""
            for tr in root.find_all("tr"):
                tds=tr.find_all("td")
                if len(tds)<4: continue
                vals=[td.get_text(" ",strip=True) for td in tds]
                d=parse_date(vals[0])
                if not d or int(d[:4])<since_year: continue
                rows_seen+=1
                links=[absolutize(url,a.get("href")) for a in tr.find_all("a") if a.get("href")]
                e={"supervisor":"SP","fecha":d,"resolucion":vals[1],"sujeto_fuente":label,"sector_fuente":"Administradoras de Fondos de Pensiones",
                   "tipo_evento":"Sanción","estado":"Publicado","monto":None,"unidad":"UF" if "UF" in vals[2].upper() else "",
                   "categoria":"Cumplimiento previsional","laft_directo":False,"resumen":vals[3],"source_url":url,"resolution_url":links[-1] if links else "",
                   "event_group":"SP ficha AFP","notes":"Captura automática desde ficha pública de AFP."}
                e.update(match(name=label,rut=rut)); e["uaf_registro_actual"]="Sí" if e.get("rut") else "No encontrado / revisar"
                events.append(e)
        except Exception:
            pass
    health.rows_seen=rows_seen; health.events_emitted=len(events); health.latest_event_date=latest_date(events)
    if health.fetch_status=="ok" and health.parse_status=="ok" and not any(e.get("fecha") for e in events):
        health.parse_status="degraded"; health.message="Archivo de noticias accesible, pero la desagregación reciente por AFP requiere enriquecer comunicados/resoluciones."
    return events,health.to_dict()
