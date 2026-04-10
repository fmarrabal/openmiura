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


def test_async_governed_dispatch_progresses_through_canonical_states(tmp_path: Path) -> None:
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
                'name': 'Async OpenClaw',
                'base_url': 'https://openclaw.internal.example',
                'transport': 'simulated',
                'auth_secret_ref': 'openclaw_token',
                'allowed_agents': ['ops-agent'],
                'metadata': {
                    'allowed_actions': ['chat'],
                    'dispatch_policy': {
                        'dispatch_mode': 'async',
                        'poll_after_s': 1.5,
                    },
                    'session_bridge': {
                        'enabled': True,
                        'workspace_connection': 'research-primary',
                        'external_workspace_id': 'oc-research',
                        'external_environment': 'prod',
                        'event_bridge_enabled': True,
                    },
                    'event_bridge': {
                        'token': 'evt-token-async',
                        'accepted_sources': ['openclaw'],
                        'accepted_event_types': ['run.accepted', 'run.queued', 'run.progress', 'run.completed'],
                    },
                },
            },
        )
        assert created.status_code == 200, created.text
        runtime_id = created.json()['runtime']['runtime_id']
        assert created.json()['runtime_summary']['dispatch_policy']['dispatch_mode'] == 'async'

        dispatched = client.post(
            f'/broker/admin/openclaw/runtimes/{runtime_id}/dispatch',
            headers=headers,
            json={
                'action': 'chat',
                'agent_id': 'ops-agent',
                'session_id': 'async-run-001',
                'payload': {'message': 'hola'},
            },
        )
        assert dispatched.status_code == 200, dispatched.text
        dispatch_payload = dispatched.json()
        dispatch_id = dispatch_payload['dispatch']['dispatch_id']
        assert dispatch_payload['dispatch']['status'] == 'accepted'
        assert dispatch_payload['dispatch']['canonical_status'] == 'accepted'
        assert dispatch_payload['dispatch']['terminal'] is False
        assert dispatch_payload['dispatch']['response']['lifecycle']['dispatch_mode'] == 'async'
        assert dispatch_payload['dispatch']['response']['lifecycle']['poll_after_s'] == 1.5

        detail = client.get(
            f'/broker/admin/openclaw/dispatches/{dispatch_id}',
            headers=headers,
        )
        assert detail.status_code == 200, detail.text
        assert detail.json()['dispatch']['canonical_status'] == 'accepted'

        queued = client.post(
            f'/openclaw/runtimes/{runtime_id}/events',
            headers={'X-OpenClaw-Event-Token': 'evt-token-async'},
            json={
                'source': 'openclaw',
                'event_type': 'run.queued',
                'event_status': 'queued',
                'source_event_id': 'evt-queued-1',
                'dispatch_id': dispatch_id,
            },
        )
        assert queued.status_code == 200, queued.text
        assert queued.json()['dispatch']['canonical_status'] == 'queued'
        assert queued.json()['dispatch']['terminal'] is False

        running = client.post(
            f'/openclaw/runtimes/{runtime_id}/events',
            headers={'X-OpenClaw-Event-Token': 'evt-token-async'},
            json={
                'source': 'openclaw',
                'event_type': 'run.progress',
                'event_status': 'running',
                'source_event_id': 'evt-running-1',
                'dispatch_id': dispatch_id,
            },
        )
        assert running.status_code == 200, running.text
        assert running.json()['dispatch']['canonical_status'] == 'running'

        completed = client.post(
            f'/openclaw/runtimes/{runtime_id}/events',
            headers={'X-OpenClaw-Event-Token': 'evt-token-async'},
            json={
                'source': 'openclaw',
                'event_type': 'run.completed',
                'event_status': 'completed',
                'source_event_id': 'evt-completed-1',
                'dispatch_id': dispatch_id,
                'message': 'done',
            },
        )
        assert completed.status_code == 200, completed.text
        assert completed.json()['dispatch']['canonical_status'] == 'completed'
        assert completed.json()['dispatch']['terminal'] is True

        stale = client.post(
            f'/openclaw/runtimes/{runtime_id}/events',
            headers={'X-OpenClaw-Event-Token': 'evt-token-async'},
            json={
                'source': 'openclaw',
                'event_type': 'run.accepted',
                'event_status': 'accepted',
                'source_event_id': 'evt-accepted-too-late',
                'dispatch_id': dispatch_id,
            },
        )
        assert stale.status_code == 200, stale.text
        assert stale.json()['dispatch']['canonical_status'] == 'completed'
        conflict = stale.json()['dispatch']['response']['lifecycle']['transition_conflict']
        assert conflict['current'] == 'completed'
        assert conflict['attempted'] == 'accepted'

        final_detail = client.get(
            f'/broker/admin/openclaw/dispatches/{dispatch_id}',
            headers=headers,
        )
        assert final_detail.status_code == 200, final_detail.text
        assert final_detail.json()['dispatch']['canonical_status'] == 'completed'
        assert final_detail.json()['dispatch']['terminal'] is True

        timeline = client.get(
            f'/broker/admin/openclaw/runtimes/{runtime_id}/timeline',
            headers=headers,
            params={'limit': 30},
        )
        assert timeline.status_code == 200, timeline.text
        dispatch_items = [item for item in timeline.json()['timeline'] if item['kind'] == 'dispatch']
        assert dispatch_items
        assert dispatch_items[0]['canonical_status'] == 'completed'
        assert dispatch_items[0]['terminal'] is True


def test_sync_dispatch_exposes_completed_canonical_state_and_summary_counts(tmp_path: Path) -> None:
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
                'name': 'Sync OpenClaw',
                'base_url': 'https://openclaw.internal.example',
                'transport': 'simulated',
                'metadata': {
                    'allowed_actions': ['chat'],
                    'dispatch_policy': {'dispatch_mode': 'sync'},
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
                'session_id': 'sync-run-001',
                'payload': {'message': 'hola'},
            },
        )
        assert dispatched.status_code == 200, dispatched.text
        assert dispatched.json()['dispatch']['status'] == 'ok'
        assert dispatched.json()['dispatch']['canonical_status'] == 'completed'
        assert dispatched.json()['dispatch']['terminal'] is True

        listing = client.get(
            '/broker/admin/openclaw/dispatches',
            headers=headers,
            params={'runtime_id': runtime_id},
        )
        assert listing.status_code == 200, listing.text
        summary = listing.json()['summary']
        assert summary['canonical_state_counts']['completed'] == 1
        assert listing.json()['items'][0]['canonical_status'] == 'completed'
