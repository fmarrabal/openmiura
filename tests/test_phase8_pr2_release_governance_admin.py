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


def test_phase8_pr2_http_admin_release_governance_endpoints(tmp_path: Path, monkeypatch) -> None:
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
                'kind': 'agent',
                'name': 'ops-agent',
                'version': '3.0.0',
                'created_by': 'admin',
                'environment': 'dev',
                'tenant_id': 'tenant-z',
                'workspace_id': 'ws-9',
                'items': [{'item_kind': 'prompt_pack', 'item_key': 'ops-pack', 'item_version': '3.0.0', 'payload': {'prompts': 7}}],
            },
        )
        assert created.status_code == 200, created.text
        release_id = created.json()['release']['release_id']

        assert client.post(f'/admin/releases/{release_id}/submit', headers=headers, json={'actor': 'admin', 'tenant_id': 'tenant-z', 'workspace_id': 'ws-9'}).status_code == 200
        assert client.post(f'/admin/releases/{release_id}/approve', headers=headers, json={'actor': 'admin', 'tenant_id': 'tenant-z', 'workspace_id': 'ws-9'}).status_code == 200

        canary = client.post(
            f'/admin/releases/{release_id}/canary',
            headers=headers,
            json={
                'actor': 'admin',
                'target_environment': 'prod',
                'traffic_percent': 5,
                'step_percent': 5,
                'bake_minutes': 60,
                'status': 'draft',
                'metric_guardrails': {'error_rate_max': 0.005},
                'analysis_summary': {'real_rollout': False},
                'tenant_id': 'tenant-z',
                'workspace_id': 'ws-9',
            },
        )
        assert canary.status_code == 200, canary.text
        assert canary.json()['canary']['target_environment'] == 'prod'

        gate = client.post(
            f'/admin/releases/{release_id}/gates',
            headers=headers,
            json={
                'actor': 'qa-bot',
                'gate_name': 'shadow-regression',
                'status': 'passed',
                'score': 0.97,
                'threshold': 0.95,
                'details': {'suite': 'prod-shadow'},
                'tenant_id': 'tenant-z',
                'workspace_id': 'ws-9',
                'environment': 'prod',
            },
        )
        assert gate.status_code == 200, gate.text

        report = client.post(
            f'/admin/releases/{release_id}/change-report',
            headers=headers,
            json={
                'actor': 'admin',
                'risk_level': 'low',
                'summary': {'breaking_changes': 0},
                'diff': {'prompt_pack_changed': True},
                'tenant_id': 'tenant-z',
                'workspace_id': 'ws-9',
            },
        )
        assert report.status_code == 200, report.text

        promoted = client.post(
            f'/admin/releases/{release_id}/promote',
            headers=headers,
            json={'actor': 'admin', 'to_environment': 'prod', 'tenant_id': 'tenant-z', 'workspace_id': 'ws-9'},
        )
        assert promoted.status_code == 200, promoted.text

        detail = client.get(f'/admin/releases/{release_id}?tenant_id=tenant-z&workspace_id=ws-9', headers=headers)
        assert detail.status_code == 200, detail.text
        payload = detail.json()
        assert payload['canary']['analysis_summary']['real_rollout'] is False
        assert payload['gate_runs'][0]['gate_name'] == 'shadow-regression'
        assert payload['change_report']['risk_level'] == 'low'
        assert payload['promotions'][0]['summary']['canary']['traffic_percent'] == 5
