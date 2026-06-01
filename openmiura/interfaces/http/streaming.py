"""http/streaming.py — Server-Sent Events helpers for the chat surface.

Closes the last of the four backend additions (G3). The
existing ``POST /http/message`` endpoint is single-shot: the
caller waits for the full ``OutboundMessage`` and then gets
the whole text at once. For an LLM that takes 5–30 s to
generate a long answer this feels broken — the user sees a
spinner and wonders if the system is hung.

**Honest disclaimer.** This module ships *pseudo-streaming*:
we still run ``process_message`` synchronously (in a thread
so the event loop isn't blocked), and once the full text
lands we chunk it into smaller pieces and emit them as SSE
``chunk`` events with a small inter-chunk delay. The user
gets a snappier "text materialising" experience but the
underlying LLM call is still single-shot.

The contract surfaces this explicitly via
``streaming_mode = "pseudo"`` in the initial ``meta`` event.
When openMiura's LLM clients (Ollama, OpenAI-compat,
Anthropic) grow native ``chat_stream`` methods this module
can switch to real token streaming without changing the
endpoint URL or the SSE event shape — only the
``streaming_mode`` value flips to ``"native"``.

SSE event taxonomy:

  event: meta
  data:  {"session_id": "...", "agent_id": "...",
          "streaming_mode": "pseudo"}

  event: heartbeat
  data:  {"ts": <unix-float>}

  event: chunk
  data:  {"delta": "<text>", "index": <0-based>}

  event: done
  data:  {"message": <full OutboundMessage>}

  event: error
  data:  {"error": "<reason>"}

The stream always closes after either ``done`` or ``error``.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import asdict
from typing import Any, AsyncIterator, Callable

from openmiura.core.llm.types import LlmStreamEvent
from openmiura.core.schema import InboundMessage, OutboundMessage


# Inter-chunk pacing. Small enough that a 2 KB response feels
# snappy (~80 chunks * 25 ms = 2 s total render time), large
# enough that the browser actually renders each step.
_CHUNK_DELAY_S = 0.025

# Heartbeat cadence while the synchronous handler is running.
# Two seconds is the sweet spot: a fast LLM call (< 2 s) emits
# zero heartbeats, a slow one (~30 s) emits ~15.
_HEARTBEAT_INTERVAL_S = 2.0

# Target chunk size for splitting a long reply. 80 chars is
# roughly one human-readable "phrase" — small enough to feel
# responsive, large enough not to drown the browser in events.
_CHUNK_TARGET_CHARS = 80


def split_into_chunks(text: str, *, target: int = _CHUNK_TARGET_CHARS) -> list[str]:
    """Split a text into smallish chunks that respect paragraph
    and sentence boundaries.

    Algorithm:
      1. First split by paragraph (double newline). Paragraphs
         under ``target`` are kept whole.
      2. Long paragraphs are split by sentence boundary
         (``. `` / ``! `` / ``? ``).
      3. Sentences longer than 2× target are hard-cut at
         ``target`` boundaries — better an ugly split than a
         3 KB single chunk.

    The function is pure and deterministic so the unit test
    can pin its behaviour without needing the rest of the
    pipeline.
    """
    if not isinstance(text, str):
        return [""]
    src = text.strip()
    if not src:
        return [""]

    chunks: list[str] = []
    paragraphs = src.split("\n\n")

    def _push_chunk(s: str) -> None:
        s = s.strip()
        if s:
            chunks.append(s)

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(para) <= target:
            _push_chunk(para)
            continue
        # Sentence-aware split.
        sentences: list[str] = []
        buf = ""
        for ch in para:
            buf += ch
            if ch in ".!?" and len(buf) >= 1:
                # Look at the next character — if it's a space
                # or end of string we treat the sentence as
                # closed. We can't peek without an index here,
                # so we close on `.! ?` and trim. Multi-char
                # token like "..." stays in one buffer.
                sentences.append(buf)
                buf = ""
        if buf:
            sentences.append(buf)

        for sent in sentences:
            sent = sent.strip()
            if not sent:
                continue
            if len(sent) <= 2 * target:
                _push_chunk(sent)
            else:
                for i in range(0, len(sent), target):
                    _push_chunk(sent[i:i + target])

    return chunks or [""]


def _sse_event(name: str, payload: Any) -> bytes:
    """Format a single SSE event as bytes."""
    line = "event: " + name + "\n"
    data = json.dumps(payload, ensure_ascii=False)
    line += "data: " + data + "\n\n"
    return line.encode("utf-8")


# ------------------------------------------------------------------
# H3.5 — in-flight native-stream registry for client cancellation.
#
# Each native stream registers under a per-stream id (a uuid hex
# surfaced in its ``meta`` event). A ``DELETE
# /http/message/stream/{id}`` request looks the stream up here and
# sets its cancel ``Event``; the streaming generator consults that
# event cooperatively (via the runtime's ``cancel_check``) and
# stops with a terminal ``cancelled`` event. The generator removes
# its own entry in a ``finally`` so the table only ever holds
# genuinely live streams.
#
# The whole HTTP app runs on a single asyncio loop, so a plain
# dict is safe — there is no await between the get-and-set in
# ``cancel_stream`` and no cross-thread access.
# ------------------------------------------------------------------

_ACTIVE_STREAMS: dict[str, asyncio.Event] = {}


def register_stream(stream_id: str, event: asyncio.Event) -> None:
    """Record a live stream so a later DELETE can cancel it."""
    _ACTIVE_STREAMS[stream_id] = event


def cancel_stream(stream_id: str) -> bool:
    """Flag an in-flight stream for cancellation. Returns True if
    the id was known (and is now flagged), False if it was unknown
    or already finished."""
    event = _ACTIVE_STREAMS.get(stream_id)
    if event is None:
        return False
    event.set()
    return True


def unregister_stream(stream_id: str) -> None:
    """Drop a stream's registry entry (idempotent)."""
    _ACTIVE_STREAMS.pop(stream_id, None)


