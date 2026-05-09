"""admin/_helpers.py — shared helpers and singletons for the admin sub-routers."""

from __future__ import annotations

import secrets
import threading
import time
from collections import defaultdict, deque
from typing import Any

from fastapi import HTTPException, Request

from openmiura.application.admin import AdminService

_ADMIN_SERVICE = AdminService()
_RATE_LIMIT_LOCK = threading.Lock()


def _get_gw(request: Request) -> Gateway:
    gw: Gateway | None = getattr(request.app.state, "gw", None)
    if gw is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    return gw


def _extract_admin_token(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return request.headers.get("X-Admin-Token", "").strip()


def _rate_limit_buckets(request: Request) -> dict[str, deque[float]]:
    buckets = getattr(request.app.state, "admin_rate_limit_buckets", None)
    if buckets is None:
        buckets = defaultdict(deque)
        request.app.state.admin_rate_limit_buckets = buckets
    return buckets


def _rate_limit_key(request: Request) -> str:
    token_prefix = _extract_admin_token(request)[:12] or "anonymous"
    client_ip = request.client.host if request.client else "unknown"
    app_id = hex(id(request.app))
    return f"{app_id}:{token_prefix}:{client_ip}"


def _rate_limit(request: Request, limit_per_minute: int) -> None:
    limit = int(limit_per_minute or 0)
    if limit <= 0:
        return
    now = time.time()
    window = now - 60.0
    key = _rate_limit_key(request)
    with _RATE_LIMIT_LOCK:
        q = _rate_limit_buckets(request)[key]
        while q and q[0] < window:
            q.popleft()
        if len(q) >= limit:
            raise HTTPException(status_code=429, detail="Admin rate limit exceeded")
        q.append(now)


def _audit_admin(gw: Gateway, action: str, payload: dict) -> int | None:
    try:
        return gw.audit.log_event(
            direction="system",
            channel="admin",
            user_id="admin",
            session_id="admin",
            payload={"action": action, **payload},
        )
    except Exception:
        return None


def _require_admin(request: Request) -> Gateway:
    gw = _get_gw(request)
    admin_cfg = getattr(gw.settings, "admin", None)
    if not admin_cfg or not getattr(admin_cfg, "enabled", False):
        raise HTTPException(status_code=503, detail="Admin API not enabled")
    _rate_limit(request, int(getattr(admin_cfg, "rate_limit_per_minute", 60) or 60))
    configured_token = (getattr(admin_cfg, "token", "") or "").strip()
    if not configured_token:
        raise HTTPException(status_code=503, detail="Admin API token not configured")
    provided_token = _extract_admin_token(request)
    if not provided_token or not secrets.compare_digest(provided_token, configured_token):
        raise HTTPException(status_code=401, detail="Invalid admin token")
    return gw


