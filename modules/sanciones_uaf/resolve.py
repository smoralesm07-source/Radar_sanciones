"""Motor de resolución de identidad entre sanciones y registro UAF.

Estrategia en cascada, de mayor a menor confianza:

1. ``RUT_EXACT``          — el evento trae RUT y coincide con el registro.
2. ``RUT_FROM_TEXT``      — el RUT se recupera del resumen/entidades de la resolución.
3. ``NAME_EXACT_NORM``    — razón social normalizada idéntica.
4. ``NAME_FUZZY_SECTOR``  — similitud de tokens alta dentro del mismo sector UAF.
5. ``NAME_FUZZY_GLOBAL``  — similitud muy alta sin restricción de sector.

Cada vínculo queda con método, confianza y evidencia, de modo que la ficha de
entidad pueda mostrar *por qué* se afirmó la coincidencia.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .contracts import IDENTITY_METHODS
from .rut import (
    clean_subject_name,
    extract_ruts,
    is_valid_rut,
    name_tokens,
    normalize_name,
    normalize_rut,
    token_similarity,
)

FUZZY_SECTOR_MIN = 0.82
FUZZY_GLOBAL_MIN = 0.93


class UafIndex:
    """Índice consultable del registro de sujetos obligados."""

    def __init__(self, rows: list[dict[str, Any]]):
        self.by_rut: dict[str, dict[str, Any]] = {}
        self.by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.by_sector: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.records: list[dict[str, Any]] = []
        self.sector_counts: dict[str, int] = defaultdict(int)

        for row in rows:
            rut = normalize_rut(row.get("rut"))
            sector = (row.get("name") or "").strip()
            razon = (row.get("activity") or "").strip()
            record = {
                "rut": rut,
                "rut_valido": is_valid_rut(rut),
                "sector_uaf": sector,
                "sector_key": normalize_name(sector),
                "razon_social": razon,
                "razon_norm": normalize_name(razon),
                "tokens": name_tokens(razon),
                "uaf_entity_id": row.get("entity_id"),
                "ambito": row.get("sector") or "PRIVADO",
            }
            self.records.append(record)
            self.sector_counts[sector] += 1
            if rut and rut not in self.by_rut:
                self.by_rut[rut] = record
            if record["razon_norm"]:
                self.by_name[record["razon_norm"]].append(record)
            if record["sector_key"]:
                self.by_sector[record["sector_key"]].append(record)

    def __len__(self) -> int:
        return len(self.records)

    # -- consultas ---------------------------------------------------------
    def match(self, *, ruts: list[str], nombre: str, sector_hint: str) -> dict[str, Any] | None:
        for idx, rut in enumerate(ruts):
            hit = self.by_rut.get(rut)
            if hit:
                method = "RUT_EXACT" if idx == 0 else "RUT_FROM_TEXT"
                return self._link(hit, method, IDENTITY_METHODS[method], f"RUT {rut}")

        norm = normalize_name(nombre)
        if norm and norm in self.by_name:
            hit = self.by_name[norm][0]
            return self._link(hit, "NAME_EXACT_NORM", IDENTITY_METHODS["NAME_EXACT_NORM"],
                              f"Razón social normalizada idéntica: {norm}")

        best: tuple[float, dict[str, Any]] | None = None
        sector_key = normalize_name(sector_hint)
        pool = self.by_sector.get(sector_key) if sector_key else None
        if pool:
            for cand in pool:
                score = token_similarity(nombre, cand["razon_social"])
                if score >= FUZZY_SECTOR_MIN and (best is None or score > best[0]):
                    best = (score, cand)
            if best:
                score, cand = best
                return self._link(cand, "NAME_FUZZY_SECTOR", round(min(0.85, score * 0.9), 3),
                                  f"Similitud {score:.2f} dentro del sector «{sector_hint}»")

        tokens = name_tokens(nombre)
        if len(tokens) >= 2:
            for cand in self.records:
                if not tokens & cand["tokens"]:
                    continue
                score = token_similarity(nombre, cand["razon_social"])
                if score >= FUZZY_GLOBAL_MIN and (best is None or score > best[0]):
                    best = (score, cand)
            if best:
                score, cand = best
                return self._link(cand, "NAME_FUZZY_GLOBAL", round(min(0.75, score * 0.78), 3),
                                  f"Similitud global {score:.2f} sin restricción de sector")
        return None

    @staticmethod
    def _link(record: dict[str, Any], method: str, confidence: float, evidence: str) -> dict[str, Any]:
        return {
            "uaf_rut": record["rut"],
            "uaf_sector": record["sector_uaf"],
            "uaf_razon_social": record["razon_social"],
            "uaf_entity_id": record["uaf_entity_id"],
            "uaf_ambito": record["ambito"],
            "identity_method": method,
            "identity_confidence": confidence,
            "identity_evidence": evidence,
        }


# ---------------------------------------------------------------------------

def _event_ruts(event: dict[str, Any]) -> list[str]:
    """RUT declarados y recuperados del texto, en orden de confianza."""
    ordered: list[str] = []

    def push(value: object) -> None:
        canonical = normalize_rut(value)
        if canonical and is_valid_rut(canonical) and canonical not in ordered:
            ordered.append(canonical)

    push(event.get("rut_fuente"))
    for extra in event.get("related_subjects") or []:
        if isinstance(extra, dict):
            push(extra.get("rut"))
    for canonical in extract_ruts(event.get("resumen")):
        if canonical not in ordered:
            ordered.append(canonical)
    return ordered


def resolve_subjects(
    events: list[dict[str, Any]],
    uaf_index: UafIndex,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Agrupa eventos en sujetos sancionados y los vincula al registro UAF.

    La clave de agrupación privilegia el RUT: dos eventos con el mismo RUT son
    la misma entidad aunque el supervisor escriba el nombre distinto.
    Devuelve la lista de sujetos y el mapa ``event_id -> subject_id``.
    """
    groups: dict[str, dict[str, Any]] = {}
    event_to_subject: dict[str, str] = {}

    for event in events:
        ruts = _event_ruts(event)
        nombre_fuente = (event.get("sujeto_fuente") or "").strip()
        nombre = clean_subject_name(nombre_fuente)
        sector_hint = (event.get("sector_fuente") or "").strip()
        if ruts:
            key = f"RUT::{ruts[0]}"
        elif nombre:
            key = f"NOM::{normalize_name(nombre)[:80]}"
        else:
            key = f"EVT::{event.get('id')}"

        group = groups.get(key)
        if group is None:
            group = {
                "subject_id": f"SUJ-{len(groups) + 1:04d}",
                "key": key,
                "rut": ruts[0] if ruts else None,
                "rut_candidatos": list(ruts),
                "nombre": nombre,
                "nombre_fuente": nombre_fuente,
                "nombres_alternativos": set(),
                "sector_declarado": sector_hint,
                "event_ids": [],
                "supervisores": set(),
            }
            groups[key] = group
        else:
            if nombre and normalize_name(nombre) != normalize_name(group["nombre"]):
                group["nombres_alternativos"].add(nombre)
            for extra in ruts:
                if extra not in group["rut_candidatos"]:
                    group["rut_candidatos"].append(extra)
            if sector_hint and not group["sector_declarado"]:
                group["sector_declarado"] = sector_hint

        group["event_ids"].append(event.get("id"))
        group["supervisores"].add(event.get("supervisor") or "—")
        event_to_subject[str(event.get("id"))] = group["subject_id"]

    subjects: list[dict[str, Any]] = []
    for group in groups.values():
        link = uaf_index.match(
            ruts=group["rut_candidatos"],
            nombre=group["nombre"],
            sector_hint=group["sector_declarado"],
        ) if len(uaf_index) else None

        subject = {
            "subject_id": group["subject_id"],
            "rut": group["rut"],
            "rut_valido": is_valid_rut(group["rut"]) if group["rut"] else False,
            "nombre": group["nombre"] or "(sujeto sin nombre publicado)",
            "nombre_fuente": group["nombre_fuente"],
            "nombres_alternativos": sorted(group["nombres_alternativos"])[:6],
            "sector_declarado": group["sector_declarado"],
            "supervisores": sorted(group["supervisores"]),
            "event_ids": group["event_ids"],
            "n_eventos": len(group["event_ids"]),
            "inscrito_uaf": bool(link),
            "identity_method": link["identity_method"] if link else "UNRESOLVED",
            "identity_confidence": link["identity_confidence"] if link else 0.0,
            "identity_evidence": link["identity_evidence"] if link else "",
        }
        if link:
            subject.update({
                "uaf_rut": link["uaf_rut"],
                "uaf_sector": link["uaf_sector"],
                "uaf_razon_social": link["uaf_razon_social"],
                "uaf_entity_id": link["uaf_entity_id"],
                "uaf_ambito": link["uaf_ambito"],
            })
        subjects.append(subject)

    return subjects, event_to_subject
