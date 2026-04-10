from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import app as app_module
from openmiura.core.audit import AuditStore
from openmiura.core.config import load_settings
from openmiura.gateway import Gateway


def _write_config(path: Path) -> None:
    db_path = (path.parent / 'audit.db').as_posix()
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
  history_limit: 6
memory:
  enabled: false
broker:
  enabled: true
  token: "broker-secret"
tenancy:
  enabled: true
  default_tenant_id: "acme"
  default_workspace_id: "research"
  default_environment: "prod"
  tenants:
    acme:
      display_name: "Acme Corp"
      workspaces:
        research:
          display_name: "Research"
          environments: [dev, prod]
          default_environment: "prod"
        ops:
          display_name: "Operations"
          environments: [staging, prod]
          default_environment: "staging"
''',
        encoding='utf-8',
    )


def test_tenancy_settings_parse_catalog(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    settings = load_settings(str(cfg))
    assert settings.tenancy is not None
    assert settings.tenancy.enabled is True
    assert settings.tenancy.default_tenant_id == 'acme'
    assert 'acme' in settings.tenancy.tenants
    assert 'research' in settings.tenancy.tenants['acme'].workspaces
    assert settings.tenancy.tenants['acme'].workspaces['research'].environments == ['dev', 'prod']


def test_broker_auth_me_returns_scope_headers_and_override(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    with TestClient(app) as client:
        me = client.get(
            '/broker/auth/me',
            headers={
                'Authorization': 'Bearer broker-secret',
                'X-Tenant-Id': 'acme',
                'X-Workspace-Id': 'ops',
                'X-Environment': 'staging',
            },
        )
        assert me.status_code == 200, me.text
        data = me.json()
        assert data['tenant_id'] == 'acme'
        assert data['workspace_id'] == 'ops'
        assert data['environment'] == 'staging'
        assert data['scope_headers']['tenant'] == 'X-Tenant-Id'


def test_audit_store_persists_scope_on_sessions_and_events(tmp_path: Path) -> None:
    store = AuditStore(str(tmp_path / 'audit.db'))
    store.init_db()
    session_id = store.get_or_create_session('http', 'user:1', 's-1', tenant_id='acme', workspace_id='research', environment='prod')
    store.log_event('in', 'http', 'user:1', session_id, {'hello': 'world'}, tenant_id='acme', workspace_id='research', environment='prod')

    sessions = store.list_sessions(limit=10)
    assert sessions[0]['tenant_id'] == 'acme'
    assert sessions[0]['workspace_id'] == 'research'
    assert sessions[0]['environment'] == 'prod'

    events = store.get_recent_events(limit=10)
    assert events[0]['tenant_id'] == 'acme'
    assert events[0]['workspace_id'] == 'research'
    assert events[0]['environment'] == 'prod'
