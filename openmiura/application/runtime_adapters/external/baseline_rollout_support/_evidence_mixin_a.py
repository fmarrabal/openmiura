"""baseline_rollout_support._evidence_mixin

Sub-mixin extracted from
``openmiura.application.runtime_adapters.external.baseline_rollout_support``
so that no individual file in the package exceeds 1,500 lines. The
public class ``OpenClawBaselineRolloutSupportMixin`` continues to
inherit from this sub-mixin.

The module-level ``OpenClawBaselineRolloutSupportMixin = None`` sentinel
is rebound by ``baseline_rollout_support/__init__.py`` so that the few
``@staticmethod`` call sites that reference the class by name resolve
correctly at call time.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


OpenClawBaselineRolloutSupportMixin: type | None = None  # late-bound by __init__.py


class _OpenClawBaselineRolloutSupportEvidenceMixinA:
    """Sub-mixin: evidence methods on OpenClawBaselineRolloutSupportMixin."""

    def _build_baseline_promotion_simulation_review_audit_export_payload(
        self,
        *,
        simulation: dict[str, Any],
        actor: str,
        timeline_limit: int | None = None,
    ) -> dict[str, Any]:
        payload = dict(simulation or {})
        simulation_id = str(payload.get('simulation_id') or '').strip()
        scope = dict(payload.get('scope') or {})
        export_policy = self._baseline_promotion_simulation_export_policy(simulation=payload)
        signing_policy = self._baseline_promotion_simulation_effective_signing_policy(simulation=payload)
        review_state = dict(payload.get('review_state') or {})
        review_items = [dict(item) for item in list(review_state.get('items') or [])]
        ordered_reviews = sorted(
            review_items,
            key=lambda item: (
                float(item.get('decided_at') or item.get('created_at') or 0.0),
                str(item.get('layer_id') or ''),
                str(item.get('review_id') or ''),
            ),
        )
        timeline = self._baseline_promotion_simulation_timeline_view(payload, limit=max(25, int(timeline_limit or export_policy.get('timeline_limit') or 250)))
        effective_policy = dict(payload.get('simulation_policy') or {})
        approval_policy = dict(effective_policy.get('approval_policy') or {})
        reviewer_ids = sorted({str(item.get('actor') or '').strip() for item in ordered_reviews if str(item.get('actor') or '').strip()})
        self_review_detected = str(payload.get('simulated_by') or '').strip() in reviewer_ids if reviewer_ids else False
        report_id = str(self._stable_digest({
            'report_type': 'openmiura_baseline_promotion_simulation_review_audit_v1',
            'simulation_id': simulation_id,
            'generated_by': str(actor or 'system'),
            'review_hash': self._stable_digest(ordered_reviews),
            'policy_hash': self._stable_digest(effective_policy),
        })[:24])
        report = {
            'report_id': report_id,
            'report_type': 'openmiura_baseline_promotion_simulation_review_audit_v1',
            'generated_at': time.time(),
            'generated_by': str(actor or 'system'),
            'simulation': {
                'simulation_id': simulation_id,
                'simulation_status': str(payload.get('simulation_status') or ''),
                'simulated_at': payload.get('simulated_at'),
                'simulated_by': payload.get('simulated_by'),
                'reviewed_at': payload.get('reviewed_at'),
                'catalog_id': str(payload.get('catalog_id') or ''),
                'candidate_catalog_version': str(payload.get('candidate_catalog_version') or ''),
            },
            'scope': scope,
            'effective_policy': {
                'simulation_policy': effective_policy,
                'approval_policy': approval_policy,
                'policy_fingerprint': self._stable_digest(effective_policy),
            },
            'review_sequence': {
                'mode': str(review_state.get('mode') or approval_policy.get('mode') or ''),
                'required': bool(review_state.get('required')),
                'overall_status': str(review_state.get('overall_status') or ''),
                'approved': bool(review_state.get('approved')),
                'rejected': bool(review_state.get('rejected')),
                'review_count': int(review_state.get('review_count') or 0),
                'approved_count': int(review_state.get('approved_count') or 0),
                'rejected_count': int(review_state.get('rejected_count') or 0),
                'pending_count': int(review_state.get('pending_count') or 0),
                'pending_layers': [str(item) for item in list(review_state.get('pending_layers') or []) if str(item)],
                'next_layer': dict(review_state.get('next_layer') or {}),
                'layers': [dict(item) for item in list(review_state.get('layers') or [])],
            },
            'separation_of_duties': {
                'allow_self_review': bool(effective_policy.get('allow_self_review', True)),
                'require_reason': bool(effective_policy.get('require_reason', False)),
                'block_on_rejection': bool(effective_policy.get('block_on_rejection', True)),
                'self_review_detected': self_review_detected,
                'distinct_reviewer_count': len(reviewer_ids),
                'reviewers': reviewer_ids,
            },
            'ordered_reviews': [
                {
                    'ordinal': idx + 1,
                    'review_id': str(item.get('review_id') or ''),
                    'layer_id': str(item.get('layer_id') or ''),
                    'label': str(item.get('label') or ''),
                    'requested_role': str(item.get('requested_role') or ''),
                    'decision': str(item.get('decision') or ''),
                    'actor': str(item.get('actor') or ''),
                    'reason': str(item.get('reason') or ''),
                    'created_at': item.get('created_at'),
                    'decided_at': item.get('decided_at'),
                }
                for idx, item in enumerate(ordered_reviews)
            ],
            'review_summary': dict(payload.get('review') or {}),
            'observed_versions': dict(payload.get('observed_versions') or payload.get('source_observed_versions') or {}),
            'fingerprints': dict(payload.get('fingerprints') or payload.get('source_fingerprints') or {}),
            'created_promotions': [dict(item) for item in list(payload.get('created_promotions') or [])],
            'timeline': timeline,
        }
        integrity = self._portfolio_evidence_integrity(
            report_type=report['report_type'],
            scope=scope,
            payload=report,
            actor=actor,
            export_policy=export_policy,
            signing_policy=signing_policy,
        )
        return {
            'ok': True,
            'simulation_id': simulation_id,
            'report': report,
            'integrity': integrity,
            'scope': scope,
        }

    @staticmethod
    def _baseline_promotion_simulation_evidence_retention_days(simulation: dict[str, Any] | None) -> int:
        payload = dict((simulation or {}).get('simulation_policy') or {})
        raw = payload.get('immutable_retention_days')
        if raw is None:
            raw = payload.get('retention_days')
        try:
            value = int(raw or 365)
        except Exception:
            value = 365
        return max(7, value)

    @staticmethod
    def _baseline_promotion_simulation_evidence_max_packages(simulation: dict[str, Any] | None) -> int:
        payload = dict((simulation or {}).get('simulation_policy') or {})
        raw = payload.get('max_evidence_packages')
        if raw is None:
            raw = payload.get('max_packages')
        try:
            value = int(raw or 50)
        except Exception:
            value = 50
        return max(1, value)

    def _baseline_promotion_simulation_evidence_classification(
        self,
        *,
        simulation: dict[str, Any] | None,
        release: dict[str, Any] | None = None,
    ) -> str:
        simulation_payload = dict(simulation or {})
        simulation_policy = dict(simulation_payload.get('simulation_policy') or {})
        classification = str(
            simulation_policy.get('evidence_classification')
            or simulation_policy.get('classification')
            or ''
        ).strip()
        if classification:
            return classification
        scope = dict(simulation_payload.get('scope') or {})
        environment_key = self._normalize_portfolio_environment_name(
            scope.get('environment')
            or (release or {}).get('environment')
            or 'default'
        )
        candidate_baselines = self._normalize_baseline_catalog_environment_entries(dict(simulation_payload.get('candidate_baselines') or {}))
        candidate_entry = dict(candidate_baselines.get(environment_key) or candidate_baselines.get('default') or {})
        classification = str(candidate_entry.get('evidence_classification') or candidate_entry.get('classification') or '').strip()
        if classification:
            return classification
        if release:
            promotion = dict(((release.get('metadata') or {}).get('baseline_promotion')) or {})
            candidate_baselines = self._normalize_baseline_catalog_environment_entries(dict(promotion.get('candidate_baselines') or {}))
            candidate_entry = dict(candidate_baselines.get(environment_key) or candidate_baselines.get('default') or {})
            classification = str(candidate_entry.get('evidence_classification') or candidate_entry.get('classification') or '').strip()
            if classification:
                return classification
        return 'regulated-enterprise-evidence'

    def _baseline_promotion_simulation_evidence_export_policy(
        self,
        *,
        simulation: dict[str, Any] | None,
        release: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        signing_policy = self._baseline_promotion_simulation_effective_signing_policy(simulation=simulation)
        escrow_policy = self._baseline_promotion_simulation_effective_escrow_policy(simulation=simulation, release=release)
        embed_artifact_content = True
        if bool(escrow_policy.get('enabled')) and not bool(escrow_policy.get('allow_inline_fallback', True)):
            embed_artifact_content = False
        return {
            'enabled': True,
            'require_signature': True,
            'embed_artifact_content': embed_artifact_content,
            'timeline_limit': 250,
            'artifact_format': 'zip',
            'retention_days': self._baseline_promotion_simulation_evidence_retention_days(simulation),
            'max_packages': self._baseline_promotion_simulation_evidence_max_packages(simulation),
            'registry_mode': 'append_only_hash_chain',
            'signer_key_id': str(signing_policy.get('key_id') or 'openmiura-local').strip() or 'openmiura-local',
            'escrow_enabled': bool(escrow_policy.get('enabled')),
        }

    def _baseline_promotion_simulation_evidence_package_manifest(
        self,
        *,
        package_id: str,
        attestation_export: dict[str, Any],
        review_audit_export: dict[str, Any],
        simulation: dict[str, Any],
        export_policy: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], str]:
        artifacts = [
            {
                'artifact_id': str(((attestation_export.get('report') or {}).get('report_id') or '')),
                'kind': 'simulation_attestation',
                'report_type': str(((attestation_export.get('report') or {}).get('report_type') or '')),
                'payload_hash': str((attestation_export.get('integrity') or {}).get('payload_hash') or self._stable_digest(dict(attestation_export.get('report') or {}))),
            },
            {
                'artifact_id': str(((review_audit_export.get('report') or {}).get('report_id') or '')),
                'kind': 'simulation_review_audit',
                'report_type': str(((review_audit_export.get('report') or {}).get('report_type') or '')),
                'payload_hash': str((review_audit_export.get('integrity') or {}).get('payload_hash') or self._stable_digest(dict(review_audit_export.get('report') or {}))),
            },
        ]
        manifest = {
            'package_id': package_id,
            'report_type': 'openmiura_baseline_promotion_simulation_evidence_package_manifest_v1',
            'generated_at': time.time(),
            'registry_mode': str((export_policy or {}).get('registry_mode') or 'append_only_hash_chain'),
            'simulation_id': str(simulation.get('simulation_id') or ''),
            'catalog_id': str(simulation.get('catalog_id') or ''),
            'candidate_catalog_version': str(simulation.get('candidate_catalog_version') or ''),
            'artifact_count': len(artifacts),
            'artifacts': artifacts,
            'simulation_fingerprint': str((simulation.get('fingerprints') or {}).get('request_hash') or self._stable_digest(dict(simulation.get('request') or {}))),
        }
        return manifest, self._stable_digest(manifest)

    def _build_baseline_promotion_simulation_evidence_artifact_archive(
        self,
        *,
        package_payload: dict[str, Any],
        integrity: dict[str, Any],
        export_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        package_id = str(package_payload.get('package_id') or '').strip()
        promotion_id = str(((package_payload.get('source_promotion') or {}).get('promotion_id')) or '').strip()
        simulation_id = str(((package_payload.get('simulation') or {}).get('simulation_id')) or '').strip()
        generated_at = float(package_payload.get('generated_at') or time.time())
        entries_payload = {
            'manifest.json': dict(package_payload.get('manifest') or {}),
            'package.json': package_payload,
            'integrity.json': integrity,
            'simulation_attestation_export.json': dict(((package_payload.get('artifacts') or {}).get('simulation_attestation_export') or {})),
            'simulation_review_audit_export.json': dict(((package_payload.get('artifacts') or {}).get('simulation_review_audit_export') or {})),
            'registry_entry.json': dict(package_payload.get('registry_entry_preview') or {}),
        }
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
        filename_prefix = f'openmiura-baseline-promotion-simulation-{promotion_id or simulation_id or "simulation"}-{package_id or "artifact"}'
        return {
            'artifact_type': 'openmiura_baseline_promotion_simulation_evidence_artifact_v1',
            'package_id': package_id,
            'promotion_id': promotion_id or None,
            'simulation_id': simulation_id or None,
            'filename': f'{filename_prefix}.zip',
            'media_type': 'application/zip',
            'format': str((export_policy or {}).get('artifact_format') or 'zip'),
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

    def _archive_baseline_promotion_simulation_evidence_artifact_external(
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
        provider = str(normalized.get('provider') or 'filesystem-governed').strip() or 'filesystem-governed'
        if provider not in {'filesystem-governed', 'filesystem-object-lock', 'object-lock-filesystem'}:
            return {
                'enabled': True,
                'archived': False,
                'provider': provider,
                'reason': 'provider_not_supported_for_simulation_evidence',
            }
        content_b64 = str(artifact.get('content_b64') or '').strip()
        if not content_b64:
            return {
                'enabled': True,
                'archived': False,
                'provider': provider,
                'reason': 'artifact_content_missing',
            }
        generated_ts = float(generated_at) if generated_at is not None else float(package_payload.get('generated_at') or time.time())
        scope = dict(package_payload.get('scope') or {})
        archive_bytes = base64.b64decode(content_b64.encode('ascii'))
        artifact_sha256 = hashlib.sha256(archive_bytes).hexdigest()
        receipt_id = str(uuid.uuid4())
        filename = str(artifact.get('filename') or f'{package_payload.get("package_id")}.zip').strip() or f'{package_payload.get("package_id")}.zip'
        promotion_id = str(((package_payload.get('source_promotion') or {}).get('promotion_id')) or '').strip() or 'promotion'
        simulation_id = str(((package_payload.get('simulation') or {}).get('simulation_id')) or '').strip() or 'simulation'
        package_id = str(package_payload.get('package_id') or '').strip() or 'package'
        manifest_payload = dict((package_payload.get('manifest') or {}))
        manifest_bytes = self._canonical_json_bytes(manifest_payload)
        immutable_until = retention.get('retain_until')
        if immutable_until is None:
            immutable_until = generated_ts + (max(1, int(normalized.get('immutable_retention_days') or 365)) * 86400.0)
        root_dir = Path(str(normalized.get('root_dir') or 'data/openclaw_evidence_escrow'))
        archive_dir = root_dir.joinpath(
            str(normalized.get('archive_namespace') or 'baseline-promotion-simulation-evidence'),
            str(scope.get('tenant_id') or 'global'),
            str(scope.get('workspace_id') or 'default'),
            str(scope.get('environment') or 'default'),
            str(promotion_id or 'promotion'),
            str(package_id or 'package'),
        )
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive_path = archive_dir.joinpath(filename)
        manifest_path = archive_dir.joinpath('manifest.json')
        receipt_path = archive_dir.joinpath(f'{filename}.receipt.json')
        lock_path = archive_dir.joinpath(f'{filename}.lock.json')

        archive_path_public = self._filesystem_path(archive_path)
        manifest_path_public = self._filesystem_path(manifest_path)
        receipt_path_public = self._filesystem_path(receipt_path)
        lock_path_public = self._filesystem_path(lock_path)

        if self._path_exists(archive_path):
            existing_bytes = self._read_file_bytes(archive_path)
            if hashlib.sha256(existing_bytes).hexdigest() != artifact_sha256:
                return {
                    'enabled': True,
                    'archived': False,
                    'provider': provider,
                    'reason': 'immutable_archive_conflict',
                    'archive_path': archive_path_public,
                }
        else:
            self._write_file_if_absent(archive_path, archive_bytes)
        if not self._path_exists(manifest_path):
            self._write_file_if_absent(manifest_path, manifest_bytes)
        object_lock_enabled = bool(normalized.get('object_lock_enabled'))
        if object_lock_enabled:
            lock_payload = {
                'lock_type': 'openmiura_baseline_promotion_simulation_object_lock_v1',
                'provider': provider,
                'archive_path': archive_path_public,
                'artifact_sha256': artifact_sha256,
                'package_id': package_id,
                'promotion_id': promotion_id,
                'simulation_id': simulation_id,
                'immutable_until': immutable_until,
                'retention_mode': str(normalized.get('retention_mode') or 'GOVERNANCE'),
                'legal_hold': bool(retention.get('legal_hold', False)),
                'locked_at': generated_ts,
            }
            if lock_path.exists():
                existing_lock = json.loads(self._read_file_text(lock_path, encoding='utf-8'))
                if str(existing_lock.get('artifact_sha256') or '') != artifact_sha256:
                    return {
                        'enabled': True,
                        'archived': False,
                        'provider': provider,
                        'reason': 'object_lock_conflict',
                        'lock_path': lock_path_public,
                    }
            elif bool(normalized.get('lock_sidecar', True)):
                self._write_file_if_absent(lock_path, self._canonical_json_bytes(lock_payload))
        receipt_payload = {
            'receipt_type': 'openmiura_baseline_promotion_simulation_evidence_escrow_receipt_v1',
            'receipt_id': receipt_id,
            'provider': provider,
            'mode': str(normalized.get('mode') or 'filesystem_external'),
            'archived': True,
            'archived_at': generated_ts,
            'archived_by': str(actor or 'system').strip() or 'system',
            'package_id': package_id,
            'promotion_id': promotion_id,
            'simulation_id': simulation_id,
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
            report_type='openmiura_baseline_promotion_simulation_evidence_escrow_receipt_v1',
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
        if receipt_path.exists():
            existing_receipt = json.loads(self._read_file_text(receipt_path, encoding='utf-8'))
            if str(existing_receipt.get('artifact_sha256') or '') != artifact_sha256:
                return {
                    'enabled': True,
                    'archived': False,
                    'provider': provider,
                    'reason': 'immutable_receipt_conflict',
                    'receipt_path': receipt_path_public,
                }
        else:
            self._write_file_if_absent(receipt_path, receipt_bytes)
        return receipt_payload

    def _load_baseline_promotion_simulation_evidence_artifact_from_escrow(self, *, escrow: dict[str, Any] | None = None) -> dict[str, Any] | None:
        receipt = dict(escrow or {})
        archive_path = str(receipt.get('archive_path') or '').strip()
        if not archive_path:
            return None
        path = Path(archive_path)
        if not self._path_exists(path) or not self._path_is_file(path):
            return None
        archive_bytes = self._read_file_bytes(path)
        return {
            'artifact_type': 'openmiura_baseline_promotion_simulation_evidence_artifact_v1',
            'package_id': receipt.get('package_id'),
            'promotion_id': receipt.get('promotion_id'),
            'simulation_id': receipt.get('simulation_id'),
            'filename': path.name,
            'media_type': 'application/zip',
            'format': 'zip',
            'sha256': hashlib.sha256(archive_bytes).hexdigest(),
            'size_bytes': len(archive_bytes),
            'encoding': 'base64',
            'content_b64': base64.b64encode(archive_bytes).decode('ascii'),
            'escrow': self._redact_large_blob(receipt),
        }

    def _verify_baseline_promotion_simulation_escrow_receipt(
        self,
        *,
        escrow: dict[str, Any] | None,
        now_ts: float | None = None,
    ) -> dict[str, Any]:
        receipt = dict(escrow or {})
        if not bool(receipt.get('archived')):
            return {'required': False, 'valid': True, 'status': 'not_archived'}
        archive_path = str(receipt.get('archive_path') or '').strip()
        if not archive_path:
            return {'required': True, 'valid': False, 'status': 'missing_archive_path'}
        path = Path(archive_path)
        if not self._path_exists(path) or not self._path_is_file(path):
            return {'required': True, 'valid': False, 'status': 'archive_missing'}
        archive_bytes = self._read_file_bytes(path)
        archive_sha256 = hashlib.sha256(archive_bytes).hexdigest()
        canonical = {
            'receipt_type': 'openmiura_baseline_promotion_simulation_evidence_escrow_receipt_v1',
            'receipt_id': receipt.get('receipt_id'),
            'provider': receipt.get('provider'),
            'mode': receipt.get('mode'),
            'archived': True,
            'archived_at': receipt.get('archived_at'),
            'archived_by': receipt.get('archived_by'),
            'package_id': receipt.get('package_id'),
            'promotion_id': receipt.get('promotion_id'),
            'simulation_id': receipt.get('simulation_id'),
            'scope': dict(receipt.get('scope') or {}),
            'archive_path': archive_path,
            'archive_uri': receipt.get('archive_uri'),
            'receipt_path': receipt.get('receipt_path'),
            'manifest_path': receipt.get('manifest_path'),
            'artifact_sha256': receipt.get('artifact_sha256'),
            'manifest_hash': receipt.get('manifest_hash'),
            'immutable_until': receipt.get('immutable_until'),
            'classification': receipt.get('classification'),
            'legal_hold': bool(receipt.get('legal_hold', False)),
            'object_lock_enabled': bool(receipt.get('object_lock_enabled', False)),
            'retention_mode': receipt.get('retention_mode'),
            'lock_path': receipt.get('lock_path'),
            'delete_protection': bool(receipt.get('delete_protection', False)),
        }
        crypto_verify = self._verify_portfolio_crypto_signature(
            report_type='openmiura_baseline_promotion_simulation_evidence_escrow_receipt_v1',
            scope=dict(receipt.get('scope') or {}),
            payload=canonical,
            integrity={
                'signed': True,
                'signature': receipt.get('signature'),
                'signature_scheme': receipt.get('signature_scheme'),
                'signature_input': receipt.get('signature_input'),
                'public_key': receipt.get('public_key'),
                'signer_key_id': str(((receipt.get('signature_input') or {}).get('signer_key_id')) or ''),
                'payload_hash': self._stable_digest(canonical),
                'crypto_v2': True,
            },
        )
        resolved_now = float(now_ts) if now_ts is not None else time.time()
        immutable_active = receipt.get('immutable_until') is not None and float(receipt.get('immutable_until') or 0.0) >= resolved_now
        archive_hash_valid = str(receipt.get('artifact_sha256') or '') == archive_sha256
        receipt_path = str(receipt.get('receipt_path') or '').strip()
        receipt_file_present = True
        receipt_file_valid = True
        if receipt_path:
            receipt_file = Path(receipt_path)
            if not self._path_exists(receipt_file) or not self._path_is_file(receipt_file):
                receipt_file_present = False
                receipt_file_valid = False
            else:
                try:
                    receipt_payload = json.loads(self._read_file_text(receipt_file, encoding='utf-8'))
                except Exception:
                    receipt_payload = {}
                compare_keys = [
                    'receipt_id',
                    'provider',
                    'mode',
                    'package_id',
                    'promotion_id',
                    'simulation_id',
                    'archive_path',
                    'artifact_sha256',
                    'manifest_hash',
                    'immutable_until',
                    'retention_mode',
                ]
                receipt_file_valid = all(receipt_payload.get(key) == receipt.get(key) for key in compare_keys)
                receipt_file_valid = receipt_file_valid and str(receipt_payload.get('signature') or '') == str(receipt.get('signature') or '')
        manifest_path = str(receipt.get('manifest_path') or '').strip()
        manifest_present = True
        manifest_hash_valid = True
        if manifest_path:
            manifest_file = Path(manifest_path)
            if not self._path_exists(manifest_file) or not self._path_is_file(manifest_file):
                manifest_present = False
                manifest_hash_valid = False
            else:
                try:
                    manifest_payload = json.loads(self._read_file_text(manifest_file, encoding='utf-8'))
                except Exception:
                    manifest_payload = {}
                manifest_payload_for_hash = dict(manifest_payload)
                manifest_payload_for_hash.pop('manifest_hash', None)
                manifest_hash_valid = str(receipt.get('manifest_hash') or '') == self._stable_digest(manifest_payload_for_hash)
        object_lock_valid = True
        if bool(receipt.get('object_lock_enabled')):
            lock_path = str(receipt.get('lock_path') or '').strip()
            object_lock_valid = False
            if lock_path:
                lock_file = Path(lock_path)
                if self._path_exists(lock_file) and self._path_is_file(lock_file):
                    try:
                        lock_payload = json.loads(self._read_file_text(lock_file, encoding='utf-8'))
                    except Exception:
                        lock_payload = {}
                    object_lock_valid = (
                        str(lock_payload.get('artifact_sha256') or '') == archive_sha256
                        and str(lock_payload.get('archive_path') or '') == archive_path
                        and str(lock_payload.get('retention_mode') or '') == str(receipt.get('retention_mode') or '')
                    )
            if not object_lock_valid and not lock_path:
                object_lock_valid = False
        valid = (
            archive_hash_valid
            and bool(crypto_verify.get('valid'))
            and receipt_file_valid
            and manifest_hash_valid
            and (object_lock_valid or not bool(receipt.get('object_lock_enabled')))
        )
        status = 'verified' if valid else 'failed'
        if not archive_hash_valid:
            status = 'artifact_hash_mismatch'
        elif not bool(crypto_verify.get('valid')):
            status = 'signature_invalid'
        elif not receipt_file_present:
            status = 'receipt_missing'
        elif not receipt_file_valid:
            status = 'receipt_mismatch'
        elif not manifest_present:
            status = 'manifest_missing'
        elif not manifest_hash_valid:
            status = 'manifest_hash_mismatch'
        elif bool(receipt.get('object_lock_enabled')) and not object_lock_valid:
            status = 'object_lock_invalid'
        return {
            'required': True,
            'valid': valid,
            'status': status,
            'archive_hash_valid': archive_hash_valid,
            'artifact_sha256': archive_sha256,
            'immutable_active': immutable_active,
            'object_lock_valid': object_lock_valid,
            'receipt_file_present': receipt_file_present,
            'receipt_file_valid': receipt_file_valid,
            'manifest_present': manifest_present,
            'manifest_hash_valid': manifest_hash_valid,
            'crypto': crypto_verify,
            'receipt': self._redact_large_blob(receipt),
        }

    def _baseline_promotion_simulation_evidence_registry_consistency(
        self,
        *,
        stored_package: dict[str, Any] | None,
        registry_entries: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        package = dict(stored_package or {})
        stored_registry = dict(package.get('registry_entry') or {})
        entries = [dict(item) for item in list(registry_entries or [])]
        entries.sort(key=lambda item: (int(item.get('sequence') or 0), float(item.get('appended_at') or 0.0), str(item.get('entry_id') or '')))
        chain_valid = True
        previous_hash = ''
        expected_sequence = 1
        for item in entries:
            item_core = dict(item.get('entry_core') or {k: v for k, v in item.items() if k not in {'entry_hash', 'entry_core'}})
            if int(item.get('sequence') or 0) != expected_sequence:
                chain_valid = False
                expected_sequence = int(item.get('sequence') or expected_sequence)
            if str(item.get('previous_entry_hash') or '') != previous_hash:
                chain_valid = False
            if self._stable_digest(item_core) != str(item.get('entry_hash') or ''):
                chain_valid = False
            previous_hash = str(item.get('entry_hash') or '')
            expected_sequence += 1
        target_entry_id = str(stored_registry.get('entry_id') or '').strip()
        target_package_id = str(package.get('package_id') or '').strip()
        matching = None
        if target_entry_id:
            for item in entries:
                if str(item.get('entry_id') or '') == target_entry_id:
                    matching = dict(item)
                    break
        if matching is None and target_package_id:
            for item in entries:
                if str(item.get('package_id') or '') == target_package_id:
                    matching = dict(item)
                    break
        membership_valid = matching is not None if (target_entry_id or target_package_id) else not bool(entries)
        match_valid = True
        if matching is not None:
            compare_keys = ['entry_id', 'sequence', 'entry_hash', 'previous_entry_hash']
            for key in compare_keys:
                if stored_registry.get(key) not in (None, '', 0) and matching.get(key) != stored_registry.get(key):
                    match_valid = False
            if str(package.get('manifest_hash') or '').strip() and str(matching.get('manifest_hash') or '').strip() != str(package.get('manifest_hash') or '').strip():
                match_valid = False
        elif target_entry_id or target_package_id:
            match_valid = False
        latest = dict(entries[-1] or {}) if entries else {}
        return {
            'entry_id': str((matching or stored_registry).get('entry_id') or ''),
            'sequence': int((matching or stored_registry).get('sequence') or 0),
            'entry_hash': str((matching or stored_registry).get('entry_hash') or ''),
            'previous_entry_hash': str((matching or stored_registry).get('previous_entry_hash') or ''),
            'membership_valid': membership_valid,
            'match_valid': match_valid,
            'chain_valid': chain_valid,
            'latest_entry_id': str(latest.get('entry_id') or ''),
            'latest_entry_hash': str(latest.get('entry_hash') or ''),
            'count': len(entries),
        }

    def _baseline_promotion_simulation_evidence_reconciliation_item(
        self,
        *,
        stored_package: dict[str, Any],
        registry_entries: list[dict[str, Any]] | None = None,
        now_ts: float | None = None,
    ) -> dict[str, Any]:
        package = dict(stored_package or {})
        escrow = dict(package.get('escrow') or {})
        verification = self._verify_baseline_promotion_simulation_evidence_artifact_payload(
            artifact=dict(package.get('artifact') or {}),
            registry_entries=registry_entries,
            stored_package=package,
            now_ts=now_ts,
        )
        registry = self._baseline_promotion_simulation_evidence_registry_consistency(
            stored_package=package,
            registry_entries=registry_entries,
        )
        drift_reasons: list[str] = []
        verification_status = str(verification.get('error') or 'verification_unavailable')
        verification_valid = False
        checks: dict[str, Any] = {}
        escrow_status = 'not_archived'
        escrow_verify = self._verify_baseline_promotion_simulation_escrow_receipt(escrow=escrow, now_ts=now_ts) if escrow else {'required': False, 'valid': True, 'status': 'not_archived'}
        if verification.get('ok'):
            verification_payload = dict(verification.get('verification') or {})
            verification_status = str(verification_payload.get('status') or '')
            verification_valid = bool(verification_payload.get('valid'))
            checks = dict(verification_payload.get('checks') or {})
            escrow_verify = dict(verification_payload.get('escrow') or escrow_verify)
            escrow_status = str(escrow_verify.get('status') or 'not_archived')
            if not bool(checks.get('archive_hash_valid', True)):
                drift_reasons.append('artifact_hash_mismatch')
            if not bool(checks.get('manifest_hash_valid', True)):
                drift_reasons.append('manifest_hash_mismatch')
            if not bool(checks.get('manifest_links_valid', True)):
                drift_reasons.append('manifest_links_invalid')
            if not bool(checks.get('package_integrity_valid', True)):
                drift_reasons.append('package_integrity_invalid')
            if not bool(checks.get('attestation_export_valid', True)):
                drift_reasons.append('attestation_export_invalid')
            if not bool(checks.get('review_audit_export_valid', True)):
                drift_reasons.append('review_audit_export_invalid')
            if not bool(checks.get('stored_package_match_valid', True)):
                drift_reasons.append('stored_package_mismatch')
        else:
            escrow_status = str(escrow_verify.get('status') or 'not_archived')
            drift_reasons.append(str(verification.get('error') or 'verification_failed'))
        if escrow and bool(escrow.get('archived')):
            if not bool(escrow_verify.get('valid')):
                drift_reasons.append(str(escrow_status or 'escrow_receipt_invalid'))
            elif str(escrow_status or '') != 'verified':
                drift_reasons.append(str(escrow_status or 'escrow_receipt_invalid'))
            lock_expected = bool(escrow.get('object_lock_enabled')) and bool(escrow.get('immutable_until'))
            if lock_expected:
                try:
                    lock_expected = float(escrow.get('immutable_until') or 0.0) >= float(now_ts if now_ts is not None else time.time())
                except Exception:
                    lock_expected = True
            if lock_expected and not (bool(escrow_verify.get('object_lock_valid')) and bool(escrow_verify.get('immutable_active'))):
                drift_reasons.append('immutable_lock_inactive')
            if not bool(escrow_verify.get('receipt_file_valid', True)):
                drift_reasons.append('receipt_sidecar_invalid')
            if not bool(escrow_verify.get('manifest_hash_valid', True)):
                drift_reasons.append('manifest_sidecar_invalid')
        if not bool(registry.get('membership_valid')):
            drift_reasons.append('registry_entry_missing')
        if not bool(registry.get('match_valid')):
            drift_reasons.append('registry_entry_mismatch')
        if not bool(registry.get('chain_valid')):
            drift_reasons.append('registry_chain_invalid')
        unique_reasons: list[str] = []
        for reason in drift_reasons:
            normalized = str(reason or '').strip()
            if normalized and normalized not in unique_reasons:
                unique_reasons.append(normalized)
        status = 'aligned' if not unique_reasons else 'drifted'
        artifact_meta = dict(package.get('artifact') or {})
        if verification.get('ok'):
            artifact_meta = dict(verification.get('artifact') or artifact_meta)
        return {
            'package_id': str(package.get('package_id') or ''),
            'simulation_id': str(package.get('simulation_id') or ''),
            'created_at': package.get('created_at'),
            'reconciliation_status': status,
            'verification_status': verification_status,
            'verification_valid': verification_valid,
            'drift_reasons': unique_reasons,
            'artifact': {
                'artifact_type': str(artifact_meta.get('artifact_type') or ''),
                'sha256': str(artifact_meta.get('sha256') or ''),
                'size_bytes': int(artifact_meta.get('size_bytes') or 0),
                'filename': str(artifact_meta.get('filename') or ''),
                'source': str(artifact_meta.get('source') or ('escrow' if bool(escrow.get('archived')) else 'inline')),
            },
            'escrow': {
                'archived': bool(escrow.get('archived')),
                'status': escrow_status,
                'receipt_id': str(escrow.get('receipt_id') or ''),
                'archive_path': str(escrow.get('archive_path') or ''),
                'immutable_until': escrow.get('immutable_until'),
                'immutable_active': bool(escrow_verify.get('immutable_active')),
                'object_lock_enabled': bool(escrow.get('object_lock_enabled')),
                'object_lock_valid': bool(escrow_verify.get('object_lock_valid', True)),
                'receipt_file_valid': bool(escrow_verify.get('receipt_file_valid', True)),
                'manifest_hash_valid': bool(escrow_verify.get('manifest_hash_valid', True)),
                'archive_hash_valid': bool(escrow_verify.get('archive_hash_valid', True)),
            },
            'registry': registry,
            'checks': {
                'verification_ok': bool(verification.get('ok')),
                'verification_valid': verification_valid,
                'escrow_receipt_valid': bool(escrow_verify.get('valid', True)),
                'registry_membership_valid': bool(registry.get('membership_valid')),
                'registry_match_valid': bool(registry.get('match_valid')),
                'registry_chain_valid': bool(registry.get('chain_valid')),
                'stored_package_match_valid': bool(checks.get('stored_package_match_valid', True)),
            },
        }

