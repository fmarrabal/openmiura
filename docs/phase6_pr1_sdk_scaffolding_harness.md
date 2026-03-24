# FASE 6 PR1 — SDK oficial + scaffolding CLI + test harness de extensiones

## Alcance implementado

Esta iteración abre la FASE 6 con tres piezas operativas:

- **SDK oficial reforzado** en `openmiura.extensions.sdk`
- **CLI de scaffolding** con comandos `openmiura create ...`
- **test harness local** con `openmiura sdk validate-manifest` y `openmiura sdk test-extension`

## SDK oficial

Se consolida la superficie pública del SDK con exportaciones estables para:

- tools
- skills
- LLM providers
- channel adapters
- auth providers
- storage backends
- observability exporters

Además se añaden:

- `ExtensionHarness`
- `ExtensionTestReport`
- `scaffold_project(...)`

## CLI de scaffolding

Nuevos comandos:

- `openmiura create tool <name>`
- `openmiura create skill <name>`
- `openmiura create provider <name>`
- `openmiura create channel <name>`
- `openmiura create workflow <name>`

Cada scaffold genera una estructura mínima profesional con:

- `manifest.yaml`
- implementación Python o `playbook.yaml`
- `README.md`
- `pyproject.toml` para extensiones Python
- `tests/test_smoke.py`

## Test harness

Nuevos comandos:

- `openmiura sdk validate-manifest <path>`
- `openmiura sdk test-extension <path>`

Capacidades iniciales:

- validación estructural de manifests
- carga local del entrypoint desde el filesystem
- contract checks por tipo de extensión
- smoke tests con contextos simulados para tool/skill/provider/channel

## Notas de diseño

- Se mantiene compatibilidad hacia atrás con los contratos ya definidos en la fase 1.
- El loader se ha endurecido para poder cargar extensiones locales añadiendo temporalmente el directorio al `sys.path`.
- El scaffold de `workflow` genera un playbook declarativo y no un módulo Python.

## Siguiente paso recomendado

FASE 6 PR2:

- ampliar el harness con validación de seguridad y compatibilidad de versiones
- añadir `openmiura create auth` y `openmiura create storage`
- preparar un registry privado mínimo y flujo de publicación interna
