"""Tests for H3.3a — Attachment dataclass + Ollama image plumbing.

H3.3a opens the multi-modal arc:

  - ``Attachment`` lives in ``openmiura.core.llm.types`` and
    carries a kind tag, MIME type, base64 payload, and an
    optional precomputed SHA-256.
  - ``attachment_from_dict`` parses the wire shape (HTTP /
    audit) into the dataclass with permissive validation.
  - ``attachment_sha256`` computes the hex digest of the raw
    bytes (post-base64), used by the audit layer.
  - ``_ollama_payload_messages`` translates openMiura messages
    into Ollama's wire format: ``attachments`` is stripped,
    image bytes become the ``images: [base64, ...]`` field.

Both ``OllamaClient.chat`` and ``OllamaClient.chat_stream``
must pass the translated payload so the wire actually carries
the images. We pin both paths with ``httpx.MockTransport``.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from typing import Any, Callable

import httpx
import pytest

from openmiura.core.llm import (
    Attachment,
    OllamaClient,
    attachment_from_dict,
    attachment_sha256,
)
from openmiura.core.llm.ollama import _ollama_payload_messages


# Tiny 1x1 transparent PNG, base64-encoded — small enough to
# inline, valid enough to round-trip through base64+hash.
_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


# ------------------------------------------------------------------
# Attachment dataclass shape
# ------------------------------------------------------------------


def test_attachment_holds_image_payload() -> None:
    a = Attachment(kind="image", media_type="image/png", data_b64=_PNG_B64)
    assert a.kind == "image"
    assert a.media_type == "image/png"
    assert a.data_b64 == _PNG_B64
    assert a.sha256 is None  # optional, defaults to None


def test_attachment_accepts_precomputed_sha256() -> None:
    a = Attachment(
        kind="image",
        media_type="image/jpeg",
        data_b64="abc",
        sha256="dead" * 16,
    )
    assert a.sha256 == "dead" * 16


# ------------------------------------------------------------------
# attachment_from_dict
# ------------------------------------------------------------------


def test_attachment_from_dict_accepts_well_formed() -> None:
    a = attachment_from_dict({
        "kind": "image",
        "media_type": "image/png",
        "data_b64": _PNG_B64,
    })
    assert a is not None
    assert a.kind == "image"
    assert a.media_type == "image/png"
    assert a.data_b64 == _PNG_B64


def test_attachment_from_dict_rejects_non_image_kind() -> None:
    """``kind`` is currently restricted to 'image'. Audio +
    binary types will arrive in a later H3 slice."""
    assert attachment_from_dict({
        "kind": "audio",
        "media_type": "audio/mpeg",
        "data_b64": "abc",
    }) is None


def test_attachment_from_dict_rejects_non_image_media_type() -> None:
    """The MIME type must start with ``image/`` — a sanity
    check so a malformed payload that declares ``kind: image``
    but ships ``application/octet-stream`` is dropped."""
    assert attachment_from_dict({
        "kind": "image",
        "media_type": "application/octet-stream",
        "data_b64": "abc",
    }) is None


def test_attachment_from_dict_rejects_empty_data() -> None:
    assert attachment_from_dict({
        "kind": "image",
        "media_type": "image/png",
        "data_b64": "",
    }) is None


def test_attachment_from_dict_returns_none_for_non_dict() -> None:
    for bad in (None, "string", 42, ["list"]):
        assert attachment_from_dict(bad) is None


def test_attachment_from_dict_normalises_kind_case() -> None:
    """``kind`` is matched case-insensitively so payloads from
    upstream UIs that uppercase don't get silently dropped."""
    a = attachment_from_dict({
        "kind": "IMAGE",
        "media_type": "image/png",
        "data_b64": _PNG_B64,
    })
    assert a is not None and a.kind == "image"


def test_attachment_from_dict_preserves_optional_sha256() -> None:
    a = attachment_from_dict({
        "kind": "image",
        "media_type": "image/png",
        "data_b64": _PNG_B64,
        "sha256": "deadbeef",
    })
    assert a is not None
    assert a.sha256 == "deadbeef"


# ------------------------------------------------------------------
# attachment_sha256
# ------------------------------------------------------------------


def test_attachment_sha256_matches_manual_digest() -> None:
    a = Attachment(kind="image", media_type="image/png", data_b64=_PNG_B64)
    expected = hashlib.sha256(base64.b64decode(_PNG_B64)).hexdigest()
    assert attachment_sha256(a) == expected


def test_attachment_sha256_is_deterministic() -> None:
    a = Attachment(kind="image", media_type="image/png", data_b64=_PNG_B64)
    assert attachment_sha256(a) == attachment_sha256(a)


# ------------------------------------------------------------------
# _ollama_payload_messages — message translator
# ------------------------------------------------------------------


def test_ollama_translator_is_identity_for_text_only_messages() -> None:
    msgs = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]
    out = _ollama_payload_messages(msgs)
    assert out == msgs
    # Same objects — no copy needed for text-only messages.
    # (Identity is an implementation detail; the contract is
    # only "equal".)


def test_ollama_translator_lifts_image_attachments_to_images_field() -> None:
    msgs = [
        {
            "role": "user",
            "content": "what is in this?",
            "attachments": [
                {"kind": "image", "media_type": "image/png", "data_b64": _PNG_B64},
            ],
        }
    ]
    out = _ollama_payload_messages(msgs)
    assert len(out) == 1
    assert "attachments" not in out[0]
    assert out[0]["images"] == [_PNG_B64]
    assert out[0]["role"] == "user"
    assert out[0]["content"] == "what is in this?"


