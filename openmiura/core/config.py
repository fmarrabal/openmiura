from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"1", "true", "yes", "y", "on"}:
            return True
        if v in {"0", "false", "no", "n", "off", ""}:
            return False
    return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _as_int_list(value: Any) -> list[int]:
    if not value:
        return []
    out: list[int] = []
    for item in value:
        try:
            out.append(int(item))
        except Exception:
            pass
    return out




def _env_bool_override(env_name: str, cfg_value: Any, default: bool = False) -> bool:
    raw = os.environ.get(env_name)
    if raw is not None:
        return _as_bool(raw, default)
    return _as_bool(cfg_value, default)


def _env_list_override(env_name: str, cfg_value: Any) -> list[str]:
    raw = os.environ.get(env_name)
    if raw is not None:
        return [item.strip() for item in str(raw).split(',') if item.strip()]
    return [str(item).strip() for item in (cfg_value or []) if str(item).strip()]

def _expand_env(value: Any) -> Any:
    if isinstance(value, str):
        if value.startswith("env:"):
            raw = value[4:]
            env_name, has_default, default_value = raw.partition("|")
            env_name = env_name.strip()
            if env_name:
                resolved = os.environ.get(env_name)
                if resolved not in {None, ""}:
                    return resolved
            return os.path.expandvars(default_value) if has_default else ""
        return os.path.expandvars(value)
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    return value


def resolve_config_related_path(
    config_path: str | Path | None,
    raw_path: str | Path | None,
    *,
    default_path: str,
) -> Path:
    candidate = Path(str(raw_path or default_path).strip() or default_path)
    if candidate.is_absolute():
        return candidate.expanduser().resolve()

    if config_path is None or str(config_path).strip() == "":
        return candidate.expanduser().resolve()

    base_dir = Path(config_path).expanduser().resolve().parent
    direct = (base_dir / candidate).resolve()
    parts = list(candidate.parts)
    if direct.exists() or not parts:
        return direct

    if len(parts) > 1 and parts[0] == base_dir.name:
        return (base_dir / Path(*parts[1:])).resolve()

    if len(parts) == 1 and parts[0] == 'skills':
        project_candidate = (base_dir.parent / 'skills').resolve()
        if project_candidate.exists():
            return project_candidate

    return direct


def _parse_scope_rbac(raw: Any):
    raw = raw or {}
    return ScopeRBACSettings(
        username_roles={str(k).strip(): str(v).strip() for k, v in dict(raw.get("username_roles") or {}).items() if str(k).strip() and str(v).strip()},
        user_key_roles={str(k).strip(): str(v).strip() for k, v in dict(raw.get("user_key_roles") or {}).items() if str(k).strip() and str(v).strip()},
        permission_grants={
            str(role).strip(): [str(x).strip() for x in (items or []) if str(x).strip()]
            for role, items in dict(raw.get("permission_grants") or {}).items()
            if str(role).strip()
        },
        permission_denies={
            str(role).strip(): [str(x).strip() for x in (items or []) if str(x).strip()]
            for role, items in dict(raw.get("permission_denies") or {}).items()
            if str(role).strip()
        },
        role_inherits={
            str(role).strip(): [str(x).strip() for x in (items or []) if str(x).strip()]
            for role, items in dict(raw.get("role_inherits") or {}).items()
            if str(role).strip()
        },
        role_scope_access={
            str(role).strip(): str(value).strip()
            for role, value in dict(raw.get("role_scope_access") or {}).items()
            if str(role).strip() and str(value).strip()
        },
    )


@dataclass(frozen=True)
class RuntimeSettings:
    history_limit: int = 12
    default_session_prefix: dict[str, str] = field(
        default_factory=lambda: {
            "http": "http",
            "telegram": "tg",
            "slack": "slack",
            "discord": "dc",
            "mcp": "mcp",
        }
    )
    pending_confirmation_ttl_s: int = 900
    confirmation_cleanup_interval_s: int = 60
    worker_mode: str = "external"


@dataclass(frozen=True)
class ServerSettings:
    host: str = "127.0.0.1"
    port: int = 8081


@dataclass(frozen=True)
class StorageSettings:
    backend: str = "sqlite"
    db_path: str = "data/audit.db"
    database_url: str = ""
    backup_dir: str = "data/backups"
    auto_migrate: bool = True


@dataclass(frozen=True)
class LLMSettings:
    provider: str = "ollama"
    base_url: str = "http://127.0.0.1:11434"
    model: str = "qwen2.5:7b-instruct"
    timeout_s: int = 60
    api_key_env_var: str = ""
    anthropic_version: str = "2023-06-01"
    max_output_tokens: int = 2048


@dataclass(frozen=True)
class TelegramAllowlistSettings:
    enabled: bool = False
    allow_user_ids: list[int] = field(default_factory=list)
    allow_chat_ids: list[int] = field(default_factory=list)
    allow_groups: bool = False
    deny_message: str = "⛔ No autorizado. Pide acceso al administrador."


@dataclass(frozen=True)
class TelegramSettings:
    bot_token: str = ""
    mode: str = "polling"
    webhook_secret: str = ""
    allowlist: TelegramAllowlistSettings = field(default_factory=TelegramAllowlistSettings)


@dataclass(frozen=True)
class SlackAllowlistSettings:
    enabled: bool = False
    allow_team_ids: list[str] = field(default_factory=list)
    allow_channel_ids: list[str] = field(default_factory=list)
    allow_im: bool = True
    deny_message: str = "⛔ No autorizado. Pide acceso al administrador."


@dataclass(frozen=True)
class SlackSettings:
    bot_token: str = ""
    signing_secret: str = ""
    bot_user_id: str = ""
    reply_in_thread: bool = True
    allowlist: SlackAllowlistSettings = field(default_factory=SlackAllowlistSettings)


