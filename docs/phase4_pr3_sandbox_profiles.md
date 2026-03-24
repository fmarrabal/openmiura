# FASE 4 — PR3 Sandbox profiles

## Objetivo
Cerrar el tercer bloque de FASE 4 enlazando:

- policy / rol / scope
- perfil de sandbox
- límites efectivos de ejecución
- auditoría y explicación operativa

## Qué se ha implementado

### 1. Motor formal de perfiles de sandbox
Nuevo módulo:

- `openmiura/core/sandbox.py`

Incluye:

- perfiles built-in:
  - `local-safe`
  - `corporate-safe`
  - `restricted`
  - `air-gapped-like`
- resolución por:
  - `default_profile`
  - `role_profiles`
  - `selectors` por rol/tenant/workspace/environment/channel/agent/tool
- decisión explainable con:
  - `profile_name`
  - `source`
  - `matched_selector`
  - `explanation`

### 2. Configuración nueva
Nuevo bloque `sandbox` en configuración:

```yaml
sandbox:
  enabled: true
  default_profile: local-safe
  role_profiles:
    admin: local-safe
    analyst: restricted
  selectors:
    - name: prod-admin-terminal
      profile: air-gapped-like
      roles: [admin]
      environments: [prod]
      tools: [terminal_exec]
```

### 3. Integración en Gateway y ToolRuntime
El runtime ahora resuelve un perfil de sandbox por ejecución de tool usando:

- `user_role`
- `tenant_id`
- `workspace_id`
- `environment`
- `channel`
- `agent_id`
- `tool_name`

Y bloquea la ejecución antes de entrar en la tool si el perfil la deniega.

### 4. Enforcement real sobre tools críticas
Aplicado a:

- `terminal_exec`
- `web_fetch`
- `fs_read`
- `fs_write`

#### `terminal_exec`
Se fusionan:

- política global de terminal
- overrides por rol
- overrides del sandbox profile

Se soporta control de:

- `allow_shell`
- `allow_shell_metacharacters`
- `allow_multiline`
- `require_explicit_allowlist`
- `allowed_commands`
- `blocked_commands`
- `blocked_patterns`
- `timeout_s`
- `max_timeout_s`
- `max_output_chars`

#### `web_fetch`
Se soporta control de:

- red habilitada / deshabilitada
- `allow_all_domains`
- `allowed_domains`
- `timeout_s`
- `max_bytes`
- `block_private_ips`

#### `fs_write`
Se soporta control de:

- perfil read-only
- `max_write_chars`

### 5. Explainability operativa
Nuevo endpoint admin:

- `POST /admin/sandbox/explain`

Permite inspeccionar qué perfil se aplica y por qué.

### 6. Auditoría y observabilidad
Añadido:

- evento de denegación por sandbox antes de ejecutar la tool
- inclusión de `sandbox_profile` en eventos realtime de inicio/fin de tool
- trazabilidad del perfil en `terminal_exec`

## Tests añadidos
Nuevo fichero:

- `tests/test_phase4_sandbox_profiles.py`

Cobertura:

- parseo de configuración de sandbox
- resolución por rol y selector
- filtrado de tools visibles por perfil
- enforcement de `fs_write` y `terminal_exec`
- endpoint admin de explicación

## Validación

- `pytest -q` ✅
- `python -m compileall -q app.py openmiura tests` ✅

## Estado del roadmap

- FASE 1 cerrada
- FASE 2 cerrada
- FASE 3 cerrada
- FASE 4:
  - PR1 Secret Broker ✅
  - PR2 Policy engine formal ✅
  - PR3 Sandbox profiles ✅

## Siguiente paso lógico

**FASE 4 PR4 — seguridad explicable + compliance pack inicial**

Con foco en:

- explicación unificada allow/deny/approval/sandbox/secret
- surfaces de UI/API para decisiones de seguridad
- export inicial de accesos sensibles, secretos y aprobaciones
