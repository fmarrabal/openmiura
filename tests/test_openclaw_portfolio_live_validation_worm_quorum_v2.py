from __future__ import annotations

import io
import sys
import types
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


class _FakeS3Client:
    def __init__(self, storage: dict[tuple[str, str], dict[str, object]]) -> None:
        self.storage = storage

    def head_bucket(self, *, Bucket: str):
        return {'Bucket': Bucket}

    def get_object_lock_configuration(self, *, Bucket: str):
        return {'ObjectLockConfiguration': {'ObjectLockEnabled': 'Enabled'}}

    def put_object(self, **kwargs):
        bucket = kwargs['Bucket']
        key = kwargs['Key']
        body = kwargs.get('Body', b'')
        if hasattr(body, 'read'):
            body = body.read()
        elif isinstance(body, str):
            body = body.encode('utf-8')
        self.storage[(bucket, key)] = {
            'Body': bytes(body),
            'Metadata': dict(kwargs.get('Metadata') or {}),
            'ObjectLockMode': kwargs.get('ObjectLockMode'),
            'ObjectLockRetainUntilDate': kwargs.get('ObjectLockRetainUntilDate'),
            'ContentType': kwargs.get('ContentType'),
            'LegalHoldStatus': 'OFF',
        }
        return {'ETag': 'fake-etag'}

    def head_object(self, *, Bucket: str, Key: str):
        record = self.storage[(Bucket, Key)]
        return {
            'Metadata': dict(record.get('Metadata') or {}),
            'ObjectLockMode': record.get('ObjectLockMode'),
            'ObjectLockRetainUntilDate': record.get('ObjectLockRetainUntilDate'),
        }

    def get_object(self, *, Bucket: str, Key: str):
        record = self.storage[(Bucket, Key)]
        return {'Body': io.BytesIO(bytes(record.get('Body') or b''))}

    def put_object_legal_hold(self, *, Bucket: str, Key: str, LegalHold: dict[str, str]):
        record = self.storage[(Bucket, Key)]
        record['LegalHoldStatus'] = str((LegalHold or {}).get('Status') or 'OFF')
        return {'Result': 'ok'}

    def get_object_retention(self, *, Bucket: str, Key: str):
        record = self.storage[(Bucket, Key)]
        return {
            'Retention': {
                'Mode': record.get('ObjectLockMode'),
                'RetainUntilDate': record.get('ObjectLockRetainUntilDate'),
            }
        }

    def get_object_legal_hold(self, *, Bucket: str, Key: str):
        record = self.storage[(Bucket, Key)]
        return {'LegalHold': {'Status': record.get('LegalHoldStatus', 'OFF')}}


class _FakeKmsClient:
    def describe_key(self, *, KeyId: str):
        return {'KeyMetadata': {'KeySpec': 'ECC_NIST_P256', 'KeyState': 'Enabled', 'KeyId': KeyId}}

    def get_public_key(self, *, KeyId: str):
        return {'PublicKey': b'fake-public', 'SigningAlgorithms': ['ECDSA_SHA_256']}


class _FakeBoto3Session:
    def __init__(self, storage: dict[tuple[str, str], dict[str, object]]) -> None:
        self.storage = storage

    def client(self, service_name: str, **kwargs):
        if service_name == 's3':
            return _FakeS3Client(self.storage)
        if service_name == 'kms':
            return _FakeKmsClient()
        raise AssertionError(service_name)


def _install_fake_boto3(monkeypatch, storage: dict[tuple[str, str], dict[str, object]]) -> None:
    module = types.SimpleNamespace(Session=lambda **kwargs: _FakeBoto3Session(storage))
    monkeypatch.setitem(sys.modules, 'boto3', module)


def _install_fake_gcp_kms(monkeypatch) -> None:
    class _FakeClient:
        def get_public_key(self, request: dict[str, str]):
            return types.SimpleNamespace(pem='-----BEGIN PUBLIC KEY-----\nFAKE\n-----END PUBLIC KEY-----', algorithm='EC_SIGN_P256_SHA256')

    google_mod = types.ModuleType('google')
    cloud_mod = types.ModuleType('google.cloud')
    kms_mod = types.ModuleType('google.cloud.kms_v1')
    kms_mod.KeyManagementServiceClient = _FakeClient
    monkeypatch.setitem(sys.modules, 'google', google_mod)
    monkeypatch.setitem(sys.modules, 'google.cloud', cloud_mod)
    monkeypatch.setitem(sys.modules, 'google.cloud.kms_v1', kms_mod)


