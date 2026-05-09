"""openmiura.application.canvas.service._timeline_mixin

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


class _LiveCanvasTimelineMixin:
    """Mixin: timeline methods on LiveCanvasService."""

    def get_node_timeline(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        node_id: str,
        limit: int = 50,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        detail = self.get_document(gw, canvas_id=canvas_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if not detail.get('ok'):
            return detail
        scope = dict(detail.get('scope') or {})
        nodes = list(detail.get('nodes') or [])
        node = next((item for item in nodes if str(item.get('node_id') or '') == str(node_id or '')), None)
        if node is None:
            return {'ok': False, 'reason': 'node_not_found', 'canvas_id': canvas_id, 'node_id': node_id, 'scope': scope}
        refs = self._collect_refs(nodes, selected_node_id=node_id)
        node_type = str(node.get('node_type') or '').strip().lower()
        items: list[dict[str, Any]] = []
        if node_type == 'workflow':
            workflow_id = str(((node.get('data') or {}).get('workflow_id')) or (refs.get('workflow_ids') or [''])[0] or '').strip()
            timeline = self.operator_console_service.workflow_service.unified_timeline(
                gw, workflow_id=workflow_id or None, limit=limit, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')
            )
            for event in list(timeline.get('items') or []):
                payload = dict(event.get('payload') or {})
                items.append({'kind': 'event', 'ts': float(event.get('ts') or 0.0), 'label': str(payload.get('event') or payload.get('action') or 'workflow_event'), 'status': str(payload.get('status') or ''), 'event': event})
        elif node_type == 'approval':
            approval_id = str(((node.get('data') or {}).get('approval_id')) or (refs.get('approval_ids') or [''])[0] or '').strip()
            timeline = self.operator_console_service.workflow_service.unified_timeline(
                gw, approval_id=approval_id or None, limit=limit, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')
            )
            for event in list(timeline.get('items') or []):
                payload = dict(event.get('payload') or {})
                items.append({'kind': 'event', 'ts': float(event.get('ts') or 0.0), 'label': str(payload.get('event') or payload.get('action') or 'approval_event'), 'status': str(payload.get('status') or ''), 'event': event})
        elif node_type in {'runtime', 'openclaw_runtime'}:
            runtime_id = str(((node.get('data') or {}).get('runtime_id')) or '').strip()
            events = self._safe_call(gw.audit, 'list_events_filtered', [], limit=max(limit * 5, 100), channels=['broker'], tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'))
            for event in list(events or []):
                payload = dict(event.get('payload') or {})
                if str(payload.get('runtime_id') or '') != runtime_id:
                    continue
                items.append({'kind': 'event', 'ts': float(event.get('ts') or 0.0), 'label': str(payload.get('action') or payload.get('event') or 'runtime_event'), 'status': str(payload.get('status') or payload.get('health_status') or ''), 'event': event})
            dispatches = self._safe_call(gw.audit, 'list_openclaw_dispatches', [], runtime_id=runtime_id, limit=limit, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'))
            concurrency = self.openclaw_recovery_scheduler_service.get_runtime_concurrency(
                gw, runtime_id=runtime_id, limit=limit, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')
            )
            alerts = self.openclaw_recovery_scheduler_service.evaluate_runtime_alerts(
                gw, runtime_id=runtime_id, limit=limit, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')
            )
            alert_states = self.openclaw_recovery_scheduler_service.list_runtime_alert_states(
                gw, runtime_id=runtime_id, limit=limit, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')
            )
            alert_approvals = self.openclaw_recovery_scheduler_service.list_alert_escalation_approvals(
                gw, runtime_id=runtime_id, limit=limit, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')
            )
            for lease in list((concurrency.get('leases') or [])):
                items.append({'kind': 'lease', 'ts': float(lease.get('updated_at') or lease.get('created_at') or 0.0), 'label': str(lease.get('lease_type') or 'lease'), 'status': 'active' if bool(lease.get('active')) else 'expired', 'lease': lease})
            for record in list((concurrency.get('idempotency_records') or [])):
                items.append({'kind': 'idempotency', 'ts': float(record.get('updated_at') or record.get('created_at') or 0.0), 'label': 'due_slot', 'status': str(record.get('status') or ''), 'idempotency_record': record})
            for alert in list((alerts.get('items') or [])):
                items.append({'kind': 'alert', 'ts': float(alert.get('observed_at') or 0.0), 'label': str(alert.get('title') or alert.get('code') or 'alert'), 'status': str(alert.get('severity') or ''), 'alert': alert})
            governance = self.openclaw_recovery_scheduler_service.get_runtime_alert_governance(
                gw, runtime_id=runtime_id, limit=limit, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')
            )
            if bool((governance.get('current') or {}).get('quiet_hours_active')) or bool((governance.get('current') or {}).get('maintenance_active')) or bool((governance.get('current') or {}).get('storm_active')):
                items.append({'kind': 'alert_governance', 'ts': time.time(), 'label': 'alert_governance', 'status': 'active', 'alert_governance': governance})
            versions = self.openclaw_recovery_scheduler_service.list_runtime_alert_governance_versions(
                gw, runtime_id=runtime_id, limit=max(5, min(limit, 20)), tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'),
            )
            if int((versions.get('summary') or {}).get('count') or 0) > 0:
                items.append({'kind': 'alert_governance_version', 'ts': time.time(), 'label': 'alert_governance_version', 'status': 'active' if (versions.get('current_version') or {}).get('version_id') else 'history', 'versions': versions})
            alert_dispatches = self.openclaw_recovery_scheduler_service.list_runtime_alert_notification_dispatches(
                gw, runtime_id=runtime_id, limit=limit, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')
            )
            alert_delivery_jobs = self.openclaw_recovery_scheduler_service.list_alert_delivery_jobs(
                gw, runtime_id=runtime_id, limit=limit, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')
            )
            for alert_state in list((alert_states.get('items') or [])):
                items.append({'kind': 'alert_workflow', 'ts': float(alert_state.get('updated_at') or alert_state.get('observed_at') or 0.0), 'label': str(alert_state.get('alert_code') or 'alert_workflow'), 'status': str(alert_state.get('workflow_status') or ''), 'alert_state': alert_state})
            for approval in list((alert_approvals.get('items') or [])):
                items.append({'kind': 'alert_approval', 'ts': float(approval.get('updated_at') or approval.get('created_at') or 0.0), 'label': str(approval.get('alert_code') or 'alert_approval'), 'status': str(approval.get('status') or ''), 'alert_approval': approval})
            for alert_dispatch in list((alert_dispatches.get('items') or [])):
                items.append({'kind': 'alert_dispatch', 'ts': float(alert_dispatch.get('updated_at') or alert_dispatch.get('created_at') or 0.0), 'label': str(alert_dispatch.get('target_id') or 'alert_dispatch'), 'status': str(alert_dispatch.get('delivery_status') or ''), 'alert_dispatch': alert_dispatch})
            for alert_job in list((alert_delivery_jobs.get('items') or [])):
                items.append({'kind': 'alert_delivery_job', 'ts': float(alert_job.get('next_run_at') or alert_job.get('created_at') or 0.0), 'label': str(((alert_job.get('target') or {}).get('target_id')) or 'alert_delivery_job'), 'status': 'due' if bool(alert_job.get('is_due')) else 'scheduled', 'alert_delivery_job': alert_job})
            for dispatch in list(dispatches or []):
                enriched_dispatch = self.openclaw_adapter_service._canonical_dispatch_view(dispatch) or dict(dispatch)
                items.append({
                    'kind': 'dispatch',
                    'ts': float(dispatch.get('created_at') or 0.0),
                    'label': str(dispatch.get('action') or 'dispatch'),
                    'status': str(dispatch.get('status') or ''),
                    'canonical_status': str(enriched_dispatch.get('canonical_status') or ''),
                    'terminal': bool(enriched_dispatch.get('terminal')),
                    'dispatch': enriched_dispatch,
                })
        elif node_type in {'baseline_promotion', 'policy_baseline_promotion'}:
            promotion_id = str(((node.get('data') or {}).get('promotion_id')) or node.get('label') or '').strip()
            if promotion_id:
                timeline = self.openclaw_recovery_scheduler_service.get_runtime_alert_governance_baseline_promotion_timeline(
                    gw,
                    promotion_id=promotion_id,
                    limit=limit,
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                )
                for event in list(timeline.get('timeline') or []):
                    items.append({
                        'kind': str(event.get('kind') or 'baseline_promotion_event'),
                        'ts': float(event.get('ts') or 0.0),
                        'label': str(event.get('label') or 'baseline_promotion_event'),
                        'status': str(event.get('status') or event.get('trigger') or ''),
                        'baseline_promotion_event': event,
                    })
                canvas_events = self._safe_call(
                    gw.audit,
                    'list_events_filtered',
                    [],
                    limit=max(limit * 5, 50),
                    channels=['canvas'],
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                )
                for event in list(canvas_events or []):
                    payload = dict(event.get('payload') or {})
                    if str(payload.get('node_id') or '') != str(node_id or ''):
                        continue
                    if str(payload.get('action') or '') not in {'canvas_node_action_executed', 'canvas_node_action_confirmation_required'}:
                        continue
                    operator_action = str(payload.get('operator_action') or '').strip()
                    if not operator_action:
                        continue
                    items.append({
                        'kind': 'canvas_action',
                        'ts': float(event.get('ts') or 0.0),
                        'label': f'canvas_{operator_action}',
                        'status': str(payload.get('reason') or ''),
                        'canvas_event': event,
                    })
        items.sort(key=lambda item: float(item.get('ts') or 0.0))
        return {'ok': True, 'canvas_id': canvas_id, 'node_id': node_id, 'items': items[-limit:], 'scope': scope}

