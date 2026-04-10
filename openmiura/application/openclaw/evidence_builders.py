from __future__ import annotations

import base64
import hashlib
import io
import json
import uuid
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any





class OpenClawEvidenceBuildersMixin:
    def _portfolio_chain_of_custody_summary(self, release: dict[str, Any]) -> dict[str, Any]:
        entries = self._list_portfolio_chain_of_custody_entries(release)
        verified = self._verify_portfolio_chain_of_custody_entries(entries)
        by_event: dict[str, int] = {}
        for item in entries:
            event_type = str(item.get('event_type') or 'unknown')
            by_event[event_type] = by_event.get(event_type, 0) + 1
        return {
            **verified,
            'by_event_type': by_event,
            'latest_entry_id': entries[-1].get('entry_id') if entries else None,
        }


    def _portfolio_custody_anchor_summary(self, release: dict[str, Any]) -> dict[str, Any]:
        receipts = self._list_portfolio_custody_anchor_receipts(release)
        latest = receipts[-1] if receipts else None
        raw_policy = (((((release.get('metadata') or {}).get('portfolio') or {}).get('train_policy') or {}).get('custody_anchor_policy') or {}))
        policy = self._resolve_portfolio_custody_anchor_policy_for_environment(raw_policy, environment=release.get('environment'))
        verify = self._verify_portfolio_custody_anchor_receipts(
            receipts,
            expected_chain_head_hash=None,
            expected_portfolio_id=str(release.get('release_id') or '') if receipts else None,
        ) if receipts else {'count': 0, 'valid': True, 'chain_valid': True, 'signature_valid_count': 0, 'invalid_anchor_ids': []}
        reconciliation = dict((((release.get('metadata') or {}).get('portfolio') or {}).get('current_custody_reconciliation') or {}) or {})
        quorum = self._portfolio_custody_quorum_view(receipts, custody_anchor_policy=policy)
        return {
            **verify,
            'latest_anchor_id': (latest or {}).get('anchor_id'),
            'anchored_count': len(receipts),
            'latest_anchor_path': (latest or {}).get('archive_path'),
            'reconciliation_status': reconciliation.get('status'),
            'reconciliation_conflict_count': int(reconciliation.get('conflict_count') or 0),
            'reconciliation_imported_count': int(reconciliation.get('imported_count') or 0),
            'reconciled': bool(reconciliation.get('status') in {'aligned', 'reconciled'}),
            'quorum': quorum,
            'quorum_satisfied': bool(quorum.get('authority_satisfied')),
        }


    def _portfolio_evidence_integrity(
        self,
        *,
        report_type: str,
        scope: dict[str, Any],
        payload: dict[str, Any],
        actor: str,
        export_policy: dict[str, Any] | None = None,
        signing_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_policy = self._normalize_portfolio_export_policy(dict(export_policy or {}))
        normalized_signing_policy = self._normalize_portfolio_signing_policy(dict(signing_policy or {}))
        generated_at = float(payload.get('generated_at') or time.time())
        signer_key_id = str(normalized_policy.get('signer_key_id') or normalized_signing_policy.get('key_id') or 'openmiura-local').strip() or 'openmiura-local'
        payload_hash = self._stable_digest(payload)
        signed = bool(normalized_policy.get('require_signature', True))
        signature = None
        signature_scheme = None
        signature_input: dict[str, Any] | None = None
        signature_input_hash = None
        public_key: dict[str, Any] | None = None
        legacy_signature = None
        signer_provider = None
        key_origin = None
        if signed:
            crypto = self._sign_portfolio_payload_crypto_v2(
                report_type=report_type,
                scope=dict(scope or {}),
                payload=dict(payload or {}),
                signer_key_id=signer_key_id,
                signing_policy=normalized_signing_policy,
            )
            signature = crypto.get('signature')
            signature_scheme = crypto.get('signature_scheme')
            signature_input = dict(crypto.get('signature_input') or {})
            signature_input_hash = crypto.get('signature_input_hash')
            public_key = dict(crypto.get('public_key') or {})
            signer_provider = crypto.get('signer_provider')
            key_origin = crypto.get('key_origin')
            legacy_signature = self._stable_digest({
                'report_type': str(report_type or '').strip(),
                'scope': dict(scope or {}),
                'payload': dict(payload or {}),
                'signer_key_id': signer_key_id,
            })
        return {
            'algorithm': 'sha256',
            'payload_hash': payload_hash,
            'signed': signed,
            'signature': signature,
            'signature_scheme': signature_scheme,
            'signature_input': signature_input,
            'signature_input_hash': signature_input_hash,
            'public_key': public_key,
            'crypto_v2': bool(signature),
            'legacy_signature': legacy_signature,
            'signer_key_id': signer_key_id,
            'signer_provider': signer_provider,
            'key_origin': key_origin,
            'signed_by': str(actor or 'system').strip() or 'system',
            'signed_at': generated_at,
        }


    def _portfolio_evidence_package_manifest(
        self,
        *,
        package_id: str,
        detail: dict[str, Any],
        attestation_export: dict[str, Any],
        postmortem_export: dict[str, Any],
        chain_of_custody: dict[str, Any] | None = None,
        custody_anchor: dict[str, Any] | None = None,
        generated_at: float,
        actor: str,
        retention: dict[str, Any],
    ) -> tuple[dict[str, Any], str]:
        artifacts = [
            {
                'artifact_id': 'attestation_export',
                'report_type': ((attestation_export.get('report') or {}).get('report_type')),
                'payload_hash': ((attestation_export.get('integrity') or {}).get('payload_hash')),
                'signature': ((attestation_export.get('integrity') or {}).get('signature')),
                'attestation_id': attestation_export.get('attestation_id'),
            },
            {
                'artifact_id': 'postmortem_export',
                'report_type': ((postmortem_export.get('report') or {}).get('report_type')),
                'payload_hash': ((postmortem_export.get('integrity') or {}).get('payload_hash')),
                'signature': ((postmortem_export.get('integrity') or {}).get('signature')),
                'attestation_id': postmortem_export.get('attestation_id'),
            },
        ]
        if chain_of_custody:
            artifacts.append({
                'artifact_id': 'chain_of_custody',
                'report_type': str(chain_of_custody.get('ledger_type') or 'openmiura_portfolio_chain_of_custody_v1'),
                'payload_hash': self._stable_digest(chain_of_custody),
                'signature': None,
                'attestation_id': attestation_export.get('attestation_id'),
            })
        if custody_anchor:
            artifacts.append({
                'artifact_id': 'custody_anchor',
                'report_type': str(custody_anchor.get('receipt_type') or 'openmiura_portfolio_custody_anchor_receipt_v1'),
                'payload_hash': self._stable_digest(custody_anchor),
                'signature': ((custody_anchor.get('integrity') or {}).get('signature')),
                'attestation_id': attestation_export.get('attestation_id'),
            })
        manifest = {
            'manifest_type': 'openmiura_portfolio_evidence_manifest_v1',
            'package_id': str(package_id or '').strip(),
            'generated_at': float(generated_at),
            'generated_by': str(actor or 'system').strip() or 'system',
            'portfolio': {
                'portfolio_id': detail.get('portfolio_id'),
                'name': ((detail.get('release') or {}).get('name')),
                'version': ((detail.get('release') or {}).get('version')),
                'status': ((detail.get('release') or {}).get('status')),
            },
            'scope': dict(detail.get('scope') or {}),
            'artifacts': artifacts,
            'retention': {
                'classification': retention.get('classification'),
                'operational_tier': retention.get('operational_tier'),
                'state': retention.get('state'),
                'retain_until': retention.get('retain_until'),
                'legal_hold': retention.get('legal_hold'),
            },
        }
        manifest_hash = self._stable_digest(manifest)
        return manifest, manifest_hash


    def _archive_portfolio_evidence_artifact_external(
        self,
        *,
        artifact: dict[str, Any],
        package_payload: dict[str, Any],
        integrity: dict[str, Any],
        retention: dict[str, Any],
        actor: str,
        escrow_policy: dict[str, Any] | None = None,
        signing_policy: dict[str, Any] | None = None,
        generated_at: float | None = None,
    ) -> dict[str, Any]:
        normalized = self._normalize_portfolio_escrow_policy(dict(escrow_policy or {}))
        if not bool(normalized.get('enabled')):
            return {
                'enabled': False,
                'archived': False,
                'provider': normalized.get('provider'),
                'reason': 'escrow_disabled',
            }
        content_b64 = str(artifact.get('content_b64') or '').strip()
        if not content_b64:
            return {
                'enabled': True,
                'archived': False,
                'provider': normalized.get('provider'),
                'reason': 'artifact_content_missing',
            }
        generated_ts = float(generated_at) if generated_at is not None else float(package_payload.get('generated_at') or time.time())
        scope = dict(package_payload.get('scope') or {})
        archive_bytes = base64.b64decode(content_b64.encode('ascii'))
        artifact_sha256 = hashlib.sha256(archive_bytes).hexdigest()
        receipt_id = str(uuid.uuid4())
        provider = str(normalized.get('provider') or 'filesystem-governed').strip() or 'filesystem-governed'
        filename = str(artifact.get('filename') or f'{package_payload.get("package_id")}.zip').strip() or f'{package_payload.get("package_id")}.zip'
        portfolio_id = str(((package_payload.get('portfolio') or {}).get('portfolio_id')) or '').strip() or 'portfolio'
        package_id = str(package_payload.get('package_id') or '').strip() or 'package'
        manifest_payload = dict((package_payload.get('manifest') or {}))
        manifest_bytes = self._canonical_json_bytes(manifest_payload)
        immutable_until = retention.get('retain_until')
        if immutable_until is None:
            immutable_until = generated_ts + (max(1, int(normalized.get('immutable_retention_days') or 365)) * 86400.0)
        if provider in {'aws-s3-object-lock', 's3-object-lock'}:
            bucket = str(normalized.get('aws_s3_bucket') or '').strip()
            if not bucket:
                return {
                    'enabled': True,
                    'archived': False,
                    'provider': provider,
                    'reason': 'aws_s3_bucket_missing',
                }
            archive_key = self._aws_s3_key_for_artifact(policy=normalized, scope=scope, portfolio_id=portfolio_id, package_id=package_id, filename=filename)
            receipt_key = f'{archive_key}.receipt.json'
            manifest_key = '/'.join([part for part in archive_key.split('/')[:-1] if part] + ['manifest.json'])
            lock_key = f'{archive_key}.lock.json'
            client = self._aws_s3_client_for_policy(normalized)
            archive_uri = self._s3_uri(bucket, archive_key)
            try:
                existing_head = client.head_object(Bucket=bucket, Key=archive_key)
            except Exception:
                existing_head = None
            if existing_head is not None:
                existing_meta = {str(k).lower(): str(v) for k, v in dict(existing_head.get('Metadata') or {}).items()}
                existing_sha = existing_meta.get('artifact_sha256')
                if existing_sha and existing_sha != artifact_sha256:
                    return {
                        'enabled': True,
                        'archived': False,
                        'provider': provider,
                        'reason': 'immutable_archive_conflict',
                        'archive_uri': archive_uri,
                    }
            else:
                put_kwargs = {
                    'Bucket': bucket,
                    'Key': archive_key,
                    'Body': archive_bytes,
                    'ContentType': 'application/zip',
                    'Metadata': {
                        'artifact_sha256': artifact_sha256,
                        'manifest_hash': str(manifest_payload.get('manifest_hash') or ''),
                        'portfolio_id': portfolio_id,
                        'package_id': package_id,
                    },
                }
                if normalized.get('aws_s3_storage_class'):
                    put_kwargs['StorageClass'] = str(normalized.get('aws_s3_storage_class'))
                if normalized.get('aws_s3_sse'):
                    put_kwargs['ServerSideEncryption'] = str(normalized.get('aws_s3_sse'))
                if normalized.get('aws_s3_kms_key_id'):
                    put_kwargs['SSEKMSKeyId'] = str(normalized.get('aws_s3_kms_key_id'))
                if bool(normalized.get('object_lock_enabled')):
                    put_kwargs['ObjectLockMode'] = str(normalized.get('retention_mode') or 'GOVERNANCE')
                    put_kwargs['ObjectLockRetainUntilDate'] = datetime.fromtimestamp(float(immutable_until), tz=timezone.utc)
                client.put_object(**put_kwargs)
                if bool(retention.get('legal_hold')) or bool(normalized.get('aws_s3_object_lock_legal_hold')):
                    client.put_object_legal_hold(Bucket=bucket, Key=archive_key, LegalHold={'Status': 'ON'})
            client.put_object(Bucket=bucket, Key=manifest_key, Body=manifest_bytes, ContentType='application/json')
            lock_payload = None
            if bool(normalized.get('object_lock_enabled')):
                lock_payload = {
                    'lock_type': 'openmiura_portfolio_object_lock_v1',
                    'provider': provider,
                    'archive_uri': archive_uri,
                    'bucket': bucket,
                    'key': archive_key,
                    'artifact_sha256': artifact_sha256,
                    'package_id': package_id,
                    'portfolio_id': portfolio_id,
                    'immutable_until': immutable_until,
                    'retention_mode': str(normalized.get('retention_mode') or 'GOVERNANCE'),
                    'legal_hold': bool(retention.get('legal_hold', False)) or bool(normalized.get('aws_s3_object_lock_legal_hold')),
                    'locked_at': generated_ts,
                }
                if bool(normalized.get('lock_sidecar', True)):
                    client.put_object(Bucket=bucket, Key=lock_key, Body=self._canonical_json_bytes(lock_payload), ContentType='application/json')
            receipt_payload = {
                'receipt_type': 'openmiura_portfolio_evidence_escrow_receipt_v1',
                'receipt_id': receipt_id,
                'provider': provider,
                'mode': str(normalized.get('mode') or 's3_object_lock'),
                'archived': True,
                'archived_at': generated_ts,
                'archived_by': str(actor or 'system').strip() or 'system',
                'package_id': package_id,
                'portfolio_id': portfolio_id,
                'scope': scope,
                'archive_path': archive_uri,
                'archive_uri': archive_uri,
                'receipt_path': self._s3_uri(bucket, receipt_key),
                'manifest_path': self._s3_uri(bucket, manifest_key),
                'artifact_sha256': artifact_sha256,
                'manifest_hash': manifest_payload.get('manifest_hash'),
                'immutable_until': immutable_until,
                'classification': retention.get('classification'),
                'legal_hold': bool(retention.get('legal_hold', False)) or bool(normalized.get('aws_s3_object_lock_legal_hold')),
                'object_lock_enabled': bool(normalized.get('object_lock_enabled')),
                'retention_mode': str(normalized.get('retention_mode') or 'GOVERNANCE'),
                'lock_path': self._s3_uri(bucket, lock_key) if bool(normalized.get('object_lock_enabled')) and bool(normalized.get('lock_sidecar', True)) else None,
                'delete_protection': True,
                'bucket': bucket,
                'key': archive_key,
                'aws_region': normalized.get('aws_region'),
                'aws_profile': normalized.get('aws_profile'),
                'aws_endpoint_url': normalized.get('aws_endpoint_url'),
            }
            crypto = self._sign_portfolio_payload_crypto_v2(
                report_type='openmiura_portfolio_evidence_escrow_receipt_v1',
                scope=scope,
                payload=receipt_payload,
                signer_key_id=str(normalized.get('escrow_key_id') or 'openmiura-escrow').strip() or 'openmiura-escrow',
                signing_policy=signing_policy,
            )
            receipt_payload.update({
                'signature': crypto.get('signature'),
                'signature_scheme': crypto.get('signature_scheme'),
                'signature_input': crypto.get('signature_input'),
                'public_key': crypto.get('public_key'),
                'crypto_v2': True,
                'signer_provider': crypto.get('signer_provider'),
                'key_origin': crypto.get('key_origin'),
            })
            if bool(normalized.get('write_receipt_sidecar', True)):
                client.put_object(Bucket=bucket, Key=receipt_key, Body=self._canonical_json_bytes(receipt_payload), ContentType='application/json')
            return receipt_payload
        if provider == 'azure-blob-immutable':
            container = str(normalized.get('azure_blob_container') or '').strip()
            if not container:
                return {
                    'enabled': True,
                    'archived': False,
                    'provider': provider,
                    'reason': 'azure_blob_container_missing',
                }
            blob_name = self._azure_blob_name_for_artifact(policy=normalized, scope=scope, portfolio_id=portfolio_id, package_id=package_id, filename=filename)
            archive_uri = self._azblob_uri(container, blob_name)
            service = self._azure_blob_service_client_for_policy(normalized)
            blob_client = service.get_blob_client(container=container, blob=blob_name)
            existing_props = None
            try:
                existing_props = blob_client.get_blob_properties()
            except Exception:
                existing_props = None
            if existing_props is not None:
                existing_meta = {str(k).lower(): str(v) for k, v in dict(getattr(existing_props, 'metadata', None) or {}).items()}
                existing_sha = existing_meta.get('artifact_sha256')
                if existing_sha and existing_sha != artifact_sha256:
                    return {'enabled': True, 'archived': False, 'provider': provider, 'reason': 'immutable_archive_conflict', 'archive_uri': archive_uri}
            else:
                metadata = {'artifact_sha256': artifact_sha256, 'manifest_hash': str(manifest_payload.get('manifest_hash') or ''), 'package_id': package_id, 'portfolio_id': portfolio_id}
                try:
                    blob_client.upload_blob(archive_bytes, overwrite=False, metadata=metadata, content_type='application/zip')
                except TypeError:
                    blob_client.upload_blob(archive_bytes, overwrite=False, metadata=metadata)
                if hasattr(blob_client, 'set_immutability_policy'):
                    try:
                        blob_client.set_immutability_policy(expiry_time=immutable_until, policy_mode=str(normalized.get('azure_blob_immutable_policy_mode') or 'Unlocked'))
                    except Exception:
                        pass
                if bool(normalized.get('azure_blob_legal_hold', False)) and hasattr(blob_client, 'set_legal_hold'):
                    try:
                        blob_client.set_legal_hold(True)
                    except Exception:
                        pass
            receipt_payload = {
                'receipt_type': 'openmiura_portfolio_evidence_escrow_receipt_v1',
                'receipt_id': receipt_id,
                'provider': provider,
                'mode': str(normalized.get('mode') or 'azure_blob_immutable'),
                'archived': True,
                'archived_at': generated_ts,
                'archived_by': str(actor or 'system').strip() or 'system',
                'package_id': package_id,
                'portfolio_id': portfolio_id,
                'scope': scope,
                'archive_path': archive_uri,
                'archive_uri': archive_uri,
                'receipt_path': None,
                'manifest_path': None,
                'artifact_sha256': artifact_sha256,
                'manifest_hash': ((package_payload.get('manifest') or {}).get('manifest_hash')),
                'immutable_until': immutable_until,
                'classification': retention.get('classification'),
                'legal_hold': bool(retention.get('legal_hold', False) or normalized.get('azure_blob_legal_hold', False)),
                'object_lock_enabled': True,
                'retention_mode': str(normalized.get('retention_mode') or 'GOVERNANCE'),
                'lock_path': None,
                'delete_protection': bool(normalized.get('delete_protection', True)),
                'container': container,
                'blob_name': blob_name,
                'azure_blob_account_url': str(normalized.get('azure_blob_account_url') or '').strip() or None,
            }
            crypto = self._sign_portfolio_payload_crypto_v2(
                report_type='openmiura_portfolio_evidence_escrow_receipt_v1',
                scope=scope,
                payload=receipt_payload,
                signer_key_id=str(normalized.get('escrow_key_id') or 'openmiura-escrow').strip() or 'openmiura-escrow',
                signing_policy=signing_policy,
            )
            receipt_payload.update({'signature': crypto.get('signature'), 'signature_scheme': crypto.get('signature_scheme'), 'signature_input': crypto.get('signature_input'), 'public_key': crypto.get('public_key'), 'crypto_v2': True, 'signer_provider': crypto.get('signer_provider'), 'key_origin': crypto.get('key_origin')})
            return receipt_payload
        if provider == 'gcs-retention-lock':
            bucket_name = str(normalized.get('gcs_bucket') or '').strip()
            if not bucket_name:
                return {'enabled': True, 'archived': False, 'provider': provider, 'reason': 'gcs_bucket_missing'}
            key = self._gcs_key_for_artifact(policy=normalized, scope=scope, portfolio_id=portfolio_id, package_id=package_id, filename=filename)
            archive_uri = self._gs_uri(bucket_name, key)
            client = self._gcs_client_for_policy(normalized)
            bucket = client.bucket(bucket_name)
            blob = bucket.blob(key)
            try:
                blob.reload()
                existing_sha = str((getattr(blob, 'metadata', None) or {}).get('artifact_sha256') or '')
                if existing_sha and existing_sha != artifact_sha256:
                    return {'enabled': True, 'archived': False, 'provider': provider, 'reason': 'immutable_archive_conflict', 'archive_uri': archive_uri}
            except Exception:
                metadata = {'artifact_sha256': artifact_sha256, 'manifest_hash': str(manifest_payload.get('manifest_hash') or ''), 'package_id': package_id, 'portfolio_id': portfolio_id}
                blob.metadata = metadata
                if bool(normalized.get('gcs_temporary_hold', True)):
                    try:
                        blob.temporary_hold = True
                    except Exception:
                        pass
                if bool(normalized.get('gcs_event_based_hold', False)):
                    try:
                        blob.event_based_hold = True
                    except Exception:
                        pass
                if immutable_until is not None and hasattr(blob, 'retention_expiration_time'):
                    try:
                        blob.retention_expiration_time = datetime.fromtimestamp(float(immutable_until), tz=timezone.utc)
                    except Exception:
                        pass
                if hasattr(blob, 'upload_from_string'):
                    blob.upload_from_string(archive_bytes, content_type='application/zip')
                if hasattr(blob, 'patch'):
                    try:
                        blob.patch()
                    except Exception:
                        pass
            receipt_payload = {
                'receipt_type': 'openmiura_portfolio_evidence_escrow_receipt_v1',
                'receipt_id': receipt_id,
                'provider': provider,
                'mode': str(normalized.get('mode') or 'gcs_retention_lock'),
                'archived': True,
                'archived_at': generated_ts,
                'archived_by': str(actor or 'system').strip() or 'system',
                'package_id': package_id,
                'portfolio_id': portfolio_id,
                'scope': scope,
                'archive_path': archive_uri,
                'archive_uri': archive_uri,
                'receipt_path': None,
                'manifest_path': None,
                'artifact_sha256': artifact_sha256,
                'manifest_hash': ((package_payload.get('manifest') or {}).get('manifest_hash')),
                'immutable_until': immutable_until,
                'classification': retention.get('classification'),
                'legal_hold': bool(retention.get('legal_hold', False)),
                'object_lock_enabled': True,
                'retention_mode': str(normalized.get('retention_mode') or 'GOVERNANCE'),
                'lock_path': None,
                'delete_protection': bool(normalized.get('delete_protection', True)),
                'bucket': bucket_name,
                'gcs_key': key,
                'gcs_project': str(normalized.get('gcs_project') or '').strip() or None,
            }
            crypto = self._sign_portfolio_payload_crypto_v2(
                report_type='openmiura_portfolio_evidence_escrow_receipt_v1',
                scope=scope,
                payload=receipt_payload,
                signer_key_id=str(normalized.get('escrow_key_id') or 'openmiura-escrow').strip() or 'openmiura-escrow',
                signing_policy=signing_policy,
            )
            receipt_payload.update({'signature': crypto.get('signature'), 'signature_scheme': crypto.get('signature_scheme'), 'signature_input': crypto.get('signature_input'), 'public_key': crypto.get('public_key'), 'crypto_v2': True, 'signer_provider': crypto.get('signer_provider'), 'key_origin': crypto.get('key_origin')})
            return receipt_payload
        root_dir = Path(str(normalized.get('root_dir') or 'data/openclaw_evidence_escrow')).expanduser().resolve()
        namespace = str(normalized.get('archive_namespace') or 'portfolio-evidence').strip() or 'portfolio-evidence'
        path_parts = [namespace, str(scope.get('tenant_id') or 'global'), str(scope.get('workspace_id') or 'default'), str(scope.get('environment') or 'default'), portfolio_id, package_id]
        base_dir = root_dir.joinpath(*path_parts)
        base_dir.mkdir(parents=True, exist_ok=True)
        archive_path = base_dir / filename
        receipt_path = base_dir / f'{filename}.receipt.json'
        manifest_path = base_dir / 'manifest.json'
        lock_path = base_dir / f'{filename}.lock.json'

        archive_path_public = self._filesystem_path(archive_path)
        receipt_path_public = self._filesystem_path(receipt_path)
        manifest_path_public = self._filesystem_path(manifest_path)
        lock_path_public = self._filesystem_path(lock_path)

        if self._path_exists(archive_path):
            existing_bytes = self._read_file_bytes(archive_path)
            if hashlib.sha256(existing_bytes).hexdigest() != artifact_sha256:
                return {
                    'enabled': True,
                    'archived': False,
                    'provider': normalized.get('provider'),
                    'reason': 'immutable_archive_conflict',
                    'archive_path': archive_path_public,
                }
        else:
            self._write_file_if_absent(archive_path, archive_bytes)
        if not self._path_exists(manifest_path):
            self._write_file_if_absent(manifest_path, manifest_bytes)
        lock_payload = None
        object_lock_enabled = bool(normalized.get('object_lock_enabled'))
        if object_lock_enabled:
            lock_payload = {
                'lock_type': 'openmiura_portfolio_object_lock_v1',
                'provider': str(normalized.get('provider') or 'filesystem-object-lock'),
                'archive_path': archive_path_public,
                'artifact_sha256': artifact_sha256,
                'package_id': package_id,
                'portfolio_id': portfolio_id,
                'immutable_until': immutable_until,
                'retention_mode': str(normalized.get('retention_mode') or 'GOVERNANCE'),
                'legal_hold': bool(retention.get('legal_hold', False)),
                'locked_at': generated_ts,
            }
            if self._path_exists(lock_path):
                existing_lock = json.loads(self._read_file_text(lock_path, encoding='utf-8'))
                if str(existing_lock.get('artifact_sha256') or '') != artifact_sha256:
                    return {
                        'enabled': True,
                        'archived': False,
                        'provider': normalized.get('provider'),
                        'reason': 'object_lock_conflict',
                        'lock_path': lock_path_public,
                    }
            elif bool(normalized.get('lock_sidecar', True)):
                self._write_file_if_absent(lock_path, self._canonical_json_bytes(lock_payload))
        receipt_payload = {
            'receipt_type': 'openmiura_portfolio_evidence_escrow_receipt_v1',
            'receipt_id': receipt_id,
            'provider': str(normalized.get('provider') or 'filesystem-governed'),
            'mode': str(normalized.get('mode') or 'filesystem_external'),
            'archived': True,
            'archived_at': generated_ts,
            'archived_by': str(actor or 'system').strip() or 'system',
            'package_id': package_id,
            'portfolio_id': portfolio_id,
            'scope': scope,
            'archive_path': archive_path_public,
            'archive_uri': f'file://{archive_path_public}',
            'receipt_path': receipt_path_public,
            'manifest_path': manifest_path_public,
            'artifact_sha256': artifact_sha256,
            'manifest_hash': ((package_payload.get('manifest') or {}).get('manifest_hash')),
            'immutable_until': immutable_until,
            'classification': retention.get('classification'),
            'legal_hold': bool(retention.get('legal_hold', False)),
            'object_lock_enabled': object_lock_enabled,
            'retention_mode': str(normalized.get('retention_mode') or 'none'),
            'lock_path': lock_path_public if object_lock_enabled and bool(normalized.get('lock_sidecar', True)) else None,
            'delete_protection': bool(normalized.get('delete_protection', object_lock_enabled)),
        }
        crypto = self._sign_portfolio_payload_crypto_v2(
            report_type='openmiura_portfolio_evidence_escrow_receipt_v1',
            scope=scope,
            payload=receipt_payload,
            signer_key_id=str(normalized.get('escrow_key_id') or 'openmiura-escrow').strip() or 'openmiura-escrow',
            signing_policy=signing_policy,
        )
        receipt_payload.update({
            'signature': crypto.get('signature'),
            'signature_scheme': crypto.get('signature_scheme'),
            'signature_input': crypto.get('signature_input'),
            'public_key': crypto.get('public_key'),
            'crypto_v2': True,
            'signer_provider': crypto.get('signer_provider'),
            'key_origin': crypto.get('key_origin'),
        })
        receipt_bytes = self._canonical_json_bytes(receipt_payload)
        if self._path_exists(receipt_path):
            existing_receipt = json.loads(self._read_file_text(receipt_path, encoding='utf-8'))
            if str(existing_receipt.get('artifact_sha256') or '') != artifact_sha256:
                return {
                    'enabled': True,
                    'archived': False,
                    'provider': normalized.get('provider'),
                    'reason': 'immutable_receipt_conflict',
                    'receipt_path': receipt_path_public,
                }
        else:
            self._write_file_if_absent(receipt_path, receipt_bytes)
        return receipt_payload


    def _load_portfolio_evidence_artifact_from_escrow(self, *, escrow: dict[str, Any] | None = None) -> dict[str, Any] | None:
        receipt = dict(escrow or {})
        archive_path = str(receipt.get('archive_path') or '').strip()
        if not archive_path:
            return None
        archive_bytes: bytes | None = None
        if archive_path.startswith('s3://'):
            parsed = self._parse_s3_uri(archive_path)
            if parsed is None:
                return None
            bucket, key = parsed
            try:
                archive_bytes = self._read_s3_object_bytes(bucket=bucket, key=key, escrow_policy=receipt)
            except Exception:
                return None
        elif archive_path.startswith('azblob://'):
            parsed = self._parse_azblob_uri(archive_path)
            if parsed is None:
                return None
            container, blob_name = parsed
            try:
                service = self._azure_blob_service_client_for_policy(receipt)
                blob_client = service.get_blob_client(container=container, blob=blob_name)
                download = blob_client.download_blob()
                archive_bytes = download.readall() if hasattr(download, 'readall') else download.read()
            except Exception:
                return None
        elif archive_path.startswith('gs://'):
            parsed = self._parse_gs_uri(archive_path)
            if parsed is None:
                return None
            bucket_name, key = parsed
            try:
                client = self._gcs_client_for_policy(receipt)
                bucket = client.bucket(bucket_name)
                blob = bucket.blob(key)
                archive_bytes = blob.download_as_bytes()
            except Exception:
                return None
        else:
            if not self._path_exists(archive_path) or not self._path_is_file(archive_path):
                return None
            archive_bytes = self._read_file_bytes(archive_path)
        return {
            'artifact_type': 'openmiura_portfolio_evidence_artifact_v1',
            'package_id': receipt.get('package_id'),
            'portfolio_id': receipt.get('portfolio_id'),
            'filename': Path(archive_path).name,
            'media_type': 'application/zip',
            'format': 'zip',
            'sha256': hashlib.sha256(archive_bytes).hexdigest(),
            'size_bytes': len(archive_bytes),
            'encoding': 'base64',
            'content_b64': base64.b64encode(archive_bytes).decode('ascii'),
            'escrow': self._redact_large_blob(receipt),
        }


    def _build_portfolio_evidence_artifact_archive(
        self,
        *,
        package_payload: dict[str, Any],
        integrity: dict[str, Any],
        export_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_policy = self._normalize_portfolio_export_policy(dict(export_policy or {}))
        package_id = str(package_payload.get('package_id') or '').strip()
        portfolio_id = str(((package_payload.get('portfolio') or {}).get('portfolio_id')) or '').strip()
        generated_at = float(package_payload.get('generated_at') or time.time())
        manifest = dict(package_payload.get('manifest') or {})
        attestation_export = dict((package_payload.get('artifacts') or {}).get('attestation_export') or {})
        postmortem_export = dict((package_payload.get('artifacts') or {}).get('postmortem_export') or {})
        entries_payload = {
            'manifest.json': manifest,
            'package.json': package_payload,
            'integrity.json': integrity,
            'attestation_export.json': attestation_export,
            'postmortem_export.json': postmortem_export,
        }
        chain_of_custody = dict(package_payload.get('chain_of_custody') or {})
        if chain_of_custody:
            entries_payload['chain_of_custody.json'] = chain_of_custody
        custody_anchor = dict(package_payload.get('custody_anchor') or {})
        if custody_anchor:
            entries_payload['custody_anchor.json'] = custody_anchor
        notarization = dict(package_payload.get('notarization') or {})
        if notarization:
            entries_payload['notarization.json'] = notarization
        retention = dict(package_payload.get('retention') or {})
        if retention:
            entries_payload['retention.json'] = retention
        entry_bytes = {name: self._canonical_json_bytes(payload) for name, payload in entries_payload.items()}
        zip_buffer = io.BytesIO()
        dt = datetime.fromtimestamp(generated_at, tz=timezone.utc)
        zip_dt = (max(1980, dt.year), dt.month, dt.day, dt.hour, dt.minute, dt.second)
        with zipfile.ZipFile(zip_buffer, mode='w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            for name in sorted(entry_bytes):
                info = zipfile.ZipInfo(filename=name, date_time=zip_dt)
                info.compress_type = zipfile.ZIP_DEFLATED
                zf.writestr(info, entry_bytes[name])
        archive_bytes = zip_buffer.getvalue()
        archive_sha256 = hashlib.sha256(archive_bytes).hexdigest()
        filename_prefix = f'openmiura-portfolio-{portfolio_id or "portfolio"}-{package_id or "artifact"}'
        return {
            'artifact_type': 'openmiura_portfolio_evidence_artifact_v1',
            'package_id': package_id,
            'portfolio_id': portfolio_id or None,
            'filename': f'{filename_prefix}.zip',
            'media_type': 'application/zip',
            'format': str(normalized_policy.get('artifact_format') or 'zip'),
            'sha256': archive_sha256,
            'size_bytes': len(archive_bytes),
            'encoding': 'base64',
            'content_b64': base64.b64encode(archive_bytes).decode('ascii'),
            'entries': [
                {
                    'name': name,
                    'sha256': hashlib.sha256(payload).hexdigest(),
                    'size_bytes': len(payload),
                }
                for name, payload in sorted(entry_bytes.items())
            ],
        }


    def _decode_portfolio_evidence_artifact_input(
        self,
        *,
        artifact: dict[str, Any] | None = None,
        artifact_b64: str | None = None,
    ) -> dict[str, Any]:
        source = dict(artifact or {})
        encoded = artifact_b64 if artifact_b64 is not None else source.get('content_b64')
        if not encoded:
            return {'ok': False, 'error': 'portfolio_evidence_artifact_missing'}
        try:
            archive_bytes = base64.b64decode(str(encoded).encode('ascii'))
        except Exception:
            return {'ok': False, 'error': 'portfolio_evidence_artifact_decode_failed'}
        archive_sha256 = hashlib.sha256(archive_bytes).hexdigest()
        try:
            with zipfile.ZipFile(io.BytesIO(archive_bytes), mode='r') as zf:
                parsed_entries: dict[str, Any] = {}
                for name in zf.namelist():
                    try:
                        parsed_entries[name] = json.loads(zf.read(name).decode('utf-8'))
                    except Exception:
                        parsed_entries[name] = None
        except Exception:
            return {'ok': False, 'error': 'portfolio_evidence_artifact_invalid_archive'}
        return {
            'ok': True,
            'archive_bytes': archive_bytes,
            'archive_sha256': archive_sha256,
            'artifact': source,
            'entries': parsed_entries,
        }


    def _verify_portfolio_evidence_artifact_payload(
        self,
        *,
        artifact: dict[str, Any] | None = None,
        artifact_b64: str | None = None,
        now_ts: float | None = None,
    ) -> dict[str, Any]:
        decoded = self._decode_portfolio_evidence_artifact_input(artifact=artifact, artifact_b64=artifact_b64)
        if not decoded.get('ok'):
            return decoded
        artifact_meta = dict(decoded.get('artifact') or {})
        escrow_meta = dict(artifact_meta.get('escrow') or {})
        entries = dict(decoded.get('entries') or {})
        package_payload = dict(entries.get('package.json') or {})
        integrity = dict(entries.get('integrity.json') or {})
        manifest_entry = dict(entries.get('manifest.json') or {})
        attestation_export = dict(entries.get('attestation_export.json') or {})
        postmortem_export = dict(entries.get('postmortem_export.json') or {})
        chain_of_custody = dict(entries.get('chain_of_custody.json') or (package_payload.get('chain_of_custody') or {}))
        custody_anchor = dict(entries.get('custody_anchor.json') or (package_payload.get('custody_anchor') or {}))
        notarization = dict(entries.get('notarization.json') or (package_payload.get('notarization') or {}))
        if not package_payload or not integrity or not manifest_entry:
            return {'ok': False, 'error': 'portfolio_evidence_artifact_incomplete'}
        provided_archive_hash = str(artifact_meta.get('sha256') or '').strip()
        archive_hash_valid = not provided_archive_hash or provided_archive_hash == str(decoded.get('archive_sha256') or '')
        archive_size_valid = artifact_meta.get('size_bytes') is None or int(artifact_meta.get('size_bytes') or 0) == len(decoded.get('archive_bytes') or b'')
        manifest_from_package = dict(package_payload.get('manifest') or {})
        manifest_hash = str(manifest_from_package.get('manifest_hash') or manifest_entry.get('manifest_hash') or '').strip()
        manifest_payload = dict(manifest_entry)
        manifest_payload.pop('manifest_hash', None)
        package_manifest_payload = dict(manifest_from_package)
        package_manifest_payload.pop('manifest_hash', None)
        expected_manifest_hash = self._stable_digest(manifest_payload)
        manifest_hash_valid = bool(manifest_hash) and manifest_hash == expected_manifest_hash and package_manifest_payload == manifest_payload
        attestation_verify = self._verify_portfolio_export_integrity(
            report_type=str(((attestation_export.get('report') or {}).get('report_type')) or ''),
            scope=dict(attestation_export.get('scope') or {}),
            payload=dict(attestation_export.get('report') or {}),
            integrity=dict(attestation_export.get('integrity') or {}),
        )
        postmortem_verify = self._verify_portfolio_export_integrity(
            report_type=str(((postmortem_export.get('report') or {}).get('report_type')) or ''),
            scope=dict(postmortem_export.get('scope') or {}),
            payload=dict(postmortem_export.get('report') or {}),
            integrity=dict(postmortem_export.get('integrity') or {}),
        )
        package_verify = self._verify_portfolio_export_integrity(
            report_type=str(package_payload.get('report_type') or ''),
            scope=dict(package_payload.get('scope') or {}),
            payload=package_payload,
            integrity=integrity,
        )
        manifest_artifacts = {str(item.get('artifact_id') or ''): dict(item) for item in list(manifest_payload.get('artifacts') or [])}
        manifest_links_valid = (
            manifest_artifacts.get('attestation_export', {}).get('payload_hash') == ((attestation_export.get('integrity') or {}).get('payload_hash'))
            and manifest_artifacts.get('postmortem_export', {}).get('payload_hash') == ((postmortem_export.get('integrity') or {}).get('payload_hash'))
            and (
                not manifest_artifacts.get('chain_of_custody')
                or manifest_artifacts.get('chain_of_custody', {}).get('payload_hash') == self._stable_digest(chain_of_custody)
            )
        )
        raw_notarization_policy = (((attestation_export.get('report') or {}).get('train_policy') or {}).get('notarization_policy')) or {}
        notarization_verify = self._verify_portfolio_notarization_receipt(
            notarization=notarization,
            scope=dict(package_payload.get('scope') or {}),
            package_id=str(package_payload.get('package_id') or ''),
            manifest_hash=manifest_hash,
            notarization_policy=dict(raw_notarization_policy or {}),
            now_ts=now_ts,
        )
        escrow_verify = self._verify_portfolio_escrow_receipt(escrow=escrow_meta, now_ts=now_ts) if escrow_meta else {'required': False, 'valid': True, 'status': 'not_archived'}
        chain_verify = self._verify_portfolio_chain_of_custody_entries(list(chain_of_custody.get('entries') or [])) if chain_of_custody else {'valid': True, 'count': 0, 'chain_valid': True, 'signature_valid_count': 0, 'invalid_entry_ids': []}
        raw_anchor_policy = (((attestation_export.get('report') or {}).get('train_policy') or {}).get('custody_anchor_policy')) or {}
        anchor_policy = self._normalize_portfolio_custody_anchor_policy(dict(raw_anchor_policy or {}))
        chain_head_hash = (chain_verify.get('head_hash') if chain_of_custody else None)
        custody_anchor_verify = self._verify_portfolio_custody_anchor_receipt(
            receipt=custody_anchor,
            expected_chain_head_hash=chain_head_hash,
            expected_portfolio_id=str(((package_payload.get('portfolio') or {}).get('portfolio_id')) or '').strip() or None,
        ) if custody_anchor else {'valid': not bool(anchor_policy.get('require_anchor_on_export', False)), 'missing': True}
        checks = {
            'archive_hash_valid': archive_hash_valid,
            'archive_size_valid': archive_size_valid,
            'manifest_hash_valid': manifest_hash_valid,
            'manifest_links_valid': manifest_links_valid,
            'attestation_export_valid': bool(attestation_verify.get('valid')),
            'postmortem_export_valid': bool(postmortem_verify.get('valid')),
            'package_integrity_valid': bool(package_verify.get('valid')),
            'notarization_valid': bool(notarization_verify.get('valid')),
            'escrow_receipt_valid': bool(escrow_verify.get('valid', True)),
            'chain_of_custody_valid': bool(chain_verify.get('valid', True)),
            'custody_anchor_valid': bool(custody_anchor_verify.get('valid', True)),
        }
        failures = [name for name, value in checks.items() if not value]
        status = 'verified' if not failures else 'failed'
        return {
            'ok': True,
            'portfolio_id': str(((package_payload.get('portfolio') or {}).get('portfolio_id')) or '').strip() or None,
            'package_id': str(package_payload.get('package_id') or '').strip() or None,
            'artifact': {
                **{k: v for k, v in artifact_meta.items() if k != 'content_b64'},
                'sha256': decoded.get('archive_sha256'),
                'size_bytes': len(decoded.get('archive_bytes') or b''),
            },
            'package': package_payload,
            'integrity': integrity,
            'verification': {
                'status': status,
                'valid': status == 'verified',
                'restorable': status == 'verified' and bool((((postmortem_export.get('report') or {}).get('replay') or {}).get('summary'))),
                'checks': checks,
                'failures': failures,
                'manifest': {
                    'manifest_hash': manifest_hash,
                    'expected_manifest_hash': expected_manifest_hash,
                    'valid': manifest_hash_valid,
                    'artifact_links_valid': manifest_links_valid,
                },
                'attestation_export': attestation_verify,
                'postmortem_export': postmortem_verify,
                'package_integrity': package_verify,
                'notarization': notarization_verify,
                'escrow': escrow_verify,
                'chain_of_custody': chain_verify,
                'custody_anchor': custody_anchor_verify,
            },
            'restored_entries': {
                'attestation_export': attestation_export,
                'postmortem_export': postmortem_export,
                'chain_of_custody': chain_of_custody,
                'custody_anchor': custody_anchor,
                'notarization': notarization,
            },
        }


    def _find_portfolio_evidence_package(
        self,
        release: dict[str, Any] | None,
        *,
        package_id: str | None = None,
        include_content: bool = False,
    ) -> dict[str, Any] | None:
        packages = self._list_portfolio_evidence_packages(release, include_content=True)
        if not packages:
            return None
        selected: dict[str, Any] | None = None
        if package_id is None:
            selected = dict(packages[0])
        else:
            needle = str(package_id or '').strip()
            for item in packages:
                if str(item.get('package_id') or '').strip() == needle:
                    selected = dict(item)
                    break
        if selected is None:
            return None
        artifact = dict(selected.get('artifact') or {})
        if include_content and not artifact.get('content_b64'):
            loaded = self._load_portfolio_evidence_artifact_from_escrow(escrow=dict(selected.get('escrow') or {}))
            if loaded is not None:
                if selected.get('escrow'):
                    loaded['escrow'] = self._redact_large_blob(dict(selected.get('escrow') or {}))
                selected['artifact'] = loaded
        elif not include_content and artifact:
            artifact.pop('content_b64', None)
            selected['artifact'] = artifact
        return selected


    def _list_portfolio_evidence_packages(self, release: dict[str, Any] | None, *, include_content: bool = False) -> list[dict[str, Any]]:
        metadata = dict((release or {}).get('metadata') or {})
        portfolio = dict(metadata.get('portfolio') or {})
        items = [dict(item) for item in list(portfolio.get('evidence_packages') or [])]
        sanitized: list[dict[str, Any]] = []
        for item in items:
            record = dict(item)
            artifact = dict(record.get('artifact') or {})
            if include_content and artifact and not artifact.get('content_b64'):
                loaded = self._load_portfolio_evidence_artifact_from_escrow(escrow=dict(record.get('escrow') or {}))
                if loaded is not None:
                    if record.get('escrow'):
                        loaded['escrow'] = self._redact_large_blob(dict(record.get('escrow') or {}))
                    record['artifact'] = loaded
            elif artifact and not include_content:
                artifact.pop('content_b64', None)
                record['artifact'] = artifact
            sanitized.append(record)
        sanitized.sort(key=lambda item: float(item.get('created_at') or 0.0), reverse=True)
        return sanitized


    def _store_portfolio_evidence_package(
        self,
        gw,
        *,
        release: dict[str, Any],
        package_record: dict[str, Any],
    ) -> dict[str, Any]:
        metadata = dict(release.get('metadata') or {})
        portfolio = dict(metadata.get('portfolio') or {})
        items = [dict(item) for item in list(portfolio.get('evidence_packages') or [])]
        items = [item for item in items if str(item.get('package_id') or '') != str(package_record.get('package_id') or '')]
        items.append(dict(package_record))
        items.sort(key=lambda item: float(item.get('created_at') or 0.0), reverse=True)
        max_packages = int((((portfolio.get('train_policy') or {}).get('retention_policy') or {}).get('max_packages')) or ((package_record.get('retention') or {}).get('max_packages') or 25))
        portfolio['evidence_packages'] = items[: max(1, max_packages * 3)]
        metadata['portfolio'] = portfolio
        return gw.audit.update_release_bundle(
            str(release.get('release_id') or ''),
            status=release.get('status'),
            notes=release.get('notes'),
            metadata=metadata,
            tenant_id=release.get('tenant_id'),
            workspace_id=release.get('workspace_id'),
            environment=release.get('environment'),
        ) or release


    def _prune_portfolio_evidence_packages(
        self,
        gw,
        *,
        release: dict[str, Any],
        actor: str,
        now_ts: float | None = None,
    ) -> dict[str, Any]:
        metadata = dict(release.get('metadata') or {})
        portfolio = dict(metadata.get('portfolio') or {})
        base_train_policy = self._normalize_portfolio_train_policy(dict(portfolio.get('train_policy') or {}))
        train_policy = self._resolve_portfolio_train_policy_for_environment(base_train_policy, environment=release.get('environment'))
        retention_policy = dict(train_policy.get('retention_policy') or {})
        packages = self._list_portfolio_evidence_packages(release, include_content=True)
        resolved_now = float(now_ts) if now_ts is not None else time.time()
        keep: list[dict[str, Any]] = []
        removed: list[dict[str, Any]] = []
        for item in packages:
            retention = self._portfolio_retention_snapshot(
                created_at=float(item.get('created_at') or resolved_now),
                retention_policy=dict(item.get('retention') or retention_policy),
                now_ts=resolved_now,
            )
            enriched = dict(item)
            enriched['retention'] = retention
            if bool(retention.get('expired')) and bool(retention.get('purge_expired', True)) and not bool(retention.get('legal_hold', False)):
                removed.append(enriched)
            else:
                keep.append(enriched)
        max_packages = max(1, int(retention_policy.get('max_packages') or 25))
        if len(keep) > max_packages:
            overflow = keep[max_packages:]
            keep = keep[:max_packages]
            removed.extend(overflow)
        if len(removed) != 0:
            portfolio['evidence_packages'] = keep
            metadata['portfolio'] = portfolio
            release = gw.audit.update_release_bundle(
                str(release.get('release_id') or ''),
                status=release.get('status'),
                notes=release.get('notes'),
                metadata=metadata,
                tenant_id=release.get('tenant_id'),
                workspace_id=release.get('workspace_id'),
                environment=release.get('environment'),
            ) or release
            gw.audit.log_event(
                direction='system',
                channel='openclaw',
                user_id=str(actor or 'system'),
                session_id='',
                payload={
                    'event': 'openclaw_portfolio_evidence_pruned',
                    'portfolio_id': str(release.get('release_id') or ''),
                    'removed_package_ids': [item.get('package_id') for item in removed],
                    'remaining_count': len(keep),
                },
                tenant_id=release.get('tenant_id'),
                workspace_id=release.get('workspace_id'),
                environment=release.get('environment'),
            )
        return {
            'release': release,
            'removed': removed,
            'remaining': keep,
            'summary': {
                'removed_count': len(removed),
                'remaining_count': len(keep),
                'expired_removed_count': sum(1 for item in removed if bool(((item.get('retention') or {}).get('expired')))),
            },
        }


    def _collect_portfolio_audit_evidence(
        self,
        gw,
        *,
        release: dict[str, Any],
        bundle_ids: list[str],
        limit: int,
    ) -> list[dict[str, Any]]:
        scope = self._scope(tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=release.get('environment'))
        events = gw.audit.list_events_filtered(
            limit=max(limit * 5, limit),
            since_ts=max(0.0, float(release.get('created_at') or 0.0) - 60.0),
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        )
        portfolio_id = str(release.get('release_id') or '')
        bundle_id_set = {str(item).strip() for item in list(bundle_ids or []) if str(item).strip()}
        filtered: list[dict[str, Any]] = []
        for item in list(events or []):
            payload = dict(item.get('payload') or {})
            payload_portfolio_id = str(payload.get('portfolio_id') or '')
            payload_bundle_id = str(payload.get('bundle_id') or '')
            if payload_portfolio_id == portfolio_id or (payload_bundle_id and payload_bundle_id in bundle_id_set):
                filtered.append({
                    'id': item.get('id'),
                    'ts': item.get('ts'),
                    'channel': item.get('channel'),
                    'direction': item.get('direction'),
                    'event': str(payload.get('event') or payload.get('action') or '').strip(),
                    'user_id': item.get('user_id'),
                    'payload': payload,
                })
        filtered.sort(key=lambda entry: (float(entry.get('ts') or 0.0), int(entry.get('id') or 0)))
        return filtered[-max(1, int(limit)) :]


    def _portfolio_postmortem_summary(
        self,
        *,
        detail: dict[str, Any],
        execution_compare: dict[str, Any],
        drift: dict[str, Any],
    ) -> dict[str, Any]:
        compare_summary = dict(execution_compare.get('summary') or {})
        detail_summary = dict(detail.get('summary') or {})
        drift_summary = dict((drift or {}).get('summary') or {})
        failure_modes: dict[str, int] = {}
        for item in list(execution_compare.get('items') or []):
            status = str(item.get('status') or '').strip()
            if status in {'error', 'drift_blocked'}:
                failure_modes[status] = failure_modes.get(status, 0) + 1
        return {
            'rollout_status': detail_summary.get('rollout_status'),
            'approval_satisfied': bool(detail_summary.get('approval_satisfied')),
            'calendar_completion_ratio': ((detail.get('analytics') or {}).get('calendar_completion_ratio')),
            'completed_count': compare_summary.get('completed_count'),
            'error_count': compare_summary.get('error_count'),
            'drift_count': drift_summary.get('count'),
            'blocking_drift_count': drift_summary.get('blocking_count'),
            'failure_modes': failure_modes,
        }


    def _log_portfolio_evidence_export(
        self,
        gw,
        *,
        release: dict[str, Any],
        actor: str,
        report_type: str,
        integrity: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        gw.audit.log_event(
            direction='system',
            channel='openclaw',
            user_id=str(actor or 'system'),
            session_id='',
            payload={
                'event': 'openclaw_portfolio_evidence_exported',
                'portfolio_id': str(release.get('release_id') or ''),
                'report_type': str(report_type or '').strip(),
                'payload_hash': integrity.get('payload_hash'),
                'signature': integrity.get('signature'),
                'signer_key_id': integrity.get('signer_key_id'),
                **dict(metadata or {}),
            },
            tenant_id=release.get('tenant_id'),
            workspace_id=release.get('workspace_id'),
            environment=release.get('environment'),
        )


    def _portfolio_policy_deviation_exception_summary(self, release: dict[str, Any]) -> dict[str, Any]:
        items = self._list_portfolio_policy_deviation_exceptions(release)
        status_counts: dict[str, int] = {}
        active_count = 0
        for item in items:
            status = str(item.get('status') or 'unknown')
            status_counts[status] = status_counts.get(status, 0) + 1
            if status in {'approved', 'pending_approval'}:
                active_count += 1
        return {
            'count': len(items),
            'active_count': active_count,
            'status_counts': status_counts,
            'latest_exception_id': items[0].get('exception_id') if items else None,
        }


    def _portfolio_evidence_package_summary(self, release: dict[str, Any]) -> dict[str, Any]:
        packages = self._list_portfolio_evidence_packages(release)
        active_count = 0
        expired_count = 0
        notarized_count = 0
        legal_hold_count = 0
        escrowed_count = 0
        immutable_archive_count = 0
        crypto_signed_count = 0
        object_lock_archive_count = 0
        external_signing_count = 0
        custody_anchor_count = 0
        custody_anchor_valid_count = 0
        operational_tier_counts: dict[str, int] = {}
        classification_counts: dict[str, int] = {}
        for item in packages:
            retention = self._portfolio_retention_snapshot(
                created_at=float(item.get('created_at') or 0.0),
                retention_policy=dict(item.get('retention') or {}),
            )
            operational_tier = str(item.get('operational_tier') or (retention.get('operational_tier') if isinstance(retention, dict) else '') or '').strip()
            if operational_tier:
                operational_tier_counts[operational_tier] = operational_tier_counts.get(operational_tier, 0) + 1
            classification = str(item.get('evidence_classification') or retention.get('classification') or '').strip()
            if classification:
                classification_counts[classification] = classification_counts.get(classification, 0) + 1
            if bool(((item.get('notarization') or {}).get('notarized'))):
                notarized_count += 1
            if bool((item.get('escrow') or {}).get('archived')):
                escrowed_count += 1
                if (item.get('escrow') or {}).get('immutable_until') is not None:
                    immutable_archive_count += 1
                if bool((item.get('escrow') or {}).get('object_lock_enabled')):
                    object_lock_archive_count += 1
            if bool(item.get('crypto_v2')) or str(item.get('signature_scheme') or '').strip().lower() == 'ed25519':
                crypto_signed_count += 1
                if str(item.get('signer_provider') or '').strip() in {'kms-ed25519-simulated', 'hsm-ed25519-simulated', 'kms-ed25519-file', 'hsm-ed25519-file', 'kms-ed25519-command', 'hsm-ed25519-command', 'aws-kms-ecdsa-p256', 'gcp-kms-ecdsa-p256', 'azure-kv-ecdsa-p256', 'pkcs11-ed25519', 'pkcs11-ecdsa-p256'}:
                    external_signing_count += 1
            custody_anchor = dict(item.get('custody_anchor') or {})
            if custody_anchor:
                custody_anchor_count += 1
                if bool(self._verify_portfolio_custody_anchor_receipt(receipt=custody_anchor, expected_portfolio_id=str(release.get('release_id') or '')).get('valid')):
                    custody_anchor_valid_count += 1
            if bool(retention.get('legal_hold')):
                legal_hold_count += 1
            elif bool(retention.get('expired')):
                expired_count += 1
            else:
                active_count += 1
        return {
            'count': len(packages),
            'active_count': active_count,
            'expired_count': expired_count,
            'legal_hold_count': legal_hold_count,
            'notarized_count': notarized_count,
            'escrowed_count': escrowed_count,
            'immutable_archive_count': immutable_archive_count,
            'object_lock_archive_count': object_lock_archive_count,
            'crypto_signed_count': crypto_signed_count,
            'external_signing_count': external_signing_count,
            'custody_anchor_count': custody_anchor_count,
            'custody_anchor_valid_count': custody_anchor_valid_count,
            'operational_tier_counts': operational_tier_counts,
            'classification_counts': classification_counts,
            'latest_package_id': packages[0].get('package_id') if packages else None,
        }


    def _build_portfolio_evidence_package_export_payload(
        self,
        gw,
        *,
        detail: dict[str, Any],
        actor: str,
        attestation_id: str | None = None,
        timeline_limit: int | None = None,
    ) -> dict[str, Any]:
        release = dict(detail.get('release') or {})
        train_policy = self._resolve_portfolio_train_policy_for_environment(dict(((detail.get('portfolio') or {}).get('train_policy') or {})), environment=release.get('environment'))
        export_policy = dict(train_policy.get('export_policy') or {})
        notarization_policy = dict(train_policy.get('notarization_policy') or {})
        retention_policy = dict(train_policy.get('retention_policy') or {})
        retention_policy['operational_tier'] = train_policy.get('operational_tier')
        retention_policy['classification'] = str(train_policy.get('evidence_classification') or retention_policy.get('classification') or 'internal-sensitive')
        escrow_policy = dict(train_policy.get('escrow_policy') or {})
        signing_policy = dict(train_policy.get('signing_policy') or {})
        chain_policy = dict(train_policy.get('chain_of_custody_policy') or {})
        custody_anchor_policy = dict(train_policy.get('custody_anchor_policy') or {})
        attestation_export = self._build_portfolio_attestation_export_payload(detail=detail, actor=actor, attestation_id=attestation_id)
        if not attestation_export.get('ok'):
            return attestation_export
        postmortem_export = self._build_portfolio_postmortem_export_payload(gw, detail=detail, actor=actor, attestation_id=attestation_id, timeline_limit=timeline_limit)
        if not postmortem_export.get('ok'):
            return postmortem_export
        generated_at = time.time()
        package_id = str(uuid.uuid4())
        retention = self._portfolio_retention_snapshot(created_at=generated_at, retention_policy=retention_policy, now_ts=generated_at)
        _, provisional_entries, chain_snapshot = self._prepare_portfolio_chain_of_custody_snapshot(
            release=release,
            actor=actor,
            chain_policy=chain_policy,
            signing_policy=signing_policy,
            events=[
                {
                    'event_type': 'portfolio_evidence_package_exported',
                    'package_id': package_id,
                    'metadata': {
                        'attestation_id': attestation_export.get('attestation_id'),
                        'report_type': 'openmiura_portfolio_evidence_package_v1',
                    },
                },
            ],
            timestamp=generated_at,
        )
        manifest, manifest_hash = self._portfolio_evidence_package_manifest(
            package_id=package_id,
            detail=detail,
            attestation_export=attestation_export,
            postmortem_export=postmortem_export,
            chain_of_custody=chain_snapshot if bool(chain_policy.get('include_in_artifact', True)) else None,
            generated_at=generated_at,
            actor=actor,
            retention=retention,
        )
        custody_anchor = self._anchor_portfolio_chain_of_custody_external(
            release=release,
            chain_of_custody=chain_snapshot if bool(chain_policy.get('include_in_artifact', True)) else None,
            package_id=package_id,
            manifest_hash=manifest_hash,
            artifact_sha256=None,
            actor=actor,
            custody_anchor_policy=custody_anchor_policy,
            signing_policy=signing_policy,
            generated_at=generated_at,
        )
        if bool(custody_anchor_policy.get('enabled')) and bool(custody_anchor_policy.get('require_anchor_on_export', False)) and not bool(custody_anchor.get('anchored')):
            return {
                'ok': False,
                'error': 'portfolio_custody_anchor_failed',
                'portfolio_id': detail.get('portfolio_id'),
                'package_id': package_id,
                'custody_anchor': custody_anchor,
            }
        notarization = self._portfolio_notarization_receipt(
            package_id=package_id,
            manifest_hash=manifest_hash,
            actor=actor,
            scope=dict(detail.get('scope') or {}),
            notarization_policy=notarization_policy,
            signing_policy=signing_policy,
            generated_at=generated_at,
        )
        package_payload = {
            'report_type': 'openmiura_portfolio_evidence_package_v1',
            'generated_at': generated_at,
            'generated_by': str(actor or 'system'),
            'package_id': package_id,
            'portfolio': {
                'portfolio_id': detail.get('portfolio_id'),
                'name': release.get('name'),
                'version': release.get('version'),
                'status': release.get('status'),
            },
            'scope': dict(detail.get('scope') or {}),
            'operational_tier': train_policy.get('operational_tier'),
            'evidence_classification': train_policy.get('evidence_classification'),
            'manifest': {**manifest, 'manifest_hash': manifest_hash},
            'artifacts': {
                'attestation_export': attestation_export,
                'postmortem_export': postmortem_export,
            },
            'attestation_export': attestation_export,
            'postmortem_export': postmortem_export,
            'chain_of_custody': chain_snapshot if bool(chain_policy.get('include_in_artifact', True)) else None,
            'custody_anchor': dict(custody_anchor.get('receipt') or {}) if bool(custody_anchor.get('anchored')) else None,
            'notarization': notarization,
            'retention': retention,
            'policy_conformance': dict(detail.get('policy_conformance') or {}),
            'policy_baseline_drift': dict(detail.get('policy_baseline_drift') or {}),
            'deviation_exceptions': dict(detail.get('deviation_exceptions') or {}),
        }
        integrity = self._portfolio_evidence_integrity(
            report_type=package_payload['report_type'],
            scope=dict(detail.get('scope') or {}),
            payload=package_payload,
            actor=actor,
            export_policy=export_policy,
            signing_policy=signing_policy,
        )
        artifact = self._build_portfolio_evidence_artifact_archive(
            package_payload=package_payload,
            integrity=integrity,
            export_policy=export_policy,
        )
        escrow = self._archive_portfolio_evidence_artifact_external(
            artifact=artifact,
            package_payload=package_payload,
            integrity=integrity,
            retention=retention,
            actor=actor,
            escrow_policy=escrow_policy,
            signing_policy=signing_policy,
            generated_at=generated_at,
        )
        if bool(escrow_policy.get('enabled')) and bool(escrow_policy.get('require_archive_on_export', True)) and not bool(escrow.get('archived')):
            if not bool(escrow_policy.get('allow_inline_fallback', True)):
                return {
                    'ok': False,
                    'error': 'portfolio_evidence_escrow_failed',
                    'portfolio_id': detail.get('portfolio_id'),
                    'package_id': package_id,
                    'escrow': escrow,
                }
        if bool(chain_policy.get('enabled', True)) and bool(notarization.get('notarized')):
            existing_chain_entries = self._list_portfolio_chain_of_custody_entries(release) + [dict(item) for item in provisional_entries]
            provisional_entries.append(
                self._build_portfolio_chain_of_custody_entry(
                    release=release,
                    actor=actor,
                    event_type='portfolio_evidence_notarized',
                    sequence=(int(existing_chain_entries[-1].get('sequence') or 0) if existing_chain_entries else 0) + 1,
                    previous_entry_hash=str(existing_chain_entries[-1].get('entry_hash') or '') if existing_chain_entries else '',
                    chain_policy=chain_policy,
                    signing_policy=signing_policy,
                    package_id=package_id,
                    metadata={'receipt_id': notarization.get('receipt_id'), 'provider': notarization.get('provider'), 'manifest_hash': manifest_hash},
                    timestamp=generated_at,
                )
            )
        if bool(chain_policy.get('enabled', True)) and bool(escrow.get('archived')):
            existing_chain_entries = self._list_portfolio_chain_of_custody_entries(release) + [dict(item) for item in provisional_entries]
            provisional_entries.append(
                self._build_portfolio_chain_of_custody_entry(
                    release=release,
                    actor=actor,
                    event_type='portfolio_evidence_escrowed',
                    sequence=(int(existing_chain_entries[-1].get('sequence') or 0) if existing_chain_entries else 0) + 1,
                    previous_entry_hash=str(existing_chain_entries[-1].get('entry_hash') or '') if existing_chain_entries else '',
                    chain_policy=chain_policy,
                    signing_policy=signing_policy,
                    package_id=package_id,
                    artifact_sha256=artifact.get('sha256'),
                    metadata={'receipt_id': escrow.get('receipt_id'), 'provider': escrow.get('provider'), 'archive_path': escrow.get('archive_path'), 'object_lock_enabled': escrow.get('object_lock_enabled')},
                    timestamp=generated_at,
                )
            )
        artifact_record = dict(artifact)
        if not bool(export_policy.get('embed_artifact_content', True)):
            artifact_record.pop('content_b64', None)
        if escrow.get('archived'):
            artifact_record['escrow'] = self._redact_large_blob(dict(escrow or {}))
        package_record = {
            'package_id': package_id,
            'created_at': generated_at,
            'created_by': str(actor or 'system'),
            'report_type': package_payload['report_type'],
            'attestation_id': attestation_export.get('attestation_id'),
            'manifest_hash': manifest_hash,
            'payload_hash': integrity.get('payload_hash'),
            'signature': integrity.get('signature'),
            'signature_scheme': integrity.get('signature_scheme'),
            'crypto_v2': bool(integrity.get('crypto_v2')),
            'signer_key_id': integrity.get('signer_key_id'),
            'signer_provider': integrity.get('signer_provider'),
            'key_origin': integrity.get('key_origin'),
            'operational_tier': train_policy.get('operational_tier'),
            'evidence_classification': train_policy.get('evidence_classification'),
            'notarization': notarization,
            'retention': retention,
            'artifact': artifact_record,
            'escrow': self._redact_large_blob(dict(escrow or {})) if escrow else {},
            'chain_of_custody': chain_snapshot if bool(chain_policy.get('include_in_artifact', True)) else None,
            'custody_anchor': self._redact_large_blob(dict(custody_anchor.get('receipt') or {})) if bool(custody_anchor.get('anchored')) else {},
            'artifacts': [
                {'artifact_id': item.get('artifact_id'), 'report_type': item.get('report_type'), 'payload_hash': item.get('payload_hash')}
                for item in list(manifest.get('artifacts') or [])
            ],
        }
        updated_release = self._store_portfolio_evidence_package(gw, release=release, package_record=package_record)
        if bool(custody_anchor.get('anchored')):
            updated_release = self._store_portfolio_custody_anchor_receipt(
                gw,
                release=updated_release,
                receipt=dict(custody_anchor.get('receipt') or {}),
                custody_anchor_policy=custody_anchor_policy,
            )
        if provisional_entries:
            updated_release = self._store_portfolio_chain_of_custody_entries(gw, release=updated_release, entries=provisional_entries, chain_policy=chain_policy)
        if bool(retention.get('prune_on_export', True)):
            prune_result = self._prune_portfolio_evidence_packages(gw, release=updated_release, actor=actor, now_ts=generated_at)
            updated_release = dict(prune_result.get('release') or updated_release)
            package_payload['retention']['prune_result'] = dict(prune_result.get('summary') or {})
        self._log_portfolio_evidence_export(
            gw,
            release=updated_release,
            actor=actor,
            report_type=package_payload['report_type'],
            integrity=integrity,
            metadata={
                'package_id': package_id,
                'attestation_id': attestation_export.get('attestation_id'),
                'manifest_hash': manifest_hash,
                'notarized': bool(notarization.get('notarized')),
                'classification': retention.get('classification'),
                'operational_tier': train_policy.get('operational_tier'),
                'escrow_archived': bool(escrow.get('archived')),
                'escrow_provider': escrow.get('provider'),
                'signer_provider': integrity.get('signer_provider'),
                'custody_anchored': bool(custody_anchor.get('anchored')),
                'custody_anchor_provider': custody_anchor.get('provider'),
            },
        )
        return {
            'ok': True,
            'portfolio_id': detail.get('portfolio_id'),
            'attestation_id': attestation_export.get('attestation_id'),
            'package_id': package_id,
            'package': package_payload,
            'integrity': integrity,
            'artifact': artifact,
            'escrow': self._redact_large_blob(dict(escrow or {})) if escrow else {},
            'custody_anchor': self._redact_large_blob(dict(custody_anchor.get('receipt') or {})) if bool(custody_anchor.get('anchored')) else custody_anchor,
            'scope': detail.get('scope'),
        }


    def _restore_portfolio_evidence_artifact_payload(
        self,
        gw,
        *,
        actor: str,
        artifact: dict[str, Any] | None = None,
        artifact_b64: str | None = None,
        persist_restore_session: bool = False,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        verification = self._verify_portfolio_evidence_artifact_payload(artifact=artifact, artifact_b64=artifact_b64)
        if not verification.get('ok'):
            return verification
        verify_summary = dict(verification.get('verification') or {})
        if not bool(verify_summary.get('restorable')):
            return {
                'ok': False,
                'error': 'portfolio_evidence_artifact_not_restorable',
                'portfolio_id': verification.get('portfolio_id'),
                'package_id': verification.get('package_id'),
                'verification': verify_summary,
            }
        postmortem_export = dict((verification.get('restored_entries') or {}).get('postmortem_export') or {})
        postmortem_report = dict(postmortem_export.get('report') or {})
        replay = dict(postmortem_report.get('replay') or {})
        restore_session = {
            'restore_id': str(uuid.uuid4()),
            'restored_at': time.time(),
            'restored_by': str(actor or 'system').strip() or 'system',
            'portfolio_id': verification.get('portfolio_id'),
            'package_id': verification.get('package_id'),
            'artifact_sha256': ((verification.get('artifact') or {}).get('sha256')),
            'verification_status': verify_summary.get('status'),
            'replay_count': ((replay.get('summary') or {}).get('count')),
            'drift_status': ((postmortem_report.get('drift') or {}).get('overall_status')),
        }
        target_scope = self._scope(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        resolved_scope = {
            'tenant_id': target_scope.get('tenant_id') if target_scope.get('tenant_id') is not None else ((verification.get('package') or {}).get('scope') or {}).get('tenant_id'),
            'workspace_id': target_scope.get('workspace_id') if target_scope.get('workspace_id') is not None else ((verification.get('package') or {}).get('scope') or {}).get('workspace_id'),
            'environment': target_scope.get('environment') if target_scope.get('environment') is not None else ((verification.get('package') or {}).get('scope') or {}).get('environment'),
        }
        release = None
        if verification.get('portfolio_id'):
            release = gw.audit.get_release_bundle(
                str(verification.get('portfolio_id') or ''),
                tenant_id=resolved_scope.get('tenant_id'),
                workspace_id=resolved_scope.get('workspace_id'),
                environment=resolved_scope.get('environment'),
            )
        if release is not None:
            if persist_restore_session:
                resolved_train_policy = self._resolve_portfolio_train_policy_for_environment(dict((((release.get('metadata') or {}).get('portfolio') or {}).get('train_policy') or {})), environment=release.get('environment'))
                export_policy = self._normalize_portfolio_export_policy(dict((resolved_train_policy.get('export_policy') or {})))
                self._store_portfolio_restore_session(
                    gw,
                    release=release,
                    session_record=restore_session,
                    restore_history_limit=int(export_policy.get('restore_history_limit') or 20),
                )
            gw.audit.log_event(
                direction='system',
                channel='openclaw',
                user_id=str(actor or 'system'),
                session_id='',
                payload={
                    'event': 'openclaw_portfolio_evidence_restored',
                    'portfolio_id': str(verification.get('portfolio_id') or ''),
                    'package_id': str(verification.get('package_id') or ''),
                    'restore_id': restore_session.get('restore_id'),
                    'artifact_sha256': restore_session.get('artifact_sha256'),
                },
                tenant_id=resolved_scope.get('tenant_id'),
                workspace_id=resolved_scope.get('workspace_id'),
                environment=resolved_scope.get('environment'),
            )
            train_policy = self._resolve_portfolio_train_policy_for_environment(dict((((release.get('metadata') or {}).get('portfolio') or {}).get('train_policy') or {})), environment=release.get('environment'))
            chain_policy = dict(train_policy.get('chain_of_custody_policy') or {})
            signing_policy = dict(train_policy.get('signing_policy') or {})
            _, new_entries, _ = self._prepare_portfolio_chain_of_custody_snapshot(
                release=release,
                actor=actor,
                chain_policy=chain_policy,
                signing_policy=signing_policy,
                events=[{
                    'event_type': 'portfolio_evidence_restored',
                    'package_id': verification.get('package_id'),
                    'artifact_sha256': restore_session.get('artifact_sha256'),
                    'metadata': {'restore_id': restore_session.get('restore_id'), 'verification_status': verify_summary.get('status')},
                }],
            )
            if new_entries:
                self._store_portfolio_chain_of_custody_entries(gw, release=release, entries=new_entries, chain_policy=chain_policy)
        return {
            'ok': True,
            'portfolio_id': verification.get('portfolio_id'),
            'package_id': verification.get('package_id'),
            'artifact': verification.get('artifact'),
            'verification': verify_summary,
            'restore': {
                'restore_session': restore_session,
                'package': verification.get('package'),
                'integrity': verification.get('integrity'),
                'attestation_export': ((verification.get('restored_entries') or {}).get('attestation_export')),
                'postmortem_export': postmortem_export,
                'replay': replay,
                'execution_compare': postmortem_report.get('execution_compare'),
                'drift': postmortem_report.get('drift'),
                'summary': {
                    'replay_count': ((replay.get('summary') or {}).get('count')),
                    'completed_count': (((postmortem_report.get('execution_compare') or {}).get('summary') or {}).get('completed_count')),
                    'error_count': (((postmortem_report.get('execution_compare') or {}).get('summary') or {}).get('error_count')),
                    'blocking_drift_count': (((postmortem_report.get('drift') or {}).get('summary') or {}).get('blocking_count')),
                    'persisted': bool(persist_restore_session),
                },
            },
        }
