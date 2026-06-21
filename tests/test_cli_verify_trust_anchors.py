"""Trust anchors for `openmiura verify` — binding a pack to a *known* signer.

The base verifier (test_cli_verify_pack) proves a pack is internally
consistent and signed by *whoever* held the embedded key. That stops at
"untampered"; it does not prove *who* signed it — a forged pack signed with
an attacker's own real Ed25519 key passes every consistency check.

`--trust-anchor` closes that gap: when one or more anchors are supplied, a
pack is AUTHORITATIVE only if the key the signature actually verified against
(by fingerprint — not the self-reported metadata) is one of them. These
tests pin:

  * matching anchor (hex / PEM file / fingerprint file) → authoritative, exit 0;
  * non-matching anchor → non-authoritative, exit 2 (and --allow-dev-seed does
    NOT rescue it — it is not a dev seed);
  * no anchor → behaviour identical to before (authenticity-of-signer unchecked);
  * a dev-seed pack stays non-authoritative even if its own key is anchored
    (the worthless-key guard dominates);
  * a typo'd anchor is a loud usage error, never a silent "trust nobody".
"""
from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa

from openmiura.evidence_verify import (
    EXIT_NON_AUTHORITATIVE,
    EXIT_OK,
    EXIT_USAGE,
    _der_fingerprint,
    _raw_ed25519_fingerprint,
    _resolve_trust_anchors,
    verify_pack,
    verify_pack_cli,
)
from tests.test_cli_verify_pack import _entry, _write_pack

_OTHER_FP = "00" * 32  # a valid-shaped fingerprint that is not the signer's


def _pub_pem(public_key) -> str:
    return public_key.public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")


def _signer_fingerprint(pack: Path) -> str:
    fp = verify_pack(pack)["public_key_fingerprint"]
    assert fp, "real-key pack must expose its verified-key fingerprint"
    return fp


# ==================================================================
# verify_pack — the trust-anchor verdict.
# ==================================================================


def test_matching_hex_anchor_is_authoritative(tmp_path: Path, monkeypatch) -> None:
    pack = _write_pack(tmp_path, monkeypatch, real_key=True)
    fp = _signer_fingerprint(pack)
    result = verify_pack(pack, trust_anchors={fp})
    assert result["trust_anchor_checked"] is True
    assert result["trusted_signer"] is True
    assert result["authoritative"] is True
    assert verify_pack_cli(pack=str(pack), trust_anchor=(fp,)) == EXIT_OK


def test_non_matching_anchor_is_non_authoritative(tmp_path: Path, monkeypatch) -> None:
    pack = _write_pack(tmp_path, monkeypatch, real_key=True)
    result = verify_pack(pack, trust_anchors={_OTHER_FP})
    # The pack is still internally consistent and cryptographically signed...
    assert result["consistent"] is True
    assert result["cryptographically_signed"] is True
    # ...but the signer is not trusted, so it is NOT authoritative.
    assert result["trust_anchor_checked"] is True
    assert result["trusted_signer"] is False
    assert result["authoritative"] is False
    assert verify_pack_cli(pack=str(pack), trust_anchor=(_OTHER_FP,)) == EXIT_NON_AUTHORITATIVE
    # An untrusted signer is not a dev seed — --allow-dev-seed must not rescue it.
    assert (
        verify_pack_cli(pack=str(pack), trust_anchor=(_OTHER_FP,), allow_dev_seed=True)
        == EXIT_NON_AUTHORITATIVE
    )


def test_no_anchor_leaves_behaviour_unchanged(tmp_path: Path, monkeypatch) -> None:
    pack = _write_pack(tmp_path, monkeypatch, real_key=True)
    result = verify_pack(pack)  # no trust_anchors
    assert result["trust_anchor_checked"] is False
    assert result["trusted_signer"] is None
    assert result["authoritative"] is True
    assert verify_pack_cli(pack=str(pack)) == EXIT_OK


