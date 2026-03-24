from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import app as app_module
from openmiura.gateway import Gateway
from openmiura.infrastructure.persistence.audit_store import AuditStore as InfraAuditStore
from openmiura.infrastructure.persistence.db import DBConnection as InfraDBConnection
from openmiura.core.audit import AuditStore as CoreAuditStore
from openmiura.core.db import DBConnection as CoreDBConnection
from openmiura.endpoints.slack import router as legacy_slack_router
from openmiura.endpoints.telegram import router as legacy_telegram_router
from openmiura.interfaces.channels.slack.routes import router as interface_slack_router
from openmiura.interfaces.channels.telegram.routes import router as interface_telegram_router


def _write_config(path: Path) -> None:
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
  history_limit: 6
memory:
  enabled: false
tools:
  sandbox_dir: "{sandbox_dir}"
broker:
  enabled: true
  token: "broker-secret"
auth:
  enabled: true
tenancy:
  enabled: true
  default_tenant_id: "acme"
  default_workspace_id: "research"
  default_environment: "prod"
  tenants:
    acme:
      display_name: "Acme Corp"
      settings_overrides:
        auth:
          oidc:
            client_secret: "tenant-secret"
      workspaces:
        research:
          display_name: "Research"
          environments: [dev, prod]
          default_environment: "prod"
          rbac:
            username_roles:
              alice: operator
        ops:
          display_name: "Operations"
          settings_overrides:
            llm:
              model: "ops-model"
          environment_settings:
            staging:
              display_name: "Staging"
              settings_overrides:
                broker:
                  token: "ops-broker-secret"
          environments: [staging, prod]
          default_environment: "staging"
          rbac:
            username_roles:
              bob: workspace_admin
''',
        encoding='utf-8',
    )


def _seed_data(gw) -> None:
    alice = gw.audit.ensure_auth_user(
        username='alice', password='pw1', user_key='user:alice', role='user', tenant_id='acme', workspace_id='research'
    )
    bob = gw.audit.ensure_auth_user(
        username='bob', password='pw2', user_key='user:bob', role='user', tenant_id='acme', workspace_id='ops'
    )
    gw.audit.create_auth_session(user_id=int(alice['id']), tenant_id='acme', workspace_id='research', environment='prod')
    gw.audit.create_auth_session(user_id=int(bob['id']), tenant_id='acme', workspace_id='ops', environment='staging')
    research_session = gw.audit.get_or_create_session('broker', 'user:alice', 'research-session', tenant_id='acme', workspace_id='research', environment='prod')
    ops_session = gw.audit.get_or_create_session('broker', 'user:bob', 'ops-session', tenant_id='acme', workspace_id='ops', environment='staging')
    gw.audit.append_message(research_session, 'user', 'research msg')
    gw.audit.append_message(ops_session, 'user', 'ops msg')
    gw.audit.log_event('in', 'broker', 'user:alice', research_session, {'scope': 'research'}, tenant_id='acme', workspace_id='research', environment='prod')
    gw.audit.log_event('in', 'broker', 'user:bob', ops_session, {'scope': 'ops'}, tenant_id='acme', workspace_id='ops', environment='staging')
    gw.audit.add_memory_item('user:alice', 'fact', 'research memory', b'\x00\x00\x00\x00', '{}', tenant_id='acme', workspace_id='research', environment='prod')
    gw.audit.add_memory_item('user:bob', 'fact', 'ops memory', b'\x00\x00\x00\x00', '{}', tenant_id='acme', workspace_id='ops', environment='staging')
    gw.audit.log_tool_call(research_session, 'user:alice', 'default', 'time_now', '{}', True, 'research', '', 1.0)
    gw.audit.log_tool_call(ops_session, 'user:bob', 'default', 'time_now', '{}', True, 'ops', '', 1.0)


def _login(client: TestClient, username: str, password: str) -> str:
    response = client.post('/broker/auth/login', json={'username': username, 'password': password})
    assert response.status_code == 200, response.text
    return str(response.json()['token'])


def test_phase1_channel_and_persistence_shims_are_wired() -> None:
    assert legacy_slack_router is interface_slack_router
    assert legacy_telegram_router is interface_telegram_router
    assert InfraAuditStore is CoreAuditStore
    assert InfraDBConnection is CoreDBConnection


def test_scoped_admin_catalog_and_effective_config_are_constrained(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    with TestClient(app) as client:
        _seed_data(app.state.gw)
        token = _login(client, 'bob', 'pw2')
        headers = {'Authorization': f'Bearer {token}'}

        tenancy = client.get('/broker/admin/tenancy', headers=headers)
        assert tenancy.status_code == 200, tenancy.text
        payload = tenancy.json()
        assert payload['scope'] == {'tenant_id': 'acme', 'workspace_id': 'ops', 'environment': 'staging'}
        assert [tenant['tenant_id'] for tenant in payload['tenants']] == ['acme']
        assert [ws['workspace_id'] for ws in payload['tenants'][0]['workspaces']] == ['ops']
        assert payload['tenants'][0]['workspaces'][0]['environment_settings'][0]['settings_overrides']['broker']['token'] == '***'
        assert payload['tenants'][0]['settings_overrides']['auth']['oidc']['client_secret'] == '***'

        effective_default = client.get('/broker/admin/tenancy/effective-config', headers=headers)
        assert effective_default.status_code == 200, effective_default.text
        effective_payload = effective_default.json()
        assert effective_payload['scope'] == {'tenant_id': 'acme', 'workspace_id': 'ops', 'environment': 'staging'}
        assert effective_payload['effective']['llm']['model'] == 'ops-model'
        assert effective_payload['effective']['broker']['token'] == '***'

        denied = client.get(
            '/broker/admin/tenancy/effective-config',
            headers=headers,
            params={'tenant_id': 'acme', 'workspace_id': 'research', 'environment': 'prod'},
        )
        assert denied.status_code == 403

        overview = client.get('/broker/admin/overview', headers=headers)
        assert overview.status_code == 200, overview.text
        overview_payload = overview.json()
        assert overview_payload['summary']['scope'] == {'tenant_id': 'acme', 'workspace_id': 'ops', 'environment': 'staging'}
        assert overview_payload['summary']['db_counts']['sessions'] == 1
        assert overview_payload['summary']['db_counts']['messages'] == 1
        assert overview_payload['summary']['db_counts']['events'] >= 1
        assert overview_payload['summary']['db_counts']['memory_items'] == 1
        assert overview_payload['summary']['db_counts']['tool_calls'] == 1
        assert overview_payload['counts']['auth_users'] == 1
        assert overview_payload['counts']['auth_sessions'] >= 1