def test_ollama_translator_accepts_attachment_dataclass_instances() -> None:
    """Callers may pass already-validated Attachment objects
    instead of dicts. Both shapes must work."""
    att = Attachment(kind="image", media_type="image/png", data_b64=_PNG_B64)
    msgs = [{"role": "user", "content": "?", "attachments": [att]}]
    out = _ollama_payload_messages(msgs)
    assert out[0]["images"] == [_PNG_B64]


def test_ollama_translator_concatenates_images_when_preexisting() -> None:
    """If the caller already set an ``images`` field (e.g.
    integration tests bypassing the dataclass), the
    translator appends rather than overwriting."""
    msgs = [{
        "role": "user",
        "content": "?",
        "images": ["preset-image-b64"],
        "attachments": [
            {"kind": "image", "media_type": "image/png", "data_b64": _PNG_B64},
        ],
    }]
    out = _ollama_payload_messages(msgs)
    assert out[0]["images"] == ["preset-image-b64", _PNG_B64]


def test_ollama_translator_handles_multiple_images_per_message() -> None:
    msgs = [{
        "role": "user",
        "content": "compare these",
        "attachments": [
            {"kind": "image", "media_type": "image/png", "data_b64": "AAA="},
            {"kind": "image", "media_type": "image/jpeg", "data_b64": "BBB="},
        ],
    }]
    out = _ollama_payload_messages(msgs)
    assert out[0]["images"] == ["AAA=", "BBB="]


def test_ollama_translator_silently_drops_non_image_attachments() -> None:
    """Audio / unknown kinds aren't supported here yet — they
    must not raise but also must not appear in the wire
    payload."""
    msgs = [{
        "role": "user",
        "content": "?",
        "attachments": [
            {"kind": "audio", "media_type": "audio/mpeg", "data_b64": "AAA="},
        ],
    }]
    out = _ollama_payload_messages(msgs)
    assert "images" not in out[0]
    assert "attachments" not in out[0]


def test_ollama_translator_drops_empty_attachments_list() -> None:
    msgs = [{"role": "user", "content": "?", "attachments": []}]
    out = _ollama_payload_messages(msgs)
    assert "attachments" not in out[0]
    assert "images" not in out[0]


def test_ollama_translator_preserves_non_dict_entries() -> None:
    """A bug elsewhere could put a non-dict in the message
    list; the translator must pass it through unmodified
    rather than dropping it."""
    msgs = [{"role": "user", "content": "ok"}, "weird sentinel"]
    out = _ollama_payload_messages(msgs)  # type: ignore[arg-type]
    assert out[1] == "weird sentinel"


# ------------------------------------------------------------------
# End-to-end: chat() and chat_stream() send images to the wire
# ------------------------------------------------------------------


def _capture_request_body(captured: list[dict[str, Any]]) -> Callable[[httpx.Request], httpx.Response]:
    """MockTransport handler that stashes the request JSON
    body into ``captured`` and returns a minimal done
    response."""
    def _handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content.decode("utf-8")))
        body = json.dumps({
            "message": {"content": "ok"},
            "done": True,
            "prompt_eval_count": 1,
            "eval_count": 1,
        }) + "\n"
        return httpx.Response(200, content=body.encode("utf-8"))
    return _handler


def test_chat_sends_images_to_wire_when_attachments_present() -> None:
    """The sync ``chat()`` path must translate attachments
    into Ollama's ``images`` field on the outbound message."""
    captured: list[dict[str, Any]] = []
    transport = httpx.MockTransport(_capture_request_body(captured))
    client = OllamaClient(
        base_url="http://test.local",
        model="llama3",
        transport=transport,
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
    assert msg["images"] == [_PNG_B64]
    assert "attachments" not in msg


def test_chat_stream_sends_images_to_wire_when_attachments_present() -> None:
    """Same contract for the async streaming path."""
    captured: list[dict[str, Any]] = []
    transport = httpx.MockTransport(_capture_request_body(captured))
    client = OllamaClient(
        base_url="http://test.local",
        model="llama3",
        transport=transport,
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
    assert len(captured) == 1
    msg = captured[0]["messages"][0]
    assert msg["images"] == [_PNG_B64]
    assert "attachments" not in msg


def test_chat_does_not_set_images_field_when_no_attachments() -> None:
    """Text-only messages must NOT grow an ``images`` field
    so the wire payload stays minimal for non-multimodal
    requests."""
    captured: list[dict[str, Any]] = []
    transport = httpx.MockTransport(_capture_request_body(captured))
    client = OllamaClient(
        base_url="http://test.local",
        model="llama3",
        transport=transport,
    )
    client.chat([{"role": "user", "content": "hello"}])
    msg = captured[0]["messages"][0]
    assert "images" not in msg
    assert "attachments" not in msg


# ------------------------------------------------------------------
# Re-exports
# ------------------------------------------------------------------


def test_attachment_symbols_are_re_exported_from_package() -> None:
    """``Attachment`` and the two helpers must be importable
    directly from ``openmiura.core.llm`` so the call sites
    in audit / HTTP layers don't have to dig into
    submodules."""
    from openmiura.core.llm import (
        Attachment as _Att,
        AttachmentKind as _Kind,
        attachment_from_dict as _from,
        attachment_sha256 as _hash,
    )
    assert _Att is Attachment
    assert _from is attachment_from_dict
    assert _hash is attachment_sha256
    # AttachmentKind is a Literal alias; can't compare with `is`,
    # but importable existence is the contract.
    assert _Kind is not None
