# Audit round 4 — cierre FASE 1–3 + arranque FASE 4

## Resultado general

La base de FASE 1, 2 y 3 queda estable.

Validación ejecutada:

- `pytest -q` → OK
- `python -m compileall -q app.py openmiura tests` → OK

## Hallazgos reales de auditoría corregidos en esta ronda

### 1. Gap de configuración en `load_settings(...)`
La carga desde YAML estaba dejando fuera parte de la política real de tools:

- `tools.tool_role_policies`
- `terminal.allow_multiline`
- `terminal.require_explicit_allowlist`
- `terminal.blocked_patterns`

Impacto:
- el runtime podía comportarse distinto según se construyera `Settings(...)` a mano en tests o desde YAML real en producción.

Estado:
- corregido.

### 2. Ruido menor en bootstrap de gateway
Había una duplicación inocua al leer la variable del password bootstrap del admin en `Gateway.from_config(...)`.

Impacto:
- no rompía funcionalidad, pero era incoherente y ensuciaba la ruta de inicialización.

Estado:
- corregido.

### 3. FASE 4 no estaba realmente iniciada en el carril de secretos
Aunque existía `ContextVault` para memoria, todavía no había una capa explícita de secret refs y resolución gobernada en runtime.

Estado:
- se abre FASE 4 con un `SecretBroker` integrado.

## Implementación añadida

### Secret Broker foundation
Se incorpora:

- `SecretRefSettings` y `SecretsSettings`
- `openmiura.core.secrets.SecretBroker`
- inyección del broker en `Gateway` y `ToolRuntime`
- `ToolContext.resolve_secret(...)`
- redacción automática de secretos conocidos en:
  - auditoría de tool calls
  - eventos realtime
  - memoria derivada de tool results
  - salida de tools cuando contenga el valor sensible

### Cobertura de tests añadida

- parseo de `secrets.refs` desde configuración
- enforcement por tool/rol/scope/domain
- auditoría de resoluciones de secretos
- redacción de secretos en output y audit trail de tools

## Conclusión de roadmap

- FASE 1: cerrada
- FASE 2: cerrada
- FASE 3: cerrada
- FASE 4: iniciada correctamente

El siguiente paso lógico ya no es seguir apretando FASE 3.
El siguiente paso correcto es continuar FASE 4 con:

1. policy engine formal unificado,
2. explainability de decisiones,
3. sandbox profiles por rol/scope,
4. compliance/export de accesos sensibles.
