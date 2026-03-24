# FASE 5 PR4 — Trazabilidad de decisiones + inspector enterprise

## Qué se ha añadido

### 1. Decision traces persistentes
Se añade una nueva migración de esquema (`v8`) con la tabla `decision_traces` para registrar por ejecución:
- sesión, usuario, canal y agente
- request/response
- provider/model
- latencia total
- coste estimado
- tokens de entrada/salida/total
- contexto usado
- memoria recuperada
- tools consideradas
- tools realmente usadas
- políticas aplicadas
- decisiones agregadas del runtime

### 2. Captura de trazabilidad en runtime
La traza queda conectada al flujo de ejecución real:
- `pipeline.process_message(...)` crea la traza
- la recuperación de memoria aporta `memory_json`
- `AgentRuntime.generate_reply(...)` agrega:
  - llamadas LLM
  - tokens
  - herramientas propuestas/ejecutadas
  - latencia total
- `ToolRuntime` aporta detalle de tools usadas y políticas/sandbox relevantes

### 3. Inspector enterprise en admin
Nuevos endpoints HTTP admin:
- `GET /admin/traces`
- `GET /admin/traces/{trace_id}`
- `GET /admin/inspector/sessions/{session_id}`

Nuevos endpoints equivalentes en broker admin:
- `GET /broker/admin/traces`
- `GET /broker/admin/traces/{trace_id}`
- `GET /broker/admin/inspector/sessions/{session_id}`

## Alcance funcional
Esta PR deja visible para inspección:
- contexto efectivo de la ejecución
- memoria recuperada y su resumen
- catálogo de tools consideradas
- tools ejecutadas con duración y resultado resumido
- políticas aplicadas por tool
- uso de tokens
- latencia por ejecución

## Limitación actual
`estimated_cost` queda preparado en la traza pero, si no existe pricing explícito para el provider/modelo, el valor permanece en `0.0`.

## Tests añadidos
- `tests/test_phase5_decision_trace_pipeline.py`
- `tests/test_phase5_decision_trace_admin.py`

## Verificación
- tests dirigidos de PR4: OK
- compilación: OK
