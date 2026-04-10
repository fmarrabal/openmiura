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


def _set_now(monkeypatch, value: float) -> None:
    monkeypatch.setattr(scheduler_mod.time, 'time', lambda: value)
    monkeypatch.setattr(openclaw_service_mod.time, 'time', lambda: value)
    monkeypatch.setattr(job_service_mod.time, 'time', lambda: value)


def _base_metadata() -> dict[str, object]:
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


def _create_runtime(client: TestClient, headers: dict[str, str], *, name: str, signal_overrides: dict[str, object] | None = None) -> str:
    metadata = _base_metadata()
    if signal_overrides:
        metadata['governance_release_signals'] = dict(signal_overrides)
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


def _approve_bundle(client: TestClient, headers: dict[str, str], *, bundle_id: str) -> None:
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


def test_progressive_exposure_policy_builds_waves_and_bundle_analytics_endpoint(tmp_path: Path, monkeypatch) -> None:
    _set_now(monkeypatch, 1_780_000_000.0)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        runtime_ids = [
            _create_runtime(client, headers, name=f'runtime-{idx}')
            for idx in range(1, 6)
        ]
        create = client.post(
            '/admin/openclaw/alert-governance/bundles',
            headers=headers,
            json={
                'actor': 'release-admin',
                'name': 'incident-governance-progressive',
                'version': '2026.03.29.progressive',
                'runtime_ids': runtime_ids,
                'candidate_policy': _candidate_policy(),
                'progressive_exposure_policy': {
                    'enabled': True,
                    'steps': [20, 60, 100],
                    'canary_count': 1,
                    'auto_advance': True,
                },
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert create.status_code == 200, create.text
        payload = create.json()
        bundle = payload['bundle']
        assert bundle['progressive_exposure_policy']['enabled'] is True
        assert payload['summary']['wave_count'] == 3
        assert bundle['wave_plan'][0]['canary'] is True
        assert bundle['wave_plan'][0]['planned_target_count'] == 1
        assert bundle['wave_plan'][1]['planned_target_count'] == 3
        assert bundle['wave_plan'][2]['planned_target_count'] == 5

        analytics = client.get(
            f"/admin/openclaw/alert-governance/bundles/{payload['bundle_id']}/analytics?tenant_id=tenant-a&workspace_id=ws-a&environment=prod",
            headers=headers,
        )
        assert analytics.status_code == 200, analytics.text
        analytics_payload = analytics.json()
        assert analytics_payload['analytics']['current_exposure_ratio'] == 0.0
        curve = analytics_payload['analytics']['wave_exposure_curve']
        assert [item['planned_target_count'] for item in curve] == [1, 3, 5]
        assert curve[0]['canary'] is True
        assert analytics_payload['analytics']['progressive_exposure_policy']['enabled'] is True


def test_promotion_slo_gates_can_halt_wave_and_trigger_rollback(tmp_path: Path, monkeypatch) -> None:
    _set_now(monkeypatch, 1_781_000_000.0)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        canary_runtime = _create_runtime(
            client,
            headers,
            name='runtime-canary-slo',
            signal_overrides={'critical_alerts': 2, 'warn_alerts': 0, 'total_alerts': 2},
        )
        broad_runtime = _create_runtime(client, headers, name='runtime-broad-slo')
        create = client.post(
            '/admin/openclaw/alert-governance/bundles',
            headers=headers,
            json={
                'actor': 'release-admin',
                'name': 'incident-governance-slo',
                'version': '2026.03.29.slo',
                'runtime_ids': [canary_runtime, broad_runtime],
                'candidate_policy': _candidate_policy(),
                'waves': [
                    {'label': 'Canary', 'runtime_ids': [canary_runtime], 'canary': True},
                    {'label': 'Broad', 'runtime_ids': [broad_runtime]},
                ],
                'wave_gates': {
                    'enabled': True,
                    'auto_halt_on_failure': True,
                    'auto_rollback_on_failure': False,
                    'max_critical_alerts': 10,
                    'max_warn_alerts': 10,
                    'max_total_alerts': 10,
                    'max_stale_runtimes': 10,
                },
                'promotion_slo_policy': {
                    'enabled': True,
                    'min_success_ratio': 1.0,
                    'max_error_ratio': 0.0,
                    'max_pending_approval_ratio': 0.0,
                    'max_critical_alerts_per_runtime': 0.0,
                    'auto_halt_on_failure': True,
                    'auto_rollback_on_failure': True,
                },
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert create.status_code == 200, create.text
        bundle_id = create.json()['bundle_id']
        _approve_bundle(client, headers, bundle_id=bundle_id)

        run_wave = client.post(
            f'/admin/openclaw/alert-governance/bundles/{bundle_id}/waves/1/run',
            headers=headers,
            json={'actor': 'release-bot', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert run_wave.status_code == 200, run_wave.text
        payload = run_wave.json()
        assert payload['wave_execution']['promotion_slo_evaluation']['status'] == 'failed'
        assert payload['wave_execution']['rollback']['count'] == 1
        assert payload['summary']['halted'] is True
        assert payload['summary']['rollout_status'] == 'halted'
        assert payload['summary']['slo_failed_wave_count'] == 1

        detail = client.get(
            f'/admin/openclaw/alert-governance/bundles/{bundle_id}?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert detail.status_code == 200, detail.text
        detail_payload = detail.json()
        assert detail_payload['bundle']['halt_state']['active'] is True
        assert detail_payload['bundle']['halt_state']['trigger'] == 'wave_promotion_slo_failure'
        assert detail_payload['analytics']['rollout_health']['slo_failed_wave_count'] == 1
        assert detail_payload['analytics']['wave_exposure_curve'][0]['slo_status'] == 'failed'
