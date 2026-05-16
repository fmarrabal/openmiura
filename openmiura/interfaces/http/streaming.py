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
from typing import Any, AsyncIterator, Callable

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


__all__ = ["split_into_chunks", "stream_message"]
