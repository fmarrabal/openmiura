"""Tests for H3.3b — OpenAI + Anthropic image translation.

H3.3a shipped the canonical ``Attachment`` dataclass and
wired Ollama (whose wire format is the simplest — a single
``images: [base64]`` field per message). This slice translates
the same dataclass into the two block-shape providers:

  - **OpenAI** wants ``content`` promoted to a list with
    ``{type: 'image_url', image_url: {url: 'data:<mime>;base64,<data>'}}``
    blocks per image.
  - **Anthropic** wants ``{type: 'image', source: {type:
    'base64', media_type: '<mime>', data: '<data>'}}`` blocks.

Both providers must:

  - strip the internal ``attachments`` field from the wire
    payload,
  - put the text block FIRST so the prompt reads correctly,
  - silently drop non-image kinds (audio reserved for later
    H3 slice),
  - leave text-only messages identical (no payload bloat).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Callable

import httpx
import pytest

from openmiura.core.llm import (
    AnthropicClient,
    Attachment,
    OpenAICompatibleClient,
)
from openmiura.core.llm.openai_compat import _openai_payload_messages


_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)
_JPG_B64 = "/9j/4AAQSkZJRgABAQEAYABgAAD//gA="


# ==================================================================
# OpenAI translator
# ==================================================================


def test_openai_translator_is_identity_for_text_only_messages() -> None:
    msgs = [
        {"role": "system", "content": "you are helpful"},
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]
    out = _openai_payload_messages(msgs)
    assert out == msgs


def test_openai_translator_builds_text_then_image_blocks() -> None:
    msgs = [{
        "role": "user",
        "content": "what is in this?",
        "attachments": [
            {"kind": "image", "media_type": "image/png", "data_b64": _PNG_B64},
        ],
    }]
    out = _openai_payload_messages(msgs)
    assert "attachments" not in out[0]
    content = out[0]["content"]
    assert isinstance(content, list)
    assert content[0] == {"type": "text", "text": "what is in this?"}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"] == f"data:image/png;base64,{_PNG_B64}"


def test_openai_translator_drops_text_block_when_content_empty() -> None:
    """An attachment-only message (e.g. drag-drop without
    typing) should NOT prepend a blank text block — OpenAI
    treats empty text as a validation error on some
    deployments."""
    msgs = [{
        "role": "user",
        "content": "",
        "attachments": [
            {"kind": "image", "media_type": "image/png", "data_b64": _PNG_B64},
        ],
    }]
    out = _openai_payload_messages(msgs)
    content = out[0]["content"]
    assert isinstance(content, list)
    assert all(b.get("type") != "text" for b in content)
    assert content[0]["type"] == "image_url"


def test_openai_translator_emits_multiple_image_blocks() -> None:
    msgs = [{
        "role": "user",
        "content": "compare",
        "attachments": [
            {"kind": "image", "media_type": "image/png", "data_b64": _PNG_B64},
            {"kind": "image", "media_type": "image/jpeg", "data_b64": _JPG_B64},
        ],
    }]
    out = _openai_payload_messages(msgs)
    images = [b for b in out[0]["content"] if b["type"] == "image_url"]
    assert len(images) == 2
    assert images[0]["image_url"]["url"] == f"data:image/png;base64,{_PNG_B64}"
    assert images[1]["image_url"]["url"] == f"data:image/jpeg;base64,{_JPG_B64}"


def test_openai_translator_accepts_attachment_dataclass() -> None:
    att = Attachment(kind="image", media_type="image/png", data_b64=_PNG_B64)
    msgs = [{"role": "user", "content": "?", "attachments": [att]}]
    out = _openai_payload_messages(msgs)
    block = [b for b in out[0]["content"] if b["type"] == "image_url"][0]
    assert block["image_url"]["url"] == f"data:image/png;base64,{_PNG_B64}"


def test_openai_translator_drops_non_image_kinds() -> None:
    msgs = [{
        "role": "user",
        "content": "?",
        "attachments": [
            {"kind": "audio", "media_type": "audio/mpeg", "data_b64": "AAA="},
        ],
    }]
    out = _openai_payload_messages(msgs)
    # No image to lift → no list promotion needed.
    assert "attachments" not in out[0]
    # Content stays as the original string (no images to add).
    assert out[0].get("content") == "?"


def test_openai_translator_drops_image_with_bad_media_type() -> None:
    """If somehow the kind says 'image' but the media_type
    is wrong, drop it silently (defence in depth — the audit
    layer would have caught it earlier)."""
    msgs = [{
        "role": "user",
        "content": "?",
        "attachments": [
            {"kind": "image", "media_type": "application/pdf", "data_b64": "AAA="},
        ],
    }]
    out = _openai_payload_messages(msgs)
    assert out[0].get("content") == "?"
    assert "attachments" not in out[0]


def test_openai_translator_preserves_existing_block_list_content() -> None:
    """If the caller already provided ``content`` as a list
    of blocks (advanced use), extend it with image blocks
    rather than overwriting."""
    msgs = [{
        "role": "user",
        "content": [{"type": "text", "text": "look:"}],
        "attachments": [
            {"kind": "image", "media_type": "image/png", "data_b64": _PNG_B64},
        ],
    }]
    out = _openai_payload_messages(msgs)
    content = out[0]["content"]
    assert content[0] == {"type": "text", "text": "look:"}
    assert content[1]["type"] == "image_url"


# ==================================================================
# OpenAI end-to-end: chat + chat_stream send blocks to the wire
# ==================================================================


def _openai_capture(captured: list[dict[str, Any]],
                    *, stream: bool = False) -> Callable[[httpx.Request], httpx.Response]:
    """MockTransport handler that stashes the OpenAI request
    JSON and returns a minimal valid completion."""
    def _handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content.decode("utf-8")))
        if stream:
            sse_lines = [
                'data: ' + json.dumps({"choices": [{"delta": {"content": "ok"}, "index": 0}]}),
                'data: ' + json.dumps({"choices": [{"delta": {}, "finish_reason": "stop", "index": 0}],
                                       "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}),
                'data: [DONE]',
                '',
            ]
            body = ('\n'.join(sse_lines) + '\n').encode("utf-8")
            return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})
        body = json.dumps({
            "choices": [{
                "message": {"role": "assistant", "content": "ok"},
                "finish_reason": "stop",
                "index": 0,
            }],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })
        return httpx.Response(200, content=body.encode("utf-8"))
    return _handler


def test_openai_chat_sends_image_blocks_to_wire(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    captured: list[dict[str, Any]] = []
    client = OpenAICompatibleClient(
        base_url="https://api.test/v1",
        model="gpt-4o",
        api_key_env_var="OPENAI_API_KEY",
        transport=httpx.MockTransport(_openai_capture(captured)),
    )
    resp = client.chat([{
        "role": "user",
        "content": "what is in this?",
        "attachments": [
            {"kind": "image", "media_type": "image/png", "data_b64": _PNG_B64},
        ],
    }])
    assert resp.content == "ok"
    assert len(captured) == 1
    msg = captured[0]["messages"][0]
    assert "attachments" not in msg
    assert isinstance(msg["content"], list)
    assert any(b.get("type") == "image_url" for b in msg["content"])


def test_openai_chat_stream_sends_image_blocks_to_wire(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    captured: list[dict[str, Any]] = []
    client = OpenAICompatibleClient(
        base_url="https://api.test/v1",
        model="gpt-4o",
        api_key_env_var="OPENAI_API_KEY",
        transport=httpx.MockTransport(_openai_capture(captured, stream=True)),
    )

    async def _run() -> None:
        async for _ in client.chat_stream([{
            "role": "user",
            "content": "?",
            "attachments": [
                {"kind": "image", "media_type": "image/png", "data_b64": _PNG_B64},
            ],
        }]):
            pass
    asyncio.run(_run())
    msg = captured[0]["messages"][0]
    assert any(b.get("type") == "image_url" for b in msg["content"])
    assert "attachments" not in msg


# ==================================================================
# Anthropic — _convert_messages handles attachments
# ==================================================================


def _anthropic_client(monkeypatch: pytest.MonkeyPatch,
                      handler: Callable[[httpx.Request], httpx.Response] | None = None) -> AnthropicClient:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    transport = httpx.MockTransport(handler) if handler else None
    return AnthropicClient(
        base_url="https://api.test/v1",
        model="claude-sonnet-4-5",
        api_key_env_var="ANTHROPIC_API_KEY",
        transport=transport,
    )


def test_anthropic_convert_messages_emits_image_source_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Anthropic's image content block uses ``{type: 'image',
    source: {type: 'base64', media_type, data}}`` — pin it."""
    client = _anthropic_client(monkeypatch)
    _, msgs = client._convert_messages([{
        "role": "user",
        "content": "what is in this?",
        "attachments": [
            {"kind": "image", "media_type": "image/png", "data_b64": _PNG_B64},
        ],
    }])
    assert len(msgs) == 1
    blocks = msgs[0]["content"]
    assert blocks[0] == {"type": "text", "text": "what is in this?"}
    assert blocks[1] == {
        "type": "image",
        "source": {
            "type":       "base64",
            "media_type": "image/png",
            "data":       _PNG_B64,
        },
    }


