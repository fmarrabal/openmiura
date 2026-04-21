# GitHub PR, merge and publication checklist

This checklist is the final operational handoff for pushing openMiura RC1 to GitHub and closing the release-preparation loop without reopening product scope.

Use it for the last PR to `main`, the merge decision, and the immediate publication steps after merge.

## 1. Goal

The objective is not to add new features. The objective is to land a clean, reviewable, reproducible and publishable state of openMiura as a governed agent operations platform.

## 2. PR preflight checklist

Complete these items before opening the final PR.

### 2.1 Repository hygiene

- [ ] Working tree is clean.
- [ ] No local runtime artifacts remain (`.pytest_cache/`, `__pycache__/`, local databases, ad-hoc reports, temporary archives).
- [ ] `.env` files are not tracked.
- [ ] Generated release bundles were reviewed before attachment or upload.
- [ ] `.gitignore` covers known local artifacts.

### 2.2 Validation

Run and review at least the following:

```bash
python -m pip install ".[dev]"
python scripts/run_release_quality_gate.py --include-extended --output-dir reports/quality_gate
python scripts/freeze_release_candidate.py --output-dir dist/rc --label rc1 --version 1.0.0-rc1
python scripts/build_release_artifacts.py --dist-dir dist --tag v-release --target desktop --strict
python scripts/verify_release_artifacts.py --dist-dir dist
python -m pytest -q
openmiura doctor --config configs/openmiura.yaml
```

Mark any deviation explicitly in the PR description.

### 2.3 Workflow readiness

- [ ] `.github/workflows/ci.yml` was reviewed for current branch protection expectations.
- [ ] `.github/workflows/package-reproducible.yml` is still aligned with local packaging commands.
- [ ] `.github/workflows/release.yml` uploads the intended artifacts.
- [ ] `.github/workflows/security.yml` still reflects the intended security posture.
- [ ] Required GitHub checks for `main` are known before opening the PR.

### 2.4 Release artifacts

- [ ] `dist/` contains the intended wheel, sdist and release bundle.
- [ ] `SHA256SUMS.txt` exists and was reviewed.
- [ ] `RELEASE_MANIFEST.json` exists and was reviewed.
- [ ] `reports/quality_gate/release_quality_gate_report.md` was reviewed.
- [ ] Release notes are updated.

### 2.5 Messaging and scope control

- [ ] The PR is framed as release-readiness / controlled-publication work, not a new macro-phase.
- [ ] Product thesis remains stable: openMiura is a governed agent operations platform / control plane.
- [ ] OpenClaw is still described as a governed runtime, not as the product identity.

## 3. Final PR checklist

Use this structure when opening the PR.

### Suggested title

`release: finalize RC1 for GitHub merge and publication`

### Suggested scope

- release hygiene only
- packaging/reproducibility only
- documentation alignment only
- no macro redesign
- no scope expansion beyond RC1 closure

### Items to include in the PR description

- [ ] Objective of the PR
- [ ] Exact validation commands executed
- [ ] Any known non-blocking issues
- [ ] Rollback path
- [ ] Merge recommendation (`GO` / `NO-GO`)

## 4. Merge checklist

Do not merge only because CI is green. Merge when the operational release story is coherent.

- [ ] All required status checks are green.
- [ ] Review comments were resolved.
- [ ] No hidden local artifacts or generated files remain in the diff.
- [ ] Documentation matches the shipped behavior.
- [ ] Security posture remains secure-by-default.
- [ ] Release notes are attached or linked.
- [ ] The merge method is consistent with repository rules.
- [ ] The target commit is the one used for release artifact generation or is traceably equivalent.
- [ ] A reviewer explicitly confirms `GO`.

## 5. Post-merge checklist

Immediately after merge:

- [ ] Pull `main` and verify the merge commit locally.
- [ ] Re-run the release workflow or tag workflow from the merged commit if required.
- [ ] Download the generated artifacts from GitHub Actions.
- [ ] Verify checksums against `SHA256SUMS.txt`.
- [ ] Confirm the release manifest matches the expected commit and version.
- [ ] Archive `reports/quality_gate/` with the release evidence.
- [ ] Confirm release notes and support posture are the final intended ones.

## 6. Publication checklist

Use this section for the first external or semi-external publication.

### 6.1 GitHub release

- [ ] Create or verify the GitHub Release entry.
- [ ] Attach the intended artifacts only.
- [ ] Include `RELEASE_NOTES_RC1.md` content or an equivalent summary.
- [ ] State the support boundary clearly.

### 6.2 Public positioning

- [ ] Position openMiura as a governed agent operations platform.
- [ ] Emphasize approvals, policies, evidence, rollout governance and operator control.
- [ ] Avoid chatbot-style positioning.
- [ ] Describe the current state as controlled release / RC / pilot as appropriate.

### 6.3 Operational handoff

- [ ] Share installation and release-candidate guides.
- [ ] Share support matrix and security guidance.
- [ ] Share rollback / restore path.
- [ ] Share known limitations honestly.

## 7. GO / NO-GO gate

### GO when

- required checks are green
- release artifacts are reproducible and verified
- docs and release notes match reality
- merge scope is clean and bounded
- publication posture is explicit

### NO-GO when

- release artifacts cannot be reproduced or verified
- the PR still contains local debris or ambiguous files
- product messaging drifts from the control-plane thesis
- reviewers cannot explain rollback, support scope or release evidence
