"""admin/_operator.py - broker admin sub-routes for the operator domain."""
from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from openmiura.application.admin import AdminService
from openmiura.application.auth.service import AuthService
from openmiura.application.tenancy.service import TenancyService
from openmiura.interfaces.broker.common import (
    audit_sensitive,
    metrics_summary,
    require_csrf,
    require_permission,
)




def register_routes(router, tenancy_service) -> None:
    """Attach the operator broker admin endpoints to *router*."""
    @router.get("/admin/traces")
    def broker_admin_decision_traces(
        request: Request,
        limit: int = Query(default=50, ge=1, le=200),
        session_id: str | None = Query(default=None),
        user_key: str | None = Query(default=None),
        agent_id: str | None = Query(default=None),
        channel: str | None = Query(default=None),
        status: str | None = Query(default=None),
        tenant_id: str | None = Query(default=None),
        workspace_id: str | None = Query(default=None),
        environment: str | None = Query(default=None),
    ):
        gw, auth_ctx = require_permission(request, "admin.read")
        target_scope = {
            "tenant_id": tenant_id or auth_ctx.get("tenant_id"),
            "workspace_id": workspace_id or auth_ctx.get("workspace_id"),
            "environment": environment or auth_ctx.get("environment"),
        }
        response = AdminService().list_decision_traces(
            gw,
            limit=limit,
            session_id=session_id,
            user_key=user_key,
            agent_id=agent_id,
            channel=channel,
            status=status,
            **target_scope,
        )
        audit_sensitive(gw, action="admin_decision_traces", auth_ctx=auth_ctx, status="ok", details={"count": len(response.get("items", []))})
        return response

    @router.get("/admin/traces/{trace_id}")
    def broker_admin_decision_trace_detail(trace_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.read")
        response = AdminService().get_decision_trace(gw, trace_id=trace_id)
        audit_sensitive(gw, action="admin_decision_trace_detail", auth_ctx=auth_ctx, status="ok", target=trace_id)
        return response

    @router.get("/admin/operator/overview")
    def broker_admin_operator_overview(
        request: Request,
        limit: int = Query(default=20, ge=1, le=100),
        tenant_id: str | None = Query(default=None),
        workspace_id: str | None = Query(default=None),
        environment: str | None = Query(default=None),
        q: str | None = Query(default=None),
        status: str | None = Query(default=None),
        kind: str | None = Query(default=None),
        only_failures: bool = Query(default=False),
    ):
        gw, auth_ctx = require_permission(request, "admin.read")
        target_scope = {
            "tenant_id": tenant_id or auth_ctx.get("tenant_id"),
            "workspace_id": workspace_id or auth_ctx.get("workspace_id"),
            "environment": environment or auth_ctx.get("environment"),
        }
        response = AdminService().operator_console_overview(gw, limit=limit, q=q, status=status, kind=kind, only_failures=only_failures, **target_scope)
        audit_sensitive(gw, action="admin_operator_console_overview", auth_ctx=auth_ctx, status="ok" if response.get("ok") else "error", details={"limit": limit, "kind": kind, "status": status, "only_failures": only_failures})
        return response

    @router.get("/admin/operator/sessions/{session_id}")
    def broker_admin_operator_session(
        session_id: str,
        request: Request,
        limit: int = Query(default=200, ge=1, le=500),
        tenant_id: str | None = Query(default=None),
        workspace_id: str | None = Query(default=None),
        environment: str | None = Query(default=None),
        q: str | None = Query(default=None),
        status: str | None = Query(default=None),
        kind: str | None = Query(default=None),
        only_failures: bool = Query(default=False),
    ):
        gw, auth_ctx = require_permission(request, "admin.read")
        target_scope = {
            "tenant_id": tenant_id or auth_ctx.get("tenant_id"),
            "workspace_id": workspace_id or auth_ctx.get("workspace_id"),
            "environment": environment or auth_ctx.get("environment"),
        }
        response = AdminService().operator_console_session(gw, session_id=session_id, limit=limit, q=q, status=status, kind=kind, only_failures=only_failures, **target_scope)
        audit_sensitive(gw, action="admin_operator_console_session", auth_ctx=auth_ctx, status="ok" if response.get("ok") else "error", target=session_id, details={"timeline_count": len(response.get("timeline", [])), "kind": kind, "status": status})
        return response

    @router.get("/admin/operator/workflows/{workflow_id}")
    def broker_admin_operator_workflow(
        workflow_id: str,
        request: Request,
        limit: int = Query(default=200, ge=1, le=500),
        tenant_id: str | None = Query(default=None),
        workspace_id: str | None = Query(default=None),
        environment: str | None = Query(default=None),
        q: str | None = Query(default=None),
        status: str | None = Query(default=None),
        kind: str | None = Query(default=None),
        only_failures: bool = Query(default=False),
    ):
        gw, auth_ctx = require_permission(request, "admin.read")
        target_scope = {
            "tenant_id": tenant_id or auth_ctx.get("tenant_id"),
            "workspace_id": workspace_id or auth_ctx.get("workspace_id"),
            "environment": environment or auth_ctx.get("environment"),
        }
        response = AdminService().operator_console_workflow(gw, workflow_id=workflow_id, limit=limit, q=q, status=status, kind=kind, only_failures=only_failures, **target_scope)
        audit_sensitive(gw, action="admin_operator_console_workflow", auth_ctx=auth_ctx, status="ok" if response.get("ok") else "error", target=workflow_id, details={"timeline_count": len(response.get("timeline", [])), "kind": kind, "status": status})
        return response

    @router.post("/admin/operator/workflows/{workflow_id}/actions/{action}")
    async def broker_admin_operator_workflow_action(
        workflow_id: str,
        action: str,
        request: Request,
        tenant_id: str | None = Query(default=None),
        workspace_id: str | None = Query(default=None),
        environment: str | None = Query(default=None),
    ):
        gw, auth_ctx = require_permission(request, "admin.write")
        payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
        target_scope = {
            "tenant_id": tenant_id or auth_ctx.get("tenant_id"),
            "workspace_id": workspace_id or auth_ctx.get("workspace_id"),
            "environment": environment or auth_ctx.get("environment"),
        }
        actor = str(payload.get('actor') or auth_ctx.get('user_key') or auth_ctx.get('username') or 'system')
        try:
            response = AdminService().operator_console_workflow_action(gw, workflow_id=workflow_id, action=action, actor=actor, reason=str(payload.get('reason') or ''), **target_scope)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit_sensitive(gw, action='admin_operator_console_workflow_action', auth_ctx=auth_ctx, status='ok' if response.get('ok') else 'error', target=workflow_id, details={'action': action, 'actor': actor})
        return response

    @router.post("/admin/operator/approvals/{approval_id}/actions/{action}")
    async def broker_admin_operator_approval_action(
        approval_id: str,
        action: str,
        request: Request,
        tenant_id: str | None = Query(default=None),
        workspace_id: str | None = Query(default=None),
        environment: str | None = Query(default=None),
    ):
        gw, auth_ctx = require_permission(request, "admin.write")
        payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
        target_scope = {
            "tenant_id": tenant_id or auth_ctx.get("tenant_id"),
            "workspace_id": workspace_id or auth_ctx.get("workspace_id"),
            "environment": environment or auth_ctx.get("environment"),
        }
        actor = str(payload.get('actor') or auth_ctx.get('user_key') or auth_ctx.get('username') or 'system')
        try:
            response = AdminService().operator_console_approval_action(gw, approval_id=approval_id, action=action, actor=actor, reason=str(payload.get('reason') or ''), auth_ctx=auth_ctx, **target_scope)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            status_code = 409 if 'claimed' in str(exc).lower() else 400
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc
        audit_sensitive(gw, action='admin_operator_console_approval_action', auth_ctx=auth_ctx, status='ok' if response.get('ok') else 'error', target=approval_id, details={'action': action, 'actor': actor})
        return response

