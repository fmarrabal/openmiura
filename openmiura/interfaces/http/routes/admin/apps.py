"""admin/apps.py — sub-router for the apps bounded admin domain."""

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


@router.get("/admin/app/installations")
def admin_app_installations(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    status: str | None = Query(default=None),
    tenant_id: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    environment: str | None = Query(default=None),
):
    gw = _get_gw(request)
    _require_admin(request)
    payload = _ADMIN_SERVICE.list_app_installations(
        gw,
        limit=limit,
        status=status,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, "app_installations_list", {"count": len(payload.get("items", [])), "status": status})
    return payload


@router.post("/admin/app/installations")
def admin_app_installation_register(payload: AppInstallationRequest, request: Request):
    gw = _get_gw(request)
    _require_admin(request)
    response = _ADMIN_SERVICE.register_app_installation(
        gw,
        actor=payload.actor,
        user_key=payload.user_key,
        platform=payload.platform,
        device_label=payload.device_label,
        push_capable=payload.push_capable,
        notification_permission=payload.notification_permission,
        deep_link_base=payload.deep_link_base,
        metadata=payload.metadata,
        tenant_id=payload.tenant_id,
        workspace_id=payload.workspace_id,
        environment=payload.environment,
    )
    _audit_admin(gw, "app_installation_register", {"installation_id": response.get("installation", {}).get("installation_id"), "actor": payload.actor})
    return response


@router.get("/admin/app/notifications")
def admin_app_notifications(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    installation_id: str | None = Query(default=None),
    tenant_id: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    environment: str | None = Query(default=None),
):
    gw = _get_gw(request)
    _require_admin(request)
    payload = _ADMIN_SERVICE.list_app_notifications(
        gw,
        limit=limit,
        installation_id=installation_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, "app_notifications_list", {"count": len(payload.get("items", [])), "installation_id": installation_id})
    return payload


@router.post("/admin/app/notifications")
def admin_app_notification_create(payload: AppNotificationRequest, request: Request):
    gw = _get_gw(request)
    _require_admin(request)
    response = _ADMIN_SERVICE.create_app_notification(
        gw,
        actor=payload.actor,
        title=payload.title,
        body=payload.body,
        category=payload.category,
        installation_id=payload.installation_id,
        target_path=payload.target_path,
        require_interaction=payload.require_interaction,
        metadata=payload.metadata,
        tenant_id=payload.tenant_id,
        workspace_id=payload.workspace_id,
        environment=payload.environment,
    )
    _audit_admin(gw, "app_notification_create", {"notification_id": response.get("notification", {}).get("notification_id"), "actor": payload.actor})
    return response


@router.get("/admin/app/deep-links")
def admin_app_deep_links(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    status: str | None = Query(default=None),
    tenant_id: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    environment: str | None = Query(default=None),
):
    gw = _get_gw(request)
    _require_admin(request)
    payload = _ADMIN_SERVICE.list_app_deep_links(
        gw,
        limit=limit,
        status=status,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    _audit_admin(gw, "app_deep_links_list", {"count": len(payload.get("items", [])), "status": status})
    return payload


@router.post("/admin/app/deep-links")
def admin_app_deep_link_create(payload: AppDeepLinkRequest, request: Request):
    gw = _get_gw(request)
    _require_admin(request)
    response = _ADMIN_SERVICE.create_app_deep_link(
        gw,
        actor=payload.actor,
        view=payload.view,
        target_type=payload.target_type,
        target_id=payload.target_id,
        params=payload.params,
        expires_in_s=payload.expires_in_s,
        tenant_id=payload.tenant_id,
        workspace_id=payload.workspace_id,
        environment=payload.environment,
    )
    _audit_admin(gw, "app_deep_link_create", {"link_token": response.get("deep_link", {}).get("link_token"), "actor": payload.actor})
    return response


@router.get("/app/deep-links/{link_token}")
def app_deep_link_redirect(link_token: str, request: Request):
    gw = _get_gw(request)
    response = _ADMIN_SERVICE.resolve_app_deep_link(gw, link_token=link_token)
    if not response.get("ok"):
        raise HTTPException(status_code=404 if response.get("reason") == "not_found" else 410, detail=response.get("reason") or "deep_link_unavailable")
    return RedirectResponse(url=response["ui_path"], status_code=307)


