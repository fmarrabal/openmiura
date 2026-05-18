/**
 * JCAMP-DX 4.24+ ASDF compression decoder.
 *
 * "ASDF" (ASCII Squeezed Difference Form) is the compact
 * encoding cFreq / Bruker TopSpin / Magritek SpinSolve use
 * when exporting 1D spectra. Three encoding modes coexist
 * inside a single line:
 *
 *   SQZ (Squeezed)
 *     A letter encodes the FIRST digit of an absolute number,
 *     baking sign into the letter so the leading "+" or "-"
 *     can be dropped:
 *
 *       @ A B C D E F G H I   →   +0 +1 +2 +3 +4 +5 +6 +7 +8 +9
 *       a b c d e f g h i     →   -1 -2 -3 -4 -5 -6 -7 -8 -9
 *
 *     The remaining digits of the number are written as plain
 *     decimal digits. So "J55" parses as +155; "b6" parses
 *     as -26.
 *
 *   DIF (Difference)
 *     A letter encodes the first digit of a DELTA (the value
 *     is added to the previous Y):
 *
 *       % J K L M N O P Q R   →   +0 +1 +2 +3 +4 +5 +6 +7 +8 +9
 *       j k l m n o p q r     →   -1 -2 -3 -4 -5 -6 -7 -8 -9
 *
 *     Trailing digits extend the delta. So after Y=100, "K5"
 *     produces Y=125 (delta +25).
 *
 *   DUP (Duplicate)
 *     A letter encoding a repeat count for the previous Y
 *     (or, when following a DIF, repeats the DELTA producing
 *     an arithmetic progression):
 *
 *       S T U V W X Y Z       →   1 2 3 4 5 6 7 8 duplicates
 *       s                     →   9 duplicates
 *
 * Lines in the (X++(Y..Y)) layout start with a plain X (no
 * SQZ); the Y values that follow are ASDF-encoded. The LAST
 * Y of line N is conventionally a re-statement of the value
 * that equals the FIRST Y of line N+1 (an integrity check);
 * a disagreement is surfaced as a warning, not an abort.
 *
 * All functions in this module are pure.
 */
