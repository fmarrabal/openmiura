"""baseline_rollout_support._monitoring_b_mixin

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

import copy
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any


OpenClawBaselineRolloutSupportMixin: type | None = None  # late-bound by __init__.py


class _OpenClawBaselineRolloutSupportMonitoringBMixin:
    """Sub-mixin: monitoring b methods on OpenClawBaselineRolloutSupportMixin."""

    def _select_baseline_promotion_simulation_custody_route_by_load(
        self,
        *,
        routes: list[dict[str, Any]],
        queue_state: dict[str, Any] | None,
        current_queue_id: str | None = None,
        prefer_lowest_load: bool = True,
        alert: dict[str, Any] | None = None,
        policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        candidates = []
        for index, item in enumerate(list(routes or [])):
            normalized = self._normalize_baseline_promotion_simulation_custody_route(dict(item or {}), index=index + 1)
            normalized['_route_index'] = index
            candidates.append(normalized)
        if not candidates:
            return {}
        queues = dict((queue_state or {}).get('queues') or {})
        normalized_current_queue_id = str(current_queue_id or '').strip() or str((((alert or {}).get('routing') or {}).get('queue_id') or '')).strip()
        normalized_policy = self._normalize_baseline_promotion_simulation_custody_monitoring_policy(dict(policy or {})) if policy is not None else {}
        queue_policy = dict(((queue_state or {}).get('policy')) or normalized_policy.get('queue_capacity_policy') or {})
        anti_thrashing_enabled = bool(queue_policy.get('anti_thrashing_enabled'))
        reroute_cooldown_s = max(0, int(queue_policy.get('reroute_cooldown_s') or 0))
        min_active_delta = max(0, int(queue_policy.get('anti_thrashing_min_active_delta') or 0))
        min_load_delta = max(0.0, float(queue_policy.get('anti_thrashing_min_load_delta') or 0.0))
        aging_enabled = bool(queue_policy.get('aging_enabled'))
        aging_after_s = max(0, int(queue_policy.get('aging_after_s') or 0))
        starvation_prevention_enabled = bool(queue_policy.get('starvation_prevention_enabled'))
        starvation_after_s = max(0, int(queue_policy.get('starvation_after_s') or 0))
        starvation_reserved_capacity_borrow_enabled = bool(queue_policy.get('starvation_reserved_capacity_borrow_enabled'))
        starvation_bypass_anti_thrashing = bool(queue_policy.get('starvation_bypass_anti_thrashing'))
        starvation_lease_capacity_borrow_enabled = bool(queue_policy.get('starvation_lease_capacity_borrow_enabled'))
        starvation_hold_capacity_borrow_enabled = bool(queue_policy.get('starvation_hold_capacity_borrow_enabled'))
        breach_prediction_enabled = bool(queue_policy.get('breach_prediction_enabled'))
        default_service_time_s = max(60, int(queue_policy.get('expected_service_time_s') or 300))
        expedite_enabled = bool(queue_policy.get('expedite_enabled'))
        expedite_threshold_s = max(0, int(queue_policy.get('expedite_threshold_s') or 0))
        expedite_min_risk_score = max(0.0, float(queue_policy.get('expedite_min_risk_score') or 0.0))
        expedite_reserved_capacity_borrow_enabled = bool(queue_policy.get('expedite_reserved_capacity_borrow_enabled'))
        expedite_lease_capacity_borrow_enabled = bool(queue_policy.get('expedite_lease_capacity_borrow_enabled'))
        expedite_hold_capacity_borrow_enabled = bool(queue_policy.get('expedite_hold_capacity_borrow_enabled'))
        expedite_bypass_anti_thrashing = bool(queue_policy.get('expedite_bypass_anti_thrashing'))
        predictive_forecasting_enabled = bool(queue_policy.get('predictive_forecasting_enabled'))
        forecast_window_s = max(300, int(queue_policy.get('forecast_window_s') or 1800))
        surge_load_ratio_threshold = max(0.25, float(queue_policy.get('surge_load_ratio_threshold') or 0.85))
        proactive_routing_enabled = bool(queue_policy.get('proactive_routing_enabled'))
        proactive_min_projected_load_delta = max(0.0, float(queue_policy.get('proactive_min_projected_load_delta') or 0.0))
        proactive_wait_buffer_s = max(0, int(queue_policy.get('proactive_wait_buffer_s') or 0))
        proactive_bypass_anti_thrashing = bool(queue_policy.get('proactive_bypass_anti_thrashing'))
        admission_control_enabled = bool(queue_policy.get('admission_control_enabled'))
        overload_governance_enabled = bool(queue_policy.get('overload_governance_enabled'))
        overload_projected_load_ratio_threshold = max(0.25, float(queue_policy.get('overload_projected_load_ratio_threshold') or queue_policy.get('surge_load_ratio_threshold') or 0.95))
        overload_projected_wait_time_threshold_s = max(0, int(queue_policy.get('overload_projected_wait_time_threshold_s') or max(300, default_service_time_s * 2)))
        admission_default_action = str(queue_policy.get('admission_default_action') or 'defer').strip().lower().replace('-', '_') or 'defer'
        overload_global_action = str(queue_policy.get('overload_global_action') or admission_default_action or 'defer').strip().lower().replace('-', '_') or 'defer'
        admission_exempt_severities = [str(item).strip().lower() for item in list(queue_policy.get('admission_exempt_severities') or []) if str(item).strip()]
        admission_exempt_queue_types = [str(item).strip() for item in list(queue_policy.get('admission_exempt_queue_types') or []) if str(item).strip()]
        admit_expedite_on_overload = bool(queue_policy.get('admit_expedite_on_overload', True))
        admit_starving_on_overload = bool(queue_policy.get('admit_starving_on_overload', True))
        queue_families_enabled = bool(queue_policy.get('queue_families_enabled'))
        multi_hop_hysteresis_enabled = bool(queue_policy.get('multi_hop_hysteresis_enabled', queue_families_enabled))
        family_reroute_cooldown_s = max(0, int(queue_policy.get('family_reroute_cooldown_s') or reroute_cooldown_s or 300))
        family_min_active_delta = max(0, int(queue_policy.get('family_min_active_delta') or min_active_delta or 1))
        family_min_load_delta = max(0.0, float(queue_policy.get('family_min_load_delta') or proactive_min_projected_load_delta or min_load_delta or 0.1))
        family_min_projected_wait_delta_s = max(0, int(queue_policy.get('family_min_projected_wait_delta_s') or proactive_wait_buffer_s or 120))
        family_recent_hops_threshold = max(1, int(queue_policy.get('family_recent_hops_threshold') or 2))
        family_history_limit = max(2, int(queue_policy.get('family_history_limit') or 8))
        expedite_bypass_family_hysteresis = bool(queue_policy.get('expedite_bypass_family_hysteresis', True))
        proactive_bypass_family_hysteresis = bool(queue_policy.get('proactive_bypass_family_hysteresis', True))
        starvation_bypass_family_hysteresis = bool(queue_policy.get('starvation_bypass_family_hysteresis', True))
        admission_bypass_family_hysteresis = bool(queue_policy.get('admission_bypass_family_hysteresis', True))
        alert_payload = dict(alert or {})
        alert_routing = dict(alert_payload.get('routing') or {})
        alert_route_history = [dict(item or {}) for item in list(alert_routing.get('route_history') or alert_payload.get('routing_history') or alert_payload.get('route_history') or []) if isinstance(item, dict)]
        if family_history_limit > 0:
            alert_route_history = alert_route_history[-family_history_limit:]
        now_ts = time.time()
        def _queue_family_id_for(queue_id: str, route: dict[str, Any] | None = None) -> str:
            metrics = dict(queues.get(str(queue_id or '').strip()) or {})
            payload = dict(route or {})
            return str(metrics.get('queue_family_id') or payload.get('queue_family_id') or metrics.get('queue_type') or payload.get('queue_type') or queue_policy.get('default_queue_family') or '').strip()
        history_cutoff_ts = now_ts - float(family_reroute_cooldown_s or 0) if family_reroute_cooldown_s > 0 else None
        recent_history = []
        for entry in alert_route_history:
            try:
                entry_ts = float(entry.get('at')) if entry.get('at') is not None else None
            except Exception:
                entry_ts = None
            if history_cutoff_ts is not None and entry_ts is not None and entry_ts < history_cutoff_ts:
                continue
            queue_id = str(entry.get('queue_id') or '').strip()
            if not queue_id:
                continue
            family_id = str(entry.get('queue_family_id') or _queue_family_id_for(queue_id) or '').strip()
            recent_history.append({'at': entry_ts, 'queue_id': queue_id, 'queue_family_id': family_id})
        if normalized_current_queue_id:
            current_family_id = _queue_family_id_for(normalized_current_queue_id)
        else:
            current_family_id = ''
        recent_queue_ids = [str(item.get('queue_id') or '') for item in recent_history if str(item.get('queue_id') or '')]
        recent_family_ids = [str(item.get('queue_family_id') or '') for item in recent_history if str(item.get('queue_family_id') or '')]
        recent_queue_hop_count = sum(1 for idx in range(1, len(recent_queue_ids)) if recent_queue_ids[idx] != recent_queue_ids[idx - 1])
        alert_severity = str(alert_payload.get('severity') or '').strip().lower()
        alert_created_at = None
        try:
            alert_created_at = float(alert_payload.get('created_at')) if alert_payload.get('created_at') is not None else None
        except Exception:
            alert_created_at = None
        alert_queue_updated_at = None
        try:
            alert_queue_updated_at = float(alert_routing.get('updated_at')) if alert_routing.get('updated_at') is not None else None
        except Exception:
            alert_queue_updated_at = None
        alert_wait_age_s = max(0, int(now_ts - (alert_created_at if alert_created_at is not None else (alert_queue_updated_at if alert_queue_updated_at is not None else now_ts))))
        aging_applied = bool(aging_enabled and aging_after_s > 0 and alert_wait_age_s >= aging_after_s)
        starving = bool(starvation_prevention_enabled and starvation_after_s > 0 and alert_wait_age_s >= starvation_after_s)
        sla_snapshot = dict(alert_payload.get('sla_state') or alert_payload.get('sla') or {})
        if alert_payload and bool((normalized_policy.get('sla_policy') or {}).get('enabled')):
            try:
                computed_sla = self._baseline_promotion_simulation_custody_sla_projection(alert_payload, normalized_policy, now_ts=now_ts)
            except Exception:
                computed_sla = {}
            if computed_sla:
                sla_snapshot = computed_sla
        def _extract_sla_target(snapshot: dict[str, Any]) -> tuple[str, int | None, str]:
            targets = dict(snapshot.get('targets') or {})
            candidate_items = []
            for name, raw_target in targets.items():
                target = dict(raw_target or {})
                if not bool(target.get('enabled')):
                    continue
                status = str(target.get('status') or '')
                if status in {'disabled', 'not_applicable', 'met'}:
                    continue
                remaining = target.get('remaining_s')
                try:
                    remaining_value = int(remaining) if remaining is not None else None
                except Exception:
                    remaining_value = None
                candidate_items.append((name, remaining_value, status))
            if not candidate_items:
                return '', None, str(snapshot.get('status') or '')
            name, remaining_value, status = sorted(candidate_items, key=lambda item: (0 if item[1] is not None and int(item[1]) < 0 else 1, float('inf') if item[1] is None else float(item[1]), str(item[0] or '')))[0]
            return str(name or ''), remaining_value, str(status or snapshot.get('status') or '')
        sla_target_name, time_to_breach_s, sla_target_status = _extract_sla_target(sla_snapshot)
        alert_at_risk = bool(expedite_enabled and time_to_breach_s is not None and ((expedite_threshold_s > 0 and time_to_breach_s <= expedite_threshold_s) or str(sla_snapshot.get('status') or '') in {'warning', 'breached'} or str(sla_target_status or '') in {'warning', 'breached'}))
        def _risk_level(score: float, predicted_breach: bool) -> str:
            if predicted_breach or score >= 1.0:
                return 'critical'
            if score >= 0.85:
                return 'high'
            if score >= 0.5:
                return 'medium'
            return 'low'
        def _annotate(route: dict[str, Any], *, reason: str, anti_thrashing_applied: bool = False, anti_thrashing_reason: str = '', starvation_prevention_applied: bool = False, starvation_prevention_reason: str = '', expedite_applied: bool = False, expedite_reason: str = '') -> dict[str, Any]:
            updated = dict(route or {})
            queue_metrics = dict(queues.get(str(updated.get('queue_id') or '').strip()) or {})
            base_active_count = int(queue_metrics.get('active_count') or 0)
            capacity = int(queue_metrics.get('capacity') or updated.get('queue_capacity') or 0)
            reserved_capacity = max(0, int(queue_metrics.get('reserved_capacity') or 0))
            leased_capacity = max(0, int(queue_metrics.get('leased_capacity') or 0))
            hold_capacity = max(0, int(queue_metrics.get('temporary_hold_capacity') or 0))
            general_capacity = max(0, int(queue_metrics.get('general_capacity') or max(0, capacity - reserved_capacity - leased_capacity - hold_capacity)))
            general_available = queue_metrics.get('general_available')
            reserved_available = queue_metrics.get('reserved_available')
            lease_available = queue_metrics.get('lease_available')
            hold_available = queue_metrics.get('temporary_hold_available')
            reservation_enabled = bool(queue_metrics.get('reservation_enabled'))
            lease_active = bool(queue_metrics.get('lease_active'))
            lease_expired = bool(queue_metrics.get('lease_expired'))
            route_queue_type = str(updated.get('queue_type') or queue_metrics.get('queue_type') or '').strip()
            route_queue_id = str(updated.get('queue_id') or queue_metrics.get('queue_id') or '').strip()
            route_queue_family_id = str(queue_metrics.get('queue_family_id') or updated.get('queue_family_id') or route_queue_type or queue_policy.get('default_queue_family') or '').strip()
            route_queue_family_label = str(queue_metrics.get('queue_family_label') or updated.get('queue_family_label') or route_queue_family_id or route_queue_type or '').strip()
            family_member_count = sum(1 for metrics in queues.values() if str(metrics.get('queue_family_id') or metrics.get('queue_type') or queue_policy.get('default_queue_family') or '').strip() == route_queue_family_id) if route_queue_family_id else 0
            family_history_queue_ids = [str(entry.get('queue_id') or '') for entry in recent_history if str(entry.get('queue_family_id') or '') == route_queue_family_id and str(entry.get('queue_id') or '')]
            recent_family_hop_count = sum(1 for idx in range(1, len(family_history_queue_ids)) if family_history_queue_ids[idx] != family_history_queue_ids[idx - 1])
            reserved_for_queue_types = [str(item).strip() for item in list(queue_metrics.get('reserved_for_queue_types') or []) if str(item).strip()]
            reserved_for_severities = [str(item).strip().lower() for item in list(queue_metrics.get('reserved_for_severities') or []) if str(item).strip()]
            leased_for_queue_types = [str(item).strip() for item in list(queue_metrics.get('leased_for_queue_types') or []) if str(item).strip()]
            leased_for_severities = [str(item).strip().lower() for item in list(queue_metrics.get('leased_for_severities') or []) if str(item).strip()]
            active_holds = [dict(item or {}) for item in list(queue_metrics.get('temporary_holds') or []) if isinstance(item, dict)]
            eligible_holds = []
            for hold in active_holds:
                hold_queue_types = [str(item).strip() for item in list(hold.get('for_queue_types') or []) if str(item).strip()]
                hold_severities = [str(item).strip().lower() for item in list(hold.get('for_severities') or []) if str(item).strip()]
                hold_type_match = (not hold_queue_types) or (route_queue_type and route_queue_type in hold_queue_types)
                hold_severity_match = (not hold_severities) or (alert_severity and alert_severity in hold_severities)
                if hold_type_match and hold_severity_match:
                    eligible_holds.append(hold)
            eligible_hold_capacity = max(0, sum(int(hold.get('capacity') or 0) for hold in eligible_holds))
            reservation_eligible = False
            if reservation_enabled:
                severity_match = (not reserved_for_severities) or (alert_severity and alert_severity in reserved_for_severities)
                type_match = (not reserved_for_queue_types) or (route_queue_type and route_queue_type in reserved_for_queue_types)
                reservation_eligible = bool(severity_match and type_match)
            lease_eligible = False
            if lease_active:
                lease_severity_match = (not leased_for_severities) or (alert_severity and alert_severity in leased_for_severities)
                lease_type_match = (not leased_for_queue_types) or (route_queue_type and route_queue_type in leased_for_queue_types)
                lease_eligible = bool(lease_severity_match and lease_type_match)
            temporary_hold_eligible = bool(eligible_holds and eligible_hold_capacity > 0)
            starvation_reserved_capacity_borrowed = bool(reservation_enabled and starving and starvation_reserved_capacity_borrow_enabled and (not reservation_eligible) and int(reserved_available or 0) > 0)
            starvation_lease_capacity_borrowed = bool(lease_active and starving and starvation_lease_capacity_borrow_enabled and (not lease_eligible) and int(lease_available or 0) > 0)
            starvation_temporary_hold_borrowed = bool(active_holds and starving and starvation_hold_capacity_borrow_enabled and (not temporary_hold_eligible) and int(hold_available or 0) > 0)
            expedite_reserved_capacity_borrowed = bool(reservation_enabled and expedite_enabled and alert_at_risk and expedite_reserved_capacity_borrow_enabled and (not reservation_eligible) and (not starvation_reserved_capacity_borrowed) and int(reserved_available or 0) > 0)
            expedite_lease_capacity_borrowed = bool(lease_active and expedite_enabled and alert_at_risk and expedite_lease_capacity_borrow_enabled and (not lease_eligible) and (not starvation_lease_capacity_borrowed) and int(lease_available or 0) > 0)
            expedite_temporary_hold_borrowed = bool(active_holds and expedite_enabled and alert_at_risk and expedite_hold_capacity_borrow_enabled and (not temporary_hold_eligible) and (not starvation_temporary_hold_borrowed) and int(hold_available or 0) > 0)
            projected_active_count = (base_active_count + 1) if str(updated.get('queue_id') or '').strip() else base_active_count
            effective_capacity = general_capacity
            if reservation_enabled and (reservation_eligible or starvation_reserved_capacity_borrowed or expedite_reserved_capacity_borrowed):
                effective_capacity += reserved_capacity
            if lease_active and (lease_eligible or starvation_lease_capacity_borrowed or expedite_lease_capacity_borrowed):
                effective_capacity += leased_capacity
            if active_holds and (temporary_hold_eligible or starvation_temporary_hold_borrowed or expedite_temporary_hold_borrowed):
                effective_capacity += hold_capacity if (starvation_temporary_hold_borrowed or expedite_temporary_hold_borrowed) else eligible_hold_capacity
            if effective_capacity <= 0 and not any([reservation_enabled, lease_active, active_holds]):
                effective_capacity = capacity
            if general_available is None:
                effective_available = (max(0, effective_capacity - base_active_count) if effective_capacity > 0 else None)
            else:
                effective_available = int(general_available or 0)
                if reservation_enabled and (reservation_eligible or starvation_reserved_capacity_borrowed or expedite_reserved_capacity_borrowed):
                    effective_available += int(reserved_available or 0)
                if lease_active and (lease_eligible or starvation_lease_capacity_borrowed or expedite_lease_capacity_borrowed):
                    effective_available += int(lease_available or 0)
                if active_holds and (temporary_hold_eligible or starvation_temporary_hold_borrowed or expedite_temporary_hold_borrowed):
                    effective_available += int(hold_available or 0) if (starvation_temporary_hold_borrowed or expedite_temporary_hold_borrowed) else min(int(hold_available or 0), eligible_hold_capacity)
            reservation_applied = bool(reservation_enabled and reservation_eligible and int(reserved_available or 0) > 0 and int(general_available or 0) <= 0 and capacity > 0)
            lease_applied = bool(lease_active and lease_eligible and int(lease_available or 0) > 0 and int(general_available or 0) <= 0 and capacity > 0)
            temporary_hold_applied = bool(active_holds and temporary_hold_eligible and int(hold_available or 0) > 0 and int(general_available or 0) <= 0 and capacity > 0)
            if starvation_reserved_capacity_borrowed and not starvation_prevention_applied:
                starvation_prevention_applied = True
                starvation_prevention_reason = 'borrow_reserved_capacity'
            elif starvation_lease_capacity_borrowed and not starvation_prevention_applied:
                starvation_prevention_applied = True
                starvation_prevention_reason = 'borrow_leased_capacity'
            elif starvation_temporary_hold_borrowed and not starvation_prevention_applied:
                starvation_prevention_applied = True
                starvation_prevention_reason = 'borrow_temporary_hold_capacity'
            current_projected_active_count = (base_active_count + 1) if str(updated.get('queue_id') or '').strip() else base_active_count
            projected_available = (max(0, effective_capacity - current_projected_active_count) if effective_capacity > 0 else None)
            current_queue_load_ratio = (float(current_projected_active_count) / float(effective_capacity) if effective_capacity > 0 else 0.0)
            service_time_s = max(60, int(queue_metrics.get('expected_service_time_s') or default_service_time_s or 300))
            route_forecast_window_s = max(300, int(queue_metrics.get('forecast_window_s') or forecast_window_s or 1800))
            forecast_arrivals_count = max(0, int(queue_metrics.get('forecast_arrivals_count') or queue_metrics.get('forecast_arrivals') or 0))
            try:
                forecast_arrivals_per_hour = max(0.0, float(queue_metrics.get('forecast_arrivals_per_hour') or 0.0))
            except Exception:
                forecast_arrivals_per_hour = 0.0
            if forecast_arrivals_count <= 0 and forecast_arrivals_per_hour > 0.0:
                forecast_arrivals_count = max(0, int(round(forecast_arrivals_per_hour * (float(route_forecast_window_s) / 3600.0))))
            forecast_departures_count = max(0, int((float(max(effective_capacity, 0)) * float(route_forecast_window_s)) / float(max(service_time_s, 1)))) if effective_capacity > 0 else 0
            projected_active_count = max(0, int(base_active_count + forecast_arrivals_count - forecast_departures_count + 1)) if effective_capacity > 0 else max(0, int(base_active_count + forecast_arrivals_count + 1))
            projected_load_ratio = (float(projected_active_count) / float(effective_capacity) if effective_capacity > 0 else 0.0)
            projected_wait_time_s = int(round((float(max(projected_active_count - 1, 0)) * float(service_time_s)) / float(max(effective_capacity, 1)))) if effective_capacity > 0 else int(round(float(base_active_count + forecast_arrivals_count) * float(service_time_s)))
            forecasted_over_capacity = bool(effective_capacity > 0 and projected_active_count > effective_capacity)
            surge_predicted = bool(predictive_forecasting_enabled and (forecasted_over_capacity or projected_load_ratio >= surge_load_ratio_threshold))
            predicted_wait_time_s = None
            if breach_prediction_enabled and time_to_breach_s is not None and effective_capacity > 0:
                predicted_wait_time_s = int(round(float(service_time_s) * float(max(base_active_count, 0)) / float(max(effective_capacity, 1))))
            elif breach_prediction_enabled and time_to_breach_s is not None:
                predicted_wait_time_s = int(round(float(service_time_s) * float(max(base_active_count, 0))))
            predicted_sla_margin_s = None
            predicted_sla_breach = False
            breach_risk_score = 0.0
            if time_to_breach_s is not None:
                if predicted_wait_time_s is not None:
                    predicted_sla_margin_s = int(time_to_breach_s - predicted_wait_time_s)
                    predicted_sla_breach = bool(predicted_sla_margin_s < 0)
                    denominator = max(float(abs(time_to_breach_s) if time_to_breach_s != 0 else 1.0), 1.0)
                    breach_risk_score = max(0.0, float(predicted_wait_time_s) / denominator)
                elif time_to_breach_s <= 0:
                    predicted_sla_breach = True
                    predicted_sla_margin_s = int(time_to_breach_s)
                    breach_risk_score = 1.0
            breach_risk_level = _risk_level(breach_risk_score, predicted_sla_breach)
            expedite_eligible = bool(expedite_enabled and time_to_breach_s is not None and (alert_at_risk or predicted_sla_breach or breach_risk_score >= expedite_min_risk_score))
            proactive_routing_eligible = bool(proactive_routing_enabled and predictive_forecasting_enabled and surge_predicted)
            route_admission_control_enabled = bool(queue_metrics.get('admission_control_enabled', admission_control_enabled))
            route_overload_governance_enabled = bool(queue_metrics.get('overload_governance_enabled', overload_governance_enabled))
            route_overload_projected_load_ratio_threshold = max(0.25, float(queue_metrics.get('overload_projected_load_ratio_threshold') or overload_projected_load_ratio_threshold or surge_load_ratio_threshold))
            route_overload_projected_wait_time_threshold_s = max(0, int(queue_metrics.get('overload_projected_wait_time_threshold_s') or overload_projected_wait_time_threshold_s or max(300, service_time_s * 2)))
            route_admission_action = str(queue_metrics.get('admission_action') or updated.get('admission_action') or admission_default_action or 'defer').strip().lower().replace('-', '_') or 'defer'
            route_overload_action = str(queue_metrics.get('overload_action') or updated.get('overload_action') or overload_global_action or route_admission_action or 'defer').strip().lower().replace('-', '_') or 'defer'
            route_admission_exempt_severities = [str(item).strip().lower() for item in list(queue_metrics.get('admission_exempt_severities') or admission_exempt_severities or []) if str(item).strip()]
            route_admission_exempt_queue_types = [str(item).strip() for item in list(queue_metrics.get('admission_exempt_queue_types') or admission_exempt_queue_types or []) if str(item).strip()]
            overload_predicted = bool(
                (effective_capacity > 0 and current_projected_active_count >= effective_capacity and bool(queue_metrics.get('hard_limit')))
                or forecasted_over_capacity
                or projected_load_ratio >= route_overload_projected_load_ratio_threshold
                or (route_overload_projected_wait_time_threshold_s > 0 and projected_wait_time_s >= route_overload_projected_wait_time_threshold_s)
            )
            overload_reasons = []
            if effective_capacity > 0 and current_projected_active_count >= effective_capacity and bool(queue_metrics.get('hard_limit')):
                overload_reasons.append('hard_limit_capacity')
            if forecasted_over_capacity:
                overload_reasons.append('forecasted_over_capacity')
            if projected_load_ratio >= route_overload_projected_load_ratio_threshold:
                overload_reasons.append('projected_load_threshold')
            if route_overload_projected_wait_time_threshold_s > 0 and projected_wait_time_s >= route_overload_projected_wait_time_threshold_s:
                overload_reasons.append('projected_wait_threshold')
            admission_exempt = bool(
                (alert_severity and alert_severity in route_admission_exempt_severities)
                or (route_queue_type and route_queue_type in route_admission_exempt_queue_types)
                or (expedite_eligible and admit_expedite_on_overload)
                or (starving and admit_starving_on_overload)
            )
            if expedite_eligible and admit_expedite_on_overload:
                admission_exempt_reason = 'expedite'
            elif starving and admit_starving_on_overload:
                admission_exempt_reason = 'starvation'
            elif alert_severity and alert_severity in route_admission_exempt_severities:
                admission_exempt_reason = 'severity_exempt'
            elif route_queue_type and route_queue_type in route_admission_exempt_queue_types:
                admission_exempt_reason = 'queue_type_exempt'
            else:
                admission_exempt_reason = ''
            admission_decision = 'admit'
            admission_blocked = False
            overload_governance_applied = False
            admission_reason = ''
            overload_reason = ','.join(overload_reasons)
            if route_admission_control_enabled and route_overload_governance_enabled and overload_predicted:
                overload_governance_applied = True
                if admission_exempt:
                    admission_decision = 'admit'
                    admission_reason = f'admit_exempt:{admission_exempt_reason}' if admission_exempt_reason else 'admit_exempt'
                else:
                    admission_decision = route_overload_action if route_overload_action in {'defer', 'manual_gate', 'park', 'reject', 'admit'} else route_admission_action
                    admission_blocked = admission_decision in {'defer', 'manual_gate', 'park', 'reject'}
                    admission_reason = overload_reason or 'overload_predicted'
            updated.update({
                'load_aware': bool(queue_metrics), 'selection_reason': reason, 'queue_active_count': current_projected_active_count, 'queue_capacity': capacity, 'queue_available': projected_available, 'queue_load_ratio': current_queue_load_ratio, 'queue_at_capacity': bool(effective_capacity > 0 and current_projected_active_count >= effective_capacity), 'queue_over_capacity': bool(effective_capacity > 0 and current_projected_active_count > effective_capacity), 'queue_warning': bool(capacity > 0 and current_projected_active_count >= max(1, int(queue_metrics.get('warning_capacity') or max(0, capacity - 1)))), 'team_queue_id': str(queue_metrics.get('queue_id') or updated.get('queue_id') or ''), 'reservation_enabled': reservation_enabled, 'reserved_capacity': reserved_capacity, 'general_capacity': general_capacity, 'general_available': general_available, 'reserved_available': reserved_available, 'reservation_eligible': reservation_eligible, 'reservation_applied': reservation_applied, 'lease_active': lease_active, 'lease_expired': lease_expired, 'leased_capacity': leased_capacity, 'lease_available': lease_available, 'lease_expires_at': queue_metrics.get('lease_expires_at'), 'lease_reason': str(queue_metrics.get('lease_reason') or ''), 'lease_holder': str(queue_metrics.get('lease_holder') or ''), 'lease_id': str(queue_metrics.get('lease_id') or ''), 'lease_eligible': lease_eligible, 'lease_applied': lease_applied, 'starvation_lease_capacity_borrowed': starvation_lease_capacity_borrowed, 'expedite_lease_capacity_borrowed': expedite_lease_capacity_borrowed, 'temporary_hold_count': int(queue_metrics.get('temporary_hold_count') or 0), 'temporary_hold_capacity': hold_capacity, 'temporary_hold_available': hold_available, 'temporary_hold_ids': list(queue_metrics.get('temporary_hold_ids') or []), 'temporary_hold_reasons': list(queue_metrics.get('temporary_hold_reasons') or []), 'temporary_hold_eligible': temporary_hold_eligible, 'temporary_hold_applied': temporary_hold_applied, 'starvation_temporary_hold_borrowed': starvation_temporary_hold_borrowed, 'expedite_temporary_hold_borrowed': expedite_temporary_hold_borrowed, 'expired_temporary_hold_count': int(queue_metrics.get('expired_temporary_hold_count') or 0), 'expired_temporary_hold_ids': list(queue_metrics.get('expired_temporary_hold_ids') or []), 'effective_capacity': effective_capacity, 'alert_wait_age_s': alert_wait_age_s, 'aging_applied': aging_applied, 'starving': starving, 'queue_oldest_alert_age_s': int(queue_metrics.get('oldest_alert_age_s') or 0), 'queue_aged_alert_count': int(queue_metrics.get('aged_alert_count') or 0), 'queue_starving_alert_count': int(queue_metrics.get('starving_alert_count') or 0), 'starvation_reserved_capacity_borrowed': starvation_reserved_capacity_borrowed, 'starvation_prevention_applied': starvation_prevention_applied, 'starvation_prevention_reason': str(starvation_prevention_reason or ''), 'anti_thrashing_applied': anti_thrashing_applied, 'anti_thrashing_reason': str(anti_thrashing_reason or ''), 'queue_family_id': route_queue_family_id, 'queue_family_label': route_queue_family_label, 'queue_family_enabled': bool(queue_families_enabled and route_queue_family_id), 'queue_family_member_count': family_member_count, 'recent_queue_hop_count': recent_queue_hop_count, 'recent_family_hop_count': recent_family_hop_count, 'family_hysteresis_applied': bool(updated.get('family_hysteresis_applied', False)), 'family_hysteresis_reason': str(updated.get('family_hysteresis_reason') or ''), 'route_history_queue_ids': recent_queue_ids[-family_history_limit:], 'route_history_family_ids': recent_family_ids[-family_history_limit:], 'sla_deadline_target': str(sla_target_name or ''), 'time_to_breach_s': time_to_breach_s, 'predicted_wait_time_s': predicted_wait_time_s, 'predicted_sla_margin_s': predicted_sla_margin_s, 'predicted_sla_breach': predicted_sla_breach, 'breach_risk_score': float(round(breach_risk_score, 4)), 'breach_risk_level': breach_risk_level, 'expected_service_time_s': service_time_s, 'forecast_window_s': route_forecast_window_s, 'forecast_arrivals_count': forecast_arrivals_count, 'forecast_departures_count': forecast_departures_count, 'projected_active_count': projected_active_count, 'projected_load_ratio': float(round(projected_load_ratio, 4)), 'projected_wait_time_s': projected_wait_time_s, 'forecasted_over_capacity': forecasted_over_capacity, 'surge_predicted': surge_predicted, 'proactive_routing_eligible': proactive_routing_eligible, 'proactive_routing_applied': bool(updated.get('proactive_routing_applied', False)), 'proactive_reason': str(updated.get('proactive_reason') or ''), 'expedite_eligible': expedite_eligible, 'expedite_reserved_capacity_borrowed': expedite_reserved_capacity_borrowed, 'expedite_applied': expedite_applied, 'expedite_reason': str(expedite_reason or ''), 'admission_control_enabled': route_admission_control_enabled, 'admission_action': route_admission_action, 'admission_exempt_severities': route_admission_exempt_severities, 'admission_exempt_queue_types': route_admission_exempt_queue_types, 'admission_exempt': admission_exempt, 'admission_exempt_reason': admission_exempt_reason, 'admission_decision': admission_decision, 'admission_blocked': admission_blocked, 'admission_reason': admission_reason, 'admission_review_required': admission_decision == 'manual_gate', 'overload_governance_enabled': route_overload_governance_enabled, 'overload_governance_applied': overload_governance_applied, 'overload_action': route_overload_action, 'overload_projected_load_ratio_threshold': route_overload_projected_load_ratio_threshold, 'overload_projected_wait_time_threshold_s': route_overload_projected_wait_time_threshold_s, 'overload_predicted': overload_predicted, 'overload_reason': overload_reason, '_base_active_count': base_active_count, '_effective_available': effective_available,
            })
            return updated
        if not bool((queue_state or {}).get('queues')) or not prefer_lowest_load:
            baseline = sorted(candidates, key=lambda item: (int(item.get('min_escalation_level') or 0), -int(item.get('_route_index') or 0)), reverse=True)[0]
            return _annotate(baseline, reason='policy_order')
        annotated = [_annotate(item, reason='candidate') for item in candidates]
        expedite_candidates = [item for item in annotated if bool(item.get('expedite_eligible'))]
        unblocked_expedite_candidates = [item for item in expedite_candidates if not bool(item.get('admission_blocked'))]
        def _score(route: dict[str, Any]) -> tuple[Any, ...]:
            queue_id = str(route.get('queue_id') or '').strip()
            if not queue_id:
                return (2, 2, float('inf'), float('inf'), float('inf'), float('inf'), int(route.get('_route_index') or 0))
            effective_available = route.get('_effective_available')
            effective_available_value = int(effective_available or 0) if effective_available is not None else 0
            hard_limit = bool(route.get('queue_hard_limit') or (queues.get(queue_id) or {}).get('hard_limit'))
            capacity_blocked = bool(route.get('effective_capacity') and int(route.get('queue_active_count') or 0) > int(route.get('effective_capacity') or 0))
            saturation_blocked = bool(route.get('effective_capacity') and int(route.get('queue_active_count') or 0) >= int(route.get('effective_capacity') or 0))
            hard_rank = 1 if hard_limit and saturation_blocked else 0
            availability_rank = 1 if effective_available is not None and effective_available_value <= 0 else 0
            admission_rank = 1 if bool(route.get('admission_blocked')) else 0
            return (admission_rank, hard_rank, availability_rank, int(route.get('queue_starving_alert_count') or 0), float(route.get('queue_oldest_alert_age_s') or 0.0), int(route.get('_base_active_count') or 0), float(route.get('queue_load_ratio') or 0.0), 0 if not capacity_blocked else 1, int(route.get('_route_index') or 0))
        def _proactive_score(route: dict[str, Any]) -> tuple[Any, ...]:
            queue_id = str(route.get('queue_id') or '').strip()
            if not queue_id:
                return (2, 2, float('inf'), float('inf'), float('inf'), int(route.get('_route_index') or 0))
            hard_limit = bool(route.get('queue_hard_limit') or (queues.get(queue_id) or {}).get('hard_limit'))
            projected_over_capacity_rank = 1 if bool(route.get('forecasted_over_capacity')) else 0
            surge_rank = 1 if bool(route.get('surge_predicted')) else 0
            projected_wait = float(route.get('projected_wait_time_s') if route.get('projected_wait_time_s') is not None else float('inf'))
            projected_load = float(route.get('projected_load_ratio') or 0.0)
            hard_rank = 1 if hard_limit and projected_over_capacity_rank else 0
            admission_rank = 1 if bool(route.get('admission_blocked')) else 0
            return (admission_rank, hard_rank, projected_over_capacity_rank, surge_rank, projected_wait, projected_load, int(route.get('_route_index') or 0))
        if unblocked_expedite_candidates:
            best = sorted(unblocked_expedite_candidates, key=lambda route: (0 if not bool(route.get('predicted_sla_breach')) else 1, -float(route.get('predicted_sla_margin_s') if route.get('predicted_sla_margin_s') is not None else -10**9), float(route.get('predicted_wait_time_s') if route.get('predicted_wait_time_s') is not None else float('inf')), int(route.get('_base_active_count') or 0), float(route.get('queue_load_ratio') or 0.0), int(route.get('_route_index') or 0)))[0]
        elif expedite_candidates:
            best = sorted(expedite_candidates, key=lambda route: (0 if not bool(route.get('predicted_sla_breach')) else 1, -float(route.get('predicted_sla_margin_s') if route.get('predicted_sla_margin_s') is not None else -10**9), float(route.get('predicted_wait_time_s') if route.get('predicted_wait_time_s') is not None else float('inf')), int(route.get('_base_active_count') or 0), float(route.get('queue_load_ratio') or 0.0), int(route.get('_route_index') or 0)))[0]
        else:
            baseline_best = sorted(annotated, key=_score)[0]
            if proactive_routing_enabled and predictive_forecasting_enabled:
                proactive_best = sorted(annotated, key=_proactive_score)[0]
                baseline_projected_load = float(baseline_best.get('projected_load_ratio') or 0.0)
                proactive_projected_load = float(proactive_best.get('projected_load_ratio') or 0.0)
                baseline_projected_wait = int(baseline_best.get('projected_wait_time_s') or 0)
                proactive_projected_wait = int(proactive_best.get('projected_wait_time_s') or 0)
                proactive_improves = bool(
                    str(proactive_best.get('queue_id') or '') != str(baseline_best.get('queue_id') or '') and (
                        (bool(baseline_best.get('surge_predicted')) and not bool(proactive_best.get('surge_predicted'))) or
                        (baseline_projected_load - proactive_projected_load) >= proactive_min_projected_load_delta or
                        (baseline_projected_wait - proactive_projected_wait) >= proactive_wait_buffer_s
                    )
                )
                if proactive_improves:
                    proactive_best = dict(proactive_best)
                    proactive_best['proactive_routing_applied'] = True
                    proactive_best['proactive_reason'] = 'avoid_forecasted_surge' if bool(baseline_best.get('surge_predicted')) and not bool(proactive_best.get('surge_predicted')) else 'lower_projected_wait'
                    best = proactive_best
                else:
                    best = baseline_best
            else:
                best = baseline_best
        queue_id = str(best.get('queue_id') or '').strip(); metrics = dict(queues.get(queue_id) or {}) if queue_id else {}
        reason = 'lowest_load_queue'
        if best.get('expedite_temporary_hold_borrowed'): reason = 'expedite_temporary_hold_queue'
        elif best.get('expedite_lease_capacity_borrowed'): reason = 'expedite_leased_capacity_queue'
        elif best.get('expedite_reserved_capacity_borrowed'): reason = 'expedite_reserved_capacity_queue'
        elif best.get('starvation_temporary_hold_borrowed'): reason = 'starvation_temporary_hold_queue'
        elif best.get('starvation_lease_capacity_borrowed'): reason = 'starvation_leased_capacity_queue'
        elif best.get('starvation_reserved_capacity_borrowed'): reason = 'starvation_reserved_capacity_queue'
        elif bool(best.get('expedite_eligible')): reason = 'expedite_predicted_breach_queue' if bool(best.get('predicted_sla_breach')) else 'expedite_deadline_queue'
        elif bool(best.get('proactive_routing_applied')) and bool(best.get('surge_predicted')): reason = 'proactive_surge_avoidance_queue'
        elif bool(best.get('proactive_routing_applied')): reason = 'proactive_forecast_queue'
        elif best.get('temporary_hold_applied'): reason = 'temporary_hold_queue'
        elif best.get('lease_applied'): reason = 'leased_capacity_queue'
        elif best.get('reservation_applied'): reason = 'reserved_capacity_queue'
        elif bool(best.get('admission_blocked')) and str(best.get('admission_decision') or '') == 'manual_gate': reason = 'overload_manual_gate_queue'
        elif bool(best.get('admission_blocked')) and str(best.get('admission_decision') or '') == 'park': reason = 'overload_park_queue'
        elif bool(best.get('admission_blocked')) and str(best.get('admission_decision') or '') == 'reject': reason = 'overload_reject_queue'
        elif bool(best.get('admission_blocked')): reason = 'overload_defer_queue'
        elif queue_id and int(best.get('queue_starving_alert_count') or 0) > 0: reason = 'avoid_starving_queue'
        elif queue_id and int(best.get('_base_active_count') or 0) == 0: reason = 'empty_queue'
        elif queue_id and bool(best.get('queue_at_capacity')): reason = 'least_loaded_available_queue' if not bool(metrics.get('hard_limit')) else 'least_loaded_hard_limit_queue'
        anti_thrashing_bypassed = False; expedite_bypass_applied = False; proactive_bypass_applied = False; overload_bypass_applied = False
        if anti_thrashing_enabled and normalized_current_queue_id:
            current = next((item for item in annotated if str(item.get('queue_id') or '').strip() == normalized_current_queue_id), None)
            if current and str(current.get('queue_id') or '') != str(best.get('queue_id') or ''):
                try: last_updated_at = float(alert_routing.get('updated_at')) if alert_routing.get('updated_at') is not None else None
                except Exception: last_updated_at = None
                within_cooldown = bool(last_updated_at is not None and reroute_cooldown_s > 0 and (now_ts - last_updated_at) < reroute_cooldown_s)
                active_delta = max(0, int(current.get('_base_active_count') or 0) - int(best.get('_base_active_count') or 0))
                load_delta = max(0.0, float(current.get('queue_load_ratio') or 0.0) - float(best.get('queue_load_ratio') or 0.0))
                current_predicted_breach = bool(current.get('predicted_sla_breach')); best_predicted_breach = bool(best.get('predicted_sla_breach')); current_risk = float(current.get('breach_risk_score') or 0.0); best_risk = float(best.get('breach_risk_score') or 0.0)
                if within_cooldown and active_delta <= min_active_delta and load_delta <= min_load_delta:
                    if bool(current.get('admission_blocked')) and not bool(best.get('admission_blocked')):
                        anti_thrashing_bypassed = True; overload_bypass_applied = True
                    elif starving and starvation_bypass_anti_thrashing: anti_thrashing_bypassed = True
                    elif bool(best.get('expedite_eligible')) and expedite_bypass_anti_thrashing and ((current_predicted_breach and not best_predicted_breach) or (best_risk + 0.1) < current_risk): anti_thrashing_bypassed = True; expedite_bypass_applied = True
                    elif bool(best.get('proactive_routing_applied')) and proactive_bypass_anti_thrashing and ((bool(current.get('surge_predicted')) and not bool(best.get('surge_predicted'))) or (float(current.get('projected_load_ratio') or 0.0) - float(best.get('projected_load_ratio') or 0.0)) >= proactive_min_projected_load_delta or (int(current.get('projected_wait_time_s') or 0) - int(best.get('projected_wait_time_s') or 0)) >= proactive_wait_buffer_s): anti_thrashing_bypassed = True; proactive_bypass_applied = True
                    else:
                        current_reason = 'anti_thrashing_keep_current_queue'
                        if current.get('temporary_hold_applied'):
                            current_reason = 'anti_thrashing_keep_temporary_hold_queue'
                        elif current.get('lease_applied'):
                            current_reason = 'anti_thrashing_keep_leased_queue'
                        elif current.get('reservation_applied'):
                            current_reason = 'anti_thrashing_keep_reserved_queue'
                        return _annotate(current, reason=current_reason, anti_thrashing_applied=True, anti_thrashing_reason='reroute_cooldown_min_delta')
        if anti_thrashing_bypassed:
            if expedite_bypass_applied:
                reason = 'expedite_bypass_anti_thrashing'
            elif proactive_bypass_applied:
                reason = 'proactive_bypass_anti_thrashing'
            elif overload_bypass_applied:
                reason = 'admission_bypass_anti_thrashing'
            else:
                reason = 'starvation_bypass_anti_thrashing'
        family_hysteresis_bypassed = False
        family_hysteresis_reason = ''
        family_expedite_bypass = False
        family_proactive_bypass = False
        family_starvation_bypass = False
        family_admission_bypass = False
        if multi_hop_hysteresis_enabled and queue_families_enabled and normalized_current_queue_id:
            current_family_candidate = next((item for item in annotated if str(item.get('queue_id') or '').strip() == normalized_current_queue_id), None)
            if current_family_candidate and str(current_family_candidate.get('queue_id') or '') != str(best.get('queue_id') or ''):
                current_family = str(current_family_candidate.get('queue_family_id') or _queue_family_id_for(str(current_family_candidate.get('queue_id') or ''), current_family_candidate) or '')
                best_family = str(best.get('queue_family_id') or _queue_family_id_for(str(best.get('queue_id') or ''), best) or '')
                same_family = bool(current_family and best_family and current_family == best_family)
                same_family_history_queue_ids = [str(item.get('queue_id') or '') for item in recent_history if str(item.get('queue_family_id') or '') == current_family and str(item.get('queue_id') or '')]
                same_family_hops = sum(1 for idx in range(1, len(same_family_history_queue_ids)) if same_family_history_queue_ids[idx] != same_family_history_queue_ids[idx - 1])
                recent_return_to_best = bool(str(best.get('queue_id') or '') and str(best.get('queue_id') or '') in same_family_history_queue_ids[:-1])
                family_active_delta = max(0, int(current_family_candidate.get('_base_active_count') or 0) - int(best.get('_base_active_count') or 0))
                family_load_delta = max(0.0, float(current_family_candidate.get('projected_load_ratio') or current_family_candidate.get('queue_load_ratio') or 0.0) - float(best.get('projected_load_ratio') or best.get('queue_load_ratio') or 0.0))
                family_wait_delta = max(0, int(current_family_candidate.get('projected_wait_time_s') or 0) - int(best.get('projected_wait_time_s') or 0))
                family_pressure = bool(same_family and (same_family_hops >= family_recent_hops_threshold or recent_return_to_best or recent_queue_hop_count >= family_recent_hops_threshold + 1))
                family_improvement_small = bool(family_active_delta <= family_min_active_delta and family_load_delta <= family_min_load_delta and family_wait_delta <= family_min_projected_wait_delta_s)
                if family_pressure and family_improvement_small:
                    if bool(current_family_candidate.get('admission_blocked')) and not bool(best.get('admission_blocked')) and admission_bypass_family_hysteresis:
                        family_hysteresis_bypassed = True; family_admission_bypass = True; family_hysteresis_reason = 'bypass_admission_blocked_queue'
                    elif starving and starvation_bypass_family_hysteresis:
                        family_hysteresis_bypassed = True; family_starvation_bypass = True; family_hysteresis_reason = 'bypass_starving_alert'
                    elif bool(best.get('expedite_eligible')) and expedite_bypass_family_hysteresis:
                        family_hysteresis_bypassed = True; family_expedite_bypass = True; family_hysteresis_reason = 'bypass_expedite_alert'
                    elif bool(best.get('proactive_routing_applied')) and proactive_bypass_family_hysteresis:
                        family_hysteresis_bypassed = True; family_proactive_bypass = True; family_hysteresis_reason = 'bypass_proactive_routing'
                    else:
                        kept = _annotate(current_family_candidate, reason='family_hysteresis_keep_current_queue')
                        kept['family_hysteresis_applied'] = True
                        kept['family_hysteresis_reason'] = 'recent_same_family_multi_hop'
                        return kept
        if family_hysteresis_bypassed and not anti_thrashing_bypassed:
            if family_expedite_bypass:
                reason = 'expedite_bypass_family_hysteresis'
            elif family_proactive_bypass:
                reason = 'proactive_bypass_family_hysteresis'
            elif family_admission_bypass:
                reason = 'admission_bypass_family_hysteresis'
            else:
                reason = 'starvation_bypass_family_hysteresis'
        starvation_applied = bool(best.get('starvation_reserved_capacity_borrowed') or best.get('starvation_lease_capacity_borrowed') or best.get('starvation_temporary_hold_borrowed') or (anti_thrashing_bypassed and not expedite_bypass_applied and not proactive_bypass_applied and not overload_bypass_applied))
        if best.get('starvation_temporary_hold_borrowed'):
            starvation_reason = 'borrow_temporary_hold_capacity'
        elif best.get('starvation_lease_capacity_borrowed'):
            starvation_reason = 'borrow_leased_capacity'
        elif best.get('starvation_reserved_capacity_borrowed'):
            starvation_reason = 'borrow_reserved_capacity'
        elif anti_thrashing_bypassed and not expedite_bypass_applied and not proactive_bypass_applied and not overload_bypass_applied:
            starvation_reason = 'bypass_anti_thrashing'
        else:
            starvation_reason = ''
        if best.get('expedite_temporary_hold_borrowed'):
            expedite_reason_value = 'borrow_temporary_hold_capacity'
        elif best.get('expedite_lease_capacity_borrowed'):
            expedite_reason_value = 'borrow_leased_capacity'
        elif best.get('expedite_reserved_capacity_borrowed'):
            expedite_reason_value = 'borrow_reserved_capacity'
        elif expedite_bypass_applied:
            expedite_reason_value = 'bypass_anti_thrashing'
        elif proactive_bypass_applied:
            expedite_reason_value = ''
        elif best.get('predicted_sla_breach'):
            expedite_reason_value = 'predicted_breach'
        elif best.get('expedite_eligible'):
            expedite_reason_value = 'deadline_threshold'
        else:
            expedite_reason_value = ''
        annotated_best = _annotate(best, reason=reason, starvation_prevention_applied=starvation_applied, starvation_prevention_reason=starvation_reason, expedite_applied=bool(best.get('expedite_eligible')), expedite_reason=expedite_reason_value)
        if family_hysteresis_bypassed:
            annotated_best['family_hysteresis_applied'] = False
            annotated_best['family_hysteresis_reason'] = family_hysteresis_reason
        if bool(best.get('proactive_routing_applied')):
            annotated_best['proactive_routing_applied'] = True
            annotated_best['proactive_reason'] = 'bypass_anti_thrashing' if proactive_bypass_applied else str(best.get('proactive_reason') or ('avoid_forecasted_surge' if bool(best.get('surge_predicted')) else 'lower_projected_wait'))
        return annotated_best

    def _apply_baseline_promotion_simulation_custody_monitoring(self, gw, *, release: dict[str, Any], reconciliation: dict[str, Any], actor: str) -> dict[str, Any]:
        policy = self._baseline_promotion_simulation_custody_monitoring_policy_for_release(release)
        metadata = dict((release or {}).get('metadata') or {})
        promotion = dict(metadata.get('baseline_promotion') or {})
        alerts = [dict(item) for item in list(promotion.get('simulation_custody_alerts') or [])]
        summary = dict((reconciliation or {}).get('summary') or {})
        drifted = str(summary.get('overall_status') or '') == 'drifted'
        now_ts = time.time()
        active_alert = next((item for item in alerts if bool(item.get('active'))), None)
        queue_state = self._baseline_promotion_simulation_custody_queue_capacity_state(
            gw,
            release=release,
            policy=policy,
        )
        new_alert = None
        if bool(policy.get('enabled')) and drifted and bool(policy.get('notify_on_drift')) and active_alert is None:
            latest_closed = next((item for item in alerts if not bool(item.get('active'))), None)
            dedupe_window_s = max(0, int(policy.get('dedupe_window_s') or 0))
            within_dedupe_window = False
            if latest_closed is not None and dedupe_window_s > 0:
                closed_at = latest_closed.get('recovered_at') or latest_closed.get('resolved_at') or latest_closed.get('cleared_at')
                try:
                    within_dedupe_window = closed_at is not None and (now_ts - float(closed_at)) <= float(dedupe_window_s)
                except Exception:
                    within_dedupe_window = False
            preview_alert = {
                'severity': str(policy.get('severity') or 'warning'),
                'escalation_level': 0,
            }
            route = self._baseline_promotion_simulation_custody_route_for_alert(policy, preview_alert, queue_state=queue_state)
            target_path = str(route.get('target_path') or policy.get('target_path') or '/ui/?tab=operator')
            notification = {}
            if not within_dedupe_window:
                notification = gw.audit.create_app_notification(
                    category='operator',
                    title='Baseline simulation custody drift detected',
                    body=f"Custody drift detected for baseline promotion {str(release.get('release_id') or '').strip()}.",
                    target_path=target_path,
                    created_by=str(actor or 'system'),
                    metadata={
                        'kind': 'baseline_promotion_simulation_custody_drift',
                        'promotion_id': str(release.get('release_id') or ''),
                        'reconciliation_id': str(reconciliation.get('reconciliation_id') or ''),
                        'drifted_count': int(summary.get('drifted_count') or 0),
                        'severity': str(policy.get('severity') or 'warning'),
                        'route_id': str(route.get('route_id') or ''),
                        'queue_id': str(route.get('queue_id') or ''),
                        'owner_role': str(route.get('owner_role') or ''),
                    },
                    tenant_id=release.get('tenant_id'),
                    workspace_id=release.get('workspace_id'),
                    environment=release.get('environment'),
                )
            new_alert = {
                'alert_id': self._stable_digest({'promotion_id': str(release.get('release_id') or ''), 'reconciliation_id': str(reconciliation.get('reconciliation_id') or ''), 'kind': 'drift'})[:24],
                'kind': 'drift',
                'active': True,
                'status': 'open',
                'created_at': now_ts,
                'created_by': str(actor or 'system'),
                'notification_id': str((notification or {}).get('notification_id') or ''),
                'last_notification_id': str((notification or {}).get('notification_id') or ''),
                'last_notification_at': (None if within_dedupe_window else now_ts),
                'notification_suppressed': within_dedupe_window,
                'reconciliation_id': str(reconciliation.get('reconciliation_id') or ''),
                'severity': str(policy.get('severity') or 'warning'),
                'escalation_level': 0,
                'escalation_count': 0,
                'escalations': [],
                'suppression_state': {
                    'suppressed': bool(within_dedupe_window),
                    'reasons': (['dedupe_window'] if within_dedupe_window else []),
                    'evaluated_at': now_ts,
                    'window_until': None,
                    'last_notification_at': (None if within_dedupe_window else now_ts),
                },
                'summary': {
                    'overall_status': str(summary.get('overall_status') or ''),
                    'drifted_count': int(summary.get('drifted_count') or 0),
                    'latest_package_id': str(summary.get('latest_package_id') or ''),
                },
                'ownership': {},
                'routing': {},
                'handoffs': [],
                'handoff_count': 0,
                'sla_state': {},
                'sla_notifications': [],
            }
            new_alert, routed = self._apply_baseline_promotion_simulation_custody_route_to_alert(
                new_alert,
                route=route,
                actor=actor,
                auto_assign=bool(policy.get('auto_assign_owner')),
                preserve_owner=False,
                source='default_route',
                manual_override=False,
            )
            alerts.append(new_alert)
            promotion = self._append_baseline_promotion_timeline_event(
                promotion,
                kind='monitoring',
                label='baseline_promotion_simulation_custody_drift_alerted',
                actor=str(actor or 'system'),
                reconciliation_id=str(reconciliation.get('reconciliation_id') or ''),
                drifted_count=int(summary.get('drifted_count') or 0),
                notification_id=str((notification or {}).get('notification_id') or ''),
                notification_suppressed=within_dedupe_window,
                route_id=str((new_alert.get('routing') or {}).get('route_id') or ''),
                queue_id=str((new_alert.get('routing') or {}).get('queue_id') or ''),
                owner_role=str((new_alert.get('routing') or {}).get('owner_role') or ''),
            )
            if routed:
                promotion = self._append_baseline_promotion_timeline_event(
                    promotion,
                    kind='monitoring',
                    label='baseline_promotion_simulation_custody_routed',
                    actor=str(actor or 'system'),
                    alert_id=str(new_alert.get('alert_id') or ''),
                    route_id=str((new_alert.get('routing') or {}).get('route_id') or ''),
                    queue_id=str((new_alert.get('routing') or {}).get('queue_id') or ''),
                    owner_role=str((new_alert.get('routing') or {}).get('owner_role') or ''),
                    source='default_route',
                )
        elif bool(policy.get('enabled')) and not drifted and active_alert is not None:
            for item in alerts:
                if str(item.get('alert_id') or '') == str(active_alert.get('alert_id') or ''):
                    item['active'] = False
                    item['cleared_at'] = now_ts
                    item['cleared_by'] = str(actor or 'system')
                    item['recovered_at'] = now_ts
                    item['recovered_by'] = str(actor or 'system')
                    item['status'] = 'recovered'
                    item['suppression_state'] = {
                        **dict(item.get('suppression_state') or {}),
                        'suppressed': False,
                        'reasons': [],
                        'evaluated_at': now_ts,
                    }
                    break
            notification = {}
            if bool(policy.get('notify_on_recovery')):
                notification = gw.audit.create_app_notification(
                    category='operator',
                    title='Baseline simulation custody drift recovered',
                    body=f"Custody drift cleared for baseline promotion {str(release.get('release_id') or '').strip()}.",
                    target_path=str(policy.get('target_path') or '/ui/?tab=operator'),
                    created_by=str(actor or 'system'),
                    metadata={
                        'kind': 'baseline_promotion_simulation_custody_recovered',
                        'promotion_id': str(release.get('release_id') or ''),
                        'reconciliation_id': str(reconciliation.get('reconciliation_id') or ''),
                        'severity': 'info',
                    },
                    tenant_id=release.get('tenant_id'),
                    workspace_id=release.get('workspace_id'),
                    environment=release.get('environment'),
                )
            promotion = self._append_baseline_promotion_timeline_event(
                promotion,
                kind='monitoring',
                label='baseline_promotion_simulation_custody_recovered',
                actor=str(actor or 'system'),
                reconciliation_id=str(reconciliation.get('reconciliation_id') or ''),
                notification_id=str((notification or {}).get('notification_id') or ''),
            )
        max_alerts = max(1, int(policy.get('max_alerts') or 20))
        alerts.sort(key=lambda item: (float(item.get('created_at') or 0.0), str(item.get('alert_id') or '')), reverse=True)
        alerts = alerts[:max_alerts]
        active_alert = next((item for item in alerts if bool(item.get('active'))), {})
        blocked = bool(policy.get('enabled')) and bool(policy.get('block_on_drift')) and drifted
        active_ownership = self._baseline_promotion_simulation_custody_ownership_projection(active_alert)
        active_routing = self._baseline_promotion_simulation_custody_routing_projection(active_alert)
        guard = {
            'blocked': blocked,
            'reason': 'baseline_promotion_simulation_custody_drift_detected' if blocked else '',
            'reasons': ['baseline_promotion_simulation_custody_drift_detected'] if blocked else [],
            'status': 'blocked' if blocked else 'clear',
            'updated_at': now_ts,
            'updated_by': str(actor or 'system'),
            'reconciliation_id': str(reconciliation.get('reconciliation_id') or ''),
            'drifted_count': int(summary.get('drifted_count') or 0),
            'active_alert_id': str(active_alert.get('alert_id') or ''),
            'notification_id': str(active_alert.get('notification_id') or ''),
            'alert_status': self._baseline_promotion_simulation_custody_alert_status(active_alert, now_ts=now_ts) if active_alert else '',
            'escalated': bool(int(active_alert.get('escalation_level') or 0) > 0),
            'escalation_level': int(active_alert.get('escalation_level') or 0),
            'severity': str(active_alert.get('severity') or ''),
            'suppressed': bool(((active_alert.get('suppression_state') or {}).get('suppressed'))),
            'suppression_reasons': [str(item) for item in list(((active_alert.get('suppression_state') or {}).get('reasons')) or []) if str(item)],
            'pending_escalation_level': int((((active_alert.get('suppression_state') or {}).get('pending_escalation_level')) or 0)),
            'owner_id': str(active_ownership.get('owner_id') or ''),
            'owner_role': str(active_ownership.get('owner_role') or ''),
            'ownership_status': str(active_ownership.get('status') or ''),
            'queue_id': str(active_ownership.get('queue_id') or active_routing.get('queue_id') or ''),
            'queue_label': str(active_ownership.get('queue_label') or active_routing.get('queue_label') or ''),
            'route_id': str(active_routing.get('route_id') or ''),
            'route_label': str(active_routing.get('route_label') or ''),
        }
        promotion['simulation_custody_alerts'] = alerts
        promotion['simulation_custody_guard'] = guard
        metadata['baseline_promotion'] = promotion
        updated = gw.audit.update_release_bundle(
            str(release.get('release_id') or ''),
            metadata=metadata,
            tenant_id=release.get('tenant_id'),
            workspace_id=release.get('workspace_id'),
            environment=release.get('environment'),
        ) or release
        governance = self._evaluate_baseline_promotion_simulation_custody_alert_governance(
            gw,
            release=updated,
            actor=actor,
            policy=policy,
            reconciliation=reconciliation,
        )
        updated_release = dict(governance.get('release') or updated)
        updated_alerts = [dict(item) for item in list(governance.get('alerts') or self._baseline_promotion_simulation_custody_alerts(updated_release))]
        updated_guard = dict(governance.get('guard') or self._baseline_promotion_simulation_custody_guard(updated_release))
        return {
            'release': updated_release,
            'policy': policy,
            'guard': updated_guard,
            'alerts': updated_alerts,
            'alerts_summary': self._baseline_promotion_simulation_custody_alerts_summary(updated_alerts),
            'new_alert': new_alert or {},
            'governance': {
                'escalated': bool(governance.get('escalated')),
            },
        }

