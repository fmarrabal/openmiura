# Health and monitoring

> Status: `beta`. openMiura exposes a liveness probe and Prometheus metrics.
> This page covers wiring them into an orchestrator and a monitoring stack.

## Health endpoint

`GET /health` returns `200 OK` when the process is up. Use it for container /
orchestrator liveness and readiness probes.

```bash
curl -fsS http://localhost:8081/health
```

The container image already declares a `HEALTHCHECK` against this endpoint, so
`docker inspect --format '{{.State.Health.Status}}' openmiura` reports health.

Kubernetes example:

```yaml
livenessProbe:
  httpGet: { path: /health, port: 8081 }
  initialDelaySeconds: 20
  periodSeconds: 30
readinessProbe:
  httpGet: { path: /health, port: 8081 }
  periodSeconds: 10
```

## Metrics

`GET /metrics` exposes Prometheus metrics (via `prometheus-client`). Point a
Prometheus scrape job at it:

```yaml
scrape_configs:
  - job_name: openmiura
    metrics_path: /metrics
    static_configs:
      - targets: ["openmiura:8081"]
```

Metrics cover request/latency counters and governance activity. Treat the
`/metrics` endpoint as internal — expose it only to your monitoring network,
not the public internet.

## Operational checks

`openmiura doctor` runs local configuration and dependency checks and prints a
report (add `--json` for machine output):

```bash
openmiura doctor --config configs/openmiura.yaml
openmiura doctor --json
```

Verify the tamper-evident audit hash-chain against the live database on a
schedule (it recomputes every row hash and matches the per-scope head):

```bash
openmiura db verify-chain            # exit 0 = intact, 1 = tampered
openmiura db verify-chain --json
```

For evidence packs, `openmiura verify pack.zip` re-checks a pack offline
(signature, manifest, and — when present — the RFC 3161 timestamp).

## What to alert on

- `/health` non-200 or the container `HEALTHCHECK` unhealthy → process down.
- `openmiura db verify-chain` exit `1` → the audit trail was tampered with;
  investigate immediately.
- Signing configured as the dev seed in production (an evidence pack verifies
  as **non-authoritative**) → a real signing key is missing; see
  [Secrets and keys](secrets_and_keys.md).

See also: [Observability](observability.md),
[Container image](container_image.md).
