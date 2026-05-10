"""admin/_apps.py - broker admin sub-routes for the apps domain."""
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
    """Attach the apps broker admin endpoints to *router*."""
    @router.get("/admin/app/installations")
    def broker_admin_app_installations(
        request: Request,
        limit: int = Query(default=50, ge=1, le=200),
        status: str | None = Query(default=None),
        tenant_id: str | None = Query(default=None),
        workspace_id: str | None = Query(default=None),
        environment: str | None = Query(default=None),
    ):
        gw, auth_ctx = require_permission(request, "admin.read")
        response = AdminService().list_app_installations(
            gw,
            limit=limit,
            status=status,
            tenant_id=tenant_id or auth_ctx.get("tenant_id"),
            workspace_id=workspace_id or auth_ctx.get("workspace_id"),
            environment=environment or auth_ctx.get("environment"),
        )
        audit_sensitive(gw, action="admin_app_installations", auth_ctx=auth_ctx, status="ok", details={"count": len(response.get("items", [])), "status": status})
        return response

    @router.post("/admin/app/installations")
    async def broker_admin_app_installation_register(request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json()
        response = AdminService().register_app_installation(
            gw,
            actor=str(payload.get("actor") or auth_ctx.get("username") or "broker-admin"),
            user_key=str(payload.get("user_key") or auth_ctx.get("user_key") or auth_ctx.get("username") or "operator"),
            platform=str(payload.get("platform") or "pwa"),
            device_label=str(payload.get("device_label") or ""),
            push_capable=bool(payload.get("push_capable") or False),
            notification_permission=str(payload.get("notification_permission") or "default"),
            deep_link_base=str(payload.get("deep_link_base") or "/ui/"),
            metadata=dict(payload.get("metadata") or {}),
            tenant_id=payload.get("tenant_id") or auth_ctx.get("tenant_id"),
            workspace_id=payload.get("workspace_id") or auth_ctx.get("workspace_id"),
            environment=payload.get("environment") or auth_ctx.get("environment"),
        )
        audit_sensitive(gw, action="admin_app_installation_register", auth_ctx=auth_ctx, status="ok", target=response.get("installation", {}).get("installation_id"))
        return response

    @router.get("/admin/app/notifications")
    def broker_admin_app_notifications(
        request: Request,
        limit: int = Query(default=50, ge=1, le=200),
        installation_id: str | None = Query(default=None),
        tenant_id: str | None = Query(default=None),
        workspace_id: str | None = Query(default=None),
        environment: str | None = Query(default=None),
    ):
        gw, auth_ctx = require_permission(request, "admin.read")
        response = AdminService().list_app_notifications(
            gw,
            limit=limit,
            installation_id=installation_id,
            tenant_id=tenant_id or auth_ctx.get("tenant_id"),
            workspace_id=workspace_id or auth_ctx.get("workspace_id"),
            environment=environment or auth_ctx.get("environment"),
        )
        audit_sensitive(gw, action="admin_app_notifications", auth_ctx=auth_ctx, status="ok", details={"count": len(response.get("items", []))})
        return response

    @router.post("/admin/app/notifications")
    async def broker_admin_app_notification_create(request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json()
        response = AdminService().create_app_notification(
            gw,
            actor=str(payload.get("actor") or auth_ctx.get("username") or "broker-admin"),
            title=str(payload.get("title") or "openMiura"),
            body=str(payload.get("body") or ""),
            category=str(payload.get("category") or "operator"),
            installation_id=payload.get("installation_id"),
            target_path=str(payload.get("target_path") or "/ui/?tab=operator"),
            require_interaction=bool(payload.get("require_interaction") or False),
            metadata=dict(payload.get("metadata") or {}),
            tenant_id=payload.get("tenant_id") or auth_ctx.get("tenant_id"),
            workspace_id=payload.get("workspace_id") or auth_ctx.get("workspace_id"),
            environment=payload.get("environment") or auth_ctx.get("environment"),
        )
        audit_sensitive(gw, action="admin_app_notification_create", auth_ctx=auth_ctx, status="ok", target=response.get("notification", {}).get("notification_id"))
        return response

    @router.get("/admin/app/deep-links")
    def broker_admin_app_deep_links(
        request: Request,
        limit: int = Query(default=50, ge=1, le=200),
        status: str | None = Query(default=None),
        tenant_id: str | None = Query(default=None),
        workspace_id: str | None = Query(default=None),
        environment: str | None = Query(default=None),
    ):
        gw, auth_ctx = require_permission(request, "admin.read")
        response = AdminService().list_app_deep_links(
            gw,
            limit=limit,
            status=status,
            tenant_id=tenant_id or auth_ctx.get("tenant_id"),
            workspace_id=workspace_id or auth_ctx.get("workspace_id"),
            environment=environment or auth_ctx.get("environment"),
        )
        audit_sensitive(gw, action="admin_app_deep_links", auth_ctx=auth_ctx, status="ok", details={"count": len(response.get("items", []))})
        return response

    @router.post("/admin/app/deep-links")
    async def broker_admin_app_deep_link_create(request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json()
        response = AdminService().create_app_deep_link(
            gw,
            actor=str(payload.get("actor") or auth_ctx.get("username") or "broker-admin"),
            view=str(payload.get("view") or "operator"),
            target_type=str(payload.get("target_type") or "record"),
            target_id=str(payload.get("target_id") or ""),
            params=dict(payload.get("params") or {}),
            expires_in_s=int(payload.get("expires_in_s") or 3600),
            tenant_id=payload.get("tenant_id") or auth_ctx.get("tenant_id"),
            workspace_id=payload.get("workspace_id") or auth_ctx.get("workspace_id"),
            environment=payload.get("environment") or auth_ctx.get("environment"),
        )
        audit_sensitive(gw, action="admin_app_deep_link_create", auth_ctx=auth_ctx, status="ok", target=response.get("deep_link", {}).get("link_token"))
        return response

