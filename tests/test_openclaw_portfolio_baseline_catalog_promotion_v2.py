from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

import app as app_module
from openmiura.application.openclaw.scheduler import OpenClawRecoverySchedulerService
from openmiura.gateway import Gateway
from tests.test_openclaw_portfolio_environment_envelopes_conformance_v2 import _approve_all_portfolio_approvals
from tests.test_openclaw_portfolio_environment_tiered_governance_v2 import (
    _create_and_approve_bundle_for_environment,
    _create_runtime_for_environment,
)
from tests.test_openclaw_portfolio_evidence_packaging_v2 import _set_now, _write_config
from tests.test_openclaw_portfolio_policy_baselines_deviation_v2 import _request_and_approve_policy_deviation


def _create_baseline_catalog(
    client: TestClient,
    headers: dict[str, str],
    *,
    name: str,
    version: str,
    environment_policy_baselines: dict[str, object],
    parent_catalog_id: str | None = None,
    promotion_policy: dict[str, object] | None = None,
) -> dict:
    response = client.post(
        '/admin/openclaw/alert-governance/baseline-catalogs',
        headers=headers,
        json={
            'actor': 'catalog-admin',
            'name': name,
            'version': version,
            'environment_policy_baselines': environment_policy_baselines,
            'parent_catalog_id': parent_catalog_id,
            'promotion_policy': promotion_policy or {},
            'tenant_id': 'tenant-a',
            'workspace_id': 'ws-a',
            'environment': 'prod',
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload['ok'] is True
    return payload


def _create_portfolio_with_catalog(
    client: TestClient,
    headers: dict[str, str],
    *,
    base_now: float,
    runtime_id: str,
    environment: str,
    environment_tier_policies: dict[str, object],
    baseline_catalog_ref: dict[str, object],
    train_policy_extras: dict[str, object] | None = None,
) -> str:
    bundle_id = _create_and_approve_bundle_for_environment(
        client,
        headers,
        name=f'bundle-catalog-{environment}-{int(base_now)}',
        runtime_ids=[runtime_id],
        environment=environment,
    )
    create = client.post(
        '/admin/openclaw/alert-governance/portfolios',
        headers=headers,
        json={
            'actor': 'portfolio-admin',
            'name': f'portfolio-catalog-{environment}-{int(base_now)}',
            'version': f'2026.03.31.catalog.{environment}.{int(base_now)}',
            'bundle_ids': [bundle_id],
            'base_release_at': base_now + 10,
            'environment_tier_policies': environment_tier_policies,
            'baseline_catalog_ref': baseline_catalog_ref,
            'deviation_management_policy': {'enabled': True, 'require_approval': True, 'requested_role': 'governance-board', 'default_ttl_s': 3600},
            **dict(train_policy_extras or {}),
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
    approve = client.post(
        f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/approve',
        headers=headers,
        json={'actor': 'portfolio-admin', 'reason': 'request approval', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': environment},
    )
    assert approve.status_code == 200, approve.text
    _approve_all_portfolio_approvals(client, headers, portfolio_id=portfolio_id, environment=environment)
    return portfolio_id


def test_baseline_catalog_inheritance_resolves_for_portfolio(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_720_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    parent_baselines = {
        'prod': {
            'operational_tier': 'prod',
            'evidence_classification': 'regulated-enterprise-evidence',
            'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'}]},
            'security_gate_policy': {'enabled': True, 'envelope_label': 'prod-envelope', 'min_approval_layers': 1, 'required_approval_roles': ['ops-director'], 'block_on_nonconformance': True},
            'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'parent-signer'},
        },
    }
    child_baselines = {
        'prod': {
            'evidence_classification': 'regulated-enterprise-evidence',
            'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'child-signer'},
        },
    }
    env_policy = {
        'prod': {
            'operational_tier': 'prod',
            'evidence_classification': 'regulated-enterprise-evidence',
            'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'}]},
            'security_gate_policy': {'enabled': True, 'envelope_label': 'prod-envelope', 'min_approval_layers': 1, 'required_approval_roles': ['ops-director'], 'block_on_nonconformance': True},
            'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'child-signer'},
        },
    }

    with TestClient(app) as client:
        parent = _create_baseline_catalog(
            client,
            headers,
            name='parent-prod-catalog',
            version='catalog-v1',
            environment_policy_baselines=parent_baselines,
        )
        child = _create_baseline_catalog(
            client,
            headers,
            name='child-prod-catalog',
            version='catalog-v1-child',
            environment_policy_baselines=child_baselines,
            parent_catalog_id=parent['catalog_id'],
        )
        runtime_id = _create_runtime_for_environment(client, headers, name='runtime-catalog-inheritance', environment='prod')
        portfolio_id = _create_portfolio_with_catalog(
            client,
            headers,
            base_now=base_now,
            runtime_id=runtime_id,
            environment='prod',
            environment_tier_policies=env_policy,
            baseline_catalog_ref={'catalog_id': child['catalog_id']},
        )
        detail = client.get(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert detail.status_code == 200, detail.text
        payload = detail.json()
        baseline = payload['portfolio']['environment_policy_baseline']
        assert baseline['configured'] is True
        assert baseline['catalog_id'] == child['catalog_id']
        assert baseline['parent_catalog_ref']['catalog_id'] == parent['catalog_id']
        assert baseline['signing_policy']['key_id'] == 'child-signer'
        assert baseline['approval_policy']['layers'][0]['requested_role'] == 'ops-director'
        assert payload['policy_baseline_drift']['overall_status'] == 'aligned'


def test_baseline_promotion_rollout_updates_catalog_and_impacted_portfolios(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_721_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    baselines_v1 = {
        'prod': {
            'operational_tier': 'prod',
            'evidence_classification': 'regulated-enterprise-evidence',
            'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'}]},
            'security_gate_policy': {'enabled': True, 'envelope_label': 'prod-envelope', 'min_approval_layers': 1, 'required_approval_roles': ['ops-director'], 'block_on_nonconformance': True},
            'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v1'},
        },
    }
    env_policy = {
        'prod': {
            'operational_tier': 'prod',
            'evidence_classification': 'regulated-enterprise-evidence',
            'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'}]},
            'security_gate_policy': {'enabled': True, 'envelope_label': 'prod-envelope', 'min_approval_layers': 1, 'required_approval_roles': ['ops-director'], 'block_on_nonconformance': True},
            'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v1'},
        },
    }

    with TestClient(app) as client:
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='promotion-catalog',
            version='catalog-v1',
            environment_policy_baselines=baselines_v1,
            promotion_policy={'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'gov', 'requested_role': 'governance-board', 'label': 'Governance board'}]}},
        )
        runtime_id = _create_runtime_for_environment(client, headers, name='runtime-catalog-promotion', environment='prod')
        portfolio_id = _create_portfolio_with_catalog(
            client,
            headers,
            base_now=base_now,
            runtime_id=runtime_id,
            environment='prod',
            environment_tier_policies=env_policy,
            baseline_catalog_ref={'catalog_id': catalog['catalog_id']},
        )
        before = client.get(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/policy-baseline-drift?tenant_id=tenant-a&workspace_id=ws-a&environment=prod&actor=auditor',
            headers=headers,
        )
        assert before.status_code == 200, before.text
        assert before.json()['policy_baseline_drift']['overall_status'] == 'aligned'

        promotion = client.post(
            f'/admin/openclaw/alert-governance/baseline-catalogs/{catalog["catalog_id"]}/promotions',
            headers=headers,
            json={
                'actor': 'catalog-admin',
                'version': 'catalog-v2',
                'environment_policy_baselines': {
                    'prod': {
                        'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v2'},
                    },
                },
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert promotion.status_code == 200, promotion.text
        promotion_payload = promotion.json()
        assert promotion_payload['baseline_promotion']['rollout_impact']['summary']['count'] == 1
        promotion_id = promotion_payload['promotion_id']

        approved = client.post(
            f'/admin/openclaw/alert-governance/baseline-promotions/{promotion_id}/actions/approve',
            headers=headers,
            json={'actor': 'governance-board', 'reason': 'promote baseline', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert approved.status_code == 200, approved.text
        approved_payload = approved.json()
        assert approved_payload['release']['status'] == 'approved'
        assert approved_payload['catalog']['baseline_catalog']['current_version']['catalog_version'] == 'catalog-v2'

        detail = client.get(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert detail.status_code == 200, detail.text
        detail_payload = detail.json()
        assert detail_payload['policy_baseline_drift']['overall_status'] == 'drifted'
        assert detail_payload['portfolio']['baseline_catalog_rollout']['promotion_id'] == promotion_id
        assert detail_payload['portfolio']['environment_policy_baseline']['signing_policy']['key_id'] == 'baseline-v2'


def test_evidence_exports_include_baseline_catalog_rollout_evidence(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_722_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    baselines_v1 = {
        'prod': {
            'operational_tier': 'prod',
            'evidence_classification': 'regulated-enterprise-evidence',
            'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'}]},
            'security_gate_policy': {'enabled': True, 'envelope_label': 'prod-envelope', 'min_approval_layers': 1, 'required_approval_roles': ['ops-director'], 'block_on_nonconformance': True, 'enforce_before_sensitive_export': True},
            'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v1'},
        },
    }
    env_policy = {
        'prod': {
            'operational_tier': 'prod',
            'evidence_classification': 'regulated-enterprise-evidence',
            'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'}]},
            'security_gate_policy': {'enabled': True, 'envelope_label': 'prod-envelope', 'min_approval_layers': 1, 'required_approval_roles': ['ops-director'], 'block_on_nonconformance': True, 'enforce_before_sensitive_export': True},
            'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v1'},
        },
    }

    with TestClient(app) as client:
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='evidence-catalog',
            version='catalog-v1',
            environment_policy_baselines=baselines_v1,
            promotion_policy={'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'gov', 'requested_role': 'governance-board', 'label': 'Governance board'}]}},
        )
        runtime_id = _create_runtime_for_environment(client, headers, name='runtime-catalog-evidence', environment='prod')
        portfolio_id = _create_portfolio_with_catalog(
            client,
            headers,
            base_now=base_now,
            runtime_id=runtime_id,
            environment='prod',
            environment_tier_policies=env_policy,
            baseline_catalog_ref={'catalog_id': catalog['catalog_id']},
        )
        promotion = client.post(
            f'/admin/openclaw/alert-governance/baseline-catalogs/{catalog["catalog_id"]}/promotions',
            headers=headers,
            json={
                'actor': 'catalog-admin',
                'version': 'catalog-v2',
                'environment_policy_baselines': {'prod': {'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v2'}}},
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert promotion.status_code == 200, promotion.text
        promotion_id = promotion.json()['promotion_id']
        approved = client.post(
            f'/admin/openclaw/alert-governance/baseline-promotions/{promotion_id}/actions/approve',
            headers=headers,
            json={'actor': 'governance-board', 'reason': 'promote baseline', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert approved.status_code == 200, approved.text

        deviation = _request_and_approve_policy_deviation(client, headers, portfolio_id=portfolio_id, environment='prod')
        assert deviation['policy_baseline_drift']['overall_status'] == 'approved_deviation'

        exported = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-package-export',
            headers=headers,
            json={'actor': 'auditor', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert exported.status_code == 200, exported.text
        payload = exported.json()
        assert payload['ok'] is True
        attestation_report = payload['package']['attestation_export']['report']
        assert attestation_report['train_policy']['baseline_catalog_ref']['catalog_id'] == catalog['catalog_id']
        assert attestation_report['baseline_catalog_rollout']['promotion_id'] == promotion_id


def test_baseline_promotion_simulation_forecasts_wave_gate_and_calendar(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_722_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    baselines_v1 = {
        'prod': {
            'operational_tier': 'prod',
            'evidence_classification': 'regulated-enterprise-evidence',
            'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'}]},
            'security_gate_policy': {'enabled': True, 'envelope_label': 'prod-envelope', 'min_approval_layers': 1, 'required_approval_roles': ['ops-director'], 'block_on_nonconformance': True},
            'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v1'},
        },
    }
    env_policy = {
        'prod': {
            'operational_tier': 'prod',
            'evidence_classification': 'regulated-enterprise-evidence',
            'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'}]},
            'security_gate_policy': {'enabled': True, 'envelope_label': 'prod-envelope', 'min_approval_layers': 1, 'required_approval_roles': ['ops-director'], 'block_on_nonconformance': True},
            'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v1'},
        },
    }

    with TestClient(app) as client:
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='promotion-sim-catalog',
            version='catalog-v1',
            environment_policy_baselines=baselines_v1,
            promotion_policy={
                'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'gov', 'requested_role': 'governance-board', 'label': 'Governance board'}]},
                'rollout_policy': {
                    'enabled': True,
                    'wave_size': 1,
                    'default_timezone': 'UTC',
                    'maintenance_windows': [
                        {'window_kind': 'absolute', 'start_at': base_now - 60, 'end_at': base_now + 600, 'timezone': 'UTC'},
                    ],
                },
                'gate_policy': {
                    'enabled': True,
                    'block_on_baseline_drift': True,
                    'max_blocking_baseline_drift_count': 0,
                },
            },
        )
        runtime_id = _create_runtime_for_environment(client, headers, name='runtime-catalog-promotion-sim', environment='prod')
        _create_portfolio_with_catalog(
            client,
            headers,
            base_now=base_now,
            runtime_id=runtime_id,
            environment='prod',
            environment_tier_policies=env_policy,
            baseline_catalog_ref={'catalog_id': catalog['catalog_id']},
        )

        simulation = client.post(
            f'/admin/openclaw/alert-governance/baseline-catalogs/{catalog["catalog_id"]}/promotions/simulate',
            headers=headers,
            json={
                'actor': 'catalog-admin',
                'version': 'catalog-v2-sim',
                'environment_policy_baselines': {
                    'prod': {
                        'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v2'},
                    },
                },
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert simulation.status_code == 200, simulation.text
        payload = simulation.json()
        assert payload['ok'] is True
        assert payload['mode'] == 'dry-run'
        assert payload['summary']['affected_count'] == 1
        assert payload['summary']['validation_status'] == 'passed'
        assert payload['summary']['approvable'] is False
        assert payload['approval_preview']['required'] is True
        assert payload['rollout_plan']['wave_count'] == 1
        wave = payload['rollout_plan']['items'][0]
        assert wave['gate_evaluation']['status'] == 'failed'
        assert 'blocking_baseline_drift' in wave['gate_evaluation']['reasons']
        assert wave['calendar_decision']['next_allowed_at'] is not None
        assert payload['analytics']['gate_reason_counts']['blocking_baseline_drift'] >= 1


def test_baseline_promotion_simulation_reports_invalid_dependency_graph_without_persisting(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_723_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    baselines_v1 = {
        'prod': {
            'operational_tier': 'prod',
            'evidence_classification': 'regulated-enterprise-evidence',
            'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'}]},
            'security_gate_policy': {'enabled': True, 'envelope_label': 'prod-envelope', 'min_approval_layers': 1, 'required_approval_roles': ['ops-director'], 'block_on_nonconformance': True},
            'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v1'},
        },
    }
    env_policy = {
        'prod': {
            'operational_tier': 'prod',
            'evidence_classification': 'regulated-enterprise-evidence',
            'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'}]},
            'security_gate_policy': {'enabled': True, 'envelope_label': 'prod-envelope', 'min_approval_layers': 1, 'required_approval_roles': ['ops-director'], 'block_on_nonconformance': True},
            'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v1'},
        },
    }

    with TestClient(app) as client:
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='promotion-sim-invalid-catalog',
            version='catalog-v1',
            environment_policy_baselines=baselines_v1,
        )
        runtime_a = _create_runtime_for_environment(client, headers, name='runtime-catalog-promotion-sim-a', environment='prod')
        runtime_b = _create_runtime_for_environment(client, headers, name='runtime-catalog-promotion-sim-b', environment='prod')
        portfolio_a = _create_portfolio_with_catalog(
            client,
            headers,
            base_now=base_now,
            runtime_id=runtime_a,
            environment='prod',
            environment_tier_policies=env_policy,
            baseline_catalog_ref={'catalog_id': catalog['catalog_id']},
        )
        portfolio_b = _create_portfolio_with_catalog(
            client,
            headers,
            base_now=base_now + 10,
            runtime_id=runtime_b,
            environment='prod',
            environment_tier_policies=env_policy,
            baseline_catalog_ref={'catalog_id': catalog['catalog_id']},
        )

        simulation = client.post(
            f'/admin/openclaw/alert-governance/baseline-catalogs/{catalog["catalog_id"]}/promotions/simulate',
            headers=headers,
            json={
                'actor': 'catalog-admin',
                'version': 'catalog-v2-invalid-sim',
                'environment_policy_baselines': {
                    'prod': {
                        'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v2'},
                    },
                },
                'rollout_policy': {
                    'enabled': True,
                    'portfolio_groups': [
                        {'group_id': 'g1', 'portfolio_ids': [portfolio_a], 'depends_on_groups': ['g2']},
                        {'group_id': 'g2', 'portfolio_ids': [portfolio_b], 'depends_on_groups': ['g1']},
                    ],
                },
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert simulation.status_code == 200, simulation.text
        payload = simulation.json()
        assert payload['ok'] is True
        assert payload['mode'] == 'dry-run'
        assert payload['summary']['validation_status'] == 'failed'
        assert payload['summary']['approvable'] is False
        assert payload['validation']['errors']
        assert any(item['code'] == 'dependency_cycle_detected' for item in payload['validation']['errors'])
        assert payload['rollout_plan']['summary']['validation_failed'] is True
        create = client.post(
            f'/admin/openclaw/alert-governance/baseline-catalogs/{catalog["catalog_id"]}/promotions',
            headers=headers,
            json={
                'actor': 'catalog-admin',
                'version': 'catalog-v2-invalid-real',
                'environment_policy_baselines': {
                    'prod': {
                        'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v2'},
                    },
                },
                'rollout_policy': {
                    'enabled': True,
                    'portfolio_groups': [
                        {'group_id': 'g1', 'portfolio_ids': [portfolio_a], 'depends_on_groups': ['g2']},
                        {'group_id': 'g2', 'portfolio_ids': [portfolio_b], 'depends_on_groups': ['g1']},
                    ],
                },
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert create.status_code == 200, create.text
        create_payload = create.json()
        assert create_payload['ok'] is False
        assert create_payload['error'] == 'baseline_rollout_plan_invalid'



def test_baseline_promotion_simulation_exposes_multireview_policy(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_723_500.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    baselines_v1 = {
        'prod': {
            'operational_tier': 'prod',
            'evidence_classification': 'regulated-enterprise-evidence',
            'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'}]},
            'security_gate_policy': {'enabled': True, 'envelope_label': 'prod-envelope', 'min_approval_layers': 1, 'required_approval_roles': ['ops-director'], 'block_on_nonconformance': True},
            'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v1'},
        },
    }
    env_policy = {
        'prod': {
            'operational_tier': 'prod',
            'evidence_classification': 'regulated-enterprise-evidence',
            'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'}]},
            'security_gate_policy': {'enabled': True, 'envelope_label': 'prod-envelope', 'min_approval_layers': 1, 'required_approval_roles': ['ops-director'], 'block_on_nonconformance': True},
            'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v1'},
        },
    }

    with TestClient(app) as client:
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='promotion-sim-review-policy-catalog',
            version='catalog-v1',
            environment_policy_baselines=baselines_v1,
            promotion_policy={
                'simulation_review_policy': {
                    'mode': 'sequential',
                    'allow_self_review': False,
                    'layers': [
                        {'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'},
                        {'layer_id': 'risk', 'requested_role': 'risk-board', 'label': 'Risk board'},
                    ],
                },
            },
        )
        runtime_id = _create_runtime_for_environment(client, headers, name='runtime-catalog-promotion-sim-review-policy', environment='prod')
        _create_portfolio_with_catalog(
            client,
            headers,
            base_now=base_now,
            runtime_id=runtime_id,
            environment='prod',
            environment_tier_policies=env_policy,
            baseline_catalog_ref={'catalog_id': catalog['catalog_id']},
        )
        simulation = client.post(
            f'/admin/openclaw/alert-governance/baseline-catalogs/{catalog["catalog_id"]}/promotions/simulate',
            headers=headers,
            json={
                'actor': 'catalog-admin',
                'version': 'catalog-v2-sim-review-policy',
                'environment_policy_baselines': {
                    'prod': {
                        'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v2'},
                    },
                },
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert simulation.status_code == 200, simulation.text
        payload = simulation.json()
        assert payload['ok'] is True
        assert payload['simulation_policy']['approval_policy']['mode'] == 'sequential'
        assert payload['simulation_policy']['allow_self_review'] is False
        assert [item['layer_id'] for item in payload['simulation_policy']['approval_policy']['layers']] == ['ops', 'risk']
        assert payload['summary']['review_required'] is True
        assert payload['summary']['review_satisfied'] is False
        assert payload['summary']['review_status'] == 'not_requested'
        assert payload['review_state']['required'] is True
        assert payload['review_state']['next_layer']['layer_id'] == 'ops'
        assert payload['review'] == {'approved': False, 'review_required': True, 'review_count': 0, 'pending_layers': ['ops', 'risk']}





def test_baseline_promotion_simulation_evidence_package_export_creates_immutable_registry(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_724_100.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    baselines_v1 = {
        'prod': {
            'operational_tier': 'prod',
            'evidence_classification': 'regulated-enterprise-evidence',
            'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'}]},
            'security_gate_policy': {'enabled': True, 'envelope_label': 'prod-envelope', 'min_approval_layers': 1, 'required_approval_roles': ['ops-director'], 'block_on_nonconformance': True},
            'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v1'},
        },
    }
    env_policy = {
        'prod': {
            'operational_tier': 'prod',
            'evidence_classification': 'regulated-enterprise-evidence',
            'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'}]},
            'security_gate_policy': {'enabled': True, 'envelope_label': 'prod-envelope', 'min_approval_layers': 1, 'required_approval_roles': ['ops-director'], 'block_on_nonconformance': True},
            'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v1'},
        },
    }

    with TestClient(app) as client:
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='promotion-sim-evidence-catalog',
            version='catalog-v1',
            environment_policy_baselines=baselines_v1,
            promotion_policy={
                'simulation_review_policy': {
                    'mode': 'sequential',
                    'allow_self_review': False,
                    'require_reason': True,
                    'layers': [
                        {'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'},
                        {'layer_id': 'risk', 'requested_role': 'risk-board', 'label': 'Risk board'},
                    ],
                },
                'simulation_ttl_s': 3600,
                'max_evidence_packages': 10,
            },
        )
        runtime_id = _create_runtime_for_environment(client, headers, name='runtime-catalog-promotion-sim-evidence', environment='prod')
        _create_portfolio_with_catalog(
            client,
            headers,
            base_now=base_now,
            runtime_id=runtime_id,
            environment='prod',
            environment_tier_policies=env_policy,
            baseline_catalog_ref={'catalog_id': catalog['catalog_id']},
        )
        promotion_resp = client.post(
            f'/admin/openclaw/alert-governance/baseline-catalogs/{catalog["catalog_id"]}/promotions',
            headers=headers,
            json={
                'actor': 'catalog-admin',
                'version': 'catalog-v2-sim-evidence',
                'environment_policy_baselines': {
                    'prod': {
                        'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v2'},
                    },
                },
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert promotion_resp.status_code == 200, promotion_resp.text
        promotion_id = promotion_resp.json()['promotion_id']
        scheduler = OpenClawRecoverySchedulerService()
        simulation = scheduler.simulate_existing_runtime_alert_governance_baseline_promotion(
            app.state.gw,
            promotion_id=promotion_id,
            actor='catalog-admin',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        simulation = scheduler.review_runtime_alert_governance_baseline_promotion_simulation(
            app.state.gw, simulation=simulation, actor='ops-reviewer', decision='approve', reason='ops ok', layer_id='ops', tenant_id='tenant-a', workspace_id='ws-a', environment='prod'
        )['simulation']
        simulation = scheduler.review_runtime_alert_governance_baseline_promotion_simulation(
            app.state.gw, simulation=simulation, actor='risk-reviewer', decision='approve', reason='risk ok', layer_id='risk', tenant_id='tenant-a', workspace_id='ws-a', environment='prod'
        )['simulation']

        first = scheduler.export_runtime_alert_governance_baseline_promotion_simulation_evidence_package(
            app.state.gw,
            simulation=simulation,
            actor='export-bot',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert first['ok'] is True
        assert first['package']['report_type'] == 'openmiura_baseline_promotion_simulation_evidence_package_v1'
        assert first['artifact']['artifact_type'] == 'openmiura_baseline_promotion_simulation_evidence_artifact_v1'
        assert first['registry_entry']['sequence'] == 1
        assert first['registry_summary']['chain_ok'] is True
        assert first['simulation_evidence_packages']['summary']['count'] == 1

        second = scheduler.export_runtime_alert_governance_baseline_promotion_simulation_evidence_package(
            app.state.gw,
            simulation=simulation,
            actor='export-bot',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert second['ok'] is True
        assert second['registry_entry']['sequence'] == 2
        assert second['registry_entry']['previous_entry_hash'] == first['registry_entry']['entry_hash']
        assert second['registry_summary']['count'] == 2
        assert second['registry_summary']['package_count'] == 2
        assert second['registry_summary']['chain_ok'] is True

        detail = scheduler.get_runtime_alert_governance_baseline_promotion(
            app.state.gw, promotion_id=promotion_id, tenant_id='tenant-a', workspace_id='ws-a', environment='prod'
        )
        assert detail['simulation_evidence_packages']['summary']['count'] == 2
        assert detail['simulation_export_registry']['summary']['count'] == 2
        assert detail['simulation_export_registry']['summary']['immutable_count'] == 2
        assert detail['simulation_export_registry']['summary']['chain_ok'] is True

def test_baseline_promotion_simulation_exports_attestation_and_review_audit(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_723_800.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    baselines_v1 = {
        'prod': {
            'operational_tier': 'prod',
            'evidence_classification': 'regulated-enterprise-evidence',
            'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'}]},
            'security_gate_policy': {'enabled': True, 'envelope_label': 'prod-envelope', 'min_approval_layers': 1, 'required_approval_roles': ['ops-director'], 'block_on_nonconformance': True},
            'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v1'},
        },
    }
    env_policy = {
        'prod': {
            'operational_tier': 'prod',
            'evidence_classification': 'regulated-enterprise-evidence',
            'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'}]},
            'security_gate_policy': {'enabled': True, 'envelope_label': 'prod-envelope', 'min_approval_layers': 1, 'required_approval_roles': ['ops-director'], 'block_on_nonconformance': True},
            'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v1'},
        },
    }

    with TestClient(app) as client:
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='promotion-sim-export-catalog',
            version='catalog-v1',
            environment_policy_baselines=baselines_v1,
            promotion_policy={
                'simulation_review_policy': {
                    'mode': 'sequential',
                    'allow_self_review': False,
                    'require_reason': True,
                    'layers': [
                        {'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'},
                        {'layer_id': 'risk', 'requested_role': 'risk-board', 'label': 'Risk board'},
                    ],
                },
            },
        )
        runtime_id = _create_runtime_for_environment(client, headers, name='runtime-catalog-promotion-sim-export', environment='prod')
        _create_portfolio_with_catalog(
            client,
            headers,
            base_now=base_now,
            runtime_id=runtime_id,
            environment='prod',
            environment_tier_policies=env_policy,
            baseline_catalog_ref={'catalog_id': catalog['catalog_id']},
        )
        promotion_resp = client.post(
            f'/admin/openclaw/alert-governance/baseline-catalogs/{catalog["catalog_id"]}/promotions',
            headers=headers,
            json={
                'actor': 'catalog-admin',
                'version': 'catalog-v2-sim-export',
                'environment_policy_baselines': {
                    'prod': {
                        'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v2'},
                    },
                },
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert promotion_resp.status_code == 200, promotion_resp.text
        promotion_id = promotion_resp.json()['promotion_id']
        scheduler = OpenClawRecoverySchedulerService()
        simulation = scheduler.simulate_existing_runtime_alert_governance_baseline_promotion(
            app.state.gw,
            promotion_id=promotion_id,
            actor='catalog-admin',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert simulation['ok'] is True
        first_review = scheduler.review_runtime_alert_governance_baseline_promotion_simulation(
            app.state.gw,
            simulation=simulation,
            actor='ops-reviewer',
            decision='approve',
            reason='ops review passed',
            layer_id='ops',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert first_review['ok'] is True
        second_review = scheduler.review_runtime_alert_governance_baseline_promotion_simulation(
            app.state.gw,
            simulation=first_review['simulation'],
            actor='risk-reviewer',
            decision='approve',
            reason='risk review passed',
            layer_id='risk',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert second_review['ok'] is True
        reviewed_simulation = second_review['simulation']
        assert reviewed_simulation['simulation_status'] == 'reviewed'

        attestation = scheduler.export_runtime_alert_governance_baseline_promotion_simulation_attestation(
            app.state.gw,
            simulation=reviewed_simulation,
            actor='export-bot',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert attestation['ok'] is True
        assert attestation['report']['report_type'] == 'openmiura_baseline_promotion_simulation_attestation_v1'
        assert attestation['report']['simulation']['simulation_status'] == 'reviewed'
        assert attestation['report']['review_state']['overall_status'] == 'approved'
        assert attestation['report']['observed_versions']['catalog_version'] == reviewed_simulation['observed_versions']['catalog_version']
        assert attestation['integrity']['signed'] is True

        review_audit = scheduler.export_runtime_alert_governance_baseline_promotion_simulation_review_audit(
            app.state.gw,
            simulation=reviewed_simulation,
            actor='export-bot',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert review_audit['ok'] is True
        assert review_audit['report']['report_type'] == 'openmiura_baseline_promotion_simulation_review_audit_v1'
        assert review_audit['report']['review_sequence']['mode'] == 'sequential'
        assert review_audit['report']['review_sequence']['overall_status'] == 'approved'
        assert [item['actor'] for item in review_audit['report']['ordered_reviews']] == ['ops-reviewer', 'risk-reviewer']
        assert review_audit['report']['separation_of_duties']['self_review_detected'] is False
        assert review_audit['integrity']['signed'] is True


def test_baseline_promotion_simulation_evidence_registry_verify_and_restore_replays_state(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_724_200.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    baselines_v1 = {
        'prod': {
            'operational_tier': 'prod',
            'evidence_classification': 'regulated-enterprise-evidence',
            'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'}]},
            'security_gate_policy': {'enabled': True, 'envelope_label': 'prod-envelope', 'min_approval_layers': 1, 'required_approval_roles': ['ops-director'], 'block_on_nonconformance': True},
            'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v1'},
        },
    }
    env_policy = {
        'prod': {
            'operational_tier': 'prod',
            'evidence_classification': 'regulated-enterprise-evidence',
            'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'}]},
            'security_gate_policy': {'enabled': True, 'envelope_label': 'prod-envelope', 'min_approval_layers': 1, 'required_approval_roles': ['ops-director'], 'block_on_nonconformance': True},
            'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v1'},
        },
    }

    with TestClient(app) as client:
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='promotion-sim-evidence-verify-restore-catalog',
            version='catalog-v1',
            environment_policy_baselines=baselines_v1,
            promotion_policy={
                'simulation_review_policy': {
                    'mode': 'sequential',
                    'allow_self_review': False,
                    'require_reason': True,
                    'layers': [
                        {'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'},
                        {'layer_id': 'risk', 'requested_role': 'risk-board', 'label': 'Risk board'},
                    ],
                },
            },
        )
        runtime_id = _create_runtime_for_environment(client, headers, name='runtime-catalog-promotion-sim-evidence-verify-restore', environment='prod')
        _create_portfolio_with_catalog(
            client,
            headers,
            base_now=base_now,
            runtime_id=runtime_id,
            environment='prod',
            environment_tier_policies=env_policy,
            baseline_catalog_ref={'catalog_id': catalog['catalog_id']},
        )
        promotion_resp = client.post(
            f'/admin/openclaw/alert-governance/baseline-catalogs/{catalog["catalog_id"]}/promotions',
            headers=headers,
            json={
                'actor': 'catalog-admin',
                'version': 'catalog-v2',
                'environment_policy_baselines': {'prod': {'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v2'}}},
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert promotion_resp.status_code == 200, promotion_resp.text
        promotion_id = promotion_resp.json()['promotion_id']

        scheduler = OpenClawRecoverySchedulerService()
        simulation = scheduler.simulate_existing_runtime_alert_governance_baseline_promotion(
            app.state.gw,
            promotion_id=promotion_id,
            actor='catalog-admin',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        simulation = scheduler.review_runtime_alert_governance_baseline_promotion_simulation(
            app.state.gw,
            simulation=simulation,
            actor='ops-reviewer',
            decision='approve',
            reason='ops ok',
            layer_id='ops',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )['simulation']
        simulation = scheduler.review_runtime_alert_governance_baseline_promotion_simulation(
            app.state.gw,
            simulation=simulation,
            actor='risk-reviewer',
            decision='approve',
            reason='risk ok',
            layer_id='risk',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )['simulation']
        exported = scheduler.export_runtime_alert_governance_baseline_promotion_simulation_evidence_package(
            app.state.gw,
            simulation=simulation,
            actor='export-bot',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert exported['ok'] is True

        verified = scheduler.verify_runtime_alert_governance_baseline_promotion_simulation_evidence_artifact(
            app.state.gw,
            promotion_id=promotion_id,
            actor='auditor',
            package_id=exported['package_id'],
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert verified['ok'] is True
        assert verified['verification']['valid'] is True
        assert verified['verification']['registry']['membership_valid'] is True
        assert verified['verification']['registry']['chain_valid'] is True

        catalog_release = app.state.gw.audit.get_release_bundle(catalog['catalog_id'], tenant_id='tenant-a', workspace_id='ws-a', environment='prod')
        assert catalog_release is not None
        metadata = dict(catalog_release.get('metadata') or {})
        baseline_catalog = dict(metadata.get('baseline_catalog') or {})
        current_baselines = dict(baseline_catalog.get('current_baselines') or {})
        prod_baseline = dict(current_baselines.get('prod') or {})
        prod_baseline['signing_policy'] = {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v3'}
        current_baselines['prod'] = prod_baseline
        baseline_catalog['current_baselines'] = current_baselines
        metadata['baseline_catalog'] = baseline_catalog
        app.state.gw.audit.update_release_bundle(
            catalog['catalog_id'],
            status=catalog_release.get('status'),
            notes=catalog_release.get('notes'),
            metadata=metadata,
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )

        restored = scheduler.restore_runtime_alert_governance_baseline_promotion_simulation_evidence_artifact(
            app.state.gw,
            promotion_id=promotion_id,
            actor='recovery-operator',
            package_id=exported['package_id'],
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert restored['ok'] is True
        assert restored['replayed_simulation']['simulation_id'] == simulation['simulation_id']
        assert restored['replayed_simulation']['stale'] is True
        assert 'baseline_promotion_simulation_stale' in restored['replayed_simulation']['blocked_reasons']
        assert restored['restore_session']['replay']['simulation_status'] == 'stale'
        assert restored['simulation_restore_sessions']['summary']['count'] == 1

        detail = scheduler.get_runtime_alert_governance_baseline_promotion(
            app.state.gw,
            promotion_id=promotion_id,
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert detail['simulation_restore_sessions']['summary']['count'] == 1
        assert detail['simulation_restore_sessions']['items'][0]['restore_id'] == restored['restore_session']['restore_id']


def test_baseline_promotion_simulation_evidence_package_escrow_receipt_and_external_restore(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_745_500.0
    _set_now(monkeypatch, base_now)
    monkeypatch.setenv('OPENMIURA_EVIDENCE_ESCROW_DIR', (tmp_path / 'escrow').as_posix())
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    escrow_policy = {
        'enabled': True,
        'provider': 'filesystem-governed',
        'archive_namespace': 'baseline-simulation-evidence-test',
        'require_archive_on_export': True,
        'allow_inline_fallback': False,
        'immutable_retention_days': 90,
    }
    baselines_v1 = {
        'prod': {
            'operational_tier': 'prod',
            'evidence_classification': 'regulated-enterprise-evidence',
            'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'}]},
            'security_gate_policy': {'enabled': True, 'envelope_label': 'prod-envelope', 'min_approval_layers': 1, 'required_approval_roles': ['ops-director'], 'block_on_nonconformance': True},
            'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v1'},
            'escrow_policy': escrow_policy,
        },
    }
    env_policy = {
        'prod': {
            'operational_tier': 'prod',
            'evidence_classification': 'regulated-enterprise-evidence',
            'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'}]},
            'security_gate_policy': {'enabled': True, 'envelope_label': 'prod-envelope', 'min_approval_layers': 1, 'required_approval_roles': ['ops-director'], 'block_on_nonconformance': True},
            'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v1'},
            'escrow_policy': escrow_policy,
        },
    }

    with TestClient(app) as client:
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='promotion-sim-evidence-escrow-catalog',
            version='catalog-v1',
            environment_policy_baselines=baselines_v1,
            promotion_policy={
                'simulation_review_policy': {
                    'mode': 'sequential',
                    'allow_self_review': False,
                    'require_reason': True,
                    'layers': [
                        {'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'},
                        {'layer_id': 'risk', 'requested_role': 'risk-board', 'label': 'Risk board'},
                    ],
                },
                'simulation_ttl_s': 3600,
                'max_evidence_packages': 10,
            },
        )
        runtime_id = _create_runtime_for_environment(client, headers, name='runtime-catalog-promotion-sim-evidence-escrow', environment='prod')
        _create_portfolio_with_catalog(
            client,
            headers,
            base_now=base_now,
            runtime_id=runtime_id,
            environment='prod',
            environment_tier_policies=env_policy,
            baseline_catalog_ref={'catalog_id': catalog['catalog_id']},
        )
        promotion_resp = client.post(
            f'/admin/openclaw/alert-governance/baseline-catalogs/{catalog["catalog_id"]}/promotions',
            headers=headers,
            json={
                'actor': 'catalog-admin',
                'version': 'catalog-v2-sim-evidence-escrow',
                'environment_policy_baselines': {
                    'prod': {
                        'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v2'},
                    },
                },
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert promotion_resp.status_code == 200, promotion_resp.text
        promotion_id = promotion_resp.json()['promotion_id']
        scheduler = OpenClawRecoverySchedulerService()
        simulation = scheduler.simulate_existing_runtime_alert_governance_baseline_promotion(
            app.state.gw,
            promotion_id=promotion_id,
            actor='catalog-admin',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        simulation = scheduler.review_runtime_alert_governance_baseline_promotion_simulation(
            app.state.gw, simulation=simulation, actor='ops-reviewer', decision='approve', reason='ops ok', layer_id='ops', tenant_id='tenant-a', workspace_id='ws-a', environment='prod'
        )['simulation']
        simulation = scheduler.review_runtime_alert_governance_baseline_promotion_simulation(
            app.state.gw, simulation=simulation, actor='risk-reviewer', decision='approve', reason='risk ok', layer_id='risk', tenant_id='tenant-a', workspace_id='ws-a', environment='prod'
        )['simulation']

        exported = scheduler.export_runtime_alert_governance_baseline_promotion_simulation_evidence_package(
            app.state.gw,
            simulation=simulation,
            actor='export-bot',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert exported['ok'] is True
        assert exported['escrow']['archived'] is True
        assert exported['escrow']['receipt_type'] == 'openmiura_baseline_promotion_simulation_evidence_escrow_receipt_v1'
        assert Path(exported['escrow']['archive_path']).exists()
        assert exported['registry_summary']['escrowed_count'] == 1
        assert exported['registry_summary']['immutable_archive_count'] == 1

        detail = scheduler.get_runtime_alert_governance_baseline_promotion(
            app.state.gw, promotion_id=promotion_id, tenant_id='tenant-a', workspace_id='ws-a', environment='prod'
        )
        package_item = detail['simulation_evidence_packages']['items'][0]
        assert 'content_b64' not in (package_item.get('artifact') or {})
        assert package_item['escrow']['archived'] is True
        assert detail['simulation_evidence_packages']['summary']['escrowed_count'] == 1

        verified = scheduler.verify_runtime_alert_governance_baseline_promotion_simulation_evidence_artifact(
            app.state.gw,
            promotion_id=promotion_id,
            actor='auditor',
            package_id=exported['package_id'],
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert verified['verification']['status'] == 'verified'
        assert verified['verification']['checks']['escrow_receipt_valid'] is True
        assert verified['artifact']['source'] == 'escrow'
        assert verified['escrow']['archived'] is True

        restored = scheduler.restore_runtime_alert_governance_baseline_promotion_simulation_evidence_artifact(
            app.state.gw,
            promotion_id=promotion_id,
            actor='auditor',
            package_id=exported['package_id'],
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert restored['verification']['status'] == 'verified'
        assert restored['verification']['checks']['escrow_receipt_valid'] is True
        assert restored['artifact']['source'] == 'escrow'
        assert restored['restore_session']['restore_id']
        assert restored['simulation_restore_sessions']['summary']['count'] >= 1


def test_baseline_promotion_simulation_evidence_custody_reconciliation_detects_lock_drift(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_746_200.0
    _set_now(monkeypatch, base_now)
    monkeypatch.setenv('OPENMIURA_EVIDENCE_ESCROW_DIR', (tmp_path / 'escrow').as_posix())
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    escrow_policy = {
        'enabled': True,
        'provider': 'filesystem-object-lock',
        'archive_namespace': 'baseline-simulation-evidence-reconcile',
        'require_archive_on_export': True,
        'allow_inline_fallback': False,
        'immutable_retention_days': 90,
    }
    baselines_v1 = {
        'prod': {
            'operational_tier': 'prod',
            'evidence_classification': 'regulated-enterprise-evidence',
            'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'}]},
            'security_gate_policy': {'enabled': True, 'envelope_label': 'prod-envelope', 'min_approval_layers': 1, 'required_approval_roles': ['ops-director'], 'block_on_nonconformance': True},
            'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v1'},
            'escrow_policy': escrow_policy,
        },
    }
    env_policy = {
        'prod': {
            'operational_tier': 'prod',
            'evidence_classification': 'regulated-enterprise-evidence',
            'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'}]},
            'security_gate_policy': {'enabled': True, 'envelope_label': 'prod-envelope', 'min_approval_layers': 1, 'required_approval_roles': ['ops-director'], 'block_on_nonconformance': True},
            'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v1'},
            'escrow_policy': escrow_policy,
        },
    }

    with TestClient(app) as client:
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='promotion-sim-evidence-reconcile-catalog',
            version='catalog-v1',
            environment_policy_baselines=baselines_v1,
            promotion_policy={
                'simulation_review_policy': {
                    'mode': 'sequential',
                    'allow_self_review': False,
                    'require_reason': True,
                    'layers': [
                        {'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'},
                        {'layer_id': 'risk', 'requested_role': 'risk-board', 'label': 'Risk board'},
                    ],
                },
                'simulation_ttl_s': 3600,
                'max_evidence_packages': 10,
            },
        )
        runtime_id = _create_runtime_for_environment(client, headers, name='runtime-catalog-promotion-sim-evidence-reconcile', environment='prod')
        _create_portfolio_with_catalog(
            client,
            headers,
            base_now=base_now,
            runtime_id=runtime_id,
            environment='prod',
            environment_tier_policies=env_policy,
            baseline_catalog_ref={'catalog_id': catalog['catalog_id']},
        )
        promotion_resp = client.post(
            f'/admin/openclaw/alert-governance/baseline-catalogs/{catalog["catalog_id"]}/promotions',
            headers=headers,
            json={
                'actor': 'catalog-admin',
                'version': 'catalog-v2-sim-evidence-reconcile',
                'environment_policy_baselines': {
                    'prod': {
                        'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v2'},
                    },
                },
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert promotion_resp.status_code == 200, promotion_resp.text
        promotion_id = promotion_resp.json()['promotion_id']
        scheduler = OpenClawRecoverySchedulerService()
        simulation = scheduler.simulate_existing_runtime_alert_governance_baseline_promotion(
            app.state.gw,
            promotion_id=promotion_id,
            actor='catalog-admin',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        simulation = scheduler.review_runtime_alert_governance_baseline_promotion_simulation(
            app.state.gw, simulation=simulation, actor='ops-reviewer', decision='approve', reason='ops ok', layer_id='ops', tenant_id='tenant-a', workspace_id='ws-a', environment='prod'
        )['simulation']
        simulation = scheduler.review_runtime_alert_governance_baseline_promotion_simulation(
            app.state.gw, simulation=simulation, actor='risk-reviewer', decision='approve', reason='risk ok', layer_id='risk', tenant_id='tenant-a', workspace_id='ws-a', environment='prod'
        )['simulation']
        exported = scheduler.export_runtime_alert_governance_baseline_promotion_simulation_evidence_package(
            app.state.gw,
            simulation=simulation,
            actor='export-bot',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert exported['ok'] is True
        lock_path = Path(exported['escrow']['lock_path'])
        assert lock_path.exists()

        reconciled = scheduler.reconcile_runtime_alert_governance_baseline_promotion_simulation_evidence_custody(
            app.state.gw,
            promotion_id=promotion_id,
            actor='auditor',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert reconciled['ok'] is True
        assert reconciled['reconciliation']['summary']['overall_status'] == 'aligned'
        assert reconciled['simulation_evidence_reconciliation']['history']['summary']['count'] == 1

        lock_path.unlink()
        drifted = scheduler.reconcile_runtime_alert_governance_baseline_promotion_simulation_evidence_custody(
            app.state.gw,
            promotion_id=promotion_id,
            actor='auditor',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert drifted['ok'] is True
        item = drifted['reconciliation']['items'][0]
        assert drifted['reconciliation']['summary']['overall_status'] == 'drifted'
        assert 'immutable_lock_inactive' in item['drift_reasons']
        assert item['escrow']['status'] == 'object_lock_invalid'
        detail = scheduler.get_runtime_alert_governance_baseline_promotion(
            app.state.gw,
            promotion_id=promotion_id,
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert detail['simulation_evidence_reconciliation']['current']['summary']['overall_status'] == 'drifted'
        assert detail['simulation_evidence_reconciliation']['history']['summary']['count'] == 2


def test_baseline_promotion_simulation_custody_monitoring_job_alerts_and_blocks_on_drift(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_780_000.0
    _set_now(monkeypatch, base_now)
    escrow_dir = tmp_path / 'escrow'
    monkeypatch.setenv('OPENMIURA_BASELINE_ESCROW_ROOT', str(escrow_dir))
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    scheduler = OpenClawRecoverySchedulerService()
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        promotion_policy = {
            'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'gov', 'requested_role': 'governance-board', 'label': 'Governance board'}]},
            'simulation_review_policy': {
                'mode': 'parallel',
                'layers': [
                    {'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'},
                    {'layer_id': 'risk', 'requested_role': 'risk-manager', 'label': 'Risk manager'},
                ],
                'allow_self_review': False,
                'block_on_rejection': True,
            },
            'simulation_custody_monitoring_policy': {
                'enabled': True,
                'auto_schedule': True,
                'interval_s': 300,
                'notify_on_drift': True,
                'notify_on_recovery': True,
                'block_on_drift': True,
                'target_path': '/ui/?tab=operator&view=baseline-promotions',
            },
        }
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='baseline-sim-custody-monitoring-catalog',
            version='catalog-v1',
            environment_policy_baselines={
                'prod': {
                    'operational_tier': 'prod',
                    'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'}]},
                    'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v1'},
                    'escrow_policy': {'enabled': True, 'provider': 'filesystem-object-lock', 'classification': 'baseline-evidence'},
                },
            },
            promotion_policy=promotion_policy,
        )
        runtime_id = _create_runtime_for_environment(client, headers, name='runtime-sim-custody-monitoring', environment='prod')
        _create_portfolio_with_catalog(
            client,
            headers,
            base_now=base_now + 1,
            runtime_id=runtime_id,
            environment='prod',
            environment_tier_policies={
                'prod': {
                    'operational_tier': 'prod',
                    'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'}]},
                    'security_gate_policy': {'enabled': True, 'required_approval_roles': ['ops-director']},
                },
            },
            baseline_catalog_ref={'catalog_id': catalog['catalog_id']},
        )
        promotion = client.post(
            f'/admin/openclaw/alert-governance/baseline-catalogs/{catalog["catalog_id"]}/promotions',
            headers=headers,
            json={
                'actor': 'catalog-admin',
                'version': 'catalog-v2',
                'environment_policy_baselines': {
                    'prod': {
                        'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v2'},
                        'escrow_policy': {'enabled': True, 'provider': 'filesystem-object-lock', 'classification': 'baseline-evidence'},
                    },
                },
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert promotion.status_code == 200, promotion.text
        promotion_id = promotion.json()['promotion_id']
        simulated = scheduler.simulate_existing_runtime_alert_governance_baseline_promotion(
            app.state.gw,
            promotion_id=promotion_id,
            actor='operator-a',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert simulated['ok'] is True
        simulation = simulated
        simulation = scheduler.review_runtime_alert_governance_baseline_promotion_simulation(
            app.state.gw,
            simulation=simulation,
            actor='ops-director',
            decision='approve',
            reason='ops approved',
            layer_id='ops',
            requested_role='ops-director',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )['simulation']
        simulation = scheduler.review_runtime_alert_governance_baseline_promotion_simulation(
            app.state.gw,
            simulation=simulation,
            actor='risk-manager',
            decision='approve',
            reason='risk approved',
            layer_id='risk',
            requested_role='risk-manager',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )['simulation']
        exported = scheduler.export_runtime_alert_governance_baseline_promotion_simulation_evidence_package(
            app.state.gw,
            actor='auditor',
            simulation=simulation,
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert exported['ok'] is True
        assert exported['custody_job']['job_id']
        detail = scheduler.get_runtime_alert_governance_baseline_promotion(
            app.state.gw,
            promotion_id=promotion_id,
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert detail['simulation_custody_monitoring']['jobs']['summary']['count'] == 1
        lock_path = Path(exported['escrow']['lock_path'])
        assert lock_path.exists()
        lock_path.unlink()
        app.state.gw.audit.update_job_schedule(
            exported['custody_job']['job_id'],
            next_run_at=1.0,
            not_before=1.0,
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        executed = scheduler.run_due_baseline_promotion_simulation_custody_jobs(
            app.state.gw,
            actor='monitor-bot',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert executed['summary']['executed'] == 1
        result = executed['items'][0]['result']
        assert result['reconciliation']['summary']['overall_status'] == 'drifted'
        assert result['custody_monitoring']['guard']['blocked'] is True
        assert result['custody_monitoring']['guard']['reason'] == 'baseline_promotion_simulation_custody_drift_detected'
        notifications = app.state.gw.audit.list_app_notifications(tenant_id='tenant-a', workspace_id='ws-a', environment='prod')
        assert notifications
        assert notifications[0]['metadata']['kind'] == 'baseline_promotion_simulation_custody_drift'
        assert notifications[0]['metadata']['promotion_id'] == promotion_id
        detail = scheduler.get_runtime_alert_governance_baseline_promotion(
            app.state.gw,
            promotion_id=promotion_id,
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert detail['simulation_custody_monitoring']['guard']['blocked'] is True
        assert detail['simulation_custody_monitoring']['alerts']['summary']['active_count'] >= 1
        blocked = scheduler.decide_runtime_alert_governance_baseline_promotion(
            app.state.gw,
            promotion_id=promotion_id,
            actor='governance-board',
            decision='approve',
            reason='approve after drift',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert blocked['ok'] is False
        assert blocked['error'] == 'baseline_promotion_simulation_custody_guard_blocked'


def test_baseline_promotion_simulation_custody_dashboard_and_alert_lifecycle(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_782_000.0
    _set_now(monkeypatch, base_now)
    escrow_dir = tmp_path / 'escrow'
    monkeypatch.setenv('OPENMIURA_BASELINE_ESCROW_ROOT', str(escrow_dir))
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    scheduler = OpenClawRecoverySchedulerService()
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        promotion_policy = {
            'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'gov', 'requested_role': 'governance-board', 'label': 'Governance board'}]},
            'simulation_review_policy': {
                'mode': 'parallel',
                'layers': [
                    {'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'},
                    {'layer_id': 'risk', 'requested_role': 'risk-manager', 'label': 'Risk manager'},
                ],
                'allow_self_review': False,
                'block_on_rejection': True,
            },
            'simulation_custody_monitoring_policy': {
                'enabled': True,
                'auto_schedule': True,
                'interval_s': 300,
                'notify_on_drift': True,
                'notify_on_recovery': True,
                'block_on_drift': True,
                'target_path': '/ui/?tab=operator&view=baseline-promotions',
                'default_mute_s': 900,
            },
        }
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='baseline-sim-custody-dashboard-catalog',
            version='catalog-v1',
            environment_policy_baselines={
                'prod': {
                    'operational_tier': 'prod',
                    'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'}]},
                    'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v1'},
                    'escrow_policy': {'enabled': True, 'provider': 'filesystem-object-lock', 'classification': 'baseline-evidence'},
                },
            },
            promotion_policy=promotion_policy,
        )
        runtime_id = _create_runtime_for_environment(client, headers, name='runtime-sim-custody-dashboard', environment='prod')
        _create_portfolio_with_catalog(
            client,
            headers,
            base_now=base_now + 1,
            runtime_id=runtime_id,
            environment='prod',
            environment_tier_policies={
                'prod': {
                    'operational_tier': 'prod',
                    'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'}]},
                    'security_gate_policy': {'enabled': True, 'required_approval_roles': ['ops-director']},
                },
            },
            baseline_catalog_ref={'catalog_id': catalog['catalog_id']},
        )
        promotion = client.post(
            f'/admin/openclaw/alert-governance/baseline-catalogs/{catalog["catalog_id"]}/promotions',
            headers=headers,
            json={
                'actor': 'catalog-admin',
                'version': 'catalog-v2',
                'environment_policy_baselines': {
                    'prod': {
                        'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v2'},
                        'escrow_policy': {'enabled': True, 'provider': 'filesystem-object-lock', 'classification': 'baseline-evidence'},
                    },
                },
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert promotion.status_code == 200, promotion.text
        promotion_id = promotion.json()['promotion_id']
        simulation = scheduler.simulate_existing_runtime_alert_governance_baseline_promotion(
            app.state.gw,
            promotion_id=promotion_id,
            actor='operator-a',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        simulation = scheduler.review_runtime_alert_governance_baseline_promotion_simulation(
            app.state.gw,
            simulation=simulation,
            actor='ops-director',
            decision='approve',
            reason='ops approved',
            layer_id='ops',
            requested_role='ops-director',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )['simulation']
        simulation = scheduler.review_runtime_alert_governance_baseline_promotion_simulation(
            app.state.gw,
            simulation=simulation,
            actor='risk-manager',
            decision='approve',
            reason='risk approved',
            layer_id='risk',
            requested_role='risk-manager',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )['simulation']
        exported = scheduler.export_runtime_alert_governance_baseline_promotion_simulation_evidence_package(
            app.state.gw,
            actor='auditor',
            simulation=simulation,
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert exported['ok'] is True
        lock_path = Path(exported['escrow']['lock_path'])
        assert lock_path.exists()
        lock_path.unlink()
        app.state.gw.audit.update_job_schedule(
            exported['custody_job']['job_id'],
            next_run_at=1.0,
            not_before=1.0,
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        executed = scheduler.run_due_baseline_promotion_simulation_custody_jobs(
            app.state.gw,
            actor='monitor-bot',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert executed['summary']['executed'] == 1
        dashboard = scheduler.get_runtime_alert_governance_baseline_simulation_custody_dashboard(
            app.state.gw,
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert dashboard['summary']['promotion_count'] == 1
        assert dashboard['summary']['blocked_count'] == 1
        assert dashboard['summary']['active_alert_count'] == 1
        assert dashboard['summary']['open_alert_count'] == 1
        alert_id = dashboard['items'][0]['alerts']['items'][0]['alert_id']
        acknowledged = scheduler.update_runtime_alert_governance_baseline_promotion_simulation_custody_alert(
            app.state.gw,
            promotion_id=promotion_id,
            actor='shift-lead',
            action='acknowledge',
            alert_id=alert_id,
            reason='triaged by operations',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert acknowledged['ok'] is True
        assert acknowledged['simulation_custody_monitoring']['alerts']['summary']['acknowledged_count'] == 1
        muted = scheduler.update_runtime_alert_governance_baseline_promotion_simulation_custody_alert(
            app.state.gw,
            promotion_id=promotion_id,
            actor='shift-lead',
            action='mute',
            alert_id=alert_id,
            reason='mute while escrow is being repaired',
            mute_for_s=600,
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert muted['ok'] is True
        assert muted['alert']['status'] == 'muted'
        dashboard = scheduler.get_runtime_alert_governance_baseline_simulation_custody_dashboard(
            app.state.gw,
            only_active=True,
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert dashboard['summary']['active_alert_count'] == 1
        assert dashboard['summary']['muted_alert_count'] == 1
        resolve_while_drifted = scheduler.update_runtime_alert_governance_baseline_promotion_simulation_custody_alert(
            app.state.gw,
            promotion_id=promotion_id,
            actor='shift-lead',
            action='resolve',
            alert_id=alert_id,
            reason='should still be blocked',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert resolve_while_drifted['ok'] is False
        assert resolve_while_drifted['error'] == 'baseline_promotion_simulation_custody_alert_still_drifted'
        lock_payload = {
            'lock_type': 'openmiura_baseline_promotion_simulation_object_lock_v1',
            'provider': str(exported['escrow']['provider'] or ''),
            'archive_path': str(exported['escrow']['archive_path'] or ''),
            'artifact_sha256': str(exported['artifact']['sha256'] or ''),
            'package_id': str(exported['package_id'] or ''),
            'promotion_id': promotion_id,
            'simulation_id': str(simulation.get('simulation_id') or ''),
            'immutable_until': exported['escrow']['immutable_until'],
            'retention_mode': str(exported['escrow']['retention_mode'] or ''),
            'legal_hold': bool(exported['escrow']['legal_hold']),
            'locked_at': exported['escrow']['archived_at'],
        }
        lock_path.write_text(json.dumps(lock_payload), encoding='utf-8')
        reconciled = scheduler.reconcile_runtime_alert_governance_baseline_promotion_simulation_evidence_custody(
            app.state.gw,
            promotion_id=promotion_id,
            actor='monitor-bot',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert reconciled['ok'] is True
        assert reconciled['reconciliation']['summary']['overall_status'] == 'aligned'
        dashboard = scheduler.get_runtime_alert_governance_baseline_simulation_custody_dashboard(
            app.state.gw,
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert dashboard['summary']['active_alert_count'] == 0
        assert dashboard['summary']['recovered_alert_count'] >= 1
        detail = scheduler.get_runtime_alert_governance_baseline_promotion(
            app.state.gw,
            promotion_id=promotion_id,
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert detail['simulation_custody_monitoring']['alerts']['summary']['recovered_count'] >= 1


def test_baseline_promotion_simulation_custody_escalation_and_suppression_policies(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_783_500.0
    _set_now(monkeypatch, base_now)
    monkeypatch.setenv('OPENMIURA_BASELINE_ESCROW_ROOT', str(tmp_path / 'escrow'))
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    scheduler = OpenClawRecoverySchedulerService()
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        promotion_policy = {
            'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'gov', 'requested_role': 'governance-board', 'label': 'Governance board'}]},
            'simulation_review_policy': {
                'mode': 'parallel',
                'layers': [
                    {'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'},
                    {'layer_id': 'risk', 'requested_role': 'risk-manager', 'label': 'Risk manager'},
                ],
                'allow_self_review': False,
                'block_on_rejection': True,
            },
            'simulation_custody_monitoring_policy': {
                'enabled': True,
                'auto_schedule': True,
                'interval_s': 300,
                'notify_on_drift': True,
                'notify_on_recovery': True,
                'notify_on_escalation': True,
                'block_on_drift': True,
                'target_path': '/ui/?tab=operator&view=baseline-promotions',
                'default_mute_s': 900,
                'suppression_window_s': 0,
                'escalation_enabled': True,
                'escalation_levels': [
                    {'after_s': 60, 'severity': 'high', 'label': 'Ops escalation'},
                    {'after_s': 120, 'severity': 'critical', 'label': 'Critical escalation'},
                ],
                'suppress_while_muted': True,
            },
        }
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='baseline-sim-custody-escalation-catalog',
            version='catalog-v1',
            environment_policy_baselines={
                'prod': {
                    'operational_tier': 'prod',
                    'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'}]},
                    'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v1'},
                    'escrow_policy': {'enabled': True, 'provider': 'filesystem-object-lock', 'classification': 'baseline-evidence'},
                },
            },
            promotion_policy=promotion_policy,
        )
        runtime_id = _create_runtime_for_environment(client, headers, name='runtime-sim-custody-escalation', environment='prod')
        _create_portfolio_with_catalog(
            client,
            headers,
            base_now=base_now + 1,
            runtime_id=runtime_id,
            environment='prod',
            environment_tier_policies={
                'prod': {
                    'operational_tier': 'prod',
                    'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'}]},
                    'security_gate_policy': {'enabled': True, 'required_approval_roles': ['ops-director']},
                },
            },
            baseline_catalog_ref={'catalog_id': catalog['catalog_id']},
        )
        promotion = client.post(
            f'/admin/openclaw/alert-governance/baseline-catalogs/{catalog["catalog_id"]}/promotions',
            headers=headers,
            json={
                'actor': 'catalog-admin',
                'version': 'catalog-v2',
                'environment_policy_baselines': {
                    'prod': {
                        'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v2'},
                        'escrow_policy': {'enabled': True, 'provider': 'filesystem-object-lock', 'classification': 'baseline-evidence'},
                    },
                },
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert promotion.status_code == 200, promotion.text
        promotion_id = promotion.json()['promotion_id']
        simulation = scheduler.simulate_existing_runtime_alert_governance_baseline_promotion(
            app.state.gw,
            promotion_id=promotion_id,
            actor='operator-a',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        simulation = scheduler.review_runtime_alert_governance_baseline_promotion_simulation(
            app.state.gw,
            simulation=simulation,
            actor='ops-director',
            decision='approve',
            reason='ops approved',
            layer_id='ops',
            requested_role='ops-director',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )['simulation']
        simulation = scheduler.review_runtime_alert_governance_baseline_promotion_simulation(
            app.state.gw,
            simulation=simulation,
            actor='risk-manager',
            decision='approve',
            reason='risk approved',
            layer_id='risk',
            requested_role='risk-manager',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )['simulation']
        exported = scheduler.export_runtime_alert_governance_baseline_promotion_simulation_evidence_package(
            app.state.gw,
            actor='auditor',
            simulation=simulation,
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert exported['ok'] is True
        Path(exported['escrow']['lock_path']).unlink()

        first_reconcile = scheduler.reconcile_runtime_alert_governance_baseline_promotion_simulation_evidence_custody(
            app.state.gw,
            promotion_id=promotion_id,
            actor='monitor-bot',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert first_reconcile['ok'] is True
        detail = scheduler.get_runtime_alert_governance_baseline_promotion(
            app.state.gw,
            promotion_id=promotion_id,
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        alert = detail['simulation_custody_monitoring']['alerts']['items'][0]
        assert alert['escalation_count'] == 0

        _set_now(monkeypatch, base_now + 90)
        second_reconcile = scheduler.reconcile_runtime_alert_governance_baseline_promotion_simulation_evidence_custody(
            app.state.gw,
            promotion_id=promotion_id,
            actor='monitor-bot',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert second_reconcile['ok'] is True
        dashboard = scheduler.get_runtime_alert_governance_baseline_simulation_custody_dashboard(
            app.state.gw,
            only_escalated=True,
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert dashboard['summary']['promotion_count'] == 1
        assert dashboard['summary']['active_escalated_alert_count'] == 1
        detail = scheduler.get_runtime_alert_governance_baseline_promotion(
            app.state.gw,
            promotion_id=promotion_id,
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        alert = detail['simulation_custody_monitoring']['alerts']['items'][0]
        assert alert['escalation_level'] == 1
        assert alert['escalation_count'] == 1
        assert alert['severity'] == 'high'

        muted = scheduler.update_runtime_alert_governance_baseline_promotion_simulation_custody_alert(
            app.state.gw,
            promotion_id=promotion_id,
            actor='shift-lead',
            action='mute',
            reason='waiting for escrow remediation',
            mute_for_s=600,
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert muted['ok'] is True
        assert muted['alert']['status'] == 'muted'

        _set_now(monkeypatch, base_now + 150)
        muted_reconcile = scheduler.reconcile_runtime_alert_governance_baseline_promotion_simulation_evidence_custody(
            app.state.gw,
            promotion_id=promotion_id,
            actor='monitor-bot',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert muted_reconcile['ok'] is True
        suppressed_dashboard = scheduler.get_runtime_alert_governance_baseline_simulation_custody_dashboard(
            app.state.gw,
            only_suppressed=True,
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert suppressed_dashboard['summary']['promotion_count'] == 1
        assert suppressed_dashboard['summary']['active_suppressed_alert_count'] == 1
        detail = scheduler.get_runtime_alert_governance_baseline_promotion(
            app.state.gw,
            promotion_id=promotion_id,
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        alert = detail['simulation_custody_monitoring']['alerts']['items'][0]
        assert alert['suppression_state']['suppressed'] is True
        assert 'muted' in alert['suppression_state']['reasons']
        assert alert['suppression_state']['pending_escalation_level'] == 2
        assert alert['escalation_count'] == 1

        unmuted = scheduler.update_runtime_alert_governance_baseline_promotion_simulation_custody_alert(
            app.state.gw,
            promotion_id=promotion_id,
            actor='shift-lead',
            action='unmute',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert unmuted['ok'] is True
        final_reconcile = scheduler.reconcile_runtime_alert_governance_baseline_promotion_simulation_evidence_custody(
            app.state.gw,
            promotion_id=promotion_id,
            actor='monitor-bot',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert final_reconcile['ok'] is True
        detail = scheduler.get_runtime_alert_governance_baseline_promotion(
            app.state.gw,
            promotion_id=promotion_id,
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        alert = detail['simulation_custody_monitoring']['alerts']['items'][0]
        assert alert['escalation_level'] == 2
        assert alert['escalation_count'] == 2
        assert alert['severity'] == 'critical'
        notifications = app.state.gw.audit.list_app_notifications(tenant_id='tenant-a', workspace_id='ws-a', environment='prod')
        assert any((item.get('metadata') or {}).get('kind') == 'baseline_promotion_simulation_custody_escalated' for item in notifications)



def test_baseline_promotion_simulation_custody_alert_ownership_and_routing(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_784_000.0
    _set_now(monkeypatch, base_now)
    escrow_dir = tmp_path / 'escrow'
    monkeypatch.setenv('OPENMIURA_BASELINE_ESCROW_ROOT', str(escrow_dir))
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    scheduler = OpenClawRecoverySchedulerService()
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        promotion_policy = {
            'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'gov', 'requested_role': 'governance-board', 'label': 'Governance board'}]},
            'simulation_review_policy': {
                'mode': 'parallel',
                'layers': [
                    {'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'},
                    {'layer_id': 'risk', 'requested_role': 'risk-manager', 'label': 'Risk manager'},
                ],
                'allow_self_review': False,
            },
            'simulation_custody_monitoring_policy': {
                'enabled': True,
                'auto_schedule': True,
                'interval_s': 300,
                'notify_on_drift': True,
                'notify_on_recovery': True,
                'notify_on_escalation': True,
                'block_on_drift': True,
                'target_path': '/ui/?tab=operator&view=baseline-promotions',
                'default_route': {
                    'route_id': 'ops-triage',
                    'label': 'Ops triage',
                    'queue_id': 'ops-oncall',
                    'queue_label': 'Ops On-call',
                    'owner_role': 'shift-lead',
                },
                'routing_routes': [
                    {
                        'route_id': 'sev1-ops-command',
                        'label': 'Ops command',
                        'min_escalation_level': 1,
                        'queue_id': 'ops-command',
                        'queue_label': 'Ops Command',
                        'owner_role': 'ops-manager',
                    },
                ],
                'escalation_enabled': True,
                'escalation_levels': [
                    {
                        'after_s': 60,
                        'severity': 'high',
                        'label': 'Ops escalation',
                        'route_id': 'sev1-ops-command',
                        'queue_id': 'ops-command',
                        'queue_label': 'Ops Command',
                        'owner_role': 'ops-manager',
                    },
                ],
            },
        }
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='baseline-sim-custody-ownership-catalog',
            version='catalog-v1',
            environment_policy_baselines={
                'prod': {
                    'operational_tier': 'prod',
                    'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'}]},
                    'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v1'},
                    'escrow_policy': {'enabled': True, 'provider': 'filesystem-object-lock', 'classification': 'baseline-evidence'},
                },
            },
            promotion_policy=promotion_policy,
        )
        runtime_id = _create_runtime_for_environment(client, headers, name='runtime-sim-custody-ownership', environment='prod')
        _create_portfolio_with_catalog(
            client,
            headers,
            base_now=base_now + 1,
            runtime_id=runtime_id,
            environment='prod',
            environment_tier_policies={
                'prod': {
                    'operational_tier': 'prod',
                    'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'}]},
                    'security_gate_policy': {'enabled': True, 'required_approval_roles': ['ops-director']},
                },
            },
            baseline_catalog_ref={'catalog_id': catalog['catalog_id']},
        )
        promotion = client.post(
            f'/admin/openclaw/alert-governance/baseline-catalogs/{catalog["catalog_id"]}/promotions',
            headers=headers,
            json={
                'actor': 'catalog-admin',
                'version': 'catalog-v2',
                'environment_policy_baselines': {
                    'prod': {
                        'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v2'},
                        'escrow_policy': {'enabled': True, 'provider': 'filesystem-object-lock', 'classification': 'baseline-evidence'},
                    },
                },
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        promotion_id = promotion.json()['promotion_id']
        simulation = scheduler.simulate_existing_runtime_alert_governance_baseline_promotion(
            app.state.gw,
            promotion_id=promotion_id,
            actor='operator-a',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        simulation = scheduler.review_runtime_alert_governance_baseline_promotion_simulation(
            app.state.gw,
            simulation=simulation,
            actor='ops-director',
            decision='approve',
            reason='ops approved',
            layer_id='ops',
            requested_role='ops-director',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )['simulation']
        simulation = scheduler.review_runtime_alert_governance_baseline_promotion_simulation(
            app.state.gw,
            simulation=simulation,
            actor='risk-manager',
            decision='approve',
            reason='risk approved',
            layer_id='risk',
            requested_role='risk-manager',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )['simulation']
        exported = scheduler.export_runtime_alert_governance_baseline_promotion_simulation_evidence_package(
            app.state.gw,
            actor='auditor',
            simulation=simulation,
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        Path(exported['escrow']['lock_path']).unlink()
        first_reconcile = scheduler.reconcile_runtime_alert_governance_baseline_promotion_simulation_evidence_custody(
            app.state.gw,
            promotion_id=promotion_id,
            actor='monitor-bot',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert first_reconcile['ok'] is True
        detail = scheduler.get_runtime_alert_governance_baseline_promotion(
            app.state.gw,
            promotion_id=promotion_id,
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        alert = detail['simulation_custody_monitoring']['alerts']['items'][0]
        assert alert['ownership']['status'] == 'queued'
        assert alert['ownership']['owner_role'] == 'shift-lead'
        assert alert['ownership']['queue_id'] == 'ops-oncall'
        assert alert['routing']['route_id'] == 'ops-triage'

        claimed = scheduler.update_runtime_alert_governance_baseline_promotion_simulation_custody_alert(
            app.state.gw,
            promotion_id=promotion_id,
            actor='shift-lead',
            action='claim',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert claimed['ok'] is True
        assert claimed['alert']['ownership']['owner_id'] == 'shift-lead'
        dashboard_claimed = scheduler.get_runtime_alert_governance_baseline_simulation_custody_dashboard(
            app.state.gw,
            only_claimed=True,
            owner_id='shift-lead',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert dashboard_claimed['summary']['promotion_count'] == 1
        assert dashboard_claimed['summary']['active_claimed_alert_count'] == 1

        _set_now(monkeypatch, base_now + 90)
        second_reconcile = scheduler.reconcile_runtime_alert_governance_baseline_promotion_simulation_evidence_custody(
            app.state.gw,
            promotion_id=promotion_id,
            actor='monitor-bot',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert second_reconcile['ok'] is True
        detail = scheduler.get_runtime_alert_governance_baseline_promotion(
            app.state.gw,
            promotion_id=promotion_id,
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        alert = detail['simulation_custody_monitoring']['alerts']['items'][0]
        assert alert['routing']['route_id'] == 'sev1-ops-command'
        assert alert['routing']['queue_id'] == 'ops-command'
        assert alert['routing']['owner_role'] == 'ops-manager'
        assert alert['ownership']['owner_id'] == 'shift-lead'

        rerouted = scheduler.update_runtime_alert_governance_baseline_promotion_simulation_custody_alert(
            app.state.gw,
            promotion_id=promotion_id,
            actor='shift-lead',
            action='reroute',
            queue_id='risk-review',
            queue_label='Risk Review',
            owner_role='risk-reviewer',
            route_id='manual-risk-review',
            route_label='Manual risk review',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert rerouted['ok'] is True
        assert rerouted['alert']['routing']['queue_id'] == 'risk-review'
        assert rerouted['alert']['routing']['route_id'] == 'manual-risk-review'
        assert rerouted['alert']['ownership']['queue_id'] == 'risk-review'

        released = scheduler.update_runtime_alert_governance_baseline_promotion_simulation_custody_alert(
            app.state.gw,
            promotion_id=promotion_id,
            actor='shift-lead',
            action='release',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert released['ok'] is True
        assert released['alert']['ownership']['owner_id'] == ''
        assert released['alert']['ownership']['status'] == 'queued'
        dashboard_unowned = scheduler.get_runtime_alert_governance_baseline_simulation_custody_dashboard(
            app.state.gw,
            only_unowned=True,
            queue_id='risk-review',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert dashboard_unowned['summary']['promotion_count'] == 1
        assert dashboard_unowned['summary']['active_unowned_alert_count'] == 1



def test_baseline_promotion_simulation_custody_alert_handoff_and_sla_tracking(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_785_000.0
    _set_now(monkeypatch, base_now)
    escrow_dir = tmp_path / 'escrow'
    monkeypatch.setenv('OPENMIURA_BASELINE_ESCROW_ROOT', str(escrow_dir))
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    scheduler = OpenClawRecoverySchedulerService()
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        promotion_policy = {
            'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'gov', 'requested_role': 'governance-board', 'label': 'Governance board'}]},
            'simulation_review_policy': {
                'mode': 'parallel',
                'layers': [
                    {'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'},
                    {'layer_id': 'risk', 'requested_role': 'risk-manager', 'label': 'Risk manager'},
                ],
                'allow_self_review': False,
            },
            'simulation_custody_monitoring_policy': {
                'enabled': True,
                'auto_schedule': True,
                'interval_s': 300,
                'notify_on_drift': True,
                'notify_on_recovery': True,
                'block_on_drift': True,
                'target_path': '/ui/?tab=operator&view=baseline-promotions',
                'default_route': {
                    'route_id': 'ops-triage',
                    'label': 'Ops triage',
                    'queue_id': 'ops-oncall',
                    'queue_label': 'Ops On-call',
                    'owner_role': 'shift-lead',
                },
                'routing_routes': [
                    {
                        'route_id': 'risk-review-route',
                        'label': 'Risk review',
                        'queue_id': 'risk-review',
                        'queue_label': 'Risk Review',
                        'owner_role': 'risk-reviewer',
                    },
                ],
                'handoff_enabled': True,
                'handoff_require_reason': True,
                'sla_policy': {
                    'enabled': True,
                    'acknowledge_s': 30,
                    'claim_s': 30,
                    'resolve_s': 300,
                    'handoff_accept_s': 20,
                    'notify_on_breach': True,
                },
            },
        }
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='baseline-sim-custody-handoff-catalog',
            version='catalog-v1',
            environment_policy_baselines={
                'prod': {
                    'operational_tier': 'prod',
                    'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'}]},
                    'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v1'},
                    'escrow_policy': {'enabled': True, 'provider': 'filesystem-object-lock', 'classification': 'baseline-evidence'},
                },
            },
            promotion_policy=promotion_policy,
        )
        runtime_id = _create_runtime_for_environment(client, headers, name='runtime-sim-custody-handoff', environment='prod')
        _create_portfolio_with_catalog(
            client,
            headers,
            base_now=base_now + 1,
            runtime_id=runtime_id,
            environment='prod',
            environment_tier_policies={
                'prod': {
                    'operational_tier': 'prod',
                    'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'}]},
                    'security_gate_policy': {'enabled': True, 'required_approval_roles': ['ops-director']},
                },
            },
            baseline_catalog_ref={'catalog_id': catalog['catalog_id']},
        )
        promotion = client.post(
            f'/admin/openclaw/alert-governance/baseline-catalogs/{catalog["catalog_id"]}/promotions',
            headers=headers,
            json={
                'actor': 'catalog-admin',
                'version': 'catalog-v2',
                'environment_policy_baselines': {
                    'prod': {
                        'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v2'},
                        'escrow_policy': {'enabled': True, 'provider': 'filesystem-object-lock', 'classification': 'baseline-evidence'},
                    },
                },
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        promotion_id = promotion.json()['promotion_id']
        simulation = scheduler.simulate_existing_runtime_alert_governance_baseline_promotion(
            app.state.gw,
            promotion_id=promotion_id,
            actor='operator-a',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        simulation = scheduler.review_runtime_alert_governance_baseline_promotion_simulation(
            app.state.gw,
            simulation=simulation,
            actor='ops-director',
            decision='approve',
            reason='ops approved',
            layer_id='ops',
            requested_role='ops-director',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )['simulation']
        simulation = scheduler.review_runtime_alert_governance_baseline_promotion_simulation(
            app.state.gw,
            simulation=simulation,
            actor='risk-manager',
            decision='approve',
            reason='risk approved',
            layer_id='risk',
            requested_role='risk-manager',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )['simulation']
        exported = scheduler.export_runtime_alert_governance_baseline_promotion_simulation_evidence_package(
            app.state.gw,
            actor='auditor',
            simulation=simulation,
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        Path(exported['escrow']['lock_path']).unlink()
        first_reconcile = scheduler.reconcile_runtime_alert_governance_baseline_promotion_simulation_evidence_custody(
            app.state.gw,
            promotion_id=promotion_id,
            actor='monitor-bot',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert first_reconcile['ok'] is True

        _set_now(monkeypatch, base_now + 5)
        claimed = scheduler.update_runtime_alert_governance_baseline_promotion_simulation_custody_alert(
            app.state.gw,
            promotion_id=promotion_id,
            actor='shift-lead',
            action='claim',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert claimed['ok'] is True

        _set_now(monkeypatch, base_now + 10)
        handed_off = scheduler.update_runtime_alert_governance_baseline_promotion_simulation_custody_alert(
            app.state.gw,
            promotion_id=promotion_id,
            actor='shift-lead',
            action='handoff',
            reason='shift handoff to risk',
            owner_id='risk-reviewer',
            owner_role='risk-reviewer',
            queue_id='risk-review',
            queue_label='Risk Review',
            route_id='risk-review-route',
            route_label='Risk review',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert handed_off['ok'] is True
        assert handed_off['alert']['handoff']['pending'] is True
        assert handed_off['alert']['handoff']['pending_to_owner_id'] == 'risk-reviewer'
        dashboard_pending = scheduler.get_runtime_alert_governance_baseline_simulation_custody_dashboard(
            app.state.gw,
            only_handoff_pending=True,
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert dashboard_pending['summary']['promotion_count'] == 1
        assert dashboard_pending['summary']['handoff_pending_count'] == 1

        _set_now(monkeypatch, base_now + 40)
        second_reconcile = scheduler.reconcile_runtime_alert_governance_baseline_promotion_simulation_evidence_custody(
            app.state.gw,
            promotion_id=promotion_id,
            actor='monitor-bot',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert second_reconcile['ok'] is True
        detail = scheduler.get_runtime_alert_governance_baseline_promotion(
            app.state.gw,
            promotion_id=promotion_id,
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        alert = detail['simulation_custody_monitoring']['alerts']['items'][0]
        assert alert['sla']['breached'] is True
        assert 'handoff_accept' in alert['sla']['breached_targets']
        assert detail['simulation_custody_monitoring']['guard']['sla_breached'] is True
        dashboard_breached = scheduler.get_runtime_alert_governance_baseline_simulation_custody_dashboard(
            app.state.gw,
            only_sla_breached=True,
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert dashboard_breached['summary']['promotion_count'] == 1
        assert dashboard_breached['summary']['sla_breached_count'] == 1
        notifications = app.state.gw.audit.list_app_notifications(tenant_id='tenant-a', workspace_id='ws-a', environment='prod')
        assert any((item.get('metadata') or {}).get('kind') == 'baseline_promotion_simulation_custody_sla_breached' for item in notifications)

        accepted = scheduler.update_runtime_alert_governance_baseline_promotion_simulation_custody_alert(
            app.state.gw,
            promotion_id=promotion_id,
            actor='risk-reviewer',
            action='claim',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert accepted['ok'] is True
        assert accepted['alert']['handoff']['pending'] is False
        assert accepted['alert']['handoff']['accepted_by'] == 'risk-reviewer'
        assert 'handoff_accept' not in list(accepted['alert']['sla'].get('pending_targets') or [])
        dashboard_cleared = scheduler.get_runtime_alert_governance_baseline_simulation_custody_dashboard(
            app.state.gw,
            only_handoff_pending=True,
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert dashboard_cleared['summary']['promotion_count'] == 0


def test_baseline_promotion_simulation_custody_sla_auto_reroute_to_team_queue(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_786_000.0
    _set_now(monkeypatch, base_now)
    escrow_dir = tmp_path / 'escrow'
    monkeypatch.setenv('OPENMIURA_BASELINE_ESCROW_ROOT', str(escrow_dir))
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    scheduler = OpenClawRecoverySchedulerService()
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        promotion_policy = {
            'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'gov', 'requested_role': 'governance-board', 'label': 'Governance board'}]},
            'simulation_review_policy': {
                'mode': 'parallel',
                'layers': [
                    {'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'},
                    {'layer_id': 'risk', 'requested_role': 'risk-manager', 'label': 'Risk manager'},
                ],
                'allow_self_review': False,
            },
            'simulation_custody_monitoring_policy': {
                'enabled': True,
                'auto_schedule': True,
                'interval_s': 300,
                'notify_on_drift': True,
                'notify_on_recovery': True,
                'block_on_drift': True,
                'default_route': {
                    'route_id': 'ops-triage',
                    'label': 'Ops triage',
                    'queue_id': 'ops-oncall',
                    'queue_label': 'Ops On-call',
                    'owner_role': 'shift-lead',
                },
                'auto_reroute_on_sla_breach': True,
                'team_escalation_queues': [
                    {
                        'route_id': 'incident-command-route',
                        'label': 'Incident command',
                        'queue_id': 'incident-command',
                        'queue_label': 'Incident Command',
                        'owner_role': 'incident-commander',
                        'breach_targets': ['acknowledge', 'claim'],
                        'severity': 'high',
                    },
                ],
                'sla_policy': {
                    'enabled': True,
                    'acknowledge_s': 30,
                    'claim_s': 30,
                    'resolve_s': 300,
                    'notify_on_breach': True,
                    'severity': 'high',
                },
            },
        }
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='baseline-sim-custody-sla-reroute-catalog',
            version='catalog-v1',
            environment_policy_baselines={
                'prod': {
                    'operational_tier': 'prod',
                    'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'}]},
                    'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v1'},
                    'escrow_policy': {'enabled': True, 'provider': 'filesystem-object-lock', 'classification': 'baseline-evidence'},
                },
            },
            promotion_policy=promotion_policy,
        )
        runtime_id = _create_runtime_for_environment(client, headers, name='runtime-sim-custody-sla-reroute', environment='prod')
        _create_portfolio_with_catalog(
            client,
            headers,
            base_now=base_now + 1,
            runtime_id=runtime_id,
            environment='prod',
            environment_tier_policies={
                'prod': {
                    'operational_tier': 'prod',
                    'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'}]},
                    'security_gate_policy': {'enabled': True, 'required_approval_roles': ['ops-director']},
                },
            },
            baseline_catalog_ref={'catalog_id': catalog['catalog_id']},
        )
        promotion = client.post(
            f'/admin/openclaw/alert-governance/baseline-catalogs/{catalog["catalog_id"]}/promotions',
            headers=headers,
            json={
                'actor': 'catalog-admin',
                'version': 'catalog-v2',
                'environment_policy_baselines': {
                    'prod': {
                        'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v2'},
                        'escrow_policy': {'enabled': True, 'provider': 'filesystem-object-lock', 'classification': 'baseline-evidence'},
                    },
                },
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        promotion_id = promotion.json()['promotion_id']
        simulation = scheduler.simulate_existing_runtime_alert_governance_baseline_promotion(
            app.state.gw,
            promotion_id=promotion_id,
            actor='catalog-admin',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        simulation = scheduler.review_runtime_alert_governance_baseline_promotion_simulation(
            app.state.gw, simulation=simulation, actor='ops-director', decision='approve', reason='ops ok', layer_id='ops', tenant_id='tenant-a', workspace_id='ws-a', environment='prod'
        )['simulation']
        simulation = scheduler.review_runtime_alert_governance_baseline_promotion_simulation(
            app.state.gw, simulation=simulation, actor='risk-manager', decision='approve', reason='risk ok', layer_id='risk', tenant_id='tenant-a', workspace_id='ws-a', environment='prod'
        )['simulation']
        exported = scheduler.export_runtime_alert_governance_baseline_promotion_simulation_evidence_package(
            app.state.gw,
            simulation=simulation,
            actor='auditor',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        lock_path = Path(exported['escrow']['lock_path'])
        lock_path.unlink()
        first_reconcile = scheduler.reconcile_runtime_alert_governance_baseline_promotion_simulation_evidence_custody(
            app.state.gw,
            promotion_id=promotion_id,
            actor='monitor-bot',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert first_reconcile['ok'] is True
        _set_now(monkeypatch, base_now + 40)
        second_reconcile = scheduler.reconcile_runtime_alert_governance_baseline_promotion_simulation_evidence_custody(
            app.state.gw,
            promotion_id=promotion_id,
            actor='monitor-bot',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert second_reconcile['ok'] is True
        detail = scheduler.get_runtime_alert_governance_baseline_promotion(
            app.state.gw,
            promotion_id=promotion_id,
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        alert = detail['simulation_custody_monitoring']['alerts']['items'][0]
        assert alert['sla']['breached'] is True
        assert alert['routing']['source'] == 'sla_breach_routing'
        assert alert['routing']['queue_id'] == 'incident-command'
        assert alert['routing']['owner_role'] == 'incident-commander'
        assert alert['sla_routing_state']['reroute_count'] == 1
        assert detail['simulation_custody_monitoring']['guard']['sla_rerouted'] is True
        assert detail['simulation_custody_monitoring']['guard']['team_queue_id'] == 'incident-command'
        dashboard = scheduler.get_runtime_alert_governance_baseline_simulation_custody_dashboard(
            app.state.gw,
            only_sla_rerouted=True,
            team_queue_id='incident-command',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert dashboard['summary']['promotion_count'] == 1
        assert dashboard['summary']['sla_rerouted_count'] == 1
        assert dashboard['summary']['team_queue_alert_count'] == 1
        notifications = app.state.gw.audit.list_app_notifications(tenant_id='tenant-a', workspace_id='ws-a', environment='prod')
        assert any((item.get('metadata') or {}).get('kind') == 'baseline_promotion_simulation_custody_sla_rerouted' for item in notifications)


def test_baseline_promotion_simulation_custody_load_aware_queue_capacity_routes_to_less_loaded_queue(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_786_500.0
    _set_now(monkeypatch, base_now)
    monkeypatch.setenv('OPENMIURA_BASELINE_ESCROW_ROOT', str(tmp_path / 'escrow'))
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    scheduler = OpenClawRecoverySchedulerService()
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        promotion_policy = {
            'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'gov', 'requested_role': 'governance-board', 'label': 'Governance board'}]},
            'simulation_custody_monitoring_policy': {
                'enabled': True,
                'auto_schedule': True,
                'interval_s': 300,
                'notify_on_drift': True,
                'block_on_drift': True,
                'load_aware_routing_enabled': True,
                'queue_capacity_policy': {
                    'enabled': True,
                    'default_capacity': 1,
                    'prefer_lowest_load': True,
                    'rebalance_on_over_capacity': True,
                },
                'routing_routes': [
                    {
                        'route_id': 'ops-primary-route',
                        'label': 'Ops primary',
                        'queue_id': 'ops-primary',
                        'queue_label': 'Ops Primary',
                        'owner_role': 'shift-lead',
                        'queue_capacity': 1,
                        'severity': 'warning',
                    },
                    {
                        'route_id': 'ops-backup-route',
                        'label': 'Ops backup',
                        'queue_id': 'ops-backup',
                        'queue_label': 'Ops Backup',
                        'owner_role': 'shift-lead',
                        'queue_capacity': 2,
                        'severity': 'warning',
                    },
                ],
                'default_route': {
                    'route_id': 'ops-primary-route',
                    'label': 'Ops primary',
                    'queue_id': 'ops-primary',
                    'queue_label': 'Ops Primary',
                    'owner_role': 'shift-lead',
                    'queue_capacity': 1,
                },
                'queue_capacities': [
                    {'queue_id': 'ops-primary', 'queue_label': 'Ops Primary', 'capacity': 1},
                    {'queue_id': 'ops-backup', 'queue_label': 'Ops Backup', 'capacity': 2},
                ],
            },
        }
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='baseline-sim-custody-load-aware-catalog',
            version='catalog-v1',
            environment_policy_baselines={
                'prod': {
                    'operational_tier': 'prod',
                    'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'}]},
                    'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v1'},
                    'escrow_policy': {'enabled': True, 'provider': 'filesystem-object-lock', 'classification': 'baseline-evidence'},
                },
            },
            promotion_policy=promotion_policy,
        )
        runtime_id = _create_runtime_for_environment(client, headers, name='runtime-sim-custody-load-aware', environment='prod')
        _create_portfolio_with_catalog(
            client,
            headers,
            base_now=base_now + 1,
            runtime_id=runtime_id,
            environment='prod',
            environment_tier_policies={
                'prod': {
                    'operational_tier': 'prod',
                    'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'}]},
                    'security_gate_policy': {'enabled': True, 'required_approval_roles': ['ops-director']},
                },
            },
            baseline_catalog_ref={'catalog_id': catalog['catalog_id']},
        )

        def _create_drifted_promotion(version: str) -> str:
            response = client.post(
                f'/admin/openclaw/alert-governance/baseline-catalogs/{catalog["catalog_id"]}/promotions',
                headers=headers,
                json={
                    'actor': 'catalog-admin',
                    'version': version,
                    'environment_policy_baselines': {
                        'prod': {
                            'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': version},
                            'escrow_policy': {'enabled': True, 'provider': 'filesystem-object-lock', 'classification': 'baseline-evidence'},
                        },
                    },
                    'tenant_id': 'tenant-a',
                    'workspace_id': 'ws-a',
                    'environment': 'prod',
                },
            )
            promotion_id = response.json()['promotion_id']
            simulation = scheduler.simulate_existing_runtime_alert_governance_baseline_promotion(
                app.state.gw,
                promotion_id=promotion_id,
                actor='catalog-admin',
                tenant_id='tenant-a',
                workspace_id='ws-a',
                environment='prod',
            )
            exported = scheduler.export_runtime_alert_governance_baseline_promotion_simulation_evidence_package(
                app.state.gw,
                simulation=simulation,
                actor='auditor',
                tenant_id='tenant-a',
                workspace_id='ws-a',
                environment='prod',
            )
            Path(exported['escrow']['lock_path']).unlink()
            reconciled = scheduler.reconcile_runtime_alert_governance_baseline_promotion_simulation_evidence_custody(
                app.state.gw,
                promotion_id=promotion_id,
                actor='monitor-bot',
                tenant_id='tenant-a',
                workspace_id='ws-a',
                environment='prod',
            )
            assert reconciled['ok'] is True
            return promotion_id

        first_promotion_id = _create_drifted_promotion('catalog-v2')
        first_detail = scheduler.get_runtime_alert_governance_baseline_promotion(
            app.state.gw,
            promotion_id=first_promotion_id,
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        first_alert = first_detail['simulation_custody_monitoring']['alerts']['items'][0]
        assert first_alert['routing']['queue_id'] in {'ops-primary', 'ops-backup'}
        assert first_alert['routing']['load_aware'] is True

        second_promotion_id = _create_drifted_promotion('catalog-v3')
        second_detail = scheduler.get_runtime_alert_governance_baseline_promotion(
            app.state.gw,
            promotion_id=second_promotion_id,
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        second_alert = second_detail['simulation_custody_monitoring']['alerts']['items'][0]
        assert second_alert['routing']['queue_id'] in {'ops-primary', 'ops-backup'}
        assert second_alert['routing']['queue_id'] != first_alert['routing']['queue_id']
        assert second_alert['routing']['load_aware'] is True
        assert second_alert['routing']['selection_reason'] in {'empty_queue', 'lowest_load_queue'}
        assert second_detail['simulation_custody_monitoring']['guard']['load_aware_routing'] is True
        assert second_detail['simulation_custody_monitoring']['guard']['queue_id'] == second_alert['routing']['queue_id']
        assert second_detail['simulation_custody_monitoring']['queue_capacity']['summary']['saturated_count'] == 1

        dashboard = scheduler.get_runtime_alert_governance_baseline_simulation_custody_dashboard(
            app.state.gw,
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert dashboard['summary']['promotion_count'] == 2
        assert dashboard['summary']['queue_capacity']['queue_count'] >= 2
        assert dashboard['summary']['queue_capacity']['saturated_count'] == 1
        assert dashboard['summary']['queue_at_capacity_count'] >= 1
        assert dashboard['summary']['load_aware_routed_count'] >= 2
        assert dashboard['queue_capacity']['summary']['hottest_queue_id'] in {'ops-primary', 'ops-backup'}
        routed_queues = {item['active_alert']['routing']['queue_id'] for item in dashboard['items']}
        assert first_alert['routing']['queue_id'] in routed_queues
        assert second_alert['routing']['queue_id'] in routed_queues



def test_baseline_promotion_simulation_custody_route_selection_respects_reserved_capacity(monkeypatch) -> None:
    base_now = 1_785_786_700.0
    _set_now(monkeypatch, base_now)
    scheduler = OpenClawRecoverySchedulerService()
    queue_state = {
        'policy': {
            'anti_thrashing_enabled': False,
        },
        'queues': {
            'ops-primary': {
                'queue_id': 'ops-primary',
                'queue_label': 'Ops Primary',
                'capacity': 2,
                'warning_capacity': 1,
                'active_count': 1,
                'hard_limit': False,
                'load_weight': 1.0,
                'reservation_enabled': True,
                'reserved_capacity': 1,
                'general_capacity': 1,
                'general_available': 0,
                'reserved_available': 1,
                'reserved_for_severities': ['critical'],
                'reserved_for_queue_types': [],
            },
            'ops-backup': {
                'queue_id': 'ops-backup',
                'queue_label': 'Ops Backup',
                'capacity': 3,
                'warning_capacity': 2,
                'active_count': 2,
                'hard_limit': False,
                'load_weight': 1.0,
                'reservation_enabled': False,
                'reserved_capacity': 0,
                'general_capacity': 3,
                'general_available': 1,
                'reserved_available': 0,
                'reserved_for_severities': [],
                'reserved_for_queue_types': [],
            },
        },
    }
    routes = [
        {'route_id': 'ops-primary-route', 'label': 'Ops primary', 'queue_id': 'ops-primary', 'queue_label': 'Ops Primary', 'owner_role': 'shift-lead'},
        {'route_id': 'ops-backup-route', 'label': 'Ops backup', 'queue_id': 'ops-backup', 'queue_label': 'Ops Backup', 'owner_role': 'shift-lead'},
    ]

    warning_route = scheduler._select_baseline_promotion_simulation_custody_route_by_load(
        routes=routes,
        queue_state=queue_state,
        prefer_lowest_load=True,
        alert={'severity': 'warning', 'routing': {}},
        policy={'queue_capacity_policy': {'reservation_enabled': True}},
    )
    assert warning_route['queue_id'] == 'ops-backup'
    assert warning_route['reservation_eligible'] is False
    assert warning_route['reservation_applied'] is False
    assert warning_route['effective_capacity'] == 3

    critical_route = scheduler._select_baseline_promotion_simulation_custody_route_by_load(
        routes=routes,
        queue_state=queue_state,
        prefer_lowest_load=True,
        alert={'severity': 'critical', 'routing': {}},
        policy={'queue_capacity_policy': {'reservation_enabled': True}},
    )
    assert critical_route['queue_id'] == 'ops-primary'
    assert critical_route['reservation_eligible'] is True
    assert critical_route['reservation_applied'] is True
    assert critical_route['effective_capacity'] == 2



def test_baseline_promotion_simulation_custody_route_selection_applies_anti_thrashing(monkeypatch) -> None:
    base_now = 1_785_786_800.0
    _set_now(monkeypatch, base_now)
    scheduler = OpenClawRecoverySchedulerService()
    queue_state = {
        'policy': {
            'anti_thrashing_enabled': True,
            'reroute_cooldown_s': 300,
            'anti_thrashing_min_active_delta': 1,
            'anti_thrashing_min_load_delta': 0.25,
        },
        'queues': {
            'ops-primary': {
                'queue_id': 'ops-primary',
                'queue_label': 'Ops Primary',
                'capacity': 4,
                'warning_capacity': 3,
                'active_count': 2,
                'hard_limit': False,
                'load_weight': 1.0,
                'reservation_enabled': False,
                'reserved_capacity': 0,
                'general_capacity': 4,
                'general_available': 2,
                'reserved_available': 0,
                'reserved_for_severities': [],
                'reserved_for_queue_types': [],
            },
            'ops-backup': {
                'queue_id': 'ops-backup',
                'queue_label': 'Ops Backup',
                'capacity': 4,
                'warning_capacity': 3,
                'active_count': 1,
                'hard_limit': False,
                'load_weight': 1.0,
                'reservation_enabled': False,
                'reserved_capacity': 0,
                'general_capacity': 4,
                'general_available': 3,
                'reserved_available': 0,
                'reserved_for_severities': [],
                'reserved_for_queue_types': [],
            },
        },
    }
    route = scheduler._select_baseline_promotion_simulation_custody_route_by_load(
        routes=[
            {'route_id': 'ops-primary-route', 'label': 'Ops primary', 'queue_id': 'ops-primary', 'queue_label': 'Ops Primary', 'owner_role': 'shift-lead'},
            {'route_id': 'ops-backup-route', 'label': 'Ops backup', 'queue_id': 'ops-backup', 'queue_label': 'Ops Backup', 'owner_role': 'shift-lead'},
        ],
        queue_state=queue_state,
        current_queue_id='ops-primary',
        prefer_lowest_load=True,
        alert={'severity': 'warning', 'routing': {'queue_id': 'ops-primary', 'updated_at': base_now - 30}},
        policy={'queue_capacity_policy': {'anti_thrashing_enabled': True, 'reroute_cooldown_s': 300, 'anti_thrashing_min_active_delta': 1, 'anti_thrashing_min_load_delta': 0.25}},
    )
    assert route['queue_id'] == 'ops-primary'
    assert route['anti_thrashing_applied'] is True
    assert route['anti_thrashing_reason'] == 'reroute_cooldown_min_delta'
    assert route['selection_reason'].startswith('anti_thrashing_keep_')


def test_baseline_promotion_simulation_custody_route_selection_deprioritizes_starving_queue(monkeypatch) -> None:
    base_now = 1_785_787_000.0
    _set_now(monkeypatch, base_now)
    scheduler = OpenClawRecoverySchedulerService()
    queue_state = {
        'policy': {
            'aging_enabled': True,
            'aging_after_s': 900,
            'starvation_prevention_enabled': True,
            'starvation_after_s': 1800,
        },
        'queues': {
            'ops-primary': {
                'queue_id': 'ops-primary',
                'queue_label': 'Ops Primary',
                'capacity': 4,
                'warning_capacity': 3,
                'active_count': 1,
                'hard_limit': False,
                'load_weight': 1.0,
                'reservation_enabled': False,
                'reserved_capacity': 0,
                'general_capacity': 4,
                'general_available': 3,
                'reserved_available': 0,
                'reserved_for_severities': [],
                'reserved_for_queue_types': [],
                'oldest_alert_age_s': 7_200,
                'aged_alert_count': 1,
                'starving_alert_count': 1,
            },
            'ops-backup': {
                'queue_id': 'ops-backup',
                'queue_label': 'Ops Backup',
                'capacity': 4,
                'warning_capacity': 3,
                'active_count': 1,
                'hard_limit': False,
                'load_weight': 1.0,
                'reservation_enabled': False,
                'reserved_capacity': 0,
                'general_capacity': 4,
                'general_available': 3,
                'reserved_available': 0,
                'reserved_for_severities': [],
                'reserved_for_queue_types': [],
                'oldest_alert_age_s': 0,
                'aged_alert_count': 0,
                'starving_alert_count': 0,
            },
        },
    }
    route = scheduler._select_baseline_promotion_simulation_custody_route_by_load(
        routes=[
            {'route_id': 'ops-primary-route', 'label': 'Ops primary', 'queue_id': 'ops-primary', 'queue_label': 'Ops Primary', 'owner_role': 'shift-lead'},
            {'route_id': 'ops-backup-route', 'label': 'Ops backup', 'queue_id': 'ops-backup', 'queue_label': 'Ops Backup', 'owner_role': 'shift-lead'},
        ],
        queue_state=queue_state,
        prefer_lowest_load=True,
        alert={'severity': 'warning', 'routing': {}},
        policy={'queue_capacity_policy': {'aging_enabled': True, 'aging_after_s': 900, 'starvation_prevention_enabled': True, 'starvation_after_s': 1800}},
    )
    assert route['queue_id'] == 'ops-backup'
    assert route['queue_starving_alert_count'] == 0
    assert route['queue_oldest_alert_age_s'] == 0



def test_baseline_promotion_simulation_custody_route_selection_borrows_reserved_capacity_for_starving_alert(monkeypatch) -> None:
    base_now = 1_785_787_100.0
    _set_now(monkeypatch, base_now)
    scheduler = OpenClawRecoverySchedulerService()
    queue_state = {
        'policy': {
            'reservation_enabled': True,
            'starvation_prevention_enabled': True,
            'starvation_after_s': 600,
            'starvation_reserved_capacity_borrow_enabled': True,
        },
        'queues': {
            'ops-primary': {
                'queue_id': 'ops-primary',
                'queue_label': 'Ops Primary',
                'capacity': 2,
                'warning_capacity': 1,
                'active_count': 1,
                'hard_limit': False,
                'load_weight': 1.0,
                'reservation_enabled': True,
                'reserved_capacity': 1,
                'general_capacity': 1,
                'general_available': 0,
                'reserved_available': 1,
                'reserved_for_severities': ['critical'],
                'reserved_for_queue_types': [],
                'oldest_alert_age_s': 0,
                'aged_alert_count': 0,
                'starving_alert_count': 0,
            },
            'ops-backup': {
                'queue_id': 'ops-backup',
                'queue_label': 'Ops Backup',
                'capacity': 3,
                'warning_capacity': 2,
                'active_count': 2,
                'hard_limit': False,
                'load_weight': 1.0,
                'reservation_enabled': False,
                'reserved_capacity': 0,
                'general_capacity': 3,
                'general_available': 1,
                'reserved_available': 0,
                'reserved_for_severities': [],
                'reserved_for_queue_types': [],
                'oldest_alert_age_s': 0,
                'aged_alert_count': 0,
                'starving_alert_count': 0,
            },
        },
    }
    fresh_route = scheduler._select_baseline_promotion_simulation_custody_route_by_load(
        routes=[
            {'route_id': 'ops-primary-route', 'label': 'Ops primary', 'queue_id': 'ops-primary', 'queue_label': 'Ops Primary', 'owner_role': 'shift-lead'},
            {'route_id': 'ops-backup-route', 'label': 'Ops backup', 'queue_id': 'ops-backup', 'queue_label': 'Ops Backup', 'owner_role': 'shift-lead'},
        ],
        queue_state=queue_state,
        prefer_lowest_load=True,
        alert={'severity': 'warning', 'created_at': base_now - 60, 'routing': {}},
        policy={'queue_capacity_policy': {'reservation_enabled': True, 'starvation_prevention_enabled': True, 'starvation_after_s': 600, 'starvation_reserved_capacity_borrow_enabled': True}},
    )
    assert fresh_route['queue_id'] == 'ops-backup'
    starving_route = scheduler._select_baseline_promotion_simulation_custody_route_by_load(
        routes=[
            {'route_id': 'ops-primary-route', 'label': 'Ops primary', 'queue_id': 'ops-primary', 'queue_label': 'Ops Primary', 'owner_role': 'shift-lead'},
            {'route_id': 'ops-backup-route', 'label': 'Ops backup', 'queue_id': 'ops-backup', 'queue_label': 'Ops Backup', 'owner_role': 'shift-lead'},
        ],
        queue_state=queue_state,
        prefer_lowest_load=True,
        alert={'severity': 'warning', 'created_at': base_now - 1_200, 'routing': {}},
        policy={'queue_capacity_policy': {'reservation_enabled': True, 'starvation_prevention_enabled': True, 'starvation_after_s': 600, 'starvation_reserved_capacity_borrow_enabled': True}},
    )
    assert starving_route['queue_id'] == 'ops-primary'
    assert starving_route['starving'] is True
    assert starving_route['starvation_reserved_capacity_borrowed'] is True
    assert starving_route['starvation_prevention_applied'] is True
    assert starving_route['starvation_prevention_reason'] == 'borrow_reserved_capacity'
    assert starving_route['reservation_applied'] is False
    assert starving_route['selection_reason'] == 'starvation_reserved_capacity_queue'



def test_baseline_promotion_simulation_custody_route_selection_bypasses_anti_thrashing_for_starving_alert(monkeypatch) -> None:
    base_now = 1_785_787_200.0
    _set_now(monkeypatch, base_now)
    scheduler = OpenClawRecoverySchedulerService()
    queue_state = {
        'policy': {
            'anti_thrashing_enabled': True,
            'reroute_cooldown_s': 300,
            'anti_thrashing_min_active_delta': 1,
            'anti_thrashing_min_load_delta': 0.25,
            'starvation_prevention_enabled': True,
            'starvation_after_s': 600,
            'starvation_bypass_anti_thrashing': True,
        },
        'queues': {
            'ops-primary': {
                'queue_id': 'ops-primary',
                'queue_label': 'Ops Primary',
                'capacity': 4,
                'warning_capacity': 3,
                'active_count': 2,
                'hard_limit': False,
                'load_weight': 1.0,
                'reservation_enabled': False,
                'reserved_capacity': 0,
                'general_capacity': 4,
                'general_available': 2,
                'reserved_available': 0,
                'reserved_for_severities': [],
                'reserved_for_queue_types': [],
                'oldest_alert_age_s': 0,
                'aged_alert_count': 0,
                'starving_alert_count': 0,
            },
            'ops-backup': {
                'queue_id': 'ops-backup',
                'queue_label': 'Ops Backup',
                'capacity': 4,
                'warning_capacity': 3,
                'active_count': 1,
                'hard_limit': False,
                'load_weight': 1.0,
                'reservation_enabled': False,
                'reserved_capacity': 0,
                'general_capacity': 4,
                'general_available': 3,
                'reserved_available': 0,
                'reserved_for_severities': [],
                'reserved_for_queue_types': [],
                'oldest_alert_age_s': 0,
                'aged_alert_count': 0,
                'starving_alert_count': 0,
            },
        },
    }
    route = scheduler._select_baseline_promotion_simulation_custody_route_by_load(
        routes=[
            {'route_id': 'ops-primary-route', 'label': 'Ops primary', 'queue_id': 'ops-primary', 'queue_label': 'Ops Primary', 'owner_role': 'shift-lead'},
            {'route_id': 'ops-backup-route', 'label': 'Ops backup', 'queue_id': 'ops-backup', 'queue_label': 'Ops Backup', 'owner_role': 'shift-lead'},
        ],
        queue_state=queue_state,
        current_queue_id='ops-primary',
        prefer_lowest_load=True,
        alert={'severity': 'warning', 'created_at': base_now - 1_200, 'routing': {'queue_id': 'ops-primary', 'updated_at': base_now - 30}},
        policy={'queue_capacity_policy': {'anti_thrashing_enabled': True, 'reroute_cooldown_s': 300, 'anti_thrashing_min_active_delta': 1, 'anti_thrashing_min_load_delta': 0.25, 'starvation_prevention_enabled': True, 'starvation_after_s': 600, 'starvation_bypass_anti_thrashing': True}},
    )
    assert route['queue_id'] == 'ops-backup'
    assert route['starving'] is True
    assert route['anti_thrashing_applied'] is False
    assert route['starvation_prevention_applied'] is True
    assert route['starvation_prevention_reason'] == 'bypass_anti_thrashing'
    assert route['selection_reason'] == 'starvation_bypass_anti_thrashing'



def test_baseline_promotion_simulation_custody_route_selection_expedites_to_avoid_predicted_sla_breach(monkeypatch) -> None:
    base_now = 1_785_787_300.0
    _set_now(monkeypatch, base_now)
    scheduler = OpenClawRecoverySchedulerService()
    queue_state = {'policy': {'breach_prediction_enabled': True, 'expected_service_time_s': 300, 'expedite_enabled': True, 'expedite_threshold_s': 900, 'expedite_min_risk_score': 0.8}, 'queues': {'ops-primary': {'queue_id': 'ops-primary', 'queue_label': 'Ops Primary', 'capacity': 2, 'warning_capacity': 1, 'active_count': 2, 'hard_limit': False, 'load_weight': 1.0, 'reservation_enabled': False, 'reserved_capacity': 0, 'general_capacity': 2, 'general_available': 0, 'reserved_available': 0, 'reserved_for_severities': [], 'reserved_for_queue_types': [], 'expected_service_time_s': 300, 'oldest_alert_age_s': 0, 'aged_alert_count': 0, 'starving_alert_count': 0}, 'ops-backup': {'queue_id': 'ops-backup', 'queue_label': 'Ops Backup', 'capacity': 4, 'warning_capacity': 3, 'active_count': 1, 'hard_limit': False, 'load_weight': 1.0, 'reservation_enabled': False, 'reserved_capacity': 0, 'general_capacity': 4, 'general_available': 3, 'reserved_available': 0, 'reserved_for_severities': [], 'reserved_for_queue_types': [], 'expected_service_time_s': 300, 'oldest_alert_age_s': 0, 'aged_alert_count': 0, 'starving_alert_count': 0}}}
    route = scheduler._select_baseline_promotion_simulation_custody_route_by_load(routes=[{'route_id': 'ops-primary-route', 'label': 'Ops primary', 'queue_id': 'ops-primary', 'queue_label': 'Ops Primary', 'owner_role': 'shift-lead'}, {'route_id': 'ops-backup-route', 'label': 'Ops backup', 'queue_id': 'ops-backup', 'queue_label': 'Ops Backup', 'owner_role': 'shift-lead'}], queue_state=queue_state, prefer_lowest_load=True, alert={'severity': 'warning', 'sla_state': {'status': 'warning', 'targets': {'acknowledge': {'enabled': True, 'status': 'warning', 'remaining_s': 180}}}, 'routing': {}}, policy={'queue_capacity_policy': {'breach_prediction_enabled': True, 'expected_service_time_s': 300, 'expedite_enabled': True, 'expedite_threshold_s': 900, 'expedite_min_risk_score': 0.8}})
    assert route['queue_id'] == 'ops-backup'
    assert route['expedite_eligible'] is True
    assert route['expedite_applied'] is True
    assert route['selection_reason'] == 'expedite_deadline_queue'
    assert route['predicted_sla_breach'] is False
    assert route['time_to_breach_s'] == 180
    assert route['predicted_wait_time_s'] == 75


def test_baseline_promotion_simulation_custody_route_selection_borrows_reserved_capacity_for_expedite(monkeypatch) -> None:
    base_now = 1_785_787_350.0
    _set_now(monkeypatch, base_now)
    scheduler = OpenClawRecoverySchedulerService()
    queue_state = {'policy': {'reservation_enabled': True, 'breach_prediction_enabled': True, 'expected_service_time_s': 300, 'expedite_enabled': True, 'expedite_threshold_s': 300, 'expedite_reserved_capacity_borrow_enabled': True}, 'queues': {'ops-primary': {'queue_id': 'ops-primary', 'queue_label': 'Ops Primary', 'capacity': 2, 'warning_capacity': 1, 'active_count': 1, 'hard_limit': False, 'load_weight': 1.0, 'reservation_enabled': True, 'reserved_capacity': 1, 'general_capacity': 1, 'general_available': 0, 'reserved_available': 1, 'reserved_for_severities': ['critical'], 'reserved_for_queue_types': [], 'expected_service_time_s': 60, 'oldest_alert_age_s': 0, 'aged_alert_count': 0, 'starving_alert_count': 0}, 'ops-backup': {'queue_id': 'ops-backup', 'queue_label': 'Ops Backup', 'capacity': 3, 'warning_capacity': 2, 'active_count': 3, 'hard_limit': False, 'load_weight': 1.0, 'reservation_enabled': False, 'reserved_capacity': 0, 'general_capacity': 3, 'general_available': 0, 'reserved_available': 0, 'reserved_for_severities': [], 'reserved_for_queue_types': [], 'expected_service_time_s': 300, 'oldest_alert_age_s': 0, 'aged_alert_count': 0, 'starving_alert_count': 0}}}
    route = scheduler._select_baseline_promotion_simulation_custody_route_by_load(routes=[{'route_id': 'ops-primary-route', 'label': 'Ops primary', 'queue_id': 'ops-primary', 'queue_label': 'Ops Primary', 'owner_role': 'shift-lead'}, {'route_id': 'ops-backup-route', 'label': 'Ops backup', 'queue_id': 'ops-backup', 'queue_label': 'Ops Backup', 'owner_role': 'shift-lead'}], queue_state=queue_state, prefer_lowest_load=True, alert={'severity': 'warning', 'sla_state': {'status': 'warning', 'targets': {'acknowledge': {'enabled': True, 'status': 'warning', 'remaining_s': 120}}}, 'routing': {}}, policy={'queue_capacity_policy': {'reservation_enabled': True, 'breach_prediction_enabled': True, 'expected_service_time_s': 300, 'expedite_enabled': True, 'expedite_threshold_s': 300, 'expedite_reserved_capacity_borrow_enabled': True}})
    assert route['queue_id'] == 'ops-primary'
    assert route['expedite_reserved_capacity_borrowed'] is True
    assert route['expedite_applied'] is True
    assert route['selection_reason'] == 'expedite_reserved_capacity_queue'
    assert route['expedite_reason'] == 'borrow_reserved_capacity'


def test_baseline_promotion_simulation_custody_route_selection_bypasses_anti_thrashing_for_expedite(monkeypatch) -> None:
    base_now = 1_785_787_400.0
    _set_now(monkeypatch, base_now)
    scheduler = OpenClawRecoverySchedulerService()
    queue_state = {'policy': {'anti_thrashing_enabled': True, 'reroute_cooldown_s': 300, 'anti_thrashing_min_active_delta': 2, 'anti_thrashing_min_load_delta': 1.0, 'breach_prediction_enabled': True, 'expected_service_time_s': 300, 'expedite_enabled': True, 'expedite_threshold_s': 600, 'expedite_bypass_anti_thrashing': True}, 'queues': {'ops-primary': {'queue_id': 'ops-primary', 'queue_label': 'Ops Primary', 'capacity': 2, 'warning_capacity': 1, 'active_count': 2, 'hard_limit': False, 'load_weight': 1.0, 'reservation_enabled': False, 'reserved_capacity': 0, 'general_capacity': 2, 'general_available': 0, 'reserved_available': 0, 'reserved_for_severities': [], 'reserved_for_queue_types': [], 'expected_service_time_s': 300, 'oldest_alert_age_s': 0, 'aged_alert_count': 0, 'starving_alert_count': 0}, 'ops-backup': {'queue_id': 'ops-backup', 'queue_label': 'Ops Backup', 'capacity': 3, 'warning_capacity': 2, 'active_count': 1, 'hard_limit': False, 'load_weight': 1.0, 'reservation_enabled': False, 'reserved_capacity': 0, 'general_capacity': 3, 'general_available': 2, 'reserved_available': 0, 'reserved_for_severities': [], 'reserved_for_queue_types': [], 'expected_service_time_s': 300, 'oldest_alert_age_s': 0, 'aged_alert_count': 0, 'starving_alert_count': 0}}}
    route = scheduler._select_baseline_promotion_simulation_custody_route_by_load(routes=[{'route_id': 'ops-primary-route', 'label': 'Ops primary', 'queue_id': 'ops-primary', 'queue_label': 'Ops Primary', 'owner_role': 'shift-lead'}, {'route_id': 'ops-backup-route', 'label': 'Ops backup', 'queue_id': 'ops-backup', 'queue_label': 'Ops Backup', 'owner_role': 'shift-lead'}], queue_state=queue_state, current_queue_id='ops-primary', prefer_lowest_load=True, alert={'severity': 'warning', 'sla_state': {'status': 'warning', 'targets': {'acknowledge': {'enabled': True, 'status': 'warning', 'remaining_s': 200}}}, 'routing': {'queue_id': 'ops-primary', 'updated_at': base_now - 30}}, policy={'queue_capacity_policy': {'anti_thrashing_enabled': True, 'reroute_cooldown_s': 300, 'anti_thrashing_min_active_delta': 2, 'anti_thrashing_min_load_delta': 1.0, 'breach_prediction_enabled': True, 'expected_service_time_s': 300, 'expedite_enabled': True, 'expedite_threshold_s': 600, 'expedite_bypass_anti_thrashing': True}})
    assert route['queue_id'] == 'ops-backup'
    assert route['expedite_applied'] is True
    assert route['selection_reason'] == 'expedite_bypass_anti_thrashing'
    assert route['expedite_reason'] == 'bypass_anti_thrashing'



def test_baseline_promotion_simulation_custody_route_selection_proactively_avoids_forecasted_surge(monkeypatch) -> None:
    base_now = 1_785_787_425.0
    _set_now(monkeypatch, base_now)
    scheduler = OpenClawRecoverySchedulerService()
    queue_state = {
        'policy': {
            'predictive_forecasting_enabled': True,
            'forecast_window_s': 900,
            'surge_load_ratio_threshold': 0.85,
            'proactive_routing_enabled': True,
            'proactive_min_projected_load_delta': 0.2,
            'proactive_wait_buffer_s': 120,
        },
        'queues': {
            'ops-primary': {
                'queue_id': 'ops-primary', 'queue_label': 'Ops Primary', 'capacity': 4, 'warning_capacity': 3, 'active_count': 1,
                'hard_limit': False, 'load_weight': 1.0, 'reservation_enabled': False, 'reserved_capacity': 0,
                'general_capacity': 4, 'general_available': 3, 'reserved_available': 0, 'expected_service_time_s': 300,
                'forecast_window_s': 900, 'forecast_arrivals_count': 20,
                'oldest_alert_age_s': 0, 'aged_alert_count': 0, 'starving_alert_count': 0,
            },
            'ops-backup': {
                'queue_id': 'ops-backup', 'queue_label': 'Ops Backup', 'capacity': 4, 'warning_capacity': 3, 'active_count': 2,
                'hard_limit': False, 'load_weight': 1.0, 'reservation_enabled': False, 'reserved_capacity': 0,
                'general_capacity': 4, 'general_available': 2, 'reserved_available': 0, 'expected_service_time_s': 300,
                'forecast_window_s': 900, 'forecast_arrivals_count': 0,
                'oldest_alert_age_s': 0, 'aged_alert_count': 0, 'starving_alert_count': 0,
            },
        },
    }
    route = scheduler._select_baseline_promotion_simulation_custody_route_by_load(
        routes=[
            {'route_id': 'ops-primary-route', 'label': 'Ops primary', 'queue_id': 'ops-primary', 'queue_label': 'Ops Primary', 'owner_role': 'shift-lead'},
            {'route_id': 'ops-backup-route', 'label': 'Ops backup', 'queue_id': 'ops-backup', 'queue_label': 'Ops Backup', 'owner_role': 'shift-lead'},
        ],
        queue_state=queue_state,
        prefer_lowest_load=True,
        alert={'severity': 'warning', 'routing': {}},
        policy={'queue_capacity_policy': {'predictive_forecasting_enabled': True, 'forecast_window_s': 900, 'surge_load_ratio_threshold': 0.85, 'proactive_routing_enabled': True, 'proactive_min_projected_load_delta': 0.2, 'proactive_wait_buffer_s': 120}},
    )
    assert route['queue_id'] == 'ops-backup'
    assert route['proactive_routing_applied'] is True
    assert route['selection_reason'] == 'proactive_forecast_queue'
    assert route['proactive_reason'] == 'avoid_forecasted_surge'
    assert route['forecast_window_s'] == 900
    assert route['projected_wait_time_s'] >= 0



def test_baseline_promotion_simulation_custody_route_selection_bypasses_anti_thrashing_for_proactive_forecast(monkeypatch) -> None:
    base_now = 1_785_787_430.0
    _set_now(monkeypatch, base_now)
    scheduler = OpenClawRecoverySchedulerService()
    queue_state = {
        'policy': {
            'anti_thrashing_enabled': True,
            'reroute_cooldown_s': 300,
            'anti_thrashing_min_active_delta': 5,
            'anti_thrashing_min_load_delta': 1.0,
            'predictive_forecasting_enabled': True,
            'forecast_window_s': 900,
            'surge_load_ratio_threshold': 0.85,
            'proactive_routing_enabled': True,
            'proactive_min_projected_load_delta': 0.2,
            'proactive_wait_buffer_s': 120,
            'proactive_bypass_anti_thrashing': True,
        },
        'queues': {
            'ops-primary': {
                'queue_id': 'ops-primary', 'queue_label': 'Ops Primary', 'capacity': 4, 'warning_capacity': 3, 'active_count': 1,
                'hard_limit': False, 'load_weight': 1.0, 'reservation_enabled': False, 'reserved_capacity': 0,
                'general_capacity': 4, 'general_available': 3, 'reserved_available': 0, 'expected_service_time_s': 300,
                'forecast_window_s': 900, 'forecast_arrivals_count': 20,
                'oldest_alert_age_s': 0, 'aged_alert_count': 0, 'starving_alert_count': 0,
            },
            'ops-backup': {
                'queue_id': 'ops-backup', 'queue_label': 'Ops Backup', 'capacity': 4, 'warning_capacity': 3, 'active_count': 2,
                'hard_limit': False, 'load_weight': 1.0, 'reservation_enabled': False, 'reserved_capacity': 0,
                'general_capacity': 4, 'general_available': 2, 'reserved_available': 0, 'expected_service_time_s': 300,
                'forecast_window_s': 900, 'forecast_arrivals_count': 0,
                'oldest_alert_age_s': 0, 'aged_alert_count': 0, 'starving_alert_count': 0,
            },
        },
    }
    route = scheduler._select_baseline_promotion_simulation_custody_route_by_load(
        routes=[
            {'route_id': 'ops-primary-route', 'label': 'Ops primary', 'queue_id': 'ops-primary', 'queue_label': 'Ops Primary', 'owner_role': 'shift-lead'},
            {'route_id': 'ops-backup-route', 'label': 'Ops backup', 'queue_id': 'ops-backup', 'queue_label': 'Ops Backup', 'owner_role': 'shift-lead'},
        ],
        queue_state=queue_state,
        current_queue_id='ops-primary',
        prefer_lowest_load=True,
        alert={'severity': 'warning', 'routing': {'queue_id': 'ops-primary', 'updated_at': base_now - 30}},
        policy={'queue_capacity_policy': {'anti_thrashing_enabled': True, 'reroute_cooldown_s': 300, 'anti_thrashing_min_active_delta': 5, 'anti_thrashing_min_load_delta': 1.0, 'predictive_forecasting_enabled': True, 'forecast_window_s': 900, 'surge_load_ratio_threshold': 0.85, 'proactive_routing_enabled': True, 'proactive_min_projected_load_delta': 0.2, 'proactive_wait_buffer_s': 120, 'proactive_bypass_anti_thrashing': True}},
    )
    assert route['queue_id'] == 'ops-backup'
    assert route['proactive_routing_applied'] is True
    assert route['selection_reason'] == 'proactive_bypass_anti_thrashing'

    assert route['proactive_reason'] == 'bypass_anti_thrashing'


def test_baseline_promotion_simulation_custody_route_selection_avoids_overloaded_queue_with_admission_control(monkeypatch) -> None:
    base_now = 1_785_787_435.0
    _set_now(monkeypatch, base_now)
    scheduler = OpenClawRecoverySchedulerService()
    queue_state = {
        'policy': {
            'predictive_forecasting_enabled': True,
            'forecast_window_s': 900,
            'admission_control_enabled': True,
            'overload_governance_enabled': True,
            'admission_default_action': 'defer',
            'overload_global_action': 'defer',
            'overload_projected_load_ratio_threshold': 0.9,
            'overload_projected_wait_time_threshold_s': 600,
        },
        'queues': {
            'ops-primary': {
                'queue_id': 'ops-primary', 'queue_label': 'Ops Primary', 'capacity': 2, 'warning_capacity': 1, 'active_count': 1,
                'hard_limit': False, 'load_weight': 1.0, 'reservation_enabled': False, 'reserved_capacity': 0,
                'general_capacity': 2, 'general_available': 1, 'reserved_available': 0, 'expected_service_time_s': 300,
                'forecast_window_s': 900, 'forecast_arrivals_count': 10,
                'oldest_alert_age_s': 0, 'aged_alert_count': 0, 'starving_alert_count': 0,
            },
            'ops-backup': {
                'queue_id': 'ops-backup', 'queue_label': 'Ops Backup', 'capacity': 4, 'warning_capacity': 3, 'active_count': 1,
                'hard_limit': False, 'load_weight': 1.0, 'reservation_enabled': False, 'reserved_capacity': 0,
                'general_capacity': 4, 'general_available': 3, 'reserved_available': 0, 'expected_service_time_s': 300,
                'forecast_window_s': 900, 'forecast_arrivals_count': 0,
                'oldest_alert_age_s': 0, 'aged_alert_count': 0, 'starving_alert_count': 0,
            },
        },
    }
    route = scheduler._select_baseline_promotion_simulation_custody_route_by_load(
        routes=[
            {'route_id': 'ops-primary-route', 'label': 'Ops primary', 'queue_id': 'ops-primary', 'queue_label': 'Ops Primary', 'owner_role': 'shift-lead'},
            {'route_id': 'ops-backup-route', 'label': 'Ops backup', 'queue_id': 'ops-backup', 'queue_label': 'Ops Backup', 'owner_role': 'shift-lead'},
        ],
        queue_state=queue_state,
        prefer_lowest_load=True,
        alert={'severity': 'warning', 'routing': {}},
        policy={'queue_capacity_policy': {'predictive_forecasting_enabled': True, 'forecast_window_s': 900, 'admission_control_enabled': True, 'overload_governance_enabled': True, 'admission_default_action': 'defer', 'overload_global_action': 'defer', 'overload_projected_load_ratio_threshold': 0.9, 'overload_projected_wait_time_threshold_s': 600}},
    )
    assert route['queue_id'] == 'ops-backup'
    assert route['admission_blocked'] is False
    assert route['overload_governance_applied'] is False



def test_baseline_promotion_simulation_custody_route_selection_manual_gates_when_all_candidates_overloaded(monkeypatch) -> None:
    base_now = 1_785_787_440.0
    _set_now(monkeypatch, base_now)
    scheduler = OpenClawRecoverySchedulerService()
    queue_state = {
        'policy': {
            'predictive_forecasting_enabled': True,
            'forecast_window_s': 900,
            'admission_control_enabled': True,
            'overload_governance_enabled': True,
            'admission_default_action': 'manual_gate',
            'overload_global_action': 'manual_gate',
            'overload_projected_load_ratio_threshold': 0.85,
            'overload_projected_wait_time_threshold_s': 300,
        },
        'queues': {
            'ops-primary': {
                'queue_id': 'ops-primary', 'queue_label': 'Ops Primary', 'capacity': 2, 'warning_capacity': 1, 'active_count': 2,
                'hard_limit': True, 'load_weight': 1.0, 'reservation_enabled': False, 'reserved_capacity': 0,
                'general_capacity': 2, 'general_available': 0, 'reserved_available': 0, 'expected_service_time_s': 300,
                'forecast_window_s': 900, 'forecast_arrivals_count': 8,
                'oldest_alert_age_s': 0, 'aged_alert_count': 0, 'starving_alert_count': 0,
            },
            'ops-backup': {
                'queue_id': 'ops-backup', 'queue_label': 'Ops Backup', 'capacity': 2, 'warning_capacity': 1, 'active_count': 2,
                'hard_limit': True, 'load_weight': 1.0, 'reservation_enabled': False, 'reserved_capacity': 0,
                'general_capacity': 2, 'general_available': 0, 'reserved_available': 0, 'expected_service_time_s': 300,
                'forecast_window_s': 900, 'forecast_arrivals_count': 6,
                'oldest_alert_age_s': 0, 'aged_alert_count': 0, 'starving_alert_count': 0,
            },
        },
    }
    route = scheduler._select_baseline_promotion_simulation_custody_route_by_load(
        routes=[
            {'route_id': 'ops-primary-route', 'label': 'Ops primary', 'queue_id': 'ops-primary', 'queue_label': 'Ops Primary', 'owner_role': 'shift-lead'},
            {'route_id': 'ops-backup-route', 'label': 'Ops backup', 'queue_id': 'ops-backup', 'queue_label': 'Ops Backup', 'owner_role': 'shift-lead'},
        ],
        queue_state=queue_state,
        prefer_lowest_load=True,
        alert={'severity': 'warning', 'routing': {}},
        policy={'queue_capacity_policy': {'predictive_forecasting_enabled': True, 'forecast_window_s': 900, 'admission_control_enabled': True, 'overload_governance_enabled': True, 'admission_default_action': 'manual_gate', 'overload_global_action': 'manual_gate', 'overload_projected_load_ratio_threshold': 0.85, 'overload_projected_wait_time_threshold_s': 300}},
    )
    assert route['admission_blocked'] is True
    assert route['admission_decision'] == 'manual_gate'
    assert route['overload_governance_applied'] is True
    assert route['selection_reason'] == 'overload_manual_gate_queue'



def test_baseline_promotion_simulation_custody_route_selection_bypasses_anti_thrashing_for_admission_control(monkeypatch) -> None:
    base_now = 1_785_787_445.0
    _set_now(monkeypatch, base_now)
    scheduler = OpenClawRecoverySchedulerService()
    queue_state = {
        'policy': {
            'anti_thrashing_enabled': True,
            'reroute_cooldown_s': 300,
            'anti_thrashing_min_active_delta': 5,
            'anti_thrashing_min_load_delta': 1.0,
            'predictive_forecasting_enabled': True,
            'forecast_window_s': 900,
            'admission_control_enabled': True,
            'overload_governance_enabled': True,
            'admission_default_action': 'defer',
            'overload_global_action': 'defer',
            'overload_projected_load_ratio_threshold': 0.9,
            'overload_projected_wait_time_threshold_s': 600,
        },
        'queues': {
            'ops-primary': {
                'queue_id': 'ops-primary', 'queue_label': 'Ops Primary', 'capacity': 2, 'warning_capacity': 1, 'active_count': 1,
                'hard_limit': False, 'load_weight': 1.0, 'reservation_enabled': False, 'reserved_capacity': 0,
                'general_capacity': 2, 'general_available': 1, 'reserved_available': 0, 'expected_service_time_s': 300,
                'forecast_window_s': 900, 'forecast_arrivals_count': 10,
                'oldest_alert_age_s': 0, 'aged_alert_count': 0, 'starving_alert_count': 0,
            },
            'ops-backup': {
                'queue_id': 'ops-backup', 'queue_label': 'Ops Backup', 'capacity': 4, 'warning_capacity': 3, 'active_count': 2,
                'hard_limit': False, 'load_weight': 1.0, 'reservation_enabled': False, 'reserved_capacity': 0,
                'general_capacity': 4, 'general_available': 2, 'reserved_available': 0, 'expected_service_time_s': 300,
                'forecast_window_s': 900, 'forecast_arrivals_count': 0,
                'oldest_alert_age_s': 0, 'aged_alert_count': 0, 'starving_alert_count': 0,
            },
        },
    }
    route = scheduler._select_baseline_promotion_simulation_custody_route_by_load(
        routes=[
            {'route_id': 'ops-primary-route', 'label': 'Ops primary', 'queue_id': 'ops-primary', 'queue_label': 'Ops Primary', 'owner_role': 'shift-lead'},
            {'route_id': 'ops-backup-route', 'label': 'Ops backup', 'queue_id': 'ops-backup', 'queue_label': 'Ops Backup', 'owner_role': 'shift-lead'},
        ],
        queue_state=queue_state,
        current_queue_id='ops-primary',
        prefer_lowest_load=True,
        alert={'severity': 'warning', 'routing': {'queue_id': 'ops-primary', 'updated_at': base_now - 30}},
        policy={'queue_capacity_policy': {'anti_thrashing_enabled': True, 'reroute_cooldown_s': 300, 'anti_thrashing_min_active_delta': 5, 'anti_thrashing_min_load_delta': 1.0, 'predictive_forecasting_enabled': True, 'forecast_window_s': 900, 'admission_control_enabled': True, 'overload_governance_enabled': True, 'admission_default_action': 'defer', 'overload_global_action': 'defer', 'overload_projected_load_ratio_threshold': 0.9, 'overload_projected_wait_time_threshold_s': 600}},
    )
    assert route['queue_id'] == 'ops-backup'
    assert route['admission_blocked'] is False
    assert route['selection_reason'] == 'admission_bypass_anti_thrashing'


def test_baseline_promotion_simulation_custody_route_selection_applies_leased_capacity(monkeypatch) -> None:
    base_now = 1_785_787_450.0
    _set_now(monkeypatch, base_now)
    scheduler = OpenClawRecoverySchedulerService()
    queue_state = {
        'policy': {
            'reservation_lease_enabled': True,
        },
        'queues': {
            'ops-primary': {
                'queue_id': 'ops-primary',
                'queue_label': 'Ops Primary',
                'capacity': 2,
                'warning_capacity': 1,
                'active_count': 1,
                'hard_limit': False,
                'load_weight': 1.0,
                'reservation_enabled': False,
                'reserved_capacity': 0,
                'general_capacity': 1,
                'general_available': 0,
                'reserved_available': 0,
                'lease_active': True,
                'lease_expired': False,
                'leased_capacity': 1,
                'lease_available': 1,
                'leased_for_severities': ['critical'],
                'leased_for_queue_types': [],
                'temporary_hold_count': 0,
                'temporary_hold_capacity': 0,
                'temporary_hold_available': 0,
                'temporary_holds': [],
                'expected_service_time_s': 60,
                'oldest_alert_age_s': 0,
                'aged_alert_count': 0,
                'starving_alert_count': 0,
            },
            'ops-backup': {
                'queue_id': 'ops-backup',
                'queue_label': 'Ops Backup',
                'capacity': 4,
                'warning_capacity': 3,
                'active_count': 2,
                'hard_limit': False,
                'load_weight': 1.0,
                'reservation_enabled': False,
                'reserved_capacity': 0,
                'general_capacity': 4,
                'general_available': 2,
                'reserved_available': 0,
                'lease_active': False,
                'lease_expired': False,
                'leased_capacity': 0,
                'lease_available': 0,
                'leased_for_severities': [],
                'leased_for_queue_types': [],
                'temporary_hold_count': 0,
                'temporary_hold_capacity': 0,
                'temporary_hold_available': 0,
                'temporary_holds': [],
                'expected_service_time_s': 300,
                'oldest_alert_age_s': 0,
                'aged_alert_count': 0,
                'starving_alert_count': 0,
            },
        },
    }
    route = scheduler._select_baseline_promotion_simulation_custody_route_by_load(
        routes=[
            {'route_id': 'ops-primary-route', 'label': 'Ops primary', 'queue_id': 'ops-primary', 'queue_label': 'Ops Primary', 'owner_role': 'shift-lead'},
            {'route_id': 'ops-backup-route', 'label': 'Ops backup', 'queue_id': 'ops-backup', 'queue_label': 'Ops Backup', 'owner_role': 'shift-lead'},
        ],
        queue_state=queue_state,
        prefer_lowest_load=True,
        alert={'severity': 'critical', 'routing': {}},
        policy={'queue_capacity_policy': {'reservation_lease_enabled': True}},
    )
    assert route['queue_id'] == 'ops-primary'
    assert route['lease_active'] is True
    assert route['lease_eligible'] is True
    assert route['lease_applied'] is True
    assert route['selection_reason'] == 'leased_capacity_queue'



def test_baseline_promotion_simulation_custody_route_selection_borrows_temporary_hold_capacity_for_expedite(monkeypatch) -> None:
    base_now = 1_785_787_500.0
    _set_now(monkeypatch, base_now)
    scheduler = OpenClawRecoverySchedulerService()
    queue_state = {
        'policy': {
            'temporary_holds_enabled': True,
            'breach_prediction_enabled': True,
            'expected_service_time_s': 300,
            'expedite_enabled': True,
            'expedite_threshold_s': 300,
            'expedite_hold_capacity_borrow_enabled': True,
        },
        'queues': {
            'ops-primary': {
                'queue_id': 'ops-primary',
                'queue_label': 'Ops Primary',
                'capacity': 2,
                'warning_capacity': 1,
                'active_count': 1,
                'hard_limit': False,
                'load_weight': 1.0,
                'reservation_enabled': False,
                'reserved_capacity': 0,
                'general_capacity': 1,
                'general_available': 0,
                'reserved_available': 0,
                'lease_active': False,
                'lease_expired': False,
                'leased_capacity': 0,
                'lease_available': 0,
                'leased_for_severities': [],
                'leased_for_queue_types': [],
                'temporary_hold_count': 1,
                'temporary_hold_capacity': 1,
                'temporary_hold_available': 1,
                'temporary_hold_ids': ['hold-1'],
                'temporary_hold_reasons': ['handoff_pending'],
                'temporary_holds': [
                    {
                        'hold_id': 'hold-1',
                        'capacity': 1,
                        'reason': 'handoff_pending',
                        'for_severities': ['critical'],
                        'for_queue_types': [],
                        'active': True,
                    }
                ],
                'expected_service_time_s': 60,
                'oldest_alert_age_s': 0,
                'aged_alert_count': 0,
                'starving_alert_count': 0,
            },
            'ops-backup': {
                'queue_id': 'ops-backup',
                'queue_label': 'Ops Backup',
                'capacity': 3,
                'warning_capacity': 2,
                'active_count': 3,
                'hard_limit': False,
                'load_weight': 1.0,
                'reservation_enabled': False,
                'reserved_capacity': 0,
                'general_capacity': 3,
                'general_available': 0,
                'reserved_available': 0,
                'lease_active': False,
                'lease_expired': False,
                'leased_capacity': 0,
                'lease_available': 0,
                'leased_for_severities': [],
                'leased_for_queue_types': [],
                'temporary_hold_count': 0,
                'temporary_hold_capacity': 0,
                'temporary_hold_available': 0,
                'temporary_holds': [],
                'expected_service_time_s': 300,
                'oldest_alert_age_s': 0,
                'aged_alert_count': 0,
                'starving_alert_count': 0,
            },
        },
    }
    route = scheduler._select_baseline_promotion_simulation_custody_route_by_load(
        routes=[
            {'route_id': 'ops-primary-route', 'label': 'Ops primary', 'queue_id': 'ops-primary', 'queue_label': 'Ops Primary', 'owner_role': 'shift-lead'},
            {'route_id': 'ops-backup-route', 'label': 'Ops backup', 'queue_id': 'ops-backup', 'queue_label': 'Ops Backup', 'owner_role': 'shift-lead'},
        ],
        queue_state=queue_state,
        prefer_lowest_load=True,
        alert={'severity': 'warning', 'sla_state': {'status': 'warning', 'targets': {'acknowledge': {'enabled': True, 'status': 'warning', 'remaining_s': 120}}}, 'routing': {}},
        policy={'queue_capacity_policy': {'temporary_holds_enabled': True, 'breach_prediction_enabled': True, 'expected_service_time_s': 300, 'expedite_enabled': True, 'expedite_threshold_s': 300, 'expedite_hold_capacity_borrow_enabled': True}},
    )
    assert route['queue_id'] == 'ops-primary'
    assert route['expedite_temporary_hold_borrowed'] is True
    assert route['expedite_applied'] is True
    assert route['selection_reason'] == 'expedite_temporary_hold_queue'
    assert route['expedite_reason'] == 'borrow_temporary_hold_capacity'



def test_baseline_promotion_simulation_custody_queue_capacity_state_tracks_leases_and_holds(monkeypatch) -> None:
    base_now = 1_785_787_550.0
    _set_now(monkeypatch, base_now)
    scheduler = OpenClawRecoverySchedulerService()

    class _Audit:
        @staticmethod
        def list_release_bundles(**kwargs):
            return []

    class _GatewayStub:
        audit = _Audit()

    state = scheduler._baseline_promotion_simulation_custody_queue_capacity_state(
        _GatewayStub(),
        policy={
            'queue_capacity_policy': {
                'reservation_enabled': True,
                'default_reserved_capacity': 1,
                'reservation_lease_enabled': True,
                'temporary_holds_enabled': True,
            },
            'queue_capacities': [
                {
                    'queue_id': 'ops-primary',
                    'queue_label': 'Ops Primary',
                    'capacity': 4,
                    'warning_capacity': 3,
                    'reserved_capacity': 1,
                    'leased_capacity': 1,
                    'lease_expires_at': base_now + 600,
                    'lease_reason': 'expedite-window',
                    'temporary_holds': [
                        {'hold_id': 'hold-active', 'capacity': 1, 'reason': 'handoff_pending', 'expires_at': base_now + 120},
                        {'hold_id': 'hold-expired', 'capacity': 1, 'reason': 'expired-window', 'expires_at': base_now - 60},
                    ],
                },
                {
                    'queue_id': 'ops-backup',
                    'queue_label': 'Ops Backup',
                    'capacity': 3,
                    'leased_capacity': 1,
                    'lease_expires_at': base_now - 30,
                },
            ],
        },
        tenant_id='tenant-a',
        workspace_id='ws-a',
        environment='prod',
    )
    primary = state['queues']['ops-primary']
    backup = state['queues']['ops-backup']
    assert primary['lease_active'] is True
    assert primary['leased_capacity'] == 1
    assert primary['temporary_hold_count'] == 1
    assert primary['expired_temporary_hold_count'] == 1
    assert primary['temporary_hold_capacity'] == 1
    assert primary['general_capacity'] == 1
    assert backup['lease_active'] is False
    assert backup['lease_expired'] is True
    assert state['summary']['leased_queue_count'] == 1
    assert state['summary']['active_temporary_hold_count'] == 1
    assert state['summary']['expired_hold_count'] == 1
    assert state['summary']['expired_lease_count'] == 1


def test_baseline_promotion_simulation_custody_route_selection_applies_family_hysteresis(monkeypatch) -> None:
    base_now = 1_785_787_900.0
    _set_now(monkeypatch, base_now)
    scheduler = OpenClawRecoverySchedulerService()
    queue_state = {
        'policy': {
            'queue_families_enabled': True,
            'multi_hop_hysteresis_enabled': True,
            'family_reroute_cooldown_s': 300,
            'family_recent_hops_threshold': 2,
            'family_min_active_delta': 1,
            'family_min_load_delta': 0.2,
            'family_min_projected_wait_delta_s': 120,
            'anti_thrashing_enabled': False,
        },
        'queues': {
            'ops-a': {
                'queue_id': 'ops-a', 'queue_label': 'Ops A', 'queue_family_id': 'ops-family', 'queue_family_label': 'Ops Family',
                'capacity': 5, 'warning_capacity': 4, 'active_count': 2, 'hard_limit': False, 'load_weight': 1.0,
                'general_capacity': 5, 'general_available': 3, 'reserved_capacity': 0, 'reserved_available': 0,
                'leased_capacity': 0, 'lease_available': 0, 'temporary_hold_capacity': 0, 'temporary_hold_available': 0,
                'expected_service_time_s': 300, 'forecast_window_s': 1800, 'forecast_arrivals_count': 0,
            },
            'ops-b': {
                'queue_id': 'ops-b', 'queue_label': 'Ops B', 'queue_family_id': 'ops-family', 'queue_family_label': 'Ops Family',
                'capacity': 5, 'warning_capacity': 4, 'active_count': 1, 'hard_limit': False, 'load_weight': 1.0,
                'general_capacity': 5, 'general_available': 4, 'reserved_capacity': 0, 'reserved_available': 0,
                'leased_capacity': 0, 'lease_available': 0, 'temporary_hold_capacity': 0, 'temporary_hold_available': 0,
                'expected_service_time_s': 300, 'forecast_window_s': 1800, 'forecast_arrivals_count': 0,
            },
        },
    }
    route = scheduler._select_baseline_promotion_simulation_custody_route_by_load(
        routes=[
            {'route_id': 'ops-a-route', 'label': 'Ops A', 'queue_id': 'ops-a', 'queue_label': 'Ops A', 'owner_role': 'shift-lead'},
            {'route_id': 'ops-b-route', 'label': 'Ops B', 'queue_id': 'ops-b', 'queue_label': 'Ops B', 'owner_role': 'shift-lead'},
        ],
        queue_state=queue_state,
        current_queue_id='ops-a',
        prefer_lowest_load=True,
        alert={
            'severity': 'warning',
            'routing': {
                'queue_id': 'ops-a',
                'updated_at': base_now - 30,
                'route_history': [
                    {'queue_id': 'ops-a', 'queue_family_id': 'ops-family', 'at': base_now - 200},
                    {'queue_id': 'ops-b', 'queue_family_id': 'ops-family', 'at': base_now - 120},
                    {'queue_id': 'ops-a', 'queue_family_id': 'ops-family', 'at': base_now - 60},
                ],
            },
        },
        policy={
            'queue_capacity_policy': {'queue_families_enabled': True, 'multi_hop_hysteresis_enabled': True, 'family_reroute_cooldown_s': 300, 'family_recent_hops_threshold': 2, 'family_min_active_delta': 1, 'family_min_load_delta': 0.2, 'family_min_projected_wait_delta_s': 120},
            'routing_routes': [
                {'route_id': 'ops-a-route', 'label': 'Ops A', 'queue_id': 'ops-a', 'queue_label': 'Ops A', 'owner_role': 'shift-lead'},
                {'route_id': 'ops-b-route', 'label': 'Ops B', 'queue_id': 'ops-b', 'queue_label': 'Ops B', 'owner_role': 'shift-lead'},
            ],
            'default_route': {'route_id': 'ops-a-route', 'label': 'Ops A', 'queue_id': 'ops-a', 'queue_label': 'Ops A', 'owner_role': 'shift-lead'},
            'load_aware_routing_enabled': True,
        },
    )
    assert route['queue_id'] == 'ops-a'
    assert route['family_hysteresis_applied'] is True
    assert route['family_hysteresis_reason'] == 'recent_same_family_multi_hop'
    assert route['selection_reason'] == 'family_hysteresis_keep_current_queue'
    assert route['queue_family_id'] == 'ops-family'
    assert route['recent_family_hop_count'] >= 1



def test_baseline_promotion_simulation_custody_route_replay_compares_policy_scenarios(monkeypatch) -> None:
    base_now = 1_785_788_050.0
    _set_now(monkeypatch, base_now)
    scheduler = OpenClawRecoverySchedulerService()
    queue_state = {
        'policy': {
            'queue_families_enabled': True,
            'multi_hop_hysteresis_enabled': True,
            'family_reroute_cooldown_s': 300,
            'family_recent_hops_threshold': 2,
            'family_min_active_delta': 1,
            'family_min_load_delta': 0.2,
            'family_min_projected_wait_delta_s': 120,
            'anti_thrashing_enabled': False,
        },
        'queues': {
            'ops-a': {
                'queue_id': 'ops-a', 'queue_label': 'Ops A', 'queue_family_id': 'ops-family', 'queue_family_label': 'Ops Family',
                'capacity': 5, 'warning_capacity': 4, 'active_count': 2, 'hard_limit': False, 'load_weight': 1.0,
                'general_capacity': 5, 'general_available': 3, 'reserved_capacity': 0, 'reserved_available': 0,
                'leased_capacity': 0, 'lease_available': 0, 'temporary_hold_capacity': 0, 'temporary_hold_available': 0,
                'expected_service_time_s': 300, 'forecast_window_s': 1800, 'forecast_arrivals_count': 0,
            },
            'ops-b': {
                'queue_id': 'ops-b', 'queue_label': 'Ops B', 'queue_family_id': 'ops-family', 'queue_family_label': 'Ops Family',
                'capacity': 5, 'warning_capacity': 4, 'active_count': 1, 'hard_limit': False, 'load_weight': 1.0,
                'general_capacity': 5, 'general_available': 4, 'reserved_capacity': 0, 'reserved_available': 0,
                'leased_capacity': 0, 'lease_available': 0, 'temporary_hold_capacity': 0, 'temporary_hold_available': 0,
                'expected_service_time_s': 300, 'forecast_window_s': 1800, 'forecast_arrivals_count': 0,
            },
        },
    }
    alert = {
        'alert_id': 'alert-1',
        'severity': 'warning',
        'routing': {
            'route_id': 'ops-a-route',
            'queue_id': 'ops-a',
            'queue_label': 'Ops A',
            'queue_family_id': 'ops-family',
            'selection_reason': 'existing_route',
            'updated_at': base_now - 30,
            'route_history': [
                {'queue_id': 'ops-a', 'queue_family_id': 'ops-family', 'at': base_now - 200},
                {'queue_id': 'ops-b', 'queue_family_id': 'ops-family', 'at': base_now - 120},
                {'queue_id': 'ops-a', 'queue_family_id': 'ops-family', 'at': base_now - 60},
            ],
        },
    }
    replay = scheduler._baseline_promotion_simulation_custody_route_replay(
        alert=alert,
        policy={
            'queue_capacity_policy': {'queue_families_enabled': True, 'multi_hop_hysteresis_enabled': True, 'family_reroute_cooldown_s': 300, 'family_recent_hops_threshold': 2, 'family_min_active_delta': 1, 'family_min_load_delta': 0.2, 'family_min_projected_wait_delta_s': 120},
            'routing_routes': [
                {'route_id': 'ops-a-route', 'label': 'Ops A', 'queue_id': 'ops-a', 'queue_label': 'Ops A', 'owner_role': 'shift-lead'},
                {'route_id': 'ops-b-route', 'label': 'Ops B', 'queue_id': 'ops-b', 'queue_label': 'Ops B', 'owner_role': 'shift-lead'},
            ],
            'default_route': {'route_id': 'ops-a-route', 'label': 'Ops A', 'queue_id': 'ops-a', 'queue_label': 'Ops A', 'owner_role': 'shift-lead'},
            'load_aware_routing_enabled': True,
        },
        queue_state=queue_state,
        current_route=dict(alert['routing']),
        comparison_policies=[
            {
                'scenario_id': 'disable_family_hysteresis',
                'label': 'Disable family hysteresis',
                'policy_overrides': {'queue_capacity_policy': {'multi_hop_hysteresis_enabled': False}},
            },
        ],
    )
    assert replay['ok'] is True
    assert replay['current_policy']['route']['queue_id'] == 'ops-a'
    assert replay['current_policy']['explainability']['kept_current_queue'] is True
    assert replay['current_policy']['explainability']['why_kept_current_queue'] == 'family_hysteresis'
    alt = next(item for item in replay['scenarios'] if item['scenario_id'] == 'disable_family_hysteresis')
    assert alt['route']['queue_id'] == 'ops-b'
    assert alt['explainability']['queue_changed'] is True
    assert 'queue_capacity_policy.multi_hop_hysteresis_enabled' in alt['policy_delta_keys']




def test_baseline_promotion_simulation_custody_builtin_policy_what_if_packs_cover_key_domains() -> None:
    scheduler = OpenClawRecoverySchedulerService()
    packs = scheduler._baseline_promotion_simulation_custody_builtin_policy_what_if_packs({
        'queue_capacity_policy': {
            'queue_families_enabled': True,
            'multi_hop_hysteresis_enabled': True,
            'breach_prediction_enabled': True,
            'expedite_enabled': True,
            'admission_control_enabled': True,
            'overload_governance_enabled': True,
        },
    })
    pack_ids = {str(item.get('pack_id') or '') for item in packs}
    assert {'family_hysteresis_presets', 'sla_expedite_presets', 'admission_overload_presets'} <= pack_ids
    family_pack = next(item for item in packs if item['pack_id'] == 'family_hysteresis_presets')
    assert any(scenario['scenario_id'] == 'disable_family_hysteresis' for scenario in family_pack['comparison_policies'])
    sla_pack = next(item for item in packs if item['pack_id'] == 'sla_expedite_presets')
    assert any('expedite' in key for scenario in sla_pack['comparison_policies'] for key in scenario['policy_delta_keys'])



def test_baseline_promotion_simulation_custody_policy_pack_normalization_preserves_registry_metadata() -> None:
    scheduler = OpenClawRecoverySchedulerService()
    pack = scheduler._normalize_baseline_promotion_simulation_custody_policy_what_if_pack(
        {
            'pack_id': 'registry-pack-1',
            'pack_label': 'Registry pack',
            'source': 'registry',
            'registry_entry_id': 'registry_1',
            'registry_scope': 'workspace',
            'promoted_at': 123.0,
            'promoted_by': 'operator',
            'promoted_from_pack_id': 'family_hysteresis_presets',
            'promoted_from_source': 'saved',
            'share_count': 2,
            'last_shared_at': 456.0,
            'last_shared_by': 'ops-lead',
            'share_targets': ['workspace:ws-a'],
            'comparison_policies': [
                {'scenario_id': 'disable_family_hysteresis', 'scenario_label': 'Disable family hysteresis', 'policy_overrides': {'queue_capacity_policy': {'multi_hop_hysteresis_enabled': False}}},
            ],
        },
        actor='operator',
        index=1,
        source='registry',
    )
    assert pack['source'] == 'registry'
    assert pack['registry_entry_id'] == 'registry_1'
    assert pack['registry_scope'] == 'workspace'
    assert pack['promoted_from_pack_id'] == 'family_hysteresis_presets'
    assert pack['share_count'] == 2
    assert pack['share_targets'] == ['workspace:ws-a']

def test_baseline_promotion_simulation_custody_policy_pack_normalization_preserves_catalog_metadata() -> None:
    scheduler = OpenClawRecoverySchedulerService()
    pack = scheduler._normalize_baseline_promotion_simulation_custody_policy_what_if_pack(
        {
            'pack_id': 'catalog-pack-1',
            'pack_label': 'Catalog pack',
            'source': 'catalog',
            'catalog_entry_id': 'catalog_1',
            'catalog_scope': 'environment',
            'catalog_scope_key': 'environment:ws-a:prod',
            'promotion_id': 'promotion-123',
            'workspace_id': 'ws-a',
            'environment': 'prod',
            'portfolio_family_id': 'portfolio-core',
            'runtime_family_id': 'runtime-family-a',
            'catalog_promoted_at': 321.0,
            'catalog_promoted_by': 'operator',
            'catalog_share_count': 3,
            'catalog_last_shared_at': 654.0,
            'catalog_last_shared_by': 'ops-lead',
            'comparison_policies': [
                {'scenario_id': 'disable_hysteresis', 'scenario_label': 'Disable hysteresis', 'policy_overrides': {'queue_capacity_policy': {'multi_hop_hysteresis_enabled': False}}},
            ],
        },
        actor='operator',
        index=1,
        source='catalog',
    )
    assert pack['source'] == 'catalog'
    assert pack['catalog_entry_id'] == 'catalog_1'
    assert pack['catalog_scope'] == 'environment'
    assert pack['catalog_scope_key'] == 'environment:ws-a:prod'
    assert pack['promotion_id'] == 'promotion-123'
    assert pack['portfolio_family_id'] == 'portfolio-core'
    assert pack['runtime_family_id'] == 'runtime-family-a'
    assert pack['catalog_share_count'] == 3
    assert pack['catalog_last_shared_by'] == 'ops-lead'


def test_baseline_promotion_simulation_custody_policy_pack_normalization_preserves_versioned_catalog_lifecycle_metadata() -> None:
    scheduler = OpenClawRecoverySchedulerService()
    pack = scheduler._normalize_baseline_promotion_simulation_custody_policy_what_if_pack(
        {
            'pack_id': 'catalog-pack-v2',
            'pack_label': 'Catalog pack v2',
            'source': 'catalog',
            'catalog_entry_id': 'catalog_entry_v2',
            'catalog_scope': 'global',
            'catalog_scope_key': 'global',
            'catalog_version_key': 'family_hysteresis_presets:global',
            'catalog_version': 2,
            'catalog_lifecycle_state': 'approved',
            'catalog_curated_at': 111.0,
            'catalog_curated_by': 'curator',
            'catalog_approved_at': 222.0,
            'catalog_approved_by': 'approver',
            'catalog_replaced_by_version': 0,
            'catalog_is_latest': True,
            'comparison_policies': [
                {'scenario_id': 'disable_hysteresis', 'scenario_label': 'Disable hysteresis', 'policy_overrides': {'queue_capacity_policy': {'multi_hop_hysteresis_enabled': False}}},
            ],
        },
        actor='operator',
        index=1,
        source='catalog',
    )
    assert pack['catalog_scope'] == 'global'
    assert pack['catalog_version_key'] == 'family_hysteresis_presets:global'
    assert pack['catalog_version'] == 2
    assert pack['catalog_lifecycle_state'] == 'approved'
    assert pack['catalog_curated_by'] == 'curator'
    assert pack['catalog_approved_by'] == 'approver'
    assert pack['catalog_is_latest'] is True



def test_baseline_promotion_simulation_custody_policy_pack_normalization_preserves_approval_and_release_governance_metadata() -> None:
    scheduler = OpenClawRecoverySchedulerService()
    pack = scheduler._normalize_baseline_promotion_simulation_custody_policy_what_if_pack(
        {
            'pack_id': 'catalog-pack-approved-release',
            'pack_label': 'Catalog pack approved release',
            'source': 'catalog',
            'catalog_entry_id': 'catalog_entry_release',
            'catalog_scope': 'global',
            'catalog_version_key': 'family_hysteresis_presets:global',
            'catalog_version': 3,
            'catalog_lifecycle_state': 'approved',
            'catalog_approval_required': True,
            'catalog_required_approvals': 2,
            'catalog_approval_count': 2,
            'catalog_approval_state': 'approved',
            'catalog_approval_requested_by': 'ops-lead',
            'catalog_approvals': [
                {'approval_id': 'a1', 'decision': 'approved', 'actor': 'approver-a', 'role': 'governance', 'at': 111.0},
                {'approval_id': 'a2', 'decision': 'approved', 'actor': 'approver-b', 'role': 'security', 'at': 222.0},
            ],
            'catalog_release_state': 'released',
            'catalog_release_train_id': 'train-1',
            'catalog_release_notes': 'ship globally',
            'catalog_release_staged_by': 'release-manager',
            'catalog_released_by': 'release-manager',
            'catalog_attestation_count': 1,
            'catalog_latest_attestation': {'report_id': 'report-1', 'report_type': 'openmiura_routing_policy_pack_catalog_attestation_v1'},
            'comparison_policies': [
                {'scenario_id': 'disable_hysteresis', 'scenario_label': 'Disable hysteresis', 'policy_overrides': {'queue_capacity_policy': {'multi_hop_hysteresis_enabled': False}}},
            ],
        },
        actor='operator',
        index=1,
        source='catalog',
    )
    assert pack['catalog_approval_required'] is True
    assert pack['catalog_required_approvals'] == 2
    assert pack['catalog_approval_count'] == 2
    assert pack['catalog_approval_state'] == 'approved'
    assert pack['catalog_approvals'][0]['approval_id'] == 'a1'
    assert pack['catalog_release_state'] == 'released'
    assert pack['catalog_release_train_id'] == 'train-1'
    assert pack['catalog_attestation_count'] == 1
    assert pack['catalog_latest_attestation']['report_id'] == 'report-1'


def test_baseline_promotion_simulation_custody_route_selection_bypasses_family_hysteresis_for_expedite(monkeypatch) -> None:
    base_now = 1_785_788_200.0
    _set_now(monkeypatch, base_now)
    scheduler = OpenClawRecoverySchedulerService()
    queue_state = {
        'policy': {
            'queue_families_enabled': True,
            'multi_hop_hysteresis_enabled': True,
            'family_reroute_cooldown_s': 300,
            'family_recent_hops_threshold': 2,
            'family_min_active_delta': 1,
            'family_min_load_delta': 0.2,
            'family_min_projected_wait_delta_s': 120,
            'breach_prediction_enabled': True,
            'expected_service_time_s': 300,
            'expedite_enabled': True,
            'expedite_threshold_s': 300,
            'expedite_bypass_family_hysteresis': True,
            'anti_thrashing_enabled': False,
        },
        'queues': {
            'ops-a': {
                'queue_id': 'ops-a', 'queue_label': 'Ops A', 'queue_family_id': 'ops-family', 'queue_family_label': 'Ops Family',
                'capacity': 5, 'warning_capacity': 4, 'active_count': 2, 'hard_limit': False, 'load_weight': 1.0,
                'general_capacity': 5, 'general_available': 3, 'reserved_capacity': 0, 'reserved_available': 0,
                'leased_capacity': 0, 'lease_available': 0, 'temporary_hold_capacity': 0, 'temporary_hold_available': 0,
                'expected_service_time_s': 300, 'forecast_window_s': 1800, 'forecast_arrivals_count': 0,
            },
            'ops-b': {
                'queue_id': 'ops-b', 'queue_label': 'Ops B', 'queue_family_id': 'ops-family', 'queue_family_label': 'Ops Family',
                'capacity': 5, 'warning_capacity': 4, 'active_count': 1, 'hard_limit': False, 'load_weight': 1.0,
                'general_capacity': 5, 'general_available': 4, 'reserved_capacity': 0, 'reserved_available': 0,
                'leased_capacity': 0, 'lease_available': 0, 'temporary_hold_capacity': 0, 'temporary_hold_available': 0,
                'expected_service_time_s': 300, 'forecast_window_s': 1800, 'forecast_arrivals_count': 0,
            },
        },
    }
    route = scheduler._select_baseline_promotion_simulation_custody_route_by_load(
        routes=[
            {'route_id': 'ops-a-route', 'label': 'Ops A', 'queue_id': 'ops-a', 'queue_label': 'Ops A', 'owner_role': 'shift-lead'},
            {'route_id': 'ops-b-route', 'label': 'Ops B', 'queue_id': 'ops-b', 'queue_label': 'Ops B', 'owner_role': 'shift-lead'},
        ],
        queue_state=queue_state,
        current_queue_id='ops-a',
        prefer_lowest_load=True,
        alert={
            'severity': 'warning',
            'sla_state': {'status': 'warning', 'targets': {'acknowledge': {'enabled': True, 'status': 'warning', 'remaining_s': 120}}},
            'routing': {
                'queue_id': 'ops-a',
                'updated_at': base_now - 30,
                'route_history': [
                    {'queue_id': 'ops-a', 'queue_family_id': 'ops-family', 'at': base_now - 220},
                    {'queue_id': 'ops-b', 'queue_family_id': 'ops-family', 'at': base_now - 120},
                    {'queue_id': 'ops-a', 'queue_family_id': 'ops-family', 'at': base_now - 60},
                ],
            },
        },
        policy={'queue_capacity_policy': {'queue_families_enabled': True, 'multi_hop_hysteresis_enabled': True, 'family_reroute_cooldown_s': 300, 'family_recent_hops_threshold': 2, 'family_min_active_delta': 1, 'family_min_load_delta': 0.2, 'family_min_projected_wait_delta_s': 120, 'breach_prediction_enabled': True, 'expected_service_time_s': 300, 'expedite_enabled': True, 'expedite_threshold_s': 300, 'expedite_bypass_family_hysteresis': True}},
    )
    assert route['queue_id'] == 'ops-b'
    assert route['expedite_applied'] is True
    assert route['selection_reason'] == 'expedite_bypass_family_hysteresis'
    assert route['family_hysteresis_applied'] is False
    assert route['family_hysteresis_reason'] == 'bypass_expedite_alert'



def test_baseline_promotion_simulation_custody_queue_capacity_state_tracks_queue_families(monkeypatch) -> None:
    base_now = 1_785_788_500.0
    _set_now(monkeypatch, base_now)
    scheduler = OpenClawRecoverySchedulerService()

    class _Audit:
        @staticmethod
        def list_release_bundles(**kwargs):
            return []

    class _GatewayStub:
        audit = _Audit()

    state = scheduler._baseline_promotion_simulation_custody_queue_capacity_state(
        _GatewayStub(),
        policy={
            'queue_capacity_policy': {
                'queue_families_enabled': True,
                'default_queue_family': 'general-family',
            },
            'queue_capacities': [
                {'queue_id': 'ops-a', 'queue_label': 'Ops A', 'capacity': 3, 'queue_family_id': 'ops-family', 'queue_family_label': 'Ops Family'},
                {'queue_id': 'ops-b', 'queue_label': 'Ops B', 'capacity': 3, 'queue_family_id': 'ops-family', 'queue_family_label': 'Ops Family'},
                {'queue_id': 'triage', 'queue_label': 'Triage', 'capacity': 2, 'queue_family_id': 'triage-family', 'queue_family_label': 'Triage Family'},
            ],
        },
        tenant_id='tenant-a',
        workspace_id='ws-a',
        environment='prod',
    )
    assert state['queues']['ops-a']['queue_family_id'] == 'ops-family'
    assert state['queues']['ops-b']['queue_family_id'] == 'ops-family'
    assert state['summary']['queue_family_count'] == 2
    assert state['summary']['largest_queue_family_id'] == 'ops-family'
    assert state['summary']['largest_queue_family_size'] == 2
