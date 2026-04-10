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


def _base_metadata(*, approval_required: bool) -> dict[str, object]:
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
            'approval_required': approval_required,
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


def _create_runtime(client: TestClient, headers: dict[str, str], *, name: str, approval_required: bool) -> str:
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
            'metadata': _base_metadata(approval_required=approval_required),
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()['runtime']['runtime_id']


def test_governance_release_bundle_rolls_out_in_waves(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        r1 = _create_runtime(client, headers, name='runtime-wave-1', approval_required=False)
        r2 = _create_runtime(client, headers, name='runtime-wave-2', approval_required=False)
        r3 = _create_runtime(client, headers, name='runtime-wave-3', approval_required=False)

        create = client.post(
            '/admin/openclaw/alert-governance/bundles',
            headers=headers,
            json={
                'actor': 'admin',
                'name': 'incident-governance-wave',
                'version': '2026.03.29.1',
                'runtime_ids': [r1, r2, r3],
                'candidate_policy': _candidate_policy(),
                'waves': [
                    {'label': 'Wave 1', 'runtime_ids': [r1, r2]},
                    {'label': 'Wave 2', 'runtime_ids': [r3]},
                ],
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert create.status_code == 200, create.text
        created = create.json()
        bundle_id = created['bundle_id']
        assert created['summary']['target_count'] == 3
        assert created['summary']['wave_count'] == 2
        assert created['release']['status'] == 'draft'

        submit = client.post(
            f'/admin/openclaw/alert-governance/bundles/{bundle_id}/submit',
            headers=headers,
            json={'actor': 'admin', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert submit.status_code == 200, submit.text
        assert submit.json()['release']['status'] == 'candidate'

        approve = client.post(
            f'/admin/openclaw/alert-governance/bundles/{bundle_id}/approve',
            headers=headers,
            json={'actor': 'security-admin', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert approve.status_code == 200, approve.text
        assert approve.json()['release']['status'] == 'approved'

        run_wave_1 = client.post(
            f'/admin/openclaw/alert-governance/bundles/{bundle_id}/waves/1/run',
            headers=headers,
            json={'actor': 'release-admin', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert run_wave_1.status_code == 200, run_wave_1.text
        wave_1 = run_wave_1.json()
        assert wave_1['wave_execution']['errors'] == 0
        assert wave_1['summary']['active_runtime_count'] == 2
        assert wave_1['summary']['next_wave_no'] == 2
        wave_1_status = {item['runtime_id']: item['status'] for item in wave_1['targets']}
        assert wave_1_status[r1] == 'active'
        assert wave_1_status[r2] == 'active'
        assert wave_1_status[r3] == 'not_started'

        runtime_1 = client.get(
            f'/admin/openclaw/runtimes/{r1}?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert runtime_1.status_code == 200, runtime_1.text
        assert runtime_1.json()['runtime_summary']['alert_governance_policy']['quiet_hours']['enabled'] is True

        run_wave_2 = client.post(
            f'/admin/openclaw/alert-governance/bundles/{bundle_id}/waves/2/run',
            headers=headers,
            json={'actor': 'release-admin', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert run_wave_2.status_code == 200, run_wave_2.text
        wave_2 = run_wave_2.json()
        assert wave_2['summary']['rollout_status'] == 'completed'
        assert wave_2['summary']['active_runtime_count'] == 3
        assert wave_2['summary']['completed_wave_count'] == 2

        listing = client.get(
            f'/admin/openclaw/alert-governance/bundles?runtime_id={r3}&tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert listing.status_code == 200, listing.text
        listed = listing.json()
        assert listed['summary']['count'] == 1
        assert listed['items'][0]['bundle_id'] == bundle_id
        assert listed['items'][0]['summary']['rollout_status'] == 'completed'


def test_governance_release_bundle_aggregates_pending_runtime_approvals(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        r1 = _create_runtime(client, headers, name='runtime-bundle-approval-1', approval_required=True)
        r2 = _create_runtime(client, headers, name='runtime-bundle-approval-2', approval_required=True)

        create = client.post(
            '/admin/openclaw/alert-governance/bundles',
            headers=headers,
            json={
                'actor': 'admin',
                'name': 'incident-governance-approval-wave',
                'version': '2026.03.29.2',
                'runtime_ids': [r1, r2],
                'candidate_policy': _candidate_policy(),
                'wave_size': 2,
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert create.status_code == 200, create.text
        bundle_id = create.json()['bundle_id']

        client.post(
            f'/admin/openclaw/alert-governance/bundles/{bundle_id}/submit',
            headers=headers,
            json={'actor': 'admin', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        client.post(
            f'/admin/openclaw/alert-governance/bundles/{bundle_id}/approve',
            headers=headers,
            json={'actor': 'security-admin', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )

        run_wave = client.post(
            f'/admin/openclaw/alert-governance/bundles/{bundle_id}/waves/1/run',
            headers=headers,
            json={'actor': 'release-admin', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert run_wave.status_code == 200, run_wave.text
        payload = run_wave.json()
        assert payload['wave_execution']['pending_approvals'] == 2
        assert payload['summary']['pending_runtime_approval_count'] == 2
        assert payload['summary']['rollout_status'] == 'awaiting_runtime_approvals'

        first_approval_id = next(item['approval_id'] for item in payload['wave_execution']['results'] if item['approval_id'])
        approve_one = client.post(
            f'/admin/openclaw/alert-governance-promotion-approvals/{first_approval_id}/decide',
            headers=headers,
            json={
                'actor': 'security-admin',
                'decision': 'approve',
                'reason': 'approve first runtime from bundle',
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert approve_one.status_code == 200, approve_one.text
        detail = client.get(
            f'/admin/openclaw/alert-governance/bundles/{bundle_id}?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert detail.status_code == 200, detail.text
        updated = detail.json()
        assert updated['summary']['active_runtime_count'] == 1
        assert updated['summary']['pending_runtime_approval_count'] == 1
        assert updated['summary']['rollout_status'] == 'awaiting_runtime_approvals'
