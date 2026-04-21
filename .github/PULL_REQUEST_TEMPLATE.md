## Summary

Describe the change in 3-8 bullets. Keep the scope explicit and non-aspirational.

## Type of change

- [ ] Release hygiene / packaging
- [ ] Documentation only
- [ ] Bug fix
- [ ] Security hardening
- [ ] UI / operability improvement
- [ ] Governance / approvals / evidence
- [ ] Other:

## Scope boundaries

State what this PR intentionally does **not** change.

## Validation executed

Paste the exact commands you ran.

```bash
# example
python -m pytest -q
```

## Required checks

- [ ] `ci` is green
- [ ] `package-reproducible` is green
- [ ] `security` is green
- [ ] `dependency-review` is green when applicable
- [ ] `python scripts/run_release_quality_gate.py --include-extended --output-dir reports/quality_gate` passed locally or the deviation is explained
- [ ] `python scripts/build_release_artifacts.py --dist-dir dist --tag <tag> --target desktop --strict` passed locally or the deviation is explained
- [ ] `python scripts/verify_release_artifacts.py --dist-dir dist` passed locally or the deviation is explained

## Release hygiene

- [ ] Working tree reviewed for local artifacts, caches and transient files
- [ ] No secrets or `.env` content are included
- [ ] Release notes updated when behavior changed
- [ ] Docs updated when operator or deployment behavior changed
- [ ] Backward compatibility / migration impact reviewed

## Governance impact

- [ ] No governance behavior changed
- [ ] Governance behavior changed and approvals/policies/evidence implications were reviewed
- [ ] Baseline / rollout / attestation / replay implications were reviewed

## Risk and rollback

Describe the main operational risk and the rollback path.

## Checklist for reviewers

- [ ] Scope is coherent and minimal
- [ ] Validation is sufficient for the risk of the change
- [ ] Documentation matches the implementation
- [ ] Release posture remains secure-by-default
