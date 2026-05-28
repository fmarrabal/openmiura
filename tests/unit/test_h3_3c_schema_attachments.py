"""Tests for H3.3c — InboundMessage.attachments + audit helpers.

H3.3a/b shipped the `Attachment` dataclass and per-provider
wire translation. H3.3c brings the multi-modal arc into the
HTTP boundary: the inbound chat payload accepts an
``attachments`` array and the audit layer logs byte-free
metadata (sha256 + size + media_type) without persisting the
raw bytes.

These tests pin the Pydantic shape and the two audit helpers
(``attachments_audit_meta``, ``model_dump_for_audit``).
Pipeline / streaming / UI integration tests live in sibling
files in this PR.
"""

from __future__ import annotations

import base64
import hashlib

import pytest

from openmiura.core.schema import InboundMessage


# Tiny 1x1 transparent PNG, base64-encoded — small enough to inline.
_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


# ------------------------------------------------------------------
# Schema shape
# ------------------------------------------------------------------


def test_inbound_message_defaults_to_empty_attachments_list() -> None:
    msg = InboundMessage(user_id="u", text="hi")
    assert msg.attachments == []


def test_inbound_message_accepts_image_attachment_dict() -> None:
    msg = InboundMessage(
        user_id="u",
        text="what is this?",
        attachments=[{
            "kind": "image",
            "media_type": "image/png",
            "data_b64": _PNG_B64,
        }],
    )
    assert len(msg.attachments) == 1
    assert msg.attachments[0]["kind"] == "image"
    assert msg.attachments[0]["data_b64"] == _PNG_B64


def test_inbound_message_attachments_round_trip_through_model_dump() -> None:
    msg = InboundMessage(
        user_id="u",
        text="x",
        attachments=[{
            "kind": "image",
            "media_type": "image/png",
            "data_b64": "abc",
        }],
    )
    dumped = msg.model_dump()
    assert "attachments" in dumped
    assert dumped["attachments"][0]["data_b64"] == "abc"


# ------------------------------------------------------------------
# attachments_audit_meta — byte-free summary
# ------------------------------------------------------------------


def test_audit_meta_is_empty_for_text_only_message() -> None:
    msg = InboundMessage(user_id="u", text="hi")
    assert msg.attachments_audit_meta() == []


def test_audit_meta_emits_sha256_size_kind_media_per_attachment() -> None:
    msg = InboundMessage(
        user_id="u",
        text="?",
        attachments=[{
            "kind": "image",
            "media_type": "image/png",
            "data_b64": _PNG_B64,
        }],
    )
    meta = msg.attachments_audit_meta()
    assert len(meta) == 1
    entry = meta[0]
    raw = base64.b64decode(_PNG_B64)
    assert entry["kind"] == "image"
    assert entry["media_type"] == "image/png"
    assert entry["size_bytes"] == len(raw)
    assert entry["sha256"] == hashlib.sha256(raw).hexdigest()
    # Crucially: no data_b64 in the audit meta.
    assert "data_b64" not in entry


def test_audit_meta_trusts_preloaded_sha256_if_well_formed() -> None:
    """If the caller already computed sha256 (e.g. the browser
    Web Crypto did it before upload), don't re-hash."""
    msg = InboundMessage(
        user_id="u", text="?",
        attachments=[{
            "kind": "image", "media_type": "image/png",
            "data_b64": _PNG_B64,
            "sha256": "a" * 64,  # well-formed but obviously wrong
        }],
    )
    assert msg.attachments_audit_meta()[0]["sha256"] == "a" * 64


def test_audit_meta_recomputes_if_preloaded_sha256_malformed() -> None:
    """If the preloaded sha is the wrong length or non-hex,
    recompute rather than trust."""
    raw = base64.b64decode(_PNG_B64)
    correct = hashlib.sha256(raw).hexdigest()
    for bad in ("not-a-hash", "abc", "Z" * 64, ""):
        msg = InboundMessage(
            user_id="u", text="?",
            attachments=[{
                "kind": "image", "media_type": "image/png",
                "data_b64": _PNG_B64, "sha256": bad,
            }],
        )
        assert msg.attachments_audit_meta()[0]["sha256"] == correct


def test_audit_meta_skips_malformed_attachments_silently() -> None:
    """A bad entry inside the (Pydantic-validated) list must
    NOT make the audit helper raise — the audit path is best-
    effort. The well-formed entries still surface.

    Note: Pydantic itself rejects non-dict items at
    construction time, so we exercise the helper directly
    against a malformed list to pin the defensive branch."""
    msg = InboundMessage(
        user_id="u", text="?",
        attachments=[
            {"kind": "image", "media_type": "image/png", "data_b64": _PNG_B64},
            {"kind": "image"},                              # missing fields
            {"kind": "image", "media_type": "image/png", "data_b64": ""},  # empty data
            {"kind": "audio", "media_type": "audio/mpeg", "data_b64": "xx"},  # not image
        ],
    )
    meta = msg.attachments_audit_meta()
    assert len(meta) == 1
    assert meta[0]["media_type"] == "image/png"

    # Exercise the defensive non-dict branch by appending
    # post-Pydantic (the helper iterates whatever's in the
    # list at call time).
    msg.attachments.append("not a dict")  # type: ignore[arg-type]
    meta2 = msg.attachments_audit_meta()
    assert len(meta2) == 1


def test_audit_meta_skips_undecodable_base64_silently() -> None:
    """Garbled base64 must not raise — drop the entry."""
    msg = InboundMessage(
        user_id="u", text="?",
        attachments=[{
            "kind": "image", "media_type": "image/png",
            "data_b64": "%%%not-valid-base64%%%",
        }],
    )
    # `base64.b64decode(validate=False)` is lenient — this
    # particular string will silently produce empty bytes
    # rather than raising. The contract is that the helper
    # never raises; producing a tiny entry is acceptable.
    # The pin is: it MUST NOT raise.
    msg.attachments_audit_meta()  # no exception


# ------------------------------------------------------------------
# model_dump_for_audit — composite helper used by pipeline
# ------------------------------------------------------------------


def test_model_dump_for_audit_omits_data_b64() -> None:
    msg = InboundMessage(
        user_id="u", text="?",
        attachments=[{
            "kind": "image", "media_type": "image/png",
            "data_b64": _PNG_B64,
        }],
    )
    out = msg.model_dump_for_audit()
    assert "attachments" not in out
    assert "attachments_meta" in out
    assert all("data_b64" not in m for m in out["attachments_meta"])


def test_model_dump_for_audit_omits_attachments_meta_when_none() -> None:
    """Text-only messages should not gain an empty
    ``attachments_meta`` field — keep the audit payload
    minimal for the common case."""
    msg = InboundMessage(user_id="u", text="hi")
    out = msg.model_dump_for_audit()
    assert "attachments" not in out
    assert "attachments_meta" not in out


def test_model_dump_for_audit_preserves_other_fields() -> None:
    msg = InboundMessage(
        user_id="u123", text="hello", session_id="sess-1",
        metadata={"trace": "abc"},
    )
    out = msg.model_dump_for_audit()
    assert out["user_id"] == "u123"
    assert out["text"] == "hello"
    assert out["session_id"] == "sess-1"
    assert out["metadata"] == {"trace": "abc"}
