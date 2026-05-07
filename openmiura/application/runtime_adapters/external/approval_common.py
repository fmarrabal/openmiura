from __future__ import annotations

from typing import Any


class OpenClawApprovalCommonMixin:
    @staticmethod
    def _approval_scope(*, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any]:
        return {
            'tenant_id': tenant_id,
            'workspace_id': workspace_id,
            'environment': environment,
        }

    def _ensure_step_approval_request(
        self,
        gw,
        *,
        workflow_id: str,
        step_id: str,
        requested_role: str,
        requested_by: str,
        payload: dict[str, Any] | None = None,
        expires_at: float | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        enrich: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        scope = self._approval_scope(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        approval = gw.audit.get_pending_approval_for_step(
            workflow_id,
            step_id,
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        )
        if approval is None:
            create_kwargs: dict[str, Any] = {
                'workflow_id': str(workflow_id or '').strip(),
                'step_id': str(step_id or '').strip(),
                'requested_role': str(requested_role or '').strip(),
                'requested_by': str(requested_by or '').strip(),
                'payload': dict(payload or {}),
                'tenant_id': scope.get('tenant_id'),
                'workspace_id': scope.get('workspace_id'),
                'environment': scope.get('environment'),
            }
            if expires_at is not None:
                create_kwargs['expires_at'] = expires_at
            approval = gw.audit.create_approval(**create_kwargs)
        result = dict(approval or {})
        for key, value in dict(enrich or {}).items():
            if value is not None:
                result[key] = value
        return result

    def _list_workflow_approvals(
        self,
        gw,
        *,
        workflow_id: str,
        limit: int = 100,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> list[dict[str, Any]]:
        return gw.audit.list_approvals(
            limit=max(1, int(limit or 1)),
            workflow_id=str(workflow_id or '').strip(),
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
