"""scheduler._recovery_jobs_mixin

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


class _OpenClawRecoverySchedulerServiceRecoveryJobsMixin:
    """Sub-mixin: recovery jobs."""

    @classmethod
    def _is_recovery_job(cls, item: dict[str, Any] | None, *, runtime_id: str | None = None) -> bool:
        return is_workflow_job(item, kind=cls.JOB_KIND, field_name='runtime_id' if runtime_id is not None else None, field_value=runtime_id)

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

