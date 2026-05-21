/**
 * NMR vendor detection (H2.5).
 *
 * H2.3 (Bruker TopSpin) and H2.4 (Magritek SpinSolve) added
 * vendor-specific post-processing to the JCAMP-DX parser, and
 * H2.2 (CSV/XY) already tagged a ``vendor_hint`` on plain-text
 * exports. This module is the single source of truth for
 * "given a parsed-spectrum object, what vendor does it look
 * like?" — used by the upload-preview modal to render a
 * vendor badge.
 *
 * Returns one of:
 *
 *   - 'bruker'      — Bruker TopSpin (BF1 / NUC1 headers,
 *                     ``bruker`` / ``topspin`` hint, ORIGIN
 *                     mentions Bruker).
 *   - 'magritek'    — Magritek SpinSolve (vendor_origin set
 *                     by H2.4, ``magritek`` / ``spinsolve``
 *                     hint).
 *   - 'mestrenova'  — MestreNova / MNova CSV exports
 *                     (vendor_hint set by H2.2).
 *   - 'unknown'     — None of the signals match.
 *
 * The function is pure given its input. No DOM, no network,
 * no side effects.
 *
 * The detector trusts the explicit-vendor signals more than
 * the hint signals; a file with ``vendor_origin: "Magritek"``
 * and ``vendor_hint: "topspin"`` resolves to 'magritek',
 * because origin is set from a ``##ORIGIN=`` header (an
 * authoritative declaration) whereas the hint can fire on a
 * stray word in any comment line.
 */
(function () {
  'use strict';

  function _lower(s) {
    return (typeof s === 'string') ? s.toLowerCase() : '';
  }

  function _contains(haystack, needle) {
    return _lower(haystack).indexOf(needle) !== -1;
  }

  /**
   * Detect the instrument vendor for a parsed spectrum.
   *
   * @param {object} parsed  Result of ``scienceNmr.parseSpectrum``.
   * @returns {string}       'bruker' | 'magritek' | 'mestrenova' | 'unknown'.
   */
  function detectVendor(parsed) {
    if (!parsed || typeof parsed !== 'object') return 'unknown';
    if (parsed.ok === false) return 'unknown';

    // 1. Magritek SpinSolve — H2.4 sets ``vendor_origin``
    // only when ``##ORIGIN=`` literally mentions Magritek or
    // SpinSolve. Authoritative.
    if (parsed.vendor_origin) {
      const vo = _lower(parsed.vendor_origin);
      if (vo.indexOf('magritek') !== -1 || vo.indexOf('spinsolve') !== -1) {
        return 'magritek';
      }
    }

    // 2. Bruker TopSpin — ``bf1`` (numeric) is set by H2.3
    // only when ``##$BF1`` was read AND the Hz→ppm conversion
    // ran. That's a strong signal because the ``$BF1`` header
    // is Bruker-private.
    if (typeof parsed.bf1 === 'number' && isFinite(parsed.bf1) && parsed.bf1 > 0) {
      return 'bruker';
    }

    // 3. Bruker via the CSV vendor_hint (e.g. MestreNova
    // export tagged "Bruker" in its header comment).
    const hint = _lower(parsed.vendor_hint);
    if (hint.indexOf('bruker') !== -1 || hint.indexOf('topspin') !== -1) {
      return 'bruker';
    }

    // 4. Magritek via the CSV vendor_hint.
    if (hint.indexOf('magritek') !== -1 || hint.indexOf('spinsolve') !== -1) {
      return 'magritek';
    }

    // 5. MestreNova / MNova via vendor_hint.
    if (hint.indexOf('mestrenova') !== -1 || hint.indexOf('mnova') !== -1) {
      return 'mestrenova';
    }

    return 'unknown';
  }

  /**
   * Human-readable label for a vendor tag. Used by the UI
   * when rendering the vendor badge.
   */
  function vendorLabel(vendor) {
    switch (vendor) {
      case 'bruker':     return 'Bruker TopSpin';
      case 'magritek':   return 'Magritek SpinSolve';
      case 'mestrenova': return 'MestreNova';
      default:           return 'Unknown';
    }
  }

  window.scienceNmrVendor = {
    detectVendor,
    vendorLabel,
  };
})();
