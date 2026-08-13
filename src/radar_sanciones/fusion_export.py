from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Iterable

from .interop import global_entity_id

RADAR_ID = "RADAR_SANCIONES"
VERSION = "1.0"


def _iso_date(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if "T" in text:
        return text
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat() + "T00:00:00+00:00"
        except ValueError:
            pass
    return None


def _seed(record: dict[str, Any]) -> str:
    return str(record.get("source_record_id") or record.get("id") or "|".join([
        str(record.get("supervisor") or ""),
        str(record.get("resolucion") or ""),
        str(record.get("fecha") or ""),
        str(record.get("sujeto_fuente") or ""),
    ]))


def _stable_id(prefix: str, record: dict[str, Any]) -> str:
    digest = hashlib.sha256(_seed(record).encode("utf-8")).hexdigest()[:20].upper()
    return f"{prefix}-{digest}"


def adapt_evidence(record: dict[str, Any], retrieved_at: str) -> dict[str, Any]:
    document_status = str(record.get("document_status") or "").lower()
    quality = "VALID" if document_status == "enriched" else ("PARTIAL" if document_status in {"partial", "failed"} else "UNKNOWN")
    content_hash = str(record.get("document_pdf_sha256") or "").strip() or None
    return {
        "evidence_id": _stable_id("EVD-SANC", record),
        "producer_id": RADAR_ID,
        "source_id": str(record.get("supervisor") or "SANCTIONS_SOURCE"),
        "ultimate_source_id": str(record.get("supervisor") or "SANCTIONS_SOURCE"),
        "source_url": record.get("resolution_url") or record.get("source_url") or None,
        "source_tier": "OFFICIAL",
        "capture_method": str(record.get("document_analysis_version") or "RADAR_SANCIONES_PIPELINE"),
        "source_run_id": None,
        "content_sha256": content_hash,
        "quality_status": quality,
        "source_published_at": _iso_date(record.get("fecha")),
        "retrieved_at": retrieved_at,
        "ingested_at": retrieved_at,
        "excerpt": record.get("resumen") or record.get("source_title") or None,
        "schema_version": VERSION,
        "attributes": {
            "resolution": record.get("resolucion"),
            "document_status": record.get("document_status"),
            "document_confidence": record.get("document_confidence"),
        },
    }


def adapt_event(record: dict[str, Any]) -> dict[str, Any]:
    entity_id = global_entity_id(record.get("rut_fuente"))
    decision_at = _iso_date(record.get("fecha"))
    return {
        "event_id": _stable_id("EVT-SANC", record),
        "event_type": "REGULATORY_SANCTION",
        "producer_id": RADAR_ID,
        "entity_ids": [entity_id] if entity_id else [],
        "territory_ids": [],
        "sector_ids": [],
        "evidence_ids": [_stable_id("EVD-SANC", record)],
        "temporal": {
            "valid_from": decision_at,
            "valid_to": None,
            "source_published_at": decision_at,
            "observed_at": None,
            "retrieved_at": None,
            "ingested_at": None,
            "last_seen_at": None,
            "freshness_state": "UNKNOWN",
        },
        "attributes": {
            "supervisor": record.get("supervisor"),
            "resolution": record.get("resolucion"),
            "source_record_id": record.get("source_record_id"),
            "subject_name": record.get("sujeto_fuente"),
            "category": record.get("categoria"),
            "laft_direct": bool(record.get("laft_directo")),
            "amount": record.get("monto"),
            "unit": record.get("unidad"),
            "status": record.get("estado"),
            "summary": record.get("resumen"),
            "identity_status": "RESOLVED" if entity_id else "UNRESOLVED_CANDIDATE",
        },
    }


def build(events: Iterable[dict[str, Any]], retrieved_at: str | None = None) -> dict[str, list[dict[str, Any]]]:
    native = list(events)
    observed = retrieved_at or datetime.now(timezone.utc).isoformat()
    evidence = [adapt_evidence(row, observed) for row in native]
    canonical_events = [adapt_event(row) for row in native]
    evidence_by_entity: dict[str, set[str]] = {}
    names: dict[str, str] = {}
    for row, event in zip(native, canonical_events):
        if not event["entity_ids"]:
            continue
        eid = event["entity_ids"][0]
        evidence_by_entity.setdefault(eid, set()).add(event["evidence_ids"][0])
        names.setdefault(eid, str(row.get("sujeto_fuente") or ""))
    entities = [{
        "entity_id": eid,
        "entity_type": "LEGAL_ENTITY",
        "canonical_name": names.get(eid) or None,
        "rut_normalized": eid.removeprefix("ENT-RUT-"),
        "aliases": [],
        "roles": ["SANCTIONED_ENTITY"],
        "producer_ids": [RADAR_ID],
        "evidence_ids": sorted(evidence_ids),
        "identity_method": "RUT_EXACT",
        "identity_confidence": 1.0,
        "attributes": {},
    } for eid, evidence_ids in sorted(evidence_by_entity.items())]
    return {"evidence": evidence, "events": canonical_events, "entities": entities}
