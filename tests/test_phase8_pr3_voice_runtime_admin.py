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


def test_phase8_pr3_voice_runtime_http_and_broker_admin_endpoints(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv('OPENMIURA_UI_ADMIN_USERNAME', 'admin')
    monkeypatch.setenv('OPENMIURA_UI_ADMIN_PASSWORD', 'secret123')
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    with TestClient(app) as client:
        headers = {'Authorization': 'Bearer secret-admin'}
        started = client.post(
            '/admin/voice/sessions',
            headers=headers,
            json={'actor': 'admin', 'user_key': 'voice:user-http', 'tenant_id': 'tenant-v', 'workspace_id': 'ws-voice', 'environment': 'dev'},
        )
        assert started.status_code == 200, started.text
        voice_session_id = started.json()['session']['voice_session_id']

        transcribed = client.post(
            f'/admin/voice/sessions/{voice_session_id}/transcribe',
            headers=headers,
            json={'actor': 'admin', 'transcript_text': 'approve this deployment', 'tenant_id': 'tenant-v', 'workspace_id': 'ws-voice', 'environment': 'dev'},
        )
        assert transcribed.status_code == 200, transcribed.text
        assert transcribed.json()['command']['status'] == 'pending_confirmation'

        confirmed = client.post(
            f'/admin/voice/sessions/{voice_session_id}/confirm',
            headers=headers,
            json={'actor': 'admin', 'decision': 'confirm', 'confirmation_text': 'yes confirm', 'tenant_id': 'tenant-v', 'workspace_id': 'ws-voice', 'environment': 'dev'},
        )
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()['command']['status'] == 'confirmed'

        detail = client.get(
            f'/admin/voice/sessions/{voice_session_id}?tenant_id=tenant-v&workspace_id=ws-voice&environment=dev',
            headers=headers,
        )
        assert detail.status_code == 200, detail.text
        assert detail.json()['session']['status'] == 'active'

        token = _login(client)
        broker_headers = {'Authorization': f'Bearer {token}'}
        broker_started = client.post(
            '/broker/admin/voice/sessions',
            headers=broker_headers,
            json={'user_key': 'voice:user-broker', 'tenant_id': 'tenant-v', 'workspace_id': 'ws-voice', 'environment': 'dev'},
        )
        assert broker_started.status_code == 200, broker_started.text
        broker_voice_session_id = broker_started.json()['session']['voice_session_id']

        broker_transcribed = client.post(
            f'/broker/admin/voice/sessions/{broker_voice_session_id}/transcribe',
            headers=broker_headers,
            json={'transcript_text': 'check status', 'tenant_id': 'tenant-v', 'workspace_id': 'ws-voice', 'environment': 'dev'},
        )
        assert broker_transcribed.status_code == 200, broker_transcribed.text
        assert broker_transcribed.json()['command']['status'] == 'executed'

        ui = client.get('/ui')
        assert ui.status_code == 200
        assert 'Voice Runtime' in ui.text
