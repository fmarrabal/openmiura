from __future__ import annotations

import base64
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


def test_phase9_operational_hardening_http_and_broker_endpoints(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv('OPENMIURA_UI_ADMIN_USERNAME', 'admin')
    monkeypatch.setenv('OPENMIURA_UI_ADMIN_PASSWORD', 'secret123')
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    with TestClient(app) as client:
        headers = {'Authorization': 'Bearer secret-admin'}
        started = client.post('/admin/voice/sessions', headers=headers, json={'actor': 'admin', 'user_key': 'voice:http', 'stt_provider': 'local-inline-stt', 'tts_provider': 'local-wave-tts', 'tenant_id': 'tenant-v', 'workspace_id': 'ws-v', 'environment': 'dev'})
        assert started.status_code == 200, started.text
        voice_session_id = started.json()['session']['voice_session_id']

        audio = client.post(
            f'/admin/voice/sessions/{voice_session_id}/audio/transcribe',
            headers=headers,
            json={'actor': 'admin', 'audio_b64': base64.b64encode(b'check status via http audio').decode('ascii'), 'tenant_id': 'tenant-v', 'workspace_id': 'ws-v', 'environment': 'dev'},
        )
        assert audio.status_code == 200, audio.text
        assert audio.json()['provider_call']['provider_kind'] == 'stt'

        baseline = client.post('/admin/releases', headers=headers, json={'kind': 'workflow', 'name': 'ops-http', 'version': '1.0.0', 'created_by': 'admin', 'environment': 'prod', 'tenant_id': 'tenant-r', 'workspace_id': 'ws-r'})
        candidate = client.post('/admin/releases', headers=headers, json={'kind': 'workflow', 'name': 'ops-http', 'version': '1.1.0', 'created_by': 'admin', 'environment': 'staging', 'tenant_id': 'tenant-r', 'workspace_id': 'ws-r'})
        baseline_id = baseline.json()['release']['release_id']
        candidate_id = candidate.json()['release']['release_id']
        for rid in (baseline_id, candidate_id):
            assert client.post(f'/admin/releases/{rid}/submit', headers=headers, json={'actor': 'admin', 'tenant_id': 'tenant-r', 'workspace_id': 'ws-r'}).status_code == 200
            assert client.post(f'/admin/releases/{rid}/approve', headers=headers, json={'actor': 'admin', 'tenant_id': 'tenant-r', 'workspace_id': 'ws-r'}).status_code == 200
        assert client.post(f'/admin/releases/{baseline_id}/promote', headers=headers, json={'actor': 'admin', 'to_environment': 'prod', 'tenant_id': 'tenant-r', 'workspace_id': 'ws-r'}).status_code == 200
        assert client.post(f'/admin/releases/{candidate_id}/canary', headers=headers, json={'actor': 'admin', 'target_environment': 'prod', 'traffic_percent': 20, 'tenant_id': 'tenant-r', 'workspace_id': 'ws-r'}).status_code == 200
        assert client.post(f'/admin/releases/{candidate_id}/gates', headers=headers, json={'actor': 'qa', 'gate_name': 'shadow', 'status': 'passed', 'tenant_id': 'tenant-r', 'workspace_id': 'ws-r', 'environment': 'prod'}).status_code == 200
        activate = client.post(f'/admin/releases/{candidate_id}/canary/activate', headers=headers, json={'actor': 'admin', 'baseline_release_id': baseline_id, 'tenant_id': 'tenant-r', 'workspace_id': 'ws-r'})
        assert activate.status_code == 200, activate.text
        routed = client.post(f'/admin/releases/{candidate_id}/canary/route', headers=headers, json={'actor': 'admin', 'routing_key': 'user-http-1', 'tenant_id': 'tenant-r', 'workspace_id': 'ws-r'})
        assert routed.status_code == 200, routed.text
        decision_id = routed.json()['decision']['decision_id']
        observed = client.post(f'/admin/releases/canary/decisions/{decision_id}/observe', headers=headers, json={'actor': 'admin', 'success': True, 'latency_ms': 90.0, 'tenant_id': 'tenant-r', 'workspace_id': 'ws-r'})
        assert observed.status_code == 200, observed.text
        summary = client.get(f'/admin/releases/{candidate_id}/canary/routing-summary?tenant_id=tenant-r&workspace_id=ws-r&target_environment=prod', headers=headers)
        assert summary.status_code == 200, summary.text
        assert summary.json()['summary']['total_decisions'] >= 1

        repro = client.post('/admin/phase9/packaging/reproducible-build', headers=headers, json={'actor': 'admin', 'target': 'desktop', 'label': 'HTTP repro', 'source_root': str(tmp_path), 'output_dir': str(tmp_path / 'dist'), 'tenant_id': 'tenant-p', 'workspace_id': 'ws-p', 'environment': 'dev'})
        assert repro.status_code == 200, repro.text
        verify = client.post('/admin/phase9/packaging/verify-manifest', headers=headers, json={'manifest_path': repro.json()['manifest_path']})
        assert verify.status_code == 200, verify.text
        assert verify.json()['ok'] is True

        token = _login(client)
        broker_headers = {'Authorization': f'Bearer {token}'}
        broker_repro = client.post('/broker/admin/phase9/packaging/reproducible-build', headers=broker_headers, json={'target': 'mobile', 'label': 'Broker repro', 'source_root': str(tmp_path), 'output_dir': str(tmp_path / 'dist')})
        assert broker_repro.status_code == 200, broker_repro.text
        broker_voice = client.post(f'/broker/admin/voice/sessions/{voice_session_id}/audio/transcribe', headers=broker_headers, json={'audio_b64': base64.b64encode(b'status from broker').decode('ascii'), 'tenant_id': 'tenant-v', 'workspace_id': 'ws-v', 'environment': 'dev'})
        assert broker_voice.status_code == 200, broker_voice.text
