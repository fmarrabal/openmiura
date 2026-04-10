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
            'name': 'runtime-ops-v2',
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
                    'poll_after_s': 1.0,
                    'operator_retry_limit': 2,
                },
                'session_bridge': {
                    'enabled': True,
                    'workspace_connection': 'primary-conn',
                    'external_workspace_id': 'oc-ws-a',
                    'external_environment': 'prod',
                    'event_bridge_enabled': True,
                },
                'event_bridge': {
                    'token': 'evt-runtime-ops-v2',
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


def test_admin_openclaw_dispatch_operations_v2_cover_cancel_retry_and_reconcile(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    with TestClient(app) as client:
        runtime_id = _create_async_runtime(client)
        dispatched = _dispatch_async_run(client, runtime_id, 'ops-v2-admin-001')
        dispatch_id = dispatched['dispatch']['dispatch_id']

        cancelled = client.post(
            f'/admin/openclaw/dispatches/{dispatch_id}/cancel',
            headers={'Authorization': 'Bearer secret-admin'},
            json={
                'actor': 'admin',
                'reason': 'operator stop',
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert cancelled.status_code == 200, cancelled.text
        cancelled_payload = cancelled.json()
        assert cancelled_payload['dispatch']['canonical_status'] == 'cancelled'
        assert cancelled_payload['dispatch']['terminal'] is True
        assert cancelled_payload['operation']['kind'] == 'cancel'

        retried = client.post(
            f'/admin/openclaw/dispatches/{dispatch_id}/retry',
            headers={'Authorization': 'Bearer secret-admin'},
            json={
                'actor': 'admin',
                'reason': 'retry after operator cancellation',
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert retried.status_code == 200, retried.text
        retried_payload = retried.json()
        retry_dispatch_id = retried_payload['dispatch']['dispatch_id']
        assert retry_dispatch_id != dispatch_id
        assert retried_payload['dispatch']['canonical_status'] == 'accepted'
        assert retried_payload['dispatch']['response']['lifecycle']['retry_count'] == 1
        assert retried_payload['dispatch']['request']['correlation']['retry_of_dispatch_id'] == dispatch_id
        assert retried_payload['dispatch']['request']['correlation']['root_dispatch_id'] == dispatch_id

        reconciled = client.post(
            f'/admin/openclaw/dispatches/{retry_dispatch_id}/reconcile',
            headers={'Authorization': 'Bearer secret-admin'},
            json={
                'actor': 'admin',
                'target_status': 'timed_out',
                'reason': 'manual close from ops',
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert reconciled.status_code == 200, reconciled.text
        reconciled_payload = reconciled.json()
        assert reconciled_payload['dispatch']['canonical_status'] == 'timed_out'
        assert reconciled_payload['dispatch']['terminal'] is True
        assert reconciled_payload['dispatch']['response']['manual_reconcile']['target_status'] == 'timed_out'
        assert reconciled_payload['operation']['kind'] == 'reconcile'

        detail = client.get(
            f'/admin/openclaw/dispatches/{dispatch_id}?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers={'Authorization': 'Bearer secret-admin'},
        )
        assert detail.status_code == 200, detail.text
        operator_actions = detail.json()['dispatch']['response']['operator_actions']
        assert [item['action'] for item in operator_actions][-2:] == ['cancel', 'retry']

        listing = client.get(
            '/admin/openclaw/dispatches?tenant_id=tenant-a&workspace_id=ws-a&environment=prod&limit=10',
            headers={'Authorization': 'Bearer secret-admin'},
        )
        assert listing.status_code == 200, listing.text
        summary = listing.json()['summary']['canonical_state_counts']
        assert summary['cancelled'] == 1
        assert summary['timed_out'] == 1


def test_canvas_runtime_node_actions_v2_support_async_run_operations(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    with TestClient(app) as client:
        headers = {'Authorization': 'Bearer secret-admin'}
        canvas = client.post(
            '/admin/canvas/documents',
            headers=headers,
            json={'actor': 'admin', 'title': 'Runtime operations canvas', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
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

        dispatched = _dispatch_async_run(client, runtime_id, 'ops-v2-canvas-001')
        dispatch_id = dispatched['dispatch']['dispatch_id']

        confirm_needed = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/cancel_run?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'admin', 'payload': {'dispatch_id': dispatch_id}},
        )
        assert confirm_needed.status_code == 200, confirm_needed.text
        assert confirm_needed.json()['error'] == 'confirmation_required'

        cancelled = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/cancel_run?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'admin', 'reason': 'cancel from canvas', 'payload': {'dispatch_id': dispatch_id, 'confirmed': True}},
        )
        assert cancelled.status_code == 200, cancelled.text
        cancelled_payload = cancelled.json()['result']
        assert cancelled_payload['dispatch']['canonical_status'] == 'cancelled'

        retried = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/retry_run?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'admin', 'reason': 'retry from canvas', 'payload': {'dispatch_id': dispatch_id}},
        )
        assert retried.status_code == 200, retried.text
        retried_payload = retried.json()['result']
        retry_dispatch_id = retried_payload['dispatch']['dispatch_id']
        assert retried_payload['dispatch']['canonical_status'] == 'accepted'
        assert retried_payload['dispatch']['request']['correlation']['retry_of_dispatch_id'] == dispatch_id

        manual_close = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/manual_close?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={
                'actor': 'admin',
                'reason': 'manual timeout from canvas',
                'payload': {'dispatch_id': retry_dispatch_id, 'manual_status': 'timed_out', 'confirmed': True},
            },
        )
        assert manual_close.status_code == 200, manual_close.text
        manual_payload = manual_close.json()['result']
        assert manual_payload['dispatch']['canonical_status'] == 'timed_out'
        assert manual_payload['dispatch']['response']['manual_reconcile']['target_status'] == 'timed_out'

        inspector = client.get(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert inspector.status_code == 200, inspector.text
        related = inspector.json()['related']['runtime_runboard']
        assert related['latest_run']['dispatch_id'] == retry_dispatch_id
        assert related['latest_run']['canonical_status'] == 'timed_out'
        assert 'retry_run' in related['summary']['available_operations']
        assert 'manual_close' in related['summary']['available_operations']