def active_stream_count() -> int:
    """Number of streams currently registered (test/diagnostic)."""
    return len(_ACTIVE_STREAMS)


async def stream_message(
    gw,
    msg: InboundMessage,
    *,
    handler: Callable[[Any, InboundMessage], OutboundMessage],
) -> AsyncIterator[bytes]:
    """Async generator that runs ``handler`` in a thread, emits
    heartbeats while it works, then streams the result as
    chunked SSE events.

    Yields raw bytes — caller wraps in a ``StreamingResponse``
    with ``media_type="text/event-stream"``.
    """
    loop = asyncio.get_running_loop()
    fut = loop.run_in_executor(None, handler, gw, msg)

    # Initial meta event so the client knows the session and
    # the streaming mode immediately.
    yield _sse_event("meta", {
        "session_id":     msg.session_id or "",
        "user_id":        msg.user_id,
        "streaming_mode": "pseudo",
    })

    # Heartbeat loop while the handler is in flight. We use
    # ``asyncio.wait`` with a timeout so we know when the
    # future is done vs. just slow.
    while not fut.done():
        try:
            await asyncio.wait_for(asyncio.shield(fut), timeout=_HEARTBEAT_INTERVAL_S)
        except asyncio.TimeoutError:
            yield _sse_event("heartbeat", {"ts": time.time()})

    try:
        outbound: OutboundMessage = fut.result()
    except Exception as exc:
        yield _sse_event("error", {"error": str(exc)})
        return

    # Convert to a dict once so we have a consistent shape for
    # both ``done`` and (if we ever choose) intermediate
    # snapshots.
    full = outbound.model_dump() if hasattr(outbound, "model_dump") else dict(outbound)
    full_text = str(full.get("text") or "")

    chunks = split_into_chunks(full_text)
    for i, piece in enumerate(chunks):
        yield _sse_event("chunk", {"delta": piece, "index": i})
        # Sleep between chunks for visible pacing. The total
        # delay is bounded by len(chunks) * _CHUNK_DELAY_S; a
        # 4 KB response with 50 chunks ≈ 1.25 s of pacing,
        # which is the right ballpark to "feel streamy".
        await asyncio.sleep(_CHUNK_DELAY_S)

    yield _sse_event("done", {"message": full})


