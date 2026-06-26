"""Signature-grade approvals — PR 3 (TOTP second factor).

TotpService wraps cryptography's built-in TOTP (no new dependency) and
persists the secret ENCRYPTED at rest via the AuditStore facade. These tests
pin: enrol → confirm → verify happy path, wrong-code rejection, the verify
gate (disabled until confirmed), the ±1-step skew window, encryption at rest
(no plaintext base32 in the DB), and fail-closed behaviour with no KEK.
"""
from __future__ import annotations

import base64

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.twofactor.totp import TOTP

from openmiura.application.auth.totp import TotpNotConfigured, TotpService
from openmiura.core.audit import AuditStore
from openmiura.core.migrations import apply_migrations

_KEK = "unit-test-key-encryption-key"


def _store(tmp_path) -> AuditStore:
    store = AuditStore(db_path=(tmp_path / "audit.db").as_posix(), backend="sqlite", database_url="")
    apply_migrations(store._conn)
    store.ensure_auth_user(username="alice", password="pw1", user_key="user:alice", role="approver")
    return store


def _code_at(secret_b32: str, t: int) -> str:
    raw = base64.b32decode(secret_b32)
    return TOTP(raw, 6, hashes.SHA1(), 30).generate(int(t)).decode("ascii")


def test_enroll_then_confirm_then_verify(tmp_path):
    store = _store(tmp_path)
    t = 1_700_000_000
    svc = TotpService(kek=_KEK, now=lambda: t)
    enrolled = svc.enroll(store, user_key="user:alice")
    assert enrolled["provisioning_uri"].startswith("otpauth://totp/")
    secret = enrolled["secret_b32"]

    # Not enabled until confirmed.
    assert svc.is_enabled(store, user_key="user:alice") is False
    assert svc.verify(store, user_key="user:alice", code=_code_at(secret, t)) is False

    assert svc.confirm(store, user_key="user:alice", code=_code_at(secret, t)) is True
    assert svc.is_enabled(store, user_key="user:alice") is True
    assert svc.verify(store, user_key="user:alice", code=_code_at(secret, t)) is True


def test_wrong_code_is_rejected(tmp_path):
    store = _store(tmp_path)
    t = 1_700_000_000
    svc = TotpService(kek=_KEK, now=lambda: t)
    secret = svc.enroll(store, user_key="user:alice")["secret_b32"]
    assert svc.confirm(store, user_key="user:alice", code="000000") is False
    # Confirm properly, then a wrong code at verify time still fails.
    svc.confirm(store, user_key="user:alice", code=_code_at(secret, t))
    assert svc.verify(store, user_key="user:alice", code="000000") is False


def test_skew_window_accepts_adjacent_step_rejects_far(tmp_path):
    store = _store(tmp_path)
    t = 1_700_000_000
    svc = TotpService(kek=_KEK, now=lambda: t)
    secret = svc.enroll(store, user_key="user:alice")["secret_b32"]
    svc.confirm(store, user_key="user:alice", code=_code_at(secret, t))
    # Previous 30s step is within the ±1 window...
    assert svc.verify(store, user_key="user:alice", code=_code_at(secret, t - 30)) is True
    # ...two steps away is not.
    assert svc.verify(store, user_key="user:alice", code=_code_at(secret, t - 90)) is False


def test_secret_is_encrypted_at_rest(tmp_path):
    store = _store(tmp_path)
    svc = TotpService(kek=_KEK, now=lambda: 1_700_000_000)
    secret = svc.enroll(store, user_key="user:alice")["secret_b32"]
    stored = store.get_user_otp(user_key="user:alice")["otp_secret_enc"]
    # The DB never holds the plaintext base32 secret.
    assert stored and stored != secret
    assert secret not in stored
    # A service with the same KEK can still decrypt+use it.
    assert svc._decrypt(stored) == secret


def test_wrong_kek_cannot_decrypt(tmp_path):
    """A rotated/wrong KEK is a loud configuration error, not a silent 'wrong
    code' — confirm/verify only swallow a wrong CODE (InvalidToken), so a bad
    KEK surfaces as a Fernet decrypt error rather than masking that 2FA is
    misconfigured."""
    from cryptography.fernet import InvalidToken as FernetInvalidToken

    store = _store(tmp_path)
    t = 1_700_000_000
    good = TotpService(kek=_KEK, now=lambda: t)
    secret = good.enroll(store, user_key="user:alice")["secret_b32"]
    good.confirm(store, user_key="user:alice", code=_code_at(secret, t))  # enable 2FA

    other = TotpService(kek="a-different-kek", now=lambda: t)
    with pytest.raises(FernetInvalidToken):
        other.verify(store, user_key="user:alice", code=_code_at(secret, t))


def test_no_kek_fails_closed(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENMIURA_OTP_KEK", raising=False)
    store = _store(tmp_path)
    svc = TotpService()  # reads env lazily; none set
    assert svc.is_configured() is False
    with pytest.raises(TotpNotConfigured):
        svc.enroll(store, user_key="user:alice")


def test_disable_forgets_secret(tmp_path):
    store = _store(tmp_path)
    t = 1_700_000_000
    svc = TotpService(kek=_KEK, now=lambda: t)
    secret = svc.enroll(store, user_key="user:alice")["secret_b32"]
    svc.confirm(store, user_key="user:alice", code=_code_at(secret, t))
    store.disable_user_otp(user_key="user:alice")
    rec = store.get_user_otp(user_key="user:alice")
    assert rec["otp_enabled"] is False
    assert rec["otp_secret_enc"] is None
    assert svc.verify(store, user_key="user:alice", code=_code_at(secret, t)) is False
