"""Tests for H3.4 — extended thinking blocks.

Anthropic's extended thinking surfaces the model's private
reasoning as a dedicated ``thinking`` content block, distinct
from the answer ``text``. On the wire it streams as:

  - ``content_block_start``  with ``content_block.type ==
    "thinking"`` (the trace starts empty);
  - ``content_block_delta``  with ``delta.type ==
    "thinking_delta"`` carrying reasoning fragments;
  - ``content_block_delta``  with ``delta.type ==
    "signature_delta"`` carrying the cryptographic signature
    Anthropic appends (no human-readable reasoning);
  - ``content_block_stop``.

A ``redacted_thinking`` block can also appear, whose reasoning
is encrypted server-side and never human-readable.

H3.4 forwards each ``thinking_delta`` fragment as a new
``kind="thinking"`` event (carrying the raw fragment in the
``thinking`` field). The contract is purely additive and
visibility-only:

  - concatenating every ``thinking`` fragment reproduces the
    full reasoning trace;
  - the reasoning is NEVER merged into the answer text
    (``delta`` events) nor into ``ChatResponse.content``;
  - ``signature_delta`` and ``redacted_thinking`` are absorbed
    without emitting any ``thinking`` event (and without
    raising);
  - the request only asks for thinking when the client is
    constructed with ``thinking_budget_tokens > 0``; the
    budget must be >= 1024 and strictly below
    ``max_output_tokens`` (Anthropic's two hard constraints,
    validated up-front).

These tests pin the contract at four layers: the Anthropic
client (stream + sync + payload), the agent runtime forwarder,
and the HTTP SSE serializer.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from typing import Any, AsyncIterator, Callable

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

from openmiura.core.agent_runtime import AgentRuntime
from openmiura.core.llm import AnthropicClient, LlmStreamEvent
from openmiura.core.llm.types import ChatResponse, ToolCall, ToolResult
from openmiura.interfaces.http.app import create_app


@pytest.fixture(autouse=True)
def _stamp_keys(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_KEY", "sk-ant-test")


# ==================================================================
# Anthropic streaming — thinking_delta fragments → thinking events
# ==================================================================


def _anthropic_sse(events: list[tuple[str, dict[str, Any]]]) -> Callable[[httpx.Request], httpx.Response]:
    parts = [f"event: {name}\ndata: {json.dumps(payload)}" for name, payload in events]
    body = "\n\n".join(parts) + "\n\n"

    def _handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body.encode("utf-8"),
                              headers={"Content-Type": "text/event-stream"})
    return _handler


def _anthropic_client(handler: Callable, **kw) -> AnthropicClient:
    return AnthropicClient(
        base_url="http://test",
        model="claude-test",
        api_key_env_var="ANTHROPIC_KEY",
        timeout_s=5,
        transport=httpx.MockTransport(handler),
        **kw,
    )


def _collect_anthropic(client: AnthropicClient, *, tools=None) -> list[LlmStreamEvent]:
    async def _run() -> list[LlmStreamEvent]:
        return [ev async for ev in client.chat_stream(
            [{"role": "user", "content": "hi"}], tools=tools)]
    return asyncio.run(_run())


def test_anthropic_thinking_block_emits_thinking_events_not_answer_text():
    """A thinking block streams ``thinking`` events; the
    following text block streams ``delta`` events. The two
    never mix: the reasoning stays out of the answer and out of
    ``ChatResponse.content``."""
    handler = _anthropic_sse([
        ("message_start", {"type": "message_start", "message": {
            "id": "m", "role": "assistant", "content": [],
            "usage": {"input_tokens": 10, "output_tokens": 0}}}),
        ("content_block_start", {"type": "content_block_start", "index": 0,
            "content_block": {"type": "thinking", "thinking": ""}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0,
            "delta": {"type": "thinking_delta", "thinking": "Let me reason"}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0,
            "delta": {"type": "thinking_delta", "thinking": " step by step."}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0,
            "delta": {"type": "signature_delta", "signature": "c2lnbmF0dXJl=="}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("content_block_start", {"type": "content_block_start", "index": 1,
            "content_block": {"type": "text", "text": ""}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 1,
            "delta": {"type": "text_delta", "text": "The answer is 42."}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 1}),
        ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn"},
            "usage": {"output_tokens": 20}}),
        ("message_stop", {"type": "message_stop"}),
    ])
    events = _collect_anthropic(_anthropic_client(handler))

    thinking = [e.thinking for e in events if e.kind == "thinking"]
    # signature_delta yields no thinking event → exactly 2.
    assert len(thinking) == 2
    assert "".join(thinking) == "Let me reason step by step."

    deltas = [e.delta for e in events if e.kind == "delta"]
    assert "".join(deltas) == "The answer is 42."

    # The materialised answer excludes the reasoning entirely.
    done = next(e for e in events if e.kind == "done")
    assert done.final.content == "The answer is 42."
    assert "reason" not in done.final.content.lower()

    # Ordering: every thinking event precedes the first delta.
    kinds = [e.kind for e in events]
    last_thinking = max(i for i, k in enumerate(kinds) if k == "thinking")
    first_delta = kinds.index("delta")
    assert last_thinking < first_delta


def test_anthropic_signature_delta_alone_emits_no_thinking():
    """A thinking block whose only delta is a ``signature_delta``
    (no readable reasoning) must produce zero thinking events."""
    handler = _anthropic_sse([
        ("message_start", {"type": "message_start", "message": {
            "id": "m", "role": "assistant", "content": [],
            "usage": {"input_tokens": 3, "output_tokens": 0}}}),
        ("content_block_start", {"type": "content_block_start", "index": 0,
            "content_block": {"type": "thinking", "thinking": ""}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0,
            "delta": {"type": "signature_delta", "signature": "b25seQ=="}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("message_stop", {"type": "message_stop"}),
    ])
    events = _collect_anthropic(_anthropic_client(handler))
    assert all(e.kind != "thinking" for e in events)


def test_anthropic_redacted_thinking_is_absorbed_without_crashing():
    """A ``redacted_thinking`` block (encrypted reasoning) must
    not raise and must surface no thinking event; the following
    text still streams normally."""
    handler = _anthropic_sse([
        ("message_start", {"type": "message_start", "message": {
            "id": "m", "role": "assistant", "content": [],
            "usage": {"input_tokens": 4, "output_tokens": 0}}}),
        ("content_block_start", {"type": "content_block_start", "index": 0,
            "content_block": {"type": "redacted_thinking", "data": "ZW5jcnlwdGVk"}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("content_block_start", {"type": "content_block_start", "index": 1,
            "content_block": {"type": "text", "text": ""}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 1,
            "delta": {"type": "text_delta", "text": "Hi"}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 1}),
        ("message_stop", {"type": "message_stop"}),
    ])
    events = _collect_anthropic(_anthropic_client(handler))
    assert all(e.kind != "thinking" for e in events)
    done = next(e for e in events if e.kind == "done")
    assert done.final.content == "Hi"


def test_anthropic_thinking_then_text_then_tool_use_stay_isolated():
    """thinking → text → tool_use in one response: the thinking
    fragments, the answer text, and the tool call must each end
    up in their own channel, in order, with nothing leaking
    into the assembled answer or the ToolCall."""
    handler = _anthropic_sse([
        ("message_start", {"type": "message_start", "message": {
            "id": "m", "role": "assistant", "content": [],
            "usage": {"input_tokens": 12, "output_tokens": 0}}}),
        ("content_block_start", {"type": "content_block_start", "index": 0,
            "content_block": {"type": "thinking", "thinking": ""}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0,
            "delta": {"type": "thinking_delta", "thinking": "Need to look it up."}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0,
            "delta": {"type": "signature_delta", "signature": "c2ln"}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("content_block_start", {"type": "content_block_start", "index": 1,
            "content_block": {"type": "text", "text": ""}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 1,
            "delta": {"type": "text_delta", "text": "Let me check."}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 1}),
        ("content_block_start", {"type": "content_block_start", "index": 2,
            "content_block": {"type": "tool_use", "id": "toolu_9", "name": "search", "input": {}}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 2,
            "delta": {"type": "input_json_delta", "partial_json": '{"q":"x"}'}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 2}),
        ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "tool_use"},
            "usage": {"output_tokens": 30}}),
        ("message_stop", {"type": "message_stop"}),
    ])
    events = _collect_anthropic(
        _anthropic_client(handler),
        tools=[{"type": "function", "function": {"name": "search", "parameters": {}}}],
    )

    kinds = [e.kind for e in events]
    # Backbone with the visibility-only fragments filtered out.
    backbone = [k for k in kinds if k not in ("thinking", "tool_call_delta")]
    assert backbone == ["delta", "tool_call", "usage", "done"]
    assert "thinking" in kinds

    thinking = "".join(e.thinking for e in events if e.kind == "thinking")
    assert thinking == "Need to look it up."

    # Answer text excludes the reasoning.
    done = next(e for e in events if e.kind == "done")
    assert done.final.content == "Let me check."

    # The tool call is intact and uncontaminated.
    tc = next(e for e in events if e.kind == "tool_call")
    assert tc.tool_call.name == "search"
    assert tc.tool_call.arguments == {"q": "x"}

    # Ordering: thinking, then text, then the tool call.
    assert max(i for i, k in enumerate(kinds) if k == "thinking") < kinds.index("delta")
    assert kinds.index("delta") < kinds.index("tool_call")


# ==================================================================
# Anthropic request payload — opt-in thinking config + validation
# ==================================================================


def _capture_chat(client: AnthropicClient) -> dict[str, Any]:
    """Run a one-shot ``chat`` and return the request body the
    client posted, via a recording transport."""
    captured: dict[str, Any] = {}

    def _handler(req: httpx.Request) -> httpx.Response:
        captured.update(json.loads(req.content))
        return httpx.Response(200, json={
            "content": [{"type": "text", "text": "ok"}],
            "usage": {"input_tokens": 1, "output_tokens": 1},
        })

    client._transport = httpx.MockTransport(_handler)
    client.chat([{"role": "user", "content": "hi"}])
    return captured


def test_thinking_disabled_by_default_omits_payload_field():
    """With no ``thinking_budget_tokens`` the request must not
    carry a ``thinking`` field at all."""
    client = AnthropicClient(
        base_url="http://test", model="claude-test",
        api_key_env_var="ANTHROPIC_KEY", timeout_s=5,
    )
    body = _capture_chat(client)
    assert "thinking" not in body


def test_thinking_budget_adds_enabled_payload_field():
    """A positive budget adds ``thinking = {type: enabled,
    budget_tokens: N}`` to the request."""
    client = AnthropicClient(
        base_url="http://test", model="claude-test",
        api_key_env_var="ANTHROPIC_KEY", timeout_s=5,
        max_output_tokens=4096, thinking_budget_tokens=1500,
    )
    body = _capture_chat(client)
    assert body["thinking"] == {"type": "enabled", "budget_tokens": 1500}
    # And max_tokens still exceeds the budget on the wire.
    assert body["max_tokens"] > body["thinking"]["budget_tokens"]


def test_thinking_budget_below_minimum_rejected():
    """Anthropic requires a budget of at least 1024 tokens."""
    with pytest.raises(ValueError, match="1024"):
        AnthropicClient(
            base_url="http://test", model="claude-test",
            api_key_env_var="ANTHROPIC_KEY",
            max_output_tokens=4096, thinking_budget_tokens=512,
        )


def test_thinking_budget_not_below_max_tokens_rejected():
    """The budget must be strictly less than max_output_tokens."""
    with pytest.raises(ValueError, match="max_output_tokens"):
        AnthropicClient(
            base_url="http://test", model="claude-test",
            api_key_env_var="ANTHROPIC_KEY",
            max_output_tokens=2048, thinking_budget_tokens=4096,
        )


def test_sync_chat_excludes_thinking_block_from_content():
    """A non-streaming response containing a thinking block plus
    a text block must yield a ChatResponse whose ``content`` is
    the text only — the reasoning never lands in the answer."""
    def _handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "content": [
                {"type": "thinking", "thinking": "secret reasoning", "signature": "sig=="},
                {"type": "redacted_thinking", "data": "ZW5j"},
                {"type": "text", "text": "Final answer."},
            ],
            "usage": {"input_tokens": 5, "output_tokens": 7},
        })

    client = _anthropic_client(_handler)
    resp = client.chat([{"role": "user", "content": "hi"}])
    assert resp.content == "Final answer."
    assert "reasoning" not in resp.content.lower()
    assert resp.tool_calls == []


# ==================================================================
# Agent runtime — forwards thinking, keeps it out of the answer
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


def test_runtime_forwards_thinking_and_keeps_it_out_of_the_answer():
    """The runtime forwards ``thinking`` events untouched and
    must not fold the reasoning into the assistant answer it
    accumulates (and ultimately audits)."""
    llm = _FakeStreamingLLM([
        [
            LlmStreamEvent.make_thinking("First I consider "),
            LlmStreamEvent.make_thinking("the options."),
            LlmStreamEvent.make_delta("Here is the answer."),
            LlmStreamEvent.make_done(ChatResponse(
                content="Here is the answer.", tool_calls=[], usage=None)),
        ],
    ])
    rt = _make_runtime(llm)
    events = _collect_runtime(rt)

    thinking = [e.thinking for e in events if e.kind == "thinking"]
    assert "".join(thinking) == "First I consider the options."

    # The deltas reconstruct the answer; thinking is absent from it.
    deltas = "".join(e.delta for e in events if e.kind == "delta")
    assert deltas == "Here is the answer."
    assert "consider" not in deltas

    done = next(e for e in events if e.kind == "done")
    assert done.final.content == "Here is the answer."
    assert "consider" not in done.final.content


# ==================================================================
# HTTP SSE — thinking serialized to the wire
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


class _FakeStreamingRuntime:
    def __init__(self, events):
        self._events = events

    def supports_streaming(self) -> bool:
        return True

    async def generate_reply_stream(self, **_kwargs):
        for ev in self._events:
            yield ev


def test_http_stream_serializes_thinking_event():
    """The native SSE endpoint must emit a ``thinking`` event
    carrying the reasoning fragment in ``delta``, ahead of the
    answer chunks, so the browser can render a collapsible
    reasoning trace."""
    app = _build_app()
    fake_runtime = _FakeStreamingRuntime([
        LlmStreamEvent.make_thinking("Considering... "),
        LlmStreamEvent.make_thinking("done."),
        LlmStreamEvent.make_delta("Answer."),
        LlmStreamEvent.make_done(ChatResponse(content="Answer.", tool_calls=[], usage=None)),
    ])
    with TestClient(app) as client:
        app.state.gw.runtime = fake_runtime
        r = client.post("/http/message/stream",
                        json={"channel": "http", "user_id": "curro", "text": "hi"})
    assert r.status_code == 200
    events = _parse_sse(r.text)
    kinds = [e["event"] for e in events]
    assert "thinking" in kinds
    # thinking events precede the first answer chunk.
    assert kinds.index("thinking") < kinds.index("chunk")

    thinking = [e["data"]["delta"] for e in events if e["event"] == "thinking"]
    assert "".join(thinking) == "Considering... done."

    # The reasoning never leaks into the answer chunks.
    chunks = "".join(e["data"]["delta"] for e in events if e["event"] == "chunk")
    assert chunks == "Answer."
    assert "Considering" not in chunks
