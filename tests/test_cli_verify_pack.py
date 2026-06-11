"""Offline `openmiura verify <pack.zip>` CLI + verifier.

These tests build a REAL evidence pack through the export flow, write the
ZIP to disk, and run the standalone verifier against it. The two
load-bearing tests are:

  * ``test_canonicalization_matches_service`` — pins the standalone
    ``stable_digest`` byte-for-byte to the scheduler service's
    ``_stable_digest`` (canonicalization drift would make every
    signature look invalid);
  * ``test_crosscheck_against_service_verifier`` — asserts the standalone
    verifier's per-check booleans agree with the in-process service
    verifier for the same pack.

The rest exercise the honest-verdict behaviour: a real-key pack verifies
authoritative (exit 0); a dev-seed pack is internally consistent but
NON-AUTHORITATIVE (exit 2) unless ``--allow-dev-seed``; tampering any
layer fails (exit 1); structural problems are usage errors (exit 3).
"""
from __future__ import annotations

import base64
import io
import json
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

import app as app_module
from openmiura.gateway import Gateway
from openmiura import evidence_verify
from openmiura.evidence_verify import (
    EXIT_FAILED,
    EXIT_NON_AUTHORITATIVE,
    EXIT_OK,
    EXIT_USAGE,
    stable_digest,
    verify_pack,
    verify_pack_cli,
)
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
    "OPENMIURA_ALLOW_DEV_SIGNING_KEY",
)


def _export_response(tmp_path: Path, monkeypatch) -> dict:
    base_now = 1_784_795_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / "openmiura.yaml"
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {"Authorization": "Bearer secret-admin"}
    with TestClient(app) as client:
        runtime_id = _create_runtime(client, headers, name="runtime-verify-cli")
        portfolio_id = _create_submitted_portfolio(
            client,
            headers,
            base_now=base_now,
            runtime_id=runtime_id,
            export_policy={
                "enabled": True,
                "require_signature": True,
                "signer_key_id": "verify-cli-ci",
                "timeline_limit": 120,
                "embed_artifact_content": True,
            },
        )
        export = client.post(
            f"/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-package-export",
            headers=headers,
            json={"actor": "auditor", "tenant_id": "tenant-a", "workspace_id": "ws-a", "environment": "prod"},
        )
        assert export.status_code == 200, export.text
        return export.json()


def _pack_bytes(tmp_path: Path, monkeypatch) -> bytes:
    payload = _export_response(tmp_path, monkeypatch)
    content_b64 = payload["artifact"]["content_b64"]
    return base64.b64decode(content_b64.encode("ascii"))


def _write_pack(tmp_path: Path, monkeypatch, *, real_key: bool) -> Path:
    for v in _SIGNING_ENVS:
        monkeypatch.delenv(v, raising=False)
    if real_key:
        monkeypatch.setenv("OPENMIURA_EVIDENCE_SIGNING_SEED", "an-operator-private-seed-for-verify-tests")
    data = _pack_bytes(tmp_path, monkeypatch)
    pack = tmp_path / "pack.zip"
    pack.write_bytes(data)
    return pack


def _rezip(original: bytes, overrides: dict[str, object]) -> bytes:
    """Rebuild a ZIP, replacing the parsed JSON of the named entries."""
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(original), "r") as zin:
        names = zin.namelist()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
            for name in names:
                if name in overrides:
                    zout.writestr(name, json.dumps(overrides[name], ensure_ascii=False, sort_keys=True, indent=2))
                else:
                    zout.writestr(name, zin.read(name))
    return out.getvalue()


def _entry(pack_bytes: bytes, name: str) -> dict:
    with zipfile.ZipFile(io.BytesIO(pack_bytes), "r") as zf:
        return json.loads(zf.read(name).decode("utf-8"))


# ==================================================================
# Canonicalization — the load-bearing pin.
# ==================================================================