@dataclass(frozen=True)
class DiscordAllowlistSettings:
    enabled: bool = False
    allow_user_ids: list[int] = field(default_factory=list)
    allow_channel_ids: list[int] = field(default_factory=list)
    allow_guild_ids: list[int] = field(default_factory=list)
    allow_dm: bool = True
    deny_message: str = "⛔ No autorizado. Pide acceso al administrador."


@dataclass(frozen=True)
class DiscordSettings:
    bot_token: str = ""
    application_id: str = ""
    mention_only: bool = True
    reply_as_reply: bool = True
    slash_enabled: bool = True
    slash_command_name: str = "miura"
    sync_on_startup: bool = True
    sync_guild_ids: list[int] = field(default_factory=list)
    expose_native_commands: bool = True
    include_attachments_in_text: bool = True
    max_attachment_items: int = 4
    allowlist: DiscordAllowlistSettings = field(default_factory=DiscordAllowlistSettings)


@dataclass(frozen=True)
class VaultSettings:
    enabled: bool = False
    passphrase_env_var: str = "OPENMIURA_VAULT_PASSPHRASE"
    pbkdf2_iterations: int = 390000


@dataclass(frozen=True)
class MemorySettings:
    enabled: bool = True
    embed_model: str = "nomic-embed-text"
    embed_base_url: str = "http://127.0.0.1:11434"
    top_k: int = 6
    min_score: float = 0.25
    scan_limit: int = 400
    max_items_per_user: int = 2000
    dedupe_threshold: float = 0.92
    store_user_facts: bool = True
    vault: VaultSettings = field(default_factory=VaultSettings)
    short_ttl_s: int = 86400
    medium_ttl_s: int = 2592000
    short_promote_repeat: int = 3
    medium_promote_access: int = 5


@dataclass(frozen=True)
class WebFetchSettings:
    timeout_s: int = 20
    max_bytes: int = 250000
    allow_all_domains: bool = True
    allowed_domains: list[str] = field(default_factory=list)
    block_private_ips: bool = True


@dataclass(frozen=True)
class TerminalToolSettings:
    enabled: bool = True
    timeout_s: int = 30
    max_output_chars: int = 12000
    shell_executable: str = ""
    allow_shell: bool = True
    allow_shell_metacharacters: bool = True
    allow_multiline: bool = False
    require_explicit_allowlist: bool = False
    allowed_commands: list[str] = field(default_factory=list)
    blocked_commands: list[str] = field(default_factory=list)
    blocked_patterns: list[str] = field(default_factory=list)
    max_timeout_s: int = 120
    role_policies: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolsSettings:
    sandbox_dir: str = "data/sandbox"
    web_fetch: WebFetchSettings = field(default_factory=WebFetchSettings)
    terminal: TerminalToolSettings = field(default_factory=TerminalToolSettings)
    tool_role_policies: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class SecretRefSettings:
    ref: str
    value: str = ""
    value_env_var: str = ""
    description: str = ""
    allowed_tools: list[str] = field(default_factory=list)
    denied_tools: list[str] = field(default_factory=list)
    allowed_roles: list[str] = field(default_factory=list)
    denied_roles: list[str] = field(default_factory=list)
    allowed_tenants: list[str] = field(default_factory=list)
    allowed_workspaces: list[str] = field(default_factory=list)
    allowed_environments: list[str] = field(default_factory=list)
    allowed_domains: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SecretsSettings:
    enabled: bool = False
    redact_logs: bool = True
    refs: dict[str, SecretRefSettings] = field(default_factory=dict)





@dataclass(frozen=True)
class EvaluationSettings:
    enabled: bool = True
    suites_path: str = "evaluations.yaml"
    persist_results: bool = True
    max_cases_per_run: int = 200
    default_latency_budget_ms: float = 5000.0


@dataclass(frozen=True)
class CostBudgetSettings:
    name: str = ""
    enabled: bool = True
    group_by: str = "tenant"
    budget_amount: float = 0.0
    window_hours: int = 24 * 30
    warning_threshold: float = 0.8
    critical_threshold: float = 1.0
    tenant_id: str = ""
    workspace_id: str = ""
    environment: str = ""
    agent_name: str = ""
    workflow_name: str = ""
    provider: str = ""
    model: str = ""


@dataclass(frozen=True)
class CostGovernanceSettings:
    enabled: bool = True
    default_window_hours: int = 24 * 30
    default_scan_limit: int = 2000
    budgets: list[CostBudgetSettings] = field(default_factory=list)


@dataclass(frozen=True)
class SandboxSelectorSettings:
    name: str = ""
    profile: str = ""
    roles: list[str] = field(default_factory=list)
    tenants: list[str] = field(default_factory=list)
    workspaces: list[str] = field(default_factory=list)
    environments: list[str] = field(default_factory=list)
    channels: list[str] = field(default_factory=list)
    agents: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SandboxSettings:
    enabled: bool = True
    default_profile: str = "local-safe"
    role_profiles: dict[str, str] = field(default_factory=dict)
    profiles: dict[str, dict[str, Any]] = field(default_factory=dict)
    selectors: list[SandboxSelectorSettings] = field(default_factory=list)


@dataclass(frozen=True)
class AdminSettings:
    enabled: bool = False
    token: str = ""
    max_search_results: int = 100
    rate_limit_per_minute: int = 60


@dataclass(frozen=True)
class MCPSettings:
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8091
    sse_path: str = "/mcp"


@dataclass(frozen=True)
class BrokerSettings:
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8081
    base_path: str = "/broker"
    token: str = ""
    rate_limit_per_minute: int = 120
    auth_rate_limit_per_minute: int = 20


