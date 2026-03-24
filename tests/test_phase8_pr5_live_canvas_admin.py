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


def test_phase8_pr5_live_canvas_http_and_broker_admin_endpoints(tmp_path: Path, monkeypatch) -> None:
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
            json={'actor': 'admin', 'title': 'Runtime canvas', 'tenant_id': 'tenant-c', 'workspace_id': 'ws-canvas', 'environment': 'dev'},
        )
        assert created.status_code == 200, created.text
        canvas_id = created.json()['document']['canvas_id']

        node = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes',
            headers=headers,
            json={'actor': 'admin', 'node_type': 'workflow', 'label': 'Workflow root', 'tenant_id': 'tenant-c', 'workspace_id': 'ws-canvas', 'environment': 'dev'},
        )
        assert node.status_code == 200, node.text
        node_id = node.json()['node']['node_id']

        presence = client.post(
            f'/admin/canvas/documents/{canvas_id}/presence',
            headers=headers,
            json={'actor': 'admin', 'user_key': 'operator:alice', 'selected_node_id': node_id, 'tenant_id': 'tenant-c', 'workspace_id': 'ws-canvas', 'environment': 'dev'},
        )
        assert presence.status_code == 200, presence.text

        detail = client.get(
            f'/admin/canvas/documents/{canvas_id}?tenant_id=tenant-c&workspace_id=ws-canvas&environment=dev',
            headers=headers,
        )
        assert detail.status_code == 200, detail.text
        assert detail.json()['document']['title'] == 'Runtime canvas'

        token = _login(client)
        broker_headers = {'Authorization': f'Bearer {token}'}
        broker_created = client.post(
            '/broker/admin/canvas/documents',
            headers=broker_headers,
            json={'title': 'Broker canvas', 'tenant_id': 'tenant-c', 'workspace_id': 'ws-canvas', 'environment': 'dev'},
        )
        assert broker_created.status_code == 200, broker_created.text

        broker_list = client.get('/broker/admin/canvas/documents', headers=broker_headers)
        assert broker_list.status_code == 200, broker_list.text
        assert len(broker_list.json()['items']) >= 1

        ui = client.get('/ui')
        assert ui.status_code == 200
        assert 'Canvas' in ui.text
