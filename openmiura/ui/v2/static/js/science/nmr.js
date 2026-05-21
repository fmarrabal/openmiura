/**
 * NMR spectrum mini-viewer — JCAMP-DX parser + SVG renderer.
 *
 * The science profile's upload view (PR-C2 / G1) lets the
 * operator stage and persist instrument files but treats every
 * file as opaque bytes. For the canonical NMR-review flow the
 * operator wants to *see* the spectrum without leaving the
 * page. This module ships a minimal viable viewer:
 *
 *   - JCAMP-DX 5.01 parser. Supports the two most common
 *     XYDATA layouts in academic Bruker exports:
 *
 *       (XY..XY)      — plain "x y" pairs, one per line
 *       (X++(Y..Y))   — each line: <x_start> y0 y1 y2 …
 *
 *     ASDF compression (SQZ, DIF, DUP) is NOT supported. The
 *     parser bails with a clear error if it encounters it,
 *     pointing the operator at "export with no compression".
 *
 *   - SVG renderer. Renders the spectrum as a polyline in a
 *     viewBox sized to the data. The X axis is reversed for
 *     NMR convention (high ppm on the left). Axis labels show
 *     the first/last X plus the X units; a small caption
 *     mirrors title / data type.
 *
 *   - Detection helper. ``isLikelyJcamp(text)`` returns true
 *     if the buffer's first non-blank line starts with
 *     ``##TITLE=`` — the JCAMP-DX magic.
 *
 * The module exposes ``window.scienceNmr`` so upload.js can
 * consume it without creating a brand new Alpine factory.
 *
 * No backend coupling: every function is pure given its input.
 */
