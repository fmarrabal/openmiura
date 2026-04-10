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


def test_phase8_pr8_packaging_hardening_http_and_broker_endpoints(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv('OPENMIURA_UI_ADMIN_USERNAME', 'admin')
    monkeypatch.setenv('OPENMIURA_UI_ADMIN_PASSWORD', 'secret123')
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    with TestClient(app) as client:
        headers = {'Authorization': 'Bearer secret-admin'}
        summary = client.get('/admin/phase8/packaging/summary', headers=headers)
        assert summary.status_code == 200, summary.text
        assert summary.json()['hardening']['profile']['pwa']['microphone_permission'] == 'self'

        created = client.post(
            '/admin/phase8/packaging/builds',
            headers=headers,
            json={
                'actor': 'admin',
                'target': 'desktop',
                'label': 'HTTP desktop shell',
                'artifact_path': 'dist/http-desktop.zip',
                'tenant_id': 'tenant-http',
                'workspace_id': 'ws-admin',
                'environment': 'dev',
            },
        )
        assert created.status_code == 200, created.text
        build_id = created.json()['build']['build_id']

        listed = client.get(
            '/admin/phase8/packaging/builds?tenant_id=tenant-http&workspace_id=ws-admin&environment=dev',
            headers=headers,
        )
        assert listed.status_code == 200, listed.text
        assert any(item['build_id'] == build_id for item in listed.json()['items'])

        token = _login(client)
        broker_headers = {'Authorization': f'Bearer {token}'}
        broker_summary = client.get('/broker/admin/phase8/packaging/summary', headers=broker_headers)
        assert broker_summary.status_code == 200, broker_summary.text

        broker_created = client.post(
            '/broker/admin/phase8/packaging/builds',
            headers=broker_headers,
            json={
                'target': 'mobile',
                'label': 'Broker mobile shell',
                'artifact_path': 'dist/broker-mobile.zip',
                'tenant_id': 'tenant-http',
                'workspace_id': 'ws-admin',
                'environment': 'dev',
            },
        )
        assert broker_created.status_code == 200, broker_created.text
        assert broker_created.json()['build']['target'] == 'mobile'

        ui = client.get('/ui')
        assert ui.status_code == 200
        assert 'Packaging &amp; hardening' in ui.text
        assert ui.headers['Permissions-Policy'] == 'camera=(), microphone=(self), geolocation=()'
