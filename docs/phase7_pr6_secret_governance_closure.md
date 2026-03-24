# FASE 7 PR6 — secret governance UI + cierre de fase

## Objetivo
Cerrar FASE 7 cubriendo la pieza visible que faltaba del roadmap: una superficie de **secret governance UI** integrada con la consola operativa y con la seguridad ya construida en FASE 4.

## Qué se ha añadido

### 1. Secret governance service
Nuevo servicio `SecretGovernanceService` con tres capacidades principales:
- **catálogo de secret refs** con visibilidad, metadatos y estado de rotación/caducidad
- **uso agregado** desde eventos `secret_resolved`
- **explainability** de acceso a secretos por `ref + tool + role + tenant/workspace/environment + domain`

### 2. Endpoints nuevos
Admin HTTP:
- `GET /admin/secrets/catalog`
- `GET /admin/secrets/usage`
- `POST /admin/secrets/explain`

Broker admin:
- `GET /broker/admin/secrets/catalog`
- `GET /broker/admin/secrets/usage`
- `POST /broker/admin/secrets/explain`

### 3. UI nueva
Nueva pestaña **Secrets** en `/ui` con:
- resumen de governance
- catálogo de secretos
- grupos de uso recientes
- explain access interactivo
- filtros por texto, ref y tool
- snapshot copiable del catálogo

## Decisiones importantes
- No se exponen secretos reales ni hashes derivados del valor.
- La vista usa metadatos declarativos (`owner`, `provider`, `expires_at`, `labels`) para estado operacional.
- La analítica de uso se basa en auditoría ya existente, sin migración adicional.

## Resultado
Con esta PR la FASE 7 queda alineada con todos los entregables visibles del roadmap:
- workflow builder visual
- policy explorer
- replay
- operator console avanzada
- secret governance UI

## Validación ejecutada
- `python -m compileall -q app.py openmiura tests`
- `pytest -q`
- tests específicos de FASE 7 y nuevo bloque de secret governance
