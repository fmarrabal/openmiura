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


def test_phase8_pr6_canvas_http_admin_timeline_and_confirmation(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv('OPENMIURA_UI_ADMIN_USERNAME', 'admin')
    monkeypatch.setenv('OPENMIURA_UI_ADMIN_PASSWORD', 'secret123')
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    with TestClient(app) as client:
        headers = {'Authorization': 'Bearer secret-admin'}
        canvas = client.post(
            '/admin/canvas/documents',
            headers=headers,
            json={'actor': 'admin', 'title': 'Ops canvas', 'tenant_id': 'tenant-z', 'workspace_id': 'ws-z', 'environment': 'prod'},
        )
        assert canvas.status_code == 200, canvas.text
        canvas_id = canvas.json()['document']['canvas_id']

        workflow_row = app.state.gw.audit.create_workflow(
            name='ops-flow',
            definition={'steps': [{'id': 'n1', 'kind': 'note', 'note': 'hello'}]},
            created_by='admin',
            tenant_id='tenant-z',
            workspace_id='ws-z',
            environment='prod',
        )
        workflow_id = workflow_row['workflow_id']
        app.state.gw.audit.update_workflow_state(
            workflow_id,
            status='running',
            tenant_id='tenant-z',
            workspace_id='ws-z',
            environment='prod',
        )
        node = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes',
            headers=headers,
            json={
                'actor': 'admin',
                'node_type': 'workflow',
                'label': 'Workflow node',
                'data': {'workflow_id': workflow_id},
                'tenant_id': 'tenant-z',
                'workspace_id': 'ws-z',
                'environment': 'prod',
            },
        )
        assert node.status_code == 200, node.text
        node_id = node.json()['node']['node_id']

        timeline = client.get(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/timeline?tenant_id=tenant-z&workspace_id=ws-z&environment=prod',
            headers=headers,
        )
        assert timeline.status_code == 200, timeline.text
        assert timeline.json()['ok'] is True

        blocked = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/cancel?tenant_id=tenant-z&workspace_id=ws-z&environment=prod',
            headers=headers,
            json={'actor': 'admin', 'session_id': 'canvas-admin'},
        )
        assert blocked.status_code == 200, blocked.text
        assert blocked.json()['error'] == 'confirmation_required'

        confirmed = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/cancel?tenant_id=tenant-z&workspace_id=ws-z&environment=prod',
            headers=headers,
            json={'actor': 'admin', 'session_id': 'canvas-admin', 'payload': {'confirmed': True}},
        )
        assert confirmed.status_code == 200, confirmed.text
        body = confirmed.json()
        assert body['ok'] is True
        assert body['reconciled'] is True
        assert body['refresh']['related']['workflow']['workflow']['status'] == 'cancelled'
