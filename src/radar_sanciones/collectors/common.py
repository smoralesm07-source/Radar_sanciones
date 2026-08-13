from __future__ import annotations
import hashlib, json, re, unicodedata
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

UA = "RadarSancionesOSINT/0.8 (+GitHub Actions; open-source-monitor)"

@dataclass
class SourceHealth:
    source: str
    checked_at: str
    url: str
    http_status: int | None = None
    fetch_status: str = "error"
    parse_status: str = "not_run"
    rows_seen: int = 0
    events_emitted: int = 0
    latest_event_date: str = ""
    content_sha256: str = ""
    message: str = ""
    mode: str = "live"
    documents_requested: int = 0
    documents_read: int = 0
    documents_cache_hit: int = 0
    documents_failed: int = 0
    document_entities_emitted: int = 0

    def to_dict(self):
        return asdict(self)


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def norm(v: object) -> str:
    s = unicodedata.normalize("NFD", str(v or "")).encode("ascii", "ignore").decode().upper()
    s = re.sub(r"\b(SOCIEDAD|ADMINISTRADORA|COMPANIA|COMPAÑIA|EMPRESA|INVERSIONES)\b", " ", s)
    s = re.sub(r"\b(SA|S A|SPA|LTDA|LIMITADA|EIRL)\b", " ", s)
    return re.sub(r"[^A-Z0-9]+", " ", s).strip()


def norm_rut(v: object) -> str:
    s = re.sub(r"[^0-9Kk]", "", str(v or "")).upper()
    return s


def parse_date(text: object) -> str:
    s = str(text or "").strip()
    if not s:
        return ""
    for fmt in ("%d.%m.%Y", "%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    m = re.search(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", s)
    if m:
        d, mo, y = map(int, m.groups())
        try:
            return datetime(y, mo, d).strftime("%Y-%m-%d")
        except ValueError:
            return ""
    return ""


def absolutize(base: str, href: str | None) -> str:
    return urljoin(base, href or "") if href else ""


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def get_html(url: str, timeout: int = 35) -> tuple[str, SourceHealth]:
    h = SourceHealth(source="", checked_at=now_iso(), url=url)
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": UA, "Accept-Language": "es-CL,es;q=0.9"})
        h.http_status = r.status_code
        h.content_sha256 = sha256_bytes(r.content)
        if r.ok:
            h.fetch_status = "ok"
            return r.text, h
        h.fetch_status = "http_error"
        h.message = f"HTTP {r.status_code}"
    except Exception as exc:
        h.fetch_status = "error"
        h.message = f"{type(exc).__name__}: {exc}"
    return "", h


def latest_date(events: list[dict]) -> str:
    vals = [str(x.get("fecha") or "") for x in events if x.get("fecha")]
    return max(vals) if vals else ""


def make_matcher(registry: list[dict]):
    by_rut = {norm_rut(x.get("rut")): x for x in registry if norm_rut(x.get("rut"))}
    by_name: dict[str, list[dict]] = {}
    for x in registry:
        n = norm(x.get("nombre") or x.get("nombre_uaf"))
        if n:
            by_name.setdefault(n, []).append(x)

    def match(name: str = "", rut: str = "") -> dict:
        rr = norm_rut(rut)
        if rr and rr in by_rut:
            x = by_rut[rr]
            return {"rut": x.get("rut"), "nombre_uaf": x.get("nombre") or x.get("nombre_uaf"), "actividad_uaf": x.get("actividad") or x.get("actividad_uaf"), "match_method": "rut", "match_score": 1.0}
        nn = norm(name)
        if nn in by_name and len(by_name[nn]) == 1:
            x = by_name[nn][0]
            return {"rut": x.get("rut"), "nombre_uaf": x.get("nombre") or x.get("nombre_uaf"), "actividad_uaf": x.get("actividad") or x.get("actividad_uaf"), "match_method": "name_exact", "match_score": 0.97}
        if not nn:
            return {}
        toks = {t for t in nn.split() if len(t) >= 5}
        candidates = []
        for key, vals in by_name.items():
            if toks and not toks.intersection(set(key.split())):
                continue
            score = SequenceMatcher(None, nn, key).ratio()
            if score >= 0.93:
                for x in vals:
                    candidates.append((score, x))
        candidates.sort(key=lambda z: z[0], reverse=True)
        if len(candidates) == 1 or (candidates and (len(candidates) < 2 or candidates[0][0] - candidates[1][0] >= 0.04)):
            score, x = candidates[0]
            return {"rut": x.get("rut"), "nombre_uaf": x.get("nombre") or x.get("nombre_uaf"), "actividad_uaf": x.get("actividad") or x.get("actividad_uaf"), "match_method": "name_fuzzy", "match_score": round(score, 3)}
        return {}
    return match


