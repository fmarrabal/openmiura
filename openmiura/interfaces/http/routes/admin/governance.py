"""admin/governance.py — sub-router for the governance bounded admin domain."""

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


@router.post("/admin/policies/explain")
def admin_policy_explain(payload: PolicyExplainRequest, request: Request):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.explain_policy(
        gw,
        scope=payload.scope,
        resource_name=payload.resource_name,
        action=payload.action,
        agent_name=payload.agent_name,
        user_role=payload.user_role,
        tenant_id=payload.tenant_id,
        workspace_id=payload.workspace_id,
        environment=payload.environment,
        channel=payload.channel,
        domain=payload.domain,
        extra=payload.extra,
        tool_name=payload.tool_name,
    )
    _audit_admin(gw, "policy_explain", {
        "scope": payload.scope,
        "resource_name": payload.resource_name,
        "requested_action": payload.action,
        "agent_name": payload.agent_name,
        "tool_name": payload.tool_name,
        "user_role": payload.user_role,
    })
    return response


@router.get("/admin/policy-explorer/snapshot")
def admin_policy_explorer_snapshot(request: Request):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.policy_explorer_snapshot(gw)
    _audit_admin(gw, "policy_explorer_snapshot", {"ok": response.get("ok")})
    return response


@router.post("/admin/policy-explorer/simulate")
def admin_policy_explorer_simulate(payload: PolicyExplorerSimulateRequest, request: Request):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.policy_explorer_simulate(
        gw,
        scope=payload.request.scope,
        resource_name=payload.request.resource_name,
        action=payload.request.action,
        agent_name=payload.request.agent_name,
        tool_name=payload.request.tool_name,
        user_role=payload.request.user_role,
        tenant_id=payload.request.tenant_id,
        workspace_id=payload.request.workspace_id,
        environment=payload.request.environment,
        channel=payload.request.channel,
        domain=payload.request.domain,
        extra=payload.request.extra,
        candidate_policy=payload.candidate_policy or None,
        candidate_policy_yaml=payload.candidate_policy_yaml,
    )
    _audit_admin(gw, "policy_explorer_simulate", {"scope": payload.request.scope, "resource_name": payload.request.resource_name, "changed": response.get("changed")})
    return response


@router.post("/admin/policy-explorer/diff")
def admin_policy_explorer_diff(payload: PolicyExplorerDiffRequest, request: Request):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.policy_explorer_diff(
        gw,
        candidate_policy=payload.candidate_policy or None,
        candidate_policy_yaml=payload.candidate_policy_yaml,
        baseline_policy=payload.baseline_policy or None,
        baseline_policy_yaml=payload.baseline_policy_yaml,
        samples=list(payload.samples or []),
    )
    _audit_admin(gw, "policy_explorer_diff", {"ok": response.get("ok"), "sample_count": len(response.get("sample_results") or [])})
    return response


@router.post("/admin/sandbox/explain")
def admin_sandbox_explain(payload: SandboxExplainRequest, request: Request):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.explain_sandbox(
        gw,
        user_role=payload.user_role,
        tenant_id=payload.tenant_id,
        workspace_id=payload.workspace_id,
        environment=payload.environment,
        channel=payload.channel,
        agent_name=payload.agent_name,
        tool_name=payload.tool_name,
    )
    _audit_admin(gw, "sandbox_explain", {
        "user_role": payload.user_role,
        "tenant_id": payload.tenant_id,
        "workspace_id": payload.workspace_id,
        "environment": payload.environment,
        "channel": payload.channel,
        "agent_name": payload.agent_name,
        "tool_name": payload.tool_name,
    })
    return response


@router.post("/admin/security/explain")
def admin_security_explain(payload: SecurityExplainRequest, request: Request):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.explain_security(
        gw,
        scope=payload.scope,
        resource_name=payload.resource_name,
        action=payload.action,
        agent_name=payload.agent_name,
        user_role=payload.user_role,
        tenant_id=payload.tenant_id,
        workspace_id=payload.workspace_id,
        environment=payload.environment,
        channel=payload.channel,
        domain=payload.domain,
        extra=payload.extra,
        tool_name=payload.tool_name,
    )
    audit_event_id = _audit_admin(gw, "security_explain", {
        "scope": payload.scope,
        "resource_name": payload.resource_name,
        "requested_action": payload.action,
        "agent_name": payload.agent_name,
        "tool_name": payload.tool_name,
        "user_role": payload.user_role,
        "tenant_id": payload.tenant_id,
        "workspace_id": payload.workspace_id,
        "environment": payload.environment,
        "channel": payload.channel,
    })
    if audit_event_id is not None and isinstance(response, dict):
        response["audit_event_id"] = audit_event_id
    return response


@router.get("/admin/compliance/summary")
def admin_compliance_summary(
    request: Request,
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
    window_hours: int = Query(default=72, ge=1, le=24 * 30),
    limit_per_section: int = Query(default=20, ge=1, le=200),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.compliance_summary(
        gw,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
        window_hours=window_hours,
        limit_per_section=limit_per_section,
    )
    audit_event_id = _audit_admin(gw, "compliance_summary", {
        "tenant_id": tenant_id,
        "workspace_id": workspace_id,
        "environment": environment,
        "window_hours": window_hours,
        "limit_per_section": limit_per_section,
    })
    response["audit_event_id"] = audit_event_id
    return response


@router.post("/admin/compliance/export")
def admin_compliance_export(payload: ComplianceExportRequest, request: Request):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.export_compliance_report(
        gw,
        tenant_id=payload.tenant_id,
        workspace_id=payload.workspace_id,
        environment=payload.environment,
        window_hours=payload.window_hours,
        limit_per_section=payload.limit_per_section,
        sections=payload.sections,
        report_label=payload.report_label,
    )
    audit_event_id = _audit_admin(gw, "compliance_export", {
        "tenant_id": payload.tenant_id,
        "workspace_id": payload.workspace_id,
        "environment": payload.environment,
        "window_hours": payload.window_hours,
        "limit_per_section": payload.limit_per_section,
        "sections": payload.sections,
        "report_label": payload.report_label,
    })
    response["audit_event_id"] = audit_event_id
    return response


