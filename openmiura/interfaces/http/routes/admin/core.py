"""admin/core.py — sub-router for the core bounded admin domain."""

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


@router.get("/admin/status")
def admin_status(request: Request):
    gw = _require_admin(request)
    payload = _ADMIN_SERVICE.status_snapshot(gw)
    _audit_admin(gw, "status_read", {})
    return payload


@router.get("/admin/memory/search")
def admin_memory_search_get(
    request: Request,
    q: Optional[str] = Query(default=None),
    user_key: Optional[str] = Query(default=None),
    top_k: int = Query(default=5, ge=1, le=100),
):
    gw = _require_admin(request)
    payload = _ADMIN_SERVICE.search_memory_semantic_or_table(gw, q=q, user_key=user_key, top_k=top_k)
    _audit_admin(gw, f"memory_{payload['mode']}_search", {
        "q": q,
        "user_key": user_key,
        "top_k": top_k,
        "returned": len(payload.get("items", [])),
    })
    return payload


@router.post("/admin/memory/search")
def admin_memory_search_post(payload: AdminMemorySearchBody, request: Request):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.search_memory(
        gw,
        user_key=payload.user_key,
        kind=payload.kind,
        text_contains=payload.text_contains,
        limit=payload.limit,
    )
    _audit_admin(gw, "memory_search", {
        "filters": response["filters"],
        "returned": response["returned"],
    })
    return response


@router.post("/admin/memory/delete")
def admin_memory_delete(payload: AdminMemoryDeleteRequest, request: Request):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.delete_memory(
        gw,
        user_key=payload.user_key,
        kind=payload.kind,
        dry_run=payload.dry_run,
    )
    if payload.dry_run:
        _audit_admin(gw, "memory_delete_dry_run", {
            "user_key": payload.user_key,
            "kind": payload.kind,
            "would_delete": response["would_delete"],
        })
    else:
        _audit_admin(gw, "memory_delete", {
            "user_key": payload.user_key,
            "kind": payload.kind,
            "deleted": response["deleted"],
        })
    return response


@router.delete("/admin/memory/{item_id}")
def admin_memory_delete_by_id(item_id: int, request: Request):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.delete_memory_by_id(gw, item_id=item_id)
    _audit_admin(gw, "memory_delete_by_id", {"item_id": item_id, "deleted": response["deleted"]})
    return response


@router.get("/admin/sessions")
def admin_sessions(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    channel: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.list_sessions(gw, limit=limit, channel=channel)
    _audit_admin(gw, "sessions_list", {"limit": limit, "channel": channel, "returned": len(response["items"])})
    return response


@router.get("/admin/events")
def admin_events(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    channel: Optional[str] = Query(default=None),
):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.list_events(gw, limit=limit, channel=channel)
    _audit_admin(gw, "events_list", {"limit": limit, "channel": channel, "returned": len(response["items"])})
    return response


@router.post("/admin/reload")
def admin_reload(request: Request):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.reload(gw)
    _audit_admin(gw, "reload", {k: v for k, v in response.items() if k != "ok"})
    return response


@router.get("/admin/identities")
def admin_identities(request: Request, global_user_key: Optional[str] = Query(default=None)):
    gw = _require_admin(request)
    response = _ADMIN_SERVICE.list_identities(gw, global_user_key=global_user_key)
    _audit_admin(gw, "identities_list", {"global_user_key": global_user_key, "returned": len(response["items"])})
    return response


@router.post("/admin/identities/link")
def admin_identities_link(payload: IdentityLinkRequest, request: Request):
    gw = _require_admin(request)
    channel_user_key = payload.channel_user_key or payload.channel_key
    if not channel_user_key:
        raise HTTPException(status_code=422, detail="channel_user_key is required")
    response = _ADMIN_SERVICE.link_identity(
        gw,
        channel_user_key=channel_user_key,
        global_user_key=payload.global_user_key,
        linked_by=payload.linked_by,
    )
    _audit_admin(gw, "identity_link", response)
    return response


