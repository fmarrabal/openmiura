"""admin/_governance.py - broker admin sub-routes for the governance domain."""
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
    """Attach the governance broker admin endpoints to *router*."""
    @router.get("/admin/policy-explorer/snapshot")
    def broker_admin_policy_explorer_snapshot(request: Request):
        gw, auth_ctx = require_permission(request, "admin.read")
        response = AdminService().policy_explorer_snapshot(gw)
        audit_sensitive(gw, action="admin_policy_explorer_snapshot", auth_ctx=auth_ctx, status="ok" if response.get("ok") else "error")
        return response

    @router.post("/admin/policy-explorer/simulate")
    async def broker_admin_policy_explorer_simulate(request: Request):
        gw, auth_ctx = require_permission(request, "admin.read")
        payload = await request.json()
        req = dict(payload.get("request") or {})
        response = AdminService().policy_explorer_simulate(
            gw,
            scope=str(req.get("scope") or "tool"),
            resource_name=str(req.get("resource_name") or req.get("tool_name") or ""),
            action=str(req.get("action") or "use"),
            agent_name=req.get("agent_name"),
            tool_name=req.get("tool_name"),
            user_role=req.get("user_role") or auth_ctx.get("role"),
            tenant_id=req.get("tenant_id") or auth_ctx.get("tenant_id"),
            workspace_id=req.get("workspace_id") or auth_ctx.get("workspace_id"),
            environment=req.get("environment") or auth_ctx.get("environment"),
            channel=req.get("channel"),
            domain=req.get("domain"),
            extra=req.get("extra") or {},
            candidate_policy=payload.get("candidate_policy") or None,
            candidate_policy_yaml=payload.get("candidate_policy_yaml"),
        )
        audit_sensitive(gw, action="admin_policy_explorer_simulate", auth_ctx=auth_ctx, status="ok", details={"scope": req.get("scope"), "resource_name": req.get("resource_name"), "changed": response.get("changed")})
        return response

    @router.post("/admin/policy-explorer/diff")
    async def broker_admin_policy_explorer_diff(request: Request):
        gw, auth_ctx = require_permission(request, "admin.read")
        payload = await request.json()
        response = AdminService().policy_explorer_diff(
            gw,
            candidate_policy=payload.get("candidate_policy") or None,
            candidate_policy_yaml=payload.get("candidate_policy_yaml"),
            baseline_policy=payload.get("baseline_policy") or None,
            baseline_policy_yaml=payload.get("baseline_policy_yaml"),
            samples=list(payload.get("samples") or []),
        )
        audit_sensitive(gw, action="admin_policy_explorer_diff", auth_ctx=auth_ctx, status="ok" if response.get("ok") else "error", details={"sample_count": len(response.get("sample_results") or [])})
        return response

    @router.get("/admin/compliance/summary")
    def broker_admin_compliance_summary(
        request: Request,
        tenant_id: str | None = Query(default=None),
        workspace_id: str | None = Query(default=None),
        environment: str | None = Query(default=None),
        window_hours: int = Query(default=72, ge=1, le=24 * 30),
        limit_per_section: int = Query(default=20, ge=1, le=200),
    ):
        gw, auth_ctx = require_permission(request, "admin.read")
        target_scope = {
            "tenant_id": tenant_id or auth_ctx.get("tenant_id"),
            "workspace_id": workspace_id or auth_ctx.get("workspace_id"),
            "environment": environment or auth_ctx.get("environment"),
        }
        payload = AdminService().compliance_summary(gw, window_hours=window_hours, limit_per_section=limit_per_section, **target_scope)
        audit_sensitive(gw, action="admin_compliance_summary", auth_ctx=auth_ctx, status="ok", details={"window_hours": window_hours, "scope": target_scope})
        return payload

    @router.post("/admin/compliance/export")
    async def broker_admin_compliance_export(request: Request):
        gw, auth_ctx = require_permission(request, "admin.read")
        payload = await request.json()
        target_scope = {
            "tenant_id": payload.get("tenant_id") or auth_ctx.get("tenant_id"),
            "workspace_id": payload.get("workspace_id") or auth_ctx.get("workspace_id"),
            "environment": payload.get("environment") or auth_ctx.get("environment"),
        }
        response = AdminService().export_compliance_report(
            gw,
            window_hours=int(payload.get("window_hours") or 72),
            limit_per_section=int(payload.get("limit_per_section") or 100),
            sections=list(payload.get("sections") or ["overview", "security", "secret_usage", "approvals", "config_changes", "tool_calls", "sessions"]),
            report_label=str(payload.get("report_label") or "initial"),
            **target_scope,
        )
        audit_sensitive(gw, action="admin_compliance_export", auth_ctx=auth_ctx, status="ok", details={"scope": target_scope, "report_label": response.get("report", {}).get("label")})
        return response

