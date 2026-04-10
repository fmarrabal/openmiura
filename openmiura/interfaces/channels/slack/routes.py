"""Slack transport routes exposed through the interfaces layer."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from openmiura.channels.slack import verify_slack_request
from openmiura.core.schema import InboundMessage
from openmiura.gateway import Gateway
from openmiura.observability import observe_request, record_error
from openmiura.pipeline import process_message as _default_process_message
from openmiura.interfaces.channels.slack.translator import normalize_slack_text, slack_chunks

router = APIRouter(tags=["slack"])
logger = logging.getLogger(__name__)


def _get_process_message():
    from openmiura.endpoints import slack as legacy_slack_endpoint
    return getattr(legacy_slack_endpoint, "process_message", _default_process_message)


def _get_gw(request: Request) -> Gateway:
    gw: Gateway | None = getattr(request.app.state, "gw", None)
    if gw is None or gw.settings.slack is None or gw.slack is None:
        raise HTTPException(status_code=503, detail="Slack not configured")
    return gw


def _process_slack_event(
    gw: Gateway,
    *,
    team_id: str,
    event_id: str,
    channel_id: str,
    slack_user: str,
    event_type: str,
    text: str,
    thread_ts: str | None,
) -> None:
    slack_cfg = gw.settings.slack
    if slack_cfg is None or gw.slack is None:
        return

    reply_in_thread = bool(getattr(slack_cfg, "reply_in_thread", True))
    thread_for_reply = thread_ts if reply_in_thread else None
    channel_user_id = f"slack:{team_id}:{slack_user}"
    user_key = gw.effective_user_key(channel_user_id)
    session_id = f"slack-{channel_id}-{user_key}"

    try:
        text = normalize_slack_text(text, event_type=event_type, bot_user_id=(slack_cfg.bot_user_id or "").strip())
        inbound = InboundMessage(
            channel="slack",
            user_id=channel_user_id,
            session_id=session_id,
            text=text,
            metadata={
                "team_id": team_id,
                "channel_id": channel_id,
                "event_type": event_type,
                "event_id": event_id,
                "thread_ts": thread_ts,
            },
        )
        out = _get_process_message()(gw, inbound)
        for chunk in slack_chunks(out.text):
            gw.slack.post_message(channel=channel_id, text=chunk, thread_ts=thread_for_reply)
    except Exception as e:
        record_error("slack_background")
        logger.exception(
            "Slack background processing failed",
            extra={
                "team_id": team_id,
                "channel_id": channel_id,
                "event_id": event_id,
                "slack_user": slack_user,
                "event_type": event_type,
            },
        )
        try:
            gw.audit.log_event(
                direction="error",
                channel="slack",
                user_id=channel_user_id,
                session_id=session_id,
                payload={
                    "stage": "slack_background",
                    "team_id": team_id,
                    "channel_id": channel_id,
                    "event_id": event_id,
                    "event_type": event_type,
                    "thread_ts": thread_ts,
                    "error": repr(e),
                },
            )
        except Exception:
            logger.exception("Failed to persist Slack background error")
        try:
            gw.slack.post_message(
                channel=channel_id,
                text="⚠️ Error interno procesando el mensaje.",
                thread_ts=thread_for_reply,
            )
        except Exception:
            logger.exception("Failed to post Slack fallback error message")


@router.post("/slack/events")
async def slack_events(request: Request, background_tasks: BackgroundTasks):
    with observe_request("slack"):
        gw = _get_gw(request)
        slack_cfg = gw.settings.slack
        assert slack_cfg is not None
        body = await request.body()
        ts = request.headers.get("X-Slack-Request-Timestamp", "")
        sig = request.headers.get("X-Slack-Signature", "")

        if not verify_slack_request(
            signing_secret=slack_cfg.signing_secret,
            timestamp=ts,
            signature=sig,
            body=body,
        ):
            record_error("slack_signature")
            raise HTTPException(status_code=401, detail="Invalid Slack signature")

        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception as e:
            logger.warning("Invalid Slack JSON payload")
            record_error("slack_invalid_json")
            raise HTTPException(status_code=400, detail="Invalid JSON payload") from e

        if payload.get("type") == "url_verification":
            return {"challenge": payload.get("challenge", "")}
        if payload.get("type") != "event_callback":
            return {"ok": True}

        event_id = payload.get("event_id", "") or ""
        team_id = payload.get("team_id", "") or payload.get("team", "") or ""
        event = payload.get("event", {}) or {}
        event_type = event.get("type", "") or ""
        subtype = event.get("subtype")

        if subtype is not None or event.get("bot_id") is not None:
            return {"ok": True}
        if event_type not in ("app_mention", "message"):
            return {"ok": True}

        channel_id = event.get("channel", "") or ""
        slack_user = event.get("user", "") or ""
        text = (event.get("text") or "").strip()
        channel_type = event.get("channel_type")
        thread_ts = event.get("thread_ts") or event.get("ts")

        if not channel_id or not slack_user:
            return {"ok": True}

        if event_id:
            is_new = gw.audit.mark_slack_event_once(event_id, team_id, channel_id, slack_user)
            if not is_new:
                return {"ok": True}

        if not gw.is_slack_allowed(team_id, channel_id, channel_type):
            deny = getattr(slack_cfg.allowlist, "deny_message", "⛔ No autorizado.")
            channel_user_id = f"slack:{team_id}:{slack_user}"
            user_key = gw.effective_user_key(channel_user_id)
            session_id = f"slack-{channel_id}-{user_key}"
            try:
                gw.audit.log_event(
                    direction="security",
                    channel="slack",
                    user_id=channel_user_id,
                    session_id=session_id,
                    payload={
                        "reason": "not_allowlisted",
                        "team_id": team_id,
                        "channel_id": channel_id,
                        "event_id": event_id,
                        "event_type": event_type,
                    },
                )
            except Exception:
                logger.exception("Failed to persist Slack security denial")
            try:
                gw.slack.post_message(channel=channel_id, text=deny, thread_ts=thread_ts)
            except Exception:
                logger.exception("Failed to post Slack deny message")
            return {"ok": True}

        background_tasks.add_task(
            _process_slack_event,
            gw,
            team_id=team_id,
            event_id=event_id,
            channel_id=channel_id,
            slack_user=slack_user,
            event_type=event_type,
            text=text,
            thread_ts=thread_ts,
        )
        return {"ok": True}
