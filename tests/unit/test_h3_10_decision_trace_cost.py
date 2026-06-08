"""Tests for H3.10 — populate decision-trace estimated_cost.

A persistent cost-governance surface already existed
(``decision_traces`` + the ``/admin`` cost_summary / cost_budgets
/ cost_alerts routes), but ``estimated_cost`` was always ``0.0``:
there was no calculator. H3.6 added one; H3.10 wires it in.

``_persist_decision_trace`` now derives ``estimated_cost`` from
the trace's usage + model (via ``pricing.estimate_cost``) when the
trace didn't carry an explicit cost, and the runtime accumulates
prompt-cache tokens into the trace usage so the persisted figure
reflects the cache discount.
"""

from __future__ import annotations

from typing import Any

from openmiura.core.agent_runtime import AgentRuntime
from openmiura.core.llm.types import ChatResponse
from openmiura.pipeline import _persist_decision_trace


# ==================================================================
# _persist_decision_trace — cost derivation
# ==================================================================


class _CapturingAudit:
    def __init__(self) -> None:
        self.logged: list[dict[str, Any]] = []

    def log_decision_trace(self, **kwargs):
        self.logged.append(kwargs)


class _FakeGw:
    def __init__(self, audit):
        self.audit = audit
        self.realtime_bus = None


def _persist(trace: dict[str, Any]) -> dict[str, Any]:
    audit = _CapturingAudit()
    _persist_decision_trace(
        _FakeGw(audit),
        trace_id="t1", session_id="s1", user_key="u1", channel="http",
        agent_id="default", tenant_id=None, workspace_id=None, environment=None,
        trace=trace,
    )
    assert len(audit.logged) == 1
    return audit.logged[0]


def test_persist_trace_computes_cost_from_usage_and_model():
    logged = _persist({
        "model": "gpt-4o-mini",
        "usage": {"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500},
        "estimated_cost": 0.0,
    })
    expected = round(1000 * 0.15 / 1e6 + 500 * 0.60 / 1e6, 6)
    assert logged["estimated_cost"] == expected
    # Token columns are still derived from usage, unchanged.
    assert logged["input_tokens"] == 1000
    assert logged["output_tokens"] == 500
    assert logged["total_tokens"] == 1500


def test_persist_trace_respects_explicit_nonzero_cost():
    logged = _persist({
        "model": "gpt-4o-mini",
        "usage": {"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500},
        "estimated_cost": 0.99,  # already set → must NOT be overwritten
    })
    assert logged["estimated_cost"] == 0.99


def test_persist_trace_unknown_model_keeps_zero_cost():
    logged = _persist({
        "model": "some-unpriced-model",
        "usage": {"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500},
        "estimated_cost": 0.0,
    })
    # Tokens recorded, cost stays 0.0 — never fabricated.
    assert logged["total_tokens"] == 1500
    assert logged["estimated_cost"] == 0.0


def test_persist_trace_applies_cache_read_rate():
    # gpt-4o-mini: cache-read 0.075/1M vs input 0.15/1M.
    logged = _persist({
        "model": "gpt-4o-mini",
        "usage": {"prompt_tokens": 0, "completion_tokens": 0,
                  "total_tokens": 1000, "cache_read_tokens": 1000},
        "estimated_cost": 0.0,
    })
    assert logged["estimated_cost"] == round(1000 * 0.075 / 1e6, 6)


def test_persist_trace_no_usage_stays_zero():
    logged = _persist({"model": "gpt-4o-mini", "usage": {}, "estimated_cost": 0.0})
    assert logged["estimated_cost"] == 0.0


# ==================================================================
# runtime — trace_collector accumulates cache tokens
# ==================================================================


class _FakeSyncLLM:
    def __init__(self, response: ChatResponse, model: str = "gpt-4o-mini"):
        self._response = response
        self.model = model

    def chat(self, messages, *, tools=None) -> ChatResponse:
        return self._response


class _PermissiveAudit:
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


def test_runtime_trace_collector_accumulates_cache_tokens():
    resp = ChatResponse(
        content="x", tool_calls=[],
        usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15,
               "cache_read_tokens": 4, "cache_write_tokens": 2},
    )
    rt = _make_runtime(_FakeSyncLLM(resp, model="gpt-4o-mini"))
    trace: dict[str, Any] = {}
    rt.generate_reply(agent_id="default", session_id="s1", user_text="hi", trace_collector=trace)

    u = trace["usage"]
    assert u["total_tokens"] == 15
    assert u["cache_read_tokens"] == 4
    assert u["cache_write_tokens"] == 2
