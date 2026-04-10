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


def test_public_openclaw_event_webhook_bridges_events_and_updates_dispatch_status(tmp_path: Path) -> None:
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
                'name': 'Webhook Runtime',
                'base_url': 'https://openclaw.internal.example',
                'transport': 'simulated',
                'auth_secret_ref': 'openclaw_token',
                'capabilities': ['chat'],
                'allowed_agents': ['ops-agent'],
                'metadata': {
                    'allowed_actions': ['chat'],
                    'session_bridge': {
                        'enabled': True,
                        'workspace_connection': 'research-primary',
                        'external_workspace_id': 'oc-research',
                        'external_environment': 'prod',
                        'event_bridge_enabled': True,
                    },
                    'event_bridge': {
                        'token': 'evt-token-123',
                        'accepted_sources': ['openclaw'],
                        'accepted_event_types': ['run.completed'],
                    },
                },
            },
        )
        assert created.status_code == 200, created.text
        runtime_id = created.json()['runtime']['runtime_id']

        dispatched = client.post(
            f'/broker/admin/openclaw/runtimes/{runtime_id}/dispatch',
            headers=headers,
            json={
                'action': 'chat',
                'agent_id': 'ops-agent',
                'session_id': 'run-evt-001',
                'payload': {'message': 'hola'},
            },
        )
        assert dispatched.status_code == 200, dispatched.text
        dispatch_id = dispatched.json()['dispatch']['dispatch_id']
        assert dispatched.json()['dispatch']['status'] == 'ok'

        bridged = client.post(
            f'/openclaw/runtimes/{runtime_id}/events',
            headers={'X-OpenClaw-Event-Token': 'evt-token-123'},
            json={
                'source': 'openclaw',
                'event_type': 'run.completed',
                'event_status': 'completed',
                'source_event_id': 'evt-001',
                'dispatch_id': dispatch_id,
                'message': 'remote execution finished',
                'payload': {'result': {'status': 'done'}},
            },
        )
        assert bridged.status_code == 200, bridged.text
        payload = bridged.json()
        assert payload['ok'] is True
        assert payload['event']['event_type'] == 'run.completed'
        assert payload['dispatch']['status'] == 'completed'
        assert payload['dispatch']['response']['event_bridge']['source_event_id'] == 'evt-001'

        duplicate = client.post(
            f'/openclaw/runtimes/{runtime_id}/events',
            headers={'X-OpenClaw-Event-Token': 'evt-token-123'},
            json={
                'source': 'openclaw',
                'event_type': 'run.completed',
                'event_status': 'completed',
                'source_event_id': 'evt-001',
                'dispatch_id': dispatch_id,
            },
        )
        assert duplicate.status_code == 200, duplicate.text
        assert duplicate.json()['duplicate'] is True

        timeline = client.get(
            f'/broker/admin/openclaw/runtimes/{runtime_id}/timeline',
            headers=headers,
            params={'limit': 20},
        )
        assert timeline.status_code == 200, timeline.text
        items = timeline.json()['timeline']
        bridged_items = [item for item in items if item.get('action') == 'openclaw_event_bridged']
        assert bridged_items
        assert bridged_items[0]['event_type'] == 'run.completed'
        assert bridged_items[0]['dispatch_id'] == dispatch_id


def test_openclaw_conformance_detects_unsecured_event_bridge(tmp_path: Path) -> None:
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
                'name': 'Conformance Runtime',
                'base_url': 'https://openclaw.internal.example',
                'transport': 'simulated',
                'tenant_id': 'acme',
                'workspace_id': 'research',
                'environment': 'prod',
                'metadata': {
                    'openclaw_compat_version': 'v2',
                    'allowed_actions': ['chat'],
                    'session_bridge': {
                        'enabled': True,
                        'workspace_connection': 'research-primary',
                        'event_bridge_enabled': True,
                    },
                    'event_bridge': {
                        'accepted_sources': ['openclaw'],
                    },
                },
            },
        )
        assert created.status_code == 200, created.text
        runtime_id = created.json()['runtime']['runtime_id']

        conformance = client.post(
            f'/admin/openclaw/runtimes/{runtime_id}/conformance',
            headers=headers,
            json={'actor': 'admin', 'tenant_id': 'acme', 'workspace_id': 'research', 'environment': 'prod'},
        )
        assert conformance.status_code == 200, conformance.text
        data = conformance.json()
        assert data['ok'] is True
        assert data['conformance']['ready'] is False
        checks = {item['check_id']: item for item in data['conformance']['checks']}
        assert checks['compat_version']['state'] == 'pass'
        assert checks['allowed_actions_declared']['state'] == 'pass'
        assert checks['event_bridge']['state'] == 'fail'
        assert 'token' in checks['event_bridge']['reason']
