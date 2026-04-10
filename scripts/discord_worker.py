from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import discord
from discord import app_commands

from openmiura.channels.discord import (
    build_command_text,
    build_gateway_url,
    chunk_text,
    extract_inbound_payload,
    merge_text_and_attachments,
    normalize_attachments,
    post_inbound_to_gateway,
    should_process_message,
    strip_bot_mention,
)
from openmiura.core.config import load_settings

logging.basicConfig(
    level=os.environ.get("OPENMIURA_LOG_LEVEL", "INFO").upper(),
    format="[discord-worker] %(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("openmiura.discord_worker")


class OpenMiuraDiscordClient(discord.Client):
    def __init__(self, *, config_path: str):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.messages = True
        intents.dm_messages = True
        super().__init__(intents=intents)
        self.config_path = config_path
        self.settings = load_settings(config_path)
        self.gateway_url = build_gateway_url(self.settings.server.host, self.settings.server.port)
        self.http_timeout_s = max(30, int(getattr(self.settings.llm, "timeout_s", 60)) + 15)
        self.tree = app_commands.CommandTree(self)
        self._slash_registered = False

    async def setup_hook(self) -> None:
        self._register_slash_commands()
        await self._sync_commands_if_enabled()

    async def on_ready(self) -> None:
        logger.info(
            "discord bot ready user=%s gateway=%s mention_only=%s slash=%s",
            getattr(self.user, "id", None),
            self.gateway_url,
            getattr(self.settings.discord, "mention_only", True) if self.settings.discord else True,
            getattr(self.settings.discord, "slash_enabled", True) if self.settings.discord else True,
        )

    def _register_slash_commands(self) -> None:
        if self._slash_registered:
            return
        dc = self.settings.discord
        if dc is None or not getattr(dc, "slash_enabled", True):
            self._slash_registered = True
            return

        command_name = (getattr(dc, "slash_command_name", "miura") or "miura").strip() or "miura"

        @self.tree.command(name=command_name, description="Habla con Miura")
        @app_commands.describe(prompt="Qué quieres preguntarle a Miura")
        async def miura(interaction: discord.Interaction, prompt: str):
            await self._handle_slash(interaction, command_name=command_name, prompt=prompt)

        if getattr(dc, "expose_native_commands", True):
            @self.tree.command(name="help", description="Muestra la ayuda de openMiura")
            async def help_cmd(interaction: discord.Interaction):
                await self._handle_slash(interaction, command_name="help")

            @self.tree.command(name="status", description="Muestra el estado e IDs")
            async def status_cmd(interaction: discord.Interaction):
                await self._handle_slash(interaction, command_name="status")

            @self.tree.command(name="reset", description="Resetea el contexto de sesión")
            async def reset_cmd(interaction: discord.Interaction):
                await self._handle_slash(interaction, command_name="reset")

            @self.tree.command(name="forget", description="Borra memoria y sesión")
            async def forget_cmd(interaction: discord.Interaction):
                await self._handle_slash(interaction, command_name="forget")

            @self.tree.command(name="link", description="Vincula este canal a una identidad global")
            @app_commands.describe(global_user_key="Identidad global, por ejemplo curro")
            async def link_cmd(interaction: discord.Interaction, global_user_key: str):
                await self._handle_slash(interaction, command_name="link", link_key=global_user_key)

        self._slash_registered = True

    async def _sync_commands_if_enabled(self) -> None:
        dc = self.settings.discord
        if dc is None or not getattr(dc, "slash_enabled", True):
            return
        if not getattr(dc, "sync_on_startup", True):
            logger.info("discord slash sync disabled")
            return

        guild_ids = [int(x) for x in (getattr(dc, "sync_guild_ids", []) or [])]
        if guild_ids:
            synced_total = 0
            for gid in guild_ids:
                guild_obj = discord.Object(id=gid)
                self.tree.copy_global_to(guild=guild_obj)
                synced = await self.tree.sync(guild=guild_obj)
                synced_total += len(synced)
                logger.info("discord slash synced guild=%s count=%s", gid, len(synced))
            logger.info("discord slash sync complete guilds=%s total=%s", len(guild_ids), synced_total)
            return

        synced = await self.tree.sync()
        logger.info("discord slash sync global count=%s", len(synced))

    def _is_allowed(self, *, guild_id: int | None, channel_id: int, user_id: int, is_dm: bool) -> bool:
        dc = self.settings.discord
        if dc is None:
            return True
        al = getattr(dc, "allowlist", None)
        if not al or not getattr(al, "enabled", False):
            return True

        allow_users = set(getattr(al, "allow_user_ids", []) or [])
        allow_channels = set(getattr(al, "allow_channel_ids", []) or [])
        allow_guilds = set(getattr(al, "allow_guild_ids", []) or [])
        allow_dm = bool(getattr(al, "allow_dm", True))

        if is_dm and not allow_dm:
            return False
        if not allow_users and not allow_channels and not allow_guilds:
            return False
        if allow_users and user_id not in allow_users:
            return False
        if allow_channels and channel_id not in allow_channels:
            return False
        if not is_dm and allow_guilds and (guild_id is None or guild_id not in allow_guilds):
            return False
        return True

    async def _send_chunked(self, message: discord.Message, text: str) -> None:
        parts = chunk_text(text)
        reply_as_reply = bool(getattr(self.settings.discord, "reply_as_reply", True)) if self.settings.discord else True
        for idx, part in enumerate(parts):
            if idx == 0 and reply_as_reply:
                try:
                    await message.reply(part, mention_author=False)
                    continue
                except Exception:
                    logger.exception("discord reply() failed; falling back to channel.send()")
            await message.channel.send(part)

    async def _respond_interaction_chunked(
        self,
        interaction: discord.Interaction,
        text: str,
        *,
        ephemeral: bool = False,
    ) -> None:
        parts = chunk_text(text)
        if not parts:
            parts = [""]
        if interaction.response.is_done():
            await interaction.followup.send(parts[0], ephemeral=ephemeral)
        else:
            await interaction.response.send_message(parts[0], ephemeral=ephemeral)
        for part in parts[1:]:
            await interaction.followup.send(part, ephemeral=ephemeral)

    async def _call_gateway(self, payload: dict) -> str:
        data = await post_inbound_to_gateway(
            gateway_url=self.gateway_url,
            payload=payload,
            timeout_s=self.http_timeout_s,
        )
        return (data.get("text") or "").strip()

    async def _handle_slash(
        self,
        interaction: discord.Interaction,
        *,
        command_name: str,
        prompt: str | None = None,
        link_key: str | None = None,
    ) -> None:
        dc = self.settings.discord
        if dc is None or not dc.bot_token:
            return

        channel = interaction.channel
        user = interaction.user
        guild = interaction.guild
        is_dm = guild is None
        guild_id = guild.id if guild else None
        channel_id = channel.id if channel else 0
        user_id = user.id

        if not self._is_allowed(guild_id=guild_id, channel_id=channel_id, user_id=user_id, is_dm=is_dm):
            deny = getattr(getattr(dc, "allowlist", None), "deny_message", "⛔ No autorizado.")
            await self._respond_interaction_chunked(interaction, deny, ephemeral=True)
            return

        text = build_command_text(command_name, prompt, link_key=link_key)
        if not text:
            await self._respond_interaction_chunked(interaction, "ℹ️ Comando vacío.", ephemeral=True)
            return

        payload = extract_inbound_payload(
            message_text=text,
            author_id=user_id,
            channel_id=channel_id,
            guild_id=guild_id,
            message_id=None,
            mentions_bot=True,
            is_dm=is_dm,
            source="slash",
            interaction_id=interaction.id,
            command_name=command_name,
            attachments=None,
        )

        try:
            reply_text = await self._call_gateway(payload)
            await self._respond_interaction_chunked(interaction, reply_text or "✅ OK")
        except Exception:
            logger.exception("discord slash gateway call failed command=%s user=%s", command_name, user_id)
            await self._respond_interaction_chunked(interaction, "⚠️ Error interno procesando el comando.", ephemeral=True)

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        dc = self.settings.discord
        if dc is None or not dc.bot_token:
            return

        is_dm = message.guild is None
        mentions_bot = bool(self.user and self.user in message.mentions)
        raw_text = (message.content or "").strip()
        if not should_process_message(
            text=raw_text,
            is_dm=is_dm,
            mentions_bot=mentions_bot,
            mention_only=bool(getattr(dc, "mention_only", True)),
        ) and not message.attachments:
            return

        bot_user_id = getattr(self.user, "id", None)
        text = strip_bot_mention(raw_text, bot_user_id)
        guild_id = message.guild.id if message.guild else None
        channel_id = message.channel.id
        user_id = message.author.id
        message_id = message.id

        if not self._is_allowed(guild_id=guild_id, channel_id=channel_id, user_id=user_id, is_dm=is_dm):
            deny = getattr(getattr(dc, "allowlist", None), "deny_message", "⛔ No autorizado.")
            logger.warning("discord deny guild=%s channel=%s user=%s is_dm=%s", guild_id, channel_id, user_id, is_dm)
            await self._send_chunked(message, deny)
            return

        attachments = normalize_attachments(
            message.attachments,
            max_items=int(getattr(dc, "max_attachment_items", 4) or 4),
        )
        text = merge_text_and_attachments(
            text,
            attachments,
            include_attachments_in_text=bool(getattr(dc, "include_attachments_in_text", True)),
        )
        if not text:
            return

        payload = extract_inbound_payload(
            message_text=text,
            author_id=user_id,
            channel_id=channel_id,
            guild_id=guild_id,
            message_id=message_id,
            mentions_bot=mentions_bot,
            is_dm=is_dm,
            source="message",
            attachments=attachments,
        )

        logger.info(
            "discord inbound guild=%s channel=%s user=%s is_dm=%s text_len=%s attachments=%s",
            guild_id,
            channel_id,
            user_id,
            is_dm,
            len(text),
            len(attachments),
        )

        try:
            reply_text = await self._call_gateway(payload)
            if reply_text:
                await self._send_chunked(message, reply_text)
        except Exception:
            logger.exception("discord gateway call failed guild=%s channel=%s user=%s", guild_id, channel_id, user_id)
            await self._send_chunked(message, "⚠️ Error interno procesando el mensaje.")


async def amain() -> None:
    config_path = os.environ.get("OPENMIURA_CONFIG", "configs/openmiura.yaml")
    settings = load_settings(config_path)
    if not settings.discord or not settings.discord.bot_token:
        raise RuntimeError(
            "Missing Discord bot token. Set discord.bot_token in YAML or OPENMIURA_DISCORD_BOT_TOKEN in the environment."
        )

    client = OpenMiuraDiscordClient(config_path=config_path)
    await client.start(settings.discord.bot_token)


def main() -> None:
    asyncio.run(amain())


if __name__ == "__main__":
    main()
