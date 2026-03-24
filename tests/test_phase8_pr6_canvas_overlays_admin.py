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


def test_phase8_pr6_canvas_overlay_http_and_broker_endpoints(tmp_path: Path, monkeypatch) -> None:
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
            json={'actor': 'admin', 'title': 'Overlay canvas', 'tenant_id': 'tenant-o', 'workspace_id': 'ws-overlay', 'environment': 'dev'},
        )
        assert created.status_code == 200, created.text
        canvas_id = created.json()['document']['canvas_id']

        node = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes',
            headers=headers,
            json={'actor': 'admin', 'node_type': 'workflow', 'label': 'Workflow root', 'data': {'workflow_id': 'wf-1'}, 'tenant_id': 'tenant-o', 'workspace_id': 'ws-overlay', 'environment': 'dev'},
        )
        assert node.status_code == 200, node.text
        node_id = node.json()['node']['node_id']

        state_saved = client.post(
            f'/admin/canvas/documents/{canvas_id}/overlay-state',
            headers=headers,
            json={'actor': 'admin', 'state_key': 'default', 'toggles': {'policy': True, 'cost': True}, 'inspector': {'selected_node_id': node_id}, 'tenant_id': 'tenant-o', 'workspace_id': 'ws-overlay', 'environment': 'dev'},
        )
        assert state_saved.status_code == 200, state_saved.text

        overlays = client.get(
            f'/admin/canvas/documents/{canvas_id}/overlays?tenant_id=tenant-o&workspace_id=ws-overlay&environment=dev&selected_node_id={node_id}',
            headers=headers,
        )
        assert overlays.status_code == 200, overlays.text
        assert overlays.json()['states'][0]['state_key'] == 'default'

        token = _login(client)
        broker_headers = {'Authorization': f'Bearer {token}'}
        broker_saved = client.post(
            f'/broker/admin/canvas/documents/{canvas_id}/overlay-state',
            headers=broker_headers,
            json={'state_key': 'mobile', 'toggles': {'failures': True, 'approvals': True}, 'tenant_id': 'tenant-o', 'workspace_id': 'ws-overlay', 'environment': 'dev'},
        )
        assert broker_saved.status_code == 200, broker_saved.text

        broker_overlays = client.get(
            f'/broker/admin/canvas/documents/{canvas_id}/overlays?tenant_id=tenant-o&workspace_id=ws-overlay&environment=dev',
            headers=broker_headers,
        )
        assert broker_overlays.status_code == 200, broker_overlays.text
        assert len(broker_overlays.json()['states']) >= 1

        ui = client.get('/ui')
        assert ui.status_code == 200
        assert 'Canvas overlays' in ui.text
