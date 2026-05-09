"""admin/evaluations.py — sub-router for the evaluations bounded admin domain."""

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


@router.get("/admin/evals/suites")
def admin_evaluation_suites(request: Request):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.list_evaluation_suites(gw)
    _audit_admin(gw, "evaluation_suites_list", {"count": len(response.get("suites", []))})
    return response


@router.post("/admin/evals/run")
def admin_evaluation_run(payload: EvaluationRunRequest, request: Request):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.run_evaluation_suite(
        gw,
        suite_name=payload.suite_name,
        observations=[item.model_dump() for item in payload.observations],
        requested_by=payload.requested_by,
        provider=payload.provider,
        model=payload.model,
        agent_name=payload.agent_name,
        tenant_id=payload.tenant_id,
        workspace_id=payload.workspace_id,
        environment=payload.environment,
    )
    _audit_admin(gw, "evaluation_run", {
        "suite_name": payload.suite_name,
        "requested_by": payload.requested_by,
        "status": response.get("status"),
        "run_id": response.get("run_id"),
    })
    return response


@router.get("/admin/evals/runs")
def admin_evaluation_runs(
    request: Request,
    limit: int = Query(default=20, ge=1, le=200),
    suite_name: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    agent_name: Optional[str] = Query(default=None),
    provider: Optional[str] = Query(default=None),
    model: Optional[str] = Query(default=None),
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.list_evaluation_runs(
        gw,
        limit=limit,
        suite_name=suite_name,
        status=status,
        agent_name=agent_name,
        provider=provider,
        model=model,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, "evaluation_runs_list", {"limit": limit, "suite_name": suite_name, "status": status, "agent_name": agent_name, "provider": provider, "model": model, "returned": len(response.get("items", []))})
    return response


@router.get("/admin/evals/runs/{run_id}")
def admin_evaluation_run_detail(run_id: str, request: Request):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.get_evaluation_run(gw, run_id=run_id)
    _audit_admin(gw, "evaluation_run_detail", {"run_id": run_id, "ok": response.get("ok")})
    return response


@router.get("/admin/evals/runs/{run_id}/compare")
def admin_evaluation_run_compare(run_id: str, request: Request, baseline_run_id: Optional[str] = Query(default=None)):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.compare_evaluation_run(gw, run_id=run_id, baseline_run_id=baseline_run_id)
    _audit_admin(gw, "evaluation_run_compare", {"run_id": run_id, "baseline_run_id": baseline_run_id, "ok": response.get("ok")})
    return response


@router.get("/admin/evals/regressions")
def admin_evaluation_regressions(
    request: Request,
    limit: int = Query(default=20, ge=1, le=200),
    suite_name: Optional[str] = Query(default=None),
    agent_name: Optional[str] = Query(default=None),
    provider: Optional[str] = Query(default=None),
    model: Optional[str] = Query(default=None),
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.list_evaluation_regressions(
        gw,
        limit=limit,
        suite_name=suite_name,
        agent_name=agent_name,
        provider=provider,
        model=model,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, "evaluation_regressions_list", {"limit": limit, "returned": len(response.get("items", []))})
    return response


@router.get("/admin/evals/scorecards")
def admin_evaluation_scorecards(
    request: Request,
    group_by: str = Query(default="agent_provider_model"),
    limit: int = Query(default=20, ge=1, le=200),
    suite_name: Optional[str] = Query(default=None),
    agent_name: Optional[str] = Query(default=None),
    provider: Optional[str] = Query(default=None),
    model: Optional[str] = Query(default=None),
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.evaluation_scorecards(
        gw,
        group_by=group_by,
        limit=limit,
        suite_name=suite_name,
        agent_name=agent_name,
        provider=provider,
        model=model,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, "evaluation_scorecards", {"group_by": group_by, "returned": len(response.get("items", []))})
    return response


@router.get("/admin/evals/leaderboard")
def admin_evaluation_leaderboard(
    request: Request,
    group_by: str = Query(default="agent_provider_model"),
    rank_by: str = Query(default="stability_score"),
    limit: int = Query(default=20, ge=1, le=200),
    use_case: Optional[str] = Query(default=None),
    suite_name: Optional[str] = Query(default=None),
    agent_name: Optional[str] = Query(default=None),
    provider: Optional[str] = Query(default=None),
    model: Optional[str] = Query(default=None),
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.evaluation_leaderboard(
        gw,
        group_by=group_by,
        rank_by=rank_by,
        limit=limit,
        use_case=use_case,
        suite_name=suite_name,
        agent_name=agent_name,
        provider=provider,
        model=model,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, "evaluation_leaderboard", {"group_by": group_by, "rank_by": rank_by, "returned": len(response.get("items", []))})
    return response


@router.get("/admin/evals/comparison")
def admin_evaluation_comparison(
    request: Request,
    split_by: str = Query(default="use_case"),
    compare_by: str = Query(default="agent_provider_model"),
    rank_by: str = Query(default="stability_score"),
    limit_groups: int = Query(default=20, ge=1, le=200),
    limit_per_group: int = Query(default=5, ge=1, le=50),
    suite_name: Optional[str] = Query(default=None),
    agent_name: Optional[str] = Query(default=None),
    provider: Optional[str] = Query(default=None),
    model: Optional[str] = Query(default=None),
    tenant_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    environment: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.evaluation_comparison(
        gw,
        split_by=split_by,
        compare_by=compare_by,
        rank_by=rank_by,
        limit_groups=limit_groups,
        limit_per_group=limit_per_group,
        suite_name=suite_name,
        agent_name=agent_name,
        provider=provider,
        model=model,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, "evaluation_comparison", {"split_by": split_by, "compare_by": compare_by, "rank_by": rank_by, "returned": len(response.get("groups", []))})
    return response


