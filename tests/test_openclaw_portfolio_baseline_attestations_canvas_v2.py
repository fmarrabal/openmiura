from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

import app as app_module
from openmiura.application.canvas.service import LiveCanvasService
from openmiura.application.openclaw.scheduler import OpenClawRecoverySchedulerService
from openmiura.gateway import Gateway
from tests.test_openclaw_portfolio_baseline_catalog_promotion_v2 import (
    _create_baseline_catalog,
    _create_portfolio_with_catalog,
)
from tests.test_openclaw_portfolio_baseline_release_trains_v2 import _baseline_catalog, _env_policy
from tests.test_openclaw_portfolio_environment_tiered_governance_v2 import _create_runtime_for_environment
from tests.test_openclaw_portfolio_evidence_packaging_v2 import _set_now, _write_config


def test_baseline_promotion_rollback_attestations_and_exports(tmp_path: Path, monkeypatch) -> None:
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
            name='baseline-rollback-attestation-catalog',
            version='catalog-v1',
            environment_policy_baselines=_baseline_catalog(),
            promotion_policy={'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'gov', 'requested_role': 'governance-board', 'label': 'Governance board'}]}},
        )
        runtime_a = _create_runtime_for_environment(client, headers, name='runtime-baseline-attestation-a', environment='prod')
        runtime_b = _create_runtime_for_environment(client, headers, name='runtime-baseline-attestation-b', environment='prod')
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
            json={'actor': 'governance-board', 'reason': 'approve and stage first wave', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()['baseline_promotion']['rollout_plan']['completed_wave_count'] == 1

        rolled_back = client.post(
            f'/admin/openclaw/alert-governance/baseline-promotions/{promotion_id}/actions/rollback',
            headers=headers,
            json={'actor': 'governance-board', 'reason': 'abort rollout for attestation test', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert rolled_back.status_code == 200, rolled_back.text
        rollback_payload = rolled_back.json()
        assert rollback_payload['release']['status'] == 'rolled_back'
        rollback_items = rollback_payload['rollback_attestations']['items']
        assert rollback_payload['rollback_attestations']['summary']['count'] == 1
        assert rollback_items[0]['affected_portfolio_count'] >= 1
        assert rollback_items[0]['integrity']['signed'] is True

        attestation_export = client.post(
            f'/admin/openclaw/alert-governance/baseline-promotions/{promotion_id}/attestation-export',
            headers=headers,
            json={'actor': 'export-bot', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert attestation_export.status_code == 200, attestation_export.text
        attestation_payload = attestation_export.json()
        assert attestation_payload['report']['report_type'] == 'openmiura_baseline_promotion_attestation_export_v1'
        assert attestation_payload['integrity']['signed'] is True
        assert attestation_payload['report']['rollback_attestations']['summary']['count'] == 1

        postmortem_export = client.post(
            f'/admin/openclaw/alert-governance/baseline-promotions/{promotion_id}/postmortem-export',
            headers=headers,
            json={'actor': 'export-bot', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert postmortem_export.status_code == 200, postmortem_export.text
        postmortem_payload = postmortem_export.json()
        assert postmortem_payload['report']['report_type'] == 'openmiura_baseline_promotion_postmortem_v1'
        assert postmortem_payload['report']['summary']['final_status'] == 'rolled_back'
        assert postmortem_payload['report']['rollback']['latest_attestation']['attestation_id'] == rollback_items[0]['attestation_id']
        assert postmortem_payload['integrity']['signed'] is True
        labels = [item['label'] for item in postmortem_payload['report']['timeline']['items']]
        assert 'baseline_promotion_rolled_back' in labels



def test_canvas_baseline_promotion_board_and_actions(tmp_path: Path, monkeypatch) -> None:
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
            name='baseline-canvas-catalog',
            version='catalog-v1',
            environment_policy_baselines=_baseline_catalog(),
            promotion_policy={'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'gov', 'requested_role': 'governance-board', 'label': 'Governance board'}]}},
        )
        runtime_a = _create_runtime_for_environment(client, headers, name='runtime-baseline-canvas-a', environment='prod')
        _create_portfolio_with_catalog(
            client,
            headers,
            base_now=base_now + 1,
            runtime_id=runtime_a,
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
                'rollout_policy': {'enabled': True, 'wave_size': 1, 'auto_apply_first_wave': False, 'require_manual_advance': True},
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
            json={'actor': 'governance-board', 'reason': 'await manual advance', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()['release']['status'] == 'awaiting_advance'

        canvas_resp = client.post(
            '/admin/canvas/documents',
            headers=headers,
            json={'actor': 'admin', 'title': 'Baseline promotions canvas', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert canvas_resp.status_code == 200, canvas_resp.text
        canvas_id = canvas_resp.json()['document']['canvas_id']
        node_resp = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes',
            headers=headers,
            json={'actor': 'admin', 'node_type': 'baseline_promotion', 'label': 'Promotion node', 'data': {'promotion_id': promotion_id}, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert node_resp.status_code == 200, node_resp.text
        node_id = node_resp.json()['node']['node_id']

        operational = client.get(
            f'/admin/canvas/documents/{canvas_id}/views/operational?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert operational.status_code == 200, operational.text
        op_payload = operational.json()
        view_keys = {item['view_key'] for item in op_payload['suggested_views']}
        assert 'baseline-rollouts' in view_keys
        assert op_payload['summary']['baseline_promotion_board']['promotion_count'] == 1

        board = client.get(
            f'/admin/canvas/documents/{canvas_id}/views/baseline-promotions?tenant_id=tenant-a&workspace_id=ws-a&environment=prod&limit=10',
            headers=headers,
        )
        assert board.status_code == 200, board.text
        board_payload = board.json()
        assert board_payload['summary']['promotion_count'] == 1
        assert board_payload['items'][0]['promotion_id'] == promotion_id
        assert board_payload['items'][0]['status'] == 'awaiting_advance'

        inspector = client.get(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert inspector.status_code == 200, inspector.text
        inspector_payload = inspector.json()
        assert 'simulate' in inspector_payload['available_actions']
        assert 'approve_simulation' in inspector_payload['available_actions']
        assert 'create_and_approve_rollout' in inspector_payload['available_actions']
        assert 'pause' in inspector_payload['available_actions']
        assert 'export_postmortem' in inspector_payload['available_actions']
        assert inspector_payload['action_prechecks']['simulate']['allowed'] is True
        assert inspector_payload['action_prechecks']['pause']['allowed'] is True
        assert inspector_payload['action_prechecks']['approve_simulation']['allowed'] is False

        simulated = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/simulate?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'admin', 'reason': 'preflight from canvas'},
        )
        assert simulated.status_code == 200, simulated.text
        simulation_payload = simulated.json()
        assert simulation_payload['result']['mode'] == 'dry-run'
        assert simulation_payload['result']['summary']['affected_count'] == 1
        assert simulation_payload['result']['simulation_source']['promotion_id'] == promotion_id
        assert simulation_payload['result']['diff']['summary']['changed_environment_count'] >= 1
        assert simulation_payload['result']['explainability']['decision'] == 'approvable'
        assert simulation_payload['result']['canvas_simulation']['review'] == {}
        assert simulation_payload['result']['canvas_simulation']['simulation_status'] == 'ready'
        assert simulation_payload['result']['canvas_simulation']['stale'] is False
        assert simulation_payload['result']['canvas_simulation']['expired'] is False
        assert simulation_payload['result']['canvas_simulation']['fingerprints']['candidate_baseline_hash']

        inspector_after_sim = client.get(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert inspector_after_sim.status_code == 200, inspector_after_sim.text
        inspector_after_sim_payload = inspector_after_sim.json()
        assert inspector_after_sim_payload['node']['data']['latest_simulation']['summary']['approvable'] is True
        assert inspector_after_sim_payload['node']['data']['latest_simulation']['simulation_status'] == 'ready'
        assert inspector_after_sim_payload['node']['data']['latest_simulation']['observed_versions']['catalog_version'] == 'catalog-v1'
        assert inspector_after_sim_payload['action_prechecks']['approve_simulation']['allowed'] is True
        assert inspector_after_sim_payload['action_prechecks']['create_and_approve_rollout']['allowed'] is False

        simulation_approved = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/approve_simulation?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'governance-board', 'reason': 'approve preflight simulation'},
        )
        assert simulation_approved.status_code == 200, simulation_approved.text
        approval_payload = simulation_approved.json()
        assert approval_payload['result']['latest_simulation']['review']['approved'] is True
        assert approval_payload['result']['latest_simulation']['simulation_status'] == 'reviewed'

        created_rollout = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/create_and_approve_rollout?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'governance-board', 'reason': 'create rollout from approved simulation'},
        )
        assert created_rollout.status_code == 200, created_rollout.text
        created_payload = created_rollout.json()
        created_promotion = created_payload['result']
        assert created_promotion['release']['release_id'] != promotion_id
        assert created_promotion['release']['status'] == 'awaiting_advance'
        assert created_promotion['created_from_simulation']['simulation_source']['promotion_id'] == promotion_id
        assert created_promotion['created_from_simulation']['comparison']['simulation_request_fingerprint']
        assert created_promotion['created_from_simulation']['comparison']['created_request_fingerprint']
        assert isinstance(created_promotion['created_from_simulation']['comparison']['diverged'], bool)
        assert created_promotion['created_node']['node_type'] == 'baseline_promotion'
        assert created_promotion['created_node']['data']['promotion_id'] == created_promotion['release']['release_id']
        assert created_promotion['created_edge']['edge_type'] == 'derived_from_simulation'
        assert created_promotion['created_edge']['data']['simulation_id'] == approval_payload['result']['latest_simulation']['simulation_id']

        paused = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/pause?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'admin', 'reason': 'pause rollout from canvas'},
        )
        assert paused.status_code == 200, paused.text
        assert paused.json()['result']['release']['status'] == 'paused'

        resumed = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/resume?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'admin', 'reason': 'resume rollout from canvas'},
        )
        assert resumed.status_code == 200, resumed.text
        assert resumed.json()['result']['release']['status'] == 'awaiting_advance'

        exported = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/export_postmortem?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'admin', 'reason': 'export from canvas', 'payload': {'timeline_limit': 50}},
        )
        assert exported.status_code == 200, exported.text
        assert exported.json()['result']['report']['report_type'] == 'openmiura_baseline_promotion_postmortem_v1'

        timeline = client.get(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/timeline?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert timeline.status_code == 200, timeline.text
        labels = {item['label'] for item in timeline.json()['items']}
        assert 'canvas_simulate' in labels
        assert 'baseline_promotion_paused' in labels
        assert 'baseline_promotion_resumed' in labels


def test_canvas_baseline_simulation_becomes_stale_after_catalog_change_and_blocks_rollout(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_746_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='baseline-simulation-stale-catalog',
            version='catalog-v1',
            environment_policy_baselines=_baseline_catalog(),
            promotion_policy={'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'gov', 'requested_role': 'governance-board', 'label': 'Governance board'}]}},
        )
        runtime_a = _create_runtime_for_environment(client, headers, name='runtime-baseline-stale-a', environment='prod')
        _create_portfolio_with_catalog(
            client,
            headers,
            base_now=base_now + 1,
            runtime_id=runtime_a,
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
                'rollout_policy': {'enabled': False},
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert promotion.status_code == 200, promotion.text
        promotion_id = promotion.json()['promotion_id']

        canvas_resp = client.post(
            '/admin/canvas/documents',
            headers=headers,
            json={'actor': 'admin', 'title': 'Stale simulation canvas', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        canvas_id = canvas_resp.json()['document']['canvas_id']
        node_resp = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes',
            headers=headers,
            json={'actor': 'admin', 'node_type': 'baseline_promotion', 'label': 'Promotion node', 'data': {'promotion_id': promotion_id}, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        node_id = node_resp.json()['node']['node_id']

        simulated = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/simulate?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'admin', 'reason': 'preflight from canvas'},
        )
        assert simulated.status_code == 200, simulated.text

        simulation_approved = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/approve_simulation?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'governance-board', 'reason': 'approve before catalog changes'},
        )
        assert simulation_approved.status_code == 200, simulation_approved.text

        source_approved = client.post(
            f'/admin/openclaw/alert-governance/baseline-promotions/{promotion_id}/actions/approve',
            headers=headers,
            json={'actor': 'governance-board', 'reason': 'apply source promotion and move catalog version', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert source_approved.status_code == 200, source_approved.text
        assert source_approved.json()['catalog']['baseline_catalog']['current_version']['catalog_version'] == 'catalog-v2'

        inspector = client.get(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert inspector.status_code == 200, inspector.text
        inspector_payload = inspector.json()
        latest = inspector_payload['node']['data']['latest_simulation']
        assert latest['stale'] is True
        assert latest['simulation_status'] == 'stale'
        assert 'catalog_version_changed' in latest['stale_reasons']
        assert inspector_payload['action_prechecks']['approve_simulation']['allowed'] is False
        assert inspector_payload['action_prechecks']['approve_simulation']['reason'] == 'baseline_promotion_simulation_stale'
        assert inspector_payload['action_prechecks']['create_rollout']['allowed'] is False
        assert inspector_payload['action_prechecks']['create_rollout']['reason'] == 'baseline_promotion_simulation_stale'

        create_rollout = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/create_rollout?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'governance-board', 'reason': 'attempt rollout from stale simulation'},
        )
        assert create_rollout.status_code == 200, create_rollout.text
        blocked_payload = create_rollout.json()
        assert blocked_payload['ok'] is False
        assert blocked_payload['error'] == 'action_blocked'
        assert blocked_payload['precheck']['reason'] == 'baseline_promotion_simulation_stale'

        scheduler = OpenClawRecoverySchedulerService()
        direct_guard = scheduler.create_runtime_alert_governance_baseline_promotion_from_simulation(
            app.state.gw,
            simulation=latest,
            actor='governance-board',
            reason='direct guard on stale simulation',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert direct_guard['ok'] is False
        assert direct_guard['error'] == 'baseline_promotion_simulation_stale'
        assert direct_guard['guard']['status'] == 'blocked'


def test_canvas_baseline_simulation_ttl_expiry_blocks_approval(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_747_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='baseline-simulation-ttl-catalog',
            version='catalog-v1',
            environment_policy_baselines=_baseline_catalog(),
            promotion_policy={
                'simulation_ttl_s': 60,
                'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'gov', 'requested_role': 'governance-board', 'label': 'Governance board'}]},
            },
        )
        runtime_a = _create_runtime_for_environment(client, headers, name='runtime-baseline-ttl-a', environment='prod')
        _create_portfolio_with_catalog(
            client,
            headers,
            base_now=base_now + 1,
            runtime_id=runtime_a,
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
                'rollout_policy': {'enabled': True, 'wave_size': 1, 'auto_apply_first_wave': False, 'require_manual_advance': True},
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert promotion.status_code == 200, promotion.text
        promotion_id = promotion.json()['promotion_id']

        canvas_resp = client.post(
            '/admin/canvas/documents',
            headers=headers,
            json={'actor': 'admin', 'title': 'TTL simulation canvas', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        canvas_id = canvas_resp.json()['document']['canvas_id']
        node_resp = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes',
            headers=headers,
            json={'actor': 'admin', 'node_type': 'baseline_promotion', 'label': 'Promotion node', 'data': {'promotion_id': promotion_id}, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        node_id = node_resp.json()['node']['node_id']

        simulated = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/simulate?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'admin', 'reason': 'ttl simulation'},
        )
        assert simulated.status_code == 200, simulated.text
        simulation_payload = simulated.json()['result']['canvas_simulation']
        assert simulation_payload['simulation_policy']['ttl_s'] == 60
        assert simulation_payload['expires_at'] == base_now + 60

        _set_now(monkeypatch, base_now + 120)

        inspector = client.get(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert inspector.status_code == 200, inspector.text
        inspector_payload = inspector.json()
        latest = inspector_payload['node']['data']['latest_simulation']
        assert latest['expired'] is True
        assert latest['simulation_status'] == 'expired'
        assert latest['why_blocked'] == 'baseline_promotion_simulation_expired'
        assert inspector_payload['action_prechecks']['approve_simulation']['allowed'] is False
        assert inspector_payload['action_prechecks']['approve_simulation']['reason'] == 'baseline_promotion_simulation_expired'

        approve_simulation = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/approve_simulation?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'governance-board', 'reason': 'late approval attempt'},
        )
        assert approve_simulation.status_code == 200, approve_simulation.text
        blocked_payload = approve_simulation.json()
        assert blocked_payload['ok'] is False
        assert blocked_payload['error'] == 'action_blocked'
        assert blocked_payload['precheck']['reason'] == 'baseline_promotion_simulation_expired'

        scheduler = OpenClawRecoverySchedulerService()
        direct_guard = scheduler.create_runtime_alert_governance_baseline_promotion_from_simulation(
            app.state.gw,
            simulation=latest,
            actor='governance-board',
            reason='direct guard on expired simulation',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert direct_guard['ok'] is False
        assert direct_guard['error'] == 'baseline_promotion_simulation_expired'
        assert direct_guard['guard']['status'] == 'blocked'



def test_canvas_baseline_simulation_multireview_governance_blocks_until_reviews_complete(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_748_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='baseline-simulation-multireview-catalog',
            version='catalog-v1',
            environment_policy_baselines=_baseline_catalog(),
            promotion_policy={
                'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'gov', 'requested_role': 'governance-board', 'label': 'Governance board'}]},
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
        runtime_a = _create_runtime_for_environment(client, headers, name='runtime-baseline-multireview-a', environment='prod')
        _create_portfolio_with_catalog(
            client,
            headers,
            base_now=base_now + 1,
            runtime_id=runtime_a,
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
                'rollout_policy': {'enabled': True, 'wave_size': 1, 'auto_apply_first_wave': False, 'require_manual_advance': True},
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert promotion.status_code == 200, promotion.text
        promotion_id = promotion.json()['promotion_id']

        canvas_resp = client.post(
            '/admin/canvas/documents',
            headers=headers,
            json={'actor': 'admin', 'title': 'Multireview simulation canvas', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        canvas_id = canvas_resp.json()['document']['canvas_id']
        node_resp = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes',
            headers=headers,
            json={'actor': 'admin', 'node_type': 'baseline_promotion', 'label': 'Promotion node', 'data': {'promotion_id': promotion_id}, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        node_id = node_resp.json()['node']['node_id']

        simulated = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/simulate?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'admin', 'reason': 'multireview simulation'},
        )
        assert simulated.status_code == 200, simulated.text
        simulation_payload = simulated.json()['result']['canvas_simulation']
        assert simulation_payload['summary']['review_required'] is True
        assert simulation_payload['review_state']['next_layer']['layer_id'] == 'ops'
        assert simulation_payload['simulation_status'] == 'ready'

        direct_guard = OpenClawRecoverySchedulerService().create_runtime_alert_governance_baseline_promotion_from_simulation(
            app.state.gw,
            simulation=simulation_payload,
            actor='governance-board',
            reason='should be blocked before reviews',
            tenant_id='tenant-a',
            workspace_id='ws-a',
            environment='prod',
        )
        assert direct_guard['ok'] is False
        assert direct_guard['error'] == 'baseline_promotion_simulation_not_approved'

        self_review = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/approve_simulation?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'admin', 'reason': 'self review should be blocked'},
        )
        assert self_review.status_code == 200, self_review.text
        self_review_payload = self_review.json()
        assert self_review_payload['ok'] is False
        assert self_review_payload['error'] == 'baseline_promotion_simulation_self_review_blocked'

        first_review = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/approve_simulation?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'ops-reviewer', 'reason': 'ops review passed', 'layer_id': 'ops'},
        )
        assert first_review.status_code == 200, first_review.text
        first_payload = first_review.json()
        assert first_payload['result']['latest_simulation']['review']['approved'] is False
        assert first_payload['result']['latest_simulation']['review_state']['review_count'] == 1
        assert first_payload['result']['latest_simulation']['review_state']['overall_status'] == 'in_review'
        assert first_payload['result']['latest_simulation']['simulation_status'] == 'in_review'
        assert first_payload['result']['latest_simulation']['review_state']['next_layer']['layer_id'] == 'risk'

        inspector_mid = client.get(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert inspector_mid.status_code == 200, inspector_mid.text
        inspector_mid_payload = inspector_mid.json()
        assert inspector_mid_payload['action_prechecks']['create_rollout']['allowed'] is False
        assert inspector_mid_payload['action_prechecks']['create_rollout']['reason'] == 'baseline_promotion_simulation_not_approved'

        second_review = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/approve_simulation?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'risk-reviewer', 'reason': 'risk review passed', 'layer_id': 'risk'},
        )
        assert second_review.status_code == 200, second_review.text
        second_payload = second_review.json()
        latest = second_payload['result']['latest_simulation']
        assert latest['review']['approved'] is True
        assert latest['review_state']['approved'] is True
        assert latest['review_state']['overall_status'] == 'approved'
        assert latest['simulation_status'] == 'reviewed'
        assert latest['review_state']['review_count'] == 2
        assert second_payload['result']['review_action']['layer_id'] == 'risk'

        inspector_final = client.get(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert inspector_final.status_code == 200, inspector_final.text
        inspector_final_payload = inspector_final.json()
        assert inspector_final_payload['action_prechecks']['create_and_approve_rollout']['allowed'] is True

        created = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/create_and_approve_rollout?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'governance-board', 'reason': 'create rollout after reviews'},
        )
        assert created.status_code == 200, created.text
        created_payload = created.json()['result']
        assert created_payload['ok'] is True
        assert created_payload['created_from_simulation']['simulation_id'] == latest['simulation_id']
        assert created_payload['created_edge']['edge_type'] == 'derived_from_simulation'



def test_canvas_simulation_exports_persist_and_flow_into_created_promotion_attestation(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_747_200.0
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
            name='baseline-simulation-export-catalog',
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
        runtime_id = _create_runtime_for_environment(client, headers, name='runtime-canvas-simulation-export', environment='prod')
        _create_portfolio_with_catalog(
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

        canvas_resp = client.post(
            '/admin/canvas/documents',
            headers=headers,
            json={'actor': 'admin', 'title': 'Simulation export canvas', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert canvas_resp.status_code == 200, canvas_resp.text
        canvas_id = canvas_resp.json()['document']['canvas_id']
        node_resp = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes',
            headers=headers,
            json={'actor': 'admin', 'node_type': 'baseline_promotion', 'label': 'Simulation export node', 'data': {'promotion_id': promotion_id}, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert node_resp.status_code == 200, node_resp.text
        node_id = node_resp.json()['node']['node_id']

        inspector_before = client.get(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert inspector_before.status_code == 200, inspector_before.text
        before_payload = inspector_before.json()
        assert 'export_simulation_attestation' in before_payload['available_actions']
        assert 'export_simulation_review_audit' in before_payload['available_actions']
        assert 'export_simulation_evidence_package' in before_payload['available_actions']
        assert before_payload['action_prechecks']['export_simulation_attestation']['allowed'] is False

        simulated = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/simulate?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'admin', 'reason': 'simulation export dry run'},
        )
        assert simulated.status_code == 200, simulated.text

        first_review = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/approve_simulation?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'ops-reviewer', 'reason': 'ops review passed', 'layer_id': 'ops'},
        )
        assert first_review.status_code == 200, first_review.text
        second_review = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/approve_simulation?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'risk-reviewer', 'reason': 'risk review passed', 'layer_id': 'risk'},
        )
        assert second_review.status_code == 200, second_review.text
        latest = second_review.json()['result']['latest_simulation']
        assert latest['simulation_status'] == 'reviewed'

        export_attestation = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/export_simulation_attestation?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'export-bot'},
        )
        assert export_attestation.status_code == 200, export_attestation.text
        export_attestation_payload = export_attestation.json()['result']
        assert export_attestation_payload['report']['report_type'] == 'openmiura_baseline_promotion_simulation_attestation_v1'
        assert export_attestation_payload['integrity']['signed'] is True
        assert export_attestation_payload['latest_simulation']['export_state']['attestation_count'] == 1

        export_review = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/export_simulation_review_audit?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'export-bot'},
        )
        assert export_review.status_code == 200, export_review.text
        export_review_payload = export_review.json()['result']
        assert export_review_payload['report']['report_type'] == 'openmiura_baseline_promotion_simulation_review_audit_v1'
        assert export_review_payload['report']['review_sequence']['overall_status'] == 'approved'
        assert export_review_payload['latest_simulation']['export_state']['review_audit_count'] == 1

        export_package = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/export_simulation_evidence_package?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'export-bot'},
        )
        assert export_package.status_code == 200, export_package.text
        export_package_payload = export_package.json()['result']
        assert export_package_payload['package']['report_type'] == 'openmiura_baseline_promotion_simulation_evidence_package_v1'
        assert export_package_payload['artifact']['artifact_type'] == 'openmiura_baseline_promotion_simulation_evidence_artifact_v1'
        assert export_package_payload['registry_entry']['sequence'] == 1
        assert export_package_payload['latest_simulation']['export_state']['evidence_package_count'] == 1

        inspector_after_export = client.get(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert inspector_after_export.status_code == 200, inspector_after_export.text
        export_state = inspector_after_export.json()['node']['data']['latest_simulation']['export_state']
        assert export_state['latest_attestation']['report_type'] == 'openmiura_baseline_promotion_simulation_attestation_v1'
        assert export_state['latest_review_audit']['report_type'] == 'openmiura_baseline_promotion_simulation_review_audit_v1'
        assert export_state['latest_evidence_package']['report_type'] == 'openmiura_baseline_promotion_simulation_evidence_package_v1'
        assert export_state['registry_summary']['count'] == 1

        created = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/create_and_approve_rollout?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'governance-board', 'reason': 'create rollout after exports'},
        )
        assert created.status_code == 200, created.text
        created_payload = created.json()['result']
        created_from_simulation = created_payload['created_from_simulation']
        assert created_from_simulation['attestation']['report_type'] == 'openmiura_baseline_promotion_simulation_attestation_v1'
        assert created_from_simulation['attestation']['integrity']['signed'] is True
        assert created_from_simulation['review_audit']['report_type'] == 'openmiura_baseline_promotion_simulation_review_audit_v1'
        assert created_from_simulation['review_audit']['summary']['reviewers'] == ['ops-reviewer', 'risk-reviewer']
        assert created_from_simulation['evidence_package']['report_type'] == 'openmiura_baseline_promotion_simulation_evidence_package_v1'
        assert created_from_simulation['evidence_package']['registry_entry']['sequence'] == 1

        created_node_id = created_payload['created_node']['node_id']
        promotion_attestation = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{created_node_id}/actions/export_attestation?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'export-bot'},
        )
        assert promotion_attestation.status_code == 200, promotion_attestation.text
        promotion_attestation_payload = promotion_attestation.json()['result']
        assert promotion_attestation_payload['report']['created_from_simulation']['attestation']['report_id'] == created_from_simulation['attestation']['report_id']
        assert promotion_attestation_payload['report']['created_from_simulation']['review_audit']['report_id'] == created_from_simulation['review_audit']['report_id']


