from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import app as app_module
from openmiura.gateway import Gateway
from tests.test_openclaw_canvas_v2_async_runtime_board import _write_config as _write_canvas_config
from tests.test_openclaw_portfolio_environment_tiered_governance_v2 import _create_runtime_for_environment
from tests.test_openclaw_portfolio_evidence_packaging_v2 import _set_now, _write_config
from tests.test_openclaw_portfolio_environment_tiered_governance_v2 import _create_and_approve_bundle_for_environment


def _create_submitted_portfolio(
    client: TestClient,
    headers: dict[str, str],
    *,
    base_now: float,
    runtime_id: str,
    environment: str,
    environment_tier_policies: dict[str, object],
) -> str:
    bundle_id = _create_and_approve_bundle_for_environment(
        client,
        headers,
        name=f'bundle-env-envelope-{environment}-{int(base_now)}',
        runtime_ids=[runtime_id],
        environment=environment,
    )
    create = client.post(
        '/admin/openclaw/alert-governance/portfolios',
        headers=headers,
        json={
            'actor': 'portfolio-admin',
            'name': f'portfolio-env-envelope-{environment}-{int(base_now)}',
            'version': f'2026.03.31.{environment}.{int(base_now)}',
            'bundle_ids': [bundle_id],
            'base_release_at': base_now + 10,
            'export_policy': {'enabled': True, 'require_signature': True, 'timeline_limit': 120},
            'retention_policy': {'enabled': True, 'retention_days': 30, 'max_packages': 5},
            'environment_tier_policies': environment_tier_policies,
            'tenant_id': 'tenant-a',
            'workspace_id': 'ws-a',
            'environment': environment,
        },
    )
    assert create.status_code == 200, create.text
    portfolio_id = create.json()['portfolio_id']
    submit = client.post(
        f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/submit',
        headers=headers,
        json={'actor': 'portfolio-admin', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': environment},
    )
    assert submit.status_code == 200, submit.text
    return portfolio_id


def _approve_all_portfolio_approvals(client: TestClient, headers: dict[str, str], *, portfolio_id: str, environment: str) -> None:
    approvals = client.get(
        f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/approvals?tenant_id=tenant-a&workspace_id=ws-a&environment={environment}',
        headers=headers,
    )
    assert approvals.status_code == 200, approvals.text
    items = [dict(item) for item in approvals.json()['items'] if item.get('status') == 'pending']
    for item in items:
        decide = client.post(
            f"/admin/openclaw/alert-governance/portfolio-approvals/{item['approval_id']}/actions/approve",
            headers=headers,
            json={'actor': str((item.get('payload') or {}).get('requested_role') or 'approver'), 'reason': 'approve env envelope', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': environment},
        )
        assert decide.status_code == 200, decide.text


def test_environment_specific_approval_and_security_envelopes_report_conformant_for_prod(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_603_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    prod_lock_dir = (tmp_path / 'prod-object-lock').resolve()
    env_policies = {
        'dev': {
            'operational_tier': 'dev',
            'evidence_classification': 'internal-dev-evidence',
        },
        'prod': {
            'operational_tier': 'prod',
            'evidence_classification': 'regulated-enterprise-evidence',
            'approval_policy': {
                'mode': 'parallel',
                'layers': [
                    {'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'},
                    {'layer_id': 'security', 'requested_role': 'security-chief', 'label': 'Security chief'},
                ],
            },
            'security_gate_policy': {
                'enabled': True,
                'envelope_label': 'prod-enterprise-envelope',
                'require_provider_validation': True,
                'require_immutable_escrow': True,
                'min_approval_layers': 2,
                'required_approval_roles': ['ops-director', 'security-chief'],
            },
            'escrow_policy': {
                'enabled': True,
                'provider': 'filesystem-object-lock',
                'root_dir': str(prod_lock_dir),
                'require_archive_on_export': True,
                'allow_inline_fallback': False,
                'object_lock_enabled': True,
            },
            'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'prod-signer'},
        },
    }

    with TestClient(app) as client:
        runtime_id = _create_runtime_for_environment(client, headers, name='runtime-prod-envelope', environment='prod')
        portfolio_id = _create_submitted_portfolio(
            client,
            headers,
            base_now=base_now,
            runtime_id=runtime_id,
            environment='prod',
            environment_tier_policies=env_policies,
        )

        request_approval = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/approve',
            headers=headers,
            json={'actor': 'portfolio-admin', 'reason': 'request prod approval', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert request_approval.status_code == 200, request_approval.text
        request_payload = request_approval.json()
        assert request_payload['release']['status'] == 'pending_approval'
        assert request_payload['approval_summary']['pending_count'] == 2

        _approve_all_portfolio_approvals(client, headers, portfolio_id=portfolio_id, environment='prod')

        validation = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/provider-validation',
            headers=headers,
            json={'actor': 'ops-admin', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert validation.status_code == 200, validation.text
        validation_payload = validation.json()['provider_validation']
        assert validation_payload['valid'] is True
        assert validation_payload['escrow']['provider'] == 'filesystem-object-lock'

        conformance = client.get(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/policy-conformance?tenant_id=tenant-a&workspace_id=ws-a&environment=prod&actor=auditor',
            headers=headers,
        )
        assert conformance.status_code == 200, conformance.text
        conformance_payload = conformance.json()['policy_conformance']
        assert conformance_payload['overall_status'] == 'conformant'
        assert conformance_payload['approval_envelope']['layer_count'] == 2
        assert conformance_payload['security_envelope']['required_provider_validation'] is True
        assert conformance_payload['security_envelope']['required_immutable_escrow'] is True
        assert conformance_payload['summary']['fail_count'] == 0


def test_security_envelope_blocks_sensitive_export_when_prod_policy_is_nonconformant(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_604_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    prod_lock_dir = (tmp_path / 'prod-export-block').resolve()
    env_policies = {
        'prod': {
            'operational_tier': 'prod',
            'evidence_classification': 'regulated-enterprise-evidence',
            'approval_policy': {
                'mode': 'parallel',
                'layers': [
                    {'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'},
                ],
            },
            'security_gate_policy': {
                'enabled': True,
                'envelope_label': 'prod-export-gated',
                'require_provider_validation': True,
                'require_immutable_escrow': True,
                'min_approval_layers': 1,
                'required_approval_roles': ['ops-director'],
                'block_on_nonconformance': True,
                'enforce_before_sensitive_export': True,
            },
            'escrow_policy': {
                'enabled': True,
                'provider': 'filesystem-object-lock',
                'root_dir': str(prod_lock_dir),
                'require_archive_on_export': True,
                'allow_inline_fallback': False,
                'object_lock_enabled': True,
            },
            'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'prod-signer'},
        },
    }

    with TestClient(app) as client:
        runtime_id = _create_runtime_for_environment(client, headers, name='runtime-prod-export-gate', environment='prod')
        portfolio_id = _create_submitted_portfolio(
            client,
            headers,
            base_now=base_now,
            runtime_id=runtime_id,
            environment='prod',
            environment_tier_policies=env_policies,
        )
        request_approval = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/approve',
            headers=headers,
            json={'actor': 'portfolio-admin', 'reason': 'request prod approval', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert request_approval.status_code == 200, request_approval.text
        _approve_all_portfolio_approvals(client, headers, portfolio_id=portfolio_id, environment='prod')

        blocked_export = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-package-export',
            headers=headers,
            json={'actor': 'auditor', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert blocked_export.status_code == 200, blocked_export.text
        blocked_payload = blocked_export.json()
        assert blocked_payload['ok'] is False
        assert blocked_payload['error'] == 'portfolio_security_envelope_failed'
        assert blocked_payload['policy_conformance']['overall_status'] == 'nonconformant'

        conformance = client.get(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/policy-conformance?tenant_id=tenant-a&workspace_id=ws-a&environment=prod&actor=auditor',
            headers=headers,
        )
        assert conformance.status_code == 200, conformance.text
        assert conformance.json()['policy_conformance']['overall_status'] == 'nonconformant'



def test_canvas_runtime_board_surfaces_policy_conformance_counts_and_action(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_605_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_canvas_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    conformant_dir = (tmp_path / 'conformant-lock').resolve()
    nonconformant_dir = (tmp_path / 'nonconformant-lock').resolve()
    with TestClient(app) as client:
        canvas = client.post(
            '/admin/canvas/documents',
            headers=headers,
            json={'actor': 'admin', 'title': 'Policy conformance canvas', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert canvas.status_code == 200, canvas.text
        canvas_id = canvas.json()['document']['canvas_id']

        runtime_id = _create_runtime_for_environment(client, headers, name='runtime-canvas-conformance', environment='prod')
        node = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes',
            headers=headers,
            json={
                'actor': 'admin',
                'node_type': 'openclaw_runtime',
                'label': 'Runtime conformance node',
                'data': {'runtime_id': runtime_id, 'agent_id': 'default'},
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert node.status_code == 200, node.text
        node_id = node.json()['node']['node_id']

        conformant_policy = {
            'prod': {
                'operational_tier': 'prod',
                'evidence_classification': 'regulated-enterprise-evidence',
                'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'}]},
                'security_gate_policy': {'enabled': True, 'require_provider_validation': True, 'require_immutable_escrow': True, 'min_approval_layers': 1, 'required_approval_roles': ['ops-director']},
                'escrow_policy': {'enabled': True, 'provider': 'filesystem-object-lock', 'root_dir': str(conformant_dir), 'require_archive_on_export': True, 'allow_inline_fallback': False, 'object_lock_enabled': True},
                'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'prod-signer-a'},
            },
        }
        nonconformant_policy = {
            'prod': {
                'operational_tier': 'prod',
                'evidence_classification': 'regulated-enterprise-evidence',
                'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'}]},
                'security_gate_policy': {'enabled': True, 'require_provider_validation': True, 'require_immutable_escrow': True, 'min_approval_layers': 1, 'required_approval_roles': ['ops-director']},
                'escrow_policy': {'enabled': True, 'provider': 'filesystem-object-lock', 'root_dir': str(nonconformant_dir), 'require_archive_on_export': True, 'allow_inline_fallback': False, 'object_lock_enabled': True},
                'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'prod-signer-b'},
            },
        }

        conformant_portfolio_id = _create_submitted_portfolio(client, headers, base_now=base_now, runtime_id=runtime_id, environment='prod', environment_tier_policies=conformant_policy)
        client.post(
            f'/admin/openclaw/alert-governance/portfolios/{conformant_portfolio_id}/approve',
            headers=headers,
            json={'actor': 'portfolio-admin', 'reason': 'request prod approval', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        _approve_all_portfolio_approvals(client, headers, portfolio_id=conformant_portfolio_id, environment='prod')
        client.post(
            f'/admin/openclaw/alert-governance/portfolios/{conformant_portfolio_id}/provider-validation',
            headers=headers,
            json={'actor': 'ops-admin', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )

        nonconformant_portfolio_id = _create_submitted_portfolio(client, headers, base_now=base_now + 100, runtime_id=runtime_id, environment='prod', environment_tier_policies=nonconformant_policy)
        client.post(
            f'/admin/openclaw/alert-governance/portfolios/{nonconformant_portfolio_id}/approve',
            headers=headers,
            json={'actor': 'portfolio-admin', 'reason': 'request prod approval', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        _approve_all_portfolio_approvals(client, headers, portfolio_id=nonconformant_portfolio_id, environment='prod')

        board = client.get(
            f'/admin/canvas/documents/{canvas_id}/views/runtime-board?tenant_id=tenant-a&workspace_id=ws-a&environment=prod&limit=10',
            headers=headers,
        )
        assert board.status_code == 200, board.text
        summary = board.json()['items'][0]['summary']
        assert summary['governance_portfolio_policy_conformance_status_counts']['conformant'] >= 1
        assert summary['governance_portfolio_policy_conformance_status_counts']['nonconformant'] >= 1

        action = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/report_portfolio_policy_conformance?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'admin', 'portfolio_id': nonconformant_portfolio_id, 'persist_metadata': True},
        )
        assert action.status_code == 200, action.text
        action_payload = action.json()['result']
        assert action_payload['ok'] is True
        assert action_payload['policy_conformance']['overall_status'] == 'nonconformant'
