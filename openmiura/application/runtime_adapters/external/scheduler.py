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
from .service import OpenClawAdapterService
from .baseline_rollout_management import OpenClawBaselineRolloutManagementMixin
from .baseline_rollout_support import OpenClawBaselineRolloutSupportMixin
from .baseline_rollout_state import OpenClawBaselineRolloutStateMixin
from .baseline_rollout_jobs import OpenClawBaselineRolloutJobsMixin
from .baseline_rollout_gates import OpenClawBaselineRolloutGatesMixin
from .alert_governance_bundle_management import OpenClawAlertGovernanceBundleManagementMixin
from .alert_governance_bundle_jobs import OpenClawAlertGovernanceBundleJobsMixin
from .alert_governance_bundle_gates import OpenClawAlertGovernanceBundleGatesMixin
from .policy_normalization import OpenClawPolicyNormalizationMixin
from .evidence_builders import OpenClawEvidenceBuildersMixin
from .runtime_rollout_summaries import OpenClawRuntimeRolloutSummariesMixin
from .runtime_alert_common import OpenClawRuntimeAlertCommonMixin
from .runtime_alert_execution import OpenClawRuntimeAlertExecutionMixin
from .runtime_alert_notifications import OpenClawRuntimeAlertNotificationsMixin
from .runtime_alert_escalations import OpenClawRuntimeAlertEscalationsMixin
from .temporal_windows import OpenClawTemporalWindowsMixin
from .job_family_common import OpenClawJobFamilyCommonMixin
from .runtime_context import OpenClawRuntimeContextMixin
from .approval_common import OpenClawApprovalCommonMixin
from .governance_explainability import OpenClawGovernanceExplainabilityMixin
from .scheduler_primitives import (
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


class OpenClawRecoverySchedulerService(
    OpenClawRuntimeContextMixin,
    OpenClawApprovalCommonMixin,
    OpenClawGovernanceExplainabilityMixin,
    OpenClawJobFamilyCommonMixin,
    OpenClawTemporalWindowsMixin,
    OpenClawRuntimeAlertCommonMixin,
    OpenClawRuntimeAlertEscalationsMixin,
    OpenClawRuntimeAlertNotificationsMixin,
    OpenClawRuntimeAlertExecutionMixin,
    OpenClawPolicyNormalizationMixin,
    OpenClawEvidenceBuildersMixin,
    OpenClawRuntimeRolloutSummariesMixin,
    OpenClawBaselineRolloutManagementMixin,
    OpenClawBaselineRolloutSupportMixin,
    OpenClawBaselineRolloutStateMixin,
    OpenClawBaselineRolloutJobsMixin,
    OpenClawBaselineRolloutGatesMixin,
    OpenClawAlertGovernanceBundleManagementMixin,
    OpenClawAlertGovernanceBundleJobsMixin,
    OpenClawAlertGovernanceBundleGatesMixin,
):
    """Periodic scheduler/worker for stale-run reconciliation on OpenClaw runtimes."""

    JOB_KIND = 'openclaw_runtime_recovery'
    ALERT_DELIVERY_JOB_KIND = 'openclaw_alert_delivery'
    GOVERNANCE_WAVE_ADVANCE_JOB_KIND = 'openclaw_alert_governance_wave_advance'
    GOVERNANCE_RELEASE_TRAIN_JOB_KIND = 'openclaw_alert_governance_release_train'
    BASELINE_WAVE_ADVANCE_JOB_KIND = 'openclaw_alert_governance_baseline_wave_advance'
    BASELINE_SIMULATION_CUSTODY_JOB_KIND = 'openclaw_alert_governance_baseline_simulation_custody_reconciliation'

    def __init__(
        self,
        *,
        openclaw_adapter_service: OpenClawAdapterService | None = None,
        job_service: JobService | None = None,
    ) -> None:
        self.openclaw_adapter_service = openclaw_adapter_service or OpenClawAdapterService()
        self.job_service = job_service or JobService()

    @staticmethod
    def _scope(*, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any]:
        return scheduler_scope(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    @classmethod
    def _is_recovery_job(cls, item: dict[str, Any] | None, *, runtime_id: str | None = None) -> bool:
        return is_workflow_job(item, kind=cls.JOB_KIND, field_name='runtime_id' if runtime_id is not None else None, field_value=runtime_id)

    @staticmethod
    def _job_definition(
        *,
        runtime_id: str,
        actor: str,
        limit: int,
        reason: str,
        scheduler_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return recovery_job_definition(
            runtime_id=runtime_id,
            actor=actor,
            limit=limit,
            reason=reason,
            scheduler_policy=scheduler_policy,
            kind=OpenClawRecoverySchedulerService.JOB_KIND,
        )

    @classmethod
    def _is_alert_delivery_job(cls, item: dict[str, Any] | None, *, runtime_id: str | None = None) -> bool:
        return is_workflow_job(item, kind=cls.ALERT_DELIVERY_JOB_KIND, field_name='runtime_id' if runtime_id is not None else None, field_value=runtime_id)

    @staticmethod
    def _alert_delivery_job_definition(
        *,
        runtime_id: str,
        alert_code: str,
        workflow_action: str,
        actor: str,
        target: dict[str, Any],
        reason: str,
        escalation_level: int,
        attempt_no: int = 0,
        notification_dispatch_id: str = '',
        route: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return alert_delivery_job_definition(
            runtime_id=runtime_id,
            alert_code=alert_code,
            workflow_action=workflow_action,
            actor=actor,
            target=target,
            reason=reason,
            escalation_level=escalation_level,
            attempt_no=attempt_no,
            notification_dispatch_id=notification_dispatch_id,
            route=route,
            kind=OpenClawRecoverySchedulerService.ALERT_DELIVERY_JOB_KIND,
        )

    @classmethod
    def _is_governance_wave_advance_job(cls, item: dict[str, Any] | None, *, bundle_id: str | None = None) -> bool:
        return is_workflow_job(item, kind=cls.GOVERNANCE_WAVE_ADVANCE_JOB_KIND, field_name='bundle_id' if bundle_id is not None else None, field_value=bundle_id)

    @staticmethod
    def _governance_wave_advance_job_definition(
        *,
        bundle_id: str,
        source_wave_no: int,
        next_wave_no: int | None,
        actor: str,
        reason: str,
    ) -> dict[str, Any]:
        return governance_wave_advance_job_definition(
            bundle_id=bundle_id,
            source_wave_no=source_wave_no,
            next_wave_no=next_wave_no,
            actor=actor,
            reason=reason,
            kind=OpenClawRecoverySchedulerService.GOVERNANCE_WAVE_ADVANCE_JOB_KIND,
        )

    @staticmethod
    def _governance_wave_job_id(bundle_id: str, source_wave_no: int) -> str:
        return governance_wave_job_id(bundle_id, source_wave_no)

    @classmethod
    def _is_baseline_wave_advance_job(cls, item: dict[str, Any] | None, *, promotion_id: str | None = None) -> bool:
        return is_workflow_job(item, kind=cls.BASELINE_WAVE_ADVANCE_JOB_KIND, field_name='promotion_id' if promotion_id is not None else None, field_value=promotion_id)

    @staticmethod
    def _baseline_wave_advance_job_definition(
        *,
        promotion_id: str,
        source_wave_no: int,
        next_wave_no: int | None,
        actor: str,
        reason: str,
    ) -> dict[str, Any]:
        return baseline_wave_advance_job_definition(
            promotion_id=promotion_id,
            source_wave_no=source_wave_no,
            next_wave_no=next_wave_no,
            actor=actor,
            reason=reason,
            kind=OpenClawRecoverySchedulerService.BASELINE_WAVE_ADVANCE_JOB_KIND,
        )

    @staticmethod
    def _baseline_wave_job_id(promotion_id: str, source_wave_no: int) -> str:
        return baseline_wave_job_id(promotion_id, source_wave_no)

    @classmethod
    def _is_baseline_simulation_custody_job(cls, item: dict[str, Any] | None, *, promotion_id: str | None = None) -> bool:
        return is_workflow_job(item, kind=cls.BASELINE_SIMULATION_CUSTODY_JOB_KIND, field_name='promotion_id' if promotion_id is not None else None, field_value=promotion_id)

    @staticmethod
    def _baseline_simulation_custody_job_definition(
        *,
        promotion_id: str,
        actor: str,
        interval_s: int,
        reason: str,
    ) -> dict[str, Any]:
        return baseline_simulation_custody_job_definition(
            promotion_id=promotion_id,
            actor=actor,
            interval_s=interval_s,
            reason=reason,
            kind=OpenClawRecoverySchedulerService.BASELINE_SIMULATION_CUSTODY_JOB_KIND,
        )

    @staticmethod
    def _baseline_simulation_custody_job_id(promotion_id: str) -> str:
        return baseline_simulation_custody_job_id(promotion_id)

    @staticmethod
    def _holder_id(actor: str) -> str:
        return holder_id(actor)

    @staticmethod
    def _scheduler_policy(item: dict[str, Any] | None) -> dict[str, Any]:
        return scheduler_policy(item)

    @staticmethod
    def _due_slot(item: dict[str, Any] | None, *, now: float | None = None) -> int:
        return due_slot(item, now=now)

    @staticmethod
    def _job_lease_key(job_id: str) -> str:
        return job_lease_key(job_id)

    @staticmethod
    def _runtime_lease_key(runtime_id: str) -> str:
        return runtime_lease_key(runtime_id)

    @classmethod
    def _workspace_lease_prefix(cls, scope: dict[str, Any]) -> str:
        return workspace_lease_prefix(scope)

    @classmethod
    def _workspace_lease_keys(cls, scope: dict[str, Any], *, limit: int) -> list[str]:
        return workspace_lease_keys(scope, limit=limit)

    @staticmethod
    def _job_idempotency_key(job_id: str, due_slot: int) -> str:
        return job_idempotency_key(job_id, due_slot)

    @staticmethod
    def _lease_type(lease_key: str) -> str:
        return lease_type(lease_key)

    @staticmethod
    def _decorate_worker_lease(item: dict[str, Any] | None, *, now: float | None = None) -> dict[str, Any]:
        return decorate_worker_lease(item, now=now)

    @staticmethod
    def _decorate_idempotency_record(item: dict[str, Any] | None, *, now: float | None = None) -> dict[str, Any]:
        return decorate_idempotency_record(item, now=now)


    @staticmethod
    def _alert_key(runtime_id: str, alert_code: str) -> str:
        return f'openclaw-alert:{str(runtime_id or "").strip()}:{str(alert_code or "").strip()}'





    @staticmethod
    def _scope_matches(match: dict[str, Any] | None, scope: dict[str, Any] | None) -> bool:
        criteria = dict(match or {})
        current = dict(scope or {})
        for key in ('tenant_id', 'workspace_id', 'environment', 'runtime_class'):
            expected = criteria.get(key)
            if expected in (None, '', []):
                continue
            if str(current.get(key) or '').strip() != str(expected).strip():
                return False
        return True


    @classmethod
    def _quiet_hours_decision(cls, *, policy: dict[str, Any], alert: dict[str, Any], now_ts: float) -> dict[str, Any]:
        quiet = dict(policy.get('quiet_hours') or {})
        if not bool(quiet.get('enabled')):
            return {'active': False, 'suppressed': False, 'scheduled': False, 'reasons': [], 'next_allowed_at': None, 'window': {}}
        severity = str(alert.get('severity') or '').strip().lower()
        code = str(alert.get('code') or '').strip()
        if severity and severity in set(quiet.get('allow_severities') or []):
            return {'active': False, 'suppressed': False, 'scheduled': False, 'reasons': [], 'next_allowed_at': None, 'window': {'bypass': 'severity'}}
        if code and code in set(quiet.get('allow_alert_codes') or []):
            return {'active': False, 'suppressed': False, 'scheduled': False, 'reasons': [], 'next_allowed_at': None, 'window': {'bypass': 'alert_code'}}
        state = cls._recurring_window_state(weekdays=list(quiet.get('weekdays') or []), start_time=str(quiet.get('start_time') or '22:00'), end_time=str(quiet.get('end_time') or '06:00'), timezone_name=str(quiet.get('timezone') or policy.get('default_timezone') or 'UTC'), now_ts=now_ts)
        if not bool(state.get('active')):
            return {'active': False, 'suppressed': False, 'scheduled': False, 'reasons': [], 'next_allowed_at': None, 'window': state}
        action = str(quiet.get('action') or 'schedule').strip().lower() or 'schedule'
        next_allowed_at = state.get('active_until') if action == 'schedule' else float(now_ts) + float(quiet.get('suppress_for_s') or 900)
        return {'active': True, 'suppressed': action == 'suppress', 'scheduled': action == 'schedule', 'reasons': ['quiet_hours'], 'next_allowed_at': next_allowed_at, 'window': state, 'action': action}

    @classmethod
    def _maintenance_decision(cls, *, policy: dict[str, Any], alert: dict[str, Any], now_ts: float) -> dict[str, Any]:
        severity = str(alert.get('severity') or '').strip().lower()
        code = str(alert.get('code') or '').strip()
        active_windows: list[dict[str, Any]] = []
        suppressed = False
        scheduled = False
        next_allowed_at = None
        for window in list(policy.get('maintenance_windows') or []):
            if not bool(window.get('enabled', True)):
                continue
            allowed_severities = [str(item).strip().lower() for item in list(window.get('allow_severities') or []) if str(item).strip()]
            allowed_codes = [str(item).strip() for item in list(window.get('allow_alert_codes') or []) if str(item).strip()]
            if severity and severity in set(allowed_severities):
                continue
            if code and code in set(allowed_codes):
                continue
            if window.get('starts_at') is not None and window.get('ends_at') is not None:
                state = cls._absolute_window_state(starts_at=window.get('starts_at'), ends_at=window.get('ends_at'), now_ts=now_ts)
            else:
                state = cls._recurring_window_state(weekdays=list(window.get('weekdays') or window.get('days') or []), start_time=str(window.get('start_time') or '00:00'), end_time=str(window.get('end_time') or '23:59'), timezone_name=str(window.get('timezone') or policy.get('default_timezone') or 'UTC'), now_ts=now_ts)
            if not bool(state.get('active')):
                continue
            action = str(window.get('action') or 'suppress').strip().lower() or 'suppress'
            window_view = {**dict(window), 'state': state, 'action': action}
            active_windows.append(window_view)
            if action == 'suppress':
                suppressed = True
                next_allowed_at = max(float(next_allowed_at or 0.0), float(state.get('active_until') or 0.0)) if state.get('active_until') else next_allowed_at
            elif action == 'schedule' and not suppressed:
                scheduled = True
                next_allowed_at = max(float(next_allowed_at or 0.0), float(state.get('active_until') or 0.0)) if state.get('active_until') else next_allowed_at
        return {'active': bool(active_windows), 'suppressed': suppressed, 'scheduled': scheduled and not suppressed, 'reasons': ['maintenance_window'] if active_windows else [], 'next_allowed_at': next_allowed_at, 'windows': active_windows}

    @classmethod
    def _storm_decision(cls, *, policy: dict[str, Any], alert: dict[str, Any], alerts: list[dict[str, Any]], now_ts: float) -> dict[str, Any]:
        storm = dict(policy.get('storm_policy') or {})
        if not bool(storm.get('enabled')):
            return {'active': False, 'suppressed': False, 'scheduled': False, 'reasons': [], 'next_allowed_at': None, 'summary': {}}
        code = str(alert.get('code') or '').strip()
        if code and code in set(storm.get('allow_alert_codes') or []):
            return {'active': False, 'suppressed': False, 'scheduled': False, 'reasons': [], 'next_allowed_at': None, 'summary': {'bypass': 'alert_code'}}
        severity = str(alert.get('severity') or '').strip().lower()
        suppressible = severity in set(storm.get('suppress_severities') or [])
        active_alert_threshold = int(storm.get('active_alert_threshold') or 0)
        severity_counts: dict[str, int] = {}
        code_counts: dict[str, int] = {}
        for item in list(alerts or []):
            sev_key = str(item.get('severity') or '').strip().lower() or 'warn'
            severity_counts[sev_key] = severity_counts.get(sev_key, 0) + 1
            code_key = str(item.get('code') or '').strip() or 'runtime_alert'
            code_counts[code_key] = code_counts.get(code_key, 0) + 1
        active = False
        if active_alert_threshold and len(list(alerts or [])) >= active_alert_threshold:
            active = True
        per_severity = dict(storm.get('per_severity_thresholds') or {})
        if severity and int(per_severity.get(severity) or 0) > 0 and severity_counts.get(severity, 0) >= int(per_severity.get(severity) or 0):
            active = True
        if not active or not suppressible:
            return {'active': active, 'suppressed': False, 'scheduled': False, 'reasons': ['alert_storm'] if active else [], 'next_allowed_at': None, 'summary': {'severity_counts': severity_counts, 'code_counts': code_counts, 'alert_count': len(list(alerts or []))}}
        action = str(storm.get('action') or 'suppress').strip().lower() or 'suppress'
        next_allowed_at = float(now_ts) + float(storm.get('suppress_for_s') or 600)
        return {'active': True, 'suppressed': action == 'suppress', 'scheduled': action == 'schedule', 'reasons': ['alert_storm'], 'next_allowed_at': next_allowed_at, 'summary': {'severity_counts': severity_counts, 'code_counts': code_counts, 'alert_count': len(list(alerts or []))}, 'action': action}


    @staticmethod
    def _policy_diff_view(baseline: dict[str, Any] | None, candidate: dict[str, Any] | None) -> dict[str, Any]:
        before = dict(baseline or {})
        after = dict(candidate or {})
        keys = sorted(set(before.keys()) | set(after.keys()))
        changed_keys = [key for key in keys if before.get(key) != after.get(key)]
        return {
            'changed': bool(changed_keys),
            'changed_keys': changed_keys,
            'baseline_signature': json.dumps(before, sort_keys=True, ensure_ascii=False),
            'candidate_signature': json.dumps(after, sort_keys=True, ensure_ascii=False),
        }



    @classmethod
    def _governance_promotion_requires_approval(cls, *, release_policy: dict[str, Any], simulation: dict[str, Any]) -> tuple[bool, list[str]]:
        reasons: list[str] = []
        if bool(release_policy.get('approval_required')):
            reasons.append('approval_required')
        summary = dict(simulation.get('summary') or {})
        affected_count = int(summary.get('affected_count') or 0)
        threshold = int(release_policy.get('approval_on_affected_count_ge') or 0)
        if threshold > 0 and affected_count >= threshold:
            reasons.append(f'affected_count>={threshold}')
        changed_keys = set(dict(simulation.get('policy_diff') or {}).get('changed_keys') or [])
        critical_keys = set(release_policy.get('critical_changed_keys') or [])
        matched_keys = sorted(changed_keys & critical_keys)
        if bool(release_policy.get('approval_on_critical_change')) and matched_keys:
            reasons.append('critical_keys:' + ','.join(matched_keys))
        return (bool(reasons), reasons)

    @staticmethod
    def _governance_release_signature(*, runtime_id: str, version_id: str, version_no: int, policy_kind: str, policy: dict[str, Any], diff: dict[str, Any], signer_key_id: str) -> str:
        payload = {
            'runtime_id': str(runtime_id or '').strip(),
            'version_id': str(version_id or '').strip(),
            'version_no': int(version_no or 0),
            'policy_kind': str(policy_kind or 'alert_governance').strip(),
            'policy': dict(policy or {}),
            'diff': dict(diff or {}),
            'signer_key_id': str(signer_key_id or 'openmiura-local').strip(),
        }
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode('utf-8')
        return hashlib.sha256(encoded).hexdigest()

    def _signed_governance_release(self, *, runtime_id: str, version_id: str, version_no: int, policy_kind: str, policy: dict[str, Any], diff: dict[str, Any], actor: str, release_policy: dict[str, Any], activated_at: float) -> dict[str, Any]:
        require_signature = bool(release_policy.get('require_signature', True))
        signer_key_id = str(release_policy.get('signer_key_id') or 'openmiura-local').strip() or 'openmiura-local'
        signature = self._governance_release_signature(
            runtime_id=runtime_id,
            version_id=version_id,
            version_no=version_no,
            policy_kind=policy_kind,
            policy=policy,
            diff=diff,
            signer_key_id=signer_key_id,
        ) if require_signature else ''
        return {
            'release_id': f'govrel-{runtime_id}-{version_no}',
            'policy_kind': str(policy_kind or 'alert_governance').strip() or 'alert_governance',
            'version_id': str(version_id or '').strip(),
            'version_no': int(version_no or 0),
            'status': 'active',
            'signed': bool(signature),
            'signature': signature or None,
            'signer_key_id': signer_key_id,
            'signed_by': str(actor or 'system').strip() or 'system',
            'signed_at': float(activated_at),
        }

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



















































    def list_recovery_jobs(
        self,
        gw,
        *,
        limit: int = 100,
        enabled: bool | None = None,
        runtime_id: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        items = gw.audit.list_job_schedules(
            limit=max(limit * 3, limit),
            enabled=enabled,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        filtered: list[dict[str, Any]] = []
        for item in items:
            if not self._is_recovery_job(item, runtime_id=runtime_id):
                continue
            enriched = self.job_service._with_operational_state(item)
            definition = dict((enriched or {}).get('workflow_definition') or {})
            filtered.append(
                {
                    **dict(enriched or {}),
                    'runtime_id': str(definition.get('runtime_id') or ''),
                    'scheduler_policy': dict(definition.get('scheduler_policy') or {}),
                }
            )
            if len(filtered) >= limit:
                break
        due_count = sum(1 for item in filtered if bool(item.get('is_due')))
        return {
            'ok': True,
            'items': filtered,
            'summary': {
                'count': len(filtered),
                'enabled': sum(1 for item in filtered if bool(item.get('enabled'))),
                'due': due_count,
                'runtime_id': runtime_id,
            },
        }

    def schedule_runtime_recovery_job(
        self,
        gw,
        *,
        runtime_id: str,
        actor: str,
        reason: str = '',
        limit: int | None = None,
        schedule_kind: str | None = None,
        interval_s: int | None = None,
        schedule_expr: str | None = None,
        timezone_name: str | None = 'UTC',
        not_before: float | None = None,
        not_after: float | None = None,
        max_runs: int | None = None,
        enabled: bool = True,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        detail = self.openclaw_adapter_service.get_runtime(
            gw,
            runtime_id=runtime_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        if not detail.get('ok'):
            return detail
        runtime = dict(detail.get('runtime') or {})
        runtime_summary = dict(detail.get('runtime_summary') or {})
        scope = self._scope(
            tenant_id=tenant_id or runtime.get('tenant_id'),
            workspace_id=workspace_id or runtime.get('workspace_id'),
            environment=environment or runtime.get('environment'),
        )
        recovery_schedule = dict(runtime_summary.get('recovery_schedule') or {})
        resolved_schedule_kind = str(schedule_kind or recovery_schedule.get('schedule_kind') or 'interval').strip().lower() or 'interval'
        resolved_interval_s = interval_s if interval_s is not None else int(recovery_schedule.get('interval_s') or 60)
        resolved_limit = int(limit if limit is not None else recovery_schedule.get('limit') or 50)
        scheduler_policy = {
            'pack_name': str(recovery_schedule.get('pack_name') or ((runtime.get('metadata') or {}).get('policy_pack') or 'generic_async_worker')),
            'schedule_kind': resolved_schedule_kind,
            'interval_s': resolved_interval_s,
            'timezone': timezone_name,
            'lease_ttl_s': int(recovery_schedule.get('lease_ttl_s') or max(resolved_interval_s * 2, 30)),
            'idempotency_ttl_s': int(recovery_schedule.get('idempotency_ttl_s') or max(resolved_interval_s * 10, 300)),
            'workspace_backpressure_limit': int(recovery_schedule.get('workspace_backpressure_limit') or 1),
            'runtime_exclusive': bool(recovery_schedule.get('runtime_exclusive', True)),
        }
        definition = self._job_definition(
            runtime_id=runtime_id,
            actor=actor,
            limit=resolved_limit,
            reason=reason or 'scheduled periodic stale-run reconciliation',
            scheduler_policy=scheduler_policy,
        )
        created = self.job_service.create_job(
            gw,
            name=f"openclaw-recovery:{runtime.get('name') or runtime_id}",
            workflow_definition=definition,
            created_by=str(actor or 'system'),
            input_payload={'runtime_id': runtime_id, 'reason': str(reason or '').strip(), 'limit': resolved_limit},
            interval_s=resolved_interval_s if resolved_schedule_kind == 'interval' else None,
            next_run_at=not_before,
            enabled=enabled,
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
            playbook_id=f'openclaw-recovery:{runtime_id}',
            schedule_kind=resolved_schedule_kind,
            schedule_expr=schedule_expr,
            timezone_name=timezone_name,
            not_before=not_before,
            not_after=not_after,
            max_runs=max_runs,
        )
        gw.audit.log_event(
            'system',
            'broker',
            str(actor or 'system'),
            self.job_service._session_id(str(created.get('job_id') or 'system')),
            {
                'action': 'openclaw_recovery_job_scheduled',
                'runtime_id': runtime_id,
                'job_id': created.get('job_id'),
                'schedule_kind': resolved_schedule_kind,
                'interval_s': resolved_interval_s if resolved_schedule_kind == 'interval' else None,
                'schedule_expr': schedule_expr,
                'limit': resolved_limit,
            },
            **scope,
        )
        return {
            'ok': True,
            'job': created,
            'runtime': runtime,
            'runtime_summary': runtime_summary,
            'scheduler_policy': scheduler_policy,
        }

    def _run_single_recovery_job(
        self,
        gw,
        *,
        item: dict[str, Any],
        actor: str,
        user_role: str,
        user_key: str,
        holder_id: str,
    ) -> dict[str, Any]:
        job_id = str(item.get('job_id') or '').strip()
        if not job_id:
            raise ValueError('job_id is required')
        now_ts = time.time()
        if not self.job_service._is_due(item, now=now_ts):
            raise ValueError('Job is not due or cannot run in current window')
        if not self._is_recovery_job(item):
            raise ValueError('Job is not an OpenClaw recovery job')
        definition = dict(item.get('workflow_definition') or {})
        runtime_id = str(definition.get('runtime_id') or '').strip()
        limit = int(definition.get('limit') or 50)
        reason = str(definition.get('reason') or 'scheduled periodic stale-run reconciliation').strip()
        scope = self._scope(
            tenant_id=item.get('tenant_id'),
            workspace_id=item.get('workspace_id'),
            environment=item.get('environment'),
        )
        session_id = self.job_service._session_id(job_id)
        scheduler_policy = self._scheduler_policy(item)
        due_slot = self._due_slot(item, now=now_ts)
        idempotency_key = self._job_idempotency_key(job_id, due_slot)
        claim = gw.audit.claim_idempotency_record(
            idempotency_key=idempotency_key,
            holder_id=holder_id,
            ttl_s=float(scheduler_policy.get('idempotency_ttl_s') or 1800),
            scope_kind=self.JOB_KIND,
            metadata={'job_id': job_id, 'runtime_id': runtime_id, 'due_slot': due_slot},
            **scope,
        )
        claimed_record = dict(claim.get('record') or {})
        if not bool(claim.get('claimed')):
            status = str(claimed_record.get('status') or 'in_progress')
            result = dict(claimed_record.get('result') or {})
            duplicate = status == 'completed'
            return {
                'job': self.job_service.get_job(gw, job_id, **scope),
                'recovery': result.get('recovery') or {'ok': True, 'duplicate': duplicate, 'runtime_id': runtime_id},
                'skipped': True,
                'skip_reason': 'duplicate_completed' if duplicate else 'idempotency_in_progress',
                'idempotency': claimed_record,
            }

        acquired_leases: list[str] = []
        try:
            job_lease = gw.audit.acquire_worker_lease(
                lease_key=self._job_lease_key(job_id),
                holder_id=holder_id,
                lease_ttl_s=float(scheduler_policy.get('lease_ttl_s') or 120),
                metadata={'kind': 'job', 'job_id': job_id, 'runtime_id': runtime_id},
                **scope,
            )
            if not bool(job_lease.get('acquired')):
                gw.audit.complete_idempotency_record(idempotency_key, holder_id=holder_id, status='skipped', result={'reason': 'job_lease_conflict'}, ttl_s=30, **scope)
                return {
                    'job': self.job_service.get_job(gw, job_id, **scope),
                    'recovery': {'ok': False, 'runtime_id': runtime_id, 'error': 'job_lease_conflict'},
                    'skipped': True,
                    'skip_reason': 'job_lease_conflict',
                    'idempotency': gw.audit.get_idempotency_record(idempotency_key, **scope),
                }
            acquired_leases.append(self._job_lease_key(job_id))

            workspace_limit = int(scheduler_policy.get('workspace_backpressure_limit') or 1)
            workspace_acquired = False
            for workspace_lease_key in self._workspace_lease_keys(scope, limit=workspace_limit):
                result = gw.audit.acquire_worker_lease(
                    lease_key=workspace_lease_key,
                    holder_id=holder_id,
                    lease_ttl_s=float(scheduler_policy.get('lease_ttl_s') or 120),
                    metadata={'kind': 'workspace', 'job_id': job_id, 'runtime_id': runtime_id},
                    **scope,
                )
                if bool(result.get('acquired')):
                    acquired_leases.append(workspace_lease_key)
                    workspace_acquired = True
                    break
            if not workspace_acquired:
                gw.audit.complete_idempotency_record(idempotency_key, holder_id=holder_id, status='skipped', result={'reason': 'workspace_backpressure'}, ttl_s=30, **scope)
                return {
                    'job': self.job_service.get_job(gw, job_id, **scope),
                    'recovery': {'ok': False, 'runtime_id': runtime_id, 'error': 'workspace_backpressure'},
                    'skipped': True,
                    'skip_reason': 'workspace_backpressure',
                    'idempotency': gw.audit.get_idempotency_record(idempotency_key, **scope),
                }

            if bool(scheduler_policy.get('runtime_exclusive', True)):
                runtime_lease = gw.audit.acquire_worker_lease(
                    lease_key=self._runtime_lease_key(runtime_id),
                    holder_id=holder_id,
                    lease_ttl_s=float(scheduler_policy.get('lease_ttl_s') or 120),
                    metadata={'kind': 'runtime', 'job_id': job_id, 'runtime_id': runtime_id},
                    **scope,
                )
                if not bool(runtime_lease.get('acquired')):
                    gw.audit.complete_idempotency_record(idempotency_key, holder_id=holder_id, status='skipped', result={'reason': 'runtime_backpressure'}, ttl_s=30, **scope)
                    return {
                        'job': self.job_service.get_job(gw, job_id, **scope),
                        'recovery': {'ok': False, 'runtime_id': runtime_id, 'error': 'runtime_backpressure'},
                        'skipped': True,
                        'skip_reason': 'runtime_backpressure',
                        'idempotency': gw.audit.get_idempotency_record(idempotency_key, **scope),
                    }
                acquired_leases.append(self._runtime_lease_key(runtime_id))

            self.job_service._log(
                gw,
                job_id,
                actor,
                {'event': 'openclaw_recovery_job_run_started', 'job_id': job_id, 'runtime_id': runtime_id, 'holder_id': holder_id, 'due_slot': due_slot},
                **scope,
            )
            self.job_service._publish(
                gw,
                'openclaw_recovery_job_run_started',
                job_id=job_id,
                runtime_id=runtime_id,
                holder_id=holder_id,
                due_slot=due_slot,
                **scope,
            )
            try:
                recovery = self.openclaw_adapter_service.recover_stale_dispatches(
                    gw,
                    runtime_id=runtime_id,
                    actor=actor,
                    reason=reason,
                    limit=limit,
                    user_role=user_role,
                    user_key=user_key,
                    session_id=session_id,
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                )
                last_error = '' if recovery.get('ok') else str(recovery.get('error') or 'recovery_failed')
            except Exception as exc:
                recovery = {'ok': False, 'error': str(exc), 'runtime_id': runtime_id}
                last_error = str(exc)
            now_ts = time.time()
            refreshed_item = dict(item)
            refreshed_item['run_count'] = int(item.get('run_count') or 0) + 1
            next_run_at = self.job_service._compute_next_run_at(refreshed_item, now=now_ts)
            gw.audit.update_job_schedule(
                job_id,
                last_run_at=now_ts,
                next_run_at=next_run_at,
                run_count=int(refreshed_item['run_count']),
                updated_at=now_ts,
                last_error=last_error,
                tenant_id=scope.get('tenant_id'),
                workspace_id=scope.get('workspace_id'),
                environment=scope.get('environment'),
            )
            refreshed = self.job_service.get_job(
                gw,
                job_id,
                tenant_id=scope.get('tenant_id'),
                workspace_id=scope.get('workspace_id'),
                environment=scope.get('environment'),
            )
            event_name = 'openclaw_recovery_job_run_failed' if last_error else 'openclaw_recovery_job_run_completed'
            event_payload = {
                'event': event_name,
                'job_id': job_id,
                'runtime_id': runtime_id,
                'error': last_error,
                'holder_id': holder_id,
                'stale_candidates': ((recovery.get('summary') or {}).get('stale_candidates')),
                'reconciled_count': ((recovery.get('summary') or {}).get('reconciled_count')),
                'polled_count': ((recovery.get('summary') or {}).get('polled_count')),
            }
            self.job_service._log(gw, job_id, actor, event_payload, **scope)
            self.job_service._publish(gw, event_name, job_id=job_id, runtime_id=runtime_id, error=last_error, holder_id=holder_id, **scope)
            result_payload = {
                'job': refreshed,
                'recovery': recovery,
                'skip_reason': '',
                'holder_id': holder_id,
                'due_slot': due_slot,
            }
            gw.audit.complete_idempotency_record(
                idempotency_key,
                holder_id=holder_id,
                status='completed' if not last_error else 'failed',
                result=result_payload,
                ttl_s=float(scheduler_policy.get('idempotency_ttl_s') or 1800),
                metadata={'job_id': job_id, 'runtime_id': runtime_id, 'due_slot': due_slot},
                **scope,
            )
            return result_payload
        finally:
            for lease_key in reversed(acquired_leases):
                try:
                    gw.audit.release_worker_lease(lease_key, holder_id=holder_id, **scope)
                except Exception:
                    pass

    def run_due_recovery_jobs(
        self,
        gw,
        *,
        actor: str,
        limit: int = 20,
        runtime_id: str | None = None,
        user_role: str = 'operator',
        user_key: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        gw.audit.cleanup_worker_leases(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        gw.audit.cleanup_idempotency_records(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        items = gw.audit.list_job_schedules(
            limit=max(limit * 5, limit),
            enabled=True,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        executed: list[dict[str, Any]] = []
        scanned = 0
        now_ts = time.time()
        holder_id = self._holder_id(actor)
        skipped_locked = 0
        skipped_duplicates = 0
        skipped_backpressure = 0
        for item in items:
            if not self._is_recovery_job(item, runtime_id=runtime_id):
                continue
            scanned += 1
            if not self.job_service._is_due(item, now=now_ts):
                continue
            result = self._run_single_recovery_job(
                gw,
                item=item,
                actor=actor,
                user_role=user_role,
                user_key=user_key,
                holder_id=holder_id,
            )
            if result.get('skipped'):
                reason = str(result.get('skip_reason') or '')
                if 'duplicate' in reason or 'idempotency' in reason:
                    skipped_duplicates += 1
                elif 'backpressure' in reason:
                    skipped_backpressure += 1
                else:
                    skipped_locked += 1
            else:
                executed.append(result)
                if len(executed) >= limit:
                    break
        return {
            'ok': True,
            'items': executed,
            'summary': {
                'scanned': scanned,
                'executed': len(executed),
                'runtime_id': runtime_id,
                'failed': sum(1 for item in executed if not bool((item.get('recovery') or {}).get('ok'))),
                'skipped_locked': skipped_locked,
                'skipped_duplicates': skipped_duplicates,
                'skipped_backpressure': skipped_backpressure,
            },
        }


    @classmethod
    def _is_alert_governance_portfolio_release(cls, release: dict[str, Any] | None) -> bool:
        payload = dict(release or {})
        if str(payload.get('kind') or '').strip() != 'policy_portfolio':
            return False
        metadata = dict(payload.get('metadata') or {})
        portfolio = dict(metadata.get('portfolio') or {})
        return str(portfolio.get('kind') or '').strip() == 'openclaw_alert_governance_portfolio'

    @classmethod
    def _is_baseline_catalog_release(cls, release: dict[str, Any] | None) -> bool:
        payload = dict(release or {})
        if str(payload.get('kind') or '').strip() != 'policy_baseline_catalog':
            return False
        metadata = dict(payload.get('metadata') or {})
        catalog = dict(metadata.get('baseline_catalog') or {})
        return str(catalog.get('kind') or '').strip() == 'openclaw_alert_governance_baseline_catalog'

    @classmethod
    def _is_baseline_promotion_release(cls, release: dict[str, Any] | None) -> bool:
        payload = dict(release or {})
        if str(payload.get('kind') or '').strip() != 'policy_baseline_promotion':
            return False
        metadata = dict(payload.get('metadata') or {})
        promotion = dict(metadata.get('baseline_promotion') or {})
        return str(promotion.get('kind') or '').strip() == 'openclaw_alert_governance_baseline_promotion'

    @staticmethod
    def _baseline_promotion_approval_workflow_id(promotion_id: str) -> str:
        return f'openclaw-governance-baseline-promotion:{str(promotion_id or "").strip()}'

    @classmethod
    def _is_release_train_job(cls, item: dict[str, Any] | None, *, portfolio_id: str | None = None) -> bool:
        definition = dict((item or {}).get('workflow_definition') or {})
        if str(definition.get('kind') or '').strip().lower() != cls.GOVERNANCE_RELEASE_TRAIN_JOB_KIND:
            return False
        if portfolio_id is None:
            return True
        return str(definition.get('portfolio_id') or '').strip() == str(portfolio_id or '').strip()

    @staticmethod
    def _release_train_job_definition(*, portfolio_id: str, event_id: str, bundle_id: str, wave_no: int, actor: str, reason: str) -> dict[str, Any]:
        return {
            'kind': OpenClawRecoverySchedulerService.GOVERNANCE_RELEASE_TRAIN_JOB_KIND,
            'portfolio_id': str(portfolio_id or '').strip(),
            'event_id': str(event_id or '').strip(),
            'bundle_id': str(bundle_id or '').strip(),
            'wave_no': int(wave_no or 0),
            'created_by': str(actor or 'system'),
            'reason': str(reason or '').strip(),
        }

    @staticmethod
    def _portfolio_event_id(portfolio_id: str, bundle_id: str, wave_no: int, order_no: int) -> str:
        seed = f'{portfolio_id}:{bundle_id}:{wave_no}:{order_no}'
        return hashlib.sha1(seed.encode('utf-8')).hexdigest()[:16]

    @staticmethod
    def _portfolio_approval_workflow_id(portfolio_id: str) -> str:
        return f'openclaw-governance-portfolio:{str(portfolio_id or "").strip()}'

    @staticmethod
    def _portfolio_deviation_approval_workflow_id(portfolio_id: str) -> str:
        return f'openclaw-governance-portfolio-deviation:{str(portfolio_id or "").strip()}'




    @staticmethod
    def _stable_digest(payload: Any) -> str:
        normalized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(normalized.encode('utf-8')).hexdigest()


    @staticmethod
    def _json_canonical_bytes(payload: Any) -> bytes:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')

    @staticmethod
    def _ed25519_public_key_pem(public_key: ed25519.Ed25519PublicKey) -> str:
        return public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode('utf-8')

    @staticmethod
    def _ed25519_public_key_fingerprint(public_key: ed25519.Ed25519PublicKey) -> str:
        return hashlib.sha256(
            public_key.public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
        ).hexdigest()

    @staticmethod
    def _public_key_pem(public_key: Any) -> str:
        return public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode('utf-8')

    @staticmethod
    def _public_key_fingerprint(public_key: Any) -> str:
        return hashlib.sha256(
            public_key.public_bytes(
                encoding=serialization.Encoding.DER,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        ).hexdigest()

    def _crypto_signature_result(
        self,
        *,
        signature_bytes: bytes,
        signature_scheme: str,
        signing_input: dict[str, Any],
        payload_hash: str,
        public_key: Any,
        provider: str,
        key_origin: str,
        provider_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        public_key_pem = self._public_key_pem(public_key)
        return {
            'payload_hash': payload_hash,
            'signature': base64.b64encode(signature_bytes).decode('ascii'),
            'signature_scheme': str(signature_scheme or 'ed25519'),
            'signature_input': dict(signing_input or {}),
            'signature_input_hash': hashlib.sha256(self._json_canonical_bytes(signing_input)).hexdigest(),
            'public_key': {
                'algorithm': str(signature_scheme or 'ed25519'),
                'origin': key_origin,
                'provider': provider,
                'provider_metadata': dict(provider_metadata or {}),
                'public_key_pem': public_key_pem,
                'public_key_fingerprint': self._public_key_fingerprint(public_key),
            },
            'signer_provider': provider,
            'key_origin': key_origin,
        }

    @staticmethod
    def _load_ed25519_private_key_from_pem(pem: bytes, *, error_prefix: str) -> ed25519.Ed25519PrivateKey:
        loaded = load_pem_private_key(pem, password=None)
        if not isinstance(loaded, ed25519.Ed25519PrivateKey):
            raise TypeError(f'{error_prefix} must contain an Ed25519 private key')
        return loaded

    def _load_portfolio_private_signing_key(
        self,
        *,
        key_id: str,
        signing_policy: dict[str, Any] | None = None,
    ) -> tuple[ed25519.Ed25519PrivateKey, dict[str, Any]]:
        policy = self._normalize_portfolio_signing_policy(dict(signing_policy or {}))
        provider = str(policy.get('provider') or 'local-ed25519').strip() or 'local-ed25519'
        private_key: ed25519.Ed25519PrivateKey | None = None
        origin = 'derived_seed'
        provider_metadata: dict[str, Any] = {'provider': provider}

        def _load_from_sources(env_b64: str, env_path: str, *, error_prefix: str) -> ed25519.Ed25519PrivateKey | None:
            if env_b64:
                return self._load_ed25519_private_key_from_pem(base64.b64decode(env_b64.encode('ascii')), error_prefix=error_prefix)
            if env_path:
                return self._load_ed25519_private_key_from_pem(Path(env_path).read_bytes(), error_prefix=error_prefix)
            return None

        if provider in {'kms-ed25519-simulated', 'kms-ed25519-file'}:
            private_key = _load_from_sources(
                str(policy.get('kms_private_key_pem_b64') or os.getenv('OPENMIURA_EVIDENCE_KMS_PRIVATE_KEY_PEM_B64') or '').strip(),
                str(policy.get('kms_private_key_pem_path') or '').strip(),
                error_prefix='KMS signing key',
            )
            if private_key is not None:
                origin = 'kms_file' if provider == 'kms-ed25519-file' else 'kms_simulated'
                provider_metadata['kms_key_ref'] = str(policy.get('kms_key_ref') or key_id or '').strip() or None
        elif provider in {'hsm-ed25519-simulated', 'hsm-ed25519-file'}:
            private_key = _load_from_sources(
                str(policy.get('hsm_private_key_pem_b64') or os.getenv('OPENMIURA_EVIDENCE_HSM_PRIVATE_KEY_PEM_B64') or '').strip(),
                str(policy.get('hsm_private_key_pem_path') or '').strip(),
                error_prefix='HSM signing key',
            )
            if private_key is not None:
                origin = 'hsm_file' if provider == 'hsm-ed25519-file' else 'hsm_simulated'
                provider_metadata['hsm_slot_id'] = str(policy.get('hsm_slot_id') or key_id or '').strip() or None
        if private_key is None and provider in {'kms-ed25519-simulated', 'hsm-ed25519-simulated', 'kms-ed25519-file', 'hsm-ed25519-file'} and not bool(policy.get('allow_local_fallback', False)):
            raise RuntimeError(f'external_signing_provider_unavailable:{provider}')
        if private_key is None:
            env_b64 = str(os.getenv('OPENMIURA_EVIDENCE_SIGNING_PRIVATE_KEY_PEM_B64') or '').strip()
            env_path = str(os.getenv('OPENMIURA_EVIDENCE_SIGNING_PRIVATE_KEY_PEM_PATH') or '').strip()
            if env_b64:
                private_key = self._load_ed25519_private_key_from_pem(base64.b64decode(env_b64.encode('ascii')), error_prefix='OPENMIURA_EVIDENCE_SIGNING_PRIVATE_KEY_PEM_B64')
                origin = 'configured_pem_b64'
            elif env_path:
                private_key = self._load_ed25519_private_key_from_pem(Path(env_path).read_bytes(), error_prefix='OPENMIURA_EVIDENCE_SIGNING_PRIVATE_KEY_PEM_PATH')
                origin = 'configured_pem_path'
            else:
                seed_material = str(os.getenv('OPENMIURA_EVIDENCE_SIGNING_SEED') or 'openmiura-portfolio-signing-v2-dev-seed').encode('utf-8')
                derived = hashlib.sha256(seed_material + b':' + str(key_id or 'openmiura-local').encode('utf-8')).digest()
                private_key = ed25519.Ed25519PrivateKey.from_private_bytes(derived)
                origin = 'derived_seed'
                provider = 'local-ed25519'
                provider_metadata['provider'] = provider
        public_key = private_key.public_key()
        return private_key, {
            'algorithm': 'ed25519',
            'origin': origin,
            'provider': provider,
            'provider_metadata': provider_metadata,
            'public_key_pem': self._ed25519_public_key_pem(public_key),
            'public_key_fingerprint': self._ed25519_public_key_fingerprint(public_key),
        }

    def _run_portfolio_external_signing_command(
        self,
        *,
        provider: str,
        signer_key_id: str,
        signing_input: dict[str, Any],
        signing_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        policy = self._normalize_portfolio_signing_policy(dict(signing_policy or {}))
        command = [str(item).strip() for item in list(policy.get('sign_command') or []) if str(item).strip()]
        if not command:
            raise RuntimeError(f'external_signing_command_missing:{provider}')
        message = self._json_canonical_bytes(signing_input)
        request_payload = {
            'operation': 'sign',
            'provider': provider,
            'key_id': str(signer_key_id or '').strip(),
            'signing_input': signing_input,
            'message_b64': base64.b64encode(message).decode('ascii'),
            'message_sha256': hashlib.sha256(message).hexdigest(),
        }
        env = os.environ.copy()
        env.update({str(key): str(value) for key, value in dict(policy.get('command_env') or {}).items()})
        proc = subprocess.run(
            command,
            input=self._json_canonical_bytes(request_payload),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=float(policy.get('command_timeout_s') or 10.0),
            env=env,
        )
        if proc.returncode != 0:
            stderr = proc.stderr.decode('utf-8', errors='replace').strip()
            raise RuntimeError(f'external_signing_command_failed:{provider}:{stderr or proc.returncode}')
        try:
            response = json.loads(proc.stdout.decode('utf-8'))
        except Exception as exc:
            raise RuntimeError(f'external_signing_command_invalid_json:{provider}') from exc
        signature_b64 = str(response.get('signature') or '').strip()
        public_key_pem = str(response.get('public_key_pem') or '').strip()
        if not public_key_pem and str(response.get('public_key_pem_b64') or '').strip():
            public_key_pem = base64.b64decode(str(response.get('public_key_pem_b64')).encode('ascii')).decode('utf-8')
        if not signature_b64 or not public_key_pem:
            raise RuntimeError(f'external_signing_command_incomplete:{provider}')
        loaded_public = load_pem_public_key(public_key_pem.encode('utf-8'))
        if not isinstance(loaded_public, ed25519.Ed25519PublicKey):
            raise TypeError('unsupported_public_key_type')
        loaded_public.verify(base64.b64decode(signature_b64.encode('ascii')), message)
        return {
            'signature': signature_b64,
            'signature_scheme': 'ed25519',
            'signature_input': dict(signing_input),
            'signature_input_hash': hashlib.sha256(message).hexdigest(),
            'public_key': {
                'algorithm': 'ed25519',
                'origin': 'external_command',
                'provider': provider,
                'provider_metadata': {
                    'provider': provider,
                    'command': command,
                    **dict(response.get('provider_metadata') or {}),
                },
                'public_key_pem': public_key_pem,
                'public_key_fingerprint': self._ed25519_public_key_fingerprint(loaded_public),
            },
            'signer_provider': provider,
            'key_origin': 'external_command',
        }

    def _load_portfolio_public_key_from_sources(
        self,
        *,
        pem_b64: str = '',
        pem_path: str = '',
        error_prefix: str = 'public key',
    ) -> Any | None:
        raw_pem = b''
        if str(pem_b64 or '').strip():
            raw_pem = base64.b64decode(str(pem_b64).encode('ascii'))
        elif str(pem_path or '').strip():
            raw_pem = Path(str(pem_path)).read_bytes()
        if not raw_pem:
            return None
        loaded = load_pem_public_key(raw_pem)
        return loaded

    def _sign_with_aws_kms_native(
        self,
        *,
        provider: str,
        signer_key_id: str,
        signing_input: dict[str, Any],
        payload_hash: str,
        signing_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        policy = self._normalize_portfolio_signing_policy(dict(signing_policy or {}))
        boto3 = importlib.import_module('boto3')
        session_cls = getattr(getattr(boto3, 'session', boto3), 'Session', None)
        if session_cls is None:
            raise RuntimeError('aws_kms_session_unavailable')
        profile = str(policy.get('aws_profile') or '').strip() or None
        region = str(policy.get('aws_region') or '').strip() or None
        endpoint_url = str(policy.get('aws_endpoint_url') or '').strip() or None
        key_ref = str(policy.get('aws_kms_key_id') or policy.get('kms_key_ref') or signer_key_id or '').strip()
        if not key_ref:
            raise RuntimeError('aws_kms_key_id_missing')
        session = session_cls(profile_name=profile) if profile else session_cls()
        client = session.client('kms', region_name=region, endpoint_url=endpoint_url)
        message = self._json_canonical_bytes(signing_input)
        algorithm = str(policy.get('aws_signing_algorithm') or 'ECDSA_SHA_256').strip() or 'ECDSA_SHA_256'
        response = client.sign(KeyId=key_ref, Message=message, MessageType='RAW', SigningAlgorithm=algorithm)
        signature_bytes = response.get('Signature') or b''
        public_key_obj = None
        try:
            pub_response = client.get_public_key(KeyId=key_ref)
            public_key_obj = serialization.load_der_public_key(pub_response.get('PublicKey'))
        except Exception:
            public_key_obj = self._load_portfolio_public_key_from_sources(
                pem_b64=str(policy.get('aws_public_key_pem_b64') or '').strip(),
                pem_path=str(policy.get('aws_public_key_pem_path') or '').strip(),
                error_prefix='AWS KMS public key',
            )
        if public_key_obj is None:
            raise RuntimeError('aws_kms_public_key_unavailable')
        scheme = 'ecdsa-sha256'
        if isinstance(public_key_obj, ed25519.Ed25519PublicKey):
            scheme = 'ed25519'
        return self._crypto_signature_result(
            signature_bytes=signature_bytes,
            signature_scheme=scheme,
            signing_input=signing_input,
            payload_hash=payload_hash,
            public_key=public_key_obj,
            provider=provider,
            key_origin='aws_kms_native',
            provider_metadata={'provider': provider, 'aws_region': region, 'aws_key_id': key_ref, 'algorithm': algorithm},
        )

    def _sign_with_gcp_kms_native(
        self,
        *,
        provider: str,
        signer_key_id: str,
        signing_input: dict[str, Any],
        payload_hash: str,
        signing_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        policy = self._normalize_portfolio_signing_policy(dict(signing_policy or {}))
        kms_v1 = importlib.import_module('google.cloud.kms_v1')
        credentials = None
        creds_path = str(policy.get('gcp_credentials_path') or '').strip()
        if creds_path:
            service_account = importlib.import_module('google.oauth2.service_account')
            credentials = service_account.Credentials.from_service_account_file(creds_path)
        client = kms_v1.KeyManagementServiceClient(credentials=credentials) if credentials is not None else kms_v1.KeyManagementServiceClient()
        key_name = str(policy.get('gcp_kms_key_name') or signer_key_id or '').strip()
        if not key_name:
            raise RuntimeError('gcp_kms_key_name_missing')
        message = self._json_canonical_bytes(signing_input)
        digest_bytes = hashlib.sha256(message).digest()
        digest = kms_v1.Digest(sha256=digest_bytes)
        response = client.asymmetric_sign(request={'name': key_name, 'digest': digest})
        signature_bytes = response.signature
        public_key_obj = None
        try:
            pub_response = client.get_public_key(request={'name': key_name})
            public_key_obj = load_pem_public_key(pub_response.pem.encode('utf-8'))
        except Exception:
            public_key_obj = self._load_portfolio_public_key_from_sources(
                pem_b64=str(policy.get('gcp_public_key_pem_b64') or '').strip(),
                pem_path=str(policy.get('gcp_public_key_pem_path') or '').strip(),
                error_prefix='GCP KMS public key',
            )
        if public_key_obj is None:
            raise RuntimeError('gcp_kms_public_key_unavailable')
        scheme = 'ecdsa-sha256'
        if isinstance(public_key_obj, ed25519.Ed25519PublicKey):
            scheme = 'ed25519'
        return self._crypto_signature_result(
            signature_bytes=signature_bytes,
            signature_scheme=scheme,
            signing_input=signing_input,
            payload_hash=payload_hash,
            public_key=public_key_obj,
            provider=provider,
            key_origin='gcp_kms_native',
            provider_metadata={'provider': provider, 'gcp_key_name': key_name},
        )

    def _sign_with_azure_key_vault_native(
        self,
        *,
        provider: str,
        signer_key_id: str,
        signing_input: dict[str, Any],
        payload_hash: str,
        signing_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        policy = self._normalize_portfolio_signing_policy(dict(signing_policy or {}))
        identity_mod = importlib.import_module('azure.identity')
        crypto_mod = importlib.import_module('azure.keyvault.keys.crypto')
        credential = getattr(identity_mod, 'DefaultAzureCredential')()
        key_id = str(policy.get('azure_key_id') or signer_key_id or '').strip()
        if not key_id:
            raise RuntimeError('azure_key_id_missing')
        message = self._json_canonical_bytes(signing_input)
        digest_bytes = hashlib.sha256(message).digest()
        crypto_client = crypto_mod.CryptographyClient(key_id, credential)
        algorithm = getattr(getattr(crypto_mod, 'SignatureAlgorithm'), str(policy.get('azure_signature_algorithm_enum') or 'es256'), None)
        if algorithm is None:
            algorithm = getattr(crypto_mod.SignatureAlgorithm, 'es256')
        sign_result = crypto_client.sign(algorithm, digest_bytes)
        signature_bytes = sign_result.signature
        public_key_obj = self._load_portfolio_public_key_from_sources(
            pem_b64=str(policy.get('azure_public_key_pem_b64') or '').strip(),
            pem_path=str(policy.get('azure_public_key_pem_path') or '').strip(),
            error_prefix='Azure Key Vault public key',
        )
        if public_key_obj is None:
            raise RuntimeError('azure_public_key_unavailable')
        scheme = 'ecdsa-sha256'
        if isinstance(public_key_obj, ed25519.Ed25519PublicKey):
            scheme = 'ed25519'
        return self._crypto_signature_result(
            signature_bytes=signature_bytes,
            signature_scheme=scheme,
            signing_input=signing_input,
            payload_hash=payload_hash,
            public_key=public_key_obj,
            provider=provider,
            key_origin='azure_key_vault_native',
            provider_metadata={'provider': provider, 'azure_key_id': key_id, 'algorithm': str(algorithm)},
        )

    def _sign_with_pkcs11_native(
        self,
        *,
        provider: str,
        signer_key_id: str,
        signing_input: dict[str, Any],
        payload_hash: str,
        signing_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        policy = self._normalize_portfolio_signing_policy(dict(signing_policy or {}))
        pkcs11 = importlib.import_module('pkcs11')
        module_path = str(policy.get('pkcs11_module_path') or '').strip()
        if not module_path:
            raise RuntimeError('pkcs11_module_path_missing')
        lib = pkcs11.lib(module_path)
        token_label = str(policy.get('pkcs11_token_label') or '').strip() or None
        pin = str(policy.get('pkcs11_pin') or '').strip() or None
        pin_env_var = str(policy.get('pkcs11_pin_env_var') or '').strip()
        if pin is None and pin_env_var:
            pin = str(os.getenv(pin_env_var) or '').strip() or None
        key_label = str(policy.get('pkcs11_key_label') or signer_key_id or '').strip() or None
        if token_label:
            token = lib.get_token(token_label=token_label)
        else:
            slot_id = policy.get('pkcs11_slot_id')
            token = lib.get_token(slot=int(slot_id)) if slot_id is not None else lib.get_token()
        message = self._json_canonical_bytes(signing_input)
        mechanism_name = str(policy.get('pkcs11_mechanism') or 'EDDSA').strip().upper() or 'EDDSA'
        mechanism = getattr(pkcs11.Mechanism, mechanism_name, None)
        if mechanism is None:
            raise RuntimeError(f'pkcs11_mechanism_unsupported:{mechanism_name}')
        with token.open(user_pin=pin) as session:
            private_key = session.get_key(label=key_label, object_class=pkcs11.ObjectClass.PRIVATE_KEY)
            if mechanism_name == 'ECDSA':
                signature_bytes = bytes(private_key.sign(hashlib.sha256(message).digest(), mechanism=mechanism))
                scheme = 'ecdsa-sha256'
            else:
                signature_bytes = bytes(private_key.sign(message, mechanism=mechanism))
                scheme = 'ed25519'
        public_key_obj = self._load_portfolio_public_key_from_sources(
            pem_b64=str(policy.get('pkcs11_public_key_pem_b64') or '').strip(),
            pem_path=str(policy.get('pkcs11_public_key_pem_path') or '').strip(),
            error_prefix='PKCS#11 public key',
        )
        if public_key_obj is None:
            raise RuntimeError('pkcs11_public_key_unavailable')
        if isinstance(public_key_obj, ec.EllipticCurvePublicKey):
            scheme = 'ecdsa-sha256'
        return self._crypto_signature_result(
            signature_bytes=signature_bytes,
            signature_scheme=scheme,
            signing_input=signing_input,
            payload_hash=payload_hash,
            public_key=public_key_obj,
            provider=provider,
            key_origin='pkcs11_native',
            provider_metadata={'provider': provider, 'pkcs11_module_path': module_path, 'pkcs11_token_label': token_label, 'pkcs11_key_label': key_label, 'mechanism': mechanism_name},
        )

    def _sign_with_native_external_provider(
        self,
        *,
        provider: str,
        signer_key_id: str,
        signing_input: dict[str, Any],
        payload_hash: str,
        signing_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if provider == 'aws-kms-ecdsa-p256':
            return self._sign_with_aws_kms_native(provider=provider, signer_key_id=signer_key_id, signing_input=signing_input, payload_hash=payload_hash, signing_policy=signing_policy)
        if provider == 'gcp-kms-ecdsa-p256':
            return self._sign_with_gcp_kms_native(provider=provider, signer_key_id=signer_key_id, signing_input=signing_input, payload_hash=payload_hash, signing_policy=signing_policy)
        if provider == 'azure-kv-ecdsa-p256':
            return self._sign_with_azure_key_vault_native(provider=provider, signer_key_id=signer_key_id, signing_input=signing_input, payload_hash=payload_hash, signing_policy=signing_policy)
        if provider in {'pkcs11-ed25519', 'pkcs11-ecdsa-p256'}:
            return self._sign_with_pkcs11_native(provider=provider, signer_key_id=signer_key_id, signing_input=signing_input, payload_hash=payload_hash, signing_policy=signing_policy)
        raise RuntimeError(f'unsupported_native_signing_provider:{provider}')

    def _sign_portfolio_payload_crypto_v2(
        self,
        *,
        report_type: str,
        scope: dict[str, Any],
        payload: dict[str, Any],
        signer_key_id: str,
        signing_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_policy = self._normalize_portfolio_signing_policy(dict(signing_policy or {}))
        provider = str(normalized_policy.get('provider') or 'local-ed25519').strip() or 'local-ed25519'
        payload_hash = self._stable_digest(payload)
        signing_input = {
            'report_type': str(report_type or '').strip(),
            'scope': dict(scope or {}),
            'payload_hash': payload_hash,
            'signer_key_id': str(signer_key_id or '').strip(),
        }
        native_providers = {'aws-kms-ecdsa-p256', 'gcp-kms-ecdsa-p256', 'azure-kv-ecdsa-p256', 'pkcs11-ed25519', 'pkcs11-ecdsa-p256'}
        if provider in native_providers:
            try:
                return self._sign_with_native_external_provider(
                    provider=provider,
                    signer_key_id=signer_key_id,
                    signing_input=signing_input,
                    payload_hash=payload_hash,
                    signing_policy=normalized_policy,
                )
            except Exception:
                if not bool(normalized_policy.get('allow_local_fallback', False)):
                    raise
        if provider in {'kms-ed25519-command', 'hsm-ed25519-command'}:
            crypto = self._run_portfolio_external_signing_command(
                provider=provider,
                signer_key_id=signer_key_id,
                signing_input=signing_input,
                signing_policy=normalized_policy,
            )
            crypto['payload_hash'] = payload_hash
            return crypto
        private_key, key_info = self._load_portfolio_private_signing_key(key_id=signer_key_id, signing_policy=normalized_policy)
        message = self._json_canonical_bytes(signing_input)
        signature_bytes = private_key.sign(message)
        return {
            'payload_hash': payload_hash,
            'signature': base64.b64encode(signature_bytes).decode('ascii'),
            'signature_scheme': 'ed25519',
            'signature_input': signing_input,
            'signature_input_hash': hashlib.sha256(message).hexdigest(),
            'public_key': key_info,
            'signer_provider': key_info.get('provider'),
            'key_origin': key_info.get('origin'),
        }

    def _verify_portfolio_crypto_signature(
        self,
        *,
        report_type: str,
        scope: dict[str, Any],
        payload: dict[str, Any],
        integrity: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        resolved = dict(integrity or {})
        payload_hash = self._stable_digest(payload)
        public_key_payload = dict(resolved.get('public_key') or {})
        public_key_pem = str(public_key_payload.get('public_key_pem') or '').strip()
        signature_b64 = str(resolved.get('signature') or '').strip()
        signer_key_id = str(resolved.get('signer_key_id') or '').strip()
        signed = bool(resolved.get('signed'))
        scheme = str(resolved.get('signature_scheme') or '').strip().lower()
        signing_input = dict(resolved.get('signature_input') or {})
        expected_input = {
            'report_type': str(report_type or '').strip(),
            'scope': dict(scope or {}),
            'payload_hash': payload_hash,
            'signer_key_id': signer_key_id,
        }
        payload_hash_valid = str(resolved.get('payload_hash') or '').strip() == payload_hash
        input_valid = signing_input == expected_input
        message = self._json_canonical_bytes(expected_input)
        signature_valid = False
        public_key_valid = False
        public_key_fingerprint = None
        error = None
        if not signed:
            signature_valid = not signature_b64
        elif not public_key_pem or not signature_b64:
            error = 'missing_crypto_material'
        else:
            try:
                loaded_public = load_pem_public_key(public_key_pem.encode('utf-8'))
                signature_bytes = base64.b64decode(signature_b64.encode('ascii'))
                if scheme == 'ed25519':
                    if not isinstance(loaded_public, ed25519.Ed25519PublicKey):
                        raise TypeError('unsupported_public_key_type')
                    public_key_valid = True
                    public_key_fingerprint = self._public_key_fingerprint(loaded_public)
                    loaded_public.verify(signature_bytes, message)
                    signature_valid = True
                elif scheme in {'ecdsa-sha256', 'ecdsa-p256-sha256', 'es256'}:
                    if not isinstance(loaded_public, ec.EllipticCurvePublicKey):
                        raise TypeError('unsupported_public_key_type')
                    public_key_valid = True
                    public_key_fingerprint = self._public_key_fingerprint(loaded_public)
                    loaded_public.verify(signature_bytes, message, ec.ECDSA(hashes.SHA256()))
                    signature_valid = True
                else:
                    error = f'unsupported_signature_scheme:{scheme or "unknown"}'
            except (ValueError, TypeError, InvalidSignature) as exc:
                error = str(exc) or exc.__class__.__name__
                signature_valid = False
        return {
            'report_type': str(report_type or '').strip(),
            'signed': signed,
            'signer_key_id': signer_key_id or None,
            'scheme': scheme or None,
            'signer_provider': public_key_payload.get('provider') or resolved.get('signer_provider'),
            'key_origin': public_key_payload.get('origin') or resolved.get('key_origin'),
            'payload_hash_valid': payload_hash_valid,
            'signature_valid': signature_valid,
            'public_key_valid': public_key_valid,
            'public_key_fingerprint': public_key_fingerprint,
            'signature_input_valid': input_valid,
            'expected_payload_hash': payload_hash,
            'error': error,
            'valid': payload_hash_valid and input_valid and signature_valid,
        }

    def _validate_portfolio_signing_provider_live(
        self,
        *,
        signing_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        policy = self._normalize_portfolio_signing_policy(dict(signing_policy or {}))
        provider = str(policy.get('provider') or 'local-ed25519').strip() or 'local-ed25519'
        base: dict[str, Any] = {
            'provider': provider,
            'key_id': str(policy.get('key_id') or '').strip() or None,
            'validated_at': time.time(),
            'live': provider in {'aws-kms-ecdsa-p256', 'gcp-kms-ecdsa-p256', 'azure-kv-ecdsa-p256', 'pkcs11-ed25519', 'pkcs11-ecdsa-p256'},
        }
        try:
            if provider == 'aws-kms-ecdsa-p256':
                boto3 = importlib.import_module('boto3')
                session_kwargs = {}
                if policy.get('aws_profile'):
                    session_kwargs['profile_name'] = str(policy.get('aws_profile'))
                session = boto3.Session(**session_kwargs)
                client_kwargs = {}
                if policy.get('aws_region'):
                    client_kwargs['region_name'] = str(policy.get('aws_region'))
                if policy.get('aws_endpoint_url'):
                    client_kwargs['endpoint_url'] = str(policy.get('aws_endpoint_url'))
                client = session.client('kms', **client_kwargs)
                key_id = str(policy.get('aws_kms_key_id') or policy.get('kms_key_ref') or policy.get('key_id') or '').strip()
                if not key_id:
                    raise RuntimeError('aws_kms_key_id_missing')
                describe = client.describe_key(KeyId=key_id)
                public_key = client.get_public_key(KeyId=key_id)
                signing_algorithms = list(public_key.get('SigningAlgorithms') or [])
                return {
                    **base,
                    'valid': True,
                    'provider_live': True,
                    'key_origin': 'aws_kms_native',
                    'key_spec': ((describe.get('KeyMetadata') or {}).get('CustomerMasterKeySpec')) or ((describe.get('KeyMetadata') or {}).get('KeySpec')),
                    'key_state': ((describe.get('KeyMetadata') or {}).get('KeyState')),
                    'signing_algorithms': signing_algorithms,
                    'public_key_pem_available': bool(public_key.get('PublicKey')),
                }
            if provider == 'gcp-kms-ecdsa-p256':
                kms_v1 = importlib.import_module('google.cloud.kms_v1')
                credentials_path = str(policy.get('gcp_credentials_path') or '').strip()
                if credentials_path and not os.getenv('GOOGLE_APPLICATION_CREDENTIALS'):
                    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = credentials_path
                client = kms_v1.KeyManagementServiceClient()
                key_name = str(policy.get('gcp_kms_key_name') or policy.get('key_id') or '').strip()
                if not key_name:
                    raise RuntimeError('gcp_kms_key_name_missing')
                public_key = client.get_public_key(request={'name': key_name})
                algorithm = getattr(public_key, 'algorithm', None)
                pem = getattr(public_key, 'pem', '')
                return {
                    **base,
                    'valid': True,
                    'provider_live': True,
                    'key_origin': 'gcp_kms_native',
                    'key_name': key_name,
                    'algorithm': str(algorithm) if algorithm is not None else None,
                    'public_key_pem_available': bool(pem),
                }
            if provider == 'azure-kv-ecdsa-p256':
                key_client_mod = importlib.import_module('azure.keyvault.keys')
                identity_mod = importlib.import_module('azure.identity')
                vault_url = str(policy.get('azure_vault_url') or '').strip()
                key_id = str(policy.get('azure_key_id') or policy.get('key_id') or '').strip()
                if not vault_url:
                    raise RuntimeError('azure_vault_url_missing')
                if not key_id:
                    raise RuntimeError('azure_key_id_missing')
                credential = identity_mod.DefaultAzureCredential()
                key_client = key_client_mod.KeyClient(vault_url=vault_url, credential=credential)
                key_name = key_id.rstrip('/').split('/')[-1]
                key = key_client.get_key(key_name)
                key_type = getattr(key, 'key_type', None)
                return {
                    **base,
                    'valid': True,
                    'provider_live': True,
                    'key_origin': 'azure_key_vault_native',
                    'key_name': key_name,
                    'key_type': str(key_type) if key_type is not None else None,
                    'public_key_pem_available': bool(policy.get('azure_public_key_pem_b64') or policy.get('azure_public_key_pem_path') or getattr(key, 'key', None)),
                }
            if provider in {'pkcs11-ed25519', 'pkcs11-ecdsa-p256'}:
                pkcs11 = importlib.import_module('pkcs11')
                module_path = str(policy.get('pkcs11_module_path') or '').strip()
                if not module_path:
                    raise RuntimeError('pkcs11_module_path_missing')
                lib = pkcs11.lib(module_path)
                token_label = str(policy.get('pkcs11_token_label') or '').strip() or None
                key_label = str(policy.get('pkcs11_key_label') or policy.get('key_id') or '').strip() or None
                pin = str(policy.get('pkcs11_pin') or '').strip() or None
                pin_env_var = str(policy.get('pkcs11_pin_env_var') or '').strip()
                if pin is None and pin_env_var:
                    pin = str(os.getenv(pin_env_var) or '').strip() or None
                if policy.get('pkcs11_slot_id') is not None:
                    token = lib.get_token(slot=int(policy.get('pkcs11_slot_id')))
                else:
                    token = lib.get_token(token_label=token_label)
                with token.open(user_pin=pin) as session:
                    private_key = session.get_key(label=key_label, object_class=pkcs11.ObjectClass.PRIVATE_KEY)
                return {
                    **base,
                    'valid': private_key is not None,
                    'provider_live': True,
                    'key_origin': 'pkcs11_native',
                    'module_path': module_path,
                    'token_label': token_label,
                    'key_label': key_label,
                }
            return {
                **base,
                'valid': True,
                'provider_live': False,
                'key_origin': 'local_or_non_live_provider',
                'reason': 'live_validation_not_required',
            }
        except Exception as exc:
            return {
                **base,
                'valid': False,
                'provider_live': bool(base.get('live')),
                'error': str(exc) or exc.__class__.__name__,
            }

    def _validate_portfolio_escrow_backend_live(
        self,
        *,
        escrow_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        policy = self._normalize_portfolio_escrow_policy(dict(escrow_policy or {}))
        provider = str(policy.get('provider') or 'filesystem-governed').strip() or 'filesystem-governed'
        base: dict[str, Any] = {
            'provider': provider,
            'validated_at': time.time(),
            'object_lock_enabled': bool(policy.get('object_lock_enabled')),
        }
        try:
            if provider in {'aws-s3-object-lock', 's3-object-lock'}:
                boto3 = importlib.import_module('boto3')
                bucket = str(policy.get('aws_s3_bucket') or '').strip()
                if not bucket:
                    raise RuntimeError('aws_s3_bucket_missing')
                session_kwargs = {}
                if policy.get('aws_profile'):
                    session_kwargs['profile_name'] = str(policy.get('aws_profile'))
                session = boto3.Session(**session_kwargs)
                client_kwargs = {}
                if policy.get('aws_region'):
                    client_kwargs['region_name'] = str(policy.get('aws_region'))
                if policy.get('aws_endpoint_url'):
                    client_kwargs['endpoint_url'] = str(policy.get('aws_endpoint_url'))
                client = session.client('s3', **client_kwargs)
                client.head_bucket(Bucket=bucket)
                lock = client.get_object_lock_configuration(Bucket=bucket)
                enabled = str((((lock.get('ObjectLockConfiguration') or {}).get('ObjectLockEnabled')) or '')).upper() == 'ENABLED'
                return {
                    **base,
                    'valid': enabled if bool(policy.get('require_object_lock', True)) else True,
                    'provider_live': True,
                    'bucket': bucket,
                    'prefix': str(policy.get('aws_s3_prefix') or '').strip() or None,
                    'object_lock_backend': True,
                    'object_lock_configuration': dict(lock.get('ObjectLockConfiguration') or {}),
                }
            if provider == 'azure-blob-immutable':
                service = self._azure_blob_service_client_for_policy(policy)
                container = str(policy.get('azure_blob_container') or '').strip()
                if not container:
                    raise RuntimeError('azure_blob_container_missing')
                container_client = service.get_container_client(container)
                if hasattr(container_client, 'get_container_properties'):
                    props = container_client.get_container_properties() or {}
                else:
                    props = {}
                return {
                    **base,
                    'valid': True,
                    'provider_live': True,
                    'container': container,
                    'account_url': str(policy.get('azure_blob_account_url') or '').strip() or None,
                    'object_lock_backend': True,
                    'container_properties': dict(props or {}),
                }
            if provider == 'gcs-retention-lock':
                client = self._gcs_client_for_policy(policy)
                bucket_name = str(policy.get('gcs_bucket') or '').strip()
                if not bucket_name:
                    raise RuntimeError('gcs_bucket_missing')
                bucket = client.bucket(bucket_name)
                if hasattr(bucket, 'reload'):
                    bucket.reload()
                retention_period = getattr(bucket, 'retention_period', None)
                return {
                    **base,
                    'valid': retention_period is not None or not bool(policy.get('require_object_lock', True)),
                    'provider_live': True,
                    'bucket': bucket_name,
                    'object_lock_backend': True,
                    'retention_period': retention_period,
                }
            if provider in {'filesystem-object-lock', 'object-lock-filesystem', 'filesystem-governed'}:
                root_dir = Path(str(policy.get('root_dir') or 'data/openclaw_evidence_escrow')).expanduser().resolve()
                root_dir.mkdir(parents=True, exist_ok=True)
                return {
                    **base,
                    'valid': True,
                    'provider_live': False,
                    'root_dir': root_dir.as_posix(),
                    'object_lock_backend': provider in {'filesystem-object-lock', 'object-lock-filesystem'},
                }
            return {
                **base,
                'valid': True,
                'provider_live': False,
                'reason': 'live_validation_not_implemented_for_provider',
            }
        except Exception as exc:
            return {
                **base,
                'valid': False,
                'provider_live': provider in {'aws-s3-object-lock', 's3-object-lock'},
                'error': str(exc) or exc.__class__.__name__,
            }

    def _validate_portfolio_custody_anchor_backend_live(
        self,
        *,
        custody_anchor_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        policy = self._normalize_portfolio_custody_anchor_policy(dict(custody_anchor_policy or {}))
        provider = str(policy.get('provider') or 'filesystem-ledger').strip() or 'filesystem-ledger'
        try:
            if provider == 'sqlite-immutable-ledger':
                sqlite_path = Path(str(policy.get('sqlite_path') or 'data/openclaw_custody_anchor/custody_anchor_ledger.sqlite3')).expanduser().resolve()
                conn = self._open_portfolio_custody_anchor_sqlite(sqlite_path)
                try:
                    row = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'custody_anchor_receipts'").fetchone()
                finally:
                    conn.close()
                return {
                    'provider': provider,
                    'validated_at': time.time(),
                    'valid': row is not None,
                    'provider_live': True,
                    'sqlite_path': sqlite_path.as_posix(),
                    'immutable_backend': True,
                }
            if provider == 'filesystem-ledger':
                root_dir = Path(str(policy.get('root_dir') or 'data/openclaw_custody_anchor')).expanduser().resolve()
                root_dir.mkdir(parents=True, exist_ok=True)
                return {
                    'provider': provider,
                    'validated_at': time.time(),
                    'valid': True,
                    'provider_live': False,
                    'root_dir': root_dir.as_posix(),
                    'immutable_backend': False,
                }
            return {
                'provider': provider,
                'validated_at': time.time(),
                'valid': False,
                'provider_live': False,
                'error': 'unsupported_custody_anchor_provider',
            }
        except Exception as exc:
            return {
                'provider': provider,
                'validated_at': time.time(),
                'valid': False,
                'provider_live': provider == 'sqlite-immutable-ledger',
                'error': str(exc) or exc.__class__.__name__,
            }

    def _store_portfolio_provider_validation(
        self,
        gw,
        *,
        release: dict[str, Any],
        validation: dict[str, Any],
    ) -> dict[str, Any]:
        metadata = dict(release.get('metadata') or {})
        portfolio = dict(metadata.get('portfolio') or {})
        history = [dict(item) for item in list(portfolio.get('provider_validation_history') or [])]
        history.append(dict(validation))
        portfolio['provider_validation_history'] = history[-20:]
        portfolio['current_provider_validation'] = dict(validation)
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

    @staticmethod
    def _ensure_parent_dir(pathlike: str | Path) -> Path:
        path = Path(pathlike)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _filesystem_path(pathlike: str | Path) -> str:
        path = Path(pathlike)
        raw = str(path)

        if os.name != 'nt':
            return raw

        try:
            normalized = str(path.resolve(strict=False))
        except Exception:
            normalized = os.path.abspath(raw)

        if normalized.startswith('\\\\?\\'):
            return normalized

        # Solo activamos prefijo extendido cuando hace falta de verdad.
        if len(normalized) < 240:
            return normalized

        if normalized.startswith('\\\\'):
            return '\\\\?\\UNC\\' + normalized.lstrip('\\')

        return '\\\\?\\' + normalized

    @classmethod
    def _path_exists(cls, pathlike: str | Path) -> bool:
        return os.path.exists(cls._filesystem_path(pathlike))

    @classmethod
    def _path_is_file(cls, pathlike: str | Path) -> bool:
        return os.path.isfile(cls._filesystem_path(pathlike))

    @classmethod
    def _read_file_bytes(cls, pathlike: str | Path) -> bytes:
        with open(cls._filesystem_path(pathlike), 'rb') as handle:
            return handle.read()

    @classmethod
    def _read_file_text(cls, pathlike: str | Path, *, encoding: str = 'utf-8') -> str:
        with open(cls._filesystem_path(pathlike), 'r', encoding=encoding) as handle:
            return handle.read()

    @classmethod
    def _write_file_if_absent(cls, pathlike: str | Path, data: bytes) -> Path:
        path = Path(pathlike)
        path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        target = cls._filesystem_path(path)

        fd = os.open(target, flags, 0o644)
        try:
            with os.fdopen(fd, 'wb') as handle:
                handle.write(data)
        except Exception:
            try:
                os.unlink(target)
            except OSError:
                pass
            raise
        return path

    @staticmethod
    def _redact_large_blob(mapping: dict[str, Any] | None, *keys: str) -> dict[str, Any]:
        result = dict(mapping or {})
        for key in keys:
            if key in result:
                result.pop(key, None)
        return result

    @classmethod
    def _default_portfolio_operational_tier(cls, environment: str | None) -> str:
        env = cls._normalize_portfolio_environment_name(environment)
        if env == 'prod':
            return 'prod'
        if env == 'stage':
            return 'stage'
        if env == 'dev':
            return 'dev'
        return env or 'standard'

    @staticmethod
    def _merge_portfolio_policy_overrides(base_policy: dict[str, Any] | None, override_policy: dict[str, Any] | None) -> dict[str, Any]:
        merged = dict(base_policy or {})
        for key, value in dict(override_policy or {}).items():
            if value in (None, '', []):
                continue
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                nested = dict(merged.get(key) or {})
                nested.update({nested_key: nested_value for nested_key, nested_value in value.items() if nested_value not in (None, '', [])})
                merged[key] = nested
            else:
                merged[key] = value
        return merged

    def _resolve_portfolio_train_policy_for_environment(
        self,
        train_policy: dict[str, Any] | None,
        *,
        environment: str | None = None,
    ) -> dict[str, Any]:
        normalized = self._normalize_portfolio_train_policy(dict(train_policy or {}))
        env_key = self._normalize_portfolio_environment_name(environment)
        resolved = dict(normalized)
        resolved['resolved_environment'] = env_key or None
        resolved['operational_tier'] = self._default_portfolio_operational_tier(env_key)
        resolved['evidence_classification'] = self._default_portfolio_evidence_classification(env_key)
        override = dict((normalized.get('environment_tier_policies') or {}).get(env_key) or {}) if env_key else {}
        if override:
            resolved['environment_tier_policy'] = dict(override)
            resolved['operational_tier'] = str(override.get('operational_tier') or resolved.get('operational_tier') or '').strip() or self._default_portfolio_operational_tier(env_key)
            resolved['evidence_classification'] = str(override.get('evidence_classification') or resolved.get('evidence_classification') or '').strip() or self._default_portfolio_evidence_classification(env_key)
            resolved['tier_label'] = str(override.get('tier_label') or resolved.get('operational_tier') or '').strip() or resolved.get('operational_tier')
            resolved['approval_policy'] = self._merge_portfolio_policy_overrides(resolved.get('approval_policy'), override.get('approval_policy'))
            resolved['security_gate_policy'] = self._merge_portfolio_policy_overrides(resolved.get('security_gate_policy'), override.get('security_gate_policy'))
            resolved['escrow_policy'] = self._merge_portfolio_policy_overrides(resolved.get('escrow_policy'), override.get('escrow_policy'))
            resolved['signing_policy'] = self._merge_portfolio_policy_overrides(resolved.get('signing_policy'), override.get('signing_policy'))
            resolved['verification_gate_policy'] = self._merge_portfolio_policy_overrides(resolved.get('verification_gate_policy'), override.get('verification_gate_policy'))
        else:
            resolved['environment_tier_policy'] = {
                'environment': env_key or None,
                'tier_label': resolved.get('operational_tier'),
                'operational_tier': resolved.get('operational_tier'),
                'evidence_classification': resolved.get('evidence_classification'),
                'approval_policy': resolved.get('approval_policy'),
                'security_gate_policy': resolved.get('security_gate_policy'),
            }
        retention_policy = dict(resolved.get('retention_policy') or {})
        if resolved.get('evidence_classification'):
            retention_policy['classification'] = str(resolved.get('evidence_classification'))
        resolved['retention_policy'] = retention_policy
        baselines = dict(normalized.get('environment_policy_baselines') or {})
        baseline_override = dict(baselines.get(env_key) or {}) if env_key else {}
        if baseline_override:
            resolved['environment_policy_baseline'] = dict(baseline_override)
        else:
            resolved['environment_policy_baseline'] = {
                'environment': env_key or None,
                'baseline_label': f'{env_key}-baseline' if env_key else 'default-baseline',
                'operational_tier': self._default_portfolio_operational_tier(env_key),
                'evidence_classification': self._default_portfolio_evidence_classification(env_key),
            }
        return resolved

    def _resolve_portfolio_environment_policy_baseline(
        self,
        train_policy: dict[str, Any] | None,
        *,
        environment: str | None = None,
        gw=None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        release: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized = self._normalize_portfolio_train_policy(dict(train_policy or {}))
        env_key = self._normalize_portfolio_environment_name(environment)
        baseline: dict[str, Any] = {}
        catalog_ref = dict(normalized.get('baseline_catalog_ref') or {})
        rollout_state = dict((((release or {}).get('metadata') or {}).get('portfolio') or {}).get('current_baseline_catalog_rollout') or {}) if release is not None else {}
        if gw is not None and catalog_ref and env_key:
            catalog_release = self._get_baseline_catalog_release(
                gw,
                catalog_id=str(catalog_ref.get('catalog_id') or ''),
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                environment=environment,
            )
            if catalog_release is not None:
                baseline = self._resolve_baseline_catalog_environment_baseline(
                    gw,
                    catalog_release=catalog_release,
                    environment=env_key,
                )
                if baseline:
                    baseline['catalog_ref'] = catalog_ref
        if rollout_state and bool(rollout_state.get('active')) and str(rollout_state.get('catalog_id') or '') == str(catalog_ref.get('catalog_id') or ''):
            rollout_candidates = self._normalize_baseline_catalog_environment_entries(dict(rollout_state.get('candidate_baselines') or {}))
            rollout_baseline = dict(rollout_candidates.get(env_key) or rollout_state.get('candidate_baseline') or {})
            if rollout_baseline:
                baseline = self._merge_portfolio_policy_overrides(baseline, rollout_baseline)
                baseline['configured'] = True
                baseline['environment'] = env_key or rollout_baseline.get('environment')
                baseline['baseline_label'] = str(rollout_baseline.get('baseline_label') or baseline.get('baseline_label') or f'{env_key}-baseline').strip() or f'{env_key}-baseline'
                baseline['candidate_rollout'] = {
                    'promotion_id': rollout_state.get('promotion_id'),
                    'wave_no': rollout_state.get('wave_no'),
                    'wave_id': rollout_state.get('wave_id'),
                    'catalog_version': rollout_state.get('catalog_version'),
                    'status': rollout_state.get('status'),
                }
        inline_baselines = dict(normalized.get('environment_policy_baselines') or {})
        inline_baseline = dict(inline_baselines.get(env_key) or {}) if env_key else {}
        catalog_overrides = dict(normalized.get('baseline_catalog_overrides') or {})
        override_baseline = dict(catalog_overrides.get(env_key) or {}) if env_key else {}
        for candidate in (inline_baseline, override_baseline):
            if candidate:
                baseline = self._merge_portfolio_policy_overrides(baseline, candidate)
                baseline['configured'] = True
                baseline['environment'] = env_key or candidate.get('environment')
                baseline['baseline_label'] = str(candidate.get('baseline_label') or baseline.get('baseline_label') or f'{env_key}-baseline').strip() or f'{env_key}-baseline'
                if candidate is override_baseline and catalog_ref:
                    baseline['override_applied'] = True
        if baseline:
            baseline['environment'] = env_key or baseline.get('environment')
            baseline['configured'] = bool(baseline.get('configured', True))
            return baseline
        return {
            'environment': env_key or None,
            'configured': False,
            'baseline_label': f'{env_key}-baseline' if env_key else 'default-baseline',
            'operational_tier': self._default_portfolio_operational_tier(env_key),
            'evidence_classification': self._default_portfolio_evidence_classification(env_key),
            'approval_policy': self._normalize_portfolio_approval_policy({}),
            'security_gate_policy': self._normalize_portfolio_security_gate_policy({}),
            'escrow_policy': self._normalize_portfolio_escrow_policy({}),
            'signing_policy': self._normalize_portfolio_signing_policy({}),
            'verification_gate_policy': self._normalize_portfolio_verification_gate_policy({}),
            'catalog_ref': catalog_ref or None,
        }




    @staticmethod
    def _resolve_portfolio_custody_anchor_policy_for_environment(
        policy: dict[str, Any] | None,
        *,
        environment: str | None = None,
    ) -> dict[str, Any]:
        normalized = OpenClawRecoverySchedulerService._normalize_portfolio_custody_anchor_policy(dict(policy or {}))
        env_key = str(environment or '').strip().lower()
        if not env_key:
            return normalized
        override = dict((normalized.get('environment_policies') or {}).get(env_key) or {})
        if not override:
            return normalized
        merged = dict(normalized)
        merged.update({k: v for k, v in override.items() if v not in (None, '', [])})
        merged['resolved_environment'] = env_key
        return merged


    def _list_portfolio_approvals(
        self,
        gw,
        *,
        portfolio_id: str,
        limit: int = 100,
        status: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> list[dict[str, Any]]:
        workflow_id = self._portfolio_approval_workflow_id(portfolio_id)
        return gw.audit.list_approvals(
            limit=max(limit, 1),
            status=status,
            workflow_id=workflow_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def _portfolio_approval_state(
        self,
        *,
        portfolio_id: str,
        approval_policy: dict[str, Any],
        approvals: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        layers = [dict(item) for item in list((approval_policy or {}).get('layers') or [])]
        records = [dict(item) for item in list(approvals or [])]
        by_layer: dict[str, dict[str, Any]] = {}
        for layer in layers:
            layer_id = str(layer.get('layer_id') or '').strip()
            matching = [item for item in records if str(((item.get('payload') or {}).get('layer_id')) or '') == layer_id]
            matching.sort(key=lambda item: float(item.get('created_at') or 0.0), reverse=True)
            active = matching[0] if matching else None
            status = str((active or {}).get('status') or ('not_requested' if layer.get('required', True) else 'optional')).strip().lower()
            by_layer[layer_id] = {
                'layer_id': layer_id,
                'label': str(layer.get('label') or layer_id),
                'requested_role': str(layer.get('requested_role') or ''),
                'required': bool(layer.get('required', True)),
                'status': status,
                'approval_id': (active or {}).get('approval_id'),
                'decided_by': (active or {}).get('decided_by'),
                'decided_at': (active or {}).get('decided_at'),
                'created_at': (active or {}).get('created_at'),
                'approval': active,
            }
        pending_count = sum(1 for item in by_layer.values() if str(item.get('status') or '') == 'pending')
        approved_count = sum(1 for item in by_layer.values() if str(item.get('status') or '') == 'approved')
        rejected_count = sum(1 for item in by_layer.values() if str(item.get('status') or '') == 'rejected')
        not_requested_count = sum(1 for item in by_layer.values() if str(item.get('status') or '') in {'not_requested', 'optional'})
        required_layers = [item for item in by_layer.values() if bool(item.get('required', True))]
        satisfied = bool(required_layers) and all(str(item.get('status') or '') == 'approved' for item in required_layers)
        if not required_layers:
            satisfied = True
        overall_status = 'not_required'
        if layers:
            if rejected_count > 0:
                overall_status = 'rejected'
            elif satisfied:
                overall_status = 'approved'
            elif pending_count > 0:
                overall_status = 'pending'
            else:
                overall_status = 'not_requested'
        next_layer = None
        if layers and not satisfied and rejected_count == 0:
            mode = str((approval_policy or {}).get('mode') or 'sequential').strip().lower() or 'sequential'
            for layer in layers:
                layer_state = by_layer.get(str(layer.get('layer_id') or '').strip(), {})
                status = str(layer_state.get('status') or '')
                if status == 'approved':
                    continue
                next_layer = layer_state
                if mode == 'sequential':
                    break
        return {
            'portfolio_id': portfolio_id,
            'mode': str((approval_policy or {}).get('mode') or 'none'),
            'enabled': bool((approval_policy or {}).get('enabled')),
            'layers': [by_layer.get(str(layer.get('layer_id') or '').strip(), {}) for layer in layers],
            'pending_count': pending_count,
            'approved_count': approved_count,
            'rejected_count': rejected_count,
            'not_requested_count': not_requested_count,
            'overall_status': overall_status,
            'satisfied': satisfied,
            'next_layer': next_layer,
        }

    def _refresh_portfolio_metadata_state(
        self,
        gw,
        *,
        release: dict[str, Any],
        approval_state: dict[str, Any] | None = None,
        simulation: dict[str, Any] | None = None,
        persist_schedule: bool = False,
    ) -> dict[str, Any]:
        metadata = dict(release.get('metadata') or {})
        portfolio = dict(metadata.get('portfolio') or {})
        calendar = [dict(item) for item in list(portfolio.get('train_calendar') or [])]
        simulation_payload = dict(simulation or {})
        simulation_items = [dict(item) for item in list(simulation_payload.get('items') or [])]
        if approval_state is not None:
            portfolio['approval_state'] = {
                'mode': approval_state.get('mode'),
                'enabled': approval_state.get('enabled'),
                'pending_count': int(approval_state.get('pending_count') or 0),
                'approved_count': int(approval_state.get('approved_count') or 0),
                'rejected_count': int(approval_state.get('rejected_count') or 0),
                'overall_status': approval_state.get('overall_status'),
                'satisfied': bool(approval_state.get('satisfied')),
                'next_layer': dict(approval_state.get('next_layer') or {}),
                'layers': [
                    {
                        'layer_id': item.get('layer_id'),
                        'label': item.get('label'),
                        'requested_role': item.get('requested_role'),
                        'required': item.get('required'),
                        'status': item.get('status'),
                        'approval_id': item.get('approval_id'),
                        'decided_by': item.get('decided_by'),
                        'decided_at': item.get('decided_at'),
                    }
                    for item in list(approval_state.get('layers') or [])
                ],
            }
        if simulation_payload:
            portfolio['last_simulation'] = {
                'executed_at': simulation_payload.get('executed_at'),
                'executed_by': simulation_payload.get('executed_by'),
                'dry_run': bool(simulation_payload.get('dry_run', True)),
                'persisted_schedule': bool(simulation_payload.get('persisted_schedule', False)),
                'validation_status': simulation_payload.get('validation_status'),
                'approvable': bool(simulation_payload.get('approvable', False)),
                'summary': dict(simulation_payload.get('summary') or {}),
                'open_conflicts': [dict(item) for item in list(simulation_payload.get('open_conflicts') or [])],
                'dependency_blocks': [dict(item) for item in list(simulation_payload.get('dependency_blocks') or [])],
                'freeze_hits': [dict(item) for item in list(simulation_payload.get('freeze_hits') or [])],
            }
            by_event = {str(item.get('event_id') or ''): item for item in simulation_items}
            updated_calendar: list[dict[str, Any]] = []
            for event in calendar:
                sim_item = by_event.get(str(event.get('event_id') or ''))
                updated = dict(event)
                if sim_item is not None:
                    validation = {
                        'simulation_status': sim_item.get('simulation_status'),
                        'original_planned_at': sim_item.get('original_planned_at'),
                        'proposed_at': sim_item.get('proposed_at'),
                        'reprogrammed': bool(sim_item.get('reprogrammed')),
                        'blockers': [dict(item) for item in list(sim_item.get('blockers') or [])],
                        'notices': [dict(item) for item in list(sim_item.get('notices') or [])],
                        'target_runtime_ids': list(sim_item.get('target_runtime_ids') or []),
                    }
                    updated['validation'] = validation
                    if persist_schedule and sim_item.get('proposed_at') is not None and str(updated.get('status') or 'planned') not in {'completed', 'error'}:
                        updated['planned_at'] = sim_item.get('proposed_at')
                updated_calendar.append(updated)
            portfolio['train_calendar'] = updated_calendar
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

    def _portfolio_attestation_schedule_items(self, simulation: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for item in list((simulation or {}).get('items') or []):
            payload = dict(item or {})
            attested_planned_at = payload.get('proposed_at')
            if attested_planned_at is None:
                attested_planned_at = payload.get('original_planned_at')
            items.append({
                'event_id': str(payload.get('event_id') or ''),
                'bundle_id': str(payload.get('bundle_id') or ''),
                'wave_no': int(payload.get('wave_no') or 1),
                'attested_planned_at': float(attested_planned_at) if attested_planned_at is not None else None,
                'window_s': int(payload.get('window_s') or 0),
                'simulation_status': str(payload.get('simulation_status') or ''),
                'target_runtime_ids': [str(entry).strip() for entry in list(payload.get('target_runtime_ids') or []) if str(entry).strip()],
            })
        items.sort(key=lambda entry: (float(entry.get('attested_planned_at') or 0.0), int(entry.get('wave_no') or 0), str(entry.get('event_id') or '')))
        return items

    def _create_portfolio_execution_attestation(
        self,
        gw,
        *,
        release: dict[str, Any],
        actor: str,
        reason: str = '',
        simulation: dict[str, Any],
        approval_state: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        metadata = dict(release.get('metadata') or {})
        portfolio = dict(metadata.get('portfolio') or {})
        now_ts = time.time()
        schedule_items = self._portfolio_attestation_schedule_items(simulation)
        attestation_id = str(uuid.uuid4())
        base_train_policy = self._normalize_portfolio_train_policy(dict(portfolio.get('train_policy') or {}))
        train_policy = self._resolve_portfolio_train_policy_for_environment(base_train_policy, environment=release.get('environment'))
        attestation = {
            'attestation_id': attestation_id,
            'kind': 'portfolio_execution_plan',
            'created_at': now_ts,
            'created_by': str(actor or 'system'),
            'reason': str(reason or '').strip(),
            'portfolio_id': str(release.get('release_id') or ''),
            'portfolio_version': str(release.get('version') or ''),
            'release_status': str(release.get('status') or ''),
            'schedule_items': schedule_items,
            'schedule_hash': self._stable_digest(schedule_items),
            'simulation_hash': self._stable_digest({
                'validation_status': simulation.get('validation_status'),
                'summary': simulation.get('summary'),
                'items': schedule_items,
            }),
            'train_policy_hash': self._stable_digest(train_policy),
            'approval_state_hash': self._stable_digest({
                'overall_status': (approval_state or {}).get('overall_status'),
                'layers': [
                    {
                        'layer_id': item.get('layer_id'),
                        'status': item.get('status'),
                        'approval_id': item.get('approval_id'),
                    }
                    for item in list((approval_state or {}).get('layers') or [])
                ],
            }),
            'summary': {
                'count': len(schedule_items),
                'validation_status': simulation.get('validation_status'),
                'approvable': bool(simulation.get('approvable')),
                'reprogrammed_count': int((simulation.get('summary') or {}).get('reprogrammed_count') or 0),
                'blocked_count': int((simulation.get('summary') or {}).get('blocked_count') or 0),
                'deferred_count': int((simulation.get('summary') or {}).get('deferred_count') or 0),
            },
            'signature': self._stable_digest({
                'portfolio_id': str(release.get('release_id') or ''),
                'attestation_id': attestation_id,
                'schedule_hash': self._stable_digest(schedule_items),
                'actor': str(actor or 'system'),
            }),
            'state': 'current',
        }
        existing = [dict(item) for item in list(portfolio.get('attestations') or [])]
        for item in existing:
            if str(item.get('state') or '') == 'current':
                item['state'] = 'superseded'
        existing.append(attestation)
        portfolio['attestations'] = existing[-20:]
        portfolio['current_attestation'] = attestation
        portfolio['last_attested_at'] = now_ts
        metadata['portfolio'] = portfolio
        updated_release = gw.audit.update_release_bundle(
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
                'event': 'openclaw_portfolio_execution_attested',
                'portfolio_id': str(release.get('release_id') or ''),
                'attestation_id': attestation_id,
                'schedule_hash': attestation.get('schedule_hash'),
                'simulation_hash': attestation.get('simulation_hash'),
                'status': updated_release.get('status'),
            },
            tenant_id=release.get('tenant_id'),
            workspace_id=release.get('workspace_id'),
            environment=release.get('environment'),
        )
        return attestation, updated_release

    def _list_portfolio_attestations(self, release: dict[str, Any] | None) -> list[dict[str, Any]]:
        metadata = dict((release or {}).get('metadata') or {})
        portfolio = dict(metadata.get('portfolio') or {})
        items = [dict(item) for item in list(portfolio.get('attestations') or [])]
        items.sort(key=lambda item: float(item.get('created_at') or 0.0), reverse=True)
        return items

    def _list_portfolio_chain_of_custody_entries(self, release: dict[str, Any] | None) -> list[dict[str, Any]]:
        metadata = dict((release or {}).get('metadata') or {})
        portfolio = dict(metadata.get('portfolio') or {})
        items = [dict(item) for item in list(portfolio.get('chain_of_custody_ledger') or [])]
        items.sort(key=lambda item: (int(item.get('sequence') or 0), float(item.get('timestamp') or 0.0), str(item.get('entry_id') or '')))
        return items

    def _build_portfolio_chain_of_custody_entry(
        self,
        *,
        release: dict[str, Any],
        actor: str,
        event_type: str,
        sequence: int,
        previous_entry_hash: str,
        chain_policy: dict[str, Any] | None = None,
        signing_policy: dict[str, Any] | None = None,
        package_id: str | None = None,
        artifact_sha256: str | None = None,
        metadata: dict[str, Any] | None = None,
        timestamp: float | None = None,
    ) -> dict[str, Any]:
        normalized_chain = self._normalize_portfolio_chain_of_custody_policy(dict(chain_policy or {}))
        scope = self._scope(tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=release.get('environment'))
        ts = float(timestamp) if timestamp is not None else time.time()
        canonical = {
            'entry_type': 'openmiura_portfolio_chain_of_custody_entry_v1',
            'entry_id': str(uuid.uuid4()),
            'portfolio_id': str(release.get('release_id') or '').strip(),
            'sequence': int(sequence),
            'timestamp': ts,
            'actor': str(actor or 'system').strip() or 'system',
            'event_type': str(event_type or '').strip() or 'unknown',
            'package_id': str(package_id or '').strip() or None,
            'artifact_sha256': str(artifact_sha256 or '').strip() or None,
            'scope': scope,
            'previous_entry_hash': str(previous_entry_hash or '').strip(),
            'metadata': dict(metadata or {}),
        }
        integrity = self._portfolio_evidence_integrity(
            report_type='openmiura_portfolio_chain_of_custody_entry_v1',
            scope=scope,
            payload=canonical,
            actor=str(actor or 'system'),
            export_policy={'require_signature': bool(normalized_chain.get('sign_entries', True)), 'signer_key_id': str(normalized_chain.get('signer_key_id') or 'openmiura-custody')},
            signing_policy=signing_policy,
        )
        entry_hash = self._stable_digest({
            'canonical': canonical,
            'payload_hash': integrity.get('payload_hash'),
            'previous_entry_hash': canonical.get('previous_entry_hash'),
        })
        return {**canonical, 'entry_hash': entry_hash, 'integrity': integrity}

    def _prepare_portfolio_chain_of_custody_snapshot(
        self,
        *,
        release: dict[str, Any],
        actor: str,
        chain_policy: dict[str, Any] | None = None,
        signing_policy: dict[str, Any] | None = None,
        events: list[dict[str, Any]] | None = None,
        timestamp: float | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        normalized_chain = self._normalize_portfolio_chain_of_custody_policy(dict(chain_policy or {}))
        base_entries = self._list_portfolio_chain_of_custody_entries(release)
        working = [dict(item) for item in base_entries]
        new_entries: list[dict[str, Any]] = []
        if bool(normalized_chain.get('enabled', True)):
            for raw in list(events or []):
                sequence = (int(working[-1].get('sequence') or 0) if working else 0) + 1
                previous_hash = str(working[-1].get('entry_hash') or '') if working else ''
                entry = self._build_portfolio_chain_of_custody_entry(
                    release=release,
                    actor=str(raw.get('actor') or actor or 'system'),
                    event_type=str(raw.get('event_type') or '').strip() or 'unknown',
                    sequence=sequence,
                    previous_entry_hash=previous_hash,
                    chain_policy=normalized_chain,
                    signing_policy=signing_policy,
                    package_id=raw.get('package_id'),
                    artifact_sha256=raw.get('artifact_sha256'),
                    metadata=dict(raw.get('metadata') or {}),
                    timestamp=timestamp,
                )
                working.append(entry)
                new_entries.append(entry)
        snapshot = {
            'ledger_type': 'openmiura_portfolio_chain_of_custody_v1',
            'portfolio_id': str(release.get('release_id') or '').strip(),
            'scope': self._scope(tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=release.get('environment')),
            'entries': working[-max(1, int(normalized_chain.get('max_entries') or 500)):],
        }
        snapshot['summary'] = self._verify_portfolio_chain_of_custody_entries(snapshot['entries'])
        return base_entries, new_entries, snapshot

    def _verify_portfolio_chain_of_custody_entries(self, entries: list[dict[str, Any]] | None) -> dict[str, Any]:
        items = [dict(item) for item in list(entries or [])]
        previous_hash = ''
        chain_valid = True
        signature_valid_count = 0
        invalid_entry_ids: list[str] = []
        for item in items:
            canonical = {
                'entry_type': 'openmiura_portfolio_chain_of_custody_entry_v1',
                'entry_id': item.get('entry_id'),
                'portfolio_id': item.get('portfolio_id'),
                'sequence': int(item.get('sequence') or 0),
                'timestamp': float(item.get('timestamp') or 0.0),
                'actor': item.get('actor'),
                'event_type': item.get('event_type'),
                'package_id': item.get('package_id'),
                'artifact_sha256': item.get('artifact_sha256'),
                'scope': dict(item.get('scope') or {}),
                'previous_entry_hash': item.get('previous_entry_hash'),
                'metadata': dict(item.get('metadata') or {}),
            }
            integrity_verify = self._verify_portfolio_export_integrity(
                report_type='openmiura_portfolio_chain_of_custody_entry_v1',
                scope=dict(item.get('scope') or {}),
                payload=canonical,
                integrity=dict(item.get('integrity') or {}),
            )
            if integrity_verify.get('valid'):
                signature_valid_count += 1
            expected_entry_hash = self._stable_digest({
                'canonical': canonical,
                'payload_hash': ((item.get('integrity') or {}).get('payload_hash')),
                'previous_entry_hash': previous_hash,
            })
            if str(item.get('previous_entry_hash') or '') != previous_hash or str(item.get('entry_hash') or '') != expected_entry_hash or not bool(integrity_verify.get('valid')):
                chain_valid = False
                invalid_entry_ids.append(str(item.get('entry_id') or ''))
            previous_hash = str(item.get('entry_hash') or '')
        return {
            'count': len(items),
            'head_hash': previous_hash or None,
            'chain_valid': chain_valid,
            'signature_valid_count': signature_valid_count,
            'invalid_entry_ids': [item for item in invalid_entry_ids if item],
            'valid': chain_valid and signature_valid_count == len(items),
        }

    def _store_portfolio_chain_of_custody_entries(
        self,
        gw,
        *,
        release: dict[str, Any],
        entries: list[dict[str, Any]] | None,
        chain_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_chain = self._normalize_portfolio_chain_of_custody_policy(dict(chain_policy or {}))
        if not entries:
            return release
        metadata = dict(release.get('metadata') or {})
        portfolio = dict(metadata.get('portfolio') or {})
        current = self._list_portfolio_chain_of_custody_entries(release)
        current.extend([dict(item) for item in list(entries or [])])
        current = current[-max(1, int(normalized_chain.get('max_entries') or 500)):]
        portfolio['chain_of_custody_ledger'] = current
        portfolio['current_chain_of_custody_head'] = current[-1].get('entry_hash') if current else None
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



    @staticmethod
    def _custody_anchor_receipt_hash(receipt: dict[str, Any] | None) -> str:
        item = dict(receipt or {})
        return OpenClawRecoverySchedulerService._stable_digest({
            'anchor_id': item.get('anchor_id'),
            'sequence': int(item.get('sequence') or 0),
            'chain_head_hash': item.get('chain_head_hash'),
            'manifest_hash': item.get('manifest_hash'),
            'control_plane_id': item.get('control_plane_id'),
            'anchor_role': item.get('anchor_role'),
            'quorum_group_key': item.get('quorum_group_key'),
            'payload_hash': ((item.get('integrity') or {}).get('payload_hash')),
            'previous_anchor_hash': item.get('previous_anchor_hash') or '',
        })

    @staticmethod
    def _open_portfolio_custody_anchor_sqlite(pathlike: str | Path) -> sqlite3.Connection:
        path = Path(pathlike)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path.as_posix(), timeout=30.0)
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA synchronous=NORMAL')
        conn.execute("CREATE TABLE IF NOT EXISTS custody_anchor_receipts (portfolio_id TEXT NOT NULL, sequence INTEGER NOT NULL, anchor_id TEXT NOT NULL, receipt_json TEXT NOT NULL, receipt_hash TEXT NOT NULL, created_at REAL NOT NULL, PRIMARY KEY (portfolio_id, sequence), UNIQUE(anchor_id))")
        conn.execute("CREATE TRIGGER IF NOT EXISTS trg_custody_anchor_receipts_no_update BEFORE UPDATE ON custody_anchor_receipts BEGIN SELECT RAISE(ABORT, 'immutable_custody_anchor_ledger'); END;")
        conn.execute("CREATE TRIGGER IF NOT EXISTS trg_custody_anchor_receipts_no_delete BEFORE DELETE ON custody_anchor_receipts BEGIN SELECT RAISE(ABORT, 'immutable_custody_anchor_ledger'); END;")
        return conn

    def _load_external_portfolio_custody_anchor_receipts(
        self,
        *,
        release: dict[str, Any],
        custody_anchor_policy: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        policy = self._resolve_portfolio_custody_anchor_policy_for_environment(custody_anchor_policy, environment=release.get('environment'))
        provider = str(policy.get('provider') or 'filesystem-ledger')
        scope = self._scope(tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=release.get('environment'))
        portfolio_id = str(release.get('release_id') or '').strip() or 'portfolio'
        items: list[dict[str, Any]] = []
        if provider == 'filesystem-ledger':
            root_dir = Path(str(policy.get('root_dir') or 'data/openclaw_custody_anchor'))
            anchor_dir = root_dir.joinpath(
                str(policy.get('ledger_namespace') or 'portfolio-custody'),
                str(scope.get('tenant_id') or 'global'),
                str(scope.get('workspace_id') or 'default'),
                str(scope.get('environment') or 'default'),
                portfolio_id,
                'anchors',
            )
            if anchor_dir.exists():
                for path in sorted(anchor_dir.glob('*.json')):
                    try:
                        items.append(json.loads(path.read_text(encoding='utf-8')))
                    except Exception:
                        continue
        elif provider == 'sqlite-immutable-ledger':
            sqlite_path = Path(str(policy.get('sqlite_path') or 'data/openclaw_custody_anchor/custody_anchor_ledger.sqlite3'))
            if sqlite_path.exists():
                conn = self._open_portfolio_custody_anchor_sqlite(sqlite_path)
                try:
                    rows = conn.execute('SELECT receipt_json FROM custody_anchor_receipts WHERE portfolio_id = ? ORDER BY sequence ASC', (portfolio_id,)).fetchall()
                finally:
                    conn.close()
                for (receipt_json,) in rows:
                    try:
                        items.append(json.loads(str(receipt_json)))
                    except Exception:
                        continue
        items.sort(key=lambda item: (int(item.get('sequence') or 0), float(item.get('anchored_at') or 0.0), str(item.get('anchor_id') or '')))
        return items

    def _replace_portfolio_custody_anchor_receipts(
        self,
        gw,
        *,
        release: dict[str, Any],
        receipts: list[dict[str, Any]],
        custody_anchor_policy: dict[str, Any] | None = None,
        reconciliation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        policy = self._normalize_portfolio_custody_anchor_policy(dict(custody_anchor_policy or {}))
        metadata = dict(release.get('metadata') or {})
        portfolio = dict(metadata.get('portfolio') or {})
        trimmed = [dict(item) for item in list(receipts or [])][-max(1, int(policy.get('max_receipts') or 250)):]
        portfolio['custody_anchor_receipts'] = trimmed
        portfolio['current_custody_anchor'] = trimmed[-1] if trimmed else None
        if reconciliation is not None:
            history = [dict(item) for item in list(portfolio.get('custody_reconciliation_history') or [])]
            history.append(dict(reconciliation))
            portfolio['custody_reconciliation_history'] = history[-20:]
            portfolio['current_custody_reconciliation'] = dict(reconciliation)
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


    @staticmethod
    def _canonical_json_bytes(payload: Any) -> bytes:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode('utf-8')

    @staticmethod
    def _s3_uri(bucket: str, key: str) -> str:
        return f's3://{str(bucket or "").strip()}/{str(key or "").lstrip("/")}'

    @staticmethod
    def _parse_s3_uri(uri: str) -> tuple[str, str] | None:
        text = str(uri or '').strip()
        if not text.startswith('s3://'):
            return None
        without_scheme = text[5:]
        if '/' not in without_scheme:
            return without_scheme, ''
        bucket, key = without_scheme.split('/', 1)
        return bucket, key


    @staticmethod
    def _azblob_uri(container: str, blob_name: str) -> str:
        return f'azblob://{str(container or "").strip()}/{str(blob_name or "").lstrip("/")}'

    @staticmethod
    def _parse_azblob_uri(uri: str) -> tuple[str, str] | None:
        text = str(uri or '').strip()
        if not text.startswith('azblob://'):
            return None
        without_scheme = text[9:]
        if '/' not in without_scheme:
            return without_scheme, ''
        container, blob_name = without_scheme.split('/', 1)
        return container, blob_name

    @staticmethod
    def _gs_uri(bucket: str, key: str) -> str:
        return f'gs://{str(bucket or "").strip()}/{str(key or "").lstrip("/")}'

    @staticmethod
    def _parse_gs_uri(uri: str) -> tuple[str, str] | None:
        text = str(uri or '').strip()
        if not text.startswith('gs://'):
            return None
        without_scheme = text[5:]
        if '/' not in without_scheme:
            return without_scheme, ''
        bucket, key = without_scheme.split('/', 1)
        return bucket, key

    @staticmethod
    def _azure_blob_service_client_for_policy(escrow_policy: dict[str, Any] | None = None):
        policy = dict(escrow_policy or {})
        blob_mod = importlib.import_module('azure.storage.blob')
        connection_string = str(policy.get('azure_blob_connection_string') or '').strip()
        if connection_string and hasattr(blob_mod.BlobServiceClient, 'from_connection_string'):
            return blob_mod.BlobServiceClient.from_connection_string(connection_string)
        account_url = str(policy.get('azure_blob_account_url') or '').strip()
        if not account_url:
            raise RuntimeError('azure_blob_account_url_missing')
        credential = policy.get('azure_blob_credential')
        return blob_mod.BlobServiceClient(account_url=account_url, credential=credential)

    @staticmethod
    def _azure_blob_name_for_artifact(*, policy: dict[str, Any], scope: dict[str, Any], portfolio_id: str, package_id: str, filename: str) -> str:
        parts = [
            str(policy.get('azure_blob_prefix') or '').strip().strip('/'),
            str(policy.get('archive_namespace') or 'portfolio-evidence').strip().strip('/'),
            str(scope.get('tenant_id') or 'global').strip(),
            str(scope.get('workspace_id') or 'default').strip(),
            str(scope.get('environment') or 'default').strip(),
            str(portfolio_id or 'portfolio').strip(),
            str(package_id or 'package').strip(),
            str(filename or f'{package_id}.zip').strip(),
        ]
        return '/'.join([part for part in parts if part])

    @staticmethod
    def _gcs_client_for_policy(escrow_policy: dict[str, Any] | None = None):
        policy = dict(escrow_policy or {})
        storage_mod = importlib.import_module('google.cloud.storage')
        credentials_path = str(policy.get('gcs_credentials_path') or '').strip()
        project = str(policy.get('gcs_project') or '').strip() or None
        if credentials_path and hasattr(storage_mod.Client, 'from_service_account_json'):
            return storage_mod.Client.from_service_account_json(credentials_path, project=project)
        return storage_mod.Client(project=project)

    @staticmethod
    def _gcs_key_for_artifact(*, policy: dict[str, Any], scope: dict[str, Any], portfolio_id: str, package_id: str, filename: str) -> str:
        parts = [
            str(policy.get('gcs_prefix') or '').strip().strip('/'),
            str(policy.get('archive_namespace') or 'portfolio-evidence').strip().strip('/'),
            str(scope.get('tenant_id') or 'global').strip(),
            str(scope.get('workspace_id') or 'default').strip(),
            str(scope.get('environment') or 'default').strip(),
            str(portfolio_id or 'portfolio').strip(),
            str(package_id or 'package').strip(),
            str(filename or f'{package_id}.zip').strip(),
        ]
        return '/'.join([part for part in parts if part])

    @staticmethod
    def _aws_s3_client_for_policy(escrow_policy: dict[str, Any] | None = None):
        policy = dict(escrow_policy or {})
        boto3 = importlib.import_module('boto3')
        session_kwargs = {}
        if policy.get('aws_profile'):
            session_kwargs['profile_name'] = str(policy.get('aws_profile'))
        session = boto3.Session(**session_kwargs)
        client_kwargs = {}
        if policy.get('aws_region'):
            client_kwargs['region_name'] = str(policy.get('aws_region'))
        if policy.get('aws_endpoint_url'):
            client_kwargs['endpoint_url'] = str(policy.get('aws_endpoint_url'))
        return session.client('s3', **client_kwargs)

    @staticmethod
    def _aws_s3_key_for_artifact(*, policy: dict[str, Any], scope: dict[str, Any], portfolio_id: str, package_id: str, filename: str) -> str:
        parts = [
            str(policy.get('aws_s3_prefix') or '').strip().strip('/'),
            str(policy.get('archive_namespace') or 'portfolio-evidence').strip().strip('/'),
            str(scope.get('tenant_id') or 'global').strip(),
            str(scope.get('workspace_id') or 'default').strip(),
            str(scope.get('environment') or 'default').strip(),
            str(portfolio_id or 'portfolio').strip(),
            str(package_id or 'package').strip(),
            str(filename or f'{package_id}.zip').strip(),
        ]
        return '/'.join([part for part in parts if part])

    def _read_s3_object_bytes(self, *, bucket: str, key: str, escrow_policy: dict[str, Any] | None = None) -> bytes:
        client = self._aws_s3_client_for_policy(escrow_policy)
        response = client.get_object(Bucket=bucket, Key=key)
        body = response.get('Body')
        if hasattr(body, 'read'):
            return body.read()
        if isinstance(body, (bytes, bytearray)):
            return bytes(body)
        raise RuntimeError('s3_body_unreadable')




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

    def _simulate_portfolio_calendar(
        self,
        gw,
        *,
        release: dict[str, Any],
        actor: str = 'system',
        now_ts: float | None = None,
        dry_run: bool = True,
        auto_reschedule: bool | None = None,
        persist_metadata: bool = False,
        persist_schedule: bool = False,
    ) -> dict[str, Any]:
        scope = self._scope(tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=release.get('environment'))
        metadata = dict(release.get('metadata') or {})
        portfolio = dict(metadata.get('portfolio') or {})
        base_train_policy = self._normalize_portfolio_train_policy(dict(portfolio.get('train_policy') or {}))
        train_policy = self._resolve_portfolio_train_policy_for_environment(base_train_policy, environment=release.get('environment'))
        bundle_ids = list(portfolio.get('bundle_ids') or []) or [str(item.get('item_key') or '').strip() for item in gw.audit.list_release_bundle_items(str(release.get('release_id') or '')) if str(item.get('item_kind') or '').strip() == 'policy_bundle']
        calendar = self._normalize_release_train_calendar(
            portfolio_id=str(release.get('release_id') or ''),
            bundle_ids=bundle_ids,
            train_calendar=list(portfolio.get('train_calendar') or []),
            base_release_at=train_policy.get('base_release_at'),
            spacing_s=int(train_policy.get('spacing_s') or 0),
            default_window_s=int(train_policy.get('default_event_window_s') or 0),
        )
        resolved_auto_reschedule = bool(train_policy.get('auto_reschedule')) if auto_reschedule is None else bool(auto_reschedule)
        default_window_s = max(1, int(train_policy.get('default_event_window_s') or 60))
        reschedule_buffer_s = max(1, int(train_policy.get('reschedule_buffer_s') or 60))
        simulation_now = float(now_ts) if now_ts is not None else time.time()
        bundle_details: dict[str, dict[str, Any]] = {}
        for bundle_id in bundle_ids:
            bundle_detail = self.get_runtime_alert_governance_bundle(
                gw,
                bundle_id=bundle_id,
                tenant_id=scope.get('tenant_id'),
                workspace_id=scope.get('workspace_id'),
                environment=scope.get('environment'),
            )
            targets = []
            target_runtime_ids: list[str] = []
            bundle_status = 'missing'
            rollout_status = 'missing'
            if bundle_detail.get('ok'):
                targets = [dict(item) for item in list(bundle_detail.get('targets') or [])]
                target_runtime_ids = [str(item.get('runtime_id') or '').strip() for item in targets if str(item.get('runtime_id') or '').strip()]
                bundle_status = str(((bundle_detail.get('release') or {}).get('status')) or 'draft')
                rollout_status = str(((bundle_detail.get('summary') or {}).get('rollout_status')) or 'draft')
            bundle_details[bundle_id] = {
                'ok': bool(bundle_detail.get('ok')),
                'error': bundle_detail.get('error'),
                'release_status': bundle_status,
                'rollout_status': rollout_status,
                'targets': targets,
                'target_runtime_ids': target_runtime_ids,
            }
        dependency_graph = self._normalize_portfolio_dependency_graph(train_policy.get('dependency_graph'))
        freeze_windows = self._normalize_portfolio_freeze_windows(list(train_policy.get('freeze_windows') or []))
        scheduled_intervals: list[dict[str, Any]] = []
        predicted_bundle_completion: dict[str, float] = {}
        completed_bundles = {
            bundle_id for bundle_id, detail in bundle_details.items()
            if str(detail.get('rollout_status') or '') == 'completed'
        }
        simulation_items: list[dict[str, Any]] = []
        open_conflicts: list[dict[str, Any]] = []
        dependency_blocks: list[dict[str, Any]] = []
        freeze_hits: list[dict[str, Any]] = []
        reprogrammed_count = 0
        for event in calendar:
            bundle_id = str(event.get('bundle_id') or '').strip()
            event_id = str(event.get('event_id') or '').strip()
            planned_at = event.get('planned_at')
            try:
                original_planned_at = float(planned_at) if planned_at is not None else None
            except Exception:
                original_planned_at = None
            current_status = str(event.get('status') or 'planned').strip().lower() or 'planned'
            bundle_info = dict(bundle_details.get(bundle_id) or {})
            target_runtime_ids = list(bundle_info.get('target_runtime_ids') or [])
            window_s = max(1, int(event.get('window_s') or default_window_s))
            proposed_at = original_planned_at
            blockers: list[dict[str, Any]] = []
            notices: list[dict[str, Any]] = []
            if current_status == 'completed':
                completion_at = (original_planned_at + window_s) if original_planned_at is not None else simulation_now
                predicted_bundle_completion[bundle_id] = completion_at
                completed_bundles.add(bundle_id)
                simulation_items.append({
                    'event_id': event_id,
                    'bundle_id': bundle_id,
                    'wave_no': int(event.get('wave_no') or 1),
                    'label': str(event.get('label') or ''),
                    'original_planned_at': original_planned_at,
                    'proposed_at': original_planned_at,
                    'window_s': window_s,
                    'simulation_status': 'completed',
                    'reprogrammed': False,
                    'blockers': [],
                    'notices': [],
                    'target_runtime_ids': target_runtime_ids,
                    'bundle_release_status': bundle_info.get('release_status'),
                })
                continue
            if original_planned_at is None:
                blockers.append({'code': 'unscheduled_event', 'reason': 'calendar event has no planned_at', 'event_id': event_id, 'bundle_id': bundle_id})
            if str(bundle_info.get('release_status') or '') not in {'approved', 'promoted'} and str(bundle_info.get('rollout_status') or '') != 'completed':
                blockers.append({'code': 'bundle_not_approved', 'reason': 'bundle release is not approved', 'bundle_id': bundle_id, 'release_status': bundle_info.get('release_status')})
            dep_ids = [dep for dep in list(dependency_graph.get(bundle_id) or []) if dep]
            if dep_ids:
                unresolved = []
                dep_completion_candidates = []
                for dep_id in dep_ids:
                    if dep_id in completed_bundles:
                        dep_completion_candidates.append(float(predicted_bundle_completion.get(dep_id) or original_planned_at or simulation_now))
                        continue
                    if dep_id in predicted_bundle_completion:
                        dep_completion_candidates.append(float(predicted_bundle_completion.get(dep_id) or simulation_now))
                    else:
                        unresolved.append(dep_id)
                if unresolved:
                    block = {
                        'code': 'dependency_blocked',
                        'reason': 'bundle dependencies are not scheduled ahead of this event',
                        'bundle_id': bundle_id,
                        'depends_on': unresolved,
                    }
                    blockers.append(block)
                    dependency_blocks.append(block)
                elif dep_completion_candidates and proposed_at is not None:
                    required_after = max(dep_completion_candidates) + reschedule_buffer_s
                    if proposed_at < required_after:
                        if resolved_auto_reschedule:
                            notices.append({'code': 'dependency_reprogrammed', 'reason': 'event moved after dependency completion', 'bundle_id': bundle_id, 'depends_on': dep_ids, 'from': proposed_at, 'to': required_after})
                            proposed_at = required_after
                        else:
                            block = {
                                'code': 'dependency_schedule_conflict',
                                'reason': 'event is planned before dependency completion window',
                                'bundle_id': bundle_id,
                                'depends_on': dep_ids,
                                'required_after': required_after,
                            }
                            blockers.append(block)
                            dependency_blocks.append(block)
            if proposed_at is not None and blockers:
                passive_event_start = float(proposed_at)
                passive_event_end = passive_event_start + window_s
                passive_freezes = []
                for freeze in freeze_windows:
                    freeze_bundle_ids = list(freeze.get('bundle_ids') or [])
                    if freeze_bundle_ids and bundle_id not in freeze_bundle_ids:
                        continue
                    freeze_environment = str(freeze.get('environment') or '').strip()
                    if freeze_environment and freeze_environment != str(scope.get('environment') or ''):
                        continue
                    freeze_start = freeze.get('start_at')
                    freeze_end = freeze.get('end_at')
                    if freeze_start is None and freeze_end is None:
                        continue
                    normalized_freeze_start = float(freeze_start) if freeze_start is not None else passive_event_start
                    normalized_freeze_end = float(freeze_end) if freeze_end is not None else passive_event_end
                    overlaps = passive_event_start < normalized_freeze_end and passive_event_end > normalized_freeze_start
                    if overlaps:
                        passive_freezes.append({
                            'window_id': freeze.get('window_id'),
                            'label': freeze.get('label'),
                            'reason': freeze.get('reason'),
                            'start_at': freeze_start,
                            'end_at': freeze_end,
                            'bundle_id': bundle_id,
                            'event_id': event_id,
                        })
                if passive_freezes:
                    freeze_hits.extend(passive_freezes)
                    if not any(str(item.get('code') or '') == 'freeze_window' for item in blockers):
                        blockers.append({
                            'code': 'freeze_window',
                            'reason': 'event falls inside freeze window',
                            'event_id': event_id,
                            'bundle_id': bundle_id,
                            'freeze_windows': passive_freezes,
                        })
            if proposed_at is not None and not blockers:
                guard = 0
                while guard < 20:
                    guard += 1
                    adjusted = False
                    event_start = float(proposed_at)
                    event_end = event_start + window_s
                    applicable_freezes = []
                    for freeze in freeze_windows:
                        freeze_bundle_ids = list(freeze.get('bundle_ids') or [])
                        if freeze_bundle_ids and bundle_id not in freeze_bundle_ids:
                            continue
                        freeze_environment = str(freeze.get('environment') or '').strip()
                        if freeze_environment and freeze_environment != str(scope.get('environment') or ''):
                            continue
                        freeze_start = freeze.get('start_at')
                        freeze_end = freeze.get('end_at')
                        if freeze_start is None and freeze_end is None:
                            continue
                        normalized_freeze_start = float(freeze_start) if freeze_start is not None else event_start
                        normalized_freeze_end = float(freeze_end) if freeze_end is not None else event_end
                        overlaps = event_start < normalized_freeze_end and event_end > normalized_freeze_start
                        if overlaps:
                            applicable_freezes.append({
                                'window_id': freeze.get('window_id'),
                                'label': freeze.get('label'),
                                'reason': freeze.get('reason'),
                                'start_at': freeze_start,
                                'end_at': freeze_end,
                                'bundle_id': bundle_id,
                                'event_id': event_id,
                            })
                    if applicable_freezes:
                        freeze_hits.extend(applicable_freezes)
                        if resolved_auto_reschedule and applicable_freezes[0].get('end_at') is not None:
                            next_at = float(applicable_freezes[0].get('end_at') or event_end) + reschedule_buffer_s
                            if next_at > proposed_at:
                                notices.append({'code': 'freeze_window_reprogrammed', 'reason': 'event moved outside freeze window', 'bundle_id': bundle_id, 'event_id': event_id, 'from': proposed_at, 'to': next_at, 'freeze_window': applicable_freezes[0]})
                                proposed_at = next_at
                                adjusted = True
                        else:
                            blockers.append({'code': 'freeze_window', 'reason': 'event falls inside freeze window', 'event_id': event_id, 'bundle_id': bundle_id, 'freeze_windows': applicable_freezes})
                        if adjusted:
                            continue
                    if blockers:
                        break
                    if bool(train_policy.get('strict_conflict_check')):
                        conflicts = []
                        for other in scheduled_intervals:
                            if not set(target_runtime_ids).intersection(set(other.get('target_runtime_ids') or [])):
                                continue
                            other_start = float(other.get('start_at') or 0.0)
                            other_end = float(other.get('end_at') or other_start)
                            if event_start < other_end and event_end > other_start:
                                conflicts.append({
                                    'event_id': event_id,
                                    'bundle_id': bundle_id,
                                    'conflicts_with_event_id': other.get('event_id'),
                                    'conflicts_with_bundle_id': other.get('bundle_id'),
                                    'shared_runtime_ids': sorted(set(target_runtime_ids).intersection(set(other.get('target_runtime_ids') or []))),
                                    'start_at': event_start,
                                    'end_at': event_end,
                                    'other_start_at': other_start,
                                    'other_end_at': other_end,
                                })
                        if conflicts:
                            if resolved_auto_reschedule:
                                next_at = max(float(item.get('other_end_at') or event_end) for item in conflicts) + reschedule_buffer_s
                                if next_at > proposed_at:
                                    notices.append({'code': 'calendar_conflict_reprogrammed', 'reason': 'event moved to avoid runtime overlap conflict', 'bundle_id': bundle_id, 'event_id': event_id, 'from': proposed_at, 'to': next_at, 'conflicts': conflicts})
                                    proposed_at = next_at
                                    adjusted = True
                            else:
                                blockers.append({'code': 'calendar_conflict', 'reason': 'event overlaps another bundle on the same runtime', 'event_id': event_id, 'bundle_id': bundle_id, 'conflicts': conflicts})
                                open_conflicts.extend(conflicts)
                        if adjusted:
                            continue
                    break
            reprogrammed = proposed_at is not None and original_planned_at is not None and abs(float(proposed_at) - float(original_planned_at)) > 0.001
            if reprogrammed:
                reprogrammed_count += 1
            simulation_status = 'ready'
            if blockers:
                simulation_status = 'blocked'
            elif reprogrammed:
                simulation_status = 'deferred'
            completion_at = (float(proposed_at) + window_s) if proposed_at is not None else None
            if simulation_status in {'ready', 'deferred'} and completion_at is not None:
                predicted_bundle_completion[bundle_id] = completion_at
                completed_bundles.add(bundle_id)
                scheduled_intervals.append({
                    'event_id': event_id,
                    'bundle_id': bundle_id,
                    'target_runtime_ids': target_runtime_ids,
                    'start_at': float(proposed_at),
                    'end_at': float(completion_at),
                })
            simulation_items.append({
                'event_id': event_id,
                'bundle_id': bundle_id,
                'wave_no': int(event.get('wave_no') or 1),
                'label': str(event.get('label') or ''),
                'original_planned_at': original_planned_at,
                'proposed_at': proposed_at,
                'window_s': window_s,
                'simulation_status': simulation_status,
                'reprogrammed': bool(reprogrammed),
                'blockers': blockers,
                'notices': notices,
                'target_runtime_ids': target_runtime_ids,
                'bundle_release_status': bundle_info.get('release_status'),
            })
        status_counts: dict[str, int] = {}
        for item in simulation_items:
            key = str(item.get('simulation_status') or 'unknown')
            status_counts[key] = status_counts.get(key, 0) + 1
        blocked_count = int(status_counts.get('blocked') or 0)
        deferred_count = int(status_counts.get('deferred') or 0)
        ready_count = int(status_counts.get('ready') or 0)
        completed_count = int(status_counts.get('completed') or 0)
        validation_status = 'ready'
        if blocked_count > 0 or open_conflicts:
            validation_status = 'blocked'
        elif deferred_count > 0:
            validation_status = 'approvable_with_reschedule'
        approvable = validation_status in {'ready', 'approvable_with_reschedule'}
        simulation = {
            'executed_at': simulation_now,
            'executed_by': str(actor or 'system'),
            'dry_run': bool(dry_run),
            'persisted_schedule': bool(persist_schedule),
            'validation_status': validation_status,
            'approvable': approvable,
            'train_policy': train_policy,
            'items': simulation_items,
            'open_conflicts': open_conflicts,
            'dependency_blocks': dependency_blocks,
            'freeze_hits': freeze_hits,
            'summary': {
                'count': len(simulation_items),
                'status_counts': status_counts,
                'blocked_count': blocked_count,
                'deferred_count': deferred_count,
                'ready_count': ready_count,
                'completed_count': completed_count,
                'freeze_hit_count': len(freeze_hits),
                'dependency_blocked_count': len(dependency_blocks),
                'open_conflict_count': len(open_conflicts),
                'reprogrammed_count': reprogrammed_count,
            },
        }
        if persist_metadata:
            release = self._refresh_portfolio_metadata_state(gw, release=release, simulation=simulation, persist_schedule=bool(persist_schedule))
            simulation['release'] = release
        return simulation

    def _portfolio_detail_view(self, gw, *, release: dict[str, Any]) -> dict[str, Any]:
        metadata = dict(release.get('metadata') or {})
        portfolio = dict(metadata.get('portfolio') or {})
        scope = self._scope(tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=release.get('environment'))
        items = gw.audit.list_release_bundle_items(str(release.get('release_id') or ''))
        bundle_ids = [str(item.get('item_key') or '').strip() for item in items if str(item.get('item_kind') or '').strip() == 'policy_bundle']
        base_train_policy = self._normalize_portfolio_train_policy(dict(portfolio.get('train_policy') or {}))
        train_policy = self._resolve_portfolio_train_policy_for_environment(base_train_policy, environment=release.get('environment'))
        bundles: list[dict[str, Any]] = []
        bundle_status_counts: dict[str, int] = {}
        total_targets = 0
        total_active = 0
        completed_bundles = 0
        max_exposure = 0.0
        for bundle_id in bundle_ids:
            detail = self.get_runtime_alert_governance_bundle(gw, bundle_id=bundle_id, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'))
            if not detail.get('ok'):
                bundles.append({'bundle_id': bundle_id, 'ok': False, 'error': detail.get('error')})
                bundle_status_counts['missing'] = bundle_status_counts.get('missing', 0) + 1
                continue
            summary = dict(detail.get('summary') or {})
            analytics = dict(detail.get('analytics') or {})
            rollout_status = str(summary.get('rollout_status') or 'unknown')
            bundle_status_counts[rollout_status] = bundle_status_counts.get(rollout_status, 0) + 1
            total_targets += int(summary.get('target_count') or 0)
            total_active += int(summary.get('active_runtime_count') or 0)
            if rollout_status == 'completed':
                completed_bundles += 1
            try:
                max_exposure = max(max_exposure, float(analytics.get('current_exposure_ratio') or 0.0))
            except Exception:
                pass
            bundles.append({
                'bundle_id': bundle_id,
                'release': detail.get('release'),
                'summary': summary,
                'analytics': analytics,
                'bundle': detail.get('bundle'),
                'targets': detail.get('targets'),
            })
        calendar_events = self._normalize_release_train_calendar(
            portfolio_id=str(release.get('release_id') or ''),
            bundle_ids=bundle_ids,
            train_calendar=list(portfolio.get('train_calendar') or []),
            base_release_at=train_policy.get('base_release_at'),
            spacing_s=int(train_policy.get('spacing_s') or 0),
            default_window_s=int(train_policy.get('default_event_window_s') or 0),
        )
        simulation = self._simulate_portfolio_calendar(gw, release=release, actor='system', dry_run=True, auto_reschedule=None, persist_metadata=False, persist_schedule=False)
        sim_items = {str(item.get('event_id') or ''): item for item in list(simulation.get('items') or [])}
        jobs_payload = self.list_release_train_jobs(
            gw,
            portfolio_id=str(release.get('release_id') or ''),
            limit=max(100, len(calendar_events) * 3 or 50),
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        )
        job_items = list(jobs_payload.get('items') or [])
        jobs_by_event = {str((item.get('workflow_definition') or {}).get('event_id') or ''): item for item in job_items}
        now_ts = time.time()
        due_count = 0
        completed_count = 0
        blocked_count = int((simulation.get('summary') or {}).get('blocked_count') or 0)
        deferred_count = int((simulation.get('summary') or {}).get('deferred_count') or 0)
        for event in calendar_events:
            event_id = str(event.get('event_id') or '')
            job = jobs_by_event.get(event_id)
            if job is not None:
                event['job'] = job
            sim_item = sim_items.get(event_id)
            if sim_item is not None:
                event['validation'] = {
                    'simulation_status': sim_item.get('simulation_status'),
                    'original_planned_at': sim_item.get('original_planned_at'),
                    'proposed_at': sim_item.get('proposed_at'),
                    'reprogrammed': bool(sim_item.get('reprogrammed')),
                    'blockers': [dict(item) for item in list(sim_item.get('blockers') or [])],
                    'notices': [dict(item) for item in list(sim_item.get('notices') or [])],
                }
            planned_at = event.get('planned_at')
            if planned_at is not None and float(planned_at) <= now_ts and str(event.get('status') or 'planned') == 'planned':
                due_count += 1
            if str(event.get('status') or '') == 'completed':
                completed_count += 1
        approval_policy = self._normalize_portfolio_approval_policy(dict(train_policy.get('approval_policy') or {}))
        approvals = self._list_portfolio_approvals(
            gw,
            portfolio_id=str(release.get('release_id') or ''),
            limit=max(20, len(list(approval_policy.get('layers') or [])) * 3 + 5),
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        )
        approval_state = self._portfolio_approval_state(
            portfolio_id=str(release.get('release_id') or ''),
            approval_policy=approval_policy,
            approvals=approvals,
        )
        attestations = self._list_portfolio_attestations(release)
        evidence_packages = self._list_portfolio_evidence_packages(release)
        evidence_summary = self._portfolio_evidence_package_summary(release)
        chain_of_custody_entries = self._list_portfolio_chain_of_custody_entries(release)
        chain_of_custody_summary = self._portfolio_chain_of_custody_summary(release)
        custody_anchor_receipts = self._list_portfolio_custody_anchor_receipts(release)
        custody_anchor_summary = self._portfolio_custody_anchor_summary(release)
        provider_validation = dict((((release.get('metadata') or {}).get('portfolio') or {}).get('current_provider_validation') or {}) or {})
        read_verification = dict((((release.get('metadata') or {}).get('portfolio') or {}).get('current_read_verification') or {}) or {})
        policy_conformance = self._portfolio_policy_conformance_report(gw, release=release, persist_metadata=False)
        policy_baseline_drift = self._portfolio_policy_baseline_drift_report(gw, release=release, persist_metadata=False)
        deviation_exception_summary = self._portfolio_policy_deviation_exception_summary(release)
        drift_report = self._evaluate_portfolio_execution_drift(
            gw,
            release=release,
            actor='system',
            simulation=simulation,
            persist_metadata=False,
        )
        current_attestation = dict((((release.get('metadata') or {}).get('portfolio') or {}).get('current_attestation') or (attestations[0] if attestations else {})) or {})
        rollout_status = 'draft'
        release_status = str(release.get('status') or '').strip()
        if release_status == 'candidate':
            rollout_status = 'candidate'
        elif release_status == 'pending_approval':
            rollout_status = 'pending_approval'
        elif release_status == 'rejected':
            rollout_status = 'rejected'
        elif release_status in {'approved', 'promoted'}:
            if completed_count == len(calendar_events) and calendar_events:
                rollout_status = 'completed'
            elif due_count > 0:
                rollout_status = 'scheduled_due'
            elif completed_count > 0:
                rollout_status = 'in_progress'
            else:
                rollout_status = 'approved'
        analytics = {
            'bundle_count': len(bundle_ids),
            'completed_bundle_ratio': round(completed_bundles / max(1, len(bundle_ids)), 4),
            'active_runtime_ratio': round(total_active / max(1, total_targets), 4) if total_targets else 0.0,
            'max_bundle_exposure_ratio': round(max_exposure, 4),
            'calendar_completion_ratio': round(completed_count / max(1, len(calendar_events)), 4) if calendar_events else 0.0,
            'calendar_due_count': due_count,
            'calendar_blocked_count': blocked_count,
            'calendar_deferred_count': deferred_count,
            'calendar_open_conflict_count': int((simulation.get('summary') or {}).get('open_conflict_count') or 0),
            'calendar_reprogrammed_count': int((simulation.get('summary') or {}).get('reprogrammed_count') or 0),
            'attested_count': len(attestations),
            'evidence_package_count': len(evidence_packages),
            'notarized_evidence_count': int(evidence_summary.get('notarized_count') or 0),
            'expired_evidence_count': int(evidence_summary.get('expired_count') or 0),
            'chain_of_custody_count': len(chain_of_custody_entries),
            'external_signing_count': int(evidence_summary.get('external_signing_count') or 0),
            'object_lock_archive_count': int(evidence_summary.get('object_lock_archive_count') or 0),
            'custody_anchor_count': int(custody_anchor_summary.get('count') or 0),
            'custody_anchor_valid': bool(custody_anchor_summary.get('valid', True)),
            'custody_anchor_reconciliation_conflict_count': int(custody_anchor_summary.get('reconciliation_conflict_count') or 0),
            'custody_anchor_reconciled': bool(custody_anchor_summary.get('reconciled', False)),
            'custody_anchor_quorum_satisfied': bool(custody_anchor_summary.get('quorum_satisfied', False)),
            'custody_anchor_distinct_control_plane_count': int(((custody_anchor_summary.get('quorum') or {}).get('distinct_control_plane_count')) or 0),
            'provider_validation_valid': bool(provider_validation.get('valid', False)),
            'operational_tier': train_policy.get('operational_tier'),
            'evidence_classification': train_policy.get('evidence_classification'),
            'evidence_tier_distribution': dict(evidence_summary.get('operational_tier_counts') or {}),
            'evidence_classification_distribution': dict(evidence_summary.get('classification_counts') or {}),
            'verify_on_read_valid': bool(read_verification.get('valid', True)),
            'verify_on_read_count': int(read_verification.get('count') or 0),
            'policy_conformance_status': policy_conformance.get('overall_status'),
            'policy_conformance_fail_count': int((policy_conformance.get('summary') or {}).get('fail_count') or 0),
            'policy_conformance_warning_count': int((policy_conformance.get('summary') or {}).get('warning_count') or 0),
            'policy_baseline_drift_status': policy_baseline_drift.get('overall_status'),
            'policy_baseline_drift_count': int((policy_baseline_drift.get('summary') or {}).get('count') or 0),
            'policy_baseline_deviation_exception_count': int(deviation_exception_summary.get('count') or 0),
            'drift_count': int((drift_report.get('summary') or {}).get('count') or 0),
            'blocking_drift_count': int((drift_report.get('summary') or {}).get('blocking_count') or 0),
        }
        summary = {
            'bundle_count': len(bundle_ids),
            'bundle_status_counts': bundle_status_counts,
            'calendar_event_count': len(calendar_events),
            'calendar_completed_count': completed_count,
            'calendar_due_count': due_count,
            'calendar_blocked_count': blocked_count,
            'calendar_deferred_count': deferred_count,
            'job_count': int((jobs_payload.get('summary') or {}).get('count') or 0),
            'rollout_status': rollout_status,
            'active_runtime_count': total_active,
            'target_runtime_count': total_targets,
            'approval_pending_count': int(approval_state.get('pending_count') or 0),
            'approval_rejected_count': int(approval_state.get('rejected_count') or 0),
            'approval_satisfied': bool(approval_state.get('satisfied')),
            'simulation_validation_status': simulation.get('validation_status'),
            'simulation_approvable': bool(simulation.get('approvable')),
            'current_attestation_id': current_attestation.get('attestation_id'),
            'attested': bool(current_attestation),
            'evidence_package_count': len(evidence_packages),
            'notarized_evidence_count': int(evidence_summary.get('notarized_count') or 0),
            'chain_of_custody_count': len(chain_of_custody_entries),
            'chain_of_custody_valid': bool(chain_of_custody_summary.get('valid')),
            'custody_anchor_count': len(custody_anchor_receipts),
            'custody_anchor_valid': bool(custody_anchor_summary.get('valid', True)),
            'custody_anchor_reconciliation_conflict_count': int(custody_anchor_summary.get('reconciliation_conflict_count') or 0),
            'custody_anchor_reconciled': bool(custody_anchor_summary.get('reconciled', False)),
            'custody_anchor_quorum_satisfied': bool(custody_anchor_summary.get('quorum_satisfied', False)),
            'provider_validation_valid': bool(provider_validation.get('valid', False)),
            'operational_tier': train_policy.get('operational_tier'),
            'evidence_classification': train_policy.get('evidence_classification'),
            'verify_on_read_valid': bool(read_verification.get('valid', True)),
            'verify_on_read_count': int(read_verification.get('count') or 0),
            'policy_conformance_status': policy_conformance.get('overall_status'),
            'policy_conformance_fail_count': int((policy_conformance.get('summary') or {}).get('fail_count') or 0),
            'policy_conformance_warning_count': int((policy_conformance.get('summary') or {}).get('warning_count') or 0),
            'policy_baseline_drift_status': policy_baseline_drift.get('overall_status'),
            'policy_baseline_drift_count': int((policy_baseline_drift.get('summary') or {}).get('count') or 0),
            'policy_baseline_deviation_exception_count': int(deviation_exception_summary.get('count') or 0),
            'drift_status': drift_report.get('overall_status'),
            'blocking_drift_count': int((drift_report.get('summary') or {}).get('blocking_count') or 0),
        }
        return {
            'ok': True,
            'portfolio_id': str(release.get('release_id') or ''),
            'release': dict(release),
            'portfolio': {
                **portfolio,
                'bundle_ids': bundle_ids,
                'train_policy': train_policy,
                'base_train_policy': base_train_policy,
                'train_calendar': calendar_events,
                'approval_policy': approval_policy,
                'current_attestation': current_attestation or None,
                'operational_tier': train_policy.get('operational_tier'),
                'evidence_classification': train_policy.get('evidence_classification'),
                'environment_tier_policy': train_policy.get('environment_tier_policy'),
                'environment_policy_baseline': self._resolve_portfolio_environment_policy_baseline(base_train_policy, environment=release.get('environment'), gw=gw, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), release=release),
                'baseline_catalog_ref': train_policy.get('baseline_catalog_ref'),
                'baseline_catalog_rollout': dict((((release.get('metadata') or {}).get('portfolio') or {}).get('current_baseline_catalog_rollout') or {}) or {}),
                'security_gate_policy': train_policy.get('security_gate_policy'),
            },
            'bundles': bundles,
            'calendar': {'items': calendar_events, 'summary': {'count': len(calendar_events), 'completed': completed_count, 'due': due_count, 'blocked': blocked_count, 'deferred': deferred_count}},
            'jobs': jobs_payload,
            'summary': summary,
            'analytics': analytics,
            'simulation': simulation,
            'approvals': {'items': approvals, 'summary': approval_state},
            'approval_summary': approval_state,
            'attestations': {'items': attestations, 'summary': {'count': len(attestations), 'current_attestation_id': current_attestation.get('attestation_id'), 'attested': bool(current_attestation)}},
            'evidence_packages': {'items': evidence_packages, 'summary': evidence_summary},
            'chain_of_custody': {'items': chain_of_custody_entries, 'summary': chain_of_custody_summary},
            'custody_anchors': {'items': custody_anchor_receipts, 'summary': custody_anchor_summary, 'reconciliation': dict((((release.get('metadata') or {}).get('portfolio') or {}).get('current_custody_reconciliation') or {}) or {})},
            'provider_validation': provider_validation,
            'read_verification': read_verification,
            'policy_conformance': policy_conformance,
            'policy_baseline_drift': policy_baseline_drift,
            'deviation_exceptions': {'items': self._list_portfolio_policy_deviation_exceptions(release), 'summary': deviation_exception_summary},
            'drift': drift_report,
            'scope': scope,
        }


    def create_runtime_alert_governance_portfolio(
        self,
        gw,
        *,
        name: str,
        version: str,
        bundle_ids: list[str],
        actor: str,
        train_calendar: list[dict[str, Any]] | None = None,
        train_policy: dict[str, Any] | None = None,
        reason: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        normalized_ids: list[str] = []
        base_scope = self._scope(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        for bundle_id in list(bundle_ids or []):
            normalized_bundle_id = str(bundle_id or '').strip()
            if not normalized_bundle_id or normalized_bundle_id in normalized_ids:
                continue
            detail = self.get_runtime_alert_governance_bundle(gw, bundle_id=normalized_bundle_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
            if not detail.get('ok'):
                return {**detail, 'bundle_id': normalized_bundle_id}
            release = dict(detail.get('release') or {})
            scope = self._scope(tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=release.get('environment'))
            if base_scope['tenant_id'] is None:
                base_scope = scope
            elif scope != base_scope:
                return {'ok': False, 'error': 'bundle_scope_mismatch', 'bundle_id': normalized_bundle_id, 'bundle_scope': scope, 'expected_scope': base_scope}
            normalized_ids.append(normalized_bundle_id)
        if not normalized_ids:
            return {'ok': False, 'error': 'bundle_ids_required'}
        train_policy_validation_errors = self._validate_portfolio_train_policy(dict(train_policy or {}))
        if train_policy_validation_errors:
            return {'ok': False, 'error': 'portfolio_train_policy_invalid', 'validation': {'status': 'failed', 'errors': train_policy_validation_errors}}
        normalized_train_policy = self._normalize_portfolio_train_policy(dict(train_policy or {}))
        bundle_items = [
            {'item_kind': 'policy_bundle', 'item_key': bundle_id, 'item_version': '', 'payload': {'bundle_id': bundle_id}}
            for bundle_id in normalized_ids
        ]
        release = gw.audit.create_release_bundle(
            kind='policy_portfolio',
            name=str(name or 'openclaw-governance-portfolio').strip() or 'openclaw-governance-portfolio',
            version=str(version or f'portfolio-{int(time.time())}').strip() or f'portfolio-{int(time.time())}',
            created_by=str(actor or 'admin'),
            items=bundle_items,
            environment=base_scope.get('environment'),
            tenant_id=base_scope.get('tenant_id'),
            workspace_id=base_scope.get('workspace_id'),
            notes=str(reason or '').strip(),
            metadata={
                'portfolio': {
                    'kind': 'openclaw_alert_governance_portfolio',
                    'bundle_ids': normalized_ids,
                    'train_policy': normalized_train_policy,
                    'created_from': {'actor': str(actor or 'admin'), 'reason': str(reason or '').strip()},
                },
            },
            status='draft',
        )
        portfolio_id = str(release.get('release_id') or '')
        metadata = dict(release.get('metadata') or {})
        portfolio = dict(metadata.get('portfolio') or {})
        portfolio['train_calendar'] = self._normalize_release_train_calendar(
            portfolio_id=portfolio_id,
            bundle_ids=normalized_ids,
            train_calendar=train_calendar,
            base_release_at=normalized_train_policy.get('base_release_at'),
            spacing_s=int(normalized_train_policy.get('spacing_s') or 0),
            default_window_s=int(normalized_train_policy.get('default_event_window_s') or 0),
        )
        metadata['portfolio'] = portfolio
        gw.audit.update_release_bundle(portfolio_id, metadata=metadata, tenant_id=base_scope.get('tenant_id'), workspace_id=base_scope.get('workspace_id'), environment=base_scope.get('environment'))
        release = gw.audit.get_release_bundle(portfolio_id, tenant_id=base_scope.get('tenant_id'), workspace_id=base_scope.get('workspace_id'), environment=base_scope.get('environment')) or release
        return self._portfolio_detail_view(gw, release=release)

    def list_runtime_alert_governance_portfolios(self, gw, *, limit: int = 50, status: str | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None, runtime_id: str | None = None) -> dict[str, Any]:
        releases = gw.audit.list_release_bundles(limit=max(limit * 5, limit), status=status, kind='policy_portfolio', tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        items = []
        read_blocked_count = 0
        policy_conformance_status_counts: dict[str, int] = {}
        policy_conformance_fail_count = 0
        policy_conformance_warning_count = 0
        operational_tier_counts: dict[str, int] = {}
        evidence_classification_counts: dict[str, int] = {}
        policy_baseline_drift_status_counts: dict[str, int] = {}
        policy_deviation_exception_count = 0
        for release in releases:
            if not self._is_alert_governance_portfolio_release(release):
                continue
            detail = self._portfolio_detail_view(gw, release=release)
            if runtime_id is not None:
                bundle_matches = False
                for bundle in list(detail.get('bundles') or []):
                    if any(str(item.get('runtime_id') or '') == str(runtime_id or '') for item in list(bundle.get('targets') or [])):
                        bundle_matches = True
                        break
                if not bundle_matches:
                    continue
            verify_on_read = self._enforce_portfolio_verify_on_read(gw, detail=detail, read_kind='list_item')
            if not verify_on_read.get('ok'):
                read_blocked_count += 1
                items.append({
                    'portfolio_id': detail.get('portfolio_id'),
                    'release': detail.get('release'),
                    'read_blocked': True,
                    'error': verify_on_read.get('error'),
                    'read_verification': verify_on_read.get('read_verification'),
                    'scope': detail.get('scope'),
                })
            else:
                if verify_on_read.get('enforced'):
                    detail = dict(verify_on_read.get('detail') or detail)
                tier = str(((detail.get('summary') or {}).get('operational_tier')) or '').strip()
                if tier:
                    operational_tier_counts[tier] = operational_tier_counts.get(tier, 0) + 1
                classification = str(((detail.get('summary') or {}).get('evidence_classification')) or '').strip()
                if classification:
                    evidence_classification_counts[classification] = evidence_classification_counts.get(classification, 0) + 1
                conformance_status = str((((detail.get('policy_conformance') or {}).get('overall_status')) or ((detail.get('summary') or {}).get('policy_conformance_status')) or '')).strip()
                if conformance_status:
                    policy_conformance_status_counts[conformance_status] = policy_conformance_status_counts.get(conformance_status, 0) + 1
                policy_conformance_fail_count += int((((detail.get('policy_conformance') or {}).get('summary') or {}).get('fail_count')) or 0)
                policy_conformance_warning_count += int((((detail.get('policy_conformance') or {}).get('summary') or {}).get('warning_count')) or 0)
                baseline_drift_status = str((((detail.get('policy_baseline_drift') or {}).get('overall_status')) or ((detail.get('summary') or {}).get('policy_baseline_drift_status')) or '')).strip()
                if baseline_drift_status:
                    policy_baseline_drift_status_counts[baseline_drift_status] = policy_baseline_drift_status_counts.get(baseline_drift_status, 0) + 1
                policy_deviation_exception_count += int((((detail.get('deviation_exceptions') or {}).get('summary') or {}).get('count')) or 0)
                items.append({
                    'portfolio_id': detail.get('portfolio_id'),
                    'release': detail.get('release'),
                    'summary': detail.get('summary'),
                    'analytics': detail.get('analytics'),
                    'portfolio': detail.get('portfolio'),
                    'simulation': detail.get('simulation'),
                    'approval_summary': detail.get('approval_summary'),
                    'attestation_summary': ((detail.get('attestations') or {}).get('summary') or {}),
                    'evidence_package_summary': ((detail.get('evidence_packages') or {}).get('summary') or {}),
                    'custody_anchor_summary': ((detail.get('custody_anchors') or {}).get('summary') or {}),
                    'provider_validation': detail.get('provider_validation') or {},
                    'read_verification': detail.get('read_verification') or {},
                    'policy_conformance': detail.get('policy_conformance') or {},
                    'policy_conformance_summary': ((detail.get('policy_conformance') or {}).get('summary') or {}),
                    'policy_baseline_drift': detail.get('policy_baseline_drift') or {},
                    'policy_baseline_drift_summary': ((detail.get('policy_baseline_drift') or {}).get('summary') or {}),
                    'deviation_exception_summary': ((detail.get('deviation_exceptions') or {}).get('summary') or {}),
                    'drift_summary': ((detail.get('drift') or {}).get('summary') or {}),
                    'drift_status': ((detail.get('drift') or {}).get('overall_status')),
                })
            if len(items) >= limit:
                break
        return {
            'ok': True,
            'items': items,
            'summary': {
                'count': len(items),
                'runtime_id': runtime_id,
                'status': status,
                'read_blocked_count': read_blocked_count,
                'policy_conformance_status_counts': policy_conformance_status_counts,
                'policy_conformance_fail_count': policy_conformance_fail_count,
                'policy_conformance_warning_count': policy_conformance_warning_count,
                'operational_tier_counts': operational_tier_counts,
                'evidence_classification_counts': evidence_classification_counts,
                'policy_baseline_drift_status_counts': policy_baseline_drift_status_counts,
                'policy_deviation_exception_count': policy_deviation_exception_count,
            },
            'scope': self._scope(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment),
        }


    def _store_portfolio_read_verification(
        self,
        gw,
        *,
        release: dict[str, Any],
        read_verification: dict[str, Any],
    ) -> dict[str, Any]:
        metadata = dict(release.get('metadata') or {})
        portfolio = dict(metadata.get('portfolio') or {})
        history = [dict(item) for item in list(portfolio.get('read_verification_history') or [])]
        history.append(dict(read_verification))
        portfolio['read_verification_history'] = history[-20:]
        portfolio['current_read_verification'] = dict(read_verification)
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


    def _store_portfolio_policy_conformance(
        self,
        gw,
        *,
        release: dict[str, Any],
        conformance: dict[str, Any],
    ) -> dict[str, Any]:
        metadata = dict(release.get('metadata') or {})
        portfolio = dict(metadata.get('portfolio') or {})
        history = [dict(item) for item in list(portfolio.get('policy_conformance_history') or [])]
        history.append(dict(conformance))
        portfolio['policy_conformance_history'] = history[-20:]
        portfolio['current_policy_conformance'] = dict(conformance)
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

    def _store_portfolio_policy_baseline_drift(
        self,
        gw,
        *,
        release: dict[str, Any],
        drift_report: dict[str, Any],
    ) -> dict[str, Any]:
        metadata = dict(release.get('metadata') or {})
        portfolio = dict(metadata.get('portfolio') or {})
        history = [dict(item) for item in list(portfolio.get('policy_baseline_drift_history') or [])]
        history.append(dict(drift_report))
        portfolio['policy_baseline_drift_history'] = history[-20:]
        portfolio['current_policy_baseline_drift'] = dict(drift_report)
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

    def _store_portfolio_policy_deviation_exceptions(
        self,
        gw,
        *,
        release: dict[str, Any],
        exceptions: list[dict[str, Any]],
        current_exception: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        metadata = dict(release.get('metadata') or {})
        portfolio = dict(metadata.get('portfolio') or {})
        normalized = sorted(
            [dict(item) for item in list(exceptions or [])],
            key=lambda item: (float(item.get('requested_at') or 0.0), str(item.get('exception_id') or '')),
        )
        portfolio['policy_deviation_exceptions'] = normalized[-200:]
        if current_exception is not None:
            portfolio['current_policy_deviation_exception'] = dict(current_exception)
        elif normalized:
            portfolio['current_policy_deviation_exception'] = dict(normalized[-1])
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

    @staticmethod
    def _list_portfolio_policy_deviation_exceptions(release: dict[str, Any]) -> list[dict[str, Any]]:
        portfolio = dict(((release.get('metadata') or {}).get('portfolio') or {}))
        items = [dict(item) for item in list(portfolio.get('policy_deviation_exceptions') or [])]
        items.sort(key=lambda item: (float(item.get('requested_at') or 0.0), str(item.get('exception_id') or '')), reverse=True)
        return items

    def _expire_portfolio_policy_deviation_exceptions(
        self,
        gw,
        *,
        release: dict[str, Any],
        now_ts: float | None = None,
        persist_metadata: bool = True,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        current = [dict(item) for item in self._list_portfolio_policy_deviation_exceptions(release)]
        if not current:
            return release, []
        ts = float(now_ts) if now_ts is not None else time.time()
        changed = False
        expired: list[dict[str, Any]] = []
        for item in current:
            if str(item.get('status') or '') != 'approved':
                continue
            expires_at = item.get('expires_at')
            try:
                normalized_expires_at = float(expires_at) if expires_at is not None else None
            except Exception:
                normalized_expires_at = None
            if normalized_expires_at is None or normalized_expires_at > ts:
                continue
            item['status'] = 'expired'
            item['expired_at'] = ts
            changed = True
            expired.append(dict(item))
        if changed and persist_metadata:
            release = self._store_portfolio_policy_deviation_exceptions(gw, release=release, exceptions=current)
        return release, expired

    @staticmethod
    def _portfolio_policy_baseline_compare_view(*, baseline: dict[str, Any], effective: dict[str, Any]) -> dict[str, Any]:
        keys = [
            'operational_tier',
            'evidence_classification',
            'approval_policy',
            'security_gate_policy',
            'escrow_policy',
            'signing_policy',
            'verification_gate_policy',
        ]
        compare: list[dict[str, Any]] = []
        for field in keys:
            baseline_value = baseline.get(field)
            effective_value = effective.get(field)
            if baseline_value == effective_value:
                continue
            baseline_hash = OpenClawRecoverySchedulerService._stable_digest(baseline_value)
            effective_hash = OpenClawRecoverySchedulerService._stable_digest(effective_value)
            deviation_id = hashlib.sha1(f'{field}:{baseline_hash}:{effective_hash}'.encode('utf-8')).hexdigest()[:20]
            compare.append({
                'deviation_id': deviation_id,
                'field_path': field,
                'field_label': field.replace('_', ' '),
                'baseline_value': baseline_value,
                'effective_value': effective_value,
                'baseline_hash': baseline_hash,
                'effective_hash': effective_hash,
            })
        return {
            'items': compare,
            'baseline_signature': OpenClawRecoverySchedulerService._stable_digest({key: baseline.get(key) for key in keys}),
            'effective_signature': OpenClawRecoverySchedulerService._stable_digest({key: effective.get(key) for key in keys}),
        }


    def _portfolio_policy_baseline_drift_report(
        self,
        gw,
        *,
        release: dict[str, Any],
        persist_metadata: bool = False,
    ) -> dict[str, Any]:
        release, _ = self._expire_portfolio_policy_deviation_exceptions(gw, release=release, persist_metadata=persist_metadata)
        train_policy = self._normalize_portfolio_train_policy(dict((((release.get('metadata') or {}).get('portfolio') or {}).get('train_policy') or {})))
        effective = self._resolve_portfolio_train_policy_for_environment(train_policy, environment=release.get('environment'))
        baseline = self._resolve_portfolio_environment_policy_baseline(train_policy, environment=release.get('environment'), gw=gw, tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), release=release)
        deviation_policy = self._normalize_portfolio_deviation_management_policy(dict(train_policy.get('deviation_management_policy') or {}))
        exceptions = self._list_portfolio_policy_deviation_exceptions(release)
        compare = self._portfolio_policy_baseline_compare_view(baseline=baseline, effective=effective)
        items: list[dict[str, Any]] = []
        status_counts: dict[str, int] = {}
        for change in list(compare.get('items') or []):
            matching = [
                dict(item)
                for item in exceptions
                if str(item.get('deviation_id') or '') == str(change.get('deviation_id') or '')
                and str(item.get('field_path') or '') == str(change.get('field_path') or '')
            ]
            matching.sort(key=lambda item: float(item.get('requested_at') or 0.0), reverse=True)
            active_exception = matching[0] if matching else None
            drift_status = 'unapproved'
            if active_exception is not None:
                exception_status = str(active_exception.get('status') or '')
                if exception_status == 'approved':
                    drift_status = 'approved_exception'
                elif exception_status == 'pending_approval':
                    drift_status = 'pending_exception'
                elif exception_status == 'expired':
                    drift_status = 'expired_exception'
                else:
                    drift_status = exception_status or 'unapproved'
            item = {
                **change,
                'status': drift_status,
                'governed': drift_status == 'approved_exception',
                'exception': active_exception,
            }
            items.append(item)
            status_counts[drift_status] = status_counts.get(drift_status, 0) + 1
        if not bool(baseline.get('configured')):
            overall_status = 'baseline_missing'
        elif not items:
            overall_status = 'aligned'
        elif any(item.get('status') in {'unapproved', 'rejected'} for item in items):
            overall_status = 'drifted'
        elif any(item.get('status') == 'expired_exception' for item in items):
            overall_status = 'expired_exception'
        elif any(item.get('status') == 'pending_exception' for item in items):
            overall_status = 'pending_deviation'
        else:
            overall_status = 'approved_deviation'
        blocking = False
        if overall_status == 'baseline_missing' and bool(deviation_policy.get('block_on_missing_baseline', False)):
            blocking = True
        if overall_status == 'drifted' and bool(deviation_policy.get('block_on_unapproved', True)):
            blocking = True
        if overall_status == 'expired_exception' and bool(deviation_policy.get('block_on_expired', True)):
            blocking = True
        report = {
            'generated_at': time.time(),
            'environment': self._normalize_portfolio_environment_name(release.get('environment')),
            'portfolio_id': str(release.get('release_id') or ''),
            'baseline': baseline,
            'effective_policy': {
                'operational_tier': effective.get('operational_tier'),
                'evidence_classification': effective.get('evidence_classification'),
                'approval_policy': effective.get('approval_policy'),
                'security_gate_policy': effective.get('security_gate_policy'),
                'escrow_policy': effective.get('escrow_policy'),
                'signing_policy': effective.get('signing_policy'),
                'verification_gate_policy': effective.get('verification_gate_policy'),
            },
            'deviation_policy': deviation_policy,
            'overall_status': overall_status,
            'blocking': blocking,
            'items': items,
            'summary': {
                'count': len(items),
                'status_counts': status_counts,
                'approved_count': int(status_counts.get('approved_exception') or 0),
                'pending_count': int(status_counts.get('pending_exception') or 0),
                'expired_count': int(status_counts.get('expired_exception') or 0),
                'unapproved_count': int(status_counts.get('unapproved') or 0) + int(status_counts.get('rejected') or 0),
                'overall_status': overall_status,
                'blocking': blocking,
                'baseline_configured': bool(baseline.get('configured')),
                'baseline_signature': compare.get('baseline_signature'),
                'effective_signature': compare.get('effective_signature'),
            },
            'deviation_exceptions': {
                'items': exceptions,
                'summary': self._portfolio_policy_deviation_exception_summary(release),
            },
        }
        if persist_metadata and bool(deviation_policy.get('persist_drift', True)):
            updated = self._store_portfolio_policy_baseline_drift(gw, release=release, drift_report=report)
            report['release'] = updated
        else:
            report['release'] = release
        return report

    def _portfolio_policy_conformance_report(
        self,
        gw,
        *,
        release: dict[str, Any],
        persist_metadata: bool = False,
    ) -> dict[str, Any]:
        scope = self._scope(tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=release.get('environment'))
        train_policy = self._resolve_portfolio_train_policy_for_environment(
            dict((((release.get('metadata') or {}).get('portfolio') or {}).get('train_policy') or {})),
            environment=release.get('environment'),
        )
        approval_policy = self._normalize_portfolio_approval_policy(dict(train_policy.get('approval_policy') or {}))
        security_gate_policy = self._normalize_portfolio_security_gate_policy(dict(train_policy.get('security_gate_policy') or {}))
        approvals = self._list_portfolio_approvals(
            gw,
            portfolio_id=str(release.get('release_id') or ''),
            limit=max(20, len(list(approval_policy.get('layers') or [])) * 3 + 5),
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        )
        approval_state = self._portfolio_approval_state(
            portfolio_id=str(release.get('release_id') or ''),
            approval_policy=approval_policy,
            approvals=approvals,
        )
        portfolio_meta = dict(((release.get('metadata') or {}).get('portfolio') or {}))
        provider_validation = dict(portfolio_meta.get('current_provider_validation') or {})
        read_verification = dict(portfolio_meta.get('current_read_verification') or {})
        evidence_summary = self._portfolio_evidence_package_summary(release)
        chain_summary = self._portfolio_chain_of_custody_summary(release)
        custody_summary = self._portfolio_custody_anchor_summary(release)
        baseline_drift = self._portfolio_policy_baseline_drift_report(gw, release=release, persist_metadata=False)
        deviation_policy = self._normalize_portfolio_deviation_management_policy(dict(train_policy.get('deviation_management_policy') or {}))
        env_name = self._normalize_portfolio_environment_name(release.get('environment'))
        expected_roles = [str(item).strip() for item in list(security_gate_policy.get('required_approval_roles') or []) if str(item).strip()]
        actual_roles = [str(item.get('requested_role') or '').strip() for item in list(approval_policy.get('layers') or []) if str(item.get('requested_role') or '').strip()]
        checks: list[dict[str, Any]] = []

        def add_check(check_id: str, category: str, status: str, *, expected: Any = None, observed: Any = None, reason: str = '', evidence: dict[str, Any] | None = None) -> None:
            normalized_status = str(status or '').strip().lower() or 'warning'
            if normalized_status not in {'pass', 'warning', 'fail'}:
                normalized_status = 'warning'
            checks.append({
                'check_id': check_id,
                'category': category,
                'status': normalized_status,
                'valid': normalized_status == 'pass',
                'expected': expected,
                'observed': observed,
                'reason': str(reason or '').strip(),
                'evidence': dict(evidence or {}),
            })

        env_policy = dict(train_policy.get('environment_tier_policy') or {})
        env_policy_environment = self._normalize_portfolio_environment_name(env_policy.get('environment')) if env_policy.get('environment') else env_name
        add_check('environment_envelope_resolved', 'environment', 'pass' if env_policy_environment == env_name else 'fail', expected=env_name, observed=env_policy_environment, reason='environment-specific envelope resolved for portfolio environment', evidence={'tier_label': env_policy.get('tier_label'), 'operational_tier': train_policy.get('operational_tier')})

        if approval_policy.get('enabled'):
            add_check('approval_layers_configured', 'approval', 'pass' if len(list(approval_policy.get('layers') or [])) > 0 else 'fail', expected='>=1 layer', observed=len(list(approval_policy.get('layers') or [])), reason='approval envelope must define layers when enabled', evidence={'mode': approval_policy.get('mode')})
        else:
            add_check('approval_layers_configured', 'approval', 'pass', expected='approval disabled or explicitly not required', observed='disabled', reason='environment allows direct promotion without multilayer approval', evidence={'mode': approval_policy.get('mode')})

        min_layers = max(int(security_gate_policy.get('min_approval_layers') or 0), len(expected_roles))
        if min_layers > 0:
            add_check('approval_layer_minimum', 'approval', 'pass' if len(actual_roles) >= min_layers else 'fail', expected=min_layers, observed=len(actual_roles), reason='approval envelope must meet the minimum layer count for this environment', evidence={'roles': actual_roles})
        if expected_roles:
            missing_roles = [role for role in expected_roles if role not in actual_roles]
            add_check('approval_roles_required', 'approval', 'pass' if not missing_roles else 'fail', expected=expected_roles, observed=actual_roles, reason='environment-specific approval roles must be present in the envelope', evidence={'missing_roles': missing_roles})
        release_status = str(release.get('status') or '').strip().lower()
        if approval_policy.get('enabled'):
            if release_status in {'approved', 'promoted'}:
                add_check('approval_state_satisfied', 'approval', 'pass' if bool(approval_state.get('satisfied')) else 'fail', expected=True, observed=bool(approval_state.get('satisfied')), reason='approved portfolios must satisfy the configured approval envelope', evidence={'overall_status': approval_state.get('overall_status'), 'pending_count': approval_state.get('pending_count')})
            elif int(approval_state.get('pending_count') or 0) > 0:
                add_check('approval_state_satisfied', 'approval', 'warning', expected='pending approvals resolved before final approval', observed=approval_state.get('overall_status'), reason='approval envelope is active and still awaiting decisions', evidence={'pending_count': approval_state.get('pending_count')})
            else:
                add_check('approval_state_satisfied', 'approval', 'pass', expected='approval envelope satisfied or not yet engaged', observed=approval_state.get('overall_status'), reason='approval envelope state is internally consistent', evidence={'pending_count': approval_state.get('pending_count')})

        if security_gate_policy.get('enabled'):
            add_check('security_gate_enabled', 'security', 'pass', expected=True, observed=True, reason='environment-specific security gate envelope is enabled', evidence={'envelope_label': security_gate_policy.get('envelope_label')})
        else:
            add_check('security_gate_enabled', 'security', 'warning', expected='security gate policy enabled for regulated environments when required', observed=False, reason='no explicit security gate envelope is configured for this environment', evidence={'envelope_label': security_gate_policy.get('envelope_label')})

        if security_gate_policy.get('require_provider_validation'):
            add_check('provider_validation_current', 'security', 'pass' if bool(provider_validation.get('valid')) else 'fail', expected=True, observed=bool(provider_validation.get('valid')), reason='security envelope requires live provider validation', evidence={'provider_validation': provider_validation})
        if security_gate_policy.get('require_immutable_escrow'):
            immutable_observed = bool(((provider_validation.get('escrow') or {}).get('immutable_backend'))) or bool(((provider_validation.get('escrow') or {}).get('object_lock_backend'))) or int(evidence_summary.get('immutable_archive_count') or 0) > 0 or int(evidence_summary.get('object_lock_archive_count') or 0) > 0
            add_check('immutable_escrow_backend', 'security', 'pass' if immutable_observed else 'fail', expected=True, observed=immutable_observed, reason='environment requires immutable escrow or object-lock/WORM archive', evidence={'escrow': provider_validation.get('escrow'), 'evidence_summary': evidence_summary})
        if security_gate_policy.get('require_external_signing'):
            signing = dict(provider_validation.get('signing') or {})
            external_signing_observed = str(signing.get('key_origin') or '').strip() == 'external' or int(evidence_summary.get('external_signing_count') or 0) > 0
            add_check('external_signing_backend', 'security', 'pass' if external_signing_observed else 'fail', expected=True, observed=external_signing_observed, reason='environment requires externally backed signing material', evidence={'signing': signing, 'evidence_summary': evidence_summary})
        if security_gate_policy.get('require_crypto_signed_evidence'):
            if int(evidence_summary.get('count') or 0) <= 0:
                add_check('crypto_signed_evidence', 'evidence', 'warning', expected='at least one crypto-signed evidence package after export', observed=0, reason='no evidence package exists yet to prove crypto-signed output under this envelope', evidence={'evidence_summary': evidence_summary})
            else:
                add_check('crypto_signed_evidence', 'evidence', 'pass' if int(evidence_summary.get('crypto_signed_count') or 0) > 0 else 'fail', expected='>=1 crypto-signed package', observed=int(evidence_summary.get('crypto_signed_count') or 0), reason='environment requires crypto-signed evidence packages', evidence={'evidence_summary': evidence_summary})
        if security_gate_policy.get('require_chain_of_custody'):
            if int(chain_summary.get('count') or 0) <= 0:
                add_check('chain_of_custody_present', 'evidence', 'warning', expected='chain of custody entries after evidence operations', observed=0, reason='chain of custody has not yet been populated for this portfolio', evidence={'chain_summary': chain_summary})
            else:
                chain_valid = bool(chain_summary.get('valid', True)) if bool(security_gate_policy.get('require_valid_chain_of_custody', True)) else True
                add_check('chain_of_custody_present', 'evidence', 'pass' if chain_valid else 'fail', expected=True, observed=bool(chain_summary.get('valid', True)), reason='environment requires a valid chain of custody', evidence={'chain_summary': chain_summary})
        if security_gate_policy.get('require_custody_anchor'):
            if int(custody_summary.get('count') or 0) <= 0:
                add_check('custody_anchor_present', 'evidence', 'warning', expected='custody anchor receipt after external archive/evidence export', observed=0, reason='no custody anchor has been recorded yet for this portfolio', evidence={'custody_anchor_summary': custody_summary})
            else:
                add_check('custody_anchor_present', 'evidence', 'pass' if bool(custody_summary.get('valid', True)) else 'fail', expected=True, observed=bool(custody_summary.get('valid', True)), reason='environment requires a valid custody anchor receipt', evidence={'custody_anchor_summary': custody_summary})
        if security_gate_policy.get('require_custody_anchor_reconciled'):
            if int(custody_summary.get('count') or 0) <= 0:
                add_check('custody_anchor_reconciled', 'evidence', 'warning', expected='reconciled after anchor creation', observed=False, reason='no custody anchor exists yet to reconcile', evidence={'custody_anchor_summary': custody_summary})
            else:
                add_check('custody_anchor_reconciled', 'evidence', 'pass' if bool(custody_summary.get('reconciled')) else 'fail', expected=True, observed=bool(custody_summary.get('reconciled')), reason='environment requires custody anchor reconciliation', evidence={'custody_anchor_summary': custody_summary})
        if security_gate_policy.get('require_custody_anchor_quorum'):
            if int(custody_summary.get('count') or 0) <= 0:
                add_check('custody_anchor_quorum', 'evidence', 'warning', expected='quorum satisfied after witness attestations', observed=False, reason='no custody anchor exists yet to satisfy quorum', evidence={'custody_anchor_summary': custody_summary})
            else:
                quorum_satisfied = bool(custody_summary.get('quorum_satisfied')) or bool(((custody_summary.get('quorum') or {}).get('authority_satisfied')))
                add_check('custody_anchor_quorum', 'evidence', 'pass' if quorum_satisfied else 'fail', expected=True, observed=quorum_satisfied, reason='environment requires authority/quorum satisfaction for custody anchors', evidence={'custody_anchor_summary': custody_summary})
        verify_on_read_required = bool(security_gate_policy.get('require_read_verification_valid')) or bool((train_policy.get('verification_gate_policy') or {}).get('require_verify_on_read'))
        if verify_on_read_required:
            if not read_verification:
                add_check('read_verification_valid', 'read_path', 'warning', expected='valid verify-on-read record', observed=None, reason='verify-on-read is enabled but no read verification has been recorded yet', evidence={})
            else:
                add_check('read_verification_valid', 'read_path', 'pass' if bool(read_verification.get('valid', False)) else 'fail', expected=True, observed=bool(read_verification.get('valid', False)), reason='environment requires valid verify-on-read state on critical reads', evidence={'read_verification': read_verification})

        baseline_status = str(baseline_drift.get('overall_status') or '').strip() or 'baseline_missing'
        baseline_configured = bool(((baseline_drift.get('summary') or {}).get('baseline_configured')))
        baseline_feature_enabled = bool(dict(train_policy.get('environment_policy_baselines') or {})) or bool(dict(train_policy.get('baseline_catalog_ref') or {}))
        if not baseline_feature_enabled:
            add_check('environment_baseline_defined', 'baseline', 'pass', expected='baseline optional when not configured', observed='not_configured', reason='no environment policy baseline is configured for this portfolio', evidence={})
            add_check('baseline_drift_governed', 'baseline', 'pass', expected='baseline governance optional when not configured', observed='not_configured', reason='baseline drift governance is not enabled for this portfolio', evidence={})
        elif baseline_configured:
            add_check('environment_baseline_defined', 'baseline', 'pass', expected=True, observed=True, reason='environment policy baseline is configured', evidence={'baseline_label': ((baseline_drift.get('baseline') or {}).get('baseline_label'))})
        else:
            add_check('environment_baseline_defined', 'baseline', 'fail' if bool(deviation_policy.get('block_on_missing_baseline', False)) else 'warning', expected=True, observed=False, reason='environment policy baseline is not configured', evidence={'baseline': baseline_drift.get('baseline')})
        if baseline_feature_enabled:
            if baseline_status in {'aligned', 'approved_deviation'}:
                add_check('baseline_drift_governed', 'baseline', 'pass', expected='aligned or governed deviation', observed=baseline_status, reason='effective policy is aligned with baseline or covered by approved exceptions', evidence={'baseline_drift': baseline_drift.get('summary')})
            elif baseline_status == 'pending_deviation':
                add_check('baseline_drift_governed', 'baseline', 'warning', expected='approved deviation before sensitive operations', observed=baseline_status, reason='policy drift exists and is awaiting exception approval', evidence={'baseline_drift': baseline_drift.get('summary')})
            elif baseline_status == 'expired_exception':
                add_check('baseline_drift_governed', 'baseline', 'fail' if bool(deviation_policy.get('block_on_expired', True)) else 'warning', expected='active approved exception', observed=baseline_status, reason='policy deviation exception expired and no longer governs the drift', evidence={'baseline_drift': baseline_drift.get('summary')})
            elif baseline_status == 'drifted':
                add_check('baseline_drift_governed', 'baseline', 'fail' if bool(deviation_policy.get('block_on_unapproved', True)) else 'warning', expected='approved deviation exception', observed=baseline_status, reason='effective policy deviates from the environment baseline without an approved exception', evidence={'baseline_drift': baseline_drift.get('summary')})
            else:
                add_check('baseline_drift_governed', 'baseline', 'warning', expected='baseline governance active', observed=baseline_status, reason='baseline governance could not prove alignment for the current environment', evidence={'baseline_drift': baseline_drift.get('summary')})

        pass_count = sum(1 for item in checks if item.get('status') == 'pass')
        warning_count = sum(1 for item in checks if item.get('status') == 'warning')
        fail_count = sum(1 for item in checks if item.get('status') == 'fail')
        overall_status = 'conformant'
        if fail_count > 0:
            overall_status = 'nonconformant'
        elif warning_count > 0:
            overall_status = 'warning'
        report = {
            'generated_at': time.time(),
            'environment': env_name,
            'operational_tier': train_policy.get('operational_tier'),
            'evidence_classification': train_policy.get('evidence_classification'),
            'release_status': release.get('status'),
            'overall_status': overall_status,
            'conformant': overall_status == 'conformant',
            'checks': checks,
            'summary': {
                'count': len(checks),
                'pass_count': pass_count,
                'warning_count': warning_count,
                'fail_count': fail_count,
                'overall_status': overall_status,
                'conformant': overall_status == 'conformant',
                'environment': env_name,
                'operational_tier': train_policy.get('operational_tier'),
                'evidence_classification': train_policy.get('evidence_classification'),
            },
            'approval_envelope': {
                'enabled': bool(approval_policy.get('enabled')),
                'mode': approval_policy.get('mode'),
                'layer_count': len(list(approval_policy.get('layers') or [])),
                'roles': actual_roles,
                'state': approval_state,
            },
            'security_envelope': {
                'enabled': bool(security_gate_policy.get('enabled')),
                'envelope_label': security_gate_policy.get('envelope_label'),
                'required_provider_validation': bool(security_gate_policy.get('require_provider_validation')),
                'required_crypto_signed_evidence': bool(security_gate_policy.get('require_crypto_signed_evidence')),
                'required_immutable_escrow': bool(security_gate_policy.get('require_immutable_escrow')),
                'required_external_signing': bool(security_gate_policy.get('require_external_signing')),
                'required_chain_of_custody': bool(security_gate_policy.get('require_chain_of_custody')),
                'required_custody_anchor': bool(security_gate_policy.get('require_custody_anchor')),
                'required_custody_anchor_reconciled': bool(security_gate_policy.get('require_custody_anchor_reconciled')),
                'required_custody_anchor_quorum': bool(security_gate_policy.get('require_custody_anchor_quorum')),
                'required_read_verification_valid': bool(security_gate_policy.get('require_read_verification_valid')),
            },
            'evidence_state': {
                'provider_validation': provider_validation,
                'read_verification': read_verification,
                'evidence_packages': evidence_summary,
                'chain_of_custody': chain_summary,
                'custody_anchors': custody_summary,
                'policy_baseline_drift': baseline_drift,
            },
            'scope': scope,
        }
        if persist_metadata:
            updated = self._store_portfolio_policy_conformance(gw, release=release, conformance=report)
            report['release'] = updated
        else:
            report['release'] = release
        return report

    def _enforce_portfolio_security_envelope(
        self,
        gw,
        *,
        detail: dict[str, Any],
        actor: str,
        operation: str,
    ) -> dict[str, Any]:
        release = dict(detail.get('release') or {})
        train_policy = self._resolve_portfolio_train_policy_for_environment(dict((((detail.get('portfolio') or {}).get('train_policy')) or {})), environment=release.get('environment'))
        security_gate_policy = dict(train_policy.get('security_gate_policy') or {})
        if not bool(security_gate_policy.get('enabled')):
            return {'ok': True, 'enforced': False, 'operation': operation, 'reason': 'security_envelope_disabled'}
        must_enforce = (
            (operation == 'sensitive_export' and bool(security_gate_policy.get('enforce_before_sensitive_export', False)))
            or (operation == 'sensitive_restore' and bool(security_gate_policy.get('enforce_before_sensitive_restore', False)))
            or (operation == 'approval_finalize' and bool(security_gate_policy.get('enforce_before_approval_finalize', False)))
        )
        if not must_enforce:
            return {'ok': True, 'enforced': False, 'operation': operation, 'reason': 'security_envelope_not_required'}
        conformance = self._portfolio_policy_conformance_report(gw, release=release, persist_metadata=True)
        if conformance.get('overall_status') == 'nonconformant' and bool(security_gate_policy.get('block_on_nonconformance', True)):
            return {'ok': False, 'error': 'portfolio_security_envelope_failed', 'reason': 'policy_conformance_nonconformant', 'operation': operation, 'policy_conformance': conformance}
        return {'ok': True, 'enforced': True, 'operation': operation, 'policy_conformance': conformance}

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

    def list_release_train_jobs(self, gw, *, limit: int = 100, portfolio_id: str | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any]:
        payload = self._list_jobs_by_family(
            gw,
            matcher=lambda item: self._is_release_train_job(item, portfolio_id=portfolio_id),
            limit=limit,
            enabled=None,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            batch_size=max(limit, 50),
        )
        return {'ok': True, 'items': payload['items'], 'summary': {**payload['summary'], 'portfolio_id': portfolio_id}}

    def _run_single_release_train_job(self, gw, *, item: dict[str, Any], actor: str) -> dict[str, Any]:
        definition = dict((item or {}).get('workflow_definition') or {})
        portfolio_id = str(definition.get('portfolio_id') or '')
        event_id = str(definition.get('event_id') or '')
        bundle_id = str(definition.get('bundle_id') or '')
        wave_no = int(definition.get('wave_no') or 1)
        detail = self.get_runtime_alert_governance_portfolio(gw, portfolio_id=portfolio_id, tenant_id=item.get('tenant_id'), workspace_id=item.get('workspace_id'), environment=item.get('environment'), read_kind='action_context')
        if not detail.get('ok'):
            gw.audit.update_job_schedule(str(item.get('job_id') or ''), enabled=False, last_error=str(detail.get('error') or 'portfolio_not_found'), run_count=int(item.get('run_count') or 0) + 1, last_run_at=time.time(), tenant_id=item.get('tenant_id'), workspace_id=item.get('workspace_id'), environment=item.get('environment'))
            return {'ok': False, 'job_id': item.get('job_id'), 'portfolio_id': portfolio_id, 'error': detail.get('error')}
        sim_items = {str(event.get('event_id') or ''): dict(event) for event in list((detail.get('simulation') or {}).get('items') or [])}
        sim_event = sim_items.get(event_id)
        drift_payload = self.detect_runtime_alert_governance_portfolio_drift(
            gw,
            portfolio_id=portfolio_id,
            actor=actor,
            tenant_id=item.get('tenant_id'),
            workspace_id=item.get('workspace_id'),
            environment=item.get('environment'),
            persist_metadata=True,
        )
        drift_report = dict(drift_payload.get('drift') or {})
        drift_items = {str(entry.get('event_id') or ''): dict(entry) for entry in list(drift_report.get('items') or [])}
        event_drift = drift_items.get(event_id)
        if str(drift_report.get('overall_status') or '') == 'no_attestation' and bool(drift_report.get('block_execution')):
            self._complete_job_execution(gw, item=item, last_error='portfolio_execution_attestation_missing', next_run_at_override=None, enabled=False)
            return {'ok': False, 'job_id': item.get('job_id'), 'portfolio_id': portfolio_id, 'event_id': event_id, 'bundle_id': bundle_id, 'wave_no': wave_no, 'error': 'portfolio_execution_attestation_missing', 'drift': drift_report}
        if event_drift is not None and int(event_drift.get('blocking_count') or 0) > 0:
            release = dict(detail.get('release') or {})
            metadata = dict(release.get('metadata') or {})
            portfolio = dict(metadata.get('portfolio') or {})
            events = [dict(ev) for ev in list(portfolio.get('train_calendar') or [])]
            for idx, event in enumerate(events):
                if str(event.get('event_id') or '') != event_id:
                    continue
                updated = dict(event)
                updated['status'] = 'drift_blocked'
                updated['last_run_at'] = time.time()
                updated['run_count'] = int(updated.get('run_count') or 0) + 1
                updated['result'] = {'ok': False, 'error': 'portfolio_execution_drift_detected', 'drift': event_drift}
                events[idx] = updated
                break
            portfolio['train_calendar'] = events
            metadata['portfolio'] = portfolio
            gw.audit.update_release_bundle(portfolio_id, metadata=metadata, tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=release.get('environment'))
            self._complete_job_execution(gw, item=item, last_error='portfolio_execution_drift_detected', next_run_at_override=None, enabled=False)
            return {'ok': False, 'job_id': item.get('job_id'), 'portfolio_id': portfolio_id, 'event_id': event_id, 'bundle_id': bundle_id, 'wave_no': wave_no, 'error': 'portfolio_execution_drift_detected', 'drift': drift_report, 'event_drift': event_drift}
        if sim_event is not None and str(sim_event.get('simulation_status') or '') == 'blocked':
            self._complete_job_execution(gw, item=item, last_error='event_blocked_by_simulation', next_run_at_override=None, enabled=False)
            return {'ok': False, 'job_id': item.get('job_id'), 'portfolio_id': portfolio_id, 'event_id': event_id, 'bundle_id': bundle_id, 'wave_no': wave_no, 'error': 'event_blocked_by_simulation', 'simulation_event': sim_event}
        result = self.run_runtime_alert_governance_bundle_wave(gw, bundle_id=bundle_id, wave_no=wave_no, actor=actor, reason=str(definition.get('reason') or ''), tenant_id=item.get('tenant_id'), workspace_id=item.get('workspace_id'), environment=item.get('environment'))
        release = dict(detail.get('release') or {})
        metadata = dict(release.get('metadata') or {})
        portfolio = dict(metadata.get('portfolio') or {})
        events = [dict(ev) for ev in list(portfolio.get('train_calendar') or [])]
        for idx, event in enumerate(events):
            if str(event.get('event_id') or '') == event_id:
                updated = dict(event)
                updated['last_run_at'] = time.time()
                updated['run_count'] = int(updated.get('run_count') or 0) + 1
                updated['result'] = {'ok': bool(result.get('ok')), 'rollout_status': ((result.get('summary') or {}).get('rollout_status')), 'errors': ((result.get('wave_execution') or {}).get('errors'))}
                updated['status'] = 'completed' if result.get('ok') else 'error'
                events[idx] = updated
                break
        portfolio['train_calendar'] = events
        metadata['portfolio'] = portfolio
        gw.audit.update_release_bundle(portfolio_id, metadata=metadata, tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=release.get('environment'))
        self._complete_job_execution(gw, item=item, last_error='' if result.get('ok') else str(result.get('error') or 'bundle_wave_failed'), next_run_at_override=None, enabled=False)
        return {'ok': bool(result.get('ok')), 'job_id': item.get('job_id'), 'portfolio_id': portfolio_id, 'event_id': event_id, 'bundle_id': bundle_id, 'wave_no': wave_no, 'result': result}

    def run_due_release_train_jobs(self, gw, *, actor: str, limit: int = 20, portfolio_id: str | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any]:
        payload = self._run_due_jobs_by_family(
            gw,
            matcher=lambda item: self._is_release_train_job(item, portfolio_id=portfolio_id),
            runner=self._run_single_release_train_job,
            actor=actor,
            limit=limit,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            batch_size=max(limit, 50),
        )
        return {'ok': True, 'items': payload['items'], 'summary': {**payload['summary'], 'portfolio_id': portfolio_id}}

