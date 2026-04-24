# Release-candidate quickstart (RC1)

This quickstart is the shortest credible path to validating the RC1 bundle from a clean machine.

## 1. Prepare the environment

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install ".[dev]"
```

On Windows PowerShell, activate with:

```powershell
.\.venv\Scripts\Activate.ps1
```

## 2. Choose a baseline profile

For a serious local baseline:

```bash
cp ops/env/secure-default.env .env
```

For a more production-like local pilot:

```bash
cp ops/env/production-like.env .env
```

Review and change bootstrap credentials immediately.

## 3. Verify configuration

```bash
openmiura doctor --config configs/openmiura.yaml
```

Do not proceed until critical issues are resolved. Non-critical warnings such as an unavailable local LLM endpoint can be acceptable for documentation-only validation, but not for an actual pilot.

## 4. Start the service

```bash
openmiura run --config configs/openmiura.yaml
```

Alternative Docker path:

```bash
docker compose up --build -d
```

## 5. Check the key surfaces

- health: `http://localhost:8081/health`
- UI: `http://localhost:8081/ui`
- metrics: `http://localhost:8081/metrics`

## 6. Exercise the minimum RC path

1. log in to the UI
2. open Config Center and confirm the loaded config
3. inspect the secrets/env references UI
4. confirm the channel setup wizard renders
5. trigger one approval-requiring or audited administrative flow
6. inspect an operator/admin timeline or audit view

## 7. Run the release-quality gate

```bash
python scripts/run_release_quality_gate.py --include-extended --output-dir reports/quality_gate
```

## 8. Freeze the candidate bundle

```bash
python scripts/freeze_release_candidate.py --output-dir dist/rc --label rc1 --version 1.0.0-rc1
```

The distribution handoff should include:

- the frozen RC zip
- the RC manifest
- `RELEASE_NOTES_RC1.md`
- `docs/release_support_matrix.md`
- `docs/alpha_release_checklist.md`

RC1 is the validation checkpoint, not the canonical GitHub Release asset line. The stable `v1.0.0` publication path is defined in `docs/release_publication.md`.
