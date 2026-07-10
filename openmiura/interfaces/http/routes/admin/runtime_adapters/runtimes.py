"""admin/runtime_adapters/runtimes.py — runtimes sub-router for runtime adapters."""

from __future__ import annotations

import json
import re
import secrets
import threading
import time
from collections import defaultdict, deque
from typing import Any, Dict, Iterable, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from openmiura.interfaces.http.routes.admin._helpers import (
    _ADMIN_SERVICE,
    _audit_admin,
    _extract_admin_token,
    _get_gw,
    _rate_limit,
    _require_admin,
    run_in_threadpool,
)
from openmiura.interfaces.http.routes.admin._models import *  # noqa: F401,F403

router = APIRouter(tags=["admin"])


@router.get("/admin/openclaw/runtimes")
def admin_openclaw_runtimes(
    request: Request,
    limit: int = Query(default=100, ge=1, le=300),
    status: Optional[str] = Query(default=None),
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.list_openclaw_runtimes(gw, limit=limit, status=status, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
    _audit_admin(gw, 'openclaw_runtimes', {'count': len(response.get('items', [])), 'status': status, 'tenant_id': tenant_id, 'workspace_id': workspace_id, 'environment': environment})
    return response


@router.post("/admin/openclaw/runtimes")
async def admin_openclaw_register_runtime(request: Request):
    gw = _require_admin(request)
    payload = await request.json()
    response = await run_in_threadpool(_ADMIN_SERVICE.register_openclaw_runtime,
        gw,
        actor=str(payload.get('actor') or 'admin'),
        name=str(payload.get('name') or ''),
        base_url=str(payload.get('base_url') or ''),
        transport=str(payload.get('transport') or 'http'),
        auth_secret_ref=str(payload.get('auth_secret_ref') or ''),
        capabilities=list(payload.get('capabilities') or []),
        allowed_agents=list(payload.get('allowed_agents') or []),
        metadata=dict(payload.get('metadata') or {}),
        runtime_id=payload.get('runtime_id'),
        tenant_id=payload.get('tenant_id'),
        workspace_id=payload.get('workspace_id'),
        environment=payload.get('environment'),
    )
    await run_in_threadpool(_audit_admin, gw, 'openclaw_runtime_register', {'runtime_id': response.get('runtime', {}).get('runtime_id'), 'tenant_id': payload.get('tenant_id'), 'workspace_id': payload.get('workspace_id'), 'environment': payload.get('environment')})
    return response


@router.post("/admin/openclaw/runtimes/{runtime_id}/policy-pack")
async def admin_openclaw_runtime_policy_pack(runtime_id: str, request: Request):
    payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    gw = _require_admin(request)
    response = await run_in_threadpool(_ADMIN_SERVICE.apply_openclaw_policy_pack,
        gw,
        runtime_id=runtime_id,
        actor=str(payload.get('actor') or 'admin'),
        pack_name=str(payload.get('pack_name') or payload.get('policy_pack') or '') or None,
        runtime_class=str(payload.get('runtime_class') or '') or None,
        overrides=dict(payload.get('overrides') or {}),
        tenant_id=payload.get('tenant_id'),
        workspace_id=payload.get('workspace_id'),
        environment=payload.get('environment'),
    )
    await run_in_threadpool(_audit_admin, gw, 'openclaw_runtime_policy_pack', {'runtime_id': runtime_id, 'ok': response.get('ok'), 'policy_pack': ((response.get('runtime_summary') or {}).get('metadata') or {}).get('policy_pack')})
    return response


@router.post("/admin/openclaw/runtimes/{runtime_id}/recovery-jobs")
async def admin_openclaw_runtime_schedule_recovery(runtime_id: str, request: Request):
    payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    gw = _require_admin(request)
    response = await run_in_threadpool(_ADMIN_SERVICE.schedule_openclaw_runtime_recovery_job,
        gw,
        runtime_id=runtime_id,
        actor=str(payload.get('actor') or 'admin'),
        reason=str(payload.get('reason') or ''),
        limit=int(payload['limit']) if payload.get('limit') is not None else None,
        schedule_kind=str(payload.get('schedule_kind') or '') or None,
        interval_s=int(payload['interval_s']) if payload.get('interval_s') is not None else None,
        schedule_expr=str(payload.get('schedule_expr') or '') or None,
        timezone_name=str(payload.get('timezone_name') or payload.get('timezone') or 'UTC'),
        not_before=payload.get('not_before'),
        not_after=payload.get('not_after'),
        max_runs=payload.get('max_runs'),
        enabled=bool(payload.get('enabled', True)),
        tenant_id=payload.get('tenant_id'),
        workspace_id=payload.get('workspace_id'),
        environment=payload.get('environment'),
    )
    await run_in_threadpool(_audit_admin, gw, 'openclaw_runtime_schedule_recovery', {'runtime_id': runtime_id, 'ok': response.get('ok'), 'job_id': response.get('job', {}).get('job_id')})
    return response


@router.get("/admin/openclaw/runtimes/{runtime_id}/concurrency")
def admin_openclaw_runtime_concurrency(
    runtime_id: str,
    request: Request,
    limit: int = Query(default=20, ge=1, le=200),
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.get_openclaw_runtime_concurrency(gw, runtime_id=runtime_id, limit=limit, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
    _audit_admin(gw, 'openclaw_runtime_concurrency', {'runtime_id': runtime_id, 'ok': response.get('ok'), 'active_leases': ((response.get('summary') or {}).get('active_leases')), 'in_progress_idempotency': ((response.get('summary') or {}).get('in_progress_idempotency_count'))})
    return response


@router.get("/admin/openclaw/runtimes/{runtime_id}/alerts")
def admin_openclaw_runtime_alert_detail(
    runtime_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.get_openclaw_runtime_alerts(gw, runtime_id=runtime_id, limit=limit, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
    _audit_admin(gw, 'openclaw_runtime_alert_detail', {'runtime_id': runtime_id, 'ok': response.get('ok'), 'critical_count': ((response.get('summary') or {}).get('critical_count')), 'warn_count': ((response.get('summary') or {}).get('warn_count'))})
    return response


@router.get("/admin/openclaw/runtimes/{runtime_id}/notification-targets")
def admin_openclaw_runtime_notification_targets(
    runtime_id: str,
    request: Request,
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.list_openclaw_notification_targets(gw, runtime_id=runtime_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
    _audit_admin(gw, 'openclaw_runtime_notification_targets', {'runtime_id': runtime_id, 'ok': response.get('ok'), 'count': len(response.get('items', []))})
    return response


@router.get("/admin/openclaw/runtimes/{runtime_id}/alert-routing")
def admin_openclaw_runtime_alert_routing(
    runtime_id: str,
    request: Request,
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.get_openclaw_alert_routing(gw, runtime_id=runtime_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
    _audit_admin(gw, 'openclaw_runtime_alert_routing', {'runtime_id': runtime_id, 'ok': response.get('ok'), 'rule_count': ((response.get('summary') or {}).get('rule_count')), 'chain_count': ((response.get('summary') or {}).get('escalation_chain_count'))})
    return response


@router.get("/admin/openclaw/runtimes/{runtime_id}/alert-governance")
def admin_openclaw_runtime_alert_governance(
    runtime_id: str,
    request: Request,
    limit: int = Query(default=200, ge=1, le=500),
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.get_openclaw_alert_governance(gw, runtime_id=runtime_id, limit=limit, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
    _audit_admin(gw, 'openclaw_runtime_alert_governance', {'runtime_id': runtime_id, 'ok': response.get('ok'), 'suppressed_alert_count': ((response.get('summary') or {}).get('suppressed_alert_count')), 'active_override_count': ((response.get('summary') or {}).get('active_override_count'))})
    return response


@router.post("/admin/openclaw/runtimes/{runtime_id}/alert-governance/simulate")
async def admin_openclaw_runtime_alert_governance_simulate(runtime_id: str, request: Request):
    payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    gw = _require_admin(request)
    response = await run_in_threadpool(_ADMIN_SERVICE.simulate_openclaw_alert_governance,
        gw,
        runtime_id=runtime_id,
        candidate_policy=dict(payload.get('candidate_policy') or payload.get('policy') or {}),
        merge_with_current=bool(payload.get('merge_with_current', True)),
        alert_code=(str(payload.get('alert_code') or '').strip() or None),
        include_unchanged=bool(payload.get('include_unchanged', True)),
        tenant_id=payload.get('tenant_id'),
        workspace_id=payload.get('workspace_id'),
        environment=payload.get('environment'),
        limit=int(payload.get('limit') or 200),
        now_ts=float(payload.get('now_ts')) if payload.get('now_ts') is not None else None,
    )
    await run_in_threadpool(_audit_admin, gw, 'openclaw_runtime_alert_governance_simulate', {'runtime_id': runtime_id, 'ok': response.get('ok'), 'mode': response.get('mode'), 'affected_count': ((response.get('summary') or {}).get('affected_count'))})
    return response


@router.get("/admin/openclaw/runtimes/{runtime_id}/alert-governance/versions")
def admin_openclaw_runtime_alert_governance_versions(
    runtime_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    status: Optional[str] = Query(default=None),
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.list_openclaw_alert_governance_versions(gw, runtime_id=runtime_id, limit=limit, status=status, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
    _audit_admin(gw, 'openclaw_runtime_alert_governance_versions', {'runtime_id': runtime_id, 'count': len(response.get('items', [])), 'status': status})
    return response


@router.post("/admin/openclaw/runtimes/{runtime_id}/alert-governance/activate")
async def admin_openclaw_runtime_alert_governance_activate(runtime_id: str, request: Request):
    payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    gw = _require_admin(request)
    response = await run_in_threadpool(_ADMIN_SERVICE.activate_openclaw_alert_governance,
        gw,
        runtime_id=runtime_id,
        actor=str(payload.get('actor') or 'system'),
        candidate_policy=dict(payload.get('candidate_policy') or payload.get('policy') or {}),
        merge_with_current=bool(payload.get('merge_with_current', True)),
        reason=str(payload.get('reason') or ''),
        alert_code=(str(payload.get('alert_code') or '').strip() or None),
        include_unchanged=bool(payload.get('include_unchanged', True)),
        tenant_id=payload.get('tenant_id'),
        workspace_id=payload.get('workspace_id'),
        environment=payload.get('environment'),
        limit=int(payload.get('limit') or 200),
        now_ts=float(payload.get('now_ts')) if payload.get('now_ts') is not None else None,
    )
    await run_in_threadpool(_audit_admin, gw, 'openclaw_runtime_alert_governance_activate', {'runtime_id': runtime_id, 'ok': response.get('ok'), 'version_id': ((response.get('version') or {}).get('version_id')), 'affected_count': (((response.get('simulation') or {}).get('summary') or {}).get('affected_count'))})
    return response


@router.post("/admin/openclaw/runtimes/{runtime_id}/alert-governance/versions/{version_id}/rollback")
async def admin_openclaw_runtime_alert_governance_rollback(runtime_id: str, version_id: str, request: Request):
    payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    gw = _require_admin(request)
    response = await run_in_threadpool(_ADMIN_SERVICE.rollback_openclaw_alert_governance_version,
        gw,
        runtime_id=runtime_id,
        version_id=version_id,
        actor=str(payload.get('actor') or 'system'),
        reason=str(payload.get('reason') or ''),
        tenant_id=payload.get('tenant_id'),
        workspace_id=payload.get('workspace_id'),
        environment=payload.get('environment'),
    )
    await run_in_threadpool(_audit_admin, gw, 'openclaw_runtime_alert_governance_rollback', {'runtime_id': runtime_id, 'ok': response.get('ok'), 'version_id': version_id, 'new_version_id': ((response.get('version') or {}).get('version_id'))})
    return response


@router.post("/admin/openclaw/runtimes/{runtime_id}/alerts/{alert_code}/dispatch")
async def admin_openclaw_runtime_alert_dispatch(runtime_id: str, alert_code: str, request: Request):
    payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    gw = _require_admin(request)
    response = await run_in_threadpool(_ADMIN_SERVICE.dispatch_openclaw_runtime_alert_notifications,
        gw,
        runtime_id=runtime_id,
        alert_code=alert_code,
        actor=str(payload.get('actor') or 'admin'),
        workflow_action=str(payload.get('workflow_action') or 'escalate'),
        target_id=str(payload.get('target_id') or payload.get('target') or ''),
        reason=str(payload.get('reason') or ''),
        level=int(payload.get('level')) if payload.get('level') is not None else None,
        tenant_id=payload.get('tenant_id'),
        workspace_id=payload.get('workspace_id'),
        environment=payload.get('environment'),
    )
    await run_in_threadpool(_audit_admin, gw, 'openclaw_runtime_alert_dispatch', {'runtime_id': runtime_id, 'alert_code': alert_code, 'ok': response.get('ok'), 'count': len(response.get('items', []))})
    return response


@router.post("/admin/openclaw/runtimes/{runtime_id}/alerts/{alert_code}/ack")
async def admin_openclaw_runtime_alert_ack(runtime_id: str, alert_code: str, request: Request):
    payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    gw = _require_admin(request)
    response = await run_in_threadpool(_ADMIN_SERVICE.ack_openclaw_runtime_alert,
        gw,
        runtime_id=runtime_id,
        alert_code=alert_code,
        actor=str(payload.get('actor') or 'admin'),
        note=str(payload.get('note') or payload.get('reason') or ''),
        tenant_id=payload.get('tenant_id'),
        workspace_id=payload.get('workspace_id'),
        environment=payload.get('environment'),
    )
    await run_in_threadpool(_audit_admin, gw, 'openclaw_runtime_alert_ack', {'runtime_id': runtime_id, 'alert_code': alert_code, 'ok': response.get('ok')})
    return response


@router.post("/admin/openclaw/runtimes/{runtime_id}/alerts/{alert_code}/silence")
async def admin_openclaw_runtime_alert_silence(runtime_id: str, alert_code: str, request: Request):
    payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    gw = _require_admin(request)
    response = await run_in_threadpool(_ADMIN_SERVICE.silence_openclaw_runtime_alert,
        gw,
        runtime_id=runtime_id,
        alert_code=alert_code,
        actor=str(payload.get('actor') or 'admin'),
        silence_for_s=int(payload.get('silence_for_s') or payload.get('duration_s') or 0) or None,
        reason=str(payload.get('reason') or ''),
        tenant_id=payload.get('tenant_id'),
        workspace_id=payload.get('workspace_id'),
        environment=payload.get('environment'),
    )
    await run_in_threadpool(_audit_admin, gw, 'openclaw_runtime_alert_silence', {'runtime_id': runtime_id, 'alert_code': alert_code, 'ok': response.get('ok')})
    return response


@router.post("/admin/openclaw/runtimes/{runtime_id}/alerts/{alert_code}/escalate")
async def admin_openclaw_runtime_alert_escalate(runtime_id: str, alert_code: str, request: Request):
    payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    gw = _require_admin(request)
    response = await run_in_threadpool(_ADMIN_SERVICE.escalate_openclaw_runtime_alert,
        gw,
        runtime_id=runtime_id,
        alert_code=alert_code,
        actor=str(payload.get('actor') or 'admin'),
        target=str(payload.get('target') or ''),
        reason=str(payload.get('reason') or ''),
        level=int(payload.get('level')) if payload.get('level') is not None else None,
        tenant_id=payload.get('tenant_id'),
        workspace_id=payload.get('workspace_id'),
        environment=payload.get('environment'),
    )
    await run_in_threadpool(_audit_admin, gw, 'openclaw_runtime_alert_escalate', {'runtime_id': runtime_id, 'alert_code': alert_code, 'ok': response.get('ok')})
    return response


@router.get("/admin/openclaw/runtimes/{runtime_id}")
def admin_openclaw_runtime_detail(
    runtime_id: str,
    request: Request,
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.get_openclaw_runtime(gw, runtime_id=runtime_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
    _audit_admin(gw, 'openclaw_runtime_detail', {'runtime_id': runtime_id, 'ok': response.get('ok')})
    return response


@router.get("/admin/openclaw/runtimes/{runtime_id}/timeline")
def admin_openclaw_runtime_timeline(
    runtime_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.get_openclaw_runtime_timeline(gw, runtime_id=runtime_id, limit=limit, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
    _audit_admin(gw, 'openclaw_runtime_timeline', {'runtime_id': runtime_id, 'ok': response.get('ok'), 'count': len(response.get('timeline', []))})
    return response


@router.post("/admin/openclaw/runtimes/{runtime_id}/health")
async def admin_openclaw_runtime_health(runtime_id: str, request: Request):
    gw = _require_admin(request)
    payload = await request.json()
    response = await run_in_threadpool(_ADMIN_SERVICE.check_openclaw_runtime_health,
        gw,
        runtime_id=runtime_id,
        actor=str(payload.get('actor') or 'admin'),
        probe=str(payload.get('probe') or 'ready'),
        user_role=str(payload.get('user_role') or 'admin'),
        user_key=str(payload.get('user_key') or 'admin'),
        session_id=str(payload.get('session_id') or 'admin'),
        tenant_id=payload.get('tenant_id'),
        workspace_id=payload.get('workspace_id'),
        environment=payload.get('environment'),
    )
    await run_in_threadpool(_audit_admin, gw, 'openclaw_runtime_health', {'runtime_id': runtime_id, 'ok': response.get('ok'), 'health_status': ((response.get('health') or {}).get('status'))})
    return response


@router.post("/admin/openclaw/runtimes/{runtime_id}/recover")
async def admin_openclaw_runtime_recover(runtime_id: str, request: Request):
    gw = _require_admin(request)
    payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    response = await run_in_threadpool(_ADMIN_SERVICE.recover_openclaw_runtime,
        gw,
        runtime_id=runtime_id,
        actor=str(payload.get('actor') or 'admin'),
        reason=str(payload.get('reason') or ''),
        limit=int(payload.get('limit') or 50),
        user_role=str(payload.get('user_role') or 'admin'),
        user_key=str(payload.get('user_key') or 'admin'),
        session_id=str(payload.get('session_id') or 'admin:openclaw:recover'),
        tenant_id=payload.get('tenant_id'),
        workspace_id=payload.get('workspace_id'),
        environment=payload.get('environment'),
    )
    await run_in_threadpool(_audit_admin, gw, 'openclaw_runtime_recover', {'runtime_id': runtime_id, 'ok': response.get('ok'), 'reconciled_count': ((response.get('summary') or {}).get('reconciled_count'))})
    return response


@router.post("/admin/openclaw/runtimes/{runtime_id}/dispatch")
async def admin_openclaw_dispatch(runtime_id: str, request: Request):
    gw = _require_admin(request)
    payload = await request.json()
    try:
        response = await run_in_threadpool(_ADMIN_SERVICE.dispatch_openclaw_runtime,
            gw,
            runtime_id=runtime_id,
            actor=str(payload.get('actor') or 'admin'),
            action=str(payload.get('action') or ''),
            payload=dict(payload.get('payload') or {}),
            agent_id=str(payload.get('agent_id') or ''),
            user_role=str(payload.get('user_role') or 'admin'),
            user_key=str(payload.get('user_key') or 'admin'),
            session_id=str(payload.get('session_id') or 'admin'),
            tenant_id=payload.get('tenant_id'),
            workspace_id=payload.get('workspace_id'),
            environment=payload.get('environment'),
            dry_run=bool(payload.get('dry_run', False)),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await run_in_threadpool(_audit_admin, gw, 'openclaw_dispatch', {'runtime_id': runtime_id, 'ok': response.get('ok'), 'dispatch_id': response.get('dispatch', {}).get('dispatch_id')})
    return response


@router.post("/admin/openclaw/runtimes/{runtime_id}/events")
async def admin_openclaw_runtime_event(runtime_id: str, request: Request):
    gw = _require_admin(request)
    payload = await request.json()
    response = await run_in_threadpool(_ADMIN_SERVICE.ingest_openclaw_runtime_event,
        gw,
        runtime_id=runtime_id,
        actor=str(payload.get('actor') or 'admin'),
        source=str(payload.get('source') or 'openclaw'),
        event_type=str(payload.get('event_type') or ''),
        event_status=str(payload.get('event_status') or ''),
        source_event_id=str(payload.get('source_event_id') or ''),
        dispatch_id=str(payload.get('dispatch_id') or ''),
        session_id=str(payload.get('session_id') or ''),
        user_key=str(payload.get('user_key') or ''),
        message=str(payload.get('message') or ''),
        payload=dict(payload.get('payload') or {}),
        observed_at=payload.get('observed_at'),
        tenant_id=payload.get('tenant_id'),
        workspace_id=payload.get('workspace_id'),
        environment=payload.get('environment'),
        auth_mode='admin',
        require_token=False,
    )
    await run_in_threadpool(_audit_admin, gw, 'openclaw_runtime_event', {'runtime_id': runtime_id, 'ok': response.get('ok'), 'duplicate': response.get('duplicate', False), 'dispatch_id': response.get('event', {}).get('dispatch_id')})
    return response


@router.post("/admin/openclaw/runtimes/{runtime_id}/conformance")
async def admin_openclaw_runtime_conformance(runtime_id: str, request: Request):
    gw = _require_admin(request)
    payload = await request.json()
    response = await run_in_threadpool(_ADMIN_SERVICE.run_openclaw_runtime_conformance,
        gw,
        runtime_id=runtime_id,
        actor=str(payload.get('actor') or 'admin'),
        user_role=str(payload.get('user_role') or 'admin'),
        user_key=str(payload.get('user_key') or 'admin'),
        session_id=str(payload.get('session_id') or 'admin'),
        tenant_id=payload.get('tenant_id'),
        workspace_id=payload.get('workspace_id'),
        environment=payload.get('environment'),
    )
    await run_in_threadpool(_audit_admin, gw, 'openclaw_runtime_conformance', {'runtime_id': runtime_id, 'ok': response.get('ok'), 'ready': ((response.get('conformance') or {}).get('ready'))})
    return response


@router.post("/openclaw/runtimes/{runtime_id}/events")
async def openclaw_runtime_event_webhook(runtime_id: str, request: Request):
    gw: Gateway = request.app.state.gw
    payload = await request.json()
    token = request.headers.get('X-OpenClaw-Event-Token') or _extract_bearer_token(request)
    try:
        response = await run_in_threadpool(_ADMIN_SERVICE.ingest_openclaw_runtime_event,
            gw,
            runtime_id=runtime_id,
            actor=str(payload.get('actor') or payload.get('source') or 'openclaw'),
            source=str(payload.get('source') or 'openclaw'),
            event_type=str(payload.get('event_type') or ''),
            event_status=str(payload.get('event_status') or ''),
            source_event_id=str(payload.get('source_event_id') or ''),
            dispatch_id=str(payload.get('dispatch_id') or ''),
            session_id=str(payload.get('session_id') or ''),
            user_key=str(payload.get('user_key') or ''),
            message=str(payload.get('message') or ''),
            payload=dict(payload.get('payload') or {}),
            observed_at=payload.get('observed_at'),
            tenant_id=payload.get('tenant_id'),
            workspace_id=payload.get('workspace_id'),
            environment=payload.get('environment'),
            auth_mode='runtime_token',
            event_token=str(token or ''),
            require_token=True,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return response


