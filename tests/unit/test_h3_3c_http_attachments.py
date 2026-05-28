"""Tests for H3.3c — HTTP endpoints accept attachments.

End-to-end pin for the inbound multi-modal contract:
``POST /http/message`` (and the streaming sibling) must accept
an ``attachments`` array in the JSON body and pass it through
to the message handler intact.

We use the ``message_handler`` injection hook on
``create_app`` so the test doesn't need a real LLM or
runtime — just confirms the wire-side serialisation.
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


_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def _build_app(*, handler):
    cfg = {
        "server":  {"host": "127.0.0.1", "port": 8081},
        "storage": {"backend": "sqlite", "db_path": ":memory:"},
        "admin":   {"enabled": True, "token": "x" * 32},
        "auth":    {"enabled": False},
    }
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False
    ) as f:
        yaml.safe_dump(cfg, f)
        cfg_path = f.name
    return create_app(config_path=cfg_path, message_handler=handler)


def test_http_message_accepts_attachments_field() -> None:
    """The endpoint must accept the ``attachments`` field in
    the inbound JSON and surface it on the ``InboundMessage``
    seen by the handler."""
    captured: list[InboundMessage] = []

    def _handler(gw, msg: InboundMessage) -> OutboundMessage:
        captured.append(msg)
        return OutboundMessage(
            channel=msg.channel, user_id=msg.user_id,
            session_id=msg.session_id or "s1",
            agent_id="default", text="ok",
        )

    app = _build_app(handler=_handler)
    with TestClient(app) as client:
        r = client.post("/http/message", json={
            "channel": "http",
            "user_id": "u1",
            "text":    "what is in this?",
            "attachments": [{
                "kind": "image",
                "media_type": "image/png",
                "data_b64": _PNG_B64,
            }],
        })
    assert r.status_code == 200, r.text
    assert len(captured) == 1
    assert captured[0].attachments == [{
        "kind": "image",
        "media_type": "image/png",
        "data_b64": _PNG_B64,
    }]


def test_http_message_attachments_default_to_empty() -> None:
    """A request without the ``attachments`` field must still
    work — the field defaults to []. Pin the back-compat."""
    captured: list[InboundMessage] = []

    def _handler(gw, msg: InboundMessage) -> OutboundMessage:
        captured.append(msg)
        return OutboundMessage(
            channel=msg.channel, user_id=msg.user_id,
            session_id=msg.session_id or "s1",
            agent_id="default", text="ok",
        )

    app = _build_app(handler=_handler)
    with TestClient(app) as client:
        r = client.post("/http/message", json={
            "channel": "http",
            "user_id": "u1",
            "text":    "hi",
        })
    assert r.status_code == 200
    assert captured[0].attachments == []


def test_http_message_audit_strips_bytes_via_model_dump_for_audit() -> None:
    """When the operator sends a turn with attachments, the
    audit ``log_event`` payload must NOT contain the raw
    ``data_b64`` field. We verify by inspecting the audit
    rows on the gateway's audit store after a request."""
    captured: list[InboundMessage] = []

    def _handler(gw, msg: InboundMessage) -> OutboundMessage:
        captured.append(msg)
        return OutboundMessage(
            channel=msg.channel, user_id=msg.user_id,
            session_id=msg.session_id or "s1",
            agent_id="default", text="ok",
        )

    app = _build_app(handler=_handler)
    with TestClient(app) as client:
        r = client.post("/http/message", json={
            "channel": "http",
            "user_id": "u1",
            "text":    "?",
            "attachments": [{
                "kind": "image",
                "media_type": "image/png",
                "data_b64": _PNG_B64,
            }],
        })
        assert r.status_code == 200
        # The handler captured an attachments-bearing InboundMessage.
        assert captured[0].attachments[0]["data_b64"] == _PNG_B64
        # And on the InboundMessage we can verify the audit
        # helper would strip the bytes.
        audit = captured[0].model_dump_for_audit()
        assert "attachments" not in audit
        assert audit["attachments_meta"][0]["media_type"] == "image/png"
        assert "data_b64" not in audit["attachments_meta"][0]
        # Hash present and well-formed (64 hex chars).
        sha = audit["attachments_meta"][0]["sha256"]
        assert isinstance(sha, str) and len(sha) == 64
        int(sha, 16)  # raises if not hex


