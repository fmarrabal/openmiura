"""openmiura.application.canvas.service._baseline_promotion_compactors_mixin

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


LiveCanvasService: type | None = None  # late-bound by service/__init__.py

class _LiveCanvasBaselinePromotionCompactorsMixin:
    """Mixin: baseline promotion compactors methods on LiveCanvasService."""

    @staticmethod
    def _compact_baseline_promotion_simulation_export_report(report: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(report or {})
        if not payload:
            return {}
        integrity = dict(payload.get('integrity') or {})
        return {
            'report_id': str(payload.get('report_id') or payload.get('package_id') or ''),
            'package_id': str(payload.get('package_id') or ''),
            'report_type': str(payload.get('report_type') or ''),
            'generated_at': payload.get('generated_at'),
            'generated_by': str(payload.get('generated_by') or ''),
            'integrity': {
                'signed': bool(integrity.get('signed', False)),
                'payload_hash': str(integrity.get('payload_hash') or ''),
            },
            'registry_entry': {
                'entry_id': str((payload.get('registry_entry') or {}).get('entry_id') or ''),
                'sequence': int((payload.get('registry_entry') or {}).get('sequence') or 0),
                'immutable': bool((payload.get('registry_entry') or {}).get('immutable', False)),
            },
            'artifact': {
                'artifact_type': str((payload.get('artifact') or {}).get('artifact_type') or ''),
                'sha256': str((payload.get('artifact') or {}).get('sha256') or ''),
                'size_bytes': int((payload.get('artifact') or {}).get('size_bytes') or 0),
                'filename': str((payload.get('artifact') or {}).get('filename') or ''),
            },
            'escrow': {
                'receipt_id': str((payload.get('escrow') or {}).get('receipt_id') or ''),
                'provider': str((payload.get('escrow') or {}).get('provider') or ''),
                'archived': bool((payload.get('escrow') or {}).get('archived', False)),
                'archived_at': (payload.get('escrow') or {}).get('archived_at'),
                'immutable_until': (payload.get('escrow') or {}).get('immutable_until'),
                'lock_path': str((payload.get('escrow') or {}).get('lock_path') or ''),
                'object_lock_enabled': bool((payload.get('escrow') or {}).get('object_lock_enabled', False)),
            },
        }

    @staticmethod
    def _compact_baseline_promotion_simulation_registry_summary(summary: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(summary or {})
        if not payload:
            return {}
        return {
            'count': int(payload.get('count') or 0),
            'package_count': int(payload.get('package_count') or 0),
            'chain_ok': bool(payload.get('chain_ok', False)),
            'broken_sequence_count': int(payload.get('broken_sequence_count') or 0),
            'immutable_count': int(payload.get('immutable_count') or 0),
            'escrowed_count': int(payload.get('escrowed_count') or 0),
            'immutable_archive_count': int(payload.get('immutable_archive_count') or 0),
            'latest_entry_id': str(payload.get('latest_entry_id') or ''),
            'latest_package_id': str(payload.get('latest_package_id') or ''),
            'latest_entry_hash': str(payload.get('latest_entry_hash') or ''),
            'latest_archive_path': str(payload.get('latest_archive_path') or ''),
            'latest_receipt_id': str(payload.get('latest_receipt_id') or ''),
        }

    @staticmethod
    def _compact_baseline_promotion_simulation_catalog_binding(binding: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(binding or {})
        if not payload:
            return {}
        return {
            'binding_id': str(payload.get('binding_id') or ''),
            'binding_scope': str(payload.get('binding_scope') or ''),
            'binding_scope_key': str(payload.get('binding_scope_key') or ''),
            'catalog_entry_id': str(payload.get('catalog_entry_id') or ''),
            'catalog_version_key': str(payload.get('catalog_version_key') or ''),
            'catalog_version': int(payload.get('catalog_version') or 0),
            'catalog_pack_id': str(payload.get('catalog_pack_id') or payload.get('pack_id') or ''),
            'catalog_pack_label': str(payload.get('catalog_pack_label') or payload.get('pack_label') or ''),
            'promotion_id': str(payload.get('promotion_id') or ''),
            'workspace_id': str(payload.get('workspace_id') or ''),
            'environment': str(payload.get('environment') or ''),
            'portfolio_family_id': str(payload.get('portfolio_family_id') or ''),
            'runtime_family_id': str(payload.get('runtime_family_id') or ''),
            'bound_at': payload.get('bound_at'),
            'bound_by': str(payload.get('bound_by') or ''),
            'state': str(payload.get('state') or 'active'),
            'note': str(payload.get('note') or '')[:160],
            'catalog_owner_canvas_id': str(payload.get('catalog_owner_canvas_id') or ''),
            'catalog_owner_node_id': str(payload.get('catalog_owner_node_id') or ''),
            'rebound_at': payload.get('rebound_at'),
            'rebound_by': str(payload.get('rebound_by') or ''),
            'rebound_reason': str(payload.get('rebound_reason') or ''),
            'binding_ready': bool(payload.get('binding_ready', False)),
            'binding_ready_reason': str(payload.get('binding_ready_reason') or ''),
        }

    @staticmethod
    def _compact_baseline_promotion_simulation_catalog_binding_event(event: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(event or {})
        if not payload:
            return {}
        return {
            'event_id': str(payload.get('event_id') or ''),
            'event_type': str(payload.get('event_type') or ''),
            'binding_id': str(payload.get('binding_id') or ''),
            'binding_scope': str(payload.get('binding_scope') or ''),
            'binding_scope_key': str(payload.get('binding_scope_key') or ''),
            'catalog_entry_id': str(payload.get('catalog_entry_id') or ''),
            'catalog_version_key': str(payload.get('catalog_version_key') or ''),
            'catalog_version': int(payload.get('catalog_version') or 0),
            'rebound_to_catalog_entry_id': str(payload.get('rebound_to_catalog_entry_id') or ''),
            'rebound_to_catalog_version': int(payload.get('rebound_to_catalog_version') or 0),
            'at': payload.get('at'),
            'by': str(payload.get('by') or ''),
            'note': str(payload.get('note') or '')[:160],
        }

    @staticmethod
    @staticmethod
    def _compact_baseline_promotion_simulation_request(request: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(request or {})
        candidate_baselines = dict(payload.get('candidate_baselines') or {})
        rollout_policy = dict(payload.get('rollout_policy') or {})
        gate_policy = dict(payload.get('gate_policy') or {})
        rollback_policy = dict(payload.get('rollback_policy') or {})
        return {
            'promotion_id': str(payload.get('promotion_id') or ''),
            'catalog_id': str(payload.get('catalog_id') or ''),
            'candidate_catalog_version': str(payload.get('candidate_catalog_version') or ''),
            'version': payload.get('version'),
            'candidate_environment_count': len(candidate_baselines),
            'candidate_environments': [str(key) for key in sorted(candidate_baselines.keys()) if str(key)],
            'rollout_policy': {
                'enabled': bool(rollout_policy.get('enabled', False)),
                'wave_size': int(rollout_policy.get('wave_size') or 0),
                'auto_apply_first_wave': bool(rollout_policy.get('auto_apply_first_wave', False)),
                'require_manual_advance': bool(rollout_policy.get('require_manual_advance', False)),
                'max_concurrent_waves': int(rollout_policy.get('max_concurrent_waves') or 0),
            },
            'gate_policy': {
                'enabled': bool(gate_policy.get('enabled', False)),
                'mode': str(gate_policy.get('mode') or ''),
                'require_all': bool(gate_policy.get('require_all', False)),
                'min_bake_time_s': int(gate_policy.get('min_bake_time_s') or 0),
            },
            'rollback_policy': {
                'enabled': bool(rollback_policy.get('enabled', False)),
                'auto_rollback_on_failure': bool(rollback_policy.get('auto_rollback_on_failure', False)),
                'attestation_required': bool(rollback_policy.get('attestation_required', False)),
            },
            'reason': str(payload.get('reason') or ''),
            'auto_approve': bool(payload.get('auto_approve', False)),
        }

    def _compact_baseline_promotion_simulation_policy(policy: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(policy or {})
        approval_policy = dict(payload.get('approval_policy') or {})
        custody_policy = dict(payload.get('custody_monitoring_policy') or {})
        return {
            'ttl_s': int(payload.get('ttl_s') or 0),
            'allow_self_review': bool(payload.get('allow_self_review', True)),
            'require_reason': bool(payload.get('require_reason', False)),
            'block_on_rejection': bool(payload.get('block_on_rejection', True)),
            'approval_policy': {
                'enabled': bool(approval_policy.get('enabled', False)),
                'mode': str(approval_policy.get('mode') or ''),
                'layers': [
                    {
                        'layer_id': str(layer.get('layer_id') or ''),
                        'label': str(layer.get('label') or ''),
                        'requested_role': str(layer.get('requested_role') or ''),
                        'required': bool(layer.get('required', True)),
                    }
                    for layer in list(approval_policy.get('layers') or [])
                ],
            },
            'custody_monitoring_policy': {
                'enabled': bool(custody_policy.get('enabled', False)),
                'auto_schedule': bool(custody_policy.get('auto_schedule', False)),
                'interval_s': int(custody_policy.get('interval_s') or 0),
                'notify_on_drift': bool(custody_policy.get('notify_on_drift', False)),
                'notify_on_recovery': bool(custody_policy.get('notify_on_recovery', False)),
                'block_on_drift': bool(custody_policy.get('block_on_drift', False)),
                'severity': str(custody_policy.get('severity') or ''),
                'load_aware_routing_enabled': bool(custody_policy.get('load_aware_routing_enabled', False)),
                'routing_enabled': bool(custody_policy.get('routing_enabled', False)),
                'ownership_enabled': bool(custody_policy.get('ownership_enabled', False)),
                'handoff_enabled': bool(custody_policy.get('handoff_enabled', False)),
                'default_route': {
                    'route_id': str((custody_policy.get('default_route') or {}).get('route_id') or ''),
                    'queue_id': str((custody_policy.get('default_route') or {}).get('queue_id') or ''),
                    'owner_role': str((custody_policy.get('default_route') or {}).get('owner_role') or ''),
                },
                'routing_routes': [
                    {
                        'route_id': str(route.get('route_id') or ''),
                        'queue_id': str(route.get('queue_id') or ''),
                        'owner_role': str(route.get('owner_role') or ''),
                        'min_escalation_level': int(route.get('min_escalation_level') or 0),
                        'queue_capacity': int(route.get('queue_capacity') or 0),
                    }
                    for route in list(custody_policy.get('routing_routes') or [])[:6]
                ],
            },
        }

    @staticmethod
    def _compact_baseline_promotion_simulation_custody_guard(guard: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(guard or {})
        return {
            'status': str(payload.get('status') or ''),
            'blocked': bool(payload.get('blocked', False)),
            'block_reason': str(payload.get('block_reason') or payload.get('reason') or ''),
            'drifted': bool(payload.get('drifted', False)),
            'alert_status': str(payload.get('alert_status') or ''),
            'escalated': bool(payload.get('escalated', False)),
            'escalation_level': int(payload.get('escalation_level') or 0),
            'severity': str(payload.get('severity') or ''),
            'suppressed': bool(payload.get('suppressed', False)),
            'suppression_reasons': [str(item) for item in list(payload.get('suppression_reasons') or []) if str(item)],
            'pending_escalation_level': int(payload.get('pending_escalation_level') or 0),
            'owner_id': str(payload.get('owner_id') or ''),
            'owner_role': str(payload.get('owner_role') or ''),
            'ownership_status': str(payload.get('ownership_status') or ''),
            'queue_id': str(payload.get('queue_id') or ''),
            'queue_label': str(payload.get('queue_label') or ''),
            'route_id': str(payload.get('route_id') or ''),
            'route_label': str(payload.get('route_label') or ''),
            'queue_active_count': int(payload.get('queue_active_count') or 0),
            'queue_capacity': int(payload.get('queue_capacity') or 0),
            'queue_available': payload.get('queue_available'),
            'queue_load_ratio': float(payload.get('queue_load_ratio') or 0.0),
            'queue_at_capacity': bool(payload.get('queue_at_capacity', False)),
            'queue_over_capacity': bool(payload.get('queue_over_capacity', False)),
            'reservation_enabled': bool(payload.get('reservation_enabled', False)),
            'reserved_capacity': int(payload.get('reserved_capacity') or 0),
            'general_capacity': int(payload.get('general_capacity') or 0),
            'general_available': payload.get('general_available'),
            'reserved_available': payload.get('reserved_available'),
            'reservation_eligible': bool(payload.get('reservation_eligible', False)),
            'reservation_applied': bool(payload.get('reservation_applied', False)),
            'lease_active': bool(payload.get('lease_active', False)),
            'lease_expired': bool(payload.get('lease_expired', False)),
            'leased_capacity': int(payload.get('leased_capacity') or 0),
            'lease_available': payload.get('lease_available'),
            'lease_expires_at': payload.get('lease_expires_at'),
            'lease_reason': str(payload.get('lease_reason') or ''),
            'lease_holder': str(payload.get('lease_holder') or ''),
            'lease_eligible': bool(payload.get('lease_eligible', False)),
            'lease_applied': bool(payload.get('lease_applied', False)),
            'starvation_lease_capacity_borrowed': bool(payload.get('starvation_lease_capacity_borrowed', False)),
            'expedite_lease_capacity_borrowed': bool(payload.get('expedite_lease_capacity_borrowed', False)),
            'temporary_hold_count': int(payload.get('temporary_hold_count') or 0),
            'temporary_hold_capacity': int(payload.get('temporary_hold_capacity') or 0),
            'temporary_hold_available': payload.get('temporary_hold_available'),
            'temporary_hold_reason': str((list(payload.get('temporary_hold_reasons') or ['']) or [''])[0] or ''),
            'temporary_hold_eligible': bool(payload.get('temporary_hold_eligible', False)),
            'temporary_hold_applied': bool(payload.get('temporary_hold_applied', False)),
            'starvation_temporary_hold_borrowed': bool(payload.get('starvation_temporary_hold_borrowed', False)),
            'expedite_temporary_hold_borrowed': bool(payload.get('expedite_temporary_hold_borrowed', False)),
            'expired_temporary_hold_count': int(payload.get('expired_temporary_hold_count') or 0),
            'effective_capacity': int(payload.get('effective_capacity') or 0),
            'alert_wait_age_s': int(payload.get('alert_wait_age_s') or 0),
            'aging_applied': bool(payload.get('aging_applied', False)),
            'starving': bool(payload.get('starving', False)),
            'queue_oldest_alert_age_s': int(payload.get('queue_oldest_alert_age_s') or 0),
            'queue_aged_alert_count': int(payload.get('queue_aged_alert_count') or 0),
            'queue_starving_alert_count': int(payload.get('queue_starving_alert_count') or 0),
            'starvation_reserved_capacity_borrowed': bool(payload.get('starvation_reserved_capacity_borrowed', False)),
            'starvation_prevention_applied': bool(payload.get('starvation_prevention_applied', False)),
            'starvation_prevention_reason': str(payload.get('starvation_prevention_reason') or ''),
            'load_aware_routing': bool(payload.get('load_aware_routing', False)),
            'selection_reason': str(payload.get('selection_reason') or ''),
            'anti_thrashing_applied': bool(payload.get('anti_thrashing_applied', False)),
            'anti_thrashing_reason': str(payload.get('anti_thrashing_reason') or ''),
            'queue_family_id': str(payload.get('queue_family_id') or ''),
            'queue_family_label': str(payload.get('queue_family_label') or ''),
            'queue_family_enabled': bool(payload.get('queue_family_enabled', False)),
            'queue_family_member_count': int(payload.get('queue_family_member_count') or 0),
            'recent_queue_hop_count': int(payload.get('recent_queue_hop_count') or 0),
            'recent_family_hop_count': int(payload.get('recent_family_hop_count') or 0),
            'family_hysteresis_applied': bool(payload.get('family_hysteresis_applied', False)),
            'family_hysteresis_reason': str(payload.get('family_hysteresis_reason') or ''),
            'route_history_queue_ids': [str(item) for item in list(payload.get('route_history_queue_ids') or []) if str(item)],
            'route_history_family_ids': [str(item) for item in list(payload.get('route_history_family_ids') or []) if str(item)],
            'sla_deadline_target': str(payload.get('sla_deadline_target') or ''),
            'time_to_breach_s': payload.get('time_to_breach_s'),
            'predicted_wait_time_s': payload.get('predicted_wait_time_s'),
            'predicted_sla_margin_s': payload.get('predicted_sla_margin_s'),
            'predicted_sla_breach': bool(payload.get('predicted_sla_breach', False)),
            'breach_risk_score': float(payload.get('breach_risk_score') or 0.0),
            'breach_risk_level': str(payload.get('breach_risk_level') or ''),
            'expected_service_time_s': int(payload.get('expected_service_time_s') or 0),
            'forecast_window_s': int(payload.get('forecast_window_s') or 0),
            'forecast_arrivals_count': int(payload.get('forecast_arrivals_count') or 0),
            'forecast_departures_count': int(payload.get('forecast_departures_count') or 0),
            'projected_active_count': int(payload.get('projected_active_count') or 0),
            'projected_load_ratio': float(payload.get('projected_load_ratio') or 0.0),
            'projected_wait_time_s': int(payload.get('projected_wait_time_s') or 0),
            'forecasted_over_capacity': bool(payload.get('forecasted_over_capacity', False)),
            'surge_predicted': bool(payload.get('surge_predicted', False)),
            'proactive_routing_eligible': bool(payload.get('proactive_routing_eligible', False)),
            'proactive_routing_applied': bool(payload.get('proactive_routing_applied', False)),
            'proactive_reason': str(payload.get('proactive_reason') or ''),
            'admission_control_enabled': bool(payload.get('admission_control_enabled', False)),
            'admission_action': str(payload.get('admission_action') or ''),
            'admission_exempt': bool(payload.get('admission_exempt', False)),
            'admission_exempt_reason': str(payload.get('admission_exempt_reason') or ''),
            'admission_decision': str(payload.get('admission_decision') or ''),
            'admission_blocked': bool(payload.get('admission_blocked', False)),
            'admission_reason': str(payload.get('admission_reason') or ''),
            'admission_review_required': bool(payload.get('admission_review_required', False)),
            'overload_governance_enabled': bool(payload.get('overload_governance_enabled', False)),
            'overload_governance_applied': bool(payload.get('overload_governance_applied', False)),
            'overload_action': str(payload.get('overload_action') or ''),
            'overload_projected_load_ratio_threshold': float(payload.get('overload_projected_load_ratio_threshold') or 0.0),
            'overload_projected_wait_time_threshold_s': int(payload.get('overload_projected_wait_time_threshold_s') or 0),
            'overload_predicted': bool(payload.get('overload_predicted', False)),
            'overload_reason': str(payload.get('overload_reason') or ''),
            'expedite_eligible': bool(payload.get('expedite_eligible', False)),
            'expedite_reserved_capacity_borrowed': bool(payload.get('expedite_reserved_capacity_borrowed', False)),
            'expedite_applied': bool(payload.get('expedite_applied', False)),
            'expedite_reason': str(payload.get('expedite_reason') or ''),
            'handoff_pending': bool(payload.get('handoff_pending', False)),
            'handoff_count': int(payload.get('handoff_count') or 0),
            'sla_status': str(payload.get('sla_status') or ''),
            'sla_breached': bool(payload.get('sla_breached', False)),
            'sla_breached_targets': [str(item) for item in list(payload.get('sla_breached_targets') or []) if str(item)],
            'sla_warning_targets': [str(item) for item in list(payload.get('sla_warning_targets') or []) if str(item)],
            'sla_rerouted': bool(payload.get('sla_rerouted', False)),
            'sla_reroute_status': str(payload.get('sla_reroute_status') or ''),
            'sla_reroute_count': int(payload.get('sla_reroute_count') or 0),
            'team_queue_id': str(payload.get('team_queue_id') or ''),
            'updated_at': payload.get('updated_at'),
        }

    @staticmethod
    def _compact_baseline_promotion_simulation_custody_alerts_summary(summary: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(summary or {})
        return {
            'count': int(payload.get('count') or 0),
            'active_count': int(payload.get('active_count') or 0),
            'acknowledged_count': int(payload.get('acknowledged_count') or 0),
            'muted_count': int(payload.get('muted_count') or 0),
            'escalated_count': int(payload.get('active_escalated_count') or payload.get('escalated_count') or 0),
            'suppressed_count': int(payload.get('active_suppressed_count') or payload.get('suppressed_count') or 0),
            'owned_count': int(payload.get('active_owned_count') or payload.get('owned_count') or 0),
            'claimed_count': int(payload.get('active_claimed_count') or payload.get('claimed_count') or 0),
            'unowned_count': int(payload.get('active_unowned_count') or payload.get('unassigned_count') or 0),
            'routed_count': int(payload.get('routed_count') or 0),
            'handoff_pending_count': int(payload.get('active_handoff_pending_count') or payload.get('pending_handoff_count') or 0),
            'sla_breached_count': int(payload.get('active_sla_breached_count') or payload.get('sla_breached_count') or 0),
            'sla_rerouted_count': int(payload.get('active_sla_rerouted_count') or payload.get('sla_rerouted_count') or 0),
            'team_queue_alert_count': int(payload.get('active_team_queue_alert_count') or payload.get('team_queue_alert_count') or 0),
            'queue_at_capacity_count': int(payload.get('active_queue_at_capacity_count') or payload.get('queue_at_capacity_count') or 0),
            'queue_over_capacity_count': int(payload.get('active_queue_over_capacity_count') or payload.get('queue_over_capacity_count') or 0),
            'load_aware_routed_count': int(payload.get('active_load_aware_routed_count') or payload.get('load_aware_routed_count') or 0),
            'reservation_protected_alert_count': int(payload.get('active_reservation_protected_alert_count') or payload.get('reservation_protected_alert_count') or 0),
            'lease_protected_alert_count': int(payload.get('active_lease_protected_alert_count') or payload.get('lease_protected_alert_count') or 0),
            'temporary_hold_protected_alert_count': int(payload.get('active_temporary_hold_protected_alert_count') or payload.get('temporary_hold_protected_alert_count') or 0),
            'anti_thrashing_kept_alert_count': int(payload.get('active_anti_thrashing_kept_alert_count') or payload.get('anti_thrashing_kept_alert_count') or 0),
            'queue_family_alert_count': int(payload.get('active_queue_family_alert_count') or payload.get('queue_family_alert_count') or 0),
            'family_hysteresis_kept_alert_count': int(payload.get('active_family_hysteresis_kept_alert_count') or payload.get('family_hysteresis_kept_alert_count') or 0),
            'aging_alert_count': int(payload.get('active_aging_alert_count') or payload.get('aging_alert_count') or 0),
            'starving_alert_count': int(payload.get('active_starving_alert_count') or payload.get('starving_alert_count') or 0),
            'starvation_prevented_alert_count': int(payload.get('active_starvation_prevented_alert_count') or payload.get('starvation_prevented_alert_count') or 0),
            'alerts_at_risk_count': int(payload.get('active_alerts_at_risk_count') or payload.get('alerts_at_risk_count') or 0),
            'predicted_sla_breach_count': int(payload.get('active_predicted_sla_breach_count') or payload.get('predicted_sla_breach_count') or 0),
            'expedite_routed_alert_count': int(payload.get('active_expedite_routed_alert_count') or payload.get('expedite_routed_alert_count') or 0),
            'proactive_routed_alert_count': int(payload.get('active_proactive_routed_alert_count') or payload.get('proactive_routed_alert_count') or 0),
            'forecasted_surge_alert_count': int(payload.get('active_forecasted_surge_alert_count') or payload.get('forecasted_surge_alert_count') or 0),
            'overload_governed_alert_count': int(payload.get('active_overload_governed_alert_count') or payload.get('overload_governed_alert_count') or 0),
            'overload_blocked_alert_count': int(payload.get('active_overload_blocked_alert_count') or payload.get('overload_blocked_alert_count') or 0),
            'admission_deferred_alert_count': int(payload.get('active_admission_deferred_alert_count') or payload.get('admission_deferred_alert_count') or 0),
            'manual_gate_alert_count': int(payload.get('active_manual_gate_alert_count') or payload.get('manual_gate_alert_count') or 0),
            'latest_alert_id': str(payload.get('latest_alert_id') or ''),
            'latest_status': str(payload.get('latest_status') or ''),
            'latest_owner_id': str(payload.get('latest_owner_id') or ''),
            'latest_queue_id': str(payload.get('latest_queue_id') or ''),
            'latest_route_id': str(payload.get('latest_route_id') or ''),
        }

    @staticmethod
    def _compact_baseline_promotion_simulation_custody_active_alert(alert: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(alert or {})
        ownership = dict(payload.get('ownership') or {})
        routing = dict(payload.get('routing') or {})
        suppression = dict(payload.get('suppression_state') or {})
        handoff = dict(payload.get('handoff') or {})
        sla = dict(payload.get('sla') or payload.get('sla_state') or {})
        return {
            'alert_id': str(payload.get('alert_id') or ''),
            'status': str(payload.get('status') or ''),
            'active': bool(payload.get('active', False)),
            'severity': str(payload.get('severity') or ''),
            'escalation_level': int(payload.get('escalation_level') or 0),
            'ownership': {
                'status': str(ownership.get('status') or ''),
                'owner_id': str(ownership.get('owner_id') or ''),
                'owner_role': str(ownership.get('owner_role') or ''),
                'queue_id': str(ownership.get('queue_id') or ''),
                'queue_label': str(ownership.get('queue_label') or ''),
                'claimed_at': ownership.get('claimed_at'),
                'updated_at': ownership.get('updated_at'),
            },
            'routing': {
                'route_id': str(routing.get('route_id') or ''),
                'route_label': str(routing.get('route_label') or ''),
                'queue_id': str(routing.get('queue_id') or ''),
                'queue_label': str(routing.get('queue_label') or ''),
                'owner_role': str(routing.get('owner_role') or ''),
                'source': str(routing.get('source') or ''),
                'manual_override': bool(routing.get('manual_override', False)),
                'load_aware': bool(routing.get('load_aware', False)),
                'selection_reason': str(routing.get('selection_reason') or ''),
                'queue_active_count': int(routing.get('queue_active_count') or 0),
                'queue_capacity': int(routing.get('queue_capacity') or 0),
                'queue_available': routing.get('queue_available'),
                'queue_load_ratio': float(routing.get('queue_load_ratio') or 0.0),
                'queue_at_capacity': bool(routing.get('queue_at_capacity', False)),
                'queue_over_capacity': bool(routing.get('queue_over_capacity', False)),
                'reservation_enabled': bool(routing.get('reservation_enabled', False)),
                'reserved_capacity': int(routing.get('reserved_capacity') or 0),
                'general_capacity': int(routing.get('general_capacity') or 0),
                'general_available': routing.get('general_available'),
                'reserved_available': routing.get('reserved_available'),
                'reservation_eligible': bool(routing.get('reservation_eligible', False)),
                'reservation_applied': bool(routing.get('reservation_applied', False)),
                'lease_active': bool(routing.get('lease_active', False)),
                'lease_expired': bool(routing.get('lease_expired', False)),
                'leased_capacity': int(routing.get('leased_capacity') or 0),
                'lease_available': routing.get('lease_available'),
                'lease_expires_at': routing.get('lease_expires_at'),
                'lease_reason': str(routing.get('lease_reason') or ''),
                'lease_holder': str(routing.get('lease_holder') or ''),
                'lease_eligible': bool(routing.get('lease_eligible', False)),
                'lease_applied': bool(routing.get('lease_applied', False)),
                'starvation_lease_capacity_borrowed': bool(routing.get('starvation_lease_capacity_borrowed', False)),
                'expedite_lease_capacity_borrowed': bool(routing.get('expedite_lease_capacity_borrowed', False)),
                'temporary_hold_count': int(routing.get('temporary_hold_count') or 0),
                'temporary_hold_capacity': int(routing.get('temporary_hold_capacity') or 0),
                'temporary_hold_available': routing.get('temporary_hold_available'),
                'temporary_hold_reason': str((list(routing.get('temporary_hold_reasons') or ['']) or [''])[0] or ''),
                'temporary_hold_eligible': bool(routing.get('temporary_hold_eligible', False)),
                'temporary_hold_applied': bool(routing.get('temporary_hold_applied', False)),
                'starvation_temporary_hold_borrowed': bool(routing.get('starvation_temporary_hold_borrowed', False)),
                'expedite_temporary_hold_borrowed': bool(routing.get('expedite_temporary_hold_borrowed', False)),
                'expired_temporary_hold_count': int(routing.get('expired_temporary_hold_count') or 0),
                'effective_capacity': int(routing.get('effective_capacity') or 0),
                'alert_wait_age_s': int(routing.get('alert_wait_age_s') or 0),
                'aging_applied': bool(routing.get('aging_applied', False)),
                'starving': bool(routing.get('starving', False)),
                'queue_oldest_alert_age_s': int(routing.get('queue_oldest_alert_age_s') or 0),
                'queue_aged_alert_count': int(routing.get('queue_aged_alert_count') or 0),
                'queue_starving_alert_count': int(routing.get('queue_starving_alert_count') or 0),
                'starvation_reserved_capacity_borrowed': bool(routing.get('starvation_reserved_capacity_borrowed', False)),
                'starvation_prevention_applied': bool(routing.get('starvation_prevention_applied', False)),
                'starvation_prevention_reason': str(routing.get('starvation_prevention_reason') or ''),
                'anti_thrashing_applied': bool(routing.get('anti_thrashing_applied', False)),
                'anti_thrashing_reason': str(routing.get('anti_thrashing_reason') or ''),
                'queue_family_id': str(routing.get('queue_family_id') or ''),
                'queue_family_label': str(routing.get('queue_family_label') or ''),
                'queue_family_enabled': bool(routing.get('queue_family_enabled', False)),
                'queue_family_member_count': int(routing.get('queue_family_member_count') or 0),
                'recent_queue_hop_count': int(routing.get('recent_queue_hop_count') or 0),
                'recent_family_hop_count': int(routing.get('recent_family_hop_count') or 0),
                'family_hysteresis_applied': bool(routing.get('family_hysteresis_applied', False)),
                'family_hysteresis_reason': str(routing.get('family_hysteresis_reason') or ''),
                'route_history_queue_ids': [str(item) for item in list(routing.get('route_history_queue_ids') or []) if str(item)],
                'route_history_family_ids': [str(item) for item in list(routing.get('route_history_family_ids') or []) if str(item)],
                'sla_deadline_target': str(routing.get('sla_deadline_target') or ''),
                'time_to_breach_s': routing.get('time_to_breach_s'),
                'predicted_wait_time_s': routing.get('predicted_wait_time_s'),
                'predicted_sla_margin_s': routing.get('predicted_sla_margin_s'),
                'predicted_sla_breach': bool(routing.get('predicted_sla_breach', False)),
                'breach_risk_score': float(routing.get('breach_risk_score') or 0.0),
                'breach_risk_level': str(routing.get('breach_risk_level') or ''),
                'expected_service_time_s': int(routing.get('expected_service_time_s') or 0),
                'forecast_window_s': int(routing.get('forecast_window_s') or 0),
                'forecast_arrivals_count': int(routing.get('forecast_arrivals_count') or 0),
                'forecast_departures_count': int(routing.get('forecast_departures_count') or 0),
                'projected_active_count': int(routing.get('projected_active_count') or 0),
                'projected_load_ratio': float(routing.get('projected_load_ratio') or 0.0),
                'projected_wait_time_s': int(routing.get('projected_wait_time_s') or 0),
                'forecasted_over_capacity': bool(routing.get('forecasted_over_capacity', False)),
                'surge_predicted': bool(routing.get('surge_predicted', False)),
                'proactive_routing_eligible': bool(routing.get('proactive_routing_eligible', False)),
                'proactive_routing_applied': bool(routing.get('proactive_routing_applied', False)),
                'proactive_reason': str(routing.get('proactive_reason') or ''),
                'admission_control_enabled': bool(routing.get('admission_control_enabled', False)),
                'admission_action': str(routing.get('admission_action') or ''),
                'admission_exempt': bool(routing.get('admission_exempt', False)),
                'admission_exempt_reason': str(routing.get('admission_exempt_reason') or ''),
                'admission_decision': str(routing.get('admission_decision') or ''),
                'admission_blocked': bool(routing.get('admission_blocked', False)),
                'admission_reason': str(routing.get('admission_reason') or ''),
                'admission_review_required': bool(routing.get('admission_review_required', False)),
                'overload_governance_enabled': bool(routing.get('overload_governance_enabled', False)),
                'overload_governance_applied': bool(routing.get('overload_governance_applied', False)),
                'overload_action': str(routing.get('overload_action') or ''),
                'overload_projected_load_ratio_threshold': float(routing.get('overload_projected_load_ratio_threshold') or 0.0),
                'overload_projected_wait_time_threshold_s': int(routing.get('overload_projected_wait_time_threshold_s') or 0),
                'overload_predicted': bool(routing.get('overload_predicted', False)),
                'overload_reason': str(routing.get('overload_reason') or ''),
                'expedite_eligible': bool(routing.get('expedite_eligible', False)),
                'expedite_reserved_capacity_borrowed': bool(routing.get('expedite_reserved_capacity_borrowed', False)),
                'expedite_applied': bool(routing.get('expedite_applied', False)),
                'expedite_reason': str(routing.get('expedite_reason') or ''),
            },
            'suppression_state': {
                'suppressed': bool(suppression.get('suppressed', False)),
                'reasons': [str(item) for item in list(suppression.get('reasons') or []) if str(item)],
                'pending_escalation_level': int(suppression.get('pending_escalation_level') or 0),
                'pending_route_id': str(suppression.get('pending_route_id') or ''),
                'pending_queue_id': str(suppression.get('pending_queue_id') or ''),
                'pending_owner_role': str(suppression.get('pending_owner_role') or ''),
            },
            'handoff': {
                'count': int(handoff.get('count') or 0),
                'pending': bool(handoff.get('pending', False)),
                'active_handoff_id': str(handoff.get('active_handoff_id') or ''),
                'pending_to_owner_id': str(handoff.get('pending_to_owner_id') or ''),
                'pending_to_owner_role': str(handoff.get('pending_to_owner_role') or ''),
                'pending_to_queue_id': str(handoff.get('pending_to_queue_id') or ''),
                'pending_since': handoff.get('pending_since'),
            },
            'sla': {
                'status': str(sla.get('status') or ''),
                'breached': bool(sla.get('breached', False)),
                'breached_targets': [str(item) for item in list(sla.get('breached_targets') or []) if str(item)],
                'warning_targets': [str(item) for item in list(sla.get('warning_targets') or []) if str(item)],
                'next_deadline': sla.get('next_deadline'),
            },
            'sla_routing': {
                'status': str((payload.get('sla_routing_state') or {}).get('status') or ('routed' if str(routing.get('source') or '') == 'sla_breach_routing' else '')),
                'reroute_count': int(((payload.get('sla_routing_state') or {}).get('reroute_count')) or (1 if str(routing.get('source') or '') == 'sla_breach_routing' else 0)),
                'last_route_id': str(((payload.get('sla_routing_state') or {}).get('last_route_id')) or routing.get('route_id') or ''),
                'last_queue_id': str(((payload.get('sla_routing_state') or {}).get('last_queue_id')) or routing.get('queue_id') or ''),
                'last_owner_role': str(((payload.get('sla_routing_state') or {}).get('last_owner_role')) or routing.get('owner_role') or ''),
                'pending': bool(((payload.get('sla_routing_state') or {}).get('pending'))),
            },
        }

    @staticmethod
    def _compact_baseline_promotion_simulation_last_alert_action(action: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(action or {})
        return {
            'action': str(payload.get('action') or ''),
            'alert_id': str(payload.get('alert_id') or ''),
            'status': str(payload.get('status') or ''),
            'ownership_status': str(payload.get('ownership_status') or ''),
            'owner_id': str(payload.get('owner_id') or ''),
            'queue_id': str(payload.get('queue_id') or ''),
            'route_id': str(payload.get('route_id') or ''),
            'at': payload.get('at'),
            'by': str(payload.get('by') or ''),
        }

    @staticmethod
    def _compact_baseline_promotion_simulation_routing_policy_pack(payload: dict[str, Any] | None) -> dict[str, Any]:
        pack = dict(payload or {})
        if not pack:
            return {}
        review_timeline = [dict(item or {}) for item in list(pack.get('catalog_review_timeline') or pack.get('catalog_review_events') or []) if isinstance(item, dict)]
        latest_review_note = next(
            (
                item for item in reversed(review_timeline)
                if str(item.get('event_type') or '') in {'review_note', 'review_comment', 'review_decision', 'review_requested'}
            ),
            {},
        )
        return {
            'pack_id': str(pack.get('pack_id') or ''),
            'pack_label': str(pack.get('pack_label') or pack.get('label') or ''),
            'description': str(pack.get('description') or ''),
            'source': str(pack.get('source') or ''),
            'category_keys': [str(item) for item in list(pack.get('category_keys') or []) if str(item)][:8],
            'tags': [str(item) for item in list(pack.get('tags') or []) if str(item)][:8],
            'scenario_count': int(pack.get('scenario_count') or len(list(pack.get('comparison_policies') or [])) or 0),
            'created_at': pack.get('created_at'),
            'created_by': str(pack.get('created_by') or ''),
            'last_used_at': pack.get('last_used_at'),
            'use_count': int(pack.get('use_count') or 0),
            'registry_entry_id': str(pack.get('registry_entry_id') or ''),
            'registry_scope': str(pack.get('registry_scope') or ''),
            'promoted_at': pack.get('promoted_at'),
            'promoted_by': str(pack.get('promoted_by') or ''),
            'promoted_from_pack_id': str(pack.get('promoted_from_pack_id') or ''),
            'promoted_from_source': str(pack.get('promoted_from_source') or ''),
            'shared_from_pack_id': str(pack.get('shared_from_pack_id') or ''),
            'shared_from_source': str(pack.get('shared_from_source') or ''),
            'last_shared_at': pack.get('last_shared_at'),
            'last_shared_by': str(pack.get('last_shared_by') or ''),
            'share_count': int(pack.get('share_count') or 0),
            'share_targets': [str(item) for item in list(pack.get('share_targets') or []) if str(item)][:8],
            'catalog_entry_id': str(pack.get('catalog_entry_id') or ''),
            'catalog_scope': str(pack.get('catalog_scope') or ''),
            'catalog_scope_key': str(pack.get('catalog_scope_key') or ''),
            'promotion_id': str(pack.get('promotion_id') or ''),
            'workspace_id': str(pack.get('workspace_id') or ''),
            'environment': str(pack.get('environment') or ''),
            'portfolio_family_id': str(pack.get('portfolio_family_id') or ''),
            'runtime_family_id': str(pack.get('runtime_family_id') or ''),
            'catalog_promoted_at': pack.get('catalog_promoted_at'),
            'catalog_promoted_by': str(pack.get('catalog_promoted_by') or ''),
            'catalog_share_count': int(pack.get('catalog_share_count') or 0),
            'catalog_last_shared_at': pack.get('catalog_last_shared_at'),
            'catalog_last_shared_by': str(pack.get('catalog_last_shared_by') or ''),
            'catalog_version_key': str(pack.get('catalog_version_key') or ''),
            'catalog_version': int(pack.get('catalog_version') or 0),
            'catalog_lifecycle_state': str(pack.get('catalog_lifecycle_state') or 'draft'),
            'catalog_curated_at': pack.get('catalog_curated_at'),
            'catalog_curated_by': str(pack.get('catalog_curated_by') or ''),
            'catalog_approved_at': pack.get('catalog_approved_at'),
            'catalog_approved_by': str(pack.get('catalog_approved_by') or ''),
            'catalog_deprecated_at': pack.get('catalog_deprecated_at'),
            'catalog_deprecated_by': str(pack.get('catalog_deprecated_by') or ''),
            'catalog_replaced_by_version': int(pack.get('catalog_replaced_by_version') or 0),
            'catalog_is_latest': bool(pack.get('catalog_is_latest', False)),
            'catalog_approval_required': bool(pack.get('catalog_approval_required', False)),
            'catalog_required_approvals': int(pack.get('catalog_required_approvals') or 0),
            'catalog_approval_count': int(pack.get('catalog_approval_count') or 0),
            'catalog_approval_state': str(pack.get('catalog_approval_state') or ''),
            'catalog_approval_requested_at': pack.get('catalog_approval_requested_at'),
            'catalog_approval_requested_by': str(pack.get('catalog_approval_requested_by') or ''),
            'catalog_approval_rejected_at': pack.get('catalog_approval_rejected_at'),
            'catalog_approval_rejected_by': str(pack.get('catalog_approval_rejected_by') or ''),
            'catalog_approvals': [
                {
                    'approval_id': str(item.get('approval_id') or ''),
                    'decision': str(item.get('decision') or ''),
                    'actor': str(item.get('actor') or ''),
                    'role': str(item.get('role') or ''),
                    'at': item.get('at'),
                }
                for item in list(pack.get('catalog_approvals') or [])[:6]
                if isinstance(item, dict)
            ],
            'catalog_review_state': str(pack.get('catalog_review_state') or ''),
            'catalog_review_requested_at': pack.get('catalog_review_requested_at'),
            'catalog_review_requested_by': str(pack.get('catalog_review_requested_by') or ''),
            'catalog_review_assigned_reviewer': str(pack.get('catalog_review_assigned_reviewer') or ''),
            'catalog_review_assigned_role': str(pack.get('catalog_review_assigned_role') or ''),
            'catalog_review_claimed_by': str(pack.get('catalog_review_claimed_by') or ''),
            'catalog_review_claimed_at': pack.get('catalog_review_claimed_at'),
            'catalog_review_last_transition_at': pack.get('catalog_review_last_transition_at'),
            'catalog_review_last_transition_by': str(pack.get('catalog_review_last_transition_by') or ''),
            'catalog_review_last_transition_action': str(pack.get('catalog_review_last_transition_action') or ''),
            'catalog_review_decision_at': pack.get('catalog_review_decision_at'),
            'catalog_review_decision_by': str(pack.get('catalog_review_decision_by') or ''),
            'catalog_review_decision': str(pack.get('catalog_review_decision') or ''),
            'catalog_review_note_count': int(pack.get('catalog_review_note_count') or len(review_timeline) or 0),
            'catalog_review_latest_note': {
                'event_type': str(latest_review_note.get('event_type') or ''),
                'actor': str(latest_review_note.get('actor') or ''),
                'role': str(latest_review_note.get('role') or ''),
                'at': latest_review_note.get('at'),
                'note': str(latest_review_note.get('note') or ''),
                'decision': str(latest_review_note.get('decision') or ''),
            },
            'catalog_review_timeline': [
                {
                    'event_id': str(item.get('event_id') or ''),
                    'event_type': str(item.get('event_type') or ''),
                    'state': str(item.get('state') or ''),
                    'actor': str(item.get('actor') or ''),
                    'role': str(item.get('role') or ''),
                    'at': item.get('at'),
                    'note': str(item.get('note') or '')[:160],
                    'decision': str(item.get('decision') or ''),
                }
                for item in review_timeline[:6]
            ],
            'catalog_dependency_refs': [
                {
                    'dependency_id': str(item.get('dependency_id') or ''),
                    'catalog_entry_id': str(item.get('catalog_entry_id') or ''),
                    'catalog_version_key': str(item.get('catalog_version_key') or ''),
                    'min_catalog_version': int(item.get('min_catalog_version') or 0),
                    'required_lifecycle_state': str(item.get('required_lifecycle_state') or ''),
                    'required_release_state': str(item.get('required_release_state') or ''),
                }
                for item in list(pack.get('catalog_dependency_refs') or [])[:6]
                if isinstance(item, dict)
            ],
            'catalog_dependency_summary': dict(pack.get('catalog_dependency_summary') or {}),
            'catalog_conflict_rules': dict(pack.get('catalog_conflict_rules') or {}),
            'catalog_conflict_summary': dict(pack.get('catalog_conflict_summary') or {}),
            'catalog_freeze_windows': [
                {
                    'window_id': str(item.get('window_id') or ''),
                    'label': str(item.get('label') or ''),
                    'start_at': item.get('start_at'),
                    'end_at': item.get('end_at'),
                    'reason': str(item.get('reason') or ''),
                    'block_stage': bool(item.get('block_stage', False)),
                    'block_release': bool(item.get('block_release', False)),
                    'block_advance': bool(item.get('block_advance', False)),
                }
                for item in list(pack.get('catalog_freeze_windows') or [])[:6]
                if isinstance(item, dict)
            ],
            'catalog_freeze_summary': dict(pack.get('catalog_freeze_summary') or {}),
            'catalog_release_guard': dict(pack.get('catalog_release_guard') or {}),
            'catalog_release_state': str(pack.get('catalog_release_state') or 'draft'),
            'catalog_release_notes': str(pack.get('catalog_release_notes') or ''),
            'catalog_release_train_id': str(pack.get('catalog_release_train_id') or ''),
            'catalog_release_staged_at': pack.get('catalog_release_staged_at'),
            'catalog_release_staged_by': str(pack.get('catalog_release_staged_by') or ''),
            'catalog_released_at': pack.get('catalog_released_at'),
            'catalog_released_by': str(pack.get('catalog_released_by') or ''),
            'catalog_withdrawn_at': pack.get('catalog_withdrawn_at'),
            'catalog_withdrawn_by': str(pack.get('catalog_withdrawn_by') or ''),
            'catalog_withdrawn_reason': str(pack.get('catalog_withdrawn_reason') or ''),
            'catalog_supersedence_summary': LiveCanvasService._baseline_promotion_simulation_custody_catalog_supersedence_summary(pack),
            'catalog_release_rollback_summary': LiveCanvasService._baseline_promotion_simulation_custody_catalog_release_rollback_summary(pack),
            'catalog_emergency_withdrawal_summary': LiveCanvasService._baseline_promotion_simulation_custody_catalog_emergency_withdrawal_summary(pack),
            'catalog_rollout_summary': LiveCanvasService._baseline_promotion_simulation_custody_catalog_rollout_summary(pack),
            'catalog_rollout_enabled': bool(pack.get('catalog_rollout_enabled', False)),
            'catalog_rollout_train_id': str(pack.get('catalog_rollout_train_id') or ''),
            'catalog_rollout_state': str(pack.get('catalog_rollout_state') or ''),
            'catalog_rollout_current_wave_index': int(pack.get('catalog_rollout_current_wave_index') or 0),
            'catalog_rollout_completed_wave_count': int(pack.get('catalog_rollout_completed_wave_count') or 0),
            'catalog_rollout_paused': bool(pack.get('catalog_rollout_paused', False)),
            'catalog_rollout_frozen': bool(pack.get('catalog_rollout_frozen', False)),
            'catalog_rollout_last_transition_at': pack.get('catalog_rollout_last_transition_at'),
            'catalog_rollout_last_transition_by': str(pack.get('catalog_rollout_last_transition_by') or ''),
            'catalog_rollout_last_transition_action': str(pack.get('catalog_rollout_last_transition_action') or ''),
            'catalog_rollout_latest_gate': dict(pack.get('catalog_rollout_latest_gate') or {}),
            'catalog_rollout_waves': [
                {
                    'wave_index': int(item.get('wave_index') or 0),
                    'status': str(item.get('status') or ''),
                    'target_count': len([key for key in list(item.get('target_keys') or []) if str(key)]),
                    'released_at': item.get('released_at'),
                    'released_by': str(item.get('released_by') or ''),
                    'gate_evaluation': dict(item.get('gate_evaluation') or {}),
                }
                for item in list(pack.get('catalog_rollout_waves') or [])[:4]
                if isinstance(item, dict)
            ],
            'catalog_rollout_targets': [
                {
                    'target_key': str(item.get('target_key') or ''),
                    'promotion_id': str(item.get('promotion_id') or ''),
                    'workspace_id': str(item.get('workspace_id') or ''),
                    'environment': str(item.get('environment') or ''),
                    'released': bool(item.get('released', False)),
                    'released_wave_index': int(item.get('released_wave_index') or 0),
                }
                for item in list(pack.get('catalog_rollout_targets') or [])[:6]
                if isinstance(item, dict)
            ],
            'catalog_attestation_count': int(pack.get('catalog_attestation_count') or 0),
            'catalog_latest_attestation': LiveCanvasService._compact_baseline_promotion_simulation_export_report(pack.get('catalog_latest_attestation') or {}),
            'catalog_evidence_package_count': int(pack.get('catalog_evidence_package_count') or 0),
            'catalog_latest_evidence_package': LiveCanvasService._compact_baseline_promotion_simulation_export_report(pack.get('catalog_latest_evidence_package') or {}),
            'catalog_release_bundle_count': int(pack.get('catalog_release_bundle_count') or 0),
            'catalog_latest_release_bundle': LiveCanvasService._compact_baseline_promotion_simulation_export_report(pack.get('catalog_latest_release_bundle') or {}),
            'catalog_compliance_summary': dict(pack.get('catalog_compliance_summary') or {}),
            'catalog_compliance_report_count': int(pack.get('catalog_compliance_report_count') or 0),
            'catalog_latest_compliance_report': LiveCanvasService._compact_baseline_promotion_simulation_export_report(pack.get('catalog_latest_compliance_report') or {}),
            'catalog_replay_count': int(pack.get('catalog_replay_count') or 0),
            'catalog_last_replayed_at': pack.get('catalog_last_replayed_at'),
            'catalog_last_replayed_by': str(pack.get('catalog_last_replayed_by') or ''),
            'catalog_last_replay_source': str(pack.get('catalog_last_replay_source') or ''),
            'catalog_binding_count': int(pack.get('catalog_binding_count') or 0),
            'catalog_last_bound_at': pack.get('catalog_last_bound_at'),
            'catalog_last_bound_by': str(pack.get('catalog_last_bound_by') or ''),
            'catalog_analytics_summary': dict(pack.get('catalog_analytics_summary') or {}),
            'catalog_analytics_report_count': int(pack.get('catalog_analytics_report_count') or 0),
            'catalog_latest_analytics_report': LiveCanvasService._compact_baseline_promotion_simulation_export_report(pack.get('catalog_latest_analytics_report') or {}),
            'organizational_service_id': str(pack.get('organizational_service_id') or ''),
            'organizational_service_entry_id': str(pack.get('organizational_service_entry_id') or ''),
            'organizational_publish_state': str(pack.get('organizational_publish_state') or ''),
            'organizational_visibility': str(pack.get('organizational_visibility') or 'tenant'),
            'organizational_service_scope_key': str(pack.get('organizational_service_scope_key') or ''),
            'organizational_published_at': pack.get('organizational_published_at'),
            'organizational_published_by': str(pack.get('organizational_published_by') or ''),
            'organizational_withdrawn_at': pack.get('organizational_withdrawn_at'),
            'organizational_withdrawn_by': str(pack.get('organizational_withdrawn_by') or ''),
            'organizational_withdrawn_reason': str(pack.get('organizational_withdrawn_reason') or ''),
            'organizational_publication_manifest': {
                'manifest_type': str((pack.get('organizational_publication_manifest') or {}).get('manifest_type') or ''),
                'manifest_digest': str((pack.get('organizational_publication_manifest') or {}).get('manifest_digest') or ''),
                'policy_digest': str((pack.get('organizational_publication_manifest') or {}).get('policy_digest') or ''),
                'published_at': (pack.get('organizational_publication_manifest') or {}).get('published_at'),
                'published_by': str((pack.get('organizational_publication_manifest') or {}).get('published_by') or ''),
            },
            'organizational_publication_health': dict(pack.get('organizational_publication_health') or {}),
            'organizational_reconciliation_report_count': int(pack.get('organizational_reconciliation_report_count') or 0),
            'organizational_latest_reconciliation_report': LiveCanvasService._compact_baseline_promotion_simulation_export_report(pack.get('organizational_latest_reconciliation_report') or {}),
            'catalog_binding_summary': dict(pack.get('catalog_binding_summary') or {}),
            'catalog_effective_binding': LiveCanvasService._compact_baseline_promotion_simulation_catalog_binding(pack.get('catalog_effective_binding') or {}),
            'catalog_is_effective_for_current_scope': bool(pack.get('catalog_is_effective_for_current_scope', False)),
            'report_id': str(pack.get('report_id') or ''),
            'report_type': str(pack.get('report_type') or ''),
            'at': pack.get('at'),
            'by': str(pack.get('by') or ''),
            'catalog_owner_canvas_id': str(pack.get('catalog_owner_canvas_id') or ''),
            'catalog_owner_node_id': str(pack.get('catalog_owner_node_id') or ''),
            'scenarios': [
                {
                    'scenario_id': str(item.get('scenario_id') or ''),
                    'scenario_label': str(item.get('scenario_label') or item.get('label') or ''),
                    'policy_delta_keys': [str(key) for key in list(item.get('policy_delta_keys') or []) if str(key)][:12],
                }
                for item in list(pack.get('comparison_policies') or pack.get('scenarios') or [])[:6]
                if isinstance(item, dict)
            ],
        }

    @staticmethod
    def _compact_baseline_promotion_simulation_routing_replay(payload: dict[str, Any] | None) -> dict[str, Any]:
        replay = dict(payload or {})
        current_route = dict(replay.get('current_route') or {})
        current_policy = dict(replay.get('current_policy') or {})
        current_explainability = dict(current_policy.get('explainability') or {})
        compact_scenarios = []
        raw_scenarios = list(replay.get('scenarios') or [])

        for item in raw_scenarios[:6]:
            scenario = dict(item or {})
            route = dict(scenario.get('route') or {})
            explainability = dict(scenario.get('explainability') or {})
            compact_scenarios.append({
                'scenario_id': str(scenario.get('scenario_id') or ''),
                'scenario_label': str(scenario.get('scenario_label') or ''),
                'policy_delta_keys': [str(key) for key in list(scenario.get('policy_delta_keys') or []) if str(key)][:12],
                'route': {
                    'route_id': str(route.get('route_id') or ''),
                    'queue_id': str(route.get('queue_id') or ''),
                    'queue_label': str(route.get('queue_label') or ''),
                    'queue_family_id': str(route.get('queue_family_id') or ''),
                    'selection_reason': str(route.get('selection_reason') or ''),
                    'anti_thrashing_applied': bool(route.get('anti_thrashing_applied', False)),
                    'family_hysteresis_applied': bool(route.get('family_hysteresis_applied', False)),
                    'expedite_applied': bool(route.get('expedite_applied', False)),
                    'proactive_routing_applied': bool(route.get('proactive_routing_applied', False)),
                    'admission_blocked': bool(route.get('admission_blocked', False)),
                },
                'explainability': {
                    'kept_current_queue': bool(explainability.get('kept_current_queue', False)),
                    'queue_changed': bool(explainability.get('queue_changed', False)),
                    'why_kept_current_queue': str(explainability.get('why_kept_current_queue') or ''),
                    'bypassed_hysteresis': bool(explainability.get('bypassed_hysteresis', False)),
                    'why_bypassed_hysteresis': str(explainability.get('why_bypassed_hysteresis') or ''),
                    'selection_reason': str(explainability.get('selection_reason') or ''),
                },
            })

        current_policy_present = bool(current_policy) and bool(
            str(current_policy.get('scenario_id') or '')
            or str(current_policy.get('scenario_label') or '')
            or str(((current_policy.get('route') or {}).get('queue_id')) or '')
            or str(((current_policy.get('route') or {}).get('route_id')) or '')
        )

        current_policy_scenario_id = str(current_policy.get('scenario_id') or '')
        current_policy_already_listed = bool(current_policy_scenario_id) and any(
            str((item or {}).get('scenario_id') or '') == current_policy_scenario_id
            for item in raw_scenarios
        )
        current_policy_extra = 1 if (current_policy_present and not current_policy_already_listed) else 0

        computed_scenario_count = max(
            len(compact_scenarios) + current_policy_extra,
            len(raw_scenarios) + current_policy_extra,
        )

        return {
            'alert_id': str(replay.get('alert_id') or ''),
            'applied_pack': LiveCanvasService._compact_baseline_promotion_simulation_routing_policy_pack(replay.get('applied_pack') or {}),
            'current_route': {
                'route_id': str(current_route.get('route_id') or ''),
                'queue_id': str(current_route.get('queue_id') or ''),
                'queue_label': str(current_route.get('queue_label') or ''),
                'queue_family_id': str(current_route.get('queue_family_id') or ''),
                'selection_reason': str(current_route.get('selection_reason') or ''),
            },
            'current_policy': {
                'scenario_id': str(current_policy.get('scenario_id') or ''),
                'scenario_label': str(current_policy.get('scenario_label') or ''),
                'route': {
                    'route_id': str(((current_policy.get('route') or {}).get('route_id')) or ''),
                    'queue_id': str(((current_policy.get('route') or {}).get('queue_id')) or ''),
                    'queue_label': str(((current_policy.get('route') or {}).get('queue_label')) or ''),
                    'selection_reason': str(((current_policy.get('route') or {}).get('selection_reason')) or ''),
                },
                'explainability': {
                    'kept_current_queue': bool(current_explainability.get('kept_current_queue', False)),
                    'queue_changed': bool(current_explainability.get('queue_changed', False)),
                    'why_kept_current_queue': str(current_explainability.get('why_kept_current_queue') or ''),
                    'bypassed_hysteresis': bool(current_explainability.get('bypassed_hysteresis', False)),
                    'why_bypassed_hysteresis': str(current_explainability.get('why_bypassed_hysteresis') or ''),
                    'selection_reason': str(current_explainability.get('selection_reason') or ''),
                    'policy_delta_keys': [str(key) for key in list(current_explainability.get('policy_delta_keys') or []) if str(key)][:12],
                },
            },
            'scenario_count': computed_scenario_count,
            'scenarios': compact_scenarios,
        }

    @staticmethod
    def _compact_baseline_promotion_simulation_routing_policy_pack_for_storage(payload: dict[str, Any] | None) -> dict[str, Any]:
        pack = dict(payload or {})
        return {
            'pack_id': str(pack.get('pack_id') or ''),
            'pack_label': str(pack.get('pack_label') or pack.get('label') or ''),
            'source': str(pack.get('source') or 'saved'),
            'category_keys': [str(item) for item in list(pack.get('category_keys') or []) if str(item)][:8],
            'tags': [str(item) for item in list(pack.get('tags') or []) if str(item)][:8],
            'created_at': pack.get('created_at'),
            'created_by': str(pack.get('created_by') or ''),
            'last_used_at': pack.get('last_used_at'),
            'use_count': int(pack.get('use_count') or 0),
            'registry_entry_id': str(pack.get('registry_entry_id') or ''),
            'registry_scope': str(pack.get('registry_scope') or ''),
            'promoted_at': pack.get('promoted_at'),
            'promoted_by': str(pack.get('promoted_by') or ''),
            'promoted_from_pack_id': str(pack.get('promoted_from_pack_id') or ''),
            'promoted_from_source': str(pack.get('promoted_from_source') or ''),
            'shared_from_pack_id': str(pack.get('shared_from_pack_id') or ''),
            'shared_from_source': str(pack.get('shared_from_source') or ''),
            'last_shared_at': pack.get('last_shared_at'),
            'last_shared_by': str(pack.get('last_shared_by') or ''),
            'share_count': int(pack.get('share_count') or 0),
            'share_targets': [str(item) for item in list(pack.get('share_targets') or []) if str(item)][:8],
            'catalog_entry_id': str(pack.get('catalog_entry_id') or ''),
            'catalog_scope': str(pack.get('catalog_scope') or ''),
            'catalog_scope_key': str(pack.get('catalog_scope_key') or ''),
            'promotion_id': str(pack.get('promotion_id') or ''),
            'workspace_id': str(pack.get('workspace_id') or ''),
            'environment': str(pack.get('environment') or ''),
            'portfolio_family_id': str(pack.get('portfolio_family_id') or ''),
            'runtime_family_id': str(pack.get('runtime_family_id') or ''),
            'catalog_promoted_at': pack.get('catalog_promoted_at'),
            'catalog_promoted_by': str(pack.get('catalog_promoted_by') or ''),
            'catalog_share_count': int(pack.get('catalog_share_count') or 0),
            'catalog_last_shared_at': pack.get('catalog_last_shared_at'),
            'catalog_last_shared_by': str(pack.get('catalog_last_shared_by') or ''),
            'catalog_version_key': str(pack.get('catalog_version_key') or ''),
            'catalog_version': int(pack.get('catalog_version') or 0),
            'catalog_lifecycle_state': str(pack.get('catalog_lifecycle_state') or 'draft'),
            'catalog_curated_at': pack.get('catalog_curated_at'),
            'catalog_curated_by': str(pack.get('catalog_curated_by') or ''),
            'catalog_approved_at': pack.get('catalog_approved_at'),
            'catalog_approved_by': str(pack.get('catalog_approved_by') or ''),
            'catalog_deprecated_at': pack.get('catalog_deprecated_at'),
            'catalog_deprecated_by': str(pack.get('catalog_deprecated_by') or ''),
            'catalog_replaced_by_version': int(pack.get('catalog_replaced_by_version') or 0),
            'catalog_is_latest': bool(pack.get('catalog_is_latest', False)),
            'catalog_approval_required': bool(pack.get('catalog_approval_required', False)),
            'catalog_required_approvals': int(pack.get('catalog_required_approvals') or 0),
            'catalog_approval_count': int(pack.get('catalog_approval_count') or 0),
            'catalog_approval_state': str(pack.get('catalog_approval_state') or ''),
            'catalog_approval_requested_at': pack.get('catalog_approval_requested_at'),
            'catalog_approval_requested_by': str(pack.get('catalog_approval_requested_by') or ''),
            'catalog_approval_rejected_at': pack.get('catalog_approval_rejected_at'),
            'catalog_approval_rejected_by': str(pack.get('catalog_approval_rejected_by') or ''),
            'catalog_approvals': [
                {
                    'approval_id': str(item.get('approval_id') or ''),
                    'decision': str(item.get('decision') or ''),
                    'actor': str(item.get('actor') or ''),
                    'role': str(item.get('role') or ''),
                    'at': item.get('at'),
                    'note': str(item.get('note') or ''),
                }
                for item in list(pack.get('catalog_approvals') or [])[:8]
                if isinstance(item, dict)
            ],
            'catalog_review_state': str(pack.get('catalog_review_state') or ''),
            'catalog_review_requested_at': pack.get('catalog_review_requested_at'),
            'catalog_review_requested_by': str(pack.get('catalog_review_requested_by') or ''),
            'catalog_review_assigned_reviewer': str(pack.get('catalog_review_assigned_reviewer') or ''),
            'catalog_review_assigned_role': str(pack.get('catalog_review_assigned_role') or ''),
            'catalog_review_claimed_by': str(pack.get('catalog_review_claimed_by') or ''),
            'catalog_review_claimed_at': pack.get('catalog_review_claimed_at'),
            'catalog_review_last_transition_at': pack.get('catalog_review_last_transition_at'),
            'catalog_review_last_transition_by': str(pack.get('catalog_review_last_transition_by') or ''),
            'catalog_review_last_transition_action': str(pack.get('catalog_review_last_transition_action') or ''),
            'catalog_review_decision_at': pack.get('catalog_review_decision_at'),
            'catalog_review_decision_by': str(pack.get('catalog_review_decision_by') or ''),
            'catalog_review_decision': str(pack.get('catalog_review_decision') or ''),
            'catalog_review_note_count': int(pack.get('catalog_review_note_count') or 0),
            'catalog_review_events': [
                {
                    'event_id': str(item.get('event_id') or ''),
                    'event_type': str(item.get('event_type') or ''),
                    'state': str(item.get('state') or ''),
                    'actor': str(item.get('actor') or ''),
                    'role': str(item.get('role') or ''),
                    'at': item.get('at'),
                    'note': str(item.get('note') or '')[:160],
                    'decision': str(item.get('decision') or ''),
                }
                for item in list(pack.get('catalog_review_events') or pack.get('catalog_review_timeline') or [])[:8]
                if isinstance(item, dict)
            ],
            'catalog_dependency_refs': LiveCanvasService._baseline_promotion_simulation_custody_catalog_dependency_refs(pack.get('catalog_dependency_refs') or []),
            'catalog_conflict_rules': LiveCanvasService._baseline_promotion_simulation_custody_catalog_conflict_rules(pack.get('catalog_conflict_rules') or {}),
            'catalog_freeze_windows': LiveCanvasService._baseline_promotion_simulation_custody_catalog_freeze_windows(pack.get('catalog_freeze_windows') or []),
            'catalog_release_state': str(pack.get('catalog_release_state') or 'draft'),
            'catalog_release_notes': str(pack.get('catalog_release_notes') or ''),
            'catalog_release_train_id': str(pack.get('catalog_release_train_id') or ''),
            'catalog_release_staged_at': pack.get('catalog_release_staged_at'),
            'catalog_release_staged_by': str(pack.get('catalog_release_staged_by') or ''),
            'catalog_released_at': pack.get('catalog_released_at'),
            'catalog_released_by': str(pack.get('catalog_released_by') or ''),
            'catalog_withdrawn_at': pack.get('catalog_withdrawn_at'),
            'catalog_withdrawn_by': str(pack.get('catalog_withdrawn_by') or ''),
            'catalog_withdrawn_reason': str(pack.get('catalog_withdrawn_reason') or ''),
            'catalog_supersedence_state': str(pack.get('catalog_supersedence_state') or ''),
            'catalog_superseded_at': pack.get('catalog_superseded_at'),
            'catalog_superseded_by': str(pack.get('catalog_superseded_by') or ''),
            'catalog_superseded_reason': str(pack.get('catalog_superseded_reason') or ''),
            'catalog_superseded_by_entry_id': str(pack.get('catalog_superseded_by_entry_id') or ''),
            'catalog_superseded_by_version': int(pack.get('catalog_superseded_by_version') or 0),
            'catalog_superseded_by_bundle_id': str(pack.get('catalog_superseded_by_bundle_id') or ''),
            'catalog_supersedes_entry_id': str(pack.get('catalog_supersedes_entry_id') or ''),
            'catalog_supersedes_version': int(pack.get('catalog_supersedes_version') or 0),
            'catalog_restored_from_entry_id': str(pack.get('catalog_restored_from_entry_id') or ''),
            'catalog_restored_from_version': int(pack.get('catalog_restored_from_version') or 0),
            'catalog_restored_at': pack.get('catalog_restored_at'),
            'catalog_restored_by': str(pack.get('catalog_restored_by') or ''),
            'catalog_restored_reason': str(pack.get('catalog_restored_reason') or ''),
            'catalog_rollback_release_state': str(pack.get('catalog_rollback_release_state') or ''),
            'catalog_rollback_release_at': pack.get('catalog_rollback_release_at'),
            'catalog_rollback_release_by': str(pack.get('catalog_rollback_release_by') or ''),
            'catalog_rollback_release_reason': str(pack.get('catalog_rollback_release_reason') or ''),
            'catalog_rollback_target_entry_id': str(pack.get('catalog_rollback_target_entry_id') or ''),
            'catalog_rollback_target_version': int(pack.get('catalog_rollback_target_version') or 0),
            'catalog_emergency_withdrawal_active': bool(pack.get('catalog_emergency_withdrawal_active', False)),
            'catalog_emergency_withdrawal_at': pack.get('catalog_emergency_withdrawal_at'),
            'catalog_emergency_withdrawal_by': str(pack.get('catalog_emergency_withdrawal_by') or ''),
            'catalog_emergency_withdrawal_reason': str(pack.get('catalog_emergency_withdrawal_reason') or ''),
            'catalog_emergency_withdrawal_incident_id': str(pack.get('catalog_emergency_withdrawal_incident_id') or ''),
            'catalog_emergency_withdrawal_severity': str(pack.get('catalog_emergency_withdrawal_severity') or ''),
            'catalog_rollout_enabled': bool(pack.get('catalog_rollout_enabled', False)),
            'catalog_rollout_policy': LiveCanvasService._baseline_promotion_simulation_custody_catalog_rollout_policy(pack.get('catalog_rollout_policy') or {}),
            'catalog_rollout_train_id': str(pack.get('catalog_rollout_train_id') or ''),
            'catalog_rollout_state': str(pack.get('catalog_rollout_state') or ''),
            'catalog_rollout_current_wave_index': int(pack.get('catalog_rollout_current_wave_index') or 0),
            'catalog_rollout_completed_wave_count': int(pack.get('catalog_rollout_completed_wave_count') or 0),
            'catalog_rollout_paused': bool(pack.get('catalog_rollout_paused', False)),
            'catalog_rollout_frozen': bool(pack.get('catalog_rollout_frozen', False)),
            'catalog_rollout_started_at': pack.get('catalog_rollout_started_at'),
            'catalog_rollout_started_by': str(pack.get('catalog_rollout_started_by') or ''),
            'catalog_rollout_completed_at': pack.get('catalog_rollout_completed_at'),
            'catalog_rollout_completed_by': str(pack.get('catalog_rollout_completed_by') or ''),
            'catalog_rollout_rolled_back_at': pack.get('catalog_rollout_rolled_back_at'),
            'catalog_rollout_rolled_back_by': str(pack.get('catalog_rollout_rolled_back_by') or ''),
            'catalog_rollout_rolled_back_reason': str(pack.get('catalog_rollout_rolled_back_reason') or ''),
            'catalog_rollout_last_transition_at': pack.get('catalog_rollout_last_transition_at'),
            'catalog_rollout_last_transition_by': str(pack.get('catalog_rollout_last_transition_by') or ''),
            'catalog_rollout_last_transition_action': str(pack.get('catalog_rollout_last_transition_action') or ''),
            'catalog_rollout_latest_gate': dict(pack.get('catalog_rollout_latest_gate') or {}),
            'catalog_rollout_targets': [
                {
                    'target_key': str(item.get('target_key') or ''),
                    'promotion_id': str(item.get('promotion_id') or ''),
                    'workspace_id': str(item.get('workspace_id') or ''),
                    'environment': str(item.get('environment') or ''),
                    'released': bool(item.get('released', False)),
                    'released_wave_index': int(item.get('released_wave_index') or 0),
                    'released_at': item.get('released_at'),
                    'released_by': str(item.get('released_by') or ''),
                }
                for item in list(pack.get('catalog_rollout_targets') or [])[:24]
                if isinstance(item, dict)
            ],
            'catalog_rollout_waves': [
                {
                    'wave_index': int(item.get('wave_index') or 0),
                    'target_keys': [str(key) for key in list(item.get('target_keys') or []) if str(key)][:24],
                    'status': str(item.get('status') or ''),
                    'released_target_count': int(item.get('released_target_count') or 0),
                    'released_at': item.get('released_at'),
                    'released_by': str(item.get('released_by') or ''),
                    'gate_evaluation': dict(item.get('gate_evaluation') or {}),
                }
                for item in list(pack.get('catalog_rollout_waves') or [])[:12]
                if isinstance(item, dict)
            ],
            'catalog_attestation_count': int(pack.get('catalog_attestation_count') or 0),
            'catalog_latest_attestation': LiveCanvasService._compact_baseline_promotion_simulation_export_report(pack.get('catalog_latest_attestation') or {}),
            'catalog_evidence_package_count': int(pack.get('catalog_evidence_package_count') or 0),
            'catalog_latest_evidence_package': LiveCanvasService._compact_baseline_promotion_simulation_export_report(pack.get('catalog_latest_evidence_package') or {}),
            'catalog_release_bundle_count': int(pack.get('catalog_release_bundle_count') or 0),
            'catalog_latest_release_bundle': LiveCanvasService._compact_baseline_promotion_simulation_export_report(pack.get('catalog_latest_release_bundle') or {}),
            'catalog_compliance_report_count': int(pack.get('catalog_compliance_report_count') or 0),
            'catalog_latest_compliance_report': LiveCanvasService._compact_baseline_promotion_simulation_export_report(pack.get('catalog_latest_compliance_report') or {}),
            'catalog_replay_count': int(pack.get('catalog_replay_count') or 0),
            'catalog_last_replayed_at': pack.get('catalog_last_replayed_at'),
            'catalog_last_replayed_by': str(pack.get('catalog_last_replayed_by') or ''),
            'catalog_last_replay_source': str(pack.get('catalog_last_replay_source') or ''),
            'catalog_binding_count': int(pack.get('catalog_binding_count') or 0),
            'catalog_last_bound_at': pack.get('catalog_last_bound_at'),
            'catalog_last_bound_by': str(pack.get('catalog_last_bound_by') or ''),
            'catalog_analytics_report_count': int(pack.get('catalog_analytics_report_count') or 0),
            'catalog_latest_analytics_report': LiveCanvasService._compact_baseline_promotion_simulation_export_report(pack.get('catalog_latest_analytics_report') or {}),
            'organizational_service_id': str(pack.get('organizational_service_id') or ''),
            'organizational_service_entry_id': str(pack.get('organizational_service_entry_id') or ''),
            'organizational_publish_state': str(pack.get('organizational_publish_state') or ''),
            'organizational_visibility': str(pack.get('organizational_visibility') or 'tenant'),
            'organizational_service_scope_key': str(pack.get('organizational_service_scope_key') or ''),
            'organizational_published_at': pack.get('organizational_published_at'),
            'organizational_published_by': str(pack.get('organizational_published_by') or ''),
            'organizational_withdrawn_at': pack.get('organizational_withdrawn_at'),
            'organizational_withdrawn_by': str(pack.get('organizational_withdrawn_by') or ''),
            'organizational_withdrawn_reason': str(pack.get('organizational_withdrawn_reason') or ''),
            'organizational_publication_manifest': {
                'manifest_type': str((pack.get('organizational_publication_manifest') or {}).get('manifest_type') or ''),
                'manifest_digest': str((pack.get('organizational_publication_manifest') or {}).get('manifest_digest') or ''),
                'policy_digest': str((pack.get('organizational_publication_manifest') or {}).get('policy_digest') or ''),
                'published_at': (pack.get('organizational_publication_manifest') or {}).get('published_at'),
                'published_by': str((pack.get('organizational_publication_manifest') or {}).get('published_by') or ''),
            },
            'organizational_publication_health': dict(pack.get('organizational_publication_health') or {}),
            'organizational_reconciliation_report_count': int(pack.get('organizational_reconciliation_report_count') or 0),
            'organizational_latest_reconciliation_report': LiveCanvasService._compact_baseline_promotion_simulation_export_report(pack.get('organizational_latest_reconciliation_report') or {}),
            'catalog_binding_summary': dict(pack.get('catalog_binding_summary') or {}),
            'catalog_effective_binding': LiveCanvasService._compact_baseline_promotion_simulation_catalog_binding(pack.get('catalog_effective_binding') or {}),
            'catalog_is_effective_for_current_scope': bool(pack.get('catalog_is_effective_for_current_scope', False)),
            'report_id': str(pack.get('report_id') or ''),
            'report_type': str(pack.get('report_type') or ''),
            'at': pack.get('at'),
            'by': str(pack.get('by') or ''),
            'comparison_policies': [
                {
                    'scenario_id': str(item.get('scenario_id') or ''),
                    'scenario_label': str(item.get('scenario_label') or item.get('label') or ''),
                    'policy_overrides': dict(item.get('policy_overrides') or item.get('overrides') or {}),
                }
                for item in list(pack.get('comparison_policies') or [])[:8]
                if isinstance(item, dict)
            ],
        }