def test_canonicalization_matches_service() -> None:
    from openmiura.application.runtime_adapters.external.scheduler._core_mixin import (
        _OpenClawRecoverySchedulerServiceCoreMixin as Core,
    )

    samples = [
        {"b": 1, "a": 2, "z": {"nested": True, "list": [3, 2, 1]}},
        {"unicode": "café — μ ± δ", "float": 1718000000.123456, "int": 7},
        {"empty": {}, "none": None, "bool": False, "arr": []},
        {"scope": {"tenant_id": "tenant-a", "workspace_id": "ws-a", "environment": "prod"}},
    ]
    for obj in samples:
        assert stable_digest(obj) == Core._stable_digest(obj)
        assert evidence_verify.canonical_message(obj) == Core._json_canonical_bytes(obj)


# ==================================================================
# Happy paths.
# ==================================================================


def test_real_key_pack_verifies_authoritative(tmp_path: Path, monkeypatch) -> None:
    pack = _write_pack(tmp_path, monkeypatch, real_key=True)
    result = verify_pack(pack)
    assert result["ok"] is True
    assert result["verdict"] == "verified"
    assert result["consistent"] is True
    assert result["authoritative"] is True
    assert result["dev_signing_key"] is False
    assert result["signature_scheme"] == "ed25519"
    assert not result["failures"]
    assert verify_pack_cli(pack=str(pack)) == EXIT_OK


def test_dev_seed_pack_is_consistent_but_non_authoritative(tmp_path: Path, monkeypatch) -> None:
    pack = _write_pack(tmp_path, monkeypatch, real_key=False)
    result = verify_pack(pack)
    # Cryptographically consistent (the dev key DOES verify)...
    assert result["consistent"] is True
    assert result["details"]["package_integrity"]["signature_valid"] is True
    # ...but flagged non-authoritative.
    assert result["dev_signing_key"] is True
    assert result["authoritative"] is False
    assert "not authoritative" in (result["signing_warning"] or "").lower()
    # Exit code distinguishes this from a tamper.
    assert verify_pack_cli(pack=str(pack)) == EXIT_NON_AUTHORITATIVE
    # Opt-in lets CI accept it.
    assert verify_pack_cli(pack=str(pack), allow_dev_seed=True) == EXIT_OK


# ==================================================================
# Cross-check against the in-process reference verifier.
# ==================================================================


def test_crosscheck_against_service_verifier(tmp_path: Path, monkeypatch) -> None:
    pack = _write_pack(tmp_path, monkeypatch, real_key=True)
    data = pack.read_bytes()

    from openmiura.application.runtime_adapters.external.scheduler import OpenClawRecoverySchedulerService

    service = OpenClawRecoverySchedulerService()
    ref = service._verify_portfolio_evidence_artifact_payload(
        artifact={"filename": pack.name, "size_bytes": len(data)},
        artifact_b64=base64.b64encode(data).decode("ascii"),
    )
    ref_checks = ref["verification"]["checks"]

    mine = verify_pack(pack)
    # Each check the standalone tool reports must agree with the service.
    assert mine["checks"]["manifest_hash_valid"] == ref_checks["manifest_hash_valid"]
    assert mine["checks"]["manifest_links_valid"] == ref_checks["manifest_links_valid"]
    assert mine["checks"]["package_integrity_valid"] == ref_checks["package_integrity_valid"]
    assert mine["checks"]["attestation_export_valid"] == ref_checks["attestation_export_valid"]
    assert mine["checks"]["postmortem_export_valid"] == ref_checks["postmortem_export_valid"]
    assert mine["consistent"] is True and ref["verification"]["valid"] is True


# ==================================================================
# Tamper detection.
# ==================================================================


