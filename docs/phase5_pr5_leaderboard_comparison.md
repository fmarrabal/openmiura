# FASE 5 PR5 — Leaderboard interno + comparativa avanzada por caso de uso/agente/modelo

## Objetivo
Cerrar FASE 5 incorporando una capa de benchmarking operativa que permita:

- rankear agentes/modelos/proveedores con criterios consistentes
- comparar desempeño por caso de uso
- detectar configuraciones estables frente a configuraciones con regresiones
- exponer esa información por API admin y broker admin

## Qué se ha implementado

### 1. Metadatos de caso de uso en suites
El catálogo de evaluaciones ahora expone `use_case` por suite.

Resolución:
1. `suite.use_case` explícito si existe
2. primer tag no genérico (`finance`, `support-triage`, etc.)
3. fallback al nombre normalizado de la suite

Esto permite agrupar resultados históricos sin requerir migración nueva.

### 2. Leaderboard interno
Nuevo servicio en `EvaluationService.leaderboard(...)` con soporte para:

- `group_by=agent`
- `group_by=provider`
- `group_by=model`
- `group_by=agent_provider_model`
- `group_by=suite`
- `group_by=use_case`
- `group_by=use_case_agent_model`

Métricas por entidad:
- `run_count`
- `run_pass_rate`
- `case_pass_rate`
- `average_latency_ms`
- `total_cost`
- `average_cost_per_run`
- `regression_events`
- `regression_cases`
- `improvement_cases`
- `latest_regression`
- `latest_comparison`
- `stability_score`

### 3. Stability score
Se añade una métrica compuesta simple para ranking enterprise:

`stability_score = ((case_pass_rate * 0.7) + (run_pass_rate * 0.2) + (1 / (1 + regression_events)) * 0.1) * 100`

Idea:
- premiar exactitud agregada
- premiar consistencia entre runs
- penalizar entidades que generan regresiones recurrentes

### 4. Comparativa avanzada
Nuevo servicio `EvaluationService.comparison(...)` para construir matrices comparativas.

Soporta:
- `split_by=use_case`
- `split_by=suite`
- `split_by=agent`
- `split_by=model`
- `split_by=provider`

Y dentro de cada grupo:
- ranking por `compare_by`
- `leader`
- resumen del grupo
- top N entidades comparadas

Caso principal previsto:
- `split_by=use_case`
- `compare_by=agent_provider_model`

## Endpoints nuevos

### Admin HTTP
- `GET /admin/evals/leaderboard`
- `GET /admin/evals/comparison`

### Broker admin
- `GET /broker/admin/evals/leaderboard`
- `GET /broker/admin/evals/comparison`

## Ejemplos

### Leaderboard general
```http
GET /admin/evals/leaderboard?group_by=agent_provider_model&rank_by=stability_score
```

### Leaderboard filtrado por caso de uso
```http
GET /admin/evals/leaderboard?group_by=agent_provider_model&use_case=support-triage
```

### Comparativa por caso de uso
```http
GET /admin/evals/comparison?split_by=use_case&compare_by=agent_provider_model&rank_by=stability_score
```

## Decisiones de diseño

### Sin migración nueva
PR5 reutiliza:
- `evaluation_runs`
- `evaluation_case_results`
- catálogo YAML de suites

No se ha añadido migración porque la semántica de `use_case` puede resolverse desde el catálogo.

### Comparación histórica reutilizando PR2
La señal de regresión del leaderboard se construye reaprovechando `compare_runs(...)`, evitando duplicar lógica de comparación.

## Testing añadido
- leaderboard por `agent_provider_model`
- ranking por `stability_score`
- detección de `latest_regression`
- agrupación por `use_case`
- comparación avanzada por caso de uso en admin HTTP

## Estado
Con este PR queda cerrada la **FASE 5**:
- PR1 Evaluation harness
- PR2 Regression suite + comparación histórica + scorecards
- PR3 Cost governance
- PR4 Trazabilidad de decisiones + inspector
- PR5 Leaderboard interno + comparativa avanzada
