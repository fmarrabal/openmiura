"""Shared types for the LLM client surface.

Two flavours live here:

  - ``ToolCall`` / ``ChatResponse`` — the synchronous single-
    shot contract every client has implemented since the
    project started.

  - ``LlmStreamEvent`` (H1.1) — the asynchronous streaming
    contract that ``chat_stream`` async generators yield.
    Tagged-union style: ``kind`` discriminates which fields
    are meaningful for a given event. The shape is
    intentionally simple so each per-provider implementation
    converts native streaming chunks into this canonical
    event sequence:

       delta*  → (tool_call | usage)*  → done
                                       OR error

    "delta" carries an incremental text chunk; "tool_call"
    carries a fully-assembled ToolCall (the per-provider
    client buffers any partial JSON-argument streaming
    before yielding); "usage" carries token counts; "done"
    carries the materialised ``ChatResponse`` so a consumer
    that prefers the single-shot contract can wait for
    ``done`` and ignore everything else.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


StreamEventKind = Literal["delta", "tool_call", "tool_result", "usage", "done", "error"]


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]
    id: str | None = None


@dataclass
class ToolResult:
    """Outcome of a tool execution, surfaced to the streaming
    consumer between LLM rounds.

    The runtime emits one ``LlmStreamEvent(kind="tool_result")``
    per executed tool call so the UI can show "tool X
    completed" before the next LLM round resumes streaming
    text. ``output`` is the tool's string output (truncated
    by the consumer for display); ``error`` is non-empty
    when the tool raised. ``call_id`` lets the consumer
    match the result back to the originating tool_call event.
    """

    name: str
    output: str
    call_id: str | None = None
    error: str | None = None


@dataclass
class ChatResponse:
    content: str
    tool_calls: list[ToolCall]
    usage: dict[str, int] | None = None


@dataclass
class LlmStreamEvent:
    """One canonical streaming event yielded by ``chat_stream``
    (LLM clients) and ``generate_reply_stream`` (the agent
    runtime).

    Exactly one of (``delta`` / ``tool_call`` / ``tool_result`` /
    ``usage`` / ``error`` / ``final``) carries a meaningful
    value for any given ``kind``; the rest are ``None``. We
    do NOT use ``Optional`` unions over a base class because
    the consuming code (HTTP SSE emitter, science chat UI)
    wants cheap attribute access without isinstance checks.

    The LLM clients only emit (``delta`` / ``tool_call`` /
    ``usage`` / ``done`` / ``error``). The ``tool_result``
    kind is emitted exclusively by the agent runtime after
    it executes a tool the LLM requested — this lets the
    UI render a "tool X finished" badge between LLM rounds.
    """

    kind: StreamEventKind
    delta: str | None = None
    tool_call: ToolCall | None = None
    tool_result: ToolResult | None = None
    usage: dict[str, int] | None = None
    error: str | None = None
    final: ChatResponse | None = None

    # Convenience constructors keep call sites readable.

    @classmethod
    def make_delta(cls, text: str) -> "LlmStreamEvent":
        return cls(kind="delta", delta=text)

    @classmethod
    def make_tool_call(cls, tc: ToolCall) -> "LlmStreamEvent":
        return cls(kind="tool_call", tool_call=tc)

    @classmethod
    def make_tool_result(cls, tr: ToolResult) -> "LlmStreamEvent":
        return cls(kind="tool_result", tool_result=tr)

    @classmethod
    def make_usage(cls, usage: dict[str, int]) -> "LlmStreamEvent":
        return cls(kind="usage", usage=usage)

    @classmethod
    def make_done(cls, final: ChatResponse) -> "LlmStreamEvent":
        return cls(kind="done", final=final)

    @classmethod
    def make_error(cls, message: str) -> "LlmStreamEvent":
        return cls(kind="error", error=message)
