"""admin/runtime_adapters/governance.py — governance sub-router for runtime adapters."""

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


@router.get("/admin/openclaw/alert-states")
def admin_openclaw_alert_states(
    request: Request,
    runtime_id: Optional[str] = Query(default=None),
    workflow_status: Optional[str] = Query(default=None),
    severity: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=300),
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.list_openclaw_alert_states(gw, runtime_id=runtime_id, workflow_status=workflow_status, severity=severity, limit=limit, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
    _audit_admin(gw, 'openclaw_alert_states', {'count': len(response.get('items', [])), 'runtime_id': runtime_id, 'workflow_status': workflow_status, 'severity': severity})
    return response


@router.get("/admin/openclaw/alert-escalation-approvals")
def admin_openclaw_alert_escalation_approvals(
    request: Request,
    runtime_id: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=300),
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.list_openclaw_alert_escalation_approvals(gw, runtime_id=runtime_id, status=status, limit=limit, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
    _audit_admin(gw, 'openclaw_alert_escalation_approvals', {'count': len(response.get('items', [])), 'runtime_id': runtime_id, 'status': status})
    return response


@router.get("/admin/openclaw/alert-governance/bundles")
def admin_openclaw_alert_governance_bundles(
    request: Request,
    runtime_id: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.list_openclaw_alert_governance_bundles(gw, runtime_id=runtime_id, status=status, limit=limit, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
    _audit_admin(gw, 'openclaw_alert_governance_bundles', {'count': len(response.get('items', [])), 'runtime_id': runtime_id, 'status': status})
    return response


@router.post("/admin/openclaw/alert-governance/bundles")
async def admin_openclaw_alert_governance_bundle_create(request: Request):
    payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    gw = _require_admin(request)
    response = await run_in_threadpool(_ADMIN_SERVICE.create_openclaw_alert_governance_bundle,
        gw,
        name=str(payload.get('name') or 'openclaw-alert-governance-bundle'),
        version=str(payload.get('version') or f"bundle-{int(time.time())}"),
        runtime_ids=[str(item) for item in list(payload.get('runtime_ids') or [])],
        actor=str(payload.get('actor') or 'admin'),
        candidate_policy=dict(payload.get('candidate_policy') or payload.get('policy') or {}),
        merge_with_current=bool(payload.get('merge_with_current', True)),
        waves=list(payload.get('waves') or []),
        wave_size=int(payload.get('wave_size')) if payload.get('wave_size') is not None else None,
        wave_gates=dict(payload.get('wave_gates') or {}),
        wave_timing_policy=dict(payload.get('wave_timing_policy') or payload.get('promotion_health') or {}),
        promotion_slo_policy=dict(payload.get('promotion_slo_policy') or payload.get('slo_policy') or {}),
        progressive_exposure_policy=dict(payload.get('progressive_exposure_policy') or {}),
        reason=str(payload.get('reason') or ''),
        tenant_id=payload.get('tenant_id'),
        workspace_id=payload.get('workspace_id'),
        environment=payload.get('environment'),
        limit=int(payload.get('limit') or 200),
    )
    await run_in_threadpool(_audit_admin, gw, 'openclaw_alert_governance_bundle_create', {'ok': response.get('ok'), 'bundle_id': response.get('bundle_id'), 'target_count': ((response.get('summary') or {}).get('target_count'))})
    return response


@router.get("/admin/openclaw/alert-governance/bundles/{bundle_id}/analytics")
def admin_openclaw_alert_governance_bundle_analytics(
    bundle_id: str,
    request: Request,
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.get_openclaw_alert_governance_bundle_analytics(gw, bundle_id=bundle_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
    _audit_admin(gw, 'openclaw_alert_governance_bundle_analytics', {'bundle_id': bundle_id, 'ok': response.get('ok'), 'rollout_status': ((response.get('summary') or {}).get('rollout_status'))})
    return response


@router.get("/admin/openclaw/alert-governance/bundles/{bundle_id}")
def admin_openclaw_alert_governance_bundle_detail(
    bundle_id: str,
    request: Request,
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.get_openclaw_alert_governance_bundle(gw, bundle_id=bundle_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
    _audit_admin(gw, 'openclaw_alert_governance_bundle_detail', {'bundle_id': bundle_id, 'ok': response.get('ok')})
    return response


@router.post("/admin/openclaw/alert-governance/bundles/{bundle_id}/submit")
async def admin_openclaw_alert_governance_bundle_submit(bundle_id: str, request: Request):
    payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    gw = _require_admin(request)
    response = await run_in_threadpool(_ADMIN_SERVICE.submit_openclaw_alert_governance_bundle,
        gw,
        bundle_id=bundle_id,
        actor=str(payload.get('actor') or 'admin'),
        reason=str(payload.get('reason') or ''),
        tenant_id=payload.get('tenant_id'),
        workspace_id=payload.get('workspace_id'),
        environment=payload.get('environment'),
    )
    await run_in_threadpool(_audit_admin, gw, 'openclaw_alert_governance_bundle_submit', {'bundle_id': bundle_id, 'ok': response.get('ok'), 'release_status': ((response.get('release') or {}).get('status'))})
    return response


@router.post("/admin/openclaw/alert-governance/bundles/{bundle_id}/approve")
async def admin_openclaw_alert_governance_bundle_approve(bundle_id: str, request: Request):
    payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    gw = _require_admin(request)
    response = await run_in_threadpool(_ADMIN_SERVICE.approve_openclaw_alert_governance_bundle,
        gw,
        bundle_id=bundle_id,
        actor=str(payload.get('actor') or 'admin'),
        reason=str(payload.get('reason') or ''),
        tenant_id=payload.get('tenant_id'),
        workspace_id=payload.get('workspace_id'),
        environment=payload.get('environment'),
    )
    await run_in_threadpool(_audit_admin, gw, 'openclaw_alert_governance_bundle_approve', {'bundle_id': bundle_id, 'ok': response.get('ok'), 'release_status': ((response.get('release') or {}).get('status'))})
    return response


@router.post("/admin/openclaw/alert-governance/bundles/{bundle_id}/waves/{wave_no}/run")
async def admin_openclaw_alert_governance_bundle_wave_run(bundle_id: str, wave_no: int, request: Request):
    payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    gw = _require_admin(request)
    response = await run_in_threadpool(_ADMIN_SERVICE.run_openclaw_alert_governance_bundle_wave,
        gw,
        bundle_id=bundle_id,
        wave_no=wave_no,
        actor=str(payload.get('actor') or 'admin'),
        reason=str(payload.get('reason') or ''),
        tenant_id=payload.get('tenant_id'),
        workspace_id=payload.get('workspace_id'),
        environment=payload.get('environment'),
        limit=int(payload.get('limit') or 200),
    )
    await run_in_threadpool(_audit_admin, gw, 'openclaw_alert_governance_bundle_wave_run', {'bundle_id': bundle_id, 'wave_no': wave_no, 'ok': response.get('ok'), 'errors': ((response.get('wave_execution') or {}).get('errors'))})
    return response


@router.get("/admin/openclaw/alert-governance/baseline-catalogs")
def admin_openclaw_alert_governance_baseline_catalogs(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.list_openclaw_alert_governance_baseline_catalogs(gw, limit=limit, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
    _audit_admin(gw, 'openclaw_alert_governance_baseline_catalogs', {'count': len(response.get('items', []))})
    return response


@router.post("/admin/openclaw/alert-governance/baseline-catalogs")
async def admin_openclaw_alert_governance_baseline_catalog_create(request: Request):
    payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    gw = _require_admin(request)
    response = await run_in_threadpool(_ADMIN_SERVICE.create_openclaw_alert_governance_baseline_catalog,
        gw,
        name=str(payload.get('name') or 'openclaw-baseline-catalog'),
        version=str(payload.get('version') or f'catalog-{int(time.time())}'),
        actor=str(payload.get('actor') or 'admin'),
        environment_policy_baselines=dict(payload.get('environment_policy_baselines') or payload.get('policy_baselines') or {}),
        promotion_policy=dict(payload.get('promotion_policy') or {}),
        parent_catalog_id=payload.get('parent_catalog_id'),
        reason=str(payload.get('reason') or ''),
        tenant_id=payload.get('tenant_id'),
        workspace_id=payload.get('workspace_id'),
        environment=payload.get('environment'),
    )
    await run_in_threadpool(_audit_admin, gw, 'openclaw_alert_governance_baseline_catalog_create', {'ok': response.get('ok'), 'catalog_id': response.get('catalog_id')})
    return response


@router.get("/admin/openclaw/alert-governance/baseline-catalogs/{catalog_id}")
def admin_openclaw_alert_governance_baseline_catalog_detail(
    catalog_id: str,
    request: Request,
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.get_openclaw_alert_governance_baseline_catalog(gw, catalog_id=catalog_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
    _audit_admin(gw, 'openclaw_alert_governance_baseline_catalog_detail', {'catalog_id': catalog_id, 'ok': response.get('ok')})
    return response


@router.post("/admin/openclaw/alert-governance/baseline-catalogs/{catalog_id}/promotions/simulate")
async def admin_openclaw_alert_governance_baseline_promotion_simulate(catalog_id: str, request: Request):
    payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    gw = _require_admin(request)
    response = await run_in_threadpool(_ADMIN_SERVICE.simulate_openclaw_alert_governance_baseline_promotion,
        gw,
        catalog_id=catalog_id,
        actor=str(payload.get('actor') or 'admin'),
        candidate_baselines=dict(payload.get('environment_policy_baselines') or payload.get('candidate_baselines') or {}),
        version=payload.get('version'),
        rollout_policy=(dict(payload.get('rollout_policy') or {}) if 'rollout_policy' in payload else None),
        gate_policy=(dict(payload.get('gate_policy') or {}) if 'gate_policy' in payload else None),
        rollback_policy=(dict(payload.get('rollback_policy') or {}) if 'rollback_policy' in payload else None),
        reason=str(payload.get('reason') or ''),
        tenant_id=payload.get('tenant_id'),
        workspace_id=payload.get('workspace_id'),
        environment=payload.get('environment'),
    )
    await run_in_threadpool(_audit_admin, gw, 'openclaw_alert_governance_baseline_promotion_simulate', {'catalog_id': catalog_id, 'ok': response.get('ok'), 'validation_status': ((response.get('validation') or {}).get('status')), 'approvable': ((response.get('summary') or {}).get('approvable'))})
    return response


@router.post("/admin/openclaw/alert-governance/baseline-catalogs/{catalog_id}/promotions")
async def admin_openclaw_alert_governance_baseline_promotion_create(catalog_id: str, request: Request):
    payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    gw = _require_admin(request)
    response = await run_in_threadpool(_ADMIN_SERVICE.create_openclaw_alert_governance_baseline_promotion,
        gw,
        catalog_id=catalog_id,
        actor=str(payload.get('actor') or 'admin'),
        candidate_baselines=dict(payload.get('environment_policy_baselines') or payload.get('candidate_baselines') or {}),
        version=payload.get('version'),
        rollout_policy=(dict(payload.get('rollout_policy') or {}) if 'rollout_policy' in payload else None),
        gate_policy=(dict(payload.get('gate_policy') or {}) if 'gate_policy' in payload else None),
        rollback_policy=(dict(payload.get('rollback_policy') or {}) if 'rollback_policy' in payload else None),
        reason=str(payload.get('reason') or ''),
        tenant_id=payload.get('tenant_id'),
        workspace_id=payload.get('workspace_id'),
        environment=payload.get('environment'),
    )
    await run_in_threadpool(_audit_admin, gw, 'openclaw_alert_governance_baseline_promotion_create', {'catalog_id': catalog_id, 'ok': response.get('ok'), 'promotion_id': response.get('promotion_id')})
    return response


@router.get("/admin/openclaw/alert-governance/baseline-promotions/simulation-custody-dashboard")
def admin_openclaw_alert_governance_baseline_simulation_custody_dashboard(
    request: Request,
    limit: int = Query(default=100, ge=1, le=200),
    only_active: bool = Query(default=False),
    only_blocked: bool = Query(default=False),
    only_escalated: bool = Query(default=False),
    only_suppressed: bool = Query(default=False),
    only_unowned: bool = Query(default=False),
    only_claimed: bool = Query(default=False),
    only_sla_breached: bool = Query(default=False),
    only_handoff_pending: bool = Query(default=False),
    only_sla_rerouted: bool = Query(default=False),
    queue_id: Optional[str] = Query(default=None),
    team_queue_id: Optional[str] = Query(default=None),
    owner_id: Optional[str] = Query(default=None),
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.get_openclaw_alert_governance_baseline_simulation_custody_dashboard(
        gw,
        limit=limit,
        only_active=only_active,
        only_blocked=only_blocked,
        only_escalated=only_escalated,
        only_suppressed=only_suppressed,
        only_unowned=only_unowned,
        only_claimed=only_claimed,
        only_sla_breached=only_sla_breached,
        only_handoff_pending=only_handoff_pending,
        only_sla_rerouted=only_sla_rerouted,
        queue_id=queue_id,
        team_queue_id=team_queue_id,
        owner_id=owner_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, 'openclaw_alert_governance_baseline_simulation_custody_dashboard', {'count': len(response.get('items', [])), 'only_active': only_active, 'only_blocked': only_blocked, 'only_escalated': only_escalated, 'only_suppressed': only_suppressed, 'only_unowned': only_unowned, 'only_claimed': only_claimed, 'only_sla_breached': only_sla_breached, 'only_handoff_pending': only_handoff_pending, 'only_sla_rerouted': only_sla_rerouted, 'queue_id': queue_id, 'team_queue_id': team_queue_id, 'owner_id': owner_id})
    return response


@router.get("/admin/openclaw/alert-governance/baseline-promotions/{promotion_id}")
def admin_openclaw_alert_governance_baseline_promotion_detail(
    promotion_id: str,
    request: Request,
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.get_openclaw_alert_governance_baseline_promotion(gw, promotion_id=promotion_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
    _audit_admin(gw, 'openclaw_alert_governance_baseline_promotion_detail', {'promotion_id': promotion_id, 'ok': response.get('ok')})
    return response


@router.get("/admin/openclaw/alert-governance/baseline-promotions/{promotion_id}/timeline")
def admin_openclaw_alert_governance_baseline_promotion_timeline(
    promotion_id: str,
    request: Request,
    limit: int = Query(default=200, ge=1, le=500),
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.get_openclaw_alert_governance_baseline_promotion_timeline(gw, promotion_id=promotion_id, limit=limit, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
    _audit_admin(gw, 'openclaw_alert_governance_baseline_promotion_timeline', {'promotion_id': promotion_id, 'ok': response.get('ok'), 'count': len(response.get('timeline') or [])})
    return response


@router.post("/admin/openclaw/alert-governance/baseline-promotions/{promotion_id}/attestation-export")
async def admin_openclaw_alert_governance_baseline_promotion_attestation_export(promotion_id: str, request: Request):
    payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    gw = _require_admin(request)
    response = await run_in_threadpool(_ADMIN_SERVICE.export_openclaw_alert_governance_baseline_promotion_attestation,
        gw,
        promotion_id=promotion_id,
        actor=str(payload.get('actor') or 'admin'),
        timeline_limit=int(payload.get('timeline_limit')) if payload.get('timeline_limit') is not None else None,
        tenant_id=payload.get('tenant_id'),
        workspace_id=payload.get('workspace_id'),
        environment=payload.get('environment'),
    )
    await run_in_threadpool(_audit_admin, gw, 'openclaw_alert_governance_baseline_promotion_attestation_export', {'promotion_id': promotion_id, 'ok': response.get('ok')})
    return response


@router.post("/admin/openclaw/alert-governance/baseline-promotions/{promotion_id}/postmortem-export")
async def admin_openclaw_alert_governance_baseline_promotion_postmortem_export(promotion_id: str, request: Request):
    payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    gw = _require_admin(request)
    response = await run_in_threadpool(_ADMIN_SERVICE.export_openclaw_alert_governance_baseline_promotion_postmortem,
        gw,
        promotion_id=promotion_id,
        actor=str(payload.get('actor') or 'admin'),
        timeline_limit=int(payload.get('timeline_limit')) if payload.get('timeline_limit') is not None else None,
        tenant_id=payload.get('tenant_id'),
        workspace_id=payload.get('workspace_id'),
        environment=payload.get('environment'),
    )
    await run_in_threadpool(_audit_admin, gw, 'openclaw_alert_governance_baseline_promotion_postmortem_export', {'promotion_id': promotion_id, 'ok': response.get('ok')})
    return response


@router.post("/admin/openclaw/alert-governance/baseline-promotions/{promotion_id}/actions/{action}")
async def admin_openclaw_alert_governance_baseline_promotion_action(promotion_id: str, action: str, request: Request):
    payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    gw = _require_admin(request)
    normalized_action = str(action or '').strip().lower()
    if normalized_action not in {'approve', 'reject', 'advance', 'rollback', 'pause', 'resume'}:
        return {'ok': False, 'error': 'unsupported_action', 'action': normalized_action, 'promotion_id': promotion_id}
    response = await run_in_threadpool(_ADMIN_SERVICE.decide_openclaw_alert_governance_baseline_promotion,
        gw,
        promotion_id=promotion_id,
        actor=str(payload.get('actor') or 'admin'),
        decision=normalized_action,
        reason=str(payload.get('reason') or ''),
        tenant_id=payload.get('tenant_id'),
        workspace_id=payload.get('workspace_id'),
        environment=payload.get('environment'),
    )
    await run_in_threadpool(_audit_admin, gw, 'openclaw_alert_governance_baseline_promotion_action', {'promotion_id': promotion_id, 'action': normalized_action, 'ok': response.get('ok')})
    return response


@router.post("/admin/openclaw/alert-governance/baseline-promotions/{promotion_id}/simulation-custody-alerts/{action}")
async def admin_openclaw_alert_governance_baseline_simulation_custody_alert_action(promotion_id: str, action: str, request: Request):
    payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    gw = _require_admin(request)
    normalized_action = str(action or '').strip().lower()
    if normalized_action not in {'acknowledge', 'mute', 'unmute', 'resolve', 'claim', 'assign', 'release', 'reroute'}:
        return {'ok': False, 'error': 'unsupported_action', 'action': normalized_action, 'promotion_id': promotion_id}
    response = await run_in_threadpool(_ADMIN_SERVICE.update_openclaw_alert_governance_baseline_simulation_custody_alert,
        gw,
        promotion_id=promotion_id,
        actor=str(payload.get('actor') or 'admin'),
        action=normalized_action,
        alert_id=str(payload.get('alert_id') or '').strip() or None,
        reason=str(payload.get('reason') or ''),
        mute_for_s=int(payload.get('mute_for_s')) if payload.get('mute_for_s') is not None else None,
        owner_id=str(payload.get('owner_id') or '').strip() or None,
        owner_role=str(payload.get('owner_role') or '').strip() or None,
        queue_id=str(payload.get('queue_id') or '').strip() or None,
        queue_label=str(payload.get('queue_label') or '').strip() or None,
        route_id=str(payload.get('route_id') or '').strip() or None,
        route_label=str(payload.get('route_label') or '').strip() or None,
        tenant_id=payload.get('tenant_id'),
        workspace_id=payload.get('workspace_id'),
        environment=payload.get('environment'),
    )
    await run_in_threadpool(_audit_admin, gw, 'openclaw_alert_governance_baseline_simulation_custody_alert_action', {'promotion_id': promotion_id, 'action': normalized_action, 'ok': response.get('ok')})
    return response


@router.get("/admin/openclaw/alert-governance/baseline-advance-jobs")
def admin_openclaw_alert_governance_baseline_advance_jobs(
    request: Request,
    limit: int = Query(default=100, ge=1, le=200),
    promotion_id: Optional[str] = Query(default=None),
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.list_openclaw_alert_governance_baseline_advance_jobs(gw, limit=limit, promotion_id=promotion_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
    _audit_admin(gw, 'openclaw_alert_governance_baseline_advance_jobs', {'promotion_id': promotion_id, 'count': len(response.get('items', []))})
    return response


@router.post("/admin/openclaw/alert-governance/baseline-advance-jobs/run-due")
async def admin_openclaw_alert_governance_baseline_advance_jobs_run_due(request: Request):
    payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    gw = _require_admin(request)
    response = await run_in_threadpool(_ADMIN_SERVICE.run_due_openclaw_alert_governance_baseline_advance_jobs,
        gw,
        actor=str(payload.get('actor') or 'admin'),
        limit=int(payload.get('limit') or 20),
        promotion_id=payload.get('promotion_id'),
        tenant_id=payload.get('tenant_id'),
        workspace_id=payload.get('workspace_id'),
        environment=payload.get('environment'),
    )
    await run_in_threadpool(_audit_admin, gw, 'openclaw_alert_governance_baseline_advance_jobs_run_due', {'promotion_id': payload.get('promotion_id'), 'executed': ((response.get('summary') or {}).get('executed'))})
    return response


@router.get("/admin/openclaw/alert-governance/portfolios")
def admin_openclaw_alert_governance_portfolios(
    request: Request,
    runtime_id: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.list_openclaw_alert_governance_portfolios(gw, runtime_id=runtime_id, status=status, limit=limit, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
    _audit_admin(gw, 'openclaw_alert_governance_portfolios', {'count': len(response.get('items', [])), 'runtime_id': runtime_id, 'status': status})
    return response


@router.post("/admin/openclaw/alert-governance/portfolios")
async def admin_openclaw_alert_governance_portfolio_create(request: Request):
    payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    gw = _require_admin(request)
    train_policy = dict(payload.get('train_policy') or {})
    for extra_key in ('freeze_windows', 'blackout_windows', 'dependency_graph', 'approval_policy', 'security_gate_policy', 'drift_policy', 'export_policy', 'notarization_policy', 'retention_policy', 'escrow_policy', 'signing_policy', 'chain_of_custody_policy', 'custody_anchor_policy', 'verification_gate_policy', 'environment_tier_policies', 'environment_envelopes', 'environment_policy_baselines', 'policy_baselines', 'baseline_catalog_ref', 'baseline_catalog_reference', 'baseline_catalog_overrides', 'deviation_management_policy', 'deviation_policy', 'strict_conflict_check', 'auto_reschedule', 'spacing_s', 'base_release_at', 'default_event_window_s', 'reschedule_buffer_s', 'default_timezone', 'rollout_timezone'):
        if extra_key in payload and payload.get(extra_key) is not None:
            train_policy[extra_key] = payload.get(extra_key)
    response = await run_in_threadpool(_ADMIN_SERVICE.create_openclaw_alert_governance_portfolio,
        gw,
        name=str(payload.get('name') or 'openclaw-alert-governance-portfolio'),
        version=str(payload.get('version') or f"portfolio-{int(time.time())}"),
        bundle_ids=[str(item) for item in list(payload.get('bundle_ids') or [])],
        actor=str(payload.get('actor') or 'admin'),
        train_calendar=list(payload.get('train_calendar') or []),
        train_policy=train_policy,
        reason=str(payload.get('reason') or ''),
        tenant_id=payload.get('tenant_id'),
        workspace_id=payload.get('workspace_id'),
        environment=payload.get('environment'),
    )
    await run_in_threadpool(_audit_admin, gw, 'openclaw_alert_governance_portfolio_create', {'ok': response.get('ok'), 'portfolio_id': response.get('portfolio_id'), 'bundle_count': ((response.get('summary') or {}).get('bundle_count'))})
    return response


@router.get("/admin/openclaw/alert-governance/portfolios/{portfolio_id}")
def admin_openclaw_alert_governance_portfolio_detail(
    portfolio_id: str,
    request: Request,
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.get_openclaw_alert_governance_portfolio(gw, portfolio_id=portfolio_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
    _audit_admin(gw, 'openclaw_alert_governance_portfolio_detail', {'portfolio_id': portfolio_id, 'ok': response.get('ok')})
    return response


@router.post("/admin/openclaw/alert-governance/portfolios/{portfolio_id}/submit")
async def admin_openclaw_alert_governance_portfolio_submit(portfolio_id: str, request: Request):
    payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    gw = _require_admin(request)
    response = await run_in_threadpool(_ADMIN_SERVICE.submit_openclaw_alert_governance_portfolio,
        gw,
        portfolio_id=portfolio_id,
        actor=str(payload.get('actor') or 'admin'),
        reason=str(payload.get('reason') or ''),
        tenant_id=payload.get('tenant_id'),
        workspace_id=payload.get('workspace_id'),
        environment=payload.get('environment'),
    )
    await run_in_threadpool(_audit_admin, gw, 'openclaw_alert_governance_portfolio_submit', {'portfolio_id': portfolio_id, 'ok': response.get('ok'), 'release_status': ((response.get('release') or {}).get('status'))})
    return response


@router.post("/admin/openclaw/alert-governance/portfolios/{portfolio_id}/approve")
async def admin_openclaw_alert_governance_portfolio_approve(portfolio_id: str, request: Request):
    payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    gw = _require_admin(request)
    response = await run_in_threadpool(_ADMIN_SERVICE.approve_openclaw_alert_governance_portfolio,
        gw,
        portfolio_id=portfolio_id,
        actor=str(payload.get('actor') or 'admin'),
        reason=str(payload.get('reason') or ''),
        tenant_id=payload.get('tenant_id'),
        workspace_id=payload.get('workspace_id'),
        environment=payload.get('environment'),
    )
    await run_in_threadpool(_audit_admin, gw, 'openclaw_alert_governance_portfolio_approve', {'portfolio_id': portfolio_id, 'ok': response.get('ok'), 'release_status': ((response.get('release') or {}).get('status'))})
    return response


@router.get("/admin/openclaw/alert-governance/portfolios/{portfolio_id}/calendar")
def admin_openclaw_alert_governance_portfolio_calendar(
    portfolio_id: str,
    request: Request,
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.get_openclaw_alert_governance_portfolio_calendar(gw, portfolio_id=portfolio_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
    _audit_admin(gw, 'openclaw_alert_governance_portfolio_calendar', {'portfolio_id': portfolio_id, 'ok': response.get('ok'), 'count': (((response.get('calendar') or {}).get('summary') or {}).get('count'))})
    return response


@router.post("/admin/openclaw/alert-governance/portfolios/{portfolio_id}/simulate")
async def admin_openclaw_alert_governance_portfolio_simulate(portfolio_id: str, request: Request):
    payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    gw = _require_admin(request)
    response = await run_in_threadpool(_ADMIN_SERVICE.simulate_openclaw_alert_governance_portfolio,
        gw,
        portfolio_id=portfolio_id,
        actor=str(payload.get('actor') or 'admin'),
        now_ts=float(payload.get('now_ts')) if payload.get('now_ts') is not None else None,
        dry_run=bool(payload.get('dry_run', True)),
        auto_reschedule=bool(payload.get('auto_reschedule')) if payload.get('auto_reschedule') is not None else None,
        persist_schedule=bool(payload.get('persist_schedule', False)),
        tenant_id=payload.get('tenant_id'),
        workspace_id=payload.get('workspace_id'),
        environment=payload.get('environment'),
    )
    await run_in_threadpool(_audit_admin, gw, 'openclaw_alert_governance_portfolio_simulate', {'portfolio_id': portfolio_id, 'ok': response.get('ok'), 'validation_status': ((response.get('simulation') or {}).get('validation_status'))})
    return response


@router.get("/admin/openclaw/alert-governance/portfolios/{portfolio_id}/chain-of-custody")
def admin_openclaw_alert_governance_portfolio_chain_of_custody(
    portfolio_id: str,
    request: Request,
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.list_openclaw_alert_governance_portfolio_chain_of_custody(gw, portfolio_id=portfolio_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
    _audit_admin(gw, 'openclaw_alert_governance_portfolio_chain_of_custody', {'portfolio_id': portfolio_id, 'count': len(((response.get('chain_of_custody') or {}).get('items') or []))})
    return response


@router.get("/admin/openclaw/alert-governance/portfolios/{portfolio_id}/custody-anchors")
def admin_openclaw_alert_governance_portfolio_custody_anchors(
    portfolio_id: str,
    request: Request,
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.list_openclaw_alert_governance_portfolio_custody_anchors(gw, portfolio_id=portfolio_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
    _audit_admin(gw, 'openclaw_alert_governance_portfolio_custody_anchors', {'portfolio_id': portfolio_id, 'count': len(((response.get('custody_anchors') or {}).get('items') or []))})
    return response


@router.post("/admin/openclaw/alert-governance/portfolios/{portfolio_id}/custody-anchors/reconcile")
async def admin_openclaw_alert_governance_portfolio_custody_anchors_reconcile(portfolio_id: str, request: Request):
    payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    gw = _require_admin(request)
    response = await run_in_threadpool(_ADMIN_SERVICE.reconcile_openclaw_alert_governance_portfolio_custody_anchors,
        gw,
        portfolio_id=portfolio_id,
        actor=str(payload.get('actor') or 'admin'),
        tenant_id=payload.get('tenant_id'),
        workspace_id=payload.get('workspace_id'),
        environment=payload.get('environment'),
    )
    await run_in_threadpool(_audit_admin, gw, 'openclaw_alert_governance_portfolio_custody_anchors_reconcile', {'portfolio_id': portfolio_id, 'ok': response.get('ok'), 'status': ((response.get('reconciliation') or {}).get('status'))})
    return response


@router.get("/admin/openclaw/alert-governance/portfolios/{portfolio_id}/policy-conformance")
def admin_openclaw_alert_governance_portfolio_policy_conformance(
    portfolio_id: str,
    request: Request,
    actor: Optional[str] = Query(default='system'),
    persist_metadata: bool = Query(default=True),
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.get_openclaw_alert_governance_portfolio_policy_conformance(
        gw,
        portfolio_id=portfolio_id,
        actor=str(actor or 'system'),
        persist_metadata=bool(persist_metadata),
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, 'openclaw_alert_governance_portfolio_policy_conformance', {'portfolio_id': portfolio_id, 'ok': response.get('ok'), 'status': ((response.get('policy_conformance') or {}).get('overall_status'))})
    return response


@router.get("/admin/openclaw/alert-governance/portfolios/{portfolio_id}/policy-baseline-drift")
def admin_openclaw_alert_governance_portfolio_policy_baseline_drift(
    portfolio_id: str,
    request: Request,
    actor: Optional[str] = Query(default='system'),
    persist_metadata: bool = Query(default=True),
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.get_openclaw_alert_governance_portfolio_policy_baseline_drift(
        gw,
        portfolio_id=portfolio_id,
        actor=str(actor or 'system'),
        persist_metadata=bool(persist_metadata),
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, 'openclaw_alert_governance_portfolio_policy_baseline_drift', {'portfolio_id': portfolio_id, 'ok': response.get('ok'), 'status': ((response.get('policy_baseline_drift') or {}).get('overall_status'))})
    return response


@router.get("/admin/openclaw/alert-governance/portfolios/{portfolio_id}/deviation-exceptions")
def admin_openclaw_alert_governance_portfolio_deviation_exceptions(
    portfolio_id: str,
    request: Request,
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.list_openclaw_alert_governance_portfolio_policy_deviation_exceptions(
        gw,
        portfolio_id=portfolio_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, 'openclaw_alert_governance_portfolio_deviation_exceptions', {'portfolio_id': portfolio_id, 'ok': response.get('ok'), 'count': (((response.get('deviation_exceptions') or {}).get('summary') or {}).get('count'))})
    return response


@router.post("/admin/openclaw/alert-governance/portfolios/{portfolio_id}/deviation-exceptions")
async def admin_openclaw_alert_governance_portfolio_deviation_exception_request(portfolio_id: str, request: Request):
    payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    gw = _require_admin(request)
    response = await run_in_threadpool(_ADMIN_SERVICE.request_openclaw_alert_governance_portfolio_policy_deviation_exception,
        gw,
        portfolio_id=portfolio_id,
        deviation_id=str(payload.get('deviation_id') or ''),
        actor=str(payload.get('actor') or 'admin'),
        reason=str(payload.get('reason') or ''),
        ttl_s=payload.get('ttl_s'),
        tenant_id=payload.get('tenant_id'),
        workspace_id=payload.get('workspace_id'),
        environment=payload.get('environment'),
    )
    await run_in_threadpool(_audit_admin, gw, 'openclaw_alert_governance_portfolio_deviation_exception_request', {'portfolio_id': portfolio_id, 'ok': response.get('ok'), 'exception_id': ((response.get('exception') or {}).get('exception_id'))})
    return response


@router.post("/admin/openclaw/alert-governance/portfolio-deviation-approvals/{approval_id}/actions/{action}")
async def admin_openclaw_alert_governance_portfolio_deviation_approval_action(approval_id: str, action: str, request: Request):
    payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    gw = _require_admin(request)
    normalized_action = str(action or '').strip().lower()
    if normalized_action not in {'approve', 'reject'}:
        return {'ok': False, 'error': 'unsupported_action', 'action': normalized_action, 'approval_id': approval_id}
    response = await run_in_threadpool(_ADMIN_SERVICE.decide_openclaw_alert_governance_portfolio_policy_deviation_exception,
        gw,
        approval_id=approval_id,
        actor=str(payload.get('actor') or 'admin'),
        decision=normalized_action,
        reason=str(payload.get('reason') or ''),
        tenant_id=payload.get('tenant_id'),
        workspace_id=payload.get('workspace_id'),
        environment=payload.get('environment'),
    )
    await run_in_threadpool(_audit_admin, gw, 'openclaw_alert_governance_portfolio_deviation_approval_action', {'approval_id': approval_id, 'action': normalized_action, 'ok': response.get('ok')})
    return response


@router.post("/admin/openclaw/alert-governance/portfolios/{portfolio_id}/provider-validation")
async def admin_openclaw_alert_governance_portfolio_provider_validation(portfolio_id: str, request: Request):
    payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    gw = _require_admin(request)
    response = await run_in_threadpool(_ADMIN_SERVICE.validate_openclaw_alert_governance_portfolio_provider_integrations,
        gw,
        portfolio_id=portfolio_id,
        actor=str(payload.get('actor') or 'admin'),
        tenant_id=payload.get('tenant_id'),
        workspace_id=payload.get('workspace_id'),
        environment=payload.get('environment'),
    )
    await run_in_threadpool(_audit_admin, gw, 'openclaw_alert_governance_portfolio_provider_validation', {'portfolio_id': portfolio_id, 'ok': response.get('ok'), 'valid': response.get('valid')})
    return response


@router.post("/admin/openclaw/alert-governance/portfolios/{portfolio_id}/custody-anchors/attest")
async def admin_openclaw_alert_governance_portfolio_custody_anchors_attest(portfolio_id: str, request: Request):
    payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    gw = _require_admin(request)
    response = await run_in_threadpool(_ADMIN_SERVICE.attest_openclaw_alert_governance_portfolio_custody_anchor,
        gw,
        portfolio_id=portfolio_id,
        actor=str(payload.get('actor') or 'admin'),
        package_id=payload.get('package_id'),
        control_plane_id=payload.get('control_plane_id'),
        tenant_id=payload.get('tenant_id'),
        workspace_id=payload.get('workspace_id'),
        environment=payload.get('environment'),
    )
    await run_in_threadpool(_audit_admin, gw, 'openclaw_alert_governance_portfolio_custody_anchors_attest', {'portfolio_id': portfolio_id, 'ok': response.get('ok'), 'package_id': response.get('package_id')})
    return response


@router.get("/admin/openclaw/alert-governance/portfolios/{portfolio_id}/attestations")
def admin_openclaw_alert_governance_portfolio_attestations(
    portfolio_id: str,
    request: Request,
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.list_openclaw_alert_governance_portfolio_attestations(gw, portfolio_id=portfolio_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
    _audit_admin(gw, 'openclaw_alert_governance_portfolio_attestations', {'portfolio_id': portfolio_id, 'count': len(((response.get('attestations') or {}).get('items') or []))})
    return response


@router.get("/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-packages")
def admin_openclaw_alert_governance_portfolio_evidence_packages(
    portfolio_id: str,
    request: Request,
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.list_openclaw_alert_governance_portfolio_evidence_packages(gw, portfolio_id=portfolio_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
    _audit_admin(gw, 'openclaw_alert_governance_portfolio_evidence_packages', {'portfolio_id': portfolio_id, 'count': len(((response.get('evidence_packages') or {}).get('items') or []))})
    return response


@router.post("/admin/openclaw/alert-governance/portfolios/{portfolio_id}/drift-detect")
async def admin_openclaw_alert_governance_portfolio_drift_detect(portfolio_id: str, request: Request):
    payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    gw = _require_admin(request)
    response = await run_in_threadpool(_ADMIN_SERVICE.detect_openclaw_alert_governance_portfolio_drift,
        gw,
        portfolio_id=portfolio_id,
        actor=str(payload.get('actor') or 'admin'),
        tenant_id=payload.get('tenant_id'),
        workspace_id=payload.get('workspace_id'),
        environment=payload.get('environment'),
        persist_metadata=bool(payload.get('persist_metadata', True)),
    )
    await run_in_threadpool(_audit_admin, gw, 'openclaw_alert_governance_portfolio_drift_detect', {'portfolio_id': portfolio_id, 'ok': response.get('ok'), 'overall_status': ((response.get('drift') or {}).get('overall_status'))})
    return response


@router.post("/admin/openclaw/alert-governance/portfolios/{portfolio_id}/attestation-export")
async def admin_openclaw_alert_governance_portfolio_attestation_export(portfolio_id: str, request: Request):
    payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    gw = _require_admin(request)
    response = await run_in_threadpool(_ADMIN_SERVICE.export_openclaw_alert_governance_portfolio_attestation,
        gw,
        portfolio_id=portfolio_id,
        actor=str(payload.get('actor') or 'admin'),
        attestation_id=payload.get('attestation_id'),
        tenant_id=payload.get('tenant_id'),
        workspace_id=payload.get('workspace_id'),
        environment=payload.get('environment'),
    )
    await run_in_threadpool(_audit_admin, gw, 'openclaw_alert_governance_portfolio_attestation_export', {'portfolio_id': portfolio_id, 'ok': response.get('ok'), 'attestation_id': response.get('attestation_id')})
    return response


@router.post("/admin/openclaw/alert-governance/portfolios/{portfolio_id}/postmortem-export")
async def admin_openclaw_alert_governance_portfolio_postmortem_export(portfolio_id: str, request: Request):
    payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    gw = _require_admin(request)
    response = await run_in_threadpool(_ADMIN_SERVICE.export_openclaw_alert_governance_portfolio_postmortem,
        gw,
        portfolio_id=portfolio_id,
        actor=str(payload.get('actor') or 'admin'),
        attestation_id=payload.get('attestation_id'),
        timeline_limit=int(payload.get('timeline_limit')) if payload.get('timeline_limit') is not None else None,
        tenant_id=payload.get('tenant_id'),
        workspace_id=payload.get('workspace_id'),
        environment=payload.get('environment'),
    )
    await run_in_threadpool(_audit_admin, gw, 'openclaw_alert_governance_portfolio_postmortem_export', {'portfolio_id': portfolio_id, 'ok': response.get('ok'), 'attestation_id': response.get('attestation_id')})
    return response


@router.post("/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-package-export")
async def admin_openclaw_alert_governance_portfolio_evidence_package_export(portfolio_id: str, request: Request):
    payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    gw = _require_admin(request)
    response = await run_in_threadpool(_ADMIN_SERVICE.export_openclaw_alert_governance_portfolio_evidence_package,
        gw,
        portfolio_id=portfolio_id,
        actor=str(payload.get('actor') or 'admin'),
        attestation_id=payload.get('attestation_id'),
        timeline_limit=int(payload.get('timeline_limit')) if payload.get('timeline_limit') is not None else None,
        tenant_id=payload.get('tenant_id'),
        workspace_id=payload.get('workspace_id'),
        environment=payload.get('environment'),
    )
    await run_in_threadpool(_audit_admin, gw, 'openclaw_alert_governance_portfolio_evidence_package_export', {'portfolio_id': portfolio_id, 'ok': response.get('ok'), 'package_id': response.get('package_id')})
    return response


@router.post("/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-packages/prune")
async def admin_openclaw_alert_governance_portfolio_evidence_package_prune(portfolio_id: str, request: Request):
    payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    gw = _require_admin(request)
    response = await run_in_threadpool(_ADMIN_SERVICE.prune_openclaw_alert_governance_portfolio_evidence_packages,
        gw,
        portfolio_id=portfolio_id,
        actor=str(payload.get('actor') or 'admin'),
        tenant_id=payload.get('tenant_id'),
        workspace_id=payload.get('workspace_id'),
        environment=payload.get('environment'),
    )
    await run_in_threadpool(_audit_admin, gw, 'openclaw_alert_governance_portfolio_evidence_package_prune', {'portfolio_id': portfolio_id, 'ok': response.get('ok'), 'removed_count': (((response.get('prune') or {}).get('summary') or {}).get('removed_count'))})
    return response


@router.post("/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-artifact-verify")
async def admin_openclaw_alert_governance_portfolio_evidence_artifact_verify(portfolio_id: str, request: Request):
    payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    gw = _require_admin(request)
    response = await run_in_threadpool(_ADMIN_SERVICE.verify_openclaw_alert_governance_portfolio_evidence_artifact,
        gw,
        portfolio_id=portfolio_id,
        actor=str(payload.get('actor') or 'admin'),
        package_id=payload.get('package_id'),
        artifact=payload.get('artifact'),
        artifact_b64=payload.get('artifact_b64'),
        tenant_id=payload.get('tenant_id'),
        workspace_id=payload.get('workspace_id'),
        environment=payload.get('environment'),
    )
    await run_in_threadpool(_audit_admin, gw, 'openclaw_alert_governance_portfolio_evidence_artifact_verify', {'portfolio_id': portfolio_id, 'ok': response.get('ok'), 'package_id': response.get('package_id'), 'verification_status': ((response.get('verification') or {}).get('status'))})
    return response


@router.post("/admin/openclaw/alert-governance/portfolios/{portfolio_id}/evidence-artifact-restore")
async def admin_openclaw_alert_governance_portfolio_evidence_artifact_restore(portfolio_id: str, request: Request):
    payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    gw = _require_admin(request)
    response = await run_in_threadpool(_ADMIN_SERVICE.restore_openclaw_alert_governance_portfolio_evidence_artifact,
        gw,
        portfolio_id=portfolio_id,
        actor=str(payload.get('actor') or 'admin'),
        package_id=payload.get('package_id'),
        artifact=payload.get('artifact'),
        artifact_b64=payload.get('artifact_b64'),
        persist_restore_session=bool(payload.get('persist_restore_session', False)),
        tenant_id=payload.get('tenant_id'),
        workspace_id=payload.get('workspace_id'),
        environment=payload.get('environment'),
    )
    await run_in_threadpool(_audit_admin, gw, 'openclaw_alert_governance_portfolio_evidence_artifact_restore', {'portfolio_id': portfolio_id, 'ok': response.get('ok'), 'package_id': response.get('package_id'), 'restore_id': (((response.get('restore') or {}).get('restore_session') or {}).get('restore_id'))})
    return response


@router.get("/admin/openclaw/alert-governance/portfolios/{portfolio_id}/approvals")
def admin_openclaw_alert_governance_portfolio_approvals(
    portfolio_id: str,
    request: Request,
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=300),
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.list_openclaw_alert_governance_portfolio_approvals(gw, portfolio_id=portfolio_id, status=status, limit=limit, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
    _audit_admin(gw, 'openclaw_alert_governance_portfolio_approvals', {'portfolio_id': portfolio_id, 'count': len(response.get('items', [])), 'status': status})
    return response


@router.post("/admin/openclaw/alert-governance/portfolio-approvals/{approval_id}/actions/{action}")
async def admin_openclaw_alert_governance_portfolio_approval_action(approval_id: str, action: str, request: Request):
    payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    gw = _require_admin(request)
    normalized_action = str(action or '').strip().lower()
    if normalized_action not in {'approve', 'reject'}:
        return {'ok': False, 'error': 'unsupported_action', 'action': normalized_action, 'approval_id': approval_id}
    response = await run_in_threadpool(_ADMIN_SERVICE.decide_openclaw_alert_governance_portfolio_approval,
        gw,
        approval_id=approval_id,
        actor=str(payload.get('actor') or 'admin'),
        decision=normalized_action,
        reason=str(payload.get('reason') or ''),
        tenant_id=payload.get('tenant_id'),
        workspace_id=payload.get('workspace_id'),
        environment=payload.get('environment'),
    )
    await run_in_threadpool(_audit_admin, gw, 'openclaw_alert_governance_portfolio_approval_action', {'approval_id': approval_id, 'action': normalized_action, 'ok': response.get('ok')})
    return response


@router.get("/admin/openclaw/alert-governance/release-train-jobs")
def admin_openclaw_alert_governance_release_train_jobs(
    request: Request,
    portfolio_id: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=300),
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.list_openclaw_release_train_jobs(gw, portfolio_id=portfolio_id, limit=limit, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
    _audit_admin(gw, 'openclaw_alert_governance_release_train_jobs', {'count': len(response.get('items', [])), 'portfolio_id': portfolio_id})
    return response


@router.post("/admin/openclaw/alert-governance/release-train-jobs/run-due")
async def admin_openclaw_alert_governance_release_train_jobs_run_due(request: Request):
    payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    gw = _require_admin(request)
    response = await run_in_threadpool(_ADMIN_SERVICE.run_due_openclaw_release_train_jobs,
        gw,
        actor=str(payload.get('actor') or 'system'),
        limit=int(payload.get('limit') or 20),
        portfolio_id=payload.get('portfolio_id'),
        tenant_id=payload.get('tenant_id'),
        workspace_id=payload.get('workspace_id'),
        environment=payload.get('environment'),
    )
    await run_in_threadpool(_audit_admin, gw, 'openclaw_alert_governance_release_train_jobs_run_due', {'count': len(response.get('items', [])), 'portfolio_id': payload.get('portfolio_id')})
    return response


@router.get("/admin/openclaw/alert-governance/advance-jobs")
def admin_openclaw_alert_governance_advance_jobs(
    request: Request,
    bundle_id: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=300),
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.list_openclaw_alert_governance_advance_jobs(gw, bundle_id=bundle_id, limit=limit, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
    _audit_admin(gw, 'openclaw_alert_governance_advance_jobs', {'count': len(response.get('items', [])), 'bundle_id': bundle_id})
    return response


@router.post("/admin/openclaw/alert-governance/advance-jobs/run-due")
async def admin_openclaw_alert_governance_advance_jobs_run_due(request: Request):
    payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    gw = _require_admin(request)
    response = await run_in_threadpool(_ADMIN_SERVICE.run_due_openclaw_alert_governance_advance_jobs,
        gw,
        actor=str(payload.get('actor') or 'admin'),
        limit=int(payload.get('limit') or 20),
        bundle_id=str(payload.get('bundle_id') or '') or None,
        tenant_id=payload.get('tenant_id'),
        workspace_id=payload.get('workspace_id'),
        environment=payload.get('environment'),
    )
    await run_in_threadpool(_audit_admin, gw, 'openclaw_alert_governance_advance_jobs_run_due', {'executed': ((response.get('summary') or {}).get('executed')), 'bundle_id': payload.get('bundle_id')})
    return response


@router.get("/admin/openclaw/alert-governance-promotion-approvals")
def admin_openclaw_alert_governance_promotion_approvals(
    request: Request,
    runtime_id: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=300),
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.list_openclaw_alert_governance_promotion_approvals(gw, runtime_id=runtime_id, status=status, limit=limit, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
    _audit_admin(gw, 'openclaw_alert_governance_promotion_approvals', {'count': len(response.get('items', [])), 'runtime_id': runtime_id, 'status': status})
    return response


@router.post("/admin/openclaw/alert-governance-promotion-approvals/{approval_id}/decide")
async def admin_openclaw_alert_governance_promotion_approval_decide(approval_id: str, request: Request):
    payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    gw = _require_admin(request)
    response = await run_in_threadpool(_ADMIN_SERVICE.decide_openclaw_alert_governance_promotion_approval,
        gw,
        approval_id=approval_id,
        actor=str(payload.get('actor') or 'system'),
        decision=str(payload.get('decision') or payload.get('action') or 'approve'),
        reason=str(payload.get('reason') or ''),
        tenant_id=payload.get('tenant_id'),
        workspace_id=payload.get('workspace_id'),
        environment=payload.get('environment'),
    )
    await run_in_threadpool(_audit_admin, gw, 'openclaw_alert_governance_promotion_approval_decide', {'approval_id': approval_id, 'ok': response.get('ok'), 'decision': payload.get('decision') or payload.get('action') or 'approve', 'version_id': ((response.get('version') or {}).get('version_id'))})
    return response


@router.get("/admin/openclaw/alert-dispatches")
def admin_openclaw_alert_dispatches(
    request: Request,
    runtime_id: Optional[str] = Query(default=None),
    alert_code: Optional[str] = Query(default=None),
    target_type: Optional[str] = Query(default=None),
    delivery_status: Optional[str] = Query(default=None),
    workflow_action: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=300),
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.list_openclaw_alert_notification_dispatches(gw, runtime_id=runtime_id, alert_code=alert_code, target_type=target_type, delivery_status=delivery_status, workflow_action=workflow_action, limit=limit, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
    _audit_admin(gw, 'openclaw_alert_dispatches', {'runtime_id': runtime_id, 'count': len(response.get('items', [])), 'delivery_status': delivery_status})
    return response


@router.get("/admin/openclaw/alert-delivery-jobs")
def admin_openclaw_alert_delivery_jobs(
    request: Request,
    runtime_id: Optional[str] = Query(default=None),
    enabled: Optional[bool] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=300),
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.list_openclaw_alert_delivery_jobs(gw, runtime_id=runtime_id, enabled=enabled, limit=limit, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
    _audit_admin(gw, 'openclaw_alert_delivery_jobs', {'runtime_id': runtime_id, 'count': len(response.get('items', [])), 'due': ((response.get('summary') or {}).get('due'))})
    return response


@router.post("/admin/openclaw/alert-delivery-jobs/run-due")
async def admin_openclaw_alert_delivery_jobs_run_due(request: Request):
    payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    gw = _require_admin(request)
    response = await run_in_threadpool(_ADMIN_SERVICE.run_due_openclaw_alert_delivery_jobs,
        gw,
        actor=str(payload.get('actor') or 'admin'),
        limit=int(payload.get('limit') or 20),
        runtime_id=payload.get('runtime_id'),
        user_key=str(payload.get('user_key') or payload.get('actor') or 'admin'),
        tenant_id=payload.get('tenant_id'),
        workspace_id=payload.get('workspace_id'),
        environment=payload.get('environment'),
    )
    await run_in_threadpool(_audit_admin, gw, 'openclaw_alert_delivery_jobs_run_due', {'executed': ((response.get('summary') or {}).get('executed')), 'runtime_id': payload.get('runtime_id')})
    return response


@router.post("/admin/openclaw/alert-escalation-approvals/{approval_id}/decide")
async def admin_openclaw_alert_escalation_approval_decide(approval_id: str, request: Request):
    payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
    gw = _require_admin(request)
    response = await run_in_threadpool(_ADMIN_SERVICE.decide_openclaw_alert_escalation_approval,
        gw,
        approval_id=approval_id,
        actor=str(payload.get('actor') or 'admin'),
        decision=str(payload.get('decision') or payload.get('action') or 'approve'),
        reason=str(payload.get('reason') or ''),
        tenant_id=payload.get('tenant_id'),
        workspace_id=payload.get('workspace_id'),
        environment=payload.get('environment'),
    )
    await run_in_threadpool(_audit_admin, gw, 'openclaw_alert_escalation_approval_decide', {'approval_id': approval_id, 'ok': response.get('ok'), 'decision': payload.get('decision') or payload.get('action') or 'approve'})
    return response


