# Phase 9 — Operational hardening

This increment closes three production gaps left intentionally open in phase 8:

1. Real voice I/O path with auditable audio assets and provider calls.
2. Percentage canary routing using stable-hash assignment plus observed results.
3. Reproducible CI/CD packaging with deterministic ZIP generation and manifest verification.

## Voice runtime hardening

- New audio asset registry: `voice_audio_assets`
- New provider-call audit trail: `voice_provider_calls`
- New endpoints for audio-based STT ingestion
- Deterministic local TTS WAV synthesis for environments without external vendors
- Optional webhook-based STT/TTS providers through environment variables

## Canary hardening

- Active canary state now supports stable-hash percentage routing.
- New decision registry: `release_routing_decisions`
- Observations can be attached to each routing decision to track latency, cost and success.

## Packaging hardening

- Deterministic package manifest generation with file-level SHA256 digests
- Deterministic ZIP creation with fixed timestamps and sorted entries
- GitHub Actions workflow: `.github/workflows/package-reproducible.yml`
- Verification endpoint/script for manifest replay
