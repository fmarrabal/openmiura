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


    @router.get("/admin/openclaw/policy-packs")
    def broker_admin_openclaw_policy_packs(request: Request, runtime_class: str | None = Query(default=None), transport: str = Query(default='http')):
        gw, auth_ctx = require_permission(request, "admin.read")
        response = AdminService().list_openclaw_policy_packs(gw, runtime_class=runtime_class, transport=transport)
        audit_sensitive(gw, action="admin_openclaw_policy_packs", auth_ctx=auth_ctx, status="ok", details={"count": len(response.get("items", [])), "runtime_class": runtime_class, "transport": transport})
        return response

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

    @router.post("/admin/openclaw/runtimes/{runtime_id}/policy-pack")
    async def broker_admin_openclaw_runtime_policy_pack(runtime_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
        target_scope = {
            "tenant_id": payload.get("tenant_id") or auth_ctx.get("tenant_id"),
            "workspace_id": payload.get("workspace_id") or auth_ctx.get("workspace_id"),
            "environment": payload.get("environment") or auth_ctx.get("environment"),
        }
        actor = str(payload.get('actor') or auth_ctx.get('user_key') or auth_ctx.get('username') or 'system')
        try:
            AuthService.validate_target_scope(auth_ctx, **target_scope)
            response = AdminService().apply_openclaw_policy_pack(gw, runtime_id=runtime_id, actor=actor, pack_name=str(payload.get('pack_name') or payload.get('policy_pack') or '') or None, runtime_class=str(payload.get('runtime_class') or '') or None, overrides=dict(payload.get('overrides') or {}), **target_scope)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        audit_sensitive(gw, action="admin_openclaw_runtime_policy_pack", auth_ctx=auth_ctx, status="ok" if response.get("ok") else "error", target=runtime_id, details={"policy_pack": (((response.get('runtime_summary') or {}).get('metadata') or {}).get('policy_pack'))})
        return response

    @router.post("/admin/openclaw/runtimes/{runtime_id}/recovery-jobs")
    async def broker_admin_openclaw_runtime_schedule_recovery(runtime_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
        target_scope = {
            "tenant_id": payload.get("tenant_id") or auth_ctx.get("tenant_id"),
            "workspace_id": payload.get("workspace_id") or auth_ctx.get("workspace_id"),
            "environment": payload.get("environment") or auth_ctx.get("environment"),
        }
        actor = str(payload.get('actor') or auth_ctx.get('user_key') or auth_ctx.get('username') or 'system')
        try:
            AuthService.validate_target_scope(auth_ctx, **target_scope)
            response = AdminService().schedule_openclaw_runtime_recovery_job(gw, runtime_id=runtime_id, actor=actor, reason=str(payload.get('reason') or ''), limit=int(payload['limit']) if payload.get('limit') is not None else None, schedule_kind=str(payload.get('schedule_kind') or '') or None, interval_s=int(payload['interval_s']) if payload.get('interval_s') is not None else None, schedule_expr=str(payload.get('schedule_expr') or '') or None, timezone_name=str(payload.get('timezone_name') or payload.get('timezone') or 'UTC'), not_before=payload.get('not_before'), not_after=payload.get('not_after'), max_runs=payload.get('max_runs'), enabled=bool(payload.get('enabled', True)), **target_scope)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        audit_sensitive(gw, action="admin_openclaw_runtime_schedule_recovery", auth_ctx=auth_ctx, status="ok" if response.get("ok") else "error", target=runtime_id, details={"job_id": response.get("job", {}).get("job_id")})
        return response

    @router.get("/admin/openclaw/worker-leases")
    def broker_admin_openclaw_worker_leases(
        request: Request,
        runtime_id: str | None = Query(default=None),
        lease_type: str | None = Query(default=None),
        active_only: bool | None = Query(default=None),
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
        response = AdminService().list_openclaw_worker_leases(gw, runtime_id=runtime_id, lease_type=lease_type, active_only=active_only, limit=limit, **target_scope)
        audit_sensitive(gw, action="admin_openclaw_worker_leases", auth_ctx=auth_ctx, status="ok", details={"count": len(response.get("items", [])), "runtime_id": runtime_id, "lease_type": lease_type})
        return response

    @router.get("/admin/openclaw/idempotency-records")
    def broker_admin_openclaw_idempotency_records(
        request: Request,
        runtime_id: str | None = Query(default=None),
        status: str | None = Query(default=None),
        active_only: bool | None = Query(default=None),
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
        response = AdminService().list_openclaw_idempotency_records(gw, runtime_id=runtime_id, status=status, active_only=active_only, limit=limit, **target_scope)
        audit_sensitive(gw, action="admin_openclaw_idempotency_records", auth_ctx=auth_ctx, status="ok", details={"count": len(response.get("items", [])), "runtime_id": runtime_id, "status": status})
        return response

    @router.get("/admin/openclaw/recovery-jobs")
    def broker_admin_openclaw_recovery_jobs(
        request: Request,
        runtime_id: str | None = Query(default=None),
        enabled: bool | None = Query(default=None),
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
        response = AdminService().list_openclaw_recovery_jobs(gw, runtime_id=runtime_id, enabled=enabled, limit=limit, **target_scope)
        audit_sensitive(gw, action="admin_openclaw_recovery_jobs", auth_ctx=auth_ctx, status="ok", details={"count": len(response.get("items", [])), "runtime_id": runtime_id})
        return response

    @router.post("/admin/openclaw/recovery-jobs/run-due")
    async def broker_admin_openclaw_recovery_jobs_run_due(request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
        target_scope = {
            "tenant_id": payload.get("tenant_id") or auth_ctx.get("tenant_id"),
            "workspace_id": payload.get("workspace_id") or auth_ctx.get("workspace_id"),
            "environment": payload.get("environment") or auth_ctx.get("environment"),
        }
        actor = str(payload.get('actor') or auth_ctx.get('user_key') or auth_ctx.get('username') or 'system')
        try:
            AuthService.validate_target_scope(auth_ctx, **target_scope)
            response = AdminService().run_due_openclaw_recovery_jobs(gw, actor=actor, limit=int(payload.get('limit') or 20), runtime_id=str(payload.get('runtime_id') or '') or None, user_role=str(auth_ctx.get('role') or 'operator'), user_key=str(auth_ctx.get('user_key') or actor), **target_scope)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        audit_sensitive(gw, action="admin_openclaw_recovery_jobs_run_due", auth_ctx=auth_ctx, status="ok" if response.get("ok") else "error", details={"executed": ((response.get('summary') or {}).get('executed')), "runtime_id": payload.get('runtime_id')})
        return response

    @router.get("/admin/openclaw/runtimes/{runtime_id}/concurrency")
    def broker_admin_openclaw_runtime_concurrency(
        runtime_id: str,
        request: Request,
        limit: int = Query(default=20, ge=1, le=200),
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
        response = AdminService().get_openclaw_runtime_concurrency(gw, runtime_id=runtime_id, limit=limit, **target_scope)
        audit_sensitive(gw, action="admin_openclaw_runtime_concurrency", auth_ctx=auth_ctx, status="ok" if response.get("ok") else "error", target=runtime_id, details={"active_leases": ((response.get("summary") or {}).get("active_leases")), "in_progress_idempotency": ((response.get("summary") or {}).get("in_progress_idempotency_count"))})
        return response

    @router.get("/admin/openclaw/runtime-alerts")
    def broker_admin_openclaw_runtime_alerts(
        request: Request,
        runtime_id: str | None = Query(default=None),
        severity: str | None = Query(default=None),
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
        response = AdminService().list_openclaw_runtime_alerts(gw, runtime_id=runtime_id, severity=severity, limit=limit, **target_scope)
        audit_sensitive(gw, action="admin_openclaw_runtime_alerts", auth_ctx=auth_ctx, status="ok", target=runtime_id or "all", details={"count": len(response.get("items", [])), "severity": severity, "critical_count": ((response.get("summary") or {}).get("critical_count"))})
        return response

    @router.get("/admin/openclaw/runtimes/{runtime_id}/alerts")
    def broker_admin_openclaw_runtime_alert_detail(
        runtime_id: str,
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
        try:
            AuthService.validate_target_scope(auth_ctx, **target_scope)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        response = AdminService().get_openclaw_runtime_alerts(gw, runtime_id=runtime_id, limit=limit, **target_scope)
        audit_sensitive(gw, action="admin_openclaw_runtime_alert_detail", auth_ctx=auth_ctx, status="ok" if response.get("ok") else "error", target=runtime_id, details={"critical_count": ((response.get("summary") or {}).get("critical_count")), "warn_count": ((response.get("summary") or {}).get("warn_count"))})
        return response

    @router.get("/admin/openclaw/alert-states")
    def broker_admin_openclaw_alert_states(
        request: Request,
        runtime_id: str | None = Query(default=None),
        workflow_status: str | None = Query(default=None),
        severity: str | None = Query(default=None),
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
        response = AdminService().list_openclaw_alert_states(gw, runtime_id=runtime_id, workflow_status=workflow_status, severity=severity, limit=limit, **target_scope)
        audit_sensitive(gw, action="admin_openclaw_alert_states", auth_ctx=auth_ctx, status="ok", target=runtime_id or "all", details={"count": len(response.get("items", [])), "workflow_status": workflow_status, "severity": severity})
        return response

    @router.get("/admin/openclaw/alert-escalation-approvals")
    def broker_admin_openclaw_alert_escalation_approvals(
        request: Request,
        runtime_id: str | None = Query(default=None),
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
        response = AdminService().list_openclaw_alert_escalation_approvals(
            gw,
            runtime_id=runtime_id,
            status=status,
            limit=limit,
            **target_scope,
        )
        audit_sensitive(
            gw,
            action="admin_openclaw_alert_escalation_approvals",
            auth_ctx=auth_ctx,
            status="ok",
            target=runtime_id or "all",
            details={"count": len(response.get("items", [])), "status_filter": status},
        )
        return response

    @router.post("/admin/openclaw/alert-escalation-approvals/{approval_id}/decide")
    async def broker_admin_openclaw_alert_escalation_approval_decide(approval_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
        target_scope = {
            "tenant_id": payload.get("tenant_id") or auth_ctx.get("tenant_id"),
            "workspace_id": payload.get("workspace_id") or auth_ctx.get("workspace_id"),
            "environment": payload.get("environment") or auth_ctx.get("environment"),
        }
        try:
            AuthService.validate_target_scope(auth_ctx, **target_scope)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        response = AdminService().decide_openclaw_alert_escalation_approval(
            gw,
            approval_id=approval_id,
            actor=str(payload.get("actor") or auth_ctx.get("username") or auth_ctx.get("user_key") or "broker-admin"),
            decision=str(payload.get("decision") or payload.get("action") or "approve"),
            reason=str(payload.get("reason") or ""),
            **target_scope,
        )
        audit_sensitive(
            gw,
            action="admin_openclaw_alert_escalation_approval_decide",
            auth_ctx=auth_ctx,
            status="ok" if response.get("ok") else "error",
            target=approval_id,
            details={"decision": payload.get("decision") or payload.get("action") or "approve"},
        )
        return response

    @router.get("/admin/openclaw/runtimes/{runtime_id}/notification-targets")
    def broker_admin_openclaw_runtime_notification_targets(
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
        response = AdminService().list_openclaw_notification_targets(gw, runtime_id=runtime_id, **target_scope)
        audit_sensitive(gw, action="admin_openclaw_runtime_notification_targets", auth_ctx=auth_ctx, status="ok", target=runtime_id, details={"count": len(response.get('items', []))})
        return response

    @router.get("/admin/openclaw/alert-governance/bundles")
    def broker_admin_openclaw_alert_governance_bundles(
        request: Request,
        runtime_id: str | None = Query(default=None),
        status: str | None = Query(default=None),
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
        try:
            AuthService.validate_target_scope(auth_ctx, **target_scope)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        response = AdminService().list_openclaw_alert_governance_bundles(gw, runtime_id=runtime_id, status=status, limit=limit, **target_scope)
        audit_sensitive(gw, action="admin_openclaw_alert_governance_bundles", auth_ctx=auth_ctx, status="ok", target=runtime_id or 'all', details={"count": len(response.get('items', [])), "status": status})
        return response

    @router.post("/admin/openclaw/alert-governance/bundles")
    async def broker_admin_openclaw_alert_governance_bundle_create(request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
        target_scope = {
            "tenant_id": payload.get("tenant_id") or auth_ctx.get("tenant_id"),
            "workspace_id": payload.get("workspace_id") or auth_ctx.get("workspace_id"),
            "environment": payload.get("environment") or auth_ctx.get("environment"),
        }
        try:
            AuthService.validate_target_scope(auth_ctx, **target_scope)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        response = AdminService().create_openclaw_alert_governance_bundle(
            gw,
            name=str(payload.get('name') or 'openclaw-alert-governance-bundle'),
            version=str(payload.get('version') or f"bundle-{int(time.time())}"),
            runtime_ids=[str(item) for item in list(payload.get('runtime_ids') or [])],
            actor=str(payload.get('actor') or auth_ctx.get('user_key') or 'broker-admin'),
            candidate_policy=dict(payload.get('candidate_policy') or payload.get('policy') or {}),
            merge_with_current=bool(payload.get('merge_with_current', True)),
            waves=list(payload.get('waves') or []),
            wave_size=int(payload.get('wave_size')) if payload.get('wave_size') is not None else None,
            wave_gates=dict(payload.get('wave_gates') or {}),
            wave_timing_policy=dict(payload.get('wave_timing_policy') or payload.get('promotion_health') or {}),
            promotion_slo_policy=dict(payload.get('promotion_slo_policy') or payload.get('slo_policy') or {}),
            progressive_exposure_policy=dict(payload.get('progressive_exposure_policy') or {}),
            reason=str(payload.get('reason') or ''),
            limit=int(payload.get('limit') or 200),
            **target_scope,
        )
        audit_sensitive(gw, action="admin_openclaw_alert_governance_bundle_create", auth_ctx=auth_ctx, status="ok" if response.get('ok') else 'error', target=response.get('bundle_id') or 'new', details={"target_count": ((response.get('summary') or {}).get('target_count'))})
        return response

    @router.get("/admin/openclaw/alert-governance/bundles/{bundle_id}/analytics")
    def broker_admin_openclaw_alert_governance_bundle_analytics(
        bundle_id: str,
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
        response = AdminService().get_openclaw_alert_governance_bundle_analytics(gw, bundle_id=bundle_id, **target_scope)
        audit_sensitive(gw, action="admin_openclaw_alert_governance_bundle_analytics", auth_ctx=auth_ctx, status="ok" if response.get('ok') else 'error', target=bundle_id)
        return response

    @router.get("/admin/openclaw/alert-governance/bundles/{bundle_id}")
    def broker_admin_openclaw_alert_governance_bundle_detail(
        bundle_id: str,
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
        response = AdminService().get_openclaw_alert_governance_bundle(gw, bundle_id=bundle_id, **target_scope)
        audit_sensitive(gw, action="admin_openclaw_alert_governance_bundle_detail", auth_ctx=auth_ctx, status="ok" if response.get('ok') else 'error', target=bundle_id)
        return response

    @router.post("/admin/openclaw/alert-governance/bundles/{bundle_id}/submit")
    async def broker_admin_openclaw_alert_governance_bundle_submit(bundle_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
        target_scope = {
            "tenant_id": payload.get("tenant_id") or auth_ctx.get("tenant_id"),
            "workspace_id": payload.get("workspace_id") or auth_ctx.get("workspace_id"),
            "environment": payload.get("environment") or auth_ctx.get("environment"),
        }
        try:
            AuthService.validate_target_scope(auth_ctx, **target_scope)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        response = AdminService().submit_openclaw_alert_governance_bundle(gw, bundle_id=bundle_id, actor=str(payload.get('actor') or auth_ctx.get('user_key') or 'broker-admin'), reason=str(payload.get('reason') or ''), **target_scope)
        audit_sensitive(gw, action="admin_openclaw_alert_governance_bundle_submit", auth_ctx=auth_ctx, status="ok" if response.get('ok') else 'error', target=bundle_id)
        return response

    @router.post("/admin/openclaw/alert-governance/bundles/{bundle_id}/approve")
    async def broker_admin_openclaw_alert_governance_bundle_approve(bundle_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
        target_scope = {
            "tenant_id": payload.get("tenant_id") or auth_ctx.get("tenant_id"),
            "workspace_id": payload.get("workspace_id") or auth_ctx.get("workspace_id"),
            "environment": payload.get("environment") or auth_ctx.get("environment"),
        }
        try:
            AuthService.validate_target_scope(auth_ctx, **target_scope)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        response = AdminService().approve_openclaw_alert_governance_bundle(gw, bundle_id=bundle_id, actor=str(payload.get('actor') or auth_ctx.get('user_key') or 'broker-admin'), reason=str(payload.get('reason') or ''), **target_scope)
        audit_sensitive(gw, action="admin_openclaw_alert_governance_bundle_approve", auth_ctx=auth_ctx, status="ok" if response.get('ok') else 'error', target=bundle_id)
        return response

    @router.post("/admin/openclaw/alert-governance/bundles/{bundle_id}/waves/{wave_no}/run")
    async def broker_admin_openclaw_alert_governance_bundle_wave_run(bundle_id: str, wave_no: int, request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
        target_scope = {
            "tenant_id": payload.get("tenant_id") or auth_ctx.get("tenant_id"),
            "workspace_id": payload.get("workspace_id") or auth_ctx.get("workspace_id"),
            "environment": payload.get("environment") or auth_ctx.get("environment"),
        }
        try:
            AuthService.validate_target_scope(auth_ctx, **target_scope)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        response = AdminService().run_openclaw_alert_governance_bundle_wave(gw, bundle_id=bundle_id, wave_no=wave_no, actor=str(payload.get('actor') or auth_ctx.get('user_key') or 'broker-admin'), reason=str(payload.get('reason') or ''), limit=int(payload.get('limit') or 200), **target_scope)
        audit_sensitive(gw, action="admin_openclaw_alert_governance_bundle_wave_run", auth_ctx=auth_ctx, status="ok" if response.get('ok') else 'error', target=bundle_id, details={"wave_no": wave_no})
        return response
    @router.get("/admin/openclaw/alert-governance/baseline-catalogs")
    def broker_admin_openclaw_alert_governance_baseline_catalogs(
        request: Request,
        limit: int = Query(default=50, ge=1, le=200),
        tenant_id: Optional[str] = Query(default=None),
        workspace_id: Optional[str] = Query(default=None),
        environment: Optional[str] = Query(default=None),
    ):
        gw, auth_ctx = require_permission(request, "admin.read")
        target_scope = {
            "tenant_id": tenant_id or auth_ctx.get("tenant_id"),
            "workspace_id": workspace_id or auth_ctx.get("workspace_id"),
            "environment": environment or auth_ctx.get("environment"),
        }
        return AdminService().list_openclaw_alert_governance_baseline_catalogs(gw, limit=limit, **target_scope)

    @router.post("/admin/openclaw/alert-governance/baseline-catalogs")
    async def broker_admin_openclaw_alert_governance_baseline_catalog_create(request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
        target_scope = {
            "tenant_id": payload.get("tenant_id") or auth_ctx.get("tenant_id"),
            "workspace_id": payload.get("workspace_id") or auth_ctx.get("workspace_id"),
            "environment": payload.get("environment") or auth_ctx.get("environment"),
        }
        return AdminService().create_openclaw_alert_governance_baseline_catalog(
            gw,
            name=str(payload.get('name') or 'openclaw-baseline-catalog'),
            version=str(payload.get('version') or f'catalog-{int(time.time())}'),
            actor=str(payload.get('actor') or auth_ctx.get('user_key') or 'broker-admin'),
            environment_policy_baselines=dict(payload.get('environment_policy_baselines') or payload.get('policy_baselines') or {}),
            promotion_policy=dict(payload.get('promotion_policy') or {}),
            parent_catalog_id=payload.get('parent_catalog_id'),
            reason=str(payload.get('reason') or ''),
            **target_scope,
        )

    @router.get("/admin/openclaw/alert-governance/baseline-catalogs/{catalog_id}")
    def broker_admin_openclaw_alert_governance_baseline_catalog_detail(
        catalog_id: str,
        request: Request,
        tenant_id: Optional[str] = Query(default=None),
        workspace_id: Optional[str] = Query(default=None),
        environment: Optional[str] = Query(default=None),
    ):
        gw, auth_ctx = require_permission(request, "admin.read")
        target_scope = {
            "tenant_id": tenant_id or auth_ctx.get("tenant_id"),
            "workspace_id": workspace_id or auth_ctx.get("workspace_id"),
            "environment": environment or auth_ctx.get("environment"),
        }
        return AdminService().get_openclaw_alert_governance_baseline_catalog(gw, catalog_id=catalog_id, **target_scope)

    @router.post("/admin/openclaw/alert-governance/baseline-catalogs/{catalog_id}/promotions")
    async def broker_admin_openclaw_alert_governance_baseline_promotion_create(catalog_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
        target_scope = {
            "tenant_id": payload.get("tenant_id") or auth_ctx.get("tenant_id"),
            "workspace_id": payload.get("workspace_id") or auth_ctx.get("workspace_id"),
            "environment": payload.get("environment") or auth_ctx.get("environment"),
        }
        return AdminService().create_openclaw_alert_governance_baseline_promotion(
            gw,
            catalog_id=catalog_id,
            actor=str(payload.get('actor') or auth_ctx.get('user_key') or 'broker-admin'),
            candidate_baselines=dict(payload.get('environment_policy_baselines') or payload.get('candidate_baselines') or {}),
            version=payload.get('version'),
            rollout_policy=(dict(payload.get('rollout_policy') or {}) if 'rollout_policy' in payload else None),
            gate_policy=(dict(payload.get('gate_policy') or {}) if 'gate_policy' in payload else None),
            rollback_policy=(dict(payload.get('rollback_policy') or {}) if 'rollback_policy' in payload else None),
            reason=str(payload.get('reason') or ''),
            **target_scope,
        )

    @router.get("/admin/openclaw/alert-governance/baseline-promotions/{promotion_id}")
    async def broker_admin_openclaw_alert_governance_baseline_promotion_detail(promotion_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.read")
        target_scope = {
            "tenant_id": request.query_params.get("tenant_id") or auth_ctx.get("tenant_id"),
            "workspace_id": request.query_params.get("workspace_id") or auth_ctx.get("workspace_id"),
            "environment": request.query_params.get("environment") or auth_ctx.get("environment"),
        }
        return AdminService().get_openclaw_alert_governance_baseline_promotion(gw, promotion_id=promotion_id, **target_scope)

    @router.get("/admin/openclaw/alert-governance/baseline-promotions/{promotion_id}/timeline")
    async def broker_admin_openclaw_alert_governance_baseline_promotion_timeline(promotion_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.read")
        try:
            limit = int(request.query_params.get('limit') or 200)
        except Exception:
            limit = 200
        target_scope = {
            "tenant_id": request.query_params.get("tenant_id") or auth_ctx.get("tenant_id"),
            "workspace_id": request.query_params.get("workspace_id") or auth_ctx.get("workspace_id"),
            "environment": request.query_params.get("environment") or auth_ctx.get("environment"),
        }
        return AdminService().get_openclaw_alert_governance_baseline_promotion_timeline(gw, promotion_id=promotion_id, limit=limit, **target_scope)

    @router.post("/admin/openclaw/alert-governance/baseline-promotions/{promotion_id}/attestation-export")
    async def admin_openclaw_alert_governance_baseline_promotion_attestation_export(promotion_id: str, request: Request):
        payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
        gw = _require_admin(request)
        response = _ADMIN_SERVICE.export_openclaw_alert_governance_baseline_promotion_attestation(
            gw,
            promotion_id=promotion_id,
            actor=str(payload.get('actor') or 'admin'),
            timeline_limit=int(payload.get('timeline_limit')) if payload.get('timeline_limit') is not None else None,
            tenant_id=payload.get('tenant_id'),
            workspace_id=payload.get('workspace_id'),
            environment=payload.get('environment'),
        )
        _audit_admin(gw, 'openclaw_alert_governance_baseline_promotion_attestation_export', {'promotion_id': promotion_id, 'ok': response.get('ok')})
        return response

    @router.post("/admin/openclaw/alert-governance/baseline-promotions/{promotion_id}/postmortem-export")
    async def admin_openclaw_alert_governance_baseline_promotion_postmortem_export(promotion_id: str, request: Request):
        payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
        gw = _require_admin(request)
        response = _ADMIN_SERVICE.export_openclaw_alert_governance_baseline_promotion_postmortem(
            gw,
            promotion_id=promotion_id,
            actor=str(payload.get('actor') or 'admin'),
            timeline_limit=int(payload.get('timeline_limit')) if payload.get('timeline_limit') is not None else None,
            tenant_id=payload.get('tenant_id'),
            workspace_id=payload.get('workspace_id'),
            environment=payload.get('environment'),
        )
        _audit_admin(gw, 'openclaw_alert_governance_baseline_promotion_postmortem_export', {'promotion_id': promotion_id, 'ok': response.get('ok')})
        return response

    @router.post("/admin/openclaw/alert-governance/baseline-promotions/{promotion_id}/actions/{action}")
    async def broker_admin_openclaw_alert_governance_baseline_promotion_action(promotion_id: str, action: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
        target_scope = {
            "tenant_id": payload.get("tenant_id") or auth_ctx.get("tenant_id"),
            "workspace_id": payload.get("workspace_id") or auth_ctx.get("workspace_id"),
            "environment": payload.get("environment") or auth_ctx.get("environment"),
        }
        normalized_action = str(action or '').strip().lower()
        if normalized_action not in {'approve', 'reject', 'advance', 'rollback', 'pause', 'resume'}:
            return {'ok': False, 'error': 'unsupported_action', 'action': normalized_action, 'promotion_id': promotion_id}
        return AdminService().decide_openclaw_alert_governance_baseline_promotion(
            gw,
            promotion_id=promotion_id,
            actor=str(payload.get('actor') or auth_ctx.get('user_key') or 'broker-admin'),
            decision=normalized_action,
            reason=str(payload.get('reason') or ''),
            **target_scope,
        )

    @router.get("/admin/openclaw/alert-governance/baseline-advance-jobs")
    def broker_admin_openclaw_alert_governance_baseline_advance_jobs(
        request: Request,
        limit: int = Query(default=100, ge=1, le=200),
        promotion_id: Optional[str] = Query(default=None),
        tenant_id: Optional[str] = Query(default=None),
        workspace_id: Optional[str] = Query(default=None),
        environment: Optional[str] = Query(default=None),
    ):
        gw, auth_ctx = require_permission(request, "admin.read")
        target_scope = {
            "tenant_id": tenant_id or auth_ctx.get("tenant_id"),
            "workspace_id": workspace_id or auth_ctx.get("workspace_id"),
            "environment": environment or auth_ctx.get("environment"),
        }
        return AdminService().list_openclaw_alert_governance_baseline_advance_jobs(gw, limit=limit, promotion_id=promotion_id, **target_scope)

    @router.post("/admin/openclaw/alert-governance/baseline-advance-jobs/run-due")
    async def broker_admin_openclaw_alert_governance_baseline_advance_jobs_run_due(request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
        target_scope = {
            "tenant_id": payload.get("tenant_id") or auth_ctx.get("tenant_id"),
            "workspace_id": payload.get("workspace_id") or auth_ctx.get("workspace_id"),
            "environment": payload.get("environment") or auth_ctx.get("environment"),
        }
        return AdminService().run_due_openclaw_alert_governance_baseline_advance_jobs(
            gw,
            actor=str(payload.get('actor') or auth_ctx.get('user_key') or 'broker-admin'),
            limit=int(payload.get('limit') or 20),
            promotion_id=payload.get('promotion_id'),
            **target_scope,
        )

    @router.get("/admin/openclaw/alert-governance/portfolios")
    def admin_openclaw_alert_governance_portfolios(
        request: Request,
        runtime_id: Optional[str] = Query(default=None),
        status: Optional[str] = Query(default=None),
        limit: int = Query(default=50, ge=1, le=200),
        tenant_id: Optional[str] = Query(default=None),
        workspace_id: Optional[str] = Query(default=None),
        environment: Optional[str] = Query(default=None),
    ):
        gw = _require_admin(request)
        response = _ADMIN_SERVICE.list_openclaw_alert_governance_portfolios(gw, runtime_id=runtime_id, status=status, limit=limit, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        _audit_admin(gw, 'openclaw_alert_governance_portfolios', {'count': len(response.get('items', [])), 'runtime_id': runtime_id, 'status': status})
        return response


    @router.post("/admin/openclaw/alert-governance/portfolios")
    async def admin_openclaw_alert_governance_portfolio_create(request: Request):
        payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
        gw = _require_admin(request)
        train_policy = dict(payload.get('train_policy') or {})
        for extra_key in ('freeze_windows', 'blackout_windows', 'dependency_graph', 'approval_policy', 'security_gate_policy', 'drift_policy', 'export_policy', 'notarization_policy', 'retention_policy', 'escrow_policy', 'signing_policy', 'chain_of_custody_policy', 'custody_anchor_policy', 'verification_gate_policy', 'environment_tier_policies', 'environment_envelopes', 'environment_policy_baselines', 'policy_baselines', 'baseline_catalog_ref', 'baseline_catalog_reference', 'baseline_catalog_overrides', 'deviation_management_policy', 'deviation_policy', 'strict_conflict_check', 'auto_reschedule', 'spacing_s', 'base_release_at', 'default_event_window_s', 'reschedule_buffer_s', 'default_timezone', 'rollout_timezone'):
            if extra_key in payload and payload.get(extra_key) is not None:
                train_policy[extra_key] = payload.get(extra_key)
        response = _ADMIN_SERVICE.create_openclaw_alert_governance_portfolio(
            gw,
            name=str(payload.get('name') or 'openclaw-alert-governance-portfolio'),
            version=str(payload.get('version') or f"portfolio-{int(time.time())}"),
            bundle_ids=[str(item) for item in list(payload.get('bundle_ids') or [])],
            actor=str(payload.get('actor') or 'admin'),
            train_calendar=list(payload.get('train_calendar') or []),
            train_policy=train_policy,
            reason=str(payload.get('reason') or ''),
            tenant_id=payload.get('tenant_id'),
            workspace_id=payload.get('workspace_id'),
            environment=payload.get('environment'),
        )
        _audit_admin(gw, 'openclaw_alert_governance_portfolio_create', {'ok': response.get('ok'), 'portfolio_id': response.get('portfolio_id'), 'bundle_count': ((response.get('summary') or {}).get('bundle_count'))})
        return response


    @router.get("/admin/openclaw/alert-governance/portfolios/{portfolio_id}")
    def admin_openclaw_alert_governance_portfolio_detail(
        portfolio_id: str,
        request: Request,
        tenant_id: Optional[str] = Query(default=None),
        workspace_id: Optional[str] = Query(default=None),
        environment: Optional[str] = Query(default=None),
    ):
        gw = _require_admin(request)
        response = _ADMIN_SERVICE.get_openclaw_alert_governance_portfolio(gw, portfolio_id=portfolio_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        _audit_admin(gw, 'openclaw_alert_governance_portfolio_detail', {'portfolio_id': portfolio_id, 'ok': response.get('ok')})
        return response


    @router.post("/admin/openclaw/alert-governance/portfolios/{portfolio_id}/submit")
    async def admin_openclaw_alert_governance_portfolio_submit(portfolio_id: str, request: Request):
        payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
        gw = _require_admin(request)
        response = _ADMIN_SERVICE.submit_openclaw_alert_governance_portfolio(
            gw,
            portfolio_id=portfolio_id,
            actor=str(payload.get('actor') or 'admin'),
            reason=str(payload.get('reason') or ''),
            tenant_id=payload.get('tenant_id'),
            workspace_id=payload.get('workspace_id'),
            environment=payload.get('environment'),
        )
        _audit_admin(gw, 'openclaw_alert_governance_portfolio_submit', {'portfolio_id': portfolio_id, 'ok': response.get('ok'), 'release_status': ((response.get('release') or {}).get('status'))})
        return response


    @router.post("/admin/openclaw/alert-governance/portfolios/{portfolio_id}/approve")
    async def admin_openclaw_alert_governance_portfolio_approve(portfolio_id: str, request: Request):
        payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
        gw = _require_admin(request)
        response = _ADMIN_SERVICE.approve_openclaw_alert_governance_portfolio(
            gw,
            portfolio_id=portfolio_id,
            actor=str(payload.get('actor') or 'admin'),
            reason=str(payload.get('reason') or ''),
            tenant_id=payload.get('tenant_id'),
            workspace_id=payload.get('workspace_id'),
            environment=payload.get('environment'),
        )
        _audit_admin(gw, 'openclaw_alert_governance_portfolio_approve', {'portfolio_id': portfolio_id, 'ok': response.get('ok'), 'release_status': ((response.get('release') or {}).get('status'))})
        return response


    @router.get("/admin/openclaw/alert-governance/portfolios/{portfolio_id}/calendar")
    def admin_openclaw_alert_governance_portfolio_calendar(
        portfolio_id: str,
        request: Request,
        tenant_id: Optional[str] = Query(default=None),
        workspace_id: Optional[str] = Query(default=None),
        environment: Optional[str] = Query(default=None),
    ):
        gw = _require_admin(request)
        response = _ADMIN_SERVICE.get_openclaw_alert_governance_portfolio_calendar(gw, portfolio_id=portfolio_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        _audit_admin(gw, 'openclaw_alert_governance_portfolio_calendar', {'portfolio_id': portfolio_id, 'ok': response.get('ok'), 'count': (((response.get('calendar') or {}).get('summary') or {}).get('count'))})
        return response


    @router.post("/admin/openclaw/alert-governance/portfolios/{portfolio_id}/simulate")
    async def admin_openclaw_alert_governance_portfolio_simulate(portfolio_id: str, request: Request):
        payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
        gw = _require_admin(request)
        response = _ADMIN_SERVICE.simulate_openclaw_alert_governance_portfolio(
            gw,
            portfolio_id=portfolio_id,
            actor=str(payload.get('actor') or 'admin'),
            now_ts=float(payload.get('now_ts')) if payload.get('now_ts') is not None else None,
            dry_run=bool(payload.get('dry_run', True)),
            auto_reschedule=bool(payload.get('auto_reschedule')) if payload.get('auto_reschedule') is not None else None,
            persist_schedule=bool(payload.get('persist_schedule', False)),
            tenant_id=payload.get('tenant_id'),
            workspace_id=payload.get('workspace_id'),
            environment=payload.get('environment'),
        )
        _audit_admin(gw, 'openclaw_alert_governance_portfolio_simulate', {'portfolio_id': portfolio_id, 'ok': response.get('ok'), 'validation_status': ((response.get('simulation') or {}).get('validation_status'))})
        return response


    @router.get("/admin/openclaw/alert-governance/portfolios/{portfolio_id}/chain-of-custody")
    def admin_openclaw_alert_governance_portfolio_chain_of_custody(
        portfolio_id: str,
        request: Request,
        tenant_id: Optional[str] = Query(default=None),
        workspace_id: Optional[str] = Query(default=None),
        environment: Optional[str] = Query(default=None),
    ):
        gw = _require_admin(request)
        response = _ADMIN_SERVICE.list_openclaw_alert_governance_portfolio_chain_of_custody(gw, portfolio_id=portfolio_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        _audit_admin(gw, 'openclaw_alert_governance_portfolio_chain_of_custody', {'portfolio_id': portfolio_id, 'count': len(((response.get('chain_of_custody') or {}).get('items') or []))})
        return response


    @router.get("/admin/openclaw/alert-governance/portfolios/{portfolio_id}/custody-anchors")
    def admin_openclaw_alert_governance_portfolio_custody_anchors(
        portfolio_id: str,
        request: Request,
        tenant_id: Optional[str] = Query(default=None),
        workspace_id: Optional[str] = Query(default=None),
        environment: Optional[str] = Query(default=None),
    ):
        gw = _require_admin(request)
        response = _ADMIN_SERVICE.list_openclaw_alert_governance_portfolio_custody_anchors(gw, portfolio_id=portfolio_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        _audit_admin(gw, 'openclaw_alert_governance_portfolio_custody_anchors', {'portfolio_id': portfolio_id, 'count': len(((response.get('custody_anchors') or {}).get('items') or []))})
        return response


    @router.post("/admin/openclaw/alert-governance/portfolios/{portfolio_id}/custody-anchors/reconcile")
    async def admin_openclaw_alert_governance_portfolio_custody_anchors_reconcile(portfolio_id: str, request: Request):
        payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
        gw = _require_admin(request)
        response = _ADMIN_SERVICE.reconcile_openclaw_alert_governance_portfolio_custody_anchors(
            gw,
            portfolio_id=portfolio_id,
            actor=str(payload.get('actor') or 'admin'),
            tenant_id=payload.get('tenant_id'),
            workspace_id=payload.get('workspace_id'),
            environment=payload.get('environment'),
        )
        _audit_admin(gw, 'openclaw_alert_governance_portfolio_custody_anchors_reconcile', {'portfolio_id': portfolio_id, 'ok': response.get('ok'), 'status': ((response.get('reconciliation') or {}).get('status'))})
        return response


    @router.get("/admin/openclaw/alert-governance/portfolios/{portfolio_id}/policy-conformance")
    def broker_admin_openclaw_alert_governance_portfolio_policy_conformance(
        portfolio_id: str,
        request: Request,
        actor: Optional[str] = Query(default='system'),
        persist_metadata: bool = Query(default=True),
        tenant_id: Optional[str] = Query(default=None),
        workspace_id: Optional[str] = Query(default=None),
        environment: Optional[str] = Query(default=None),
    ):
        gw = _require_broker_admin(request)
        return _ADMIN_SERVICE.get_openclaw_alert_governance_portfolio_policy_conformance(
            gw,
            portfolio_id=portfolio_id,
            actor=str(actor or 'system'),
            persist_metadata=bool(persist_metadata),
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    @router.get("/admin/openclaw/alert-governance/portfolios/{portfolio_id}/policy-baseline-drift")
    def broker_admin_openclaw_alert_governance_portfolio_policy_baseline_drift(
        portfolio_id: str,
        request: Request,
        actor: str | None = Query(default='system'),
        persist_metadata: bool = Query(default=True),
        tenant_id: str | None = Query(default=None),
        workspace_id: str | None = Query(default=None),
        environment: str | None = Query(default=None),
    ):
        gw = _require_broker_admin(request)
        return _ADMIN_SERVICE.get_openclaw_alert_governance_portfolio_policy_baseline_drift(
            gw,
            portfolio_id=portfolio_id,
            actor=str(actor or 'system'),
            persist_metadata=bool(persist_metadata),
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    @router.get("/admin/openclaw/alert-governance/portfolios/{portfolio_id}/deviation-exceptions")
    def broker_admin_openclaw_alert_governance_portfolio_deviation_exceptions(
        portfolio_id: str,
        request: Request,
        tenant_id: str | None = Query(default=None),
        workspace_id: str | None = Query(default=None),
        environment: str | None = Query(default=None),
    ):
        gw = _require_broker_admin(request)
        return _ADMIN_SERVICE.list_openclaw_alert_governance_portfolio_policy_deviation_exceptions(
            gw,
            portfolio_id=portfolio_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    @router.post("/admin/openclaw/alert-governance/portfolios/{portfolio_id}/deviation-exceptions")
    async def broker_admin_openclaw_alert_governance_portfolio_deviation_exception_request(portfolio_id: str, request: Request):
        payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
        gw = _require_broker_admin(request)
        return _ADMIN_SERVICE.request_openclaw_alert_governance_portfolio_policy_deviation_exception(
            gw,
            portfolio_id=portfolio_id,
            deviation_id=str(payload.get('deviation_id') or ''),
            actor=str(payload.get('actor') or 'admin'),
            reason=str(payload.get('reason') or ''),
            ttl_s=payload.get('ttl_s'),
            tenant_id=payload.get('tenant_id'),
            workspace_id=payload.get('workspace_id'),
            environment=payload.get('environment'),
        )

    @router.post("/admin/openclaw/alert-governance/portfolio-deviation-approvals/{approval_id}/actions/{action}")
    async def broker_admin_openclaw_alert_governance_portfolio_deviation_approval_action(approval_id: str, action: str, request: Request):
        payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
        normalized_action = str(action or '').strip().lower()
        if normalized_action not in {'approve', 'reject'}:
            return {'ok': False, 'error': 'unsupported_action', 'action': normalized_action, 'approval_id': approval_id}
        gw = _require_broker_admin(request)
        return _ADMIN_SERVICE.decide_openclaw_alert_governance_portfolio_policy_deviation_exception(
            gw,
            approval_id=approval_id,
            actor=str(payload.get('actor') or 'admin'),
            decision=normalized_action,
            reason=str(payload.get('reason') or ''),
            tenant_id=payload.get('tenant_id'),
            workspace_id=payload.get('workspace_id'),
            environment=payload.get('environment'),
        )

    @router.post("/admin/openclaw/alert-governance/portfolios/{portfolio_id}/provider-validation")
    async def admin_openclaw_alert_governance_portfolio_provider_validation(portfolio_id: str, request: Request):
        payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
        gw = _require_admin(request)
        response = _ADMIN_SERVICE.validate_openclaw_alert_governance_portfolio_provider_integrations(
            gw,
            portfolio_id=portfolio_id,
            actor=str(payload.get('actor') or 'admin'),
            tenant_id=payload.get('tenant_id'),
            workspace_id=payload.get('workspace_id'),
            environment=payload.get('environment'),
        )
        _audit_admin(gw, 'openclaw_alert_governance_portfolio_provider_validation', {'portfolio_id': portfolio_id, 'ok': response.get('ok'), 'valid': response.get('valid')})
        return response


    @router.post("/admin/openclaw/alert-governance/portfolios/{portfolio_id}/custody-anchors/attest")
    async def admin_openclaw_alert_governance_portfolio_custody_anchors_attest(portfolio_id: str, request: Request):
        payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
        gw = _require_admin(request)
        response = _ADMIN_SERVICE.attest_openclaw_alert_governance_portfolio_custody_anchor(
            gw,
            portfolio_id=portfolio_id,
            actor=str(payload.get('actor') or 'admin'),
            package_id=payload.get('package_id'),
            control_plane_id=payload.get('control_plane_id'),
            tenant_id=payload.get('tenant_id'),
            workspace_id=payload.get('workspace_id'),
            environment=payload.get('environment'),
        )
        _audit_admin(gw, 'openclaw_alert_governance_portfolio_custody_anchors_attest', {'portfolio_id': portfolio_id, 'ok': response.get('ok'), 'package_id': response.get('package_id')})
        return response


    @router.get("/admin/openclaw/alert-governance/portfolios/{portfolio_id}/attestations")
    def admin_openclaw_alert_governance_portfolio_attestations(
        portfolio_id: str,
        request: Request,
        tenant_id: Optional[str] = Query(default=None),
        workspace_id: Optional[str] = Query(default=None),
        environment: Optional[str] = Query(default=None),
    ):
        gw = _require_admin(request)
        response = _ADMIN_SERVICE.list_openclaw_alert_governance_portfolio_attestations(gw, portfolio_id=portfolio_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        _audit_admin(gw, 'openclaw_alert_governance_portfolio_attestations', {'portfolio_id': portfolio_id, 'count': len(((response.get('attestations') or {}).get('items') or []))})
        return response


    @router.get("/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-packages")
    def admin_openclaw_alert_governance_portfolio_evidence_packages(
        portfolio_id: str,
        request: Request,
        tenant_id: Optional[str] = Query(default=None),
        workspace_id: Optional[str] = Query(default=None),
        environment: Optional[str] = Query(default=None),
    ):
        gw = _require_admin(request)
        response = _ADMIN_SERVICE.list_openclaw_alert_governance_portfolio_evidence_packages(gw, portfolio_id=portfolio_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        _audit_admin(gw, 'openclaw_alert_governance_portfolio_evidence_packages', {'portfolio_id': portfolio_id, 'count': len(((response.get('evidence_packages') or {}).get('items') or []))})
        return response


    @router.post("/admin/openclaw/alert-governance/portfolios/{portfolio_id}/drift-detect")
    async def admin_openclaw_alert_governance_portfolio_drift_detect(portfolio_id: str, request: Request):
        payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
        gw = _require_admin(request)
        response = _ADMIN_SERVICE.detect_openclaw_alert_governance_portfolio_drift(
            gw,
            portfolio_id=portfolio_id,
            actor=str(payload.get('actor') or 'admin'),
            tenant_id=payload.get('tenant_id'),
            workspace_id=payload.get('workspace_id'),
            environment=payload.get('environment'),
            persist_metadata=bool(payload.get('persist_metadata', True)),
        )
        _audit_admin(gw, 'openclaw_alert_governance_portfolio_drift_detect', {'portfolio_id': portfolio_id, 'ok': response.get('ok'), 'overall_status': ((response.get('drift') or {}).get('overall_status'))})
        return response


    @router.post("/admin/openclaw/alert-governance/portfolios/{portfolio_id}/attestation-export")
    async def admin_openclaw_alert_governance_portfolio_attestation_export(portfolio_id: str, request: Request):
        payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
        gw = _require_admin(request)
        response = _ADMIN_SERVICE.export_openclaw_alert_governance_portfolio_attestation(
            gw,
            portfolio_id=portfolio_id,
            actor=str(payload.get('actor') or 'admin'),
            attestation_id=payload.get('attestation_id'),
            tenant_id=payload.get('tenant_id'),
            workspace_id=payload.get('workspace_id'),
            environment=payload.get('environment'),
        )
        _audit_admin(gw, 'openclaw_alert_governance_portfolio_attestation_export', {'portfolio_id': portfolio_id, 'ok': response.get('ok'), 'attestation_id': response.get('attestation_id')})
        return response


    @router.post("/admin/openclaw/alert-governance/portfolios/{portfolio_id}/postmortem-export")
    async def admin_openclaw_alert_governance_portfolio_postmortem_export(portfolio_id: str, request: Request):
        payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
        gw = _require_admin(request)
        response = _ADMIN_SERVICE.export_openclaw_alert_governance_portfolio_postmortem(
            gw,
            portfolio_id=portfolio_id,
            actor=str(payload.get('actor') or 'admin'),
            attestation_id=payload.get('attestation_id'),
            timeline_limit=int(payload.get('timeline_limit')) if payload.get('timeline_limit') is not None else None,
            tenant_id=payload.get('tenant_id'),
            workspace_id=payload.get('workspace_id'),
            environment=payload.get('environment'),
        )
        _audit_admin(gw, 'openclaw_alert_governance_portfolio_postmortem_export', {'portfolio_id': portfolio_id, 'ok': response.get('ok'), 'attestation_id': response.get('attestation_id')})
        return response


    @router.post("/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-package-export")
    async def admin_openclaw_alert_governance_portfolio_evidence_package_export(portfolio_id: str, request: Request):
        payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
        gw = _require_admin(request)
        response = _ADMIN_SERVICE.export_openclaw_alert_governance_portfolio_evidence_package(
            gw,
            portfolio_id=portfolio_id,
            actor=str(payload.get('actor') or 'admin'),
            attestation_id=payload.get('attestation_id'),
            timeline_limit=int(payload.get('timeline_limit')) if payload.get('timeline_limit') is not None else None,
            tenant_id=payload.get('tenant_id'),
            workspace_id=payload.get('workspace_id'),
            environment=payload.get('environment'),
        )
        _audit_admin(gw, 'openclaw_alert_governance_portfolio_evidence_package_export', {'portfolio_id': portfolio_id, 'ok': response.get('ok'), 'package_id': response.get('package_id')})
        return response


    @router.post("/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-packages/prune")
    async def admin_openclaw_alert_governance_portfolio_evidence_package_prune(portfolio_id: str, request: Request):
        payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
        gw = _require_admin(request)
        response = _ADMIN_SERVICE.prune_openclaw_alert_governance_portfolio_evidence_packages(
            gw,
            portfolio_id=portfolio_id,
            actor=str(payload.get('actor') or 'admin'),
            tenant_id=payload.get('tenant_id'),
            workspace_id=payload.get('workspace_id'),
            environment=payload.get('environment'),
        )
        _audit_admin(gw, 'openclaw_alert_governance_portfolio_evidence_package_prune', {'portfolio_id': portfolio_id, 'ok': response.get('ok'), 'removed_count': (((response.get('prune') or {}).get('summary') or {}).get('removed_count'))})
        return response


    @router.post("/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-artifact-verify")
    async def admin_openclaw_alert_governance_portfolio_evidence_artifact_verify(portfolio_id: str, request: Request):
        payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
        gw = _require_admin(request)
        response = _ADMIN_SERVICE.verify_openclaw_alert_governance_portfolio_evidence_artifact(
            gw,
            portfolio_id=portfolio_id,
            actor=str(payload.get('actor') or 'admin'),
            package_id=payload.get('package_id'),
            artifact=payload.get('artifact'),
            artifact_b64=payload.get('artifact_b64'),
            tenant_id=payload.get('tenant_id'),
            workspace_id=payload.get('workspace_id'),
            environment=payload.get('environment'),
        )
        _audit_admin(gw, 'openclaw_alert_governance_portfolio_evidence_artifact_verify', {'portfolio_id': portfolio_id, 'ok': response.get('ok'), 'package_id': response.get('package_id'), 'verification_status': ((response.get('verification') or {}).get('status'))})
        return response


    @router.post("/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-artifact-restore")
    async def admin_openclaw_alert_governance_portfolio_evidence_artifact_restore(portfolio_id: str, request: Request):
        payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
        gw = _require_admin(request)
        response = _ADMIN_SERVICE.restore_openclaw_alert_governance_portfolio_evidence_artifact(
            gw,
            portfolio_id=portfolio_id,
            actor=str(payload.get('actor') or 'admin'),
            package_id=payload.get('package_id'),
            artifact=payload.get('artifact'),
            artifact_b64=payload.get('artifact_b64'),
            persist_restore_session=bool(payload.get('persist_restore_session', False)),
            tenant_id=payload.get('tenant_id'),
            workspace_id=payload.get('workspace_id'),
            environment=payload.get('environment'),
        )
        _audit_admin(gw, 'openclaw_alert_governance_portfolio_evidence_artifact_restore', {'portfolio_id': portfolio_id, 'ok': response.get('ok'), 'package_id': response.get('package_id'), 'restore_id': (((response.get('restore') or {}).get('restore_session') or {}).get('restore_id'))})
        return response


    @router.get("/admin/openclaw/alert-governance/portfolios/{portfolio_id}/approvals")
    def admin_openclaw_alert_governance_portfolio_approvals(
        portfolio_id: str,
        request: Request,
        status: Optional[str] = Query(default=None),
        limit: int = Query(default=100, ge=1, le=300),
        tenant_id: Optional[str] = Query(default=None),
        workspace_id: Optional[str] = Query(default=None),
        environment: Optional[str] = Query(default=None),
    ):
        gw = _require_admin(request)
        response = _ADMIN_SERVICE.list_openclaw_alert_governance_portfolio_approvals(gw, portfolio_id=portfolio_id, status=status, limit=limit, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        _audit_admin(gw, 'openclaw_alert_governance_portfolio_approvals', {'portfolio_id': portfolio_id, 'count': len(response.get('items', [])), 'status': status})
        return response


    @router.post("/admin/openclaw/alert-governance/portfolio-approvals/{approval_id}/actions/{action}")
    async def admin_openclaw_alert_governance_portfolio_approval_action(approval_id: str, action: str, request: Request):
        payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
        gw = _require_admin(request)
        normalized_action = str(action or '').strip().lower()
        if normalized_action not in {'approve', 'reject'}:
            return {'ok': False, 'error': 'unsupported_action', 'action': normalized_action, 'approval_id': approval_id}
        response = _ADMIN_SERVICE.decide_openclaw_alert_governance_portfolio_approval(
            gw,
            approval_id=approval_id,
            actor=str(payload.get('actor') or 'admin'),
            decision=normalized_action,
            reason=str(payload.get('reason') or ''),
            tenant_id=payload.get('tenant_id'),
            workspace_id=payload.get('workspace_id'),
            environment=payload.get('environment'),
        )
        _audit_admin(gw, 'openclaw_alert_governance_portfolio_approval_action', {'approval_id': approval_id, 'action': normalized_action, 'ok': response.get('ok')})
        return response


    @router.get("/admin/openclaw/alert-governance/release-train-jobs")
    def admin_openclaw_alert_governance_release_train_jobs(
        request: Request,
        portfolio_id: Optional[str] = Query(default=None),
        limit: int = Query(default=100, ge=1, le=300),
        tenant_id: Optional[str] = Query(default=None),
        workspace_id: Optional[str] = Query(default=None),
        environment: Optional[str] = Query(default=None),
    ):
        gw = _require_admin(request)
        response = _ADMIN_SERVICE.list_openclaw_release_train_jobs(gw, portfolio_id=portfolio_id, limit=limit, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        _audit_admin(gw, 'openclaw_alert_governance_release_train_jobs', {'count': len(response.get('items', [])), 'portfolio_id': portfolio_id})
        return response


    @router.post("/admin/openclaw/alert-governance/release-train-jobs/run-due")
    async def admin_openclaw_alert_governance_release_train_jobs_run_due(request: Request):
        payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
        gw = _require_admin(request)
        response = _ADMIN_SERVICE.run_due_openclaw_release_train_jobs(
            gw,
            actor=str(payload.get('actor') or 'system'),
            limit=int(payload.get('limit') or 20),
            portfolio_id=payload.get('portfolio_id'),
            tenant_id=payload.get('tenant_id'),
            workspace_id=payload.get('workspace_id'),
            environment=payload.get('environment'),
        )
        _audit_admin(gw, 'openclaw_alert_governance_release_train_jobs_run_due', {'count': len(response.get('items', [])), 'portfolio_id': payload.get('portfolio_id')})
        return response




    @router.get("/admin/openclaw/alert-governance/advance-jobs")
    def broker_admin_openclaw_alert_governance_advance_jobs(
        request: Request,
        bundle_id: str | None = Query(default=None),
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
        response = AdminService().list_openclaw_alert_governance_advance_jobs(gw, bundle_id=bundle_id, limit=limit, **target_scope)
        audit_sensitive(gw, action="admin_openclaw_alert_governance_advance_jobs", auth_ctx=auth_ctx, status="ok", target=bundle_id or 'all', details={"count": len(response.get('items', []))})
        return response

    @router.post("/admin/openclaw/alert-governance/advance-jobs/run-due")
    async def broker_admin_openclaw_alert_governance_advance_jobs_run_due(request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
        target_scope = {
            "tenant_id": payload.get("tenant_id") or auth_ctx.get("tenant_id"),
            "workspace_id": payload.get("workspace_id") or auth_ctx.get("workspace_id"),
            "environment": payload.get("environment") or auth_ctx.get("environment"),
        }
        try:
            AuthService.validate_target_scope(auth_ctx, **target_scope)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        response = AdminService().run_due_openclaw_alert_governance_advance_jobs(gw, actor=str(payload.get('actor') or auth_ctx.get('user_key') or 'broker-admin'), limit=int(payload.get('limit') or 20), bundle_id=str(payload.get('bundle_id') or '') or None, **target_scope)
        audit_sensitive(gw, action="admin_openclaw_alert_governance_advance_jobs_run_due", auth_ctx=auth_ctx, status="ok" if response.get('ok') else 'error', target=payload.get('bundle_id') or 'all', details={"executed": ((response.get('summary') or {}).get('executed'))})
        return response

    @router.get("/admin/openclaw/alert-governance-promotion-approvals")
    def broker_admin_openclaw_alert_governance_promotion_approvals(
        request: Request,
        runtime_id: str | None = Query(default=None),
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
        response = AdminService().list_openclaw_alert_governance_promotion_approvals(
            gw,
            runtime_id=runtime_id,
            status=status,
            limit=limit,
            **target_scope,
        )
        audit_sensitive(gw, action="admin_openclaw_alert_governance_promotion_approvals", auth_ctx=auth_ctx, status="ok", target=runtime_id or "all", details={"count": len(response.get("items", [])), "status_filter": status})
        return response

    @router.post("/admin/openclaw/alert-governance-promotion-approvals/{approval_id}/decide")
    async def broker_admin_openclaw_alert_governance_promotion_approval_decide(approval_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
        target_scope = {
            "tenant_id": payload.get("tenant_id") or auth_ctx.get("tenant_id"),
            "workspace_id": payload.get("workspace_id") or auth_ctx.get("workspace_id"),
            "environment": payload.get("environment") or auth_ctx.get("environment"),
        }
        try:
            AuthService.validate_target_scope(auth_ctx, **target_scope)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        response = AdminService().decide_openclaw_alert_governance_promotion_approval(
            gw,
            approval_id=approval_id,
            actor=str(payload.get("actor") or auth_ctx.get("username") or auth_ctx.get("user_key") or "broker-admin"),
            decision=str(payload.get("decision") or payload.get("action") or "approve"),
            reason=str(payload.get("reason") or ""),
            **target_scope,
        )
        audit_sensitive(gw, action="admin_openclaw_alert_governance_promotion_approval_decide", auth_ctx=auth_ctx, status="ok" if response.get("ok") else "error", target=approval_id, details={"decision": payload.get("decision") or payload.get("action") or "approve"})
        return response

    @router.get("/admin/openclaw/runtimes/{runtime_id}/alert-governance")
    def broker_admin_openclaw_runtime_alert_governance(
        runtime_id: str,
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
        try:
            AuthService.validate_target_scope(auth_ctx, **target_scope)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        response = AdminService().get_openclaw_alert_governance(gw, runtime_id=runtime_id, limit=limit, **target_scope)
        audit_sensitive(gw, action="admin_openclaw_runtime_alert_governance", auth_ctx=auth_ctx, status="ok" if response.get("ok") else "error", target=runtime_id, details={"suppressed_alert_count": ((response.get('summary') or {}).get('suppressed_alert_count')), "active_override_count": ((response.get('summary') or {}).get('active_override_count'))})
        return response

    @router.post("/admin/openclaw/runtimes/{runtime_id}/alert-governance/simulate")
    async def broker_admin_openclaw_runtime_alert_governance_simulate(runtime_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
        target_scope = {
            "tenant_id": payload.get("tenant_id") or auth_ctx.get("tenant_id"),
            "workspace_id": payload.get("workspace_id") or auth_ctx.get("workspace_id"),
            "environment": payload.get("environment") or auth_ctx.get("environment"),
        }
        try:
            AuthService.validate_target_scope(auth_ctx, **target_scope)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        response = AdminService().simulate_openclaw_alert_governance(
            gw,
            runtime_id=runtime_id,
            candidate_policy=dict(payload.get('candidate_policy') or payload.get('policy') or {}),
            merge_with_current=bool(payload.get('merge_with_current', True)),
            alert_code=(str(payload.get('alert_code') or '').strip() or None),
            include_unchanged=bool(payload.get('include_unchanged', True)),
            limit=int(payload.get('limit') or 200),
            now_ts=float(payload.get('now_ts')) if payload.get('now_ts') is not None else None,
            **target_scope,
        )
        audit_sensitive(gw, action="admin_openclaw_runtime_alert_governance_simulate", auth_ctx=auth_ctx, status="ok" if response.get("ok") else "error", target=runtime_id, details={"affected_count": ((response.get('summary') or {}).get('affected_count')), "mode": response.get('mode')})
        return response

    @router.get("/admin/openclaw/runtimes/{runtime_id}/alert-governance/versions")
    def broker_admin_openclaw_runtime_alert_governance_versions(
        runtime_id: str,
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
        try:
            AuthService.validate_target_scope(auth_ctx, **target_scope)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        response = AdminService().list_openclaw_alert_governance_versions(gw, runtime_id=runtime_id, limit=limit, status=status, **target_scope)
        audit_sensitive(gw, action="admin_openclaw_runtime_alert_governance_versions", auth_ctx=auth_ctx, status="ok", target=runtime_id, details={"count": len(response.get('items', [])), "status": status})
        return response

    @router.post("/admin/openclaw/runtimes/{runtime_id}/alert-governance/activate")
    async def broker_admin_openclaw_runtime_alert_governance_activate(runtime_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
        target_scope = {
            "tenant_id": payload.get("tenant_id") or auth_ctx.get("tenant_id"),
            "workspace_id": payload.get("workspace_id") or auth_ctx.get("workspace_id"),
            "environment": payload.get("environment") or auth_ctx.get("environment"),
        }
        try:
            AuthService.validate_target_scope(auth_ctx, **target_scope)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        response = AdminService().activate_openclaw_alert_governance(
            gw,
            runtime_id=runtime_id,
            actor=str(payload.get('actor') or auth_ctx.get('user_key') or 'system'),
            candidate_policy=dict(payload.get('candidate_policy') or payload.get('policy') or {}),
            merge_with_current=bool(payload.get('merge_with_current', True)),
            reason=str(payload.get('reason') or ''),
            alert_code=(str(payload.get('alert_code') or '').strip() or None),
            include_unchanged=bool(payload.get('include_unchanged', True)),
            limit=int(payload.get('limit') or 200),
            now_ts=float(payload.get('now_ts')) if payload.get('now_ts') is not None else None,
            **target_scope,
        )
        audit_sensitive(gw, action="admin_openclaw_runtime_alert_governance_activate", auth_ctx=auth_ctx, status="ok" if response.get("ok") else "error", target=runtime_id, details={"version_id": ((response.get('version') or {}).get('version_id')), "affected_count": (((response.get('simulation') or {}).get('summary') or {}).get('affected_count'))})
        return response

    @router.post("/admin/openclaw/runtimes/{runtime_id}/alert-governance/versions/{version_id}/rollback")
    async def broker_admin_openclaw_runtime_alert_governance_rollback(runtime_id: str, version_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
        target_scope = {
            "tenant_id": payload.get("tenant_id") or auth_ctx.get("tenant_id"),
            "workspace_id": payload.get("workspace_id") or auth_ctx.get("workspace_id"),
            "environment": payload.get("environment") or auth_ctx.get("environment"),
        }
        try:
            AuthService.validate_target_scope(auth_ctx, **target_scope)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        response = AdminService().rollback_openclaw_alert_governance_version(
            gw,
            runtime_id=runtime_id,
            version_id=version_id,
            actor=str(payload.get('actor') or auth_ctx.get('user_key') or 'system'),
            reason=str(payload.get('reason') or ''),
            **target_scope,
        )
        audit_sensitive(gw, action="admin_openclaw_runtime_alert_governance_rollback", auth_ctx=auth_ctx, status="ok" if response.get("ok") else "error", target=runtime_id, details={"version_id": version_id, "new_version_id": ((response.get('version') or {}).get('version_id'))})
        return response

    @router.get("/admin/openclaw/alert-dispatches")
    def broker_admin_openclaw_alert_dispatches(
        request: Request,
        runtime_id: str | None = Query(default=None),
        alert_code: str | None = Query(default=None),
        target_type: str | None = Query(default=None),
        delivery_status: str | None = Query(default=None),
        workflow_action: str | None = Query(default=None),
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
        response = AdminService().list_openclaw_alert_notification_dispatches(gw, runtime_id=runtime_id, alert_code=alert_code, target_type=target_type, delivery_status=delivery_status, workflow_action=workflow_action, limit=limit, **target_scope)
        audit_sensitive(gw, action="admin_openclaw_alert_dispatches", auth_ctx=auth_ctx, status="ok", target=runtime_id or 'all', details={"count": len(response.get('items', [])), "delivery_status": delivery_status})
        return response

    @router.post("/admin/openclaw/runtimes/{runtime_id}/alerts/{alert_code}/dispatch")
    async def broker_admin_openclaw_runtime_alert_dispatch(runtime_id: str, alert_code: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
        target_scope = {
            "tenant_id": payload.get("tenant_id") or auth_ctx.get("tenant_id"),
            "workspace_id": payload.get("workspace_id") or auth_ctx.get("workspace_id"),
            "environment": payload.get("environment") or auth_ctx.get("environment"),
        }
        try:
            AuthService.validate_target_scope(auth_ctx, **target_scope)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        response = AdminService().dispatch_openclaw_runtime_alert_notifications(
            gw,
            runtime_id=runtime_id,
            alert_code=alert_code,
            actor=str(payload.get('actor') or auth_ctx.get('username') or 'broker-admin'),
            workflow_action=str(payload.get('workflow_action') or 'escalate'),
            target_id=str(payload.get('target_id') or payload.get('target') or ''),
            reason=str(payload.get('reason') or ''),
            level=int(payload.get('level')) if payload.get('level') is not None else None,
            **target_scope,
        )
        audit_sensitive(gw, action="admin_openclaw_runtime_alert_dispatch", auth_ctx=auth_ctx, status="ok", target=runtime_id, details={"alert_code": alert_code, "count": len(response.get('items', []))})
        return response

    @router.post("/admin/openclaw/runtimes/{runtime_id}/alerts/{alert_code}/ack")
    def broker_admin_openclaw_runtime_alert_ack(
        runtime_id: str,
        alert_code: str,
        payload: dict,
        request: Request,
    ):
        gw, auth_ctx = require_permission(request, "admin.write")
        target_scope = {
            "tenant_id": payload.get("tenant_id") or auth_ctx.get("tenant_id"),
            "workspace_id": payload.get("workspace_id") or auth_ctx.get("workspace_id"),
            "environment": payload.get("environment") or auth_ctx.get("environment"),
        }
        try:
            AuthService.validate_target_scope(auth_ctx, **target_scope)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        response = AdminService().ack_openclaw_runtime_alert(gw, runtime_id=runtime_id, alert_code=alert_code, actor=str(payload.get("actor") or "admin"), note=str(payload.get("note") or payload.get("reason") or ""), **target_scope)
        audit_sensitive(gw, action="admin_openclaw_runtime_alert_ack", auth_ctx=auth_ctx, status="ok" if response.get("ok") else "error", target=runtime_id, details={"alert_code": alert_code})
        return response

    @router.post("/admin/openclaw/runtimes/{runtime_id}/alerts/{alert_code}/silence")
    def broker_admin_openclaw_runtime_alert_silence(
        runtime_id: str,
        alert_code: str,
        payload: dict,
        request: Request,
    ):
        gw, auth_ctx = require_permission(request, "admin.write")
        target_scope = {
            "tenant_id": payload.get("tenant_id") or auth_ctx.get("tenant_id"),
            "workspace_id": payload.get("workspace_id") or auth_ctx.get("workspace_id"),
            "environment": payload.get("environment") or auth_ctx.get("environment"),
        }
        try:
            AuthService.validate_target_scope(auth_ctx, **target_scope)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        response = AdminService().silence_openclaw_runtime_alert(gw, runtime_id=runtime_id, alert_code=alert_code, actor=str(payload.get("actor") or "admin"), silence_for_s=int(payload.get("silence_for_s") or payload.get("duration_s") or 0) or None, reason=str(payload.get("reason") or ""), **target_scope)
        audit_sensitive(gw, action="admin_openclaw_runtime_alert_silence", auth_ctx=auth_ctx, status="ok" if response.get("ok") else "error", target=runtime_id, details={"alert_code": alert_code})
        return response

    @router.post("/admin/openclaw/runtimes/{runtime_id}/alerts/{alert_code}/escalate")
    def broker_admin_openclaw_runtime_alert_escalate(
        runtime_id: str,
        alert_code: str,
        payload: dict,
        request: Request,
    ):
        gw, auth_ctx = require_permission(request, "admin.write")
        target_scope = {
            "tenant_id": payload.get("tenant_id") or auth_ctx.get("tenant_id"),
            "workspace_id": payload.get("workspace_id") or auth_ctx.get("workspace_id"),
            "environment": payload.get("environment") or auth_ctx.get("environment"),
        }
        try:
            AuthService.validate_target_scope(auth_ctx, **target_scope)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        response = AdminService().escalate_openclaw_runtime_alert(gw, runtime_id=runtime_id, alert_code=alert_code, actor=str(payload.get("actor") or "admin"), target=str(payload.get("target") or ""), reason=str(payload.get("reason") or ""), level=int(payload.get("level")) if payload.get("level") is not None else None, **target_scope)
        audit_sensitive(gw, action="admin_openclaw_runtime_alert_escalate", auth_ctx=auth_ctx, status="ok" if response.get("ok") else "error", target=runtime_id, details={"alert_code": alert_code})
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

    @router.get("/admin/openclaw/dispatches/{dispatch_id}")
    def broker_admin_openclaw_dispatch_detail(
        dispatch_id: str,
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
        response = AdminService().get_openclaw_dispatch(gw, dispatch_id=dispatch_id, **target_scope)
        audit_sensitive(gw, action="admin_openclaw_dispatch_detail", auth_ctx=auth_ctx, status="ok" if response.get("ok") else "missing", target=dispatch_id, details={"canonical_status": ((response.get("dispatch") or {}).get("canonical_status"))})
        return response

    @router.post("/admin/openclaw/dispatches/{dispatch_id}/cancel")
    async def broker_admin_openclaw_dispatch_cancel(dispatch_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
        target_scope = {
            "tenant_id": payload.get("tenant_id") or auth_ctx.get("tenant_id"),
            "workspace_id": payload.get("workspace_id") or auth_ctx.get("workspace_id"),
            "environment": payload.get("environment") or auth_ctx.get("environment"),
        }
        actor = str(payload.get('actor') or auth_ctx.get('user_key') or auth_ctx.get('username') or 'system')
        try:
            AuthService.validate_target_scope(auth_ctx, **target_scope)
            response = AdminService().cancel_openclaw_dispatch(gw, dispatch_id=dispatch_id, actor=actor, reason=str(payload.get('reason') or ''), user_role=str(auth_ctx.get('role') or 'operator'), user_key=str(auth_ctx.get('user_key') or actor), session_id=str(payload.get('session_id') or 'broker:openclaw:cancel'), **target_scope)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit_sensitive(gw, action="admin_openclaw_dispatch_cancel", auth_ctx=auth_ctx, status="ok" if response.get("ok") else "error", target=dispatch_id, details={"canonical_status": ((response.get("dispatch") or {}).get("canonical_status"))})
        return response

    @router.post("/admin/openclaw/dispatches/{dispatch_id}/retry")
    async def broker_admin_openclaw_dispatch_retry(dispatch_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
        target_scope = {
            "tenant_id": payload.get("tenant_id") or auth_ctx.get("tenant_id"),
            "workspace_id": payload.get("workspace_id") or auth_ctx.get("workspace_id"),
            "environment": payload.get("environment") or auth_ctx.get("environment"),
        }
        actor = str(payload.get('actor') or auth_ctx.get('user_key') or auth_ctx.get('username') or 'system')
        try:
            AuthService.validate_target_scope(auth_ctx, **target_scope)
            response = AdminService().retry_openclaw_dispatch(gw, dispatch_id=dispatch_id, actor=actor, reason=str(payload.get('reason') or ''), payload_override=dict(payload.get('payload_override') or {}), action_override=str(payload.get('action_override') or ''), agent_id_override=str(payload.get('agent_id_override') or ''), user_role=str(auth_ctx.get('role') or 'operator'), user_key=str(auth_ctx.get('user_key') or actor), session_id=str(payload.get('session_id') or 'broker:openclaw:retry'), **target_scope)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit_sensitive(gw, action="admin_openclaw_dispatch_retry", auth_ctx=auth_ctx, status="ok" if response.get("ok") else "error", target=dispatch_id, details={"new_dispatch_id": response.get("dispatch", {}).get("dispatch_id")})
        return response

    @router.post("/admin/openclaw/dispatches/{dispatch_id}/reconcile")
    async def broker_admin_openclaw_dispatch_reconcile(dispatch_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
        target_scope = {
            "tenant_id": payload.get("tenant_id") or auth_ctx.get("tenant_id"),
            "workspace_id": payload.get("workspace_id") or auth_ctx.get("workspace_id"),
            "environment": payload.get("environment") or auth_ctx.get("environment"),
        }
        actor = str(payload.get('actor') or auth_ctx.get('user_key') or auth_ctx.get('username') or 'system')
        try:
            AuthService.validate_target_scope(auth_ctx, **target_scope)
            response = AdminService().reconcile_openclaw_dispatch(gw, dispatch_id=dispatch_id, actor=actor, target_status=str(payload.get('target_status') or payload.get('manual_status') or ''), reason=str(payload.get('reason') or ''), user_role=str(auth_ctx.get('role') or 'operator'), user_key=str(auth_ctx.get('user_key') or actor), session_id=str(payload.get('session_id') or 'broker:openclaw:reconcile'), **target_scope)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit_sensitive(gw, action="admin_openclaw_dispatch_reconcile", auth_ctx=auth_ctx, status="ok" if response.get("ok") else "error", target=dispatch_id, details={"canonical_status": ((response.get("dispatch") or {}).get("canonical_status"))})
        return response

    @router.post("/admin/openclaw/dispatches/{dispatch_id}/poll")
    async def broker_admin_openclaw_dispatch_poll(dispatch_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
        target_scope = {
            "tenant_id": payload.get("tenant_id") or auth_ctx.get("tenant_id"),
            "workspace_id": payload.get("workspace_id") or auth_ctx.get("workspace_id"),
            "environment": payload.get("environment") or auth_ctx.get("environment"),
        }
        actor = str(payload.get('actor') or auth_ctx.get('user_key') or auth_ctx.get('username') or 'system')
        try:
            AuthService.validate_target_scope(auth_ctx, **target_scope)
            response = AdminService().poll_openclaw_dispatch(gw, dispatch_id=dispatch_id, actor=actor, reason=str(payload.get('reason') or ''), user_role=str(auth_ctx.get('role') or 'operator'), user_key=str(auth_ctx.get('user_key') or actor), session_id=str(payload.get('session_id') or 'broker:openclaw:poll'), **target_scope)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit_sensitive(gw, action="admin_openclaw_dispatch_poll", auth_ctx=auth_ctx, status="ok" if response.get("ok") else "error", target=dispatch_id, details={"canonical_status": ((response.get("dispatch") or {}).get("canonical_status"))})
        return response

    @router.get("/admin/openclaw/runtimes/{runtime_id}/timeline")
    def broker_admin_openclaw_runtime_timeline(
        runtime_id: str,
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
        try:
            AuthService.validate_target_scope(auth_ctx, **target_scope)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        response = AdminService().get_openclaw_runtime_timeline(gw, runtime_id=runtime_id, limit=limit, **target_scope)
        audit_sensitive(gw, action="admin_openclaw_runtime_timeline", auth_ctx=auth_ctx, status="ok" if response.get("ok") else "missing", target=runtime_id, details={"count": len(response.get("timeline", []))})
        return response

    @router.post("/admin/openclaw/runtimes/{runtime_id}/health")
    async def broker_admin_openclaw_runtime_health(runtime_id: str, request: Request):
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
            response = AdminService().check_openclaw_runtime_health(
                gw,
                runtime_id=runtime_id,
                actor=str(payload.get("actor") or auth_ctx.get("username") or "broker-admin"),
                probe=str(payload.get("probe") or "ready"),
                user_role=str(auth_ctx.get("role") or "operator"),
                user_key=str(auth_ctx.get("user_key") or auth_ctx.get("username") or ""),
                session_id=str(payload.get("session_id") or "admin"),
                **target_scope,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit_sensitive(gw, action="admin_openclaw_runtime_health", auth_ctx=auth_ctx, status="ok" if response.get("ok") else "error", target=runtime_id, details={"health_status": ((response.get("health") or {}).get("status"))})
        return response

    @router.post("/admin/openclaw/runtimes/{runtime_id}/recover")
    async def broker_admin_openclaw_runtime_recover(runtime_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
        target_scope = {
            "tenant_id": payload.get("tenant_id") or auth_ctx.get("tenant_id"),
            "workspace_id": payload.get("workspace_id") or auth_ctx.get("workspace_id"),
            "environment": payload.get("environment") or auth_ctx.get("environment"),
        }
        try:
            AuthService.validate_target_scope(auth_ctx, **target_scope)
            response = AdminService().recover_openclaw_runtime(
                gw,
                runtime_id=runtime_id,
                actor=str(payload.get("actor") or auth_ctx.get("username") or "broker-admin"),
                reason=str(payload.get('reason') or ''),
                limit=int(payload.get('limit') or 50),
                user_role=str(auth_ctx.get("role") or "operator"),
                user_key=str(auth_ctx.get("user_key") or auth_ctx.get("username") or ""),
                session_id=str(payload.get("session_id") or "broker:openclaw:recover"),
                **target_scope,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit_sensitive(gw, action="admin_openclaw_runtime_recover", auth_ctx=auth_ctx, status="ok" if response.get("ok") else "error", target=runtime_id, details={"reconciled_count": ((response.get("summary") or {}).get("reconciled_count"))})
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

    @router.post("/admin/openclaw/runtimes/{runtime_id}/events")
    async def broker_admin_openclaw_runtime_events(runtime_id: str, request: Request):
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
            response = AdminService().ingest_openclaw_runtime_event(
                gw,
                runtime_id=runtime_id,
                actor=str(payload.get("actor") or auth_ctx.get("username") or "broker-admin"),
                source=str(payload.get("source") or "openclaw"),
                event_type=str(payload.get("event_type") or ""),
                event_status=str(payload.get("event_status") or ""),
                source_event_id=str(payload.get("source_event_id") or ""),
                dispatch_id=str(payload.get("dispatch_id") or ""),
                session_id=str(payload.get("session_id") or "admin"),
                user_key=str(auth_ctx.get("user_key") or auth_ctx.get("username") or ""),
                message=str(payload.get("message") or ""),
                payload=dict(payload.get("payload") or {}),
                observed_at=payload.get("observed_at"),
                auth_mode='broker_admin',
                require_token=False,
                **target_scope,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit_sensitive(gw, action="admin_openclaw_runtime_event", auth_ctx=auth_ctx, status="ok", target=runtime_id, details={"duplicate": response.get("duplicate", False), "dispatch_id": response.get("event", {}).get("dispatch_id")})
        return response

    @router.post("/admin/openclaw/runtimes/{runtime_id}/conformance")
    async def broker_admin_openclaw_runtime_conformance(runtime_id: str, request: Request):
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
            response = AdminService().run_openclaw_runtime_conformance(
                gw,
                runtime_id=runtime_id,
                actor=str(payload.get("actor") or auth_ctx.get("username") or "broker-admin"),
                user_role=str(auth_ctx.get("role") or "operator"),
                user_key=str(auth_ctx.get("user_key") or auth_ctx.get("username") or ""),
                session_id=str(payload.get("session_id") or "admin"),
                **target_scope,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        audit_sensitive(gw, action="admin_openclaw_runtime_conformance", auth_ctx=auth_ctx, status="ok", target=runtime_id, details={"ready": ((response.get("conformance") or {}).get("ready"))})
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

    @router.get("/admin/canvas/documents/{canvas_id}/views/runtime-board")
    def broker_admin_canvas_runtime_board(
        canvas_id: str,
        request: Request,
        limit: int = Query(default=10, ge=1, le=100),
        tenant_id: str | None = Query(default=None),
        workspace_id: str | None = Query(default=None),
        environment: str | None = Query(default=None),
    ):
        gw, auth_ctx = require_permission(request, "admin.read")
        response = AdminService().get_canvas_runtime_board(
            gw,
            canvas_id=canvas_id,
            limit=limit,
            tenant_id=tenant_id or auth_ctx.get("tenant_id"),
            workspace_id=workspace_id or auth_ctx.get("workspace_id"),
            environment=environment or auth_ctx.get("environment"),
        )
        audit_sensitive(gw, action="admin_canvas_runtime_board", auth_ctx=auth_ctx, status="ok" if response.get("ok") else "missing", target=canvas_id, details={"runtime_count": len(response.get("items") or [])})
        return response

    @router.get("/admin/canvas/documents/{canvas_id}/views/baseline-promotions")
    def admin_canvas_baseline_promotion_board(
        canvas_id: str,
        request: Request,
        limit: int = Query(default=10, ge=1, le=100),
        tenant_id: str | None = Query(default=None),
        workspace_id: str | None = Query(default=None),
        environment: str | None = Query(default=None),
    ):
        gw = _get_gw(request)
        _require_admin(request)
        payload = _ADMIN_SERVICE.get_canvas_baseline_promotion_board(
            gw,
            canvas_id=canvas_id,
            limit=limit,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        _audit_admin(gw, "canvas_baseline_promotion_board", {"canvas_id": canvas_id, "ok": payload.get("ok"), "promotion_count": len(payload.get("items") or [])})
        return payload

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
