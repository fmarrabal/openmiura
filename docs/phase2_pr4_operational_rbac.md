# FASE 2 — PR4: RBAC operativo, matrices de permisos y validación de acceso

Esta iteración remata la parte operativa de la **FASE 2** del roadmap antes del salto a workflows y approvals.

## Objetivo

Endurecer el modelo de autorización multi-tenant ya introducido, haciendo explícitos:

- roles operativos adicionales
- herencia de roles por scope
- alcance efectivo del rol (`global`, `tenant`, `workspace`, `environment`)
- inspección de la matriz RBAC desde el broker
- simulación/evaluación de permisos para un scope concreto

## Cambios principales

### 1. Roles operativos añadidos

Se añaden roles built-in adicionales:

- `viewer`
- `auditor`
- `workspace_admin`
- `tenant_admin`

junto con sus permisos base e herencia.

### 2. Scope profile explícito

El contexto auth expone ahora:

- `scope_access`
  - `global`
  - `tenant`
  - `scoped`
- `scope_level`
  - `global`
  - `tenant`
  - `workspace`
  - `environment`

Esto permite distinguir mejor entre:

- un admin global
- un tenant admin
- un usuario ligado a un workspace
- una sesión/token ligado a un environment concreto

### 3. RBAC configurable por scope

`ScopeRBACSettings` soporta ahora:

- `role_inherits`
- `role_scope_access`

además de los ya existentes:

- `username_roles`
- `user_key_roles`
- `permission_grants`
- `permission_denies`

### 4. Endpoints nuevos

#### `GET /broker/auth/rbac/matrix`

Devuelve la matriz efectiva de roles para el scope actual.

Incluye por rol:

- permisos base
- permisos efectivos
- herencia
- `scope_access`
- `scope_level`

#### `POST /broker/auth/authorize`

Permite evaluar si el contexto auth actual puede ejercer un permiso concreto en un scope objetivo.

Uso típico:

- depuración de permisos
- validación de rollout enterprise
- tests de no regresión

## Efecto práctico

Con esto ya es posible modelar de forma razonable:

- admins globales
- admins por tenant
- admins por workspace
- perfiles de auditoría
- roles personalizados heredados por scope

sin duplicar matrices de permisos en el broker.

## Tests asociados

- `tests/test_phase2_rbac_operational.py`
- `tests/test_phase2_rbac_segregation.py`
- `tests/test_phase2_workspaces_oidc.py`
- `tests/test_phase2_tenancy_foundation.py`

## Estado

Con este PR, la **FASE 2** queda mucho más cerrada y lista para pasar al siguiente bloque del roadmap:

- **FASE 3 — workflows, approvals y automatización**