(function () {
  'use strict';

  // Char-class tables. Keep them as strings so indexOf gives
  // us the numeric digit directly (@→0, A→1, ... I→9 for SQZ
  // positive).
  const SQZ_POS = '@ABCDEFGHI';   // → +0 .. +9
  const SQZ_NEG = 'abcdefghi';    // → -1 .. -9
  const DIF_POS = '%JKLMNOPQR';   // → +0 .. +9
  const DIF_NEG = 'jklmnopqr';    // → -1 .. -9
  const DUP_TOK = 'STUVWXYZs';    // → 1 .. 9 duplicates

  /**
   * Quick check: does the line contain any ASDF letter?
   * Used by the upstream parser to decide whether to call
   * the ASDF decoder or fall back to plain-token parsing.
   */
  function lineHasAsdf(line) {
    if (typeof line !== 'string' || !line) return false;
    for (let i = 0; i < line.length; i++) {
      const ch = line[i];
      if (SQZ_POS.indexOf(ch) >= 0) return true;
      if (SQZ_NEG.indexOf(ch) >= 0) return true;
      if (DIF_POS.indexOf(ch) >= 0) return true;
      if (DIF_NEG.indexOf(ch) >= 0) return true;
      if (DUP_TOK.indexOf(ch) >= 0) return true;
    }
    return false;
  }

  /**
   * Tokenise a single ASDF-encoded line.
   *
   * Returns ``{ tokens, leadingPlain }`` where ``leadingPlain``
   * is the first plain (non-ASDF) number on the line — used
   * by the X++(Y..Y) layout to extract the X coordinate
   * that prefixes each Y-block.
   */
  function tokenizeAsdf(line) {
    const tokens = [];
    let leadingPlain = null;
    const src = String(line || '');
    let i = 0;

    // Skip leading whitespace.
    while (i < src.length && (src[i] === ' ' || src[i] === '\t')) i++;

    // Consume any leading plain decimal (the X in X++(Y..Y)).
    // A plain number starts with an optional sign and a digit
    // or a dot.
    if (i < src.length && /[0-9+\-.]/.test(src[i])) {
      let j = i;
      // Sign
      if (src[j] === '+' || src[j] === '-') j++;
      // Mantissa
      let sawDigit = false;
      while (j < src.length && /[0-9.]/.test(src[j])) {
        sawDigit = true;
        j++;
      }
      // Exponent (rare on JCAMP X, but possible)
      if (j < src.length && (src[j] === 'e' || src[j] === 'E')) {
        j++;
        if (j < src.length && (src[j] === '+' || src[j] === '-')) j++;
        while (j < src.length && /[0-9]/.test(src[j])) j++;
      }
      if (sawDigit) {
        const v = parseFloat(src.slice(i, j));
        if (isFinite(v)) {
          leadingPlain = v;
          i = j;
        }
      }
    }

    while (i < src.length) {
      const ch = src[i];

      if (ch === ' ' || ch === '\t' || ch === ',') {
        i++;
        continue;
      }

      // SQZ +
      let idx = SQZ_POS.indexOf(ch);
      if (idx >= 0) {
        let digits = String(idx);
        i++;
        while (i < src.length && /[0-9]/.test(src[i])) {
          digits += src[i];
          i++;
        }
        tokens.push({ kind: 'abs', value: parseInt(digits, 10) });
        continue;
      }
      // SQZ -
      idx = SQZ_NEG.indexOf(ch);
      if (idx >= 0) {
        let digits = String(idx + 1);
        i++;
        while (i < src.length && /[0-9]/.test(src[i])) {
          digits += src[i];
          i++;
        }
        tokens.push({ kind: 'abs', value: -parseInt(digits, 10) });
        continue;
      }
      // DIF +
      idx = DIF_POS.indexOf(ch);
      if (idx >= 0) {
        let digits = String(idx);
        i++;
        while (i < src.length && /[0-9]/.test(src[i])) {
          digits += src[i];
          i++;
        }
        tokens.push({ kind: 'dif', value: parseInt(digits, 10) });
        continue;
      }
      // DIF -
      idx = DIF_NEG.indexOf(ch);
      if (idx >= 0) {
        let digits = String(idx + 1);
        i++;
        while (i < src.length && /[0-9]/.test(src[i])) {
          digits += src[i];
          i++;
        }
        tokens.push({ kind: 'dif', value: -parseInt(digits, 10) });
        continue;
      }
      // DUP
      idx = DUP_TOK.indexOf(ch);
      if (idx >= 0) {
        tokens.push({ kind: 'dup', count: idx + 1 });
        i++;
        continue;
      }

      // Unknown character — skip silently. Real-world JCAMP
      // exports sometimes mix ASCII spaces or stray
      // punctuation into the data block.
      i++;
    }

    return { tokens, leadingPlain };
  }

  /**
   * Evaluate ASDF tokens into a flat Y sequence.
   *
   * @param {Array} tokens   from tokenizeAsdf().tokens
   * @param {number|null} prevLastY  Last Y of the previous line, or null for line 1.
   * @returns {{ ys: number[], lastY: number|null, checkY: number|null, warnings: string[] }}
   *   ``checkY`` is the value the parser BELIEVED is the first Y of this
   *   line; the caller can compare with prevLastY for the integrity check.
   */
  function evaluateAsdfTokens(tokens, prevLastY) {
    const ys = [];
    let lastY = prevLastY;
    let lastDelta = 0;
    let lastWasDif = false;
    let checkY = null;
    const warnings = [];

    for (let k = 0; k < tokens.length; k++) {
      const tok = tokens[k];
      if (tok.kind === 'abs') {
        if (checkY === null) checkY = tok.value;
        ys.push(tok.value);
        lastY = tok.value;
        lastWasDif = false;
      } else if (tok.kind === 'dif') {
        if (lastY === null) {
          // No baseline yet — treat the delta as absolute so
          // the parser doesn't silently drop the value. Warn
          // because this is unusual.
          warnings.push('DIF token at line start without a prior Y; treating as absolute');
          lastY = tok.value;
        } else {
          lastY = lastY + tok.value;
        }
        if (checkY === null) checkY = lastY;
        ys.push(lastY);
        lastDelta = tok.value;
        lastWasDif = true;
      } else if (tok.kind === 'dup') {
        if (lastY === null) {
          warnings.push('DUP token at line start without a prior Y; skipped');
          continue;
        }
        for (let n = 0; n < tok.count; n++) {
          if (lastWasDif) {
            // After a DIF, DUP continues the arithmetic
            // progression with the same delta. This is the
            // strict-ASDF reading and matches real Bruker
            // exports we've seen.
            lastY = lastY + lastDelta;
          }
          ys.push(lastY);
        }
      }
    }

    return { ys, lastY, checkY, warnings };
  }

  /**
   * Convenience: full decode of one X++(Y..Y) line.
   *
   * The line typically starts with a plain X value, then a
   * sequence of ASDF tokens for the Y samples. Returns the
   * decoded sequence + cross-line continuity info.
   *
   * @param {string} line
   * @param {number|null} prevLastY  Carried from the previous line.
   * @returns {{ x: number|null, ys: number[], lastY: number|null, checkY: number|null, warnings: string[] }}
   */
  function decodeAsdfLine(line, prevLastY) {
    const { tokens, leadingPlain } = tokenizeAsdf(line);
    const evald = evaluateAsdfTokens(tokens, prevLastY);
    // Integrity check: the first Y of this line should
    // equal the last Y of the previous line. Mismatch is
    // a warning (real data sometimes drifts in the last
    // digit due to rounding), not an abort.
    if (
      prevLastY !== null && prevLastY !== undefined &&
      evald.checkY !== null &&
      Math.abs((prevLastY - evald.checkY)) > 0.0001
    ) {
      evald.warnings.push(
        `Y check-digit mismatch: previous line ended at ${prevLastY}, ` +
        `current line starts at ${evald.checkY}`
      );
    }
    return {
      x:        leadingPlain,
      ys:       evald.ys,
      lastY:    evald.lastY,
      checkY:   evald.checkY,
      warnings: evald.warnings,
    };
  }

  window.scienceNmrAsdf = {
    lineHasAsdf,
    tokenizeAsdf,
    evaluateAsdfTokens,
    decodeAsdfLine,
    // Exposed so the upstream parser + the Python reference
    // can verify their char-class tables agree.
    _tables: { SQZ_POS, SQZ_NEG, DIF_POS, DIF_NEG, DUP_TOK },
  };
})();
