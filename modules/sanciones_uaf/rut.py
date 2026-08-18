"""Normalización, validación y comparación de identificadores tributarios chilenos.

El módulo cruza tres fuentes que escriben el RUT de forma distinta (con puntos,
sin guion, con K minúscula, con ceros a la izquierda). Toda comparación de
identidad del módulo pasa por aquí para que el cruce sea determinista.
"""

from __future__ import annotations

import re
import unicodedata

_RUT_CHARS = re.compile(r"[^0-9K]")
_RUT_IN_TEXT = re.compile(r"\b(\d{1,3}(?:\.\d{3})*|\d{7,8})-([\dkK])\b")

# Sufijos societarios y ruido que no aporta a la comparación de razones sociales.
_LEGAL_SUFFIXES = {
    "SA", "S", "A", "SPA", "LTDA", "LIMITADA", "EIRL", "SAC", "SADP", "SAGR",
    "CIA", "COMPANIA", "SOCIEDAD", "ANONIMA", "E", "I", "R", "L", "DE", "DEL",
    "LA", "LAS", "EL", "LOS", "Y", "EN", "COMERCIAL", "INVERSIONES", "GRUPO",
}


def normalize_rut(value: object) -> str | None:
    """Devuelve el RUT en forma canónica ``12345678-9`` o ``None`` si no es utilizable."""
    if value is None:
        return None
    raw = str(value).strip().upper()
    if not raw or raw in {"-", "NAN", "NONE", "SIN RUT", "S/I"}:
        return None
    cleaned = _RUT_CHARS.sub("", raw)
    if len(cleaned) < 2:
        return None
    body, dv = cleaned[:-1], cleaned[-1]
    body = body.lstrip("0")
    if not body or not body.isdigit():
        return None
    if len(body) > 9:
        return None
    return f"{body}-{dv}"


def rut_check_digit(body: str) -> str:
    """Dígito verificador módulo 11 del cuerpo numérico."""
    total, factor = 0, 2
    for ch in reversed(body):
        total += int(ch) * factor
        factor = 2 if factor == 7 else factor + 1
    rest = 11 - (total % 11)
    if rest == 11:
        return "0"
    if rest == 10:
        return "K"
    return str(rest)


def is_valid_rut(canonical: str | None) -> bool:
    """Valida el dígito verificador de un RUT ya canonizado."""
    if not canonical or "-" not in canonical:
        return False
    body, dv = canonical.split("-", 1)
    if not body.isdigit():
        return False
    return rut_check_digit(body) == dv.upper()


def extract_ruts(text: object) -> list[str]:
    """Extrae todos los RUT válidos presentes en un texto libre (resúmenes, PDF)."""
    if not text:
        return []
    found: list[str] = []
    for body, dv in _RUT_IN_TEXT.findall(str(text)):
        canonical = normalize_rut(f"{body}-{dv}")
        if canonical and is_valid_rut(canonical) and canonical not in found:
            found.append(canonical)
    return found


# Ruido de encabezado y de pie que los supervisores arrastran al campo del sujeto.
_TITLE_PREFIX = re.compile(
    r"^(APLICA\s+SANCI[OÓ]N(ES)?\s+(A|AL)\b|SANCIONA\s+A\b|RESUELVE\s+(RECURSO|REPOSICI[OÓ]N|"
    r"REPOSICIONES)[^,;]{0,80}?\b(POR|DE|DEDUCIDA?S?\s+POR)\b|MULTA\s+A\b|"
    r"(LOS?|LAS?)\s+SE[NÑ]OR(ES|A|AS)?\b|EL\s+SE[NÑ]OR\b|LA\s+SE[NÑ]ORA\b)\s*",
    re.IGNORECASE,
)
_TRAILING_AMOUNT = re.compile(r"[\s,.:;-]*\b\d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?\s*(UF|UTM)\.?$", re.IGNORECASE)
_TRAILING_JUNK = re.compile(r"[\s,;:.\-–—]+$")


def clean_subject_name(value: object) -> str:
    """Limpia el nombre del sancionado tal como lo publica el supervisor.

    Las fuentes mezclan el encabezado de la resolución («APLICA SANCIÓN A …»)
    y el monto («… S.A. 210 UF») dentro del campo del sujeto. Se normalizan los
    saltos de línea y se recortan esos afijos para que el nombre sea comparable
    y legible; el original se conserva aparte.
    """
    if not value:
        return ""
    text = re.sub(r"\s+", " ", str(value).replace("\n", " ")).strip()
    for _ in range(2):
        text = _TITLE_PREFIX.sub("", text).strip()
    text = _TRAILING_AMOUNT.sub("", text).strip()
    text = _TRAILING_JUNK.sub("", text).strip()
    return text or re.sub(r"\s+", " ", str(value)).strip()


def strip_accents(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


# Tras quitar la puntuación, «S.A.» queda como «S A» y «SA» como «SA»: sin este
# colapso, dos grafías del mismo sufijo societario dejarían de coincidir.
_LETTER_RUN = re.compile(r"\b(?:[A-Z]\s+){1,5}[A-Z]\b")


def normalize_name(value: object) -> str:
    """Forma comparable de una razón social: sin acentos, sin puntuación, colapsada."""
    if not value:
        return ""
    text = strip_accents(str(value)).upper()
    text = re.sub(r"[^A-Z0-9ÑÜ ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return _LETTER_RUN.sub(lambda m: m.group(0).replace(" ", ""), text)


def name_tokens(value: object) -> frozenset[str]:
    """Tokens significativos de una razón social, sin sufijos societarios."""
    tokens = {
        tok
        for tok in normalize_name(value).split()
        if len(tok) > 1 and tok not in _LEGAL_SUFFIXES
    }
    return frozenset(tokens)


def token_similarity(a: object, b: object) -> float:
    """Similitud Jaccard ponderada por cobertura del nombre más corto (0..1)."""
    ta, tb = name_tokens(a), name_tokens(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    if not inter:
        return 0.0
    jaccard = inter / len(ta | tb)
    coverage = inter / min(len(ta), len(tb))
    return round(0.45 * jaccard + 0.55 * coverage, 4)
