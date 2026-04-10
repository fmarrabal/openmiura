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


class _FakeAzureBlobDownload:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def readall(self) -> bytes:
        return self.payload


class _FakeAzureBlobProperties:
    def __init__(self, record: dict[str, object]) -> None:
        self.metadata = dict(record.get('metadata') or {})
        self.immutability_policy = record.get('immutability_policy')
        self.has_legal_hold = bool(record.get('legal_hold', False))


class _FakeAzureBlobClient:
    def __init__(self, storage: dict[tuple[str, str], dict[str, object]], container: str, blob: str) -> None:
        self.storage = storage
        self.container = container
        self.blob = blob

    def upload_blob(self, data, overwrite: bool = False, metadata: dict[str, str] | None = None, content_type: str | None = None):
        key = (self.container, self.blob)
        if key in self.storage and not overwrite:
            raise RuntimeError('blob_exists')
        if hasattr(data, 'read'):
            data = data.read()
        self.storage[key] = {
            'body': bytes(data),
            'metadata': dict(metadata or {}),
            'content_type': content_type,
            'immutability_policy': None,
            'legal_hold': False,
        }

    def get_blob_properties(self):
        key = (self.container, self.blob)
        if key not in self.storage:
            raise RuntimeError('blob_missing')
        return _FakeAzureBlobProperties(self.storage[key])

    def download_blob(self):
        key = (self.container, self.blob)
        if key not in self.storage:
            raise RuntimeError('blob_missing')
        return _FakeAzureBlobDownload(bytes(self.storage[key]['body']))

    def set_immutability_policy(self, *, expiry_time, policy_mode: str):
        key = (self.container, self.blob)
        self.storage[key]['immutability_policy'] = {'expiry_time': expiry_time, 'policy_mode': policy_mode}

    def set_legal_hold(self, value: bool):
        key = (self.container, self.blob)
        self.storage[key]['legal_hold'] = bool(value)


class _FakeAzureContainerClient:
    def __init__(self, container: str) -> None:
        self.container = container

    def get_container_properties(self):
        return {'name': self.container, 'immutableStorageWithVersioning': {'enabled': True}}


class _FakeAzureBlobServiceClient:
    def __init__(self, storage: dict[tuple[str, str], dict[str, object]], account_url: str | None = None) -> None:
        self.storage = storage
        self.account_url = account_url or 'https://example.blob.core.windows.net/'

    @classmethod
    def from_connection_string(cls, connection_string: str):
        return cls({}, account_url='https://from-connection-string.blob.core.windows.net/')

    def get_container_client(self, container: str):
        return _FakeAzureContainerClient(container)

    def get_blob_client(self, *, container: str, blob: str):
        return _FakeAzureBlobClient(self.storage, container, blob)


class _FakeGCSBlob:
    def __init__(self, storage: dict[tuple[str, str], dict[str, object]], bucket: str, key: str) -> None:
        self.storage = storage
        self.bucket_name = bucket
        self.name = key
        self.metadata: dict[str, str] = {}
        self.temporary_hold = False
        self.event_based_hold = False
        self.retention_expiration_time = None

    def upload_from_string(self, data: bytes, content_type: str | None = None):
        self.storage[(self.bucket_name, self.name)] = {
            'body': bytes(data),
            'metadata': dict(self.metadata),
            'temporary_hold': self.temporary_hold,
            'event_based_hold': self.event_based_hold,
            'retention_expiration_time': self.retention_expiration_time,
            'content_type': content_type,
        }

    def reload(self):
        record = self.storage.get((self.bucket_name, self.name))
        if record is None:
            raise RuntimeError('blob_missing')
        self.metadata = dict(record.get('metadata') or {})
        self.temporary_hold = bool(record.get('temporary_hold', False))
        self.event_based_hold = bool(record.get('event_based_hold', False))
        self.retention_expiration_time = record.get('retention_expiration_time')

    def download_as_bytes(self) -> bytes:
        record = self.storage.get((self.bucket_name, self.name))
        if record is None:
            raise RuntimeError('blob_missing')
        return bytes(record.get('body') or b'')


class _FakeGCSBucket:
    def __init__(self, storage: dict[tuple[str, str], dict[str, object]], name: str) -> None:
        self.storage = storage
        self.name = name
        self.retention_period = 3600

    def reload(self):
        return None

    def blob(self, key: str):
        return _FakeGCSBlob(self.storage, self.name, key)


class _FakeGCSClient:
    def __init__(self, storage: dict[tuple[str, str], dict[str, object]], project: str | None = None) -> None:
        self.storage = storage
        self.project = project

    @classmethod
    def from_service_account_json(cls, path: str, project: str | None = None):
        return cls({}, project=project)

    def bucket(self, name: str):
        return _FakeGCSBucket(self.storage, name)



