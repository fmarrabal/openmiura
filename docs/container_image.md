# Running the container image

> Status: `experimental`. The container image is a convenience for evaluation
> and self-hosting; you own the runtime, the data, and the signing keys.

openMiura ships a container image on the GitHub Container Registry (GHCR),
built from the repository [`Dockerfile`](../Dockerfile) by the
`.github/workflows/container.yml` workflow.

```bash
docker pull ghcr.io/fmarrabal/openmiura:latest
```

Tags: `latest` (most recent stable release), `X.Y.Z` and `X.Y` (a specific
release), and `sha-<commit>` (an exact build). Pin to `X.Y.Z` in production.

## Run

```bash
docker run --rm \
  -p 8081:8081 \
  -v openmiura-data:/app/data \
  ghcr.io/fmarrabal/openmiura:latest
```

The container starts `openmiura run` via
[`docker/entrypoint.sh`](../docker/entrypoint.sh) and serves on port `8081`.
Open `http://localhost:8081/ui/v2` for the admin UI and
`http://localhost:8081/health` for the health probe.

## Persist your data

Everything mutable lives under `/app/data` (created and owned by the non-root
`openmiura` user): the SQLite audit database (`data/audit.db`), the tool
sandbox (`data/sandbox`), and backups (`data/backups`). **Mount a volume there**
— without it, the audit trail and evidence are lost when the container is
removed.

```bash
docker volume create openmiura-data
docker run -d --name openmiura \
  -p 8081:8081 \
  -v openmiura-data:/app/data \
  -e OPENMIURA_ADMIN_TOKEN=... \
  ghcr.io/fmarrabal/openmiura:latest
```

## Configuration

The entrypoint reads these environment variables (defaults in parentheses):

| Variable | Purpose |
|---|---|
| `OPENMIURA_CONFIG` (`configs/openmiura.yaml`) | Path to the YAML config |
| `OPENMIURA_SERVER_HOST` (`0.0.0.0`) / `OPENMIURA_SERVER_PORT` (`8081`) | Bind address |
| `OPENMIURA_DB_PATH` (`data/audit.db`) | SQLite database path (keep it under the mounted volume) |
| `OPENMIURA_SANDBOX_DIR` (`data/sandbox`) | Tool sandbox directory |
| `OPENMIURA_LOG_LEVEL` (`info`) | Uvicorn log level |
| `OPENMIURA_WITH_WORKERS` (`false`) | Start inline workers |

Secrets (admin token, evidence signing key, TOTP KEK, vault passphrase) are
covered in [Secrets and keys](secrets_and_keys.md). To supply your own full
config, mount it and point `OPENMIURA_CONFIG` at it:

```bash
docker run --rm -p 8081:8081 \
  -v "$PWD/my-config.yaml:/app/configs/openmiura.yaml:ro" \
  -v openmiura-data:/app/data \
  ghcr.io/fmarrabal/openmiura:latest
```

## Health and lifecycle

The image declares a `HEALTHCHECK` that polls `/health`; `docker inspect`
reports the container health. To run a one-off CLI command in the image
(e.g. verify an evidence pack) instead of the server, override the command:

```bash
docker run --rm -v openmiura-data:/app/data \
  ghcr.io/fmarrabal/openmiura:latest openmiura doctor
```

See also: [Health and monitoring](health_and_monitoring.md),
[Upgrades](upgrades.md), [Backup and restore](backup_restore.md).