def _install_fake_azure_kv(monkeypatch) -> None:
    identity_mod = types.ModuleType('azure.identity')
    identity_mod.DefaultAzureCredential = lambda: object()
    keys_mod = types.ModuleType('azure.keyvault.keys')

    class _FakeKeyClient:
        def __init__(self, *, vault_url: str, credential):
            self.vault_url = vault_url
            self.credential = credential

        def get_key(self, key_name: str):
            return types.SimpleNamespace(key_type='EC', key=object(), name=key_name)

    keys_mod.KeyClient = _FakeKeyClient
    monkeypatch.setitem(sys.modules, 'azure.identity', identity_mod)
    monkeypatch.setitem(sys.modules, 'azure.keyvault.keys', keys_mod)


def _install_fake_pkcs11(monkeypatch) -> None:
    module = types.ModuleType('pkcs11')

    class _ObjectClass:
        PRIVATE_KEY = 'private'

    class _Session:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get_key(self, *, label: str, object_class):
            assert object_class == _ObjectClass.PRIVATE_KEY
            return {'label': label}

    class _Token:
        def open(self, *, user_pin=None):
            return _Session()

    class _Lib:
        def get_token(self, slot=None, token_label=None):
            return _Token()

    module.ObjectClass = _ObjectClass
    module.lib = lambda path: _Lib()
    monkeypatch.setitem(sys.modules, 'pkcs11', module)