def test_canvas_baseline_simulation_evidence_verify_and_restore_recovers_latest_simulation(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_744_800.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='baseline-simulation-evidence-restore-canvas-catalog',
            version='catalog-v1',
            environment_policy_baselines=_baseline_catalog(),
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
        runtime_id = _create_runtime_for_environment(client, headers, name='runtime-canvas-simulation-evidence-restore', environment='prod')
        _create_portfolio_with_catalog(
            client,
            headers,
            base_now=base_now,
            runtime_id=runtime_id,
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
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert promotion.status_code == 200, promotion.text
        promotion_id = promotion.json()['promotion_id']

        canvas_resp = client.post(
            '/admin/canvas/documents',
            headers=headers,
            json={'actor': 'admin', 'title': 'Simulation evidence restore canvas', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert canvas_resp.status_code == 200, canvas_resp.text
        canvas_id = canvas_resp.json()['document']['canvas_id']
        node_resp = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes',
            headers=headers,
            json={'actor': 'admin', 'node_type': 'baseline_promotion', 'label': 'Simulation evidence restore node', 'data': {'promotion_id': promotion_id}, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert node_resp.status_code == 200, node_resp.text
        node_payload = node_resp.json()['node']
        node_id = node_payload['node_id']

        simulated = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/simulate?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'admin', 'reason': 'simulation export for recovery'},
        )
        assert simulated.status_code == 200, simulated.text
        approve_ops = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/approve_simulation?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'ops-reviewer', 'reason': 'ops review passed', 'layer_id': 'ops'},
        )
        assert approve_ops.status_code == 200, approve_ops.text
        approve_risk = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/approve_simulation?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'risk-reviewer', 'reason': 'risk review passed', 'layer_id': 'risk'},
        )
        assert approve_risk.status_code == 200, approve_risk.text

        export_package = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/export_simulation_evidence_package?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'export-bot'},
        )
        assert export_package.status_code == 200, export_package.text
        export_package_payload = export_package.json()['result']
        package_id = export_package_payload['package_id']

        clear_node = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes',
            headers=headers,
            json={
                'actor': 'admin',
                'node_id': node_id,
                'node_type': 'baseline_promotion',
                'label': 'Simulation evidence restore node',
                'data': {'promotion_id': promotion_id},
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert clear_node.status_code == 200, clear_node.text
        assert 'latest_simulation' not in (clear_node.json()['node'].get('data') or {})

        inspector = client.get(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert inspector.status_code == 200, inspector.text
        inspector_payload = inspector.json()
        assert 'verify_simulation_evidence_package' in inspector_payload['available_actions']
        assert 'restore_simulation_evidence_package' in inspector_payload['available_actions']
        assert inspector_payload['action_prechecks']['verify_simulation_evidence_package']['allowed'] is True
        assert inspector_payload['action_prechecks']['restore_simulation_evidence_package']['allowed'] is True

        verify = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/verify_simulation_evidence_package?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'auditor', 'package_id': package_id},
        )
        assert verify.status_code == 200, verify.text
        verify_result = verify.json()['result']
        assert verify_result['verification']['valid'] is True
        assert verify_result['verification']['registry']['membership_valid'] is True

        catalog_release = app.state.gw.audit.get_release_bundle(catalog['catalog_id'], tenant_id='tenant-a', workspace_id='ws-a', environment='prod')
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

        restore = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/restore_simulation_evidence_package?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'recovery-operator', 'package_id': package_id},
        )
        assert restore.status_code == 200, restore.text
        restore_result = restore.json()['result']
        restored_latest = restore_result['latest_simulation']
        assert restored_latest['simulation_id'] == export_package_payload['package']['simulation']['simulation_id']
        assert restored_latest['stale'] is True
        assert restored_latest['simulation_status'] == 'stale'
        assert restored_latest['export_state']['latest_restore']['restore_id']
        assert restored_latest['export_state']['latest_verification']['valid'] is True

        inspector_after = client.get(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert inspector_after.status_code == 200, inspector_after.text
        node_data = inspector_after.json()['node']['data']
        assert node_data['latest_simulation']['simulation_status'] == 'stale'
        assert node_data['last_simulation_evidence_verification']['valid'] is True
        assert node_data['last_simulation_restore']['restore_id'] == restore_result['restore_session']['restore_id']


def test_canvas_baseline_simulation_evidence_package_escrow_receipt_surface_and_restore(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_745_900.0
    _set_now(monkeypatch, base_now)
    monkeypatch.setenv('OPENMIURA_EVIDENCE_ESCROW_DIR', (tmp_path / 'escrow').as_posix())
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    escrow_policy = {
        'enabled': True,
        'provider': 'filesystem-governed',
        'archive_namespace': 'baseline-simulation-evidence-canvas',
        'require_archive_on_export': True,
        'allow_inline_fallback': False,
        'immutable_retention_days': 90,
    }
    baseline_catalog = _baseline_catalog()
    baseline_catalog['prod'] = {**baseline_catalog['prod'], 'escrow_policy': escrow_policy}
    env_policy = _env_policy('baseline-v2')
    env_policy['prod'] = {**env_policy['prod'], 'escrow_policy': escrow_policy}

    with TestClient(app) as client:
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='baseline-simulation-evidence-escrow-canvas-catalog',
            version='catalog-v1',
            environment_policy_baselines=baseline_catalog,
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
        runtime_id = _create_runtime_for_environment(client, headers, name='runtime-canvas-simulation-evidence-escrow', environment='prod')
        _create_portfolio_with_catalog(
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

        canvas_resp = client.post(
            '/admin/canvas/documents',
            headers=headers,
            json={'actor': 'admin', 'title': 'Simulation evidence escrow canvas', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert canvas_resp.status_code == 200, canvas_resp.text
        canvas_id = canvas_resp.json()['document']['canvas_id']
        node_resp = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes',
            headers=headers,
            json={'actor': 'admin', 'node_type': 'baseline_promotion', 'label': 'Simulation evidence escrow node', 'data': {'promotion_id': promotion_id}, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert node_resp.status_code == 200, node_resp.text
        node_id = node_resp.json()['node']['node_id']

        simulated = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/simulate?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'admin', 'reason': 'simulation export for escrow'},
        )
        assert simulated.status_code == 200, simulated.text
        approve_ops = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/approve_simulation?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'ops-reviewer', 'reason': 'ops review passed', 'layer_id': 'ops'},
        )
        assert approve_ops.status_code == 200, approve_ops.text
        approve_risk = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/approve_simulation?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'risk-reviewer', 'reason': 'risk review passed', 'layer_id': 'risk'},
        )
        assert approve_risk.status_code == 200, approve_risk.text

        export_package = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/export_simulation_evidence_package?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'export-bot'},
        )
        assert export_package.status_code == 200, export_package.text
        export_payload = export_package.json()['result']
        assert export_payload['escrow']['archived'] is True
        assert export_payload['latest_simulation']['export_state']['latest_evidence_package']['escrow']['archived'] is True
        package_id = export_payload['package_id']

        clear_node = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes',
            headers=headers,
            json={
                'actor': 'admin',
                'node_id': node_id,
                'node_type': 'baseline_promotion',
                'label': 'Simulation evidence escrow node',
                'data': {'promotion_id': promotion_id},
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert clear_node.status_code == 200, clear_node.text
        assert 'latest_simulation' not in (clear_node.json()['node'].get('data') or {})

        verify = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/verify_simulation_evidence_package?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'auditor', 'package_id': package_id},
        )
        assert verify.status_code == 200, verify.text
        verify_payload = verify.json()['result']
        assert verify_payload['verification']['checks']['escrow_receipt_valid'] is True
        assert verify_payload['latest_simulation']['export_state']['latest_verification']['artifact_source'] == 'escrow'
        assert verify_payload['latest_simulation']['export_state']['latest_verification']['escrow_status'] == 'verified'

        restore = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/restore_simulation_evidence_package?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'auditor', 'package_id': package_id, 'persist_restore_session': True},
        )
        assert restore.status_code == 200, restore.text
        restore_payload = restore.json()['result']
        latest = restore_payload['latest_simulation']
        assert restore_payload['verification']['checks']['escrow_receipt_valid'] is True
        assert latest['export_state']['latest_evidence_package']['escrow']['archived'] is True
        assert latest['export_state']['latest_verification']['artifact_source'] == 'escrow'



def test_canvas_baseline_simulation_evidence_custody_reconciliation_detects_lock_drift(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_746_800.0
    _set_now(monkeypatch, base_now)
    monkeypatch.setenv('OPENMIURA_EVIDENCE_ESCROW_DIR', (tmp_path / 'escrow').as_posix())
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    escrow_policy = {
        'enabled': True,
        'provider': 'filesystem-object-lock',
        'archive_namespace': 'baseline-simulation-evidence-reconcile-canvas',
        'require_archive_on_export': True,
        'allow_inline_fallback': False,
        'immutable_retention_days': 90,
    }
    baseline_catalog = {
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
        catalog_payload = _create_baseline_catalog(
            client,
            headers,
            name='baseline-simulation-evidence-reconcile-canvas-catalog',
            version='catalog-v1',
            environment_policy_baselines=baseline_catalog,
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
        runtime_id = _create_runtime_for_environment(client, headers, name='runtime-canvas-simulation-evidence-reconcile', environment='prod')
        _create_portfolio_with_catalog(
            client,
            headers,
            base_now=base_now,
            runtime_id=runtime_id,
            environment='prod',
            environment_tier_policies=env_policy,
            baseline_catalog_ref={'catalog_id': catalog_payload['catalog_id']},
        )
        promotion = client.post(
            f'/admin/openclaw/alert-governance/baseline-catalogs/{catalog_payload["catalog_id"]}/promotions',
            headers=headers,
            json={
                'actor': 'catalog-admin',
                'version': 'catalog-v2-sim-evidence-reconcile-canvas',
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
        promotion_id = promotion.json()['promotion_id']

        canvas = client.post(
            '/admin/canvas/documents',
            headers=headers,
            json={'actor': 'admin', 'title': 'Simulation evidence reconcile canvas', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert canvas.status_code == 200, canvas.text
        canvas_id = canvas.json()['document']['canvas_id']
        node = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes',
            headers=headers,
            json={'actor': 'admin', 'node_type': 'baseline_promotion', 'label': 'Simulation evidence reconcile node', 'data': {'promotion_id': promotion_id}, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert node.status_code == 200, node.text
        node_id = node.json()['node']['node_id']

        simulated = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/simulate?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'admin', 'reason': 'simulation export for reconcile'},
        )
        assert simulated.status_code == 200, simulated.text
        approve_ops = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/approve_simulation?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'ops-reviewer', 'reason': 'ops review passed', 'layer_id': 'ops'},
        )
        assert approve_ops.status_code == 200, approve_ops.text
        approve_risk = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/approve_simulation?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'risk-reviewer', 'reason': 'risk review passed', 'layer_id': 'risk'},
        )
        assert approve_risk.status_code == 200, approve_risk.text
        export_package = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/export_simulation_evidence_package?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'export-bot'},
        )
        assert export_package.status_code == 200, export_package.text
        export_payload = export_package.json()['result']
        lock_path = Path(export_payload['escrow']['lock_path'])
        assert lock_path.exists()

        inspector = client.get(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert inspector.status_code == 200, inspector.text
        inspector_payload = inspector.json()
        assert 'reconcile_simulation_evidence_custody' in inspector_payload['available_actions']
        assert inspector_payload['action_prechecks']['reconcile_simulation_evidence_custody']['allowed'] is True

        reconcile = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/reconcile_simulation_evidence_custody?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'auditor'},
        )
        assert reconcile.status_code == 200, reconcile.text
        reconcile_payload = reconcile.json()['result']
        assert reconcile_payload['reconciliation']['summary']['overall_status'] == 'aligned'
        assert reconcile_payload['latest_simulation']['export_state']['latest_reconciliation']['overall_status'] == 'aligned'

        lock_path.unlink()
        drifted = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/reconcile_simulation_evidence_custody?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'auditor'},
        )
        assert drifted.status_code == 200, drifted.text
        drifted_payload = drifted.json()['result']
        assert drifted_payload['reconciliation']['summary']['overall_status'] == 'drifted'
        assert drifted_payload['reconciliation']['items'][0]['escrow']['status'] == 'object_lock_invalid'
        latest = drifted_payload['latest_simulation']
        assert latest['export_state']['latest_reconciliation']['overall_status'] == 'drifted'
        assert latest['export_state']['latest_reconciliation']['lock_drift_count'] >= 1
        assert latest['export_state']['latest_reconciliation']['reconciliation_id']
        inspector_after = client.get(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert inspector_after.status_code == 200, inspector_after.text
        node_data = inspector_after.json()['node']['data']
        assert node_data['last_simulation_evidence_reconciliation']['overall_status'] == 'drifted'


def test_canvas_baseline_simulation_custody_monitoring_job_blocks_rollout_after_drift(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_781_000.0
    _set_now(monkeypatch, base_now)
    monkeypatch.setenv('OPENMIURA_BASELINE_ESCROW_ROOT', str(tmp_path / 'escrow'))
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    scheduler = OpenClawRecoverySchedulerService()
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='canvas-sim-custody-monitoring-catalog',
            version='catalog-v1',
            environment_policy_baselines={
                'prod': {
                    'operational_tier': 'prod',
                    'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'}]},
                    'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v1'},
                    'escrow_policy': {'enabled': True, 'provider': 'filesystem-object-lock', 'classification': 'baseline-evidence'},
                },
            },
            promotion_policy={
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
                    'block_on_drift': True,
                    'target_path': '/ui/?tab=operator&view=baseline-promotions',
                },
            },
        )
        runtime_id = _create_runtime_for_environment(client, headers, name='runtime-canvas-sim-custody-monitoring', environment='prod')
        _create_portfolio_with_catalog(
            client,
            headers,
            base_now=base_now + 1,
            runtime_id=runtime_id,
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
        canvas = client.post('/admin/canvas/documents', headers=headers, json={'actor': 'operator', 'title': 'simulation custody canvas', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'})
        assert canvas.status_code == 200, canvas.text
        canvas_id = canvas.json()['document']['canvas_id']
        node_create = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes',
            headers=headers,
            json={'actor': 'operator', 'node_type': 'baseline_promotion', 'label': promotion_id, 'data': {'promotion_id': promotion_id}, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert node_create.status_code == 200, node_create.text
        node_id = node_create.json()['node']['node_id']
        simulate = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/simulate?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator'},
        )
        assert simulate.status_code == 200, simulate.text
        approve_ops = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/approve_simulation?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'ops-director', 'layer_id': 'ops', 'requested_role': 'ops-director', 'reason': 'ops ok'},
        )
        assert approve_ops.status_code == 200, approve_ops.text
        approve_risk = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/approve_simulation?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'risk-manager', 'layer_id': 'risk', 'requested_role': 'risk-manager', 'reason': 'risk ok'},
        )
        assert approve_risk.status_code == 200, approve_risk.text
        export_pkg = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/export_simulation_evidence_package?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'auditor'},
        )
        assert export_pkg.status_code == 200, export_pkg.text
        export_payload = export_pkg.json()['result']
        custody_job = export_payload['custody_job']
        assert custody_job['job_id']
        lock_path = Path((export_payload['latest_simulation']['export_state']['latest_evidence_package'] or {}).get('escrow', {}).get('lock_path') or export_payload['escrow']['lock_path'])
        assert lock_path.exists()
        lock_path.unlink()
        app.state.gw.audit.update_job_schedule(
            custody_job['job_id'],
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
        inspector = client.get(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert inspector.status_code == 200, inspector.text
        inspector_payload = inspector.json()
        assert inspector_payload['related']['baseline_promotion']['simulation_custody_monitoring']['guard']['blocked'] is True
        assert inspector_payload['action_prechecks']['create_rollout']['allowed'] is False
        assert inspector_payload['action_prechecks']['create_rollout']['reason'] == 'baseline_promotion_simulation_custody_drift_detected'
        assert inspector_payload['related']['baseline_promotion_board']['summary']['custody_guard_blocked'] is True


def test_canvas_baseline_simulation_custody_dashboard_and_alert_lifecycle_actions(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_783_000.0
    _set_now(monkeypatch, base_now)
    monkeypatch.setenv('OPENMIURA_BASELINE_ESCROW_ROOT', str(tmp_path / 'escrow'))
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    scheduler = OpenClawRecoverySchedulerService()
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='canvas-sim-custody-dashboard-catalog',
            version='catalog-v1',
            environment_policy_baselines={
                'prod': {
                    'operational_tier': 'prod',
                    'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'}]},
                    'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v1'},
                    'escrow_policy': {'enabled': True, 'provider': 'filesystem-object-lock', 'classification': 'baseline-evidence'},
                },
            },
            promotion_policy={
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
                    'default_mute_s': 1200,
                    'target_path': '/ui/?tab=operator&view=baseline-promotions',
                },
            },
        )
        runtime_id = _create_runtime_for_environment(client, headers, name='runtime-canvas-sim-custody-dashboard', environment='prod')
        _create_portfolio_with_catalog(
            client,
            headers,
            base_now=base_now + 1,
            runtime_id=runtime_id,
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
        canvas = client.post('/admin/canvas/documents', headers=headers, json={'actor': 'operator', 'title': 'simulation custody dashboard canvas', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'})
        assert canvas.status_code == 200, canvas.text
        canvas_id = canvas.json()['document']['canvas_id']
        node_create = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes',
            headers=headers,
            json={'actor': 'operator', 'node_type': 'baseline_promotion', 'label': promotion_id, 'data': {'promotion_id': promotion_id}, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        node_id = node_create.json()['node']['node_id']
        assert node_id
        assert client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/simulate?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator'},
        ).status_code == 200
        assert client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/approve_simulation?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'ops-director', 'layer_id': 'ops', 'requested_role': 'ops-director', 'reason': 'ops ok'},
        ).status_code == 200
        assert client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/approve_simulation?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'risk-manager', 'layer_id': 'risk', 'requested_role': 'risk-manager', 'reason': 'risk ok'},
        ).status_code == 200
        export_pkg = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/export_simulation_evidence_package?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'auditor'},
        )
        export_payload = export_pkg.json()['result']
        lock_path = Path((export_payload['latest_simulation']['export_state']['latest_evidence_package'] or {}).get('escrow', {}).get('lock_path') or export_payload['escrow']['lock_path'])
        lock_path.unlink()
        app.state.gw.audit.update_job_schedule(
            export_payload['custody_job']['job_id'],
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
        inspector = client.get(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        inspector_payload = inspector.json()
        assert inspector_payload['action_prechecks']['acknowledge_simulation_custody_alert']['allowed'] is True
        assert inspector_payload['action_prechecks']['mute_simulation_custody_alert']['allowed'] is True
        assert inspector_payload['related']['baseline_promotion_board']['summary']['custody_active_alert_count'] == 1
        ack = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/acknowledge_simulation_custody_alert?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'shift-lead', 'reason': 'triaged'},
        )
        assert ack.status_code == 200, ack.text
        ack_payload = ack.json()['result']
        assert ack_payload['simulation_custody_monitoring']['alerts']['summary']['acknowledged_count'] == 1
        mute = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/mute_simulation_custody_alert?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'shift-lead', 'reason': 'repair underway', 'mute_for_s': 600},
        )
        assert mute.status_code == 200, mute.text
        mute_payload = mute.json()['result']
        assert mute_payload['alert']['status'] == 'muted'
        board = client.get(
            f'/admin/canvas/documents/{canvas_id}/views/baseline-promotions?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert board.status_code == 200, board.text
        board_payload = board.json()
        assert board_payload['summary']['custody_muted_alert_count'] == 1
        assert board_payload['items'][0]['summary']['custody_muted_alert_count'] == 1
        resolve_precheck = client.get(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        ).json()['action_prechecks']['resolve_simulation_custody_alert']
        assert resolve_precheck['allowed'] is False
        assert resolve_precheck['reason'] == 'baseline_promotion_simulation_custody_alert_still_drifted'
        lock_payload = {
            'lock_type': 'openmiura_baseline_promotion_simulation_object_lock_v1',
            'provider': str(export_payload['escrow']['provider'] or ''),
            'archive_path': str(export_payload['escrow']['archive_path'] or ''),
            'artifact_sha256': str(export_payload['artifact']['sha256'] or ''),
            'package_id': str(export_payload['package_id'] or ''),
            'promotion_id': promotion_id,
            'simulation_id': str((export_payload['latest_simulation'] or {}).get('simulation_id') or ''),
            'immutable_until': export_payload['escrow']['immutable_until'],
            'retention_mode': str(export_payload['escrow']['retention_mode'] or ''),
            'legal_hold': bool(export_payload['escrow']['legal_hold']),
            'locked_at': export_payload['escrow']['archived_at'],
        }
        lock_path.write_text(json.dumps(lock_payload), encoding='utf-8')
        reconcile = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/reconcile_simulation_evidence_custody?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'monitor-bot'},
        )
        assert reconcile.status_code == 200, reconcile.text
        board_after = client.get(
            f'/admin/canvas/documents/{canvas_id}/views/baseline-promotions?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        board_after_payload = board_after.json()
        assert board_after_payload['summary']['custody_active_alert_count'] == 0
        assert board_after_payload['summary']['custody_guard_blocked_count'] == 0


def test_canvas_baseline_simulation_custody_escalation_and_suppression_surface(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_783_250.0
    _set_now(monkeypatch, base_now)
    monkeypatch.setenv('OPENMIURA_BASELINE_ESCROW_ROOT', str(tmp_path / 'escrow'))
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='canvas-sim-custody-escalation-catalog',
            version='catalog-v1',
            environment_policy_baselines={
                'prod': {
                    'operational_tier': 'prod',
                    'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'}]},
                    'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v1'},
                    'escrow_policy': {'enabled': True, 'provider': 'filesystem-object-lock', 'classification': 'baseline-evidence'},
                },
            },
            promotion_policy={
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
                    'default_mute_s': 1200,
                    'target_path': '/ui/?tab=operator&view=baseline-promotions',
                    'suppression_window_s': 0,
                    'escalation_enabled': True,
                    'escalation_levels': [
                        {'after_s': 60, 'severity': 'high', 'label': 'Ops escalation'},
                        {'after_s': 120, 'severity': 'critical', 'label': 'Critical escalation'},
                    ],
                    'suppress_while_muted': True,
                },
            },
        )
        runtime_id = _create_runtime_for_environment(client, headers, name='runtime-canvas-sim-custody-escalation', environment='prod')
        _create_portfolio_with_catalog(
            client,
            headers,
            base_now=base_now + 1,
            runtime_id=runtime_id,
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
        canvas = client.post('/admin/canvas/documents', headers=headers, json={'actor': 'operator', 'title': 'simulation custody escalation canvas', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'})
        canvas_id = canvas.json()['document']['canvas_id']
        node_create = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes',
            headers=headers,
            json={'actor': 'operator', 'node_type': 'baseline_promotion', 'label': promotion_id, 'data': {'promotion_id': promotion_id}, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        node_id = node_create.json()['node']['node_id']
        assert client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/simulate?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator'},
        ).status_code == 200
        assert client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/approve_simulation?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'ops-director', 'layer_id': 'ops', 'requested_role': 'ops-director', 'reason': 'ops ok'},
        ).status_code == 200
        assert client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/approve_simulation?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'risk-manager', 'layer_id': 'risk', 'requested_role': 'risk-manager', 'reason': 'risk ok'},
        ).status_code == 200
        export_pkg = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/export_simulation_evidence_package?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'auditor'},
        )
        export_payload = export_pkg.json()['result']
        Path((export_payload['latest_simulation']['export_state']['latest_evidence_package'] or {}).get('escrow', {}).get('lock_path') or export_payload['escrow']['lock_path']).unlink()

        first_reconcile = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/reconcile_simulation_evidence_custody?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'monitor-bot'},
        )
        assert first_reconcile.status_code == 200, first_reconcile.text
        _set_now(monkeypatch, base_now + 90)
        second_reconcile = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/reconcile_simulation_evidence_custody?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'monitor-bot'},
        )
        assert second_reconcile.status_code == 200, second_reconcile.text
        second_payload = second_reconcile.json()['result']
        assert second_payload['latest_simulation']['export_state']['custody_guard']['escalated'] is True
        assert second_payload['latest_simulation']['export_state']['custody_guard']['escalation_level'] == 1
        board = client.get(
            f'/admin/canvas/documents/{canvas_id}/views/baseline-promotions?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        board_payload = board.json()
        assert board_payload['summary']['custody_escalated_alert_count'] == 1
        assert board_payload['items'][0]['summary']['custody_escalated_alert_count'] == 1

        mute = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/mute_simulation_custody_alert?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'shift-lead', 'reason': 'repair underway', 'mute_for_s': 600},
        )
        assert mute.status_code == 200, mute.text
        _set_now(monkeypatch, base_now + 150)
        muted_reconcile = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/reconcile_simulation_evidence_custody?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'monitor-bot'},
        )
        assert muted_reconcile.status_code == 200, muted_reconcile.text
        muted_payload = muted_reconcile.json()['result']
        assert muted_payload['latest_simulation']['export_state']['custody_guard']['suppressed'] is True
        assert muted_payload['latest_simulation']['export_state']['custody_guard']['pending_escalation_level'] == 2
        board = client.get(
            f'/admin/canvas/documents/{canvas_id}/views/baseline-promotions?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        board_payload = board.json()
        assert board_payload['summary']['custody_suppressed_alert_count'] == 1
        assert board_payload['items'][0]['summary']['custody_suppressed_alert_count'] == 1



def test_canvas_baseline_simulation_custody_ownership_and_routing_surface(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_783_500.0
    _set_now(monkeypatch, base_now)
    monkeypatch.setenv('OPENMIURA_BASELINE_ESCROW_ROOT', str(tmp_path / 'escrow'))
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='canvas-sim-custody-ownership-catalog',
            version='catalog-v1',
            environment_policy_baselines={
                'prod': {
                    'operational_tier': 'prod',
                    'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'}]},
                    'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v1'},
                    'escrow_policy': {'enabled': True, 'provider': 'filesystem-object-lock', 'classification': 'baseline-evidence'},
                },
            },
            promotion_policy={
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
                    'routing_routes': [
                        {
                            'route_id': 'risk-review-route',
                            'label': 'Risk review',
                            'min_escalation_level': 1,
                            'queue_id': 'risk-review',
                            'queue_label': 'Risk Review',
                            'owner_role': 'risk-reviewer',
                        },
                    ],
                    'target_path': '/ui/?tab=operator&view=baseline-promotions',
                },
            },
        )
        runtime_id = _create_runtime_for_environment(client, headers, name='runtime-canvas-sim-custody-ownership', environment='prod')
        _create_portfolio_with_catalog(
            client,
            headers,
            base_now=base_now + 1,
            runtime_id=runtime_id,
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
        canvas = client.post('/admin/canvas/documents', headers=headers, json={'actor': 'operator', 'title': 'simulation custody ownership canvas', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'})
        canvas_id = canvas.json()['document']['canvas_id']
        node_create = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes',
            headers=headers,
            json={'actor': 'operator', 'node_type': 'baseline_promotion', 'label': promotion_id, 'data': {'promotion_id': promotion_id}, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        node_id = node_create.json()['node']['node_id']
        assert client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/simulate?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator'},
        ).status_code == 200
        assert client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/approve_simulation?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'ops-director', 'layer_id': 'ops', 'requested_role': 'ops-director', 'reason': 'ops ok'},
        ).status_code == 200
        assert client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/approve_simulation?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'risk-manager', 'layer_id': 'risk', 'requested_role': 'risk-manager', 'reason': 'risk ok'},
        ).status_code == 200
        export_pkg = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/export_simulation_evidence_package?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'auditor'},
        )
        export_payload = export_pkg.json()['result']
        Path((export_payload['latest_simulation']['export_state']['latest_evidence_package'] or {}).get('escrow', {}).get('lock_path') or export_payload['escrow']['lock_path']).unlink()

        first_reconcile = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/reconcile_simulation_evidence_custody?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'monitor-bot'},
        )
        assert first_reconcile.status_code == 200, first_reconcile.text
        first_payload = first_reconcile.json()['result']
        assert first_payload['latest_simulation']['export_state']['custody_active_alert']['ownership']['queue_id'] == 'ops-oncall'
        inspector = client.get(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        ).json()
        assert inspector['action_prechecks']['claim_simulation_custody_alert']['allowed'] is True
        assert inspector['action_prechecks']['assign_simulation_custody_alert']['allowed'] is True
        assert inspector['related']['baseline_promotion_board']['summary']['custody_unowned_alert_count'] == 1

        claim = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/claim_simulation_custody_alert?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'shift-lead'},
        )
        assert claim.status_code == 200, claim.text
        claim_payload = claim.json()['result']
        assert claim_payload['alert']['ownership']['owner_id'] == 'shift-lead'
        assert claim_payload['latest_simulation']['export_state']['custody_active_alert']['ownership']['owner_id'] == 'shift-lead'

        reroute = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/reroute_simulation_custody_alert?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'shift-lead', 'route_id': 'risk-review-route', 'queue_id': 'risk-review', 'queue_label': 'Risk Review', 'owner_role': 'risk-reviewer', 'route_label': 'Risk review'},
        )
        assert reroute.status_code == 200, reroute.text
        reroute_payload = reroute.json()['result']
        assert reroute_payload['alert']['routing']['route_id'] == 'risk-review-route'
        assert reroute_payload['latest_simulation']['export_state']['custody_active_alert']['routing']['queue_id'] == 'risk-review'

        release = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/release_simulation_custody_alert?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'shift-lead'},
        )
        assert release.status_code == 200, release.text
        release_payload = release.json()['result']
        assert release_payload['alert']['ownership']['owner_id'] == ''
        board = client.get(
            f'/admin/canvas/documents/{canvas_id}/views/baseline-promotions?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        ).json()
        assert board['summary']['custody_owned_alert_count'] == 0
        assert board['summary']['custody_unowned_alert_count'] == 1
        assert board['summary']['custody_routed_alert_count'] == 1



def test_canvas_baseline_simulation_custody_handoff_and_sla_surface(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_786_000.0
    _set_now(monkeypatch, base_now)
    monkeypatch.setenv('OPENMIURA_BASELINE_ESCROW_ROOT', str(tmp_path / 'escrow'))
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='canvas-sim-custody-handoff-catalog',
            version='catalog-v1',
            environment_policy_baselines={
                'prod': {
                    'operational_tier': 'prod',
                    'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'}]},
                    'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v1'},
                    'escrow_policy': {'enabled': True, 'provider': 'filesystem-object-lock', 'classification': 'baseline-evidence'},
                },
            },
            promotion_policy={
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
                    'target_path': '/ui/?tab=operator&view=baseline-promotions',
                },
            },
        )
        runtime_id = _create_runtime_for_environment(client, headers, name='runtime-canvas-sim-custody-handoff', environment='prod')
        _create_portfolio_with_catalog(
            client,
            headers,
            base_now=base_now + 1,
            runtime_id=runtime_id,
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
        canvas = client.post('/admin/canvas/documents', headers=headers, json={'actor': 'operator', 'title': 'simulation custody handoff canvas', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'})
        canvas_id = canvas.json()['document']['canvas_id']
        node_create = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes',
            headers=headers,
            json={'actor': 'operator', 'node_type': 'baseline_promotion', 'label': promotion_id, 'data': {'promotion_id': promotion_id}, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        node_id = node_create.json()['node']['node_id']
        assert client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/simulate?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator'},
        ).status_code == 200
        assert client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/approve_simulation?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'ops-director', 'layer_id': 'ops', 'requested_role': 'ops-director', 'reason': 'ops ok'},
        ).status_code == 200
        assert client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/approve_simulation?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'risk-manager', 'layer_id': 'risk', 'requested_role': 'risk-manager', 'reason': 'risk ok'},
        ).status_code == 200
        export_pkg = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/export_simulation_evidence_package?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'auditor'},
        )
        export_payload = export_pkg.json()['result']
        Path((export_payload['latest_simulation']['export_state']['latest_evidence_package'] or {}).get('escrow', {}).get('lock_path') or export_payload['escrow']['lock_path']).unlink()
        reconcile = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/reconcile_simulation_evidence_custody?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'monitor-bot'},
        )
        assert reconcile.status_code == 200, reconcile.text

        claim = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/claim_simulation_custody_alert?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'shift-lead'},
        )
        assert claim.status_code == 200, claim.text
        handoff = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/handoff_simulation_custody_alert?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'shift-lead', 'reason': 'shift handoff to risk', 'owner_id': 'risk-reviewer', 'owner_role': 'risk-reviewer', 'queue_id': 'risk-review', 'queue_label': 'Risk Review', 'route_id': 'risk-review-route', 'route_label': 'Risk review'},
        )
        assert handoff.status_code == 200, handoff.text
        handoff_payload = handoff.json()['result']
        assert handoff_payload['alert']['handoff']['pending'] is True
        assert handoff_payload['latest_simulation']['export_state']['custody_active_alert']['handoff']['pending'] is True
        inspector = client.get(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        ).json()
        assert inspector['action_prechecks']['handoff_simulation_custody_alert']['allowed'] is True

        _set_now(monkeypatch, base_now + 35)
        reconcile_breach = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/reconcile_simulation_evidence_custody?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'monitor-bot'},
        )
        assert reconcile_breach.status_code == 200, reconcile_breach.text
        breach_payload = reconcile_breach.json()['result']
        assert breach_payload['latest_simulation']['export_state']['custody_guard']['sla_breached'] is True
        assert 'handoff_accept' in breach_payload['latest_simulation']['export_state']['custody_active_alert']['sla']['breached_targets']
        board = client.get(
            f'/admin/canvas/documents/{canvas_id}/views/baseline-promotions?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        ).json()
        assert board['summary']['custody_handoff_pending_alert_count'] == 1
        assert board['summary']['custody_sla_breached_alert_count'] == 1

        accept = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/claim_simulation_custody_alert?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'risk-reviewer'},
        )
        assert accept.status_code == 200, accept.text
        accept_payload = accept.json()['result']
        assert accept_payload['alert']['handoff']['pending'] is False
        assert accept_payload['latest_simulation']['export_state']['custody_active_alert']['handoff']['pending'] is False


