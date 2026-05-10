"""baseline_rollout_support._alerts_b_mixin

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


class _OpenClawBaselineRolloutSupportAlertsBMixin:
    """Sub-mixin: alerts b methods on OpenClawBaselineRolloutSupportMixin."""

    def _update_baseline_promotion_simulation_custody_alert_lifecycle(
        self,
        gw,
        *,
        release: dict[str, Any],
        actor: str,
        action: str,
        alert_id: str | None = None,
        reason: str = '',
        mute_for_s: int | None = None,
        owner_id: str | None = None,
        owner_role: str | None = None,
        queue_id: str | None = None,
        queue_label: str | None = None,
        route_id: str | None = None,
        route_label: str | None = None,
    ) -> dict[str, Any]:
        normalized_action = str(action or '').strip().lower()
        metadata = dict((release or {}).get('metadata') or {})
        promotion = dict(metadata.get('baseline_promotion') or {})
        alerts = [dict(item) for item in list(promotion.get('simulation_custody_alerts') or [])]
        if not alerts:
            return {'ok': False, 'error': 'baseline_promotion_simulation_custody_alert_missing'}
        target = None
        if alert_id:
            target = next((item for item in alerts if str(item.get('alert_id') or '') == str(alert_id or '').strip()), None)
        if target is None:
            target = next((item for item in alerts if bool(item.get('active'))), None)
        if target is None:
            return {'ok': False, 'error': 'baseline_promotion_simulation_custody_alert_missing'}
        now_ts = time.time()
        target_id = str(target.get('alert_id') or '')
        current_status = self._baseline_promotion_simulation_custody_alert_status(target, now_ts=now_ts)
        policy = self._baseline_promotion_simulation_custody_monitoring_policy_for_release(release)
        queue_state = self._baseline_promotion_simulation_custody_queue_capacity_state(
            gw,
            release=release,
            policy=policy,
            exclude_alert_id=target_id,
        )
        current_reconciliation = dict(promotion.get('current_simulation_evidence_reconciliation') or {})
        current_summary = dict(current_reconciliation.get('summary') or {})
        drifted = str(current_summary.get('overall_status') or '') == 'drifted'
        ownership = dict(target.get('ownership') or {})
        routing = dict(target.get('routing') or {})
        normalized_owner_id = str(owner_id or '').strip()
        normalized_owner_role = str(owner_role or '').strip()
        normalized_queue_id = str(queue_id or '').strip()
        normalized_queue_label = str(queue_label or '').strip()
        normalized_route_id = str(route_id or '').strip()
        normalized_route_label = str(route_label or '').strip()
        if normalized_action == 'acknowledge':
            if not bool(target.get('active')):
                return {'ok': False, 'error': 'baseline_promotion_simulation_custody_alert_not_active', 'alert': target}
            target['acknowledged_at'] = now_ts
            target['acknowledged_by'] = str(actor or 'system')
            target['status'] = 'acknowledged'
            label = 'baseline_promotion_simulation_custody_alert_acknowledged'
        elif normalized_action == 'mute':
            if not bool(target.get('active')):
                return {'ok': False, 'error': 'baseline_promotion_simulation_custody_alert_not_active', 'alert': target}
            try:
                mute_window_s = int(mute_for_s) if mute_for_s is not None else int(policy.get('default_mute_s') or 0)
            except Exception:
                mute_window_s = int(policy.get('default_mute_s') or 0)
            mute_window_s = max(0, int(mute_window_s or 0))
            target['muted_at'] = now_ts
            target['muted_by'] = str(actor or 'system')
            target['muted_until'] = (now_ts + mute_window_s) if mute_window_s > 0 else None
            target['mute_reason'] = str(reason or '').strip()
            target['status'] = 'muted'
            label = 'baseline_promotion_simulation_custody_alert_muted'
        elif normalized_action == 'unmute':
            if current_status != 'muted':
                return {'ok': False, 'error': 'baseline_promotion_simulation_custody_alert_not_muted', 'alert': target}
            target.pop('muted_at', None)
            target.pop('muted_by', None)
            target.pop('muted_until', None)
            target.pop('mute_reason', None)
            target['status'] = 'acknowledged' if target.get('acknowledged_at') is not None else 'open'
            label = 'baseline_promotion_simulation_custody_alert_unmuted'
        elif normalized_action == 'resolve':
            if bool(target.get('active')) and drifted:
                return {'ok': False, 'error': 'baseline_promotion_simulation_custody_alert_still_drifted', 'alert': target, 'reconciliation': current_reconciliation}
            target['active'] = False
            target['resolved_at'] = now_ts
            target['resolved_by'] = str(actor or 'system')
            target['resolve_reason'] = str(reason or '').strip()
            target['status'] = 'resolved'
            label = 'baseline_promotion_simulation_custody_alert_resolved'
        elif normalized_action == 'claim':
            if not bool(target.get('active')):
                return {'ok': False, 'error': 'baseline_promotion_simulation_custody_alert_not_active', 'alert': target}
            current_owner_id = str(ownership.get('owner_id') or '').strip()
            if current_owner_id and current_owner_id != str(actor or 'system'):
                return {'ok': False, 'error': 'baseline_promotion_simulation_custody_alert_already_owned', 'alert': target}
            ownership['owner_id'] = str(actor or 'system')
            ownership['owner_display'] = str(actor or 'system')
            ownership['assigned_at'] = ownership.get('assigned_at') or now_ts
            ownership['assigned_by'] = ownership.get('assigned_by') or str(actor or 'system')
            ownership['claimed_at'] = now_ts
            ownership['claimed_by'] = str(actor or 'system')
            ownership['updated_at'] = now_ts
            ownership['updated_by'] = str(actor or 'system')
            ownership['status'] = 'claimed'
            handoffs = [dict(item) for item in list(target.get('handoffs') or [])]
            if handoffs:
                latest_handoff = dict(handoffs[-1] or {})
                target_owner = str(latest_handoff.get('to_owner_id') or '').strip()
                if latest_handoff.get('accepted_at') is None and (not target_owner or target_owner == str(actor or 'system')):
                    latest_handoff['accepted_at'] = now_ts
                    latest_handoff['accepted_by'] = str(actor or 'system')
                    latest_handoff['status'] = 'accepted'
                    handoffs[-1] = latest_handoff
                    target['handoffs'] = handoffs
                    target['handoff_count'] = len(handoffs)
            target['ownership'] = ownership
            label = 'baseline_promotion_simulation_custody_alert_claimed'
        elif normalized_action == 'assign':
            if not bool(target.get('active')):
                return {'ok': False, 'error': 'baseline_promotion_simulation_custody_alert_not_active', 'alert': target}
            if not any([normalized_owner_id, normalized_owner_role, normalized_queue_id, normalized_route_id]):
                return {'ok': False, 'error': 'baseline_promotion_simulation_custody_alert_assignment_missing', 'alert': target}
            if normalized_route_id or normalized_queue_id or normalized_owner_role:
                route = self._baseline_promotion_simulation_custody_route_for_alert(policy, target, preferred_route_id=normalized_route_id, queue_state=queue_state)
                if normalized_queue_id or normalized_owner_role or normalized_route_label:
                    route = self._normalize_baseline_promotion_simulation_custody_route({
                        **route,
                        'route_id': normalized_route_id or route.get('route_id') or self._stable_digest({'promotion_id': str(release.get('release_id') or ''), 'queue_id': normalized_queue_id, 'owner_role': normalized_owner_role})[:16],
                        'label': normalized_route_label or route.get('label') or 'Manual routing',
                        'queue_id': normalized_queue_id or route.get('queue_id') or '',
                        'queue_label': normalized_queue_label or route.get('queue_label') or normalized_queue_id or '',
                        'owner_role': normalized_owner_role or route.get('owner_role') or '',
                        'owner_id': normalized_owner_id or route.get('owner_id') or '',
                        'target_path': route.get('target_path') or policy.get('target_path') or '/ui/?tab=operator',
                    }, index=0)
                route = self._select_baseline_promotion_simulation_custody_route_by_load(
                    routes=[route],
                    queue_state=queue_state,
                    current_queue_id=str((target.get('routing') or {}).get('queue_id') or ''),
                    prefer_lowest_load=False,
                    alert=target,
                    policy=policy,
                )
                target, _ = self._apply_baseline_promotion_simulation_custody_route_to_alert(
                    target,
                    route=route,
                    actor=actor,
                    auto_assign=False,
                    preserve_owner=not bool(normalized_owner_id),
                    source='manual_assignment',
                    manual_override=True,
                )
                ownership = dict(target.get('ownership') or {})
                routing = dict(target.get('routing') or {})
            if normalized_owner_id:
                ownership['owner_id'] = normalized_owner_id
                ownership['owner_display'] = normalized_owner_id
            if normalized_owner_role:
                ownership['owner_role'] = normalized_owner_role
            if normalized_queue_id:
                ownership['queue_id'] = normalized_queue_id
                ownership['queue_label'] = normalized_queue_label or normalized_queue_id
            ownership['assigned_at'] = now_ts
            ownership['assigned_by'] = str(actor or 'system')
            ownership.pop('claimed_at', None)
            ownership.pop('claimed_by', None)
            ownership['status'] = 'assigned' if str(ownership.get('owner_id') or '').strip() else ('queued' if str(ownership.get('queue_id') or ownership.get('owner_role') or '').strip() else 'unassigned')
            target['ownership'] = ownership
            if normalized_route_id:
                routing['route_id'] = normalized_route_id
            if normalized_route_label:
                routing['route_label'] = normalized_route_label
            if normalized_queue_id:
                routing['queue_id'] = normalized_queue_id
                routing['queue_label'] = normalized_queue_label or normalized_queue_id
            if normalized_owner_role:
                routing['owner_role'] = normalized_owner_role
            if normalized_owner_id:
                routing['owner_id'] = normalized_owner_id
            routing['updated_at'] = now_ts
            routing['updated_by'] = str(actor or 'system')
            routing['source'] = 'manual_assignment'
            routing['manual_override'] = True
            target['routing'] = routing
            label = 'baseline_promotion_simulation_custody_alert_assigned'
        elif normalized_action == 'release':
            if not str(ownership.get('owner_id') or '').strip():
                return {'ok': False, 'error': 'baseline_promotion_simulation_custody_alert_not_owned', 'alert': target}
            ownership.pop('owner_id', None)
            ownership.pop('owner_display', None)
            ownership.pop('claimed_at', None)
            ownership.pop('claimed_by', None)
            ownership['released_at'] = now_ts
            ownership['released_by'] = str(actor or 'system')
            ownership['status'] = 'queued' if str(ownership.get('queue_id') or ownership.get('owner_role') or '').strip() else 'unassigned'
            target['ownership'] = ownership
            label = 'baseline_promotion_simulation_custody_alert_released'
        elif normalized_action == 'reroute':
            if not bool(target.get('active')):
                return {'ok': False, 'error': 'baseline_promotion_simulation_custody_alert_not_active', 'alert': target}
            route = self._baseline_promotion_simulation_custody_route_for_alert(policy, target, preferred_route_id=normalized_route_id, queue_state=queue_state)
            if normalized_route_id and not route:
                route = {}
            route = self._normalize_baseline_promotion_simulation_custody_route({
                **route,
                'route_id': normalized_route_id or route.get('route_id') or self._stable_digest({'promotion_id': str(release.get('release_id') or ''), 'queue_id': normalized_queue_id or routing.get('queue_id') or ''})[:16],
                'label': normalized_route_label or route.get('label') or 'Manual reroute',
                'queue_id': normalized_queue_id or route.get('queue_id') or routing.get('queue_id') or '',
                'queue_label': normalized_queue_label or route.get('queue_label') or routing.get('queue_label') or normalized_queue_id or '',
                'owner_role': normalized_owner_role or route.get('owner_role') or routing.get('owner_role') or ownership.get('owner_role') or '',
                'owner_id': route.get('owner_id') or routing.get('owner_id') or '',
                'target_path': route.get('target_path') or policy.get('target_path') or '/ui/?tab=operator',
            }, index=0)
            if not any(route.get(key) for key in ('queue_id', 'owner_role', 'owner_id', 'route_id')):
                return {'ok': False, 'error': 'baseline_promotion_simulation_custody_alert_route_missing', 'alert': target}
            route = self._select_baseline_promotion_simulation_custody_route_by_load(
                routes=[route],
                queue_state=queue_state,
                current_queue_id=str((target.get('routing') or {}).get('queue_id') or ''),
                prefer_lowest_load=False,
                alert=target,
                policy=policy,
            )
            target, _ = self._apply_baseline_promotion_simulation_custody_route_to_alert(
                target,
                route=route,
                actor=actor,
                auto_assign=False,
                preserve_owner=True,
                source='manual_reroute',
                manual_override=True,
            )
            label = 'baseline_promotion_simulation_custody_alert_rerouted'
        elif normalized_action == 'handoff':
            if not bool(policy.get('handoff_enabled', True)):
                return {'ok': False, 'error': 'baseline_promotion_simulation_custody_handoff_disabled', 'alert': target}
            if not bool(target.get('active')):
                return {'ok': False, 'error': 'baseline_promotion_simulation_custody_alert_not_active', 'alert': target}
            if bool(policy.get('handoff_require_reason')) and not str(reason or '').strip():
                return {'ok': False, 'error': 'baseline_promotion_simulation_custody_handoff_reason_required', 'alert': target}
            if not any([normalized_owner_id, normalized_owner_role, normalized_queue_id, normalized_route_id]):
                return {'ok': False, 'error': 'baseline_promotion_simulation_custody_handoff_missing', 'alert': target}
            previous_ownership = self._baseline_promotion_simulation_custody_ownership_projection(target)
            previous_routing = self._baseline_promotion_simulation_custody_routing_projection(target)
            route = self._baseline_promotion_simulation_custody_route_for_alert(policy, target, preferred_route_id=normalized_route_id, queue_state=queue_state)
            if normalized_route_id and not route:
                route = {}
            route = self._normalize_baseline_promotion_simulation_custody_route({
                **route,
                'route_id': normalized_route_id or route.get('route_id') or self._stable_digest({'promotion_id': str(release.get('release_id') or ''), 'owner_id': normalized_owner_id, 'queue_id': normalized_queue_id})[:16],
                'label': normalized_route_label or route.get('label') or 'Manual handoff',
                'queue_id': normalized_queue_id or route.get('queue_id') or previous_routing.get('queue_id') or '',
                'queue_label': normalized_queue_label or route.get('queue_label') or previous_routing.get('queue_label') or normalized_queue_id or '',
                'owner_role': normalized_owner_role or route.get('owner_role') or previous_routing.get('owner_role') or previous_ownership.get('owner_role') or '',
                'owner_id': normalized_owner_id or route.get('owner_id') or '',
                'target_path': route.get('target_path') or policy.get('target_path') or '/ui/?tab=operator',
            }, index=0)
            route = self._select_baseline_promotion_simulation_custody_route_by_load(
                routes=[route],
                queue_state=queue_state,
                current_queue_id=str((target.get('routing') or {}).get('queue_id') or ''),
                prefer_lowest_load=False,
                alert=target,
                policy=policy,
            )
            target, _ = self._apply_baseline_promotion_simulation_custody_route_to_alert(
                target,
                route=route,
                actor=actor,
                auto_assign=False,
                preserve_owner=False,
                source='manual_handoff',
                manual_override=True,
            )
            ownership = dict(target.get('ownership') or {})
            routing = dict(target.get('routing') or {})
            ownership['assigned_at'] = now_ts
            ownership['assigned_by'] = str(actor or 'system')
            ownership['updated_at'] = now_ts
            ownership['updated_by'] = str(actor or 'system')
            ownership.pop('claimed_at', None)
            ownership.pop('claimed_by', None)
            ownership['status'] = 'assigned' if str(ownership.get('owner_id') or '').strip() else ('queued' if str(ownership.get('queue_id') or ownership.get('owner_role') or '').strip() else 'unassigned')
            target['ownership'] = ownership
            handoffs = [dict(item) for item in list(target.get('handoffs') or [])]
            entry = {
                'handoff_id': self._stable_digest({'promotion_id': str(release.get('release_id') or ''), 'alert_id': target_id, 'handoff_at': now_ts, 'to_owner_id': str(ownership.get('owner_id') or ''), 'to_queue_id': str(ownership.get('queue_id') or routing.get('queue_id') or '')})[:24],
                'handoff_at': now_ts,
                'handed_off_by': str(actor or 'system'),
                'reason': str(reason or '').strip(),
                'from_owner_id': str(previous_ownership.get('owner_id') or ''),
                'from_owner_role': str(previous_ownership.get('owner_role') or ''),
                'from_queue_id': str(previous_ownership.get('queue_id') or previous_routing.get('queue_id') or ''),
                'from_route_id': str(previous_routing.get('route_id') or ''),
                'to_owner_id': str(ownership.get('owner_id') or ''),
                'to_owner_role': str(ownership.get('owner_role') or ''),
                'to_queue_id': str(ownership.get('queue_id') or routing.get('queue_id') or ''),
                'to_route_id': str(routing.get('route_id') or ''),
                'status': 'pending',
            }
            if str(entry.get('to_owner_id') or '') == str(actor or 'system'):
                entry['accepted_at'] = now_ts
                entry['accepted_by'] = str(actor or 'system')
                entry['status'] = 'accepted'
            handoffs.append(entry)
            target['handoffs'] = handoffs[-20:]
            target['handoff_count'] = len(target['handoffs'])
            label = 'baseline_promotion_simulation_custody_alert_handed_off'
        else:
            return {'ok': False, 'error': 'baseline_promotion_simulation_custody_alert_action_unsupported', 'action': normalized_action}
        for item in alerts:
            if str(item.get('alert_id') or '') == target_id:
                item.update(target)
                break
        promotion['simulation_custody_alerts'] = alerts
        promotion = self._append_baseline_promotion_timeline_event(
            promotion,
            kind='monitoring',
            label=label,
            actor=str(actor or 'system'),
            alert_id=target_id,
            reason=str(reason or '').strip(),
            mute_for_s=(None if mute_for_s is None else max(0, int(mute_for_s or 0))),
            owner_id=str((target.get('ownership') or {}).get('owner_id') or ''),
            owner_role=str((target.get('ownership') or {}).get('owner_role') or ''),
            queue_id=str((target.get('ownership') or {}).get('queue_id') or ((target.get('routing') or {}).get('queue_id')) or ''),
            route_id=str((target.get('routing') or {}).get('route_id') or ''),
        )
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
            reconciliation=current_reconciliation,
        )
        updated_release = dict(governance.get('release') or updated)
        updated_alerts = [dict(item) for item in list(governance.get('alerts') or self._baseline_promotion_simulation_custody_alerts(updated_release))]
        return {
            'ok': True,
            'action': normalized_action,
            'alert': next((item for item in updated_alerts if str(item.get('alert_id') or '') == target_id), {}),
            'alerts': updated_alerts,
            'alerts_summary': self._baseline_promotion_simulation_custody_alerts_summary(updated_alerts),
            'release': updated_release,
        }

    def export_runtime_alert_governance_baseline_promotion_attestation(
        self,
        gw,
        *,
        promotion_id: str,
        actor: str,
        timeline_limit: int | None = None,
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
        return self._build_baseline_promotion_attestation_export_payload(detail=detail, actor=actor, timeline_limit=timeline_limit)

    def export_runtime_alert_governance_baseline_promotion_postmortem(
        self,
        gw,
        *,
        promotion_id: str,
        actor: str,
        timeline_limit: int | None = None,
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
        return self._build_baseline_promotion_postmortem_export_payload(detail=detail, actor=actor, timeline_limit=timeline_limit)

