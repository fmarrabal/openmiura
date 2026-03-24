# FASE 5 PR1 — Evaluation harness inicial

## Objetivo
Abrir la FASE 5 con una base real para medir agentes, prompts, tools y ejecuciones sin acoplar todavía el sistema a un proveedor concreto ni a un runner LLM en red.

## Qué queda implementado

### 1. Configuración formal
Nueva sección `evaluations` en configuración:
- `enabled`
- `suites_path`
- `persist_results`
- `max_cases_per_run`
- `default_latency_budget_ms`

### 2. Catálogo de suites
Nuevo fichero `configs/evaluations.yaml` con soporte para:
- `defaults`
- `suites`
- `cases`
- `assertions`

### 3. Evaluation service
Nuevo servicio `openmiura.application.evaluations.EvaluationService` con:
- carga del catálogo de suites
- listado de suites y casos
- ejecución de una suite contra observaciones importadas
- scorecards agregados
- persistencia histórica

### 4. Tipos de assertions soportados
- `exact_match`
- `contains`
- `any_of`
- `tool_used`
- `tool_not_used`
- `policy_adherence`
- `latency_max_ms`
- `cost_max`
- `rubric_min_score`

### 5. Persistencia histórica
Nueva migración `7` con tablas:
- `evaluation_runs`
- `evaluation_case_results`

Se añaden métodos en `AuditStore` para:
- registrar runs
- registrar resultados por caso
- listar runs
- recuperar detalle de un run
- contar resultados

### 6. API admin
Nuevos endpoints HTTP admin:
- `GET /admin/evals/suites`
- `POST /admin/evals/run`
- `GET /admin/evals/runs`
- `GET /admin/evals/runs/{run_id}`

También se añaden equivalentes en broker admin:
- `GET /broker/admin/evals/suites`
- `POST /broker/admin/evals/run`
- `GET /broker/admin/evals/runs`
- `GET /broker/admin/evals/runs/{run_id}`

## Enfoque de este PR
Este PR no intenta todavía “ejecutar” un agente completo desde el harness. La base que deja es una arquitectura útil para:
- evaluar observaciones importadas desde CI
- validar regresiones de comportamiento
- construir scorecards históricos
- enchufar después un runner real de agentes/workflows

## Valor real que aporta
- ya existe un storage histórico de evaluación
- ya hay un formato mínimo de suites
- ya hay endpoints para lanzar evaluaciones y consultar runs
- ya se puede usar en CI con salidas observadas

## Siguiente paso recomendado
FASE 5 PR2:
- regression suites por agente
- fixtures/observations versionadas
- comparación entre runs
- primeros scorecards por agente/provider/modelo
