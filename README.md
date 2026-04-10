<p align="center">
  <img src="assets/logo/openmiura-logo.png" alt="openMiura logo" width="220">
</p>

<h1 align="center">openMiura</h1>

<p align="center">
  Governed Agent Operations Platform
</p>

<p align="center">
  Deploy agents with control, approvals, auditability, and runtime governance
</p>

<p align="center">
  Local-first • Multi-tenant • Policy-driven • Auditable • Extensible
</p>

<p align="center">
  <strong>Bring your runtime. openMiura governs it.</strong>
</p>

---

## Overview

openMiura is a **governed agent operations platform** for organizations that want to run AI agents across email, terminal, Slack, browsers, CRM, ERP, and internal tools with **policy control, approvals, secrets isolation, auditability, and rollback**.

Most agent systems focus on making assistants more capable.  
openMiura focuses on making agents **deployable in real organizations**.

It adds the missing enterprise layer around agent execution:

- controlled execution of tools, workflows, and operational actions
- tenant / workspace / environment isolation
- RBAC, policy engine, approvals, and audit-first design
- release governance, promotions, rollbacks, and canary routing
- live operational surfaces for operators and reviewers
- reproducible packaging and controlled deployment workflows

---

## Why openMiura

Organizations increasingly want to use agents in real operational environments, but real deployment requires much more than a model and a chat interface.

They need to answer questions such as:

- Who can run which agent?
- Which tools may an agent use?
- Which actions require human approval?
- What secret can be used, and where?
- What happened during execution?
- Can we replay, inspect, or roll back a run?
- Can we deploy agents safely across teams and environments?

openMiura is designed to answer those questions by acting as the **control plane** around agent execution.

---

## What openMiura is

openMiura sits between:

- models
- tools
- channels
- operators
- workflows
- runtime policies
- enterprise controls

Instead of optimizing only for chat-style interaction, it focuses on **agent operations**.

That means turning agent execution into something:

- governable
- inspectable
- replayable
- auditable
- controllable
- deployable across real organizational boundaries

---

## Core capabilities

### 1. Governance and release operations

- release bundles, promotions, approvals, and rollbacks
- evaluation gates for quality, latency, cost, and policy adherence
- canary routing and release observations
- change intelligence and release summaries
- controlled rollout and rollback patterns for agent releases

### 2. Runtime and control plane

- HTTP API and admin endpoints
- broker interfaces for governed runtime access
- policy-aware tool execution
- confirmation and approval flows
- audit logging and operational traceability
- controlled routing between agents, tools, and workflows

### 3. Voice, mobile, and operator experience

- voice sessions, transcripts, and command lifecycle
- local voice asset pipeline hooks
- PWA/mobile operational mode
- operator console for runtime administration
- task visibility for operational users and reviewers

### 4. Live operations canvas

- persisted canvas documents, nodes, edges, and views
- overlays for approvals, failures, costs, traces, and policies
- comments, snapshots, compare views, and shared operational context
- visual support for replay, rollback, and postmortem workflows

### 5. Security and enterprise controls

- tenant / workspace / environment segregation
- role-based access control
- policy enforcement
- secret governance hooks
- hardened limits for voice, canvas, and HTTP surfaces
- approval boundaries for sensitive actions

### 6. Developer experience and packaging

- migrations and automated validation
- extension SDK and registry foundations
- reproducible packaging artifacts
- quickstarts, runbooks, and operational docs
- controlled project structure for extensibility and maintenance

---

## Key documents

- [Agent Control Plane overview](docs/openMiura_agent_control_plane.md)
- [24-month investor strategy roadmap](docs/ROADMAP_24M_PRODUCT_STRATEGY.md)
- [Commercial one-pager](docs/openMiura_one_pager_commercial.md)
- [Use cases](docs/use_cases.md)
- [Self-hosted Enterprise Alpha](docs/enterprise_alpha.md)
- [Enterprise Alpha release checklist](docs/alpha_release_checklist.md)

---

## High-level architecture

```text
Channels / UI / PWA / Voice / Canvas
                |
        HTTP API / Broker / Admin
                |
        Application services layer
                |
 Policies / approvals / routing / audit
                |
 Persistence / registries / artifacts
```

## Repository structure

```text
.
├── app.py
├── configs/                 # YAML configuration and runtime policy definitions
├── docs/                    # architecture, operations, quickstarts, runbooks
├── docker/                  # container entrypoints and deployment helpers
├── openmiura/
│   ├── agents/              # agent routing and agent-specific logic
│   ├── application/         # services for releases, voice, pwa, canvas, packaging, etc.
│   ├── builtin_skills/      # bundled skills and built-in capability definitions
│   ├── channels/            # channel adapters (Telegram, Slack, Discord, ...)
│   ├── core/                # config, schema, audit, memory, auth, security primitives
│   ├── endpoints/           # HTTP endpoint composition
│   ├── extensions/          # SDK, loader, registry, scaffolding
│   ├── infrastructure/      # persistence and infra support services
│   ├── interfaces/          # HTTP, broker, and admin route surfaces
│   ├── tools/               # tool implementations and execution controls
│   ├── ui/                  # browser UI / operator surface assets
│   └── workers/             # background and channel workers
├── ops/                     # observability assets
├── packaging/               # desktop/mobile packaging scaffolds
├── scripts/                 # operational and maintenance scripts
├── skills/                  # user/project-defined skills
└── tests/                   # unit and integration tests
```

