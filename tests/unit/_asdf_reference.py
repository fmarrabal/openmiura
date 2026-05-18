"""Python reference implementation of the JCAMP-DX ASDF
decoder. Mirrors the JS algorithm in
``openmiura/ui/v2/static/js/science/nmr_asdf.js`` so we can
exercise the same logic from pytest without a JS runtime.

If the two implementations drift, the pinned tests under
``tests/unit/test_nmr_asdf.py`` fail. To stay in sync:

  - char-class tables MUST match (SQZ_POS, SQZ_NEG, DIF_POS,
    DIF_NEG, DUP_TOK)
  - tokenisation order MUST match
  - DUP-after-DIF semantics MUST match (we continue the
    arithmetic progression)
  - check-digit warning MUST fire under the same condition

This module is test-only. Do not import it from the
production codebase.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


SQZ_POS = '@ABCDEFGHI'    # +0..+9
SQZ_NEG = 'abcdefghi'     # -1..-9
DIF_POS = '%JKLMNOPQR'    # +0..+9
DIF_NEG = 'jklmnopqr'     # -1..-9
DUP_TOK = 'STUVWXYZs'     # 1..9 duplicates


@dataclass
class _Token:
    kind: str   # 'abs' | 'dif' | 'dup'
    value: int = 0
    count: int = 0


@dataclass
class TokenizeResult:
    tokens: list[_Token] = field(default_factory=list)
    leading_plain: float | None = None


@dataclass
class EvalResult:
    ys: list[float] = field(default_factory=list)
    last_y: float | None = None
    check_y: float | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class DecodeLineResult:
    x: float | None = None
    ys: list[float] = field(default_factory=list)
    last_y: float | None = None
    check_y: float | None = None
    warnings: list[str] = field(default_factory=list)


def line_has_asdf(line: str) -> bool:
    """True if any ASDF letter is present in the line."""
    if not isinstance(line, str) or not line:
        return False
    pool = SQZ_POS + SQZ_NEG + DIF_POS + DIF_NEG + DUP_TOK
    for ch in line:
        if ch in pool:
            return True
    return False


def _is_digit(ch: str) -> bool:
    return len(ch) == 1 and '0' <= ch <= '9'


def tokenize_asdf(line: str) -> TokenizeResult:
    """Tokenise one ASDF-encoded JCAMP-DX line.

    The optional leading plain decimal (the X in X++(Y..Y))
    is captured separately so the caller can decide whether
    to treat it as an X coordinate or as data.
    """
    src = str(line or '')
    i = 0
    result = TokenizeResult()

    # Skip leading whitespace.
    while i < len(src) and src[i] in (' ', '\t'):
        i += 1

    # Leading plain decimal.
    if i < len(src) and src[i] in '0123456789+-.':
        j = i
        if src[j] in '+-':
            j += 1
        saw_digit = False
        while j < len(src) and (src[j] in '0123456789' or src[j] == '.'):
            saw_digit = saw_digit or (src[j] != '.')
            j += 1
        if j < len(src) and src[j] in 'eE':
            j += 1
            if j < len(src) and src[j] in '+-':
                j += 1
            while j < len(src) and _is_digit(src[j]):
                j += 1
        if saw_digit:
            try:
                result.leading_plain = float(src[i:j])
                i = j
            except ValueError:
                pass

    while i < len(src):
        ch = src[i]
        if ch in (' ', '\t', ','):
            i += 1
            continue

        # SQZ +
        idx = SQZ_POS.find(ch)
        if idx >= 0:
            digits = str(idx)
            i += 1
            while i < len(src) and _is_digit(src[i]):
                digits += src[i]
                i += 1
            result.tokens.append(_Token(kind='abs', value=int(digits)))
            continue
        # SQZ -
        idx = SQZ_NEG.find(ch)
        if idx >= 0:
            digits = str(idx + 1)
            i += 1
            while i < len(src) and _is_digit(src[i]):
                digits += src[i]
                i += 1
            result.tokens.append(_Token(kind='abs', value=-int(digits)))
            continue
        # DIF +
        idx = DIF_POS.find(ch)
        if idx >= 0:
            digits = str(idx)
            i += 1
            while i < len(src) and _is_digit(src[i]):
                digits += src[i]
                i += 1
            result.tokens.append(_Token(kind='dif', value=int(digits)))
            continue
        # DIF -
        idx = DIF_NEG.find(ch)
        if idx >= 0:
            digits = str(idx + 1)
            i += 1
            while i < len(src) and _is_digit(src[i]):
                digits += src[i]
                i += 1
            result.tokens.append(_Token(kind='dif', value=-int(digits)))
            continue
        # DUP
        idx = DUP_TOK.find(ch)
        if idx >= 0:
            result.tokens.append(_Token(kind='dup', count=idx + 1))
            i += 1
            continue
        # Unknown — skip
        i += 1

    return result


def evaluate_asdf_tokens(tokens: list[_Token], prev_last_y: float | None) -> EvalResult:
    """Apply the token sequence to produce a flat Y list."""
    out = EvalResult(last_y=prev_last_y)
    last_y = prev_last_y
    last_delta = 0
    last_was_dif = False

    for tok in tokens:
        if tok.kind == 'abs':
            if out.check_y is None:
                out.check_y = float(tok.value)
            out.ys.append(float(tok.value))
            last_y = float(tok.value)
            last_was_dif = False
        elif tok.kind == 'dif':
            if last_y is None:
                out.warnings.append(
                    'DIF token at line start without a prior Y; treating as absolute'
                )
                last_y = float(tok.value)
            else:
                last_y = last_y + tok.value
            if out.check_y is None:
                out.check_y = last_y
            out.ys.append(last_y)
            last_delta = tok.value
            last_was_dif = True
        elif tok.kind == 'dup':
            if last_y is None:
                out.warnings.append(
                    'DUP token at line start without a prior Y; skipped'
                )
                continue
            for _ in range(tok.count):
                if last_was_dif:
                    last_y = last_y + last_delta
                out.ys.append(last_y)

    out.last_y = last_y
    return out


def decode_asdf_line(line: str, prev_last_y: float | None = None) -> DecodeLineResult:
    """Tokenise + evaluate + run the check-digit comparison."""
    tok = tokenize_asdf(line)
    ev = evaluate_asdf_tokens(tok.tokens, prev_last_y)
    if (
        prev_last_y is not None
        and ev.check_y is not None
        and abs(prev_last_y - ev.check_y) > 0.0001
    ):
        ev.warnings.append(
            f'Y check-digit mismatch: previous line ended at {prev_last_y}, '
            f'current line starts at {ev.check_y}'
        )
    return DecodeLineResult(
        x=tok.leading_plain,
        ys=ev.ys,
        last_y=ev.last_y,
        check_y=ev.check_y,
        warnings=ev.warnings,
    )
