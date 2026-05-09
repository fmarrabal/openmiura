"""admin/approvals.py — sub-router for the approvals bounded admin domain."""

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


@router.post("/admin/operator/approvals/{approval_id}/actions/{action}")
def admin_operator_approval_action(
    approval_id: str,
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
        response = _ADMIN_SERVICE.operator_console_approval_action(
            gw,
            approval_id=approval_id,
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
        status_code = 409 if 'claimed' in str(exc).lower() else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    _audit_admin(gw, 'operator_console_approval_action', {'approval_id': approval_id, 'action': action, 'actor': actor})
    return response


