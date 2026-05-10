"""baseline_rollout_support._custody_mixin

Sub-mixin extracted from
``openmiura.application.runtime_adapters.external.baseline_rollout_support``
so that no individual file in the package exceeds 1,500 lines. The
public class ``OpenClawBaselineRolloutSupportMixin`` continues to
inherit from this sub-mixin.

The module-level ``OpenClawBaselineRolloutSupportMixin = None`` sentinel
is rebound by ``baseline_rollout_support/__init__.py`` so that the few
``@staticmethod`` call sites that reference the class by name resolve
correctly at call time.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


OpenClawBaselineRolloutSupportMixin: type | None = None  # late-bound by __init__.py


class _OpenClawBaselineRolloutSupportCustodyMixin:
    """Sub-mixin: custody methods on OpenClawBaselineRolloutSupportMixin."""

    @staticmethod
    def _baseline_promotion_simulation_custody_capacity_tier_state(
        *,
        active_count: int,
        capacity: int,
        general_capacity: int,
        reserved_capacity: int = 0,
        leased_capacity: int = 0,
        hold_capacity: int = 0,
    ) -> dict[str, int | None]:
        total_capacity = max(0, int(capacity or 0))
        general_capacity_value = max(0, min(total_capacity, int(general_capacity or 0)))
        remaining_capacity = max(0, total_capacity - general_capacity_value)
        reserved_capacity_value = max(0, min(remaining_capacity, int(reserved_capacity or 0)))
        remaining_capacity = max(0, remaining_capacity - reserved_capacity_value)
        leased_capacity_value = max(0, min(remaining_capacity, int(leased_capacity or 0)))
        remaining_capacity = max(0, remaining_capacity - leased_capacity_value)
        hold_capacity_value = max(0, min(remaining_capacity, int(hold_capacity or 0)))
        active_value = max(0, int(active_count or 0))
        general_used = min(active_value, general_capacity_value)
        remaining_active = max(0, active_value - general_used)
        reserved_used = min(remaining_active, reserved_capacity_value)
        remaining_active = max(0, remaining_active - reserved_used)
        leased_used = min(remaining_active, leased_capacity_value)
        remaining_active = max(0, remaining_active - leased_used)
        hold_used = min(remaining_active, hold_capacity_value)
        return {
            'general_capacity': general_capacity_value,
            'reserved_capacity': reserved_capacity_value,
            'leased_capacity': leased_capacity_value,
            'hold_capacity': hold_capacity_value,
            'general_available': (max(0, general_capacity_value - general_used) if total_capacity > 0 else None),
            'reserved_available': (max(0, reserved_capacity_value - reserved_used) if total_capacity > 0 else None),
            'lease_available': (max(0, leased_capacity_value - leased_used) if total_capacity > 0 else None),
            'hold_available': (max(0, hold_capacity_value - hold_used) if total_capacity > 0 else None),
        }

    @staticmethod
    def _baseline_promotion_simulation_custody_normalize_temporary_hold(
        raw_hold: dict[str, Any] | None,
        *,
        default_ttl_s: int = 0,
        now_ts: float | None = None,
        index: int = 1,
    ) -> dict[str, Any]:
        payload = dict(raw_hold or {})
        try:
            hold_capacity = int(payload.get('capacity') or payload.get('hold_capacity') or payload.get('reserved_capacity') or 0)
        except Exception:
            hold_capacity = 0
        hold_created_at = payload.get('created_at')
        hold_expires_at = payload.get('expires_at') or payload.get('hold_expires_at') or payload.get('until')
        try:
            hold_created_at_value = float(hold_created_at) if hold_created_at is not None else None
        except Exception:
            hold_created_at_value = None
        try:
            hold_expires_at_value = float(hold_expires_at) if hold_expires_at is not None else None
        except Exception:
            hold_expires_at_value = None
        if hold_expires_at_value is None and default_ttl_s > 0:
            base_ts = hold_created_at_value if hold_created_at_value is not None else float(now_ts if now_ts is not None else time.time())
            hold_expires_at_value = float(base_ts + max(0, int(default_ttl_s or 0)))
        queue_types = [
            str(item).strip()
            for item in list(payload.get('for_queue_types') or payload.get('queue_types') or payload.get('eligible_queue_types') or [])
            if str(item).strip()
        ]
        severities = [
            str(item).strip().lower()
            for item in list(payload.get('for_severities') or payload.get('severities') or payload.get('eligible_severities') or [])
            if str(item).strip()
        ]
        active = bool(max(0, hold_capacity) > 0 and (hold_expires_at_value is None or hold_expires_at_value > float(now_ts if now_ts is not None else time.time())))
        return {
            'hold_id': str(payload.get('hold_id') or payload.get('id') or f'temporary-hold-{index}').strip() or f'temporary-hold-{index}',
            'label': str(payload.get('label') or payload.get('name') or f'Temporary hold {index}').strip() or f'Temporary hold {index}',
            'capacity': max(0, int(hold_capacity or 0)),
            'reason': str(payload.get('reason') or payload.get('hold_reason') or '').strip(),
            'holder': str(payload.get('holder') or payload.get('owner') or '').strip(),
            'created_at': hold_created_at_value,
            'expires_at': hold_expires_at_value,
            'for_queue_types': queue_types,
            'for_severities': severities,
            'active': active,
            'expired': bool(max(0, hold_capacity) > 0 and hold_expires_at_value is not None and hold_expires_at_value <= float(now_ts if now_ts is not None else time.time())),
        }

    def _baseline_promotion_simulation_custody_route_explainability(
        self,
        *,
        current_route: dict[str, Any] | None,
        replayed_route: dict[str, Any] | None,
        scenario_label: str,
        policy_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        current_payload = dict(current_route or {})
        replay_payload = dict(replayed_route or {})
        current_queue_id = str(current_payload.get('queue_id') or '').strip()
        replay_queue_id = str(replay_payload.get('queue_id') or '').strip()
        current_family_id = str(current_payload.get('queue_family_id') or current_payload.get('queue_type') or '').strip()
        replay_family_id = str(replay_payload.get('queue_family_id') or replay_payload.get('queue_type') or '').strip()
        kept_current_queue = bool(current_queue_id and replay_queue_id and current_queue_id == replay_queue_id)
        queue_changed = bool(current_queue_id and replay_queue_id and current_queue_id != replay_queue_id)
        maintained_by = ''
        if kept_current_queue:
            if bool(replay_payload.get('manual_override')):
                maintained_by = 'manual_override'
            elif bool(replay_payload.get('family_hysteresis_applied')):
                maintained_by = 'family_hysteresis'
            elif bool(replay_payload.get('anti_thrashing_applied')):
                maintained_by = 'anti_thrashing'
            elif str(replay_payload.get('admission_decision') or '') == 'manual_gate':
                maintained_by = 'manual_gate'
            else:
                maintained_by = 'policy_preference'
        bypass_reason = ''
        selection_reason = str(replay_payload.get('selection_reason') or '').strip()
        if selection_reason.startswith('expedite_bypass_'):
            bypass_reason = 'expedite'
        elif selection_reason.startswith('proactive_bypass_'):
            bypass_reason = 'proactive_routing'
        elif selection_reason.startswith('starvation_bypass_'):
            bypass_reason = 'starvation_prevention'
        elif selection_reason.startswith('admission_bypass_'):
            bypass_reason = 'admission_control'
        blocking_reasons = [
            str(item)
            for item in [
                replay_payload.get('anti_thrashing_reason'),
                replay_payload.get('family_hysteresis_reason'),
                replay_payload.get('admission_reason'),
                replay_payload.get('starvation_prevention_reason'),
                replay_payload.get('expedite_reason'),
                replay_payload.get('proactive_reason'),
                replay_payload.get('overload_reason'),
            ]
            if str(item).strip()
        ]
        current_wait = int(current_payload.get('projected_wait_time_s') or current_payload.get('predicted_wait_time_s') or 0)
        replay_wait = int(replay_payload.get('projected_wait_time_s') or replay_payload.get('predicted_wait_time_s') or 0)
        policy_delta_keys = self._baseline_promotion_simulation_custody_policy_delta_keys(policy_overrides or {})
        return {
            'scenario_label': str(scenario_label or 'current_policy'),
            'kept_current_queue': kept_current_queue,
            'queue_changed': queue_changed,
            'why_kept_current_queue': maintained_by,
            'bypassed_hysteresis': bool(bypass_reason),
            'why_bypassed_hysteresis': bypass_reason,
            'selection_reason': selection_reason,
            'blocking_reasons': blocking_reasons[:6],
            'current_queue_id': current_queue_id,
            'current_queue_label': str(current_payload.get('queue_label') or current_queue_id),
            'current_queue_family_id': current_family_id,
            'replayed_queue_id': replay_queue_id,
            'replayed_queue_label': str(replay_payload.get('queue_label') or replay_queue_id),
            'replayed_queue_family_id': replay_family_id,
            'current_load_ratio': float(current_payload.get('queue_load_ratio') or 0.0),
            'replayed_load_ratio': float(replay_payload.get('queue_load_ratio') or 0.0),
            'current_projected_wait_time_s': current_wait,
            'replayed_projected_wait_time_s': replay_wait,
            'current_projected_load_ratio': float(current_payload.get('projected_load_ratio') or current_payload.get('queue_load_ratio') or 0.0),
            'replayed_projected_load_ratio': float(replay_payload.get('projected_load_ratio') or replay_payload.get('queue_load_ratio') or 0.0),
            'policy_delta_keys': policy_delta_keys[:12],
        }

    def _baseline_promotion_simulation_custody_route_replay(
        self,
        *,
        alert: dict[str, Any] | None,
        policy: dict[str, Any] | None,
        queue_state: dict[str, Any] | None,
        current_route: dict[str, Any] | None = None,
        comparison_policies: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        alert_payload = dict(alert or {})
        normalized_policy = self._normalize_baseline_promotion_simulation_custody_monitoring_policy(dict(policy or {}))
        current_route_payload = dict(current_route or self._baseline_promotion_simulation_custody_routing_projection(alert_payload))
        scenario_specs = [{'scenario_id': 'current_policy', 'scenario_label': 'Current policy', 'policy_overrides': {}}]
        for index, raw_item in enumerate(list(comparison_policies or []), start=1):
            item = dict(raw_item or {})
            overrides = dict(item.get('policy_overrides') or item.get('overrides') or {})
            if not overrides:
                overrides = {key: value for key, value in item.items() if key not in {'scenario_id', 'scenario_label', 'label', 'policy_overrides', 'overrides'}}
            scenario_label = str(item.get('scenario_label') or item.get('label') or f'comparison_policy_{index}').strip() or f'comparison_policy_{index}'
            scenario_id = str(item.get('scenario_id') or f'comparison_policy_{index}').strip() or f'comparison_policy_{index}'
            scenario_specs.append({'scenario_id': scenario_id, 'scenario_label': scenario_label, 'policy_overrides': overrides})
        scenarios: list[dict[str, Any]] = []
        for spec in scenario_specs:
            overrides = dict(spec.get('policy_overrides') or {})
            effective_policy = self._baseline_promotion_simulation_custody_merge_policy_overrides(normalized_policy, overrides)
            scenario_queue_state = {'policy': dict(effective_policy.get('queue_capacity_policy') or ((queue_state or {}).get('policy')) or {}), 'queues': dict((queue_state or {}).get('queues') or {}), 'summary': dict((queue_state or {}).get('summary') or {})}
            simulated_route = self._baseline_promotion_simulation_custody_route_for_alert(effective_policy, alert_payload, queue_state=scenario_queue_state)
            scenarios.append({
                'scenario_id': str(spec.get('scenario_id') or ''),
                'scenario_label': str(spec.get('scenario_label') or ''),
                'policy_overrides': overrides,
                'policy_delta_keys': self._baseline_promotion_simulation_custody_policy_delta_keys(overrides),
                'route': dict(simulated_route or {}),
                'explainability': self._baseline_promotion_simulation_custody_route_explainability(
                    current_route=current_route_payload,
                    replayed_route=simulated_route,
                    scenario_label=str(spec.get('scenario_label') or ''),
                    policy_overrides=overrides,
                ),
            })
        current_policy_result = next((item for item in scenarios if str(item.get('scenario_id') or '') == 'current_policy'), dict(scenarios[0] or {}) if scenarios else {})
        return {
            'ok': True,
            'alert_id': str(alert_payload.get('alert_id') or ''),
            'current_route': dict(current_route_payload or {}),
            'current_policy': current_policy_result,
            'scenarios': scenarios,
        }

    @staticmethod
    def _normalize_baseline_promotion_simulation_custody_route(raw_route: dict[str, Any] | None, *, index: int = 1, fallback_target_path: str = '/ui/?tab=operator') -> dict[str, Any]:
        payload = dict(raw_route or {})
        try:
            min_level = int(payload.get('min_escalation_level') or payload.get('min_level') or payload.get('level') or payload.get('escalation_level') or 0)
        except Exception:
            min_level = 0
        max_level_raw = payload.get('max_escalation_level') or payload.get('max_level')
        try:
            max_level = int(max_level_raw) if max_level_raw is not None else None
        except Exception:
            max_level = None
        capacity_raw = payload.get('queue_capacity')
        if capacity_raw is None:
            capacity_raw = payload.get('capacity')
        try:
            queue_capacity = int(capacity_raw) if capacity_raw is not None else 0
        except Exception:
            queue_capacity = 0
        try:
            load_weight = float(payload.get('load_weight') or payload.get('queue_weight') or 1.0)
        except Exception:
            load_weight = 1.0
        return {
            'route_id': str(payload.get('route_id') or payload.get('id') or f'route-{index}').strip() or f'route-{index}',
            'label': str(payload.get('label') or payload.get('name') or f'Route {index}').strip() or f'Route {index}',
            'min_escalation_level': max(0, int(min_level or 0)),
            'max_escalation_level': None if max_level is None else max(0, int(max_level or 0)),
            'queue_id': str(payload.get('queue_id') or payload.get('queue') or '').strip(),
            'queue_label': str(payload.get('queue_label') or payload.get('queue_name') or payload.get('queue') or '').strip(),
            'owner_role': str(payload.get('owner_role') or payload.get('requested_role') or '').strip(),
            'owner_id': str(payload.get('owner_id') or payload.get('assignee') or '').strip(),
            'target_path': str(payload.get('target_path') or fallback_target_path).strip() or fallback_target_path,
            'severity': str(payload.get('severity') or '').strip(),
            'breach_targets': [str(item).strip() for item in list(payload.get('breach_targets') or payload.get('on_targets') or payload.get('targets') or []) if str(item).strip()],
            'queue_type': str(payload.get('queue_type') or payload.get('type') or '').strip(),
            'queue_family_id': str(payload.get('queue_family_id') or payload.get('family_id') or payload.get('family') or payload.get('queue_type') or payload.get('type') or '').strip(),
            'queue_family_label': str(payload.get('queue_family_label') or payload.get('family_label') or payload.get('queue_family_id') or payload.get('family_id') or payload.get('family') or payload.get('queue_type') or payload.get('type') or '').strip(),
            'queue_capacity': max(0, int(queue_capacity or 0)),
            'queue_hard_limit': bool(payload.get('queue_hard_limit', payload.get('hard_limit', False))),
            'load_weight': max(0.1, float(load_weight or 1.0)),
            'load_aware': bool(payload.get('load_aware')),
            'selection_reason': str(payload.get('selection_reason') or '').strip(),
            'queue_active_count': int(payload.get('queue_active_count') or 0),
            'queue_available': payload.get('queue_available'),
            'queue_load_ratio': float(payload.get('queue_load_ratio') or 0.0),
            'queue_at_capacity': bool(payload.get('queue_at_capacity')),
            'queue_over_capacity': bool(payload.get('queue_over_capacity')),
            'queue_warning': bool(payload.get('queue_warning')),
            'reservation_enabled': bool(payload.get('reservation_enabled')),
            'reserved_capacity': int(payload.get('reserved_capacity') or 0),
            'general_capacity': int(payload.get('general_capacity') or 0),
            'general_available': payload.get('general_available'),
            'reserved_available': payload.get('reserved_available'),
            'reservation_eligible': bool(payload.get('reservation_eligible')),
            'reservation_applied': bool(payload.get('reservation_applied')),
            'lease_active': bool(payload.get('lease_active')),
            'lease_expired': bool(payload.get('lease_expired')),
            'leased_capacity': int(payload.get('leased_capacity') or 0),
            'lease_available': payload.get('lease_available'),
            'lease_expires_at': payload.get('lease_expires_at'),
            'lease_reason': str(payload.get('lease_reason') or '').strip(),
            'lease_holder': str(payload.get('lease_holder') or '').strip(),
            'lease_id': str(payload.get('lease_id') or '').strip(),
            'lease_eligible': bool(payload.get('lease_eligible')),
            'lease_applied': bool(payload.get('lease_applied')),
            'starvation_lease_capacity_borrowed': bool(payload.get('starvation_lease_capacity_borrowed')),
            'expedite_lease_capacity_borrowed': bool(payload.get('expedite_lease_capacity_borrowed')),
            'temporary_hold_count': int(payload.get('temporary_hold_count') or 0),
            'temporary_hold_capacity': int(payload.get('temporary_hold_capacity') or 0),
            'temporary_hold_available': payload.get('temporary_hold_available'),
            'temporary_hold_ids': [str(item) for item in list(payload.get('temporary_hold_ids') or []) if str(item)],
            'temporary_hold_reasons': [str(item) for item in list(payload.get('temporary_hold_reasons') or []) if str(item)],
            'temporary_hold_eligible': bool(payload.get('temporary_hold_eligible')),
            'temporary_hold_applied': bool(payload.get('temporary_hold_applied')),
            'starvation_temporary_hold_borrowed': bool(payload.get('starvation_temporary_hold_borrowed')),
            'expedite_temporary_hold_borrowed': bool(payload.get('expedite_temporary_hold_borrowed')),
            'expired_temporary_hold_count': int(payload.get('expired_temporary_hold_count') or 0),
            'expired_temporary_hold_ids': [str(item) for item in list(payload.get('expired_temporary_hold_ids') or []) if str(item)],
            'effective_capacity': int(payload.get('effective_capacity') or 0),
            'alert_wait_age_s': int(payload.get('alert_wait_age_s') or 0),
            'aging_applied': bool(payload.get('aging_applied')),
            'starving': bool(payload.get('starving')),
            'queue_oldest_alert_age_s': int(payload.get('queue_oldest_alert_age_s') or 0),
            'queue_aged_alert_count': int(payload.get('queue_aged_alert_count') or 0),
            'queue_starving_alert_count': int(payload.get('queue_starving_alert_count') or 0),
            'starvation_reserved_capacity_borrowed': bool(payload.get('starvation_reserved_capacity_borrowed')),
            'starvation_prevention_applied': bool(payload.get('starvation_prevention_applied')),
            'starvation_prevention_reason': str(payload.get('starvation_prevention_reason') or '').strip(),
            'anti_thrashing_applied': bool(payload.get('anti_thrashing_applied')),
            'anti_thrashing_reason': str(payload.get('anti_thrashing_reason') or '').strip(),
            'queue_family_enabled': bool(payload.get('queue_family_enabled')),
            'queue_family_member_count': int(payload.get('queue_family_member_count') or 0),
            'recent_queue_hop_count': int(payload.get('recent_queue_hop_count') or 0),
            'recent_family_hop_count': int(payload.get('recent_family_hop_count') or 0),
            'family_hysteresis_applied': bool(payload.get('family_hysteresis_applied')),
            'family_hysteresis_reason': str(payload.get('family_hysteresis_reason') or '').strip(),
            'route_history_queue_ids': [str(item) for item in list(payload.get('route_history_queue_ids') or []) if str(item)],
            'route_history_family_ids': [str(item) for item in list(payload.get('route_history_family_ids') or []) if str(item)],
            'sla_deadline_target': str(payload.get('sla_deadline_target') or '').strip(),
            'time_to_breach_s': payload.get('time_to_breach_s'),
            'predicted_wait_time_s': payload.get('predicted_wait_time_s'),
            'predicted_sla_margin_s': payload.get('predicted_sla_margin_s'),
            'predicted_sla_breach': bool(payload.get('predicted_sla_breach')),
            'breach_risk_score': float(payload.get('breach_risk_score') or 0.0),
            'breach_risk_level': str(payload.get('breach_risk_level') or '').strip(),
            'expected_service_time_s': int(payload.get('expected_service_time_s') or 0),
            'forecast_window_s': int(payload.get('forecast_window_s') or 0),
            'forecast_arrivals_count': int(payload.get('forecast_arrivals_count') or 0),
            'forecast_departures_count': int(payload.get('forecast_departures_count') or 0),
            'projected_active_count': int(payload.get('projected_active_count') or 0),
            'projected_load_ratio': float(payload.get('projected_load_ratio') or 0.0),
            'projected_wait_time_s': int(payload.get('projected_wait_time_s') or 0),
            'forecasted_over_capacity': bool(payload.get('forecasted_over_capacity')),
            'surge_predicted': bool(payload.get('surge_predicted')),
            'proactive_routing_eligible': bool(payload.get('proactive_routing_eligible')),
            'proactive_routing_applied': bool(payload.get('proactive_routing_applied')),
            'proactive_reason': str(payload.get('proactive_reason') or '').strip(),
            'expedite_eligible': bool(payload.get('expedite_eligible')),
            'expedite_reserved_capacity_borrowed': bool(payload.get('expedite_reserved_capacity_borrowed')),
            'expedite_applied': bool(payload.get('expedite_applied')),
            'expedite_reason': str(payload.get('expedite_reason') or '').strip(),
            '_route_index': int(payload.get('_route_index') or 0),
        }

    @staticmethod
    def _baseline_promotion_simulation_custody_ownership_projection(alert: dict[str, Any] | None) -> dict[str, Any]:
        ownership = dict((dict(alert or {}).get('ownership') or {}))
        owner_id = str(ownership.get('owner_id') or '').strip()
        owner_role = str(ownership.get('owner_role') or '').strip()
        queue_id = str(ownership.get('queue_id') or '').strip()
        status = str(ownership.get('status') or '').strip() or ('claimed' if owner_id and str(ownership.get('claimed_by') or '') == owner_id else ('assigned' if owner_id else ('queued' if queue_id or owner_role else 'unassigned')))
        return {
            'status': status,
            'owner_id': owner_id,
            'owner_display': str(ownership.get('owner_display') or owner_id or '').strip(),
            'owner_role': owner_role,
            'queue_id': queue_id,
            'queue_label': str(ownership.get('queue_label') or '').strip(),
            'claimed': status == 'claimed',
            'assigned': bool(owner_id),
            'queued': status == 'queued' or bool(queue_id or owner_role),
            'assigned_at': ownership.get('assigned_at'),
            'assigned_by': str(ownership.get('assigned_by') or '').strip(),
            'claimed_at': ownership.get('claimed_at'),
            'claimed_by': str(ownership.get('claimed_by') or '').strip(),
            'released_at': ownership.get('released_at'),
            'released_by': str(ownership.get('released_by') or '').strip(),
        }

    @staticmethod
    def _baseline_promotion_simulation_custody_routing_projection(alert: dict[str, Any] | None) -> dict[str, Any]:
        routing = dict((dict(alert or {}).get('routing') or {}))
        return {
            'route_id': str(routing.get('route_id') or '').strip(),
            'route_label': str(routing.get('route_label') or routing.get('label') or '').strip(),
            'queue_id': str(routing.get('queue_id') or '').strip(),
            'queue_label': str(routing.get('queue_label') or '').strip(),
            'owner_role': str(routing.get('owner_role') or '').strip(),
            'owner_id': str(routing.get('owner_id') or '').strip(),
            'target_path': str(routing.get('target_path') or '').strip(),
            'updated_at': routing.get('updated_at'),
            'updated_by': str(routing.get('updated_by') or '').strip(),
            'source': str(routing.get('source') or '').strip(),
            'manual_override': bool(routing.get('manual_override')),
            'load_aware': bool(routing.get('load_aware')),
            'selection_reason': str(routing.get('selection_reason') or '').strip(),
            'queue_active_count': int(routing.get('queue_active_count') or 0),
            'queue_capacity': int(routing.get('queue_capacity') or 0),
            'queue_available': routing.get('queue_available'),
            'queue_load_ratio': float(routing.get('queue_load_ratio') or 0.0),
            'queue_at_capacity': bool(routing.get('queue_at_capacity')),
            'queue_over_capacity': bool(routing.get('queue_over_capacity')),
            'queue_warning': bool(routing.get('queue_warning')),
            'reservation_enabled': bool(routing.get('reservation_enabled')),
            'reserved_capacity': int(routing.get('reserved_capacity') or 0),
            'general_capacity': int(routing.get('general_capacity') or 0),
            'general_available': routing.get('general_available'),
            'reserved_available': routing.get('reserved_available'),
            'reservation_eligible': bool(routing.get('reservation_eligible')),
            'reservation_applied': bool(routing.get('reservation_applied')),
            'lease_active': bool(routing.get('lease_active')),
            'lease_expired': bool(routing.get('lease_expired')),
            'leased_capacity': int(routing.get('leased_capacity') or 0),
            'lease_available': routing.get('lease_available'),
            'lease_expires_at': routing.get('lease_expires_at'),
            'lease_reason': str(routing.get('lease_reason') or '').strip(),
            'lease_holder': str(routing.get('lease_holder') or '').strip(),
            'lease_id': str(routing.get('lease_id') or '').strip(),
            'lease_eligible': bool(routing.get('lease_eligible')),
            'lease_applied': bool(routing.get('lease_applied')),
            'starvation_lease_capacity_borrowed': bool(routing.get('starvation_lease_capacity_borrowed')),
            'expedite_lease_capacity_borrowed': bool(routing.get('expedite_lease_capacity_borrowed')),
            'temporary_hold_count': int(routing.get('temporary_hold_count') or 0),
            'temporary_hold_capacity': int(routing.get('temporary_hold_capacity') or 0),
            'temporary_hold_available': routing.get('temporary_hold_available'),
            'temporary_hold_ids': [str(item) for item in list(routing.get('temporary_hold_ids') or []) if str(item)],
            'temporary_hold_reasons': [str(item) for item in list(routing.get('temporary_hold_reasons') or []) if str(item)],
            'temporary_hold_eligible': bool(routing.get('temporary_hold_eligible')),
            'temporary_hold_applied': bool(routing.get('temporary_hold_applied')),
            'starvation_temporary_hold_borrowed': bool(routing.get('starvation_temporary_hold_borrowed')),
            'expedite_temporary_hold_borrowed': bool(routing.get('expedite_temporary_hold_borrowed')),
            'expired_temporary_hold_count': int(routing.get('expired_temporary_hold_count') or 0),
            'expired_temporary_hold_ids': [str(item) for item in list(routing.get('expired_temporary_hold_ids') or []) if str(item)],
            'effective_capacity': int(routing.get('effective_capacity') or 0),
            'alert_wait_age_s': int(routing.get('alert_wait_age_s') or 0),
            'aging_applied': bool(routing.get('aging_applied')),
            'starving': bool(routing.get('starving')),
            'queue_oldest_alert_age_s': int(routing.get('queue_oldest_alert_age_s') or 0),
            'queue_aged_alert_count': int(routing.get('queue_aged_alert_count') or 0),
            'queue_starving_alert_count': int(routing.get('queue_starving_alert_count') or 0),
            'starvation_reserved_capacity_borrowed': bool(routing.get('starvation_reserved_capacity_borrowed')),
            'starvation_prevention_applied': bool(routing.get('starvation_prevention_applied')),
            'starvation_prevention_reason': str(routing.get('starvation_prevention_reason') or '').strip(),
            'anti_thrashing_applied': bool(routing.get('anti_thrashing_applied')),
            'anti_thrashing_reason': str(routing.get('anti_thrashing_reason') or '').strip(),
            'queue_family_id': str(routing.get('queue_family_id') or routing.get('queue_type') or '').strip(),
            'queue_family_label': str(routing.get('queue_family_label') or routing.get('queue_family_id') or routing.get('queue_type') or '').strip(),
            'queue_family_enabled': bool(routing.get('queue_family_enabled')),
            'queue_family_member_count': int(routing.get('queue_family_member_count') or 0),
            'recent_queue_hop_count': int(routing.get('recent_queue_hop_count') or 0),
            'recent_family_hop_count': int(routing.get('recent_family_hop_count') or 0),
            'family_hysteresis_applied': bool(routing.get('family_hysteresis_applied')),
            'family_hysteresis_reason': str(routing.get('family_hysteresis_reason') or '').strip(),
            'route_history_queue_ids': [str(item) for item in list(routing.get('route_history_queue_ids') or []) if str(item)],
            'route_history_family_ids': [str(item) for item in list(routing.get('route_history_family_ids') or []) if str(item)],
            'sla_deadline_target': str(routing.get('sla_deadline_target') or '').strip(),
            'time_to_breach_s': routing.get('time_to_breach_s'),
            'predicted_wait_time_s': routing.get('predicted_wait_time_s'),
            'predicted_sla_margin_s': routing.get('predicted_sla_margin_s'),
            'predicted_sla_breach': bool(routing.get('predicted_sla_breach')),
            'breach_risk_score': float(routing.get('breach_risk_score') or 0.0),
            'breach_risk_level': str(routing.get('breach_risk_level') or '').strip(),
            'expected_service_time_s': int(routing.get('expected_service_time_s') or 0),
            'forecast_window_s': int(routing.get('forecast_window_s') or 0),
            'forecast_arrivals_count': int(routing.get('forecast_arrivals_count') or 0),
            'forecast_departures_count': int(routing.get('forecast_departures_count') or 0),
            'projected_active_count': int(routing.get('projected_active_count') or 0),
            'projected_load_ratio': float(routing.get('projected_load_ratio') or 0.0),
            'projected_wait_time_s': int(routing.get('projected_wait_time_s') or 0),
            'forecasted_over_capacity': bool(routing.get('forecasted_over_capacity')),
            'surge_predicted': bool(routing.get('surge_predicted')),
            'proactive_routing_eligible': bool(routing.get('proactive_routing_eligible')),
            'proactive_routing_applied': bool(routing.get('proactive_routing_applied')),
            'proactive_reason': str(routing.get('proactive_reason') or '').strip(),
            'expedite_eligible': bool(routing.get('expedite_eligible')),
            'expedite_reserved_capacity_borrowed': bool(routing.get('expedite_reserved_capacity_borrowed')),
            'expedite_applied': bool(routing.get('expedite_applied')),
            'expedite_reason': str(routing.get('expedite_reason') or '').strip(),
        }

    @staticmethod
    def _baseline_promotion_simulation_custody_handoff_projection(alert: dict[str, Any] | None) -> dict[str, Any]:
        handoffs = [dict(item) for item in list((dict(alert or {}).get('handoffs') or []))]
        handoffs.sort(key=lambda item: (float(item.get('handoff_at') or 0.0), str(item.get('handoff_id') or '')), reverse=True)
        pending_items = [item for item in handoffs if item.get('accepted_at') is None]
        latest = dict(handoffs[0] or {}) if handoffs else {}
        pending = dict(pending_items[0] or {}) if pending_items else {}
        accepted_count = sum(1 for item in handoffs if item.get('accepted_at') is not None)
        return {
            'count': len(handoffs),
            'accepted_count': accepted_count,
            'pending_count': len(pending_items),
            'pending': bool(pending),
            'latest_handoff_id': str(latest.get('handoff_id') or ''),
            'latest_handoff_at': latest.get('handoff_at'),
            'latest_handed_off_by': str(latest.get('handed_off_by') or ''),
            'latest_from_owner_id': str(latest.get('from_owner_id') or ''),
            'latest_to_owner_id': str(latest.get('to_owner_id') or ''),
            'latest_to_owner_role': str(latest.get('to_owner_role') or ''),
            'latest_to_queue_id': str(latest.get('to_queue_id') or ''),
            'latest_to_route_id': str(latest.get('to_route_id') or ''),
            'latest_reason': str(latest.get('reason') or ''),
            'active_handoff_id': str(pending.get('handoff_id') or ''),
            'pending_to_owner_id': str(pending.get('to_owner_id') or ''),
            'pending_to_owner_role': str(pending.get('to_owner_role') or ''),
            'pending_to_queue_id': str(pending.get('to_queue_id') or ''),
            'pending_to_route_id': str(pending.get('to_route_id') or ''),
            'pending_since': pending.get('handoff_at'),
            'accepted_at': latest.get('accepted_at'),
            'accepted_by': str(latest.get('accepted_by') or ''),
        }

    @staticmethod
    def _baseline_promotion_simulation_custody_sla_projection(
        alert: dict[str, Any] | None,
        policy: dict[str, Any] | None = None,
        *,
        now_ts: float | None = None,
    ) -> dict[str, Any]:
        payload = dict(alert or {})
        monitoring_policy = dict(policy or {})
        sla_policy = dict(monitoring_policy.get('sla_policy') or payload.get('sla_policy') or {})
        enabled = bool(sla_policy.get('enabled'))
        now_ts = float(now_ts if now_ts is not None else time.time())

        def _ts(value: Any) -> float | None:
            if value is None:
                return None
            try:
                return float(value)
            except Exception:
                return None

        def _first(values: list[Any]) -> float | None:
            numeric = [ts for ts in (_ts(value) for value in values) if ts is not None]
            return min(numeric) if numeric else None

        created_at = _ts(payload.get('created_at')) or now_ts
        acknowledged_at = _ts(payload.get('acknowledged_at'))
        claimed_at = _ts(((payload.get('ownership') or {}).get('claimed_at')) or payload.get('claimed_at'))
        assigned_at = _ts(((payload.get('ownership') or {}).get('assigned_at')) or payload.get('assigned_at'))
        resolved_at = _first([payload.get('resolved_at'), payload.get('recovered_at'), payload.get('cleared_at')])
        handoffs = [dict(item) for item in list(payload.get('handoffs') or [])]
        handoffs.sort(key=lambda item: (float(item.get('handoff_at') or 0.0), str(item.get('handoff_id') or '')), reverse=True)
        pending_handoff = next((item for item in handoffs if item.get('accepted_at') is None), {})
        warning_ratio = min(0.95, max(0.0, float(sla_policy.get('warning_ratio') or 0.8))) if enabled else 0.8

        def _target(name: str, target_s: int, *, start_ts: float | None, met_ts: float | None, applicable: bool = True) -> dict[str, Any]:
            result = {
                'name': name,
                'enabled': bool(enabled and target_s > 0 and applicable and start_ts is not None),
                'target_s': max(0, int(target_s or 0)),
                'status': 'disabled',
                'deadline': None,
                'met_at': met_ts,
                'remaining_s': None,
                'breached': False,
                'warning': False,
            }
            if not result['enabled']:
                result['status'] = 'disabled' if target_s <= 0 or not enabled else 'not_applicable'
                return result
            deadline = float(start_ts or now_ts) + float(target_s or 0)
            result['deadline'] = deadline
            if met_ts is not None:
                breached = float(met_ts) > deadline
                result['breached'] = breached
                result['status'] = 'breached' if breached else 'met'
                result['remaining_s'] = int(round(deadline - float(met_ts)))
                return result
            remaining = int(round(deadline - now_ts))
            result['remaining_s'] = remaining
            if remaining < 0:
                result['breached'] = True
                result['status'] = 'breached'
                return result
            elapsed_ratio = 0.0 if target_s <= 0 else max(0.0, min(1.0, (now_ts - float(start_ts or now_ts)) / float(target_s or 1)))
            if elapsed_ratio >= warning_ratio:
                result['warning'] = True
                result['status'] = 'warning'
            else:
                result['status'] = 'pending'
            return result

        acknowledge_target = _target(
            'acknowledge',
            int(sla_policy.get('acknowledge_s') or 0),
            start_ts=created_at,
            met_ts=_first([acknowledged_at, claimed_at]),
            applicable=bool(payload.get('active', False)),
        )
        claim_target = _target(
            'claim',
            int(sla_policy.get('claim_s') or 0),
            start_ts=created_at,
            met_ts=_first([claimed_at, assigned_at]) if str(((payload.get('ownership') or {}).get('owner_id') or '')).strip() else claimed_at,
            applicable=bool(payload.get('active', False)),
        )
        resolve_target = _target(
            'resolve',
            int(sla_policy.get('resolve_s') or 0),
            start_ts=created_at,
            met_ts=resolved_at,
            applicable=True,
        )
        handoff_target = _target(
            'handoff_accept',
            int(sla_policy.get('handoff_accept_s') or 0),
            start_ts=_ts(pending_handoff.get('handoff_at')),
            met_ts=_ts(pending_handoff.get('accepted_at')),
            applicable=bool(pending_handoff),
        )
        targets = [acknowledge_target, claim_target, resolve_target, handoff_target]
        breached_targets = [item['name'] for item in targets if bool(item.get('breached'))]
        warning_targets = [item['name'] for item in targets if bool(item.get('warning'))]
        pending_targets = [item['name'] for item in targets if str(item.get('status') or '') in {'pending', 'warning'}]
        next_deadlines = [float(item.get('deadline')) for item in targets if item.get('deadline') is not None and str(item.get('status') or '') in {'pending', 'warning'}]
        status = 'disabled'
        if enabled:
            if breached_targets:
                status = 'breached'
            elif warning_targets:
                status = 'warning'
            elif any(str(item.get('status') or '') == 'pending' for item in targets):
                status = 'pending'
            elif any(str(item.get('status') or '') == 'met' for item in targets):
                status = 'met'
            else:
                status = 'disabled'
        return {
            'enabled': enabled,
            'status': status,
            'evaluated_at': now_ts,
            'age_s': max(0, int(now_ts - created_at)),
            'breached': bool(breached_targets),
            'breached_targets': breached_targets,
            'warning_targets': warning_targets,
            'pending_targets': pending_targets,
            'next_deadline': (min(next_deadlines) if next_deadlines else None),
            'targets': {
                'acknowledge': acknowledge_target,
                'claim': claim_target,
                'resolve': resolve_target,
                'handoff_accept': handoff_target,
            },
        }

    def _baseline_promotion_simulation_custody_guard(self, release: dict[str, Any] | None) -> dict[str, Any]:
        metadata = dict((release or {}).get('metadata') or {})
        promotion = dict(metadata.get('baseline_promotion') or {})
        guard = dict(promotion.get('simulation_custody_guard') or {})
        alerts = [dict(item) for item in list(promotion.get('simulation_custody_alerts') or [])]
        active_alert = next((item for item in alerts if bool(item.get('active'))), {})
        ownership = self._baseline_promotion_simulation_custody_ownership_projection(active_alert)
        routing = self._baseline_promotion_simulation_custody_routing_projection(active_alert)
        handoff = self._baseline_promotion_simulation_custody_handoff_projection(active_alert)
        sla = dict(active_alert.get('sla_state') or {})
        return {
            'blocked': bool(guard.get('blocked')),
            'reason': str(guard.get('reason') or ''),
            'reasons': [str(item) for item in list(guard.get('reasons') or []) if str(item)],
            'status': str(guard.get('status') or ('blocked' if guard.get('blocked') else 'clear')),
            'updated_at': guard.get('updated_at'),
            'updated_by': str(guard.get('updated_by') or ''),
            'active_alert_id': str(active_alert.get('alert_id') or ''),
            'notification_id': str(active_alert.get('notification_id') or ''),
            'alert_status': str(guard.get('alert_status') or self._baseline_promotion_simulation_custody_alert_status(active_alert) if active_alert else ''),
            'escalated': bool(guard.get('escalated')),
            'escalation_level': int(guard.get('escalation_level') or 0),
            'severity': str(guard.get('severity') or active_alert.get('severity') or ''),
            'suppressed': bool(guard.get('suppressed')),
            'suppression_reasons': [str(item) for item in list(guard.get('suppression_reasons') or []) if str(item)],
            'pending_escalation_level': int(guard.get('pending_escalation_level') or 0),
            'owner_id': str(guard.get('owner_id') or ownership.get('owner_id') or ''),
            'owner_role': str(guard.get('owner_role') or ownership.get('owner_role') or ''),
            'ownership_status': str(guard.get('ownership_status') or ownership.get('status') or ''),
            'queue_id': str(guard.get('queue_id') or ownership.get('queue_id') or routing.get('queue_id') or ''),
            'queue_label': str(guard.get('queue_label') or ownership.get('queue_label') or routing.get('queue_label') or ''),
            'route_id': str(guard.get('route_id') or routing.get('route_id') or ''),
            'route_label': str(guard.get('route_label') or routing.get('route_label') or ''),
            'queue_active_count': int(guard.get('queue_active_count') or routing.get('queue_active_count') or 0),
            'queue_capacity': int(guard.get('queue_capacity') or routing.get('queue_capacity') or 0),
            'queue_available': guard.get('queue_available', routing.get('queue_available')),
            'queue_load_ratio': float(guard.get('queue_load_ratio') or routing.get('queue_load_ratio') or 0.0),
            'queue_at_capacity': bool(guard.get('queue_at_capacity', routing.get('queue_at_capacity'))),
            'queue_over_capacity': bool(guard.get('queue_over_capacity', routing.get('queue_over_capacity'))),
            'queue_warning': bool(guard.get('queue_warning', routing.get('queue_warning'))),
            'reservation_enabled': bool(guard.get('reservation_enabled', routing.get('reservation_enabled'))),
            'reserved_capacity': int(guard.get('reserved_capacity') or routing.get('reserved_capacity') or 0),
            'general_capacity': int(guard.get('general_capacity') or routing.get('general_capacity') or 0),
            'general_available': guard.get('general_available', routing.get('general_available')),
            'reserved_available': guard.get('reserved_available', routing.get('reserved_available')),
            'reservation_eligible': bool(guard.get('reservation_eligible', routing.get('reservation_eligible'))),
            'reservation_applied': bool(guard.get('reservation_applied', routing.get('reservation_applied'))),
            'lease_active': bool(guard.get('lease_active', routing.get('lease_active'))),
            'lease_expired': bool(guard.get('lease_expired', routing.get('lease_expired'))),
            'leased_capacity': int(guard.get('leased_capacity') or routing.get('leased_capacity') or 0),
            'lease_available': guard.get('lease_available', routing.get('lease_available')),
            'lease_expires_at': guard.get('lease_expires_at', routing.get('lease_expires_at')),
            'lease_reason': str(guard.get('lease_reason') or routing.get('lease_reason') or ''),
            'lease_holder': str(guard.get('lease_holder') or routing.get('lease_holder') or ''),
            'lease_id': str(guard.get('lease_id') or routing.get('lease_id') or ''),
            'lease_eligible': bool(guard.get('lease_eligible', routing.get('lease_eligible'))),
            'lease_applied': bool(guard.get('lease_applied', routing.get('lease_applied'))),
            'starvation_lease_capacity_borrowed': bool(guard.get('starvation_lease_capacity_borrowed', routing.get('starvation_lease_capacity_borrowed'))),
            'expedite_lease_capacity_borrowed': bool(guard.get('expedite_lease_capacity_borrowed', routing.get('expedite_lease_capacity_borrowed'))),
            'temporary_hold_count': int(guard.get('temporary_hold_count') or routing.get('temporary_hold_count') or 0),
            'temporary_hold_capacity': int(guard.get('temporary_hold_capacity') or routing.get('temporary_hold_capacity') or 0),
            'temporary_hold_available': guard.get('temporary_hold_available', routing.get('temporary_hold_available')),
            'temporary_hold_ids': [str(item) for item in list(guard.get('temporary_hold_ids') or routing.get('temporary_hold_ids') or []) if str(item)],
            'temporary_hold_reasons': [str(item) for item in list(guard.get('temporary_hold_reasons') or routing.get('temporary_hold_reasons') or []) if str(item)],
            'temporary_hold_eligible': bool(guard.get('temporary_hold_eligible', routing.get('temporary_hold_eligible'))),
            'temporary_hold_applied': bool(guard.get('temporary_hold_applied', routing.get('temporary_hold_applied'))),
            'starvation_temporary_hold_borrowed': bool(guard.get('starvation_temporary_hold_borrowed', routing.get('starvation_temporary_hold_borrowed'))),
            'expedite_temporary_hold_borrowed': bool(guard.get('expedite_temporary_hold_borrowed', routing.get('expedite_temporary_hold_borrowed'))),
            'expired_temporary_hold_count': int(guard.get('expired_temporary_hold_count') or routing.get('expired_temporary_hold_count') or 0),
            'expired_temporary_hold_ids': [str(item) for item in list(guard.get('expired_temporary_hold_ids') or routing.get('expired_temporary_hold_ids') or []) if str(item)],
            'effective_capacity': int(guard.get('effective_capacity') or routing.get('effective_capacity') or 0),
            'alert_wait_age_s': int(guard.get('alert_wait_age_s') or routing.get('alert_wait_age_s') or 0),
            'aging_applied': bool(guard.get('aging_applied', routing.get('aging_applied'))),
            'starving': bool(guard.get('starving', routing.get('starving'))),
            'queue_oldest_alert_age_s': int(guard.get('queue_oldest_alert_age_s') or routing.get('queue_oldest_alert_age_s') or 0),
            'queue_aged_alert_count': int(guard.get('queue_aged_alert_count') or routing.get('queue_aged_alert_count') or 0),
            'queue_starving_alert_count': int(guard.get('queue_starving_alert_count') or routing.get('queue_starving_alert_count') or 0),
            'starvation_reserved_capacity_borrowed': bool(guard.get('starvation_reserved_capacity_borrowed', routing.get('starvation_reserved_capacity_borrowed'))),
            'starvation_prevention_applied': bool(guard.get('starvation_prevention_applied', routing.get('starvation_prevention_applied'))),
            'starvation_prevention_reason': str(guard.get('starvation_prevention_reason') or routing.get('starvation_prevention_reason') or ''),
            'load_aware_routing': bool(guard.get('load_aware_routing', routing.get('load_aware'))),
            'selection_reason': str(guard.get('selection_reason') or routing.get('selection_reason') or ''),
            'anti_thrashing_applied': bool(guard.get('anti_thrashing_applied', routing.get('anti_thrashing_applied'))),
            'anti_thrashing_reason': str(guard.get('anti_thrashing_reason') or routing.get('anti_thrashing_reason') or ''),
            'queue_family_id': str(guard.get('queue_family_id') or routing.get('queue_family_id') or routing.get('queue_type') or ''),
            'queue_family_label': str(guard.get('queue_family_label') or routing.get('queue_family_label') or routing.get('queue_family_id') or routing.get('queue_type') or ''),
            'queue_family_enabled': bool(guard.get('queue_family_enabled', routing.get('queue_family_enabled'))),
            'queue_family_member_count': int(guard.get('queue_family_member_count') or routing.get('queue_family_member_count') or 0),
            'recent_queue_hop_count': int(guard.get('recent_queue_hop_count') or routing.get('recent_queue_hop_count') or 0),
            'recent_family_hop_count': int(guard.get('recent_family_hop_count') or routing.get('recent_family_hop_count') or 0),
            'family_hysteresis_applied': bool(guard.get('family_hysteresis_applied', routing.get('family_hysteresis_applied'))),
            'family_hysteresis_reason': str(guard.get('family_hysteresis_reason') or routing.get('family_hysteresis_reason') or ''),
            'route_history_queue_ids': [str(item) for item in list(guard.get('route_history_queue_ids') or routing.get('route_history_queue_ids') or []) if str(item)],
            'route_history_family_ids': [str(item) for item in list(guard.get('route_history_family_ids') or routing.get('route_history_family_ids') or []) if str(item)],
            'sla_deadline_target': str(guard.get('sla_deadline_target') or routing.get('sla_deadline_target') or ''),
            'time_to_breach_s': guard.get('time_to_breach_s', routing.get('time_to_breach_s')),
            'predicted_wait_time_s': guard.get('predicted_wait_time_s', routing.get('predicted_wait_time_s')),
            'predicted_sla_margin_s': guard.get('predicted_sla_margin_s', routing.get('predicted_sla_margin_s')),
            'predicted_sla_breach': bool(guard.get('predicted_sla_breach', routing.get('predicted_sla_breach'))),
            'breach_risk_score': float(guard.get('breach_risk_score') or routing.get('breach_risk_score') or 0.0),
            'breach_risk_level': str(guard.get('breach_risk_level') or routing.get('breach_risk_level') or ''),
            'expected_service_time_s': int(guard.get('expected_service_time_s') or routing.get('expected_service_time_s') or 0),
            'expedite_eligible': bool(guard.get('expedite_eligible', routing.get('expedite_eligible'))),
            'expedite_reserved_capacity_borrowed': bool(guard.get('expedite_reserved_capacity_borrowed', routing.get('expedite_reserved_capacity_borrowed'))),
            'expedite_applied': bool(guard.get('expedite_applied', routing.get('expedite_applied'))),
            'expedite_reason': str(guard.get('expedite_reason') or routing.get('expedite_reason') or ''),
            'handoff_pending': bool(guard.get('handoff_pending', handoff.get('pending'))),
            'handoff_count': int(guard.get('handoff_count') or handoff.get('count') or 0),
            'sla_status': str(guard.get('sla_status') or sla.get('status') or ''),
            'sla_breached': bool(guard.get('sla_breached', sla.get('breached'))),
            'sla_breached_targets': [str(item) for item in list(guard.get('sla_breached_targets') or sla.get('breached_targets') or []) if str(item)],
            'sla_warning_targets': [str(item) for item in list(guard.get('sla_warning_targets') or sla.get('warning_targets') or []) if str(item)],
            'sla_rerouted': bool(guard.get('sla_rerouted')),
            'sla_reroute_status': str(guard.get('sla_reroute_status') or ''),
            'sla_reroute_count': int(guard.get('sla_reroute_count') or 0),
            'team_queue_id': str(guard.get('team_queue_id') or ''),
        }