@dataclass(frozen=True)
class OIDCSettings:
    enabled: bool = False
    issuer_url: str = ""
    discovery_url: str = ""
    client_id: str = ""
    client_secret: str = ""
    client_secret_env_var: str = "OPENMIURA_OIDC_CLIENT_SECRET"
    authorize_url: str = ""
    token_url: str = ""
    userinfo_url: str = ""
    jwks_url: str = ""
    end_session_url: str = ""
    redirect_path: str = "/broker/auth/oidc/callback"
    post_logout_redirect_path: str = "/ui"
    scopes: list[str] = field(default_factory=lambda: ["openid", "profile", "email"])
    subject_claim: str = "sub"
    email_claim: str = "email"
    username_claim: str = "preferred_username"
    group_claim: str = "groups"
    tenant_claim: str = "tenant_id"
    workspace_claim: str = "workspace_id"
    environment_claim: str = "environment"
    allowed_email_domains: list[str] = field(default_factory=list)
    group_role_mapping: dict[str, str] = field(default_factory=dict)
    default_role: str = "user"
    auto_provision_users: bool = True
    use_pkce: bool = True
    state_ttl_s: int = 600
    prompt: str = "login"


@dataclass(frozen=True)
class AuthSettings:
    enabled: bool = False
    session_ttl_s: int = 86400
    bootstrap_admin_username_env: str = "OPENMIURA_UI_ADMIN_USERNAME"
    bootstrap_admin_password_env: str = "OPENMIURA_UI_ADMIN_PASSWORD"
    session_idle_ttl_s: int = 0
    max_sessions_per_user: int = 0
    session_rotation_interval_s: int = 0
    api_token_default_ttl_s: int = 0
    api_token_idle_ttl_s: int = 0
    api_token_rotation_interval_s: int = 0
    session_cookie_enabled: bool = False
    session_cookie_name: str = "openmiura_session"
    session_cookie_secure: bool = False
    session_cookie_samesite: str = "lax"
    csrf_enabled: bool = False
    csrf_cookie_name: str = "openmiura_csrf"
    csrf_header_name: str = "X-CSRF-Token"
    oidc: OIDCSettings = field(default_factory=OIDCSettings)


@dataclass(frozen=True)
class ScopeRBACSettings:
    username_roles: dict[str, str] = field(default_factory=dict)
    user_key_roles: dict[str, str] = field(default_factory=dict)
    permission_grants: dict[str, list[str]] = field(default_factory=dict)
    permission_denies: dict[str, list[str]] = field(default_factory=dict)
    role_inherits: dict[str, list[str]] = field(default_factory=dict)
    role_scope_access: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class EnvironmentScopeSettings:
    environment: str = "prod"
    display_name: str = ""
    settings_overrides: dict[str, Any] = field(default_factory=dict)
    rbac: ScopeRBACSettings = field(default_factory=ScopeRBACSettings)


@dataclass(frozen=True)
class WorkspaceScopeSettings:
    workspace_id: str = "main"
    display_name: str = ""
    environments: list[str] = field(default_factory=lambda: ["dev", "staging", "prod"])
    default_environment: str = "prod"
    settings_overrides: dict[str, Any] = field(default_factory=dict)
    environment_settings: dict[str, EnvironmentScopeSettings] = field(default_factory=dict)
    rbac: ScopeRBACSettings = field(default_factory=ScopeRBACSettings)


@dataclass(frozen=True)
class TenantScopeSettings:
    tenant_id: str = "default"
    display_name: str = ""
    settings_overrides: dict[str, Any] = field(default_factory=dict)
    workspaces: dict[str, WorkspaceScopeSettings] = field(default_factory=dict)
    rbac: ScopeRBACSettings = field(default_factory=ScopeRBACSettings)


@dataclass(frozen=True)
class TenancySettings:
    enabled: bool = False
    default_tenant_id: str = "default"
    default_workspace_id: str = "main"
    default_environment: str = "prod"
    tenant_header_name: str = "X-Tenant-Id"
    workspace_header_name: str = "X-Workspace-Id"
    environment_header_name: str = "X-Environment"
    allow_request_scope_override: bool = True
    tenants: dict[str, TenantScopeSettings] = field(default_factory=dict)


@dataclass(frozen=True)
class Settings:
    server: ServerSettings
    storage: StorageSettings
    llm: LLMSettings
    runtime: RuntimeSettings
    agents: dict[str, dict[str, Any]] = field(default_factory=dict)
    telegram: TelegramSettings | None = None
    slack: SlackSettings | None = None
    discord: DiscordSettings | None = None
    memory: MemorySettings | None = None
    tools: ToolsSettings | None = None
    admin: AdminSettings | None = None
    mcp: MCPSettings | None = None
    broker: BrokerSettings | None = None
    auth: AuthSettings | None = None
    tenancy: TenancySettings | None = None
    secrets: SecretsSettings | None = None
    sandbox: SandboxSettings | None = None
    evaluations: EvaluationSettings | None = None
    cost_governance: CostGovernanceSettings | None = None
    agents_path: str = "agents.yaml"
    policies_path: str = "policies.yaml"
    skills_path: str = "../skills"
    config_path: str = ""