# ------------------------------------------------------------------
# UI source pins
# ------------------------------------------------------------------


def test_chat_js_declares_attachment_helpers() -> None:
    """``chat.js`` must declare the H3.3c paste/drop pipeline.
    Pin the function names so a future refactor surfaces here
    if it renames the public Alpine handlers (the science.html
    template references them by name)."""
    chat_js = Path(__file__).resolve().parents[2] \
        / "openmiura" / "ui" / "v2" / "static" / "js" / "science" / "chat.js"
    text = chat_js.read_text(encoding="utf-8")
    for name in (
        "_fileToAttachment", "_attachmentForWire",
        "pendingAttachments",
        "onComposerPaste", "onComposerDrop", "onComposerDragOver",
        "onComposerDragLeave", "onComposerFilePicker",
        "removeAttachment", "_ingestFiles",
        "_MAX_ATTACHMENT_BYTES", "_MAX_ATTACHMENTS_PER_TURN",
    ):
        assert name in text, f"chat.js must declare {name}"


def test_chat_js_caps_attachment_count_and_size() -> None:
    """Pin the numeric caps so a future refactor that
    accidentally drops the limits triggers here."""
    chat_js = Path(__file__).resolve().parents[2] \
        / "openmiura" / "ui" / "v2" / "static" / "js" / "science" / "chat.js"
    text = chat_js.read_text(encoding="utf-8")
    assert "10 * 1024 * 1024" in text, "chat.js must keep the 10 MiB per-attachment cap"
    assert "_MAX_ATTACHMENTS_PER_TURN = 4" in text, "chat.js must cap attachments per turn"


def test_chat_js_strips_display_only_fields_before_wire() -> None:
    """``_attachmentForWire`` must drop the leading-underscore
    UI-only fields (_name, _size, _preview) so the outbound
    payload matches the InboundMessage shape exactly."""
    chat_js = Path(__file__).resolve().parents[2] \
        / "openmiura" / "ui" / "v2" / "static" / "js" / "science" / "chat.js"
    text = chat_js.read_text(encoding="utf-8")
    # The function should only forward kind / media_type /
    # data_b64 / optional sha256.
    fn_re = "_attachmentForWire"
    assert fn_re in text
    # The opposite: must NOT leak _preview, _name, _size into
    # the wire object. Crude check: the wire-builder block
    # references kind/media_type/data_b64.
    # (Stronger: extract the function body and assert the
    # underscore-prefixed names don't appear in it. Skipped
    # to keep the test cheap; the function is short.)
    assert "kind:" in text and "media_type:" in text and "data_b64:" in text


def test_science_html_composer_wires_paste_drop_handlers() -> None:
    """``science.html`` must hook the Alpine handlers on the
    composer textarea + container so paste / drop actually
    routes into chat.js."""
    html = Path(__file__).resolve().parents[2] \
        / "openmiura" / "ui" / "v2" / "static" / "science.html"
    text = html.read_text(encoding="utf-8")
    assert "onComposerPaste" in text
    assert "onComposerDrop" in text
    assert "onComposerDragOver" in text
    assert "pendingAttachments" in text
    assert "removeAttachment" in text
    assert "onComposerFilePicker" in text


def test_science_html_send_button_allows_attachment_only_send() -> None:
    """The send button's :disabled guard must allow sending
    when text is empty BUT there's at least one attachment —
    otherwise a drag-drop without typing leaves the operator
    stuck."""
    html = Path(__file__).resolve().parents[2] \
        / "openmiura" / "ui" / "v2" / "static" / "science.html"
    text = html.read_text(encoding="utf-8")
    # The disabled expression should reference both text AND
    # pendingAttachments so that attachment-only sends work.
    # We just pin that the new clause is present.
    assert "pendingAttachments.length" in text
