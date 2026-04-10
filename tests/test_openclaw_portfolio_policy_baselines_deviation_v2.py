from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import app as app_module
from openmiura.gateway import Gateway
from tests.test_openclaw_canvas_v2_async_runtime_board import _write_config as _write_canvas_config
from tests.test_openclaw_portfolio_environment_envelopes_conformance_v2 import _approve_all_portfolio_approvals
from tests.test_openclaw_portfolio_environment_tiered_governance_v2 import _create_and_approve_bundle_for_environment, _create_runtime_for_environment
from tests.test_openclaw_portfolio_evidence_packaging_v2 import _set_now, _write_config


def _create_submitted_portfolio_with_baseline(
    client: TestClient,
    headers: dict[str, str],
    *,
    base_now: float,
    runtime_id: str,
    environment: str,
    environment_tier_policies: dict[str, object],
    environment_policy_baselines: dict[str, object],
    deviation_management_policy: dict[str, object] | None = None,
) -> str:
    bundle_id = _create_and_approve_bundle_for_environment(
        client,
        headers,
        name=f'bundle-baseline-{environment}-{int(base_now)}',
        runtime_ids=[runtime_id],
        environment=environment,
    )
    create = client.post(
        '/admin/openclaw/alert-governance/portfolios',
        headers=headers,
        json={
            'actor': 'portfolio-admin',
            'name': f'portfolio-baseline-{environment}-{int(base_now)}',
            'version': f'2026.03.31.{environment}.{int(base_now)}',
            'bundle_ids': [bundle_id],
            'base_release_at': base_now + 10,
            'export_policy': {'enabled': True, 'require_signature': True, 'timeline_limit': 120},
            'environment_tier_policies': environment_tier_policies,
            'environment_policy_baselines': environment_policy_baselines,
            'deviation_management_policy': deviation_management_policy or {'enabled': True, 'require_approval': True, 'requested_role': 'governance-board', 'default_ttl_s': 3600},
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


def _request_and_approve_policy_deviation(
    client: TestClient,
    headers: dict[str, str],
    *,
    portfolio_id: str,
    environment: str,
    ttl_s: int = 3600,
) -> dict:
    drift = client.get(
        f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/policy-baseline-drift?tenant_id=tenant-a&workspace_id=ws-a&environment={environment}&actor=auditor',
        headers=headers,
    )
    assert drift.status_code == 200, drift.text
    drift_payload = drift.json()['policy_baseline_drift']
    deviation_id = drift_payload['items'][0]['deviation_id']
    requested = client.post(
        f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/deviation-exceptions',
        headers=headers,
        json={
            'actor': 'policy-owner',
            'deviation_id': deviation_id,
            'ttl_s': ttl_s,
            'reason': 'approved portfolio-specific exception',
            'tenant_id': 'tenant-a',
            'workspace_id': 'ws-a',
            'environment': environment,
        },
    )
    assert requested.status_code == 200, requested.text
    approval_id = requested.json()['approval']['approval_id']
    decided = client.post(
        f'/admin/openclaw/alert-governance/portfolio-deviation-approvals/{approval_id}/actions/approve',
        headers=headers,
        json={
            'actor': 'governance-board',
            'reason': 'allow deviation',
            'tenant_id': 'tenant-a',
            'workspace_id': 'ws-a',
            'environment': environment,
        },
    )
    assert decided.status_code == 200, decided.text
    return decided.json()



def test_policy_baseline_drift_requires_approved_exception_before_sensitive_export(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_607_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    env_policy = {
        'prod': {
            'operational_tier': 'prod',
            'evidence_classification': 'regulated-enterprise-evidence',
            'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'}]},
            'security_gate_policy': {'enabled': True, 'envelope_label': 'prod-envelope', 'min_approval_layers': 1, 'required_approval_roles': ['ops-director'], 'block_on_nonconformance': True, 'enforce_before_sensitive_export': True},
            'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'prod-signer'},
        },
    }
    env_baseline = {
        'prod': {
            'operational_tier': 'prod',
            'evidence_classification': 'regulated-enterprise-evidence',
            'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'}]},
            'security_gate_policy': {'enabled': True, 'envelope_label': 'prod-envelope', 'min_approval_layers': 1, 'required_approval_roles': ['ops-director'], 'block_on_nonconformance': True, 'enforce_before_sensitive_export': True},
            'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-signer'},
        },
    }

    with TestClient(app) as client:
        runtime_id = _create_runtime_for_environment(client, headers, name='runtime-policy-baseline', environment='prod')
        portfolio_id = _create_submitted_portfolio_with_baseline(
            client,
            headers,
            base_now=base_now,
            runtime_id=runtime_id,
            environment='prod',
            environment_tier_policies=env_policy,
            environment_policy_baselines=env_baseline,
        )
        request_approval = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/approve',
            headers=headers,
            json={'actor': 'portfolio-admin', 'reason': 'request prod approval', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert request_approval.status_code == 200, request_approval.text
        _approve_all_portfolio_approvals(client, headers, portfolio_id=portfolio_id, environment='prod')

        drift = client.get(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/policy-baseline-drift?tenant_id=tenant-a&workspace_id=ws-a&environment=prod&actor=auditor',
            headers=headers,
        )
        assert drift.status_code == 200, drift.text
        drift_payload = drift.json()['policy_baseline_drift']
        assert drift_payload['overall_status'] == 'drifted'
        assert drift_payload['summary']['unapproved_count'] >= 1

        blocked_export = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-package-export',
            headers=headers,
            json={'actor': 'auditor', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert blocked_export.status_code == 200, blocked_export.text
        assert blocked_export.json()['ok'] is False
        assert blocked_export.json()['error'] == 'portfolio_security_envelope_failed'

        approved = _request_and_approve_policy_deviation(client, headers, portfolio_id=portfolio_id, environment='prod')
        assert approved['exception']['status'] == 'approved'
        assert approved['policy_baseline_drift']['overall_status'] == 'approved_deviation'

        exported = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-package-export',
            headers=headers,
            json={'actor': 'auditor', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert exported.status_code == 200, exported.text
        exported_payload = exported.json()
        assert exported_payload['ok'] is True
        assert exported_payload['package']['policy_baseline_drift']['overall_status'] == 'approved_deviation'



def test_policy_deviation_exception_expires_and_reverts_to_nonconformant(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_608_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    env_policy = {
        'prod': {
            'operational_tier': 'prod',
            'evidence_classification': 'regulated-enterprise-evidence',
            'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'}]},
            'security_gate_policy': {'enabled': True, 'envelope_label': 'prod-envelope', 'min_approval_layers': 1, 'required_approval_roles': ['ops-director'], 'block_on_nonconformance': True, 'enforce_before_sensitive_export': True},
            'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'prod-signer'},
        },
    }
    env_baseline = {
        'prod': {
            'operational_tier': 'prod',
            'evidence_classification': 'regulated-enterprise-evidence',
            'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'}]},
            'security_gate_policy': {'enabled': True, 'envelope_label': 'prod-envelope', 'min_approval_layers': 1, 'required_approval_roles': ['ops-director'], 'block_on_nonconformance': True, 'enforce_before_sensitive_export': True},
            'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-signer'},
        },
    }

    with TestClient(app) as client:
        runtime_id = _create_runtime_for_environment(client, headers, name='runtime-policy-expiry', environment='prod')
        portfolio_id = _create_submitted_portfolio_with_baseline(
            client,
            headers,
            base_now=base_now,
            runtime_id=runtime_id,
            environment='prod',
            environment_tier_policies=env_policy,
            environment_policy_baselines=env_baseline,
            deviation_management_policy={'enabled': True, 'require_approval': True, 'requested_role': 'governance-board', 'default_ttl_s': 60, 'max_ttl_s': 60, 'block_on_expired': True},
        )
        client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/approve',
            headers=headers,
            json={'actor': 'portfolio-admin', 'reason': 'request prod approval', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        _approve_all_portfolio_approvals(client, headers, portfolio_id=portfolio_id, environment='prod')
        approved = _request_and_approve_policy_deviation(client, headers, portfolio_id=portfolio_id, environment='prod', ttl_s=60)
        assert approved['policy_baseline_drift']['overall_status'] == 'approved_deviation'

        _set_now(monkeypatch, base_now + 120.0)
        expired = client.get(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/policy-baseline-drift?tenant_id=tenant-a&workspace_id=ws-a&environment=prod&actor=auditor&persist_metadata=true',
            headers=headers,
        )
        assert expired.status_code == 200, expired.text
        expired_payload = expired.json()['policy_baseline_drift']
        assert expired_payload['overall_status'] == 'expired_exception'
        assert expired_payload['summary']['expired_count'] >= 1

        conformance = client.get(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/policy-conformance?tenant_id=tenant-a&workspace_id=ws-a&environment=prod&actor=auditor',
            headers=headers,
        )
        assert conformance.status_code == 200, conformance.text
        assert conformance.json()['policy_conformance']['overall_status'] == 'nonconformant'



def test_canvas_runtime_board_surfaces_policy_baseline_drift_and_deviation_counts(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_609_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_canvas_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    env_policy = {
        'prod': {
            'operational_tier': 'prod',
            'evidence_classification': 'regulated-enterprise-evidence',
            'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'}]},
            'security_gate_policy': {'enabled': True, 'min_approval_layers': 1, 'required_approval_roles': ['ops-director']},
            'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'prod-signer'},
        },
    }
    env_baseline = {
        'prod': {
            'operational_tier': 'prod',
            'evidence_classification': 'regulated-enterprise-evidence',
            'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'}]},
            'security_gate_policy': {'enabled': True, 'min_approval_layers': 1, 'required_approval_roles': ['ops-director']},
            'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-signer'},
        },
    }

    with TestClient(app) as client:
        canvas = client.post(
            '/admin/canvas/documents',
            headers=headers,
            json={'actor': 'admin', 'title': 'Baseline drift canvas', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert canvas.status_code == 200, canvas.text
        canvas_id = canvas.json()['document']['canvas_id']
        runtime_id = _create_runtime_for_environment(client, headers, name='runtime-canvas-baseline', environment='prod')
        node = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes',
            headers=headers,
            json={'actor': 'admin', 'node_type': 'openclaw_runtime', 'label': 'Runtime baseline node', 'data': {'runtime_id': runtime_id, 'agent_id': 'default'}, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert node.status_code == 200, node.text
        node_id = node.json()['node']['node_id']

        drifted_portfolio_id = _create_submitted_portfolio_with_baseline(
            client,
            headers,
            base_now=base_now,
            runtime_id=runtime_id,
            environment='prod',
            environment_tier_policies=env_policy,
            environment_policy_baselines=env_baseline,
        )
        client.post(
            f'/admin/openclaw/alert-governance/portfolios/{drifted_portfolio_id}/approve',
            headers=headers,
            json={'actor': 'portfolio-admin', 'reason': 'request prod approval', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        _approve_all_portfolio_approvals(client, headers, portfolio_id=drifted_portfolio_id, environment='prod')

        governed_portfolio_id = _create_submitted_portfolio_with_baseline(
            client,
            headers,
            base_now=base_now + 100.0,
            runtime_id=runtime_id,
            environment='prod',
            environment_tier_policies=env_policy,
            environment_policy_baselines=env_baseline,
        )
        client.post(
            f'/admin/openclaw/alert-governance/portfolios/{governed_portfolio_id}/approve',
            headers=headers,
            json={'actor': 'portfolio-admin', 'reason': 'request prod approval', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        _approve_all_portfolio_approvals(client, headers, portfolio_id=governed_portfolio_id, environment='prod')
        _request_and_approve_policy_deviation(client, headers, portfolio_id=governed_portfolio_id, environment='prod')

        board = client.get(
            f'/admin/canvas/documents/{canvas_id}/views/runtime-board?tenant_id=tenant-a&workspace_id=ws-a&environment=prod&limit=10',
            headers=headers,
        )
        assert board.status_code == 200, board.text
        summary = board.json()['items'][0]['summary']
        assert summary['governance_portfolio_policy_baseline_drift_status_counts']['drifted'] >= 1
        assert summary['governance_portfolio_policy_baseline_drift_status_counts']['approved_deviation'] >= 1
        assert summary['governance_portfolio_policy_deviation_exception_count'] >= 1

        action = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/report_portfolio_policy_baseline_drift?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'admin', 'portfolio_id': drifted_portfolio_id, 'persist_metadata': True},
        )
        assert action.status_code == 200, action.text
        assert action.json()['result']['policy_baseline_drift']['overall_status'] == 'drifted'
