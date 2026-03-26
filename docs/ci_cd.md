# CI/CD

openMiura incluye una configuración base de GitHub Actions para integrar validación continua, auditoría de dependencias y artefactos de release.

## Workflows

### CI (`.github/workflows/ci.yml`)

Se ejecuta en `push`, `pull_request` y manualmente:

- matriz Python 3.10, 3.11 y 3.12
- instalación editable del proyecto
- `pip check`
- compilación sintáctica con `compileall`
- `openmiura doctor`
- `pytest -q`
- build de `sdist` y `wheel` con `SOURCE_DATE_EPOCH` derivado del commit/tag
- smoke test de instalación del wheel generado
- smoke test de `docker build`

Todos los jobs que ejecutan scripts del repositorio usan la acción compuesta local `./.github/actions/setup-openmiura`, que instala el paquete local en modo editable antes de ejecutar `scripts/`. Esto evita regresiones donde los workflows instalan dependencias pero fallan en `import openmiura`.

### Release (`.github/workflows/release.yml`)

Se ejecuta al publicar tags `v*.*.*` o manualmente:

- build de `sdist` y `wheel` con `SOURCE_DATE_EPOCH` derivado del commit/tag
- validación con `twine check`
- build del bundle reproducible con `scripts/reproducible_package.py`
- generación de `SHA256SUMS.txt` y `RELEASE_MANIFEST.json` mediante `scripts/build_release_artifacts.py`
- verificación final con `scripts/verify_release_artifacts.py`
- subida de artefactos de `dist/`
- creación automática de GitHub Release con los artefactos adjuntos

El árbol publicable queda reforzado con `MANIFEST.in`, que garantiza que el `sdist` arrastre documentación, configs, workflows, scripts, packaging shells y assets necesarios para una alpha self-hosted.

### Security (`.github/workflows/security.yml`)

Se ejecuta en PR, semanalmente y manualmente:

- dependency review en pull requests
- `pip-audit` sobre dependencias instaladas
- `gitleaks` sobre el árbol del repositorio
- `gitleaks` sobre artefactos `dist/*` generados en CI

## Pre-commit recomendado

Antes de subir cambios, instala los hooks locales:

```bash
python -m pip install pre-commit
pre-commit install
```

El repositorio incluye hooks para:

- detección de claves privadas
- `gitleaks` sobre cambios staged
- saneamiento básico de ficheros de texto

## Dependabot

`.github/dependabot.yml` mantiene actualizaciones automáticas para:

- dependencias Python
- GitHub Actions

## Recomendaciones de secretos

Para que los workflows funcionen de forma segura:

- no subas `.env`
- usa `OPENMIURA_*` como repository secrets cuando corresponda
- mantén los tokens de producción fuera de la configuración versionada

## Release manual

```bash
python -m pip install --upgrade build twine
python -m build --sdist --wheel
python -m twine check dist/*
python scripts/reproducible_package.py --target desktop --label "Manual build" --version local --output-dir dist
python scripts/build_release_artifacts.py --dist-dir dist --tag v-local --target desktop --strict
python scripts/verify_release_artifacts.py --dist-dir dist
```
