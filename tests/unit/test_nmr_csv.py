"""Tests for the CSV / XY plain-text NMR parser (H2.2).

The parser lives in a browser-side JS module
(``openmiura/ui/v2/static/js/science/nmr_csv.js``); these
tests pin its file-level contract (functions exposed, regex
shapes, fixture parseability) and the two fixture shapes
shipped under tests/fixtures/.

The actual numeric parsing happens in the browser. We don't
ship a Python twin for CSV because the algorithm is small
(split, parse two columns, skip headers) — pinning the
fixture format + the JS function surface is enough for
regression coverage.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
JS_NMR_CSV = ROOT / "openmiura" / "ui" / "v2" / "static" / "js" / "science" / "nmr_csv.js"
JS_NMR     = ROOT / "openmiura" / "ui" / "v2" / "static" / "js" / "science" / "nmr.js"
FIX_MNOVA  = ROOT / "tests" / "fixtures" / "nmr_mestrenova.csv"
FIX_XY     = ROOT / "tests" / "fixtures" / "nmr_topspin_xy.txt"


# ------------------------------------------------------------------
# Module surface
# ------------------------------------------------------------------


def test_csv_module_exposes_documented_functions() -> None:
    assert JS_NMR_CSV.exists()
    text = JS_NMR_CSV.read_text(encoding="utf-8")
    assert "window.scienceNmrCsv" in text
    for fn in ("isLikelyCsv", "parseCsvXy"):
        assert fn in text, f"nmr_csv.js must declare {fn}"


def test_csv_module_supports_common_separators() -> None:
    """The split regex must accept comma, tab, semicolon and
    whitespace. Pin the character class so a future refactor
    that breaks one of them surfaces here."""
    text = JS_NMR_CSV.read_text(encoding="utf-8")
    # Look for a regex literal that includes comma, tab, semicolon,
    # and \s in the same split call.
    assert re.search(r"\[,\\t;\\s\]\+", text) or re.search(r",\\t;\\s", text), (
        "nmr_csv.js must split rows on [,\\t;\\s]+"
    )


def test_csv_module_recognises_comment_prefixes() -> None:
    """Comment / header lines starting with #, ;, %, or //
    are skipped. Pin all four."""
    text = JS_NMR_CSV.read_text(encoding="utf-8")
    assert "_isComment" in text
    for marker in ("'#'", "';'", "'%'", "'//'"):
        assert marker in text, f"nmr_csv.js must recognise {marker} as a comment prefix"


def test_csv_module_rejects_jcamp_files() -> None:
    """The CSV detector must explicitly reject files that
    begin with ##TITLE= so the dispatcher prefers the JCAMP
    path. Otherwise a JCAMP file whose headers happen to
    contain numeric values could be misclassified as CSV."""
    text = JS_NMR_CSV.read_text(encoding="utf-8")
    assert "##TITLE=" in text
    # The reject is wired in isLikelyCsv.
    block = re.search(r"function isLikelyCsv[\s\S]*?function ", text)
    assert block is not None
    assert "##TITLE=" in block.group(0), (
        "isLikelyCsv must check for the JCAMP-DX magic and return false"
    )


def test_csv_module_extracts_vendor_hint() -> None:
    """Vendor names that commonly appear in the header line
    of an export should set vendor_hint accordingly. This
    is non-binding (purely informational) but the field
    appears in the upload-preview modal."""
    text = JS_NMR_CSV.read_text(encoding="utf-8")
    for vendor in ("mestrenova", "mnova", "topspin", "bruker", "spinsolve", "magritek"):
        assert vendor in text.lower(), (
            f"nmr_csv.js must recognise '{vendor}' as a vendor hint"
        )


# ------------------------------------------------------------------
# Dispatcher in nmr.js
# ------------------------------------------------------------------


def test_nmr_module_exposes_parse_spectrum_dispatcher() -> None:
    """H2.2 adds a top-level parseSpectrum(text) that
    auto-detects between JCAMP-DX and CSV/XY and dispatches.
    Pin the dispatcher and the fields it sets."""
    text = JS_NMR.read_text(encoding="utf-8")
    assert "parseSpectrum" in text
    assert "scienceNmrCsv" in text, (
        "nmr.js must consume the CSV module"
    )
    # Format tag set on the returned object.
    assert "'JCAMP-DX'" in text
    assert "'CSV/XY'" in text


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


def test_mestrenova_fixture_is_valid_csv() -> None:
    """The MestreNova fixture must parse cleanly:
      - >= 3 numeric rows in the first 10 lines (for detection)
      - 21 data rows total
      - 2-column shape (ppm, intensity)
    """
    assert FIX_MNOVA.exists()
    text = FIX_MNOVA.read_text(encoding="utf-8")
    # Count numeric data rows (skip blank + #-prefixed lines).
    rows = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        parts = [p.strip() for p in re.split(r"[,\t;]+", line) if p.strip()]
        if len(parts) >= 2:
            try:
                x = float(parts[0])
                y = float(parts[1])
            except ValueError:
                continue
            rows.append((x, y))
    assert len(rows) == 21
    # Peak at 7.26 ppm has Y=95.
    peak = [y for x, y in rows if abs(x - 7.26) < 1e-6]
    assert peak == [95.0]


def test_topspin_xy_fixture_uses_tab_separator() -> None:
    """The TopSpin ASCII export fixture is tab-separated and
    must parse as 21 (ppm, intensity) rows. The peak Y=95
    sits at ppm=7.26 to mirror the MestreNova fixture."""
    assert FIX_XY.exists()
    text = FIX_XY.read_text(encoding="utf-8")
    rows = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        parts = [p for p in re.split(r"\s+", line) if p]
        if len(parts) >= 2:
            try:
                x = float(parts[0])
                y = float(parts[1])
            except ValueError:
                continue
            rows.append((x, y))
    assert len(rows) == 21
    peak = [y for x, y in rows if abs(x - 7.26) < 1e-6]
    assert peak == [95.0]


# ------------------------------------------------------------------
# Upload module integration
# ------------------------------------------------------------------


def test_upload_module_accepts_csv_xy_extensions() -> None:
    """``looksLikeSpectrum`` must accept .csv, .tsv, .xy
    and qualified .txt so the View button shows on those
    files too."""
    upload_js = ROOT / "openmiura" / "ui" / "v2" / "static" / "js" / "science" / "upload.js"
    text = upload_js.read_text(encoding="utf-8")
    for ext in ("'.csv'", "'.tsv'", "'.xy'"):
        assert ext in text, f"upload.js looksLikeSpectrum must accept {ext}"


def test_upload_module_uses_parse_spectrum_dispatcher() -> None:
    """openPreview should call parseSpectrum (the new auto-
    detect dispatcher) rather than calling parseJcampDx
    directly. Pin the prefer-dispatcher logic."""
    upload_js = ROOT / "openmiura" / "ui" / "v2" / "static" / "js" / "science" / "upload.js"
    text = upload_js.read_text(encoding="utf-8")
    assert "parseSpectrum" in text
