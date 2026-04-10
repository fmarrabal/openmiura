# Admin Quickstart

This quickstart is for platform administrators responsible for operating openMiura safely in shared or regulated environments.

## What an admin does in openMiura

An admin is responsible for the platform itself, not just individual agent runs. The admin makes sure that:

- the system is deployed correctly;
- tenants, workspaces, and environments are isolated;
- packaging and releases are trustworthy;
- approvals and audit trails are working;
- secrets, policies, and hardening settings are enforced;
- incidents can be investigated and contained.

In practical terms, the admin is the person who answers questions such as:

- Can we allow this team to use agents in production?
- Can this workspace use terminal, browser, or voice features?
- Can we prove what happened during a sensitive run?
- Can we promote a new release safely?

## Before you start

You should have:

- access to the admin interface or admin API;
- permission to inspect tenants, workspaces, policies, and audit data;
- a deployment that is already installed and reachable;
- at least one test workspace you can use safely.

## First 15 minutes checklist

### 1. Check platform health

Confirm that the service is up and that the core subsystems are healthy:

- HTTP/API service
- broker/runtime connectivity
- database/audit store
- background jobs/scheduler
- realtime/event stream if enabled
- packaging metadata if release features are enabled

What you want to verify:

- no startup errors;
- no migration mismatches;
- no obvious rate-limit or auth failures;
- no missing configuration for the target environment.

### 2. Check tenant and workspace boundaries

Review whether the platform is partitioned correctly:

- tenant A cannot see tenant B data;
- workspace-scoped memory is isolated;
- audit trails are filtered correctly;
- environment-specific config is not leaking across workspaces.

This matters because openMiura becomes enterprise-grade only when isolation is not just a convention, but an enforced platform property.

### 3. Review policies and approvals

Make sure risky actions are not allowed silently.

Examples of actions that should usually require policy control or approval:

- terminal execution;
- browser actions against authenticated systems;
- actions that use production secrets;
- release promotion;
- deletion, rollback, or write actions in regulated workflows.

### 4. Validate release and packaging state

If you are using build and release governance, verify:

- the package was produced from the expected version;
- reproducible packaging metadata exists;
- hardening options match the target environment;
- build artifacts are recorded and traceable.

## Core admin workflows

## A. Create or review a tenant/workspace setup

A healthy setup usually looks like this:

- one tenant per customer or organizational boundary;
- one or more workspaces per team, product area, or risk domain;
- separate environments such as development, staging, and production.

Questions to ask:

- Should development and production share the same secrets? Usually no.
- Should one workspace be allowed to use another workspace's tools? Usually no.
- Should all channels have access to all agents? Usually no.

## B. Promote a release safely

A controlled release flow should include:

1. build produced;
2. evidence recorded;
3. packaging profile validated;
4. policy checks passed;
5. canary or staged promotion if available;
6. rollback path verified.

As admin, you are looking for trust signals, not just “the build succeeded.”

## C. Investigate a failed or suspicious run

When an incident occurs, check:

- who initiated the run;
- in which tenant/workspace/environment it happened;
- which agent handled it;
- what policy decisions were made;
- whether approval was required and granted;
- which tool calls were attempted;
- whether a secret reference was involved;
- final result, latency, and error state.

A good admin investigation ends with one of these outcomes:

- issue explained and closed;
- policy tightened;
- runtime isolated;
- release rolled back;
- access revoked or scoped down.

## D. Review hardening posture

Admin responsibilities also include confirming that the platform is hardened for its operating context.

Typical areas to review:

- authentication and admin token handling;
- secret storage and secret injection boundaries;
- sandbox or runner restrictions;
- audit immutability and retention;
- packaging trust and release provenance;
- environment-specific feature flags.

## Suggested routine

## Daily

- check health and alerts;
- review failed runs and blocked approvals;
- review policy denials for false positives or real risk;
- confirm no unexpected tenant/workspace crossovers.

## Weekly

- review release evidence and deployment history;
- review top risky tool calls;
- confirm backup and restore posture;
- review costs, quotas, and workspace usage.

## Monthly

- review admin and privileged access;
- review policy coverage gaps;
- test incident response and rollback;
- prune or archive stale workspaces if needed.

## Common mistakes

- treating tenants and workspaces as naming conventions instead of enforced isolation;
- allowing broad access to terminal or browser actions without approvals;
- storing secrets in prompts or static config visible to agents;
- promoting builds without reproducibility or evidence;
- focusing on agent output quality while ignoring operational control.

## Success criteria

You are using openMiura correctly as an admin when you can say:

- we know who can do what;
- we know what happened during any sensitive run;
- we can prove approvals and policy decisions;
- we can isolate failures and roll back safely;
- we can promote releases with confidence.

## Next documents to read

- `docs/security.md`
- `docs/production.md`
- `docs/observability.md`
- `docs/backup_restore.md`
- `docs/ci_cd.md`
