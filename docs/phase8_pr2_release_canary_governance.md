# openMiura — FASE 8 PR2

## Evaluation gates, canary modelado y change intelligence base

Esta PR extiende la governance de releases de PR1 con tres artefactos gobernados que quedan **persistidos, auditados y enlazados a la promoción**:

- **evaluation gates** por release
- **canary plan** por release
- **change report** por release

## Alcance implementado

### Persistencia
Se añade la migración **10** con las tablas:
- `release_canaries`
- `release_gate_runs`
- `release_change_reports`

### Backend
Se amplía `ReleaseService` y `AuditStore` para:
- definir un canary plan por release
- registrar ejecuciones de gates con score, threshold y detalles
- registrar un change report con resumen, diff y nivel de riesgo
- propagar estos artefactos al `summary` y `gate_result` de la promoción
- exponer todo en el detalle de la release

### Endpoints HTTP admin
- `POST /admin/releases/{release_id}/canary`
- `POST /admin/releases/{release_id}/gates`
- `POST /admin/releases/{release_id}/change-report`

### Endpoints broker admin
- `POST /broker/admin/releases/{release_id}/canary`
- `POST /broker/admin/releases/{release_id}/gates`
- `POST /broker/admin/releases/{release_id}/change-report`

## Decisión de diseño clave

El canary de esta PR es un **artefacto de gobierno**, no un despliegue progresivo real.

Eso significa:
- sí queda modelado en base de datos
- sí queda trazado en auditoría y en el historial de promoción
- sí puede asociarse a thresholds y criterios de bake
- **todavía no enruta tráfico real ni ejecuta rollout progresivo automático**

## Criterio de aceptación cubierto

- un release aprobado puede tener un canary plan persistido
- un release puede acumular gate runs auditados
- un release puede tener un change report versionado a nivel operativo
- al promover, la promotion conserva snapshot del último gate y del canary/change report asociado
- el detalle de release devuelve estos artefactos para inspección operativa

## Siguiente iteración natural

**PR3 — Voice runtime base**, dejando ya preparado el anclaje con releases gobernadas para rollout multimodal posterior.