def _install_fake_azure_blob(monkeypatch, storage: dict[tuple[str, str], dict[str, object]]) -> None:
    module = types.ModuleType('azure.storage.blob')
    module.BlobServiceClient = lambda account_url=None, credential=None: _FakeAzureBlobServiceClient(storage, account_url=account_url)
    monkeypatch.setitem(sys.modules, 'azure.storage.blob', module)



def _install_fake_gcs_storage(monkeypatch, storage: dict[tuple[str, str], dict[str, object]]) -> None:
    google_mod = sys.modules.get('google') or types.ModuleType('google')
    cloud_mod = sys.modules.get('google.cloud') or types.ModuleType('google.cloud')
    storage_mod = types.ModuleType('google.cloud.storage')
    storage_mod.Client = lambda project=None: _FakeGCSClient(storage, project=project)
    storage_mod.Client.from_service_account_json = classmethod(lambda cls, path, project=None: _FakeGCSClient(storage, project=project))
    monkeypatch.setitem(sys.modules, 'google', google_mod)
    monkeypatch.setitem(sys.modules, 'google.cloud', cloud_mod)
    monkeypatch.setitem(sys.modules, 'google.cloud.storage', storage_mod)



def test_portfolio_provider_validation_supports_cross_cloud_immutable_backends(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_500_000.0
    _set_now(monkeypatch, base_now)
    azure_storage: dict[tuple[str, str], dict[str, object]] = {}
    gcs_storage: dict[tuple[str, str], dict[str, object]] = {}
    _install_fake_azure_blob(monkeypatch, azure_storage)
    _install_fake_gcs_storage(monkeypatch, gcs_storage)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    backends = [
        ({'enabled': True, 'provider': 'azure-blob-immutable', 'azure_blob_account_url': 'https://acct.blob.core.windows.net/', 'azure_blob_container': 'evidence'}, 'azure-blob-immutable'),
        ({'enabled': True, 'provider': 'gcs-retention-lock', 'gcs_bucket': 'evidence-bucket', 'gcs_project': 'demo-project'}, 'gcs-retention-lock'),
    ]

    with TestClient(app) as client:
        runtime_id = _create_runtime(client, headers, name='runtime-cross-cloud-validate')
        for index, (escrow_policy, expected_provider) in enumerate(backends, start=1):
            portfolio_id = _create_submitted_portfolio(client, headers, base_now=base_now + index, runtime_id=runtime_id, escrow_policy=escrow_policy)
            response = client.post(
                f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/provider-validation',
                headers=headers,
                json={'actor': 'ops-admin', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
            )
            assert response.status_code == 200, response.text
            payload = response.json()
            assert payload['ok'] is True
            assert payload['provider_validation']['escrow']['provider'] == expected_provider
            assert payload['provider_validation']['escrow']['valid'] is True
            assert payload['provider_validation']['escrow']['provider_live'] is True



def test_portfolio_evidence_package_supports_azure_blob_and_gcs_immutable_archives(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_501_000.0
    _set_now(monkeypatch, base_now)
    azure_storage: dict[tuple[str, str], dict[str, object]] = {}
    gcs_storage: dict[tuple[str, str], dict[str, object]] = {}
    _install_fake_azure_blob(monkeypatch, azure_storage)
    _install_fake_gcs_storage(monkeypatch, gcs_storage)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    configs = [
        ({'enabled': True, 'provider': 'azure-blob-immutable', 'azure_blob_account_url': 'https://acct.blob.core.windows.net/', 'azure_blob_container': 'evidence', 'require_archive_on_export': True, 'allow_inline_fallback': False}, 'azblob://'),
        ({'enabled': True, 'provider': 'gcs-retention-lock', 'gcs_bucket': 'evidence-bucket', 'gcs_project': 'demo-project', 'require_archive_on_export': True, 'allow_inline_fallback': False}, 'gs://'),
    ]

    with TestClient(app) as client:
        runtime_id = _create_runtime(client, headers, name='runtime-cross-cloud-export')
        for index, (escrow_policy, prefix) in enumerate(configs, start=1):
            portfolio_id = _create_submitted_portfolio(
                client,
                headers,
                base_now=base_now + index,
                runtime_id=runtime_id,
                export_policy={'enabled': True, 'require_signature': True, 'signer_key_id': 'portfolio-export-ci', 'timeline_limit': 120, 'embed_artifact_content': False},
                escrow_policy=escrow_policy,
            )
            export = client.post(
                f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-package-export',
                headers=headers,
                json={'actor': 'auditor', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
            )
            assert export.status_code == 200, export.text
            payload = export.json()
            assert payload['ok'] is True
            assert payload['escrow']['archive_uri'].startswith(prefix)
            verify = client.post(
                f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-artifact-verify',
                headers=headers,
                json={'actor': 'auditor', 'package_id': payload['package_id'], 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
            )
            assert verify.status_code == 200, verify.text
            verified = verify.json()
            assert verified['verification']['status'] == 'verified'
            assert verified['verification']['escrow']['archive_backend'] in {'azure_blob_immutable', 'gcs_retention_lock'}



def test_environment_specific_quorum_witness_policy_is_enforced_in_prod(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_502_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        runtime_id = _create_runtime(client, headers, name='runtime-env-quorum')
        portfolio_id = _create_submitted_portfolio(
            client,
            headers,
            base_now=base_now,
            runtime_id=runtime_id,
            custody_anchor_policy={
                'enabled': True,
                'provider': 'filesystem-ledger',
                'root_dir': str((tmp_path / 'custody').resolve()),
                'anchor_on_export': True,
                'require_anchor_on_export': True,
                'control_plane_id': 'cp-leader',
                'append_authority': 'any',
                'quorum_enabled': False,
                'environment_policies': {
                    'prod': {
                        'append_authority': 'leader',
                        'leader_control_plane_id': 'cp-leader',
                        'quorum_enabled': True,
                        'quorum_size': 3,
                        'require_quorum_for_reconciliation': True,
                        'required_witness_count': 2,
                    }
                },
            },
            verification_gate_policy={
                'enabled': True,
                'require_before_sensitive_restore': True,
                'require_chain_reconciliation': True,
                'require_external_anchor_validation': True,
                'require_verified_artifact_for_restore': True,
                'require_quorum_or_authority': True,
            },
        )
        export = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-package-export',
            headers=headers,
            json={'actor': 'auditor', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert export.status_code == 200, export.text
        payload = export.json()
        package_id = payload['package_id']

        client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/custody-anchors/attest',
            headers=headers,
            json={'actor': 'cp2', 'package_id': package_id, 'control_plane_id': 'cp-w1', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        reconcile = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/custody-anchors/reconcile',
            headers=headers,
            json={'actor': 'ops-admin', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert reconcile.status_code == 200, reconcile.text
        reconciled = reconcile.json()
        assert reconciled['reconciliation']['quorum']['required_witness_count'] == 2
        assert reconciled['reconciliation']['quorum']['witness_count'] == 1
        assert reconciled['reconciliation']['status'] in {'witness_pending', 'quorum_pending'}

        restore = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-artifact-restore',
            headers=headers,
            json={'actor': 'auditor', 'package_id': package_id, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert restore.status_code == 200, restore.text
        assert restore.json()['ok'] is False

        client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/custody-anchors/attest',
            headers=headers,
            json={'actor': 'cp3', 'package_id': package_id, 'control_plane_id': 'cp-w2', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        reconcile = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/custody-anchors/reconcile',
            headers=headers,
            json={'actor': 'ops-admin', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        reconciled = reconcile.json()
        assert reconciled['reconciliation']['quorum']['authority_satisfied'] is True
        assert reconciled['reconciliation']['quorum']['witness_count'] == 2

        restore = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-artifact-restore',
            headers=headers,
            json={'actor': 'auditor', 'package_id': package_id, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert restore.status_code == 200, restore.text
        assert restore.json()['ok'] is True



def test_mandatory_verify_on_read_blocks_evidence_reads_after_tamper(tmp_path: Path, monkeypatch) -> None:
    base_now = 1_785_503_000.0
    _set_now(monkeypatch, base_now)
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}

    with TestClient(app) as client:
        runtime_id = _create_runtime(client, headers, name='runtime-verify-on-read')
        portfolio_id = _create_submitted_portfolio(
            client,
            headers,
            base_now=base_now,
            runtime_id=runtime_id,
            export_policy={'enabled': True, 'require_signature': True, 'signer_key_id': 'portfolio-export-ci', 'timeline_limit': 120, 'embed_artifact_content': False},
            escrow_policy={'enabled': True, 'provider': 'filesystem-governed', 'root_dir': str((tmp_path / 'escrow').resolve()), 'require_archive_on_export': True, 'allow_inline_fallback': False},
            verification_gate_policy={'enabled': True, 'require_verify_on_read': True, 'block_on_failed_verify_on_read': True, 'verify_on_read_latest_only': True},
        )
        export = client.post(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-package-export',
            headers=headers,
            json={'actor': 'auditor', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert export.status_code == 200, export.text
        payload = export.json()
        archive_path = Path(payload['escrow']['archive_path'])
        archive_path.write_bytes(b'tampered-artifact')

        listed = client.get(
            f'/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-packages?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert listed.status_code == 200, listed.text
        data = listed.json()
        assert data['ok'] is False
        assert data['error'] == 'portfolio_verify_on_read_failed'
        assert data['read_verification']['valid'] is False
