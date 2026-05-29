"""Tests for H3.2 — streaming tool-call arguments.

Before H3.2 the streaming clients buffered a tool call's
whole argument JSON and only surfaced it once assembled, as a
single ``tool_call`` event. The UI could show *that* a tool
was about to run but not watch its arguments form. Modern
providers stream those arguments piecewise (OpenAI:
``function.arguments`` string fragments; Anthropic:
``input_json_delta.partial_json`` fragments), so the latency
to "first visible argument" was the whole JSON, not the first
token.

H3.2 forwards each fragment as a new ``kind="tool_call_delta"``
event (carrying a ``ToolCallDelta``) BEFORE the assembled
``tool_call`` arrives. The contract is purely additive:

  - concatenating every ``arguments_delta`` for a given
    ``index`` reproduces the full arguments JSON string;
  - the first fragment for an index carries ``id`` + ``name``,
    later fragments carry ``None`` for both;
  - the authoritative ``tool_call`` event still fires exactly
    once afterwards and remains the only execution trigger;
  - providers that deliver tool calls atomically (Ollama)
    never emit ``tool_call_delta``.

These tests pin the contract at four layers: the OpenAI
client, the Anthropic client, the agent runtime forwarder,
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
from openmiura.core.llm import AnthropicClient, LlmStreamEvent, OpenAICompatibleClient
from openmiura.core.llm.types import ChatResponse, ToolCall, ToolCallDelta, ToolResult
from openmiura.interfaces.http.app import create_app


# ==================================================================
# OpenAI — function.arguments fragments → tool_call_delta
# ==================================================================


def _openai_sse(lines: list[dict[str, Any] | str]) -> Callable[[httpx.Request], httpx.Response]:
    parts = []
    for item in lines:
        parts.append(f"data: {item if isinstance(item, str) else json.dumps(item)}")
    body = "\n\n".join(parts) + "\n\n"

    def _handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body.encode("utf-8"),
                              headers={"Content-Type": "text/event-stream"})
    return _handler


def _openai_client(handler: Callable) -> OpenAICompatibleClient:
    return OpenAICompatibleClient(
        base_url="http://test",
        model="gpt-test",
        api_key_env_var="OPENAI_KEY",
        timeout_s=5,
        transport=httpx.MockTransport(handler),
    )


def _collect_openai(client: OpenAICompatibleClient, *, tools=None) -> list[LlmStreamEvent]:
    async def _run() -> list[LlmStreamEvent]:
        return [ev async for ev in client.chat_stream(
            [{"role": "user", "content": "hi"}], tools=tools)]
    return asyncio.run(_run())


@pytest.fixture(autouse=True)
def _stamp_keys(monkeypatch):
    monkeypatch.setenv("OPENAI_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_KEY", "sk-ant-test")


def test_openai_streams_arg_fragments_then_full_tool_call():
    """Each ``function.arguments`` chunk becomes a
    ``tool_call_delta``; concatenating their ``arguments_delta``
    yields the full JSON; the assembled ``tool_call`` still
    fires once at the end."""
    handler = _openai_sse([
        {"choices": [{"index": 0, "delta": {
            "tool_calls": [{"index": 0, "id": "call_xyz",
                            "function": {"name": "fs_read", "arguments": ""}}]
        }, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {
            "tool_calls": [{"index": 0, "function": {"arguments": "{\"path\":"}}]
        }, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {
            "tool_calls": [{"index": 0, "function": {"arguments": " \"/tmp/x\"}"}}]
        }, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
        "[DONE]",
    ])
    events = _collect_openai(_openai_client(handler),
                            tools=[{"type": "function", "function": {"name": "fs_read", "parameters": {}}}])

    deltas = [e.tool_call_delta for e in events if e.kind == "tool_call_delta"]
    assert deltas, "expected at least one tool_call_delta"
    assert all(isinstance(d, ToolCallDelta) for d in deltas)
    # All fragments belong to the same call (index 0).
    assert {d.index for d in deltas} == {0}
    # The opening fragment carries id + name.
    assert deltas[0].id == "call_xyz"
    assert deltas[0].name == "fs_read"
    # Argument-only fragments carry neither id nor name.
    assert deltas[1].id is None and deltas[1].name is None
    # Concatenated fragments reconstruct the full arguments JSON.
    joined = "".join(d.arguments_delta for d in deltas)
    assert json.loads(joined) == {"path": "/tmp/x"}

    # The authoritative tool_call still arrives exactly once.
    tc_events = [e for e in events if e.kind == "tool_call"]
    assert len(tc_events) == 1
    assert tc_events[0].tool_call.name == "fs_read"
    assert tc_events[0].tool_call.arguments == {"path": "/tmp/x"}
    assert tc_events[0].tool_call.id == "call_xyz"

    # Ordering: every delta precedes the assembled tool_call.
    first_tc_idx = next(i for i, e in enumerate(events) if e.kind == "tool_call")
    last_delta_idx = max(i for i, e in enumerate(events) if e.kind == "tool_call_delta")
    assert last_delta_idx < first_tc_idx


def test_openai_parallel_calls_emit_index_tagged_deltas():
    """Two parallel calls (index 0 + 1) must produce deltas
    tagged with their own index so a consumer can group them."""
    handler = _openai_sse([
        {"choices": [{"index": 0, "delta": {
            "tool_calls": [
                {"index": 0, "id": "c1", "function": {"name": "tool_a", "arguments": ""}},
                {"index": 1, "id": "c2", "function": {"name": "tool_b", "arguments": ""}},
            ]
        }, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {
            "tool_calls": [{"index": 0, "function": {"arguments": "{\"a\":1}"}}]
        }, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {
            "tool_calls": [{"index": 1, "function": {"arguments": "{\"b\":2}"}}]
        }, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
        "[DONE]",
    ])
    events = _collect_openai(_openai_client(handler))

    deltas = [e.tool_call_delta for e in events if e.kind == "tool_call_delta"]
    by_index: dict[int, str] = {0: "", 1: ""}
    names: dict[int, str | None] = {}
    for d in deltas:
        by_index[d.index] += d.arguments_delta
        if d.name:
            names[d.index] = d.name
    assert names == {0: "tool_a", 1: "tool_b"}
    assert json.loads(by_index[0]) == {"a": 1}
    assert json.loads(by_index[1]) == {"b": 2}


def test_openai_full_dict_arguments_in_one_chunk_emits_single_delta():
    """Some compatible providers send the whole arguments dict
    in one chunk. We marshal it to JSON and forward it as a
    single ``tool_call_delta`` whose fragment parses back to
    the dict."""
    handler = _openai_sse([
        {"choices": [{"index": 0, "delta": {
            "tool_calls": [{"index": 0, "id": "call_1",
                            "function": {"name": "tool_x", "arguments": {"k": 1, "v": "x"}}}]
        }, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
        "[DONE]",
    ])
    events = _collect_openai(_openai_client(handler))
    deltas = [e.tool_call_delta for e in events if e.kind == "tool_call_delta"]
    assert len(deltas) == 1
    assert deltas[0].name == "tool_x"
    assert json.loads(deltas[0].arguments_delta) == {"k": 1, "v": "x"}


# ==================================================================
# Anthropic — input_json_delta fragments → tool_call_delta
# ==================================================================


def _anthropic_sse(events: list[tuple[str, dict[str, Any]]]) -> Callable[[httpx.Request], httpx.Response]:
    parts = [f"event: {name}\ndata: {json.dumps(payload)}" for name, payload in events]
    body = "\n\n".join(parts) + "\n\n"

    def _handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body.encode("utf-8"),
                              headers={"Content-Type": "text/event-stream"})
    return _handler


def _anthropic_client(handler: Callable) -> AnthropicClient:
    return AnthropicClient(
        base_url="http://test",
        model="claude-test",
        api_key_env_var="ANTHROPIC_KEY",
        timeout_s=5,
        transport=httpx.MockTransport(handler),
    )


def _collect_anthropic(client: AnthropicClient, *, tools=None) -> list[LlmStreamEvent]:
    async def _run() -> list[LlmStreamEvent]:
        return [ev async for ev in client.chat_stream(
            [{"role": "user", "content": "hi"}], tools=tools)]
    return asyncio.run(_run())


def test_anthropic_tool_use_emits_opening_then_arg_fragments():
    """A tool_use block emits one opening ``tool_call_delta``
    (id + name, empty args) on content_block_start, then one
    per ``input_json_delta``. Concatenating the argument
    fragments reproduces the JSON; the assembled ``tool_call``
    follows on content_block_stop."""
    handler = _anthropic_sse([
        ("message_start", {"type": "message_start", "message": {
            "id": "m", "role": "assistant", "content": [],
            "usage": {"input_tokens": 30, "output_tokens": 0}}}),
        ("content_block_start", {"type": "content_block_start", "index": 0,
            "content_block": {"type": "tool_use", "id": "toolu_01", "name": "fs_read", "input": {}}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": '{"path":'}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": ' "/tmp/x"}'}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "tool_use"},
            "usage": {"output_tokens": 14}}),
        ("message_stop", {"type": "message_stop"}),
    ])
    events = _collect_anthropic(_anthropic_client(handler),
                               tools=[{"type": "function", "function": {"name": "fs_read", "parameters": {}}}])

    deltas = [e.tool_call_delta for e in events if e.kind == "tool_call_delta"]
    assert len(deltas) == 3, f"opening + 2 arg fragments, got {len(deltas)}"
    # Opening fragment: id + name, no args.
    assert deltas[0].id == "toolu_01"
    assert deltas[0].name == "fs_read"
    assert deltas[0].arguments_delta == ""
    # Argument fragments: no id/name, carry the JSON pieces.
    assert deltas[1].id is None and deltas[1].name is None
    joined = "".join(d.arguments_delta for d in deltas)
    assert json.loads(joined) == {"path": "/tmp/x"}

    # The assembled tool_call still arrives, after the deltas.
    tc_events = [e for e in events if e.kind == "tool_call"]
    assert len(tc_events) == 1
    assert tc_events[0].tool_call.arguments == {"path": "/tmp/x"}
    assert tc_events[0].tool_call.id == "toolu_01"


def test_anthropic_text_only_stream_emits_no_tool_call_delta():
    """A pure-text completion must not produce any
    ``tool_call_delta`` — the new event is tool-use-only."""
    handler = _anthropic_sse([
        ("message_start", {"type": "message_start", "message": {
            "id": "m", "role": "assistant", "content": [],
            "usage": {"input_tokens": 5, "output_tokens": 0}}}),
        ("content_block_start", {"type": "content_block_start", "index": 0,
            "content_block": {"type": "text", "text": ""}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0,
            "delta": {"type": "text_delta", "text": "Hello"}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("message_stop", {"type": "message_stop"}),
    ])
    events = _collect_anthropic(_anthropic_client(handler))
    assert all(e.kind != "tool_call_delta" for e in events)


# ==================================================================
# Agent runtime — forwards tool_call_delta in order
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


class _FakeToolsRuntime:
    def __init__(self, outputs: dict[str, str]):
        self.outputs = outputs

    def available_tool_schemas(self, agent_id, *, user_key=None, **_kwargs):
        return [{"type": "function", "function": {"name": n, "parameters": {}}}
                for n in self.outputs]

    def run_tool(self, *, tool_name, **_kwargs):
        return self.outputs.get(tool_name, f"{tool_name}-ok")


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


def test_runtime_forwards_tool_call_delta_events_in_order():
    """The runtime must forward ``tool_call_delta`` events
    untouched, interleaved with delta/tool_call, and never
    treat them as an execution trigger (the assembled
    ``tool_call`` does that)."""
    final = ChatResponse(content="done", tool_calls=[], usage=None)
    llm = _FakeStreamingLLM([
        [
            LlmStreamEvent.make_delta("Let me look. "),
            LlmStreamEvent.make_tool_call_delta(ToolCallDelta(index=0, id="c1", name="lookup")),
            LlmStreamEvent.make_tool_call_delta(ToolCallDelta(index=0, arguments_delta='{"q":')),
            LlmStreamEvent.make_tool_call_delta(ToolCallDelta(index=0, arguments_delta='"x"}')),
            LlmStreamEvent.make_tool_call(ToolCall(name="lookup", arguments={"q": "x"}, id="c1")),
            LlmStreamEvent.make_done(ChatResponse(
                content="Let me look. ",
                tool_calls=[ToolCall(name="lookup", arguments={"q": "x"}, id="c1")],
                usage=None)),
        ],
        [LlmStreamEvent.make_done(final)],
    ])
    tools = _FakeToolsRuntime({"lookup": "x=42"})
    rt = _make_runtime(llm)
    events = _collect_runtime(rt, tools_runtime=tools, user_key="u1")

    kinds = [e.kind for e in events]
    # The deltas survive and sit before the assembled tool_call,
    # which sits before the tool_result.
    assert kinds.count("tool_call_delta") == 3
    last_delta = max(i for i, k in enumerate(kinds) if k == "tool_call_delta")
    tc_idx = kinds.index("tool_call")
    tr_idx = kinds.index("tool_result")
    assert last_delta < tc_idx < tr_idx
    # The forwarded fragments are intact ToolCallDelta objects.
    fragments = [e.tool_call_delta for e in events if e.kind == "tool_call_delta"]
    assert fragments[0].name == "lookup" and fragments[0].id == "c1"
    assert "".join(f.arguments_delta for f in fragments) == '{"q":"x"}'
    # The tool still ran exactly once and resumed the stream.
    assert [e.tool_result.output for e in events if e.kind == "tool_result"] == ["x=42"]
    assert events[-1].kind == "done"


# ==================================================================
# HTTP SSE — tool_call_delta serialized to the wire
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


def test_http_stream_serializes_tool_call_delta_event():
    """The native SSE endpoint must emit a ``tool_call_delta``
    event carrying index / id / name / arguments_delta so the
    browser can render the call forming."""
    app = _build_app()
    fake_runtime = _FakeStreamingRuntime([
        LlmStreamEvent.make_tool_call_delta(ToolCallDelta(index=0, id="c1", name="lookup")),
        LlmStreamEvent.make_tool_call_delta(ToolCallDelta(index=0, arguments_delta='{"q":"x"}')),
        LlmStreamEvent.make_tool_call(ToolCall(name="lookup", arguments={"q": "x"}, id="c1")),
        LlmStreamEvent.make_tool_result(ToolResult(name="lookup", output="x=42", call_id="c1")),
        LlmStreamEvent.make_done(ChatResponse(content="ok", tool_calls=[], usage=None)),
    ])
    with TestClient(app) as client:
        app.state.gw.runtime = fake_runtime
        r = client.post("/http/message/stream",
                        json={"channel": "http", "user_id": "curro", "text": "hi"})
    assert r.status_code == 200
    events = _parse_sse(r.text)
    kinds = [e["event"] for e in events]
    assert "tool_call_delta" in kinds
    # tool_call_delta events precede the assembled tool_call.
    assert kinds.index("tool_call_delta") < kinds.index("tool_call")

    deltas = [e["data"] for e in events if e["event"] == "tool_call_delta"]
    assert deltas[0]["index"] == 0
    assert deltas[0]["id"] == "c1"
    assert deltas[0]["name"] == "lookup"
    assert deltas[1]["arguments_delta"] == '{"q":"x"}'
    assert deltas[1]["id"] is None and deltas[1]["name"] is None
