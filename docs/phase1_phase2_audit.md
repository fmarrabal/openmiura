# Auditoría de cierre de FASE 1 y FASE 2

## Resumen
Se ha revisado el código del repositorio, se ha ejecutado la suite de tests y se han corregido varios puntos que dejaban incompleta la clausura de las fases 1 y 2 del roadmap.

## Hallazgos corregidos

### 1. Separación de interfaces de canales aún incompleta
Antes, `openmiura.interfaces.http.app` seguía montando Slack y Telegram desde `openmiura.endpoints.*`.

Corrección aplicada:
- nuevas rutas canónicas en `openmiura/interfaces/channels/slack/routes.py`
- nuevas rutas canónicas en `openmiura/interfaces/channels/telegram/routes.py`
- `openmiura/endpoints/slack.py` y `openmiura/endpoints/telegram.py` quedan como shims de compatibilidad

### 2. Persistencia sin ruta canónica en infraestructura
Aunque el runtime ya estaba refactorizado parcialmente, faltaba un namespace explícito para persistencia.

Corrección aplicada:
- `openmiura/infrastructure/persistence/audit_store.py`
- `openmiura/infrastructure/persistence/db.py`
- imports internos actualizados en gateway, CLI y tools runtime

### 3. Fuga de catálogo tenancy para admins con scope acotado
`/broker/admin/tenancy` devolvía el catálogo completo aun cuando el usuario tenía un scope acotado por workspace.

Corrección aplicada:
- `TenancyService.catalog(...)` ahora soporta filtrado por `tenant_id`, `workspace_id` y `environment`
- `broker/admin/overview` y `broker/admin/tenancy` devuelven catálogo filtrado por scope efectivo

### 4. Escalado implícito en effective-config
`/broker/admin/tenancy/effective-config` resolvía la configuración por defecto cuando no se pasaban parámetros, incluso para usuarios con scope acotado.

Corrección aplicada:
- el endpoint ahora usa por defecto el scope del usuario autenticado
- además valida el scope objetivo mediante `AuthService.validate_target_scope(...)`

### 5. Resolución incorrecta del environment por defecto
Al resolver un workspace explícito sin `environment`, se heredaba el environment global por defecto en lugar del `default_environment` del workspace.

Corrección aplicada:
- `TenancyService.resolve(...)` ahora usa el `default_environment` del workspace seleccionado

### 6. Métricas y conteos de overview no segregados del todo
Los `db_counts` seguían siendo globales.

Corrección aplicada:
- nuevos métodos de conteo scope-aware en `AuditStore`
- nuevo `table_counts_scoped(...)`
- `metrics_summary(...)` y `/broker/admin/overview` usan conteos segregados por scope

## Verificación
- suite completa de tests ejecutada
- nuevos tests añadidos para cerrar huecos detectados en arquitectura y segregación de scope
