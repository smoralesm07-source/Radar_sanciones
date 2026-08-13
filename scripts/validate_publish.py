from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[1]
required=['docs/data/events.json','docs/data/entities.json','docs/data/metadata.json','docs/data/source_catalog.json','docs/data/coverage_matrix.json']
for p in required:
    f=ROOT/p
    if not f.exists(): raise SystemExit(f'Falta {p}')
    json.load(open(f,encoding='utf-8'))
e=json.load(open(ROOT/'docs/data/events.json',encoding='utf-8')); meta=json.load(open(ROOT/'docs/data/metadata.json',encoding='utf-8'))
if meta.get('bootstrap_pending'):
    print(f'OK bootstrap: {len(e)} eventos; primera captura aún pendiente.')
else:
    if len(e)<10: raise SystemExit(f'Guardrail: sólo {len(e)} eventos; no publicar caída anómala.')
    bad=[x for x in e if not x.get('entity_id') or not x.get('source_record_id') or not x.get('evidence_id')]
    if bad: raise SystemExit(f'Guardrail: {len(bad)} eventos sin identidad/evidencia canónica.')
    print(f'OK: {len(e)} eventos; publicación válida.')
