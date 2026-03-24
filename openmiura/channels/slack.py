from __future__ import annotations

import hashlib
import hmac
import time
from typing import Optional

import httpx


class SlackClient:
    def __init__(self, bot_token: str, timeout_s: int = 20):
        self.bot_token = bot_token
        self.timeout_s = timeout_s

    def post_message(self, *, channel: str, text: str, thread_ts: Optional[str] = None) -> None:
        url = "https://slack.com/api/chat.postMessage"
        headers = {"Authorization": f"Bearer {self.bot_token}"}
        payload = {"channel": channel, "text": text}
        if thread_ts:
            payload["thread_ts"] = thread_ts
        with httpx.Client(timeout=self.timeout_s) as client:
            r = client.post(url, headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()
            if not data.get("ok", False):
                raise RuntimeError(f"Slack chat.postMessage failed: {data}")


def verify_slack_request(*, signing_secret: str, timestamp: str, signature: str, body: bytes, max_age_s: int = 300) -> bool:
    if not signing_secret or not timestamp or not signature:
        return False
    try:
        ts = int(timestamp)
    except Exception:
        return False
    if abs(int(time.time()) - ts) > max_age_s:
        return False
    base = b"v0:" + str(ts).encode("utf-8") + b":" + body
    digest = hmac.new(signing_secret.encode("utf-8"), base, hashlib.sha256).hexdigest()
    expected = f"v0={digest}"
    return hmac.compare_digest(expected, signature)
