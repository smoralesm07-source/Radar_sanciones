"""Clasificación de perímetro (Niveles 0/1/2) y scoring explicable.

Dos preguntas de negocio, dos niveles:

* **Nivel 1** — ¿los sujetos obligados inscritos en la UAF figuran en alguna
  sanción de los supervisores prudenciales?
* **Nivel 2** — ¿los potenciales sujetos obligados (actividad vigente en SII
  pero sin inscripción UAF) tienen alguna marca de sanción?

El scoring nunca es una caja negra: cada punto del índice queda desglosado en
factores con su aporte, para que la ficha lo muestre y sea auditable.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date
from typing import Any

from .contracts import HYPOTHESIS_STATES, HYPOTHESIS_STRENGTH
from .rut import normalize_name

# Dominio regulado por cada supervisor, expresado en sectores UAF.
# Permite formular la hipótesis de obligación cuando no hay ACTECO por RUT.
SUPERVISOR_DOMAIN: dict[str, dict[str, Any]] = {
    "UAF": {
        "label": "Unidad de Análisis Financiero",
        "sectores": ["*"],
        "exclusivo": True,
        "strength": "ALTA",
        "nota": (
            "La UAF sólo sanciona a quien tiene calidad de sujeto obligado; si el "
            "sancionado no aparece en el registro vigente, o se dio de baja o el "
            "cruce de identidad necesita revisión manual."
        ),
    },
    "CMF": {
        "label": "Comisión para el Mercado Financiero",
        "sectores": [
            "Bancos", "Corredores de bolsa de valores", "Agentes de valores",
            "Administradoras generales de fondos", "Administradoras de fondos de inversión",
            "Compañías de Seguro", "Corredores de seguros", "Administradoras de Mutuos Hipotecarios",
            "Institución Financiera", "Cooperativas de ahorro y crédito", "Bolsas de valores",
            "Emisores y operadores de tarjetas de pago", "Casas de cambio",
            "Empresas de factoraje (Factoring)", "Empresas de leasing",
        ],
        "exclusivo": False,
        "strength": "MEDIA_ALTA",
        "nota": (
            "El perímetro CMF se superpone con sectores UAF financieros, pero también "
            "alcanza emisores, auditores y personas naturales que no son sujetos "
            "obligados: sancionar por CMF no basta por sí solo para inferir obligación."
        ),
    },
    "SCJ": {
        "label": "Superintendencia de Casinos de Juego",
        "sectores": ["Casinos de Juego"],
        "exclusivo": True,
        "strength": "ALTA",
        "nota": "Todo operador de casino es sujeto obligado por la Ley 19.913.",
    },
    "SP": {
        "label": "Superintendencia de Pensiones",
        "sectores": ["Administradores de Fondos de Pensiones", "Cajas de Compensación"],
        "exclusivo": False,
        "strength": "MEDIA",
        "nota": "Perímetro previsional con obligación de inscripción parcial.",
    },
    "SUSESO": {
        "label": "Superintendencia de Seguridad Social",
        "sectores": ["Cajas de Compensación"],
        "exclusivo": False,
        "strength": "MEDIA",
        "nota": "Sólo las cajas de compensación son sujetos obligados.",
    },
    "SMA": {
        "label": "Superintendencia del Medio Ambiente",
        "sectores": [],
        "exclusivo": False,
        "strength": "NULA",
        "nota": "Fuera del perímetro ALA/CFT: se conserva como control negativo.",
    },
}

# Firmas de razón social → sector UAF. Es screening onomástico: la denominación
# social declara la actividad regulada con altísima frecuencia en Chile.
SECTOR_NAME_SIGNATURES: tuple[tuple[str, str], ...] = (
    (r"\bBANCO\b", "Bancos"),
    (r"COOPERATIVA DE AHORRO", "Cooperativas de ahorro y crédito"),
    (r"CORREDORA?E?S? DE BOLSA", "Corredores de bolsa de valores"),
    (r"AGENTE DE VALORES", "Agentes de valores"),
    (r"BOLSA DE (VALORES|PRODUCTOS)", "Bolsas de valores"),
    (r"ADMINISTRADORA GENERAL DE FONDOS", "Administradoras generales de fondos"),
    (r"ADMINISTRADORA DE FONDOS DE INVERSI", "Administradoras de fondos de inversión"),
    (r"ADMINISTRADORA DE FONDOS DE PENSIONES|\bAFP\b", "Administradores de Fondos de Pensiones"),
    (r"ADMINISTRADORA DE MUTUOS HIPOTECARIOS|MUTUOS HIPOTECARIOS", "Administradoras de Mutuos Hipotecarios"),
    (r"CAJA DE COMPENSACI", "Cajas de Compensación"),
    # El orden importa: la firma más específica gana antes que la genérica.
    (r"CORREDORA?E?S? DE SEGUROS", "Corredores de seguros"),
    (r"\bSEGUROS?\b|ASEGURADORA", "Compañías de Seguro"),
    (r"CASA DE CAMBIO|CAMBIOS? Y TURISMO", "Casas de cambio"),
    (r"\bCASINO\b", "Casinos de Juego"),
    # normalize_name colapsa «S.A.D.P» en «SADP», por eso basta la forma unida.
    (r"\bSADP\b|CLUB DEPORTIVO|CLUB DE DEPORTES|SOCIEDAD ANONIMA DEPORTIVA",
     "Organizaciones Deportivas Profesionales"),
    (r"FACTORING|FACTORAJE", "Empresas de factoraje (Factoring)"),
    (r"\bLEASING\b", "Empresas de leasing"),
    (r"TRANSFERENCIA DE DINERO|REMESAS", "Empresas de transferencia de dinero"),
    (r"CORREDORA?E?S? DE PROPIEDADES", "Corredores de propiedades"),
    (r"GESTI[OÓ]N INMOBILIARIA|INMOBILIARIA", "Empresas dedicadas a la gestión inmobiliaria"),
    (r"ZONA FRANCA|ZOFRI", "Usuarios de zonas francas"),
    (r"NOTAR[IÍ]A|CONSERVADOR DE BIENES", "Notarios"),
    (r"JOYA|JOYER", "Comerciantes de Joyas y Piedras Preciosas"),
    (r"AUTOMOTRI|AUTOMOVILES|VEHICULOS", "Empresas dedicadas al comercio de vehículos"),
    (r"TARJETA DE (PAGO|CR[EÉ]DITO)", "Emisores y operadores de tarjetas de pago"),
)

# Categorías de sanción que hablan directamente de deberes ALA/CFT.
LAFT_CATEGORIES = {
    "Cumplimiento ALA/CFT/FP",
    "ALA/CFT / debida diligencia",
    "Deberes de información / reportabilidad",
}


class ScreeningPolicy:
    """Política de screening UAF↔SII agregada por sector."""

    def __init__(self, rows: list[dict[str, Any]]):
        self.rows = rows
        self.by_sector: dict[str, dict[str, Any]] = {}
        self.acteco_priority: dict[str, dict[str, Any]] = {}

        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            sector = (row.get("uaf_sector") or "").strip()
            if sector:
                grouped[sector].append(row)

        for sector, items in grouped.items():
            gatillantes = [r for r in items if (r.get("screening_priority") or "").startswith("A")]
            secundarios = [r for r in items if (r.get("screening_priority") or "") == "B"]
            base = gatillantes or secundarios or items
            universo = sum(_as_int(r.get("candidate_universe_gross")) for r in base)
            inscritos = max((_as_int(r.get("uaf_ruts_total")) for r in items), default=0)
            self.by_sector[normalize_name(sector)] = {
                "sector_uaf": sector,
                "inscritos_uaf": inscritos,
                "universo_candidato": universo,
                "codigos_gatillantes": [
                    {
                        "acteco": r.get("sii_acteco"),
                        "glosa": r.get("sii_glosa"),
                        "prioridad": r.get("screening_priority"),
                        "clase": r.get("screening_class"),
                        "uso": r.get("candidate_use"),
                        "universo": _as_int(r.get("candidate_universe_gross")),
                        "riesgo_falso_positivo": r.get("false_positive_risk"),
                        "lectura_legal": r.get("legal_interpretation"),
                    }
                    for r in sorted(base, key=lambda x: -_as_int(x.get("candidate_universe_gross")))[:8]
                ],
                "prioridad_maxima": _best_priority([r.get("screening_priority") for r in items]),
                "n_codigos": len(items),
            }
            for r in items:
                acteco = (r.get("sii_acteco") or "").strip()
                if acteco:
                    prev = self.acteco_priority.get(acteco)
                    if prev is None or _priority_rank(r.get("screening_priority")) > _priority_rank(prev.get("prioridad")):
                        self.acteco_priority[acteco] = {
                            "sector_uaf": sector,
                            "prioridad": r.get("screening_priority"),
                            "clase": r.get("screening_class"),
                            "glosa": r.get("sii_glosa"),
                        }

    def sector(self, name: str) -> dict[str, Any] | None:
        return self.by_sector.get(normalize_name(name))

    def sectors_for_supervisor(self, supervisor: str) -> list[dict[str, Any]]:
        domain = SUPERVISOR_DOMAIN.get(supervisor)
        if not domain:
            return []
        if domain["sectores"] == ["*"]:
            return list(self.by_sector.values())
        out = []
        for name in domain["sectores"]:
            hit = self.sector(name)
            if hit:
                out.append(hit)
        return out


def _as_int(value: object) -> int:
    try:
        return int(float(str(value).strip() or 0))
    except (TypeError, ValueError):
        return 0


_PRIORITY_ORDER = {"D": 1, "C": 2, "B": 3, "A": 4, "A_REGISTRO": 5}


def _priority_rank(value: object) -> int:
    return _PRIORITY_ORDER.get(str(value or "").strip(), 0)


def _best_priority(values: list[object]) -> str:
    best, rank = "—", 0
    for v in values:
        r = _priority_rank(v)
        if r > rank:
            best, rank = str(v), r
    return best


# ---------------------------------------------------------------------------

def classify_subjects(
    subjects: list[dict[str, Any]],
    events_by_subject: dict[str, list[dict[str, Any]]],
    policy: ScreeningPolicy,
    acteco_by_rut: dict[str, list[dict[str, Any]]],
) -> None:
    """Asigna nivel, hipótesis y estado de perímetro a cada sujeto (in place)."""
    for subject in subjects:
        events = events_by_subject.get(subject["subject_id"], [])
        supervisores = subject["supervisores"]

        if subject["inscrito_uaf"]:
            subject["nivel"] = "N1_SO_SANCIONADO"
            subject["hipotesis"] = "NO_APLICA"
            subject["hipotesis_fuerza"] = 1.0
            subject["hipotesis_detalle"] = (
                f"Inscrito en el registro UAF · sector «{subject.get('uaf_sector') or '—'}» "
                f"({subject['identity_evidence']})."
            )
            subject["sector_analitico"] = subject.get("uaf_sector") or subject.get("sector_declarado") or "Sin sector"
            subject["screening_prioridad"] = (policy.sector(subject["sector_analitico"]) or {}).get("prioridad_maxima", "—")
            continue

        # --- No inscrito: se evalúa hipótesis de obligación (Nivel 2) --------
        hypothesis, detail, sector = _build_hypothesis(subject, events, supervisores, policy, acteco_by_rut)
        subject["hipotesis"] = hypothesis
        subject["hipotesis_detalle"] = detail
        subject["hipotesis_fuerza"] = HYPOTHESIS_STRENGTH.get(hypothesis, 0.0)
        subject["sector_analitico"] = sector or subject.get("sector_declarado") or "Sin sector"
        sector_policy = policy.sector(subject["sector_analitico"])
        subject["screening_prioridad"] = (sector_policy or {}).get("prioridad_maxima", "—")
        subject["nivel"] = "N2_POTENCIAL_SO" if hypothesis != "SIN_HIPOTESIS" else "N0_FUERA_PERIMETRO"


def name_signature(nombre: str) -> str:
    """Sector UAF sugerido por la razón social, o cadena vacía."""
    texto = normalize_name(nombre)
    for pattern, sector in SECTOR_NAME_SIGNATURES:
        if re.search(pattern, texto):
            return sector
    return ""


def _build_hypothesis(
    subject: dict[str, Any],
    events: list[dict[str, Any]],
    supervisores: list[str],
    policy: ScreeningPolicy,
    acteco_by_rut: dict[str, list[dict[str, Any]]],
) -> tuple[str, str, str]:
    """Cascada de hipótesis del Nivel 2, de mayor a menor fuerza probatoria.

    Cada peldaño exige una señal propia. No basta con que un supervisor
    financiero haya sancionado: la CMF también sanciona emisores, auditores y
    personas naturales que no son sujetos obligados. Sólo los supervisores con
    competencia *exclusiva* sobre sujetos obligados (UAF, Casinos) sostienen la
    hipótesis por sí solos.
    """
    # 1 — Confirmación documental por actividad económica vigente en el SII.
    rut = subject.get("rut")
    if rut and acteco_by_rut:
        for row in acteco_by_rut.get(rut, []):
            if not row.get("vigente", True):
                continue
            hit = policy.acteco_priority.get(str(row.get("acteco") or "").strip())
            if hit and _priority_rank(hit["prioridad"]) >= _PRIORITY_ORDER["B"]:
                return (
                    "CONFIRMADO_SII",
                    f"ACTECO {row.get('acteco')} «{hit['glosa']}» vigente en SII, "
                    f"gatillante prioridad {hit['prioridad']} del sector «{hit['sector_uaf']}».",
                    hit["sector_uaf"],
                )

    # 2 — La propia resolución clasifica al sancionado en un sector obligado.
    declarado = subject.get("sector_declarado") or ""
    if declarado:
        hit = policy.sector(declarado)
        if hit:
            return (
                "INFERIDO_SECTOR",
                f"La resolución clasifica al sancionado en «{hit['sector_uaf']}», sector con "
                f"obligación de inscripción (prioridad de screening {hit['prioridad_maxima']}).",
                hit["sector_uaf"],
            )
        return (
            "INFERIDO_SECTOR",
            f"La resolución declara el sector «{declarado}», que la política de screening "
            "UAF↔SII aún no homologa a un ACTECO gatillante.",
            declarado,
        )

    # 3 — La materia sancionada son deberes ALA/CFT: el supervisor ya lo trata
    #     como sujeto obligado, sea cual sea el sector.
    laft = [e for e in events if e.get("laft_directo") or e.get("categoria") in LAFT_CATEGORIES]
    if laft:
        firma = name_signature(subject.get("nombre") or "")
        ejemplo = laft[0]
        return (
            "INFERIDO_MATERIA_LAFT",
            f"{len(laft)} de {len(events)} sanciones versan sobre «{ejemplo.get('categoria')}»: "
            f"{ejemplo.get('supervisor')} le exige deberes de prevención propios de un sujeto obligado.",
            firma,
        )

    # 4 — La razón social declara una actividad regulada.
    firma = name_signature(subject.get("nombre") or "")
    if firma:
        pol = policy.sector(firma)
        return (
            "INFERIDO_RAZON_SOCIAL",
            f"La razón social contiene la firma del sector «{firma}»"
            + (f" (prioridad {pol['prioridad_maxima']}, {fmt_universe(pol)})." if pol else
               ", aún sin homologación ACTECO publicada."),
            firma,
        )

    # 5 — Supervisor con competencia exclusiva sobre sujetos obligados.
    for sup in supervisores:
        domain = SUPERVISOR_DOMAIN.get(sup)
        if domain and domain.get("exclusivo"):
            sector = "" if domain["sectores"] == ["*"] else domain["sectores"][0]
            return (
                "INFERIDO_SUPERVISOR",
                f"Sancionado por {domain['label']}. {domain['nota']}",
                sector,
            )

    return ("SIN_HIPOTESIS", HYPOTHESIS_STATES["SIN_HIPOTESIS"], "")


def fmt_universe(pol: dict[str, Any]) -> str:
    universo = _as_int(pol.get("universo_candidato"))
    return f"{universo:,}".replace(",", ".") + " RUT candidatos en SII"


# ---------------------------------------------------------------------------
# Índice de Exposición Regulatoria (IER) — 0..100, explicable factor a factor.
# ---------------------------------------------------------------------------

def score_subject(
    subject: dict[str, Any],
    events: list[dict[str, Any]],
    link_degree: int,
    today: date,
) -> None:
    factors: list[dict[str, Any]] = []

    def add(key: str, label: str, value: str, points: float, cap: float, why: str) -> None:
        factors.append({
            "key": key, "label": label, "value": value,
            "points": round(min(points, cap), 1), "max": cap, "why": why,
        })

    n = len(events)
    add("recurrencia", "Recurrencia sancionatoria", f"{n} evento{'s' if n != 1 else ''}",
        0 if n <= 1 else 8 + (n - 2) * 4.5, 22,
        "Un evento aislado no distingue; la reiteración sí es señal de patrón.")

    uf = sum(float(e.get("monto") or 0) for e in events if (e.get("unidad") or "").upper() == "UF")
    censuras = sum(1 for e in events if (e.get("unidad") or "").lower() == "censura")
    sev_pts = 0.0
    if uf > 0:
        sev_pts += min(16.0, 4 + (uf ** 0.5) * 0.75)
    sev_pts += min(6.0, censuras * 3.0)
    sev_label = f"{uf:,.0f} UF".replace(",", ".") if uf else (f"{censuras} censura(s)" if censuras else "sin monto publicado")
    add("severidad", "Severidad de la sanción", sev_label, sev_pts, 20,
        "Escala cóncava sobre el monto en UF: castiga la magnitud sin dejar que un outlier domine.")

    laft = sum(1 for e in events if e.get("laft_directo") or (e.get("categoria") in LAFT_CATEGORIES))
    add("laft", "Materia ALA/CFT directa", f"{laft} de {n} eventos",
        0 if not laft else 8 + min(10.0, (laft / max(n, 1)) * 10), 18,
        "Distingue la infracción de deberes de prevención de lavado del incumplimiento regulatorio genérico.")

    sups = subject.get("supervisores", [])
    add("convergencia", "Convergencia supervisora", f"{len(sups)} supervisor(es): {', '.join(sups)}",
        0 if len(sups) <= 1 else 6 + (len(sups) - 2) * 3, 12,
        "Ser observado por más de un supervisor es señal transversal, no repetición del mismo hallazgo.")

    fechas = sorted([e.get("fecha") for e in events if e.get("fecha")])
    if fechas:
        try:
            last = date.fromisoformat(fechas[-1][:10])
            months = max(0, (today - last).days / 30.44)
            rec_pts = 15 * (0.5 ** (months / 24))
            rec_label = fechas[-1]
        except ValueError:
            rec_pts, rec_label = 0.0, fechas[-1]
    else:
        rec_pts, rec_label = 0.0, "sin fecha"
    add("recencia", "Recencia del último evento", rec_label, rec_pts, 15,
        "Vida media de 24 meses: una sanción de 2020 pesa la mitad que una de 2022.")

    add("red", "Vinculación en resoluciones", f"{link_degree} entidad(es) co-mencionada(s)",
        min(8.0, link_degree * 2.0), 8,
        "Aparecer junto a otras entidades en la misma resolución sugiere estructura o grupo.")

    gap_pts = (15.0 * subject.get("hipotesis_fuerza", 0.0)
               if subject.get("nivel") == "N2_POTENCIAL_SO" else 0.0)
    add("brecha", "Brecha de perímetro", subject.get("hipotesis", "—"), gap_pts, 15,
        "Sancionado con actividad obligada pero sin inscripción vigente: es el hallazgo accionable del Nivel 2.")

    total = round(min(100.0, sum(f["points"] for f in factors)), 1)
    subject["ier"] = total
    subject["ier_banda"] = ("Crítico" if total >= 70 else "Alto" if total >= 50
                            else "Medio" if total >= 30 else "Bajo")
    subject["ier_factores"] = factors
