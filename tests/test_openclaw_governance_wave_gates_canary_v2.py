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


def _base_metadata(*, signal_override: dict[str, object] | None = None) -> dict[str, object]:
    metadata: dict[str, object] = {
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
    if signal_override:
        metadata['governance_release_signals'] = dict(signal_override)
    return metadata


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


def _create_runtime(client: TestClient, headers: dict[str, str], *, name: str, signal_override: dict[str, object] | None = None) -> str:
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
            'metadata': _base_metadata(signal_override=signal_override),
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


def test_canary_wave_gate_failure_halts_bundle_and_rolls_back(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        canary_runtime = _create_runtime(
            client,
            headers,
            name='runtime-canary-fail',
            signal_override={'gate_state': 'fail', 'reasons': ['synthetic canary regression']},
        )
        normal_runtime = _create_runtime(client, headers, name='runtime-next-wave')

        bundle_id = _create_and_approve_bundle(
            client,
            headers,
            {
                'actor': 'admin',
                'name': 'incident-governance-canary-fail',
                'version': '2026.03.29.canary-fail',
                'runtime_ids': [canary_runtime, normal_runtime],
                'candidate_policy': _candidate_policy(),
                'waves': [
                    {'label': 'Canary', 'runtime_ids': [canary_runtime], 'canary': True},
                    {'label': 'Broad rollout', 'runtime_ids': [normal_runtime]},
                ],
                'wave_gates': {
                    'enabled': True,
                    'auto_halt_on_failure': True,
                    'auto_rollback_on_failure': True,
                    'max_runtime_errors': 0,
                    'max_critical_alerts': 0,
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
        payload = run_wave_1.json()
        assert payload['summary']['rollout_status'] == 'halted'
        assert payload['summary']['halted'] is True
        assert payload['summary']['halted_wave_no'] == 1
        assert payload['summary']['rollback_executed'] is True
        assert payload['wave_execution']['gate_evaluation']['status'] == 'failed'
        assert payload['wave_execution']['rollback']['count'] == 1
        assert payload['bundle']['wave_plan'][0]['status'] == 'canary_failed'

        runtime_detail = client.get(
            f'/admin/openclaw/runtimes/{canary_runtime}?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert runtime_detail.status_code == 200, runtime_detail.text
        assert runtime_detail.json()['runtime_summary']['alert_governance_policy']['quiet_hours']['enabled'] is False

        blocked = client.post(
            f'/admin/openclaw/alert-governance/bundles/{bundle_id}/waves/2/run',
            headers=headers,
            json={'actor': 'release-admin', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert blocked.status_code == 200, blocked.text
        assert blocked.json()['ok'] is False
        assert blocked.json()['error'] == 'bundle_halted'


def test_canary_wave_pass_allows_following_wave(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        canary_runtime = _create_runtime(client, headers, name='runtime-canary-pass')
        normal_runtime = _create_runtime(client, headers, name='runtime-broad-pass')

        bundle_id = _create_and_approve_bundle(
            client,
            headers,
            {
                'actor': 'admin',
                'name': 'incident-governance-canary-pass',
                'version': '2026.03.29.canary-pass',
                'runtime_ids': [canary_runtime, normal_runtime],
                'candidate_policy': _candidate_policy(),
                'waves': [
                    {'label': 'Canary', 'runtime_ids': [canary_runtime], 'canary': True},
                    {'label': 'Broad rollout', 'runtime_ids': [normal_runtime]},
                ],
                'wave_gates': {
                    'enabled': True,
                    'auto_halt_on_failure': True,
                    'auto_rollback_on_failure': True,
                    'max_stale_runtimes': 1,
                    'max_critical_alerts': 1,
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
        assert payload_1['wave_execution']['gate_evaluation']['status'] in {'passed', 'warning'}
        assert payload_1['bundle']['wave_plan'][0]['status'] in {'canary_passed', 'completed'}
        assert payload_1['summary']['halted'] is False
        assert payload_1['summary']['next_wave_no'] == 2

        run_wave_2 = client.post(
            f'/admin/openclaw/alert-governance/bundles/{bundle_id}/waves/2/run',
            headers=headers,
            json={'actor': 'release-admin', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert run_wave_2.status_code == 200, run_wave_2.text
        payload_2 = run_wave_2.json()
        assert payload_2['summary']['rollout_status'] == 'completed'
        assert payload_2['summary']['completed_wave_count'] == 1 or payload_2['summary']['completed_wave_count'] == 2
        assert payload_2['summary']['active_runtime_count'] >= 2
