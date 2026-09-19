"""Offline verifier — dev-seed guard and trust-anchor precedence.

Two defects found by an adversarial audit, both of which let a pack read as
VERIFIED + authoritative when it must not:

  * the dev-seed guard re-derived the public development key from the RAW
    ``signer_key_id`` while the signature binds the STRIPPED one, so a single
    leading space made the derivation miss. Combined with deleting the two
    unsigned ``dev_signing_key`` / ``signing_warning`` fields — which
    ``test_stripped_dev_seed_flag_is_still_detected`` already covers — the
    whole "re-derive rather than trust a flag" defence collapsed, and the dev
    seed is a public literal anyone can sign with.
  * ``--allow-dev-seed`` returned EXIT_OK without consulting ``trusted_signer``,
    so it silently overrode an explicit, non-matching ``--trust-anchor``.
"""
from __future__ import annotations

import base64
import io
import json
import zipfile
from pathlib import Path

from openmiura.evidence_verify import (
    EXIT_NON_AUTHORITATIVE,
    EXIT_OK,
    _dev_seed_public_fingerprint,
    verify_pack,
    verify_pack_cli,
)
from tests.test_cli_verify_pack import _write_pack, _entry, _rezip


def test_dev_seed_derivation_ignores_surrounding_whitespace() -> None:
    """The guard must key off the same value the signature is bound to."""
    assert _dev_seed_public_fingerprint("ci-key") == _dev_seed_public_fingerprint("ci-key")
    # The derivation itself is whitespace-sensitive by construction; what
    # matters is that verify_pack feeds it the stripped form (below).
    assert _dev_seed_public_fingerprint(" ci-key ") != _dev_seed_public_fingerprint("ci-key")


def test_padded_signer_key_id_cannot_launder_a_dev_seed_pack(tmp_path: Path, monkeypatch) -> None:
    """A space in signer_key_id must not turn a dev-seed pack authoritative."""
    pack = _write_pack(tmp_path, monkeypatch, real_key=False)
    data = pack.read_bytes()

    honest = verify_pack(pack)
    assert honest["dev_signing_key"] is True
    assert honest["authoritative"] is False

    integrity = _entry(data, "integrity.json")
    # Strip the two UNSIGNED giveaway fields...
    integrity["public_key"].pop("dev_signing_key", None)
    integrity["public_key"].pop("signing_warning", None)
    # ...and pad the signer_key_id, which the signing input strips anyway.
    integrity["signer_key_id"] = f" {integrity['signer_key_id']} "
    laundered = tmp_path / "laundered.zip"
    laundered.write_bytes(_rezip(data, {"integrity.json": integrity}))

    result = verify_pack(laundered)
    # The signature still verifies (the signing input strips the key id)...
    assert result["details"]["package_integrity"]["signature_valid"] is True
    # ...but the dev key must still be recognised by re-derivation.
    assert result["dev_key_fingerprint_match"] is True, "padding defeated the dev-seed guard"
    assert result["dev_signing_key"] is True
    assert result["authoritative"] is False
    assert verify_pack_cli(pack=str(laundered)) == EXIT_NON_AUTHORITATIVE


def test_allow_dev_seed_does_not_override_a_failing_trust_anchor(tmp_path: Path, monkeypatch) -> None:
    """An explicit signer pin outranks the local-dev convenience flag."""
    pack = _write_pack(tmp_path, monkeypatch, real_key=False)
    foreign = "11" * 32

    # Without an anchor the flag is allowed to accept a dev-seed pack.
    assert verify_pack_cli(pack=str(pack), allow_dev_seed=True) == EXIT_OK
    # With a non-matching anchor it must not.
    assert verify_pack_cli(pack=str(pack), trust_anchor=(foreign,)) == EXIT_NON_AUTHORITATIVE
    assert verify_pack_cli(
        pack=str(pack), trust_anchor=(foreign,), allow_dev_seed=True
    ) == EXIT_NON_AUTHORITATIVE


def test_allow_dev_seed_still_works_with_a_matching_anchor(tmp_path: Path, monkeypatch) -> None:
    """The guard must not break the legitimate combination."""
    pack = _write_pack(tmp_path, monkeypatch, real_key=False)
    result = verify_pack(pack)
    fingerprint = result["details"]["package_integrity"]["public_key_fingerprint"]
    assert verify_pack_cli(
        pack=str(pack), trust_anchor=(fingerprint,), allow_dev_seed=True
    ) == EXIT_OK
