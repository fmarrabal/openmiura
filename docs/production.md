# Guía de producción

Esta guía resume una configuración razonable para desplegar openMiura de forma estable.

## 1. Modo recomendado

Para producción ligera o doméstica avanzada:

- backend: SQLite
- UI + broker en un único contenedor
- reverse proxy con TLS
- backups programados

Para producción más seria:

- backend: PostgreSQL
- reverse proxy dedicado
- observabilidad con Prometheus/Grafana/Alertmanager
- rotación de tokens y sesiones activada

## 2. Despliegue recomendado

### Opción A: entorno casero / laboratorio

- `storage.backend=sqlite`
- volumen persistente en `data/`
- TLS terminado en Caddy o Nginx
- broker protegido por token o auth UI

### Opción B: operación seria

- `storage.backend=postgresql`
- `OPENMIURA_AUTH_COOKIE_ENABLED=true`
- `OPENMIURA_AUTH_COOKIE_SECURE=true`
- `OPENMIURA_AUTH_CSRF_ENABLED=true`
- Prometheus/Grafana/Alertmanager activos
- API tokens con TTL y rotación

## 3. Variables importantes

- `OPENMIURA_ADMIN_TOKEN`
- `OPENMIURA_UI_ADMIN_USERNAME`
- `OPENMIURA_UI_ADMIN_PASSWORD`
- `OPENMIURA_LLM_PROVIDER`
- `OPENMIURA_LLM_BASE_URL`
- `OPENMIURA_LLM_MODEL`
- `OPENMIURA_LLM_API_KEY`
- `OPENMIURA_DB_BACKEND`
- `OPENMIURA_DB_PATH`
- `OPENMIURA_DATABASE_URL`
- `OPENMIURA_AUTH_COOKIE_ENABLED`
- `OPENMIURA_AUTH_COOKIE_SECURE`
- `OPENMIURA_AUTH_CSRF_ENABLED`

## 4. Reverse proxy y TLS

Publica openMiura detrás de Nginx o Caddy. Termina TLS ahí y reenvía:

- `Host`
- `X-Forwarded-Proto`
- `X-Forwarded-For`
- `X-Request-ID`

Mantén `proxy_buffering off` si vas a usar SSE de chat, terminal o eventos live.

## 5. Endpoints a proteger especialmente

- `/broker/auth/*`
- `/broker/admin/*`
- `/broker/tools/call`
- `/broker/terminal/stream`
- `/metrics`, Grafana, Prometheus y Alertmanager si no están en red interna

## 6. Recomendaciones operativas

- usa roles `user`, `operator` y `admin`
- restringe `terminal_exec` al mínimo posible
- activa cookies seguras y CSRF si la UI se usa desde navegador
- rota tokens regularmente
- revisa dashboards a diario si el sistema está en uso continuo
- programa backups y prueba restore periódicamente

## 7. Arranque recomendado con Compose

```bash
cp .env.example .env
docker compose --profile observability up --build -d
```

## 8. Lista de comprobación previa a producción

- `openmiura doctor --config configs/` sin errores críticos
- backup inicial generado
- login admin probado
- alertas sintéticas enviadas
- dashboard Grafana cargado
- reverse proxy con TLS probado
- rate limiting verificado
- expiración/rotación de sesiones y tokens configurada
