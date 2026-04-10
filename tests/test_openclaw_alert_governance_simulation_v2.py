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
        'slo_policy': {
            'runtime_run_warn_ratio': 0.5,
            'runtime_run_critical_ratio': 1.0,
            'workspace_run_warn_ratio': 0.5,
            'workspace_run_critical_ratio': 1.0,
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


def test_alert_governance_simulation_endpoint_explains_affected_alerts(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        runtime_id = _create_runtime(client, headers, name='runtime-governance-sim', metadata=_base_metadata())
        _dispatch_active_run(client, headers, runtime_id, session_id='gov-sim-001')

        sim_resp = client.post(
            f'/admin/openclaw/runtimes/{runtime_id}/alert-governance/simulate',
            headers=headers,
            json={
                'candidate_policy': {
                    'default_timezone': 'UTC',
                    'quiet_hours': {
                        'enabled': True,
                        'timezone': 'UTC',
                        'weekdays': [_weekday_utc()],
                        'start_time': '00:00',
                        'end_time': '23:59',
                        'action': 'schedule',
                    },
                },
                'include_unchanged': False,
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert sim_resp.status_code == 200, sim_resp.text
        payload = sim_resp.json()
        assert payload['ok'] is True
        assert payload['mode'] == 'dry-run'
        assert payload['policy_diff']['changed'] is True
        assert payload['summary']['affected_count'] >= 1
        assert payload['items']

        runtime_alert = next(item for item in payload['items'] if item['alert']['code'] == 'runtime_run_saturation')
        assert runtime_alert['baseline']['decision']['status'] == 'allow'
        assert runtime_alert['candidate']['decision']['status'] == 'scheduled'
        assert runtime_alert['change_summary']['affected'] is True
        assert runtime_alert['change_summary']['transition'] == 'allow->scheduled'
        explanation = runtime_alert['candidate']['explain']['explanation']
        assert explanation
        assert explanation[0]['source'] == 'quiet_hours'
        assert payload['summary']['newly_scheduled_count'] >= 1


def test_canvas_runtime_action_can_simulate_governance_policy_dry_run(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    metadata = _base_metadata()
    metadata['alert_governance_policy'] = {
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

    with TestClient(app) as client:
        runtime_id = _create_runtime(client, headers, name='runtime-governance-canvas', metadata=metadata)
        _dispatch_active_run(client, headers, runtime_id, session_id='gov-sim-002')

        canvas = client.post(
            '/admin/canvas/documents',
            headers=headers,
            json={'actor': 'admin', 'title': 'Governance simulation canvas', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
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
        assert 'simulate_alert_governance' in inspector.json()['available_actions']

        action = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/simulate_alert_governance?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={
                'actor': 'admin',
                'reason': 'preview override policy',
                'payload': {
                    'alert_code': 'runtime_run_saturation',
                    'candidate_policy': {
                        'override_policies': [
                            {
                                'policy_id': 'ws-prod-disable-quiet-hours',
                                'match': {'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
                                'quiet_hours': {'enabled': False},
                            }
                        ],
                    },
                },
            },
        )
        assert action.status_code == 200, action.text
        result = action.json()['result']
        assert result['mode'] == 'dry-run'
        assert result['summary']['affected_count'] == 1
        simulated = result['items'][0]
        assert simulated['alert']['code'] == 'runtime_run_saturation'
        assert simulated['baseline']['decision']['status'] == 'scheduled'
        assert simulated['candidate']['decision']['status'] == 'allow'
        assert simulated['change_summary']['newly_allowed'] is True
