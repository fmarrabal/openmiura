"""baseline_rollout_support._alerts_a_mixin

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


class _OpenClawBaselineRolloutSupportAlertsAMixin:
    """Sub-mixin: alerts a methods on OpenClawBaselineRolloutSupportMixin."""

    def simulate_runtime_alert_governance_baseline_promotion_simulation_custody_routing(
        self,
        gw,
        *,
        promotion_id: str,
        actor: str,
        alert_id: str | None = None,
        policy_overrides: dict[str, Any] | None = None,
        comparison_policies: list[dict[str, Any]] | None = None,
        alert_overrides: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        detail = self.get_runtime_alert_governance_baseline_promotion(
            gw,
            promotion_id=promotion_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        if not detail.get('ok'):
            return detail
        release = dict(detail.get('release') or {})
        monitoring = dict(detail.get('simulation_custody_monitoring') or {})
        alert_items = [dict(item or {}) for item in list(((monitoring.get('alerts') or {}).get('items')) or []) if isinstance(item, dict)]
        target = {}
        normalized_alert_id = str(alert_id or '').strip()
        if normalized_alert_id:
            target = next((item for item in alert_items if str(item.get('alert_id') or '').strip() == normalized_alert_id), {})
        if not target:
            target = next((item for item in alert_items if bool(item.get('active'))), {})
        if not target:
            target = dict(alert_items[0] or {}) if alert_items else {}
        if not target:
            synthetic_route = dict((dict(alert_overrides or {}).get('routing') or {}))
            if not synthetic_route:
                default_route = dict((dict(monitoring.get('default_route') or self._baseline_promotion_simulation_custody_monitoring_policy_for_release(release).get('default_route') or {})))
                synthetic_route = {
                    'route_id': str(default_route.get('route_id') or ''),
                    'queue_id': str(default_route.get('queue_id') or ''),
                    'queue_label': str(default_route.get('queue_label') or ''),
                    'queue_family_id': str(default_route.get('queue_family_id') or ''),
                    'owner_role': str(default_route.get('owner_role') or ''),
                    'selection_reason': 'synthetic_replay',
                    'source': 'synthetic_replay',
                }
            target = {
                'alert_id': normalized_alert_id or 'simulation-custody-routing-replay',
                'kind': 'routing_replay',
                'active': False,
                'status': 'simulated',
                'created_at': time.time(),
                'created_by': str(actor or 'operator'),
                'severity': str((dict(alert_overrides or {}).get('severity') or '')).strip() or 'warning',
                'escalation_level': int(dict(alert_overrides or {}).get('escalation_level') or 0),
                'routing': synthetic_route,
                'ownership': {'queue_id': str(synthetic_route.get('queue_id') or ''), 'queue_label': str(synthetic_route.get('queue_label') or ''), 'owner_role': str(synthetic_route.get('owner_role') or '')},
                'route_history': [
                    {
                        'at': time.time(),
                        'route_id': str(synthetic_route.get('route_id') or ''),
                        'queue_id': str(synthetic_route.get('queue_id') or ''),
                        'queue_family_id': str(synthetic_route.get('queue_family_id') or ''),
                        'selection_reason': str(synthetic_route.get('selection_reason') or 'synthetic_replay'),
                        'source': str(synthetic_route.get('source') or 'synthetic_replay'),
                    }
                ] if synthetic_route else [],
            }
        if alert_overrides:
            target = self._baseline_promotion_simulation_custody_merge_policy_overrides(target, dict(alert_overrides or {}))
        base_policy = self._baseline_promotion_simulation_custody_merge_policy_overrides(
            dict(monitoring.get('policy') or self._baseline_promotion_simulation_custody_monitoring_policy_for_release(release)),
            dict(policy_overrides or {}),
        )
        target_alert_id = str(target.get('alert_id') or '')
        current_route = self._baseline_promotion_simulation_custody_routing_projection(target)
        base_queue_state = self._baseline_promotion_simulation_custody_queue_capacity_state(
            gw,
            release=release,
            policy=base_policy,
            exclude_alert_id=target_alert_id or None,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        replay = self._baseline_promotion_simulation_custody_route_replay(
            alert=target,
            policy=base_policy,
            queue_state=base_queue_state,
            current_route=current_route,
            comparison_policies=comparison_policies,
        )
        return {
            'ok': True,
            'promotion_id': str(release.get('release_id') or promotion_id),
            'alert_id': str(target.get('alert_id') or ''),
            'alert': target,
            'routing_replay': replay,
            'scope': detail.get('scope'),
        }

    def _baseline_promotion_simulation_custody_route_for_alert(
        self,
        policy: dict[str, Any] | None,
        alert: dict[str, Any] | None,
        *,
        preferred_route_id: str | None = None,
        queue_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_policy = self._normalize_baseline_promotion_simulation_custody_monitoring_policy(dict(policy or {}))
        fallback_target_path = str(normalized_policy.get('target_path') or '/ui/?tab=operator').strip() or '/ui/?tab=operator'
        routes = [dict(item) for item in list(normalized_policy.get('routing_routes') or [])]
        default_route = dict(normalized_policy.get('default_route') or {})
        manual_routing = dict((dict(alert or {}).get('routing') or {}))
        preferred = str(preferred_route_id or '').strip()
        if not preferred and bool(manual_routing.get('manual_override')):
            if any(str(manual_routing.get(key) or '').strip() for key in ('route_id', 'queue_id', 'owner_role', 'owner_id')):
                manual_route = self._normalize_baseline_promotion_simulation_custody_route({
                    'route_id': manual_routing.get('route_id') or 'manual-route',
                    'label': manual_routing.get('route_label') or manual_routing.get('label') or 'Manual route',
                    'queue_id': manual_routing.get('queue_id') or '',
                    'queue_label': manual_routing.get('queue_label') or '',
                    'owner_role': manual_routing.get('owner_role') or '',
                    'owner_id': manual_routing.get('owner_id') or '',
                    'target_path': manual_routing.get('target_path') or normalized_policy.get('target_path') or fallback_target_path,
                    'severity': manual_routing.get('severity') or '',
                    'queue_type': manual_routing.get('queue_type') or '',
                }, index=0, fallback_target_path=normalized_policy.get('target_path') or fallback_target_path)
                return self._select_baseline_promotion_simulation_custody_route_by_load(
                    routes=[manual_route],
                    queue_state=queue_state,
                    current_queue_id=str(manual_routing.get('queue_id') or ''),
                    prefer_lowest_load=False,
                    alert=alert,
                    policy=normalized_policy,
                )
        if preferred:
            explicit = next((item for item in routes if str(item.get('route_id') or '') == preferred), None)
            if explicit is not None:
                return self._select_baseline_promotion_simulation_custody_route_by_load(
                    routes=[explicit],
                    queue_state=queue_state,
                    current_queue_id=str(manual_routing.get('queue_id') or ''),
                    prefer_lowest_load=bool(normalized_policy.get('load_aware_routing_enabled')),
                    alert=alert,
                    policy=normalized_policy,
                )
            if str(default_route.get('route_id') or '') == preferred:
                return self._select_baseline_promotion_simulation_custody_route_by_load(
                    routes=[default_route],
                    queue_state=queue_state,
                    current_queue_id=str(manual_routing.get('queue_id') or ''),
                    prefer_lowest_load=bool(normalized_policy.get('load_aware_routing_enabled')),
                    alert=alert,
                    policy=normalized_policy,
                )
        level = max(0, int((dict(alert or {}).get('escalation_level') or 0)))
        severity = str((dict(alert or {}).get('severity') or '')).strip().lower()
        matching = []
        for route in routes:
            min_level = max(0, int(route.get('min_escalation_level') or 0))
            max_level = route.get('max_escalation_level')
            if level < min_level:
                continue
            if max_level is not None and level > int(max_level or 0):
                continue
            route_severity = str(route.get('severity') or '').strip().lower()
            if route_severity and severity and route_severity != severity:
                continue
            matching.append(route)
        candidates = matching or ([default_route] if any(default_route.get(key) for key in ('route_id', 'queue_id', 'owner_role', 'owner_id')) else [])
        if candidates:
            return self._select_baseline_promotion_simulation_custody_route_by_load(
                routes=candidates,
                queue_state=queue_state,
                current_queue_id=str(manual_routing.get('queue_id') or ''),
                prefer_lowest_load=bool(normalized_policy.get('load_aware_routing_enabled', False)),
                alert=alert,
                policy=normalized_policy,
            )
        return {}

    def _baseline_promotion_simulation_custody_sla_route_for_alert(
        self,
        policy: dict[str, Any] | None,
        alert: dict[str, Any] | None,
        sla: dict[str, Any] | None,
        *,
        breached_targets: list[str] | None = None,
        queue_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_policy = self._normalize_baseline_promotion_simulation_custody_monitoring_policy(dict(policy or {}))
        if not bool(normalized_policy.get('auto_reroute_on_sla_breach')):
            return {}
        normalized_targets = [str(item).strip() for item in list(breached_targets or (dict(sla or {}).get('breached_targets') or [])) if str(item).strip()]
        level = max(0, int((dict(alert or {}).get('escalation_level') or 0)))
        severity = str(((normalized_policy.get('sla_policy') or {}).get('severity') or dict(alert or {}).get('severity') or '')).strip().lower()
        candidates = []
        for raw_route in list(normalized_policy.get('team_escalation_queues') or []):
            route = self._normalize_baseline_promotion_simulation_custody_route(dict(raw_route or {}), index=0, fallback_target_path=str((normalized_policy.get('sla_policy') or {}).get('target_path') or normalized_policy.get('target_path') or '/ui/?tab=operator'))
            route_targets = [str(item).strip() for item in list(route.get('breach_targets') or []) if str(item).strip()]
            if route_targets and normalized_targets and not set(route_targets).intersection(normalized_targets):
                continue
            min_level = max(0, int(route.get('min_escalation_level') or 0))
            max_level = route.get('max_escalation_level')
            if level < min_level:
                continue
            if max_level is not None and level > int(max_level or 0):
                continue
            route_severity = str(route.get('severity') or '').strip().lower()
            if route_severity and severity and route_severity != severity:
                continue
            candidates.append(route)
        if candidates:
            candidates.sort(key=lambda item: (len(list(item.get('breach_targets') or [])), int(item.get('min_escalation_level') or 0), str(item.get('route_id') or '')), reverse=True)
            return self._select_baseline_promotion_simulation_custody_route_by_load(
                routes=candidates,
                queue_state=queue_state,
                current_queue_id=str(((alert or {}).get('routing') or {}).get('queue_id') or ''),
                prefer_lowest_load=bool(normalized_policy.get('load_aware_routing_enabled', False)),
                alert=alert,
                policy=normalized_policy,
            )
        fallback_route = dict(normalized_policy.get('sla_breach_route') or {})
        if fallback_route:
            fallback_targets = [str(item).strip() for item in list(fallback_route.get('breach_targets') or []) if str(item).strip()]
            if not fallback_targets or not normalized_targets or set(fallback_targets).intersection(normalized_targets):
                return self._select_baseline_promotion_simulation_custody_route_by_load(
                    routes=[fallback_route],
                    queue_state=queue_state,
                    current_queue_id=str(((alert or {}).get('routing') or {}).get('queue_id') or ''),
                    prefer_lowest_load=bool(normalized_policy.get('load_aware_routing_enabled', False)),
                    alert=alert,
                    policy=normalized_policy,
                )
        return {}

    def _apply_baseline_promotion_simulation_custody_route_to_alert(
        self,
        alert: dict[str, Any] | None,
        *,
        route: dict[str, Any] | None,
        actor: str,
        auto_assign: bool = False,
        preserve_owner: bool = True,
        source: str = 'routing_policy',
        manual_override: bool = False,
    ) -> tuple[dict[str, Any], bool]:
        updated = dict(alert or {})
        normalized_route = self._normalize_baseline_promotion_simulation_custody_route(dict(route or {}), index=0)
        ownership = dict(updated.get('ownership') or {})
        routing = dict(updated.get('routing') or {})
        previous_key = (
            str(routing.get('route_id') or ''),
            str(routing.get('queue_id') or ''),
            str(routing.get('owner_role') or ''),
            str(routing.get('owner_id') or ''),
            str(routing.get('target_path') or ''),
        )
        now_ts = time.time()
        if normalized_route:
            routing.update({
                'route_id': str(normalized_route.get('route_id') or ''),
                'route_label': str(normalized_route.get('label') or ''),
                'queue_id': str(normalized_route.get('queue_id') or ''),
                'queue_label': str(normalized_route.get('queue_label') or ''),
                'owner_role': str(normalized_route.get('owner_role') or ''),
                'owner_id': str(normalized_route.get('owner_id') or ''),
                'target_path': str(normalized_route.get('target_path') or ''),
                'severity': str(normalized_route.get('severity') or ''),
                'updated_at': now_ts,
                'updated_by': str(actor or 'system'),
                'source': str(source or 'routing_policy'),
                'manual_override': bool(manual_override),
                'load_aware': bool(normalized_route.get('load_aware')),
                'selection_reason': str(normalized_route.get('selection_reason') or ''),
                'queue_active_count': int(normalized_route.get('queue_active_count') or 0),
                'queue_capacity': int(normalized_route.get('queue_capacity') or 0),
                'queue_available': normalized_route.get('queue_available'),
                'queue_load_ratio': float(normalized_route.get('queue_load_ratio') or 0.0),
                'queue_at_capacity': bool(normalized_route.get('queue_at_capacity')),
                'queue_over_capacity': bool(normalized_route.get('queue_over_capacity')),
                'queue_warning': bool(normalized_route.get('queue_warning')),
                'reservation_enabled': bool(normalized_route.get('reservation_enabled')),
                'reserved_capacity': int(normalized_route.get('reserved_capacity') or 0),
                'general_capacity': int(normalized_route.get('general_capacity') or 0),
                'general_available': normalized_route.get('general_available'),
                'reserved_available': normalized_route.get('reserved_available'),
                'reservation_eligible': bool(normalized_route.get('reservation_eligible')),
                'reservation_applied': bool(normalized_route.get('reservation_applied')),
                'lease_active': bool(normalized_route.get('lease_active')),
                'lease_expired': bool(normalized_route.get('lease_expired')),
                'leased_capacity': int(normalized_route.get('leased_capacity') or 0),
                'lease_available': normalized_route.get('lease_available'),
                'lease_expires_at': normalized_route.get('lease_expires_at'),
                'lease_reason': str(normalized_route.get('lease_reason') or ''),
                'lease_holder': str(normalized_route.get('lease_holder') or ''),
                'lease_id': str(normalized_route.get('lease_id') or ''),
                'lease_eligible': bool(normalized_route.get('lease_eligible')),
                'lease_applied': bool(normalized_route.get('lease_applied')),
                'starvation_lease_capacity_borrowed': bool(normalized_route.get('starvation_lease_capacity_borrowed')),
                'expedite_lease_capacity_borrowed': bool(normalized_route.get('expedite_lease_capacity_borrowed')),
                'temporary_hold_count': int(normalized_route.get('temporary_hold_count') or 0),
                'temporary_hold_capacity': int(normalized_route.get('temporary_hold_capacity') or 0),
                'temporary_hold_available': normalized_route.get('temporary_hold_available'),
                'temporary_hold_ids': [str(item) for item in list(normalized_route.get('temporary_hold_ids') or []) if str(item)],
                'temporary_hold_reasons': [str(item) for item in list(normalized_route.get('temporary_hold_reasons') or []) if str(item)],
                'temporary_hold_eligible': bool(normalized_route.get('temporary_hold_eligible')),
                'temporary_hold_applied': bool(normalized_route.get('temporary_hold_applied')),
                'starvation_temporary_hold_borrowed': bool(normalized_route.get('starvation_temporary_hold_borrowed')),
                'expedite_temporary_hold_borrowed': bool(normalized_route.get('expedite_temporary_hold_borrowed')),
                'expired_temporary_hold_count': int(normalized_route.get('expired_temporary_hold_count') or 0),
                'expired_temporary_hold_ids': [str(item) for item in list(normalized_route.get('expired_temporary_hold_ids') or []) if str(item)],
                'effective_capacity': int(normalized_route.get('effective_capacity') or 0),
                'alert_wait_age_s': int(normalized_route.get('alert_wait_age_s') or 0),
                'aging_applied': bool(normalized_route.get('aging_applied')),
                'starving': bool(normalized_route.get('starving')),
                'queue_oldest_alert_age_s': int(normalized_route.get('queue_oldest_alert_age_s') or 0),
                'queue_aged_alert_count': int(normalized_route.get('queue_aged_alert_count') or 0),
                'queue_starving_alert_count': int(normalized_route.get('queue_starving_alert_count') or 0),
                'starvation_reserved_capacity_borrowed': bool(normalized_route.get('starvation_reserved_capacity_borrowed')),
                'starvation_prevention_applied': bool(normalized_route.get('starvation_prevention_applied')),
                'starvation_prevention_reason': str(normalized_route.get('starvation_prevention_reason') or ''),
                'anti_thrashing_applied': bool(normalized_route.get('anti_thrashing_applied')),
                'anti_thrashing_reason': str(normalized_route.get('anti_thrashing_reason') or ''),
                'queue_family_id': str(normalized_route.get('queue_family_id') or normalized_route.get('queue_type') or ''),
                'queue_family_label': str(normalized_route.get('queue_family_label') or normalized_route.get('queue_family_id') or normalized_route.get('queue_type') or ''),
                'queue_family_enabled': bool(normalized_route.get('queue_family_enabled')),
                'queue_family_member_count': int(normalized_route.get('queue_family_member_count') or 0),
                'recent_queue_hop_count': int(normalized_route.get('recent_queue_hop_count') or 0),
                'recent_family_hop_count': int(normalized_route.get('recent_family_hop_count') or 0),
                'family_hysteresis_applied': bool(normalized_route.get('family_hysteresis_applied')),
                'family_hysteresis_reason': str(normalized_route.get('family_hysteresis_reason') or ''),
                'route_history_queue_ids': [str(item) for item in list(normalized_route.get('route_history_queue_ids') or []) if str(item)],
                'route_history_family_ids': [str(item) for item in list(normalized_route.get('route_history_family_ids') or []) if str(item)],
                'sla_deadline_target': str(normalized_route.get('sla_deadline_target') or ''),
                'time_to_breach_s': normalized_route.get('time_to_breach_s'),
                'predicted_wait_time_s': normalized_route.get('predicted_wait_time_s'),
                'predicted_sla_margin_s': normalized_route.get('predicted_sla_margin_s'),
                'predicted_sla_breach': bool(normalized_route.get('predicted_sla_breach')),
                'breach_risk_score': float(normalized_route.get('breach_risk_score') or 0.0),
                'breach_risk_level': str(normalized_route.get('breach_risk_level') or ''),
                'expected_service_time_s': int(normalized_route.get('expected_service_time_s') or 0),
                'expedite_eligible': bool(normalized_route.get('expedite_eligible')),
                'expedite_reserved_capacity_borrowed': bool(normalized_route.get('expedite_reserved_capacity_borrowed')),
                'expedite_applied': bool(normalized_route.get('expedite_applied')),
                'expedite_reason': str(normalized_route.get('expedite_reason') or ''),
            })
            if normalized_route.get('queue_id'):
                ownership['queue_id'] = str(normalized_route.get('queue_id') or '')
                ownership['queue_label'] = str(normalized_route.get('queue_label') or normalized_route.get('queue_id') or '')
            if normalized_route.get('owner_role'):
                ownership['owner_role'] = str(normalized_route.get('owner_role') or '')
            if not preserve_owner or not str(ownership.get('owner_id') or '').strip():
                owner_id = str(normalized_route.get('owner_id') or '').strip()
                if owner_id:
                    ownership['owner_id'] = owner_id
                    ownership['owner_display'] = str(normalized_route.get('owner_id') or owner_id)
                    ownership['assigned_at'] = ownership.get('assigned_at') or now_ts
                    ownership['assigned_by'] = ownership.get('assigned_by') or str(actor or 'system')
                    ownership['status'] = 'assigned'
                elif not str(ownership.get('owner_id') or '').strip():
                    ownership['status'] = 'queued' if str(ownership.get('queue_id') or ownership.get('owner_role') or '').strip() else 'unassigned'
            updated['routing'] = routing
        ownership.setdefault('status', 'queued' if str(ownership.get('queue_id') or ownership.get('owner_role') or '').strip() else ('assigned' if str(ownership.get('owner_id') or '').strip() else 'unassigned'))
        updated['ownership'] = ownership
        current_key = (
            str((updated.get('routing') or {}).get('route_id') or ''),
            str((updated.get('routing') or {}).get('queue_id') or ''),
            str((updated.get('routing') or {}).get('owner_role') or ''),
            str((updated.get('routing') or {}).get('owner_id') or ''),
            str((updated.get('routing') or {}).get('target_path') or ''),
        )
        route_changed = current_key != previous_key
        if route_changed:
            routing_state = dict(updated.get('routing') or {})
            history_limit = max(2, int(routing_state.get('family_history_limit') or 8))
            previous_history = [dict(item or {}) for item in list(routing_state.get('route_history') or []) if isinstance(item, dict)]
            history_entry = {
                'at': now_ts,
                'route_id': str(routing_state.get('route_id') or ''),
                'queue_id': str(routing_state.get('queue_id') or ''),
                'queue_family_id': str(routing_state.get('queue_family_id') or routing_state.get('queue_type') or ''),
                'selection_reason': str(routing_state.get('selection_reason') or ''),
                'source': str(routing_state.get('source') or ''),
            }
            previous_history.append(history_entry)
            routing_state['route_history'] = previous_history[-history_limit:]
            updated['routing'] = routing_state
        return updated, route_changed

    def _baseline_promotion_simulation_custody_alerts(self, release: dict[str, Any] | None) -> list[dict[str, Any]]:
        metadata = dict((release or {}).get('metadata') or {})
        promotion = dict(metadata.get('baseline_promotion') or {})
        alerts = [dict(item) for item in list(promotion.get('simulation_custody_alerts') or [])]
        policy = self._baseline_promotion_simulation_custody_monitoring_policy_for_release(release)
        now_ts = time.time()
        for item in alerts:
            item['status'] = self._baseline_promotion_simulation_custody_alert_status(item, now_ts=now_ts)
            item['ownership'] = self._baseline_promotion_simulation_custody_ownership_projection(item)
            item['routing'] = self._baseline_promotion_simulation_custody_routing_projection(item)
            item['handoff'] = self._baseline_promotion_simulation_custody_handoff_projection(item)
            item['sla'] = self._baseline_promotion_simulation_custody_sla_projection(item, policy, now_ts=now_ts)
            item['sla_state'] = dict(item.get('sla_state') or item['sla'])
            item['sla_routing_state'] = dict(item.get('sla_routing_state') or {})
        alerts.sort(key=lambda item: (float(item.get('created_at') or 0.0), str(item.get('alert_id') or '')), reverse=True)
        return alerts

    @staticmethod
    def _baseline_promotion_simulation_custody_alert_status(alert: dict[str, Any] | None, *, now_ts: float | None = None) -> str:
        payload = dict(alert or {})
        now_ts = float(now_ts if now_ts is not None else time.time())
        if bool(payload.get('active')):
            muted_until = payload.get('muted_until')
            try:
                muted_until_ts = float(muted_until) if muted_until is not None else None
            except Exception:
                muted_until_ts = None
            if muted_until_ts is not None and muted_until_ts > now_ts:
                return 'muted'
            if payload.get('acknowledged_at') is not None:
                return 'acknowledged'
            return str(payload.get('status') or 'open').strip() or 'open'
        if payload.get('recovered_at') is not None:
            return 'recovered'
        if payload.get('resolved_at') is not None or payload.get('cleared_at') is not None:
            return 'resolved'
        return str(payload.get('status') or 'closed').strip() or 'closed'

    def _baseline_promotion_simulation_custody_alerts_summary(self, alerts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        payload = [dict(item) for item in list(alerts or [])]
        active_count = sum(1 for item in payload if bool(item.get('active')))
        open_count = 0
        acknowledged_count = 0
        muted_count = 0
        resolved_count = 0
        recovered_count = 0
        suppressed_count = 0
        escalated_count = 0
        active_escalated_count = 0
        active_suppressed_count = 0
        critical_count = 0
        pending_escalation_count = 0
        owned_count = 0
        active_owned_count = 0
        claimed_count = 0
        active_claimed_count = 0
        unassigned_count = 0
        active_unowned_count = 0
        routed_count = 0
        queued_count = 0
        handoff_count = 0
        pending_handoff_count = 0
        active_handoff_pending_count = 0
        sla_breached_count = 0
        active_sla_breached_count = 0
        sla_warning_count = 0
        sla_rerouted_count = 0
        active_sla_rerouted_count = 0
        team_queue_alert_count = 0
        active_team_queue_alert_count = 0
        queue_at_capacity_count = 0
        active_queue_at_capacity_count = 0
        queue_over_capacity_count = 0
        active_queue_over_capacity_count = 0
        load_aware_routed_count = 0
        active_load_aware_routed_count = 0
        reservation_protected_alert_count = 0
        active_reservation_protected_alert_count = 0
        lease_protected_alert_count = 0
        active_lease_protected_alert_count = 0
        temporary_hold_protected_alert_count = 0
        active_temporary_hold_protected_alert_count = 0
        anti_thrashing_kept_alert_count = 0
        active_anti_thrashing_kept_alert_count = 0
        queue_family_alert_count = 0
        active_queue_family_alert_count = 0
        family_hysteresis_kept_alert_count = 0
        active_family_hysteresis_kept_alert_count = 0
        aging_alert_count = 0
        active_aging_alert_count = 0
        starving_alert_count = 0
        active_starving_alert_count = 0
        starvation_prevented_alert_count = 0
        active_starvation_prevented_alert_count = 0
        alerts_at_risk_count = 0
        active_alerts_at_risk_count = 0
        predicted_sla_breach_count = 0
        active_predicted_sla_breach_count = 0
        expedite_routed_alert_count = 0
        active_expedite_routed_alert_count = 0
        proactive_routed_alert_count = 0
        active_proactive_routed_alert_count = 0
        forecasted_surge_alert_count = 0
        active_forecasted_surge_alert_count = 0
        overload_governed_alert_count = 0
        active_overload_governed_alert_count = 0
        overload_blocked_alert_count = 0
        active_overload_blocked_alert_count = 0
        admission_deferred_alert_count = 0
        active_admission_deferred_alert_count = 0
        manual_gate_alert_count = 0
        active_manual_gate_alert_count = 0
        queue_counts: dict[str, int] = {}
        owner_counts: dict[str, int] = {}
        for item in payload:
            status = self._baseline_promotion_simulation_custody_alert_status(item)
            if status == 'muted':
                muted_count += 1
            elif status == 'acknowledged':
                acknowledged_count += 1
            elif status == 'recovered':
                recovered_count += 1
            elif status == 'resolved':
                resolved_count += 1
            elif status == 'open':
                open_count += 1
            suppression_state = dict(item.get('suppression_state') or {})
            suppressed = bool(suppression_state.get('suppressed')) or bool(item.get('notification_suppressed'))
            if suppressed:
                suppressed_count += 1
                if bool(item.get('active')):
                    active_suppressed_count += 1
            escalation_count = int(item.get('escalation_count') or len(list(item.get('escalations') or [])) or 0)
            if escalation_count > 0 or int(item.get('escalation_level') or 0) > 0:
                escalated_count += 1
                if bool(item.get('active')):
                    active_escalated_count += 1
            if str(item.get('severity') or '').strip().lower() in {'critical', 'high'}:
                critical_count += 1
            if int(suppression_state.get('pending_escalation_level') or 0) > 0:
                pending_escalation_count += 1
            ownership = self._baseline_promotion_simulation_custody_ownership_projection(item)
            routing = self._baseline_promotion_simulation_custody_routing_projection(item)
            handoff = dict(item.get('handoff') or self._baseline_promotion_simulation_custody_handoff_projection(item))
            sla = dict(item.get('sla') or item.get('sla_state') or {})
            sla_routing = dict(item.get('sla_routing_state') or {})
            if int(handoff.get('count') or 0) > 0:
                handoff_count += 1
            if bool(handoff.get('pending')):
                pending_handoff_count += 1
                if bool(item.get('active')):
                    active_handoff_pending_count += 1
            if bool(sla.get('breached')):
                sla_breached_count += 1
                if bool(item.get('active')):
                    active_sla_breached_count += 1
            if str(sla.get('status') or '') == 'warning':
                sla_warning_count += 1
            if int(sla_routing.get('reroute_count') or 0) > 0 or str(routing.get('source') or '') == 'sla_breach_routing':
                sla_rerouted_count += 1
                if bool(item.get('active')):
                    active_sla_rerouted_count += 1
            if str(routing.get('source') or '') == 'sla_breach_routing':
                team_queue_alert_count += 1
                if bool(item.get('active')):
                    active_team_queue_alert_count += 1
            if bool(routing.get('queue_at_capacity')):
                queue_at_capacity_count += 1
                if bool(item.get('active')):
                    active_queue_at_capacity_count += 1
            if bool(routing.get('queue_over_capacity')):
                queue_over_capacity_count += 1
                if bool(item.get('active')):
                    active_queue_over_capacity_count += 1
            if bool(routing.get('load_aware')):
                load_aware_routed_count += 1
                if bool(item.get('active')):
                    active_load_aware_routed_count += 1
            if bool(routing.get('reservation_applied')):
                reservation_protected_alert_count += 1
                if bool(item.get('active')):
                    active_reservation_protected_alert_count += 1
            if bool(routing.get('lease_applied')):
                lease_protected_alert_count += 1
                if bool(item.get('active')):
                    active_lease_protected_alert_count += 1
            if bool(routing.get('temporary_hold_applied')):
                temporary_hold_protected_alert_count += 1
                if bool(item.get('active')):
                    active_temporary_hold_protected_alert_count += 1
            if bool(routing.get('anti_thrashing_applied')):
                anti_thrashing_kept_alert_count += 1
                if bool(item.get('active')):
                    active_anti_thrashing_kept_alert_count += 1
            if str(routing.get('queue_family_id') or '').strip():
                queue_family_alert_count += 1
                if bool(item.get('active')):
                    active_queue_family_alert_count += 1
            if bool(routing.get('family_hysteresis_applied')):
                family_hysteresis_kept_alert_count += 1
                if bool(item.get('active')):
                    active_family_hysteresis_kept_alert_count += 1
            if bool(routing.get('aging_applied')):
                aging_alert_count += 1
                if bool(item.get('active')):
                    active_aging_alert_count += 1
            if bool(routing.get('starving')):
                starving_alert_count += 1
                if bool(item.get('active')):
                    active_starving_alert_count += 1
            if bool(routing.get('starvation_prevention_applied')):
                starvation_prevented_alert_count += 1
                if bool(item.get('active')):
                    active_starvation_prevented_alert_count += 1
            if bool(sla.get('status') in {'warning', 'breached'} or routing.get('expedite_eligible')):
                alerts_at_risk_count += 1
                if bool(item.get('active')):
                    active_alerts_at_risk_count += 1
            if bool(routing.get('predicted_sla_breach')):
                predicted_sla_breach_count += 1
                if bool(item.get('active')):
                    active_predicted_sla_breach_count += 1
            if bool(routing.get('expedite_applied')):
                expedite_routed_alert_count += 1
                if bool(item.get('active')):
                    active_expedite_routed_alert_count += 1
            if bool(routing.get('proactive_routing_applied')):
                proactive_routed_alert_count += 1
                if bool(item.get('active')):
                    active_proactive_routed_alert_count += 1
            if bool(routing.get('surge_predicted')):
                forecasted_surge_alert_count += 1
                if bool(item.get('active')):
                    active_forecasted_surge_alert_count += 1
            if bool(routing.get('overload_governance_applied')):
                overload_governed_alert_count += 1
                if bool(item.get('active')):
                    active_overload_governed_alert_count += 1
            if bool(routing.get('admission_blocked')):
                overload_blocked_alert_count += 1
                if bool(item.get('active')):
                    active_overload_blocked_alert_count += 1
            if str(routing.get('admission_decision') or '') == 'defer':
                admission_deferred_alert_count += 1
                if bool(item.get('active')):
                    active_admission_deferred_alert_count += 1
            if str(routing.get('admission_decision') or '') == 'manual_gate':
                manual_gate_alert_count += 1
                if bool(item.get('active')):
                    active_manual_gate_alert_count += 1
            owner_id = str(ownership.get('owner_id') or '').strip()
            queue_id = str(ownership.get('queue_id') or routing.get('queue_id') or '').strip()
            owned = bool(owner_id)
            if owned:
                owned_count += 1
                owner_counts[owner_id] = owner_counts.get(owner_id, 0) + 1
                if bool(item.get('active')):
                    active_owned_count += 1
            else:
                unassigned_count += 1
                if bool(item.get('active')):
                    active_unowned_count += 1
            if ownership.get('status') == 'claimed':
                claimed_count += 1
                if bool(item.get('active')):
                    active_claimed_count += 1
            if queue_id:
                queued_count += 1
                queue_counts[queue_id] = queue_counts.get(queue_id, 0) + 1
            if str(routing.get('route_id') or '').strip() or queue_id:
                routed_count += 1
        latest = dict(payload[0] or {}) if payload else {}
        latest_suppression = dict(latest.get('suppression_state') or {}) if latest else {}
        latest_ownership = self._baseline_promotion_simulation_custody_ownership_projection(latest) if latest else {}
        latest_routing = self._baseline_promotion_simulation_custody_routing_projection(latest) if latest else {}
        latest_handoff = dict(latest.get('handoff') or self._baseline_promotion_simulation_custody_handoff_projection(latest)) if latest else {}
        latest_sla = dict(latest.get('sla') or latest.get('sla_state') or {}) if latest else {}
        return {
            'count': len(payload),
            'active_count': active_count,
            'open_count': open_count,
            'acknowledged_count': acknowledged_count,
            'muted_count': muted_count,
            'resolved_count': resolved_count,
            'recovered_count': recovered_count,
            'suppressed_count': suppressed_count,
            'active_suppressed_count': active_suppressed_count,
            'escalated_count': escalated_count,
            'active_escalated_count': active_escalated_count,
            'critical_count': critical_count,
            'pending_escalation_count': pending_escalation_count,
            'owned_count': owned_count,
            'active_owned_count': active_owned_count,
            'claimed_count': claimed_count,
            'active_claimed_count': active_claimed_count,
            'unassigned_count': unassigned_count,
            'active_unowned_count': active_unowned_count,
            'queued_count': queued_count,
            'routed_count': routed_count,
            'handoff_count': handoff_count,
            'pending_handoff_count': pending_handoff_count,
            'active_handoff_pending_count': active_handoff_pending_count,
            'sla_breached_count': sla_breached_count,
            'active_sla_breached_count': active_sla_breached_count,
            'sla_warning_count': sla_warning_count,
            'sla_rerouted_count': sla_rerouted_count,
            'active_sla_rerouted_count': active_sla_rerouted_count,
            'team_queue_alert_count': team_queue_alert_count,
            'active_team_queue_alert_count': active_team_queue_alert_count,
            'queue_at_capacity_count': queue_at_capacity_count,
            'active_queue_at_capacity_count': active_queue_at_capacity_count,
            'queue_over_capacity_count': queue_over_capacity_count,
            'active_queue_over_capacity_count': active_queue_over_capacity_count,
            'load_aware_routed_count': load_aware_routed_count,
            'active_load_aware_routed_count': active_load_aware_routed_count,
            'reservation_protected_alert_count': reservation_protected_alert_count,
            'active_reservation_protected_alert_count': active_reservation_protected_alert_count,
            'lease_protected_alert_count': lease_protected_alert_count,
            'active_lease_protected_alert_count': active_lease_protected_alert_count,
            'temporary_hold_protected_alert_count': temporary_hold_protected_alert_count,
            'active_temporary_hold_protected_alert_count': active_temporary_hold_protected_alert_count,
            'anti_thrashing_kept_alert_count': anti_thrashing_kept_alert_count,
            'active_anti_thrashing_kept_alert_count': active_anti_thrashing_kept_alert_count,
            'queue_family_alert_count': queue_family_alert_count,
            'active_queue_family_alert_count': active_queue_family_alert_count,
            'family_hysteresis_kept_alert_count': family_hysteresis_kept_alert_count,
            'active_family_hysteresis_kept_alert_count': active_family_hysteresis_kept_alert_count,
            'aging_alert_count': aging_alert_count,
            'active_aging_alert_count': active_aging_alert_count,
            'starving_alert_count': starving_alert_count,
            'active_starving_alert_count': active_starving_alert_count,
            'starvation_prevented_alert_count': starvation_prevented_alert_count,
            'active_starvation_prevented_alert_count': active_starvation_prevented_alert_count,
            'alerts_at_risk_count': alerts_at_risk_count,
            'active_alerts_at_risk_count': active_alerts_at_risk_count,
            'predicted_sla_breach_count': predicted_sla_breach_count,
            'active_predicted_sla_breach_count': active_predicted_sla_breach_count,
            'expedite_routed_alert_count': expedite_routed_alert_count,
            'active_expedite_routed_alert_count': active_expedite_routed_alert_count,
            'proactive_routed_alert_count': proactive_routed_alert_count,
            'active_proactive_routed_alert_count': active_proactive_routed_alert_count,
            'forecasted_surge_alert_count': forecasted_surge_alert_count,
            'active_forecasted_surge_alert_count': active_forecasted_surge_alert_count,
            'overload_governed_alert_count': overload_governed_alert_count,
            'active_overload_governed_alert_count': active_overload_governed_alert_count,
            'overload_blocked_alert_count': overload_blocked_alert_count,
            'active_overload_blocked_alert_count': active_overload_blocked_alert_count,
            'admission_deferred_alert_count': admission_deferred_alert_count,
            'active_admission_deferred_alert_count': active_admission_deferred_alert_count,
            'manual_gate_alert_count': manual_gate_alert_count,
            'active_manual_gate_alert_count': active_manual_gate_alert_count,
            'queue_counts': queue_counts,
            'owner_counts': owner_counts,
            'latest_alert_id': str(latest.get('alert_id') or ''),
            'latest_status': self._baseline_promotion_simulation_custody_alert_status(latest) if latest else '',
            'latest_notification_id': str(latest.get('last_notification_id') or latest.get('notification_id') or ''),
            'latest_escalation_level': int(latest.get('escalation_level') or 0),
            'latest_severity': str(latest.get('severity') or ''),
            'latest_suppressed': bool(latest_suppression.get('suppressed')),
            'latest_owner_id': str(latest_ownership.get('owner_id') or ''),
            'latest_owner_role': str(latest_ownership.get('owner_role') or ''),
            'latest_queue_id': str(latest_ownership.get('queue_id') or latest_routing.get('queue_id') or ''),
            'latest_route_id': str(latest_routing.get('route_id') or ''),
            'latest_handoff_pending': bool(latest_handoff.get('pending')),
            'latest_handoff_id': str(latest_handoff.get('active_handoff_id') or latest_handoff.get('latest_handoff_id') or ''),
            'latest_sla_status': str(latest_sla.get('status') or ''),
            'latest_sla_breached': bool(latest_sla.get('breached')),
            'latest_sla_rerouted': bool((dict(latest.get('sla_routing_state') or {}).get('reroute_count')) or str((latest.get('routing') or {}).get('source') or '') == 'sla_breach_routing'),
            'latest_team_queue_id': str((latest.get('sla_routing_state') or {}).get('last_queue_id') or (latest_routing.get('queue_id') or '')),
        }

    def _evaluate_baseline_promotion_simulation_custody_alert_governance(
        self,
        gw,
        *,
        release: dict[str, Any],
        actor: str,
        policy: dict[str, Any] | None = None,
        reconciliation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        policy = self._normalize_baseline_promotion_simulation_custody_monitoring_policy(
            dict(policy or self._baseline_promotion_simulation_custody_monitoring_policy_for_release(release))
        )
        metadata = dict((release or {}).get('metadata') or {})
        promotion = dict(metadata.get('baseline_promotion') or {})
        alerts = [dict(item) for item in list(promotion.get('simulation_custody_alerts') or [])]
        current_reconciliation = dict(reconciliation or promotion.get('current_simulation_evidence_reconciliation') or {})
        summary = dict(current_reconciliation.get('summary') or {})
        drifted = str(summary.get('overall_status') or '') == 'drifted'
        now_ts = time.time()
        active_alert_index = next((index for index, item in enumerate(alerts) if bool(item.get('active'))), None)
        if active_alert_index is None or not bool(policy.get('enabled')) or not drifted:
            guard = dict(promotion.get('simulation_custody_guard') or {})
            return {
                'release': release,
                'policy': policy,
                'alerts': alerts,
                'alerts_summary': self._baseline_promotion_simulation_custody_alerts_summary(alerts),
                'guard': guard,
                'updated': False,
                'escalated': False,
                'routed': False,
            }
        alert = dict(alerts[active_alert_index] or {})
        queue_state = self._baseline_promotion_simulation_custody_queue_capacity_state(
            gw,
            release=release,
            policy=policy,
            exclude_alert_id=str(alert.get('alert_id') or ''),
        )
        current_status = self._baseline_promotion_simulation_custody_alert_status(alert, now_ts=now_ts)
        suppression_reasons: list[str] = []
        if current_status == 'muted' and bool(policy.get('suppress_while_muted')):
            suppression_reasons.append('muted')
        if current_status == 'acknowledged' and bool(policy.get('suppress_while_acknowledged')):
            suppression_reasons.append('acknowledged')
        suppression_window_s = max(0, int(policy.get('suppression_window_s') or 0))
        last_notification_at = None
        try:
            last_notification_at = float(alert.get('last_notification_at')) if alert.get('last_notification_at') is not None else None
        except Exception:
            last_notification_at = None
        window_until = None
        if suppression_window_s > 0 and last_notification_at is not None and (now_ts - last_notification_at) < suppression_window_s:
            suppression_reasons.append('notification_window')
            window_until = last_notification_at + suppression_window_s
        suppression_state = dict(alert.get('suppression_state') or {})
        previously_suppressed = bool(suppression_state.get('suppressed'))
        suppression_state.update({
            'suppressed': bool(suppression_reasons),
            'reasons': suppression_reasons,
            'evaluated_at': now_ts,
            'window_until': window_until,
            'last_notification_at': last_notification_at,
        })
        if bool(suppression_reasons):
            suppression_state['last_suppressed_at'] = now_ts
        levels = [dict(item) for item in list(policy.get('escalation_levels') or [])]
        eligible_level = {}
        highest_recorded_level = max([int((item or {}).get('level') or 0) for item in list(alert.get('escalations') or [])] + [int(alert.get('escalation_level') or 0)])
        if bool(policy.get('escalation_enabled')) and levels:
            try:
                alert_created_at = float(alert.get('created_at') or now_ts)
            except Exception:
                alert_created_at = now_ts
            alert_age_s = max(0, int(now_ts - alert_created_at))
            for level in levels:
                if alert_age_s >= int(level.get('after_s') or 0):
                    eligible_level = level
            eligible_level_no = int(eligible_level.get('level') or 0)
            if eligible_level_no > highest_recorded_level:
                pending_route = self._baseline_promotion_simulation_custody_route_for_alert(
                    policy,
                    {
                        **alert,
                        'escalation_level': eligible_level_no,
                        'severity': str(eligible_level.get('severity') or alert.get('severity') or ''),
                    },
                    queue_state=queue_state,
                )
                suppression_state['pending_escalation_level'] = eligible_level_no
                suppression_state['pending_escalation_label'] = str(eligible_level.get('label') or '')
                suppression_state['pending_route_id'] = str(pending_route.get('route_id') or '')
                suppression_state['pending_queue_id'] = str(pending_route.get('queue_id') or '')
                suppression_state['pending_owner_role'] = str(pending_route.get('owner_role') or '')
            else:
                for key in ('pending_escalation_level', 'pending_escalation_label', 'pending_route_id', 'pending_queue_id', 'pending_owner_role'):
                    suppression_state.pop(key, None)
        else:
            for key in ('pending_escalation_level', 'pending_escalation_label', 'pending_route_id', 'pending_queue_id', 'pending_owner_role'):
                suppression_state.pop(key, None)
        alert['notification_suppressed'] = bool(suppression_reasons)
        alert['suppression_state'] = suppression_state
        if bool(suppression_reasons) and not previously_suppressed:
            promotion = self._append_baseline_promotion_timeline_event(
                promotion,
                kind='monitoring',
                label='baseline_promotion_simulation_custody_alert_suppressed',
                actor=str(actor or 'system'),
                alert_id=str(alert.get('alert_id') or ''),
                reasons=list(suppression_reasons),
            )
        if (not bool(suppression_reasons)) and previously_suppressed:
            promotion = self._append_baseline_promotion_timeline_event(
                promotion,
                kind='monitoring',
                label='baseline_promotion_simulation_custody_alert_unsuppressed',
                actor=str(actor or 'system'),
                alert_id=str(alert.get('alert_id') or ''),
            )
        escalated = False
        if bool(policy.get('escalation_enabled')) and eligible_level and int(eligible_level.get('level') or 0) > highest_recorded_level:
            escalation_count = len(list(alert.get('escalations') or []))
            max_escalations = max(1, int(policy.get('max_escalations') or max(len(levels), 1)))
            if escalation_count < max_escalations and not bool(suppression_reasons) and bool(policy.get('notify_on_escalation', True)):
                route_preview = self._baseline_promotion_simulation_custody_route_for_alert(
                    policy,
                    {
                        **alert,
                        'escalation_level': int(eligible_level.get('level') or 0),
                        'severity': str(eligible_level.get('severity') or alert.get('severity') or 'critical'),
                    },
                    queue_state=queue_state,
                )
                notification = gw.audit.create_app_notification(
                    category='operator',
                    title='Baseline simulation custody drift escalated',
                    body=f"Custody drift escalated for baseline promotion {str(release.get('release_id') or '').strip()} to {str(eligible_level.get('label') or '').strip() or 'an elevated severity' }.",
                    target_path=str(route_preview.get('target_path') or eligible_level.get('target_path') or policy.get('escalation_target_path') or policy.get('target_path') or '/ui/?tab=operator'),
                    created_by=str(actor or 'system'),
                    metadata={
                        'kind': 'baseline_promotion_simulation_custody_escalated',
                        'promotion_id': str(release.get('release_id') or ''),
                        'reconciliation_id': str(current_reconciliation.get('reconciliation_id') or ''),
                        'alert_id': str(alert.get('alert_id') or ''),
                        'escalation_level': int(eligible_level.get('level') or 0),
                        'severity': str(eligible_level.get('severity') or alert.get('severity') or 'critical'),
                        'route_id': str(route_preview.get('route_id') or ''),
                        'queue_id': str(route_preview.get('queue_id') or ''),
                        'owner_role': str(route_preview.get('owner_role') or ''),
                    },
                    tenant_id=release.get('tenant_id'),
                    workspace_id=release.get('workspace_id'),
                    environment=release.get('environment'),
                )
                escalations = [dict(item) for item in list(alert.get('escalations') or [])]
                escalation_entry = {
                    'level': int(eligible_level.get('level') or 0),
                    'label': str(eligible_level.get('label') or ''),
                    'severity': str(eligible_level.get('severity') or alert.get('severity') or 'critical'),
                    'after_s': int(eligible_level.get('after_s') or 0),
                    'escalated_at': now_ts,
                    'escalated_by': str(actor or 'system'),
                    'notification_id': str((notification or {}).get('notification_id') or ''),
                }
                escalations.append(escalation_entry)
                alert['escalations'] = escalations[-max_escalations:]
                alert['escalation_count'] = len(alert['escalations'])
                alert['escalation_level'] = int(eligible_level.get('level') or 0)
                alert['last_escalated_at'] = now_ts
                alert['last_escalated_by'] = str(actor or 'system')
                alert['severity'] = str(eligible_level.get('severity') or alert.get('severity') or 'critical')
                alert['last_notification_id'] = str((notification or {}).get('notification_id') or '')
                alert['last_notification_at'] = now_ts
                for key in ('pending_escalation_level', 'pending_escalation_label', 'pending_route_id', 'pending_queue_id', 'pending_owner_role'):
                    suppression_state.pop(key, None)
                alert['suppression_state'] = suppression_state
                promotion = self._append_baseline_promotion_timeline_event(
                    promotion,
                    kind='monitoring',
                    label='baseline_promotion_simulation_custody_escalated',
                    actor=str(actor or 'system'),
                    alert_id=str(alert.get('alert_id') or ''),
                    escalation_level=int(eligible_level.get('level') or 0),
                    severity=str(eligible_level.get('severity') or alert.get('severity') or 'critical'),
                    notification_id=str((notification or {}).get('notification_id') or ''),
                    route_id=str(route_preview.get('route_id') or ''),
                    queue_id=str(route_preview.get('queue_id') or ''),
                    owner_role=str(route_preview.get('owner_role') or ''),
                )
                escalated = True
        manual_override_active = bool(((alert.get('routing') or {}).get('manual_override')))
        route = self._baseline_promotion_simulation_custody_route_for_alert(policy, alert, queue_state=queue_state)
        alert, routed = self._apply_baseline_promotion_simulation_custody_route_to_alert(
            alert,
            route=route,
            actor=actor,
            auto_assign=False,
            preserve_owner=True,
            source=('manual_routing' if manual_override_active else ('escalation_routing' if escalated else 'routing_policy')),
            manual_override=manual_override_active,
        )
        if routed:
            promotion = self._append_baseline_promotion_timeline_event(
                promotion,
                kind='monitoring',
                label='baseline_promotion_simulation_custody_routed',
                actor=str(actor or 'system'),
                alert_id=str(alert.get('alert_id') or ''),
                route_id=str((alert.get('routing') or {}).get('route_id') or ''),
                queue_id=str((alert.get('routing') or {}).get('queue_id') or ''),
                owner_role=str((alert.get('routing') or {}).get('owner_role') or ''),
                source=str((alert.get('routing') or {}).get('source') or 'routing_policy'),
            )
        handoff = self._baseline_promotion_simulation_custody_handoff_projection(alert)
        previous_sla = dict(alert.get('sla_state') or {})
        sla = self._baseline_promotion_simulation_custody_sla_projection(alert, policy, now_ts=now_ts)
        alert['handoff_count'] = int(handoff.get('count') or 0)
        alert['sla_state'] = sla
        newly_breached_targets = [
            str(item) for item in list(sla.get('breached_targets') or [])
            if str(item) and str(item) not in {str(existing) for existing in list(previous_sla.get('breached_targets') or []) if str(existing)}
        ]
        if bool((policy.get('sla_policy') or {}).get('enabled')) and newly_breached_targets and not bool((alert.get('suppression_state') or {}).get('suppressed')) and bool((policy.get('sla_policy') or {}).get('notify_on_breach', True)):
            notification = gw.audit.create_app_notification(
                category='operator',
                title='Baseline simulation custody SLA breached',
                body=f"SLA breached for baseline promotion {str(release.get('release_id') or '').strip()} ({', '.join(newly_breached_targets)}).",
                target_path=str(((policy.get('sla_policy') or {}).get('target_path')) or policy.get('target_path') or '/ui/?tab=operator'),
                created_by=str(actor or 'system'),
                metadata={
                    'kind': 'baseline_promotion_simulation_custody_sla_breached',
                    'promotion_id': str(release.get('release_id') or ''),
                    'reconciliation_id': str(current_reconciliation.get('reconciliation_id') or ''),
                    'alert_id': str(alert.get('alert_id') or ''),
                    'targets': newly_breached_targets,
                    'severity': str(((policy.get('sla_policy') or {}).get('severity')) or 'high'),
                },
                tenant_id=release.get('tenant_id'),
                workspace_id=release.get('workspace_id'),
                environment=release.get('environment'),
            )
            sla_notifications = [dict(item) for item in list(alert.get('sla_notifications') or [])]
            sla_notifications.append({
                'notification_id': str((notification or {}).get('notification_id') or ''),
                'targets': newly_breached_targets,
                'created_at': now_ts,
                'created_by': str(actor or 'system'),
            })
            alert['sla_notifications'] = sla_notifications[-10:]
            alert['last_sla_notification_id'] = str((notification or {}).get('notification_id') or '')
            alert['last_sla_notification_at'] = now_ts
            promotion = self._append_baseline_promotion_timeline_event(
                promotion,
                kind='monitoring',
                label='baseline_promotion_simulation_custody_sla_breached',
                actor=str(actor or 'system'),
                alert_id=str(alert.get('alert_id') or ''),
                targets=newly_breached_targets,
                notification_id=str((notification or {}).get('notification_id') or ''),
            )
        elif bool(previous_sla.get('breached_targets')) and not bool(sla.get('breached_targets')):
            promotion = self._append_baseline_promotion_timeline_event(
                promotion,
                kind='monitoring',
                label='baseline_promotion_simulation_custody_sla_recovered',
                actor=str(actor or 'system'),
                alert_id=str(alert.get('alert_id') or ''),
            )
        sla_routing_state = dict(alert.get('sla_routing_state') or {})
        if bool(policy.get('auto_reroute_on_sla_breach')) and bool(sla.get('breached')):
            breached_targets_for_route = [str(item) for item in list(sla.get('breached_targets') or newly_breached_targets or []) if str(item)]
            if bool((alert.get('suppression_state') or {}).get('suppressed')):
                sla_routing_state.update({
                    'pending': True,
                    'status': 'suppressed',
                    'pending_targets': breached_targets_for_route,
                    'updated_at': now_ts,
                    'updated_by': str(actor or 'system'),
                })
            elif manual_override_active:
                sla_routing_state.update({
                    'pending': True,
                    'status': 'manual_override_blocked',
                    'pending_targets': breached_targets_for_route,
                    'updated_at': now_ts,
                    'updated_by': str(actor or 'system'),
                })
            else:
                sla_route = self._baseline_promotion_simulation_custody_sla_route_for_alert(
                    policy,
                    alert,
                    sla,
                    breached_targets=breached_targets_for_route,
                    queue_state=queue_state,
                )
                desired_key = ''
                if sla_route:
                    desired_key = self._stable_digest({
                        'route_id': str(sla_route.get('route_id') or ''),
                        'queue_id': str(sla_route.get('queue_id') or ''),
                        'owner_role': str(sla_route.get('owner_role') or ''),
                        'owner_id': str(sla_route.get('owner_id') or ''),
                        'targets': sorted(breached_targets_for_route),
                    })
                current_route = dict(alert.get('routing') or {})
                already_routed = bool(sla_route) and (
                    str(current_route.get('route_id') or '') == str(sla_route.get('route_id') or '')
                    and str(current_route.get('queue_id') or '') == str(sla_route.get('queue_id') or '')
                    and str(current_route.get('source') or '') == 'sla_breach_routing'
                    and str(sla_routing_state.get('last_reroute_key') or '') == desired_key
                )
                if sla_route and not already_routed:
                    alert, sla_routed = self._apply_baseline_promotion_simulation_custody_route_to_alert(
                        alert,
                        route=sla_route,
                        actor=actor,
                        auto_assign=False,
                        preserve_owner=False,
                        source='sla_breach_routing',
                        manual_override=False,
                    )
                    if sla_routed:
                        notification = {}
                        if bool(policy.get('notify_on_sla_reroute', True)):
                            notification = gw.audit.create_app_notification(
                                category='operator',
                                title='Baseline simulation custody SLA rerouted',
                                body=f"SLA breach rerouted baseline promotion {str(release.get('release_id') or '').strip()} to {str(sla_route.get('label') or sla_route.get('queue_label') or sla_route.get('route_id') or '').strip() or 'an escalation queue' }.",
                                target_path=str(sla_route.get('target_path') or ((policy.get('sla_policy') or {}).get('target_path')) or policy.get('target_path') or '/ui/?tab=operator'),
                                created_by=str(actor or 'system'),
                                metadata={
                                    'kind': 'baseline_promotion_simulation_custody_sla_rerouted',
                                    'promotion_id': str(release.get('release_id') or ''),
                                    'reconciliation_id': str(current_reconciliation.get('reconciliation_id') or ''),
                                    'alert_id': str(alert.get('alert_id') or ''),
                                    'targets': breached_targets_for_route,
                                    'route_id': str((alert.get('routing') or {}).get('route_id') or ''),
                                    'queue_id': str((alert.get('routing') or {}).get('queue_id') or ''),
                                    'owner_role': str((alert.get('routing') or {}).get('owner_role') or ''),
                                },
                                tenant_id=release.get('tenant_id'),
                                workspace_id=release.get('workspace_id'),
                                environment=release.get('environment'),
                            )
                        sla_routing_state.update({
                            'pending': False,
                            'status': 'routed',
                            'reroute_count': int(sla_routing_state.get('reroute_count') or 0) + 1,
                            'last_rerouted_at': now_ts,
                            'last_rerouted_by': str(actor or 'system'),
                            'last_route_id': str((alert.get('routing') or {}).get('route_id') or ''),
                            'last_queue_id': str((alert.get('routing') or {}).get('queue_id') or ''),
                            'last_owner_role': str((alert.get('routing') or {}).get('owner_role') or ''),
                            'last_owner_id': str((alert.get('routing') or {}).get('owner_id') or ''),
                            'last_breached_targets': breached_targets_for_route,
                            'last_reroute_key': desired_key,
                            'last_notification_id': str((notification or {}).get('notification_id') or ''),
                            'updated_at': now_ts,
                            'updated_by': str(actor or 'system'),
                        })
                        promotion = self._append_baseline_promotion_timeline_event(
                            promotion,
                            kind='monitoring',
                            label='baseline_promotion_simulation_custody_sla_rerouted',
                            actor=str(actor or 'system'),
                            alert_id=str(alert.get('alert_id') or ''),
                            targets=breached_targets_for_route,
                            route_id=str((alert.get('routing') or {}).get('route_id') or ''),
                            queue_id=str((alert.get('routing') or {}).get('queue_id') or ''),
                            owner_role=str((alert.get('routing') or {}).get('owner_role') or ''),
                            notification_id=str((notification or {}).get('notification_id') or ''),
                        )
                elif sla_route:
                    sla_routing_state.update({
                        'pending': False,
                        'status': 'already_routed',
                        'last_route_id': str(current_route.get('route_id') or ''),
                        'last_queue_id': str(current_route.get('queue_id') or ''),
                        'last_owner_role': str(current_route.get('owner_role') or ''),
                        'last_owner_id': str(current_route.get('owner_id') or ''),
                        'last_breached_targets': breached_targets_for_route,
                        'last_reroute_key': desired_key,
                        'updated_at': now_ts,
                        'updated_by': str(actor or 'system'),
                    })
                else:
                    sla_routing_state.update({
                        'pending': True,
                        'status': 'no_route',
                        'pending_targets': breached_targets_for_route,
                        'updated_at': now_ts,
                        'updated_by': str(actor or 'system'),
                    })
        elif sla_routing_state:
            sla_routing_state.update({
                'pending': False,
                'status': 'clear',
                'updated_at': now_ts,
                'updated_by': str(actor or 'system'),
            })
        alert['sla_routing_state'] = sla_routing_state
        alerts[active_alert_index] = alert
        current_status = self._baseline_promotion_simulation_custody_alert_status(alert, now_ts=now_ts)
        ownership = self._baseline_promotion_simulation_custody_ownership_projection(alert)
        routing = self._baseline_promotion_simulation_custody_routing_projection(alert)
        guard = dict(promotion.get('simulation_custody_guard') or {})
        sla_routing = dict(alert.get('sla_routing_state') or {})
        guard.update({
            'alert_status': current_status,
            'escalated': bool(int(alert.get('escalation_level') or 0) > 0),
            'escalation_level': int(alert.get('escalation_level') or 0),
            'severity': str(alert.get('severity') or guard.get('severity') or ''),
            'suppressed': bool((alert.get('suppression_state') or {}).get('suppressed')),
            'suppression_reasons': [str(item) for item in list((alert.get('suppression_state') or {}).get('reasons') or []) if str(item)],
            'pending_escalation_level': int(((alert.get('suppression_state') or {}).get('pending_escalation_level')) or 0),
            'owner_id': str(ownership.get('owner_id') or ''),
            'owner_role': str(ownership.get('owner_role') or ''),
            'ownership_status': str(ownership.get('status') or ''),
            'queue_id': str(ownership.get('queue_id') or routing.get('queue_id') or ''),
            'queue_label': str(ownership.get('queue_label') or routing.get('queue_label') or ''),
            'route_id': str(routing.get('route_id') or ''),
            'route_label': str(routing.get('route_label') or ''),
            'handoff_pending': bool(handoff.get('pending')),
            'handoff_count': int(handoff.get('count') or 0),
            'sla_status': str(sla.get('status') or ''),
            'sla_breached': bool(sla.get('breached')),
            'sla_breached_targets': [str(item) for item in list(sla.get('breached_targets') or []) if str(item)],
            'sla_warning_targets': [str(item) for item in list(sla.get('warning_targets') or []) if str(item)],
            'sla_rerouted': bool(int(sla_routing.get('reroute_count') or 0) > 0 or str(routing.get('source') or '') == 'sla_breach_routing'),
            'sla_reroute_status': str(sla_routing.get('status') or ''),
            'sla_reroute_count': int(sla_routing.get('reroute_count') or 0),
            'team_queue_id': str(sla_routing.get('last_queue_id') or routing.get('queue_id') or ''),
            'alert_wait_age_s': int(routing.get('alert_wait_age_s') or 0),
            'aging_applied': bool(routing.get('aging_applied')),
            'starving': bool(routing.get('starving')),
            'queue_oldest_alert_age_s': int(routing.get('queue_oldest_alert_age_s') or 0),
            'queue_aged_alert_count': int(routing.get('queue_aged_alert_count') or 0),
            'queue_starving_alert_count': int(routing.get('queue_starving_alert_count') or 0),
            'starvation_reserved_capacity_borrowed': bool(routing.get('starvation_reserved_capacity_borrowed')),
            'starvation_prevention_applied': bool(routing.get('starvation_prevention_applied')),
            'starvation_prevention_reason': str(routing.get('starvation_prevention_reason') or ''),
            'sla_deadline_target': str(routing.get('sla_deadline_target') or ''),
            'time_to_breach_s': routing.get('time_to_breach_s'),
            'predicted_wait_time_s': routing.get('predicted_wait_time_s'),
            'predicted_sla_margin_s': routing.get('predicted_sla_margin_s'),
            'predicted_sla_breach': bool(routing.get('predicted_sla_breach')),
            'breach_risk_score': float(routing.get('breach_risk_score') or 0.0),
            'breach_risk_level': str(routing.get('breach_risk_level') or ''),
            'expected_service_time_s': int(routing.get('expected_service_time_s') or 0),
            'expedite_eligible': bool(routing.get('expedite_eligible')),
            'expedite_reserved_capacity_borrowed': bool(routing.get('expedite_reserved_capacity_borrowed')),
            'expedite_applied': bool(routing.get('expedite_applied')),
            'expedite_reason': str(routing.get('expedite_reason') or ''),
            'updated_at': now_ts,
            'updated_by': str(actor or 'system'),
        })
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
        updated_alerts = self._baseline_promotion_simulation_custody_alerts(updated)
        return {
            'release': updated,
            'policy': policy,
            'alerts': updated_alerts,
            'alerts_summary': self._baseline_promotion_simulation_custody_alerts_summary(updated_alerts),
            'guard': self._baseline_promotion_simulation_custody_guard(updated),
            'updated': True,
            'escalated': escalated,
            'routed': routed,
        }