def test_portfolio_provider_validation_supports_live_cloud_and_pkcs11_adapters(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_200_000.0
    _set_now(monkeypatch, base_now)
    _install_fake_boto3(monkeypatch, {})
    _install_fake_gcp_kms(monkeypatch)
    _install_fake_azure_kv(monkeypatch)
    _install_fake_pkcs11(monkeypatch)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    providers = [
        ({'provider': 'aws-kms-ecdsa-p256', 'aws_kms_key_id': 'arn:aws:kms:eu-west-1:123:key/abc', 'key_id': 'aws-kms-key'}, 'aws-kms-ecdsa-p256'),
        ({'provider': 'gcp-kms-ecdsa-p256', 'gcp_kms_key_name': 'projects/p/locations/l/keyRings/r/cryptoKeys/k/cryptoKeyVersions/1', 'key_id': 'gcp-kms-key'}, 'gcp-kms-ecdsa-p256'),
        ({'provider': 'azure-kv-ecdsa-p256', 'azure_vault_url': 'https://vault.example.vault.azure.net/', 'azure_key_id': 'signing-key', 'key_id': 'azure-key'}, 'azure-kv-ecdsa-p256'),
        ({'provider': 'pkcs11-ed25519', 'pkcs11_module_path': '/opt/libpkcs11.so', 'pkcs11_token_label': 'token-a', 'pkcs11_key_label': 'signing-key', 'key_id': 'pkcs11-key'}, 'pkcs11-ed25519'),
    ]

    with TestClient(app) as client:
        runtime_id = _create_runtime(client, headers, name='runtime-provider-validation')
        for index, (signing_policy, provider_name) in enumerate(providers, start=1):
            portfolio_id = _create_submitted_portfolio(
                client,
                headers,
                base_now=base_now + index,
                runtime_id=runtime_id,
                signing_policy=signing_policy,
            )
            response = client.post(
                f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/provider-validation',
                headers=headers,
                json={'actor': 'ops-admin', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
            )
            assert response.status_code == 200, response.text
            payload = response.json()
            assert payload['ok'] is True
            assert payload['valid'] is True
            assert payload['provider_validation']['signing']['provider'] == provider_name
            assert payload['provider_validation']['signing']['valid'] is True
            assert payload['provider_validation']['signing']['provider_live'] is True


def test_portfolio_evidence_package_supports_real_s3_object_lock_backend_and_restore(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_201_000.0
    _set_now(monkeypatch, base_now)
    s3_storage: dict[tuple[str, str], dict[str, object]] = {}
    _install_fake_boto3(monkeypatch, s3_storage)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        runtime_id = _create_runtime(client, headers, name='runtime-s3-object-lock')
        portfolio_id = _create_submitted_portfolio(
            client,
            headers,
            base_now=base_now,
            runtime_id=runtime_id,
            export_policy={'enabled': True, 'require_signature': True, 'signer_key_id': 'portfolio-export-ci', 'timeline_limit': 120, 'embed_artifact_content': False},
            escrow_policy={
                'enabled': True,
                'provider': 'aws-s3-object-lock',
                'aws_s3_bucket': 'evidence-bucket',
                'aws_s3_prefix': 'regulated',
                'aws_region': 'eu-west-1',
                'require_archive_on_export': True,
                'allow_inline_fallback': False,
                'object_lock_enabled': True,
                'retention_mode': 'GOVERNANCE',
                'aws_s3_object_lock_legal_hold': True,
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
        assert payload['escrow']['provider'] == 'aws-s3-object-lock'
        assert payload['escrow']['archive_uri'].startswith('s3://evidence-bucket/')
        assert payload['escrow']['object_lock_enabled'] is True
        assert s3_storage

        verify = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-artifact-verify',
            headers=headers,
            json={'actor': 'auditor', 'package_id': payload['package_id'], 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert verify.status_code == 200, verify.text
        verified = verify.json()
        assert verified['verification']['status'] == 'verified'
        assert verified['verification']['escrow']['archive_backend'] == 's3_object_lock'
        assert verified['verification']['escrow']['object_lock_valid'] is True

        restore = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-artifact-restore',
            headers=headers,
            json={'actor': 'auditor', 'package_id': payload['package_id'], 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert restore.status_code == 200, restore.text
        restored = restore.json()
        assert restored['ok'] is True
        assert restored['package_id'] == payload['package_id']
        assert int(restored['restore']['summary']['replay_count'] or 0) > 0


def test_distributed_custody_quorum_and_leader_append_authority_gate_sensitive_restore(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_202_000.0
    _set_now(monkeypatch, base_now)
    sqlite_path = tmp_path / 'custody-ledger.sqlite3'
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        runtime_id = _create_runtime(client, headers, name='runtime-custody-quorum')
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
                'append_authority': 'leader',
                'leader_control_plane_id': 'cp-leader',
                'control_plane_id': 'cp-leader',
                'quorum_enabled': True,
                'quorum_size': 2,
                'require_quorum_for_reconciliation': True,
            },
            verification_gate_policy={
                'enabled': True,
                'require_before_sensitive_restore': True,
                'require_chain_reconciliation': True,
                'require_external_anchor_validation': True,
                'require_quorum_or_authority': True,
                'block_on_reconciliation_conflict': True,
            },
        )
        export = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-package-export',
            headers=headers,
            json={'actor': 'security-admin', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert export.status_code == 200, export.text
        payload = export.json()
        assert payload['ok'] is True
        assert payload['custody_anchor']['anchor_role'] == 'authority'

        restore_before = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-artifact-restore',
            headers=headers,
            json={'actor': 'auditor', 'package_id': payload['package_id'], 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert restore_before.status_code == 200, restore_before.text
        blocked = restore_before.json()
        assert blocked['ok'] is False
        assert blocked['reason'] == 'custody_anchor_quorum_or_authority_missing'

        attest = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/custody-anchors/attest',
            headers=headers,
            json={
                'actor': 'node-b-operator',
                'package_id': payload['package_id'],
                'control_plane_id': 'cp-node-b',
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert attest.status_code == 200, attest.text
        attested = attest.json()
        assert attested['ok'] is True
        assert attested['anchor']['anchor_role'] == 'witness'

        reconcile = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/custody-anchors/reconcile',
            headers=headers,
            json={'actor': 'ops-admin', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert reconcile.status_code == 200, reconcile.text
        reconciled = reconcile.json()
        assert reconciled['reconciliation']['status'] in {'reconciled', 'aligned'}
        assert reconciled['reconciliation']['quorum']['authority_satisfied'] is True
        assert reconciled['reconciliation']['quorum']['leader_present'] is True
        assert reconciled['reconciliation']['quorum']['distinct_control_plane_count'] == 2

        restore_after = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-artifact-restore',
            headers=headers,
            json={'actor': 'auditor', 'package_id': payload['package_id'], 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert restore_after.status_code == 200, restore_after.text
        restored = restore_after.json()
        assert restored['ok'] is True
        assert restored['verification_gate']['reconciliation']['quorum']['authority_satisfied'] is True
