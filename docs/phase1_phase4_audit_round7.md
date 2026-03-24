# Auditoría round 7 — cierre operativo de FASE 4 PR4

## Base auditada
Árbol auditado: `openmiura_phase4_pr3_sandbox`

## Resultado
Se implementa correctamente el siguiente paso del roadmap:

- **FASE 4 PR4 — seguridad explicable + compliance pack inicial**

## Cambios relevantes verificados

### 1. Seguridad explicable unificada
Se añade una capa de explicación combinada para decisiones de seguridad.

Puntos verificados:
- composición de `policy` + `sandbox` + `secret broker`,
- cálculo de `final_state`,
- separación entre explicación de usuario y explicación de admin,
- hints de auditoría y correlación por `audit_event_id` en la API admin.

### 2. Secret broker sin exposición de valores
Se añade `SecretBroker.explain_access(...)`.

Puntos verificados:
- no se resuelve el secreto real,
- no se expone el valor,
- sí se expone el estado de configuración y los metadatos permitidos,
- se combina con `PolicyEngine.check_secret_access(...)`.

### 3. Compliance pack inicial
Se añaden summary y export.

Puntos verificados:
- clasificación básica de eventos de seguridad,
- export JSON reproducible,
- hash SHA-256 del reporte,
- soporte de filtros por tenant/workspace/environment y ventana temporal.

### 4. Auditoría persistente mejorada
`AuditStore.log_event(...)` ahora devuelve `event_id` cuando el backend lo permite.

Puntos verificados:
- no rompe compatibilidad con call-sites existentes,
- mejora la trazabilidad de acciones administrativas.

### 5. Filtrado de eventos
Se añade `list_events_filtered(...)`.

Puntos verificados:
- filtros por canal, dirección, ventana temporal y scope,
- filtrado adicional por `payload.event`/`payload.action` en memoria,
- sin requerir JSON SQL específico del backend.

## Riesgos revisados

### Riesgo 1 — explicación excesivamente optimista sin policy
Estado: aceptable para esta fase.

Cuando no hay policy configurada, `security/explain` sigue pudiendo explicar sandbox o secret broker. Esto es coherente con el estado real del runtime.

### Riesgo 2 — export firmado no criptográfico
Estado: conocido y aceptado.

En PR4 el export incluye integridad (`sha256`) pero no firma criptográfica. Esto encaja con el alcance “initial compliance pack”.

### Riesgo 3 — clasificación heurística de eventos
Estado: aceptable.

La clasificación de compliance se apoya en nombres de `event/action`. Es suficiente para PR4, pero en una fase posterior conviene normalizar taxonomía de eventos sensibles.

## Validación ejecutada
- `pytest -q tests/test_phase4_security_explain.py tests/test_phase4_compliance_pack.py` ✅
- `pytest -q tests/test_phase4_policy_admin.py tests/test_phase4_sandbox_profiles.py tests/unit/test_policy_phase4_unified.py tests/test_phase4_secret_broker.py` ✅
- `pytest -q` ✅
- `python -m compileall -q app.py openmiura tests` ✅

## Estado del roadmap tras esta ronda
- FASE 1 ✅
- FASE 2 ✅
- FASE 3 ✅
- FASE 4
  - PR1 Secret Broker ✅
  - PR2 Policy Engine formal ✅
  - PR3 Sandbox profiles ✅
  - PR4 Seguridad explicable + compliance pack inicial ✅

## Conclusión
La FASE 4 queda cerrada con una base razonablemente sólida para seguridad operativa enterprise:

- secretos no expuestos,
- políticas formales,
- sandboxing por perfiles,
- decisiones explicables,
- compliance pack inicial exportable.

El siguiente salto de valor ya está en **FASE 5 — evaluación y gobernanza del agente**.
