"""TOTP second factor for signature-grade approvals.

A thin wrapper over ``cryptography``'s built-in
``cryptography.hazmat.primitives.twofactor.totp.TOTP`` — the SAME library
that already backs evidence-pack signing, so this adds NO new dependency.

Secrets at rest: the base32 TOTP secret is NEVER stored in plaintext. It is
encrypted with a key derived from an operator-provided key-encryption key
(env ``OPENMIURA_OTP_KEK``). If no KEK is configured, enrolment/verification
fail closed (``TotpNotConfigured``) rather than persisting a usable secret a
DB read would expose — a second factor stored in the clear is not a second
factor.

Replay note: ``verify`` accepts a ±1 time-step window for clock skew. It does
NOT enforce single-use of a code. The distinct-signer quorum stops the same
signer voting twice on one release, but a code could in principle be reused on
a *different* release within its ~60 s window. Global single-use (consumed
time-step tracking) is a known limitation, deferred to the HTTP-facing PR where
an intercepted code becomes externally replayable.
"""
from __future__ import annotations

import base64
import hashlib
import os
import time
from typing import Any, Callable

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.twofactor import InvalidToken
from cryptography.hazmat.primitives.twofactor.totp import TOTP

_KEK_ENV = "OPENMIURA_OTP_KEK"
_DIGITS = 6
_STEP_SECONDS = 30
_DEFAULT_SKEW_STEPS = 1  # ±1 step (±30 s) tolerance for clock drift


class TotpNotConfigured(RuntimeError):
    """Raised when TOTP is used but no key-encryption key is configured."""


class TotpService:
    """Stateless helper. Persistence goes through a ``store`` exposing
    ``set_user_otp_secret`` / ``mark_user_otp_confirmed`` / ``get_user_otp``
    (the AuditStore facade satisfies this)."""

    def __init__(self, *, kek: str | None = None, now: Callable[[], float] = time.time) -> None:
        # ``kek`` overrides the env var (tests / explicit wiring); otherwise the
        # env is read lazily at call time so the process can be configured late.
        self._kek_override = kek
        self._now = now

    # --- key management ----------------------------------------------------
    def _kek(self) -> str:
        kek = self._kek_override if self._kek_override is not None else os.environ.get(_KEK_ENV, "")
        if not kek:
            raise TotpNotConfigured(
                f"{_KEK_ENV} is not set; TOTP enrolment is disabled "
                "(refusing to store a second-factor secret unencrypted)"
            )
        return kek

    def is_configured(self) -> bool:
        try:
            self._kek()
            return True
        except TotpNotConfigured:
            return False

    def _fernet(self) -> Fernet:
        # Derive a Fernet (AES-128-CBC + HMAC) key from the high-entropy KEK.
        key = base64.urlsafe_b64encode(hashlib.sha256(self._kek().encode("utf-8")).digest())
        return Fernet(key)

    def _encrypt(self, secret_b32: str) -> str:
        return self._fernet().encrypt(secret_b32.encode("ascii")).decode("ascii")

    def _decrypt(self, token: str) -> str:
        return self._fernet().decrypt(token.encode("ascii")).decode("ascii")

    # --- TOTP primitive ----------------------------------------------------
    @staticmethod
    def _totp(secret_b32: str) -> TOTP:
        raw = base64.b32decode(secret_b32)
        return TOTP(raw, _DIGITS, hashes.SHA1(), _STEP_SECONDS)

    def _verify_code(self, secret_b32: str, code: str, *, skew_steps: int = _DEFAULT_SKEW_STEPS) -> bool:
        totp = self._totp(secret_b32)
        code_b = str(code or "").strip().encode("ascii")
        if not code_b:
            return False
        now = int(self._now())
        for offset in range(-skew_steps, skew_steps + 1):
            try:
                totp.verify(code_b, now + offset * _STEP_SECONDS)
                return True
            except InvalidToken:
                continue
        return False

    # --- lifecycle ---------------------------------------------------------
    def enroll(self, store: Any, *, user_key: str, account_name: str | None = None, issuer: str = "openMiura") -> dict[str, Any]:
        """Generate a new secret, persist it ENCRYPTED (2FA still disabled
        until confirmed), and return the provisioning URI + base32 secret for
        the authenticator app."""
        raw = os.urandom(20)
        secret_b32 = base64.b32encode(raw).decode("ascii")
        store.set_user_otp_secret(user_key=user_key, otp_secret_enc=self._encrypt(secret_b32))
        uri = self._totp(secret_b32).get_provisioning_uri(account_name or user_key, issuer)
        return {"provisioning_uri": uri, "secret_b32": secret_b32}

    def confirm(self, store: Any, *, user_key: str, code: str) -> bool:
        """Verify the first code against the pending secret; on success enable
        2FA for the user."""
        rec = store.get_user_otp(user_key=user_key)
        if not rec or not rec.get("otp_secret_enc"):
            return False
        if not self._verify_code(self._decrypt(rec["otp_secret_enc"]), code):
            return False
        store.mark_user_otp_confirmed(user_key=user_key, confirmed_at=self._now())
        return True

    def verify(self, store: Any, *, user_key: str, code: str) -> bool:
        """Verify a code for a user with 2FA ENABLED. False if not enrolled,
        not enabled, or the code is wrong."""
        rec = store.get_user_otp(user_key=user_key)
        if not rec or not rec.get("otp_enabled") or not rec.get("otp_secret_enc"):
            return False
        return self._verify_code(self._decrypt(rec["otp_secret_enc"]), code)

    def is_enabled(self, store: Any, *, user_key: str) -> bool:
        rec = store.get_user_otp(user_key=user_key)
        return bool(rec and rec.get("otp_enabled"))
