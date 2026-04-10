from __future__ import annotations

import json
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


def test_phase8_pr4_pwa_http_and_broker_admin_endpoints_and_static_assets(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv('OPENMIURA_UI_ADMIN_USERNAME', 'admin')
    monkeypatch.setenv('OPENMIURA_UI_ADMIN_PASSWORD', 'secret123')
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    with TestClient(app) as client:
        manifest = client.get('/ui/manifest.webmanifest')
        assert manifest.status_code == 200
        manifest_payload = json.loads(manifest.text)
        assert manifest_payload['display'] == 'standalone'

        service_worker = client.get('/ui/service-worker.js')
        assert service_worker.status_code == 200
        assert 'notificationclick' in service_worker.text

        headers = {'Authorization': 'Bearer secret-admin'}
        installed = client.post(
            '/admin/app/installations',
            headers=headers,
            json={
                'actor': 'admin',
                'user_key': 'operator:pwa',
                'device_label': 'Browser test',
                'push_capable': True,
                'notification_permission': 'granted',
                'tenant_id': 'tenant-pwa',
                'workspace_id': 'ws-mobile',
                'environment': 'dev',
            },
        )
        assert installed.status_code == 200, installed.text
        installation_id = installed.json()['installation']['installation_id']

        notified = client.post(
            '/admin/app/notifications',
            headers=headers,
            json={
                'actor': 'admin',
                'title': 'Approval pending',
                'body': 'A release requires action.',
                'installation_id': installation_id,
                'target_path': '/ui/?tab=operator&approval_id=appr_1',
                'tenant_id': 'tenant-pwa',
                'workspace_id': 'ws-mobile',
                'environment': 'dev',
            },
        )
        assert notified.status_code == 200, notified.text
        assert notified.json()['notification']['installation_id'] == installation_id

        linked = client.post(
            '/admin/app/deep-links',
            headers=headers,
            json={
                'actor': 'admin',
                'view': 'operator',
                'target_type': 'approval',
                'target_id': 'appr_1',
                'params': {'approval_id': 'appr_1', 'tab': 'operator'},
                'tenant_id': 'tenant-pwa',
                'workspace_id': 'ws-mobile',
                'environment': 'dev',
            },
        )
        assert linked.status_code == 200, linked.text
        token = linked.json()['deep_link']['link_token']

        redirected = client.get(f'/app/deep-links/{token}', follow_redirects=False)
        assert redirected.status_code == 307
        assert '/ui/?tab=operator' in redirected.headers['location']

        broker_token = _login(client)
        broker_headers = {'Authorization': f'Bearer {broker_token}'}
        broker_installations = client.get('/broker/admin/app/installations', headers=broker_headers)
        assert broker_installations.status_code == 200, broker_installations.text
        assert len(broker_installations.json()['items']) >= 1

        ui = client.get('/ui')
        assert ui.status_code == 200
        assert 'Install app' in ui.text
        assert 'App' in ui.text
