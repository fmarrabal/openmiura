"""evidence_builders._verify_mixin"""
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


class _OpenClawEvidenceBuildersMixinVerifyMixin:
    """Sub-mixin: verify."""

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

