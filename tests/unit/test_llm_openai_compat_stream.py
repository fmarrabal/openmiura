"""Tests for OpenAICompatibleClient.chat_stream (H1.2).

OpenAI's streaming Chat Completions wire format is SSE:
each line ``data: <json>`` (or ``data: [DONE]``). Tool
calls are emitted in pieces and must be reassembled per
``index``. We mock the wire with ``httpx.MockTransport`` so
the test never makes real network calls.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Callable

import httpx
import pytest

from openmiura.core.llm import LlmStreamEvent, OpenAICompatibleClient
from openmiura.core.llm.types import ChatResponse, ToolCall


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _sse(lines: list[dict[str, Any] | str]) -> Callable[[httpx.Request], httpx.Response]:
    """Build a MockTransport handler returning an OpenAI-style
    SSE response body. Items that are dicts are JSON-encoded
    behind ``data: ``; items that are strings are emitted
    verbatim as ``data: <string>``."""
    parts = []
    for item in lines:
        if isinstance(item, str):
            parts.append(f"data: {item}")
        else:
            parts.append(f"data: {json.dumps(item)}")
    body = "\n\n".join(parts) + "\n\n"

    def _handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=body.encode("utf-8"),
            headers={"Content-Type": "text/event-stream"},
        )

    return _handler


def _build_client(handler: Callable, *, env_key: str = "OPENAI_KEY") -> OpenAICompatibleClient:
    # The chat_stream method calls _api_key() inside the try
    # block so a missing key yields a clean error event.
    return OpenAICompatibleClient(
        base_url="http://test",
        model="gpt-test",
        api_key_env_var=env_key,
        timeout_s=5,
        transport=httpx.MockTransport(handler),
    )


def _collect(client: OpenAICompatibleClient, *, tools=None) -> list[LlmStreamEvent]:
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
    """Every test in this module sets the api key env so the
    chat_stream call doesn't bail with "Missing API key"."""
    monkeypatch.setenv("OPENAI_KEY", "sk-test")


# ------------------------------------------------------------------
# Happy path: content-only stream
# ------------------------------------------------------------------


