"""admin/_costs.py - broker admin sub-routes for the costs domain."""
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
    """Attach the costs broker admin endpoints to *router*."""
    @router.get("/admin/costs/summary")
    def broker_admin_cost_summary(
        request: Request,
        group_by: str = Query(default="tenant"),
        limit: int = Query(default=20, ge=1, le=200),
        window_hours: int = Query(default=24 * 30, ge=1, le=24 * 365),
        workflow_name: str | None = Query(default=None),
        agent_name: str | None = Query(default=None),
        provider: str | None = Query(default=None),
        model: str | None = Query(default=None),
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
        response = AdminService().cost_summary(
            gw,
            group_by=group_by,
            limit=limit,
            window_hours=window_hours,
            workflow_name=workflow_name,
            agent_name=agent_name,
            provider=provider,
            model=model,
            **target_scope,
        )
        audit_sensitive(gw, action="admin_cost_summary", auth_ctx=auth_ctx, status="ok", details={"group_by": group_by, "count": len(response.get("items", []))})
        return response

    @router.get("/admin/costs/budgets")
    def broker_admin_cost_budgets(
        request: Request,
        limit: int = Query(default=50, ge=1, le=200),
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
        response = AdminService().cost_budgets(gw, limit=limit, **target_scope)
        audit_sensitive(gw, action="admin_cost_budgets", auth_ctx=auth_ctx, status="ok", details={"count": len(response.get("items", []))})
        return response

    @router.get("/admin/costs/alerts")
    def broker_admin_cost_alerts(
        request: Request,
        severity: str = Query(default="all"),
        limit: int = Query(default=50, ge=1, le=200),
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
        response = AdminService().cost_alerts(gw, severity=severity, limit=limit, **target_scope)
        audit_sensitive(gw, action="admin_cost_alerts", auth_ctx=auth_ctx, status="ok", details={"severity": severity, "count": len(response.get("items", []))})
        return response

