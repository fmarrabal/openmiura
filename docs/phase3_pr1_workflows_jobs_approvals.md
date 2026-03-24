# Fase 3 PR1 — Workflows, jobs, approvals y playbooks base

## Alcance aplicado

Se introduce el primer bloque real de la FASE 3 del roadmap:

- workflow engine persistente
- approvals humanas persistentes
- jobs programados base
- catálogo inicial de playbooks reutilizables
- timeline consultable por workflow

## Persistencia

Nueva migración:

- v5 `workflow_engine`

Nuevas tablas:

- `workflows`
- `approvals`
- `job_schedules`

Todas las tablas quedan scope-aware por:

- `tenant_id`
- `workspace_id`
- `environment`

## Servicios de aplicación

Nuevos servicios:

- `openmiura/application/workflows/service.py`
- `openmiura/application/approvals/service.py`
- `openmiura/application/jobs/service.py`
- `openmiura/application/workflows/playbooks.py`

## Broker HTTP

Nuevas rutas en `openmiura/interfaces/broker/routes/workflows.py`:

- `GET /broker/workflows`
- `POST /broker/workflows`
- `GET /broker/workflows/{workflow_id}`
- `GET /broker/workflows/{workflow_id}/timeline`
- `POST /broker/workflows/{workflow_id}/run`
- `POST /broker/workflows/{workflow_id}/cancel`
- `GET /broker/approvals`
- `POST /broker/approvals/{approval_id}/decision`
- `GET /broker/jobs`
- `POST /broker/jobs`
- `POST /broker/jobs/{job_id}/run`
- `POST /broker/jobs/run-due`
- `GET /broker/playbooks`
- `POST /broker/playbooks/{playbook_id}/instantiate`

## Permisos añadidos

Se añaden permisos operativos nuevos:

- `workflows.read`
- `workflows.write`
- `approvals.read`
- `approvals.write`
- `jobs.read`
- `jobs.write`
- `jobs.run`

## Comportamiento actual

### Workflow engine

Se soportan pasos de tipo:

- `note`
- `tool`
- `approval`

### Approvals

Un paso `approval` pausa el workflow con estado `waiting_approval` y crea un registro en `approvals`.

Cuando una aprobación se marca como:

- `approved` → el workflow reanuda la ejecución
- `rejected` → el workflow pasa a `rejected`

### Jobs

Los jobs permiten:

- creación persistente
- ejecución manual
- ejecución de los jobs vencidos con `run-due`
- actualización de `last_run_at` y `next_run_at`

### Playbooks

Se incluye un catálogo base con ejemplos reutilizables:

- `summary_daily`
- `approval_gate`
- `reconciliation_stub`

## Realtime y timeline

Cada workflow emite eventos en:

- auditoría (`events` con canal `workflow`)
- realtime bus cuando está disponible

El timeline del workflow se consulta con:

- `GET /broker/workflows/{workflow_id}/timeline`

## Límite intencional de esta iteración

Esta iteración deja preparada la base, pero todavía no incluye:

- scheduler daemon dedicado
- cron parser completo
- branching declarativo avanzado
- retries/backoff formales
- compensaciones
- bandeja UI avanzada

Esos puntos quedan listos para la siguiente iteración de la FASE 3.
