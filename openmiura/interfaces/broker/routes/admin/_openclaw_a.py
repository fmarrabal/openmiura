"""admin/_openclaw_a.py - broker admin sub-routes for the openclaw_a domain."""
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
    """Attach the openclaw_a broker admin endpoints to *router*."""
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

