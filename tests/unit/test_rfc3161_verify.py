"""RFC 3161 trusted-timestamp offline verification.

Builds real TimeStampTokens with a local TSA cert/key (the ``build_*`` /
``verify_*`` round-trip a real TSA would produce) and pins: a valid token
verifies and its genTime is recovered; tampering the data or the token breaks
it; ``trusted`` is a SEPARATE axis (signer is/ isn't a supplied TSA anchor,
including the issued-by-a-trusted-CA case); RSA/EC/Ed25519 TSAs all work; a
malformed token is reported, never raised.
"""
from __future__ import annotations

import datetime as dt

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.x509.oid import NameOID

from openmiura.rfc3161 import build_timestamp_token, verify_timestamp_token

_NOW = dt.datetime(2026, 6, 30, 12, 0, 0, tzinfo=dt.timezone.utc)
_DATA = b"openmiura-evidence-pack-archive"


def _name(cn):
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def _self_signed(key, *, cn="openMiura Test TSA", serial=1234, sig_hash=hashes.SHA256()):
    n = _name(cn)
    builder = (
        x509.CertificateBuilder().subject_name(n).issuer_name(n)
        .public_key(key.public_key()).serial_number(serial)
        .not_valid_before(_NOW - dt.timedelta(days=1)).not_valid_after(_NOW + dt.timedelta(days=365))
    )
    return builder.sign(key, None if isinstance(key, ed25519.Ed25519PrivateKey) else sig_hash)


def _der(cert):
    return cert.public_bytes(Encoding.DER)


def _ed25519_tsa():
    key = ed25519.Ed25519PrivateKey.generate()
    return key, _self_signed(key)


def test_valid_token_verifies_and_recovers_gentime():
    key, cert = _ed25519_tsa()
    token = build_timestamp_token(data=_DATA, gen_time=_NOW, private_key=key, certificate=cert, serial_number=99)
    r = verify_timestamp_token(token_der=token, data=_DATA, trusted_tsa_certs=[_der(cert)])
    assert r["valid"] is True
    assert r["imprint_match"] is True and r["signature_valid"] is True
    assert r["trusted"] is True
    assert r["gen_time"] == "2026-06-30T12:00:00+00:00"
    assert r["serial_number"] == 99
    assert r["error"] is None


def test_no_anchor_leaves_trusted_none():
    key, cert = _ed25519_tsa()
    token = build_timestamp_token(data=_DATA, gen_time=_NOW, private_key=key, certificate=cert)
    r = verify_timestamp_token(token_der=token, data=_DATA)
    assert r["valid"] is True and r["trusted"] is None


def test_tampered_data_fails_imprint():
    key, cert = _ed25519_tsa()
    token = build_timestamp_token(data=_DATA, gen_time=_NOW, private_key=key, certificate=cert)
    r = verify_timestamp_token(token_der=token, data=_DATA + b"x")
    assert r["valid"] is False and r["imprint_match"] is False


def test_untrusted_signer_is_valid_but_not_trusted():
    key, cert = _ed25519_tsa()
    token = build_timestamp_token(data=_DATA, gen_time=_NOW, private_key=key, certificate=cert)
    other_key, other_cert = _ed25519_tsa()
    r = verify_timestamp_token(token_der=token, data=_DATA, trusted_tsa_certs=[_der(other_cert)])
    assert r["valid"] is True       # the token itself is internally valid...
    assert r["trusted"] is False    # ...but the signer is not a trusted TSA


def test_tampered_signature_fails():
    key, cert = _ed25519_tsa()
    token = bytearray(build_timestamp_token(data=_DATA, gen_time=_NOW, private_key=key, certificate=cert))
    token[-1] ^= 0xFF  # flip a byte in the trailing signature region
    r = verify_timestamp_token(token_der=bytes(token), data=_DATA)
    assert r["valid"] is False


def test_malformed_token_is_reported_not_raised():
    r = verify_timestamp_token(token_der=b"not a der token", data=_DATA)
    assert r["valid"] is False and r["error"]


@pytest.mark.parametrize("kind", ["rsa", "ec"])
def test_rsa_and_ec_tsa_round_trip(kind):
    if kind == "rsa":
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    else:
        key = ec.generate_private_key(ec.SECP256R1())
    cert = _self_signed(key, cn=f"openMiura {kind} TSA", serial=55)
    token = build_timestamp_token(data=_DATA, gen_time=_NOW, private_key=key, certificate=cert)
    r = verify_timestamp_token(token_der=token, data=_DATA, trusted_tsa_certs=[_der(cert)])
    assert r["valid"] is True and r["trusted"] is True


def test_trust_via_issuing_ca():
    """A TSA cert ISSUED BY a trusted CA is trusted even though the CA cert,
    not the TSA leaf, is the supplied anchor."""
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_cert = _self_signed(ca_key, cn="openMiura Test CA", serial=1)

    tsa_key = ed25519.Ed25519PrivateKey.generate()
    tsa_cert = (
        x509.CertificateBuilder().subject_name(_name("openMiura Issued TSA")).issuer_name(ca_cert.subject)
        .public_key(tsa_key.public_key()).serial_number(2)
        .not_valid_before(_NOW - dt.timedelta(days=1)).not_valid_after(_NOW + dt.timedelta(days=365))
        .sign(ca_key, hashes.SHA256())
    )
    token = build_timestamp_token(data=_DATA, gen_time=_NOW, private_key=tsa_key, certificate=tsa_cert)
    r = verify_timestamp_token(token_der=token, data=_DATA, trusted_tsa_certs=[_der(ca_cert)])
    assert r["valid"] is True and r["trusted"] is True
