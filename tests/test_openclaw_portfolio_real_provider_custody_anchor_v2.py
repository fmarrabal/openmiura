from __future__ import annotations

import base64
import json
import sys
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


def _write_ed25519_keypair(private_path: Path, public_path: Path) -> None:
    key = ed25519.Ed25519PrivateKey.generate()
    private_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    public_path.write_bytes(
        key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )


def _write_external_signer(path: Path) -> None:
    path.write_text(
        """
from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

payload = json.loads(sys.stdin.read())
message = base64.b64decode(payload['message_b64'].encode('ascii'))
key_path = Path(os.environ['OPENMIURA_TEST_EXTERNAL_SIGNER_KEY_PATH'])
raw = key_path.read_bytes()
private_key = serialization.load_pem_private_key(raw, password=None)
if not isinstance(private_key, Ed25519PrivateKey):
    raise SystemExit('invalid private key')
signature = private_key.sign(message)
public_key_pem = private_key.public_key().public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo,
).decode('utf-8')
sys.stdout.write(json.dumps({
    'signature': base64.b64encode(signature).decode('ascii'),
    'public_key_pem': public_key_pem,
    'provider_metadata': {
        'external_signer': 'python-test-command',
        'key_path': key_path.as_posix(),
    },
}))
""".strip(),
        encoding='utf-8',
    )


def test_portfolio_evidence_package_supports_external_command_signing_and_custody_anchors(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_784_860_000.0
    _set_now(monkeypatch, base_now)
    monkeypatch.setenv('OPENMIURA_CUSTODY_ANCHOR_DIR', (tmp_path / 'custody-anchor').as_posix())
    private_key_path = tmp_path / 'external-signer-private.pem'
    public_key_path = tmp_path / 'external-signer-public.pem'
    _write_ed25519_keypair(private_key_path, public_key_path)
    signer_script = tmp_path / 'external_signer.py'
    _write_external_signer(signer_script)
    monkeypatch.setenv('OPENMIURA_TEST_EXTERNAL_SIGNER_KEY_PATH', private_key_path.as_posix())

    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        runtime_id = _create_runtime(client, headers, name='runtime-command-signing-anchor')
        portfolio_id = _create_submitted_portfolio(
            client,
            headers,
            base_now=base_now,
            runtime_id=runtime_id,
            signing_policy={
                'provider': 'kms-ed25519-command',
                'require_external_provider': True,
                'allow_local_fallback': False,
                'key_id': 'kms-cmd-ci',
                'sign_command': [sys.executable, signer_script.as_posix()],
            },
            custody_anchor_policy={
                'enabled': True,
                'provider': 'filesystem-ledger',
                'ledger_namespace': 'portfolio-custody-test',
                'require_anchor_on_export': True,
                'anchor_on_export': True,
                'include_in_artifact': True,
                'signer_key_id': 'anchor-ci',
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
        assert payload['integrity']['signer_provider'] == 'kms-ed25519-command'
        assert payload['integrity']['key_origin'] == 'external_command'
        assert payload['custody_anchor']['anchor_id']
        assert Path(payload['custody_anchor']['archive_path']).exists()

        anchors = client.get(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/custody-anchors?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert anchors.status_code == 200, anchors.text
        anchors_payload = anchors.json()
        assert anchors_payload['custody_anchors']['summary']['count'] == 1
        assert anchors_payload['custody_anchors']['summary']['valid'] is True
        assert anchors_payload['custody_anchors']['items'][0]['anchor_id'] == payload['custody_anchor']['anchor_id']

        verify = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-artifact-verify',
            headers=headers,
            json={'actor': 'auditor', 'package_id': payload['package_id'], 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert verify.status_code == 200, verify.text
        verified = verify.json()
        assert verified['verification']['status'] == 'verified'
        assert verified['verification']['checks']['custody_anchor_valid'] is True
        assert verified['verification']['package_integrity']['signer_provider'] == 'kms-ed25519-command'


def test_exported_artifact_embeds_custody_anchor_receipt(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_784_870_000.0
    _set_now(monkeypatch, base_now)
    monkeypatch.setenv('OPENMIURA_CUSTODY_ANCHOR_DIR', (tmp_path / 'custody-anchor').as_posix())
    private_key_path = tmp_path / 'external-signer-private.pem'
    public_key_path = tmp_path / 'external-signer-public.pem'
    _write_ed25519_keypair(private_key_path, public_key_path)
    signer_script = tmp_path / 'external_signer.py'
    _write_external_signer(signer_script)
    monkeypatch.setenv('OPENMIURA_TEST_EXTERNAL_SIGNER_KEY_PATH', private_key_path.as_posix())

    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        runtime_id = _create_runtime(client, headers, name='runtime-custody-anchor-artifact')
        portfolio_id = _create_submitted_portfolio(
            client,
            headers,
            base_now=base_now,
            runtime_id=runtime_id,
            signing_policy={
                'provider': 'kms-ed25519-command',
                'require_external_provider': True,
                'allow_local_fallback': False,
                'key_id': 'kms-cmd-ci',
                'sign_command': [sys.executable, signer_script.as_posix()],
            },
            custody_anchor_policy={
                'enabled': True,
                'provider': 'filesystem-ledger',
                'ledger_namespace': 'portfolio-custody-test',
                'require_anchor_on_export': True,
                'anchor_on_export': True,
                'include_in_artifact': True,
            },
        )
        export = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-package-export',
            headers=headers,
            json={'actor': 'auditor', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert export.status_code == 200, export.text
        artifact_b64 = export.json()['artifact']['content_b64']
        anchor_id = export.json()['custody_anchor']['anchor_id']

    archive_bytes = base64.b64decode(artifact_b64.encode('ascii'))
    with zipfile.ZipFile(BytesIO(archive_bytes), mode='r') as zf:
        names = set(zf.namelist())
        assert 'custody_anchor.json' in names
        anchor = json.loads(zf.read('custody_anchor.json').decode('utf-8'))
        assert anchor['anchor_id'] == anchor_id
        assert anchor['receipt_type'] == 'openmiura_portfolio_custody_anchor_receipt_v1'
        assert anchor['integrity']['crypto_v2'] is True


def test_custody_anchor_is_required_when_policy_demands_it(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_784_880_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        runtime_id = _create_runtime(client, headers, name='runtime-anchor-required')
        portfolio_id = _create_submitted_portfolio(
            client,
            headers,
            base_now=base_now,
            runtime_id=runtime_id,
            custody_anchor_policy={
                'enabled': True,
                'provider': 'unsupported-provider',
                'require_anchor_on_export': True,
            },
        )
        export = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-package-export',
            headers=headers,
            json={'actor': 'auditor', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert export.status_code == 200, export.text
        payload = export.json()
        assert payload['ok'] is False
        assert payload['error'] == 'portfolio_custody_anchor_failed'
        assert payload['custody_anchor']['reason'] == 'unsupported_custody_anchor_provider'
