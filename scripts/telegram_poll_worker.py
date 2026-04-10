from __future__ import annotations

import hashlib
import os
import random
import time

import httpx

from openmiura.channels.telegram import TelegramClient
from openmiura.core.audit import AuditStore
from openmiura.core.config import load_settings


def _env_or(value: str, env_name: str) -> str:
    return value or os.environ.get(env_name, "")


def main() -> None:
    config_path = os.environ.get("OPENMIURA_CONFIG", "configs/openmiura.yaml")
    settings = load_settings(config_path)

    telegram_token = ""
    if settings.telegram is not None:
        telegram_token = _env_or(
            settings.telegram.bot_token,
            "OPENMIURA_TELEGRAM_BOT_TOKEN",
        )

    if not telegram_token:
        raise RuntimeError(
            "Missing Telegram bot token. Set telegram.bot_token in configs/openmiura.yaml "
            "or OPENMIURA_TELEGRAM_BOT_TOKEN in the environment."
        )

    gateway_url = f"http://{settings.server.host}:{settings.server.port}/http/message"
    print(f"[telegram-poll] using gateway {gateway_url}")

    audit = AuditStore(settings.storage.db_path)
    audit.init_db()

    bot_key = hashlib.sha256(telegram_token.encode("utf-8")).hexdigest()[:16]
    offset = audit.get_telegram_offset(bot_key)
    print(f"[telegram-poll] starting offset={offset}")

    tg = TelegramClient(telegram_token, timeout_s=45)

    poll_timeout_s = 25
    consecutive_failures = 0

    timeout = httpx.Timeout(
        connect=10.0,
        read=40.0,
        write=20.0,
        pool=20.0,
    )

    with httpx.Client(timeout=timeout, trust_env=False) as client:
        while True:
            try:
                r = client.get(
                    f"https://api.telegram.org/bot{telegram_token}/getUpdates",
                    params={
                        "offset": offset,
                        "timeout": poll_timeout_s,
                        "allowed_updates": '["message","edited_message"]',
                    },
                )
                r.raise_for_status()
                payload = r.json()

                if not payload.get("ok", False):
                    print(f"[telegram-poll] telegram returned ok=false: {payload}")
                    time.sleep(2.0)
                    continue

                updates = payload.get("result", []) or []
                consecutive_failures = 0

                for upd in updates:
                    update_id = upd.get("update_id")
                    if update_id is None:
                        continue

                    offset = int(update_id) + 1
                    audit.set_telegram_offset(bot_key, offset)

                    try:
                        msg = upd.get("message") or upd.get("edited_message") or {}
                        from_id = (msg.get("from") or {}).get("id", "")
                        text = msg.get("text", "")
                        chat_id = (msg.get("chat") or {}).get("id")
                        message_id = msg.get("message_id")

                        if not from_id or not text:
                            continue

                        resp = client.post(
                            gateway_url,
                            json={
                                "channel": "telegram",
                                "user_id": f"tg:{from_id}",
                                "session_id": None,
                                "text": text,
                                "metadata": {
                                    "chat_id": chat_id,
                                    "from_id": from_id,
                                    "message_id": message_id,
                                    "update": upd,
                                },
                            },
                        )
                        resp.raise_for_status()
                        out = resp.json()
                        reply_text = (out or {}).get("text", "")

                        if chat_id and reply_text:
                            tg.send_message_chunked(
                                chat_id=chat_id,
                                text=reply_text,
                                reply_to_message_id=message_id,
                            )
                    except Exception as e:
                        print(f"[telegram-poll] gateway/send error: {e!r}")

            except httpx.ReadTimeout:
                print("[telegram-poll] read timeout on getUpdates; retrying")
                continue

            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                print(f"[telegram-poll] HTTP error from Telegram: {status}")

                consecutive_failures += 1

                if status in (502, 503, 504, 520, 522, 524):
                    sleep_s = min(30.0, 2.0 ** min(consecutive_failures, 4))
                    sleep_s += random.uniform(0.0, 0.8)
                    print(
                        f"[telegram-poll] transient upstream error, sleeping {sleep_s:.1f}s"
                    )
                    time.sleep(sleep_s)
                    continue

                time.sleep(3.0)

            except Exception as e:
                consecutive_failures += 1
                sleep_s = min(60.0, 2.0 ** min(consecutive_failures, 5))
                sleep_s += random.uniform(0.0, 1.0)
                print(f"[telegram-poll] error: {e!r}")
                print(f"[telegram-poll] sleeping {sleep_s:.1f}s before retry")
                time.sleep(sleep_s)


if __name__ == "__main__":
    main()