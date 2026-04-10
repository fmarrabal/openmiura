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


def _create_and_approve_bundle(client: TestClient, headers: dict[str, str], *, name: str, runtime_ids: list[str]) -> str:
    create = client.post(
        '/admin/openclaw/alert-governance/bundles',
        headers=headers,
        json={
            'actor': 'release-admin',
            'name': name,
            'version': f'{name}-v1',
            'runtime_ids': runtime_ids,
            'candidate_policy': _candidate_policy(),
            'wave_size': max(1, len(runtime_ids)),
            'tenant_id': 'tenant-a',
            'workspace_id': 'ws-a',
            'environment': 'prod',
        },
    )
    assert create.status_code == 200, create.text
    bundle_id = create.json()['bundle_id']
    submit = client.post(
        f'/admin/openclaw/alert-governance/bundles/{bundle_id}/submit',
        headers=headers,
        json={'actor': 'release-admin', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
    )
    assert submit.status_code == 200, submit.text
    approve = client.post(
        f'/admin/openclaw/alert-governance/bundles/{bundle_id}/approve',
        headers=headers,
        json={'actor': 'security-admin', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
    )
    assert approve.status_code == 200, approve.text
    return bundle_id


def test_governance_portfolio_release_train_runs_bundles_by_calendar(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_784_000_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        r1 = _create_runtime(client, headers, name='runtime-portfolio-1')
        r2 = _create_runtime(client, headers, name='runtime-portfolio-2')
        bundle_1 = _create_and_approve_bundle(client, headers, name='bundle-one', runtime_ids=[r1])
        bundle_2 = _create_and_approve_bundle(client, headers, name='bundle-two', runtime_ids=[r2])

        create = client.post(
            '/admin/openclaw/alert-governance/portfolios',
            headers=headers,
            json={
                'actor': 'portfolio-admin',
                'name': 'portfolio-train',
                'version': '2026.03.29.portfolio',
                'bundle_ids': [bundle_1, bundle_2],
                'train_calendar': [
                    {'bundle_id': bundle_1, 'wave_no': 1, 'label': 'slot-1', 'planned_at': base_now + 10},
                    {'bundle_id': bundle_2, 'wave_no': 1, 'label': 'slot-2', 'planned_at': base_now + 20},
                ],
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert create.status_code == 200, create.text
        portfolio_id = create.json()['portfolio_id']
        assert create.json()['summary']['bundle_count'] == 2
        assert create.json()['calendar']['summary']['count'] == 2

        submit = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/submit',
            headers=headers,
            json={'actor': 'portfolio-admin', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert submit.status_code == 200, submit.text
        approve = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/approve',
            headers=headers,
            json={'actor': 'security-admin', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert approve.status_code == 200, approve.text
        assert approve.json()['summary']['job_count'] == 2

        jobs = client.get(
            '/admin/openclaw/alert-governance/release-train-jobs?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert jobs.status_code == 200, jobs.text
        assert jobs.json()['summary']['count'] == 2

        _set_now(monkeypatch, base_now + 11)
        run_due_1 = client.post(
            '/admin/openclaw/alert-governance/release-train-jobs/run-due',
            headers=headers,
            json={'actor': 'train-bot', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert run_due_1.status_code == 200, run_due_1.text
        assert run_due_1.json()['summary']['executed'] == 1

        detail_1 = client.get(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert detail_1.status_code == 200, detail_1.text
        payload_1 = detail_1.json()
        assert payload_1['summary']['calendar_completed_count'] == 1
        assert payload_1['summary']['rollout_status'] == 'in_progress'
        bundle_states_1 = {item['bundle_id']: (item.get('summary') or {}).get('rollout_status') for item in payload_1['bundles']}
        assert bundle_states_1[bundle_1] == 'completed'
        assert bundle_states_1[bundle_2] in {'approved', 'draft'}

        _set_now(monkeypatch, base_now + 21)
        run_due_2 = client.post(
            '/admin/openclaw/alert-governance/release-train-jobs/run-due',
            headers=headers,
            json={'actor': 'train-bot', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert run_due_2.status_code == 200, run_due_2.text
        assert run_due_2.json()['summary']['executed'] == 1

        detail_2 = client.get(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert detail_2.status_code == 200, detail_2.text
        payload_2 = detail_2.json()
        assert payload_2['summary']['calendar_completed_count'] == 2
        assert payload_2['summary']['rollout_status'] == 'completed'
        assert payload_2['analytics']['calendar_completion_ratio'] == 1.0


def test_governance_portfolio_train_policy_generates_calendar_and_runtime_filter(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_784_100_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        r1 = _create_runtime(client, headers, name='runtime-portfolio-filter')
        bundle_1 = _create_and_approve_bundle(client, headers, name='bundle-filter', runtime_ids=[r1])
        create = client.post(
            '/admin/openclaw/alert-governance/portfolios',
            headers=headers,
            json={
                'actor': 'portfolio-admin',
                'name': 'portfolio-generated-calendar',
                'version': '2026.03.29.portfolio.generated',
                'bundle_ids': [bundle_1],
                'train_policy': {'base_release_at': base_now + 60, 'spacing_s': 300},
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert create.status_code == 200, create.text
        payload = create.json()
        assert payload['calendar']['summary']['count'] == 1
        event = payload['calendar']['items'][0]
        assert event['planned_at'] == base_now + 60
        assert event['bundle_id'] == bundle_1

        listing = client.get(
            f'/admin/openclaw/alert-governance/portfolios?runtime_id={r1}&tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert listing.status_code == 200, listing.text
        assert listing.json()['summary']['count'] == 1
        assert listing.json()['items'][0]['portfolio_id'] == payload['portfolio_id']
