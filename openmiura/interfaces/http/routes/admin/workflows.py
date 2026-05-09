"""admin/workflows.py — sub-router for the workflows bounded admin domain."""

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


@router.get("/admin/replay/workflows/{workflow_id}")
def admin_workflow_replay(
    workflow_id: str,
    request: Request,
    limit: int = Query(default=200, ge=1, le=500),
    tenant_id: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    environment: str | None = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.workflow_replay(gw, workflow_id=workflow_id, limit=limit, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
    _audit_admin(gw, "workflow_replay", {"workflow_id": workflow_id, "timeline_count": len(response.get("timeline", []))})
    return response


@router.get("/admin/operator/workflows/{workflow_id}")
def admin_operator_workflow(
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
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.operator_console_workflow(
        gw,
        workflow_id=workflow_id,
        limit=limit,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
        q=q,
        status=status,
        kind=kind,
        only_failures=only_failures,
    )
    _audit_admin(gw, "operator_console_workflow", {"workflow_id": workflow_id, "timeline_count": len(response.get("timeline", [])), "kind": kind, "status": status})
    return response


@router.post("/admin/operator/workflows/{workflow_id}/actions/{action}")
def admin_operator_workflow_action(
    workflow_id: str,
    action: str,
    payload: OperatorActionRequest,
    request: Request,
    tenant_id: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    environment: str | None = Query(default=None),
):
    gw = _require_admin(request)
    actor = str(payload.actor or 'admin')
    try:
        response = _ADMIN_SERVICE.operator_console_workflow_action(
            gw,
            workflow_id=workflow_id,
            action=action,
            actor=actor,
            reason=payload.reason,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit_admin(gw, 'operator_console_workflow_action', {'workflow_id': workflow_id, 'action': action, 'actor': actor})
    return response


