# Deployment

## Startup with Docker Compose

```bash
cp .env.example .env
docker compose up --build
```

## Observability profile

```bash
docker compose --profile observability up --build
```

### Real alert receivers

Supported variables:

- `OPENMIURA_ALERT_WEBHOOK_URL`
- `OPENMIURA_ALERT_WEBHOOK_HTTP_CONFIG_BEARER_TOKEN`
- `OPENMIURA_ALERT_SLACK_WEBHOOK_URL`
- `OPENMIURA_ALERT_SLACK_CHANNEL`
- `OPENMIURA_ALERT_EMAIL_TO`
- `OPENMIURA_ALERT_EMAIL_FROM`
- `OPENMIURA_ALERT_EMAIL_SMARTHOST`
- `OPENMIURA_ALERT_EMAIL_AUTH_USERNAME`
- `OPENMIURA_ALERT_EMAIL_AUTH_PASSWORD`
- `OPENMIURA_ALERT_EMAIL_REQUIRE_TLS`

Alertmanager renders its final configuration when the container starts, so you
can use the same stack in lab or production by only changing `.env`.

## Alert validation

Once Alertmanager is up:

```bash
python scripts/fire_test_alerts.py --alertmanager-url http://localhost:9093
```

## Reverse proxy

Publish only the necessary ports, and protect Grafana/Prometheus/Alertmanager
behind an internal network or additional authentication if they go beyond the
lab.


## Migration rollback

openMiura supports formal schema downgrades. Examples:

```bash
openmiura db rollback --config configs/ --steps 1
openmiura db rollback --config configs/ --to-version 1
```

Before a downgrade in production, take a backup:

```bash
openmiura db backup --config configs/
```
