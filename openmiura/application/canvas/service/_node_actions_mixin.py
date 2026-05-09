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

class _LiveCanvasNodeActionsMixin:
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
            workflow_id = str(data.get('workflow_id') or (inspected.get('references') or {}).get('workflow_ids', [''])[0] or '').strip()
            if not workflow_id:
                raise ValueError('workflow node missing workflow_id')
            result = self.operator_console_service.workflow_action(
                gw, workflow_id=workflow_id, action=normalized_action, actor=actor, reason=reason,
                tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'),
            )
        elif node_type == 'approval':
            approval_id = str(data.get('approval_id') or (inspected.get('references') or {}).get('approval_ids', [''])[0] or '').strip()
            if not approval_id:
                raise ValueError('approval node missing approval_id')
            result = self.operator_console_service.approval_action(
                gw, approval_id=approval_id, action=normalized_action, actor=actor, reason=reason,
                tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'),
            )
        elif node_type in {'runtime', 'openclaw_runtime'}:
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
        elif node_type in {'baseline_promotion', 'policy_baseline_promotion'}:
            promotion_id = str(data.get('promotion_id') or node.get('label') or '').strip()
            if not promotion_id:
                raise ValueError('baseline promotion node missing promotion_id')
            latest_simulation = dict(data.get('latest_simulation') or {})
            if normalized_action in {'simulate', 'simulate_baseline_promotion'}:
                promotion_detail = dict((inspected.get('related') or {}).get('baseline_promotion') or {})
                baseline_promotion = dict(promotion_detail.get('baseline_promotion') or {})
                promotion_policy = dict(baseline_promotion.get('promotion_policy') or {})
                simulation_request = {
                    'catalog_id': str(baseline_promotion.get('catalog_id') or ''),
                    'candidate_baselines': dict(raw_payload.get('environment_policy_baselines') or raw_payload.get('candidate_baselines') or baseline_promotion.get('candidate_baselines') or {}),
                    'version': (str(raw_payload.get('version')).strip() if raw_payload.get('version') is not None else None),
                    'rollout_policy': (dict(raw_payload.get('rollout_policy') or {}) if 'rollout_policy' in raw_payload else dict(promotion_policy.get('rollout_policy') or {})),
                    'gate_policy': (dict(raw_payload.get('gate_policy') or {}) if 'gate_policy' in raw_payload else dict(promotion_policy.get('gate_policy') or {})),
                    'rollback_policy': (dict(raw_payload.get('rollback_policy') or {}) if 'rollback_policy' in raw_payload else dict(promotion_policy.get('rollback_policy') or {})),
                    'reason': str(reason or raw_payload.get('reason') or ''),
                }
                result = self.openclaw_recovery_scheduler_service.simulate_existing_runtime_alert_governance_baseline_promotion(
                    gw,
                    promotion_id=promotion_id,
                    actor=actor,
                    candidate_baselines=dict(simulation_request.get('candidate_baselines') or {}),
                    version=simulation_request.get('version'),
                    rollout_policy=dict(simulation_request.get('rollout_policy') or {}),
                    gate_policy=dict(simulation_request.get('gate_policy') or {}),
                    rollback_policy=dict(simulation_request.get('rollback_policy') or {}),
                    reason=reason,
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                )
                if result.get('ok'):
                    updated_data = dict(data)
                    updated_data['latest_simulation'] = self._baseline_promotion_simulation_state(
                        simulation=result,
                        actor=actor,
                        request=simulation_request,
                    )
                    node = dict((self._replace_node_data(
                        gw,
                        canvas_id=canvas_id,
                        node=node,
                        actor=actor,
                        data=updated_data,
                        tenant_id=scope.get('tenant_id'),
                        workspace_id=scope.get('workspace_id'),
                        environment=scope.get('environment'),
                    ) or {}).get('node') or node)
                    data = dict(node.get('data') or {})
                    result['canvas_simulation'] = dict(updated_data.get('latest_simulation') or {})
            elif normalized_action in {'approve_simulation', 'reject_simulation'}:
                review_result = self.openclaw_recovery_scheduler_service.review_runtime_alert_governance_baseline_promotion_simulation(
                    gw,
                    simulation=latest_simulation,
                    actor=actor,
                    decision='approve' if normalized_action == 'approve_simulation' else 'reject',
                    reason=str(reason or raw_payload.get('reason') or ''),
                    layer_id=(str(raw_payload.get('layer_id')).strip() if raw_payload.get('layer_id') is not None else None),
                    requested_role=(str(raw_payload.get('requested_role')).strip() if raw_payload.get('requested_role') is not None else None),
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                )
                if not review_result.get('ok'):
                    result = review_result
                else:
                    updated_state = self._baseline_promotion_simulation_state(
                        simulation=dict(review_result.get('simulation') or latest_simulation),
                        actor=str(latest_simulation.get('simulated_by') or actor or 'operator'),
                        request=dict(latest_simulation.get('request') or {}),
                        created_promotions=[dict(item) for item in list(latest_simulation.get('created_promotions') or [])],
                    )
                    updated_data = dict(data)
                    updated_data['latest_simulation'] = updated_state
                    node = dict((self._replace_node_data(
                        gw,
                        canvas_id=canvas_id,
                        node=node,
                        actor=actor,
                        data=updated_data,
                        tenant_id=scope.get('tenant_id'),
                        workspace_id=scope.get('workspace_id'),
                        environment=scope.get('environment'),
                    ) or {}).get('node') or node)
                    data = dict(node.get('data') or {})
                    result = {'ok': True, 'latest_simulation': updated_state, 'review_action': dict(review_result.get('review_action') or {})}
            elif normalized_action in {'export_simulation_attestation', 'export_simulation_review_audit', 'export_simulation_evidence_package', 'verify_simulation_evidence_package', 'restore_simulation_evidence_package', 'reconcile_simulation_evidence_custody'}:
                promotion_detail = dict((inspected.get('related') or {}).get('baseline_promotion') or {})
                package_id = str(raw_payload.get('package_id') or (((latest_simulation.get('export_state') or {}).get('latest_evidence_package') or {}).get('package_id')) or ((((promotion_detail.get('simulation_evidence_packages') or {}).get('items') or [{}])[0]).get('package_id')) or '').strip() or None
                if normalized_action == 'export_simulation_attestation':
                    export_result = self.openclaw_recovery_scheduler_service.export_runtime_alert_governance_baseline_promotion_simulation_attestation(
                        gw,
                        simulation=latest_simulation,
                        actor=actor,
                        timeline_limit=int(raw_payload.get('timeline_limit')) if raw_payload.get('timeline_limit') is not None else None,
                        tenant_id=scope.get('tenant_id'),
                        workspace_id=scope.get('workspace_id'),
                        environment=scope.get('environment'),
                    )
                elif normalized_action == 'export_simulation_review_audit':
                    export_result = self.openclaw_recovery_scheduler_service.export_runtime_alert_governance_baseline_promotion_simulation_review_audit(
                        gw,
                        simulation=latest_simulation,
                        actor=actor,
                        timeline_limit=int(raw_payload.get('timeline_limit')) if raw_payload.get('timeline_limit') is not None else None,
                        tenant_id=scope.get('tenant_id'),
                        workspace_id=scope.get('workspace_id'),
                        environment=scope.get('environment'),
                    )
                elif normalized_action == 'export_simulation_evidence_package':
                    export_result = self.openclaw_recovery_scheduler_service.export_runtime_alert_governance_baseline_promotion_simulation_evidence_package(
                        gw,
                        simulation=latest_simulation,
                        actor=actor,
                        timeline_limit=int(raw_payload.get('timeline_limit')) if raw_payload.get('timeline_limit') is not None else None,
                        tenant_id=scope.get('tenant_id'),
                        workspace_id=scope.get('workspace_id'),
                        environment=scope.get('environment'),
                    )
                elif normalized_action == 'verify_simulation_evidence_package':
                    export_result = self.openclaw_recovery_scheduler_service.verify_runtime_alert_governance_baseline_promotion_simulation_evidence_artifact(
                        gw,
                        promotion_id=promotion_id,
                        actor=actor,
                        package_id=package_id,
                        tenant_id=scope.get('tenant_id'),
                        workspace_id=scope.get('workspace_id'),
                        environment=scope.get('environment'),
                    )
                elif normalized_action == 'restore_simulation_evidence_package':
                    export_result = self.openclaw_recovery_scheduler_service.restore_runtime_alert_governance_baseline_promotion_simulation_evidence_artifact(
                        gw,
                        promotion_id=promotion_id,
                        actor=actor,
                        package_id=package_id,
                        persist_restore_session=bool(raw_payload.get('persist_restore_session', True)),
                        tenant_id=scope.get('tenant_id'),
                        workspace_id=scope.get('workspace_id'),
                        environment=scope.get('environment'),
                    )
                else:
                    export_result = self.openclaw_recovery_scheduler_service.reconcile_runtime_alert_governance_baseline_promotion_simulation_evidence_custody(
                        gw,
                        promotion_id=promotion_id,
                        actor=actor,
                        package_id=package_id,
                        persist_reconciliation_session=bool(raw_payload.get('persist_reconciliation_session', True)),
                        tenant_id=scope.get('tenant_id'),
                        workspace_id=scope.get('workspace_id'),
                        environment=scope.get('environment'),
                    )
                if not export_result.get('ok'):
                    result = export_result
                else:
                    export_state = dict(latest_simulation.get('export_state') or {})
                    report = dict(export_result.get('report') or {})
                    integrity = dict(export_result.get('integrity') or {})
                    export_summary = {
                        'report_id': str(report.get('report_id') or ''),
                        'report_type': str(report.get('report_type') or ''),
                        'generated_at': report.get('generated_at'),
                        'generated_by': report.get('generated_by'),
                        'integrity': integrity,
                    }
                    updated_simulation = dict(latest_simulation)
                    updated_data = dict(data)
                    if normalized_action == 'export_simulation_attestation':
                        export_state['attestation_count'] = int(export_state.get('attestation_count') or 0) + 1
                        export_state['latest_attestation'] = export_summary
                    elif normalized_action == 'export_simulation_review_audit':
                        export_state['review_audit_count'] = int(export_state.get('review_audit_count') or 0) + 1
                        export_state['latest_review_audit'] = export_summary
                    elif normalized_action == 'export_simulation_evidence_package':
                        artifact = dict(export_result.get('artifact') or {})
                        registry_entry = dict(export_result.get('registry_entry') or {})
                        export_state['evidence_package_count'] = int(export_state.get('evidence_package_count') or 0) + 1
                        export_state['custody_job'] = dict(export_result.get('custody_job') or {})
                        export_state['latest_evidence_package'] = {
                            'package_id': str(export_result.get('package_id') or ''),
                            'report_type': str(((export_result.get('package') or {}).get('report_type') or '')),
                            'generated_at': (export_result.get('package') or {}).get('generated_at'),
                            'generated_by': (export_result.get('package') or {}).get('generated_by'),
                            'integrity': integrity,
                            'artifact': {
                                'artifact_type': str(artifact.get('artifact_type') or ''),
                                'sha256': str(artifact.get('sha256') or ''),
                                'size_bytes': int(artifact.get('size_bytes') or 0),
                                'filename': str(artifact.get('filename') or ''),
                            },
                            'registry_entry': {
                                'entry_id': str(registry_entry.get('entry_id') or ''),
                                'sequence': int(registry_entry.get('sequence') or 0),
                                'entry_hash': str(registry_entry.get('entry_hash') or ''),
                                'previous_entry_hash': str(registry_entry.get('previous_entry_hash') or ''),
                                'immutable': bool(registry_entry.get('immutable')),
                            },
                            'escrow': dict(export_result.get('escrow') or {}),
                        }
                        export_state['registry_summary'] = dict(export_result.get('registry_summary') or {})
                    elif normalized_action == 'verify_simulation_evidence_package':
                        export_state['verification_count'] = int(export_state.get('verification_count') or 0) + 1
                        export_state['latest_verification'] = {
                            'package_id': str(export_result.get('package_id') or package_id or ''),
                            'verified_at': time.time(),
                            'verified_by': str(actor or 'operator'),
                            'status': str(((export_result.get('verification') or {}).get('status')) or ''),
                            'valid': bool(((export_result.get('verification') or {}).get('valid'))),
                            'failures': [str(item) for item in list(((export_result.get('verification') or {}).get('failures')) or []) if str(item)],
                            'artifact_sha256': str(((export_result.get('artifact') or {}).get('sha256')) or ''),
                            'artifact_source': str(((export_result.get('artifact') or {}).get('source')) or ''),
                            'escrow_status': str((((export_result.get('verification') or {}).get('escrow') or {}).get('status')) or ''),
                            'registry_entry': {
                                'entry_id': str(((export_result.get('registry_entry') or {}).get('entry_id')) or ''),
                                'sequence': int(((export_result.get('registry_entry') or {}).get('sequence')) or 0),
                            },
                        }
                        updated_data['last_simulation_evidence_verification'] = dict(export_state.get('latest_verification') or {})
                    elif normalized_action == 'reconcile_simulation_evidence_custody':
                        reconciliation = dict(export_result.get('reconciliation') or {})
                        summary = dict(reconciliation.get('summary') or {})
                        export_state['reconciliation_count'] = int(export_state.get('reconciliation_count') or 0) + 1
                        export_state['latest_reconciliation'] = {
                            'reconciliation_id': str(reconciliation.get('reconciliation_id') or ''),
                            'package_id': str(export_result.get('package_id') or package_id or ''),
                            'reconciled_at': reconciliation.get('reconciled_at'),
                            'reconciled_by': str(reconciliation.get('reconciled_by') or actor or 'operator'),
                            'overall_status': str(summary.get('overall_status') or ''),
                            'drifted_count': int(summary.get('drifted_count') or 0),
                            'missing_archive_count': int(summary.get('missing_archive_count') or 0),
                            'lock_drift_count': int(summary.get('lock_drift_count') or 0),
                            'registry_drift_count': int(summary.get('registry_drift_count') or 0),
                            'latest_package_id': str(summary.get('latest_package_id') or ''),
                        }
                        updated_data['last_simulation_evidence_reconciliation'] = dict(export_state.get('latest_reconciliation') or {})
                        metadata = dict(((export_result.get('release') or {}).get('release') or {}).get('metadata') or {}) if isinstance(export_result.get('release'), dict) and 'release' in export_result.get('release') else dict((export_result.get('release') or {}).get('metadata') or {})
                        promotion_meta = dict(metadata.get('baseline_promotion') or {})
                        monitoring_guard = ((export_result.get('custody_monitoring') or {}).get('guard') or {})
                        export_state['custody_guard'] = self._compact_baseline_promotion_simulation_custody_guard(monitoring_guard or promotion_meta.get('simulation_custody_guard') or {})
                        raw_alert_items = [dict(item) for item in list(promotion_meta.get('simulation_custody_alerts') or [])]
                        monitoring_alerts = (export_result.get('custody_monitoring') or {}).get('alerts')
                        monitoring_alert_items = []
                        monitoring_alert_summary = {}
                        if isinstance(monitoring_alerts, dict):
                            monitoring_alert_items = [dict(item) for item in list(monitoring_alerts.get('items') or [])]
                            monitoring_alert_summary = dict(monitoring_alerts.get('summary') or {})
                        elif isinstance(monitoring_alerts, list):
                            monitoring_alert_items = [dict(item) for item in list(monitoring_alerts or [])]
                        alert_items = monitoring_alert_items or raw_alert_items
                        if monitoring_alert_summary:
                            export_state['custody_alerts_summary'] = self._compact_baseline_promotion_simulation_custody_alerts_summary(monitoring_alert_summary)
                        else:
                            export_state['custody_alerts_summary'] = self._compact_baseline_promotion_simulation_custody_alerts_summary({
                                'count': len(alert_items),
                                'active_count': sum(1 for item in alert_items if bool(item.get('active'))),
                                'acknowledged_count': sum(1 for item in alert_items if str(item.get('status') or '') == 'acknowledged'),
                                'muted_count': sum(1 for item in alert_items if str(item.get('status') or '') == 'muted'),
                                'escalated_count': sum(1 for item in alert_items if int(item.get('escalation_level') or item.get('escalation_count') or 0) > 0),
                                'suppressed_count': sum(1 for item in alert_items if bool((item.get('suppression_state') or {}).get('suppressed'))),
                                'pending_handoff_count': sum(1 for item in alert_items if bool((item.get('handoff') or {}).get('pending'))),
                                'sla_breached_count': sum(1 for item in alert_items if bool((item.get('sla') or item.get('sla_state') or {}).get('breached'))),
                                'latest_alert_id': str((alert_items[0] or {}).get('alert_id') or '') if alert_items else '',
                            })
                        active_alert = next((item for item in alert_items if bool(item.get('active'))), {})
                        export_state['custody_active_alert'] = self._compact_baseline_promotion_simulation_custody_active_alert(active_alert)
                    else:
                        restored_simulation = dict(export_result.get('replayed_simulation') or export_result.get('restored_simulation') or {})
                        export_state = dict((restored_simulation.get('export_state') or export_state))
                        export_state['verification_count'] = int(export_state.get('verification_count') or 0) + 1
                        export_state['latest_verification'] = {
                            'package_id': str(export_result.get('package_id') or package_id or ''),
                            'verified_at': time.time(),
                            'verified_by': str(actor or 'operator'),
                            'status': str(((export_result.get('verification') or {}).get('status')) or ''),
                            'valid': bool(((export_result.get('verification') or {}).get('valid'))),
                            'failures': [str(item) for item in list(((export_result.get('verification') or {}).get('failures')) or []) if str(item)],
                            'artifact_sha256': str(((export_result.get('artifact') or {}).get('sha256')) or ''),
                            'artifact_source': str(((export_result.get('artifact') or {}).get('source')) or ''),
                            'escrow_status': str((((export_result.get('verification') or {}).get('escrow') or {}).get('status')) or ''),
                            'registry_entry': {
                                'entry_id': str(((export_result.get('registry_entry') or {}).get('entry_id')) or ''),
                                'sequence': int(((export_result.get('registry_entry') or {}).get('sequence')) or 0),
                            },
                        }
                        export_state['restore_count'] = int(export_state.get('restore_count') or 0) + 1
                        export_state['latest_restore'] = {
                            'restore_id': str(((export_result.get('restore_session') or {}).get('restore_id')) or ''),
                            'package_id': str(export_result.get('package_id') or package_id or ''),
                            'restored_at': ((export_result.get('restore_session') or {}).get('restored_at')),
                            'restored_by': str(((export_result.get('restore_session') or {}).get('restored_by')) or actor or 'operator'),
                            'simulation_status': str((restored_simulation.get('simulation_status') or '')),
                            'stale': bool(restored_simulation.get('stale')),
                            'expired': bool(restored_simulation.get('expired')),
                            'blocked': bool(restored_simulation.get('blocked')),
                            'why_blocked': str(restored_simulation.get('why_blocked') or ''),
                        }
                        restored_simulation['export_state'] = export_state
                        updated_simulation = restored_simulation
                        updated_data['last_simulation_restore'] = dict(export_state.get('latest_restore') or {})
                    if normalized_action in {'export_simulation_attestation', 'export_simulation_review_audit', 'export_simulation_evidence_package', 'verify_simulation_evidence_package', 'reconcile_simulation_evidence_custody'}:
                        updated_simulation['export_state'] = export_state
                    if updated_simulation:
                        updated_state = self._baseline_promotion_simulation_state(
                            simulation=updated_simulation,
                            actor=str(updated_simulation.get('simulated_by') or latest_simulation.get('simulated_by') or actor or 'operator'),
                            request=dict(updated_simulation.get('request') or latest_simulation.get('request') or {}),
                            review=dict(updated_simulation.get('review') or latest_simulation.get('review') or {}),
                            created_promotions=[dict(item) for item in list(updated_simulation.get('created_promotions') or latest_simulation.get('created_promotions') or [])],
                        )
                        updated_data['latest_simulation'] = updated_state
                    node = dict((self._replace_node_data(
                        gw,
                        canvas_id=canvas_id,
                        node=node,
                        actor=actor,
                        data=updated_data,
                        tenant_id=scope.get('tenant_id'),
                        workspace_id=scope.get('workspace_id'),
                        environment=scope.get('environment'),
                    ) or {}).get('node') or node)
                    data = dict(node.get('data') or {})
                    result = {**export_result, 'latest_simulation': dict(data.get('latest_simulation') or {})}
            elif normalized_action == 'save_simulation_custody_routing_policy_pack':
                promotion_detail = dict((inspected.get('related') or {}).get('baseline_promotion') or {})
                builtin_packs = self._baseline_promotion_simulation_custody_builtin_policy_packs(promotion_detail)
                builtin_pack_ids = {str(item.get('pack_id') or '') for item in builtin_packs}
                raw_saved_packs = [dict(item or {}) for item in list(data.get('saved_routing_policy_packs') or []) if isinstance(item, dict)]
                raw_registry_packs = [dict(item or {}) for item in list(data.get('routing_policy_pack_registry') or []) if isinstance(item, dict)]
                preset_pack_id = str(raw_payload.get('preset_pack_id') or raw_payload.get('builtin_pack_id') or '').strip()
                save_error = {}
                if preset_pack_id:
                    policy_pack = self._resolve_baseline_promotion_simulation_custody_policy_pack(promotion_detail=promotion_detail, raw_saved_packs=raw_saved_packs, raw_registry_packs=raw_registry_packs, pack_id=preset_pack_id)
                    if not policy_pack:
                        save_error = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_missing'}
                    else:
                        policy_pack = dict(policy_pack)
                        policy_pack['source'] = 'saved'
                        policy_pack['created_by'] = str(actor or 'operator')
                        policy_pack['created_at'] = time.time()
                        policy_pack['last_used_at'] = None
                        policy_pack['use_count'] = 0
                else:
                    raw_pack = dict(raw_payload.get('policy_pack') or raw_payload.get('pack') or {})
                    if not raw_pack:
                        raw_pack = {
                            'pack_id': raw_payload.get('pack_id'),
                            'pack_label': raw_payload.get('pack_label') or raw_payload.get('label'),
                            'description': raw_payload.get('description'),
                            'category_keys': list(raw_payload.get('category_keys') or raw_payload.get('categories') or []),
                            'tags': list(raw_payload.get('tags') or []),
                            'comparison_policies': [dict(item or {}) for item in list(raw_payload.get('comparison_policies') or []) if isinstance(item, dict)],
                        }
                    policy_pack = self.openclaw_recovery_scheduler_service._normalize_baseline_promotion_simulation_custody_policy_what_if_pack(raw_pack, actor=str(actor or 'operator'), index=len(raw_saved_packs) + 1, source='saved')
                    if not list(policy_pack.get('comparison_policies') or []):
                        save_error = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_empty'}
                if save_error:
                    result = save_error
                else:
                    updated_saved = [item for item in raw_saved_packs if str(item.get('pack_id') or '') != str(policy_pack.get('pack_id') or '')]
                    if str(policy_pack.get('pack_id') or '') in builtin_pack_ids or str(policy_pack.get('promoted_from_pack_id') or '') in builtin_pack_ids:
                        saved_storage_pack = {
                            'pack_id': str(policy_pack.get('pack_id') or ''),
                            'pack_label': str(policy_pack.get('pack_label') or ''),
                            'source': 'saved',
                            'category_keys': [str(item) for item in list(policy_pack.get('category_keys') or []) if str(item)][:8],
                            'tags': [str(item) for item in list(policy_pack.get('tags') or []) if str(item)][:8],
                            'created_at': policy_pack.get('created_at'),
                            'created_by': str(policy_pack.get('created_by') or ''),
                            'scenario_count': int(policy_pack.get('scenario_count') or 0),
                        }
                    else:
                        saved_storage_pack = self._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(policy_pack)
                    updated_saved.append(saved_storage_pack)
                    normalized_saved = self._baseline_promotion_simulation_custody_saved_policy_packs(updated_saved)
                    normalized_registry = self._baseline_promotion_simulation_custody_registry_policy_packs(raw_registry_packs)
                    compact_pack = self._compact_baseline_promotion_simulation_routing_policy_pack(policy_pack)
                    updated_data = dict(data)
                    updated_data['saved_routing_policy_packs'] = updated_saved
                    updated_data['last_saved_routing_policy_pack'] = dict(compact_pack)
                    if latest_simulation:
                        export_state = dict(latest_simulation.get('export_state') or {})
                        export_state['routing_policy_what_if_presets'] = [
                            {'pack_id': str(item.get('pack_id') or ''), 'pack_label': str(item.get('pack_label') or ''), 'source': str(item.get('source') or ''), 'category_keys': [str(v) for v in list(item.get('category_keys') or []) if str(v)][:8], 'scenario_count': int(item.get('scenario_count') or 0)}
                            for item in builtin_packs[:6]
                        ]
                        export_state['saved_routing_policy_packs'] = [
                            {'pack_id': str(item.get('pack_id') or ''), 'pack_label': str(item.get('pack_label') or ''), 'source': str(item.get('source') or ''), 'category_keys': [str(v) for v in list(item.get('category_keys') or []) if str(v)][:8], 'scenario_count': int(item.get('scenario_count') or 0), 'created_at': item.get('created_at'), 'created_by': str(item.get('created_by') or ''), 'last_used_at': item.get('last_used_at'), 'use_count': int(item.get('use_count') or 0)}
                            for item in normalized_saved[:6]
                        ]
                        export_state['routing_policy_pack_registry'] = [
                            {
                                'pack_id': str(item.get('pack_id') or ''),
                                'pack_label': str(item.get('pack_label') or ''),
                                'source': str(item.get('source') or ''),
                                'registry_entry_id': str(item.get('registry_entry_id') or ''),
                                'registry_scope': str(item.get('registry_scope') or ''),
                                'catalog_entry_id': str(item.get('catalog_entry_id') or ''),
                                'catalog_scope': str(item.get('catalog_scope') or ''),
                                'catalog_scope_key': str(item.get('catalog_scope_key') or ''),
                                'catalog_version_key': str(item.get('catalog_version_key') or ''),
                                'catalog_version': int(item.get('catalog_version') or 0),
                                'workspace_id': str(item.get('workspace_id') or ''),
                                'environment': str(item.get('environment') or ''),
                                'promotion_id': str(item.get('promotion_id') or ''),
                                'catalog_lifecycle_state': str(item.get('catalog_lifecycle_state') or 'draft'),
                                'catalog_approval_required': bool(item.get('catalog_approval_required', False)),
                                'catalog_required_approvals': int(item.get('catalog_required_approvals') or 0),
                                'catalog_approval_count': int(item.get('catalog_approval_count') or 0),
                                'catalog_approval_state': str(item.get('catalog_approval_state') or ''),
                                'catalog_attestation_count': int(item.get('catalog_attestation_count') or 0),
                                'catalog_latest_attestation': LiveCanvasService._compact_baseline_promotion_simulation_export_report(item.get('catalog_latest_attestation') or {}),
                                'catalog_evidence_package_count': int(item.get('catalog_evidence_package_count') or 0),
                                'catalog_latest_evidence_package': LiveCanvasService._compact_baseline_promotion_simulation_export_report(item.get('catalog_latest_evidence_package') or {}),
                                'catalog_release_bundle_count': int(item.get('catalog_release_bundle_count') or 0),
                                'catalog_latest_release_bundle': LiveCanvasService._compact_baseline_promotion_simulation_export_report(item.get('catalog_latest_release_bundle') or {}),
                                'catalog_review_state': str(item.get('catalog_review_state') or ''),
                                'catalog_review_assigned_reviewer': str(item.get('catalog_review_assigned_reviewer') or ''),
                                'catalog_review_assigned_role': str(item.get('catalog_review_assigned_role') or ''),
                                'catalog_review_claimed_by': str(item.get('catalog_review_claimed_by') or ''),
                                'catalog_review_claimed_at': item.get('catalog_review_claimed_at'),
                                'catalog_review_decision': str(item.get('catalog_review_decision') or ''),
                                'catalog_review_decision_at': item.get('catalog_review_decision_at'),
                                'catalog_review_decision_by': str(item.get('catalog_review_decision_by') or ''),
                                'catalog_review_latest_note': str(item.get('catalog_review_latest_note') or ''),
                                'catalog_review_note_count': int(item.get('catalog_review_note_count') or 0),
                                'catalog_review_last_transition_at': item.get('catalog_review_last_transition_at'),
                                'catalog_review_last_transition_by': str(item.get('catalog_review_last_transition_by') or ''),
                                'catalog_review_last_transition_action': str(item.get('catalog_review_last_transition_action') or ''),
                                'catalog_review_events': [{
                                    'event_id': str(v.get('event_id') or ''),
                                    'event_type': str(v.get('event_type') or ''),
                                    'state': str(v.get('state') or ''),
                                    'actor': str(v.get('actor') or ''),
                                    'role': str(v.get('role') or ''),
                                    'at': v.get('at'),
                                    'note': str(v.get('note') or '')[:80],
                                    'decision': str(v.get('decision') or ''),
                                    'assigned_reviewer': str(v.get('assigned_reviewer') or '')[:80],
                                } for v in list(item.get('catalog_review_events') or [])[:8] if isinstance(v, dict)],
                                'catalog_release_state': str(item.get('catalog_release_state') or 'draft'),
                                'catalog_release_train_id': str(item.get('catalog_release_train_id') or ''),
                                'catalog_rollout_train_id': str(item.get('catalog_rollout_train_id') or ''),
                                'catalog_rollout_policy': LiveCanvasService._baseline_promotion_simulation_custody_catalog_rollout_policy(item.get('catalog_rollout_policy') or {}),
                                'catalog_rollout_enabled': bool(item.get('catalog_rollout_enabled', False)),
                                'catalog_rollout_state': str(item.get('catalog_rollout_state') or ''),
                                'catalog_rollout_current_wave_index': int(item.get('catalog_rollout_current_wave_index') or 0),
                                'catalog_rollout_completed_wave_count': int(item.get('catalog_rollout_completed_wave_count') or 0),
                                'catalog_rollout_paused': bool(item.get('catalog_rollout_paused', False)),
                                'catalog_rollout_frozen': bool(item.get('catalog_rollout_frozen', False)),
                                'catalog_rollout_targets': [
                                    {
                                        'target_key': str(v.get('target_key') or ''),
                                        'promotion_id': str(v.get('promotion_id') or ''),
                                        'workspace_id': str(v.get('workspace_id') or ''),
                                        'environment': str(v.get('environment') or ''),
                                        'released': bool(v.get('released', False)),
                                        'released_wave_index': int(v.get('released_wave_index') or 0),
                                    }
                                    for v in list(item.get('catalog_rollout_targets') or [])[:12]
                                    if isinstance(v, dict)
                                ],
                                'catalog_rollout_waves': [
                                    {
                                        'wave_index': int(v.get('wave_index') or 0),
                                        'status': str(v.get('status') or ''),
                                        'target_keys': [str(k) for k in list(v.get('target_keys') or []) if str(k)][:12],
                                    }
                                    for v in list(item.get('catalog_rollout_waves') or [])[:8]
                                    if isinstance(v, dict)
                                ],
                                'catalog_rollout_policy': LiveCanvasService._baseline_promotion_simulation_custody_catalog_rollout_policy(item.get('catalog_rollout_policy') or {}),
                                'catalog_dependency_refs': LiveCanvasService._baseline_promotion_simulation_custody_catalog_dependency_refs(item.get('catalog_dependency_refs') or []),
                                'catalog_conflict_rules': LiveCanvasService._baseline_promotion_simulation_custody_catalog_conflict_rules(item.get('catalog_conflict_rules') or {}),
                                'catalog_freeze_windows': LiveCanvasService._baseline_promotion_simulation_custody_catalog_freeze_windows(item.get('catalog_freeze_windows') or []),
                                'catalog_dependency_summary': dict(item.get('catalog_dependency_summary') or {}),
                                'catalog_conflict_summary': dict(item.get('catalog_conflict_summary') or {}),
                                'catalog_freeze_summary': dict(item.get('catalog_freeze_summary') or {}),
                                'catalog_release_guard': dict(item.get('catalog_release_guard') or {}),
                                'scenario_count': int(item.get('scenario_count') or 0),
                                'share_count': int(item.get('share_count') or 0),
                            }
                            for item in normalized_registry[:4]
                        ]
                        export_state['last_saved_routing_policy_pack'] = {'pack_id': str(policy_pack.get('pack_id') or ''), 'pack_label': str(policy_pack.get('pack_label') or ''), 'source': str(policy_pack.get('source') or ''), 'category_keys': [str(v) for v in list(policy_pack.get('category_keys') or []) if str(v)][:8], 'scenario_count': int(policy_pack.get('scenario_count') or 0), 'created_at': policy_pack.get('created_at'), 'created_by': str(policy_pack.get('created_by') or ''), 'last_used_at': policy_pack.get('last_used_at'), 'use_count': int(policy_pack.get('use_count') or 0)}
                        updated_simulation = dict(latest_simulation)
                        updated_simulation['export_state'] = export_state
                        updated_data.pop('routing_policy_pack_catalog', None)
                        updated_data.pop('routing_policy_pack_catalog_summary', None)
                        updated_data.pop('routing_policy_pack_compliance_summary', None)
                        updated_data.pop('effective_routing_policy_pack_compliance', None)
                        updated_data.pop('routing_policy_pack_analytics_summary', None)
                        updated_data.pop('routing_policy_pack_operator_dashboard', None)
                        updated_data['latest_simulation'] = self._baseline_promotion_simulation_state(simulation=updated_simulation, actor=str(updated_simulation.get('simulated_by') or actor or 'operator'), request=dict(updated_simulation.get('request') or {}), review=dict(updated_simulation.get('review') or {}), created_promotions=[dict(item) for item in list(updated_simulation.get('created_promotions') or [])])
                    node = dict((self._replace_node_data(gw, canvas_id=canvas_id, node=node, actor=actor, data=updated_data, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')) or {}).get('node') or node)
                    data = dict(node.get('data') or {})
                    result = {'ok': True, 'policy_pack': compact_pack, 'latest_simulation': dict(data.get('latest_simulation') or {})}
            elif normalized_action == 'promote_simulation_custody_routing_policy_pack_to_registry':
                promotion_detail = dict((inspected.get('related') or {}).get('baseline_promotion') or {})
                builtin_packs = self._baseline_promotion_simulation_custody_builtin_policy_packs(promotion_detail)
                builtin_pack_ids = {str(item.get('pack_id') or '') for item in builtin_packs}
                raw_saved_packs = [dict(item or {}) for item in list(data.get('saved_routing_policy_packs') or []) if isinstance(item, dict)]
                raw_registry_packs = [dict(item or {}) for item in list(data.get('routing_policy_pack_registry') or []) if isinstance(item, dict)]
                requested_pack_id = str(raw_payload.get('registry_pack_id') or raw_payload.get('policy_pack_id') or raw_payload.get('saved_pack_id') or raw_payload.get('preset_pack_id') or raw_payload.get('pack_id') or '').strip()
                if not requested_pack_id:
                    result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_missing'}
                else:
                    source_pack = self._resolve_baseline_promotion_simulation_custody_policy_pack(promotion_detail=promotion_detail, raw_saved_packs=raw_saved_packs, raw_registry_packs=raw_registry_packs, pack_id=requested_pack_id)
                    if not source_pack:
                        result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_missing'}
                    else:
                        existing_registry = next((item for item in self._baseline_promotion_simulation_custody_registry_policy_packs(raw_registry_packs) if str(item.get('pack_id') or '') == requested_pack_id), {})
                        promoted_pack = dict(source_pack)
                        promoted_pack['source'] = 'registry'
                        promoted_pack['registry_entry_id'] = str(existing_registry.get('registry_entry_id') or raw_payload.get('registry_entry_id') or f'registry_{requested_pack_id}').strip() or f'registry_{requested_pack_id}'
                        promoted_pack['registry_scope'] = str(raw_payload.get('registry_scope') or existing_registry.get('registry_scope') or 'promotion').strip() or 'promotion'
                        promoted_pack['promoted_at'] = time.time()
                        promoted_pack['promoted_by'] = str(actor or 'operator')
                        promoted_pack['promoted_from_pack_id'] = str(source_pack.get('promoted_from_pack_id') or source_pack.get('pack_id') or '')
                        source_origin = str(source_pack.get('promoted_from_source') or source_pack.get('shared_from_source') or source_pack.get('source') or 'saved')
                        if str(source_pack.get('pack_id') or '') in builtin_pack_ids or str(promoted_pack.get('promoted_from_pack_id') or '') in builtin_pack_ids:
                            source_origin = 'builtin'
                        promoted_pack['promoted_from_source'] = source_origin
                        promoted_pack['share_count'] = int(existing_registry.get('share_count') or 0)
                        promoted_pack['last_shared_at'] = existing_registry.get('last_shared_at')
                        promoted_pack['last_shared_by'] = str(existing_registry.get('last_shared_by') or '')
                        promoted_pack['share_targets'] = [str(item) for item in list(existing_registry.get('share_targets') or raw_payload.get('share_targets') or []) if str(item)][:8]
                        if str(promoted_pack.get('promoted_from_source') or '') == 'builtin':
                            registry_storage_pack = {
                                'pack_id': str(promoted_pack.get('pack_id') or ''),
                                'pack_label': str(promoted_pack.get('pack_label') or ''),
                                'source': 'registry',
                                'registry_entry_id': str(promoted_pack.get('registry_entry_id') or ''),
                                'registry_scope': str(promoted_pack.get('registry_scope') or ''),
                                'promoted_at': promoted_pack.get('promoted_at'),
                                'promoted_by': str(promoted_pack.get('promoted_by') or ''),
                                'promoted_from_pack_id': str(promoted_pack.get('promoted_from_pack_id') or ''),
                                'promoted_from_source': str(promoted_pack.get('promoted_from_source') or ''),
                                'share_count': int(promoted_pack.get('share_count') or 0),
                                'share_targets': [str(item) for item in list(promoted_pack.get('share_targets') or []) if str(item)][:8],
                            }
                        else:
                            registry_storage_pack = self._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(promoted_pack)
                        updated_registry = [item for item in raw_registry_packs if str(item.get('pack_id') or '') != str(promoted_pack.get('pack_id') or '')]
                        updated_registry.append(registry_storage_pack)
                        normalized_registry = self._baseline_promotion_simulation_custody_registry_policy_packs(updated_registry)
                        updated_saved = [item for item in raw_saved_packs if str(item.get('pack_id') or '') != str(promoted_pack.get('pack_id') or '')]
                        normalized_saved = self._baseline_promotion_simulation_custody_saved_policy_packs(updated_saved)
                        compact_pack = self._compact_baseline_promotion_simulation_routing_policy_pack(promoted_pack)
                        updated_data = dict(data)
                        updated_data['saved_routing_policy_packs'] = [
                            LiveCanvasService._prune_canvas_payload(
                                LiveCanvasService._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(item)
                            )
                            for item in list(updated_saved or [])[-1:]
                            if isinstance(item, dict)
                        ]
                        if not updated_saved or str(((data.get('last_saved_routing_policy_pack') or {}).get('pack_id')) or '') == str(promoted_pack.get('pack_id') or ''):
                            updated_data.pop('last_saved_routing_policy_pack', None)
                        updated_data['routing_policy_pack_registry'] = [
                            LiveCanvasService._prune_canvas_payload(
                                LiveCanvasService._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(item)
                            )
                            for item in list(updated_registry or [])[:4]
                            if isinstance(item, dict)
                        ]
                        updated_data['last_promoted_routing_policy_pack'] = {'pack_id': str(compact_pack.get('pack_id') or ''), 'pack_label': str(compact_pack.get('pack_label') or ''), 'source': str(compact_pack.get('source') or ''), 'registry_entry_id': str(compact_pack.get('registry_entry_id') or ''), 'registry_scope': str(compact_pack.get('registry_scope') or ''), 'scenario_count': int(compact_pack.get('scenario_count') or 0)}
                        if latest_simulation:
                            updated_data['latest_simulation'] = dict(data.get('latest_simulation') or latest_simulation)
                        node = dict((self._replace_node_data(gw, canvas_id=canvas_id, node=node, actor=actor, data=updated_data, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')) or {}).get('node') or node)
                        data = dict(node.get('data') or {})
                        result = {'ok': True, 'policy_pack': compact_pack, 'latest_simulation': dict(data.get('latest_simulation') or {})}
            elif normalized_action == 'promote_simulation_custody_routing_policy_pack_to_catalog':
                promotion_detail = dict((inspected.get('related') or {}).get('baseline_promotion') or {})
                builtin_packs = self._baseline_promotion_simulation_custody_builtin_policy_packs(promotion_detail)
                builtin_pack_ids = {str(item.get('pack_id') or '') for item in builtin_packs}
                raw_saved_packs = [dict(item or {}) for item in list(data.get('saved_routing_policy_packs') or []) if isinstance(item, dict)]
                raw_registry_packs = [dict(item or {}) for item in list(data.get('routing_policy_pack_registry') or []) if isinstance(item, dict)]
                requested_pack_id = str(raw_payload.get('catalog_pack_id') or raw_payload.get('registry_pack_id') or raw_payload.get('policy_pack_id') or raw_payload.get('saved_pack_id') or raw_payload.get('preset_pack_id') or raw_payload.get('pack_id') or '').strip()
                if not requested_pack_id:
                    result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_missing'}
                else:
                    source_pack = self._resolve_baseline_promotion_simulation_custody_policy_pack(promotion_detail=promotion_detail, raw_saved_packs=raw_saved_packs, raw_registry_packs=raw_registry_packs, pack_id=requested_pack_id)
                    if not source_pack:
                        result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_missing'}
                    else:
                        promotion_meta = dict((promotion_detail.get('baseline_promotion') or {}))
                        normalized_registry = self._baseline_promotion_simulation_custody_registry_policy_packs(raw_registry_packs)
                        catalog_scope = str(raw_payload.get('catalog_scope') or raw_payload.get('registry_scope') or source_pack.get('catalog_scope') or source_pack.get('registry_scope') or 'promotion').strip() or 'promotion'
                        promotion_id_value = str(promotion_meta.get('promotion_id') or promotion_id or data.get('promotion_id') or '')
                        workspace_value = str(scope.get('workspace_id') or '')
                        environment_value = str(scope.get('environment') or '')
                        portfolio_family_id = str(raw_payload.get('portfolio_family_id') or data.get('portfolio_family_id') or promotion_meta.get('portfolio_family_id') or '')
                        runtime_family_id = str(raw_payload.get('runtime_family_id') or data.get('runtime_family_id') or promotion_meta.get('runtime_family_id') or '')
                        if catalog_scope == 'promotion':
                            catalog_scope_key = f'promotion:{promotion_id_value}'
                        elif catalog_scope == 'workspace':
                            catalog_scope_key = f'workspace:{workspace_value}'
                        elif catalog_scope == 'environment':
                            catalog_scope_key = f'environment:{workspace_value}:{environment_value}'
                        elif catalog_scope == 'portfolio_family':
                            catalog_scope_key = f'portfolio_family:{portfolio_family_id}'
                        elif catalog_scope == 'runtime_family':
                            catalog_scope_key = f'runtime_family:{runtime_family_id}'
                        elif catalog_scope == 'global':
                            catalog_scope_key = 'global'
                        else:
                            catalog_scope_key = str(raw_payload.get('catalog_scope_key') or '') or f'{catalog_scope}:{workspace_value}'
                        catalog_version_key = str(raw_payload.get('catalog_version_key') or f'{requested_pack_id}:{catalog_scope_key}').strip() or f'{requested_pack_id}:{catalog_scope_key}'
                        existing_versions = [dict(item or {}) for item in normalized_registry if str(item.get('catalog_version_key') or '') == catalog_version_key]
                        requested_version = int(raw_payload.get('catalog_version') or 0)
                        if requested_version <= 0:
                            requested_version = max([int(item.get('catalog_version') or 0) for item in existing_versions] + [0]) + 1
                        requested_entry_id = str(raw_payload.get('catalog_entry_id') or '').strip()
                        existing_registry = next((item for item in existing_versions if str(item.get('catalog_entry_id') or '') == requested_entry_id or int(item.get('catalog_version') or 0) == requested_version), {})
                        lifecycle_state = str(raw_payload.get('catalog_lifecycle_state') or existing_registry.get('catalog_lifecycle_state') or source_pack.get('catalog_lifecycle_state') or 'draft').strip() or 'draft'
                        generated_entry_seed = f'{catalog_version_key}:{requested_version}'
                        generated_entry_suffix = uuid.uuid5(uuid.NAMESPACE_URL, generated_entry_seed).hex[:12]
                        generated_entry_id = f'catalog_{requested_pack_id}_{catalog_scope}_{generated_entry_suffix}_{requested_version}'
                        promoted_pack = dict(source_pack)
                        promoted_pack['source'] = 'catalog'
                        promoted_pack['registry_entry_id'] = str(existing_registry.get('registry_entry_id') or requested_entry_id or generated_entry_id).strip() or generated_entry_id
                        promoted_pack['registry_scope'] = catalog_scope
                        promoted_pack['catalog_entry_id'] = str(existing_registry.get('catalog_entry_id') or requested_entry_id or promoted_pack.get('registry_entry_id') or '').strip()
                        promoted_pack['catalog_scope'] = catalog_scope
                        promoted_pack['catalog_scope_key'] = catalog_scope_key
                        promoted_pack['catalog_version_key'] = catalog_version_key
                        promoted_pack['catalog_version'] = requested_version
                        promoted_pack['catalog_lifecycle_state'] = lifecycle_state
                        promoted_pack['promotion_id'] = promotion_id_value
                        promoted_pack['workspace_id'] = workspace_value
                        promoted_pack['environment'] = environment_value
                        promoted_pack['portfolio_family_id'] = portfolio_family_id
                        promoted_pack['runtime_family_id'] = runtime_family_id
                        promoted_pack['catalog_promoted_at'] = time.time()
                        promoted_pack['catalog_promoted_by'] = str(actor or 'operator')
                        promoted_pack['promoted_at'] = promoted_pack.get('catalog_promoted_at')
                        promoted_pack['promoted_by'] = promoted_pack.get('catalog_promoted_by')
                        promoted_pack['promoted_from_pack_id'] = str(source_pack.get('promoted_from_pack_id') or source_pack.get('pack_id') or '')
                        source_origin = str(source_pack.get('promoted_from_source') or source_pack.get('shared_from_source') or source_pack.get('source') or 'saved')
                        if str(source_pack.get('pack_id') or '') in builtin_pack_ids or str(promoted_pack.get('promoted_from_pack_id') or '') in builtin_pack_ids:
                            source_origin = 'builtin'
                        promoted_pack['promoted_from_source'] = source_origin
                        promoted_pack['share_count'] = int(existing_registry.get('share_count') or 0)
                        promoted_pack['catalog_share_count'] = int(existing_registry.get('catalog_share_count') or promoted_pack.get('share_count') or 0)
                        promoted_pack['last_shared_at'] = existing_registry.get('last_shared_at')
                        promoted_pack['last_shared_by'] = str(existing_registry.get('last_shared_by') or '')
                        promoted_pack['catalog_last_shared_at'] = existing_registry.get('catalog_last_shared_at') or promoted_pack.get('last_shared_at')
                        promoted_pack['catalog_last_shared_by'] = str(existing_registry.get('catalog_last_shared_by') or promoted_pack.get('last_shared_by') or '')
                        promoted_pack['share_targets'] = [str(item) for item in list(existing_registry.get('share_targets') or raw_payload.get('share_targets') or []) if str(item)][:8]
                        promoted_pack['catalog_curated_at'] = existing_registry.get('catalog_curated_at')
                        promoted_pack['catalog_curated_by'] = str(existing_registry.get('catalog_curated_by') or '')
                        promoted_pack['catalog_approved_at'] = existing_registry.get('catalog_approved_at')
                        promoted_pack['catalog_approved_by'] = str(existing_registry.get('catalog_approved_by') or '')
                        promoted_pack['catalog_deprecated_at'] = existing_registry.get('catalog_deprecated_at')
                        promoted_pack['catalog_deprecated_by'] = str(existing_registry.get('catalog_deprecated_by') or '')
                        promoted_pack['catalog_replaced_by_version'] = int(existing_registry.get('catalog_replaced_by_version') or 0)
                        promoted_pack['catalog_is_latest'] = True
                        approval_required = bool(raw_payload.get('catalog_approval_required', existing_registry.get('catalog_approval_required', False)))
                        required_approvals = int(raw_payload.get('catalog_required_approvals') or existing_registry.get('catalog_required_approvals') or (1 if approval_required else 0))
                        approvals = [dict(item or {}) for item in list(existing_registry.get('catalog_approvals') or []) if isinstance(item, dict)]
                        approval_count = int(existing_registry.get('catalog_approval_count') or len([item for item in approvals if str(item.get('decision') or '') == 'approved']))
                        approval_state = str(existing_registry.get('catalog_approval_state') or ('approved' if approval_required and approval_count >= max(1, required_approvals) else ('not_required' if not approval_required or required_approvals <= 0 else 'pending')))
                        promoted_pack['catalog_approval_required'] = approval_required
                        promoted_pack['catalog_required_approvals'] = max(0, required_approvals)
                        promoted_pack['catalog_approval_count'] = approval_count
                        promoted_pack['catalog_approval_state'] = approval_state
                        promoted_pack['catalog_approval_requested_at'] = existing_registry.get('catalog_approval_requested_at')
                        promoted_pack['catalog_approval_requested_by'] = str(existing_registry.get('catalog_approval_requested_by') or '')
                        promoted_pack['catalog_approval_rejected_at'] = existing_registry.get('catalog_approval_rejected_at')
                        promoted_pack['catalog_approval_rejected_by'] = str(existing_registry.get('catalog_approval_rejected_by') or '')
                        promoted_pack['catalog_approvals'] = approvals[:12]
                        promoted_pack['catalog_release_state'] = str(existing_registry.get('catalog_release_state') or raw_payload.get('catalog_release_state') or 'draft')
                        promoted_pack['catalog_release_notes'] = str(existing_registry.get('catalog_release_notes') or raw_payload.get('catalog_release_notes') or '')
                        promoted_pack['catalog_release_train_id'] = str(existing_registry.get('catalog_release_train_id') or raw_payload.get('catalog_release_train_id') or '')
                        promoted_pack['catalog_release_staged_at'] = existing_registry.get('catalog_release_staged_at')
                        promoted_pack['catalog_release_staged_by'] = str(existing_registry.get('catalog_release_staged_by') or '')
                        promoted_pack['catalog_released_at'] = existing_registry.get('catalog_released_at')
                        promoted_pack['catalog_released_by'] = str(existing_registry.get('catalog_released_by') or '')
                        promoted_pack['catalog_withdrawn_at'] = existing_registry.get('catalog_withdrawn_at')
                        promoted_pack['catalog_withdrawn_by'] = str(existing_registry.get('catalog_withdrawn_by') or '')
                        promoted_pack['catalog_withdrawn_reason'] = str(existing_registry.get('catalog_withdrawn_reason') or '')
                        promoted_pack['catalog_attestation_count'] = int(existing_registry.get('catalog_attestation_count') or 0)
                        promoted_pack['catalog_latest_attestation'] = dict(existing_registry.get('catalog_latest_attestation') or {})
                        promoted_pack['catalog_review_state'] = str(existing_registry.get('catalog_review_state') or '')
                        promoted_pack['catalog_review_requested_at'] = existing_registry.get('catalog_review_requested_at')
                        promoted_pack['catalog_review_requested_by'] = str(existing_registry.get('catalog_review_requested_by') or '')
                        promoted_pack['catalog_review_assigned_reviewer'] = str(existing_registry.get('catalog_review_assigned_reviewer') or raw_payload.get('catalog_review_assigned_reviewer') or '')
                        promoted_pack['catalog_review_assigned_role'] = str(existing_registry.get('catalog_review_assigned_role') or raw_payload.get('catalog_review_assigned_role') or '')
                        promoted_pack['catalog_review_claimed_by'] = str(existing_registry.get('catalog_review_claimed_by') or '')
                        promoted_pack['catalog_review_claimed_at'] = existing_registry.get('catalog_review_claimed_at')
                        promoted_pack['catalog_review_last_transition_at'] = existing_registry.get('catalog_review_last_transition_at')
                        promoted_pack['catalog_review_last_transition_by'] = str(existing_registry.get('catalog_review_last_transition_by') or '')
                        promoted_pack['catalog_review_last_transition_action'] = str(existing_registry.get('catalog_review_last_transition_action') or '')
                        promoted_pack['catalog_review_decision_at'] = existing_registry.get('catalog_review_decision_at')
                        promoted_pack['catalog_review_decision_by'] = str(existing_registry.get('catalog_review_decision_by') or '')
                        promoted_pack['catalog_review_decision'] = str(existing_registry.get('catalog_review_decision') or '')
                        promoted_pack['catalog_review_note_count'] = int(existing_registry.get('catalog_review_note_count') or len(list(existing_registry.get('catalog_review_events') or [])) or 0)
                        promoted_pack['catalog_review_events'] = [dict(item or {}) for item in list(existing_registry.get('catalog_review_events') or []) if isinstance(item, dict)][:12]
                        promoted_pack['catalog_evidence_package_count'] = int(existing_registry.get('catalog_evidence_package_count') or 0)
                        promoted_pack['catalog_latest_evidence_package'] = dict(existing_registry.get('catalog_latest_evidence_package') or {})
                        promoted_pack['catalog_release_bundle_count'] = int(existing_registry.get('catalog_release_bundle_count') or 0)
                        promoted_pack['catalog_latest_release_bundle'] = dict(existing_registry.get('catalog_latest_release_bundle') or {})
                        promoted_pack['catalog_compliance_report_count'] = int(existing_registry.get('catalog_compliance_report_count') or 0)
                        promoted_pack['catalog_latest_compliance_report'] = dict(existing_registry.get('catalog_latest_compliance_report') or {})
                        promoted_pack['catalog_replay_count'] = int(existing_registry.get('catalog_replay_count') or 0)
                        promoted_pack['catalog_last_replayed_at'] = existing_registry.get('catalog_last_replayed_at')
                        promoted_pack['catalog_last_replayed_by'] = str(existing_registry.get('catalog_last_replayed_by') or '')
                        promoted_pack['catalog_last_replay_source'] = str(existing_registry.get('catalog_last_replay_source') or '')
                        promoted_pack['catalog_binding_count'] = int(existing_registry.get('catalog_binding_count') or 0)
                        promoted_pack['catalog_last_bound_at'] = existing_registry.get('catalog_last_bound_at')
                        promoted_pack['catalog_last_bound_by'] = str(existing_registry.get('catalog_last_bound_by') or '')
                        promoted_pack['catalog_analytics_report_count'] = int(existing_registry.get('catalog_analytics_report_count') or 0)
                        promoted_pack['catalog_latest_analytics_report'] = dict(existing_registry.get('catalog_latest_analytics_report') or {})
                        promoted_pack['catalog_dependency_refs'] = self._baseline_promotion_simulation_custody_catalog_dependency_refs(raw_payload.get('catalog_dependency_refs') or existing_registry.get('catalog_dependency_refs') or [])
                        promoted_pack['catalog_conflict_rules'] = self._baseline_promotion_simulation_custody_catalog_conflict_rules(raw_payload.get('catalog_conflict_rules') or existing_registry.get('catalog_conflict_rules') or {})
                        promoted_pack['catalog_freeze_windows'] = self._baseline_promotion_simulation_custody_catalog_freeze_windows(raw_payload.get('catalog_freeze_windows') or existing_registry.get('catalog_freeze_windows') or [])
                        if lifecycle_state == 'curated' and not promoted_pack.get('catalog_curated_at'):
                            promoted_pack['catalog_curated_at'] = promoted_pack.get('catalog_promoted_at')
                            promoted_pack['catalog_curated_by'] = str(actor or 'operator')
                        if lifecycle_state == 'approved' and not promoted_pack.get('catalog_approved_at'):
                            promoted_pack['catalog_approved_at'] = promoted_pack.get('catalog_promoted_at')
                            promoted_pack['catalog_approved_by'] = str(actor or 'operator')
                        if lifecycle_state == 'deprecated' and not promoted_pack.get('catalog_deprecated_at'):
                            promoted_pack['catalog_deprecated_at'] = promoted_pack.get('catalog_promoted_at')
                            promoted_pack['catalog_deprecated_by'] = str(actor or 'operator')
                        updated_registry = []
                        for item in raw_registry_packs:
                            normalized_item = self.openclaw_recovery_scheduler_service._normalize_baseline_promotion_simulation_custody_policy_what_if_pack(item, actor=str((item or {}).get('created_by') or (item or {}).get('promoted_by') or ''), source=str((item or {}).get('source') or 'registry'))
                            if str(normalized_item.get('catalog_version_key') or '') == catalog_version_key and int(normalized_item.get('catalog_version') or 0) == requested_version:
                                continue
                            updated_registry.append(self._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(normalized_item))
                        if str(promoted_pack.get('promoted_from_source') or '') == 'builtin':
                            catalog_storage_pack = {
                                'pack_id': str(promoted_pack.get('pack_id') or ''),
                                'pack_label': str(promoted_pack.get('pack_label') or ''),
                                'source': 'catalog',
                                'registry_entry_id': str(promoted_pack.get('registry_entry_id') or ''),
                                'registry_scope': str(promoted_pack.get('registry_scope') or ''),
                                'catalog_entry_id': str(promoted_pack.get('catalog_entry_id') or ''),
                                'catalog_scope': str(promoted_pack.get('catalog_scope') or ''),
                                'catalog_scope_key': str(promoted_pack.get('catalog_scope_key') or ''),
                                'catalog_version_key': str(promoted_pack.get('catalog_version_key') or ''),
                                'catalog_version': int(promoted_pack.get('catalog_version') or 0),
                                'catalog_lifecycle_state': str(promoted_pack.get('catalog_lifecycle_state') or 'draft'),
                                'catalog_curated_at': promoted_pack.get('catalog_curated_at'),
                                'catalog_curated_by': str(promoted_pack.get('catalog_curated_by') or ''),
                                'catalog_approved_at': promoted_pack.get('catalog_approved_at'),
                                'catalog_approved_by': str(promoted_pack.get('catalog_approved_by') or ''),
                                'catalog_deprecated_at': promoted_pack.get('catalog_deprecated_at'),
                                'catalog_deprecated_by': str(promoted_pack.get('catalog_deprecated_by') or ''),
                                'catalog_replaced_by_version': int(promoted_pack.get('catalog_replaced_by_version') or 0),
                                'catalog_is_latest': bool(promoted_pack.get('catalog_is_latest', False)),
                                'promoted_from_pack_id': str(promoted_pack.get('promoted_from_pack_id') or ''),
                                'promoted_from_source': str(promoted_pack.get('promoted_from_source') or ''),
                                'promotion_id': str(promoted_pack.get('promotion_id') or ''),
                                'workspace_id': str(promoted_pack.get('workspace_id') or ''),
                                'environment': str(promoted_pack.get('environment') or ''),
                                'portfolio_family_id': str(promoted_pack.get('portfolio_family_id') or ''),
                                'runtime_family_id': str(promoted_pack.get('runtime_family_id') or ''),
                                'catalog_promoted_at': promoted_pack.get('catalog_promoted_at'),
                                'catalog_promoted_by': str(promoted_pack.get('catalog_promoted_by') or ''),
                                'catalog_share_count': int(promoted_pack.get('catalog_share_count') or 0),
                                'catalog_approval_required': bool(promoted_pack.get('catalog_approval_required', False)),
                                'catalog_required_approvals': int(promoted_pack.get('catalog_required_approvals') or 0),
                                'catalog_approval_count': int(promoted_pack.get('catalog_approval_count') or 0),
                                'catalog_approval_state': str(promoted_pack.get('catalog_approval_state') or ''),
                                'catalog_approval_requested_at': promoted_pack.get('catalog_approval_requested_at'),
                                'catalog_approval_requested_by': str(promoted_pack.get('catalog_approval_requested_by') or ''),
                                'catalog_approval_rejected_at': promoted_pack.get('catalog_approval_rejected_at'),
                                'catalog_approval_rejected_by': str(promoted_pack.get('catalog_approval_rejected_by') or ''),
                                'catalog_approvals': [dict(item or {}) for item in list(promoted_pack.get('catalog_approvals') or [])[:8]],
                                'catalog_release_state': str(promoted_pack.get('catalog_release_state') or 'draft'),
                                'catalog_release_notes': str(promoted_pack.get('catalog_release_notes') or ''),
                                'catalog_release_train_id': str(promoted_pack.get('catalog_release_train_id') or ''),
                                'catalog_release_staged_at': promoted_pack.get('catalog_release_staged_at'),
                                'catalog_release_staged_by': str(promoted_pack.get('catalog_release_staged_by') or ''),
                                'catalog_released_at': promoted_pack.get('catalog_released_at'),
                                'catalog_released_by': str(promoted_pack.get('catalog_released_by') or ''),
                                'catalog_withdrawn_at': promoted_pack.get('catalog_withdrawn_at'),
                                'catalog_withdrawn_by': str(promoted_pack.get('catalog_withdrawn_by') or ''),
                                'catalog_withdrawn_reason': str(promoted_pack.get('catalog_withdrawn_reason') or ''),
                                'catalog_attestation_count': int(promoted_pack.get('catalog_attestation_count') or 0),
                                'catalog_latest_attestation': dict(promoted_pack.get('catalog_latest_attestation') or {}),
                                'catalog_review_state': str(promoted_pack.get('catalog_review_state') or ''),
                                'catalog_review_requested_at': promoted_pack.get('catalog_review_requested_at'),
                                'catalog_review_requested_by': str(promoted_pack.get('catalog_review_requested_by') or ''),
                                'catalog_review_assigned_reviewer': str(promoted_pack.get('catalog_review_assigned_reviewer') or ''),
                                'catalog_review_assigned_role': str(promoted_pack.get('catalog_review_assigned_role') or ''),
                                'catalog_review_claimed_by': str(promoted_pack.get('catalog_review_claimed_by') or ''),
                                'catalog_review_claimed_at': promoted_pack.get('catalog_review_claimed_at'),
                                'catalog_review_last_transition_at': promoted_pack.get('catalog_review_last_transition_at'),
                                'catalog_review_last_transition_by': str(promoted_pack.get('catalog_review_last_transition_by') or ''),
                                'catalog_review_last_transition_action': str(promoted_pack.get('catalog_review_last_transition_action') or ''),
                                'catalog_review_decision_at': promoted_pack.get('catalog_review_decision_at'),
                                'catalog_review_decision_by': str(promoted_pack.get('catalog_review_decision_by') or ''),
                                'catalog_review_decision': str(promoted_pack.get('catalog_review_decision') or ''),
                                'catalog_review_note_count': int(promoted_pack.get('catalog_review_note_count') or 0),
                                'catalog_review_events': [dict(item or {}) for item in list(promoted_pack.get('catalog_review_events') or [])[:12]],
                                'catalog_evidence_package_count': int(promoted_pack.get('catalog_evidence_package_count') or 0),
                                'catalog_latest_evidence_package': dict(promoted_pack.get('catalog_latest_evidence_package') or {}),
                                'catalog_release_bundle_count': int(promoted_pack.get('catalog_release_bundle_count') or 0),
                                'catalog_latest_release_bundle': dict(promoted_pack.get('catalog_latest_release_bundle') or {}),
                                'catalog_dependency_refs': self._baseline_promotion_simulation_custody_catalog_dependency_refs(promoted_pack.get('catalog_dependency_refs') or []),
                                'catalog_conflict_rules': self._baseline_promotion_simulation_custody_catalog_conflict_rules(promoted_pack.get('catalog_conflict_rules') or {}),
                                'catalog_freeze_windows': self._baseline_promotion_simulation_custody_catalog_freeze_windows(promoted_pack.get('catalog_freeze_windows') or []),
                            }
                        else:
                            catalog_storage_pack = self._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(promoted_pack)
                        updated_registry.append(catalog_storage_pack)
                        updated_registry = [self._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(item) for item in self._baseline_promotion_simulation_custody_apply_catalog_version_flags(self._baseline_promotion_simulation_custody_registry_policy_packs(updated_registry))]
                        updated_data = dict(data)
                        updated_data['routing_policy_pack_registry'] = updated_registry
                        updated_data['last_catalog_promoted_routing_policy_pack'] = {'pack_id': str(promoted_pack.get('pack_id') or ''), 'pack_label': str(promoted_pack.get('pack_label') or ''), 'source': str(promoted_pack.get('source') or ''), 'catalog_entry_id': str(promoted_pack.get('catalog_entry_id') or ''), 'catalog_scope': str(promoted_pack.get('catalog_scope') or ''), 'catalog_scope_key': str(promoted_pack.get('catalog_scope_key') or ''), 'catalog_version_key': str(promoted_pack.get('catalog_version_key') or ''), 'catalog_version': int(promoted_pack.get('catalog_version') or 0), 'catalog_lifecycle_state': str(promoted_pack.get('catalog_lifecycle_state') or ''), 'scenario_count': int(promoted_pack.get('scenario_count') or 0)}
                        if latest_simulation:
                            export_state = dict(latest_simulation.get('export_state') or {})
                            export_state['last_catalog_promoted_routing_policy_pack'] = dict(updated_data['last_catalog_promoted_routing_policy_pack'])
                            updated_simulation = dict(latest_simulation)
                            updated_simulation['export_state'] = export_state
                            updated_data['latest_simulation'] = self._baseline_promotion_simulation_state(simulation=updated_simulation, actor=str(updated_simulation.get('simulated_by') or actor or 'operator'), request=dict(updated_simulation.get('request') or {}), review=dict(updated_simulation.get('review') or {}), created_promotions=[dict(item) for item in list(updated_simulation.get('created_promotions') or [])])
                        node = dict((self._replace_node_data(gw, canvas_id=canvas_id, node=node, actor=actor, data=updated_data, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')) or {}).get('node') or node)
                        data = dict(node.get('data') or {})
                        compact_pack = self._compact_baseline_promotion_simulation_routing_policy_pack(promoted_pack)
                        result = {'ok': True, 'policy_pack': compact_pack, 'latest_simulation': dict(data.get('latest_simulation') or {})}
            
            elif normalized_action == 'share_registered_simulation_custody_routing_policy_pack':
                promotion_detail = dict((inspected.get('related') or {}).get('baseline_promotion') or {})
                builtin_packs = self._baseline_promotion_simulation_custody_builtin_policy_packs(promotion_detail)
                raw_saved_packs = [dict(item or {}) for item in list(data.get('saved_routing_policy_packs') or []) if isinstance(item, dict)]
                raw_registry_packs = [dict(item or {}) for item in list(data.get('routing_policy_pack_registry') or []) if isinstance(item, dict)]
                normalized_registry = self._baseline_promotion_simulation_custody_registry_policy_packs(raw_registry_packs)
                requested_pack_id = str(raw_payload.get('registry_pack_id') or raw_payload.get('policy_pack_id') or raw_payload.get('pack_id') or '').strip()
                target_pack_id = str(raw_payload.get('target_pack_id') or raw_payload.get('shared_pack_id') or requested_pack_id).strip() or requested_pack_id
                registry_pack = self._resolve_baseline_promotion_simulation_custody_policy_pack(promotion_detail=promotion_detail, raw_saved_packs=raw_saved_packs, raw_registry_packs=raw_registry_packs, pack_id=requested_pack_id)
                if not registry_pack or str(registry_pack.get('source') or '') not in {'registry', 'shared_registry'}:
                    result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_missing'}
                else:
                    shared_pack = dict(registry_pack)
                    shared_pack['pack_id'] = target_pack_id
                    shared_pack['source'] = 'shared_registry'
                    shared_pack['shared_from_pack_id'] = str(registry_pack.get('pack_id') or '')
                    shared_pack['shared_from_source'] = 'registry'
                    shared_pack['created_at'] = time.time()
                    shared_pack['created_by'] = str(actor or 'operator')
                    shared_pack['last_used_at'] = None
                    shared_pack['use_count'] = 0
                    share_targets = [str(item) for item in list(raw_payload.get('share_targets') or registry_pack.get('share_targets') or []) if str(item)][:8]
                    shared_pack['share_targets'] = share_targets
                    shared_pack['last_shared_at'] = time.time()
                    shared_pack['last_shared_by'] = str(actor or 'operator')
                    updated_saved = [item for item in raw_saved_packs if str(item.get('pack_id') or '') != str(shared_pack.get('pack_id') or '')]
                    if str(registry_pack.get('promoted_from_source') or '') == 'builtin':
                        shared_storage_pack = {
                            'pack_id': str(shared_pack.get('pack_id') or ''),
                            'pack_label': str(shared_pack.get('pack_label') or ''),
                            'source': 'shared_registry',
                            'shared_from_pack_id': str(shared_pack.get('shared_from_pack_id') or ''),
                            'shared_from_source': str(shared_pack.get('shared_from_source') or ''),
                            'scenario_count': int(shared_pack.get('scenario_count') or 0),
                        }
                    else:
                        shared_storage_pack = self._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(shared_pack)
                    updated_saved.append(shared_storage_pack)
                    updated_registry = []
                    for item in raw_registry_packs:
                        if str(item.get('pack_id') or '') == str(registry_pack.get('pack_id') or ''):
                            registry_item = dict(item or {})
                            registry_item['source'] = 'registry'
                            registry_item['share_count'] = int(registry_item.get('share_count') or 0) + 1
                            registry_item['last_shared_at'] = shared_pack.get('last_shared_at')
                            registry_item['last_shared_by'] = str(actor or 'operator')
                            registry_item['share_targets'] = share_targets
                            updated_registry.append(registry_item)
                        else:
                            updated_registry.append(dict(item or {}))
                    normalized_saved = self._baseline_promotion_simulation_custody_saved_policy_packs(updated_saved)
                    normalized_registry = self._baseline_promotion_simulation_custody_registry_policy_packs(updated_registry)
                    normalized_updated_registry = self._baseline_promotion_simulation_custody_catalog_enrich_packs(self._baseline_promotion_simulation_custody_apply_catalog_version_flags(self._baseline_promotion_simulation_custody_registry_policy_packs(updated_registry)))
                    updated_registry = [self._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(item) for item in normalized_updated_registry]
                    compact_pack = self._compact_baseline_promotion_simulation_routing_policy_pack(shared_pack)
                    updated_data = dict(data)
                    updated_data['saved_routing_policy_packs'] = updated_saved
                    updated_data['routing_policy_pack_registry'] = updated_registry
                    updated_data['last_shared_routing_policy_pack'] = {'pack_id': str(compact_pack.get('pack_id') or ''), 'pack_label': str(compact_pack.get('pack_label') or ''), 'source': str(compact_pack.get('source') or ''), 'shared_from_pack_id': str(compact_pack.get('shared_from_pack_id') or ''), 'shared_from_source': str(compact_pack.get('shared_from_source') or ''), 'scenario_count': int(compact_pack.get('scenario_count') or 0)}
                    if latest_simulation:
                        updated_data['latest_simulation'] = dict(data.get('latest_simulation') or latest_simulation)
                    node = dict((self._replace_node_data(gw, canvas_id=canvas_id, node=node, actor=actor, data=updated_data, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')) or {}).get('node') or node)
                    data = dict(node.get('data') or {})
                    result = {'ok': True, 'policy_pack': compact_pack, 'latest_simulation': dict(data.get('latest_simulation') or {})}
            elif normalized_action == 'share_cataloged_simulation_custody_routing_policy_pack':
                promotion_detail = dict((inspected.get('related') or {}).get('baseline_promotion') or {})
                raw_saved_packs = [dict(item or {}) for item in list(data.get('saved_routing_policy_packs') or []) if isinstance(item, dict)]
                raw_registry_packs = [dict(item or {}) for item in list(data.get('routing_policy_pack_registry') or []) if isinstance(item, dict)]
                requested_pack_id = str(raw_payload.get('catalog_pack_id') or raw_payload.get('policy_pack_id') or raw_payload.get('pack_id') or '').strip()
                requested_catalog_entry_id = str(raw_payload.get('catalog_entry_id') or '').strip()
                target_pack_id = str(raw_payload.get('target_pack_id') or raw_payload.get('shared_pack_id') or requested_pack_id or requested_catalog_entry_id).strip() or requested_pack_id or requested_catalog_entry_id
                catalog_pack = self._resolve_baseline_promotion_simulation_custody_catalog_policy_pack(
                    gw,
                    promotion_detail=promotion_detail,
                    node_data=data,
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                    pack_id=requested_pack_id or None,
                    catalog_entry_id=requested_catalog_entry_id or None,
                )
                if not catalog_pack:
                    result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_missing'}
                elif str(catalog_pack.get('catalog_lifecycle_state') or 'draft') == 'deprecated':
                    result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_deprecated'}
                elif not self._baseline_promotion_simulation_custody_catalog_rollout_access(catalog_pack, current_context={**self._baseline_promotion_simulation_custody_catalog_context(promotion_detail=promotion_detail, node_data=data, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')), 'canvas_id': canvas_id, 'node_id': node_id}).get('allowed'):
                    result = {'ok': False, 'error': self._baseline_promotion_simulation_custody_catalog_rollout_access(catalog_pack, current_context={**self._baseline_promotion_simulation_custody_catalog_context(promotion_detail=promotion_detail, node_data=data, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')), 'canvas_id': canvas_id, 'node_id': node_id}).get('reason') or 'catalog_rollout_target_not_released'}
                else:
                    shared_pack = dict(catalog_pack)
                    shared_pack['pack_id'] = target_pack_id
                    shared_pack['source'] = 'shared_catalog'
                    shared_pack['shared_from_pack_id'] = str(catalog_pack.get('pack_id') or '')
                    shared_pack['shared_from_source'] = 'catalog'
                    shared_pack['catalog_entry_id'] = str(catalog_pack.get('catalog_entry_id') or catalog_pack.get('registry_entry_id') or '')
                    shared_pack['created_at'] = time.time()
                    shared_pack['created_by'] = str(actor or 'operator')
                    shared_pack['last_used_at'] = None
                    shared_pack['use_count'] = 0
                    updated_saved = [item for item in raw_saved_packs if str(item.get('pack_id') or '') != str(shared_pack.get('pack_id') or '')]
                    if str(catalog_pack.get('promoted_from_source') or '') == 'builtin':
                        saved_storage_pack = {
                            'pack_id': str(shared_pack.get('pack_id') or ''),
                            'pack_label': str(shared_pack.get('pack_label') or ''),
                            'source': 'shared_catalog',
                            'shared_from_pack_id': str(shared_pack.get('shared_from_pack_id') or ''),
                            'shared_from_source': str(shared_pack.get('shared_from_source') or ''),
                            'catalog_entry_id': str(shared_pack.get('catalog_entry_id') or ''),
                            'catalog_scope': str(shared_pack.get('catalog_scope') or ''),
                            'catalog_version_key': str(shared_pack.get('catalog_version_key') or ''),
                            'catalog_version': int(shared_pack.get('catalog_version') or 0),
                            'catalog_lifecycle_state': str(shared_pack.get('catalog_lifecycle_state') or 'draft'),
                            'scenario_count': int(shared_pack.get('scenario_count') or 0),
                        }
                    else:
                        saved_storage_pack = self._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(shared_pack)
                    updated_saved.append(saved_storage_pack)
                    target_entry_id = str(catalog_pack.get('catalog_entry_id') or catalog_pack.get('registry_entry_id') or '')
                    updated_registry = []
                    for item in raw_registry_packs:
                        normalized_item = self.openclaw_recovery_scheduler_service._normalize_baseline_promotion_simulation_custody_policy_what_if_pack(item, actor=str((item or {}).get('created_by') or (item or {}).get('promoted_by') or ''), source=str((item or {}).get('source') or 'registry'))
                        if str(normalized_item.get('catalog_entry_id') or normalized_item.get('registry_entry_id') or '') == target_entry_id:
                            normalized_item['catalog_share_count'] = int(normalized_item.get('catalog_share_count') or 0) + 1
                            normalized_item['catalog_last_shared_at'] = shared_pack.get('created_at')
                            normalized_item['catalog_last_shared_by'] = str(actor or 'operator')
                        updated_registry.append(self._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(normalized_item))
                    compact_pack = self._compact_baseline_promotion_simulation_routing_policy_pack(shared_pack)
                    updated_data = dict(data)
                    updated_data['saved_routing_policy_packs'] = updated_saved
                    updated_data['routing_policy_pack_registry'] = updated_registry
                    updated_data['last_shared_catalog_routing_policy_pack'] = {'pack_id': str(compact_pack.get('pack_id') or ''), 'pack_label': str(compact_pack.get('pack_label') or ''), 'source': str(compact_pack.get('source') or ''), 'shared_from_pack_id': str(compact_pack.get('shared_from_pack_id') or ''), 'shared_from_source': str(compact_pack.get('shared_from_source') or ''), 'catalog_entry_id': str(compact_pack.get('catalog_entry_id') or ''), 'scenario_count': int(compact_pack.get('scenario_count') or 0)}
                    if latest_simulation:
                        export_state = dict(latest_simulation.get('export_state') or {})
                        export_state['last_shared_catalog_routing_policy_pack'] = dict(updated_data['last_shared_catalog_routing_policy_pack'])
                        updated_simulation = dict(latest_simulation)
                        updated_simulation['export_state'] = export_state
                        updated_data['latest_simulation'] = self._baseline_promotion_simulation_state(simulation=updated_simulation, actor=str(updated_simulation.get('simulated_by') or actor or 'operator'), request=dict(updated_simulation.get('request') or {}), review=dict(updated_simulation.get('review') or {}), created_promotions=[dict(item) for item in list(updated_simulation.get('created_promotions') or [])])
                    node = dict((self._replace_node_data(gw, canvas_id=canvas_id, node=node, actor=actor, data=updated_data, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')) or {}).get('node') or node)
                    data = dict(node.get('data') or {})
                    result = {'ok': True, 'policy_pack': compact_pack, 'latest_simulation': dict(data.get('latest_simulation') or {})}
            elif normalized_action in {'request_cataloged_simulation_custody_routing_policy_pack_review', 'claim_cataloged_simulation_custody_routing_policy_pack_review', 'add_cataloged_simulation_custody_routing_policy_pack_review_note', 'submit_cataloged_simulation_custody_routing_policy_pack_review_decision'}:
                promotion_detail = dict((inspected.get('related') or {}).get('baseline_promotion') or {})
                raw_registry_packs = [dict(item or {}) for item in list(data.get('routing_policy_pack_registry') or []) if isinstance(item, dict)]
                requested_pack_id = str(raw_payload.get('catalog_pack_id') or raw_payload.get('policy_pack_id') or raw_payload.get('pack_id') or '').strip()
                requested_catalog_entry_id = str(raw_payload.get('catalog_entry_id') or '').strip()
                catalog_pack = self._resolve_baseline_promotion_simulation_custody_catalog_policy_pack(
                    gw,
                    promotion_detail=promotion_detail,
                    node_data=data,
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                    pack_id=requested_pack_id or None,
                    catalog_entry_id=requested_catalog_entry_id or None,
                )
                if not catalog_pack:
                    result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_missing'}
                else:
                    now = time.time()
                    target_entry_id = str(catalog_pack.get('catalog_entry_id') or catalog_pack.get('registry_entry_id') or '')
                    review_note = str(raw_payload.get('note') or raw_payload.get('review_note') or raw_payload.get('comment') or raw_payload.get('review_comment') or '').strip()
                    review_role = str(raw_payload.get('role') or raw_payload.get('reviewer_role') or raw_payload.get('assigned_role') or '').strip()
                    requested_reviewer = str(raw_payload.get('assigned_reviewer') or raw_payload.get('reviewer_id') or raw_payload.get('reviewer') or '').strip()
                    review_decision_input = str(raw_payload.get('decision') or raw_payload.get('review_decision') or '').strip().lower()
                    review_decision = {
                        'approved': 'review_approved',
                        'review_approved': 'review_approved',
                        'changes_requested': 'review_changes_requested',
                        'review_changes_requested': 'review_changes_requested',
                        'rejected': 'review_rejected',
                        'review_rejected': 'review_rejected',
                    }.get(review_decision_input, '')
                    current_review_state = self._baseline_promotion_simulation_custody_catalog_pack_review_state(catalog_pack)
                    assigned_reviewer = str(catalog_pack.get('catalog_review_assigned_reviewer') or '')
                    if normalized_action == 'claim_cataloged_simulation_custody_routing_policy_pack_review' and assigned_reviewer and assigned_reviewer != str(actor or 'operator'):
                        result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_review_assigned_to_other'}
                    elif normalized_action == 'submit_cataloged_simulation_custody_routing_policy_pack_review_decision' and not review_decision:
                        result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_review_decision_invalid'}
                    elif normalized_action in {'add_cataloged_simulation_custody_routing_policy_pack_review_note', 'submit_cataloged_simulation_custody_routing_policy_pack_review_decision'} and current_review_state == 'not_requested':
                        result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_review_not_requested'}
                    else:
                        updated_registry = []
                        for item in raw_registry_packs:
                            normalized_item = self.openclaw_recovery_scheduler_service._normalize_baseline_promotion_simulation_custody_policy_what_if_pack(item, actor=str((item or {}).get('created_by') or (item or {}).get('promoted_by') or ''), source=str((item or {}).get('source') or 'registry'))
                            entry_id = str(normalized_item.get('catalog_entry_id') or normalized_item.get('registry_entry_id') or '')
                            if entry_id == target_entry_id:
                                review_events = [dict(v or {}) for v in list(normalized_item.get('catalog_review_events') or []) if isinstance(v, dict)]
                                if normalized_action == 'request_cataloged_simulation_custody_routing_policy_pack_review':
                                    assigned = requested_reviewer or str(normalized_item.get('catalog_review_assigned_reviewer') or '')
                                    assigned_role = review_role or str(normalized_item.get('catalog_review_assigned_role') or '')
                                    normalized_item['catalog_review_state'] = 'pending_review'
                                    normalized_item['catalog_review_requested_at'] = now
                                    normalized_item['catalog_review_requested_by'] = str(actor or 'operator')
                                    normalized_item['catalog_review_assigned_reviewer'] = assigned
                                    normalized_item['catalog_review_assigned_role'] = assigned_role
                                    normalized_item['catalog_review_claimed_by'] = ''
                                    normalized_item['catalog_review_claimed_at'] = None
                                    normalized_item['catalog_review_decision'] = ''
                                    normalized_item['catalog_review_decision_at'] = None
                                    normalized_item['catalog_review_decision_by'] = ''
                                    normalized_item['catalog_review_latest_note'] = review_note or str(normalized_item.get('catalog_review_latest_note') or '')
                                    event = self._baseline_promotion_simulation_custody_catalog_pack_review_event(
                                        event_type='request_review',
                                        state='pending_review',
                                        actor=str(actor or 'operator'),
                                        at=now,
                                        role=assigned_role,
                                        note=review_note,
                                        assigned_reviewer=assigned,
                                    )
                                    review_events.append(event)
                                elif normalized_action == 'claim_cataloged_simulation_custody_routing_policy_pack_review':
                                    normalized_item['catalog_review_state'] = 'in_review'
                                    normalized_item['catalog_review_claimed_by'] = str(actor or 'operator')
                                    normalized_item['catalog_review_claimed_at'] = now
                                    normalized_item['catalog_review_assigned_reviewer'] = str(actor or 'operator')
                                    normalized_item['catalog_review_assigned_role'] = review_role or str(normalized_item.get('catalog_review_assigned_role') or '')
                                    event = self._baseline_promotion_simulation_custody_catalog_pack_review_event(
                                        event_type='claim_review',
                                        state='in_review',
                                        actor=str(actor or 'operator'),
                                        at=now,
                                        role=str(normalized_item.get('catalog_review_assigned_role') or review_role or ''),
                                        note=review_note,
                                        assigned_reviewer=str(actor or 'operator'),
                                    )
                                    review_events.append(event)
                                elif normalized_action == 'add_cataloged_simulation_custody_routing_policy_pack_review_note':
                                    normalized_item['catalog_review_state'] = 'in_review'
                                    normalized_item['catalog_review_claimed_by'] = str(normalized_item.get('catalog_review_claimed_by') or actor or 'operator')
                                    normalized_item['catalog_review_claimed_at'] = normalized_item.get('catalog_review_claimed_at') or now
                                    if not str(normalized_item.get('catalog_review_assigned_reviewer') or '').strip():
                                        normalized_item['catalog_review_assigned_reviewer'] = str(actor or 'operator')
                                    if review_role and not str(normalized_item.get('catalog_review_assigned_role') or '').strip():
                                        normalized_item['catalog_review_assigned_role'] = review_role
                                    normalized_item['catalog_review_latest_note'] = review_note
                                    event = self._baseline_promotion_simulation_custody_catalog_pack_review_event(
                                        event_type='add_review_note',
                                        state='in_review',
                                        actor=str(actor or 'operator'),
                                        at=now,
                                        role=review_role or str(normalized_item.get('catalog_review_assigned_role') or ''),
                                        note=review_note,
                                        assigned_reviewer=str(normalized_item.get('catalog_review_assigned_reviewer') or ''),
                                    )
                                    review_events.append(event)
                                else:
                                    normalized_item['catalog_review_state'] = review_decision
                                    normalized_item['catalog_review_claimed_by'] = str(normalized_item.get('catalog_review_claimed_by') or actor or 'operator')
                                    normalized_item['catalog_review_claimed_at'] = normalized_item.get('catalog_review_claimed_at') or now
                                    if not str(normalized_item.get('catalog_review_assigned_reviewer') or '').strip():
                                        normalized_item['catalog_review_assigned_reviewer'] = str(normalized_item.get('catalog_review_claimed_by') or actor or 'operator')
                                    normalized_item['catalog_review_decision'] = review_decision
                                    normalized_item['catalog_review_decision_at'] = now
                                    normalized_item['catalog_review_decision_by'] = str(actor or 'operator')
                                    normalized_item['catalog_review_latest_note'] = review_note or str(normalized_item.get('catalog_review_latest_note') or '')
                                    event = self._baseline_promotion_simulation_custody_catalog_pack_review_event(
                                        event_type='submit_review_decision',
                                        state=review_decision,
                                        actor=str(actor or 'operator'),
                                        at=now,
                                        role=review_role or str(normalized_item.get('catalog_review_assigned_role') or ''),
                                        note=review_note,
                                        decision=review_decision,
                                        assigned_reviewer=str(normalized_item.get('catalog_review_assigned_reviewer') or ''),
                                    )
                                    review_events.append(event)
                                review_events = review_events[-20:]
                                normalized_item['catalog_review_events'] = review_events
                                normalized_item['catalog_review_note_count'] = len([evt for evt in review_events if str((evt or {}).get('event_type') or '') in {'add_review_note', 'submit_review_decision', 'request_review'} and str((evt or {}).get('note') or '').strip()])
                                normalized_item['catalog_review_timeline'] = review_events[-5:]
                                normalized_item['catalog_review_last_transition_at'] = now
                                normalized_item['catalog_review_last_transition_by'] = str(actor or 'operator')
                                normalized_item['catalog_review_last_transition_action'] = {
                                    'request_cataloged_simulation_custody_routing_policy_pack_review': 'request_review',
                                    'claim_cataloged_simulation_custody_routing_policy_pack_review': 'claim_review',
                                    'add_cataloged_simulation_custody_routing_policy_pack_review_note': 'add_review_note',
                                    'submit_cataloged_simulation_custody_routing_policy_pack_review_decision': 'submit_review_decision',
                                }.get(normalized_action, '')
                            updated_registry.append(self._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(normalized_item))
                        normalized_updated_registry = self._baseline_promotion_simulation_custody_catalog_enrich_packs(self._baseline_promotion_simulation_custody_apply_catalog_version_flags(self._baseline_promotion_simulation_custody_registry_policy_packs(updated_registry)))
                        updated_registry = [self._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(item) for item in normalized_updated_registry]
                        updated_catalog_pack = next((item for item in normalized_updated_registry if str(item.get('catalog_entry_id') or item.get('registry_entry_id') or '') == target_entry_id), dict(catalog_pack))
                        compact_pack = self._compact_baseline_promotion_simulation_routing_policy_pack(updated_catalog_pack)
                        if normalized_action == 'export_cataloged_simulation_custody_routing_policy_pack_compliance_report':
                            compact_pack['catalog_compliance_report_count'] = max(1, int(compact_pack.get('catalog_compliance_report_count') or 0))
                            compact_pack['catalog_latest_compliance_report'] = self._compact_baseline_promotion_simulation_export_report({
                                **dict(export_result.get('report') or {}),
                                'integrity': dict(export_result.get('integrity') or {}),
                            })
                        elif normalized_action == 'export_cataloged_simulation_custody_routing_policy_pack_analytics_report':
                            compact_pack['catalog_analytics_report_count'] = max(1, int(compact_pack.get('catalog_analytics_report_count') or 0))
                            compact_pack['catalog_latest_analytics_report'] = self._compact_baseline_promotion_simulation_export_report({
                                **dict(export_result.get('report') or {}),
                                'integrity': dict(export_result.get('integrity') or {}),
                            })
                        updated_data = dict(data)
                        updated_data['routing_policy_pack_registry'] = updated_registry
                        updated_data['last_catalog_review_transition_routing_policy_pack'] = {
                            'pack_id': str(compact_pack.get('pack_id') or ''),
                            'catalog_entry_id': str(compact_pack.get('catalog_entry_id') or ''),
                            'catalog_review_state': str(compact_pack.get('catalog_review_state') or ''),
                            'catalog_review_assigned_reviewer': str(compact_pack.get('catalog_review_assigned_reviewer') or ''),
                            'catalog_review_claimed_by': str(compact_pack.get('catalog_review_claimed_by') or ''),
                            'catalog_review_decision': str(compact_pack.get('catalog_review_decision') or ''),
                            'catalog_review_note_count': int(compact_pack.get('catalog_review_note_count') or 0),
                            'at': now,
                            'by': str(actor or 'operator'),
                        }
                        if latest_simulation:
                            export_state = dict(latest_simulation.get('export_state') or {})
                            export_state['last_catalog_review_transition_routing_policy_pack'] = dict(updated_data['last_catalog_review_transition_routing_policy_pack'])
                            updated_simulation = dict(latest_simulation)
                            export_state['routing_policy_pack_catalog_summary'] = self._baseline_promotion_simulation_custody_catalog_summary(normalized_updated_registry)
                            updated_simulation['export_state'] = export_state
                            updated_data['latest_simulation'] = self._baseline_promotion_simulation_state(simulation=updated_simulation, actor=str(updated_simulation.get('simulated_by') or actor or 'operator'), request=dict(updated_simulation.get('request') or {}), review=dict(updated_simulation.get('review') or {}), created_promotions=[dict(item) for item in list(updated_simulation.get('created_promotions') or [])])
                        node = dict((self._replace_node_data(gw, canvas_id=canvas_id, node=node, actor=actor, data=updated_data, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')) or {}).get('node') or node)
                        data = dict(node.get('data') or {})
                        result = {'ok': True, 'policy_pack': compact_pack, 'latest_simulation': dict(data.get('latest_simulation') or {})}
            elif normalized_action in {'request_cataloged_simulation_custody_routing_policy_pack_approval', 'reject_cataloged_simulation_custody_routing_policy_pack_approval', 'curate_cataloged_simulation_custody_routing_policy_pack', 'approve_cataloged_simulation_custody_routing_policy_pack', 'deprecate_cataloged_simulation_custody_routing_policy_pack', 'stage_cataloged_simulation_custody_routing_policy_pack_release', 'release_cataloged_simulation_custody_routing_policy_pack', 'advance_cataloged_simulation_custody_routing_policy_pack_rollout', 'pause_cataloged_simulation_custody_routing_policy_pack_rollout', 'resume_cataloged_simulation_custody_routing_policy_pack_rollout', 'freeze_cataloged_simulation_custody_routing_policy_pack_rollout', 'unfreeze_cataloged_simulation_custody_routing_policy_pack_rollout', 'rollback_cataloged_simulation_custody_routing_policy_pack_rollout', 'rollback_cataloged_simulation_custody_routing_policy_pack_release', 'emergency_withdraw_cataloged_simulation_custody_routing_policy_pack_release', 'withdraw_cataloged_simulation_custody_routing_policy_pack_release'}:
                promotion_detail = dict((inspected.get('related') or {}).get('baseline_promotion') or {})
                raw_registry_packs = [dict(item or {}) for item in list(data.get('routing_policy_pack_registry') or []) if isinstance(item, dict)]
                requested_pack_id = str(raw_payload.get('catalog_pack_id') or raw_payload.get('policy_pack_id') or raw_payload.get('pack_id') or '').strip()
                requested_catalog_entry_id = str(raw_payload.get('catalog_entry_id') or '').strip()
                catalog_pack = self._resolve_baseline_promotion_simulation_custody_catalog_policy_pack(
                    gw,
                    promotion_detail=promotion_detail,
                    node_data=data,
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                    pack_id=requested_pack_id or None,
                    catalog_entry_id=requested_catalog_entry_id or None,
                )
                if not catalog_pack:
                    result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_missing'}
                else:
                    now = time.time()
                    target_entry_id = str(catalog_pack.get('catalog_entry_id') or catalog_pack.get('registry_entry_id') or '')
                    version_key = str(catalog_pack.get('catalog_version_key') or '')
                    target_version = int(catalog_pack.get('catalog_version') or 0)
                    target_scope_key = str(catalog_pack.get('catalog_scope_key') or '')
                    approval_note = str(raw_payload.get('note') or raw_payload.get('reason') or '').strip()
                    approval_role = str(raw_payload.get('role') or raw_payload.get('requested_role') or '').strip()
                    rollout_summary = self._baseline_promotion_simulation_custody_catalog_rollout_summary(catalog_pack)
                    current_catalog_context = self._baseline_promotion_simulation_custody_catalog_context(
                        promotion_detail=promotion_detail,
                        node_data=data,
                        tenant_id=scope.get('tenant_id'),
                        workspace_id=scope.get('workspace_id'),
                        environment=scope.get('environment'),
                    )
                    catalog_packs_context = self._baseline_promotion_simulation_custody_catalog_policy_packs(
                        gw,
                        promotion_detail=promotion_detail,
                        node_data=data,
                        tenant_id=scope.get('tenant_id'),
                        workspace_id=scope.get('workspace_id'),
                        environment=scope.get('environment'),
                    )
                    stage_guard = self._baseline_promotion_simulation_custody_catalog_release_guard(catalog_pack, catalog_packs=catalog_packs_context, action='stage')
                    release_guard = self._baseline_promotion_simulation_custody_catalog_release_guard(catalog_pack, catalog_packs=catalog_packs_context, action='release')
                    if normalized_action == 'stage_cataloged_simulation_custody_routing_policy_pack_release' and not bool(stage_guard.get('passed')) and str(stage_guard.get('reason') or ''):
                        result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_release_blocked', 'guard_evaluation': stage_guard}
                    elif normalized_action == 'stage_cataloged_simulation_custody_routing_policy_pack_release' and not self._baseline_promotion_simulation_custody_catalog_pack_release_ready(catalog_pack):
                        result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_release_not_ready'}
                    elif normalized_action == 'stage_cataloged_simulation_custody_routing_policy_pack_release' and not bool(stage_guard.get('passed')):
                        result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_release_blocked', 'guard_evaluation': stage_guard}
                    elif normalized_action == 'release_cataloged_simulation_custody_routing_policy_pack' and not bool(release_guard.get('passed')) and str(release_guard.get('reason') or ''):
                        result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_release_blocked', 'guard_evaluation': release_guard}
                    elif normalized_action == 'release_cataloged_simulation_custody_routing_policy_pack' and not self._baseline_promotion_simulation_custody_catalog_pack_release_ready(catalog_pack):
                        result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_release_not_ready'}
                    elif normalized_action == 'release_cataloged_simulation_custody_routing_policy_pack' and not bool(release_guard.get('passed')):
                        result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_release_blocked', 'guard_evaluation': release_guard}
                    elif normalized_action == 'release_cataloged_simulation_custody_routing_policy_pack' and str(catalog_pack.get('catalog_release_state') or 'draft') not in {'staged', 'released', 'rolling_out'}:
                        result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_release_not_staged'}
                    elif normalized_action == 'advance_cataloged_simulation_custody_routing_policy_pack_rollout' and not bool(rollout_summary.get('enabled')):
                        result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_rollout_missing'}
                    elif normalized_action == 'advance_cataloged_simulation_custody_routing_policy_pack_rollout' and str(rollout_summary.get('state') or '') != 'rolling_out':
                        result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_rollout_not_active'}
                    elif normalized_action == 'advance_cataloged_simulation_custody_routing_policy_pack_rollout' and not self._baseline_promotion_simulation_custody_catalog_rollout_gate(catalog_pack, catalog_packs=catalog_packs_context).get('passed'):
                        result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_rollout_gate_failed', 'gate_evaluation': self._baseline_promotion_simulation_custody_catalog_rollout_gate(catalog_pack, catalog_packs=catalog_packs_context)}
                    elif normalized_action == 'pause_cataloged_simulation_custody_routing_policy_pack_rollout' and str(rollout_summary.get('state') or '') != 'rolling_out':
                        result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_rollout_not_active'}
                    elif normalized_action == 'resume_cataloged_simulation_custody_routing_policy_pack_rollout' and not bool(catalog_pack.get('catalog_rollout_paused', False)):
                        result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_rollout_not_paused'}
                    elif normalized_action == 'freeze_cataloged_simulation_custody_routing_policy_pack_rollout' and not bool(rollout_summary.get('enabled')):
                        result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_rollout_missing'}
                    elif normalized_action == 'unfreeze_cataloged_simulation_custody_routing_policy_pack_rollout' and not bool(catalog_pack.get('catalog_rollout_frozen', False)):
                        result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_rollout_not_frozen'}
                    elif normalized_action == 'rollback_cataloged_simulation_custody_routing_policy_pack_rollout' and not bool(rollout_summary.get('enabled')):
                        result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_rollout_missing'}
                    elif normalized_action == 'emergency_withdraw_cataloged_simulation_custody_routing_policy_pack_release' and str(catalog_pack.get('catalog_release_state') or 'draft') not in {'staged', 'rolling_out', 'released'}:
                        result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_release_not_active'}
                    elif normalized_action == 'rollback_cataloged_simulation_custody_routing_policy_pack_release' and not self._baseline_promotion_simulation_custody_catalog_previous_restore_candidate(catalog_pack, catalog_packs=catalog_packs_context):
                        result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_release_rollback_target_missing'}
                    else:
                        updated_registry = []
                        for item in raw_registry_packs:
                            normalized_item = self.openclaw_recovery_scheduler_service._normalize_baseline_promotion_simulation_custody_policy_what_if_pack(item, actor=str((item or {}).get('created_by') or (item or {}).get('promoted_by') or ''), source=str((item or {}).get('source') or 'registry'))
                            entry_id = str(normalized_item.get('catalog_entry_id') or normalized_item.get('registry_entry_id') or '')
                            if entry_id == target_entry_id:
                                approvals = [dict(v or {}) for v in list(normalized_item.get('catalog_approvals') or []) if isinstance(v, dict)]
                                approval_required = bool(normalized_item.get('catalog_approval_required', False))
                                required_approvals = max(0, int(normalized_item.get('catalog_required_approvals') or 0))
                                if normalized_action == 'request_cataloged_simulation_custody_routing_policy_pack_approval':
                                    approval_required = bool(raw_payload.get('catalog_approval_required', True if required_approvals <= 0 else approval_required))
                                    required_approvals = max(0, int(raw_payload.get('catalog_required_approvals') or required_approvals or (1 if approval_required else 0)))
                                    normalized_item['catalog_approval_required'] = approval_required
                                    normalized_item['catalog_required_approvals'] = required_approvals
                                    normalized_item['catalog_approval_state'] = 'pending' if approval_required and required_approvals > 0 else 'not_required'
                                    normalized_item['catalog_approval_requested_at'] = now
                                    normalized_item['catalog_approval_requested_by'] = str(actor or 'operator')
                                    normalized_item['catalog_approval_rejected_at'] = None
                                    normalized_item['catalog_approval_rejected_by'] = ''
                                    if approval_note or approval_role:
                                        approvals.append({'approval_id': f'approval_request_{int(now)}', 'decision': 'requested', 'actor': str(actor or 'operator'), 'role': approval_role, 'at': now, 'note': approval_note})
                                elif normalized_action == 'reject_cataloged_simulation_custody_routing_policy_pack_approval':
                                    normalized_item['catalog_approval_state'] = 'rejected'
                                    normalized_item['catalog_approval_rejected_at'] = now
                                    normalized_item['catalog_approval_rejected_by'] = str(actor or 'operator')
                                    approvals.append({'approval_id': f'approval_reject_{int(now)}', 'decision': 'rejected', 'actor': str(actor or 'operator'), 'role': approval_role, 'at': now, 'note': approval_note})
                                elif normalized_action == 'curate_cataloged_simulation_custody_routing_policy_pack':
                                    normalized_item['catalog_lifecycle_state'] = 'curated'
                                    normalized_item['catalog_curated_at'] = now
                                    normalized_item['catalog_curated_by'] = str(actor or 'operator')
                                elif normalized_action == 'approve_cataloged_simulation_custody_routing_policy_pack':
                                    if approval_required and required_approvals <= 0:
                                        required_approvals = 1
                                        normalized_item['catalog_required_approvals'] = 1
                                    existing_approved_count = max(0, int(normalized_item.get('catalog_approval_count') or 0))
                                    appended_approval = False
                                    if not any(str(approval.get('actor') or '') == str(actor or 'operator') and str(approval.get('decision') or '') == 'approved' for approval in approvals):
                                        approvals.append({'approval_id': f'approval_{int(now)}_{len(approvals)+1}', 'decision': 'approved', 'actor': str(actor or 'operator'), 'role': approval_role, 'at': now, 'note': approval_note})
                                        appended_approval = True
                                    approved_count = len([approval for approval in approvals if str(approval.get('decision') or '') == 'approved'])
                                    approved_count = max(approved_count, existing_approved_count + (1 if appended_approval else 0))
                                    normalized_item['catalog_approval_count'] = approved_count
                                    normalized_item['catalog_approval_rejected_at'] = None
                                    normalized_item['catalog_approval_rejected_by'] = ''
                                    if approval_required and required_approvals > 0 and approved_count < required_approvals:
                                        normalized_item['catalog_approval_state'] = 'pending'
                                        normalized_item['catalog_lifecycle_state'] = 'curated' if str(normalized_item.get('catalog_lifecycle_state') or 'draft') == 'draft' else str(normalized_item.get('catalog_lifecycle_state') or 'curated')
                                        normalized_item['catalog_curated_at'] = normalized_item.get('catalog_curated_at') or now
                                        normalized_item['catalog_curated_by'] = str(normalized_item.get('catalog_curated_by') or actor or 'operator')
                                    else:
                                        normalized_item['catalog_approval_state'] = 'approved' if approval_required and required_approvals > 0 else 'not_required'
                                        normalized_item['catalog_lifecycle_state'] = 'approved'
                                        normalized_item['catalog_curated_at'] = normalized_item.get('catalog_curated_at') or now
                                        normalized_item['catalog_curated_by'] = str(normalized_item.get('catalog_curated_by') or actor or 'operator')
                                        normalized_item['catalog_approved_at'] = now
                                        normalized_item['catalog_approved_by'] = str(actor or 'operator')
                                        normalized_item['catalog_deprecated_at'] = None
                                        normalized_item['catalog_deprecated_by'] = ''
                                        normalized_item['catalog_replaced_by_version'] = 0
                                elif normalized_action == 'deprecate_cataloged_simulation_custody_routing_policy_pack':
                                    normalized_item['catalog_lifecycle_state'] = 'deprecated'
                                    normalized_item['catalog_deprecated_at'] = now
                                    normalized_item['catalog_deprecated_by'] = str(actor or 'operator')
                                elif normalized_action == 'stage_cataloged_simulation_custody_routing_policy_pack_release':
                                    rollout_policy = self._baseline_promotion_simulation_custody_catalog_rollout_policy(raw_payload.get('catalog_rollout_policy') or normalized_item.get('catalog_rollout_policy') or {})
                                    normalized_item['catalog_release_state'] = 'staged'
                                    normalized_item['catalog_release_notes'] = str(raw_payload.get('catalog_release_notes') or normalized_item.get('catalog_release_notes') or '')
                                    normalized_item['catalog_release_train_id'] = str(raw_payload.get('catalog_release_train_id') or normalized_item.get('catalog_release_train_id') or '')
                                    normalized_item['catalog_release_staged_at'] = now
                                    normalized_item['catalog_release_staged_by'] = str(actor or 'operator')
                                    normalized_item['catalog_rollout_policy'] = rollout_policy
                                    normalized_item['catalog_rollout_enabled'] = bool(rollout_policy.get('enabled'))
                                    if bool(rollout_policy.get('enabled')):
                                        targets = self._baseline_promotion_simulation_custody_catalog_rollout_targets(gw, pack=normalized_item, current_context=current_catalog_context)
                                        waves = self._baseline_promotion_simulation_custody_catalog_rollout_waves(targets, wave_size=int(rollout_policy.get('wave_size') or 1), existing_waves=normalized_item.get('catalog_rollout_waves') or [])
                                        normalized_item['catalog_rollout_targets'] = targets
                                        normalized_item['catalog_rollout_waves'] = waves
                                        normalized_item['catalog_rollout_train_id'] = str(raw_payload.get('catalog_rollout_train_id') or normalized_item.get('catalog_rollout_train_id') or normalized_item.get('catalog_release_train_id') or f'rollout-{target_entry_id[:12]}')
                                        normalized_item['catalog_rollout_state'] = 'staged'
                                        normalized_item['catalog_rollout_current_wave_index'] = 0
                                        normalized_item['catalog_rollout_completed_wave_count'] = 0
                                        normalized_item['catalog_rollout_paused'] = False
                                        normalized_item['catalog_rollout_frozen'] = False
                                elif normalized_action == 'release_cataloged_simulation_custody_routing_policy_pack':
                                    rollout_policy = self._baseline_promotion_simulation_custody_catalog_rollout_policy(raw_payload.get('catalog_rollout_policy') or normalized_item.get('catalog_rollout_policy') or {})
                                    normalized_item['catalog_release_notes'] = str(raw_payload.get('catalog_release_notes') or normalized_item.get('catalog_release_notes') or '')
                                    normalized_item['catalog_release_train_id'] = str(raw_payload.get('catalog_release_train_id') or normalized_item.get('catalog_release_train_id') or '')
                                    normalized_item['catalog_released_at'] = now
                                    normalized_item['catalog_released_by'] = str(actor or 'operator')
                                    normalized_item['catalog_release_staged_at'] = normalized_item.get('catalog_release_staged_at') or now
                                    normalized_item['catalog_release_staged_by'] = str(normalized_item.get('catalog_release_staged_by') or actor or 'operator')
                                    normalized_item['catalog_withdrawn_at'] = None
                                    normalized_item['catalog_withdrawn_by'] = ''
                                    normalized_item['catalog_withdrawn_reason'] = ''
                                    normalized_item['catalog_emergency_withdrawal_active'] = False
                                    normalized_item['catalog_emergency_withdrawal_at'] = None
                                    normalized_item['catalog_emergency_withdrawal_by'] = ''
                                    normalized_item['catalog_emergency_withdrawal_reason'] = ''
                                    normalized_item['catalog_emergency_withdrawal_incident_id'] = ''
                                    normalized_item['catalog_emergency_withdrawal_severity'] = ''
                                    normalized_item['catalog_rollback_release_state'] = ''
                                    normalized_item['catalog_rollback_release_at'] = None
                                    normalized_item['catalog_rollback_release_by'] = ''
                                    normalized_item['catalog_rollback_release_reason'] = ''
                                    normalized_item['catalog_rollback_target_entry_id'] = ''
                                    normalized_item['catalog_rollback_target_version'] = 0
                                    normalized_item['catalog_restored_from_entry_id'] = ''
                                    normalized_item['catalog_restored_from_version'] = 0
                                    normalized_item['catalog_restored_at'] = None
                                    normalized_item['catalog_restored_by'] = ''
                                    normalized_item['catalog_restored_reason'] = ''
                                    normalized_item['catalog_rollout_policy'] = rollout_policy
                                    previous_release = next((dict(item or {}) for item in list(catalog_packs_context or []) if isinstance(item, dict) and str(item.get('catalog_version_key') or '') == version_key and str(item.get('catalog_scope_key') or '') == target_scope_key and str(item.get('catalog_release_state') or '') in {'released', 'rolling_out'} and str(item.get('catalog_entry_id') or item.get('registry_entry_id') or '') != target_entry_id), {})
                                    normalized_item['catalog_supersedes_entry_id'] = str(previous_release.get('catalog_entry_id') or previous_release.get('registry_entry_id') or '')
                                    normalized_item['catalog_supersedes_version'] = int(previous_release.get('catalog_version') or 0)
                                    normalized_item['catalog_rollout_enabled'] = bool(rollout_policy.get('enabled'))
                                    if bool(rollout_policy.get('enabled')):
                                        targets = self._baseline_promotion_simulation_custody_catalog_rollout_targets(gw, pack=normalized_item, current_context=current_catalog_context)
                                        waves = self._baseline_promotion_simulation_custody_catalog_rollout_waves(targets, wave_size=int(rollout_policy.get('wave_size') or 1), existing_waves=normalized_item.get('catalog_rollout_waves') or [])
                                        normalized_item['catalog_rollout_targets'] = targets
                                        normalized_item['catalog_rollout_waves'] = waves
                                        normalized_item['catalog_rollout_train_id'] = str(raw_payload.get('catalog_rollout_train_id') or normalized_item.get('catalog_rollout_train_id') or normalized_item.get('catalog_release_train_id') or f'rollout-{target_entry_id[:12]}')
                                        normalized_item['catalog_rollout_started_at'] = normalized_item.get('catalog_rollout_started_at') or now
                                        normalized_item['catalog_rollout_started_by'] = str(normalized_item.get('catalog_rollout_started_by') or actor or 'operator')
                                        normalized_item['catalog_rollout_paused'] = False
                                        normalized_item['catalog_rollout_frozen'] = False
                                        if waves:
                                            normalized_item = self._baseline_promotion_simulation_custody_catalog_rollout_activate_wave(normalized_item, wave_index=1, actor=str(actor or 'operator'), at=now)
                                            if len(waves) == 1:
                                                normalized_item['catalog_rollout_waves'][0]['status'] = 'completed'
                                                normalized_item['catalog_rollout_completed_wave_count'] = 1
                                                normalized_item['catalog_rollout_state'] = 'completed'
                                                normalized_item['catalog_release_state'] = 'released'
                                                normalized_item['catalog_rollout_completed_at'] = now
                                                normalized_item['catalog_rollout_completed_by'] = str(actor or 'operator')
                                            else:
                                                normalized_item['catalog_rollout_state'] = 'rolling_out'
                                                normalized_item['catalog_release_state'] = 'rolling_out'
                                        else:
                                            normalized_item['catalog_rollout_state'] = 'completed'
                                            normalized_item['catalog_release_state'] = 'released'
                                            normalized_item['catalog_rollout_completed_at'] = now
                                            normalized_item['catalog_rollout_completed_by'] = str(actor or 'operator')
                                    else:
                                        normalized_item['catalog_release_state'] = 'released'
                                elif normalized_action == 'advance_cataloged_simulation_custody_routing_policy_pack_rollout':
                                    waves = [dict(v or {}) for v in list(normalized_item.get('catalog_rollout_waves') or []) if isinstance(v, dict)]
                                    current_wave_index = int(normalized_item.get('catalog_rollout_current_wave_index') or 0)
                                    gate = self._baseline_promotion_simulation_custody_catalog_rollout_gate(normalized_item, wave_index=current_wave_index, catalog_packs=catalog_packs_context)
                                    normalized_item['catalog_rollout_latest_gate'] = gate
                                    for wave in waves:
                                        if int(wave.get('wave_index') or 0) == current_wave_index:
                                            wave['status'] = 'completed'
                                            wave['gate_evaluation'] = dict(gate)
                                    normalized_item['catalog_rollout_waves'] = waves
                                    normalized_item['catalog_rollout_completed_wave_count'] = len([wave for wave in waves if str(wave.get('status') or '') == 'completed'])
                                    next_wave_index = current_wave_index + 1
                                    if next_wave_index <= len(waves):
                                        normalized_item = self._baseline_promotion_simulation_custody_catalog_rollout_activate_wave(normalized_item, wave_index=next_wave_index, actor=str(actor or 'operator'), at=now)
                                        normalized_item['catalog_rollout_state'] = 'rolling_out'
                                        normalized_item['catalog_release_state'] = 'rolling_out'
                                    else:
                                        normalized_item['catalog_rollout_state'] = 'completed'
                                        normalized_item['catalog_release_state'] = 'released'
                                        normalized_item['catalog_rollout_completed_at'] = now
                                        normalized_item['catalog_rollout_completed_by'] = str(actor or 'operator')
                                elif normalized_action == 'pause_cataloged_simulation_custody_routing_policy_pack_rollout':
                                    normalized_item['catalog_rollout_paused'] = True
                                    normalized_item['catalog_rollout_state'] = 'paused'
                                elif normalized_action == 'resume_cataloged_simulation_custody_routing_policy_pack_rollout':
                                    normalized_item['catalog_rollout_paused'] = False
                                    normalized_item['catalog_rollout_state'] = 'rolling_out'
                                elif normalized_action == 'freeze_cataloged_simulation_custody_routing_policy_pack_rollout':
                                    normalized_item['catalog_rollout_frozen'] = True
                                elif normalized_action == 'unfreeze_cataloged_simulation_custody_routing_policy_pack_rollout':
                                    normalized_item['catalog_rollout_frozen'] = False
                                elif normalized_action == 'rollback_cataloged_simulation_custody_routing_policy_pack_rollout':
                                    normalized_item['catalog_rollout_state'] = 'rolled_back'
                                    normalized_item['catalog_rollout_rolled_back_at'] = now
                                    normalized_item['catalog_rollout_rolled_back_by'] = str(actor or 'operator')
                                    normalized_item['catalog_rollout_rolled_back_reason'] = str(raw_payload.get('catalog_rollout_rolled_back_reason') or approval_note or 'manual_rollback')
                                    normalized_item['catalog_release_state'] = 'withdrawn'
                                    normalized_item['catalog_withdrawn_at'] = now
                                    normalized_item['catalog_withdrawn_by'] = str(actor or 'operator')
                                    normalized_item['catalog_withdrawn_reason'] = str(raw_payload.get('catalog_withdrawn_reason') or normalized_item.get('catalog_rollout_rolled_back_reason') or '')
                                elif normalized_action == 'rollback_cataloged_simulation_custody_routing_policy_pack_release':
                                    rollback_target = self._baseline_promotion_simulation_custody_catalog_previous_restore_candidate(normalized_item, catalog_packs=catalog_packs_context)
                                    normalized_item['catalog_release_state'] = 'withdrawn'
                                    normalized_item['catalog_withdrawn_at'] = now
                                    normalized_item['catalog_withdrawn_by'] = str(actor or 'operator')
                                    normalized_item['catalog_withdrawn_reason'] = str(raw_payload.get('catalog_withdrawn_reason') or raw_payload.get('catalog_rollback_release_reason') or 'rollback_to_previous_release')
                                    normalized_item['catalog_rollback_release_state'] = 'rolled_back_to_previous_release' if rollback_target else 'rolled_back_without_restore'
                                    normalized_item['catalog_rollback_release_at'] = now
                                    normalized_item['catalog_rollback_release_by'] = str(actor or 'operator')
                                    normalized_item['catalog_rollback_release_reason'] = str(raw_payload.get('catalog_rollback_release_reason') or normalized_item.get('catalog_withdrawn_reason') or 'rollback_to_previous_release')
                                    normalized_item['catalog_rollback_target_entry_id'] = str((rollback_target or {}).get('catalog_entry_id') or '')
                                    normalized_item['catalog_rollback_target_version'] = int((rollback_target or {}).get('catalog_version') or 0)
                                    if bool(normalized_item.get('catalog_rollout_enabled', False)):
                                        normalized_item['catalog_rollout_state'] = 'rolled_back'
                                        normalized_item['catalog_rollout_rolled_back_at'] = now
                                        normalized_item['catalog_rollout_rolled_back_by'] = str(actor or 'operator')
                                        normalized_item['catalog_rollout_rolled_back_reason'] = str(normalized_item.get('catalog_rollback_release_reason') or 'release_rollback')
                                elif normalized_action == 'emergency_withdraw_cataloged_simulation_custody_routing_policy_pack_release':
                                    normalized_item['catalog_release_state'] = 'withdrawn'
                                    normalized_item['catalog_withdrawn_at'] = now
                                    normalized_item['catalog_withdrawn_by'] = str(actor or 'operator')
                                    normalized_item['catalog_withdrawn_reason'] = str(raw_payload.get('catalog_withdrawn_reason') or raw_payload.get('catalog_emergency_withdrawal_reason') or approval_note or 'emergency_withdrawal')
                                    normalized_item['catalog_emergency_withdrawal_active'] = True
                                    normalized_item['catalog_emergency_withdrawal_at'] = now
                                    normalized_item['catalog_emergency_withdrawal_by'] = str(actor or 'operator')
                                    normalized_item['catalog_emergency_withdrawal_reason'] = str(raw_payload.get('catalog_emergency_withdrawal_reason') or normalized_item.get('catalog_withdrawn_reason') or 'emergency_withdrawal')
                                    normalized_item['catalog_emergency_withdrawal_incident_id'] = str(raw_payload.get('incident_id') or raw_payload.get('catalog_emergency_withdrawal_incident_id') or '')
                                    normalized_item['catalog_emergency_withdrawal_severity'] = str(raw_payload.get('severity') or raw_payload.get('catalog_emergency_withdrawal_severity') or 'high')
                                    if bool(normalized_item.get('catalog_rollout_enabled', False)):
                                        normalized_item['catalog_rollout_state'] = 'rolled_back'
                                        normalized_item['catalog_rollout_rolled_back_at'] = now
                                        normalized_item['catalog_rollout_rolled_back_by'] = str(actor or 'operator')
                                        normalized_item['catalog_rollout_rolled_back_reason'] = str(normalized_item.get('catalog_emergency_withdrawal_reason') or 'emergency_withdrawal')
                                else:
                                    normalized_item['catalog_release_state'] = 'withdrawn'
                                    normalized_item['catalog_withdrawn_at'] = now
                                    normalized_item['catalog_withdrawn_by'] = str(actor or 'operator')
                                    normalized_item['catalog_withdrawn_reason'] = str(raw_payload.get('catalog_withdrawn_reason') or approval_note or normalized_item.get('catalog_withdrawn_reason') or '')
                                    if bool(normalized_item.get('catalog_rollout_enabled', False)):
                                        normalized_item['catalog_rollout_state'] = 'rolled_back'
                                        normalized_item['catalog_rollout_rolled_back_at'] = now
                                        normalized_item['catalog_rollout_rolled_back_by'] = str(actor or 'operator')
                                        normalized_item['catalog_rollout_rolled_back_reason'] = str(normalized_item.get('catalog_withdrawn_reason') or 'release_withdrawn')
                                normalized_item['catalog_rollout_last_transition_at'] = now
                                normalized_item['catalog_rollout_last_transition_by'] = str(actor or 'operator')
                                normalized_item['catalog_rollout_last_transition_action'] = normalized_action
                                normalized_item['catalog_approvals'] = approvals[:12]
                                if not normalized_item.get('catalog_approval_count'):
                                    normalized_item['catalog_approval_count'] = len([approval for approval in approvals if str(approval.get('decision') or '') == 'approved'])
                                updated_registry.append(self._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(normalized_item))
                                continue
                            if normalized_action == 'approve_cataloged_simulation_custody_routing_policy_pack' and version_key and str(normalized_item.get('catalog_version_key') or '') == version_key and str(normalized_item.get('catalog_lifecycle_state') or '') == 'approved':
                                normalized_item['catalog_lifecycle_state'] = 'deprecated'
                                normalized_item['catalog_deprecated_at'] = now
                                normalized_item['catalog_deprecated_by'] = str(actor or 'operator')
                                normalized_item['catalog_replaced_by_version'] = target_version
                            if normalized_action == 'release_cataloged_simulation_custody_routing_policy_pack' and version_key and target_scope_key and str(normalized_item.get('catalog_version_key') or '') == version_key and str(normalized_item.get('catalog_scope_key') or '') == target_scope_key and str(normalized_item.get('catalog_release_state') or '') in {'released', 'rolling_out'}:
                                normalized_item['catalog_release_state'] = 'withdrawn'
                                normalized_item['catalog_withdrawn_at'] = now
                                normalized_item['catalog_withdrawn_by'] = str(actor or 'operator')
                                normalized_item['catalog_withdrawn_reason'] = 'replaced_by_new_release'
                                normalized_item['catalog_supersedence_state'] = 'superseded'
                                normalized_item['catalog_superseded_at'] = now
                                normalized_item['catalog_superseded_by'] = str(actor or 'operator')
                                normalized_item['catalog_superseded_reason'] = 'replaced_by_new_release'
                                normalized_item['catalog_superseded_by_entry_id'] = target_entry_id
                                normalized_item['catalog_superseded_by_version'] = target_version
                                if bool(normalized_item.get('catalog_rollout_enabled', False)):
                                    normalized_item['catalog_rollout_state'] = 'rolled_back'
                                    normalized_item['catalog_rollout_rolled_back_at'] = now
                                    normalized_item['catalog_rollout_rolled_back_by'] = str(actor or 'operator')
                                    normalized_item['catalog_rollout_rolled_back_reason'] = 'replaced_by_new_release'
                            if normalized_action == 'rollback_cataloged_simulation_custody_routing_policy_pack_release' and version_key and target_scope_key and str(normalized_item.get('catalog_version_key') or '') == version_key and str(normalized_item.get('catalog_scope_key') or '') == target_scope_key and str(normalized_item.get('catalog_entry_id') or normalized_item.get('registry_entry_id') or '') == str((self._baseline_promotion_simulation_custody_catalog_previous_restore_candidate(catalog_pack, catalog_packs=catalog_packs_context) or {}).get('catalog_entry_id') or ''):
                                normalized_item['catalog_release_state'] = 'released'
                                normalized_item['catalog_lifecycle_state'] = 'approved'
                                normalized_item['catalog_deprecated_at'] = None
                                normalized_item['catalog_deprecated_by'] = ''
                                normalized_item['catalog_replaced_by_version'] = 0
                                normalized_item['catalog_withdrawn_at'] = None
                                normalized_item['catalog_withdrawn_by'] = ''
                                normalized_item['catalog_withdrawn_reason'] = ''
                                normalized_item['catalog_restored_from_entry_id'] = target_entry_id
                                normalized_item['catalog_restored_from_version'] = target_version
                                normalized_item['catalog_restored_at'] = now
                                normalized_item['catalog_restored_by'] = str(actor or 'operator')
                                normalized_item['catalog_restored_reason'] = str(raw_payload.get('catalog_rollback_release_reason') or 'release_rollback_restore')
                                normalized_item['catalog_emergency_withdrawal_active'] = False
                                normalized_item['catalog_emergency_withdrawal_at'] = None
                                normalized_item['catalog_emergency_withdrawal_by'] = ''
                                normalized_item['catalog_emergency_withdrawal_reason'] = ''
                                normalized_item['catalog_emergency_withdrawal_incident_id'] = ''
                                normalized_item['catalog_emergency_withdrawal_severity'] = ''
                                normalized_item['catalog_supersedence_state'] = ''
                                normalized_item['catalog_superseded_at'] = None
                                normalized_item['catalog_superseded_by'] = ''
                                normalized_item['catalog_superseded_reason'] = ''
                                normalized_item['catalog_superseded_by_entry_id'] = ''
                                normalized_item['catalog_superseded_by_version'] = 0
                                normalized_item['catalog_superseded_by_bundle_id'] = ''
                                if bool(normalized_item.get('catalog_rollout_enabled', False)):
                                    normalized_item['catalog_rollout_state'] = 'completed'
                                    normalized_item['catalog_rollout_completed_at'] = now
                                    normalized_item['catalog_rollout_completed_by'] = str(actor or 'operator')
                            updated_registry.append(self._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(normalized_item))
                        normalized_updated_registry = self._baseline_promotion_simulation_custody_catalog_enrich_packs(self._baseline_promotion_simulation_custody_apply_catalog_version_flags(self._baseline_promotion_simulation_custody_registry_policy_packs(updated_registry)))
                        updated_registry = [self._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(item) for item in normalized_updated_registry]
                        updated_catalog_pack = next((item for item in normalized_updated_registry if str(item.get('catalog_entry_id') or item.get('registry_entry_id') or '') == target_entry_id), dict(catalog_pack))
                        compact_pack = self._compact_baseline_promotion_simulation_routing_policy_pack(updated_catalog_pack)
                        if normalized_action == 'rollback_cataloged_simulation_custody_routing_policy_pack_release':
                            rollback_target = self._baseline_promotion_simulation_custody_catalog_previous_restore_candidate(catalog_pack, catalog_packs=catalog_packs_context)
                            if rollback_target:
                                self._baseline_promotion_simulation_custody_rebind_catalog_bindings(
                                    gw,
                                    from_pack=updated_catalog_pack,
                                    to_pack=rollback_target,
                                    actor=str(actor or 'operator'),
                                    tenant_id=scope.get('tenant_id'),
                                    reason=str(raw_payload.get('catalog_rollback_release_reason') or 'release_rollback_restore'),
                                )
                        if normalized_action == 'export_cataloged_simulation_custody_routing_policy_pack_compliance_report':
                            compact_pack['catalog_compliance_report_count'] = max(1, int(compact_pack.get('catalog_compliance_report_count') or 0))
                            compact_pack['catalog_latest_compliance_report'] = self._compact_baseline_promotion_simulation_export_report({
                                **dict(export_result.get('report') or {}),
                                'integrity': dict(export_result.get('integrity') or {}),
                            })
                        elif normalized_action == 'export_cataloged_simulation_custody_routing_policy_pack_analytics_report':
                            compact_pack['catalog_analytics_report_count'] = max(1, int(compact_pack.get('catalog_analytics_report_count') or 0))
                            compact_pack['catalog_latest_analytics_report'] = self._compact_baseline_promotion_simulation_export_report({
                                **dict(export_result.get('report') or {}),
                                'integrity': dict(export_result.get('integrity') or {}),
                            })
                        updated_data = dict(data)
                        updated_data['routing_policy_pack_registry'] = updated_registry
                        if normalized_action in {'request_cataloged_simulation_custody_routing_policy_pack_approval', 'reject_cataloged_simulation_custody_routing_policy_pack_approval', 'approve_cataloged_simulation_custody_routing_policy_pack'}:
                            updated_data['last_catalog_approval_transition_routing_policy_pack'] = {'pack_id': str(compact_pack.get('pack_id') or ''), 'catalog_entry_id': str(compact_pack.get('catalog_entry_id') or ''), 'catalog_approval_state': str(compact_pack.get('catalog_approval_state') or ''), 'catalog_approval_count': int(compact_pack.get('catalog_approval_count') or 0), 'catalog_required_approvals': int(compact_pack.get('catalog_required_approvals') or 0), 'at': now, 'by': str(actor or 'operator')}
                        elif normalized_action in {'stage_cataloged_simulation_custody_routing_policy_pack_release', 'release_cataloged_simulation_custody_routing_policy_pack', 'rollback_cataloged_simulation_custody_routing_policy_pack_release', 'emergency_withdraw_cataloged_simulation_custody_routing_policy_pack_release', 'withdraw_cataloged_simulation_custody_routing_policy_pack_release'}:
                            updated_data['last_catalog_release_transition_routing_policy_pack'] = {'pack_id': str(compact_pack.get('pack_id') or ''), 'catalog_entry_id': str(compact_pack.get('catalog_entry_id') or ''), 'catalog_release_state': str(compact_pack.get('catalog_release_state') or ''), 'catalog_version_key': str(compact_pack.get('catalog_version_key') or ''), 'catalog_version': int(compact_pack.get('catalog_version') or 0), 'at': now, 'by': str(actor or 'operator')}
                        elif normalized_action in {'advance_cataloged_simulation_custody_routing_policy_pack_rollout', 'pause_cataloged_simulation_custody_routing_policy_pack_rollout', 'resume_cataloged_simulation_custody_routing_policy_pack_rollout', 'freeze_cataloged_simulation_custody_routing_policy_pack_rollout', 'unfreeze_cataloged_simulation_custody_routing_policy_pack_rollout', 'rollback_cataloged_simulation_custody_routing_policy_pack_rollout'}:
                            updated_data['last_catalog_rollout_transition_routing_policy_pack'] = {'pack_id': str(compact_pack.get('pack_id') or ''), 'catalog_entry_id': str(compact_pack.get('catalog_entry_id') or ''), 'catalog_rollout_train_id': str(compact_pack.get('catalog_rollout_train_id') or ''), 'catalog_rollout_state': str(compact_pack.get('catalog_rollout_state') or ''), 'catalog_rollout_current_wave_index': int(compact_pack.get('catalog_rollout_current_wave_index') or 0), 'catalog_rollout_completed_wave_count': int(compact_pack.get('catalog_rollout_completed_wave_count') or 0), 'catalog_rollout_frozen': bool(compact_pack.get('catalog_rollout_frozen', False)), 'catalog_rollout_paused': bool(compact_pack.get('catalog_rollout_paused', False)), 'at': now, 'by': str(actor or 'operator')}
                        else:
                            updated_data['last_catalog_lifecycle_transition_routing_policy_pack'] = {'pack_id': str(compact_pack.get('pack_id') or ''), 'pack_label': str(compact_pack.get('pack_label') or ''), 'catalog_entry_id': str(compact_pack.get('catalog_entry_id') or ''), 'catalog_version_key': str(compact_pack.get('catalog_version_key') or ''), 'catalog_version': int(compact_pack.get('catalog_version') or 0), 'catalog_lifecycle_state': str(compact_pack.get('catalog_lifecycle_state') or ''), 'at': now, 'by': str(actor or 'operator')}
                        if latest_simulation:
                            export_state = dict(latest_simulation.get('export_state') or {})
                            if 'last_catalog_lifecycle_transition_routing_policy_pack' in updated_data:
                                export_state['last_catalog_lifecycle_transition_routing_policy_pack'] = dict(updated_data['last_catalog_lifecycle_transition_routing_policy_pack'])
                            if 'last_catalog_approval_transition_routing_policy_pack' in updated_data:
                                export_state['last_catalog_approval_transition_routing_policy_pack'] = dict(updated_data['last_catalog_approval_transition_routing_policy_pack'])
                            if 'last_catalog_release_transition_routing_policy_pack' in updated_data:
                                export_state['last_catalog_release_transition_routing_policy_pack'] = dict(updated_data['last_catalog_release_transition_routing_policy_pack'])
                            if 'last_catalog_rollout_transition_routing_policy_pack' in updated_data:
                                export_state['last_catalog_rollout_transition_routing_policy_pack'] = dict(updated_data['last_catalog_rollout_transition_routing_policy_pack'])
                            export_state['routing_policy_pack_catalog_summary'] = self._baseline_promotion_simulation_custody_catalog_summary(normalized_updated_registry)
                            updated_simulation = dict(latest_simulation)
                            updated_simulation['export_state'] = export_state
                            updated_data['latest_simulation'] = self._baseline_promotion_simulation_state(simulation=updated_simulation, actor=str(updated_simulation.get('simulated_by') or actor or 'operator'), request=dict(updated_simulation.get('request') or {}), review=dict(updated_simulation.get('review') or {}), created_promotions=[dict(item) for item in list(updated_simulation.get('created_promotions') or [])])
                        node = dict((self._replace_node_data(gw, canvas_id=canvas_id, node=node, actor=actor, data=updated_data, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')) or {}).get('node') or node)
                        data = dict(node.get('data') or {})
                        result = {'ok': True, 'policy_pack': compact_pack, 'latest_simulation': dict(data.get('latest_simulation') or {})}
            elif normalized_action in {'export_cataloged_simulation_custody_routing_policy_pack_evidence_package', 'export_cataloged_simulation_custody_routing_policy_pack_signed_release_bundle', 'export_cataloged_simulation_custody_routing_policy_pack_compliance_report', 'export_cataloged_simulation_custody_routing_policy_pack_analytics_report'}:
                promotion_detail = dict((inspected.get('related') or {}).get('baseline_promotion') or {})
                requested_pack_id = str(raw_payload.get('catalog_pack_id') or raw_payload.get('policy_pack_id') or raw_payload.get('pack_id') or '').strip()
                requested_catalog_entry_id = str(raw_payload.get('catalog_entry_id') or '').strip()
                catalog_pack = self._resolve_baseline_promotion_simulation_custody_catalog_policy_pack(
                    gw,
                    promotion_detail=promotion_detail,
                    node_data=data,
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                    pack_id=requested_pack_id or None,
                    catalog_entry_id=requested_catalog_entry_id or None,
                )
                if not catalog_pack:
                    result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_missing'}
                elif normalized_action == 'export_cataloged_simulation_custody_routing_policy_pack_signed_release_bundle' and str(catalog_pack.get('catalog_release_state') or 'draft') == 'draft':
                    result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_release_bundle_not_ready'}
                else:
                    catalog_packs = self._baseline_promotion_simulation_custody_catalog_policy_packs(
                        gw,
                        promotion_detail=promotion_detail,
                        node_data=data,
                        tenant_id=scope.get('tenant_id'),
                        workspace_id=scope.get('workspace_id'),
                        environment=scope.get('environment'),
                    )
                    if normalized_action == 'export_cataloged_simulation_custody_routing_policy_pack_evidence_package':
                        export_result = self._build_baseline_promotion_simulation_custody_catalog_pack_evidence_package_export(
                            pack=catalog_pack,
                            actor=actor,
                            promotion_detail=promotion_detail,
                            tenant_id=scope.get('tenant_id'),
                            workspace_id=scope.get('workspace_id'),
                            environment=scope.get('environment'),
                            catalog_packs=catalog_packs,
                        )
                    elif normalized_action == 'export_cataloged_simulation_custody_routing_policy_pack_signed_release_bundle':
                        export_result = self._build_baseline_promotion_simulation_custody_catalog_pack_signed_release_bundle_export(
                            pack=catalog_pack,
                            actor=actor,
                            promotion_detail=promotion_detail,
                            tenant_id=scope.get('tenant_id'),
                            workspace_id=scope.get('workspace_id'),
                            environment=scope.get('environment'),
                            catalog_packs=catalog_packs,
                        )
                    else:
                        catalog_bindings = self._baseline_promotion_simulation_custody_catalog_policy_bindings(gw, tenant_id=scope.get('tenant_id'))
                        if normalized_action == 'export_cataloged_simulation_custody_routing_policy_pack_analytics_report':
                            export_result = self._build_baseline_promotion_simulation_custody_catalog_pack_analytics_report_export(
                                pack=catalog_pack,
                                actor=actor,
                                promotion_detail=promotion_detail,
                                tenant_id=scope.get('tenant_id'),
                                workspace_id=scope.get('workspace_id'),
                                environment=scope.get('environment'),
                                node_data=data,
                                catalog_packs=catalog_packs,
                                bindings=catalog_bindings,
                            )
                        else:
                            export_result = self._build_baseline_promotion_simulation_custody_catalog_pack_compliance_report_export(
                                pack=catalog_pack,
                                actor=actor,
                                promotion_detail=promotion_detail,
                                tenant_id=scope.get('tenant_id'),
                                workspace_id=scope.get('workspace_id'),
                                environment=scope.get('environment'),
                                node_data=data,
                                catalog_packs=catalog_packs,
                                bindings=catalog_bindings,
                            )
                    if not export_result.get('ok'):
                        result = export_result
                    else:
                        now = time.time()
                        target_entry_id = str(catalog_pack.get('catalog_entry_id') or catalog_pack.get('registry_entry_id') or '')
                        raw_registry_packs = [dict(item or {}) for item in list(data.get('routing_policy_pack_registry') or []) if isinstance(item, dict)]
                        updated_registry = []
                        for item in raw_registry_packs:
                            normalized_item = self.openclaw_recovery_scheduler_service._normalize_baseline_promotion_simulation_custody_policy_what_if_pack(item, actor=str((item or {}).get('created_by') or (item or {}).get('promoted_by') or ''), source=str((item or {}).get('source') or 'registry'))
                            entry_id = str(normalized_item.get('catalog_entry_id') or normalized_item.get('registry_entry_id') or '')
                            if entry_id == target_entry_id:
                                if normalized_action == 'export_cataloged_simulation_custody_routing_policy_pack_evidence_package':
                                    normalized_item['catalog_evidence_package_count'] = int(normalized_item.get('catalog_evidence_package_count') or 0) + 1
                                    normalized_item['catalog_latest_evidence_package'] = self._compact_baseline_promotion_simulation_export_report({
                                        **dict(export_result.get('report') or {}),
                                        'integrity': dict(export_result.get('integrity') or {}),
                                    })
                                elif normalized_action == 'export_cataloged_simulation_custody_routing_policy_pack_signed_release_bundle':
                                    normalized_item['catalog_release_bundle_count'] = int(normalized_item.get('catalog_release_bundle_count') or 0) + 1
                                    normalized_item['catalog_latest_release_bundle'] = self._compact_baseline_promotion_simulation_export_report({
                                        **dict(export_result.get('report') or {}),
                                        'release_bundle_id': str(export_result.get('release_bundle_id') or (export_result.get('report') or {}).get('release_bundle_id') or (export_result.get('report') or {}).get('report_id') or ''),
                                        'integrity': dict(export_result.get('integrity') or {}),
                                    })
                                else:
                                    if normalized_action == 'export_cataloged_simulation_custody_routing_policy_pack_analytics_report':
                                        normalized_item['catalog_analytics_report_count'] = int(normalized_item.get('catalog_analytics_report_count') or 0) + 1
                                        normalized_item['catalog_latest_analytics_report'] = self._compact_baseline_promotion_simulation_export_report({
                                            **dict(export_result.get('report') or {}),
                                            'integrity': dict(export_result.get('integrity') or {}),
                                        })
                                    else:
                                        normalized_item['catalog_compliance_report_count'] = int(normalized_item.get('catalog_compliance_report_count') or 0) + 1
                                        normalized_item['catalog_latest_compliance_report'] = self._compact_baseline_promotion_simulation_export_report({
                                            **dict(export_result.get('report') or {}),
                                            'integrity': dict(export_result.get('integrity') or {}),
                                        })
                            updated_registry.append(self._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(normalized_item))
                        normalized_updated_registry = self._baseline_promotion_simulation_custody_catalog_enrich_packs(self._baseline_promotion_simulation_custody_apply_catalog_version_flags(self._baseline_promotion_simulation_custody_registry_policy_packs(updated_registry)))
                        updated_registry = [self._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(item) for item in normalized_updated_registry]
                        updated_catalog_pack = next((item for item in normalized_updated_registry if str(item.get('catalog_entry_id') or item.get('registry_entry_id') or '') == target_entry_id), dict(catalog_pack))
                        compact_pack = self._compact_baseline_promotion_simulation_routing_policy_pack(updated_catalog_pack)
                        if normalized_action == 'export_cataloged_simulation_custody_routing_policy_pack_compliance_report':
                            compact_pack['catalog_compliance_report_count'] = max(1, int(compact_pack.get('catalog_compliance_report_count') or 0))
                            compact_pack['catalog_latest_compliance_report'] = self._compact_baseline_promotion_simulation_export_report({
                                **dict(export_result.get('report') or {}),
                                'integrity': dict(export_result.get('integrity') or {}),
                            })
                        updated_data = dict(data)
                        updated_data['routing_policy_pack_registry'] = updated_registry
                        if normalized_action == 'export_cataloged_simulation_custody_routing_policy_pack_evidence_package':
                            updated_data['last_catalog_evidence_package_routing_policy_pack'] = {
                                'pack_id': str(compact_pack.get('pack_id') or ''),
                                'catalog_entry_id': target_entry_id,
                                'report_id': str((export_result.get('report') or {}).get('report_id') or ''),
                                'report_type': str((export_result.get('report') or {}).get('report_type') or ''),
                                'package_id': str((export_result.get('report') or {}).get('package_id') or ''),
                                'at': now,
                                'by': str(actor or 'operator'),
                            }
                        elif normalized_action == 'export_cataloged_simulation_custody_routing_policy_pack_signed_release_bundle':
                            updated_data['last_catalog_signed_release_bundle_routing_policy_pack'] = {
                                'pack_id': str(compact_pack.get('pack_id') or ''),
                                'catalog_entry_id': target_entry_id,
                                'report_id': str((export_result.get('report') or {}).get('report_id') or ''),
                                'report_type': str((export_result.get('report') or {}).get('report_type') or ''),
                                'release_bundle_id': str(export_result.get('release_bundle_id') or (export_result.get('report') or {}).get('release_bundle_id') or ''),
                                'at': now,
                                'by': str(actor or 'operator'),
                            }
                        else:
                            if normalized_action == 'export_cataloged_simulation_custody_routing_policy_pack_analytics_report':
                                updated_data['last_catalog_analytics_report_routing_policy_pack'] = {
                                    'pack_id': str(compact_pack.get('pack_id') or ''),
                                    'catalog_entry_id': target_entry_id,
                                    'report_id': str((export_result.get('report') or {}).get('report_id') or ''),
                                    'report_type': str((export_result.get('report') or {}).get('report_type') or ''),
                                    'overall_status': str((((export_result.get('report') or {}).get('catalog_analytics_summary')) or {}).get('overall_status') or ''),
                                    'total_replay_count': int((((export_result.get('report') or {}).get('catalog_analytics_summary')) or {}).get('total_replay_count') or 0),
                                    'at': now,
                                    'by': str(actor or 'operator'),
                                }
                            else:
                                updated_data['last_catalog_compliance_report_routing_policy_pack'] = {
                                    'pack_id': str(compact_pack.get('pack_id') or ''),
                                    'catalog_entry_id': target_entry_id,
                                    'report_id': str((export_result.get('report') or {}).get('report_id') or ''),
                                    'report_type': str((export_result.get('report') or {}).get('report_type') or ''),
                                    'overall_status': str((((export_result.get('report') or {}).get('compliance')) or {}).get('overall_status') or ''),
                                    'drifted_count': int((((export_result.get('report') or {}).get('compliance_summary')) or {}).get('drifted_count') or 0),
                                    'at': now,
                                    'by': str(actor or 'operator'),
                                }
                        node = dict((self._replace_node_data(gw, canvas_id=canvas_id, node=node, actor=actor, data=updated_data, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')) or {}).get('node') or node)
                        data = dict(node.get('data') or {})
                        result = {**export_result, 'policy_pack': compact_pack, 'latest_simulation': dict(data.get('latest_simulation') or {})}
            elif normalized_action in {'publish_cataloged_simulation_custody_routing_policy_pack_to_organizational_catalog_service', 'withdraw_cataloged_simulation_custody_routing_policy_pack_from_organizational_catalog_service', 'export_organizational_simulation_custody_routing_policy_pack_catalog_service_snapshot', 'reconcile_organizational_simulation_custody_routing_policy_pack_catalog_service', 'export_organizational_simulation_custody_routing_policy_pack_catalog_service_reconciliation_report'}:
                promotion_detail = dict((inspected.get('related') or {}).get('baseline_promotion') or {})
                if normalized_action in {'export_organizational_simulation_custody_routing_policy_pack_catalog_service_snapshot', 'reconcile_organizational_simulation_custody_routing_policy_pack_catalog_service', 'export_organizational_simulation_custody_routing_policy_pack_catalog_service_reconciliation_report'}:
                    if normalized_action == 'export_organizational_simulation_custody_routing_policy_pack_catalog_service_snapshot':
                        export_result = self._build_baseline_promotion_simulation_custody_organizational_catalog_snapshot_export(
                            gw,
                            actor=actor,
                            promotion_detail=promotion_detail,
                            tenant_id=scope.get('tenant_id'),
                            workspace_id=scope.get('workspace_id'),
                            environment=scope.get('environment'),
                            node_data=data,
                        )
                        updated_data = dict(data)
                        updated_data['last_organizational_catalog_snapshot_routing_policy_pack'] = {
                            'report_id': str((export_result.get('report') or {}).get('report_id') or ''),
                            'report_type': str((export_result.get('report') or {}).get('report_type') or ''),
                            'service_id': str(((export_result.get('report') or {}).get('service') or {}).get('service_id') or ''),
                            'published_entry_count': int(((export_result.get('report') or {}).get('summary') or {}).get('published_entry_count') or 0),
                            'at': time.time(),
                            'by': str(actor or 'operator'),
                        }
                    else:
                        export_result = self._build_baseline_promotion_simulation_custody_organizational_catalog_reconciliation_export(
                            gw,
                            actor=actor,
                            promotion_detail=promotion_detail,
                            tenant_id=scope.get('tenant_id'),
                            workspace_id=scope.get('workspace_id'),
                            environment=scope.get('environment'),
                            node_data=data,
                        )
                        updated_data = dict(data)
                        updated_data['last_organizational_catalog_reconciliation_routing_policy_pack'] = {
                            'report_id': str((export_result.get('report') or {}).get('report_id') or ''),
                            'report_type': str((export_result.get('report') or {}).get('report_type') or ''),
                            'service_id': str(((export_result.get('report') or {}).get('service') or {}).get('service_id') or ''),
                            'overall_status': str((export_result.get('reconciliation_summary') or {}).get('overall_status') or ''),
                            'drifted_publication_count': int((export_result.get('reconciliation_summary') or {}).get('drifted_publication_count') or 0),
                            'healthy_publication_count': int((export_result.get('reconciliation_summary') or {}).get('healthy_publication_count') or 0),
                            'at': time.time(),
                            'by': str(actor or 'operator'),
                        }
                    node = dict((self._replace_node_data(gw, canvas_id=canvas_id, node=node, actor=actor, data=updated_data, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')) or {}).get('node') or node)
                    data = dict(node.get('data') or {})
                    result = {**export_result, 'latest_simulation': dict(data.get('latest_simulation') or {})}
                else:
                    raw_registry_packs = [dict(item or {}) for item in list(data.get('routing_policy_pack_registry') or []) if isinstance(item, dict)]
                    requested_pack_id = str(raw_payload.get('catalog_pack_id') or raw_payload.get('policy_pack_id') or raw_payload.get('pack_id') or '').strip()
                    requested_catalog_entry_id = str(raw_payload.get('catalog_entry_id') or '').strip()
                    catalog_pack = self._resolve_baseline_promotion_simulation_custody_catalog_policy_pack(
                        gw,
                        promotion_detail=promotion_detail,
                        node_data=data,
                        tenant_id=scope.get('tenant_id'),
                        workspace_id=scope.get('workspace_id'),
                        environment=scope.get('environment'),
                        pack_id=requested_pack_id or None,
                        catalog_entry_id=requested_catalog_entry_id or None,
                    )
                    if not catalog_pack:
                        result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_missing'}
                    elif normalized_action == 'publish_cataloged_simulation_custody_routing_policy_pack_to_organizational_catalog_service' and (str(catalog_pack.get('catalog_lifecycle_state') or 'draft') != 'approved' or str(catalog_pack.get('catalog_release_state') or 'draft') not in {'released', 'rolling_out'}):
                        result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_not_publishable'}
                    elif normalized_action == 'withdraw_cataloged_simulation_custody_routing_policy_pack_from_organizational_catalog_service' and str(catalog_pack.get('organizational_publish_state') or '') != 'published':
                        result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_not_published_to_organizational_catalog_service'}
                    else:
                        target_entry_id = str(catalog_pack.get('catalog_entry_id') or catalog_pack.get('registry_entry_id') or '')
                        target_version = int(catalog_pack.get('catalog_version') or 0)
                        organizational_visibility = str(raw_payload.get('organizational_visibility') or raw_payload.get('visibility') or catalog_pack.get('organizational_visibility') or 'tenant').strip() or 'tenant'
                        service_id = self._baseline_promotion_simulation_custody_organizational_catalog_service_id(tenant_id=scope.get('tenant_id'))
                        scope_key = self._baseline_promotion_simulation_custody_organizational_catalog_scope_key(
                            organizational_visibility,
                            tenant_id=scope.get('tenant_id'),
                            workspace_id=scope.get('workspace_id'),
                            environment=scope.get('environment'),
                        )
                        updated_registry = []
                        for item in raw_registry_packs:
                            normalized_item = self.openclaw_recovery_scheduler_service._normalize_baseline_promotion_simulation_custody_policy_what_if_pack(item, actor=str((item or {}).get('created_by') or (item or {}).get('promoted_by') or ''), source=str((item or {}).get('source') or 'registry'))
                            if str(normalized_item.get('catalog_entry_id') or normalized_item.get('registry_entry_id') or '') == target_entry_id and int(normalized_item.get('catalog_version') or 0) == target_version:
                                if normalized_action == 'publish_cataloged_simulation_custody_routing_policy_pack_to_organizational_catalog_service':
                                    normalized_item['organizational_service_id'] = service_id
                                    normalized_item['organizational_service_entry_id'] = str(normalized_item.get('organizational_service_entry_id') or self.openclaw_recovery_scheduler_service._stable_digest({'service_id': service_id, 'catalog_entry_id': target_entry_id, 'catalog_version': target_version})[:24])
                                    normalized_item['organizational_publish_state'] = 'published'
                                    normalized_item['organizational_visibility'] = organizational_visibility
                                    normalized_item['organizational_service_scope_key'] = scope_key
                                    normalized_item['organizational_published_at'] = time.time()
                                    normalized_item['organizational_published_by'] = str(actor or 'operator')
                                    normalized_item['organizational_withdrawn_at'] = None
                                    normalized_item['organizational_withdrawn_by'] = ''
                                    normalized_item['organizational_withdrawn_reason'] = ''
                                    normalized_item['organizational_publication_manifest'] = self._baseline_promotion_simulation_custody_organizational_publication_manifest(
                                        normalized_item,
                                        tenant_id=scope.get('tenant_id'),
                                        workspace_id=scope.get('workspace_id'),
                                        environment=scope.get('environment'),
                                    )
                                else:
                                    normalized_item['organizational_publish_state'] = 'withdrawn'
                                    normalized_item['organizational_withdrawn_at'] = time.time()
                                    normalized_item['organizational_withdrawn_by'] = str(actor or 'operator')
                                    normalized_item['organizational_withdrawn_reason'] = str(raw_payload.get('reason') or raw_payload.get('note') or 'manual_withdrawal')
                            updated_registry.append(self._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(normalized_item))
                        normalized_updated_registry = self._baseline_promotion_simulation_custody_catalog_enrich_packs(self._baseline_promotion_simulation_custody_apply_catalog_version_flags(self._baseline_promotion_simulation_custody_registry_policy_packs(updated_registry)))
                        updated_registry = [self._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(item) for item in normalized_updated_registry]
                        updated_catalog_pack = next((item for item in normalized_updated_registry if str(item.get('catalog_entry_id') or item.get('registry_entry_id') or '') == target_entry_id and int(item.get('catalog_version') or 0) == target_version), dict(catalog_pack))
                        compact_pack = self._compact_baseline_promotion_simulation_routing_policy_pack(updated_catalog_pack)
                        updated_data = dict(data)
                        updated_data['routing_policy_pack_registry'] = updated_registry
                        if normalized_action == 'publish_cataloged_simulation_custody_routing_policy_pack_to_organizational_catalog_service':
                            updated_data['last_organizational_catalog_publish_routing_policy_pack'] = {
                                'catalog_entry_id': target_entry_id,
                                'catalog_version': target_version,
                                'pack_id': str(compact_pack.get('pack_id') or ''),
                                'organizational_service_id': str(compact_pack.get('organizational_service_id') or ''),
                                'organizational_service_entry_id': str(compact_pack.get('organizational_service_entry_id') or ''),
                                'organizational_visibility': str(compact_pack.get('organizational_visibility') or ''),
                                'at': time.time(),
                                'by': str(actor or 'operator'),
                            }
                        else:
                            updated_data['last_organizational_catalog_withdraw_routing_policy_pack'] = {
                                'catalog_entry_id': target_entry_id,
                                'catalog_version': target_version,
                                'pack_id': str(compact_pack.get('pack_id') or ''),
                                'organizational_service_entry_id': str(compact_pack.get('organizational_service_entry_id') or ''),
                                'organizational_publish_state': str(compact_pack.get('organizational_publish_state') or ''),
                                'at': time.time(),
                                'by': str(actor or 'operator'),
                            }
                        node = dict((self._replace_node_data(gw, canvas_id=canvas_id, node=node, actor=actor, data=updated_data, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')) or {}).get('node') or node)
                        data = dict(node.get('data') or {})
                        result = {'ok': True, 'policy_pack': compact_pack, 'latest_simulation': dict(data.get('latest_simulation') or {})}
            elif normalized_action == 'export_cataloged_simulation_custody_routing_policy_pack_attestation':
                promotion_detail = dict((inspected.get('related') or {}).get('baseline_promotion') or {})
                requested_pack_id = str(raw_payload.get('catalog_pack_id') or raw_payload.get('policy_pack_id') or raw_payload.get('pack_id') or '').strip()
                requested_catalog_entry_id = str(raw_payload.get('catalog_entry_id') or '').strip()
                catalog_pack = self._resolve_baseline_promotion_simulation_custody_catalog_policy_pack(
                    gw,
                    promotion_detail=promotion_detail,
                    node_data=data,
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                    pack_id=requested_pack_id or None,
                    catalog_entry_id=requested_catalog_entry_id or None,
                )
                if not catalog_pack:
                    result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_missing'}
                else:
                    export_result = self._build_baseline_promotion_simulation_custody_catalog_pack_attestation_export(
                        pack=catalog_pack,
                        actor=actor,
                        promotion_detail=promotion_detail,
                        tenant_id=scope.get('tenant_id'),
                        workspace_id=scope.get('workspace_id'),
                        environment=scope.get('environment'),
                        catalog_packs=self._baseline_promotion_simulation_custody_catalog_policy_packs(
                            gw,
                            promotion_detail=promotion_detail,
                            node_data=data,
                            tenant_id=scope.get('tenant_id'),
                            workspace_id=scope.get('workspace_id'),
                            environment=scope.get('environment'),
                        ),
                    )
                    if not export_result.get('ok'):
                        result = export_result
                    else:
                        now = time.time()
                        target_entry_id = str(catalog_pack.get('catalog_entry_id') or catalog_pack.get('registry_entry_id') or '')
                        raw_registry_packs = [dict(item or {}) for item in list(data.get('routing_policy_pack_registry') or []) if isinstance(item, dict)]
                        updated_registry = []
                        for item in raw_registry_packs:
                            normalized_item = self.openclaw_recovery_scheduler_service._normalize_baseline_promotion_simulation_custody_policy_what_if_pack(item, actor=str((item or {}).get('created_by') or (item or {}).get('promoted_by') or ''), source=str((item or {}).get('source') or 'registry'))
                            entry_id = str(normalized_item.get('catalog_entry_id') or normalized_item.get('registry_entry_id') or '')
                            if entry_id == target_entry_id:
                                normalized_item['catalog_attestation_count'] = int(normalized_item.get('catalog_attestation_count') or 0) + 1
                                normalized_item['catalog_latest_attestation'] = self._compact_baseline_promotion_simulation_export_report({
                                    **dict(export_result.get('report') or {}),
                                    'integrity': dict(export_result.get('integrity') or {}),
                                })
                            updated_registry.append(self._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(normalized_item))
                        updated_data = dict(data)
                        updated_data['routing_policy_pack_registry'] = updated_registry
                        updated_data['last_catalog_attestation_routing_policy_pack'] = {'pack_id': str(catalog_pack.get('pack_id') or ''), 'catalog_entry_id': target_entry_id, 'report_id': str((export_result.get('report') or {}).get('report_id') or ''), 'report_type': str((export_result.get('report') or {}).get('report_type') or ''), 'at': now, 'by': str(actor or 'operator')}
                        if latest_simulation:
                            export_state = dict(latest_simulation.get('export_state') or {})
                            export_state['last_catalog_attestation_routing_policy_pack'] = dict(updated_data['last_catalog_attestation_routing_policy_pack'])
                            updated_simulation = dict(latest_simulation)
                            updated_simulation['export_state'] = export_state
                            updated_data['latest_simulation'] = self._baseline_promotion_simulation_state(simulation=updated_simulation, actor=str(updated_simulation.get('simulated_by') or actor or 'operator'), request=dict(updated_simulation.get('request') or {}), review=dict(updated_simulation.get('review') or {}), created_promotions=[dict(item) for item in list(updated_simulation.get('created_promotions') or [])])
                        node = dict((self._replace_node_data(gw, canvas_id=canvas_id, node=node, actor=actor, data=updated_data, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')) or {}).get('node') or node)
                        data = dict(node.get('data') or {})
                        result = {**export_result, 'latest_simulation': dict(data.get('latest_simulation') or {})}

            elif normalized_action in {'bind_cataloged_simulation_custody_routing_policy_pack_effective_policy', 'unbind_cataloged_simulation_custody_routing_policy_pack_effective_policy'}:
                promotion_detail = dict((inspected.get('related') or {}).get('baseline_promotion') or {})
                raw_bindings = [dict(item or {}) for item in list(data.get('routing_policy_pack_bindings') or []) if isinstance(item, dict)]
                raw_binding_events = [dict(item or {}) for item in list(data.get('routing_policy_pack_binding_events') or []) if isinstance(item, dict)]
                current_catalog_context = self._baseline_promotion_simulation_custody_catalog_context(
                    promotion_detail=promotion_detail,
                    node_data=data,
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                )
                requested_pack_id = str(raw_payload.get('catalog_pack_id') or raw_payload.get('policy_pack_id') or raw_payload.get('pack_id') or '').strip()
                requested_catalog_entry_id = str(raw_payload.get('catalog_entry_id') or '').strip()
                all_catalog_packs = self._baseline_promotion_simulation_custody_catalog_policy_packs(
                    gw,
                    promotion_detail=promotion_detail,
                    node_data=data,
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                )
                all_bindings = self._baseline_promotion_simulation_custody_catalog_policy_bindings(gw, tenant_id=scope.get('tenant_id'))
                now = time.time()
                if normalized_action == 'bind_cataloged_simulation_custody_routing_policy_pack_effective_policy':
                    catalog_pack = self._resolve_baseline_promotion_simulation_custody_catalog_policy_pack(
                        gw,
                        promotion_detail=promotion_detail,
                        node_data=data,
                        tenant_id=scope.get('tenant_id'),
                        workspace_id=scope.get('workspace_id'),
                        environment=scope.get('environment'),
                        pack_id=requested_pack_id or None,
                        catalog_entry_id=requested_catalog_entry_id or None,
                    )
                    if not catalog_pack:
                        result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_missing'}
                    elif str(catalog_pack.get('catalog_lifecycle_state') or '') != 'approved' or str(catalog_pack.get('catalog_release_state') or '') not in {'released', 'rolling_out'}:
                        result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_binding_not_releasable'}
                    else:
                        binding_scope = str(raw_payload.get('binding_scope') or raw_payload.get('adoption_scope') or 'promotion').strip() or 'promotion'
                        binding_context = {
                            'promotion_id': str(raw_payload.get('binding_promotion_id') or current_catalog_context.get('promotion_id') or ''),
                            'workspace_id': str(raw_payload.get('binding_workspace_id') or current_catalog_context.get('workspace_id') or ''),
                            'environment': str(raw_payload.get('binding_environment') or current_catalog_context.get('environment') or ''),
                            'portfolio_family_id': str(raw_payload.get('binding_portfolio_family_id') or current_catalog_context.get('portfolio_family_id') or ''),
                            'runtime_family_id': str(raw_payload.get('binding_runtime_family_id') or current_catalog_context.get('runtime_family_id') or ''),
                        }
                        binding_scope_key = self._baseline_promotion_simulation_custody_catalog_binding_scope_key(binding_scope, context=binding_context)
                        if binding_scope not in {'global', 'workspace', 'environment', 'portfolio_family', 'runtime_family', 'promotion'} or (binding_scope != 'global' and not binding_scope_key):
                            result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_binding_scope_invalid'}
                        else:
                            new_binding = self._baseline_promotion_simulation_custody_catalog_binding({
                                'binding_id': uuid.uuid4().hex,
                                'binding_scope': binding_scope,
                                'binding_scope_key': binding_scope_key,
                                'catalog_entry_id': str(catalog_pack.get('catalog_entry_id') or ''),
                                'catalog_version_key': str(catalog_pack.get('catalog_version_key') or ''),
                                'catalog_version': int(catalog_pack.get('catalog_version') or 0),
                                'catalog_pack_id': str(catalog_pack.get('pack_id') or ''),
                                'catalog_pack_label': str(catalog_pack.get('pack_label') or ''),
                                'promotion_id': str(binding_context.get('promotion_id') or ''),
                                'workspace_id': str(binding_context.get('workspace_id') or ''),
                                'environment': str(binding_context.get('environment') or ''),
                                'portfolio_family_id': str(binding_context.get('portfolio_family_id') or ''),
                                'runtime_family_id': str(binding_context.get('runtime_family_id') or ''),
                                'bound_at': now,
                                'bound_by': str(actor or 'operator'),
                                'state': 'active',
                                'note': str(raw_payload.get('note') or raw_payload.get('reason') or ''),
                            })
                            updated_bindings = [
                                self._baseline_promotion_simulation_custody_catalog_binding(item)
                                for item in raw_bindings
                                if not (str((item or {}).get('binding_scope') or '') == binding_scope and str((item or {}).get('binding_scope_key') or '') == binding_scope_key and str((item or {}).get('state') or 'active') == 'active')
                            ]
                            updated_bindings.append(new_binding)
                            binding_event = {
                                'event_id': uuid.uuid4().hex,
                                'event_type': 'bound',
                                'binding_id': str(new_binding.get('binding_id') or ''),
                                'binding_scope': binding_scope,
                                'binding_scope_key': binding_scope_key,
                                'catalog_entry_id': str(new_binding.get('catalog_entry_id') or ''),
                                'catalog_version_key': str(new_binding.get('catalog_version_key') or ''),
                                'catalog_version': int(new_binding.get('catalog_version') or 0),
                                'at': now,
                                'by': str(actor or 'operator'),
                                'note': str(raw_payload.get('note') or raw_payload.get('reason') or ''),
                            }
                            raw_binding_events.append(binding_event)
                            all_bindings_effective = [
                                item for item in all_bindings
                                if not (str((item or {}).get('catalog_owner_canvas_id') or '') == canvas_id and str((item or {}).get('catalog_owner_node_id') or '') == node_id and str((item or {}).get('binding_scope') or '') == binding_scope and str((item or {}).get('binding_scope_key') or '') == binding_scope_key)
                            ] + updated_bindings
                            effective_binding = self._baseline_promotion_simulation_custody_effective_catalog_binding(all_bindings_effective, context=current_catalog_context, catalog_packs=all_catalog_packs)
                            target_entry_id = str(catalog_pack.get('catalog_entry_id') or catalog_pack.get('registry_entry_id') or '')
                            raw_registry_packs = [dict(item or {}) for item in list(data.get('routing_policy_pack_registry') or []) if isinstance(item, dict)]
                            updated_registry = []
                            for item in raw_registry_packs:
                                normalized_item = self.openclaw_recovery_scheduler_service._normalize_baseline_promotion_simulation_custody_policy_what_if_pack(item, actor=str((item or {}).get('created_by') or (item or {}).get('promoted_by') or ''), source=str((item or {}).get('source') or 'registry'))
                                if str(normalized_item.get('catalog_entry_id') or normalized_item.get('registry_entry_id') or '') == target_entry_id:
                                    normalized_item['catalog_binding_count'] = int(normalized_item.get('catalog_binding_count') or 0) + 1
                                    normalized_item['catalog_last_bound_at'] = now
                                    normalized_item['catalog_last_bound_by'] = str(actor or 'operator')
                                updated_registry.append(self._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(normalized_item))
                            normalized_updated_registry = self._baseline_promotion_simulation_custody_catalog_enrich_packs(self._baseline_promotion_simulation_custody_apply_catalog_version_flags(self._baseline_promotion_simulation_custody_registry_policy_packs(updated_registry)))
                            updated_registry = [self._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(item) for item in normalized_updated_registry]
                            updated_data = dict(data)
                            updated_data['routing_policy_pack_registry'] = updated_registry
                            updated_data['routing_policy_pack_bindings'] = [self._compact_baseline_promotion_simulation_catalog_binding(item) for item in updated_bindings[-12:]]
                            updated_data['routing_policy_pack_binding_events'] = [self._compact_baseline_promotion_simulation_catalog_binding_event(item) for item in raw_binding_events[-12:]]
                            updated_data['routing_policy_pack_binding_summary'] = self._baseline_promotion_simulation_custody_catalog_binding_summary(all_bindings_effective)
                            updated_data['effective_routing_policy_pack_binding'] = self._compact_baseline_promotion_simulation_catalog_binding(effective_binding)
                            updated_data['last_catalog_binding_routing_policy_pack'] = self._compact_baseline_promotion_simulation_catalog_binding(new_binding)
                            if latest_simulation:
                                export_state = dict(latest_simulation.get('export_state') or {})
                                export_state['last_catalog_binding_routing_policy_pack'] = dict(updated_data['last_catalog_binding_routing_policy_pack'])
                                export_state['effective_routing_policy_pack_binding'] = dict(updated_data['effective_routing_policy_pack_binding'])
                                updated_simulation = dict(latest_simulation)
                                updated_simulation['export_state'] = export_state
                                updated_data['latest_simulation'] = self._baseline_promotion_simulation_state(simulation=updated_simulation, actor=str(updated_simulation.get('simulated_by') or actor or 'operator'), request=dict(updated_simulation.get('request') or {}), review=dict(updated_simulation.get('review') or {}), created_promotions=[dict(item) for item in list(updated_simulation.get('created_promotions') or [])])
                            node = dict((self._replace_node_data(gw, canvas_id=canvas_id, node=node, actor=actor, data=updated_data, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')) or {}).get('node') or node)
                            data = dict(node.get('data') or {})
                            pack_with_binding = dict(catalog_pack)
                            pack_with_binding.update(self._baseline_promotion_simulation_custody_catalog_pack_bindings(pack_with_binding, bindings=all_bindings_effective, effective_binding=effective_binding))
                            result = {'ok': True, 'policy_pack': self._compact_baseline_promotion_simulation_routing_policy_pack(pack_with_binding), 'binding': self._compact_baseline_promotion_simulation_catalog_binding(new_binding), 'effective_binding': dict(data.get('effective_routing_policy_pack_binding') or {}), 'latest_simulation': dict(data.get('latest_simulation') or {})}
                else:
                    binding_id = str(raw_payload.get('binding_id') or '').strip()
                    binding_scope = str(raw_payload.get('binding_scope') or raw_payload.get('adoption_scope') or '').strip()
                    binding_context = {
                        'promotion_id': str(raw_payload.get('binding_promotion_id') or current_catalog_context.get('promotion_id') or ''),
                        'workspace_id': str(raw_payload.get('binding_workspace_id') or current_catalog_context.get('workspace_id') or ''),
                        'environment': str(raw_payload.get('binding_environment') or current_catalog_context.get('environment') or ''),
                        'portfolio_family_id': str(raw_payload.get('binding_portfolio_family_id') or current_catalog_context.get('portfolio_family_id') or ''),
                        'runtime_family_id': str(raw_payload.get('binding_runtime_family_id') or current_catalog_context.get('runtime_family_id') or ''),
                    }
                    binding_scope_key = self._baseline_promotion_simulation_custody_catalog_binding_scope_key(binding_scope, context=binding_context) if binding_scope else ''
                    if not binding_id and not binding_scope:
                        inferred = self._baseline_promotion_simulation_custody_effective_catalog_binding(all_bindings, context=current_catalog_context, catalog_packs=all_catalog_packs)
                        binding_id = str(inferred.get('binding_id') or '')
                        if not binding_id:
                            binding_scope = 'promotion'
                            binding_scope_key = self._baseline_promotion_simulation_custody_catalog_binding_scope_key(binding_scope, context=current_catalog_context)
                    removed = []
                    updated_bindings = []
                    for item in raw_bindings:
                        normalized_binding = self._baseline_promotion_simulation_custody_catalog_binding(item)
                        matches = False
                        if binding_id and str(normalized_binding.get('binding_id') or '') == binding_id:
                            matches = True
                        elif binding_scope and str(normalized_binding.get('binding_scope') or '') == binding_scope and str(normalized_binding.get('binding_scope_key') or '') == binding_scope_key:
                            if not requested_catalog_entry_id or str(normalized_binding.get('catalog_entry_id') or '') == requested_catalog_entry_id:
                                matches = True
                        if matches:
                            removed.append(normalized_binding)
                        else:
                            updated_bindings.append(normalized_binding)
                    if not removed:
                        result = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_binding_missing'}
                    else:
                        for removed_binding in removed:
                            raw_binding_events.append({
                                'event_id': uuid.uuid4().hex,
                                'event_type': 'unbound',
                                'binding_id': str(removed_binding.get('binding_id') or ''),
                                'binding_scope': str(removed_binding.get('binding_scope') or ''),
                                'binding_scope_key': str(removed_binding.get('binding_scope_key') or ''),
                                'catalog_entry_id': str(removed_binding.get('catalog_entry_id') or ''),
                                'catalog_version_key': str(removed_binding.get('catalog_version_key') or ''),
                                'catalog_version': int(removed_binding.get('catalog_version') or 0),
                                'at': now,
                                'by': str(actor or 'operator'),
                                'note': str(raw_payload.get('note') or raw_payload.get('reason') or ''),
                            })
                        all_bindings_effective = [
                            item for item in all_bindings
                            if not (str((item or {}).get('catalog_owner_canvas_id') or '') == canvas_id and str((item or {}).get('catalog_owner_node_id') or '') == node_id)
                        ] + updated_bindings
                        effective_binding = self._baseline_promotion_simulation_custody_effective_catalog_binding(all_bindings_effective, context=current_catalog_context, catalog_packs=all_catalog_packs)
                        updated_data = dict(data)
                        updated_data['routing_policy_pack_bindings'] = [self._compact_baseline_promotion_simulation_catalog_binding(item) for item in updated_bindings[-12:]]
                        updated_data['routing_policy_pack_binding_events'] = [self._compact_baseline_promotion_simulation_catalog_binding_event(item) for item in raw_binding_events[-12:]]
                        updated_data['routing_policy_pack_binding_summary'] = self._baseline_promotion_simulation_custody_catalog_binding_summary(all_bindings_effective)
                        updated_data['effective_routing_policy_pack_binding'] = self._compact_baseline_promotion_simulation_catalog_binding(effective_binding)
                        updated_data['last_catalog_unbound_routing_policy_pack'] = self._compact_baseline_promotion_simulation_catalog_binding(removed[0])
                        if latest_simulation:
                            export_state = dict(latest_simulation.get('export_state') or {})
                            export_state['last_catalog_unbound_routing_policy_pack'] = dict(updated_data['last_catalog_unbound_routing_policy_pack'])
                            export_state['effective_routing_policy_pack_binding'] = dict(updated_data['effective_routing_policy_pack_binding'])
                            updated_simulation = dict(latest_simulation)
                            updated_simulation['export_state'] = export_state
                            updated_data['latest_simulation'] = self._baseline_promotion_simulation_state(simulation=updated_simulation, actor=str(updated_simulation.get('simulated_by') or actor or 'operator'), request=dict(updated_simulation.get('request') or {}), review=dict(updated_simulation.get('review') or {}), created_promotions=[dict(item) for item in list(updated_simulation.get('created_promotions') or [])])
                        node = dict((self._replace_node_data(gw, canvas_id=canvas_id, node=node, actor=actor, data=updated_data, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')) or {}).get('node') or node)
                        data = dict(node.get('data') or {})
                        result = {'ok': True, 'removed_bindings': [self._compact_baseline_promotion_simulation_catalog_binding(item) for item in removed], 'effective_binding': dict(data.get('effective_routing_policy_pack_binding') or {}), 'latest_simulation': dict(data.get('latest_simulation') or {})}

            elif normalized_action in {'simulate_simulation_custody_routing', 'replay_simulation_custody_routing', 'replay_saved_simulation_custody_routing_policy_pack', 'replay_registered_simulation_custody_routing_policy_pack', 'replay_cataloged_simulation_custody_routing_policy_pack', 'replay_organizational_simulation_custody_routing_policy_pack'}:
                promotion_detail = dict((inspected.get('related') or {}).get('baseline_promotion') or {})
                raw_saved_packs = [dict(item or {}) for item in list(data.get('saved_routing_policy_packs') or []) if isinstance(item, dict)]
                raw_registry_packs = [dict(item or {}) for item in list(data.get('routing_policy_pack_registry') or []) if isinstance(item, dict)]
                requested_pack_id = str(raw_payload.get('saved_pack_id') or raw_payload.get('registry_pack_id') or raw_payload.get('catalog_pack_id') or raw_payload.get('policy_pack_id') or raw_payload.get('pack_id') or '').strip()
                requested_catalog_entry_id = str(raw_payload.get('catalog_entry_id') or '').strip()
                requested_organizational_service_entry_id = str(raw_payload.get('organizational_service_entry_id') or raw_payload.get('service_entry_id') or '').strip()
                replay_error = {}
                applied_pack = {}
                if normalized_action == 'replay_cataloged_simulation_custody_routing_policy_pack':
                    applied_pack = self._resolve_baseline_promotion_simulation_custody_catalog_policy_pack(
                        gw,
                        promotion_detail=promotion_detail,
                        node_data=data,
                        tenant_id=scope.get('tenant_id'),
                        workspace_id=scope.get('workspace_id'),
                        environment=scope.get('environment'),
                        pack_id=requested_pack_id or None,
                        catalog_entry_id=requested_catalog_entry_id or None,
                    )
                    if not applied_pack:
                        replay_error = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_missing'}
                    elif str(applied_pack.get('catalog_lifecycle_state') or 'draft') == 'deprecated':
                        replay_error = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_deprecated'}
                    else:
                        rollout_access = self._baseline_promotion_simulation_custody_catalog_rollout_access(applied_pack, current_context={**self._baseline_promotion_simulation_custody_catalog_context(promotion_detail=promotion_detail, node_data=data, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')), 'canvas_id': canvas_id, 'node_id': node_id})
                        if not rollout_access.get('allowed'):
                            replay_error = {'ok': False, 'error': str(rollout_access.get('reason') or 'catalog_rollout_target_not_released')}
                elif normalized_action == 'replay_organizational_simulation_custody_routing_policy_pack':
                    applied_pack = self._resolve_baseline_promotion_simulation_custody_organizational_catalog_service_pack(
                        gw,
                        promotion_detail=promotion_detail,
                        node_data=data,
                        tenant_id=scope.get('tenant_id'),
                        workspace_id=scope.get('workspace_id'),
                        environment=scope.get('environment'),
                        pack_id=requested_pack_id or None,
                        catalog_entry_id=requested_catalog_entry_id or None,
                        organizational_service_entry_id=requested_organizational_service_entry_id or None,
                    )
                    if not applied_pack:
                        replay_error = {'ok': False, 'error': 'baseline_promotion_simulation_custody_organizational_policy_pack_missing'}
                    elif str(applied_pack.get('catalog_lifecycle_state') or 'draft') != 'approved':
                        replay_error = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_not_approved'}
                    elif str(applied_pack.get('catalog_release_state') or 'draft') not in {'released', 'rolling_out'}:
                        replay_error = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_not_released'}
                elif requested_pack_id:
                    applied_pack = self._resolve_baseline_promotion_simulation_custody_policy_pack(promotion_detail=promotion_detail, raw_saved_packs=raw_saved_packs, raw_registry_packs=raw_registry_packs, pack_id=requested_pack_id)
                    if not applied_pack:
                        replay_error = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_missing'}
                elif normalized_action in {'replay_saved_simulation_custody_routing_policy_pack', 'replay_registered_simulation_custody_routing_policy_pack', 'replay_cataloged_simulation_custody_routing_policy_pack', 'replay_organizational_simulation_custody_routing_policy_pack'}:
                    replay_error = {'ok': False, 'error': 'baseline_promotion_simulation_custody_policy_pack_missing'}
                if replay_error:
                    result = replay_error
                else:
                    comparison_policies = [dict(item or {}) for item in list(raw_payload.get('comparison_policies') or []) if isinstance(item, dict)]
                    if applied_pack:
                        comparison_policies = [dict(item or {}) for item in list(applied_pack.get('comparison_policies') or []) if isinstance(item, dict)] + comparison_policies
                    replay_result = self.openclaw_recovery_scheduler_service.simulate_runtime_alert_governance_baseline_promotion_simulation_custody_routing(gw, promotion_id=promotion_id, actor=actor, alert_id=str(raw_payload.get('alert_id') or '').strip() or None, policy_overrides=dict(raw_payload.get('policy_overrides') or {}), comparison_policies=comparison_policies, alert_overrides=dict(raw_payload.get('alert_overrides') or {}), tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'))
                    if not replay_result.get('ok'):
                        result = replay_result
                    else:
                        raw_replay = dict(replay_result.get('routing_replay') or {})
                        if applied_pack:
                            raw_replay['applied_pack'] = self._compact_baseline_promotion_simulation_routing_policy_pack(applied_pack)
                        compact_replay = self._compact_baseline_promotion_simulation_routing_replay(raw_replay)
                        if normalized_action in {'replay_saved_simulation_custody_routing_policy_pack', 'replay_registered_simulation_custody_routing_policy_pack', 'replay_cataloged_simulation_custody_routing_policy_pack', 'replay_organizational_simulation_custody_routing_policy_pack'}:
                            updated_data = dict(data)
                            if normalized_action in {'replay_cataloged_simulation_custody_routing_policy_pack', 'replay_organizational_simulation_custody_routing_policy_pack'} and applied_pack:
                                target_entry_id = str(applied_pack.get('catalog_entry_id') or applied_pack.get('registry_entry_id') or '')
                                updated_registry = []
                                for item in raw_registry_packs:
                                    normalized_item = self.openclaw_recovery_scheduler_service._normalize_baseline_promotion_simulation_custody_policy_what_if_pack(item, actor=str((item or {}).get('created_by') or (item or {}).get('promoted_by') or ''), source=str((item or {}).get('source') or 'registry'))
                                    if str(normalized_item.get('catalog_entry_id') or normalized_item.get('registry_entry_id') or '') == target_entry_id:
                                        normalized_item['catalog_replay_count'] = int(normalized_item.get('catalog_replay_count') or 0) + 1
                                        normalized_item['catalog_last_replayed_at'] = time.time()
                                        normalized_item['catalog_last_replayed_by'] = str(actor or 'operator')
                                        normalized_item['catalog_last_replay_source'] = normalized_action
                                    updated_registry.append(self._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(normalized_item))
                                if updated_registry:
                                    normalized_updated_registry = self._baseline_promotion_simulation_custody_catalog_enrich_packs(self._baseline_promotion_simulation_custody_apply_catalog_version_flags(self._baseline_promotion_simulation_custody_registry_policy_packs(updated_registry)))
                                    updated_registry = [self._compact_baseline_promotion_simulation_routing_policy_pack_for_storage(item) for item in normalized_updated_registry]
                                    updated_data['routing_policy_pack_registry'] = updated_registry
                            if applied_pack:
                                updated_data['last_used_routing_policy_pack'] = {
                                    'catalog_entry_id': str((compact_replay.get('applied_pack') or {}).get('catalog_entry_id') or ''),
                                    'catalog_version': int((compact_replay.get('applied_pack') or {}).get('catalog_version') or 0),
                                    'pack_id': str((compact_replay.get('applied_pack') or {}).get('pack_id') or ''),
                                    'pack_label': str((compact_replay.get('applied_pack') or {}).get('pack_label') or ''),
                                    'usage_source': normalized_action,
                                    'used_at': time.time(),
                                    'used_by': str(actor or 'operator'),
                                }
                                if normalized_action == 'replay_organizational_simulation_custody_routing_policy_pack':
                                    updated_data['last_organizational_catalog_replay_routing_policy_pack'] = {
                                        'catalog_entry_id': str((compact_replay.get('applied_pack') or {}).get('catalog_entry_id') or ''),
                                        'catalog_version': int((compact_replay.get('applied_pack') or {}).get('catalog_version') or 0),
                                        'pack_id': str((compact_replay.get('applied_pack') or {}).get('pack_id') or ''),
                                        'organizational_service_entry_id': str((compact_replay.get('applied_pack') or {}).get('organizational_service_entry_id') or ''),
                                        'usage_source': normalized_action,
                                        'used_at': time.time(),
                                        'used_by': str(actor or 'operator'),
                                    }
                            node = dict((self._replace_node_data(gw, canvas_id=canvas_id, node=node, actor=actor, data=updated_data, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')) or {}).get('node') or node)
                            data = dict(node.get('data') or {})
                            result = {**replay_result, 'latest_simulation': dict(data.get('latest_simulation') or {}), 'routing_replay': compact_replay}
                        else:
                            updated_data = dict(data)
                            updated_data['last_simulation_routing_replay'] = {'alert_id': str(compact_replay.get('alert_id') or ''), 'scenario_count': int(compact_replay.get('scenario_count') or 0), 'applied_pack': dict(compact_replay.get('applied_pack') or {})}
                            if latest_simulation:
                                export_state = dict(latest_simulation.get('export_state') or {})
                                export_state['latest_routing_replay'] = compact_replay
                                updated_simulation = dict(latest_simulation)
                                updated_simulation['export_state'] = export_state
                                updated_data['latest_simulation'] = self._baseline_promotion_simulation_state(simulation=updated_simulation, actor=str(updated_simulation.get('simulated_by') or actor or 'operator'), request=dict(updated_simulation.get('request') or {}), review=dict(updated_simulation.get('review') or {}), created_promotions=[dict(item) for item in list(updated_simulation.get('created_promotions') or [])])
                            node = dict((self._replace_node_data(gw, canvas_id=canvas_id, node=node, actor=actor, data=updated_data, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')) or {}).get('node') or node)
                            data = dict(node.get('data') or {})
                            result = {**replay_result, 'latest_simulation': dict(data.get('latest_simulation') or {}), 'routing_replay': compact_replay}
            elif normalized_action in {'acknowledge_simulation_custody_alert', 'mute_simulation_custody_alert', 'unmute_simulation_custody_alert', 'resolve_simulation_custody_alert', 'claim_simulation_custody_alert', 'assign_simulation_custody_alert', 'release_simulation_custody_alert', 'reroute_simulation_custody_alert', 'handoff_simulation_custody_alert'}:
                lifecycle_action = normalized_action.replace('_simulation_custody_alert', '')
                promotion_detail = dict((inspected.get('related') or {}).get('baseline_promotion') or {})
                alert_items = [dict(item) for item in list((((promotion_detail.get('simulation_custody_monitoring') or {}).get('alerts')) or {}).get('items') or [])]
                active_alert = next((item for item in alert_items if bool(item.get('active'))), {})
                muted_alert = next((item for item in alert_items if str(item.get('status') or '') == 'muted'), {})
                target_alert = muted_alert if lifecycle_action == 'unmute' else active_alert
                lifecycle_result = self.openclaw_recovery_scheduler_service.update_runtime_alert_governance_baseline_promotion_simulation_custody_alert(
                    gw,
                    promotion_id=promotion_id,
                    actor=actor,
                    action=lifecycle_action,
                    alert_id=str(raw_payload.get('alert_id') or target_alert.get('alert_id') or '').strip() or None,
                    reason=str(reason or raw_payload.get('reason') or ''),
                    mute_for_s=(int(raw_payload.get('mute_for_s')) if raw_payload.get('mute_for_s') is not None else None),
                    owner_id=str(raw_payload.get('owner_id') or '').strip() or None,
                    owner_role=str(raw_payload.get('owner_role') or '').strip() or None,
                    queue_id=str(raw_payload.get('queue_id') or '').strip() or None,
                    queue_label=str(raw_payload.get('queue_label') or '').strip() or None,
                    route_id=str(raw_payload.get('route_id') or '').strip() or None,
                    route_label=str(raw_payload.get('route_label') or '').strip() or None,
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                )
                if not lifecycle_result.get('ok'):
                    result = lifecycle_result
                else:
                    export_state = dict(latest_simulation.get('export_state') or {})
                    monitoring = dict(lifecycle_result.get('simulation_custody_monitoring') or {})
                    alert_payload = dict(lifecycle_result.get('alert') or {})
                    export_state['custody_guard'] = self._compact_baseline_promotion_simulation_custody_guard(monitoring.get('guard') or {})
                    export_state['custody_alerts_summary'] = self._compact_baseline_promotion_simulation_custody_alerts_summary(((monitoring.get('alerts') or {}).get('summary')) or {})
                    export_state['custody_active_alert'] = self._compact_baseline_promotion_simulation_custody_active_alert(alert_payload)
                    export_state['last_alert_action'] = self._compact_baseline_promotion_simulation_last_alert_action({
                        'action': lifecycle_action,
                        'alert_id': str(alert_payload.get('alert_id') or ''),
                        'status': str(alert_payload.get('status') or ''),
                        'ownership_status': str((alert_payload.get('ownership') or {}).get('status') or ''),
                        'owner_id': str((alert_payload.get('ownership') or {}).get('owner_id') or ''),
                        'queue_id': str((alert_payload.get('ownership') or {}).get('queue_id') or ((alert_payload.get('routing') or {}).get('queue_id')) or ''),
                        'route_id': str((alert_payload.get('routing') or {}).get('route_id') or ''),
                        'at': time.time(),
                        'by': str(actor or 'operator'),
                    })
                    updated_simulation = dict(latest_simulation)
                    updated_simulation['export_state'] = export_state
                    updated_data = dict(data)
                    updated_data['last_simulation_custody_alert_action'] = dict(export_state.get('last_alert_action') or {})
                    updated_data['latest_simulation'] = self._baseline_promotion_simulation_state(
                        simulation=updated_simulation,
                        actor=str(updated_simulation.get('simulated_by') or actor or 'operator'),
                        request=dict(updated_simulation.get('request') or {}),
                        review=dict(updated_simulation.get('review') or {}),
                        created_promotions=[dict(item) for item in list(updated_simulation.get('created_promotions') or [])],
                    )
                    node = dict((self._replace_node_data(
                        gw,
                        canvas_id=canvas_id,
                        node=node,
                        actor=actor,
                        data=updated_data,
                        tenant_id=scope.get('tenant_id'),
                        workspace_id=scope.get('workspace_id'),
                        environment=scope.get('environment'),
                    ) or {}).get('node') or node)
                    data = dict(node.get('data') or {})
                    result = {**lifecycle_result, 'latest_simulation': dict(data.get('latest_simulation') or {})}
            elif normalized_action in {'create_rollout', 'create_and_approve_rollout'}:
                create_result = self.openclaw_recovery_scheduler_service.create_runtime_alert_governance_baseline_promotion_from_simulation(
                    gw,
                    simulation=latest_simulation,
                    actor=actor,
                    reason=str(reason or raw_payload.get('reason') or ''),
                    auto_approve=normalized_action == 'create_and_approve_rollout',
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                )
                if not create_result.get('ok'):
                    result = create_result
                else:
                    created_release = dict(create_result.get('release') or {})
                    created_promotion_id = str(created_release.get('release_id') or create_result.get('promotion_id') or '').strip()
                    created_node = {}
                    created_edge = {}
                    if bool(raw_payload.get('create_canvas_node', True)) and created_promotion_id:
                        created_label = str(raw_payload.get('label') or f'Baseline promotion {created_promotion_id[:8]}').strip() or f'Baseline promotion {created_promotion_id[:8]}'
                        created_node_payload = self.upsert_node(
                            gw,
                            canvas_id=canvas_id,
                            actor=actor,
                            node_type='baseline_promotion',
                            label=created_label,
                            position_x=float(node.get('position_x') or 0.0) + 320.0,
                            position_y=float(node.get('position_y') or 0.0),
                            width=float(node.get('width') or 240.0),
                            height=float(node.get('height') or 120.0),
                            data={
                                'promotion_id': created_promotion_id,
                                'created_from_simulation': {
                                    'source_node_id': str(node.get('node_id') or ''),
                                    'source_promotion_id': promotion_id,
                                    'simulation_id': str(latest_simulation.get('simulation_id') or ''),
                                },
                            },
                            tenant_id=scope.get('tenant_id'),
                            workspace_id=scope.get('workspace_id'),
                            environment=scope.get('environment'),
                        )
                        created_node = dict(created_node_payload.get('node') or {})
                        if created_node:
                            created_edge = dict((self.upsert_edge(
                                gw,
                                canvas_id=canvas_id,
                                actor=actor,
                                source_node_id=str(node.get('node_id') or ''),
                                target_node_id=str(created_node.get('node_id') or ''),
                                label='derived_from_simulation',
                                edge_type='derived_from_simulation',
                                data={
                                    'simulation_id': str(latest_simulation.get('simulation_id') or ''),
                                    'created_promotion_id': created_promotion_id,
                                    'diverged': bool((((create_result.get('created_from_simulation') or {}).get('comparison') or {}).get('diverged'))),
                                },
                                tenant_id=scope.get('tenant_id'),
                                workspace_id=scope.get('workspace_id'),
                                environment=scope.get('environment'),
                            ) or {}).get('edge') or {})
                    created_promotions = [dict(item) for item in list(latest_simulation.get('created_promotions') or [])]
                    created_promotions.append({
                        'promotion_id': created_promotion_id,
                        'status': str(created_release.get('status') or ''),
                        'created_at': time.time(),
                        'created_by': str(actor or 'operator'),
                        'auto_approved': normalized_action == 'create_and_approve_rollout',
                        'simulation_id': str(latest_simulation.get('simulation_id') or ''),
                        'created_node_id': str(created_node.get('node_id') or ''),
                        'diverged': bool((((create_result.get('created_from_simulation') or {}).get('comparison') or {}).get('diverged'))),
                        'divergence_count': len(list((((create_result.get('created_from_simulation') or {}).get('comparison') or {}).get('items') or []))),
                    })
                    updated_state = self._baseline_promotion_simulation_state(
                        simulation=latest_simulation,
                        actor=str(latest_simulation.get('simulated_by') or actor or 'operator'),
                        request=dict(latest_simulation.get('request') or {}),
                        review=dict(latest_simulation.get('review') or {}),
                        created_promotions=created_promotions,
                    )
                    updated_data = dict(data)
                    updated_data['latest_simulation'] = updated_state
                    updated_data['last_created_promotion'] = {
                        'promotion_id': created_promotion_id,
                        'status': str(created_release.get('status') or ''),
                        'created_node_id': str(created_node.get('node_id') or ''),
                        'simulation_id': str(latest_simulation.get('simulation_id') or ''),
                        'diverged': bool((((create_result.get('created_from_simulation') or {}).get('comparison') or {}).get('diverged'))),
                    }
                    node = dict((self._replace_node_data(
                        gw,
                        canvas_id=canvas_id,
                        node=node,
                        actor=actor,
                        data=updated_data,
                        tenant_id=scope.get('tenant_id'),
                        workspace_id=scope.get('workspace_id'),
                        environment=scope.get('environment'),
                    ) or {}).get('node') or node)
                    data = dict(node.get('data') or {})
                    create_result['created_node'] = created_node
                    create_result['created_edge'] = created_edge
                    create_result['canvas_simulation'] = updated_state
                    result = create_result
            elif normalized_action == 'export_attestation':
                result = self.openclaw_recovery_scheduler_service.export_runtime_alert_governance_baseline_promotion_attestation(
                    gw,
                    promotion_id=promotion_id,
                    actor=actor,
                    timeline_limit=int(raw_payload.get('timeline_limit')) if raw_payload.get('timeline_limit') is not None else None,
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                )
            elif normalized_action == 'export_postmortem':
                result = self.openclaw_recovery_scheduler_service.export_runtime_alert_governance_baseline_promotion_postmortem(
                    gw,
                    promotion_id=promotion_id,
                    actor=actor,
                    timeline_limit=int(raw_payload.get('timeline_limit')) if raw_payload.get('timeline_limit') is not None else None,
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                )
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

