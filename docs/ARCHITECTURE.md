# Arquitectura canónica

## Capas

1. `source_snapshot`: evidencia exacta de lo observado.
2. `sanction_case`: expediente/procedimiento/resolución.
3. `sanction_fact`: sanción o evento individual por entidad.
4. `legal_entity`: entidad canónica por RUT.
5. `derived_feature`: recencia, frecuencia, autoridad múltiple, sector, magnitud normalizada.
6. `risk_signal`: señal explicable y regenerable.
7. `evidence`: documento, hash, páginas y confianza de extracción.

## Interoperabilidad

Radar CGR, Radar SII y Radar Sanciones comparten `ENT-RUT-{RUT}` y temporalidad explícita. El integrador futuro debe mantener separado hecho fuente, señal e inferencia multicapa.
