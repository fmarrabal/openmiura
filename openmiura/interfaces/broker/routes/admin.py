from __future__ import annotations

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


def build_admin_router() -> APIRouter:
    router = APIRouter(tags=["broker"])
    tenancy_service = TenancyService()

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


    @router.get("/admin/openclaw/runtimes")
    def broker_admin_openclaw_runtimes(
        request: Request,
        limit: int = Query(default=100, ge=1, le=300),
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
        try:
            AuthService.validate_target_scope(auth_ctx, **target_scope)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        response = AdminService().list_openclaw_runtimes(gw, limit=limit, status=status, **target_scope)
        audit_sensitive(gw, action="admin_openclaw_runtimes", auth_ctx=auth_ctx, status="ok", details={"count": len(response.get("items", [])), "status": status})
        return response

    @router.post("/admin/openclaw/runtimes")
    async def broker_admin_openclaw_register_runtime(request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json()
        target_scope = {
            "tenant_id": payload.get("tenant_id") or auth_ctx.get("tenant_id"),
            "workspace_id": payload.get("workspace_id") or auth_ctx.get("workspace_id"),
            "environment": payload.get("environment") or auth_ctx.get("environment"),
        }
        try:
            AuthService.validate_target_scope(auth_ctx, **target_scope)
            response = AdminService().register_openclaw_runtime(
                gw,
                actor=str(payload.get("actor") or auth_ctx.get("username") or "broker-admin"),
                name=str(payload.get("name") or ""),
                base_url=str(payload.get("base_url") or ""),
                transport=str(payload.get("transport") or "http"),
                auth_secret_ref=str(payload.get("auth_secret_ref") or ""),
                capabilities=list(payload.get("capabilities") or []),
                allowed_agents=list(payload.get("allowed_agents") or []),
                metadata=dict(payload.get("metadata") or {}),
                runtime_id=payload.get("runtime_id"),
                **target_scope,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit_sensitive(gw, action="admin_openclaw_runtime_register", auth_ctx=auth_ctx, status="ok", details={"runtime_id": response.get("runtime", {}).get("runtime_id")})
        return response

    @router.get("/admin/openclaw/runtimes/{runtime_id}")
    def broker_admin_openclaw_runtime_detail(
        runtime_id: str,
        request: Request,
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
        try:
            AuthService.validate_target_scope(auth_ctx, **target_scope)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        response = AdminService().get_openclaw_runtime(gw, runtime_id=runtime_id, **target_scope)
        audit_sensitive(gw, action="admin_openclaw_runtime_detail", auth_ctx=auth_ctx, status="ok" if response.get("ok") else "missing", target=runtime_id)
        return response

    @router.get("/admin/openclaw/dispatches")
    def broker_admin_openclaw_dispatches(
        request: Request,
        runtime_id: str | None = Query(default=None),
        action: str | None = Query(default=None),
        status: str | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=300),
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
        try:
            AuthService.validate_target_scope(auth_ctx, **target_scope)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        response = AdminService().list_openclaw_dispatches(gw, runtime_id=runtime_id, action=action, status=status, limit=limit, **target_scope)
        audit_sensitive(gw, action="admin_openclaw_dispatches", auth_ctx=auth_ctx, status="ok", details={"count": len(response.get("items", [])), "runtime_id": runtime_id, "dispatch_status": status})
        return response

    @router.post("/admin/openclaw/runtimes/{runtime_id}/dispatch")
    async def broker_admin_openclaw_dispatch(runtime_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json()
        target_scope = {
            "tenant_id": payload.get("tenant_id") or auth_ctx.get("tenant_id"),
            "workspace_id": payload.get("workspace_id") or auth_ctx.get("workspace_id"),
            "environment": payload.get("environment") or auth_ctx.get("environment"),
        }
        try:
            AuthService.validate_target_scope(auth_ctx, **target_scope)
            response = AdminService().dispatch_openclaw_runtime(
                gw,
                runtime_id=runtime_id,
                actor=str(payload.get("actor") or auth_ctx.get("username") or "broker-admin"),
                action=str(payload.get("action") or ""),
                payload=dict(payload.get("payload") or {}),
                agent_id=str(payload.get("agent_id") or ""),
                user_role=str(auth_ctx.get("role") or "operator"),
                user_key=str(auth_ctx.get("user_key") or auth_ctx.get("username") or ""),
                session_id=str(payload.get("session_id") or "admin"),
                dry_run=bool(payload.get("dry_run", False)),
                **target_scope,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        detail = response.get("error") or response.get("dispatch", {}).get("error_text") or ""
        audit_sensitive(gw, action="admin_openclaw_dispatch", auth_ctx=auth_ctx, status="ok" if response.get("ok") else "error", target=runtime_id, details={"action": payload.get("action"), "dispatch_id": response.get("dispatch", {}).get("dispatch_id"), "error": detail})
        return response


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



    @router.get("/admin/voice/sessions")
    def broker_admin_voice_sessions(
        request: Request,
        limit: int = Query(default=50, ge=1, le=200),
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
        response = AdminService().list_voice_sessions(
            gw,
            limit=limit,
            status=status,
            **target_scope,
        )
        audit_sensitive(gw, action="admin_voice_sessions", auth_ctx=auth_ctx, status="ok", details={"count": len(response.get("items", [])), "status": status})
        return response

    @router.get("/admin/voice/sessions/{voice_session_id}")
    def broker_admin_voice_session_detail(
        voice_session_id: str,
        request: Request,
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
        response = AdminService().get_voice_session(gw, voice_session_id=voice_session_id, **target_scope)
        audit_sensitive(gw, action="admin_voice_session_detail", auth_ctx=auth_ctx, status="ok" if response.get("ok") else "missing", target=voice_session_id)
        return response

    @router.post("/admin/voice/sessions")
    async def broker_admin_voice_session_start(request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json()
        response = AdminService().start_voice_session(
            gw,
            actor=str(payload.get("actor") or auth_ctx.get("username") or "broker-admin"),
            user_key=str(payload.get("user_key") or auth_ctx.get("user_key") or auth_ctx.get("username") or "voice-user"),
            locale=str(payload.get("locale") or "es-ES"),
            stt_provider=str(payload.get("stt_provider") or "simulated-stt"),
            tts_provider=str(payload.get("tts_provider") or "simulated-tts"),
            metadata=dict(payload.get("metadata") or {}),
            tenant_id=payload.get("tenant_id") or auth_ctx.get("tenant_id"),
            workspace_id=payload.get("workspace_id") or auth_ctx.get("workspace_id"),
            environment=payload.get("environment") or auth_ctx.get("environment"),
        )
        audit_sensitive(gw, action="admin_voice_session_start", auth_ctx=auth_ctx, status="ok", target=response.get("session", {}).get("voice_session_id"))
        return response

    @router.post("/admin/voice/sessions/{voice_session_id}/transcribe")
    async def broker_admin_voice_session_transcribe(voice_session_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json()
        try:
            response = AdminService().transcribe_voice_turn(
                gw,
                voice_session_id=voice_session_id,
                actor=str(payload.get("actor") or auth_ctx.get("username") or "broker-admin"),
                transcript_text=str(payload.get("transcript_text") or ""),
                confidence=float(payload.get("confidence") or 1.0),
                language=str(payload.get("language") or ""),
                metadata=dict(payload.get("metadata") or {}),
                tenant_id=payload.get("tenant_id") or auth_ctx.get("tenant_id"),
                workspace_id=payload.get("workspace_id") or auth_ctx.get("workspace_id"),
                environment=payload.get("environment") or auth_ctx.get("environment"),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="voice_session_not_found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit_sensitive(gw, action="admin_voice_session_transcribe", auth_ctx=auth_ctx, status="ok", target=voice_session_id)
        return response

    @router.post("/admin/voice/sessions/{voice_session_id}/respond")
    async def broker_admin_voice_session_respond(voice_session_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json()
        try:
            response = AdminService().respond_voice_turn(
                gw,
                voice_session_id=voice_session_id,
                actor=str(payload.get("actor") or auth_ctx.get("username") or "broker-admin"),
                text=str(payload.get("text") or ""),
                voice_name=str(payload.get("voice_name") or "assistant"),
                metadata=dict(payload.get("metadata") or {}),
                tenant_id=payload.get("tenant_id") or auth_ctx.get("tenant_id"),
                workspace_id=payload.get("workspace_id") or auth_ctx.get("workspace_id"),
                environment=payload.get("environment") or auth_ctx.get("environment"),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="voice_session_not_found") from exc
        audit_sensitive(gw, action="admin_voice_session_respond", auth_ctx=auth_ctx, status="ok", target=voice_session_id)
        return response

    @router.post("/admin/voice/sessions/{voice_session_id}/confirm")
    async def broker_admin_voice_session_confirm(voice_session_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json()
        try:
            response = AdminService().confirm_voice_turn(
                gw,
                voice_session_id=voice_session_id,
                actor=str(payload.get("actor") or auth_ctx.get("username") or "broker-admin"),
                decision=str(payload.get("decision") or "confirm"),
                confirmation_text=str(payload.get("confirmation_text") or ""),
                tenant_id=payload.get("tenant_id") or auth_ctx.get("tenant_id"),
                workspace_id=payload.get("workspace_id") or auth_ctx.get("workspace_id"),
                environment=payload.get("environment") or auth_ctx.get("environment"),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="voice_session_not_found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit_sensitive(gw, action="admin_voice_session_confirm", auth_ctx=auth_ctx, status="ok", target=voice_session_id)
        return response

    @router.post("/admin/voice/sessions/{voice_session_id}/close")
    async def broker_admin_voice_session_close(voice_session_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        try:
            response = AdminService().close_voice_session(
                gw,
                voice_session_id=voice_session_id,
                actor=str(payload.get("actor") or auth_ctx.get("username") or "broker-admin"),
                reason=str(payload.get("reason") or ""),
                tenant_id=payload.get("tenant_id") or auth_ctx.get("tenant_id"),
                workspace_id=payload.get("workspace_id") or auth_ctx.get("workspace_id"),
                environment=payload.get("environment") or auth_ctx.get("environment"),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="voice_session_not_found") from exc
        audit_sensitive(gw, action="admin_voice_session_close", auth_ctx=auth_ctx, status="ok", target=voice_session_id)
        return response

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


    @router.get("/admin/canvas/documents")
    def broker_admin_canvas_documents(
        request: Request,
        limit: int = Query(default=50, ge=1, le=200),
        status: str | None = Query(default=None),
        tenant_id: str | None = Query(default=None),
        workspace_id: str | None = Query(default=None),
        environment: str | None = Query(default=None),
    ):
        gw, auth_ctx = require_permission(request, "admin.read")
        response = AdminService().list_canvas_documents(
            gw,
            limit=limit,
            status=status,
            tenant_id=tenant_id or auth_ctx.get("tenant_id"),
            workspace_id=workspace_id or auth_ctx.get("workspace_id"),
            environment=environment or auth_ctx.get("environment"),
        )
        audit_sensitive(gw, action="admin_canvas_documents", auth_ctx=auth_ctx, status="ok", details={"count": len(response.get("items", [])), "status": status})
        return response

    @router.post("/admin/canvas/documents")
    async def broker_admin_canvas_document_create(request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json()
        response = AdminService().create_canvas_document(
            gw,
            actor=str(payload.get("actor") or auth_ctx.get("username") or "broker-admin"),
            title=str(payload.get("title") or ""),
            description=str(payload.get("description") or ""),
            status=str(payload.get("status") or "active"),
            metadata=dict(payload.get("metadata") or {}),
            tenant_id=payload.get("tenant_id") or auth_ctx.get("tenant_id"),
            workspace_id=payload.get("workspace_id") or auth_ctx.get("workspace_id"),
            environment=payload.get("environment") or auth_ctx.get("environment"),
        )
        audit_sensitive(gw, action="admin_canvas_document_create", auth_ctx=auth_ctx, status="ok", target=response.get("document", {}).get("canvas_id"))
        return response

    @router.get("/admin/canvas/documents/{canvas_id}")
    def broker_admin_canvas_document_detail(
        canvas_id: str,
        request: Request,
        tenant_id: str | None = Query(default=None),
        workspace_id: str | None = Query(default=None),
        environment: str | None = Query(default=None),
    ):
        gw, auth_ctx = require_permission(request, "admin.read")
        response = AdminService().get_canvas_document(
            gw,
            canvas_id=canvas_id,
            tenant_id=tenant_id or auth_ctx.get("tenant_id"),
            workspace_id=workspace_id or auth_ctx.get("workspace_id"),
            environment=environment or auth_ctx.get("environment"),
        )
        audit_sensitive(gw, action="admin_canvas_document_detail", auth_ctx=auth_ctx, status="ok" if response.get("ok") else "missing", target=canvas_id)
        return response

    @router.post("/admin/canvas/documents/{canvas_id}/nodes")
    async def broker_admin_canvas_node_upsert(canvas_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json()
        try:
            response = AdminService().upsert_canvas_node(
                gw,
                canvas_id=canvas_id,
                actor=str(payload.get("actor") or auth_ctx.get("username") or "broker-admin"),
                node_id=payload.get("node_id"),
                node_type=str(payload.get("node_type") or "note"),
                label=str(payload.get("label") or ""),
                position_x=float(payload.get("position_x") or 0.0),
                position_y=float(payload.get("position_y") or 0.0),
                width=float(payload.get("width") or 240.0),
                height=float(payload.get("height") or 120.0),
                data=dict(payload.get("data") or {}),
                tenant_id=payload.get("tenant_id") or auth_ctx.get("tenant_id"),
                workspace_id=payload.get("workspace_id") or auth_ctx.get("workspace_id"),
                environment=payload.get("environment") or auth_ctx.get("environment"),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="canvas_not_found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit_sensitive(gw, action="admin_canvas_node_upsert", auth_ctx=auth_ctx, status="ok", target=response.get("node", {}).get("node_id"))
        return response

    @router.post("/admin/canvas/documents/{canvas_id}/edges")
    async def broker_admin_canvas_edge_upsert(canvas_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json()
        try:
            response = AdminService().upsert_canvas_edge(
                gw,
                canvas_id=canvas_id,
                actor=str(payload.get("actor") or auth_ctx.get("username") or "broker-admin"),
                edge_id=payload.get("edge_id"),
                source_node_id=str(payload.get("source_node_id") or ""),
                target_node_id=str(payload.get("target_node_id") or ""),
                label=str(payload.get("label") or ""),
                edge_type=str(payload.get("edge_type") or "default"),
                data=dict(payload.get("data") or {}),
                tenant_id=payload.get("tenant_id") or auth_ctx.get("tenant_id"),
                workspace_id=payload.get("workspace_id") or auth_ctx.get("workspace_id"),
                environment=payload.get("environment") or auth_ctx.get("environment"),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="canvas_not_found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit_sensitive(gw, action="admin_canvas_edge_upsert", auth_ctx=auth_ctx, status="ok", target=response.get("edge", {}).get("edge_id"))
        return response

    @router.post("/admin/canvas/documents/{canvas_id}/views")
    async def broker_admin_canvas_view_save(canvas_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json()
        try:
            response = AdminService().save_canvas_view(
                gw,
                canvas_id=canvas_id,
                actor=str(payload.get("actor") or auth_ctx.get("username") or "broker-admin"),
                view_id=payload.get("view_id"),
                name=str(payload.get("name") or "Default"),
                layout=dict(payload.get("layout") or {}),
                filters=dict(payload.get("filters") or {}),
                is_default=bool(payload.get("is_default") or False),
                tenant_id=payload.get("tenant_id") or auth_ctx.get("tenant_id"),
                workspace_id=payload.get("workspace_id") or auth_ctx.get("workspace_id"),
                environment=payload.get("environment") or auth_ctx.get("environment"),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="canvas_not_found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit_sensitive(gw, action="admin_canvas_view_save", auth_ctx=auth_ctx, status="ok", target=response.get("view", {}).get("view_id"))
        return response

    @router.post("/admin/canvas/documents/{canvas_id}/presence")
    async def broker_admin_canvas_presence_update(canvas_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json()
        try:
            response = AdminService().update_canvas_presence(
                gw,
                canvas_id=canvas_id,
                actor=str(payload.get("actor") or auth_ctx.get("username") or "broker-admin"),
                user_key=str(payload.get("user_key") or auth_ctx.get("username") or "operator"),
                cursor_x=float(payload.get("cursor_x") or 0.0),
                cursor_y=float(payload.get("cursor_y") or 0.0),
                selected_node_id=payload.get("selected_node_id"),
                status=str(payload.get("status") or "active"),
                metadata=dict(payload.get("metadata") or {}),
                tenant_id=payload.get("tenant_id") or auth_ctx.get("tenant_id"),
                workspace_id=payload.get("workspace_id") or auth_ctx.get("workspace_id"),
                environment=payload.get("environment") or auth_ctx.get("environment"),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="canvas_not_found") from exc
        audit_sensitive(gw, action="admin_canvas_presence_update", auth_ctx=auth_ctx, status="ok", target=response.get("presence", {}).get("presence_id"))
        return response

    @router.get("/admin/canvas/documents/{canvas_id}/comments")
    def broker_admin_canvas_comments(
        canvas_id: str,
        request: Request,
        limit: int = Query(default=50, ge=1, le=200),
        status: str | None = Query(default=None),
        tenant_id: str | None = Query(default=None),
        workspace_id: str | None = Query(default=None),
        environment: str | None = Query(default=None),
    ):
        gw, auth_ctx = require_permission(request, "admin.read")
        response = AdminService().list_canvas_comments(
            gw,
            canvas_id=canvas_id,
            limit=limit,
            status=status,
            tenant_id=tenant_id or auth_ctx.get("tenant_id"),
            workspace_id=workspace_id or auth_ctx.get("workspace_id"),
            environment=environment or auth_ctx.get("environment"),
        )
        audit_sensitive(gw, action="admin_canvas_comments", auth_ctx=auth_ctx, status="ok", target=canvas_id, details={"count": len(response.get("items", []))})
        return response

    @router.post("/admin/canvas/documents/{canvas_id}/comments")
    async def broker_admin_canvas_comment_create(canvas_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json()
        try:
            response = AdminService().add_canvas_comment(
                gw,
                canvas_id=canvas_id,
                actor=str(payload.get("actor") or auth_ctx.get("username") or "broker-admin"),
                body=str(payload.get("body") or ""),
                node_id=payload.get("node_id"),
                status=str(payload.get("status") or "active"),
                metadata=dict(payload.get("metadata") or {}),
                tenant_id=payload.get("tenant_id") or auth_ctx.get("tenant_id"),
                workspace_id=payload.get("workspace_id") or auth_ctx.get("workspace_id"),
                environment=payload.get("environment") or auth_ctx.get("environment"),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="canvas_not_found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit_sensitive(gw, action="admin_canvas_comment_create", auth_ctx=auth_ctx, status="ok", target=canvas_id, details={"comment_id": response.get("comment", {}).get("comment_id")})
        return response

    @router.get("/admin/canvas/documents/{canvas_id}/snapshots")
    def broker_admin_canvas_snapshots(
        canvas_id: str,
        request: Request,
        limit: int = Query(default=50, ge=1, le=200),
        snapshot_kind: str | None = Query(default=None),
        tenant_id: str | None = Query(default=None),
        workspace_id: str | None = Query(default=None),
        environment: str | None = Query(default=None),
    ):
        gw, auth_ctx = require_permission(request, "admin.read")
        response = AdminService().list_canvas_snapshots(
            gw,
            canvas_id=canvas_id,
            limit=limit,
            snapshot_kind=snapshot_kind,
            tenant_id=tenant_id or auth_ctx.get("tenant_id"),
            workspace_id=workspace_id or auth_ctx.get("workspace_id"),
            environment=environment or auth_ctx.get("environment"),
        )
        audit_sensitive(gw, action="admin_canvas_snapshots", auth_ctx=auth_ctx, status="ok", target=canvas_id, details={"count": len(response.get("items", []))})
        return response

    @router.post("/admin/canvas/documents/{canvas_id}/snapshots")
    async def broker_admin_canvas_snapshot_create(canvas_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json()
        try:
            response = AdminService().create_canvas_snapshot(
                gw,
                canvas_id=canvas_id,
                actor=str(payload.get("actor") or auth_ctx.get("username") or "broker-admin"),
                label=str(payload.get("label") or ""),
                snapshot_kind=str(payload.get("snapshot_kind") or "manual"),
                view_id=payload.get("view_id"),
                selected_node_id=payload.get("selected_node_id"),
                metadata=dict(payload.get("metadata") or {}),
                tenant_id=payload.get("tenant_id") or auth_ctx.get("tenant_id"),
                workspace_id=payload.get("workspace_id") or auth_ctx.get("workspace_id"),
                environment=payload.get("environment") or auth_ctx.get("environment"),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="canvas_not_found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit_sensitive(gw, action="admin_canvas_snapshot_create", auth_ctx=auth_ctx, status="ok", target=canvas_id, details={"snapshot_id": response.get("snapshot", {}).get("snapshot_id")})
        return response

    @router.post("/admin/canvas/documents/{canvas_id}/share-view")
    async def broker_admin_canvas_share_view(canvas_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json()
        try:
            response = AdminService().share_canvas_view(
                gw,
                canvas_id=canvas_id,
                actor=str(payload.get("actor") or auth_ctx.get("username") or "broker-admin"),
                view_id=payload.get("view_id"),
                label=str(payload.get("label") or "Shared view"),
                selected_node_id=payload.get("selected_node_id"),
                metadata=dict(payload.get("metadata") or {}),
                tenant_id=payload.get("tenant_id") or auth_ctx.get("tenant_id"),
                workspace_id=payload.get("workspace_id") or auth_ctx.get("workspace_id"),
                environment=payload.get("environment") or auth_ctx.get("environment"),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="canvas_not_found") from exc
        audit_sensitive(gw, action="admin_canvas_share_view", auth_ctx=auth_ctx, status="ok", target=canvas_id, details={"share_token": response.get("share_token")})
        return response

    @router.get("/admin/canvas/snapshots/compare")
    def broker_admin_canvas_snapshots_compare(
        request: Request,
        snapshot_a_id: str = Query(...),
        snapshot_b_id: str = Query(...),
        tenant_id: str | None = Query(default=None),
        workspace_id: str | None = Query(default=None),
        environment: str | None = Query(default=None),
    ):
        gw, auth_ctx = require_permission(request, "admin.read")
        response = AdminService().compare_canvas_snapshots(
            gw,
            snapshot_a_id=snapshot_a_id,
            snapshot_b_id=snapshot_b_id,
            tenant_id=tenant_id or auth_ctx.get("tenant_id"),
            workspace_id=workspace_id or auth_ctx.get("workspace_id"),
            environment=environment or auth_ctx.get("environment"),
        )
        audit_sensitive(gw, action="admin_canvas_snapshots_compare", auth_ctx=auth_ctx, status="ok" if response.get("ok") else "missing", details={"snapshot_a_id": snapshot_a_id, "snapshot_b_id": snapshot_b_id})
        return response

    @router.get("/admin/canvas/documents/{canvas_id}/presence-events")
    def broker_admin_canvas_presence_events(
        canvas_id: str,
        request: Request,
        limit: int = Query(default=50, ge=1, le=200),
        tenant_id: str | None = Query(default=None),
        workspace_id: str | None = Query(default=None),
        environment: str | None = Query(default=None),
    ):
        gw, auth_ctx = require_permission(request, "admin.read")
        response = AdminService().list_canvas_presence_events(
            gw,
            canvas_id=canvas_id,
            limit=limit,
            tenant_id=tenant_id or auth_ctx.get("tenant_id"),
            workspace_id=workspace_id or auth_ctx.get("workspace_id"),
            environment=environment or auth_ctx.get("environment"),
        )
        audit_sensitive(gw, action="admin_canvas_presence_events", auth_ctx=auth_ctx, status="ok", target=canvas_id, details={"count": len(response.get("items", []))})
        return response

    @router.post("/admin/canvas/documents/{canvas_id}/overlay-state")
    async def broker_admin_canvas_overlay_state_save(canvas_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json()
        try:
            response = AdminService().save_canvas_overlay_state(
                gw,
                canvas_id=canvas_id,
                actor=str(payload.get("actor") or auth_ctx.get("username") or "broker-admin"),
                state_key=str(payload.get("state_key") or "default"),
                toggles=dict(payload.get("toggles") or {}),
                inspector=dict(payload.get("inspector") or {}),
                tenant_id=payload.get("tenant_id") or auth_ctx.get("tenant_id"),
                workspace_id=payload.get("workspace_id") or auth_ctx.get("workspace_id"),
                environment=payload.get("environment") or auth_ctx.get("environment"),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="canvas_not_found") from exc
        audit_sensitive(gw, action="admin_canvas_overlay_state_save", auth_ctx=auth_ctx, status="ok", target=canvas_id, details={"state_key": response.get("state", {}).get("state_key")})
        return response

    @router.get("/admin/canvas/documents/{canvas_id}/overlays")
    def broker_admin_canvas_overlays(
        canvas_id: str,
        request: Request,
        selected_node_id: str | None = Query(default=None),
        state_key: str = Query(default='default'),
        limit: int = Query(default=50, ge=1, le=200),
        overlay_policy: bool = Query(default=True),
        overlay_cost: bool = Query(default=True),
        overlay_traces: bool = Query(default=True),
        overlay_failures: bool = Query(default=True),
        overlay_approvals: bool = Query(default=True),
        overlay_secrets: bool = Query(default=True),
        tenant_id: str | None = Query(default=None),
        workspace_id: str | None = Query(default=None),
        environment: str | None = Query(default=None),
    ):
        gw, auth_ctx = require_permission(request, "admin.read")
        response = AdminService().get_canvas_operational_overlays(
            gw,
            canvas_id=canvas_id,
            selected_node_id=selected_node_id,
            state_key=state_key,
            limit=limit,
            toggles={
                'policy': overlay_policy,
                'cost': overlay_cost,
                'traces': overlay_traces,
                'failures': overlay_failures,
                'approvals': overlay_approvals,
                'secrets': overlay_secrets,
            },
            tenant_id=tenant_id or auth_ctx.get("tenant_id"),
            workspace_id=workspace_id or auth_ctx.get("workspace_id"),
            environment=environment or auth_ctx.get("environment"),
        )
        audit_sensitive(gw, action="admin_canvas_overlays", auth_ctx=auth_ctx, status="ok", target=canvas_id, details={"selected_node_id": selected_node_id, "state_key": state_key})
        return response

    @router.get("/admin/canvas/documents/{canvas_id}/views/operational")
    def broker_admin_canvas_operational_views(
        canvas_id: str,
        request: Request,
        tenant_id: str | None = Query(default=None),
        workspace_id: str | None = Query(default=None),
        environment: str | None = Query(default=None),
    ):
        gw, auth_ctx = require_permission(request, "admin.read")
        response = AdminService().list_canvas_operational_views(
            gw,
            canvas_id=canvas_id,
            tenant_id=tenant_id or auth_ctx.get("tenant_id"),
            workspace_id=workspace_id or auth_ctx.get("workspace_id"),
            environment=environment or auth_ctx.get("environment"),
        )
        audit_sensitive(gw, action="admin_canvas_operational_views", auth_ctx=auth_ctx, status="ok" if response.get("ok") else "missing", target=canvas_id)
        return response

    @router.get("/admin/canvas/documents/{canvas_id}/nodes/{node_id}/inspector")
    def broker_admin_canvas_node_inspector(
        canvas_id: str,
        node_id: str,
        request: Request,
        state_key: str = Query(default='default'),
        limit: int = Query(default=50, ge=1, le=200),
        tenant_id: str | None = Query(default=None),
        workspace_id: str | None = Query(default=None),
        environment: str | None = Query(default=None),
    ):
        gw, auth_ctx = require_permission(request, "admin.read")
        response = AdminService().inspect_canvas_node(
            gw,
            canvas_id=canvas_id,
            node_id=node_id,
            state_key=state_key,
            limit=limit,
            tenant_id=tenant_id or auth_ctx.get("tenant_id"),
            workspace_id=workspace_id or auth_ctx.get("workspace_id"),
            environment=environment or auth_ctx.get("environment"),
        )
        audit_sensitive(gw, action="admin_canvas_node_inspector", auth_ctx=auth_ctx, status="ok" if response.get("ok") else "missing", target=node_id, details={"canvas_id": canvas_id})
        return response

    @router.get("/admin/canvas/documents/{canvas_id}/nodes/{node_id}/timeline")
    def broker_admin_canvas_node_timeline(
        canvas_id: str,
        node_id: str,
        request: Request,
        limit: int = Query(default=50, ge=1, le=200),
        tenant_id: str | None = Query(default=None),
        workspace_id: str | None = Query(default=None),
        environment: str | None = Query(default=None),
    ):
        gw, auth_ctx = require_permission(request, "admin.read")
        response = AdminService().canvas_node_timeline(
            gw,
            canvas_id=canvas_id,
            node_id=node_id,
            limit=limit,
            tenant_id=tenant_id or auth_ctx.get("tenant_id"),
            workspace_id=workspace_id or auth_ctx.get("workspace_id"),
            environment=environment or auth_ctx.get("environment"),
        )
        audit_sensitive(gw, action="admin_canvas_node_timeline", auth_ctx=auth_ctx, status="ok" if response.get("ok") else "missing", target=node_id, details={"canvas_id": canvas_id})
        return response

    @router.post("/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/{action}")
    async def broker_admin_canvas_node_action(
        canvas_id: str,
        node_id: str,
        action: str,
        request: Request,
        tenant_id: str | None = Query(default=None),
        workspace_id: str | None = Query(default=None),
        environment: str | None = Query(default=None),
    ):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
        target_scope = {
            "tenant_id": tenant_id or payload.get("tenant_id") or auth_ctx.get("tenant_id"),
            "workspace_id": workspace_id or payload.get("workspace_id") or auth_ctx.get("workspace_id"),
            "environment": environment or payload.get("environment") or auth_ctx.get("environment"),
        }
        actor = str(payload.get('actor') or auth_ctx.get('user_key') or auth_ctx.get('username') or 'system')
        try:
            response = AdminService().execute_canvas_node_action(
                gw,
                canvas_id=canvas_id,
                node_id=node_id,
                action=action,
                actor=actor,
                reason=str(payload.get('reason') or ''),
                payload=dict(payload.get('payload') or {}),
                user_role=str(auth_ctx.get('role') or 'operator'),
                user_key=str(auth_ctx.get('user_key') or actor),
                session_id=str(payload.get('session_id') or f'canvas:{canvas_id}'),
                **target_scope,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            status_code = 409 if 'claimed' in str(exc).lower() else 400
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc
        audit_sensitive(gw, action='admin_canvas_node_action', auth_ctx=auth_ctx, status='ok' if response.get('ok') else 'error', target=node_id, details={'canvas_id': canvas_id, 'action': action, 'actor': actor})
        return response

    @router.get("/admin/canvas/documents/{canvas_id}/events")
    def broker_admin_canvas_events(
        canvas_id: str,
        request: Request,
        limit: int = Query(default=50, ge=1, le=200),
        tenant_id: str | None = Query(default=None),
        workspace_id: str | None = Query(default=None),
        environment: str | None = Query(default=None),
    ):
        gw, auth_ctx = require_permission(request, "admin.read")
        response = AdminService().list_canvas_events(
            gw,
            canvas_id=canvas_id,
            limit=limit,
            tenant_id=tenant_id or auth_ctx.get("tenant_id"),
            workspace_id=workspace_id or auth_ctx.get("workspace_id"),
            environment=environment or auth_ctx.get("environment"),
        )
        audit_sensitive(gw, action="admin_canvas_events", auth_ctx=auth_ctx, status="ok", target=canvas_id, details={"count": len(response.get("items", []))})
        return response


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

    @router.get("/admin/inspector/sessions/{session_id}")
    def broker_admin_session_inspector(session_id: str, request: Request, limit: int = Query(default=20, ge=1, le=200)):
        gw, auth_ctx = require_permission(request, "admin.read")
        response = AdminService().session_inspector(gw, session_id=session_id, limit=limit)
        audit_sensitive(gw, action="admin_session_inspector", auth_ctx=auth_ctx, status="ok", target=session_id, details={"trace_count": len(response.get("traces", []))})
        return response

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

    @router.post("/admin/reload")
    def broker_admin_reload(request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        result = gw.reload_dynamic_configs(force=True)
        audit_sensitive(gw, action="admin_reload", auth_ctx=auth_ctx, status="ok")
        return {"ok": True, **result}

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


    @router.post("/admin/voice/sessions/{voice_session_id}/audio/transcribe")
    async def broker_admin_voice_session_audio_transcribe(voice_session_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json()
        try:
            response = AdminService().transcribe_voice_audio(
                gw,
                voice_session_id=voice_session_id,
                actor=str(payload.get("actor") or auth_ctx.get("username") or "broker-admin"),
                audio_b64=str(payload.get("audio_b64") or ""),
                mime_type=str(payload.get("mime_type") or "audio/wav"),
                sample_rate_hz=int(payload.get("sample_rate_hz") or 16000),
                language=str(payload.get("language") or ""),
                metadata=dict(payload.get("metadata") or {}),
                tenant_id=payload.get("tenant_id") or auth_ctx.get("tenant_id"),
                workspace_id=payload.get("workspace_id") or auth_ctx.get("workspace_id"),
                environment=payload.get("environment") or auth_ctx.get("environment"),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="voice_session_not_found") from exc
        audit_sensitive(gw, action="admin_voice_session_audio_transcribe", auth_ctx=auth_ctx, status="ok", target=voice_session_id)
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


    return router
