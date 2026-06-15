"""Audit hash-chain — PR 5 (attest chain heads in evidence packs).

The chain HEAD per (chained table, scope) is now embedded as a signed
chain-of-custody event in the portfolio evidence pack, so `openmiura
verify` records what the head was and who signed it; `openmiura db
verify-chain` then proves the live DB still hashes to it. This closes the
pack <-> DB loop with no change to the offline verifier.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import app as app_module
from openmiura.gateway import Gateway
from openmiura.persistence.base import canonical_chain_scope
from tests.test_openclaw_portfolio_evidence_packaging_v2 import (
    _create_runtime,
    _create_submitted_portfolio,
    _set_now,
    _write_config,
)


def _export_with_logged_events(tmp_path: Path, monkeypatch):
    base_now = 1_784_800_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / "openmiura.yaml"
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {"Authorization": "Bearer secret-admin"}
    with TestClient(app) as client:
        gw = app.state.gw
        runtime_id = _create_runtime(client, headers, name="runtime-pr5")
        portfolio_id = _create_submitted_portfolio(
            client, headers, base_now=base_now, runtime_id=runtime_id,
            export_policy={"enabled": True, "require_signature": True, "signer_key_id": "pr5-ci", "timeline_limit": 120},
        )
        # Log an event under the release scope so the events chain has a head.
        gw.audit.log_event("in", "http", "u", "s-pr5", {"k": "v"},
                           tenant_id="tenant-a", workspace_id="ws-a", environment="prod")
        head = gw.audit._conn.cursor().execute(
            "SELECT head_hash, head_seq FROM audit_chain_heads WHERE chain_table='events' AND chain_scope=?",
            (canonical_chain_scope("tenant-a", "ws-a", "prod"),),
        ).fetchone()
        export = client.post(
            f"/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-package-export",
            headers=headers,
            json={"actor": "auditor", "tenant_id": "tenant-a", "workspace_id": "ws-a", "environment": "prod"},
        )
        assert export.status_code == 200, export.text
        return export.json(), (head["head_hash"] if head else None)


def test_pack_attests_audit_chain_head(tmp_path, monkeypatch):
    payload, head_hash = _export_with_logged_events(tmp_path, monkeypatch)
    assert head_hash, "events chain head should exist for the scope"

    custody = (payload["package"].get("chain_of_custody") or {})
    entries = custody.get("entries") or []
    matched = [
        e for e in entries
        if e.get("event_type") == "audit_chain_head"
        and (e.get("metadata") or {}).get("chain_table") == "events"
    ]
    assert matched, (
        "expected an audit_chain_head custody entry for events; entries="
        f"{[(e.get('event_type'), (e.get('metadata') or {}).get('chain_table')) for e in entries]}"
    )
    assert matched[0]["metadata"]["head_hash"] == head_hash
    # The whole custody chain still verifies internally.
    assert custody.get("summary", {}).get("valid") is True


def test_pack_offline_verifier_accepts_audit_chain_head(tmp_path, monkeypatch):
    """The embedded audit_chain_head events must not break the offline
    pack verifier — it validates the custody chain generically."""
    import base64
    from openmiura import evidence_verify

    payload, _ = _export_with_logged_events(tmp_path, monkeypatch)
    content_b64 = payload["artifact"]["content_b64"]
    pack = tmp_path / "pack.zip"
    pack.write_bytes(base64.b64decode(content_b64.encode("ascii")))
    result = evidence_verify.verify_pack(pack)
    assert result["ok"] is True
    # chain_of_custody is verified offline by the existing verifier.
    assert result["details"]["chain_of_custody"] is None or result["details"]["chain_of_custody"]["valid"] is True
