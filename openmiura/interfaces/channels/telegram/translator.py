from __future__ import annotations

from openmiura.core.schema import InboundMessage


def build_telegram_inbound(*, from_id: int, chat_id: int, message_id: int, text: str) -> InboundMessage:
    return InboundMessage(
        channel="telegram",
        user_id=f"tg:{from_id}",
        text=text,
        metadata={"chat_id": chat_id, "from_id": from_id, "message_id": message_id},
    )
