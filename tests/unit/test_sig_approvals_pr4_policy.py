"""Signature-grade approvals — PR 4 (enforcement core).

ReleaseService.cast_release_approval_vote is the strict counterpart to the
legacy approve_release: it resolves the actor to a real identity, blocks the
creator/submitter from self-approving and any signer from voting twice,
requires a TOTP second factor from signers who have 2FA enabled, and only
flips the release to ``approved`` once the per-release n-of-m quorum of
DISTINCT approvers is met. With no quorum policy it defaults to n=1, so the
legacy single-approver behaviour (and existing tests) are preserved.
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
from openmiura.core.migrations import apply_migrations
from openmiura.persistence.hashchain import verify_audit_chain

_KEK = "pr4-kek"


def _gw(tmp_path):
    store = AuditStore(db_path=(tmp_path / "audit.db").as_posix(), backend="sqlite", database_url="")
    apply_migrations(store._conn)
    return types.SimpleNamespace(audit=store), store


def _submitted_release(store, *, created_by="user:alice", submitter="user:bob"):
    bundle = store.create_release_bundle(kind="agent", name="svc", version="1.0.0", created_by=created_by)
    rid = bundle["release_id"]
    store.submit_release_bundle(rid, actor=submitter, reason="ready")
    return rid


def _code_now(secret_b32: str) -> str:
    raw = base64.b32decode(secret_b32)
    return TOTP(raw, 6, hashes.SHA1(), 30).generate(int(time.time())).decode("ascii")


# ==================================================================
# Default (no quorum policy) → n=1, legacy-compatible.
# ==================================================================


def test_single_distinct_approver_approves(tmp_path):
    gw, store = _gw(tmp_path)
    rid = _submitted_release(store)
    out = ReleaseService().cast_release_approval_vote(gw, release_id=rid, actor="user:carol")
    assert out["quorum_met"] is True
    assert out["votes_required"] == 1
    assert store.get_release_bundle(rid)["status"] == "approved"
    assert verify_audit_chain(store._conn, chain_table="release_approvals")["any_tamper"] is False


def test_creator_cannot_self_approve(tmp_path):
    gw, store = _gw(tmp_path)
    rid = _submitted_release(store, created_by="user:alice")
    with pytest.raises(PermissionError):
        ReleaseService().cast_release_approval_vote(gw, release_id=rid, actor="user:alice")


def test_submitter_cannot_self_approve(tmp_path):
    gw, store = _gw(tmp_path)
    rid = _submitted_release(store, submitter="user:bob")
    with pytest.raises(PermissionError):
        ReleaseService().cast_release_approval_vote(gw, release_id=rid, actor="user:bob")


def test_submitter_cannot_self_approve_across_identity_forms(tmp_path):
    """SoD must canonicalize identities: submitting under a username and
    approving under the matching user_key (or vice-versa) is still self-approval."""
    gw, store = _gw(tmp_path)
    store.ensure_auth_user(username="bob", password="pw", user_key="user:bob", role="approver")
    # Submit under the bare username...
    rid = _submitted_release(store, created_by="user:alice", submitter="bob")
    # ...approve under the user_key — must be rejected.
    with pytest.raises(PermissionError):
        ReleaseService().cast_release_approval_vote(gw, release_id=rid, actor="user:bob")


def test_creator_cannot_self_approve_across_identity_forms(tmp_path):
    gw, store = _gw(tmp_path)
    store.ensure_auth_user(username="alice", password="pw", user_key="user:alice", role="approver")
    # Created under the user_key, approve under the username → rejected.
    rid = _submitted_release(store, created_by="user:alice", submitter="user:bob")
    with pytest.raises(PermissionError):
        ReleaseService().cast_release_approval_vote(gw, release_id=rid, actor="alice")


# ==================================================================
# Quorum policy (strict): n-of-m distinct registered approvers.
# ==================================================================


def test_quorum_requires_two_distinct_approvers(tmp_path):
    gw, store = _gw(tmp_path)
    for name in ("carol", "dave"):
        store.ensure_auth_user(username=name, password="pw", user_key=f"user:{name}", role="approver")
    rid = _submitted_release(store)
    store.set_release_quorum(release_id=rid, required_n=2)

    first = ReleaseService().cast_release_approval_vote(gw, release_id=rid, actor="user:carol")
    assert first["quorum_met"] is False
    assert first["votes_remaining"] == 1
    assert store.get_release_bundle(rid)["status"] == "pending_approval"

    second = ReleaseService().cast_release_approval_vote(gw, release_id=rid, actor="user:dave")
    assert second["quorum_met"] is True
    assert store.get_release_bundle(rid)["status"] == "approved"
    assert verify_audit_chain(store._conn, chain_table="release_approvals")["any_tamper"] is False


def test_same_signer_cannot_vote_twice(tmp_path):
    gw, store = _gw(tmp_path)
    store.ensure_auth_user(username="carol", password="pw", user_key="user:carol", role="approver")
    rid = _submitted_release(store)
    store.set_release_quorum(release_id=rid, required_n=2)
    ReleaseService().cast_release_approval_vote(gw, release_id=rid, actor="user:carol")
    with pytest.raises(PermissionError):
        ReleaseService().cast_release_approval_vote(gw, release_id=rid, actor="user:carol")


def test_unknown_approver_rejected_in_strict_mode(tmp_path):
    gw, store = _gw(tmp_path)
    rid = _submitted_release(store)
    store.set_release_quorum(release_id=rid, required_n=2)
    with pytest.raises(PermissionError):
        ReleaseService().cast_release_approval_vote(gw, release_id=rid, actor="ghost")


# ==================================================================
# Second factor.
# ==================================================================


def test_totp_required_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENMIURA_OTP_KEK", _KEK)
    gw, store = _gw(tmp_path)
    store.ensure_auth_user(username="carol", password="pw", user_key="user:carol", role="approver")
    totp = TotpService()  # reads env KEK
    secret = totp.enroll(store, user_key="user:carol")["secret_b32"]
    totp.confirm(store, user_key="user:carol", code=_code_now(secret))

    rid = _submitted_release(store)
    # Missing / wrong code → rejected.
    with pytest.raises(PermissionError):
        ReleaseService().cast_release_approval_vote(gw, release_id=rid, actor="user:carol")
    # Valid code → approved, second factor recorded.
    out = ReleaseService().cast_release_approval_vote(
        gw, release_id=rid, actor="user:carol", otp_code=_code_now(secret)
    )
    assert out["quorum_met"] is True
    assert out["second_factor"] == "totp"
    votes = store.list_release_approval_votes(release_id=rid)
    assert votes and votes[-1]["second_factor_method"] == "totp"
    assert votes[-1]["otp_verified_at"] is not None


# ==================================================================
# Legacy approve_release path is untouched.
# ==================================================================


def test_legacy_approve_release_still_accepts_any_actor(tmp_path):
    gw, store = _gw(tmp_path)
    rid = _submitted_release(store)
    out = ReleaseService().approve_release(gw, release_id=rid, actor="whoever")
    assert out["ok"] is True
    assert store.get_release_bundle(rid)["status"] == "approved"
