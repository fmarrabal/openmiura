"""admin/cost_governance.py — sub-router for the cost_governance bounded admin domain."""

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


@router.get("/admin/costs/summary")
def admin_cost_summary(
    request: Request,
    group_by: str = Query(default="tenant"),
    limit: int = Query(default=20, ge=1, le=200),
    window_hours: int = Query(default=24 * 30, ge=1, le=24 * 365),
    workflow_name: Optional[str] = Query(default=None),
    agent_name: Optional[str] = Query(default=None),
    provider: Optional[str] = Query(default=None),
    model: Optional[str] = Query(default=None),
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.cost_summary(
        gw,
        group_by=group_by,
        limit=limit,
        window_hours=window_hours,
        workflow_name=workflow_name,
        agent_name=agent_name,
        provider=provider,
        model=model,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, "cost_summary", {"group_by": group_by, "window_hours": window_hours, "returned": len(response.get("items", []))})
    return response


@router.get("/admin/costs/budgets")
def admin_cost_budgets(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.cost_budgets(
        gw,
        limit=limit,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, "cost_budgets", {"returned": len(response.get("items", []))})
    return response


@router.get("/admin/costs/alerts")
def admin_cost_alerts(
    request: Request,
    severity: str = Query(default="all"),
    limit: int = Query(default=50, ge=1, le=200),
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.cost_alerts(
        gw,
        severity=severity,
        limit=limit,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, "cost_alerts", {"severity": severity, "returned": len(response.get("items", []))})
    return response


