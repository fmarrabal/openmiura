from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import app as app_module
from openmiura.gateway import Gateway
import openmiura.application.openclaw.scheduler as scheduler_mod
import openmiura.application.openclaw.service as openclaw_service_mod
import openmiura.application.jobs.service as job_service_mod


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


def _base_metadata(*, runtime_stale_after_s: int = 120) -> dict[str, object]:
    return {
        'runtime_class': 'incident',
        'allowed_actions': ['chat'],
        'dispatch_policy': {
            'dispatch_mode': 'async',
            'poll_after_s': 0.1,
            'max_active_runs': 2,
            'max_active_runs_per_workspace': 3,
        },
        'heartbeat_policy': {
            'runtime_stale_after_s': runtime_stale_after_s,
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
            'approval_required': False,
            'requested_role': 'security',
            'ttl_s': 1800,
            'require_signature': True,
            'signer_key_id': 'governance-ci',
        },
    }


def _candidate_policy() -> dict[str, object]:
    return {
        'default_timezone': 'UTC',
        'quiet_hours': {
            'enabled': True,
            'timezone': 'UTC',
            'weekdays': [0, 1, 2, 3, 4, 5, 6],
            'start_time': '00:00',
            'end_time': '23:59',
            'action': 'schedule',
        },
    }


def _create_runtime(client: TestClient, headers: dict[str, str], *, name: str, runtime_stale_after_s: int = 120) -> str:
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
            'metadata': _base_metadata(runtime_stale_after_s=runtime_stale_after_s),
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()['runtime']['runtime_id']


