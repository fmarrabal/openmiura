from __future__ import annotations

from typing import Any


class OpenClawGovernanceExplainabilityMixin:
    @staticmethod
    def _governance_explain_view(decision: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(decision or {})
        quiet = dict(payload.get('quiet_hours') or {})
        maintenance = dict(payload.get('maintenance') or {})
        storm = dict(payload.get('storm') or {})
        explanation: list[dict[str, Any]] = []
        quiet_window = dict(quiet.get('window') or {})
        if bool(quiet.get('active')):
            explanation.append({
                'source': 'quiet_hours',
                'effect': str(quiet.get('action') or payload.get('status') or 'schedule'),
                'why': 'quiet hours window is active',
                'details': {
                    'timezone': quiet_window.get('timezone'),
                    'active_from': quiet_window.get('active_from'),
                    'active_until': quiet_window.get('active_until'),
                    'weekdays': quiet_window.get('weekdays'),
                },
            })
        elif quiet_window.get('bypass'):
            explanation.append({
                'source': 'quiet_hours',
                'effect': 'bypass',
                'why': f"quiet hours bypassed by {quiet_window.get('bypass')}",
                'details': {'bypass': quiet_window.get('bypass')},
            })
        windows = [dict(item) for item in list(maintenance.get('windows') or [])]
        if bool(maintenance.get('active')):
            explanation.append({
                'source': 'maintenance',
                'effect': str(maintenance.get('action') or payload.get('status') or 'suppress'),
                'why': 'maintenance window is active',
                'details': {
                    'window_ids': [str(item.get('window_id') or '') for item in windows if str(item.get('window_id') or '').strip()],
                    'active_windows': windows,
                },
            })
        if bool(storm.get('active')):
            explanation.append({
                'source': 'alert_storm',
                'effect': str(storm.get('action') or payload.get('status') or 'suppress'),
                'why': 'alert storm thresholds are active',
                'details': dict(storm.get('summary') or {}),
            })
        if not explanation:
            explanation.append({
                'source': 'governance',
                'effect': 'allow',
                'why': 'no governance rule blocked or deferred delivery',
                'details': {'reasons': list(payload.get('reasons') or [])},
            })
        return {
            'status': str(payload.get('status') or 'allow'),
            'suppressed': bool(payload.get('suppressed')),
            'scheduled': bool(payload.get('scheduled')),
            'next_allowed_at': payload.get('next_allowed_at'),
            'reasons': list(payload.get('reasons') or []),
            'active_override_count': int(payload.get('active_override_count') or 0),
            'explanation': explanation,
        }

    @staticmethod
    def _governance_decision_change_summary(
        baseline: dict[str, Any] | None,
        candidate: dict[str, Any] | None,
    ) -> dict[str, Any]:
        before = dict(baseline or {})
        after = dict(candidate or {})
        reasons_before = {str(item) for item in list(before.get('reasons') or []) if str(item).strip()}
        reasons_after = {str(item) for item in list(after.get('reasons') or []) if str(item).strip()}
        changed = {
            'status_changed': str(before.get('status') or 'allow') != str(after.get('status') or 'allow'),
            'suppressed_changed': bool(before.get('suppressed')) != bool(after.get('suppressed')),
            'scheduled_changed': bool(before.get('scheduled')) != bool(after.get('scheduled')),
            'next_allowed_at_changed': before.get('next_allowed_at') != after.get('next_allowed_at'),
            'override_count_changed': int(before.get('active_override_count') or 0) != int(after.get('active_override_count') or 0),
        }
        affected = any(changed.values()) or reasons_before != reasons_after
        return {
            'affected': affected,
            'changed': changed,
            'reason_delta': {
                'added': sorted(reasons_after - reasons_before),
                'removed': sorted(reasons_before - reasons_after),
            },
            'transition': f"{str(before.get('status') or 'allow')}->{str(after.get('status') or 'allow')}",
            'newly_suppressed': (not bool(before.get('suppressed'))) and bool(after.get('suppressed')),
            'newly_scheduled': (not bool(before.get('scheduled'))) and bool(after.get('scheduled')),
            'newly_allowed': str(before.get('status') or 'allow') != 'allow' and str(after.get('status') or 'allow') == 'allow',
        }

    @staticmethod
    def _governance_reason_counts(items: list[dict[str, Any]] | None, *, reason_key: str = 'reasons') -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in list(items or []):
            for reason in list((item or {}).get(reason_key) or []):
                key = str(reason or '').strip()
                if not key:
                    continue
                counts[key] = counts.get(key, 0) + 1
        return counts

    @staticmethod
    def _governance_analytics_shape(
        *,
        reason_counts: dict[str, int] | None = None,
        curve: list[dict[str, Any]] | None = None,
        latest: dict[str, Any] | None = None,
        extras: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = dict(extras or {})
        if reason_counts is not None:
            payload['reason_counts'] = dict(reason_counts)
        if curve is not None:
            payload['curve'] = list(curve)
        if latest is not None:
            payload['latest'] = dict(latest)
        return payload
