# Arquitectura por capas: refactor inicial aplicado

Este cambio introduce una primera vertical de la arquitectura propuesta sin romper la compatibilidad observable del proyecto.

## Qué se ha aplicado

### 1. Application layer
Se añaden servicios de aplicación para separar casos de uso del transporte HTTP:

- `openmiura/application/admin/service.py`
- `openmiura/application/memory/service.py`
- `openmiura/application/sessions/service.py`

Estos servicios absorben la agregación del snapshot admin, búsqueda/borrado de memoria y listado de sesiones/eventos/identidades.

### 2. Contratos ligeros del core
Se añaden protocolos mínimos para desacoplar la capa Application del objeto `Gateway` concreto:

- `openmiura/core/contracts/admin.py`

No es todavía una extracción completa del dominio, pero sí un primer paso para que Application dependa de capacidades y no de implementaciones concretas.

### 3. Interfaces HTTP explícitas
La implementación canónica del router admin pasa a:

- `openmiura/interfaces/http/routes/admin.py`

El módulo histórico `openmiura/endpoints/admin.py` se mantiene como shim de compatibilidad.

### 4. Bootstrap de infraestructura
Se centraliza la construcción/probing del gateway en:

- `openmiura/infrastructure/bootstrap/container.py`

### 5. App HTTP desacoplada
La implementación de la app HTTP pasa a:

- `openmiura/interfaces/http/app.py`

El `app.py` raíz se mantiene para compatibilidad con tests, monkeypatching y despliegues existentes.

## Resultado

- Se mantiene el contrato observable actual.
- La lógica de `/admin/*` deja de vivir en el endpoint y pasa a servicios de aplicación.
- `app.py` deja de ser el único lugar donde se concentra la composición del sistema.
- Se conserva la compatibilidad con la suite actual y con el patrón de parcheo usado por los tests.

## Próximo paso recomendado

La siguiente vertical natural sería repetir este patrón en:

1. broker HTTP
2. Slack / Telegram transport
3. auth / policy engine
4. extracción progresiva de persistencia a `infrastructure/persistence/*`


## Extensión aplicada en PR2: auth / policy unificado

Se ha añadido una segunda vertical del refactor de Fase 1 para centralizar autenticación y autorización del broker sin romper contratos existentes.

### Piezas nuevas

- `openmiura/application/auth/service.py`
- `openmiura/core/auth/models.py`
- `openmiura/core/policies/engine.py`
- `openmiura/core/policies/models.py`
- `openmiura/core/policies/__init__.py`

### Compatibilidad hacia atrás

- `openmiura/core/policy.py` sigue existiendo como shim de compatibilidad.
- El broker HTTP mantiene rutas, payloads y códigos HTTP.
- La suite actual sigue pasando completa.

### Cambio arquitectónico concreto

- La matriz de permisos del broker deja de vivir embebida en `openmiura/channels/http_broker.py`.
- La resolución del contexto de autenticación del broker se centraliza en `AuthService`.
- El motor de políticas tiene ya una ubicación canónica bajo `openmiura/core/policies/*`.

### Resultado

Con esto queda cerrada la subfase de Fase 1 centrada en **arquitectura + contratos + modelo común de permisos/capacidades** antes de abordar el troceado del broker como siguiente hito.


## PR3 — broker HTTP v1 por verticales

Se ha troceado el broker HTTP en `interfaces/broker/*`, manteniendo `openmiura/channels/http_broker.py` como shim de compatibilidad. Con esto la FASE 1 del roadmap avanza en el bloque de arquitectura, contratos y formalización del broker.
