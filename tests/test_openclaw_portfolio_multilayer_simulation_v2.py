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


def test_portfolio_simulation_detects_freeze_dependencies_and_conflicts(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_784_300_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        r1 = _create_runtime(client, headers, name='runtime-shared')
        r2 = _create_runtime(client, headers, name='runtime-dependent')
        b1 = _create_and_approve_bundle(client, headers, name='bundle-primary', runtime_ids=[r1])
        b2 = _create_and_approve_bundle(client, headers, name='bundle-conflict', runtime_ids=[r1])
        b3 = _create_and_approve_bundle(client, headers, name='bundle-dependent', runtime_ids=[r2])

        create = client.post(
            '/admin/openclaw/alert-governance/portfolios',
            headers=headers,
            json={
                'actor': 'portfolio-admin',
                'name': 'portfolio-simulated',
                'version': '2026.03.29.portfolio.sim',
                'bundle_ids': [b1, b2, b3],
                'strict_conflict_check': True,
                'auto_reschedule': False,
                'dependency_graph': [
                    {'bundle_id': b3, 'depends_on': [b1]},
                ],
                'freeze_windows': [
                    {'window_id': 'freeze-1', 'start_at': base_now + 1, 'end_at': base_now + 20, 'reason': 'global freeze', 'bundle_ids': [b3]},
                ],
                'train_calendar': [
                    {'bundle_id': b1, 'wave_no': 1, 'label': 'primary', 'planned_at': base_now + 30, 'window_s': 60},
                    {'bundle_id': b2, 'wave_no': 1, 'label': 'conflict', 'planned_at': base_now + 30, 'window_s': 60},
                    {'bundle_id': b3, 'wave_no': 1, 'label': 'dependent', 'planned_at': base_now + 10, 'window_s': 60},
                ],
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert create.status_code == 200, create.text
        portfolio_id = create.json()['portfolio_id']
        submit = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/submit',
            headers=headers,
            json={'actor': 'portfolio-admin', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert submit.status_code == 200, submit.text

        simulate = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/simulate',
            headers=headers,
            json={'actor': 'portfolio-admin', 'dry_run': True, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert simulate.status_code == 200, simulate.text
        payload = simulate.json()
        assert payload['simulation']['validation_status'] == 'blocked'
        assert payload['simulation']['summary']['blocked_count'] >= 2
        assert payload['simulation']['summary']['freeze_hit_count'] >= 1
        assert payload['simulation']['summary']['dependency_blocked_count'] >= 1
        assert payload['simulation']['summary']['open_conflict_count'] >= 1
        per_event = {item['bundle_id']: item for item in payload['simulation']['items']}
        assert per_event[b1]['simulation_status'] == 'ready'
        assert per_event[b2]['simulation_status'] == 'blocked'
        assert per_event[b3]['simulation_status'] == 'blocked'

        approve = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/approve',
            headers=headers,
            json={'actor': 'portfolio-admin', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert approve.status_code == 200, approve.text
        assert approve.json()['ok'] is False
        assert approve.json()['error'] == 'portfolio_simulation_blocked'



def test_portfolio_multilayer_approval_flow_finalizes_release_train(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_784_400_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        r1 = _create_runtime(client, headers, name='runtime-approval-1')
        bundle_id = _create_and_approve_bundle(client, headers, name='bundle-approval', runtime_ids=[r1])
        create = client.post(
            '/admin/openclaw/alert-governance/portfolios',
            headers=headers,
            json={
                'actor': 'portfolio-admin',
                'name': 'portfolio-multilayer',
                'version': '2026.03.29.portfolio.approvals',
                'bundle_ids': [bundle_id],
                'base_release_at': base_now + 60,
                'approval_policy': {
                    'mode': 'sequential',
                    'layers': [
                        {'layer_id': 'ops', 'requested_role': 'ops_manager', 'label': 'Ops approval'},
                        {'layer_id': 'security', 'requested_role': 'security', 'label': 'Security approval'},
                    ],
                },
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert create.status_code == 200, create.text
        portfolio_id = create.json()['portfolio_id']
        submit = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/submit',
            headers=headers,
            json={'actor': 'portfolio-admin', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert submit.status_code == 200, submit.text

        request_approval = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/approve',
            headers=headers,
            json={'actor': 'portfolio-admin', 'reason': 'request multilayer approval', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert request_approval.status_code == 200, request_approval.text
        request_payload = request_approval.json()
        assert request_payload['release']['status'] == 'pending_approval'
        assert request_payload['approval_summary']['pending_count'] == 1
        assert request_payload['approval_summary']['layers'][0]['layer_id'] == 'ops'

        approvals_1 = client.get(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/approvals?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert approvals_1.status_code == 200, approvals_1.text
        approval_items_1 = approvals_1.json()['items']
        assert len(approval_items_1) == 1
        assert approval_items_1[0]['payload']['layer_id'] == 'ops'

        approve_ops = client.post(
            f"/admin/openclaw/alert-governance/portfolio-approvals/{approval_items_1[0]['approval_id']}/actions/approve",
            headers=headers,
            json={'actor': 'ops-director', 'reason': 'ops approved', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert approve_ops.status_code == 200, approve_ops.text
        ops_payload = approve_ops.json()
        assert ops_payload['release']['status'] == 'pending_approval'
        assert ops_payload['approval_summary']['pending_count'] == 1
        assert ops_payload['approval_summary']['next_layer']['layer_id'] == 'security'

        approvals_2 = client.get(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/approvals?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert approvals_2.status_code == 200, approvals_2.text
        approval_items_2 = approvals_2.json()['items']
        pending_security = next(item for item in approval_items_2 if item['status'] == 'pending')
        assert pending_security['payload']['layer_id'] == 'security'

        approve_security = client.post(
            f"/admin/openclaw/alert-governance/portfolio-approvals/{pending_security['approval_id']}/actions/approve",
            headers=headers,
            json={'actor': 'security-chief', 'reason': 'security approved', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert approve_security.status_code == 200, approve_security.text
        security_payload = approve_security.json()
        assert security_payload['release']['status'] == 'approved'
        assert security_payload['approval_summary']['satisfied'] is True
        assert security_payload['summary']['job_count'] == 1
        assert security_payload['simulation']['validation_status'] in {'ready', 'approvable_with_reschedule'}

        jobs = client.get(
            f'/admin/openclaw/alert-governance/release-train-jobs?portfolio_id={portfolio_id}&tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert jobs.status_code == 200, jobs.text
        assert jobs.json()['summary']['count'] == 1



def test_canvas_runtime_node_exposes_portfolio_simulation_and_approval_actions(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_784_500_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        runtime_id = _create_runtime(client, headers, name='runtime-canvas-portfolio')
        bundle_id = _create_and_approve_bundle(client, headers, name='bundle-canvas-portfolio', runtime_ids=[runtime_id])
        create = client.post(
            '/admin/openclaw/alert-governance/portfolios',
            headers=headers,
            json={
                'actor': 'portfolio-admin',
                'name': 'portfolio-canvas',
                'version': '2026.03.29.portfolio.canvas',
                'bundle_ids': [bundle_id],
                'base_release_at': base_now + 120,
                'approval_policy': {
                    'mode': 'sequential',
                    'layers': [
                        {'layer_id': 'portfolio-security', 'requested_role': 'security', 'label': 'Portfolio security'},
                    ],
                },
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert create.status_code == 200, create.text
        portfolio_id = create.json()['portfolio_id']
        submit = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/submit',
            headers=headers,
            json={'actor': 'portfolio-admin', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert submit.status_code == 200, submit.text

        canvas = client.post(
            '/admin/canvas/documents',
            headers=headers,
            json={'actor': 'admin', 'title': 'Portfolio canvas', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
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
        related_portfolios = inspector_payload['related']['runtime_alert_governance_portfolios']
        assert related_portfolios['items'][0]['portfolio_id'] == portfolio_id
        assert 'simulate_portfolio_calendar' in inspector_payload['available_actions']
        assert 'request_portfolio_approval' in inspector_payload['available_actions']
        assert related_portfolios['items'][0]['simulation']['validation_status'] in {'ready', 'approvable_with_reschedule'}

        simulate = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/simulate_portfolio_calendar?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'admin', 'payload': {'portfolio_id': portfolio_id, 'dry_run': True}, 'session_id': 'canvas-admin'},
        )
        assert simulate.status_code == 200, simulate.text
        assert simulate.json()['result']['simulation']['validation_status'] in {'ready', 'approvable_with_reschedule'}

        request_approval = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/request_portfolio_approval?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'admin', 'payload': {'portfolio_id': portfolio_id}, 'session_id': 'canvas-admin'},
        )
        assert request_approval.status_code == 200, request_approval.text
        assert request_approval.json()['result']['release']['status'] == 'pending_approval'

        approvals = client.get(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/approvals?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert approvals.status_code == 200, approvals.text
        approval_id = approvals.json()['items'][0]['approval_id']

        approve_canvas = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/approve_portfolio_approval?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'security-admin', 'payload': {'portfolio_id': portfolio_id, 'approval_id': approval_id}, 'session_id': 'canvas-admin'},
        )
        assert approve_canvas.status_code == 200, approve_canvas.text
        assert approve_canvas.json()['result']['release']['status'] == 'approved'
