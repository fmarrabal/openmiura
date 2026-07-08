# Production guide

This guide summarizes a reasonable configuration for deploying openMiura in a
stable way.

## 1. Recommended mode

For light production or advanced home use:

- backend: SQLite
- UI + broker in a single container
- reverse proxy with TLS
- scheduled backups

For more serious production:

- backend: PostgreSQL
- dedicated reverse proxy
- observability with Prometheus/Grafana/Alertmanager
- token and session rotation enabled

## 2. Recommended deployment

### Option A: home / lab environment

- `storage.backend=sqlite`
- persistent volume under `data/`
- TLS terminated at Caddy or Nginx
- broker protected by a token or UI auth

### Option B: serious operation

- `storage.backend=postgresql`
- `OPENMIURA_AUTH_COOKIE_ENABLED=true`
- `OPENMIURA_AUTH_COOKIE_SECURE=true`
- `OPENMIURA_AUTH_CSRF_ENABLED=true`
- Prometheus/Grafana/Alertmanager active
- API tokens with TTL and rotation

## 3. Recommended base profile

Use `ops/env/production-like.env` as the initial template. openMiura is now
secure-by-default: it limits `web_fetch` domains, leaves `terminal_exec`
disabled, and forces you to explicitly review any relaxation. Then replace all
placeholders and read `docs/configuration_profiles.md` to understand the
precedence between `.env` and YAML.

## 4. Important variables

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

## 5. Reverse proxy and TLS

Publish openMiura behind Nginx or Caddy. Terminate TLS there and forward:

- `Host`
- `X-Forwarded-Proto`
- `X-Forwarded-For`
- `X-Request-ID`

Keep `proxy_buffering off` if you are going to use chat, terminal, or live-event
SSE.

## 6. Endpoints to protect with special care

- `/broker/auth/*`
- `/broker/admin/*`
- `/broker/tools/call`
- `/broker/terminal/stream`
- `/metrics`, Grafana, Prometheus, and Alertmanager if they are not on an
  internal network

## 7. Operational recommendations

- use the `user`, `operator`, and `admin` roles
- restrict `terminal_exec` to the minimum possible
- enable secure cookies and CSRF if the UI is used from a browser
- rotate tokens regularly
- review dashboards daily if the system is in continuous use
- schedule backups and test the restore periodically

## 8. Recommended startup with Compose

```bash
cp ops/env/production-like.env .env
docker compose --profile observability up --build -d
```

## 9. Pre-production checklist

- `openmiura doctor --config configs/openmiura.yaml` with no critical errors
- initial backup generated
- admin login tested
- synthetic alerts sent
- Grafana dashboard loaded
- reverse proxy with TLS tested
- rate limiting verified
- session and token expiry/rotation configured


## Alpha references

- [Self-hosted Enterprise Alpha](enterprise_alpha.md)
- [Enterprise Alpha release checklist](alpha_release_checklist.md)
- [Release Candidate RC1](release_candidate.md)
- [Release support matrix](release_support_matrix.md)
- [RC1 quickstart](quickstarts/release_candidate.md)
