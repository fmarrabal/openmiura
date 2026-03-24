"""Telegram transport routes exposed through the interfaces layer."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from openmiura.channels.telegram import extract_message
from openmiura.gateway import Gateway
from openmiura.observability import observe_request, record_error
from openmiura.pipeline import process_message as _default_process_message
from openmiura.interfaces.channels.telegram.translator import build_telegram_inbound

router = APIRouter(tags=["telegram"])
logger = logging.getLogger(__name__)


def _get_process_message():
    from openmiura.endpoints import telegram as legacy_telegram_endpoint
    return getattr(legacy_telegram_endpoint, "process_message", _default_process_message)


def _get_gw(request: Request) -> Gateway:
    gw: Gateway | None = getattr(request.app.state, "gw", None)
    if gw is None or gw.telegram is None:
        raise HTTPException(status_code=503, detail="Telegram not configured")
    return gw


@router.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    with observe_request("telegram"):
        gw = _get_gw(request)
        tg = gw.telegram
        assert tg is not None

        secret_cfg = (
            (gw.settings.telegram.webhook_secret or "").strip()
            if gw.settings.telegram
            else ""
        )
        if secret_cfg:
            header = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
            if header != secret_cfg:
                raise HTTPException(status_code=401, detail="Invalid Telegram secret token")

        try:
            update = await request.json()
        except Exception as e:
            logger.warning("Invalid Telegram JSON payload")
            record_error("telegram_invalid_json")
            raise HTTPException(status_code=400, detail="Invalid JSON payload") from e

        data = extract_message(update)
        if data is None:
            return {"ok": True}

        chat_id, from_id, message_id, text = data

        if not gw.is_telegram_allowed(chat_id, from_id):
            deny_msg = gw.telegram_deny_message()
            try:
                tg.send_message_chunked(chat_id=chat_id, text=deny_msg, reply_to_message_id=message_id)
            except Exception:
                logger.exception("Failed to post Telegram deny message")
            try:
                inbound = build_telegram_inbound(from_id=from_id, chat_id=chat_id, message_id=message_id, text=text)
                user_key = gw.effective_user_key(inbound.user_id)
                session_id = gw.derive_session_id(inbound, user_key)
                gw.audit.log_event(
                    direction="security",
                    channel="telegram",
                    user_id=inbound.user_id,
                    session_id=session_id,
                    payload={
                        "reason": "not_allowlisted",
                        "chat_id": chat_id,
                        "from_id": from_id,
                        "message_id": message_id,
                    },
                )
            except Exception:
                logger.exception("Failed to persist Telegram security denial")
            return {"ok": True}

        inbound = build_telegram_inbound(from_id=from_id, chat_id=chat_id, message_id=message_id, text=text)
        out = _get_process_message()(gw, inbound)
        tg.send_message_chunked(chat_id=chat_id, text=out.text, reply_to_message_id=message_id)
        return {"ok": True}
