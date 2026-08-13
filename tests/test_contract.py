import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def test_seed_or_bootstrap_contract():
    rows=json.load(open(ROOT/'data/silver/sanction_events.json',encoding='utf-8')); meta=json.load(open(ROOT/'data/gold/metadata.json',encoding='utf-8'))
    if meta.get('bootstrap_pending'):
        assert rows==[]
    else:
        assert len(rows)>=10
        assert all(x.get('entity_id') and x.get('source_record_id') and x.get('evidence_id') for x in rows)
def test_target_starts_2020():
    meta=json.load(open(ROOT/'data/gold/metadata.json',encoding='utf-8')); assert meta['target_from_year']==2020
def test_coverage_does_not_claim_complete_without_validation():
    rows=json.load(open(ROOT/'data/gold/coverage_matrix.json',encoding='utf-8')); assert all(x.get('status')!='complete' for x in rows)