async def stream_message_native(
    gw,
    msg: InboundMessage,
    *,
    stream_id: str | None = None,
    cancel_event: asyncio.Event | None = None,
) -> AsyncIterator[bytes]:
    """Native streaming path for /http/message/stream (H1.5).

    Bypasses the heavier branches of ``process_message``
    (command parsing, allow-list checks, special routing)
    and goes directly: audit the user turn → call the
    runtime's async ``generate_reply_stream`` → forward
    every LlmStreamEvent as an SSE event → audit the
    assistant turn at the end.

    SSE event taxonomy (in addition to the pseudo path):

      event: meta         streaming_mode = "native", stream_id
      event: chunk        per-LLM-token delta, no pacing
      event: thinking     extended-thinking reasoning fragment (H3.4)
      event: tool_call_delta  incremental tool-argument fragment (H3.2)
      event: tool_call    LLM requested a tool
      event: tool_result  runtime ran the tool, emits output
      event: usage        consolidated token usage
      event: cancelled    stream cancelled by the client (H3.5)
      event: done         full OutboundMessage
      event: error        any error along the way

    The runtime's tool loop runs inside this generator, so
    by the time we emit ``done`` all rounds + tool
    executions are complete and the audit trail is intact.

    H3.5 — cancellation. The ``meta`` event carries a
    ``stream_id``; a ``DELETE /http/message/stream/{stream_id}``
    sets this stream's cancel ``Event`` (held in the module
    registry), which the runtime consults cooperatively via
    ``cancel_check``. On cancel the generator emits a terminal
    ``cancelled`` event and audits the partial assistant turn
    with ``cancelled: true``. The same partial-turn audit runs
    if the client simply drops the connection (the transport
    throws ``CancelledError``/``GeneratorExit`` into us) — so
    the audit trail records cancelled turns either way, even
    though the abrupt-disconnect path cannot emit a final SSE
    event to a client that is already gone.
    """
    # ----- Identity + scope resolution (mirrors pipeline) -----
    try:
        channel_user_id = msg.user_id
        user_key = gw.effective_user_key(channel_user_id) if hasattr(gw, "effective_user_key") else channel_user_id

        scope_meta = dict((msg.metadata or {}).get("_scope") or {})
        tenant_id = str(scope_meta.get("tenant_id") or "").strip() or None
        workspace_id = str(scope_meta.get("workspace_id") or "").strip() or None
        environment = str(scope_meta.get("environment") or "").strip() or None
        channel = msg.channel or "http"

        derived_session_id = (
            gw.derive_session_id(msg, user_key)
            if hasattr(gw, "derive_session_id")
            else (msg.session_id or "")
        )
        session_id = gw.audit.get_or_create_session(
            channel=channel,
            user_id=user_key,
            session_id=derived_session_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
    except Exception as exc:
        yield _sse_event("error", {"error": f"setup failed: {exc!r}"})
        return

    # ----- H3.5 cancellation handle -----
    # Mint a stream id + cancel Event up front so the id can ride
    # the meta event; the actual registry registration is deferred
    # to just before the streaming try/finally so we never leak an
    # entry on an early disconnect (see below).
    if stream_id is None:
        stream_id = uuid.uuid4().hex
    if cancel_event is None:
        cancel_event = asyncio.Event()

    # ----- Initial meta event -----
    yield _sse_event("meta", {
        "session_id":     session_id,
        "user_id":        msg.user_id,
        "streaming_mode": "native",
        "stream_id":      stream_id,
    })

    # ----- Agent + tools resolution -----
    metadata = msg.metadata or {}
    agent_id = str(metadata.get("agent_id") or "default")
    tools_runtime = getattr(gw, "tools", None)

    # ----- Audit user turn BEFORE streaming -----
    try:
        gw.audit.append_message(session_id=session_id, role="user", content=msg.text)
        # H3.3c — include attachments_meta (byte-free) in the
        # audit payload when the user attached images. The raw
        # base64 bytes are forwarded to the LLM via the runtime
        # call below but never persisted in the events table.
        in_payload: dict[str, Any] = {
            "text":          msg.text,
            "metadata_keys": sorted(list(metadata.keys())),
        }
        att_meta = msg.attachments_audit_meta()
        if att_meta:
            in_payload["attachments_meta"] = att_meta
        gw.audit.log_event(
            direction="in",
            channel=channel,
            user_id=user_key,
            session_id=session_id,
            payload=in_payload,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
    except Exception:
        # Audit failures must NOT abort the stream — the
        # user still gets a reply; the operator catches the
        # silent audit miss in the metrics view.
        pass

    # ----- Stream LLM events through the runtime -----
    content_accum = ""
    usage: dict[str, int] | None = None
    saw_error = False
    cancelled = False
    cancel_reason: str | None = None

    def _audit_assistant_turn(text: str, *, was_cancelled: bool, reason: str | None) -> None:
        # Best-effort assistant-turn audit, shared by the normal,
        # graceful-cancel and disconnect paths. A cancelled turn is
        # flagged so the audit trail distinguishes a complete answer
        # from a truncated one. Audit failures never propagate — the
        # operator catches the silent miss in the metrics view.
        try:
            gw.audit.append_message(session_id=session_id, role="assistant", content=text)
            payload: dict[str, Any] = {"text": text, "usage": usage}
            if was_cancelled:
                payload["cancelled"] = True
                if reason:
                    payload["cancel_reason"] = reason
            gw.audit.log_event(
                direction="out",
                channel=channel,
                user_id=msg.user_id,
                session_id=session_id,
                payload=payload,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                environment=environment,
            )
        except Exception:
            pass

    # H3.3c — only forward attachments if the runtime
    # accepts the kwarg. Older runtimes / test doubles fall
    # back to the legacy signature.
    stream_kwargs: dict[str, Any] = dict(
        agent_id=agent_id,
        session_id=session_id,
        user_text=msg.text,
        extra_system=None,
        tools_runtime=tools_runtime,
        user_key=user_key,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
        channel=channel,
    )
    if msg.attachments:
        stream_kwargs["attachments"] = msg.attachments
    # H3.5 — give the runtime a cooperative cancel predicate
    # backed by this stream's Event.
    stream_kwargs["cancel_check"] = cancel_event.is_set

    # Register only now, immediately before the guarded section, so
    # the matching unregister in `finally` always runs and we never
    # leak a registry entry if an early disconnect happened during
    # the meta/audit steps above.
    register_stream(stream_id, cancel_event)
    try:
        try:
            gen = gw.runtime.generate_reply_stream(**stream_kwargs)
        except TypeError:
            # Older runtime / test double that doesn't accept
            # cancel_check — retry on the legacy signature.
            stream_kwargs.pop("cancel_check", None)
            gen = gw.runtime.generate_reply_stream(**stream_kwargs)
        async for ev in gen:
            if ev.kind == "delta":
                content_accum += ev.delta or ""
                yield _sse_event("chunk", {"delta": ev.delta or "", "index": -1})
            elif ev.kind == "thinking" and ev.thinking is not None:
                # H3.4 — extended-thinking fragment. Pure
                # visibility: the model's reasoning trace,
                # surfaced so the operator can audit how it
                # reached the answer. Never accumulated into
                # content_accum (the assistant answer) — it is
                # a separate, collapsible stream in the UI.
                yield _sse_event("thinking", {"delta": ev.thinking})
            elif ev.kind == "tool_call_delta" and ev.tool_call_delta is not None:
                # H3.2 — incremental tool-argument fragment. The
                # UI groups fragments by index and appends
                # arguments_delta to show the call forming; the
                # authoritative tool_call event follows.
                yield _sse_event("tool_call_delta", {
                    "index":           ev.tool_call_delta.index,
                    "id":              ev.tool_call_delta.id,
                    "name":            ev.tool_call_delta.name,
                    "arguments_delta": ev.tool_call_delta.arguments_delta,
                })
            elif ev.kind == "tool_call" and ev.tool_call is not None:
                yield _sse_event("tool_call", {
                    "name":      ev.tool_call.name,
                    "id":        ev.tool_call.id,
                    "arguments": ev.tool_call.arguments,
                })
            elif ev.kind == "tool_result" and ev.tool_result is not None:
                # Truncate the output for the SSE event — UI
                # only needs a preview; the full output is in
                # the audit trail.
                output_preview = (ev.tool_result.output or "")[:1000]
                yield _sse_event("tool_result", {
                    "name":    ev.tool_result.name,
                    "call_id": ev.tool_result.call_id,
                    "output":  output_preview,
                    "error":   ev.tool_result.error,
                })
            elif ev.kind == "usage" and ev.usage:
                usage = ev.usage
                yield _sse_event("usage", ev.usage)
            elif ev.kind == "cancelled":
                # H3.5 — the runtime tripped its cancel check (a
                # DELETE flipped this stream's Event). Emit a
                # terminal cancelled event; the partial assistant
                # turn is audited below.
                cancelled = True
                cancel_reason = cancel_reason or "cancelled_by_client"
                yield _sse_event("cancelled", {"reason": cancel_reason})
                break
            elif ev.kind == "done" and ev.final is not None:
                # The runtime's done event carries the
                # full consolidated ChatResponse. Don't
                # forward it here — we build our own done
                # event with the OutboundMessage shape.
                if ev.final.content:
                    content_accum = ev.final.content
                if ev.final.usage:
                    usage = ev.final.usage
                break
            elif ev.kind == "error":
                yield _sse_event("error", {"error": ev.error or "unknown"})
                saw_error = True
                break
    except (asyncio.CancelledError, GeneratorExit):
        # H3.5 — the client dropped the connection mid-stream. The
        # transport cancels us; audit whatever partial answer we
        # streamed (flagged cancelled) before propagating. We can't
        # emit a final SSE event — there is no one left to read it.
        partial = (content_accum or "").strip()
        if partial:
            _audit_assistant_turn(partial, was_cancelled=True, reason="client_disconnected")
        raise
    except Exception as exc:
        yield _sse_event("error", {"error": f"stream failed: {exc!r}"})
        return
    finally:
        # Always drop the registry entry — this stream can no
        # longer be cancelled once we leave the guarded section.
        unregister_stream(stream_id)

    if saw_error:
        return

    if cancelled:
        # Graceful cancel: audit the partial turn (flagged) and
        # stop. The cancelled event was already emitted; a
        # cancelled stream gets no trailing done.
        _audit_assistant_turn((content_accum or "").strip(), was_cancelled=True, reason=cancel_reason)
        return

    final_text = (content_accum or "").strip() or "(empty response)"

    # ----- Audit assistant turn -----
    _audit_assistant_turn(final_text, was_cancelled=False, reason=None)

    # ----- Emit final done event with OutboundMessage shape -----
    outbound = OutboundMessage(
        channel=channel,
        user_id=msg.user_id,
        session_id=session_id,
        agent_id=agent_id,
        text=final_text,
        metadata={"usage": usage} if usage else {},
    )
    yield _sse_event("done", {"message": outbound.model_dump()})


__all__ = [
    "split_into_chunks",
    "stream_message",
    "stream_message_native",
    "register_stream",
    "cancel_stream",
    "unregister_stream",
    "active_stream_count",
]
