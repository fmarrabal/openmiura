# FASE 6 PR3 — contract tests avanzados + compatibilidad/versionado + flujo formal del registry

## Objetivo
Cerrar la segunda mitad de FASE 6 elevando el SDK y el registry desde un scaffolding útil a una base más formal para ecosistema interno enterprise.

## Qué se ha implementado

### 1. Compatibilidad y versionado de extensiones
Se ha ampliado el modelo público de `ExtensionManifest` con dos bloques nuevos:

- `compatibility`
  - `min_openmiura_version`
  - `max_openmiura_version`
  - `tested_contract_versions`
  - `backward_compatible_from`
- `review`
  - `reviewers`
  - `required_approvals`

Además, el SDK incorpora helpers reutilizables:

- `semver_key(...)`
- `compare_versions(...)`
- `detect_version_bump(...)`
- `evaluate_extension_compatibility(...)`

Con esto el runtime/harness/registry pueden decidir si una extensión es compatible con la versión actual de openMiura y con la versión del contrato público.

### 2. Contract tests avanzados en el harness
`ExtensionHarness` se ha reforzado para validar no solo el manifest, sino también:

- compatibilidad real contra la versión actual de openMiura
- consistencia del `contract_version` entre manifest y entrypoint exportado
- checks de empaquetado (`README.md`, `CHANGELOG.md`, `tests/test_smoke.py`)
- validación del resultado del smoke test por tipo de extensión
- serializabilidad JSON del resultado del smoke test

El informe del harness ahora devuelve adicionalmente:

- `compatibility`
- `contract_checks`
- `packaging_checks`

### 3. Scaffolding mejorado
El scaffolding de extensiones ahora genera:

- bloque `compatibility` en `manifest.yaml`
- bloque `review` en `manifest.yaml`
- `CHANGELOG.md`
- ejemplos preparados para pasar por el flujo del registry

### 4. Registry privado con flujo de revisión/publicación más formal
`ExtensionRegistry` se ha ampliado con:

- evaluación automática del harness en `publish(...)`
- bloqueo de publicación si la extensión no pasa harness/compatibilidad
- clasificación de release semántica (`initial`, `patch`, `minor`, `major`, `same`, `downgrade`)
- historial de revisión (`review_history`)
- métodos nuevos:
  - `describe(...)`
  - `start_review(...)`
  - `verify(...)`
  - `deprecate(...)`
- verificación de checksum antes de instalar

El flujo soportado queda así:

1. `publish`
2. `review-start`
3. `approve` o `reject`
4. `verify`
5. `install`
6. `deprecate` si procede

### 5. CLI ampliada
Se añaden comandos nuevos:

- `openmiura registry review-start`
- `openmiura registry reject`
- `openmiura registry describe`
- `openmiura registry verify`
- `openmiura registry deprecate`

## Corrección realizada durante esta ronda
Durante la implementación apareció una regresión real:

- el `packaging check` del harness trataba la ausencia de `README.md` como error duro y eso impedía llegar a validar fallos de contrato/entrypoint en fixtures minimalistas.
- se corrigió para que los checks de empaquetado sean señal de calidad y no oculten errores contractuales más importantes.

## Cobertura de tests añadida
Se añadieron pruebas para:

- helpers de versionado semántico
- incompatibilidad por ventana de versión de openMiura
- flujo formal del registry
- checksum verification
- CLI extendida del registry
- scaffolds con `CHANGELOG.md`

## Validación ejecutada
- `pytest -q tests/test_phase5_* tests/test_phase6_* tests/test_cli_* tests/unit/test_extension_sdk.py` ✅
- `python -m compileall -q app.py openmiura tests` ✅

## Resultado
Con esta PR, FASE 6 ya no solo dispone de SDK y scaffolding, sino también de:

- contrato público más maduro
- matriz básica de compatibilidad
- flujo formal de publicación y revisión
- verificación de integridad antes de instalar extensiones

El siguiente paso lógico sería **FASE 6 PR4 — endurecimiento del registry para firma/verificación más fuerte + políticas de instalación por tenant + documentación/DX final de publicación**.
