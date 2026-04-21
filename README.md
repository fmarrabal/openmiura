<p align="center">
  <img src="assets/logo/openmiura-logo.png" alt="openMiura logo" width="220">
</p>

<h1 align="center">openMiura</h1>

<p align="center">
  <strong>Governed Agent Operations Platform</strong>
</p>

<p align="center">
  Bring your runtime. openMiura governs it.
</p>

<p align="center">
  Local-first • Multi-tenant • Policy-driven • Auditable • Extensible
</p>

---

## openMiura in one sentence

openMiura is a **governed agent operations platform** for organizations that need AI agents, automations, and runtime actions to operate under **policy, approvals, audit, evidence, environment isolation, and release control**.

---

## Why openMiura exists

Most agent products optimize for capability.

Real organizations also need to answer questions like:

- Who is allowed to execute this action?
- In which tenant, workspace, and environment?
- Under which policy?
- With which approval chain?
- With which secret or credential posture?
- What evidence is generated afterward?
- Can the action be inspected, replayed, rolled back, or promoted safely?

openMiura focuses on those operational questions.

Its core operating model is simple:

- **the runtime executes**
- **openMiura governs**

That makes openMiura useful when the runtime may be local, remote, external, channel-driven, workflow-driven, or specialized, but execution still needs to remain governed.

---

## What openMiura is

openMiura is **not** just a chatbot wrapper and **not** another generic assistant shell.

It is a **control plane** around runtime execution, approvals, policies, operator review, evidence, replay, packaging, and governed rollout.

It is designed for teams that want to run:

- AI agents
- runtime-backed tools
- operator actions
- workflow steps
- release and promotion flows
- channel-triggered automations
- governed interactions with external runtimes such as OpenClaw

without accepting ungoverned execution.

---

## Current release status

The project currently includes **v1.0.0-rc1**, published as the first release candidate for the current governed control-plane baseline.

RC1 closes the final hygiene, packaging, and release-readiness work required for GitHub publication, including:

- release candidate freeze and quality gate workflow
- reproducible packaging outputs and manifest/checksum verification
- Windows-safe release artifact generation
- release documentation, checklists, and support matrix alignment
- final UI/admin regression coverage for config center and tiny runtime surfaces
- stabilized GitHub workflows and repository publication readiness

See:

- [Release Candidate RC1](docs/release_candidate.md)
- [RC1 quickstart](docs/quickstarts/release_candidate.md)
- [RC1 release notes](RELEASE_NOTES_RC1.md)
- [Release support matrix](docs/release_support_matrix.md)
- [Release quality gate](docs/release_quality_gate.md)

---

## What the repository already contains

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
- **extension SDK and registry foundations**

In practical terms, openMiura already contains meaningful implementation across governance, operator surfaces, release flows, evidence handling, and runtime control.

---

## Core capability areas

### 1. Governed execution

- policy-aware runtime dispatch
- action gating and confirmation flows
- role-aware control surfaces
- tenant / workspace / environment scoping
- local-first operation with governed runtime integration

### 2. Workflows and approvals

- workflow creation and execution tracking
- approval creation, claim, decision, and cancellation flows
- operator-facing and admin-facing approval surfaces
- governed progression of sensitive actions

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

---

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

---

## Product posture

openMiura is designed with these priorities:

- **governance before convenience**
- **operational control before demo polish**
- **local-first by default**
- **extensibility without losing control-plane authority**
- **evidence and audit as first-class concerns**
- **multi-tenant operation as a real design constraint**
- **runtime compatibility instead of runtime lock-in**

This is why the project is positioned as a **Governed Agent Operations Platform**.

---

## Repository structure

```text
.
├── app.py
├── assets/                  # branding assets
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
├── ops/
│   ├── env/                 # environment profiles and deployment defaults
│   └── quality_gate/        # release quality-gate inputs
├── packaging/               # packaging scaffolds
├── reports/                 # generated reports (when produced locally)
├── scripts/                 # operational and release scripts
├── skills/                  # skill manifests
└── tests/                   # regression and integration coverage
```

