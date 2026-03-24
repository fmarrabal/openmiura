from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Optional

from openmiura.channels.slack import SlackClient
from openmiura.channels.telegram import TelegramClient
from openmiura.core.agent_runtime import AgentRuntime
from openmiura.infrastructure.persistence.audit_store import AuditStore
from openmiura.core.config import Settings, load_settings
from openmiura.core.identity import IdentityManager
from openmiura.core.memory import MemoryEngine
from openmiura.core.vault import ContextVault
from openmiura.core.pending_confirmations import PendingConfirmationStore
from openmiura.core.secrets import SecretBroker
from openmiura.core.sandbox import SandboxManager
from openmiura.realtime import RealtimeBus
from openmiura.core.policy import PolicyEngine
from openmiura.core.router import AgentRouter
from openmiura.core.schema import InboundMessage
from openmiura.tools.fs import FsReadTool, FsWriteTool
from openmiura.tools.terminal_exec import TerminalExecTool
from openmiura.tools.runtime import ToolRegistry, ToolRuntime
from openmiura.tools.time_now import TimeNowTool
from openmiura.tools.web_fetch import WebFetchTool


@dataclass
class Gateway:
    settings: Settings
    audit: AuditStore
    router: AgentRouter
    runtime: AgentRuntime
    memory: Optional[MemoryEngine] = None
    tools: Optional[ToolRuntime] = None
    telegram: Optional[TelegramClient] = None
    slack: Optional[SlackClient] = None
    policy: Optional[PolicyEngine] = None
    identity: Optional[IdentityManager] = None
    started_at: float = field(default_factory=time.time)
    pending_confirmations: PendingConfirmationStore = field(default_factory=PendingConfirmationStore)
    realtime_bus: object | None = None
    secret_broker: SecretBroker | None = None
    sandbox: SandboxManager | None = None

    def set_pending_tool_confirmation(self, session_id: str, **payload) -> None:
        agent_id = str(payload.get("agent_id") or "default")
        self.pending_confirmations.set(session_id, agent_id=agent_id, payload=payload)
        if self.realtime_bus is not None:
            try:
                self.realtime_bus.publish(
                    "confirmation_pending",
                    session_id=session_id,
                    user_key=payload.get("user_key"),
                    agent_id=agent_id,
                    tool_name=payload.get("tool_name"),
                    args=payload.get("args") or {},
                )
            except Exception:
                pass

    def get_pending_tool_confirmation(self, session_id: str):
        return self.pending_confirmations.get(session_id)

    def pop_pending_tool_confirmation(self, session_id: str):
        return self.pending_confirmations.pop(session_id)

    def consume_pending_tool_confirmation(self, session_id: str, *, user_key: str | None = None):
        item = self.pending_confirmations.consume(session_id, user_key=user_key)
        if item is not None and self.realtime_bus is not None:
            try:
                self.realtime_bus.publish("confirmation_resolved", session_id=session_id, user_key=item.get("user_key"), decision="confirm")
            except Exception:
                pass
        return item

    def cancel_pending_tool_confirmation(self, session_id: str, *, user_key: str | None = None) -> bool:
        ok = self.pending_confirmations.cancel(session_id, user_key=user_key)
        if ok and self.realtime_bus is not None:
            try:
                self.realtime_bus.publish("confirmation_resolved", session_id=session_id, user_key=user_key, decision="cancel")
            except Exception:
                pass
        return ok

    def clear_pending_tool_confirmation(self, session_id: str) -> bool:
        return self.pending_confirmations.clear(session_id)

    def reset_pending_tool_confirmations(self, session_id: str) -> bool:
        return self.pending_confirmations.reset_session(session_id)

    def invalidate_pending_confirmation_for_agent_change(self, session_id: str, next_agent_id: str | None) -> bool:
        current_agent = getattr(getattr(self.router, "_session_agent", {}), "get", lambda *_: None)(session_id)
        if current_agent and next_agent_id and str(current_agent).strip() != str(next_agent_id).strip():
            return bool(self.pending_confirmations.invalidate_agent(session_id, str(current_agent)))
        return False

    def invalidate_pending_tool_confirmation_for_agent(self, session_id: str, agent_id: str | None) -> int:
        return self.pending_confirmations.invalidate_agent(session_id, agent_id)

    def cleanup_expired_tool_confirmations(self) -> int:
        n = self.pending_confirmations.cleanup_expired()
        if n and self.realtime_bus is not None:
            try:
                self.realtime_bus.publish("confirmation_cleanup", count=n)
            except Exception:
                pass
        return n

    @classmethod
    def from_config(cls, config_path: str | None = None) -> "Gateway":
        path = config_path or os.environ.get("OPENMIURA_CONFIG", "configs/openmiura.yaml")
        settings = load_settings(path)
        audit = AuditStore(db_path=settings.storage.db_path, backend=getattr(settings.storage, "backend", "sqlite"), database_url=getattr(settings.storage, "database_url", ""))
        if getattr(settings.storage, "auto_migrate", True):
            audit.init_db()
        auth_cfg = getattr(settings, "auth", None)
        if auth_cfg is not None and getattr(auth_cfg, "enabled", False):
            admin_user = os.environ.get(getattr(auth_cfg, "bootstrap_admin_username_env", "OPENMIURA_UI_ADMIN_USERNAME"), "").strip()
            admin_pass = os.environ.get(getattr(auth_cfg, "bootstrap_admin_password_env", "OPENMIURA_UI_ADMIN_PASSWORD"), "")
            if admin_user and admin_pass:
                try:
                    audit.ensure_auth_user(username=admin_user, password=admin_pass, user_key=f"user:{admin_user}", role="admin")
                except Exception:
                    pass
        policy = PolicyEngine(getattr(settings, "policies_path", None))
        router = AgentRouter(settings=settings, audit=audit)
        runtime = AgentRuntime(settings=settings, audit=audit)
        identity = IdentityManager(audit)

        memory: MemoryEngine | None = None
        if settings.memory and settings.memory.enabled:
            vault = ContextVault.from_env(
                enabled=getattr(settings.memory.vault, "enabled", False),
                passphrase_env_var=getattr(settings.memory.vault, "passphrase_env_var", "OPENMIURA_VAULT_PASSPHRASE"),
                iterations=getattr(settings.memory.vault, "pbkdf2_iterations", 390000),
            )
            memory = MemoryEngine(
                audit=audit,
                base_url=getattr(settings.memory, "embed_base_url", settings.llm.base_url),
                embed_model=settings.memory.embed_model,
                timeout_s=settings.llm.timeout_s,
                top_k=settings.memory.top_k,
                min_score=settings.memory.min_score,
                scan_limit=settings.memory.scan_limit,
                max_items_per_user=settings.memory.max_items_per_user,
                dedupe_threshold=settings.memory.dedupe_threshold,
                store_user_facts=settings.memory.store_user_facts,
                vault=vault,
                short_ttl_s=getattr(settings.memory, "short_ttl_s", 86400),
                medium_ttl_s=getattr(settings.memory, "medium_ttl_s", 2592000),
                short_promote_repeat=getattr(settings.memory, "short_promote_repeat", 3),
                medium_promote_access=getattr(settings.memory, "medium_promote_access", 5),
            )

        secret_broker = SecretBroker(settings=getattr(settings, "secrets", None), audit=audit, policy=policy)
        sandbox = SandboxManager(settings=settings, audit=audit)

        reg = ToolRegistry()
        reg.register(TimeNowTool())
        reg.register(WebFetchTool())
        reg.register(FsReadTool())
        reg.register(FsWriteTool())
        if settings.tools is None or getattr(getattr(settings.tools, 'terminal', None), 'enabled', True):
            reg.register(TerminalExecTool())

        skill_loader = getattr(runtime, "skill_loader", None)
        if skill_loader is not None:
            try:
                skill_loader.register_skill_tools(reg)
            except Exception:
                pass

        event_bus = RealtimeBus()
        tools = ToolRuntime(
            settings=settings,
            audit=audit,
            memory=memory,
            registry=reg,
            policy=policy,
            skill_loader=skill_loader,
            event_publisher=event_bus.publish,
            secret_broker=secret_broker,
            sandbox_manager=sandbox,
        )

        telegram: TelegramClient | None = None
        if settings.telegram and settings.telegram.bot_token:
            telegram = TelegramClient(bot_token=settings.telegram.bot_token)
        slack: SlackClient | None = None
        if settings.slack and settings.slack.bot_token:
            slack = SlackClient(bot_token=settings.slack.bot_token)

        gw = cls(
            settings=settings,
            audit=audit,
            router=router,
            runtime=runtime,
            memory=memory,
            tools=tools,
            telegram=telegram,
            slack=slack,
            policy=policy,
            identity=identity,
            pending_confirmations=PendingConfirmationStore(
                ttl_s=getattr(settings.runtime, "pending_confirmation_ttl_s", 900)
            ),
            realtime_bus=event_bus,
            secret_broker=secret_broker,
            sandbox=sandbox,
        )
        gw.audit.log_event(
            direction="system",
            channel="system",
            user_id="system",
            session_id="system",
            payload={"event": "startup", "config_path": path},
        )
        if gw.realtime_bus is not None:
            try:
                gw.realtime_bus.publish("system", event="startup", config_path=path)
            except Exception:
                pass
        return gw

    def reload_dynamic_configs(self, force: bool = False) -> dict[str, object]:
        agents = self.router.reload_agents(force=force)
        policies = (
            self.policy.reload(force=force)
            if self.policy is not None
            else {"changed": False, "reason": "policy_not_configured"}
        )
        return {"agents": agents, "policies": policies}

    def effective_user_key(self, channel_user_key: str) -> str:
        if self.identity is not None:
            return self.identity.resolve(channel_user_key) or channel_user_key
        global_key = self.audit.get_identity(channel_user_key)
        return global_key or channel_user_key

    def has_identity_link(self, channel_user_key: str) -> bool:
        return self.effective_user_key(channel_user_key) != channel_user_key

    def link_hint(self, channel_user_key: str) -> str:
        if self.has_identity_link(channel_user_key):
            return ""
        return "\n\n💡 Puedes vincular tu cuenta con /link <tu_nombre>."

    def derive_session_id(self, msg: InboundMessage, user_key: str) -> str:
        if msg.session_id is not None and str(msg.session_id).strip():
            return str(msg.session_id).strip()
        ch = (msg.channel or "http").strip().lower()
        if ch == "telegram":
            md = msg.metadata or {}
            chat_id = md.get("chat_id")
            try:
                chat_id_int = int(chat_id) if chat_id is not None else None
            except Exception:
                chat_id_int = None
            if chat_id_int is None:
                _, from_id = telegram_ids_from_msg(msg)
                chat_id_int = from_id
            return f"tg-{chat_id_int}-{user_key}"
        prefix = str((self.settings.runtime.default_session_prefix or {}).get(ch, ch))
        return f"{prefix}-{user_key}"

    def is_telegram_allowed(self, chat_id: int | None, from_id: int | None) -> bool:
        if self.settings.telegram is None:
            return True
        al = getattr(self.settings.telegram, "allowlist", None)
        if not al or not getattr(al, "enabled", False):
            return True
        if chat_id is None or from_id is None:
            return False
        if chat_id < 0 and not getattr(al, "allow_groups", False):
            return False
        allow_user_ids = getattr(al, "allow_user_ids", []) or []
        allow_chat_ids = getattr(al, "allow_chat_ids", []) or []
        if not allow_user_ids and not allow_chat_ids:
            return True
        return (from_id in allow_user_ids) or (chat_id in allow_chat_ids)

    def telegram_deny_message(self) -> str:
        tg = self.settings.telegram
        if tg and getattr(tg, "allowlist", None):
            return getattr(tg.allowlist, "deny_message", "⛔ No autorizado.")
        return "⛔ No autorizado."

    def is_slack_allowed(self, team_id: str, channel_id: str, channel_type: str | None = None) -> bool:
        if self.settings.slack is None:
            return True
        al = getattr(self.settings.slack, "allowlist", None)
        if not al or not getattr(al, "enabled", False):
            return True
        allow_teams = set(getattr(al, "allow_team_ids", []) or [])
        allow_channels = set(getattr(al, "allow_channel_ids", []) or [])
        allow_im = bool(getattr(al, "allow_im", True))
        if channel_type == "im" and not allow_im:
            return False
        if not allow_teams and not allow_channels:
            return True
        if allow_teams and team_id not in allow_teams:
            return False
        if allow_channels and channel_id not in allow_channels:
            return False
        return True

    def is_discord_allowed(
        self,
        guild_id: int | None,
        channel_id: int | None,
        user_id: int | None,
        is_dm: bool = False,
    ) -> bool:
        if self.settings.discord is None:
            return True
        al = getattr(self.settings.discord, "allowlist", None)
        if not al or not getattr(al, "enabled", False):
            return True
        allow_users = set(getattr(al, "allow_user_ids", []) or [])
        allow_channels = set(getattr(al, "allow_channel_ids", []) or [])
        allow_guilds = set(getattr(al, "allow_guild_ids", []) or [])
        allow_dm = bool(getattr(al, "allow_dm", True))
        if is_dm and not allow_dm:
            return False
        if not allow_users and not allow_channels and not allow_guilds:
            return True
        if allow_users and (user_id is None or user_id not in allow_users):
            return False
        if allow_channels and (channel_id is None or channel_id not in allow_channels):
            return False
        if not is_dm and allow_guilds and (guild_id is None or guild_id not in allow_guilds):
            return False
        return True


def telegram_ids_from_msg(msg: InboundMessage) -> tuple[int | None, int | None]:
    md = msg.metadata or {}
    chat_id = md.get("chat_id")
    from_id = md.get("from_id")
    try:
        chat_id = int(chat_id) if chat_id is not None else None
    except Exception:
        chat_id = None
    try:
        from_id = int(from_id) if from_id is not None else None
    except Exception:
        from_id = None
    return chat_id, from_id
