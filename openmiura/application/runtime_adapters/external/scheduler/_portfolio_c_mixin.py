"""scheduler._portfolio_c_mixin

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


class _OpenClawRecoverySchedulerServicePortfolioCMixin:
    """Sub-mixin: portfolio c."""

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

