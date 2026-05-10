"""scheduler._portfolio_b_mixin

Sub-mixin extracted from OpenClawRecoverySchedulerService; original imports replicated.
"""
from __future__ import annotations

import base64
import hashlib
import json
import importlib
import os
import socket
import sqlite3
import subprocess
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519
from cryptography.hazmat.primitives.serialization import load_pem_private_key, load_pem_public_key

from openmiura.application.jobs import JobService
from openmiura.application.runtime_adapters.external.service import OpenClawAdapterService
from openmiura.application.runtime_adapters.external.baseline_rollout_management import OpenClawBaselineRolloutManagementMixin
from openmiura.application.runtime_adapters.external.baseline_rollout_support import OpenClawBaselineRolloutSupportMixin
from openmiura.application.runtime_adapters.external.baseline_rollout_state import OpenClawBaselineRolloutStateMixin
from openmiura.application.runtime_adapters.external.baseline_rollout_jobs import OpenClawBaselineRolloutJobsMixin
from openmiura.application.runtime_adapters.external.baseline_rollout_gates import OpenClawBaselineRolloutGatesMixin
from openmiura.application.runtime_adapters.external.alert_governance_bundle_management import OpenClawAlertGovernanceBundleManagementMixin
from openmiura.application.runtime_adapters.external.alert_governance_bundle_jobs import OpenClawAlertGovernanceBundleJobsMixin
from openmiura.application.runtime_adapters.external.alert_governance_bundle_gates import OpenClawAlertGovernanceBundleGatesMixin
from openmiura.application.runtime_adapters.external.policy_normalization import OpenClawPolicyNormalizationMixin
from openmiura.application.runtime_adapters.external.evidence_builders import OpenClawEvidenceBuildersMixin
from openmiura.application.runtime_adapters.external.runtime_rollout_summaries import OpenClawRuntimeRolloutSummariesMixin
from openmiura.application.runtime_adapters.external.runtime_alert_common import OpenClawRuntimeAlertCommonMixin
from openmiura.application.runtime_adapters.external.runtime_alert_execution import OpenClawRuntimeAlertExecutionMixin
from openmiura.application.runtime_adapters.external.runtime_alert_notifications import OpenClawRuntimeAlertNotificationsMixin
from openmiura.application.runtime_adapters.external.runtime_alert_escalations import OpenClawRuntimeAlertEscalationsMixin
from openmiura.application.runtime_adapters.external.temporal_windows import OpenClawTemporalWindowsMixin
from openmiura.application.runtime_adapters.external.job_family_common import OpenClawJobFamilyCommonMixin
from openmiura.application.runtime_adapters.external.runtime_context import OpenClawRuntimeContextMixin
from openmiura.application.runtime_adapters.external.approval_common import OpenClawApprovalCommonMixin
from openmiura.application.runtime_adapters.external.governance_explainability import OpenClawGovernanceExplainabilityMixin
from openmiura.application.runtime_adapters.external.scheduler_primitives import (
    alert_delivery_job_definition,
    baseline_simulation_custody_job_definition,
    baseline_simulation_custody_job_id,
    baseline_wave_advance_job_definition,
    baseline_wave_job_id,
    decorate_idempotency_record,
    decorate_worker_lease,
    due_slot,
    governance_wave_advance_job_definition,
    governance_wave_job_id,
    holder_id,
    is_workflow_job,
    job_idempotency_key,
    job_lease_key,
    lease_type,
    recovery_job_definition,
    runtime_lease_key,
    scheduler_policy,
    scope as scheduler_scope,
    workspace_lease_keys,
    workspace_lease_prefix,
)



OpenClawRecoverySchedulerService: type | None = None  # late-bound by __init__.py


