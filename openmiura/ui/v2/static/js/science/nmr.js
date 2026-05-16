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

    // ASDF compression sigil check — refuse cleanly.
    // ASDF uses characters @, A..I (positive SQZ) / a..i (negative SQZ),
    // J..R (positive DIF) / j..r (negative DIF), S..Z + s..z (DUP),
    // + and -. We just look for any letter outside scientific-notation
    // E/e in the body and bail out.
    function _looksAsdf(line) {
      // Scientific notation is 1.23e-4 or 1.23E-4; allow those.
      // ASDF letters appear inside number tokens without a leading digit.
      // Heuristic: a token of letters between digits is ASDF.
      return /\d[a-zA-Z][^Ee0-9+\-.\s]/.test(line) ||
             /[a-df-ik-rt-zA-DF-IK-RT-Z][0-9+\-.]/.test(line);
    }

    if (mode === 'XY..XY') {
      for (let i = dataStart; i < lines.length; i++) {
        const raw = lines[i].trim();
        if (!raw) continue;
        if (raw.startsWith('##END')) break;
        if (raw.startsWith('##')) break;
        if (raw.startsWith('$$')) continue;
        if (_looksAsdf(raw)) {
          return {
            ok: false,
            error: 'Detected ASDF compression. Re-export without compression.',
          };
        }
        // Each line is one or more "x y" pairs separated by
        // whitespace, comma or semicolon.
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
      // X++(Y..Y): each line is <x_start> y0 y1 y2 ...
      // We compute the per-step dx from the header. If npoints
      // and lastx are present we use the consistent dx; otherwise
      // we fall back to xfactor.
      let dx = xfactor;
      if (_isFiniteNumber(firstx) && _isFiniteNumber(lastx) && _isFiniteNumber(npoints) && npoints > 1) {
        dx = (lastx - firstx) / (npoints - 1);
      }
      for (let i = dataStart; i < lines.length; i++) {
        const raw = lines[i].trim();
        if (!raw) continue;
        if (raw.startsWith('##END')) break;
        if (raw.startsWith('##')) break;
        if (raw.startsWith('$$')) continue;
        if (_looksAsdf(raw)) {
          return {
            ok: false,
            error: 'Detected ASDF compression. Re-export without compression.',
          };
        }
        const tokens = raw.split(/[\s,;]+/).filter(Boolean);
        if (tokens.length === 0) continue;
        const x0 = _toNumber(tokens[0]);
        if (!_isFiniteNumber(x0)) continue;
        for (let j = 1; j < tokens.length; j++) {
          const y = _toNumber(tokens[j]);
          if (_isFiniteNumber(y)) {
            points.push({ x: (x0 + (j - 1) * dx), y: y * yfactor });
          }
        }
      }
    }

    if (points.length === 0) {
      return { ok: false, error: 'No data points parsed from XYDATA section.' };
    }

    return {
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
    };
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

  window.scienceNmr = {
    parseJcampDx,
    renderSvg,
    isLikelyJcamp,
  };
})();
