"""Tests for the JCAMP-DX ASDF compression decoder (H2.1).

The decoder ships as a JS module
(``openmiura/ui/v2/static/js/science/nmr_asdf.js``) that runs
in the browser. To exercise the algorithm from pytest we use
the Python reference twin at ``tests/unit/_asdf_reference.py``;
these tests pin the algorithm AND verify that the JS module
declares the same char-class tables so the two
implementations don't drift.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import pytest

from tests.unit._asdf_reference import (
    DUP_TOK,
    DIF_NEG,
    DIF_POS,
    SQZ_NEG,
    SQZ_POS,
    decode_asdf_line,
    evaluate_asdf_tokens,
    line_has_asdf,
    tokenize_asdf,
)

ROOT = Path(__file__).resolve().parents[2]
JS_ASDF = ROOT / "openmiura" / "ui" / "v2" / "static" / "js" / "science" / "nmr_asdf.js"
FIXTURE = ROOT / "tests" / "fixtures" / "nmr_asdf_synthetic.jdx"


# ------------------------------------------------------------------
# line_has_asdf — detection
# ------------------------------------------------------------------


def test_detects_asdf_in_sqz_only_line():
    assert line_has_asdf("E0 V I5") is True


def test_detects_asdf_in_pure_diff_line():
    assert line_has_asdf("J5 K2 L1") is True


def test_does_not_flag_plain_numeric_line():
    assert line_has_asdf("10.0 5 10 95") is False
    assert line_has_asdf("") is False
    # NOTE: scientific notation ``1.23e-4`` contains the
    # letter ``e`` which IS in SQZ_NEG; the upstream parser
    # only calls line_has_asdf on data lines (never on
    # headers where scientific notation appears), so we
    # accept that false positive consciously.


# ------------------------------------------------------------------
# SQZ — absolute values
# ------------------------------------------------------------------


@pytest.mark.parametrize(("token", "expected"), [
    ("@0",  0),    # @ = +0
    ("A",   1),    # A = +1, no trailing digits
    ("A0",  10),   # A=+1, '0' tail → 10
    ("I9",  99),   # I=+9, '9' tail → 99
    ("I99", 999), # I=+9, '99' tail → 999
    ("a",  -1),
    ("a5", -15),
    ("i9", -99),
])
def test_sqz_token_decodes_to_absolute_value(token, expected):
    result = tokenize_asdf(token)
    assert len(result.tokens) == 1
    tok = result.tokens[0]
    assert tok.kind == "abs"
    assert tok.value == expected


def test_multiple_sqz_tokens_back_to_back():
    """No whitespace required between SQZ tokens; the next
    upper/lower letter starts a new number.

    E5  → letter E (=+5 first digit) + trailing '5' → +55
    A0  → letter A (=+1 first digit) + trailing '0' → +10
    b3  → letter b (=-2 first digit) + trailing '3' → -23
    """
    result = tokenize_asdf("E5A0b3")
    assert [t.value for t in result.tokens] == [55, 10, -23]


# ------------------------------------------------------------------
# DIF — differences accumulate from previous Y
# ------------------------------------------------------------------


@pytest.mark.parametrize(("token", "delta"), [
    ("%",  0),   # % = +0
    ("J",  1),   # J = +1
    ("R9", 99),  # R=+9, '9' tail → +99
    ("j",  -1),
    ("r9", -99),
])
def test_dif_token_carries_delta(token, delta):
    result = tokenize_asdf(token)
    assert result.tokens[0].kind == "dif"
    assert result.tokens[0].value == delta


def test_dif_chain_accumulates_against_prev_y():
    # SQZ first to establish baseline, then DIF.
    # In ASDF the letter is the FIRST digit and trailing
    # plain digits extend the number:
    #   E0 → letter E (+5 first digit) + '0' tail → +50
    #   J0 → letter J (DIF +1) + '0' tail → +10 delta
    #   K0 → letter K (DIF +2) + '0' tail → +20 delta
    #   L0 → letter L (DIF +3) + '0' tail → +30 delta
    line = "E0 J0 J0 K0 K0 L0"
    res = decode_asdf_line(line, prev_last_y=None)
    # 50 → 60 → 70 → 90 → 110 → 140
    assert res.ys == [50, 60, 70, 90, 110, 140]
    assert res.last_y == 140


def test_dif_at_line_start_uses_prev_lastY_as_baseline():
    """The first token of a line is conventionally SQZ
    (absolute), but a strict DIF-only line is legal: it
    continues the previous line's last Y."""
    res = decode_asdf_line("J0 J0", prev_last_y=50)
    # +10 + 50 = 60; +10 + 60 = 70
    assert res.ys == [60, 70]


