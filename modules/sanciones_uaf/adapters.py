"""Adaptadores de lectura para los puertos del módulo.

Cada adaptador intenta varias rutas conocidas y degrada de forma explícita:
si no encuentra la fuente devuelve lista vacía y un ``PortStatus`` con el
detalle, en vez de fallar. Así el módulo se puede acoplar a un despliegue que
todavía no publica alguna de las tres capas.
"""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Any, Iterable

from .contracts import (
    PORT_SANCIONES,
    PORT_SII_ACTECO_RUT,
    PORT_SII_SCREENING,
    PORT_UAF_REGISTRO,
    ModuleInput,
    PortStatus,
)
from .rut import normalize_rut

# Raíz por defecto: el directorio que contiene los repos Radar_*.
DEFAULT_WORKSPACE = Path(os.environ.get("RADAR_WORKSPACE", Path(__file__).resolve().parents[3]))


def _first_existing(candidates: Iterable[Path]) -> Path | None:
    for path in candidates:
        if path.exists():
            return path
    return None


def _read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _read_csv_semicolon(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh, delimiter=";"))


# ---------------------------------------------------------------------------
# PORT_SANCIONES
# ---------------------------------------------------------------------------

def load_sanciones(workspace: Path = DEFAULT_WORKSPACE) -> tuple[list[dict], list[dict], PortStatus]:
    repo = workspace / "Radar_sanciones"
    events_path = _first_existing([
        repo / "docs" / "data" / "events.json",
        repo / "data" / "silver" / "sanction_events.json",
        Path("docs/data/events.json"),
    ])
    entities_path = _first_existing([
        repo / "docs" / "data" / "entities.json",
        repo / "data" / "silver" / "entities.json",
        Path("docs/data/entities.json"),
    ])
    if events_path is None:
        return [], [], PortStatus(
            PORT_SANCIONES.port_id, PORT_SANCIONES.provider, PORT_SANCIONES.title,
            "ABSENT", 0, "", "No se encontró events.json en Radar_sanciones.",
        )
    events = _read_json(events_path)
    entities = _read_json(entities_path) if entities_path else []
    return events, entities, PortStatus(
        PORT_SANCIONES.port_id, PORT_SANCIONES.provider, PORT_SANCIONES.title,
        "OK", len(events), str(events_path.relative_to(workspace)) if events_path.is_absolute() else str(events_path),
        f"{len(events)} eventos y {len(entities)} entidades consolidadas.",
    )


# ---------------------------------------------------------------------------
# PORT_UAF_REGISTRO
# ---------------------------------------------------------------------------

def load_uaf_registry(workspace: Path = DEFAULT_WORKSPACE) -> tuple[list[dict], PortStatus]:
    repo = workspace / "Radar_UAF"
    parquet_path = repo / "data" / "gold" / "entities.parquet"
    dashboard_path = repo / "docs" / "data" / "dashboard.json"

    if parquet_path.exists():
        try:
            import pyarrow.parquet as pq  # noqa: PLC0415 — dependencia opcional

            rows = pq.read_table(parquet_path).to_pylist()
            rows = [r for r in rows if (r.get("entity_type") or "SUJETO_OBLIGADO") == "SUJETO_OBLIGADO"]
            return rows, PortStatus(
                PORT_UAF_REGISTRO.port_id, PORT_UAF_REGISTRO.provider, PORT_UAF_REGISTRO.title,
                "OK", len(rows), "Radar_UAF/data/gold/entities.parquet",
                "Registro completo de entidades reportantes (corte UAF vigente).",
            )
        except ImportError:
            pass  # cae al dashboard publicado

    if dashboard_path.exists():
        payload = _read_json(dashboard_path)
        rows = [r for r in payload.get("entities", []) if r.get("entity_type") == "SUJETO_OBLIGADO"]
        total = int((payload.get("kpis") or {}).get("entities") or len(rows))
        status = "OK" if len(rows) >= total else "DEGRADED"
        return rows, PortStatus(
            PORT_UAF_REGISTRO.port_id, PORT_UAF_REGISTRO.provider, PORT_UAF_REGISTRO.title,
            status, len(rows), "Radar_UAF/docs/data/dashboard.json",
            f"Muestra publicada de {len(rows)} de {total} inscritos (dashboard recorta la nómina)."
            if status == "DEGRADED" else "Nómina publicada completa.",
        )

    return [], PortStatus(
        PORT_UAF_REGISTRO.port_id, PORT_UAF_REGISTRO.provider, PORT_UAF_REGISTRO.title,
        "ABSENT", 0, "", PORT_UAF_REGISTRO.degradation,
    )


