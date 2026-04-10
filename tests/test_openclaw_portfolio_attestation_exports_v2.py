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


def _create_submitted_portfolio(client: TestClient, headers: dict[str, str], *, base_now: float, runtime_id: str, approval_policy: dict[str, object] | None = None, export_policy: dict[str, object] | None = None) -> str:
    bundle_id = _create_and_approve_bundle(client, headers, name='bundle-export', runtime_ids=[runtime_id])
    payload = {
        'actor': 'portfolio-admin',
        'name': 'portfolio-export',
        'version': '2026.03.29.portfolio.export',
        'bundle_ids': [bundle_id],
        'base_release_at': base_now + 10,
        'drift_policy': {
            'enabled': True,
            'block_on_schedule_change': True,
            'block_on_target_change': True,
            'block_on_status_downgrade': True,
        },
        'export_policy': export_policy or {
            'enabled': True,
            'require_signature': True,
            'signer_key_id': 'portfolio-export-ci',
            'timeline_limit': 120,
        },
        'tenant_id': 'tenant-a',
        'workspace_id': 'ws-a',
        'environment': 'prod',
    }
    if approval_policy is not None:
        payload['approval_policy'] = approval_policy
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


def test_portfolio_attestation_export_returns_signed_evidence(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_784_700_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        runtime_id = _create_runtime(client, headers, name='runtime-export-attestation')
        portfolio_id = _create_submitted_portfolio(client, headers, base_now=base_now, runtime_id=runtime_id)
        approve = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/approve',
            headers=headers,
            json={'actor': 'security-admin', 'reason': 'approve and attest', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert approve.status_code == 200, approve.text
        attestation_id = approve.json()['attestation']['attestation_id']

        export = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/attestation-export',
            headers=headers,
            json={'actor': 'auditor', 'attestation_id': attestation_id, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert export.status_code == 200, export.text
        payload = export.json()
        assert payload['attestation_id'] == attestation_id
        assert payload['report']['report_type'] == 'openmiura_portfolio_attestation_export_v1'
        assert payload['report']['attestation']['attestation_id'] == attestation_id
        assert payload['integrity']['signed'] is True
        assert payload['integrity']['signature']
        assert payload['integrity']['signer_key_id'] == 'portfolio-export-ci'
        assert payload['integrity']['payload_hash']


def test_portfolio_postmortem_export_contains_signed_replay_evidence(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_784_710_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        runtime_id = _create_runtime(client, headers, name='runtime-export-postmortem')
        portfolio_id = _create_submitted_portfolio(client, headers, base_now=base_now, runtime_id=runtime_id)
        approve = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/approve',
            headers=headers,
            json={'actor': 'security-admin', 'reason': 'approve for execution', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert approve.status_code == 200, approve.text
        attestation_id = approve.json()['attestation']['attestation_id']

        _set_now(monkeypatch, base_now + 11)
        run_due = client.post(
            '/admin/openclaw/alert-governance/release-train-jobs/run-due',
            headers=headers,
            json={'actor': 'train-bot', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert run_due.status_code == 200, run_due.text
        assert run_due.json()['summary']['executed'] == 1

        postmortem = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/postmortem-export',
            headers=headers,
            json={'actor': 'postmortem-bot', 'attestation_id': attestation_id, 'timeline_limit': 120, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert postmortem.status_code == 200, postmortem.text
        payload = postmortem.json()
        assert payload['report']['report_type'] == 'openmiura_portfolio_postmortem_v1'
        assert payload['integrity']['signed'] is True
        assert payload['report']['execution_compare']['summary']['count'] == 1
        assert payload['report']['execution_compare']['summary']['completed_count'] == 1
        assert payload['report']['summary']['completed_count'] == 1
        assert payload['report']['replay']['summary']['count'] > 0
        labels = {item['label'] for item in payload['report']['replay']['items']}
        assert 'execution_attested' in labels
        assert labels & {'portfolio_event_executed', 'openclaw_alert_governance_bundle_wave_run'}


def test_canvas_runtime_node_exposes_portfolio_export_actions(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_784_720_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        runtime_id = _create_runtime(client, headers, name='runtime-canvas-export')
        portfolio_id = _create_submitted_portfolio(
            client,
            headers,
            base_now=base_now,
            runtime_id=runtime_id,
            approval_policy={
                'mode': 'sequential',
                'layers': [
                    {'layer_id': 'security', 'requested_role': 'security', 'label': 'Security approval'},
                ],
            },
        )

        request_approval = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/approve',
            headers=headers,
            json={'actor': 'portfolio-admin', 'reason': 'request approval', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert request_approval.status_code == 200, request_approval.text
        assert request_approval.json()['release']['status'] == 'pending_approval'

        approvals = client.get(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/approvals?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert approvals.status_code == 200, approvals.text
        approval_id = approvals.json()['items'][0]['approval_id']
        approve_canvas_seed = client.post(
            f'/admin/openclaw/alert-governance/portfolio-approvals/{approval_id}/actions/approve',
            headers=headers,
            json={'actor': 'security-admin', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert approve_canvas_seed.status_code == 200, approve_canvas_seed.text
        attestation_id = approve_canvas_seed.json()['attestation']['attestation_id']

        canvas = client.post(
            '/admin/canvas/documents',
            headers=headers,
            json={'actor': 'admin', 'title': 'Portfolio export canvas', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
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
        assert 'export_portfolio_attestation' in inspector_payload['available_actions']
        assert 'export_portfolio_postmortem' in inspector_payload['available_actions']

        export = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/export_portfolio_attestation?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'admin', 'payload': {'portfolio_id': portfolio_id, 'attestation_id': attestation_id}, 'session_id': 'canvas-admin'},
        )
        assert export.status_code == 200, export.text
        result = export.json()['result']
        assert result['report']['report_type'] == 'openmiura_portfolio_attestation_export_v1'
        assert result['integrity']['signed'] is True
