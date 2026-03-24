# Phase 9 operational hardening audit

## Scope

This increment hardens three phase-8 gaps:

- Real voice path with audio assets and provider-call traces
- Percentage canary routing with stable-hash assignment and observation capture
- Reproducible CI/CD packaging with deterministic ZIP creation and manifest verification

## Implemented changes

### Voice
- `voice_audio_assets`
- `voice_provider_calls`
- local STT/TTS provider adapters
- audio transcription endpoint
- TTS audio persistence with `audio_ref`

### Canary
- `release_routing_decisions`
- canary activation with gate blocker checks
- stable percentage routing
- observation updates and routing summary

### Packaging
- deterministic manifest generation
- deterministic ZIP packaging
- manifest verification
- CI workflow `package-reproducible.yml`
- packaging script `scripts/reproducible_package.py`

## Validation executed

- `python -m compileall -q app.py openmiura tests`
- `node --check openmiura/ui/static/app.js`
- `pytest -q tests/test_phase9_operational_hardening_voice.py tests/test_phase9_operational_hardening_canary.py tests/test_phase9_operational_hardening_packaging.py tests/test_phase9_operational_hardening_admin.py tests/test_db_migrations.py`
- `pytest -q tests/test_phase8_pr2_release_governance.py tests/test_phase8_pr2_release_governance_admin.py tests/test_phase8_pr3_voice_runtime.py tests/test_phase8_pr3_voice_runtime_admin.py tests/test_phase8_pr8_packaging_hardening.py tests/test_phase8_pr8_packaging_hardening_admin.py tests/test_phase8_pr8_release_voice_canvas_smoke.py`

## Result

All listed validation commands passed.
