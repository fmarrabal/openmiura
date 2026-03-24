# Operator Quickstart

This quickstart is for operators: people who run the platform day to day, monitor activity, respond to issues, and keep workflows moving.

## What an operator does

The operator sits between administration and end users.

An operator may:

- monitor active runs and workflows;
- watch approvals and escalations;
- inspect policy denials and failures;
- help recover stuck executions;
- review replay and timeline evidence;
- coordinate with admins, developers, or approvers during incidents.

The operator is not necessarily the person defining policy or deploying code. The operator keeps the system usable and safe in practice.

## What to watch first

A good operator view should answer these questions quickly:

- which agents are currently active?
- which workflows are running right now?
- which executions are waiting for approval?
- which runs failed or got blocked?
- which policy denials are expected versus suspicious?
- where are cost or latency spikes appearing?

## First 15 minutes checklist

### 1. Open the main operational surface

This may be a PWA, admin console, operator console, or canvas-style operations screen.

Confirm you can see:

- current runs;
- recent failures;
- pending approvals;
- runtime or channel health;
- recent alerts or warnings.

### 2. Review blocked and pending items

Focus first on anything that is stuck:

- approval pending too long;
- runtime dispatch failed;
- policy denied unexpectedly;
- workflow waiting on missing input;
- repeated retries.

### 3. Check for noisy or unhealthy patterns

Examples:

- one workspace producing many failures;
- an agent stuck in retry loops;
- sudden increase in policy denials;
- large latency increase;
- unusual cost growth;
- one channel producing malformed requests.

## Core operator workflows

## A. Monitor a running workflow

For an active workflow, inspect:

- current state;
- current step;
- waiting reason if paused;
- related approvals;
- last tool call;
- errors, warnings, or retries;
- expected next action.

Operators are often the first to notice whether a process is merely slow or genuinely broken.

## B. Handle an approval bottleneck

If a critical workflow is waiting for approval:

- verify which approval is required;
- identify the right approver;
- confirm whether the request is still relevant;
- escalate if the SLA is at risk.

The operator should not blindly approve unless explicitly authorized to do so.

## C. Triage a failed run

When a run fails, the operator should quickly determine whether the failure is due to:

- user input;
- policy denial;
- approval missing;
- runtime failure;
- tool failure;
- secret access issue;
- environment/configuration issue.

This helps route the issue correctly:

- to the requester;
- to an approver;
- to an admin;
- to engineering.

## D. Use replay and timeline views

Replay and timeline features are especially useful when:

- a workflow did not behave as expected;
- a tool call was blocked;
- a user disputes what happened;
- you need to reconstruct the path to failure.

The operator does not need to inspect every low-level detail, but should know how to find the execution story quickly.

## E. Manage voice or multimodal actions if enabled

If your deployment includes voice, browser, or rich canvas features, the operator should verify that sensitive actions remain controlled.

Examples:

- voice command requested a privileged action;
- browser action targeted a protected system;
- visual/canvas overlay indicates a blocked or pending step;
- multimodal input created an ambiguous request requiring clarification.

## Escalation model

Operators should know who owns what.

Escalate to:

- **Approver** when the issue is a pending or disputed approval;
- **Admin** when the issue concerns policy, isolation, release, or privileged access;
- **Developer/engineering** when the issue is a defect, runtime integration failure, or broken feature;
- **Requester/business owner** when the workflow intent itself is unclear or no longer needed.

## Daily operating rhythm

## Start of shift

- check health and alerts;
- review pending approvals;
- review failed or retried runs;
- review any high-risk policy denials.

## During the day

- watch active workflows;
- triage new failures;
- keep approvals moving;
- monitor unusual cost or latency spikes;
- surface repeating issues to admin or engineering.

## End of shift

- hand over unresolved incidents;
- note recurring approval bottlenecks;
- summarize top failures or policy conflicts;
- confirm no critical workflows are stuck invisibly.

## Common mistakes

- treating all failures as engineering problems when many are governance or approval issues;
- bypassing process to “just make it run”;
- ignoring repeated policy denials that indicate misconfiguration or unsafe usage;
- focusing only on output instead of workflow state and execution trace;
- failing to escalate when privileged or production actions are affected.

## Success criteria

You are effective as an operator when:

- workflows move with minimal avoidable delay;
- failures are classified quickly and routed correctly;
- approvals do not disappear into a black hole;
- suspicious or risky patterns are surfaced early;
- teams can rely on the platform operationally, not just technically.

## Next documents to read

- `docs/observability.md`
- `docs/troubleshooting.md`
- `docs/production.md`
- `docs/runbooks/alerts.md`
- `docs/openMiura_agent_control_plane.md`
