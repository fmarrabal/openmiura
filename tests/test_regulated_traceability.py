"""The regulated traceability matrix must stay honest.

`docs/regulated/traceability_matrix.md` links each regulatory control to the
test(s) that evidence it. This test parses every `tests/...` glob cited in that
matrix and fails if any no longer matches a real test file — so the matrix
cannot silently rot as tests are renamed or removed.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "docs" / "regulated" / "traceability_matrix.md"

# Backticked tokens that look like a test path/glob under tests/.
_CITATION = re.compile(r"`(tests/[^`]+\.py)`")


def _cited_globs() -> list[str]:
    text = MATRIX.read_text(encoding="utf-8")
    # Preserve order, de-dupe.
    seen: dict[str, None] = {}
    for m in _CITATION.finditer(text):
        seen.setdefault(m.group(1), None)
    return list(seen)


def test_matrix_exists_and_is_linked() -> None:
    assert MATRIX.exists()
    index = (ROOT / "docs" / "regulated" / "README.md").read_text(encoding="utf-8")
    assert "traceability_matrix.md" in index, "matrix must be linked from docs/regulated/README.md"


def test_every_cited_test_glob_resolves() -> None:
    globs = _cited_globs()
    assert len(globs) >= 10, f"matrix cites suspiciously few tests: {len(globs)}"
    missing = [g for g in globs if not list(ROOT.glob(g))]
    assert not missing, f"traceability matrix cites tests that no longer exist: {missing}"


def test_new_capability_evidence_is_present() -> None:
    """The controls strengthened by the signature-grade / hash-chain / RFC 3161
    work must cite their evidence — guards against gutting the matrix."""
    text = MATRIX.read_text(encoding="utf-8")
    for token in (
        "test_sig_approvals_",     # signature-grade approvals
        "test_audit_hashchain_",   # tamper-evident audit trail
        "test_rfc3161_",           # trusted timestamp
        "test_cli_verify_",        # offline pack verification
    ):
        assert token in text, f"matrix no longer cites {token}* evidence"
