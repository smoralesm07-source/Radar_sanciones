from pathlib import Path
import json,shutil
ROOT=Path(__file__).resolve().parents[1]; pub=ROOT/'docs/data'; pub.mkdir(parents=True,exist_ok=True)
map_paths={
 'events.json':ROOT/'data/silver/sanction_events.json','entities.json':ROOT/'data/silver/entities.json','uaf_registry.json':ROOT/'data/silver/uaf_registry.json',
 'metadata.json':ROOT/'data/gold/metadata.json','source_catalog.json':ROOT/'data/gold/source_catalog.json','coverage_matrix.json':ROOT/'data/gold/coverage_matrix.json','backfill_state.json':ROOT/'data/gold/backfill_state.json',
 'run_delta.json':ROOT/'data/operational/run_delta.json','source_health.json':ROOT/'data/operational/source_health.json','run_history.json':ROOT/'data/operational/run_history.json'}
for name,src in map_paths.items():
    if src.exists(): shutil.copy2(src,pub/name)
print('Publicación docs/data actualizada.')