def load_settings(path: str) -> Settings:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    raw_cfg = _expand_env(yaml.safe_load(p.read_text(encoding="utf-8")) or {})

    server_raw = raw_cfg.get("server", {}) or {}
    server = ServerSettings(
        host=str(server_raw.get("host", "127.0.0.1")),
        port=_as_int(server_raw.get("port", 8081), 8081),
    )

    storage_raw = raw_cfg.get("storage", {}) or {}
    storage = StorageSettings(
        backend=str(storage_raw.get("backend", "sqlite") or "sqlite"),
        db_path=str(storage_raw.get("db_path", "data/audit.db")),
        database_url=str(storage_raw.get("database_url", "")),
        backup_dir=str(storage_raw.get("backup_dir", "data/backups")),
        auto_migrate=_as_bool(storage_raw.get("auto_migrate", True), True),
    )

    llm_raw = raw_cfg.get("llm", {}) or {}
    provider = str(llm_raw.get("provider", "ollama") or "ollama").strip().lower()
    default_base_urls = {
        "ollama": "http://127.0.0.1:11434",
        "openai": "https://api.openai.com/v1",
        "kimi": "https://api.moonshot.ai/v1",
        "anthropic": "https://api.anthropic.com/v1",
    }
    default_key_env = {
        "openai": "OPENAI_API_KEY",
        "kimi": "OPENMIURA_KIMI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
    }
    llm = LLMSettings(
        provider=provider,
        base_url=str(llm_raw.get("base_url", default_base_urls.get(provider, "http://127.0.0.1:11434"))),
        model=str(llm_raw.get("model", "qwen2.5:7b-instruct")),
        timeout_s=_as_int(llm_raw.get("timeout_s", 60), 60),
        api_key_env_var=str(llm_raw.get("api_key_env_var", default_key_env.get(provider, ""))),
        anthropic_version=str(llm_raw.get("anthropic_version", "2023-06-01")),
        max_output_tokens=_as_int(llm_raw.get("max_output_tokens", 2048), 2048),
    )

    runtime_raw = raw_cfg.get("runtime", {}) or {}
    runtime = RuntimeSettings(
        history_limit=_as_int(runtime_raw.get("history_limit", 12), 12),
        default_session_prefix=runtime_raw.get(
            "default_session_prefix",
            {
                "http": "http",
                "telegram": "tg",
                "slack": "slack",
                "discord": "dc",
                "mcp": "mcp",
            },
        ),
        pending_confirmation_ttl_s=_as_int(runtime_raw.get("pending_confirmation_ttl_s", 900), 900),
        confirmation_cleanup_interval_s=_as_int(runtime_raw.get("confirmation_cleanup_interval_s", 60), 60),
        worker_mode=str(runtime_raw.get("worker_mode", "external") or "external"),
    )

    agents = raw_cfg.get("agents", {}) or {}

    telegram_raw = raw_cfg.get("telegram", {}) or {}
    telegram_allowlist_raw = telegram_raw.get("allowlist", {}) or {}
    telegram = TelegramSettings(
        bot_token=str(telegram_raw.get("bot_token") or os.environ.get("OPENMIURA_TELEGRAM_BOT_TOKEN", "")),
        mode=str(telegram_raw.get("mode", "polling")),
        webhook_secret=str(telegram_raw.get("webhook_secret") or os.environ.get("OPENMIURA_TELEGRAM_WEBHOOK_SECRET", "")),
        allowlist=TelegramAllowlistSettings(
            enabled=_as_bool(telegram_allowlist_raw.get("enabled", False)),
            allow_user_ids=_as_int_list(telegram_allowlist_raw.get("allow_user_ids")),
            allow_chat_ids=_as_int_list(telegram_allowlist_raw.get("allow_chat_ids")),
            allow_groups=_as_bool(telegram_allowlist_raw.get("allow_groups", False)),
            deny_message=str(telegram_allowlist_raw.get("deny_message", "⛔ No autorizado. Pide acceso al administrador.")),
        ),
    )

    slack_raw = raw_cfg.get("slack", {}) or {}
    slack_allowlist_raw = slack_raw.get("allowlist", {}) or {}
    slack = SlackSettings(
        bot_token=str(slack_raw.get("bot_token") or os.environ.get("OPENMIURA_SLACK_BOT_TOKEN", "")),
        signing_secret=str(slack_raw.get("signing_secret") or os.environ.get("OPENMIURA_SLACK_SIGNING_SECRET", "")),
        bot_user_id=str(slack_raw.get("bot_user_id") or os.environ.get("OPENMIURA_SLACK_BOT_USER_ID", "")),
        reply_in_thread=_as_bool(slack_raw.get("reply_in_thread", True), True),
        allowlist=SlackAllowlistSettings(
            enabled=_as_bool(slack_allowlist_raw.get("enabled", False)),
            allow_team_ids=[str(x) for x in (slack_allowlist_raw.get("allow_team_ids") or [])],
            allow_channel_ids=[str(x) for x in (slack_allowlist_raw.get("allow_channel_ids") or [])],
            allow_im=_as_bool(slack_allowlist_raw.get("allow_im", True), True),
            deny_message=str(slack_allowlist_raw.get("deny_message", "⛔ No autorizado. Pide acceso al administrador.")),
        ),
    )

    discord_raw = raw_cfg.get("discord", {}) or {}
    discord_allowlist_raw = discord_raw.get("allowlist", {}) or {}
    discord = DiscordSettings(
        bot_token=str(discord_raw.get("bot_token") or os.environ.get("OPENMIURA_DISCORD_BOT_TOKEN", "")),
        application_id=str(discord_raw.get("application_id") or os.environ.get("OPENMIURA_DISCORD_APPLICATION_ID", "")),
        mention_only=_as_bool(discord_raw.get("mention_only", True), True),
        reply_as_reply=_as_bool(discord_raw.get("reply_as_reply", True), True),
        slash_enabled=_as_bool(discord_raw.get("slash_enabled", True), True),
        slash_command_name=str(discord_raw.get("slash_command_name", "miura")),
        sync_on_startup=_as_bool(discord_raw.get("sync_on_startup", True), True),
        sync_guild_ids=_as_int_list(discord_raw.get("sync_guild_ids")),
        expose_native_commands=_as_bool(discord_raw.get("expose_native_commands", True), True),
        include_attachments_in_text=_as_bool(discord_raw.get("include_attachments_in_text", True), True),
        max_attachment_items=_as_int(discord_raw.get("max_attachment_items", 4), 4),
        allowlist=DiscordAllowlistSettings(
            enabled=_as_bool(discord_allowlist_raw.get("enabled", False)),
            allow_user_ids=_as_int_list(discord_allowlist_raw.get("allow_user_ids")),
            allow_channel_ids=_as_int_list(discord_allowlist_raw.get("allow_channel_ids")),
            allow_guild_ids=_as_int_list(discord_allowlist_raw.get("allow_guild_ids")),
            allow_dm=_as_bool(discord_allowlist_raw.get("allow_dm", True), True),
            deny_message=str(discord_allowlist_raw.get("deny_message", "⛔ No autorizado. Pide acceso al administrador.")),
        ),
    )

    memory_raw = raw_cfg.get("memory", {}) or {}
    vault_raw = memory_raw.get("vault", {}) or {}
    vault = VaultSettings(
        enabled=_env_bool_override("OPENMIURA_VAULT_ENABLED", vault_raw.get("enabled", False), False),
        passphrase_env_var=str(vault_raw.get("passphrase_env_var", "OPENMIURA_VAULT_PASSPHRASE")),
        pbkdf2_iterations=_as_int(vault_raw.get("pbkdf2_iterations", 390000), 390000),
    )
    memory = MemorySettings(
        enabled=_as_bool(memory_raw.get("enabled", True), True),
        embed_model=str(memory_raw.get("embed_model", "nomic-embed-text")),
        embed_base_url=str(memory_raw.get("embed_base_url", "http://127.0.0.1:11434")),
        top_k=_as_int(memory_raw.get("top_k", 6), 6),
        min_score=_as_float(memory_raw.get("min_score", 0.25), 0.25),
        scan_limit=_as_int(memory_raw.get("scan_limit", 400), 400),
        max_items_per_user=_as_int(memory_raw.get("max_items_per_user", 2000), 2000),
        dedupe_threshold=_as_float(memory_raw.get("dedupe_threshold", 0.92), 0.92),
        store_user_facts=_as_bool(memory_raw.get("store_user_facts", True), True),
        vault=vault,
        short_ttl_s=_as_int(memory_raw.get("short_ttl_s", 86400), 86400),
        medium_ttl_s=_as_int(memory_raw.get("medium_ttl_s", 2592000), 2592000),
        short_promote_repeat=_as_int(memory_raw.get("short_promote_repeat", 3), 3),
        medium_promote_access=_as_int(memory_raw.get("medium_promote_access", 5), 5),
    )

    tools_raw = raw_cfg.get("tools", {}) or {}
    web_fetch_raw = tools_raw.get("web_fetch", {}) or {}
    terminal_raw = tools_raw.get("terminal", {}) or {}
    tools = ToolsSettings(
        sandbox_dir=str(tools_raw.get("sandbox_dir", "data/sandbox")),
        web_fetch=WebFetchSettings(
            timeout_s=_as_int(web_fetch_raw.get("timeout_s", 20), 20),
            max_bytes=_as_int(web_fetch_raw.get("max_bytes", 250000), 250000),
            allow_all_domains=_env_bool_override("OPENMIURA_WEB_FETCH_ALLOW_ALL_DOMAINS", web_fetch_raw.get("allow_all_domains", False), False),
            allowed_domains=_env_list_override("OPENMIURA_WEB_FETCH_ALLOWED_DOMAINS", web_fetch_raw.get("allowed_domains") or []),
            block_private_ips=_env_bool_override("OPENMIURA_WEB_FETCH_BLOCK_PRIVATE_IPS", web_fetch_raw.get("block_private_ips", True), True),
        ),
        terminal=TerminalToolSettings(
            enabled=_env_bool_override("OPENMIURA_TERMINAL_ENABLED", terminal_raw.get("enabled", False), False),
            timeout_s=_as_int(terminal_raw.get("timeout_s", 30), 30),
            max_output_chars=_as_int(terminal_raw.get("max_output_chars", 12000), 12000),
            shell_executable=str(terminal_raw.get("shell_executable", "")),
            allow_shell=_env_bool_override("OPENMIURA_TERMINAL_ALLOW_SHELL", terminal_raw.get("allow_shell", False), False),
            allow_shell_metacharacters=_env_bool_override("OPENMIURA_TERMINAL_ALLOW_METACHARACTERS", terminal_raw.get("allow_shell_metacharacters", False), False),
            allow_multiline=_as_bool(terminal_raw.get("allow_multiline", False), False),
            require_explicit_allowlist=_env_bool_override("OPENMIURA_TERMINAL_REQUIRE_EXPLICIT_ALLOWLIST", terminal_raw.get("require_explicit_allowlist", True), True),
            allowed_commands=_env_list_override("OPENMIURA_TERMINAL_ALLOWED_COMMANDS", terminal_raw.get("allowed_commands") or []),
            blocked_commands=_env_list_override("OPENMIURA_TERMINAL_BLOCKED_COMMANDS", terminal_raw.get("blocked_commands") or []),
            blocked_patterns=_env_list_override("OPENMIURA_TERMINAL_BLOCKED_PATTERNS", terminal_raw.get("blocked_patterns") or []),
            max_timeout_s=_as_int(terminal_raw.get("max_timeout_s", 120), 120),
            role_policies={
                str(role).strip().lower(): dict(cfg or {})
                for role, cfg in dict(terminal_raw.get("role_policies") or {}).items()
                if str(role).strip()
            },
        ),
        tool_role_policies={
            str(role).strip().lower(): dict(cfg or {})
            for role, cfg in dict(tools_raw.get("tool_role_policies") or {}).items()
            if str(role).strip()
        },
    )

    secrets_raw = raw_cfg.get("secrets", {}) or {}
    secret_items = dict(secrets_raw.get("refs") or {})
    secret_refs: dict[str, SecretRefSettings] = {}
    for raw_ref, raw_secret in secret_items.items():
        ref_name = str(raw_ref).strip()
        if not ref_name:
            continue
        secret_cfg = dict(raw_secret or {})
        value_env_var = str(secret_cfg.get("value_env_var", "") or "").strip()
        resolved_value = str(secret_cfg.get("value", "") or "")
        if not resolved_value and value_env_var:
            resolved_value = str(os.environ.get(value_env_var, "") or "")
        secret_refs[ref_name] = SecretRefSettings(
            ref=ref_name,
            value=resolved_value,
            value_env_var=value_env_var,
            description=str(secret_cfg.get("description", "") or ""),
            allowed_tools=[str(x).strip() for x in (secret_cfg.get("allowed_tools") or []) if str(x).strip()],
            denied_tools=[str(x).strip() for x in (secret_cfg.get("denied_tools") or []) if str(x).strip()],
            allowed_roles=[str(x).strip().lower() for x in (secret_cfg.get("allowed_roles") or []) if str(x).strip()],
            denied_roles=[str(x).strip().lower() for x in (secret_cfg.get("denied_roles") or []) if str(x).strip()],
            allowed_tenants=[str(x).strip() for x in (secret_cfg.get("allowed_tenants") or []) if str(x).strip()],
            allowed_workspaces=[str(x).strip() for x in (secret_cfg.get("allowed_workspaces") or []) if str(x).strip()],
            allowed_environments=[str(x).strip() for x in (secret_cfg.get("allowed_environments") or []) if str(x).strip()],
            allowed_domains=[str(x).strip().lower() for x in (secret_cfg.get("allowed_domains") or []) if str(x).strip()],
            metadata=dict(secret_cfg.get("metadata") or {}),
        )
    secrets = SecretsSettings(
        enabled=_as_bool(secrets_raw.get("enabled", False), False),
        redact_logs=_as_bool(secrets_raw.get("redact_logs", True), True),
        refs=secret_refs,
    )

    sandbox_raw = raw_cfg.get("sandbox", {}) or {}
    sandbox = SandboxSettings(
        enabled=_as_bool(sandbox_raw.get("enabled", True), True),
        default_profile=str(sandbox_raw.get("default_profile", "local-safe") or "local-safe"),
        role_profiles={
            str(role).strip().lower(): str(profile).strip()
            for role, profile in dict(sandbox_raw.get("role_profiles") or {}).items()
            if str(role).strip() and str(profile).strip()
        },
        profiles={
            str(name).strip(): dict(profile or {})
            for name, profile in dict(sandbox_raw.get("profiles") or {}).items()
            if str(name).strip()
        },
        selectors=[
            SandboxSelectorSettings(
                name=str(item.get("name", "") or ""),
                profile=str(item.get("profile", "") or ""),
                roles=[str(x).strip().lower() for x in (item.get("roles") or []) if str(x).strip()],
                tenants=[str(x).strip() for x in (item.get("tenants") or []) if str(x).strip()],
                workspaces=[str(x).strip() for x in (item.get("workspaces") or []) if str(x).strip()],
                environments=[str(x).strip().lower() for x in (item.get("environments") or []) if str(x).strip()],
                channels=[str(x).strip().lower() for x in (item.get("channels") or []) if str(x).strip()],
                agents=[str(x).strip().lower() for x in (item.get("agents") or []) if str(x).strip()],
                tools=[str(x).strip().lower() for x in (item.get("tools") or []) if str(x).strip()],
            )
            for item in list(sandbox_raw.get("selectors") or [])
            if isinstance(item, dict)
        ],
    )

    evaluations_raw = raw_cfg.get("evaluations", {}) or {}
    evaluations = EvaluationSettings(
        enabled=_as_bool(evaluations_raw.get("enabled", True), True),
        suites_path=str(evaluations_raw.get("suites_path", "evaluations.yaml") or "evaluations.yaml"),
        persist_results=_as_bool(evaluations_raw.get("persist_results", True), True),
        max_cases_per_run=_as_int(evaluations_raw.get("max_cases_per_run", 200), 200),
        default_latency_budget_ms=_as_float(evaluations_raw.get("default_latency_budget_ms", 5000.0), 5000.0),
    )

    cost_raw = raw_cfg.get("cost_governance", {}) or {}
    cost_governance = CostGovernanceSettings(
        enabled=_as_bool(cost_raw.get("enabled", True), True),
        default_window_hours=_as_int(cost_raw.get("default_window_hours", 24 * 30), 24 * 30),
        default_scan_limit=_as_int(cost_raw.get("default_scan_limit", 2000), 2000),
        budgets=[
            CostBudgetSettings(
                name=str(item.get("name", "") or ""),
                enabled=_as_bool(item.get("enabled", True), True),
                group_by=str(item.get("group_by", "tenant") or "tenant").strip().lower(),
                budget_amount=_as_float(item.get("budget_amount", 0.0), 0.0),
                window_hours=_as_int(item.get("window_hours", cost_raw.get("default_window_hours", 24 * 30)), _as_int(cost_raw.get("default_window_hours", 24 * 30), 24 * 30)),
                warning_threshold=_as_float(item.get("warning_threshold", 0.8), 0.8),
                critical_threshold=_as_float(item.get("critical_threshold", 1.0), 1.0),
                tenant_id=str(item.get("tenant_id", "") or ""),
                workspace_id=str(item.get("workspace_id", "") or ""),
                environment=str(item.get("environment", "") or ""),
                agent_name=str(item.get("agent_name", "") or ""),
                workflow_name=str(item.get("workflow_name", "") or ""),
                provider=str(item.get("provider", "") or ""),
                model=str(item.get("model", "") or ""),
            )
            for item in list(cost_raw.get("budgets") or [])
            if isinstance(item, dict)
        ],
    )

    admin_raw = raw_cfg.get("admin", {}) or {}
    admin = AdminSettings(
        enabled=_as_bool(admin_raw.get("enabled", False)),
        token=str(admin_raw.get("token", "")),
        max_search_results=_as_int(admin_raw.get("max_search_results", 100), 100),
        rate_limit_per_minute=_as_int(admin_raw.get("rate_limit_per_minute", 60), 60),
    )

    mcp_raw = raw_cfg.get("mcp", {}) or {}
    mcp = MCPSettings(
        enabled=_env_bool_override("OPENMIURA_MCP_ENABLED", mcp_raw.get("enabled", False), False),
        host=str(mcp_raw.get("host", "127.0.0.1")),
        port=_as_int(mcp_raw.get("port", 8091), 8091),
        sse_path=str(mcp_raw.get("sse_path", "/mcp")),
    )

    broker_raw = raw_cfg.get("broker", {}) or {}
    broker = BrokerSettings(
        enabled=_env_bool_override("OPENMIURA_BROKER_ENABLED", broker_raw.get("enabled", False), False),
        host=str(broker_raw.get("host", str(server.host))),
        port=_as_int(broker_raw.get("port", int(server.port)), int(server.port)),
        base_path=str(broker_raw.get("base_path", "/broker")),
        token=str(broker_raw.get("token") or os.environ.get("OPENMIURA_BROKER_TOKEN", "")),
        rate_limit_per_minute=_as_int(broker_raw.get("rate_limit_per_minute", 120), 120),
        auth_rate_limit_per_minute=_as_int(broker_raw.get("auth_rate_limit_per_minute", 20), 20),
    )

    auth_raw = raw_cfg.get("auth", {}) or {}
    oidc_raw = auth_raw.get("oidc", {}) or {}
    oidc = OIDCSettings(
        enabled=_as_bool(oidc_raw.get("enabled", False), False),
        issuer_url=str(oidc_raw.get("issuer_url", "") or ""),
        discovery_url=str(oidc_raw.get("discovery_url", "") or ""),
        client_id=str(oidc_raw.get("client_id", "") or ""),
        client_secret=str(oidc_raw.get("client_secret") or os.environ.get(str(oidc_raw.get("client_secret_env_var", "OPENMIURA_OIDC_CLIENT_SECRET")), "")),
        client_secret_env_var=str(oidc_raw.get("client_secret_env_var", "OPENMIURA_OIDC_CLIENT_SECRET") or "OPENMIURA_OIDC_CLIENT_SECRET"),
        authorize_url=str(oidc_raw.get("authorize_url", "") or ""),
        token_url=str(oidc_raw.get("token_url", "") or ""),
        userinfo_url=str(oidc_raw.get("userinfo_url", "") or ""),
        jwks_url=str(oidc_raw.get("jwks_url", "") or ""),
        end_session_url=str(oidc_raw.get("end_session_url", "") or ""),
        redirect_path=str(oidc_raw.get("redirect_path", "/broker/auth/oidc/callback") or "/broker/auth/oidc/callback"),
        post_logout_redirect_path=str(oidc_raw.get("post_logout_redirect_path", "/ui") or "/ui"),
        scopes=[str(x).strip() for x in (oidc_raw.get("scopes") or ["openid", "profile", "email"]) if str(x).strip()],
        subject_claim=str(oidc_raw.get("subject_claim", "sub") or "sub"),
        email_claim=str(oidc_raw.get("email_claim", "email") or "email"),
        username_claim=str(oidc_raw.get("username_claim", "preferred_username") or "preferred_username"),
        group_claim=str(oidc_raw.get("group_claim", "groups") or "groups"),
        tenant_claim=str(oidc_raw.get("tenant_claim", "tenant_id") or "tenant_id"),
        workspace_claim=str(oidc_raw.get("workspace_claim", "workspace_id") or "workspace_id"),
        environment_claim=str(oidc_raw.get("environment_claim", "environment") or "environment"),
        allowed_email_domains=[str(x).strip().lower() for x in (oidc_raw.get("allowed_email_domains") or []) if str(x).strip()],
        group_role_mapping={str(k).strip(): str(v).strip() for k, v in dict(oidc_raw.get("group_role_mapping") or {}).items() if str(k).strip() and str(v).strip()},
        default_role=str(oidc_raw.get("default_role", "user") or "user"),
        auto_provision_users=_as_bool(oidc_raw.get("auto_provision_users", True), True),
        use_pkce=_as_bool(oidc_raw.get("use_pkce", True), True),
        state_ttl_s=_as_int(oidc_raw.get("state_ttl_s", 600), 600),
        prompt=str(oidc_raw.get("prompt", "login") or "login"),
    )
    auth = AuthSettings(
        enabled=_as_bool(auth_raw.get("enabled", False), False),
        session_ttl_s=_as_int(auth_raw.get("session_ttl_s", 86400), 86400),
        bootstrap_admin_username_env=str(auth_raw.get("bootstrap_admin_username_env", "OPENMIURA_UI_ADMIN_USERNAME")),
        bootstrap_admin_password_env=str(auth_raw.get("bootstrap_admin_password_env", "OPENMIURA_UI_ADMIN_PASSWORD")),
        session_idle_ttl_s=_as_int(auth_raw.get("session_idle_ttl_s", 0), 0),
        max_sessions_per_user=_as_int(auth_raw.get("max_sessions_per_user", 0), 0),
        session_rotation_interval_s=_as_int(auth_raw.get("session_rotation_interval_s", 0), 0),
        api_token_default_ttl_s=_as_int(auth_raw.get("api_token_default_ttl_s", 0), 0),
        api_token_idle_ttl_s=_as_int(auth_raw.get("api_token_idle_ttl_s", 0), 0),
        api_token_rotation_interval_s=_as_int(auth_raw.get("api_token_rotation_interval_s", 0), 0),
        session_cookie_enabled=_as_bool(auth_raw.get("session_cookie_enabled", False), False),
        session_cookie_name=str(auth_raw.get("session_cookie_name", "openmiura_session") or "openmiura_session"),
        session_cookie_secure=_as_bool(auth_raw.get("session_cookie_secure", False), False),
        session_cookie_samesite=str(auth_raw.get("session_cookie_samesite", "lax") or "lax").lower(),
        csrf_enabled=_as_bool(auth_raw.get("csrf_enabled", False), False),
        csrf_cookie_name=str(auth_raw.get("csrf_cookie_name", "openmiura_csrf") or "openmiura_csrf"),
        csrf_header_name=str(auth_raw.get("csrf_header_name", "X-CSRF-Token") or "X-CSRF-Token"),
        oidc=oidc,
    )

    tenancy_raw = raw_cfg.get("tenancy", {}) or {}
    tenant_items = tenancy_raw.get("tenants", {}) or {}
    tenants: dict[str, TenantScopeSettings] = {}
    for raw_tenant_id, raw_tenant in dict(tenant_items).items():
        tenant_id = str((raw_tenant or {}).get("tenant_id", raw_tenant_id) or raw_tenant_id).strip() or str(raw_tenant_id).strip() or "default"
        tenant_cfg = raw_tenant or {}
        workspace_items = tenant_cfg.get("workspaces", {}) or {}
        workspaces: dict[str, WorkspaceScopeSettings] = {}
        for raw_workspace_id, raw_workspace in dict(workspace_items).items():
            workspace_cfg = raw_workspace or {}
            workspace_id = str(workspace_cfg.get("workspace_id", raw_workspace_id) or raw_workspace_id).strip() or str(raw_workspace_id).strip() or "main"
            raw_envs = workspace_cfg.get("environments") or ["dev", "staging", "prod"]
            environment_settings: dict[str, EnvironmentScopeSettings] = {}
            if isinstance(raw_envs, dict):
                envs = []
                for raw_env_name, raw_env_cfg in dict(raw_envs).items():
                    env_name = str((raw_env_cfg or {}).get("environment", raw_env_name) or raw_env_name).strip()
                    if not env_name:
                        continue
                    envs.append(env_name)
                    env_cfg = raw_env_cfg or {}
                    environment_settings[env_name] = EnvironmentScopeSettings(
                        environment=env_name,
                        display_name=str(env_cfg.get("display_name", "") or ""),
                        settings_overrides=dict(env_cfg.get("settings_overrides") or {}),
                        rbac=_parse_scope_rbac(env_cfg.get("rbac") or {}),
                    )
            else:
                envs = [str(x).strip() for x in raw_envs if str(x).strip()]
                for raw_env_name, raw_env_cfg in dict(workspace_cfg.get("environment_settings", {}) or {}).items():
                    env_name = str((raw_env_cfg or {}).get("environment", raw_env_name) or raw_env_name).strip()
                    if not env_name:
                        continue
                    environment_settings[env_name] = EnvironmentScopeSettings(
                        environment=env_name,
                        display_name=str((raw_env_cfg or {}).get("display_name", "") or ""),
                        settings_overrides=dict((raw_env_cfg or {}).get("settings_overrides") or {}),
                        rbac=_parse_scope_rbac((raw_env_cfg or {}).get("rbac") or {}),
                    )
                    if env_name not in envs:
                        envs.append(env_name)
            if not envs:
                envs = ["dev", "staging", "prod"]
            default_env = str(workspace_cfg.get("default_environment", envs[-1]) or envs[-1]).strip() or envs[-1]
            if default_env not in envs:
                envs.append(default_env)
            workspaces[workspace_id] = WorkspaceScopeSettings(
                workspace_id=workspace_id,
                display_name=str(workspace_cfg.get("display_name", "") or ""),
                environments=envs,
                default_environment=default_env,
                settings_overrides=dict(workspace_cfg.get("settings_overrides") or {}),
                environment_settings=environment_settings,
                rbac=_parse_scope_rbac(workspace_cfg.get("rbac") or {}),
            )
        tenants[tenant_id] = TenantScopeSettings(
            tenant_id=tenant_id,
            display_name=str(tenant_cfg.get("display_name", "") or ""),
            settings_overrides=dict(tenant_cfg.get("settings_overrides") or {}),
            workspaces=workspaces,
            rbac=_parse_scope_rbac(tenant_cfg.get("rbac") or {}),
        )

    tenancy = TenancySettings(
        enabled=_as_bool(tenancy_raw.get("enabled", False), False),
        default_tenant_id=str(tenancy_raw.get("default_tenant_id", "default") or "default"),
        default_workspace_id=str(tenancy_raw.get("default_workspace_id", "main") or "main"),
        default_environment=str(tenancy_raw.get("default_environment", "prod") or "prod"),
        tenant_header_name=str(tenancy_raw.get("tenant_header_name", "X-Tenant-Id") or "X-Tenant-Id"),
        workspace_header_name=str(tenancy_raw.get("workspace_header_name", "X-Workspace-Id") or "X-Workspace-Id"),
        environment_header_name=str(tenancy_raw.get("environment_header_name", "X-Environment") or "X-Environment"),
        allow_request_scope_override=_as_bool(tenancy_raw.get("allow_request_scope_override", True), True),
        tenants=tenants,
    )

    return Settings(
        config_path=str(p.resolve()),
        server=server,
        storage=storage,
        llm=llm,
        runtime=runtime,
        agents=agents,
        telegram=telegram,
        slack=slack,
        discord=discord,
        memory=memory,
        tools=tools,
        admin=admin,
        mcp=mcp,
        broker=broker,
        auth=auth,
        tenancy=tenancy,
        secrets=secrets,
        sandbox=sandbox,
        evaluations=evaluations,
        cost_governance=cost_governance,
        agents_path=str(raw_cfg.get("agents_path") or "agents.yaml"),
        policies_path=str(raw_cfg.get("policies_path") or "policies.yaml"),
        skills_path=str(raw_cfg.get("skills_path") or "../skills"),
    )
