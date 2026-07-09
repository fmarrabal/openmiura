"""admin/runtime_adapters/dispatches.py — dispatches sub-router for runtime adapters."""

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


@router.get("/admin/openclaw/dispatches")
def admin_openclaw_dispatches(
    request: Request,
    runtime_id: Optional[str] = Query(default=None),
    action: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=300),
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.list_openclaw_dispatches(gw, runtime_id=runtime_id, action=action, status=status, limit=limit, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
    _audit_admin(gw, 'openclaw_dispatches', {'count': len(response.get('items', [])), 'runtime_id': runtime_id, 'status': status})
    return response


@router.get("/admin/openclaw/dispatches/{dispatch_id}")
def admin_openclaw_dispatch_detail(
    dispatch_id: str,
    request: Request,
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.get_openclaw_dispatch(gw, dispatch_id=dispatch_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
    _audit_admin(gw, 'openclaw_dispatch_detail', {'dispatch_id': dispatch_id, 'ok': response.get('ok'), 'canonical_status': ((response.get('dispatch') or {}).get('canonical_status'))})
    return response


@router.post("/admin/openclaw/dispatches/{dispatch_id}/cancel")
async def admin_openclaw_dispatch_cancel(dispatch_id: str, request: Request):
    payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    gw = _require_admin(request)
    try:
        response = await run_in_threadpool(
            _ADMIN_SERVICE.cancel_openclaw_dispatch,
            gw,
            dispatch_id=dispatch_id,
            actor=str(payload.get('actor') or 'admin'),
            reason=str(payload.get('reason') or ''),
            user_role='admin',
            user_key=str(payload.get('actor') or 'admin'),
            session_id=str(payload.get('session_id') or 'admin:openclaw:cancel'),
            tenant_id=payload.get('tenant_id'),
            workspace_id=payload.get('workspace_id'),
            environment=payload.get('environment'),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await run_in_threadpool(_audit_admin, gw, 'openclaw_dispatch_cancel', {'dispatch_id': dispatch_id, 'ok': response.get('ok'), 'canonical_status': ((response.get('dispatch') or {}).get('canonical_status'))})
    return response


@router.post("/admin/openclaw/dispatches/{dispatch_id}/retry")
async def admin_openclaw_dispatch_retry(dispatch_id: str, request: Request):
    payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    gw = _require_admin(request)
    try:
        response = await run_in_threadpool(
            _ADMIN_SERVICE.retry_openclaw_dispatch,
            gw,
            dispatch_id=dispatch_id,
            actor=str(payload.get('actor') or 'admin'),
            reason=str(payload.get('reason') or ''),
            payload_override=dict(payload.get('payload_override') or {}),
            action_override=str(payload.get('action_override') or ''),
            agent_id_override=str(payload.get('agent_id_override') or ''),
            user_role='admin',
            user_key=str(payload.get('actor') or 'admin'),
            session_id=str(payload.get('session_id') or 'admin:openclaw:retry'),
            tenant_id=payload.get('tenant_id'),
            workspace_id=payload.get('workspace_id'),
            environment=payload.get('environment'),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await run_in_threadpool(_audit_admin, gw, 'openclaw_dispatch_retry', {'dispatch_id': dispatch_id, 'ok': response.get('ok'), 'new_dispatch_id': response.get('dispatch', {}).get('dispatch_id')})
    return response


@router.post("/admin/openclaw/dispatches/{dispatch_id}/reconcile")
async def admin_openclaw_dispatch_reconcile(dispatch_id: str, request: Request):
    payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    gw = _require_admin(request)
    try:
        response = await run_in_threadpool(
            _ADMIN_SERVICE.reconcile_openclaw_dispatch,
            gw,
            dispatch_id=dispatch_id,
            actor=str(payload.get('actor') or 'admin'),
            target_status=str(payload.get('target_status') or payload.get('manual_status') or ''),
            reason=str(payload.get('reason') or ''),
            user_role='admin',
            user_key=str(payload.get('actor') or 'admin'),
            session_id=str(payload.get('session_id') or 'admin:openclaw:reconcile'),
            tenant_id=payload.get('tenant_id'),
            workspace_id=payload.get('workspace_id'),
            environment=payload.get('environment'),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await run_in_threadpool(_audit_admin, gw, 'openclaw_dispatch_reconcile', {'dispatch_id': dispatch_id, 'ok': response.get('ok'), 'canonical_status': ((response.get('dispatch') or {}).get('canonical_status'))})
    return response


@router.post("/admin/openclaw/dispatches/{dispatch_id}/poll")
async def admin_openclaw_dispatch_poll(dispatch_id: str, request: Request):
    payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    gw = _require_admin(request)
    try:
        response = await run_in_threadpool(
            _ADMIN_SERVICE.poll_openclaw_dispatch,
            gw,
            dispatch_id=dispatch_id,
            actor=str(payload.get('actor') or 'admin'),
            reason=str(payload.get('reason') or ''),
            user_role='admin',
            user_key=str(payload.get('actor') or 'admin'),
            session_id=str(payload.get('session_id') or 'admin:openclaw:poll'),
            tenant_id=payload.get('tenant_id'),
            workspace_id=payload.get('workspace_id'),
            environment=payload.get('environment'),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await run_in_threadpool(_audit_admin, gw, 'openclaw_dispatch_poll', {'dispatch_id': dispatch_id, 'ok': response.get('ok'), 'canonical_status': ((response.get('dispatch') or {}).get('canonical_status'))})
    return response


