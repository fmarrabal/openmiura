# FASE 4 PR4 — Seguridad explicable + compliance pack inicial

## Objetivo
Cerrar la FASE 4 con una capa operativa que permita:

- explicar por qué una acción fue permitida, denegada o quedó sujeta a confirmación/aprobación,
- unificar policy + sandbox + secret broker en una sola vista de decisión,
- exponer un compliance pack inicial exportable desde la API de administración.

## Alcance implementado

### 1. Security explain unificado
Se añade una explicación consolidada de seguridad sobre cualquier request administrativa relevante:

- `POST /admin/security/explain`
- `POST /broker/admin/security/explain`

Entrada soportada:
- `scope`: `tool|memory|secret|channel|approval`
- `resource_name`
- `action`
- `agent_name`
- `user_role`
- `tenant_id`
- `workspace_id`
- `environment`
- `channel`
- `domain`
- `extra`

Salida principal:
- `final_state`: `allowed|denied|confirmation_required|approval_required`
- `allowed`
- `requires_confirmation`
- `requires_approval`
- `user_explanation`
- `admin_explanation`
- `components.policy`
- `components.sandbox`
- `components.secret`
- `audit_hints`
- `audit_event_id` en la API admin HTTP

### 2. Explicabilidad para secretos
El `SecretBroker` añade `explain_access(...)` para evaluar acceso a una ref sin resolver el secreto real.

Devuelve:
- si el broker está habilitado,
- si la ref existe,
- si está configurada,
- si pasa controles declarativos por tool/role/scope/domain,
- decisión del policy engine asociada,
- metadatos no sensibles de la ref.

No se expone nunca el valor del secreto.

### 3. Compliance pack inicial
Nuevos endpoints:

- `GET /admin/compliance/summary`
- `POST /admin/compliance/export`
- `GET /broker/admin/compliance/summary`
- `POST /broker/admin/compliance/export`

#### Summary
Resume por ventana temporal y scope:
- security events
- secret usages
- approval events
- config changes
- tool calls
- sessions

#### Export
Genera un paquete JSON inicial con:
- `overview`
- `security`
- `secret_usage`
- `approvals`
- `config_changes`
- `tool_calls`
- `sessions`

Incluye integridad:
- `integrity.sha256`
- `integrity.algorithm = sha256`
- `signed = false` (fase inicial)

## Criterios de diseño

### Explicación dual
La respuesta distingue entre:
- **user explanation**: mensaje breve y no sensible
- **admin explanation**: detalle operativo con reglas coincidentes, perfil de sandbox y ref implicada

### No filtración de secretos
La explicación de seguridad para secretos usa únicamente:
- nombre de la ref,
- metadatos permitidos,
- razón de allow/deny,
- decisión de policy,

pero jamás el valor real.

### Compatibilidad hacia atrás
No se rompe:
- `POST /admin/policies/explain`
- `POST /admin/sandbox/explain`

PR4 se monta encima de PR2 y PR3 sin invalidarlos.

## Ficheros principales tocados
- `openmiura/application/admin/service.py`
- `openmiura/interfaces/http/routes/admin.py`
- `openmiura/interfaces/broker/routes/admin.py`
- `openmiura/core/secrets.py`
- `openmiura/core/audit.py`

## Tests añadidos
- `tests/test_phase4_security_explain.py`
- `tests/test_phase4_compliance_pack.py`

## Validación
- `pytest -q` ✅
- `python -m compileall -q app.py openmiura tests` ✅

## Siguiente paso lógico
Con esto, la FASE 4 queda prácticamente cerrada funcionalmente.

El siguiente paso razonable es:
- remate de FASE 4 con endurecimiento fino de exports y firma real opcional, o
- abrir FASE 5 con evaluation harness + regression suite + trazabilidad de decisiones más profunda.