def test_dif_without_baseline_warns_but_decodes_as_abs():
    """If we ever see a DIF token before any baseline (no
    previous Y from this or the previous line), we treat it
    as absolute and emit a warning. Better than silently
    dropping the value."""
    res = decode_asdf_line("J5", prev_last_y=None)
    assert res.ys == [15]
    assert any("DIF token at line start" in w for w in res.warnings)


# ------------------------------------------------------------------
# DUP — duplicate counts
# ------------------------------------------------------------------


@pytest.mark.parametrize(("token", "count"), [
    ("S", 1),
    ("T", 2),
    ("U", 3),
    ("V", 4),
    ("W", 5),
    ("X", 6),
    ("Y", 7),
    ("Z", 8),
    ("s", 9),
])
def test_dup_token_count(token, count):
    result = tokenize_asdf(token)
    assert result.tokens[0].kind == "dup"
    assert result.tokens[0].count == count


def test_dup_after_sqz_repeats_value():
    """DUP after an SQZ (abs) value repeats it verbatim N
    times. Total values emitted = 1 (the SQZ) + N (the DUPs).

    E (=+5 with no trailing digits) + V (=4 dups) → 5 values.
    """
    res = decode_asdf_line("E V", prev_last_y=None)
    assert res.ys == [5, 5, 5, 5, 5]


def test_dup_after_dif_continues_arithmetic_progression():
    """DUP after a DIF continues the *delta* — emits an
    arithmetic progression. This is the strict-ASDF reading
    and the one real Bruker exports use.

    E (+5 abs) → 5
    J5 (DIF +15) → 5+15 = 20
    V (4 dups continuing +15 delta) → 35, 50, 65, 80
    """
    res = decode_asdf_line("E J5 V", prev_last_y=None)
    assert res.ys == [5, 20, 35, 50, 65, 80]


def test_dup_without_baseline_warns_and_skips():
    res = decode_asdf_line("S", prev_last_y=None)
    assert res.ys == []
    assert any("DUP token at line start" in w for w in res.warnings)


# ------------------------------------------------------------------
# X++(Y..Y) line format
# ------------------------------------------------------------------


def test_decode_line_extracts_leading_X():
    """Matches the synthetic fixture's line 1.

    E   = +5 abs
    W   = 5 dups → 5,5,5,5,5
    I5  = +95 abs (letter I = +9 first digit, '5' tail → +95)
    """
    res = decode_asdf_line("10.0 E W I5", prev_last_y=None)
    assert res.x == 10.0
    assert res.ys == [5, 5, 5, 5, 5, 5, 95]
    assert res.last_y == 95


def test_decode_line_handles_signed_X():
    res = decode_asdf_line("-3.5 A", prev_last_y=None)
    assert res.x == -3.5
    assert res.ys == [1]


def test_decode_line_handles_scientific_notation_in_X():
    res = decode_asdf_line("1.5e-4 A", prev_last_y=None)
    assert res.x == pytest.approx(1.5e-4)


# ------------------------------------------------------------------
# Cross-line integrity check
# ------------------------------------------------------------------


