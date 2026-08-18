"""Pruebas del módulo acoplable Radar Sanciones ↔ UAF."""

from __future__ import annotations

from datetime import date

import pytest

from modules.sanciones_uaf.bundle import build_bundle
from modules.sanciones_uaf.classify import (
    ScreeningPolicy,
    classify_subjects,
    name_signature,
)
from modules.sanciones_uaf.contracts import BUNDLE_SCHEMA, ModuleInput, PortStatus
from modules.sanciones_uaf.graph import build_graph
from modules.sanciones_uaf.metrics import herfindahl, wilson_interval
from modules.sanciones_uaf.render import PLACEHOLDER, TEMPLATE, render_html
from modules.sanciones_uaf.resolve import UafIndex, resolve_subjects
from modules.sanciones_uaf.rut import (
    clean_subject_name,
    extract_ruts,
    is_valid_rut,
    normalize_rut,
    token_similarity,
)

# --------------------------------------------------------------------------
# Identificadores
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("76.697.522-4", "76697522-4"),
        ("076697522-4", "76697522-4"),
        ("76697522k", "76697522-K"),
        ("  65063344-K ", "65063344-K"),
        ("", None),
        (None, None),
        ("-", None),
    ],
)
def test_normalize_rut(raw, expected):
    assert normalize_rut(raw) == expected


def test_dv_modulo_11():
    assert is_valid_rut("76697522-4")
    assert is_valid_rut("65063344-K")
    assert not is_valid_rut("76697522-9")


def test_extract_ruts_desde_texto_descarta_dv_invalido():
    texto = "La resolución individualiza a ACME SPA (RUT 76.697.522-4) y a 11.111.111-9."
    assert extract_ruts(texto) == ["76697522-4"]


def test_normalize_name_unifica_grafias_del_sufijo_societario():
    from modules.sanciones_uaf.rut import normalize_name

    assert normalize_name("CASINO DEL LAGO S.A.") == normalize_name("CASINO DEL LAGO SA")
    assert normalize_name("Deportes Osorno S.A.D.P") == normalize_name("DEPORTES OSORNO SADP")


def test_clean_subject_name_quita_encabezado_y_monto():
    assert clean_subject_name("APLICA SANCIÓN A CAMERON PARTNERS S.A. 210 UF") == "CAMERON PARTNERS S.A"
    assert clean_subject_name("EL SEÑOR JUAN PÉREZ") == "JUAN PÉREZ"
    assert clean_subject_name("BANCO DE\nCHILE") == "BANCO DE CHILE"
    # Si al limpiar no queda nada, se devuelve el original normalizado.
    assert clean_subject_name("APLICA SANCIÓN A") == "APLICA SANCIÓN A"


def test_token_similarity_ignora_sufijos_societarios():
    assert token_similarity("CASINO DEL LAGO S.A.", "CASINO DEL LAGO SA") == 1.0
    assert token_similarity("BANCO DE CHILE", "SUPERMERCADOS UNIDOS LTDA") == 0.0


# --------------------------------------------------------------------------
# Resolución de identidad
# --------------------------------------------------------------------------

REGISTRO = [
    {"rut": "76.697.522-4", "name": "Casinos de Juego", "activity": "CASINO DEL LAGO SA",
     "entity_id": "ENT-1", "sector": "PRIVADO"},
    {"rut": "65063344-K", "name": "Notarios", "activity": "GABRIEL OGALDE RODRIGUEZ",
     "entity_id": "ENT-2", "sector": "PRIVADO"},
]


def _evento(**kw):
    base = {"id": "EVT-1", "supervisor": "CMF", "fecha": "2024-05-02",
            "sujeto_fuente": "CASINO DEL LAGO S.A.", "tipo_evento": "Sanción"}
    base.update(kw)
    return base


def test_match_por_rut_gana_sobre_nombre():
    idx = UafIndex(REGISTRO)
    subjects, _ = resolve_subjects([_evento(rut_fuente="76697522-4")], idx)
    assert subjects[0]["identity_method"] == "RUT_EXACT"
    assert subjects[0]["identity_confidence"] == 1.0
    assert subjects[0]["inscrito_uaf"] is True


def test_match_por_nombre_normalizado():
    idx = UafIndex(REGISTRO)
    subjects, _ = resolve_subjects([_evento()], idx)
    assert subjects[0]["identity_method"] == "NAME_EXACT_NORM"
    assert subjects[0]["uaf_sector"] == "Casinos de Juego"


def test_match_difuso_restringido_al_sector():
    idx = UafIndex(REGISTRO)
    ev = _evento(sujeto_fuente="GABRIEL GUSTAVO OGALDE RODRIGUEZ",
                 sector_fuente="Notarios", supervisor="UAF")
    subjects, _ = resolve_subjects([ev], idx)
    assert subjects[0]["identity_method"] == "NAME_FUZZY_SECTOR"
    assert subjects[0]["identity_confidence"] < 1.0


