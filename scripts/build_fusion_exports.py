from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from radar_sanciones.interop import global_entity_id

DATA = ROOT / "docs" / "data"
SOURCE = DATA / "events.json"


def iso(value):
    text = str(value or "").strip()
    return (text + "T00:00:00+00:00") if len(text) == 10 else (text or None)


def ev_id(row):
    seed = "|".join(str(row.get(k) or "") for k in ("source_system", "source_event_id", "source_url", "last_seen_at"))
    return "EVD-SANC-" + hashlib.sha256(seed.encode()).hexdigest()[:24]


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def build():
    rows = json.loads(SOURCE.read_text(encoding="utf-8")) if SOURCE.exists() else []
    evidence, entities, events = {}, {}, []
    unresolved = 0
    for row in rows:
        event_id = str(row.get("event_id") or "").strip()
        retrieved = iso(row.get("last_seen_at") or row.get("first_seen_at"))
        if not event_id or not retrieved:
            continue
        eid = ev_id(row)
        confidence = float(row.get("confidence") or 0)
        evidence[eid] = {
            "evidence_id": eid,
            "producer_id": "RADAR_SANCIONES",
            "source_id": str(row.get("source_system") or row.get("regulator") or "SOURCE"),
            "ultimate_source_id": str(row.get("source_system") or row.get("regulator") or "SOURCE"),
            "source_url": row.get("source_url") or None,
            "source_tier": row.get("source_tier") or None,
            "capture_method": "RADAR_SANCIONES_PIPELINE",
            "source_run_id": row.get("source_version") or None,
            "content_sha256": None,
            "quality_status": "VALID" if confidence >= 0.8 else "PARTIAL",
            "source_published_at": iso(row.get("published_at") or row.get("decision_date")),
            "retrieved_at": retrieved,
            "ingested_at": retrieved,
            "excerpt": row.get("description") or None,
            "schema_version": "1.0",
        }
        entity_id = global_entity_id(row.get("rut"))
        entity_ids = [entity_id] if entity_id else []
        if entity_id:
            obj = entities.setdefault(entity_id, {
                "entity_id": entity_id,
                "entity_type": "LEGAL_ENTITY",
                "canonical_name": row.get("entity_name") or None,
                "rut_normalized": row.get("rut") or None,
                "aliases": [],
                "roles": ["SANCTIONED_PARTY"],
                "producer_ids": ["RADAR_SANCIONES"],
                "evidence_ids": [],
                "identity_method": "RUT_EXACT",
                "identity_confidence": 1.0,
                "attributes": {},
            })
            if eid not in obj["evidence_ids"]:
                obj["evidence_ids"].append(eid)
        else:
            unresolved += 1
        events.append({
            "event_id": event_id,
            "event_type": "SANCTION",
            "producer_id": "RADAR_SANCIONES",
            "entity_ids": entity_ids,
            "territory_ids": [],
            "sector_ids": [],
            "evidence_ids": [eid],
            "temporal": {
                "valid_from": iso(row.get("decision_date") or row.get("published_at")),
                "valid_to": None,
                "source_published_at": iso(row.get("published_at")),
                "observed_at": iso(row.get("first_seen_at")),
                "retrieved_at": retrieved,
                "ingested_at": retrieved,
                "last_seen_at": iso(row.get("last_seen_at")),
                "freshness_state": "CURRENT",
            },
            "attributes": {
                "entity_name_unresolved": None if entity_id else row.get("entity_name"),
                "sanction_type": row.get("sanction_type"),
                "sanction_amount_clp": row.get("sanction_amount_clp"),
                "currency": row.get("currency"),
                "regulator": row.get("regulator"),
                "legal_basis": row.get("legal_basis"),
                "status": row.get("status"),
                "classification": row.get("classification"),
                "confidence": row.get("confidence"),
                "review_status": row.get("review_status"),
            },
        })
    write_jsonl(DATA / "evidence_v1.jsonl", evidence.values())
    write_jsonl(DATA / "entities_fusion_v1.jsonl", entities.values())
    write_jsonl(DATA / "events_fusion_v1.jsonl", events)
    status = {"interop_version":"1.0","radar_id":"RADAR_SANCIONES","status":"FUSION_EXPORT_READY","evidence":len(evidence),"entities":len(entities),"events":len(events),"unresolved_event_entities":unresolved,"source_failure_is_zero":False}
    (DATA / "fusion_interop_status_v1.json").write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    return status


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False))
