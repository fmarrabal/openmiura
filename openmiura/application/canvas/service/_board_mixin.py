"""openmiura.application.canvas.service._board_mixin

Part of the canvas service split. Methods originally lived on
``openmiura.application.canvas.service.LiveCanvasService``; they
have been moved verbatim into this mixin so that no individual
file in the package exceeds the project's ``max 1,500 lines``
ceiling. The public class still inherits from this mixin and
exposes every method unchanged.
"""

from __future__ import annotations

import json
import time
import uuid
from collections import Counter
from typing import Any

from openmiura.application.canvas.helpers import (
    enforce_canvas_counts as canvas_enforce_counts,
    enforce_canvas_payload as canvas_enforce_payload,
    enforce_scope_limits as canvas_enforce_scope_limits,
    normalize_toggles as canvas_normalize_toggles,
    payload_size as canvas_payload_size,
    redact_sensitive as canvas_redact_sensitive,
    safe_call as canvas_safe_call,
    sanitize_scope as canvas_sanitize_scope,
)
from openmiura.application.packaging import PackagingHardeningService
from openmiura.core.contracts import AdminGatewayLike


class _LiveCanvasBoardMixin:
    """Mixin: board methods on LiveCanvasService."""

    def _runtime_board_entry(
        self,
        gw: AdminGatewayLike,
        *,
        node: dict[str, Any],
        scope: dict[str, Any],
        limit: int = 10,
    ) -> dict[str, Any]:
        data = dict(node.get('data') or {})
        runtime_id = str(data.get('runtime_id') or '').strip()
        runtime_detail = self.openclaw_adapter_service.get_runtime(
            gw,
            runtime_id=runtime_id,
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        ) if runtime_id else {'ok': False, 'error': 'runtime_not_found'}
        runtime = dict(runtime_detail.get('runtime') or {})
        runtime_summary = dict(runtime_detail.get('runtime_summary') or {})
        health = dict(runtime_detail.get('health') or {})
        dispatches_payload = self.openclaw_adapter_service.list_dispatches(
            gw,
            runtime_id=runtime_id or None,
            limit=max(1, int(limit)),
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        ) if runtime_id else {'ok': True, 'items': [], 'summary': {'canonical_state_counts': {}}}
        dispatches = list(dispatches_payload.get('items') or [])
        canonical_state_counts = dict((dispatches_payload.get('summary') or {}).get('canonical_state_counts') or {})
        active_runs = [
            item for item in dispatches
            if str(item.get('canonical_status') or '').strip().lower() in {'requested', 'accepted', 'queued', 'running'}
        ]
        terminal_runs = [
            item for item in dispatches
            if bool(item.get('terminal')) or str(item.get('canonical_status') or '').strip().lower() in {'completed', 'failed', 'cancelled', 'timed_out'}
        ]
        latest_run = dispatches[0] if dispatches else None
        warnings: list[str] = []
        heartbeat_policy = dict(runtime_summary.get('heartbeat_policy') or {})
        stale_active_runs = [
            item for item in active_runs
            if (time.time() - float(self.openclaw_adapter_service._dispatch_signal_ts(item) or 0.0)) >= float(heartbeat_policy.get('active_run_stale_after_s') or 0.0)
        ] if active_runs else []
        health_status = str(health.get('status') or runtime.get('last_health_status') or 'unknown').strip().lower() or 'unknown'
        if health_status in {'degraded', 'unhealthy'}:
            warnings.append(f'runtime_health:{health_status}')
        if bool(health.get('stale')):
            warnings.append('runtime_health:stale')
        recovery_jobs_payload = self.openclaw_recovery_scheduler_service.list_recovery_jobs(
            gw,
            limit=5,
            enabled=None,
            runtime_id=runtime_id or None,
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        ) if runtime_id else {'ok': True, 'items': [], 'summary': {'count': 0, 'due': 0}}
        recovery_jobs = list(recovery_jobs_payload.get('items') or [])
        concurrency_payload = self.openclaw_recovery_scheduler_service.get_runtime_concurrency(
            gw,
            runtime_id=runtime_id,
            limit=max(10, int(limit)),
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        ) if runtime_id else {'ok': True, 'leases': [], 'idempotency_records': [], 'summary': {}}
        concurrency_summary = dict(concurrency_payload.get('summary') or {})
        alerts_payload = self.openclaw_recovery_scheduler_service.evaluate_runtime_alerts(
            gw,
            runtime_id=runtime_id,
            limit=max(10, int(limit)),
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        ) if runtime_id else {'ok': True, 'items': [], 'summary': {}}
        alerts_summary = dict(alerts_payload.get('summary') or {})
        alert_approvals_payload = self.openclaw_recovery_scheduler_service.list_alert_escalation_approvals(
            gw,
            runtime_id=runtime_id,
            limit=max(10, int(limit)),
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        ) if runtime_id else {'ok': True, 'items': [], 'summary': {'count': 0, 'status_counts': {}}}
        alert_approvals_summary = dict(alert_approvals_payload.get('summary') or {})
        notification_targets_payload = self.openclaw_recovery_scheduler_service.list_runtime_notification_targets(
            gw,
            runtime_id=runtime_id,
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        ) if runtime_id else {'ok': True, 'items': [], 'summary': {'count': 0}}
        alert_dispatches_payload = self.openclaw_recovery_scheduler_service.list_runtime_alert_notification_dispatches(
            gw,
            runtime_id=runtime_id,
            limit=max(10, int(limit)),
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        ) if runtime_id else {'ok': True, 'items': [], 'summary': {'count': 0, 'status_counts': {}, 'type_counts': {}}}
        alert_dispatches_summary = dict(alert_dispatches_payload.get('summary') or {})
        routing_payload = self.openclaw_recovery_scheduler_service.get_runtime_alert_routing(
            gw,
            runtime_id=runtime_id,
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        ) if runtime_id else {'ok': True, 'routing_policy': {}, 'summary': {'rule_count': 0, 'escalation_chain_count': 0}}
        governance_payload = self.openclaw_recovery_scheduler_service.get_runtime_alert_governance(
            gw,
            runtime_id=runtime_id,
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
            limit=max(10, int(limit)),
        ) if runtime_id else {'ok': True, 'policy': {}, 'current': {}, 'summary': {'suppressed_alert_count': 0, 'scheduled_alert_count': 0, 'active_override_count': 0}}
        governance_versions_payload = self.openclaw_recovery_scheduler_service.list_runtime_alert_governance_versions(
            gw,
            runtime_id=runtime_id,
            limit=max(10, int(limit)),
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        ) if runtime_id else {'ok': True, 'items': [], 'current_version': None, 'summary': {'count': 0, 'current_version_id': None, 'current_version_no': None}}
        governance_promotion_approvals_payload = self.openclaw_recovery_scheduler_service.list_runtime_alert_governance_promotion_approvals(
            gw,
            runtime_id=runtime_id,
            limit=max(10, int(limit)),
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        ) if runtime_id else {'ok': True, 'items': [], 'summary': {'count': 0, 'pending_count': 0, 'approved_count': 0, 'rejected_count': 0}}
        governance_bundles_payload = self.openclaw_recovery_scheduler_service.list_runtime_alert_governance_bundles(
            gw,
            runtime_id=runtime_id,
            limit=max(10, int(limit)),
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        ) if runtime_id else {'ok': True, 'items': [], 'summary': {'count': 0}}
        governance_portfolios_payload = self.openclaw_recovery_scheduler_service.list_runtime_alert_governance_portfolios(
            gw,
            runtime_id=runtime_id,
            limit=max(10, int(limit)),
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        ) if runtime_id else {'ok': True, 'items': [], 'summary': {'count': 0}}
        alert_delivery_jobs_payload = self.openclaw_recovery_scheduler_service.list_alert_delivery_jobs(
            gw,
            runtime_id=runtime_id,
            limit=max(10, int(limit)),
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        ) if runtime_id else {'ok': True, 'items': [], 'summary': {'count': 0, 'due': 0}}
        alert_delivery_jobs_summary = dict(alert_delivery_jobs_payload.get('summary') or {})
        governance_summary = dict(governance_payload.get('summary') or {})
        governance_current = dict(governance_payload.get('current') or {})
        governance_versions_summary = dict(governance_versions_payload.get('summary') or {})
        governance_promotion_approvals_summary = dict(governance_promotion_approvals_payload.get('summary') or {})
        governance_bundles_summary = dict(governance_bundles_payload.get('summary') or {})
        governance_bundle_items = list(governance_bundles_payload.get('items') or [])
        governance_portfolios_summary = dict(governance_portfolios_payload.get('summary') or {})
        governance_portfolio_items = list(governance_portfolios_payload.get('items') or [])
        governance_bundle_rollout_status_counts: dict[str, int] = {}
        governance_portfolio_rollout_status_counts: dict[str, int] = {}
        governance_bundle_max_exposure_ratio = 0.0
        governance_portfolio_calendar_due_count = 0
        governance_portfolio_pending_approval_count = 0
        governance_portfolio_blocked_count = 0
        governance_portfolio_deferred_count = 0
        governance_portfolio_attested_count = 0
        governance_portfolio_evidence_package_count = 0
        governance_portfolio_notarized_evidence_count = 0
        governance_portfolio_escrowed_evidence_count = 0
        governance_portfolio_crypto_signed_evidence_count = 0
        governance_portfolio_object_lock_evidence_count = 0
        governance_portfolio_external_signing_evidence_count = 0
        governance_portfolio_custody_anchor_count = 0
        governance_portfolio_custody_reconciled_count = 0
        governance_portfolio_custody_reconciliation_conflict_count = 0
        governance_portfolio_custody_quorum_satisfied_count = 0
        governance_portfolio_provider_validation_count = 0
        governance_portfolio_chain_of_custody_count = 0
        governance_portfolio_drifted_count = 0
        governance_portfolio_blocking_drift_count = 0
        governance_portfolio_read_blocked_count = 0
        governance_portfolio_policy_conformance_status_counts: dict[str, int] = {}
        governance_portfolio_policy_conformance_fail_count = 0
        governance_portfolio_policy_conformance_warning_count = 0
        governance_portfolio_policy_baseline_drift_status_counts: dict[str, int] = {}
        governance_portfolio_policy_deviation_exception_count = 0
        governance_portfolio_operational_tier_counts: dict[str, int] = {}
        governance_portfolio_evidence_classification_counts: dict[str, int] = {}
        for _bundle_item in governance_bundle_items:
            _status = str(((_bundle_item.get('summary') or {}).get('rollout_status')) or 'unknown')
            governance_bundle_rollout_status_counts[_status] = governance_bundle_rollout_status_counts.get(_status, 0) + 1
            _analytics = dict(_bundle_item.get('analytics') or {})
            try:
                governance_bundle_max_exposure_ratio = max(governance_bundle_max_exposure_ratio, float(_analytics.get('current_exposure_ratio') or 0.0))
            except Exception:
                pass
        for _portfolio_item in governance_portfolio_items:
            if bool(_portfolio_item.get('read_blocked')):
                governance_portfolio_read_blocked_count += 1
                continue
            _status = str(((_portfolio_item.get('summary') or {}).get('rollout_status')) or 'unknown')
            governance_portfolio_rollout_status_counts[_status] = governance_portfolio_rollout_status_counts.get(_status, 0) + 1
            try:
                governance_portfolio_calendar_due_count += int(((_portfolio_item.get('analytics') or {}).get('calendar_due_count')) or 0)
            except Exception:
                pass
            try:
                governance_portfolio_pending_approval_count += int(((_portfolio_item.get('approval_summary') or {}).get('pending_count')) or 0)
            except Exception:
                pass
            try:
                governance_portfolio_blocked_count += int((((_portfolio_item.get('simulation') or {}).get('summary') or {}).get('blocked_count')) or 0)
            except Exception:
                pass
            try:
                governance_portfolio_deferred_count += int((((_portfolio_item.get('simulation') or {}).get('summary') or {}).get('deferred_count')) or 0)
            except Exception:
                pass
            try:
                governance_portfolio_attested_count += 1 if bool(((_portfolio_item.get('attestation_summary') or {}).get('attested'))) else 0
            except Exception:
                pass
            try:
                governance_portfolio_evidence_package_count += int((((_portfolio_item.get('evidence_package_summary') or {}).get('count')) or 0))
            except Exception:
                pass
            try:
                governance_portfolio_notarized_evidence_count += int((((_portfolio_item.get('evidence_package_summary') or {}).get('notarized_count')) or 0))
            except Exception:
                pass
            try:
                governance_portfolio_escrowed_evidence_count += int((((_portfolio_item.get('evidence_package_summary') or {}).get('escrowed_count')) or 0))
            except Exception:
                pass
            try:
                governance_portfolio_crypto_signed_evidence_count += int((((_portfolio_item.get('evidence_package_summary') or {}).get('crypto_signed_count')) or 0))
            except Exception:
                pass
            try:
                governance_portfolio_object_lock_evidence_count += int((((_portfolio_item.get('evidence_package_summary') or {}).get('object_lock_archive_count')) or 0))
            except Exception:
                pass
            try:
                governance_portfolio_external_signing_evidence_count += int((((_portfolio_item.get('evidence_package_summary') or {}).get('external_signing_count')) or 0))
            except Exception:
                pass
            try:
                governance_portfolio_custody_anchor_count += int((((_portfolio_item.get('evidence_package_summary') or {}).get('custody_anchor_count')) or 0))
            except Exception:
                pass
            try:
                governance_portfolio_custody_reconciled_count += 1 if bool(((_portfolio_item.get('custody_anchor_summary') or {}).get('reconciled'))) else 0
            except Exception:
                pass
            try:
                governance_portfolio_custody_reconciliation_conflict_count += int((((_portfolio_item.get('custody_anchor_summary') or {}).get('reconciliation_conflict_count')) or 0))
            except Exception:
                pass
            try:
                governance_portfolio_custody_quorum_satisfied_count += 1 if bool(((_portfolio_item.get('custody_anchor_summary') or {}).get('quorum_satisfied'))) else 0
            except Exception:
                pass
            try:
                governance_portfolio_provider_validation_count += 1 if bool(((_portfolio_item.get('summary') or {}).get('provider_validation_valid'))) else 0
            except Exception:
                pass
            try:
                _tier = str(((_portfolio_item.get('summary') or {}).get('operational_tier')) or '').strip()
                if _tier:
                    governance_portfolio_operational_tier_counts[_tier] = governance_portfolio_operational_tier_counts.get(_tier, 0) + 1
                _classification = str(((_portfolio_item.get('summary') or {}).get('evidence_classification')) or '').strip()
                if _classification:
                    governance_portfolio_evidence_classification_counts[_classification] = governance_portfolio_evidence_classification_counts.get(_classification, 0) + 1
                _conformance_status = str(((_portfolio_item.get('policy_conformance_summary') or {}).get('overall_status')) or ((_portfolio_item.get('summary') or {}).get('policy_conformance_status')) or '').strip()
                if _conformance_status:
                    governance_portfolio_policy_conformance_status_counts[_conformance_status] = governance_portfolio_policy_conformance_status_counts.get(_conformance_status, 0) + 1
                governance_portfolio_policy_conformance_fail_count += int(((_portfolio_item.get('policy_conformance_summary') or {}).get('fail_count')) or 0)
                governance_portfolio_policy_conformance_warning_count += int(((_portfolio_item.get('policy_conformance_summary') or {}).get('warning_count')) or 0)
                _baseline_drift_status = str(((_portfolio_item.get('policy_baseline_drift_summary') or {}).get('overall_status')) or ((_portfolio_item.get('summary') or {}).get('policy_baseline_drift_status')) or '').strip()
                if _baseline_drift_status:
                    governance_portfolio_policy_baseline_drift_status_counts[_baseline_drift_status] = governance_portfolio_policy_baseline_drift_status_counts.get(_baseline_drift_status, 0) + 1
                governance_portfolio_policy_deviation_exception_count += int(((_portfolio_item.get('deviation_exception_summary') or {}).get('count')) or 0)
            except Exception:
                pass
            try:
                governance_portfolio_chain_of_custody_count += int((((_portfolio_item.get('analytics') or {}).get('chain_of_custody_count')) or 0))
            except Exception:
                pass
            try:
                if str(_portfolio_item.get('drift_status') or '') in {'drift_detected', 'blocking_drift', 'no_attestation'}:
                    governance_portfolio_drifted_count += 1
            except Exception:
                pass
            try:
                governance_portfolio_blocking_drift_count += int((((_portfolio_item.get('drift_summary') or {}).get('blocking_count')) or 0))
            except Exception:
                pass
        event_bridge = dict(runtime_summary.get('event_bridge') or {})
        session_bridge = dict(runtime_summary.get('session_bridge') or {})
        if runtime_summary.get('dispatch_policy', {}).get('dispatch_mode') == 'async' and not bool(event_bridge.get('enabled')):
            warnings.append('event_bridge:disabled_for_async')
        if session_bridge.get('enabled') and not session_bridge.get('workspace_connection'):
            warnings.append('session_bridge:missing_workspace_connection')
        if active_runs and bool(health.get('stale')):
            warnings.append('active_runs:stale_runtime_health')
        if stale_active_runs:
            warnings.append('active_runs:stale_detected')
        if bool(concurrency_summary.get('runtime_lock_active')):
            warnings.append('scheduler:runtime_lock_active')
        if (concurrency_summary.get('workspace_slot_pressure_ratio') or 0) >= 1.0:
            warnings.append('scheduler:workspace_slot_saturated')
        if (concurrency_summary.get('runtime_run_pressure_ratio') or 0) >= 1.0:
            warnings.append('dispatch:runtime_backpressure')
        if (concurrency_summary.get('workspace_run_pressure_ratio') or 0) >= 1.0:
            warnings.append('dispatch:workspace_backpressure')
        if int(concurrency_summary.get('in_progress_idempotency_count') or 0) > 0:
            warnings.append('scheduler:idempotency_in_progress')
        if bool(governance_current.get('quiet_hours_active')):
            warnings.append('alert_governance:quiet_hours')
        if bool(governance_current.get('maintenance_active')):
            warnings.append('alert_governance:maintenance_window')
        if bool(governance_current.get('storm_active')):
            warnings.append('alert_governance:alert_storm')
        return {
            'node_id': node.get('node_id'),
            'label': node.get('label'),
            'node_type': node.get('node_type'),
            'runtime_id': runtime_id,
            'runtime': runtime,
            'runtime_summary': runtime_summary,
            'health': health,
            'latest_run': latest_run,
            'recent_runs': dispatches,
            'active_runs': active_runs,
            'recovery_jobs': recovery_jobs,
            'concurrency': concurrency_payload,
            'alerts': alerts_payload,
            'alert_approvals': alert_approvals_payload,
            'notification_targets': notification_targets_payload,
            'alert_dispatches': alert_dispatches_payload,
            'alert_routing': routing_payload,
            'alert_governance': governance_payload,
            'alert_governance_versions': governance_versions_payload,
            'alert_governance_promotion_approvals': governance_promotion_approvals_payload,
            'alert_governance_bundles': governance_bundles_payload,
            'alert_governance_portfolios': governance_portfolios_payload,
            'alert_governance_bundle_rollout_status_counts': governance_bundle_rollout_status_counts,
            'alert_governance_portfolio_rollout_status_counts': governance_portfolio_rollout_status_counts,
            'alert_delivery_jobs': alert_delivery_jobs_payload,
            'summary': {
                'count': len(dispatches),
                'active_count': len(active_runs),
                'terminal_count': len(terminal_runs),
                'stale_active_count': len(stale_active_runs),
                'canonical_state_counts': canonical_state_counts,
                'warnings': warnings,
                'recovery_jobs_count': int((recovery_jobs_payload.get('summary') or {}).get('count') or 0),
                'recovery_due_count': int((recovery_jobs_payload.get('summary') or {}).get('due') or 0),
                'active_leases': int(concurrency_summary.get('active_leases') or 0),
                'in_progress_idempotency_count': int(concurrency_summary.get('in_progress_idempotency_count') or 0),
                'workspace_slot_pressure_ratio': concurrency_summary.get('workspace_slot_pressure_ratio'),
                'runtime_run_pressure_ratio': concurrency_summary.get('runtime_run_pressure_ratio'),
                'workspace_run_pressure_ratio': concurrency_summary.get('workspace_run_pressure_ratio'),
                'alert_count': int(alerts_summary.get('count') or 0),
                'critical_alert_count': int(alerts_summary.get('critical_count') or 0),
                'warn_alert_count': int(alerts_summary.get('warn_count') or 0),
                'highest_alert_severity': alerts_summary.get('highest_severity'),
                'alert_code_counts': dict(alerts_summary.get('code_counts') or {}),
                'alert_workflow_status_counts': dict(alerts_summary.get('workflow_status_counts') or {}),
                'silenced_alert_count': int(alerts_summary.get('silenced_count') or 0),
                'suppressed_alert_count': int(alerts_summary.get('suppressed_count') or 0),
                'escalated_alert_count': int(alerts_summary.get('escalated_count') or 0),
                'acked_alert_count': int(alerts_summary.get('acked_count') or 0),
                'pending_alert_approval_count': int(alert_approvals_summary.get('pending_count') or 0),
                'approved_alert_approval_count': int(alert_approvals_summary.get('approved_count') or 0),
                'rejected_alert_approval_count': int(alert_approvals_summary.get('rejected_count') or 0),
                'notification_target_count': int((notification_targets_payload.get('summary') or {}).get('count') or 0),
                'alert_dispatch_count': int(alert_dispatches_summary.get('count') or 0),
                'alert_dispatch_status_counts': dict(alert_dispatches_summary.get('status_counts') or {}),
                'alert_dispatch_type_counts': dict(alert_dispatches_summary.get('type_counts') or {}),
                'rate_limited_dispatch_count': int(dict(alert_dispatches_summary.get('status_counts') or {}).get('rate_limited') or 0),
                'routing_rule_count': int((routing_payload.get('summary') or {}).get('rule_count') or 0),
                'escalation_chain_count': int((routing_payload.get('summary') or {}).get('escalation_chain_count') or 0),
                'quiet_hours_active': bool(governance_current.get('quiet_hours_active')),
                'maintenance_active': bool(governance_current.get('maintenance_active')),
                'storm_active': bool(governance_current.get('storm_active')),
                'governance_suppressed_alert_count': int(governance_summary.get('suppressed_alert_count') or 0),
                'governance_scheduled_alert_count': int(governance_summary.get('scheduled_alert_count') or 0),
                'active_override_count': int(governance_summary.get('active_override_count') or 0),
                'governance_version_count': int(governance_versions_summary.get('count') or 0),
                'pending_governance_promotion_approval_count': int(governance_promotion_approvals_summary.get('pending_count') or 0),
                'governance_bundle_count': int(governance_bundles_summary.get('count') or 0),
                'governance_bundle_rollout_status_counts': governance_bundle_rollout_status_counts,
                'governance_bundle_max_exposure_ratio': round(governance_bundle_max_exposure_ratio, 4),
                'governance_portfolio_count': int(governance_portfolios_summary.get('count') or 0),
                'governance_portfolio_rollout_status_counts': governance_portfolio_rollout_status_counts,
                'governance_portfolio_calendar_due_count': governance_portfolio_calendar_due_count,
                'pending_governance_portfolio_approval_count': governance_portfolio_pending_approval_count,
                'governance_portfolio_blocked_count': governance_portfolio_blocked_count,
                'governance_portfolio_deferred_count': governance_portfolio_deferred_count,
                'governance_portfolio_attested_count': governance_portfolio_attested_count,
                'governance_portfolio_evidence_package_count': governance_portfolio_evidence_package_count,
                'governance_portfolio_notarized_evidence_count': governance_portfolio_notarized_evidence_count,
                'governance_portfolio_escrowed_evidence_count': governance_portfolio_escrowed_evidence_count,
                'governance_portfolio_crypto_signed_evidence_count': governance_portfolio_crypto_signed_evidence_count,
                'governance_portfolio_object_lock_evidence_count': governance_portfolio_object_lock_evidence_count,
                'governance_portfolio_external_signing_evidence_count': governance_portfolio_external_signing_evidence_count,
                'governance_portfolio_custody_anchor_count': governance_portfolio_custody_anchor_count,
                'governance_portfolio_custody_reconciled_count': governance_portfolio_custody_reconciled_count,
                'governance_portfolio_custody_reconciliation_conflict_count': governance_portfolio_custody_reconciliation_conflict_count,
                'governance_portfolio_custody_quorum_satisfied_count': governance_portfolio_custody_quorum_satisfied_count,
                'governance_portfolio_provider_validation_count': governance_portfolio_provider_validation_count,
                'governance_portfolio_chain_of_custody_count': governance_portfolio_chain_of_custody_count,
                'governance_portfolio_drifted_count': governance_portfolio_drifted_count,
                'governance_portfolio_blocking_drift_count': governance_portfolio_blocking_drift_count,
                'governance_portfolio_read_blocked_count': governance_portfolio_read_blocked_count,
                'governance_portfolio_policy_conformance_status_counts': governance_portfolio_policy_conformance_status_counts,
                'governance_portfolio_policy_conformance_fail_count': governance_portfolio_policy_conformance_fail_count,
                'governance_portfolio_policy_conformance_warning_count': governance_portfolio_policy_conformance_warning_count,
                'governance_portfolio_policy_baseline_drift_status_counts': governance_portfolio_policy_baseline_drift_status_counts,
                'governance_portfolio_policy_deviation_exception_count': governance_portfolio_policy_deviation_exception_count,
                'governance_portfolio_operational_tier_counts': governance_portfolio_operational_tier_counts,
                'governance_portfolio_evidence_classification_counts': governance_portfolio_evidence_classification_counts,
                'governance_current_version_id': governance_versions_summary.get('current_version_id'),
                'governance_current_version_no': governance_versions_summary.get('current_version_no'),
                'alert_delivery_job_count': int(alert_delivery_jobs_summary.get('count') or 0),
                'alert_delivery_due_count': int(alert_delivery_jobs_summary.get('due') or 0),
                'available_operations': ['cancel_run', 'retry_run', 'manual_close', 'reconcile_run', 'poll_run', 'recover_stale_runs', 'ack_alert', 'silence_alert', 'escalate_alert', 'dispatch_alert_notification', 'approve_alert_escalation', 'reject_alert_escalation', 'simulate_alert_governance', 'activate_alert_governance', 'rollback_alert_governance', 'approve_governance_promotion', 'reject_governance_promotion', 'simulate_portfolio_calendar', 'detect_portfolio_drift', 'report_portfolio_policy_conformance', 'report_portfolio_policy_baseline_drift', 'reconcile_portfolio_custody_anchors', 'validate_portfolio_providers', 'attest_portfolio_custody_anchor', 'request_portfolio_policy_deviation_exception', 'approve_portfolio_policy_deviation_exception', 'reject_portfolio_policy_deviation_exception', 'request_portfolio_approval', 'approve_portfolio_approval', 'reject_portfolio_approval', 'export_portfolio_attestation', 'export_portfolio_postmortem', 'export_portfolio_evidence_package', 'verify_portfolio_evidence_artifact', 'restore_portfolio_evidence_artifact', 'prune_portfolio_evidence_packages'],
            },
        }

    def get_runtime_board(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        limit: int = 10,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        detail = self.get_document(
            gw,
            canvas_id=canvas_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        if not detail.get('ok'):
            return detail
        scope = dict(detail.get('scope') or {})
        runtime_nodes = [
            node for node in list(detail.get('nodes') or [])
            if str(node.get('node_type') or '').strip().lower() in {'runtime', 'openclaw_runtime'}
        ]
        items = [
            self._runtime_board_entry(gw, node=node, scope=scope, limit=limit)
            for node in runtime_nodes
        ]
        async_runtime_count = 0
        stale_runtime_count = 0
        unhealthy_runtime_count = 0
        total_active_runs = 0
        total_terminal_runs = 0
        active_leases = 0
        in_progress_idempotency = 0
        saturated_runtime_count = 0
        saturated_workspace_count = 0
        runtime_locked_count = 0
        alert_count = 0
        critical_alert_count = 0
        warn_alert_count = 0
        silenced_alert_count = 0
        suppressed_alert_count = 0
        escalated_alert_count = 0
        acked_alert_count = 0
        alert_code_counts: dict[str, int] = {}
        alert_workflow_status_counts: dict[str, int] = {}
        canonical_state_counts: dict[str, int] = {}
        alert_dispatch_count = 0
        alert_dispatch_status_counts: dict[str, int] = {}
        alert_dispatch_type_counts: dict[str, int] = {}
        notification_target_count = 0
        pending_alert_approval_count = 0
        alert_delivery_job_count = 0
        alert_delivery_due_count = 0
        routing_rule_count = 0
        escalation_chain_count = 0
        quiet_hours_active_count = 0
        maintenance_active_count = 0
        storm_active_count = 0
        governance_suppressed_alert_count = 0
        governance_scheduled_alert_count = 0
        active_override_count = 0
        for item in items:
            dispatch_policy = dict((item.get('runtime_summary') or {}).get('dispatch_policy') or {})
            if str(dispatch_policy.get('dispatch_mode') or '').strip().lower() == 'async':
                async_runtime_count += 1
            health = dict(item.get('health') or {})
            if bool(health.get('stale')):
                stale_runtime_count += 1
            if str(health.get('status') or '').strip().lower() in {'degraded', 'unhealthy'}:
                unhealthy_runtime_count += 1
            summary = dict(item.get('summary') or {})
            total_active_runs += int(summary.get('active_count') or 0)
            total_terminal_runs += int(summary.get('terminal_count') or 0)
            active_leases += int(summary.get('active_leases') or 0)
            in_progress_idempotency += int(summary.get('in_progress_idempotency_count') or 0)
            if (summary.get('runtime_run_pressure_ratio') or 0) >= 1.0:
                saturated_runtime_count += 1
            if (summary.get('workspace_slot_pressure_ratio') or 0) >= 1.0 or (summary.get('workspace_run_pressure_ratio') or 0) >= 1.0:
                saturated_workspace_count += 1
            if 'scheduler:runtime_lock_active' in list(summary.get('warnings') or []):
                runtime_locked_count += 1
            alert_count += int(summary.get('alert_count') or 0)
            critical_alert_count += int(summary.get('critical_alert_count') or 0)
            warn_alert_count += int(summary.get('warn_alert_count') or 0)
            silenced_alert_count += int(summary.get('silenced_alert_count') or 0)
            suppressed_alert_count += int(summary.get('suppressed_alert_count') or 0)
            escalated_alert_count += int(summary.get('escalated_alert_count') or 0)
            acked_alert_count += int(summary.get('acked_alert_count') or 0)
            for key, value in dict(summary.get('alert_code_counts') or {}).items():
                alert_code_counts[str(key)] = alert_code_counts.get(str(key), 0) + int(value or 0)
            for key, value in dict(summary.get('alert_workflow_status_counts') or {}).items():
                alert_workflow_status_counts[str(key)] = alert_workflow_status_counts.get(str(key), 0) + int(value or 0)
            notification_target_count += int(summary.get('notification_target_count') or 0)
            pending_alert_approval_count += int(summary.get('pending_alert_approval_count') or 0)
            alert_delivery_job_count += int(summary.get('alert_delivery_job_count') or 0)
            alert_delivery_due_count += int(summary.get('alert_delivery_due_count') or 0)
            routing_rule_count += int(summary.get('routing_rule_count') or 0)
            escalation_chain_count += int(summary.get('escalation_chain_count') or 0)
            quiet_hours_active_count += 1 if bool(summary.get('quiet_hours_active')) else 0
            maintenance_active_count += 1 if bool(summary.get('maintenance_active')) else 0
            storm_active_count += 1 if bool(summary.get('storm_active')) else 0
            governance_suppressed_alert_count += int(summary.get('governance_suppressed_alert_count') or 0)
            governance_scheduled_alert_count += int(summary.get('governance_scheduled_alert_count') or 0)
            active_override_count += int(summary.get('active_override_count') or 0)
            alert_dispatch_count += int(summary.get('alert_dispatch_count') or 0)
            for key, value in dict(summary.get('alert_dispatch_status_counts') or {}).items():
                alert_dispatch_status_counts[str(key)] = alert_dispatch_status_counts.get(str(key), 0) + int(value or 0)
            for key, value in dict(summary.get('alert_dispatch_type_counts') or {}).items():
                alert_dispatch_type_counts[str(key)] = alert_dispatch_type_counts.get(str(key), 0) + int(value or 0)
            for key, value in dict(summary.get('canonical_state_counts') or {}).items():
                canonical_state_counts[str(key)] = canonical_state_counts.get(str(key), 0) + int(value or 0)
        return {
            'ok': True,
            'canvas_id': canvas_id,
            'items': items,
            'summary': {
                'runtime_count': len(items),
                'async_runtime_count': async_runtime_count,
                'stale_runtime_count': stale_runtime_count,
                'unhealthy_runtime_count': unhealthy_runtime_count,
                'total_active_runs': total_active_runs,
                'total_terminal_runs': total_terminal_runs,
                'stale_active_runs': sum(int((item.get('summary') or {}).get('stale_active_count') or 0) for item in items),
                'active_leases': active_leases,
                'in_progress_idempotency_count': in_progress_idempotency,
                'runtime_locked_count': runtime_locked_count,
                'saturated_runtime_count': saturated_runtime_count,
                'saturated_workspace_count': saturated_workspace_count,
                'alert_count': alert_count,
                'critical_alert_count': critical_alert_count,
                'warn_alert_count': warn_alert_count,
                'silenced_alert_count': silenced_alert_count,
                'suppressed_alert_count': suppressed_alert_count,
                'escalated_alert_count': escalated_alert_count,
                'acked_alert_count': acked_alert_count,
                'notification_target_count': notification_target_count,
                'routing_rule_count': routing_rule_count,
                'escalation_chain_count': escalation_chain_count,
                'quiet_hours_active_count': quiet_hours_active_count,
                'maintenance_active_count': maintenance_active_count,
                'storm_active_count': storm_active_count,
                'governance_suppressed_alert_count': governance_suppressed_alert_count,
                'governance_scheduled_alert_count': governance_scheduled_alert_count,
                'active_override_count': active_override_count,
                'alert_delivery_job_count': alert_delivery_job_count,
                'alert_delivery_due_count': alert_delivery_due_count,
                'alert_dispatch_count': alert_dispatch_count,
                'alert_dispatch_status_counts': alert_dispatch_status_counts,
                'alert_dispatch_type_counts': alert_dispatch_type_counts,
                'alert_code_counts': alert_code_counts,
                'alert_workflow_status_counts': alert_workflow_status_counts,
                'canonical_state_counts': canonical_state_counts,
            },
            'scope': scope,
        }

