from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import app as app_module
from openmiura.gateway import Gateway
import openmiura.application.jobs.service as job_service_mod
import openmiura.application.openclaw.scheduler as scheduler_mod
import openmiura.application.openclaw.service as openclaw_service_mod


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


def _create_submitted_portfolio(client: TestClient, headers: dict[str, str], *, base_now: float, runtime_id: str, with_canvas_policy: bool = False) -> str:
    bundle_id = _create_and_approve_bundle(client, headers, name='bundle-attestation', runtime_ids=[runtime_id])
    payload = {
        'actor': 'portfolio-admin',
        'name': 'portfolio-attestation',
        'version': '2026.03.29.portfolio.attestation',
        'bundle_ids': [bundle_id],
        'base_release_at': base_now + 10,
        'drift_policy': {
            'enabled': True,
            'block_on_schedule_change': True,
            'block_on_target_change': True,
            'block_on_status_downgrade': True,
        },
        'tenant_id': 'tenant-a',
        'workspace_id': 'ws-a',
        'environment': 'prod',
    }
    if with_canvas_policy:
        payload['approval_policy'] = {
            'mode': 'sequential',
            'layers': [
                {'layer_id': 'security', 'requested_role': 'security', 'label': 'Security approval'},
            ],
        }
    create = client.post('/admin/openclaw/alert-governance/portfolios', headers=headers, json=payload)
    assert create.status_code == 200, create.text
    portfolio_id = create.json()['portfolio_id']
    submit = client.post(
        f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/submit',
        headers=headers,
        json={'actor': 'portfolio-admin', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
    )
    assert submit.status_code == 200, submit.text
    return portfolio_id


def _tamper_portfolio_calendar(app, *, portfolio_id: str, delta_s: float) -> None:
    gw = app.state.gw
    release = gw.audit.get_release_bundle(portfolio_id, tenant_id='tenant-a', workspace_id='ws-a', environment='prod')
    assert release is not None
    metadata = dict(release.get('metadata') or {})
    portfolio = dict(metadata.get('portfolio') or {})
    calendar = [dict(item) for item in list(portfolio.get('train_calendar') or [])]
    assert calendar
    calendar[0]['planned_at'] = float(calendar[0].get('planned_at') or 0.0) + float(delta_s)
    portfolio['train_calendar'] = calendar
    metadata['portfolio'] = portfolio
    gw.audit.update_release_bundle(
        portfolio_id,
        metadata=metadata,
        tenant_id='tenant-a',
        workspace_id='ws-a',
        environment='prod',
    )


def test_portfolio_approval_creates_execution_attestation_and_drift_is_aligned(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_784_600_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        runtime_id = _create_runtime(client, headers, name='runtime-attestation-1')
        portfolio_id = _create_submitted_portfolio(client, headers, base_now=base_now, runtime_id=runtime_id)

        approve = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/approve',
            headers=headers,
            json={'actor': 'security-admin', 'reason': 'approve release train', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert approve.status_code == 200, approve.text
        payload = approve.json()
        assert payload['release']['status'] == 'approved'
        assert payload['attestation']['kind'] == 'portfolio_execution_plan'
        assert payload['attestation']['schedule_hash']
        assert payload['summary']['attested'] is True

        attest = client.get(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/attestations?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert attest.status_code == 200, attest.text
        attest_payload = attest.json()
        assert attest_payload['attestations']['summary']['attested'] is True
        assert attest_payload['attestations']['summary']['count'] == 1

        drift = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/drift-detect',
            headers=headers,
            json={'actor': 'drift-bot', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert drift.status_code == 200, drift.text
        drift_payload = drift.json()
        assert drift_payload['drift']['overall_status'] == 'aligned'
        assert drift_payload['drift']['block_execution'] is False
        assert drift_payload['drift']['summary']['count'] == 0


def test_portfolio_drift_detection_blocks_due_release_train_job_after_calendar_tamper(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_784_610_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        runtime_id = _create_runtime(client, headers, name='runtime-attestation-2')
        portfolio_id = _create_submitted_portfolio(client, headers, base_now=base_now, runtime_id=runtime_id)

        approve = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/approve',
            headers=headers,
            json={'actor': 'security-admin', 'reason': 'approve release train', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert approve.status_code == 200, approve.text
        assert approve.json()['summary']['job_count'] == 1

        _tamper_portfolio_calendar(app, portfolio_id=portfolio_id, delta_s=300.0)

        drift = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/drift-detect',
            headers=headers,
            json={'actor': 'drift-bot', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert drift.status_code == 200, drift.text
        drift_payload = drift.json()
        assert drift_payload['drift']['overall_status'] == 'blocking_drift'
        assert drift_payload['drift']['summary']['blocking_count'] >= 1
        assert any(item['code'] == 'schedule_changed' for item in drift_payload['drift']['drifts'])

        _set_now(monkeypatch, base_now + 11)
        run_due = client.post(
            '/admin/openclaw/alert-governance/release-train-jobs/run-due',
            headers=headers,
            json={'actor': 'train-bot', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert run_due.status_code == 200, run_due.text
        run_payload = run_due.json()
        assert run_payload['summary']['executed'] == 1
        assert run_payload['items'][0]['ok'] is False
        assert run_payload['items'][0]['error'] == 'portfolio_execution_drift_detected'

        detail = client.get(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert detail.status_code == 200, detail.text
        detail_payload = detail.json()
        assert detail_payload['summary']['drift_status'] == 'blocking_drift'
        assert detail_payload['calendar']['items'][0]['status'] == 'drift_blocked'


def test_canvas_runtime_node_exposes_portfolio_drift_action_and_summary(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_784_620_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        runtime_id = _create_runtime(client, headers, name='runtime-attestation-canvas')
        portfolio_id = _create_submitted_portfolio(client, headers, base_now=base_now, runtime_id=runtime_id)
        approve = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/approve',
            headers=headers,
            json={'actor': 'security-admin', 'reason': 'approve release train', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert approve.status_code == 200, approve.text
        _tamper_portfolio_calendar(app, portfolio_id=portfolio_id, delta_s=180.0)

        canvas = client.post(
            '/admin/canvas/documents',
            headers=headers,
            json={'actor': 'admin', 'title': 'Portfolio drift canvas', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert canvas.status_code == 200, canvas.text
        canvas_id = canvas.json()['document']['canvas_id']
        node = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes',
            headers=headers,
            json={
                'actor': 'admin',
                'node_type': 'runtime',
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
        inspector_payload = inspector.json()
        assert 'detect_portfolio_drift' in inspector_payload['available_actions']

        detect = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/detect_portfolio_drift?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'canvas-admin', 'payload': {'portfolio_id': portfolio_id, 'persist_metadata': True}, 'session_id': 'canvas-admin'},
        )
        assert detect.status_code == 200, detect.text
        detect_payload = detect.json()
        assert detect_payload['result']['drift']['overall_status'] == 'blocking_drift'

        board = client.get(
            f'/admin/canvas/documents/{canvas_id}/views/runtime-board?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert board.status_code == 200, board.text
        board_payload = board.json()
        assert board_payload['summary']['runtime_count'] == 1
        assert board_payload['items'][0]['summary']['governance_portfolio_attested_count'] >= 1
        assert board_payload['items'][0]['summary']['governance_portfolio_drifted_count'] >= 1
        assert board_payload['items'][0]['summary']['governance_portfolio_blocking_drift_count'] >= 1
