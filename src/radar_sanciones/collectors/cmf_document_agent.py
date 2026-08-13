from __future__ import annotations

"""Agente documental para resoluciones sancionatorias de la CMF.

Objetivo: abrir la resolución oficial, identificar sujetos individualizados, RUT,
sanción y una evidencia breve de la infracción. El diseño es deliberadamente
conservador y auditable: si no puede extraer con suficiente evidencia, marca el
resultado como parcial en vez de inventar campos.
"""

from io import BytesIO
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
import hashlib
import json
import os
import re
import unicodedata
from typing import Iterable

import requests
from pypdf import PdfReader

from .common import UA, norm, norm_rut

AGENT_VERSION = "cmf-doc-agent-1.0"

LEGAL_HINTS = {
    "SA", "SPA", "LTDA", "LIMITADA", "EIRL", "SADP", "SOCIEDAD", "BANCO",
    "COOPERATIVA", "COMPANIA", "COMPAÑIA", "SEGUROS", "CORREDORES", "CORREDORA",
    "ADMINISTRADORA", "ADMINISTRADOR", "FONDO", "CLUB", "CAJA", "MUTUAL",
    "EMISOR", "OPERADORA", "OPERADOR", "BOLSA", "DEPOSITO", "DEPÓSITO",
    "AUDITORES", "CONSULTORES", "INMOBILIARIA", "FINANCE", "FINANCIERA",
    "CREDITO", "CRÉDITO", "CAPITAL", "ASSET", "GESTION", "GESTIÓN",
}

RUT_RE = re.compile(r"(?P<rut>\d{1,2}(?:\.\d{3}){2}-[0-9Kk]|\d{7,8}-[0-9Kk])")
SUBJECT_RUT_RE = re.compile(
    r"(?P<name>[A-ZÁÉÍÓÚÑÜ0-9][A-ZÁÉÍÓÚÑÜ0-9&.,()'’\- /]{2,180}?)"
    r"\s*,?\s*RUT\s*(?:N\s*)?[°ºo]?\s*(?P<rut>\d{1,2}(?:\.\d{3}){2}-[0-9Kk]|\d{7,8}-[0-9Kk])",
    re.IGNORECASE,
)

SANCTION_PATTERNS = [
    re.compile(r"\bCENSURA\b", re.I),
    re.compile(r"\bAMONESTACI[ÓO]N\b", re.I),
    re.compile(r"\bREVOCACI[ÓO]N\b", re.I),
    re.compile(r"\bMULTA\b[^\n]{0,45}?\b(?:UF|U\.F\.|UTM)\s*([0-9][0-9.,]*)", re.I),
    re.compile(r"\b(?:UF|U\.F\.|UTM)\s*([0-9][0-9.,]*)", re.I),
    re.compile(r"\b([0-9][0-9.,]*)\s*(?:UF|U\.F\.|UTM)\b", re.I),
]

KEYWORDS_INFRACTION = (
    "incumplimiento", "no envío", "no remisión", "no remitió", "contraviniendo",
    "deber de información", "obligación de información", "tasa máxima", "control interno",
    "gestión de riesgos", "reporte", "información continua", "comercializó", "intermedió",
    "coberturas", "debida diligencia", "beneficiario final", "lavado de activos",
    "financiamiento del terrorismo", "fraude", "custodia", "incidente operacional",
)


@dataclass
class DocumentSubject:
    name: str
    rut: str
    page_entity: int | None = None
    subject_kind: str = "unknown"
    sanction_text: str = ""
    sanction_kind: str = ""
    monto: float | None = None
    unidad: str = ""
    page_sanction: int | None = None
    infraction_excerpt: str = ""
    page_infraction: int | None = None
    category: str = "Pendiente de clasificación detallada"
    laft_directo: bool = False
    confidence: float = 0.0

    def to_dict(self):
        return asdict(self)


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _strip_accents(s: str) -> str:
    return unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode()


