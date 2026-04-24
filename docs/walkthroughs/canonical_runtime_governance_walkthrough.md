# Walkthrough · canonical runtime governance case

## Case name

**Governed runtime alert policy activation**

## Objective

Show, in one compact story, how openMiura governs a sensitive operational change over a runtime without turning into a generic assistant demo.

## Why this walkthrough matters

This walkthrough is the public proof that openMiura is a control plane.

The goal is not to show that a model can answer a prompt. The goal is to show that a runtime-affecting change can be:

- scoped to tenant, workspace, and environment;
- evaluated by policy;
- blocked pending human approval;
- surfaced to an operator;
- executed only after approval;
- preserved as evidence afterward.

## Actors

- **Requester**: `platform-admin`
- **Approver**: `security-admin`
- **Governed runtime**: simulated OpenClaw-compatible runtime
- **Operator surface**: canvas runtime inspector

## Preconditions

- openMiura is installed using the route in [Installation](../installation.md)
- the canonical demo assets from [Canonical demo](../demos/canonical_demo.md) are available
- the admin token is `secret-admin` in the demo profile

## Minimal architecture involved

```text
HTTP request
   |
   v
openMiura FastAPI control plane
   |
   +--> policy evaluation and approval gating
   +--> approval state and admin events
   +--> canvas operator surface
   +--> governed runtime adapter
   +--> signed governance release record
```

## Flow overview

### 1. Runtime registration

The demo first creates a governed runtime record.

What to observe:

- a runtime exists under a concrete tenant, workspace, and environment;
- the runtime metadata includes a governance release policy;
- the runtime is now available for controlled operations.

What value this proves:

- openMiura is governing a runtime, not simulating a chatbot exchange.

### 2. Initial runtime activity

The demo sends a normal dispatch to make the runtime operational.

What to observe:

- the runtime has an operational context before the sensitive change is requested.

What value this proves:

- the later governance step is happening around an active runtime surface.

### 3. Sensitive request enters the control plane

A request arrives over HTTP asking openMiura to activate a quiet-hours alert governance policy on the runtime.

What to observe:

- the request is associated to `tenant-a`, `ws-a`, and `prod`;
- the request is treated as a runtime governance action, not a chat message.

What value this proves:

- openMiura normalizes incoming work into governed operational context.

### 4. Policy evaluation blocks immediate execution

The runtime metadata states that governance promotion requires approval.

What to observe:

- the candidate version enters `pending_approval`;
- the target policy is **not yet active**;
- a pending approval object is created.

What value this proves:

- sensitive operational changes do not execute immediately just because they were requested.

### 5. Pending state becomes visible to an operator

The demo creates a canvas document and a runtime node, then reads the node inspector.

What to observe:

- the inspector exposes `approve_governance_promotion` as an available action;
- the operator surface can review the governed runtime context.

What value this proves:

- governance is visible and operable through an operator surface, not hidden in logs alone.

### 6. Human approval unblocks the change

The approver executes the inspector action to approve the pending governance promotion.

What to observe:

- the approval status becomes `approved`;
- the version status becomes `active`;
- the governance release is marked as signed.

What value this proves:

- human approval is a real control boundary that changes system state.

### 7. Evidence and audit trail remain available

The demo then queries version state, runtime timeline, and admin events.

What to observe:

- the current version matches the approved version;
- runtime timeline items are present;
- admin events are present;
- signed release data remains attached to the version.

What value this proves:

- execution is not the end of the story; openMiura leaves a reviewable record behind.

## Exact execution path

### Self-contained route

```bash
python scripts/run_canonical_demo.py --output demo_artifacts/canonical-demo-report.json
```

This is the recommended public route because it is:

- local;
- reproducible;
- independent of external infrastructure;
- aligned with the real HTTP and admin surfaces through `TestClient`.

### Live local server route

```bash
python scripts/run_canonical_demo.py \
  --base-url http://127.0.0.1:8081 \
  --admin-token secret-admin \
  --output demo_artifacts/canonical-demo-live.json
```

Use the live route when you want screenshots from an actual running server.

## What to inspect in the demo report

The generated JSON report is the core artifact for walkthrough, screenshots, and article writing.

Inspect these sections:

- `steps.governance_activation_requested`
- `steps.pending_approvals_before_decision`
- `steps.canvas_inspector`
- `steps.canvas_approval_result`
- `steps.versions_after_approval`
- `steps.runtime_timeline`
- `steps.admin_events`
- `validation`

## What this walkthrough demonstrates at each phase

| Phase | What you see | What it proves |
|---|---|---|
| Request intake | scoped runtime governance request | openMiura is governing operations, not chatting |
| Policy gate | `pending_approval` | policy can block execution |
| Operator review | canvas inspector action | governance is observable |
| Human decision | approval becomes `approved` | a human boundary exists |
| Execution | version becomes `active` | change is applied only after approval |
| Evidence | signed release, timeline, events | the operation remains auditable |

## Recommended screenshot moments

Use the screenshot plan in [Screenshot plan](../media/screenshot_plan.md). The most important moments are:

1. installation/health validation;
2. demo script run;
3. pending approval state;
4. canvas inspector action visibility;
5. approved active version with signed release evidence.

## Reuse guidance

This walkthrough is the canonical source for:

- README demo explanation;
- stable release notes;
- public product walkthroughs;
- Medium article narrative;
- slide deck flow;
- screenshot sequencing.

When in doubt, use this walkthrough rather than improvising a new story.
