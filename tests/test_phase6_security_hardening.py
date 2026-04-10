from __future__ import annotations

import json
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
from openmiura.tools.runtime import ToolContext, ToolError
from openmiura.tools.terminal_exec import TerminalExecTool


def _ctx(tmp_path: Path, terminal: TerminalToolSettings):
    settings = Settings(
        server=ServerSettings(),
        storage=StorageSettings(db_path=':memory:'),
        llm=LLMSettings(),
        runtime=RuntimeSettings(),
        agents={},
        memory=MemorySettings(enabled=False),
        tools=ToolsSettings(sandbox_dir=str(tmp_path), terminal=terminal),
        admin=AdminSettings(),
        mcp=MCPSettings(),
        broker=BrokerSettings(),
        auth=AuthSettings(),
    )
    audit = AuditStore(':memory:')
    audit.init_db()
    return ToolContext(settings=settings, audit=audit, memory=None, sandbox_dir=tmp_path)


def _write_config(path: Path, *, broker_rate_limit: int = 120, auth_idle_ttl_s: int = 0) -> None:
    db_path = (path.parent / 'audit.db').as_posix()
    sandbox_dir = (path.parent / 'sandbox').as_posix()
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
  base_path: "/broker"
  token: ""
  rate_limit_per_minute: {broker_rate_limit}
  auth_rate_limit_per_minute: 5
auth:
  enabled: true
  session_ttl_s: 3600
  session_idle_ttl_s: {auth_idle_ttl_s}
''',
        encoding='utf-8',
    )


def test_terminal_exec_allowlist_blocks_disallowed_command(tmp_path: Path) -> None:
    ctx = _ctx(
        tmp_path,
        TerminalToolSettings(
            enabled=True,
            allowed_commands=['python', Path(sys.executable).name],
            blocked_commands=['rm'],
            allow_shell=True,
        ),
    )
    tool = TerminalExecTool()
    try:
        tool.run(ctx, command='echo hello')
        assert False, 'expected ToolError'
    except ToolError as exc:
        assert 'allowlisted' in str(exc)


def test_api_token_rotation_revokes_previous_token(audit_store: AuditStore) -> None:
    token = audit_store.create_api_token(user_key='user:alice', label='cli', ttl_s=3600)
    rotated = audit_store.rotate_api_token(token_id=int(token['id']), user_key='user:alice', ttl_s=1800)
    assert rotated is not None
    assert rotated['token'] != token['token']
    assert audit_store.get_api_token(token['token']) is None
    assert audit_store.get_api_token(rotated['token']) is not None


def test_broker_chat_rate_limit_returns_429(tmp_path: Path, monkeypatch) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg, broker_rate_limit=1)

    def _fake_process_message(gw, inbound):
        gw.audit.get_or_create_session(inbound.channel, inbound.user_id, inbound.session_id)
        from openmiura.core.schema import OutboundMessage
        return OutboundMessage(channel='broker', user_id=inbound.user_id, session_id=inbound.session_id, agent_id='default', text='ok')

    monkeypatch.setattr('openmiura.channels.http_broker.process_message', _fake_process_message)
    monkeypatch.setattr('app.process_message', _fake_process_message)

    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    with TestClient(app) as client:
        first = client.post('/broker/chat', json={'message': 'hola', 'user_id': 'u1'})
        second = client.post('/broker/chat', json={'message': 'hola otra vez', 'user_id': 'u1'})
    assert first.status_code == 200
    assert second.status_code == 429


def test_auth_session_idle_ttl_expires_session(audit_store: AuditStore) -> None:
    user = audit_store.ensure_auth_user(username='alice', password='pw', role='user')
    session = audit_store.create_auth_session(user_id=int(user['id']), ttl_s=3600)
    assert audit_store.get_auth_session(session['token'], idle_ttl_s=1) is not None
    time.sleep(1.05)
    assert audit_store.get_auth_session(session['token'], idle_ttl_s=1) is None


def test_app_sets_security_headers(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    with TestClient(app) as client:
        response = client.get('/health')
    assert response.status_code == 200
    assert response.headers['x-request-id']
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert response.headers['x-frame-options'] == 'DENY'