def test_chat_stream_emits_content_deltas_in_order():
    handler = _sse([
        {"choices": [{"index": 0, "delta": {"role": "assistant", "content": "Hello"}, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {"content": " "}, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {"content": "world"}, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
        {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13}},
        "[DONE]",
    ])
    client = _build_client(handler)
    events = _collect(client)

    kinds = [e.kind for e in events]
    # 3 content deltas, then usage, then done.
    assert kinds == ["delta", "delta", "delta", "usage", "done"]
    assert events[0].delta == "Hello"
    assert events[1].delta == " "
    assert events[2].delta == "world"
    assert events[3].usage == {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13}
    final: ChatResponse = events[4].final
    assert final.content == "Hello world"
    assert final.usage["total_tokens"] == 13


def test_chat_stream_handles_sse_comment_lines_and_blanks():
    """OpenAI compatible providers sometimes emit ":" comment
    lines as heartbeats. They must be skipped silently."""
    raw_body = (
        ": keepalive\n\n"
        "data: " + json.dumps({"choices": [{"delta": {"content": "ok"}, "finish_reason": None}]}) + "\n\n"
        "data: " + json.dumps({"choices": [{"delta": {}, "finish_reason": "stop"}]}) + "\n\n"
        "data: [DONE]\n\n"
    )

    def _handler(_req):
        return httpx.Response(200, content=raw_body.encode("utf-8"),
                              headers={"Content-Type": "text/event-stream"})

    client = _build_client(_handler)
    events = _collect(client)
    kinds = [e.kind for e in events]
    # No usage (we didn't send a usage chunk), so: 1 delta + 1 done.
    assert kinds == ["delta", "done"]


# ------------------------------------------------------------------
# Tool calls — argument streaming + assembly
# ------------------------------------------------------------------


def test_chat_stream_assembles_streamed_tool_call_arguments():
    """OpenAI streams ``function.arguments`` as a JSON string
    one chunk at a time. The assembler must concatenate the
    pieces and emit ONE tool_call event with the parsed
    arguments."""
    handler = _sse([
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
    client = _build_client(handler)
    events = _collect(client, tools=[{"type": "function", "function": {"name": "fs_read", "parameters": {}}}])

    tc_events = [e for e in events if e.kind == "tool_call"]
    assert len(tc_events) == 1, f"expected 1 assembled tool_call, got {len(tc_events)}: {events}"
    tc = tc_events[0].tool_call
    assert isinstance(tc, ToolCall)
    assert tc.name == "fs_read"
    assert tc.arguments == {"path": "/tmp/x"}
    assert tc.id == "call_xyz"


def test_chat_stream_assembles_multiple_parallel_tool_calls():
    """A single message can contain multiple tool calls (each
    with its own ``index``). Assembler must keep slots
    separate and emit them in index order."""
    handler = _sse([
        # Two tool calls start in parallel.
        {"choices": [{"index": 0, "delta": {
            "tool_calls": [
                {"index": 0, "id": "c1", "function": {"name": "tool_a", "arguments": ""}},
                {"index": 1, "id": "c2", "function": {"name": "tool_b", "arguments": ""}},
            ]
        }, "finish_reason": None}]},
        # Stream args for index 0
        {"choices": [{"index": 0, "delta": {
            "tool_calls": [{"index": 0, "function": {"arguments": "{\"a\":1}"}}]
        }, "finish_reason": None}]},
        # Stream args for index 1
        {"choices": [{"index": 0, "delta": {
            "tool_calls": [{"index": 1, "function": {"arguments": "{\"b\":2}"}}]
        }, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
        "[DONE]",
    ])
    client = _build_client(handler)
    events = _collect(client)

    tc_events = [e for e in events if e.kind == "tool_call"]
    assert len(tc_events) == 2
    names = [e.tool_call.name for e in tc_events]
    assert names == ["tool_a", "tool_b"], "tool calls must emit in index order"
    assert tc_events[0].tool_call.arguments == {"a": 1}
    assert tc_events[1].tool_call.arguments == {"b": 2}


def test_chat_stream_accepts_full_dict_arguments_in_one_chunk():
    """Some OpenAI-compatible providers (e.g. older Kimi
    builds) send the complete arguments dict in a single
    chunk instead of streaming the JSON string. The
    assembler must accept both shapes."""
    handler = _sse([
        {"choices": [{"index": 0, "delta": {
            "tool_calls": [{
                "index":    0,
                "id":       "call_1",
                "function": {"name": "tool_x", "arguments": {"k": 1, "v": "x"}},
            }]
        }, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
        "[DONE]",
    ])
    client = _build_client(handler)
    events = _collect(client)
    tc_events = [e for e in events if e.kind == "tool_call"]
    assert len(tc_events) == 1
    assert tc_events[0].tool_call.arguments == {"k": 1, "v": "x"}


def test_chat_stream_flushes_tool_calls_even_without_finish_reason():
    """If the provider's stream ends with [DONE] but no
    explicit ``finish_reason`` for the tool block, we still
    flush whatever's in the assembler."""
    handler = _sse([
        {"choices": [{"index": 0, "delta": {
            "tool_calls": [{
                "index":    0,
                "id":       "call_q",
                "function": {"name": "quick", "arguments": "{}"},
            }]
        }, "finish_reason": None}]},
        # No finish_reason chunk — jump straight to [DONE].
        "[DONE]",
    ])
    client = _build_client(handler)
    events = _collect(client)
    tc_events = [e for e in events if e.kind == "tool_call"]
    assert len(tc_events) == 1
    assert tc_events[0].tool_call.name == "quick"


def test_chat_stream_skips_tool_call_with_missing_function_name():
    """Defensive: a tool_call delta with no function name is
    incomplete and must not emit a stray ToolCall event."""
    handler = _sse([
        {"choices": [{"index": 0, "delta": {
            "tool_calls": [{"index": 0, "function": {"arguments": "{}"}}]
        }, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
        "[DONE]",
    ])
    client = _build_client(handler)
    events = _collect(client)
    tc_events = [e for e in events if e.kind == "tool_call"]
    assert len(tc_events) == 0


# ------------------------------------------------------------------
# Error paths
# ------------------------------------------------------------------


def test_chat_stream_yields_error_event_on_http_5xx():
    def _handler(_req):
        return httpx.Response(503, content=b'{"error":{"message":"overloaded"}}')

    client = _build_client(_handler)
    events = _collect(client)
    assert len(events) == 1
    assert events[0].kind == "error"
    assert "503" in events[0].error
    assert "overloaded" in events[0].error


def test_chat_stream_yields_error_when_api_key_missing(monkeypatch):
    monkeypatch.delenv("OPENAI_KEY", raising=False)
    # The transport is never reached — error fires before
    # the HTTP call.
    client = OpenAICompatibleClient(
        base_url="http://test",
        model="gpt-test",
        api_key_env_var="OPENAI_KEY",
        transport=httpx.MockTransport(lambda r: httpx.Response(200)),
    )
    events = _collect(client)
    assert len(events) == 1
    assert events[0].kind == "error"
    assert "OPENAI_KEY" in events[0].error


def test_chat_stream_never_raises_pin_contract():
    def _connect_error(req):
        raise httpx.ConnectError("nope", request=req)

    client = _build_client(_connect_error)
    events = _collect(client)
    # Got an event, not an exception.
    assert all(e.kind in ("delta", "tool_call", "usage", "done", "error") for e in events)
    assert events[-1].kind == "error"


# ------------------------------------------------------------------
# Sync sanity check
# ------------------------------------------------------------------


def test_chat_sync_still_returns_chatresponse():
    """The async addition must not regress the synchronous
    path. Verify the same shape as before."""
    payload = {
        "choices": [{
            "index":   0,
            "message": {
                "role":    "assistant",
                "content": "hello",
                "tool_calls": [{
                    "id":       "c1",
                    "type":     "function",
                    "function": {"name": "do_thing", "arguments": '{"k":1}'},
                }],
            },
            "finish_reason": "tool_calls",
        }],
        "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
    }

    def _handler(_req):
        return httpx.Response(200, json=payload)

    client = _build_client(_handler)
    resp = client.chat([{"role": "user", "content": "hi"}])
    assert isinstance(resp, ChatResponse)
    assert resp.content == "hello"
    assert resp.tool_calls[0].name == "do_thing"
    assert resp.tool_calls[0].arguments == {"k": 1}
    assert resp.usage["total_tokens"] == 7
