"""evidence_builders._archive_mixin"""
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






OpenClawEvidenceBuildersMixin: type | None = None


class _OpenClawEvidenceBuildersMixinArchiveMixin:
    """Sub-mixin: archive."""

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

