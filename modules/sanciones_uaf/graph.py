"""Construcción del grafo de vinculación.

El grafo no es decorativo: cada arista corresponde a un hecho verificable en la
fuente. Se construyen cuatro tipos de relación.

* ``sancion``      — el supervisor sancionó al sujeto.
* ``perimetro``    — el sujeto pertenece a un sector UAF (inscrito o hipotético).
* ``co_resolucion``— dos entidades individualizadas en la misma resolución.
* ``mencion``      — entidad mencionada en la resolución sin sanción propia.

La arista ``co_resolucion`` es la que revela estructuras: administradora y fondo,
matriz y filial, personas naturales junto a la sociedad sancionada.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .rut import (
    clean_subject_name,
    is_valid_rut,
    name_tokens,
    normalize_name,
    normalize_rut,
    token_similarity,
)


def build_graph(
    subjects: list[dict[str, Any]],
    events_by_subject: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    seen_edges: set[tuple[str, str, str]] = set()

    by_rut = {s["rut"]: s for s in subjects if s.get("rut")}
    by_name = {normalize_name(s["nombre"]): s for s in subjects if s.get("nombre")}

    def add_node(node_id: str, **attrs: Any) -> None:
        if node_id not in nodes:
            nodes[node_id] = {"id": node_id, **attrs}
        else:
            nodes[node_id]["weight"] = nodes[node_id].get("weight", 1) + 1

    def add_edge(src: str, dst: str, kind: str, label: str = "", weight: float = 1.0) -> None:
        if src == dst:
            return
        key = (src, dst, kind) if src < dst else (dst, src, kind)
        if key in seen_edges:
            for e in edges:
                if (e["source"], e["target"], e["kind"]) in (key, (key[1], key[0], key[2])):
                    e["weight"] += weight
                    return
            return
        seen_edges.add(key)
        edges.append({"source": src, "target": dst, "kind": kind, "label": label, "weight": weight})

    # --- nodos de sujeto ---------------------------------------------------
    for s in subjects:
        nid = f"S::{s['subject_id']}"
        add_node(
            nid, type="sujeto", label=s["nombre"][:52],
            nivel=s.get("nivel", "N0_FUERA_PERIMETRO"),
            rut=s.get("rut"), ier=s.get("ier", 0), eventos=s["n_eventos"],
            sector=s.get("sector_analitico"), subject_id=s["subject_id"],
            weight=max(1, s["n_eventos"]),
        )
        sector = s.get("sector_analitico")
        if sector and sector != "Sin sector":
            sid = f"C::{sector}"
            add_node(sid, type="sector", label=sector, weight=1)
            add_edge(nid, sid, "perimetro",
                     "inscrito" if s.get("inscrito_uaf") else "hipótesis")
        for sup in s.get("supervisores", []):
            pid = f"P::{sup}"
            add_node(pid, type="supervisor", label=sup, weight=1)
            add_edge(nid, pid, "sancion", sup)

    # --- co-resolución y menciones ----------------------------------------
    degree: dict[str, int] = defaultdict(int)
    for s in subjects:
        nid = f"S::{s['subject_id']}"
        for event in events_by_subject.get(s["subject_id"], []):
            related = list(event.get("other_entities_in_resolution") or [])
            related += list(event.get("related_subjects") or [])
            for item in related:
                if not isinstance(item, dict):
                    continue
                nombre = clean_subject_name(item.get("name"))
                rut = normalize_rut(item.get("rut"))
                if rut and not is_valid_rut(rut):
                    rut = None
                # Un fragmento como «DE INVERSIÓN S.A» es ruido de extracción del
                # PDF, no una entidad: sin RUT y sin dos tokens propios, se descarta.
                tokens = name_tokens(nombre)
                if not rut and len(tokens) < 2:
                    continue

                counterpart = by_rut.get(rut) if rut else None
                if counterpart is None and nombre:
                    counterpart = by_name.get(normalize_name(nombre))
                    if counterpart is None:
                        best_score = 0.0
                        for other in subjects:
                            if not tokens & name_tokens(other["nombre"]):
                                continue
                            score = token_similarity(nombre, other["nombre"])
                            if score >= 0.9 and score > best_score:
                                counterpart, best_score = other, score

                if counterpart is not None and counterpart["subject_id"] != s["subject_id"]:
                    tid = f"S::{counterpart['subject_id']}"
                    add_edge(nid, tid, "co_resolucion",
                             f"Resolución {event.get('resolucion') or '—'} ({event.get('supervisor')})")
                    degree[s["subject_id"]] += 1
                    degree[counterpart["subject_id"]] += 1
                elif counterpart is None:
                    label = (nombre or rut or "")[:48]
                    tid = f"V::{rut or normalize_name(nombre)[:40]}"
                    add_node(tid, type="vinculada", label=label, rut=rut, weight=1)
                    add_edge(nid, tid, "mencion",
                             f"Individualizada en resolución {event.get('resolucion') or '—'}")
                    degree[s["subject_id"]] += 1

    for node in nodes.values():
        if node["type"] == "sujeto":
            node["grado_vinculacion"] = degree.get(node["subject_id"], 0)

    return {
        "nodes": list(nodes.values()),
        "edges": edges,
        "degree": dict(degree),
        "stats": {
            "nodos": len(nodes),
            "aristas": len(edges),
            "co_resoluciones": sum(1 for e in edges if e["kind"] == "co_resolucion"),
            "menciones": sum(1 for e in edges if e["kind"] == "mencion"),
            "componentes": _components(nodes, edges),
        },
    }


def _components(nodes: dict[str, dict[str, Any]], edges: list[dict[str, Any]]) -> int:
    """Componentes conexos considerando sólo aristas entre entidades."""
    parent: dict[str, str] = {n: n for n in nodes}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for e in edges:
        if e["kind"] not in {"co_resolucion", "mencion"}:
            continue
        a, b = find(e["source"]), find(e["target"])
        if a != b:
            parent[a] = b
    roots = {find(n) for n, node in nodes.items() if node["type"] in {"sujeto", "vinculada"}}
    return len(roots)
