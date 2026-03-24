from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

import app as app_module
from openmiura.core.audit import AuditStore
from openmiura.core.config import (
    AdminSettings,
    AuthSettings,
    BrokerSettings,
    LLMSettings,
    MCPSettings,
    MemorySettings,
    RuntimeSettings,
    SandboxSelectorSettings,
    SandboxSettings,
    ServerSettings,
    Settings,
    StorageSettings,
    TerminalToolSettings,
    ToolsSettings,
    load_settings,
)
from openmiura.core.sandbox import SandboxManager
from openmiura.tools.fs import FsWriteTool
from openmiura.tools.runtime import ToolContext, ToolRegistry, ToolRuntime, ToolError
from openmiura.tools.terminal_exec import TerminalExecTool
from openmiura.tools.time_now import TimeNowTool
from openmiura.tools.web_fetch import WebFetchTool


def _base_settings(tmp_path: Path, *, sandbox: SandboxSettings | None = None) -> Settings:
    return Settings(
        server=ServerSettings(),
        storage=StorageSettings(db_path=":memory:"),
        llm=LLMSettings(),
        runtime=RuntimeSettings(),
        agents={"default": {"allowed_tools": ["time_now", "terminal_exec", "fs_write", "web_fetch"]}},
        memory=MemorySettings(enabled=False),
        tools=ToolsSettings(
            sandbox_dir=str(tmp_path),
            terminal=TerminalToolSettings(enabled=True, allow_shell=False, allowed_commands=["echo"]),
        ),
        admin=AdminSettings(enabled=True, token="secret"),
        mcp=MCPSettings(),
        broker=BrokerSettings(),
        auth=AuthSettings(),
        sandbox=sandbox or SandboxSettings(),
    )


def test_load_settings_parses_sandbox_config(tmp_path: Path) -> None:
    cfg = tmp_path / "openmiura.yaml"
    cfg.write_text(
        f'''\
server:\n  host: "127.0.0.1"\n  port: 8081\nstorage:\n  db_path: ":memory:"\nllm:\n  provider: "ollama"\n  model: "qwen"\nruntime:\n  history_limit: 4\nagents:\n  default:\n    system_prompt: "base"\nmemory:\n  enabled: false\ntools:\n  sandbox_dir: "{tmp_path.as_posix()}"\nsandbox:\n  enabled: true\n  default_profile: "corporate-safe"\n  role_profiles:\n    admin: "local-safe"\n    analyst: "restricted"\n  profiles:\n    docs-only:\n      tool_permissions:\n        fs_read: true\n        fs_write: false\n  selectors:\n    - name: "prod analyst"\n      profile: "air-gapped-like"\n      roles: ["analyst"]\n      environments: ["prod"]\n''',
        encoding="utf-8",
    )

    settings = load_settings(str(cfg))
    assert settings.sandbox is not None
    assert settings.sandbox.default_profile == "corporate-safe"
    assert settings.sandbox.role_profiles["admin"] == "local-safe"
    assert settings.sandbox.profiles["docs-only"]["tool_permissions"]["fs_write"] is False
    assert settings.sandbox.selectors[0].profile == "air-gapped-like"


def test_sandbox_manager_resolves_role_and_selector(tmp_path: Path) -> None:
    settings = _base_settings(
        tmp_path,
        sandbox=SandboxSettings(
            default_profile="local-safe",
            role_profiles={"user": "restricted", "admin": "local-safe"},
            selectors=[
                SandboxSelectorSettings(
                    name="prod-admin-terminal",
                    profile="air-gapped-like",
                    roles=["admin"],
                    environments=["prod"],
                    tools=["terminal_exec"],
                )
            ],
        ),
    )
    manager = SandboxManager(settings)

    user_decision = manager.resolve(user_role="user", agent_name="default", tool_name="fs_write")
    assert user_decision.profile_name == "restricted"
    assert user_decision.allows_tool("fs_write") is False

    admin_terminal = manager.resolve(user_role="admin", environment="prod", agent_name="default", tool_name="terminal_exec")
    assert admin_terminal.profile_name == "air-gapped-like"
    assert admin_terminal.network_enabled() is False


