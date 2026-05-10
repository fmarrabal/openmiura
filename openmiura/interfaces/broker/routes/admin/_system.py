"""admin/_system.py - broker admin sub-routes for the system domain."""
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
    """Attach the system broker admin endpoints to *router*."""
    @router.get("/admin/phase8/packaging/summary")
    def broker_admin_phase8_packaging_summary(request: Request):
        gw, auth_ctx = require_permission(request, "admin.read")
        response = {
            "ok": True,
            "packaging": AdminService().phase8_packaging_summary(gw),
            "hardening": AdminService().phase8_hardening_summary(gw),
        }
        audit_sensitive(gw, action="admin_phase8_packaging_summary", auth_ctx=auth_ctx, status="ok")
        return response

    @router.get("/admin/phase8/packaging/builds")
    def broker_admin_phase8_package_builds(
        request: Request,
        limit: int = Query(default=50, ge=1, le=200),
        target: str | None = Query(default=None),
        status: str | None = Query(default=None),
        tenant_id: str | None = Query(default=None),
        workspace_id: str | None = Query(default=None),
        environment: str | None = Query(default=None),
    ):
        gw, auth_ctx = require_permission(request, "admin.read")
        response = AdminService().list_package_builds(
            gw,
            limit=limit,
            target=target,
            status=status,
            tenant_id=tenant_id or auth_ctx.get("tenant_id"),
            workspace_id=workspace_id or auth_ctx.get("workspace_id"),
            environment=environment or auth_ctx.get("environment"),
        )
        audit_sensitive(gw, action="admin_phase8_package_builds", auth_ctx=auth_ctx, status="ok", details={"count": len(response.get("items", [])), "target": target, "status": status})
        return response

    @router.post("/admin/phase8/packaging/builds")
    async def broker_admin_phase8_package_build_create(request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json()
        response = AdminService().create_package_build(
            gw,
            actor=str(payload.get("actor") or auth_ctx.get("username") or "broker-admin"),
            target=str(payload.get("target") or "desktop"),
            label=str(payload.get("label") or "Phase 8 shell"),
            version=str(payload.get("version") or "phase8-pr8"),
            artifact_path=str(payload.get("artifact_path") or ""),
            status=str(payload.get("status") or "ready"),
            metadata=dict(payload.get("metadata") or {}),
            tenant_id=payload.get("tenant_id") or auth_ctx.get("tenant_id"),
            workspace_id=payload.get("workspace_id") or auth_ctx.get("workspace_id"),
            environment=payload.get("environment") or auth_ctx.get("environment"),
        )
        audit_sensitive(gw, action="admin_phase8_package_build_create", auth_ctx=auth_ctx, status="ok", target=response.get("build", {}).get("build_id"), details={"target": response.get("build", {}).get("target")})
        return response

    @router.post("/admin/phase9/packaging/reproducible-build")
    async def broker_admin_phase9_reproducible_build(request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json()
        response = AdminService().create_reproducible_package_build(
            gw,
            actor=str(payload.get("actor") or auth_ctx.get("username") or "broker-admin"),
            target=str(payload.get("target") or "desktop"),
            label=str(payload.get("label") or "Reproducible build"),
            version=str(payload.get("version") or "phase9-operational-hardening"),
            source_root=payload.get("source_root"),
            output_dir=payload.get("output_dir"),
            tenant_id=payload.get("tenant_id") or auth_ctx.get("tenant_id"),
            workspace_id=payload.get("workspace_id") or auth_ctx.get("workspace_id"),
            environment=payload.get("environment") or auth_ctx.get("environment"),
        )
        audit_sensitive(gw, action="admin_phase9_reproducible_build", auth_ctx=auth_ctx, status="ok", target=response.get("build", {}).get("build_id"))
        return response

    @router.post("/admin/phase9/packaging/verify-manifest")
    async def broker_admin_phase9_verify_manifest(request: Request):
        gw, auth_ctx = require_permission(request, "admin.read")
        payload = await request.json()
        response = AdminService().verify_reproducible_package_manifest(manifest_path=str(payload.get("manifest_path") or ""))
        audit_sensitive(gw, action="admin_phase9_verify_manifest", auth_ctx=auth_ctx, status="ok", details={"ok": response.get("ok")})
        return response

