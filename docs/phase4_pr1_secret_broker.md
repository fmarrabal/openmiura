# Phase 4 PR1 — Secret Broker foundation

## Objetivo

Abrir la FASE 4 con una base real para:

- secret refs en lugar de secretos en texto plano,
- resolución autorizada en runtime,
- scoping por tool/rol/tenant/workspace/environment/domain,
- redacción automática de secretos en logs, auditoría, realtime y memoria.

## Cambios principales

### 1. Nueva configuración `secrets`
Se añade una sección formal en `configs/openmiura.yaml`:

- `secrets.enabled`
- `secrets.redact_logs`
- `secrets.refs`

Cada ref soporta:

- `value` o `value_env_var`
- `allowed_tools`
- `denied_tools`
- `allowed_roles`
- `denied_roles`
- `allowed_tenants`
- `allowed_workspaces`
- `allowed_environments`
- `allowed_domains`
- `metadata`

### 2. `SecretBroker`
Se incorpora `openmiura.core.secrets.SecretBroker` con:

- resolución de refs,
- controles de autorización,
- validación de domain pinning,
- auditoría de uso (`channel=security`, `event=secret_resolved`),
- redacción de valores sensibles.

### 3. Integración con `ToolRuntime`
`ToolRuntime` pasa a:

- inyectar el broker en `ToolContext`,
- exponer `ctx.resolve_secret(...)` a las tools,
- redactor automático de `args`, `result_excerpt`, `error` y memoria,
- evitar que un secreto conocido viaje sin redacción a logs o eventos.

### 4. Integración con `Gateway`
`Gateway.from_config(...)` crea un `SecretBroker` y lo propaga al runtime de tools.

## Ejemplo de uso

```yaml
secrets:
  enabled: true
  redact_logs: true
  refs:
    github_pat:
      value_env_var: OPENMIURA_GITHUB_PAT
      allowed_tools: [web_fetch]
      allowed_roles: [admin, operator]
      allowed_tenants: [acme]
      allowed_workspaces: [research]
      allowed_environments: [prod]
      allowed_domains: [api.github.com]
```

Una tool puede resolverlo así:

```python
secret = ctx.resolve_secret(
    "github_pat",
    tool_name="web_fetch",
    domain="https://api.github.com/repos/org/repo",
)
```

## Validación

- `pytest -q` → OK
- `python -m compileall -q app.py openmiura tests` → OK

## Siguiente paso sugerido dentro de FASE 4

PR2 debería cerrar el carril de seguridad formal:

- policy engine unificado más allá de tools,
- decisiones explainable,
- hooks de aprobación/política sobre secretos,
- perfiles de sandboxing enlazados a rol/scope.
