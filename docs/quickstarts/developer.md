# Developer Quickstart

This quickstart is for developers extending, testing, or integrating openMiura.

## What a developer does in openMiura

A developer typically works on one or more of these areas:

- core services and APIs;
- broker/runtime integration;
- tools and providers;
- workflows and approvals;
- packaging and release flows;
- channels such as Slack, Telegram, or web;
- UI surfaces such as operations views and canvas features.

The goal is not only to make the platform powerful, but to keep it governable.

## Development mindset

When building in openMiura, do not think only in terms of “can the agent do this?”

Also ask:

- should this action be allowed at all?
- in which tenant/workspace/environment?
- under which policy?
- with which secret boundary?
- with which audit evidence?
- with which rollback or replay path?

That is the difference between an agent demo and an enterprise platform.

## Local setup

## 1. Clone and install

From the repository root, create or activate your environment and install the project in editable mode.

Typical workflow:

- install Python;
- create a virtual environment;
- install the project with development dependencies;
- verify the package imports correctly.

A common pattern is:

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## 2. Run the main app

Start the HTTP app or the main gateway entry point used by the project.

Typical goals for first run:

- app boots without import errors;
- configuration loads correctly;
- database migrations are in sync;
- health endpoints respond;
- admin endpoints are reachable if enabled.

## 3. Run the broker/runtime components if required

If your task involves broker features, runtime adapters, packaging, or channels, start the required services locally and verify connectivity.

## First things to understand in the codebase

Developers should get familiar with these broad layers:

### Application layer

Contains use cases and service logic such as:

- workflow orchestration;
- approvals;
- packaging governance;
- release operations;
- policy-driven runtime decisions.

### Interfaces layer

Contains the edges of the system:

- HTTP routes;
- broker routes;
- channel adapters;
- admin endpoints;
- external runtime integrations.

### Core layer

Contains the internal foundations:

- configuration;
- audit store;
- shared domain models;
- migrations;
- common primitives.

### Extensions/runtime layer

Contains tools, providers, skills, channels, and future runtime integrations such as OpenClaw compatibility.

## Recommended first developer tasks

## A. Run targeted tests

Instead of running everything blindly, begin with focused areas.

Examples:

- tests for admin and governance features;
- tests for workflows and approvals;
- tests for packaging and release governance;
- tests for canvas or realtime functionality if that is your area.

Then run the broader suite once your local changes are stable.

## B. Trace one end-to-end governed run

Pick one simple request and follow it through the system:

1. inbound request enters;
2. policy is checked;
3. approval is requested if needed;
4. runtime/tool dispatch occurs;
5. audit is recorded;
6. result is returned.

This gives you a mental model of how openMiura works as a governed execution system.

## C. Modify a small feature in a controlled area

Good first changes are usually:

- improving an admin or audit response;
- tightening validation;
- adding a narrow test case;
- extending a policy explanation path;
- improving documentation.

## Developer principles

## 1. Governance is part of the feature

If you add a tool, workflow step, or runtime action, ask how it is:

- authorized;
- approved;
- audited;
- bounded by secrets;
- isolated by tenant/workspace.

## 2. Prefer explicit contracts

The platform becomes stronger when interfaces are clear.

Examples:

- runtime adapter interfaces;
- structured audit events;
- policy decision models;
- approval request schemas;
- packaging manifests.

## 3. Avoid hidden privilege

Do not make powerful actions silently available just because the code path exists.

## 4. Keep tests close to operational guarantees

The most valuable tests are often not purely functional. They check guarantees such as:

- isolation;
- denial under policy;
- approval requirement enforcement;
- audit completeness;
- packaging reproducibility;
- rollback safety.

## Common developer mistakes

- building features that bypass policy and approval layers;
- treating secrets as configuration values instead of controlled assets;
- optimizing for agent capability while ignoring tenant/workspace segregation;
- relying on local assumptions that break in CI or self-hosted deployments;
- adding new runtime power without adding audit evidence.

## If you are implementing OpenClaw compatibility

The right mental model is:

- openMiura governs;
- the external runtime executes.

That means the integration should be shaped around:

- runtime abstraction;
- policy checks before dispatch;
- approval checks before dispatch;
- normalized results and events;
- unified audit and operations trace.

## Success criteria

You are productive as a developer when you can:

- run the platform locally;
- understand one governed execution flow end to end;
- add or change functionality without bypassing governance;
- write focused tests that protect enterprise guarantees.

## Next documents to read

- `docs/installation.md`
- `docs/deployment.md`
- `docs/security.md`
- `docs/extensions_sdk.md`
- `docs/mcp_broker_integration.md`
- `docs/ci_cd.md`
