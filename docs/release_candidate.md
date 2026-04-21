# Release Candidate RC1

RC1 is the formal frozen candidate that closes the current product-remate cycle for openMiura.

## Product statement

openMiura is a governed agent operations platform. It is designed to govern runtimes, policies, approvals, evidence and operator control surfaces rather than behave as a generic personal assistant.

## What RC1 means

RC1 is the first bundle in this line that is intended to be:

- clean enough to hand to another team
- explicit about support boundaries
- backed by a named release-quality gate
- documented as a controlled pilot artifact

## Freeze command

To freeze a clean RC bundle from the source tree:

```bash
python scripts/freeze_release_candidate.py --output-dir dist/rc --label rc1 --version 1.0.0-rc1
```

The command generates:

- a clean RC zip bundle
- a `release_candidate_manifest.json` file

## Required validation before distribution

Run at least:

```bash
python -m pip install ".[dev]"
python scripts/run_release_quality_gate.py --include-extended --output-dir reports/quality_gate
python scripts/freeze_release_candidate.py --output-dir dist/rc --label rc1 --version 1.0.0-rc1
openmiura doctor --config configs/openmiura.yaml
```

If the environment also supports `python -m build`, execute the full build+verify path described in `docs/release_quality_gate.md`.

## Scope of RC1

RC1 includes:

- governed runtime control surfaces
- approvals and evidence flows
- baseline and policy-pack governance
- Config Center, channel wizards and secrets/env references UI
- tiny runtime trust and certificate management UI
- reproducible packaging and release-manifest foundations

## Distribution posture

Use RC1 for controlled pilots, demos and technical evaluation. Keep it behind intentional auth, reverse proxy and environment-specific configuration.

## Related material

- [Release support matrix](release_support_matrix.md)
- [Release-candidate quickstart](quickstarts/release_candidate.md)
- [Release quality gate](release_quality_gate.md)
- [Enterprise alpha guide](enterprise_alpha.md)
- [Alpha release checklist](alpha_release_checklist.md)
- [GitHub PR, merge and publication checklist](github_pr_merge_publish_checklist.md)
