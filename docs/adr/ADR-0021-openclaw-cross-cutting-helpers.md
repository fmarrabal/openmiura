# ADR-0021 — Helpers transversales para ventanas temporales, familias de jobs y runtime context

## Estado
Aceptado

## Contexto
Persistían patrones repetidos de validación temporal, paginación de jobs y carga de contexto runtime en varios dominios.

## Decisión
Introducir helpers transversales reutilizables:
- `temporal_windows.py`
- `job_family_common.py`
- `runtime_context.py`

## Alternativas consideradas
- Mantener helpers duplicados por dominio.
- Extraer solo parcialmente sin API común.

## Consecuencias
- menor divergencia semántica;
- reglas comunes para tiempo, jobs y runtime context;
- reducción del riesgo de duplicación futura.

## Riesgos aceptados
- algunos caminos pueden tardar en absorber por completo los nuevos helpers;
- la API común debe permanecer estable y simple.
