# Plan de pruebas de FASE 2

Este documento reúne las pruebas que deben ejecutarse para validar la **FASE 2** del roadmap, incluyendo:

- multi-tenant base
- workspaces y entornos con overrides
- OIDC/SSO base
- RBAC fino por tenant/workspace
- segregación estricta de memoria/auditoría/config

## 1. Suite automática mínima obligatoria

Ejecutar siempre:

```bash
pytest -q tests/test_phase2_tenancy_foundation.py \
          tests/test_phase2_workspaces_oidc.py \
          tests/test_phase2_rbac_segregation.py \
          tests/test_phase2_rbac_operational.py
```

## 2. Suite automática completa recomendada

Ejecutar siempre antes de cerrar la fase:

```bash
pytest -q
```

## 3. Cobertura funcional esperada

### A. Multi-tenant foundation

Validar:

- resolución de tenant/workspace/environment por headers
- exposición de scope en `/broker/auth/me`
- catálogo de tenancy en `/broker/admin/tenancy`
- persistencia de scope en sesiones, eventos, auth sessions y API tokens
- migración `v4 tenancy_foundation`

Pruebas automáticas asociadas:

- `tests/test_phase2_tenancy_foundation.py`
- `tests/test_db_migrations.py`

### B. Workspaces y entornos con overrides

Validar:

- overrides a nivel tenant
- overrides a nivel workspace
- overrides a nivel environment
- resolución de configuración efectiva
- enmascarado de secretos en `/broker/admin/tenancy/effective-config`

Pruebas automáticas asociadas:

- `tests/test_phase2_workspaces_oidc.py`

### C. OIDC / SSO base

Validar:

- publicación de config OIDC
- generación de URL de login
- PKCE
- state firmado
- callback
- login local tras callback
- mapping de grupos a roles
- mapping de claims a tenant/workspace/environment

Pruebas automáticas asociadas:

- `tests/test_phase2_workspaces_oidc.py`

### D. RBAC fino por scope

Validar:

- binding `username_roles`
- binding `user_key_roles`
- `permission_grants`
- `permission_denies`
- diferencia entre `base_role` y `role`
- denegación de acciones fuera del scope

Pruebas automáticas asociadas:

- `tests/test_phase2_rbac_segregation.py::test_workspace_rbac_binding_and_permission_override`
- `tests/test_phase2_rbac_operational.py::test_tenant_admin_can_cross_workspace_within_tenant_but_not_cross_tenant`
- `tests/test_phase2_rbac_operational.py::test_custom_role_matrix_and_authorization_endpoint`
- `tests/test_phase5_ui_auth_stream_admin.py`

### E. Segregación estricta de datos

Validar filtrado por scope en:

- `/broker/auth/users`
- `/broker/auth/sessions`
- `/broker/auth/tokens`
- `/broker/admin/overview`
- `/broker/admin/events`
- `/broker/admin/sessions`
- `/broker/admin/memory/search`
- `/broker/admin/tool-calls`

Pruebas automáticas asociadas:

- `tests/test_phase2_rbac_segregation.py::test_scope_segregation_filters_admin_and_auth_views`
- `tests/test_phase5_ui_completion.py`
- `tests/test_phase5_ui_auth_stream_admin.py`

## 4. Checklist manual recomendado

### 4.1 Admin global sin headers

Comprobar que un admin global:

- puede ver usuarios de varios workspaces
- puede ver tool calls globales
- no queda atado al default scope si no manda headers

### 4.2 Admin global con headers

Comprobar que un admin global, al enviar:

- `X-Tenant-Id`
- `X-Workspace-Id`
- `X-Environment`

ve únicamente datos de ese scope.

### 4.3 Usuario scopeado

Comprobar que un usuario scopeado:

- no puede crear usuarios en otro workspace
- no puede crear tokens fuera de su scope
- no puede escalar permisos por headers

### 4.4 Memoria

Comprobar que dos workspaces distintos:

- escriben memoria separada
- recuperan memoria separada
- no cruzan resultados en búsquedas

### 4.5 Auditoría

Comprobar que eventos, sesiones y tool calls:

- quedan etiquetados con scope
- se pueden filtrar por scope
- no muestran elementos de otro workspace en vistas admin scopeadas

### 4.6 OIDC

Comprobar:

- login con grupo que mapea a rol operator
- login con claims que mapean a tenant/workspace/environment
- creación de sesión local posterior al callback

## 5. Criterio de aceptación de la fase

La fase puede considerarse estable cuando:

- la suite mínima de FASE 2 pasa completa
- la suite global `pytest -q` pasa completa
- las comprobaciones manuales de scope y OIDC no muestran fugas
- el admin global mantiene visibilidad global cuando no manda headers
- las vistas scopeadas no mezclan datos de otros workspaces
- la matriz RBAC efectiva y el endpoint de autorización reflejan correctamente herencia, grants/denies y scope
