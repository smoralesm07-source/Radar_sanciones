"""Contratos de entrada/salida del módulo.

El módulo es acoplable: no asume rutas ni repositorios, sólo *puertos*. Cada
puerto declara qué campos necesita, cuáles son opcionales y qué ocurre si la
fuente no está disponible (degradación explícita, nunca silenciosa).

Acoplar el módulo a otro entorno = implementar los tres puertos y llamar a
``bundle.build_bundle``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

MODULE_ID = "MOD_SANCIONES_UAF"
MODULE_VERSION = "1.0.0"
BUNDLE_SCHEMA = "sanciones_uaf.bundle/v1"


@dataclass(frozen=True)
class PortSpec:
    port_id: str
    title: str
    provider: str
    required_fields: tuple[str, ...]
    optional_fields: tuple[str, ...]
    degradation: str
    purpose: str


PORT_SANCIONES = PortSpec(
    port_id="PORT_SANCIONES_EVENTS",
    title="Eventos sancionatorios de supervisores prudenciales",
    provider="RADAR_SANCIONES",
    required_fields=("id", "supervisor", "fecha", "sujeto_fuente", "tipo_evento"),
    optional_fields=(
        "rut_fuente", "sector_fuente", "resolucion", "resolution_url", "source_url",
        "monto", "unidad", "categoria", "laft_directo", "estado", "resumen",
        "other_entities_in_resolution", "related_subjects", "entity_id", "evidence_id",
    ),
    degradation="BLOQUEANTE — sin eventos el módulo no tiene objeto.",
    purpose="Universo de sanciones publicadas que se contrasta contra el perímetro UAF.",
)

PORT_UAF_REGISTRO = PortSpec(
    port_id="PORT_UAF_REGISTRO",
    title="Registro de sujetos obligados inscritos en la UAF",
    provider="RADAR_UAF",
    required_fields=("rut", "activity", "name"),
    optional_fields=("sector", "entity_id", "normalized_name", "source_document_id"),
    degradation=(
        "DEGRADADO — sin registro no hay Nivel 1; todo sancionado queda "
        "'perímetro indeterminado' y el módulo lo declara en trazabilidad."
    ),
    purpose="Define el perímetro de sujeto obligado inscrito (Nivel 1).",
)

PORT_SII_SCREENING = PortSpec(
    port_id="PORT_SII_SCREENING",
    title="Política de screening empírico UAF↔SII por actividad económica",
    provider="RADAR_SII",
    required_fields=("uaf_sector", "sii_acteco", "sii_glosa", "screening_priority"),
    optional_fields=(
        "screening_class", "candidate_use", "candidate_universe_gross",
        "legal_interpretation", "sii_ruts_with_code", "uaf_ruts_total",
        "coverage_sector", "lift_vs_uaf", "false_positive_risk", "empirical_score",
    ),
    degradation=(
        "DEGRADADO — sin política de screening el Nivel 2 se calcula sólo con "
        "hipótesis por supervisor y queda marcado como INFERIDO_DEBIL."
    ),
    purpose="Define el universo de potenciales sujetos obligados no inscritos (Nivel 2).",
)

PORT_SII_ACTECO_RUT = PortSpec(
    port_id="PORT_SII_ACTECO_RUT",
    title="Actividades económicas vigentes por RUT (nómina SII personas jurídicas)",
    provider="RADAR_SII",
    required_fields=("rut", "acteco", "vigente"),
    optional_fields=("razon_social", "region", "tramo_ventas", "fecha_inicio"),
    degradation=(
        "OPCIONAL — cuando no está, el Nivel 2 confirma por sector/supervisor "
        "(estado INFERIDO). Cuando está, cada candidato pasa a CONFIRMADO_SII."
    ),
    purpose="Permite confirmar RUT a RUT que un sancionado es potencial sujeto obligado.",
)

PORTS: tuple[PortSpec, ...] = (
    PORT_SANCIONES,
    PORT_UAF_REGISTRO,
    PORT_SII_SCREENING,
    PORT_SII_ACTECO_RUT,
)


@dataclass
class PortStatus:
    """Estado observado de un puerto tras intentar leerlo."""

    port_id: str
    provider: str
    title: str
    status: str  # OK | DEGRADED | ABSENT
    records: int = 0
    source: str = ""
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "port_id": self.port_id,
            "provider": self.provider,
            "title": self.title,
            "status": self.status,
            "records": self.records,
            "source": self.source,
            "detail": self.detail,
        }


@dataclass
class ModuleInput:
    """Payload completo que consume el motor, independiente del origen."""

    sanction_events: list[dict[str, Any]] = field(default_factory=list)
    sanction_entities: list[dict[str, Any]] = field(default_factory=list)
    uaf_registry: list[dict[str, Any]] = field(default_factory=list)
    sii_screening: list[dict[str, Any]] = field(default_factory=list)
    sii_acteco_by_rut: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    port_status: list[PortStatus] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)

    def status_of(self, port_id: str) -> str:
        for ps in self.port_status:
            if ps.port_id == port_id:
                return ps.status
        return "ABSENT"


Loader = Callable[[], Iterable[dict[str, Any]]]


# ---------------------------------------------------------------------------
# Taxonomía de clasificación — es el corazón semántico del módulo.
# ---------------------------------------------------------------------------

CLASSES = {
    "N1_SO_SANCIONADO": {
        "label": "Sujeto obligado inscrito con sanción",
        "short": "N1 · Inscrito sancionado",
        "level": 1,
        "color": "uaf",
        "definition": (
            "El sancionado está inscrito en el Registro de Entidades Reportantes de "
            "la UAF al corte vigente. El cruce es de identidad, no de mérito: no "
            "implica incumplimiento ALA/CFT salvo que la propia sanción lo declare."
        ),
    },
    "N2_POTENCIAL_SO": {
        "label": "Potencial sujeto obligado no inscrito con marca de sanción",
        "short": "N2 · Potencial no inscrito",
        "level": 2,
        "color": "sii",
        "definition": (
            "El sancionado NO figura en el registro UAF pero su actividad o su "
            "supervisor lo sitúa dentro de un sector con obligación de inscripción. "
            "Es una hipótesis de screening, nunca una determinación jurídica."
        ),
    },
    "N0_FUERA_PERIMETRO": {
        "label": "Sancionado fuera del perímetro UAF observable",
        "short": "N0 · Fuera de perímetro",
        "level": 0,
        "color": "neutral",
        "definition": (
            "No hay evidencia de inscripción ni de actividad gatillante. Se mantiene "
            "en el módulo como control negativo y para no inflar los niveles 1 y 2."
        ),
    },
}

# Cascada de hipótesis del Nivel 2, de mayor a menor fuerza probatoria.
HYPOTHESIS_STATES = {
    "CONFIRMADO_SII": "ACTECO vigente en la nómina SII coincide con un gatillante UAF del sector.",
    "INFERIDO_SECTOR": "La propia resolución clasifica al sancionado en un sector UAF obligado.",
    "INFERIDO_MATERIA_LAFT": "La sanción versa sobre deberes ALA/CFT: el supervisor lo trata como sujeto obligado.",
    "INFERIDO_RAZON_SOCIAL": "La razón social declara una actividad propia de un sector obligado.",
    "INFERIDO_SUPERVISOR": "El supervisor sólo tiene competencia sancionatoria sobre sujetos obligados.",
    "SIN_HIPOTESIS": "No hay señal de obligación de inscripción: queda fuera del perímetro observable.",
}

HYPOTHESIS_STRENGTH = {
    "CONFIRMADO_SII": 1.00,
    "INFERIDO_SECTOR": 0.80,
    "INFERIDO_MATERIA_LAFT": 0.72,
    "INFERIDO_RAZON_SOCIAL": 0.55,
    "INFERIDO_SUPERVISOR": 0.45,
    "SIN_HIPOTESIS": 0.0,
}

IDENTITY_METHODS = {
    "RUT_EXACT": 1.00,
    "RUT_FROM_TEXT": 0.92,
    "NAME_EXACT_NORM": 0.88,
    "NAME_FUZZY_SECTOR": 0.74,
    "NAME_FUZZY_GLOBAL": 0.60,
    "UNRESOLVED": 0.0,
}
