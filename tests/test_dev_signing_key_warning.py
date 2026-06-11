"""The built-in evidence-signing seed must not masquerade as a
real signature.

openMiura signs portfolio evidence packs with ed25519. When no real
key is configured (no PEM, no KMS/HSM provider, no custom
OPENMIURA_EVIDENCE_SIGNING_SEED) it falls back to a key derived from
a PUBLIC, hardcoded development seed — anyone with the source can
reproduce that private key and forge a "signature". For a governance
plane whose whole value is auditable, non-repudiable evidence, a
forgeable default that *looks* signed is a disqualifying trap.

The fix is additive and honest: when the built-in dev seed is in use
and the operator hasn't explicitly opted in
(OPENMIURA_ALLOW_DEV_SIGNING_KEY), the signed integrity block is
stamped dev_signing_key=true + a signing_warning, so an auditor
reading the pack is never misled. The signature itself is unchanged.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import app as app_module
from openmiura.gateway import Gateway
from tests.test_openclaw_portfolio_evidence_packaging_v2 import (
    _create_runtime,
    _create_submitted_portfolio,
    _set_now,
    _write_config,
)

_SIGNING_ENVS = (
    "OPENMIURA_EVIDENCE_SIGNING_SEED",
    "OPENMIURA_EVIDENCE_SIGNING_PRIVATE_KEY_PEM_B64",
    "OPENMIURA_EVIDENCE_SIGNING_PRIVATE_KEY_PEM_PATH",
)


def _export_integrity(tmp_path: Path, monkeypatch) -> dict:
    base_now = 1_784_790_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / "openmiura.yaml"
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {"Authorization": "Bearer secret-admin"}
    with TestClient(app) as client:
        runtime_id = _create_runtime(client, headers, name="runtime-dev-signing")
        portfolio_id = _create_submitted_portfolio(
            client,
            headers,
            base_now=base_now,
            runtime_id=runtime_id,
            export_policy={
                "enabled": True,
                "require_signature": True,
                "signer_key_id": "dev-signing-ci",
                "timeline_limit": 120,
                "embed_artifact_content": False,
            },
        )
        export = client.post(
            f"/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-package-export",
            headers=headers,
            json={"actor": "auditor", "tenant_id": "tenant-a", "workspace_id": "ws-a", "environment": "prod"},
        )
        assert export.status_code == 200, export.text
        return export.json()["integrity"]


def test_default_dev_seed_marks_signature_non_authoritative(tmp_path: Path, monkeypatch) -> None:
    for v in _SIGNING_ENVS + ("OPENMIURA_ALLOW_DEV_SIGNING_KEY",):
        monkeypatch.delenv(v, raising=False)

    integ = _export_integrity(tmp_path, monkeypatch)

    assert integ["signature_scheme"] == "ed25519"
    pk = integ["public_key"]
    assert pk["origin"] == "derived_seed"
    # The forgeable dev seed is flagged, loudly.
    assert pk.get("dev_signing_key") is True
    assert "signing_warning" in pk
    assert "not authoritative" in pk["signing_warning"].lower()


def test_opt_in_env_suppresses_dev_seed_warning(tmp_path: Path, monkeypatch) -> None:
    for v in _SIGNING_ENVS:
        monkeypatch.delenv(v, raising=False)
    # Operator consciously accepts the dev key (e.g. local dev).
    monkeypatch.setenv("OPENMIURA_ALLOW_DEV_SIGNING_KEY", "1")

    integ = _export_integrity(tmp_path, monkeypatch)

    pk = integ["public_key"]
    assert pk["origin"] == "derived_seed"
    assert "dev_signing_key" not in pk
    assert "signing_warning" not in pk


def test_custom_seed_is_not_flagged_as_dev_default(tmp_path: Path, monkeypatch) -> None:
    for v in _SIGNING_ENVS + ("OPENMIURA_ALLOW_DEV_SIGNING_KEY",):
        monkeypatch.delenv(v, raising=False)
    # A custom (non-public) seed is the operator's deliberate choice;
    # it is still derived_seed but must NOT carry the dev warning.
    monkeypatch.setenv("OPENMIURA_EVIDENCE_SIGNING_SEED", "an-operator-chosen-private-seed-value")

    integ = _export_integrity(tmp_path, monkeypatch)

    pk = integ["public_key"]
    assert pk["origin"] == "derived_seed"
    assert "dev_signing_key" not in pk
    assert "signing_warning" not in pk
