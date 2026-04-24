# Screenshot plan

This plan defines the **single recommended screenshot sequence** for README, the stable release, Medium, and presentation material.

## Capture principles

- show control-plane behavior, not chat transcripts;
- prefer runtime governance state, approvals, evidence, and operator surfaces;
- keep the sequence short enough to explain in under five minutes;
- capture what the current product really does.

## Recommended capture order

### 01 · `01-installation-health-check.png`

**What to capture**

- terminal showing `openmiura doctor --config configs/openmiura.yaml`
- optional browser or curl response for `/health`

**What should be visible**

- config path is valid
- install succeeded
- service can answer health checks

**What message it supports**

- openMiura is installable and runnable as a real product, not only as source code.

**How to reproduce**

```bash
openmiura doctor --config configs/openmiura.yaml
curl http://127.0.0.1:8081/health
```

### 02 · `02-demo-script-run.png`

**What to capture**

- terminal showing the canonical demo script run and the generated report path

**What should be visible**

- `success=True`
- `runtime_id=...`
- `approval_id=...`

**What message it supports**

- there is a single repeatable public demo path.

**How to reproduce**

```bash
python scripts/run_canonical_demo.py --output demo_artifacts/canonical-demo-report.json
```

### 03 · `03-pending-approval-state.png`

**What to capture**

- JSON snippet or endpoint response from `steps.governance_activation_requested`

**What should be visible**

- `approval_required: true`
- `status: pending_approval`
- quiet-hours policy not yet active

**What message it supports**

- policy blocks sensitive execution before it happens.

**How to reproduce**

Read from `demo_artifacts/canonical-demo-report.json`:

- `steps.governance_activation_requested`

### 04 · `04-pending-approvals-summary.png`

**What to capture**

- JSON snippet or endpoint response summarizing pending approvals

**What should be visible**

- a pending approval count
- runtime identifier and scope

**What message it supports**

- approval state is explicit and queryable.

**How to reproduce**

Read from report:

- `steps.pending_approvals_before_decision`

Or query the live endpoint:

```text
/admin/openclaw/alert-governance-promotion-approvals
```

### 05 · `05-canvas-inspector-action.png`

**What to capture**

- canvas node inspector output or UI state showing the runtime node actions

**What should be visible**

- `approve_governance_promotion`

**What message it supports**

- the operator surface exposes governed actions, not just logs.

**How to reproduce**

Read from report:

- `steps.canvas_inspector`

Or query the live inspector endpoint:

```text
/admin/canvas/documents/{canvas_id}/nodes/{node_id}/inspector
```

### 06 · `06-approval-result-active-version.png`

**What to capture**

- JSON snippet or UI state after approval

**What should be visible**

- approval status `approved`
- version status `active`
- signed release information

**What message it supports**

- human approval is a real execution boundary.

**How to reproduce**

Read from report:

- `steps.canvas_approval_result`

### 07 · `07-runtime-timeline-and-events.png`

**What to capture**

- timeline or event output showing the governed sequence after activation

**What should be visible**

- runtime timeline entries
- admin event entries

**What message it supports**

- the operation remains auditable after execution.

**How to reproduce**

Read from report:

- `steps.runtime_timeline`
- `steps.admin_events`

### 08 · `08-current-version-signed-evidence.png`

**What to capture**

- the current version object after approval

**What should be visible**

- `current_version`
- matching `version_id`
- signed release metadata

**What message it supports**

- the governed change has a stable, reviewable final state.

**How to reproduce**

Read from report:

- `steps.versions_after_approval`

## Minimal capture set

If only four images fit, keep these:

1. `01-installation-health-check.png`
2. `03-pending-approval-state.png`
3. `05-canvas-inspector-action.png`
4. `08-current-version-signed-evidence.png`

## Reuse map

### README

Use:

- 01 for installation credibility
- 03 and 05 for the canonical demo section

### Stable release notes

Use:

- 01
- 06
- 08

### Medium article

Use the full sequence 01–08.

### Presentation / slides

Use:

- 01
- 03
- 05
- 06
- 08

## Supporting assets

Canonical inputs already exist in:

- `docs/demos/payloads/runtime_create.json`
- `docs/demos/payloads/governance_activation_request.json`
- `docs/demos/payloads/canvas_approval_request.json`

The canonical walkthrough is in:

- [Canonical runtime governance walkthrough](../walkthroughs/canonical_runtime_governance_walkthrough.md)