def test_check_digit_mismatch_emits_warning_but_continues():
    """Real Bruker exports usually duplicate the last Y of a
    line as the first Y of the next line. When the duplicate
    is missing or the values disagree, the parser warns but
    still decodes.

    E0 = +50 abs. Previous Y was 999 — mismatch.
    """
    res = decode_asdf_line("E0", prev_last_y=999)
    assert res.ys == [50]
    assert any("check-digit mismatch" in w for w in res.warnings)


def test_check_digit_match_emits_no_warning():
    """E0 = +50 abs; prev_last_y = 50 → matches."""
    res = decode_asdf_line("E0", prev_last_y=50)
    assert res.warnings == []


# ------------------------------------------------------------------
# Fixture cross-check
# ------------------------------------------------------------------


def test_fixture_decodes_to_expected_y_sequence():
    """The synthetic fixture under tests/fixtures/ encodes a
    21-point 1D NMR with peaks at indices 6 (Y=95) and 15
    (Y=85). Decoding the X++(Y..Y) block via the Python
    reference produces that exact sequence."""
    assert FIXTURE.exists()
    text = FIXTURE.read_text(encoding="utf-8")
    # Pull lines between ##XYDATA= and ##END=.
    in_data = False
    data_lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not in_data:
            if line.startswith("##XYDATA="):
                in_data = True
            continue
        if line.startswith("##"):
            break
        if line:
            data_lines.append(line)

    all_ys: list[float] = []
    prev_last = None
    for line in data_lines:
        res = decode_asdf_line(line, prev_last_y=prev_last)
        all_ys.extend(res.ys)
        prev_last = res.last_y

    # Expected: 6 baseline + 1 peak (idx 6) + 7 baseline + 1
    # peak (idx 15) + 5 baseline + 1 trailing = 21 values.
    # Wait — line 3 emits [5, 85, 5, 5, 5, 5, 5] = 7 values
    # (after line 1 emits 7 and line 2 emits 7). Total 21.
    expected = (
        [5, 5, 5, 5, 5, 5, 95]    # line 1
        + [5, 5, 5, 5, 5, 5, 5]    # line 2
        + [5, 85, 5, 5, 5, 5, 5]   # line 3
    )
    assert all_ys == expected
    assert len(all_ys) == 21


# ------------------------------------------------------------------
# JS / Python implementation parity
# ------------------------------------------------------------------


def _js_table(name: str) -> str:
    """Extract one of the char-class tables from the JS file."""
    text = JS_ASDF.read_text(encoding="utf-8")
    m = re.search(rf"const\s+{name}\s*=\s*'([^']+)'", text)
    assert m, f"could not find {name} in {JS_ASDF}"
    return m.group(1)


@pytest.mark.parametrize(("name", "expected"), [
    ("SQZ_POS", SQZ_POS),
    ("SQZ_NEG", SQZ_NEG),
    ("DIF_POS", DIF_POS),
    ("DIF_NEG", DIF_NEG),
    ("DUP_TOK", DUP_TOK),
])
def test_js_char_class_tables_match_python_reference(name, expected):
    """The two implementations MUST agree on the char-class
    tables. If they drift the JS in the browser produces
    different Y values than the Python reference, and the
    cross-check above stops being meaningful."""
    assert _js_table(name) == expected, (
        f"JS {name} ({_js_table(name)!r}) drifted from Python {name} ({expected!r})"
    )


def test_js_module_exposes_documented_functions():
    text = JS_ASDF.read_text(encoding="utf-8")
    assert "window.scienceNmrAsdf" in text
    for fn in ("lineHasAsdf", "tokenizeAsdf", "evaluateAsdfTokens", "decodeAsdfLine"):
        assert fn in text, f"nmr_asdf.js must declare {fn}"


def test_js_module_documents_dup_after_dif_arithmetic_progression():
    """The DUP-after-DIF arithmetic-progression behaviour is
    subtle enough that we keep the comment as a doc anchor.
    A future refactor that removes the comment is a flag to
    re-verify the behaviour."""
    text = JS_ASDF.read_text(encoding="utf-8")
    assert "arithmetic progression" in text.lower()
