"""admin/_releases.py - broker admin sub-routes for the releases domain."""
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
    """Attach the releases broker admin endpoints to *router*."""
    @router.get("/admin/releases")
    def broker_admin_releases(
        request: Request,
        limit: int = Query(default=50, ge=1, le=200),
        status: str | None = Query(default=None),
        kind: str | None = Query(default=None),
        name: str | None = Query(default=None),
        environment: str | None = Query(default=None),
        tenant_id: str | None = Query(default=None),
        workspace_id: str | None = Query(default=None),
    ):
        gw, auth_ctx = require_permission(request, "admin.read")
        target_scope = {
            "tenant_id": tenant_id or auth_ctx.get("tenant_id"),
            "workspace_id": workspace_id or auth_ctx.get("workspace_id"),
        }
        response = AdminService().list_releases(
            gw,
            limit=limit,
            status=status,
            kind=kind,
            name=name,
            environment=environment or auth_ctx.get("environment"),
            **target_scope,
        )
        audit_sensitive(gw, action="admin_releases", auth_ctx=auth_ctx, status="ok", details={"count": len(response.get("items", [])), "kind": kind, "status": status})
        return response

    @router.get("/admin/releases/{release_id}")
    def broker_admin_release_detail(
        release_id: str,
        request: Request,
        environment: str | None = Query(default=None),
        tenant_id: str | None = Query(default=None),
        workspace_id: str | None = Query(default=None),
    ):
        gw, auth_ctx = require_permission(request, "admin.read")
        target_scope = {
            "tenant_id": tenant_id or auth_ctx.get("tenant_id"),
            "workspace_id": workspace_id or auth_ctx.get("workspace_id"),
        }
        response = AdminService().get_release(gw, release_id=release_id, environment=environment or auth_ctx.get("environment"), **target_scope)
        audit_sensitive(gw, action="admin_release_detail", auth_ctx=auth_ctx, status="ok" if response.get("ok") else "missing", target=release_id)
        return response

    @router.post("/admin/releases")
    async def broker_admin_release_create(request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json()
        target_scope = {
            "tenant_id": payload.get("tenant_id") or auth_ctx.get("tenant_id"),
            "workspace_id": payload.get("workspace_id") or auth_ctx.get("workspace_id"),
        }
        try:
            response = AdminService().create_release(
                gw,
                kind=str(payload.get("kind") or ""),
                name=str(payload.get("name") or ""),
                version=str(payload.get("version") or ""),
                created_by=str(payload.get("created_by") or auth_ctx.get("username") or "broker-admin"),
                items=list(payload.get("items") or []),
                environment=payload.get("environment") or auth_ctx.get("environment"),
                notes=str(payload.get("notes") or ""),
                metadata=dict(payload.get("metadata") or {}),
                **target_scope,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit_sensitive(gw, action="admin_release_create", auth_ctx=auth_ctx, status="ok", details={"release_id": response.get("release", {}).get("release_id")})
        return response

    @router.post("/admin/releases/{release_id}/submit")
    async def broker_admin_release_submit(release_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        try:
            response = AdminService().submit_release(
                gw,
                release_id=release_id,
                actor=str(payload.get("actor") or auth_ctx.get("username") or "broker-admin"),
                reason=str(payload.get("reason") or ""),
                tenant_id=payload.get("tenant_id") or auth_ctx.get("tenant_id"),
                workspace_id=payload.get("workspace_id") or auth_ctx.get("workspace_id"),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="release_not_found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit_sensitive(gw, action="admin_release_submit", auth_ctx=auth_ctx, status="ok", target=release_id)
        return response

    @router.post("/admin/releases/{release_id}/approve")
    async def broker_admin_release_approve(release_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        try:
            response = AdminService().approve_release(
                gw,
                release_id=release_id,
                actor=str(payload.get("actor") or auth_ctx.get("username") or "broker-admin"),
                reason=str(payload.get("reason") or ""),
                tenant_id=payload.get("tenant_id") or auth_ctx.get("tenant_id"),
                workspace_id=payload.get("workspace_id") or auth_ctx.get("workspace_id"),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="release_not_found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit_sensitive(gw, action="admin_release_approve", auth_ctx=auth_ctx, status="ok", target=release_id)
        return response

    @router.post("/admin/releases/{release_id}/promote")
    async def broker_admin_release_promote(release_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        try:
            response = AdminService().promote_release(
                gw,
                release_id=release_id,
                to_environment=str(payload.get("to_environment") or payload.get("environment") or auth_ctx.get("environment") or ""),
                actor=str(payload.get("actor") or auth_ctx.get("username") or "broker-admin"),
                reason=str(payload.get("reason") or ""),
                tenant_id=payload.get("tenant_id") or auth_ctx.get("tenant_id"),
                workspace_id=payload.get("workspace_id") or auth_ctx.get("workspace_id"),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="release_not_found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit_sensitive(gw, action="admin_release_promote", auth_ctx=auth_ctx, status="ok", target=release_id, details={"to_environment": payload.get("to_environment")})
        return response

    @router.post("/admin/releases/{release_id}/canary")
    async def broker_admin_release_canary(release_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json()
        try:
            response = AdminService().configure_release_canary(
                gw,
                release_id=release_id,
                target_environment=str(payload.get("target_environment") or payload.get("to_environment") or auth_ctx.get("environment") or ""),
                actor=str(payload.get("actor") or auth_ctx.get("username") or "broker-admin"),
                strategy=str(payload.get("strategy") or "percentage"),
                traffic_percent=float(payload.get("traffic_percent") or 0),
                step_percent=float(payload.get("step_percent") or 0),
                bake_minutes=int(payload.get("bake_minutes") or 0),
                status=str(payload.get("status") or "draft"),
                metric_guardrails=dict(payload.get("metric_guardrails") or {}),
                analysis_summary=dict(payload.get("analysis_summary") or {}),
                tenant_id=payload.get("tenant_id") or auth_ctx.get("tenant_id"),
                workspace_id=payload.get("workspace_id") or auth_ctx.get("workspace_id"),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="release_not_found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit_sensitive(gw, action="admin_release_canary", auth_ctx=auth_ctx, status="ok", target=release_id)
        return response

    @router.post("/admin/releases/{release_id}/gates")
    async def broker_admin_release_gate_run(release_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json()
        try:
            response = AdminService().record_release_gate_run(
                gw,
                release_id=release_id,
                gate_name=str(payload.get("gate_name") or ""),
                status=str(payload.get("status") or ""),
                actor=str(payload.get("actor") or auth_ctx.get("username") or "broker-admin"),
                score=payload.get("score"),
                threshold=payload.get("threshold"),
                details=dict(payload.get("details") or {}),
                tenant_id=payload.get("tenant_id") or auth_ctx.get("tenant_id"),
                workspace_id=payload.get("workspace_id") or auth_ctx.get("workspace_id"),
                environment=payload.get("environment") or auth_ctx.get("environment"),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="release_not_found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit_sensitive(gw, action="admin_release_gate_run", auth_ctx=auth_ctx, status="ok", target=release_id)
        return response

    @router.post("/admin/releases/{release_id}/change-report")
    async def broker_admin_release_change_report(release_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json()
        try:
            response = AdminService().set_release_change_report(
                gw,
                release_id=release_id,
                risk_level=str(payload.get("risk_level") or "unknown"),
                actor=str(payload.get("actor") or auth_ctx.get("username") or "broker-admin"),
                summary=dict(payload.get("summary") or {}),
                diff=dict(payload.get("diff") or {}),
                tenant_id=payload.get("tenant_id") or auth_ctx.get("tenant_id"),
                workspace_id=payload.get("workspace_id") or auth_ctx.get("workspace_id"),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="release_not_found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit_sensitive(gw, action="admin_release_change_report", auth_ctx=auth_ctx, status="ok", target=release_id)
        return response

    @router.post("/admin/releases/{release_id}/rollback")
    async def broker_admin_release_rollback(release_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        try:
            response = AdminService().rollback_release(
                gw,
                release_id=release_id,
                actor=str(payload.get("actor") or auth_ctx.get("username") or "broker-admin"),
                reason=str(payload.get("reason") or ""),
                tenant_id=payload.get("tenant_id") or auth_ctx.get("tenant_id"),
                workspace_id=payload.get("workspace_id") or auth_ctx.get("workspace_id"),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="release_not_found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit_sensitive(gw, action="admin_release_rollback", auth_ctx=auth_ctx, status="ok", target=release_id)
        return response

    @router.post("/admin/releases/{release_id}/canary/activate")
    async def broker_admin_release_canary_activate(release_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json()
        try:
            response = AdminService().activate_release_canary(
                gw,
                release_id=release_id,
                actor=str(payload.get("actor") or auth_ctx.get("username") or "broker-admin"),
                baseline_release_id=payload.get("baseline_release_id"),
                tenant_id=payload.get("tenant_id") or auth_ctx.get("tenant_id"),
                workspace_id=payload.get("workspace_id") or auth_ctx.get("workspace_id"),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="release_not_found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit_sensitive(gw, action="admin_release_canary_activate", auth_ctx=auth_ctx, status="ok", target=release_id)
        return response

    @router.post("/admin/releases/{release_id}/canary/route")
    async def broker_admin_release_canary_route(release_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.read")
        payload = await request.json()
        try:
            response = AdminService().resolve_release_canary_route(
                gw,
                release_id=release_id,
                routing_key=str(payload.get("routing_key") or ""),
                actor=str(payload.get("actor") or auth_ctx.get("username") or "broker-admin"),
                tenant_id=payload.get("tenant_id") or auth_ctx.get("tenant_id"),
                workspace_id=payload.get("workspace_id") or auth_ctx.get("workspace_id"),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="release_not_found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit_sensitive(gw, action="admin_release_canary_route", auth_ctx=auth_ctx, status="ok", target=release_id)
        return response

    @router.post("/admin/releases/canary/decisions/{decision_id}/observe")
    async def broker_admin_release_canary_observe(decision_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json()
        try:
            response = AdminService().record_release_canary_observation(
                gw,
                decision_id=decision_id,
                actor=str(payload.get("actor") or auth_ctx.get("username") or "broker-admin"),
                success=bool(payload.get("success")),
                latency_ms=payload.get("latency_ms"),
                cost_estimate=payload.get("cost_estimate"),
                metadata=dict(payload.get("metadata") or {}),
                tenant_id=payload.get("tenant_id") or auth_ctx.get("tenant_id"),
                workspace_id=payload.get("workspace_id") or auth_ctx.get("workspace_id"),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="routing_decision_not_found") from exc
        audit_sensitive(gw, action="admin_release_canary_observe", auth_ctx=auth_ctx, status="ok", target=decision_id)
        return response

    @router.get("/admin/releases/{release_id}/canary/routing-summary")
    def broker_admin_release_canary_routing_summary(request: Request, release_id: str, tenant_id: str | None = Query(default=None), workspace_id: str | None = Query(default=None), target_environment: str | None = Query(default=None)):
        gw, auth_ctx = require_permission(request, "admin.read")
        try:
            response = AdminService().release_canary_routing_summary(
                gw,
                release_id=release_id,
                tenant_id=tenant_id or auth_ctx.get("tenant_id"),
                workspace_id=workspace_id or auth_ctx.get("workspace_id"),
                target_environment=target_environment or auth_ctx.get("environment"),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="release_not_found") from exc
        audit_sensitive(gw, action="admin_release_canary_routing_summary", auth_ctx=auth_ctx, status="ok", target=release_id)
        return response

