import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from radar_sanciones.fusion_export import build

SOURCE = ROOT / "data/silver/sanction_events.json"
OUT = ROOT / "data/silver"
STATUS = ROOT / "docs/data/fusion_interop_status_v1.json"


def write_jsonl(path: Path, rows: list[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(rows)


def main() -> None:
    if not SOURCE.exists():
        raise RuntimeError("Missing sanction_events.json; refusing false-zero Fusion export")
    events = json.loads(SOURCE.read_text(encoding="utf-8"))
    if not events:
        raise RuntimeError("Sanctions source is empty; refusing false-zero Fusion export")
    fusion = build(events)
    counts = {
        "evidence": write_jsonl(OUT / "evidence_fusion_v1.jsonl", fusion["evidence"]),
        "entities": write_jsonl(OUT / "entities_fusion_v1.jsonl", fusion["entities"]),
        "events": write_jsonl(OUT / "events_fusion_v1.jsonl", fusion["events"]),
    }
    status = {
        "interop_version": "1.0",
        "radar_id": "RADAR_SANCIONES",
        "status": "FUSION_EXPORT_READY",
        **counts,
        "source_failure_is_zero": False,
        "name_only_entities_promoted": False,
    }
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    STATUS.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(status, ensure_ascii=False))


if __name__ == "__main__":
    main()
