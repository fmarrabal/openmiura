from __future__ import annotations

import copy
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

import app as app_module
from openmiura.gateway import Gateway
import openmiura.application.openclaw.scheduler as scheduler_mod
from tests.test_openclaw_portfolio_evidence_artifact_restore_v2 import _tamper_artifact_content
from tests.test_openclaw_portfolio_evidence_packaging_v2 import (
    _create_runtime,
    _create_submitted_portfolio,
    _set_now,
    _write_config,
)


def _patch_native_provider(monkeypatch, helper_name: str, provider_name: str) -> None:
    private_key = ec.generate_private_key(ec.SECP256R1())

    def _fake(
        self,
        *,
        provider: str,
        signer_key_id: str,
        signing_input: dict[str, object],
        payload_hash: str,
        signing_policy: dict[str, object] | None = None,
    ) -> dict[str, object]:
        assert provider == provider_name
        signature = private_key.sign(self._json_canonical_bytes(signing_input), ec.ECDSA(hashes.SHA256()))
        return self._crypto_signature_result(
            signature_bytes=signature,
            signature_scheme='ecdsa-sha256',
            signing_input=signing_input,
            payload_hash=payload_hash,
            public_key=private_key.public_key(),
            provider=provider,
            key_origin=f'{provider_name}_native_test',
            provider_metadata={'provider': provider_name, 'native_test': True, 'signer_key_id': signer_key_id},
        )

    monkeypatch.setattr(scheduler_mod.OpenClawRecoverySchedulerService, helper_name, _fake)