def _flat(s: str) -> str:
    s = _strip_accents(str(s or "")).upper()
    s = re.sub(r"[^A-Z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _clean_spaces(s: str) -> str:
    s = str(s or "").replace("\u00a0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _format_rut(raw: str) -> str:
    n = norm_rut(raw)
    if len(n) < 2:
        return ""
    return f"{n[:-1]}-{n[-1]}"


def _clean_subject_name(raw: str) -> str:
    s = _clean_spaces(raw)
    s = re.sub(r"^(?:III(?:\.\d+)?\.?|IV(?:\.\d+)?\.?|V(?:\.\d+)?\.?|VI(?:\.\d+)?\.?)\s*", "", s, flags=re.I)
    s = re.sub(r"^\d+\.\s*", "", s)
    s = re.sub(r"^(?:APLICAR\s+(?:A|AL|A LA|DON|DOÑA)\s+|RESPECTO\s+DE\s+|EN CONTRA DE\s+)", "", s, flags=re.I)
    s = re.sub(r"^DON\s+", "", s, flags=re.I)
    s = s.strip(" ,.;:-")
    if "\n" in s:
        s = s.split("\n")[-1].strip()
    return re.sub(r"\s+", " ", s)


def _subject_kind(name: str) -> str:
    toks = set(_flat(name).split())
    if toks & {_flat(x) for x in LEGAL_HINTS}:
        return "legal_entity"
    if re.search(r"\bS\s*A\b|\bS\s*P\s*A\b|\bLTDA\b|\bEIRL\b|\bSADP\b", _flat(name)):
        return "legal_entity"
    if 2 <= len(toks) <= 5:
        return "person"
    return "unknown"


def _parse_amount(raw: str) -> float | None:
    s = str(raw or "").strip().replace(" ", "")
    if not s:
        return None
    try:
        if "," in s:
            s = s.replace(".", "").replace(",", ".")
        elif s.count(".") == 1 and len(s.split(".")[-1]) == 3:
            s = s.replace(".", "")
        elif s.count(".") > 1:
            s = s.replace(".", "")
        return float(s)
    except ValueError:
        return None


def _parse_sanction(text: str) -> dict:
    t = _clean_spaces(text)
    if re.search(r"\bCENSURA\b", t, re.I):
        return {"sanction_text": "Censura", "sanction_kind": "Censura", "monto": None, "unidad": "Censura"}
    if re.search(r"\bAMONESTACI[ÓO]N\b", t, re.I):
        return {"sanction_text": "Amonestación", "sanction_kind": "Amonestación", "monto": None, "unidad": "Amonestación"}
    if re.search(r"\bREVOCACI[ÓO]N\b", t, re.I):
        return {"sanction_text": "Revocación", "sanction_kind": "Revocación", "monto": None, "unidad": "Revocación"}
    m = re.search(r"(?:MULTA\s*(?:DE)?\s*)?(UF|U\.F\.|UTM)\s*([0-9][0-9.,]*)", t, re.I)
    if not m:
        m2 = re.search(r"(?:MULTA\s*(?:DE)?\s*)?([0-9][0-9.,]*)\s*(UF|U\.F\.|UTM)\b", t, re.I)
        if m2:
            amount, unit = m2.group(1), m2.group(2)
        else:
            return {}
    else:
        unit, amount = m.group(1), m.group(2)
    unit = "UF" if _flat(unit).replace(" ", "") in {"UF"} else "UTM"
    val = _parse_amount(amount)
    if val is None:
        return {}
    label = f"Multa {unit} {val:g}"
    return {"sanction_text": label, "sanction_kind": "Multa", "monto": val, "unidad": unit}


def _extract_pdf_pages(content: bytes) -> list[str]:
    reader = PdfReader(BytesIO(content))
    pages = []
    for page in reader.pages:
        try:
            pages.append(_clean_spaces(page.extract_text() or ""))
        except Exception:
            pages.append("")
    return pages


def _extract_subjects(pages: list[str]) -> list[DocumentSubject]:
    found: dict[str, DocumentSubject] = {}
    for page_no, page in enumerate(pages, 1):
        for m in SUBJECT_RUT_RE.finditer(page):
            name = _clean_subject_name(m.group("name"))
            rut = _format_rut(m.group("rut"))
            if not name or not rut:
                continue
            if len(name) > 150:
                continue
            key = norm_rut(rut)
            cur = found.get(key)
            candidate = DocumentSubject(name=name, rut=rut, page_entity=page_no, subject_kind=_subject_kind(name))
            if cur is None:
                found[key] = candidate
            else:
                def quality(x: DocumentSubject):
                    return (x.subject_kind == "legal_entity", -len(x.name), x.page_entity or 999)
                if quality(candidate) > quality(cur):
                    candidate.page_entity = min(p for p in [candidate.page_entity, cur.page_entity] if p)
                    found[key] = candidate
    return list(found.values())


def _last_resolve_page(pages: list[str]) -> int:
    hits = []
    for i, p in enumerate(pages):
        if re.search(r"\bRESUELV[EA]\s*:", p, re.I) or re.search(r"FINANCIERO\s*,?\s*RESUELV[EA]", p, re.I):
            hits.append(i)
    return hits[-1] if hits else max(0, len(pages) - 5)


def _name_similarity(a: str, b: str) -> float:
    aa, bb = _flat(a), _flat(b)
    if not aa or not bb:
        return 0.0
    if aa in bb or bb in aa:
        return 1.0
    return SequenceMatcher(None, aa, bb).ratio()


def _resolutive_table_rows(pages: list[str]) -> list[tuple[str, dict, int]]:
    start = _last_resolve_page(pages)
    rows: list[tuple[str, dict, int]] = []
    for page_idx in range(start, min(len(pages), start + 4)):
        lines = [re.sub(r"\s+", " ", x).strip() for x in pages[page_idx].splitlines() if x.strip()]
        header_idx = next((i for i,l in enumerate(lines) if "SOCIEDAD" in _flat(l) and "SANCION" in _flat(l)), None)
        if header_idx is None:
            continue
        current: list[str] = []
        def flush():
            nonlocal current
            if not current:
                return
            chunk = " ".join(current)
            m = re.match(r"^\d+\s+(.*)$", chunk)
            if m:
                body = m.group(1).strip()
                body = re.sub(r"\s+Para validar ir a\s+https?://.*$", "", body, flags=re.I)
                body = re.sub(r"\s+FOLIO:\s*RES-.*$", "", body, flags=re.I)
                sanc = _parse_sanction(body)
                if sanc:
                    name = re.sub(r"\s+(?:CENSURA|AMONESTACI[ÓO]N|REVOCACI[ÓO]N|MULTA\b.*)$", "", body, flags=re.I)
                    rows.append((name.strip(), sanc, page_idx + 1))
            current = []
        for l in lines[header_idx+1:]:
            if re.match(r"^\d+\.\s", l) and not re.match(r"^\d+\s+(?!UF\b|U\.F\.|UTM\b)(?=[A-ZÁÉÍÓÚÑ])", l, re.I):
                flush(); break
            if re.match(r"^\d+\s+(?!UF\b|U\.F\.|UTM\b)(?=[A-ZÁÉÍÓÚÑ])", l, re.I):
                flush(); current = [l]
            elif current:
                current.append(l)
        flush()
    return rows


def _find_sanction(subject: DocumentSubject, pages: list[str]) -> tuple[dict, int | None]:
    candidates = []
    for row_name, sanction, page_no in _resolutive_table_rows(pages):
        candidates.append((_name_similarity(subject.name, row_name), sanction, page_no))
    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        if candidates[0][0] >= 0.84:
            return candidates[0][1], candidates[0][2]

    start = _last_resolve_page(pages)
    rut_norm = norm_rut(subject.rut)
    for page_idx in range(start, min(len(pages), start + 4)):
        text = pages[page_idx]
        if not text:
            continue
        for mr in RUT_RE.finditer(text):
            if norm_rut(mr.group("rut")) != rut_norm:
                continue
            window = text[max(0, mr.start() - 200): min(len(text), mr.end() + 300)]
            parsed = _parse_sanction(window)
            if parsed:
                return parsed, page_idx + 1
    return {}, None


def _extract_infraction_from_block(block: str) -> str:
    block = _clean_spaces(block)
    if not block:
        return ""
    m = re.search(
        r"Infracci[oó]n\s+Detectada\s*(.*?)(?=\n\s*2\.\s|\n\s*3\.\s|\n\s*4\.\s|\bEn\s+dicho\s+requerimiento\b|\bQue,\s+en\s+dicho\s+Requerimiento\b)",
        block, re.I | re.S,
    )
    if m:
        txt = m.group(1)
        txt = re.sub(r"Para validar ir a .*?P[aá]gina\s+\d+/\d+", " ", txt, flags=re.I | re.S)
        txt = re.sub(r"FOLIO:.*?SGD:\s*\d+", " ", txt, flags=re.I)
        txt = re.sub(r"\s+", " ", txt).strip(" .;:")
        if txt:
            return txt[:900]
    compact = re.sub(r"\s+", " ", block)
    pieces = re.split(r"(?<=[.;:])\s+(?=[A-ZÁÉÍÓÚÑ0-9])", compact)
    chosen = []
    for p in pieces:
        low = p.lower()
        if any(k in low for k in KEYWORDS_INFRACTION):
            if len(p) < 45:
                continue
            chosen.append(p.strip())
        if len(" ".join(chosen)) > 700:
            break
    return " ".join(chosen)[:900]


def _find_infraction(subject: DocumentSubject, pages: list[str]) -> tuple[str, int | None]:
    for page_idx in range(max(0, len(pages) - 15), len(pages)):
        block = "\n".join(pages[page_idx:min(len(pages), page_idx + 2)])
        for m in re.finditer(r"Respecto\s+de\s+([^:\n]{3,180})[:：]", block, re.I):
            label = _clean_subject_name(m.group(1))
            if _name_similarity(subject.name, label) < 0.72:
                continue
            tail = block[m.end():]
            next_m = re.search(r"(?:I{1,4}|V?I{0,3})\.?-?\s*Respecto\s+de\s+", tail, re.I)
            if next_m:
                tail = tail[:next_m.start()]
            excerpt = _extract_infraction_from_block(tail)
            if excerpt:
                return excerpt, page_idx + 1

    rut_norm = norm_rut(subject.rut)
    for page_idx, text in enumerate(pages):
        for mr in RUT_RE.finditer(text):
            if norm_rut(mr.group("rut")) != rut_norm:
                continue
            block = "\n".join(pages[page_idx:min(len(pages), page_idx + 2)])
            excerpt = _extract_infraction_from_block(block)
            if excerpt:
                return excerpt, page_idx + 1
    return "", None


def _classify(text: str) -> tuple[str, bool]:
    f = _flat(text)
    if any(k in f for k in ("LAVADO DE ACTIVOS", "FINANCIAMIENTO DEL TERRORISMO", "BENEFICIARIO FINAL", "DEBIDA DILIGENCIA")):
        return "ALA/CFT / debida diligencia", True
    if any(k in f for k in ("INFORMACION CONTINUA", "NO ENVIO DE INFORMACION", "DEBER DE INFORMACION", "OBLIGACION DE INFORMACION", "REMISION DE INFORMACION", "REMITIR TRIMESTRALMENTE")):
        return "Deberes de información / reportabilidad", False
    if "TASA MAXIMA CONVENCIONAL" in f:
        return "Crédito / tasa máxima convencional", False
    if any(k in f for k in ("CONTROL INTERNO", "GESTION DE RIESGO", "GESTION DE RIESGOS")):
        return "Control interno / gestión de riesgos", False
    if any(k in f for k in ("INCIDENTE OPERACIONAL", "CIBERSEGURIDAD", "SEGURIDAD DE LA INFORMACION")):
        return "Riesgo operacional / ciberseguridad", False
    if any(k in f for k in ("POLIZA", "POLIZAS", "CORREDOR DE SEGUROS", "INTERMEDIO", "INTERMEDIACION", "COMERCIALIZO")):
        return "Conducta de mercado / seguros", False
    if any(k in f for k in ("CUSTODIA", "TITULOS", "INVERSIONES")):
        return "Inversiones / custodia / mercado de valores", False
    return "Cumplimiento regulatorio", False


def analyze_pages(pages: list[str]) -> dict:
    text_all = "\n".join(pages)
    subjects = _extract_subjects(pages)
    table_rows = _resolutive_table_rows(pages)
    for s in subjects:
        if table_rows:
            ranked = sorted(((_name_similarity(s.name, row_name), row_name) for row_name, _, _ in table_rows), reverse=True)
            if ranked and ranked[0][0] >= 0.90:
                s.name = ranked[0][1]
        sanction, p_sanc = _find_sanction(s, pages)
        if sanction:
            s.sanction_text = sanction.get("sanction_text", "")
            s.sanction_kind = sanction.get("sanction_kind", "")
            s.monto = sanction.get("monto")
            s.unidad = sanction.get("unidad", "")
            s.page_sanction = p_sanc
        excerpt, p_inf = _find_infraction(s, pages)
        s.infraction_excerpt = excerpt
        s.page_infraction = p_inf
        s.category, s.laft_directo = _classify((excerpt or "") + " " + text_all[:12000])
        score = 0.35
        if s.rut:
            score += 0.25
        if s.sanction_text:
            score += 0.22
        if s.infraction_excerpt:
            score += 0.13
        if s.subject_kind == "legal_entity":
            score += 0.05
        s.confidence = min(0.99, round(score, 2))

    legal = [s for s in subjects if s.subject_kind == "legal_entity"]
    resolved = [s for s in legal if s.sanction_text]
    status = "enriched" if legal and len(resolved) == len(legal) else ("partial" if legal else "failed")
    conf = round(sum(s.confidence for s in legal) / len(legal), 2) if legal else 0.0
    return {
        "agent_version": AGENT_VERSION,
        "status": status,
        "page_count": len(pages),
        "subject_count": len(subjects),
        "legal_entity_count": len(legal),
        "confidence": conf,
        "subjects": [s.to_dict() for s in subjects],
    }


def analyze_pdf_bytes(content: bytes) -> dict:
    pages = _extract_pdf_pages(content)
    result = analyze_pages(pages)
    result["pdf_sha256"] = hashlib.sha256(content).hexdigest()
    return result


def fetch_pdf(url: str, timeout: int = 50) -> tuple[bytes | None, str]:
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": UA, "Accept": "application/pdf,*/*"})
        if not r.ok:
            return None, f"HTTP {r.status_code}"
        ctype = (r.headers.get("content-type") or "").lower()
        if "pdf" not in ctype and not r.content.startswith(b"%PDF"):
            return None, f"contenido no PDF ({ctype or 'sin content-type'})"
        return r.content, "ok"
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def load_cache(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            obj = json.load(f)
        return obj if isinstance(obj, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_cache(path: str, cache: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def analyze_resolution(url: str, resolution: str, cache: dict | None = None, force: bool = False) -> tuple[dict | None, str, bool]:
    cache = cache if cache is not None else {}
    key = str(resolution or url)
    existing = cache.get(key)
    if existing and not force and existing.get("analysis"):
        return existing["analysis"], "cache", True
    content, msg = fetch_pdf(url)
    if not content:
        if existing and existing.get("analysis"):
            return existing["analysis"], f"fallback cache tras error: {msg}", True
        return None, msg, False
    try:
        analysis = analyze_pdf_bytes(content)
    except Exception as exc:
        return None, f"parser PDF {type(exc).__name__}: {exc}", False
    cache[key] = {
        "resolution": str(resolution),
        "url": url,
        "checked_at": _now_iso(),
        "analysis": analysis,
    }
    return analysis, "ok", False
