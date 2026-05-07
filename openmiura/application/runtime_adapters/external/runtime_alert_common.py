from __future__ import annotations

import time
from typing import Any


class OpenClawRuntimeAlertCommonMixin:
    @staticmethod
    def _decorate_alert_state(item: dict[str, Any] | None, *, now: float | None = None) -> dict[str, Any]:
        state = dict(item or {})
        ts = float(now if now is not None else time.time())
        silence_until = state.get('silence_until')
        silence_value = float(silence_until) if silence_until is not None else None
        silenced = silence_value is not None and silence_value > ts
        governance_state = dict((state.get('state') or {}).get('governance') or {})
        governance_until = governance_state.get('next_allowed_at')
        governance_until_value = float(governance_until) if governance_until is not None else None
        governance_suppressed = bool(governance_state.get('suppressed')) and (governance_until_value is None or governance_until_value > ts)
        state['silenced'] = silenced
        state['suppressed'] = silenced or governance_suppressed
        state['silence_remaining_s'] = max(0.0, silence_value - ts) if silence_value is not None else 0.0
        state['acked'] = bool(state.get('acked_at'))
        state['escalated'] = int(state.get('escalation_level') or 0) > 0 or bool(state.get('escalated_at'))
        workflow_status = str(state.get('workflow_status') or 'open').strip().lower() or 'open'
        if workflow_status == 'silenced' and not silenced:
            workflow_status = 'acked' if state['acked'] else ('escalated' if state['escalated'] else 'open')
        if workflow_status == 'suppressed' and not governance_suppressed:
            workflow_status = 'acked' if state['acked'] else ('escalated' if state['escalated'] else 'open')
        state['workflow_status'] = workflow_status
        return state

    @staticmethod
    def _runtime_alert_scope(*, alert: dict[str, Any] | None = None, runtime_summary: dict[str, Any] | None = None) -> dict[str, Any]:
        scope = dict((alert or {}).get('scope') or {})
        if not scope and runtime_summary is not None:
            scope = dict((runtime_summary or {}).get('scope') or {})
        return {
            'tenant_id': scope.get('tenant_id'),
            'workspace_id': scope.get('workspace_id'),
            'environment': scope.get('environment'),
        }

    @staticmethod
    def _runtime_alert_approval_view(approval: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(approval or {})
        view = {
            'approval_id': str(payload.get('approval_id') or ''),
            'status': str(payload.get('status') or ''),
            'requested_role': str(payload.get('requested_role') or ''),
            'decided_by': str(payload.get('decided_by') or ''),
            'decided_at': payload.get('decided_at'),
        }
        optional_scalar_fields = ['requested_by', 'expires_at', 'target', 'level']
        for key in optional_scalar_fields:
            if payload.get(key) is not None:
                view[key] = payload.get(key)
        return view

    def _runtime_alert_available_actions(self, *, policy: dict[str, Any] | None, raw_state: dict[str, Any] | None, approval_info: dict[str, Any] | None) -> list[str]:
        policy_obj = dict(policy or {})
        state = dict(raw_state or {})
        approval = dict(approval_info or {})
        available_actions: list[str] = []
        if policy_obj.get('allow_ack', True):
            available_actions.append('ack')
        if policy_obj.get('allow_silence', True):
            available_actions.append('silence')
        if policy_obj.get('allow_escalate', True) and int(state.get('escalation_level') or 0) < int(policy_obj.get('escalation_max_level') or 1):
            available_actions.append('escalate')
        if str(state.get('workflow_status') or '') == 'approval_pending' and str(approval.get('status') or 'pending') == 'pending':
            available_actions.extend(['approve_escalation', 'reject_escalation'])
        return available_actions

    def _runtime_alert_workflow_view(self, *, policy: dict[str, Any] | None, raw_state: dict[str, Any] | None, governance: dict[str, Any] | None = None) -> dict[str, Any]:
        state = dict(raw_state or {})
        approval_info = self._runtime_alert_approval_view((state.get('state') or {}).get('approval'))
        return {
            'policy': dict(policy or {}),
            'state': state,
            'status': str(state.get('workflow_status') or 'open'),
            'acked': bool(state.get('acked')),
            'silenced': bool(state.get('silenced')),
            'suppressed': bool(state.get('suppressed')),
            'silence_until': state.get('silence_until'),
            'silence_remaining_s': state.get('silence_remaining_s'),
            'escalated': bool(state.get('escalated')),
            'escalation_level': int(state.get('escalation_level') or 0),
            'escalation_target': str(state.get('escalation_target') or ''),
            'approval': approval_info,
            'governance': dict(governance or {}),
            'available_actions': self._runtime_alert_available_actions(policy=policy, raw_state=state, approval_info=approval_info),
        }

    @staticmethod
    def _runtime_alert_state_patch(state_obj: dict[str, Any] | None, **updates: Any) -> dict[str, Any]:
        state_payload = dict((state_obj or {}).get('state') or {})
        for key, value in updates.items():
            if value is None:
                continue
            if key == 'approval':
                state_payload[key] = OpenClawRuntimeAlertCommonMixin._runtime_alert_approval_view(value)
            else:
                state_payload[key] = value
        return state_payload

    def _runtime_alert_log_event(
        self,
        gw,
        *,
        actor: str,
        runtime_id: str,
        alert: dict[str, Any] | None,
        action: str,
        details: dict[str, Any] | None = None,
        entity: str | None = None,
    ) -> None:
        scope = self._runtime_alert_scope(alert=alert)
        payload = {
            'action': str(action or '').strip(),
            'runtime_id': str(runtime_id or '').strip(),
            'alert_code': str((alert or {}).get('code') or '').strip(),
        }
        payload.update(dict(details or {}))
        gw.audit.log_event(
            'system',
            'broker',
            str(actor or 'operator'),
            str(entity or f"alert:{str(runtime_id or '').strip()}") or 'system',
            payload,
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        )

    def _runtime_alert_dispatch_create_kwargs(
        self,
        *,
        alert: dict[str, Any],
        runtime_id: str,
        alert_code: str,
        target: dict[str, Any],
        workflow_action: str,
        escalation_level: int,
        delivery_status: str,
        request: dict[str, Any] | None,
        response: dict[str, Any] | None,
        created_by: str,
        notification_dispatch_id: str | None = None,
        delivered_at: float | None = None,
    ) -> dict[str, Any]:
        scope = self._runtime_alert_scope(alert=alert)
        return {
            'notification_dispatch_id': str(notification_dispatch_id or '').strip(),
            'alert_key': str(alert.get('alert_key') or self._alert_key(runtime_id, alert_code)),
            'runtime_id': str(runtime_id or '').strip(),
            'alert_code': str(alert.get('code') or alert_code or '').strip(),
            'target_id': str(target.get('target_id') or '').strip(),
            'target_type': str(target.get('type') or '').strip(),
            'workflow_action': str(workflow_action or '').strip(),
            'severity': str(alert.get('severity') or '').strip(),
            'escalation_level': int(escalation_level or 0),
            'delivery_status': str(delivery_status or 'pending').strip(),
            'request': dict(request or {}),
            'response': dict(response or {}),
            'created_by': str(created_by or '').strip(),
            'delivered_at': delivered_at,
            'tenant_id': scope.get('tenant_id'),
            'workspace_id': scope.get('workspace_id'),
            'environment': scope.get('environment'),
        }
