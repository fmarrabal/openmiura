# Despliegue

## Arranque con Docker Compose

```bash
cp .env.example .env
docker compose up --build
```

## Perfil observability

```bash
docker compose --profile observability up --build
```

### Receptores reales de alertas

Variables soportadas:

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

Alertmanager renderiza su configuración final al iniciar el contenedor. Así puedes usar el mismo stack en laboratorio o producción solo cambiando `.env`.

## Validación de alertas

Una vez levantado Alertmanager:

```bash
python scripts/fire_test_alerts.py --alertmanager-url http://localhost:9093
```

## Reverse proxy

Publica solo los puertos necesarios y protege Grafana/Prometheus/Alertmanager detrás de red interna o autenticación adicional si van fuera de laboratorio.


## Rollback de migraciones

openMiura soporta downgrade formal de esquema. Ejemplos:

```bash
openmiura db rollback --config configs/ --steps 1
openmiura db rollback --config configs/ --to-version 1
```

Antes de un downgrade en producción, genera un backup:

```bash
openmiura db backup --config configs/
```
