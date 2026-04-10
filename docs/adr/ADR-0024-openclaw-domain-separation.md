# ADR-0024 — Separación entre baseline rollout, runtime alerts y alert governance bundles

## Estado
Aceptado

## Contexto
Tres dominios distintos —baseline rollout, runtime alerts y alert governance bundles— convivían demasiado cerca dentro del scheduler.

## Decisión
Separarlos explícitamente en familias de módulos distintas, con helpers comunes solo donde exista patrón transversal real.

## Alternativas consideradas
- mantenerlos agrupados bajo un único gran módulo;
- separar solo runtime alerts y dejar governance unificado.

## Consecuencias
- fronteras funcionales más claras;
- mejor mantenibilidad;
- menor coste de razonamiento sobre cambios.

## Riesgos aceptados
- aparición de más puntos de integración;
- necesidad de vigilar que los helpers comunes no vuelvan a convertirse en un pseudo-monolito.
