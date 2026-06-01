"""Tests for H3.5 — client cancellation mid-stream.

Before H3.5 a native stream ran to completion no matter what:
once ``generate_reply_stream`` started there was no way for the
caller to stop it, and a client that navigated away simply left
the server generating tokens nobody would read, with no audit
record of the abandonment.

H3.5 adds cooperative cancellation:

  - the agent runtime accepts a ``cancel_check`` predicate and,
    when it trips, stops at the next checkpoint (between rounds
    and between streamed events), emitting a single terminal
    ``kind="cancelled"`` event — no ``done`` follows;
  - the native SSE generator mints a ``stream_id`` (surfaced in
    the ``meta`` event) and registers a cancel ``Event`` in a
    module registry; a ``DELETE /http/message/stream/{id}`` flips
    it; the generator maps the runtime's ``cancelled`` event to
    an ``event: cancelled`` and audits the partial assistant
    turn flagged ``cancelled``;
  - if the client just drops the connection, the transport
    throws ``CancelledError``/``GeneratorExit`` into the
    generator, which still audits the partial turn (reason
    ``client_disconnected``) before propagating.

These tests pin the contract at the runtime, the SSE generator
(graceful + disconnect), the registry and the DELETE route.
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
from openmiura.interfaces.http.streaming import (
    active_stream_count,
    cancel_stream,
    register_stream,
    stream_message_native,
    unregister_stream,
)


# ==================================================================
# types — make_cancelled
# ==================================================================


def test_make_cancelled_constructs_terminal_payload_free_event():
    ev = LlmStreamEvent.make_cancelled()
    assert ev.kind == "cancelled"
    # It carries no payload — the reason lives at the transport layer.
    assert ev.delta is None
    assert ev.thinking is None
    assert ev.tool_call is None
    assert ev.tool_call_delta is None
    assert ev.tool_result is None
    assert ev.final is None
    assert ev.error is None


# ==================================================================
# Agent runtime — cancel_check trips → cancelled event
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


def test_runtime_emits_cancelled_when_cancel_check_trips_mid_stream():
    """A cancel_check that flips truthy after the first event
    yields one delta then a terminal ``cancelled`` — no ``done``."""
    llm = _FakeStreamingLLM([[
        LlmStreamEvent.make_delta("partial "),
        LlmStreamEvent.make_delta("more"),
        LlmStreamEvent.make_done(ChatResponse(content="partial more", tool_calls=[], usage=None)),
    ]])
    rt = _make_runtime(llm)

    # Checked at round-top (1, False), before event 1 (2, False),
    # before event 2 (3, True → cancel).
    calls = {"n": 0}
    def cancel_check() -> bool:
        calls["n"] += 1
        return calls["n"] > 2

    events = _collect_runtime(rt, cancel_check=cancel_check)
    kinds = [e.kind for e in events]
    assert kinds == ["delta", "cancelled"]
    assert events[0].delta == "partial "
    assert "done" not in kinds


def test_runtime_cancels_before_first_round_without_calling_llm():
    """A cancel_check already truthy stops before any LLM call —
    the only event is ``cancelled`` and chat_stream never runs."""
    llm = _FakeStreamingLLM([[
        LlmStreamEvent.make_delta("never seen"),
        LlmStreamEvent.make_done(ChatResponse(content="x", tool_calls=[], usage=None)),
    ]])
    rt = _make_runtime(llm)
    events = _collect_runtime(rt, cancel_check=lambda: True)
    assert [e.kind for e in events] == ["cancelled"]
    assert llm.calls == []


def test_runtime_without_cancel_check_completes_normally():
    """Omitting cancel_check is a no-op: the stream finishes with
    a ``done`` and no ``cancelled`` event (default path intact)."""
    llm = _FakeStreamingLLM([[
        LlmStreamEvent.make_delta("hi"),
        LlmStreamEvent.make_done(ChatResponse(content="hi", tool_calls=[], usage=None)),
    ]])
    rt = _make_runtime(llm)
    events = _collect_runtime(rt)
    kinds = [e.kind for e in events]
    assert "cancelled" not in kinds
    assert kinds[-1] == "done"


# ==================================================================
# Native SSE generator — graceful cancel + disconnect
# ==================================================================


class _RecordingAudit:
    """Captures the audit calls the streaming generator makes so a
    test can assert a cancelled turn was recorded."""

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


def test_native_generator_emits_cancelled_event_and_audits_partial():
    """When the runtime yields a ``cancelled`` event, the SSE
    generator emits ``event: cancelled`` (after the streamed
    chunk, with no trailing ``done``) and audits the partial
    assistant turn flagged cancelled."""
    audit = _RecordingAudit()
    gw = _FakeGateway(audit, _FakeRuntimeYields([
        LlmStreamEvent.make_delta("partial answer"),
        LlmStreamEvent.make_cancelled(),
    ]))
    msg = InboundMessage(channel="http", user_id="curro", text="hi")

    async def _drain():
        parts: list[bytes] = []
        async for chunk in stream_message_native(gw, msg):
            parts.append(chunk)
        return _parse_sse(b"".join(parts).decode("utf-8"))

    events = asyncio.run(_drain())
    kinds = [e["event"] for e in events]
    assert "cancelled" in kinds
    assert "done" not in kinds, "a cancelled stream must not emit done"
    assert kinds.index("chunk") < kinds.index("cancelled")

    cev = next(e for e in events if e["event"] == "cancelled")
    assert cev["data"]["reason"] == "cancelled_by_client"

    # meta carried a stream_id for the client to DELETE.
    meta = next(e for e in events if e["event"] == "meta")
    assert isinstance(meta["data"].get("stream_id"), str) and meta["data"]["stream_id"]

    # The partial assistant turn was audited, flagged cancelled.
    assistant = [m for m in audit.messages if m["role"] == "assistant"]
    assert assistant and assistant[-1]["content"] == "partial answer"
    out = [e for e in audit.events if e["direction"] == "out"]
    assert out and out[-1]["payload"].get("cancelled") is True
    assert out[-1]["payload"].get("cancel_reason") == "cancelled_by_client"

    # The registry is clean once the generator finishes.
    assert active_stream_count() == 0


def test_native_generator_disconnect_audits_partial_turn():
    """If the client drops mid-stream (generator aclose →
    GeneratorExit), the partial turn is still audited as
    cancelled with reason ``client_disconnected``."""
    audit = _RecordingAudit()
    gw = _FakeGateway(audit, _FakeRuntimeYields([
        LlmStreamEvent.make_delta("hello "),
        LlmStreamEvent.make_delta("world"),
        LlmStreamEvent.make_done(ChatResponse(content="hello world", tool_calls=[], usage=None)),
    ]))
    msg = InboundMessage(channel="http", user_id="curro", text="hi")

    async def _disconnect_after_first_chunk():
        gen = stream_message_native(gw, msg)
        await gen.__anext__()   # meta
        await gen.__anext__()   # first chunk ("hello ")
        await gen.aclose()      # client goes away

    asyncio.run(_disconnect_after_first_chunk())

    out = [e for e in audit.events if e["direction"] == "out"]
    assert out, "expected an audited assistant turn on disconnect"
    last = out[-1]
    assert last["payload"].get("cancelled") is True
    assert last["payload"].get("cancel_reason") == "client_disconnected"
    # Only the first delta had been consumed before the drop.
    assert last["payload"]["text"] == "hello"
    assert active_stream_count() == 0


# ==================================================================
# Registry + DELETE endpoint
# ==================================================================


def test_stream_registry_register_cancel_unregister_cycle():
    ev = asyncio.Event()
    sid = "h35-registry-test"
    register_stream(sid, ev)
    try:
        assert cancel_stream(sid) is True
        assert ev.is_set()
        assert cancel_stream("never-registered") is False
    finally:
        unregister_stream(sid)
    # Gone after unregister.
    assert cancel_stream(sid) is False


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


def test_delete_cancel_endpoint_returns_202_for_live_404_for_unknown():
    app = _build_app()
    with TestClient(app) as client:
        # Unknown / already-finished stream → 404.
        r404 = client.delete("/http/message/stream/no-such-stream")
        assert r404.status_code == 404

        # Register a live stream, then DELETE it → 202 and the
        # cancel Event is set.
        ev = asyncio.Event()
        register_stream("h35-route-test", ev)
        try:
            r202 = client.delete("/http/message/stream/h35-route-test")
            assert r202.status_code == 202
            body = r202.json()
            assert body["stream_id"] == "h35-route-test"
            assert body["cancelled"] is True
            assert ev.is_set()
        finally:
            unregister_stream("h35-route-test")
