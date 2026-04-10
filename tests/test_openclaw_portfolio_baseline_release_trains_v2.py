from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import app as app_module
from openmiura.gateway import Gateway
from tests.test_openclaw_portfolio_baseline_catalog_promotion_v2 import (
    _create_baseline_catalog,
    _create_portfolio_with_catalog,
)
from tests.test_openclaw_portfolio_environment_tiered_governance_v2 import _create_runtime_for_environment
from tests.test_openclaw_portfolio_evidence_packaging_v2 import _set_now, _write_config


def _portfolio_detail(client: TestClient, headers: dict[str, str], portfolio_id: str) -> dict:
    response = client.get(
        f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _baseline_catalog() -> dict[str, object]:
    return {
        'prod': {
            'operational_tier': 'prod',
            'evidence_classification': 'regulated-enterprise-evidence',
            'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'}]},
            'security_gate_policy': {'enabled': True, 'envelope_label': 'prod-envelope', 'min_approval_layers': 1, 'required_approval_roles': ['ops-director'], 'block_on_nonconformance': True},
            'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v1'},
        },
    }


def _env_policy(signing_key_id: str) -> dict[str, object]:
    return {
        'prod': {
            'operational_tier': 'prod',
            'evidence_classification': 'regulated-enterprise-evidence',
            'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'}]},
            'security_gate_policy': {'enabled': True, 'envelope_label': 'prod-envelope', 'min_approval_layers': 1, 'required_approval_roles': ['ops-director'], 'block_on_nonconformance': True},
            'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': signing_key_id},
        },
    }


