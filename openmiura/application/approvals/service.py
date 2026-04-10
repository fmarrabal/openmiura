from __future__ import annotations

import time
from typing import Any

from openmiura.application.auth.service import AuthService
from openmiura.application.workflows.service import WorkflowService


class ApprovalService:
    def __init__(self, *, workflow_service: WorkflowService | None = None) -> None:
        self.workflow_service = workflow_service or WorkflowService()

    def _normalize_actor(self, actor: str | None) -> str:
        return str(actor or 'system')

    def _publish(self, gw, event_type: str, **payload: Any) -> None:
        bus = getattr(gw, 'realtime_bus', None)
        if bus is None:
            return
        try:
            bus.publish(event_type, **payload)
        except Exception:
            pass

    def _workflow_scope(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            'tenant_id': item.get('tenant_id'),
            'workspace_id': item.get('workspace_id'),
            'environment': item.get('environment'),
        }

    def _log_workflow_event(self, gw, item: dict[str, Any], actor: str, payload: dict[str, Any]) -> None:
        workflow_id = str(item.get('workflow_id') or '').strip()
        if not workflow_id:
            return
        scope = self._workflow_scope(item)
        gw.audit.log_event(
            direction='workflow',
            channel='workflow',
            user_id=str(actor or 'system'),
            session_id=f'workflow:{workflow_id}',
            payload=payload,
            **scope,
        )

    def _effective_auth_ctx(self, gw, auth_ctx: dict[str, Any] | None, item: dict[str, Any], actor_key: str | None = None) -> dict[str, Any]:
        ctx = dict(auth_ctx or {})
        actor = str(actor_key or '').strip()
        if not ctx and actor and ':' in actor:
            candidate_role = actor.split(':', 1)[0].strip().lower()
            if candidate_role in {'viewer', 'user', 'auditor', 'operator', 'workspace_admin', 'tenant_admin', 'admin', 'approver'}:
                normalized_role = 'operator' if candidate_role == 'approver' else candidate_role
                ctx = {
                    'role': normalized_role,
                    'base_role': normalized_role,
                    'permissions': AuthService.permissions_for_role(normalized_role),
                }
        ctx.setdefault('tenant_id', item.get('tenant_id'))
        ctx.setdefault('workspace_id', item.get('workspace_id'))
        ctx.setdefault('environment', item.get('environment'))
        return AuthService.finalize_scope_access(gw, ctx) if ctx else {}

    def _enforce_actor_can_handle(self, gw, item: dict[str, Any], actor_key: str, auth_ctx: dict[str, Any] | None) -> dict[str, Any]:
        ctx = self._effective_auth_ctx(gw, auth_ctx, item, actor_key)
        requested_role = str(item.get('requested_role') or '').strip().lower() or None
        if requested_role and not AuthService.role_satisfies(gw, ctx, requested_role):
            raise PermissionError(f"Approval requires role '{requested_role}'")
        requested_by = str(item.get('requested_by') or '').strip()
        if requested_by and requested_by == actor_key and not AuthService.is_admin(ctx):
            raise PermissionError('Requester cannot approve or claim their own approval')
        return ctx

    def _approval_evidence(self, gw, item: dict[str, Any]) -> dict[str, Any]:
        scope = self._workflow_scope(item)
        approval_id = str(item.get('approval_id') or '')
        workflow_id = str(item.get('workflow_id') or '')
        timeline_payload = self.workflow_service.unified_timeline(
            gw,
            limit=200,
            approval_id=approval_id,
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        )
        timeline = list(timeline_payload.get('items') or [])
        event_names = [
            str((entry.get('payload') or {}).get('event') or '')
            for entry in timeline
            if (entry.get('payload') or {}).get('event') is not None
        ]
        if 'approval_requested' not in event_names and 'waiting_for_approval' in event_names:
            event_names = ['approval_requested' if name == 'waiting_for_approval' else name for name in event_names]
        workflow = gw.audit.get_workflow(
            workflow_id,
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        ) if workflow_id else None
        return {
            'approval_id': approval_id,
            'workflow_id': workflow_id or None,
            'scope': scope,
            'status': item.get('status'),
            'requested_role': item.get('requested_role'),
            'requested_by': item.get('requested_by'),
            'assigned_to': item.get('assigned_to'),
            'decided_by': item.get('decided_by'),
            'created_at': item.get('created_at'),
            'claimed_at': item.get('claimed_at'),
            'decided_at': item.get('decided_at'),
            'expires_at': item.get('expires_at'),
            'reason': item.get('reason'),
            'timeline_count': len(timeline),
            'timeline_events': event_names,
            'workflow_status': (workflow or {}).get('status') if workflow else None,
            'workflow_waiting_for_approval': (workflow or {}).get('waiting_for_approval') if workflow else None,
        }

    def _expire_pending(self, gw, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> None:
        now = time.time()
        for item in gw.audit.list_approvals(limit=500, status='pending', tenant_id=tenant_id, workspace_id=workspace_id, environment=environment):
            expires_at = item.get('expires_at')
            if expires_at is None:
                continue
            if float(expires_at) <= now:
                updated = gw.audit.decide_approval(
                    item['approval_id'],
                    decision='expire',
                    decided_by='system',
                    reason='approval_expired',
                    tenant_id=item.get('tenant_id'),
                    workspace_id=item.get('workspace_id'),
                    environment=item.get('environment'),
                )
                if updated is not None:
                    self._log_workflow_event(gw, item, 'system', {'event': 'approval_expired', 'approval_id': item['approval_id'], 'step_id': item.get('step_id')})
                    self._publish(
                        gw,
                        'approval_expired',
                        topic='workflow',
                        workflow_id=item.get('workflow_id'),
                        approval_id=item['approval_id'],
                        step_id=item.get('step_id'),
                        requested_role=item.get('requested_role'),
                        entity_kind='approval',
                        entity_id=item['approval_id'],
                        **self._workflow_scope(item),
                    )
                    self.workflow_service.reject_workflow(
                        gw,
                        str(item.get('workflow_id') or ''),
                        actor='system',
                        reason='approval_expired',
                        tenant_id=item.get('tenant_id'),
                        workspace_id=item.get('workspace_id'),
                        environment=item.get('environment'),
                    )

    def _refresh_approval(self, gw, approval_id: str, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any] | None:
        self._expire_pending(gw, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        return gw.audit.get_approval(approval_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def get_approval(self, gw, approval_id: str, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any] | None:
        return self._refresh_approval(gw, approval_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def get_evidence(self, gw, approval_id: str, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any] | None:
        item = self.get_approval(gw, approval_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if item is None:
            return None
        return {
            'ok': True,
            'approval': item,
            'evidence': self._approval_evidence(gw, item),
            'timeline': self.workflow_service.unified_timeline(
                gw,
                limit=200,
                approval_id=approval_id,
                tenant_id=item.get('tenant_id'),
                workspace_id=item.get('workspace_id'),
                environment=item.get('environment'),
            ).get('items', []),
        }

    def list_approvals(
        self,
        gw,
        *,
        limit: int = 100,
        status: str | None = None,
        workflow_id: str | None = None,
        requested_role: str | None = None,
        requested_by: str | None = None,
        assignee: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        self._expire_pending(gw, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        items = gw.audit.list_approvals(
            limit=limit,
            status=status,
            workflow_id=workflow_id,
            requested_role=requested_role,
            requested_by=requested_by,
            assignee=assignee,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        return {'ok': True, 'items': items}

    def claim(self, gw, approval_id: str, *, actor: str, auth_ctx: dict[str, Any] | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any]:
        actor_key = self._normalize_actor(actor)
        item = self._refresh_approval(gw, approval_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if item is None:
            raise LookupError('Unknown approval')
        if item.get('status') != 'pending':
            return item
        effective_ctx = self._enforce_actor_can_handle(gw, item, actor_key, auth_ctx)
        assigned_to = str(item.get('assigned_to') or '').strip()
        if assigned_to and assigned_to != actor_key:
            raise ValueError('Approval already claimed by another actor')
        updated = gw.audit.update_approval_assignment(
            approval_id,
            assigned_to=actor_key,
            claimed_at=time.time(),
            tenant_id=item.get('tenant_id'),
            workspace_id=item.get('workspace_id'),
            environment=item.get('environment'),
        )
        refreshed = self._refresh_approval(gw, approval_id, tenant_id=item.get('tenant_id'), workspace_id=item.get('workspace_id'), environment=item.get('environment')) or item | {'updated': updated}
        self._log_workflow_event(
            gw,
            refreshed,
            actor_key,
            {
                'event': 'approval_claimed',
                'approval_id': approval_id,
                'step_id': refreshed.get('step_id'),
                'assigned_to': actor_key,
                'actor_role': effective_ctx.get('role'),
            },
        )
        self._publish(
            gw,
            'approval_claimed',
            topic='workflow',
            workflow_id=refreshed.get('workflow_id'),
            approval_id=approval_id,
            step_id=refreshed.get('step_id'),
            assigned_to=actor_key,
            requested_role=refreshed.get('requested_role'),
            actor_role=effective_ctx.get('role'),
            entity_kind='approval',
            entity_id=approval_id,
            **self._workflow_scope(refreshed),
        )
        return refreshed

    def decide(self, gw, approval_id: str, *, actor: str, decision: str, reason: str = '', auth_ctx: dict[str, Any] | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any]:
        actor_key = self._normalize_actor(actor)
        item = self._refresh_approval(gw, approval_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if item is None:
            raise LookupError('Unknown approval')
        if item.get('status') != 'pending':
            return item
        effective_ctx = self._enforce_actor_can_handle(gw, item, actor_key, auth_ctx)
        assigned_to = str(item.get('assigned_to') or '').strip()
        if assigned_to and assigned_to != actor_key:
            raise ValueError('Approval already claimed by another actor')
        updated = gw.audit.decide_approval(approval_id, decision=decision, decided_by=actor_key, reason=reason, tenant_id=item.get('tenant_id'), workspace_id=item.get('workspace_id'), environment=item.get('environment'))
        if updated is None:
            raise LookupError('Unknown approval')
        refreshed = self._refresh_approval(gw, approval_id, tenant_id=item.get('tenant_id'), workspace_id=item.get('workspace_id'), environment=item.get('environment')) or updated
        normalized_decision = str(decision).strip().lower()
        self._log_workflow_event(
            gw,
            refreshed,
            actor_key,
            {
                'event': 'approval_decided',
                'approval_id': approval_id,
                'step_id': refreshed.get('step_id'),
                'decision': normalized_decision,
                'reason': reason,
                'actor_role': effective_ctx.get('role'),
                'requested_role': refreshed.get('requested_role'),
            },
        )
        self._publish(
            gw,
            'approval_decided',
            topic='workflow',
            workflow_id=refreshed.get('workflow_id'),
            approval_id=approval_id,
            step_id=refreshed.get('step_id'),
            decision=normalized_decision,
            requested_role=refreshed.get('requested_role'),
            actor_role=effective_ctx.get('role'),
            reason=reason,
            entity_kind='approval',
            entity_id=approval_id,
            **self._workflow_scope(refreshed),
        )
        if normalized_decision in {'approve', 'approved'}:
            self.workflow_service.run_workflow(
                gw,
                str(item.get('workflow_id') or ''),
                actor=actor_key,
                tenant_id=item.get('tenant_id'),
                workspace_id=item.get('workspace_id'),
                environment=item.get('environment'),
            )
        else:
            self.workflow_service.reject_workflow(
                gw,
                str(item.get('workflow_id') or ''),
                actor=actor_key,
                reason=reason or 'approval_rejected',
                tenant_id=item.get('tenant_id'),
                workspace_id=item.get('workspace_id'),
                environment=item.get('environment'),
            )
        return gw.audit.get_approval(approval_id, tenant_id=item.get('tenant_id'), workspace_id=item.get('workspace_id'), environment=item.get('environment')) or refreshed
