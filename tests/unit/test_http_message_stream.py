"""Tests for the SSE pseudo-streaming chat surface (G3).

We exercise both the pure split-into-chunks helper and the
live POST /http/message/stream endpoint. The endpoint is
tested with a custom ``message_handler`` injected into
``create_app`` so we don't need a real LLM behind it.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from openmiura.core.schema import InboundMessage, OutboundMessage
from openmiura.interfaces.http.app import create_app
from openmiura.interfaces.http.streaming import split_into_chunks


# ------------------------------------------------------------------
# Pure helper: split_into_chunks
# ------------------------------------------------------------------


def test_split_into_chunks_short_text_returns_single_chunk():
    out = split_into_chunks("hello")
    assert out == ["hello"]


def test_split_into_chunks_preserves_paragraph_boundaries():
    text = "first paragraph\n\nsecond paragraph"
    out = split_into_chunks(text, target=80)
    assert out == ["first paragraph", "second paragraph"]


def test_split_into_chunks_long_paragraph_splits_by_sentence():
    text = (
        "First sentence with many words goes here. "
        "Second sentence is also long enough to push us over the boundary. "
        "Third sentence wraps up the thought."
    )
    out = split_into_chunks(text, target=40)
    # We should get roughly 3 chunks (one per sentence) — exact
    # count depends on how the sentence detector ate punctuation.
    assert len(out) >= 3
    # Each chunk is non-empty.
    for c in out:
        assert c
    # And concatenated they cover the original content modulo
    # whitespace.
    joined = " ".join(out).replace("  ", " ")
    assert "First sentence" in joined
    assert "Third sentence" in joined


def test_split_into_chunks_empty_text():
    assert split_into_chunks("") == [""]
    assert split_into_chunks("   \n\n ") == [""]


def test_split_into_chunks_hard_cut_on_very_long_run():
    # 500-char run with no sentence boundary → hard-cut at 40
    # chars per chunk (target 40 → 2× target = 80 max).
    text = "x" * 500
    out = split_into_chunks(text, target=40)
    # All but possibly the last chunk should be 40 chars long.
    assert all(len(c) <= 40 for c in out)
    assert sum(len(c) for c in out) == 500


# ------------------------------------------------------------------
# Endpoint: POST /http/message/stream
# ------------------------------------------------------------------


TOKEN = "test-admin-token-xxxxxxxxxxxxxxxx"


def _build_app(*, handler=None):
    cfg = {
        "server":  {"host": "127.0.0.1", "port": 8081},
        "storage": {"backend": "sqlite", "db_path": ":memory:"},
        "admin":   {"enabled": True, "token": TOKEN},
        "auth":    {"enabled": False},
    }
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False
    ) as f:
        yaml.safe_dump(cfg, f)
        cfg_path = f.name
    return create_app(config_path=cfg_path, message_handler=handler)


def _parse_sse(raw: str) -> list[dict]:
    """Parse an SSE stream body into a list of {event, data} dicts."""
    events = []
    current_event = None
    current_data = []
    for line in raw.splitlines():
        if line.startswith("event: "):
            current_event = line[len("event: "):].strip()
        elif line.startswith("data: "):
            current_data.append(line[len("data: "):])
        elif line == "":
            if current_event is not None:
                payload = "\n".join(current_data)
                try:
                    payload_obj = json.loads(payload) if payload else None
                except json.JSONDecodeError:
                    payload_obj = payload
                events.append({"event": current_event, "data": payload_obj})
            current_event = None
            current_data = []
    return events


def _force_pseudo(app) -> None:
    """Pin ``runtime.supports_streaming`` to False on the
    live gateway so the endpoint goes through the pseudo
    path — needed for the pre-H1.5 tests that scripted the
    sync ``handler`` shape."""
    runtime = getattr(app.state.gw, "runtime", None)
    if runtime is not None:
        runtime.supports_streaming = lambda: False  # type: ignore[attr-defined]


def _echo_handler(gw, msg: InboundMessage) -> OutboundMessage:
    """Synchronous test handler — returns a deterministic
    OutboundMessage so we can assert chunk boundaries and the
    final payload shape."""
    return OutboundMessage(
        channel="http",
        user_id=msg.user_id,
        session_id=msg.session_id or "sess_test",
        agent_id="test-agent",
        text=(
            "First short answer. "
            "Second part of the reply, slightly longer. "
            "Third sentence wraps up."
        ),
        metadata={"echoed_from": msg.text},
    )


def test_stream_emits_meta_chunks_done_in_order():
    app = _build_app(handler=_echo_handler)
    with TestClient(app) as client:
        _force_pseudo(app)
        r = client.post(
            "/http/message/stream",
            json={
                "channel":    "http",
                "user_id":    "curro",
                "text":       "hello",
                "session_id": "sess_test",
            },
        )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(r.text)

    # The first event must be ``meta``.
    assert events[0]["event"] == "meta"
    assert events[0]["data"]["streaming_mode"] == "pseudo"
    assert events[0]["data"]["session_id"] == "sess_test"

    # The last event must be ``done`` with the full message.
    assert events[-1]["event"] == "done"
    done_msg = events[-1]["data"]["message"]
    assert done_msg["text"].startswith("First short answer")
    assert done_msg["agent_id"] == "test-agent"
    assert done_msg["session_id"] == "sess_test"
    assert done_msg["metadata"]["echoed_from"] == "hello"

    # In between, we must see at least one ``chunk``.
    chunk_events = [e for e in events if e["event"] == "chunk"]
    assert len(chunk_events) >= 1
    # Chunks carry "delta" and "index".
    for ce in chunk_events:
        assert "delta" in ce["data"]
        assert isinstance(ce["data"]["index"], int)


def test_stream_errors_become_error_event():
    def _explode(gw, msg):
        raise RuntimeError("upstream LLM unreachable")
    app = _build_app(handler=_explode)
    with TestClient(app) as client:
        _force_pseudo(app)
        r = client.post(
            "/http/message/stream",
            json={"channel": "http", "user_id": "curro", "text": "x"},
        )
    assert r.status_code == 200
    events = _parse_sse(r.text)
    # We still get a meta event first…
    assert events[0]["event"] == "meta"
    # …and an error somewhere after.
    error_events = [e for e in events if e["event"] == "error"]
    assert len(error_events) == 1
    assert "upstream LLM unreachable" in error_events[0]["data"]["error"]
    # No ``done`` after an error.
    assert all(e["event"] != "done" for e in events)


def test_stream_concatenated_chunks_match_full_text():
    """The streaming UX is purely a render-pacing optimisation;
    the chunks concatenated MUST equal the final text the
    ``done`` event reports, modulo whitespace. A client that
    builds the UI by appending deltas should land on the
    same string as one that ignores chunks and waits for
    ``done``."""
    app = _build_app(handler=_echo_handler)
    with TestClient(app) as client:
        _force_pseudo(app)
        r = client.post(
            "/http/message/stream",
            json={"channel": "http", "user_id": "curro", "text": "hi"},
        )
    events = _parse_sse(r.text)
    chunks = [e["data"]["delta"] for e in events if e["event"] == "chunk"]
    done = [e["data"]["message"]["text"] for e in events if e["event"] == "done"]
    assert len(done) == 1
    # Join chunks with the same separator the splitter
    # introduces (paragraph + sentence boundaries). For our
    # deterministic test handler with no \n\n the chunks are
    # sentences; we tolerate inter-chunk single spaces.
    rejoined = " ".join(chunks).replace("  ", " ").strip()
    final = done[0].strip()
    # Normalise: collapse whitespace.
    def _norm(s: str) -> str:
        return " ".join(s.split())
    assert _norm(rejoined) == _norm(final)


def test_stream_meta_event_reflects_input_user_id():
    app = _build_app(handler=_echo_handler)
    with TestClient(app) as client:
        _force_pseudo(app)
        r = client.post(
            "/http/message/stream",
            json={"channel": "http", "user_id": "alice@lab", "text": "x"},
        )
    events = _parse_sse(r.text)
    assert events[0]["data"]["user_id"] == "alice@lab"


# ------------------------------------------------------------------
# H1.5 — native streaming path
# ------------------------------------------------------------------


class _FakeStreamingRuntime:
    """Stand-in for AgentRuntime that supports streaming.

    The runtime is monkey-patched onto the live gateway
    after app startup so the H1.5 endpoint detects
    ``supports_streaming() == True`` and uses the native
    path.
    """

    def __init__(self, events):
        self._events = events

    def supports_streaming(self) -> bool:
        return True

    async def generate_reply_stream(self, **_kwargs):
        from openmiura.core.llm.types import LlmStreamEvent
        for ev in self._events:
            yield ev


def test_native_streaming_meta_event_declares_mode():
    """When the runtime supports streaming, the meta event
    must say ``streaming_mode = "native"``."""
    from openmiura.core.llm.types import ChatResponse, LlmStreamEvent

    app = _build_app(handler=_echo_handler)
    fake_runtime = _FakeStreamingRuntime([
        LlmStreamEvent.make_delta("Hello"),
        LlmStreamEvent.make_done(ChatResponse(content="Hello", tool_calls=[], usage=None)),
    ])
    with TestClient(app) as client:
        # Override the runtime AFTER app startup so the
        # capability check returns True.
        app.state.gw.runtime = fake_runtime
        r = client.post(
            "/http/message/stream",
            json={"channel": "http", "user_id": "curro", "text": "hi"},
        )
    assert r.status_code == 200
    events = _parse_sse(r.text)
    assert events[0]["event"] == "meta"
    assert events[0]["data"]["streaming_mode"] == "native"


def test_native_streaming_forwards_deltas_and_tool_events():
    """Native path emits ``chunk`` events for deltas plus
    ``tool_call`` and ``tool_result`` events between tool
    rounds."""
    from openmiura.core.llm.types import (
        ChatResponse,
        LlmStreamEvent,
        ToolCall,
        ToolResult,
    )

    app = _build_app(handler=_echo_handler)
    fake_runtime = _FakeStreamingRuntime([
        LlmStreamEvent.make_delta("Let me check."),
        LlmStreamEvent.make_tool_call(ToolCall(name="lookup", arguments={"q": "x"}, id="c1")),
        LlmStreamEvent.make_tool_result(ToolResult(name="lookup", output="x=42", call_id="c1")),
        LlmStreamEvent.make_delta(" The answer is 42."),
        LlmStreamEvent.make_usage({"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8}),
        LlmStreamEvent.make_done(ChatResponse(
            content="Let me check. The answer is 42.",
            tool_calls=[],
            usage={"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
        )),
    ])
    with TestClient(app) as client:
        app.state.gw.runtime = fake_runtime
        r = client.post(
            "/http/message/stream",
            json={"channel": "http", "user_id": "curro", "text": "hi"},
        )
    events = _parse_sse(r.text)
    kinds = [e["event"] for e in events]

    assert kinds[0] == "meta"
    assert "chunk" in kinds
    assert "tool_call" in kinds
    assert "tool_result" in kinds
    assert "usage" in kinds
    assert kinds[-1] == "done"

    # The tool_call event carries the name + arguments.
    tc_evs = [e for e in events if e["event"] == "tool_call"]
    assert len(tc_evs) == 1
    assert tc_evs[0]["data"]["name"] == "lookup"
    assert tc_evs[0]["data"]["arguments"] == {"q": "x"}

    # The tool_result event carries the output + call_id.
    tr_evs = [e for e in events if e["event"] == "tool_result"]
    assert len(tr_evs) == 1
    assert tr_evs[0]["data"]["name"] == "lookup"
    assert tr_evs[0]["data"]["output"] == "x=42"
    assert tr_evs[0]["data"]["call_id"] == "c1"

    # The final done event carries an OutboundMessage with
    # the consolidated text.
    done = [e for e in events if e["event"] == "done"][0]
    assert "answer is 42" in done["data"]["message"]["text"]


def test_native_streaming_falls_back_to_pseudo_when_runtime_lacks_capability():
    """If the runtime doesn't expose supports_streaming or
    returns False, the endpoint silently falls back to the
    pseudo path — same behaviour as before H1.5."""
    app = _build_app(handler=_echo_handler)
    with TestClient(app) as client:
        # The live runtime built by the test app uses Ollama
        # by default (which DOES support streaming after
        # H1.1), so we have to override it with something
        # that doesn't.
        class _SyncRuntime:
            def supports_streaming(self):
                return False
        app.state.gw.runtime = _SyncRuntime()
        r = client.post(
            "/http/message/stream",
            json={"channel": "http", "user_id": "curro", "text": "hi"},
        )
    events = _parse_sse(r.text)
    assert events[0]["data"]["streaming_mode"] == "pseudo"
