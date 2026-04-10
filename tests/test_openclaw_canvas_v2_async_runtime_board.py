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


def test_canvas_v2_runtime_board_tracks_async_governed_runs(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    with TestClient(app) as client:
        headers = {'Authorization': 'Bearer secret-admin'}
        canvas = client.post(
            '/admin/canvas/documents',
            headers=headers,
            json={'actor': 'admin', 'title': 'Async ops canvas', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert canvas.status_code == 200, canvas.text
        canvas_id = canvas.json()['document']['canvas_id']

        runtime = client.post(
            '/admin/openclaw/runtimes',
            headers=headers,
            json={
                'actor': 'admin',
                'name': 'remote-openclaw',
                'base_url': 'simulated://openclaw',
                'transport': 'simulated',
                'allowed_agents': ['default'],
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
                'metadata': {
                    'allowed_actions': ['chat'],
                    'dispatch_policy': {'dispatch_mode': 'async', 'poll_after_s': 1.0},
                    'session_bridge': {
                        'enabled': True,
                        'workspace_connection': 'primary-conn',
                        'external_workspace_id': 'oc-ws-a',
                        'external_environment': 'prod',
                        'event_bridge_enabled': True,
                    },
                    'event_bridge': {
                        'token': 'evt-canvas-v2',
                        'accepted_sources': ['openclaw'],
                        'accepted_event_types': ['run.queued', 'run.progress', 'run.completed'],
                    },
                },
            },
        )
        assert runtime.status_code == 200, runtime.text
        runtime_id = runtime.json()['runtime']['runtime_id']

        node = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes',
            headers=headers,
            json={
                'actor': 'admin',
                'node_type': 'openclaw_runtime',
                'label': 'Runtime node',
                'data': {'runtime_id': runtime_id, 'agent_id': 'default'},
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert node.status_code == 200, node.text
        node_id = node.json()['node']['node_id']

        dispatched = client.post(
            f'/admin/openclaw/runtimes/{runtime_id}/dispatch',
            headers=headers,
            json={
                'actor': 'admin',
                'action': 'chat',
                'agent_id': 'default',
                'payload': {'message': 'hola'},
                'session_id': 'canvas-v2-001',
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert dispatched.status_code == 200, dispatched.text
        dispatch_id = dispatched.json()['dispatch']['dispatch_id']
        assert dispatched.json()['dispatch']['canonical_status'] == 'accepted'

        queued = client.post(
            f'/openclaw/runtimes/{runtime_id}/events',
            headers={'X-OpenClaw-Event-Token': 'evt-canvas-v2'},
            json={
                'source': 'openclaw',
                'event_type': 'run.queued',
                'event_status': 'queued',
                'dispatch_id': dispatch_id,
                'source_event_id': 'evt-queue-1',
            },
        )
        assert queued.status_code == 200, queued.text

        running = client.post(
            f'/openclaw/runtimes/{runtime_id}/events',
            headers={'X-OpenClaw-Event-Token': 'evt-canvas-v2'},
            json={
                'source': 'openclaw',
                'event_type': 'run.progress',
                'event_status': 'running',
                'dispatch_id': dispatch_id,
                'source_event_id': 'evt-running-1',
            },
        )
        assert running.status_code == 200, running.text

        views = client.get(
            f'/admin/canvas/documents/{canvas_id}/views/operational?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert views.status_code == 200, views.text
        views_payload = views.json()
        assert any(item['view_key'] == 'async-governed-runs' for item in views_payload['suggested_views'])
        assert views_payload['summary']['runtime_board']['total_active_runs'] == 1
        assert views_payload['summary']['runtime_board']['async_runtime_count'] == 1

        board = client.get(
            f'/admin/canvas/documents/{canvas_id}/views/runtime-board?tenant_id=tenant-a&workspace_id=ws-a&environment=prod&limit=10',
            headers=headers,
        )
        assert board.status_code == 200, board.text
        board_payload = board.json()
        assert board_payload['summary']['runtime_count'] == 1
        assert board_payload['summary']['total_active_runs'] == 1
        assert board_payload['summary']['canonical_state_counts']['running'] == 1
        assert board_payload['items'][0]['runtime_summary']['dispatch_policy']['dispatch_mode'] == 'async'
        assert board_payload['items'][0]['latest_run']['canonical_status'] == 'running'
        assert board_payload['items'][0]['summary']['active_count'] == 1

        inspector = client.get(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert inspector.status_code == 200, inspector.text
        inspector_payload = inspector.json()
        assert inspector_payload['related']['runtime_runboard']['latest_run']['canonical_status'] == 'running'
        assert inspector_payload['related']['runtime_runboard']['summary']['active_count'] == 1

        timeline = client.get(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/timeline?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert timeline.status_code == 200, timeline.text
        dispatch_items = [item for item in timeline.json()['items'] if item['kind'] == 'dispatch']
        assert dispatch_items
        assert dispatch_items[-1]['canonical_status'] == 'running'
        assert dispatch_items[-1]['terminal'] is False

        completed = client.post(
            f'/openclaw/runtimes/{runtime_id}/events',
            headers={'X-OpenClaw-Event-Token': 'evt-canvas-v2'},
            json={
                'source': 'openclaw',
                'event_type': 'run.completed',
                'event_status': 'completed',
                'dispatch_id': dispatch_id,
                'source_event_id': 'evt-completed-1',
            },
        )
        assert completed.status_code == 200, completed.text

        refreshed_board = client.get(
            f'/admin/canvas/documents/{canvas_id}/views/runtime-board?tenant_id=tenant-a&workspace_id=ws-a&environment=prod&limit=10',
            headers=headers,
        )
        assert refreshed_board.status_code == 200, refreshed_board.text
        refreshed_payload = refreshed_board.json()
        assert refreshed_payload['summary']['total_active_runs'] == 0
        assert refreshed_payload['summary']['total_terminal_runs'] == 1
        assert refreshed_payload['summary']['canonical_state_counts']['completed'] == 1
        assert refreshed_payload['items'][0]['latest_run']['canonical_status'] == 'completed'
