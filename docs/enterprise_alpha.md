# Self-hosted Enterprise Alpha

This guide documents the first self-hosted Enterprise Alpha of openMiura. It is written for operators who want to install, validate and distribute an internal alpha with enough governance to demonstrate the product safely.

The product thesis stays the same in this alpha:

> Bring your runtime. openMiura governs it.

This means the alpha is oriented to governed execution, approvals, auditability, scoped operations and OpenClaw runtime compatibility. It is **not** positioned as a general-purpose personal assistant.

## 1. Scope of this alpha

This alpha is intended for:

- local laboratory deployments
- internal team pilots
- customer or investor demos in controlled environments
- early self-hosted evaluations of the governed platform model

This alpha is **not yet** presented as a fully hardened general-availability release.

## 2. What is included

The current alpha installation includes the foundations implemented in the roadmap up to the self-hosted alpha package:

- tenant / workspace / environment isolation
- RBAC and policy enforcement
- approvals and audit foundations
- Secret Broker v1
- OpenClaw adapter v1
- operations canvas with operator actions
- reproducible packaging and release manifests

## 3. Supported deployment shapes

### Option A — Single-node alpha

Use this when you want the fastest reproducible setup for internal validation.

Typical characteristics:

- one Docker host or one VM
- SQLite backend
- local or nearby Ollama endpoint
- optional Prometheus / Grafana / Alertmanager profile
- one or a few operators

### Option B — Alpha with observability

Use this when you want better operational visibility during demos or pilot runs.

Typical characteristics:

- same base deployment as Option A
- `observability` profile enabled in Compose
- dashboard and alerting validation included in acceptance checklist

## 4. Requirements

Minimum software requirements:

- Python 3.10, 3.11 or 3.12
- `pip`
- Git
- Docker Engine and Docker Compose plugin for containerized install

Recommended for the default local-first stack:

- Ollama reachable from the openMiura container or host
- enough disk space for `data/`, package artifacts and logs

Recommended operator prerequisites:

- ability to manage `.env` values safely
- ability to rotate admin/bootstrap secrets before wider sharing
- ability to run basic health and packaging validation commands

## 5. Files you should review before starting

Review these files before the first alpha deployment:

- `.env.example`
- `configs/openmiura.yaml`
- `configs/agents.yaml`
- `configs/policies.yaml`
- `docker-compose.yml`
- `docs/installation.md`
- `docs/production.md`
- `docs/ci_cd.md`

For release artifact validation, also review:

- `MANIFEST.in`
- `scripts/reproducible_package.py`
- `scripts/build_release_artifacts.py`
- `scripts/verify_release_artifacts.py`

## 6. Recommended installation path

### 6.1 Clone and prepare

```bash
git clone <your-openmiura-repository>
cd openMiura
cp .env.example .env
```

Edit `.env` and set at least:

- `OPENMIURA_UI_ADMIN_USERNAME`
- `OPENMIURA_UI_ADMIN_PASSWORD`
- `OPENMIURA_ADMIN_TOKEN`
- `OPENMIURA_LLM_PROVIDER`
- `OPENMIURA_LLM_BASE_URL`
- `OPENMIURA_LLM_MODEL`
- `OPENMIURA_DB_PATH`

If you will use secrets features in the alpha, also review:

- `OPENMIURA_VAULT_ENABLED`
- `OPENMIURA_VAULT_PASSPHRASE`
- `OPENMIURA_SECRETS_ENABLED`

### 6.2 Start the alpha with Docker Compose

Base alpha:

```bash
docker compose up --build -d
```

Alpha with observability:

```bash
docker compose --profile observability up --build -d
```

Optional standalone MCP service:

```bash
docker compose --profile mcp-standalone up --build -d
```

### 6.3 Verify the service is alive

Core checks:

```bash
curl http://localhost:8081/health
curl http://localhost:8081/metrics
```

UI:

- `http://localhost:8081/ui`

Broker/authenticated surfaces should only be exposed behind appropriate auth and reverse-proxy controls.

## 7. First-run validation

Run these checks after the first startup.

### 7.1 Doctor

```bash
openmiura doctor --config configs/openmiura.yaml
```

Expected result:

- configuration loads cleanly
- storage backend is detected
- sandbox directory is available
- provider wiring looks correct
- broker and optional MCP are reported consistently

### 7.2 Packaging/release validation

