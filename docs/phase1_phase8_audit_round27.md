# Auditoría round 27 · PR4 PWA operativa

## Alcance auditado
- migración 12
- persistencia PWA (`app_installations`, `app_notifications`, `app_deep_links`)
- servicio de aplicación `PWAFoundationService`
- endpoints admin HTTP y broker
- assets estáticos de PWA (`manifest.webmanifest`, `service-worker.js`, `offline.html`, iconos)
- integración mínima en la UI

## Hallazgos
- La base PWA queda alineada con el roadmap: instalación, notificaciones, deep links y modo móvil operador.
- La seguridad de navegación sigue descansando en RBAC y broker auth ya existentes; el deep link no bypassea permisos.
- El service worker es deliberadamente contenido: shell cache + offline fallback + click handling. No introduce sincronización compleja ni colas offline todavía.
- La notificación remota real no está implementada; en esta iteración se modela el artefacto y se habilita el disparo local desde la UI cuando hay permiso.

## Riesgo residual
- Falta un proveedor real de push/webpush para campañas operativas multi-dispositivo.
- El modo móvil es funcional pero todavía no equivale a un wrapper nativo endurecido.
- La cache de PWA es conservadora; no intenta cachear datos vivos de operación.

## Resultado
PR4 es consistente con el objetivo de “App foundation” y deja una base razonable para PR5–PR8.
