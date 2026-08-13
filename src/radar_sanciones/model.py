from __future__ import annotations
import hashlib,re,unicodedata

def norm_rut(value): return re.sub(r'[^0-9Kk]','',str(value or '')).upper()
def normalizar_nombre(value):
    n=unicodedata.normalize('NFD',str(value or '')).encode('ascii','ignore').decode().upper()
    return re.sub(r'[^A-Z0-9]+',' ',n).strip()
def entity_id(rut='', name=''):
    r=norm_rut(rut)
    if r: return f'ENT-RUT-{r}'
    n=unicodedata.normalize('NFD',str(name or '')).encode('ascii','ignore').decode().upper()
    n=re.sub(r'[^A-Z0-9]+','-',n).strip('-')[:50]
    return f'ENT-NAME-{n or "SIN-ID"}'
def evidence_id(source_record_id): return 'EVD-'+hashlib.sha1(source_record_id.encode()).hexdigest()[:16].upper()