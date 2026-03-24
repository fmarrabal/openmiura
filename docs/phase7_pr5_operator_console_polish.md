# FASE 7 PR5 — Pulido de operator console y comparación avanzada

## Objetivo
Dar una última vuelta operativa a la FASE 7 para que la consola no sea solo una superficie de lectura, sino una herramienta de operación diaria más útil para soporte, compliance y troubleshooting.

## Alcance implementado

### 1. Filtros avanzados en operator console
Se añade soporte de filtrado por:
- `q` (búsqueda libre)
- `status`
- `kind`
- `only_failures`
- `limit`

Aplicado a:
- overview operativo
- replay de sesión dentro de operator console
- replay de workflow dentro de operator console

La respuesta incluye:
- `filters`
- `filtered_counts`

### 2. Acciones operativas rápidas
Nuevos endpoints para operar desde la consola:

#### Admin HTTP
- `POST /admin/operator/workflows/{workflow_id}/actions/{action}`
- `POST /admin/operator/approvals/{approval_id}/actions/{action}`

#### Broker admin
- `POST /broker/admin/operator/workflows/{workflow_id}/actions/{action}`
- `POST /broker/admin/operator/approvals/{approval_id}/actions/{action}`

Acciones soportadas:
- workflow: `cancel`, `run`
- approval: `claim`, `approve`, `reject`

Se devuelve el recurso enriquecido con `available_actions`.

### 3. Comparación visual más rica en replay
Se amplía `ReplayService.compare_replays(...)` con:
- `timeline_kind_diff`
- `timeline_status_diff`
- `timeline_signature_diff`

Esto permite distinguir mejor si cambió:
- el tipo de eventos que aparecen
- el estado observado por tipo de ejecución
- la estructura efectiva del timeline

### 4. UI
Se añaden en `/ui`:
- filtros avanzados en la pestaña Operator
- acciones rápidas para workflows y approvals
- snapshot de filtros aplicados
- resumen visual de comparación de replay
- highlights de diferencias estructurales

## Correcciones realizadas durante la ronda
- La comparación de replay antes era demasiado cruda para operación; ahora expone diffs de kinds, estados y firmas de timeline.
- La operator console no permitía actuar sobre approvals/workflows sin salir a otras superficies; ahora soporta quick actions.
- El overview no distinguía bien entre dataset total y subconjunto filtrado; ahora devuelve `filtered_counts`.

## Validación ejecutada
- `python -m compileall -q app.py openmiura tests`
- `pytest -q tests/test_phase7_replay.py tests/test_phase7_operator_console.py tests/test_phase7_polish.py`

## Resultado
Con esta ronda, la FASE 7 queda mucho más cerca de una superficie operator-grade:
- inspección
- replay
- policy hints
- comparación
- acciones rápidas
- filtrado útil para incidentes y soporte
