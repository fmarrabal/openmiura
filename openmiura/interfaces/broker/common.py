from __future__ import annotations

import json
import queue
import secrets
import threading
import time
from collections import defaultdict, deque
from typing import Any

from fastapi import HTTPException, Request, Response

from openmiura.application.auth.service import AuthService
from openmiura.application.tenancy.service import TenancyService
from openmiura.observability import update_memory_metrics

_RATE_LIMIT_LOCK = threading.Lock()
_RATE_LIMIT_BUCKETS: dict[str, deque[float]] = defaultdict(deque)
_TENANCY_SERVICE = TenancyService()


def get_process_message():
    # Late import keeps compatibility with tests that monkeypatch
    # openmiura.channels.http_broker.process_message.
    from openmiura.channels import http_broker as legacy_http_broker

    return legacy_http_broker.process_message


def get_legacy_module():
    from openmiura.channels import http_broker as legacy_http_broker

    return legacy_http_broker


def rate_limit_key(request: Request, auth_ctx: dict[str, Any], bucket: str) -> str:
    actor = str(
        auth_ctx.get("username")
        or auth_ctx.get("user_key")
        or extract_bearer(request)[:12]
        or (request.client.host if request.client else "anonymous")
    )
    client_ip = request.client.host if request.client else "unknown"
    app_id = hex(id(request.app))
    return f"{app_id}:{bucket}:{actor}:{client_ip}"


def enforce_rate_limit(request: Request, auth_ctx: dict[str, Any], *, bucket: str, limit_per_minute: int) -> None:
    limit = int(limit_per_minute or 0)
    if limit <= 0:
        return
    key = rate_limit_key(request, auth_ctx, bucket)
    now = time.time()
    window = now - 60.0
    with _RATE_LIMIT_LOCK:
        dq = _RATE_LIMIT_BUCKETS[key]
        while dq and dq[0] < window:
            dq.popleft()
        if len(dq) >= limit:
            raise HTTPException(status_code=429, detail=f"Rate limit exceeded for {bucket}")
        dq.append(now)


def publish(gw, event_type: str, **payload: Any) -> None:
    bus = getattr(gw, "realtime_bus", None)
    if bus is None:
        return
    try:
        bus.publish(event_type, **payload)
    except Exception:
        pass


def audit_sensitive(
    gw,
    *,
    action: str,
    auth_ctx: dict[str, Any] | None = None,
    status: str = "ok",
    target: str = "",
    session_id: str = "",
    details: dict[str, Any] | None = None,
) -> None:
    try:
        gw.audit.log_event(
            "security",
            "broker",
            str((auth_ctx or {}).get("user_key") or (auth_ctx or {}).get("username") or "system"),
            session_id,
            {
                "event": action,
                "status": status,
                "target": target,
                "auth_mode": (auth_ctx or {}).get("mode"),
                "username": (auth_ctx or {}).get("username"),
                "role": (auth_ctx or {}).get("role"),
                "details": details or {},
            },
            tenant_id=(auth_ctx or {}).get("tenant_id"),
            workspace_id=(auth_ctx or {}).get("workspace_id"),
            environment=(auth_ctx or {}).get("environment"),
        )
    except Exception:
        pass


def get_gw(request: Request):
    gw = getattr(request.app.state, "gw", None)
    if gw is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    return gw


