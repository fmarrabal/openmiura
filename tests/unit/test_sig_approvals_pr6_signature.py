"""Signature-grade approvals — PR 6 (ed25519 signature manifestation).

Every strict approval vote is now signed with ed25519 over the same canonical
signing_input the evidence verifier knows. These tests pin the sign/verify
round-trip and tamper detection at the module level, and that a cast vote
persists a verifiable signature whose row stays inside the intact hash-chain.
"""
from __future__ import annotations

import types

from openmiura.application.releases.approval_signing import (
    sign_release_approval,
    verify_release_approval_signature,
)
from openmiura.application.releases.service import ReleaseService
from openmiura.core.audit import AuditStore
from openmiura.core.migrations import apply_migrations
from openmiura.persistence.hashchain import verify_audit_chain

_SCOPE = {"tenant_id": "acme", "workspace_id": "w", "environment": "prod"}
_PAYLOAD = {
    "release_id": "r1",
    "action": "approve",
    "signer_user_key": "user:carol",
    "meaning": "approved release for promotion",
    "second_factor_method": None,
    "otp_verified_at": None,
}


def _clear_key_env(monkeypatch):
    for var in (
        "OPENMIURA_EVIDENCE_SIGNING_PRIVATE_KEY_PEM_B64",
        "OPENMIURA_EVIDENCE_SIGNING_PRIVATE_KEY_PEM_PATH",
        "OPENMIURA_EVIDENCE_SIGNING_SEED",
        "OPENMIURA_ALLOW_DEV_SIGNING_KEY",
    ):
        monkeypatch.delenv(var, raising=False)


# ============================ module level ============================


def test_sign_verify_roundtrip(monkeypatch):
    _clear_key_env(monkeypatch)
    sig = sign_release_approval(scope=_SCOPE, payload=_PAYLOAD)
    assert sig["signature_scheme"] == "ed25519"
    assert verify_release_approval_signature(
        scope=_SCOPE, payload=_PAYLOAD, signer_key_id=sig["signer_key_id"], signature_b64=sig["signature"]
    ) is True
    # And against the embedded public key (the offline / pack path).
    assert verify_release_approval_signature(
        scope=_SCOPE, payload=_PAYLOAD, signer_key_id=sig["signer_key_id"],
        signature_b64=sig["signature"], public_key_pem=sig["public_key_pem"],
    ) is True


def test_tampered_payload_fails_verification(monkeypatch):
    _clear_key_env(monkeypatch)
    sig = sign_release_approval(scope=_SCOPE, payload=_PAYLOAD)
    tampered = dict(_PAYLOAD, meaning="rejected")
    assert verify_release_approval_signature(
        scope=_SCOPE, payload=tampered, signer_key_id=sig["signer_key_id"], signature_b64=sig["signature"]
    ) is False
    # A different signer in the payload also breaks it.
    impersonated = dict(_PAYLOAD, signer_user_key="user:mallory")
    assert verify_release_approval_signature(
        scope=_SCOPE, payload=impersonated, signer_key_id=sig["signer_key_id"], signature_b64=sig["signature"]
    ) is False


def test_dev_seed_is_flagged_real_seed_is_not(monkeypatch):
    _clear_key_env(monkeypatch)
    assert sign_release_approval(scope=_SCOPE, payload=_PAYLOAD)["dev_signing_key"] is True
    monkeypatch.setenv("OPENMIURA_EVIDENCE_SIGNING_SEED", "an-operator-private-seed")
    real = sign_release_approval(scope=_SCOPE, payload=_PAYLOAD)
    assert real["dev_signing_key"] is False
    # The real-key signature still verifies.
    assert verify_release_approval_signature(
        scope=_SCOPE, payload=_PAYLOAD, signer_key_id=real["signer_key_id"], signature_b64=real["signature"]
    ) is True


# ============================ service integration ============================


def _gw(tmp_path):
    store = AuditStore(db_path=(tmp_path / "audit.db").as_posix(), backend="sqlite", database_url="")
    apply_migrations(store._conn)
    return types.SimpleNamespace(audit=store), store


def _submitted_release(store):
    rid = store.create_release_bundle(kind="agent", name="svc", version="1.0.0", created_by="user:alice")["release_id"]
    store.submit_release_bundle(rid, actor="user:bob", reason="ready")
    return rid


def test_cast_vote_persists_verifiable_signature(tmp_path, monkeypatch):
    _clear_key_env(monkeypatch)
    gw, store = _gw(tmp_path)
    rid = _submitted_release(store)
    ReleaseService().cast_release_approval_vote(gw, release_id=rid, actor="user:carol")

    vote = store.list_release_approval_votes(release_id=rid)[-1]
    assert vote["signature"] and vote["signature_scheme"] == "ed25519"
    assert vote["signer_key_id"] == "openmiura-release-approvals"

    bundle = store.get_release_bundle(rid)
    scope = {"tenant_id": bundle["tenant_id"], "workspace_id": bundle["workspace_id"], "environment": bundle["environment"]}
    payload = {
        "release_id": rid,
        "action": "approve",
        "signer_user_key": vote["signer_user_key"],
        "meaning": vote["meaning"],
        "second_factor_method": vote["second_factor_method"],
        "otp_verified_at": vote["otp_verified_at"],
    }
    assert verify_release_approval_signature(
        scope=scope, payload=payload, signer_key_id=vote["signer_key_id"], signature_b64=vote["signature"]
    ) is True
    # The signed columns are part of the chained row, which stays intact.
    assert verify_audit_chain(store._conn, chain_table="release_approvals")["any_tamper"] is False