def test_tamper_package_payload_fails(tmp_path: Path, monkeypatch) -> None:
    pack = _write_pack(tmp_path, monkeypatch, real_key=True)
    data = pack.read_bytes()
    pkg = _entry(data, "package.json")
    pkg["generated_by"] = "attacker"  # mutate signed content without re-signing
    tampered = tmp_path / "tampered_pkg.zip"
    tampered.write_bytes(_rezip(data, {"package.json": pkg}))
    result = verify_pack(tampered)
    assert result["checks"]["package_integrity_valid"] is False
    assert verify_pack_cli(pack=str(tampered)) == EXIT_FAILED


def test_tamper_manifest_without_updating_hash_fails(tmp_path: Path, monkeypatch) -> None:
    pack = _write_pack(tmp_path, monkeypatch, real_key=True)
    data = pack.read_bytes()
    manifest = _entry(data, "manifest.json")
    manifest["generated_by"] = "attacker"  # leaves manifest_hash stale
    tampered = tmp_path / "tampered_manifest.zip"
    tampered.write_bytes(_rezip(data, {"manifest.json": manifest}))
    result = verify_pack(tampered)
    assert result["checks"]["manifest_hash_valid"] is False
    assert verify_pack_cli(pack=str(tampered)) == EXIT_FAILED


def test_tamper_signature_fails(tmp_path: Path, monkeypatch) -> None:
    pack = _write_pack(tmp_path, monkeypatch, real_key=True)
    data = pack.read_bytes()
    integrity = _entry(data, "integrity.json")
    sig = integrity["signature"]
    # Flip a character in the base64 signature (keep it decodable).
    flipped = ("B" if sig[0] != "B" else "C") + sig[1:]
    integrity["signature"] = flipped
    tampered = tmp_path / "tampered_sig.zip"
    tampered.write_bytes(_rezip(data, {"integrity.json": integrity}))
    result = verify_pack(tampered)
    assert result["checks"]["package_integrity_valid"] is False
    assert verify_pack_cli(pack=str(tampered)) == EXIT_FAILED


def test_stripped_dev_seed_flag_is_still_detected(tmp_path: Path, monkeypatch) -> None:
    """The dev_signing_key/signing_warning fields live OUTSIDE the signed
    signing_input, so an attacker can delete them without breaking the
    signature. The verifier must detect the dev seed independently (by
    re-deriving the public dev key for the signature-bound signer_key_id)
    — otherwise stripping two unsigned fields turns a worthless dev-seed
    pack into a 'VERIFIED authoritative' exit-0 verdict."""
    pack = _write_pack(tmp_path, monkeypatch, real_key=False)
    data = pack.read_bytes()
    integrity = _entry(data, "integrity.json")
    assert integrity["public_key"].pop("dev_signing_key", None) is True
    integrity["public_key"].pop("signing_warning", None)
    stripped = tmp_path / "stripped_dev.zip"
    stripped.write_bytes(_rezip(data, {"integrity.json": integrity}))

    result = verify_pack(stripped)
    # The signature still verifies (nothing signed was touched)...
    assert result["details"]["package_integrity"]["signature_valid"] is True
    # ...but the dev key is recognised by fingerprint, not by the flag.
    assert result["dev_key_fingerprint_match"] is True
    assert result["dev_signing_key"] is True
    assert result["authoritative"] is False
    assert verify_pack_cli(pack=str(stripped)) == EXIT_NON_AUTHORITATIVE


def test_real_key_pack_does_not_false_positive_dev_fingerprint(tmp_path: Path, monkeypatch) -> None:
    pack = _write_pack(tmp_path, monkeypatch, real_key=True)
    result = verify_pack(pack)
    assert result["dev_key_fingerprint_match"] is False
    assert result["authoritative"] is True


