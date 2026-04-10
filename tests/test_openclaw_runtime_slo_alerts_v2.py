from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

import app as app_module
from openmiura.application.openclaw import OpenClawRecoverySchedulerService
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


def test_admin_and_canvas_surface_runtime_slo_alerts(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    scheduler = OpenClawRecoverySchedulerService()

    with TestClient(app) as client:
        headers = {'Authorization': 'Bearer secret-admin'}
        runtime_resp = client.post(
            '/admin/openclaw/runtimes',
            headers=headers,
            json={
                'actor': 'admin',
                'name': 'runtime-slo',
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
                        'runtime_stale_after_s': 1,
                        'active_run_stale_after_s': 0,
                        'auto_reconcile_after_s': 60,
                        'poll_interval_s': 1,
                        'max_poll_retries': 0,
                        'auto_poll_enabled': False,
                        'auto_reconcile_enabled': False,
                        'stale_target_status': 'timed_out',
                    },
                    'slo_policy': {
                        'runtime_run_warn_ratio': 0.5,
                        'runtime_run_critical_ratio': 1.0,
                        'workspace_run_warn_ratio': 0.5,
                        'workspace_run_critical_ratio': 1.0,
                        'workspace_slot_warn_ratio': 0.5,
                        'workspace_slot_critical_ratio': 1.0,
                        'stale_active_warn_count': 1,
                        'stale_active_critical_count': 1,
                        'stale_active_warn_ratio': 0.2,
                        'stale_active_critical_ratio': 0.5,
                        'long_lease_warn_after_s': 0,
                        'long_lease_critical_after_s': 0,
                        'long_lease_warn_count': 1,
                        'long_lease_critical_count': 1,
                        'stuck_idempotency_warn_after_s': 0,
                        'stuck_idempotency_critical_after_s': 0,
                        'idempotency_warn_count': 1,
                        'idempotency_critical_count': 1,
                        'runtime_stale_warn_after_s': 0,
                        'runtime_stale_critical_after_s': 0,
                    },
                    'session_bridge': {
                        'enabled': True,
                        'workspace_connection': 'primary-conn',
                        'external_workspace_id': 'oc-ws-a',
                        'external_environment': 'prod',
                        'event_bridge_enabled': True,
                    },
                    'event_bridge': {
                        'token': 'evt-slo',
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
            json={'actor': 'admin', 'title': 'SLO canvas', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert canvas_resp.status_code == 200, canvas_resp.text
        canvas_id = canvas_resp.json()['document']['canvas_id']
        node_resp = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes',
            headers=headers,
            json={'actor': 'admin', 'node_type': 'openclaw_runtime', 'label': 'SLO runtime', 'data': {'runtime_id': runtime_id}, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert node_resp.status_code == 200, node_resp.text
        node_id = node_resp.json()['node']['node_id']

        dispatch_resp = client.post(
            f'/admin/openclaw/runtimes/{runtime_id}/dispatch',
            headers=headers,
            json={'actor': 'admin', 'action': 'chat', 'agent_id': 'default', 'payload': {'message': 'hola'}, 'session_id': 'slo-001', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert dispatch_resp.status_code == 200, dispatch_resp.text

        job_resp = client.post(
            f'/admin/openclaw/runtimes/{runtime_id}/recovery-jobs',
            headers=headers,
            json={'actor': 'admin', 'reason': 'slo test', 'schedule_kind': 'interval', 'interval_s': 5, 'not_before': time.time() - 1, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert job_resp.status_code == 200, job_resp.text
        job_id = job_resp.json()['job']['job_id']

        gw = app.state.gw
        scope = {'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'}
        runtime_lease = gw.audit.acquire_worker_lease(
            lease_key=scheduler._runtime_lease_key(runtime_id),
            holder_id='worker-a',
            lease_ttl_s=60,
            metadata={'kind': 'runtime'},
            **scope,
        )
        assert runtime_lease['acquired'] is True
        workspace_lease = gw.audit.acquire_worker_lease(
            lease_key=scheduler._workspace_lease_keys(scope, limit=1)[0],
            holder_id='worker-a',
            lease_ttl_s=60,
            metadata={'kind': 'workspace'},
            **scope,
        )
        assert workspace_lease['acquired'] is True
        idem = gw.audit.claim_idempotency_record(
            idempotency_key=scheduler._job_idempotency_key(job_id, int(time.time())),
            holder_id='worker-a',
            ttl_s=300,
            scope_kind='openclaw_runtime_recovery',
            metadata={'runtime_id': runtime_id},
            **scope,
        )
        assert idem['claimed'] is True

        runtime_alerts = client.get(
            f'/admin/openclaw/runtimes/{runtime_id}/alerts?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert runtime_alerts.status_code == 200, runtime_alerts.text
        alerts_payload = runtime_alerts.json()
        codes = {item['code'] for item in alerts_payload['items']}
        assert 'runtime_run_saturation' in codes
        assert 'workspace_run_saturation' in codes
        assert 'workspace_scheduler_saturation' in codes
        assert 'stale_run_pressure' in codes
        assert 'worker_leases_too_long' in codes
        assert 'idempotency_records_stuck' in codes
        assert 'runtime_heartbeat_stale' in codes
        assert alerts_payload['summary']['critical_count'] >= 4

        all_alerts = client.get(
            '/admin/openclaw/runtime-alerts?tenant_id=tenant-a&workspace_id=ws-a&environment=prod&severity=critical',
            headers=headers,
        )
        assert all_alerts.status_code == 200, all_alerts.text
        assert all_alerts.json()['summary']['critical_count'] >= 1

        board = client.get(
            f'/admin/canvas/documents/{canvas_id}/views/runtime-board?tenant_id=tenant-a&workspace_id=ws-a&environment=prod&limit=10',
            headers=headers,
        )
        assert board.status_code == 200, board.text
        board_payload = board.json()
        assert board_payload['summary']['alert_count'] >= 1
        assert board_payload['summary']['critical_alert_count'] >= 1
        assert 'runtime_run_saturation' in board_payload['summary']['alert_code_counts']
        entry = board_payload['items'][0]
        assert entry['alerts']['summary']['critical_count'] >= 1
        assert entry['summary']['alert_count'] >= 1
        assert 'worker_leases_too_long' in entry['summary']['alert_code_counts']

        inspector = client.get(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert inspector.status_code == 200, inspector.text
        inspector_payload = inspector.json()
        assert inspector_payload['related']['runtime_alerts']['summary']['critical_count'] >= 1

        timeline = client.get(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/timeline?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert timeline.status_code == 200, timeline.text
        kinds = {item['kind'] for item in timeline.json()['items']}
        assert 'alert' in kinds
