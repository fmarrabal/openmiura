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


def test_phase8_http_admin_release_endpoints(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv('OPENMIURA_UI_ADMIN_USERNAME', 'admin')
    monkeypatch.setenv('OPENMIURA_UI_ADMIN_PASSWORD', 'secret123')
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    with TestClient(app) as client:
        headers = {'Authorization': 'Bearer secret-admin'}
        created = client.post(
            '/admin/releases',
            headers=headers,
            json={
                'kind': 'workflow',
                'name': 'doc-triage',
                'version': '0.1.0',
                'created_by': 'admin',
                'environment': 'dev',
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-1',
                'items': [{'item_kind': 'workflow', 'item_key': 'triage', 'item_version': '0.1.0', 'payload': {'steps': 2}}],
            },
        )
        assert created.status_code == 200, created.text
        release_id = created.json()['release']['release_id']

        listed = client.get('/admin/releases?tenant_id=tenant-a&workspace_id=ws-1', headers=headers)
        assert listed.status_code == 200
        assert listed.json()['items'][0]['release_id'] == release_id

        submitted = client.post(f'/admin/releases/{release_id}/submit', headers=headers, json={'actor': 'admin', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-1'})
        assert submitted.status_code == 200
        approved = client.post(f'/admin/releases/{release_id}/approve', headers=headers, json={'actor': 'admin', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-1'})
        assert approved.status_code == 200
        promoted = client.post(f'/admin/releases/{release_id}/promote', headers=headers, json={'actor': 'admin', 'to_environment': 'staging', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-1'})
        assert promoted.status_code == 200
        assert promoted.json()['release']['status'] == 'promoted'

        detail = client.get(f'/admin/releases/{release_id}?tenant_id=tenant-a&workspace_id=ws-1', headers=headers)
        assert detail.status_code == 200, detail.text
        payload = detail.json()
        assert payload['release']['environment'] == 'staging'
        assert payload['promotions'][0]['to_environment'] == 'staging'
        assert payload['available_actions'] == ['rollback']
        assert payload['items'][0]['item_key'] == 'triage'

        bad = client.post('/admin/releases', headers=headers, json={'kind': 'unsupported', 'name': 'x', 'version': '1'})
        assert bad.status_code == 400


def test_phase8_broker_admin_release_endpoints_and_ui_tab(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv('OPENMIURA_UI_ADMIN_USERNAME', 'admin')
    monkeypatch.setenv('OPENMIURA_UI_ADMIN_PASSWORD', 'secret123')
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    with TestClient(app) as client:
        token = _login(client)
        headers = {'Authorization': f'Bearer {token}'}
        created = client.post(
            '/broker/admin/releases',
            headers=headers,
            json={
                'kind': 'agent',
                'name': 'ops-agent',
                'version': '2.0.0',
                'environment': 'dev',
                'tenant_id': 'tenant-b',
                'workspace_id': 'ws-2',
                'items': [{'item_kind': 'prompt_pack', 'item_key': 'ops-pack', 'item_version': '2.0.0', 'payload': {'prompt_count': 4}}],
            },
        )
        assert created.status_code == 200, created.text
        release_id = created.json()['release']['release_id']

        detail = client.get(f'/broker/admin/releases/{release_id}?tenant_id=tenant-b&workspace_id=ws-2', headers=headers)
        assert detail.status_code == 200, detail.text
        assert detail.json()['release']['name'] == 'ops-agent'

        client.post(f'/broker/admin/releases/{release_id}/submit', headers=headers, json={'tenant_id': 'tenant-b', 'workspace_id': 'ws-2'})
        client.post(f'/broker/admin/releases/{release_id}/approve', headers=headers, json={'tenant_id': 'tenant-b', 'workspace_id': 'ws-2'})
        promoted = client.post(
            f'/broker/admin/releases/{release_id}/promote',
            headers=headers,
            json={'to_environment': 'prod', 'tenant_id': 'tenant-b', 'workspace_id': 'ws-2'},
        )
        assert promoted.status_code == 200, promoted.text
        assert promoted.json()['target_environment'] == 'prod'

        ui = client.get('/ui')
        assert ui.status_code == 200
        assert 'Release Governance' in ui.text
