from __future__ import annotations

from datetime import datetime, timezone
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


def _list_jobs(client: TestClient, headers: dict[str, str], *, promotion_id: str | None = None) -> dict:
    suffix = f'&promotion_id={promotion_id}' if promotion_id else ''
    response = client.get(
        f'/admin/openclaw/alert-governance/baseline-advance-jobs?tenant_id=tenant-a&workspace_id=ws-a&environment=prod{suffix}',
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_baseline_rollout_auto_advance_window_schedules_job_and_completes_next_wave(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_733_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='baseline-rollout-jobs-catalog',
            version='catalog-v1',
            environment_policy_baselines=_baseline_catalog(),
            promotion_policy={'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'gov', 'requested_role': 'governance-board', 'label': 'Governance board'}]}},
        )
        runtime_a = _create_runtime_for_environment(client, headers, name='runtime-baseline-jobs-a', environment='prod')
        runtime_b = _create_runtime_for_environment(client, headers, name='runtime-baseline-jobs-b', environment='prod')
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
                'rollout_policy': {
                    'enabled': True,
                    'wave_size': 1,
                    'auto_apply_first_wave': True,
                    'require_manual_advance': True,
                    'auto_advance': True,
                    'auto_advance_window_s': 30,
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
            json={'actor': 'governance-board', 'reason': 'start staged rollout with auto window', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert approved.status_code == 200, approved.text
        approved_payload = approved.json()
        assert approved_payload['release']['status'] == 'awaiting_advance_window'
        assert approved_payload['scheduled_advance_job'] is not None
        assert approved_payload['analytics']['completed_wave_count'] == 1
        assert approved_payload['advance_jobs']['summary']['count'] == 1
        assert approved_payload['advance_jobs']['summary']['due'] == 0

        not_due = client.post(
            '/admin/openclaw/alert-governance/baseline-advance-jobs/run-due',
            headers=headers,
            json={'actor': 'baseline-release-bot', 'promotion_id': promotion_id, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert not_due.status_code == 200, not_due.text
        assert not_due.json()['summary']['executed'] == 0

        _set_now(monkeypatch, base_now + 31)
        due = client.post(
            '/admin/openclaw/alert-governance/baseline-advance-jobs/run-due',
            headers=headers,
            json={'actor': 'baseline-release-bot', 'promotion_id': promotion_id, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert due.status_code == 200, due.text
        due_payload = due.json()
        assert due_payload['summary']['executed'] == 1
        assert due_payload['items'][0]['result']['status'] == 'advanced'

        detail = client.get(
            f'/admin/openclaw/alert-governance/baseline-promotions/{promotion_id}?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert detail.status_code == 200, detail.text
        detail_payload = detail.json()
        assert detail_payload['release']['status'] == 'completed'
        assert detail_payload['catalog']['baseline_catalog']['current_version']['catalog_version'] == 'catalog-v2'
        labels = [item['label'] for item in detail_payload['timeline']['items']]
        assert 'baseline_promotion_wave_auto_advance_scheduled' in labels
        assert 'baseline_promotion_wave_auto_advance_advanced' in labels


def test_manual_baseline_advance_cancels_scheduled_job(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_734_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='baseline-rollout-jobs-manual-catalog',
            version='catalog-v1',
            environment_policy_baselines=_baseline_catalog(),
            promotion_policy={'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'gov', 'requested_role': 'governance-board', 'label': 'Governance board'}]}},
        )
        runtime_a = _create_runtime_for_environment(client, headers, name='runtime-baseline-manual-a', environment='prod')
        runtime_b = _create_runtime_for_environment(client, headers, name='runtime-baseline-manual-b', environment='prod')
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
                'rollout_policy': {
                    'enabled': True,
                    'wave_size': 1,
                    'auto_apply_first_wave': True,
                    'require_manual_advance': True,
                    'auto_advance': True,
                    'auto_advance_window_s': 60,
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
            json={'actor': 'governance-board', 'reason': 'stage first wave', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()['advance_jobs']['summary']['count'] == 1

        manual_advance = client.post(
            f'/admin/openclaw/alert-governance/baseline-promotions/{promotion_id}/actions/advance',
            headers=headers,
            json={'actor': 'governance-board', 'reason': 'advance manually before window', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert manual_advance.status_code == 200, manual_advance.text
        manual_payload = manual_advance.json()
        assert manual_payload['release']['status'] == 'completed'

        _set_now(monkeypatch, base_now + 120)
        due = client.post(
            '/admin/openclaw/alert-governance/baseline-advance-jobs/run-due',
            headers=headers,
            json={'actor': 'baseline-release-bot', 'promotion_id': promotion_id, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert due.status_code == 200, due.text
        assert due.json()['summary']['executed'] == 0

        jobs = _list_jobs(client, headers, promotion_id=promotion_id)
        assert jobs['summary']['due'] == 0



def test_baseline_rollout_maintenance_window_reprograms_auto_advance_job(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_735_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='baseline-rollout-maintenance-catalog',
            version='catalog-v1',
            environment_policy_baselines=_baseline_catalog(),
            promotion_policy={'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'gov', 'requested_role': 'governance-board', 'label': 'Governance board'}]}},
        )
        runtime_a = _create_runtime_for_environment(client, headers, name='runtime-baseline-maint-a', environment='prod')
        runtime_b = _create_runtime_for_environment(client, headers, name='runtime-baseline-maint-b', environment='prod')
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
                'rollout_policy': {
                    'enabled': True,
                    'wave_size': 1,
                    'auto_apply_first_wave': True,
                    'require_manual_advance': True,
                    'auto_advance': True,
                    'auto_advance_window_s': 10,
                    'maintenance_windows': [
                        {'window_id': 'mw-1', 'label': 'prod-maintenance', 'start_at': base_now + 30, 'end_at': base_now + 90, 'reason': 'planned release window'},
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
            json={'actor': 'governance-board', 'reason': 'respect maintenance window', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert approved.status_code == 200, approved.text
        approved_payload = approved.json()
        assert approved_payload['release']['status'] == 'awaiting_advance_window'
        scheduled_job = approved_payload['scheduled_advance_job']
        assert scheduled_job is not None
        assert float(scheduled_job['next_run_at']) == base_now + 30
        assert approved_payload['baseline_promotion']['rollout_plan']['items'][0]['scheduled_advance']['calendar_blockers'] == ['maintenance_window']

        _set_now(monkeypatch, base_now + 31)
        due = client.post(
            '/admin/openclaw/alert-governance/baseline-advance-jobs/run-due',
            headers=headers,
            json={'actor': 'baseline-release-bot', 'promotion_id': promotion_id, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert due.status_code == 200, due.text
        assert due.json()['summary']['executed'] == 1
        assert due.json()['items'][0]['result']['status'] == 'advanced'

        detail = client.get(
            f'/admin/openclaw/alert-governance/baseline-promotions/{promotion_id}?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert detail.status_code == 200, detail.text
        assert detail.json()['release']['status'] == 'completed'



def test_baseline_rollout_freeze_window_pushes_auto_advance_to_unfreeze(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_736_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='baseline-rollout-freeze-catalog',
            version='catalog-v1',
            environment_policy_baselines=_baseline_catalog(),
            promotion_policy={'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'gov', 'requested_role': 'governance-board', 'label': 'Governance board'}]}},
        )
        runtime_a = _create_runtime_for_environment(client, headers, name='runtime-baseline-freeze-a', environment='prod')
        runtime_b = _create_runtime_for_environment(client, headers, name='runtime-baseline-freeze-b', environment='prod')
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
                'rollout_policy': {
                    'enabled': True,
                    'wave_size': 1,
                    'auto_apply_first_wave': True,
                    'require_manual_advance': True,
                    'auto_advance': True,
                    'auto_advance_window_s': 10,
                    'freeze_windows': [
                        {'window_id': 'freeze-1', 'label': 'quarter-end-freeze', 'start_at': base_now + 10, 'end_at': base_now + 40, 'reason': 'quarter close'},
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
            json={'actor': 'governance-board', 'reason': 'respect freeze window', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert approved.status_code == 200, approved.text
        approved_payload = approved.json()
        scheduled_job = approved_payload['scheduled_advance_job']
        assert scheduled_job is not None
        assert float(scheduled_job['next_run_at']) == base_now + 40
        assert approved_payload['baseline_promotion']['rollout_plan']['items'][0]['scheduled_advance']['calendar_blockers'] == ['freeze_window']

        _set_now(monkeypatch, base_now + 41)
        due = client.post(
            '/admin/openclaw/alert-governance/baseline-advance-jobs/run-due',
            headers=headers,
            json={'actor': 'baseline-release-bot', 'promotion_id': promotion_id, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert due.status_code == 200, due.text
        assert due.json()['summary']['executed'] == 1
        assert due.json()['items'][0]['result']['status'] == 'advanced'

        detail = client.get(
            f'/admin/openclaw/alert-governance/baseline-promotions/{promotion_id}?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert detail.status_code == 200, detail.text
        assert detail.json()['release']['status'] == 'completed'



def test_baseline_rollout_retry_backoff_reschedules_failed_auto_advance(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_737_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='baseline-rollout-retry-catalog',
            version='catalog-v1',
            environment_policy_baselines=_baseline_catalog(),
            promotion_policy={'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'gov', 'requested_role': 'governance-board', 'label': 'Governance board'}]}},
        )
        runtime_a = _create_runtime_for_environment(client, headers, name='runtime-baseline-retry-a', environment='prod')
        runtime_b = _create_runtime_for_environment(client, headers, name='runtime-baseline-retry-b', environment='prod')
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
                'rollout_policy': {
                    'enabled': True,
                    'wave_size': 1,
                    'auto_apply_first_wave': True,
                    'require_manual_advance': True,
                    'auto_advance': True,
                    'auto_advance_window_s': 10,
                    'retry_policy': {'enabled': True, 'max_retries': 2, 'backoff_s': 20, 'backoff_multiplier': 2.0, 'max_backoff_s': 60},
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
            json={'actor': 'governance-board', 'reason': 'exercise retry policy', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert approved.status_code == 200, approved.text

        jobs_before = _list_jobs(client, headers, promotion_id=promotion_id)
        job_id = jobs_before['items'][0]['job_id']
        gw = client.app.state.gw
        tampered_definition = dict(jobs_before['items'][0]['workflow_definition'] or {})
        tampered_definition['next_wave_no'] = 99
        gw.audit.update_job_schedule(job_id, workflow_definition=tampered_definition, tenant_id='tenant-a', workspace_id='ws-a', environment='prod')

        _set_now(monkeypatch, base_now + 11)
        first_due = client.post(
            '/admin/openclaw/alert-governance/baseline-advance-jobs/run-due',
            headers=headers,
            json={'actor': 'baseline-release-bot', 'promotion_id': promotion_id, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert first_due.status_code == 200, first_due.text
        first_payload = first_due.json()
        assert first_payload['summary']['executed'] == 1
        assert first_payload['items'][0]['result']['status'] == 'retry_scheduled'
        assert first_payload['items'][0]['result']['retry_attempt'] == 1
        assert first_payload['items'][0]['result']['retry_backoff_s'] == 20
        assert float(first_payload['items'][0]['job']['next_run_at']) == base_now + 31

        retried_job = gw.audit.get_job_schedule(job_id, tenant_id='tenant-a', workspace_id='ws-a', environment='prod')
        repaired_definition = dict(retried_job.get('workflow_definition') or {})
        repaired_definition['next_wave_no'] = 2
        gw.audit.update_job_schedule(job_id, workflow_definition=repaired_definition, tenant_id='tenant-a', workspace_id='ws-a', environment='prod')

        _set_now(monkeypatch, base_now + 32)
        second_due = client.post(
            '/admin/openclaw/alert-governance/baseline-advance-jobs/run-due',
            headers=headers,
            json={'actor': 'baseline-release-bot', 'promotion_id': promotion_id, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert second_due.status_code == 200, second_due.text
        second_payload = second_due.json()
        assert second_payload['summary']['executed'] == 1
        assert second_payload['items'][0]['result']['status'] == 'advanced'

        detail = client.get(
            f'/admin/openclaw/alert-governance/baseline-promotions/{promotion_id}?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert detail.status_code == 200, detail.text
        detail_payload = detail.json()
        assert detail_payload['release']['status'] == 'completed'
        labels = [item['label'] for item in detail_payload['timeline']['items']]
        assert 'baseline_promotion_wave_auto_advance_retry_scheduled' in labels
        assert 'baseline_promotion_wave_auto_advance_advanced' in labels



def test_baseline_rollout_recurring_workspace_timezone_window_schedules_next_valid_slot(tmp_path: Path, monkeypatch) -> None:
    base_now = datetime(2026, 3, 31, 9, 50, tzinfo=timezone.utc).timestamp()
    expected_run_at = datetime(2026, 3, 31, 10, 0, tzinfo=timezone.utc).timestamp()
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='baseline-rollout-recurring-workspace-catalog',
            version='catalog-v1',
            environment_policy_baselines=_baseline_catalog(),
            promotion_policy={'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'gov', 'requested_role': 'governance-board', 'label': 'Governance board'}]}},
        )
        runtime_a = _create_runtime_for_environment(client, headers, name='runtime-baseline-recurring-a', environment='prod')
        runtime_b = _create_runtime_for_environment(client, headers, name='runtime-baseline-recurring-b', environment='prod')
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
                    'waves': [[portfolio_a], [portfolio_b]],
                    'auto_apply_first_wave': True,
                    'require_manual_advance': True,
                    'auto_advance': True,
                    'auto_advance_window_s': 0,
                    'timezone_by_workspace': {'ws-a': 'Europe/Madrid'},
                    'maintenance_windows': [
                        {'window_id': 'mw-recurring', 'label': 'change-window', 'weekdays': ['tuesday'], 'start_time': '12:00', 'end_time': '13:00'},
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
            json={'actor': 'governance-board', 'reason': 'respect recurring workspace change window', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert approved.status_code == 200, approved.text
        payload = approved.json()
        scheduled_job = payload['scheduled_advance_job']
        assert scheduled_job is not None
        assert float(scheduled_job['next_run_at']) == expected_run_at
        scheduled = payload['baseline_promotion']['rollout_plan']['items'][0]['scheduled_advance']
        assert scheduled['calendar_blockers'] == ['maintenance_window']
        assert scheduled['portfolio_calendar'][0]['resolved_timezone'] == 'Europe/Madrid'



def test_baseline_rollout_hierarchical_blackouts_and_portfolio_timezone_override(tmp_path: Path, monkeypatch) -> None:
    base_now = datetime(2026, 3, 31, 13, 50, tzinfo=timezone.utc).timestamp()
    expected_window_start = datetime(2026, 3, 31, 14, 0, tzinfo=timezone.utc).timestamp()
    expected_run_at = datetime(2026, 3, 31, 15, 0, tzinfo=timezone.utc).timestamp()
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='baseline-rollout-hierarchical-blackout-catalog',
            version='catalog-v1',
            environment_policy_baselines=_baseline_catalog(),
            promotion_policy={'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'gov', 'requested_role': 'governance-board', 'label': 'Governance board'}]}},
        )
        runtime_a = _create_runtime_for_environment(client, headers, name='runtime-baseline-hblackout-a', environment='prod')
        runtime_b = _create_runtime_for_environment(client, headers, name='runtime-baseline-hblackout-b', environment='prod')
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
            train_policy_extras={'rollout_timezone': 'America/New_York'},
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
                    'waves': [[portfolio_a], [portfolio_b]],
                    'auto_apply_first_wave': True,
                    'require_manual_advance': True,
                    'auto_advance': True,
                    'auto_advance_window_s': 0,
                    'timezone_by_workspace': {'ws-a': 'Europe/Madrid'},
                    'maintenance_windows': [
                        {'window_id': 'mw-recurring', 'label': 'change-window', 'weekdays': ['tuesday'], 'start_time': '10:00', 'end_time': '11:00'},
                    ],
                    'blackout_windows': {
                        'workspace': {
                            'ws-a': [
                                {'window_id': 'ws-freeze', 'label': 'workspace-freeze', 'start_at': expected_window_start, 'end_at': expected_window_start + 1800, 'reason': 'workspace blackout'},
                            ],
                        },
                        'portfolio': {
                            portfolio_b: [
                                {'window_id': 'portfolio-freeze', 'label': 'portfolio-freeze', 'start_at': expected_window_start + 1800, 'end_at': expected_window_start + 3600, 'reason': 'portfolio blackout'},
                            ],
                        },
                    },
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
            json={'actor': 'governance-board', 'reason': 'respect hierarchical blackout windows', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert approved.status_code == 200, approved.text
        payload = approved.json()
        scheduled_job = payload['scheduled_advance_job']
        assert scheduled_job is not None
        assert float(scheduled_job['next_run_at']) == expected_run_at
        scheduled = payload['baseline_promotion']['rollout_plan']['items'][0]['scheduled_advance']
        assert set(scheduled['calendar_blockers']) == {'maintenance_window', 'freeze_window'}
        assert scheduled['portfolio_calendar'][0]['resolved_timezone'] == 'America/New_York'



def test_baseline_rollout_pause_resume_preserves_state_and_rearms_job(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_738_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='baseline-rollout-pause-resume-catalog',
            version='catalog-v1',
            environment_policy_baselines=_baseline_catalog(),
            promotion_policy={'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'gov', 'requested_role': 'governance-board', 'label': 'Governance board'}]}},
        )
        runtime_a = _create_runtime_for_environment(client, headers, name='runtime-baseline-pause-a', environment='prod')
        runtime_b = _create_runtime_for_environment(client, headers, name='runtime-baseline-pause-b', environment='prod')
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
                'rollout_policy': {
                    'enabled': True,
                    'wave_size': 1,
                    'auto_apply_first_wave': True,
                    'require_manual_advance': True,
                    'auto_advance': True,
                    'auto_advance_window_s': 60,
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
            json={'actor': 'governance-board', 'reason': 'schedule next wave', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()['advance_jobs']['summary']['count'] == 1

        paused = client.post(
            f'/admin/openclaw/alert-governance/baseline-promotions/{promotion_id}/actions/pause',
            headers=headers,
            json={'actor': 'governance-board', 'reason': 'operator pause', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert paused.status_code == 200, paused.text
        paused_payload = paused.json()
        assert paused_payload['release']['status'] == 'paused'
        assert paused_payload['baseline_promotion']['pause_state']['paused'] is True
        jobs_paused = _list_jobs(client, headers, promotion_id=promotion_id)
        assert jobs_paused['summary']['count'] == 1
        assert jobs_paused['items'][0]['enabled'] is False

        _set_now(monkeypatch, base_now + 120)
        while_paused = client.post(
            '/admin/openclaw/alert-governance/baseline-advance-jobs/run-due',
            headers=headers,
            json={'actor': 'baseline-release-bot', 'promotion_id': promotion_id, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert while_paused.status_code == 200, while_paused.text
        assert while_paused.json()['summary']['executed'] == 0

        resumed = client.post(
            f'/admin/openclaw/alert-governance/baseline-promotions/{promotion_id}/actions/resume',
            headers=headers,
            json={'actor': 'governance-board', 'reason': 'operator resume', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert resumed.status_code == 200, resumed.text
        resumed_payload = resumed.json()
        assert resumed_payload['release']['status'] == 'awaiting_advance_window'
        assert resumed_payload['baseline_promotion']['pause_state']['paused'] is False
        jobs_resumed = _list_jobs(client, headers, promotion_id=promotion_id)
        assert jobs_resumed['summary']['count'] == 1
        assert jobs_resumed['items'][0]['enabled'] is True
        assert float(jobs_resumed['items'][0]['next_run_at']) <= base_now + 120

        due = client.post(
            '/admin/openclaw/alert-governance/baseline-advance-jobs/run-due',
            headers=headers,
            json={'actor': 'baseline-release-bot', 'promotion_id': promotion_id, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert due.status_code == 200, due.text
        assert due.json()['summary']['executed'] == 1
        assert due.json()['items'][0]['result']['status'] == 'advanced'

        detail = client.get(
            f'/admin/openclaw/alert-governance/baseline-promotions/{promotion_id}?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert detail.status_code == 200, detail.text
        detail_payload = detail.json()
        assert detail_payload['release']['status'] == 'completed'
        labels = [item['label'] for item in detail_payload['timeline']['items']]
        assert 'baseline_promotion_paused' in labels
        assert 'baseline_promotion_resumed' in labels



def test_baseline_rollout_invalid_timezone_is_rejected(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_750_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='baseline-rollout-invalid-timezone-catalog',
            version='catalog-v1',
            environment_policy_baselines=_baseline_catalog(),
            promotion_policy={'approval_policy': {'enabled': False, 'layers': []}},
        )
        runtime_a = _create_runtime_for_environment(client, headers, name='runtime-baseline-invalid-tz-a', environment='prod')
        _create_portfolio_with_catalog(
            client,
            headers,
            base_now=base_now + 1,
            runtime_id=runtime_a,
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
                    'default_timezone': 'Mars/Phobos',
                    'maintenance_windows': [{'window_kind': 'recurring', 'weekdays': ['mon'], 'start_time': '10:00', 'end_time': '12:00'}],
                },
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload['ok'] is False
        assert payload['error'] == 'baseline_rollout_policy_invalid'
        assert any(item['code'] == 'invalid_timezone' for item in payload['validation']['errors'])


def test_portfolio_invalid_rollout_timezone_is_rejected(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_751_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        runtime = _create_runtime_for_environment(client, headers, name='runtime-portfolio-invalid-timezone', environment='prod')
        bundle_response = client.post(
            '/admin/openclaw/alert-governance/bundles',
            headers=headers,
            json={
                'name': 'bundle-invalid-timezone',
                'version': 'v1',
                'actor': 'admin',
                'runtime_ids': [runtime],
                'policy_payload': {'alert_governance': {'mode': 'monitor'}},
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert bundle_response.status_code == 200, bundle_response.text
        bundle_id = bundle_response.json()['bundle_id']

        response = client.post(
            '/admin/openclaw/alert-governance/portfolios',
            headers=headers,
            json={
                'name': 'portfolio-invalid-timezone',
                'version': 'portfolio-v1',
                'bundle_ids': [bundle_id],
                'actor': 'admin',
                'rollout_timezone': 'Invalid/Timezone',
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload['ok'] is False
        assert payload['error'] == 'portfolio_train_policy_invalid'
        assert any(item['code'] == 'invalid_timezone' for item in payload['validation']['errors'])


def test_baseline_rollout_job_listing_and_disable_handle_more_than_200_jobs(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_752_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='baseline-rollout-many-jobs-catalog',
            version='catalog-v1',
            environment_policy_baselines=_baseline_catalog(),
            promotion_policy={'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'gov', 'requested_role': 'governance-board', 'label': 'Governance board'}]}},
        )
        runtime_a = _create_runtime_for_environment(client, headers, name='runtime-baseline-many-jobs-a', environment='prod')
        runtime_b = _create_runtime_for_environment(client, headers, name='runtime-baseline-many-jobs-b', environment='prod')
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
                'rollout_policy': {
                    'enabled': True,
                    'wave_size': 1,
                    'auto_apply_first_wave': True,
                    'require_manual_advance': True,
                    'auto_advance': True,
                    'auto_advance_window_s': 300,
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
            json={'actor': 'governance-board', 'reason': 'seed lots of jobs', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert approved.status_code == 200, approved.text
        gw = app.state.gw
        for idx in range(1, 206):
            gw.audit.create_job_schedule(
                name=f'bulk-baseline-job-{idx}',
                workflow_definition={
                    'kind': 'openclaw_alert_governance_baseline_wave_advance',
                    'promotion_id': promotion_id,
                    'source_wave_no': 1000 + idx,
                    'next_wave_no': 1001 + idx,
                    'created_by': 'test',
                    'reason': 'bulk job seed',
                },
                created_by='test',
                input_payload={'promotion_id': promotion_id},
                next_run_at=base_now + 600 + idx,
                enabled=True,
                tenant_id='tenant-a',
                workspace_id='ws-a',
                environment='prod',
                playbook_id=f'bulk-baseline-job-{idx}',
                schedule_kind='once',
                not_before=base_now + 600 + idx,
                max_runs=1,
            )

        jobs = _list_jobs(client, headers, promotion_id=promotion_id)
        assert jobs['summary']['count'] == 206
        assert len(jobs['items']) == 100

        completed = client.post(
            f'/admin/openclaw/alert-governance/baseline-promotions/{promotion_id}/actions/advance',
            headers=headers,
            json={'actor': 'governance-board', 'reason': 'complete promotion and disable jobs', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert completed.status_code == 200, completed.text
        assert completed.json()['release']['status'] == 'completed'

        remaining_enabled = [
            item for item in gw.audit.list_job_schedules(limit=1000, enabled=True, tenant_id='tenant-a', workspace_id='ws-a', environment='prod')
            if (item.get('workflow_definition') or {}).get('kind') == 'openclaw_alert_governance_baseline_wave_advance'
            and (item.get('workflow_definition') or {}).get('promotion_id') == promotion_id
        ]
        assert remaining_enabled == []
