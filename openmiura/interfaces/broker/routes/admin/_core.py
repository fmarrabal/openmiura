"""admin/_core.py - broker admin sub-routes for the core domain."""
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
    """Attach the core broker admin endpoints to *router*."""
    @router.get("/admin/overview")
    def broker_admin_overview(request: Request):
        gw, auth_ctx = require_permission(request, "admin.read")
        summary = metrics_summary(gw, auth_ctx)
        scope = AuthService.scope_filters(auth_ctx, include_environment=True)
        if any(scope.values()):
            counts = getattr(gw.audit, "table_counts_scoped", lambda **_: getattr(gw.audit, "table_counts", lambda: {})())(**scope) or {}
        else:
            counts = getattr(gw.audit, "table_counts", lambda: {})() or {}
        return {
            "ok": True,
            "service": "openMiura",
            "summary": summary,
            "counts": counts,
            "identities": len(getattr(gw.audit, "list_identities", lambda *_args, **_kwargs: [])(**AuthService.scope_filters(auth_ctx))),
            "auth_users": len(getattr(gw.audit, "list_auth_users", lambda **_kwargs: [])(**AuthService.scope_filters(auth_ctx))),
            "channels": {
                "telegram": bool(getattr(gw, "telegram", None)),
                "slack": bool(getattr(gw, "slack", None)),
                "discord": bool(getattr(gw.settings, "discord", None) and getattr(gw.settings.discord, "bot_token", "")),
                "mcp": bool(getattr(getattr(gw, "settings", None), "mcp", None) and getattr(gw.settings.mcp, "enabled", False)),
                "broker": bool(getattr(getattr(gw, "settings", None), "broker", None) and getattr(gw.settings.broker, "enabled", False)),
            },
            "llm": {
                "provider": gw.settings.llm.provider,
                "model": gw.settings.llm.model,
                "base_url": gw.settings.llm.base_url,
            },
            "tenancy": tenancy_service.catalog(gw.settings, **scope),
        }

    @router.get("/admin/events")
    def broker_admin_events(request: Request, limit: int = Query(default=50, ge=1, le=200), channel: str | None = Query(default=None)):
        gw, auth_ctx = require_permission(request, "events.read")
        items = gw.audit.get_recent_events(limit=limit, channel=channel, **AuthService.scope_filters(auth_ctx, include_environment=True))
        audit_sensitive(gw, action="admin_events_read", auth_ctx=auth_ctx, status="ok", details={"count": len(items), "channel": channel})
        return {"ok": True, "items": items}

    @router.get("/admin/identities")
    def broker_admin_identities(request: Request, global_user_key: str | None = Query(default=None)):
        gw, auth_ctx = require_permission(request, "identities.read")
        items = gw.audit.list_identities(global_user_key, **AuthService.scope_filters(auth_ctx))
        audit_sensitive(gw, action="admin_identities_read", auth_ctx=auth_ctx, status="ok", target=str(global_user_key or ""), details={"count": len(items)})
        return {"ok": True, "items": items}

    @router.get("/admin/sessions")
    def broker_admin_sessions(request: Request, limit: int = Query(default=100, ge=1, le=300), channel: str | None = Query(default=None)):
        gw, auth_ctx = require_permission(request, "sessions.read")
        items = gw.audit.list_sessions(limit=limit, channel=channel, **AuthService.scope_filters(auth_ctx, include_environment=True))
        audit_sensitive(gw, action="admin_sessions_read", auth_ctx=auth_ctx, status="ok", details={"count": len(items), "channel": channel})
        return {"ok": True, "items": items}

    @router.get("/admin/memory/search")
    def broker_admin_memory_search(request: Request, q: str | None = Query(default=None), user_key: str | None = Query(default=None), limit: int = Query(default=20, ge=1, le=100)):
        gw, auth_ctx = require_permission(request, "memory.read")
        if getattr(gw, "memory", None) is not None:
            try:
                items = gw.memory.search_items(user_key=user_key, text_contains=q, limit=limit, **AuthService.scope_filters(auth_ctx, include_environment=True))
            except Exception:
                items = gw.audit.search_memory_items(user_key=user_key, text_contains=q, limit=limit, **AuthService.scope_filters(auth_ctx, include_environment=True))
        else:
            items = gw.audit.search_memory_items(user_key=user_key, text_contains=q, limit=limit, **AuthService.scope_filters(auth_ctx, include_environment=True))
        audit_sensitive(gw, action="admin_memory_search", auth_ctx=auth_ctx, status="ok", target=str(user_key or ""), details={"query": q, "count": len(items)})
        return {"ok": True, "items": items}

    @router.get("/admin/tool-calls")
    def broker_admin_tool_calls(request: Request, limit: int = Query(default=100, ge=1, le=300), session_id: str | None = Query(default=None), user_key: str | None = Query(default=None), agent_id: str | None = Query(default=None), tool_name: str | None = Query(default=None)):
        gw, auth_ctx = require_permission(request, "tool_calls.read")
        items = gw.audit.list_tool_calls(limit=limit, session_id=session_id, user_key=user_key, agent_id=agent_id, tool_name=tool_name, **AuthService.scope_filters(auth_ctx, include_environment=True))
        audit_sensitive(gw, action="admin_tool_calls_read", auth_ctx=auth_ctx, status="ok", details={"count": len(items), "tool_name": tool_name, "agent_id": agent_id})
        return {"ok": True, "items": items}

    @router.get("/admin/tenancy")
    def broker_admin_tenancy(request: Request):
        gw, auth_ctx = require_permission(request, "admin.read")
        scope = AuthService.scope_filters(auth_ctx, include_environment=True)
        payload = tenancy_service.catalog(gw.settings, **scope)
        audit_sensitive(gw, action="admin_tenancy_read", auth_ctx=auth_ctx, status="ok", details={"enabled": payload.get("enabled"), "scope": payload.get("scope")})
        return {"ok": True, **payload}

    @router.get("/admin/tenancy/effective-config")
    def broker_admin_tenancy_effective_config(
        request: Request,
        tenant_id: str | None = Query(default=None),
        workspace_id: str | None = Query(default=None),
        environment: str | None = Query(default=None),
    ):
        gw, auth_ctx = require_permission(request, "admin.read")
        requested = {
            "tenant_id": tenant_id or auth_ctx.get("tenant_id"),
            "workspace_id": workspace_id or auth_ctx.get("workspace_id"),
            "environment": environment or auth_ctx.get("environment"),
        }
        try:
            AuthService.validate_target_scope(auth_ctx, **requested)
            payload = tenancy_service.effective_config(
                gw.settings,
                tenant_id=requested["tenant_id"],
                workspace_id=requested["workspace_id"],
                environment=requested["environment"],
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit_sensitive(
            gw,
            action="admin_tenancy_effective_config_read",
            auth_ctx=auth_ctx,
            status="ok",
            details={"scope": payload.get("scope")},
        )
        return {"ok": True, **payload}

    @router.get("/admin/inspector/sessions/{session_id}")
    def broker_admin_session_inspector(session_id: str, request: Request, limit: int = Query(default=20, ge=1, le=200)):
        gw, auth_ctx = require_permission(request, "admin.read")
        response = AdminService().session_inspector(gw, session_id=session_id, limit=limit)
        audit_sensitive(gw, action="admin_session_inspector", auth_ctx=auth_ctx, status="ok", target=session_id, details={"trace_count": len(response.get("traces", []))})
        return response

    @router.post("/admin/security/explain")
    async def broker_admin_security_explain(request: Request):
        gw, auth_ctx = require_permission(request, "admin.read")
        payload = await request.json()
        response = AdminService().explain_security(
            gw,
            scope=str(payload.get("scope") or ""),
            resource_name=str(payload.get("resource_name") or ""),
            action=str(payload.get("action") or "use"),
            agent_name=payload.get("agent_name"),
            user_role=payload.get("user_role") or auth_ctx.get("role"),
            tenant_id=payload.get("tenant_id") or auth_ctx.get("tenant_id"),
            workspace_id=payload.get("workspace_id") or auth_ctx.get("workspace_id"),
            environment=payload.get("environment") or auth_ctx.get("environment"),
            channel=payload.get("channel"),
            domain=payload.get("domain"),
            extra=payload.get("extra") or {},
            tool_name=payload.get("tool_name"),
        )
        audit_sensitive(gw, action="admin_security_explain", auth_ctx=auth_ctx, status="ok", target=str(payload.get("resource_name") or ""), details={"scope": payload.get("scope")})
        return response

    @router.post("/admin/reload")
    def broker_admin_reload(request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        result = gw.reload_dynamic_configs(force=True)
        audit_sensitive(gw, action="admin_reload", auth_ctx=auth_ctx, status="ok")
        return {"ok": True, **result}

