"""Tests for streaming decision traces.

The native streaming endpoint (`/http/message/stream`) historically
produced NO decision trace, so streaming turns fed the in-process
`/http/budget` gauge but never the persistent cost-governance
surface (`decision_traces` + the `/admin` cost routes) that the
synchronous `/http/message` path populates.

This change gives streaming turns parity: `stream_message_native`
builds a trace_payload, the runtime fills `llm_calls` + `tool_rounds`
through a `trace_collector`, and the trace is persisted on every
exit path (completed / graceful-cancel / disconnect / error) through
the shared `_persist_decision_trace` — which also derives
`estimated_cost` from usage + model (H3.10).

These tests pin: the runtime filling the collector, and the HTTP
generator persisting exactly one trace per turn with the right
status on each exit path.
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

from openmiura.core.agent_runtime import AgentRuntime
from openmiura.core.llm import LlmStreamEvent
from openmiura.core.llm.types import ChatResponse
from openmiura.core.schema import InboundMessage
from openmiura.interfaces.http.streaming import stream_message_native
from openmiura.observability import reset_budget


# ==================================================================
# Shared fakes
# ==================================================================


class _TracingAudit:
    """One audit double serving both the runtime (get_recent_messages)
    and the HTTP layer (session/message/event/decision-trace)."""

    def __init__(self) -> None:
        self.traces: list[dict[str, Any]] = []
        self.messages: list[tuple[str, str]] = []

    def get_recent_messages(self, *, session_id, limit):
        return []

    def get_or_create_session(self, *, channel, user_id, session_id,
                              tenant_id=None, workspace_id=None, environment=None):
        return session_id or "sess_test"

    def append_message(self, *, session_id, role, content):
        self.messages.append((role, content))

    def log_event(self, **_kw):
        pass

    def log_decision_trace(self, **kw):
        self.traces.append(kw)


class _LLMCfg:
    provider = "openai"
    model = "gpt-4o-mini"


class _Settings:
    llm = _LLMCfg()


class _FakeGw:
    def __init__(self, audit, runtime):
        self.audit = audit
        self.runtime = runtime
        self.tools = None
        self.settings = _Settings()
        self.realtime_bus = None


class _FakeRuntimeYields:
    """HTTP-layer-only double: yields the given events verbatim."""

    def __init__(self, events: list[LlmStreamEvent]):
        self._events = events

    async def generate_reply_stream(self, **_kwargs) -> AsyncIterator[LlmStreamEvent]:
        for ev in self._events:
            yield ev


class _FakeStreamingLLM:
    def __init__(self, rounds: list[list[LlmStreamEvent]]):
        self._rounds = list(rounds)
        self.model = "gpt-4o-mini"

    def chat_stream(self, messages, *, tools=None) -> AsyncIterator[LlmStreamEvent]:
        events = self._rounds.pop(0) if self._rounds else []

        async def _gen() -> AsyncIterator[LlmStreamEvent]:
            for ev in events:
                yield ev
        return _gen()


class _RuntimeSettings:
    class _Runtime:
        history_limit = 0
    class _LLM:
        provider = "openai"
        model = "gpt-4o-mini"
    runtime = _Runtime()
    llm = _LLM()
    agents: dict[str, Any] = {}


def _make_runtime(llm, audit) -> AgentRuntime:
    rt = AgentRuntime.__new__(AgentRuntime)
    rt.llm = llm
    rt.audit = audit
    rt.settings = _RuntimeSettings()
    rt.skill_loader = None
    rt.skills_path = ""
    return rt


def _drain(gw, msg) -> None:
    async def _run():
        async for _chunk in stream_message_native(gw, msg):
            pass
    asyncio.run(_run())


# ==================================================================
# Runtime — fills trace_collector
# ==================================================================


def test_runtime_fills_trace_collector_llm_calls_and_tool_rounds():
    reset_budget()
    try:
        audit = _TracingAudit()
        llm = _FakeStreamingLLM([[
            LlmStreamEvent.make_usage({"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}),
            LlmStreamEvent.make_done(ChatResponse(content="x", tool_calls=[], usage=None)),
        ]])
        rt = _make_runtime(llm, audit)
        tc: dict[str, Any] = {}

        async def _run():
            async for _ in rt.generate_reply_stream(
                agent_id="default", session_id="s1", user_text="hi", trace_collector=tc):
                pass
        asyncio.run(_run())

        # No tools → 1 LLM call, 0 tool rounds.
        assert tc["llm_calls"] == [{"round": 0}]
        assert tc["decisions"]["tool_rounds"] == 0
    finally:
        reset_budget()


# ==================================================================
# HTTP generator — persists a trace on every exit path
# ==================================================================


def test_streaming_completed_persists_trace_with_cost():
    """A completed streaming turn persists exactly one decision trace
    with status=completed, the response text, the model, the token
    counts, an H3.10-derived cost, and the runtime's llm_calls."""
    reset_budget()
    try:
        audit = _TracingAudit()
        llm = _FakeStreamingLLM([[
            LlmStreamEvent.make_delta("The answer is 42."),
            LlmStreamEvent.make_usage({"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500}),
            LlmStreamEvent.make_done(ChatResponse(content="The answer is 42.", tool_calls=[], usage=None)),
        ]])
        rt = _make_runtime(llm, audit)
        gw = _FakeGw(audit, rt)
        _drain(gw, InboundMessage(channel="http", user_id="curro", text="hi"))

        assert len(audit.traces) == 1, "exactly one decision trace per streaming turn"
        tr = audit.traces[0]
        assert tr["status"] == "completed"
        assert "answer is 42" in tr["response_text"]
        assert tr["model"] == "gpt-4o-mini"
        assert tr["input_tokens"] == 1000
        assert tr["output_tokens"] == 500
        assert tr["total_tokens"] == 1500
        # H3.10 — cost derived from usage + model.
        expected = round(1000 * 0.15 / 1e6 + 500 * 0.60 / 1e6, 6)
        assert tr["estimated_cost"] == expected
        # Runtime filled llm_calls (rounds + 1 = 1).
        assert tr["llm_calls"] == 1
    finally:
        reset_budget()


def test_streaming_graceful_cancel_persists_cancelled_trace():
    audit = _TracingAudit()
    gw = _FakeGw(audit, _FakeRuntimeYields([
        LlmStreamEvent.make_delta("partial answer"),
        LlmStreamEvent.make_cancelled(),
    ]))
    _drain(gw, InboundMessage(channel="http", user_id="curro", text="hi"))

    assert len(audit.traces) == 1
    tr = audit.traces[0]
    assert tr["status"] == "cancelled"
    assert tr["response_text"] == "partial answer"


def test_streaming_disconnect_persists_cancelled_trace():
    audit = _TracingAudit()
    gw = _FakeGw(audit, _FakeRuntimeYields([
        LlmStreamEvent.make_delta("hello "),
        LlmStreamEvent.make_delta("world"),
        LlmStreamEvent.make_done(ChatResponse(content="hello world", tool_calls=[], usage=None)),
    ]))
    msg = InboundMessage(channel="http", user_id="curro", text="hi")

    async def _disconnect_after_first_chunk():
        gen = stream_message_native(gw, msg)
        await gen.__anext__()   # meta
        await gen.__anext__()   # first chunk
        await gen.aclose()      # client drops

    asyncio.run(_disconnect_after_first_chunk())

    assert len(audit.traces) == 1
    tr = audit.traces[0]
    assert tr["status"] == "cancelled"
    assert tr["response_text"] == "hello"


def test_streaming_error_event_persists_error_trace():
    audit = _TracingAudit()
    gw = _FakeGw(audit, _FakeRuntimeYields([
        LlmStreamEvent.make_delta("oops "),
        LlmStreamEvent.make_error("upstream exploded"),
    ]))
    _drain(gw, InboundMessage(channel="http", user_id="curro", text="hi"))

    assert len(audit.traces) == 1
    assert audit.traces[0]["status"] == "error"
