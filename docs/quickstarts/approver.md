# Approver Quickstart

This quickstart is for approvers: people who do not administer the whole platform, but who are authorized to approve or reject sensitive agent actions.

## What an approver does

An approver is the human control point for risky execution.

In openMiura, some actions should not run automatically. Examples include:

- terminal commands that can change systems;
- browser actions that operate in authenticated sessions;
- document or finance workflows that produce binding outputs;
- use of production secrets or production-only tools;
- release, rollback, delete, or write actions in sensitive environments.

The approver’s role is simple in principle:

- inspect the request;
- understand the risk;
- decide whether to allow it;
- leave an auditable decision.

## Before you start

You should have:

- access to the approval inbox, dashboard, or direct link;
- permission to approve for the relevant tenant/workspace/environment;
- enough context to judge whether the action is legitimate.

## What you should look at before approving

A good approval is not based on trust alone. It is based on evidence.

Review these items whenever possible:

### 1. Who initiated the request?

Check whether the requester is expected to perform this type of action.

### 2. What exactly will happen if approved?

You should be able to see, in clear language:

- the requested action;
- the affected system or environment;
- the tool or workflow involved;
- the likely effect.

### 3. Why is approval required?

Approval should not feel arbitrary. The system should tell you why it asked for a human decision.

Typical reasons:

- high-risk tool;
- production scope;
- privileged secret access;
- policy threshold exceeded;
- regulated or irreversible action.

### 4. What evidence is attached?

A strong approval review may include:

- policy explanation;
- workflow context;
- prior execution trace;
- replay or preview;
- linked ticket or incident;
- expected rollback plan.

## Approve vs reject: a simple decision framework

Approve when:

- the requester is legitimate;
- the action is understood;
- the target environment is correct;
- the business or operational justification is clear;
- the blast radius is acceptable;
- rollback or containment is possible if something goes wrong.

Reject when:

- the action is unclear;
- the wrong environment is targeted;
- the justification is weak or missing;
- the request bypasses expected change control;
- the approval appears to broaden access indirectly.

If needed, reject with a short reason so the requester can adjust and resubmit.

## Example approval scenarios

## A. Terminal command in production

A workflow wants to run a command on a production node.

As approver, verify:

- which node or cluster is targeted;
- whether this is read-only or mutating;
- whether there is a maintenance window or incident justification;
- whether rollback is available.

## B. Browser workflow with authenticated session

An agent wants to perform actions in a browser against an internal admin console.

As approver, verify:

- the site/application being accessed;
- whether the workflow is read-only or write-capable;
- whether production data could be altered;
- whether the action should instead go through an API or a better controlled path.

## C. Finance or procurement document approval

An agent proposes to process or approve a document-driven workflow.

As approver, verify:

- the document source;
- the business context;
- the confidence or review notes;
- whether a second human approval is required by policy.

## Best practices

- approve the smallest safe action, not the largest convenient action;
- prefer narrow approvals over broad ones;
- insist on readable evidence;
- leave a short reason when rejecting;
- escalate when the impact goes beyond your authority.

## Common mistakes

- approving based only on the requester’s name;
- ignoring environment mismatches;
- approving actions whose output or effect is not explained;
- treating repeated approvals as harmless even when they create a pattern of privilege creep.

## What a good approval system should give you

An approver should not have to guess. A good openMiura approval flow should show:

- who requested the action;
- what the action will do;
- why approval is required;
- what systems or data are affected;
- what policy triggered the request;
- what happened after approval or rejection.

## Success criteria

You are using approvals correctly when you can say:

- I understand what I am approving;
- I know why the request is risky enough to require me;
- my decision is recorded and explainable later;
- the platform can show whether execution matched the approved intent.

## Next documents to read

- `docs/security.md`
- `docs/production.md`
- `docs/openMiura_agent_control_plane.md`
- `docs/use_cases.md`
