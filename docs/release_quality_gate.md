# Release quality gate

openMiura ships with a single, explicit release-quality gate for release readiness.

The goal is to answer two operational questions with evidence instead of intuition:

1. **Did the curated release-required suites pass?**
2. **Was a release artifact build and verification completed in the current environment?**

## What the gate does

`python scripts/run_release_quality_gate.py` performs these stages:

1. collects the current pytest inventory
2. runs `openmiura doctor --config configs/openmiura.yaml`
3. runs a reproducible packaging smoke test through `PackagingHardeningService`
4. runs the curated **required** pytest suites from `ops/quality_gate/release_required.txt`
5. optionally runs broader **extended** suites from `ops/quality_gate/release_extended.txt`
6. if `python -m build` is available, builds release artifacts and verifies them against `RELEASE_MANIFEST.json`
7. emits machine-readable and human-readable reports under `reports/quality_gate/`

## Commands

Required gate only:

```bash
python scripts/run_release_quality_gate.py --output-dir reports/quality_gate
```

Required + extended suites:

```bash
python scripts/run_release_quality_gate.py --include-extended --output-dir reports/quality_gate
```

If you want to skip the wheel/sdist build stage in a constrained environment:

```bash
python scripts/run_release_quality_gate.py --include-extended --skip-build --output-dir reports/quality_gate
```

## Output artifacts

The gate writes:

- `reports/quality_gate/release_quality_gate_report.json`
- `reports/quality_gate/release_quality_gate_report.md`
- `reports/quality_gate/junit-required-<n>.xml` for each required-suite chunk
- `reports/quality_gate/coverage-required.xml` when coverage is enabled and the required suites run in a single chunk
- command logs for each stage

## Decision model

### Required gate

The **required gate** is green only when all of the following are green:

- pytest collection
- `openmiura doctor`
- reproducible packaging smoke
- curated required suites

### Full release gate

The **full release gate** is green only when the required gate is green **and**:

- `python -m build` is available in the environment
- `scripts/build_release_artifacts.py --strict` succeeds
- `scripts/verify_release_artifacts.py --dist-dir ...` succeeds

This lets local development environments remain useful while still distinguishing them from a real release environment.

## Curated suites

The curated lists live in:

- `ops/quality_gate/release_required.txt`
- `ops/quality_gate/release_extended.txt`

Treat them as versioned release policy, not as an ad-hoc scratch list.

## CI posture

The GitHub workflows should install `.[dev]` for jobs that execute the release gate or artifact builds, so `build` and other release-time dependencies are consistently available.