---

## Deployment posture

openMiura is built to run **local-first** or inside controlled infrastructure.

Typical baseline:

- FastAPI application
- SQLite by default, with PostgreSQL support available
- Ollama-compatible LLM endpoint by default
- channel workers enabled only when needed
- admin and broker surfaces protected by tokens and policy controls
- release and artifact flows validated through reproducible packaging scripts

---

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

---

## Release and packaging workflow

A typical local RC / release validation flow is:

```bash
python -m pytest -q
python scripts/build_release_artifacts.py --dist-dir dist --tag v-ci --target desktop --strict
python scripts/verify_release_artifacts.py --dist-dir dist
python scripts/run_release_quality_gate.py --include-extended --output-dir reports/quality_gate
```

These flows generate and validate:

- wheel and sdist
- reproducible desktop bundle
- release manifest
- SHA256 checksums
- quality-gate reports

Related docs:

- [Release quality gate](docs/release_quality_gate.md)
- [Release candidate closure](docs/release_candidate_closure.md)
- [GitHub PR / merge / publish checklist](docs/github_pr_merge_publish_checklist.md)
- [Release support matrix](docs/release_support_matrix.md)

---

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

---

## Validation

Typical local validation flow:

```bash
python -m compileall -q app.py openmiura tests
pytest -q
```

---

## Documentation

Start here:

- [Documentation index](docs/README.md)
- [Installation guide](docs/installation.md)
- [Deployment guide](docs/deployment.md)
- [Production guide](docs/production.md)
- [Enterprise alpha guide](docs/enterprise_alpha.md)
- [Alpha release checklist](docs/alpha_release_checklist.md)
- [Release Candidate RC1](docs/release_candidate.md)
- [Release support matrix](docs/release_support_matrix.md)
- [Troubleshooting](docs/troubleshooting.md)

### Product and positioning

- [Agent Control Plane overview](docs/openMiura_agent_control_plane.md)
- [Commercial one-pager](docs/openMiura_one_pager_commercial.md)
- [Use cases](docs/use_cases.md)
- [24-month product strategy roadmap](docs/ROADMAP_24M_PRODUCT_STRATEGY.md)

### Setup and operations

- [Observability](docs/observability.md)
- [Security](docs/security.md)
- [Backup and restore](docs/backup_restore.md)
- [Migrations](docs/migrations.md)
- [Production](docs/production.md)

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
- [RC1 quickstart](docs/quickstarts/release_candidate.md)
- [Alert runbook](docs/runbooks/alerts.md)

## Current status

This repository is suitable for:

- local development
- controlled internal evaluation
- private collaboration
- staged hardening for self-hosted enterprise-style deployments
- release-candidate level packaging and validation

It already contains substantial implementation across governance, canvas operations, release flows, evidence handling, runtime control, and release engineering.

Stable production rollout still depends on your concrete choices for:

- identity and access management
- secret management
- infrastructure topology
- artifact storage and escrow posture
- operational ownership model
- deployment and upgrade policy

---

## Who openMiura is for

openMiura is especially relevant for teams that need:

- AI agents under operator control
- governed execution across environments
- auditable automation
- approval-backed sensitive actions
- reproducible release and packaging discipline
- compatibility with external runtimes without giving up control-plane governance

It is a strong fit for internal platforms, innovation teams, applied AI teams, and self-hosted enterprise-style environments where governance matters as much as capability.

---

## Public repository hygiene

Do not commit:

- real credentials or tokens
- local databases and backups
- generated voice assets
- temporary patch scripts or debug dumps
- local sandbox outputs and generated escrow artifacts

Use environment variables, `.env` templates, and governed secret-management paths instead.

---

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

---

## License

Apache License 2.0. See [LICENSE](LICENSE).
