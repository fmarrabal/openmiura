"""Tests for H3.6 — cache + cost telemetry.

H3.6 adds three things:

  1. **Cache-token capture.** The per-provider clients surface
     prompt-cache tokens in the canonical ``usage`` dict —
     Anthropic's ``cache_read_input_tokens`` /
     ``cache_creation_input_tokens`` (reported separately from
     ``input_tokens``) and OpenAI's
     ``prompt_tokens_details.cached_tokens`` (a subset of
     ``prompt_tokens``, split out so the buckets don't
     double-count). The cache keys appear only when non-zero, so
     an uncached call keeps the canonical 3-key shape.

  2. **A cost estimator.** ``core/llm/pricing.py`` maps
     (model, usage) → an approximate USD breakdown using a
     configurable list-price table; unknown models report
     ``known=False`` with zero cost rather than a fabricated
     number.

  3. **A running budget + endpoint.** The runtime records cost
     and cache tokens into a process-local budget; ``GET
     /http/budget`` exposes the running totals.

These tests pin each layer: pricing, the two usage parsers, the
observability budget, the runtime wiring, and the endpoint.
"""

from __future__ import annotations

import asyncio
import tempfile
from typing import Any, AsyncIterator

import yaml
from fastapi.testclient import TestClient

from openmiura.core.agent_runtime import AgentRuntime
from openmiura.core.llm import LlmStreamEvent
from openmiura.core.llm.anthropic_client import _usage_from_anthropic
from openmiura.core.llm.openai_compat import _usage_from_payload
from openmiura.core.llm.pricing import DEFAULT_PRICES, estimate_cost, price_for
from openmiura.core.llm.types import ChatResponse
from openmiura.interfaces.http.app import create_app
from openmiura.observability import (
    budget_snapshot,
    record_cost,
    record_tokens,
    reset_budget,
)


# ==================================================================
# pricing — price_for + estimate_cost
# ==================================================================


def test_price_for_exact_versioned_substring_and_unknown():
    assert price_for("gpt-4o-mini") is DEFAULT_PRICES["gpt-4o-mini"]
    # Versioned / dated ids resolve to their family entry.
    assert price_for("claude-3-5-sonnet-20241022") is DEFAULT_PRICES["claude-3-5-sonnet"]
    assert price_for("gpt-4o-2024-08-06") is DEFAULT_PRICES["gpt-4o"]
    # Unknown / empty → None (caller must treat as "cost unknown").
    assert price_for("totally-made-up-model") is None
    assert price_for("") is None
    assert price_for(None) is None  # type: ignore[arg-type]


def test_price_for_longest_match_wins():
    # "claude-3-5-haiku" must beat the shorter "claude-3-haiku"
    # substring so the right rate is picked.
    assert price_for("claude-3-5-haiku-20241022") is DEFAULT_PRICES["claude-3-5-haiku"]


def test_estimate_cost_known_model_with_cache_buckets():
    usage = {
        "prompt_tokens":      1_000_000,
        "completion_tokens":  1_000_000,
        "cache_read_tokens":  1_000_000,
        "cache_write_tokens": 0,
    }
    b = estimate_cost("claude-3-5-sonnet", usage)
    assert b["known"] is True
    assert b["input_usd"] == 3.0
    assert b["output_usd"] == 15.0
    assert b["cache_read_usd"] == 0.3
    assert b["cache_write_usd"] == 0.0
    assert b["total_usd"] == round(3.0 + 15.0 + 0.3, 6)


def test_estimate_cost_cache_write_falls_back_to_input_rate_when_unpriced():
    # gpt-4o-mini declares no cache_write rate → the estimator
    # falls back to the full input rate (never under-counts).
    b = estimate_cost("gpt-4o-mini", {"cache_write_tokens": 1_000_000})
    assert b["cache_write_usd"] == 0.15  # == input rate


