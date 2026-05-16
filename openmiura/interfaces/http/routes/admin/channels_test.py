"""admin/channels_test.py — per-channel test-message sender.

Closes the gap documented in UI v2 PR-B6 (#51, Channels
wizard): the operator can validate and save channel config,
but cannot tell from inside the wizard whether the saved
config actually works without dropping into a separate
shell to fire a message manually.

This module adds a single endpoint:

  POST /admin/channels/{channel}/test
       body: { recipient, text, actor }                    (confirmed)

The handler dispatches per channel — adapters are bespoke
(SlackClient.post_message vs TelegramClient.send_message),
so a single ``adapter.send(...)`` abstraction would obscure
the per-channel arg differences. The dispatch table here
documents which channels are supported; adding a new one is
a one-line entry plus the corresponding client method.

Errors from the upstream provider (Slack API, Telegram API)
are caught and returned as 502 with the provider error in
the body. The action is recorded on the audit trail
regardless of outcome — an attempted send that fails is
still operator activity worth auditing.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from openmiura.interfaces.http.routes.admin._helpers import (
    _audit_admin,
    _require_admin,
)

router = APIRouter(tags=["admin"])


class ChannelTestRequest(BaseModel):
    recipient: str = Field(
        ...,
        description=(
            "Channel-specific destination. For slack: channel id or "
            "name (e.g. '#general'). For telegram: chat_id as a "
            "string; the handler parses it to int."
        ),
    )
    text: str = Field(..., min_length=1, max_length=4000)
    actor: str = Field(default="admin")


def _send_slack(gw, *, recipient: str, text: str) -> dict[str, Any]:
    client = getattr(gw, "slack", None)
    if client is None:
        raise HTTPException(
            status_code=503,
            detail="Slack channel is not configured in this scope",
        )
    try:
        client.post_message(channel=recipient, text=text)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=f"Slack send failed: {exc}") from exc
    except Exception as exc:
        # httpx.HTTPStatusError, network errors, etc.
        raise HTTPException(status_code=502, detail=f"Slack send failed: {exc}") from exc
    return {"ok": True, "channel": "slack", "recipient": recipient}


def _send_telegram(gw, *, recipient: str, text: str) -> dict[str, Any]:
    client = getattr(gw, "telegram", None)
    if client is None:
        raise HTTPException(
            status_code=503,
            detail="Telegram channel is not configured in this scope",
        )
    try:
        chat_id = int((recipient or "").strip())
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=422,
            detail="Telegram recipient must be a numeric chat_id",
        )
    try:
        client.send_message(chat_id, text)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Telegram send failed: {exc}") from exc
    return {"ok": True, "channel": "telegram", "recipient": str(chat_id)}


# Per-channel dispatch table. Adding a new channel is a one-
# line entry here plus the corresponding send-helper above.
_DISPATCH = {
    "slack":    _send_slack,
    "telegram": _send_telegram,
}


@router.post("/admin/channels/{channel}/test")
def admin_channels_test(channel: str, payload: ChannelTestRequest, request: Request):
    """Send a one-off test message through the named channel.

    The message goes through the same client used by the live
    runtime — so a successful test is a strong signal that the
    saved channel config is correct. Recipients (Slack channel
    names, Telegram chat ids) must be valid; the handler does
    not auto-discover defaults.
    """
    gw = _require_admin(request)
    name = (channel or "").strip().lower()
    handler = _DISPATCH.get(name)
    if handler is None:
        supported = ", ".join(sorted(_DISPATCH.keys()))
        raise HTTPException(
            status_code=404,
            detail=f"Channel '{name}' not supported for test message (supported: {supported})",
        )
    text = (payload.text or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail="text is required")
    recipient = (payload.recipient or "").strip()
    if not recipient:
        raise HTTPException(status_code=422, detail="recipient is required")

    actor = (payload.actor or "admin").strip() or "admin"

    # Record the *attempt* in the audit log before we even fire
    # the request — so that an upstream provider timeout still
    # leaves a trace.
    attempt_audit_id = _audit_admin(gw, "channel_test_attempt", {
        "channel":   name,
        "recipient": recipient,
        "actor":     actor,
        "text_len":  len(text),
    })

    try:
        response = handler(gw, recipient=recipient, text=text)
    except HTTPException:
        # Re-record as failure so a grep over the audit trail
        # finds both the attempt and the outcome on the same key.
        _audit_admin(gw, "channel_test_failure", {
            "channel":   name,
            "recipient": recipient,
            "actor":     actor,
            "attempt_audit_id": attempt_audit_id,
        })
        raise

    success_audit_id = _audit_admin(gw, "channel_test_success", {
        "channel":   name,
        "recipient": recipient,
        "actor":     actor,
        "attempt_audit_id": attempt_audit_id,
    })
    if attempt_audit_id is not None:
        response["attempt_audit_id"] = attempt_audit_id
    if success_audit_id is not None:
        response["audit_event_id"] = success_audit_id
    return response


__all__ = ["router"]
