"""Per-model LLM price table + cost estimator (H3.6).

This is a *lightweight, best-effort* cost estimator, not a
billing source of truth. The numbers below are approximate
public list prices (USD per 1,000,000 tokens) captured while
building H3.6; providers change them, negotiated/enterprise
rates differ, and prices vary by region. Treat the output as a
running estimate for budget awareness, and override the table
when you need accuracy (``estimate_cost(..., prices=...)``).

Token-accounting convention (matches what the per-provider
clients put in the canonical ``usage`` dict):

  - ``prompt_tokens``     — input tokens billed at the full
                            input rate (NON-cached);
  - ``cache_read_tokens`` — input tokens served from a prompt
                            cache, billed at the (cheaper)
                            cache-read rate;
  - ``cache_write_tokens``— input tokens written into the
                            cache, billed at the cache-write
                            rate (Anthropic; OpenAI has no
                            separate write charge);
  - ``completion_tokens`` — output tokens billed at the output
                            rate.

The clients normalise both providers to this convention:
Anthropic already reports cache tokens separately from
``input_tokens``; for OpenAI (whose ``prompt_tokens`` *includes*
the cached subset) the client subtracts ``cached_tokens`` from
``prompt_tokens`` so the buckets never double-count.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional


@dataclass(frozen=True)
class ModelPrice:
    """USD per 1,000,000 tokens for one model.

    ``cache_read`` / ``cache_write`` fall back to the full
    ``input`` rate when ``None`` (i.e. "no distinct cache
    pricing known" → cost is never under-counted).
    """

    input: float
    output: float
    cache_read: Optional[float] = None
    cache_write: Optional[float] = None


# Approximate public list prices (USD / 1M tokens). NOT a billing
# source of truth — see the module docstring. Keys are matched
# case-insensitively by exact id first, then by longest
# prefix/substring so versioned ids ("claude-3-5-sonnet-20241022",
# "gpt-4o-2024-08-06") resolve to their family entry.
DEFAULT_PRICES: dict[str, ModelPrice] = {
    # ---- Anthropic (Claude 4.x / Fable) ----
    # cache_read = 0.1x input, cache_write = 1.25x input (5-minute TTL),
    # the standard Anthropic prompt-cache multipliers.
    "claude-fable-5":    ModelPrice(10.00, 50.00, cache_read=1.00, cache_write=12.50),
    "claude-opus-4-8":   ModelPrice(5.00, 25.00, cache_read=0.50, cache_write=6.25),
    "claude-opus-4-7":   ModelPrice(5.00, 25.00, cache_read=0.50, cache_write=6.25),
    "claude-opus-4-6":   ModelPrice(5.00, 25.00, cache_read=0.50, cache_write=6.25),
    "claude-sonnet-4-6": ModelPrice(3.00, 15.00, cache_read=0.30, cache_write=3.75),
    "claude-haiku-4-5":  ModelPrice(1.00, 5.00, cache_read=0.10, cache_write=1.25),
    # ---- Anthropic (Claude 3.x) ----
    "claude-3-5-sonnet": ModelPrice(3.00, 15.00, cache_read=0.30, cache_write=3.75),
    "claude-3-5-haiku":  ModelPrice(0.80, 4.00, cache_read=0.08, cache_write=1.00),
    "claude-3-opus":     ModelPrice(15.00, 75.00, cache_read=1.50, cache_write=18.75),
    "claude-3-sonnet":   ModelPrice(3.00, 15.00, cache_read=0.30, cache_write=3.75),
    "claude-3-haiku":    ModelPrice(0.25, 1.25, cache_read=0.03, cache_write=0.30),
    # ---- OpenAI (no separate cache-write charge) ----
    "gpt-4o-mini":       ModelPrice(0.15, 0.60, cache_read=0.075),
    "gpt-4o":            ModelPrice(2.50, 10.00, cache_read=1.25),
    "gpt-4.1-mini":      ModelPrice(0.40, 1.60, cache_read=0.10),
    "gpt-4.1-nano":      ModelPrice(0.10, 0.40, cache_read=0.025),
    "gpt-4.1":           ModelPrice(2.00, 8.00, cache_read=0.50),
}


def price_for(model: str, prices: Optional[Mapping[str, ModelPrice]] = None) -> Optional[ModelPrice]:
    """Resolve a model id to its ``ModelPrice``.

    Exact (case-insensitive) match wins; otherwise the
    longest table key that is a prefix of — or substring of —
    the model id wins (so versioned/dated ids resolve to their
    family). Returns ``None`` when nothing matches: callers must
    treat an unknown model as "cost unknown" rather than free.
    """
    table = prices or DEFAULT_PRICES
    key = (model or "").strip().lower()
    if not key:
        return None
    exact = table.get(key)
    if exact is not None:
        return exact
    best: Optional[ModelPrice] = None
    best_len = -1
    for cand, price in table.items():
        if (key.startswith(cand) or cand in key) and len(cand) > best_len:
            best = price
            best_len = len(cand)
    return best


def estimate_cost(
    model: str,
    usage: Optional[Mapping[str, Any]],
    *,
    prices: Optional[Mapping[str, ModelPrice]] = None,
) -> dict[str, Any]:
    """Estimate the USD cost of one ``usage`` dict.

    Returns a breakdown ``{model, known, input_usd, output_usd,
    cache_read_usd, cache_write_usd, total_usd}``. When the model
    is not in the table, ``known`` is ``False`` and every figure
    is ``0.0`` — we report "unknown", never a fabricated number.
    All USD figures are rounded to 6 decimals (micro-dollar).
    """
    usage = usage or {}
    prompt = int(usage.get("prompt_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    cache_read = int(usage.get("cache_read_tokens") or 0)
    cache_write = int(usage.get("cache_write_tokens") or 0)

    price = price_for(model, prices)
    if price is None:
        return {
            "model":           model,
            "known":           False,
            "input_usd":       0.0,
            "output_usd":      0.0,
            "cache_read_usd":  0.0,
            "cache_write_usd": 0.0,
            "total_usd":       0.0,
        }

    per = 1_000_000.0
    cr_rate = price.cache_read if price.cache_read is not None else price.input
    cw_rate = price.cache_write if price.cache_write is not None else price.input

    input_usd = prompt * price.input / per
    output_usd = completion * price.output / per
    cache_read_usd = cache_read * cr_rate / per
    cache_write_usd = cache_write * cw_rate / per
    total_usd = input_usd + output_usd + cache_read_usd + cache_write_usd

    return {
        "model":           model,
        "known":           True,
        "input_usd":       round(input_usd, 6),
        "output_usd":      round(output_usd, 6),
        "cache_read_usd":  round(cache_read_usd, 6),
        "cache_write_usd": round(cache_write_usd, 6),
        "total_usd":       round(total_usd, 6),
    }


__all__ = ["ModelPrice", "DEFAULT_PRICES", "price_for", "estimate_cost"]
