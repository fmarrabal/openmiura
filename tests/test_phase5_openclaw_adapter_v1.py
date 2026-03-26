from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import app as app_module
from openmiura.gateway import Gateway


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
admin:
  enabled: true
  token: "admin-secret"
secrets:
  enabled: true
  refs:
    openclaw_token:
      value: "super-secret-token"
      allowed_tools: [openclaw_adapter]
      allowed_roles: [workspace_admin, tenant_admin, admin]
      allowed_tenants: [acme]
      allowed_workspaces: [research]
      allowed_environments: [prod]
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
          rbac:
            username_roles:
              wally: workspace_admin
        ops:
          display_name: "Operations"
          environments: [staging, prod]
          default_environment: "staging"
          rbac:
            username_roles:
              olga: workspace_admin
''',
        encoding='utf-8',
    )


def _login(client: TestClient, username: str, password: str) -> str:
    response = client.post('/broker/auth/login', json={'username': username, 'password': password})
    assert response.status_code == 200, response.text
    return response.json()['token']


def test_workspace_admin_can_register_and_dispatch_scoped_openclaw_runtime(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    with TestClient(app) as client:
        gw = app.state.gw
        gw.audit.ensure_auth_user(username='wally', password='pw1', user_key='user:wally', role='user', tenant_id='acme', workspace_id='research')
        token = _login(client, 'wally', 'pw1')
        headers = {
            'Authorization': f'Bearer {token}',
            'X-Tenant-Id': 'acme',
            'X-Workspace-Id': 'research',
            'X-Environment': 'prod',
        }

        created = client.post(
            '/broker/admin/openclaw/runtimes',
            headers=headers,
            json={
                'name': 'Research OpenClaw',
                'base_url': 'https://openclaw.internal.example',
                'transport': 'simulated',
                'auth_secret_ref': 'openclaw_token',
                'capabilities': ['chat', 'tools'],
                'allowed_agents': ['ops-agent'],
                'metadata': {'owner': 'research'},
            },
        )
        assert created.status_code == 200, created.text
        runtime = created.json()['runtime']
        assert runtime['transport'] == 'simulated'
        assert runtime['auth_secret_ref'] == 'openclaw_token'
        assert runtime['allowed_agents'] == ['ops-agent']

        dispatched = client.post(
            f"/broker/admin/openclaw/runtimes/{runtime['runtime_id']}/dispatch",
            headers=headers,
            json={
                'action': 'chat',
                'agent_id': 'ops-agent',
                'payload': {'message': 'hola'},
            },
        )
        assert dispatched.status_code == 200, dispatched.text
        payload = dispatched.json()
        assert payload['ok'] is True
        assert payload['dispatch']['secret_ref'] == 'openclaw_token'
        assert payload['request']['headers']['Authorization'] == '[secret:openclaw_token]'
        assert 'super-secret-token' not in str(payload)
        assert payload['response']['accepted'] is True

        listing = client.get('/broker/admin/openclaw/dispatches', headers=headers)
        assert listing.status_code == 200, listing.text
        assert listing.json()['summary']['count'] >= 1
        assert listing.json()['items'][0]['runtime_id'] == runtime['runtime_id']


def test_workspace_admin_cannot_manage_openclaw_runtime_outside_workspace(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    with TestClient(app) as client:
        gw = app.state.gw
        gw.audit.ensure_auth_user(username='wally', password='pw1', user_key='user:wally', role='user', tenant_id='acme', workspace_id='research')
        gw.audit.ensure_auth_user(username='olga', password='pw2', user_key='user:olga', role='user', tenant_id='acme', workspace_id='ops')

        research_token = _login(client, 'wally', 'pw1')
        research_headers = {
            'Authorization': f'Bearer {research_token}',
            'X-Tenant-Id': 'acme',
            'X-Workspace-Id': 'research',
            'X-Environment': 'prod',
        }
        created = client.post(
            '/broker/admin/openclaw/runtimes',
            headers=research_headers,
            json={'name': 'Research OpenClaw', 'base_url': 'https://openclaw.internal.example', 'transport': 'simulated'},
        )
        assert created.status_code == 200, created.text
        runtime_id = created.json()['runtime']['runtime_id']

        ops_token = _login(client, 'olga', 'pw2')
        ops_headers = {
            'Authorization': f'Bearer {ops_token}',
            'X-Tenant-Id': 'acme',
            'X-Workspace-Id': 'ops',
            'X-Environment': 'staging',
        }
        denied = client.get(f'/broker/admin/openclaw/runtimes/{runtime_id}', headers=ops_headers, params={'tenant_id': 'acme', 'workspace_id': 'research', 'environment': 'prod'})
        assert denied.status_code == 403, denied.text

        denied_dispatch = client.post(
            f'/broker/admin/openclaw/runtimes/{runtime_id}/dispatch',
            headers=ops_headers,
            json={'tenant_id': 'acme', 'workspace_id': 'research', 'environment': 'prod', 'action': 'chat', 'payload': {'message': 'hola'}},
        )
        assert denied_dispatch.status_code == 403, denied_dispatch.text


def test_legacy_admin_openclaw_endpoints_support_registration_and_listing(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    with TestClient(app) as client:
        headers = {'Authorization': 'Bearer admin-secret'}
        created = client.post(
            '/admin/openclaw/runtimes',
            headers=headers,
            json={
                'actor': 'admin',
                'name': 'Tenant OpenClaw',
                'base_url': 'https://openclaw.internal.example',
                'transport': 'simulated',
                'tenant_id': 'acme',
                'workspace_id': 'research',
                'environment': 'prod',
            },
        )
        assert created.status_code == 200, created.text
        runtime_id = created.json()['runtime']['runtime_id']

        detail = client.get('/admin/openclaw/runtimes/' + runtime_id, headers=headers, params={'tenant_id': 'acme', 'workspace_id': 'research', 'environment': 'prod'})
        assert detail.status_code == 200, detail.text
        assert detail.json()['runtime']['name'] == 'Tenant OpenClaw'

        listing = client.get('/admin/openclaw/runtimes', headers=headers, params={'tenant_id': 'acme', 'workspace_id': 'research', 'environment': 'prod'})
        assert listing.status_code == 200, listing.text
        assert any(item['runtime_id'] == runtime_id for item in listing.json()['items'])
