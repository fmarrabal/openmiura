# Stable release final pack · openMiura 1.0.0

## Recommended release title

**openMiura v1.0.0 — Stable release**

## GitHub Release short summary

openMiura `1.0.0` is the first stable public release of the project as a governed agent operations platform. It provides a stable downloadable artifact line, a Windows-first installation path, and a canonical end-to-end demo that shows policy evaluation, human approval, signed governance evidence, and auditable operator review around a governed runtime action.

## GitHub Release body

openMiura `1.0.0` is the first stable public release of the project as a **governed agent operations platform**.

The recommended way to evaluate this line is simple:

1. download the stable reproducible bundle and verification assets;
2. validate the installation with `openmiura doctor` and a local service start;
3. run the canonical public demo;
4. inspect the resulting approval state, signed governance evidence, runtime timeline, and admin events.

### Highlights

- first stable downloadable artifact line
- stable reproducible bundle, wheel, and sdist publication
- Windows-first installation and validation path
- canonical public demo for governed runtime operations
- public walkthrough, screenshot plan, and Medium-ready narrative pack

### Recommended assets to download

For the first serious evaluation, download:

- reproducible bundle zip
- reproducible bundle manifest
- `RELEASE_MANIFEST.json`
- `SHA256SUMS.txt`

For Python-package-oriented consumption, also download:

- wheel
- sdist

### Official installation path

Use the stable reproducible bundle as the primary path, especially on Windows.

Recommended validation:

```bash
openmiura doctor --config configs/openmiura.yaml
openmiura run --config configs/openmiura.yaml
```

Check:

- `http://127.0.0.1:8081/health`
- `http://127.0.0.1:8081/ui`

### Canonical public demo

Run:

```bash
python scripts/run_canonical_demo.py --output demo_artifacts/canonical-demo-report.json
```

Inspect these proof points:

- `pending_approval` state before approval
- operator-visible approval action through the canvas inspector
- active signed version after approval
- runtime timeline
- admin events

### What the product demonstrates in this release

openMiura shows a serious control-plane posture around runtime-affecting actions:

- policy evaluation before execution
- approval gating for sensitive change
- operator-visible review surfaces
- signed governance evidence
- auditable operational records

### Honest limitations

This stable line does not claim to solve every production concern automatically. Organizations still bring their own:

- identity and access model
- secret-management posture
- infrastructure topology
- operator processes
- production rollout policy

### Relationship to RC1

`v1.0.0-rc1` remains the validation checkpoint for this line.

`v1.0.0` is the first stable release that should carry the official downloadable asset set.

## Short announcement text

openMiura `1.0.0` is out as the first stable public release of the project as a governed agent operations platform. The line includes a stable artifact set, a Windows-first installation path, and a canonical demo that shows policy-gated runtime change, human approval, signed evidence, and auditable operator review.

## README release section snippet

**Stable release:** `v1.0.0` is the first stable public line of openMiura as a governed agent operations platform. Start with the reproducible bundle, validate with `openmiura doctor`, then run the canonical demo to inspect approval gating, signed evidence, and operator-visible audit trail around a governed runtime action.

## Short social / post copy

openMiura `1.0.0` marks the first stable public release of the project as a governed agent operations platform: a control plane for policy, approvals, evidence, auditability, and operator visibility around runtime operations. Start with the stable bundle and the canonical governed runtime demo.
