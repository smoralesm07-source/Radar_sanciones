from __future__ import annotations
import os
import re
from .common import get_html, parse_date, absolutize, latest_date, soup, make_matcher, norm_rut
from .cmf_document_agent import analyze_resolution, load_cache, save_cache, AGENT_VERSION

URL = "https://www.cmfchile.cl/institucional/sanciones/sanciones_mercados_entidad.php"
CACHE_DEFAULT = "data/cmf_document_cache.json"

PREFIXES = [
    r"APLICA SANCI[ÓO]N DE MULTA A\s+", r"APLICA SANCI[ÓO]N A\s+", r"APLICA SANCI[ÓO]N DE CENSURA A\s+",
    r"RESUELVE REPOSICI[ÓO]N DEDUCIDA POR\s+", r"RESUELVE REPOSICI[ÓO]N DE\s+", r"APLICA MULTA A\s+"
]


def subject_from_title(title:str)->str:
    s=title.strip().rstrip(".")
    for p in PREFIXES:
        s2=re.sub(p,"",s,flags=re.I)
        if s2!=s: s=s2; break
    s=re.split(r"\s+EN CONTRA DE\s+|\s+POR INFRACCI|\s+Y CIERRA\s+",s,flags=re.I)[0]
    return s.strip()


def _doc_enabled(document_mode: bool | None) -> bool:
    if document_mode is not None:
        return bool(document_mode)
    return os.getenv("RADAR_CMF_DOCUMENTS", "1").strip().lower() not in {"0","false","no","off"}


def _doc_candidate(title: str, url: str) -> bool:
    if not url:
        return False
    t = title.upper()
    return any(x in t for x in ("SANCIÓN", "SANCION", "MULTA", "CENSURA", "REPOSICIÓN", "REPOSICION"))


def _subject_event(base: dict, subj: dict, analysis: dict, registry: list[dict]) -> dict | None:
    match = make_matcher(registry)
    name = str(subj.get("name") or "").strip()
    rut_source = str(subj.get("rut") or "").strip()
    matched = match(name=name, rut=rut_source)
    if subj.get("subject_kind") != "legal_entity" and not matched.get("rut"):
        return None

    e = dict(base)
    e["sujeto_fuente"] = name or base.get("sujeto_fuente", "")
    e["rut_fuente"] = rut_source
    e.update(matched)
    e["uaf_registro_actual"] = "Sí" if e.get("rut") else "No encontrado / revisar"
    e["monto"] = subj.get("monto")
    e["unidad"] = subj.get("unidad") or ""
    e["categoria"] = subj.get("category") or "Pendiente de clasificación detallada"
    e["laft_directo"] = bool(subj.get("laft_directo"))
    e["document_status"] = analysis.get("status")
    e["document_confidence"] = subj.get("confidence") or analysis.get("confidence") or 0
    e["document_subject_count"] = analysis.get("subject_count", 0)
    e["document_entity_count"] = analysis.get("legal_entity_count", 0)
    e["document_page_entity"] = subj.get("page_entity")
    e["document_page_sanction"] = subj.get("page_sanction")
    e["document_page_infraction"] = subj.get("page_infraction")
    e["document_analysis_version"] = analysis.get("agent_version") or AGENT_VERSION
    e["document_pdf_sha256"] = analysis.get("pdf_sha256", "")
    e["needs_pdf_enrichment"] = analysis.get("status") != "enriched" or not subj.get("sanction_text")

    legal = [x for x in analysis.get("subjects", []) if x.get("subject_kind") == "legal_entity"]
    e["other_entities_in_resolution"] = [
        {"name":x.get("name"),"rut":x.get("rut"),"sanction":x.get("sanction_text")}
        for x in legal if norm_rut(x.get("rut")) != norm_rut(rut_source)
    ]
    e["related_subjects"] = [
        {"name":x.get("name"),"rut":x.get("rut"),"kind":x.get("subject_kind")}
        for x in analysis.get("subjects", []) if x.get("subject_kind") != "legal_entity"
    ]

    sanction = subj.get("sanction_text") or "sanción no extraída"
    inf = re.sub(r"\s+", " ", str(subj.get("infraction_excerpt") or "")).strip()
    if inf:
        if len(inf) > 360:
            inf = inf[:357].rstrip() + "…"
        e["resumen"] = f"La resolución CMF N°{e.get('resolucion')} individualiza a {name} (RUT {rut_source}). Sanción: {sanction}. Hecho/cargo extraído: {inf}"
    else:
        e["resumen"] = f"La resolución CMF N°{e.get('resolucion')} individualiza a {name} (RUT {rut_source}). Sanción: {sanction}. Materia clasificada: {e['categoria']}."
    pages = []
    if subj.get("page_entity"): pages.append(f"entidad p.{subj['page_entity']}")
    if subj.get("page_sanction"): pages.append(f"sanción p.{subj['page_sanction']}")
    if subj.get("page_infraction"): pages.append(f"hecho/cargo p.{subj['page_infraction']}")
    e["notes"] = f"{AGENT_VERSION}: resolución oficial leída automáticamente" + (f" ({', '.join(pages)})." if pages else ".")
    return e


