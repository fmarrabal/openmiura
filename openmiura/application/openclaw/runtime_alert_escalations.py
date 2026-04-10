from __future__ import annotations

import time
from typing import Any


class OpenClawRuntimeAlertEscalationsMixin:
    @staticmethod
    def _alert_escalation_workflow_id(runtime_id: str) -> str:
        return f'openclaw-alert-escalation:{str(runtime_id or "").strip()}'

    @staticmethod
    def _alert_escalation_step_id(alert_code: str, *, target: str = '', level: int = 0) -> str:
        return f"{str(alert_code or '').strip()}:{str(target or '-').strip() or '-'}:{int(level or 0)}"

    def _enrich_alert_workflow(self, gw, *, alert: dict[str, Any], runtime_summary: dict[str, Any] | None = None) -> dict[str, Any]:
        item = dict(alert or {})
        runtime_id = str(item.get('runtime_id') or '').strip()
        code = str(item.get('code') or '').strip()
        scope = dict(item.get('scope') or {})
        policy = self._alert_workflow_policy(runtime_summary)
        alert_key = self._alert_key(runtime_id, code)
        raw_state = self._decorate_alert_state(
            gw.audit.get_runtime_alert_state(
                alert_key=alert_key,
                tenant_id=scope.get('tenant_id'),
                workspace_id=scope.get('workspace_id'),
                environment=scope.get('environment'),
            ) or {
                'alert_key': alert_key,
                'runtime_id': runtime_id,
                'alert_code': code,
                'workflow_status': 'open',
                'severity': str(item.get('severity') or ''),
                'title': str(item.get('title') or ''),
                'observed_at': float(item.get('observed_at') or time.time()),
                'created_at': float(item.get('observed_at') or time.time()),
                'updated_at': float(item.get('observed_at') or time.time()),
                'tenant_id': scope.get('tenant_id'),
                'workspace_id': scope.get('workspace_id'),
                'environment': scope.get('environment'),
                'state': {},
            }
        )
        governance = dict(item.get('governance') or {})
        if governance:
            raw_state['state'] = self._runtime_alert_state_patch(raw_state, governance=governance)
            raw_state['suppressed'] = bool(raw_state.get('suppressed')) or bool(governance.get('suppressed'))
            if bool(governance.get('suppressed')) and str(raw_state.get('workflow_status') or '') not in {'silenced', 'approval_pending'}:
                raw_state['workflow_status'] = 'suppressed'
        item['alert_key'] = alert_key
        item['workflow'] = self._runtime_alert_workflow_view(policy=policy, raw_state=raw_state, governance=governance)
        return item

    def _escalation_requires_approval(
        self,
        *,
        runtime_summary: dict[str, Any],
        alert: dict[str, Any],
        desired_level: int,
        target: str = '',
    ) -> tuple[bool, dict[str, Any]]:
        policy = self._alert_escalation_policy(runtime_summary)
        if not bool(policy.get('enabled')):
            return False, policy
        required = bool(policy.get('default_requires_approval', False))
        severity = str(alert.get('severity') or '').strip().lower()
        code = str(alert.get('code') or '').strip()
        if severity and severity in set(policy.get('required_severities') or []):
            required = True
        if code and code in set(policy.get('required_alert_codes') or []):
            required = True
        if int(desired_level or 0) >= int(policy.get('min_escalation_level') or 1) and (policy.get('default_requires_approval') or policy.get('required_severities') or policy.get('required_alert_codes')):
            required = required or bool(policy.get('default_requires_approval'))
        if target and str(target).strip() in set(policy.get('required_target_ids') or []):
            required = True
        if target:
            target_obj = next((item for item in self._notification_targets(runtime_summary) if str(item.get('target_id') or '') == str(target).strip()), None)
            if target_obj and str(target_obj.get('type') or '').strip().lower() in set(policy.get('required_target_types') or []):
                required = True
        return required, policy

    def _finalize_runtime_alert_escalation(
        self,
        gw,
        *,
        runtime_summary: dict[str, Any],
        alert: dict[str, Any],
        actor: str,
        target: str = '',
        reason: str = '',
        desired_level: int,
        approval: dict[str, Any] | None = None,
        dispatch_notifications: bool = True,
    ) -> dict[str, Any]:
        runtime_id = str(alert.get('runtime_id') or (runtime_summary or {}).get('runtime_id') or '').strip()
        alert_code = str(alert.get('code') or '').strip()
        workflow = dict(alert.get('workflow') or {})
        state_obj = dict(workflow.get('state') or {})
        state_payload = self._runtime_alert_state_patch(
            state_obj,
            last_escalation_reason=str(reason or '').strip(),
            last_escalation_by=str(actor or '').strip(),
            approval=approval,
        )
        state = gw.audit.upsert_runtime_alert_state(
            alert_key=str(alert.get('alert_key') or self._alert_key(runtime_id, alert_code)),
            runtime_id=runtime_id,
            alert_code=alert_code,
            title=str(alert.get('title') or ''),
            severity=str(alert.get('severity') or ''),
            workflow_status='escalated',
            acked_by=str(state_obj.get('acked_by') or actor or '').strip(),
            acked_at=state_obj.get('acked_at') or time.time(),
            silence_until=state_obj.get('silence_until'),
            silenced_by=str(state_obj.get('silenced_by') or ''),
            silence_reason=str(state_obj.get('silence_reason') or ''),
            escalation_level=int(desired_level or 0),
            escalation_target=str(target or state_obj.get('escalation_target') or ''),
            escalated_by=str(actor or '').strip(),
            escalated_at=time.time(),
            state=state_payload,
            observed_at=float(alert.get('observed_at') or time.time()),
            tenant_id=(alert.get('scope') or {}).get('tenant_id'),
            workspace_id=(alert.get('scope') or {}).get('workspace_id'),
            environment=(alert.get('scope') or {}).get('environment'),
        )
        self._runtime_alert_log_event(
            gw,
            actor=str(actor or 'operator'),
            runtime_id=runtime_id,
            alert=alert,
            action='openclaw_alert_escalated',
            details={
                'level': int(desired_level or 0),
                'target': str(target or '').strip(),
                'reason': str(reason or '').strip(),
                'approval_id': str((approval or {}).get('approval_id') or ''),
            },
        )
        refreshed = self.evaluate_runtime_alerts(gw, runtime_id=runtime_id, limit=200, tenant_id=(alert.get('scope') or {}).get('tenant_id'), workspace_id=(alert.get('scope') or {}).get('workspace_id'), environment=(alert.get('scope') or {}).get('environment'))
        alert_out = self._alert_by_code(refreshed, alert_code) or alert
        notifications = None
        if dispatch_notifications and self._notification_policy(dict(refreshed.get('runtime_summary') or runtime_summary or {})).get('dispatch_on_escalate', True):
            notifications = self.dispatch_runtime_alert_notifications(gw, runtime_id=runtime_id, alert_code=alert_code, actor=actor, workflow_action='escalate', target_id=str(target or '').strip(), reason=str(reason or '').strip(), escalation_level=int(desired_level or 0), tenant_id=(alert.get('scope') or {}).get('tenant_id'), workspace_id=(alert.get('scope') or {}).get('workspace_id'), environment=(alert.get('scope') or {}).get('environment'))
        return {'ok': True, 'alert': alert_out, 'state': self._decorate_alert_state(state), 'scope': alert.get('scope') or {}, 'notifications': notifications, 'approval': approval}

    def list_alert_escalation_approvals(
        self,
        gw,
        *,
        limit: int = 100,
        runtime_id: str | None = None,
        status: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        approvals = gw.audit.list_approvals(limit=max(limit * 5, limit), status=status, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        items: list[dict[str, Any]] = []
        for item in approvals:
            workflow_id = str(item.get('workflow_id') or '')
            if not workflow_id.startswith('openclaw-alert-escalation:'):
                continue
            rid = workflow_id.split(':', 2)[-1]
            if runtime_id is not None and rid != str(runtime_id or '').strip():
                continue
            payload = dict(item.get('payload') or {})
            items.append({**dict(item or {}), 'kind': str(payload.get('kind') or ''), 'runtime_id': rid, 'alert_code': str(payload.get('alert_code') or ''), 'target': str(payload.get('target') or ''), 'level': int(payload.get('level') or 0), 'requested_scope': {'tenant_id': payload.get('tenant_id'), 'workspace_id': payload.get('workspace_id'), 'environment': payload.get('environment')}})
            if len(items) >= limit:
                break
        status_counts: dict[str, int] = {}
        for item in items:
            key = str(item.get('status') or 'pending')
            status_counts[key] = status_counts.get(key, 0) + 1
        return {'ok': True, 'items': items, 'summary': {'count': len(items), 'status_counts': status_counts, 'runtime_id': runtime_id, 'pending_count': status_counts.get('pending', 0), 'approved_count': status_counts.get('approved', 0), 'rejected_count': status_counts.get('rejected', 0)}, 'scope': self._scope(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)}

    def decide_alert_escalation_approval(
        self,
        gw,
        *,
        approval_id: str,
        actor: str,
        decision: str,
        reason: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        approval = gw.audit.get_approval(approval_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if approval is None:
            return {'ok': False, 'error': 'approval_not_found', 'approval_id': str(approval_id or '').strip()}
        if not str(approval.get('workflow_id') or '').startswith('openclaw-alert-escalation:'):
            return {'ok': False, 'error': 'unsupported_approval', 'approval_id': str(approval_id or '').strip()}
        updated = gw.audit.decide_approval(str(approval_id or '').strip(), decision=decision, decided_by=str(actor or '').strip(), reason=str(reason or '').strip(), tenant_id=approval.get('tenant_id'), workspace_id=approval.get('workspace_id'), environment=approval.get('environment'))
        if updated is None:
            return {'ok': False, 'error': 'approval_not_pending', 'approval_id': str(approval_id or '').strip()}
        payload = dict(updated.get('payload') or {})
        runtime_id = str(payload.get('runtime_id') or '').strip()
        alert_code = str(payload.get('alert_code') or '').strip()
        alerts_payload = self.evaluate_runtime_alerts(gw, runtime_id=runtime_id, limit=200, tenant_id=payload.get('tenant_id'), workspace_id=payload.get('workspace_id'), environment=payload.get('environment'))
        alert = self._alert_by_code(alerts_payload, alert_code) if alerts_payload.get('ok') else None
        if alert is None:
            return {'ok': True, 'approval': updated, 'alert': None, 'notifications': None, 'scope': {'tenant_id': payload.get('tenant_id'), 'workspace_id': payload.get('workspace_id'), 'environment': payload.get('environment')}}
        if str(updated.get('status') or '') == 'approved':
            return {**self._finalize_runtime_alert_escalation(gw, runtime_summary=dict(alerts_payload.get('runtime_summary') or {}), alert=alert, actor=str(actor or '').strip(), target=str(payload.get('target') or ''), reason=str(payload.get('reason') or reason or ''), desired_level=int(payload.get('level') or 1), approval=updated, dispatch_notifications=bool(self._alert_escalation_policy(dict(alerts_payload.get('runtime_summary') or {})).get('auto_dispatch_on_approval', True))), 'approval': updated}
        workflow = dict(alert.get('workflow') or {})
        state_obj = dict(workflow.get('state') or {})
        state_payload = self._runtime_alert_state_patch(state_obj, approval=updated)
        state = gw.audit.upsert_runtime_alert_state(alert_key=str(alert.get('alert_key') or self._alert_key(runtime_id, alert_code)), runtime_id=runtime_id, alert_code=alert_code, title=str(alert.get('title') or ''), severity=str(alert.get('severity') or ''), workflow_status='approval_rejected', acked_by=str(state_obj.get('acked_by') or actor or '').strip(), acked_at=state_obj.get('acked_at') or time.time(), silence_until=state_obj.get('silence_until'), silenced_by=str(state_obj.get('silenced_by') or ''), silence_reason=str(state_obj.get('silence_reason') or ''), escalation_level=int(state_obj.get('escalation_level') or 0), escalation_target=str(payload.get('target') or state_obj.get('escalation_target') or ''), escalated_by=str(state_obj.get('escalated_by') or ''), escalated_at=state_obj.get('escalated_at'), state=state_payload, observed_at=float(alert.get('observed_at') or time.time()), tenant_id=(alert.get('scope') or {}).get('tenant_id'), workspace_id=(alert.get('scope') or {}).get('workspace_id'), environment=(alert.get('scope') or {}).get('environment'))
        self._runtime_alert_log_event(
            gw,
            actor=str(actor or 'operator'),
            runtime_id=runtime_id,
            alert=alert,
            action='openclaw_alert_escalation_rejected',
            details={'approval_id': str(updated.get('approval_id') or ''), 'reason': str(reason or '').strip()},
        )
        refreshed = self.evaluate_runtime_alerts(gw, runtime_id=runtime_id, limit=200, tenant_id=(alert.get('scope') or {}).get('tenant_id'), workspace_id=(alert.get('scope') or {}).get('workspace_id'), environment=(alert.get('scope') or {}).get('environment'))
        alert_out = self._alert_by_code(refreshed, alert_code) or alert
        return {'ok': True, 'approval': updated, 'alert': alert_out, 'state': self._decorate_alert_state(state), 'notifications': None, 'scope': alert.get('scope') or {}}

    def list_runtime_alert_governance_promotion_approvals(
        self,
        gw,
        *,
        limit: int = 100,
        runtime_id: str | None = None,
        status: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        approvals = gw.audit.list_approvals(limit=max(limit * 5, limit), status=status, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        items: list[dict[str, Any]] = []
        for item in approvals:
            workflow_id = str(item.get('workflow_id') or '')
            if not workflow_id.startswith('openclaw-governance-promotion:'):
                continue
            rid = workflow_id.split(':', 1)[-1]
            if runtime_id is not None and rid != str(runtime_id or '').strip():
                continue
            payload = dict(item.get('payload') or {})
            items.append({
                **dict(item or {}),
                'kind': str(payload.get('kind') or ''),
                'runtime_id': rid,
                'version_id': str(payload.get('version_id') or ''),
                'release_id': str(payload.get('release_id') or ''),
                'requested_scope': {
                    'tenant_id': payload.get('tenant_id'),
                    'workspace_id': payload.get('workspace_id'),
                    'environment': payload.get('environment'),
                },
            })
            if len(items) >= limit:
                break
        status_counts: dict[str, int] = {}
        for item in items:
            key = str(item.get('status') or 'pending')
            status_counts[key] = status_counts.get(key, 0) + 1
        return {
            'ok': True,
            'items': items,
            'summary': {
                'count': len(items),
                'status_counts': status_counts,
                'runtime_id': runtime_id,
                'pending_count': status_counts.get('pending', 0),
                'approved_count': status_counts.get('approved', 0),
                'rejected_count': status_counts.get('rejected', 0),
            },
            'scope': self._scope(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment),
        }

    def decide_runtime_alert_governance_promotion_approval(
        self,
        gw,
        *,
        approval_id: str,
        actor: str,
        decision: str,
        reason: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        approval = gw.audit.get_approval(approval_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if approval is None:
            return {'ok': False, 'error': 'approval_not_found', 'approval_id': str(approval_id or '').strip()}
        if not str(approval.get('workflow_id') or '').startswith('openclaw-governance-promotion:'):
            return {'ok': False, 'error': 'unsupported_approval', 'approval_id': str(approval_id or '').strip()}
        updated_approval = gw.audit.decide_approval(str(approval_id or '').strip(), decision=decision, decided_by=str(actor or '').strip(), reason=str(reason or '').strip(), tenant_id=approval.get('tenant_id'), workspace_id=approval.get('workspace_id'), environment=approval.get('environment'))
        if updated_approval is None:
            return {'ok': False, 'error': 'approval_not_pending', 'approval_id': str(approval_id or '').strip()}
        payload = dict(updated_approval.get('payload') or {})
        runtime_id = str(payload.get('runtime_id') or '').strip()
        version_id = str(payload.get('version_id') or '').strip()
        version = gw.audit.get_runtime_governance_policy_version(version_id, tenant_id=approval.get('tenant_id'), workspace_id=approval.get('workspace_id'), environment=approval.get('environment'))
        if version is None:
            return {'ok': False, 'error': 'governance_version_not_found', 'approval': updated_approval, 'version_id': version_id}
        detail = self.openclaw_adapter_service.get_runtime(gw, runtime_id=runtime_id, tenant_id=approval.get('tenant_id'), workspace_id=approval.get('workspace_id'), environment=approval.get('environment'))
        if not detail.get('ok'):
            return {**detail, 'approval': updated_approval}
        runtime = dict(detail.get('runtime') or {})
        scope = self._scope(tenant_id=runtime.get('tenant_id'), workspace_id=runtime.get('workspace_id'), environment=runtime.get('environment'))
        if str(updated_approval.get('status') or '') == 'approved':
            finalized = self._finalize_runtime_alert_governance_version_activation(
                gw,
                runtime=runtime,
                version=version,
                actor=actor,
                scope=scope,
                reason=str(reason or payload.get('reason') or version.get('activation_reason') or ''),
                approval=updated_approval,
                now_ts=time.time(),
            )
            return {**finalized, 'approval': updated_approval}
        simulation = dict(version.get('simulation') or {})
        simulation['approval'] = {
            **dict(simulation.get('approval') or {}),
            'required': True,
            'status': str(updated_approval.get('status') or 'rejected'),
            'approval_id': str(updated_approval.get('approval_id') or ''),
            'decided_by': str(updated_approval.get('decided_by') or actor or ''),
            'decided_at': updated_approval.get('decided_at'),
            'reason': str(reason or '').strip(),
        }
        simulation['release'] = {
            **dict(simulation.get('release') or {}),
            'status': 'rejected',
        }
        updated_version = gw.audit.update_runtime_governance_policy_version(
            version_id,
            status='rejected',
            activation_reason=str(reason or version.get('activation_reason') or '').strip(),
            simulation=simulation,
        ) or version
        gw.audit.log_event('system', 'broker', str(actor or 'system'), 'system', {
            'action': 'openclaw_alert_governance_activation_rejected',
            'runtime_id': runtime_id,
            'version_id': version_id,
            'approval_id': str(updated_approval.get('approval_id') or ''),
            'reason': str(reason or '').strip(),
        }, **scope)
        return {
            'ok': True,
            'runtime_id': runtime_id,
            'runtime': runtime,
            'runtime_summary': detail.get('runtime_summary') or self.openclaw_adapter_service._build_runtime_summary(runtime),
            'version': self._runtime_alert_governance_version_view(updated_version),
            'approval': updated_approval,
            'scope': scope,
        }

    def ack_runtime_alert(
        self,
        gw,
        *,
        runtime_id: str,
        alert_code: str,
        actor: str,
        note: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        payload = self.evaluate_runtime_alerts(gw, runtime_id=runtime_id, limit=200, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if not payload.get('ok'):
            return payload
        alert = self._alert_by_code(payload, alert_code)
        if alert is None:
            return {'ok': False, 'error': 'alert_not_active', 'runtime_id': runtime_id, 'alert_code': str(alert_code or '').strip()}
        workflow_state = dict(((alert.get('workflow') or {}).get('state')) or {})
        state_payload = self._runtime_alert_state_patch(
            workflow_state,
            last_ack_note=str(note or '').strip(),
            last_ack_by=str(actor or '').strip(),
        )
        state = gw.audit.upsert_runtime_alert_state(
            alert_key=str(alert.get('alert_key') or self._alert_key(runtime_id, alert_code)),
            runtime_id=runtime_id,
            alert_code=str(alert_code or '').strip(),
            title=str(alert.get('title') or ''),
            severity=str(alert.get('severity') or ''),
            workflow_status='acked',
            acked_by=str(actor or '').strip(),
            acked_at=time.time(),
            silence_until=workflow_state.get('silence_until'),
            silenced_by=str(workflow_state.get('silenced_by') or ''),
            silence_reason=str(workflow_state.get('silence_reason') or ''),
            escalation_level=int(workflow_state.get('escalation_level') or 0),
            escalation_target=str(workflow_state.get('escalation_target') or ''),
            escalated_by=str(workflow_state.get('escalated_by') or ''),
            escalated_at=workflow_state.get('escalated_at'),
            state=state_payload,
            observed_at=float(alert.get('observed_at') or time.time()),
            tenant_id=(alert.get('scope') or {}).get('tenant_id'),
            workspace_id=(alert.get('scope') or {}).get('workspace_id'),
            environment=(alert.get('scope') or {}).get('environment'),
        )
        self._runtime_alert_log_event(
            gw,
            actor=str(actor or 'operator'),
            runtime_id=runtime_id,
            alert=alert,
            action='openclaw_alert_acked',
            details={'note': str(note or '').strip()},
        )
        refreshed = self.evaluate_runtime_alerts(gw, runtime_id=runtime_id, limit=200, tenant_id=(alert.get('scope') or {}).get('tenant_id'), workspace_id=(alert.get('scope') or {}).get('workspace_id'), environment=(alert.get('scope') or {}).get('environment'))
        alert_out = self._alert_by_code(refreshed, alert_code) or alert
        notifications = None
        if self._notification_policy(dict(refreshed.get('runtime_summary') or {})).get('dispatch_on_ack'):
            notifications = self.dispatch_runtime_alert_notifications(gw, runtime_id=runtime_id, alert_code=str(alert_code or '').strip(), actor=actor, workflow_action='ack', reason=str(note or '').strip(), escalation_level=int((self._decorate_alert_state(state) or {}).get('escalation_level') or 0), tenant_id=(alert.get('scope') or {}).get('tenant_id'), workspace_id=(alert.get('scope') or {}).get('workspace_id'), environment=(alert.get('scope') or {}).get('environment'))
        return {'ok': True, 'alert': alert_out, 'state': self._decorate_alert_state(state), 'scope': alert.get('scope') or {}, 'notifications': notifications}

    def silence_runtime_alert(
        self,
        gw,
        *,
        runtime_id: str,
        alert_code: str,
        actor: str,
        silence_for_s: int | None = None,
        reason: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        payload = self.evaluate_runtime_alerts(gw, runtime_id=runtime_id, limit=200, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if not payload.get('ok'):
            return payload
        alert = self._alert_by_code(payload, alert_code)
        if alert is None:
            return {'ok': False, 'error': 'alert_not_active', 'runtime_id': runtime_id, 'alert_code': str(alert_code or '').strip()}
        workflow = dict(alert.get('workflow') or {})
        policy = dict(workflow.get('policy') or {})
        state_obj = dict(workflow.get('state') or {})
        resolved_silence = int(silence_for_s or policy.get('default_silence_s') or 3600)
        resolved_silence = max(60, min(int(policy.get('max_silence_s') or resolved_silence), resolved_silence))
        until = time.time() + resolved_silence
        state_payload = self._runtime_alert_state_patch(
            state_obj,
            last_silence_reason=str(reason or '').strip(),
            last_silence_by=str(actor or '').strip(),
        )
        state = gw.audit.upsert_runtime_alert_state(
            alert_key=str(alert.get('alert_key') or self._alert_key(runtime_id, alert_code)),
            runtime_id=runtime_id,
            alert_code=str(alert_code or '').strip(),
            title=str(alert.get('title') or ''),
            severity=str(alert.get('severity') or ''),
            workflow_status='silenced',
            acked_by=str(state_obj.get('acked_by') or actor or '').strip(),
            acked_at=state_obj.get('acked_at') or time.time(),
            silence_until=until,
            silenced_by=str(actor or '').strip(),
            silence_reason=str(reason or '').strip(),
            escalation_level=int(state_obj.get('escalation_level') or 0),
            escalation_target=str(state_obj.get('escalation_target') or ''),
            escalated_by=str(state_obj.get('escalated_by') or ''),
            escalated_at=state_obj.get('escalated_at'),
            state=state_payload,
            observed_at=float(alert.get('observed_at') or time.time()),
            tenant_id=(alert.get('scope') or {}).get('tenant_id'),
            workspace_id=(alert.get('scope') or {}).get('workspace_id'),
            environment=(alert.get('scope') or {}).get('environment'),
        )
        self._runtime_alert_log_event(
            gw,
            actor=str(actor or 'operator'),
            runtime_id=runtime_id,
            alert=alert,
            action='openclaw_alert_silenced',
            details={'silence_for_s': resolved_silence, 'reason': str(reason or '').strip()},
        )
        refreshed = self.evaluate_runtime_alerts(gw, runtime_id=runtime_id, limit=200, tenant_id=(alert.get('scope') or {}).get('tenant_id'), workspace_id=(alert.get('scope') or {}).get('workspace_id'), environment=(alert.get('scope') or {}).get('environment'))
        alert_out = self._alert_by_code(refreshed, alert_code) or alert
        notifications = None
        if self._notification_policy(dict(refreshed.get('runtime_summary') or {})).get('dispatch_on_silence'):
            notifications = self.dispatch_runtime_alert_notifications(gw, runtime_id=runtime_id, alert_code=str(alert_code or '').strip(), actor=actor, workflow_action='silence', reason=str(reason or '').strip(), escalation_level=int((self._decorate_alert_state(state) or {}).get('escalation_level') or 0), tenant_id=(alert.get('scope') or {}).get('tenant_id'), workspace_id=(alert.get('scope') or {}).get('workspace_id'), environment=(alert.get('scope') or {}).get('environment'))
        return {'ok': True, 'alert': alert_out, 'state': self._decorate_alert_state(state), 'scope': alert.get('scope') or {}, 'notifications': notifications}

    def escalate_runtime_alert(
        self,
        gw,
        *,
        runtime_id: str,
        alert_code: str,
        actor: str,
        target: str = '',
        reason: str = '',
        level: int | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        payload = self.evaluate_runtime_alerts(gw, runtime_id=runtime_id, limit=200, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if not payload.get('ok'):
            return payload
        alert = self._alert_by_code(payload, alert_code)
        if alert is None:
            return {'ok': False, 'error': 'alert_not_active', 'runtime_id': runtime_id, 'alert_code': str(alert_code or '').strip()}
        workflow = dict(alert.get('workflow') or {})
        policy = dict(workflow.get('policy') or {})
        state_obj = dict(workflow.get('state') or {})
        current_level = int(state_obj.get('escalation_level') or 0)
        desired_level = int(level if level is not None else current_level + 1)
        desired_level = max(1, min(int(policy.get('escalation_max_level') or desired_level), desired_level))
        runtime_summary = dict(payload.get('runtime_summary') or {})
        requires_approval, approval_policy = self._escalation_requires_approval(runtime_summary=runtime_summary, alert=alert, desired_level=desired_level, target=str(target or '').strip())
        current_approval = dict((state_obj.get('state') or {}).get('approval') or {})
        if requires_approval and str(current_approval.get('status') or '') != 'approved':
            scope = dict(alert.get('scope') or {})
            workflow_id = self._alert_escalation_workflow_id(runtime_id)
            step_id = self._alert_escalation_step_id(str(alert_code or '').strip(), target=str(target or '').strip(), level=desired_level)
            approval = self._ensure_step_approval_request(
                gw,
                workflow_id=workflow_id,
                step_id=step_id,
                requested_role=str(approval_policy.get('requested_role') or 'admin'),
                requested_by=str(actor or '').strip(),
                payload={
                    'kind': 'openclaw_alert_escalation',
                    'runtime_id': runtime_id,
                    'alert_code': str(alert_code or '').strip(),
                    'target': str(target or '').strip(),
                    'reason': str(reason or '').strip(),
                    'level': int(desired_level or 0),
                    'tenant_id': scope.get('tenant_id'),
                    'workspace_id': scope.get('workspace_id'),
                    'environment': scope.get('environment'),
                },
                expires_at=time.time() + float(approval_policy.get('ttl_s') or 1800),
                tenant_id=scope.get('tenant_id'),
                workspace_id=scope.get('workspace_id'),
                environment=scope.get('environment'),
            )
            state_payload = self._runtime_alert_state_patch(
                state_obj,
                approval={
                    **dict(approval or {}),
                    'status': str(approval.get('status') or 'pending'),
                    'requested_by': str(approval.get('requested_by') or actor or '').strip(),
                    'target': str(target or '').strip(),
                    'level': int(desired_level or 0),
                },
                pending_escalation={'target': str(target or '').strip(), 'level': int(desired_level or 0), 'reason': str(reason or '').strip()},
            )
            state = gw.audit.upsert_runtime_alert_state(alert_key=str(alert.get('alert_key') or self._alert_key(runtime_id, alert_code)), runtime_id=runtime_id, alert_code=str(alert_code or '').strip(), title=str(alert.get('title') or ''), severity=str(alert.get('severity') or ''), workflow_status='approval_pending', acked_by=str(state_obj.get('acked_by') or actor or '').strip(), acked_at=state_obj.get('acked_at') or time.time(), silence_until=state_obj.get('silence_until'), silenced_by=str(state_obj.get('silenced_by') or ''), silence_reason=str(state_obj.get('silence_reason') or ''), escalation_level=int(state_obj.get('escalation_level') or 0), escalation_target=str(target or state_obj.get('escalation_target') or ''), escalated_by=str(state_obj.get('escalated_by') or ''), escalated_at=state_obj.get('escalated_at'), state=state_payload, observed_at=float(alert.get('observed_at') or time.time()), tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'))
            self._runtime_alert_log_event(
                gw,
                actor=str(actor or 'operator'),
                runtime_id=runtime_id,
                alert=alert,
                action='openclaw_alert_escalation_approval_requested',
                details={'approval_id': str(approval.get('approval_id') or ''), 'level': desired_level, 'target': str(target or '').strip(), 'reason': str(reason or '').strip()},
            )
            refreshed = self.evaluate_runtime_alerts(gw, runtime_id=runtime_id, limit=200, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'))
            alert_out = self._alert_by_code(refreshed, alert_code) or alert
            return {'ok': True, 'approval_required': True, 'approval': approval, 'alert': alert_out, 'state': self._decorate_alert_state(state), 'scope': alert.get('scope') or {}, 'notifications': None, 'policy': approval_policy}
        return self._finalize_runtime_alert_escalation(gw, runtime_summary=runtime_summary, alert=alert, actor=actor, target=str(target or '').strip(), reason=str(reason or '').strip(), desired_level=int(desired_level or 0), approval=None, dispatch_notifications=True)

