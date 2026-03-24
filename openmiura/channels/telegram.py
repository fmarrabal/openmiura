from __future__ import annotations

from dataclasses import dataclass
import random
import time
from typing import Any, Dict, Optional, Tuple

import httpx


@dataclass(frozen=True)
class TelegramSettings:
    bot_token: str
    mode: str = "polling"         # polling | webhook
    webhook_secret: str = ""      # opcional


MAX_LEN = 3500  # margen de seguridad (Telegram suele limitar ~4096)


def _split_preserving_paragraphs(text: str, n: int) -> list[str]:
    text = (text or "").strip()
    if not text:
        return [""]

    out: list[str] = []
    current = ""
    paragraphs = text.split("\n\n")
    for para in paragraphs:
        candidate = para if not current else current + "\n\n" + para
        if len(candidate) <= n:
            current = candidate
            continue
        if current:
            out.append(current)
            current = ""
        if len(para) <= n:
            current = para
            continue
        for i in range(0, len(para), n):
            out.append(para[i:i + n])
    if current:
        out.append(current)
    return out or [""]


class TelegramClient:
    def __init__(self, bot_token: str, timeout_s: int = 20):
        self.bot_token = bot_token
        self.timeout_s = timeout_s
        self.base = f"https://api.telegram.org/bot{bot_token}"
        self._consecutive_failures = 0

    def send_message(
        self,
        chat_id: int,
        text: str,
        reply_to_message_id: Optional[int] = None,
    ) -> None:
        payload: Dict[str, Any] = {"chat_id": chat_id, "text": text}
        if reply_to_message_id is not None:
            payload["reply_to_message_id"] = reply_to_message_id

        last_exc: Exception | None = None
        for _attempt in range(5):
            try:
                with httpx.Client(timeout=self.timeout_s) as client:
                    r = client.post(f"{self.base}/sendMessage", json=payload)
                if r.status_code == 429:
                    retry_after = 1
                    try:
                        retry_after = int((r.json().get("parameters") or {}).get("retry_after") or 1)
                    except Exception:
                        retry_after = 1
                    time.sleep(float(retry_after) + random.uniform(0.1, 0.6))
                    continue
                r.raise_for_status()
                self._consecutive_failures = 0
                return
            except Exception as exc:
                last_exc = exc
                self._consecutive_failures += 1
                if self._consecutive_failures >= 5:
                    time.sleep(60.0)
                    self._consecutive_failures = 0
                else:
                    time.sleep(0.5)
        if last_exc is not None:
            raise last_exc

    def send_message_chunked(
        self,
        chat_id: int,
        text: str,
        reply_to_message_id: int | None = None,
    ) -> None:
        raw_parts = _split_preserving_paragraphs(text, MAX_LEN - 12)
        total = len(raw_parts)
        parts = [
            f"[{i + 1}/{total}] {part}" if total > 1 else part
            for i, part in enumerate(raw_parts)
        ]
        for i, part in enumerate(parts):
            rmid = reply_to_message_id if i == 0 else None
            self.send_message(chat_id=chat_id, text=part, reply_to_message_id=rmid)


def extract_message(update: Dict[str, Any]) -> Optional[Tuple[int, int, int, str]]:
    """
    Returns (chat_id, from_id, message_id, text) or None if not a text message.
    """
    msg = update.get("message") or update.get("edited_message")
    if not isinstance(msg, dict):
        return None

    text = msg.get("text")
    if not isinstance(text, str) or not text.strip():
        return None

    chat = msg.get("chat") or {}
    sender = msg.get("from") or {}
    chat_id = chat.get("id")
    from_id = sender.get("id")
    message_id = msg.get("message_id")

    if not isinstance(chat_id, int) or not isinstance(from_id, int) or not isinstance(message_id, int):
        return None

    return chat_id, from_id, message_id, text.strip()


def session_id_for(chat_id: int, from_id: int) -> str:
    # Sesión estable por chat+usuario (DM o grupo)
    return f"tg-{chat_id}-{from_id}"