def collect(registry:list[dict], since_year:int=2020, document_mode: bool | None=None):
    html,health=get_html(URL); health.source="CMF"
    if not html: return [],health.to_dict()
    match=make_matcher(registry); events=[]; rows_seen=0
    doc_mode = _doc_enabled(document_mode)
    cache_path = os.getenv("RADAR_CMF_CACHE", CACHE_DEFAULT)
    cache = load_cache(cache_path) if doc_mode else {}
    max_docs = int(os.getenv("RADAR_CMF_MAX_DOCS", "35"))
    docs_this_run = 0
    cache_dirty = False
    try:
        root=soup(html)
        for tr in root.find_all("tr"):
            tds=tr.find_all("td")
            if len(tds)<3: continue
            vals=[td.get_text(" ",strip=True) for td in tds]
            if not re.fullmatch(r"\d+", vals[0].replace(".","")): continue
            res=vals[0]; d=parse_date(vals[1]); title=vals[2]
            if not d or int(d[:4])<since_year: continue
            rows_seen+=1
            subject=subject_from_title(title)
            link=tds[-1].find("a")
            url=absolutize(URL, link.get("href") if link else "")
            low=title.lower()
            typ="Recurso de reposición" if "reposici" in low else ("Censura" if "censura" in low else "Sanción")
            generic=bool(re.search(r"QUE INDICA|SOCIEDADES|ADMINISTRADORAS", title, re.I))
            base={"supervisor":"CMF","fecha":d,"resolucion":res,"sujeto_fuente":subject,
               "tipo_evento":typ,"estado":"Publicado","monto":None,"unidad":"","categoria":"Pendiente de clasificación detallada",
               "laft_directo":False,"resumen":title,"source_url":URL,"resolution_url":url,"event_group":"CMF resoluciones sancionatorias",
               "source_title":title,"notes":"Captura automática de índice CMF.","needs_pdf_enrichment":True}

            used_document = False
            if doc_mode and _doc_candidate(title, url):
                health.documents_requested += 1
                cached = str(res) in cache and cache[str(res)].get("analysis")
                if cached or generic or docs_this_run < max_docs:
                    if not cached:
                        docs_this_run += 1
                    analysis,msg,cache_hit = analyze_resolution(url,res,cache,force=False)
                    if cache_hit:
                        health.documents_cache_hit += 1
                    elif analysis:
                        health.documents_read += 1; cache_dirty = True
                    else:
                        health.documents_failed += 1
                    if analysis:
                        children=[]
                        for subj in analysis.get("subjects",[]):
                            child=_subject_event(base,subj,analysis,registry)
                            if child:
                                children.append(child)
                        if children:
                            health.document_entities_emitted += len(children)
                            events.extend(children)
                            used_document=True
                        else:
                            base["document_status"] = analysis.get("status")
                            base["document_confidence"] = analysis.get("confidence")
                            base["document_subject_count"] = analysis.get("subject_count",0)
                            base["document_entity_count"] = analysis.get("legal_entity_count",0)
                            base["notes"] += f" {AGENT_VERSION}: documento leído, pero no se individualizó una entidad jurídica emitible."
                    elif msg:
                        base["notes"] += f" {AGENT_VERSION}: {msg}."
                else:
                    base["document_status"]="queued"
                    base["notes"] += f" {AGENT_VERSION}: en cola de lectura documental por límite de {max_docs} documentos/corrida."

            if used_document:
                continue
            if not generic:
                base.update(match(name=subject))
            base["uaf_registro_actual"]="Sí" if base.get("rut") else "No encontrado / revisar"
            events.append(base)

        if doc_mode and cache_dirty:
            save_cache(cache_path,cache)
        health.rows_seen=rows_seen; health.events_emitted=len(events); health.latest_event_date=latest_date(events)
        health.parse_status="ok" if events else "empty"
        if doc_mode:
            health.message=(f"Agente documental CMF activo: {health.documents_read} PDF nuevos leídos, "
                            f"{health.documents_cache_hit} desde cache, {health.documents_failed} fallidos; "
                            f"{health.document_entities_emitted} eventos individualizados desde documentos.")
    except Exception as exc:
        health.parse_status="error"; health.message=f"{type(exc).__name__}: {exc}"
    return events,health.to_dict()