# ---------------------------------------------------------------------------
# PORT_SII_SCREENING
# ---------------------------------------------------------------------------

def load_sii_screening(workspace: Path = DEFAULT_WORKSPACE) -> tuple[list[dict], PortStatus]:
    repo = workspace / "Radar_SII"
    path = _first_existing([
        repo / "config" / "uaf_sii_screening_policy.csv",
        repo / "config" / "uaf_sii_crosswalk_v2.csv",
    ])
    if path is None:
        return [], PortStatus(
            PORT_SII_SCREENING.port_id, PORT_SII_SCREENING.provider, PORT_SII_SCREENING.title,
            "ABSENT", 0, "", PORT_SII_SCREENING.degradation,
        )
    rows = _read_csv_semicolon(path)
    has_policy = any(r.get("screening_priority") for r in rows)
    return rows, PortStatus(
        PORT_SII_SCREENING.port_id, PORT_SII_SCREENING.provider, PORT_SII_SCREENING.title,
        "OK" if has_policy else "DEGRADED", len(rows), f"Radar_SII/config/{path.name}",
        f"{len(rows)} pares sector UAF ↔ ACTECO con clase de screening y universo candidato."
        if has_policy else "Crosswalk empírico sin política de screening: prioridades no disponibles.",
    )


# ---------------------------------------------------------------------------
# PORT_SII_ACTECO_RUT (opcional — habilita confirmación RUT a RUT del Nivel 2)
# ---------------------------------------------------------------------------

def load_sii_acteco_by_rut(workspace: Path = DEFAULT_WORKSPACE) -> tuple[dict[str, list[dict]], PortStatus]:
    repo = workspace / "Radar_SII"
    path = _first_existing([
        repo / "docs" / "data" / "sii_rut_actividades.jsonl",
        repo / "data" / "gold" / "sii_rut_actividades.jsonl",
    ])
    if path is None:
        return {}, PortStatus(
            PORT_SII_ACTECO_RUT.port_id, PORT_SII_ACTECO_RUT.provider, PORT_SII_ACTECO_RUT.title,
            "ABSENT", 0, "",
            "Nómina RUT↔ACTECO no publicada en este despliegue. El Nivel 2 opera "
            "con hipótesis por sector y supervisor; el puerto queda listo para "
            "confirmar RUT a RUT cuando Radar SII publique el extracto.",
        )
    by_rut: dict[str, list[dict]] = {}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            key = normalize_rut(row.get("rut"))
            if key:
                by_rut.setdefault(key, []).append(row)
    return by_rut, PortStatus(
        PORT_SII_ACTECO_RUT.port_id, PORT_SII_ACTECO_RUT.provider, PORT_SII_ACTECO_RUT.title,
        "OK", len(by_rut), str(path.name),
        f"{len(by_rut)} RUT con actividad económica vigente para confirmación directa.",
    )


# ---------------------------------------------------------------------------

def collect_input(workspace: Path = DEFAULT_WORKSPACE) -> ModuleInput:
    """Ejecuta los cuatro adaptadores y arma el payload del motor."""
    events, entities, st_sanc = load_sanciones(workspace)
    uaf_rows, st_uaf = load_uaf_registry(workspace)
    screening, st_scr = load_sii_screening(workspace)
    acteco, st_act = load_sii_acteco_by_rut(workspace)

    provenance: dict[str, Any] = {}
    meta_path = workspace / "Radar_sanciones" / "docs" / "data" / "metadata.json"
    if meta_path.exists():
        provenance["radar_sanciones"] = _read_json(meta_path)
    uaf_dash = workspace / "Radar_UAF" / "docs" / "data" / "dashboard.json"
    if uaf_dash.exists():
        payload = _read_json(uaf_dash)
        provenance["radar_uaf"] = {
            "version": payload.get("version"),
            "generated_at": payload.get("generated_at"),
            "kpis": {
                k: payload.get("kpis", {}).get(k)
                for k in (
                    "registered_private_latest", "registered_public_latest",
                    "registered_total_latest", "registered_total_as_of",
                    "ros_latest", "supervision_latest", "fines_uf_latest",
                )
            },
        }
    sii_sum = workspace / "Radar_SII" / "docs" / "data" / "uaf_sii_empirical_summary.json"
    if sii_sum.exists():
        provenance["radar_sii"] = _read_json(sii_sum)

    return ModuleInput(
        sanction_events=events,
        sanction_entities=entities,
        uaf_registry=uaf_rows,
        sii_screening=screening,
        sii_acteco_by_rut=acteco,
        port_status=[st_sanc, st_uaf, st_scr, st_act],
        provenance=provenance,
    )
