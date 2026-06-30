"""RFC 3161 trusted timestamps — offline verification (and a local issuer).

A TimeStampToken is a CMS ``SignedData`` whose encapsulated content is a
``TSTInfo`` (RFC 3161 §2.4.2): it binds a hash of some data to a time
(``genTime``), signed by a Timestamping Authority (TSA). Verifying one OFFLINE
proves *when* the data existed without contacting anyone — the last "needs a
time reference" leg of the openMiura evidence-pack verification chain.

This module:
  * ``verify_timestamp_token`` — parse + verify a token against the data it
    should cover, checking the message imprint, the CMS signer signature, and
    (optionally) that the signer is a trusted TSA. Never raises for a bad
    token; problems are reported in the result.
  * ``build_timestamp_token`` — produce a token with a local key/cert. This is
    what a TSA does; openMiura uses it as a fixture in tests and as an optional
    *local* (self-asserted, non-authoritative unless trusted) timestamp source.

``asn1crypto`` (MIT) supplies the TSP/CMS ASN.1 structures; ``cryptography``
verifies the signer's certificate signature.
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from asn1crypto import algos, cms, core, tsp
from asn1crypto import x509 as asn1_x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, padding, rsa
from cryptography.x509 import load_der_x509_certificate

_HASHES = {"sha256": hashlib.sha256, "sha384": hashlib.sha384, "sha512": hashlib.sha512}
_CRYPTO_HASHES = {"sha256": hashes.SHA256, "sha384": hashes.SHA384, "sha512": hashes.SHA512}
_DEFAULT_POLICY = "1.3.6.1.4.1.58306.1"  # openMiura local-TSA policy OID (private arc)


def _digest(name: str, data: bytes) -> bytes:
    fn = _HASHES.get(name)
    if fn is None:
        raise ValueError(f"unsupported hash algorithm: {name}")
    return fn(data).digest()


def _signed_attrs_der_for_signing(signed_attrs: cms.CMSAttributes) -> bytes:
    """The bytes a CMS signature covers: the SignedAttributes DER re-tagged
    from the implicit ``[0]`` (0xA0) context tag to a universal SET (0x31)."""
    raw = signed_attrs.dump()
    return b"\x31" + raw[1:]


def _attr_value(signed_attrs: cms.CMSAttributes, name: str) -> Any:
    for attr in signed_attrs:
        if attr["type"].native == name:
            values = attr["values"]
            return values[0].native if len(values) else None
    return None


def _cert_fingerprint(cert_der: bytes) -> str:
    return hashlib.sha256(cert_der).hexdigest()


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def _verify_cms_signature(public_key: Any, signature: bytes, message: bytes, sig_alg: str, hash_name: str) -> bool:
    try:
        if isinstance(public_key, ed25519.Ed25519PublicKey):
            public_key.verify(signature, message)
            return True
        hash_cls = _CRYPTO_HASHES.get(hash_name)
        if hash_cls is None:
            return False
        if isinstance(public_key, rsa.RSAPublicKey):
            public_key.verify(signature, message, padding.PKCS1v15(), hash_cls())
            return True
        if isinstance(public_key, ec.EllipticCurvePublicKey):
            public_key.verify(signature, message, ec.ECDSA(hash_cls()))
            return True
        return False
    except (InvalidSignature, ValueError, TypeError):
        return False


def _find_signer_cert(sd: cms.SignedData, signer_info: cms.SignerInfo) -> asn1_x509.Certificate | None:
    certs = [c.chosen for c in sd["certificates"] if c.name == "certificate"]
    sid = signer_info["sid"]
    if sid.name == "issuer_and_serial_number":
        want_serial = sid.chosen["serial_number"].native
        want_issuer = sid.chosen["issuer"]
        for cert in certs:
            if cert["tbs_certificate"]["serial_number"].native == want_serial and cert.issuer == want_issuer:
                return cert
    else:  # subject_key_identifier
        want_ski = sid.chosen.native
        for cert in certs:
            if cert.key_identifier == want_ski:
                return cert
    return certs[0] if certs else None


def _is_trusted(signer_cert: asn1_x509.Certificate, trusted_certs: list[bytes]) -> bool:
    signer_der = signer_cert.dump()
    signer_fp = _cert_fingerprint(signer_der)
    for anchor_der in trusted_certs:
        if _cert_fingerprint(anchor_der) == signer_fp:
            return True  # signer IS the trusted TSA cert
    # One-level issuer check: signer cert directly issued by a trusted CA.
    # The signature on the signer leaf is made with the ANCHOR's key; the args
    # come from the anchor key type + the leaf's signature hash.
    crypto_signer = load_der_x509_certificate(signer_der)
    for anchor_der in trusted_certs:
        try:
            anchor_pub = load_der_x509_certificate(anchor_der).public_key()
            sig = crypto_signer.signature
            tbs = crypto_signer.tbs_certificate_bytes
            if isinstance(anchor_pub, ed25519.Ed25519PublicKey):
                anchor_pub.verify(sig, tbs)
            elif isinstance(anchor_pub, ec.EllipticCurvePublicKey):
                anchor_pub.verify(sig, tbs, ec.ECDSA(crypto_signer.signature_hash_algorithm))
            elif isinstance(anchor_pub, rsa.RSAPublicKey):
                anchor_pub.verify(sig, tbs, padding.PKCS1v15(), crypto_signer.signature_hash_algorithm)
            else:
                continue
            return True
        except Exception:
            continue
    return False


def verify_timestamp_token(
    *,
    token_der: bytes,
    data: bytes,
    trusted_tsa_certs: list[bytes] | None = None,
) -> dict[str, Any]:
    """Verify an RFC 3161 token offline against ``data``.

    Returns a structured result. ``valid`` is True when the token is a
    well-formed TSTInfo whose imprint matches ``data`` and whose CMS signature
    verifies. ``trusted`` is None when no anchors are supplied, else whether
    the signer is (or chains to) a supplied trusted TSA cert.
    """
    result: dict[str, Any] = {
        "valid": False,
        "imprint_match": False,
        "signature_valid": False,
        "trusted": None,
        "gen_time": None,
        "tsa": None,
        "serial_number": None,
        "error": None,
    }
    try:
        content_info = cms.ContentInfo.load(token_der)
        if content_info["content_type"].native != "signed_data":
            result["error"] = "not_a_signed_data_token"
            return result
        sd = content_info["content"]
        eci = sd["encap_content_info"]
        if eci["content_type"].native != "tst_info":
            result["error"] = "encapsulated_content_is_not_tst_info"
            return result
        tst_info = eci["content"].parsed
        econtent_der = tst_info.dump()

        mi = tst_info["message_imprint"]
        hash_name = mi["hash_algorithm"]["algorithm"].native
        imprint_match = _digest(hash_name, data) == mi["hashed_message"].native
        result["imprint_match"] = imprint_match
        result["gen_time"] = tst_info["gen_time"].native.isoformat()
        result["serial_number"] = int(tst_info["serial_number"].native)

        signer_info = sd["signer_infos"][0]
        signer_cert = _find_signer_cert(sd, signer_info)
        if signer_cert is None:
            result["error"] = "no_signer_certificate"
            return result
        result["tsa"] = signer_cert.subject.human_friendly

        signed_attrs = signer_info["signed_attrs"]
        # Mandatory signed attrs must bind the eContent + its type.
        ct_attr = _attr_value(signed_attrs, "content_type")
        md_attr = _attr_value(signed_attrs, "message_digest")
        digest_name = signer_info["digest_algorithm"]["algorithm"].native
        attrs_bind = ct_attr == "tst_info" and md_attr == _digest(digest_name, econtent_der)

        crypto_cert = load_der_x509_certificate(signer_cert.dump())
        sig_alg = signer_info["signature_algorithm"]["algorithm"].native
        sig_hash = digest_name if "ed25519" not in sig_alg else ""
        signature_valid = attrs_bind and _verify_cms_signature(
            crypto_cert.public_key(),
            signer_info["signature"].native,
            _signed_attrs_der_for_signing(signed_attrs),
            sig_alg,
            sig_hash,
        )
        result["signature_valid"] = bool(signature_valid)

        if trusted_tsa_certs is not None:
            result["trusted"] = _is_trusted(signer_cert, list(trusted_tsa_certs))

        result["valid"] = bool(imprint_match and signature_valid)
        return result
    except Exception as exc:  # malformed token → reported, never raised
        result["error"] = f"{type(exc).__name__}:{exc}"
        return result


# ---------------------------------------------------------------------------
# Local issuance (test fixture / optional self-asserted timestamp source)
# ---------------------------------------------------------------------------


def build_timestamp_token(
    *,
    data: bytes,
    gen_time: datetime,
    private_key: Any,
    certificate: Any,
    serial_number: int = 1,
    hash_name: str = "sha256",
    policy_oid: str = _DEFAULT_POLICY,
) -> bytes:
    """Build an RFC 3161 TimeStampToken over ``data`` (what a TSA does).

    ``gen_time`` must be a timezone-aware UTC datetime; ``certificate`` /
    ``private_key`` are the ``cryptography`` cert + key of the (local) TSA.
    """
    imprint = tsp.MessageImprint({
        "hash_algorithm": algos.DigestAlgorithm({"algorithm": hash_name}),
        "hashed_message": _digest(hash_name, data),
    })
    tst_info = tsp.TSTInfo({
        "version": "v1",
        "policy": policy_oid,
        "message_imprint": imprint,
        "serial_number": serial_number,
        "gen_time": gen_time,
    })
    econtent_der = tst_info.dump()

    from cryptography.hazmat.primitives.serialization import Encoding

    asn1_cert = asn1_x509.Certificate.load(certificate.public_bytes(Encoding.DER))
    signed_attrs = cms.CMSAttributes([
        cms.CMSAttribute({"type": "content_type", "values": ["tst_info"]}),
        cms.CMSAttribute({"type": "message_digest", "values": [_digest(hash_name, econtent_der)]}),
    ])

    if isinstance(private_key, ed25519.Ed25519PrivateKey):
        sig_alg = "ed25519"
        signature = private_key.sign(_signed_attrs_der_for_signing(signed_attrs))
    elif isinstance(private_key, ec.EllipticCurvePrivateKey):
        sig_alg = f"{hash_name}_ecdsa"
        signature = private_key.sign(_signed_attrs_der_for_signing(signed_attrs), ec.ECDSA(_CRYPTO_HASHES[hash_name]()))
    else:  # RSA
        sig_alg = f"{hash_name}_rsa"
        signature = private_key.sign(_signed_attrs_der_for_signing(signed_attrs), padding.PKCS1v15(), _CRYPTO_HASHES[hash_name]())

    signer_info = cms.SignerInfo({
        "version": "v1",
        "sid": cms.SignerIdentifier({"issuer_and_serial_number": cms.IssuerAndSerialNumber({
            "issuer": asn1_cert.issuer,
            "serial_number": asn1_cert["tbs_certificate"]["serial_number"].native,
        })}),
        "digest_algorithm": algos.DigestAlgorithm({"algorithm": hash_name}),
        "signed_attrs": signed_attrs,
        "signature_algorithm": algos.SignedDigestAlgorithm({"algorithm": sig_alg}),
        "signature": signature,
    })
    signed_data = cms.SignedData({
        "version": "v3",
        "digest_algorithms": [algos.DigestAlgorithm({"algorithm": hash_name})],
        "encap_content_info": cms.EncapsulatedContentInfo({
            "content_type": "tst_info",
            "content": core.ParsableOctetString(econtent_der),
        }),
        "certificates": [asn1_cert],
        "signer_infos": [signer_info],
    })
    return cms.ContentInfo({"content_type": "signed_data", "content": signed_data}).dump()
