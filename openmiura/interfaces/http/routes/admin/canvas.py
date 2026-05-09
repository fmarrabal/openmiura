"""admin/canvas.py — sub-router for the canvas bounded admin domain."""

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


@router.get("/admin/canvas/documents")
def admin_canvas_documents(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    status: str | None = Query(default=None),
    tenant_id: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    environment: str | None = Query(default=None),
):
    gw = _get_gw(request)
    _require_admin(request)
    payload = _ADMIN_SERVICE.list_canvas_documents(
        gw,
        limit=limit,
        status=status,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, "canvas_documents_list", {"count": len(payload.get("items", [])), "status": status})
    return payload


@router.post("/admin/canvas/documents")
def admin_canvas_document_create(payload: CanvasCreateRequest, request: Request):
    gw = _get_gw(request)
    _require_admin(request)
    response = _ADMIN_SERVICE.create_canvas_document(
        gw,
        actor=payload.actor,
        title=payload.title,
        description=payload.description,
        status=payload.status,
        metadata=payload.metadata,
        tenant_id=payload.tenant_id,
        workspace_id=payload.workspace_id,
        environment=payload.environment,
    )
    _audit_admin(gw, "canvas_document_create", {"canvas_id": response.get("document", {}).get("canvas_id"), "actor": payload.actor})
    return response


@router.get("/admin/canvas/documents/{canvas_id}")
def admin_canvas_document_detail(
    canvas_id: str,
    request: Request,
    tenant_id: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    environment: str | None = Query(default=None),
):
    gw = _get_gw(request)
    _require_admin(request)
    payload = _ADMIN_SERVICE.get_canvas_document(
        gw,
        canvas_id=canvas_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, "canvas_document_detail", {"canvas_id": canvas_id, "ok": payload.get("ok")})
    return payload


