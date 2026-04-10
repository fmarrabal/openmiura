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


def test_openclaw_alert_workflows_are_operable_via_admin_and_canvas(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    with TestClient(app) as client:
        headers = {'Authorization': 'Bearer secret-admin'}
        runtime_resp = client.post(
            '/admin/openclaw/runtimes',
            headers=headers,
            json={
                'actor': 'admin',
                'name': 'runtime-alert-workflows',
                'base_url': 'simulated://openclaw',
                'transport': 'simulated',
                'allowed_agents': ['default'],
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
                'metadata': {
                    'runtime_class': 'terminal',
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
                    'alert_workflow_policy': {
                        'default_silence_s': 300,
                        'max_silence_s': 7200,
                        'escalation_max_level': 3,
                    },
                    'session_bridge': {
                        'enabled': True,
                        'workspace_connection': 'primary-conn',
                        'external_workspace_id': 'oc-ws-a',
                        'external_environment': 'prod',
                        'event_bridge_enabled': True,
                    },
                    'event_bridge': {
                        'token': 'evt-alert-workflows',
                        'accepted_sources': ['openclaw'],
                        'accepted_event_types': ['run.progress', 'run.completed'],
                    },
                },
            },
        )
        assert runtime_resp.status_code == 200, runtime_resp.text
        runtime_id = runtime_resp.json()['runtime']['runtime_id']

        canvas_resp = client.post(
            '/admin/canvas/documents',
            headers=headers,
            json={'actor': 'admin', 'title': 'Alert workflows canvas', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert canvas_resp.status_code == 200, canvas_resp.text
        canvas_id = canvas_resp.json()['document']['canvas_id']
        node_resp = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes',
            headers=headers,
            json={'actor': 'admin', 'node_type': 'openclaw_runtime', 'label': 'Alert runtime', 'data': {'runtime_id': runtime_id}, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert node_resp.status_code == 200, node_resp.text
        node_id = node_resp.json()['node']['node_id']

        dispatch_resp = client.post(
            f'/admin/openclaw/runtimes/{runtime_id}/dispatch',
            headers=headers,
            json={'actor': 'admin', 'action': 'chat', 'agent_id': 'default', 'payload': {'message': 'hola'}, 'session_id': 'awf-001', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert dispatch_resp.status_code == 200, dispatch_resp.text

        alerts_resp = client.get(
            f'/admin/openclaw/runtimes/{runtime_id}/alerts?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert alerts_resp.status_code == 200, alerts_resp.text
        alerts_payload = alerts_resp.json()
        alert_codes = {item['code'] for item in alerts_payload['items']}
        assert 'runtime_run_saturation' in alert_codes
        target_alert = next(item for item in alerts_payload['items'] if item['code'] == 'runtime_run_saturation')
        assert 'ack' in target_alert['workflow']['available_actions']

        ack_resp = client.post(
            f'/admin/openclaw/runtimes/{runtime_id}/alerts/runtime_run_saturation/ack',
            headers=headers,
            json={'actor': 'admin', 'note': 'ack from admin api', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert ack_resp.status_code == 200, ack_resp.text
        assert ack_resp.json()['state']['workflow_status'] == 'acked'

        inspector = client.get(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert inspector.status_code == 200, inspector.text
        inspector_payload = inspector.json()
        assert 'ack_alert' in inspector_payload['available_actions']
        assert 'silence_alert' in inspector_payload['available_actions']
        assert 'escalate_alert' in inspector_payload['available_actions']

        silence_action = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/silence_alert?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'admin', 'reason': 'quiet period', 'payload': {'alert_code': 'runtime_run_saturation', 'silence_for_s': 600}, 'session_id': 'canvas-alerts'},
        )
        assert silence_action.status_code == 200, silence_action.text
        assert silence_action.json()['result']['state']['silenced'] is True

        escalate_action = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/escalate_alert?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'admin', 'reason': 'notify oncall', 'payload': {'alert_code': 'runtime_run_saturation', 'target': 'platform-oncall', 'confirmed': True}, 'session_id': 'canvas-alerts'},
        )
        assert escalate_action.status_code == 200, escalate_action.text
        assert escalate_action.json()['result']['state']['workflow_status'] == 'escalated'
        assert escalate_action.json()['result']['state']['escalation_level'] >= 1

        states_resp = client.get(
            f'/admin/openclaw/alert-states?runtime_id={runtime_id}&tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert states_resp.status_code == 200, states_resp.text
        states_payload = states_resp.json()
        state = next(item for item in states_payload['items'] if item['alert_code'] == 'runtime_run_saturation')
        assert state['workflow_status'] == 'escalated'
        assert state['silenced'] is True
        assert state['acked'] is True
        assert state['escalated'] is True

        board = client.get(
            f'/admin/canvas/documents/{canvas_id}/views/runtime-board?tenant_id=tenant-a&workspace_id=ws-a&environment=prod&limit=10',
            headers=headers,
        )
        assert board.status_code == 200, board.text
        board_payload = board.json()
        entry = board_payload['items'][0]
        assert entry['summary']['acked_alert_count'] >= 1
        assert entry['summary']['silenced_alert_count'] >= 1
        assert entry['summary']['escalated_alert_count'] >= 1
        assert entry['alerts']['summary']['workflow_status_counts']['escalated'] >= 1
        assert board_payload['summary']['alert_workflow_status_counts']['escalated'] >= 1

        timeline = client.get(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/timeline?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert timeline.status_code == 200, timeline.text
        kinds = {item['kind'] for item in timeline.json()['items']}
        assert 'alert' in kinds
        assert 'alert_workflow' in kinds
