"""Tests for H3.1 — parallel tool execution in the agent runtime.

H1.4 built the tool-call loop sequentially: each tool ran
``await loop.run_in_executor(...)`` in turn. With modern
LLMs that fire several ``tool_call`` events per round (GPT-4,
Claude 3.5+, Gemini) that serialisation became the latency
floor: 3 tools at 2 s each meant 6 s end-to-end even though
they were independent.

H3.1 wraps every per-round tool execution in
``asyncio.gather`` so they overlap. The output order
(emitted ``tool_result`` events + appended ``tool``
messages) must still match the LLM's request order — only
the wallclock collapses.

These tests use a fake LLM that scripts a single round
with N parallel ``tool_call`` events, a tools runtime whose
handlers ``time.sleep`` to make parallelism observable, and
assert both the wallclock and the order contract.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any, AsyncIterator

import pytest

from openmiura.core.agent_runtime import AgentRuntime
from openmiura.core.llm.types import ChatResponse, LlmStreamEvent, ToolCall


# ------------------------------------------------------------------
# Fakes — match the patterns used by test_agent_runtime_stream.py
# ------------------------------------------------------------------


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


class _SleepingToolsRuntime:
    """Tools whose handlers sleep for a configurable time, so
    we can pin parallel execution by wallclock.

    Each ``run_tool`` records its start + end timestamps in
    ``self.events`` so a test can prove the executions
    overlapped (start of #2 < end of #1)."""

    def __init__(self, sleeps_ms: dict[str, int]):
        self.sleeps_ms = sleeps_ms
        self.events: list[tuple[str, str, float]] = []  # (tool, phase, ts)
        self._lock = threading.Lock()

    def available_tool_schemas(self, agent_id, *, user_key=None, **_kwargs):
        return [
            {'type': 'function', 'function': {'name': n, 'parameters': {}}}
            for n in self.sleeps_ms
        ]

    def run_tool(self, *, agent_id, session_id, user_key, tool_name, args, **_kwargs):
        with self._lock:
            self.events.append((tool_name, 'start', time.perf_counter()))
        time.sleep(self.sleeps_ms.get(tool_name, 0) / 1000.0)
        with self._lock:
            self.events.append((tool_name, 'end', time.perf_counter()))
        return f'{tool_name}-ok'


class _FailingToolsRuntime:
    """One tool always raises; others succeed. Used to prove
    failure isolation under parallel execution."""

    def __init__(self, bad: str):
        self.bad = bad
        self.calls: list[str] = []
        self._lock = threading.Lock()

    def available_tool_schemas(self, *_a, **_kw):
        return []

    def run_tool(self, *, tool_name, **_kw):
        with self._lock:
            self.calls.append(tool_name)
        if tool_name == self.bad:
            raise ValueError(f'tool {tool_name} broke')
        return f'{tool_name}-ok'


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
    agents: dict[str, Any] = {}


def _make_runtime(llm) -> AgentRuntime:
    rt = AgentRuntime.__new__(AgentRuntime)
    rt.llm = llm
    rt.audit = _FakeAudit()
    rt.settings = _FakeSettings()
    rt.skill_loader = None
    rt.skills_path = ""
    return rt


def _collect(rt: AgentRuntime, **kw) -> list[LlmStreamEvent]:
    async def _run() -> list[LlmStreamEvent]:
        out: list[LlmStreamEvent] = []
        async for ev in rt.generate_reply_stream(
            agent_id='default',
            session_id='s1',
            user_text='hi',
            **kw,
        ):
            out.append(ev)
        return out
    return asyncio.run(_run())


def _three_parallel_round(names: list[str]) -> list[LlmStreamEvent]:
    """Build a single LLM round with N parallel tool_call
    events and a done event listing all of them."""
    tcs = [ToolCall(name=n, arguments={}, id=f'c_{n}') for n in names]
    events: list[LlmStreamEvent] = []
    for tc in tcs:
        events.append(LlmStreamEvent.make_tool_call(tc))
    events.append(LlmStreamEvent.make_done(
        ChatResponse(content='', tool_calls=tcs, usage=None)
    ))
    return events


# ------------------------------------------------------------------
# Wallclock — three 100 ms tools complete in < 2× one tool
# ------------------------------------------------------------------


def test_three_parallel_tools_run_concurrently_not_serially():
    """If the runtime serialised the tools, total wall time
    would be ~3 × 100 ms = 300 ms. In parallel it should
    finish under 200 ms even on a slow CI runner.

    We assert under 250 ms to absorb thread-pool startup
    cost; the contract is "clearly less than the serial
    baseline", not "exactly 100 ms"."""
    final = ChatResponse(content='ok', tool_calls=[], usage=None)
    llm = _FakeStreamingLLM([
        _three_parallel_round(['a', 'b', 'c']),
        [LlmStreamEvent.make_done(final)],
    ])
    tools = _SleepingToolsRuntime({'a': 100, 'b': 100, 'c': 100})
    rt = _make_runtime(llm)

    t0 = time.perf_counter()
    _collect(rt, tools_runtime=tools, user_key='u1')
    elapsed_ms = (time.perf_counter() - t0) * 1000

    # The 3 sleeps overlap; total should be near the longest
    # single sleep, not the sum. Pin loosely.
    assert elapsed_ms < 250, (
        f'expected parallel execution (~100 ms), got {elapsed_ms:.0f} ms '
        '— looks like tools ran sequentially'
    )
    # And by construction the per-tool start timestamps should
    # all happen BEFORE any per-tool end timestamp (the strict
    # overlap proof).
    starts = sorted(ts for _, phase, ts in tools.events if phase == 'start')
    ends   = sorted(ts for _, phase, ts in tools.events if phase == 'end')
    assert len(starts) == 3 and len(ends) == 3
    assert max(starts) < min(ends), (
        f'tool starts {starts} must all precede tool ends {ends}'
    )


# ------------------------------------------------------------------
# Order preservation — input order is the emit order
# ------------------------------------------------------------------


def test_tool_results_emitted_in_request_order_not_completion_order():
    """Tool A sleeps 200 ms, B sleeps 50 ms. B finishes
    first but the runtime must emit the tool_result events
    in the order the LLM requested them: [A, B]."""
    final = ChatResponse(content='ok', tool_calls=[], usage=None)
    llm = _FakeStreamingLLM([
        _three_parallel_round(['a', 'b']),
        [LlmStreamEvent.make_done(final)],
    ])
    tools = _SleepingToolsRuntime({'a': 200, 'b': 50})
    rt = _make_runtime(llm)
    events = _collect(rt, tools_runtime=tools, user_key='u1')

    tr = [e.tool_result for e in events if e.kind == 'tool_result']
    assert [r.name for r in tr] == ['a', 'b'], (
        'tool_result events must preserve request order even when '
        'the LLM-faster tool completes first'
    )
    assert [r.output for r in tr] == ['a-ok', 'b-ok']
    # And the audit trail (the 'tool' messages appended to
    # the conversation for the next round) follows the same
    # order — captured indirectly by the second LLM call's
    # message snapshot.
    assert len(llm.calls) >= 2, 'a second round must have been opened'
    second_call_msgs = llm.calls[1]['messages']
    tool_msgs = [m for m in second_call_msgs if m.get('role') == 'tool']
    assert [m['name'] for m in tool_msgs] == ['a', 'b']


# ------------------------------------------------------------------
# Failure isolation — one tool raising must not abort siblings
# ------------------------------------------------------------------


def test_failure_in_one_tool_does_not_cancel_siblings():
    """Tool B raises ValueError; tools A and C must still
    complete and surface tool_result events."""
    final = ChatResponse(content='ok', tool_calls=[], usage=None)
    llm = _FakeStreamingLLM([
        _three_parallel_round(['a', 'b', 'c']),
        [LlmStreamEvent.make_done(final)],
    ])
    tools = _FailingToolsRuntime(bad='b')
    rt = _make_runtime(llm)
    events = _collect(rt, tools_runtime=tools, user_key='u1')

    tr = [e.tool_result for e in events if e.kind == 'tool_result']
    assert len(tr) == 3
    names = [r.name for r in tr]
    assert names == ['a', 'b', 'c']
    # B carries an error; the others don't.
    by_name = {r.name: r for r in tr}
    assert by_name['a'].error is None
    assert by_name['a'].output == 'a-ok'
    assert by_name['b'].error is not None
    assert 'ValueError' in by_name['b'].error
    assert 'Tool b failed' in by_name['b'].output
    assert by_name['c'].error is None
    assert by_name['c'].output == 'c-ok'
    # All three tools were actually invoked.
    assert sorted(tools.calls) == ['a', 'b', 'c']
    # And the stream continued to produce a normal done.
    assert events[-1].kind == 'done'


# ------------------------------------------------------------------
# Call IDs preserved — UI uses them to match tool_call → result
# ------------------------------------------------------------------


def test_tool_result_call_id_matches_originating_tool_call():
    """The tool_result.call_id field must be the same as the
    originating ToolCall.id so the UI can pair them. Critical
    for the H1.6 tool timeline."""
    final = ChatResponse(content='ok', tool_calls=[], usage=None)
    llm = _FakeStreamingLLM([
        _three_parallel_round(['a', 'b']),
        [LlmStreamEvent.make_done(final)],
    ])
    tools = _SleepingToolsRuntime({'a': 10, 'b': 10})
    rt = _make_runtime(llm)
    events = _collect(rt, tools_runtime=tools, user_key='u1')

    tc_events = [e for e in events if e.kind == 'tool_call']
    tr_events = [e for e in events if e.kind == 'tool_result']
    assert len(tc_events) == 2 and len(tr_events) == 2
    for tc_ev, tr_ev in zip(tc_events, tr_events):
        assert tc_ev.tool_call.id == tr_ev.tool_result.call_id
