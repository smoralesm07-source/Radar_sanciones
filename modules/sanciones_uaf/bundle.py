"""Ensamble del bundle analítico ``sanciones_uaf.bundle/v1``.

El bundle es el único artefacto que consume la interfaz. Cualquier host —el
HTML autocontenido, el cockpit IFL, un notebook— se acopla leyendo este
contrato y nada más.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from . import adapters
from .classify import (
    SUPERVISOR_DOMAIN,
    ScreeningPolicy,
    classify_subjects,
    score_subject,
)
from .contracts import (
    BUNDLE_SCHEMA,
    CLASSES,
    HYPOTHESIS_STATES,
    HYPOTHESIS_STRENGTH,
    IDENTITY_METHODS,
    MODULE_ID,
    MODULE_VERSION,
    PORTS,
    ModuleInput,
)
from .graph import build_graph
from .metrics import (
    anomalies,
    headline_kpis,
    heatmap_sector_year,
    momentum,
    recurrence_profile,
    sector_matrix,
    temporal_series,
)
from .resolve import UafIndex, resolve_subjects

EVENT_FIELDS = (
    "id", "supervisor", "fecha", "resolucion", "tipo_evento", "estado",
    "categoria", "monto", "unidad", "laft_directo", "resolution_url",
    "source_url", "sector_fuente", "sujeto_fuente",
)


def _slim_event(event: dict[str, Any], subject_id: str) -> dict[str, Any]:
    out = {k: event.get(k) for k in EVENT_FIELDS}
    resumen = (event.get("resumen") or "").strip()
    out["resumen"] = resumen[:420] + ("…" if len(resumen) > 420 else "")
    out["subject_id"] = subject_id
    out["anio"] = int(str(event.get("fecha"))[:4]) if str(event.get("fecha", ""))[:4].isdigit() else None
    return out


def build_bundle(payload: ModuleInput | None = None,
                 workspace: Path | None = None,
                 today: date | None = None) -> dict[str, Any]:
    payload = payload or adapters.collect_input(workspace or adapters.DEFAULT_WORKSPACE)
    today = today or date.today()

    uaf_index = UafIndex(payload.uaf_registry)
    policy = ScreeningPolicy(payload.sii_screening)

    subjects, event_to_subject = resolve_subjects(payload.sanction_events, uaf_index)
    subject_by_id = {s["subject_id"]: s for s in subjects}

    events_by_subject: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in payload.sanction_events:
        sid = event_to_subject.get(str(event.get("id")))
        if sid:
            events_by_subject[sid].append(event)
    for evs in events_by_subject.values():
        evs.sort(key=lambda e: str(e.get("fecha") or ""), reverse=True)

    classify_subjects(subjects, events_by_subject, policy, payload.sii_acteco_by_rut)

    graph = build_graph(subjects, events_by_subject)
    for s in subjects:
        score_subject(s, events_by_subject.get(s["subject_id"], []),
                      graph["degree"].get(s["subject_id"], 0), today)
        s["grado_vinculacion"] = graph["degree"].get(s["subject_id"], 0)
        fechas = sorted(str(e.get("fecha") or "") for e in events_by_subject.get(s["subject_id"], []))
        s["primer_evento"] = fechas[0] if fechas else None
        s["ultimo_evento"] = fechas[-1] if fechas else None
        s["categorias"] = sorted({e.get("categoria") for e in events_by_subject.get(s["subject_id"], []) if e.get("categoria")})
        s["monto_uf"] = round(sum(float(e.get("monto") or 0) for e in events_by_subject.get(s["subject_id"], [])
                                  if (e.get("unidad") or "").upper() == "UF"), 2)

    # El racional de cada factor es idéntico para todos los sujetos: viaja una
    # sola vez como esquema y no multiplicado por cada fila del bundle.
    ier_schema = [
        {"key": f["key"], "label": f["label"], "max": f["max"], "why": f["why"]}
        for f in (subjects[0]["ier_factores"] if subjects else [])
    ]
    for s in subjects:
        for f in s["ier_factores"]:
            f.pop("why", None)
            f.pop("label", None)

    nivel_of = {s["subject_id"]: s["nivel"] for s in subjects}
    sector_of = {s["subject_id"]: s.get("sector_analitico") or "Sin sector" for s in subjects}

    uaf_sector_counts = dict(uaf_index.sector_counts)
    sectors = sector_matrix(subjects, events_by_subject, policy, uaf_sector_counts)
    kpis = headline_kpis(subjects, payload.sanction_events, sectors, len(uaf_index), policy)

    events_slim = [_slim_event(e, event_to_subject.get(str(e.get("id")), "")) for e in payload.sanction_events]

    bundle: dict[str, Any] = {
        "schema": BUNDLE_SCHEMA,
        "module_id": MODULE_ID,
        "module_version": MODULE_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "as_of": today.isoformat(),
        "kpis": kpis,
        "classes": CLASSES,
        "hypothesis_states": HYPOTHESIS_STATES,
        "hypothesis_strength": HYPOTHESIS_STRENGTH,
        "identity_methods": IDENTITY_METHODS,
        "ier_schema": ier_schema,
        "supervisor_domain": SUPERVISOR_DOMAIN,
        "subjects": subjects,
        "events": events_slim,
        "sectors": sectors,
        "graph": {"nodes": graph["nodes"], "edges": graph["edges"], "stats": graph["stats"]},
        "series": temporal_series(payload.sanction_events, event_to_subject, nivel_of),
        "heatmap": heatmap_sector_year(subjects, events_by_subject),
        "recurrence": recurrence_profile(subjects, events_by_subject),
        "momentum": momentum(payload.sanction_events, event_to_subject, sector_of, today),
        "anomalies": anomalies(sectors),
        "distributions": _distributions(subjects, payload.sanction_events, subject_by_id, event_to_subject),
        "traceability": {
            "ports": [p.__dict__ for p in PORTS],
            "port_status": [ps.as_dict() for ps in payload.port_status],
            "provenance": payload.provenance,
            "registro_uaf_indexado": len(uaf_index),
            "sectores_uaf_indexados": len(uaf_sector_counts),
            "politica_screening_sectores": len(policy.by_sector),
            "cobertura_identidad": _identity_coverage(subjects),
        },
        "disclaimer": (
            "Este módulo cruza registros públicos. Figurar en el registro UAF o en "
            "una hipótesis de screening SII no constituye imputación, incumplimiento "
            "ni estimación de riesgo LA/FT de la entidad. Toda coincidencia por "
            "nombre requiere validación documental antes de cualquier uso decisorio."
        ),
    }
    return bundle


def _identity_coverage(subjects: list[dict[str, Any]]) -> dict[str, Any]:
    methods = Counter(s["identity_method"] for s in subjects)
    con_rut = sum(1 for s in subjects if s.get("rut"))
    return {
        "por_metodo": [{"metodo": k, "sujetos": v} for k, v in methods.most_common()],
        "con_rut_publicado": con_rut,
        "sin_rut_publicado": len(subjects) - con_rut,
        "resueltos_por_nombre": sum(v for k, v in methods.items() if k.startswith("NAME")),
        "confianza_media": round(
            sum(s["identity_confidence"] for s in subjects if s["inscrito_uaf"])
            / max(1, sum(1 for s in subjects if s["inscrito_uaf"])), 3),
    }


def _distributions(subjects: list[dict[str, Any]], events: list[dict[str, Any]],
                   subject_by_id: dict[str, dict[str, Any]],
                   event_to_subject: dict[str, str]) -> dict[str, Any]:
    supervisor_nivel: dict[str, Counter] = defaultdict(Counter)
    categoria = Counter()
    estado = Counter()
    for e in events:
        sid = event_to_subject.get(str(e.get("id")))
        nivel = subject_by_id.get(sid, {}).get("nivel", "N0_FUERA_PERIMETRO") if sid else "N0_FUERA_PERIMETRO"
        supervisor_nivel[e.get("supervisor") or "—"][nivel] += 1
        if e.get("categoria"):
            categoria[e["categoria"]] += 1
        if e.get("estado"):
            estado[e["estado"]] += 1
    return {
        "supervisor_nivel": [
            {"supervisor": k, **{n: v.get(n, 0) for n in CLASSES}, "total": sum(v.values())}
            for k, v in sorted(supervisor_nivel.items(), key=lambda kv: -sum(kv[1].values()))
        ],
        "categoria": [{"label": k, "value": v} for k, v in categoria.most_common(12)],
        "estado": [{"label": k, "value": v} for k, v in estado.most_common(8)],
        "hipotesis": [
            {"label": k, "value": v}
            for k, v in Counter(s["hipotesis"] for s in subjects if s["nivel"] == "N2_POTENCIAL_SO").most_common()
        ],
        "banda_ier": [
            {"label": k, "value": v}
            for k, v in Counter(s["ier_banda"] for s in subjects).most_common()
        ],
    }