def test_tool_runtime_filters_tools_by_sandbox_profile(tmp_path: Path) -> None:
    settings = _base_settings(
        tmp_path,
        sandbox=SandboxSettings(role_profiles={"user": "restricted", "admin": "local-safe"}),
    )
    audit = AuditStore(":memory:")
    audit.init_db()
    audit.ensure_auth_user(username="alice", password="pw", user_key="user:alice", role="user")
    audit.ensure_auth_user(username="root", password="pw", user_key="user:root", role="admin")
    registry = ToolRegistry()
    registry.register(TimeNowTool())
    registry.register(TerminalExecTool())
    registry.register(FsWriteTool())
    registry.register(WebFetchTool())
    runtime = ToolRuntime(settings=settings, audit=audit, memory=None, registry=registry)

    user_names = {item["function"]["name"] for item in runtime.available_tool_schemas("default", user_key="user:alice")}
    assert user_names == {"time_now"}

    admin_names = {item["function"]["name"] for item in runtime.available_tool_schemas("default", user_key="user:root")}
    assert {"time_now", "terminal_exec", "fs_write", "web_fetch"}.issubset(admin_names)


def test_sandbox_profile_enforces_fs_write_and_terminal(tmp_path: Path) -> None:
    settings = _base_settings(tmp_path, sandbox=SandboxSettings(role_profiles={"user": "restricted"}))
    audit = AuditStore(":memory:")
    audit.init_db()
    manager = SandboxManager(settings)
    decision = manager.resolve(user_role="user", tool_name="fs_write", agent_name="default")
    ctx = ToolContext(settings=settings, audit=audit, memory=None, sandbox_dir=tmp_path, user_key="u1", user_role="user", sandbox_decision=decision)

    try:
        FsWriteTool().run(ctx, path="note.txt", content="hola")
        assert False, "expected ToolError"
    except ToolError as exc:
        assert "denies filesystem writes" in str(exc) or "read-only" in str(exc)

    terminal_decision = manager.resolve(user_role="user", tool_name="terminal_exec", agent_name="default")
    terminal_ctx = ToolContext(settings=settings, audit=audit, memory=None, sandbox_dir=tmp_path, user_key="u1", user_role="user", sandbox_decision=terminal_decision)
    try:
        TerminalExecTool().run(terminal_ctx, command="echo hola")
        assert False, "expected ToolError"
    except ToolError as exc:
        assert "denies terminal execution" in str(exc)


def test_admin_sandbox_explain_endpoint_returns_profile() -> None:
    class _FakeAudit:
        def __init__(self):
            self.logged = []

        def table_counts(self):
            return {}

        def count_memory_items(self, *args, **kwargs):
            return 0

        def count_sessions(self, **kwargs):
            return 0

        def count_active_sessions(self, **kwargs):
            return 0

        def get_last_event(self, **kwargs):
            return None

        def log_event(self, **kwargs):
            self.logged.append(kwargs)

    class _FakeSandbox:
        def profiles_catalog(self):
            return {"restricted": {}}

        def explain(self, **kwargs):
            return {
                "ok": True,
                "profile_name": "restricted",
                "source": "role_profile",
                "matched_selector": "",
                "profile": {"tool_permissions": {"terminal_exec": False}},
                "tool_allowed": False,
                "network_enabled": False,
                "explanation": [{"scope": "role", "name": "user", "reason": "role mapped", "matched": True}],
            }

    class _FakeGateway:
        def __init__(self):
            self.settings = SimpleNamespace(
                llm=SimpleNamespace(provider="ollama", model="qwen", base_url="http://127.0.0.1:11434"),
                memory=SimpleNamespace(enabled=False, embed_model=""),
                storage=SimpleNamespace(db_path=":memory:"),
                admin=SimpleNamespace(enabled=True, token="secret", max_search_results=5),
                sandbox=SimpleNamespace(enabled=True, default_profile="local-safe"),
            )
            self.telegram = None
            self.slack = None
            self.audit = _FakeAudit()
            self.tools = SimpleNamespace(registry=SimpleNamespace(_tools={}))
            self.policy = None
            self.router = None
            self.identity = None
            self.started_at = 0.0
            self.sandbox = _FakeSandbox()

    gw = _FakeGateway()
    app = app_module.create_app(gateway_factory=lambda _config: gw)
    with TestClient(app) as client:
        response = client.post(
            "/admin/sandbox/explain",
            headers={"Authorization": "Bearer secret"},
            json={"user_role": "user", "tool_name": "terminal_exec"},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["profile_name"] == "restricted"
    assert data["tool_allowed"] is False
    assert any(item["payload"].get("action") == "sandbox_explain" for item in gw.audit.logged)