class _OpenClawRecoverySchedulerServicePortfolioBMixin:
    """Sub-mixin: portfolio b."""

    def _reconcile_portfolio_custody_anchor_state(
        self,
        gw,
        *,
        release: dict[str, Any],
        actor: str,
        custody_anchor_policy: dict[str, Any] | None = None,
        persist: bool = True,
    ) -> dict[str, Any]:
        policy = self._resolve_portfolio_custody_anchor_policy_for_environment(custody_anchor_policy, environment=release.get('environment'))
        local = self._list_portfolio_custody_anchor_receipts(release)
        external = self._load_external_portfolio_custody_anchor_receipts(release=release, custody_anchor_policy=policy)
        local_by_seq = {int(item.get('sequence') or 0): dict(item) for item in local}
        external_by_seq = {int(item.get('sequence') or 0): dict(item) for item in external}
        imported: list[dict[str, Any]] = []
        conflicts: list[dict[str, Any]] = []
        for seq, ext in external_by_seq.items():
            loc = local_by_seq.get(seq)
            if loc is None:
                imported.append(dict(ext))
                continue
            if self._custody_anchor_receipt_hash(loc) != self._custody_anchor_receipt_hash(ext):
                conflicts.append({'sequence': seq, 'local_anchor_id': loc.get('anchor_id'), 'external_anchor_id': ext.get('anchor_id')})
        local_verify = self._verify_portfolio_custody_anchor_receipts(local, expected_portfolio_id=str(release.get('release_id') or '') if local else None) if local else {'valid': True, 'count': 0, 'head_hash': None}
        external_verify = self._verify_portfolio_custody_anchor_receipts(external, expected_portfolio_id=str(release.get('release_id') or '') if external else None) if external else {'valid': True, 'count': 0, 'head_hash': None}
        quorum = self._portfolio_custody_quorum_view(external or local, custody_anchor_policy=policy)
        head_match = (local_verify.get('head_hash') == external_verify.get('head_hash')) if local and external else True
        if persist:
            status = 'conflict' if conflicts else ('reconciled' if imported else 'aligned')
            if not conflicts and bool(policy.get('require_quorum_for_reconciliation')) and not bool(quorum.get('authority_satisfied')):
                status = 'quorum_pending'
            replacement = list(external) if imported and not conflicts and bool(external_verify.get('valid', True)) else list(local)
            release = self._replace_portfolio_custody_anchor_receipts(
                gw,
                release=release,
                receipts=replacement,
                custody_anchor_policy=policy,
                reconciliation={
                    'reconciled_at': time.time(),
                    'reconciled_by': str(actor or 'system'),
                    'provider': policy.get('provider'),
                    'imported_count': len(imported),
                    'conflict_count': len(conflicts),
                    'external_count': len(external),
                    'local_count_before': len(local),
                    'head_match': head_match,
                    'external_valid': bool(external_verify.get('valid', True)),
                    'local_valid': bool(local_verify.get('valid', True)),
                    'status': status,
                    'quorum': quorum,
                    'authority_satisfied': bool(quorum.get('authority_satisfied')),
                },
            )
        refreshed = gw.audit.get_release_bundle(str(release.get('release_id') or ''), tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=release.get('environment')) or release
        reconciliation = dict((((refreshed.get('metadata') or {}).get('portfolio') or {}).get('current_custody_reconciliation') or {}) or {})
        return {
            'ok': True,
            'portfolio_id': str(release.get('release_id') or ''),
            'provider': policy.get('provider'),
            'immutable_backend': str(policy.get('provider') or '') == 'sqlite-immutable-ledger',
            'imported_count': len(imported),
            'conflict_count': len(conflicts),
            'conflicts': conflicts,
            'local_count': len(local),
            'external_count': len(external),
            'head_match': head_match,
            'local_valid': bool(local_verify.get('valid', True)),
            'external_valid': bool(external_verify.get('valid', True)),
            'status': str(reconciliation.get('status') or ('conflict' if conflicts else ('reconciled' if imported else 'aligned'))),
            'reconciled': not conflicts and bool(external_verify.get('valid', True)) and (not bool(policy.get('require_quorum_for_reconciliation')) or bool(quorum.get('authority_satisfied'))),
            'release': refreshed,
            'reconciliation': reconciliation,
            'quorum': quorum,
        }

    def _list_portfolio_custody_anchor_receipts(self, release: dict[str, Any] | None) -> list[dict[str, Any]]:
        metadata = dict((release or {}).get('metadata') or {})
        portfolio = dict(metadata.get('portfolio') or {})
        items = [dict(item) for item in list(portfolio.get('custody_anchor_receipts') or [])]
        items.sort(key=lambda item: (int(item.get('sequence') or 0), float(item.get('anchored_at') or 0.0), str(item.get('anchor_id') or '')))
        return items

    def _verify_portfolio_custody_anchor_receipt(
        self,
        *,
        receipt: dict[str, Any] | None,
        expected_chain_head_hash: str | None = None,
        expected_portfolio_id: str | None = None,
    ) -> dict[str, Any]:
        resolved = dict(receipt or {})
        canonical = {
            'receipt_type': 'openmiura_portfolio_custody_anchor_receipt_v1',
            'anchor_id': resolved.get('anchor_id'),
            'portfolio_id': resolved.get('portfolio_id'),
            'package_id': resolved.get('package_id'),
            'scope': dict(resolved.get('scope') or {}),
            'provider': resolved.get('provider'),
            'sequence': int(resolved.get('sequence') or 0),
            'previous_anchor_hash': resolved.get('previous_anchor_hash') or '',
            'anchored_at': float(resolved.get('anchored_at') or 0.0),
            'chain_head_hash': resolved.get('chain_head_hash'),
            'chain_entry_count': int(resolved.get('chain_entry_count') or 0),
            'chain_payload_hash': resolved.get('chain_payload_hash'),
            'artifact_sha256': resolved.get('artifact_sha256'),
            'manifest_hash': resolved.get('manifest_hash'),
            'ledger_namespace': resolved.get('ledger_namespace'),
            'archive_path': resolved.get('archive_path'),
            'archive_uri': resolved.get('archive_uri'),
            'control_plane_id': resolved.get('control_plane_id'),
            'anchor_role': resolved.get('anchor_role'),
            'authority_mode': resolved.get('authority_mode'),
            'leader_control_plane_id': resolved.get('leader_control_plane_id'),
            'quorum_size': int(resolved.get('quorum_size') or 1),
            'quorum_group_key': resolved.get('quorum_group_key'),
        }
        integrity_verify = self._verify_portfolio_export_integrity(
            report_type='openmiura_portfolio_custody_anchor_receipt_v1',
            scope=dict(resolved.get('scope') or {}),
            payload=canonical,
            integrity=dict(resolved.get('integrity') or {}),
        )
        head_matches = expected_chain_head_hash is None or str(resolved.get('chain_head_hash') or '') == str(expected_chain_head_hash or '')
        portfolio_matches = expected_portfolio_id is None or str(resolved.get('portfolio_id') or '') == str(expected_portfolio_id or '')
        provider = str(resolved.get('provider') or '').strip()
        external_exists = True
        external_matches = True
        archive_path = str(resolved.get('archive_path') or '').strip()
        if provider == 'sqlite-immutable-ledger':
            sqlite_path = Path(archive_path) if archive_path else None
            external_exists = bool(sqlite_path and sqlite_path.exists())
            if external_exists and sqlite_path is not None:
                conn = self._open_portfolio_custody_anchor_sqlite(sqlite_path)
                try:
                    row = conn.execute('SELECT receipt_json FROM custody_anchor_receipts WHERE anchor_id = ?', (str(resolved.get('anchor_id') or ''),)).fetchone()
                finally:
                    conn.close()
                if row is None:
                    external_matches = False
                else:
                    try:
                        persisted = json.loads(str(row[0]))
                    except Exception:
                        persisted = {}
                    external_matches = self._custody_anchor_receipt_hash(persisted) == self._custody_anchor_receipt_hash(resolved)
        elif archive_path:
            path = Path(archive_path)
            external_exists = path.exists()
            if external_exists:
                try:
                    persisted = json.loads(path.read_text(encoding='utf-8'))
                    external_matches = self._custody_anchor_receipt_hash(persisted) == self._custody_anchor_receipt_hash(resolved)
                except Exception:
                    external_matches = False
        return {
            'valid': bool(integrity_verify.get('valid')) and head_matches and portfolio_matches and external_exists and external_matches,
            'integrity': integrity_verify,
            'head_matches': head_matches,
            'portfolio_matches': portfolio_matches,
            'external_exists': external_exists,
            'external_matches': external_matches,
            'sequence': canonical['sequence'],
            'anchor_id': canonical['anchor_id'],
            'chain_head_hash': canonical['chain_head_hash'],
            'previous_anchor_hash': canonical['previous_anchor_hash'],
            'control_plane_id': canonical['control_plane_id'],
            'anchor_role': canonical['anchor_role'],
            'quorum_group_key': canonical['quorum_group_key'],
        }

    def _verify_portfolio_custody_anchor_receipts(
        self,
        receipts: list[dict[str, Any]] | None,
        *,
        expected_chain_head_hash: str | None = None,
        expected_portfolio_id: str | None = None,
    ) -> dict[str, Any]:
        items = [dict(item) for item in list(receipts or [])]
        previous_anchor_hash = ''
        invalid_anchor_ids: list[str] = []
        signature_valid_count = 0
        chain_valid = True
        latest_verify: dict[str, Any] | None = None
        for index, item in enumerate(items):
            verify = self._verify_portfolio_custody_anchor_receipt(
                receipt=item,
                expected_chain_head_hash=expected_chain_head_hash if index == len(items) - 1 else None,
                expected_portfolio_id=expected_portfolio_id,
            )
            if bool((verify.get('integrity') or {}).get('valid')):
                signature_valid_count += 1
            expected_previous = previous_anchor_hash
            current_anchor_hash = self._custody_anchor_receipt_hash(item)
            if str(item.get('previous_anchor_hash') or '') != expected_previous or not bool(verify.get('valid')):
                chain_valid = False
                invalid_anchor_ids.append(str(item.get('anchor_id') or ''))
            previous_anchor_hash = current_anchor_hash
            latest_verify = verify
        return {
            'count': len(items),
            'head_hash': previous_anchor_hash or None,
            'chain_valid': chain_valid,
            'signature_valid_count': signature_valid_count,
            'invalid_anchor_ids': [item for item in invalid_anchor_ids if item],
            'latest': latest_verify or {},
            'valid': chain_valid and signature_valid_count == len(items),
        }

    def _portfolio_custody_quorum_view(
        self,
        receipts: list[dict[str, Any]] | None,
        *,
        custody_anchor_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        policy = self._normalize_portfolio_custody_anchor_policy(dict(custody_anchor_policy or {}))
        items = [dict(item) for item in list(receipts or [])]
        latest = items[-1] if items else {}
        quorum_group_key = str(latest.get('quorum_group_key') or '')
        if not quorum_group_key and latest:
            quorum_group_key = self._stable_digest({
                'package_id': latest.get('package_id'),
                'chain_head_hash': latest.get('chain_head_hash'),
                'manifest_hash': latest.get('manifest_hash'),
            })
        group_items = []
        for item in items:
            item_group_key = str(item.get('quorum_group_key') or '') or self._stable_digest({
                'package_id': item.get('package_id'),
                'chain_head_hash': item.get('chain_head_hash'),
                'manifest_hash': item.get('manifest_hash'),
            })
            if quorum_group_key and item_group_key == quorum_group_key:
                group_items.append(dict(item))
        distinct_control_planes = sorted({str(item.get('control_plane_id') or '').strip() for item in group_items if str(item.get('control_plane_id') or '').strip()})
        leader_id = str(policy.get('leader_control_plane_id') or '').strip()
        leader_present = bool(leader_id) and leader_id in distinct_control_planes
        authority_mode = str(policy.get('append_authority') or 'any').strip().lower() or 'any'
        authority_present = any(str(item.get('anchor_role') or '').strip().lower() == 'authority' for item in group_items)
        witness_control_planes = sorted({str(item.get('control_plane_id') or '').strip() for item in group_items if str(item.get('anchor_role') or '').strip().lower() == 'witness' and str(item.get('control_plane_id') or '').strip()})
        required_witness_count = max(0, int(policy.get('required_witness_count') or 0))
        required_witness_control_planes = [str(item).strip() for item in list(policy.get('required_witness_control_planes') or []) if str(item).strip()]
        required_witnesses_met = len(witness_control_planes) >= required_witness_count
        required_witness_control_planes_met = all(item in witness_control_planes for item in required_witness_control_planes) if required_witness_control_planes else True
        quorum_size = max(1, int(policy.get('quorum_size') or 1))
        quorum_met = len(distinct_control_planes) >= quorum_size
        quorum_required = bool(policy.get('quorum_enabled')) and quorum_size > 1
        base_authority_satisfied = False
        if authority_mode == 'leader':
            base_authority_satisfied = leader_present and authority_present and (not quorum_required or quorum_met)
        elif authority_mode == 'quorum':
            base_authority_satisfied = quorum_met
        else:
            base_authority_satisfied = (authority_present or bool(group_items)) and (not quorum_required or quorum_met)
        authority_satisfied = base_authority_satisfied and required_witnesses_met and required_witness_control_planes_met
        status = 'not_configured'
        if items:
            if quorum_required and not quorum_met:
                status = 'quorum_pending'
            elif authority_mode == 'leader' and not authority_satisfied:
                status = 'leader_pending'
            elif authority_mode == 'quorum' and not quorum_met:
                status = 'quorum_pending'
            elif (required_witness_count > 0 or required_witness_control_planes) and not authority_satisfied:
                status = 'witness_pending'
            else:
                status = 'satisfied'
        return {
            'enabled': bool(policy.get('quorum_enabled')) or authority_mode in {'leader', 'quorum'},
            'status': status,
            'authority_mode': authority_mode,
            'leader_control_plane_id': leader_id or None,
            'leader_present': leader_present,
            'authority_present': authority_present,
            'quorum_size': quorum_size,
            'quorum_required': quorum_required,
            'distinct_control_plane_count': len(distinct_control_planes),
            'distinct_control_planes': distinct_control_planes,
            'quorum_met': quorum_met,
            'authority_satisfied': authority_satisfied,
            'required_witness_count': required_witness_count,
            'witness_count': len(witness_control_planes),
            'witness_control_planes': witness_control_planes,
            'required_witness_control_planes': required_witness_control_planes,
            'required_witnesses_met': required_witnesses_met,
            'required_witness_control_planes_met': required_witness_control_planes_met,
            'quorum_group_key': quorum_group_key or None,
            'group_receipt_count': len(group_items),
        }

    def _store_portfolio_custody_anchor_receipt(
        self,
        gw,
        *,
        release: dict[str, Any],
        receipt: dict[str, Any],
        custody_anchor_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        policy = self._normalize_portfolio_custody_anchor_policy(dict(custody_anchor_policy or {}))
        metadata = dict(release.get('metadata') or {})
        portfolio = dict(metadata.get('portfolio') or {})
        current = self._list_portfolio_custody_anchor_receipts(release)
        current.append(dict(receipt or {}))
        current = current[-max(1, int(policy.get('max_receipts') or 250)):]
        portfolio['custody_anchor_receipts'] = current
        portfolio['current_custody_anchor'] = current[-1] if current else None
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

    def _anchor_portfolio_chain_of_custody_external(
        self,
        *,
        release: dict[str, Any],
        chain_of_custody: dict[str, Any] | None,
        package_id: str,
        manifest_hash: str,
        artifact_sha256: str | None,
        actor: str,
        custody_anchor_policy: dict[str, Any] | None = None,
        signing_policy: dict[str, Any] | None = None,
        generated_at: float | None = None,
        anchor_role: str | None = None,
        control_plane_id: str | None = None,
    ) -> dict[str, Any]:
        policy = self._resolve_portfolio_custody_anchor_policy_for_environment(custody_anchor_policy, environment=release.get('environment'))
        if not bool(policy.get('enabled')) or not bool(policy.get('anchor_on_export', True)):
            return {'enabled': bool(policy.get('enabled')), 'anchored': False, 'provider': policy.get('provider'), 'reason': 'custody_anchor_disabled'}
        provider = str(policy.get('provider') or '')
        if provider not in {'filesystem-ledger', 'sqlite-immutable-ledger'}:
            return {'enabled': True, 'anchored': False, 'provider': policy.get('provider'), 'reason': 'unsupported_custody_anchor_provider'}
        scope = self._scope(tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=release.get('environment'))
        portfolio_id = str(release.get('release_id') or '').strip() or 'portfolio'
        ts = float(generated_at) if generated_at is not None else time.time()
        chain_snapshot = dict(chain_of_custody or {})
        anchor_id = str(uuid.uuid4())
        authority_mode = str(policy.get('append_authority') or 'any').strip().lower() or 'any'
        effective_control_plane_id = str(control_plane_id or policy.get('control_plane_id') or 'control-plane').strip() or 'control-plane'
        leader_control_plane_id = str(policy.get('leader_control_plane_id') or '').strip() or None
        resolved_anchor_role = str(anchor_role or ('authority' if authority_mode != 'quorum' else 'authority')).strip().lower() or 'authority'
        if resolved_anchor_role not in {'authority', 'witness'}:
            resolved_anchor_role = 'authority'
        if authority_mode == 'leader' and leader_control_plane_id and effective_control_plane_id != leader_control_plane_id and resolved_anchor_role == 'authority':
            return {
                'enabled': True,
                'anchored': False,
                'provider': provider,
                'reason': 'append_authority_denied',
                'authority_mode': authority_mode,
                'leader_control_plane_id': leader_control_plane_id,
                'control_plane_id': effective_control_plane_id,
            }
        if resolved_anchor_role == 'witness' and not bool(policy.get('allow_witness_attestations', True)):
            return {
                'enabled': True,
                'anchored': False,
                'provider': provider,
                'reason': 'witness_attestations_disabled',
                'control_plane_id': effective_control_plane_id,
            }
        existing_external = self._load_external_portfolio_custody_anchor_receipts(release=release, custody_anchor_policy=policy)
        sequence = (int(existing_external[-1].get('sequence') or 0) if existing_external else 0) + 1
        previous_anchor_hash = self._custody_anchor_receipt_hash(existing_external[-1]) if existing_external else ''
        quorum_group_key = self._stable_digest({
            'portfolio_id': portfolio_id,
            'package_id': str(package_id or '').strip() or None,
            'chain_head_hash': ((chain_snapshot.get('summary') or {}).get('head_hash')),
            'manifest_hash': str(manifest_hash or '').strip(),
        })
        if provider == 'filesystem-ledger':
            root_dir = Path(str(policy.get('root_dir') or 'data/openclaw_custody_anchor'))
            path_parts = [
                str(policy.get('ledger_namespace') or 'portfolio-custody'),
                str(scope.get('tenant_id') or 'global'),
                str(scope.get('workspace_id') or 'default'),
                str(scope.get('environment') or 'default'),
                portfolio_id,
                'anchors',
                f'{sequence:06d}-{anchor_id}.json',
            ]
            anchor_path = root_dir.joinpath(*path_parts)
            anchor_uri = f'file://{anchor_path.as_posix()}'
        else:
            anchor_path = Path(str(policy.get('sqlite_path') or 'data/openclaw_custody_anchor/custody_anchor_ledger.sqlite3')).expanduser().resolve()
            anchor_uri = f'sqlite://{anchor_path.as_posix()}#portfolio={portfolio_id}&sequence={sequence}'
        canonical = {
            'receipt_type': 'openmiura_portfolio_custody_anchor_receipt_v1',
            'anchor_id': anchor_id,
            'portfolio_id': portfolio_id,
            'package_id': str(package_id or '').strip() or None,
            'scope': scope,
            'provider': provider,
            'sequence': sequence,
            'previous_anchor_hash': previous_anchor_hash,
            'anchored_at': ts,
            'chain_head_hash': ((chain_snapshot.get('summary') or {}).get('head_hash')),
            'chain_entry_count': int(((chain_snapshot.get('summary') or {}).get('count')) or len(list(chain_snapshot.get('entries') or []))),
            'chain_payload_hash': self._stable_digest(chain_snapshot),
            'artifact_sha256': str(artifact_sha256 or '').strip() or None,
            'manifest_hash': str(manifest_hash or '').strip(),
            'ledger_namespace': str(policy.get('ledger_namespace') or 'portfolio-custody'),
            'archive_path': anchor_path.as_posix(),
            'archive_uri': anchor_uri,
            'control_plane_id': effective_control_plane_id,
            'anchor_role': resolved_anchor_role,
            'authority_mode': authority_mode,
            'leader_control_plane_id': leader_control_plane_id,
            'quorum_size': int(policy.get('quorum_size') or 1),
            'quorum_group_key': quorum_group_key,
        }
        integrity = self._portfolio_evidence_integrity(
            report_type='openmiura_portfolio_custody_anchor_receipt_v1',
            scope=scope,
            payload=canonical,
            actor=actor,
            export_policy={'require_signature': True, 'signer_key_id': str(policy.get('signer_key_id') or 'openmiura-custody-anchor')},
            signing_policy=signing_policy,
        )
        persisted = {**canonical, 'integrity': integrity}
        if provider == 'filesystem-ledger':
            self._write_file_if_absent(anchor_path, self._canonical_json_bytes(persisted))
        else:
            conn = self._open_portfolio_custody_anchor_sqlite(anchor_path)
            try:
                receipt_json = self._canonical_json_bytes(persisted).decode('utf-8')
                receipt_hash = self._custody_anchor_receipt_hash(persisted)
                conn.execute('BEGIN IMMEDIATE')
                latest = conn.execute('SELECT sequence, receipt_hash FROM custody_anchor_receipts WHERE portfolio_id = ? ORDER BY sequence DESC LIMIT 1', (portfolio_id,)).fetchone()
                if latest is not None and int(latest[0]) >= sequence:
                    sequence = int(latest[0]) + 1
                    persisted['sequence'] = sequence
                    persisted['previous_anchor_hash'] = str(latest[1] or '')
                    persisted['integrity'] = self._portfolio_evidence_integrity(
                        report_type='openmiura_portfolio_custody_anchor_receipt_v1',
                        scope=scope,
                        payload={k: v for k, v in persisted.items() if k != 'integrity'},
                        actor=actor,
                        export_policy={'require_signature': True, 'signer_key_id': str(policy.get('signer_key_id') or 'openmiura-custody-anchor')},
                        signing_policy=signing_policy,
                    )
                    receipt_json = self._canonical_json_bytes(persisted).decode('utf-8')
                    receipt_hash = self._custody_anchor_receipt_hash(persisted)
                conn.execute('INSERT INTO custody_anchor_receipts (portfolio_id, sequence, anchor_id, receipt_json, receipt_hash, created_at) VALUES (?, ?, ?, ?, ?, ?)', (portfolio_id, int(persisted.get('sequence') or 0), str(persisted.get('anchor_id') or ''), receipt_json, receipt_hash, ts))
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
        return {
            'enabled': True,
            'anchored': True,
            'provider': policy.get('provider'),
            'anchor_id': persisted.get('anchor_id'),
            'sequence': int(persisted.get('sequence') or sequence),
            'chain_head_hash': persisted.get('chain_head_hash'),
            'manifest_hash': persisted.get('manifest_hash'),
            'artifact_sha256': persisted.get('artifact_sha256'),
            'archive_path': persisted.get('archive_path'),
            'archive_uri': persisted.get('archive_uri'),
            'receipt': persisted,
            'immutable_backend': provider == 'sqlite-immutable-ledger',
            'anchor_role': resolved_anchor_role,
            'authority_mode': authority_mode,
        }

    def _portfolio_retention_snapshot(
        self,
        *,
        created_at: float,
        retention_policy: dict[str, Any] | None = None,
        now_ts: float | None = None,
    ) -> dict[str, Any]:
        normalized = self._normalize_portfolio_retention_policy(dict(retention_policy or {}))
        resolved_now = float(now_ts) if now_ts is not None else time.time()
        retain_until = None
        if bool(normalized.get('enabled', True)) and not bool(normalized.get('legal_hold', False)):
            retain_until = float(created_at) + (max(0, int(normalized.get('retention_days') or 0)) * 86400.0)
        state = 'active'
        if bool(normalized.get('legal_hold', False)):
            state = 'legal_hold'
        elif retain_until is not None and retain_until <= resolved_now:
            state = 'expired'
        return {
            'enabled': bool(normalized.get('enabled', True)),
            'classification': str(normalized.get('classification') or 'internal-sensitive'),
            'operational_tier': str(normalized.get('operational_tier') or '').strip() or None,
            'retention_days': int(normalized.get('retention_days') or 0),
            'max_packages': int(normalized.get('max_packages') or 25),
            'legal_hold': bool(normalized.get('legal_hold', False)),
            'prune_on_export': bool(normalized.get('prune_on_export', True)),
            'purge_expired': bool(normalized.get('purge_expired', True)),
            'retain_until': retain_until,
            'state': state,
            'expired': state == 'expired',
        }

    def _portfolio_notarization_receipt(
        self,
        *,
        package_id: str,
        manifest_hash: str,
        actor: str,
        scope: dict[str, Any],
        notarization_policy: dict[str, Any] | None = None,
        signing_policy: dict[str, Any] | None = None,
        generated_at: float | None = None,
    ) -> dict[str, Any]:
        normalized = self._normalize_portfolio_notarization_policy(dict(notarization_policy or {}))
        if not bool(normalized.get('enabled', False)):
            return {
                'enabled': False,
                'notarized': False,
                'provider': normalized.get('provider'),
                'reason': 'notarization_disabled',
            }
        submitted_at = float(generated_at) if generated_at is not None else time.time()
        receipt_id = str(uuid.uuid4())
        canonical = {
            'package_id': str(package_id or '').strip(),
            'manifest_hash': str(manifest_hash or '').strip(),
            'provider': normalized.get('provider'),
            'scope': dict(scope or {}),
            'receipt_id': receipt_id,
            'submitted_at': submitted_at,
        }
        verification_hash = self._stable_digest(canonical)
        crypto = self._sign_portfolio_payload_crypto_v2(
            report_type='openmiura_portfolio_notarization_receipt_v1',
            scope=dict(scope or {}),
            payload=canonical,
            signer_key_id=str(normalized.get('notary_key_id') or 'openmiura-notary').strip() or 'openmiura-notary',
            signing_policy=signing_policy,
        )
        return {
            'enabled': True,
            'notarized': True,
            'mode': str(normalized.get('mode') or 'simulated_external'),
            'provider': str(normalized.get('provider') or 'simulated-external'),
            'receipt_id': receipt_id,
            'manifest_hash': str(manifest_hash or '').strip(),
            'submitted_at': submitted_at,
            'notarized_at': submitted_at,
            'submitted_by': str(actor or 'system').strip() or 'system',
            'verification_hash': verification_hash,
            'notary_key_id': str(normalized.get('notary_key_id') or 'openmiura-notary'),
            'reference': f'{str(normalized.get("provider") or "simulated-external").strip() or "simulated-external"}://{str(normalized.get("reference_namespace") or "openmiura-evidence").strip() or "openmiura-evidence"}/{receipt_id}',
            'expires_at': submitted_at + (max(1, int(normalized.get('receipt_ttl_days') or 365)) * 86400.0),
            'signature': crypto.get('signature'),
            'signature_scheme': crypto.get('signature_scheme'),
            'signature_input': crypto.get('signature_input'),
            'public_key': crypto.get('public_key'),
            'crypto_v2': True,
            'signer_provider': crypto.get('signer_provider'),
            'key_origin': crypto.get('key_origin'),
        }

    def _verify_portfolio_escrow_receipt(
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
        lock_status_payload: dict[str, Any] = {}
        if archive_path.startswith('s3://'):
            parsed = self._parse_s3_uri(archive_path)
            if parsed is None:
                return {'required': True, 'valid': False, 'status': 'archive_uri_invalid'}
            bucket, key = parsed
            try:
                archive_bytes = self._read_s3_object_bytes(bucket=bucket, key=key, escrow_policy=receipt)
                client = self._aws_s3_client_for_policy(receipt)
                head = client.head_object(Bucket=bucket, Key=key)
                if bool(receipt.get('object_lock_enabled')):
                    try:
                        retention_payload = client.get_object_retention(Bucket=bucket, Key=key)
                    except Exception:
                        retention_payload = {}
                    try:
                        legal_hold_payload = client.get_object_legal_hold(Bucket=bucket, Key=key)
                    except Exception:
                        legal_hold_payload = {}
                    lock_status_payload = {
                        'head': dict(head or {}),
                        'retention': dict(retention_payload or {}),
                        'legal_hold': dict(legal_hold_payload or {}),
                    }
            except Exception:
                return {'required': True, 'valid': False, 'status': 'archive_missing'}
        elif archive_path.startswith('azblob://'):
            parsed = self._parse_azblob_uri(archive_path)
            if parsed is None:
                return {'required': True, 'valid': False, 'status': 'archive_uri_invalid'}
            container, blob_name = parsed
            try:
                service = self._azure_blob_service_client_for_policy(receipt)
                blob_client = service.get_blob_client(container=container, blob=blob_name)
                props = blob_client.get_blob_properties()
                download = blob_client.download_blob()
                archive_bytes = download.readall() if hasattr(download, 'readall') else download.read()
                lock_status_payload = {'properties': props}
            except Exception:
                return {'required': True, 'valid': False, 'status': 'archive_missing'}
        elif archive_path.startswith('gs://'):
            parsed = self._parse_gs_uri(archive_path)
            if parsed is None:
                return {'required': True, 'valid': False, 'status': 'archive_uri_invalid'}
            bucket_name, key = parsed
            try:
                client = self._gcs_client_for_policy(receipt)
                bucket = client.bucket(bucket_name)
                blob = bucket.blob(key)
                blob.reload()
                archive_bytes = blob.download_as_bytes()
                lock_status_payload = {'blob': blob, 'bucket': bucket}
            except Exception:
                return {'required': True, 'valid': False, 'status': 'archive_missing'}
        else:
            path = Path(archive_path)
            if not path.exists() or not path.is_file():
                return {'required': True, 'valid': False, 'status': 'archive_missing'}
            archive_bytes = path.read_bytes()
        archive_sha256 = hashlib.sha256(archive_bytes).hexdigest()
        canonical = {
            'receipt_type': 'openmiura_portfolio_evidence_escrow_receipt_v1',
            'receipt_id': receipt.get('receipt_id'),
            'provider': receipt.get('provider'),
            'mode': receipt.get('mode'),
            'archived': True,
            'archived_at': receipt.get('archived_at'),
            'archived_by': receipt.get('archived_by'),
            'package_id': receipt.get('package_id'),
            'portfolio_id': receipt.get('portfolio_id'),
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
        if str(receipt.get('provider') or '') in {'aws-s3-object-lock', 's3-object-lock'} and any(receipt.get(field) not in (None, '') for field in ('bucket', 'key', 'aws_region', 'aws_profile', 'aws_endpoint_url')):
            canonical.update({
                'bucket': receipt.get('bucket'),
                'key': receipt.get('key'),
                'aws_region': receipt.get('aws_region'),
                'aws_profile': receipt.get('aws_profile'),
                'aws_endpoint_url': receipt.get('aws_endpoint_url'),
            })
        if any(receipt.get(field) not in (None, '') for field in ('container', 'blob_name', 'azure_blob_account_url')):
            canonical.update({
                'container': receipt.get('container'),
                'blob_name': receipt.get('blob_name'),
                'azure_blob_account_url': receipt.get('azure_blob_account_url'),
            })
        if any(receipt.get(field) not in (None, '') for field in ('bucket', 'gcs_key', 'gcs_project')) and str(receipt.get('provider') or '') == 'gcs-retention-lock':
            canonical.update({
                'bucket': receipt.get('bucket'),
                'gcs_key': receipt.get('gcs_key'),
                'gcs_project': receipt.get('gcs_project'),
            })
        crypto_verify = self._verify_portfolio_crypto_signature(
            report_type='openmiura_portfolio_evidence_escrow_receipt_v1',
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
        object_lock_valid = True
        if bool(receipt.get('object_lock_enabled')):
            lock_path = str(receipt.get('lock_path') or '').strip()
            object_lock_valid = False
            if archive_path.startswith('s3://'):
                retention_state = (((lock_status_payload.get('retention') or {}).get('Retention')) or {})
                legal_hold_state = (((lock_status_payload.get('legal_hold') or {}).get('LegalHold')) or {})
                head_payload = dict(lock_status_payload.get('head') or {})
                metadata = {str(k).lower(): str(v) for k, v in dict(head_payload.get('Metadata') or {}).items()}
                object_lock_valid = (
                    metadata.get('artifact_sha256') == archive_sha256
                    and (not bool(receipt.get('immutable_until')) or retention_state.get('RetainUntilDate') is not None)
                    and (not bool(receipt.get('legal_hold')) or str(legal_hold_state.get('Status') or '').upper() == 'ON')
                )
            elif archive_path.startswith('azblob://'):
                props = lock_status_payload.get('properties')
                metadata = {str(k).lower(): str(v) for k, v in dict(getattr(props, 'metadata', None) or {}).items()}
                immutability = getattr(props, 'immutability_policy', None)
                legal_hold = getattr(props, 'has_legal_hold', False)
                object_lock_valid = metadata.get('artifact_sha256') == archive_sha256 and (immutability is not None or not bool(receipt.get('immutable_until')))
                if bool(receipt.get('legal_hold')):
                    object_lock_valid = object_lock_valid and bool(legal_hold)
            elif archive_path.startswith('gs://'):
                blob = lock_status_payload.get('blob')
                metadata = {str(k).lower(): str(v) for k, v in dict(getattr(blob, 'metadata', None) or {}).items()}
                object_lock_valid = metadata.get('artifact_sha256') == archive_sha256 and bool(getattr(blob, 'temporary_hold', False) or getattr(blob, 'event_based_hold', False) or getattr(blob, 'retention_expiration_time', None) is not None)
            elif lock_path:
                lock_file = Path(lock_path)
                if lock_file.exists() and lock_file.is_file():
                    try:
                        lock_payload = json.loads(lock_file.read_text(encoding='utf-8'))
                    except Exception:
                        lock_payload = {}
                    object_lock_valid = (
                        str(lock_payload.get('artifact_sha256') or '') == archive_sha256
                        and str(lock_payload.get('archive_path') or '') == archive_path
                        and str(lock_payload.get('retention_mode') or '') == str(receipt.get('retention_mode') or '')
                    )
        valid = archive_hash_valid and bool(crypto_verify.get('valid')) and object_lock_valid
        return {
            'required': True,
            'valid': valid,
            'status': 'verified' if valid else 'mismatch',
            'archive_hash_valid': archive_hash_valid,
            'signature_valid': bool(crypto_verify.get('valid')),
            'immutable_active': immutable_active,
            'object_lock_valid': object_lock_valid,
            'archive_path': archive_path,
            'archive_sha256': archive_sha256,
            'public_key_fingerprint': crypto_verify.get('public_key_fingerprint'),
            'signer_provider': crypto_verify.get('signer_provider'),
            'archive_backend': 's3_object_lock' if archive_path.startswith('s3://') else ('azure_blob_immutable' if archive_path.startswith('azblob://') else ('gcs_retention_lock' if archive_path.startswith('gs://') else 'filesystem')),
        }

    def _verify_portfolio_export_integrity(
        self,
        *,
        report_type: str,
        scope: dict[str, Any],
        payload: dict[str, Any],
        integrity: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        resolved = dict(integrity or {})
        if bool(resolved.get('crypto_v2')) or str(resolved.get('signature_scheme') or '').strip().lower() == 'ed25519':
            crypto_verify = self._verify_portfolio_crypto_signature(
                report_type=report_type,
                scope=dict(scope or {}),
                payload=dict(payload or {}),
                integrity=resolved,
            )
            crypto_verify['expected_signature'] = None
            return crypto_verify
        expected_payload_hash = self._stable_digest(payload)
        signed = bool(resolved.get('signed'))
        signer_key_id = str(resolved.get('signer_key_id') or '').strip()
        expected_signature = None
        if signed:
            expected_signature = self._stable_digest({
                'report_type': str(report_type or '').strip(),
                'scope': dict(scope or {}),
                'payload': dict(payload or {}),
                'signer_key_id': signer_key_id,
            })
        payload_hash_valid = str(resolved.get('payload_hash') or '') == expected_payload_hash
        signature_valid = (not signed and not resolved.get('signature')) or str(resolved.get('signature') or '') == str(expected_signature or '')
        return {
            'report_type': str(report_type or '').strip(),
            'signed': signed,
            'signer_key_id': signer_key_id or None,
            'payload_hash_valid': payload_hash_valid,
            'signature_valid': signature_valid,
            'expected_payload_hash': expected_payload_hash,
            'expected_signature': expected_signature,
            'valid': payload_hash_valid and signature_valid,
        }

    def _verify_portfolio_notarization_receipt(
        self,
        *,
        notarization: dict[str, Any] | None,
        scope: dict[str, Any],
        package_id: str,
        manifest_hash: str,
        notarization_policy: dict[str, Any] | None = None,
        now_ts: float | None = None,
    ) -> dict[str, Any]:
        policy = self._normalize_portfolio_notarization_policy(dict(notarization_policy or {}))
        receipt = dict(notarization or {})
        resolved_now = float(now_ts) if now_ts is not None else time.time()
        if not bool(policy.get('enabled')):
            return {
                'required': False,
                'valid': True,
                'status': 'not_required',
                'notarized': bool(receipt.get('notarized')),
                'provider': receipt.get('provider'),
            }
        if not bool(receipt.get('notarized')):
            valid = bool(policy.get('allow_unsigned_fallback', False))
            return {
                'required': bool(policy.get('require_on_export', True)),
                'valid': valid,
                'status': 'unsigned_fallback' if valid else 'missing_required_receipt',
                'notarized': False,
                'provider': receipt.get('provider') or policy.get('provider'),
            }
        receipt_id = str(receipt.get('receipt_id') or '').strip()
        submitted_at = float(receipt.get('submitted_at') or receipt.get('notarized_at') or resolved_now)
        canonical = {
            'package_id': str(package_id or '').strip(),
            'manifest_hash': str(manifest_hash or '').strip(),
            'provider': receipt.get('provider'),
            'scope': dict(scope or {}),
            'receipt_id': receipt_id,
            'submitted_at': submitted_at,
        }
        expected_hash = self._stable_digest(canonical)
        verification_hash_valid = str(receipt.get('verification_hash') or '') == expected_hash
        manifest_hash_valid = str(receipt.get('manifest_hash') or '') == str(manifest_hash or '')
        expired = receipt.get('expires_at') is not None and float(receipt.get('expires_at') or 0.0) < resolved_now
        crypto_verify = self._verify_portfolio_crypto_signature(
            report_type='openmiura_portfolio_notarization_receipt_v1',
            scope=dict(scope or {}),
            payload=canonical,
            integrity={
                'signed': True,
                'signature': receipt.get('signature'),
                'signature_scheme': receipt.get('signature_scheme'),
                'signature_input': receipt.get('signature_input'),
                'public_key': receipt.get('public_key'),
                'signer_key_id': receipt.get('notary_key_id'),
                'payload_hash': expected_hash,
                'crypto_v2': True,
            },
        )
        valid = verification_hash_valid and manifest_hash_valid and not expired and bool(crypto_verify.get('valid'))
        return {
            'required': bool(policy.get('require_on_export', True)),
            'valid': valid,
            'status': 'verified' if valid else ('expired' if expired else 'mismatch'),
            'notarized': True,
            'provider': receipt.get('provider') or policy.get('provider'),
            'verification_hash_valid': verification_hash_valid,
            'manifest_hash_valid': manifest_hash_valid,
            'expired': expired,
            'expected_verification_hash': expected_hash,
            'signature_valid': bool(crypto_verify.get('valid')),
            'signature_scheme': crypto_verify.get('scheme'),
            'public_key_fingerprint': crypto_verify.get('public_key_fingerprint'),
        }

    def _store_portfolio_restore_session(
        self,
        gw,
        *,
        release: dict[str, Any],
        session_record: dict[str, Any],
        restore_history_limit: int = 20,
    ) -> dict[str, Any]:
        metadata = dict(release.get('metadata') or {})
        portfolio = dict(metadata.get('portfolio') or {})
        history = [dict(item) for item in list(portfolio.get('restore_sessions') or [])]
        history.append(dict(session_record))
        portfolio['restore_sessions'] = history[-max(1, int(restore_history_limit or 20)) :]
        portfolio['current_restore_session'] = dict(session_record)
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

    def _find_portfolio_attestation(
        self,
        release: dict[str, Any],
        *,
        attestation_id: str | None = None,
    ) -> dict[str, Any] | None:
        attestations = self._list_portfolio_attestations(release)
        if attestation_id is None:
            metadata = dict(release.get('metadata') or {})
            portfolio = dict(metadata.get('portfolio') or {})
            current = dict(portfolio.get('current_attestation') or {})
            return current or (attestations[0] if attestations else None)
        needle = str(attestation_id or '').strip()
        for item in attestations:
            if str(item.get('attestation_id') or '').strip() == needle:
                return dict(item)
        return None

    def _build_portfolio_replay_timeline(
        self,
        gw,
        *,
        release: dict[str, Any],
        detail: dict[str, Any],
        attestation: dict[str, Any] | None = None,
        limit: int = 250,
    ) -> dict[str, Any]:
        portfolio = dict((detail.get('portfolio') or {}))
        bundle_ids = [str(item).strip() for item in list(portfolio.get('bundle_ids') or []) if str(item).strip()]
        timeline: list[dict[str, Any]] = []

        def _append(ts: float | None, kind: str, label: str, **extra: Any) -> None:
            if ts is None:
                return
            try:
                ts_value = float(ts)
            except Exception:
                return
            timeline.append({'ts': ts_value, 'kind': kind, 'label': label, **extra})

        _append(release.get('created_at'), 'portfolio', 'portfolio_created', status=release.get('status'), created_by=release.get('created_by'))
        _append(release.get('submitted_at'), 'portfolio', 'portfolio_submitted', status='candidate')
        _append(release.get('approved_at'), 'portfolio', 'portfolio_approved', status='approved')
        _append(release.get('rejected_at'), 'portfolio', 'portfolio_rejected', status='rejected')

        for item in list(((detail.get('approvals') or {}).get('items') or [])):
            payload = dict(item.get('payload') or {})
            _append(item.get('created_at'), 'approval', 'approval_requested', approval_id=item.get('approval_id'), layer_id=payload.get('layer_id'), role=item.get('requested_role'), status=item.get('status'))
            if item.get('decided_at') is not None:
                _append(item.get('decided_at'), 'approval', 'approval_decided', approval_id=item.get('approval_id'), layer_id=payload.get('layer_id'), role=item.get('requested_role'), status=item.get('status'), actor=item.get('decided_by'))

        if attestation:
            _append(attestation.get('created_at'), 'attestation', 'execution_attested', attestation_id=attestation.get('attestation_id'), schedule_hash=attestation.get('schedule_hash'))

        for event in list(((detail.get('calendar') or {}).get('items') or [])):
            _append(event.get('planned_at'), 'calendar', 'portfolio_event_planned', event_id=event.get('event_id'), bundle_id=event.get('bundle_id'), wave_no=event.get('wave_no'), status=event.get('status'))
            executed_at = event.get('last_run_at')
            if executed_at is None and str(event.get('status') or '') in {'completed', 'error', 'drift_blocked'}:
                executed_at = event.get('planned_at')
            if executed_at is not None:
                _append(executed_at, 'calendar', 'portfolio_event_executed', event_id=event.get('event_id'), bundle_id=event.get('bundle_id'), wave_no=event.get('wave_no'), status=event.get('status'), result=dict(event.get('result') or {}))

        for job in list(((detail.get('jobs') or {}).get('items') or [])):
            if job.get('created_at') is not None:
                definition = dict(job.get('workflow_definition') or {})
                _append(job.get('created_at'), 'job', 'release_train_job_created', job_id=job.get('job_id'), event_id=definition.get('event_id'), bundle_id=definition.get('bundle_id'), status='enabled' if job.get('enabled') else 'disabled')
            if job.get('last_run_at') is not None:
                definition = dict(job.get('workflow_definition') or {})
                _append(job.get('last_run_at'), 'job', 'release_train_job_ran', job_id=job.get('job_id'), event_id=definition.get('event_id'), bundle_id=definition.get('bundle_id'), status='error' if job.get('last_error') else 'ok', last_error=job.get('last_error'))

        metadata = dict(release.get('metadata') or {})
        portfolio_metadata = dict(metadata.get('portfolio') or {})
        for drift in list(portfolio_metadata.get('drift_detections') or []):
            _append(drift.get('executed_at'), 'drift', 'portfolio_drift_evaluated', overall_status=drift.get('overall_status'), count=((drift.get('summary') or {}).get('count')), blocking=((drift.get('summary') or {}).get('blocking_count')))

        export_policy = self._normalize_portfolio_export_policy(dict(((portfolio.get('train_policy') or {}).get('export_policy') or {})))
        if bool(export_policy.get('include_audit_events', True)):
            for item in self._collect_portfolio_audit_evidence(gw, release=release, bundle_ids=bundle_ids, limit=max(limit, int(export_policy.get('evidence_limit') or limit))):
                _append(item.get('ts'), 'audit_event', str(item.get('event') or 'audit_event'), event_id=item.get('id'), channel=item.get('channel'), direction=item.get('direction'), user_id=item.get('user_id'), payload=item.get('payload'))

        timeline.sort(key=lambda entry: (float(entry.get('ts') or 0.0), str(entry.get('kind') or ''), str(entry.get('label') or '')))
        trimmed = timeline[-max(1, int(limit)) :]
        status_counts: dict[str, int] = {}
        for item in trimmed:
            status = str(item.get('status') or item.get('overall_status') or '').strip()
            if status:
                status_counts[status] = status_counts.get(status, 0) + 1
        return {
            'items': trimmed,
            'summary': {
                'count': len(trimmed),
                'kind_counts': {kind: sum(1 for item in trimmed if str(item.get('kind') or '') == kind) for kind in sorted({str(item.get('kind') or '') for item in trimmed})},
                'status_counts': status_counts,
                'first_ts': trimmed[0].get('ts') if trimmed else None,
                'last_ts': trimmed[-1].get('ts') if trimmed else None,
            },
        }

    def _portfolio_execution_compare(
        self,
        *,
        detail: dict[str, Any],
        attestation: dict[str, Any] | None = None,
        drift: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        calendar_items = [dict(item) for item in list(((detail.get('calendar') or {}).get('items') or []))]
        attested_items = [dict(item) for item in list((attestation or {}).get('schedule_items') or [])]
        drift_by_event = {str(item.get('event_id') or ''): dict(item) for item in list((drift or {}).get('items') or [])}
        attested_by_event = {str(item.get('event_id') or ''): dict(item) for item in attested_items}
        compare_items: list[dict[str, Any]] = []
        for event in calendar_items:
            event_id = str(event.get('event_id') or '')
            att_item = attested_by_event.get(event_id, {})
            drift_item = drift_by_event.get(event_id, {})
            compare_items.append({
                'event_id': event_id,
                'bundle_id': str(event.get('bundle_id') or ''),
                'wave_no': int(event.get('wave_no') or 1),
                'attested_planned_at': att_item.get('attested_planned_at'),
                'planned_at': event.get('planned_at'),
                'last_run_at': event.get('last_run_at'),
                'status': str(event.get('status') or ''),
                'simulation_status': str(((event.get('validation') or {}).get('simulation_status')) or ''),
                'rollout_status': str(((event.get('result') or {}).get('rollout_status')) or ''),
                'drift_status': str(drift_item.get('drift_status') or 'aligned'),
                'blocking_drift_count': int(drift_item.get('blocking_count') or 0),
                'changed': bool(drift_item.get('drifts')),
                'result': dict(event.get('result') or {}),
            })
        return {
            'items': compare_items,
            'summary': {
                'count': len(compare_items),
                'completed_count': sum(1 for item in compare_items if str(item.get('status') or '') == 'completed'),
                'error_count': sum(1 for item in compare_items if str(item.get('status') or '') in {'error', 'drift_blocked'}),
                'drifted_count': sum(1 for item in compare_items if bool(item.get('changed'))),
                'blocking_drift_count': sum(int(item.get('blocking_drift_count') or 0) for item in compare_items),
            },
        }

    def _evaluate_portfolio_execution_drift(
        self,
        gw,
        *,
        release: dict[str, Any],
        actor: str,
        simulation: dict[str, Any] | None = None,
        persist_metadata: bool = False,
    ) -> dict[str, Any]:
        metadata = dict(release.get('metadata') or {})
        portfolio = dict(metadata.get('portfolio') or {})
        base_train_policy = self._normalize_portfolio_train_policy(dict(portfolio.get('train_policy') or {}))
        train_policy = self._resolve_portfolio_train_policy_for_environment(base_train_policy, environment=release.get('environment'))
        drift_policy = self._normalize_portfolio_drift_policy(dict(train_policy.get('drift_policy') or {}))
        attestations = self._list_portfolio_attestations(release)
        current_attestation = dict(portfolio.get('current_attestation') or (attestations[0] if attestations else {}))
        current_simulation = dict(simulation or {})
        if not current_simulation:
            current_simulation = self._simulate_portfolio_calendar(
                gw,
                release=release,
                actor=actor,
                dry_run=True,
                auto_reschedule=None,
                persist_metadata=False,
                persist_schedule=False,
            )
        drift_items: list[dict[str, Any]] = []
        drifts: list[dict[str, Any]] = []
        now_ts = time.time()
        if not current_attestation:
            blocking = bool(drift_policy.get('enabled')) and bool(drift_policy.get('block_on_missing_attestation', True))
            report = {
                'executed_at': now_ts,
                'executed_by': str(actor or 'system'),
                'policy': drift_policy,
                'overall_status': 'no_attestation',
                'block_execution': blocking,
                'attestation': None,
                'items': [],
                'drifts': [{
                    'code': 'missing_attestation',
                    'reason': 'portfolio approval has no execution attestation',
                    'blocking': blocking,
                }],
                'summary': {'count': 1, 'blocking_count': 1 if blocking else 0, 'drifted_event_count': 0, 'attested_count': 0, 'current_event_count': len(list(current_simulation.get('items') or []))},
                'current_schedule_hash': self._stable_digest(self._portfolio_attestation_schedule_items(current_simulation)),
            }
        else:
            attested_items = [dict(item) for item in list(current_attestation.get('schedule_items') or [])]
            current_items = self._portfolio_attestation_schedule_items(current_simulation)
            current_by_event = {str(item.get('event_id') or ''): dict(item) for item in current_items}
            tolerance_s = float(drift_policy.get('schedule_tolerance_s') or 0.0)
            for att_item in attested_items:
                event_id = str(att_item.get('event_id') or '')
                event_drifts: list[dict[str, Any]] = []
                current_item = current_by_event.get(event_id)
                if current_item is None:
                    blocking = bool(drift_policy.get('enabled')) and bool(drift_policy.get('block_on_schedule_change', True))
                    event_drifts.append({'code': 'event_missing', 'reason': 'attested event is missing from current calendar', 'blocking': blocking})
                else:
                    att_planned = att_item.get('attested_planned_at')
                    cur_planned = current_item.get('attested_planned_at')
                    if att_planned is None and cur_planned is not None or att_planned is not None and cur_planned is None or (att_planned is not None and cur_planned is not None and abs(float(att_planned) - float(cur_planned)) > tolerance_s):
                        blocking = bool(drift_policy.get('enabled')) and bool(drift_policy.get('block_on_schedule_change', True))
                        event_drifts.append({'code': 'schedule_changed', 'reason': 'current execution time differs from attested schedule', 'blocking': blocking, 'attested_planned_at': att_planned, 'current_planned_at': cur_planned})
                    if set(att_item.get('target_runtime_ids') or []) != set(current_item.get('target_runtime_ids') or []):
                        blocking = bool(drift_policy.get('enabled')) and bool(drift_policy.get('block_on_target_change', True))
                        event_drifts.append({'code': 'target_runtime_changed', 'reason': 'current runtime targets differ from attested execution plan', 'blocking': blocking, 'attested_target_runtime_ids': list(att_item.get('target_runtime_ids') or []), 'current_target_runtime_ids': list(current_item.get('target_runtime_ids') or [])})
                    att_status = str(att_item.get('simulation_status') or '')
                    cur_status = str(current_item.get('simulation_status') or '')
                    if att_status in {'ready', 'deferred', 'completed'} and cur_status == 'blocked':
                        blocking = bool(drift_policy.get('enabled')) and bool(drift_policy.get('block_on_status_downgrade', True))
                        event_drifts.append({'code': 'status_downgraded', 'reason': 'current simulation is blocked after an attested executable plan', 'blocking': blocking, 'attested_status': att_status, 'current_status': cur_status})
                if event_drifts:
                    drifts.extend([{'event_id': event_id, 'bundle_id': att_item.get('bundle_id'), **entry} for entry in event_drifts])
                drift_items.append({
                    'event_id': event_id,
                    'bundle_id': att_item.get('bundle_id'),
                    'attested': att_item,
                    'current': current_item,
                    'drift_status': 'drifted' if event_drifts else 'aligned',
                    'blocking_count': sum(1 for entry in event_drifts if bool(entry.get('blocking'))),
                    'drifts': event_drifts,
                })
            attested_event_ids = {str(item.get('event_id') or '') for item in attested_items}
            for current_item in current_items:
                event_id = str(current_item.get('event_id') or '')
                if event_id in attested_event_ids:
                    continue
                blocking = bool(drift_policy.get('enabled')) and bool(drift_policy.get('block_on_schedule_change', True))
                drift = {'event_id': event_id, 'bundle_id': current_item.get('bundle_id'), 'code': 'unexpected_event', 'reason': 'current calendar includes an event absent from the attested plan', 'blocking': blocking}
                drifts.append(drift)
                drift_items.append({
                    'event_id': event_id,
                    'bundle_id': current_item.get('bundle_id'),
                    'attested': None,
                    'current': current_item,
                    'drift_status': 'drifted',
                    'blocking_count': 1 if blocking else 0,
                    'drifts': [drift],
                })
            blocking_count = sum(1 for item in drifts if bool(item.get('blocking')) )
            overall_status = 'aligned' if not drifts else ('blocking_drift' if blocking_count > 0 else 'drift_detected')
            report = {
                'executed_at': now_ts,
                'executed_by': str(actor or 'system'),
                'policy': drift_policy,
                'overall_status': overall_status,
                'block_execution': blocking_count > 0,
                'attestation': {
                    'attestation_id': current_attestation.get('attestation_id'),
                    'created_at': current_attestation.get('created_at'),
                    'created_by': current_attestation.get('created_by'),
                    'schedule_hash': current_attestation.get('schedule_hash'),
                    'simulation_hash': current_attestation.get('simulation_hash'),
                },
                'items': drift_items,
                'drifts': drifts,
                'summary': {
                    'count': len(drifts),
                    'blocking_count': blocking_count,
                    'drifted_event_count': sum(1 for item in drift_items if str(item.get('drift_status') or '') == 'drifted'),
                    'attested_count': len(attested_items),
                    'current_event_count': len(current_items),
                },
                'current_schedule_hash': self._stable_digest(current_items),
            }
        if persist_metadata and bool(drift_policy.get('persist_detections', True)):
            metadata = dict(release.get('metadata') or {})
            portfolio = dict(metadata.get('portfolio') or {})
            history = [dict(item) for item in list(portfolio.get('drift_detections') or [])]
            history.append(report)
            portfolio['current_drift'] = report
            portfolio['drift_detections'] = history[-20:]
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
                    'event': 'openclaw_portfolio_drift_evaluated',
                    'portfolio_id': str(release.get('release_id') or ''),
                    'overall_status': report.get('overall_status'),
                    'blocking_count': ((report.get('summary') or {}).get('blocking_count')),
                    'drift_count': ((report.get('summary') or {}).get('count')),
                },
                tenant_id=release.get('tenant_id'),
                workspace_id=release.get('workspace_id'),
                environment=release.get('environment'),
            )
        return report

    def _create_portfolio_layer_approval_request(
        self,
        gw,
        *,
        release: dict[str, Any],
        layer: dict[str, Any],
        actor: str,
    ) -> dict[str, Any]:
        portfolio_id = str(release.get('release_id') or '')
        return self._ensure_step_approval_request(
            gw,
            workflow_id=self._portfolio_approval_workflow_id(portfolio_id),
            step_id=f'portfolio-layer:{str(layer.get("layer_id") or "")}',
            requested_role=str(layer.get('requested_role') or 'approver'),
            requested_by=str(actor or 'system'),
            payload={
                'portfolio_id': portfolio_id,
                'layer_id': str(layer.get('layer_id') or ''),
                'layer_label': str(layer.get('label') or layer.get('layer_id') or ''),
                'requested_role': str(layer.get('requested_role') or ''),
                'portfolio_name': str(release.get('name') or ''),
                'portfolio_version': str(release.get('version') or ''),
            },
            tenant_id=release.get('tenant_id'),
            workspace_id=release.get('workspace_id'),
            environment=release.get('environment'),
        )

    def _ensure_portfolio_multilayer_approvals(
        self,
        gw,
        *,
        release: dict[str, Any],
        actor: str,
        approval_policy: dict[str, Any],
        limit: int = 100,
    ) -> dict[str, Any]:
        portfolio_id = str(release.get('release_id') or '')
        approvals = self._list_portfolio_approvals(
            gw,
            portfolio_id=portfolio_id,
            limit=max(limit, len(list((approval_policy or {}).get('layers') or [])) * 3 + 5),
            tenant_id=release.get('tenant_id'),
            workspace_id=release.get('workspace_id'),
            environment=release.get('environment'),
        )
        state = self._portfolio_approval_state(portfolio_id=portfolio_id, approval_policy=approval_policy, approvals=approvals)
        mode = str((approval_policy or {}).get('mode') or 'sequential').strip().lower() or 'sequential'
        if not approval_policy.get('enabled'):
            return state
        if str(state.get('overall_status') or '') == 'rejected':
            return state
        created = False
        for layer in list(state.get('layers') or []):
            status = str(layer.get('status') or '')
            if status in {'approved', 'pending'}:
                if mode == 'sequential' and status == 'pending':
                    break
                continue
            if status in {'not_requested', 'optional'}:
                self._create_portfolio_layer_approval_request(gw, release=release, layer=layer, actor=actor)
                created = True
                if mode == 'sequential':
                    break
        if created:
            approvals = self._list_portfolio_approvals(
                gw,
                portfolio_id=portfolio_id,
                limit=max(limit, len(list((approval_policy or {}).get('layers') or [])) * 3 + 5),
                tenant_id=release.get('tenant_id'),
                workspace_id=release.get('workspace_id'),
                environment=release.get('environment'),
            )
            state = self._portfolio_approval_state(portfolio_id=portfolio_id, approval_policy=approval_policy, approvals=approvals)
        return state

