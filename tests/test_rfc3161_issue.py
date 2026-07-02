"""RFC 3161 issuance — TSA client + pack timestamping (TSA-PR3).

Uses an httpx MockTransport as a fake TSA (it parses the TimeStampReq and
returns a TimeStampResp wrapping a token built with a local TSA key), so the
client + `add_timestamp_to_pack` + `openmiura timestamp` round-trip is exercised
offline and the resulting pack verifies.
"""
from __future__ import annotations

import datetime as dt

import httpx
import pytest
from asn1crypto import cms, tsp
from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.x509.oid import NameOID

from openmiura.evidence_verify import EXIT_FAILED, EXIT_OK, EXIT_USAGE, timestamp_pack_cli, verify_pack
from openmiura.rfc3161 import add_timestamp_to_pack, build_timestamp_token, request_timestamp, verify_timestamp_token
from tests.test_cli_verify_pack import _write_pack

_GEN = dt.datetime(2026, 6, 30, 12, 0, 0, tzinfo=dt.timezone.utc)


def _local_tsa():
    key = ed25519.Ed25519PrivateKey.generate()
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "MockTSA")])
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(7)
        .not_valid_before(_GEN - dt.timedelta(days=1)).not_valid_after(_GEN + dt.timedelta(days=365))
        .sign(key, None)
    )
    return key, cert


def _mock_tsa_client(key, cert, *, granted=True):
    def handler(request: httpx.Request) -> httpx.Response:
        req = tsp.TimeStampReq.load(request.content)
        imprint = req["message_imprint"]["hashed_message"].native
        if not granted:
            resp = tsp.TimeStampResp({"status": tsp.PKIStatusInfo({"status": "rejection"})})
            return httpx.Response(200, content=resp.dump())
        token = build_timestamp_token(hashed_message=imprint, gen_time=_GEN, private_key=key, certificate=cert, serial_number=5)
        resp = tsp.TimeStampResp({
            "status": tsp.PKIStatusInfo({"status": "granted"}),
            "time_stamp_token": cms.ContentInfo.load(token),
        })
        return httpx.Response(200, content=resp.dump())

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_request_timestamp_round_trip():
    key, cert = _local_tsa()
    data = b"pack-signature-bytes"
    with _mock_tsa_client(key, cert) as client:
        token = request_timestamp(data=data, tsa_url="https://tsa.example/tsr", http_client=client)
    r = verify_timestamp_token(token_der=token, data=data, trusted_tsa_certs=[cert.public_bytes(Encoding.DER)])
    assert r["valid"] is True and r["trusted"] is True


def test_request_timestamp_rejected_raises():
    key, cert = _local_tsa()
    with _mock_tsa_client(key, cert, granted=False) as client:
        with pytest.raises(ValueError):
            request_timestamp(data=b"x", tsa_url="https://tsa.example/tsr", http_client=client)


def test_add_timestamp_to_pack_via_tsa(tmp_path, monkeypatch):
    key, cert = _local_tsa()
    pack = _write_pack(tmp_path, monkeypatch, real_key=True)
    with _mock_tsa_client(key, cert) as client:
        stamped = add_timestamp_to_pack(pack.read_bytes(), tsa_url="https://tsa.example/tsr", http_client=client)
    out = tmp_path / "stamped.zip"
    out.write_bytes(stamped)
    ts = verify_pack(out, tsa_trust_anchors=[cert.public_bytes(Encoding.DER)])["timestamp"]
    assert ts["valid"] is True and ts["trusted"] is True


def test_add_timestamp_to_pack_via_local_signer(tmp_path, monkeypatch):
    key, cert = _local_tsa()
    pack = _write_pack(tmp_path, monkeypatch, real_key=True)
    stamped = add_timestamp_to_pack(pack.read_bytes(), local_signer=(key, cert, _GEN))
    out = tmp_path / "stamped2.zip"
    out.write_bytes(stamped)
    assert verify_pack(out)["timestamp"]["valid"] is True


def test_timestamp_cli_writes_verifiable_pack(tmp_path, monkeypatch):
    key, cert = _local_tsa()
    pack = _write_pack(tmp_path, monkeypatch, real_key=True)
    out = tmp_path / "cli_stamped.zip"
    with _mock_tsa_client(key, cert) as client:
        code = timestamp_pack_cli(pack=str(pack), tsa_url="https://tsa.example/tsr", output=str(out), http_client=client)
    assert code == EXIT_OK
    ts = verify_pack(out, tsa_trust_anchors=[cert.public_bytes(Encoding.DER)])["timestamp"]
    assert ts["valid"] is True and ts["trusted"] is True


def test_timestamp_cli_usage_errors(tmp_path):
    assert timestamp_pack_cli(pack="whatever.zip", tsa_url=None) == EXIT_USAGE
    assert timestamp_pack_cli(pack=str(tmp_path / "missing.zip"), tsa_url="https://tsa.example/tsr") == EXIT_USAGE