@pytest.mark.parametrize(
    ('provider_name', 'helper_name'),
    [
        ('aws-kms-ecdsa-p256', '_sign_with_aws_kms_native'),
        ('gcp-kms-ecdsa-p256', '_sign_with_gcp_kms_native'),
        ('azure-kv-ecdsa-p256', '_sign_with_azure_key_vault_native'),
        ('pkcs11-ecdsa-p256', '_sign_with_pkcs11_native'),
    ],
)
def test_portfolio_evidence_package_supports_native_signing_provider_dispatch(
    tmp_path: Path,
    monkeypatch,
    provider_name: str,
    helper_name: str,
) -> None:
    base_now = 1_784_930_000.0
    _set_now(monkeypatch, base_now)
    _patch_native_provider(monkeypatch, helper_name, provider_name)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        runtime_id = _create_runtime(client, headers, name=f'runtime-{provider_name}')
        portfolio_id = _create_submitted_portfolio(
            client,
            headers,
            base_now=base_now,
            runtime_id=runtime_id,
            signing_policy={
                'provider': provider_name,
                'require_external_provider': True,
                'allow_local_fallback': False,
                'key_id': f'{provider_name}-key',
            },
        )
        export = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-package-export',
            headers=headers,
            json={'actor': 'auditor', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert export.status_code == 200, export.text
        payload = export.json()
        assert payload['ok'] is True
        assert payload['integrity']['signer_provider'] == provider_name
        assert payload['integrity']['signature_scheme'] == 'ecdsa-sha256'

        verify = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-artifact-verify',
            headers=headers,
            json={'actor': 'auditor', 'package_id': payload['package_id'], 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert verify.status_code == 200, verify.text
        verified = verify.json()
        assert verified['verification']['status'] == 'verified'
        assert verified['verification']['package_integrity']['scheme'] == 'ecdsa-sha256'


def test_sqlite_immutable_custody_anchor_backend_reconciles_missing_local_receipts(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_784_931_000.0
    _set_now(monkeypatch, base_now)
    sqlite_path = tmp_path / 'custody-ledger.sqlite3'
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        runtime_id = _create_runtime(client, headers, name='runtime-sqlite-custody')
        portfolio_id = _create_submitted_portfolio(
            client,
            headers,
            base_now=base_now,
            runtime_id=runtime_id,
            custody_anchor_policy={
                'enabled': True,
                'provider': 'sqlite-immutable-ledger',
                'sqlite_path': sqlite_path.as_posix(),
                'require_anchor_on_export': True,
                'anchor_on_export': True,
                'verify_against_external': True,
            },
        )
        export = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-package-export',
            headers=headers,
            json={'actor': 'auditor', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert export.status_code == 200, export.text
        assert export.json()['custody_anchor']['provider'] == 'sqlite-immutable-ledger'
        assert sqlite_path.exists()

        gw = client.app.state.gw
        release = gw.audit.get_release_bundle(portfolio_id, tenant_id='tenant-a', workspace_id='ws-a', environment='prod')
        metadata = dict(release.get('metadata') or {})
        portfolio = dict(metadata.get('portfolio') or {})
        portfolio['custody_anchor_receipts'] = []
        portfolio['current_custody_anchor'] = None
        metadata['portfolio'] = portfolio
        gw.audit.update_release_bundle(portfolio_id, metadata=metadata, tenant_id='tenant-a', workspace_id='ws-a', environment='prod')

        reconcile = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/custody-anchors/reconcile',
            headers=headers,
            json={'actor': 'ops-admin', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert reconcile.status_code == 200, reconcile.text
        payload = reconcile.json()
        assert payload['reconciliation']['status'] == 'reconciled'
        assert payload['reconciliation']['imported_count'] == 1
        assert payload['reconciliation']['immutable_backend'] is True
        assert payload['custody_anchors']['summary']['count'] == 1
        assert payload['custody_anchors']['summary']['reconciled'] is True


def test_verification_gate_blocks_sensitive_export_when_custody_reconciliation_conflicts(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_784_932_000.0
    _set_now(monkeypatch, base_now)
    sqlite_path = tmp_path / 'custody-ledger.sqlite3'
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        runtime_id = _create_runtime(client, headers, name='runtime-export-gate')
        portfolio_id = _create_submitted_portfolio(
            client,
            headers,
            base_now=base_now,
            runtime_id=runtime_id,
            custody_anchor_policy={
                'enabled': True,
                'provider': 'sqlite-immutable-ledger',
                'sqlite_path': sqlite_path.as_posix(),
                'require_anchor_on_export': True,
                'anchor_on_export': True,
            },
            verification_gate_policy={
                'enabled': True,
                'require_before_sensitive_export': True,
                'require_chain_reconciliation': True,
                'require_external_anchor_validation': True,
                'block_on_reconciliation_conflict': True,
            },
        )
        first_export = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-package-export',
            headers=headers,
            json={'actor': 'auditor', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert first_export.status_code == 200, first_export.text
        assert first_export.json()['ok'] is True

        gw = client.app.state.gw
        release = gw.audit.get_release_bundle(portfolio_id, tenant_id='tenant-a', workspace_id='ws-a', environment='prod')
        metadata = dict(release.get('metadata') or {})
        portfolio = dict(metadata.get('portfolio') or {})
        tampered = copy.deepcopy(list(portfolio.get('custody_anchor_receipts') or []))
        tampered[0]['chain_head_hash'] = 'tampered-head-hash'
        portfolio['custody_anchor_receipts'] = tampered
        portfolio['current_custody_anchor'] = dict(tampered[-1])
        metadata['portfolio'] = portfolio
        gw.audit.update_release_bundle(portfolio_id, metadata=metadata, tenant_id='tenant-a', workspace_id='ws-a', environment='prod')

        second_export = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-package-export',
            headers=headers,
            json={'actor': 'auditor', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert second_export.status_code == 200, second_export.text
        payload = second_export.json()
        assert payload['ok'] is False
        assert payload['error'] == 'portfolio_verification_gate_failed'
        assert payload['reason'] == 'custody_anchor_reconciliation_conflict'
        assert payload['reconciliation']['conflict_count'] >= 1


def test_verification_gate_blocks_sensitive_restore_until_artifact_is_verified(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_784_933_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        runtime_id = _create_runtime(client, headers, name='runtime-restore-gate')
        portfolio_id = _create_submitted_portfolio(
            client,
            headers,
            base_now=base_now,
            runtime_id=runtime_id,
            verification_gate_policy={
                'enabled': True,
                'require_before_sensitive_restore': True,
                'require_verified_artifact_for_restore': True,
                'require_chain_reconciliation': False,
                'require_external_anchor_validation': False,
            },
        )
        export = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-package-export',
            headers=headers,
            json={'actor': 'auditor', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert export.status_code == 200, export.text
        artifact = export.json()['artifact']
        tampered_b64 = _tamper_artifact_content(artifact['content_b64'])

        restore = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-artifact-restore',
            headers=headers,
            json={
                'actor': 'auditor',
                'artifact': {**{k: v for k, v in artifact.items() if k != 'content_b64'}, 'content_b64': tampered_b64},
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert restore.status_code == 200, restore.text
        payload = restore.json()
        assert payload['ok'] is False
        assert payload['error'] == 'portfolio_verification_gate_failed'
        assert payload['reason'] == 'artifact_verification_required'
        assert payload['verification']['verification']['status'] == 'failed'


def test_canvas_runtime_node_exposes_custody_reconcile_action(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_784_934_000.0
    _set_now(monkeypatch, base_now)
    sqlite_path = tmp_path / 'custody-ledger.sqlite3'
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        runtime_id = _create_runtime(client, headers, name='runtime-canvas-custody-reconcile')
        portfolio_id = _create_submitted_portfolio(
            client,
            headers,
            base_now=base_now,
            runtime_id=runtime_id,
            custody_anchor_policy={
                'enabled': True,
                'provider': 'sqlite-immutable-ledger',
                'sqlite_path': sqlite_path.as_posix(),
                'require_anchor_on_export': True,
                'anchor_on_export': True,
            },
        )
        export = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-package-export',
            headers=headers,
            json={'actor': 'auditor', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert export.status_code == 200, export.text

        canvas = client.post(
            '/admin/canvas/documents',
            headers=headers,
            json={'actor': 'admin', 'title': 'Custody reconcile canvas', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
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
        payload = inspector.json()
        assert 'reconcile_portfolio_custody_anchors' in payload['available_actions']

        reconcile = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/reconcile_portfolio_custody_anchors?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'admin', 'payload': {'portfolio_id': portfolio_id}, 'session_id': 'canvas-admin'},
        )
        assert reconcile.status_code == 200, reconcile.text
        assert reconcile.json()['result']['reconciliation']['status'] in {'aligned', 'reconciled'}
