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


class _OpenClawBaselineRolloutSupportEvidenceMixinB:
    """Sub-mixin: evidence methods on OpenClawBaselineRolloutSupportMixin."""

    @staticmethod
    def _baseline_promotion_simulation_evidence_reconciliation_summary(items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        payload = [dict(item) for item in list(items or [])]
        aligned_count = sum(1 for item in payload if str(item.get('reconciliation_status') or '') == 'aligned')
        drifted_count = sum(1 for item in payload if str(item.get('reconciliation_status') or '') == 'drifted')
        escrowed_count = sum(1 for item in payload if bool((item.get('escrow') or {}).get('archived')))
        missing_archive_count = sum(1 for item in payload if str(((item.get('escrow') or {}).get('status')) or '') == 'archive_missing')
        lock_drift_count = sum(1 for item in payload if 'immutable_lock_inactive' in list(item.get('drift_reasons') or []))
        registry_drift_count = sum(1 for item in payload if any(reason.startswith('registry_') for reason in list(item.get('drift_reasons') or [])))
        receipt_drift_count = sum(1 for item in payload if any(reason in {'receipt_sidecar_invalid', 'manifest_sidecar_invalid', 'receipt_missing', 'receipt_mismatch', 'manifest_missing', 'manifest_hash_mismatch'} for reason in list(item.get('drift_reasons') or [])))
        overall_status = 'aligned' if drifted_count == 0 else 'drifted'
        latest = dict(payload[0] or {}) if payload else {}
        return {
            'count': len(payload),
            'aligned_count': aligned_count,
            'drifted_count': drifted_count,
            'escrowed_count': escrowed_count,
            'missing_archive_count': missing_archive_count,
            'lock_drift_count': lock_drift_count,
            'registry_drift_count': registry_drift_count,
            'receipt_drift_count': receipt_drift_count,
            'overall_status': overall_status,
            'latest_package_id': str(latest.get('package_id') or ''),
            'latest_status': str(latest.get('reconciliation_status') or ''),
            'latest_archive_path': str((((latest.get('escrow') or {}).get('archive_path')) or '')),
        }

    def _list_baseline_promotion_simulation_evidence_reconciliation_sessions(self, release: dict[str, Any] | None) -> list[dict[str, Any]]:
        metadata = dict((release or {}).get('metadata') or {})
        promotion = dict(metadata.get('baseline_promotion') or {})
        items = [dict(item) for item in list(promotion.get('simulation_evidence_reconciliation_sessions') or [])]
        items.sort(key=lambda item: (float(item.get('reconciled_at') or 0.0), str(item.get('reconciliation_id') or '')), reverse=True)
        return items

    def _store_baseline_promotion_simulation_evidence_reconciliation_session(
        self,
        gw,
        *,
        release: dict[str, Any],
        session_record: dict[str, Any],
        history_limit: int = 20,
    ) -> dict[str, Any]:
        metadata = dict(release.get('metadata') or {})
        promotion = dict(metadata.get('baseline_promotion') or {})
        sessions = [dict(item) for item in list(promotion.get('simulation_evidence_reconciliation_sessions') or [])]
        sessions = [item for item in sessions if str(item.get('reconciliation_id') or '') != str(session_record.get('reconciliation_id') or '')]
        sessions.append(dict(session_record))
        sessions.sort(key=lambda item: (float(item.get('reconciled_at') or 0.0), str(item.get('reconciliation_id') or '')), reverse=True)
        promotion['simulation_evidence_reconciliation_sessions'] = sessions[: max(1, int(history_limit or 20))]
        promotion['current_simulation_evidence_reconciliation'] = dict(session_record)
        promotion = self._append_baseline_promotion_timeline_event(
            promotion,
            kind='evidence',
            label='baseline_promotion_simulation_evidence_reconciled',
            actor=str(session_record.get('reconciled_by') or 'system'),
            reconciliation_id=str(session_record.get('reconciliation_id') or ''),
            package_count=int((session_record.get('summary') or {}).get('count') or 0),
            drifted_count=int((session_record.get('summary') or {}).get('drifted_count') or 0),
            overall_status=str((session_record.get('summary') or {}).get('overall_status') or ''),
            latest_package_id=str((session_record.get('summary') or {}).get('latest_package_id') or ''),
        )
        metadata['baseline_promotion'] = promotion
        return gw.audit.update_release_bundle(
            str(release.get('release_id') or ''),
            status=release.get('status'),
            notes=release.get('notes'),
            metadata=metadata,
            tenant_id=release.get('tenant_id'),
            workspace_id=release.get('workspace_id'),
            environment=release.get('environment'),
        ) or release

    def _list_baseline_promotion_simulation_evidence_packages(self, release: dict[str, Any] | None, *, include_content: bool = False) -> list[dict[str, Any]]:
        metadata = dict((release or {}).get('metadata') or {})
        promotion = dict(metadata.get('baseline_promotion') or {})
        items = [dict(item) for item in list(promotion.get('simulation_evidence_packages') or [])]
        sanitized: list[dict[str, Any]] = []
        for item in items:
            record = dict(item)
            artifact = dict(record.get('artifact') or {})
            if artifact and not include_content:
                artifact.pop('content_b64', None)
                record['artifact'] = artifact
            sanitized.append(record)
        sanitized.sort(key=lambda item: float(item.get('created_at') or 0.0), reverse=True)
        return sanitized

    def _store_baseline_promotion_simulation_evidence_package(
        self,
        gw,
        *,
        release: dict[str, Any],
        package_record: dict[str, Any],
        registry_entry: dict[str, Any],
    ) -> dict[str, Any]:
        metadata = dict(release.get('metadata') or {})
        promotion = dict(metadata.get('baseline_promotion') or {})
        packages = [dict(item) for item in list(promotion.get('simulation_evidence_packages') or [])]
        packages = [item for item in packages if str(item.get('package_id') or '') != str(package_record.get('package_id') or '')]
        packages.append(dict(package_record))
        packages.sort(key=lambda item: float(item.get('created_at') or 0.0), reverse=True)
        max_packages = max(1, int((package_record.get('retention') or {}).get('max_packages') or self._baseline_promotion_simulation_evidence_max_packages(package_record.get('source_simulation'))))
        promotion['simulation_evidence_packages'] = packages[: max(1, max_packages * 3)]
        registry = [dict(item) for item in list(promotion.get('simulation_export_registry') or [])]
        registry.append(dict(registry_entry))
        registry.sort(key=lambda item: (int(item.get('sequence') or 0), float(item.get('appended_at') or 0.0), str(item.get('entry_id') or '')))
        promotion['simulation_export_registry'] = registry
        promotion = self._append_baseline_promotion_timeline_event(
            promotion,
            kind='evidence',
            label='baseline_promotion_simulation_evidence_packaged',
            actor=str(package_record.get('created_by') or 'system'),
            simulation_id=str(package_record.get('simulation_id') or ''),
            package_id=str(package_record.get('package_id') or ''),
            registry_entry_id=str(registry_entry.get('entry_id') or ''),
            immutable=True,
            artifact_sha256=str(((package_record.get('artifact') or {}).get('sha256')) or ''),
        )
        escrow = dict(package_record.get('escrow') or {})
        if bool(escrow.get('archived')):
            promotion = self._append_baseline_promotion_timeline_event(
                promotion,
                kind='evidence',
                label='baseline_promotion_simulation_evidence_escrowed',
                actor=str(package_record.get('created_by') or 'system'),
                simulation_id=str(package_record.get('simulation_id') or ''),
                package_id=str(package_record.get('package_id') or ''),
                receipt_id=str(escrow.get('receipt_id') or ''),
                archive_path=str(escrow.get('archive_path') or ''),
                immutable_until=escrow.get('immutable_until'),
                object_lock_enabled=bool(escrow.get('object_lock_enabled')),
            )
        metadata['baseline_promotion'] = promotion
        return gw.audit.update_release_bundle(
            str(release.get('release_id') or ''),
            status=release.get('status'),
            notes=release.get('notes'),
            metadata=metadata,
            tenant_id=release.get('tenant_id'),
            workspace_id=release.get('workspace_id'),
            environment=release.get('environment'),
        ) or release

    def _build_baseline_promotion_simulation_evidence_package_export_payload(
        self,
        *,
        release: dict[str, Any],
        simulation: dict[str, Any],
        actor: str,
        timeline_limit: int | None = None,
    ) -> dict[str, Any]:
        attestation_export = self._build_baseline_promotion_simulation_attestation_export_payload(
            simulation=simulation,
            actor=actor,
            timeline_limit=timeline_limit,
        )
        review_audit_export = self._build_baseline_promotion_simulation_review_audit_export_payload(
            simulation=simulation,
            actor=actor,
            timeline_limit=timeline_limit,
        )
        export_policy = self._baseline_promotion_simulation_evidence_export_policy(simulation=simulation, release=release)
        escrow_policy = self._baseline_promotion_simulation_effective_escrow_policy(simulation=simulation, release=release)
        retention_days = self._baseline_promotion_simulation_evidence_retention_days(simulation)
        retention_until = time.time() + (retention_days * 86400.0)
        generated_at = time.time()
        package_id = f'sim-evidence-{uuid.uuid4().hex[:24]}'
        manifest, manifest_hash = self._baseline_promotion_simulation_evidence_package_manifest(
            package_id=package_id,
            attestation_export=attestation_export,
            review_audit_export=review_audit_export,
            simulation=simulation,
            export_policy=export_policy,
        )
        entries = self._baseline_promotion_simulation_export_registry_entries(release)
        previous = dict(entries[-1] or {}) if entries else {}
        sequence = (int(previous.get('sequence') or 0) + 1) if previous else 1
        registry_core = {
            'entry_id': f'sim-export-reg-{str(release.get("release_id") or "")[:8]}-{sequence:06d}',
            'sequence': sequence,
            'package_id': package_id,
            'simulation_id': str(simulation.get('simulation_id') or ''),
            'report_type': 'openmiura_baseline_promotion_simulation_evidence_package_v1',
            'payload_fingerprint': str((simulation.get('fingerprints') or {}).get('request_hash') or ''),
            'manifest_hash': manifest_hash,
            'scope': self._scope(tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=release.get('environment')),
            'appended_at': generated_at,
            'appended_by': str(actor or 'system'),
            'previous_entry_hash': str(previous.get('entry_hash') or ''),
            'immutable': True,
            'immutable_until': retention_until,
            'registry_mode': str(export_policy.get('registry_mode') or 'append_only_hash_chain'),
        }
        registry_entry = {
            **registry_core,
            'entry_core': dict(registry_core),
            'entry_hash': self._stable_digest(registry_core),
        }
        retention = {
            'immutable_retention_days': retention_days,
            'retain_until': retention_until,
            'max_packages': self._baseline_promotion_simulation_evidence_max_packages(simulation),
            'classification': self._baseline_promotion_simulation_evidence_classification(simulation=simulation, release=release),
            'legal_hold': bool(escrow_policy.get('object_lock_enabled')) and bool(escrow_policy.get('delete_protection', False)),
        }
        package_payload = {
            'report_type': 'openmiura_baseline_promotion_simulation_evidence_package_v1',
            'generated_at': generated_at,
            'generated_by': str(actor or 'system'),
            'package_id': package_id,
            'simulation': {
                'simulation_id': str(simulation.get('simulation_id') or ''),
                'simulation_status': str(simulation.get('simulation_status') or ''),
                'simulated_at': simulation.get('simulated_at'),
                'simulated_by': simulation.get('simulated_by'),
                'reviewed_at': simulation.get('reviewed_at'),
                'catalog_id': str(simulation.get('catalog_id') or ''),
                'catalog_name': str(simulation.get('catalog_name') or ''),
                'candidate_catalog_version': str(simulation.get('candidate_catalog_version') or ''),
            },
            'source_promotion': {
                'promotion_id': str(release.get('release_id') or ''),
                'name': str(release.get('name') or ''),
                'version': str(release.get('version') or ''),
                'status': str(release.get('status') or ''),
            },
            'scope': self._scope(tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=release.get('environment')),
            'manifest': {**manifest, 'manifest_hash': manifest_hash},
            'artifacts': {
                'simulation_attestation_export': attestation_export,
                'simulation_review_audit_export': review_audit_export,
            },
            'observed_versions': dict(simulation.get('observed_versions') or {}),
            'fingerprints': dict(simulation.get('fingerprints') or {}),
            'simulation_policy': dict(simulation.get('simulation_policy') or {}),
            'review_state': dict(simulation.get('review_state') or {}),
            'created_promotions': [dict(item) for item in list(simulation.get('created_promotions') or [])],
            'registry_entry_preview': dict(registry_entry),
            'retention': retention,
            'escrow_policy': dict(escrow_policy),
        }
        integrity = self._portfolio_evidence_integrity(
            report_type=package_payload['report_type'],
            scope=dict(package_payload.get('scope') or {}),
            payload=package_payload,
            actor=actor,
            export_policy=export_policy,
            signing_policy=self._baseline_promotion_simulation_effective_signing_policy(simulation=simulation),
        )
        artifact = self._build_baseline_promotion_simulation_evidence_artifact_archive(
            package_payload=package_payload,
            integrity=integrity,
            export_policy=export_policy,
        )
        escrow = self._archive_baseline_promotion_simulation_evidence_artifact_external(
            artifact=artifact,
            package_payload=package_payload,
            integrity=integrity,
            retention=retention,
            actor=actor,
            escrow_policy=escrow_policy,
            signing_policy=self._baseline_promotion_simulation_effective_signing_policy(simulation=simulation),
            generated_at=generated_at,
        )
        if bool(escrow_policy.get('enabled')) and bool(escrow_policy.get('require_archive_on_export', True)) and not bool(escrow.get('archived')):
            if not bool(escrow_policy.get('allow_inline_fallback', True)):
                return {
                    'ok': False,
                    'error': 'baseline_promotion_simulation_evidence_escrow_failed',
                    'promotion_id': str(release.get('release_id') or ''),
                    'package_id': package_id,
                    'escrow': escrow,
                }
        artifact_record = dict(artifact)
        if not bool(export_policy.get('embed_artifact_content', True)):
            artifact_record.pop('content_b64', None)
        if escrow.get('archived'):
            artifact_record['escrow'] = self._redact_large_blob(dict(escrow or {}))
        package_record = {
            'package_id': package_id,
            'created_at': float(package_payload.get('generated_at') or time.time()),
            'created_by': str(actor or 'system'),
            'report_type': package_payload['report_type'],
            'simulation_id': str(simulation.get('simulation_id') or ''),
            'manifest_hash': manifest_hash,
            'payload_hash': integrity.get('payload_hash'),
            'signature': integrity.get('signature'),
            'signature_scheme': integrity.get('signature_scheme'),
            'signer_key_id': integrity.get('signer_key_id'),
            'signer_provider': integrity.get('signer_provider'),
            'retention': dict(package_payload.get('retention') or {}),
            'source_simulation': {
                'simulation_id': str(simulation.get('simulation_id') or ''),
            },
            'source_promotion': dict(package_payload.get('source_promotion') or {}),
            'artifact': artifact_record,
            'escrow': self._redact_large_blob(dict(escrow or {})) if escrow else {},
            'registry_entry': {
                'entry_id': str(registry_entry.get('entry_id') or ''),
                'sequence': int(registry_entry.get('sequence') or 0),
                'entry_hash': str(registry_entry.get('entry_hash') or ''),
                'previous_entry_hash': str(registry_entry.get('previous_entry_hash') or ''),
                'immutable': True,
                'immutable_until': registry_entry.get('immutable_until'),
            },
            'attestation': {
                'report_id': str(((attestation_export.get('report') or {}).get('report_id') or '')),
                'report_type': str(((attestation_export.get('report') or {}).get('report_type') or '')),
            },
            'review_audit': {
                'report_id': str(((review_audit_export.get('report') or {}).get('report_id') or '')),
                'report_type': str(((review_audit_export.get('report') or {}).get('report_type') or '')),
            },
        }
        return {
            'ok': True,
            'package_id': package_id,
            'package': package_payload,
            'integrity': integrity,
            'artifact': artifact,
            'escrow': self._redact_large_blob(dict(escrow or {})) if escrow else {},
            'registry_entry': registry_entry,
            'package_record': package_record,
            'scope': dict(package_payload.get('scope') or {}),
        }

    def _find_baseline_promotion_simulation_evidence_package(
        self,
        release: dict[str, Any] | None,
        *,
        package_id: str | None = None,
        include_content: bool = False,
    ) -> dict[str, Any] | None:
        packages = self._list_baseline_promotion_simulation_evidence_packages(release, include_content=include_content)
        target_package_id = str(package_id or '').strip()
        if not packages:
            return None
        if not target_package_id:
            return dict(packages[0])
        for item in packages:
            if str(item.get('package_id') or '') == target_package_id:
                return dict(item)
        return None

    def _decode_baseline_promotion_simulation_evidence_artifact_input(
        self,
        *,
        artifact: dict[str, Any] | None = None,
        artifact_b64: str | None = None,
    ) -> dict[str, Any]:
        source = dict(artifact or {})
        encoded = artifact_b64 if artifact_b64 is not None else source.get('content_b64')
        if not encoded:
            return {'ok': False, 'error': 'baseline_promotion_simulation_evidence_artifact_missing'}
        try:
            archive_bytes = base64.b64decode(str(encoded).encode('ascii'))
        except Exception:
            return {'ok': False, 'error': 'baseline_promotion_simulation_evidence_artifact_decode_failed'}
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
            return {'ok': False, 'error': 'baseline_promotion_simulation_evidence_artifact_invalid_archive'}
        return {
            'ok': True,
            'archive_bytes': archive_bytes,
            'archive_sha256': archive_sha256,
            'artifact': source,
            'entries': parsed_entries,
        }

    def _verify_baseline_promotion_simulation_evidence_artifact_payload(
        self,
        *,
        artifact: dict[str, Any] | None = None,
        artifact_b64: str | None = None,
        registry_entries: list[dict[str, Any]] | None = None,
        stored_package: dict[str, Any] | None = None,
        now_ts: float | None = None,
    ) -> dict[str, Any]:
        resolved_artifact = dict(artifact or {})
        stored = dict(stored_package or {})
        escrow_meta = dict(resolved_artifact.get('escrow') or stored.get('escrow') or {})
        artifact_source = 'inline'
        if artifact_b64 is None and not str(resolved_artifact.get('content_b64') or '').strip() and escrow_meta:
            loaded_artifact = self._load_baseline_promotion_simulation_evidence_artifact_from_escrow(escrow=escrow_meta)
            if loaded_artifact is not None:
                resolved_artifact = loaded_artifact
                artifact_source = 'escrow'
        decoded = self._decode_baseline_promotion_simulation_evidence_artifact_input(artifact=resolved_artifact, artifact_b64=artifact_b64)
        if not decoded.get('ok'):
            return decoded
        artifact_meta = dict(decoded.get('artifact') or {})
        entries = dict(decoded.get('entries') or {})
        package_payload = dict(entries.get('package.json') or {})
        integrity = dict(entries.get('integrity.json') or {})
        manifest_entry = dict(entries.get('manifest.json') or {})
        attestation_export = dict(entries.get('simulation_attestation_export.json') or {})
        review_audit_export = dict(entries.get('simulation_review_audit_export.json') or {})
        registry_entry = dict(entries.get('registry_entry.json') or (package_payload.get('registry_entry_preview') or {}))
        if not package_payload or not integrity or not manifest_entry or not attestation_export or not review_audit_export or not registry_entry:
            return {'ok': False, 'error': 'baseline_promotion_simulation_evidence_artifact_incomplete'}

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
        review_audit_verify = self._verify_portfolio_export_integrity(
            report_type=str(((review_audit_export.get('report') or {}).get('report_type')) or ''),
            scope=dict(review_audit_export.get('scope') or {}),
            payload=dict(review_audit_export.get('report') or {}),
            integrity=dict(review_audit_export.get('integrity') or {}),
        )
        package_verify = self._verify_portfolio_export_integrity(
            report_type=str(package_payload.get('report_type') or ''),
            scope=dict(package_payload.get('scope') or {}),
            payload=dict(package_payload),
            integrity=integrity,
        )

        manifest_artifacts = {str(item.get('artifact_id') or ''): dict(item) for item in list(manifest_payload.get('artifacts') or [])}
        attestation_report = dict(attestation_export.get('report') or {})
        review_audit_report = dict(review_audit_export.get('report') or {})
        manifest_links_valid = (
            manifest_artifacts.get(str(attestation_report.get('report_id') or ''), {}).get('payload_hash') == ((attestation_export.get('integrity') or {}).get('payload_hash'))
            and manifest_artifacts.get(str(review_audit_report.get('report_id') or ''), {}).get('payload_hash') == ((review_audit_export.get('integrity') or {}).get('payload_hash'))
        )

        registry_entry_preview = dict(package_payload.get('registry_entry_preview') or {})
        registry_payload_match_valid = not registry_entry_preview or registry_entry_preview == registry_entry
        entry_core = dict(registry_entry.get('entry_core') or {})
        if not entry_core:
            entry_core = {
                key: value
                for key, value in registry_entry.items()
                if key not in {'entry_hash', 'entry_core'}
            }
        expected_entry_hash = self._stable_digest(entry_core) if entry_core else ''
        registry_entry_hash_valid = bool(expected_entry_hash) and str(registry_entry.get('entry_hash') or '') == expected_entry_hash

        sorted_registry_entries = [dict(item) for item in list(registry_entries or [])]
        sorted_registry_entries.sort(key=lambda item: (int(item.get('sequence') or 0), float(item.get('appended_at') or 0.0), str(item.get('entry_id') or '')))
        registry_chain_valid = True
        previous_hash = ''
        for pos, item in enumerate(sorted_registry_entries, start=1):
            item_core = dict(item.get('entry_core') or {
                key: value for key, value in item.items() if key not in {'entry_hash', 'entry_core'}
            })
            if int(item.get('sequence') or 0) != pos:
                registry_chain_valid = False
            if str(item.get('previous_entry_hash') or '') != previous_hash:
                registry_chain_valid = False
            if self._stable_digest(item_core) != str(item.get('entry_hash') or ''):
                registry_chain_valid = False
            previous_hash = str(item.get('entry_hash') or '')

        matching_registry_entry = None
        for item in sorted_registry_entries:
            if str(item.get('entry_id') or '') == str(registry_entry.get('entry_id') or ''):
                matching_registry_entry = dict(item)
                break
        registry_membership_valid = matching_registry_entry is not None if sorted_registry_entries else True
        registry_match_valid = True
        if matching_registry_entry is not None:
            compare_keys = ['entry_id', 'sequence', 'package_id', 'simulation_id', 'manifest_hash', 'entry_hash', 'previous_entry_hash', 'immutable', 'registry_mode']
            registry_match_valid = all(matching_registry_entry.get(key) == registry_entry.get(key) for key in compare_keys)
            registry_match_valid = registry_match_valid and dict(matching_registry_entry.get('entry_core') or entry_core) == dict(entry_core)

        stored_package_match_valid = True
        if stored:
            stored_package_match_valid = str(stored.get('package_id') or '') == str(package_payload.get('package_id') or '')
            stored_package_match_valid = stored_package_match_valid and str(stored.get('manifest_hash') or '') == str(manifest_hash or '')
            stored_artifact = dict(stored.get('artifact') or {})
            stored_sha = str(stored_artifact.get('sha256') or '').strip()
            if stored_sha:
                stored_package_match_valid = stored_package_match_valid and stored_sha == str(decoded.get('archive_sha256') or '')
        escrow_verify = self._verify_baseline_promotion_simulation_escrow_receipt(escrow=escrow_meta, now_ts=now_ts) if escrow_meta else {'required': False, 'valid': True, 'status': 'not_archived'}

        checks = {
            'archive_hash_valid': archive_hash_valid,
            'archive_size_valid': archive_size_valid,
            'manifest_hash_valid': manifest_hash_valid,
            'manifest_links_valid': manifest_links_valid,
            'attestation_export_valid': bool(attestation_verify.get('valid')),
            'review_audit_export_valid': bool(review_audit_verify.get('valid')),
            'package_integrity_valid': bool(package_verify.get('valid')),
            'escrow_receipt_valid': bool(escrow_verify.get('valid', True)),
            'registry_payload_match_valid': registry_payload_match_valid,
            'registry_entry_hash_valid': registry_entry_hash_valid,
            'registry_membership_valid': registry_membership_valid,
            'registry_match_valid': registry_match_valid,
            'registry_chain_valid': registry_chain_valid,
            'stored_package_match_valid': stored_package_match_valid,
        }
        failures = [name for name, value in checks.items() if not value]
        status = 'verified' if not failures else 'failed'
        immutable_until = registry_entry.get('immutable_until')
        try:
            immutable_active = bool(registry_entry.get('immutable')) and immutable_until is not None and float(immutable_until) >= float(now_ts if now_ts is not None else time.time())
        except Exception:
            immutable_active = bool(registry_entry.get('immutable'))
        return {
            'ok': True,
            'package_id': str(package_payload.get('package_id') or '').strip() or None,
            'simulation_id': str(((package_payload.get('simulation') or {}).get('simulation_id')) or '').strip() or None,
            'artifact': {
                **{k: v for k, v in artifact_meta.items() if k != 'content_b64'},
                'sha256': decoded.get('archive_sha256'),
                'size_bytes': len(decoded.get('archive_bytes') or b''),
                'source': artifact_source,
            },
            'package': package_payload,
            'integrity': integrity,
            'verification': {
                'status': status,
                'valid': status == 'verified',
                'restorable': status == 'verified',
                'checks': checks,
                'failures': failures,
                'manifest': {
                    'manifest_hash': manifest_hash,
                    'expected_manifest_hash': expected_manifest_hash,
                    'valid': manifest_hash_valid,
                    'artifact_links_valid': manifest_links_valid,
                },
                'attestation_export': attestation_verify,
                'review_audit_export': review_audit_verify,
                'package_integrity': package_verify,
                'escrow': escrow_verify,
                'registry': {
                    'entry_id': str(registry_entry.get('entry_id') or ''),
                    'sequence': int(registry_entry.get('sequence') or 0),
                    'entry_hash': str(registry_entry.get('entry_hash') or ''),
                    'previous_entry_hash': str(registry_entry.get('previous_entry_hash') or ''),
                    'manifest_hash': str(registry_entry.get('manifest_hash') or ''),
                    'immutable': bool(registry_entry.get('immutable')),
                    'immutable_until': immutable_until,
                    'immutable_active': immutable_active,
                    'membership_valid': registry_membership_valid,
                    'match_valid': registry_match_valid,
                    'chain_valid': registry_chain_valid,
                },
                'stored_package_match_valid': stored_package_match_valid,
            },
            'restored_entries': {
                'simulation_attestation_export': attestation_export,
                'simulation_review_audit_export': review_audit_export,
                'registry_entry': registry_entry,
            },
            'registry_entry': registry_entry,
            'escrow': self._redact_large_blob(escrow_meta) if escrow_meta else {},
            'stored_package': {k: v for k, v in stored.items() if k != 'artifact'} if stored else {},
        }

    def _restore_baseline_promotion_simulation_from_evidence_verification(
        self,
        *,
        verification: dict[str, Any],
    ) -> dict[str, Any]:
        attestation_export = dict(((verification.get('restored_entries') or {}).get('simulation_attestation_export')) or {})
        review_audit_export = dict(((verification.get('restored_entries') or {}).get('simulation_review_audit_export')) or {})
        package_payload = dict(verification.get('package') or {})
        attestation_report = dict(attestation_export.get('report') or {})
        review_audit_report = dict(review_audit_export.get('report') or {})
        simulation_meta = dict(attestation_report.get('simulation') or {})
        review_state = dict(attestation_report.get('review_state') or {})
        review_state.setdefault('overall_status', str((review_audit_report.get('review_sequence') or {}).get('overall_status') or review_state.get('overall_status') or ''))
        review_state.setdefault('items', [dict(item) for item in list((review_audit_report.get('ordered_reviews') or []))])
        restored = {
            'simulation_id': str(simulation_meta.get('simulation_id') or ((package_payload.get('simulation') or {}).get('simulation_id')) or ''),
            'mode': str(simulation_meta.get('mode') or ''),
            'simulation_status': str(simulation_meta.get('simulation_status') or ''),
            'simulated_at': simulation_meta.get('simulated_at'),
            'simulated_by': simulation_meta.get('simulated_by'),
            'reviewed_at': simulation_meta.get('reviewed_at') or ((review_audit_report.get('simulation') or {}).get('reviewed_at')),
            'stale': bool(simulation_meta.get('stale')),
            'expired': bool(simulation_meta.get('expired')),
            'blocked': bool(simulation_meta.get('blocked')),
            'why_blocked': str(simulation_meta.get('why_blocked') or ''),
            'catalog_id': str(simulation_meta.get('catalog_id') or ((package_payload.get('simulation') or {}).get('catalog_id')) or ''),
            'catalog_name': str(simulation_meta.get('catalog_name') or ''),
            'candidate_catalog_version': str(simulation_meta.get('candidate_catalog_version') or ((package_payload.get('simulation') or {}).get('candidate_catalog_version')) or ''),
            'scope': dict(attestation_report.get('scope') or package_payload.get('scope') or {}),
            'simulation_source': dict(attestation_report.get('source') or {}),
            'request': dict(attestation_report.get('request') or {}),
            'candidate_baselines': dict(((attestation_report.get('request') or {}).get('candidate_baselines') or {})),
            'summary': dict(attestation_report.get('summary') or {}),
            'validation': dict(attestation_report.get('validation') or {}),
            'approval_preview': dict(attestation_report.get('approval_preview') or {}),
            'simulation_policy': dict(attestation_report.get('simulation_policy') or {}),
            'review': dict(attestation_report.get('review') or review_audit_report.get('review_summary') or {}),
            'review_state': review_state,
            'observed_context': dict(attestation_report.get('observed_context') or {}),
            'observed_versions': dict(attestation_report.get('observed_versions') or {}),
            'source_observed_versions': dict(attestation_report.get('observed_versions') or {}),
            'fingerprints': dict(attestation_report.get('fingerprints') or {}),
            'source_fingerprints': dict(attestation_report.get('fingerprints') or {}),
            'diff': dict(attestation_report.get('diff') or {}),
            'explainability': dict(attestation_report.get('explainability') or {}),
            'created_promotions': [dict(item) for item in list(attestation_report.get('created_promotions') or package_payload.get('created_promotions') or [])],
            'timeline': [
                dict(item)
                for item in list(((attestation_report.get('timeline') or {}).get('items') if isinstance(attestation_report.get('timeline'), dict) else attestation_report.get('timeline')) or [])
            ],
            'export_state': {
                'attestation_count': 1,
                'review_audit_count': 1,
                'evidence_package_count': 1,
                'latest_attestation': {
                    'report_id': str(attestation_report.get('report_id') or ''),
                    'report_type': str(attestation_report.get('report_type') or ''),
                    'generated_at': attestation_report.get('generated_at'),
                    'generated_by': attestation_report.get('generated_by'),
                    'integrity': dict(attestation_export.get('integrity') or {}),
                },
                'latest_review_audit': {
                    'report_id': str(review_audit_report.get('report_id') or ''),
                    'report_type': str(review_audit_report.get('report_type') or ''),
                    'generated_at': review_audit_report.get('generated_at'),
                    'generated_by': review_audit_report.get('generated_by'),
                    'integrity': dict(review_audit_export.get('integrity') or {}),
                },
                'latest_evidence_package': {
                    'package_id': str(package_payload.get('package_id') or ''),
                    'report_type': str(package_payload.get('report_type') or ''),
                    'generated_at': package_payload.get('generated_at'),
                    'generated_by': package_payload.get('generated_by'),
                    'integrity': dict(verification.get('integrity') or {}),
                    'artifact': {
                        'artifact_type': str(((verification.get('artifact') or {}).get('artifact_type')) or ''),
                        'sha256': str(((verification.get('artifact') or {}).get('sha256')) or ''),
                        'size_bytes': int(((verification.get('artifact') or {}).get('size_bytes')) or 0),
                        'filename': str(((verification.get('artifact') or {}).get('filename')) or ''),
                        'source': str(((verification.get('artifact') or {}).get('source')) or ''),
                    },
                    'registry_entry': {
                        'entry_id': str(((verification.get('registry_entry') or {}).get('entry_id')) or ''),
                        'sequence': int(((verification.get('registry_entry') or {}).get('sequence')) or 0),
                        'entry_hash': str(((verification.get('registry_entry') or {}).get('entry_hash')) or ''),
                        'previous_entry_hash': str(((verification.get('registry_entry') or {}).get('previous_entry_hash')) or ''),
                        'immutable': bool(((verification.get('registry_entry') or {}).get('immutable'))),
                    },
                    'escrow': dict(verification.get('escrow') or {}),
                },
                'registry_summary': {
                    'count': int(((verification.get('verification') or {}).get('registry') or {}).get('sequence') or 0),
                    'latest_entry_id': str(((verification.get('registry_entry') or {}).get('entry_id')) or ''),
                    'latest_package_id': str(package_payload.get('package_id') or ''),
                    'latest_entry_hash': str(((verification.get('registry_entry') or {}).get('entry_hash')) or ''),
                    'chain_ok': bool((((verification.get('verification') or {}).get('registry') or {}).get('chain_valid'))),
                },
            },
            'restore_context': {
                'restored_from_package_id': str(package_payload.get('package_id') or ''),
                'artifact_sha256': str(((verification.get('artifact') or {}).get('sha256')) or ''),
                'registry_entry_id': str(((verification.get('registry_entry') or {}).get('entry_id')) or ''),
                'registry_sequence': int(((verification.get('registry_entry') or {}).get('sequence')) or 0),
            },
        }
        return restored

