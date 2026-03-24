# Phase 4 PR2 — Policy engine formal unificado

## Objetivo

Continuar la FASE 4 después del Secret Broker con un motor de políticas más formal, explainable y reutilizable para distintos dominios operativos.

## Alcance implementado

### 1. Motor unificado de políticas
Se amplía `openmiura.core.policies` para soportar, además de las reglas legacy de tools:

- `tool_rules`
- `memory_rules`
- `secret_rules`
- `channel_rules`
- `approval_rules`
- `defaults`

Manteniendo compatibilidad hacia atrás con:

- `agent_rules`
- `user_rules`
- `tool_rules` clásicos con `requires_confirmation`

### 2. Decisiones explainable
Se añaden modelos de decisión y trazas:

- `PolicyDecision`
- `ToolAccessDecision`
- `PolicyTrace`

Cada evaluación devuelve:

- `allowed`
- `requires_confirmation`
- `requires_approval`
- `reason`
- `matched_rules`
- `explanation`

### 3. Evaluaciones soportadas
El engine ahora expone:

- `check_tool_access(...)`
- `check_memory_access(...)`
- `check_secret_access(...)`
- `check_channel_access(...)`
- `check_approval_requirement(...)`
- `explain_request(...)`

### 4. Integración real en runtime
#### Tool runtime
`ToolRuntime` ahora evalúa la policy pasando además:

- `user_role`
- `tenant_id`
- `workspace_id`
- `environment`

De esta forma la decisión de tool ya puede depender del scope enterprise.

#### Secret broker
`SecretBroker` ahora puede consumir también el `PolicyEngine`, de modo que un secreto puede:

- estar permitido por la ref local,
- pero quedar denegado por policy formal.

Esto permite desacoplar:

- configuración del secreto
- gobierno centralizado del acceso al secreto

### 5. Surface de explainability en admin API
Se añade:

- `POST /admin/policies/explain`

Con ello se puede pedir una explicación formal de una decisión sobre:

- tool
- memory
- secret
- channel
- approval

## Ejemplo de policy moderna

```yaml
defaults:
  tools: true
  memory: true
  secrets: true
  channels: true

agent_rules:
  - agent: researcher
    allow_tools: [web_fetch, time_now]

tool_rules:
  - name: deny_terminal_for_user
    tool: terminal_exec
    user_role: user
    effect: deny
    reason: terminal blocked for user

  - name: confirm_web_fetch_prod
    tool: web_fetch
    tenant_id: acme
    workspace_id: research
    environment: prod
    effect: allow
    requires_confirmation: true

memory_rules:
  - name: deny_memory_delete_user
    action: delete
    user_role: user
    effect: deny
    reason: memory deletion reserved to admins

secret_rules:
  - name: deny_terminal_secret
    ref: github_pat
    tool: terminal_exec
    effect: deny
    reason: terminal cannot resolve github secrets

channel_rules:
  - name: deny_discord_prod
    channel: discord
    environment: prod
    effect: deny
    reason: discord disabled in prod

approval_rules:
  - name: require_fs_write_admin_approval
    action_name: fs_write
    effect: require_approval
    reason: write operations require approval
```

## Validación

Se han añadido tests nuevos para:

- engine unificado y explainability
- integración policy + secret broker
- endpoint admin de explicación de políticas

Y además:

- `pytest -q` → OK
- `python -m compileall -q app.py openmiura tests` → OK

## Siguiente paso recomendado dentro de FASE 4

El siguiente bloque lógico sería **PR3 — sandboxing por perfiles + enforcement formal por policy**:

- perfiles `local-safe`, `corporate-safe`, `restricted`, `air-gapped-like`
- límites de red / FS / procesos / tiempo
- mapping por rol / tenant / workspace / tool
- explainability de por qué una ejecución cae en un perfil u otro
