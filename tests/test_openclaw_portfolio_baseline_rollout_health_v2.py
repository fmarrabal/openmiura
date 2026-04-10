from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import app as app_module
from openmiura.gateway import Gateway
from tests.test_openclaw_portfolio_baseline_catalog_promotion_v2 import (
    _create_baseline_catalog,
    _create_portfolio_with_catalog,
)
from tests.test_openclaw_portfolio_baseline_release_trains_v2 import _baseline_catalog, _env_policy
from tests.test_openclaw_portfolio_environment_tiered_governance_v2 import _create_runtime_for_environment
from tests.test_openclaw_portfolio_evidence_packaging_v2 import _set_now, _write_config


def test_baseline_rollout_groups_and_dependencies_shape_waves(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_742_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='baseline-rollout-grouped-catalog',
            version='catalog-v1',
            environment_policy_baselines=_baseline_catalog(),
            promotion_policy={'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'gov', 'requested_role': 'governance-board', 'label': 'Governance board'}]}},
        )
        runtime_a = _create_runtime_for_environment(client, headers, name='runtime-baseline-group-a', environment='prod')
        runtime_b = _create_runtime_for_environment(client, headers, name='runtime-baseline-group-b', environment='prod')
        runtime_c = _create_runtime_for_environment(client, headers, name='runtime-baseline-group-c', environment='prod')
        portfolio_a = _create_portfolio_with_catalog(
            client,
            headers,
            base_now=base_now + 1,
            runtime_id=runtime_a,
            environment='prod',
            environment_tier_policies=_env_policy('baseline-v2'),
            baseline_catalog_ref={'catalog_id': catalog['catalog_id']},
        )
        portfolio_b = _create_portfolio_with_catalog(
            client,
            headers,
            base_now=base_now + 2,
            runtime_id=runtime_b,
            environment='prod',
            environment_tier_policies=_env_policy('baseline-v2'),
            baseline_catalog_ref={'catalog_id': catalog['catalog_id']},
        )
        portfolio_c = _create_portfolio_with_catalog(
            client,
            headers,
            base_now=base_now + 3,
            runtime_id=runtime_c,
            environment='prod',
            environment_tier_policies=_env_policy('baseline-v2'),
            baseline_catalog_ref={'catalog_id': catalog['catalog_id']},
        )

        promotion = client.post(
            f'/admin/openclaw/alert-governance/baseline-catalogs/{catalog["catalog_id"]}/promotions',
            headers=headers,
            json={
                'actor': 'catalog-admin',
                'version': 'catalog-v2',
                'environment_policy_baselines': {'prod': {'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v2'}}},
                'rollout_policy': {
                    'enabled': True,
                    'wave_size': 2,
                    'auto_apply_first_wave': True,
                    'require_manual_advance': True,
                    'portfolio_groups': [
                        {'group_id': 'core', 'group_label': 'core wave', 'portfolio_ids': [portfolio_a, portfolio_b]},
                        {'group_id': 'edge', 'group_label': 'edge wave', 'portfolio_ids': [portfolio_c], 'depends_on_groups': ['core']},
                    ],
                },
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
            json={'actor': 'governance-board', 'reason': 'shape rollout by groups', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert approved.status_code == 200, approved.text
        payload = approved.json()
        rollout_plan = payload['baseline_promotion']['rollout_plan']
        assert rollout_plan['wave_count'] == 2
        assert rollout_plan['group_summary']['group_count'] == 2
        first_wave = rollout_plan['items'][0]
        second_wave = rollout_plan['items'][1]
        assert first_wave['group_ids'] == ['core']
        assert set(first_wave['portfolio_ids']) == {portfolio_a, portfolio_b}
        assert first_wave['gate_evaluation']['passed'] is True
        assert second_wave['group_ids'] == ['edge']
        assert second_wave['dependency_summary']['depends_on_group_ids'] == ['core']
        assert second_wave['dependency_summary']['depends_on_wave_nos'] == [1]
        analytics = payload['analytics']
        assert analytics['group_count'] == 2
        assert analytics['dependency_edge_count'] >= 1
        assert analytics['wave_health_curve'][0]['group_ids'] == ['core']
        assert analytics['wave_health_curve'][1]['depends_on_wave_nos'] == [1]


def test_baseline_rollout_richer_slo_gate_and_health_analytics(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_743_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='baseline-rollout-health-catalog',
            version='catalog-v1',
            environment_policy_baselines=_baseline_catalog(),
            promotion_policy={'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'gov', 'requested_role': 'governance-board', 'label': 'Governance board'}]}},
        )
        runtime_a = _create_runtime_for_environment(client, headers, name='runtime-baseline-health-a', environment='prod')
        runtime_b = _create_runtime_for_environment(client, headers, name='runtime-baseline-health-b', environment='prod')
        _create_portfolio_with_catalog(
            client,
            headers,
            base_now=base_now + 1,
            runtime_id=runtime_a,
            environment='prod',
            environment_tier_policies=_env_policy('baseline-v2'),
            baseline_catalog_ref={'catalog_id': catalog['catalog_id']},
        )
        _create_portfolio_with_catalog(
            client,
            headers,
            base_now=base_now + 2,
            runtime_id=runtime_b,
            environment='prod',
            environment_tier_policies=_env_policy('baseline-v1'),
            baseline_catalog_ref={'catalog_id': catalog['catalog_id']},
        )

        promotion = client.post(
            f'/admin/openclaw/alert-governance/baseline-catalogs/{catalog["catalog_id"]}/promotions',
            headers=headers,
            json={
                'actor': 'catalog-admin',
                'version': 'catalog-v2',
                'environment_policy_baselines': {'prod': {'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v2'}}},
                'rollout_policy': {'enabled': True, 'wave_size': 1, 'auto_apply_first_wave': True, 'require_manual_advance': True},
                'gate_policy': {
                    'enabled': True,
                    'block_on_nonconformant': True,
                    'max_nonconformant_count': 0,
                    'max_nonconformant_ratio': 0.0,
                    'block_on_health_regression': True,
                    'max_nonconformant_delta': 0,
                },
                'rollback_policy': {'enabled': False},
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
            json={'actor': 'governance-board', 'reason': 'exercise health gate', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()['baseline_promotion']['rollout_plan']['items'][0]['gate_evaluation']['passed'] is True

        advanced = client.post(
            f'/admin/openclaw/alert-governance/baseline-promotions/{promotion_id}/actions/advance',
            headers=headers,
            json={'actor': 'governance-board', 'reason': 'run unhealthy second wave', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert advanced.status_code == 200, advanced.text
        payload = advanced.json()
        assert payload['release']['status'] == 'gate_failed'
        second_wave = payload['baseline_promotion']['rollout_plan']['items'][1]
        gate_evaluation = second_wave['gate_evaluation']
        assert gate_evaluation['passed'] is False
        assert gate_evaluation['status'] == 'failed'
        assert gate_evaluation['summary']['nonconformant_count'] == 1
        assert gate_evaluation['summary']['nonconformant_ratio'] == 1.0
        assert 'nonconformant_portfolios' in gate_evaluation['reasons']
        assert 'nonconformant_ratio_exceeded' in gate_evaluation['reasons']
        assert 'nonconformant_regression' in gate_evaluation['reasons']
        analytics = payload['analytics']
        assert analytics['gate_failed'] is True
        assert analytics['gate_failed_wave_no'] == 2
        assert analytics['gate_reason_counts']['nonconformant_ratio_exceeded'] >= 1
        assert analytics['latest_health']['wave_no'] == 2
        assert analytics['latest_health']['nonconformant_ratio'] == 1.0
        assert analytics['wave_health_curve'][1]['reasons']


def test_baseline_rollout_dependency_cycle_is_rejected(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_744_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='baseline-rollout-cycle-catalog',
            version='catalog-v1',
            environment_policy_baselines=_baseline_catalog(),
            promotion_policy={'approval_policy': {'enabled': False, 'layers': []}},
        )
        runtime_a = _create_runtime_for_environment(client, headers, name='runtime-baseline-cycle-a', environment='prod')
        runtime_b = _create_runtime_for_environment(client, headers, name='runtime-baseline-cycle-b', environment='prod')
        portfolio_a = _create_portfolio_with_catalog(
            client,
            headers,
            base_now=base_now + 1,
            runtime_id=runtime_a,
            environment='prod',
            environment_tier_policies=_env_policy('baseline-v2'),
            baseline_catalog_ref={'catalog_id': catalog['catalog_id']},
        )
        portfolio_b = _create_portfolio_with_catalog(
            client,
            headers,
            base_now=base_now + 2,
            runtime_id=runtime_b,
            environment='prod',
            environment_tier_policies=_env_policy('baseline-v2'),
            baseline_catalog_ref={'catalog_id': catalog['catalog_id']},
        )

        response = client.post(
            f'/admin/openclaw/alert-governance/baseline-catalogs/{catalog["catalog_id"]}/promotions',
            headers=headers,
            json={
                'actor': 'catalog-admin',
                'version': 'catalog-v2',
                'environment_policy_baselines': {'prod': {'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v2'}}},
                'rollout_policy': {
                    'enabled': True,
                    'auto_apply_first_wave': False,
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
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload['ok'] is False
        assert payload['error'] == 'baseline_rollout_plan_invalid'
        assert payload['validation']['status'] == 'failed'
        assert any(item['code'] == 'dependency_cycle_detected' for item in payload['validation']['errors'])


def test_baseline_rollout_exclusive_groups_add_operational_dependency(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_745_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='baseline-rollout-exclusive-catalog',
            version='catalog-v1',
            environment_policy_baselines=_baseline_catalog(),
            promotion_policy={'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'gov', 'requested_role': 'governance-board', 'label': 'Governance board'}]}},
        )
        runtime_a = _create_runtime_for_environment(client, headers, name='runtime-baseline-exclusive-a', environment='prod')
        runtime_b = _create_runtime_for_environment(client, headers, name='runtime-baseline-exclusive-b', environment='prod')
        portfolio_a = _create_portfolio_with_catalog(
            client,
            headers,
            base_now=base_now + 1,
            runtime_id=runtime_a,
            environment='prod',
            environment_tier_policies=_env_policy('baseline-v2'),
            baseline_catalog_ref={'catalog_id': catalog['catalog_id']},
        )
        portfolio_b = _create_portfolio_with_catalog(
            client,
            headers,
            base_now=base_now + 2,
            runtime_id=runtime_b,
            environment='prod',
            environment_tier_policies=_env_policy('baseline-v2'),
            baseline_catalog_ref={'catalog_id': catalog['catalog_id']},
        )

        promotion = client.post(
            f'/admin/openclaw/alert-governance/baseline-catalogs/{catalog["catalog_id"]}/promotions',
            headers=headers,
            json={
                'actor': 'catalog-admin',
                'version': 'catalog-v2',
                'environment_policy_baselines': {'prod': {'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v2'}}},
                'rollout_policy': {
                    'enabled': True,
                    'wave_size': 1,
                    'auto_apply_first_wave': True,
                    'require_manual_advance': True,
                    'portfolio_groups': [
                        {'group_id': 'core', 'portfolio_ids': [portfolio_a]},
                        {'group_id': 'audit', 'portfolio_ids': [portfolio_b], 'exclusive_with_groups': ['core']},
                    ],
                },
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
            json={'actor': 'governance-board', 'reason': 'exercise exclusive rollout dependency', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert approved.status_code == 200, approved.text
        payload = approved.json()
        second_wave = payload['baseline_promotion']['rollout_plan']['items'][1]
        assert second_wave['dependency_summary']['exclusive_with_groups'] == ['core']
        assert second_wave['dependency_summary']['exclusive_depends_on_wave_nos'] == [1]
        assert second_wave['dependency_summary']['depends_on_wave_nos'] == [1]