def test_baseline_release_train_rolls_out_by_waves_and_completes(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_730_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='release-train-catalog',
            version='catalog-v1',
            environment_policy_baselines=_baseline_catalog(),
            promotion_policy={'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'gov', 'requested_role': 'governance-board', 'label': 'Governance board'}]}},
        )
        runtime_a = _create_runtime_for_environment(client, headers, name='runtime-release-train-a', environment='prod')
        runtime_b = _create_runtime_for_environment(client, headers, name='runtime-release-train-b', environment='prod')
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
                'rollout_policy': {'enabled': True, 'wave_size': 1, 'auto_apply_first_wave': True, 'require_manual_advance': True},
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
            json={'actor': 'governance-board', 'reason': 'start staged rollout', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert approved.status_code == 200, approved.text
        approved_payload = approved.json()
        assert approved_payload['release']['status'] == 'awaiting_advance'
        rollout_plan = approved_payload['baseline_promotion']['rollout_plan']
        assert rollout_plan['wave_count'] == 2
        assert rollout_plan['completed_wave_count'] == 1
        first_wave = rollout_plan['items'][0]
        second_wave = rollout_plan['items'][1]
        assert first_wave['gate_evaluation']['passed'] is True

        first_portfolio_id = first_wave['portfolio_ids'][0]
        second_portfolio_id = second_wave['portfolio_ids'][0]
        assert {first_portfolio_id, second_portfolio_id} == {portfolio_a, portfolio_b}

        first_detail = _portfolio_detail(client, headers, first_portfolio_id)
        second_detail = _portfolio_detail(client, headers, second_portfolio_id)
        assert first_detail['policy_baseline_drift']['overall_status'] == 'aligned'
        assert first_detail['portfolio']['baseline_catalog_rollout']['active'] is True
        assert second_detail['policy_baseline_drift']['overall_status'] == 'drifted'

        advanced = client.post(
            f'/admin/openclaw/alert-governance/baseline-promotions/{promotion_id}/actions/advance',
            headers=headers,
            json={'actor': 'governance-board', 'reason': 'advance next wave', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert advanced.status_code == 200, advanced.text
        advanced_payload = advanced.json()
        assert advanced_payload['release']['status'] == 'completed'
        assert advanced_payload['catalog']['baseline_catalog']['current_version']['catalog_version'] == 'catalog-v2'

        for portfolio_id in (portfolio_a, portfolio_b):
            detail = _portfolio_detail(client, headers, portfolio_id)
            assert detail['policy_baseline_drift']['overall_status'] == 'aligned'
            assert detail['portfolio']['baseline_catalog_rollout']['status'] == 'completed'
            assert detail['portfolio']['baseline_catalog_rollout']['active'] is False


def test_baseline_release_train_gate_failure_triggers_rollback(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_731_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='release-train-rollback-catalog',
            version='catalog-v1',
            environment_policy_baselines=_baseline_catalog(),
            promotion_policy={'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'gov', 'requested_role': 'governance-board', 'label': 'Governance board'}]}},
        )
        runtime_id = _create_runtime_for_environment(client, headers, name='runtime-release-train-rollback', environment='prod')
        portfolio_id = _create_portfolio_with_catalog(
            client,
            headers,
            base_now=base_now + 1,
            runtime_id=runtime_id,
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
            json={'actor': 'governance-board', 'reason': 'start staged rollout', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert approved.status_code == 200, approved.text
        payload = approved.json()
        assert payload['release']['status'] == 'rolled_back'
        assert payload['rollback_attestations']['summary']['count'] == 1
        assert payload['catalog']['baseline_catalog']['current_version']['catalog_version'] == 'catalog-v1'
        assert any(item['label'] == 'baseline_promotion_rolled_back' for item in payload['timeline']['items'])

        detail = _portfolio_detail(client, headers, portfolio_id)
        assert detail['policy_baseline_drift']['overall_status'] == 'aligned'
        assert detail['portfolio']['baseline_catalog_rollout']['status'] == 'rolled_back'
        assert detail['portfolio']['baseline_catalog_rollout']['active'] is False


def test_baseline_release_train_observability_and_manual_rollback(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_732_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='release-train-observability-catalog',
            version='catalog-v1',
            environment_policy_baselines=_baseline_catalog(),
            promotion_policy={'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'gov', 'requested_role': 'governance-board', 'label': 'Governance board'}]}},
        )
        runtime_a = _create_runtime_for_environment(client, headers, name='runtime-release-train-obs-a', environment='prod')
        runtime_b = _create_runtime_for_environment(client, headers, name='runtime-release-train-obs-b', environment='prod')
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
                'rollout_policy': {'enabled': True, 'wave_size': 1, 'auto_apply_first_wave': True, 'require_manual_advance': True},
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
            json={'actor': 'governance-board', 'reason': 'start staged rollout', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert approved.status_code == 200, approved.text
        approved_payload = approved.json()
        assert approved_payload['analytics']['wave_count'] == 2
        assert approved_payload['analytics']['rollback_attestation_count'] == 0

        detail = client.get(
            f'/admin/openclaw/alert-governance/baseline-promotions/{promotion_id}?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert detail.status_code == 200, detail.text
        detail_payload = detail.json()
        assert detail_payload['analytics']['completed_wave_count'] == 1

        timeline = client.get(
            f'/admin/openclaw/alert-governance/baseline-promotions/{promotion_id}/timeline?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert timeline.status_code == 200, timeline.text
        labels = [item['label'] for item in timeline.json()['timeline']]
        assert 'baseline_promotion_created' in labels
        assert 'baseline_promotion_approved' in labels
        assert 'baseline_promotion_wave_applied' in labels
        assert 'baseline_promotion_wave_gate_passed' in labels

        rollback = client.post(
            f'/admin/openclaw/alert-governance/baseline-promotions/{promotion_id}/actions/rollback',
            headers=headers,
            json={'actor': 'governance-board', 'reason': 'abort before next wave', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert rollback.status_code == 200, rollback.text
        rollback_payload = rollback.json()
        assert rollback_payload['release']['status'] == 'rolled_back'
        assert rollback_payload['rollback_attestations']['summary']['count'] == 1

        timeline_after = client.get(
            f'/admin/openclaw/alert-governance/baseline-promotions/{promotion_id}/timeline?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert timeline_after.status_code == 200, timeline_after.text
        labels_after = [item['label'] for item in timeline_after.json()['timeline']]
        assert 'baseline_promotion_rolled_back' in labels_after
