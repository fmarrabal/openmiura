from __future__ import annotations

import base64
import json
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

import app as app_module
from openmiura.gateway import Gateway
from tests.test_openclaw_portfolio_evidence_packaging_v2 import (
    _create_runtime,
    _create_submitted_portfolio,
    _set_now,
    _write_config,
)


def test_portfolio_evidence_package_export_archives_to_external_escrow_and_uses_crypto_v2(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_784_790_000.0
    _set_now(monkeypatch, base_now)
    monkeypatch.setenv('OPENMIURA_EVIDENCE_ESCROW_DIR', (tmp_path / 'escrow').as_posix())
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        runtime_id = _create_runtime(client, headers, name='runtime-evidence-escrow')
        portfolio_id = _create_submitted_portfolio(
            client,
            headers,
            base_now=base_now,
            runtime_id=runtime_id,
            export_policy={
                'enabled': True,
                'require_signature': True,
                'signer_key_id': 'portfolio-export-ci',
                'timeline_limit': 120,
                'embed_artifact_content': False,
            },
            escrow_policy={
                'enabled': True,
                'provider': 'filesystem-governed',
                'archive_namespace': 'portfolio-evidence-test',
                'require_archive_on_export': True,
                'allow_inline_fallback': False,
                'immutable_retention_days': 90,
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
        assert payload['integrity']['signature_scheme'] == 'ed25519'
        assert payload['integrity']['public_key']['public_key_pem']
        assert payload['escrow']['archived'] is True
        assert payload['escrow']['archive_path']
        assert Path(payload['escrow']['archive_path']).exists()
        assert payload['escrow']['immutable_until'] is not None

        listed = client.get(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-packages?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert listed.status_code == 200, listed.text
        listed_payload = listed.json()
        item = listed_payload['evidence_packages']['items'][0]
        assert item['escrow']['archived'] is True
        assert 'content_b64' not in (item.get('artifact') or {})
        assert listed_payload['evidence_packages']['summary']['escrowed_count'] == 1
        assert listed_payload['evidence_packages']['summary']['crypto_signed_count'] == 1

        verify = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-artifact-verify',
            headers=headers,
            json={'actor': 'auditor', 'package_id': payload['package_id'], 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert verify.status_code == 200, verify.text
        verified = verify.json()
        assert verified['verification']['status'] == 'verified'
        assert verified['verification']['checks']['escrow_receipt_valid'] is True
        assert verified['verification']['package_integrity']['scheme'] == 'ed25519'


def test_portfolio_evidence_restore_works_from_external_escrow_without_inline_artifact(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_784_800_000.0
    _set_now(monkeypatch, base_now)
    monkeypatch.setenv('OPENMIURA_EVIDENCE_ESCROW_DIR', (tmp_path / 'escrow').as_posix())
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        runtime_id = _create_runtime(client, headers, name='runtime-evidence-restore-escrow')
        portfolio_id = _create_submitted_portfolio(
            client,
            headers,
            base_now=base_now,
            runtime_id=runtime_id,
            export_policy={
                'enabled': True,
                'require_signature': True,
                'signer_key_id': 'portfolio-export-ci',
                'timeline_limit': 120,
                'embed_artifact_content': False,
            },
            escrow_policy={
                'enabled': True,
                'provider': 'filesystem-governed',
                'archive_namespace': 'portfolio-restore-test',
                'require_archive_on_export': True,
                'allow_inline_fallback': False,
            },
        )

        export = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-package-export',
            headers=headers,
            json={'actor': 'auditor', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert export.status_code == 200, export.text
        package_id = export.json()['package_id']

        restore = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-artifact-restore',
            headers=headers,
            json={
                'actor': 'auditor',
                'package_id': package_id,
                'persist_restore_session': True,
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert restore.status_code == 200, restore.text
        restored = restore.json()
        assert restored['verification']['status'] == 'verified'
        assert restored['verification']['checks']['escrow_receipt_valid'] is True
        assert restored['restore']['summary']['persisted'] is True
        assert restored['restore']['summary']['replay_count'] >= 1


def test_offline_verification_script_verifies_artifact_without_runtime_state(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_784_810_000.0
    _set_now(monkeypatch, base_now)
    monkeypatch.setenv('OPENMIURA_EVIDENCE_ESCROW_DIR', (tmp_path / 'escrow').as_posix())
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        runtime_id = _create_runtime(client, headers, name='runtime-evidence-offline')
        portfolio_id = _create_submitted_portfolio(
            client,
            headers,
            base_now=base_now,
            runtime_id=runtime_id,
            escrow_policy={
                'enabled': True,
                'provider': 'filesystem-governed',
                'archive_namespace': 'portfolio-offline-test',
                'require_archive_on_export': True,
                'allow_inline_fallback': False,
            },
        )
        export = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-package-export',
            headers=headers,
            json={'actor': 'auditor', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert export.status_code == 200, export.text
        artifact_b64 = export.json()['artifact']['content_b64']
        artifact_path = tmp_path / 'portfolio-evidence.zip'
        artifact_path.write_bytes(base64.b64decode(artifact_b64.encode('ascii')))

    result = subprocess.run(
        [sys.executable, 'scripts/verify_portfolio_evidence_artifact_offline.py', str(artifact_path)],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload['verification']['status'] == 'verified'
    assert payload['verification']['checks']['package_integrity_valid'] is True
    assert payload['offline']['independent_of_runtime_state'] is True