def test_sin_coincidencia_queda_sin_resolver():
    idx = UafIndex(REGISTRO)
    subjects, _ = resolve_subjects([_evento(sujeto_fuente="EMPRESA INEXISTENTE SPA")], idx)
    assert subjects[0]["identity_method"] == "UNRESOLVED"
    assert subjects[0]["inscrito_uaf"] is False


def test_eventos_con_mismo_rut_son_un_solo_sujeto():
    idx = UafIndex(REGISTRO)
    eventos = [
        _evento(id="EVT-1", rut_fuente="76697522-4", sujeto_fuente="CASINO DEL LAGO S.A."),
        _evento(id="EVT-2", rut_fuente="76.697.522-4", sujeto_fuente="Casino del Lago"),
    ]
    subjects, mapping = resolve_subjects(eventos, idx)
    assert len(subjects) == 1
    assert subjects[0]["n_eventos"] == 2
    assert mapping["EVT-1"] == mapping["EVT-2"]


# --------------------------------------------------------------------------
# Clasificación
# --------------------------------------------------------------------------


def test_firma_de_razon_social_prefiere_la_mas_especifica():
    assert name_signature("BANCHILE CORREDORES DE SEGUROS LIMITADA") == "Corredores de seguros"
    assert name_signature("BICE VIDA COMPAÑÍA DE SEGUROS S.A.") == "Compañías de Seguro"
    assert name_signature("SUPERMERCADO LA ESQUINA LTDA") == ""


def _payload(eventos, registro=REGISTRO, screening=None):
    return ModuleInput(
        sanction_events=eventos,
        uaf_registry=registro,
        sii_screening=screening or [],
        port_status=[PortStatus("PORT_SANCIONES_EVENTS", "RADAR_SANCIONES", "t", "OK", len(eventos))],
    )


def test_nivel_1_para_inscrito_sancionado():
    bundle = build_bundle(_payload([_evento(rut_fuente="76697522-4")]), today=date(2026, 1, 1))
    assert bundle["subjects"][0]["nivel"] == "N1_SO_SANCIONADO"
    assert bundle["kpis"]["n1_sancionados"] == 1


def test_nivel_0_para_persona_natural_sancionada_por_cmf():
    """La CMF también sanciona a quien no es sujeto obligado: no debe inflar el Nivel 2."""
    ev = _evento(sujeto_fuente="ANDRÉS FELIPE ROJAS FIGUEROA",
                 categoria="Cumplimiento regulatorio", laft_directo=False)
    bundle = build_bundle(_payload([ev]), today=date(2026, 1, 1))
    assert bundle["subjects"][0]["nivel"] == "N0_FUERA_PERIMETRO"
    assert bundle["subjects"][0]["hipotesis"] == "SIN_HIPOTESIS"


def test_nivel_2_por_materia_laft():
    ev = _evento(sujeto_fuente="COMERCIALIZADORA DEL SUR SPA",
                 categoria="Cumplimiento ALA/CFT/FP", laft_directo=True)
    bundle = build_bundle(_payload([ev]), today=date(2026, 1, 1))
    subject = bundle["subjects"][0]
    assert subject["nivel"] == "N2_POTENCIAL_SO"
    assert subject["hipotesis"] == "INFERIDO_MATERIA_LAFT"


def test_nivel_2_por_supervisor_exclusivo():
    ev = _evento(sujeto_fuente="ENTIDAD DESCONOCIDA SPA", supervisor="UAF",
                 categoria="Otro", laft_directo=False)
    bundle = build_bundle(_payload([ev]), today=date(2026, 1, 1))
    assert bundle["subjects"][0]["hipotesis"] == "INFERIDO_SUPERVISOR"


def test_confirmacion_por_acteco_sii_domina_la_cascada():
    screening = [{
        "uaf_sector": "Casas de cambio", "sii_acteco": "661204",
        "sii_glosa": "ACTIVIDADES DE CASAS DE CAMBIO", "screening_priority": "A",
        "candidate_universe_gross": "528", "uaf_ruts_total": "40",
    }]
    payload = _payload([_evento(sujeto_fuente="CAMBIOS ANDES SPA", rut_fuente="77009274-4")],
                       screening=screening)
    payload.sii_acteco_by_rut = {"77009274-4": [{"rut": "77009274-4", "acteco": "661204", "vigente": True}]}
    bundle = build_bundle(payload, today=date(2026, 1, 1))
    subject = bundle["subjects"][0]
    assert subject["hipotesis"] == "CONFIRMADO_SII"
    assert subject["sector_analitico"] == "Casas de cambio"
    assert subject["hipotesis_fuerza"] == 1.0


# --------------------------------------------------------------------------
# Estadística
# --------------------------------------------------------------------------


def test_wilson_es_conservador_con_denominador_chico():
    lo_chico, hi_chico = wilson_interval(1, 4)
    lo_grande, hi_grande = wilson_interval(250, 1000)
    assert lo_chico < 0.25 < hi_chico
    assert (hi_chico - lo_chico) > (hi_grande - lo_grande)