def test_anthropic_convert_messages_handles_attachment_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drag-drop without typing — empty content, only the
    image. The text block must be omitted, not blank."""
    client = _anthropic_client(monkeypatch)
    _, msgs = client._convert_messages([{
        "role": "user",
        "content": "",
        "attachments": [
            {"kind": "image", "media_type": "image/jpeg", "data_b64": _JPG_B64},
        ],
    }])
    blocks = msgs[0]["content"]
    assert all(b.get("type") != "text" for b in blocks)
    assert blocks[0]["type"] == "image"
    assert blocks[0]["source"]["media_type"] == "image/jpeg"


def test_anthropic_convert_messages_drops_non_image_kinds(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _anthropic_client(monkeypatch)
    _, msgs = client._convert_messages([{
        "role": "user",
        "content": "?",
        "attachments": [
            {"kind": "audio", "media_type": "audio/mpeg", "data_b64": "AAA="},
        ],
    }])
    # No image → blocks list contains only the text block.
    blocks = msgs[0]["content"]
    assert blocks == [{"type": "text", "text": "?"}]


def test_anthropic_convert_messages_accepts_attachment_dataclass(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _anthropic_client(monkeypatch)
    att = Attachment(kind="image", media_type="image/png", data_b64=_PNG_B64)
    _, msgs = client._convert_messages([{
        "role": "user",
        "content": "?",
        "attachments": [att],
    }])
    blocks = msgs[0]["content"]
    image_blocks = [b for b in blocks if b.get("type") == "image"]
    assert len(image_blocks) == 1
    assert image_blocks[0]["source"]["data"] == _PNG_B64


def test_anthropic_convert_messages_emits_multiple_images(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _anthropic_client(monkeypatch)
    _, msgs = client._convert_messages([{
        "role": "user",
        "content": "compare",
        "attachments": [
            {"kind": "image", "media_type": "image/png", "data_b64": _PNG_B64},
            {"kind": "image", "media_type": "image/jpeg", "data_b64": _JPG_B64},
        ],
    }])
    images = [b for b in msgs[0]["content"] if b.get("type") == "image"]
    assert len(images) == 2
    assert images[0]["source"]["media_type"] == "image/png"
    assert images[1]["source"]["media_type"] == "image/jpeg"


def test_anthropic_convert_messages_strips_attachments_key(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _anthropic_client(monkeypatch)
    _, msgs = client._convert_messages([{
        "role": "user",
        "content": "?",
        "attachments": [
            {"kind": "image", "media_type": "image/png", "data_b64": _PNG_B64},
        ],
    }])
    # The outbound message must not carry the internal key.
    assert "attachments" not in msgs[0]


def test_anthropic_convert_messages_text_only_is_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _anthropic_client(monkeypatch)
    _, msgs = client._convert_messages([
        {"role": "system", "content": "be helpful"},
        {"role": "user", "content": "hi"},
    ])
    # System extracted; user stays as plain string content.
    assert msgs == [{"role": "user", "content": "hi"}]


# ==================================================================
# Anthropic end-to-end: chat sends image blocks to the wire
# ==================================================================


def _anthropic_capture(captured: list[dict[str, Any]]) -> Callable[[httpx.Request], httpx.Response]:
    def _handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content.decode("utf-8")))
        body = json.dumps({
            "id": "msg_01",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "ok"}],
            "model": "claude-sonnet-4-5",
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 1, "output_tokens": 1},
        })
        return httpx.Response(200, content=body.encode("utf-8"))
    return _handler


def test_anthropic_chat_sends_image_blocks_to_wire(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict[str, Any]] = []
    client = _anthropic_client(monkeypatch, _anthropic_capture(captured))
    resp = client.chat([{
        "role": "user",
        "content": "what is in this?",
        "attachments": [
            {"kind": "image", "media_type": "image/png", "data_b64": _PNG_B64},
        ],
    }])
    assert resp.content == "ok"
    msg = captured[0]["messages"][0]
    assert "attachments" not in msg
    image_blocks = [b for b in msg["content"] if b.get("type") == "image"]
    assert len(image_blocks) == 1
    assert image_blocks[0]["source"]["data"] == _PNG_B64
