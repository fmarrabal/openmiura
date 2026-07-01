"""`openmiura verify` — embedded RFC 3161 timestamp (TSA-PR2).

Builds a REAL evidence pack, timestamps its signature bytes with a local TSA
(the `build_timestamp_token` fixture), injects a `timestamp.json` entry, and
checks that `verify_pack` / the CLI verify it offline: a valid timestamp is
surfaced with its genTime; a supplied `--tsa-anchor` flips it to trusted; a
tampered signature breaks the timestamp; an absent entry yields no timestamp.
"""
from __future__ import annotations

import base64
import datetime as dt
import io
import json
import zipfile
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.x509.oid import NameOID

from openmiura.evidence_verify import EXIT_OK, EXIT_USAGE, verify_pack, verify_pack_cli
from openmiura.rfc3161 import build_timestamp_token
from tests.test_cli_verify_pack import _entry, _write_pack

_GEN = dt.datetime(2026, 6, 30, 12, 0, 0, tzinfo=dt.timezone.utc)


def _local_tsa():
    key = ed25519.Ed25519PrivateKey.generate()
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "openMiura Local TSA")])
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(7)
        .not_valid_before(_GEN - dt.timedelta(days=1)).not_valid_after(_GEN + dt.timedelta(days=365))
        .sign(key, None)
    )
    return key, cert


def _add_entry(original: bytes, name: str, obj: dict) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(original), "r") as zin:
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
            for n in zin.namelist():
                zout.writestr(n, zin.read(n))
            zout.writestr(name, json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2))
    return out.getvalue()


def _pack_with_timestamp(tmp_path, monkeypatch, *, key, cert, over_signature=None):
    pack = _write_pack(tmp_path, monkeypatch, real_key=True)
    data = pack.read_bytes()
    signature_b64 = _entry(data, "integrity.json")["signature"]
    covered = base64.b64decode((over_signature or signature_b64).encode("ascii"))
    token = build_timestamp_token(data=covered, gen_time=_GEN, private_key=key, certificate=cert, serial_number=11)
    stamped = tmp_path / "stamped.zip"
    stamped.write_bytes(_add_entry(data, "timestamp.json", {
        "format": "rfc3161",
        "covers": "integrity.signature",
        "token_b64": base64.b64encode(token).decode("ascii"),
    }))
    return stamped, cert


def test_valid_timestamp_is_verified_and_trusted(tmp_path, monkeypatch):
    key, cert = _local_tsa()
    pack, cert = _pack_with_timestamp(tmp_path, monkeypatch, key=key, cert=cert)
    anchor = cert.public_bytes(Encoding.DER)
    result = verify_pack(pack, tsa_trust_anchors=[anchor])
    ts = result["timestamp"]
    assert ts is not None and ts["valid"] is True
    assert ts["trusted"] is True
    assert ts["gen_time"] == "2026-06-30T12:00:00+00:00"


def test_timestamp_without_anchor_is_valid_but_untrusted_axis(tmp_path, monkeypatch):
    key, cert = _local_tsa()
    pack, _ = _pack_with_timestamp(tmp_path, monkeypatch, key=key, cert=cert)
    ts = verify_pack(pack)["timestamp"]
    assert ts["valid"] is True and ts["trusted"] is None


def test_absent_timestamp_is_none(tmp_path, monkeypatch):
    pack = _write_pack(tmp_path, monkeypatch, real_key=True)
    assert verify_pack(pack)["timestamp"] is None


def test_timestamp_over_wrong_signature_is_invalid(tmp_path, monkeypatch):
    key, cert = _local_tsa()
    # Stamp a DIFFERENT signature than the pack actually carries → imprint fails.
    pack, _ = _pack_with_timestamp(
        tmp_path, monkeypatch, key=key, cert=cert,
        over_signature=base64.b64encode(b"some-other-signature").decode("ascii"),
    )
    ts = verify_pack(pack)["timestamp"]
    assert ts["valid"] is False and ts["imprint_match"] is False


def test_cli_tsa_anchor_flag(tmp_path, monkeypatch):
    key, cert = _local_tsa()
    pack, cert = _pack_with_timestamp(tmp_path, monkeypatch, key=key, cert=cert)
    cert_file = tmp_path / "tsa.pem"
    cert_file.write_bytes(cert.public_bytes(Encoding.PEM))
    # The pack is real-key signed → authoritative → exit 0; timestamp is extra.
    assert verify_pack_cli(pack=str(pack), tsa_anchor=(str(cert_file),)) == EXIT_OK


def test_cli_bad_tsa_anchor_is_usage_error(tmp_path, monkeypatch):
    pack = _write_pack(tmp_path, monkeypatch, real_key=True)
    assert verify_pack_cli(pack=str(pack), tsa_anchor=(str(tmp_path / "nope.pem"),)) == EXIT_USAGE