(function () {
  'use strict';

  // ------------------------------------------------------------------
  // Helpers
  // ------------------------------------------------------------------

  function _isFiniteNumber(n) {
    return typeof n === 'number' && isFinite(n);
  }

  function _toNumber(s) {
    if (s == null) return NaN;
    const trimmed = String(s).trim();
    if (!trimmed) return NaN;
    // JCAMP-DX 5.01 numbers are plain floats, possibly with
    // a leading sign or scientific notation. JavaScript Number
    // handles both.
    const v = Number(trimmed);
    return _isFiniteNumber(v) ? v : NaN;
  }

  function isLikelyJcamp(text) {
    if (typeof text !== 'string') return false;
    // Look at the first ~256 bytes for the magic. JCAMP files
    // begin with ##TITLE= as the first non-comment line; we
    // accept arbitrary whitespace before it.
    const head = text.slice(0, 256).trimStart();
    return head.startsWith('##TITLE=');
  }

  // ------------------------------------------------------------------
  // Parser
  // ------------------------------------------------------------------

  /**
   * Parse a JCAMP-DX 5.01 1D spectrum.
   *
   * @param {string} text   Raw file text.
   * @returns {object} {
   *   ok, error?,
   *   title, dataType, xunits, yunits, xfactor, yfactor,
   *   firstx, lastx, npoints,
   *   xydataKind,  // '(XY..XY)' | '(X++(Y..Y))'
   *   points: [{x, y}, ...]
   * }
   */
  function parseJcampDx(text) {
    if (typeof text !== 'string' || !text) {
      return { ok: false, error: 'Empty input.' };
    }
    const lines = text.split(/\r?\n/);

    const headers = {};
    let xydataKind = null;
    let dataStart = -1;
    for (let i = 0; i < lines.length; i++) {
      const raw = lines[i];
      const line = raw.trim();
      if (!line) continue;
      if (line.startsWith('$$')) continue;          // comment
      if (!line.startsWith('##')) continue;
      const eq = line.indexOf('=');
      if (eq < 0) continue;
      const key = line.slice(2, eq).trim().toUpperCase();
      const val = line.slice(eq + 1).trim();
      if (key === 'XYDATA') {
        xydataKind = val;
        dataStart = i + 1;
        break;
      }
      headers[key] = val;
    }

    if (xydataKind === null) {
      return { ok: false, error: 'No ##XYDATA section found.' };
    }
    const kindLower = xydataKind.toLowerCase().replace(/\s+/g, '');
    let mode;
    if (kindLower.startsWith('(xy..xy)')) {
      mode = 'XY..XY';
    } else if (kindLower.startsWith('(x++(y..y))')) {
      mode = 'X++(Y..Y)';
    } else {
      return {
        ok: false,
        error: 'Unsupported XYDATA layout: ' + xydataKind +
               '. Re-export without ASDF compression as (XY..XY) or (X++(Y..Y)).',
      };
    }

    const xfactor = _toNumber(headers.XFACTOR) || 1.0;
    const yfactor = _toNumber(headers.YFACTOR) || 1.0;
    const firstx  = _toNumber(headers.FIRSTX);
    const lastx   = _toNumber(headers.LASTX);
    const npoints = _toNumber(headers.NPOINTS);

    const points = [];
    const warnings = [];

    // ASDF detection helper — delegates to the H2.1 module
    // when available. Falls back to "no ASDF" if the module
    // isn't loaded (the test page can still parse plain
    // (XY..XY) data this way).
    const asdf = (typeof window !== 'undefined' && window.scienceNmrAsdf) || null;
    function _looksAsdf(line) {
      return asdf ? asdf.lineHasAsdf(line) : false;
    }

    if (mode === 'XY..XY') {
      // (XY..XY) lines are plain "x y x y ..." pairs by spec.
      // ASDF in this layout is not standardised and we don't
      // see it in the wild — keep the bail to surface a
      // file that violates the spec.
      for (let i = dataStart; i < lines.length; i++) {
        const raw = lines[i].trim();
        if (!raw) continue;
        if (raw.startsWith('##END')) break;
        if (raw.startsWith('##')) break;
        if (raw.startsWith('$$')) continue;
        if (_looksAsdf(raw)) {
          return {
            ok: false,
            error: 'ASDF compression detected inside an (XY..XY) block; ' +
                   'this layout is not supported. Re-export as (X++(Y..Y)).',
          };
        }
        const tokens = raw.split(/[\s,;]+/).filter(Boolean);
        for (let j = 0; j + 1 < tokens.length; j += 2) {
          const x = _toNumber(tokens[j]);
          const y = _toNumber(tokens[j + 1]);
          if (_isFiniteNumber(x) && _isFiniteNumber(y)) {
            points.push({ x: x * xfactor, y: y * yfactor });
          }
        }
      }
    } else {
      // X++(Y..Y): plain-or-ASDF lines. We pick per line
      // based on whether ASDF letters appear; that way a
      // file that uses ASDF only in some lines (rare but
      // legal) still parses correctly.
      let dx = xfactor;
      if (_isFiniteNumber(firstx) && _isFiniteNumber(lastx) && _isFiniteNumber(npoints) && npoints > 1) {
        dx = (lastx - firstx) / (npoints - 1);
      }

      // ASDF cross-line continuity: the LAST Y of line N
      // is conventionally the first Y of line N+1. The
      // decoder uses prev_last_y to validate that.
      let asdfLastY = null;
      // Cumulative Y-index across all lines so the X
      // increments correctly when lines are ASDF-encoded
      // (each ASDF line yields a variable number of Ys).
      let cumulativeIdx = 0;

      for (let i = dataStart; i < lines.length; i++) {
        const raw = lines[i].trim();
        if (!raw) continue;
        if (raw.startsWith('##END')) break;
        if (raw.startsWith('##')) break;
        if (raw.startsWith('$$')) continue;

        if (asdf && _looksAsdf(raw)) {
          // ASDF-encoded line. Delegate to the H2.1 decoder
          // which extracts the leading X (if any), the Y
          // sequence, and the cross-line check digit.
          const decoded = asdf.decodeAsdfLine(raw, asdfLastY);
          if (decoded.warnings && decoded.warnings.length) {
            for (const w of decoded.warnings) warnings.push(w);
          }
          // We use the explicit X from the line if present,
          // else fall back to cumulativeIdx-based dx.
          let x0 = _isFiniteNumber(decoded.x) ? decoded.x : null;
          if (x0 === null && _isFiniteNumber(firstx)) {
            x0 = firstx + cumulativeIdx * dx;
          }
          for (let k = 0; k < decoded.ys.length; k++) {
            const xk = (x0 !== null)
              ? (x0 + k * dx)
              : (cumulativeIdx * dx);
            points.push({ x: xk, y: decoded.ys[k] * yfactor });
            cumulativeIdx += 1;
          }
          asdfLastY = decoded.lastY;
          continue;
        }

        // Plain (no ASDF) X++(Y..Y) line.
        const tokens = raw.split(/[\s,;]+/).filter(Boolean);
        if (tokens.length === 0) continue;
        const x0 = _toNumber(tokens[0]);
        if (!_isFiniteNumber(x0)) continue;
        // Reset cumulativeIdx based on x0 so subsequent
        // ASDF or plain lines keep numbering correct.
        if (_isFiniteNumber(firstx) && _isFiniteNumber(dx) && dx !== 0) {
          cumulativeIdx = Math.round((x0 - firstx) / dx);
        }
        for (let j = 1; j < tokens.length; j++) {
          const y = _toNumber(tokens[j]);
          if (_isFiniteNumber(y)) {
            points.push({ x: (x0 + (j - 1) * dx), y: y * yfactor });
            asdfLastY = y;
            cumulativeIdx += 1;
          }
        }
      }
    }

    if (points.length === 0) {
      return { ok: false, error: 'No data points parsed from XYDATA section.' };
    }

    const parsed = {
      ok:         true,
      title:      headers.TITLE || '',
      dataType:   headers['DATA TYPE'] || headers.DATATYPE || '',
      xunits:     headers.XUNITS || '',
      yunits:     headers.YUNITS || '',
      xfactor,
      yfactor,
      firstx, lastx, npoints,
      xydataKind: mode,
      points,
      warnings,
    };

    // H2.3 — Bruker TopSpin enhancements. Runs unconditionally
    // because Bruker-specific headers are namespaced under
    // ``##$`` and are absent on non-Bruker files (no-op there).
    _brukerEnhance(parsed, headers, lines);

    // H2.4 — Magritek SpinSolve enhancements. Same no-op
    // contract: skips silently on files that don't carry
    // SpinSolve-flavoured headers.
    _magritekEnhance(parsed, headers, lines);

    return parsed;
  }

  // ------------------------------------------------------------------
  // H2.3 — Bruker TopSpin edge cases
  // ------------------------------------------------------------------

  /**
   * Mutate a parsed-spectrum object with TopSpin-specific
   * enhancements:
   *
   *   1. Count ``##XYDATA=`` blocks — warn if > 1 (real +
   *      imaginary; we only render the first / real channel).
   *   2. Parse the Bruker-private ``##$NUC1`` header (typical
   *      shape: ``<1H>``) into a ``nuclei`` field.
   *   3. When the X axis is in Hz AND ``##$BF1`` (base
   *      frequency, MHz) is present, convert each point's X
   *      from Hz to ppm via ``ppm = Hz / BF1``. Stash the
   *      original unit so a future toggle UI could swap back.
   *
   * Non-Bruker files are unaffected because none of the
   * trigger headers are present.
   */
  function _brukerEnhance(parsed, headers, allLines) {
    parsed.warnings = parsed.warnings || [];

    // 1. Multi-block detection.
    let xydataCount = 0;
    for (let i = 0; i < allLines.length; i++) {
      if (allLines[i].trim().startsWith('##XYDATA=')) xydataCount += 1;
    }
    if (xydataCount > 1) {
      parsed.warnings.push(
        `Multi-block XYDATA detected (${xydataCount} blocks). ` +
        `Rendering the first block only; subsequent blocks ` +
        `(typically the imaginary channel) are ignored.`
      );
    }
    parsed.xydataBlockCount = xydataCount;

    // 2. Nuclei.
    const nuc1Raw = headers['$NUC1'];
    if (nuc1Raw) {
      // Strip angle brackets if present: "<1H>" → "1H".
      const m = String(nuc1Raw).match(/^<\s*(.+?)\s*>$/);
      parsed.nuclei = m ? m[1] : String(nuc1Raw).trim();
    } else {
      parsed.nuclei = null;
    }

    // 3. Hz → ppm conversion. ``##$BF1`` is the base
    // frequency in MHz; dividing Hz by it gives ppm.
    const bf1 = _toNumber(headers['$BF1']);
    if (_convertHzToPpm(parsed, bf1, '$BF1')) {
      parsed.bf1 = bf1;
    }
  }

  // ------------------------------------------------------------------
  // H2.4 — Magritek SpinSolve edge cases
  // ------------------------------------------------------------------

  /**
   * Mutate a parsed-spectrum object with SpinSolve-specific
   * enhancements:
   *
   *   1. Record ``##ORIGIN`` when it advertises Magritek /
   *      SpinSolve into ``vendor_origin`` for the H2.5 vendor
   *      detector.
   *   2. Populate ``nuclei`` from the JCAMP-standard
   *      ``##.OBSERVE NUCLEUS`` header when the Bruker pass
   *      didn't set it (SpinSolve doesn't ship ``##$NUC1``).
   *   3. When the X axis is in Hz and Bruker's ``$BF1`` was
   *      absent, fall back to ``##SPECTROMETER FREQUENCY`` (or
   *      ``##.OBSERVE FREQUENCY``) — both report the base
   *      frequency in MHz — to drive the same Hz→ppm
   *      conversion.
   *   4. Pull ``$$ Lock substance:`` and ``$$ Temperature:``
   *      out of the comment block.
   *
   * Non-Magritek files are unaffected because none of the
   * trigger headers / comments are present.
   */
  function _magritekEnhance(parsed, headers, allLines) {
    parsed.warnings = parsed.warnings || [];

    // 1. Vendor origin string.
    const origin = headers['ORIGIN'];
    if (origin) {
      const lo = String(origin).toLowerCase();
      if (lo.indexOf('magritek') !== -1 || lo.indexOf('spinsolve') !== -1) {
        parsed.vendor_origin = String(origin).trim();
      }
    }

    // 2. Nuclei fallback. JCAMP standard puts this in
    // ``##.OBSERVE NUCLEUS``; Bruker uses ``##$NUC1``. Only
    // overwrite if the Bruker pass left it null.
    if (!parsed.nuclei) {
      const obsNuc = headers['.OBSERVE NUCLEUS'];
      if (obsNuc) {
        parsed.nuclei = String(obsNuc).trim();
      }
    }

    // 3. Hz → ppm fallback via ``##SPECTROMETER FREQUENCY``
    // (preferred) or ``##.OBSERVE FREQUENCY``. Skip if the
    // Bruker pass already ran the conversion (xunits is now
    // ``PPM`` and ``xunits_original`` is populated).
    const alreadyConverted = !!parsed.xunits_original;
    if (!alreadyConverted) {
      const specFreq = _toNumber(
        headers['SPECTROMETER FREQUENCY'] || headers['.OBSERVE FREQUENCY']
      );
      if (_convertHzToPpm(parsed, specFreq, 'SPECTROMETER FREQUENCY')) {
        parsed.spectrometer_freq = specFreq;
      }
    }

    // 4. Lock substance + temperature from the ``$$`` comment
    // block. SpinSolve exports stash run metadata there
    // rather than in headers.
    const lockRe = /^\$\$\s*Lock\s+substance\s*[:=]\s*(.+?)\s*$/i;
    const tempRe = /^\$\$\s*Temperature\s*[:=]\s*([0-9eE.+-]+)\s*([A-Za-z]*)\s*$/;
    for (let i = 0; i < allLines.length; i++) {
      const line = allLines[i].trim();
      if (!line.startsWith('$$')) continue;
      let m = line.match(lockRe);
      if (m && !parsed.lock_substance) {
        parsed.lock_substance = m[1].trim();
        continue;
      }
      m = line.match(tempRe);
      if (m && parsed.temperature === undefined) {
        const v = _toNumber(m[1]);
        if (_isFiniteNumber(v)) {
          parsed.temperature = v;
          if (m[2]) parsed.temperature_unit = m[2].toUpperCase();
        }
      }
    }
  }

  /**
   * Shared Hz → ppm converter. Returns true if the conversion
   * ran (so callers can stash their vendor-specific frequency
   * field), false otherwise.
   */
  function _convertHzToPpm(parsed, freqMHz, sourceLabel) {
    const xunitsUp = String(parsed.xunits || '').toUpperCase();
    if (!_isFiniteNumber(freqMHz) || freqMHz <= 0) return false;
    if (xunitsUp.indexOf('HZ') === -1) return false;
    for (let i = 0; i < parsed.points.length; i++) {
      parsed.points[i].x = parsed.points[i].x / freqMHz;
    }
    if (_isFiniteNumber(parsed.firstx)) parsed.firstx = parsed.firstx / freqMHz;
    if (_isFiniteNumber(parsed.lastx))  parsed.lastx  = parsed.lastx  / freqMHz;
    parsed.xunits_original = parsed.xunits;
    parsed.xunits = 'PPM';
    parsed.warnings.push(
      `Converted X axis from Hz to ppm using ${sourceLabel}=${freqMHz} MHz.`
    );
    return true;
  }

  // ------------------------------------------------------------------
  // SVG renderer
  // ------------------------------------------------------------------

  /**
   * Render a parsed spectrum as inline SVG markup.
   *
   * @param {object} parsed  Result of parseJcampDx.
   * @param {object=} opts   { width?, height?, color?, reverseX? }
   * @returns {string}       SVG element as a string.
   */
  function renderSvg(parsed, opts) {
    if (!parsed || !parsed.ok || !Array.isArray(parsed.points) || parsed.points.length === 0) {
      return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 200"><text x="20" y="100">No data.</text></svg>';
    }
    const o = opts || {};
    const width  = Number(o.width)  || 720;
    const height = Number(o.height) || 240;
    const color  = String(o.color || '#0ea5e9');
    const padX   = 40;
    const padTop = 16;
    const padBot = 28;

    // NMR convention: high ppm on the left ⇒ reverse X axis.
    // ``reverseX`` defaults to true for NMR-flavoured data
    // (xunits PPM, HZ, or unset) and false otherwise.
    const xunits = (parsed.xunits || '').toUpperCase();
    const looksLikeNmr = xunits.indexOf('PPM') !== -1 || xunits.indexOf('HZ') !== -1 || !xunits;
    const reverseX = (o.reverseX === undefined) ? looksLikeNmr : !!o.reverseX;

    const xs = parsed.points.map((p) => p.x);
    const ys = parsed.points.map((p) => p.y);
    let xMin = Math.min.apply(null, xs);
    let xMax = Math.max.apply(null, xs);
    let yMin = Math.min.apply(null, ys);
    let yMax = Math.max.apply(null, ys);
    if (xMin === xMax) xMax = xMin + 1;
    if (yMin === yMax) yMax = yMin + 1;

    const innerW = width  - padX * 2;
    const innerH = height - padTop - padBot;

    function mapX(x) {
      const t = (x - xMin) / (xMax - xMin);
      const u = reverseX ? (1 - t) : t;
      return padX + u * innerW;
    }
    function mapY(y) {
      const t = (y - yMin) / (yMax - yMin);
      return padTop + (1 - t) * innerH;
    }

    // Downsample to ~1500 points for SVG sanity. The plot is
    // visually identical for 1H NMR and the SVG stays small.
    const MAX_PTS = 1500;
    let pts = parsed.points;
    if (pts.length > MAX_PTS) {
      const step = pts.length / MAX_PTS;
      const sampled = [];
      for (let i = 0; i < MAX_PTS; i++) {
        sampled.push(pts[Math.floor(i * step)]);
      }
      pts = sampled;
    }

    const path = pts.map((p, i) => {
      const cmd = i === 0 ? 'M' : 'L';
      return `${cmd}${mapX(p.x).toFixed(1)},${mapY(p.y).toFixed(1)}`;
    }).join(' ');

    function _fmtX(v) {
      // Compact axis label: 4 sig figs is enough for ppm.
      return Number(v).toPrecision(4).replace(/\.?0+$/, '');
    }

    const leftLabel  = _fmtX(reverseX ? xMax : xMin);
    const rightLabel = _fmtX(reverseX ? xMin : xMax);
    const xAxisY = padTop + innerH;

    return [
      `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" `
        + `role="img" aria-label="NMR spectrum">`,
      `<rect x="0" y="0" width="${width}" height="${height}" fill="transparent"/>`,
      // X-axis baseline
      `<line x1="${padX}" y1="${xAxisY}" x2="${width - padX}" y2="${xAxisY}" `
        + `stroke="currentColor" stroke-opacity="0.25" stroke-width="1"/>`,
      // Spectrum trace
      `<path d="${path}" fill="none" stroke="${color}" stroke-width="1.25" `
        + `stroke-linecap="round" stroke-linejoin="round"/>`,
      // Left tick + label
      `<text x="${padX}" y="${height - 8}" font-size="10" `
        + `text-anchor="start" font-family="monospace">${leftLabel}</text>`,
      // Right tick + label
      `<text x="${width - padX}" y="${height - 8}" font-size="10" `
        + `text-anchor="end" font-family="monospace">${rightLabel}</text>`,
      // Units centred under the axis
      `<text x="${width / 2}" y="${height - 8}" font-size="10" `
        + `text-anchor="middle" font-family="monospace" opacity="0.6">`
        + `${_escape((parsed.xunits || 'X'))}${reverseX ? ' (NMR-reversed)' : ''}</text>`,
      `</svg>`,
    ].join('');
  }

  function _escape(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;',
    }[c]));
  }

  /**
   * Auto-detect format and dispatch to the right parser.
   *
   * Order of preference:
   *   1. JCAMP-DX (the documented openMiura format) — detected
   *      by the ``##TITLE=`` magic.
   *   2. CSV / XY plain text — when at least 3 of the first 10
   *      non-blank lines parse to numeric columns. Handled by
   *      the H2.2 module ``scienceNmrCsv`` when available.
   *
   * Returns the canonical parsed shape (see ``parseJcampDx``);
   * adds a ``format`` field so the upload-preview UI can show
   * "JCAMP-DX" vs "CSV/XY" in the metadata grid.
   */
  function parseSpectrum(text) {
    if (typeof text !== 'string' || !text) {
      return { ok: false, error: 'Empty input.' };
    }
    if (isLikelyJcamp(text)) {
      const parsed = parseJcampDx(text);
      if (parsed.ok) parsed.format = 'JCAMP-DX';
      return parsed;
    }
    const csv = (typeof window !== 'undefined' && window.scienceNmrCsv) || null;
    if (csv && csv.isLikelyCsv(text)) {
      const parsed = csv.parseCsvXy(text);
      if (parsed.ok) parsed.format = 'CSV/XY';
      return parsed;
    }
    return {
      ok: false,
      error:
        'Unrecognised file format. Supported: JCAMP-DX 5.01 (.jdx/.dx) ' +
        'and plain CSV / XY ASCII columns.',
    };
  }

  window.scienceNmr = {
    parseJcampDx,
    parseSpectrum,
    renderSvg,
    isLikelyJcamp,
  };
})();
