from __future__ import annotations

import secrets
import time

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from openmiura.application.auth.oidc_service import OIDCService
from openmiura.application.auth.service import AuthService, ROLE_PERMISSIONS
from openmiura.application.tenancy.service import TenancyService
from openmiura.interfaces.broker.common import (
    audit_sensitive,
    broker_auth_context,
    clear_auth_cookies,
    enforce_rate_limit,
    get_gw,
    require_csrf,
    require_permission,
    set_auth_cookies,
)
from openmiura.interfaces.broker.schemas import (
    BrokerAuthAuthorizeRequest,
    BrokerAuthSessionRevokeRequest,
    BrokerAuthSessionRotateRequest,
    BrokerAuthUserCreateRequest,
    BrokerLoginRequest,
    BrokerTokenCreateRequest,
    BrokerTokenRevokeRequest,
    BrokerTokenRotateRequest,
)


def build_auth_router() -> APIRouter:
    router = APIRouter(tags=["broker"])
    oidc_service = OIDCService()
    tenancy_service = TenancyService()

    def _resolve_user_scope(gw, user: dict[str, object] | None) -> tuple[str | None, str | None, str | None]:
        user = user or {}
        explicit_tenant = str(user.get("tenant_id") or "").strip() or None
        explicit_workspace = str(user.get("workspace_id") or "").strip() or None
        explicit_role = str(user.get("role") or "user").strip().lower() or "user"
        if explicit_role == "admin" and explicit_tenant is None and explicit_workspace is None:
            return None, None, None
        if explicit_tenant and explicit_workspace is None:
            return explicit_tenant, None, None
        try:
            scope = tenancy_service.resolve(
                gw.settings,
                tenant_id=explicit_tenant,
                workspace_id=explicit_workspace,
                environment=None,
            )
            return scope.tenant_id, scope.workspace_id, scope.environment
        except Exception:
            return (explicit_tenant, explicit_workspace, None)

    def _set_oidc_flow_cookie(response: JSONResponse, gw, value: str, *, max_age: int) -> None:
        auth_cfg = getattr(getattr(gw, "settings", None), "auth", None)
        secure = bool(getattr(auth_cfg, "session_cookie_secure", False))
        samesite = str(getattr(auth_cfg, "session_cookie_samesite", "lax") or "lax").lower()
        response.set_cookie(
            key=oidc_service.FLOW_COOKIE_NAME,
            value=value,
            max_age=max_age,
            httponly=True,
            secure=secure,
            samesite=samesite,
            path="/",
        )

    def _clear_oidc_flow_cookie(response: JSONResponse) -> None:
        response.delete_cookie(key=oidc_service.FLOW_COOKIE_NAME, path="/")

    @router.get("/health")
    def broker_health(request: Request):
        gw, auth_ctx = broker_auth_context(request)
        broker_cfg = gw.settings.broker
        return {
            "ok": True,
            "service": "openMiura HTTP broker",
            "transport": "http-broker",
            "mcp_compatible": True,
            "base_path": getattr(broker_cfg, "base_path", "/broker"),
            "auth_mode": auth_ctx.get("mode"),
        }

    @router.get("/auth/me")
    def broker_auth_me(request: Request):
        gw, auth_ctx = broker_auth_context(request)
        audit_sensitive(gw, action="auth_me", auth_ctx=auth_ctx, status="ok")
        token = auth_ctx.get("token")
        safe_token = None
        if isinstance(token, dict):
            safe_token = {k: v for k, v in token.items() if k != "token"}
        auth_cfg = getattr(getattr(gw, "settings", None), "auth", None)
        session_rotation_after_s = int(getattr(auth_cfg, "session_rotation_interval_s", 0) or 0)
        api_rotation_after_s = int(getattr(auth_cfg, "api_token_rotation_interval_s", 0) or 0)
        session_age_s = None
        rotation_due = False
        if isinstance(safe_token, dict) and safe_token.get("created_at") is not None:
            session_age_s = max(0, int(time.time() - float(safe_token["created_at"])))
            threshold = session_rotation_after_s if auth_ctx.get("mode") in {"auth-session", "auth-session-cookie"} else api_rotation_after_s
            rotation_due = bool(threshold and session_age_s >= threshold)
        return {
            "ok": True,
            "auth_mode": auth_ctx.get("mode"),
            "user_key": auth_ctx.get("user_key"),
            "username": auth_ctx.get("username"),
            "role": auth_ctx.get("role"),
            "base_role": auth_ctx.get("base_role"),
            "permissions": list(auth_ctx.get("permissions") or []),
            "scope_access": auth_ctx.get("scope_access"),
            "scope_level": auth_ctx.get("scope_level"),
            "tenant_id": auth_ctx.get("tenant_id"),
            "workspace_id": auth_ctx.get("workspace_id"),
            "environment": auth_ctx.get("environment"),
            "scope_headers": auth_ctx.get("scope_headers") or {},
            "token": safe_token,
            "csrf_enabled": bool(getattr(auth_cfg, "csrf_enabled", False)),
            "csrf_header_name": str(getattr(auth_cfg, "csrf_header_name", "X-CSRF-Token") or "X-CSRF-Token"),
            "session_age_s": session_age_s,
            "session_rotation_due": rotation_due,
            "api_token_rotation_interval_s": int(getattr(auth_cfg, "api_token_rotation_interval_s", 0) or 0),
            "oidc": oidc_service.public_config(gw, request) if bool(getattr(getattr(auth_cfg, "oidc", None), "enabled", False)) else {"enabled": False},
        }

    @router.post("/auth/login")
    def broker_auth_login(payload: BrokerLoginRequest, request: Request):
        gw = get_gw(request)
        broker_cfg = getattr(getattr(gw, "settings", None), "broker", None)
        enforce_rate_limit(request, {"username": payload.username}, bucket="auth_login", limit_per_minute=int(getattr(broker_cfg, "auth_rate_limit_per_minute", 20) or 20))
        auth_cfg = getattr(getattr(gw, "settings", None), "auth", None)
        if auth_cfg is None or not getattr(auth_cfg, "enabled", False):
            raise HTTPException(status_code=404, detail="Formal auth is not enabled")
        user = gw.audit.verify_auth_user(username=payload.username, password=payload.password)
        if user is None:
            audit_sensitive(gw, action="auth_login", auth_ctx={"username": payload.username, "mode": "anonymous"}, status="denied", details={"reason": "invalid_credentials"})
            raise HTTPException(status_code=401, detail="Invalid username or password")
        max_sessions = int(getattr(auth_cfg, "max_sessions_per_user", 0) or 0)
        if max_sessions > 0:
            sessions = gw.audit.list_auth_sessions(user_id=int(user["id"]), include_revoked=False)
            for stale in sessions[max(0, max_sessions - 1):]:
                gw.audit.revoke_auth_session(session_id=int(stale["id"]))
        tenant_id, workspace_id, environment = _resolve_user_scope(gw, user)
        session = gw.audit.create_auth_session(
            user_id=int(user["id"]),
            ttl_s=int(getattr(auth_cfg, "session_ttl_s", 86400) or 86400),
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        csrf_token = secrets.token_urlsafe(24) if bool(getattr(auth_cfg, "csrf_enabled", False)) else None
        body = {
            "ok": True,
            "auth_mode": "auth-session",
            "token": session["token"],
            "session": {k: v for k, v in session.items() if k != "token"},
            "user": user,
            "permissions": AuthService.permissions_for_role(user.get("role")),
            "csrf_token": csrf_token,
        }
        response = JSONResponse(content=body)
        if payload.use_cookie_session and bool(getattr(auth_cfg, "session_cookie_enabled", False)):
            set_auth_cookies(response, gw, session["token"], csrf_token)
        audit_sensitive(gw, action="auth_login", auth_ctx={"mode": "auth-session", "username": user.get("username"), "user_key": user.get("user_key"), "role": user.get("role")}, status="ok", target=user.get("username", ""), details={"session_id": session["id"]})
        return response

    @router.get("/auth/oidc/config")
    def broker_auth_oidc_config(request: Request):
        gw = get_gw(request)
        try:
            payload = oidc_service.public_config(gw, request)
        except PermissionError:
            payload = {"enabled": False}
        return {"ok": True, **payload}

    @router.get("/auth/oidc/login")
    def broker_auth_oidc_login(request: Request):
        gw = get_gw(request)
        try:
            payload = oidc_service.build_login(gw, request)
        except PermissionError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        response = JSONResponse(content={
            "ok": True,
            "authorize_url": payload["authorize_url"],
            "state": payload["state"],
            "redirect_uri": payload["redirect_uri"],
            "scope": payload["scope"],
        })
        max_age = int(getattr(getattr(gw.settings.auth, "oidc", None), "state_ttl_s", 600) or 600)
        _set_oidc_flow_cookie(response, gw, payload["flow_cookie"], max_age=max_age)
        audit_sensitive(gw, action="auth_oidc_login_start", auth_ctx={"mode": "anonymous"}, status="ok", details={"scope": payload["scope"]})
        return response

    @router.get("/auth/oidc/callback")
    def broker_auth_oidc_callback(request: Request, code: str = Query(...), state: str = Query(...)):
        gw = get_gw(request)
        flow_cookie = str(request.cookies.get(oidc_service.FLOW_COOKIE_NAME, "") or "").strip()
        if not flow_cookie:
            raise HTTPException(status_code=400, detail="OIDC flow cookie is missing")
        try:
            body = oidc_service.complete_login(gw, request, code=code, state=state, flow_cookie=flow_cookie)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        body["permissions"] = AuthService.permissions_for_role((body.get("user") or {}).get("role"))
        csrf_token = secrets.token_urlsafe(24) if bool(getattr(gw.settings.auth, "csrf_enabled", False)) else None
        body["csrf_token"] = csrf_token
        response = JSONResponse(content=body)
        if bool(getattr(gw.settings.auth, "session_cookie_enabled", False)):
            set_auth_cookies(response, gw, str(body["token"]), csrf_token)
        _clear_oidc_flow_cookie(response)
        audit_sensitive(gw, action="auth_oidc_callback", auth_ctx={"mode": "auth-session", "username": (body.get("user") or {}).get("username"), "user_key": (body.get("user") or {}).get("user_key"), "role": (body.get("user") or {}).get("role")}, status="ok", target=str((body.get("user") or {}).get("username") or ""), details={"scope": body.get("scope")})
        return response

    @router.post("/auth/oidc/logout")
    def broker_auth_oidc_logout(request: Request):
        gw, auth_ctx = broker_auth_context(request)
        require_csrf(request, auth_ctx)
        response = JSONResponse(content={**oidc_service.logout_payload(gw, request)})
        if auth_ctx.get("mode") in {"auth-session", "auth-session-cookie"}:
            raw = request.headers.get("Authorization", "")
            if raw.lower().startswith("bearer "):
                raw = raw.split(" ", 1)[1].strip()
            else:
                raw = request.headers.get("X-Broker-Token", "").strip() or request.headers.get("X-API-Token", "").strip() or request.cookies.get(getattr(getattr(gw, "settings", None).auth, "session_cookie_name", "openmiura_session"), "")
            revoked = gw.audit.revoke_auth_session(raw_token=raw)
            response = JSONResponse(content={**oidc_service.logout_payload(gw, request), "revoked": revoked})
            clear_auth_cookies(response, gw)
        _clear_oidc_flow_cookie(response)
        audit_sensitive(gw, action="auth_oidc_logout", auth_ctx=auth_ctx, status="ok")
        return response

    @router.post("/auth/logout")
    def broker_auth_logout(request: Request):
        gw, auth_ctx = broker_auth_context(request)
        require_csrf(request, auth_ctx)
        if auth_ctx.get("mode") not in {"auth-session", "auth-session-cookie"}:
            raise HTTPException(status_code=400, detail="No auth session to revoke")
        raw = request.headers.get("Authorization", "")
        if raw.lower().startswith("bearer "):
            raw = raw.split(" ", 1)[1].strip()
        else:
            raw = request.headers.get("X-Broker-Token", "").strip() or request.headers.get("X-API-Token", "").strip() or request.cookies.get(getattr(getattr(gw, "settings", None).auth, "session_cookie_name", "openmiura_session"), "")
        revoked = gw.audit.revoke_auth_session(raw_token=raw)
        response = JSONResponse(content={"ok": True, "revoked": revoked})
        clear_auth_cookies(response, gw)
        audit_sensitive(gw, action="auth_logout", auth_ctx=auth_ctx, status="ok", details={"revoked": revoked})
        return response

    @router.get("/auth/sessions")
    def broker_auth_sessions(request: Request):
        gw, auth_ctx = broker_auth_context(request)
        scope = AuthService.scope_filters(auth_ctx, include_environment=True)
        if auth_ctx.get("scope_access") == "global":
            items = gw.audit.list_auth_sessions(include_revoked=False, **scope)
        else:
            token = auth_ctx.get("token") or {}
            items = gw.audit.list_auth_sessions(user_id=int(token.get("user_id") or 0), include_revoked=False, **scope)
        return {"ok": True, "items": items}

    @router.post("/auth/sessions/revoke")
    def broker_revoke_auth_session(payload: BrokerAuthSessionRevokeRequest, request: Request):
        gw, auth_ctx = broker_auth_context(request)
        require_csrf(request, auth_ctx)
        token = auth_ctx.get("token") or {}
        if payload.revoke_all_for_user:
            target_user_id = int(payload.user_id or token.get("user_id") or 0)
            if auth_ctx.get("role") != "admin" and auth_ctx.get("mode") != "broker-token":
                target_user_id = int(token.get("user_id") or 0)
            revoked = gw.audit.revoke_auth_sessions_for_user(user_id=target_user_id)
            audit_sensitive(gw, action="auth_sessions_revoke_all", auth_ctx=auth_ctx, status="ok", target=str(target_user_id), details={"revoked": revoked})
            return {"ok": True, "revoked": revoked}
        target_session_id = int(payload.session_id or token.get("id") or 0)
        if not target_session_id:
            raise HTTPException(status_code=422, detail="session_id is required")
        if auth_ctx.get("role") != "admin" and auth_ctx.get("mode") != "broker-token":
            allowed = {int(item["id"]) for item in gw.audit.list_auth_sessions(user_id=int(token.get("user_id") or 0), include_revoked=False, **AuthService.scope_filters(auth_ctx, include_environment=True))}
            if target_session_id not in allowed:
                raise HTTPException(status_code=403, detail="Cannot revoke another user's session")
        revoked = gw.audit.revoke_auth_session(session_id=target_session_id)
        audit_sensitive(gw, action="auth_session_revoke", auth_ctx=auth_ctx, status="ok", target=str(target_session_id), details={"revoked": revoked})
        return {"ok": True, "revoked": revoked}

    @router.post("/auth/sessions/rotate")
    def broker_rotate_auth_session(payload: BrokerAuthSessionRotateRequest, request: Request):
        gw, auth_ctx = broker_auth_context(request)
        require_csrf(request, auth_ctx)
        token = auth_ctx.get("token") or {}
        target_session_id = int(payload.session_id or token.get("id") or 0)
        if auth_ctx.get("role") != "admin" and auth_ctx.get("mode") != "broker-token":
            allowed = {int(item["id"]) for item in gw.audit.list_auth_sessions(user_id=int(token.get("user_id") or 0), include_revoked=False, **AuthService.scope_filters(auth_ctx, include_environment=True))}
            if target_session_id not in allowed:
                raise HTTPException(status_code=403, detail="Cannot rotate another user's session")
        rotated = gw.audit.rotate_auth_session(session_id=target_session_id, ttl_s=int(getattr(gw.settings.auth, "session_ttl_s", 86400) or 86400))
        if rotated is None:
            raise HTTPException(status_code=404, detail="Unable to rotate auth session")
        csrf_token = secrets.token_urlsafe(24) if bool(getattr(gw.settings.auth, "csrf_enabled", False)) else None
        body = {"ok": True, "session": {k: v for k, v in rotated.items() if k != "token"}, "token": rotated["token"], "csrf_token": csrf_token}
        response = JSONResponse(content=body)
        if bool(getattr(gw.settings.auth, "session_cookie_enabled", False)):
            set_auth_cookies(response, gw, rotated["token"], csrf_token)
        audit_sensitive(gw, action="auth_session_rotate", auth_ctx=auth_ctx, status="ok", target=str(target_session_id), details={"new_session_id": rotated["id"]})
        return response

    @router.get("/auth/users")
    def broker_auth_users(request: Request):
        gw, auth_ctx = require_permission(request, "users.read")
        items = gw.audit.list_auth_users(**AuthService.scope_filters(auth_ctx))
        for item in items:
            ctx = dict(auth_ctx)
            ctx["username"] = item.get("username")
            ctx["user_key"] = item.get("user_key")
            item["effective_role"] = AuthService.finalize_scope_access(gw, {**ctx}).get("role")
            item["permissions"] = AuthService._resolve_permissions(gw, {**ctx, "role": item["effective_role"], "tenant_id": auth_ctx.get("tenant_id"), "workspace_id": auth_ctx.get("workspace_id"), "environment": auth_ctx.get("environment")}, item["effective_role"])
        audit_sensitive(gw, action="auth_users_list", auth_ctx=auth_ctx, status="ok", details={"count": len(items)})
        return {"ok": True, "items": items}

    @router.get("/auth/roles")
    def broker_auth_roles(request: Request):
        gw, auth_ctx = require_permission(request, "users.read")
        items = AuthService.role_catalog(gw, auth_ctx)
        audit_sensitive(gw, action="auth_roles_list", auth_ctx=auth_ctx, status="ok", details={"count": len(items)})
        return {"ok": True, "items": items}

    @router.get("/auth/rbac/matrix")
    def broker_auth_rbac_matrix(request: Request):
        gw, auth_ctx = require_permission(request, "users.read")
        items = AuthService.role_catalog(gw, auth_ctx)
        current = AuthService.evaluate_permission(gw, auth_ctx, "workspace.read")
        audit_sensitive(gw, action="auth_rbac_matrix_read", auth_ctx=auth_ctx, status="ok", details={"count": len(items)})
        return {"ok": True, "scope": current["scope"], "current_role": current["role"], "current_scope_access": current["scope_access"], "current_scope_level": current["scope_level"], "items": items}

    @router.post("/auth/authorize")
    def broker_auth_authorize(payload: BrokerAuthAuthorizeRequest, request: Request):
        gw, auth_ctx = broker_auth_context(request)
        try:
            result = AuthService.evaluate_permission(
                gw,
                auth_ctx,
                payload.permission,
                tenant_id=payload.tenant_id,
                workspace_id=payload.workspace_id,
                environment=payload.environment,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        audit_sensitive(gw, action="auth_authorize", auth_ctx=auth_ctx, status="ok" if result["allowed"] else "denied", details={"permission": payload.permission, "scope": result["scope"]})
        return {"ok": True, **result}

    @router.post("/auth/users")
    def broker_auth_create_user(payload: BrokerAuthUserCreateRequest, request: Request):
        gw, auth_ctx = require_permission(request, "auth.manage")
        require_csrf(request, auth_ctx)
        try:
            AuthService.validate_target_scope(auth_ctx, tenant_id=payload.tenant_id, workspace_id=payload.workspace_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        user = gw.audit.ensure_auth_user(
            username=payload.username,
            password=payload.password,
            user_key=payload.user_key,
            role=payload.role,
            tenant_id=payload.tenant_id or auth_ctx.get("tenant_id"),
            workspace_id=payload.workspace_id or auth_ctx.get("workspace_id"),
        )
        audit_sensitive(gw, action="auth_user_create", auth_ctx=auth_ctx, status="ok", target=payload.username, details={"role": payload.role})
        return {"ok": True, "user": user}

    @router.post("/auth/tokens")
    def broker_create_token(payload: BrokerTokenCreateRequest, request: Request):
        gw, auth_ctx = require_permission(request, "auth.manage")
        require_csrf(request, auth_ctx)
        try:
            AuthService.validate_target_scope(auth_ctx, tenant_id=payload.tenant_id, workspace_id=payload.workspace_id, environment=payload.environment)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        ttl_s = payload.ttl_s if payload.ttl_s is not None else int(getattr(gw.settings.auth, "api_token_default_ttl_s", 0) or 0) or None
        token = gw.audit.create_api_token(
            user_key=payload.user_key,
            label=payload.label,
            scopes=payload.scopes,
            ttl_s=ttl_s,
            tenant_id=payload.tenant_id or auth_ctx.get("tenant_id"),
            workspace_id=payload.workspace_id or auth_ctx.get("workspace_id"),
            environment=payload.environment or auth_ctx.get("environment"),
        )
        audit_sensitive(gw, action="api_token_create", auth_ctx=auth_ctx, status="ok", target=payload.user_key, details={"token_id": token["id"], "label": token["label"]})
        return {"ok": True, "token": token}

    @router.get("/auth/tokens")
    def broker_list_tokens(request: Request, user_key: str | None = Query(default=None)):
        gw, auth_ctx = broker_auth_context(request)
        if auth_ctx.get("scope_access") == "global":
            effective_user = user_key
        else:
            effective_user = auth_ctx.get("user_key")
            if user_key and user_key != effective_user:
                raise HTTPException(status_code=403, detail="Cannot inspect tokens for another user")
        items = gw.audit.list_api_tokens(user_key=effective_user, **AuthService.scope_filters(auth_ctx, include_environment=True))
        rotation_after_s = int(getattr(gw.settings.auth, "api_token_rotation_interval_s", 0) or 0)
        now_ts = time.time()
        for item in items:
            created_at = float(item.get("created_at") or now_ts)
            age_s = max(0, int(now_ts - created_at))
            item["age_s"] = age_s
            item["rotation_due"] = bool(rotation_after_s and age_s >= rotation_after_s)
        audit_sensitive(gw, action="api_tokens_list", auth_ctx=auth_ctx, status="ok", target=str(effective_user or ""), details={"count": len(items)})
        return {"ok": True, "items": items}

    @router.post("/auth/tokens/revoke")
    def broker_revoke_token(payload: BrokerTokenRevokeRequest, request: Request):
        gw, auth_ctx = require_permission(request, "auth.manage")
        require_csrf(request, auth_ctx)
        revoked = gw.audit.revoke_api_token(token_id=payload.token_id)
        audit_sensitive(gw, action="api_token_revoke", auth_ctx=auth_ctx, status="ok", target=str(payload.token_id), details={"revoked": revoked})
        return {"ok": True, "revoked": revoked}

    @router.post("/auth/tokens/rotate")
    def broker_rotate_token(payload: BrokerTokenRotateRequest, request: Request):
        gw, auth_ctx = broker_auth_context(request)
        require_csrf(request, auth_ctx)
        token_items = {int(item["id"]): item for item in gw.audit.list_api_tokens(include_revoked=False, **AuthService.scope_filters(auth_ctx, include_environment=True))}
        current = token_items.get(int(payload.token_id))
        if current is None:
            raise HTTPException(status_code=404, detail="Unknown token_id")
        owner = current.get("user_key")
        if auth_ctx.get("mode") != "broker-token" and auth_ctx.get("role") != "admin" and auth_ctx.get("user_key") != owner:
            raise HTTPException(status_code=403, detail="Cannot rotate another user's token")
        rotated = gw.audit.rotate_api_token(token_id=int(payload.token_id), ttl_s=payload.ttl_s, user_key=owner)
        if rotated is None:
            raise HTTPException(status_code=404, detail="Unable to rotate token")
        audit_sensitive(gw, action="api_token_rotate", auth_ctx=auth_ctx, status="ok", target=str(payload.token_id), details={"new_token_id": rotated["id"]})
        return {"ok": True, "token": rotated}

    return router