def resolve_tenant_context(request: Request, gw, auth_ctx: dict[str, Any]) -> dict[str, Any]:
    settings = getattr(gw, "settings", None)
    tenancy = getattr(settings, "tenancy", None)
    headers = _TENANCY_SERVICE.headers(settings)
    header_tenant = str(request.headers.get(headers["tenant"], "") or "").strip() or None
    header_workspace = str(request.headers.get(headers["workspace"], "") or "").strip() or None
    header_environment = str(request.headers.get(headers["environment"], "") or "").strip() or None

    requested_tenant = header_tenant or str(auth_ctx.get("tenant_id") or "").strip() or None
    requested_workspace = header_workspace or str(auth_ctx.get("workspace_id") or "").strip() or None
    requested_environment = header_environment or str(auth_ctx.get("environment") or "").strip() or None

    is_global_admin = (
        str(auth_ctx.get("base_role") or auth_ctx.get("role") or "").strip().lower() == "admin"
        and not auth_ctx.get("bound_tenant_id")
        and not auth_ctx.get("bound_workspace_id")
    )
    explicit_scope_headers = any((header_tenant, header_workspace, header_environment))

    if is_global_admin and not explicit_scope_headers:
        auth_ctx.update({"tenant_id": None, "workspace_id": None, "environment": None})
        auth_ctx["scope_headers"] = headers
        auth_ctx["tenancy_enabled"] = bool(getattr(tenancy, "enabled", False))
        try:
            return AuthService.finalize_scope_access(gw, auth_ctx)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    try:
        scope = _TENANCY_SERVICE.resolve(
            settings,
            tenant_id=requested_tenant,
            workspace_id=requested_workspace,
            environment=requested_environment,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    auth_ctx.update(scope.as_dict())
    auth_ctx["scope_headers"] = headers
    auth_ctx["tenancy_enabled"] = bool(getattr(tenancy, "enabled", False))
    try:
        return AuthService.finalize_scope_access(gw, auth_ctx)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def extract_bearer(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return ""


def cookie_name(gw, attr: str, default: str) -> str:
    auth_cfg = getattr(getattr(gw, "settings", None), "auth", None)
    return str(getattr(auth_cfg, attr, default) or default)


def extract_cookie_token(request: Request, gw) -> str:
    return str(request.cookies.get(cookie_name(gw, "session_cookie_name", "openmiura_session"), "") or "").strip()


def csrf_cookie(request: Request, gw) -> str:
    return str(request.cookies.get(cookie_name(gw, "csrf_cookie_name", "openmiura_csrf"), "") or "").strip()


def csrf_header(request: Request, gw) -> str:
    auth_cfg = getattr(getattr(gw, "settings", None), "auth", None)
    header_name = str(getattr(auth_cfg, "csrf_header_name", "X-CSRF-Token") or "X-CSRF-Token")
    return str(request.headers.get(header_name, "") or "").strip()


def require_csrf(request: Request, auth_ctx: dict[str, Any]) -> None:
    if auth_ctx.get("mode") != "auth-session-cookie":
        return
    gw = get_gw(request)
    auth_cfg = getattr(getattr(gw, "settings", None), "auth", None)
    if auth_cfg is None or not bool(getattr(auth_cfg, "csrf_enabled", False)):
        return
    if request.method.upper() in {"GET", "HEAD", "OPTIONS"}:
        return
    cookie_token = csrf_cookie(request, gw)
    header_token = csrf_header(request, gw)
    if not cookie_token or not header_token or not secrets.compare_digest(cookie_token, header_token):
        raise HTTPException(status_code=403, detail="CSRF validation failed")


def set_auth_cookies(response: Response, gw, session_token: str, csrf_token: str | None) -> None:
    auth_cfg = getattr(getattr(gw, "settings", None), "auth", None)
    max_age = int(getattr(auth_cfg, "session_ttl_s", 86400) or 86400)
    secure = bool(getattr(auth_cfg, "session_cookie_secure", False))
    samesite = str(getattr(auth_cfg, "session_cookie_samesite", "lax") or "lax").lower()
    response.set_cookie(
        key=cookie_name(gw, "session_cookie_name", "openmiura_session"),
        value=session_token,
        max_age=max_age,
        httponly=True,
        secure=secure,
        samesite=samesite,
        path="/",
    )
    if csrf_token:
        response.set_cookie(
            key=cookie_name(gw, "csrf_cookie_name", "openmiura_csrf"),
            value=csrf_token,
            max_age=max_age,
            httponly=False,
            secure=secure,
            samesite=samesite,
            path="/",
        )


def clear_auth_cookies(response: Response, gw) -> None:
    response.delete_cookie(key=cookie_name(gw, "session_cookie_name", "openmiura_session"), path="/")
    response.delete_cookie(key=cookie_name(gw, "csrf_cookie_name", "openmiura_csrf"), path="/")


def broker_auth_context(request: Request):
    gw = get_gw(request)
    broker_cfg = getattr(getattr(gw, "settings", None), "broker", None)
    if broker_cfg is None or not getattr(broker_cfg, "enabled", False):
        raise HTTPException(status_code=404, detail="HTTP broker not enabled")

    auth_cfg = getattr(getattr(gw, "settings", None), "auth", None)
    if getattr(gw, "audit", None) is not None and auth_cfg is not None:
        try:
            gw.audit.cleanup_auth_sessions(idle_ttl_s=int(getattr(auth_cfg, "session_idle_ttl_s", 0) or 0))
            gw.audit.cleanup_api_tokens(idle_ttl_s=int(getattr(auth_cfg, "api_token_idle_ttl_s", 0) or 0))
        except Exception:
            pass

    bearer = extract_bearer(request)
    header_token = request.headers.get("X-Broker-Token", "").strip() or request.headers.get("X-API-Token", "").strip()
    cookie_token = extract_cookie_token(request, gw)
    provided = bearer or header_token or cookie_token

    try:
        auth_ctx = AuthService.build_broker_auth_context(
            gw,
            provided_token=provided,
            cookie_token=cookie_token,
            bearer_token=bearer,
            header_token=header_token,
        )
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    return gw, resolve_tenant_context(request, gw, auth_ctx.as_dict())


def require_admin_auth(request: Request):
    gw, auth_ctx = broker_auth_context(request)
    if auth_ctx.get("mode") == "broker-token" or auth_ctx.get("role") == "admin":
        return gw, auth_ctx
    raise HTTPException(status_code=403, detail="Admin privileges required")


def require_permission(request: Request, permission: str):
    gw, auth_ctx = broker_auth_context(request)
    if AuthService.has_permission(auth_ctx, permission):
        return gw, auth_ctx
    raise HTTPException(status_code=403, detail=f"Missing permission: {permission}")


def require_broker(request: Request):
    gw, _ = broker_auth_context(request)
    return gw


def session_event(event_type: str, **payload: Any) -> str:
    return f"event: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def chunk_text(text: str, max_chars: int = 36) -> list[str]:
    words = text.split()
    if not words:
        return [text] if text else []
    chunks: list[str] = []
    buf = ""
    for word in words:
        candidate = f"{buf} {word}".strip()
        if buf and len(candidate) > max_chars:
            chunks.append(buf + " ")
            buf = word
        else:
            buf = candidate
    if buf:
        chunks.append(buf)
    return chunks


def resolve_user_key(auth_ctx: dict[str, Any], explicit_user_key: str | None, fallback: str = "broker:local") -> str:
    return str(explicit_user_key or auth_ctx.get("user_key") or fallback)


def tool_catalog(gw, agent_id: str, auth_ctx: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    tools_runtime = getattr(gw, "tools", None)
    registry = getattr(tools_runtime, "registry", None)
    if tools_runtime is None or registry is None:
        return []
    out: list[dict[str, Any]] = []
    role = (auth_ctx or {}).get("role") if auth_ctx else None
    user_key = (auth_ctx or {}).get("user_key") if auth_ctx else None
    for schema in tools_runtime.available_tool_schemas(agent_id, user_key=user_key, user_role=role):
        fn = dict(schema.get("function") or {})
        name = str(fn.get("name") or "").strip()
        if not name:
            continue
        access = tools_runtime.tool_access(agent_id, name)
        out.append(
            {
                "name": name,
                "description": str(fn.get("description") or ""),
                "inputSchema": dict(fn.get("parameters") or {}),
                "openai_schema": schema,
                "mcp_compatible": True,
                "requires_confirmation": bool(access.get("requires_confirmation", False)),
                "allowed": bool(access.get("allowed", True)),
            }
        )
    return out


def metrics_summary(gw, auth_ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    audit = getattr(gw, "audit", None)
    if audit is None:
        return {"ok": True, "sessions": 0, "active_sessions": 0, "memory": {}, "tool_calls": 0}
    update_memory_metrics(audit)
    scope = AuthService.scope_filters(auth_ctx or {}, include_environment=True) if auth_ctx else {}
    if auth_ctx and any(scope.values()):
        counts = getattr(audit, "table_counts_scoped", lambda **_: getattr(audit, "table_counts", lambda: {})())(**scope) or {}
    else:
        counts = getattr(audit, "table_counts", lambda: {})() or {}
    return {
        "ok": True,
        "service": "openMiura",
        "sessions": int(getattr(audit, "count_sessions", lambda **_: 0)(**scope)),
        "active_sessions": int(getattr(audit, "count_active_sessions", lambda **_: 0)(window_s=86400, **scope)),
        "memory": {
            "total": int(getattr(audit, "count_memory_items", lambda **_: 0)(**scope)),
            "by_kind": getattr(audit, "count_memory_items_by_kind", lambda **_: {}) (**scope) or {},
        },
        "tool_calls": int(getattr(audit, "count_tool_calls", lambda **_: 0)(**scope)),
        "events": int(getattr(audit, "count_events", lambda **_: 0)(**scope)),
        "db_counts": counts,
        "scope": scope,
    }