def test_estimate_cost_unknown_model_is_zero_and_flagged():
    b = estimate_cost("mystery-model-9000", {"prompt_tokens": 999, "completion_tokens": 999})
    assert b["known"] is False
    assert b["total_usd"] == 0.0
    assert b["input_usd"] == 0.0


# ==================================================================
# usage capture — Anthropic + OpenAI
# ==================================================================


def test_anthropic_usage_adds_cache_buckets_to_total():
    u = _usage_from_anthropic({
        "input_tokens":               100,
        "output_tokens":              50,
        "cache_read_input_tokens":    800,
        "cache_creation_input_tokens": 200,
    })
    assert u["prompt_tokens"] == 100
    assert u["completion_tokens"] == 50
    assert u["cache_read_tokens"] == 800
    assert u["cache_write_tokens"] == 200
    # Anthropic cache tokens are separate from input → they add.
    assert u["total_tokens"] == 100 + 50 + 800 + 200


def test_anthropic_usage_without_cache_keeps_three_keys():
    u = _usage_from_anthropic({"input_tokens": 12, "output_tokens": 5})
    assert u == {"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17}


def test_openai_usage_splits_cached_tokens_out_of_prompt():
    u = _usage_from_payload({
        "prompt_tokens":         1000,
        "completion_tokens":     200,
        "total_tokens":          1200,
        "prompt_tokens_details": {"cached_tokens": 400},
    })
    # Cached is a subset of prompt → split out, not added.
    assert u["prompt_tokens"] == 600
    assert u["cache_read_tokens"] == 400
    assert u["completion_tokens"] == 200
    assert u["total_tokens"] == 1200          # unchanged
    assert "cache_write_tokens" not in u      # OpenAI has no write bucket


def test_openai_usage_without_cache_keeps_three_keys():
    u = _usage_from_payload({"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13})
    assert u == {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13}


# ==================================================================
# observability — running budget
# ==================================================================


def test_budget_accumulates_tokens_cost_and_cache():
    reset_budget()
    try:
        record_tokens("gpt-4o", total_tokens=1000)
        record_cost("gpt-4o", cost_usd=0.05, cache_read_tokens=300, cache_write_tokens=0)
        snap = budget_snapshot()
        assert snap["total_tokens"] == 1000
        assert snap["total_cost_usd"] == 0.05
        m = snap["by_model"]["gpt-4o"]
        assert m["tokens"] == 1000
        assert m["cost_usd"] == 0.05
        assert m["cache_read_tokens"] == 300
        assert m["cache_write_tokens"] == 0
    finally:
        reset_budget()


def test_budget_skips_zero_cost_rows():
    reset_budget()
    try:
        # Unknown-model turn → cost 0; record_cost must not invent
        # a cost figure (cache tokens may still be recorded).
        record_cost("unknown", cost_usd=0.0)
        snap = budget_snapshot()
        assert snap["total_cost_usd"] == 0.0
        assert "unknown" not in snap["by_model"]
    finally:
        reset_budget()


# ==================================================================
# runtime — records cost + surfaces cache in consolidated usage
# ==================================================================


class _FakeStreamingLLM:
    def __init__(self, rounds: list[list[LlmStreamEvent]]):
        self._rounds = list(rounds)
        self.model = "fake"
        self.calls: list[dict[str, Any]] = []

    def chat_stream(self, messages, *, tools=None) -> AsyncIterator[LlmStreamEvent]:
        self.calls.append({"messages": list(messages), "tools": tools})
        events = self._rounds.pop(0) if self._rounds else []

        async def _gen() -> AsyncIterator[LlmStreamEvent]:
            for ev in events:
                yield ev
        return _gen()


class _FakeAudit:
    def get_recent_messages(self, *, session_id, limit):
        return []


class _FakeSettings:
    class _Runtime:
        history_limit = 0
    class _LLM:
        provider = "fake"
        model = "fake-model"
    runtime = _Runtime()
    llm = _LLM()
    agents: dict[str, Any] = {}


def _make_runtime(llm) -> AgentRuntime:
    rt = AgentRuntime.__new__(AgentRuntime)
    rt.llm = llm
    rt.audit = _FakeAudit()
    rt.settings = _FakeSettings()
    rt.skill_loader = None
    rt.skills_path = ""
    return rt


def _collect_runtime(rt: AgentRuntime, **kw) -> list[LlmStreamEvent]:
    async def _run() -> list[LlmStreamEvent]:
        return [ev async for ev in rt.generate_reply_stream(
            agent_id="default", session_id="s1", user_text="hi", **kw)]
    return asyncio.run(_run())


def test_runtime_records_cost_and_surfaces_cache_in_usage():
    reset_budget()
    try:
        llm = _FakeStreamingLLM([[
            LlmStreamEvent.make_delta("hi"),
            LlmStreamEvent.make_usage({
                "prompt_tokens": 1000, "completion_tokens": 500,
                "total_tokens": 1500, "cache_read_tokens": 200,
            }),
            LlmStreamEvent.make_done(ChatResponse(content="hi", tool_calls=[], usage=None)),
        ]])
        llm.model = "gpt-4o-mini"
        rt = _make_runtime(llm)
        events = _collect_runtime(rt)

        # The consolidated usage event carries the cache bucket.
        usage_ev = next(e for e in events if e.kind == "usage")
        assert usage_ev.usage["prompt_tokens"] == 1000
        assert usage_ev.usage["cache_read_tokens"] == 200

        # Cost was estimated + recorded into the running budget.
        expected = round(1000 * 0.15 / 1e6 + 500 * 0.60 / 1e6 + 200 * 0.075 / 1e6, 6)
        snap = budget_snapshot()
        assert snap["total_tokens"] == 1500
        assert snap["total_cost_usd"] == expected
        assert snap["by_model"]["gpt-4o-mini"]["cache_read_tokens"] == 200
    finally:
        reset_budget()


def test_runtime_usage_without_cache_keeps_canonical_three_keys():
    reset_budget()
    try:
        llm = _FakeStreamingLLM([[
            LlmStreamEvent.make_usage({"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}),
            LlmStreamEvent.make_done(ChatResponse(content="x", tool_calls=[], usage=None)),
        ]])
        rt = _make_runtime(llm)
        events = _collect_runtime(rt)
        usage_ev = next(e for e in events if e.kind == "usage")
        # Backward-compatible: no cache → exactly the 3 canonical keys.
        assert usage_ev.usage == {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}
    finally:
        reset_budget()


# ==================================================================
# /http/budget endpoint
# ==================================================================


_TOKEN = "test-admin-token-xxxxxxxxxxxxxxxx"


def _build_app():
    cfg = {
        "server":  {"host": "127.0.0.1", "port": 8081},
        "storage": {"backend": "sqlite", "db_path": ":memory:"},
        "admin":   {"enabled": True, "token": _TOKEN},
        "auth":    {"enabled": False},
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.safe_dump(cfg, f)
        cfg_path = f.name
    return create_app(config_path=cfg_path, message_handler=lambda gw, msg: None)


def test_http_budget_endpoint_reports_running_snapshot():
    reset_budget()
    try:
        record_tokens("gpt-4o", total_tokens=2000)
        record_cost("gpt-4o", cost_usd=0.123456, cache_read_tokens=10)
        app = _build_app()
        with TestClient(app) as client:
            r = client.get("/http/budget")
        assert r.status_code == 200
        data = r.json()
        assert data["total_tokens"] == 2000
        assert data["total_cost_usd"] == 0.123456
        assert data["by_model"]["gpt-4o"]["cost_usd"] == 0.123456
        assert data["by_model"]["gpt-4o"]["cache_read_tokens"] == 10
        assert "disclaimer" in data and "estimate" in data["disclaimer"].lower()
    finally:
        reset_budget()
