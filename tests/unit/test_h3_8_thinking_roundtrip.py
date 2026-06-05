"""Tests for H3.8 — signed-thinking round-trip for tool use.

H3.4 surfaced extended-thinking blocks but documented a hard
limitation: with thinking enabled, a tool-calling turn could not
continue, because Anthropic requires the *signed* thinking block
to be echoed back in the assistant turn that precedes a
``tool_result`` — and the runtime reconstructed that turn without
it, so the follow-up request 400'd.

H3.8 lifts that:

  - the Anthropic client surfaces the signed ``thinking`` /
    ``redacted_thinking`` blocks on ``ChatResponse.thinking_blocks``
    (streaming + sync);
  - the agent runtime carries them on the assistant turn it
    appends before executing tools;
  - ``_convert_messages`` re-emits them verbatim (signature
    intact) ahead of the ``tool_use`` block.

The feature is opt-in: it only matters when thinking is enabled,
and is a no-op otherwise.

These tests pin the assembler extractor, the message conversion
ordering, the sync capture, and — the real proof — a two-round
streamed interaction whose SECOND request body carries the signed
thinking block back to the API.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator, Callable

import httpx
import pytest

from openmiura.core.agent_runtime import AgentRuntime
from openmiura.core.llm import AnthropicClient, LlmStreamEvent
from openmiura.core.llm.anthropic_client import _StreamingBlockAssembler


@pytest.fixture(autouse=True)
def _stamp_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_KEY", "sk-ant-test")


# ==================================================================
# assembler — thinking_blocks() extractor
# ==================================================================


def test_assembler_extracts_signed_and_redacted_blocks_in_order():
    asm = _StreamingBlockAssembler()
    asm.ingest_start(0, {"type": "thinking", "thinking": ""})
    asm.ingest_delta(0, {"type": "thinking_delta", "thinking": "step one"})
    asm.ingest_delta(0, {"type": "signature_delta", "signature": "SIG1"})
    asm.ingest_start(1, {"type": "redacted_thinking", "data": "ENC"})
    asm.ingest_start(2, {"type": "text", "text": ""})
    asm.ingest_delta(2, {"type": "text_delta", "text": "answer"})

    assert asm.thinking_blocks() == [
        {"type": "thinking", "thinking": "step one", "signature": "SIG1"},
        {"type": "redacted_thinking", "data": "ENC"},
    ]
    # The text block is the answer, not a thinking block.
    assert asm.text_accum() == "answer"


def test_assembler_drops_unsigned_thinking_block():
    asm = _StreamingBlockAssembler()
    asm.ingest_start(0, {"type": "thinking", "thinking": ""})
    asm.ingest_delta(0, {"type": "thinking_delta", "thinking": "no signature yet"})
    # No signature_delta arrived → cannot be round-tripped → dropped.
    assert asm.thinking_blocks() == []


# ==================================================================
# _convert_messages — thinking block precedes tool_use
# ==================================================================


def _client(**kw) -> AnthropicClient:
    return AnthropicClient(
        base_url="http://test", model="claude-3-5-sonnet",
        api_key_env_var="ANTHROPIC_KEY", **kw,
    )


def test_convert_messages_prepends_thinking_before_tool_use():
    client = _client()
    _system, msgs = client._convert_messages([
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": "let me look",
            "tool_calls": [{"id": "t1", "function": {"name": "lookup", "arguments": "{}"}}],
            "_thinking_blocks": [{"type": "thinking", "thinking": "hmm", "signature": "S1"}],
        },
        {"role": "tool", "name": "lookup", "content": "42"},
    ])
    assistant = next(m for m in msgs if m["role"] == "assistant")
    content = assistant["content"]
    types_ = [b["type"] for b in content]
    # thinking first, signature intact, then text, then tool_use.
    assert types_[0] == "thinking"
    assert content[0]["signature"] == "S1"
    assert "tool_use" in types_
    assert types_.index("thinking") < types_.index("tool_use")


def test_convert_messages_without_thinking_blocks_unchanged():
    client = _client()
    _system, msgs = client._convert_messages([
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "t1", "function": {"name": "lookup", "arguments": "{}"}}],
        },
    ])
    content = msgs[0]["content"]
    assert [b["type"] for b in content] == ["tool_use"]


# ==================================================================
# sync chat() — surfaces thinking_blocks
# ==================================================================


def test_sync_chat_surfaces_thinking_blocks():
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "content": [
                {"type": "thinking", "thinking": "reasoning", "signature": "SIGX"},
                {"type": "tool_use", "id": "tu1", "name": "lookup", "input": {"q": "x"}},
            ],
            "usage": {"input_tokens": 5, "output_tokens": 3},
        })
    client = _client(transport=httpx.MockTransport(handler))
    resp = client.chat([{"role": "user", "content": "hi"}])
    assert resp.thinking_blocks is not None
    assert resp.thinking_blocks[0]["type"] == "thinking"
    assert resp.thinking_blocks[0]["signature"] == "SIGX"
    assert len(resp.tool_calls) == 1 and resp.tool_calls[0].name == "lookup"
    # Thinking/tool_use only → no answer text leaks into content.
    assert resp.content == ""


# ==================================================================
# Two-round integration — signed block returns in request #2
# ==================================================================


def _anthropic_sse(events: list[tuple[str, dict[str, Any]]]) -> str:
    parts = [f"event: {name}\ndata: {json.dumps(payload)}" for name, payload in events]
    return "\n\n".join(parts) + "\n\n"


_ROUND1 = _anthropic_sse([
    ("message_start", {"type": "message_start", "message": {
        "id": "m1", "role": "assistant", "content": [],
        "usage": {"input_tokens": 20, "output_tokens": 0}}}),
    ("content_block_start", {"type": "content_block_start", "index": 0,
        "content_block": {"type": "thinking", "thinking": ""}}),
    ("content_block_delta", {"type": "content_block_delta", "index": 0,
        "delta": {"type": "thinking_delta", "thinking": "Let me think about it."}}),
    ("content_block_delta", {"type": "content_block_delta", "index": 0,
        "delta": {"type": "signature_delta", "signature": "SIG_ABC"}}),
    ("content_block_stop", {"type": "content_block_stop", "index": 0}),
    ("content_block_start", {"type": "content_block_start", "index": 1,
        "content_block": {"type": "tool_use", "id": "toolu_1", "name": "lookup", "input": {}}}),
    ("content_block_delta", {"type": "content_block_delta", "index": 1,
        "delta": {"type": "input_json_delta", "partial_json": '{"q":"x"}'}}),
    ("content_block_stop", {"type": "content_block_stop", "index": 1}),
    ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "tool_use"},
        "usage": {"output_tokens": 15}}),
    ("message_stop", {"type": "message_stop"}),
])

_ROUND2 = _anthropic_sse([
    ("message_start", {"type": "message_start", "message": {
        "id": "m2", "role": "assistant", "content": [],
        "usage": {"input_tokens": 30, "output_tokens": 0}}}),
    ("content_block_start", {"type": "content_block_start", "index": 0,
        "content_block": {"type": "thinking", "thinking": ""}}),
    ("content_block_delta", {"type": "content_block_delta", "index": 0,
        "delta": {"type": "thinking_delta", "thinking": "Now I know."}}),
    ("content_block_delta", {"type": "content_block_delta", "index": 0,
        "delta": {"type": "signature_delta", "signature": "SIG_DEF"}}),
    ("content_block_stop", {"type": "content_block_stop", "index": 0}),
    ("content_block_start", {"type": "content_block_start", "index": 1,
        "content_block": {"type": "text", "text": ""}}),
    ("content_block_delta", {"type": "content_block_delta", "index": 1,
        "delta": {"type": "text_delta", "text": "The answer is 42."}}),
    ("content_block_stop", {"type": "content_block_stop", "index": 1}),
    ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn"},
        "usage": {"output_tokens": 10}}),
    ("message_stop", {"type": "message_stop"}),
])


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
        provider = "anthropic"
        model = "claude-3-5-sonnet"
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


def test_signed_thinking_block_roundtrips_into_second_request():
    """End-to-end: round 1 streams a signed thinking block + a
    tool_use; the runtime runs the tool and re-opens the stream;
    round 2's request body must echo that thinking block — with
    its signature — ahead of the tool_use in the assistant turn."""
    requests_seen: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        requests_seen.append(json.loads(req.content))
        body = _ROUND1 if len(requests_seen) == 1 else _ROUND2
        return httpx.Response(200, content=body.encode("utf-8"),
                              headers={"Content-Type": "text/event-stream"})

    client = AnthropicClient(
        base_url="http://test", model="claude-3-5-sonnet",
        api_key_env_var="ANTHROPIC_KEY",
        max_output_tokens=4096, thinking_budget_tokens=1024, timeout_s=5,
        transport=httpx.MockTransport(handler),
    )
    rt = _make_runtime(client)
    events = _collect_runtime(rt, tools_runtime=_FakeToolsRuntime({"lookup": "42"}), user_key="u1")

    # Two requests: the initial round + the post-tool continuation.
    assert len(requests_seen) == 2
    # Round 1 actually asked for extended thinking.
    assert requests_seen[0].get("thinking") == {"type": "enabled", "budget_tokens": 1024}

    # Round 2's assistant turn echoes the signed thinking block
    # ahead of the tool_use it justified.
    msgs = requests_seen[1]["messages"]
    assistant = [m for m in msgs if m.get("role") == "assistant" and isinstance(m.get("content"), list)]
    assert assistant, "round 2 must carry an assistant turn with block content"
    content = assistant[-1]["content"]
    types_ = [b.get("type") for b in content if isinstance(b, dict)]
    assert "thinking" in types_ and "tool_use" in types_
    assert types_.index("thinking") < types_.index("tool_use")

    tb = next(b for b in content if b.get("type") == "thinking")
    assert tb["signature"] == "SIG_ABC"
    assert tb["thinking"] == "Let me think about it."

    # The interaction completed: tool ran, final answer produced.
    assert any(e.kind == "tool_result" for e in events)
    assert events[-1].kind == "done"
    assert "answer is 42" in (events[-1].final.content or "")
