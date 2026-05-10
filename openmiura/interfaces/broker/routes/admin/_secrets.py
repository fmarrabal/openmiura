"""admin/_secrets.py - broker admin sub-routes for the secrets domain."""
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
    """Attach the secrets broker admin endpoints to *router*."""
    @router.get("/admin/secrets/summary")
    def broker_admin_secret_governance_summary(
        request: Request,
        tenant_id: str | None = Query(default=None),
        workspace_id: str | None = Query(default=None),
        environment: str | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=500),
    ):
        gw, auth_ctx = require_permission(request, "admin.read")
        target_scope = {
            "tenant_id": tenant_id or auth_ctx.get("tenant_id"),
            "workspace_id": workspace_id or auth_ctx.get("workspace_id"),
            "environment": environment or auth_ctx.get("environment"),
        }
        response = AdminService().secret_governance_summary(gw, limit=limit, **target_scope)
        audit_sensitive(gw, action="admin_secret_governance_summary", auth_ctx=auth_ctx, status="ok" if response.get("ok") else "error", details={"total_events": (response.get("summary") or {}).get("total_events", 0), "denied_events": (response.get("summary") or {}).get("denied_events", 0)})
        return response

    @router.get("/admin/secrets/timeline")
    def broker_admin_secret_governance_timeline(
        request: Request,
        q: str | None = Query(default=None),
        ref: str | None = Query(default=None),
        tool_name: str | None = Query(default=None),
        outcome: str | None = Query(default=None),
        tenant_id: str | None = Query(default=None),
        workspace_id: str | None = Query(default=None),
        environment: str | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=500),
    ):
        gw, auth_ctx = require_permission(request, "admin.read")
        target_scope = {
            "tenant_id": tenant_id or auth_ctx.get("tenant_id"),
            "workspace_id": workspace_id or auth_ctx.get("workspace_id"),
            "environment": environment or auth_ctx.get("environment"),
        }
        response = AdminService().secret_governance_timeline(gw, q=q, ref=ref, tool_name=tool_name, outcome=outcome, limit=limit, **target_scope)
        audit_sensitive(gw, action="admin_secret_governance_timeline", auth_ctx=auth_ctx, status="ok" if response.get("ok") else "error", details={"items": len(response.get("items") or []), "ref": ref, "tool_name": tool_name, "outcome": outcome})
        return response

    @router.get("/admin/secrets/catalog")
    def broker_admin_secret_governance_catalog(
        request: Request,
        q: str | None = Query(default=None),
        tenant_id: str | None = Query(default=None),
        workspace_id: str | None = Query(default=None),
        environment: str | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=500),
    ):
        gw, auth_ctx = require_permission(request, "admin.read")
        target_scope = {
            "tenant_id": tenant_id or auth_ctx.get("tenant_id"),
            "workspace_id": workspace_id or auth_ctx.get("workspace_id"),
            "environment": environment or auth_ctx.get("environment"),
        }
        response = AdminService().secret_governance_catalog(gw, q=q, limit=limit, **target_scope)
        audit_sensitive(gw, action="admin_secret_governance_catalog", auth_ctx=auth_ctx, status="ok" if response.get("ok") else "error", details={"visible_refs": len(response.get("items") or []), "limit": limit})
        return response

    @router.get("/admin/secrets/usage")
    def broker_admin_secret_governance_usage(
        request: Request,
        q: str | None = Query(default=None),
        ref: str | None = Query(default=None),
        tool_name: str | None = Query(default=None),
        tenant_id: str | None = Query(default=None),
        workspace_id: str | None = Query(default=None),
        environment: str | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=500),
    ):
        gw, auth_ctx = require_permission(request, "admin.read")
        target_scope = {
            "tenant_id": tenant_id or auth_ctx.get("tenant_id"),
            "workspace_id": workspace_id or auth_ctx.get("workspace_id"),
            "environment": environment or auth_ctx.get("environment"),
        }
        response = AdminService().secret_governance_usage(gw, q=q, ref=ref, tool_name=tool_name, limit=limit, **target_scope)
        audit_sensitive(gw, action="admin_secret_governance_usage", auth_ctx=auth_ctx, status="ok" if response.get("ok") else "error", details={"groups": len(response.get("items") or []), "ref": ref, "tool_name": tool_name})
        return response

    @router.post("/admin/secrets/explain")
    async def broker_admin_secret_governance_explain(request: Request):
        gw, auth_ctx = require_permission(request, "admin.read")
        payload = await request.json()
        response = AdminService().secret_governance_explain(
            gw,
            ref=str(payload.get("ref") or ""),
            tool_name=str(payload.get("tool_name") or ""),
            user_role=payload.get("user_role") or auth_ctx.get("role") or 'user',
            tenant_id=payload.get("tenant_id") or auth_ctx.get("tenant_id"),
            workspace_id=payload.get("workspace_id") or auth_ctx.get("workspace_id"),
            environment=payload.get("environment") or auth_ctx.get("environment"),
            domain=payload.get("domain"),
        )
        audit_sensitive(gw, action="admin_secret_governance_explain", auth_ctx=auth_ctx, status="ok" if response.get("ok") else "error", target=str(payload.get("ref") or ""), details={"tool_name": payload.get("tool_name"), "allowed": response.get("allowed")})
        return response

