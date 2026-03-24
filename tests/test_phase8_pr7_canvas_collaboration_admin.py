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
agents:
  default:
    system_prompt: "base"
    tools: ["time_now"]
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


def _login(client: TestClient) -> str:
    response = client.post('/broker/auth/login', json={'username': 'admin', 'password': 'secret123'})
    assert response.status_code == 200, response.text
    return response.json()['token']


def test_phase8_pr7_canvas_collaboration_http_and_broker_endpoints(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv('OPENMIURA_UI_ADMIN_USERNAME', 'admin')
    monkeypatch.setenv('OPENMIURA_UI_ADMIN_PASSWORD', 'secret123')
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    with TestClient(app) as client:
        headers = {'Authorization': 'Bearer secret-admin'}
        created = client.post(
            '/admin/canvas/documents',
            headers=headers,
            json={'actor': 'admin', 'title': 'Shared canvas', 'tenant_id': 'tenant-s', 'workspace_id': 'ws-shared', 'environment': 'dev'},
        )
        assert created.status_code == 200, created.text
        canvas_id = created.json()['document']['canvas_id']

        node = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes',
            headers=headers,
            json={'actor': 'admin', 'node_type': 'workflow', 'label': 'Workflow root', 'tenant_id': 'tenant-s', 'workspace_id': 'ws-shared', 'environment': 'dev'},
        )
        assert node.status_code == 200, node.text
        node_id = node.json()['node']['node_id']

        comment = client.post(
            f'/admin/canvas/documents/{canvas_id}/comments',
            headers=headers,
            json={'actor': 'admin', 'body': 'Looks good for handoff', 'node_id': node_id, 'tenant_id': 'tenant-s', 'workspace_id': 'ws-shared', 'environment': 'dev'},
        )
        assert comment.status_code == 200, comment.text

        snapshot = client.post(
            f'/admin/canvas/documents/{canvas_id}/snapshots',
            headers=headers,
            json={'actor': 'admin', 'label': 'Before review', 'selected_node_id': node_id, 'tenant_id': 'tenant-s', 'workspace_id': 'ws-shared', 'environment': 'dev'},
        )
        assert snapshot.status_code == 200, snapshot.text
        snapshot_id = snapshot.json()['snapshot']['snapshot_id']

        presence = client.post(
            f'/admin/canvas/documents/{canvas_id}/presence',
            headers=headers,
            json={'actor': 'admin', 'user_key': 'operator:alice', 'selected_node_id': node_id, 'tenant_id': 'tenant-s', 'workspace_id': 'ws-shared', 'environment': 'dev'},
        )
        assert presence.status_code == 200, presence.text

        share = client.post(
            f'/admin/canvas/documents/{canvas_id}/share-view',
            headers=headers,
            json={'actor': 'admin', 'label': 'Mobile share', 'selected_node_id': node_id, 'tenant_id': 'tenant-s', 'workspace_id': 'ws-shared', 'environment': 'dev'},
        )
        assert share.status_code == 200, share.text
        assert share.json()['share_token']

        comments = client.get(
            f'/admin/canvas/documents/{canvas_id}/comments?tenant_id=tenant-s&workspace_id=ws-shared&environment=dev',
            headers=headers,
        )
        assert comments.status_code == 200, comments.text
        assert len(comments.json()['items']) >= 1

        presence_events = client.get(
            f'/admin/canvas/documents/{canvas_id}/presence-events?tenant_id=tenant-s&workspace_id=ws-shared&environment=dev',
            headers=headers,
        )
        assert presence_events.status_code == 200, presence_events.text
        assert len(presence_events.json()['items']) >= 1

        token = _login(client)
        broker_headers = {'Authorization': f'Bearer {token}'}
        broker_snapshot = client.post(
            f'/broker/admin/canvas/documents/{canvas_id}/snapshots',
            headers=broker_headers,
            json={'label': 'Broker compare', 'tenant_id': 'tenant-s', 'workspace_id': 'ws-shared', 'environment': 'dev'},
        )
        assert broker_snapshot.status_code == 200, broker_snapshot.text
        broker_snapshot_id = broker_snapshot.json()['snapshot']['snapshot_id']

        compare = client.get(
            f'/broker/admin/canvas/snapshots/compare?snapshot_a_id={snapshot_id}&snapshot_b_id={broker_snapshot_id}&tenant_id=tenant-s&workspace_id=ws-shared&environment=dev',
            headers=broker_headers,
        )
        assert compare.status_code == 200, compare.text
        assert compare.json()['ok'] is True

        ui = client.get('/ui')
        assert ui.status_code == 200
        assert 'Collaboration' in ui.text
