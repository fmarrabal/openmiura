# openMiura public-release audit

Date: 2026-03-23

## Scope

Final audit and cleanup of the uploaded `openMiuraV2Bundle.zip` to produce a GitHub-ready public bundle.

## Fix applied before publication

### Admin rate limiter state leak

A real defect was fixed in `openmiura/interfaces/http/routes/admin.py`.

Original behavior:
- the admin HTTP rate limiter used a module-level global bucket keyed only by client IP,
- different `TestClient` instances and app instances in the same process shared that state,
- later admin tests could fail with false `429 Admin rate limit exceeded` responses.

Applied correction:
- moved rate-limit buckets to `request.app.state.admin_rate_limit_buckets`,
- added an explicit lock for safe mutation,
- keyed the limiter by `app_id + token_prefix + client_ip`,
- preserved the public API behavior while removing cross-instance contamination.

This closes the failing admin validation path without changing endpoint contracts.

## Cleanup executed

Removed from the public tree:
- `.pytest_cache/`
- all `__pycache__/` directories
- all `*.pyc` and `*.pyo`
- generated `build/`
- generated `openmiura.egg-info/`
- runtime voice artifacts `data/voice_assets/*.wav`

Retained intentionally:
- source code, docs, tests, workflows and packaging files
- runtime folders under `data/` and `reports/`, kept empty through `.gitkeep`
- sanitized local startup examples in `arrancar_openmiura.txt`

## Validation executed

### Build/package sanity

- `python -m compileall -q openmiura app.py scripts` ✅
- `python -m pip wheel . --no-deps` ✅

### Test validation

- total discovered tests: **259**
- full test suite executed in two file chunks: ✅
- targeted regression suite for the previous failure cluster: ✅

Targeted regression files validated:
- `tests/test_phase8_pr5_live_canvas_admin.py`
- `tests/test_phase8_pr6_canvas_overlays_admin.py`
- `tests/test_phase8_pr7_canvas_collaboration_admin.py`
- `tests/test_phase8_pr8_packaging_hardening_admin.py`
- `tests/test_phase8_release_admin.py`
- `tests/test_phase9_operational_hardening_admin.py`

Additional phase 8/9 coverage re-run after the fix: ✅

## Secret scan note

A lightweight regex scan found only an intentional fake fixture in tests:
- `tests/test_phase7_secret_governance.py` with a synthetic GitHub token-like test value token pattern

No production secret-like value was found in repository files selected for publication.

## Release readiness conclusion

The cleaned tree is publishable.

No blocking implementation gap was found for the integrated Phase 1–9 bundle. The remaining work is non-blocking technical debt and future hardening, mainly:
- splitting very large modules such as `openmiura/core/audit.py`, `openmiura/application/admin/service.py` and `openmiura/interfaces/http/routes/admin.py`
- continuing operational hardening in real deployments
- enforcing GitHub branch protections, code scanning and secret scanning on the recreated repository
