"""admin/release.py — sub-router for the release bounded admin domain."""

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
from openmiura.application.auth.totp import TotpNotConfigured

router = APIRouter(tags=["admin"])


@router.get("/admin/releases")
def admin_releases(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    status: Optional[str] = Query(default=None),
    kind: Optional[str] = Query(default=None),
    name: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    payload = _ADMIN_SERVICE.list_releases(
        gw,
        limit=limit,
        status=status,
        kind=kind,
        name=name,
        environment=environment,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )
    _audit_admin(gw, "releases_list", {"count": len(payload.get("items", [])), "status": status, "kind": kind, "environment": environment})
    return payload


@router.get("/admin/releases/{release_id}")
def admin_release_detail(
    release_id: str,
    request: Request,
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    payload = _ADMIN_SERVICE.get_release(gw, release_id=release_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
    _audit_admin(gw, "release_detail", {"release_id": release_id, "ok": payload.get("ok")})
    return payload


@router.post("/admin/releases")
def admin_release_create(payload: ReleaseCreateRequest, request: Request):
    gw = _require_admin(request)
    try:
        response = _ADMIN_SERVICE.create_release(
            gw,
            kind=payload.kind,
            name=payload.name,
            version=payload.version,
            created_by=payload.created_by,
            items=[item.model_dump() for item in payload.items],
            environment=payload.environment,
            tenant_id=payload.tenant_id,
            workspace_id=payload.workspace_id,
            notes=payload.notes,
            metadata=payload.metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit_admin(gw, "release_create", {"release_id": response.get("release", {}).get("release_id"), "kind": payload.kind, "name": payload.name, "version": payload.version})
    return response


@router.post("/admin/releases/{release_id}/submit")
def admin_release_submit(release_id: str, payload: ReleaseActionRequest, request: Request):
    gw = _require_admin(request)
    try:
        response = _ADMIN_SERVICE.submit_release(gw, release_id=release_id, actor=payload.actor, reason=payload.reason, tenant_id=payload.tenant_id, workspace_id=payload.workspace_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="release_not_found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit_admin(gw, "release_submit", {"release_id": release_id, "actor": payload.actor})
    return response


@router.post("/admin/releases/{release_id}/approve")
def admin_release_approve(release_id: str, payload: ReleaseActionRequest, request: Request):
    gw = _require_admin(request)
    # Signature-grade is opt-in PER RELEASE: when a quorum policy is configured
    # the strict path runs (identity + anti-self-approval + TOTP + n-of-m
    # quorum); otherwise the legacy single-approver path is preserved so
    # existing deployments are unchanged.
    strict = gw.audit.get_release_quorum(release_id=release_id, action="approve") is not None
    try:
        if strict:
            response = _ADMIN_SERVICE.cast_release_approval_vote(
                gw, release_id=release_id, actor=payload.actor, reason=payload.reason,
                meaning=payload.meaning, otp_code=payload.otp_code,
                tenant_id=payload.tenant_id, workspace_id=payload.workspace_id,
            )
        else:
            response = _ADMIN_SERVICE.approve_release(gw, release_id=release_id, actor=payload.actor, reason=payload.reason, tenant_id=payload.tenant_id, workspace_id=payload.workspace_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="release_not_found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit_admin(gw, "release_approve", {"release_id": release_id, "actor": payload.actor, "strict": strict, "quorum_met": response.get("quorum_met")})
    return response


@router.post("/admin/releases/{release_id}/quorum")
def admin_release_set_quorum(release_id: str, payload: ReleaseQuorumRequest, request: Request):
    """Configure the signature-grade approval quorum for a release (opt in)."""
    gw = _require_admin(request)
    policy = gw.audit.set_release_quorum(
        release_id=release_id, action=payload.action, required_n=payload.required_n,
        distinct_required=payload.distinct_required, allow_self=payload.allow_self,
        tenant_id=payload.tenant_id, workspace_id=payload.workspace_id, environment=payload.environment,
    )
    _audit_admin(gw, "release_quorum_set", {"release_id": release_id, "action": payload.action, "required_n": payload.required_n})
    return {"ok": True, "quorum": policy}


@router.post("/admin/auth/otp/enroll")
def admin_otp_enroll(payload: OtpEnrollRequest, request: Request):
    """Enrol a TOTP second factor for a user (returns a provisioning URI)."""
    gw = _require_admin(request)
    try:
        result = _ADMIN_SERVICE.enroll_user_totp(gw, user_key=payload.user_key, account_name=payload.account_name)
    except TotpNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    _audit_admin(gw, "otp_enroll", {"user_key": payload.user_key})
    return {"ok": True, **result}


@router.post("/admin/auth/otp/confirm")
def admin_otp_confirm(payload: OtpConfirmRequest, request: Request):
    """Confirm TOTP enrolment with the first code, enabling 2FA for the user."""
    gw = _require_admin(request)
    try:
        result = _ADMIN_SERVICE.confirm_user_totp(gw, user_key=payload.user_key, code=payload.code)
    except TotpNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail="invalid_or_expired_code")
    _audit_admin(gw, "otp_confirm", {"user_key": payload.user_key})
    return result


@router.post("/admin/releases/{release_id}/promote")
def admin_release_promote(release_id: str, payload: ReleaseActionRequest, request: Request):
    gw = _require_admin(request)
    try:
        response = _ADMIN_SERVICE.promote_release(
            gw,
            release_id=release_id,
            to_environment=str(payload.to_environment or "").strip(),
            actor=payload.actor,
            reason=payload.reason,
            tenant_id=payload.tenant_id,
            workspace_id=payload.workspace_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="release_not_found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit_admin(gw, "release_promote", {"release_id": release_id, "actor": payload.actor, "to_environment": payload.to_environment})
    return response


@router.post("/admin/releases/{release_id}/canary")
def admin_release_canary(release_id: str, payload: ReleaseCanaryRequest, request: Request):
    gw = _require_admin(request)
    try:
        response = _ADMIN_SERVICE.configure_release_canary(
            gw,
            release_id=release_id,
            target_environment=payload.target_environment,
            actor=payload.actor,
            strategy=payload.strategy,
            traffic_percent=payload.traffic_percent,
            step_percent=payload.step_percent,
            bake_minutes=payload.bake_minutes,
            status=payload.status,
            metric_guardrails=payload.metric_guardrails,
            analysis_summary=payload.analysis_summary,
            tenant_id=payload.tenant_id,
            workspace_id=payload.workspace_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="release_not_found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit_admin(gw, "release_canary", {"release_id": release_id, "actor": payload.actor, "target_environment": payload.target_environment})
    return response


@router.post("/admin/releases/{release_id}/gates")
def admin_release_gate_run(release_id: str, payload: ReleaseGateRunRequest, request: Request):
    gw = _require_admin(request)
    try:
        response = _ADMIN_SERVICE.record_release_gate_run(
            gw,
            release_id=release_id,
            gate_name=payload.gate_name,
            status=payload.status,
            actor=payload.actor,
            score=payload.score,
            threshold=payload.threshold,
            details=payload.details,
            tenant_id=payload.tenant_id,
            workspace_id=payload.workspace_id,
            environment=payload.environment,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="release_not_found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit_admin(gw, "release_gate_run", {"release_id": release_id, "gate_name": payload.gate_name, "status": payload.status})
    return response


@router.post("/admin/releases/{release_id}/change-report")
def admin_release_change_report(release_id: str, payload: ReleaseChangeReportRequest, request: Request):
    gw = _require_admin(request)
    try:
        response = _ADMIN_SERVICE.set_release_change_report(
            gw,
            release_id=release_id,
            risk_level=payload.risk_level,
            actor=payload.actor,
            summary=payload.summary,
            diff=payload.diff,
            tenant_id=payload.tenant_id,
            workspace_id=payload.workspace_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="release_not_found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit_admin(gw, "release_change_report", {"release_id": release_id, "risk_level": payload.risk_level})
    return response


@router.post("/admin/releases/{release_id}/rollback")
def admin_release_rollback(release_id: str, payload: ReleaseActionRequest, request: Request):
    gw = _require_admin(request)
    try:
        response = _ADMIN_SERVICE.rollback_release(gw, release_id=release_id, actor=payload.actor, reason=payload.reason, tenant_id=payload.tenant_id, workspace_id=payload.workspace_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="release_not_found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit_admin(gw, "release_rollback", {"release_id": release_id, "actor": payload.actor})
    return response


@router.post("/admin/releases/{release_id}/canary/activate")
def admin_release_canary_activate(release_id: str, payload: ReleaseCanaryActivateRequest, request: Request):
    gw = _require_admin(request)
    try:
        response = _ADMIN_SERVICE.activate_release_canary(
            gw,
            release_id=release_id,
            actor=payload.actor,
            baseline_release_id=payload.baseline_release_id,
            tenant_id=payload.tenant_id,
            workspace_id=payload.workspace_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="release_not_found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit_event_id = _audit_admin(gw, "release_canary_activate", {"release_id": release_id, "actor": payload.actor})
    response["audit_event_id"] = audit_event_id
    return response


@router.post("/admin/releases/{release_id}/canary/route")
def admin_release_canary_route(release_id: str, payload: ReleaseCanaryRouteRequest, request: Request):
    gw = _require_admin(request)
    try:
        response = _ADMIN_SERVICE.resolve_release_canary_route(
            gw,
            release_id=release_id,
            routing_key=payload.routing_key,
            actor=payload.actor,
            tenant_id=payload.tenant_id,
            workspace_id=payload.workspace_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="release_not_found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit_event_id = _audit_admin(gw, "release_canary_route", {"release_id": release_id, "actor": payload.actor})
    response["audit_event_id"] = audit_event_id
    return response


@router.post("/admin/releases/canary/decisions/{decision_id}/observe")
def admin_release_canary_observe(decision_id: str, payload: ReleaseCanaryObservationRequest, request: Request):
    gw = _require_admin(request)
    try:
        response = _ADMIN_SERVICE.record_release_canary_observation(
            gw,
            decision_id=decision_id,
            actor=payload.actor,
            success=payload.success,
            latency_ms=payload.latency_ms,
            cost_estimate=payload.cost_estimate,
            metadata=payload.metadata,
            tenant_id=payload.tenant_id,
            workspace_id=payload.workspace_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="routing_decision_not_found") from exc
    audit_event_id = _audit_admin(gw, "release_canary_observe", {"decision_id": decision_id, "actor": payload.actor, "success": payload.success})
    response["audit_event_id"] = audit_event_id
    return response


@router.get("/admin/releases/{release_id}/canary/routing-summary")
def admin_release_canary_routing_summary(release_id: str, request: Request, tenant_id: Optional[str] = Query(default=None), workspace_id: Optional[str] = Query(default=None), target_environment: Optional[str] = Query(default=None)):
    gw = _require_admin(request)
    try:
        response = _ADMIN_SERVICE.release_canary_routing_summary(
            gw,
            release_id=release_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            target_environment=target_environment,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="release_not_found") from exc
    audit_event_id = _audit_admin(gw, "release_canary_routing_summary", {"release_id": release_id})
    response["audit_event_id"] = audit_event_id
    return response


