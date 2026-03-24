# FASE 6 PR2 — auth/storage scaffolding + contract/security checks + base del registry privado

## Objetivo
Extender la DX pública de openMiura para que el SDK no cubra solo `tool/skill/provider/channel`, sino también `auth_provider` y `storage_backend`, y preparar una base real de registry privado con flujo mínimo de publicación, aprobación e instalación.

## Alcance implementado

### 1. Scaffolding ampliado
Se ha ampliado `openmiura create ...` con dos nuevos tipos:
- `openmiura create auth <name>`
- `openmiura create storage <name>`

Cada scaffold genera:
- `manifest.yaml`
- módulo Python listo para el tipo de extensión
- `README.md`
- `pyproject.toml`
- `tests/test_smoke.py`

### 2. Harness más rico
`ExtensionHarness` ahora añade validaciones adicionales:
- compatibilidad de `contract_version` por major
- validación de `config_schema.type == object`
- advertencias para manifiestos con poca declaración operativa (`permissions` / `capabilities`)
- comprobación de consistencia entre el `manifest.yaml` y el `manifest` expuesto por el entrypoint
- validación mínima de firmas por tipo de extensión
- escaneo estático simple de patrones peligrosos

#### Patrones bloqueados actualmente
- `os.system(`
- `shell=True`
- `eval(`
- `exec(`

#### Patrones avisados actualmente
- `pickle.loads(`
- `yaml.load(`

### 3. Registry privado base
Se introduce `ExtensionRegistry` con backend local en filesystem.

Soporta:
- inicialización del registry
- publicación de una extensión versionada
- listado filtrable por namespace / status / kind
- aprobación de publicación
- instalación controlada desde el registry a un destino local

### 4. CLI del registry
Nuevos comandos:
- `openmiura registry init`
- `openmiura registry publish <path>`
- `openmiura registry list`
- `openmiura registry approve <name> <version>`
- `openmiura registry install <name>`

## Decisiones de diseño
- El registry es local-first y deliberadamente simple; sirve como base contractual y operativa para evolucionar más adelante a revisión, firma y políticas de tenant.
- El harness se mantiene agnóstico de runtime real; las comprobaciones nuevas no rompen la ejecución local ni los casos existentes.
- Los checks de seguridad son conservadores y fáciles de explicar; se prioriza evitar patrones muy problemáticos sin meter un falso analizador estático complejo.

## Limitaciones conocidas
- El registry aún no implementa firma/verificación criptográfica.
- No hay flujo de rollback publicado como comando formal; la base queda preparada mediante versionado e instalación por versión.
- El escaneo estático es textual, no semántico.

## Resultado
Con esta PR, FASE 6 deja de ser solo SDK + scaffolding básico y pasa a tener:
- cobertura inicial de extensiones enterprise (`auth`, `storage`)
- contract/security checks más serios
- base operativa del registry privado
