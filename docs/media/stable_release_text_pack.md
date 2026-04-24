# Stable release text pack

This file contains the recommended public text blocks for the future `1.0.0` stable release.

## Stable release summary

openMiura `1.0.0` is the first stable public release of the project as a governed agent operations platform. It packages a reproducible artifact line, a Windows-first installation path, and a canonical end-to-end demo that shows policy evaluation, human approval, signed release evidence, and auditable operator review around a governed runtime action.

## Release highlights

- first stable downloadable artifact line
- stable reproducible bundle, wheel, and sdist publication
- Windows-first installation and validation path
- canonical public demo for governed runtime operations
- public-facing walkthrough, screenshot plan, and Medium-ready narrative pack

## What to download

For the first serious evaluation, download:

- the reproducible bundle zip
- the reproducible bundle manifest
- `RELEASE_MANIFEST.json`
- `SHA256SUMS.txt`

For Python-package-oriented consumption, also download:

- the wheel
- the sdist

## How to validate installation

Recommended first-start validation:

```bash
openmiura doctor --config configs/openmiura.yaml
openmiura run --config configs/openmiura.yaml
```

Key checks:

- `/health`
- `/ui`
- the canonical demo report

## How to run the canonical demo

```bash
python scripts/run_canonical_demo.py --output demo_artifacts/canonical-demo-report.json
```

Inspect:

- pending approval state
- canvas approval action visibility
- active signed version after approval
- runtime timeline
- admin events

## Honest limitations

This stable line does not claim to solve every production concern automatically. Organizations still bring their own:

- identity and access model
- secret-management posture
- infrastructure topology
- operator processes
- production rollout policy

## RC1 relationship

`v1.0.0-rc1` remains the validation checkpoint for the line.

`v1.0.0` is the first stable release that should carry the official downloadable asset set.
