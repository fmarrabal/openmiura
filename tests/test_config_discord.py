from __future__ import annotations

from pathlib import Path

from openmiura.core.config import load_settings


def test_load_settings_parses_discord_slash_and_attachment_fields(tmp_path: Path):
    cfg = tmp_path / "openmiura.yaml"
    cfg.write_text(
        """
server:
  host: "127.0.0.1"
  port: 8081
storage:
  db_path: "data/test.db"
llm:
  provider: "ollama"
  base_url: "http://127.0.0.1:11434"
  model: "qwen2.5:7b-instruct"
  timeout_s: 60
runtime:
  history_limit: 12
agents:
  default:
    system_prompt: "hola"
discord:
  bot_token: "abc"
  application_id: "123456"
  mention_only: true
  reply_as_reply: false
  slash_enabled: true
  slash_command_name: "miura"
  sync_on_startup: true
  sync_guild_ids: [111, 222]
  expose_native_commands: false
  include_attachments_in_text: false
  max_attachment_items: 7
  allowlist:
    enabled: true
    allow_user_ids: [1]
    allow_channel_ids: [2]
    allow_guild_ids: [3]
    allow_dm: false
    deny_message: "denied"
""",
        encoding="utf-8",
    )

    settings = load_settings(str(cfg))

    assert settings.discord is not None
    assert settings.discord.bot_token == "abc"
    assert settings.discord.application_id == "123456"
    assert settings.discord.reply_as_reply is False
    assert settings.discord.slash_enabled is True
    assert settings.discord.slash_command_name == "miura"
    assert settings.discord.sync_on_startup is True
    assert settings.discord.sync_guild_ids == [111, 222]
    assert settings.discord.expose_native_commands is False
    assert settings.discord.include_attachments_in_text is False
    assert settings.discord.max_attachment_items == 7
    assert settings.discord.allowlist.enabled is True
    assert settings.discord.allowlist.allow_user_ids == [1]
    assert settings.discord.allowlist.allow_channel_ids == [2]
    assert settings.discord.allowlist.allow_guild_ids == [3]
    assert settings.discord.allowlist.allow_dm is False
    assert settings.discord.allowlist.deny_message == "denied"


def test_load_settings_sets_discord_defaults(tmp_path: Path):
    cfg = tmp_path / "openmiura.yaml"
    cfg.write_text(
        """
server: {}
storage: {}
llm: {}
runtime: {}
agents:
  default:
    system_prompt: "hola"
""",
        encoding="utf-8",
    )

    settings = load_settings(str(cfg))

    assert settings.discord is not None
    assert settings.discord.slash_enabled is True
    assert settings.discord.slash_command_name == "miura"
    assert settings.discord.sync_on_startup is True
    assert settings.discord.sync_guild_ids == []
    assert settings.discord.expose_native_commands is True
    assert settings.discord.include_attachments_in_text is True
    assert settings.discord.max_attachment_items == 4


def test_load_settings_resolves_secret_placeholders_from_env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPENMIURA_DISCORD_BOT_TOKEN", "disc-secret")
    monkeypatch.setenv("OPENMIURA_DISCORD_APPLICATION_ID", "999")
    monkeypatch.setenv("OPENMIURA_ADMIN_TOKEN", "admin-secret")
    cfg = tmp_path / "openmiura.yaml"
    cfg.write_text(
        """
server: {}
storage: {}
llm: {}
runtime: {}
agents:
  default:
    system_prompt: "hola"
discord:
  bot_token: "${OPENMIURA_DISCORD_BOT_TOKEN}"
  application_id: "env:OPENMIURA_DISCORD_APPLICATION_ID"
admin:
  enabled: true
  token: "${OPENMIURA_ADMIN_TOKEN}"
""",
        encoding="utf-8",
    )

    settings = load_settings(str(cfg))

    assert settings.discord is not None
    assert settings.discord.bot_token == "disc-secret"
    assert settings.discord.application_id == "999"
    assert settings.admin is not None
    assert settings.admin.token == "admin-secret"


def test_load_settings_falls_back_to_env_for_blank_secrets(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPENMIURA_TELEGRAM_BOT_TOKEN", "tg-secret")
    monkeypatch.setenv("OPENMIURA_SLACK_BOT_TOKEN", "slack-secret")
    monkeypatch.setenv("OPENMIURA_SLACK_SIGNING_SECRET", "sig-secret")
    cfg = tmp_path / "openmiura.yaml"
    cfg.write_text(
        """
server: {}
storage: {}
llm: {}
runtime: {}
agents:
  default:
    system_prompt: "hola"
telegram:
  bot_token: ""
slack:
  bot_token: ""
  signing_secret: ""
""",
        encoding="utf-8",
    )

    settings = load_settings(str(cfg))

    assert settings.telegram is not None
    assert settings.telegram.bot_token == "tg-secret"
    assert settings.slack is not None
    assert settings.slack.bot_token == "slack-secret"
    assert settings.slack.signing_secret == "sig-secret"
