# ADR-0023 — Capa común de explainability y analytics shape

## Estado
Aceptado

## Contexto
Los shapes de explainability, reason counts y analytics de governance empezaban a divergir entre baseline rollout, bundles y runtime governance.

## Decisión
Introducir una capa ligera común en `governance_explainability.py` para unificar vistas, `reason_counts` y estructuras de analytics.

## Alternativas consideradas
- dejar cada dominio con shapes propios;
- imponer una abstracción demasiado rígida.

## Consecuencias
- mayor consistencia de salidas;
- menor esfuerzo para consumidores y canvas/operator views;
- mejor base para futuras exportaciones y reporting.

## Riesgos aceptados
- no todos los analytics caben en una única abstracción completa;
- la capa común debe mantenerse ligera para no forzar simplificaciones artificiales.
