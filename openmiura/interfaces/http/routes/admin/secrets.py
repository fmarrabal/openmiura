"""admin/secrets.py — sub-router for the secrets bounded admin domain."""

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


@router.get("/admin/config-center/secrets-wizard")
def admin_config_center_secrets_wizard(request: Request, env_prefix: Optional[str] = Query(default='OPENMIURA')):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.secret_env_reference_wizard_snapshot(gw, env_prefix=env_prefix or 'OPENMIURA')
    _audit_admin(gw, "config_center_secrets_wizard_read", {"profiles": [item.get("name") for item in response.get("profiles", [])], "env_prefix": response.get("env_prefix")})
    return response


@router.post("/admin/config-center/secrets-wizard/validate")
def admin_config_center_secrets_wizard_validate(payload: SecretEnvWizardValidateRequest, request: Request):
    gw = _require_admin(request)
    try:
        response = _ADMIN_SERVICE.validate_secret_env_references(
            gw,
            profile=payload.profile,
            content=payload.content,
            wizard_payload=payload.wizard_payload,
            env_prefix=payload.env_prefix,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except yaml.YAMLError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit_admin(gw, "config_center_secrets_wizard_validate", {"profile": response.get("profile"), "configured": response.get("profile_status", {}).get("configured")})
    return response


@router.post("/admin/config-center/secrets-wizard/save")
def admin_config_center_secrets_wizard_save(payload: SecretEnvWizardSaveRequest, request: Request):
    gw = _require_admin(request)
    try:
        response = _ADMIN_SERVICE.save_secret_env_references(
            gw,
            profile=payload.profile,
            content=payload.content,
            wizard_payload=payload.wizard_payload,
            env_prefix=payload.env_prefix,
            reload_after_save=payload.reload_after_save,
            actor=payload.actor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except yaml.YAMLError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit_admin(gw, "config_center_secrets_wizard_save", {"profile": response.get("profile"), "restart_required": response.get("restart_required")})
    return response


@router.get("/admin/secrets/summary")
def admin_secret_governance_summary(
    request: Request,
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.secret_governance_summary(
        gw,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
        limit=limit,
    )
    _audit_admin(gw, "secret_governance_summary", {"total_events": (response.get("summary") or {}).get("total_events", 0), "denied_events": (response.get("summary") or {}).get("denied_events", 0)})
    return response


@router.get("/admin/secrets/timeline")
def admin_secret_governance_timeline(
    request: Request,
    q: Optional[str] = Query(default=None),
    ref: Optional[str] = Query(default=None),
    tool_name: Optional[str] = Query(default=None),
    outcome: Optional[str] = Query(default=None),
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.secret_governance_timeline(
        gw,
        q=q,
        ref=ref,
        tool_name=tool_name,
        outcome=outcome,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
        limit=limit,
    )
    _audit_admin(gw, "secret_governance_timeline", {"ref": ref, "tool_name": tool_name, "outcome": outcome, "items": len(response.get("items") or [])})
    return response


@router.get("/admin/secrets/catalog")
def admin_secret_governance_catalog(
    request: Request,
    q: Optional[str] = Query(default=None),
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.secret_governance_catalog(
        gw,
        q=q,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
        limit=limit,
    )
    _audit_admin(gw, "secret_governance_catalog", {"q": q, "limit": limit, "visible_refs": len(response.get("items") or [])})
    return response


@router.get("/admin/secrets/usage")
def admin_secret_governance_usage(
    request: Request,
    q: Optional[str] = Query(default=None),
    ref: Optional[str] = Query(default=None),
    tool_name: Optional[str] = Query(default=None),
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.secret_governance_usage(
        gw,
        q=q,
        ref=ref,
        tool_name=tool_name,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
        limit=limit,
    )
    _audit_admin(gw, "secret_governance_usage", {"ref": ref, "tool_name": tool_name, "groups": len(response.get("items") or [])})
    return response


@router.post("/admin/secrets/explain")
def admin_secret_governance_explain(payload: SecretGovernanceExplainRequest, request: Request):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.secret_governance_explain(
        gw,
        ref=payload.ref,
        tool_name=payload.tool_name,
        user_role=payload.user_role or 'user',
        tenant_id=payload.tenant_id,
        workspace_id=payload.workspace_id,
        environment=payload.environment,
        domain=payload.domain,
    )
    _audit_admin(gw, "secret_governance_explain", {"ref": payload.ref, "tool_name": payload.tool_name, "allowed": response.get("allowed")})
    return response


