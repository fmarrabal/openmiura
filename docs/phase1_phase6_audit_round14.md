# Auditoría y avance round 14 — apertura de FASE 6

## Estado

Se ha abierto la FASE 6 con una implementación funcional del primer bloque:

- SDK oficial reforzado
- scaffolding CLI
- test harness de extensiones

## Cambios principales

### 1. SDK público reforzado

Nuevos componentes exportados desde `openmiura.extensions.sdk`:

- `ExtensionHarness`
- `ExtensionTestReport`
- `ScaffoldResult`
- `scaffold_project(...)`

### 2. Scaffolding CLI

Nuevos comandos:

- `openmiura create tool <name>`
- `openmiura create skill <name>`
- `openmiura create provider <name>`
- `openmiura create channel <name>`
- `openmiura create workflow <name>`

### 3. Test harness

Nuevos comandos:

- `openmiura sdk validate-manifest <path>`
- `openmiura sdk test-extension <path>`

Cobertura inicial:

- validación de manifests
- carga local de entrypoints desde filesystem
- contract checks por tipo de extensión
- smoke tests para tool, skill, provider y channel

### 4. Loader endurecido

`ExtensionLoader` ahora soporta carga local añadiendo temporalmente el directorio del scaffold al `sys.path`.

## Problemas encontrados y corregidos durante la implementación

### Ciclo de importación en `openmiura.extensions`

Apareció un ciclo entre:

- `openmiura.extensions.__init__`
- `openmiura.extensions.loader`
- `openmiura.extensions.sdk.__init__`
- `openmiura.extensions.sdk.harness`

Corrección aplicada:

- `openmiura.extensions.__init__` pasa a usar `__getattr__` perezoso
- `harness.py` deja de importar desde `openmiura.extensions.sdk` y pasa a importar módulos concretos

Con esto queda eliminada la circularidad.

## Validación realizada

- `python -m compileall -q app.py openmiura tests` → OK
- `pytest -q tests/test_phase6_* tests/test_phase5_* tests/test_phase4_* tests/test_cli_*` → OK

## Tests nuevos añadidos

- `tests/test_phase6_sdk_scaffold.py`
- `tests/test_phase6_extension_harness.py`

## Resultado

FASE 6 queda **abierta correctamente** con una base funcional para DX/extensibilidad.

## Siguiente paso recomendado

FASE 6 PR2:

- ampliar scaffolding a `auth` y `storage`
- añadir compatibilidad/version checks más ricos al harness
- preparar flujo inicial de registry privado
