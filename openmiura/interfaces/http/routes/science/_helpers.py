"""science/_helpers.py — shared helpers for the science sub-routers.

Mirrors the admin _helpers.py pattern. The two reasons we don't
just import from admin are:

  (1) The audit channel string differs (``science`` vs ``admin``)
      so downstream filters can distinguish them. An ops view that
      groups admin writes shouldn't also include scientist uploads.

  (2) The rate-limit bucket key uses a different prefix so the
      admin allowance isn't shared with the science allowance —
      a noisy bulk-upload session can't starve the admin console.
"""

from __future__ import annotations

import secrets
import threading
import time
from collections import defaultdict, deque
from typing import Any

from fastapi import HTTPException, Request

from openmiura.gateway import Gateway

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
    buckets = getattr(request.app.state, "science_rate_limit_buckets", None)
    if buckets is None:
        buckets = defaultdict(deque)
        request.app.state.science_rate_limit_buckets = buckets
    return buckets


def _rate_limit_key(request: Request) -> str:
    token_prefix = _extract_admin_token(request)[:12] or "anonymous"
    client_ip = request.client.host if request.client else "unknown"
    app_id = hex(id(request.app))
    return f"science:{app_id}:{token_prefix}:{client_ip}"


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
            raise HTTPException(status_code=429, detail="Science rate limit exceeded")
        q.append(now)


def _audit_science(gw: Gateway, action: str, payload: dict[str, Any]) -> int | None:
    """Record a science-channel audit event.

    Mirrors ``_audit_admin`` but uses ``channel='science'`` so a
    log filter can separate them. Returns the assigned event id
    when the audit store accepts the row, or ``None`` if the
    record was dropped (we never raise — audit failures must not
    take down a working endpoint).
    """
    try:
        return gw.audit.log_event(
            direction="system",
            channel="science",
            user_id=str(payload.get("user_id") or "science"),
            session_id=str(payload.get("session_id") or "science"),
            payload={"action": action, **payload},
        )
    except Exception:
        return None


def _require_science_auth(request: Request) -> Gateway:
    """Gate every /science/* endpoint behind the admin token.

    For v1 this is identical to ``_require_admin`` — the UI v2
    science profile uses the same auth dropdown as the admin
    profile, so no separate credential surface exists yet. The
    function is named differently so a future PR that adds a
    softer scientist-only token has a clear extension point
    without breaking the existing call sites.
    """
    gw = _get_gw(request)
    admin_cfg = getattr(gw.settings, "admin", None)
    if not admin_cfg or not getattr(admin_cfg, "enabled", False):
        raise HTTPException(status_code=503, detail="Admin API not enabled")
    science_cfg = getattr(gw.settings, "science", None)
    rate_per_min = int(getattr(science_cfg, "rate_limit_per_minute", 30) or 30)
    _rate_limit(request, rate_per_min)
    configured_token = (getattr(admin_cfg, "token", "") or "").strip()
    if not configured_token:
        raise HTTPException(status_code=503, detail="Admin API token not configured")
    provided_token = _extract_admin_token(request)
    if not provided_token or not secrets.compare_digest(provided_token, configured_token):
        raise HTTPException(status_code=401, detail="Invalid admin token")
    return gw


__all__ = [
    "_get_gw",
    "_extract_admin_token",
    "_rate_limit",
    "_audit_science",
    "_require_science_auth",
]
