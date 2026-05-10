"""scheduler._portfolio_d_mixin

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


class _OpenClawRecoverySchedulerServicePortfolioDMixin:
    """Sub-mixin: portfolio d."""

    def _enforce_portfolio_verify_on_read(self, gw, *, detail: dict[str, Any], read_kind: str = 'detail') -> dict[str, Any]:
        release = dict(detail.get('release') or {})
        train_policy = self._resolve_portfolio_train_policy_for_environment(dict((((detail.get('portfolio') or {}).get('train_policy')) or {})), environment=release.get('environment'))
        gate_policy = dict(train_policy.get('verification_gate_policy') or {})
        read_key = str(read_kind or 'detail').strip().lower() or 'detail'
        critical_read_paths = [str(item or '').strip().lower() for item in list(gate_policy.get('critical_read_paths') or []) if str(item or '').strip()]
        if not bool(gate_policy.get('require_verify_on_read', False)):
            return {'ok': True, 'enforced': False}
        if critical_read_paths and '*' not in critical_read_paths and read_key not in critical_read_paths:
            return {'ok': True, 'enforced': False, 'reason': 'verify_on_read_not_required_for_path', 'read_kind': read_key}
        records = self._list_portfolio_evidence_packages(release, include_content=True)
        if bool(gate_policy.get('verify_on_read_latest_only', True)) and records:
            records = [records[0]]
        verifications = []
        for record in records:
            artifact = dict(record.get('artifact') or {})
            if not artifact:
                continue
            verification = self._verify_portfolio_evidence_artifact_payload(artifact=artifact)
            verifications.append({
                'package_id': record.get('package_id'),
                'artifact_sha256': ((verification.get('artifact') or {}).get('sha256')),
                'status': (((verification.get('verification') or {}).get('status')) if verification.get('ok') else 'failed'),
                'valid': bool(((verification.get('verification') or {}).get('valid')) if verification.get('ok') else False),
                'failures': list((((verification.get('verification') or {}).get('failures')) or [])),
            })
        valid = all(bool(item.get('valid')) for item in verifications) if verifications else True
        payload = {
            'verified_at': time.time(),
            'status': 'verified' if valid else 'failed',
            'valid': valid,
            'count': len(verifications),
            'items': verifications,
            'read_kind': read_key,
            'operational_tier': train_policy.get('operational_tier'),
            'evidence_classification': train_policy.get('evidence_classification'),
        }
        if bool(gate_policy.get('persist_verify_on_read', True)):
            updated = self._store_portfolio_read_verification(gw, release=release, read_verification=payload)
            detail = self._portfolio_detail_view(gw, release=updated)
        detail['read_verification'] = payload
        if not valid and bool(gate_policy.get('block_on_failed_verify_on_read', True)):
            return {'ok': False, 'error': 'portfolio_verify_on_read_failed', 'portfolio_id': detail.get('portfolio_id'), 'read_verification': payload}
        return {'ok': True, 'enforced': True, 'detail': detail, 'read_verification': payload}

    def get_runtime_alert_governance_portfolio(self, gw, *, portfolio_id: str, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None, read_kind: str = 'detail') -> dict[str, Any]:
        release = gw.audit.get_release_bundle(portfolio_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if release is None or not self._is_alert_governance_portfolio_release(release):
            return {'ok': False, 'error': 'governance_portfolio_not_found', 'portfolio_id': str(portfolio_id or '').strip()}
        detail = self._portfolio_detail_view(gw, release=release)
        verify_on_read = self._enforce_portfolio_verify_on_read(gw, detail=detail, read_kind=read_kind)
        if not verify_on_read.get('ok'):
            return verify_on_read
        if verify_on_read.get('enforced'):
            detail = dict(verify_on_read.get('detail') or detail)
        return detail

    def submit_runtime_alert_governance_portfolio(self, gw, *, portfolio_id: str, actor: str, reason: str = '', tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any]:
        release = gw.audit.submit_release_bundle(portfolio_id, actor=str(actor or 'admin'), reason=str(reason or '').strip(), tenant_id=tenant_id, workspace_id=workspace_id)
        metadata = dict(release.get('metadata') or {})
        portfolio = dict(metadata.get('portfolio') or {})
        portfolio['submitted_by'] = str(actor or 'admin')
        portfolio['submitted_reason'] = str(reason or '').strip()
        metadata['portfolio'] = portfolio
        gw.audit.update_release_bundle(portfolio_id, status=release.get('status'), notes=release.get('notes'), metadata=metadata, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        release = gw.audit.get_release_bundle(portfolio_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment) or release
        return self._portfolio_detail_view(gw, release=release)

    def simulate_runtime_alert_governance_portfolio(
        self,
        gw,
        *,
        portfolio_id: str,
        actor: str,
        now_ts: float | None = None,
        dry_run: bool = True,
        auto_reschedule: bool | None = None,
        persist_schedule: bool = False,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        release = gw.audit.get_release_bundle(portfolio_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if release is None or not self._is_alert_governance_portfolio_release(release):
            return {'ok': False, 'error': 'governance_portfolio_not_found', 'portfolio_id': str(portfolio_id or '').strip()}
        simulation = self._simulate_portfolio_calendar(
            gw,
            release=release,
            actor=actor,
            now_ts=now_ts,
            dry_run=dry_run,
            auto_reschedule=auto_reschedule,
            persist_metadata=True,
            persist_schedule=bool(persist_schedule),
        )
        refreshed = gw.audit.get_release_bundle(portfolio_id, tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=release.get('environment')) or release
        detail = self._portfolio_detail_view(gw, release=refreshed)
        detail['simulation'] = simulation
        return detail

    def list_runtime_alert_governance_portfolio_approvals(
        self,
        gw,
        *,
        portfolio_id: str | None = None,
        limit: int = 100,
        status: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        if portfolio_id:
            detail = self.get_runtime_alert_governance_portfolio(gw, portfolio_id=portfolio_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, read_kind='approvals')
            if not detail.get('ok'):
                return detail
            approvals = self._list_portfolio_approvals(
                gw,
                portfolio_id=portfolio_id,
                limit=limit,
                status=status,
                tenant_id=detail.get('scope', {}).get('tenant_id'),
                workspace_id=detail.get('scope', {}).get('workspace_id'),
                environment=detail.get('scope', {}).get('environment'),
            )
            return {
                'ok': True,
                'portfolio_id': portfolio_id,
                'items': approvals,
                'summary': detail.get('approval_summary'),
                'scope': detail.get('scope'),
                'read_verification': detail.get('read_verification'),
            }
        approvals = gw.audit.list_approvals(limit=max(limit * 5, limit), status=status, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        filtered = []
        for approval in approvals:
            workflow_id = str(approval.get('workflow_id') or '')
            if not workflow_id.startswith('openclaw-governance-portfolio:'):
                continue
            filtered.append(approval)
            if len(filtered) >= limit:
                break
        return {'ok': True, 'items': filtered, 'summary': {'count': len(filtered), 'status': status}, 'scope': self._scope(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)}

    def _finalize_runtime_alert_governance_portfolio_approval(
        self,
        gw,
        *,
        release: dict[str, Any],
        actor: str,
        reason: str,
        simulation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        simulation_payload = dict(simulation or {})
        if not simulation_payload:
            simulation_payload = self._simulate_portfolio_calendar(
                gw,
                release=release,
                actor=actor,
                dry_run=True,
                auto_reschedule=None,
                persist_metadata=False,
                persist_schedule=False,
            )
        if not bool(simulation_payload.get('approvable')):
            return {
                'ok': False,
                'error': 'portfolio_simulation_blocked',
                'portfolio_id': str(release.get('release_id') or ''),
                'simulation': simulation_payload,
            }
        should_persist_schedule = bool((simulation_payload.get('summary') or {}).get('reprogrammed_count') or 0) > 0
        simulation_payload = self._simulate_portfolio_calendar(
            gw,
            release=release,
            actor=actor,
            dry_run=False,
            auto_reschedule=True,
            persist_metadata=True,
            persist_schedule=should_persist_schedule,
        )
        refreshed = gw.audit.get_release_bundle(str(release.get('release_id') or ''), tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=release.get('environment')) or release
        approved_release = gw.audit.approve_release_bundle(
            str(refreshed.get('release_id') or ''),
            actor=str(actor or 'admin'),
            reason=str(reason or '').strip(),
            tenant_id=refreshed.get('tenant_id'),
            workspace_id=refreshed.get('workspace_id'),
        )
        metadata = dict(approved_release.get('metadata') or {})
        portfolio = dict(metadata.get('portfolio') or {})
        portfolio['approved_by'] = str(actor or 'admin')
        portfolio['approved_reason'] = str(reason or '').strip()
        metadata['portfolio'] = portfolio
        gw.audit.update_release_bundle(str(approved_release.get('release_id') or ''), status=approved_release.get('status'), notes=approved_release.get('notes'), metadata=metadata, tenant_id=approved_release.get('tenant_id'), workspace_id=approved_release.get('workspace_id'), environment=approved_release.get('environment'))
        approved_release = gw.audit.get_release_bundle(str(approved_release.get('release_id') or ''), tenant_id=approved_release.get('tenant_id'), workspace_id=approved_release.get('workspace_id'), environment=approved_release.get('environment')) or approved_release
        attestation, approved_release = self._create_portfolio_execution_attestation(
            gw,
            release=approved_release,
            actor=str(actor or 'system'),
            reason=str(reason or '').strip(),
            simulation=simulation_payload,
        )
        self._ensure_portfolio_release_train_jobs(gw, release=approved_release, actor=str(actor or 'system'))
        detail = self._portfolio_detail_view(gw, release=approved_release)
        detail['simulation'] = simulation_payload
        detail['attestation'] = attestation
        return detail

    def approve_runtime_alert_governance_portfolio(self, gw, *, portfolio_id: str, actor: str, reason: str = '', tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any]:
        release = gw.audit.get_release_bundle(portfolio_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if release is None or not self._is_alert_governance_portfolio_release(release):
            return {'ok': False, 'error': 'governance_portfolio_not_found', 'portfolio_id': str(portfolio_id or '').strip()}
        if str(release.get('status') or '') not in {'candidate', 'pending_approval', 'approved'}:
            return {'ok': False, 'error': 'portfolio_not_approvable', 'portfolio_id': portfolio_id, 'release_status': release.get('status')}
        metadata = dict(release.get('metadata') or {})
        portfolio = dict(metadata.get('portfolio') or {})
        base_train_policy = self._normalize_portfolio_train_policy(dict(portfolio.get('train_policy') or {}))
        train_policy = self._resolve_portfolio_train_policy_for_environment(base_train_policy, environment=release.get('environment'))
        simulation = self._simulate_portfolio_calendar(
            gw,
            release=release,
            actor=actor,
            dry_run=True,
            auto_reschedule=None,
            persist_metadata=True,
            persist_schedule=False,
        )
        if not bool(simulation.get('approvable')):
            return {
                'ok': False,
                'error': 'portfolio_simulation_blocked',
                'portfolio_id': portfolio_id,
                'release_status': release.get('status'),
                'simulation': simulation,
            }
        approval_policy = self._normalize_portfolio_approval_policy(dict(train_policy.get('approval_policy') or {}))
        if approval_policy.get('enabled'):
            approval_state = self._ensure_portfolio_multilayer_approvals(gw, release=release, actor=actor, approval_policy=approval_policy)
            if str(approval_state.get('overall_status') or '') == 'rejected':
                return {
                    'ok': False,
                    'error': 'portfolio_approval_rejected',
                    'portfolio_id': portfolio_id,
                    'approval_summary': approval_state,
                    'simulation': simulation,
                }
            if not bool(approval_state.get('satisfied')):
                pending_release = self._refresh_portfolio_metadata_state(gw, release=release, approval_state=approval_state, simulation=simulation, persist_schedule=False)
                pending_release = gw.audit.update_release_bundle(
                    str(pending_release.get('release_id') or ''),
                    status='pending_approval',
                    notes=pending_release.get('notes'),
                    metadata=dict(pending_release.get('metadata') or {}),
                    tenant_id=pending_release.get('tenant_id'),
                    workspace_id=pending_release.get('workspace_id'),
                    environment=pending_release.get('environment'),
                ) or pending_release
                return self._portfolio_detail_view(gw, release=pending_release)
        security_gate = self._enforce_portfolio_security_envelope(gw, detail=self._portfolio_detail_view(gw, release=release), actor=actor, operation='approval_finalize')
        if not security_gate.get('ok'):
            return {**security_gate, 'portfolio_id': portfolio_id, 'simulation': simulation}
        detail = self._finalize_runtime_alert_governance_portfolio_approval(gw, release=release, actor=actor, reason=reason, simulation=simulation)
        if detail.get('ok'):
            detail['security_envelope'] = security_gate
        return detail

    def decide_runtime_alert_governance_portfolio_approval(
        self,
        gw,
        *,
        approval_id: str,
        actor: str,
        decision: str,
        reason: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        approval = gw.audit.get_approval(approval_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if approval is None:
            return {'ok': False, 'error': 'approval_not_found', 'approval_id': str(approval_id or '').strip()}
        workflow_id = str(approval.get('workflow_id') or '')
        if not workflow_id.startswith('openclaw-governance-portfolio:'):
            return {'ok': False, 'error': 'unsupported_approval', 'approval_id': str(approval_id or '').strip()}
        portfolio_id = workflow_id.split(':', 1)[1]
        updated_approval = gw.audit.decide_approval(
            str(approval_id or '').strip(),
            decision=decision,
            decided_by=str(actor or '').strip(),
            reason=str(reason or '').strip(),
            tenant_id=approval.get('tenant_id'),
            workspace_id=approval.get('workspace_id'),
            environment=approval.get('environment'),
        )
        if updated_approval is None:
            return {'ok': False, 'error': 'approval_not_pending', 'approval_id': str(approval_id or '').strip()}
        release = gw.audit.get_release_bundle(portfolio_id, tenant_id=approval.get('tenant_id'), workspace_id=approval.get('workspace_id'), environment=approval.get('environment'))
        if release is None or not self._is_alert_governance_portfolio_release(release):
            return {'ok': False, 'error': 'governance_portfolio_not_found', 'approval': updated_approval, 'portfolio_id': portfolio_id}
        metadata = dict(release.get('metadata') or {})
        portfolio = dict(metadata.get('portfolio') or {})
        base_train_policy = self._normalize_portfolio_train_policy(dict(portfolio.get('train_policy') or {}))
        train_policy = self._resolve_portfolio_train_policy_for_environment(base_train_policy, environment=release.get('environment'))
        approval_policy = self._normalize_portfolio_approval_policy(dict(train_policy.get('approval_policy') or {}))
        approval_state = self._ensure_portfolio_multilayer_approvals(gw, release=release, actor=actor, approval_policy=approval_policy)
        release = self._refresh_portfolio_metadata_state(gw, release=release, approval_state=approval_state, persist_schedule=False)
        if str(updated_approval.get('status') or '') == 'approved' and bool(approval_state.get('satisfied')):
            detail = self._finalize_runtime_alert_governance_portfolio_approval(gw, release=release, actor=actor, reason=reason)
            detail['approval'] = updated_approval
            return detail
        if str(updated_approval.get('status') or '') == 'rejected':
            metadata = dict(release.get('metadata') or {})
            portfolio = dict(metadata.get('portfolio') or {})
            portfolio['approval_rejected_by'] = str(actor or '').strip()
            portfolio['approval_rejected_reason'] = str(reason or '').strip()
            metadata['portfolio'] = portfolio
            rejected_release = gw.audit.update_release_bundle(
                str(release.get('release_id') or ''),
                status='rejected',
                notes=reason or release.get('notes'),
                metadata=metadata,
                tenant_id=release.get('tenant_id'),
                workspace_id=release.get('workspace_id'),
                environment=release.get('environment'),
            ) or release
            detail = self._portfolio_detail_view(gw, release=rejected_release)
            detail['approval'] = updated_approval
            return detail
        pending_release = gw.audit.update_release_bundle(
            str(release.get('release_id') or ''),
            status='pending_approval',
            notes=release.get('notes'),
            metadata=dict(release.get('metadata') or {}),
            tenant_id=release.get('tenant_id'),
            workspace_id=release.get('workspace_id'),
            environment=release.get('environment'),
        ) or release
        detail = self._portfolio_detail_view(gw, release=pending_release)
        detail['approval'] = updated_approval
        return detail

    def _ensure_portfolio_release_train_jobs(self, gw, *, release: dict[str, Any], actor: str) -> list[dict[str, Any]]:
        detail = self._portfolio_detail_view(gw, release=release)
        scope = dict(detail.get('scope') or {})
        created: list[dict[str, Any]] = []
        existing_jobs = gw.audit.list_job_schedules(limit=500, enabled=None, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'))
        by_event = {str((item.get('workflow_definition') or {}).get('event_id') or ''): item for item in existing_jobs if self._is_release_train_job(item, portfolio_id=str(release.get('release_id') or ''))}
        for event in list((detail.get('calendar') or {}).get('items') or []):
            if event.get('planned_at') is None or str(((event.get('validation') or {}).get('simulation_status')) or '') == 'blocked':
                continue
            event_id = str(event.get('event_id') or '')
            job = by_event.get(event_id)
            definition = self._release_train_job_definition(portfolio_id=str(release.get('release_id') or ''), event_id=event_id, bundle_id=str(event.get('bundle_id') or ''), wave_no=int(event.get('wave_no') or 1), actor=actor, reason=f'portfolio {release.get("release_id")} event {event_id}')
            if job is not None:
                gw.audit.update_job_schedule(str(job.get('job_id') or ''), workflow_definition=definition, next_run_at=float(event.get('planned_at')), enabled=True, last_error='', updated_at=time.time(), tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'))
                refreshed = self.job_service.get_job(gw, str(job.get('job_id') or ''), tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'))
                if refreshed is not None:
                    created.append(refreshed)
                continue
            created.append(self.job_service.create_job(gw, name=f'openclaw-train-{event_id}', workflow_definition=definition, created_by=str(actor or 'system'), input_payload={'portfolio_id': str(release.get('release_id') or ''), 'event_id': event_id}, next_run_at=float(event.get('planned_at')), enabled=True, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'), schedule_kind='once'))
        return created

    def _build_portfolio_attestation_export_payload(
        self,
        *,
        detail: dict[str, Any],
        actor: str,
        attestation_id: str | None = None,
    ) -> dict[str, Any]:
        release = dict(detail.get('release') or {})
        attestation = self._find_portfolio_attestation(release, attestation_id=attestation_id)
        if attestation is None:
            return {'ok': False, 'error': 'portfolio_attestation_not_found', 'portfolio_id': detail.get('portfolio_id'), 'attestation_id': attestation_id}
        train_policy = self._resolve_portfolio_train_policy_for_environment(dict(((detail.get('portfolio') or {}).get('train_policy') or {})), environment=release.get('environment'))
        report = {
            'report_type': 'openmiura_portfolio_attestation_export_v1',
            'generated_at': time.time(),
            'generated_by': str(actor or 'system'),
            'portfolio': {
                'portfolio_id': detail.get('portfolio_id'),
                'name': release.get('name'),
                'version': release.get('version'),
                'status': release.get('status'),
            },
            'scope': dict(detail.get('scope') or {}),
            'attestation': attestation,
            'approval_summary': dict(detail.get('approval_summary') or {}),
            'simulation': {
                'validation_status': ((detail.get('simulation') or {}).get('validation_status')),
                'summary': ((detail.get('simulation') or {}).get('summary')),
            },
            'train_policy': {
                'export_policy': train_policy.get('export_policy'),
                'drift_policy': train_policy.get('drift_policy'),
                'notarization_policy': train_policy.get('notarization_policy'),
                'retention_policy': train_policy.get('retention_policy'),
                'escrow_policy': train_policy.get('escrow_policy'),
                'signing_policy': train_policy.get('signing_policy'),
                'chain_of_custody_policy': train_policy.get('chain_of_custody_policy'),
                'verification_gate_policy': train_policy.get('verification_gate_policy'),
                'security_gate_policy': train_policy.get('security_gate_policy'),
                'environment_tier_policy': train_policy.get('environment_tier_policy'),
                'baseline_catalog_ref': train_policy.get('baseline_catalog_ref'),
                'operational_tier': train_policy.get('operational_tier'),
                'evidence_classification': train_policy.get('evidence_classification'),
            },
            'baseline_catalog_rollout': dict(((detail.get('portfolio') or {}).get('baseline_catalog_rollout') or {}) or {}),
            'policy_conformance': dict(detail.get('policy_conformance') or {}),
            'policy_baseline_drift': dict(detail.get('policy_baseline_drift') or {}),
            'deviation_exceptions': dict(detail.get('deviation_exceptions') or {}),
        }
        integrity = self._portfolio_evidence_integrity(
            report_type=report['report_type'],
            scope=dict(detail.get('scope') or {}),
            payload=report,
            actor=actor,
            export_policy=train_policy.get('export_policy'),
            signing_policy=train_policy.get('signing_policy'),
        )
        return {'ok': True, 'portfolio_id': detail.get('portfolio_id'), 'attestation_id': attestation.get('attestation_id'), 'report': report, 'integrity': integrity, 'scope': detail.get('scope')}

    def _build_portfolio_postmortem_export_payload(
        self,
        gw,
        *,
        detail: dict[str, Any],
        actor: str,
        attestation_id: str | None = None,
        timeline_limit: int | None = None,
    ) -> dict[str, Any]:
        release = dict(detail.get('release') or {})
        attestation = self._find_portfolio_attestation(release, attestation_id=attestation_id)
        train_policy = self._resolve_portfolio_train_policy_for_environment(dict(((detail.get('portfolio') or {}).get('train_policy') or {})), environment=release.get('environment'))
        export_policy = dict(train_policy.get('export_policy') or {})
        replay_limit = max(25, int(timeline_limit or export_policy.get('timeline_limit') or 250))
        drift = dict(detail.get('drift') or {})
        replay = self._build_portfolio_replay_timeline(gw, release=release, detail=detail, attestation=attestation, limit=replay_limit)
        execution_compare = self._portfolio_execution_compare(detail=detail, attestation=attestation, drift=drift)
        report = {
            'report_type': 'openmiura_portfolio_postmortem_v1',
            'generated_at': time.time(),
            'generated_by': str(actor or 'system'),
            'portfolio': {
                'portfolio_id': detail.get('portfolio_id'),
                'name': release.get('name'),
                'version': release.get('version'),
                'status': release.get('status'),
            },
            'scope': dict(detail.get('scope') or {}),
            'attestation': attestation,
            'operational_tier': train_policy.get('operational_tier'),
            'evidence_classification': train_policy.get('evidence_classification'),
            'drift': drift,
            'summary': self._portfolio_postmortem_summary(detail=detail, execution_compare=execution_compare, drift=drift),
            'execution_compare': execution_compare,
            'replay': replay,
            'jobs': detail.get('jobs') if bool(export_policy.get('include_jobs', True)) else {'items': [], 'summary': {}},
            'approvals': detail.get('approvals'),
            'policy_conformance': dict(detail.get('policy_conformance') or {}),
            'policy_baseline_drift': dict(detail.get('policy_baseline_drift') or {}),
            'deviation_exceptions': dict(detail.get('deviation_exceptions') or {}),
        }
        integrity = self._portfolio_evidence_integrity(
            report_type=report['report_type'],
            scope=dict(detail.get('scope') or {}),
            payload=report,
            actor=actor,
            export_policy=export_policy,
            signing_policy=train_policy.get('signing_policy'),
        )
        return {'ok': True, 'portfolio_id': detail.get('portfolio_id'), 'attestation_id': (attestation or {}).get('attestation_id'), 'report': report, 'integrity': integrity, 'scope': detail.get('scope')}

    def _enforce_portfolio_verification_gate(
        self,
        gw,
        *,
        detail: dict[str, Any],
        actor: str,
        operation: str,
        package_id: str | None = None,
        artifact: dict[str, Any] | None = None,
        artifact_b64: str | None = None,
    ) -> dict[str, Any]:
        release = dict(detail.get('release') or {})
        train_policy = self._resolve_portfolio_train_policy_for_environment(dict((((detail.get('portfolio') or {}).get('train_policy')) or {})), environment=release.get('environment'))
        gate_policy = dict(train_policy.get('verification_gate_policy') or {})
        if not bool(gate_policy.get('enabled')):
            return {'ok': True, 'enforced': False, 'operation': operation, 'reason': 'verification_gate_disabled'}
        must_enforce = (operation == 'sensitive_export' and bool(gate_policy.get('require_before_sensitive_export'))) or (operation == 'sensitive_restore' and bool(gate_policy.get('require_before_sensitive_restore')))
        if not must_enforce:
            return {'ok': True, 'enforced': False, 'operation': operation, 'reason': 'verification_gate_not_required'}
        custody_anchor_policy = dict(train_policy.get('custody_anchor_policy') or {})
        reconciliation = None
        if bool(gate_policy.get('require_chain_reconciliation', True)):
            reconciliation = self._reconcile_portfolio_custody_anchor_state(
                gw,
                release=release,
                actor=actor,
                custody_anchor_policy=custody_anchor_policy,
                persist=True,
            )
            if bool(gate_policy.get('block_on_reconciliation_conflict', True)) and int(reconciliation.get('conflict_count') or 0) > 0:
                return {'ok': False, 'error': 'portfolio_verification_gate_failed', 'reason': 'custody_anchor_reconciliation_conflict', 'operation': operation, 'reconciliation': reconciliation}
            if bool(gate_policy.get('require_quorum_or_authority', False)) and not bool(((reconciliation.get('quorum') or {}).get('authority_satisfied'))):
                return {'ok': False, 'error': 'portfolio_verification_gate_failed', 'reason': 'custody_anchor_quorum_or_authority_missing', 'operation': operation, 'reconciliation': reconciliation}
        if bool(gate_policy.get('require_external_anchor_validation', True)):
            receipts = self._load_external_portfolio_custody_anchor_receipts(release=release, custody_anchor_policy=custody_anchor_policy)
            if receipts:
                external_verify = self._verify_portfolio_custody_anchor_receipts(receipts, expected_portfolio_id=str(release.get('release_id') or ''))
                if not bool(external_verify.get('valid', True)):
                    return {'ok': False, 'error': 'portfolio_verification_gate_failed', 'reason': 'external_custody_anchor_validation_failed', 'operation': operation, 'reconciliation': reconciliation, 'custody_anchor_validation': external_verify}
        provider_validation = None
        if bool(gate_policy.get('require_live_provider_validation', False)):
            provider_validation = self.validate_runtime_alert_governance_portfolio_provider_integrations(
                gw,
                portfolio_id=str(release.get('release_id') or ''),
                actor=actor,
                tenant_id=release.get('tenant_id'),
                workspace_id=release.get('workspace_id'),
                environment=release.get('environment'),
            )
            if not bool(provider_validation.get('ok')) or not bool(provider_validation.get('valid')):
                return {'ok': False, 'error': 'portfolio_verification_gate_failed', 'reason': 'live_provider_validation_failed', 'operation': operation, 'provider_validation': provider_validation, 'reconciliation': reconciliation}
        verification = None
        if operation == 'sensitive_restore' and bool(gate_policy.get('require_verified_artifact_for_restore', True)):
            verification = self._verify_portfolio_evidence_artifact_payload(artifact=artifact, artifact_b64=artifact_b64) if (artifact or artifact_b64 is not None) else self._verify_portfolio_evidence_artifact_payload(artifact=dict((self._find_portfolio_evidence_package(release, package_id=package_id, include_content=True) or {}).get('artifact') or {}))
            if not bool((verification.get('verification') or {}).get('valid')):
                return {'ok': False, 'error': 'portfolio_verification_gate_failed', 'reason': 'artifact_verification_required', 'operation': operation, 'verification': verification, 'reconciliation': reconciliation}
        return {'ok': True, 'enforced': True, 'operation': operation, 'reconciliation': reconciliation, 'verification': verification, 'provider_validation': provider_validation}

    def reconcile_runtime_alert_governance_portfolio_custody_anchors(
        self,
        gw,
        *,
        portfolio_id: str,
        actor: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        release = gw.audit.get_release_bundle(portfolio_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if release is None or not self._is_alert_governance_portfolio_release(release):
            return {'ok': False, 'error': 'governance_portfolio_not_found', 'portfolio_id': str(portfolio_id or '').strip()}
        train_policy = self._resolve_portfolio_train_policy_for_environment(dict((((release.get('metadata') or {}).get('portfolio') or {}).get('train_policy') or {})), environment=release.get('environment'))
        reconciliation = self._reconcile_portfolio_custody_anchor_state(
            gw,
            release=release,
            actor=actor,
            custody_anchor_policy=dict(train_policy.get('custody_anchor_policy') or {}),
            persist=True,
        )
        refreshed = dict(reconciliation.get('release') or release)
        detail = self._portfolio_detail_view(gw, release=refreshed)
        return {'ok': True, 'portfolio_id': detail.get('portfolio_id'), 'reconciliation': reconciliation, 'custody_anchors': detail.get('custody_anchors'), 'summary': detail.get('summary'), 'scope': detail.get('scope')}

    def get_runtime_alert_governance_portfolio_calendar(self, gw, *, portfolio_id: str, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any]:
        detail = self.get_runtime_alert_governance_portfolio(gw, portfolio_id=portfolio_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, read_kind='calendar')
        if not detail.get('ok'):
            return detail
        return {'ok': True, 'portfolio_id': detail.get('portfolio_id'), 'calendar': detail.get('calendar'), 'jobs': detail.get('jobs'), 'summary': detail.get('summary'), 'simulation': detail.get('simulation'), 'approval_summary': detail.get('approval_summary'), 'attestations': detail.get('attestations'), 'evidence_packages': detail.get('evidence_packages'), 'drift': detail.get('drift'), 'scope': detail.get('scope'), 'read_verification': detail.get('read_verification')}

    def list_runtime_alert_governance_portfolio_attestations(self, gw, *, portfolio_id: str, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any]:
        detail = self.get_runtime_alert_governance_portfolio(gw, portfolio_id=portfolio_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, read_kind='attestations')
        if not detail.get('ok'):
            return detail
        return {'ok': True, 'portfolio_id': detail.get('portfolio_id'), 'attestations': detail.get('attestations'), 'summary': detail.get('summary'), 'scope': detail.get('scope'), 'read_verification': detail.get('read_verification')}

    def list_runtime_alert_governance_portfolio_evidence_packages(self, gw, *, portfolio_id: str, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any]:
        detail = self.get_runtime_alert_governance_portfolio(gw, portfolio_id=portfolio_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, read_kind='evidence_packages')
        if not detail.get('ok'):
            return detail
        return {'ok': True, 'portfolio_id': detail.get('portfolio_id'), 'evidence_packages': detail.get('evidence_packages'), 'summary': detail.get('summary'), 'scope': detail.get('scope'), 'read_verification': detail.get('read_verification')}

    def list_runtime_alert_governance_portfolio_chain_of_custody(self, gw, *, portfolio_id: str, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any]:
        detail = self.get_runtime_alert_governance_portfolio(gw, portfolio_id=portfolio_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, read_kind='chain_of_custody')
        if not detail.get('ok'):
            return detail
        return {'ok': True, 'portfolio_id': detail.get('portfolio_id'), 'chain_of_custody': detail.get('chain_of_custody'), 'summary': detail.get('summary'), 'scope': detail.get('scope'), 'read_verification': detail.get('read_verification')}

    def list_runtime_alert_governance_portfolio_custody_anchors(self, gw, *, portfolio_id: str, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any]:
        detail = self.get_runtime_alert_governance_portfolio(gw, portfolio_id=portfolio_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, read_kind='custody_anchors')
        if not detail.get('ok'):
            return detail
        return {'ok': True, 'portfolio_id': detail.get('portfolio_id'), 'custody_anchors': detail.get('custody_anchors'), 'summary': detail.get('summary'), 'scope': detail.get('scope'), 'read_verification': detail.get('read_verification')}

    def validate_runtime_alert_governance_portfolio_provider_integrations(
        self,
        gw,
        *,
        portfolio_id: str,
        actor: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        release = gw.audit.get_release_bundle(portfolio_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if release is None or not self._is_alert_governance_portfolio_release(release):
            return {'ok': False, 'error': 'governance_portfolio_not_found', 'portfolio_id': str(portfolio_id or '').strip()}
        train_policy = self._resolve_portfolio_train_policy_for_environment(dict((((release.get('metadata') or {}).get('portfolio') or {}).get('train_policy') or {})), environment=release.get('environment'))
        signing = self._validate_portfolio_signing_provider_live(signing_policy=dict(train_policy.get('signing_policy') or {}))
        escrow = self._validate_portfolio_escrow_backend_live(escrow_policy=dict(train_policy.get('escrow_policy') or {}))
        custody_anchor = self._validate_portfolio_custody_anchor_backend_live(custody_anchor_policy=dict(train_policy.get('custody_anchor_policy') or {}))
        payload = {
            'validated_at': time.time(),
            'validated_by': str(actor or 'system').strip() or 'system',
            'operational_tier': train_policy.get('operational_tier'),
            'evidence_classification': train_policy.get('evidence_classification'),
            'signing': signing,
            'escrow': escrow,
            'custody_anchor': custody_anchor,
            'valid': bool(signing.get('valid', True)) and bool(escrow.get('valid', True)) and bool(custody_anchor.get('valid', True)),
        }
        updated = self._store_portfolio_provider_validation(gw, release=release, validation=payload)
        detail = self._portfolio_detail_view(gw, release=updated)
        return {'ok': True, 'portfolio_id': portfolio_id, 'valid': bool(payload.get('valid')), 'provider_validation': payload, 'summary': detail.get('summary'), 'scope': detail.get('scope')}

    def attest_runtime_alert_governance_portfolio_custody_anchor(
        self,
        gw,
        *,
        portfolio_id: str,
        actor: str,
        package_id: str | None = None,
        control_plane_id: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        detail = self.get_runtime_alert_governance_portfolio(gw, portfolio_id=portfolio_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, read_kind='action_context')
        if not detail.get('ok'):
            return detail
        release = dict(detail.get('release') or {})
        train_policy = self._resolve_portfolio_train_policy_for_environment(dict((((detail.get('portfolio') or {}).get('train_policy')) or {})), environment=release.get('environment'))
        custody_anchor_policy = dict(train_policy.get('custody_anchor_policy') or {})
        signing_policy = dict(train_policy.get('signing_policy') or {})
        current_package = self._find_portfolio_evidence_package(release, package_id=package_id, include_content=False)
        if current_package is None:
            current_package = self._find_portfolio_evidence_package(release, package_id=None, include_content=False)
        if current_package is None:
            return {'ok': False, 'error': 'portfolio_evidence_package_not_found', 'portfolio_id': portfolio_id, 'package_id': package_id}
        package_payload = dict(current_package.get('package') or {})
        chain_snapshot = dict(package_payload.get('chain_of_custody') or current_package.get('chain_of_custody') or {})
        if not chain_snapshot:
            chain_entries = self._list_portfolio_chain_of_custody_entries(release)
            chain_snapshot = {
                'ledger_type': 'openmiura_portfolio_chain_of_custody_v1',
                'portfolio_id': str(release.get('release_id') or ''),
                'scope': self._scope(tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=release.get('environment')),
                'entries': chain_entries,
                'summary': self._verify_portfolio_chain_of_custody_entries(chain_entries),
            }
        manifest_hash = str(
            (((package_payload.get('manifest') or {}).get('manifest_hash'))
             or ((current_package.get('manifest') or {}).get('manifest_hash'))
             or current_package.get('manifest_hash')
             or '')
        ).strip()
        anchor = self._anchor_portfolio_chain_of_custody_external(
            release=release,
            chain_of_custody=chain_snapshot,
            package_id=str(current_package.get('package_id') or ''),
            manifest_hash=manifest_hash,
            artifact_sha256=str(((current_package.get('artifact') or {}).get('sha256')) or ''),
            actor=actor,
            custody_anchor_policy=custody_anchor_policy,
            signing_policy=signing_policy,
            anchor_role='witness',
            control_plane_id=control_plane_id,
        )
        if not bool(anchor.get('anchored')):
            return {'ok': False, 'error': 'portfolio_custody_anchor_attestation_failed', 'portfolio_id': portfolio_id, 'package_id': current_package.get('package_id'), 'anchor': anchor}
        refreshed = self._store_portfolio_custody_anchor_receipt(gw, release=release, receipt=dict(anchor.get('receipt') or {}), custody_anchor_policy=custody_anchor_policy)
        detail = self._portfolio_detail_view(gw, release=refreshed)
        return {'ok': True, 'portfolio_id': portfolio_id, 'package_id': current_package.get('package_id'), 'anchor': anchor, 'custody_anchors': detail.get('custody_anchors'), 'summary': detail.get('summary'), 'scope': detail.get('scope')}

    def export_runtime_alert_governance_portfolio_attestation(
        self,
        gw,
        *,
        portfolio_id: str,
        actor: str,
        attestation_id: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        detail = self.get_runtime_alert_governance_portfolio(gw, portfolio_id=portfolio_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, read_kind='action_context')
        if not detail.get('ok'):
            return detail
        security_gate = self._enforce_portfolio_security_envelope(gw, detail=detail, actor=actor, operation='sensitive_export')
        if not security_gate.get('ok'):
            return {**security_gate, 'portfolio_id': portfolio_id}
        payload = self._build_portfolio_attestation_export_payload(detail=detail, actor=actor, attestation_id=attestation_id)
        if not payload.get('ok'):
            return payload
        release = dict(detail.get('release') or {})
        self._log_portfolio_evidence_export(gw, release=release, actor=actor, report_type=((payload.get('report') or {}).get('report_type') or ''), integrity=dict(payload.get('integrity') or {}), metadata={'attestation_id': payload.get('attestation_id')})
        payload['security_envelope'] = security_gate
        return payload

    def export_runtime_alert_governance_portfolio_postmortem(
        self,
        gw,
        *,
        portfolio_id: str,
        actor: str,
        attestation_id: str | None = None,
        timeline_limit: int | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        detail = self.get_runtime_alert_governance_portfolio(gw, portfolio_id=portfolio_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, read_kind='action_context')
        if not detail.get('ok'):
            return detail
        security_gate = self._enforce_portfolio_security_envelope(gw, detail=detail, actor=actor, operation='sensitive_export')
        if not security_gate.get('ok'):
            return {**security_gate, 'portfolio_id': portfolio_id}
        payload = self._build_portfolio_postmortem_export_payload(gw, detail=detail, actor=actor, attestation_id=attestation_id, timeline_limit=timeline_limit)
        if not payload.get('ok'):
            return payload
        release = dict(detail.get('release') or {})
        self._log_portfolio_evidence_export(
            gw,
            release=release,
            actor=actor,
            report_type=((payload.get('report') or {}).get('report_type') or ''),
            integrity=dict(payload.get('integrity') or {}),
            metadata={'attestation_id': payload.get('attestation_id'), 'timeline_count': ((((payload.get('report') or {}).get('replay') or {}).get('summary') or {}).get('count'))},
        )
        payload['security_envelope'] = security_gate
        return payload

    def export_runtime_alert_governance_portfolio_evidence_package(
        self,
        gw,
        *,
        portfolio_id: str,
        actor: str,
        attestation_id: str | None = None,
        timeline_limit: int | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        detail = self.get_runtime_alert_governance_portfolio(gw, portfolio_id=portfolio_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, read_kind='action_context')
        if not detail.get('ok'):
            return detail
        security_gate = self._enforce_portfolio_security_envelope(gw, detail=detail, actor=actor, operation='sensitive_export')
        if not security_gate.get('ok'):
            return {**security_gate, 'portfolio_id': portfolio_id}
        gate = self._enforce_portfolio_verification_gate(gw, detail=detail, actor=actor, operation='sensitive_export')
        if not gate.get('ok'):
            return {**gate, 'portfolio_id': portfolio_id}
        payload = self._build_portfolio_evidence_package_export_payload(gw, detail=detail, actor=actor, attestation_id=attestation_id, timeline_limit=timeline_limit)
        if payload.get('ok'):
            payload['verification_gate'] = gate
            payload['security_envelope'] = security_gate
        return payload

    def prune_runtime_alert_governance_portfolio_evidence_packages(
        self,
        gw,
        *,
        portfolio_id: str,
        actor: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        detail = self.get_runtime_alert_governance_portfolio(gw, portfolio_id=portfolio_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, read_kind='action_context')
        if not detail.get('ok'):
            return detail
        release = dict(detail.get('release') or {})
        prune = self._prune_portfolio_evidence_packages(gw, release=release, actor=actor)
        refreshed = gw.audit.get_release_bundle(portfolio_id, tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=release.get('environment')) or release
        updated_detail = self._portfolio_detail_view(gw, release=refreshed)
        return {
            'ok': True,
            'portfolio_id': portfolio_id,
            'prune': {'removed': prune.get('removed'), 'summary': prune.get('summary')},
            'evidence_packages': updated_detail.get('evidence_packages'),
            'summary': updated_detail.get('summary'),
            'scope': updated_detail.get('scope'),
        }

    def verify_runtime_alert_governance_portfolio_evidence_artifact(
        self,
        gw,
        *,
        portfolio_id: str,
        actor: str,
        package_id: str | None = None,
        artifact: dict[str, Any] | None = None,
        artifact_b64: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        detail = self.get_runtime_alert_governance_portfolio(gw, portfolio_id=portfolio_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, read_kind='action_context')
        if not detail.get('ok'):
            return detail
        artifact_payload = dict(artifact or {})
        if not artifact_payload and artifact_b64 is None:
            record = self._find_portfolio_evidence_package(dict(detail.get('release') or {}), package_id=package_id, include_content=True)
            if record is None:
                return {'ok': False, 'error': 'portfolio_evidence_package_not_found', 'portfolio_id': portfolio_id, 'package_id': package_id}
            artifact_payload = dict(record.get('artifact') or {})
        verification = self._verify_portfolio_evidence_artifact_payload(artifact=artifact_payload or artifact, artifact_b64=artifact_b64)
        if verification.get('ok'):
            release = dict(detail.get('release') or {})
            self._log_portfolio_evidence_export(
                gw,
                release=release,
                actor=actor,
                report_type='openmiura_portfolio_evidence_artifact_verification_v1',
                integrity={'payload_hash': self._stable_digest(verification.get('verification') or {}), 'signature': '', 'signer_key_id': None},
                metadata={'package_id': verification.get('package_id'), 'artifact_sha256': ((verification.get('artifact') or {}).get('sha256')), 'verification_status': ((verification.get('verification') or {}).get('status'))},
            )
            train_policy = self._resolve_portfolio_train_policy_for_environment(dict((((detail.get('portfolio') or {}).get('train_policy')) or {})), environment=release.get('environment'))
            chain_policy = dict(train_policy.get('chain_of_custody_policy') or {})
            signing_policy = dict(train_policy.get('signing_policy') or {})
            _, new_entries, _ = self._prepare_portfolio_chain_of_custody_snapshot(
                release=release,
                actor=actor,
                chain_policy=chain_policy,
                signing_policy=signing_policy,
                events=[{
                    'event_type': 'portfolio_evidence_verified',
                    'package_id': verification.get('package_id'),
                    'artifact_sha256': ((verification.get('artifact') or {}).get('sha256')),
                    'metadata': {'verification_status': ((verification.get('verification') or {}).get('status'))},
                }],
            )
            if new_entries:
                self._store_portfolio_chain_of_custody_entries(gw, release=release, entries=new_entries, chain_policy=chain_policy)
        return verification

    def restore_runtime_alert_governance_portfolio_evidence_artifact(
        self,
        gw,
        *,
        portfolio_id: str,
        actor: str,
        package_id: str | None = None,
        artifact: dict[str, Any] | None = None,
        artifact_b64: str | None = None,
        persist_restore_session: bool = False,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        detail = self.get_runtime_alert_governance_portfolio(gw, portfolio_id=portfolio_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, read_kind='action_context')
        if not detail.get('ok'):
            return detail
        artifact_payload = dict(artifact or {})
        if not artifact_payload and artifact_b64 is None:
            record = self._find_portfolio_evidence_package(dict(detail.get('release') or {}), package_id=package_id, include_content=True)
            if record is None:
                return {'ok': False, 'error': 'portfolio_evidence_package_not_found', 'portfolio_id': portfolio_id, 'package_id': package_id}
            artifact_payload = dict(record.get('artifact') or {})
        security_gate = self._enforce_portfolio_security_envelope(gw, detail=detail, actor=actor, operation='sensitive_restore')
        if not security_gate.get('ok'):
            return {**security_gate, 'portfolio_id': portfolio_id, 'package_id': package_id}
        gate = self._enforce_portfolio_verification_gate(
            gw,
            detail=detail,
            actor=actor,
            operation='sensitive_restore',
            package_id=package_id,
            artifact=artifact_payload or artifact,
            artifact_b64=artifact_b64,
        )
        if not gate.get('ok'):
            return {**gate, 'portfolio_id': portfolio_id, 'package_id': package_id}
        restored = self._restore_portfolio_evidence_artifact_payload(
            gw,
            actor=actor,
            artifact=artifact_payload or artifact,
            artifact_b64=artifact_b64,
            persist_restore_session=persist_restore_session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        if restored.get('ok'):
            restored['verification_gate'] = gate
            restored['security_envelope'] = security_gate
        return restored

    def get_runtime_alert_governance_portfolio_policy_conformance(
        self,
        gw,
        *,
        portfolio_id: str,
        actor: str = 'system',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        persist_metadata: bool = True,
    ) -> dict[str, Any]:
        detail = self.get_runtime_alert_governance_portfolio(gw, portfolio_id=portfolio_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, read_kind='policy_conformance')
        if not detail.get('ok'):
            return detail
        release = dict(detail.get('release') or {})
        conformance = self._portfolio_policy_conformance_report(gw, release=release, persist_metadata=persist_metadata)
        refreshed_release = dict(conformance.get('release') or release)
        refreshed_detail = self._portfolio_detail_view(gw, release=refreshed_release)
        refreshed_detail['policy_conformance'] = conformance
        return {'ok': True, 'portfolio_id': portfolio_id, 'policy_conformance': conformance, 'summary': refreshed_detail.get('summary'), 'scope': refreshed_detail.get('scope')}

    def get_runtime_alert_governance_portfolio_policy_baseline_drift(
        self,
        gw,
        *,
        portfolio_id: str,
        actor: str = 'system',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        persist_metadata: bool = True,
    ) -> dict[str, Any]:
        detail = self.get_runtime_alert_governance_portfolio(gw, portfolio_id=portfolio_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, read_kind='policy_baseline_drift')
        if not detail.get('ok'):
            return detail
        release = dict(detail.get('release') or {})
        drift = self._portfolio_policy_baseline_drift_report(gw, release=release, persist_metadata=persist_metadata)
        refreshed_release = dict(drift.get('release') or release)
        refreshed_detail = self._portfolio_detail_view(gw, release=refreshed_release)
        refreshed_detail['policy_baseline_drift'] = drift
        return {
            'ok': True,
            'portfolio_id': portfolio_id,
            'policy_baseline_drift': drift,
            'deviation_exceptions': refreshed_detail.get('deviation_exceptions'),
            'summary': refreshed_detail.get('summary'),
            'scope': refreshed_detail.get('scope'),
        }

    def list_runtime_alert_governance_portfolio_policy_deviation_exceptions(
        self,
        gw,
        *,
        portfolio_id: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        persist_expiration: bool = True,
    ) -> dict[str, Any]:
        detail = self.get_runtime_alert_governance_portfolio(gw, portfolio_id=portfolio_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, read_kind='deviation_exceptions')
        if not detail.get('ok'):
            return detail
        release = dict(detail.get('release') or {})
        release, expired = self._expire_portfolio_policy_deviation_exceptions(gw, release=release, persist_metadata=persist_expiration)
        if expired:
            detail = self._portfolio_detail_view(gw, release=release)
        return {
            'ok': True,
            'portfolio_id': portfolio_id,
            'deviation_exceptions': detail.get('deviation_exceptions'),
            'policy_baseline_drift': detail.get('policy_baseline_drift'),
            'summary': detail.get('summary'),
            'scope': detail.get('scope'),
            'read_verification': detail.get('read_verification'),
        }

    def request_runtime_alert_governance_portfolio_policy_deviation_exception(
        self,
        gw,
        *,
        portfolio_id: str,
        deviation_id: str,
        actor: str,
        reason: str = '',
        ttl_s: int | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        release = gw.audit.get_release_bundle(portfolio_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if release is None or not self._is_alert_governance_portfolio_release(release):
            return {'ok': False, 'error': 'governance_portfolio_not_found', 'portfolio_id': str(portfolio_id or '').strip()}
        drift = self._portfolio_policy_baseline_drift_report(gw, release=release, persist_metadata=False)
        deviation = next((dict(item) for item in list(drift.get('items') or []) if str(item.get('deviation_id') or '') == str(deviation_id or '')), None)
        if deviation is None:
            return {'ok': False, 'error': 'portfolio_policy_deviation_not_found', 'portfolio_id': portfolio_id, 'deviation_id': str(deviation_id or '').strip()}
        train_policy = self._normalize_portfolio_train_policy(dict((((release.get('metadata') or {}).get('portfolio') or {}).get('train_policy') or {})))
        deviation_policy = self._normalize_portfolio_deviation_management_policy(dict(train_policy.get('deviation_management_policy') or {}))
        current_exceptions = [dict(item) for item in self._list_portfolio_policy_deviation_exceptions(release)]
        active_count = sum(1 for item in current_exceptions if str(item.get('status') or '') in {'approved', 'pending_approval'})
        if active_count >= int(deviation_policy.get('max_active_exceptions') or 25):
            return {'ok': False, 'error': 'portfolio_policy_deviation_exception_limit_reached', 'portfolio_id': portfolio_id, 'active_count': active_count}
        requested_ttl_s = int(ttl_s if ttl_s is not None else deviation_policy.get('default_ttl_s') or 7 * 24 * 3600)
        requested_ttl_s = max(60, min(requested_ttl_s, int(deviation_policy.get('max_ttl_s') or requested_ttl_s)))
        now_ts = time.time()
        exception_id = str(uuid.uuid4())
        requested_role = str(deviation_policy.get('requested_role') or 'security-governance').strip() or 'security-governance'
        exception_record = {
            'exception_id': exception_id,
            'portfolio_id': portfolio_id,
            'deviation_id': str(deviation.get('deviation_id') or ''),
            'field_path': str(deviation.get('field_path') or ''),
            'environment': self._normalize_portfolio_environment_name(release.get('environment')),
            'baseline_hash': deviation.get('baseline_hash'),
            'effective_hash': deviation.get('effective_hash'),
            'baseline_value': deviation.get('baseline_value'),
            'effective_value': deviation.get('effective_value'),
            'requested_at': now_ts,
            'requested_by': str(actor or 'system').strip() or 'system',
            'reason': str(reason or '').strip(),
            'requested_role': requested_role,
            'expires_at': now_ts + requested_ttl_s if bool(deviation_policy.get('auto_expire', True)) else None,
            'status': 'approved' if not bool(deviation_policy.get('require_approval', True)) else 'pending_approval',
        }
        approval = None
        if bool(deviation_policy.get('require_approval', True)):
            approval = self._ensure_step_approval_request(
                gw,
                workflow_id=self._portfolio_deviation_approval_workflow_id(portfolio_id),
                step_id=f'portfolio-deviation:{exception_id}',
                requested_role=requested_role,
                requested_by=str(actor or 'system').strip() or 'system',
                payload={
                    'portfolio_id': portfolio_id,
                    'exception_id': exception_id,
                    'deviation_id': exception_record['deviation_id'],
                    'field_path': exception_record['field_path'],
                    'baseline_hash': exception_record['baseline_hash'],
                    'effective_hash': exception_record['effective_hash'],
                    'expires_at': exception_record['expires_at'],
                },
                tenant_id=release.get('tenant_id'),
                workspace_id=release.get('workspace_id'),
                environment=release.get('environment'),
            )
            exception_record['approval_id'] = str((approval or {}).get('approval_id') or '')
        else:
            exception_record['approved_at'] = now_ts
            exception_record['approved_by'] = str(actor or 'system').strip() or 'system'
        current_exceptions.append(exception_record)
        updated = self._store_portfolio_policy_deviation_exceptions(gw, release=release, exceptions=current_exceptions, current_exception=exception_record)
        refreshed = self._portfolio_detail_view(gw, release=updated)
        drift = self._portfolio_policy_baseline_drift_report(gw, release=updated, persist_metadata=bool(deviation_policy.get('persist_drift', True)))
        return {
            'ok': True,
            'portfolio_id': portfolio_id,
            'exception': exception_record,
            'approval': approval,
            'policy_baseline_drift': drift,
            'deviation_exceptions': refreshed.get('deviation_exceptions'),
            'summary': refreshed.get('summary'),
            'scope': refreshed.get('scope'),
        }

    def decide_runtime_alert_governance_portfolio_policy_deviation_exception(
        self,
        gw,
        *,
        approval_id: str,
        actor: str,
        decision: str,
        reason: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        approval = gw.audit.get_approval(approval_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if approval is None:
            return {'ok': False, 'error': 'approval_not_found', 'approval_id': str(approval_id or '').strip()}
        workflow_id = str(approval.get('workflow_id') or '')
        if not workflow_id.startswith('openclaw-governance-portfolio-deviation:'):
            return {'ok': False, 'error': 'unsupported_approval', 'approval_id': str(approval_id or '').strip()}
        portfolio_id = workflow_id.split(':', 1)[1]
        updated_approval = gw.audit.decide_approval(
            str(approval_id or '').strip(),
            decision=decision,
            decided_by=str(actor or '').strip(),
            reason=str(reason or '').strip(),
            tenant_id=approval.get('tenant_id'),
            workspace_id=approval.get('workspace_id'),
            environment=approval.get('environment'),
        )
        if updated_approval is None:
            return {'ok': False, 'error': 'approval_not_pending', 'approval_id': str(approval_id or '').strip()}
        release = gw.audit.get_release_bundle(portfolio_id, tenant_id=approval.get('tenant_id'), workspace_id=approval.get('workspace_id'), environment=approval.get('environment'))
        if release is None or not self._is_alert_governance_portfolio_release(release):
            return {'ok': False, 'error': 'governance_portfolio_not_found', 'approval': updated_approval, 'portfolio_id': portfolio_id}
        exceptions = [dict(item) for item in self._list_portfolio_policy_deviation_exceptions(release)]
        target_exception = None
        for item in exceptions:
            if str(item.get('approval_id') or '') == str(approval_id or ''):
                target_exception = item
                break
        if target_exception is None:
            return {'ok': False, 'error': 'portfolio_policy_deviation_exception_not_found', 'approval': updated_approval, 'portfolio_id': portfolio_id}
        now_ts = time.time()
        target_exception['status'] = 'approved' if str(updated_approval.get('status') or '') == 'approved' else 'rejected'
        target_exception['decided_at'] = now_ts
        target_exception['decided_by'] = str(actor or '').strip() or 'system'
        target_exception['decision_reason'] = str(reason or '').strip()
        if target_exception['status'] == 'approved':
            target_exception['approved_at'] = now_ts
            target_exception['approved_by'] = str(actor or '').strip() or 'system'
        updated_release = self._store_portfolio_policy_deviation_exceptions(gw, release=release, exceptions=exceptions, current_exception=target_exception)
        drift = self._portfolio_policy_baseline_drift_report(gw, release=updated_release, persist_metadata=True)
        refreshed = self._portfolio_detail_view(gw, release=updated_release)
        return {
            'ok': True,
            'portfolio_id': portfolio_id,
            'approval': updated_approval,
            'exception': target_exception,
            'policy_baseline_drift': drift,
            'deviation_exceptions': refreshed.get('deviation_exceptions'),
            'summary': refreshed.get('summary'),
            'scope': refreshed.get('scope'),
        }

    def detect_runtime_alert_governance_portfolio_drift(
        self,
        gw,
        *,
        portfolio_id: str,
        actor: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        persist_metadata: bool = True,
    ) -> dict[str, Any]:
        release = gw.audit.get_release_bundle(portfolio_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if release is None or not self._is_alert_governance_portfolio_release(release):
            return {'ok': False, 'error': 'governance_portfolio_not_found', 'portfolio_id': str(portfolio_id or '').strip()}
        simulation = self._simulate_portfolio_calendar(
            gw,
            release=release,
            actor=actor,
            dry_run=True,
            auto_reschedule=None,
            persist_metadata=False,
            persist_schedule=False,
        )
        drift = self._evaluate_portfolio_execution_drift(
            gw,
            release=release,
            actor=actor,
            simulation=simulation,
            persist_metadata=persist_metadata,
        )
        refreshed = gw.audit.get_release_bundle(portfolio_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment) or release
        return {'ok': True, 'portfolio_id': portfolio_id, 'drift': drift, 'simulation': simulation, 'release': refreshed, 'scope': self._scope(tenant_id=refreshed.get('tenant_id'), workspace_id=refreshed.get('workspace_id'), environment=refreshed.get('environment'))}

