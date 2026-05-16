"""Tests for AnthropicClient.chat_stream (H1.3).

Anthropic's streaming wire is typed SSE: pairs of
``event: <name>`` + ``data: <json>`` separated by blank lines.
Content blocks (text, tool_use) have indices; text deltas
arrive as ``text_delta`` payloads, tool-use input arrives as
``input_json_delta`` fragments that the assembler concatenates
into a complete JSON object.

Tests mock the wire via ``httpx.MockTransport``; async
generators run inside ``asyncio.run`` so no pytest-asyncio
dependency is needed.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Callable

import httpx
import pytest

from openmiura.core.llm import AnthropicClient, LlmStreamEvent
from openmiura.core.llm.types import ChatResponse, ToolCall


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _sse_events(events: list[tuple[str, dict[str, Any]]]) -> Callable[[httpx.Request], httpx.Response]:
    """Build a MockTransport handler returning a typed SSE
    body. Each item is ``(event_name, payload_dict)``."""
    parts = []
    for ev_name, payload in events:
        parts.append(f"event: {ev_name}\ndata: {json.dumps(payload)}")
    body = "\n\n".join(parts) + "\n\n"

    def _handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=body.encode("utf-8"),
            headers={"Content-Type": "text/event-stream"},
        )

    return _handler


def _build_client(handler: Callable, *, env_key: str = "ANTHROPIC_KEY") -> AnthropicClient:
    return AnthropicClient(
        base_url="http://test",
        model="claude-test",
        api_key_env_var=env_key,
        timeout_s=5,
        transport=httpx.MockTransport(handler),
    )


def _collect(client: AnthropicClient, *, tools=None) -> list[LlmStreamEvent]:
    async def _run() -> list[LlmStreamEvent]:
        out: list[LlmStreamEvent] = []
        async for ev in client.chat_stream(
            [{"role": "user", "content": "hi"}],
            tools=tools,
        ):
            out.append(ev)
        return out
    return asyncio.run(_run())


@pytest.fixture(autouse=True)
def _stamp_api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_KEY", "sk-ant-test")


# ------------------------------------------------------------------
# Happy path: text-only
# ------------------------------------------------------------------


def test_chat_stream_text_block_emits_deltas_then_usage_then_done():
    handler = _sse_events([
        ("message_start", {
            "type":    "message_start",
            "message": {"id": "msg_1", "role": "assistant", "content": [], "usage": {"input_tokens": 12, "output_tokens": 0}},
        }),
        ("content_block_start", {
            "type": "content_block_start", "index": 0,
            "content_block": {"type": "text", "text": ""},
        }),
        ("content_block_delta", {
            "type": "content_block_delta", "index": 0,
            "delta": {"type": "text_delta", "text": "Hello"},
        }),
        ("content_block_delta", {
            "type": "content_block_delta", "index": 0,
            "delta": {"type": "text_delta", "text": " world"},
        }),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("message_delta", {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn"},
            "usage": {"output_tokens": 5},
        }),
        ("message_stop", {"type": "message_stop"}),
    ])
    client = _build_client(handler)
    events = _collect(client)

    kinds = [e.kind for e in events]
    # 2 text deltas, then usage, then done.
    assert kinds == ["delta", "delta", "usage", "done"]
    assert events[0].delta == "Hello"
    assert events[1].delta == " world"
    assert events[2].usage == {
        "prompt_tokens":     12,
        "completion_tokens": 5,
        "total_tokens":      17,
    }
    final: ChatResponse = events[3].final
    assert final.content == "Hello world"
    assert final.tool_calls == []


# ------------------------------------------------------------------
# Tool use — input_json_delta assembly
# ------------------------------------------------------------------


def test_chat_stream_tool_use_buffers_input_json_then_emits_tool_call():
    """tool_use blocks emit their input as ``input_json_delta``
    fragments. The assembler concatenates the partial_json
    strings and only emits the tool_call once the block's
    stop event arrives."""
    handler = _sse_events([
        ("message_start", {
            "type":    "message_start",
            "message": {"id": "msg_1", "role": "assistant", "content": [], "usage": {"input_tokens": 30, "output_tokens": 0}},
        }),
        ("content_block_start", {
            "type": "content_block_start", "index": 0,
            "content_block": {"type": "tool_use", "id": "toolu_01", "name": "fs_read", "input": {}},
        }),
        ("content_block_delta", {
            "type": "content_block_delta", "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": '{"path":'},
        }),
        ("content_block_delta", {
            "type": "content_block_delta", "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": ' "/tmp/x"}'},
        }),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("message_delta", {
            "type":  "message_delta",
            "delta": {"stop_reason": "tool_use"},
            "usage": {"output_tokens": 14},
        }),
        ("message_stop", {"type": "message_stop"}),
    ])
    client = _build_client(handler)
    events = _collect(client, tools=[{"type": "function", "function": {"name": "fs_read", "parameters": {}}}])

    tc_events = [e for e in events if e.kind == "tool_call"]
    # Exactly one tool_call event, emitted on content_block_stop.
    assert len(tc_events) == 1
    tc = tc_events[0].tool_call
    assert isinstance(tc, ToolCall)
    assert tc.name == "fs_read"
    assert tc.arguments == {"path": "/tmp/x"}
    assert tc.id == "toolu_01"

    # The done event still fires after the tool_call.
    kinds_after_tool = [e.kind for e in events[events.index(tc_events[0]) + 1:]]
    assert "done" in kinds_after_tool


def test_chat_stream_text_then_tool_use_mixed():
    """A real Anthropic completion often emits a short text
    block (the rationale) before a tool_use block. Both must
    surface — text deltas first, then the tool_call when the
    tool-use block stops."""
    handler = _sse_events([
        ("message_start", {
            "type": "message_start",
            "message": {"id": "m", "role": "assistant", "content": [], "usage": {"input_tokens": 8, "output_tokens": 0}},
        }),
        ("content_block_start", {
            "type": "content_block_start", "index": 0,
            "content_block": {"type": "text", "text": ""},
        }),
        ("content_block_delta", {
            "type": "content_block_delta", "index": 0,
            "delta": {"type": "text_delta", "text": "I'll check that."},
        }),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("content_block_start", {
            "type": "content_block_start", "index": 1,
            "content_block": {"type": "tool_use", "id": "toolu_02", "name": "web_fetch", "input": {}},
        }),
        ("content_block_delta", {
            "type": "content_block_delta", "index": 1,
            "delta": {"type": "input_json_delta", "partial_json": '{"url":"https://e.x"}'},
        }),
        ("content_block_stop", {"type": "content_block_stop", "index": 1}),
        ("message_delta", {
            "type":  "message_delta",
            "delta": {"stop_reason": "tool_use"},
            "usage": {"output_tokens": 30},
        }),
        ("message_stop", {"type": "message_stop"}),
    ])
    client = _build_client(handler)
    events = _collect(client)

    kinds = [e.kind for e in events]
    # Expect: delta (text) → tool_call → usage → done
    assert kinds[0] == "delta"
    assert kinds[1] == "tool_call"
    assert kinds[2] == "usage"
    assert kinds[3] == "done"
    assert events[0].delta == "I'll check that."
    assert events[1].tool_call.name == "web_fetch"
    assert events[1].tool_call.arguments == {"url": "https://e.x"}


def test_chat_stream_tool_use_without_input_yields_empty_args():
    """A tool_use block whose stop event arrives without any
    input_json_delta produces a ToolCall with empty
    arguments (the spec allows this for zero-arg tools)."""
    handler = _sse_events([
        ("message_start", {
            "type": "message_start",
            "message": {"id": "m", "role": "assistant", "content": [], "usage": {"input_tokens": 4, "output_tokens": 0}},
        }),
        ("content_block_start", {
            "type": "content_block_start", "index": 0,
            "content_block": {"type": "tool_use", "id": "toolu_03", "name": "ping", "input": {}},
        }),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("message_stop", {"type": "message_stop"}),
    ])
    client = _build_client(handler)
    events = _collect(client)
    tc_events = [e for e in events if e.kind == "tool_call"]
    assert len(tc_events) == 1
    assert tc_events[0].tool_call.arguments == {}


def test_chat_stream_tool_use_with_invalid_json_yields_empty_args():
    """Defensive: if input_json_delta fragments concatenate
    to something that isn't valid JSON, the assembler falls
    back to {} rather than raise. The agent runtime can then
    decide to retry."""
    handler = _sse_events([
        ("message_start", {
            "type": "message_start",
            "message": {"id": "m", "role": "assistant", "content": [], "usage": {"input_tokens": 5, "output_tokens": 0}},
        }),
        ("content_block_start", {
            "type": "content_block_start", "index": 0,
            "content_block": {"type": "tool_use", "id": "toolu_04", "name": "tool_b", "input": {}},
        }),
        ("content_block_delta", {
            "type": "content_block_delta", "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": "{not valid"},
        }),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("message_stop", {"type": "message_stop"}),
    ])
    client = _build_client(handler)
    events = _collect(client)
    tc_events = [e for e in events if e.kind == "tool_call"]
    assert len(tc_events) == 1
    assert tc_events[0].tool_call.arguments == {}


# ------------------------------------------------------------------
# Error paths
# ------------------------------------------------------------------


def test_chat_stream_error_event_yields_kind_error_and_returns():
    """Anthropic emits an explicit ``error`` SSE event for
    overload / rate-limit issues. The stream surfaces the
    message and stops."""
    handler = _sse_events([
        ("message_start", {
            "type": "message_start",
            "message": {"id": "m", "role": "assistant", "content": [], "usage": {"input_tokens": 1, "output_tokens": 0}},
        }),
        ("error", {
            "type":  "error",
            "error": {"type": "overloaded_error", "message": "Overloaded"},
        }),
    ])
    client = _build_client(handler)
    events = _collect(client)
    # message_start may produce zero externally-visible
    # events (just primes internal state). The error event
    # then arrives.
    error_events = [e for e in events if e.kind == "error"]
    assert len(error_events) == 1
    assert "Overloaded" in error_events[0].error
    # No done after error.
    assert all(e.kind != "done" for e in events)


def test_chat_stream_http_5xx_yields_kind_error():
    def _handler(_req):
        return httpx.Response(529, content=b'{"error":{"message":"overloaded"}}')

    client = _build_client(_handler)
    events = _collect(client)
    assert len(events) == 1
    assert events[0].kind == "error"
    assert "529" in events[0].error


def test_chat_stream_missing_api_key_yields_kind_error(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_KEY", raising=False)
    client = AnthropicClient(
        base_url="http://test",
        model="claude-test",
        api_key_env_var="ANTHROPIC_KEY",
        transport=httpx.MockTransport(lambda r: httpx.Response(200)),
    )
    events = _collect(client)
    assert len(events) == 1
    assert events[0].kind == "error"
    assert "ANTHROPIC_KEY" in events[0].error


def test_chat_stream_never_raises_pin_contract():
    def _connect_error(req):
        raise httpx.ConnectError("nope", request=req)
    client = _build_client(_connect_error)
    events = _collect(client)
    assert all(e.kind in ("delta", "tool_call", "usage", "done", "error") for e in events)


# ------------------------------------------------------------------
# Sync sanity check
# ------------------------------------------------------------------


def test_chat_sync_still_returns_chatresponse():
    """The async addition must not regress the synchronous
    path."""
    payload = {
        "id":      "msg_1",
        "type":    "message",
        "role":    "assistant",
        "content": [
            {"type": "text",     "text": "hello"},
            {"type": "tool_use", "id": "toolu_99", "name": "do_thing", "input": {"k": 1}},
        ],
        "usage":   {"input_tokens": 12, "output_tokens": 4},
    }

    def _handler(_req):
        return httpx.Response(200, json=payload)

    client = _build_client(_handler)
    resp = client.chat([{"role": "user", "content": "hi"}])
    assert isinstance(resp, ChatResponse)
    assert resp.content == "hello"
    assert resp.tool_calls[0].name == "do_thing"
    assert resp.tool_calls[0].arguments == {"k": 1}
    assert resp.usage["total_tokens"] == 16
