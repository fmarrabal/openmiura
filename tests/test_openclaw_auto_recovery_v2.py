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
admin:
  enabled: true
  token: secret-admin
broker:
  enabled: true
  base_path: "/broker"
auth:
  enabled: true
  session_ttl_s: 3600
''',
        encoding='utf-8',
    )


def _create_async_runtime(client: TestClient) -> str:
    response = client.post(
        '/admin/openclaw/runtimes',
        headers={'Authorization': 'Bearer secret-admin'},
        json={
            'actor': 'admin',
            'name': 'runtime-auto-recovery-v2',
            'base_url': 'simulated://openclaw',
            'transport': 'simulated',
            'allowed_agents': ['default'],
            'tenant_id': 'tenant-a',
            'workspace_id': 'ws-a',
            'environment': 'prod',
            'metadata': {
                'allowed_actions': ['chat'],
                'dispatch_policy': {
                    'dispatch_mode': 'async',
                    'poll_after_s': 0.1,
                    'operator_retry_limit': 2,
                },
                'heartbeat_policy': {
                    'runtime_stale_after_s': 60,
                    'active_run_stale_after_s': 0,
                    'auto_reconcile_after_s': 0,
                    'auto_poll_enabled': True,
                    'auto_reconcile_enabled': True,
                    'stale_target_status': 'timed_out',
                },
                'session_bridge': {
                    'enabled': True,
                    'workspace_connection': 'primary-conn',
                    'external_workspace_id': 'oc-ws-a',
                    'external_environment': 'prod',
                    'event_bridge_enabled': True,
                },
                'event_bridge': {
                    'token': 'evt-auto-recovery-v2',
                    'accepted_sources': ['openclaw'],
                    'accepted_event_types': ['run.progress', 'run.completed', 'run.failed'],
                },
            },
        },
    )
    assert response.status_code == 200, response.text
    return response.json()['runtime']['runtime_id']


def _dispatch_async_run(client: TestClient, runtime_id: str, session_id: str) -> dict:
    response = client.post(
        f'/admin/openclaw/runtimes/{runtime_id}/dispatch',
        headers={'Authorization': 'Bearer secret-admin'},
        json={
            'actor': 'admin',
            'action': 'chat',
            'agent_id': 'default',
            'payload': {'message': 'hola'},
            'session_id': session_id,
            'tenant_id': 'tenant-a',
            'workspace_id': 'ws-a',
            'environment': 'prod',
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()['dispatch']['canonical_status'] == 'accepted'
    return response.json()


def test_admin_openclaw_auto_recovery_polls_and_reconciles_stale_async_runs(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    with TestClient(app) as client:
        runtime_id = _create_async_runtime(client)
        dispatched = _dispatch_async_run(client, runtime_id, 'auto-recovery-admin-001')
        dispatch_id = dispatched['dispatch']['dispatch_id']

        polled = client.post(
            f'/admin/openclaw/dispatches/{dispatch_id}/poll',
            headers={'Authorization': 'Bearer secret-admin'},
            json={
                'actor': 'admin',
                'reason': 'operator poll before automated recovery',
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert polled.status_code == 200, polled.text
        polled_payload = polled.json()
        assert polled_payload['dispatch']['canonical_status'] == 'accepted'
        assert polled_payload['dispatch']['response']['lifecycle']['poll_count'] >= 1
        assert polled_payload['operation']['kind'] == 'poll'

        recovered = client.post(
            f'/admin/openclaw/runtimes/{runtime_id}/recover',
            headers={'Authorization': 'Bearer secret-admin'},
            json={
                'actor': 'admin',
                'reason': 'automatic stale-run recovery sweep',
                'limit': 10,
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert recovered.status_code == 200, recovered.text
        recovered_payload = recovered.json()
        assert recovered_payload['summary']['scanned'] >= 1
        assert recovered_payload['summary']['stale_candidates'] >= 1
        assert recovered_payload['summary']['polled_count'] >= 1
        assert recovered_payload['summary']['reconciled_count'] == 1
        assert recovered_payload['summary']['stale_target_status'] == 'timed_out'
        assert recovered_payload['items'][0]['dispatch_id'] == dispatch_id
        assert recovered_payload['items'][0]['auto_reconciled'] is True
        assert recovered_payload['items'][0]['canonical_status'] == 'timed_out'

        detail = client.get(
            f'/admin/openclaw/dispatches/{dispatch_id}?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers={'Authorization': 'Bearer secret-admin'},
        )
        assert detail.status_code == 200, detail.text
        detail_payload = detail.json()
        assert detail_payload['dispatch']['canonical_status'] == 'timed_out'
        assert detail_payload['dispatch']['terminal'] is True
        assert detail_payload['dispatch']['response']['manual_reconcile']['target_status'] == 'timed_out'
        operator_actions = [item['action'] for item in detail_payload['dispatch']['response']['operator_actions']]
        assert operator_actions[-2:] == ['poll', 'reconcile']


def test_canvas_runtime_node_actions_support_poll_and_recover_stale_runs(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    with TestClient(app) as client:
        headers = {'Authorization': 'Bearer secret-admin'}
        canvas = client.post(
            '/admin/canvas/documents',
            headers=headers,
            json={'actor': 'admin', 'title': 'Runtime auto recovery canvas', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert canvas.status_code == 200, canvas.text
        canvas_id = canvas.json()['document']['canvas_id']

        runtime_id = _create_async_runtime(client)
        node = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes',
            headers=headers,
            json={
                'actor': 'admin',
                'node_type': 'openclaw_runtime',
                'label': 'Async runtime node',
                'data': {'runtime_id': runtime_id, 'agent_id': 'default'},
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert node.status_code == 200, node.text
        node_id = node.json()['node']['node_id']

        dispatched = _dispatch_async_run(client, runtime_id, 'auto-recovery-canvas-001')
        dispatch_id = dispatched['dispatch']['dispatch_id']

        polled = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/poll_run?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'admin', 'reason': 'poll from canvas', 'payload': {'dispatch_id': dispatch_id}},
        )
        assert polled.status_code == 200, polled.text
        polled_payload = polled.json()['result']
        assert polled_payload['dispatch']['canonical_status'] == 'accepted'
        assert polled_payload['operation']['kind'] == 'poll'

        recovered = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/recover_stale_runs?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'admin', 'reason': 'recover from canvas', 'payload': {'limit': 10}},
        )
        assert recovered.status_code == 200, recovered.text
        recovered_payload = recovered.json()['result']
        assert recovered_payload['summary']['reconciled_count'] == 1
        assert recovered_payload['items'][0]['dispatch_id'] == dispatch_id
        assert recovered_payload['items'][0]['canonical_status'] == 'timed_out'

        inspector = client.get(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert inspector.status_code == 200, inspector.text
        related = inspector.json()['related']['runtime_runboard']
        assert related['latest_run']['dispatch_id'] == dispatch_id
        assert related['latest_run']['canonical_status'] == 'timed_out'
        assert 'poll_run' in related['summary']['available_operations']
        assert 'recover_stale_runs' in related['summary']['available_operations']

        board = client.get(
            f'/admin/canvas/documents/{canvas_id}/views/runtime-board?tenant_id=tenant-a&workspace_id=ws-a&environment=prod&limit=10',
            headers=headers,
        )
        assert board.status_code == 200, board.text
        board_payload = board.json()
        assert board_payload['summary']['stale_active_runs'] == 0
        assert board_payload['items'][0]['runtime_summary']['heartbeat_policy']['stale_target_status'] == 'timed_out'
