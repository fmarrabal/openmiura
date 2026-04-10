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
    }


def _create_runtime(client: TestClient, headers: dict[str, str], *, name: str, metadata: dict[str, object]) -> str:
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
            'metadata': metadata,
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


def test_admin_runtime_alert_governance_activation_versions_and_rollback(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        runtime_id = _create_runtime(client, headers, name='runtime-governance-activate', metadata=_base_metadata())
        _dispatch_active_run(client, headers, runtime_id, session_id='gov-activate-001')

        activate = client.post(
            f'/admin/openclaw/runtimes/{runtime_id}/alert-governance/activate',
            headers=headers,
            json={
                'actor': 'admin',
                'candidate_policy': _candidate_policy(),
                'reason': 'promote schedule policy',
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert activate.status_code == 200, activate.text
        activation_payload = activate.json()
        assert activation_payload['ok'] is True
        assert activation_payload['version']['change_kind'] == 'activation'
        assert activation_payload['version']['status'] == 'active'
        assert activation_payload['simulation']['summary']['affected_count'] >= 1
        assert activation_payload['runtime_summary']['alert_governance_policy']['quiet_hours']['enabled'] is True
        activated_version_id = activation_payload['version']['version_id']

        versions = client.get(
            f'/admin/openclaw/runtimes/{runtime_id}/alert-governance/versions?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert versions.status_code == 200, versions.text
        versions_payload = versions.json()
        assert versions_payload['summary']['count'] == 1
        assert versions_payload['current_version']['version_id'] == activated_version_id
        assert versions_payload['items'][0]['summary']['affected_count'] >= 1

        rollback = client.post(
            f'/admin/openclaw/runtimes/{runtime_id}/alert-governance/versions/{activated_version_id}/rollback',
            headers=headers,
            json={
                'actor': 'admin',
                'reason': 'restore baseline',
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert rollback.status_code == 200, rollback.text
        rollback_payload = rollback.json()
        assert rollback_payload['ok'] is True
        assert rollback_payload['version']['change_kind'] == 'rollback'
        assert rollback_payload['restored_version']['version_id'] == activated_version_id
        assert rollback_payload['runtime_summary']['alert_governance_policy']['quiet_hours']['enabled'] is False

        versions_after = client.get(
            f'/admin/openclaw/runtimes/{runtime_id}/alert-governance/versions?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert versions_after.status_code == 200, versions_after.text
        versions_after_payload = versions_after.json()
        assert versions_after_payload['summary']['count'] == 2
        assert versions_after_payload['summary']['current_version_no'] == 2
        assert versions_after_payload['current_version']['change_kind'] == 'rollback'


def test_canvas_runtime_actions_can_activate_and_rollback_governance_versions(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        runtime_id = _create_runtime(client, headers, name='runtime-governance-canvas-activate', metadata=_base_metadata())
        _dispatch_active_run(client, headers, runtime_id, session_id='gov-activate-002')

        canvas = client.post(
            '/admin/canvas/documents',
            headers=headers,
            json={'actor': 'admin', 'title': 'Governance activation canvas', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
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
        assert 'activate_alert_governance' in available_actions
        assert 'rollback_alert_governance' in available_actions

        activate_action = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/activate_alert_governance?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={
                'actor': 'admin',
                'reason': 'activate from canvas',
                'payload': {
                    'candidate_policy': _candidate_policy(),
                    'alert_code': 'runtime_run_saturation',
                },
            },
        )
        assert activate_action.status_code == 200, activate_action.text
        activate_result = activate_action.json()['result']
        assert activate_result['version']['change_kind'] == 'activation'
        activated_version_id = activate_result['version']['version_id']

        rollback_action = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/rollback_alert_governance?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={
                'actor': 'admin',
                'reason': 'rollback from canvas',
                'payload': {
                    'version_id': activated_version_id,
                },
            },
        )
        assert rollback_action.status_code == 200, rollback_action.text
        rollback_result = rollback_action.json()['result']
        assert rollback_result['rollback']['rollback_of_version_id'] == activated_version_id
        assert rollback_result['version']['change_kind'] == 'rollback'