def test_canvas_baseline_simulation_custody_sla_auto_reroute_team_queue_surface(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_786_250.0
    _set_now(monkeypatch, base_now)
    monkeypatch.setenv('OPENMIURA_BASELINE_ESCROW_ROOT', str(tmp_path / 'escrow'))
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='canvas-sim-custody-sla-reroute-catalog',
            version='catalog-v1',
            environment_policy_baselines={
                'prod': {
                    'operational_tier': 'prod',
                    'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'}]},
                    'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v1'},
                    'escrow_policy': {'enabled': True, 'provider': 'filesystem-object-lock', 'classification': 'baseline-evidence'},
                },
            },
            promotion_policy={
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
            },
        )
        runtime_id = _create_runtime_for_environment(client, headers, name='runtime-canvas-sim-custody-sla-reroute', environment='prod')
        _create_portfolio_with_catalog(
            client,
            headers,
            base_now=base_now + 1,
            runtime_id=runtime_id,
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
        canvas = client.post('/admin/canvas/documents', headers=headers, json={'actor': 'operator', 'title': 'simulation custody sla reroute canvas', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'})
        canvas_id = canvas.json()['document']['canvas_id']
        node_create = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes',
            headers=headers,
            json={'actor': 'operator', 'node_type': 'baseline_promotion', 'label': promotion_id, 'data': {'promotion_id': promotion_id}, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        node_id = node_create.json()['node']['node_id']
        assert client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/simulate?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator'},
        ).status_code == 200
        assert client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/approve_simulation?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'ops-director', 'layer_id': 'ops', 'requested_role': 'ops-director', 'reason': 'ops ok'},
        ).status_code == 200
        assert client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/approve_simulation?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'risk-manager', 'layer_id': 'risk', 'requested_role': 'risk-manager', 'reason': 'risk ok'},
        ).status_code == 200
        export_pkg = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/export_simulation_evidence_package?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'auditor'},
        )
        export_payload = export_pkg.json()['result']
        Path((export_payload['latest_simulation']['export_state']['latest_evidence_package'] or {}).get('escrow', {}).get('lock_path') or export_payload['escrow']['lock_path']).unlink()

        first_reconcile = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/reconcile_simulation_evidence_custody?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'monitor-bot'},
        )
        assert first_reconcile.status_code == 200, first_reconcile.text
        _set_now(monkeypatch, base_now + 40)
        second_reconcile = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/reconcile_simulation_evidence_custody?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'monitor-bot'},
        )
        assert second_reconcile.status_code == 200, second_reconcile.text
        second_payload = second_reconcile.json()['result']
        active_alert = second_payload['latest_simulation']['export_state']['custody_active_alert']
        assert active_alert['routing']['source'] == 'sla_breach_routing'
        assert active_alert['routing']['queue_id'] == 'incident-command'
        assert active_alert['routing']['owner_role'] == 'incident-commander'
        assert active_alert['sla_routing']['reroute_count'] == 1
        assert second_payload['latest_simulation']['export_state']['custody_guard']['sla_rerouted'] is True
        assert second_payload['latest_simulation']['export_state']['custody_guard']['team_queue_id'] == 'incident-command'

        board = client.get(
            f'/admin/canvas/documents/{canvas_id}/views/baseline-promotions?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        ).json()
        assert board['summary']['custody_sla_rerouted_alert_count'] == 1
        assert board['summary']['custody_team_queue_alert_count'] == 1
        assert board['items'][0]['summary']['custody_sla_rerouted_alert_count'] == 1
        assert board['items'][0]['summary']['custody_team_queue_alert_count'] == 1


def test_canvas_baseline_simulation_custody_load_aware_queue_capacity_surface(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_786_700.0
    _set_now(monkeypatch, base_now)
    monkeypatch.setenv('OPENMIURA_BASELINE_ESCROW_ROOT', str(tmp_path / 'escrow'))
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    scheduler = OpenClawRecoverySchedulerService()
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='canvas-sim-custody-load-aware-catalog',
            version='catalog-v1',
            environment_policy_baselines={
                'prod': {
                    'operational_tier': 'prod',
                    'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'}]},
                    'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v1'},
                    'escrow_policy': {'enabled': True, 'provider': 'filesystem-object-lock', 'classification': 'baseline-evidence'},
                },
            },
            promotion_policy={
                'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'gov', 'requested_role': 'governance-board', 'label': 'Governance board'}]},
                'simulation_custody_monitoring_policy': {
                    'enabled': True,
                    'auto_schedule': True,
                    'interval_s': 300,
                    'notify_on_drift': True,
                    'block_on_drift': True,
                    'load_aware_routing_enabled': True,
                    'queue_capacity_policy': {'enabled': True, 'default_capacity': 1, 'prefer_lowest_load': True},
                    'routing_routes': [
                        {'route_id': 'ops-primary-route', 'label': 'Ops primary', 'queue_id': 'ops-primary', 'queue_label': 'Ops Primary', 'owner_role': 'shift-lead', 'queue_capacity': 1},
                        {'route_id': 'ops-backup-route', 'label': 'Ops backup', 'queue_id': 'ops-backup', 'queue_label': 'Ops Backup', 'owner_role': 'shift-lead', 'queue_capacity': 2},
                    ],
                    'default_route': {'route_id': 'ops-primary-route', 'label': 'Ops primary', 'queue_id': 'ops-primary', 'queue_label': 'Ops Primary', 'owner_role': 'shift-lead', 'queue_capacity': 1},
                    'queue_capacities': [
                        {'queue_id': 'ops-primary', 'queue_label': 'Ops Primary', 'capacity': 1},
                        {'queue_id': 'ops-backup', 'queue_label': 'Ops Backup', 'capacity': 2},
                    ],
                },
            },
        )
        runtime_id = _create_runtime_for_environment(client, headers, name='runtime-canvas-sim-custody-load-aware', environment='prod')
        _create_portfolio_with_catalog(
            client,
            headers,
            base_now=base_now + 1,
            runtime_id=runtime_id,
            environment='prod',
            environment_tier_policies=_env_policy('baseline-v2'),
            baseline_catalog_ref={'catalog_id': catalog['catalog_id']},
        )

        def _create_promotion(version: str) -> str:
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
            return response.json()['promotion_id']

        promotion_one = _create_promotion('catalog-v2')
        promotion_two = _create_promotion('catalog-v3')
        canvas = client.post('/admin/canvas/documents', headers=headers, json={'actor': 'operator', 'title': 'simulation custody load aware canvas', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'})
        canvas_id = canvas.json()['document']['canvas_id']

        def _create_node(promotion_id: str) -> str:
            node_create = client.post(
                f'/admin/canvas/documents/{canvas_id}/nodes',
                headers=headers,
                json={'actor': 'operator', 'node_type': 'baseline_promotion', 'label': promotion_id, 'data': {'promotion_id': promotion_id}, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
            )
            return node_create.json()['node']['node_id']

        def _simulate_and_export(node_id: str) -> dict[str, Any]:
            assert client.post(
                f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/simulate?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
                headers=headers,
                json={'actor': 'operator'},
            ).status_code == 200
            export_pkg = client.post(
                f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/export_simulation_evidence_package?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
                headers=headers,
                json={'actor': 'auditor'},
            )
            assert export_pkg.status_code == 200, export_pkg.text
            lock_path = (export_pkg.json()['result']['latest_simulation']['export_state']['latest_evidence_package'] or {}).get('escrow', {}).get('lock_path') or (export_pkg.json()['result'].get('escrow') or {}).get('lock_path')
            Path(lock_path).unlink()
            reconcile = client.post(
                f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/reconcile_simulation_evidence_custody?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
                headers=headers,
                json={'actor': 'monitor-bot'},
            )
            assert reconcile.status_code == 200, reconcile.text
            return reconcile.json()

        node_one = _create_node(promotion_one)
        node_two = _create_node(promotion_two)
        first_reconcile = _simulate_and_export(node_one)
        second_reconcile = _simulate_and_export(node_two)
        latest_simulation = second_reconcile['result']['latest_simulation']
        assert latest_simulation['export_state']['custody_active_alert']['routing']['queue_id'] in {'ops-primary', 'ops-backup'}
        assert latest_simulation['export_state']['custody_active_alert']['routing']['load_aware'] is True
        assert latest_simulation['export_state']['custody_active_alert']['routing']['queue_capacity'] in {1, 2}
        assert latest_simulation['export_state']['custody_guard']['load_aware_routing'] is True

        board = client.get(
            f'/admin/canvas/documents/{canvas_id}/views/baseline-promotions?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        ).json()
        assert board['summary']['custody_queue_at_capacity_alert_count'] >= 1
        assert board['summary']['custody_load_aware_routed_alert_count'] >= 2
        assert any(item['summary']['custody_load_aware_routed_alert_count'] >= 1 for item in board['items'])
        second_item = next(item for item in board['items'] if item['promotion_id'] == promotion_two)
        assert second_item['summary']['custody_load_aware_routed_alert_count'] == 1



def test_canvas_baseline_simulation_custody_routing_replay_action_surface(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_789_100.0
    _set_now(monkeypatch, base_now)
    monkeypatch.setenv('OPENMIURA_BASELINE_ESCROW_ROOT', str(tmp_path / 'escrow'))
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='canvas-sim-custody-routing-replay-catalog',
            version='catalog-v1',
            environment_policy_baselines={
                'prod': {
                    'operational_tier': 'prod',
                    'approval_policy': {'mode': 'parallel', 'layers': [{'layer_id': 'ops', 'requested_role': 'ops-director', 'label': 'Ops director'}]},
                    'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'baseline-v1'},
                    'escrow_policy': {'enabled': True, 'provider': 'filesystem-object-lock', 'classification': 'baseline-evidence'},
                },
            },
            promotion_policy={
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
                        'queue_families_enabled': True,
                        'multi_hop_hysteresis_enabled': True,
                        'family_reroute_cooldown_s': 300,
                        'family_recent_hops_threshold': 2,
                        'family_min_active_delta': 1,
                        'family_min_load_delta': 0.2,
                        'family_min_projected_wait_delta_s': 120,
                    },
                    'routing_routes': [
                        {'route_id': 'ops-a-route', 'label': 'Ops A', 'queue_id': 'ops-a', 'queue_label': 'Ops A', 'owner_role': 'shift-lead', 'queue_capacity': 1},
                        {'route_id': 'ops-b-route', 'label': 'Ops B', 'queue_id': 'ops-b', 'queue_label': 'Ops B', 'owner_role': 'shift-lead', 'queue_capacity': 2},
                    ],
                    'default_route': {'route_id': 'ops-a-route', 'label': 'Ops A', 'queue_id': 'ops-a', 'queue_label': 'Ops A', 'owner_role': 'shift-lead', 'queue_capacity': 1},
                    'queue_capacities': [
                        {'queue_id': 'ops-a', 'queue_label': 'Ops A', 'capacity': 1, 'queue_family_id': 'ops-family', 'queue_family_label': 'Ops Family'},
                        {'queue_id': 'ops-b', 'queue_label': 'Ops B', 'capacity': 2, 'queue_family_id': 'ops-family', 'queue_family_label': 'Ops Family'},
                    ],
                },
            },
        )
        runtime_id = _create_runtime_for_environment(client, headers, name='runtime-canvas-sim-custody-routing-replay', environment='prod')
        _create_portfolio_with_catalog(
            client,
            headers,
            base_now=base_now + 1,
            runtime_id=runtime_id,
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
                'environment_policy_baselines': {
                    'prod': {
                        'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'catalog-v2'},
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

        canvas = client.post('/admin/canvas/documents', headers=headers, json={'actor': 'operator', 'title': 'simulation custody routing replay canvas', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'})
        canvas_id = canvas.json()['document']['canvas_id']
        node_create = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes',
            headers=headers,
            json={'actor': 'operator', 'node_type': 'baseline_promotion', 'label': promotion_id, 'data': {'promotion_id': promotion_id}, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        node_id = node_create.json()['node']['node_id']

        assert client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/simulate?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator'},
        ).status_code == 200
        export_pkg = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/export_simulation_evidence_package?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'auditor'},
        )
        assert export_pkg.status_code == 200, export_pkg.text
        lock_path = (export_pkg.json()['result']['latest_simulation']['export_state']['latest_evidence_package'] or {}).get('escrow', {}).get('lock_path') or export_pkg.json()['result']['escrow']['lock_path']
        Path(lock_path).unlink()
        reconcile = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/reconcile_simulation_evidence_custody?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'monitor-bot'},
        )
        assert reconcile.status_code == 200, reconcile.text

        inspector = client.get(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert inspector.status_code == 200, inspector.text
        inspector_payload = inspector.json()
        assert 'replay_simulation_custody_routing' in inspector_payload['available_actions']
        assert inspector_payload['action_prechecks']['replay_simulation_custody_routing']['allowed'] is True

        replay = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/replay_simulation_custody_routing?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={
                'actor': 'operator',
                'alert_overrides': {
                    'routing': {
                        'queue_id': 'ops-a',
                        'queue_label': 'Ops A',
                        'route_id': 'ops-a-route',
                        'route_label': 'Ops A',
                        'queue_family_id': 'ops-family',
                        'updated_at': base_now - 30,
                        'route_history': [
                            {'queue_id': 'ops-a', 'queue_family_id': 'ops-family', 'at': base_now - 200},
                            {'queue_id': 'ops-b', 'queue_family_id': 'ops-family', 'at': base_now - 120},
                            {'queue_id': 'ops-a', 'queue_family_id': 'ops-family', 'at': base_now - 60},
                        ],
                    },
                },
                'comparison_policies': [
                    {
                        'scenario_id': 'disable_family_hysteresis',
                        'label': 'Disable family hysteresis',
                        'policy_overrides': {'queue_capacity_policy': {'multi_hop_hysteresis_enabled': False}},
                    },
                ],
            },
        )
        assert replay.status_code == 200, replay.text
        replay_payload = replay.json()['result']['routing_replay']
        assert replay_payload['current_policy']['route']['queue_id'] in {'ops-a', 'ops-b'}
        alt = next(item for item in replay_payload['scenarios'] if item['scenario_id'] == 'disable_family_hysteresis')
        assert alt['route']['queue_id'] in {'ops-a', 'ops-b'}
        assert 'queue_capacity_policy.multi_hop_hysteresis_enabled' in alt['policy_delta_keys']

        refreshed_inspector = client.get(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        refreshed_payload = refreshed_inspector.json()
        latest_replay = ((refreshed_payload['node']['data'].get('latest_simulation') or {}).get('export_state') or {}).get('latest_routing_replay') or {}
        assert latest_replay['scenario_count'] >= 2
        assert latest_replay['scenarios'][0]['scenario_id'] == 'current_policy'




def test_canvas_routing_policy_pack_save_and_replay_from_saved_pack(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_788_300.0
    _set_now(monkeypatch, base_now)
    monkeypatch.setenv('OPENMIURA_BASELINE_ESCROW_ROOT', str(tmp_path / 'escrow'))
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='catalog-routing-pack-v1',
            version='catalog-v1',
            environment_policy_baselines={'prod': {'operational_tier': 'prod', 'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'catalog-v1'}, 'escrow_policy': {'enabled': True, 'provider': 'filesystem-object-lock', 'classification': 'baseline-evidence'}}},
            promotion_policy={
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
                        'queue_families_enabled': True,
                        'multi_hop_hysteresis_enabled': True,
                        'family_reroute_cooldown_s': 300,
                        'family_recent_hops_threshold': 2,
                        'family_min_active_delta': 1,
                        'family_min_load_delta': 0.2,
                        'family_min_projected_wait_delta_s': 120,
                    },
                    'routing_routes': [
                        {'route_id': 'ops-a-route', 'label': 'Ops A', 'queue_id': 'ops-a', 'queue_label': 'Ops A', 'owner_role': 'shift-lead', 'queue_capacity': 1},
                        {'route_id': 'ops-b-route', 'label': 'Ops B', 'queue_id': 'ops-b', 'queue_label': 'Ops B', 'owner_role': 'shift-lead', 'queue_capacity': 2},
                    ],
                    'default_route': {'route_id': 'ops-a-route', 'label': 'Ops A', 'queue_id': 'ops-a', 'queue_label': 'Ops A', 'owner_role': 'shift-lead', 'queue_capacity': 1},
                    'queue_capacities': [
                        {'queue_id': 'ops-a', 'queue_label': 'Ops A', 'capacity': 1, 'queue_family_id': 'ops-family', 'queue_family_label': 'Ops Family'},
                        {'queue_id': 'ops-b', 'queue_label': 'Ops B', 'capacity': 2, 'queue_family_id': 'ops-family', 'queue_family_label': 'Ops Family'},
                    ],
                },
            },
        )
        runtime_id = _create_runtime_for_environment(client, headers, name='runtime-routing-pack', environment='prod')
        _create_portfolio_with_catalog(client, headers, base_now=base_now + 1, runtime_id=runtime_id, environment='prod', environment_tier_policies=_env_policy('baseline-v2'), baseline_catalog_ref={'catalog_id': catalog['catalog_id']})
        promotion = client.post(
            f'/admin/openclaw/alert-governance/baseline-catalogs/{catalog["catalog_id"]}/promotions',
            headers=headers,
            json={
                'actor': 'catalog-admin',
                'version': 'catalog-v2',
                'environment_policy_baselines': {'prod': {'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'catalog-v2'}, 'escrow_policy': {'enabled': True, 'provider': 'filesystem-object-lock', 'classification': 'baseline-evidence'}}},
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert promotion.status_code == 200, promotion.text
        promotion_id = promotion.json()['promotion_id']
        canvas = client.post('/admin/canvas/documents', headers=headers, json={'actor': 'operator', 'title': 'routing policy pack canvas', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'})
        canvas_id = canvas.json()['document']['canvas_id']
        node_create = client.post(f'/admin/canvas/documents/{canvas_id}/nodes', headers=headers, json={'actor': 'operator', 'node_type': 'baseline_promotion', 'label': promotion_id, 'data': {'promotion_id': promotion_id}, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'})
        node_id = node_create.json()['node']['node_id']
        assert client.post(f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/simulate?tenant_id=tenant-a&workspace_id=ws-a&environment=prod', headers=headers, json={'actor': 'operator'}).status_code == 200
        export_pkg = client.post(f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/export_simulation_evidence_package?tenant_id=tenant-a&workspace_id=ws-a&environment=prod', headers=headers, json={'actor': 'auditor'})
        assert export_pkg.status_code == 200, export_pkg.text
        lock_path = (export_pkg.json()['result']['latest_simulation']['export_state']['latest_evidence_package'] or {}).get('escrow', {}).get('lock_path') or export_pkg.json()['result']['escrow']['lock_path']
        Path(lock_path).unlink()
        assert client.post(f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/reconcile_simulation_evidence_custody?tenant_id=tenant-a&workspace_id=ws-a&environment=prod', headers=headers, json={'actor': 'monitor-bot'}).status_code == 200
        inspector = client.get(f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod', headers=headers)
        inspector_payload = inspector.json()
        assert 'save_simulation_custody_routing_policy_pack' in inspector_payload['available_actions']
        assert 'replay_saved_simulation_custody_routing_policy_pack' in inspector_payload['available_actions']
        save_pack = client.post(f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/save_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod', headers=headers, json={'actor': 'operator', 'preset_pack_id': 'family_hysteresis_presets'})
        assert save_pack.status_code == 200, save_pack.text
        assert save_pack.json()['result']['policy_pack']['pack_id'] == 'family_hysteresis_presets'
        replay = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/replay_saved_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={
                'actor': 'operator',
                'pack_id': 'family_hysteresis_presets',
                'alert_overrides': {
                    'routing': {
                        'queue_id': 'ops-a',
                        'queue_label': 'Ops A',
                        'route_id': 'ops-a-route',
                        'route_label': 'Ops A',
                        'queue_family_id': 'ops-family',
                        'updated_at': base_now - 30,
                        'route_history': [
                            {'queue_id': 'ops-a', 'queue_family_id': 'ops-family', 'at': base_now - 200},
                            {'queue_id': 'ops-b', 'queue_family_id': 'ops-family', 'at': base_now - 120},
                            {'queue_id': 'ops-a', 'queue_family_id': 'ops-family', 'at': base_now - 60},
                        ],
                    },
                },
            },
        )
        assert replay.status_code == 200, replay.text
        replay_payload = replay.json()['result']['routing_replay']
        assert replay_payload['applied_pack']['pack_id'] == 'family_hysteresis_presets'
        refreshed = client.get(f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod', headers=headers)
        export_state = ((refreshed.json()['node']['data'].get('latest_simulation') or {}).get('export_state') or {})
        assert export_state['saved_routing_policy_packs'][0]['pack_id'] == 'family_hysteresis_presets'



def test_canvas_routing_policy_pack_registry_promotion_share_and_replay(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_788_320.0
    _set_now(monkeypatch, base_now)
    monkeypatch.setenv('OPENMIURA_BASELINE_ESCROW_ROOT', str(tmp_path / 'escrow'))
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='catalog-routing-pack-registry-v1',
            version='catalog-v1',
            environment_policy_baselines={'prod': {'operational_tier': 'prod', 'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'catalog-v1'}, 'escrow_policy': {'enabled': True, 'provider': 'filesystem-object-lock', 'classification': 'baseline-evidence'}}},
            promotion_policy={
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
                        'queue_families_enabled': True,
                        'multi_hop_hysteresis_enabled': True,
                        'family_reroute_cooldown_s': 300,
                        'family_recent_hops_threshold': 2,
                        'family_min_active_delta': 1,
                        'family_min_load_delta': 0.2,
                        'family_min_projected_wait_delta_s': 120,
                    },
                    'routing_routes': [
                        {'route_id': 'ops-a-route', 'label': 'Ops A', 'queue_id': 'ops-a', 'queue_label': 'Ops A', 'owner_role': 'shift-lead', 'queue_capacity': 1},
                        {'route_id': 'ops-b-route', 'label': 'Ops B', 'queue_id': 'ops-b', 'queue_label': 'Ops B', 'owner_role': 'shift-lead', 'queue_capacity': 2},
                    ],
                    'default_route': {'route_id': 'ops-a-route', 'label': 'Ops A', 'queue_id': 'ops-a', 'queue_label': 'Ops A', 'owner_role': 'shift-lead', 'queue_capacity': 1},
                    'queue_capacities': [
                        {'queue_id': 'ops-a', 'queue_label': 'Ops A', 'capacity': 1, 'queue_family_id': 'ops-family', 'queue_family_label': 'Ops Family'},
                        {'queue_id': 'ops-b', 'queue_label': 'Ops B', 'capacity': 2, 'queue_family_id': 'ops-family', 'queue_family_label': 'Ops Family'},
                    ],
                },
            },
        )
        runtime_id = _create_runtime_for_environment(client, headers, name='runtime-routing-pack-registry', environment='prod')
        _create_portfolio_with_catalog(client, headers, base_now=base_now + 1, runtime_id=runtime_id, environment='prod', environment_tier_policies=_env_policy('baseline-v2'), baseline_catalog_ref={'catalog_id': catalog['catalog_id']})
        promotion = client.post(
            f'/admin/openclaw/alert-governance/baseline-catalogs/{catalog["catalog_id"]}/promotions',
            headers=headers,
            json={
                'actor': 'catalog-admin',
                'version': 'catalog-v2',
                'environment_policy_baselines': {'prod': {'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'catalog-v2'}, 'escrow_policy': {'enabled': True, 'provider': 'filesystem-object-lock', 'classification': 'baseline-evidence'}}},
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert promotion.status_code == 200, promotion.text
        promotion_id = promotion.json()['promotion_id']
        canvas = client.post('/admin/canvas/documents', headers=headers, json={'actor': 'operator', 'title': 'routing policy pack registry canvas', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'})
        canvas_id = canvas.json()['document']['canvas_id']
        node_create = client.post(f'/admin/canvas/documents/{canvas_id}/nodes', headers=headers, json={'actor': 'operator', 'node_type': 'baseline_promotion', 'label': promotion_id, 'data': {'promotion_id': promotion_id}, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'})
        node_id = node_create.json()['node']['node_id']
        assert client.post(f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/simulate?tenant_id=tenant-a&workspace_id=ws-a&environment=prod', headers=headers, json={'actor': 'operator'}).status_code == 200
        export_pkg = client.post(f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/export_simulation_evidence_package?tenant_id=tenant-a&workspace_id=ws-a&environment=prod', headers=headers, json={'actor': 'auditor'})
        assert export_pkg.status_code == 200, export_pkg.text
        lock_path = (export_pkg.json()['result']['latest_simulation']['export_state']['latest_evidence_package'] or {}).get('escrow', {}).get('lock_path') or export_pkg.json()['result']['escrow']['lock_path']
        Path(lock_path).unlink()
        assert client.post(f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/reconcile_simulation_evidence_custody?tenant_id=tenant-a&workspace_id=ws-a&environment=prod', headers=headers, json={'actor': 'monitor-bot'}).status_code == 200

        inspector = client.get(f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod', headers=headers)
        inspector_payload = inspector.json()
        assert 'promote_simulation_custody_routing_policy_pack_to_registry' in inspector_payload['available_actions']
        assert 'replay_registered_simulation_custody_routing_policy_pack' in inspector_payload['available_actions']
        assert 'share_registered_simulation_custody_routing_policy_pack' in inspector_payload['available_actions']

        save_pack = client.post(f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/save_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod', headers=headers, json={'actor': 'operator', 'preset_pack_id': 'family_hysteresis_presets'})
        assert save_pack.status_code == 200, save_pack.text

        promote = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/promote_simulation_custody_routing_policy_pack_to_registry?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator', 'pack_id': 'family_hysteresis_presets', 'registry_scope': 'workspace'},
        )
        assert promote.status_code == 200, promote.text
        assert promote.json()['result']['policy_pack']['source'] == 'registry'
        assert promote.json()['result']['policy_pack']['registry_scope'] == 'workspace'

        replay = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/replay_registered_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={
                'actor': 'operator',
                'pack_id': 'family_hysteresis_presets',
                'alert_overrides': {
                    'routing': {
                        'queue_id': 'ops-a',
                        'queue_label': 'Ops A',
                        'route_id': 'ops-a-route',
                        'route_label': 'Ops A',
                        'queue_family_id': 'ops-family',
                        'updated_at': base_now - 30,
                        'route_history': [
                            {'queue_id': 'ops-a', 'queue_family_id': 'ops-family', 'at': base_now - 200},
                            {'queue_id': 'ops-b', 'queue_family_id': 'ops-family', 'at': base_now - 120},
                            {'queue_id': 'ops-a', 'queue_family_id': 'ops-family', 'at': base_now - 60},
                        ],
                    },
                },
            },
        )
        assert replay.status_code == 200, replay.text
        assert replay.json()['result']['routing_replay']['applied_pack']['source'] == 'registry'

        share = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/share_registered_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator', 'pack_id': 'family_hysteresis_presets', 'target_pack_id': 'family_hysteresis_presets_shared', 'share_targets': ['workspace:ws-a']},
        )
        assert share.status_code == 200, share.text
        assert share.json()['result']['policy_pack']['source'] == 'shared_registry'
        assert share.json()['result']['policy_pack']['shared_from_pack_id'] == 'family_hysteresis_presets'

        refreshed = client.get(f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod', headers=headers)
        node_data = refreshed.json()['node']['data']
        assert node_data['routing_policy_pack_registry'][0]['pack_id'] == 'family_hysteresis_presets'
        assert node_data['routing_policy_pack_registry'][0]['registry_scope'] == 'workspace'
        assert node_data['last_promoted_routing_policy_pack']['source'] == 'registry'
        assert node_data['saved_routing_policy_packs'][0]['pack_id'] == 'family_hysteresis_presets_shared'
        assert node_data['saved_routing_policy_packs'][0]['shared_from_pack_id'] == 'family_hysteresis_presets'
        assert node_data['last_shared_routing_policy_pack']['source'] == 'shared_registry'

def test_canvas_compacts_routing_replay_state() -> None:
    replay = LiveCanvasService._compact_baseline_promotion_simulation_routing_replay({
        'alert_id': 'alert-1',
        'applied_pack': {'pack_id': 'family_hysteresis_presets', 'pack_label': 'Families + hysteresis presets', 'source': 'saved', 'scenario_count': 3},
        'current_route': {'queue_id': 'ops-a', 'queue_label': 'Ops A', 'selection_reason': 'existing_route'},
        'current_policy': {
            'scenario_id': 'current_policy',
            'scenario_label': 'Current policy',
            'route': {'queue_id': 'ops-a', 'queue_label': 'Ops A', 'selection_reason': 'family_hysteresis_keep_current_queue'},
            'explainability': {'kept_current_queue': True, 'why_kept_current_queue': 'family_hysteresis', 'selection_reason': 'family_hysteresis_keep_current_queue'},
        },
        'scenarios': [
            {
                'scenario_id': 'current_policy',
                'scenario_label': 'Current policy',
                'route': {'queue_id': 'ops-a', 'queue_label': 'Ops A', 'selection_reason': 'family_hysteresis_keep_current_queue'},
                'explainability': {'kept_current_queue': True, 'why_kept_current_queue': 'family_hysteresis'},
            },
            {
                'scenario_id': 'disable_family_hysteresis',
                'scenario_label': 'Disable family hysteresis',
                'policy_delta_keys': ['queue_capacity_policy.multi_hop_hysteresis_enabled'],
                'route': {'queue_id': 'ops-b', 'queue_label': 'Ops B', 'selection_reason': 'load_aware_queue'},
                'explainability': {'queue_changed': True, 'selection_reason': 'load_aware_queue'},
            },
        ],
    })
    assert replay['alert_id'] == 'alert-1'
    assert replay['applied_pack']['pack_id'] == 'family_hysteresis_presets'
    assert replay['current_policy']['explainability']['why_kept_current_queue'] == 'family_hysteresis'
    assert replay['scenario_count'] == 2
    assert replay['scenarios'][1]['route']['queue_id'] == 'ops-b'


def test_canvas_cross_promotion_routing_policy_pack_catalog_and_scoped_governance(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_791_300.0
    _set_now(monkeypatch, base_now)
    monkeypatch.setenv('OPENMIURA_BASELINE_ESCROW_ROOT', str(tmp_path / 'escrow'))
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='baseline-routing-catalog-cross-promotion',
            version='catalog-v1',
            environment_policy_baselines={'prod': _env_policy('baseline-v1')},
            promotion_policy={
                'simulation_custody_monitoring_policy': {
                    'enabled': True,
                    'auto_schedule': True,
                    'interval_s': 300,
                    'notify_on_drift': True,
                    'block_on_drift': True,
                    'load_aware_routing_enabled': True,
                    'queue_capacity_policy': {
                        'enabled': True,
                        'default_capacity': 2,
                        'prefer_lowest_load': True,
                        'queue_families_enabled': True,
                        'default_queue_family': 'ops',
                        'multi_hop_hysteresis_enabled': True,
                        'breach_prediction_enabled': True,
                        'expedite_enabled': True,
                        'admission_control_enabled': True,
                        'overload_governance_enabled': True,
                    },
                    'routing_routes': [
                        {'route_id': 'ops-a-route', 'label': 'Ops A', 'queue_id': 'ops-a', 'queue_label': 'Ops A', 'queue_family_id': 'ops', 'owner_role': 'shift-lead', 'queue_capacity': 2, 'severity': 'warning'},
                        {'route_id': 'ops-b-route', 'label': 'Ops B', 'queue_id': 'ops-b', 'queue_label': 'Ops B', 'queue_family_id': 'ops', 'owner_role': 'shift-lead', 'queue_capacity': 2, 'severity': 'warning'},
                    ],
                    'default_route': {'route_id': 'ops-a-route', 'label': 'Ops A', 'queue_id': 'ops-a', 'queue_label': 'Ops A', 'queue_family_id': 'ops', 'owner_role': 'shift-lead', 'queue_capacity': 2},
                    'queue_capacities': [
                        {'queue_id': 'ops-a', 'queue_label': 'Ops A', 'capacity': 2, 'queue_family_id': 'ops'},
                        {'queue_id': 'ops-b', 'queue_label': 'Ops B', 'capacity': 2, 'queue_family_id': 'ops'},
                    ],
                },
            },
        )
        runtime_id = _create_runtime_for_environment(client, headers, name='runtime-routing-pack-catalog', environment='prod')
        _create_portfolio_with_catalog(client, headers, base_now=base_now + 1, runtime_id=runtime_id, environment='prod', environment_tier_policies=_env_policy('baseline-v2'), baseline_catalog_ref={'catalog_id': catalog['catalog_id']})

        promotion_a = client.post(
            f'/admin/openclaw/alert-governance/baseline-catalogs/{catalog["catalog_id"]}/promotions',
            headers=headers,
            json={'actor': 'catalog-admin', 'version': 'catalog-v2', 'environment_policy_baselines': {'prod': {'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'catalog-v2'}, 'escrow_policy': {'enabled': True, 'provider': 'filesystem-object-lock', 'classification': 'baseline-evidence'}}}, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert promotion_a.status_code == 200, promotion_a.text
        promotion_a_id = promotion_a.json()['promotion_id']

        promotion_b = client.post(
            f'/admin/openclaw/alert-governance/baseline-catalogs/{catalog["catalog_id"]}/promotions',
            headers=headers,
            json={'actor': 'catalog-admin', 'version': 'catalog-v3', 'environment_policy_baselines': {'prod': {'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'catalog-v3'}, 'escrow_policy': {'enabled': True, 'provider': 'filesystem-object-lock', 'classification': 'baseline-evidence'}}}, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert promotion_b.status_code == 200, promotion_b.text
        promotion_b_id = promotion_b.json()['promotion_id']

        canvas_a = client.post('/admin/canvas/documents', headers=headers, json={'actor': 'operator-a', 'title': 'catalog source canvas', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'})
        canvas_a_id = canvas_a.json()['document']['canvas_id']
        node_a = client.post(f'/admin/canvas/documents/{canvas_a_id}/nodes', headers=headers, json={'actor': 'operator-a', 'node_type': 'baseline_promotion', 'label': promotion_a_id, 'data': {'promotion_id': promotion_a_id}, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'})
        node_a_id = node_a.json()['node']['node_id']
        assert client.post(f'/admin/canvas/documents/{canvas_a_id}/nodes/{node_a_id}/actions/simulate?tenant_id=tenant-a&workspace_id=ws-a&environment=prod', headers=headers, json={'actor': 'operator-a'}).status_code == 200
        save_pack = client.post(f'/admin/canvas/documents/{canvas_a_id}/nodes/{node_a_id}/actions/save_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod', headers=headers, json={'actor': 'operator-a', 'preset_pack_id': 'family_hysteresis_presets'})
        assert save_pack.status_code == 200, save_pack.text
        promote_catalog = client.post(
            f'/admin/canvas/documents/{canvas_a_id}/nodes/{node_a_id}/actions/promote_simulation_custody_routing_policy_pack_to_catalog?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator-a', 'pack_id': 'family_hysteresis_presets', 'catalog_scope': 'workspace'},
        )
        assert promote_catalog.status_code == 200, promote_catalog.text
        assert promote_catalog.json()['result']['policy_pack']['catalog_scope'] == 'workspace'

        canvas_b = client.post('/admin/canvas/documents', headers=headers, json={'actor': 'operator-b', 'title': 'catalog target canvas', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'})
        canvas_b_id = canvas_b.json()['document']['canvas_id']
        node_b = client.post(f'/admin/canvas/documents/{canvas_b_id}/nodes', headers=headers, json={'actor': 'operator-b', 'node_type': 'baseline_promotion', 'label': promotion_b_id, 'data': {'promotion_id': promotion_b_id}, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'})
        node_b_id = node_b.json()['node']['node_id']
        assert client.post(f'/admin/canvas/documents/{canvas_b_id}/nodes/{node_b_id}/actions/simulate?tenant_id=tenant-a&workspace_id=ws-a&environment=prod', headers=headers, json={'actor': 'operator-b'}).status_code == 200
        export_pkg = client.post(f'/admin/canvas/documents/{canvas_b_id}/nodes/{node_b_id}/actions/export_simulation_evidence_package?tenant_id=tenant-a&workspace_id=ws-a&environment=prod', headers=headers, json={'actor': 'auditor'})
        assert export_pkg.status_code == 200, export_pkg.text
        lock_path = (export_pkg.json()['result']['latest_simulation']['export_state']['latest_evidence_package'] or {}).get('escrow', {}).get('lock_path') or export_pkg.json()['result']['escrow']['lock_path']
        Path(lock_path).unlink()
        assert client.post(f'/admin/canvas/documents/{canvas_b_id}/nodes/{node_b_id}/actions/reconcile_simulation_evidence_custody?tenant_id=tenant-a&workspace_id=ws-a&environment=prod', headers=headers, json={'actor': 'monitor-bot'}).status_code == 200

        inspector = client.get(f'/admin/canvas/documents/{canvas_b_id}/nodes/{node_b_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod', headers=headers)
        inspector_payload = inspector.json()
        assert 'promote_simulation_custody_routing_policy_pack_to_catalog' in inspector_payload['available_actions']
        assert 'replay_cataloged_simulation_custody_routing_policy_pack' in inspector_payload['available_actions']
        assert 'share_cataloged_simulation_custody_routing_policy_pack' in inspector_payload['available_actions']
        assert inspector_payload['node']['data']['routing_policy_pack_catalog_summary']['workspace_scope_count'] >= 1
        assert any(item['pack_id'] == 'family_hysteresis_presets' for item in inspector_payload['node']['data']['routing_policy_pack_catalog'])

        replay = client.post(
            f'/admin/canvas/documents/{canvas_b_id}/nodes/{node_b_id}/actions/replay_cataloged_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={
                'actor': 'operator-b',
                'pack_id': 'family_hysteresis_presets',
                'alert_overrides': {'routing': {'queue_id': 'ops-a', 'queue_label': 'Ops A', 'queue_family_id': 'ops', 'selection_reason': 'manual_override'}},
            },
        )
        assert replay.status_code == 200, replay.text
        assert replay.json()['result']['routing_replay']['applied_pack']['catalog_scope'] == 'workspace'

        share = client.post(
            f'/admin/canvas/documents/{canvas_b_id}/nodes/{node_b_id}/actions/share_cataloged_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator-b', 'pack_id': 'family_hysteresis_presets', 'target_pack_id': 'family_hysteresis_presets_catalog_shared'},
        )
        assert share.status_code == 200, share.text

        detail = client.get(f'/admin/canvas/documents/{canvas_b_id}?tenant_id=tenant-a&workspace_id=ws-a&environment=prod', headers=headers)
        node_payload = next(item for item in detail.json()['nodes'] if item['node_id'] == node_b_id)['data']
        assert node_payload['last_shared_catalog_routing_policy_pack']['source'] == 'shared_catalog'
        assert node_payload['last_shared_catalog_routing_policy_pack']['catalog_entry_id']


def test_canvas_global_versioned_routing_policy_pack_catalog_lifecycle(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_791_700.0
    _set_now(monkeypatch, base_now)
    monkeypatch.setenv('OPENMIURA_BASELINE_ESCROW_ROOT', str(tmp_path / 'escrow'))
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='baseline-routing-catalog-global-lifecycle',
            version='catalog-v1',
            environment_policy_baselines={'prod': _env_policy('baseline-v1')},
            promotion_policy={
                'simulation_custody_monitoring_policy': {
                    'enabled': True,
                    'auto_schedule': True,
                    'interval_s': 300,
                    'notify_on_drift': True,
                    'block_on_drift': True,
                    'load_aware_routing_enabled': True,
                    'queue_capacity_policy': {
                        'enabled': True,
                        'default_capacity': 2,
                        'prefer_lowest_load': True,
                        'queue_families_enabled': True,
                        'default_queue_family': 'ops',
                        'multi_hop_hysteresis_enabled': True,
                        'breach_prediction_enabled': True,
                        'expedite_enabled': True,
                        'admission_control_enabled': True,
                        'overload_governance_enabled': True,
                    },
                    'routing_routes': [
                        {'route_id': 'ops-a-route', 'label': 'Ops A', 'queue_id': 'ops-a', 'queue_label': 'Ops A', 'queue_family_id': 'ops', 'owner_role': 'shift-lead', 'queue_capacity': 2, 'severity': 'warning'},
                        {'route_id': 'ops-b-route', 'label': 'Ops B', 'queue_id': 'ops-b', 'queue_label': 'Ops B', 'queue_family_id': 'ops', 'owner_role': 'shift-lead', 'queue_capacity': 2, 'severity': 'warning'},
                    ],
                    'default_route': {'route_id': 'ops-a-route', 'label': 'Ops A', 'queue_id': 'ops-a', 'queue_label': 'Ops A', 'queue_family_id': 'ops', 'owner_role': 'shift-lead', 'queue_capacity': 2},
                    'queue_capacities': [
                        {'queue_id': 'ops-a', 'queue_label': 'Ops A', 'capacity': 2, 'queue_family_id': 'ops'},
                        {'queue_id': 'ops-b', 'queue_label': 'Ops B', 'capacity': 2, 'queue_family_id': 'ops'},
                    ],
                },
            },
        )
        runtime_id = _create_runtime_for_environment(client, headers, name='runtime-routing-pack-global-lifecycle', environment='prod')
        _create_portfolio_with_catalog(client, headers, base_now=base_now + 1, runtime_id=runtime_id, environment='prod', environment_tier_policies=_env_policy('baseline-v2'), baseline_catalog_ref={'catalog_id': catalog['catalog_id']})

        promotion_a = client.post(
            f'/admin/openclaw/alert-governance/baseline-catalogs/{catalog["catalog_id"]}/promotions',
            headers=headers,
            json={'actor': 'catalog-admin', 'version': 'catalog-v2', 'environment_policy_baselines': {'prod': {'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'catalog-v2'}, 'escrow_policy': {'enabled': True, 'provider': 'filesystem-object-lock', 'classification': 'baseline-evidence'}}}, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert promotion_a.status_code == 200, promotion_a.text
        promotion_a_id = promotion_a.json()['promotion_id']

        promotion_b = client.post(
            f'/admin/openclaw/alert-governance/baseline-catalogs/{catalog["catalog_id"]}/promotions',
            headers=headers,
            json={'actor': 'catalog-admin', 'version': 'catalog-v3', 'environment_policy_baselines': {'prod': {'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'catalog-v3'}, 'escrow_policy': {'enabled': True, 'provider': 'filesystem-object-lock', 'classification': 'baseline-evidence'}}}, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert promotion_b.status_code == 200, promotion_b.text
        promotion_b_id = promotion_b.json()['promotion_id']

        canvas_a = client.post('/admin/canvas/documents', headers=headers, json={'actor': 'operator-a', 'title': 'global catalog source canvas', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'})
        canvas_a_id = canvas_a.json()['document']['canvas_id']
        node_a = client.post(f'/admin/canvas/documents/{canvas_a_id}/nodes', headers=headers, json={'actor': 'operator-a', 'node_type': 'baseline_promotion', 'label': promotion_a_id, 'data': {'promotion_id': promotion_a_id}, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'})
        node_a_id = node_a.json()['node']['node_id']
        assert client.post(f'/admin/canvas/documents/{canvas_a_id}/nodes/{node_a_id}/actions/simulate?tenant_id=tenant-a&workspace_id=ws-a&environment=prod', headers=headers, json={'actor': 'operator-a'}).status_code == 200
        save_pack = client.post(f'/admin/canvas/documents/{canvas_a_id}/nodes/{node_a_id}/actions/save_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod', headers=headers, json={'actor': 'operator-a', 'preset_pack_id': 'family_hysteresis_presets'})
        assert save_pack.status_code == 200, save_pack.text
        promote_v1 = client.post(
            f'/admin/canvas/documents/{canvas_a_id}/nodes/{node_a_id}/actions/promote_simulation_custody_routing_policy_pack_to_catalog?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator-a', 'pack_id': 'family_hysteresis_presets', 'catalog_scope': 'global', 'catalog_version': 1},
        )
        assert promote_v1.status_code == 200, promote_v1.text
        entry_v1 = promote_v1.json()['result']['policy_pack']['catalog_entry_id']
        assert promote_v1.json()['result']['policy_pack']['catalog_version'] == 1
        assert promote_v1.json()['result']['policy_pack']['catalog_lifecycle_state'] == 'draft'

        curate_v1 = client.post(
            f'/admin/canvas/documents/{canvas_a_id}/nodes/{node_a_id}/actions/curate_cataloged_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'curator-a', 'catalog_entry_id': entry_v1},
        )
        assert curate_v1.status_code == 200, curate_v1.text
        assert curate_v1.json()['result']['policy_pack']['catalog_lifecycle_state'] == 'curated'

        approve_v1 = client.post(
            f'/admin/canvas/documents/{canvas_a_id}/nodes/{node_a_id}/actions/approve_cataloged_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'approver-a', 'catalog_entry_id': entry_v1},
        )
        assert approve_v1.status_code == 200, approve_v1.text
        assert approve_v1.json()['result']['policy_pack']['catalog_lifecycle_state'] == 'approved'

        promote_v2 = client.post(
            f'/admin/canvas/documents/{canvas_a_id}/nodes/{node_a_id}/actions/promote_simulation_custody_routing_policy_pack_to_catalog?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator-a', 'pack_id': 'family_hysteresis_presets', 'catalog_scope': 'global', 'catalog_version': 2},
        )
        assert promote_v2.status_code == 200, promote_v2.text
        entry_v2 = promote_v2.json()['result']['policy_pack']['catalog_entry_id']
        approve_v2 = client.post(
            f'/admin/canvas/documents/{canvas_a_id}/nodes/{node_a_id}/actions/approve_cataloged_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'approver-a', 'catalog_entry_id': entry_v2},
        )
        assert approve_v2.status_code == 200, approve_v2.text
        assert approve_v2.json()['result']['policy_pack']['catalog_version'] == 2
        assert approve_v2.json()['result']['policy_pack']['catalog_lifecycle_state'] == 'approved'

        canvas_b = client.post('/admin/canvas/documents', headers=headers, json={'actor': 'operator-b', 'title': 'global catalog target canvas', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'})
        canvas_b_id = canvas_b.json()['document']['canvas_id']
        node_b = client.post(f'/admin/canvas/documents/{canvas_b_id}/nodes', headers=headers, json={'actor': 'operator-b', 'node_type': 'baseline_promotion', 'label': promotion_b_id, 'data': {'promotion_id': promotion_b_id}, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'})
        node_b_id = node_b.json()['node']['node_id']
        assert client.post(f'/admin/canvas/documents/{canvas_b_id}/nodes/{node_b_id}/actions/simulate?tenant_id=tenant-a&workspace_id=ws-a&environment=prod', headers=headers, json={'actor': 'operator-b'}).status_code == 200

        inspector = client.get(f'/admin/canvas/documents/{canvas_b_id}/nodes/{node_b_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod', headers=headers)
        inspector_payload = inspector.json()
        assert 'approve_cataloged_simulation_custody_routing_policy_pack' in inspector_payload['available_actions']
        assert inspector_payload['node']['data']['routing_policy_pack_catalog_summary']['global_scope_count'] >= 1
        assert inspector_payload['node']['data']['routing_policy_pack_catalog_summary']['approved_count'] >= 1
        assert inspector_payload['node']['data']['routing_policy_pack_catalog_summary']['deprecated_count'] >= 1

        replay_latest = client.post(
            f'/admin/canvas/documents/{canvas_b_id}/nodes/{node_b_id}/actions/replay_cataloged_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator-b', 'pack_id': 'family_hysteresis_presets', 'alert_overrides': {'routing': {'queue_id': 'ops-a', 'queue_label': 'Ops A', 'queue_family_id': 'ops', 'selection_reason': 'manual_override'}}},
        )
        assert replay_latest.status_code == 200, replay_latest.text
        assert replay_latest.json()['result']['routing_replay']['applied_pack']['catalog_scope'] == 'global'
        assert replay_latest.json()['result']['routing_replay']['applied_pack']['catalog_version'] == 2
        assert replay_latest.json()['result']['routing_replay']['applied_pack']['catalog_lifecycle_state'] == 'approved'

        replay_old = client.post(
            f'/admin/canvas/documents/{canvas_b_id}/nodes/{node_b_id}/actions/replay_cataloged_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator-b', 'catalog_entry_id': entry_v1},
        )
        assert replay_old.status_code == 200, replay_old.text
        assert replay_old.json()['result']['error'] == 'baseline_promotion_simulation_custody_policy_pack_deprecated'

        share_latest = client.post(
            f'/admin/canvas/documents/{canvas_b_id}/nodes/{node_b_id}/actions/share_cataloged_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator-b', 'catalog_entry_id': entry_v2, 'target_pack_id': 'family_hysteresis_presets_global_shared'},
        )
        assert share_latest.status_code == 200, share_latest.text
        assert share_latest.json()['result']['policy_pack']['source'] == 'shared_catalog'



def test_canvas_cataloged_routing_policy_pack_approvals_attestation_and_release_governance(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_792_200.0
    _set_now(monkeypatch, base_now)
    monkeypatch.setenv('OPENMIURA_BASELINE_ESCROW_ROOT', str(tmp_path / 'escrow'))
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='baseline-routing-catalog-approval-release',
            version='catalog-v1',
            environment_policy_baselines={'prod': _env_policy('baseline-v1')},
            promotion_policy={
                'simulation_custody_monitoring_policy': {
                    'enabled': True,
                    'auto_schedule': True,
                    'interval_s': 300,
                    'queue_capacity_policy': {
                        'enabled': True,
                        'default_capacity': 2,
                        'queue_families_enabled': True,
                        'default_queue_family': 'ops',
                        'multi_hop_hysteresis_enabled': True,
                        'breach_prediction_enabled': True,
                        'expedite_enabled': True,
                        'admission_control_enabled': True,
                        'overload_governance_enabled': True,
                    },
                    'routing_routes': [
                        {'route_id': 'ops-a-route', 'label': 'Ops A', 'queue_id': 'ops-a', 'queue_label': 'Ops A', 'queue_family_id': 'ops', 'owner_role': 'shift-lead', 'queue_capacity': 2, 'severity': 'warning'},
                        {'route_id': 'ops-b-route', 'label': 'Ops B', 'queue_id': 'ops-b', 'queue_label': 'Ops B', 'queue_family_id': 'ops', 'owner_role': 'shift-lead', 'queue_capacity': 2, 'severity': 'warning'},
                    ],
                    'default_route': {'route_id': 'ops-a-route', 'label': 'Ops A', 'queue_id': 'ops-a', 'queue_label': 'Ops A', 'queue_family_id': 'ops', 'owner_role': 'shift-lead', 'queue_capacity': 2},
                    'queue_capacities': [
                        {'queue_id': 'ops-a', 'queue_label': 'Ops A', 'capacity': 2, 'queue_family_id': 'ops'},
                        {'queue_id': 'ops-b', 'queue_label': 'Ops B', 'capacity': 2, 'queue_family_id': 'ops'},
                    ],
                },
            },
        )
        runtime_id = _create_runtime_for_environment(client, headers, name='runtime-routing-pack-approval-release', environment='prod')
        _create_portfolio_with_catalog(client, headers, base_now=base_now + 1, runtime_id=runtime_id, environment='prod', environment_tier_policies=_env_policy('baseline-v2'), baseline_catalog_ref={'catalog_id': catalog['catalog_id']})
        promotion = client.post(
            f'/admin/openclaw/alert-governance/baseline-catalogs/{catalog["catalog_id"]}/promotions',
            headers=headers,
            json={'actor': 'catalog-admin', 'version': 'catalog-v2', 'environment_policy_baselines': {'prod': {'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'catalog-v2'}, 'escrow_policy': {'enabled': True, 'provider': 'filesystem-object-lock', 'classification': 'baseline-evidence'}}}, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert promotion.status_code == 200, promotion.text
        promotion_id = promotion.json()['promotion_id']

        canvas = client.post('/admin/canvas/documents', headers=headers, json={'actor': 'operator-a', 'title': 'catalog governance canvas', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'})
        canvas_id = canvas.json()['document']['canvas_id']
        node = client.post(f'/admin/canvas/documents/{canvas_id}/nodes', headers=headers, json={'actor': 'operator-a', 'node_type': 'baseline_promotion', 'label': promotion_id, 'data': {'promotion_id': promotion_id}, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'})
        node_id = node.json()['node']['node_id']
        assert client.post(f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/simulate?tenant_id=tenant-a&workspace_id=ws-a&environment=prod', headers=headers, json={'actor': 'operator-a'}).status_code == 200
        save_pack = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/save_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator-a', 'preset_pack_id': 'family_hysteresis_presets'},
        )
        assert save_pack.status_code == 200, save_pack.text
        promote = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/promote_simulation_custody_routing_policy_pack_to_catalog?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator-a', 'pack_id': 'family_hysteresis_presets', 'catalog_scope': 'global', 'catalog_version': 1, 'catalog_approval_required': True, 'catalog_required_approvals': 2},
        )
        assert promote.status_code == 200, promote.text
        entry_id = promote.json()['result']['policy_pack']['catalog_entry_id']

        inspector = client.get(f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod', headers=headers)
        inspector_payload = inspector.json()
        assert 'request_cataloged_simulation_custody_routing_policy_pack_approval' in inspector_payload['available_actions']
        assert 'export_cataloged_simulation_custody_routing_policy_pack_attestation' in inspector_payload['available_actions']
        assert 'release_cataloged_simulation_custody_routing_policy_pack' in inspector_payload['available_actions']

        request_approval = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/request_cataloged_simulation_custody_routing_policy_pack_approval?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'ops-lead', 'catalog_entry_id': entry_id, 'catalog_required_approvals': 2, 'note': 'needs governance + security'},
        )
        assert request_approval.status_code == 200, request_approval.text
        assert request_approval.json()['result']['policy_pack']['catalog_approval_state'] == 'pending'

        approve_one = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/approve_cataloged_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'approver-a', 'catalog_entry_id': entry_id, 'role': 'governance'},
        )
        assert approve_one.status_code == 200, approve_one.text
        assert approve_one.json()['result']['policy_pack']['catalog_approval_state'] == 'pending'
        assert approve_one.json()['result']['policy_pack']['catalog_approval_count'] == 1

        stage_blocked = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/stage_cataloged_simulation_custody_routing_policy_pack_release?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'release-manager', 'catalog_entry_id': entry_id},
        )
        assert stage_blocked.status_code == 200, stage_blocked.text
        assert stage_blocked.json()['result']['error'] == 'baseline_promotion_simulation_custody_policy_pack_release_not_ready'

        approve_two = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/approve_cataloged_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'approver-b', 'catalog_entry_id': entry_id, 'role': 'security'},
        )
        assert approve_two.status_code == 200, approve_two.text
        approved_pack = approve_two.json()['result']['policy_pack']
        assert approved_pack['catalog_approval_state'] == 'approved'
        assert approved_pack['catalog_approval_count'] == 2
        assert approved_pack['catalog_lifecycle_state'] == 'approved'

        export_attestation = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/export_cataloged_simulation_custody_routing_policy_pack_attestation?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'auditor-a', 'catalog_entry_id': entry_id},
        )
        assert export_attestation.status_code == 200, export_attestation.text
        attestation_payload = export_attestation.json()['result']
        assert attestation_payload['report']['report_type'] == 'openmiura_routing_policy_pack_catalog_attestation_v1'
        assert attestation_payload['integrity']['signed'] is True

        stage_release = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/stage_cataloged_simulation_custody_routing_policy_pack_release?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'release-manager', 'catalog_entry_id': entry_id, 'catalog_release_train_id': 'train-1', 'catalog_release_notes': 'stage for production'},
        )
        assert stage_release.status_code == 200, stage_release.text
        assert stage_release.json()['result']['policy_pack']['catalog_release_state'] == 'staged'

        release_pack = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/release_cataloged_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'release-manager', 'catalog_entry_id': entry_id, 'catalog_release_notes': 'release globally'},
        )
        assert release_pack.status_code == 200, release_pack.text
        assert release_pack.json()['result']['policy_pack']['catalog_release_state'] == 'released'

        inspector_after = client.get(f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod', headers=headers)
        inspector_after_payload = inspector_after.json()
        summary = inspector_after_payload['node']['data']['routing_policy_pack_catalog_summary']
        assert summary['approval_approved_count'] >= 1
        assert summary['released_count'] >= 1
        assert summary['attested_count'] >= 1
        node_data = inspector_after_payload['node']['data']
        assert node_data['last_catalog_release_transition_routing_policy_pack']['catalog_release_state'] == 'released'
        assert node_data['last_catalog_attestation_routing_policy_pack']['report_type'] == 'openmiura_routing_policy_pack_catalog_attestation_v1'


def test_canvas_cataloged_routing_policy_pack_review_workflow_evidence_and_signed_release_bundle(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_792_600.0
    _set_now(monkeypatch, base_now)
    monkeypatch.setenv('OPENMIURA_BASELINE_ESCROW_ROOT', str(tmp_path / 'escrow'))
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='baseline-routing-catalog-review-bundles',
            version='catalog-v1',
            environment_policy_baselines={'prod': _env_policy('baseline-v1')},
            promotion_policy={
                'simulation_custody_monitoring_policy': {
                    'enabled': True,
                    'auto_schedule': True,
                    'interval_s': 300,
                    'queue_capacity_policy': {
                        'enabled': True,
                        'default_capacity': 2,
                        'queue_families_enabled': True,
                        'default_queue_family': 'ops',
                        'multi_hop_hysteresis_enabled': True,
                        'breach_prediction_enabled': True,
                        'expedite_enabled': True,
                        'admission_control_enabled': True,
                        'overload_governance_enabled': True,
                    },
                    'routing_routes': [
                        {'route_id': 'ops-a-route', 'label': 'Ops A', 'queue_id': 'ops-a', 'queue_label': 'Ops A', 'queue_family_id': 'ops', 'owner_role': 'shift-lead', 'queue_capacity': 2, 'severity': 'warning'},
                        {'route_id': 'ops-b-route', 'label': 'Ops B', 'queue_id': 'ops-b', 'queue_label': 'Ops B', 'queue_family_id': 'ops', 'owner_role': 'shift-lead', 'queue_capacity': 2, 'severity': 'warning'},
                    ],
                    'default_route': {'route_id': 'ops-a-route', 'label': 'Ops A', 'queue_id': 'ops-a', 'queue_label': 'Ops A', 'queue_family_id': 'ops', 'owner_role': 'shift-lead', 'queue_capacity': 2},
                    'queue_capacities': [
                        {'queue_id': 'ops-a', 'queue_label': 'Ops A', 'capacity': 2, 'queue_family_id': 'ops'},
                        {'queue_id': 'ops-b', 'queue_label': 'Ops B', 'capacity': 2, 'queue_family_id': 'ops'},
                    ],
                },
            },
        )
        runtime_id = _create_runtime_for_environment(client, headers, name='runtime-routing-pack-review-bundles', environment='prod')
        _create_portfolio_with_catalog(client, headers, base_now=base_now + 1, runtime_id=runtime_id, environment='prod', environment_tier_policies=_env_policy('baseline-v2'), baseline_catalog_ref={'catalog_id': catalog['catalog_id']})
        promotion = client.post(
            f'/admin/openclaw/alert-governance/baseline-catalogs/{catalog["catalog_id"]}/promotions',
            headers=headers,
            json={'actor': 'catalog-admin', 'version': 'catalog-v2', 'environment_policy_baselines': {'prod': {'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'catalog-v2'}, 'escrow_policy': {'enabled': True, 'provider': 'filesystem-object-lock', 'classification': 'baseline-evidence'}}}, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert promotion.status_code == 200, promotion.text
        promotion_id = promotion.json()['promotion_id']

        canvas = client.post('/admin/canvas/documents', headers=headers, json={'actor': 'operator-a', 'title': 'catalog review workflow canvas', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'})
        canvas_id = canvas.json()['document']['canvas_id']
        node = client.post(f'/admin/canvas/documents/{canvas_id}/nodes', headers=headers, json={'actor': 'operator-a', 'node_type': 'baseline_promotion', 'label': promotion_id, 'data': {'promotion_id': promotion_id}, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'})
        node_id = node.json()['node']['node_id']
        assert client.post(f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/simulate?tenant_id=tenant-a&workspace_id=ws-a&environment=prod', headers=headers, json={'actor': 'operator-a'}).status_code == 200
        assert client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/save_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator-a', 'preset_pack_id': 'family_hysteresis_presets'},
        ).status_code == 200
        promote = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/promote_simulation_custody_routing_policy_pack_to_catalog?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator-a', 'pack_id': 'family_hysteresis_presets', 'catalog_scope': 'global', 'catalog_version': 1, 'catalog_approval_required': True, 'catalog_required_approvals': 2},
        )
        assert promote.status_code == 200, promote.text
        entry_id = promote.json()['result']['policy_pack']['catalog_entry_id']

        inspector_before = client.get(f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod', headers=headers)
        inspector_before_payload = inspector_before.json()
        assert 'request_cataloged_simulation_custody_routing_policy_pack_review' in inspector_before_payload['available_actions']
        assert 'export_cataloged_simulation_custody_routing_policy_pack_evidence_package' in inspector_before_payload['available_actions']
        assert 'export_cataloged_simulation_custody_routing_policy_pack_signed_release_bundle' in inspector_before_payload['available_actions']

        request_review = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/request_cataloged_simulation_custody_routing_policy_pack_review?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'ops-lead', 'catalog_entry_id': entry_id, 'assigned_reviewer': 'reviewer-a', 'assigned_role': 'qa', 'note': 'initial QA review'},
        )
        assert request_review.status_code == 200, request_review.text
        assert request_review.json()['result']['policy_pack']['catalog_review_state'] == 'pending_review'

        claim_review = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/claim_cataloged_simulation_custody_routing_policy_pack_review?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'reviewer-a', 'catalog_entry_id': entry_id, 'role': 'qa'},
        )
        assert claim_review.status_code == 200, claim_review.text
        assert claim_review.json()['result']['policy_pack']['catalog_review_state'] == 'in_review'
        assert claim_review.json()['result']['policy_pack']['catalog_review_claimed_by'] == 'reviewer-a'

        add_note = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/add_cataloged_simulation_custody_routing_policy_pack_review_note?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'reviewer-a', 'catalog_entry_id': entry_id, 'review_note': 'needs tighter hysteresis thresholds'},
        )
        assert add_note.status_code == 200, add_note.text
        assert add_note.json()['result']['policy_pack']['catalog_review_note_count'] >= 1

        changes_requested = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/submit_cataloged_simulation_custody_routing_policy_pack_review_decision?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'reviewer-a', 'catalog_entry_id': entry_id, 'decision': 'changes_requested', 'review_note': 'revise thresholds before release'},
        )
        assert changes_requested.status_code == 200, changes_requested.text
        assert changes_requested.json()['result']['policy_pack']['catalog_review_state'] == 'review_changes_requested'

        request_approval = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/request_cataloged_simulation_custody_routing_policy_pack_approval?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'ops-lead', 'catalog_entry_id': entry_id, 'catalog_required_approvals': 2, 'note': 'needs governance + security'},
        )
        assert request_approval.status_code == 200, request_approval.text
        approve_one = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/approve_cataloged_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'approver-a', 'catalog_entry_id': entry_id, 'role': 'governance'},
        )
        assert approve_one.status_code == 200, approve_one.text
        approve_two = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/approve_cataloged_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'approver-b', 'catalog_entry_id': entry_id, 'role': 'security'},
        )
        assert approve_two.status_code == 200, approve_two.text
        assert approve_two.json()['result']['policy_pack']['catalog_lifecycle_state'] == 'approved'

        stage_blocked = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/stage_cataloged_simulation_custody_routing_policy_pack_release?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'release-manager', 'catalog_entry_id': entry_id},
        )
        assert stage_blocked.status_code == 200, stage_blocked.text
        assert stage_blocked.json()['result']['error'] == 'baseline_promotion_simulation_custody_policy_pack_release_not_ready'

        request_review_again = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/request_cataloged_simulation_custody_routing_policy_pack_review?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'ops-lead', 'catalog_entry_id': entry_id, 'assigned_reviewer': 'reviewer-b', 'assigned_role': 'qa', 'note': 'thresholds updated, re-review'},
        )
        assert request_review_again.status_code == 200, request_review_again.text
        assert request_review_again.json()['result']['policy_pack']['catalog_review_state'] == 'pending_review'

        claim_review_again = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/claim_cataloged_simulation_custody_routing_policy_pack_review?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'reviewer-b', 'catalog_entry_id': entry_id, 'role': 'qa'},
        )
        assert claim_review_again.status_code == 200, claim_review_again.text

        approve_review = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/submit_cataloged_simulation_custody_routing_policy_pack_review_decision?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'reviewer-b', 'catalog_entry_id': entry_id, 'decision': 'approved', 'review_note': 'approved after threshold adjustment'},
        )
        assert approve_review.status_code == 200, approve_review.text
        approved_review_pack = approve_review.json()['result']['policy_pack']
        assert approved_review_pack['catalog_review_state'] == 'review_approved'
        assert approved_review_pack['catalog_review_decision'] == 'review_approved'

        export_evidence = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/export_cataloged_simulation_custody_routing_policy_pack_evidence_package?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'auditor-a', 'catalog_entry_id': entry_id},
        )
        assert export_evidence.status_code == 200, export_evidence.text
        evidence_payload = export_evidence.json()['result']
        assert evidence_payload['report']['report_type'] == 'openmiura_routing_policy_pack_catalog_evidence_package_v1'
        assert evidence_payload['report']['governance']['review_state'] == 'review_approved'
        assert evidence_payload['report']['attestation_linkage']['report_type'] == 'openmiura_routing_policy_pack_catalog_attestation_v1'

        stage_release = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/stage_cataloged_simulation_custody_routing_policy_pack_release?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'release-manager', 'catalog_entry_id': entry_id, 'catalog_release_train_id': 'train-review-1', 'catalog_release_notes': 'stage for production'},
        )
        assert stage_release.status_code == 200, stage_release.text
        assert stage_release.json()['result']['policy_pack']['catalog_release_state'] == 'staged'

        release_pack = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/release_cataloged_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'release-manager', 'catalog_entry_id': entry_id, 'catalog_release_notes': 'release globally'},
        )
        assert release_pack.status_code == 200, release_pack.text
        assert release_pack.json()['result']['policy_pack']['catalog_release_state'] == 'released'

        export_bundle = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/export_cataloged_simulation_custody_routing_policy_pack_signed_release_bundle?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'release-manager', 'catalog_entry_id': entry_id},
        )
        assert export_bundle.status_code == 200, export_bundle.text
        bundle_payload = export_bundle.json()['result']
        assert bundle_payload['report']['report_type'] == 'openmiura_routing_policy_pack_signed_release_bundle_v1'
        assert bundle_payload['report']['release_bundle_id']
        assert bundle_payload['integrity']['signed'] is True

        inspector_after = client.get(f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod', headers=headers)
        inspector_after_payload = inspector_after.json()
        node_data = inspector_after_payload['node']['data']
        summary = node_data['routing_policy_pack_catalog_summary']
        assert summary['review_approved_count'] >= 1
        assert summary['evidence_packaged_count'] >= 1
        assert summary['signed_bundle_count'] >= 1
        pack = next(item for item in node_data['routing_policy_pack_catalog'] if item['catalog_entry_id'] == entry_id)
        assert pack['catalog_review_state'] == 'review_approved'
        assert pack['catalog_review_assigned_reviewer'] == 'reviewer-b'
        assert pack['catalog_review_claimed_by'] == 'reviewer-b'
        assert pack['catalog_review_timeline']
        assert any(item['state'] == 'review_changes_requested' for item in pack['catalog_review_timeline'])
        assert pack['catalog_latest_evidence_package']['report_type'] == 'openmiura_routing_policy_pack_catalog_evidence_package_v1'
        assert pack['catalog_latest_release_bundle']['report_type'] == 'openmiura_routing_policy_pack_signed_release_bundle_v1'
        assert node_data['last_catalog_review_transition_routing_policy_pack']['catalog_review_state'] == 'review_approved'
        assert node_data['last_catalog_evidence_package_routing_policy_pack']['report_type'] == 'openmiura_routing_policy_pack_catalog_evidence_package_v1'
        assert node_data['last_catalog_signed_release_bundle_routing_policy_pack']['report_type'] == 'openmiura_routing_policy_pack_signed_release_bundle_v1'



def test_canvas_cataloged_routing_policy_pack_release_train_rollout_governance(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_793_600.0
    _set_now(monkeypatch, base_now)
    monkeypatch.setenv('OPENMIURA_BASELINE_ESCROW_ROOT', str(tmp_path / 'escrow'))
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='baseline-routing-catalog-release-train',
            version='catalog-v1',
            environment_policy_baselines={'prod': _env_policy('baseline-v1')},
            promotion_policy={
                'simulation_custody_monitoring_policy': {
                    'enabled': True,
                    'auto_schedule': True,
                    'interval_s': 300,
                    'notify_on_drift': True,
                    'block_on_drift': True,
                    'load_aware_routing_enabled': True,
                    'queue_capacity_policy': {
                        'enabled': True,
                        'default_capacity': 2,
                        'prefer_lowest_load': True,
                        'queue_families_enabled': True,
                        'default_queue_family': 'ops',
                        'multi_hop_hysteresis_enabled': True,
                        'breach_prediction_enabled': True,
                        'expedite_enabled': True,
                        'admission_control_enabled': True,
                        'overload_governance_enabled': True,
                    },
                    'routing_routes': [
                        {'route_id': 'ops-a-route', 'label': 'Ops A', 'queue_id': 'ops-a', 'queue_label': 'Ops A', 'queue_family_id': 'ops', 'owner_role': 'shift-lead', 'queue_capacity': 2, 'severity': 'warning'},
                        {'route_id': 'ops-b-route', 'label': 'Ops B', 'queue_id': 'ops-b', 'queue_label': 'Ops B', 'queue_family_id': 'ops', 'owner_role': 'shift-lead', 'queue_capacity': 2, 'severity': 'warning'},
                    ],
                    'default_route': {'route_id': 'ops-a-route', 'label': 'Ops A', 'queue_id': 'ops-a', 'queue_label': 'Ops A', 'queue_family_id': 'ops', 'owner_role': 'shift-lead', 'queue_capacity': 2},
                    'queue_capacities': [
                        {'queue_id': 'ops-a', 'queue_label': 'Ops A', 'capacity': 2, 'queue_family_id': 'ops'},
                        {'queue_id': 'ops-b', 'queue_label': 'Ops B', 'capacity': 2, 'queue_family_id': 'ops'},
                    ],
                },
            },
        )
        runtime_id = _create_runtime_for_environment(client, headers, name='runtime-routing-pack-release-train', environment='prod')
        _create_portfolio_with_catalog(client, headers, base_now=base_now + 1, runtime_id=runtime_id, environment='prod', environment_tier_policies=_env_policy('baseline-v2'), baseline_catalog_ref={'catalog_id': catalog['catalog_id']})

        promotions = []
        for idx, version in enumerate(('catalog-v2', 'catalog-v3', 'catalog-v4'), start=1):
            response = client.post(
                f'/admin/openclaw/alert-governance/baseline-catalogs/{catalog["catalog_id"]}/promotions',
                headers=headers,
                json={'actor': f'catalog-admin-{idx}', 'version': version, 'environment_policy_baselines': {'prod': {'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': version}, 'escrow_policy': {'enabled': True, 'provider': 'filesystem-object-lock', 'classification': 'baseline-evidence'}}}, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
            )
            assert response.status_code == 200, response.text
            promotions.append(response.json()['promotion_id'])

        nodes: list[tuple[str, str]] = []
        for idx, promotion_id in enumerate(promotions, start=1):
            canvas = client.post('/admin/canvas/documents', headers=headers, json={'actor': f'operator-{idx}', 'title': f'catalog rollout canvas {idx}', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'})
            canvas_id = canvas.json()['document']['canvas_id']
            node = client.post(f'/admin/canvas/documents/{canvas_id}/nodes', headers=headers, json={'actor': f'operator-{idx}', 'node_type': 'baseline_promotion', 'label': promotion_id, 'data': {'promotion_id': promotion_id}, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'})
            node_id = node.json()['node']['node_id']
            nodes.append((canvas_id, node_id))
            simulate = client.post(f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/simulate?tenant_id=tenant-a&workspace_id=ws-a&environment=prod', headers=headers, json={'actor': f'operator-{idx}'})
            assert simulate.status_code == 200, simulate.text

        owner_canvas_id, owner_node_id = nodes[0]
        consumer_b_canvas_id, consumer_b_node_id = nodes[1]
        consumer_c_canvas_id, consumer_c_node_id = nodes[2]

        save_pack = client.post(f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/save_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod', headers=headers, json={'actor': 'operator-owner', 'preset_pack_id': 'family_hysteresis_presets'})
        assert save_pack.status_code == 200, save_pack.text
        promote = client.post(
            f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/promote_simulation_custody_routing_policy_pack_to_catalog?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator-owner', 'pack_id': 'family_hysteresis_presets', 'catalog_scope': 'global', 'catalog_approval_required': True, 'catalog_required_approvals': 1},
        )
        assert promote.status_code == 200, promote.text
        entry_id = promote.json()['result']['policy_pack']['catalog_entry_id']

        approve_pack = client.post(
            f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/approve_cataloged_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'governance-board', 'catalog_entry_id': entry_id, 'role': 'governance'},
        )
        assert approve_pack.status_code == 200, approve_pack.text
        assert approve_pack.json()['result']['policy_pack']['catalog_lifecycle_state'] == 'approved'

        stage = client.post(
            f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/stage_cataloged_simulation_custody_routing_policy_pack_release?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'release-manager', 'catalog_entry_id': entry_id, 'catalog_release_train_id': 'train-rollout-1', 'catalog_rollout_policy': {'enabled': True, 'wave_size': 1, 'require_manual_advance': True, 'require_evidence_package': True, 'require_signed_bundle': True}},
        )
        assert stage.status_code == 200, stage.text
        assert stage.json()['result']['policy_pack']['catalog_release_state'] == 'staged'
        assert stage.json()['result']['policy_pack']['catalog_rollout_state'] == 'staged'

        release = client.post(
            f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/release_cataloged_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'release-manager', 'catalog_entry_id': entry_id, 'catalog_release_notes': 'start staged rollout', 'catalog_rollout_policy': {'enabled': True, 'wave_size': 1, 'require_manual_advance': True, 'require_evidence_package': True, 'require_signed_bundle': True}},
        )
        assert release.status_code == 200, release.text
        released_pack = release.json()['result']['policy_pack']
        assert released_pack['catalog_release_state'] == 'rolling_out'
        assert released_pack['catalog_rollout_state'] == 'rolling_out'
        assert released_pack['catalog_rollout_current_wave_index'] == 1
        assert released_pack['catalog_rollout_summary']['wave_count'] == 3

        blocked_replay = client.post(
            f'/admin/canvas/documents/{consumer_b_canvas_id}/nodes/{consumer_b_node_id}/actions/replay_cataloged_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator-b', 'catalog_entry_id': entry_id},
        )
        assert blocked_replay.status_code == 200, blocked_replay.text
        assert blocked_replay.json()['result']['error'] == 'catalog_rollout_target_not_released'

        blocked_advance = client.post(
            f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/advance_cataloged_simulation_custody_routing_policy_pack_rollout?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'release-manager', 'catalog_entry_id': entry_id},
        )
        assert blocked_advance.status_code == 200, blocked_advance.text
        assert blocked_advance.json()['result']['error'] == 'baseline_promotion_simulation_custody_policy_pack_rollout_gate_failed'

        evidence = client.post(
            f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/export_cataloged_simulation_custody_routing_policy_pack_evidence_package?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'auditor-a', 'catalog_entry_id': entry_id},
        )
        assert evidence.status_code == 200, evidence.text
        bundle = client.post(
            f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/export_cataloged_simulation_custody_routing_policy_pack_signed_release_bundle?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'release-manager', 'catalog_entry_id': entry_id},
        )
        assert bundle.status_code == 200, bundle.text

        advance_wave_2 = client.post(
            f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/advance_cataloged_simulation_custody_routing_policy_pack_rollout?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'release-manager', 'catalog_entry_id': entry_id},
        )
        assert advance_wave_2.status_code == 200, advance_wave_2.text
        assert advance_wave_2.json()['result']['policy_pack']['catalog_rollout_current_wave_index'] == 2
        assert advance_wave_2.json()['result']['policy_pack']['catalog_rollout_state'] == 'rolling_out'

        allowed_replay_b = client.post(
            f'/admin/canvas/documents/{consumer_b_canvas_id}/nodes/{consumer_b_node_id}/actions/replay_cataloged_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator-b', 'catalog_entry_id': entry_id},
        )
        assert allowed_replay_b.status_code == 200, allowed_replay_b.text
        assert allowed_replay_b.json()['result']['routing_replay']['applied_pack']['catalog_rollout_state'] == 'rolling_out'

        freeze = client.post(
            f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/freeze_cataloged_simulation_custody_routing_policy_pack_rollout?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'release-manager', 'catalog_entry_id': entry_id},
        )
        assert freeze.status_code == 200, freeze.text
        assert freeze.json()['result']['policy_pack']['catalog_rollout_frozen'] is True

        blocked_frozen_advance = client.post(
            f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/advance_cataloged_simulation_custody_routing_policy_pack_rollout?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'release-manager', 'catalog_entry_id': entry_id},
        )
        assert blocked_frozen_advance.status_code == 200, blocked_frozen_advance.text
        assert blocked_frozen_advance.json()['result']['error'] == 'baseline_promotion_simulation_custody_policy_pack_rollout_gate_failed'
        assert blocked_frozen_advance.json()['result']['gate_evaluation']['reason'] == 'catalog_rollout_frozen'

        unfreeze = client.post(
            f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/unfreeze_cataloged_simulation_custody_routing_policy_pack_rollout?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'release-manager', 'catalog_entry_id': entry_id},
        )
        assert unfreeze.status_code == 200, unfreeze.text
        assert unfreeze.json()['result']['policy_pack']['catalog_rollout_frozen'] is False

        pause = client.post(
            f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/pause_cataloged_simulation_custody_routing_policy_pack_rollout?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'release-manager', 'catalog_entry_id': entry_id},
        )
        assert pause.status_code == 200, pause.text
        assert pause.json()['result']['policy_pack']['catalog_rollout_state'] == 'paused'

        blocked_paused_advance = client.post(
            f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/advance_cataloged_simulation_custody_routing_policy_pack_rollout?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'release-manager', 'catalog_entry_id': entry_id},
        )
        assert blocked_paused_advance.status_code == 200, blocked_paused_advance.text
        assert blocked_paused_advance.json()['result']['error'] == 'baseline_promotion_simulation_custody_policy_pack_rollout_not_active'

        resume = client.post(
            f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/resume_cataloged_simulation_custody_routing_policy_pack_rollout?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'release-manager', 'catalog_entry_id': entry_id},
        )
        assert resume.status_code == 200, resume.text
        assert resume.json()['result']['policy_pack']['catalog_rollout_state'] == 'rolling_out'

        advance_wave_3 = client.post(
            f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/advance_cataloged_simulation_custody_routing_policy_pack_rollout?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'release-manager', 'catalog_entry_id': entry_id},
        )
        assert advance_wave_3.status_code == 200, advance_wave_3.text
        wave_3_pack = advance_wave_3.json()['result']['policy_pack']
        assert wave_3_pack['catalog_rollout_state'] == 'rolling_out'
        assert wave_3_pack['catalog_release_state'] == 'rolling_out'
        assert wave_3_pack['catalog_rollout_current_wave_index'] == 3
        assert wave_3_pack['catalog_rollout_completed_wave_count'] == 2

        allowed_replay_c = client.post(
            f'/admin/canvas/documents/{consumer_c_canvas_id}/nodes/{consumer_c_node_id}/actions/replay_cataloged_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator-c', 'catalog_entry_id': entry_id},
        )
        assert allowed_replay_c.status_code == 200, allowed_replay_c.text
        assert allowed_replay_c.json()['result']['routing_replay']['applied_pack']['catalog_rollout_state'] == 'rolling_out'

        advance_complete = client.post(
            f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/advance_cataloged_simulation_custody_routing_policy_pack_rollout?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'release-manager', 'catalog_entry_id': entry_id},
        )
        assert advance_complete.status_code == 200, advance_complete.text
        complete_pack = advance_complete.json()['result']['policy_pack']
        assert complete_pack['catalog_rollout_state'] == 'completed'
        assert complete_pack['catalog_release_state'] == 'released'
        assert complete_pack['catalog_rollout_completed_wave_count'] == 3

        inspector_after = client.get(f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod', headers=headers)
        assert inspector_after.status_code == 200, inspector_after.text
        node_data = inspector_after.json()['node']['data']
        summary = node_data['routing_policy_pack_catalog_summary']
        assert summary['rollout_completed_count'] >= 1
        pack = next(item for item in node_data['routing_policy_pack_catalog'] if item['catalog_entry_id'] == entry_id)
        assert pack['catalog_rollout_summary']['state'] == 'completed'
        assert pack['catalog_rollout_summary']['wave_count'] == 3
        assert node_data['last_catalog_rollout_transition_routing_policy_pack']['catalog_rollout_state'] == 'completed'


def test_canvas_cataloged_routing_policy_pack_rollout_rollback_blocks_replay(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_793_900.0
    _set_now(monkeypatch, base_now)
    monkeypatch.setenv('OPENMIURA_BASELINE_ESCROW_ROOT', str(tmp_path / 'escrow'))
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='baseline-routing-catalog-rollout-rollback',
            version='catalog-v1',
            environment_policy_baselines={'prod': _env_policy('baseline-v1')},
            promotion_policy={
                'simulation_custody_monitoring_policy': {
                    'enabled': True,
                    'auto_schedule': True,
                    'interval_s': 300,
                    'queue_capacity_policy': {
                        'enabled': True,
                        'default_capacity': 2,
                        'queue_families_enabled': True,
                        'default_queue_family': 'ops',
                        'multi_hop_hysteresis_enabled': True,
                        'breach_prediction_enabled': True,
                        'expedite_enabled': True,
                        'admission_control_enabled': True,
                        'overload_governance_enabled': True,
                    },
                    'routing_routes': [
                        {'route_id': 'ops-a-route', 'label': 'Ops A', 'queue_id': 'ops-a', 'queue_label': 'Ops A', 'queue_family_id': 'ops', 'owner_role': 'shift-lead', 'queue_capacity': 2, 'severity': 'warning'},
                    ],
                    'default_route': {'route_id': 'ops-a-route', 'label': 'Ops A', 'queue_id': 'ops-a', 'queue_label': 'Ops A', 'queue_family_id': 'ops', 'owner_role': 'shift-lead', 'queue_capacity': 2},
                    'queue_capacities': [
                        {'queue_id': 'ops-a', 'queue_label': 'Ops A', 'capacity': 2, 'queue_family_id': 'ops'},
                    ],
                },
            },
        )
        runtime_id = _create_runtime_for_environment(client, headers, name='runtime-routing-pack-rollout-rollback', environment='prod')
        _create_portfolio_with_catalog(client, headers, base_now=base_now + 1, runtime_id=runtime_id, environment='prod', environment_tier_policies=_env_policy('baseline-v2'), baseline_catalog_ref={'catalog_id': catalog['catalog_id']})

        promotion_a = client.post(
            f'/admin/openclaw/alert-governance/baseline-catalogs/{catalog["catalog_id"]}/promotions',
            headers=headers,
            json={'actor': 'catalog-admin-a', 'version': 'catalog-v2', 'environment_policy_baselines': {'prod': {'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'catalog-v2'}}}, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        promotion_b = client.post(
            f'/admin/openclaw/alert-governance/baseline-catalogs/{catalog["catalog_id"]}/promotions',
            headers=headers,
            json={'actor': 'catalog-admin-b', 'version': 'catalog-v3', 'environment_policy_baselines': {'prod': {'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'catalog-v3'}}}, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        owner_promotion_id = promotion_a.json()['promotion_id']
        consumer_promotion_id = promotion_b.json()['promotion_id']

        owner_canvas = client.post('/admin/canvas/documents', headers=headers, json={'actor': 'owner', 'title': 'rollback owner canvas', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'})
        owner_canvas_id = owner_canvas.json()['document']['canvas_id']
        owner_node = client.post(f'/admin/canvas/documents/{owner_canvas_id}/nodes', headers=headers, json={'actor': 'owner', 'node_type': 'baseline_promotion', 'label': owner_promotion_id, 'data': {'promotion_id': owner_promotion_id}, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'})
        owner_node_id = owner_node.json()['node']['node_id']
        consumer_canvas = client.post('/admin/canvas/documents', headers=headers, json={'actor': 'consumer', 'title': 'rollback consumer canvas', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'})
        consumer_canvas_id = consumer_canvas.json()['document']['canvas_id']
        consumer_node = client.post(f'/admin/canvas/documents/{consumer_canvas_id}/nodes', headers=headers, json={'actor': 'consumer', 'node_type': 'baseline_promotion', 'label': consumer_promotion_id, 'data': {'promotion_id': consumer_promotion_id}, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'})
        consumer_node_id = consumer_node.json()['node']['node_id']
        assert client.post(f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/simulate?tenant_id=tenant-a&workspace_id=ws-a&environment=prod', headers=headers, json={'actor': 'owner'}).status_code == 200
        assert client.post(f'/admin/canvas/documents/{consumer_canvas_id}/nodes/{consumer_node_id}/actions/simulate?tenant_id=tenant-a&workspace_id=ws-a&environment=prod', headers=headers, json={'actor': 'consumer'}).status_code == 200

        assert client.post(f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/save_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod', headers=headers, json={'actor': 'owner', 'preset_pack_id': 'family_hysteresis_presets'}).status_code == 200
        promote = client.post(
            f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/promote_simulation_custody_routing_policy_pack_to_catalog?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'owner', 'pack_id': 'family_hysteresis_presets', 'catalog_scope': 'global', 'catalog_approval_required': True, 'catalog_required_approvals': 1},
        )
        entry_id = promote.json()['result']['policy_pack']['catalog_entry_id']
        assert client.post(f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/approve_cataloged_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod', headers=headers, json={'actor': 'governance-board', 'catalog_entry_id': entry_id, 'role': 'governance'}).status_code == 200
        assert client.post(f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/stage_cataloged_simulation_custody_routing_policy_pack_release?tenant_id=tenant-a&workspace_id=ws-a&environment=prod', headers=headers, json={'actor': 'release-manager', 'catalog_entry_id': entry_id, 'catalog_rollout_policy': {'enabled': True, 'wave_size': 1, 'require_manual_advance': True}}).status_code == 200
        release = client.post(f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/release_cataloged_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod', headers=headers, json={'actor': 'release-manager', 'catalog_entry_id': entry_id, 'catalog_rollout_policy': {'enabled': True, 'wave_size': 1, 'require_manual_advance': True}})
        assert release.status_code == 200, release.text
        assert release.json()['result']['policy_pack']['catalog_rollout_state'] == 'rolling_out'

        rollback = client.post(
            f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/rollback_cataloged_simulation_custody_routing_policy_pack_rollout?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'release-manager', 'catalog_entry_id': entry_id, 'catalog_rollout_rolled_back_reason': 'manual abort'},
        )
        assert rollback.status_code == 200, rollback.text
        rolled_back_pack = rollback.json()['result']['policy_pack']
        assert rolled_back_pack['catalog_rollout_state'] == 'rolled_back'
        assert rolled_back_pack['catalog_release_state'] == 'withdrawn'

        blocked_consumer = client.post(
            f'/admin/canvas/documents/{consumer_canvas_id}/nodes/{consumer_node_id}/actions/replay_cataloged_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'consumer', 'catalog_entry_id': entry_id},
        )
        assert blocked_consumer.status_code == 200, blocked_consumer.text
        assert blocked_consumer.json()['result']['error'] == 'catalog_rollout_withdrawn'

        inspector_after = client.get(f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod', headers=headers)
        node_data = inspector_after.json()['node']['data']
        assert node_data['routing_policy_pack_catalog_summary']['rollout_rolled_back_count'] >= 1
        assert node_data['last_catalog_rollout_transition_routing_policy_pack']['catalog_rollout_state'] == 'rolled_back'



def test_canvas_compacts_routing_policy_pack_state() -> None:
    pack = LiveCanvasService._compact_baseline_promotion_simulation_routing_policy_pack({
        'pack_id': 'sla_expedite_presets',
        'pack_label': 'SLA + expedite presets',
        'description': 'Compare deadline behaviour.',
        'source': 'registry',
        'category_keys': ['sla', 'expedite'],
        'tags': ['sla'],
        'scenario_count': 2,
        'use_count': 3,
        'registry_entry_id': 'registry_sla',
        'registry_scope': 'workspace',
        'promoted_at': 123.0,
        'promoted_by': 'operator',
        'catalog_scope': 'global',
        'catalog_version_key': 'sla_expedite_presets:global',
        'catalog_version': 2,
        'catalog_lifecycle_state': 'approved',
        'catalog_approved_by': 'approver',
        'catalog_is_latest': True,
        'catalog_approval_required': True,
        'catalog_required_approvals': 2,
        'catalog_approval_count': 2,
        'catalog_approval_state': 'approved',
        'catalog_release_state': 'released',
        'catalog_release_train_id': 'train-1',
        'catalog_rollout_enabled': True,
        'catalog_rollout_train_id': 'rollout-train-1',
        'catalog_rollout_state': 'completed',
        'catalog_rollout_current_wave_index': 2,
        'catalog_rollout_completed_wave_count': 2,
        'catalog_rollout_waves': [
            {'wave_index': 1, 'target_keys': ['t1'], 'status': 'completed', 'gate_evaluation': {'passed': True}},
            {'wave_index': 2, 'target_keys': ['t2'], 'status': 'completed', 'gate_evaluation': {'passed': True}},
        ],
        'catalog_rollout_targets': [
            {'target_key': 't1', 'promotion_id': 'promotion-a', 'released': True, 'released_wave_index': 1},
            {'target_key': 't2', 'promotion_id': 'promotion-b', 'released': True, 'released_wave_index': 2},
        ],
        'catalog_attestation_count': 1,
        'catalog_latest_attestation': {'report_id': 'report-1', 'report_type': 'openmiura_routing_policy_pack_catalog_attestation_v1', 'integrity': {'signed': True, 'payload_hash': 'abc'}},
        'catalog_review_state': 'review_approved',
        'catalog_review_assigned_reviewer': 'reviewer-a',
        'catalog_review_assigned_role': 'qa',
        'catalog_review_claimed_by': 'reviewer-a',
        'catalog_review_claimed_at': 124.0,
        'catalog_review_requested_at': 123.5,
        'catalog_review_requested_by': 'ops-lead',
        'catalog_review_last_transition_at': 125.0,
        'catalog_review_last_transition_by': 'reviewer-a',
        'catalog_review_last_transition_action': 'submit_review_decision',
        'catalog_review_decision': 'review_approved',
        'catalog_review_decision_at': 125.0,
        'catalog_review_decision_by': 'reviewer-a',
        'catalog_review_note_count': 2,
        'catalog_review_latest_note': 'approved after review',
        'catalog_review_events': [
            {'event_id': 'review-1', 'event_type': 'request_review', 'state': 'pending_review', 'actor': 'ops-lead', 'at': 123.5, 'assigned_reviewer': 'reviewer-a'},
            {'event_id': 'review-2', 'event_type': 'submit_review_decision', 'state': 'review_approved', 'actor': 'reviewer-a', 'at': 125.0, 'decision': 'review_approved', 'note': 'approved after review'},
        ],
        'catalog_evidence_package_count': 1,
        'catalog_latest_evidence_package': {'package_id': 'pkg-1', 'report_id': 'pkg-1', 'report_type': 'openmiura_routing_policy_pack_catalog_evidence_package_v1', 'integrity': {'signed': True, 'payload_hash': 'def'}},
        'catalog_release_bundle_count': 1,
        'catalog_latest_release_bundle': {'release_bundle_id': 'bundle-1', 'report_id': 'bundle-1', 'report_type': 'openmiura_routing_policy_pack_signed_release_bundle_v1', 'integrity': {'signed': True, 'payload_hash': 'ghi'}},
        'share_count': 2,
        'shared_from_pack_id': 'sla_expedite_presets',
        'shared_from_source': 'registry',
        'comparison_policies': [
            {'scenario_id': 'disable_expedite', 'scenario_label': 'Disable expedite', 'policy_delta_keys': ['queue_capacity_policy.expedite_enabled']},
            {'scenario_id': 'aggressive_expedite', 'scenario_label': 'Aggressive expedite', 'policy_delta_keys': ['queue_capacity_policy.expedite_threshold_s']},
        ],
    })
    assert pack['pack_id'] == 'sla_expedite_presets'
    assert pack['scenario_count'] == 2
    assert pack['use_count'] == 3
    assert pack['registry_entry_id'] == 'registry_sla'
    assert pack['registry_scope'] == 'workspace'
    assert pack['share_count'] == 2
    assert pack['catalog_scope'] == 'global'
    assert pack['catalog_version'] == 2
    assert pack['catalog_lifecycle_state'] == 'approved'
    assert pack['catalog_is_latest'] is True
    assert pack['catalog_approval_state'] == 'approved'
    assert pack['catalog_release_state'] == 'released'
    assert pack['catalog_rollout_summary']['state'] == 'completed'
    assert pack['catalog_rollout_summary']['released_target_count'] == 2
    assert pack['catalog_rollout_waves'][0]['status'] == 'completed'
    assert pack['catalog_attestation_count'] == 1
    assert pack['catalog_latest_attestation']['report_id'] == 'report-1'
    assert pack['catalog_review_state'] == 'review_approved'
    assert pack['catalog_review_assigned_reviewer'] == 'reviewer-a'
    assert pack['catalog_review_claimed_by'] == 'reviewer-a'
    assert pack['catalog_review_note_count'] == 2
    assert pack['catalog_review_timeline'][0]['event_type'] == 'request_review'
    assert pack['catalog_latest_evidence_package']['report_id'] == 'pkg-1'
    assert pack['catalog_latest_release_bundle']['report_id'] == 'bundle-1'
    assert pack['scenarios'][0]['scenario_id'] == 'disable_expedite'


def test_canvas_compacts_reservation_and_anti_thrashing_state() -> None:
    guard = LiveCanvasService._compact_baseline_promotion_simulation_custody_guard({
        'blocked': False,
        'reservation_enabled': True,
        'reserved_capacity': 2,
        'general_capacity': 3,
        'general_available': 0,
        'reserved_available': 1,
        'reservation_eligible': True,
        'reservation_applied': True,
        'effective_capacity': 5,
        'anti_thrashing_applied': True,
        'anti_thrashing_reason': 'reroute_cooldown_min_delta',
    })
    assert guard['reservation_enabled'] is True
    assert guard['reservation_applied'] is True
    assert guard['reserved_available'] == 1
    assert guard['anti_thrashing_applied'] is True
    assert guard['anti_thrashing_reason'] == 'reroute_cooldown_min_delta'

    summary = LiveCanvasService._compact_baseline_promotion_simulation_custody_alerts_summary({
        'active_reservation_protected_alert_count': 2,
        'active_anti_thrashing_kept_alert_count': 1,
    })
    assert summary['reservation_protected_alert_count'] == 2
    assert summary['anti_thrashing_kept_alert_count'] == 1

    active_alert = LiveCanvasService._compact_baseline_promotion_simulation_custody_active_alert({
        'alert_id': 'alert-1',
        'routing': {
            'route_id': 'route-1',
            'queue_id': 'ops-primary',
            'reservation_enabled': True,
            'reserved_capacity': 1,
            'general_capacity': 1,
            'general_available': 0,
            'reserved_available': 1,
            'reservation_eligible': True,
            'reservation_applied': True,
            'effective_capacity': 2,
            'anti_thrashing_applied': True,
            'anti_thrashing_reason': 'reroute_cooldown_min_delta',
        },
    })
    assert active_alert['routing']['reservation_enabled'] is True
    assert active_alert['routing']['reservation_applied'] is True
    assert active_alert['routing']['effective_capacity'] == 2
    assert active_alert['routing']['anti_thrashing_applied'] is True


def test_canvas_compacts_aging_and_starvation_state() -> None:
    guard = LiveCanvasService._compact_baseline_promotion_simulation_custody_guard({
        'alert_wait_age_s': 3_600,
        'aging_applied': True,
        'starving': True,
        'queue_oldest_alert_age_s': 7_200,
        'queue_aged_alert_count': 2,
        'queue_starving_alert_count': 1,
        'starvation_reserved_capacity_borrowed': True,
        'starvation_prevention_applied': True,
        'starvation_prevention_reason': 'borrow_reserved_capacity',
    })
    assert guard['alert_wait_age_s'] == 3_600
    assert guard['aging_applied'] is True
    assert guard['starving'] is True
    assert guard['queue_oldest_alert_age_s'] == 7_200
    assert guard['starvation_prevention_applied'] is True
    assert guard['starvation_prevention_reason'] == 'borrow_reserved_capacity'

    summary = LiveCanvasService._compact_baseline_promotion_simulation_custody_alerts_summary({
        'active_aging_alert_count': 2,
        'active_starving_alert_count': 1,
        'active_starvation_prevented_alert_count': 1,
    })
    assert summary['aging_alert_count'] == 2
    assert summary['starving_alert_count'] == 1
    assert summary['starvation_prevented_alert_count'] == 1

    active_alert = LiveCanvasService._compact_baseline_promotion_simulation_custody_active_alert({
        'alert_id': 'alert-2',
        'routing': {
            'route_id': 'route-2',
            'queue_id': 'ops-primary',
            'alert_wait_age_s': 1_800,
            'aging_applied': True,
            'starving': True,
            'queue_oldest_alert_age_s': 5_400,
            'queue_aged_alert_count': 3,
            'queue_starving_alert_count': 1,
            'starvation_reserved_capacity_borrowed': True,
            'starvation_prevention_applied': True,
            'starvation_prevention_reason': 'borrow_reserved_capacity',
        },
    })
    assert active_alert['routing']['alert_wait_age_s'] == 1_800
    assert active_alert['routing']['aging_applied'] is True
    assert active_alert['routing']['starving'] is True
    assert active_alert['routing']['queue_starving_alert_count'] == 1
    assert active_alert['routing']['starvation_prevention_applied'] is True



def test_canvas_compacts_sla_deadline_and_expedite_state() -> None:
    guard = LiveCanvasService._compact_baseline_promotion_simulation_custody_guard({'sla_deadline_target': 'acknowledge', 'time_to_breach_s': 180, 'predicted_wait_time_s': 75, 'predicted_sla_margin_s': 105, 'predicted_sla_breach': False, 'breach_risk_score': 0.42, 'breach_risk_level': 'medium', 'expected_service_time_s': 300, 'expedite_eligible': True, 'expedite_applied': True, 'expedite_reason': 'deadline_threshold'})
    assert guard['sla_deadline_target'] == 'acknowledge'
    assert guard['time_to_breach_s'] == 180
    assert guard['predicted_wait_time_s'] == 75
    assert guard['expedite_applied'] is True
    summary = LiveCanvasService._compact_baseline_promotion_simulation_custody_alerts_summary({'active_alerts_at_risk_count': 2, 'active_predicted_sla_breach_count': 1, 'active_expedite_routed_alert_count': 1})
    assert summary['alerts_at_risk_count'] == 2
    assert summary['predicted_sla_breach_count'] == 1
    assert summary['expedite_routed_alert_count'] == 1
    active_alert = LiveCanvasService._compact_baseline_promotion_simulation_custody_active_alert({'alert_id': 'alert-sla', 'routing': {'route_id': 'route-expedite', 'queue_id': 'ops-backup', 'sla_deadline_target': 'acknowledge', 'time_to_breach_s': 180, 'predicted_wait_time_s': 75, 'predicted_sla_margin_s': 105, 'predicted_sla_breach': False, 'breach_risk_score': 0.42, 'breach_risk_level': 'medium', 'expected_service_time_s': 300, 'expedite_eligible': True, 'expedite_applied': True, 'expedite_reason': 'deadline_threshold'}})
    assert active_alert['routing']['sla_deadline_target'] == 'acknowledge'
    assert active_alert['routing']['predicted_wait_time_s'] == 75
    assert active_alert['routing']['expedite_applied'] is True



def test_canvas_compacts_admission_control_and_overload_governance_state() -> None:
    guard = LiveCanvasService._compact_baseline_promotion_simulation_custody_guard({
        'admission_control_enabled': True,
        'admission_action': 'defer',
        'admission_exempt': False,
        'admission_decision': 'defer',
        'admission_blocked': True,
        'admission_reason': 'projected_wait_threshold',
        'admission_review_required': False,
        'overload_governance_enabled': True,
        'overload_governance_applied': True,
        'overload_action': 'defer',
        'overload_projected_load_ratio_threshold': 0.9,
        'overload_projected_wait_time_threshold_s': 600,
        'overload_predicted': True,
        'overload_reason': 'projected_wait_threshold',
    })
    assert guard['admission_control_enabled'] is True
    assert guard['admission_decision'] == 'defer'
    assert guard['admission_blocked'] is True
    assert guard['overload_governance_applied'] is True
    assert guard['overload_predicted'] is True

    summary = LiveCanvasService._compact_baseline_promotion_simulation_custody_alerts_summary({
        'active_overload_governed_alert_count': 2,
        'active_overload_blocked_alert_count': 1,
        'active_admission_deferred_alert_count': 1,
        'active_manual_gate_alert_count': 1,
    })
    assert summary['overload_governed_alert_count'] == 2
    assert summary['overload_blocked_alert_count'] == 1
    assert summary['admission_deferred_alert_count'] == 1
    assert summary['manual_gate_alert_count'] == 1

    active_alert = LiveCanvasService._compact_baseline_promotion_simulation_custody_active_alert({
        'alert_id': 'alert-overload',
        'routing': {
            'route_id': 'route-overload',
            'queue_id': 'ops-primary',
            'admission_control_enabled': True,
            'admission_action': 'manual_gate',
            'admission_exempt': False,
            'admission_decision': 'manual_gate',
            'admission_blocked': True,
            'admission_reason': 'forecasted_over_capacity',
            'admission_review_required': True,
            'overload_governance_enabled': True,
            'overload_governance_applied': True,
            'overload_action': 'manual_gate',
            'overload_projected_load_ratio_threshold': 0.85,
            'overload_projected_wait_time_threshold_s': 300,
            'overload_predicted': True,
            'overload_reason': 'forecasted_over_capacity',
        },
    })
    assert active_alert['routing']['admission_decision'] == 'manual_gate'
    assert active_alert['routing']['admission_blocked'] is True
    assert active_alert['routing']['admission_review_required'] is True
    assert active_alert['routing']['overload_governance_applied'] is True
    assert active_alert['routing']['overload_reason'] == 'forecasted_over_capacity'



def test_canvas_compacts_predictive_forecasting_and_proactive_routing_state() -> None:
    guard = LiveCanvasService._compact_baseline_promotion_simulation_custody_guard({
        'forecast_window_s': 900,
        'forecast_arrivals_count': 12,
        'forecast_departures_count': 4,
        'projected_active_count': 5,
        'projected_load_ratio': 1.25,
        'projected_wait_time_s': 375,
        'forecasted_over_capacity': True,
        'surge_predicted': True,
        'proactive_routing_eligible': True,
        'proactive_routing_applied': True,
        'proactive_reason': 'avoid_forecasted_surge',
    })
    assert guard['forecast_window_s'] == 900
    assert guard['forecast_arrivals_count'] == 12
    assert guard['projected_load_ratio'] == 1.25
    assert guard['surge_predicted'] is True
    assert guard['proactive_routing_applied'] is True
    assert guard['proactive_reason'] == 'avoid_forecasted_surge'

    summary = LiveCanvasService._compact_baseline_promotion_simulation_custody_alerts_summary({
        'active_proactive_routed_alert_count': 2,
        'active_forecasted_surge_alert_count': 3,
    })
    assert summary['proactive_routed_alert_count'] == 2
    assert summary['forecasted_surge_alert_count'] == 3

    active_alert = LiveCanvasService._compact_baseline_promotion_simulation_custody_active_alert({
        'alert_id': 'alert-forecast',
        'routing': {
            'route_id': 'route-forecast',
            'queue_id': 'ops-backup',
            'forecast_window_s': 900,
            'forecast_arrivals_count': 12,
            'forecast_departures_count': 4,
            'projected_active_count': 5,
            'projected_load_ratio': 1.25,
            'projected_wait_time_s': 375,
            'forecasted_over_capacity': True,
            'surge_predicted': True,
            'proactive_routing_eligible': True,
            'proactive_routing_applied': True,
            'proactive_reason': 'avoid_forecasted_surge',
        },
    })
    assert active_alert['routing']['forecast_window_s'] == 900
    assert active_alert['routing']['projected_wait_time_s'] == 375
    assert active_alert['routing']['proactive_routing_applied'] is True
    assert active_alert['routing']['proactive_reason'] == 'avoid_forecasted_surge'


def test_canvas_compacts_reservation_leasing_and_temporary_hold_state() -> None:
    guard = LiveCanvasService._compact_baseline_promotion_simulation_custody_guard({
        'lease_active': True,
        'leased_capacity': 1,
        'lease_available': 1,
        'lease_reason': 'expedite-window',
        'lease_holder': 'ops-control',
        'lease_eligible': True,
        'lease_applied': True,
        'temporary_hold_count': 1,
        'temporary_hold_capacity': 1,
        'temporary_hold_available': 1,
        'temporary_hold_ids': ['hold-1'],
        'temporary_hold_reasons': ['handoff_pending'],
        'temporary_hold_eligible': True,
        'temporary_hold_applied': True,
        'expired_temporary_hold_count': 1,
        'expired_temporary_hold_ids': ['hold-expired'],
    })
    assert guard['lease_active'] is True
    assert guard['leased_capacity'] == 1
    assert guard['lease_applied'] is True
    assert guard['temporary_hold_count'] == 1
    assert guard['temporary_hold_applied'] is True
    assert guard['expired_temporary_hold_count'] == 1

    summary = LiveCanvasService._compact_baseline_promotion_simulation_custody_alerts_summary({
        'active_lease_protected_alert_count': 2,
        'active_temporary_hold_protected_alert_count': 1,
    })
    assert summary['lease_protected_alert_count'] == 2
    assert summary['temporary_hold_protected_alert_count'] == 1

    active_alert = LiveCanvasService._compact_baseline_promotion_simulation_custody_active_alert({
        'alert_id': 'alert-lease',
        'routing': {
            'route_id': 'route-lease',
            'queue_id': 'ops-primary',
            'lease_active': True,
            'leased_capacity': 1,
            'lease_available': 1,
            'lease_reason': 'expedite-window',
            'lease_applied': True,
            'temporary_hold_count': 1,
            'temporary_hold_capacity': 1,
            'temporary_hold_available': 1,
            'temporary_hold_ids': ['hold-1'],
            'temporary_hold_reasons': ['handoff_pending'],
            'temporary_hold_applied': True,
            'expired_temporary_hold_count': 1,
        },
    })
    assert active_alert['routing']['lease_active'] is True
    assert active_alert['routing']['lease_applied'] is True
    assert active_alert['routing']['temporary_hold_count'] == 1
    assert active_alert['routing']['temporary_hold_applied'] is True


def test_canvas_compacts_queue_family_and_hysteresis_state() -> None:
    guard = LiveCanvasService._compact_baseline_promotion_simulation_custody_guard({
        'queue_family_id': 'ops-family',
        'queue_family_label': 'Ops Family',
        'queue_family_enabled': True,
        'queue_family_member_count': 2,
        'recent_queue_hop_count': 3,
        'recent_family_hop_count': 2,
        'family_hysteresis_applied': True,
        'family_hysteresis_reason': 'recent_same_family_multi_hop',
        'route_history_queue_ids': ['ops-a', 'ops-b', 'ops-a'],
        'route_history_family_ids': ['ops-family', 'ops-family', 'ops-family'],
    })
    assert guard['queue_family_id'] == 'ops-family'
    assert guard['queue_family_member_count'] == 2
    assert guard['family_hysteresis_applied'] is True
    assert guard['family_hysteresis_reason'] == 'recent_same_family_multi_hop'

    summary = LiveCanvasService._compact_baseline_promotion_simulation_custody_alerts_summary({
        'active_queue_family_alert_count': 2,
        'active_family_hysteresis_kept_alert_count': 1,
    })
    assert summary['queue_family_alert_count'] == 2
    assert summary['family_hysteresis_kept_alert_count'] == 1

    active_alert = LiveCanvasService._compact_baseline_promotion_simulation_custody_active_alert({
        'alert_id': 'alert-family-1',
        'routing': {
            'route_id': 'route-ops-b',
            'queue_id': 'ops-b',
            'queue_family_id': 'ops-family',
            'queue_family_label': 'Ops Family',
            'queue_family_enabled': True,
            'queue_family_member_count': 2,
            'recent_queue_hop_count': 3,
            'recent_family_hop_count': 2,
            'family_hysteresis_applied': False,
            'family_hysteresis_reason': 'bypass_expedite_alert',
            'route_history_queue_ids': ['ops-a', 'ops-b', 'ops-a'],
            'route_history_family_ids': ['ops-family', 'ops-family', 'ops-family'],
        },
    })
    assert active_alert['routing']['queue_family_id'] == 'ops-family'
    assert active_alert['routing']['recent_family_hop_count'] == 2
    assert active_alert['routing']['family_hysteresis_reason'] == 'bypass_expedite_alert'


def test_canvas_cataloged_routing_policy_pack_dependency_conflict_and_freeze_governance(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_794_500.0
    _set_now(monkeypatch, base_now)
    monkeypatch.setenv('OPENMIURA_BASELINE_ESCROW_ROOT', str(tmp_path / 'escrow'))
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='baseline-routing-catalog-dependency-conflict-freeze',
            version='catalog-v1',
            environment_policy_baselines={'prod': _env_policy('baseline-v1')},
            promotion_policy={
                'simulation_custody_monitoring_policy': {
                    'enabled': True,
                    'auto_schedule': True,
                    'interval_s': 300,
                    'queue_capacity_policy': {
                        'enabled': True,
                        'default_capacity': 2,
                        'queue_families_enabled': True,
                        'default_queue_family': 'ops',
                        'multi_hop_hysteresis_enabled': True,
                        'breach_prediction_enabled': True,
                        'expedite_enabled': True,
                        'admission_control_enabled': True,
                        'overload_governance_enabled': True,
                    },
                    'routing_routes': [
                        {'route_id': 'ops-a-route', 'label': 'Ops A', 'queue_id': 'ops-a', 'queue_label': 'Ops A', 'queue_family_id': 'ops', 'owner_role': 'shift-lead', 'queue_capacity': 2, 'severity': 'warning'},
                        {'route_id': 'ops-b-route', 'label': 'Ops B', 'queue_id': 'ops-b', 'queue_label': 'Ops B', 'queue_family_id': 'ops', 'owner_role': 'shift-lead', 'queue_capacity': 2, 'severity': 'warning'},
                    ],
                    'default_route': {'route_id': 'ops-a-route', 'label': 'Ops A', 'queue_id': 'ops-a', 'queue_label': 'Ops A', 'queue_family_id': 'ops', 'owner_role': 'shift-lead', 'queue_capacity': 2},
                    'queue_capacities': [
                        {'queue_id': 'ops-a', 'queue_label': 'Ops A', 'capacity': 2, 'queue_family_id': 'ops'},
                        {'queue_id': 'ops-b', 'queue_label': 'Ops B', 'capacity': 2, 'queue_family_id': 'ops'},
                    ],
                },
            },
        )
        runtime_id = _create_runtime_for_environment(client, headers, name='runtime-routing-pack-dependency-conflict-freeze', environment='prod')
        _create_portfolio_with_catalog(client, headers, base_now=base_now + 1, runtime_id=runtime_id, environment='prod', environment_tier_policies=_env_policy('baseline-v2'), baseline_catalog_ref={'catalog_id': catalog['catalog_id']})

        promotions: list[str] = []
        for idx, version in enumerate(('catalog-v2', 'catalog-v3', 'catalog-v4'), start=1):
            response = client.post(
                f'/admin/openclaw/alert-governance/baseline-catalogs/{catalog["catalog_id"]}/promotions',
                headers=headers,
                json={'actor': f'catalog-admin-{idx}', 'version': version, 'environment_policy_baselines': {'prod': {'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': version}}}, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
            )
            assert response.status_code == 200, response.text
            promotions.append(response.json()['promotion_id'])

        nodes: list[tuple[str, str]] = []
        for idx, promotion_id in enumerate(promotions, start=1):
            canvas = client.post('/admin/canvas/documents', headers=headers, json={'actor': f'operator-{idx}', 'title': f'catalog dependency conflict freeze canvas {idx}', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'})
            canvas_id = canvas.json()['document']['canvas_id']
            node = client.post(f'/admin/canvas/documents/{canvas_id}/nodes', headers=headers, json={'actor': f'operator-{idx}', 'node_type': 'baseline_promotion', 'label': promotion_id, 'data': {'promotion_id': promotion_id}, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'})
            node_id = node.json()['node']['node_id']
            nodes.append((canvas_id, node_id))
            simulate = client.post(f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/simulate?tenant_id=tenant-a&workspace_id=ws-a&environment=prod', headers=headers, json={'actor': f'operator-{idx}'})
            assert simulate.status_code == 200, simulate.text
            save_pack = client.post(
                f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/save_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
                headers=headers,
                json={'actor': f'operator-{idx}', 'preset_pack_id': 'family_hysteresis_presets'},
            )
            assert save_pack.status_code == 200, save_pack.text

        dep_canvas_id, dep_node_id = nodes[0]
        target_canvas_id, target_node_id = nodes[1]
        conflict_canvas_id, conflict_node_id = nodes[2]

        dep_promote = client.post(
            f'/admin/canvas/documents/{dep_canvas_id}/nodes/{dep_node_id}/actions/promote_simulation_custody_routing_policy_pack_to_catalog?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator-dep', 'pack_id': 'family_hysteresis_presets', 'catalog_scope': 'global', 'catalog_version_key': 'routing-pack-dependency-line', 'catalog_approval_required': True, 'catalog_required_approvals': 1},
        )
        assert dep_promote.status_code == 200, dep_promote.text
        dep_entry_id = dep_promote.json()['result']['policy_pack']['catalog_entry_id']

        target_promote = client.post(
            f'/admin/canvas/documents/{target_canvas_id}/nodes/{target_node_id}/actions/promote_simulation_custody_routing_policy_pack_to_catalog?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={
                'actor': 'operator-target',
                'pack_id': 'family_hysteresis_presets',
                'catalog_scope': 'global',
                'catalog_version_key': 'routing-pack-target-line',
                'catalog_approval_required': True,
                'catalog_required_approvals': 1,
                'catalog_dependency_refs': [{'catalog_version_key': 'routing-pack-dependency-line', 'required_release_state': 'released'}],
                'catalog_freeze_windows': [
                    {'window_id': 'freeze-stage', 'label': 'Stage freeze', 'start_at': base_now - 60.0, 'end_at': base_now + 60.0, 'reason': 'CAB freeze', 'block_stage': True, 'block_release': True, 'block_advance': False},
                    {'window_id': 'freeze-advance', 'label': 'Advance freeze', 'start_at': base_now + 200.0, 'end_at': base_now + 320.0, 'reason': 'Weekend freeze', 'block_stage': False, 'block_release': False, 'block_advance': True},
                ],
            },
        )
        assert target_promote.status_code == 200, target_promote.text
        target_entry_id = target_promote.json()['result']['policy_pack']['catalog_entry_id']

        target_approve = client.post(
            f'/admin/canvas/documents/{target_canvas_id}/nodes/{target_node_id}/actions/approve_cataloged_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'governance-target', 'catalog_entry_id': target_entry_id, 'role': 'governance'},
        )
        assert target_approve.status_code == 200, target_approve.text

        blocked_by_dependency = client.post(
            f'/admin/canvas/documents/{target_canvas_id}/nodes/{target_node_id}/actions/stage_cataloged_simulation_custody_routing_policy_pack_release?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'release-manager', 'catalog_entry_id': target_entry_id},
        )
        assert blocked_by_dependency.status_code == 200, blocked_by_dependency.text
        assert blocked_by_dependency.json()['result']['error'] == 'baseline_promotion_simulation_custody_policy_pack_release_blocked'
        assert blocked_by_dependency.json()['result']['guard_evaluation']['reason'] == 'catalog_dependency_unsatisfied'

        dep_approve = client.post(
            f'/admin/canvas/documents/{dep_canvas_id}/nodes/{dep_node_id}/actions/approve_cataloged_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'governance-dep', 'catalog_entry_id': dep_entry_id, 'role': 'governance'},
        )
        assert dep_approve.status_code == 200, dep_approve.text
        dep_stage = client.post(
            f'/admin/canvas/documents/{dep_canvas_id}/nodes/{dep_node_id}/actions/stage_cataloged_simulation_custody_routing_policy_pack_release?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'release-manager', 'catalog_entry_id': dep_entry_id},
        )
        assert dep_stage.status_code == 200, dep_stage.text
        dep_release = client.post(
            f'/admin/canvas/documents/{dep_canvas_id}/nodes/{dep_node_id}/actions/release_cataloged_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'release-manager', 'catalog_entry_id': dep_entry_id},
        )
        assert dep_release.status_code == 200, dep_release.text
        assert dep_release.json()['result']['policy_pack']['catalog_release_state'] == 'released'

        blocked_by_freeze = client.post(
            f'/admin/canvas/documents/{target_canvas_id}/nodes/{target_node_id}/actions/stage_cataloged_simulation_custody_routing_policy_pack_release?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'release-manager', 'catalog_entry_id': target_entry_id},
        )
        assert blocked_by_freeze.status_code == 200, blocked_by_freeze.text
        assert blocked_by_freeze.json()['result']['error'] == 'baseline_promotion_simulation_custody_policy_pack_release_blocked'
        assert blocked_by_freeze.json()['result']['guard_evaluation']['reason'] == 'catalog_freeze_window_active'

        _set_now(monkeypatch, base_now + 150.0)

        conflict_promote = client.post(
            f'/admin/canvas/documents/{conflict_canvas_id}/nodes/{conflict_node_id}/actions/promote_simulation_custody_routing_policy_pack_to_catalog?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator-conflict', 'pack_id': 'family_hysteresis_presets', 'catalog_scope': 'global', 'catalog_version_key': 'routing-pack-conflict-line', 'catalog_approval_required': True, 'catalog_required_approvals': 1},
        )
        assert conflict_promote.status_code == 200, conflict_promote.text
        conflict_entry_id = conflict_promote.json()['result']['policy_pack']['catalog_entry_id']

        conflict_approve = client.post(
            f'/admin/canvas/documents/{conflict_canvas_id}/nodes/{conflict_node_id}/actions/approve_cataloged_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'governance-conflict', 'catalog_entry_id': conflict_entry_id, 'role': 'governance'},
        )
        assert conflict_approve.status_code == 200, conflict_approve.text
        conflict_stage = client.post(
            f'/admin/canvas/documents/{conflict_canvas_id}/nodes/{conflict_node_id}/actions/stage_cataloged_simulation_custody_routing_policy_pack_release?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'release-manager', 'catalog_entry_id': conflict_entry_id},
        )
        assert conflict_stage.status_code == 200, conflict_stage.text
        conflict_release = client.post(
            f'/admin/canvas/documents/{conflict_canvas_id}/nodes/{conflict_node_id}/actions/release_cataloged_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'release-manager', 'catalog_entry_id': conflict_entry_id},
        )
        assert conflict_release.status_code == 200, conflict_release.text
        assert conflict_release.json()['result']['policy_pack']['catalog_release_state'] == 'released'

        target_conflict_update = client.post(
            f'/admin/canvas/documents/{target_canvas_id}/nodes/{target_node_id}/actions/promote_simulation_custody_routing_policy_pack_to_catalog?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={
                'actor': 'operator-target',
                'pack_id': 'family_hysteresis_presets',
                'catalog_scope': 'global',
                'catalog_entry_id': target_entry_id,
                'catalog_version_key': 'routing-pack-target-line',
                'catalog_version': 1,
                'catalog_approval_required': True,
                'catalog_required_approvals': 1,
                'catalog_dependency_refs': [{'catalog_version_key': 'routing-pack-dependency-line', 'required_release_state': 'released'}],
                'catalog_conflict_rules': {'conflict_version_keys': ['routing-pack-conflict-line']},
                'catalog_freeze_windows': [
                    {'window_id': 'freeze-stage', 'label': 'Stage freeze', 'start_at': base_now - 60.0, 'end_at': base_now + 60.0, 'reason': 'CAB freeze', 'block_stage': True, 'block_release': True, 'block_advance': False},
                    {'window_id': 'freeze-advance', 'label': 'Advance freeze', 'start_at': base_now + 200.0, 'end_at': base_now + 320.0, 'reason': 'Weekend freeze', 'block_stage': False, 'block_release': False, 'block_advance': True},
                ],
            },
        )
        assert target_conflict_update.status_code == 200, target_conflict_update.text

        inspector_conflict = client.get(f'/admin/canvas/documents/{target_canvas_id}/nodes/{target_node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod', headers=headers)
        assert inspector_conflict.status_code == 200, inspector_conflict.text
        conflict_node_data = inspector_conflict.json()['node']['data']
        target_pack_conflict = next(item for item in conflict_node_data['routing_policy_pack_catalog'] if item['catalog_entry_id'] == target_entry_id)
        assert target_pack_conflict['catalog_dependency_summary']['blocking'] is False
        assert target_pack_conflict['catalog_conflict_summary']['blocking'] is True
        assert target_pack_conflict['catalog_release_guard']['reason'] == 'catalog_conflict_detected'
        assert conflict_node_data['routing_policy_pack_catalog_summary']['conflict_blocked_count'] >= 1

        blocked_by_conflict = client.post(
            f'/admin/canvas/documents/{target_canvas_id}/nodes/{target_node_id}/actions/stage_cataloged_simulation_custody_routing_policy_pack_release?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'release-manager', 'catalog_entry_id': target_entry_id},
        )
        assert blocked_by_conflict.status_code == 200, blocked_by_conflict.text
        assert blocked_by_conflict.json()['result']['error'] == 'baseline_promotion_simulation_custody_policy_pack_release_blocked'
        assert blocked_by_conflict.json()['result']['guard_evaluation']['reason'] == 'catalog_conflict_detected'

        withdraw_conflict = client.post(
            f'/admin/canvas/documents/{conflict_canvas_id}/nodes/{conflict_node_id}/actions/withdraw_cataloged_simulation_custody_routing_policy_pack_release?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'release-manager', 'catalog_entry_id': conflict_entry_id, 'catalog_withdrawn_reason': 'clear conflict for target pack'},
        )
        assert withdraw_conflict.status_code == 200, withdraw_conflict.text
        assert withdraw_conflict.json()['result']['policy_pack']['catalog_release_state'] == 'withdrawn'

        stage_target = client.post(
            f'/admin/canvas/documents/{target_canvas_id}/nodes/{target_node_id}/actions/stage_cataloged_simulation_custody_routing_policy_pack_release?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'release-manager', 'catalog_entry_id': target_entry_id, 'catalog_rollout_policy': {'enabled': True, 'wave_size': 1, 'require_manual_advance': True}},
        )
        assert stage_target.status_code == 200, stage_target.text
        assert stage_target.json()['result']['policy_pack']['catalog_release_state'] == 'staged'

        release_target = client.post(
            f'/admin/canvas/documents/{target_canvas_id}/nodes/{target_node_id}/actions/release_cataloged_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'release-manager', 'catalog_entry_id': target_entry_id, 'catalog_rollout_policy': {'enabled': True, 'wave_size': 1, 'require_manual_advance': True}},
        )
        assert release_target.status_code == 200, release_target.text
        assert release_target.json()['result']['policy_pack']['catalog_rollout_state'] == 'rolling_out'

        _set_now(monkeypatch, base_now + 250.0)
        blocked_advance = client.post(
            f'/admin/canvas/documents/{target_canvas_id}/nodes/{target_node_id}/actions/advance_cataloged_simulation_custody_routing_policy_pack_rollout?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'release-manager', 'catalog_entry_id': target_entry_id},
        )
        assert blocked_advance.status_code == 200, blocked_advance.text
        assert blocked_advance.json()['result']['error'] == 'baseline_promotion_simulation_custody_policy_pack_rollout_gate_failed'
        assert blocked_advance.json()['result']['gate_evaluation']['reason'] == 'catalog_freeze_window_active'

        _set_now(monkeypatch, base_now + 400.0)
        advance_ok = client.post(
            f'/admin/canvas/documents/{target_canvas_id}/nodes/{target_node_id}/actions/advance_cataloged_simulation_custody_routing_policy_pack_rollout?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'release-manager', 'catalog_entry_id': target_entry_id},
        )
        assert advance_ok.status_code == 200, advance_ok.text
        assert advance_ok.json()['result']['policy_pack']['catalog_rollout_current_wave_index'] >= 2


def test_canvas_cataloged_routing_policy_pack_scoped_adoption_governance_and_effective_policy_binding(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_798_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='baseline-routing-catalog-effective-binding',
            version='catalog-v1',
            environment_policy_baselines={'prod': _env_policy('baseline-v1'), 'dev': _env_policy('baseline-v1')},
            promotion_policy={
                'simulation_custody_monitoring_policy': {
                    'enabled': True,
                    'auto_schedule': True,
                    'interval_s': 300,
                    'queue_capacity_policy': {
                        'enabled': True,
                        'default_capacity': 2,
                        'queue_families_enabled': True,
                        'default_queue_family': 'ops',
                        'multi_hop_hysteresis_enabled': True,
                        'breach_prediction_enabled': True,
                        'expedite_enabled': True,
                        'admission_control_enabled': True,
                        'overload_governance_enabled': True,
                    },
                    'routing_routes': [
                        {'route_id': 'ops-a-route', 'label': 'Ops A', 'queue_id': 'ops-a', 'queue_label': 'Ops A', 'queue_family_id': 'ops', 'owner_role': 'shift-lead', 'queue_capacity': 2, 'severity': 'warning'},
                        {'route_id': 'ops-b-route', 'label': 'Ops B', 'queue_id': 'ops-b', 'queue_label': 'Ops B', 'queue_family_id': 'ops', 'owner_role': 'shift-lead', 'queue_capacity': 2, 'severity': 'warning'},
                    ],
                    'default_route': {'route_id': 'ops-a-route', 'label': 'Ops A', 'queue_id': 'ops-a', 'queue_label': 'Ops A', 'queue_family_id': 'ops', 'owner_role': 'shift-lead', 'queue_capacity': 2},
                    'queue_capacities': [
                        {'queue_id': 'ops-a', 'queue_label': 'Ops A', 'capacity': 2, 'queue_family_id': 'ops'},
                        {'queue_id': 'ops-b', 'queue_label': 'Ops B', 'capacity': 2, 'queue_family_id': 'ops'},
                    ],
                },
            },
        )
        runtime_prod = _create_runtime_for_environment(client, headers, name='runtime-routing-binding-prod', environment='prod')
        runtime_dev = _create_runtime_for_environment(client, headers, name='runtime-routing-binding-dev', environment='dev')
        _create_portfolio_with_catalog(client, headers, base_now=base_now + 1, runtime_id=runtime_prod, environment='prod', environment_tier_policies=_env_policy('baseline-v2'), baseline_catalog_ref={'catalog_id': catalog['catalog_id']})
        _create_portfolio_with_catalog(client, headers, base_now=base_now + 2, runtime_id=runtime_dev, environment='dev', environment_tier_policies=_env_policy('baseline-v2'), baseline_catalog_ref={'catalog_id': catalog['catalog_id']})

        def _create_canvas_node(version: str, *, actor: str, title: str, environment: str) -> tuple[str, str, str]:
            promotion = client.post(
                f'/admin/openclaw/alert-governance/baseline-catalogs/{catalog["catalog_id"]}/promotions',
                headers=headers,
                json={'actor': actor, 'version': version, 'environment_policy_baselines': {environment: {'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': version}}}, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': environment},
            )
            assert promotion.status_code == 200, promotion.text
            promotion_id = promotion.json()['promotion_id']
            canvas = client.post('/admin/canvas/documents', headers=headers, json={'actor': actor, 'title': title, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': environment})
            canvas_id = canvas.json()['document']['canvas_id']
            node = client.post(f'/admin/canvas/documents/{canvas_id}/nodes', headers=headers, json={'actor': actor, 'node_type': 'baseline_promotion', 'label': promotion_id, 'data': {'promotion_id': promotion_id}, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': environment})
            node_id = node.json()['node']['node_id']
            simulate = client.post(f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/simulate?tenant_id=tenant-a&workspace_id=ws-a&environment={environment}', headers=headers, json={'actor': actor})
            assert simulate.status_code == 200, simulate.text
            return promotion_id, canvas_id, node_id

        owner_promotion_id, owner_canvas_id, owner_node_id = _create_canvas_node('catalog-v2-prod-owner', actor='operator-owner', title='routing binding owner', environment='prod')
        prod_promotion_id, prod_canvas_id, prod_node_id = _create_canvas_node('catalog-v2-prod-consumer', actor='operator-prod', title='routing binding prod consumer', environment='prod')
        _dev_promotion_id, dev_canvas_id, dev_node_id = _create_canvas_node('catalog-v2-dev-consumer', actor='operator-dev', title='routing binding dev consumer', environment='dev')

        def _promote_release_pack(pack_id: str, *, actor: str) -> str:
            save = client.post(
                f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/save_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
                headers=headers,
                json={'actor': actor, 'preset_pack_id': pack_id},
            )
            assert save.status_code == 200, save.text
            promote = client.post(
                f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/promote_simulation_custody_routing_policy_pack_to_catalog?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
                headers=headers,
                json={'actor': actor, 'pack_id': pack_id, 'catalog_scope': 'global'},
            )
            assert promote.status_code == 200, promote.text
            entry_id = promote.json()['result']['policy_pack']['catalog_entry_id']
            approve = client.post(
                f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/approve_cataloged_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
                headers=headers,
                json={'actor': 'governance-board', 'catalog_entry_id': entry_id},
            )
            assert approve.status_code == 200, approve.text
            stage = client.post(
                f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/stage_cataloged_simulation_custody_routing_policy_pack_release?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
                headers=headers,
                json={'actor': 'release-manager', 'catalog_entry_id': entry_id},
            )
            assert stage.status_code == 200, stage.text
            release = client.post(
                f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/release_cataloged_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
                headers=headers,
                json={'actor': 'release-manager', 'catalog_entry_id': entry_id},
            )
            assert release.status_code == 200, release.text
            assert release.json()['result']['policy_pack']['catalog_release_state'] == 'released'
            return entry_id

        entry_workspace = _promote_release_pack('family_hysteresis_presets', actor='operator-owner')
        entry_environment = _promote_release_pack('sla_expedite_presets', actor='operator-owner')
        entry_promotion = _promote_release_pack('admission_overload_presets', actor='operator-owner')

        bind_workspace = client.post(
            f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/bind_cataloged_simulation_custody_routing_policy_pack_effective_policy?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator-owner', 'catalog_entry_id': entry_workspace, 'binding_scope': 'workspace', 'note': 'workspace default pack'},
        )
        assert bind_workspace.status_code == 200, bind_workspace.text
        assert bind_workspace.json()['result']['binding']['binding_scope'] == 'workspace'

        bind_environment = client.post(
            f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/bind_cataloged_simulation_custody_routing_policy_pack_effective_policy?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator-owner', 'catalog_entry_id': entry_environment, 'binding_scope': 'environment', 'note': 'prod env pack'},
        )
        assert bind_environment.status_code == 200, bind_environment.text
        assert bind_environment.json()['result']['binding']['binding_scope'] == 'environment'

        bind_promotion = client.post(
            f'/admin/canvas/documents/{prod_canvas_id}/nodes/{prod_node_id}/actions/bind_cataloged_simulation_custody_routing_policy_pack_effective_policy?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator-prod', 'catalog_entry_id': entry_promotion, 'binding_scope': 'promotion', 'binding_promotion_id': prod_promotion_id, 'note': 'prod promotion-specific pack'},
        )
        assert bind_promotion.status_code == 200, bind_promotion.text
        assert bind_promotion.json()['result']['policy_pack']['catalog_is_effective_for_current_scope'] is True

        owner_inspector = client.get(f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod', headers=headers)
        owner_payload = owner_inspector.json()
        assert owner_payload['node']['data']['effective_routing_policy_pack_binding']['catalog_entry_id'] == entry_environment
        assert owner_payload['node']['data']['routing_policy_pack_binding_summary']['active_binding_count'] >= 2

        prod_inspector = client.get(f'/admin/canvas/documents/{prod_canvas_id}/nodes/{prod_node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod', headers=headers)
        prod_payload = prod_inspector.json()
        assert 'bind_cataloged_simulation_custody_routing_policy_pack_effective_policy' in prod_payload['available_actions']
        assert 'unbind_cataloged_simulation_custody_routing_policy_pack_effective_policy' in prod_payload['available_actions']
        assert prod_payload['node']['data']['effective_routing_policy_pack_binding']['catalog_entry_id'] == entry_promotion

        dev_inspector = client.get(f'/admin/canvas/documents/{dev_canvas_id}/nodes/{dev_node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=dev', headers=headers)
        dev_payload = dev_inspector.json()
        assert dev_payload['node']['data']['effective_routing_policy_pack_binding']['catalog_entry_id'] == entry_workspace

        replay_prod = client.post(
            f'/admin/canvas/documents/{prod_canvas_id}/nodes/{prod_node_id}/actions/replay_cataloged_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator-prod'},
        )
        assert replay_prod.status_code == 200, replay_prod.text
        assert replay_prod.json()['result']['routing_replay']['applied_pack']['catalog_entry_id'] == entry_promotion
        assert replay_prod.json()['result']['routing_replay']['applied_pack']['pack_id'] == 'admission_overload_presets'

        replay_owner = client.post(
            f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/replay_cataloged_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator-owner'},
        )
        assert replay_owner.status_code == 200, replay_owner.text
        assert replay_owner.json()['result']['routing_replay']['applied_pack']['catalog_entry_id'] == entry_environment
        assert replay_owner.json()['result']['routing_replay']['applied_pack']['pack_id'] == 'sla_expedite_presets'

        replay_dev = client.post(
            f'/admin/canvas/documents/{dev_canvas_id}/nodes/{dev_node_id}/actions/replay_cataloged_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=dev',
            headers=headers,
            json={'actor': 'operator-dev'},
        )
        assert replay_dev.status_code == 200, replay_dev.text
        assert replay_dev.json()['result']['routing_replay']['applied_pack']['catalog_entry_id'] == entry_workspace
        assert replay_dev.json()['result']['routing_replay']['applied_pack']['pack_id'] == 'family_hysteresis_presets'

        unbind_promotion = client.post(
            f'/admin/canvas/documents/{prod_canvas_id}/nodes/{prod_node_id}/actions/unbind_cataloged_simulation_custody_routing_policy_pack_effective_policy?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator-prod', 'binding_scope': 'promotion', 'binding_promotion_id': prod_promotion_id},
        )
        assert unbind_promotion.status_code == 200, unbind_promotion.text
        assert unbind_promotion.json()['result']['removed_bindings'][0]['catalog_entry_id'] == entry_promotion

        replay_prod_fallback = client.post(
            f'/admin/canvas/documents/{prod_canvas_id}/nodes/{prod_node_id}/actions/replay_cataloged_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator-prod'},
        )
        assert replay_prod_fallback.status_code == 200, replay_prod_fallback.text
        assert replay_prod_fallback.json()['result']['routing_replay']['applied_pack']['catalog_entry_id'] == entry_environment
        assert replay_prod_fallback.json()['result']['routing_replay']['applied_pack']['pack_id'] == 'sla_expedite_presets'


def test_canvas_cataloged_routing_policy_pack_drift_detection_and_compliance_reporting(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_700_000_700.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='baseline-routing-catalog-compliance',
            version='catalog-v1',
            environment_policy_baselines={'prod': _env_policy('baseline-v1')},
            promotion_policy={
                'simulation_custody_monitoring_policy': {
                    'enabled': True,
                    'auto_schedule': True,
                    'interval_s': 300,
                    'queue_capacity_policy': {
                        'enabled': True,
                        'default_capacity': 2,
                        'queue_families_enabled': True,
                        'default_queue_family': 'ops',
                        'multi_hop_hysteresis_enabled': True,
                        'breach_prediction_enabled': True,
                        'expedite_enabled': True,
                        'admission_control_enabled': True,
                        'overload_governance_enabled': True,
                    },
                    'routing_routes': [
                        {'route_id': 'ops-a-route', 'label': 'Ops A', 'queue_id': 'ops-a', 'queue_label': 'Ops A', 'queue_family_id': 'ops', 'owner_role': 'shift-lead', 'queue_capacity': 2, 'severity': 'warning'},
                        {'route_id': 'ops-b-route', 'label': 'Ops B', 'queue_id': 'ops-b', 'queue_label': 'Ops B', 'queue_family_id': 'ops', 'owner_role': 'shift-lead', 'queue_capacity': 2, 'severity': 'warning'},
                    ],
                    'default_route': {'route_id': 'ops-a-route', 'label': 'Ops A', 'queue_id': 'ops-a', 'queue_label': 'Ops A', 'queue_family_id': 'ops', 'owner_role': 'shift-lead', 'queue_capacity': 2},
                    'queue_capacities': [
                        {'queue_id': 'ops-a', 'queue_label': 'Ops A', 'capacity': 2, 'queue_family_id': 'ops'},
                        {'queue_id': 'ops-b', 'queue_label': 'Ops B', 'capacity': 2, 'queue_family_id': 'ops'},
                    ],
                },
            },
        )
        runtime_prod = _create_runtime_for_environment(client, headers, name='runtime-routing-compliance-prod', environment='prod')
        _create_portfolio_with_catalog(
            client,
            headers,
            base_now=base_now + 1,
            runtime_id=runtime_prod,
            environment='prod',
            environment_tier_policies=_env_policy('baseline-v2'),
            baseline_catalog_ref={'catalog_id': catalog['catalog_id']},
        )

        def _create_canvas_node(version: str, *, actor: str, title: str) -> tuple[str, str, str]:
            promotion = client.post(
                f'/admin/openclaw/alert-governance/baseline-catalogs/{catalog["catalog_id"]}/promotions',
                headers=headers,
                json={
                    'actor': actor,
                    'version': version,
                    'environment_policy_baselines': {'prod': {'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': version}}},
                    'tenant_id': 'tenant-a',
                    'workspace_id': 'ws-a',
                    'environment': 'prod',
                },
            )
            assert promotion.status_code == 200, promotion.text
            promotion_id = promotion.json()['promotion_id']
            canvas = client.post('/admin/canvas/documents', headers=headers, json={'actor': actor, 'title': title, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'})
            canvas_id = canvas.json()['document']['canvas_id']
            node = client.post(
                f'/admin/canvas/documents/{canvas_id}/nodes',
                headers=headers,
                json={'actor': actor, 'node_type': 'baseline_promotion', 'label': promotion_id, 'data': {'promotion_id': promotion_id}, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
            )
            node_id = node.json()['node']['node_id']
            simulate = client.post(
                f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/simulate?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
                headers=headers,
                json={'actor': actor},
            )
            assert simulate.status_code == 200, simulate.text
            return promotion_id, canvas_id, node_id

        _owner_promotion_id, owner_canvas_id, owner_node_id = _create_canvas_node('catalog-v2-compliance-owner', actor='operator-owner', title='routing compliance owner')
        _owner_secondary_promotion_id, owner_secondary_canvas_id, owner_secondary_node_id = _create_canvas_node('catalog-v2-compliance-owner-secondary', actor='operator-owner-2', title='routing compliance owner secondary')
        consumer_promotion_id, consumer_canvas_id, consumer_node_id = _create_canvas_node('catalog-v2-compliance-consumer', actor='operator-consumer', title='routing compliance consumer')

        def _promote_release_pack(pack_id: str, *, owner_canvas_id: str, owner_node_id: str) -> str:
            save = client.post(
                f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/save_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
                headers=headers,
                json={'actor': 'operator-owner', 'preset_pack_id': pack_id},
            )
            assert save.status_code == 200, save.text
            promote = client.post(
                f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/promote_simulation_custody_routing_policy_pack_to_catalog?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
                headers=headers,
                json={'actor': 'operator-owner', 'pack_id': pack_id, 'catalog_scope': 'global'},
            )
            assert promote.status_code == 200, promote.text
            entry_id = promote.json()['result']['policy_pack']['catalog_entry_id']
            approve = client.post(
                f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/approve_cataloged_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
                headers=headers,
                json={'actor': 'governance-board', 'catalog_entry_id': entry_id},
            )
            assert approve.status_code == 200, approve.text
            stage = client.post(
                f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/stage_cataloged_simulation_custody_routing_policy_pack_release?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
                headers=headers,
                json={'actor': 'release-manager', 'catalog_entry_id': entry_id},
            )
            assert stage.status_code == 200, stage.text
            release = client.post(
                f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/release_cataloged_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
                headers=headers,
                json={'actor': 'release-manager', 'catalog_entry_id': entry_id},
            )
            assert release.status_code == 200, release.text
            return entry_id

        entry_workspace = _promote_release_pack('family_hysteresis_presets', owner_canvas_id=owner_canvas_id, owner_node_id=owner_node_id)
        entry_promotion = _promote_release_pack('admission_overload_presets', owner_canvas_id=owner_secondary_canvas_id, owner_node_id=owner_secondary_node_id)

        bind_workspace = client.post(
            f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/bind_cataloged_simulation_custody_routing_policy_pack_effective_policy?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator-owner', 'catalog_entry_id': entry_workspace, 'binding_scope': 'workspace', 'note': 'workspace default routing pack'},
        )
        assert bind_workspace.status_code == 200, bind_workspace.text

        initial_replay = client.post(
            f'/admin/canvas/documents/{consumer_canvas_id}/nodes/{consumer_node_id}/actions/replay_cataloged_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator-consumer'},
        )
        assert initial_replay.status_code == 200, initial_replay.text
        assert initial_replay.json()['result']['routing_replay']['applied_pack']['catalog_entry_id'] == entry_workspace

        initial_inspector = client.get(
            f'/admin/canvas/documents/{consumer_canvas_id}/nodes/{consumer_node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        initial_payload = initial_inspector.json()
        assert initial_payload['node']['data']['routing_policy_pack_compliance_summary']['overall_status'] == 'conformant'
        assert initial_payload['node']['data']['effective_routing_policy_pack_binding']['catalog_entry_id'] == entry_workspace
        assert initial_payload['node']['data']['effective_routing_policy_pack_compliance']['catalog_entry_id'] == entry_workspace
        assert 'export_cataloged_simulation_custody_routing_policy_pack_compliance_report' in initial_payload['available_actions']

        bind_promotion = client.post(
            f'/admin/canvas/documents/{consumer_canvas_id}/nodes/{consumer_node_id}/actions/bind_cataloged_simulation_custody_routing_policy_pack_effective_policy?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={
                'actor': 'operator-consumer',
                'catalog_entry_id': entry_promotion,
                'binding_scope': 'promotion',
                'binding_promotion_id': consumer_promotion_id,
                'note': 'promotion override routing pack',
            },
        )
        assert bind_promotion.status_code == 200, bind_promotion.text

        drift_inspector = client.get(
            f'/admin/canvas/documents/{consumer_canvas_id}/nodes/{consumer_node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        drift_payload = drift_inspector.json()
        compliance_summary = drift_payload['node']['data']['routing_policy_pack_compliance_summary']
        assert compliance_summary['overall_status'] == 'drifted'
        assert compliance_summary['drifted_count'] >= 1
        assert drift_payload['node']['data']['effective_routing_policy_pack_binding']['catalog_entry_id'] == entry_promotion
        promotion_item = next(item for item in drift_payload['node']['data']['routing_policy_pack_catalog'] if item['catalog_entry_id'] == entry_promotion)
        assert 'effective_binding_usage_mismatch' in promotion_item['catalog_compliance_summary']['drift_reasons']

        compliance_report = client.post(
            f'/admin/canvas/documents/{consumer_canvas_id}/nodes/{consumer_node_id}/actions/export_cataloged_simulation_custody_routing_policy_pack_compliance_report?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'compliance-auditor', 'catalog_entry_id': entry_promotion},
        )
        assert compliance_report.status_code == 200, compliance_report.text
        compliance_result = compliance_report.json()['result']
        assert compliance_result['report']['report_type'] == 'openmiura_routing_policy_pack_catalog_compliance_report_v1'
        assert compliance_result['report']['compliance']['overall_status'] == 'drifted'
        assert compliance_result['report']['divergence_explainability']['expected_catalog_entry_id'] == entry_promotion
        assert compliance_result['report']['divergence_explainability']['actual_catalog_entry_id'] == entry_workspace
        assert compliance_result['policy_pack']['catalog_latest_compliance_report']['report_id'] == compliance_result['report']['report_id']

        aligned_replay = client.post(
            f'/admin/canvas/documents/{consumer_canvas_id}/nodes/{consumer_node_id}/actions/replay_cataloged_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator-consumer'},
        )
        assert aligned_replay.status_code == 200, aligned_replay.text
        assert aligned_replay.json()['result']['routing_replay']['applied_pack']['catalog_entry_id'] == entry_promotion
        assert aligned_replay.json()['result']['routing_replay']['applied_pack']['pack_id'] == 'admission_overload_presets'

        aligned_inspector = client.get(
            f'/admin/canvas/documents/{consumer_canvas_id}/nodes/{consumer_node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        aligned_payload = aligned_inspector.json()
        assert aligned_payload['node']['data']['routing_policy_pack_compliance_summary']['overall_status'] == 'conformant'
        assert aligned_payload['node']['data']['routing_policy_pack_compliance_summary']['drifted_count'] == 0
        assert aligned_payload['node']['data']['routing_policy_pack_compliance_summary']['last_used_catalog_entry_id'] == entry_promotion
        assert aligned_payload['node']['data']['effective_routing_policy_pack_compliance']['catalog_entry_id'] == entry_promotion

        aligned_report = client.post(
            f'/admin/canvas/documents/{consumer_canvas_id}/nodes/{consumer_node_id}/actions/export_cataloged_simulation_custody_routing_policy_pack_compliance_report?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'compliance-auditor', 'catalog_entry_id': entry_promotion},
        )
        assert aligned_report.status_code == 200, aligned_report.text
        aligned_result = aligned_report.json()['result']
        assert aligned_result['report']['compliance']['overall_status'] == 'conformant'
        assert aligned_result['policy_pack']['catalog_latest_compliance_report']['report_id'] == aligned_result['report']['report_id']
        assert aligned_result['report']['compliance_summary']['overall_status'] == 'conformant'


def test_canvas_cataloged_routing_policy_pack_rollback_supersedence_and_emergency_withdrawal_governance(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_796_900.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='baseline-routing-rollback-governance',
            version='catalog-v1',
            environment_policy_baselines={'prod': _env_policy('baseline-v1')},
            promotion_policy={
                'simulation_custody_monitoring_policy': {
                    'enabled': True,
                    'auto_schedule': True,
                    'interval_s': 300,
                    'queue_capacity_policy': {'enabled': True, 'default_capacity': 2},
                    'routing_routes': [
                        {'route_id': 'ops-a-route', 'label': 'Ops A', 'queue_id': 'ops-a', 'queue_label': 'Ops A', 'owner_role': 'shift-lead', 'queue_capacity': 2},
                        {'route_id': 'ops-b-route', 'label': 'Ops B', 'queue_id': 'ops-b', 'queue_label': 'Ops B', 'owner_role': 'shift-lead', 'queue_capacity': 2},
                    ],
                    'default_route': {'route_id': 'ops-a-route', 'label': 'Ops A', 'queue_id': 'ops-a', 'queue_label': 'Ops A', 'owner_role': 'shift-lead', 'queue_capacity': 2},
                    'queue_capacities': [
                        {'queue_id': 'ops-a', 'queue_label': 'Ops A', 'capacity': 2},
                        {'queue_id': 'ops-b', 'queue_label': 'Ops B', 'capacity': 2},
                    ],
                },
            },
        )
        runtime_id = _create_runtime_for_environment(client, headers, name='runtime-routing-rollback-governance', environment='prod')
        _create_portfolio_with_catalog(client, headers, base_now=base_now + 1, runtime_id=runtime_id, environment='prod', environment_tier_policies=_env_policy('baseline-v2'), baseline_catalog_ref={'catalog_id': catalog['catalog_id']})

        def _create_canvas_node(version: str, *, actor: str, title: str) -> tuple[str, str, str]:
            promotion = client.post(
                f'/admin/openclaw/alert-governance/baseline-catalogs/{catalog["catalog_id"]}/promotions',
                headers=headers,
                json={
                    'actor': actor,
                    'version': version,
                    'environment_policy_baselines': {'prod': {'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': version}}},
                    'tenant_id': 'tenant-a',
                    'workspace_id': 'ws-a',
                    'environment': 'prod',
                },
            )
            assert promotion.status_code == 200, promotion.text
            promotion_id = promotion.json()['promotion_id']
            canvas = client.post('/admin/canvas/documents', headers=headers, json={'actor': actor, 'title': title, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'})
            canvas_id = canvas.json()['document']['canvas_id']
            node = client.post(
                f'/admin/canvas/documents/{canvas_id}/nodes',
                headers=headers,
                json={'actor': actor, 'node_type': 'baseline_promotion', 'label': promotion_id, 'data': {'promotion_id': promotion_id}, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
            )
            node_id = node.json()['node']['node_id']
            simulate = client.post(
                f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/simulate?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
                headers=headers,
                json={'actor': actor},
            )
            assert simulate.status_code == 200, simulate.text
            return promotion_id, canvas_id, node_id

        _owner_promotion_id, owner_canvas_id, owner_node_id = _create_canvas_node('catalog-v2-rollback-owner', actor='operator-owner', title='routing rollback owner')
        consumer_promotion_id, consumer_canvas_id, consumer_node_id = _create_canvas_node('catalog-v2-rollback-consumer', actor='operator-consumer', title='routing rollback consumer')

        def _promote_release_pack(owner_canvas_id: str, owner_node_id: str, *, actor: str) -> str:
            save = client.post(
                f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/save_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
                headers=headers,
                json={'actor': actor, 'preset_pack_id': 'family_hysteresis_presets'},
            )
            assert save.status_code == 200, save.text
            promote = client.post(
                f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/promote_simulation_custody_routing_policy_pack_to_catalog?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
                headers=headers,
                json={'actor': actor, 'pack_id': 'family_hysteresis_presets', 'catalog_scope': 'global'},
            )
            assert promote.status_code == 200, promote.text
            entry_id = promote.json()['result']['policy_pack']['catalog_entry_id']
            approve = client.post(
                f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/approve_cataloged_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
                headers=headers,
                json={'actor': 'governance-board', 'catalog_entry_id': entry_id},
            )
            assert approve.status_code == 200, approve.text
            stage = client.post(
                f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/stage_cataloged_simulation_custody_routing_policy_pack_release?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
                headers=headers,
                json={'actor': 'release-manager', 'catalog_entry_id': entry_id},
            )
            assert stage.status_code == 200, stage.text
            release = client.post(
                f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/release_cataloged_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
                headers=headers,
                json={'actor': 'release-manager', 'catalog_entry_id': entry_id},
            )
            assert release.status_code == 200, release.text
            return entry_id

        entry_v1 = _promote_release_pack(owner_canvas_id, owner_node_id, actor='operator-owner')
        bind_v1 = client.post(
            f'/admin/canvas/documents/{consumer_canvas_id}/nodes/{consumer_node_id}/actions/bind_cataloged_simulation_custody_routing_policy_pack_effective_policy?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator-consumer', 'catalog_entry_id': entry_v1, 'binding_scope': 'promotion', 'binding_promotion_id': consumer_promotion_id},
        )
        assert bind_v1.status_code == 200, bind_v1.text
        replay_v1 = client.post(
            f'/admin/canvas/documents/{consumer_canvas_id}/nodes/{consumer_node_id}/actions/replay_cataloged_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator-consumer'},
        )
        assert replay_v1.status_code == 200, replay_v1.text
        assert replay_v1.json()['result']['routing_replay']['applied_pack']['catalog_entry_id'] == entry_v1

        entry_v2 = _promote_release_pack(owner_canvas_id, owner_node_id, actor='operator-owner')
        owner_after_release = client.get(
            f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        owner_after_release_payload = owner_after_release.json()
        pack_v1_after = next(item for item in owner_after_release_payload['node']['data']['routing_policy_pack_catalog'] if item['catalog_entry_id'] == entry_v1)
        pack_v2_after = next(item for item in owner_after_release_payload['node']['data']['routing_policy_pack_catalog'] if item['catalog_entry_id'] == entry_v2)
        assert pack_v1_after['catalog_release_state'] == 'withdrawn'
        assert pack_v1_after['catalog_supersedence_summary']['state'] == 'superseded'
        assert pack_v1_after['catalog_supersedence_summary']['superseded_by_entry_id'] == entry_v2
        assert pack_v2_after['catalog_supersedence_summary']['supersedes_entry_id'] == entry_v1

        bind_v2 = client.post(
            f'/admin/canvas/documents/{consumer_canvas_id}/nodes/{consumer_node_id}/actions/bind_cataloged_simulation_custody_routing_policy_pack_effective_policy?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator-consumer', 'catalog_entry_id': entry_v2, 'binding_scope': 'promotion', 'binding_promotion_id': consumer_promotion_id},
        )
        assert bind_v2.status_code == 200, bind_v2.text
        replay_v2 = client.post(
            f'/admin/canvas/documents/{consumer_canvas_id}/nodes/{consumer_node_id}/actions/replay_cataloged_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator-consumer'},
        )
        assert replay_v2.status_code == 200, replay_v2.text
        assert replay_v2.json()['result']['routing_replay']['applied_pack']['catalog_entry_id'] == entry_v2

        emergency = client.post(
            f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/emergency_withdraw_cataloged_simulation_custody_routing_policy_pack_release?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'incident-commander', 'catalog_entry_id': entry_v2, 'catalog_emergency_withdrawal_reason': 'critical routing defect', 'incident_id': 'INC-4242', 'severity': 'critical'},
        )
        assert emergency.status_code == 200, emergency.text
        emergency_pack = emergency.json()['result']['policy_pack']
        assert emergency_pack['catalog_release_state'] == 'withdrawn'
        assert emergency_pack['catalog_emergency_withdrawal_summary']['active'] is True
        assert emergency_pack['catalog_emergency_withdrawal_summary']['incident_id'] == 'INC-4242'

        blocked_replay = client.post(
            f'/admin/canvas/documents/{consumer_canvas_id}/nodes/{consumer_node_id}/actions/replay_cataloged_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator-consumer'},
        )
        assert blocked_replay.status_code == 200, blocked_replay.text
        assert blocked_replay.json()['result']['ok'] is False
        assert blocked_replay.json()['result']['error'] in {'catalog_rollout_withdrawn', 'baseline_promotion_simulation_custody_policy_pack_missing'}

        rollback_release = client.post(
            f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/rollback_cataloged_simulation_custody_routing_policy_pack_release?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'release-manager', 'catalog_entry_id': entry_v2, 'catalog_rollback_release_reason': 'restore previous stable release'},
        )
        assert rollback_release.status_code == 200, rollback_release.text
        rollback_payload = rollback_release.json()['result']
        assert rollback_payload['policy_pack']['catalog_release_rollback_summary']['state'] == 'rolled_back_to_previous_release'
        assert rollback_payload['policy_pack']['catalog_release_rollback_summary']['target_entry_id'] == entry_v1

        consumer_after = client.get(
            f'/admin/canvas/documents/{consumer_canvas_id}/nodes/{consumer_node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        consumer_after_payload = consumer_after.json()
        assert consumer_after_payload['node']['data']['effective_routing_policy_pack_binding']['catalog_entry_id'] == entry_v1
        assert consumer_after_payload['node']['data']['effective_routing_policy_pack_binding']['rebound_reason'] == 'restore previous stable release'
        consumer_pack_v1 = next(item for item in consumer_after_payload['node']['data']['routing_policy_pack_catalog'] if item['catalog_entry_id'] == entry_v1)
        consumer_pack_v2 = next(item for item in consumer_after_payload['node']['data']['routing_policy_pack_catalog'] if item['catalog_entry_id'] == entry_v2)
        assert consumer_pack_v1['catalog_release_state'] == 'released'
        assert consumer_pack_v1['catalog_supersedence_summary']['restored_from_entry_id'] == entry_v2
        assert consumer_pack_v2['catalog_release_state'] == 'withdrawn'
        assert consumer_pack_v2['catalog_release_rollback_summary']['target_entry_id'] == entry_v1

        replay_restored = client.post(
            f'/admin/canvas/documents/{consumer_canvas_id}/nodes/{consumer_node_id}/actions/replay_cataloged_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator-consumer'},
        )
        assert replay_restored.status_code == 200, replay_restored.text
        assert replay_restored.json()['result']['routing_replay']['applied_pack']['catalog_entry_id'] == entry_v1


def test_canvas_cataloged_routing_policy_pack_analytics_and_operator_dashboard(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_797_400.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='baseline-routing-catalog-analytics',
            version='catalog-v1',
            environment_policy_baselines={'prod': _env_policy('baseline-v1')},
            promotion_policy={
                'simulation_custody_monitoring_policy': {
                    'enabled': True,
                    'auto_schedule': True,
                    'interval_s': 300,
                    'queue_capacity_policy': {
                        'enabled': True,
                        'default_capacity': 2,
                        'queue_families_enabled': True,
                        'default_queue_family': 'ops',
                        'multi_hop_hysteresis_enabled': True,
                        'breach_prediction_enabled': True,
                        'expedite_enabled': True,
                        'admission_control_enabled': True,
                        'overload_governance_enabled': True,
                    },
                    'routing_routes': [
                        {'route_id': 'ops-a-route', 'label': 'Ops A', 'queue_id': 'ops-a', 'queue_label': 'Ops A', 'queue_family_id': 'ops', 'owner_role': 'shift-lead', 'queue_capacity': 2, 'severity': 'warning'},
                        {'route_id': 'ops-b-route', 'label': 'Ops B', 'queue_id': 'ops-b', 'queue_label': 'Ops B', 'queue_family_id': 'ops', 'owner_role': 'shift-lead', 'queue_capacity': 2, 'severity': 'warning'},
                    ],
                    'default_route': {'route_id': 'ops-a-route', 'label': 'Ops A', 'queue_id': 'ops-a', 'queue_label': 'Ops A', 'queue_family_id': 'ops', 'owner_role': 'shift-lead', 'queue_capacity': 2},
                    'queue_capacities': [
                        {'queue_id': 'ops-a', 'queue_label': 'Ops A', 'capacity': 2, 'queue_family_id': 'ops'},
                        {'queue_id': 'ops-b', 'queue_label': 'Ops B', 'capacity': 2, 'queue_family_id': 'ops'},
                    ],
                },
            },
        )
        runtime_id = _create_runtime_for_environment(client, headers, name='runtime-routing-pack-analytics', environment='prod')
        _create_portfolio_with_catalog(
            client,
            headers,
            base_now=base_now + 1,
            runtime_id=runtime_id,
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
                'environment_policy_baselines': {'prod': {'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'catalog-v2'}}},
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert promotion.status_code == 200, promotion.text
        promotion_id = promotion.json()['promotion_id']

        canvas = client.post(
            '/admin/canvas/documents',
            headers=headers,
            json={'actor': 'operator-a', 'title': 'catalog analytics canvas', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        canvas_id = canvas.json()['document']['canvas_id']
        node = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes',
            headers=headers,
            json={'actor': 'operator-a', 'node_type': 'baseline_promotion', 'label': promotion_id, 'data': {'promotion_id': promotion_id}, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        node_id = node.json()['node']['node_id']

        simulate = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/simulate?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator-a'},
        )
        assert simulate.status_code == 200, simulate.text
        save = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/save_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator-a', 'preset_pack_id': 'family_hysteresis_presets'},
        )
        assert save.status_code == 200, save.text
        promote = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/promote_simulation_custody_routing_policy_pack_to_catalog?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator-a', 'pack_id': 'family_hysteresis_presets', 'catalog_scope': 'global'},
        )
        assert promote.status_code == 200, promote.text
        entry_id = promote.json()['result']['policy_pack']['catalog_entry_id']

        approve = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/approve_cataloged_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'governance-board', 'catalog_entry_id': entry_id},
        )
        assert approve.status_code == 200, approve.text
        stage = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/stage_cataloged_simulation_custody_routing_policy_pack_release?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'release-manager', 'catalog_entry_id': entry_id},
        )
        assert stage.status_code == 200, stage.text
        release = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/release_cataloged_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'release-manager', 'catalog_entry_id': entry_id},
        )
        assert release.status_code == 200, release.text

        bind = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/bind_cataloged_simulation_custody_routing_policy_pack_effective_policy?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator-a', 'catalog_entry_id': entry_id, 'binding_scope': 'workspace', 'note': 'workspace default for analytics'},
        )
        assert bind.status_code == 200, bind.text

        replay_one = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/replay_cataloged_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator-a'},
        )
        assert replay_one.status_code == 200, replay_one.text
        assert replay_one.json()['result']['routing_replay']['applied_pack']['catalog_entry_id'] == entry_id

        replay_two = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/replay_cataloged_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator-a', 'catalog_entry_id': entry_id},
        )
        assert replay_two.status_code == 200, replay_two.text
        assert replay_two.json()['result']['routing_replay']['applied_pack']['catalog_entry_id'] == entry_id

        share = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/share_cataloged_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator-a', 'catalog_entry_id': entry_id, 'target_pack_id': 'family_hysteresis_presets_analytics_shared'},
        )
        assert share.status_code == 200, share.text
        assert share.json()['result']['policy_pack']['source'] == 'shared_catalog'

        inspector_before_export = client.get(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert inspector_before_export.status_code == 200, inspector_before_export.text
        inspector_before_payload = inspector_before_export.json()
        assert 'export_cataloged_simulation_custody_routing_policy_pack_analytics_report' in inspector_before_payload['available_actions']
        analytics_before = inspector_before_payload['node']['data']['routing_policy_pack_analytics_summary']
        dashboard_before = inspector_before_payload['node']['data']['routing_policy_pack_operator_dashboard']
        assert analytics_before['total_replay_count'] >= 2
        assert analytics_before['total_share_count'] >= 1
        assert analytics_before['active_binding_count'] >= 1
        assert dashboard_before['dashboard_type'] == 'openmiura_routing_policy_pack_operator_dashboard_v1'
        catalog_pack_before = next(item for item in inspector_before_payload['node']['data']['routing_policy_pack_catalog'] if item['catalog_entry_id'] == entry_id)
        assert catalog_pack_before['catalog_replay_count'] >= 2
        assert catalog_pack_before['catalog_share_count'] >= 1
        assert catalog_pack_before['catalog_binding_count'] >= 1
        assert catalog_pack_before['catalog_analytics_summary']['replay_count'] >= 2

        export_analytics = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/export_cataloged_simulation_custody_routing_policy_pack_analytics_report?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'analytics-auditor', 'catalog_entry_id': entry_id},
        )
        assert export_analytics.status_code == 200, export_analytics.text
        analytics_result = export_analytics.json()['result']
        assert analytics_result['report']['report_type'] == 'openmiura_routing_policy_pack_catalog_analytics_report_v1'
        assert analytics_result['report']['pack_analytics']['catalog_entry_id'] == entry_id
        assert analytics_result['report']['pack_analytics']['replay_count'] >= 2
        assert analytics_result['report']['pack_analytics']['share_count'] >= 1
        assert analytics_result['report']['pack_analytics']['active_binding_count'] >= 1
        assert analytics_result['report']['catalog_analytics_summary']['total_replay_count'] >= 2
        assert analytics_result['report']['catalog_analytics_summary']['total_share_count'] >= 1
        assert analytics_result['report']['operator_dashboard']['dashboard_type'] == 'openmiura_routing_policy_pack_operator_dashboard_v1'
        assert analytics_result['integrity']['signed'] is True
        assert analytics_result['policy_pack']['catalog_latest_analytics_report']['report_id'] == analytics_result['report']['report_id']

        inspector_after_export = client.get(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert inspector_after_export.status_code == 200, inspector_after_export.text
        inspector_after_payload = inspector_after_export.json()
        analytics_after = inspector_after_payload['node']['data']['routing_policy_pack_analytics_summary']
        assert analytics_after['analytics_reported_count'] >= 1
        assert analytics_after['total_replay_count'] >= 2
        assert analytics_after['total_share_count'] >= 1
        assert inspector_after_payload['node']['data']['routing_policy_pack_catalog_summary']['analytics_reported_count'] >= 1
        assert inspector_after_payload['related']['routing_policy_pack_analytics']['dashboard']['dashboard_type'] == 'openmiura_routing_policy_pack_operator_dashboard_v1'
        catalog_pack_after = next(item for item in inspector_after_payload['node']['data']['routing_policy_pack_catalog'] if item['catalog_entry_id'] == entry_id)
        assert catalog_pack_after['catalog_analytics_report_count'] >= 1
        assert catalog_pack_after['catalog_latest_analytics_report']['report_type'] == 'openmiura_routing_policy_pack_catalog_analytics_report_v1'
        assert inspector_after_payload['node']['data']['last_catalog_analytics_report_routing_policy_pack']['catalog_entry_id'] == entry_id


def test_canvas_cataloged_routing_policy_pack_externalized_registry_and_organizational_catalog_service(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_798_200.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='baseline-routing-catalog-organizational-service',
            version='catalog-v1',
            environment_policy_baselines={'prod': _env_policy('baseline-v1')},
            promotion_policy={
                'simulation_custody_monitoring_policy': {
                    'enabled': True,
                    'auto_schedule': True,
                    'interval_s': 300,
                    'queue_capacity_policy': {
                        'enabled': True,
                        'default_capacity': 2,
                        'queue_families_enabled': True,
                        'default_queue_family': 'ops',
                        'multi_hop_hysteresis_enabled': True,
                        'breach_prediction_enabled': True,
                        'expedite_enabled': True,
                        'admission_control_enabled': True,
                        'overload_governance_enabled': True,
                    },
                    'routing_routes': [
                        {'route_id': 'ops-a-route', 'label': 'Ops A', 'queue_id': 'ops-a', 'queue_label': 'Ops A', 'queue_family_id': 'ops', 'owner_role': 'shift-lead', 'queue_capacity': 2, 'severity': 'warning'},
                        {'route_id': 'ops-b-route', 'label': 'Ops B', 'queue_id': 'ops-b', 'queue_label': 'Ops B', 'queue_family_id': 'ops', 'owner_role': 'shift-lead', 'queue_capacity': 2, 'severity': 'warning'},
                    ],
                    'default_route': {'route_id': 'ops-a-route', 'label': 'Ops A', 'queue_id': 'ops-a', 'queue_label': 'Ops A', 'queue_family_id': 'ops', 'owner_role': 'shift-lead', 'queue_capacity': 2},
                    'queue_capacities': [
                        {'queue_id': 'ops-a', 'queue_label': 'Ops A', 'capacity': 2, 'queue_family_id': 'ops'},
                        {'queue_id': 'ops-b', 'queue_label': 'Ops B', 'capacity': 2, 'queue_family_id': 'ops'},
                    ],
                },
            },
        )
        runtime_owner = _create_runtime_for_environment(client, headers, name='runtime-routing-pack-owner', environment='prod')
        runtime_consumer = _create_runtime_for_environment(client, headers, name='runtime-routing-pack-consumer', environment='prod')
        _create_portfolio_with_catalog(
            client,
            headers,
            base_now=base_now + 1,
            runtime_id=runtime_owner,
            environment='prod',
            environment_tier_policies=_env_policy('baseline-v2'),
            baseline_catalog_ref={'catalog_id': catalog['catalog_id']},
        )
        _create_portfolio_with_catalog(
            client,
            headers,
            base_now=base_now + 2,
            runtime_id=runtime_consumer,
            environment='prod',
            environment_tier_policies=_env_policy('baseline-v2'),
            baseline_catalog_ref={'catalog_id': catalog['catalog_id']},
        )

        owner_promotion = client.post(
            f'/admin/openclaw/alert-governance/baseline-catalogs/{catalog["catalog_id"]}/promotions',
            headers=headers,
            json={
                'actor': 'catalog-admin',
                'version': 'catalog-v2',
                'environment_policy_baselines': {'prod': {'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'catalog-v2'}}},
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert owner_promotion.status_code == 200, owner_promotion.text
        owner_promotion_id = owner_promotion.json()['promotion_id']

        consumer_promotion_id = owner_promotion_id

        owner_canvas = client.post(
            '/admin/canvas/documents',
            headers=headers,
            json={'actor': 'operator-owner', 'title': 'catalog org owner', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        owner_canvas_id = owner_canvas.json()['document']['canvas_id']
        owner_node = client.post(
            f'/admin/canvas/documents/{owner_canvas_id}/nodes',
            headers=headers,
            json={'actor': 'operator-owner', 'node_type': 'baseline_promotion', 'label': owner_promotion_id, 'data': {'promotion_id': owner_promotion_id}, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        owner_node_id = owner_node.json()['node']['node_id']

        consumer_canvas = client.post(
            '/admin/canvas/documents',
            headers=headers,
            json={'actor': 'operator-consumer', 'title': 'catalog org consumer', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        consumer_canvas_id = consumer_canvas.json()['document']['canvas_id']
        consumer_node = client.post(
            f'/admin/canvas/documents/{consumer_canvas_id}/nodes',
            headers=headers,
            json={'actor': 'operator-consumer', 'node_type': 'baseline_promotion', 'label': consumer_promotion_id, 'data': {'promotion_id': consumer_promotion_id}, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        consumer_node_id = consumer_node.json()['node']['node_id']

        simulate = client.post(
            f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/simulate?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator-owner'},
        )
        assert simulate.status_code == 200, simulate.text
        save = client.post(
            f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/save_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator-owner', 'preset_pack_id': 'family_hysteresis_presets'},
        )
        assert save.status_code == 200, save.text
        promote = client.post(
            f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/promote_simulation_custody_routing_policy_pack_to_catalog?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator-owner', 'pack_id': 'family_hysteresis_presets', 'catalog_scope': 'global'},
        )
        assert promote.status_code == 200, promote.text
        entry_id = promote.json()['result']['policy_pack']['catalog_entry_id']

        approve = client.post(
            f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/approve_cataloged_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'governance-board', 'catalog_entry_id': entry_id},
        )
        assert approve.status_code == 200, approve.text
        stage = client.post(
            f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/stage_cataloged_simulation_custody_routing_policy_pack_release?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'release-manager', 'catalog_entry_id': entry_id},
        )
        assert stage.status_code == 200, stage.text
        release = client.post(
            f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/release_cataloged_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'release-manager', 'catalog_entry_id': entry_id},
        )
        assert release.status_code == 200, release.text

        publish = client.post(
            f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/publish_cataloged_simulation_custody_routing_policy_pack_to_organizational_catalog_service?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'release-manager', 'catalog_entry_id': entry_id, 'organizational_visibility': 'tenant'},
        )
        assert publish.status_code == 200, publish.text
        publish_result = publish.json()['result']
        assert publish_result['policy_pack']['organizational_publish_state'] == 'published'
        service_entry_id = publish_result['policy_pack']['organizational_service_entry_id']
        assert service_entry_id

        consumer_inspector = client.get(
            f'/admin/canvas/documents/{consumer_canvas_id}/nodes/{consumer_node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert consumer_inspector.status_code == 200, consumer_inspector.text
        consumer_payload = consumer_inspector.json()
        assert 'replay_organizational_simulation_custody_routing_policy_pack' in consumer_payload['available_actions']
        assert 'export_organizational_simulation_custody_routing_policy_pack_catalog_service_snapshot' in consumer_payload['available_actions']
        organizational_summary = consumer_payload['node']['data']['routing_policy_pack_organizational_catalog_service_summary']
        assert organizational_summary['published_entry_count'] >= 1
        organizational_entries = consumer_payload['node']['data']['routing_policy_pack_organizational_catalog_service']['entries']
        assert any(item['organizational_service_entry_id'] == service_entry_id for item in organizational_entries)

        organizational_replay = client.post(
            f'/admin/canvas/documents/{consumer_canvas_id}/nodes/{consumer_node_id}/actions/replay_organizational_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator-consumer', 'organizational_service_entry_id': service_entry_id},
        )
        assert organizational_replay.status_code == 200, organizational_replay.text
        replay_result = organizational_replay.json()['result']
        assert replay_result['routing_replay']['applied_pack']['catalog_entry_id'] == entry_id
        assert replay_result['routing_replay']['applied_pack']['organizational_service_entry_id'] == service_entry_id

        export_snapshot = client.post(
            f'/admin/canvas/documents/{consumer_canvas_id}/nodes/{consumer_node_id}/actions/export_organizational_simulation_custody_routing_policy_pack_catalog_service_snapshot?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'catalog-auditor'},
        )
        assert export_snapshot.status_code == 200, export_snapshot.text
        snapshot_result = export_snapshot.json()['result']
        assert snapshot_result['report']['report_type'] == 'openmiura_routing_policy_pack_organizational_catalog_snapshot_v1'
        assert snapshot_result['report']['summary']['published_entry_count'] >= 1
        assert snapshot_result['integrity']['signed'] is True

        withdraw = client.post(
            f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/withdraw_cataloged_simulation_custody_routing_policy_pack_from_organizational_catalog_service?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'release-manager', 'catalog_entry_id': entry_id, 'organizational_withdraw_reason': 'retire externalized publication'},
        )
        assert withdraw.status_code == 200, withdraw.text
        withdraw_result = withdraw.json()['result']
        assert withdraw_result['policy_pack']['organizational_publish_state'] == 'withdrawn'

        consumer_after_withdraw = client.get(
            f'/admin/canvas/documents/{consumer_canvas_id}/nodes/{consumer_node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert consumer_after_withdraw.status_code == 200, consumer_after_withdraw.text
        assert consumer_after_withdraw.json()['node']['data']['routing_policy_pack_organizational_catalog_service_summary']['published_entry_count'] == 0

        replay_after_withdraw = client.post(
            f'/admin/canvas/documents/{consumer_canvas_id}/nodes/{consumer_node_id}/actions/replay_organizational_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator-consumer', 'organizational_service_entry_id': service_entry_id},
        )
        assert replay_after_withdraw.status_code == 200, replay_after_withdraw.text
        replay_after_withdraw_payload = replay_after_withdraw.json()
        assert replay_after_withdraw_payload['ok'] is False
        assert replay_after_withdraw_payload['error'] == 'action_blocked'
        assert replay_after_withdraw_payload['precheck']['reason'] == 'baseline_promotion_simulation_custody_organizational_policy_pack_missing'


def test_canvas_cataloged_routing_policy_pack_organizational_catalog_reconciliation_and_publication_health(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_798_600.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        catalog = _create_baseline_catalog(
            client,
            headers,
            name='baseline-routing-catalog-organizational-reconciliation',
            version='catalog-v1',
            environment_policy_baselines={'prod': _env_policy('baseline-v1')},
            promotion_policy={
                'simulation_custody_monitoring_policy': {
                    'enabled': True,
                    'auto_schedule': True,
                    'interval_s': 300,
                    'queue_capacity_policy': {
                        'enabled': True,
                        'default_capacity': 2,
                        'queue_families_enabled': True,
                        'default_queue_family': 'ops',
                        'multi_hop_hysteresis_enabled': True,
                        'breach_prediction_enabled': True,
                        'expedite_enabled': True,
                        'admission_control_enabled': True,
                        'overload_governance_enabled': True,
                    },
                    'routing_routes': [
                        {'route_id': 'ops-a-route', 'label': 'Ops A', 'queue_id': 'ops-a', 'queue_label': 'Ops A', 'queue_family_id': 'ops', 'owner_role': 'shift-lead', 'queue_capacity': 2, 'severity': 'warning'},
                        {'route_id': 'ops-b-route', 'label': 'Ops B', 'queue_id': 'ops-b', 'queue_label': 'Ops B', 'queue_family_id': 'ops', 'owner_role': 'shift-lead', 'queue_capacity': 2, 'severity': 'warning'},
                    ],
                    'default_route': {'route_id': 'ops-a-route', 'label': 'Ops A', 'queue_id': 'ops-a', 'queue_label': 'Ops A', 'queue_family_id': 'ops', 'owner_role': 'shift-lead', 'queue_capacity': 2},
                    'queue_capacities': [
                        {'queue_id': 'ops-a', 'queue_label': 'Ops A', 'capacity': 2, 'queue_family_id': 'ops'},
                        {'queue_id': 'ops-b', 'queue_label': 'Ops B', 'capacity': 2, 'queue_family_id': 'ops'},
                    ],
                },
            },
        )
        runtime_owner = _create_runtime_for_environment(client, headers, name='runtime-routing-pack-owner-reconcile', environment='prod')
        runtime_consumer = _create_runtime_for_environment(client, headers, name='runtime-routing-pack-consumer-reconcile', environment='prod')
        _create_portfolio_with_catalog(
            client,
            headers,
            base_now=base_now + 1,
            runtime_id=runtime_owner,
            environment='prod',
            environment_tier_policies=_env_policy('baseline-v2'),
            baseline_catalog_ref={'catalog_id': catalog['catalog_id']},
        )
        _create_portfolio_with_catalog(
            client,
            headers,
            base_now=base_now + 2,
            runtime_id=runtime_consumer,
            environment='prod',
            environment_tier_policies=_env_policy('baseline-v2'),
            baseline_catalog_ref={'catalog_id': catalog['catalog_id']},
        )

        promotion_response = client.post(
            f'/admin/openclaw/alert-governance/baseline-catalogs/{catalog["catalog_id"]}/promotions',
            headers=headers,
            json={
                'actor': 'catalog-admin',
                'version': 'catalog-v2',
                'environment_policy_baselines': {'prod': {'signing_policy': {'enabled': True, 'provider': 'local-ed25519', 'key_id': 'catalog-v2'}}},
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert promotion_response.status_code == 200, promotion_response.text
        promotion_id = promotion_response.json()['promotion_id']

        owner_canvas = client.post(
            '/admin/canvas/documents',
            headers=headers,
            json={'actor': 'operator-owner', 'title': 'catalog org reconcile owner', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        owner_canvas_id = owner_canvas.json()['document']['canvas_id']
        owner_node = client.post(
            f'/admin/canvas/documents/{owner_canvas_id}/nodes',
            headers=headers,
            json={'actor': 'operator-owner', 'node_type': 'baseline_promotion', 'label': promotion_id, 'data': {'promotion_id': promotion_id}, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        owner_node_id = owner_node.json()['node']['node_id']

        consumer_canvas = client.post(
            '/admin/canvas/documents',
            headers=headers,
            json={'actor': 'operator-consumer', 'title': 'catalog org reconcile consumer', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        consumer_canvas_id = consumer_canvas.json()['document']['canvas_id']
        consumer_node = client.post(
            f'/admin/canvas/documents/{consumer_canvas_id}/nodes',
            headers=headers,
            json={'actor': 'operator-consumer', 'node_type': 'baseline_promotion', 'label': promotion_id, 'data': {'promotion_id': promotion_id}, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        consumer_node_id = consumer_node.json()['node']['node_id']

        simulate = client.post(
            f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/simulate?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator-owner'},
        )
        assert simulate.status_code == 200, simulate.text
        save = client.post(
            f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/save_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator-owner', 'preset_pack_id': 'family_hysteresis_presets'},
        )
        assert save.status_code == 200, save.text
        promote = client.post(
            f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/promote_simulation_custody_routing_policy_pack_to_catalog?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'operator-owner', 'pack_id': 'family_hysteresis_presets', 'catalog_scope': 'global'},
        )
        assert promote.status_code == 200, promote.text
        entry_id = promote.json()['result']['policy_pack']['catalog_entry_id']

        approve = client.post(
            f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/approve_cataloged_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'governance-board', 'catalog_entry_id': entry_id},
        )
        assert approve.status_code == 200, approve.text
        stage = client.post(
            f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/stage_cataloged_simulation_custody_routing_policy_pack_release?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'release-manager', 'catalog_entry_id': entry_id},
        )
        assert stage.status_code == 200, stage.text
        release = client.post(
            f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/release_cataloged_simulation_custody_routing_policy_pack?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'release-manager', 'catalog_entry_id': entry_id},
        )
        assert release.status_code == 200, release.text
        publish = client.post(
            f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/publish_cataloged_simulation_custody_routing_policy_pack_to_organizational_catalog_service?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'release-manager', 'catalog_entry_id': entry_id, 'organizational_visibility': 'tenant'},
        )
        assert publish.status_code == 200, publish.text
        service_entry_id = publish.json()['result']['policy_pack']['organizational_service_entry_id']
        assert publish.json()['result']['policy_pack']['organizational_publication_manifest']['manifest_digest']

        emergency_withdraw = client.post(
            f'/admin/canvas/documents/{owner_canvas_id}/nodes/{owner_node_id}/actions/emergency_withdraw_cataloged_simulation_custody_routing_policy_pack_release?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'incident-commander', 'catalog_entry_id': entry_id, 'reason': 'routing incident', 'incident_id': 'INC-42', 'severity': 'sev1'},
        )
        assert emergency_withdraw.status_code == 200, emergency_withdraw.text

        consumer_inspector = client.get(
            f'/admin/canvas/documents/{consumer_canvas_id}/nodes/{consumer_node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert consumer_inspector.status_code == 200, consumer_inspector.text
        consumer_payload = consumer_inspector.json()
        assert 'reconcile_organizational_simulation_custody_routing_policy_pack_catalog_service' in consumer_payload['available_actions']
        assert 'export_organizational_simulation_custody_routing_policy_pack_catalog_service_reconciliation_report' in consumer_payload['available_actions']
        organizational_summary = consumer_payload['node']['data']['routing_policy_pack_organizational_catalog_service_summary']
        assert organizational_summary['drifted_publication_count'] >= 1
        assert organizational_summary['publication_health_counts']['drifted'] >= 1
        organizational_entries = consumer_payload['node']['data']['routing_policy_pack_organizational_catalog_service']['entries']
        affected_entry = next(item for item in organizational_entries if item['organizational_service_entry_id'] == service_entry_id)
        health = affected_entry['organizational_publication_health']
        assert health['status'] == 'drifted'
        assert 'release_state_drift' in health['issue_codes']
        assert 'publication_manifest_drift' in health['issue_codes']

        reconcile = client.post(
            f'/admin/canvas/documents/{consumer_canvas_id}/nodes/{consumer_node_id}/actions/reconcile_organizational_simulation_custody_routing_policy_pack_catalog_service?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'catalog-auditor'},
        )
        assert reconcile.status_code == 200, reconcile.text
        reconcile_result = reconcile.json()['result']
        assert reconcile_result['report']['report_type'] == 'openmiura_routing_policy_pack_organizational_catalog_reconciliation_report_v1'
        assert reconcile_result['reconciliation_summary']['overall_status'] == 'drifted'
        assert reconcile_result['reconciliation_summary']['drifted_publication_count'] >= 1
        assert reconcile_result['integrity']['signed'] is True

        export_reconciliation = client.post(
            f'/admin/canvas/documents/{consumer_canvas_id}/nodes/{consumer_node_id}/actions/export_organizational_simulation_custody_routing_policy_pack_catalog_service_reconciliation_report?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'catalog-auditor'},
        )
        assert export_reconciliation.status_code == 200, export_reconciliation.text
        export_result = export_reconciliation.json()['result']
        assert export_result['report']['report_type'] == 'openmiura_routing_policy_pack_organizational_catalog_reconciliation_report_v1'
        assert export_result['summary']['drifted_publication_count'] >= 1

        consumer_after_reconcile = client.get(
            f'/admin/canvas/documents/{consumer_canvas_id}/nodes/{consumer_node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert consumer_after_reconcile.status_code == 200, consumer_after_reconcile.text
        latest_reconciliation = consumer_after_reconcile.json()['node']['data']['last_organizational_catalog_reconciliation_routing_policy_pack']
        assert latest_reconciliation['report_type'] == 'openmiura_routing_policy_pack_organizational_catalog_reconciliation_report_v1'
        assert latest_reconciliation['drifted_publication_count'] >= 1
