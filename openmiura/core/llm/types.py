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

import base64
import hashlib
from dataclasses import dataclass
from typing import Any, Literal


StreamEventKind = Literal[
    "delta",
    "thinking",
    "tool_call",
    "tool_call_delta",
    "tool_result",
    "usage",
    "done",
    "error",
    "cancelled",
]

AttachmentKind = Literal["image"]


@dataclass
class Attachment:
    """A binary attachment carried by a chat message — currently
    only images (pasted spectra screenshots, lab-notebook scans,
    drawn structures…). Multi-modal LLMs consume them via
    provider-specific wire shapes; the per-provider client owns
    that translation.

    Fields:

      - ``kind`` — discriminator. Today only ``'image'``. Audio
        and arbitrary binary attachments are reserved for
        future H3 slices.
      - ``media_type`` — MIME type (``image/png``, ``image/jpeg``,
        ``image/webp``, etc). Used to set the right wire field
        on Anthropic / OpenAI; ignored by Ollama which sniffs
        the bytes itself.
      - ``data_b64`` — base64-encoded payload without any
        ``data:...;base64,`` prefix.
      - ``sha256`` — optional precomputed hex digest. The
        audit layer fills this so the same bytes don't get
        rehashed downstream.
    """

    kind: AttachmentKind
    media_type: str
    data_b64: str
    sha256: str | None = None


def attachment_from_dict(d: Any) -> Attachment | None:
    """Best-effort dict → Attachment. Returns ``None`` on
    malformed input so caller can skip silently rather than
    raise (HTTP payloads from the wild can be ragged).
    """
    if not isinstance(d, dict):
        return None
    kind = str(d.get("kind") or "").strip().lower()
    if kind != "image":
        return None
    media = str(d.get("media_type") or "").strip()
    if not media.startswith("image/"):
        return None
    data = str(d.get("data_b64") or "").strip()
    if not data:
        return None
    sha = str(d.get("sha256") or "").strip() or None
    return Attachment(
        kind="image",
        media_type=media,
        data_b64=data,
        sha256=sha,
    )


def attachment_sha256(att: Attachment) -> str:
    """Compute the SHA-256 of the raw (post-base64) bytes.

    Cheap: a 1 MiB image hashes in ~5 ms. The result is hex-
    encoded so it can live in a JSON audit record.
    """
    raw = base64.b64decode(att.data_b64, validate=False)
    return hashlib.sha256(raw).hexdigest()


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]
    id: str | None = None


@dataclass
class ToolCallDelta:
    """An incremental fragment of a tool call still being
    streamed by the LLM, surfaced *before* the call is fully
    assembled (H3.2).

    Providers that stream tool-call arguments do so as a
    sequence of JSON-string fragments:

      - OpenAI: ``choices[].delta.tool_calls[].function.arguments``
        — the name + id arrive in the first fragment, then
        arguments accumulate piece by piece.
      - Anthropic: ``content_block_start`` (name + id, no args)
        followed by ``input_json_delta.partial_json`` fragments.

    Forwarding these lets the UI show a call forming in real
    time ("``search_pubmed({"query": "spin–…``") instead of
    waiting for the whole JSON. It is purely additive
    visibility: the fully-assembled ``ToolCall`` still arrives
    later as a normal ``tool_call`` event, and *that* remains
    the only trigger for execution. A consumer that ignores
    ``tool_call_delta`` sees no behaviour change.

    Fields:

      - ``index`` — the provider's per-round tool-call index.
        A single round can stream several calls; the index
        lets a consumer group fragments belonging to the same
        call. Stable for the lifetime of one call.
      - ``id`` — the call id, present on the first fragment for
        an index once known, ``None`` on subsequent
        argument-only fragments.
      - ``name`` — the function name, present on the first
        fragment for an index, ``None`` on argument-only
        fragments.
      - ``arguments_delta`` — the raw JSON fragment for *this*
        chunk (NOT cumulative). Concatenating every
        ``arguments_delta`` for a given ``index`` reproduces
        the full arguments JSON string. May be empty on the
        opening fragment that only announces id + name.

    Providers that deliver tool calls atomically (Ollama, which
    returns a complete ``tool_calls`` array in the final
    message) never emit ``tool_call_delta`` — they go straight
    to ``tool_call``.
    """

    index: int
    id: str | None = None
    name: str | None = None
    arguments_delta: str = ""


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

    Exactly one of (``delta`` / ``thinking`` / ``tool_call`` /
    ``tool_call_delta`` / ``tool_result`` / ``usage`` /
    ``error`` / ``final``) carries a meaningful value for any
    given ``kind``; the rest are ``None``. We do NOT use
    ``Optional`` unions over a base class because the consuming
    code (HTTP SSE emitter, science chat UI) wants cheap
    attribute access without isinstance checks.

    The LLM clients emit (``delta`` / ``thinking`` /
    ``tool_call`` / ``tool_call_delta`` / ``usage`` / ``done``
    / ``error``). ``tool_call_delta`` (H3.2) carries an
    incremental fragment of a tool call still being streamed;
    it always precedes the fully-assembled ``tool_call`` for
    the same call and is optional visibility only.
    ``thinking`` (H3.4) carries an incremental fragment of the
    model's extended-thinking reasoning trace (Anthropic
    ``thinking_delta`` blocks); it is pure visibility and is
    never merged into the assistant's answer text (``delta``)
    or into ``ChatResponse.content``. The ``tool_result`` kind
    is emitted exclusively by the agent runtime after it
    executes a tool the LLM requested — this lets the UI render
    a "tool X finished" badge between LLM rounds.
    ``cancelled`` (H3.5) is emitted by the agent runtime when a
    caller-supplied cancel check trips mid-stream; it is the
    terminal event for that stream (no ``done`` follows) and
    signals that the partial output so far is all there will
    be. It carries no payload — the reason lives at the
    transport/audit layer.
    """

    kind: StreamEventKind
    delta: str | None = None
    thinking: str | None = None
    tool_call: ToolCall | None = None
    tool_call_delta: ToolCallDelta | None = None
    tool_result: ToolResult | None = None
    usage: dict[str, int] | None = None
    error: str | None = None
    final: ChatResponse | None = None

    # Convenience constructors keep call sites readable.

    @classmethod
    def make_delta(cls, text: str) -> "LlmStreamEvent":
        return cls(kind="delta", delta=text)

    @classmethod
    def make_thinking(cls, text: str) -> "LlmStreamEvent":
        return cls(kind="thinking", thinking=text)

    @classmethod
    def make_tool_call(cls, tc: ToolCall) -> "LlmStreamEvent":
        return cls(kind="tool_call", tool_call=tc)

    @classmethod
    def make_tool_call_delta(cls, tcd: ToolCallDelta) -> "LlmStreamEvent":
        return cls(kind="tool_call_delta", tool_call_delta=tcd)

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

    @classmethod
    def make_cancelled(cls) -> "LlmStreamEvent":
        return cls(kind="cancelled")
