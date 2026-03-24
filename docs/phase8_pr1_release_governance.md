# openMiura — FASE 8 PR1

## Release model y promotion pipeline base

Esta entrega abre la FASE 8 con la base persistente de **release governance** para agentes, workflows, bundles de políticas, prompt packs y toolset bundles.

## Alcance implementado

### Persistencia
Se añade la migración **9** con las tablas:
- `release_bundles`
- `release_bundle_items`
- `release_promotions`
- `release_approvals`
- `release_rollbacks`
- `environment_snapshots`

### Backend
Se incorpora `ReleaseService` y soporte de `AuditStore` para:
- crear releases en estado `draft`
- listar y detallar releases
- enviar a revisión (`submit`)
- aprobar (`approve`)
- promover entre entornos (`promote`)
- rollback lógico (`rollback`)

### Estados soportados
- `draft`
- `candidate`
- `approved`
- `promoted`
- `rolled_back`

### Endpoints HTTP admin
- `GET /admin/releases`
- `GET /admin/releases/{release_id}`
- `POST /admin/releases`
- `POST /admin/releases/{release_id}/submit`
- `POST /admin/releases/{release_id}/approve`
- `POST /admin/releases/{release_id}/promote`
- `POST /admin/releases/{release_id}/rollback`

### Endpoints broker admin
- `GET /broker/admin/releases`
- `GET /broker/admin/releases/{release_id}`
- `POST /broker/admin/releases`
- `POST /broker/admin/releases/{release_id}/submit`
- `POST /broker/admin/releases/{release_id}/approve`
- `POST /broker/admin/releases/{release_id}/promote`
- `POST /broker/admin/releases/{release_id}/rollback`

### UI
Se añade una pestaña inicial **Releases** en `/ui` para:
- crear un draft
- listar releases
- cargar detalle
- ejecutar submit / approve / promote / rollback

## Notas de diseño

- El rollback se apoya en `environment_snapshots` creados antes de cada promoción.
- La promoción mueve la release aprobada al entorno objetivo y degrada la release previamente activa a `approved`.
- La lógica de `canary`, `gates` y `change intelligence` queda reservada para **PR2**.

## Criterio de aceptación cubierto en esta PR

- no se puede promover una release en `draft`
- la aprobación cambia el estado a `approved`
- la promoción genera snapshot + promotion record
- el rollback restaura la release previamente activa
- el scoping por `tenant/workspace/environment` se preserva en lectura y escritura
