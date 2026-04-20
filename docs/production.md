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

## 3. Perfil base recomendado

Usa `ops/env/production-like.env` como plantilla inicial. openMiura es ahora secure-by-default: limita dominios de `web_fetch`, deja `terminal_exec` deshabilitado y obliga a revisar explícitamente cualquier relajación. Después sustituye todos los placeholders y revisa `docs/configuration_profiles.md` para entender la precedencia entre `.env` y YAML.

## 4. Variables importantes

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

## 5. Reverse proxy y TLS

Publica openMiura detrás de Nginx o Caddy. Termina TLS ahí y reenvía:

- `Host`
- `X-Forwarded-Proto`
- `X-Forwarded-For`
- `X-Request-ID`

Mantén `proxy_buffering off` si vas a usar SSE de chat, terminal o eventos live.

## 6. Endpoints a proteger especialmente

- `/broker/auth/*`
- `/broker/admin/*`
- `/broker/tools/call`
- `/broker/terminal/stream`
- `/metrics`, Grafana, Prometheus y Alertmanager si no están en red interna

## 7. Recomendaciones operativas

- usa roles `user`, `operator` y `admin`
- restringe `terminal_exec` al mínimo posible
- activa cookies seguras y CSRF si la UI se usa desde navegador
- rota tokens regularmente
- revisa dashboards a diario si el sistema está en uso continuo
- programa backups y prueba restore periódicamente

## 8. Arranque recomendado con Compose

```bash
cp ops/env/production-like.env .env
docker compose --profile observability up --build -d
```

## 9. Lista de comprobación previa a producción

- `openmiura doctor --config configs/openmiura.yaml` sin errores críticos
- backup inicial generado
- login admin probado
- alertas sintéticas enviadas
- dashboard Grafana cargado
- reverse proxy con TLS probado
- rate limiting verificado
- expiración/rotación de sesiones y tokens configurada


## Referencias alpha

- [Self-hosted Enterprise Alpha](enterprise_alpha.md)
- [Enterprise Alpha release checklist](alpha_release_checklist.md)
- [Release Candidate RC1](release_candidate.md)
- [Release support matrix](release_support_matrix.md)
- [RC1 quickstart](quickstarts/release_candidate.md)
