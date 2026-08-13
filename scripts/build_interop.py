import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from radar_sanciones.interop import build_entity_hub, hub_metrics

SOURCE = ROOT / "data/silver/entities.json"
GOLD = ROOT / "data/gold/entity_hub_v1.json"
DOCS = ROOT / "docs/data/entity_hub_v1.json"
STATUS = ROOT / "docs/data/interop_status_v1.json"


def main():
    records = json.loads(SOURCE.read_text(encoding="utf-8")) if SOURCE.exists() else []
    rows = build_entity_hub(records)
    for path in (GOLD, DOCS):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    STATUS.write_text(json.dumps({"interop_version":"1.0","radar_id":"RADAR_SANCIONES",**hub_metrics(rows)}, ensure_ascii=False, indent=2), encoding="utf-8")
    # Fusion materialization is intentionally chained here so every radar refresh publishes canonical outputs.
    from fusion_v1 import main as fusion_main
    fusion_main()
    print(json.dumps(hub_metrics(rows), ensure_ascii=False))


if __name__ == "__main__":
    main()
