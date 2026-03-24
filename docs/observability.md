# Observabilidad operativa

openMiura expone métricas Prometheus en `GET /metrics` y trae una pila opcional de observabilidad lista para usar con Docker Compose:

- Prometheus para scrape y reglas
- Alertmanager para enrutado de alertas
- Grafana para dashboards operativos

## Arranque rápido

```bash
cp .env.example .env
docker compose --profile observability up --build
```

## Servicios

- App: `http://localhost:8081`
- Grafana: `http://localhost:3000`
- Prometheus: `http://localhost:9090`
- Alertmanager: `http://localhost:9093`

## Dashboards provisionados

### openMiura Operations Overview

Panel principal para salud global, tráfico y uso del sistema.

### openMiura Channel & Tool Operations

Panel para throughput por canal, ratio de error por canal y tool calls.

### openMiura Latency & Capacity

Panel específico para p50/p95, presión de tráfico y capacidad observada.

### openMiura Security & Broker

Panel específico para autenticación, errores de broker, tool errors y health de accesos.

## Alertas incluidas

- **OpenMiuraTargetDown**
- **OpenMiuraHighErrorRate**
- **OpenMiuraHighLatencyP95**
- **OpenMiuraToolErrorsBurst**
- **OpenMiuraNoActiveSessions**
- **OpenMiuraBrokerAuthFailures**
- **OpenMiuraTokenUsageDrop**

Todas las alertas incluyen `runbook_url` apuntando a `docs/runbooks/alerts.md`.

## Canales reales de alerta

La pila soporta receptores reales desde variables de entorno:

- webhook corporativo: `OPENMIURA_ALERT_WEBHOOK_URL`
- Slack: `OPENMIURA_ALERT_SLACK_WEBHOOK_URL`, `OPENMIURA_ALERT_SLACK_CHANNEL`
- email: `OPENMIURA_ALERT_EMAIL_TO`, `OPENMIURA_ALERT_EMAIL_FROM`, `OPENMIURA_ALERT_EMAIL_SMARTHOST`

La configuración final de Alertmanager se renderiza al arranque a partir de `ops/alertmanager/render_alertmanager_config.sh`.

## Pruebas de firing de alertas

Puedes inyectar alertas sintéticas directamente en Alertmanager:

```bash
python scripts/fire_test_alerts.py --alertmanager-url http://localhost:9093
```

Payload por defecto:
- `ops/alertmanager/testdata/sample_alerts.json`

Esto permite verificar de extremo a extremo que llegan a webhook, Slack o email sin esperar a que el sistema genere la condición de firing.

## Operación recomendada

- revisar diariamente `Operations Overview`
- usar `Latency & Capacity` cuando suba la latencia
- usar `Security & Broker` cuando fallen auth, broker o tools
- conectar Alertmanager a tu canal real antes de producción
- revisar los runbooks antes de activar alertas críticas en horario no laboral
