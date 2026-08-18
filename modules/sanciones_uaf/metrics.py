"""Métricas analíticas del módulo.

Todo lo que se grafica en la interfaz se calcula aquí, con la estadística
explícita: intervalos de Wilson para tasas con denominador pequeño, lift
sectorial, concentración de Herfindahl, momentum interanual y un índice de
riesgo de no inscripción para focalizar la fiscalización del Nivel 2.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import date
from typing import Any

from .classify import LAFT_CATEGORIES, ScreeningPolicy, _as_int, _priority_rank


def wilson_interval(hits: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """Intervalo de Wilson: honesto cuando el denominador es de dos dígitos."""
    if total <= 0:
        return (0.0, 0.0)
    p = hits / total
    denom = 1 + z * z / total
    centre = p + z * z / (2 * total)
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total)
    return (max(0.0, (centre - margin) / denom), min(1.0, (centre + margin) / denom))


def herfindahl(counts: list[int]) -> float:
    """HHI normalizado 0..1 sobre la distribución de eventos por entidad."""
    total = sum(counts)
    if total <= 0 or len(counts) <= 1:
        return 0.0
    hhi = sum((c / total) ** 2 for c in counts)
    n = len(counts)
    return round(max(0.0, (hhi - 1 / n) / (1 - 1 / n)), 4)


def gini(values: list[float]) -> float:
    if not values or sum(values) == 0:
        return 0.0
    ordered = sorted(values)
    n = len(ordered)
    cum = sum((i + 1) * v for i, v in enumerate(ordered))
    return round((2 * cum) / (n * sum(ordered)) - (n + 1) / n, 4)


def _year(value: object) -> int | None:
    try:
        return int(str(value)[:4])
    except (TypeError, ValueError):
        return None


def _month(value: object) -> str | None:
    text = str(value or "")
    return text[:7] if len(text) >= 7 else None


def _parse(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------

def sector_matrix(
    subjects: list[dict[str, Any]],
    events_by_subject: dict[str, list[dict[str, Any]]],
    policy: ScreeningPolicy,
    uaf_sector_counts: dict[str, int],
) -> list[dict[str, Any]]:
    """Una fila por sector UAF: perímetro inscrito, brecha SII y presión sancionatoria.

    Es la tabla que alimenta la matriz de priorización (burbuja) y el ranking.
    """
    n1_por_sector: dict[str, list[dict[str, Any]]] = defaultdict(list)
    n2_por_sector: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for s in subjects:
        sector = s.get("sector_analitico") or "Sin sector"
        if s["nivel"] == "N1_SO_SANCIONADO":
            n1_por_sector[sector].append(s)
        elif s["nivel"] == "N2_POTENCIAL_SO":
            n2_por_sector[sector].append(s)

    total_inscritos = sum(uaf_sector_counts.values()) or 1
    total_sancionados = sum(len(v) for v in n1_por_sector.values())
    tasa_global = total_sancionados / total_inscritos

    sectores = set(uaf_sector_counts) | set(n1_por_sector) | set(n2_por_sector)
    rows: list[dict[str, Any]] = []
    for sector in sectores:
        inscritos = uaf_sector_counts.get(sector, 0)
        n1 = n1_por_sector.get(sector, [])
        n2 = n2_por_sector.get(sector, [])
        pol = policy.sector(sector) or {}
        universo = _as_int(pol.get("universo_candidato"))
        prioridad = pol.get("prioridad_maxima", "—")

        eventos_n1 = sum(len(events_by_subject.get(s["subject_id"], [])) for s in n1)
        eventos_n2 = sum(len(events_by_subject.get(s["subject_id"], [])) for s in n2)
        laft = 0
        for s in n1 + n2:
            for e in events_by_subject.get(s["subject_id"], []):
                if e.get("laft_directo") or e.get("categoria") in LAFT_CATEGORIES:
                    laft += 1

        tasa = (len(n1) / inscritos) if inscritos else 0.0
        lo, hi = wilson_interval(len(n1), inscritos) if inscritos else (0.0, 0.0)
        cobertura = inscritos / (inscritos + universo) if (inscritos + universo) else None

        rows.append({
            "sector": sector,
            "inscritos_uaf": inscritos,
            "sancionados_n1": len(n1),
            "eventos_n1": eventos_n1,
            "tasa_penetracion": round(tasa, 5),
            "wilson_low": round(lo, 5),
            "wilson_high": round(hi, 5),
            "lift": round(tasa / tasa_global, 3) if tasa_global and inscritos else None,
            "significativo": bool(inscritos >= 20 and lo > tasa_global),
            "potenciales_n2": len(n2),
            "eventos_n2": eventos_n2,
            "universo_candidato_sii": universo,
            "cobertura_registral": round(cobertura, 5) if cobertura is not None else None,
            "brecha_registral": round(1 - cobertura, 5) if cobertura is not None else None,
            "prioridad_screening": prioridad,
            "prioridad_rank": _priority_rank(prioridad),
            "eventos_laft": laft,
            "ier_max": max((s.get("ier", 0) for s in n1 + n2), default=0),
            "ier_medio": round(sum(s.get("ier", 0) for s in n1 + n2) / len(n1 + n2), 1) if (n1 or n2) else 0,
            "codigos_gatillantes": pol.get("codigos_gatillantes", []),
        })

    for row in rows:
        row["irni"] = _irni(row, tasa_global)
    rows.sort(key=lambda r: (-r["irni"], -r["sancionados_n1"]))
    return rows


def _irni(row: dict[str, Any], tasa_global: float) -> float:
    """Índice de Riesgo de No Inscripción (0..100) por sector.

    Combina cuánto perímetro queda fuera del registro, cuán sancionado está el
    perímetro que sí está dentro, cuánta marca de sanción ya se observa fuera y
    qué tan sólido es el gatillante ACTECO del sector.
    """
    brecha = row.get("brecha_registral")
    if brecha is None:
        brecha_pts = 0.0
    else:
        brecha_pts = 34 * brecha

    presion = row.get("tasa_penetracion") or 0.0
    presion_pts = 26 * min(1.0, (presion / (tasa_global * 3)) if tasa_global else 0.0)

    marcas = row.get("potenciales_n2") or 0
    marcas_pts = min(22.0, 6 * math.log2(marcas + 1) if marcas else 0.0)

    prioridad_pts = {5: 18.0, 4: 18.0, 3: 12.0, 2: 6.0, 1: 2.0}.get(row.get("prioridad_rank", 0), 0.0)

    volumen = row.get("universo_candidato_sii") or 0
    escala = min(1.0, math.log10(volumen + 1) / 5) if volumen else 0.0
    return round(min(100.0, (brecha_pts + presion_pts + marcas_pts + prioridad_pts) * (0.72 + 0.28 * escala)), 1)


# ---------------------------------------------------------------------------

def temporal_series(events: list[dict[str, Any]], subject_of: dict[str, str],
                    nivel_of: dict[str, str]) -> dict[str, Any]:
    """Series mensuales y anuales por nivel de perímetro."""
    per_month: dict[str, Counter] = defaultdict(Counter)
    per_year: dict[int, Counter] = defaultdict(Counter)
    for e in events:
        nivel = nivel_of.get(subject_of.get(str(e.get("id")), ""), "N0_FUERA_PERIMETRO")
        m, y = _month(e.get("fecha")), _year(e.get("fecha"))
        if m:
            per_month[m][nivel] += 1
        if y:
            per_year[y][nivel] += 1
    months = sorted(per_month)
    years = sorted(per_year)
    return {
        "months": months,
        "by_month": {n: [per_month[m].get(n, 0) for m in months]
                     for n in ("N1_SO_SANCIONADO", "N2_POTENCIAL_SO", "N0_FUERA_PERIMETRO")},
        "years": years,
        "by_year": {n: [per_year[y].get(n, 0) for y in years]
                    for n in ("N1_SO_SANCIONADO", "N2_POTENCIAL_SO", "N0_FUERA_PERIMETRO")},
    }


def heatmap_sector_year(subjects: list[dict[str, Any]],
                        events_by_subject: dict[str, list[dict[str, Any]]],
                        top: int = 14) -> dict[str, Any]:
    grid: dict[str, Counter] = defaultdict(Counter)
    for s in subjects:
        if s["nivel"] == "N0_FUERA_PERIMETRO":
            continue
        sector = s.get("sector_analitico") or "Sin sector"
        for e in events_by_subject.get(s["subject_id"], []):
            y = _year(e.get("fecha"))
            if y:
                grid[sector][y] += 1
    years = sorted({y for row in grid.values() for y in row})
    ranked = sorted(grid, key=lambda k: -sum(grid[k].values()))[:top]
    return {
        "sectors": ranked,
        "years": years,
        "values": [[grid[s].get(y, 0) for y in years] for s in ranked],
    }


def recurrence_profile(subjects: list[dict[str, Any]],
                       events_by_subject: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Reincidencia: distribución, intervalo entre sanciones y concentración."""
    dist = Counter()
    gaps: list[int] = []
    for s in subjects:
        evs = events_by_subject.get(s["subject_id"], [])
        dist[min(len(evs), 5)] += 1
        fechas = sorted([d for d in (_parse(e.get("fecha")) for e in evs) if d])
        for a, b in zip(fechas, fechas[1:]):
            delta = (b - a).days
            if 0 < delta <= 365 * 6:
                gaps.append(delta)
    gaps.sort()
    counts = [len(events_by_subject.get(s["subject_id"], [])) for s in subjects]
    return {
        "distribucion": [{"eventos": k if k < 5 else "5+", "sujetos": v} for k, v in sorted(dist.items())],
        "reincidentes": sum(v for k, v in dist.items() if k >= 2),
        "gap_mediano_dias": gaps[len(gaps) // 2] if gaps else None,
        "gap_p25": gaps[len(gaps) // 4] if gaps else None,
        "gap_p75": gaps[(len(gaps) * 3) // 4] if gaps else None,
        "gaps_observados": len(gaps),
        "hhi_normalizado": herfindahl(counts),
        "gini_eventos": gini([float(c) for c in counts]),
        "top_share_10": round(sum(sorted(counts, reverse=True)[:max(1, len(counts) // 10)]) / max(1, sum(counts)), 4),
    }


def momentum(events: list[dict[str, Any]], subject_of: dict[str, str],
             sector_of: dict[str, str], today: date) -> list[dict[str, Any]]:
    """Variación de eventos en 12 meses móviles contra los 12 previos, por sector."""
    recent: Counter = Counter()
    prior: Counter = Counter()
    for e in events:
        d = _parse(e.get("fecha"))
        if not d:
            continue
        sector = sector_of.get(subject_of.get(str(e.get("id")), ""), "Sin sector")
        age = (today - d).days
        if 0 <= age < 365:
            recent[sector] += 1
        elif 365 <= age < 730:
            prior[sector] += 1
    out = []
    for sector in set(recent) | set(prior):
        r, p = recent[sector], prior[sector]
        if r + p < 3:
            continue
        out.append({
            "sector": sector, "ultimos_12m": r, "previos_12m": p,
            "delta": r - p,
            "variacion": round((r - p) / p, 3) if p else None,
        })
    out.sort(key=lambda x: -abs(x["delta"]))
    return out[:16]


def anomalies(sector_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sectores cuya tasa de penetración se desvía del comportamiento del conjunto."""
    pool = [r for r in sector_rows if r["inscritos_uaf"] >= 10]
    if len(pool) < 4:
        return []
    tasas = [r["tasa_penetracion"] for r in pool]
    mu = sum(tasas) / len(tasas)
    var = sum((t - mu) ** 2 for t in tasas) / max(1, len(tasas) - 1)
    sd = math.sqrt(var) or 1e-9
    out = []
    for r in pool:
        z = (r["tasa_penetracion"] - mu) / sd
        if abs(z) >= 1.5:
            out.append({
                "sector": r["sector"], "z": round(z, 2),
                "tasa": r["tasa_penetracion"], "inscritos": r["inscritos_uaf"],
                "sancionados": r["sancionados_n1"],
                "lectura": ("Presión sancionatoria muy por sobre el resto del registro"
                            if z > 0 else "Sector inscrito sin marcas relevantes"),
            })
    out.sort(key=lambda x: -abs(x["z"]))
    return out[:10]


def headline_kpis(subjects: list[dict[str, Any]], events: list[dict[str, Any]],
                  sector_rows: list[dict[str, Any]], uaf_total: int,
                  policy: ScreeningPolicy) -> dict[str, Any]:
    n1 = [s for s in subjects if s["nivel"] == "N1_SO_SANCIONADO"]
    n2 = [s for s in subjects if s["nivel"] == "N2_POTENCIAL_SO"]
    n0 = [s for s in subjects if s["nivel"] == "N0_FUERA_PERIMETRO"]
    confirmados = [s for s in n2 if s["hipotesis"] == "CONFIRMADO_SII"]
    uaf_sanc_no_inscrito = [s for s in n2 if "UAF" in s.get("supervisores", [])]
    universo_a = sum(r["universo_candidato_sii"] for r in sector_rows if r["prioridad_rank"] >= 4)
    lo, hi = wilson_interval(len(n1), uaf_total) if uaf_total else (0.0, 0.0)
    return {
        "eventos_totales": len(events),
        "sujetos_totales": len(subjects),
        "inscritos_uaf": uaf_total,
        "n1_sancionados": len(n1),
        "n1_tasa": round(len(n1) / uaf_total, 5) if uaf_total else 0.0,
        "n1_tasa_ic": [round(lo, 5), round(hi, 5)],
        "n1_eventos": sum(s["n_eventos"] for s in n1),
        "n2_potenciales": len(n2),
        "n2_confirmados_sii": len(confirmados),
        "n2_eventos": sum(s["n_eventos"] for s in n2),
        "n0_fuera": len(n0),
        "uaf_sancionado_sin_inscripcion": len(uaf_sanc_no_inscrito),
        "universo_candidato_prioridad_a": universo_a,
        "sectores_con_brecha": sum(1 for r in sector_rows if (r["brecha_registral"] or 0) > 0.5),
        "criticos": sum(1 for s in subjects if s.get("ier", 0) >= 70),
        "altos": sum(1 for s in subjects if 50 <= s.get("ier", 0) < 70),
        "sectores_politica": len(policy.by_sector),
    }
