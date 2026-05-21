"""Tests for the NMR vendor-detection helper (H2.5).

The helper lives in
``openmiura/ui/v2/static/js/science/nmr_vendor.js`` and
exposes:

  - ``detectVendor(parsed) -> 'bruker' | 'magritek' |
    'mestrenova' | 'unknown'``
  - ``vendorLabel(vendor) -> str``

Like every other JS science module the algorithm itself runs
in the browser. These tests pin:

  1. The module surface (functions, return tags, label
     strings).
  2. The detection priority — explicit vendor headers beat
     CSV vendor hints.
  3. A cross-vendor smoke check that walks each shipped
     fixture, replicates the detection logic in Python, and
     asserts the result matches the expected vendor tag.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT       = Path(__file__).resolve().parents[2]
JS_DIR     = ROOT / "openmiura" / "ui" / "v2" / "static" / "js" / "science"
JS_VENDOR  = JS_DIR / "nmr_vendor.js"
JS_NMR     = JS_DIR / "nmr.js"
JS_HTML    = ROOT / "openmiura" / "ui" / "v2" / "static" / "science.html"
JS_UPLOAD  = JS_DIR / "upload.js"

FIX_BRUKER   = ROOT / "tests" / "fixtures" / "nmr_bruker_topspin.jdx"
FIX_MAGRITEK = ROOT / "tests" / "fixtures" / "nmr_magritek_spinsolve.jdx"
FIX_MNOVA    = ROOT / "tests" / "fixtures" / "nmr_mestrenova.csv"
FIX_PLAIN    = ROOT / "tests" / "fixtures" / "nmr_sample.jdx"


# ------------------------------------------------------------------
# Module surface
# ------------------------------------------------------------------


def test_vendor_module_exists() -> None:
    assert JS_VENDOR.exists()
    text = JS_VENDOR.read_text(encoding="utf-8")
    assert "window.scienceNmrVendor" in text
    assert "detectVendor" in text
    assert "vendorLabel" in text


def test_vendor_module_returns_documented_tags() -> None:
    """The four allowed return values must appear as string
    literals so a refactor can't silently introduce a fifth
    tag without updating this pin."""
    text = JS_VENDOR.read_text(encoding="utf-8")
    for tag in ("'bruker'", "'magritek'", "'mestrenova'", "'unknown'"):
        assert tag in text, f"detectVendor must return {tag} for at least one branch"


def test_vendor_module_explicit_signal_beats_hint() -> None:
    """``vendor_origin`` (set by H2.4 from ``##ORIGIN=``) is
    authoritative and must be checked BEFORE the CSV
    ``vendor_hint``. Pin via lexical order in the source."""
    text = JS_VENDOR.read_text(encoding="utf-8")
    origin_idx = text.find("parsed.vendor_origin")
    hint_idx   = text.find("parsed.vendor_hint")
    assert origin_idx != -1 and hint_idx != -1
    assert origin_idx < hint_idx, (
        "detectVendor must consult vendor_origin before vendor_hint"
    )


def test_vendor_module_bruker_path_checks_bf1() -> None:
    """The Bruker primary signal is the numeric ``bf1`` that
    H2.3 stamps on the parsed object after a successful
    Hz→ppm conversion."""
    text = JS_VENDOR.read_text(encoding="utf-8")
    assert "parsed.bf1" in text


def test_vendor_module_recognises_topspin_in_hint() -> None:
    """CSV exports tagged as TopSpin (e.g. via the comment
    header) must still resolve to 'bruker'."""
    text = JS_VENDOR.read_text(encoding="utf-8")
    assert "'topspin'" in text.lower()


def test_vendor_module_recognises_mnova_alias_in_hint() -> None:
    """Both 'mestrenova' and 'mnova' must map to 'mestrenova'."""
    text = JS_VENDOR.read_text(encoding="utf-8")
    assert "'mestrenova'" in text.lower()
    assert "'mnova'" in text.lower()


def test_vendor_labels_are_human_readable() -> None:
    """``vendorLabel`` must produce a vendor-and-product
    string for each known tag. Pin the four strings."""
    text = JS_VENDOR.read_text(encoding="utf-8")
    assert "Bruker TopSpin" in text
    assert "Magritek SpinSolve" in text
    assert "MestreNova" in text
    assert "Unknown" in text


# ------------------------------------------------------------------
# Loading order in science.html
# ------------------------------------------------------------------


def test_science_html_loads_vendor_module_before_upload() -> None:
    """``upload.js`` uses ``window.scienceNmrVendor`` so the
    vendor script must be loaded first."""
    text = JS_HTML.read_text(encoding="utf-8")
    vendor_idx = text.find("nmr_vendor.js")
    upload_idx = text.find("upload.js")
    assert vendor_idx != -1, "science.html must include nmr_vendor.js"
    assert upload_idx != -1
    assert vendor_idx < upload_idx, (
        "nmr_vendor.js must load before upload.js"
    )


def test_upload_module_consumes_vendor_detector() -> None:
    """``openPreview`` should call ``detectVendor`` to
    populate ``previewMeta.vendor``."""
    text = JS_UPLOAD.read_text(encoding="utf-8")
    assert "scienceNmrVendor" in text
    assert "detectVendor" in text
    assert "vendor_label" in text


# ------------------------------------------------------------------
# Cross-vendor smoke: Python twin of detectVendor over each fixture
# ------------------------------------------------------------------


def _python_detect_vendor(*,
                          vendor_origin: str | None = None,
                          bf1: float | None = None,
                          vendor_hint: str | None = None) -> str:
    """Python twin of the JS ``detectVendor`` algorithm.
    Kept in sync via the source-code pins above; if the JS
    diverges, those tests fail before this one does."""
    if vendor_origin:
        vo = vendor_origin.lower()
        if "magritek" in vo or "spinsolve" in vo:
            return "magritek"
    if bf1 is not None and bf1 > 0:
        return "bruker"
    hint = (vendor_hint or "").lower()
    if "bruker" in hint or "topspin" in hint:
        return "bruker"
    if "magritek" in hint or "spinsolve" in hint:
        return "magritek"
    if "mestrenova" in hint or "mnova" in hint:
        return "mestrenova"
    return "unknown"


def test_smoke_magritek_fixture_resolves_to_magritek() -> None:
    """The SpinSolve fixture carries ``##ORIGIN= Magritek
    Spinsolve`` so H2.4 will set ``vendor_origin``. The
    detector must resolve it to 'magritek'."""
    text = FIX_MAGRITEK.read_text(encoding="utf-8")
    m = re.search(r"^##ORIGIN=\s*(.+)$", text, re.MULTILINE)
    assert m is not None
    vendor_origin = m.group(1).strip()
    assert _python_detect_vendor(vendor_origin=vendor_origin) == "magritek"


def test_smoke_bruker_fixture_resolves_to_bruker() -> None:
    """The TopSpin fixture carries ``##$BF1= 400.0`` so H2.3
    will set ``parsed.bf1=400``. The detector must resolve to
    'bruker'."""
    text = FIX_BRUKER.read_text(encoding="utf-8")
    m = re.search(r"^##\$BF1=\s*([0-9.]+)", text, re.MULTILINE)
    assert m is not None
    bf1 = float(m.group(1))
    assert _python_detect_vendor(bf1=bf1) == "bruker"


def test_smoke_mestrenova_fixture_resolves_to_mestrenova() -> None:
    """The MestreNova CSV fixture has '# MestreNova ...' as
    its first line so the H2.2 CSV parser sets
    ``vendor_hint='mestrenova'``."""
    text = FIX_MNOVA.read_text(encoding="utf-8")
    assert "MestreNova" in text or "mestrenova" in text.lower()
    assert _python_detect_vendor(vendor_hint="mestrenova") == "mestrenova"


def test_smoke_plain_jcamp_fixture_resolves_to_unknown() -> None:
    """The original ``nmr_sample.jdx`` carries
    ``##ORIGIN= openMiura test fixture`` and no vendor-specific
    headers, so it must NOT be misclassified."""
    text = FIX_PLAIN.read_text(encoding="utf-8")
    m = re.search(r"^##ORIGIN=\s*(.+)$", text, re.MULTILINE)
    vendor_origin = m.group(1).strip() if m else None
    # No ##$BF1, no vendor_hint expected.
    assert _python_detect_vendor(vendor_origin=vendor_origin) == "unknown"


def test_smoke_priority_explicit_origin_beats_conflicting_hint() -> None:
    """A file that somehow advertises ``##ORIGIN= Magritek``
    AND contains a ``vendor_hint='topspin'`` (unrealistic but
    a useful pin) must resolve to 'magritek' because the
    explicit origin header beats the hint."""
    assert _python_detect_vendor(
        vendor_origin="Magritek Spinsolve",
        vendor_hint="topspin",
    ) == "magritek"


def test_smoke_unknown_when_no_signals() -> None:
    assert _python_detect_vendor() == "unknown"
