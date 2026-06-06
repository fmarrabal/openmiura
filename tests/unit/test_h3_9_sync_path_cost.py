"""Tests for H3.9 — cost on the synchronous /http/message path.

H3.6 instrumented only the streaming runtime path, so
``GET /http/budget`` undercounted: synchronous turns recorded
tokens but no cost. Worse, the sync path recorded tokens via
``record_tokens(model, **usage)`` — which raises ``TypeError``
once ``usage`` carries the H3.6 cache keys
(``cache_read_tokens`` / ``cache_write_tokens``) that
``record_tokens`` does not accept.

H3.9 switches the sync path to explicit kwargs (no more
TypeError) and records estimated cost + cache tokens, so the
budget reflects every turn regardless of streaming mode.
"""

from __future__ import annotations

from typing import Any

from openmiura.core.agent_runtime import AgentRuntime
from openmiura.core.llm.types import ChatResponse
from openmiura.observability import budget_snapshot, reset_budget


class _FakeSyncLLM:
    """Synchronous single-shot LLM double."""

    def __init__(self, response: ChatResponse, model: str = "gpt-4o-mini"):
        self._response = response
        self.model = model
        self.calls = 0

    def chat(self, messages, *, tools=None) -> ChatResponse:
        self.calls += 1
        return self._response


class _PermissiveAudit:
    """get_recent_messages returns []; any other audit call no-ops."""

    def get_recent_messages(self, *, session_id, limit):
        return []

    def __getattr__(self, _name):
        return lambda *a, **k: None


class _FakeSettings:
    class _Runtime:
        history_limit = 0
    class _LLM:
        provider = "openai"
        model = "gpt-4o-mini"
    runtime = _Runtime()
    llm = _LLM()
    agents: dict[str, Any] = {}


def _make_runtime(llm) -> AgentRuntime:
    rt = AgentRuntime.__new__(AgentRuntime)
    rt.llm = llm
    rt.audit = _PermissiveAudit()
    rt.settings = _FakeSettings()
    rt.skill_loader = None
    rt.skills_path = ""
    return rt


def test_sync_path_records_cost_and_cache_into_budget():
    reset_budget()
    try:
        resp = ChatResponse(
            content="the answer",
            tool_calls=[],
            usage={
                "prompt_tokens": 1000, "completion_tokens": 500,
                "total_tokens": 1500, "cache_read_tokens": 200,
            },
        )
        rt = _make_runtime(_FakeSyncLLM(resp, model="gpt-4o-mini"))
        out = rt.generate_reply(agent_id="default", session_id="s1", user_text="hi")
        assert out == "the answer"

        snap = budget_snapshot()
        assert snap["total_tokens"] == 1500
        expected = round(1000 * 0.15 / 1e6 + 500 * 0.60 / 1e6 + 200 * 0.075 / 1e6, 6)
        assert snap["total_cost_usd"] == expected
        assert snap["by_model"]["gpt-4o-mini"]["cache_read_tokens"] == 200
    finally:
        reset_budget()


def test_sync_path_usage_with_cache_keys_does_not_raise():
    """Regression: record_tokens(model, **usage) used to TypeError
    once usage carried H3.6 cache keys. The sync path must absorb a
    cache-laden usage dict without raising and still return text."""
    reset_budget()
    try:
        resp = ChatResponse(
            content="ok",
            tool_calls=[],
            usage={
                "prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15,
                "cache_read_tokens": 3, "cache_write_tokens": 7,
            },
        )
        rt = _make_runtime(_FakeSyncLLM(resp, model="claude-3-5-sonnet"))
        # Must not raise despite the cache keys in usage.
        out = rt.generate_reply(agent_id="default", session_id="s1", user_text="hi")
        assert out == "ok"
        snap = budget_snapshot()
        assert snap["total_tokens"] == 15
        m = snap["by_model"]["claude-3-5-sonnet"]
        assert m["cache_read_tokens"] == 3
        assert m["cache_write_tokens"] == 7
        assert m["cost_usd"] > 0
    finally:
        reset_budget()


def test_sync_path_unknown_model_records_tokens_but_zero_cost():
    reset_budget()
    try:
        resp = ChatResponse(
            content="ok",
            tool_calls=[],
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )
        rt = _make_runtime(_FakeSyncLLM(resp, model="some-unpriced-model"))
        rt.generate_reply(agent_id="default", session_id="s1", user_text="hi")
        snap = budget_snapshot()
        assert snap["total_tokens"] == 15
        # Unknown model → tokens counted, cost stays 0 (never fabricated).
        assert snap["total_cost_usd"] == 0.0
    finally:
        reset_budget()
