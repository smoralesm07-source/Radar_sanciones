# Radar de Sanciones OSINT v0.8

Radar transversal de sanciones y procedimientos regulatorios de Chile, diseñado para interoperar con Radar CGR y Radar SII.

## Principio de arquitectura

`SOURCE_SNAPSHOT -> SANCTION_FACT -> CANONICAL_ENTITY -> DERIVED_FEATURE -> RISK_SIGNAL -> EVIDENCE`

- **Bronze**: snapshot bruto por fuente/fecha, con hash y metadata.
- **Silver**: hechos sancionatorios y entidades normalizadas.
- **Gold**: dashboard, cobertura, señales y catálogo de fuentes.
- **docs/**: publicación GitHub Pages desacoplada del pipeline.

## Foco temporal

El universo objetivo es **2020–hoy**. La v0.8 migra 164 eventos reales heredados del prototipo v0.7 (principalmente 2024–2026) y declara 2020–2023 como **backfill pendiente**, para evitar confundir falta de carga con ausencia de sanciones.

## Núcleo de fuentes

UAF, CMF, SP, SUSESO y SCJ. SII se usa para enriquecimiento de entidad. SMA/SNIFA queda incorporada como primera expansión OSINT no prudencial.

## Llave e identidad

`entity_id = ENT-RUT-{RUT}` cuando el RUT está disponible. El nombre normalizado sólo apoya el matching; no reemplaza el RUT.

## Modelo sancionatorio

Se separan `sanction_case` (procedimiento/resolución) y `sanction_fact` (resultado por entidad). Una resolución colectiva puede producir múltiples hechos, cada uno trazable al mismo caso y documento.

## Backfill 2020+

```bash
pip install -r requirements.txt
python scripts/backfill.py --from-year 2020 --to-year 2026 --sources UAF,CMF,SCJ,SUSESO,SP
python scripts/rebuild_coverage.py
python scripts/publish.py
python scripts/validate_publish.py
```

## Radar diario

La portada prioriza delta/recencia. El histórico 2020+ se usa para reincidencia, clusters y convergencia entre autoridades. Un evento antiguo recién descubierto se marca como **nuevo para el radar**, sin cambiar la fecha real del hecho.

## Guardrails

- una falla de fuente nunca borra el histórico;
- un año pendiente de backfill nunca se muestra como “cero sanciones”;
- formulación de cargos ≠ sanción firme;
- sanciones administrativas no equivalen por sí solas a riesgo LA/FT;
- cada derivación debe conservar evidencia y URL oficial.