@router.post("/admin/canvas/documents/{canvas_id}/nodes")
def admin_canvas_node_upsert(canvas_id: str, payload: CanvasNodeRequest, request: Request):
    gw = _get_gw(request)
    _require_admin(request)
    try:
        response = _ADMIN_SERVICE.upsert_canvas_node(
            gw,
            canvas_id=canvas_id,
            actor=payload.actor,
            node_id=payload.node_id,
            node_type=payload.node_type,
            label=payload.label,
            position_x=payload.position_x,
            position_y=payload.position_y,
            width=payload.width,
            height=payload.height,
            data=payload.data,
            tenant_id=payload.tenant_id,
            workspace_id=payload.workspace_id,
            environment=payload.environment,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="canvas_not_found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit_admin(gw, "canvas_node_upsert", {"canvas_id": canvas_id, "node_id": response.get("node", {}).get("node_id")})
    return response


@router.post("/admin/canvas/documents/{canvas_id}/edges")
def admin_canvas_edge_upsert(canvas_id: str, payload: CanvasEdgeRequest, request: Request):
    gw = _get_gw(request)
    _require_admin(request)
    try:
        response = _ADMIN_SERVICE.upsert_canvas_edge(
            gw,
            canvas_id=canvas_id,
            actor=payload.actor,
            edge_id=payload.edge_id,
            source_node_id=payload.source_node_id,
            target_node_id=payload.target_node_id,
            label=payload.label,
            edge_type=payload.edge_type,
            data=payload.data,
            tenant_id=payload.tenant_id,
            workspace_id=payload.workspace_id,
            environment=payload.environment,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="canvas_not_found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit_admin(gw, "canvas_edge_upsert", {"canvas_id": canvas_id, "edge_id": response.get("edge", {}).get("edge_id")})
    return response


@router.post("/admin/canvas/documents/{canvas_id}/views")
def admin_canvas_view_save(canvas_id: str, payload: CanvasViewRequest, request: Request):
    gw = _get_gw(request)
    _require_admin(request)
    try:
        response = _ADMIN_SERVICE.save_canvas_view(
            gw,
            canvas_id=canvas_id,
            actor=payload.actor,
            view_id=payload.view_id,
            name=payload.name,
            layout=payload.layout,
            filters=payload.filters,
            is_default=payload.is_default,
            tenant_id=payload.tenant_id,
            workspace_id=payload.workspace_id,
            environment=payload.environment,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="canvas_not_found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit_admin(gw, "canvas_view_save", {"canvas_id": canvas_id, "view_id": response.get("view", {}).get("view_id")})
    return response


@router.post("/admin/canvas/documents/{canvas_id}/presence")
def admin_canvas_presence_update(canvas_id: str, payload: CanvasPresenceRequest, request: Request):
    gw = _get_gw(request)
    _require_admin(request)
    try:
        response = _ADMIN_SERVICE.update_canvas_presence(
            gw,
            canvas_id=canvas_id,
            actor=payload.actor,
            user_key=payload.user_key,
            cursor_x=payload.cursor_x,
            cursor_y=payload.cursor_y,
            selected_node_id=payload.selected_node_id,
            status=payload.status,
            metadata=payload.metadata,
            tenant_id=payload.tenant_id,
            workspace_id=payload.workspace_id,
            environment=payload.environment,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="canvas_not_found") from exc
    _audit_admin(gw, "canvas_presence_update", {"canvas_id": canvas_id, "user_key": payload.user_key})
    return response


@router.get("/admin/canvas/documents/{canvas_id}/comments")
def admin_canvas_comments(
    canvas_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    status: str | None = Query(default=None),
    tenant_id: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    environment: str | None = Query(default=None),
):
    gw = _get_gw(request)
    payload = _ADMIN_SERVICE.list_canvas_comments(
        gw,
        canvas_id=canvas_id,
        limit=limit,
        status=status,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, "canvas_comments", {"canvas_id": canvas_id, "count": len(payload.get("items", []))})
    return payload


@router.post("/admin/canvas/documents/{canvas_id}/comments")
def admin_canvas_comment_create(canvas_id: str, payload: CanvasCommentRequest, request: Request):
    gw = _require_admin(request)
    try:
        response = _ADMIN_SERVICE.add_canvas_comment(
            gw,
            canvas_id=canvas_id,
            actor=payload.actor,
            body=payload.body,
            node_id=payload.node_id,
            status=payload.status,
            metadata=payload.metadata,
            tenant_id=payload.tenant_id,
            workspace_id=payload.workspace_id,
            environment=payload.environment,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="canvas_not_found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit_admin(gw, "canvas_comment_create", {"canvas_id": canvas_id, "comment_id": response.get("comment", {}).get("comment_id")})
    return response


@router.get("/admin/canvas/documents/{canvas_id}/snapshots")
def admin_canvas_snapshots(
    canvas_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    snapshot_kind: str | None = Query(default=None),
    tenant_id: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    environment: str | None = Query(default=None),
):
    gw = _get_gw(request)
    payload = _ADMIN_SERVICE.list_canvas_snapshots(
        gw,
        canvas_id=canvas_id,
        limit=limit,
        snapshot_kind=snapshot_kind,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, "canvas_snapshots", {"canvas_id": canvas_id, "count": len(payload.get("items", []))})
    return payload


@router.post("/admin/canvas/documents/{canvas_id}/snapshots")
def admin_canvas_snapshot_create(canvas_id: str, payload: CanvasSnapshotRequest, request: Request):
    gw = _require_admin(request)
    try:
        response = _ADMIN_SERVICE.create_canvas_snapshot(
            gw,
            canvas_id=canvas_id,
            actor=payload.actor,
            label=payload.label,
            snapshot_kind=payload.snapshot_kind,
            view_id=payload.view_id,
            selected_node_id=payload.selected_node_id,
            metadata=payload.metadata,
            tenant_id=payload.tenant_id,
            workspace_id=payload.workspace_id,
            environment=payload.environment,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="canvas_not_found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit_admin(gw, "canvas_snapshot_create", {"canvas_id": canvas_id, "snapshot_id": response.get("snapshot", {}).get("snapshot_id")})
    return response


@router.post("/admin/canvas/documents/{canvas_id}/share-view")
def admin_canvas_share_view(canvas_id: str, payload: CanvasShareViewRequest, request: Request):
    gw = _require_admin(request)
    try:
        response = _ADMIN_SERVICE.share_canvas_view(
            gw,
            canvas_id=canvas_id,
            actor=payload.actor,
            view_id=payload.view_id,
            label=payload.label,
            selected_node_id=payload.selected_node_id,
            metadata=payload.metadata,
            tenant_id=payload.tenant_id,
            workspace_id=payload.workspace_id,
            environment=payload.environment,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="canvas_not_found") from exc
    _audit_admin(gw, "canvas_share_view", {"canvas_id": canvas_id, "share_token": response.get("share_token")})
    return response


@router.get("/admin/canvas/snapshots/compare")
def admin_canvas_snapshots_compare(
    request: Request,
    snapshot_a_id: str = Query(...),
    snapshot_b_id: str = Query(...),
    tenant_id: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    environment: str | None = Query(default=None),
):
    gw = _get_gw(request)
    payload = _ADMIN_SERVICE.compare_canvas_snapshots(
        gw,
        snapshot_a_id=snapshot_a_id,
        snapshot_b_id=snapshot_b_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, "canvas_snapshots_compare", {"snapshot_a_id": snapshot_a_id, "snapshot_b_id": snapshot_b_id, "ok": payload.get("ok")})
    return payload


@router.get("/admin/canvas/documents/{canvas_id}/presence-events")
def admin_canvas_presence_events(
    canvas_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    tenant_id: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    environment: str | None = Query(default=None),
):
    gw = _get_gw(request)
    payload = _ADMIN_SERVICE.list_canvas_presence_events(
        gw,
        canvas_id=canvas_id,
        limit=limit,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, "canvas_presence_events", {"canvas_id": canvas_id, "count": len(payload.get("items", []))})
    return payload


@router.post("/admin/canvas/documents/{canvas_id}/overlay-state")
def admin_canvas_overlay_state_save(canvas_id: str, payload: CanvasOverlayStateRequest, request: Request):
    gw = _get_gw(request)
    _require_admin(request)
    try:
        response = _ADMIN_SERVICE.save_canvas_overlay_state(
            gw,
            canvas_id=canvas_id,
            actor=payload.actor,
            state_key=payload.state_key,
            toggles=payload.toggles,
            inspector=payload.inspector,
            tenant_id=payload.tenant_id,
            workspace_id=payload.workspace_id,
            environment=payload.environment,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="canvas_not_found") from exc
    _audit_admin(gw, "canvas_overlay_state_save", {"canvas_id": canvas_id, "state_key": payload.state_key})
    return response


@router.get("/admin/canvas/documents/{canvas_id}/overlays")
def admin_canvas_overlays(
    canvas_id: str,
    request: Request,
    selected_node_id: str | None = Query(default=None),
    state_key: str = Query(default='default'),
    limit: int = Query(default=50, ge=1, le=200),
    overlay_policy: bool = Query(default=True),
    overlay_cost: bool = Query(default=True),
    overlay_traces: bool = Query(default=True),
    overlay_failures: bool = Query(default=True),
    overlay_approvals: bool = Query(default=True),
    overlay_secrets: bool = Query(default=True),
    tenant_id: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    environment: str | None = Query(default=None),
):
    gw = _get_gw(request)
    _require_admin(request)
    payload = _ADMIN_SERVICE.get_canvas_operational_overlays(
        gw,
        canvas_id=canvas_id,
        selected_node_id=selected_node_id,
        state_key=state_key,
        limit=limit,
        toggles={
            'policy': overlay_policy,
            'cost': overlay_cost,
            'traces': overlay_traces,
            'failures': overlay_failures,
            'approvals': overlay_approvals,
            'secrets': overlay_secrets,
        },
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, "canvas_overlays", {"canvas_id": canvas_id, "selected_node_id": selected_node_id, "state_key": state_key})
    return payload


@router.get("/admin/canvas/documents/{canvas_id}/views/operational")
def admin_canvas_operational_views(
    canvas_id: str,
    request: Request,
    tenant_id: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    environment: str | None = Query(default=None),
):
    gw = _get_gw(request)
    _require_admin(request)
    payload = _ADMIN_SERVICE.list_canvas_operational_views(
        gw,
        canvas_id=canvas_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, "canvas_operational_views", {"canvas_id": canvas_id, "ok": payload.get("ok")})
    return payload


@router.get("/admin/canvas/documents/{canvas_id}/views/runtime-board")
def admin_canvas_runtime_board(
    canvas_id: str,
    request: Request,
    limit: int = Query(default=10, ge=1, le=100),
    tenant_id: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    environment: str | None = Query(default=None),
):
    gw = _get_gw(request)
    _require_admin(request)
    payload = _ADMIN_SERVICE.get_canvas_runtime_board(
        gw,
        canvas_id=canvas_id,
        limit=limit,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, "canvas_runtime_board", {"canvas_id": canvas_id, "ok": payload.get("ok"), "runtime_count": len(payload.get("items") or [])})
    return payload


@router.get("/admin/canvas/documents/{canvas_id}/views/baseline-promotions")
def admin_canvas_baseline_promotion_board(
    canvas_id: str,
    request: Request,
    limit: int = Query(default=10, ge=1, le=100),
    tenant_id: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    environment: str | None = Query(default=None),
):
    gw = _get_gw(request)
    _require_admin(request)
    payload = _ADMIN_SERVICE.get_canvas_baseline_promotion_board(
        gw,
        canvas_id=canvas_id,
        limit=limit,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, "canvas_baseline_promotion_board", {"canvas_id": canvas_id, "ok": payload.get("ok"), "promotion_count": len(payload.get("items") or [])})
    return payload


@router.get("/admin/canvas/documents/{canvas_id}/nodes/{node_id}/inspector")
def admin_canvas_node_inspector(
    canvas_id: str,
    node_id: str,
    request: Request,
    state_key: str = Query(default='default'),
    limit: int = Query(default=50, ge=1, le=200),
    tenant_id: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    environment: str | None = Query(default=None),
):
    gw = _get_gw(request)
    _require_admin(request)
    payload = _ADMIN_SERVICE.inspect_canvas_node(
        gw,
        canvas_id=canvas_id,
        node_id=node_id,
        state_key=state_key,
        limit=limit,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, "canvas_node_inspector", {"canvas_id": canvas_id, "node_id": node_id, "ok": payload.get("ok")})
    return payload


@router.get("/admin/canvas/documents/{canvas_id}/nodes/{node_id}/timeline")
def admin_canvas_node_timeline(
    canvas_id: str,
    node_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    tenant_id: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    environment: str | None = Query(default=None),
):
    gw = _get_gw(request)
    _require_admin(request)
    payload = _ADMIN_SERVICE.canvas_node_timeline(
        gw,
        canvas_id=canvas_id,
        node_id=node_id,
        limit=limit,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, "canvas_node_timeline", {"canvas_id": canvas_id, "node_id": node_id, "ok": payload.get("ok")})
    return payload


@router.post("/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/{action}")
def admin_canvas_node_action(
    canvas_id: str,
    node_id: str,
    action: str,
    payload: CanvasNodeActionRequest,
    request: Request,
    tenant_id: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    environment: str | None = Query(default=None),
):
    gw = _require_admin(request)
    raw_extra_payload = dict(getattr(payload, 'model_extra', {}) or {})
    merged_payload = dict(raw_extra_payload)
    merged_payload.update(dict(payload.payload or {}))
    try:
        response = _ADMIN_SERVICE.execute_canvas_node_action(
            gw,
            canvas_id=canvas_id,
            node_id=node_id,
            action=action,
            actor=payload.actor,
            reason=payload.reason,
            payload=merged_payload,
            user_role='admin',
            user_key=str(payload.actor or 'admin'),
            session_id=payload.session_id or f'canvas:{canvas_id}',
            tenant_id=tenant_id or payload.tenant_id,
            workspace_id=workspace_id or payload.workspace_id,
            environment=environment or payload.environment,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        status_code = 409 if 'claimed' in str(exc).lower() else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    _audit_admin(gw, "canvas_node_action", {"canvas_id": canvas_id, "node_id": node_id, "action": action, "actor": payload.actor})
    return response


@router.get("/admin/canvas/documents/{canvas_id}/events")
def admin_canvas_events(
    canvas_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    tenant_id: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    environment: str | None = Query(default=None),
):
    gw = _get_gw(request)
    _require_admin(request)
    payload = _ADMIN_SERVICE.list_canvas_events(
        gw,
        canvas_id=canvas_id,
        limit=limit,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, "canvas_events", {"canvas_id": canvas_id, "count": len(payload.get("items", []))})
    return payload