def event_key(e: dict) -> str:
    rut = norm_rut(e.get("rut") or e.get("rut_fuente"))
    identity = rut or norm(e.get("sujeto_fuente") or e.get("nombre_uaf"))
    parts = [norm(e.get("supervisor")), norm(e.get("resolucion")), str(e.get("fecha") or ""), identity]
    return "|".join(parts)


def merge_preserving_rich(base: list[dict], live: list[dict]) -> list[dict]:
    out = {event_key(x): dict(x) for x in base}
    mutable = {
        "estado", "monto", "unidad", "resolution_url", "source_url", "resolucion", "tipo_evento",
        "rut", "rut_fuente", "nombre_uaf", "actividad_uaf", "match_method", "match_score",
        "uaf_registro_actual", "needs_pdf_enrichment", "document_status", "document_confidence",
        "document_subject_count", "document_entity_count", "document_page_entity",
        "document_page_sanction", "document_page_infraction", "document_analysis_version",
        "document_pdf_sha256", "other_entities_in_resolution", "related_subjects",
    }

    def alias_key(e: dict) -> tuple:
        return (
            norm(e.get("supervisor")), norm(e.get("resolucion")), str(e.get("fecha") or ""),
            norm(e.get("sujeto_fuente") or e.get("nombre_uaf")),
        )

    for e in live:
        k = event_key(e)
        target_key = k if k in out else None
        if target_key is None:
            erut = norm_rut(e.get("rut") or e.get("rut_fuente"))
            if erut:
                candidates = [ok for ok, ov in out.items() if
                    norm(ov.get("supervisor")) == norm(e.get("supervisor")) and
                    norm(ov.get("resolucion")) == norm(e.get("resolucion")) and
                    str(ov.get("fecha") or "") == str(e.get("fecha") or "") and
                    norm_rut(ov.get("rut") or ov.get("rut_fuente")) == erut]
                if len(candidates) == 1:
                    target_key = candidates[0]
        if target_key is None:
            ak = alias_key(e)
            candidates = [ok for ok, ov in out.items() if alias_key(ov) == ak]
            if len(candidates) == 1:
                target_key = candidates[0]
        if target_key is None:
            out[k] = dict(e)
            continue
        cur = out[target_key]
        document_rich = str(e.get("document_status") or "") in {"enriched", "partial"}
        document_fields = {"resumen", "categoria", "laft_directo", "notes", "source_title", "event_group"}
        for field, value in e.items():
            if value in (None, "", [], {}):
                continue
            if field in mutable or (document_rich and field in document_fields) or cur.get(field) in (None, "", [], {}):
                cur[field] = value
        new_key = event_key(cur)
        if new_key != target_key:
            out.pop(target_key, None)
        out[new_key] = cur

    rows = list(out.values())
    cmf_resolved = {
        str(x.get("resolucion")) for x in rows
        if norm(x.get("supervisor")) == "CMF" and norm_rut(x.get("rut") or x.get("rut_fuente"))
    }
    cleaned = []
    for x in rows:
        is_cmf = norm(x.get("supervisor")) == "CMF"
        res = str(x.get("resolucion") or "")
        no_id = not norm_rut(x.get("rut") or x.get("rut_fuente"))
        generic = bool(x.get("needs_pdf_enrichment")) or bool(re.search(r"SOCIEDADES? QUE INDICA|ADMINISTRADORAS? .* QUE INDICA", str(x.get("sujeto_fuente") or x.get("resumen") or ""), re.I))
        if is_cmf and res in cmf_resolved and no_id and generic:
            continue
        cleaned.append(x)
    rows = cleaned

    rows.sort(key=lambda x: (x.get("fecha") or "", x.get("supervisor") or "", x.get("resolucion") or ""), reverse=True)
    for i, e in enumerate(rows, 1):
        e["id"] = f"EVT-{i:04d}"
    return rows

def soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")
