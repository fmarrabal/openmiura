"""Signature-grade approvals — PR 7 (TOTP single-use).

Migration 28 adds ``otp_consumed_steps``; TotpService.verify now claims the
code's generation time-step single-use, so an intercepted code cannot be
replayed (e.g. to approve a second release) within its window. Enrolment
confirm does NOT consume, so a freshly enrolled code still works once.
"""
from __future__ import annotations

import base64
import time
import types

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.twofactor.totp import TOTP

from openmiura.application.auth.totp import TotpService
from openmiura.application.releases.service import ReleaseService
from openmiura.core.audit import AuditStore
from openmiura.core.migrations import MIGRATIONS, apply_migrations

_KEK = "pr7-kek"


def _store(tmp_path):
    store = AuditStore(db_path=(tmp_path / "audit.db").as_posix(), backend="sqlite", database_url="")
    apply_migrations(store._conn)
    return store


def _code_at(secret_b32: str, t: int) -> str:
    raw = base64.b32decode(secret_b32)
    return TOTP(raw, 6, hashes.SHA1(), 30).generate(int(t)).decode("ascii")


def test_migration_28_registered():
    by_version = {m.version: m for m in MIGRATIONS}
    assert 28 in by_version and by_version[28].name == "otp_single_use"


def test_otp_consumed_steps_table_exists(tmp_path):
    store = _store(tmp_path)
    assert store._conn.cursor().execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='otp_consumed_steps'"
    ).fetchone() is not None


def test_code_is_single_use(tmp_path):
    store = _store(tmp_path)
    store.ensure_auth_user(username="carol", password="pw", user_key="user:carol", role="approver")
    t = 1_700_000_000
    svc = TotpService(kek=_KEK, now=lambda: t)
    secret = svc.enroll(store, user_key="user:carol")["secret_b32"]
    svc.confirm(store, user_key="user:carol", code=_code_at(secret, t))  # does NOT consume
    code = _code_at(secret, t)
    assert svc.verify(store, user_key="user:carol", code=code) is True   # claims the step
    assert svc.verify(store, user_key="user:carol", code=code) is False  # replay rejected


def test_consume_step_is_per_user(tmp_path):
    store = _store(tmp_path)
    assert store.consume_otp_step(user_key="user:a", time_step=42) is True
    assert store.consume_otp_step(user_key="user:a", time_step=42) is False  # same user+step → replay
    assert store.consume_otp_step(user_key="user:b", time_step=42) is True   # different user is independent


def _gw(tmp_path):
    store = _store(tmp_path)
    return types.SimpleNamespace(audit=store), store


def _submitted(store):
    rid = store.create_release_bundle(kind="agent", name="svc", version="1.0.0", created_by="user:alice")["release_id"]
    store.submit_release_bundle(rid, actor="user:bob", reason="ready")
    return rid


def test_same_code_cannot_approve_two_releases(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENMIURA_OTP_KEK", _KEK)
    gw, store = _gw(tmp_path)
    store.ensure_auth_user(username="carol", password="pw", user_key="user:carol", role="approver")
    t = 1_700_000_000
    svc = TotpService(kek=_KEK, now=lambda: t)
    secret = svc.enroll(store, user_key="user:carol")["secret_b32"]
    svc.confirm(store, user_key="user:carol", code=_code_at(secret, t))

    rid1, rid2 = _submitted(store), _submitted(store)
    code = _code_at(secret, t)
    # cast_release_approval_vote builds its own TotpService() (reads env KEK +
    # real clock); to keep the matched step deterministic we pin the code to the
    # current real step.
    code = _code_at(secret, int(time.time()))
    out1 = ReleaseService().cast_release_approval_vote(gw, release_id=rid1, actor="user:carol", otp_code=code)
    assert out1["quorum_met"] is True
    # Replaying the same code on a second release is rejected (single-use).
    with pytest.raises(PermissionError):
        ReleaseService().cast_release_approval_vote(gw, release_id=rid2, actor="user:carol", otp_code=code)