If you are validating a distributable alpha artifact and not just a source checkout, run:

```bash
python scripts/reproducible_package.py --target desktop --label "Enterprise Alpha" --version alpha --output-dir dist
python scripts/build_release_artifacts.py --dist-dir dist --tag v-alpha --target desktop --strict
python scripts/verify_release_artifacts.py --dist-dir dist
```

Expected result:

- reproducible package generated
- `SHA256SUMS.txt` created
- `RELEASE_MANIFEST.json` created
- verification succeeds without missing or changed artifacts

### 7.3 Functional smoke test

Perform a minimal governed-flow validation:

1. log in to `/ui`
2. execute a basic chat request
3. run a safe tool such as `time_now`
4. inspect audit or operator view
5. verify memory can be searched
6. verify approvals appear when expected for sensitive flows
7. if OpenClaw runtime is configured, validate a governed dispatch path

## 8. Recommended reverse-proxy posture

For any non-localhost use, terminate TLS in a reverse proxy such as Nginx or Caddy.

Forward at least:

- `Host`
- `X-Forwarded-Proto`
- `X-Forwarded-For`
- `X-Request-ID`

For SSE/live surfaces, keep proxy buffering disabled.

Do not expose these surfaces casually to the public internet:

- `/broker/auth/*`
- `/broker/admin/*`
- `/broker/tools/call`
- `/broker/terminal/stream`
- `/metrics`
- Grafana / Prometheus / Alertmanager UIs

## 9. Operational guidance for the alpha

### Identity and scope

Use tenant / workspace / environment fields intentionally during pilots. The alpha is already organized around scoped governance, so demos and evaluations should reflect that model.

### Roles

Start with a small role model:

- `user`
- `operator`
- `admin`

Do not grant operator-like permissions broadly just because the installation is internal.

### Secrets

Treat the Secret Broker as governance infrastructure, not as a convenience feature. Do not embed long-lived secrets directly in prompts or notebooks. Prefer secret references and keep vault/passphrase handling out of version control.

### OpenClaw runtime usage

Use OpenClaw as a governed runtime target. Register runtimes intentionally, keep allowed agents narrow and validate dispatch with audit and canvas visibility.

## 10. Known risks and residual limitations

The alpha is installable and demonstrable, but there are still residual risks you should state explicitly before distribution.

### Known risks

- this is an alpha, so interfaces and operational contracts may still evolve
- default deployments may still use SQLite, which is good for pilots but not the final answer for heavier multi-user production
- some enterprise-grade controls are present in v1 form and should be treated as governed foundations, not final maturity
- external channel integrations may require additional environment-specific hardening before wider exposure
- runtime health, callbacks and dispatch governance around OpenClaw are usable but still early-stage compared with a future hardened release train

### Limitations

- no claim of GA-level hardening or support process yet
- no promise that every workflow or connector is production-certified
- release packaging is reproducible and checkable, but you should still run local validation on the exact artifact you plan to distribute
- distribution should stay controlled: internal pilot, partner preview or guided customer evaluation

## 11. Go / no-go review before distribution

Use the checklist document together with this guide:

- [Enterprise Alpha release checklist](alpha_release_checklist.md)

Minimum go decision for distribution:

- workflows pass
- release artifacts verify cleanly
- bootstrap login works
- operator visibility works
- one governed workflow and one governed runtime dispatch succeed
- known risks have been communicated to the receiving party

## 12. Suggested distribution package

For each alpha handoff, include at least:

- source tree or approved release bundle
- `SHA256SUMS.txt`
- `RELEASE_MANIFEST.json`
- this installation guide
- release checklist
- a short note on known limitations and pilot support expectations

## 13. Critical review of the current result

The current self-hosted alpha is credible for controlled pilots because the platform foundations, packaging checks and operational canvas are already present. The remaining gap is not whether it can be installed, but how carefully it is introduced.

That means the most important discipline at this stage is:

- keep distribution narrow
- validate artifacts before every handoff
- treat roles, secrets and OpenClaw runtimes as governed surfaces from day one
- document limitations honestly

If you follow that discipline, this alpha is strong enough to support internal validation, demos and early design-partner conversations.


## 11. RC1 companion material

For the formal frozen candidate handoff, also include:

- `RELEASE_NOTES_RC1.md`
- `docs/release_candidate.md`
- `docs/release_support_matrix.md`
- `docs/quickstarts/release_candidate.md`
