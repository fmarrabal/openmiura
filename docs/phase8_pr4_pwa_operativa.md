# FASE 8 · PR4 — App foundation: PWA operativa

## Objetivo
Abrir una superficie móvil e instalable para openMiura, orientada a operación real: approvals, replay, operator console y voz, sin romper seguridad, segregación ni trazabilidad.

## Qué se añade
- `manifest.webmanifest` con modo `standalone`, accesos directos y assets de icono.
- `service-worker.js` con cache básico de shell, fallback offline y manejo de `notificationclick`.
- `offline.html` como fallback cuando la shell está cacheada pero no hay conectividad.
- Nueva pestaña **App** en la UI con:
  - registro de instalación actual
  - creación de notificaciones operativas
  - generación de deep links seguros
  - vista de instalaciones, notificaciones y deep links recientes
- Persistencia nueva:
  - `app_installations`
  - `app_notifications`
  - `app_deep_links`
- Endpoints admin HTTP y broker para listar/crear estos artefactos.
- Resolución de deep links por servidor mediante `GET /app/deep-links/{link_token}` con redirección hacia `/ui/`.

## Criterios de aceptación cubiertos
- **Instalación como PWA**: manifest y service worker servidos desde `/ui/`.
- **Notificaciones funcionales**: el backend modela y persiste notificaciones, y la UI puede disparar una notificación local cuando el permiso está concedido.
- **Deep links seguros**: se generan tokens persistidos y el servidor resuelve la navegación sin exponer datos sensibles en el registro interno.
- **Navegación segura con permisos válidos**: el deep link solo abre la shell; la lectura de datos sigue protegida por las APIs ya existentes de broker/admin.

## Estado de PR4
PR4 deja la base PWA **operativa, persistida y auditada**, pero todavía no implementa push remota real con proveedores externos ni empaquetado nativo. Esa parte queda para PR8.
