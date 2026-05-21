"""Tests for the Magritek SpinSolve edge-cases enhancer (H2.4).

Like H2.3, the enhancer lives in
``openmiura/ui/v2/static/js/science/nmr.js`` and runs at the
end of ``parseJcampDx`` immediately after the Bruker pass.

SpinSolve / Magritek exports differ from Bruker in three ways
the generic parser misses:

  * The vendor signature is ``##ORIGIN= Magritek ...`` (or
    ``Spinsolve``), not a private ``##$`` header.
  * The base frequency lives in ``##SPECTROMETER FREQUENCY``
    (or ``##.OBSERVE FREQUENCY``) instead of ``##$BF1``.
  * The observed nucleus uses the JCAMP-standard
    ``##.OBSERVE NUCLEUS`` rather than ``##$NUC1``.
  * Lock substance + temperature are tucked into ``$$``
    comments (``$$ Lock substance: D2O``,
    ``$$ Temperature: 298.15 K``) instead of being headers at
    all.

These tests pin the JS module surface and the synthetic
fixture content.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT         = Path(__file__).resolve().parents[2]
JS_NMR       = ROOT / "openmiura" / "ui" / "v2" / "static" / "js" / "science" / "nmr.js"
FIX_MAGRITEK = ROOT / "tests" / "fixtures" / "nmr_magritek_spinsolve.jdx"


# ------------------------------------------------------------------
# Module surface
# ------------------------------------------------------------------


def test_magritek_enhancer_function_exists() -> None:
    assert JS_NMR.exists()
    text = JS_NMR.read_text(encoding="utf-8")
    assert "_magritekEnhance" in text, (
        "nmr.js must declare the Magritek SpinSolve enhancer"
    )
    assert re.search(r"_magritekEnhance\s*\(", text), (
        "nmr.js must call _magritekEnhance(...)"
    )


def test_magritek_enhancer_runs_after_bruker_pass() -> None:
    """The Bruker pass owns the canonical Hz→ppm conversion
    when ``$BF1`` is present; SpinSolve only fills in the
    gap. Pin the call order so a refactor can't accidentally
    swap them and double-convert."""
    text = JS_NMR.read_text(encoding="utf-8")
    bruker_idx   = text.find("_brukerEnhance(parsed")
    magritek_idx = text.find("_magritekEnhance(parsed")
    assert bruker_idx != -1 and magritek_idx != -1
    assert bruker_idx < magritek_idx, (
        "_brukerEnhance must be called before _magritekEnhance"
    )


def test_magritek_enhancer_extracts_vendor_origin() -> None:
    """``##ORIGIN`` is the public vendor advertisement. We
    capture it in ``vendor_origin`` only when it mentions
    Magritek or SpinSolve so the H2.5 vendor detector can
    branch on it cheaply."""
    text = JS_NMR.read_text(encoding="utf-8")
    assert "vendor_origin" in text
    assert "'magritek'" in text.lower()
    assert "'spinsolve'" in text.lower()


def test_magritek_enhancer_reads_observe_nucleus_header() -> None:
    """JCAMP standard puts the observed nucleus in
    ``##.OBSERVE NUCLEUS=``. The header parser uppercases keys
    but keeps the leading ``.``."""
    text = JS_NMR.read_text(encoding="utf-8")
    assert "'.OBSERVE NUCLEUS'" in text, (
        "nmr.js must read headers['.OBSERVE NUCLEUS']"
    )


def test_magritek_enhancer_reads_spectrometer_frequency_header() -> None:
    """The base frequency header for SpinSolve is
    ``##SPECTROMETER FREQUENCY`` (MHz). ``##.OBSERVE FREQUENCY``
    is the per-nucleus equivalent and acts as a fallback."""
    text = JS_NMR.read_text(encoding="utf-8")
    assert "'SPECTROMETER FREQUENCY'" in text
    assert "'.OBSERVE FREQUENCY'" in text


def test_magritek_enhancer_uses_shared_hz_to_ppm_helper() -> None:
    """The Hz→ppm conversion is shared with the Bruker pass
    via ``_convertHzToPpm``. Pin both the helper's existence
    and that Magritek calls it."""
    text = JS_NMR.read_text(encoding="utf-8")
    assert "_convertHzToPpm" in text
    # The helper should be called from BOTH enhancers.
    assert text.count("_convertHzToPpm(") >= 2, (
        "_convertHzToPpm must be called from both _brukerEnhance "
        "and _magritekEnhance"
    )


def test_magritek_enhancer_skips_conversion_when_bruker_already_ran() -> None:
    """If the Bruker pass already converted Hz→ppm,
    ``xunits_original`` is set and Magritek must not run a
    second time. Pin the guard."""
    text = JS_NMR.read_text(encoding="utf-8")
    assert "alreadyConverted" in text or "xunits_original" in text, (
        "nmr.js must short-circuit the SpinSolve conversion "
        "when the Bruker pass already ran it"
    )


def test_magritek_enhancer_parses_lock_substance_and_temperature() -> None:
    """``$$ Lock substance: X`` and ``$$ Temperature: X K``
    are SpinSolve's metadata channel. Pin both regexes and
    the destination fields."""
    text = JS_NMR.read_text(encoding="utf-8")
    assert "lock_substance" in text
    assert "temperature" in text
    # The lock-substance regex must accept both ":" and "=".
    assert re.search(r"Lock\\s\+substance", text), (
        "nmr.js must scan $$ comments for 'Lock substance:'"
    )
    assert re.search(r"Temperature", text)


# ------------------------------------------------------------------
# Fixture
# ------------------------------------------------------------------


def test_magritek_fixture_exists_and_declares_spinsolve_headers() -> None:
    assert FIX_MAGRITEK.exists()
    text = FIX_MAGRITEK.read_text(encoding="utf-8")
    assert "##ORIGIN= Magritek Spinsolve" in text
    assert "##.OBSERVE NUCLEUS= 1H" in text
    assert "##SPECTROMETER FREQUENCY= 60.49" in text
    assert "##XUNITS= HZ" in text
    assert "$$ Lock substance: D2O" in text
    assert "$$ Temperature: 298.15 K" in text


def test_magritek_fixture_hz_values_map_to_clean_ppm() -> None:
    """5 Hz points at 60.49 MHz must divide cleanly to
    10/7.5/5/2.5/0 ppm."""
    text = FIX_MAGRITEK.read_text(encoding="utf-8")
    freq = 60.49
    lines = text.splitlines()
    data_start = None
    for i, line in enumerate(lines):
        if line.strip().startswith("##XYDATA="):
            data_start = i + 1
            break
    assert data_start is not None
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
    expected_ppm = [10.0, 7.5, 5.0, 2.5, 0.0]
    for hz, want in zip(hz_values, expected_ppm):
        got = hz / freq
        assert abs(got - want) < 1e-6, (
            f"hz/{freq} = {got}, expected {want}"
        )


def test_magritek_fixture_peak_position() -> None:
    """Peak Y=95 sits at 302.45 Hz = 5.0 ppm. Mirrors the
    Bruker fixture so a cross-vendor smoke test (H2.5) can
    pin the same nominal peak."""
    text = FIX_MAGRITEK.read_text(encoding="utf-8")
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
    peak_hz, peak_y = max(rows, key=lambda r: r[1])
    assert peak_y == 95.0
    assert peak_hz == 302.45
    assert abs(peak_hz / 60.49 - 5.0) < 1e-9
