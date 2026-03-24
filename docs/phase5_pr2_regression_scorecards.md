# FASE 5 PR2 — Regression suite por agente + comparación histórica + scorecards

## Objetivo
Extender el evaluation harness inicial para que openMiura no solo ejecute suites puntuales, sino que permita:

- comparar runs históricamente,
- detectar regresiones de forma operativa,
- agregar scorecards por agente, provider y modelo.

## Qué se ha implementado

### 1. Comparación histórica de runs
Se añade comparación entre ejecuciones de evaluación:

- comparación explícita entre `run_id` y `baseline_run_id`,
- comparación automática contra el run previo comparable,
- diff de métricas:
  - `pass_rate_delta`
  - `failed_cases_delta`
  - `average_latency_ms_delta`
  - `total_cost_delta`
- diff de casos:
  - regresiones
  - mejoras
  - casos cambiados

### 2. Regression suites por agente
El catálogo de suites ahora soporta metadatos orientados a regresión:

- `agent_name`
- `provider`
- `model`
- `is_regression_suite`

Esto permite asociar suites a combinaciones concretas de agente/proveedor/modelo.

### 3. Detección agregada de regresiones
Nuevos cálculos para agrupar runs comparables por:

- suite
- agente
- provider
- modelo
- tenant/workspace/environment

Sobre cada grupo se compara el último run frente al inmediatamente anterior y se listan solo los grupos con regresión real.

### 4. Scorecards agregados
Nuevos scorecards agregados con `group_by` configurable:

- `agent`
- `provider`
- `model`
- `agent_provider_model`
- `suite`

Cada scorecard devuelve:

- número de runs
- runs pasados/fallidos
- total de casos
- ratio de éxito por casos
- latencia media
- coste total
- último run
- suites/agentes/providers/modelos implicados

## Endpoints nuevos

### HTTP admin
- `GET /admin/evals/runs/{run_id}/compare`
- `GET /admin/evals/regressions`
- `GET /admin/evals/scorecards`

### Broker admin
- `GET /broker/admin/evals/runs/{run_id}/compare`
- `GET /broker/admin/evals/regressions`
- `GET /broker/admin/evals/scorecards`

## Cambios técnicos principales
- `EvaluationService`
  - `compare_runs(...)`
  - `list_regressions(...)`
  - `scorecards(...)`
- `AdminService`
  - passthrough de comparación, regresiones y scorecards
- `AuditStore.list_evaluation_runs(...)`
  - nuevos filtros por `agent_name`, `provider`, `model`
- `configs/evaluations.yaml`
  - ejemplo de suite ligada a agente/provider/modelo

## Cobertura añadida
- comparación histórica de runs
- detección de regresión
- scorecards agregados
- endpoints admin HTTP

## Resultado
Con este PR, FASE 5 ya no se limita a almacenar runs de evaluación: empieza a ofrecer capacidad real de gobernanza experimental y detección de regresiones orientada a operación.
