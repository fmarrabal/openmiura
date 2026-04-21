<p align="center">
  <img src="assets/logo/openmiura-logo.png" alt="openMiura logo" width="220">
</p>

<h1 align="center">openMiura</h1>

<p align="center">
  Governed Agent Operations Platform
</p>

<p align="center">
  Bring your runtime. openMiura governs it.
</p>

<p align="center">
  Local-first • Multi-tenant • Policy-driven • Auditable • Extensible
</p>

---

## What openMiura is

openMiura is a **governed agent operations platform** for organizations that want to run AI agents and operational automations with **approvals, policy control, auditability, release governance, replayability, and environment isolation**.

The platform is designed around a simple idea:

- **the runtime executes**
- **openMiura governs**

That makes it useful when an organization wants to work with agents across chat, HTTP, operational workflows, or external runtimes, but cannot accept ungoverned execution.

## What this bundle currently contains

This repository already includes implemented surfaces for:

- **admin and control-plane APIs** over FastAPI
- **multi-tenant scoping** with tenant, workspace, and environment boundaries
- **workflow and approval services**
- **release, promotion, rollback, and evidence flows**
- **live operational canvas** documents, nodes, inspectors, views, overlays, and actions
- **OpenClaw governance adapters** for governed runtime dispatch
- **evidence export, escrow, verification, and packaging hardening**
- **voice, PWA, operator, replay, session, and cost services**
- **HTTP broker and MCP integration surfaces**
- **channel adapters** for Telegram, Slack, and Discord
- **extension SDK and private registry foundations**

In practice, this means openMiura is not just a chat wrapper. It is a control plane around runtime actions, policies, approvals, operational review, and governed rollout.

## Why it exists

Most agent demos optimize for capability. Real deployment requires something else:

- who can execute what
- in which environment
- under which policy
- with which secret
- with which approval chain
- with what audit evidence afterward
- and how the action can be inspected, replayed, or rolled back

openMiura focuses on those operational questions.

## Core capability areas

### 1. Governed execution

- policy-aware runtime dispatch
- action gating and confirmation flows
- role-aware control surfaces
- environment scoping for dev, stage, and prod-like operation

### 2. Workflows and approvals

- workflow creation and execution tracking
- approval steps, assignment, claim, decision, and cancellation flows
- operational actions exposed through admin and canvas inspectors

### 3. Release governance

- governed promotions and release flows
- approval-gated releases
- rollback and supersedence support
- release evidence and export artifacts
- rollout intelligence for controlled change management

### 4. Live operations canvas

- persisted canvas documents and nodes
- operational views and suggested views
- node inspectors with contextual actions
- replay, comparison, routing, and governance-oriented inspection
- collaboration-oriented operational visualization

### 5. Security and evidence

- tenant / workspace / environment segregation
- audit-first persistence model
- evidence package generation and escrow flows
- verification-on-read and tamper-detection paths
- packaging and operational hardening controls

### 6. Integrations and runtime posture

- FastAPI HTTP application
- HTTP broker surface
- MCP server integration
- Telegram, Slack, and Discord channel adapters
- OpenClaw runtime governance adapter
- local-first default posture with configurable infrastructure

## High-level architecture

```text
Channels / UI / Voice / PWA / Canvas / Broker / MCP
                         |
                FastAPI control plane
                         |
      Governance services, workflows, approvals, releases,
         evidence, operator actions, replay, packaging
                         |
         Policies / audit / tenancy / secrets / routing
                         |
          Persistence / registries / artifacts / runtimes
```

## Repository structure

```text
.
├── app.py
├── configs/                 # YAML configuration
├── docker/                  # container helpers
├── docs/                    # product, architecture, ops, and runbooks
├── openmiura/
│   ├── application/         # control-plane services
│   ├── channels/            # Telegram, Slack, Discord, HTTP broker, MCP
│   ├── core/                # config, auth, audit, memory, migrations
│   ├── extensions/          # SDK, scaffolding, registry helpers
│   ├── infrastructure/      # persistence and infra adapters
│   ├── interfaces/          # HTTP app and route composition
│   ├── tools/               # governed tool execution surfaces
│   ├── ui/                  # UI assets
│   └── workers/             # background workers
├── ops/                     # observability assets
├── packaging/               # packaging scaffolds
├── scripts/                 # operational scripts
├── skills/                  # skill manifests
└── tests/                   # regression and integration coverage
```

## Deployment posture

openMiura is built to run **local-first** or inside controlled infrastructure.

Typical baseline:

- FastAPI application
- SQLite by default, with PostgreSQL support available
- Ollama-compatible LLM endpoint by default
- channel workers enabled only when needed
- admin and broker surfaces protected by tokens and policy controls

## Quickstart

### 1. Create an environment

```bash
python -m venv .venv
source .venv/bin/activate
```

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 2. Install

```bash
pip install -e .[dev]
```

Alternative:

```bash
pip install -r requirements.txt
```

### 3. Prepare configuration

Fastest path for local development:

```bash
cp ops/env/secure-default.env .env
```

Canonical variable catalog:

```text
.env.example
```

Default config file:

```text
configs/openmiura.yaml
```

Configuration profiles and precedence rules:

```text
docs/configuration_profiles.md
```

### 4. Run the application

```bash
python -m openmiura run --config configs/openmiura.yaml
```

Direct ASGI run:

```bash
uvicorn app:app --host 127.0.0.1 --port 8081 --reload
```

### 5. Health and diagnostics

```bash
python -m openmiura doctor --config configs/openmiura.yaml
```

### 6. Optional workers

Telegram polling:

```bash
python scripts/telegram_poll_worker.py
```

Discord worker:

```bash
python scripts/discord_worker.py
```

## CLI surfaces included

The current CLI already exposes groups for:

- `openmiura run`
- `openmiura doctor`
- `openmiura db ...`
- `openmiura memory ...`
- `openmiura mcp ...`
- `openmiura create ...`
- `openmiura sdk ...`
- `openmiura registry ...`

## Validation

Typical local validation flow:

```bash
python -m compileall -q app.py openmiura tests
pytest -q
```

## Key documentation

### Product and positioning

- [Agent Control Plane overview](docs/openMiura_agent_control_plane.md)
- [Commercial one-pager](docs/openMiura_one_pager_commercial.md)
- [Use cases](docs/use_cases.md)
- [24-month product strategy roadmap](docs/ROADMAP_24M_PRODUCT_STRATEGY.md)

### Setup and operations

- [Installation](docs/installation.md)
- [Deployment](docs/deployment.md)
- [Production](docs/production.md)
- [Observability](docs/observability.md)
- [Security](docs/security.md)
- [Backup and restore](docs/backup_restore.md)
- [Migrations](docs/migrations.md)
- [Troubleshooting](docs/troubleshooting.md)

### Integrations and platform docs

- [LLM providers](docs/llm_providers.md)
- [MCP](docs/mcp.md)
- [MCP broker integration](docs/mcp_broker_integration.md)
- [Extension SDK](docs/extensions_sdk.md)
- [Extension registry](docs/extensions_registry.md)

### Quickstarts and operational docs

- [Operator quickstart](docs/quickstarts/operator.md)
- [Admin quickstart](docs/quickstarts/admin.md)
- [Developer quickstart](docs/quickstarts/developer.md)
- [Approver quickstart](docs/quickstarts/approver.md)
- [Alert runbook](docs/runbooks/alerts.md)

## Current status

This bundle is suitable for:

- local development
- controlled internal evaluation
- private collaboration
- staged hardening for self-hosted enterprise-style deployments

It already contains substantial implementation across governance, canvas operations, release flows, evidence handling, and runtime control. Production rollout still depends on your concrete identity, secret-management, infrastructure, and operating model choices.

## Public repository hygiene

Do not commit:

- real credentials or tokens
- local databases and backups
- generated voice assets
- temporary patch scripts or debug dumps
- local sandbox outputs and generated escrow artifacts

## Contributing

Contributions are especially valuable in:

- runtime adapters
- policy and approval features
- canvas and operator experience
- security and evidence hardening
- documentation and deployment workflows
- tests and regression coverage

Before contributing:

1. read the relevant docs in `docs/`
2. run the validation steps locally
3. avoid committing secrets or generated runtime artifacts
4. keep changes aligned with the governed-agent-operations model


## Documentation

Start here:

- [Documentation index](docs/README.md)
- [Installation guide](docs/installation.md)
- [Production guide](docs/production.md)
- [Enterprise alpha guide](docs/enterprise_alpha.md)
- [Alpha release checklist](docs/alpha_release_checklist.md)
- [Release Candidate RC1](docs/release_candidate.md)
- [Release support matrix](docs/release_support_matrix.md)
- [RC1 quickstart](docs/quickstarts/release_candidate.md)
- [RC1 release notes](RELEASE_NOTES_RC1.md)

## License

Apache License 2.0. See [LICENSE](LICENSE).