def test_wilson_denominador_cero():
    assert wilson_interval(0, 0) == (0.0, 0.0)


def test_herfindahl_normalizado():
    assert herfindahl([1, 1, 1, 1]) == 0.0
    assert herfindahl([10, 0, 0, 0]) == 1.0


def test_ier_acotado_y_explicable():
    ev = [_evento(id=f"EVT-{i}", rut_fuente="76697522-4", fecha="2026-01-0%d" % (i + 1),
                  monto=5000, unidad="UF", laft_directo=True) for i in range(6)]
    bundle = build_bundle(_payload(ev), today=date(2026, 2, 1))
    subject = bundle["subjects"][0]
    assert 0 <= subject["ier"] <= 100
    for factor in subject["ier_factores"]:
        schema = next(f for f in bundle["ier_schema"] if f["key"] == factor["key"])
        assert factor["points"] <= schema["max"]


# --------------------------------------------------------------------------
# Grafo y contrato de salida
# --------------------------------------------------------------------------


def _graph_de(eventos):
    """Reproduce la secuencia real del pipeline: resolver, clasificar, graficar."""
    idx = UafIndex(REGISTRO)
    subjects, _ = resolve_subjects(eventos, idx)
    by_subject = {s["subject_id"]: [e for e in eventos if e["id"] in s["event_ids"]]
                  for s in subjects}
    classify_subjects(subjects, by_subject, ScreeningPolicy([]), {})
    return build_graph(subjects, by_subject)


def test_grafo_enlaza_co_resoluciones():
    eventos = [
        _evento(id="EVT-1", rut_fuente="76697522-4", sujeto_fuente="CASINO DEL LAGO S.A.",
                resolucion="8401",
                other_entities_in_resolution=[{"name": "GABRIEL OGALDE RODRIGUEZ", "rut": "65063344-K"}]),
        _evento(id="EVT-2", rut_fuente="65063344-K", sujeto_fuente="GABRIEL OGALDE RODRIGUEZ"),
    ]
    graph = _graph_de(eventos)
    assert graph["stats"]["co_resoluciones"] == 1
    assert all(e["source"] != e["target"] for e in graph["edges"])


def test_ruido_de_extraccion_no_crea_nodos():
    """«DE INVERSIÓN S.A» sin RUT es un fragmento de PDF, no una entidad."""
    eventos = [_evento(id="EVT-1", rut_fuente="76697522-4",
                       other_entities_in_resolution=[{"name": "DE INVERSIÓN S.A", "rut": ""}])]
    assert _graph_de(eventos)["stats"]["menciones"] == 0


def test_bundle_cumple_el_contrato():
    bundle = build_bundle(_payload([_evento(rut_fuente="76697522-4")]), today=date(2026, 1, 1))
    assert bundle["schema"] == BUNDLE_SCHEMA
    for key in ("kpis", "subjects", "events", "sectors", "graph", "series",
                "heatmap", "recurrence", "traceability", "ier_schema", "disclaimer"):
        assert key in bundle, key
    # El racional de los factores viaja una sola vez, no por sujeto.
    assert all("why" not in f for s in bundle["subjects"] for f in s["ier_factores"])


def test_degradacion_sin_registro_uaf_no_rompe():
    bundle = build_bundle(_payload([_evento()], registro=[]), today=date(2026, 1, 1))
    assert bundle["kpis"]["n1_sancionados"] == 0
    assert bundle["kpis"]["inscritos_uaf"] == 0


def test_render_html_embebe_el_bundle(tmp_path):
    assert PLACEHOLDER in TEMPLATE.read_text(encoding="utf-8")
    bundle = build_bundle(_payload([_evento(rut_fuente="76697522-4")]), today=date(2026, 1, 1))
    out = render_html(bundle, tmp_path / "modulo.html")
    html = out.read_text(encoding="utf-8")
    assert PLACEHOLDER not in html
    assert "RadarSancionesUAF" in html
    # Ninguna cadena del bundle puede cerrar el <script> que lo contiene.
    assert "</script>" not in html.split("window.RadarSancionesUAF")[0].split("const BUNDLE =")[1]


def test_politica_de_screening_agrega_por_sector():
    policy = ScreeningPolicy([
        {"uaf_sector": "Bancos", "sii_acteco": "641910", "sii_glosa": "ACTIVIDADES BANCARIAS",
         "screening_priority": "A", "candidate_universe_gross": "38", "uaf_ruts_total": "18"},
        {"uaf_sector": "Bancos", "sii_acteco": "649209", "sii_glosa": "OTRAS",
         "screening_priority": "D", "candidate_universe_gross": "999", "uaf_ruts_total": "18"},
    ])
    sector = policy.sector("Bancos")
    assert sector["prioridad_maxima"] == "A"
    # Sólo los gatillantes prioritarios cuentan para el universo candidato.
    assert sector["universo_candidato"] == 38
