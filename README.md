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

openMiura is a **governed agent operations platform**: a control plane that sits in front of agent runtimes and operational automations to enforce **policy, approvals, evidence, auditability, and operator visibility**.

The product thesis is deliberately simple:

- **the runtime executes**
- **openMiura governs**

That makes openMiura useful when an organization wants to run agentic systems across HTTP, channels, workflows, or external runtimes, but cannot accept ungoverned execution.

## What problem it solves

Most agent demos optimize for capability. Production teams usually need answers to different questions:

- who can execute what;
- in which tenant, workspace, and environment;
- under which policy;
- with which approval chain;
- with what evidence afterward;
- and how the action can be inspected, replayed, or rolled back.

openMiura focuses on those operational questions.

## Why it is not another assistant

openMiura is **not** positioned as:

- a general-purpose chatbot;
- a thin wrapper around LLM APIs;
- a replacement identity for external runtimes such as OpenClaw.

It is the governance layer around runtime actions and agentic operations.

## The quickest serious evaluation path

For a first external evaluation, use this route:

1. install from the **stable reproducible bundle** using the [installation guide](docs/installation.md);
2. validate the install with `openmiura doctor --config configs/openmiura.yaml`;
3. run the [canonical public demo](docs/demos/canonical_demo.md);
4. inspect the [public walkthrough](docs/walkthroughs/canonical_runtime_governance_walkthrough.md).

Recommended first-start profile:

```text
ops/env/local-secure.env
```

## Canonical public demo

The recommended public demo is **Governed runtime alert policy activation**.

Run it in self-contained mode:

```bash
python scripts/run_canonical_demo.py --output demo_artifacts/canonical-demo-report.json
```

That single case demonstrates:

- a sensitive operational change request over HTTP;
- policy evaluation and approval gating;
- operator review through a canvas runtime inspector;
- execution only after human approval;
- signed release evidence and audit trail.

See these companion docs:

- [Canonical demo](docs/demos/canonical_demo.md)
- [Canonical walkthrough](docs/walkthroughs/canonical_runtime_governance_walkthrough.md)
- [Screenshot plan](docs/media/screenshot_plan.md)

## OpenClaw in this story

OpenClaw is one **governed runtime** that openMiura can supervise. It is not the product identity of openMiura and it is not the conceptual replacement for openMiura.

The public framing is:

- **OpenClaw executes runtime work**
- **openMiura governs the operation around it**

## Core capability areas

### Governed execution

- policy-aware runtime dispatch
- action gating and confirmation flows
- tenant / workspace / environment scoping
- role-aware control surfaces

### Workflows and approvals

- approval steps, decision, cancellation, and assignment flows
- gated operational actions exposed through admin and canvas inspectors
- human-in-the-loop governance for sensitive changes

### Evidence and audit

- audit-first persistence model
- evidence package generation and export flows
- release signatures and traceability surfaces
- replay-oriented operational records

### Operator visibility

- live operational canvas documents and nodes
- inspectors with contextual actions
- runtime timelines and governance-oriented views
- observable review surfaces for operators and approvers

### Integrations and runtime posture

- FastAPI HTTP application
- HTTP broker surface
- MCP server integration
- Telegram, Slack, and Discord channel adapters
- OpenClaw governance adapter
- local-first default posture with configurable infrastructure

## Installation and validation

The recommended path for external users is the **stable reproducible bundle** from the GitHub Release, not an editable developer checkout.

Validation flow:

```bash
openmiura doctor --config configs/openmiura.yaml
openmiura run --config configs/openmiura.yaml
```

Key surfaces:

- health: `http://127.0.0.1:8081/health`
- UI: `http://127.0.0.1:8081/ui`
- metrics: `http://127.0.0.1:8081/metrics`

Use the detailed guide here:

- [Installation](docs/installation.md)
- [Stable release publication policy](docs/release_publication.md)

## Public documentation map

### Start here

- [Public narrative](docs/public_narrative.md)
- [Installation](docs/installation.md)
- [Canonical demo](docs/demos/canonical_demo.md)
- [Canonical walkthrough](docs/walkthroughs/canonical_runtime_governance_walkthrough.md)
- [Stable release publication policy](docs/release_publication.md)
- [Enterprise alpha guide](docs/enterprise_alpha.md)
- [Release Candidate RC1](docs/release_candidate.md)
- [Release support matrix](docs/release_support_matrix.md)

### Public-facing media pack

- [Screenshot plan](docs/media/screenshot_plan.md)
- [Medium article outline](docs/media/medium_article_outline.md)
- [Medium article final](docs/media/medium_article_final.md)
- [Medium article publication pack](docs/media/medium_article_publication_pack.md)
- [Stable release final pack](docs/release/stable_release_final_pack.md)
- [Publication reuse note](docs/media/publication_reuse_note.md)

### Product and platform docs

- [Documentation index](docs/README.md)
- [Deployment](docs/deployment.md)
- [Production](docs/production.md)
- [Observability](docs/observability.md)
- [Security](docs/security.md)
- [Backup and restore](docs/backup_restore.md)
- [Migrations](docs/migrations.md)
- [Troubleshooting](docs/troubleshooting.md)
- [LLM providers](docs/llm_providers.md)
- [MCP broker integration](docs/mcp_broker_integration.md)
- [Extension SDK](docs/extensions_sdk.md)
- [Extension registry](docs/extensions_registry.md)

## Current status

This bundle is suitable for:

- local development;
- controlled internal evaluation;
- private collaboration;
- staged hardening for self-hosted enterprise-style deployments.

It already contains substantial implementation across governance, approvals, canvas operations, release flows, evidence handling, and runtime control. Stable external use still depends on your concrete identity, secret-management, infrastructure, and operating model choices.

## Validation

Typical local validation flow:

```bash
python -m compileall -q app.py openmiura tests
pytest -q
```

## Contributing

Contributions are especially valuable in:

- runtime adapters;
- policy and approval features;
- canvas and operator experience;
- security and evidence hardening;
- documentation and deployment workflows;
- tests and regression coverage.

Before contributing:

1. read the relevant docs in `docs/`;
2. run the validation steps locally;
3. avoid committing secrets or generated runtime artifacts;
4. keep changes aligned with the governed-agent-operations model.

## License

Apache License 2.0. See [LICENSE](LICENSE).
