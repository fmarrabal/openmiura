"""Pin the Claude 4.x / Fable price entries.

Before this, the table only knew Claude 3.x and GPT models, so any
current Anthropic model (Opus 4.x, Sonnet 4.6, Haiku 4.5, Fable 5)
resolved to ``None`` and every cost estimate silently reported $0.00 —
``known=False``. These tests lock in that the current models are priced
and resolve correctly (including dated/suffixed ids), so cost telemetry
is non-zero for the models the platform actually runs.
"""
from __future__ import annotations

import pytest

from openmiura.core.llm.pricing import DEFAULT_PRICES, estimate_cost, price_for


@pytest.mark.parametrize(
    "model, input_rate, output_rate",
    [
        ("claude-fable-5", 10.00, 50.00),
        ("claude-opus-4-8", 5.00, 25.00),
        ("claude-opus-4-7", 5.00, 25.00),
        ("claude-opus-4-6", 5.00, 25.00),
        ("claude-sonnet-4-6", 3.00, 15.00),
        ("claude-haiku-4-5", 1.00, 5.00),
    ],
)
def test_current_models_are_priced(model: str, input_rate: float, output_rate: float) -> None:
    price = price_for(model)
    assert price is not None, f"{model} must be in the price table"
    assert price.input == input_rate
    assert price.output == output_rate
    # cache buckets follow the standard 0.1x / 1.25x multipliers.
    assert price.cache_read == pytest.approx(input_rate * 0.1)
    assert price.cache_write == pytest.approx(input_rate * 1.25)


def test_current_model_cost_is_known_and_nonzero() -> None:
    b = estimate_cost("claude-opus-4-8", {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000})
    assert b["known"] is True
    assert b["input_usd"] == pytest.approx(5.00)
    assert b["output_usd"] == pytest.approx(25.00)
    assert b["total_usd"] == pytest.approx(30.00)


def test_dated_and_suffixed_ids_resolve_to_family() -> None:
    # A dated id resolves to its family entry by longest-prefix match.
    assert price_for("claude-haiku-4-5-20251001") is DEFAULT_PRICES["claude-haiku-4-5"]
    # A 4.x id must NOT collide with a Claude 3.x entry.
    assert price_for("claude-opus-4-8") is DEFAULT_PRICES["claude-opus-4-8"]
    assert price_for("claude-opus-4-8") is not DEFAULT_PRICES["claude-3-opus"]
    assert price_for("claude-sonnet-4-6") is DEFAULT_PRICES["claude-sonnet-4-6"]
    assert price_for("claude-sonnet-4-6") is not DEFAULT_PRICES["claude-3-sonnet"]
