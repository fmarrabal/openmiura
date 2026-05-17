"""Tests for AgentRuntime.generate_reply_stream (H1.4).

The runtime sits between the LLM clients (H1.1/1.2/1.3) and
the HTTP SSE endpoint (H1.5). It forwards LLM stream events
to the consumer AND runs any tools the LLM requests between
rounds, emitting ``tool_result`` events so the UI can show
progress.

These tests use a hand-rolled ``_FakeStreamingLLM`` whose
``chat_stream`` yields a scripted event sequence per call.
That keeps the test focus on the runtime's loop logic
without depending on the real LLM clients.
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

import pytest

from openmiura.core.agent_runtime import AgentRuntime
from openmiura.core.llm.types import (
    ChatResponse,
    LlmStreamEvent,
    ToolCall,
)


# ------------------------------------------------------------------
# Fake LLM that scripts per-round event sequences
# ------------------------------------------------------------------


class _FakeStreamingLLM:
    """Substitute for an LLM client during testing.

    ``rounds`` is a list of event lists; each element is the
    full event sequence that ``chat_stream`` will yield for
    one call. Each call advances to the next list (i.e.
    successive calls drive successive tool-loop iterations).
    """

    def __init__(self, rounds: list[list[LlmStreamEvent]], *, model: str = 'fake-model'):
        self._rounds = list(rounds)
        self.model = model
        self.calls: list[dict[str, Any]] = []

    def chat_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[LlmStreamEvent]:
        # Capture the call for later assertions.
        self.calls.append({'messages': list(messages), 'tools': tools})
        if not self._rounds:
            raise RuntimeError("FakeStreamingLLM ran out of scripted rounds")
        events = self._rounds.pop(0)

        async def _gen() -> AsyncIterator[LlmStreamEvent]:
            for ev in events:
                yield ev
        return _gen()


class _FakeToolsRuntime:
    """Substitute for the tools runtime.

    ``outputs`` is a dict mapping tool_name → callable
    (args -> output) or → str. Anything not in the dict
    raises a RuntimeError so we can test the error path.
    """

    def __init__(self, outputs: dict[str, Any]):
        self.outputs = outputs
        self.calls: list[dict[str, Any]] = []

    def available_tool_schemas(self, agent_id, *, user_key=None, **_kwargs):
        return [
            {'type': 'function', 'function': {'name': name, 'parameters': {}}}
            for name in self.outputs.keys()
        ]

    def run_tool(self, *, agent_id, session_id, user_key, tool_name, args, **_kwargs):
        self.calls.append({'tool': tool_name, 'args': args})
        if tool_name not in self.outputs:
            raise RuntimeError(f'unknown tool: {tool_name}')
        handler = self.outputs[tool_name]
        if callable(handler):
            return handler(args)
        return str(handler)


def _make_runtime(llm: _FakeStreamingLLM) -> AgentRuntime:
    """Build an AgentRuntime with the fake LLM, bypassing
    the normal __init__ that builds an LLM from settings."""
    rt = AgentRuntime.__new__(AgentRuntime)
    rt.llm = llm
    rt.audit = _FakeAudit()
    rt.settings = _FakeSettings()
    rt.skill_loader = None
    rt.skills_path = ''
    return rt


class _FakeAudit:
    def get_recent_messages(self, *, session_id, limit):
        return []


class _FakeSettings:
    class _Runtime:
        history_limit = 0
    class _LLM:
        provider = 'fake'
        model = 'fake-model'
    runtime = _Runtime()
    llm = _LLM()
    agents = {}


def _collect(rt: AgentRuntime, **kwargs) -> list[LlmStreamEvent]:
    async def _run() -> list[LlmStreamEvent]:
        out: list[LlmStreamEvent] = []
        async for ev in rt.generate_reply_stream(
            agent_id='default',
            session_id='sess_test',
            user_text='hello',
            **kwargs,
        ):
            out.append(ev)
        return out
    return asyncio.run(_run())


# ------------------------------------------------------------------
# Capability gate
# ------------------------------------------------------------------


def test_supports_streaming_true_when_llm_has_chat_stream():
    rt = _make_runtime(_FakeStreamingLLM([[]]))
    assert rt.supports_streaming() is True


def test_supports_streaming_false_when_llm_has_no_chat_stream():
    class _SyncOnly:
        model = 'sync'
        def chat(self, *_a, **_k): ...
    rt = AgentRuntime.__new__(AgentRuntime)
    rt.llm = _SyncOnly()
    assert rt.supports_streaming() is False


def test_generate_reply_stream_raises_when_no_chat_stream():
    class _SyncOnly:
        model = 'sync'
        def chat(self, *_a, **_k): ...
    rt = AgentRuntime.__new__(AgentRuntime)
    rt.llm = _SyncOnly()
    rt.audit = _FakeAudit()
    rt.settings = _FakeSettings()
    rt.skill_loader = None
    with pytest.raises(RuntimeError, match='does not support chat_stream'):
        # Have to drive the generator to trigger the body.
        async def _run():
            async for _ in rt.generate_reply_stream(
                agent_id='default',
                session_id='s',
                user_text='hi',
            ):
                pass
        asyncio.run(_run())


# ------------------------------------------------------------------
# Single-round (no tool calls) — purely forwards LLM deltas
# ------------------------------------------------------------------


def test_single_round_forwards_deltas_and_emits_done():
    final = ChatResponse(content='Hello world', tool_calls=[], usage={'prompt_tokens': 10, 'completion_tokens': 2, 'total_tokens': 12})
    llm = _FakeStreamingLLM([[
        LlmStreamEvent.make_delta('Hello '),
        LlmStreamEvent.make_delta('world'),
        LlmStreamEvent.make_usage({'prompt_tokens': 10, 'completion_tokens': 2, 'total_tokens': 12}),
        LlmStreamEvent.make_done(final),
    ]])
    rt = _make_runtime(llm)
    events = _collect(rt)

    kinds = [e.kind for e in events]
    # 2 deltas forwarded, then consolidated usage + done.
    assert kinds == ['delta', 'delta', 'usage', 'done']
    assert events[0].delta == 'Hello '
    assert events[1].delta == 'world'
    assert events[2].usage == {'prompt_tokens': 10, 'completion_tokens': 2, 'total_tokens': 12}
    assert events[3].final.content == 'Hello world'


def test_single_round_no_usage_omits_usage_event():
    llm = _FakeStreamingLLM([[
        LlmStreamEvent.make_delta('ok'),
        LlmStreamEvent.make_done(ChatResponse(content='ok', tool_calls=[], usage=None)),
    ]])
    rt = _make_runtime(llm)
    events = _collect(rt)
    kinds = [e.kind for e in events]
    # No intermediate usage event from the LLM and no
    # accumulated tokens → runtime skips the usage event.
    assert kinds == ['delta', 'done']


# ------------------------------------------------------------------
# Tool-call loop
# ------------------------------------------------------------------


def test_tool_call_loop_executes_tool_and_resumes_streaming():
    """Round 1: LLM thinks aloud + emits a tool_call.
       Round 2: LLM continues with the tool result, finishes
       with regular content."""
    final = ChatResponse(content='I checked and the answer is 42.', tool_calls=[], usage=None)
    llm = _FakeStreamingLLM([
        [
            LlmStreamEvent.make_delta("I'll check that."),
            LlmStreamEvent.make_tool_call(ToolCall(name='lookup', arguments={'q': 'meaning'}, id='c1')),
            LlmStreamEvent.make_done(ChatResponse(content="I'll check that.", tool_calls=[ToolCall(name='lookup', arguments={'q': 'meaning'}, id='c1')], usage=None)),
        ],
        [
            LlmStreamEvent.make_delta(' Answer: 42.'),
            LlmStreamEvent.make_done(final),
        ],
    ])
    tools = _FakeToolsRuntime({'lookup': lambda args: f'result for {args.get("q")}'})
    rt = _make_runtime(llm)
    events = _collect(rt, tools_runtime=tools, user_key='u1')

    kinds = [e.kind for e in events]
    # delta → tool_call → tool_result → delta → done
    assert kinds == ['delta', 'tool_call', 'tool_result', 'delta', 'done']

    assert events[0].delta == "I'll check that."
    assert events[1].tool_call.name == 'lookup'
    assert events[2].tool_result.name == 'lookup'
    assert events[2].tool_result.output == 'result for meaning'
    assert events[2].tool_result.call_id == 'c1'
    assert events[2].tool_result.error is None
    assert events[3].delta == ' Answer: 42.'
    # The final ChatResponse is the *concatenated* content
    # across all rounds (the user sees the full transcript).
    assert events[4].final.content == "I'll check that. Answer: 42."

    # The tool ran once with the right args.
    assert tools.calls == [{'tool': 'lookup', 'args': {'q': 'meaning'}}]


def test_tool_failure_emits_tool_result_with_error_and_continues():
    """A tool that raises must NOT abort the stream. The
    runtime emits the error inside the tool_result event and
    sends a failure message to the LLM in the next round."""
    final = ChatResponse(content='sorry, that tool is broken', tool_calls=[], usage=None)
    llm = _FakeStreamingLLM([
        [
            LlmStreamEvent.make_tool_call(ToolCall(name='broken', arguments={}, id='c1')),
            LlmStreamEvent.make_done(ChatResponse(content='', tool_calls=[ToolCall(name='broken', arguments={}, id='c1')], usage=None)),
        ],
        [
            LlmStreamEvent.make_delta('sorry, that tool is broken'),
            LlmStreamEvent.make_done(final),
        ],
    ])
    # tools_runtime where 'broken' raises.
    def _explode(args):
        raise ValueError("boom")
    tools = _FakeToolsRuntime({'broken': _explode})
    rt = _make_runtime(llm)
    events = _collect(rt, tools_runtime=tools, user_key='u1')

    tr_events = [e for e in events if e.kind == 'tool_result']
    assert len(tr_events) == 1
    assert tr_events[0].tool_result.error is not None
    assert 'ValueError' in tr_events[0].tool_result.error
    assert 'Tool broken failed' in tr_events[0].tool_result.output
    # The stream continued to produce a normal done.
    assert events[-1].kind == 'done'


def test_loop_limit_emits_marker_and_stops():
    """If the LLM keeps requesting tool calls past
    _MAX_TOOL_ROUNDS=3, the runtime must emit a marker
    tool_result and finish gracefully."""
    # Always returns a tool call → would loop forever
    # without the cap.
    looping_round = [
        LlmStreamEvent.make_tool_call(ToolCall(name='loop', arguments={}, id='c')),
        LlmStreamEvent.make_done(ChatResponse(content='', tool_calls=[ToolCall(name='loop', arguments={}, id='c')], usage=None)),
    ]
    llm = _FakeStreamingLLM([
        list(looping_round),
        list(looping_round),
        list(looping_round),
        list(looping_round),  # 4th round — limit triggers here
    ])
    tools = _FakeToolsRuntime({'loop': lambda a: 'still looping'})
    rt = _make_runtime(llm)
    events = _collect(rt, tools_runtime=tools, user_key='u1')

    # The marker tool_result with error='tool_round_limit'.
    limit_markers = [e for e in events if e.kind == 'tool_result' and e.tool_result.error == 'tool_round_limit']
    assert len(limit_markers) == 1
    # And we still emit done at the end.
    assert events[-1].kind == 'done'
    # Did NOT exceed the LLM-call budget.
    assert len(llm.calls) <= 4


def test_multiple_parallel_tool_calls_in_one_round():
    """A round can include multiple tool_call events; the
    runtime must execute each tool and emit a tool_result for
    each before moving to the next round."""
    final = ChatResponse(content='both done', tool_calls=[], usage=None)
    llm = _FakeStreamingLLM([
        [
            LlmStreamEvent.make_tool_call(ToolCall(name='a', arguments={'k': 1}, id='c_a')),
            LlmStreamEvent.make_tool_call(ToolCall(name='b', arguments={'k': 2}, id='c_b')),
            LlmStreamEvent.make_done(ChatResponse(
                content='',
                tool_calls=[
                    ToolCall(name='a', arguments={'k': 1}, id='c_a'),
                    ToolCall(name='b', arguments={'k': 2}, id='c_b'),
                ],
                usage=None,
            )),
        ],
        [
            LlmStreamEvent.make_delta('both done'),
            LlmStreamEvent.make_done(final),
        ],
    ])
    tools = _FakeToolsRuntime({
        'a': lambda args: f'a={args["k"]}',
        'b': lambda args: f'b={args["k"]}',
    })
    rt = _make_runtime(llm)
    events = _collect(rt, tools_runtime=tools, user_key='u1')

    tr_events = [e for e in events if e.kind == 'tool_result']
    assert len(tr_events) == 2
    assert tr_events[0].tool_result.name == 'a'
    assert tr_events[0].tool_result.output == 'a=1'
    assert tr_events[1].tool_result.name == 'b'
    assert tr_events[1].tool_result.output == 'b=2'


# ------------------------------------------------------------------
# Error events from the LLM
# ------------------------------------------------------------------


def test_llm_error_event_is_forwarded_and_stops_loop():
    llm = _FakeStreamingLLM([[
        LlmStreamEvent.make_delta('partial...'),
        LlmStreamEvent.make_error('upstream timeout'),
    ]])
    rt = _make_runtime(llm)
    events = _collect(rt)
    kinds = [e.kind for e in events]
    # delta + error, no done.
    assert 'error' in kinds
    assert 'done' not in kinds
    err = [e for e in events if e.kind == 'error'][0]
    assert 'upstream timeout' in err.error


# ------------------------------------------------------------------
# Usage aggregation across rounds
# ------------------------------------------------------------------


def test_usage_aggregated_across_tool_rounds():
    """Two rounds each emit a usage event; the runtime
    consolidates them into ONE usage event before done."""
    final = ChatResponse(content='final', tool_calls=[], usage=None)
    llm = _FakeStreamingLLM([
        [
            LlmStreamEvent.make_tool_call(ToolCall(name='t', arguments={}, id='c')),
            LlmStreamEvent.make_usage({'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}),
            LlmStreamEvent.make_done(ChatResponse(content='', tool_calls=[ToolCall(name='t', arguments={}, id='c')], usage=None)),
        ],
        [
            LlmStreamEvent.make_delta('final'),
            LlmStreamEvent.make_usage({'prompt_tokens': 20, 'completion_tokens': 3, 'total_tokens': 23}),
            LlmStreamEvent.make_done(final),
        ],
    ])
    tools = _FakeToolsRuntime({'t': lambda a: 'ok'})
    rt = _make_runtime(llm)
    events = _collect(rt, tools_runtime=tools, user_key='u1')

    usage_events = [e for e in events if e.kind == 'usage']
    assert len(usage_events) == 1
    # Sum of both rounds.
    assert usage_events[0].usage == {
        'prompt_tokens':     30,
        'completion_tokens': 8,
        'total_tokens':      38,
    }
