from __future__ import annotations

from datetime import datetime, timezone
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


def _weekday_utc() -> int:
    return datetime.now(timezone.utc).weekday()


def _base_metadata() -> dict[str, object]:
    return {
        'runtime_class': 'incident',
        'allowed_actions': ['chat'],
        'dispatch_policy': {
            'dispatch_mode': 'async',
            'poll_after_s': 0.1,
            'max_active_runs': 1,
            'max_active_runs_per_workspace': 1,
        },
        'heartbeat_policy': {
            'runtime_stale_after_s': 120,
            'active_run_stale_after_s': 60,
            'auto_reconcile_after_s': 600,
            'poll_interval_s': 5,
            'max_poll_retries': 1,
            'auto_poll_enabled': False,
            'auto_reconcile_enabled': False,
            'stale_target_status': 'timed_out',
        },
        'session_bridge': {
            'enabled': True,
            'workspace_connection': 'primary-conn',
            'external_workspace_id': 'oc-ws-a',
            'external_environment': 'prod',
            'event_bridge_enabled': True,
        },
        'governance_release_policy': {
            'approval_required': True,
            'requested_role': 'security',
            'ttl_s': 1800,
            'require_signature': True,
            'signer_key_id': 'governance-ci',
        },
    }


def _create_runtime(client: TestClient, headers: dict[str, str], *, name: str) -> str:
    resp = client.post(
        '/admin/openclaw/runtimes',
        headers=headers,
        json={
            'actor': 'admin',
            'name': name,
            'base_url': 'simulated://openclaw',
            'transport': 'simulated',
            'allowed_agents': ['default'],
            'tenant_id': 'tenant-a',
            'workspace_id': 'ws-a',
            'environment': 'prod',
            'metadata': _base_metadata(),
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()['runtime']['runtime_id']


def _dispatch_active_run(client: TestClient, headers: dict[str, str], runtime_id: str, *, session_id: str) -> None:
    resp = client.post(
        f'/admin/openclaw/runtimes/{runtime_id}/dispatch',
        headers=headers,
        json={
            'actor': 'admin',
            'action': 'chat',
            'agent_id': 'default',
            'payload': {'message': 'hola'},
            'session_id': session_id,
            'tenant_id': 'tenant-a',
            'workspace_id': 'ws-a',
            'environment': 'prod',
        },
    )
    assert resp.status_code == 200, resp.text


def _candidate_policy() -> dict[str, object]:
    return {
        'default_timezone': 'UTC',
        'quiet_hours': {
            'enabled': True,
            'timezone': 'UTC',
            'weekdays': [_weekday_utc()],
            'start_time': '00:00',
            'end_time': '23:59',
            'action': 'schedule',
        },
    }


def test_governance_activation_requires_approval_and_signs_release(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        runtime_id = _create_runtime(client, headers, name='runtime-governance-approval')
        _dispatch_active_run(client, headers, runtime_id, session_id='gov-prom-001')

        activate = client.post(
            f'/admin/openclaw/runtimes/{runtime_id}/alert-governance/activate',
            headers=headers,
            json={
                'actor': 'admin',
                'candidate_policy': _candidate_policy(),
                'reason': 'critical quiet hours change',
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert activate.status_code == 200, activate.text
        payload = activate.json()
        assert payload['ok'] is True
        assert payload['approval_required'] is True
        assert payload['version']['status'] == 'pending_approval'
        assert payload['approval']['status'] == 'pending'
        assert payload['version']['release']['status'] == 'pending_approval'
        assert payload['runtime_summary']['alert_governance_policy']['quiet_hours']['enabled'] is False
        approval_id = payload['approval']['approval_id']
        version_id = payload['version']['version_id']

        approvals = client.get(
            f'/admin/openclaw/alert-governance-promotion-approvals?runtime_id={runtime_id}&tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert approvals.status_code == 200, approvals.text
        approvals_payload = approvals.json()
        assert approvals_payload['summary']['pending_count'] == 1
        assert approvals_payload['items'][0]['approval_id'] == approval_id
        assert approvals_payload['items'][0]['version_id'] == version_id

        approve = client.post(
            f'/admin/openclaw/alert-governance-promotion-approvals/{approval_id}/decide',
            headers=headers,
            json={
                'actor': 'security-admin',
                'decision': 'approve',
                'reason': 'approved after review',
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert approve.status_code == 200, approve.text
        approved_payload = approve.json()
        assert approved_payload['ok'] is True
        assert approved_payload['approval']['status'] == 'approved'
        assert approved_payload['version']['status'] == 'active'
        assert approved_payload['version']['release']['signed'] is True
        assert approved_payload['version']['release']['signature']
        assert approved_payload['runtime_summary']['alert_governance_policy']['quiet_hours']['enabled'] is True

        versions = client.get(
            f'/admin/openclaw/runtimes/{runtime_id}/alert-governance/versions?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert versions.status_code == 200, versions.text
        versions_payload = versions.json()
        assert versions_payload['current_version']['version_id'] == version_id
        assert versions_payload['current_version']['release']['signed'] is True
        assert versions_payload['current_version']['approval']['status'] == 'approved'


def test_canvas_can_approve_governance_promotion(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        runtime_id = _create_runtime(client, headers, name='runtime-governance-canvas-approval')
        _dispatch_active_run(client, headers, runtime_id, session_id='gov-prom-002')

        activate = client.post(
            f'/admin/openclaw/runtimes/{runtime_id}/alert-governance/activate',
            headers=headers,
            json={
                'actor': 'admin',
                'candidate_policy': _candidate_policy(),
                'reason': 'stage candidate policy',
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert activate.status_code == 200, activate.text
        approval_id = activate.json()['approval']['approval_id']

        canvas = client.post(
            '/admin/canvas/documents',
            headers=headers,
            json={'actor': 'admin', 'title': 'Governance promotion canvas', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert canvas.status_code == 200, canvas.text
        canvas_id = canvas.json()['document']['canvas_id']

        node = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes',
            headers=headers,
            json={
                'actor': 'admin',
                'node_type': 'openclaw_runtime',
                'label': 'Runtime node',
                'data': {'runtime_id': runtime_id},
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert node.status_code == 200, node.text
        node_id = node.json()['node']['node_id']

        inspector = client.get(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert inspector.status_code == 200, inspector.text
        available_actions = inspector.json()['available_actions']
        assert 'approve_governance_promotion' in available_actions
        assert 'reject_governance_promotion' in available_actions

        approve_action = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/approve_governance_promotion?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={
                'actor': 'security-admin',
                'reason': 'approved from canvas',
                'payload': {'approval_id': approval_id},
            },
        )
        assert approve_action.status_code == 200, approve_action.text
        result = approve_action.json()['result']
        assert result['approval']['status'] == 'approved'
        assert result['version']['status'] == 'active'
        assert result['runtime_summary']['alert_governance_policy']['quiet_hours']['enabled'] is True
