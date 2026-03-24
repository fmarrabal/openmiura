from __future__ import annotations

SLACK_MAX_LEN = 3000


def slack_chunks(text: str, limit: int = SLACK_MAX_LEN) -> list[str]:
    text = (text or "").strip()
    if not text:
        return [""]
    parts: list[str] = []
    current = ""
    for para in text.split("\n\n"):
        candidate = para if not current else current + "\n\n" + para
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            parts.append(current)
            current = ""
        if len(para) <= limit:
            current = para
            continue
        for i in range(0, len(para), limit):
            parts.append(para[i:i + limit])
    if current:
        parts.append(current)
    return parts or [""]


def normalize_slack_text(text: str, *, event_type: str, bot_user_id: str = "") -> str:
    text = (text or "").strip()
    if event_type == "app_mention" and bot_user_id:
        text = text.replace(f"<@{bot_user_id}>", "").strip()
    return text
