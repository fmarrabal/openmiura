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
''',
        encoding='utf-8',
    )


def _login(client: TestClient, username: str, password: str) -> str:
    response = client.post('/broker/auth/login', json={'username': username, 'password': password})
    assert response.status_code == 200, response.text
    return response.json()['token']


def test_openclaw_v2_health_and_timeline_expose_runtime_summary_and_correlation(tmp_path: Path) -> None:
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
                'name': 'Research OpenClaw V2',
                'base_url': 'https://openclaw.internal.example',
                'transport': 'simulated',
                'auth_secret_ref': 'openclaw_token',
                'capabilities': ['chat', 'tools'],
                'allowed_agents': ['ops-agent'],
                'metadata': {
                    'allowed_actions': ['chat'],
                    'dispatch_policy': {'quota_per_hour': 5, 'max_retries': 1},
                    'session_bridge': {
                        'enabled': True,
                        'workspace_connection': 'research-primary',
                        'external_workspace_id': 'oc-research',
                        'external_environment': 'prod',
                        'event_bridge_enabled': True,
                    },
                },
            },
        )
        assert created.status_code == 200, created.text
        runtime_id = created.json()['runtime']['runtime_id']
        runtime_summary = created.json()['runtime_summary']
        assert runtime_summary['allowed_actions'] == ['chat']
        assert runtime_summary['session_bridge']['workspace_connection'] == 'research-primary'

        health = client.post(
            f'/broker/admin/openclaw/runtimes/{runtime_id}/health',
            headers=headers,
            json={'probe': 'ready', 'session_id': 'health-session'},
        )
        assert health.status_code == 200, health.text
        assert health.json()['health']['status'] == 'healthy'
        assert health.json()['health']['detail']['attempts'] == 1

        dispatched = client.post(
            f'/broker/admin/openclaw/runtimes/{runtime_id}/dispatch',
            headers=headers,
            json={
                'action': 'chat',
                'agent_id': 'ops-agent',
                'session_id': 'run-001',
                'payload': {'message': 'hola'},
            },
        )
        assert dispatched.status_code == 200, dispatched.text
        dispatch_payload = dispatched.json()
        assert dispatch_payload['ok'] is True
        corr = dispatch_payload['request']['body']['correlation']
        assert corr['openmiura_session_id'] == 'run-001'
        assert corr['workspace_connection'] == 'research-primary'
        assert corr['external_workspace_id'] == 'oc-research'
        assert dispatch_payload['response']['attempts'] == 1

        timeline = client.get(
            f'/broker/admin/openclaw/runtimes/{runtime_id}/timeline',
            headers=headers,
            params={'limit': 20},
        )
        assert timeline.status_code == 200, timeline.text
        data = timeline.json()
        assert data['ok'] is True
        assert data['runtime_summary']['session_bridge']['event_bridge_enabled'] is True
        labels = [item['action'] for item in data['timeline']]
        assert 'openclaw_runtime_health_checked' in labels
        assert 'openclaw_dispatch_requested' in labels
        assert 'openclaw_dispatch_completed' in labels
        correlated_dispatches = [item for item in data['timeline'] if item['kind'] == 'dispatch']
        assert correlated_dispatches
        assert correlated_dispatches[0]['payload']['request']['correlation']['openmiura_session_id'] == 'run-001'


def test_openclaw_v2_enforces_allowed_actions_and_hourly_quota(tmp_path: Path) -> None:
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
                'name': 'Quota OpenClaw',
                'base_url': 'https://openclaw.internal.example',
                'transport': 'simulated',
                'metadata': {
                    'allowed_actions': ['chat'],
                    'dispatch_policy': {'quota_per_hour': 1},
                },
            },
        )
        assert created.status_code == 200, created.text
        runtime_id = created.json()['runtime']['runtime_id']

        forbidden = client.post(
            f'/broker/admin/openclaw/runtimes/{runtime_id}/dispatch',
            headers=headers,
            json={'action': 'browser', 'session_id': 'run-browser', 'payload': {'url': 'https://example.com'}},
        )
        assert forbidden.status_code == 403, forbidden.text
        assert "action 'browser' not allowed" in forbidden.text

        allowed = client.post(
            f'/broker/admin/openclaw/runtimes/{runtime_id}/dispatch',
            headers=headers,
            json={'action': 'chat', 'session_id': 'run-chat', 'payload': {'message': 'hola'}},
        )
        assert allowed.status_code == 200, allowed.text
        assert allowed.json()['ok'] is True

        quota_hit = client.post(
            f'/broker/admin/openclaw/runtimes/{runtime_id}/dispatch',
            headers=headers,
            json={'action': 'chat', 'session_id': 'run-chat-2', 'payload': {'message': 'otra vez'}},
        )
        assert quota_hit.status_code == 403, quota_hit.text
        assert 'exceeded hourly dispatch quota' in quota_hit.text
