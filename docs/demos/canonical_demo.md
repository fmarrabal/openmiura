# Canonical demo · governed runtime alert policy activation

## Two-minute explanation

This is the **single recommended public demo** for openMiura.

A sensitive runtime governance request arrives over HTTP. openMiura evaluates policy, blocks the change in `pending_approval`, exposes the decision to an operator through a canvas runtime inspector, waits for human approval, activates the version only after approval, and leaves signed release evidence plus audit records behind.

That is the public thesis in action:

- the runtime executes;
- openMiura governs.

## Why this is the canonical public demo

This case is the best public demo because it is:

- understandable in under two minutes;
- local and reproducible;
- independent of fragile external infrastructure;
- aligned with runtime governance rather than chat UX;
- rich enough to show policy, approval, operator visibility, evidence, and audit.

## Demo name

**Governed runtime alert policy activation**

## Objective

Apply a sensitive quiet-hours governance policy to a governed runtime. The change must not become active immediately. It must enter a pending state, require human approval, become visible through an operator surface, and only then activate as a signed governance release.

## Actors

- **Requester**: `platform-admin`
- **Approver**: `security-admin`
- **Governed runtime**: simulated OpenClaw-compatible runtime
- **Operator surface**: canvas runtime inspector

## Preconditions

- the Sprint 2 installation path has completed successfully, or a working repo checkout is available;
- the recommended config path is in place;
- for live mode, the admin token is `secret-admin`.

## Recommended execution route

The canonical recommendation is the **self-contained demo script**. It spins up an in-process openMiura app, exercises the real HTTP routes through `TestClient`, and writes a report that can be inspected, screenshotted, or reused in public material.

```bash
python scripts/run_canonical_demo.py --output demo_artifacts/canonical-demo-report.json
```

Expected terminal outcome:

- `success=True`
- a `runtime_id`
- an `approval_id`
- a JSON report written to `demo_artifacts/canonical-demo-report.json`

## Optional live server route

Use the live route when you want to capture screenshots against a running local server:

```bash
python scripts/run_canonical_demo.py \
  --base-url http://127.0.0.1:8081 \
  --admin-token secret-admin \
  --output demo_artifacts/canonical-demo-live.json
```

## What the demo does

1. creates a governed runtime record;
2. dispatches a normal action so the runtime has operating context;
3. submits a sensitive quiet-hours governance activation request;
4. confirms that policy blocks activation and creates a pending approval;
5. creates a canvas document and runtime node;
6. reads the node inspector and confirms that the operator action is visible;
7. approves the request from the canvas action;
8. verifies that the governed version becomes active and signed;
9. collects version, timeline, and admin-event evidence.

## What to inspect in the report

The generated report is the core demo artifact.

Inspect these sections:

- `steps.governance_activation_requested`
- `steps.pending_approvals_before_decision`
- `steps.canvas_inspector`
- `steps.canvas_approval_result`
- `steps.versions_after_approval`
- `steps.runtime_timeline`
- `steps.admin_events`
- `validation`

## Expected evidence

The demo is successful when all of these are true:

- the activation request says `approval_required: true`;
- the new version enters `pending_approval` before approval;
- the runtime summary still shows the quiet-hours policy as inactive before approval;
- the inspector exposes `approve_governance_promotion`;
- the approval result ends with version status `active`;
- the release is marked as `signed`;
- the runtime timeline contains entries;
- the admin event feed contains entries;
- the current version matches the approved version.

## Why this proves the product thesis

This case does not optimize for conversation. It optimizes for governed execution.

What it proves is not that a model can answer a prompt. It proves that a runtime change can be:

- scoped,
- policy-evaluated,
- approval-gated,
- surfaced to an operator,
- executed only after approval,
- and left behind as auditable evidence.

## Companion material

Use these documents together:

- [Public narrative](../public_narrative.md)
- [Canonical runtime governance walkthrough](../walkthroughs/canonical_runtime_governance_walkthrough.md)
- [Screenshot plan](../media/screenshot_plan.md)
- [Medium article outline](../media/medium_article_outline.md)

## Payload references

- `docs/demos/payloads/runtime_create.json`
- `docs/demos/payloads/governance_activation_request.json`
- `docs/demos/payloads/canvas_approval_request.json`
