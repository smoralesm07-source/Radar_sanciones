from __future__ import annotations
import re
from .common import get_html, parse_date, absolutize, latest_date, soup, make_matcher

URL = "https://www.uaf.cl/es-cl/publicaciones-uaf/sanciones-ejecutoriadas"


def collect(registry: list[dict], since_year: int = 2020):
    html, health = get_html(URL); health.source = "UAF"
    if not html:
        return [], health.to_dict()
    match = make_matcher(registry)
    events=[]; rows_seen=0
    try:
        root=soup(html)
        for table in root.find_all("table"):
            headers=" ".join(th.get_text(" ", strip=True) for th in table.find_all("th"))
            if "ROL" not in headers.upper() or "PERSONA" not in headers.upper():
                continue
            year=None
            h3=table.find_previous(["h2","h3","h4"])
            if h3:
                m=re.search(r"(20\d{2})", h3.get_text(" ", strip=True)); year=int(m.group(1)) if m else None
            if year and year < since_year:
                continue
            prior={}
            for tr in table.find_all("tr"):
                tds=tr.find_all("td")
                if len(tds)<5: continue
                vals=[td.get_text(" ", strip=True) for td in tds]
                rows_seen += 1
                rol,name,sector,causal,date=vals[:5]
                if not rol: continue
                if name:
                    prior={"name":name,"sector":sector}
                else:
                    name=prior.get("name",""); sector=prior.get("sector","")
                d=parse_date(date)
                if not d or int(d[:4]) < since_year: continue
                link=tds[-1].find("a")
                resolution_url=absolutize(URL, link.get("href") if link else "")
                causal_norm=causal.lower()
                typ="Recurso de reposición" if "repos" in causal_norm else "Sanción ejecutoriada"
                e={"supervisor":"UAF","fecha":d,"resolucion":rol,"sujeto_fuente":name,"sector_fuente":sector,
                   "tipo_evento":typ,"estado":"Ejecutoriada" if typ=="Sanción ejecutoriada" else "Recurso publicado",
                   "monto":None,"unidad":"","categoria":"Cumplimiento ALA/CFT/FP","laft_directo":True,
                   "resumen":f"La UAF publicó {causal.lower() or 'un antecedente sancionatorio'} para {name}.",
                   "source_url":URL,"resolution_url":resolution_url,"event_group":"UAF sanciones ejecutoriadas","notes":"Captura automática desde tabla oficial UAF."}
                e.update(match(name=name))
                e["uaf_registro_actual"]="Sí" if e.get("rut") else "No encontrado / revisar"
                events.append(e)
        health.rows_seen=rows_seen; health.events_emitted=len(events); health.latest_event_date=latest_date(events)
        health.parse_status="ok" if events else "empty"
        if not events: health.message="La página respondió, pero no se emitieron eventos con el esquema esperado."
    except Exception as exc:
        health.parse_status="error"; health.message=f"{type(exc).__name__}: {exc}"
    return events, health.to_dict()
