"""admin/operator.py — sub-router for the operator bounded admin domain."""

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


@router.get("/admin/traces")
def admin_decision_traces(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    session_id: Optional[str] = Query(default=None),
    user_key: Optional[str] = Query(default=None),
    agent_id: Optional[str] = Query(default=None),
    channel: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.list_decision_traces(
        gw,
        limit=limit,
        session_id=session_id,
        user_key=user_key,
        agent_id=agent_id,
        channel=channel,
        status=status,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, "decision_traces", {"limit": limit, "returned": len(response.get("items", []))})
    return response


@router.get("/admin/traces/{trace_id}")
def admin_decision_trace_detail(trace_id: str, request: Request):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.get_decision_trace(gw, trace_id=trace_id)
    _audit_admin(gw, "decision_trace_detail", {"trace_id": trace_id, "ok": response.get("ok")})
    return response


@router.get("/admin/inspector/sessions/{session_id}")
def admin_session_inspector(session_id: str, request: Request, limit: int = Query(default=20, ge=1, le=200)):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.session_inspector(gw, session_id=session_id, limit=limit)
    _audit_admin(gw, "session_inspector", {"session_id": session_id, "trace_count": len(response.get("traces", []))})
    return response


@router.get("/admin/replay/sessions/{session_id}")
def admin_session_replay(
    session_id: str,
    request: Request,
    limit: int = Query(default=200, ge=1, le=500),
    tenant_id: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    environment: str | None = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.session_replay(gw, session_id=session_id, limit=limit, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
    _audit_admin(gw, "session_replay", {"session_id": session_id, "timeline_count": len(response.get("timeline", []))})
    return response


@router.post("/admin/replay/compare")
def admin_replay_compare(payload: ReplayCompareRequest, request: Request):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.replay_compare(
        gw,
        left_kind=payload.left_kind,
        left_id=payload.left_id,
        right_kind=payload.right_kind,
        right_id=payload.right_id,
        limit=payload.limit,
        tenant_id=payload.tenant_id,
        workspace_id=payload.workspace_id,
        environment=payload.environment,
    )
    _audit_admin(gw, "replay_compare", {"left_kind": payload.left_kind, "right_kind": payload.right_kind, "changed": response.get("changed")})
    return response


@router.get("/admin/operator/overview")
def admin_operator_overview(
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
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.operator_console_overview(
        gw,
        limit=limit,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
        q=q,
        status=status,
        kind=kind,
        only_failures=only_failures,
    )
    _audit_admin(gw, "operator_console_overview", {"ok": response.get("ok"), "limit": limit, "kind": kind, "status": status, "only_failures": only_failures})
    return response


@router.get("/admin/operator/sessions/{session_id}")
def admin_operator_session(
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
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.operator_console_session(
        gw,
        session_id=session_id,
        limit=limit,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
        q=q,
        status=status,
        kind=kind,
        only_failures=only_failures,
    )
    _audit_admin(gw, "operator_console_session", {"session_id": session_id, "timeline_count": len(response.get("timeline", [])), "kind": kind, "status": status})
    return response


