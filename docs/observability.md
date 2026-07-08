# Operational observability

openMiura exposes Prometheus metrics at `GET /metrics` and ships an optional
observability stack ready to use with Docker Compose:

- Prometheus for scraping and rules
- Alertmanager for alert routing
- Grafana for operational dashboards

## Quick start

```bash
cp .env.example .env
docker compose --profile observability up --build
```

## Services

- App: `http://localhost:8081`
- Grafana: `http://localhost:3000`
- Prometheus: `http://localhost:9090`
- Alertmanager: `http://localhost:9093`

## Provisioned dashboards

### openMiura Operations Overview

Main panel for overall health, traffic, and system usage.

### openMiura Channel & Tool Operations

Panel for per-channel throughput, per-channel error rate, and tool calls.

### openMiura Latency & Capacity

Panel dedicated to p50/p95, traffic pressure, and observed capacity.

### openMiura Security & Broker

Panel dedicated to authentication, broker errors, tool errors, and access
health.

## Included alerts

- **OpenMiuraTargetDown**
- **OpenMiuraHighErrorRate**
- **OpenMiuraHighLatencyP95**
- **OpenMiuraToolErrorsBurst**
- **OpenMiuraNoActiveSessions**
- **OpenMiuraBrokerAuthFailures**
- **OpenMiuraTokenUsageDrop**

All alerts include a `runbook_url` pointing to `docs/runbooks/alerts.md`.

## Real alert channels

The stack supports real receivers from environment variables:

- corporate webhook: `OPENMIURA_ALERT_WEBHOOK_URL`
- Slack: `OPENMIURA_ALERT_SLACK_WEBHOOK_URL`, `OPENMIURA_ALERT_SLACK_CHANNEL`
- email: `OPENMIURA_ALERT_EMAIL_TO`, `OPENMIURA_ALERT_EMAIL_FROM`, `OPENMIURA_ALERT_EMAIL_SMARTHOST`

The final Alertmanager configuration is rendered at startup from
`ops/alertmanager/render_alertmanager_config.sh`.

## Alert-firing tests

You can inject synthetic alerts directly into Alertmanager:

```bash
python scripts/fire_test_alerts.py --alertmanager-url http://localhost:9093
```

Default payload:
- `ops/alertmanager/testdata/sample_alerts.json`

This lets you verify end to end that alerts reach the webhook, Slack, or email
without waiting for the system to produce the firing condition.

## Recommended operation

- review `Operations Overview` daily
- use `Latency & Capacity` when latency rises
- use `Security & Broker` when auth, broker, or tools fail
- connect Alertmanager to your real channel before production
- review the runbooks before enabling critical alerts outside working hours
