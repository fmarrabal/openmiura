"""Ed25519 signing for individual release approvals (21 CFR Part 11 §11.50).

A self-contained *local* ed25519 signer that turns a release approval into a
signature manifestation: signer + meaning + timestamp, signed over the SAME
canonical ``signing_input`` shape the evidence-pack verifier already knows —
``{report_type, scope, payload_hash, signer_key_id}`` — using the SAME
canonicalization (``evidence_verify.canonical_message``) and the SAME key
sources / dev-seed honesty as portfolio evidence signing.

Why a separate module (not the scheduler's ``_sign_portfolio_payload_crypto_v2``):
that method is coupled to the scheduler mixin and carries KMS/HSM provider
branches a per-approval signature does not need. This reimplements ONLY the
local-ed25519 path, reusing ``evidence_verify`` primitives so the two stay
byte-compatible, and touches none of the evidence-pack signing code.

Key sources (first match wins), identical to
``_load_portfolio_private_signing_key``:
  1. ``OPENMIURA_EVIDENCE_SIGNING_PRIVATE_KEY_PEM_B64``
  2. ``OPENMIURA_EVIDENCE_SIGNING_PRIVATE_KEY_PEM_PATH``
  3. ``OPENMIURA_EVIDENCE_SIGNING_SEED`` (seed → sha256 derive)
  4. the built-in PUBLIC dev seed (flagged ``dev_signing_key`` unless
     ``OPENMIURA_ALLOW_DEV_SIGNING_KEY`` is set) — a signature from it is not
     authoritative, exactly as the offline verifier reports.
"""
from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from openmiura.evidence_verify import (
    _DEV_SEED_LITERAL,
    _raw_ed25519_fingerprint,
    canonical_message,
    stable_digest,
)

_REPORT_TYPE = "release_approval"
_TRUTHY = {"1", "true", "yes", "on"}


def _load_private_key(*, signer_key_id: str) -> tuple[ed25519.Ed25519PrivateKey, dict[str, Any]]:
    key_id = str(signer_key_id or "openmiura-local")
    pem_b64 = str(os.getenv("OPENMIURA_EVIDENCE_SIGNING_PRIVATE_KEY_PEM_B64") or "").strip()
    pem_path = str(os.getenv("OPENMIURA_EVIDENCE_SIGNING_PRIVATE_KEY_PEM_PATH") or "").strip()
    dev_signing_key = False

    if pem_b64:
        private = serialization.load_pem_private_key(base64.b64decode(pem_b64.encode("ascii")), password=None)
        origin = "configured_pem_b64"
    elif pem_path:
        private = serialization.load_pem_private_key(Path(pem_path).read_bytes(), password=None)
        origin = "configured_pem_path"
    else:
        configured_seed = str(os.getenv("OPENMIURA_EVIDENCE_SIGNING_SEED") or "").strip()
        dev_signing_key = not configured_seed
        seed_material = (configured_seed.encode("utf-8") if configured_seed else _DEV_SEED_LITERAL)
        derived = hashlib.sha256(seed_material + b":" + key_id.encode("utf-8")).digest()
        private = ed25519.Ed25519PrivateKey.from_private_bytes(derived)
        origin = "derived_seed"

    if not isinstance(private, ed25519.Ed25519PrivateKey):
        raise TypeError("release-approval signing key must be Ed25519")

    public = private.public_key()
    dev_opt_in = str(os.getenv("OPENMIURA_ALLOW_DEV_SIGNING_KEY") or "").strip().lower() in _TRUTHY
    info: dict[str, Any] = {
        "origin": origin,
        "public_key_pem": public.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8"),
        "public_key_fingerprint": _raw_ed25519_fingerprint(public),
        "dev_signing_key": bool(dev_signing_key and not dev_opt_in),
    }
    return private, info


def signing_input_for(*, scope: dict[str, Any], payload: dict[str, Any], signer_key_id: str) -> dict[str, Any]:
    """The exact object that gets signed — one builder used by signer + verifier."""
    return {
        "report_type": _REPORT_TYPE,
        "scope": dict(scope or {}),
        "payload_hash": stable_digest(payload),
        "signer_key_id": str(signer_key_id or "").strip(),
    }


def sign_release_approval(
    *,
    scope: dict[str, Any],
    payload: dict[str, Any],
    signer_key_id: str = "openmiura-local",
) -> dict[str, Any]:
    """Sign a release approval. Returns the columns to persist on the row
    (``signature``, ``signature_scheme``, ``signer_key_id``,
    ``signature_input_hash``) plus ``public_key_pem`` / ``dev_signing_key`` for
    the caller to surface."""
    signing_input = signing_input_for(scope=scope, payload=payload, signer_key_id=signer_key_id)
    message = canonical_message(signing_input)
    private, info = _load_private_key(signer_key_id=signer_key_id)
    signature = private.sign(message)
    return {
        "signature": base64.b64encode(signature).decode("ascii"),
        "signature_scheme": "ed25519",
        "signer_key_id": str(signer_key_id or "").strip(),
        "signature_input_hash": hashlib.sha256(message).hexdigest(),
        "public_key_pem": info["public_key_pem"],
        "public_key_fingerprint": info["public_key_fingerprint"],
        "dev_signing_key": info["dev_signing_key"],
    }


def verify_release_approval_signature(
    *,
    scope: dict[str, Any],
    payload: dict[str, Any],
    signer_key_id: str,
    signature_b64: str,
    public_key_pem: str | None = None,
) -> bool:
    """Verify a stored approval signature. When ``public_key_pem`` is given the
    signature is checked against it (offline / pack path); otherwise the local
    key for ``signer_key_id`` is re-derived (server-side path)."""
    if not signature_b64:
        return False
    message = canonical_message(signing_input_for(scope=scope, payload=payload, signer_key_id=signer_key_id))
    try:
        if public_key_pem:
            public = load_pem_public_key(public_key_pem.encode("utf-8"))
        else:
            public = _load_private_key(signer_key_id=signer_key_id)[0].public_key()
        if not isinstance(public, ed25519.Ed25519PublicKey):
            return False
        public.verify(base64.b64decode(signature_b64.encode("ascii")), message)
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False
