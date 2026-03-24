from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any
from urllib.parse import urlencode, urljoin

import httpx

from openmiura.application.tenancy.service import TenancyService


class OIDCService:
    FLOW_COOKIE_NAME = "openmiura_oidc_flow"
    _cache: dict[str, tuple[float, dict[str, Any]]] = {}

    def __init__(self) -> None:
        self.tenancy = TenancyService()

    def public_config(self, gw, request) -> dict[str, Any]:
        oidc_cfg = self._settings(gw)
        redirect_uri = self.redirect_uri(gw, request)
        return {
            "enabled": bool(getattr(oidc_cfg, "enabled", False)),
            "issuer_url": str(getattr(oidc_cfg, "issuer_url", "") or ""),
            "client_id": str(getattr(oidc_cfg, "client_id", "") or ""),
            "redirect_uri": redirect_uri,
            "redirect_path": str(getattr(oidc_cfg, "redirect_path", "/broker/auth/oidc/callback") or "/broker/auth/oidc/callback"),
            "scopes": list(getattr(oidc_cfg, "scopes", []) or []),
            "pkce": bool(getattr(oidc_cfg, "use_pkce", True)),
        }

    def redirect_uri(self, gw, request) -> str:
        oidc_cfg = self._settings(gw)
        base = str(request.base_url).rstrip("/") + "/"
        redirect_path = str(getattr(oidc_cfg, "redirect_path", "/broker/auth/oidc/callback") or "/broker/auth/oidc/callback")
        return urljoin(base, redirect_path.lstrip("/"))

    def build_login(self, gw, request) -> dict[str, Any]:
        oidc_cfg = self._settings(gw)
        metadata = self.provider_metadata(oidc_cfg)
        redirect_uri = self.redirect_uri(gw, request)
        requested = self.tenancy.resolve(
            gw.settings,
            tenant_id=request.query_params.get("tenant_id") or None,
            workspace_id=request.query_params.get("workspace_id") or None,
            environment=request.query_params.get("environment") or None,
        )
        verifier = secrets.token_urlsafe(48) if bool(getattr(oidc_cfg, "use_pkce", True)) else ""
        nonce = secrets.token_urlsafe(24)
        issued_at = int(time.time())
        state_payload = {
            "nonce": nonce,
            "ts": issued_at,
            "tenant_id": requested.tenant_id,
            "workspace_id": requested.workspace_id,
            "environment": requested.environment,
        }
        flow_payload = dict(state_payload)
        flow_payload["redirect_uri"] = redirect_uri
        if verifier:
            flow_payload["code_verifier"] = verifier

        state = self._sign(gw, state_payload)
        flow_cookie = self._sign(gw, flow_payload)
        params = {
            "client_id": str(getattr(oidc_cfg, "client_id", "") or ""),
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": " ".join(list(getattr(oidc_cfg, "scopes", []) or ["openid", "profile", "email"])),
            "state": state,
            "prompt": str(getattr(oidc_cfg, "prompt", "login") or "login"),
        }
        if verifier:
            params["code_challenge"] = self._code_challenge(verifier)
            params["code_challenge_method"] = "S256"
        authorize_url = str(metadata["authorization_endpoint"]).rstrip("?") + "?" + urlencode(params)
        return {
            "authorize_url": authorize_url,
            "state": state,
            "flow_cookie": flow_cookie,
            "redirect_uri": redirect_uri,
            "scope": requested.as_dict(),
        }

    def complete_login(self, gw, request, *, code: str, state: str, flow_cookie: str) -> dict[str, Any]:
        oidc_cfg = self._settings(gw)
        state_payload = self._unsign(gw, state)
        flow_payload = self._unsign(gw, flow_cookie)
        if str(state_payload.get("nonce") or "") != str(flow_payload.get("nonce") or ""):
            raise ValueError("OIDC state mismatch")
        ttl_s = int(getattr(oidc_cfg, "state_ttl_s", 600) or 600)
        issued_at = int(state_payload.get("ts") or 0)
        if not issued_at or issued_at + ttl_s < int(time.time()):
            raise ValueError("OIDC login flow expired")

        metadata = self.provider_metadata(oidc_cfg)
        tokens = self.exchange_code_for_tokens(
            metadata,
            oidc_cfg,
            code=code,
            redirect_uri=str(flow_payload.get("redirect_uri") or self.redirect_uri(gw, request)),
            code_verifier=str(flow_payload.get("code_verifier") or ""),
        )
        claims = dict(tokens.get("claims") or {})
        access_token = str(tokens.get("access_token") or "")
        if access_token and metadata.get("userinfo_endpoint"):
            claims.update(self.fetch_userinfo(metadata, access_token))
        identity = self.identity_from_claims(gw, claims, fallback_scope=flow_payload)

        existing = gw.audit.get_auth_user(user_key=identity["user_key"])
        if existing is None and not bool(getattr(oidc_cfg, "auto_provision_users", True)):
            raise PermissionError("OIDC auto-provisioning is disabled")

        user = gw.audit.ensure_auth_user(
            username=identity["username"],
            password=secrets.token_urlsafe(24),
            user_key=identity["user_key"],
            role=identity["role"],
            tenant_id=identity["tenant_id"],
            workspace_id=identity["workspace_id"],
        )
        ttl = int(getattr(gw.settings.auth, "session_ttl_s", 86400) or 86400)
        session = gw.audit.create_auth_session(
            user_id=int(user["id"]),
            ttl_s=ttl,
            tenant_id=identity["tenant_id"],
            workspace_id=identity["workspace_id"],
            environment=identity["environment"],
        )
        return {
            "ok": True,
            "auth_mode": "auth-session",
            "token": session["token"],
            "session": {k: v for k, v in session.items() if k != "token"},
            "user": user,
            "permissions": [],
            "claims": self._safe_claims(claims),
            "scope": {
                "tenant_id": identity["tenant_id"],
                "workspace_id": identity["workspace_id"],
                "environment": identity["environment"],
            },
        }

    def logout_payload(self, gw, request) -> dict[str, Any]:
        oidc_cfg = self._settings(gw)
        end_session_url = str(getattr(oidc_cfg, "end_session_url", "") or "")
        redirect_base = str(request.base_url).rstrip("/") + "/"
        post_logout_path = str(getattr(oidc_cfg, "post_logout_redirect_path", "/ui") or "/ui")
        post_logout_redirect_uri = urljoin(redirect_base, post_logout_path.lstrip("/"))
        if end_session_url:
            return {
                "ok": True,
                "end_session_url": end_session_url + "?" + urlencode({"post_logout_redirect_uri": post_logout_redirect_uri}),
                "post_logout_redirect_uri": post_logout_redirect_uri,
            }
        return {"ok": True, "post_logout_redirect_uri": post_logout_redirect_uri}

    def identity_from_claims(self, gw, claims: dict[str, Any], *, fallback_scope: dict[str, Any] | None = None) -> dict[str, str | None]:
        oidc_cfg = self._settings(gw)
        email = str(claims.get(getattr(oidc_cfg, "email_claim", "email")) or "").strip()
        if email:
            domain = email.rsplit("@", 1)[-1].lower() if "@" in email else ""
            allowed_domains = [str(x).strip().lower() for x in (getattr(oidc_cfg, "allowed_email_domains", []) or []) if str(x).strip()]
            if allowed_domains and domain not in allowed_domains:
                raise PermissionError("OIDC email domain is not allowed")
        username = str(claims.get(getattr(oidc_cfg, "username_claim", "preferred_username")) or email or claims.get(getattr(oidc_cfg, "subject_claim", "sub")) or "").strip()
        subject = str(claims.get(getattr(oidc_cfg, "subject_claim", "sub")) or email or username or "").strip()
        if not username or not subject:
            raise ValueError("OIDC claims are missing a stable identity")
        groups_raw = claims.get(getattr(oidc_cfg, "group_claim", "groups")) or []
        if isinstance(groups_raw, str):
            groups = [groups_raw]
        elif isinstance(groups_raw, list):
            groups = [str(x) for x in groups_raw if str(x).strip()]
        else:
            groups = []
        role = str(getattr(oidc_cfg, "default_role", "user") or "user")
        role_map = dict(getattr(oidc_cfg, "group_role_mapping", {}) or {})
        for group in groups:
            mapped = role_map.get(str(group))
            if mapped:
                role = str(mapped)
                break
        fallback_scope = fallback_scope or {}
        requested_tenant = str(claims.get(getattr(oidc_cfg, "tenant_claim", "tenant_id")) or fallback_scope.get("tenant_id") or "").strip() or None
        requested_workspace = str(claims.get(getattr(oidc_cfg, "workspace_claim", "workspace_id")) or fallback_scope.get("workspace_id") or "").strip() or None
        requested_environment = str(claims.get(getattr(oidc_cfg, "environment_claim", "environment")) or fallback_scope.get("environment") or "").strip() or None
        scope = self.tenancy.resolve(
            gw.settings,
            tenant_id=requested_tenant,
            workspace_id=requested_workspace,
            environment=requested_environment,
        )
        return {
            "username": username,
            "user_key": f"oidc:{subject}",
            "role": role,
            "tenant_id": scope.tenant_id,
            "workspace_id": scope.workspace_id,
            "environment": scope.environment,
        }

    def exchange_code_for_tokens(
        self,
        metadata: dict[str, Any],
        oidc_cfg,
        *,
        code: str,
        redirect_uri: str,
        code_verifier: str = "",
    ) -> dict[str, Any]:
        token_url = str(metadata.get("token_endpoint") or "")
        if not token_url:
            raise ValueError("OIDC token endpoint is not configured")
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": str(getattr(oidc_cfg, "client_id", "") or ""),
        }
        if getattr(oidc_cfg, "client_secret", ""):
            data["client_secret"] = str(getattr(oidc_cfg, "client_secret", "") or "")
        if code_verifier:
            data["code_verifier"] = code_verifier
        response = httpx.post(token_url, data=data, timeout=15.0)
        response.raise_for_status()
        return dict(response.json() or {})

    def fetch_userinfo(self, metadata: dict[str, Any], access_token: str) -> dict[str, Any]:
        userinfo_url = str(metadata.get("userinfo_endpoint") or "")
        if not userinfo_url or not access_token:
            return {}
        response = httpx.get(userinfo_url, headers={"Authorization": f"Bearer {access_token}"}, timeout=15.0)
        response.raise_for_status()
        return dict(response.json() or {})

    def provider_metadata(self, oidc_cfg) -> dict[str, Any]:
        explicit = {
            "issuer": str(getattr(oidc_cfg, "issuer_url", "") or ""),
            "authorization_endpoint": str(getattr(oidc_cfg, "authorize_url", "") or ""),
            "token_endpoint": str(getattr(oidc_cfg, "token_url", "") or ""),
            "userinfo_endpoint": str(getattr(oidc_cfg, "userinfo_url", "") or ""),
            "jwks_uri": str(getattr(oidc_cfg, "jwks_url", "") or ""),
            "end_session_endpoint": str(getattr(oidc_cfg, "end_session_url", "") or ""),
        }
        if explicit["authorization_endpoint"] and explicit["token_endpoint"]:
            return explicit
        discovery_url = str(getattr(oidc_cfg, "discovery_url", "") or "")
        issuer_url = str(getattr(oidc_cfg, "issuer_url", "") or "")
        if not discovery_url and issuer_url:
            discovery_url = issuer_url.rstrip("/") + "/.well-known/openid-configuration"
        if not discovery_url:
            return explicit
        cached = self._cache.get(discovery_url)
        if cached and cached[0] > time.time():
            metadata = dict(cached[1])
        else:
            response = httpx.get(discovery_url, timeout=10.0)
            response.raise_for_status()
            metadata = dict(response.json() or {})
            self._cache[discovery_url] = (time.time() + 300.0, metadata)
        for key, value in explicit.items():
            if value:
                metadata[key] = value
        return metadata

    def _settings(self, gw):
        auth_cfg = getattr(getattr(gw, "settings", None), "auth", None)
        oidc_cfg = getattr(auth_cfg, "oidc", None)
        if oidc_cfg is None or not bool(getattr(oidc_cfg, "enabled", False)):
            raise PermissionError("OIDC is not enabled")
        return oidc_cfg

    def _sign(self, gw, payload: dict[str, Any]) -> str:
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        body_b64 = self._b64url(body)
        signature = hmac.new(self._secret(gw), body_b64.encode("ascii"), hashlib.sha256).digest()
        return body_b64 + "." + self._b64url(signature)

    def _unsign(self, gw, token: str) -> dict[str, Any]:
        body_b64, _, sig_b64 = str(token or "").partition(".")
        if not body_b64 or not sig_b64:
            raise ValueError("Invalid OIDC state")
        expected = self._b64url(hmac.new(self._secret(gw), body_b64.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(expected, sig_b64):
            raise ValueError("Invalid OIDC signature")
        raw = self._b64url_decode(body_b64)
        return dict(json.loads(raw.decode("utf-8")) or {})

    def _secret(self, gw) -> bytes:
        oidc_cfg = getattr(getattr(gw, "settings", None).auth, "oidc", None)
        seed = str(getattr(oidc_cfg, "client_secret", "") or "")
        if not seed:
            seed = str(getattr(getattr(gw, "settings", None).broker, "token", "") or "")
        if not seed:
            seed = "openmiura-oidc"
        return hashlib.sha256(seed.encode("utf-8")).digest()

    def _code_challenge(self, verifier: str) -> str:
        return self._b64url(hashlib.sha256(verifier.encode("utf-8")).digest())

    def _safe_claims(self, claims: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in claims.items():
            lowered = str(key).lower()
            if lowered in {"at_hash", "c_hash"}:
                continue
            if any(mark in lowered for mark in ("token", "secret", "nonce")):
                out[str(key)] = "***"
            else:
                out[str(key)] = value
        return out

    def _b64url(self, raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    def _b64url_decode(self, value: str) -> bytes:
        padding = "=" * ((4 - len(value) % 4) % 4)
        return base64.urlsafe_b64decode(value + padding)
