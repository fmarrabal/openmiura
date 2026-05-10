"""baseline_rollout_support._monitoring_a_mixin

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


class _OpenClawBaselineRolloutSupportMonitoringAMixin:
    """Sub-mixin: monitoring a methods on OpenClawBaselineRolloutSupportMixin."""

    def _normalize_baseline_promotion_simulation_custody_monitoring_policy(self, raw_policy: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(raw_policy or {})
        fallback_target_path = str(payload.get('target_path') or '/ui/?tab=operator').strip() or '/ui/?tab=operator'
        try:
            interval_s = int(payload.get('interval_s') or payload.get('reconcile_every_s') or 3600)
        except Exception:
            interval_s = 3600
        try:
            max_alerts = int(payload.get('max_alerts') or 20)
        except Exception:
            max_alerts = 20
        try:
            dedupe_window_s = int(payload.get('dedupe_window_s') or 0)
        except Exception:
            dedupe_window_s = 0
        try:
            default_mute_s = int(payload.get('default_mute_s') or payload.get('mute_default_s') or 3600)
        except Exception:
            default_mute_s = 3600
        try:
            suppression_window_s = int(payload.get('suppression_window_s') or payload.get('notification_suppression_window_s') or 0)
        except Exception:
            suppression_window_s = 0
        raw_levels = list(payload.get('escalation_levels') or payload.get('escalations') or [])
        if not raw_levels:
            fallback_after_s = payload.get('escalate_after_s') or payload.get('ack_timeout_s') or payload.get('escalation_after_s')
            if fallback_after_s is not None:
                raw_levels = [{
                    'after_s': fallback_after_s,
                    'severity': payload.get('escalation_severity') or payload.get('severity') or 'critical',
                    'label': payload.get('escalation_label') or 'Escalated custody drift',
                    'route_id': payload.get('escalation_route_id') or 'escalation-route-1',
                    'queue_id': payload.get('escalation_queue_id') or payload.get('queue_id') or '',
                    'queue_label': payload.get('escalation_queue_label') or payload.get('queue_label') or payload.get('queue_name') or '',
                    'owner_role': payload.get('escalation_owner_role') or payload.get('owner_role') or payload.get('default_owner_role') or '',
                    'owner_id': payload.get('escalation_owner_id') or payload.get('owner_id') or payload.get('default_owner_id') or '',
                }]
        levels = []
        for index, raw_level in enumerate(raw_levels, start=1):
            level_payload = dict(raw_level or {})
            try:
                after_s = int(level_payload.get('after_s') or level_payload.get('delay_s') or level_payload.get('ack_timeout_s') or 0)
            except Exception:
                after_s = 0
            try:
                level_no = int(level_payload.get('level') or index)
            except Exception:
                level_no = index
            levels.append({
                'level': max(1, level_no),
                'after_s': max(0, after_s),
                'severity': str(level_payload.get('severity') or payload.get('escalation_severity') or 'critical').strip() or 'critical',
                'label': str(level_payload.get('label') or f'Escalation level {index}').strip() or f'Escalation level {index}',
                'target_path': str(level_payload.get('target_path') or payload.get('escalation_target_path') or fallback_target_path).strip() or fallback_target_path,
                'route_id': str(level_payload.get('route_id') or level_payload.get('id') or f'escalation-route-{index}').strip() or f'escalation-route-{index}',
                'queue_id': str(level_payload.get('queue_id') or level_payload.get('queue') or payload.get('escalation_queue_id') or payload.get('default_queue_id') or '').strip(),
                'queue_label': str(level_payload.get('queue_label') or level_payload.get('queue_name') or level_payload.get('queue') or payload.get('escalation_queue_label') or payload.get('default_queue_label') or payload.get('queue_label') or '').strip(),
                'owner_role': str(level_payload.get('owner_role') or level_payload.get('requested_role') or payload.get('escalation_owner_role') or payload.get('default_owner_role') or '').strip(),
                'owner_id': str(level_payload.get('owner_id') or level_payload.get('assignee') or payload.get('escalation_owner_id') or payload.get('default_owner_id') or '').strip(),
            })
        levels.sort(key=lambda item: (int(item.get('after_s') or 0), int(item.get('level') or 0)))
        for index, item in enumerate(levels, start=1):
            item['level'] = max(index, int(item.get('level') or index))
        raw_default_route = dict(payload.get('default_route') or {})
        if not raw_default_route:
            raw_default_route = {
                'route_id': payload.get('default_route_id') or 'default-route',
                'label': payload.get('default_route_label') or 'Default custody route',
                'queue_id': payload.get('default_queue_id') or payload.get('queue_id') or '',
                'queue_label': payload.get('default_queue_label') or payload.get('queue_label') or payload.get('queue_name') or '',
                'owner_role': payload.get('default_owner_role') or payload.get('owner_role') or '',
                'owner_id': payload.get('default_owner_id') or payload.get('owner_id') or '',
                'target_path': payload.get('target_path') or fallback_target_path,
                'severity': payload.get('severity') or 'warning',
                'min_escalation_level': 0,
            }
        default_route = self._normalize_baseline_promotion_simulation_custody_route(raw_default_route, index=0, fallback_target_path=fallback_target_path)
        raw_routes = list(payload.get('routing_routes') or payload.get('routes') or payload.get('ownership_routes') or payload.get('escalation_routes') or [])
        routes = [
            self._normalize_baseline_promotion_simulation_custody_route(raw_route, index=index, fallback_target_path=fallback_target_path)
            for index, raw_route in enumerate(raw_routes, start=1)
        ]
        if any(default_route.get(key) for key in ('queue_id', 'owner_role', 'owner_id', 'target_path')):
            routes.append(default_route)
        for level in levels:
            if any(level.get(key) for key in ('queue_id', 'owner_role', 'owner_id')):
                routes.append(self._normalize_baseline_promotion_simulation_custody_route({
                    'route_id': level.get('route_id') or f'escalation-route-{int(level.get("level") or 0)}',
                    'label': level.get('label') or f'Escalation level {int(level.get("level") or 0)}',
                    'min_escalation_level': int(level.get('level') or 0),
                    'queue_id': level.get('queue_id') or '',
                    'queue_label': level.get('queue_label') or '',
                    'owner_role': level.get('owner_role') or '',
                    'owner_id': level.get('owner_id') or '',
                    'target_path': level.get('target_path') or fallback_target_path,
                    'severity': level.get('severity') or '',
                }, index=int(level.get('level') or 0), fallback_target_path=fallback_target_path))
        unique_routes: list[dict[str, Any]] = []
        seen_route_ids: set[str] = set()
        for route in sorted(routes, key=lambda item: (int(item.get('min_escalation_level') or 0), str(item.get('route_id') or ''))):
            route_id = str(route.get('route_id') or '').strip()
            if not route_id or route_id in seen_route_ids:
                continue
            seen_route_ids.add(route_id)
            unique_routes.append(route)
        routes = unique_routes
        escalation_enabled = bool(payload.get('escalation_enabled', bool(levels)))
        try:
            max_escalations = int(payload.get('max_escalations') or len(levels) or 3)
        except Exception:
            max_escalations = max(len(levels), 3)
        routing_enabled = bool(payload.get('routing_enabled', bool(routes)))
        routing_enabled = bool(payload.get('routing_enabled', bool(routes)))
        ownership_enabled = bool(payload.get('ownership_enabled', routing_enabled or bool(default_route.get('owner_role')) or bool(default_route.get('owner_id'))))
        handoff_enabled = bool(payload.get('handoff_enabled', ownership_enabled))
        handoff_require_reason = bool(payload.get('handoff_require_reason', False))
        sla_payload = dict(payload.get('sla_policy') or payload.get('sla') or {})
        def _sla_int(*keys: str, default: int = 0) -> int:
            for key in keys:
                value = sla_payload.get(key) if key in sla_payload else payload.get(key)
                if value is None:
                    continue
                try:
                    return max(0, int(value))
                except Exception:
                    continue
            return max(0, int(default or 0))
        try:
            warning_ratio = float(sla_payload.get('warning_ratio') if 'warning_ratio' in sla_payload else payload.get('sla_warning_ratio', payload.get('warning_ratio', 0.8)))
        except Exception:
            warning_ratio = 0.8
        warning_ratio = min(0.95, max(0.0, warning_ratio))
        acknowledge_s = _sla_int('acknowledge_s', 'ack_s', 'first_response_s', default=0)
        claim_s = _sla_int('claim_s', 'ownership_s', 'owner_claim_s', default=0)
        resolve_s = _sla_int('resolve_s', 'resolution_s', 'clear_s', default=0)
        handoff_accept_s = _sla_int('handoff_accept_s', 'handoff_s', 'handoff_ack_s', default=0)
        sla_enabled = bool(sla_payload.get('enabled', payload.get('sla_enabled', any([acknowledge_s, claim_s, resolve_s, handoff_accept_s]))))
        sla_policy = {
            'enabled': sla_enabled,
            'acknowledge_s': acknowledge_s,
            'claim_s': claim_s,
            'resolve_s': resolve_s,
            'handoff_accept_s': handoff_accept_s,
            'warning_ratio': warning_ratio,
            'notify_on_breach': bool(sla_payload.get('notify_on_breach', payload.get('notify_on_sla_breach', True))),
            'severity': str(sla_payload.get('severity') or payload.get('sla_severity') or 'high').strip() or 'high',
            'target_path': str(sla_payload.get('target_path') or payload.get('sla_target_path') or fallback_target_path).strip() or fallback_target_path,
        }
        raw_team_escalation_queues = list(
            payload.get('team_escalation_queues')
            or payload.get('sla_team_queues')
            or payload.get('sla_breach_routes')
            or []
        )
        team_escalation_queues = []
        for index, raw_route in enumerate(raw_team_escalation_queues, start=1):
            route_payload = dict(raw_route or {})
            normalized_route = self._normalize_baseline_promotion_simulation_custody_route({
                **route_payload,
                'route_id': route_payload.get('route_id') or route_payload.get('id') or f'sla-team-route-{index}',
                'label': route_payload.get('label') or route_payload.get('name') or f'SLA team queue {index}',
                'target_path': route_payload.get('target_path') or sla_policy.get('target_path') or fallback_target_path,
                'severity': route_payload.get('severity') or sla_policy.get('severity') or payload.get('severity') or '',
            }, index=index, fallback_target_path=sla_policy.get('target_path') or fallback_target_path)
            normalized_route['breach_targets'] = [
                str(item).strip()
                for item in list(route_payload.get('breach_targets') or route_payload.get('on_targets') or route_payload.get('targets') or [])
                if str(item).strip()
            ]
            normalized_route['queue_type'] = str(route_payload.get('queue_type') or route_payload.get('type') or 'team_escalation').strip() or 'team_escalation'
            team_escalation_queues.append(normalized_route)
        raw_sla_breach_route = dict(payload.get('sla_breach_route') or {})
        if not raw_sla_breach_route and any(payload.get(key) is not None for key in ('sla_breach_route_id', 'sla_breach_queue_id', 'sla_breach_owner_role', 'sla_breach_owner_id')):
            raw_sla_breach_route = {
                'route_id': payload.get('sla_breach_route_id') or 'sla-breach-route',
                'label': payload.get('sla_breach_route_label') or 'SLA breach route',
                'queue_id': payload.get('sla_breach_queue_id') or '',
                'queue_label': payload.get('sla_breach_queue_label') or payload.get('sla_breach_queue_id') or '',
                'owner_role': payload.get('sla_breach_owner_role') or '',
                'owner_id': payload.get('sla_breach_owner_id') or '',
                'target_path': payload.get('sla_breach_target_path') or sla_policy.get('target_path') or fallback_target_path,
                'severity': payload.get('sla_breach_severity') or sla_policy.get('severity') or '',
            }
        sla_breach_route = self._normalize_baseline_promotion_simulation_custody_route(raw_sla_breach_route, index=0, fallback_target_path=sla_policy.get('target_path') or fallback_target_path) if raw_sla_breach_route else {}
        auto_reroute_on_sla_breach = bool(payload.get('auto_reroute_on_sla_breach', bool(team_escalation_queues) or bool(sla_breach_route)))
        raw_queue_capacities = list(payload.get('queue_capacities') or payload.get('queue_capacity_map') or payload.get('queue_capacity_routes') or [])
        if isinstance(payload.get('queue_capacity_map'), dict):
            raw_queue_capacities = [
                {'queue_id': key, **(dict(value or {}) if isinstance(value, dict) else {'capacity': value})}
                for key, value in dict(payload.get('queue_capacity_map') or {}).items()
            ]
        queue_capacities = []
        for index, raw_queue in enumerate(raw_queue_capacities, start=1):
            queue_payload = dict(raw_queue or {})
            queue_id = str(queue_payload.get('queue_id') or queue_payload.get('queue') or '').strip()
            if not queue_id:
                continue
            try:
                queue_capacity = int(queue_payload.get('capacity') or queue_payload.get('queue_capacity') or queue_payload.get('max_active_alerts') or 0)
            except Exception:
                queue_capacity = 0
            try:
                queue_warning = int(queue_payload.get('warning_capacity') or queue_payload.get('warning_threshold') or max(0, queue_capacity - 1)) if queue_capacity > 0 else 0
            except Exception:
                queue_warning = max(0, queue_capacity - 1)
            reserved_for_queue_types = [
                str(item).strip()
                for item in list(queue_payload.get('reserved_for_queue_types') or queue_payload.get('reserved_queue_types') or [])
                if str(item).strip()
            ]
            reserved_for_severities = [
                str(item).strip().lower()
                for item in list(queue_payload.get('reserved_for_severities') or queue_payload.get('reserved_severities') or [])
                if str(item).strip()
            ]
            try:
                reserved_capacity = int(queue_payload.get('reserved_capacity') or queue_payload.get('queue_reserved_capacity') or 0)
            except Exception:
                reserved_capacity = 0
            leased_for_queue_types = [
                str(item).strip()
                for item in list(queue_payload.get('leased_for_queue_types') or queue_payload.get('lease_for_queue_types') or queue_payload.get('leased_queue_types') or [])
                if str(item).strip()
            ]
            leased_for_severities = [
                str(item).strip().lower()
                for item in list(queue_payload.get('leased_for_severities') or queue_payload.get('lease_for_severities') or queue_payload.get('leased_severities') or [])
                if str(item).strip()
            ]
            try:
                leased_capacity = int(queue_payload.get('leased_capacity') or queue_payload.get('lease_capacity') or 0)
            except Exception:
                leased_capacity = 0
            lease_expires_at = queue_payload.get('lease_expires_at') or queue_payload.get('leased_until') or queue_payload.get('lease_until')
            temporary_holds = [
                dict(item or {})
                for item in list(queue_payload.get('temporary_holds') or queue_payload.get('queue_holds') or queue_payload.get('holds') or [])
                if isinstance(item, dict)
            ]
            queue_capacities.append({
                'queue_id': queue_id,
                'queue_label': str(queue_payload.get('queue_label') or queue_payload.get('label') or queue_id).strip() or queue_id,
                'capacity': max(0, int(queue_capacity or 0)),
                'warning_capacity': max(0, int(queue_warning or 0)),
                'hard_limit': bool(queue_payload.get('hard_limit', queue_payload.get('queue_hard_limit', False))),
                'queue_type': str(queue_payload.get('queue_type') or queue_payload.get('type') or '').strip(),
                'target_path': str(queue_payload.get('target_path') or fallback_target_path).strip() or fallback_target_path,
                'owner_role': str(queue_payload.get('owner_role') or '').strip(),
                'owner_id': str(queue_payload.get('owner_id') or '').strip(),
                'queue_family_id': str(queue_payload.get('queue_family_id') or queue_payload.get('family_id') or queue_payload.get('family') or '').strip(),
                'queue_family_label': str(queue_payload.get('queue_family_label') or queue_payload.get('family_label') or queue_payload.get('queue_family_id') or queue_payload.get('family_id') or queue_payload.get('family') or '').strip(),
                'load_weight': max(0.1, float(queue_payload.get('load_weight') or queue_payload.get('queue_weight') or 1.0)),
                'reserved_capacity': max(0, int(reserved_capacity or 0)),
                'reserved_for_queue_types': reserved_for_queue_types,
                'reserved_for_severities': reserved_for_severities,
                'leased_capacity': max(0, int(leased_capacity or 0)),
                'lease_expires_at': lease_expires_at,
                'lease_reason': str(queue_payload.get('lease_reason') or queue_payload.get('leased_reason') or '').strip(),
                'lease_holder': str(queue_payload.get('lease_holder') or queue_payload.get('lease_owner') or '').strip(),
                'lease_id': str(queue_payload.get('lease_id') or '').strip(),
                'leased_for_queue_types': leased_for_queue_types,
                'leased_for_severities': leased_for_severities,
                'temporary_holds': temporary_holds,
                'forecast_arrivals': queue_payload.get('forecast_arrivals'),
                'forecast_arrivals_per_hour': queue_payload.get('forecast_arrivals_per_hour'),
                'forecast_window_s': queue_payload.get('forecast_window_s'),
            })
        queue_capacity_payload = dict(payload.get('queue_capacity_policy') or payload.get('queue_load_policy') or {})
        default_queue_capacity_raw = queue_capacity_payload.get('default_capacity') if 'default_capacity' in queue_capacity_payload else payload.get('default_queue_capacity')
        try:
            default_queue_capacity = int(default_queue_capacity_raw) if default_queue_capacity_raw is not None else 0
        except Exception:
            default_queue_capacity = 0
        default_queue_warning_raw = queue_capacity_payload.get('warning_capacity') if 'warning_capacity' in queue_capacity_payload else payload.get('default_queue_warning_capacity')
        try:
            default_queue_warning = int(default_queue_warning_raw) if default_queue_warning_raw is not None else max(0, default_queue_capacity - 1)
        except Exception:
            default_queue_warning = max(0, default_queue_capacity - 1)
        try:
            default_reserved_capacity = int(queue_capacity_payload.get('default_reserved_capacity') or payload.get('default_reserved_capacity') or 0)
        except Exception:
            default_reserved_capacity = 0
        try:
            default_leased_capacity = int(queue_capacity_payload.get('default_leased_capacity') or payload.get('default_leased_capacity') or 0)
        except Exception:
            default_leased_capacity = 0
        try:
            default_lease_ttl_s = int(queue_capacity_payload.get('default_lease_ttl_s') or payload.get('default_lease_ttl_s') or 0)
        except Exception:
            default_lease_ttl_s = 0
        try:
            default_hold_ttl_s = int(queue_capacity_payload.get('default_hold_ttl_s') or payload.get('default_hold_ttl_s') or 0)
        except Exception:
            default_hold_ttl_s = 0
        reserved_for_queue_types = [
            str(item).strip()
            for item in list(queue_capacity_payload.get('reserved_for_queue_types') or payload.get('reserved_for_queue_types') or [])
            if str(item).strip()
        ]
        reserved_for_severities = [
            str(item).strip().lower()
            for item in list(queue_capacity_payload.get('reserved_for_severities') or payload.get('reserved_for_severities') or [])
            if str(item).strip()
        ]
        try:
            reroute_cooldown_s = int(queue_capacity_payload.get('reroute_cooldown_s') or payload.get('reroute_cooldown_s') or 0)
        except Exception:
            reroute_cooldown_s = 0
        try:
            anti_thrashing_min_active_delta = int(queue_capacity_payload.get('anti_thrashing_min_active_delta') or payload.get('anti_thrashing_min_active_delta') or 0)
        except Exception:
            anti_thrashing_min_active_delta = 0
        try:
            anti_thrashing_min_load_delta = float(queue_capacity_payload.get('anti_thrashing_min_load_delta') or payload.get('anti_thrashing_min_load_delta') or 0.0)
        except Exception:
            anti_thrashing_min_load_delta = 0.0
        try:
            aging_after_s = int(queue_capacity_payload.get('aging_after_s') or queue_capacity_payload.get('queue_aging_after_s') or payload.get('aging_after_s') or payload.get('queue_aging_after_s') or 0)
        except Exception:
            aging_after_s = 0
        try:
            starvation_after_s = int(queue_capacity_payload.get('starvation_after_s') or queue_capacity_payload.get('starvation_threshold_s') or queue_capacity_payload.get('queue_starvation_after_s') or payload.get('starvation_after_s') or payload.get('starvation_threshold_s') or payload.get('queue_starvation_after_s') or 0)
        except Exception:
            starvation_after_s = 0
        try:
            expected_service_time_s = int(queue_capacity_payload.get('expected_service_time_s') or queue_capacity_payload.get('service_time_s') or payload.get('expected_service_time_s') or payload.get('service_time_s') or 300)
        except Exception:
            expected_service_time_s = 300
        try:
            expedite_threshold_s = int(queue_capacity_payload.get('expedite_threshold_s') or payload.get('expedite_threshold_s') or 900)
        except Exception:
            expedite_threshold_s = 900
        try:
            expedite_min_risk_score = float(queue_capacity_payload.get('expedite_min_risk_score') or payload.get('expedite_min_risk_score') or 0.85)
        except Exception:
            expedite_min_risk_score = 0.85
        try:
            forecast_window_s = int(queue_capacity_payload.get('forecast_window_s') or payload.get('forecast_window_s') or 1800)
        except Exception:
            forecast_window_s = 1800
        try:
            proactive_min_projected_load_delta = float(queue_capacity_payload.get('proactive_min_projected_load_delta') or payload.get('proactive_min_projected_load_delta') or 0.15)
        except Exception:
            proactive_min_projected_load_delta = 0.15
        try:
            proactive_wait_buffer_s = int(queue_capacity_payload.get('proactive_wait_buffer_s') or payload.get('proactive_wait_buffer_s') or 180)
        except Exception:
            proactive_wait_buffer_s = 180
        try:
            surge_load_ratio_threshold = float(queue_capacity_payload.get('surge_load_ratio_threshold') or payload.get('surge_load_ratio_threshold') or 0.85)
        except Exception:
            surge_load_ratio_threshold = 0.85
        try:
            overload_projected_load_ratio_threshold = float(queue_capacity_payload.get('overload_projected_load_ratio_threshold') or payload.get('overload_projected_load_ratio_threshold') or surge_load_ratio_threshold or 0.95)
        except Exception:
            overload_projected_load_ratio_threshold = float(surge_load_ratio_threshold or 0.95)
        try:
            overload_projected_wait_time_threshold_s = int(queue_capacity_payload.get('overload_projected_wait_time_threshold_s') or payload.get('overload_projected_wait_time_threshold_s') or max(300, int(expected_service_time_s or 300) * 2))
        except Exception:
            overload_projected_wait_time_threshold_s = max(300, int(expected_service_time_s or 300) * 2)
        def _normalize_admission_action(raw_value: Any, default: str = 'defer') -> str:
            value = str(raw_value or default).strip().lower().replace('-', '_')
            return value if value in {'admit', 'defer', 'manual_gate', 'park', 'reject'} else default
        admission_default_action = _normalize_admission_action(queue_capacity_payload.get('admission_default_action') or payload.get('admission_default_action') or queue_capacity_payload.get('overload_default_action') or payload.get('overload_default_action') or 'defer')
        overload_global_action = _normalize_admission_action(queue_capacity_payload.get('overload_global_action') or payload.get('overload_global_action') or admission_default_action, admission_default_action)
        admission_exempt_severities = [
            str(item).strip().lower()
            for item in list(queue_capacity_payload.get('admission_exempt_severities') or payload.get('admission_exempt_severities') or [])
            if str(item).strip()
        ]
        admission_exempt_queue_types = [
            str(item).strip()
            for item in list(queue_capacity_payload.get('admission_exempt_queue_types') or payload.get('admission_exempt_queue_types') or [])
            if str(item).strip()
        ]
        default_queue_family = str(queue_capacity_payload.get('default_queue_family') or payload.get('default_queue_family') or '').strip()
        queue_families_enabled = bool(
            queue_capacity_payload.get(
                'queue_families_enabled',
                payload.get(
                    'queue_families_enabled',
                    bool(default_queue_family)
                    or any(str(dict(item or {}).get('queue_family_id') or dict(item or {}).get('family_id') or dict(item or {}).get('family') or '').strip() for item in queue_capacities),
                ),
            )
        )
        family_reroute_cooldown_default = queue_capacity_payload.get('family_reroute_cooldown_s') or payload.get('family_reroute_cooldown_s') or reroute_cooldown_s or 300
        try:
            family_reroute_cooldown_s = int(family_reroute_cooldown_default)
        except Exception:
            family_reroute_cooldown_s = int(reroute_cooldown_s or 300)
        try:
            family_min_active_delta = int(queue_capacity_payload.get('family_min_active_delta') or payload.get('family_min_active_delta') or anti_thrashing_min_active_delta or 1)
        except Exception:
            family_min_active_delta = int(anti_thrashing_min_active_delta or 1)
        try:
            family_min_load_delta = float(queue_capacity_payload.get('family_min_load_delta') or payload.get('family_min_load_delta') or proactive_min_projected_load_delta or anti_thrashing_min_load_delta or 0.1)
        except Exception:
            family_min_load_delta = float(proactive_min_projected_load_delta or anti_thrashing_min_load_delta or 0.1)
        try:
            family_min_projected_wait_delta_s = int(queue_capacity_payload.get('family_min_projected_wait_delta_s') or payload.get('family_min_projected_wait_delta_s') or proactive_wait_buffer_s or 120)
        except Exception:
            family_min_projected_wait_delta_s = int(proactive_wait_buffer_s or 120)
        try:
            family_recent_hops_threshold = int(queue_capacity_payload.get('family_recent_hops_threshold') or payload.get('family_recent_hops_threshold') or 2)
        except Exception:
            family_recent_hops_threshold = 2
        try:
            family_history_limit = int(queue_capacity_payload.get('family_history_limit') or payload.get('family_history_limit') or 8)
        except Exception:
            family_history_limit = 8
        multi_hop_hysteresis_enabled = bool(queue_capacity_payload.get('multi_hop_hysteresis_enabled', payload.get('multi_hop_hysteresis_enabled', queue_families_enabled)))
        starvation_prevention_enabled = bool(queue_capacity_payload.get('starvation_prevention_enabled', payload.get('starvation_prevention_enabled', starvation_after_s > 0)))
        queue_capacity_policy = {
            'enabled': bool(queue_capacity_payload.get('enabled', payload.get('queue_capacity_enabled', bool(queue_capacities) or default_queue_capacity > 0))),
            'default_capacity': max(0, int(default_queue_capacity or 0)),
            'warning_capacity': max(0, int(default_queue_warning or 0)),
            'hard_limit': bool(queue_capacity_payload.get('hard_limit', payload.get('queue_capacity_hard_limit', False))),
            'prefer_lowest_load': bool(queue_capacity_payload.get('prefer_lowest_load', payload.get('prefer_lowest_load', True))),
            'rebalance_on_over_capacity': bool(queue_capacity_payload.get('rebalance_on_over_capacity', payload.get('rebalance_on_over_capacity', True))),
            'load_metric': str(queue_capacity_payload.get('load_metric') or payload.get('queue_load_metric') or 'active_alerts').strip() or 'active_alerts',
            'reservation_enabled': bool(queue_capacity_payload.get('reservation_enabled', payload.get('reservation_enabled', default_reserved_capacity > 0))),
            'default_reserved_capacity': max(0, int(default_reserved_capacity or 0)),
            'reserved_for_queue_types': reserved_for_queue_types,
            'reserved_for_severities': reserved_for_severities,
            'reservation_lease_enabled': bool(queue_capacity_payload.get('reservation_lease_enabled', payload.get('reservation_lease_enabled', default_leased_capacity > 0 or any(int(dict(item or {}).get('leased_capacity') or 0) > 0 for item in queue_capacities)))),
            'default_leased_capacity': max(0, int(default_leased_capacity or 0)),
            'default_lease_ttl_s': max(0, int(default_lease_ttl_s or 0)),
            'lease_reclaim_enabled': bool(queue_capacity_payload.get('lease_reclaim_enabled', payload.get('lease_reclaim_enabled', True))),
            'temporary_holds_enabled': bool(queue_capacity_payload.get('temporary_holds_enabled', payload.get('temporary_holds_enabled', any(list(dict(item or {}).get('temporary_holds') or [] ) for item in queue_capacities)))),
            'default_hold_ttl_s': max(0, int(default_hold_ttl_s or 0)),
            'starvation_lease_capacity_borrow_enabled': bool(queue_capacity_payload.get('starvation_lease_capacity_borrow_enabled', payload.get('starvation_lease_capacity_borrow_enabled', starvation_prevention_enabled))),
            'starvation_hold_capacity_borrow_enabled': bool(queue_capacity_payload.get('starvation_hold_capacity_borrow_enabled', payload.get('starvation_hold_capacity_borrow_enabled', starvation_prevention_enabled))),
            'expedite_lease_capacity_borrow_enabled': bool(queue_capacity_payload.get('expedite_lease_capacity_borrow_enabled', payload.get('expedite_lease_capacity_borrow_enabled', True))),
            'expedite_hold_capacity_borrow_enabled': bool(queue_capacity_payload.get('expedite_hold_capacity_borrow_enabled', payload.get('expedite_hold_capacity_borrow_enabled', True))),
            'anti_thrashing_enabled': bool(queue_capacity_payload.get('anti_thrashing_enabled', payload.get('anti_thrashing_enabled', False))),
            'reroute_cooldown_s': max(0, int(reroute_cooldown_s or 0)),
            'anti_thrashing_min_active_delta': max(0, int(anti_thrashing_min_active_delta or 0)),
            'anti_thrashing_min_load_delta': max(0.0, float(anti_thrashing_min_load_delta or 0.0)),
            'aging_enabled': bool(queue_capacity_payload.get('aging_enabled', payload.get('aging_enabled', aging_after_s > 0))),
            'aging_after_s': max(0, int(aging_after_s or 0)),
            'starvation_prevention_enabled': starvation_prevention_enabled,
            'starvation_after_s': max(0, int(starvation_after_s or 0)),
            'starvation_reserved_capacity_borrow_enabled': bool(queue_capacity_payload.get('starvation_reserved_capacity_borrow_enabled', payload.get('starvation_reserved_capacity_borrow_enabled', starvation_prevention_enabled))),
            'starvation_bypass_anti_thrashing': bool(queue_capacity_payload.get('starvation_bypass_anti_thrashing', payload.get('starvation_bypass_anti_thrashing', starvation_prevention_enabled))),
            'breach_prediction_enabled': bool(queue_capacity_payload.get('breach_prediction_enabled', payload.get('breach_prediction_enabled', bool(payload.get('sla_policy') or payload.get('sla'))))),
            'expected_service_time_s': max(60, int(expected_service_time_s or 300)),
            'expedite_enabled': bool(queue_capacity_payload.get('expedite_enabled', payload.get('expedite_enabled', bool(payload.get('sla_policy') or payload.get('sla'))))),
            'expedite_threshold_s': max(0, int(expedite_threshold_s or 0)),
            'expedite_min_risk_score': max(0.0, float(expedite_min_risk_score or 0.0)),
            'expedite_reserved_capacity_borrow_enabled': bool(queue_capacity_payload.get('expedite_reserved_capacity_borrow_enabled', payload.get('expedite_reserved_capacity_borrow_enabled', True))),
            'expedite_bypass_anti_thrashing': bool(queue_capacity_payload.get('expedite_bypass_anti_thrashing', payload.get('expedite_bypass_anti_thrashing', True))),
            'predictive_forecasting_enabled': bool(queue_capacity_payload.get('predictive_forecasting_enabled', queue_capacity_payload.get('forecasting_enabled', payload.get('predictive_forecasting_enabled', payload.get('forecasting_enabled', False))))),
            'forecast_window_s': max(300, int(forecast_window_s or 1800)),
            'surge_load_ratio_threshold': min(2.0, max(0.25, float(surge_load_ratio_threshold or 0.85))),
            'proactive_routing_enabled': bool(queue_capacity_payload.get('proactive_routing_enabled', payload.get('proactive_routing_enabled', bool(queue_capacity_payload.get('predictive_forecasting_enabled', queue_capacity_payload.get('forecasting_enabled', payload.get('predictive_forecasting_enabled', payload.get('forecasting_enabled', False)))))))),
            'proactive_min_projected_load_delta': max(0.0, float(proactive_min_projected_load_delta or 0.0)),
            'proactive_wait_buffer_s': max(0, int(proactive_wait_buffer_s or 0)),
            'proactive_bypass_anti_thrashing': bool(queue_capacity_payload.get('proactive_bypass_anti_thrashing', payload.get('proactive_bypass_anti_thrashing', False))),
            'admission_control_enabled': bool(queue_capacity_payload.get('admission_control_enabled', payload.get('admission_control_enabled', bool(queue_capacity_payload.get('overload_governance_enabled', payload.get('overload_governance_enabled', False)))))),
            'admission_default_action': admission_default_action,
            'admission_exempt_severities': admission_exempt_severities,
            'admission_exempt_queue_types': admission_exempt_queue_types,
            'queue_families_enabled': queue_families_enabled,
            'default_queue_family': default_queue_family,
            'multi_hop_hysteresis_enabled': multi_hop_hysteresis_enabled,
            'family_reroute_cooldown_s': max(0, int(family_reroute_cooldown_s or 0)),
            'family_min_active_delta': max(0, int(family_min_active_delta or 0)),
            'family_min_load_delta': max(0.0, float(family_min_load_delta or 0.0)),
            'family_min_projected_wait_delta_s': max(0, int(family_min_projected_wait_delta_s or 0)),
            'family_recent_hops_threshold': max(1, int(family_recent_hops_threshold or 1)),
            'family_history_limit': max(2, int(family_history_limit or 2)),
            'expedite_bypass_family_hysteresis': bool(queue_capacity_payload.get('expedite_bypass_family_hysteresis', payload.get('expedite_bypass_family_hysteresis', True))),
            'proactive_bypass_family_hysteresis': bool(queue_capacity_payload.get('proactive_bypass_family_hysteresis', payload.get('proactive_bypass_family_hysteresis', True))),
            'starvation_bypass_family_hysteresis': bool(queue_capacity_payload.get('starvation_bypass_family_hysteresis', payload.get('starvation_bypass_family_hysteresis', True))),
            'admission_bypass_family_hysteresis': bool(queue_capacity_payload.get('admission_bypass_family_hysteresis', payload.get('admission_bypass_family_hysteresis', True))),
            'admit_expedite_on_overload': bool(queue_capacity_payload.get('admit_expedite_on_overload', payload.get('admit_expedite_on_overload', True))),
            'admit_starving_on_overload': bool(queue_capacity_payload.get('admit_starving_on_overload', payload.get('admit_starving_on_overload', True))),
            'overload_governance_enabled': bool(queue_capacity_payload.get('overload_governance_enabled', payload.get('overload_governance_enabled', bool(queue_capacity_payload.get('predictive_forecasting_enabled', queue_capacity_payload.get('forecasting_enabled', payload.get('predictive_forecasting_enabled', payload.get('forecasting_enabled', False)))))))),
            'overload_projected_load_ratio_threshold': min(3.0, max(0.25, float(overload_projected_load_ratio_threshold or surge_load_ratio_threshold or 0.95))),
            'overload_projected_wait_time_threshold_s': max(0, int(overload_projected_wait_time_threshold_s or 0)),
            'overload_global_action': overload_global_action,
        }
        load_aware_routing_enabled = bool(payload.get('load_aware_routing_enabled', queue_capacity_policy.get('enabled')))
        return {
            'enabled': bool(payload.get('enabled', False)),
            'auto_schedule': bool(payload.get('auto_schedule', True)),
            'interval_s': max(60, int(interval_s or 3600)),
            'notify_on_drift': bool(payload.get('notify_on_drift', True)),
            'notify_on_recovery': bool(payload.get('notify_on_recovery', True)),
            'notify_on_escalation': bool(payload.get('notify_on_escalation', True)),
            'block_on_drift': bool(payload.get('block_on_drift', False)),
            'target_path': fallback_target_path,
            'severity': str(payload.get('severity') or 'warning').strip() or 'warning',
            'max_alerts': max(1, int(max_alerts or 20)),
            'dedupe_window_s': max(0, int(dedupe_window_s or 0)),
            'default_mute_s': max(0, int(default_mute_s or 0)),
            'escalation_enabled': escalation_enabled,
            'escalation_levels': levels,
            'max_escalations': max(1, int(max_escalations or max(len(levels), 1))),
            'suppression_window_s': max(0, int(suppression_window_s or 0)),
            'suppress_while_acknowledged': bool(payload.get('suppress_while_acknowledged', True)),
            'suppress_while_muted': bool(payload.get('suppress_while_muted', True)),
            'escalation_target_path': str(payload.get('escalation_target_path') or payload.get('target_path') or fallback_target_path).strip() or fallback_target_path,
            'routing_enabled': routing_enabled,
            'ownership_enabled': ownership_enabled,
            'handoff_enabled': handoff_enabled,
            'handoff_require_reason': handoff_require_reason,
            'auto_assign_owner': bool(payload.get('auto_assign_owner', False)),
            'default_route': default_route,
            'routing_routes': routes,
            'sla_policy': sla_policy,
            'auto_reroute_on_sla_breach': auto_reroute_on_sla_breach,
            'notify_on_sla_reroute': bool(payload.get('notify_on_sla_reroute', True)),
            'team_escalation_queues': team_escalation_queues,
            'sla_breach_route': sla_breach_route,
            'queue_capacities': queue_capacities,
            'queue_capacity_policy': queue_capacity_policy,
            'load_aware_routing_enabled': load_aware_routing_enabled,
        }

    def _baseline_promotion_simulation_custody_monitoring_policy_for_release(self, release: dict[str, Any] | None, simulation: dict[str, Any] | None = None) -> dict[str, Any]:
        metadata = dict((release or {}).get('metadata') or {})
        promotion = dict(metadata.get('baseline_promotion') or {})
        promotion_policy = self._normalize_baseline_catalog_promotion_policy(dict(promotion.get('promotion_policy') or {}))
        policy = self._normalize_baseline_promotion_simulation_custody_monitoring_policy(dict(promotion_policy.get('simulation_custody_monitoring_policy') or {}))
        sim_policy = dict((dict(simulation or {}).get('simulation_policy') or {}))
        if sim_policy:
            policy = {
                **policy,
                **self._normalize_baseline_promotion_simulation_custody_monitoring_policy(dict(sim_policy.get('custody_monitoring_policy') or {})),
            }
        return self._normalize_baseline_promotion_simulation_custody_monitoring_policy(policy)

    def _baseline_promotion_simulation_custody_queue_capacity_state(
        self,
        gw,
        *,
        release: dict[str, Any] | None = None,
        policy: dict[str, Any] | None = None,
        exclude_alert_id: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        normalized_policy = self._normalize_baseline_promotion_simulation_custody_monitoring_policy(
            dict(policy or self._baseline_promotion_simulation_custody_monitoring_policy_for_release(release))
        )
        scope_tenant = tenant_id if tenant_id is not None else (release or {}).get('tenant_id')
        scope_workspace = workspace_id if workspace_id is not None else (release or {}).get('workspace_id')
        scope_environment = environment if environment is not None else (release or {}).get('environment')
        queue_capacity_policy = dict(normalized_policy.get('queue_capacity_policy') or {})
        default_capacity = max(0, int(queue_capacity_policy.get('default_capacity') or 0))
        default_warning = max(0, int(queue_capacity_policy.get('warning_capacity') or max(0, default_capacity - 1)))
        aging_enabled = bool(queue_capacity_policy.get('aging_enabled'))
        aging_after_s = max(0, int(queue_capacity_policy.get('aging_after_s') or 0))
        starvation_prevention_enabled = bool(queue_capacity_policy.get('starvation_prevention_enabled'))
        starvation_after_s = max(0, int(queue_capacity_policy.get('starvation_after_s') or 0))
        reservation_lease_enabled = bool(queue_capacity_policy.get('reservation_lease_enabled'))
        lease_reclaim_enabled = bool(queue_capacity_policy.get('lease_reclaim_enabled', True))
        temporary_holds_enabled = bool(queue_capacity_policy.get('temporary_holds_enabled'))
        default_leased_capacity = max(0, int(queue_capacity_policy.get('default_leased_capacity') or 0))
        default_lease_ttl_s = max(0, int(queue_capacity_policy.get('default_lease_ttl_s') or 0))
        default_hold_ttl_s = max(0, int(queue_capacity_policy.get('default_hold_ttl_s') or 0))
        now_ts = time.time()
        queues: dict[str, dict[str, Any]] = {}

        def _ensure_queue(queue_id: str, **updates: Any) -> dict[str, Any]:
            normalized_queue_id = str(queue_id or '').strip()
            if not normalized_queue_id:
                return {}
            item = queues.setdefault(normalized_queue_id, {
                'queue_id': normalized_queue_id,
                'queue_label': '',
                'capacity': 0,
                'warning_capacity': 0,
                'hard_limit': False,
                'queue_type': '',
                'owner_role': '',
                'owner_id': '',
                'queue_family_id': '',
                'queue_family_label': '',
                'load_weight': 1.0,
                'reserved_capacity': 0,
                'reservation_enabled': False,
                'reserved_for_queue_types': [],
                'reserved_for_severities': [],
                'leased_capacity': 0,
                'lease_expires_at': None,
                'lease_reason': '',
                'lease_holder': '',
                'lease_id': '',
                'leased_for_queue_types': [],
                'leased_for_severities': [],
                'temporary_holds': [],
                'active_count': 0,
                'active_alert_ids': [],
                'promotion_ids': [],
                'sla_rerouted_count': 0,
                'source_count': 0,
                'oldest_alert_age_s': 0,
                'newest_alert_age_s': 0,
                'aged_alert_count': 0,
                'starving_alert_count': 0,
                'expected_service_time_s': max(60, int(queue_capacity_policy.get('expected_service_time_s') or 300)),
                'forecast_arrivals': 0,
                'forecast_arrivals_per_hour': 0.0,
                'forecast_window_s': max(300, int(queue_capacity_policy.get('forecast_window_s') or 1800)),
                'admission_control_enabled': bool(queue_capacity_policy.get('admission_control_enabled')),
                'admission_action': str(queue_capacity_policy.get('admission_default_action') or ''),
                'admission_exempt_severities': list(queue_capacity_policy.get('admission_exempt_severities') or []),
                'admission_exempt_queue_types': list(queue_capacity_policy.get('admission_exempt_queue_types') or []),
                'overload_governance_enabled': bool(queue_capacity_policy.get('overload_governance_enabled')),
                'overload_projected_load_ratio_threshold': float(queue_capacity_policy.get('overload_projected_load_ratio_threshold') or 0.0),
                'overload_projected_wait_time_threshold_s': int(queue_capacity_policy.get('overload_projected_wait_time_threshold_s') or 0),
                'overload_action': str(queue_capacity_policy.get('overload_global_action') or queue_capacity_policy.get('admission_default_action') or ''),
            })
            for key, value in updates.items():
                if key in {'capacity', 'warning_capacity'}:
                    try:
                        numeric = int(value) if value is not None else 0
                    except Exception:
                        numeric = 0
                    item[key] = max(int(item.get(key) or 0), max(0, numeric))
                elif key == 'hard_limit':
                    item['hard_limit'] = bool(item.get('hard_limit')) or bool(value)
                elif key == 'load_weight':
                    try:
                        numeric = float(value) if value is not None else 1.0
                    except Exception:
                        numeric = 1.0
                    item['load_weight'] = max(0.1, float(item.get('load_weight') or 1.0), max(0.1, numeric))
                elif key == 'source_count':
                    item['source_count'] = int(item.get('source_count') or 0) + int(value or 0)
                elif key == 'reserved_capacity':
                    try:
                        numeric = int(value) if value is not None else 0
                    except Exception:
                        numeric = 0
                    item['reserved_capacity'] = max(int(item.get('reserved_capacity') or 0), max(0, numeric))
                    if int(item.get('reserved_capacity') or 0) > 0:
                        item['reservation_enabled'] = True
                elif key == 'leased_capacity':
                    try:
                        numeric = int(value) if value is not None else 0
                    except Exception:
                        numeric = 0
                    item['leased_capacity'] = max(int(item.get('leased_capacity') or 0), max(0, numeric))
                elif key == 'lease_expires_at':
                    try:
                        candidate = float(value) if value is not None else None
                    except Exception:
                        candidate = None
                    existing = item.get('lease_expires_at')
                    item['lease_expires_at'] = candidate if existing in {None, ''} else (max(float(existing), candidate) if candidate is not None else existing)
                elif key == 'expected_service_time_s':
                    try:
                        numeric = int(value) if value is not None else int(queue_capacity_policy.get('expected_service_time_s') or 300)
                    except Exception:
                        numeric = int(queue_capacity_policy.get('expected_service_time_s') or 300)
                    item['expected_service_time_s'] = max(60, int(numeric or 300))
                elif key == 'forecast_arrivals':
                    try:
                        numeric = int(value) if value is not None else 0
                    except Exception:
                        numeric = 0
                    item['forecast_arrivals'] = max(int(item.get('forecast_arrivals') or 0), max(0, numeric))
                elif key == 'forecast_arrivals_per_hour':
                    try:
                        numeric = float(value) if value is not None else 0.0
                    except Exception:
                        numeric = 0.0
                    item['forecast_arrivals_per_hour'] = max(float(item.get('forecast_arrivals_per_hour') or 0.0), max(0.0, numeric))
                elif key == 'forecast_window_s':
                    try:
                        numeric = int(value) if value is not None else int(queue_capacity_policy.get('forecast_window_s') or 1800)
                    except Exception:
                        numeric = int(queue_capacity_policy.get('forecast_window_s') or 1800)
                    item['forecast_window_s'] = max(300, int(numeric or 1800))
                elif key == 'reservation_enabled':
                    item['reservation_enabled'] = bool(item.get('reservation_enabled')) or bool(value)
                elif key in {'reserved_for_queue_types', 'reserved_for_severities', 'leased_for_queue_types', 'leased_for_severities', 'admission_exempt_queue_types', 'admission_exempt_severities'}:
                    lower_keys = {'reserved_for_severities', 'leased_for_severities', 'admission_exempt_severities'}
                    existing = [str(v).strip().lower() if key in lower_keys else str(v).strip() for v in list(item.get(key) or []) if str(v).strip()]
                    incoming = [str(v).strip().lower() if key in lower_keys else str(v).strip() for v in list(value or []) if str(v).strip()]
                    item[key] = list(dict.fromkeys(existing + incoming))
                elif key in {'queue_family_id', 'queue_family_label'}:
                    candidate = str(value or '').strip()
                    if candidate:
                        existing = str(item.get(key) or '').strip()
                        item[key] = existing or candidate
                elif key in {'admission_control_enabled', 'overload_governance_enabled'}:
                    item[key] = bool(item.get(key)) or bool(value)
                elif key in {'overload_projected_load_ratio_threshold'}:
                    try:
                        numeric = float(value) if value is not None else 0.0
                    except Exception:
                        numeric = 0.0
                    item[key] = max(float(item.get(key) or 0.0), max(0.0, numeric))
                elif key in {'overload_projected_wait_time_threshold_s'}:
                    try:
                        numeric = int(value) if value is not None else 0
                    except Exception:
                        numeric = 0
                    item[key] = max(int(item.get(key) or 0), max(0, numeric))
                elif key == 'temporary_holds':
                    existing = [dict(v or {}) for v in list(item.get('temporary_holds') or []) if isinstance(v, dict)]
                    incoming = [dict(v or {}) for v in list(value or []) if isinstance(v, dict)]
                    merged = {str(v.get('hold_id') or ''): v for v in existing if str(v.get('hold_id') or '')}
                    for hold in incoming:
                        hold_id = str(hold.get('hold_id') or '')
                        if hold_id:
                            merged[hold_id] = hold
                        else:
                            existing.append(hold)
                    item['temporary_holds'] = list(merged.values()) + [hold for hold in existing if not str(hold.get('hold_id') or '')]
                elif value and not item.get(key):
                    item[key] = value
            return item

        def _register_route(raw_route: dict[str, Any] | None) -> None:
            route = self._normalize_baseline_promotion_simulation_custody_route(dict(raw_route or {}), index=0, fallback_target_path=str(normalized_policy.get('target_path') or '/ui/?tab=operator'))
            queue_id = str(route.get('queue_id') or '').strip()
            if not queue_id:
                return
            _ensure_queue(
                queue_id,
                queue_label=str(route.get('queue_label') or queue_id),
                capacity=int(route.get('queue_capacity') or 0),
                hard_limit=bool(route.get('queue_hard_limit')),
                queue_type=str(route.get('queue_type') or ''),
                owner_role=str(route.get('owner_role') or ''),
                owner_id=str(route.get('owner_id') or ''),
                queue_family_id=str(route.get('queue_family_id') or route.get('queue_type') or ''),
                queue_family_label=str(route.get('queue_family_label') or route.get('queue_family_id') or route.get('queue_type') or ''),
                load_weight=float(route.get('load_weight') or 1.0),
                source_count=1,
            )

        def _register_policy(raw_policy: dict[str, Any] | None) -> None:
            candidate = self._normalize_baseline_promotion_simulation_custody_monitoring_policy(dict(raw_policy or {}))
            _register_route(candidate.get('default_route') or {})
            for route in list(candidate.get('routing_routes') or []):
                _register_route(route)
            for route in list(candidate.get('team_escalation_queues') or []):
                _register_route(route)
            _register_route(candidate.get('sla_breach_route') or {})
            for queue_payload in list(candidate.get('queue_capacities') or []):
                queue_data = dict(queue_payload or {})
                queue_id = str(queue_data.get('queue_id') or '').strip()
                if not queue_id:
                    continue
                _ensure_queue(
                    queue_id,
                    queue_label=str(queue_data.get('queue_label') or queue_id),
                    capacity=int(queue_data.get('capacity') or 0),
                    warning_capacity=int(queue_data.get('warning_capacity') or 0),
                    hard_limit=bool(queue_data.get('hard_limit')),
                    queue_type=str(queue_data.get('queue_type') or ''),
                    owner_role=str(queue_data.get('owner_role') or ''),
                    owner_id=str(queue_data.get('owner_id') or ''),
                    queue_family_id=str(queue_data.get('queue_family_id') or queue_data.get('family_id') or queue_data.get('family') or queue_data.get('queue_type') or ''),
                    queue_family_label=str(queue_data.get('queue_family_label') or queue_data.get('family_label') or queue_data.get('queue_family_id') or queue_data.get('family_id') or queue_data.get('family') or queue_data.get('queue_type') or ''),
                    load_weight=float(queue_data.get('load_weight') or 1.0),
                    reserved_capacity=int(queue_data.get('reserved_capacity') or 0),
                    reservation_enabled=bool(queue_data.get('reserved_capacity') or queue_data.get('reservation_enabled')),
                    reserved_for_queue_types=list(queue_data.get('reserved_for_queue_types') or []),
                    reserved_for_severities=list(queue_data.get('reserved_for_severities') or []),
                    leased_capacity=int(queue_data.get('leased_capacity') or 0),
                    lease_expires_at=queue_data.get('lease_expires_at'),
                    lease_reason=str(queue_data.get('lease_reason') or ''),
                    lease_holder=str(queue_data.get('lease_holder') or ''),
                    lease_id=str(queue_data.get('lease_id') or ''),
                    leased_for_queue_types=list(queue_data.get('leased_for_queue_types') or []),
                    leased_for_severities=list(queue_data.get('leased_for_severities') or []),
                    temporary_holds=list(queue_data.get('temporary_holds') or []),
                    expected_service_time_s=int(queue_data.get('expected_service_time_s') or queue_data.get('service_time_s') or queue_capacity_policy.get('expected_service_time_s') or 300),
                    forecast_arrivals=queue_data.get('forecast_arrivals'),
                    forecast_arrivals_per_hour=queue_data.get('forecast_arrivals_per_hour'),
                    forecast_window_s=queue_data.get('forecast_window_s') or queue_capacity_policy.get('forecast_window_s'),
                    admission_control_enabled=bool(queue_data.get('admission_control_enabled', queue_capacity_policy.get('admission_control_enabled'))),
                    admission_action=str(queue_data.get('admission_action') or queue_data.get('overload_action') or queue_capacity_policy.get('admission_default_action') or ''),
                    admission_exempt_severities=list(queue_data.get('admission_exempt_severities') or []),
                    admission_exempt_queue_types=list(queue_data.get('admission_exempt_queue_types') or []),
                    overload_governance_enabled=bool(queue_data.get('overload_governance_enabled', queue_capacity_policy.get('overload_governance_enabled'))),
                    overload_projected_load_ratio_threshold=queue_data.get('overload_projected_load_ratio_threshold') or queue_capacity_policy.get('overload_projected_load_ratio_threshold'),
                    overload_projected_wait_time_threshold_s=queue_data.get('overload_projected_wait_time_threshold_s') or queue_capacity_policy.get('overload_projected_wait_time_threshold_s'),
                    overload_action=str(queue_data.get('overload_action') or queue_data.get('admission_action') or queue_capacity_policy.get('overload_global_action') or queue_capacity_policy.get('admission_default_action') or ''),
                    source_count=1,
                )

        _register_policy(normalized_policy)
        releases = list(gw.audit.list_release_bundles(
            limit=500,
            kind='policy_baseline_promotion',
            tenant_id=scope_tenant,
            workspace_id=scope_workspace,
            environment=scope_environment,
        ) or [])
        for candidate_release in releases:
            if not self._is_baseline_promotion_release(candidate_release):
                continue
            candidate_policy = self._baseline_promotion_simulation_custody_monitoring_policy_for_release(candidate_release)
            _register_policy(candidate_policy)
            alerts = self._baseline_promotion_simulation_custody_alerts(candidate_release)
            active_alert = next((item for item in alerts if bool(item.get('active'))), None)
            if not active_alert:
                continue
            if exclude_alert_id and str(active_alert.get('alert_id') or '') == str(exclude_alert_id or ''):
                continue
            ownership = self._baseline_promotion_simulation_custody_ownership_projection(active_alert)
            routing = self._baseline_promotion_simulation_custody_routing_projection(active_alert)
            queue_id = str(ownership.get('queue_id') or routing.get('queue_id') or '').strip()
            if not queue_id:
                continue
            item = _ensure_queue(
                queue_id,
                queue_label=str(ownership.get('queue_label') or routing.get('queue_label') or queue_id),
                owner_role=str(ownership.get('owner_role') or routing.get('owner_role') or ''),
                owner_id=str(routing.get('owner_id') or ''),
                queue_family_id=str(routing.get('queue_family_id') or routing.get('queue_type') or ''),
                queue_family_label=str(routing.get('queue_family_label') or routing.get('queue_family_id') or routing.get('queue_type') or ''),
            )
            item['active_count'] = int(item.get('active_count') or 0) + 1
            item['active_alert_ids'] = list(item.get('active_alert_ids') or []) + [str(active_alert.get('alert_id') or '')]
            item['promotion_ids'] = list(item.get('promotion_ids') or []) + [str(candidate_release.get('release_id') or '')]
            alert_created_at = None
            try:
                alert_created_at = float(active_alert.get('created_at')) if active_alert.get('created_at') is not None else None
            except Exception:
                alert_created_at = None
            queue_assigned_at = None
            try:
                queue_assigned_at = float(routing.get('updated_at')) if routing.get('updated_at') is not None else None
            except Exception:
                queue_assigned_at = None
            queue_age_s = max(0, int(now_ts - (queue_assigned_at if queue_assigned_at is not None else (alert_created_at if alert_created_at is not None else now_ts))))
            previous_oldest_age = int(item.get('oldest_alert_age_s') or 0)
            item['oldest_alert_age_s'] = max(previous_oldest_age, queue_age_s)
            if int(item.get('newest_alert_age_s') or 0) <= 0:
                item['newest_alert_age_s'] = queue_age_s
            else:
                item['newest_alert_age_s'] = min(int(item.get('newest_alert_age_s') or 0), queue_age_s)
            if aging_enabled and aging_after_s > 0 and queue_age_s >= aging_after_s:
                item['aged_alert_count'] = int(item.get('aged_alert_count') or 0) + 1
            if starvation_prevention_enabled and starvation_after_s > 0 and queue_age_s >= starvation_after_s:
                item['starving_alert_count'] = int(item.get('starving_alert_count') or 0) + 1
            if str(routing.get('source') or '') == 'sla_breach_routing':
                item['sla_rerouted_count'] = int(item.get('sla_rerouted_count') or 0) + 1
        queue_items = []
        saturated_count = 0
        over_capacity_count = 0
        total_active = 0
        aged_alert_count = 0
        starving_alert_count = 0
        starving_queue_count = 0
        oldest_alert_age_s = 0
        leased_queue_count = 0
        active_leased_capacity = 0
        expired_lease_count = 0
        hold_queue_count = 0
        active_temporary_hold_count = 0
        active_temporary_hold_capacity = 0
        expired_hold_count = 0
        forecasted_surge_queue_count = 0
        overloaded_queue_count = 0
        admission_blocked_queue_count = 0
        hottest_projected_load_ratio = 0.0
        hottest_projected_queue_id = ''
        hottest_projected_queue_label = ''
        queue_family_ids: set[str] = set()
        family_queue_counts: dict[str, int] = {}
        largest_queue_family_id = ''
        largest_queue_family_label = ''
        largest_queue_family_size = 0
        policy_reserved_capacity = max(0, int(queue_capacity_policy.get('default_reserved_capacity') or 0))
        policy_reservation_enabled = bool(queue_capacity_policy.get('reservation_enabled'))
        policy_reserved_for_queue_types = [str(item).strip() for item in list(queue_capacity_policy.get('reserved_for_queue_types') or []) if str(item).strip()]
        policy_reserved_for_severities = [str(item).strip().lower() for item in list(queue_capacity_policy.get('reserved_for_severities') or []) if str(item).strip()]
        for queue_id, item in queues.items():
            capacity = max(0, int(item.get('capacity') or default_capacity or 0))
            warning_capacity = max(0, int(item.get('warning_capacity') or default_warning or (capacity - 1 if capacity > 0 else 0)))
            active_count = int(item.get('active_count') or 0)
            configured_reserved_capacity = int(item.get('reserved_capacity') or 0)
            reservation_enabled = bool(item.get('reservation_enabled')) or bool(policy_reservation_enabled and configured_reserved_capacity <= 0 and policy_reserved_capacity > 0)
            reserved_capacity = max(0, min(capacity, configured_reserved_capacity or (policy_reserved_capacity if reservation_enabled else 0)))
            raw_lease_expires_at = item.get('lease_expires_at')
            try:
                lease_expires_at = float(raw_lease_expires_at) if raw_lease_expires_at is not None else None
            except Exception:
                lease_expires_at = None
            lease_expired = bool((int(item.get('leased_capacity') or default_leased_capacity or 0) > 0) and lease_expires_at is not None and lease_expires_at <= now_ts)
            lease_active = bool(reservation_lease_enabled and (int(item.get('leased_capacity') or default_leased_capacity or 0) > 0) and (lease_expires_at is None or lease_expires_at > now_ts))
            leased_capacity = max(0, min(capacity, int(item.get('leased_capacity') or (default_leased_capacity if lease_active else 0) or 0))) if lease_active else 0
            normalized_holds = [
                self._baseline_promotion_simulation_custody_normalize_temporary_hold(dict(hold or {}), default_ttl_s=default_hold_ttl_s, now_ts=now_ts, index=index + 1)
                for index, hold in enumerate(list(item.get('temporary_holds') or []))
                if isinstance(hold, dict)
            ]
            active_holds = [hold for hold in normalized_holds if bool(hold.get('active'))]
            expired_holds = [hold for hold in normalized_holds if bool(hold.get('expired'))]
            hold_capacity = max(0, sum(int(hold.get('capacity') or 0) for hold in active_holds)) if temporary_holds_enabled else 0
            general_capacity = max(0, capacity - reserved_capacity - leased_capacity - hold_capacity)
            tier_state = self._baseline_promotion_simulation_custody_capacity_tier_state(
                active_count=active_count,
                capacity=capacity,
                general_capacity=general_capacity,
                reserved_capacity=reserved_capacity,
                leased_capacity=leased_capacity,
                hold_capacity=hold_capacity,
            )
            general_available = tier_state.get('general_available')
            reserved_available = tier_state.get('reserved_available')
            lease_available = tier_state.get('lease_available')
            hold_available = tier_state.get('hold_available')
            available = (max(0, capacity - active_count) if capacity > 0 else None)
            load_ratio = (float(active_count) / float(capacity) if capacity > 0 else 0.0)
            at_capacity = bool(capacity > 0 and active_count >= capacity)
            over_capacity = bool(capacity > 0 and active_count > capacity)
            warning = bool(capacity > 0 and active_count >= max(1, warning_capacity))
            oldest_queue_age_s = max(0, int(item.get('oldest_alert_age_s') or 0))
            queue_aged_alert_count = int(item.get('aged_alert_count') or 0)
            queue_starving_alert_count = int(item.get('starving_alert_count') or 0)
            queue_forecast_window_s = max(300, int(item.get('forecast_window_s') or queue_capacity_policy.get('forecast_window_s') or 1800))
            forecast_arrivals_count = max(0, int(item.get('forecast_arrivals') or 0))
            try:
                forecast_arrivals_per_hour = max(0.0, float(item.get('forecast_arrivals_per_hour') or 0.0))
            except Exception:
                forecast_arrivals_per_hour = 0.0
            if forecast_arrivals_count <= 0 and forecast_arrivals_per_hour > 0.0:
                forecast_arrivals_count = max(0, int(round(forecast_arrivals_per_hour * (float(queue_forecast_window_s) / 3600.0))))
            forecast_service_capacity = max(0, int((float(max(capacity, 0)) * float(queue_forecast_window_s)) / float(max(60, int(item.get('expected_service_time_s') or queue_capacity_policy.get('expected_service_time_s') or 300))))) if capacity > 0 else 0
            projected_active_count = max(0, int(active_count + forecast_arrivals_count - forecast_service_capacity))
            projected_load_ratio = (float(projected_active_count) / float(capacity) if capacity > 0 else 0.0)
            projected_wait_time_s = int(round((float(max(projected_active_count, 0)) * float(max(60, int(item.get('expected_service_time_s') or queue_capacity_policy.get('expected_service_time_s') or 300)))) / float(max(capacity, 1)))) if capacity > 0 else 0
            forecasted_over_capacity = bool(capacity > 0 and projected_active_count > capacity)
            surge_predicted = bool(queue_capacity_policy.get('predictive_forecasting_enabled') and (forecasted_over_capacity or projected_load_ratio >= float(queue_capacity_policy.get('surge_load_ratio_threshold') or 0.85)))
            overload_projected_load_ratio_threshold = max(0.25, float(item.get('overload_projected_load_ratio_threshold') or queue_capacity_policy.get('overload_projected_load_ratio_threshold') or queue_capacity_policy.get('surge_load_ratio_threshold') or 0.95))
            overload_projected_wait_time_threshold_s = max(0, int(item.get('overload_projected_wait_time_threshold_s') or queue_capacity_policy.get('overload_projected_wait_time_threshold_s') or max(300, int(item.get('expected_service_time_s') or queue_capacity_policy.get('expected_service_time_s') or 300) * 2)))
            overload_predicted = bool(
                (capacity > 0 and active_count >= capacity and bool(item.get('hard_limit')))
                or forecasted_over_capacity
                or projected_load_ratio >= overload_projected_load_ratio_threshold
                or (overload_projected_wait_time_threshold_s > 0 and projected_wait_time_s >= overload_projected_wait_time_threshold_s)
            )
            admission_control_enabled = bool(item.get('admission_control_enabled', queue_capacity_policy.get('admission_control_enabled')))
            overload_governance_enabled = bool(item.get('overload_governance_enabled', queue_capacity_policy.get('overload_governance_enabled')))
            admission_action = str(item.get('admission_action') or queue_capacity_policy.get('admission_default_action') or 'defer').strip() or 'defer'
            overload_action = str(item.get('overload_action') or admission_action or queue_capacity_policy.get('overload_global_action') or 'defer').strip() or 'defer'
            queue_family_id = str(item.get('queue_family_id') or queue_capacity_policy.get('default_queue_family') or item.get('queue_type') or '').strip()
            queue_family_label = str(item.get('queue_family_label') or queue_family_id or item.get('queue_label') or item.get('queue_type') or '').strip()
            record = {
                **item,
                'capacity': capacity,
                'warning_capacity': warning_capacity,
                'queue_family_id': queue_family_id,
                'queue_family_label': queue_family_label,
                'queue_family_enabled': bool(queue_capacity_policy.get('queue_families_enabled')),
                'active_count': active_count,
                'available': available,
                'load_ratio': load_ratio,
                'warning': warning,
                'at_capacity': at_capacity,
                'over_capacity': over_capacity,
                'reservation_enabled': reservation_enabled,
                'reserved_capacity': reserved_capacity,
                'general_capacity': general_capacity,
                'general_available': general_available,
                'reserved_available': reserved_available,
                'lease_active': lease_active,
                'lease_expired': lease_expired,
                'leased_capacity': leased_capacity,
                'lease_available': lease_available,
                'lease_expires_at': lease_expires_at,
                'lease_reason': str(item.get('lease_reason') or ''),
                'lease_holder': str(item.get('lease_holder') or ''),
                'lease_id': str(item.get('lease_id') or ''),
                'leased_for_queue_types': list(item.get('leased_for_queue_types') or []),
                'leased_for_severities': list(item.get('leased_for_severities') or []),
                'temporary_hold_count': len(active_holds),
                'temporary_hold_capacity': hold_capacity,
                'temporary_hold_available': hold_available,
                'temporary_hold_ids': [str(hold.get('hold_id') or '') for hold in active_holds if str(hold.get('hold_id') or '')],
                'temporary_hold_reasons': [str(hold.get('reason') or '') for hold in active_holds if str(hold.get('reason') or '')],
                'temporary_holds': active_holds,
                'expired_temporary_hold_count': len(expired_holds),
                'expired_temporary_hold_ids': [str(hold.get('hold_id') or '') for hold in expired_holds if str(hold.get('hold_id') or '')],
                'reserved_for_queue_types': list(item.get('reserved_for_queue_types') or policy_reserved_for_queue_types),
                'reserved_for_severities': list(item.get('reserved_for_severities') or policy_reserved_for_severities),
                'expected_service_time_s': max(60, int(item.get('expected_service_time_s') or queue_capacity_policy.get('expected_service_time_s') or 300)),
                'promotion_ids': sorted({str(x) for x in list(item.get('promotion_ids') or []) if str(x)}),
                'active_alert_ids': sorted({str(x) for x in list(item.get('active_alert_ids') or []) if str(x)}),
                'oldest_alert_age_s': oldest_queue_age_s,
                'newest_alert_age_s': max(0, int(item.get('newest_alert_age_s') or 0)),
                'aged_alert_count': queue_aged_alert_count,
                'starving_alert_count': queue_starving_alert_count,
                'aging_enabled': aging_enabled,
                'starvation_prevention_enabled': starvation_prevention_enabled,
                'starving': bool(queue_starving_alert_count > 0),
                'forecast_window_s': queue_forecast_window_s,
                'forecast_arrivals_count': forecast_arrivals_count,
                'forecast_arrivals_per_hour': forecast_arrivals_per_hour,
                'forecast_service_capacity': forecast_service_capacity,
                'projected_active_count': projected_active_count,
                'projected_load_ratio': projected_load_ratio,
                'projected_wait_time_s': projected_wait_time_s,
                'forecasted_over_capacity': forecasted_over_capacity,
                'surge_predicted': surge_predicted,
                'admission_control_enabled': admission_control_enabled,
                'admission_action': admission_action,
                'admission_exempt_severities': list(item.get('admission_exempt_severities') or queue_capacity_policy.get('admission_exempt_severities') or []),
                'admission_exempt_queue_types': list(item.get('admission_exempt_queue_types') or queue_capacity_policy.get('admission_exempt_queue_types') or []),
                'overload_governance_enabled': overload_governance_enabled,
                'overload_action': overload_action,
                'overload_projected_load_ratio_threshold': overload_projected_load_ratio_threshold,
                'overload_projected_wait_time_threshold_s': overload_projected_wait_time_threshold_s,
                'overload_predicted': overload_predicted,
                'admission_blocked': bool(admission_control_enabled and overload_governance_enabled and overload_predicted and overload_action in {'defer', 'manual_gate', 'park', 'reject'}),
            }
            if queue_family_id:
                queue_family_ids.add(queue_family_id)
                family_queue_counts[queue_family_id] = family_queue_counts.get(queue_family_id, 0) + 1
                if family_queue_counts[queue_family_id] >= largest_queue_family_size:
                    largest_queue_family_size = family_queue_counts[queue_family_id]
                    largest_queue_family_id = queue_family_id
                    largest_queue_family_label = queue_family_label or queue_family_id
            if at_capacity:
                saturated_count += 1
            if over_capacity:
                over_capacity_count += 1
            if queue_starving_alert_count > 0:
                starving_queue_count += 1
            if surge_predicted:
                forecasted_surge_queue_count += 1
            if overload_predicted:
                overloaded_queue_count += 1
            if bool(record.get('admission_blocked')):
                admission_blocked_queue_count += 1
            if projected_load_ratio >= hottest_projected_load_ratio:
                hottest_projected_load_ratio = projected_load_ratio
                hottest_projected_queue_id = str(record.get('queue_id') or '')
                hottest_projected_queue_label = str(record.get('queue_label') or '')
            if lease_active:
                leased_queue_count += 1
                active_leased_capacity += leased_capacity
            if lease_expired and lease_reclaim_enabled:
                expired_lease_count += 1
            if active_holds:
                hold_queue_count += 1
                active_temporary_hold_count += len(active_holds)
                active_temporary_hold_capacity += hold_capacity
            expired_hold_count += len(expired_holds)
            aged_alert_count += queue_aged_alert_count
            starving_alert_count += queue_starving_alert_count
            oldest_alert_age_s = max(oldest_alert_age_s, oldest_queue_age_s)
            total_active += active_count
            queue_items.append(record)
        queue_items.sort(key=lambda item: (bool(item.get('at_capacity')), float(item.get('load_ratio') or 0.0), int(item.get('active_count') or 0), str(item.get('queue_id') or '')), reverse=True)
        hottest = dict(queue_items[0] or {}) if queue_items else {}
        return {
            'policy': queue_capacity_policy,
            'queues': {str(item.get('queue_id') or ''): item for item in queue_items},
            'items': queue_items,
            'summary': {
                'queue_count': len(queue_items),
                'active_alert_count': total_active,
                'saturated_count': saturated_count,
                'over_capacity_count': over_capacity_count,
                'aged_alert_count': aged_alert_count,
                'starving_alert_count': starving_alert_count,
                'starving_queue_count': starving_queue_count,
                'leased_queue_count': leased_queue_count,
                'active_leased_capacity': active_leased_capacity,
                'expired_lease_count': expired_lease_count,
                'hold_queue_count': hold_queue_count,
                'active_temporary_hold_count': active_temporary_hold_count,
                'active_temporary_hold_capacity': active_temporary_hold_capacity,
                'expired_hold_count': expired_hold_count,
                'forecasted_surge_queue_count': forecasted_surge_queue_count,
                'overloaded_queue_count': overloaded_queue_count,
                'admission_blocked_queue_count': admission_blocked_queue_count,
                'forecast_window_s': max(300, int(queue_capacity_policy.get('forecast_window_s') or 1800)),
                'queue_family_count': len(queue_family_ids),
                'family_queue_counts': dict(family_queue_counts),
                'largest_queue_family_id': largest_queue_family_id,
                'largest_queue_family_label': largest_queue_family_label,
                'largest_queue_family_size': largest_queue_family_size,
                'hottest_projected_queue_id': hottest_projected_queue_id,
                'hottest_projected_queue_label': hottest_projected_queue_label,
                'hottest_projected_load_ratio': float(hottest_projected_load_ratio or 0.0),
                'oldest_alert_age_s': oldest_alert_age_s,
                'hottest_queue_id': str(hottest.get('queue_id') or ''),
                'hottest_queue_label': str(hottest.get('queue_label') or ''),
                'hottest_load_ratio': float(hottest.get('load_ratio') or 0.0),
            },
        }

