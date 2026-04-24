# Public narrative

This document defines the **single recommended external narrative** for openMiura across the README, stable release notes, public demos, screenshots, and the Medium article.

## One-line product definition

**openMiura is a governed agent operations platform: a control plane that governs agent runtimes and operational automations with policy, approvals, evidence, auditability, and operator visibility.**

## Short positioning paragraph

openMiura is for teams that want the benefits of agentic systems without accepting ungoverned execution. Instead of replacing runtimes, openMiura sits in front of them as the governance layer: it evaluates policy, blocks sensitive actions when required, routes approvals, records evidence, and gives operators a visible audit trail around what happened and why.

## Tagline

**Bring your runtime. openMiura governs it.**

## What to say clearly

Use these points consistently in public material:

- openMiura is a **control plane**, not a chatbot.
- openMiura governs **runtime actions and operational change**, not just prompt/response traffic.
- openMiura is designed for **tenant / workspace / environment scoped operation**.
- sensitive actions can be **gated pending human approval**.
- approvals, releases, timelines, and exported evidence create an **auditable operational record**.
- operator-facing surfaces matter as much as runtime execution.

## What not to say

Avoid these framings:

- “another AI assistant”
- “the best chatbot for enterprises”
- “a universal autonomous agent”
- “a replacement for OpenClaw”
- any claim that implies fully autonomous operation without governance boundaries

## Canonical proof point

The canonical public proof point is the demo called **Governed runtime alert policy activation**.

That case shows a single operational story:

1. a sensitive request arrives over HTTP;
2. openMiura resolves tenant, workspace, and environment context;
3. policy requires approval;
4. the action is blocked in `pending_approval`;
5. an operator reviews the request through a canvas runtime inspector;
6. a human approves it;
7. the runtime change becomes active;
8. signed release data, timeline history, and admin events remain available as evidence.

This is the shortest serious explanation of why openMiura exists.

## OpenClaw framing

Use this exact framing publicly:

- **OpenClaw is one governed runtime that openMiura can supervise.**
- **OpenClaw is not the product identity of openMiura.**
- **openMiura does not need to replace the runtime to govern it.**

That keeps the product thesis intact:

- the runtime executes;
- openMiura governs.

## Short capability list for public use

Use this compact capability list when space is limited:

- governed execution
- policy and approval gating
- evidence and audit trail
- release and promotion governance
- operator visibility through canvas and admin surfaces
- local-first, multi-tenant posture

## Recommended README / release phrasing

### README paragraph

openMiura is a governed agent operations platform for teams that need control around agent runtimes and operational automations. It sits in front of runtime execution to enforce policy, approvals, evidence capture, auditability, and operator visibility.

### Stable release summary paragraph

Version 1.0.0 establishes openMiura as a public, installable control plane for governed runtime operations. The stable line combines reproducible artifacts, a Windows-first install path, and a canonical end-to-end demo that shows policy evaluation, human approval, signed release evidence, and auditable operator review.

### Demo intro paragraph

The canonical demo is not a chat demo. It is a governed operational action that stays blocked until policy and human approval allow execution, then leaves behind signed and reviewable evidence.

## Language guardrails

Prefer these terms:

- governed runtime
- control plane
- sensitive operational action
- approval-gated change
- auditable evidence
- operator surface
- runtime governance

Use “assistant” only when describing what openMiura is **not** trying to be.

## Audience fit

This narrative is aimed at:

- platform engineers
- security and governance leads
- AI infrastructure teams
- technical decision makers evaluating controlled agent deployment

It is not written first for mass consumer AI audiences.
