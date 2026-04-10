from __future__ import annotations

from openmiura.channels.discord import (
    build_command_text,
    build_gateway_url,
    chunk_text,
    extract_inbound_payload,
    merge_text_and_attachments,
    normalize_attachments,
    should_process_message,
    strip_bot_mention,
)


class _FakeAttachment:
    def __init__(self, filename: str, url: str, content_type: str, size: int):
        self.filename = filename
        self.url = url
        self.content_type = content_type
        self.size = size


def test_chunk_text_splits_long_message():
    parts = chunk_text("a" * 4005, n=1900)
    assert len(parts) == 3
    assert len(parts[0]) == 1900
    assert len(parts[1]) == 1900
    assert len(parts[2]) == 205


def test_strip_bot_mention_removes_both_formats():
    text = "<@123> hola <@!123> qué tal"
    assert strip_bot_mention(text, 123) == "hola qué tal"


def test_should_process_message_respects_mention_only():
    assert should_process_message(text="hola", is_dm=True, mentions_bot=False, mention_only=True) is True
    assert should_process_message(text="hola", is_dm=False, mentions_bot=False, mention_only=True) is False
    assert should_process_message(text="hola", is_dm=False, mentions_bot=True, mention_only=True) is True
    assert should_process_message(text="", is_dm=False, mentions_bot=True, mention_only=False) is False


def test_build_command_text_maps_native_commands_and_prompt():
    assert build_command_text("help") == "/help"
    assert build_command_text("status") == "/status"
    assert build_command_text("miura", "Explícame DOSY") == "Explícame DOSY"
    assert build_command_text("link", link_key="curro") == "/link curro"
    assert build_command_text("unknown", "texto libre") == "texto libre"


def test_attachment_helpers_normalize_and_merge():
    items = normalize_attachments(
        [
            _FakeAttachment("a.png", "https://x/a.png", "image/png", 100),
            _FakeAttachment("b.txt", "https://x/b.txt", "text/plain", 50),
        ],
        max_items=1,
    )
    assert items == [
        {
            "filename": "a.png",
            "url": "https://x/a.png",
            "content_type": "image/png",
            "size": 100,
        }
    ]
    merged = merge_text_and_attachments("mira esto", items)
    assert "mira esto" in merged
    assert "Adjuntos Discord:" in merged
    assert "a.png" in merged


def test_extract_inbound_payload_supports_slash_metadata_and_attachments():
    payload = extract_inbound_payload(
        message_text="/status",
        author_id=10,
        channel_id=20,
        guild_id=30,
        message_id=None,
        mentions_bot=False,
        is_dm=False,
        source="slash",
        interaction_id=999,
        command_name="status",
        attachments=[{"filename": "a.txt", "url": "https://x/a.txt"}],
    )
    assert payload["channel"] == "discord"
    assert payload["user_id"] == "discord:10"
    assert payload["text"] == "/status"
    assert payload["metadata"]["source"] == "slash"
    assert payload["metadata"]["interaction_id"] == 999
    assert payload["metadata"]["command_name"] == "status"
    assert payload["metadata"]["attachments"][0]["filename"] == "a.txt"


def test_build_gateway_url_points_to_http_message():
    assert build_gateway_url("127.0.0.1", 8081) == "http://127.0.0.1:8081/http/message"
