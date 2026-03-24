# Phase 3 PR4 — playbooks versionables/publicables + scheduler operativo + timeline unificado

## Alcance

Esta iteración cierra la fase 3 con tres bloques:

1. Playbooks versionables y publicables
2. Scheduler más orientado a operaciones
3. Timeline/realtime unificado para workflows, approvals y jobs

## Cambios principales

### Playbooks
- catálogo con metadatos de publicación:
  - `publication_status`
  - `published_at`
  - `published_by`
  - `publication_notes`
  - `available_versions`
  - `change_log`
- nuevos endpoints:
  - `GET /broker/playbooks?published_only=true|false&include_versions=true|false`
  - `GET /broker/playbooks/{playbook_id}?version=x.y.z`
  - `GET /broker/playbooks/{playbook_id}/versions`
  - `POST /broker/playbooks/{playbook_id}/publish`
  - `POST /broker/playbooks/{playbook_id}/deprecate`
- protección para impedir instanciar versiones no publicadas

### Jobs / scheduler operativo
- enriquecimiento de jobs con:
  - `operational_state`
  - `is_due`
  - `next_run_in_s`
- estados operativos:
  - `due`
  - `scheduled`
  - `paused`
  - `waiting_window`
  - `window_closed`
  - `exhausted`
  - `error`
- nuevo endpoint:
  - `GET /broker/jobs/summary`
- eventos auditados y publicados para jobs:
  - `job_created`
  - `job_paused`
  - `job_resumed`
  - `job_run_started`
  - `job_run_completed`
  - `job_run_failed`

### Timeline / realtime unificado
- timeline genérico:
  - `GET /broker/timeline`
- stream SSE genérico:
  - `GET /broker/timeline/stream`
- timelines por entidad:
  - `GET /broker/approvals/{approval_id}/timeline`
  - `GET /broker/jobs/{job_id}/timeline`
- filtros ampliados en realtime bus y endpoints:
  - `workflow_id`
  - `approval_id`
  - `job_id`
  - `entity_kind`
  - `entity_id`
- los eventos de workflow ahora propagan también:
  - `source_job_id`
  - `playbook_id`

## Validación
- `pytest -q` → OK
- `python -m compileall -q app.py openmiura tests` → OK
