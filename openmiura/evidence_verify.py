"""Standalone, import-light offline verifier for openMiura portfolio
evidence packs.

This module re-implements the cryptographic-integrity checks that the
runtime applies when it verifies an evidence artifact, but with NO
dependency on the FastAPI app, the gateway, the database, or the
scheduler service.  Its only third-party dependency is ``cryptography``
(plus the standard library).  That is deliberate: an auditor must be
able to verify a pack on a clean machine, years later, without standing
up openMiura.

What it proves
--------------
A green result means the pack is *internally consistent and has not been
tampered with*: every embedded document hashes to the value recorded in
the manifest, the manifest hashes to its recorded ``manifest_hash``, and
the package / nested exports carry a valid ed25519 (or ECDSA-P256)
signature over their canonical signing input.

What it does NOT prove
----------------------
It does **not** establish the *identity* of the signer.  The public key
travels inside the pack, so a forged pack signed with an attacker's own
freshly-generated key would also verify as "internally consistent".  The
one built-in signal that a key is worthless is the dev seed: when a pack
was signed with openMiura's public, source-reproducible development
seed, the runtime stamps ``integrity.public_key.dev_signing_key`` and a
``signing_warning`` — but those fields are UNSIGNED metadata an attacker
can strip.  This verifier therefore detects the dev seed independently:
the seed is a public literal, so the dev public key for the pack's
(signature-bound) ``signer_key_id`` is re-derivable, and its fingerprint
is compared against the embedded key.  A dev-seed pack is treated as
NON-AUTHORITATIVE regardless of whether the signature maths check out
and regardless of whether the flag survived.  Binding a pack to a
*known* signer (a trust anchor) is out of scope for this first version.

Canonicalization
----------------
The single most important detail: the ``*.json`` files inside the ZIP are
written pretty-printed (``indent=2``), but every hash and signed message
uses the COMPACT canonical form
``json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':'))``.
A verifier must therefore re-parse each entry and re-serialize it
compactly before hashing — never hash the raw file bytes.  See
:func:`stable_digest` / :func:`canonical_message`, which mirror
``_stable_digest`` / ``_json_canonical_bytes`` in the scheduler service
byte-for-byte.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import zipfile
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, ed25519
from cryptography.hazmat.primitives.serialization import load_pem_public_key

# Exit codes — kept stable so CI can distinguish tamper from untrusted-key.
EXIT_OK = 0
EXIT_FAILED = 1            # a required check failed (tampered / invalid)
EXIT_NON_AUTHORITATIVE = 2  # signature valid but signed with the dev seed
EXIT_USAGE = 3            # bad input: missing file, not a zip, missing entries

_REQUIRED_ENTRIES = ("package.json", "integrity.json", "manifest.json")


# ---------------------------------------------------------------------------
# Canonicalization — must match scheduler/_core_mixin.py exactly.
# ---------------------------------------------------------------------------


def stable_digest(payload: Any) -> str:
    """SHA-256 hex of the compact canonical JSON of ``payload``."""
    normalized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def canonical_message(payload: Any) -> bytes:
    """Compact canonical JSON bytes — the exact message that was signed."""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _raw_ed25519_fingerprint(public_key: ed25519.Ed25519PublicKey) -> str:
    from cryptography.hazmat.primitives import serialization

    return hashlib.sha256(
        public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).hexdigest()


def _der_fingerprint(public_key: Any) -> str:
    from cryptography.hazmat.primitives import serialization

    return hashlib.sha256(
        public_key.public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    ).hexdigest()


# The built-in development signing seed is a PUBLIC literal in the source
# (scheduler/_portfolio_a_mixin.py). Anyone can derive the corresponding
# private key, so a signature from it is worthless. The signer stamps
# integrity.public_key.dev_signing_key when it is used — but that flag is
# unsigned metadata an attacker can strip. The verifier therefore
# re-derives the dev PUBLIC key for the pack's signer_key_id (which IS
# signature-bound via signing_input) and compares fingerprints.
_DEV_SEED_LITERAL = b"openmiura-portfolio-signing-v2-dev-seed"


def _dev_seed_public_fingerprint(signer_key_id: str) -> str:
    derived = hashlib.sha256(
        _DEV_SEED_LITERAL + b":" + str(signer_key_id or "openmiura-local").encode("utf-8")
    ).digest()
    return _raw_ed25519_fingerprint(ed25519.Ed25519PrivateKey.from_private_bytes(derived).public_key())


# ---------------------------------------------------------------------------
# Crypto-signature verification — mirrors
# scheduler/_portfolio_a_mixin.py::_verify_portfolio_crypto_signature
# and scheduler/_portfolio_b_mixin.py::_verify_portfolio_export_integrity.
# ---------------------------------------------------------------------------


def _verify_crypto_signature(
    *,
    report_type: str,
    scope: dict[str, Any],
    payload: dict[str, Any],
    integrity: dict[str, Any],
) -> dict[str, Any]:
    resolved = dict(integrity or {})
    payload_hash = stable_digest(payload)
    public_key_payload = dict(resolved.get("public_key") or {})
    public_key_pem = str(public_key_payload.get("public_key_pem") or "").strip()
    signature_b64 = str(resolved.get("signature") or "").strip()
    signer_key_id = str(resolved.get("signer_key_id") or "").strip()
    signed = bool(resolved.get("signed"))
    scheme = str(resolved.get("signature_scheme") or "").strip().lower()
    signing_input = dict(resolved.get("signature_input") or {})
    expected_input = {
        "report_type": str(report_type or "").strip(),
        "scope": dict(scope or {}),
        "payload_hash": payload_hash,
        "signer_key_id": signer_key_id,
    }
    payload_hash_valid = str(resolved.get("payload_hash") or "").strip() == payload_hash
    input_valid = signing_input == expected_input
    message = canonical_message(expected_input)
    signature_valid = False
    public_key_valid = False
    public_key_fingerprint = None
    error = None
    if not signed:
        signature_valid = not signature_b64
    elif not public_key_pem or not signature_b64:
        error = "missing_crypto_material"
    else:
        try:
            loaded_public = load_pem_public_key(public_key_pem.encode("utf-8"))
            signature_bytes = base64.b64decode(signature_b64.encode("ascii"))
            if scheme == "ed25519":
                if not isinstance(loaded_public, ed25519.Ed25519PublicKey):
                    raise TypeError("unsupported_public_key_type")
                public_key_valid = True
                public_key_fingerprint = _raw_ed25519_fingerprint(loaded_public)
                loaded_public.verify(signature_bytes, message)
                signature_valid = True
            elif scheme in {"ecdsa-sha256", "ecdsa-p256-sha256", "es256"}:
                if not isinstance(loaded_public, ec.EllipticCurvePublicKey):
                    raise TypeError("unsupported_public_key_type")
                public_key_valid = True
                public_key_fingerprint = _der_fingerprint(loaded_public)
                loaded_public.verify(signature_bytes, message, ec.ECDSA(hashes.SHA256()))
                signature_valid = True
            else:
                error = f"unsupported_signature_scheme:{scheme or 'unknown'}"
        except (ValueError, TypeError, InvalidSignature) as exc:
            error = str(exc) or exc.__class__.__name__
            signature_valid = False
    return {
        "report_type": str(report_type or "").strip(),
        "signed": signed,
        "signer_key_id": signer_key_id or None,
        "scheme": scheme or None,
        "signer_provider": public_key_payload.get("provider") or resolved.get("signer_provider"),
        "key_origin": public_key_payload.get("origin") or resolved.get("key_origin"),
        "payload_hash_valid": payload_hash_valid,
        "signature_valid": signature_valid,
        "public_key_valid": public_key_valid,
        "public_key_fingerprint": public_key_fingerprint,
        "signature_input_valid": input_valid,
        "expected_payload_hash": payload_hash,
        "error": error,
        "valid": payload_hash_valid and input_valid and signature_valid,
    }


def _verify_export_integrity(
    *,
    report_type: str,
    scope: dict[str, Any],
    payload: dict[str, Any],
    integrity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved = dict(integrity or {})
    if bool(resolved.get("crypto_v2")) or str(resolved.get("signature_scheme") or "").strip().lower() == "ed25519":
        crypto_verify = _verify_crypto_signature(
            report_type=report_type,
            scope=dict(scope or {}),
            payload=dict(payload or {}),
            integrity=resolved,
        )
        crypto_verify["expected_signature"] = None
        return crypto_verify
    # Legacy (non-crypto_v2) hash-based signature.
    expected_payload_hash = stable_digest(payload)
    signed = bool(resolved.get("signed"))
    signer_key_id = str(resolved.get("signer_key_id") or "").strip()
    expected_signature = None
    if signed:
        expected_signature = stable_digest({
            "report_type": str(report_type or "").strip(),
            "scope": dict(scope or {}),
            "payload": dict(payload or {}),
            "signer_key_id": signer_key_id,
        })
    payload_hash_valid = str(resolved.get("payload_hash") or "") == expected_payload_hash
    signature_valid = (not signed and not resolved.get("signature")) or str(resolved.get("signature") or "") == str(expected_signature or "")
    return {
        "report_type": str(report_type or "").strip(),
        "signed": signed,
        "signer_key_id": signer_key_id or None,
        "payload_hash_valid": payload_hash_valid,
        "signature_valid": signature_valid,
        "expected_payload_hash": expected_payload_hash,
        "expected_signature": expected_signature,
        "valid": payload_hash_valid and signature_valid,
    }


def _verify_chain_of_custody(entries: list[dict[str, Any]] | None) -> dict[str, Any]:
    items = [dict(item) for item in list(entries or [])]
    previous_hash = ""
    chain_valid = True
    signature_valid_count = 0
    invalid_entry_ids: list[str] = []
    for item in items:
        canonical = {
            "entry_type": "openmiura_portfolio_chain_of_custody_entry_v1",
            "entry_id": item.get("entry_id"),
            "portfolio_id": item.get("portfolio_id"),
            "sequence": int(item.get("sequence") or 0),
            "timestamp": float(item.get("timestamp") or 0.0),
            "actor": item.get("actor"),
            "event_type": item.get("event_type"),
            "package_id": item.get("package_id"),
            "artifact_sha256": item.get("artifact_sha256"),
            "scope": dict(item.get("scope") or {}),
            "previous_entry_hash": item.get("previous_entry_hash"),
            "metadata": dict(item.get("metadata") or {}),
        }
        integrity_verify = _verify_export_integrity(
            report_type="openmiura_portfolio_chain_of_custody_entry_v1",
            scope=dict(item.get("scope") or {}),
            payload=canonical,
            integrity=dict(item.get("integrity") or {}),
        )
        if integrity_verify.get("valid"):
            signature_valid_count += 1
        expected_entry_hash = stable_digest({
            "canonical": canonical,
            "payload_hash": ((item.get("integrity") or {}).get("payload_hash")),
            "previous_entry_hash": previous_hash,
        })
        if (
            str(item.get("previous_entry_hash") or "") != previous_hash
            or str(item.get("entry_hash") or "") != expected_entry_hash
            or not bool(integrity_verify.get("valid"))
        ):
            chain_valid = False
            invalid_entry_ids.append(str(item.get("entry_id") or ""))
        previous_hash = str(item.get("entry_hash") or "")
    return {
        "count": len(items),
        "head_hash": previous_hash or None,
        "chain_valid": chain_valid,
        "signature_valid_count": signature_valid_count,
        "invalid_entry_ids": [item for item in invalid_entry_ids if item],
        "valid": chain_valid and signature_valid_count == len(items),
    }


# ---------------------------------------------------------------------------
# Pack-level orchestration.
# ---------------------------------------------------------------------------


class _PackError(Exception):
    """Raised for structural/usage problems (maps to EXIT_USAGE)."""


def _read_entries(pack_path: Path) -> tuple[bytes, dict[str, Any]]:
    try:
        archive_bytes = pack_path.read_bytes()
    except OSError as exc:
        raise _PackError(f"cannot_read_file:{exc}") from exc
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes), mode="r") as zf:
            entries: dict[str, Any] = {}
            for name in zf.namelist():
                try:
                    entries[name] = json.loads(zf.read(name).decode("utf-8"))
                except Exception:
                    entries[name] = None
    except zipfile.BadZipFile as exc:
        raise _PackError("not_a_zip_archive") from exc
    missing = [name for name in _REQUIRED_ENTRIES if not isinstance(entries.get(name), dict)]
    if missing:
        raise _PackError(f"missing_required_entries:{','.join(missing)}")
    return archive_bytes, entries


def verify_pack(pack_path: str | Path, *, strict: bool = False) -> dict[str, Any]:
    """Verify an evidence pack ZIP on disk and return a structured result.

    Never raises for verification failures — those are reported in the
    result.  Structural/usage problems set ``ok=False`` and
    ``verdict='error'``.
    """
    path = Path(pack_path)
    try:
        archive_bytes, entries = _read_entries(path)
    except _PackError as exc:
        return {
            "ok": False,
            "pack": path.as_posix(),
            "verdict": "error",
            "error": str(exc),
        }

    archive_sha256 = hashlib.sha256(archive_bytes).hexdigest()
    package_payload = dict(entries.get("package.json") or {})
    integrity = dict(entries.get("integrity.json") or {})
    manifest_entry = dict(entries.get("manifest.json") or {})
    attestation_export = dict(entries.get("attestation_export.json") or {})
    postmortem_export = dict(entries.get("postmortem_export.json") or {})
    # Side-car documents also exist as a copy INSIDE the signed
    # package.json. The standalone ZIP entries are unsigned, so the signed
    # copy is the source of truth; a present entry must match it (see
    # sidecar_docs_match_signed_package below).
    chain_of_custody = dict((package_payload.get("chain_of_custody") or entries.get("chain_of_custody.json") or {}))
    custody_anchor = dict((package_payload.get("custody_anchor") or entries.get("custody_anchor.json") or {}))
    notarization = dict((package_payload.get("notarization") or entries.get("notarization.json") or {}))
    sidecar_mismatches: list[str] = []
    for entry_name, package_key in (
        ("chain_of_custody.json", "chain_of_custody"),
        ("custody_anchor.json", "custody_anchor"),
        ("notarization.json", "notarization"),
        ("retention.json", "retention"),
    ):
        entry_doc = entries.get(entry_name)
        package_doc = package_payload.get(package_key)
        if isinstance(entry_doc, dict) and entry_doc and isinstance(package_doc, dict) and package_doc:
            if entry_doc != package_doc:
                sidecar_mismatches.append(entry_name)

    # Manifest self-consistency.
    manifest_from_package = dict(package_payload.get("manifest") or {})
    manifest_hash = str(manifest_from_package.get("manifest_hash") or manifest_entry.get("manifest_hash") or "").strip()
    manifest_payload = dict(manifest_entry)
    manifest_payload.pop("manifest_hash", None)
    package_manifest_payload = dict(manifest_from_package)
    package_manifest_payload.pop("manifest_hash", None)
    expected_manifest_hash = stable_digest(manifest_payload)
    manifest_hash_valid = bool(manifest_hash) and manifest_hash == expected_manifest_hash and package_manifest_payload == manifest_payload

    # Package + nested export signatures.
    package_verify = _verify_export_integrity(
        report_type=str(package_payload.get("report_type") or ""),
        scope=dict(package_payload.get("scope") or {}),
        payload=package_payload,
        integrity=integrity,
    )
    attestation_verify = _verify_export_integrity(
        report_type=str(((attestation_export.get("report") or {}).get("report_type")) or ""),
        scope=dict(attestation_export.get("scope") or {}),
        payload=dict(attestation_export.get("report") or {}),
        integrity=dict(attestation_export.get("integrity") or {}),
    )
    postmortem_verify = _verify_export_integrity(
        report_type=str(((postmortem_export.get("report") or {}).get("report_type")) or ""),
        scope=dict(postmortem_export.get("scope") or {}),
        payload=dict(postmortem_export.get("report") or {}),
        integrity=dict(postmortem_export.get("integrity") or {}),
    )

    # Manifest links: artifact hashes match the embedded documents.
    manifest_artifacts = {str(item.get("artifact_id") or ""): dict(item) for item in list(manifest_payload.get("artifacts") or [])}
    manifest_links_valid = (
        manifest_artifacts.get("attestation_export", {}).get("payload_hash") == ((attestation_export.get("integrity") or {}).get("payload_hash"))
        and manifest_artifacts.get("postmortem_export", {}).get("payload_hash") == ((postmortem_export.get("integrity") or {}).get("payload_hash"))
        and (
            not manifest_artifacts.get("chain_of_custody")
            or manifest_artifacts.get("chain_of_custody", {}).get("payload_hash") == stable_digest(chain_of_custody)
        )
    )

    # Chain of custody (self-contained; only gates under --strict).
    chain_present = bool(chain_of_custody.get("entries"))
    chain_verify = _verify_chain_of_custody(list(chain_of_custody.get("entries") or [])) if chain_present else None

    # Required checks gate the headline verdict.
    required_checks = {
        "manifest_hash_valid": manifest_hash_valid,
        "manifest_links_valid": manifest_links_valid,
        "package_integrity_valid": bool(package_verify.get("valid")),
        "attestation_export_valid": bool(attestation_verify.get("valid")),
        "postmortem_export_valid": bool(postmortem_verify.get("valid")),
        "sidecar_docs_match_signed_package": not sidecar_mismatches,
    }
    if strict and chain_present:
        required_checks["chain_of_custody_valid"] = bool(chain_verify and chain_verify.get("valid"))

    failures = [name for name, ok in required_checks.items() if not ok]
    consistent = not failures

    # Signedness. A pack is only AUTHORITATIVE when its package payload
    # carries a real cryptographic signature (ed25519/ECDSA) whose public
    # key we actually loaded and verified. ``signed=False`` (no signature
    # at all) and the legacy hash-based "signature" (reproducible from the
    # payload, no private key) are NOT authoritative — otherwise a forged
    # pack with no real signature would look "verified".
    package_signed = bool(package_verify.get("signed"))
    cryptographically_signed = bool(package_verify.get("public_key_valid"))

    # Dev-seed / authoritativeness. The pack's own dev_signing_key flag is
    # unsigned metadata (it lives outside the signed signing_input), so a
    # stripped flag must not be trusted: independently re-derive the dev
    # public key for this pack's signature-bound signer_key_id and compare
    # fingerprints against the embedded (verified) key.
    public_key_block = dict(integrity.get("public_key") or {})
    dev_key_fingerprint_match = False
    embedded_fingerprint = package_verify.get("public_key_fingerprint")
    if embedded_fingerprint:
        try:
            dev_key_fingerprint_match = embedded_fingerprint == _dev_seed_public_fingerprint(
                str(integrity.get("signer_key_id") or "")
            )
        except Exception:
            dev_key_fingerprint_match = False
    dev_signing_key = bool(public_key_block.get("dev_signing_key")) or dev_key_fingerprint_match
    signing_warning = public_key_block.get("signing_warning")
    authoritative = consistent and cryptographically_signed and not dev_signing_key

    verdict = "verified" if consistent else "failed"

    return {
        "ok": True,
        "pack": path.as_posix(),
        "archive_sha256": archive_sha256,
        "archive_size_bytes": len(archive_bytes),
        "verdict": verdict,
        "consistent": consistent,
        "authoritative": authoritative,
        "signed": package_signed,
        "cryptographically_signed": cryptographically_signed,
        "dev_signing_key": dev_signing_key,
        "dev_key_fingerprint_match": dev_key_fingerprint_match,
        "signing_warning": signing_warning,
        "signature_scheme": integrity.get("signature_scheme"),
        "public_key_fingerprint": public_key_block.get("public_key_fingerprint"),
        "signer_provider": public_key_block.get("provider") or integrity.get("signer_provider"),
        "key_origin": public_key_block.get("origin") or integrity.get("key_origin"),
        "portfolio_id": str(((package_payload.get("portfolio") or {}).get("portfolio_id")) or "").strip() or None,
        "package_id": str(package_payload.get("package_id") or "").strip() or None,
        "checks": required_checks,
        "failures": failures,
        "manifest": {
            "manifest_hash": manifest_hash,
            "expected_manifest_hash": expected_manifest_hash,
            "valid": manifest_hash_valid,
        },
        "details": {
            "package_integrity": package_verify,
            "attestation_export": attestation_verify,
            "postmortem_export": postmortem_verify,
            "chain_of_custody": chain_verify,
        },
        # These need a time reference, policy, or live cloud APIs and are
        # therefore NOT verified offline — only their presence is reported.
        "not_verified_offline": {
            "notarization_present": bool(notarization),
            "custody_anchor_present": bool(custody_anchor),
            "escrow_present": bool(package_payload.get("escrow") or integrity.get("escrow")),
        },
    }


def _exit_code_for(result: dict[str, Any], *, allow_dev_seed: bool) -> int:
    if not result.get("ok"):
        return EXIT_USAGE
    if not result.get("consistent"):
        return EXIT_FAILED
    if result.get("authoritative"):
        return EXIT_OK
    # Consistent but not authoritative. The only opt-in that flips this to
    # success is --allow-dev-seed, and only for a genuinely dev-seed-signed
    # pack (an unsigned / legacy-signed pack is never made "OK" by it).
    if result.get("dev_signing_key") and result.get("cryptographically_signed") and allow_dev_seed:
        return EXIT_OK
    return EXIT_NON_AUTHORITATIVE


def _print_human(result: dict[str, Any]) -> None:
    if not result.get("ok"):
        print(f"ERROR: {result.get('error')} ({result.get('pack')})")
        return
    print(f"openMiura evidence pack: {result['pack']}")
    print(f"archive sha256: {result['archive_sha256']}")
    if result.get("package_id"):
        print(f"package: {result['package_id']}  portfolio: {result.get('portfolio_id')}")
    print(f"signature: {result.get('signature_scheme')}  provider: {result.get('signer_provider')}  origin: {result.get('key_origin')}")
    if result.get("public_key_fingerprint"):
        print(f"public key fingerprint: {result['public_key_fingerprint']}")
    for name, ok in result["checks"].items():
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    chain = (result.get("details") or {}).get("chain_of_custody")
    if chain is not None:
        print(f"[INFO] chain_of_custody: {chain.get('count')} entries, chain_valid={chain.get('valid')}")
    nvo = result.get("not_verified_offline") or {}
    present = [k.replace("_present", "") for k, v in nvo.items() if v]
    if present:
        print(f"[SKIP] not verified offline (need time/policy/cloud): {', '.join(present)}")
    print()
    if not result.get("consistent"):
        print(f"VERDICT: FAILED — {', '.join(result['failures'])}")
    elif result.get("dev_signing_key"):
        print("VERDICT: NON-AUTHORITATIVE — pack is internally consistent BUT was signed")
        print("with the built-in public development seed. This signature is NOT")
        print("authoritative and must not be relied upon.")
        if result.get("dev_key_fingerprint_match"):
            print("  (detected by re-deriving the public dev key and matching its")
            print("  fingerprint — independent of the pack's own metadata)")
        if result.get("signing_warning"):
            print(f"  {result['signing_warning']}")
    elif not result.get("cryptographically_signed"):
        kind = "unsigned" if not result.get("signed") else "signed only with the legacy reproducible hash"
        print(f"VERDICT: NON-AUTHORITATIVE — pack is internally consistent but is {kind};")
        print("there is no real cryptographic signature, so authenticity cannot be relied upon.")
    else:
        print("VERDICT: VERIFIED (internally consistent, signature valid)")
        print("Note: this proves the pack is untampered and signed by whoever held")
        print("the embedded key; it does not by itself prove the signer's identity.")


def verify_pack_cli(*, pack: str, json_output: bool = False, allow_dev_seed: bool = False, strict: bool = False) -> int:
    """CLI entry point. Returns a process exit code."""
    result = verify_pack(pack, strict=strict)
    exit_code = _exit_code_for(result, allow_dev_seed=allow_dev_seed)
    if json_output:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _print_human(result)
    return exit_code
