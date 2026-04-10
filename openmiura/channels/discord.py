from __future__ import annotations

from typing import Any, Iterable

import httpx

MAX_LEN = 1900


def chunk_text(text: str, n: int = MAX_LEN) -> list[str]:
    text = (text or "").strip()
    if not text:
        return [""]
    return [text[i : i + n] for i in range(0, len(text), n)]


def strip_bot_mention(text: str, bot_user_id: int | str | None) -> str:
    if bot_user_id is None:
        return (text or "").strip()
    bid = str(bot_user_id).strip()
    cleaned = (text or "").replace(f"<@{bid}>", " ").replace(f"<@!{bid}>", " ")
    return " ".join(cleaned.split())


def should_process_message(
    *,
    text: str,
    is_dm: bool,
    mentions_bot: bool,
    mention_only: bool,
) -> bool:
    if not (text or "").strip():
        return False
    if is_dm:
        return True
    if mention_only and not mentions_bot:
        return False
    return True


def build_command_text(
    command_name: str,
    prompt: str | None = None,
    *,
    link_key: str | None = None,
) -> str:
    name = (command_name or "").strip().lower()
    prompt = (prompt or "").strip()

    native_map = {
        "help": "/help",
        "ayuda": "/help",
        "status": "/status",
        "reset": "/reset",
        "forget": "/forget",
    }
    if name == "link":
        return f"/link {link_key.strip()}" if (link_key or "").strip() else "/link"
    if name in native_map:
        return native_map[name]
    if prompt:
        return prompt
    return ""


def normalize_attachments(
    attachments: Iterable[Any] | None,
    *,
    max_items: int = 4,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if not attachments:
        return items

    for att in list(attachments)[: max(0, int(max_items))]:
        filename = getattr(att, "filename", None)
        url = getattr(att, "url", None)
        content_type = getattr(att, "content_type", None)
        size = getattr(att, "size", None)
        items.append(
            {
                "filename": filename,
                "url": url,
                "content_type": content_type,
                "size": size,
            }
        )
    return items


def render_attachment_context(items: list[dict[str, Any]] | None) -> str:
    if not items:
        return ""
    lines = ["Adjuntos Discord:"]
    for item in items:
        filename = item.get("filename") or "archivo"
        url = item.get("url") or ""
        ctype = item.get("content_type") or "desconocido"
        size = item.get("size")
        size_txt = f", {size} bytes" if isinstance(size, int) else ""
        lines.append(f"- {filename} ({ctype}{size_txt}): {url}")
    return "\n".join(lines)


def merge_text_and_attachments(
    message_text: str,
    attachments: list[dict[str, Any]] | None,
    *,
    include_attachments_in_text: bool = True,
) -> str:
    base = (message_text or "").strip()
    if not include_attachments_in_text or not attachments:
        return base
    ctx = render_attachment_context(attachments)
    if not base:
        return ctx
    return f"{base}\n\n{ctx}" if ctx else base


def extract_inbound_payload(
    *,
    message_text: str,
    author_id: int,
    channel_id: int,
    guild_id: int | None,
    message_id: int | None,
    mentions_bot: bool,
    is_dm: bool,
    source: str = "message",
    interaction_id: int | None = None,
    command_name: str | None = None,
    attachments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "author_id": author_id,
        "channel_id": channel_id,
        "guild_id": guild_id,
        "message_id": message_id,
        "is_dm": is_dm,
        "mentions_bot": mentions_bot,
        "source": source,
    }
    if interaction_id is not None:
        metadata["interaction_id"] = interaction_id
    if command_name:
        metadata["command_name"] = command_name
    if attachments:
        metadata["attachments"] = attachments

    return {
        "channel": "discord",
        "user_id": f"discord:{author_id}",
        "text": message_text,
        "metadata": metadata,
    }


def build_gateway_url(host: str, port: int) -> str:
    host = (host or "127.0.0.1").strip()
    return f"http://{host}:{int(port)}/http/message"


async def post_inbound_to_gateway(
    *,
    gateway_url: str,
    payload: dict[str, Any],
    timeout_s: int,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=timeout_s)
    assert client is not None
    try:
        resp = await client.post(gateway_url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            raise RuntimeError("Gateway returned non-object JSON")
        return data
    finally:
        if own_client:
            await client.aclose()