## Supported deployment posture

openMiura is designed to run **local-first** or in controlled infrastructure. A common baseline is:

- FastAPI application behind a reverse proxy
- local SQLite for baseline operation or external database where appropriate
- Ollama-compatible local model endpoints by default
- separate workers for Telegram/Slack/Discord when enabled
- admin and broker endpoints protected by tokens, auth, and policy controls

## Quickstart

### 1. Create and activate a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate
```

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 2. Install dependencies

```bash
pip install -e .[dev]
```

or, if you prefer requirements:

```bash
pip install -r requirements.txt
```

### 3. Prepare configuration

Copy the example environment file and adjust only the variables you need:

```bash
cp .env.example .env
```

The default runtime configuration file is:

```text
configs/openmiura.yaml
```

### 4. Run the application

```bash
python -m openmiura run --config configs/openmiura.yaml
```

You can also run the FastAPI app directly:

```bash
uvicorn app:app --host 127.0.0.1 --port 8081 --reload
```

### 5. Optional workers

Telegram polling:

```bash
python scripts/telegram_poll_worker.py
```

Discord worker:

```bash
python scripts/discord_worker.py
```

### 6. Environment health check

```bash
python -m openmiura doctor --config configs/openmiura.yaml
```

## Validation

Typical validation flow:

```bash
python -m compileall -q app.py openmiura tests
pytest --collect-only -q
pytest -q tests/unit
```

Optional UI syntax validation:

```bash
node --check openmiura/ui/static/app.js
```

## Security model

openMiura assumes an enterprise-style control model:

- tenant/workspace/environment segregation
- approvals for sensitive operations
- release governance and promotion evidence
- audit logging for sensitive runtime actions
- policy enforcement at channel, tool, and control-plane boundaries
- secrets kept outside the repository and injected at runtime

Before running openMiura outside a local sandbox, read [SECURITY.md](SECURITY.md).

## Public repository hygiene

This public-ready bundle excludes generated caches, local runtime artifacts, embedded audio samples, and VCS metadata. Do **not** commit:

- `.env`
- real admin, broker, channel, or provider tokens
- local databases and backups
- generated voice assets
- local sandbox outputs

## Recommended docs to read next

- [Installation](docs/installation.md)
- [Deployment](docs/deployment.md)
- [Security](docs/security.md)
- [Observability](docs/observability.md)
- [Backup and restore](docs/backup_restore.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Operator quickstart](docs/quickstarts/operator.md)
- [Admin quickstart](docs/quickstarts/admin.md)
- [Developer quickstart](docs/quickstarts/developer.md)
- [Approver quickstart](docs/quickstarts/approver.md)
- [24-month product strategy roadmap](docs/ROADMAP_24M_PRODUCT_STRATEGY.md)
- [openMiura Agent Control Plane](docs/openMiura_agent_control_plane.md)

---

## Compatibility direction

openMiura is being shaped as a **governance and control layer** around agent runtimes.

That means the long-term direction is not limited to a single execution engine. The platform is intended to support governed interaction with external runtimes, tools, and execution surfaces while preserving:

- policy enforcement
- approval workflows
- audit evidence
- secret isolation
- operational visibility
- replay and rollback semantics

In practical terms, the vision is:

> Bring your runtime. openMiura governs it.


## Typical use cases

openMiura is especially relevant where agent usefulness is blocked by risk, governance, or operational control requirements.

Examples include:

- **IT / SecOps / Platform Ops**  
  Agents that inspect alerts, open incidents, propose remediation, and execute controlled playbooks only after approval.

- **Finance / Procurement / Compliance**  
  Agents that process documents, prepare reconciliations, route approvals, and maintain evidence trails.

- **Laboratories / Pharma / Regulated Industry**  
  Agents that operate SOP-driven flows, QA workflows, document control, and controlled operational tasks with strong traceability.

---

## Project status

The codebase is suitable for private collaboration and controlled deployments, and it now has a public-friendly repository structure.

Production use still requires environment-specific decisions around:

- external identity integration and secret management
- real provider credentials for voice and model services
- infrastructure, reverse proxying, backups, and observability setup
- release promotion workflow and approval ownership
- deployment topology and operational responsibility boundaries

## Contributing

Contributions are welcome, especially around:

- governance and policy features
- runtime adapters and integrations
- operational tooling
- documentation improvements
- packaging and deployment workflows
- testing, validation, and developer experience

Before contributing, make sure to:

1. read the relevant docs in `docs/`
2. run the validation steps locally
3. avoid committing secrets or generated runtime artifacts
4. keep changes aligned with the governed agent operations model


## License

Apache License 2.0. See [LICENSE](LICENSE).
