# FASE 7 PR3 — Replay de sesiones/workflows + comparación visual de ejecuciones

## Alcance
Esta entrega abre el bloque de replay operacional para openMiura, centrado en dos superficies:

- reconstrucción de ejecuciones de **sesiones**
- reconstrucción de ejecuciones de **workflows**
- comparación estructural entre dos ejecuciones

El objetivo es que un operador pueda revisar qué ocurrió, en qué orden, con qué tools, con qué trazas de decisión y con qué diferencias frente a otra ejecución.

## Implementado

### 1. Replay service
Nuevo servicio `ReplayService` en `openmiura.application.replay` con soporte para:

- `session_replay(...)`
- `workflow_replay(...)`
- `compare_replays(...)`

### 2. Timeline unificado
Cada replay normaliza en una línea temporal ascendente:

- mensajes
- eventos
- tool calls
- decision traces
- approvals (en workflows)

Cada item queda serializado con un `kind` estable para la UI:

- `message`
- `event`
- `tool_call`
- `trace`
- `approval`

### 3. Resumen de ejecución
Cada replay devuelve un `summary` con:

- `message_count`
- `event_count`
- `tool_call_count`
- `trace_count`
- `memory_hits`
- `duration_ms`
- `event_names`
- `tools_used`
- `fingerprint`

Y en workflows además:

- `approval_count`
- `step_count`
- `workflow_name`
- `playbook_id`

### 4. Comparación de ejecuciones
Nuevo comparador con:

- `metrics_diff`
- `event_name_diff`
- `tool_diff`
- cambio de `status`
- agentes implicados
- providers/modelos observados
- fingerprint por replay

### 5. Endpoints nuevos
#### Admin HTTP
- `GET /admin/replay/sessions/{session_id}`
- `GET /admin/replay/workflows/{workflow_id}`
- `POST /admin/replay/compare`

#### Broker admin
- `GET /broker/admin/replay/sessions/{session_id}`
- `GET /broker/admin/replay/workflows/{workflow_id}`
- `POST /broker/admin/replay/compare`

### 6. UI
Nueva pestaña **Replay** en `/ui` con:

- carga de replay de la sesión seleccionada
- carga de replay por workflow id
- timeline renderizada
- bloque de detalles serializados
- comparación visual izquierda/derecha

## Nota de diseño
La comparación es **estructural y operativa**, no semántica. El fingerprint se calcula sobre el orden y naturaleza de los items de timeline, lo cual sirve para detectar cambios de ejecución aunque el contenido textual no se compare con profundidad semántica.

## Validación ejecutada
- `pytest -q` ✅
- `python -m compileall -q app.py openmiura tests` ✅
