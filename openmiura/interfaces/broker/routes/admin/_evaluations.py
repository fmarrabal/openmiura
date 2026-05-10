"""admin/_evaluations.py - broker admin sub-routes for the evaluations domain."""
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
    """Attach the evaluations broker admin endpoints to *router*."""
    @router.get("/admin/evals/suites")
    def broker_admin_evaluation_suites(request: Request):
        gw, auth_ctx = require_permission(request, "admin.read")
        response = AdminService().list_evaluation_suites(gw)
        audit_sensitive(gw, action="admin_evaluation_suites", auth_ctx=auth_ctx, status="ok", details={"count": len(response.get("suites", []))})
        return response

    @router.post("/admin/evals/run")
    async def broker_admin_evaluation_run(request: Request):
        gw, auth_ctx = require_permission(request, "admin.read")
        payload = await request.json()
        target_scope = {
            "tenant_id": payload.get("tenant_id") or auth_ctx.get("tenant_id"),
            "workspace_id": payload.get("workspace_id") or auth_ctx.get("workspace_id"),
            "environment": payload.get("environment") or auth_ctx.get("environment"),
        }
        response = AdminService().run_evaluation_suite(
            gw,
            suite_name=str(payload.get("suite_name") or ""),
            observations=list(payload.get("observations") or []),
            requested_by=str(payload.get("requested_by") or auth_ctx.get("username") or "broker-admin"),
            provider=payload.get("provider"),
            model=payload.get("model"),
            agent_name=payload.get("agent_name"),
            **target_scope,
        )
        audit_sensitive(gw, action="admin_evaluation_run", auth_ctx=auth_ctx, status=str(response.get("status") or "unknown"), details={"suite_name": payload.get("suite_name"), "run_id": response.get("run_id")})
        return response

    @router.get("/admin/evals/runs")
    def broker_admin_evaluation_runs(
        request: Request,
        limit: int = Query(default=20, ge=1, le=200),
        suite_name: str | None = Query(default=None),
        status: str | None = Query(default=None),
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
        response = AdminService().list_evaluation_runs(
            gw,
            limit=limit,
            suite_name=suite_name,
            status=status,
            agent_name=agent_name,
            provider=provider,
            model=model,
            **target_scope,
        )
        audit_sensitive(gw, action="admin_evaluation_runs", auth_ctx=auth_ctx, status="ok", details={"suite_name": suite_name, "agent_name": agent_name, "provider": provider, "model": model, "count": len(response.get("items", []))})
        return response

    @router.get("/admin/evals/runs/{run_id}")
    def broker_admin_evaluation_run_detail(run_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.read")
        response = AdminService().get_evaluation_run(gw, run_id=run_id)
        audit_sensitive(gw, action="admin_evaluation_run_detail", auth_ctx=auth_ctx, status="ok" if response.get("ok") else "missing", target=run_id)
        return response

    @router.get("/admin/evals/runs/{run_id}/compare")
    def broker_admin_evaluation_run_compare(run_id: str, request: Request, baseline_run_id: str | None = Query(default=None)):
        gw, auth_ctx = require_permission(request, "admin.read")
        response = AdminService().compare_evaluation_run(gw, run_id=run_id, baseline_run_id=baseline_run_id)
        audit_sensitive(gw, action="admin_evaluation_run_compare", auth_ctx=auth_ctx, status="ok" if response.get("ok") else "missing", target=run_id, details={"baseline_run_id": baseline_run_id})
        return response

    @router.get("/admin/evals/regressions")
    def broker_admin_evaluation_regressions(
        request: Request,
        limit: int = Query(default=20, ge=1, le=200),
        suite_name: str | None = Query(default=None),
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
        response = AdminService().list_evaluation_regressions(
            gw,
            limit=limit,
            suite_name=suite_name,
            agent_name=agent_name,
            provider=provider,
            model=model,
            **target_scope,
        )
        audit_sensitive(gw, action="admin_evaluation_regressions", auth_ctx=auth_ctx, status="ok", details={"count": len(response.get("items", []))})
        return response

    @router.get("/admin/evals/scorecards")
    def broker_admin_evaluation_scorecards(
        request: Request,
        group_by: str = Query(default="agent_provider_model"),
        limit: int = Query(default=20, ge=1, le=200),
        suite_name: str | None = Query(default=None),
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
        response = AdminService().evaluation_scorecards(
            gw,
            group_by=group_by,
            limit=limit,
            suite_name=suite_name,
            agent_name=agent_name,
            provider=provider,
            model=model,
            **target_scope,
        )
        audit_sensitive(gw, action="admin_evaluation_scorecards", auth_ctx=auth_ctx, status="ok", details={"group_by": group_by, "count": len(response.get("items", []))})
        return response

    @router.get("/admin/evals/leaderboard")
    def broker_admin_evaluation_leaderboard(
        request: Request,
        group_by: str = Query(default="agent_provider_model"),
        rank_by: str = Query(default="stability_score"),
        limit: int = Query(default=20, ge=1, le=200),
        use_case: str | None = Query(default=None),
        suite_name: str | None = Query(default=None),
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
        response = AdminService().evaluation_leaderboard(
            gw,
            group_by=group_by,
            rank_by=rank_by,
            limit=limit,
            use_case=use_case,
            suite_name=suite_name,
            agent_name=agent_name,
            provider=provider,
            model=model,
            **target_scope,
        )
        audit_sensitive(gw, action="admin_evaluation_leaderboard", auth_ctx=auth_ctx, status="ok", details={"group_by": group_by, "rank_by": rank_by, "count": len(response.get("items", []))})
        return response

    @router.get("/admin/evals/comparison")
    def broker_admin_evaluation_comparison(
        request: Request,
        split_by: str = Query(default="use_case"),
        compare_by: str = Query(default="agent_provider_model"),
        rank_by: str = Query(default="stability_score"),
        limit_groups: int = Query(default=20, ge=1, le=200),
        limit_per_group: int = Query(default=5, ge=1, le=50),
        suite_name: str | None = Query(default=None),
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
        response = AdminService().evaluation_comparison(
            gw,
            split_by=split_by,
            compare_by=compare_by,
            rank_by=rank_by,
            limit_groups=limit_groups,
            limit_per_group=limit_per_group,
            suite_name=suite_name,
            agent_name=agent_name,
            provider=provider,
            model=model,
            **target_scope,
        )
        audit_sensitive(gw, action="admin_evaluation_comparison", auth_ctx=auth_ctx, status="ok", details={"split_by": split_by, "compare_by": compare_by, "rank_by": rank_by, "count": len(response.get("groups", []))})
        return response

