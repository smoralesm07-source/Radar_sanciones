-- Radar de Sanciones OSINT v0.8
CREATE TABLE IF NOT EXISTS source_snapshot (
  snapshot_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, url TEXT NOT NULL,
  downloaded_at TEXT NOT NULL, published_update TEXT, sha256 TEXT NOT NULL,
  http_status INTEGER, bytes INTEGER, parser_version TEXT, coverage_from TEXT, coverage_to TEXT
);
CREATE TABLE IF NOT EXISTS legal_entity (
  entity_id TEXT PRIMARY KEY, rut TEXT, legal_name TEXT, normalized_name TEXT,
  uaf_status TEXT, uaf_activity TEXT, sii_status TEXT, created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS sanction_case (
  sanction_case_id TEXT PRIMARY KEY, authority TEXT NOT NULL, source_case_id TEXT,
  case_start_date TEXT, decision_date TEXT, publication_date TEXT, event_stage TEXT,
  finality TEXT, source_snapshot_id TEXT, source_url TEXT, resolution_url TEXT
);
CREATE TABLE IF NOT EXISTS sanction_fact (
  sanction_fact_id TEXT PRIMARY KEY, sanction_case_id TEXT NOT NULL, entity_id TEXT NOT NULL,
  sanction_type TEXT, amount REAL, amount_unit TEXT, status TEXT, infraction_text TEXT,
  infringed_norm TEXT, category TEXT, laft_direct INTEGER DEFAULT 0,
  first_seen_at TEXT, last_changed_at TEXT, evidence_id TEXT,
  FOREIGN KEY(sanction_case_id) REFERENCES sanction_case(sanction_case_id),
  FOREIGN KEY(entity_id) REFERENCES legal_entity(entity_id)
);
CREATE TABLE IF NOT EXISTS evidence (
  evidence_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, document_url TEXT,
  document_sha256 TEXT, page_entity INTEGER, page_sanction INTEGER, page_infraction INTEGER,
  extraction_status TEXT, extraction_confidence REAL, excerpt TEXT, captured_at TEXT
);
