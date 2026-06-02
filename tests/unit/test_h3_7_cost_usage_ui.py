"""Tests for H3.7 — cost/usage surfacing (backend enabler).

H3.6 captured cache tokens and estimated cost into telemetry, but
the science UI never saw a per-turn cost. H3.7 wires the estimate
through to the client:

  - ``LlmStreamEvent.make_usage(usage, cost=...)`` carries an
    optional USD cost breakdown ALONGSIDE the token dict (the
    token dict shape is never mutated);
  - the agent runtime attaches ``estimate_cost(model, usage)`` to
    its consolidated usage event;
  - the native SSE generator forwards the cost on the ``usage``
    event (``estimated_cost_usd`` + full ``cost`` breakdown) and
    in the ``done`` message metadata, so a reloaded transcript
    keeps its per-turn spend.

These tests pin the backend enabler; the UI rendering itself
(chat.js / science.html) is exercised by the asset + CSS-check
tests.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from typing import Any, AsyncIterator

import yaml
from fastapi.testclient import TestClient

from openmiura.core.agent_runtime import AgentRuntime
from openmiura.core.llm import LlmStreamEvent
from openmiura.core.llm.types import ChatResponse
from openmiura.core.schema import InboundMessage
from openmiura.interfaces.http.app import create_app
from openmiura.interfaces.http.streaming import stream_message_native
from openmiura.observability import reset_budget


# ==================================================================
# types — make_usage carries an optional cost companion
# ==================================================================


def test_make_usage_carries_optional_cost():
    ev = LlmStreamEvent.make_usage(
        {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        cost={"known": True, "total_usd": 0.01},
    )
    assert ev.kind == "usage"
    assert ev.usage == {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}
    assert ev.cost == {"known": True, "total_usd": 0.01}


def test_make_usage_cost_defaults_none():
    ev = LlmStreamEvent.make_usage({"total_tokens": 5})
    assert ev.cost is None


# ==================================================================
# runtime — attaches a cost breakdown to the consolidated usage
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


def test_runtime_attaches_known_cost_with_cache_to_usage_event():
    reset_budget()
    try:
        llm = _FakeStreamingLLM([[
            LlmStreamEvent.make_usage({
                "prompt_tokens": 1000, "completion_tokens": 500,
                "total_tokens": 1500, "cache_read_tokens": 200,
            }),
            LlmStreamEvent.make_done(ChatResponse(content="x", tool_calls=[], usage=None)),
        ]])
        llm.model = "gpt-4o-mini"
        rt = _make_runtime(llm)
        events = _collect_runtime(rt)

        usage_ev = next(e for e in events if e.kind == "usage")
        # Token dict carries the cache bucket; cost rides alongside.
        assert usage_ev.usage["total_tokens"] == 1500
        assert usage_ev.usage["cache_read_tokens"] == 200
        assert usage_ev.cost is not None
        assert usage_ev.cost["known"] is True
        assert usage_ev.cost["total_usd"] > 0
        assert usage_ev.cost["cache_read_usd"] > 0
    finally:
        reset_budget()


def test_runtime_cost_unknown_model_is_flagged_and_zero():
    reset_budget()
    try:
        llm = _FakeStreamingLLM([[
            LlmStreamEvent.make_usage({"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}),
            LlmStreamEvent.make_done(ChatResponse(content="x", tool_calls=[], usage=None)),
        ]])
        # default model "fake" → not in the price table
        rt = _make_runtime(llm)
        events = _collect_runtime(rt)
        usage_ev = next(e for e in events if e.kind == "usage")
        assert usage_ev.cost is not None
        assert usage_ev.cost["known"] is False
        assert usage_ev.cost["total_usd"] == 0.0
        # Token dict stays canonical (no cost leakage).
        assert usage_ev.usage == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    finally:
        reset_budget()


# ==================================================================
# native SSE — cost on the usage event + done metadata
# ==================================================================


class _RecordingAudit:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []

    def get_or_create_session(self, *, channel, user_id, session_id,
                              tenant_id=None, workspace_id=None, environment=None):
        return session_id or "sess_test"

    def append_message(self, *, session_id, role, content):
        self.messages.append({"session_id": session_id, "role": role, "content": content})

    def log_event(self, *, direction, channel=None, user_id=None, session_id=None,
                  payload=None, tenant_id=None, workspace_id=None, environment=None):
        self.events.append({"direction": direction, "payload": dict(payload or {})})


class _FakeRuntimeYields:
    def __init__(self, events: list[LlmStreamEvent]):
        self._events = events

    async def generate_reply_stream(self, **_kwargs) -> AsyncIterator[LlmStreamEvent]:
        for ev in self._events:
            yield ev


class _FakeGateway:
    def __init__(self, audit, runtime):
        self.audit = audit
        self.runtime = runtime
        self.tools = None


def _parse_sse(raw: str) -> list[dict]:
    events: list[dict] = []
    current_event = None
    current_data: list[str] = []
    for line in raw.splitlines():
        if line.startswith("event: "):
            current_event = line[len("event: "):].strip()
        elif line.startswith("data: "):
            current_data.append(line[len("data: "):])
        elif line == "":
            if current_event is not None:
                payload = "\n".join(current_data)
                try:
                    obj = json.loads(payload) if payload else None
                except json.JSONDecodeError:
                    obj = payload
                events.append({"event": current_event, "data": obj})
            current_event = None
            current_data = []
    return events


def test_native_sse_usage_event_carries_cost_and_done_metadata():
    audit = _RecordingAudit()
    cost = {
        "model": "gpt-4o-mini", "known": True,
        "input_usd": 0.0002, "output_usd": 0.0003,
        "cache_read_usd": 0.0, "cache_write_usd": 0.0, "total_usd": 0.0005,
    }
    gw = _FakeGateway(audit, _FakeRuntimeYields([
        LlmStreamEvent.make_delta("answer"),
        LlmStreamEvent.make_usage(
            {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            cost=cost,
        ),
        LlmStreamEvent.make_done(ChatResponse(
            content="answer", tool_calls=[],
            usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150})),
    ]))
    msg = InboundMessage(channel="http", user_id="curro", text="hi")

    async def _drain():
        parts: list[bytes] = []
        async for chunk in stream_message_native(gw, msg):
            parts.append(chunk)
        return _parse_sse(b"".join(parts).decode("utf-8"))

    events = asyncio.run(_drain())

    usage_ev = next(e for e in events if e["event"] == "usage")
    assert usage_ev["data"]["total_tokens"] == 150
    assert usage_ev["data"]["estimated_cost_usd"] == 0.0005
    assert usage_ev["data"]["cost"]["known"] is True
    assert usage_ev["data"]["cost"]["total_usd"] == 0.0005

    done = next(e for e in events if e["event"] == "done")
    meta = done["data"]["message"]["metadata"]
    assert meta["usage"]["total_tokens"] == 150
    assert meta["cost"]["total_usd"] == 0.0005


def test_native_sse_usage_without_cost_omits_cost_keys():
    audit = _RecordingAudit()
    gw = _FakeGateway(audit, _FakeRuntimeYields([
        LlmStreamEvent.make_usage({"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}),
        LlmStreamEvent.make_done(ChatResponse(content="x", tool_calls=[], usage=None)),
    ]))
    msg = InboundMessage(channel="http", user_id="curro", text="hi")

    async def _drain():
        parts: list[bytes] = []
        async for chunk in stream_message_native(gw, msg):
            parts.append(chunk)
        return _parse_sse(b"".join(parts).decode("utf-8"))

    events = asyncio.run(_drain())
    usage_ev = next(e for e in events if e["event"] == "usage")
    # No cost on the event → no cost keys leak into the payload.
    assert "estimated_cost_usd" not in usage_ev["data"]
    assert "cost" not in usage_ev["data"]
    assert usage_ev["data"] == {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}
