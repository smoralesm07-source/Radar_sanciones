# Módulo `sanciones_uaf` — Radar Sanciones ↔ Perímetro UAF

Módulo **acoplable** que cruza las sanciones publicadas por los supervisores
prudenciales contra el perímetro de sujetos obligados de la UAF, y ordena el
resultado en dos niveles de lectura:

| Nivel | Pregunta que responde | Universo |
|---|---|---|
| **N1** | ¿Qué sujetos obligados **inscritos** en la UAF figuran en alguna sanción? | Registro de Entidades Reportantes ∩ sanciones |
| **N2** | ¿Qué **potenciales** sujetos obligados (actividad vigente en SII, sin inscripción) tienen marca de sanción? | Sancionados fuera del registro con hipótesis de obligación |
| **N0** | Control negativo: sancionados sin señal alguna de obligación | Personas naturales, auditores, emisores |

El Nivel 0 existe a propósito: sin él, cualquier sanción de la CMF inflaría el
Nivel 2 y el módulo dejaría de ser útil para focalizar.

## Uso

```bash
# Verifica los puertos de entrada sin escribir nada
python -m modules.sanciones_uaf.cli check --workspace /ruta/a/los/radares

# Construye el bundle y el HTML autocontenido
python -m modules.sanciones_uaf.cli build \
    --html   docs/modulo_sanciones_uaf.html \
    --bundle docs/data/modulo_sanciones_uaf_v1.json
```

Como biblioteca:

```python
from modules.sanciones_uaf import build_bundle, render_html

bundle = build_bundle()                       # lee los puertos y calcula todo
render_html(bundle, "docs/modulo_sanciones_uaf.html")
```

## Acoplamiento

El módulo no conoce rutas ni repositorios: sólo cuatro **puertos**. Para
montarlo en otro entorno basta construir un `ModuleInput` y llamar a
`build_bundle(payload)`.

| Puerto | Proveedor | Si falta |
|---|---|---|
| `PORT_SANCIONES_EVENTS` | Radar Sanciones | **Bloqueante** |
| `PORT_UAF_REGISTRO` | Radar UAF | Degrada: no hay Nivel 1 |
| `PORT_SII_SCREENING` | Radar SII | Degrada: Nivel 2 sin universo candidato |
| `PORT_SII_ACTECO_RUT` | Radar SII | Opcional: convierte inferencias en confirmaciones |

El estado observado de cada puerto viaja dentro del bundle y se muestra en la
vista **Método y trazabilidad**: la degradación nunca es silenciosa.

### Acoplar al cockpit IFL

La capa de presentación expone un punto de montaje único:

```js
RadarSancionesUAF.mount(elemento, bundle);   // bundle = sanciones_uaf.bundle/v1
```

El HTML autocontenido sólo hace `mount(document.body, BUNDLE)` con el bundle
embebido. Un host externo puede cargar el mismo bloque y montarlo en cualquier
contenedor, o consumir el bundle JSON directamente.

## Cómo se resuelve la identidad

Cascada de mayor a menor confianza, siempre etiquetada:

1. `RUT_EXACT` (1.00) — la resolución publica el RUT y coincide con el registro.
2. `RUT_FROM_TEXT` (0.92) — el RUT se recupera del resumen o de las entidades
   individualizadas en la resolución.
3. `NAME_EXACT_NORM` (0.88) — razón social normalizada idéntica. La
   normalización unifica grafías del sufijo societario (`S.A.` ≡ `SA`,
   `S.A.D.P` ≡ `SADP`).
4. `NAME_FUZZY_SECTOR` (≤0.85) — similitud de tokens ≥0,82 **dentro del sector
   declarado** en la propia sanción.
5. `NAME_FUZZY_GLOBAL` (≤0.75) — similitud ≥0,93 sin restricción de sector.

Toda coincidencia por nombre viaja con confianza reducida y con la evidencia
textual del vínculo. **No debe usarse como prueba** sin validación documental.

## Cómo se formula la hipótesis del Nivel 2

Cada peldaño exige una señal propia; el primero que se cumple gana.

| Hipótesis | Fuerza | Señal |
|---|---|---|
| `CONFIRMADO_SII` | 1,00 | ACTECO vigente en la nómina SII coincide con un gatillante del sector |
| `INFERIDO_SECTOR` | 0,80 | La resolución clasifica al sancionado en un sector obligado |
| `INFERIDO_MATERIA_LAFT` | 0,72 | La sanción versa sobre deberes ALA/CFT |
| `INFERIDO_RAZON_SOCIAL` | 0,55 | La denominación social declara la actividad regulada |
| `INFERIDO_SUPERVISOR` | 0,45 | Supervisor con competencia **exclusiva** sobre sujetos obligados (UAF, Casinos) |
| `SIN_HIPOTESIS` | 0 | → Nivel 0 |

Sancionar por CMF **no** basta por sí solo: ese perímetro alcanza emisores,
auditores y personas naturales que no son sujetos obligados.

## Métricas

- **Penetración sancionatoria por sector** con intervalo de Wilson al 95 %. Un
  sector sólo se declara sobre el promedio cuando el extremo inferior del
  intervalo supera la tasa global — con 14 inscritos, la tasa puntual engaña.
- **Lift sectorial** — tasa del sector ÷ tasa global.
- **Brecha registral** — universo candidato SII ÷ (candidatos + inscritos).
- **IRNI** (Índice de Riesgo de No Inscripción, 0–100) por sector: brecha,
  presión sancionatoria del perímetro inscrito, marcas de sanción observadas
  fuera del registro y solidez del gatillante ACTECO.
- **IER** (Índice de Exposición Regulatoria, 0–100) por sujeto: siete factores
  acotados —recurrencia, severidad, materia ALA/CFT, convergencia supervisora,
  recencia con vida media de 24 meses, vinculación en resoluciones y brecha de
  perímetro—. Ningún factor puede dominar el índice; la ficha muestra el aporte
  exacto de cada uno.
- **Reincidencia** — distribución, intervalo mediano entre sanciones
  consecutivas, HHI normalizado y Gini.
- **Momentum** — 12 meses móviles contra los 12 previos, por sector.
- **Anomalías** — z-score de la tasa de penetración sobre sectores con ≥10
  inscritos.

## Límite de uso

Figurar en el registro UAF o en una hipótesis de screening SII **no** constituye
imputación, incumplimiento ni estimación de riesgo LA/FT. El universo candidato
SII es bruto: incluye entidades que ejercen la actividad de forma incidental.
Toda coincidencia por nombre requiere validación documental antes de cualquier
uso decisorio.