def test_dev_seed_pack_stays_non_authoritative_even_if_anchored(tmp_path: Path, monkeypatch) -> None:
    """Anchoring the dev key must NOT promote a dev-seed pack to authoritative:
    the key is public, so a matching anchor is meaningless. The worthless-key
    guard dominates the trust-anchor check."""
    pack = _write_pack(tmp_path, monkeypatch, real_key=False)
    dev_fp = verify_pack(pack)["public_key_fingerprint"]
    result = verify_pack(pack, trust_anchors={dev_fp})
    assert result["dev_signing_key"] is True
    # The fingerprint genuinely matches the anchor...
    assert result["trusted_signer"] is True
    # ...yet the dev-seed guard keeps it non-authoritative.
    assert result["authoritative"] is False
    assert verify_pack_cli(pack=str(pack), trust_anchor=(dev_fp,)) == EXIT_NON_AUTHORITATIVE


# ==================================================================
# Anchor resolution — PEM file, fingerprint file, hex, errors.
# ==================================================================


def test_pem_file_anchor_resolves_to_signer(tmp_path: Path, monkeypatch) -> None:
    pack = _write_pack(tmp_path, monkeypatch, real_key=True)
    pem = _entry(pack.read_bytes(), "integrity.json")["public_key"]["public_key_pem"]
    pem_file = tmp_path / "signer.pem"
    pem_file.write_text(pem, encoding="utf-8")
    # The PEM resolves to the same fingerprint the verifier derives → trusted.
    assert _resolve_trust_anchors((str(pem_file),)) == {_signer_fingerprint(pack)}
    assert verify_pack_cli(pack=str(pack), trust_anchor=(str(pem_file),)) == EXIT_OK


def test_fingerprint_file_anchor_resolves(tmp_path: Path, monkeypatch) -> None:
    pack = _write_pack(tmp_path, monkeypatch, real_key=True)
    fp = _signer_fingerprint(pack)
    anchors_file = tmp_path / "trusted.txt"
    anchors_file.write_text(
        f"# trusted operator keys\n\n{fp}  # ci signer\n{_OTHER_FP}\n",
        encoding="utf-8",
    )
    resolved = _resolve_trust_anchors((str(anchors_file),))
    assert fp in resolved and _OTHER_FP in resolved
    assert verify_pack_cli(pack=str(pack), trust_anchor=(str(anchors_file),)) == EXIT_OK


def test_bare_hex_is_case_insensitive(tmp_path: Path, monkeypatch) -> None:
    pack = _write_pack(tmp_path, monkeypatch, real_key=True)
    fp = _signer_fingerprint(pack)
    # Fingerprints are lowercased on both sides, so an upper-case anchor matches.
    assert verify_pack_cli(pack=str(pack), trust_anchor=(fp.upper(),)) == EXIT_OK


def test_multiple_anchors_match_if_any_matches(tmp_path: Path, monkeypatch) -> None:
    pack = _write_pack(tmp_path, monkeypatch, real_key=True)
    fp = _signer_fingerprint(pack)
    assert verify_pack_cli(pack=str(pack), trust_anchor=(_OTHER_FP, fp)) == EXIT_OK


def test_typoed_anchor_is_usage_error(tmp_path: Path, monkeypatch) -> None:
    pack = _write_pack(tmp_path, monkeypatch, real_key=True)
    # Neither a readable file nor a 64-char hex string → loud failure, never
    # a silent "no anchors → trust nobody → non-authoritative".
    assert verify_pack_cli(pack=str(pack), trust_anchor=("not-a-key",)) == EXIT_USAGE