def test_tamper_sidecar_notarization_fails(tmp_path: Path, monkeypatch) -> None:
    """The side-car ZIP entries are unsigned; a swapped notarization.json
    must fail against the signed copy inside package.json."""
    pack = _write_pack(tmp_path, monkeypatch, real_key=True)
    data = pack.read_bytes()
    notarization = _entry(data, "notarization.json")
    notarization["receipt_id"] = "forged-receipt"
    tampered = tmp_path / "tampered_notarization.zip"
    tampered.write_bytes(_rezip(data, {"notarization.json": notarization}))
    result = verify_pack(tampered)
    assert result["checks"]["sidecar_docs_match_signed_package"] is False
    assert verify_pack_cli(pack=str(tampered)) == EXIT_FAILED


def test_unsigned_pack_is_consistent_but_not_authoritative(tmp_path: Path, monkeypatch) -> None:
    """A pack with no real cryptographic signature must never read as
    'verified authoritative' even if every hash is internally consistent
    — otherwise a forged unsigned pack would pass."""
    pack = _write_pack(tmp_path, monkeypatch, real_key=True)
    data = pack.read_bytes()
    integrity = _entry(data, "integrity.json")
    integrity["signed"] = False
    integrity["signature"] = ""
    integrity.pop("crypto_v2", None)
    integrity["signature_scheme"] = ""
    unsigned = tmp_path / "unsigned.zip"
    unsigned.write_bytes(_rezip(data, {"integrity.json": integrity}))
    result = verify_pack(unsigned)
    assert result["consistent"] is True
    assert result["cryptographically_signed"] is False
    assert result["authoritative"] is False
    assert verify_pack_cli(pack=str(unsigned)) == EXIT_NON_AUTHORITATIVE
    # --allow-dev-seed must NOT rescue an unsigned pack (it's not a dev seed).
    assert verify_pack_cli(pack=str(unsigned), allow_dev_seed=True) == EXIT_NON_AUTHORITATIVE


# ==================================================================
# Usage errors.
# ==================================================================


def test_missing_file_is_usage_error(tmp_path: Path) -> None:
    result = verify_pack(tmp_path / "does_not_exist.zip")
    assert result["ok"] is False
    assert result["verdict"] == "error"
    assert verify_pack_cli(pack=str(tmp_path / "does_not_exist.zip")) == EXIT_USAGE


def test_non_zip_is_usage_error(tmp_path: Path) -> None:
    bogus = tmp_path / "not.zip"
    bogus.write_text("this is not a zip", encoding="utf-8")
    result = verify_pack(bogus)
    assert result["ok"] is False
    assert result["error"] == "not_a_zip_archive"
    assert verify_pack_cli(pack=str(bogus)) == EXIT_USAGE


def test_zip_missing_required_entry_is_usage_error(tmp_path: Path) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps({"manifest_hash": "x"}))
    incomplete = tmp_path / "incomplete.zip"
    incomplete.write_bytes(buf.getvalue())
    result = verify_pack(incomplete)
    assert result["ok"] is False
    assert result["error"].startswith("missing_required_entries")
    assert verify_pack_cli(pack=str(incomplete)) == EXIT_USAGE


# ==================================================================
# JSON output shape.
# ==================================================================


def test_main_propagates_exit_code(tmp_path: Path, monkeypatch) -> None:
    """The console-script entry point must surface the verifier's exit
    code (Click returns it in non-standalone mode; main must not swallow
    it)."""
    from openmiura.cli import main

    assert main(["verify", str(tmp_path / "does_not_exist.zip")]) == EXIT_USAGE
    pack = _write_pack(tmp_path, monkeypatch, real_key=True)
    assert main(["verify", str(pack)]) == EXIT_OK
    assert main(["verify", str(pack), "--json"]) == EXIT_OK


def test_json_output_is_stable(tmp_path: Path, monkeypatch, capsys) -> None:
    pack = _write_pack(tmp_path, monkeypatch, real_key=True)
    code = verify_pack_cli(pack=str(pack), json_output=True)
    assert code == EXIT_OK
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["verdict"] == "verified"
    assert parsed["authoritative"] is True
    assert set(["checks", "failures", "archive_sha256", "not_verified_offline"]).issubset(parsed.keys())
