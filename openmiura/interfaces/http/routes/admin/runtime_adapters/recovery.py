"""admin/runtime_adapters/recovery.py — recovery sub-router for runtime adapters."""

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
)
from openmiura.interfaces.http.routes.admin._models import *  # noqa: F401,F403

router = APIRouter(tags=["admin"])


@router.get("/admin/openclaw/policy-packs")
def admin_openclaw_policy_packs(
    request: Request,
    runtime_class: Optional[str] = Query(default=None),
    transport: str = Query(default='http'),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.list_openclaw_policy_packs(gw, runtime_class=runtime_class, transport=transport)
    _audit_admin(gw, 'openclaw_policy_packs', {'count': len(response.get('items', [])), 'runtime_class': runtime_class, 'transport': transport})
    return response


@router.get("/admin/openclaw/worker-leases")
def admin_openclaw_worker_leases(
    request: Request,
    runtime_id: Optional[str] = Query(default=None),
    lease_type: Optional[str] = Query(default=None),
    active_only: Optional[bool] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=300),
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.list_openclaw_worker_leases(gw, runtime_id=runtime_id, lease_type=lease_type, active_only=active_only, limit=limit, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
    _audit_admin(gw, 'openclaw_worker_leases', {'count': len(response.get('items', [])), 'runtime_id': runtime_id, 'lease_type': lease_type, 'active_only': active_only})
    return response


@router.get("/admin/openclaw/idempotency-records")
def admin_openclaw_idempotency_records(
    request: Request,
    runtime_id: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    active_only: Optional[bool] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=300),
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.list_openclaw_idempotency_records(gw, runtime_id=runtime_id, status=status, active_only=active_only, limit=limit, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
    _audit_admin(gw, 'openclaw_idempotency_records', {'count': len(response.get('items', [])), 'runtime_id': runtime_id, 'status': status, 'active_only': active_only})
    return response


@router.get("/admin/openclaw/recovery-jobs")
def admin_openclaw_recovery_jobs(
    request: Request,
    runtime_id: Optional[str] = Query(default=None),
    enabled: Optional[bool] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=300),
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.list_openclaw_recovery_jobs(gw, runtime_id=runtime_id, enabled=enabled, limit=limit, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
    _audit_admin(gw, 'openclaw_recovery_jobs', {'count': len(response.get('items', [])), 'runtime_id': runtime_id})
    return response


@router.post("/admin/openclaw/recovery-jobs/run-due")
async def admin_openclaw_recovery_jobs_run_due(request: Request):
    payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.run_due_openclaw_recovery_jobs(
        gw,
        actor=str(payload.get('actor') or 'admin'),
        limit=int(payload.get('limit') or 20),
        runtime_id=str(payload.get('runtime_id') or '') or None,
        user_role='admin',
        user_key=str(payload.get('actor') or 'admin'),
        tenant_id=payload.get('tenant_id'),
        workspace_id=payload.get('workspace_id'),
        environment=payload.get('environment'),
    )
    _audit_admin(gw, 'openclaw_recovery_jobs_run_due', {'executed': ((response.get('summary') or {}).get('executed')), 'runtime_id': payload.get('runtime_id')})
    return response


@router.get("/admin/openclaw/runtime-alerts")
def admin_openclaw_runtime_alerts(
    request: Request,
    runtime_id: Optional[str] = Query(default=None),
    severity: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=300),
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.list_openclaw_runtime_alerts(gw, runtime_id=runtime_id, severity=severity, limit=limit, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
    _audit_admin(gw, 'openclaw_runtime_alerts', {'count': len(response.get('items', [])), 'runtime_id': runtime_id, 'severity': severity, 'critical_count': ((response.get('summary') or {}).get('critical_count'))})
    return response


