"""Truthful LLM logging (#10).

Two data-integrity gaps in the Anthropic path:

  1. ``stop_reason`` was dropped — a response truncated at ``max_tokens``
     or a ``refusal`` was logged indistinguishably from a complete
     answer. It is now surfaced on ``ChatResponse.stop_reason`` (sync and
     streaming) and recorded in the decision trace.

  2. Tool-call arguments that didn't parse to a JSON object were silently
     replaced with ``{}`` and the tool executed anyway — so a run with
     dropped arguments was logged as a normal success. Such a call now
     carries ``ToolCall.arguments_error`` and the runtime returns an error
     tool_result instead of executing it.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from openmiura.core.agent_runtime import AgentRuntime
from openmiura.core.llm import AnthropicClient, LlmStreamEvent
from openmiura.core.llm.anthropic_client import _StreamingBlockAssembler


@pytest.fixture(autouse=True)
def _stamp_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_KEY", "sk-ant-test")


def _client(handler) -> AnthropicClient:
    return AnthropicClient(
        base_url="http://test", model="claude-3-5-sonnet",
        api_key_env_var="ANTHROPIC_KEY", transport=httpx.MockTransport(handler),
    )


# ============================ stop_reason ============================


def test_sync_chat_surfaces_stop_reason():
    def handler(_req):
        return httpx.Response(200, json={
            "content": [{"type": "text", "text": "partial..."}],
            "stop_reason": "max_tokens",
            "usage": {"input_tokens": 5, "output_tokens": 2},
        })
    resp = _client(handler).chat([{"role": "user", "content": "hi"}])
    assert resp.stop_reason == "max_tokens"


def test_sync_chat_stop_reason_none_when_absent():
    def handler(_req):
        return httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}], "usage": {"input_tokens": 1, "output_tokens": 1}})
    resp = _client(handler).chat([{"role": "user", "content": "hi"}])
    assert resp.stop_reason is None


# ===================== malformed tool arguments =====================


def test_assembler_flags_unparseable_tool_args():
    asm = _StreamingBlockAssembler()
    asm.ingest_start(0, {"type": "tool_use", "id": "t1", "name": "lookup", "input": {}})
    asm.ingest_delta(0, {"type": "input_json_delta", "partial_json": '{"q": "x'})  # truncated JSON
    tc = asm.finalise_block(0)
    assert tc is not None
    assert tc.arguments == {}
    assert tc.arguments_error and "not valid JSON" in tc.arguments_error


def test_assembler_flags_non_object_tool_args():
    asm = _StreamingBlockAssembler()
    asm.ingest_start(0, {"type": "tool_use", "id": "t1", "name": "lookup", "input": {}})
    asm.ingest_delta(0, {"type": "input_json_delta", "partial_json": '"just a string"'})
    tc = asm.finalise_block(0)
    assert tc.arguments == {}
    assert tc.arguments_error and "not a JSON object" in tc.arguments_error


def test_assembler_valid_object_has_no_error():
    asm = _StreamingBlockAssembler()
    asm.ingest_start(0, {"type": "tool_use", "id": "t1", "name": "lookup", "input": {}})
    asm.ingest_delta(0, {"type": "input_json_delta", "partial_json": '{"q":"x"}'})
    tc = asm.finalise_block(0)
    assert tc.arguments == {"q": "x"}
    assert tc.arguments_error is None


# ============== runtime: malformed args are not executed =============


class _FakeAudit:
    def get_recent_messages(self, *, session_id, limit):
        return []


class _FakeSettings:
    class _Runtime:
        history_limit = 0
    class _LLM:
        provider = "anthropic"
        model = "claude-3-5-sonnet"
    runtime = _Runtime()
    llm = _LLM()
    agents: dict[str, Any] = {}


class _ExplodingToolsRuntime:
    """run_tool must never be called for a malformed-args tool call."""
    def __init__(self):
        self.calls = 0

    def available_tool_schemas(self, agent_id, *, user_key=None, **_kw):
        return [{"type": "function", "function": {"name": "lookup", "parameters": {}}}]

    def run_tool(self, **_kw):
        self.calls += 1
        return "should-not-run"


def _make_runtime(llm) -> AgentRuntime:
    rt = AgentRuntime.__new__(AgentRuntime)
    rt.llm = llm
    rt.audit = _FakeAudit()
    rt.settings = _FakeSettings()
    rt.skill_loader = None
    rt.skills_path = ""
    return rt


def _sse(events: list[tuple[str, dict]]) -> str:
    return "\n\n".join(f"event: {n}\ndata: {json.dumps(p)}" for n, p in events) + "\n\n"


# Round 1: a tool_use whose argument JSON is truncated → unparseable.
_ROUND1_BAD_ARGS = _sse([
    ("message_start", {"type": "message_start", "message": {"id": "m1", "role": "assistant", "content": [], "usage": {"input_tokens": 10, "output_tokens": 0}}}),
    ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "tool_use", "id": "toolu_1", "name": "lookup", "input": {}}}),
    ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": '{"q": "x'}}),
    ("content_block_stop", {"type": "content_block_stop", "index": 0}),
    ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 5}}),
    ("message_stop", {"type": "message_stop"}),
])
# Round 2: plain final answer (the model "recovers").
_ROUND2_FINAL = _sse([
    ("message_start", {"type": "message_start", "message": {"id": "m2", "role": "assistant", "content": [], "usage": {"input_tokens": 12, "output_tokens": 0}}}),
    ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
    ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Could not call the tool."}}),
    ("content_block_stop", {"type": "content_block_stop", "index": 0}),
    ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 6}}),
    ("message_stop", {"type": "message_stop"}),
])


def test_runtime_does_not_execute_tool_with_malformed_args():
    seen: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(json.loads(req.content))
        body = _ROUND1_BAD_ARGS if len(seen) == 1 else _ROUND2_FINAL
        return httpx.Response(200, content=body.encode("utf-8"), headers={"Content-Type": "text/event-stream"})

    client = AnthropicClient(base_url="http://test", model="claude-3-5-sonnet", api_key_env_var="ANTHROPIC_KEY", transport=httpx.MockTransport(handler))
    rt = _make_runtime(client)
    tools = _ExplodingToolsRuntime()

    async def _run():
        return [ev async for ev in rt.generate_reply_stream(
            agent_id="default", session_id="s1", user_text="hi",
            tools_runtime=tools, user_key="u1")]
    events = asyncio.run(_run())

    # The tool was NEVER executed with dropped args.
    assert tools.calls == 0
    # An error tool_result was surfaced instead.
    tool_results = [e for e in events if e.kind == "tool_result"]
    assert tool_results, "expected a tool_result event"
    assert any(tr.tool_result.error == "tool_arguments_invalid" for tr in tool_results)
    # The interaction still completed with the recovery answer.
    assert events[-1].kind == "done"
    assert "Could not call the tool" in (events[-1].final.content or "")


def test_runtime_records_stop_reason_in_trace():
    def handler(_req):
        return httpx.Response(200, content=_ROUND2_FINAL.encode("utf-8"), headers={"Content-Type": "text/event-stream"})
    client = AnthropicClient(base_url="http://test", model="claude-3-5-sonnet", api_key_env_var="ANTHROPIC_KEY", transport=httpx.MockTransport(handler))
    rt = _make_runtime(client)
    trace: dict[str, Any] = {}

    async def _run():
        return [ev async for ev in rt.generate_reply_stream(
            agent_id="default", session_id="s1", user_text="hi", trace_collector=trace)]
    asyncio.run(_run())
    assert trace["decisions"]["stop_reason"] == "end_turn"
    assert trace["decisions"]["response_truncated"] is False
    assert trace["decisions"]["response_refused"] is False