def _create_and_approve_bundle(client: TestClient, headers: dict[str, str], payload: dict[str, object]) -> str:
    create = client.post('/admin/openclaw/alert-governance/bundles', headers=headers, json=payload)
    assert create.status_code == 200, create.text
    bundle_id = create.json()['bundle_id']
    submit = client.post(
        f'/admin/openclaw/alert-governance/bundles/{bundle_id}/submit',
        headers=headers,
        json={'actor': 'admin', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
    )
    assert submit.status_code == 200, submit.text
    approve = client.post(
        f'/admin/openclaw/alert-governance/bundles/{bundle_id}/approve',
        headers=headers,
        json={'actor': 'security-admin', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
    )
    assert approve.status_code == 200, approve.text
    return bundle_id


def _set_now(monkeypatch, value: float) -> None:
    monkeypatch.setattr(scheduler_mod.time, 'time', lambda: value)
    monkeypatch.setattr(openclaw_service_mod.time, 'time', lambda: value)
    monkeypatch.setattr(job_service_mod.time, 'time', lambda: value)


def test_wave_bake_window_schedules_auto_advance_job_and_advances_next_wave(tmp_path: Path, monkeypatch) -> None:
    base_ts = 1_750_000_000.0
    _set_now(monkeypatch, base_ts)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        canary_runtime = _create_runtime(client, headers, name='runtime-canary-bake')
        broad_runtime = _create_runtime(client, headers, name='runtime-broad-bake')
        bundle_id = _create_and_approve_bundle(
            client,
            headers,
            {
                'actor': 'admin',
                'name': 'incident-governance-bake',
                'version': '2026.03.29.bake',
                'runtime_ids': [canary_runtime, broad_runtime],
                'candidate_policy': _candidate_policy(),
                'waves': [
                    {'label': 'Canary', 'runtime_ids': [canary_runtime], 'canary': True},
                    {'label': 'Broad rollout', 'runtime_ids': [broad_runtime]},
                ],
                'wave_gates': {
                    'enabled': True,
                    'auto_halt_on_failure': True,
                    'auto_rollback_on_failure': True,
                    'max_stale_runtimes': 1,
                    'max_critical_alerts': 1,
                },
                'wave_timing_policy': {
                    'health_window_s': 10,
                    'bake_time_s': 20,
                    'auto_advance': True,
                },
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )

        run_wave_1 = client.post(
            f'/admin/openclaw/alert-governance/bundles/{bundle_id}/waves/1/run',
            headers=headers,
            json={'actor': 'release-admin', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert run_wave_1.status_code == 200, run_wave_1.text
        payload_1 = run_wave_1.json()
        assert payload_1['bundle']['wave_plan'][0]['observation']['status'] == 'pending'
        assert payload_1['wave_execution']['scheduled_advance_job'] is not None
        assert payload_1['summary']['pending_observation_count'] == 1

        jobs = client.get(
            '/admin/openclaw/alert-governance/advance-jobs?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert jobs.status_code == 200, jobs.text
        jobs_payload = jobs.json()
        assert jobs_payload['summary']['count'] == 1
        assert jobs_payload['summary']['due'] == 0

        not_due = client.post(
            '/admin/openclaw/alert-governance/advance-jobs/run-due',
            headers=headers,
            json={'actor': 'release-bot', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert not_due.status_code == 200, not_due.text
        assert not_due.json()['summary']['executed'] == 0

        _set_now(monkeypatch, base_ts + 31)
        due = client.post(
            '/admin/openclaw/alert-governance/advance-jobs/run-due',
            headers=headers,
            json={'actor': 'release-bot', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert due.status_code == 200, due.text
        due_payload = due.json()
        assert due_payload['summary']['executed'] == 1
        assert due_payload['items'][0]['result']['status'] == 'advanced'

        bundle_detail = client.get(
            f'/admin/openclaw/alert-governance/bundles/{bundle_id}?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert bundle_detail.status_code == 200, bundle_detail.text
        detail = bundle_detail.json()
        assert detail['summary']['rollout_status'] == 'completed'
        assert detail['summary']['active_runtime_count'] >= 2
        assert detail['bundle']['wave_plan'][0]['observation']['status'] == 'advanced'


def test_post_wave_health_window_can_halt_and_rollback_before_next_wave(tmp_path: Path, monkeypatch) -> None:
    base_ts = 1_760_000_000.0
    _set_now(monkeypatch, base_ts)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        canary_runtime = _create_runtime(client, headers, name='runtime-canary-stale', runtime_stale_after_s=120)
        broad_runtime = _create_runtime(client, headers, name='runtime-broad-stale', runtime_stale_after_s=120)
        bundle_id = _create_and_approve_bundle(
            client,
            headers,
            {
                'actor': 'admin',
                'name': 'incident-governance-stale-window',
                'version': '2026.03.29.stale-window',
                'runtime_ids': [canary_runtime, broad_runtime],
                'candidate_policy': _candidate_policy(),
                'waves': [
                    {'label': 'Canary', 'runtime_ids': [canary_runtime], 'canary': True},
                    {'label': 'Broad rollout', 'runtime_ids': [broad_runtime]},
                ],
                'wave_gates': {
                    'enabled': True,
                    'auto_halt_on_failure': True,
                    'auto_rollback_on_failure': True,
                    'max_stale_runtimes': 1,
                    'max_critical_alerts': 1,
                },
                'wave_timing_policy': {
                    'health_window_s': 10,
                    'bake_time_s': 0,
                    'auto_advance': True,
                },
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )

        run_wave_1 = client.post(
            f'/admin/openclaw/alert-governance/bundles/{bundle_id}/waves/1/run',
            headers=headers,
            json={'actor': 'release-admin', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert run_wave_1.status_code == 200, run_wave_1.text
        assert run_wave_1.json()['bundle']['wave_plan'][0]['observation']['status'] == 'pending'

        original_signal_summary = scheduler_mod.OpenClawRecoverySchedulerService._runtime_governance_release_signal_summary

        def _forced_fail(self, gw, *, runtime_id: str, tenant_id=None, workspace_id=None, environment=None, limit: int = 50):
            if runtime_id == canary_runtime:
                return {
                    'runtime_id': runtime_id,
                    'gate_state': 'fail',
                    'reasons': ['post-wave synthetic regression'],
                    'metrics': {
                        'runtime_errors': 0,
                        'pending_approvals': 0,
                        'unhealthy_runtimes': 0,
                        'stale_runtimes': 0,
                        'critical_alerts': 0,
                        'warn_alerts': 0,
                        'total_alerts': 0,
                    },
                    'runtime_summary': {},
                    'health': {},
                    'alerts': {'summary': {}},
                }
            return original_signal_summary(self, gw, runtime_id=runtime_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, limit=limit)

        monkeypatch.setattr(scheduler_mod.OpenClawRecoverySchedulerService, '_runtime_governance_release_signal_summary', _forced_fail)

        _set_now(monkeypatch, base_ts + 11)
        due = client.post(
            '/admin/openclaw/alert-governance/advance-jobs/run-due',
            headers=headers,
            json={'actor': 'release-bot', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert due.status_code == 200, due.text
        due_payload = due.json()
        assert due_payload['summary']['executed'] == 1
        result = due_payload['items'][0]['result']
        assert result['status'] == 'halted'
        assert result['gate_evaluation']['status'] == 'failed'
        assert result['rollback']['count'] == 1

        bundle_detail = client.get(
            f'/admin/openclaw/alert-governance/bundles/{bundle_id}?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert bundle_detail.status_code == 200, bundle_detail.text
        detail = bundle_detail.json()
        assert detail['summary']['rollout_status'] == 'halted'
        assert detail['summary']['halted_wave_no'] == 1
        assert detail['summary']['rollback_executed'] is True

        runtime_detail = client.get(
            f'/admin/openclaw/runtimes/{canary_runtime}?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert runtime_detail.status_code == 200, runtime_detail.text
        assert runtime_detail.json()['runtime_summary']['alert_governance_policy']['quiet_hours']['enabled'] is False
