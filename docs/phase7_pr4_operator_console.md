# FASE 7 PR4 — Operator console avanzada

## Objetivo
Unificar en una sola superficie operativa las capacidades que ya existían por separado:
- replay de sesiones y workflows
- inspector de trazas
- timeline de ejecución
- visibilidad de políticas activas

## Qué queda implementado

### Backend / servicios
- Nuevo `OperatorConsoleService`
- Vista agregada de operación con:
  - sesiones recientes
  - workflows recientes
  - aprobaciones pendientes
  - trazas recientes
  - fallos recientes
  - snapshot resumido de política activa
- Vista unificada por sesión:
  - summary
  - timeline
  - mensajes
  - tool calls
  - traces
  - policy hints para tools observadas
- Vista unificada por workflow:
  - summary
  - timeline
  - approvals
  - traces
  - policy hints para tools observadas y acciones de approval

### Endpoints nuevos
HTTP admin:
- `GET /admin/operator/overview`
- `GET /admin/operator/sessions/{session_id}`
- `GET /admin/operator/workflows/{workflow_id}`

Broker admin:
- `GET /broker/admin/operator/overview`
- `GET /broker/admin/operator/sessions/{session_id}`
- `GET /broker/admin/operator/workflows/{workflow_id}`

### UI
Nueva pestaña **Operator** en `/ui` con:
- overview operativo
- colas activas
- policy surface
- carga de sesión o workflow
- timeline operativa
- panel unificado de inspector + policy hints
- listas clicables de sesiones/workflows recientes
- bandeja de approvals pendientes y fallos recientes

## Problema real corregido durante la ronda
Se ha corregido una incoherencia en las rutas admin HTTP:
- las rutas de replay estaban llamando a `_authorize_admin(...)`
- ese helper no existía en el módulo
- se ha normalizado el uso de `_require_admin(...)`

## Validación realizada
- `pytest -q` → OK
- `python -m compileall -q app.py openmiura tests` → OK

## Resultado
Con esta PR, la FASE 7 ya dispone de una consola operativa más fuerte y cohesionada, en lugar de varias superficies aisladas.
