from __future__ import annotations
from .common import get_html, soup, latest_date

REGISTER_URL='https://snifa.sma.gob.cl/RegistroPublico'

def collect(registry:list[dict], since_year:int=2020, enabled:bool=False):
    if not enabled:
        return [], {'source':'SMA','checked_at':'','url':REGISTER_URL,'fetch_status':'scheduled','parse_status':'not_run','rows_seen':0,'events_emitted':0,'latest_event_date':'','message':'Conector de expansión planificado: Registro Público de Sanciones / Datos Abiertos SNIFA.','mode':'scheduled'}
    html,h=get_html(REGISTER_URL); h.source='SMA'
    if not html: return [],h.to_dict()
    h.parse_status='degraded'; h.message='Página accesible; ingestión productiva debe usar Datos Abiertos SNIFA o endpoint estructurado validado.'
    return [],h.to_dict()
