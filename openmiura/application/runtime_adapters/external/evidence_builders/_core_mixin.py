"""evidence_builders._core_mixin"""
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


class _OpenClawEvidenceBuildersMixinCoreMixin:
    """Sub-mixin: core."""

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

