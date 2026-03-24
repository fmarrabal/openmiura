# Fase 3 — Plan de pruebas

## 1. Migraciones

- inicializar una base nueva y comprobar que se aplican las migraciones hasta v5
- verificar existencia de tablas:
  - `workflows`
  - `approvals`
  - `job_schedules`
- probar rollback de una versión

## 2. Workflow engine

- crear workflow con pasos `note + tool`
- crear workflow con paso `approval`
- reanudar workflow tras aprobación
- rechazar workflow y verificar estado terminal
- cancelar workflow y verificar estado terminal
- consultar timeline

## 3. Approvals

- listar aprobaciones pendientes
- aprobar una aprobación válida
- rechazar una aprobación válida
- impedir decisiones sobre aprobaciones inexistentes
- impedir decisiones fuera de scope

## 4. Jobs

- crear job habilitado
- listar jobs por scope
- ejecutar job manualmente
- ejecutar jobs vencidos con `run-due`
- comprobar actualización de `last_run_at` y `next_run_at`

## 5. Playbooks

- listar playbooks
- instanciar un playbook en workflow
- ejecutar playbook con `autorun`

## 6. Permisos

- usuario normal puede leer/escribir workflows en su scope
- operador puede decidir approvals
- operador puede crear y ejecutar jobs
- actor fuera de scope no ve workflows ajenos

## 7. Regresión

- ejecutar suite completa
- ejecutar `python -m compileall -q app.py openmiura tests`


## PR2 additional validation

- workflow tool retries with bounded backoff
- workflow branching based on input/context
- timeout failure path and compensation execution
- approval filters by requested role and assignee
- approval claim endpoint and detail endpoint
- job scheduler metadata (`schedule_kind`, `schedule_expr`, `timezone`)
- one-shot jobs with `max_runs`
- pause/resume behavior for scheduled jobs
- schema migration v6 applied and rollback metadata updated
