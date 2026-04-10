from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import app as app_module
from openmiura.gateway import Gateway
from tests.test_openclaw_canvas_v2_async_runtime_board import _write_config as _write_canvas_config
from tests.test_openclaw_portfolio_evidence_artifact_restore_v2 import _tamper_artifact_content
from tests.test_openclaw_portfolio_evidence_packaging_v2 import (
    _base_metadata,
    _candidate_policy,
    _set_now,
    _write_config,
)


def _create_runtime_for_environment(client: TestClient, headers: dict[str, str], *, name: str, environment: str) -> str:
    metadata = _base_metadata()
    session_bridge = dict(metadata.get('session_bridge') or {})
    session_bridge['external_environment'] = environment
    metadata['session_bridge'] = session_bridge
    response = client.post(
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
            'environment': environment,
            'metadata': metadata,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()['runtime']['runtime_id']



def _create_and_approve_bundle_for_environment(
    client: TestClient,
    headers: dict[str, str],
    *,
    name: str,
    runtime_ids: list[str],
    environment: str,
) -> str:
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
            'environment': environment,
        },
    )
    assert create.status_code == 200, create.text
    bundle_id = create.json()['bundle_id']
    submit = client.post(
        f'/admin/openclaw/alert-governance/bundles/{bundle_id}/submit',
        headers=headers,
        json={'actor': 'release-admin', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': environment},
    )
    assert submit.status_code == 200, submit.text
    approve = client.post(
        f'/admin/openclaw/alert-governance/bundles/{bundle_id}/approve',
        headers=headers,
        json={'actor': 'security-admin', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': environment},
    )
    assert approve.status_code == 200, approve.text
    return bundle_id



def _create_submitted_portfolio_for_environment(
    client: TestClient,
    headers: dict[str, str],
    *,
    base_now: float,
    runtime_id: str,
    environment: str,
    export_policy: dict[str, object] | None = None,
    retention_policy: dict[str, object] | None = None,
    escrow_policy: dict[str, object] | None = None,
    signing_policy: dict[str, object] | None = None,
    verification_gate_policy: dict[str, object] | None = None,
    environment_tier_policies: dict[str, object] | None = None,
) -> str:
    bundle_id = _create_and_approve_bundle_for_environment(
        client,
        headers,
        name=f'bundle-{environment}-{int(base_now)}',
        runtime_ids=[runtime_id],
        environment=environment,
    )
    create = client.post(
        '/admin/openclaw/alert-governance/portfolios',
        headers=headers,
        json={
            'actor': 'portfolio-admin',
            'name': f'portfolio-{environment}-{int(base_now)}',
            'version': f'2026.03.31.{environment}.{int(base_now)}',
            'bundle_ids': [bundle_id],
            'base_release_at': base_now + 10,
            'export_policy': export_policy or {
                'enabled': True,
                'require_signature': True,
                'timeline_limit': 120,
            },
            'retention_policy': retention_policy or {
                'enabled': True,
                'retention_days': 30,
                'max_packages': 5,
                'purge_expired': True,
                'prune_on_export': True,
            },
            'escrow_policy': escrow_policy or {},
            'signing_policy': signing_policy or {},
            'verification_gate_policy': verification_gate_policy or {},
            'environment_tier_policies': environment_tier_policies or {},
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
        json={'actor': 'security-admin', 'reason': 'approve environment-tiered portfolio', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': environment},
    )
    assert approve.status_code == 200, approve.text
    return portfolio_id



def test_environment_tier_policies_apply_distinct_escrow_signing_and_classification_per_environment(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_600_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    stage_escrow_dir = (tmp_path / 'stage-escrow').resolve()
    prod_escrow_dir = (tmp_path / 'prod-escrow').resolve()
    tier_policies = {
        'stage': {
            'operational_tier': 'stage',
            'evidence_classification': 'controlled-preprod-evidence',
            'escrow_policy': {
                'enabled': True,
                'provider': 'filesystem-governed',
                'root_dir': str(stage_escrow_dir),
                'require_archive_on_export': False,
                'allow_inline_fallback': True,
            },
            'signing_policy': {
                'enabled': True,
                'provider': 'local-ed25519',
                'key_id': 'stage-signer',
            },
            'verification_gate_policy': {
                'enabled': True,
                'require_verify_on_read': False,
            },
        },
        'prod': {
            'operational_tier': 'prod',
            'evidence_classification': 'regulated-enterprise-evidence',
            'escrow_policy': {
                'enabled': True,
                'provider': 'filesystem-object-lock',
                'root_dir': str(prod_escrow_dir),
                'require_archive_on_export': True,
                'allow_inline_fallback': False,
                'object_lock_enabled': True,
            },
            'signing_policy': {
                'enabled': True,
                'provider': 'local-ed25519',
                'key_id': 'prod-signer',
            },
            'verification_gate_policy': {
                'enabled': True,
                'require_verify_on_read': True,
                'block_on_failed_verify_on_read': True,
            },
        },
    }

    with TestClient(app) as client:
        stage_runtime_id = _create_runtime_for_environment(client, headers, name='runtime-stage-tiered', environment='stage')
        prod_runtime_id = _create_runtime_for_environment(client, headers, name='runtime-prod-tiered', environment='prod')

        stage_portfolio_id = _create_submitted_portfolio_for_environment(
            client,
            headers,
            base_now=base_now,
            runtime_id=stage_runtime_id,
            environment='stage',
            environment_tier_policies=tier_policies,
        )
        prod_portfolio_id = _create_submitted_portfolio_for_environment(
            client,
            headers,
            base_now=base_now + 100,
            runtime_id=prod_runtime_id,
            environment='prod',
            environment_tier_policies=tier_policies,
        )

        stage_detail = client.get(
            f'/admin/openclaw/alert-governance/portfolios/{stage_portfolio_id}?tenant_id=tenant-a&workspace_id=ws-a&environment=stage',
            headers=headers,
        )
        assert stage_detail.status_code == 200, stage_detail.text
        stage_data = stage_detail.json()
        assert stage_data['summary']['operational_tier'] == 'stage'
        assert stage_data['summary']['evidence_classification'] == 'controlled-preprod-evidence'
        assert stage_data['portfolio']['train_policy']['environment_tier_policy']['signing_policy']['key_id'] == 'stage-signer'
        assert stage_data['portfolio']['train_policy']['environment_tier_policy']['escrow_policy']['provider'] == 'filesystem-governed'

        prod_detail = client.get(
            f'/admin/openclaw/alert-governance/portfolios/{prod_portfolio_id}?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert prod_detail.status_code == 200, prod_detail.text
        prod_data = prod_detail.json()
        assert prod_data['summary']['operational_tier'] == 'prod'
        assert prod_data['summary']['evidence_classification'] == 'regulated-enterprise-evidence'
        assert prod_data['portfolio']['train_policy']['environment_tier_policy']['signing_policy']['key_id'] == 'prod-signer'
        assert prod_data['portfolio']['train_policy']['environment_tier_policy']['escrow_policy']['provider'] == 'filesystem-object-lock'

        stage_validation = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{stage_portfolio_id}/provider-validation',
            headers=headers,
            json={'actor': 'ops-admin', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'stage'},
        )
        assert stage_validation.status_code == 200, stage_validation.text
        stage_validation_payload = stage_validation.json()['provider_validation']
        assert stage_validation_payload['signing']['provider'] == 'local-ed25519'
        assert stage_validation_payload['signing']['key_id'] == 'stage-signer'
        assert stage_validation_payload['escrow']['provider'] == 'filesystem-governed'

        prod_validation = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{prod_portfolio_id}/provider-validation',
            headers=headers,
            json={'actor': 'ops-admin', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert prod_validation.status_code == 200, prod_validation.text
        prod_validation_payload = prod_validation.json()['provider_validation']
        assert prod_validation_payload['signing']['provider'] == 'local-ed25519'
        assert prod_validation_payload['signing']['key_id'] == 'prod-signer'
        assert prod_validation_payload['escrow']['provider'] == 'filesystem-object-lock'

        stage_export = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{stage_portfolio_id}/evidence-package-export',
            headers=headers,
            json={'actor': 'auditor', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'stage'},
        )
        assert stage_export.status_code == 200, stage_export.text
        stage_export_payload = stage_export.json()
        assert stage_export_payload['package']['operational_tier'] == 'stage'
        assert stage_export_payload['package']['evidence_classification'] == 'controlled-preprod-evidence'
        assert stage_export_payload['integrity']['signed'] is True
        assert stage_export_payload['escrow']['provider'] == 'filesystem-governed'

        prod_export = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{prod_portfolio_id}/evidence-package-export',
            headers=headers,
            json={'actor': 'auditor', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert prod_export.status_code == 200, prod_export.text
        prod_export_payload = prod_export.json()
        assert prod_export_payload['package']['operational_tier'] == 'prod'
        assert prod_export_payload['package']['evidence_classification'] == 'regulated-enterprise-evidence'
        assert prod_export_payload['integrity']['signed'] is True
        assert prod_export_payload['escrow']['provider'] == 'filesystem-object-lock'
        assert prod_export_payload['escrow']['object_lock_enabled'] is True

        listed = client.get(
            '/admin/openclaw/alert-governance/portfolios?tenant_id=tenant-a&workspace_id=ws-a&limit=20',
            headers=headers,
        )
        assert listed.status_code == 200, listed.text
        listed_payload = listed.json()
        assert listed_payload['summary']['operational_tier_counts']['stage'] >= 1
        assert listed_payload['summary']['operational_tier_counts']['prod'] >= 1
        assert listed_payload['summary']['evidence_classification_counts']['controlled-preprod-evidence'] >= 1
        assert listed_payload['summary']['evidence_classification_counts']['regulated-enterprise-evidence'] >= 1



def test_verify_on_read_blocks_critical_reads_and_list_items_but_not_verify_action(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_601_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        runtime_id = _create_runtime_for_environment(client, headers, name='runtime-read-hardening', environment='prod')
        portfolio_id = _create_submitted_portfolio_for_environment(
            client,
            headers,
            base_now=base_now,
            runtime_id=runtime_id,
            environment='prod',
            verification_gate_policy={
                'enabled': True,
                'require_verify_on_read': True,
                'block_on_failed_verify_on_read': True,
                'verify_on_read_latest_only': True,
                'persist_verify_on_read': True,
                'critical_read_paths': ['detail', 'list_item', 'chain_of_custody', 'custody_anchors', 'evidence_packages'],
            },
        )

        export = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-package-export',
            headers=headers,
            json={'actor': 'auditor', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert export.status_code == 200, export.text
        exported = export.json()
        package_id = exported['package_id']
        tampered_b64 = _tamper_artifact_content(exported['artifact']['content_b64'])

        gw = client.app.state.gw
        release = gw.audit.get_release_bundle(portfolio_id, tenant_id='tenant-a', workspace_id='ws-a', environment='prod')
        metadata = dict(release.get('metadata') or {})
        portfolio = dict(metadata.get('portfolio') or {})
        packages = [dict(item) for item in list(portfolio.get('evidence_packages') or [])]
        packages[0] = {
            **packages[0],
            'artifact': {
                **{k: v for k, v in dict(packages[0].get('artifact') or {}).items() if k != 'content_b64'},
                'content_b64': tampered_b64,
            },
        }
        portfolio['evidence_packages'] = packages
        metadata['portfolio'] = portfolio
        gw.audit.update_release_bundle(portfolio_id, metadata=metadata, tenant_id='tenant-a', workspace_id='ws-a', environment='prod')

        detail = client.get(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert detail.status_code == 200, detail.text
        detail_payload = detail.json()
        assert detail_payload['ok'] is False
        assert detail_payload['error'] == 'portfolio_verify_on_read_failed'
        assert detail_payload['read_verification']['status'] == 'failed'

        evidence_packages = client.get(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-packages?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert evidence_packages.status_code == 200, evidence_packages.text
        evidence_payload = evidence_packages.json()
        assert evidence_payload['ok'] is False
        assert evidence_payload['error'] == 'portfolio_verify_on_read_failed'

        chain = client.get(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/chain-of-custody?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert chain.status_code == 200, chain.text
        chain_payload = chain.json()
        assert chain_payload['ok'] is False
        assert chain_payload['error'] == 'portfolio_verify_on_read_failed'

        listed = client.get(
            '/admin/openclaw/alert-governance/portfolios?tenant_id=tenant-a&workspace_id=ws-a&limit=20',
            headers=headers,
        )
        assert listed.status_code == 200, listed.text
        listed_payload = listed.json()
        assert listed_payload['ok'] is True
        assert listed_payload['summary']['read_blocked_count'] >= 1
        assert any(bool(item.get('read_blocked')) for item in listed_payload['items'])

        verify = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-artifact-verify',
            headers=headers,
            json={'actor': 'auditor', 'package_id': package_id, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert verify.status_code == 200, verify.text
        verify_payload = verify.json()
        assert verify_payload['ok'] is True
        assert verify_payload['verification']['status'] == 'failed'
        assert verify_payload['verification']['checks']['archive_hash_valid'] is False or verify_payload['verification']['checks']['package_integrity_valid'] is False



def test_canvas_runtime_board_surfaces_tier_counts_and_read_blocked_portfolios(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_602_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_canvas_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        canvas = client.post(
            '/admin/canvas/documents',
            headers=headers,
            json={'actor': 'admin', 'title': 'Evidence governance canvas', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert canvas.status_code == 200, canvas.text
        canvas_id = canvas.json()['document']['canvas_id']

        runtime_id = _create_runtime_for_environment(client, headers, name='runtime-canvas-tiered', environment='prod')
        node = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes',
            headers=headers,
            json={
                'actor': 'admin',
                'node_type': 'openclaw_runtime',
                'label': 'Runtime evidence node',
                'data': {'runtime_id': runtime_id, 'agent_id': 'default'},
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert node.status_code == 200, node.text

        normal_portfolio_id = _create_submitted_portfolio_for_environment(
            client,
            headers,
            base_now=base_now,
            runtime_id=runtime_id,
            environment='prod',
            environment_tier_policies={
                'prod': {
                    'operational_tier': 'prod',
                    'evidence_classification': 'regulated-enterprise-evidence',
                }
            },
        )
        blocked_portfolio_id = _create_submitted_portfolio_for_environment(
            client,
            headers,
            base_now=base_now + 100,
            runtime_id=runtime_id,
            environment='prod',
            verification_gate_policy={
                'enabled': True,
                'require_verify_on_read': True,
                'block_on_failed_verify_on_read': True,
                'verify_on_read_latest_only': True,
                'critical_read_paths': ['list_item'],
            },
        )

        normal_export = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{normal_portfolio_id}/evidence-package-export',
            headers=headers,
            json={'actor': 'auditor', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert normal_export.status_code == 200, normal_export.text

        blocked_export = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{blocked_portfolio_id}/evidence-package-export',
            headers=headers,
            json={'actor': 'auditor', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert blocked_export.status_code == 200, blocked_export.text
        tampered_b64 = _tamper_artifact_content(blocked_export.json()['artifact']['content_b64'])
        gw = client.app.state.gw
        release = gw.audit.get_release_bundle(blocked_portfolio_id, tenant_id='tenant-a', workspace_id='ws-a', environment='prod')
        metadata = dict(release.get('metadata') or {})
        portfolio = dict(metadata.get('portfolio') or {})
        packages = [dict(item) for item in list(portfolio.get('evidence_packages') or [])]
        packages[0] = {
            **packages[0],
            'artifact': {
                **{k: v for k, v in dict(packages[0].get('artifact') or {}).items() if k != 'content_b64'},
                'content_b64': tampered_b64,
            },
        }
        portfolio['evidence_packages'] = packages
        metadata['portfolio'] = portfolio
        gw.audit.update_release_bundle(blocked_portfolio_id, metadata=metadata, tenant_id='tenant-a', workspace_id='ws-a', environment='prod')

        board = client.get(
            f'/admin/canvas/documents/{canvas_id}/views/runtime-board?tenant_id=tenant-a&workspace_id=ws-a&environment=prod&limit=10',
            headers=headers,
        )
        assert board.status_code == 200, board.text
        payload = board.json()
        node_summary = payload['items'][0]['summary']
        assert node_summary['governance_portfolio_read_blocked_count'] >= 1
        assert node_summary['governance_portfolio_operational_tier_counts']['prod'] >= 1
        assert node_summary['governance_portfolio_evidence_classification_counts']['regulated-enterprise-evidence'] >= 1
