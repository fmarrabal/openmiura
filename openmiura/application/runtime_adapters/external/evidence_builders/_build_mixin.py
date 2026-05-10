"""evidence_builders._build_mixin"""
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


class _OpenClawEvidenceBuildersMixinBuildMixin:
    """Sub-mixin: build."""

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

