# openMiura audit round 8 — cierre de auditoría antes de continuar

## Alcance auditado
- FASE 1
- FASE 2
- FASE 3
- FASE 4 PR1–PR4

## Verificaciones ejecutadas
- `pytest -q` → OK
- `python -m compileall -q app.py openmiura tests` → OK

## Problemas reales encontrados y corregidos

### 1. Inicialización duplicada del Gateway al crear la app HTTP
**Problema**
- `create_app(...)` estaba llamando a `probe_gateway(...)` para decidir si montar broker/MCP.
- Eso provocaba bootstrap prematuro del Gateway al construir la app, y luego otro bootstrap real al entrar en `lifespan`.
- Consecuencias potenciales:
  - doble evento de startup,
  - doble apertura/uso de recursos,
  - side effects antes del arranque efectivo,
  - tests y despliegues con factories con efectos laterales más frágiles.

**Corrección**
- Eliminado el `probe_gateway(...)` del path de creación de la app.
- El montaje de broker/MCP ahora se decide a partir de `load_settings(...)`.
- Para MCP se usa un wrapper ASGI lazy que construye la subapp con el Gateway ya inicializado en `app.state.gw`.

**Cobertura añadida**
- test que asegura que el `gateway_factory` se invoca una sola vez.

### 2. `compliance_summary(...)` no respetaba bien la ventana temporal para sesiones y tool calls
**Problema**
- La parte de eventos sí usaba `since_ts`, pero `list_tool_calls(...)` y `list_sessions(...)` solo devolvían los últimos registros por orden, no filtrados por ventana.
- Resultado: un informe con `window_hours=24` podía contar sesiones o tool calls antiguos si seguían entrando en el `LIMIT`.

**Corrección**
- Añadido filtrado temporal explícito en `AdminService` para:
  - tool calls por `ts`,
  - sesiones por `updated_at`/`created_at`.
- Aumentado el fetch previo para no perder registros recientes por culpa de registros antiguos que ocupen el límite.

**Cobertura añadida**
- test que verifica que sesiones/tool calls antiguos quedan fuera del compliance summary.

### 3. Explainability de secretos: ambigüedad entre `agent_name` y `tool_name`
**Problema**
- En `explain_request(...)` y `explain_security(...)`, para el scope `secret`, el sistema reutilizaba `agent_name` como si fuera `tool_name`.
- Eso mezclaba dos conceptos distintos y podía devolver una decisión incorrecta al explicar acceso a secretos.

**Corrección**
- Añadido `tool_name` explícito en:
  - `PolicyExplainRequest`,
  - `SecurityExplainRequest`,
  - `AdminService.explain_policy(...)`,
  - `AdminService.explain_security(...)`,
  - `PolicyEngine.explain_request(...)`,
  - endpoint broker equivalente.
- Se mantiene compatibilidad: si no llega `tool_name`, se usa fallback conservador sobre `extra.tool_name` y después `agent_name`.

**Cobertura añadida**
- test que verifica que el explain de secretos usa el `tool_name` explícito.

### 4. Limpieza menor de incoherencias internas
**Correcciones menores**
- Eliminada duplicación inocua de generación de `workflow_id` en `AuditStore.create_workflow(...)`.
- Ajustado el código de admin routes para que el nuevo `tool_name` quede auditado y no rompa los endpoints previos.

## Resultado final de la auditoría
- No he encontrado, tras estas correcciones, un bloqueo estructural en FASE 1–4.
- La base queda más sólida para continuar con FASE 5.
- El punto más importante de esta ronda era evitar bootstrap duplicado y dejar compliance/explainability coherentes con el modelo de seguridad ya introducido en FASE 4.
