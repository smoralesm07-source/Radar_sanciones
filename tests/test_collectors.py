from pathlib import Path
from radar_sanciones.collectors import uaf, cmf
from radar_sanciones.collectors.cmf_document_agent import analyze_pages
from radar_sanciones.collectors.common import SourceHealth, merge_preserving_rich

FIX=Path(__file__).parent/'fixtures'
REG=[
 {'rut':'76000000-1','nombre':'FACTORING DEL SUR SPA','actividad':'Empresas de factoraje (Factoring)'},
 {'rut':'97023000-9','nombre':'BANCO ITAU CHILE','actividad':'Bancos'},
]

def fake(module,name):
    html=(FIX/name).read_text(encoding='utf-8')
    def _get(url):
        return html, SourceHealth(source='',checked_at='2026-08-11T16:00:00-04:00',url=url,http_status=200,fetch_status='ok')
    module.get_html=_get

def test_uaf_table_and_reposition():
    fake(uaf,'uaf.html'); ev,h=uaf.collect(REG,2024)
    assert len(ev)==2
    assert ev[0]['rut']=='76000000-1'
    assert ev[1]['tipo_evento']=='Recurso de reposición'
    assert h['parse_status']=='ok'

def test_cmf_collective_goes_to_pdf_queue():
    fake(cmf,'cmf.html'); ev,h=cmf.collect(REG,2024,document_mode=False)
    assert len(ev)==2
    normal=[x for x in ev if x['resolucion']=='6786'][0]
    collective=[x for x in ev if x['resolucion']=='6782'][0]
    assert normal['rut']=='97023000-9'
    assert collective['needs_pdf_enrichment'] is True
    assert not collective.get('rut')

def test_merge_preserves_enrichment():
    base=[{'supervisor':'CMF','resolucion':'1','rut':'1-9','fecha':'2026-01-01','sujeto_fuente':'X','tipo_evento':'Sanción','categoria':'Control interno','resumen':'Detalle rico','estado':'Publicado'}]
    live=[{'supervisor':'CMF','resolucion':'1','rut':'1-9','fecha':'2026-01-01','sujeto_fuente':'X','tipo_evento':'Sanción','categoria':'Pendiente','resumen':'Título corto','estado':'Ejecutoriada'}]
    out=merge_preserving_rich(base,live)
    assert out[0]['categoria']=='Control interno'
    assert out[0]['resumen']=='Detalle rico'
    assert out[0]['estado']=='Ejecutoriada'


def test_cmf_document_agent_desagrega_sociedades_que_indica():
    pages=[
        """REF.: APLICA SANCIÓN A SOCIEDADES QUE INDICA.\nIII. INFRACCIONES A LOS DEBERES DE INFORMACIÓN CONTINUA.\nIII.1. TRASANDINO S.A.D.P., RUT N° 76.259.275-4\n1. Requerimiento imputando la siguiente infracción.\n2. sanción de CENSURA.""",
        """III.2. LILAS S.A.D.P., RUT N° 76.264.096-1\n1. Requerimiento imputando la siguiente infracción.\n2. sanción de 180 U.F.""",
        """EL CONSEJO DE LA COMISIÓN PARA EL MERCADO FINANCIERO RESUELVE:\n2. Aplicar a las entidades la sanción siguiente:\nSOCIEDAD SANCIÓN\n1 TRASANDINO S.A.D.P. Censura\n2 LILAS S.A.D.P. Multa UF 180\n3. Remítase a cada sancionado.""",
    ]
    a=analyze_pages(pages)
    legal=[x for x in a['subjects'] if x['subject_kind']=='legal_entity']
    assert a['status']=='enriched'
    assert len(legal)==2
    by={x['rut']:x for x in legal}
    assert by['76259275-4']['sanction_kind']=='Censura'
    assert by['76264096-1']['monto']==180
    assert by['76264096-1']['unidad']=='UF'


def test_cmf_document_agent_multi_entidad_individual_con_rut():
    pages=[
        """REF.: APLICA SANCIÓN A CHUBB SEGUROS CHILE S.A. Y BANCHILE CORREDORES DE SEGUROS LIMITADA""",
        """VI. DECISIÓN\nI.- Respecto de Chubb Seguros Chile S.A.:\na) Incumplimiento de la obligación legal de cumplir instrucciones de la CMF por comercializar pólizas contrarias a la ley.\nII.- Respecto de Banchile Corredores de Seguros Limitada:\na) Incumplimiento de la obligación legal de cumplir instrucciones de la CMF por intermediar pólizas contrarias a la ley.""",
        """EL CONSEJO DE LA COMISIÓN PARA EL MERCADO FINANCIERO RESUELVE:\n1. Aplicar a CHUBB SEGUROS CHILE S.A., RUT N° 99.225.000-3, la sanción de censura.\n2. Aplicar a BANCHILE CORREDORES DE SEGUROS LIMITADA, RUT N° 77.191.070-K, la sanción de censura.""",
    ]
    a=analyze_pages(pages)
    legal=[x for x in a['subjects'] if x['subject_kind']=='legal_entity']
    assert len(legal)==2
    assert all(x['sanction_kind']=='Censura' for x in legal)
    assert all(x['category']=='Conducta de mercado / seguros' for x in legal)


def test_merge_prunes_cmf_collective_placeholder_when_children_exist():
    base=[{'supervisor':'CMF','resolucion':'9','fecha':'2026-01-01','sujeto_fuente':'SOCIEDADES QUE INDICA','tipo_evento':'Sanción','needs_pdf_enrichment':True}]
    live=[{'supervisor':'CMF','resolucion':'9','fecha':'2026-01-01','sujeto_fuente':'EMPRESA A S.A.','rut_fuente':'76000000-1','tipo_evento':'Sanción','needs_pdf_enrichment':False}]
    out=merge_preserving_rich(base,live)
    assert len(out)==1
    assert out[0]['sujeto_fuente']=='EMPRESA A S.A.'

def test_cmf_document_agent_limpia_pie_validacion_en_ultima_fila():
    pages=[
        """III.1. AUDAX ITALIANO LA FLORIDA S.A.D.P., RUT N° 76.670.340-2""",
        """EL CONSEJO DE LA COMISIÓN PARA EL MERCADO FINANCIERO RESUELVE:\nSOCIEDAD SANCIÓN\n1 AUDAX ITALIANO LA FLORIDA S.A.D.P. Multa UF 60 Para validar ir a http://www.svs.cl/institucional/validar/validar.php FOLIO: RES-1-1 SGD: 123 Página 2/3\n3. Remítase.""",
    ]
    a=analyze_pages(pages)
    legal=[x for x in a['subjects'] if x['subject_kind']=='legal_entity']
    assert len(legal)==1
    assert legal[0]['name']=='AUDAX ITALIANO LA FLORIDA S.A.D.P.'
    assert legal[0]['monto']==60
