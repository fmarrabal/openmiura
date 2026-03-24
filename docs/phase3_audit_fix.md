# FASE 3 — auditoría de código y correcciones

## Objetivo
Revisar la implementación actual de workflows, approvals y scheduler para detectar errores funcionales, incongruencias de runtime y casos límite no cubiertos.

## Hallazgos corregidos

### 1. Doble marcado de fallo en workflows lanzados desde jobs y broker
Se detectó una duplicación del estado de fallo:
- `WorkflowService.run_workflow(...)` ya marcaba el workflow como `failed` y emitía `workflow_failed`.
- Después, `JobService.run_job(...)` y algunas rutas broker volvían a invocar `fail_workflow(...)`.

**Corrección aplicada**
- Se eliminó el segundo marcado redundante.
- Ahora se reutiliza el estado ya persistido por `run_workflow(...)`.

**Impacto**
- timeline consistente
- sin eventos `workflow_failed` duplicados
- menor ruido de auditoría

### 2. Expiración de approvals sin rechazo del workflow asociado
Se detectó que una approval podía pasar a `expired`, pero el workflow quedarse en `waiting_approval` hasta una acción posterior.

**Corrección aplicada**
- `ApprovalService._expire_pending(...)` ahora rechaza el workflow asociado con razón `approval_expired` cuando expira una approval pendiente.

**Impacto**
- coherencia entre inbox de approvals y estado del workflow
- eliminación de workflows “zombie” esperando aprobaciones ya expiradas

### 3. Race funcional al reclamar approvals
Se detectó que una approval ya reclamada podía ser reasignada silenciosamente por otro actor con permisos.

**Corrección aplicada**
- `ApprovalService.claim(...)` ahora impide “robar” una approval ya reclamada por otro actor.
- la ruta broker devuelve conflicto HTTP 409 en ese caso.

**Impacto**
- ownership más claro en bandeja de approvals
- evita colisiones operativas entre revisores

### 4. Validación insuficiente de expresiones cron
La validación de cron permitía expresiones fuera de rango que no fallaban pronto y podían degradar el cálculo del siguiente disparo.

**Corrección aplicada**
- validación explícita de rangos y pasos en `_parse_cron_field(...)`
- errores claros para valores inválidos

**Impacto**
- fallos más tempranos
- menos comportamientos silenciosos o degradación de cálculo

### 5. Incongruencia entre tool steps y compensation tool steps
Los tool steps resolvían referencias del contexto de workflow, pero los compensation tool steps no lo hacían.

**Corrección aplicada**
- se añadió resolución estructural de referencias también para compensaciones

**Impacto**
- comportamiento uniforme entre ejecución principal y compensaciones

## Tests añadidos
- expiración de approval con rechazo automático del workflow
- protección frente a “claim stealing”
- comprobación de un único `workflow_failed` en jobs fallidos
- rechazo explícito de cron inválido

## Verificación ejecutada
- `pytest -q` → OK
- `python -m compileall -q app.py openmiura tests` → OK
- suite actual: **176 tests**
