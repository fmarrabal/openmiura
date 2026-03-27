# Enterprise Alpha release checklist

Use this checklist before distributing a self-hosted Enterprise Alpha build of openMiura.

## 1. Source and workflow checks

- [ ] The working tree is clean and the intended branch/tag is identified.
- [ ] Critical GitHub workflows pass, especially `ci`, `package-reproducible` and `release`-related checks.
- [ ] The local package installation contract is still consistent across workflows.

## 2. Packaging and artifact validation

- [ ] `python -m build --sdist --wheel` completes successfully.
- [ ] `python scripts/reproducible_package.py --target desktop --label "Enterprise Alpha" --version alpha --output-dir dist` completes successfully.
- [ ] `python scripts/build_release_artifacts.py --dist-dir dist --tag v-alpha --target desktop --strict` completes successfully.
- [ ] `python scripts/verify_release_artifacts.py --dist-dir dist` succeeds.
- [ ] `SHA256SUMS.txt` exists in `dist/`.
- [ ] `RELEASE_MANIFEST.json` exists in `dist/`.
- [ ] Wheel, sdist and reproducible bundle are all present.

## 3. Installation validation

- [ ] `.env` is prepared from `.env.example` and bootstrap credentials were changed from defaults.
- [ ] `docker compose up --build -d` succeeds on a clean host or VM.
- [ ] `docker compose --profile observability up --build -d` was tested if observability is part of the handoff.
- [ ] `/health` responds correctly.
- [ ] `/ui` is reachable.
- [ ] `openmiura doctor --config configs/` reports no critical setup problems.

## 4. Governance validation

- [ ] Tenant / workspace / environment isolation has been sanity-checked in the target configuration.
- [ ] RBAC roles are configured intentionally and broad admin sharing has been avoided.
- [ ] At least one approval-requiring flow was exercised.
- [ ] At least one audit trail / operator timeline was inspected.
- [ ] Secret references were tested without exposing cleartext secrets in prompts or logs.
- [ ] If OpenClaw is part of the pilot, one governed runtime dispatch was validated.

## 5. Security and operations checks

- [ ] Reverse proxy / TLS plan is defined for any non-localhost deployment.
- [ ] Sensitive broker/admin endpoints are not being casually exposed.
- [ ] Metrics and observability endpoints are protected or kept internal.
- [ ] Backup location for `data/` is defined.
- [ ] Initial rollback / restore path is understood.

## 6. Documentation and communication

- [ ] The recipient receives `docs/enterprise_alpha.md`.
- [ ] The recipient receives this checklist or an equivalent signed-off copy.
- [ ] Known risks and limitations have been stated explicitly.
- [ ] The alpha is presented as a controlled pilot, not a GA promise.
- [ ] Support expectations, contact point and pilot boundaries are clear.

## 7. Go / no-go decision

Mark the release as ready only when all mandatory checks above are complete.

- [ ] GO for controlled alpha distribution
- [ ] NO-GO until issues are fixed and revalidated
