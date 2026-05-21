"""Tests for the Bruker TopSpin edge-cases enhancer (H2.3).

The enhancer lives in
``openmiura/ui/v2/static/js/science/nmr.js`` as the
``_brukerEnhance`` helper invoked at the end of
``parseJcampDx``. It pulls Bruker-private headers (``##$BF1``,
``##$NUC1``) out of the parsed shape and, when the X axis is
in Hz with a known base frequency, converts it to ppm.

Like H2.2 the algorithm itself runs in the browser; these
tests pin the JS module surface, the textual contract of the
warning messages, and the fixture shape.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT       = Path(__file__).resolve().parents[2]
JS_NMR     = ROOT / "openmiura" / "ui" / "v2" / "static" / "js" / "science" / "nmr.js"
FIX_BRUKER = ROOT / "tests" / "fixtures" / "nmr_bruker_topspin.jdx"


# ------------------------------------------------------------------
# Module surface
# ------------------------------------------------------------------


def test_bruker_enhancer_function_exists() -> None:
    assert JS_NMR.exists()
    text = JS_NMR.read_text(encoding="utf-8")
    assert "_brukerEnhance" in text, (
        "nmr.js must declare the Bruker TopSpin enhancer"
    )
    # The enhancer should be invoked from inside parseJcampDx.
    assert re.search(r"_brukerEnhance\s*\(", text), (
        "nmr.js must call _brukerEnhance(...)"
    )


def test_bruker_enhancer_reads_bf1_and_nuc1_headers() -> None:
    """The Bruker-private headers we depend on must be named
    exactly so a future header-key normalisation refactor that
    changes the case or strips the leading ``$`` surfaces
    here."""
    text = JS_NMR.read_text(encoding="utf-8")
    # parseJcampDx strips the leading "##" so headers are
    # keyed as e.g. "$BF1" / "$NUC1".
    assert "'$BF1'" in text, "nmr.js must read headers['$BF1']"
    assert "'$NUC1'" in text, "nmr.js must read headers['$NUC1']"


def test_bruker_enhancer_handles_hz_to_ppm_conversion() -> None:
    """When ``XUNITS=HZ`` and ``$BF1`` is positive, the
    enhancer divides every point's X by BF1 and re-labels the
    axis as PPM. The original unit is preserved in
    ``xunits_original`` so a future toggle can swap back."""
    text = JS_NMR.read_text(encoding="utf-8")
    assert "xunits_original" in text
    assert "'PPM'" in text
    # The conversion factor is a division by the base frequency.
    # H2.4 extracted the body into a shared ``_convertHzToPpm``
    # helper, so the division reads as ``.x / freqMHz`` there.
    assert re.search(r"\.x\s*/\s*freqMHz\b", text), (
        "nmr.js must divide point.x by the base frequency to get ppm"
    )
    # The Bruker enhancer must still hand ``$BF1`` to the
    # shared helper.
    assert re.search(r"_convertHzToPpm\([^)]*bf1", text), (
        "nmr.js must call _convertHzToPpm with the Bruker $BF1 value"
    )


def test_bruker_enhancer_strips_angle_brackets_from_nuc1() -> None:
    """``##$NUC1`` typically ships as ``<1H>``. The enhancer
    must strip the angle brackets so downstream UI can show
    just ``1H``."""
    text = JS_NMR.read_text(encoding="utf-8")
    # Look for a regex that matches <...> wrapping.
    assert re.search(r"\^<.*\?>", text) or re.search(r"\^<\\s\*\(", text), (
        "nmr.js must strip the <...> wrapping from $NUC1"
    )


def test_bruker_enhancer_counts_xydata_blocks() -> None:
    """Bruker exports often contain two ``##XYDATA=`` blocks
    (real + imaginary channel). We render the first and warn
    the operator so they understand why the imaginary half is
    missing."""
    text = JS_NMR.read_text(encoding="utf-8")
    assert "##XYDATA=" in text
    assert "xydataBlockCount" in text
    assert "Multi-block XYDATA" in text or "Rendering the first block" in text, (
        "nmr.js must emit a warning when more than one XYDATA block is seen"
    )


def test_bruker_enhancer_emits_warning_with_bf1_value() -> None:
    """The Hz→ppm conversion warning must mention BF1 so the
    operator can audit the conversion. Pin the message
    skeleton."""
    text = JS_NMR.read_text(encoding="utf-8")
    assert "Converted X axis from Hz to ppm" in text


# ------------------------------------------------------------------
# Fixture
# ------------------------------------------------------------------


def test_bruker_fixture_exists_and_declares_topspin_headers() -> None:
    assert FIX_BRUKER.exists()
    text = FIX_BRUKER.read_text(encoding="utf-8")
    # Bruker-private headers we care about.
    assert "##$BF1= 400.0" in text
    assert "##$NUC1= <1H>" in text
    # XUNITS must be Hz so the enhancer kicks in.
    assert "##XUNITS= HZ" in text
    assert "##XYDATA= (XY..XY)" in text


def test_bruker_fixture_hz_values_map_to_clean_ppm() -> None:
    """The 5 Hz points should divide cleanly by BF1=400 MHz
    to produce ppm values 10.0, 7.5, 5.0, 2.5, 0.0. This pins
    the fixture's numerical content so a regression that
    rounds BF1 or changes the values is caught here."""
    text = FIX_BRUKER.read_text(encoding="utf-8")
    bf1 = 400.0
    # Pull the (XY..XY) block.
    lines = text.splitlines()
    data_start = None
    for i, line in enumerate(lines):
        if line.strip().startswith("##XYDATA="):
            data_start = i + 1
            break
    assert data_start is not None
    expected_ppm = [10.0, 7.5, 5.0, 2.5, 0.0]
    hz_values = []
    for line in lines[data_start:]:
        s = line.strip()
        if not s or s.startswith("##") or s.startswith("$$"):
            if s.startswith("##END"):
                break
            continue
        parts = s.split()
        if len(parts) >= 2:
            try:
                hz_values.append(float(parts[0]))
            except ValueError:
                continue
    assert len(hz_values) == 5
    actual_ppm = [hz / bf1 for hz in hz_values]
    for got, want in zip(actual_ppm, expected_ppm):
        assert abs(got - want) < 1e-9, f"hz/{bf1} = {got}, expected {want}"


def test_bruker_fixture_peak_position() -> None:
    """The synthetic fixture has its tallest peak (Y=95) at
    2000 Hz, which is 5.0 ppm. Pin that so a casual
    re-shuffle of the fixture surfaces here."""
    text = FIX_BRUKER.read_text(encoding="utf-8")
    rows = []
    in_data = False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("##XYDATA="):
            in_data = True
            continue
        if not in_data:
            continue
        if s.startswith("##END"):
            break
        if not s or s.startswith("##") or s.startswith("$$"):
            continue
        parts = s.split()
        if len(parts) >= 2:
            try:
                rows.append((float(parts[0]), float(parts[1])))
            except ValueError:
                continue
    # Find the row with maximum Y.
    peak_hz, peak_y = max(rows, key=lambda r: r[1])
    assert peak_y == 95.0
    assert peak_hz == 2000.0
    assert peak_hz / 400.0 == 5.0


# ------------------------------------------------------------------
# Non-Bruker safety: enhancer must be a no-op on plain files
# ------------------------------------------------------------------


def test_enhancer_is_no_op_when_bf1_absent() -> None:
    """When ``$BF1`` is not in the header dict, the Hz→ppm
    branch must not run (it would multiply X by NaN otherwise).
    H2.4 moved the guard inside ``_convertHzToPpm`` where the
    expression is ``_isFiniteNumber(freqMHz)`` plus a
    ``freqMHz <= 0`` early-return."""
    text = JS_NMR.read_text(encoding="utf-8")
    assert re.search(r"_isFiniteNumber\(freqMHz\)", text), (
        "nmr.js must guard the Hz→ppm helper with "
        "_isFiniteNumber(freqMHz)"
    )
    assert re.search(r"freqMHz\s*<=\s*0", text), (
        "nmr.js must early-return when freqMHz <= 0"
    )


def test_enhancer_is_no_op_when_xunits_not_hz() -> None:
    """If the fixture's X axis is already in ppm, the
    conversion must not run. The shared helper uses an
    ``indexOf('HZ') === -1`` early-return."""
    text = JS_NMR.read_text(encoding="utf-8")
    assert re.search(r"xunitsUp\.indexOf\(\s*['\"]HZ['\"]\s*\)\s*===\s*-1", text), (
        "nmr.js must require xunits to contain 'HZ' before "
        "running the conversion"
    )
