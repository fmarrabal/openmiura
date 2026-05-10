"""admin/_replay.py - broker admin sub-routes for the replay domain."""
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
    """Attach the replay broker admin endpoints to *router*."""
    @router.get("/admin/replay/sessions/{session_id}")
    def broker_admin_session_replay(
        session_id: str,
        request: Request,
        limit: int = Query(default=200, ge=1, le=500),
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
        response = AdminService().session_replay(gw, session_id=session_id, limit=limit, **target_scope)
        audit_sensitive(gw, action="admin_session_replay", auth_ctx=auth_ctx, status="ok", target=session_id, details={"timeline_count": len(response.get("timeline", []))})
        return response

    @router.get("/admin/replay/workflows/{workflow_id}")
    def broker_admin_workflow_replay(
        workflow_id: str,
        request: Request,
        limit: int = Query(default=200, ge=1, le=500),
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
        response = AdminService().workflow_replay(gw, workflow_id=workflow_id, limit=limit, **target_scope)
        audit_sensitive(gw, action="admin_workflow_replay", auth_ctx=auth_ctx, status="ok", target=workflow_id, details={"timeline_count": len(response.get("timeline", []))})
        return response

    @router.post("/admin/replay/compare")
    async def broker_admin_replay_compare(request: Request):
        gw, auth_ctx = require_permission(request, "admin.read")
        payload = await request.json()
        target_scope = {
            "tenant_id": payload.get("tenant_id") or auth_ctx.get("tenant_id"),
            "workspace_id": payload.get("workspace_id") or auth_ctx.get("workspace_id"),
            "environment": payload.get("environment") or auth_ctx.get("environment"),
        }
        response = AdminService().replay_compare(
            gw,
            left_kind=str(payload.get("left_kind") or "session"),
            left_id=str(payload.get("left_id") or ""),
            right_kind=str(payload.get("right_kind") or "session"),
            right_id=str(payload.get("right_id") or ""),
            limit=int(payload.get("limit") or 200),
            **target_scope,
        )
        audit_sensitive(gw, action="admin_replay_compare", auth_ctx=auth_ctx, status="ok" if response.get("ok") else "error", details={"changed": response.get("changed")})
        return response

