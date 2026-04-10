from __future__ import annotations

import base64
import json
import zipfile
from io import BytesIO
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from fastapi.testclient import TestClient

import app as app_module
from openmiura.gateway import Gateway
from tests.test_openclaw_portfolio_evidence_packaging_v2 import (
    _create_runtime,
    _create_submitted_portfolio,
    _set_now,
    _write_config,
)


def _write_ed25519_private_key(path: Path) -> None:
    key = ed25519.Ed25519PrivateKey.generate()
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    path.write_bytes(pem)


def test_portfolio_evidence_package_supports_kms_signing_and_object_lock_archive(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_784_820_000.0
    _set_now(monkeypatch, base_now)
    monkeypatch.setenv('OPENMIURA_EVIDENCE_ESCROW_DIR', (tmp_path / 'escrow').as_posix())
    kms_key_path = tmp_path / 'kms-ed25519.pem'
    _write_ed25519_private_key(kms_key_path)
    monkeypatch.setenv('OPENMIURA_EVIDENCE_KMS_PRIVATE_KEY_PEM_PATH', kms_key_path.as_posix())
    monkeypatch.setenv('OPENMIURA_EVIDENCE_KMS_KEY_REF', 'kms://openmiura/test-key')
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        runtime_id = _create_runtime(client, headers, name='runtime-kms-object-lock')
        portfolio_id = _create_submitted_portfolio(
            client,
            headers,
            base_now=base_now,
            runtime_id=runtime_id,
            signing_policy={
                'provider': 'kms-ed25519-simulated',
                'require_external_provider': True,
                'allow_local_fallback': False,
                'key_id': 'kms-ci',
            },
            escrow_policy={
                'enabled': True,
                'provider': 'filesystem-object-lock',
                'archive_namespace': 'portfolio-kms-object-lock',
                'require_archive_on_export': True,
                'allow_inline_fallback': False,
                'immutable_retention_days': 90,
                'retention_mode': 'COMPLIANCE',
            },
        )

        export = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-package-export',
            headers=headers,
            json={'actor': 'auditor', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert export.status_code == 200, export.text
        payload = export.json()
        assert payload['integrity']['crypto_v2'] is True
        assert payload['integrity']['signer_provider'] == 'kms-ed25519-simulated'
        assert payload['integrity']['key_origin'] == 'kms_simulated'
        assert payload['escrow']['archived'] is True
        assert payload['escrow']['object_lock_enabled'] is True
        assert payload['escrow']['retention_mode'] == 'COMPLIANCE'
        assert Path(payload['escrow']['lock_path']).exists()

        verify = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-artifact-verify',
            headers=headers,
            json={'actor': 'auditor', 'package_id': payload['package_id'], 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert verify.status_code == 200, verify.text
        verified = verify.json()
        assert verified['verification']['status'] == 'verified'
        assert verified['verification']['checks']['escrow_receipt_valid'] is True
        assert verified['verification']['checks']['chain_of_custody_valid'] is True
        assert verified['verification']['escrow']['object_lock_valid'] is True
        assert verified['verification']['package_integrity']['signer_provider'] == 'kms-ed25519-simulated'


def test_portfolio_chain_of_custody_tracks_export_verify_restore(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_784_830_000.0
    _set_now(monkeypatch, base_now)
    monkeypatch.setenv('OPENMIURA_EVIDENCE_ESCROW_DIR', (tmp_path / 'escrow').as_posix())
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        runtime_id = _create_runtime(client, headers, name='runtime-custody-ledger')
        portfolio_id = _create_submitted_portfolio(
            client,
            headers,
            base_now=base_now,
            runtime_id=runtime_id,
            chain_of_custody_policy={
                'enabled': True,
                'include_in_artifact': True,
                'sign_entries': True,
                'signer_key_id': 'custody-ci',
                'max_entries': 50,
            },
        )

        export = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-package-export',
            headers=headers,
            json={'actor': 'auditor', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert export.status_code == 200, export.text
        package_id = export.json()['package_id']

        verify = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-artifact-verify',
            headers=headers,
            json={'actor': 'auditor', 'package_id': package_id, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert verify.status_code == 200, verify.text

        restore = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-artifact-restore',
            headers=headers,
            json={'actor': 'auditor', 'package_id': package_id, 'persist_restore_session': True, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert restore.status_code == 200, restore.text

        ledger = client.get(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/chain-of-custody?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert ledger.status_code == 200, ledger.text
        payload = ledger.json()
        summary = payload['chain_of_custody']['summary']
        assert summary['valid'] is True
        assert summary['count'] >= 3
        event_types = {item['event_type'] for item in payload['chain_of_custody']['items']}
        assert 'portfolio_evidence_package_exported' in event_types
        assert 'portfolio_evidence_verified' in event_types
        assert 'portfolio_evidence_restored' in event_types


def test_exported_artifact_embeds_chain_of_custody_manifest_entry(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_784_840_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        runtime_id = _create_runtime(client, headers, name='runtime-custody-artifact')
        portfolio_id = _create_submitted_portfolio(
            client,
            headers,
            base_now=base_now,
            runtime_id=runtime_id,
            chain_of_custody_policy={'enabled': True, 'include_in_artifact': True, 'sign_entries': True},
        )
        export = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-package-export',
            headers=headers,
            json={'actor': 'auditor', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert export.status_code == 200, export.text
        artifact_b64 = export.json()['artifact']['content_b64']

    archive_bytes = base64.b64decode(artifact_b64.encode('ascii'))
    with zipfile.ZipFile(BytesIO(archive_bytes), mode='r') as zf:
        names = set(zf.namelist())
        assert 'chain_of_custody.json' in names
        manifest = json.loads(zf.read('manifest.json').decode('utf-8'))
        artifact_ids = {item['artifact_id'] for item in manifest['artifacts']}
        assert 'chain_of_custody' in artifact_ids
        chain = json.loads(zf.read('chain_of_custody.json').decode('utf-8'))
        assert chain['summary']['valid'] is True
        assert chain['summary']['count'] >= 1
