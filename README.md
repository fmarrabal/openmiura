<p align="center">
  <img src="assets/logo/openmiura-logo.png" alt="openMiura logo" width="220">
</p>

<h1 align="center">openMiura</h1>

<p align="center">
  Open governance plane for LLM agents, with a focus on auditable, regulated environments.
</p>

<p align="center">
  <strong>Status:</strong> experimental
</p>

---

## What it is

openMiura is an open-source governance layer that sits in front of
LLM-driven agent runtimes. It evaluates each action against policy,
gates sensitive operations behind human approvals, records every step
in an append-only audit trail, and emits tamper-evident evidence
packs. The target use case is environments where the audit trail is
itself part of the deliverable — biomedical research, regulated
laboratories, scientific computing under quality systems.

The core primitives are:

- **policy engine** — declarative rules over actions and contexts;
- **approval gates** — human-in-the-loop with signer, meaning, and timestamp;
- **evidence packs** — signed exports linking decisions to underlying records;
- **scope isolation** — `tenant / workspace / environment` partitioning.

## What it is not

- Not a chatbot or a thin wrapper around a model API.
- Not a replacement for an agent runtime; it supervises one.
- Not a certified compliance product. It maps to regulatory controls
  (21 CFR Part 11, EU GMP Annex 11, GAMP 5, ALCOA+); certification
  remains the responsibility of the operating organization.
- Not stable. Most components are `experimental`; a few are `beta`.
  None are `stable` yet.

## What works today

Verifiable on a local clone:

- A canonical end-to-end demo runs locally and produces a real audit
  trail with policy evaluation, human approval, signed release
  evidence, and a reviewable canvas inspector:
  ```bash
  python scripts/run_canonical_demo.py --output /tmp/demo.json
  ```
  Returns `success=True`.
- The unit test suite passes:
  ```bash
  pytest -q --tb=no -p no:cacheprovider tests/unit
  ```
- A FastAPI HTTP application exposing health, UI, and metrics surfaces.
- Adapters for Telegram, Slack, and Discord channels.
- An MCP integration surface for tool brokering.
- An `openmiura doctor` CLI command that validates a configuration.

Internal patterns (god-object persistence layer, large auto-generated
modules) are being refactored. See the master plan for the schedule.

## Quick start

```bash
git clone https://github.com/fmarrabal/openmiura.git
cd openmiura
pip install -e .[dev]
openmiura doctor --config configs/openmiura.yaml
python scripts/run_canonical_demo.py --output /tmp/demo.json
```

Requires Python ≥ 3.10.

## Architecture

```
        +------------------+
        |  agent runtime   |   any LLM-driven runtime
        +---------+--------+
                  |
                  v
        +---------+--------+        +------------------+
        | openMiura plane  +------->|  evidence pack   |
        |  policy / gates  |        |  (signed export) |
        |  audit / scope   |        +------------------+
        +---------+--------+
                  |
                  v
        +------------------+
        | persistence + UI |
        +------------------+
```

The control plane intercepts agent actions, applies policy, requests
approvals when required, records every step in an append-only audit
trail, and emits evidence packs that link decisions to underlying
records. Scope (`tenant / workspace / environment`) is enforced at the
persistence layer so multi-context deployments stay isolated.

## Roadmap

The 4-week working plan and the long-term direction are tracked in
`docs/STRATEGY.md` (to be added in a later phase of the master plan).

## License

Apache License 2.0. See [LICENSE](LICENSE).

## Disclosure

This repository has been developed with LLM assistance under
continuous human review. See [AGENTS.md](AGENTS.md).
