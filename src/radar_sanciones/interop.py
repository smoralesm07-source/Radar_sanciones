from __future__ import annotations

import re
from typing import Any, Iterable

from .model import normalizar_nombre

INTEROP_VERSION = "1.0"
RADAR_ID = "RADAR_SANCIONES"


def _rut_dv(body: str) -> str:
    total = 0
    multiplier = 2
    for digit in reversed(body):
        total += int(digit) * multiplier
        multiplier = multiplier + 1 if multiplier < 7 else 2
    value = 11 - (total % 11)
    return "0" if value == 11 else ("K" if value == 10 else str(value))


def normalize_rut(value: object) -> str | None:
    compact = re.sub(r"[^0-9Kk]", "", str(value or "")).upper()
    if not re.fullmatch(r"\d{1,8}[0-9K]", compact):
        return None
    body, dv = compact[:-1], compact[-1]
    if _rut_dv(body) != dv:
        return None
    return f"{int(body)}-{dv}"


def global_entity_id(rut: object) -> str | None:
    canonical = normalize_rut(rut)
    return f"ENT-RUT-{canonical}" if canonical else None


def adapt_entity(record: dict[str, Any]) -> dict[str, Any]:
    rut = normalize_rut(record.get("rut"))
    eid = global_entity_id(rut)
    source_id = str(record.get("entity_id") or record.get("source_entity_id") or "")
    name = str(
        record.get("nombre_uaf")
        or record.get("nombre")
        or record.get("entity_name")
        or record.get("canonical_name")
        or ""
    )
    resolved = bool(eid)
    return {
        "interop_version": INTEROP_VERSION,
        "radar_id": RADAR_ID,
        "entity_id": eid,
        "source_entity_id": source_id or None,
        "candidate_entity_id": None if resolved else (source_id or None),
        "entity_type": record.get("entity_type") or "LEGAL_ENTITY",
        "entity_role": "SANCTIONED_ENTITY",
        "rut": rut,
        "rut_valid": resolved,
        "canonical_name": name,
        "normalized_name": normalizar_nombre(name),
        "identity_status": "RESOLVED" if resolved else "UNRESOLVED",
        "identity_method": "RUT_EXACT" if resolved else "SOURCE_LOCAL_ONLY",
        "identity_confidence": 1.0 if resolved else 0.0,
        "candidate_confidence": None if resolved else 0.0,
        "source_systems": record.get("supervisores") or "",
        "last_event_at": record.get("fecha_ultimo_evento") or "",
    }


def build_entity_hub(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = [adapt_entity(r) for r in records]
    return sorted(rows, key=lambda r: (str(r.get("entity_id") or "~"), str(r.get("source_entity_id") or "")))


def hub_metrics(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    data = list(rows)
    return {
        "rows": len(data),
        "resolved": sum(bool(x.get("entity_id")) for x in data),
        "unresolved": sum(not bool(x.get("entity_id")) for x in data),
    }
