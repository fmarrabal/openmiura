# openMiura — FASE 8 PR8

## Packaging, hardening y cierre de DX

PR8 cierra la FASE 8 con cuatro bloques:

- **Packaging**: scaffolds para shell desktop (Electron) y mobile (Capacitor).
- **Hardening**: límites operativos para voz, canvas, realtime y PWA.
- **DX**: quickstarts por perfil y script base de empaquetado.
- **Smoke E2E**: validación mínima transversal release + voice + canvas.

## Cambios principales

### 1. Packaging

Se añade `PackagingHardeningService` con:

- `packaging_summary()`
- `hardening_summary()`
- `create_package_build()`
- `list_package_builds()`

Además se incorpora persistencia de `package_builds` para registrar builds auditables por tenant/workspace/environment.

### 2. Hardening

Se añaden controles de endurecimiento:

- **Voice**
  - límite de transcripciones por minuto
  - límite de longitud de transcript
  - límite de longitud de respuesta TTS
- **Canvas**
  - límite de documentos por scope
  - límite de nodos, aristas y vistas por canvas
  - límite de tamaño de payload
  - límite de tamaño de snapshot
  - límite de longitud de comentario
- **PWA/HTTP**
  - `Permissions-Policy` con `microphone=(self)`
- **Realtime**
  - perfil declarado de timeout/backoff/retries para la siguiente capa de runtime

### 3. UI / DX

Se añade en la UI una sección **Packaging & hardening** dentro de la pestaña App, con:

- resumen de packaging
- resumen de hardening
- registro manual de builds
- listado de builds registrados

Se añaden quickstarts:

- `docs/quickstarts/operator.md`
- `docs/quickstarts/admin.md`
- `docs/quickstarts/approver.md`
- `docs/quickstarts/developer.md`

### 4. Scaffolds

Se añaden:

- `packaging/desktop/electron/*`
- `packaging/mobile/capacitor/*`
- `scripts/package_phase8_shell.py`

## Endpoints nuevos

### HTTP admin

- `GET /admin/phase8/packaging/summary`
- `GET /admin/phase8/packaging/builds`
- `POST /admin/phase8/packaging/builds`

### Broker admin

- `GET /broker/admin/phase8/packaging/summary`
- `GET /broker/admin/phase8/packaging/builds`
- `POST /broker/admin/phase8/packaging/builds`

## Migración

Se añade la migración **16**:

- tabla `package_builds`
- índice `idx_package_builds_scope_created`

## Criterios cubiertos

- empaquetado base desktop/mobile disponible
- endurecimiento mínimo aplicado a voz/canvas/PWA
- quickstarts por perfil incorporados
- smoke transversal de release + voice + canvas preparado
