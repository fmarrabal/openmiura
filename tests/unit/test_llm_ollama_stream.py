"""Tests for OllamaClient.chat_stream (H1.1).

The Ollama wire format for ``/api/chat`` with ``stream=true``
is newline-delimited JSON. We mock the wire with
``httpx.MockTransport`` so the test never makes real
network calls. The transport handler returns a Response
whose body is the joined JSON-line stream.

Each test runs the async generator via ``asyncio.run`` so we
don't introduce a pytest-asyncio dependency.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Callable

import httpx
import pytest

from openmiura.core.llm import LlmStreamEvent, OllamaClient
from openmiura.core.llm.types import ChatResponse, ToolCall


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _lines_response(lines: list[dict[str, Any]], status: int = 200) -> Callable[[httpx.Request], httpx.Response]:
    """Build a MockTransport handler that returns the given
    JSON objects as a newline-delimited stream."""
    body = "\n".join(json.dumps(line) for line in lines) + "\n"

    def _handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=body.encode("utf-8"))

    return _handler


def _error_response(status: int, message: str) -> Callable[[httpx.Request], httpx.Response]:
    def _handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=message.encode("utf-8"))
    return _handler


def _connect_error(_request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection refused", request=_request)


def _collect(client: OllamaClient, **kwargs) -> list[LlmStreamEvent]:
    async def _run() -> list[LlmStreamEvent]:
        out: list[LlmStreamEvent] = []
        async for ev in client.chat_stream([{"role": "user", "content": "hi"}], **kwargs):
            out.append(ev)
        return out
    return asyncio.run(_run())


# ------------------------------------------------------------------
# Happy path: text-only stream
# ------------------------------------------------------------------


def test_chat_stream_yields_deltas_then_done_with_usage():
    handler = _lines_response([
        {"message": {"role": "assistant", "content": "Hello"}, "done": False},
        {"message": {"role": "assistant", "content": " "}, "done": False},
        {"message": {"role": "assistant", "content": "world"}, "done": False},
        {
            "message": {"role": "assistant", "content": ""},
            "done": True,
            "prompt_eval_count": 12,
            "eval_count":        3,
        },
    ])
    client = OllamaClient(
        base_url="http://test",
        model="qwen-test",
        timeout_s=5,
        transport=httpx.MockTransport(handler),
    )
    events = _collect(client)

    kinds = [e.kind for e in events]
    # 3 deltas, then usage, then done.
    assert kinds == ["delta", "delta", "delta", "usage", "done"]
    assert events[0].delta == "Hello"
    assert events[1].delta == " "
    assert events[2].delta == "world"
    # Token-usage layout matches the legacy field fallback.
    assert events[3].usage == {
        "prompt_tokens":     12,
        "completion_tokens": 3,
        "total_tokens":      15,
    }
    # Final ChatResponse has the concatenated text.
    final: ChatResponse = events[4].final
    assert final.content == "Hello world"
    assert final.tool_calls == []
    assert final.usage["total_tokens"] == 15


def test_chat_stream_skips_empty_and_corrupt_lines():
    """A real Ollama stream sometimes has trailing whitespace
    or partial flushes that aren't valid JSON. The stream
    must keep going — we only abort on done/error."""
    handler = _lines_response([
        {"message": {"role": "assistant", "content": "ok"}, "done": False},
    ])
    # Splice in a corrupt line before the valid one.

    body = "\n\n{not valid json\n" + json.dumps({"message": {"content": "ok"}, "done": False}) + "\n" + \
           json.dumps({"message": {"content": ""}, "done": True}) + "\n"

    def _custom_handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body.encode("utf-8"))

    client = OllamaClient(
        base_url="http://test",
        model="qwen-test",
        transport=httpx.MockTransport(_custom_handler),
    )
    events = _collect(client)
    kinds = [e.kind for e in events]
    # Exactly one delta (the corrupt line was skipped) then done.
    assert kinds == ["delta", "done"]
    assert events[0].delta == "ok"


# ------------------------------------------------------------------
# Tool calls
# ------------------------------------------------------------------


def test_chat_stream_emits_tool_call_event_then_done():
    """Ollama emits tool_calls on the final message (no
    incremental argument streaming) — assert that the
    tool_call event fires AND the final ChatResponse
    aggregates the same tool call."""
    handler = _lines_response([
        {"message": {"role": "assistant", "content": ""}, "done": False},
        {
            "message": {
                "role":    "assistant",
                "content": "",
                "tool_calls": [{
                    "function": {
                        "name":      "fs_read",
                        "arguments": {"path": "/tmp/foo"},
                    },
                    "id": "call_001",
                }],
            },
            "done":              True,
            "prompt_eval_count": 5,
            "eval_count":        0,
        },
    ])
    client = OllamaClient(
        base_url="http://test",
        model="qwen-test",
        transport=httpx.MockTransport(handler),
    )
    events = _collect(client)
    kinds = [e.kind for e in events]
    # Sequence: usage, then tool_call (in the loop ordering),
    # then done. We assert presence + final aggregation
    # rather than exact ordering because tool_call comes from
    # the same message as done.
    assert "tool_call" in kinds
    assert kinds[-1] == "done"

    tc_events = [e for e in events if e.kind == "tool_call"]
    assert len(tc_events) == 1
    tc = tc_events[0].tool_call
    assert isinstance(tc, ToolCall)
    assert tc.name == "fs_read"
    assert tc.arguments == {"path": "/tmp/foo"}
    assert tc.id == "call_001"

    final = events[-1].final
    assert len(final.tool_calls) == 1
    assert final.tool_calls[0].name == "fs_read"


def test_chat_stream_parses_string_encoded_tool_call_arguments():
    """Some Ollama builds emit ``arguments`` as a JSON-encoded
    string rather than a dict. The parser must accept both."""
    handler = _lines_response([
        {
            "message": {
                "role":    "assistant",
                "content": "",
                "tool_calls": [{
                    "function": {
                        "name":      "web_fetch",
                        "arguments": '{"url": "https://example.com"}',
                    },
                }],
            },
            "done": True,
        },
    ])
    client = OllamaClient(
        base_url="http://test",
        model="qwen-test",
        transport=httpx.MockTransport(handler),
    )
    events = _collect(client)
    tc_events = [e for e in events if e.kind == "tool_call"]
    assert len(tc_events) == 1
    assert tc_events[0].tool_call.arguments == {"url": "https://example.com"}


def test_chat_stream_skips_malformed_tool_calls():
    """A tool_call entry missing a function name must be
    skipped silently — better that than yielding a
    half-formed ToolCall and confusing the agent runtime."""
    handler = _lines_response([
        {
            "message": {
                "role":    "assistant",
                "content": "",
                "tool_calls": [
                    {"function": {}},                          # missing name
                    {"function": {"name": "ok", "arguments": {}}},
                ],
            },
            "done": True,
        },
    ])
    client = OllamaClient(
        base_url="http://test",
        model="qwen-test",
        transport=httpx.MockTransport(handler),
    )
    events = _collect(client)
    tc_events = [e for e in events if e.kind == "tool_call"]
    assert len(tc_events) == 1
    assert tc_events[0].tool_call.name == "ok"


# ------------------------------------------------------------------
# Error paths
# ------------------------------------------------------------------


def test_chat_stream_yields_error_event_on_http_5xx():
    client = OllamaClient(
        base_url="http://test",
        model="qwen-test",
        transport=httpx.MockTransport(_error_response(503, "service unavailable")),
    )
    events = _collect(client)
    assert len(events) == 1
    assert events[0].kind == "error"
    assert "503" in events[0].error
    assert "service unavailable" in events[0].error


def test_chat_stream_yields_error_event_on_connect_failure():
    client = OllamaClient(
        base_url="http://test",
        model="qwen-test",
        transport=httpx.MockTransport(_connect_error),
    )
    events = _collect(client)
    assert len(events) == 1
    assert events[0].kind == "error"
    assert "Cannot connect to Ollama" in events[0].error


def test_chat_stream_never_raises_exposes_only_canonical_events():
    """The agent runtime relies on chat_stream never raising
    — any error must be a ``kind="error"`` event. This test
    pins that contract by exercising the connect-error path
    and asserting we got an event, not an exception."""
    client = OllamaClient(
        base_url="http://test",
        model="qwen-test",
        transport=httpx.MockTransport(_connect_error),
    )
    # If chat_stream raised, _collect would propagate.
    events = _collect(client)
    assert all(e.kind in ("delta", "tool_call", "usage", "done", "error") for e in events)


# ------------------------------------------------------------------
# Sync sanity check — chat(...) still works post-refactor
# ------------------------------------------------------------------


def test_chat_sync_still_returns_chatresponse():
    """The chat_stream addition must not regress the
    synchronous path. We post a single JSON blob (the legacy
    non-streamed shape) and verify the same return shape as
    before the refactor."""
    payload = {
        "message": {
            "role":    "assistant",
            "content": "hello",
            "tool_calls": [{
                "function": {"name": "tool_a", "arguments": {"k": 1}},
            }],
        },
        "prompt_eval_count": 3,
        "eval_count":        2,
    }

    def _handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    client = OllamaClient(
        base_url="http://test",
        model="qwen-test",
        transport=httpx.MockTransport(_handler),
    )
    resp = client.chat([{"role": "user", "content": "hi"}])
    assert isinstance(resp, ChatResponse)
    assert resp.content == "hello"
    assert resp.tool_calls[0].name == "tool_a"
    assert resp.usage["total_tokens"] == 5


# ------------------------------------------------------------------
# Stream-event helpers — pinned because the SSE emitter
# downstream reads these fields verbatim.
# ------------------------------------------------------------------


def test_llm_stream_event_helpers_set_kind_and_field():
    delta_ev = LlmStreamEvent.make_delta("abc")
    assert delta_ev.kind == "delta"
    assert delta_ev.delta == "abc"
    assert delta_ev.tool_call is None

    tc = ToolCall(name="t", arguments={})
    tc_ev = LlmStreamEvent.make_tool_call(tc)
    assert tc_ev.kind == "tool_call"
    assert tc_ev.tool_call is tc

    usage_ev = LlmStreamEvent.make_usage({"total_tokens": 7})
    assert usage_ev.kind == "usage"
    assert usage_ev.usage["total_tokens"] == 7

    final = ChatResponse(content="x", tool_calls=[])
    done_ev = LlmStreamEvent.make_done(final)
    assert done_ev.kind == "done"
    assert done_ev.final is final

    err_ev = LlmStreamEvent.make_error("boom")
    assert err_ev.kind == "error"
    assert err_ev.error == "boom"
