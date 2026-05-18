/**
 * Plain-text CSV / XY parser for NMR 1D spectra (H2.2).
 *
 * Many vendor tools export spectra as plain ASCII columns
 * outside JCAMP-DX. The most common shapes seen in academic
 * labs:
 *
 *   ppm,intensity                       (MestreNova default CSV)
 *   ppm    intensity                    (TopSpin "ASCII export",
 *                                        tab- or whitespace-
 *                                        separated)
 *   ppm,real,imag                       (some SpinSolve and
 *                                        MNova exports keep
 *                                        the real + imaginary
 *                                        traces side by side)
 *   ppm;intensity                       (regional locales)
 *
 * Comments and headers must be skipped. Common header markers:
 *   - "#" or ";" or "%" at the very start of a line
 *   - "//" double-slash
 *   - Any non-numeric leading token (e.g. "Frequency,Intensity")
 *
 * The output shape mirrors ``parseJcampDx`` so downstream
 * consumers (the SVG renderer, the upload-preview modal) treat
 * either parser identically.
 */
(function () {
  'use strict';

  function _isFiniteNumber(n) {
    return typeof n === 'number' && isFinite(n);
  }

  function _toNumber(s) {
    if (s == null) return NaN;
    const trimmed = String(s).trim();
    if (!trimmed) return NaN;
    // Accept comma decimal separator if the cell looks like a
    // single number (e.g. "1,23" → 1.23). Skip this fix if
    // the cell has more than one comma (then it's a row).
    let candidate = trimmed;
    if (candidate.indexOf(',') !== -1 && candidate.indexOf('.') === -1) {
      const parts = candidate.split(',');
      if (parts.length === 2 && /^-?\d+$/.test(parts[0]) && /^\d+$/.test(parts[1])) {
        candidate = parts[0] + '.' + parts[1];
      }
    }
    const v = Number(candidate);
    return _isFiniteNumber(v) ? v : NaN;
  }

  /**
   * Detection heuristic: does the buffer look like a CSV/XY
   * column dump?
   *
   * Returns true if at least 3 of the first 10 non-blank
   * non-comment lines parse cleanly to two or three numeric
   * columns. The threshold trades a few false-negatives for a
   * very low false-positive rate (we don't want to claim a
   * JCAMP-DX file is CSV just because its header says
   * ##XUNITS= PPM).
   */
  function isLikelyCsv(text) {
    if (typeof text !== 'string' || !text) return false;
    // A JCAMP-DX file is recognised by its ##TITLE= magic —
    // explicitly reject it here so the dispatcher prefers the
    // JCAMP path even if some line further down looks numeric.
    const head = text.slice(0, 256).trimStart();
    if (head.startsWith('##TITLE=')) return false;

    const lines = text.split(/\r?\n/);
    let seen = 0;
    let numeric = 0;
    for (const raw of lines) {
      if (seen >= 10) break;
      const line = raw.trim();
      if (!line) continue;
      if (_isComment(line)) continue;
      seen += 1;
      const tokens = line.split(/[,\t;\s]+/).filter(Boolean);
      if (tokens.length < 2 || tokens.length > 4) continue;
      // Every cell must parse as a number.
      let allNum = true;
      for (const t of tokens) {
        if (!_isFiniteNumber(_toNumber(t))) { allNum = false; break; }
      }
      if (allNum) numeric += 1;
    }
    return numeric >= 3;
  }

  function _isComment(line) {
    if (!line) return false;
    if (line.startsWith('#') || line.startsWith(';') ||
        line.startsWith('%') || line.startsWith('//')) return true;
    return false;
  }

  /**
   * Parse a CSV / XY plain-text 1D spectrum.
   *
   * Same return shape as ``parseJcampDx``:
   *
   *   { ok, error?, title, dataType, xunits, yunits,
   *     firstx, lastx, npoints, xydataKind, points,
   *     warnings, vendor_hint }
   *
   * ``vendor_hint`` is set to one of 'mestrenova' / 'topspin' /
   * 'spinsolve' / 'unknown' when the header line gives us a
   * cue. It's purely informational.
   *
   * For 3-column rows we treat column 2 as real and column 3
   * as imaginary and keep only the real part (the imaginary
   * trace isn't useful for visual peak picking).
   */
  function parseCsvXy(text) {
    if (typeof text !== 'string' || !text) {
      return { ok: false, error: 'Empty input.' };
    }
    const lines = text.split(/\r?\n/);
    const points = [];
    const warnings = [];
    let title = '';
    let xunits = 'PPM';
    let yunits = '';
    let vendorHint = 'unknown';

    // Walk the first 5 non-blank lines for a recognisable
    // header. We accept either a comment-prefix style ("#
    // ppm,intensity"), a bare header row ("ppm,intensity"),
    // or no header at all. The "title" we surface in the
    // viewer metadata is best-effort.
    let headerLineIdx = -1;
    for (let i = 0; i < lines.length && i < 5; i++) {
      const raw = lines[i].trim();
      if (!raw) continue;
      const m = raw.toLowerCase();
      if (m.indexOf('mestrenova') !== -1 || m.indexOf('mnova') !== -1) vendorHint = 'mestrenova';
      else if (m.indexOf('topspin') !== -1 || m.indexOf('bruker') !== -1) vendorHint = 'topspin';
      else if (m.indexOf('spinsolve') !== -1 || m.indexOf('magritek') !== -1) vendorHint = 'spinsolve';

      const stripped = _isComment(raw) ? raw.replace(/^[#;%]|\/\//, '').trim() : raw;
      const tokens = stripped.split(/[,\t;\s]+/).filter(Boolean);
      const firstNum = tokens.length ? _toNumber(tokens[0]) : NaN;
      if (!_isFiniteNumber(firstNum)) {
        // It's a header / banner line. Capture it for title +
        // unit hints.
        if (!title) title = stripped.slice(0, 120);
        headerLineIdx = i;
        const lower = stripped.toLowerCase();
        if (lower.indexOf('hz') !== -1) xunits = 'HZ';
        else if (lower.indexOf('ppm') !== -1) xunits = 'PPM';
        if (lower.indexOf('intensity') !== -1) yunits = 'ARBITRARY UNITS';
      }
    }

    // Data scan. Start from line 0 — we'll skip non-numeric
    // rows defensively rather than rely on headerLineIdx
    // (some files have multi-line banners).
    for (let i = 0; i < lines.length; i++) {
      const raw = lines[i];
      if (raw === undefined) continue;
      const line = raw.trim();
      if (!line) continue;
      if (_isComment(line)) continue;
      const tokens = line.split(/[,\t;\s]+/).filter(Boolean);
      if (tokens.length < 2) continue;
      const x = _toNumber(tokens[0]);
      const y = _toNumber(tokens[1]);
      if (!_isFiniteNumber(x) || !_isFiniteNumber(y)) {
        // Probably a header row — skip silently.
        continue;
      }
      // 3-column real+imag: ignore imag.
      points.push({ x, y });
    }

    if (points.length === 0) {
      return {
        ok: false,
        error: 'No data points parsed. Expected at least one numeric "x y" row.',
      };
    }

    const xs = points.map((p) => p.x);
    const firstx = xs[0];
    const lastx  = xs[xs.length - 1];
    const npoints = points.length;

    return {
      ok:          true,
      title:       title || '(untitled CSV)',
      dataType:    'NMR SPECTRUM',
      xunits,
      yunits,
      xfactor:     1.0,
      yfactor:     1.0,
      firstx,
      lastx,
      npoints,
      xydataKind:  'CSV',
      points,
      warnings,
      vendor_hint: vendorHint,
    };
  }

  window.scienceNmrCsv = {
    isLikelyCsv,
    parseCsvXy,
    // Helpers exposed for tests / debugging.
    _isComment,
    _toNumber,
  };
})();
