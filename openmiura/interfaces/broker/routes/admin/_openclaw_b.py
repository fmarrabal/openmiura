"""admin/_openclaw_b.py - broker admin sub-routes for the openclaw_b domain."""
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
    """Attach the openclaw_b broker admin endpoints to *router*."""
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

