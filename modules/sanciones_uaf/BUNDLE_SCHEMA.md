# Contrato de salida `sanciones_uaf.bundle/v1`

Artefacto único que consume la interfaz. Cualquier host —el HTML autocontenido,
el cockpit IFL, un notebook— se acopla leyendo este contrato y nada más.

## Raíz

| Clave | Tipo | Descripción |
|---|---|---|
| `schema` | str | Siempre `sanciones_uaf.bundle/v1` |
| `module_id` / `module_version` | str | Identidad del módulo que lo produjo |
| `generated_at` / `as_of` | str | ISO-8601 UTC / fecha de corte del cálculo |
| `kpis` | obj | Cifras de portada (ver abajo) |
| `classes` | obj | Taxonomía N0/N1/N2 con definición legible |
| `hypothesis_states` / `hypothesis_strength` | obj | Cascada del Nivel 2 y su peso |
| `identity_methods` | obj | Métodos de vínculo y confianza base |
| `ier_schema` | lista | Racional y tope de cada factor del IER (viaja una vez) |
| `supervisor_domain` | obj | Dominio regulado por supervisor |
| `subjects` | lista | Un registro por sujeto sancionado |
| `events` | lista | Eventos sancionatorios adelgazados |
| `sectors` | lista | Matriz sectorial |
| `graph` | obj | `nodes`, `edges`, `stats` |
| `series` / `heatmap` / `recurrence` / `momentum` / `anomalies` / `distributions` | obj | Agregados precalculados |
| `traceability` | obj | Puertos, estado, procedencia y cobertura de identidad |
| `disclaimer` | str | Límite de uso, obligatorio de mostrar |

## `kpis`

`eventos_totales`, `sujetos_totales`, `inscritos_uaf`, `n1_sancionados`,
`n1_tasa`, `n1_tasa_ic` (par Wilson 95 %), `n1_eventos`, `n2_potenciales`,
`n2_confirmados_sii`, `n2_eventos`, `n0_fuera`,
`uaf_sancionado_sin_inscripcion`, `universo_candidato_prioridad_a`,
`sectores_con_brecha`, `criticos`, `altos`, `sectores_politica`.

## `subjects[]`

```jsonc
{
  "subject_id": "SUJ-0042",
  "rut": "76697522-4", "rut_valido": true,
  "nombre": "CASINO DEL LAGO S.A",          // limpio, comparable
  "nombre_fuente": "APLICA SANCIÓN A ...",  // tal como lo publica el supervisor
  "nombres_alternativos": ["…"],
  "sector_declarado": "Casinos de Juego",   // el que trae la resolución
  "sector_analitico": "Casinos de Juego",   // el que usa el módulo
  "supervisores": ["SCJ"], "event_ids": ["EVT-0104"], "n_eventos": 3,

  "inscrito_uaf": true,
  "identity_method": "RUT_EXACT", "identity_confidence": 1.0,
  "identity_evidence": "RUT 76697522-4",
  "uaf_rut": "76697522-4", "uaf_sector": "…", "uaf_razon_social": "…",
  "uaf_entity_id": "ENT-…", "uaf_ambito": "PRIVADO",

  "nivel": "N1_SO_SANCIONADO",
  "hipotesis": "NO_APLICA", "hipotesis_detalle": "…", "hipotesis_fuerza": 1.0,
  "screening_prioridad": "A",

  "primer_evento": "2021-03-11", "ultimo_evento": "2026-06-26",
  "categorias": ["…"], "monto_uf": 375.0, "grado_vinculacion": 4,

  "ier": 73.7, "ier_banda": "Crítico",
  "ier_factores": [{"key": "recurrencia", "value": "3 eventos", "points": 12.5, "max": 22}]
}
```

`ier_factores[].key` referencia `ier_schema[]`, donde vive `label`, `max` y el
racional `why`. Esa indirección evita repetir el texto en cada sujeto.

## `sectors[]`

`sector`, `inscritos_uaf`, `sancionados_n1`, `eventos_n1`, `tasa_penetracion`,
`wilson_low`, `wilson_high`, `lift`, `significativo`, `potenciales_n2`,
`eventos_n2`, `universo_candidato_sii`, `cobertura_registral`,
`brecha_registral`, `prioridad_screening`, `prioridad_rank`, `eventos_laft`,
`ier_max`, `ier_medio`, `irni`, `codigos_gatillantes[]`.

`significativo` es `true` sólo si el sector tiene ≥20 inscritos **y** su
`wilson_low` supera la tasa global: es la única marca que autoriza a decir que
un sector está por sobre el promedio.

## `graph`

- `nodes[]`: `id` (`S::`, `C::`, `P::`, `V::`), `type` (`sujeto` | `sector` |
  `supervisor` | `vinculada`), `label`, y para sujetos `nivel`, `rut`, `ier`,
  `eventos`, `sector`, `subject_id`, `grado_vinculacion`.
- `edges[]`: `source`, `target`, `kind`, `label`, `weight`.
  - `sancion` — el supervisor sancionó al sujeto.
  - `perimetro` — el sujeto pertenece a un sector (inscrito o hipotético).
  - `co_resolucion` — **ambas** entidades fueron individualizadas en la misma
    resolución. Es la arista que revela estructura societaria.
  - `mencion` — entidad individualizada sin sanción propia.
- `stats`: `nodos`, `aristas`, `co_resoluciones`, `menciones`, `componentes`.

## `traceability`

`ports[]` (especificación de los cuatro puertos), `port_status[]` (estado
observado: `OK` | `DEGRADED` | `ABSENT`, con registros y detalle),
`provenance` (versiones y cortes de cada radar de origen),
`registro_uaf_indexado`, `sectores_uaf_indexados`,
`politica_screening_sectores` y `cobertura_identidad` (mezcla de métodos,
sujetos con y sin RUT publicado, confianza media del Nivel 1).

## Compatibilidad

`v1` es aditivo: un host puede ignorar claves que no conozca. Un cambio que
elimine o resignifique una clave existente sube la versión del esquema.
