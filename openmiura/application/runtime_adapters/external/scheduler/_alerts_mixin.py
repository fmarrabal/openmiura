"""scheduler._alerts_mixin

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


class _OpenClawRecoverySchedulerServiceAlertsMixin:
    """Sub-mixin: alerts."""

    def _finalize_runtime_alert_governance_version_activation(
        self,
        gw,
        *,
        runtime: dict[str, Any],
        version: dict[str, Any],
        actor: str,
        scope: dict[str, Any],
        reason: str = '',
        approval: dict[str, Any] | None = None,
        now_ts: float | None = None,
    ) -> dict[str, Any]:
        runtime_id = str(runtime.get('runtime_id') or version.get('runtime_id') or '').strip()
        version_id = str(version.get('version_id') or '').strip()
        version_no = int(version.get('version_no') or 0)
        policy = dict(version.get('policy') or {})
        runtime_metadata = dict(self.openclaw_adapter_service._runtime_metadata(runtime))
        previous_policy = dict(runtime_metadata.get('alert_governance_policy') or {})
        runtime_metadata['alert_governance_policy'] = policy
        release_policy = self._governance_release_policy(self.openclaw_adapter_service._build_runtime_summary(runtime))
        activated_at = float(now_ts if now_ts is not None else time.time())
        gw.audit.mark_runtime_governance_policy_versions(
            runtime_id=runtime_id,
            policy_kind='alert_governance',
            from_status='active',
            to_status='superseded',
            exclude_version_id=version_id,
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        )
        updated_runtime = gw.audit.upsert_openclaw_runtime(
            runtime_id=runtime_id,
            name=str(runtime.get('name') or ''),
            base_url=str(runtime.get('base_url') or ''),
            transport=str(runtime.get('transport') or 'http'),
            auth_secret_ref=str(runtime.get('auth_secret_ref') or ''),
            status=str(runtime.get('status') or 'registered'),
            capabilities=list(runtime.get('capabilities') or []),
            allowed_agents=list(runtime.get('allowed_agents') or []),
            metadata=runtime_metadata,
            created_by=str(actor or 'system'),
            **scope,
        )
        simulation = dict(version.get('simulation') or {})
        simulation['release'] = self._signed_governance_release(
            runtime_id=runtime_id,
            version_id=version_id,
            version_no=version_no,
            policy_kind='alert_governance',
            policy=policy,
            diff=dict(version.get('diff') or {}),
            actor=actor,
            release_policy=release_policy,
            activated_at=activated_at,
        )
        simulation['approval'] = {
            **dict(simulation.get('approval') or {}),
            'required': bool(approval),
            'status': str((approval or {}).get('status') or 'not_required'),
            'approval_id': str((approval or {}).get('approval_id') or ''),
            'decided_by': str((approval or {}).get('decided_by') or actor or ''),
            'decided_at': (approval or {}).get('decided_at') if approval else activated_at,
        }
        updated_version = gw.audit.update_runtime_governance_policy_version(
            version_id,
            status='active',
            activated_at=activated_at,
            activation_reason=str(reason or version.get('activation_reason') or '').strip(),
            simulation=simulation,
        ) or version
        gw.audit.log_event('system', 'broker', str(actor or 'system'), 'system', {
            'action': 'openclaw_alert_governance_activated',
            'runtime_id': runtime_id,
            'version_id': version_id,
            'version_no': version_no,
            'reason': str(reason or version.get('activation_reason') or '').strip(),
            'approval_id': str((approval or {}).get('approval_id') or ''),
            'signature': dict(simulation.get('release') or {}).get('signature'),
        }, **scope)
        return {
            'ok': True,
            'runtime_id': runtime_id,
            'runtime': updated_runtime,
            'runtime_summary': self.openclaw_adapter_service._build_runtime_summary(updated_runtime),
            'version': self._runtime_alert_governance_version_view(updated_version),
            'scope': scope,
        }

    def simulate_runtime_alert_governance(
        self,
        gw,
        *,
        runtime_id: str,
        candidate_policy: dict[str, Any] | None = None,
        merge_with_current: bool = True,
        alert_code: str | None = None,
        include_unchanged: bool = True,
        limit: int = 200,
        now_ts: float | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        alerts_payload = self.evaluate_runtime_alerts(
            gw,
            runtime_id=runtime_id,
            limit=limit,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        if not alerts_payload.get('ok'):
            return alerts_payload
        runtime_summary = dict(alerts_payload.get('runtime_summary') or {})
        scope = dict(alerts_payload.get('scope') or {})
        scope_with_runtime = {
            **scope,
            'runtime_class': str((((runtime_summary.get('metadata') or {}).get('runtime_class')) or '')).strip(),
        }
        current_raw = dict(runtime_summary.get('alert_governance_policy') or {})
        patch = dict(candidate_policy or {})
        candidate_raw = self.openclaw_adapter_service._deep_merge(current_raw, patch) if merge_with_current else patch
        candidate_runtime_summary = dict(runtime_summary)
        candidate_runtime_summary['alert_governance_policy'] = candidate_raw
        baseline_policy = self._effective_alert_governance_policy(runtime_summary=runtime_summary, scope=scope_with_runtime)
        simulated_policy = self._effective_alert_governance_policy(runtime_summary=candidate_runtime_summary, scope=scope_with_runtime)
        now_value = float(now_ts if now_ts is not None else time.time())
        active_alerts = [dict(item) for item in list(alerts_payload.get('items') or [])]
        selected_code = str(alert_code or '').strip()
        items: list[dict[str, Any]] = []
        affected_count = 0
        for raw_alert in active_alerts:
            code = str(raw_alert.get('code') or '').strip()
            if selected_code and code != selected_code:
                continue
            base_alert = dict(raw_alert)
            baseline_decision = self._alert_governance_decision(
                runtime_summary=runtime_summary,
                scope=scope,
                alert=base_alert,
                alerts=active_alerts,
                now_ts=now_value,
            )
            candidate_decision = self._alert_governance_decision(
                runtime_summary=candidate_runtime_summary,
                scope=scope,
                alert=base_alert,
                alerts=active_alerts,
                now_ts=now_value,
            )
            change_summary = self._governance_decision_change_summary(baseline_decision, candidate_decision)
            if not include_unchanged and not bool(change_summary.get('affected')):
                continue
            if bool(change_summary.get('affected')):
                affected_count += 1
            items.append({
                'alert': {
                    'code': code,
                    'title': str(raw_alert.get('title') or code),
                    'severity': str(raw_alert.get('severity') or ''),
                    'category': str(raw_alert.get('category') or ''),
                    'message': str(raw_alert.get('message') or ''),
                    'observed_at': raw_alert.get('observed_at'),
                    'scope': dict(raw_alert.get('scope') or {}),
                },
                'baseline': {
                    'decision': baseline_decision,
                    'explain': self._governance_explain_view(baseline_decision),
                },
                'candidate': {
                    'decision': candidate_decision,
                    'explain': self._governance_explain_view(candidate_decision),
                },
                'change_summary': change_summary,
            })
        counts = {
            'allow': 0,
            'scheduled': 0,
            'suppressed': 0,
        }
        for item in items:
            status = str((((item.get('candidate') or {}).get('decision') or {}).get('status')) or 'allow').strip().lower() or 'allow'
            counts[status] = counts.get(status, 0) + 1
        summary = {
            'alert_count': len(active_alerts) if not selected_code else len([item for item in active_alerts if str(item.get('code') or '').strip() == selected_code]),
            'evaluated_count': len(items),
            'affected_count': affected_count,
            'unchanged_count': max(0, len(items) - affected_count) if include_unchanged else max(0, len(active_alerts) - affected_count),
            'candidate_status_counts': counts,
            'newly_suppressed_count': sum(1 for item in items if bool((item.get('change_summary') or {}).get('newly_suppressed'))),
            'newly_scheduled_count': sum(1 for item in items if bool((item.get('change_summary') or {}).get('newly_scheduled'))),
            'newly_allowed_count': sum(1 for item in items if bool((item.get('change_summary') or {}).get('newly_allowed'))),
        }
        return {
            'ok': True,
            'mode': 'dry-run',
            'runtime_id': runtime_id,
            'runtime_summary': runtime_summary,
            'scope': scope,
            'baseline_policy': baseline_policy,
            'candidate_policy': simulated_policy,
            'policy_diff': self._policy_diff_view(baseline_policy, simulated_policy),
            'items': items,
            'summary': summary,
        }

    def _runtime_alert_governance_version_view(self, item: dict[str, Any] | None) -> dict[str, Any]:
        record = dict(item or {})
        simulation = dict(record.get('simulation') or {})
        summary = dict(simulation.get('summary') or {})
        diff = dict(record.get('diff') or {})
        return {
            **record,
            'summary': {
                'affected_count': int(summary.get('affected_count') or 0),
                'newly_suppressed_count': int(summary.get('newly_suppressed_count') or 0),
                'newly_scheduled_count': int(summary.get('newly_scheduled_count') or 0),
                'newly_allowed_count': int(summary.get('newly_allowed_count') or 0),
                'changed': bool(diff.get('changed')),
                'changed_keys': list(diff.get('changed_keys') or []),
            },
            'release': dict(simulation.get('release') or {}),
            'approval': dict(simulation.get('approval') or {}),
            'bundle': dict(simulation.get('bundle') or {}),
        }

    def list_runtime_alert_governance_versions(
        self,
        gw,
        *,
        runtime_id: str,
        limit: int = 50,
        status: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        scope = self._scope(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        items = [
            self._runtime_alert_governance_version_view(item)
            for item in gw.audit.list_runtime_governance_policy_versions(
                runtime_id=runtime_id,
                policy_kind='alert_governance',
                status=status,
                limit=limit,
                tenant_id=scope.get('tenant_id'),
                workspace_id=scope.get('workspace_id'),
                environment=scope.get('environment'),
            )
        ]
        status_counts: dict[str, int] = {}
        change_kind_counts: dict[str, int] = {}
        for item in items:
            status_key = str(item.get('status') or 'active')
            change_key = str(item.get('change_kind') or 'activation')
            status_counts[status_key] = status_counts.get(status_key, 0) + 1
            change_kind_counts[change_key] = change_kind_counts.get(change_key, 0) + 1
        current = next((item for item in items if str(item.get('status') or '') == 'active'), None)
        return {
            'ok': True,
            'runtime_id': runtime_id,
            'items': items,
            'current_version': current,
            'summary': {
                'count': len(items),
                'status_counts': status_counts,
                'change_kind_counts': change_kind_counts,
                'current_version_id': current.get('version_id') if current else None,
                'current_version_no': current.get('version_no') if current else None,
            },
            'scope': scope,
        }

    def activate_runtime_alert_governance(
        self,
        gw,
        *,
        runtime_id: str,
        actor: str,
        candidate_policy: dict[str, Any] | None = None,
        merge_with_current: bool = True,
        reason: str = '',
        alert_code: str | None = None,
        include_unchanged: bool = True,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        limit: int = 200,
        now_ts: float | None = None,
        release_bundle_id: str | None = None,
        release_wave_id: str | None = None,
        release_wave_no: int | None = None,
        release_wave_label: str | None = None,
    ) -> dict[str, Any]:
        detail = self.openclaw_adapter_service.get_runtime(gw, runtime_id=runtime_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if not detail.get('ok'):
            return detail
        runtime = dict(detail.get('runtime') or {})
        scope = self._scope(
            tenant_id=tenant_id or runtime.get('tenant_id'),
            workspace_id=workspace_id or runtime.get('workspace_id'),
            environment=environment or runtime.get('environment'),
        )
        simulation = self.simulate_runtime_alert_governance(
            gw,
            runtime_id=runtime_id,
            candidate_policy=candidate_policy,
            merge_with_current=merge_with_current,
            alert_code=alert_code,
            include_unchanged=include_unchanged,
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
            limit=limit,
            now_ts=now_ts,
        )
        if not simulation.get('ok'):
            return simulation
        previous_policy = dict(self.openclaw_adapter_service._runtime_metadata(runtime).get('alert_governance_policy') or {})
        candidate_effective = dict(simulation.get('candidate_policy') or {})
        candidate_raw = self.openclaw_adapter_service._deep_merge(previous_policy, dict(candidate_policy or {})) if merge_with_current else dict(candidate_policy or {})
        current_version = gw.audit.latest_runtime_governance_policy_version(
            runtime_id=runtime_id,
            policy_kind='alert_governance',
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        )
        next_version_no = int((current_version or {}).get('version_no') or 0) + 1
        version_id = f'gov-{runtime_id}-{next_version_no}-{uuid.uuid4().hex[:8]}'
        release_policy = self._governance_release_policy(detail.get('runtime_summary') or self.openclaw_adapter_service._build_runtime_summary(runtime))
        needs_approval, approval_reasons = self._governance_promotion_requires_approval(release_policy=release_policy, simulation=simulation)
        activated_at = float(now_ts if now_ts is not None else time.time())
        release_state = {
            'release_id': f'govrel-{runtime_id}-{next_version_no}',
            'policy_kind': 'alert_governance',
            'version_id': version_id,
            'version_no': next_version_no,
            'status': 'pending_approval' if needs_approval else 'active',
            'signed': False,
            'signature': None,
            'signer_key_id': str(release_policy.get('signer_key_id') or 'openmiura-local'),
            'signed_by': None,
            'signed_at': None,
        }
        bundle_context = {
            'release_bundle_id': str(release_bundle_id or '').strip(),
            'release_wave_id': str(release_wave_id or '').strip(),
            'release_wave_no': int(release_wave_no or 0),
            'release_wave_label': str(release_wave_label or '').strip(),
        }
        if not bundle_context['release_bundle_id']:
            bundle_context = {}
        simulation_record = {
            'summary': dict(simulation.get('summary') or {}),
            'candidate_policy': candidate_effective,
            'baseline_policy': dict(simulation.get('baseline_policy') or {}),
            'release_policy': release_policy,
            'release': release_state,
            'approval': {
                'required': needs_approval,
                'status': 'pending' if needs_approval else 'not_required',
                'reasons': approval_reasons,
                'approval_id': '',
            },
            'bundle': bundle_context,
        }
        version = gw.audit.create_runtime_governance_policy_version(
            version_id=version_id,
            runtime_id=runtime_id,
            policy_kind='alert_governance',
            version_no=next_version_no,
            version_label=f'alert-governance-v{next_version_no}',
            change_kind='activation',
            status='pending_approval' if needs_approval else 'active',
            based_on_version_id=str((current_version or {}).get('version_id') or ''),
            activated_by=str(actor or 'system'),
            activation_reason=str(reason or '').strip(),
            policy=candidate_raw,
            previous_policy=previous_policy,
            diff=dict(simulation.get('policy_diff') or {}),
            simulation=simulation_record,
            activated_at=None if needs_approval else activated_at,
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        )
        if needs_approval:
            workflow_id = f'openclaw-governance-promotion:{runtime_id}'
            step_id = f'activate:{version_id}'
            approval = self._ensure_step_approval_request(
                gw,
                workflow_id=workflow_id,
                step_id=step_id,
                requested_role=str(release_policy.get('requested_role') or 'admin'),
                requested_by=str(actor or 'system'),
                payload={
                    'kind': 'openclaw_governance_promotion',
                    'runtime_id': runtime_id,
                    'version_id': version_id,
                    'release_id': release_state['release_id'],
                    'tenant_id': scope.get('tenant_id'),
                    'workspace_id': scope.get('workspace_id'),
                    'environment': scope.get('environment'),
                    'reason': str(reason or '').strip(),
                    'policy_kind': 'alert_governance',
                    'bundle': bundle_context,
                },
                expires_at=activated_at + float(release_policy.get('ttl_s') or 3600),
                tenant_id=scope.get('tenant_id'),
                workspace_id=scope.get('workspace_id'),
                environment=scope.get('environment'),
            )
            simulation_record['approval'] = {
                **dict(simulation_record.get('approval') or {}),
                'approval_id': str((approval or {}).get('approval_id') or ''),
                'requested_role': str((approval or {}).get('requested_role') or release_policy.get('requested_role') or 'admin'),
                'expires_at': (approval or {}).get('expires_at'),
            }
            version = gw.audit.update_runtime_governance_policy_version(version_id, status='pending_approval', simulation=simulation_record) or version
            gw.audit.log_event('system', 'broker', str(actor or 'system'), 'system', {
                'action': 'openclaw_alert_governance_activation_pending_approval',
                'runtime_id': runtime_id,
                'version_id': version_id,
                'version_no': next_version_no,
                'reason': str(reason or '').strip(),
                'approval_id': str((approval or {}).get('approval_id') or ''),
                'approval_reasons': approval_reasons,
            }, **scope)
            return {
                'ok': True,
                'approval_required': True,
                'runtime_id': runtime_id,
                'runtime': runtime,
                'runtime_summary': detail.get('runtime_summary') or self.openclaw_adapter_service._build_runtime_summary(runtime),
                'version': self._runtime_alert_governance_version_view(version),
                'simulation': simulation,
                'approval': approval,
                'scope': scope,
            }
        finalized = self._finalize_runtime_alert_governance_version_activation(
            gw,
            runtime=runtime,
            version=version,
            actor=actor,
            scope=scope,
            reason=str(reason or '').strip(),
            approval=None,
            now_ts=activated_at,
        )
        return {
            **finalized,
            'activation': {
                'mode': 'activate',
                'version_id': version_id,
                'version_no': next_version_no,
                'reason': str(reason or '').strip(),
                'affected_count': int((simulation.get('summary') or {}).get('affected_count') or 0),
            },
            'simulation': simulation,
        }

    def rollback_runtime_alert_governance_version(
        self,
        gw,
        *,
        runtime_id: str,
        version_id: str,
        actor: str,
        reason: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        detail = self.openclaw_adapter_service.get_runtime(gw, runtime_id=runtime_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if not detail.get('ok'):
            return detail
        runtime = dict(detail.get('runtime') or {})
        scope = self._scope(
            tenant_id=tenant_id or runtime.get('tenant_id'),
            workspace_id=workspace_id or runtime.get('workspace_id'),
            environment=environment or runtime.get('environment'),
        )
        target = gw.audit.get_runtime_governance_policy_version(
            version_id,
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        )
        if target is None or str(target.get('runtime_id') or '').strip() != str(runtime_id or '').strip():
            return {'ok': False, 'error': 'governance_version_not_found', 'runtime_id': runtime_id, 'version_id': version_id, 'scope': scope}
        restore_policy = dict(target.get('previous_policy') or {})
        current_policy = dict(self.openclaw_adapter_service._runtime_metadata(runtime).get('alert_governance_policy') or {})
        current_version = gw.audit.latest_runtime_governance_policy_version(
            runtime_id=runtime_id,
            policy_kind='alert_governance',
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        )
        next_version_no = int((current_version or {}).get('version_no') or 0) + 1
        new_version_id = f'gov-{runtime_id}-{next_version_no}-{uuid.uuid4().hex[:8]}'
        updated_metadata = dict(self.openclaw_adapter_service._runtime_metadata(runtime))
        updated_metadata['alert_governance_policy'] = restore_policy
        gw.audit.mark_runtime_governance_policy_versions(
            runtime_id=runtime_id,
            policy_kind='alert_governance',
            from_status='active',
            to_status='superseded',
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        )
        updated = gw.audit.upsert_openclaw_runtime(
            runtime_id=str(runtime.get('runtime_id') or runtime_id),
            name=str(runtime.get('name') or ''),
            base_url=str(runtime.get('base_url') or ''),
            transport=str(runtime.get('transport') or 'http'),
            auth_secret_ref=str(runtime.get('auth_secret_ref') or ''),
            status=str(runtime.get('status') or 'registered'),
            capabilities=list(runtime.get('capabilities') or []),
            allowed_agents=list(runtime.get('allowed_agents') or []),
            metadata=updated_metadata,
            created_by=str(actor or 'system'),
            **scope,
        )
        rollback_version = gw.audit.create_runtime_governance_policy_version(
            version_id=new_version_id,
            runtime_id=runtime_id,
            policy_kind='alert_governance',
            version_no=next_version_no,
            version_label=f'alert-governance-v{next_version_no}',
            change_kind='rollback',
            status='active',
            based_on_version_id=str((current_version or {}).get('version_id') or ''),
            rollback_of_version_id=str(version_id or '').strip(),
            activated_by=str(actor or 'system'),
            activation_reason=str(reason or '').strip(),
            policy=restore_policy,
            previous_policy=current_policy,
            diff=self._policy_diff_view(current_policy, restore_policy),
            simulation={
                'summary': {
                    'affected_count': 0,
                    'rollback_of_version_id': str(version_id or '').strip(),
                },
                'restored_from_version_id': str(version_id or '').strip(),
            },
            activated_at=time.time(),
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        )
        gw.audit.log_event('system', 'broker', str(actor or 'system'), 'system', {
            'action': 'openclaw_alert_governance_rolled_back',
            'runtime_id': runtime_id,
            'version_id': new_version_id,
            'rollback_of_version_id': str(version_id or '').strip(),
            'reason': str(reason or '').strip(),
        }, **scope)
        return {
            'ok': True,
            'runtime_id': runtime_id,
            'runtime': updated,
            'runtime_summary': self.openclaw_adapter_service._build_runtime_summary(updated),
            'rollback': {
                'mode': 'rollback',
                'version_id': new_version_id,
                'rollback_of_version_id': str(version_id or '').strip(),
                'reason': str(reason or '').strip(),
            },
            'version': self._runtime_alert_governance_version_view(rollback_version),
            'restored_version': self._runtime_alert_governance_version_view(target),
            'scope': scope,
        }

