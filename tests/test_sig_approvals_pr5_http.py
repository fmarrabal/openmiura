"""Signature-grade approvals — PR 5 (HTTP wiring).

The /admin/releases/{id}/approve route now dispatches: with a quorum policy
configured it runs the strict signature-grade path (identity + anti-self +
TOTP + n-of-m quorum), otherwise the legacy single-approver path — so existing
deployments are unchanged and signature-grade is opt-in per release. New
endpoints configure the quorum and enrol/confirm a TOTP second factor.
"""
from __future__ import annotations

import base64
import time
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.twofactor.totp import TOTP
from fastapi.testclient import TestClient

import app as app_module
from openmiura.gateway import Gateway

_H = {"Authorization": "Bearer secret-admin"}


def _write_config(path: Path) -> None:
    db_path = (path.parent / "audit.db").as_posix()
    sandbox_dir = (path.parent / "sandbox").as_posix()
    path.write_text(
        f'''\
server:
  host: "127.0.0.1"
  port: 8081
storage:
  db_path: "{db_path}"
llm:
  provider: "ollama"
  base_url: "http://127.0.0.1:11434"
  model: "qwen2.5:7b-instruct"
tools:
  sandbox_dir: "{sandbox_dir}"
admin:
  enabled: true
  token: secret-admin
auth:
  enabled: true
''',
        encoding="utf-8",
    )


def _app(tmp_path: Path):
    cfg = tmp_path / "openmiura.yaml"
    _write_config(cfg)
    return app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)


def _make_release(client: TestClient, *, created_by: str, submitter: str) -> str:
    created = client.post(
        "/admin/releases",
        headers=_H,
        json={"kind": "workflow", "name": "svc", "version": "1.0.0", "created_by": created_by,
              "items": [{"item_kind": "workflow", "item_key": "k", "item_version": "1.0.0", "payload": {}}]},
    )
    assert created.status_code == 200, created.text
    rid = created.json()["release"]["release_id"]
    assert client.post(f"/admin/releases/{rid}/submit", headers=_H, json={"actor": submitter}).status_code == 200
    return rid


def _code_now(secret_b32: str) -> str:
    raw = base64.b32decode(secret_b32)
    return TOTP(raw, 6, hashes.SHA1(), 30).generate(int(time.time())).decode("ascii")


def test_legacy_dispatch_unchanged_without_quorum(tmp_path):
    """No quorum policy → legacy path: the same admin can approve (200)."""
    with TestClient(_app(tmp_path)) as client:
        rid = _make_release(client, created_by="admin", submitter="admin")
        r = client.post(f"/admin/releases/{rid}/approve", headers=_H, json={"actor": "admin"})
        assert r.status_code == 200, r.text
        assert client.app.state.gw.audit.get_release_bundle(rid)["status"] == "approved"


def test_strict_dispatch_blocks_self_approval(tmp_path):
    """With a quorum policy, the strict path runs and the creator/submitter is
    rejected with 403."""
    with TestClient(_app(tmp_path)) as client:
        rid = _make_release(client, created_by="user:carol", submitter="user:carol")
        assert client.post(f"/admin/releases/{rid}/quorum", headers=_H, json={"required_n": 2}).status_code == 200
        r = client.post(f"/admin/releases/{rid}/approve", headers=_H, json={"actor": "user:carol"})
        assert r.status_code == 403, r.text


def test_strict_quorum_two_distinct_approvers(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        store = client.app.state.gw.audit
        for name in ("carol", "dave"):
            store.ensure_auth_user(username=name, password="pw", user_key=f"user:{name}", role="approver")
        rid = _make_release(client, created_by="user:alice", submitter="user:bob")
        assert client.post(f"/admin/releases/{rid}/quorum", headers=_H, json={"required_n": 2}).status_code == 200

        first = client.post(f"/admin/releases/{rid}/approve", headers=_H, json={"actor": "user:carol"})
        assert first.status_code == 200, first.text
        assert first.json()["quorum_met"] is False
        assert store.get_release_bundle(rid)["status"] == "pending_approval"

        second = client.post(f"/admin/releases/{rid}/approve", headers=_H, json={"actor": "user:dave"})
        assert second.status_code == 200
        assert second.json()["quorum_met"] is True
        assert store.get_release_bundle(rid)["status"] == "approved"


def test_unknown_approver_rejected_in_strict(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        rid = _make_release(client, created_by="user:alice", submitter="user:bob")
        client.post(f"/admin/releases/{rid}/quorum", headers=_H, json={"required_n": 2})
        r = client.post(f"/admin/releases/{rid}/approve", headers=_H, json={"actor": "ghost"})
        assert r.status_code == 403, r.text


def test_otp_enroll_confirm_and_required_for_approval(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENMIURA_OTP_KEK", "pr5-kek")
    with TestClient(_app(tmp_path)) as client:
        store = client.app.state.gw.audit
        store.ensure_auth_user(username="carol", password="pw", user_key="user:carol", role="approver")

        enroll = client.post("/admin/auth/otp/enroll", headers=_H, json={"user_key": "user:carol"})
        assert enroll.status_code == 200, enroll.text
        secret = enroll.json()["secret_b32"]
        assert enroll.json()["provisioning_uri"].startswith("otpauth://totp/")
        assert client.post("/admin/auth/otp/confirm", headers=_H, json={"user_key": "user:carol", "code": _code_now(secret)}).status_code == 200

        rid = _make_release(client, created_by="user:alice", submitter="user:bob")
        client.post(f"/admin/releases/{rid}/quorum", headers=_H, json={"required_n": 1})
        # Carol has 2FA enabled → approval without a code is rejected.
        assert client.post(f"/admin/releases/{rid}/approve", headers=_H, json={"actor": "user:carol"}).status_code == 403
        # With a valid code → approved.
        ok = client.post(f"/admin/releases/{rid}/approve", headers=_H, json={"actor": "user:carol", "otp_code": _code_now(secret)})
        assert ok.status_code == 200, ok.text
        assert ok.json()["quorum_met"] is True


def test_otp_enroll_fails_closed_without_kek(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENMIURA_OTP_KEK", raising=False)
    with TestClient(_app(tmp_path)) as client:
        client.app.state.gw.audit.ensure_auth_user(username="carol", password="pw", user_key="user:carol", role="approver")
        r = client.post("/admin/auth/otp/enroll", headers=_H, json={"user_key": "user:carol"})
        assert r.status_code == 503, r.text
