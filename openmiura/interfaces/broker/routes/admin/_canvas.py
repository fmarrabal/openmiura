"""admin/_canvas.py - broker admin sub-routes for the canvas domain."""
from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from openmiura.application.admin import AdminService
from openmiura.application.auth.service import AuthService
from openmiura.application.tenancy.service import TenancyService
from openmiura.interfaces.broker.common import (
    audit_sensitive,
    metrics_summary,
    require_csrf,
    require_permission,
)




def register_routes(router, tenancy_service) -> None:
    """Attach the canvas broker admin endpoints to *router*."""
    @router.get("/admin/canvas/documents")
    def broker_admin_canvas_documents(
        request: Request,
        limit: int = Query(default=50, ge=1, le=200),
        status: str | None = Query(default=None),
        tenant_id: str | None = Query(default=None),
        workspace_id: str | None = Query(default=None),
        environment: str | None = Query(default=None),
    ):
        gw, auth_ctx = require_permission(request, "admin.read")
        response = AdminService().list_canvas_documents(
            gw,
            limit=limit,
            status=status,
            tenant_id=tenant_id or auth_ctx.get("tenant_id"),
            workspace_id=workspace_id or auth_ctx.get("workspace_id"),
            environment=environment or auth_ctx.get("environment"),
        )
        audit_sensitive(gw, action="admin_canvas_documents", auth_ctx=auth_ctx, status="ok", details={"count": len(response.get("items", [])), "status": status})
        return response

    @router.post("/admin/canvas/documents")
    async def broker_admin_canvas_document_create(request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json()
        response = AdminService().create_canvas_document(
            gw,
            actor=str(payload.get("actor") or auth_ctx.get("username") or "broker-admin"),
            title=str(payload.get("title") or ""),
            description=str(payload.get("description") or ""),
            status=str(payload.get("status") or "active"),
            metadata=dict(payload.get("metadata") or {}),
            tenant_id=payload.get("tenant_id") or auth_ctx.get("tenant_id"),
            workspace_id=payload.get("workspace_id") or auth_ctx.get("workspace_id"),
            environment=payload.get("environment") or auth_ctx.get("environment"),
        )
        audit_sensitive(gw, action="admin_canvas_document_create", auth_ctx=auth_ctx, status="ok", target=response.get("document", {}).get("canvas_id"))
        return response

    @router.get("/admin/canvas/documents/{canvas_id}")
    def broker_admin_canvas_document_detail(
        canvas_id: str,
        request: Request,
        tenant_id: str | None = Query(default=None),
        workspace_id: str | None = Query(default=None),
        environment: str | None = Query(default=None),
    ):
        gw, auth_ctx = require_permission(request, "admin.read")
        response = AdminService().get_canvas_document(
            gw,
            canvas_id=canvas_id,
            tenant_id=tenant_id or auth_ctx.get("tenant_id"),
            workspace_id=workspace_id or auth_ctx.get("workspace_id"),
            environment=environment or auth_ctx.get("environment"),
        )
        audit_sensitive(gw, action="admin_canvas_document_detail", auth_ctx=auth_ctx, status="ok" if response.get("ok") else "missing", target=canvas_id)
        return response

    @router.post("/admin/canvas/documents/{canvas_id}/nodes")
    async def broker_admin_canvas_node_upsert(canvas_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json()
        try:
            response = AdminService().upsert_canvas_node(
                gw,
                canvas_id=canvas_id,
                actor=str(payload.get("actor") or auth_ctx.get("username") or "broker-admin"),
                node_id=payload.get("node_id"),
                node_type=str(payload.get("node_type") or "note"),
                label=str(payload.get("label") or ""),
                position_x=float(payload.get("position_x") or 0.0),
                position_y=float(payload.get("position_y") or 0.0),
                width=float(payload.get("width") or 240.0),
                height=float(payload.get("height") or 120.0),
                data=dict(payload.get("data") or {}),
                tenant_id=payload.get("tenant_id") or auth_ctx.get("tenant_id"),
                workspace_id=payload.get("workspace_id") or auth_ctx.get("workspace_id"),
                environment=payload.get("environment") or auth_ctx.get("environment"),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="canvas_not_found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit_sensitive(gw, action="admin_canvas_node_upsert", auth_ctx=auth_ctx, status="ok", target=response.get("node", {}).get("node_id"))
        return response

    @router.post("/admin/canvas/documents/{canvas_id}/edges")
    async def broker_admin_canvas_edge_upsert(canvas_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json()
        try:
            response = AdminService().upsert_canvas_edge(
                gw,
                canvas_id=canvas_id,
                actor=str(payload.get("actor") or auth_ctx.get("username") or "broker-admin"),
                edge_id=payload.get("edge_id"),
                source_node_id=str(payload.get("source_node_id") or ""),
                target_node_id=str(payload.get("target_node_id") or ""),
                label=str(payload.get("label") or ""),
                edge_type=str(payload.get("edge_type") or "default"),
                data=dict(payload.get("data") or {}),
                tenant_id=payload.get("tenant_id") or auth_ctx.get("tenant_id"),
                workspace_id=payload.get("workspace_id") or auth_ctx.get("workspace_id"),
                environment=payload.get("environment") or auth_ctx.get("environment"),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="canvas_not_found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit_sensitive(gw, action="admin_canvas_edge_upsert", auth_ctx=auth_ctx, status="ok", target=response.get("edge", {}).get("edge_id"))
        return response

    @router.post("/admin/canvas/documents/{canvas_id}/views")
    async def broker_admin_canvas_view_save(canvas_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json()
        try:
            response = AdminService().save_canvas_view(
                gw,
                canvas_id=canvas_id,
                actor=str(payload.get("actor") or auth_ctx.get("username") or "broker-admin"),
                view_id=payload.get("view_id"),
                name=str(payload.get("name") or "Default"),
                layout=dict(payload.get("layout") or {}),
                filters=dict(payload.get("filters") or {}),
                is_default=bool(payload.get("is_default") or False),
                tenant_id=payload.get("tenant_id") or auth_ctx.get("tenant_id"),
                workspace_id=payload.get("workspace_id") or auth_ctx.get("workspace_id"),
                environment=payload.get("environment") or auth_ctx.get("environment"),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="canvas_not_found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit_sensitive(gw, action="admin_canvas_view_save", auth_ctx=auth_ctx, status="ok", target=response.get("view", {}).get("view_id"))
        return response

    @router.post("/admin/canvas/documents/{canvas_id}/presence")
    async def broker_admin_canvas_presence_update(canvas_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json()
        try:
            response = AdminService().update_canvas_presence(
                gw,
                canvas_id=canvas_id,
                actor=str(payload.get("actor") or auth_ctx.get("username") or "broker-admin"),
                user_key=str(payload.get("user_key") or auth_ctx.get("username") or "operator"),
                cursor_x=float(payload.get("cursor_x") or 0.0),
                cursor_y=float(payload.get("cursor_y") or 0.0),
                selected_node_id=payload.get("selected_node_id"),
                status=str(payload.get("status") or "active"),
                metadata=dict(payload.get("metadata") or {}),
                tenant_id=payload.get("tenant_id") or auth_ctx.get("tenant_id"),
                workspace_id=payload.get("workspace_id") or auth_ctx.get("workspace_id"),
                environment=payload.get("environment") or auth_ctx.get("environment"),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="canvas_not_found") from exc
        audit_sensitive(gw, action="admin_canvas_presence_update", auth_ctx=auth_ctx, status="ok", target=response.get("presence", {}).get("presence_id"))
        return response

    @router.get("/admin/canvas/documents/{canvas_id}/comments")
    def broker_admin_canvas_comments(
        canvas_id: str,
        request: Request,
        limit: int = Query(default=50, ge=1, le=200),
        status: str | None = Query(default=None),
        tenant_id: str | None = Query(default=None),
        workspace_id: str | None = Query(default=None),
        environment: str | None = Query(default=None),
    ):
        gw, auth_ctx = require_permission(request, "admin.read")
        response = AdminService().list_canvas_comments(
            gw,
            canvas_id=canvas_id,
            limit=limit,
            status=status,
            tenant_id=tenant_id or auth_ctx.get("tenant_id"),
            workspace_id=workspace_id or auth_ctx.get("workspace_id"),
            environment=environment or auth_ctx.get("environment"),
        )
        audit_sensitive(gw, action="admin_canvas_comments", auth_ctx=auth_ctx, status="ok", target=canvas_id, details={"count": len(response.get("items", []))})
        return response

    @router.post("/admin/canvas/documents/{canvas_id}/comments")
    async def broker_admin_canvas_comment_create(canvas_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json()
        try:
            response = AdminService().add_canvas_comment(
                gw,
                canvas_id=canvas_id,
                actor=str(payload.get("actor") or auth_ctx.get("username") or "broker-admin"),
                body=str(payload.get("body") or ""),
                node_id=payload.get("node_id"),
                status=str(payload.get("status") or "active"),
                metadata=dict(payload.get("metadata") or {}),
                tenant_id=payload.get("tenant_id") or auth_ctx.get("tenant_id"),
                workspace_id=payload.get("workspace_id") or auth_ctx.get("workspace_id"),
                environment=payload.get("environment") or auth_ctx.get("environment"),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="canvas_not_found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit_sensitive(gw, action="admin_canvas_comment_create", auth_ctx=auth_ctx, status="ok", target=canvas_id, details={"comment_id": response.get("comment", {}).get("comment_id")})
        return response

    @router.get("/admin/canvas/documents/{canvas_id}/snapshots")
    def broker_admin_canvas_snapshots(
        canvas_id: str,
        request: Request,
        limit: int = Query(default=50, ge=1, le=200),
        snapshot_kind: str | None = Query(default=None),
        tenant_id: str | None = Query(default=None),
        workspace_id: str | None = Query(default=None),
        environment: str | None = Query(default=None),
    ):
        gw, auth_ctx = require_permission(request, "admin.read")
        response = AdminService().list_canvas_snapshots(
            gw,
            canvas_id=canvas_id,
            limit=limit,
            snapshot_kind=snapshot_kind,
            tenant_id=tenant_id or auth_ctx.get("tenant_id"),
            workspace_id=workspace_id or auth_ctx.get("workspace_id"),
            environment=environment or auth_ctx.get("environment"),
        )
        audit_sensitive(gw, action="admin_canvas_snapshots", auth_ctx=auth_ctx, status="ok", target=canvas_id, details={"count": len(response.get("items", []))})
        return response

    @router.post("/admin/canvas/documents/{canvas_id}/snapshots")
    async def broker_admin_canvas_snapshot_create(canvas_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json()
        try:
            response = AdminService().create_canvas_snapshot(
                gw,
                canvas_id=canvas_id,
                actor=str(payload.get("actor") or auth_ctx.get("username") or "broker-admin"),
                label=str(payload.get("label") or ""),
                snapshot_kind=str(payload.get("snapshot_kind") or "manual"),
                view_id=payload.get("view_id"),
                selected_node_id=payload.get("selected_node_id"),
                metadata=dict(payload.get("metadata") or {}),
                tenant_id=payload.get("tenant_id") or auth_ctx.get("tenant_id"),
                workspace_id=payload.get("workspace_id") or auth_ctx.get("workspace_id"),
                environment=payload.get("environment") or auth_ctx.get("environment"),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="canvas_not_found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit_sensitive(gw, action="admin_canvas_snapshot_create", auth_ctx=auth_ctx, status="ok", target=canvas_id, details={"snapshot_id": response.get("snapshot", {}).get("snapshot_id")})
        return response

    @router.post("/admin/canvas/documents/{canvas_id}/share-view")
    async def broker_admin_canvas_share_view(canvas_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json()
        try:
            response = AdminService().share_canvas_view(
                gw,
                canvas_id=canvas_id,
                actor=str(payload.get("actor") or auth_ctx.get("username") or "broker-admin"),
                view_id=payload.get("view_id"),
                label=str(payload.get("label") or "Shared view"),
                selected_node_id=payload.get("selected_node_id"),
                metadata=dict(payload.get("metadata") or {}),
                tenant_id=payload.get("tenant_id") or auth_ctx.get("tenant_id"),
                workspace_id=payload.get("workspace_id") or auth_ctx.get("workspace_id"),
                environment=payload.get("environment") or auth_ctx.get("environment"),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="canvas_not_found") from exc
        audit_sensitive(gw, action="admin_canvas_share_view", auth_ctx=auth_ctx, status="ok", target=canvas_id, details={"share_token": response.get("share_token")})
        return response

    @router.get("/admin/canvas/snapshots/compare")
    def broker_admin_canvas_snapshots_compare(
        request: Request,
        snapshot_a_id: str = Query(...),
        snapshot_b_id: str = Query(...),
        tenant_id: str | None = Query(default=None),
        workspace_id: str | None = Query(default=None),
        environment: str | None = Query(default=None),
    ):
        gw, auth_ctx = require_permission(request, "admin.read")
        response = AdminService().compare_canvas_snapshots(
            gw,
            snapshot_a_id=snapshot_a_id,
            snapshot_b_id=snapshot_b_id,
            tenant_id=tenant_id or auth_ctx.get("tenant_id"),
            workspace_id=workspace_id or auth_ctx.get("workspace_id"),
            environment=environment or auth_ctx.get("environment"),
        )
        audit_sensitive(gw, action="admin_canvas_snapshots_compare", auth_ctx=auth_ctx, status="ok" if response.get("ok") else "missing", details={"snapshot_a_id": snapshot_a_id, "snapshot_b_id": snapshot_b_id})
        return response

    @router.get("/admin/canvas/documents/{canvas_id}/presence-events")
    def broker_admin_canvas_presence_events(
        canvas_id: str,
        request: Request,
        limit: int = Query(default=50, ge=1, le=200),
        tenant_id: str | None = Query(default=None),
        workspace_id: str | None = Query(default=None),
        environment: str | None = Query(default=None),
    ):
        gw, auth_ctx = require_permission(request, "admin.read")
        response = AdminService().list_canvas_presence_events(
            gw,
            canvas_id=canvas_id,
            limit=limit,
            tenant_id=tenant_id or auth_ctx.get("tenant_id"),
            workspace_id=workspace_id or auth_ctx.get("workspace_id"),
            environment=environment or auth_ctx.get("environment"),
        )
        audit_sensitive(gw, action="admin_canvas_presence_events", auth_ctx=auth_ctx, status="ok", target=canvas_id, details={"count": len(response.get("items", []))})
        return response

    @router.post("/admin/canvas/documents/{canvas_id}/overlay-state")
    async def broker_admin_canvas_overlay_state_save(canvas_id: str, request: Request):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json()
        try:
            response = AdminService().save_canvas_overlay_state(
                gw,
                canvas_id=canvas_id,
                actor=str(payload.get("actor") or auth_ctx.get("username") or "broker-admin"),
                state_key=str(payload.get("state_key") or "default"),
                toggles=dict(payload.get("toggles") or {}),
                inspector=dict(payload.get("inspector") or {}),
                tenant_id=payload.get("tenant_id") or auth_ctx.get("tenant_id"),
                workspace_id=payload.get("workspace_id") or auth_ctx.get("workspace_id"),
                environment=payload.get("environment") or auth_ctx.get("environment"),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="canvas_not_found") from exc
        audit_sensitive(gw, action="admin_canvas_overlay_state_save", auth_ctx=auth_ctx, status="ok", target=canvas_id, details={"state_key": response.get("state", {}).get("state_key")})
        return response

    @router.get("/admin/canvas/documents/{canvas_id}/overlays")
    def broker_admin_canvas_overlays(
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
        gw, auth_ctx = require_permission(request, "admin.read")
        response = AdminService().get_canvas_operational_overlays(
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
            tenant_id=tenant_id or auth_ctx.get("tenant_id"),
            workspace_id=workspace_id or auth_ctx.get("workspace_id"),
            environment=environment or auth_ctx.get("environment"),
        )
        audit_sensitive(gw, action="admin_canvas_overlays", auth_ctx=auth_ctx, status="ok", target=canvas_id, details={"selected_node_id": selected_node_id, "state_key": state_key})
        return response

    @router.get("/admin/canvas/documents/{canvas_id}/views/operational")
    def broker_admin_canvas_operational_views(
        canvas_id: str,
        request: Request,
        tenant_id: str | None = Query(default=None),
        workspace_id: str | None = Query(default=None),
        environment: str | None = Query(default=None),
    ):
        gw, auth_ctx = require_permission(request, "admin.read")
        response = AdminService().list_canvas_operational_views(
            gw,
            canvas_id=canvas_id,
            tenant_id=tenant_id or auth_ctx.get("tenant_id"),
            workspace_id=workspace_id or auth_ctx.get("workspace_id"),
            environment=environment or auth_ctx.get("environment"),
        )
        audit_sensitive(gw, action="admin_canvas_operational_views", auth_ctx=auth_ctx, status="ok" if response.get("ok") else "missing", target=canvas_id)
        return response

    @router.get("/admin/canvas/documents/{canvas_id}/views/runtime-board")
    def broker_admin_canvas_runtime_board(
        canvas_id: str,
        request: Request,
        limit: int = Query(default=10, ge=1, le=100),
        tenant_id: str | None = Query(default=None),
        workspace_id: str | None = Query(default=None),
        environment: str | None = Query(default=None),
    ):
        gw, auth_ctx = require_permission(request, "admin.read")
        response = AdminService().get_canvas_runtime_board(
            gw,
            canvas_id=canvas_id,
            limit=limit,
            tenant_id=tenant_id or auth_ctx.get("tenant_id"),
            workspace_id=workspace_id or auth_ctx.get("workspace_id"),
            environment=environment or auth_ctx.get("environment"),
        )
        audit_sensitive(gw, action="admin_canvas_runtime_board", auth_ctx=auth_ctx, status="ok" if response.get("ok") else "missing", target=canvas_id, details={"runtime_count": len(response.get("items") or [])})
        return response

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
    def broker_admin_canvas_node_inspector(
        canvas_id: str,
        node_id: str,
        request: Request,
        state_key: str = Query(default='default'),
        limit: int = Query(default=50, ge=1, le=200),
        tenant_id: str | None = Query(default=None),
        workspace_id: str | None = Query(default=None),
        environment: str | None = Query(default=None),
    ):
        gw, auth_ctx = require_permission(request, "admin.read")
        response = AdminService().inspect_canvas_node(
            gw,
            canvas_id=canvas_id,
            node_id=node_id,
            state_key=state_key,
            limit=limit,
            tenant_id=tenant_id or auth_ctx.get("tenant_id"),
            workspace_id=workspace_id or auth_ctx.get("workspace_id"),
            environment=environment or auth_ctx.get("environment"),
        )
        audit_sensitive(gw, action="admin_canvas_node_inspector", auth_ctx=auth_ctx, status="ok" if response.get("ok") else "missing", target=node_id, details={"canvas_id": canvas_id})
        return response

    @router.get("/admin/canvas/documents/{canvas_id}/nodes/{node_id}/timeline")
    def broker_admin_canvas_node_timeline(
        canvas_id: str,
        node_id: str,
        request: Request,
        limit: int = Query(default=50, ge=1, le=200),
        tenant_id: str | None = Query(default=None),
        workspace_id: str | None = Query(default=None),
        environment: str | None = Query(default=None),
    ):
        gw, auth_ctx = require_permission(request, "admin.read")
        response = AdminService().canvas_node_timeline(
            gw,
            canvas_id=canvas_id,
            node_id=node_id,
            limit=limit,
            tenant_id=tenant_id or auth_ctx.get("tenant_id"),
            workspace_id=workspace_id or auth_ctx.get("workspace_id"),
            environment=environment or auth_ctx.get("environment"),
        )
        audit_sensitive(gw, action="admin_canvas_node_timeline", auth_ctx=auth_ctx, status="ok" if response.get("ok") else "missing", target=node_id, details={"canvas_id": canvas_id})
        return response

    @router.post("/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/{action}")
    async def broker_admin_canvas_node_action(
        canvas_id: str,
        node_id: str,
        action: str,
        request: Request,
        tenant_id: str | None = Query(default=None),
        workspace_id: str | None = Query(default=None),
        environment: str | None = Query(default=None),
    ):
        gw, auth_ctx = require_permission(request, "admin.write")
        require_csrf(request, auth_ctx)
        payload = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
        target_scope = {
            "tenant_id": tenant_id or payload.get("tenant_id") or auth_ctx.get("tenant_id"),
            "workspace_id": workspace_id or payload.get("workspace_id") or auth_ctx.get("workspace_id"),
            "environment": environment or payload.get("environment") or auth_ctx.get("environment"),
        }
        actor = str(payload.get('actor') or auth_ctx.get('user_key') or auth_ctx.get('username') or 'system')
        try:
            response = AdminService().execute_canvas_node_action(
                gw,
                canvas_id=canvas_id,
                node_id=node_id,
                action=action,
                actor=actor,
                reason=str(payload.get('reason') or ''),
                payload=dict(payload.get('payload') or {}),
                user_role=str(auth_ctx.get('role') or 'operator'),
                user_key=str(auth_ctx.get('user_key') or actor),
                session_id=str(payload.get('session_id') or f'canvas:{canvas_id}'),
                **target_scope,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            status_code = 409 if 'claimed' in str(exc).lower() else 400
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc
        audit_sensitive(gw, action='admin_canvas_node_action', auth_ctx=auth_ctx, status='ok' if response.get('ok') else 'error', target=node_id, details={'canvas_id': canvas_id, 'action': action, 'actor': actor})
        return response

    @router.get("/admin/canvas/documents/{canvas_id}/events")
    def broker_admin_canvas_events(
        canvas_id: str,
        request: Request,
        limit: int = Query(default=50, ge=1, le=200),
        tenant_id: str | None = Query(default=None),
        workspace_id: str | None = Query(default=None),
        environment: str | None = Query(default=None),
    ):
        gw, auth_ctx = require_permission(request, "admin.read")
        response = AdminService().list_canvas_events(
            gw,
            canvas_id=canvas_id,
            limit=limit,
            tenant_id=tenant_id or auth_ctx.get("tenant_id"),
            workspace_id=workspace_id or auth_ctx.get("workspace_id"),
            environment=environment or auth_ctx.get("environment"),
        )
        audit_sensitive(gw, action="admin_canvas_events", auth_ctx=auth_ctx, status="ok", target=canvas_id, details={"count": len(response.get("items", []))})
        return response

