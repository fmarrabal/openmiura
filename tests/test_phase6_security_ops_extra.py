from __future__ import annotations

import os
import sys
import time
from pathlib import Path

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
    ServerSettings,
    Settings,
    StorageSettings,
    TerminalToolSettings,
    ToolsSettings,
)
from openmiura.gateway import Gateway
from openmiura.tools.runtime import ToolContext, ToolError, ToolRegistry, ToolRuntime
from openmiura.tools.terminal_exec import TerminalExecTool
from openmiura.tools.time_now import TimeNowTool


def _write_cookie_config(path: Path) -> None:
    db_path = (path.parent / "audit.db").as_posix()
    sandbox_dir = (path.parent / "sandbox").as_posix()
    path.write_text(
        f'''\
server:
  host: "127.0.0.1"
  port: 8081
storage:
  db_path: "{db_path}"
llm:
  provider: "ollama"
  base_url: "http://127.0.0.1:11434"
  model: "qwen2.5:7b-instruct"
runtime:
  history_limit: 4
agents:
  default:
    system_prompt: "base"
memory:
  enabled: false
tools:
  sandbox_dir: "{sandbox_dir}"
broker:
  enabled: true
auth:
  enabled: true
  session_ttl_s: 3600
  session_idle_ttl_s: 0
  session_cookie_enabled: true
  session_cookie_name: openmiura_session
  session_cookie_secure: false
  session_cookie_samesite: lax
  csrf_enabled: true
  csrf_cookie_name: openmiura_csrf
  csrf_header_name: X-CSRF-Token
''',
        encoding="utf-8",
    )


def test_cookie_auth_requires_csrf_for_mutating_requests(tmp_path: Path, monkeypatch) -> None:
    cfg = tmp_path / "openmiura.yaml"
    _write_cookie_config(cfg)
    monkeypatch.setenv("OPENMIURA_UI_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("OPENMIURA_UI_ADMIN_PASSWORD", "secret")

    def _fake_process_message(gw, inbound):
        gw.audit.get_or_create_session(inbound.channel, inbound.user_id, inbound.session_id)
        from openmiura.core.schema import OutboundMessage

        return OutboundMessage(
            channel="broker",
            user_id=inbound.user_id,
            session_id=inbound.session_id,
            agent_id="default",
            text=f"ok:{inbound.text}",
        )

    monkeypatch.setattr("openmiura.channels.http_broker.process_message", _fake_process_message)
    monkeypatch.setattr("app.process_message", _fake_process_message)

    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    with TestClient(app) as client:
        login = client.post("/broker/auth/login", json={"username": "admin", "password": "secret", "use_cookie_session": True})
        assert login.status_code == 200
        csrf_token = login.json()["csrf_token"]
        assert client.cookies.get("openmiura_session")
        assert client.cookies.get("openmiura_csrf") == csrf_token

        denied = client.post("/broker/chat", json={"message": "hola", "user_id": "u1"})
        assert denied.status_code == 403
        allowed = client.post("/broker/chat", json={"message": "hola", "user_id": "u1"}, headers={"X-CSRF-Token": csrf_token})
        assert allowed.status_code == 200
        assert allowed.json()["text"] == "ok:hola"


def test_terminal_role_policy_overrides_global(tmp_path: Path) -> None:
    settings = Settings(
        server=ServerSettings(),
        storage=StorageSettings(db_path=":memory:"),
        llm=LLMSettings(),
        runtime=RuntimeSettings(),
        agents={},
        memory=MemorySettings(enabled=False),
        tools=ToolsSettings(
            sandbox_dir=str(tmp_path),
            terminal=TerminalToolSettings(
                enabled=True,
                allow_shell=False,
                allow_shell_metacharacters=False,
                allowed_commands=[],
                blocked_commands=[],
                role_policies={
                    "admin": {"allowed_commands": ["echo"], "allow_shell": False},
                    "user": {"allowed_commands": ["python"], "allow_shell": False},
                },
            ),
        ),
        admin=AdminSettings(),
        mcp=MCPSettings(),
        broker=BrokerSettings(),
        auth=AuthSettings(),
    )
    audit = AuditStore(":memory:")
    audit.init_db()
    tool = TerminalExecTool()

    user_ctx = ToolContext(settings=settings, audit=audit, memory=None, sandbox_dir=tmp_path, user_key="u1", user_role="user")
    try:
        tool.run(user_ctx, command="echo hi")
        assert False, "expected ToolError"
    except ToolError as exc:
        assert "allowlisted" in str(exc)

    admin_ctx = ToolContext(settings=settings, audit=audit, memory=None, sandbox_dir=tmp_path, user_key="u2", user_role="admin")
    result = tool.run(admin_ctx, command="echo hi")
    assert '"exit_code": 0' in result


def test_api_token_idle_ttl_cleanup_revokes_stale_tokens(audit_store: AuditStore) -> None:
    token = audit_store.create_api_token(user_key="user:alice", label="cli")
    time.sleep(1.05)
    assert audit_store.get_api_token(token["token"], idle_ttl_s=1) is None
    cleaned = audit_store.cleanup_api_tokens(idle_ttl_s=1)
    assert cleaned["idle_revoked"] >= 1


def test_auth_session_rotation_revokes_previous_session(audit_store: AuditStore) -> None:
    user = audit_store.ensure_auth_user(username="alice", password="pw", role="user")
    session = audit_store.create_auth_session(user_id=int(user["id"]), ttl_s=3600)
    rotated = audit_store.rotate_auth_session(raw_token=session["token"], ttl_s=3600)
    assert rotated is not None
    assert audit_store.get_auth_session(session["token"]) is None
    assert audit_store.get_auth_session(rotated["token"]) is not None


def test_generic_tool_role_policy_filters_tools(tmp_path: Path) -> None:
    settings = Settings(
        server=ServerSettings(),
        storage=StorageSettings(db_path=":memory:"),
        llm=LLMSettings(),
        runtime=RuntimeSettings(),
        agents={"default": {"allowed_tools": ["time_now", "terminal_exec"]}},
        memory=MemorySettings(enabled=False),
        tools=ToolsSettings(
            sandbox_dir=str(tmp_path),
            terminal=TerminalToolSettings(enabled=True, allow_shell=False, allowed_commands=["echo"]),
            tool_role_policies={
                "user": {"allowed_tools": ["time_now"]},
                "admin": {"allowed_tools": ["time_now", "terminal_exec"]},
            },
        ),
        admin=AdminSettings(),
        mcp=MCPSettings(),
        broker=BrokerSettings(),
        auth=AuthSettings(),
    )
    audit = AuditStore(":memory:")
    audit.init_db()
    audit.ensure_auth_user(username="alice", password="pw", user_key="user:alice", role="user")
    audit.ensure_auth_user(username="root", password="pw", user_key="user:root", role="admin")
    registry = ToolRegistry()
    registry.register(TimeNowTool())
    registry.register(TerminalExecTool())
    runtime = ToolRuntime(settings=settings, audit=audit, memory=None, registry=registry)

    user_names = {item["function"]["name"] for item in runtime.available_tool_schemas("default", user_key="user:alice")}
    assert user_names == {"time_now"}

    admin_names = {item["function"]["name"] for item in runtime.available_tool_schemas("default", user_key="user:root")}
    assert admin_names == {"time_now", "terminal_exec"}
