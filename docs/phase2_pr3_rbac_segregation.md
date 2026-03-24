# Phase 2 PR3 — RBAC fino por tenant/workspace + segregación reforzada

## Objetivo

Seguir la **FASE 2** del roadmap y cerrar dos bloques clave de fundación enterprise:

1. **RBAC fino por tenant/workspace/environment**
2. **Segregación estricta de memoria, auditoría y configuración efectiva por scope**

## Qué se ha implementado

### 1. RBAC por scope

Se añade capacidad de definir RBAC en tres niveles:

- tenant
- workspace
- environment

Cada nivel soporta:

- `username_roles`
- `user_key_roles`
- `permission_grants`
- `permission_denies`

La resolución efectiva de permisos sigue este orden:

1. rol base del usuario
2. bindings RBAC por tenant
3. bindings RBAC por workspace
4. bindings RBAC por environment
5. grants/denies acumulados

### 2. AuthContext ampliado

El contexto auth ahora distingue explícitamente entre:

- `base_role`
- `role` efectivo
- `bound_tenant_id`
- `bound_workspace_id`
- `bound_environment`
- `scope_access` (`global` o `scoped`)

Esto permite separar con claridad:

- administración global
- administración acotada por workspace
- usuarios normales con permisos ampliados o recortados por RBAC

### 3. Validación de scope objetivo

La creación de:

- usuarios
- tokens

queda validada contra el scope efectivo del actor. Un actor con acceso `scoped` no puede crear recursos fuera de su tenant/workspace/environment.

### 4. Segregación reforzada en auditoría

La capa `AuditStore` ahora soporta filtrado por scope en:

- eventos
- sesiones de chat
- memoria
- tool calls
- auth users
- auth sessions
- API tokens

Además:

- `log_event(...)` infiere scope desde la sesión si no se pasa explícitamente
- `log_tool_call(...)` infiere scope desde la sesión si no se pasa explícitamente

### 5. Segregación reforzada en memoria

La capa de memoria ahora propaga scope en:

- `remember_text(...)`
- `maybe_remember_user_text(...)`
- `recall(...)`
- `search_items(...)`

### 6. Broker/admin/auth filtrados por scope

Quedan filtrados por scope efectivo:

- `/broker/auth/users`
- `/broker/auth/sessions`
- `/broker/auth/tokens`
- `/broker/admin/overview`
- `/broker/admin/events`
- `/broker/admin/sessions`
- `/broker/admin/memory/search`
- `/broker/admin/tool-calls`

### 7. Preservación del admin global

Se mantiene el comportamiento esperado del admin global:

- si **no** envía cabeceras de scope, opera en modo global
- si envía cabeceras `X-Tenant-Id` / `X-Workspace-Id` / `X-Environment`, opera filtrado a ese scope

Esto evita que el admin global quede accidentalmente forzado al scope por defecto.

### 8. Compatibilidad hacia atrás

Se ha añadido compatibilidad defensiva en `pipeline.py` para implementaciones legacy/fake de memoria que todavía no aceptan argumentos de scope.

## Archivos principales afectados

### Nuevos tests

- `tests/test_phase2_rbac_segregation.py`

### Modificados

- `openmiura/core/config.py`
- `openmiura/core/tenancy/models.py`
- `openmiura/core/auth/models.py`
- `openmiura/application/auth/service.py`
- `openmiura/interfaces/broker/common.py`
- `openmiura/interfaces/broker/routes/auth.py`
- `openmiura/interfaces/broker/routes/admin.py`
- `openmiura/core/audit.py`
- `openmiura/core/memory.py`
- `openmiura/interfaces/broker/routes/chat.py`
- `openmiura/pipeline.py`

## Riesgos mitigados en esta iteración

### Fuga lateral entre workspaces

Mitigado filtrando todas las vistas sensibles por scope.

### Escalada silenciosa de permisos

Mitigado separando `base_role` de `role` efectivo y aplicando `permission_denies`.

### Admin global accidentalmente scopeado al default

Mitigado preservando `scope_access=global` salvo que haya cabeceras explícitas.

### Rotura de tests legacy por memoria fake

Mitigado con fallback compatible en `pipeline.py`.
