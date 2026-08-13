from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[1]
events=json.load(open(ROOT/'data/silver/sanction_events.json',encoding='utf-8'))
catalog=json.load(open(ROOT/'data/gold/source_catalog.json',encoding='utf-8'))
years=range(2020,2027); rows=[]
for src in [x for x in catalog if x.get('tier')=='core']:
    for y in years:
        n=sum(1 for e in events if e.get('supervisor')==src['source_id'] and str(e.get('fecha','')).startswith(str(y)))
        rows.append({'source_id':src['source_id'],'year':y,'events_loaded':n,'status':'loaded_partial' if n else 'pending_backfill','target':True})
json.dump(rows,open(ROOT/'data/gold/coverage_matrix.json','w',encoding='utf-8'),ensure_ascii=False,indent=2)
print('Cobertura reconstruida.')
