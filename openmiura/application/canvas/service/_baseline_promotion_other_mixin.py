"""openmiura.application.canvas.service._baseline_promotion_other_mixin

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


class _LiveCanvasBaselinePromotionOtherMixin:
    """Mixin: baseline promotion other methods on LiveCanvasService."""

    def _baseline_promotion_simulation_custody_builtin_policy_packs(self, promotion_detail: dict[str, Any] | None) -> list[dict[str, Any]]:
        monitoring = dict(((promotion_detail or {}).get('simulation_custody_monitoring') or {}))
        policy = dict(monitoring.get('policy') or {})
        return self.openclaw_recovery_scheduler_service._baseline_promotion_simulation_custody_builtin_policy_what_if_packs(policy)

    def _baseline_promotion_simulation_custody_saved_policy_packs(self, raw_packs: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for index, item in enumerate(list(raw_packs or []), start=1):
            if not isinstance(item, dict):
                continue
            normalized.append(self.openclaw_recovery_scheduler_service._normalize_baseline_promotion_simulation_custody_policy_what_if_pack(item, actor=str(item.get('created_by') or ''), index=index, source=str(item.get('source') or 'saved')))
        return normalized

    def _baseline_promotion_simulation_custody_registry_policy_packs(self, raw_packs: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for index, item in enumerate(list(raw_packs or []), start=1):
            if not isinstance(item, dict):
                continue
            normalized.append(self.openclaw_recovery_scheduler_service._normalize_baseline_promotion_simulation_custody_policy_what_if_pack(item, actor=str(item.get('created_by') or item.get('promoted_by') or ''), index=index, source=str(item.get('source') or 'registry')))
        return normalized

    def _baseline_promotion_simulation_custody_organizational_publication_manifest(
        self,
        pack: dict[str, Any] | None,
        *,
        tenant_id: str | None,
        workspace_id: str | None,
        environment: str | None,
    ) -> dict[str, Any]:
        payload = dict(pack or {})
        service_id = str(payload.get('organizational_service_id') or self._baseline_promotion_simulation_custody_organizational_catalog_service_id(tenant_id=tenant_id))
        visibility = str(payload.get('organizational_visibility') or 'tenant').strip() or 'tenant'
        derived_scope_key = self._baseline_promotion_simulation_custody_organizational_catalog_scope_key(
            visibility,
            tenant_id=tenant_id,
            workspace_id=str(payload.get('workspace_id') or workspace_id or ''),
            environment=str(payload.get('environment') or environment or ''),
        )
        manifest = {
            'manifest_type': 'openmiura_routing_policy_pack_organizational_publication_manifest_v1',
            'catalog_entry_id': str(payload.get('catalog_entry_id') or payload.get('registry_entry_id') or ''),
            'catalog_version_key': str(payload.get('catalog_version_key') or ''),
            'catalog_version': int(payload.get('catalog_version') or 0),
            'pack_id': str(payload.get('pack_id') or ''),
            'pack_label': str(payload.get('pack_label') or ''),
            'organizational_service_id': service_id,
            'organizational_service_entry_id': str(payload.get('organizational_service_entry_id') or ''),
            'organizational_visibility': visibility,
            'organizational_service_scope_key': str(payload.get('organizational_service_scope_key') or derived_scope_key),
            'catalog_lifecycle_state': str(payload.get('catalog_lifecycle_state') or 'draft'),
            'catalog_release_state': str(payload.get('catalog_release_state') or 'draft'),
            'policy_digest': str(self.openclaw_recovery_scheduler_service._stable_digest({
                'comparison_policies': list(payload.get('comparison_policies') or []),
                'category_keys': [str(item) for item in list(payload.get('category_keys') or []) if str(item)],
                'tags': [str(item) for item in list(payload.get('tags') or []) if str(item)],
                'catalog_scope': str(payload.get('catalog_scope') or ''),
                'catalog_scope_key': str(payload.get('catalog_scope_key') or ''),
            })),
            'published_at': payload.get('organizational_published_at'),
            'published_by': str(payload.get('organizational_published_by') or ''),
        }
        manifest['manifest_digest'] = str(self.openclaw_recovery_scheduler_service._stable_digest({
            key: value for key, value in manifest.items() if key != 'manifest_digest'
        }))
        return manifest

    def _baseline_promotion_board_entry(
        self,
        gw: AdminGatewayLike,
        *,
        node: dict[str, Any],
        scope: dict[str, Any],
        limit: int = 10,
    ) -> dict[str, Any]:
        data = dict(node.get('data') or {})
        promotion_id = str(data.get('promotion_id') or node.get('label') or '').strip()
        detail = {'ok': False, 'error': 'baseline_promotion_not_found', 'promotion_id': promotion_id}
        if promotion_id:
            detail = self.openclaw_recovery_scheduler_service.get_runtime_alert_governance_baseline_promotion(
                gw,
                promotion_id=promotion_id,
                tenant_id=scope.get('tenant_id'),
                workspace_id=scope.get('workspace_id'),
                environment=scope.get('environment'),
            )
        if not detail.get('ok'):
            return {
                'node_id': node.get('node_id'),
                'node_label': node.get('label'),
                'promotion_id': promotion_id,
                'status': 'unknown',
                'error': detail.get('error') or 'baseline_promotion_not_found',
                'summary': {'wave_count': 0, 'completed_wave_count': 0, 'due_advance_job_count': 0, 'rollback_attestation_count': 0},
            }
        release = dict(detail.get('release') or {})
        promotion = dict(detail.get('baseline_promotion') or {})
        analytics = dict(detail.get('analytics') or {})
        advance_jobs = dict(detail.get('advance_jobs') or {})
        rollback_attestations = dict(detail.get('rollback_attestations') or {})
        custody_alerts_summary = dict((((detail.get('simulation_custody_monitoring') or {}).get('alerts')) or {}).get('summary') or {})
        return {
            'node_id': node.get('node_id'),
            'node_label': node.get('label'),
            'promotion_id': promotion_id,
            'status': str(release.get('status') or ''),
            'catalog_id': str(promotion.get('catalog_id') or ''),
            'catalog_name': str(promotion.get('catalog_name') or ''),
            'candidate_catalog_version': str(promotion.get('candidate_catalog_version') or release.get('version') or ''),
            'previous_catalog_version': str(promotion.get('previous_catalog_version') or ''),
            'summary': {
                'wave_count': int(analytics.get('wave_count') or 0),
                'completed_wave_count': int(analytics.get('completed_wave_count') or 0),
                'pending_portfolio_count': int(analytics.get('pending_portfolio_count') or 0),
                'due_advance_job_count': int((advance_jobs.get('summary') or {}).get('due') or 0),
                'scheduled_advance_job_count': int((advance_jobs.get('summary') or {}).get('count') or 0),
                'rollback_attestation_count': int((rollback_attestations.get('summary') or {}).get('count') or 0),
                'gate_failed': bool(analytics.get('gate_failed')),
                'paused': bool((promotion.get('pause_state') or {}).get('paused')),
                'custody_guard_blocked': bool((((detail.get('simulation_custody_monitoring') or {}).get('guard')) or {}).get('blocked')),
                'custody_drifted_count': int(((((detail.get('simulation_evidence_reconciliation') or {}).get('current') or {}).get('summary')) or {}).get('drifted_count') or 0),
                'custody_active_alert_count': int(custody_alerts_summary.get('active_count') or 0),
                'custody_acknowledged_alert_count': int(custody_alerts_summary.get('acknowledged_count') or 0),
                'custody_muted_alert_count': int(custody_alerts_summary.get('muted_count') or 0),
                'custody_escalated_alert_count': int(custody_alerts_summary.get('active_escalated_count') or custody_alerts_summary.get('escalated_count') or 0),
                'custody_suppressed_alert_count': int(custody_alerts_summary.get('active_suppressed_count') or custody_alerts_summary.get('suppressed_count') or 0),
                'custody_owned_alert_count': int(custody_alerts_summary.get('active_owned_count') or custody_alerts_summary.get('owned_count') or 0),
                'custody_claimed_alert_count': int(custody_alerts_summary.get('active_claimed_count') or custody_alerts_summary.get('claimed_count') or 0),
                'custody_unowned_alert_count': int(custody_alerts_summary.get('active_unowned_count') or custody_alerts_summary.get('unassigned_count') or 0),
                'custody_routed_alert_count': int(custody_alerts_summary.get('routed_count') or 0),
                'custody_handoff_pending_alert_count': int(custody_alerts_summary.get('active_handoff_pending_count') or custody_alerts_summary.get('pending_handoff_count') or 0),
                'custody_sla_breached_alert_count': int(custody_alerts_summary.get('active_sla_breached_count') or custody_alerts_summary.get('sla_breached_count') or 0),
                'custody_sla_rerouted_alert_count': int(custody_alerts_summary.get('active_sla_rerouted_count') or custody_alerts_summary.get('sla_rerouted_count') or 0),
                'custody_team_queue_alert_count': int(custody_alerts_summary.get('active_team_queue_alert_count') or custody_alerts_summary.get('team_queue_alert_count') or 0),
                'custody_queue_at_capacity_alert_count': int(custody_alerts_summary.get('active_queue_at_capacity_count') or custody_alerts_summary.get('queue_at_capacity_count') or 0),
                'custody_load_aware_routed_alert_count': int(custody_alerts_summary.get('active_load_aware_routed_count') or custody_alerts_summary.get('load_aware_routed_count') or 0),
                'custody_reservation_protected_alert_count': int(custody_alerts_summary.get('active_reservation_protected_alert_count') or custody_alerts_summary.get('reservation_protected_alert_count') or 0),
                'custody_lease_protected_alert_count': int(custody_alerts_summary.get('active_lease_protected_alert_count') or custody_alerts_summary.get('lease_protected_alert_count') or 0),
                'custody_temporary_hold_protected_alert_count': int(custody_alerts_summary.get('active_temporary_hold_protected_alert_count') or custody_alerts_summary.get('temporary_hold_protected_alert_count') or 0),
                'custody_anti_thrashing_kept_alert_count': int(custody_alerts_summary.get('active_anti_thrashing_kept_alert_count') or custody_alerts_summary.get('anti_thrashing_kept_alert_count') or 0),
                'custody_queue_family_alert_count': int(custody_alerts_summary.get('active_queue_family_alert_count') or custody_alerts_summary.get('queue_family_alert_count') or 0),
                'custody_family_hysteresis_kept_alert_count': int(custody_alerts_summary.get('active_family_hysteresis_kept_alert_count') or custody_alerts_summary.get('family_hysteresis_kept_alert_count') or 0),
                'custody_aging_alert_count': int(custody_alerts_summary.get('active_aging_alert_count') or custody_alerts_summary.get('aging_alert_count') or 0),
                'custody_starving_alert_count': int(custody_alerts_summary.get('active_starving_alert_count') or custody_alerts_summary.get('starving_alert_count') or 0),
                'custody_starvation_prevented_alert_count': int(custody_alerts_summary.get('active_starvation_prevented_alert_count') or custody_alerts_summary.get('starvation_prevented_alert_count') or 0),
                'custody_alerts_at_risk_count': int(custody_alerts_summary.get('active_alerts_at_risk_count') or custody_alerts_summary.get('alerts_at_risk_count') or 0),
                'custody_predicted_sla_breach_count': int(custody_alerts_summary.get('active_predicted_sla_breach_count') or custody_alerts_summary.get('predicted_sla_breach_count') or 0),
                'custody_expedite_routed_alert_count': int(custody_alerts_summary.get('active_expedite_routed_alert_count') or custody_alerts_summary.get('expedite_routed_alert_count') or 0),
                'custody_proactive_routed_alert_count': int(custody_alerts_summary.get('active_proactive_routed_alert_count') or custody_alerts_summary.get('proactive_routed_alert_count') or 0),
                'custody_forecasted_surge_alert_count': int(custody_alerts_summary.get('active_forecasted_surge_alert_count') or custody_alerts_summary.get('forecasted_surge_alert_count') or 0),
                'custody_overload_governed_alert_count': int(custody_alerts_summary.get('active_overload_governed_alert_count') or custody_alerts_summary.get('overload_governed_alert_count') or 0),
                'custody_overload_blocked_alert_count': int(custody_alerts_summary.get('active_overload_blocked_alert_count') or custody_alerts_summary.get('overload_blocked_alert_count') or 0),
                'custody_admission_deferred_alert_count': int(custody_alerts_summary.get('active_admission_deferred_alert_count') or custody_alerts_summary.get('admission_deferred_alert_count') or 0),
                'custody_manual_gate_alert_count': int(custody_alerts_summary.get('active_manual_gate_alert_count') or custody_alerts_summary.get('manual_gate_alert_count') or 0),
            },
            'latest_health': analytics.get('latest_health'),
            'rollback_attestations': rollback_attestations,
            'advance_jobs': advance_jobs,
            'baseline_promotion': detail,
        }

    def get_baseline_promotion_board(
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
        promotion_nodes = [
            node for node in list(detail.get('nodes') or [])
            if str(node.get('node_type') or '').strip().lower() in {'baseline_promotion', 'policy_baseline_promotion'}
        ]
        items = [
            self._baseline_promotion_board_entry(gw, node=node, scope=scope, limit=limit)
            for node in promotion_nodes
        ]
        status_counts: dict[str, int] = {}
        due_advance_job_count = 0
        rollback_attestation_count = 0
        paused_count = 0
        gate_failed_count = 0
        awaiting_advance_count = 0
        custody_guard_blocked_count = 0
        custody_active_alert_count = 0
        custody_acknowledged_alert_count = 0
        custody_muted_alert_count = 0
        custody_escalated_alert_count = 0
        custody_suppressed_alert_count = 0
        custody_owned_alert_count = 0
        custody_claimed_alert_count = 0
        custody_unowned_alert_count = 0
        custody_routed_alert_count = 0
        custody_handoff_pending_alert_count = 0
        custody_sla_breached_alert_count = 0
        custody_sla_rerouted_alert_count = 0
        custody_team_queue_alert_count = 0
        custody_queue_at_capacity_alert_count = 0
        custody_load_aware_routed_alert_count = 0
        custody_reservation_protected_alert_count = 0
        custody_lease_protected_alert_count = 0
        custody_temporary_hold_protected_alert_count = 0
        custody_anti_thrashing_kept_alert_count = 0
        custody_queue_family_alert_count = 0
        custody_family_hysteresis_kept_alert_count = 0
        custody_aging_alert_count = 0
        custody_starving_alert_count = 0
        custody_starvation_prevented_alert_count = 0
        custody_alerts_at_risk_count = 0
        custody_predicted_sla_breach_count = 0
        custody_expedite_routed_alert_count = 0
        custody_proactive_routed_alert_count = 0
        custody_forecasted_surge_alert_count = 0
        custody_overload_governed_alert_count = 0
        custody_overload_blocked_alert_count = 0
        custody_admission_deferred_alert_count = 0
        custody_manual_gate_alert_count = 0
        for item in items:
            status = str(item.get('status') or 'unknown')
            status_counts[status] = status_counts.get(status, 0) + 1
            summary = dict(item.get('summary') or {})
            due_advance_job_count += int(summary.get('due_advance_job_count') or 0)
            rollback_attestation_count += int(summary.get('rollback_attestation_count') or 0)
            paused_count += 1 if bool(summary.get('paused')) else 0
            gate_failed_count += 1 if bool(summary.get('gate_failed')) else 0
            awaiting_advance_count += 1 if status in {'awaiting_advance', 'awaiting_advance_window', 'awaiting_dependencies'} else 0
            custody_guard_blocked_count += 1 if bool(summary.get('custody_guard_blocked')) else 0
            custody_active_alert_count += int(summary.get('custody_active_alert_count') or 0)
            custody_acknowledged_alert_count += int(summary.get('custody_acknowledged_alert_count') or 0)
            custody_muted_alert_count += int(summary.get('custody_muted_alert_count') or 0)
            custody_escalated_alert_count += int(summary.get('custody_escalated_alert_count') or 0)
            custody_suppressed_alert_count += int(summary.get('custody_suppressed_alert_count') or 0)
            custody_owned_alert_count += int(summary.get('custody_owned_alert_count') or 0)
            custody_claimed_alert_count += int(summary.get('custody_claimed_alert_count') or 0)
            custody_unowned_alert_count += int(summary.get('custody_unowned_alert_count') or 0)
            custody_routed_alert_count += int(summary.get('custody_routed_alert_count') or 0)
            custody_handoff_pending_alert_count += int(summary.get('custody_handoff_pending_alert_count') or 0)
            custody_sla_breached_alert_count += int(summary.get('custody_sla_breached_alert_count') or 0)
            custody_sla_rerouted_alert_count += int(summary.get('custody_sla_rerouted_alert_count') or 0)
            custody_team_queue_alert_count += int(summary.get('custody_team_queue_alert_count') or 0)
            custody_queue_at_capacity_alert_count += int(summary.get('custody_queue_at_capacity_alert_count') or 0)
            custody_load_aware_routed_alert_count += int(summary.get('custody_load_aware_routed_alert_count') or 0)
            custody_reservation_protected_alert_count += int(summary.get('custody_reservation_protected_alert_count') or 0)
            custody_lease_protected_alert_count += int(summary.get('custody_lease_protected_alert_count') or 0)
            custody_temporary_hold_protected_alert_count += int(summary.get('custody_temporary_hold_protected_alert_count') or 0)
            custody_anti_thrashing_kept_alert_count += int(summary.get('custody_anti_thrashing_kept_alert_count') or 0)
            custody_queue_family_alert_count += int(summary.get('custody_queue_family_alert_count') or 0)
            custody_family_hysteresis_kept_alert_count += int(summary.get('custody_family_hysteresis_kept_alert_count') or 0)
            custody_aging_alert_count += int(summary.get('custody_aging_alert_count') or 0)
            custody_starving_alert_count += int(summary.get('custody_starving_alert_count') or 0)
            custody_starvation_prevented_alert_count += int(summary.get('custody_starvation_prevented_alert_count') or 0)
            custody_alerts_at_risk_count += int(summary.get('custody_alerts_at_risk_count') or 0)
            custody_predicted_sla_breach_count += int(summary.get('custody_predicted_sla_breach_count') or 0)
            custody_expedite_routed_alert_count += int(summary.get('custody_expedite_routed_alert_count') or 0)
            custody_proactive_routed_alert_count += int(summary.get('custody_proactive_routed_alert_count') or 0)
            custody_forecasted_surge_alert_count += int(summary.get('custody_forecasted_surge_alert_count') or 0)
            custody_overload_governed_alert_count += int(summary.get('custody_overload_governed_alert_count') or 0)
            custody_overload_blocked_alert_count += int(summary.get('custody_overload_blocked_alert_count') or 0)
            custody_admission_deferred_alert_count += int(summary.get('custody_admission_deferred_alert_count') or 0)
            custody_manual_gate_alert_count += int(summary.get('custody_manual_gate_alert_count') or 0)
        return {
            'ok': True,
            'canvas_id': canvas_id,
            'items': items,
            'summary': {
                'promotion_count': len(items),
                'status_counts': status_counts,
                'due_advance_job_count': due_advance_job_count,
                'rollback_attestation_count': rollback_attestation_count,
                'paused_count': paused_count,
                'gate_failed_count': gate_failed_count,
                'awaiting_advance_count': awaiting_advance_count,
                'custody_guard_blocked_count': custody_guard_blocked_count,
                'custody_active_alert_count': custody_active_alert_count,
                'custody_acknowledged_alert_count': custody_acknowledged_alert_count,
                'custody_muted_alert_count': custody_muted_alert_count,
                'custody_escalated_alert_count': custody_escalated_alert_count,
                'custody_suppressed_alert_count': custody_suppressed_alert_count,
                'custody_owned_alert_count': custody_owned_alert_count,
                'custody_claimed_alert_count': custody_claimed_alert_count,
                'custody_unowned_alert_count': custody_unowned_alert_count,
                'custody_routed_alert_count': custody_routed_alert_count,
                'custody_handoff_pending_alert_count': custody_handoff_pending_alert_count,
                'custody_sla_breached_alert_count': custody_sla_breached_alert_count,
                'custody_sla_rerouted_alert_count': custody_sla_rerouted_alert_count,
                'custody_team_queue_alert_count': custody_team_queue_alert_count,
                'custody_queue_at_capacity_alert_count': custody_queue_at_capacity_alert_count,
                'custody_load_aware_routed_alert_count': custody_load_aware_routed_alert_count,
                'custody_reservation_protected_alert_count': custody_reservation_protected_alert_count,
                'custody_lease_protected_alert_count': custody_lease_protected_alert_count,
                'custody_temporary_hold_protected_alert_count': custody_temporary_hold_protected_alert_count,
                'custody_anti_thrashing_kept_alert_count': custody_anti_thrashing_kept_alert_count,
                'custody_queue_family_alert_count': custody_queue_family_alert_count,
                'custody_family_hysteresis_kept_alert_count': custody_family_hysteresis_kept_alert_count,
                'custody_aging_alert_count': custody_aging_alert_count,
                'custody_starving_alert_count': custody_starving_alert_count,
                'custody_starvation_prevented_alert_count': custody_starvation_prevented_alert_count,
                'custody_alerts_at_risk_count': custody_alerts_at_risk_count,
                'custody_predicted_sla_breach_count': custody_predicted_sla_breach_count,
                'custody_expedite_routed_alert_count': custody_expedite_routed_alert_count,
                'custody_proactive_routed_alert_count': custody_proactive_routed_alert_count,
                'custody_forecasted_surge_alert_count': custody_forecasted_surge_alert_count,
                'custody_overload_governed_alert_count': custody_overload_governed_alert_count,
                'custody_overload_blocked_alert_count': custody_overload_blocked_alert_count,
                'custody_admission_deferred_alert_count': custody_admission_deferred_alert_count,
                'custody_manual_gate_alert_count': custody_manual_gate_alert_count,
            },
            'scope': scope,
        }

