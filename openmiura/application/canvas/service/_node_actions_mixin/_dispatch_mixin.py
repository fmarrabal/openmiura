"""openmiura.application.canvas.service._node_actions_mixin

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

class _LiveCanvasNodeActionsMixinDispatch:
    """Mixin: node actions methods on LiveCanvasService."""

    def execute_node_action(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        node_id: str,
        action: str,
        actor: str,
        reason: str = '',
        payload: dict[str, Any] | None = None,
        user_role: str = 'operator',
        user_key: str = '',
        session_id: str = 'canvas',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        inspected = self.get_node_inspector(
            gw,
            canvas_id=canvas_id,
            node_id=node_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            actor=actor,
        )
        if not inspected.get('ok'):
            return inspected
        scope = dict(inspected.get('scope') or {})
        node = dict(inspected.get('node') or {})
        inspected_node = dict(node)
        raw_node = next((item for item in gw.audit.list_canvas_nodes(canvas_id=canvas_id, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')) if str(item.get('node_id') or '') == str(node_id or '')), {})
        if raw_node:
            node = dict(raw_node)
            inspected_data = dict((inspected_node.get('data') or {}))
            if inspected_data:
                merged_data = dict(node.get('data') or {})
                merged_data.update(inspected_data)
                node['data'] = merged_data
        node_type = str(node.get('node_type') or '').strip().lower()
        data = dict(node.get('data') or {})
        normalized_action = str(action or '').strip().lower()
        raw_payload = dict(payload or {})
        precheck = self._node_action_precheck(node=node, related=dict(inspected.get('related') or {}), action=normalized_action, actor=actor, payload=raw_payload)
        if not precheck.get('allowed'):
            self._safe_call(
                gw.audit, 'log_event', None, 'admin', 'canvas', str(actor or 'operator'), canvas_id,
                {'action': 'canvas_node_action_blocked', 'node_id': node_id, 'node_type': node_type, 'operator_action': normalized_action, 'reason': precheck.get('reason') or reason},
                tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'),
            )
            return {'ok': False, 'canvas_id': canvas_id, 'node_id': node_id, 'action': normalized_action, 'error': 'action_blocked', 'precheck': precheck, 'scope': scope}
        if precheck.get('requires_confirmation') and not bool(raw_payload.get('confirmed', False)):
            self._safe_call(
                gw.audit, 'log_event', None, 'admin', 'canvas', str(actor or 'operator'), canvas_id,
                {'action': 'canvas_node_action_confirmation_required', 'node_id': node_id, 'node_type': node_type, 'operator_action': normalized_action, 'reason': reason},
                tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'),
            )
            return {'ok': False, 'canvas_id': canvas_id, 'node_id': node_id, 'action': normalized_action, 'error': 'confirmation_required', 'precheck': precheck, 'scope': scope}
        result: dict[str, Any]
        if node_type == 'workflow':
            result = self._execute_workflow_action(gw, canvas_id=canvas_id, node_id=node_id, action=action, actor=actor, reason=reason, payload=payload, user_role=user_role, user_key=user_key, session_id=session_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, inspected=inspected, scope=scope, node=node, inspected_node=inspected_node, raw_node=raw_node, node_type=node_type, data=data, normalized_action=normalized_action, raw_payload=raw_payload, precheck=precheck)
        elif node_type == 'approval':
            result = self._execute_approval_action(gw, canvas_id=canvas_id, node_id=node_id, action=action, actor=actor, reason=reason, payload=payload, user_role=user_role, user_key=user_key, session_id=session_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, inspected=inspected, scope=scope, node=node, inspected_node=inspected_node, raw_node=raw_node, node_type=node_type, data=data, normalized_action=normalized_action, raw_payload=raw_payload, precheck=precheck)
        elif node_type in {'runtime', 'openclaw_runtime'}:
            result = self._execute_runtime_action(gw, canvas_id=canvas_id, node_id=node_id, action=action, actor=actor, reason=reason, payload=payload, user_role=user_role, user_key=user_key, session_id=session_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, inspected=inspected, scope=scope, node=node, inspected_node=inspected_node, raw_node=raw_node, node_type=node_type, data=data, normalized_action=normalized_action, raw_payload=raw_payload, precheck=precheck)
        elif node_type in {'baseline_promotion', 'policy_baseline_promotion'}:
            result = self._execute_baseline_promotion_action(gw, canvas_id=canvas_id, node_id=node_id, action=action, actor=actor, reason=reason, payload=payload, user_role=user_role, user_key=user_key, session_id=session_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, inspected=inspected, scope=scope, node=node, inspected_node=inspected_node, raw_node=raw_node, node_type=node_type, data=data, normalized_action=normalized_action, raw_payload=raw_payload, precheck=precheck)
        else:
            raise ValueError('Unsupported node action')
        refreshed = self.get_node_inspector(
            gw,
            canvas_id=canvas_id,
            node_id=node_id,
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
            actor=actor,
        )
        self._safe_call(
            gw.audit, 'log_event', None, 'admin', 'canvas', str(actor or 'operator'), canvas_id,
            {'action': 'canvas_node_action_executed', 'node_id': node_id, 'node_type': node_type, 'operator_action': normalized_action, 'reason': reason, 'reconciled': bool(refreshed.get('ok'))},
            tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'),
        )
        result_ok = True
        result_error = ''
        if isinstance(result, dict):
            result_ok = bool(result.get('ok', True))
            result_error = str(result.get('error') or '').strip()
        return {
            'ok': result_ok,
            'canvas_id': canvas_id,
            'node_id': node_id,
            'action': normalized_action,
            'error': result_error,
            'precheck': precheck,
            'result': result,
            'reconciled': bool(refreshed.get('ok')),
            'refresh': refreshed if refreshed.get('ok') else {},
            'scope': scope,
        }

    def _execute_workflow_action(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id,
        node_id,
        action,
        actor,
        reason,
        payload,
        user_role,
        user_key,
        session_id,
        tenant_id,
        workspace_id,
        environment,
        inspected,
        scope,
        node,
        inspected_node,
        raw_node,
        node_type,
        data,
        normalized_action,
        raw_payload,
        precheck,
    ) -> dict[str, Any]:
        workflow_id = str(data.get('workflow_id') or (inspected.get('references') or {}).get('workflow_ids', [''])[0] or '').strip()
        if not workflow_id:
            raise ValueError('workflow node missing workflow_id')
        result = self.operator_console_service.workflow_action(
            gw, workflow_id=workflow_id, action=normalized_action, actor=actor, reason=reason,
            tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'),
        )
        return result

    def _execute_approval_action(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id,
        node_id,
        action,
        actor,
        reason,
        payload,
        user_role,
        user_key,
        session_id,
        tenant_id,
        workspace_id,
        environment,
        inspected,
        scope,
        node,
        inspected_node,
        raw_node,
        node_type,
        data,
        normalized_action,
        raw_payload,
        precheck,
    ) -> dict[str, Any]:
        approval_id = str(data.get('approval_id') or (inspected.get('references') or {}).get('approval_ids', [''])[0] or '').strip()
        if not approval_id:
            raise ValueError('approval node missing approval_id')
        result = self.operator_console_service.approval_action(
            gw, approval_id=approval_id, action=normalized_action, actor=actor, reason=reason,
            tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'),
        )
        return result

    def _execute_runtime_action(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id,
        node_id,
        action,
        actor,
        reason,
        payload,
        user_role,
        user_key,
        session_id,
        tenant_id,
        workspace_id,
        environment,
        inspected,
        scope,
        node,
        inspected_node,
        raw_node,
        node_type,
        data,
        normalized_action,
        raw_payload,
        precheck,
    ) -> dict[str, Any]:
        runtime_id = str(data.get('runtime_id') or '').strip()
        if not runtime_id:
            raise ValueError('runtime node missing runtime_id')
        selected_dispatch_id = str(
            raw_payload.get('dispatch_id')
            or (((inspected.get('related') or {}).get('runtime_runboard') or {}).get('latest_run') or {}).get('dispatch_id')
            or ''
        ).strip()
        if normalized_action == 'health_check':
            result = self.openclaw_adapter_service.check_runtime_health(
                gw, runtime_id=runtime_id, actor=actor, probe=str(raw_payload.get('probe') or 'ready'),
                user_role=str(user_role or 'operator'), user_key=str(user_key or actor or ''),
                session_id=str(session_id or f'canvas:{canvas_id}'), tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'),
            )
        elif normalized_action == 'cancel_run':
            if not selected_dispatch_id:
                raise ValueError('runtime action requires dispatch_id or latest_run')
            result = self.openclaw_adapter_service.cancel_dispatch(
                gw, dispatch_id=selected_dispatch_id, actor=actor, reason=reason,
                user_role=str(user_role or 'operator'), user_key=str(user_key or actor or ''),
                session_id=str(session_id or f'canvas:{canvas_id}'), tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'),
            )
        elif normalized_action == 'retry_run':
            if not selected_dispatch_id:
                raise ValueError('runtime action requires dispatch_id or latest_run')
            result = self.openclaw_adapter_service.retry_dispatch(
                gw, dispatch_id=selected_dispatch_id, actor=actor, reason=reason,
                payload_override=dict(raw_payload.get('payload_override') or {}),
                action_override=str(raw_payload.get('action_override') or ''),
                agent_id_override=str(raw_payload.get('agent_id_override') or ''),
                user_role=str(user_role or 'operator'), user_key=str(user_key or actor or ''),
                session_id=str(session_id or f'canvas:{canvas_id}'), tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'),
            )
        elif normalized_action in {'manual_close', 'reconcile_run'}:
            if not selected_dispatch_id:
                raise ValueError('runtime action requires dispatch_id or latest_run')
            target_status = str(raw_payload.get('target_status') or raw_payload.get('manual_status') or ('cancelled' if normalized_action == 'manual_close' else '')).strip().lower()
            result = self.openclaw_adapter_service.reconcile_dispatch(
                gw, dispatch_id=selected_dispatch_id, actor=actor, target_status=target_status, reason=reason,
                user_role=str(user_role or 'operator'), user_key=str(user_key or actor or ''),
                session_id=str(session_id or f'canvas:{canvas_id}'), tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'),
            )
        elif normalized_action == 'poll_run':
            if not selected_dispatch_id:
                raise ValueError('runtime action requires dispatch_id or latest_run')
            result = self.openclaw_adapter_service.poll_dispatch(
                gw, dispatch_id=selected_dispatch_id, actor=actor, reason=reason,
                user_role=str(user_role or 'operator'), user_key=str(user_key or actor or ''),
                session_id=str(session_id or f'canvas:{canvas_id}'), tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'),
            )
        elif normalized_action == 'recover_stale_runs':
            result = self.openclaw_adapter_service.recover_stale_dispatches(
                gw, runtime_id=runtime_id, actor=actor, reason=reason,
                limit=int(raw_payload.get('limit') or 25),
                user_role=str(user_role or 'operator'), user_key=str(user_key or actor or ''),
                session_id=str(session_id or f'canvas:{canvas_id}'), tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'),
            )
        elif normalized_action in {'simulate_portfolio_calendar', 'detect_portfolio_drift', 'report_portfolio_policy_conformance', 'report_portfolio_policy_baseline_drift', 'reconcile_portfolio_custody_anchors', 'validate_portfolio_providers', 'attest_portfolio_custody_anchor', 'request_portfolio_policy_deviation_exception', 'approve_portfolio_policy_deviation_exception', 'reject_portfolio_policy_deviation_exception', 'request_portfolio_approval', 'approve_portfolio_approval', 'reject_portfolio_approval', 'export_portfolio_attestation', 'export_portfolio_postmortem', 'export_portfolio_evidence_package', 'verify_portfolio_evidence_artifact', 'restore_portfolio_evidence_artifact', 'prune_portfolio_evidence_packages'}:
            portfolios = dict((inspected.get('related') or {}).get('runtime_alert_governance_portfolios') or {})
            selected_portfolio_id = str(raw_payload.get('portfolio_id') or (((portfolios.get('items') or [{}])[0]).get('portfolio_id')) or '').strip()
            if not selected_portfolio_id:
                raise ValueError('portfolio action requires portfolio_id or an available portfolio')
            if normalized_action == 'simulate_portfolio_calendar':
                result = self.openclaw_recovery_scheduler_service.simulate_runtime_alert_governance_portfolio(
                    gw,
                    portfolio_id=selected_portfolio_id,
                    actor=actor,
                    now_ts=float(raw_payload.get('now_ts')) if raw_payload.get('now_ts') is not None else None,
                    dry_run=bool(raw_payload.get('dry_run', True)),
                    auto_reschedule=bool(raw_payload.get('auto_reschedule')) if raw_payload.get('auto_reschedule') is not None else None,
                    persist_schedule=bool(raw_payload.get('persist_schedule', False)),
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                )
            elif normalized_action == 'detect_portfolio_drift':
                result = self.openclaw_recovery_scheduler_service.detect_runtime_alert_governance_portfolio_drift(
                    gw,
                    portfolio_id=selected_portfolio_id,
                    actor=actor,
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                    persist_metadata=bool(raw_payload.get('persist_metadata', True)),
                )
            elif normalized_action == 'report_portfolio_policy_conformance':
                result = self.openclaw_recovery_scheduler_service.get_runtime_alert_governance_portfolio_policy_conformance(
                    gw,
                    portfolio_id=selected_portfolio_id,
                    actor=actor,
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                    persist_metadata=bool(raw_payload.get('persist_metadata', True)),
                )
            elif normalized_action == 'report_portfolio_policy_baseline_drift':
                result = self.openclaw_recovery_scheduler_service.get_runtime_alert_governance_portfolio_policy_baseline_drift(
                    gw,
                    portfolio_id=selected_portfolio_id,
                    actor=actor,
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                    persist_metadata=bool(raw_payload.get('persist_metadata', True)),
                )
            elif normalized_action == 'reconcile_portfolio_custody_anchors':
                result = self.openclaw_recovery_scheduler_service.reconcile_runtime_alert_governance_portfolio_custody_anchors(
                    gw,
                    portfolio_id=selected_portfolio_id,
                    actor=actor,
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                )
            elif normalized_action == 'validate_portfolio_providers':
                result = self.openclaw_recovery_scheduler_service.validate_runtime_alert_governance_portfolio_provider_integrations(
                    gw,
                    portfolio_id=selected_portfolio_id,
                    actor=actor,
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                )
            elif normalized_action == 'attest_portfolio_custody_anchor':
                result = self.openclaw_recovery_scheduler_service.attest_runtime_alert_governance_portfolio_custody_anchor(
                    gw,
                    portfolio_id=selected_portfolio_id,
                    actor=actor,
                    package_id=raw_payload.get('package_id'),
                    control_plane_id=raw_payload.get('control_plane_id'),
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                )
            elif normalized_action == 'request_portfolio_policy_deviation_exception':
                result = self.openclaw_recovery_scheduler_service.request_runtime_alert_governance_portfolio_policy_deviation_exception(
                    gw,
                    portfolio_id=selected_portfolio_id,
                    deviation_id=str(raw_payload.get('deviation_id') or ''),
                    actor=actor,
                    reason=reason,
                    ttl_s=int(raw_payload.get('ttl_s')) if raw_payload.get('ttl_s') is not None else None,
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                )
            elif normalized_action in {'approve_portfolio_policy_deviation_exception', 'reject_portfolio_policy_deviation_exception'}:
                approval_id = str(raw_payload.get('approval_id') or '').strip()
                if not approval_id:
                    approvals = self.openclaw_recovery_scheduler_service.list_runtime_alert_governance_portfolio_policy_deviation_exceptions(
                        gw,
                        portfolio_id=selected_portfolio_id,
                        tenant_id=scope.get('tenant_id'),
                        workspace_id=scope.get('workspace_id'),
                        environment=scope.get('environment'),
                    )
                    items = list(((approvals.get('deviation_exceptions') or {}).get('items') or []))
                    for item in items:
                        if str(item.get('status') or '') == 'pending_approval' and str(item.get('approval_id') or '').strip():
                            approval_id = str(item.get('approval_id') or '').strip()
                            break
                if not approval_id:
                    raise ValueError('portfolio policy deviation action requires approval_id or a pending exception')
                result = self.openclaw_recovery_scheduler_service.decide_runtime_alert_governance_portfolio_policy_deviation_exception(
                    gw,
                    approval_id=approval_id,
                    actor=actor,
                    decision='approve' if normalized_action == 'approve_portfolio_policy_deviation_exception' else 'reject',
                    reason=reason,
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                )
            elif normalized_action == 'request_portfolio_approval':
                result = self.openclaw_recovery_scheduler_service.approve_runtime_alert_governance_portfolio(
                    gw,
                    portfolio_id=selected_portfolio_id,
                    actor=actor,
                    reason=str(reason or raw_payload.get('reason') or ''),
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                )
            elif normalized_action == 'export_portfolio_attestation':
                result = self.openclaw_recovery_scheduler_service.export_runtime_alert_governance_portfolio_attestation(
                    gw,
                    portfolio_id=selected_portfolio_id,
                    actor=actor,
                    attestation_id=raw_payload.get('attestation_id'),
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                )
            elif normalized_action == 'export_portfolio_postmortem':
                result = self.openclaw_recovery_scheduler_service.export_runtime_alert_governance_portfolio_postmortem(
                    gw,
                    portfolio_id=selected_portfolio_id,
                    actor=actor,
                    attestation_id=raw_payload.get('attestation_id'),
                    timeline_limit=int(raw_payload.get('timeline_limit')) if raw_payload.get('timeline_limit') is not None else None,
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                )
            elif normalized_action == 'export_portfolio_evidence_package':
                result = self.openclaw_recovery_scheduler_service.export_runtime_alert_governance_portfolio_evidence_package(
                    gw,
                    portfolio_id=selected_portfolio_id,
                    actor=actor,
                    attestation_id=raw_payload.get('attestation_id'),
                    timeline_limit=int(raw_payload.get('timeline_limit')) if raw_payload.get('timeline_limit') is not None else None,
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                )
            elif normalized_action == 'verify_portfolio_evidence_artifact':
                result = self.openclaw_recovery_scheduler_service.verify_runtime_alert_governance_portfolio_evidence_artifact(
                    gw,
                    portfolio_id=selected_portfolio_id,
                    actor=actor,
                    package_id=raw_payload.get('package_id'),
                    artifact=raw_payload.get('artifact'),
                    artifact_b64=raw_payload.get('artifact_b64'),
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                )
            elif normalized_action == 'restore_portfolio_evidence_artifact':
                result = self.openclaw_recovery_scheduler_service.restore_runtime_alert_governance_portfolio_evidence_artifact(
                    gw,
                    portfolio_id=selected_portfolio_id,
                    actor=actor,
                    package_id=raw_payload.get('package_id'),
                    artifact=raw_payload.get('artifact'),
                    artifact_b64=raw_payload.get('artifact_b64'),
                    persist_restore_session=bool(raw_payload.get('persist_restore_session', False)),
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                )
            elif normalized_action == 'prune_portfolio_evidence_packages':
                result = self.openclaw_recovery_scheduler_service.prune_runtime_alert_governance_portfolio_evidence_packages(
                    gw,
                    portfolio_id=selected_portfolio_id,
                    actor=actor,
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                )
            else:
                portfolio_detail = self.openclaw_recovery_scheduler_service.get_runtime_alert_governance_portfolio(
                    gw,
                    portfolio_id=selected_portfolio_id,
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                )
                approval_items = list(((portfolio_detail.get('approvals') or {}).get('items') or []))
                approval_id = str(raw_payload.get('approval_id') or (((approval_items or [{}])[0]).get('approval_id')) or '').strip()
                if not approval_id:
                    raise ValueError('portfolio approval action requires approval_id or a pending portfolio approval')
                result = self.openclaw_recovery_scheduler_service.decide_runtime_alert_governance_portfolio_approval(
                    gw,
                    approval_id=approval_id,
                    actor=actor,
                    decision='approve' if normalized_action == 'approve_portfolio_approval' else 'reject',
                    reason=str(reason or raw_payload.get('reason') or ''),
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                )
        elif normalized_action in {'ack_alert', 'silence_alert', 'escalate_alert', 'dispatch_alert_notification', 'approve_alert_escalation', 'reject_alert_escalation', 'simulate_alert_governance', 'activate_alert_governance', 'rollback_alert_governance', 'approve_governance_promotion', 'reject_governance_promotion'}:
            runtime_alerts = dict((inspected.get('related') or {}).get('runtime_alerts') or {})
            selected_alert_code = str(raw_payload.get('alert_code') or (((runtime_alerts.get('items') or [{}])[0]).get('code')) or '').strip()
            if not selected_alert_code:
                raise ValueError('runtime alert action requires alert_code or an active alert')
            if normalized_action == 'ack_alert':
                result = self.openclaw_recovery_scheduler_service.ack_runtime_alert(
                    gw, runtime_id=runtime_id, alert_code=selected_alert_code, actor=actor,
                    note=str(raw_payload.get('note') or reason or ''),
                    tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'),
                )
            elif normalized_action == 'silence_alert':
                result = self.openclaw_recovery_scheduler_service.silence_runtime_alert(
                    gw, runtime_id=runtime_id, alert_code=selected_alert_code, actor=actor,
                    silence_for_s=int(raw_payload.get('silence_for_s') or raw_payload.get('duration_s') or 0) or None,
                    reason=str(reason or raw_payload.get('reason') or ''),
                    tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'),
                )
            elif normalized_action == 'escalate_alert':
                result = self.openclaw_recovery_scheduler_service.escalate_runtime_alert(
                    gw, runtime_id=runtime_id, alert_code=selected_alert_code, actor=actor,
                    target=str(raw_payload.get('target') or ''),
                    reason=str(reason or raw_payload.get('reason') or ''),
                    level=int(raw_payload.get('level')) if raw_payload.get('level') is not None else None,
                    tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'),
                )
            elif normalized_action in {'approve_alert_escalation', 'reject_alert_escalation'}:
                approvals = dict((inspected.get('related') or {}).get('runtime_alert_approvals') or {})
                approval_id = str(raw_payload.get('approval_id') or (((approvals.get('items') or [{}])[0]).get('approval_id')) or '').strip()
                if not approval_id:
                    raise ValueError('alert escalation approval action requires approval_id or a pending approval')
                result = self.openclaw_recovery_scheduler_service.decide_alert_escalation_approval(
                    gw, approval_id=approval_id, actor=actor,
                    decision='approve' if normalized_action == 'approve_alert_escalation' else 'reject',
                    reason=str(reason or raw_payload.get('reason') or ''),
                    tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'),
                )
            elif normalized_action in {'approve_governance_promotion', 'reject_governance_promotion'}:
                approvals = dict((inspected.get('related') or {}).get('runtime_alert_governance_promotion_approvals') or {})
                approval_id = str(raw_payload.get('approval_id') or (((approvals.get('items') or [{}])[0]).get('approval_id')) or '').strip()
                if not approval_id:
                    raise ValueError('governance promotion approval action requires approval_id or a pending approval')
                result = self.openclaw_recovery_scheduler_service.decide_runtime_alert_governance_promotion_approval(
                    gw, approval_id=approval_id, actor=actor,
                    decision='approve' if normalized_action == 'approve_governance_promotion' else 'reject',
                    reason=str(reason or raw_payload.get('reason') or ''),
                    tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'),
                )
            elif normalized_action == 'simulate_alert_governance':
                result = self.openclaw_recovery_scheduler_service.simulate_runtime_alert_governance(
                    gw,
                    runtime_id=runtime_id,
                    candidate_policy=dict(raw_payload.get('candidate_policy') or raw_payload.get('policy') or {}),
                    merge_with_current=bool(raw_payload.get('merge_with_current', True)),
                    alert_code=selected_alert_code,
                    include_unchanged=bool(raw_payload.get('include_unchanged', True)),
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                    limit=int(raw_payload.get('limit') or 200),
                    now_ts=float(raw_payload.get('now_ts')) if raw_payload.get('now_ts') is not None else None,
                )
            elif normalized_action == 'activate_alert_governance':
                result = self.openclaw_recovery_scheduler_service.activate_runtime_alert_governance(
                    gw,
                    runtime_id=runtime_id,
                    actor=actor,
                    candidate_policy=dict(raw_payload.get('candidate_policy') or raw_payload.get('policy') or {}),
                    merge_with_current=bool(raw_payload.get('merge_with_current', True)),
                    reason=str(reason or raw_payload.get('reason') or ''),
                    alert_code=(str(raw_payload.get('alert_code') or selected_alert_code).strip() or None),
                    include_unchanged=bool(raw_payload.get('include_unchanged', True)),
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                    limit=int(raw_payload.get('limit') or 200),
                    now_ts=float(raw_payload.get('now_ts')) if raw_payload.get('now_ts') is not None else None,
                )
            elif normalized_action == 'rollback_alert_governance':
                versions = dict((inspected.get('related') or {}).get('runtime_alert_governance_versions') or {})
                version_id = str(raw_payload.get('version_id') or (((versions.get('current_version') or {}).get('version_id')) or (((versions.get('items') or [{}])[0]).get('version_id')) or '')).strip()
                if not version_id:
                    raise ValueError('alert governance rollback requires version_id or an available version')
                result = self.openclaw_recovery_scheduler_service.rollback_runtime_alert_governance_version(
                    gw,
                    runtime_id=runtime_id,
                    version_id=version_id,
                    actor=actor,
                    reason=str(reason or raw_payload.get('reason') or ''),
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                )
            else:
                result = self.openclaw_recovery_scheduler_service.dispatch_runtime_alert_notifications(
                    gw, runtime_id=runtime_id, alert_code=selected_alert_code, actor=actor,
                    workflow_action=str(raw_payload.get('workflow_action') or 'escalate'),
                    target_id=str(raw_payload.get('target_id') or raw_payload.get('target') or ''),
                    reason=str(reason or raw_payload.get('reason') or ''),
                    escalation_level=int(raw_payload.get('level')) if raw_payload.get('level') is not None else None,
                    tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'),
                )
        else:
            dispatch_payload = dict(raw_payload.get('payload') or raw_payload)
            dispatch_action = normalized_action
            effective_dispatch_action = dispatch_action
            dry_run = bool(raw_payload.get('dry_run', False))
            if normalized_action in {'dry_run', 'preview'}:
                dry_run = True
                dispatch_action = str(raw_payload.get('dispatch_action') or 'health_check')
                effective_dispatch_action = dispatch_action
                runtime_detail = gw.audit.get_openclaw_runtime(
                    runtime_id,
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                )
                if runtime_detail is not None:
                    allowed_actions = self.openclaw_adapter_service._allowed_actions(runtime_detail)
                    if allowed_actions and dispatch_action not in allowed_actions and 'dispatch' in allowed_actions:
                        effective_dispatch_action = 'dispatch'
                        dispatch_payload = dict(dispatch_payload or {})
                        dispatch_payload.setdefault('dispatch_action', dispatch_action)
            result = self.openclaw_adapter_service.dispatch(
                gw, runtime_id=runtime_id, actor=actor, action=effective_dispatch_action, payload=dispatch_payload,
                agent_id=str(raw_payload.get('agent_id') or data.get('agent_id') or ''),
                user_role=str(user_role or 'operator'),
                user_key=str(user_key or actor or ''),
                session_id=str(session_id or f'canvas:{canvas_id}'),
                tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'),
                dry_run=dry_run,
            )
        return result

    def _execute_baseline_promotion_action(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id,
        node_id,
        action,
        actor,
        reason,
        payload,
        user_role,
        user_key,
        session_id,
        tenant_id,
        workspace_id,
        environment,
        inspected,
        scope,
        node,
        inspected_node,
        raw_node,
        node_type,
        data,
        normalized_action,
        raw_payload,
        precheck,
    ) -> dict[str, Any]:
        promotion_id = str(data.get('promotion_id') or node.get('label') or '').strip()
        if not promotion_id:
            raise ValueError('baseline promotion node missing promotion_id')
        latest_simulation = dict(data.get('latest_simulation') or {})
        if normalized_action in {'simulate', 'simulate_baseline_promotion'}:
            result = self._baseline_promotion_action_simulate(gw, canvas_id=canvas_id, node_id=node_id, action=action, actor=actor, reason=reason, payload=payload, user_role=user_role, user_key=user_key, session_id=session_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, inspected=inspected, scope=scope, node=node, inspected_node=inspected_node, raw_node=raw_node, node_type=node_type, data=data, normalized_action=normalized_action, raw_payload=raw_payload, precheck=precheck, promotion_id=promotion_id, latest_simulation=latest_simulation)
        elif normalized_action in {'approve_simulation', 'reject_simulation'}:
            result = self._baseline_promotion_action_approve_simulation(gw, canvas_id=canvas_id, node_id=node_id, action=action, actor=actor, reason=reason, payload=payload, user_role=user_role, user_key=user_key, session_id=session_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, inspected=inspected, scope=scope, node=node, inspected_node=inspected_node, raw_node=raw_node, node_type=node_type, data=data, normalized_action=normalized_action, raw_payload=raw_payload, precheck=precheck, promotion_id=promotion_id, latest_simulation=latest_simulation)
        elif normalized_action in {'export_simulation_attestation', 'export_simulation_review_audit', 'export_simulation_evidence_package', 'verify_simulation_evidence_package', 'restore_simulation_evidence_package', 'reconcile_simulation_evidence_custody'}:
            result = self._baseline_promotion_action_export_simulation_attestation(gw, canvas_id=canvas_id, node_id=node_id, action=action, actor=actor, reason=reason, payload=payload, user_role=user_role, user_key=user_key, session_id=session_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, inspected=inspected, scope=scope, node=node, inspected_node=inspected_node, raw_node=raw_node, node_type=node_type, data=data, normalized_action=normalized_action, raw_payload=raw_payload, precheck=precheck, promotion_id=promotion_id, latest_simulation=latest_simulation)
        elif normalized_action == 'save_simulation_custody_routing_policy_pack':
            result = self._baseline_promotion_action_save_simulation_custody_routing_policy_pack(gw, canvas_id=canvas_id, node_id=node_id, action=action, actor=actor, reason=reason, payload=payload, user_role=user_role, user_key=user_key, session_id=session_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, inspected=inspected, scope=scope, node=node, inspected_node=inspected_node, raw_node=raw_node, node_type=node_type, data=data, normalized_action=normalized_action, raw_payload=raw_payload, precheck=precheck, promotion_id=promotion_id, latest_simulation=latest_simulation)
        elif normalized_action == 'promote_simulation_custody_routing_policy_pack_to_registry':
            result = self._baseline_promotion_action_promote_simulation_custody_routing_policy_pack_to_registry(gw, canvas_id=canvas_id, node_id=node_id, action=action, actor=actor, reason=reason, payload=payload, user_role=user_role, user_key=user_key, session_id=session_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, inspected=inspected, scope=scope, node=node, inspected_node=inspected_node, raw_node=raw_node, node_type=node_type, data=data, normalized_action=normalized_action, raw_payload=raw_payload, precheck=precheck, promotion_id=promotion_id, latest_simulation=latest_simulation)
        elif normalized_action == 'promote_simulation_custody_routing_policy_pack_to_catalog':
            result = self._baseline_promotion_action_promote_simulation_custody_routing_policy_pack_to_catalog(gw, canvas_id=canvas_id, node_id=node_id, action=action, actor=actor, reason=reason, payload=payload, user_role=user_role, user_key=user_key, session_id=session_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, inspected=inspected, scope=scope, node=node, inspected_node=inspected_node, raw_node=raw_node, node_type=node_type, data=data, normalized_action=normalized_action, raw_payload=raw_payload, precheck=precheck, promotion_id=promotion_id, latest_simulation=latest_simulation)
        elif normalized_action == 'share_registered_simulation_custody_routing_policy_pack':
            result = self._baseline_promotion_action_share_registered_simulation_custody_routing_policy_pack(gw, canvas_id=canvas_id, node_id=node_id, action=action, actor=actor, reason=reason, payload=payload, user_role=user_role, user_key=user_key, session_id=session_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, inspected=inspected, scope=scope, node=node, inspected_node=inspected_node, raw_node=raw_node, node_type=node_type, data=data, normalized_action=normalized_action, raw_payload=raw_payload, precheck=precheck, promotion_id=promotion_id, latest_simulation=latest_simulation)
        elif normalized_action == 'share_cataloged_simulation_custody_routing_policy_pack':
            result = self._baseline_promotion_action_share_cataloged_simulation_custody_routing_policy_pack(gw, canvas_id=canvas_id, node_id=node_id, action=action, actor=actor, reason=reason, payload=payload, user_role=user_role, user_key=user_key, session_id=session_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, inspected=inspected, scope=scope, node=node, inspected_node=inspected_node, raw_node=raw_node, node_type=node_type, data=data, normalized_action=normalized_action, raw_payload=raw_payload, precheck=precheck, promotion_id=promotion_id, latest_simulation=latest_simulation)
        elif normalized_action in {'request_cataloged_simulation_custody_routing_policy_pack_review', 'claim_cataloged_simulation_custody_routing_policy_pack_review', 'add_cataloged_simulation_custody_routing_policy_pack_review_note', 'submit_cataloged_simulation_custody_routing_policy_pack_review_decision'}:
            result = self._baseline_promotion_action_request_cataloged_simulation_custody_routing_policy_pack_review(gw, canvas_id=canvas_id, node_id=node_id, action=action, actor=actor, reason=reason, payload=payload, user_role=user_role, user_key=user_key, session_id=session_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, inspected=inspected, scope=scope, node=node, inspected_node=inspected_node, raw_node=raw_node, node_type=node_type, data=data, normalized_action=normalized_action, raw_payload=raw_payload, precheck=precheck, promotion_id=promotion_id, latest_simulation=latest_simulation)
        elif normalized_action in {'request_cataloged_simulation_custody_routing_policy_pack_approval', 'reject_cataloged_simulation_custody_routing_policy_pack_approval', 'curate_cataloged_simulation_custody_routing_policy_pack', 'approve_cataloged_simulation_custody_routing_policy_pack', 'deprecate_cataloged_simulation_custody_routing_policy_pack', 'stage_cataloged_simulation_custody_routing_policy_pack_release', 'release_cataloged_simulation_custody_routing_policy_pack', 'advance_cataloged_simulation_custody_routing_policy_pack_rollout', 'pause_cataloged_simulation_custody_routing_policy_pack_rollout', 'resume_cataloged_simulation_custody_routing_policy_pack_rollout', 'freeze_cataloged_simulation_custody_routing_policy_pack_rollout', 'unfreeze_cataloged_simulation_custody_routing_policy_pack_rollout', 'rollback_cataloged_simulation_custody_routing_policy_pack_rollout', 'rollback_cataloged_simulation_custody_routing_policy_pack_release', 'emergency_withdraw_cataloged_simulation_custody_routing_policy_pack_release', 'withdraw_cataloged_simulation_custody_routing_policy_pack_release'}:
            result = self._baseline_promotion_action_request_cataloged_simulation_custody_routing_policy_pack_approval(gw, canvas_id=canvas_id, node_id=node_id, action=action, actor=actor, reason=reason, payload=payload, user_role=user_role, user_key=user_key, session_id=session_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, inspected=inspected, scope=scope, node=node, inspected_node=inspected_node, raw_node=raw_node, node_type=node_type, data=data, normalized_action=normalized_action, raw_payload=raw_payload, precheck=precheck, promotion_id=promotion_id, latest_simulation=latest_simulation)
        elif normalized_action in {'export_cataloged_simulation_custody_routing_policy_pack_evidence_package', 'export_cataloged_simulation_custody_routing_policy_pack_signed_release_bundle', 'export_cataloged_simulation_custody_routing_policy_pack_compliance_report', 'export_cataloged_simulation_custody_routing_policy_pack_analytics_report'}:
            result = self._baseline_promotion_action_export_cataloged_simulation_custody_routing_policy_pack_evidence_package(gw, canvas_id=canvas_id, node_id=node_id, action=action, actor=actor, reason=reason, payload=payload, user_role=user_role, user_key=user_key, session_id=session_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, inspected=inspected, scope=scope, node=node, inspected_node=inspected_node, raw_node=raw_node, node_type=node_type, data=data, normalized_action=normalized_action, raw_payload=raw_payload, precheck=precheck, promotion_id=promotion_id, latest_simulation=latest_simulation)
        elif normalized_action in {'publish_cataloged_simulation_custody_routing_policy_pack_to_organizational_catalog_service', 'withdraw_cataloged_simulation_custody_routing_policy_pack_from_organizational_catalog_service', 'export_organizational_simulation_custody_routing_policy_pack_catalog_service_snapshot', 'reconcile_organizational_simulation_custody_routing_policy_pack_catalog_service', 'export_organizational_simulation_custody_routing_policy_pack_catalog_service_reconciliation_report'}:
            result = self._baseline_promotion_action_publish_cataloged_simulation_custody_routing_policy_pack_to_organizational_catalog_service(gw, canvas_id=canvas_id, node_id=node_id, action=action, actor=actor, reason=reason, payload=payload, user_role=user_role, user_key=user_key, session_id=session_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, inspected=inspected, scope=scope, node=node, inspected_node=inspected_node, raw_node=raw_node, node_type=node_type, data=data, normalized_action=normalized_action, raw_payload=raw_payload, precheck=precheck, promotion_id=promotion_id, latest_simulation=latest_simulation)
        elif normalized_action == 'export_cataloged_simulation_custody_routing_policy_pack_attestation':
            result = self._baseline_promotion_action_export_cataloged_simulation_custody_routing_policy_pack_attestation(gw, canvas_id=canvas_id, node_id=node_id, action=action, actor=actor, reason=reason, payload=payload, user_role=user_role, user_key=user_key, session_id=session_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, inspected=inspected, scope=scope, node=node, inspected_node=inspected_node, raw_node=raw_node, node_type=node_type, data=data, normalized_action=normalized_action, raw_payload=raw_payload, precheck=precheck, promotion_id=promotion_id, latest_simulation=latest_simulation)
        elif normalized_action in {'bind_cataloged_simulation_custody_routing_policy_pack_effective_policy', 'unbind_cataloged_simulation_custody_routing_policy_pack_effective_policy'}:
            result = self._baseline_promotion_action_bind_cataloged_simulation_custody_routing_policy_pack_effective_policy(gw, canvas_id=canvas_id, node_id=node_id, action=action, actor=actor, reason=reason, payload=payload, user_role=user_role, user_key=user_key, session_id=session_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, inspected=inspected, scope=scope, node=node, inspected_node=inspected_node, raw_node=raw_node, node_type=node_type, data=data, normalized_action=normalized_action, raw_payload=raw_payload, precheck=precheck, promotion_id=promotion_id, latest_simulation=latest_simulation)
        elif normalized_action in {'simulate_simulation_custody_routing', 'replay_simulation_custody_routing', 'replay_saved_simulation_custody_routing_policy_pack', 'replay_registered_simulation_custody_routing_policy_pack', 'replay_cataloged_simulation_custody_routing_policy_pack', 'replay_organizational_simulation_custody_routing_policy_pack'}:
            result = self._baseline_promotion_action_simulate_simulation_custody_routing(gw, canvas_id=canvas_id, node_id=node_id, action=action, actor=actor, reason=reason, payload=payload, user_role=user_role, user_key=user_key, session_id=session_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, inspected=inspected, scope=scope, node=node, inspected_node=inspected_node, raw_node=raw_node, node_type=node_type, data=data, normalized_action=normalized_action, raw_payload=raw_payload, precheck=precheck, promotion_id=promotion_id, latest_simulation=latest_simulation)
        elif normalized_action in {'acknowledge_simulation_custody_alert', 'mute_simulation_custody_alert', 'unmute_simulation_custody_alert', 'resolve_simulation_custody_alert', 'claim_simulation_custody_alert', 'assign_simulation_custody_alert', 'release_simulation_custody_alert', 'reroute_simulation_custody_alert', 'handoff_simulation_custody_alert'}:
            result = self._baseline_promotion_action_acknowledge_simulation_custody_alert(gw, canvas_id=canvas_id, node_id=node_id, action=action, actor=actor, reason=reason, payload=payload, user_role=user_role, user_key=user_key, session_id=session_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, inspected=inspected, scope=scope, node=node, inspected_node=inspected_node, raw_node=raw_node, node_type=node_type, data=data, normalized_action=normalized_action, raw_payload=raw_payload, precheck=precheck, promotion_id=promotion_id, latest_simulation=latest_simulation)
        elif normalized_action in {'create_rollout', 'create_and_approve_rollout'}:
            result = self._baseline_promotion_action_create_rollout(gw, canvas_id=canvas_id, node_id=node_id, action=action, actor=actor, reason=reason, payload=payload, user_role=user_role, user_key=user_key, session_id=session_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, inspected=inspected, scope=scope, node=node, inspected_node=inspected_node, raw_node=raw_node, node_type=node_type, data=data, normalized_action=normalized_action, raw_payload=raw_payload, precheck=precheck, promotion_id=promotion_id, latest_simulation=latest_simulation)
        elif normalized_action == 'export_attestation':
            result = self._baseline_promotion_action_export_attestation(gw, canvas_id=canvas_id, node_id=node_id, action=action, actor=actor, reason=reason, payload=payload, user_role=user_role, user_key=user_key, session_id=session_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, inspected=inspected, scope=scope, node=node, inspected_node=inspected_node, raw_node=raw_node, node_type=node_type, data=data, normalized_action=normalized_action, raw_payload=raw_payload, precheck=precheck, promotion_id=promotion_id, latest_simulation=latest_simulation)
        elif normalized_action == 'export_postmortem':
            result = self._baseline_promotion_action_export_postmortem(gw, canvas_id=canvas_id, node_id=node_id, action=action, actor=actor, reason=reason, payload=payload, user_role=user_role, user_key=user_key, session_id=session_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, inspected=inspected, scope=scope, node=node, inspected_node=inspected_node, raw_node=raw_node, node_type=node_type, data=data, normalized_action=normalized_action, raw_payload=raw_payload, precheck=precheck, promotion_id=promotion_id, latest_simulation=latest_simulation)
        else:
            result = self.openclaw_recovery_scheduler_service.decide_runtime_alert_governance_baseline_promotion(
                gw,
                promotion_id=promotion_id,
                actor=actor,
                decision=normalized_action,
                reason=reason,
                tenant_id=scope.get('tenant_id'),
                workspace_id=scope.get('workspace_id'),
                environment=scope.get('environment'),
            )
        return result

    def _node_action_precheck(self, *, node: dict[str, Any], related: dict[str, Any] | None, action: str, actor: str = '', payload: dict[str, Any] | None = None) -> dict[str, Any]:
        normalized_action = str(action or '').strip().lower()
        node_type = str(node.get('node_type') or '').strip().lower()
        available = set(self._node_available_actions(node, related=related))
        if normalized_action not in available:
            return {'allowed': False, 'reason': 'action_not_available', 'requires_confirmation': False, 'warnings': []}
        warnings: list[str] = []
        if node_type == 'workflow':
            workflow = dict((related or {}).get('workflow', {}).get('workflow') or {})
            status = str(workflow.get('status') or '').strip().lower()
            if normalized_action == 'run' and status in {'running', 'waiting_approval'}:
                return {'allowed': False, 'reason': 'workflow_already_active', 'requires_confirmation': False, 'warnings': []}
            if normalized_action == 'cancel' and status not in {'created', 'pending', 'running', 'waiting_approval'}:
                return {'allowed': False, 'reason': 'workflow_not_cancellable', 'requires_confirmation': False, 'warnings': []}
        elif node_type == 'approval':
            approval = dict((related or {}).get('approval') or {})
            status = str(approval.get('status') or '').strip().lower()
            assigned_to = str(approval.get('assigned_to') or '').strip()
            actor_key = str(actor or '').strip()
            if status != 'pending':
                return {'allowed': False, 'reason': 'approval_not_pending', 'requires_confirmation': False, 'warnings': []}
            if assigned_to and actor_key and assigned_to != actor_key:
                return {'allowed': False, 'reason': 'approval_claimed_by_other', 'requires_confirmation': False, 'warnings': []}
        elif node_type in {'runtime', 'openclaw_runtime'}:
            runtime = dict((related or {}).get('runtime', {}).get('runtime') or {})
            health = dict((related or {}).get('runtime', {}).get('health') or {})
            if str(health.get('status') or '') in {'unhealthy', 'degraded'}:
                warnings.append(f"runtime_health:{health.get('status')}")
            if bool(health.get('stale')):
                warnings.append('runtime_health:stale')
            if not runtime:
                return {'allowed': False, 'reason': 'runtime_not_found', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action in {'ack_alert', 'silence_alert', 'escalate_alert', 'dispatch_alert_notification', 'approve_alert_escalation', 'reject_alert_escalation'}:
                alerts = dict((related or {}).get('runtime_alerts') or {})
                if not list(alerts.get('items') or []):
                    return {'allowed': False, 'reason': 'no_runtime_alerts', 'requires_confirmation': False, 'warnings': warnings}
                if normalized_action in {'approve_alert_escalation', 'reject_alert_escalation'}:
                    warnings.append('approval_action:alert_escalation')
                    approvals = dict((related or {}).get('runtime_alert_approvals') or {})
                    if not list(approvals.get('items') or []):
                        return {'allowed': False, 'reason': 'no_alert_escalation_approvals', 'requires_confirmation': False, 'warnings': warnings}
                if normalized_action == 'dispatch_alert_notification':
                    targets = dict((related or {}).get('runtime_notification_targets') or {})
                    if not list(targets.get('items') or []):
                        warnings.append('alert_notification_targets:missing')
            if normalized_action in {'approve_governance_promotion', 'reject_governance_promotion'}:
                warnings.append('approval_action:governance_promotion')
                approvals = dict((related or {}).get('runtime_alert_governance_promotion_approvals') or {})
                if not list(approvals.get('items') or []):
                    return {'allowed': False, 'reason': 'no_governance_promotion_approvals', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action in {'simulate_portfolio_calendar', 'detect_portfolio_drift', 'report_portfolio_policy_conformance', 'report_portfolio_policy_baseline_drift', 'reconcile_portfolio_custody_anchors', 'validate_portfolio_providers', 'attest_portfolio_custody_anchor', 'request_portfolio_policy_deviation_exception', 'approve_portfolio_policy_deviation_exception', 'reject_portfolio_policy_deviation_exception', 'request_portfolio_approval', 'approve_portfolio_approval', 'reject_portfolio_approval', 'export_portfolio_attestation', 'export_portfolio_postmortem', 'export_portfolio_evidence_package', 'verify_portfolio_evidence_artifact', 'restore_portfolio_evidence_artifact', 'prune_portfolio_evidence_packages'}:
                portfolios = dict((related or {}).get('runtime_alert_governance_portfolios') or {})
                portfolio_items = list(portfolios.get('items') or [])
                if not portfolio_items:
                    return {'allowed': False, 'reason': 'no_governance_portfolios', 'requires_confirmation': False, 'warnings': warnings}
                if normalized_action in {'approve_portfolio_approval', 'reject_portfolio_approval'}:
                    warnings.append('approval_action:governance_portfolio')
                    pending_found = any(int((item.get('approval_summary') or {}).get('pending_count') or 0) > 0 for item in portfolio_items)
                    if not pending_found:
                        return {'allowed': False, 'reason': 'no_portfolio_approvals', 'requires_confirmation': False, 'warnings': warnings}
                if normalized_action in {'approve_portfolio_policy_deviation_exception', 'reject_portfolio_policy_deviation_exception'}:
                    warnings.append('approval_action:governance_portfolio_deviation')
        elif node_type in {'baseline_promotion', 'policy_baseline_promotion'}:
            promotion_detail = dict((related or {}).get('baseline_promotion') or {})
            if not promotion_detail.get('ok'):
                return {'allowed': False, 'reason': 'baseline_promotion_not_found', 'requires_confirmation': False, 'warnings': warnings}
            release = dict(promotion_detail.get('release') or {})
            promotion = dict(promotion_detail.get('baseline_promotion') or {})
            latest_simulation = dict((node.get('data') or {}).get('latest_simulation') or {})
            status = str(release.get('status') or '').strip().lower()
            paused = bool((promotion.get('pause_state') or {}).get('paused')) or status == 'paused'
            terminal = status in {'completed', 'rolled_back', 'rejected'}
            if normalized_action == 'simulate' and not str(promotion.get('catalog_id') or '').strip():
                return {'allowed': False, 'reason': 'baseline_promotion_not_simulatable', 'requires_confirmation': False, 'warnings': warnings}
            stored_simulation_packages = list(((promotion_detail.get('simulation_evidence_packages') or {}).get('items') or []))
            if normalized_action in {'export_simulation_attestation', 'export_simulation_review_audit', 'export_simulation_evidence_package'}:
                if not latest_simulation:
                    return {'allowed': False, 'reason': 'baseline_promotion_simulation_missing', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action in {'verify_simulation_evidence_package', 'restore_simulation_evidence_package', 'reconcile_simulation_evidence_custody'}:
                if not stored_simulation_packages and not str((((latest_simulation.get('export_state') or {}).get('latest_evidence_package') or {}).get('package_id')) or '').strip():
                    return {'allowed': False, 'reason': 'baseline_promotion_simulation_evidence_package_missing', 'requires_confirmation': False, 'warnings': warnings}
            custody_guard = dict((((promotion_detail.get('simulation_custody_monitoring') or {}).get('guard')) or {}))
            custody_alert_items = [dict(item) for item in list((((promotion_detail.get('simulation_custody_monitoring') or {}).get('alerts')) or {}).get('items') or [])]
            active_custody_alert = next((item for item in custody_alert_items if bool(item.get('active'))), {})
            muted_custody_alert = next((item for item in custody_alert_items if str(item.get('status') or '') == 'muted'), {})
            if bool(custody_guard.get('blocked')):
                warnings.append('baseline_promotion_simulation_custody:blocked')
            if normalized_action in {'save_simulation_custody_routing_policy_pack', 'promote_simulation_custody_routing_policy_pack_to_registry', 'promote_simulation_custody_routing_policy_pack_to_catalog', 'share_registered_simulation_custody_routing_policy_pack', 'share_cataloged_simulation_custody_routing_policy_pack'} and not latest_simulation:
                return {'allowed': False, 'reason': 'baseline_promotion_simulation_missing', 'requires_confirmation': False, 'warnings': warnings}
            catalog_registry = [
                dict(item or {})
                for item in list(((node.get('data') or {}).get('routing_policy_pack_catalog') or []) if isinstance((node.get('data') or {}).get('routing_policy_pack_catalog'), list) else [])
                if isinstance(item, dict)
            ]
            if not catalog_registry:
                catalog_registry = self._baseline_promotion_simulation_custody_registry_policy_packs(
                    list(((node.get('data') or {}).get('routing_policy_pack_registry') or []))
                )
            organizational_service = dict((related or {}).get('routing_policy_pack_organizational_catalog_service') or {})
            organizational_entries = [dict(item or {}) for item in list(organizational_service.get('entries') or []) if isinstance(item, dict)]
            if normalized_action in {'request_cataloged_simulation_custody_routing_policy_pack_review', 'claim_cataloged_simulation_custody_routing_policy_pack_review', 'add_cataloged_simulation_custody_routing_policy_pack_review_note', 'submit_cataloged_simulation_custody_routing_policy_pack_review_decision', 'request_cataloged_simulation_custody_routing_policy_pack_approval', 'reject_cataloged_simulation_custody_routing_policy_pack_approval', 'curate_cataloged_simulation_custody_routing_policy_pack', 'approve_cataloged_simulation_custody_routing_policy_pack', 'deprecate_cataloged_simulation_custody_routing_policy_pack', 'export_cataloged_simulation_custody_routing_policy_pack_attestation', 'export_cataloged_simulation_custody_routing_policy_pack_evidence_package', 'export_cataloged_simulation_custody_routing_policy_pack_signed_release_bundle', 'export_cataloged_simulation_custody_routing_policy_pack_compliance_report', 'export_cataloged_simulation_custody_routing_policy_pack_analytics_report', 'publish_cataloged_simulation_custody_routing_policy_pack_to_organizational_catalog_service', 'withdraw_cataloged_simulation_custody_routing_policy_pack_from_organizational_catalog_service', 'bind_cataloged_simulation_custody_routing_policy_pack_effective_policy', 'unbind_cataloged_simulation_custody_routing_policy_pack_effective_policy', 'stage_cataloged_simulation_custody_routing_policy_pack_release', 'release_cataloged_simulation_custody_routing_policy_pack', 'advance_cataloged_simulation_custody_routing_policy_pack_rollout', 'pause_cataloged_simulation_custody_routing_policy_pack_rollout', 'resume_cataloged_simulation_custody_routing_policy_pack_rollout', 'freeze_cataloged_simulation_custody_routing_policy_pack_rollout', 'unfreeze_cataloged_simulation_custody_routing_policy_pack_rollout', 'rollback_cataloged_simulation_custody_routing_policy_pack_rollout', 'rollback_cataloged_simulation_custody_routing_policy_pack_release', 'emergency_withdraw_cataloged_simulation_custody_routing_policy_pack_release', 'withdraw_cataloged_simulation_custody_routing_policy_pack_release', 'replay_cataloged_simulation_custody_routing_policy_pack'} and not catalog_registry:
                return {'allowed': False, 'reason': 'baseline_promotion_simulation_custody_policy_pack_missing', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action == 'export_organizational_simulation_custody_routing_policy_pack_catalog_service_snapshot' and not organizational_entries:
                return {'allowed': False, 'reason': 'baseline_promotion_simulation_custody_organizational_policy_pack_missing', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action == 'replay_organizational_simulation_custody_routing_policy_pack' and not organizational_entries:
                return {'allowed': False, 'reason': 'baseline_promotion_simulation_custody_organizational_policy_pack_missing', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action in {'add_cataloged_simulation_custody_routing_policy_pack_review_note', 'submit_cataloged_simulation_custody_routing_policy_pack_review_decision'}:
                active_review_found = any(self._baseline_promotion_simulation_custody_catalog_pack_review_state(item) != 'not_requested' for item in catalog_registry)
                if not active_review_found:
                    return {'allowed': False, 'reason': 'baseline_promotion_simulation_custody_policy_pack_review_not_requested', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action == 'unbind_cataloged_simulation_custody_routing_policy_pack_effective_policy' and not any(isinstance(item, dict) for item in list((node.get('data') or {}).get('routing_policy_pack_bindings') or [])):
                return {'allowed': False, 'reason': 'baseline_promotion_simulation_custody_policy_pack_binding_missing', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action == 'export_cataloged_simulation_custody_routing_policy_pack_signed_release_bundle':
                releasable_pack_found = any(str(item.get('catalog_release_state') or 'draft') != 'draft' for item in catalog_registry)
                if not releasable_pack_found:
                    return {'allowed': False, 'reason': 'baseline_promotion_simulation_custody_policy_pack_release_bundle_not_ready', 'requires_confirmation': False, 'warnings': warnings}
            rollout_summaries = [self._baseline_promotion_simulation_custody_catalog_rollout_summary(item) for item in catalog_registry]
            if normalized_action == 'advance_cataloged_simulation_custody_routing_policy_pack_rollout' and not any(bool(item.get('enabled')) for item in rollout_summaries):
                return {'allowed': False, 'reason': 'baseline_promotion_simulation_custody_policy_pack_rollout_missing', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action == 'pause_cataloged_simulation_custody_routing_policy_pack_rollout' and not any(str(item.get('state') or '') == 'rolling_out' for item in rollout_summaries):
                return {'allowed': False, 'reason': 'baseline_promotion_simulation_custody_policy_pack_rollout_not_active', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action == 'resume_cataloged_simulation_custody_routing_policy_pack_rollout' and not any(bool(item.get('paused')) for item in rollout_summaries):
                return {'allowed': False, 'reason': 'baseline_promotion_simulation_custody_policy_pack_rollout_not_paused', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action == 'freeze_cataloged_simulation_custody_routing_policy_pack_rollout' and not any(bool(item.get('enabled')) for item in rollout_summaries):
                return {'allowed': False, 'reason': 'baseline_promotion_simulation_custody_policy_pack_rollout_missing', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action == 'unfreeze_cataloged_simulation_custody_routing_policy_pack_rollout' and not any(bool(item.get('frozen')) for item in rollout_summaries):
                return {'allowed': False, 'reason': 'baseline_promotion_simulation_custody_policy_pack_rollout_not_frozen', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action == 'rollback_cataloged_simulation_custody_routing_policy_pack_rollout' and not any(bool(item.get('enabled')) for item in rollout_summaries):
                return {'allowed': False, 'reason': 'baseline_promotion_simulation_custody_policy_pack_rollout_missing', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action == 'emergency_withdraw_cataloged_simulation_custody_routing_policy_pack_release' and not any(str(item.get('catalog_release_state') or 'draft') in {'staged', 'rolling_out', 'released'} for item in catalog_registry):
                return {'allowed': False, 'reason': 'baseline_promotion_simulation_custody_policy_pack_release_not_active', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action == 'rollback_cataloged_simulation_custody_routing_policy_pack_release' and not any(self._baseline_promotion_simulation_custody_catalog_previous_restore_candidate(item, catalog_packs=catalog_registry) for item in catalog_registry):
                return {'allowed': False, 'reason': 'baseline_promotion_simulation_custody_policy_pack_release_rollback_target_missing', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action in {'simulate_simulation_custody_routing', 'replay_simulation_custody_routing', 'replay_saved_simulation_custody_routing_policy_pack', 'replay_registered_simulation_custody_routing_policy_pack', 'replay_cataloged_simulation_custody_routing_policy_pack', 'replay_organizational_simulation_custody_routing_policy_pack'} and not (active_custody_alert or muted_custody_alert):
                replay_actions = {'replay_simulation_custody_routing', 'replay_saved_simulation_custody_routing_policy_pack', 'replay_registered_simulation_custody_routing_policy_pack', 'replay_cataloged_simulation_custody_routing_policy_pack', 'replay_organizational_simulation_custody_routing_policy_pack'}
                if normalized_action not in replay_actions:
                    return {'allowed': False, 'reason': 'baseline_promotion_simulation_custody_alert_missing', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action in {'acknowledge_simulation_custody_alert', 'mute_simulation_custody_alert', 'resolve_simulation_custody_alert', 'claim_simulation_custody_alert', 'assign_simulation_custody_alert', 'release_simulation_custody_alert', 'reroute_simulation_custody_alert', 'handoff_simulation_custody_alert'} and not active_custody_alert:
                return {'allowed': False, 'reason': 'baseline_promotion_simulation_custody_alert_missing', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action == 'unmute_simulation_custody_alert' and not muted_custody_alert:
                return {'allowed': False, 'reason': 'baseline_promotion_simulation_custody_alert_not_muted', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action == 'resolve_simulation_custody_alert':
                current_reconciliation = dict((promotion_detail.get('simulation_evidence_reconciliation') or {}).get('current') or {})
                if str((current_reconciliation.get('summary') or {}).get('overall_status') or '') == 'drifted':
                    return {'allowed': False, 'reason': 'baseline_promotion_simulation_custody_alert_still_drifted', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action == 'claim_simulation_custody_alert':
                current_owner_id = str(((active_custody_alert.get('ownership') or {}).get('owner_id')) or '')
                if current_owner_id and current_owner_id != actor:
                    return {'allowed': False, 'reason': 'baseline_promotion_simulation_custody_alert_already_owned', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action == 'release_simulation_custody_alert' and not str(((active_custody_alert.get('ownership') or {}).get('owner_id')) or '').strip():
                return {'allowed': False, 'reason': 'baseline_promotion_simulation_custody_alert_not_owned', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action in {'approve_simulation', 'reject_simulation'}:
                if not latest_simulation:
                    return {'allowed': False, 'reason': 'baseline_promotion_simulation_missing', 'requires_confirmation': False, 'warnings': warnings}
                if bool(latest_simulation.get('expired')):
                    return {'allowed': False, 'reason': 'baseline_promotion_simulation_expired', 'requires_confirmation': False, 'warnings': warnings}
                if bool(latest_simulation.get('stale')):
                    return {'allowed': False, 'reason': 'baseline_promotion_simulation_stale', 'requires_confirmation': False, 'warnings': warnings}
                if str((latest_simulation.get('validation') or {}).get('status') or '').strip().lower() != 'passed':
                    return {'allowed': False, 'reason': 'baseline_promotion_simulation_invalid', 'requires_confirmation': False, 'warnings': warnings}
                if not bool((latest_simulation.get('summary') or {}).get('approvable', False)):
                    return {'allowed': False, 'reason': 'baseline_promotion_simulation_not_approvable', 'requires_confirmation': False, 'warnings': warnings}
                if bool(latest_simulation.get('blocked')) and str(latest_simulation.get('why_blocked') or '') not in {'baseline_promotion_simulation_review_rejected'}:
                    return {'allowed': False, 'reason': str(latest_simulation.get('why_blocked') or 'baseline_promotion_simulation_blocked'), 'requires_confirmation': False, 'warnings': warnings}
                if normalized_action == 'approve_simulation':
                    if bool((latest_simulation.get('review') or {}).get('approved')):
                        return {'allowed': False, 'reason': 'baseline_promotion_simulation_already_approved', 'requires_confirmation': False, 'warnings': warnings}
                    if bool(((latest_simulation.get('review_state') or {}).get('rejected'))):
                        return {'allowed': False, 'reason': 'baseline_promotion_simulation_review_rejected', 'requires_confirmation': False, 'warnings': warnings}
                if normalized_action == 'reject_simulation' and bool(((latest_simulation.get('review_state') or {}).get('rejected'))):
                    return {'allowed': False, 'reason': 'baseline_promotion_simulation_already_rejected', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action in {'create_rollout', 'create_and_approve_rollout'}:
                if not latest_simulation:
                    return {'allowed': False, 'reason': 'baseline_promotion_simulation_missing', 'requires_confirmation': False, 'warnings': warnings}
                if bool(custody_guard.get('blocked')):
                    return {'allowed': False, 'reason': str(custody_guard.get('reason') or 'baseline_promotion_simulation_custody_drift_detected'), 'requires_confirmation': False, 'warnings': warnings}
                if bool(latest_simulation.get('expired')):
                    return {'allowed': False, 'reason': 'baseline_promotion_simulation_expired', 'requires_confirmation': False, 'warnings': warnings}
                if bool(latest_simulation.get('stale')):
                    return {'allowed': False, 'reason': 'baseline_promotion_simulation_stale', 'requires_confirmation': False, 'warnings': warnings}
                if bool(((latest_simulation.get('review_state') or {}).get('rejected'))):
                    return {'allowed': False, 'reason': 'baseline_promotion_simulation_review_rejected', 'requires_confirmation': False, 'warnings': warnings}
                if not bool((latest_simulation.get('review') or {}).get('approved')):
                    return {'allowed': False, 'reason': 'baseline_promotion_simulation_not_approved', 'requires_confirmation': False, 'warnings': warnings}
                if str((latest_simulation.get('validation') or {}).get('status') or '').strip().lower() != 'passed':
                    return {'allowed': False, 'reason': 'baseline_promotion_simulation_invalid', 'requires_confirmation': False, 'warnings': warnings}
                if not bool((latest_simulation.get('summary') or {}).get('approvable', False)):
                    return {'allowed': False, 'reason': 'baseline_promotion_simulation_not_approvable', 'requires_confirmation': False, 'warnings': warnings}
                if bool(latest_simulation.get('blocked')):
                    return {'allowed': False, 'reason': str(latest_simulation.get('why_blocked') or 'baseline_promotion_simulation_blocked'), 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action in {'approve', 'advance', 'resume'} and bool(custody_guard.get('blocked')):
                return {'allowed': False, 'reason': str(custody_guard.get('reason') or 'baseline_promotion_simulation_custody_drift_detected'), 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action == 'approve' and status not in {'pending_approval'}:
                return {'allowed': False, 'reason': 'baseline_promotion_not_approvable', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action == 'reject' and status not in {'pending_approval', 'approved', 'awaiting_advance', 'awaiting_advance_window', 'awaiting_dependencies'}:
                return {'allowed': False, 'reason': 'baseline_promotion_not_rejectable', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action == 'advance':
                if terminal:
                    return {'allowed': False, 'reason': 'baseline_promotion_not_advanceable', 'requires_confirmation': False, 'warnings': warnings}
                if paused:
                    return {'allowed': False, 'reason': 'baseline_promotion_paused', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action == 'pause' and (terminal or paused):
                return {'allowed': False, 'reason': 'baseline_promotion_not_pausable', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action == 'resume' and not paused:
                return {'allowed': False, 'reason': 'baseline_promotion_not_paused', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action == 'rollback' and terminal:
                return {'allowed': False, 'reason': 'baseline_promotion_not_rollbackable', 'requires_confirmation': False, 'warnings': warnings}
            if normalized_action.startswith('export_') and int((promotion_detail.get('analytics') or {}).get('timeline_count') or 0) == 0:
                warnings.append('baseline_promotion_timeline:empty')
        return {'allowed': True, 'reason': '', 'requires_confirmation': normalized_action in {'cancel', 'reject', 'cancel_run', 'manual_close', 'reconcile_run', 'escalate_alert', 'reject_alert_escalation', 'reject_governance_promotion', 'reject_portfolio_policy_deviation_exception', 'reject_portfolio_approval', 'prune_portfolio_evidence_packages', 'rollback'}, 'warnings': warnings}

