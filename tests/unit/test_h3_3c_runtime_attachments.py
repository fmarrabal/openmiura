"""Tests for H3.3c — AgentRuntime forwards attachments.

H3.3c plumbs the multi-modal payload from the HTTP boundary
all the way down to the per-provider LLM clients. The
runtime sits between the two: ``generate_reply`` and
``generate_reply_stream`` both gain an ``attachments``
kwarg, and ``_build_messages`` stamps it on the live user
turn (NOT on history — history is text-only).

These tests pin:

  1. ``_build_messages`` attaches the field to the user turn
     when ``attachments`` is non-empty.
  2. Same builder leaves the user turn unchanged when
     ``attachments`` is None / empty.
  3. The async ``generate_reply_stream`` forwards the field
     to the LLM client (captured via a fake LLM).
  4. The sync ``generate_reply`` does the same.
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

import pytest

from openmiura.core.agent_runtime import AgentRuntime
from openmiura.core.llm.types import ChatResponse, LlmStreamEvent


_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)
_ATT = {"kind": "image", "media_type": "image/png", "data_b64": _PNG_B64}


class _FakeLLM:
    """Sync LLM stub. Captures the messages it sees so the
    test can pin the user turn's shape."""

    def __init__(self) -> None:
        self.model = "fake"
        self.calls: list[dict[str, Any]] = []

    def chat(self, messages, *, tools=None):
        self.calls.append({"messages": list(messages), "tools": tools})
        return ChatResponse(content="ok", tool_calls=[], usage=None)


class _FakeStreamingLLM:
    """Streaming LLM stub — yields a single delta then a done."""

    def __init__(self) -> None:
        self.model = "fake"
        self.calls: list[dict[str, Any]] = []

    def chat_stream(self, messages, *, tools=None) -> AsyncIterator[LlmStreamEvent]:
        self.calls.append({"messages": list(messages), "tools": tools})

        async def _gen() -> AsyncIterator[LlmStreamEvent]:
            yield LlmStreamEvent.make_delta("ok")
            yield LlmStreamEvent.make_done(
                ChatResponse(content="ok", tool_calls=[], usage=None)
            )
        return _gen()


class _FakeAudit:
    def __init__(self, history=None):
        self._history = history or []
    def get_recent_messages(self, *, session_id, limit):
        return self._history


class _FakeSettings:
    class _Runtime:
        history_limit = 5
    class _LLM:
        provider = ""
        model = ""
    runtime = _Runtime()
    llm = _LLM()


def _make_runtime(llm) -> AgentRuntime:
    """Build a runtime with stubbed deps via __new__ to
    bypass the LLM-builder in the normal __init__. Mirrors
    the pattern in test_agent_runtime_stream.py."""
    rt = AgentRuntime.__new__(AgentRuntime)
    rt.llm = llm
    rt.audit = _FakeAudit()
    rt.settings = _FakeSettings()
    rt.skill_loader = None
    rt.skills_path = ""
    rt._agent_cfg = lambda agent_id: {
        "system_prompt": "you are openMiura",
    }
    return rt


# ------------------------------------------------------------------
# _build_messages — attachment stamping
# ------------------------------------------------------------------


def test_build_messages_stamps_attachments_on_live_user_turn() -> None:
    rt = _make_runtime(_FakeLLM())
    msgs = rt._build_messages(
        agent_id="default",
        session_id="s1",
        user_text="what is in this?",
        attachments=[_ATT],
    )
    assert msgs[-1]["role"] == "user"
    assert msgs[-1]["content"] == "what is in this?"
    assert msgs[-1]["attachments"] == [_ATT]


def test_build_messages_omits_attachments_field_when_none() -> None:
    rt = _make_runtime(_FakeLLM())
    msgs = rt._build_messages(
        agent_id="default",
        session_id="s1",
        user_text="hi",
    )
    assert msgs[-1] == {"role": "user", "content": "hi"}
    assert "attachments" not in msgs[-1]


def test_build_messages_omits_attachments_field_when_empty_list() -> None:
    rt = _make_runtime(_FakeLLM())
    msgs = rt._build_messages(
        agent_id="default",
        session_id="s1",
        user_text="hi",
        attachments=[],
    )
    assert "attachments" not in msgs[-1]


def test_build_messages_does_not_stamp_attachments_on_history() -> None:
    """History entries come from the audit DB (text-only) and
    must never grow an attachments field even if we pass
    attachments for the current turn."""
    rt = _make_runtime(_FakeLLM())
    rt.audit = _FakeAudit(history=[
        ("user", "earlier turn"),
        ("assistant", "earlier reply"),
    ])
    msgs = rt._build_messages(
        agent_id="default",
        session_id="s1",
        user_text="current turn",
        attachments=[_ATT],
    )
    # 0 system + 2 history + 1 new = 4 messages.
    assert len(msgs) == 4
    assert msgs[1] == {"role": "user", "content": "earlier turn"}
    assert msgs[2] == {"role": "assistant", "content": "earlier reply"}
    assert msgs[3]["attachments"] == [_ATT]
    # And history entries have no attachments field.
    assert "attachments" not in msgs[1]
    assert "attachments" not in msgs[2]


# ------------------------------------------------------------------
# generate_reply — sync path forwards attachments
# ------------------------------------------------------------------


def test_generate_reply_forwards_attachments_to_llm() -> None:
    llm = _FakeLLM()
    rt = _make_runtime(llm)
    rt.generate_reply(
        agent_id="default",
        session_id="s1",
        user_text="?",
        attachments=[_ATT],
    )
    assert len(llm.calls) == 1
    user_msg = llm.calls[0]["messages"][-1]
    assert user_msg["attachments"] == [_ATT]


# ------------------------------------------------------------------
# generate_reply_stream — async path forwards attachments
# ------------------------------------------------------------------


def test_generate_reply_stream_forwards_attachments_to_llm() -> None:
    llm = _FakeStreamingLLM()
    rt = _make_runtime(llm)

    async def _run() -> None:
        async for _ in rt.generate_reply_stream(
            agent_id="default",
            session_id="s1",
            user_text="?",
            attachments=[_ATT],
        ):
            pass

    asyncio.run(_run())
    assert len(llm.calls) == 1
    user_msg = llm.calls[0]["messages"][-1]
    assert user_msg["attachments"] == [_ATT]