def test_resolve_trust_anchors_rejects_bad_input(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        _resolve_trust_anchors(("xyz",))
    bad_file = tmp_path / "bad.txt"
    bad_file.write_text("not-hex-at-all\n", encoding="utf-8")
    with pytest.raises(ValueError):
        _resolve_trust_anchors((str(bad_file),))


def test_multi_key_pem_bundle_anchors_every_key(tmp_path: Path) -> None:
    """A bundle concatenating several PEM public keys must anchor ALL of them
    — not silently drop every key after the first."""
    ed_key = ed25519.Ed25519PrivateKey.generate().public_key()
    ec_key = ec.generate_private_key(ec.SECP256R1()).public_key()
    bundle = tmp_path / "trusted_signers.pem"
    bundle.write_text(_pub_pem(ed_key) + _pub_pem(ec_key), encoding="utf-8")
    resolved = _resolve_trust_anchors((str(bundle),))
    assert resolved == {_raw_ed25519_fingerprint(ed_key), _der_fingerprint(ec_key)}


def test_file_mixing_pem_and_hex_keeps_both(tmp_path: Path) -> None:
    ed_key = ed25519.Ed25519PrivateKey.generate().public_key()
    mixed = tmp_path / "anchors.txt"
    mixed.write_text(
        f"# operators\n{_OTHER_FP}\n{_pub_pem(ed_key)}\n",
        encoding="utf-8",
    )
    resolved = _resolve_trust_anchors((str(mixed),))
    assert resolved == {_OTHER_FP, _raw_ed25519_fingerprint(ed_key)}


def test_unsupported_pem_key_type_is_rejected(tmp_path: Path) -> None:
    """An RSA (or any non-Ed25519/EC) anchor can never match a pack; resolving
    it must raise, not silently produce an unmatchable fingerprint."""
    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048).public_key()
    pem_file = tmp_path / "rsa.pem"
    pem_file.write_text(_pub_pem(rsa_key), encoding="utf-8")
    with pytest.raises(ValueError):
        _resolve_trust_anchors((str(pem_file),))


def test_bare_hex_is_not_shadowed_by_same_named_file(tmp_path: Path, monkeypatch) -> None:
    """A well-formed 64-hex fingerprint is unambiguous: even if a file with
    that exact name exists in the CWD, the literal fingerprint wins."""
    monkeypatch.chdir(tmp_path)
    decoy = tmp_path / _OTHER_FP  # filename == the hex fingerprint
    decoy.write_text("ff" * 32 + "\n", encoding="utf-8")  # different content
    assert _resolve_trust_anchors((_OTHER_FP,)) == {_OTHER_FP}


def test_empty_anchor_value_is_loud_usage_error(tmp_path: Path, monkeypatch) -> None:
    """`--trust-anchor ""` must fail loudly (exit 3), never silently resolve to
    an empty set ('trust nobody') that downgrades a valid pack."""
    with pytest.raises(ValueError):
        _resolve_trust_anchors(("   ",))
    pack = _write_pack(tmp_path, monkeypatch, real_key=True)
    assert verify_pack_cli(pack=str(pack), trust_anchor=("",)) == EXIT_USAGE


def test_public_api_is_case_insensitive_for_direct_callers(tmp_path: Path, monkeypatch) -> None:
    """verify_pack() itself honours the case-insensitive contract — a direct
    caller passing an upper-case fingerprint set still matches."""
    pack = _write_pack(tmp_path, monkeypatch, real_key=True)
    fp = _signer_fingerprint(pack)
    result = verify_pack(pack, trust_anchors={fp.upper()})
    assert result["trusted_signer"] is True
    assert result["authoritative"] is True


# ==================================================================
# Human output surfaces the trust verdict.
# ==================================================================


def test_human_output_reports_trust_verdict(tmp_path: Path, monkeypatch, capsys) -> None:
    pack = _write_pack(tmp_path, monkeypatch, real_key=True)
    fp = _signer_fingerprint(pack)

    verify_pack_cli(pack=str(pack), trust_anchor=(fp,))
    assert "authenticity confirmed" in capsys.readouterr().out.lower()

    verify_pack_cli(pack=str(pack), trust_anchor=(_OTHER_FP,))
    out = capsys.readouterr().out.lower()
    assert "non-authoritative" in out and "trust anchor" in out
