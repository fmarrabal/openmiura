from __future__ import annotations

import secrets
from typing import Any

from openmiura.core.auth.models import AuthContext


ROLE_PERMISSIONS = {
    "viewer": {
        "workspace.read",
        "tools.read",
        "tool_calls.read.own",
        "workflows.read",
        "jobs.read",
    },
    "user": {
        "workspace.read",
        "workspace.write",
        "confirmations.read",
        "confirmations.write",
        "memory.read",
        "terminal.stream",
        "tools.read",
        "tool_calls.read.own",
        "workflows.read",
        "workflows.write",
        "jobs.read",
        "approvals.read",
    },
    "auditor": {
        "workspace.read",
        "memory.read",
        "admin.read",
        "metrics.read",
        "sessions.read",
        "events.read",
        "identities.read",
        "tool_calls.read",
        "users.read",
        "workflows.read",
        "approvals.read",
    },
    "operator": {
        "workspace.read",
        "workspace.write",
        "confirmations.read",
        "confirmations.write",
        "memory.read",
        "terminal.stream",
        "tools.read",
        "tool_calls.read.own",
        "admin.read",
        "metrics.read",
        "sessions.read",
        "events.read",
        "identities.read",
        "tool_calls.read",
        "users.read",
        "auth.manage",
        "workflows.read",
        "workflows.write",
        "approvals.read",
        "approvals.write",
        "jobs.read",
        "jobs.write",
        "jobs.run",
    },
    "workspace_admin": {
        "workspace.read",
        "workspace.write",
        "confirmations.read",
        "confirmations.write",
        "memory.read",
        "terminal.stream",
        "tools.read",
        "tool_calls.read.own",
        "admin.read",
        "admin.write",
        "metrics.read",
        "sessions.read",
        "events.read",
        "identities.read",
        "tool_calls.read",
        "users.read",
        "auth.manage",
        "workflows.read",
        "workflows.write",
        "approvals.read",
        "approvals.write",
        "jobs.read",
        "jobs.write",
        "jobs.run",
    },
    "tenant_admin": {
        "workspace.read",
        "workspace.write",
        "confirmations.read",
        "confirmations.write",
        "memory.read",
        "terminal.stream",
        "tools.read",
        "tool_calls.read.own",
        "admin.read",
        "admin.write",
        "metrics.read",
        "sessions.read",
        "events.read",
        "identities.read",
        "tool_calls.read",
        "users.read",
        "auth.manage",
        "workflows.read",
        "workflows.write",
        "approvals.read",
        "approvals.write",
        "jobs.read",
        "jobs.write",
        "jobs.run",
    },
    "admin": {"*"},
}

ROLE_INHERITS = {
    "viewer": [],
    "user": ["viewer"],
    "auditor": ["viewer"],
    "operator": ["user"],
    "workspace_admin": ["operator"],
    "tenant_admin": ["workspace_admin"],
    "admin": [],
}

ROLE_SCOPE_ACCESS = {
    "viewer": "scoped",
    "user": "scoped",
    "auditor": "scoped",
    "operator": "scoped",
    "workspace_admin": "scoped",
    "tenant_admin": "tenant",
    "admin": "global",
}

ROLE_SCOPE_LEVEL = {
    "viewer": "workspace",
    "user": "workspace",
    "auditor": "workspace",
    "operator": "workspace",
    "workspace_admin": "workspace",
    "tenant_admin": "tenant",
    "admin": "global",
}

VALID_SCOPE_ACCESS = {"scoped", "tenant", "global"}
VALID_SCOPE_LEVEL = {"environment", "workspace", "tenant", "global"}


class AuthService:
    """Centralized auth/policy helpers for broker-facing interfaces."""

    @staticmethod
    def permissions_for_role(role: str | None) -> list[str]:
        role_key = str(role or "user").strip().lower() or "user"
        return sorted(ROLE_PERMISSIONS.get(role_key, ROLE_PERMISSIONS["user"]))

    @staticmethod
    def has_permission(auth_ctx: dict[str, Any] | AuthContext, permission: str) -> bool:
        ctx = auth_ctx.as_dict() if isinstance(auth_ctx, AuthContext) else auth_ctx
        perms = set(ctx.get("permissions") or [])
        return "*" in perms or permission in perms

    @staticmethod
    def is_admin(auth_ctx: dict[str, Any] | AuthContext) -> bool:
        ctx = auth_ctx.as_dict() if isinstance(auth_ctx, AuthContext) else auth_ctx
        return ctx.get("mode") == "broker-token" or str(ctx.get("role") or "").strip().lower() == "admin"

    @staticmethod
    def scope_filters(auth_ctx: dict[str, Any] | AuthContext, *, include_environment: bool = False) -> dict[str, Any]:
        ctx = auth_ctx.as_dict() if isinstance(auth_ctx, AuthContext) else auth_ctx
        out = {
            "tenant_id": ctx.get("tenant_id"),
            "workspace_id": ctx.get("workspace_id"),
        }
        if include_environment:
            out["environment"] = ctx.get("environment")
        return out

    @classmethod
    def validate_target_scope(
        cls,
        auth_ctx: dict[str, Any] | AuthContext,
        *,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> None:
        ctx = auth_ctx.as_dict() if isinstance(auth_ctx, AuthContext) else auth_ctx
        scope_access = str(ctx.get("scope_access") or "scoped")
        scope_level = str(ctx.get("scope_level") or "workspace")
        current_tenant = ctx.get("tenant_id")
        current_workspace = ctx.get("workspace_id")
        current_environment = ctx.get("environment")
        bound_tenant = ctx.get("bound_tenant_id", current_tenant)
        bound_workspace = ctx.get("bound_workspace_id", current_workspace)
        bound_environment = ctx.get("bound_environment", current_environment)

        if scope_access == "global":
            return

        if tenant_id is not None:
            target_tenant = str(tenant_id).strip()
            if bound_tenant and target_tenant and target_tenant != str(bound_tenant):
                raise PermissionError("Cannot target a different tenant_id")
            if scope_access != "tenant" and current_tenant and target_tenant and target_tenant != str(current_tenant):
                raise PermissionError("Cannot target a different tenant_id")

        if workspace_id is not None:
            target_workspace = str(workspace_id).strip()
            if scope_access == "tenant":
                return
            if bound_workspace and target_workspace and target_workspace != str(bound_workspace):
                raise PermissionError("Cannot target a different workspace_id")
            if current_workspace and target_workspace and target_workspace != str(current_workspace):
                raise PermissionError("Cannot target a different workspace_id")

        if environment is not None:
            target_environment = str(environment).strip()
            if scope_access == "tenant":
                return
            if scope_level == "environment":
                if bound_environment and target_environment and target_environment != str(bound_environment):
                    raise PermissionError("Cannot target a different environment")
                if current_environment and target_environment and target_environment != str(current_environment):
                    raise PermissionError("Cannot target a different environment")

    @classmethod
    def build_broker_auth_context(
        cls,
        gw,
        *,
        provided_token: str = "",
        cookie_token: str = "",
        bearer_token: str = "",
        header_token: str = "",
    ) -> AuthContext:
        broker_cfg = getattr(getattr(gw, "settings", None), "broker", None)
        auth_cfg = getattr(getattr(gw, "settings", None), "auth", None)

        configured_token = str(getattr(broker_cfg, "token", "") or "").strip()
        provided = str(provided_token or "").strip()

        if configured_token and provided and secrets.compare_digest(provided, configured_token):
            return AuthContext(
                mode="broker-token",
                role="admin",
                base_role="admin",
                permissions=cls.permissions_for_role("admin"),
                tenant_id=None,
                workspace_id=None,
                environment=None,
                bound_tenant_id=None,
                bound_workspace_id=None,
                bound_environment=None,
                scope_access="global",
                scope_level="global",
            )

        idle_ttl_s = int(getattr(auth_cfg, "session_idle_ttl_s", 0) or 0)
        auth_session = getattr(gw.audit, "get_auth_session", lambda *_args, **_kwargs: None)(provided, idle_ttl_s=idle_ttl_s) if provided else None
        if auth_session is not None:
            getattr(gw.audit, "touch_auth_session", lambda *_: 0)(provided)
            role = auth_session.get("role", "user")
            mode = "auth-session-cookie" if cookie_token and provided == cookie_token and not bearer_token and not header_token else "auth-session"
            return AuthContext(
                mode=mode,
                user_key=auth_session.get("user_key"),
                token=auth_session,
                role=role,
                base_role=str(role or "user"),
                username=auth_session.get("username"),
                permissions=cls.permissions_for_role(role),
                tenant_id=auth_session.get("tenant_id"),
                workspace_id=auth_session.get("workspace_id"),
                environment=auth_session.get("environment"),
                bound_tenant_id=auth_session.get("tenant_id"),
                bound_workspace_id=auth_session.get("workspace_id"),
                bound_environment=auth_session.get("environment"),
            )

        if configured_token:
            if provided:
                raise ValueError("Invalid broker or session token")
            raise PermissionError("Broker authentication required")

        token_info = getattr(gw.audit, "get_api_token", lambda *_args, **_kwargs: None)(provided, idle_ttl_s=int(getattr(auth_cfg, "api_token_idle_ttl_s", 0) or 0)) if provided else None
        if token_info is not None:
            getattr(gw.audit, "touch_api_token", lambda *_: 0)(provided)
            auth_user = None
            try:
                auth_user = gw.audit.get_auth_user(user_key=token_info.get("user_key"))
            except Exception:
                auth_user = None
            role = (auth_user or {}).get("role") or "user"
            return AuthContext(
                mode="user-token",
                user_key=token_info.get("user_key"),
                token=token_info,
                role=role,
                base_role=str(role or "user"),
                username=(auth_user or {}).get("username"),
                permissions=cls.permissions_for_role(role),
                tenant_id=token_info.get("tenant_id"),
                workspace_id=token_info.get("workspace_id"),
                environment=token_info.get("environment"),
                bound_tenant_id=token_info.get("tenant_id"),
                bound_workspace_id=token_info.get("workspace_id"),
                bound_environment=token_info.get("environment"),
            )

        return AuthContext(base_role="user")

    @classmethod
    def finalize_scope_access(cls, gw, auth_ctx: dict[str, Any]) -> dict[str, Any]:
        mode = str(auth_ctx.get("mode") or "anonymous")
        base_role = str(auth_ctx.get("base_role") or auth_ctx.get("role") or "user").strip().lower() or "user"
        auth_ctx["base_role"] = base_role

        if mode == "broker-token":
            auth_ctx["role"] = "admin"
            auth_ctx["permissions"] = cls.permissions_for_role("admin")
            auth_ctx["scope_access"] = "global"
            auth_ctx["scope_level"] = "global"
            return auth_ctx

        effective_role = cls._resolve_bound_role(gw, auth_ctx, base_role)
        scope_access, scope_level = cls._resolve_scope_profile(gw, auth_ctx, effective_role)
        auth_ctx["role"] = effective_role
        auth_ctx["scope_access"] = scope_access
        auth_ctx["scope_level"] = scope_level
        cls._enforce_requested_scope(auth_ctx)
        auth_ctx["permissions"] = cls._resolve_permissions(gw, auth_ctx, effective_role)
        return auth_ctx

    @classmethod
    def evaluate_permission(
        cls,
        gw,
        auth_ctx: dict[str, Any] | AuthContext,
        permission: str,
        *,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        ctx = auth_ctx.as_dict() if isinstance(auth_ctx, AuthContext) else dict(auth_ctx)
        if tenant_id is not None:
            ctx["tenant_id"] = tenant_id
        if workspace_id is not None:
            ctx["workspace_id"] = workspace_id
        if environment is not None:
            ctx["environment"] = environment
        ctx = cls.finalize_scope_access(gw, ctx)
        allowed = cls.has_permission(ctx, permission)
        return {
            "allowed": allowed,
            "permission": permission,
            "role": ctx.get("role"),
            "base_role": ctx.get("base_role"),
            "scope_access": ctx.get("scope_access"),
            "scope_level": ctx.get("scope_level"),
            "scope": {
                "tenant_id": ctx.get("tenant_id"),
                "workspace_id": ctx.get("workspace_id"),
                "environment": ctx.get("environment"),
            },
            "permissions": list(ctx.get("permissions") or []),
        }

    @classmethod
    def role_catalog(cls, gw, auth_ctx: dict[str, Any] | AuthContext) -> list[dict[str, Any]]:
        ctx = auth_ctx.as_dict() if isinstance(auth_ctx, AuthContext) else dict(auth_ctx)
        role_names = set(ROLE_PERMISSIONS) | set(ROLE_INHERITS)
        for rbac in cls._scope_rbac_layers(gw, ctx):
            role_names.update(rbac.get("permission_grants", {}).keys())
            role_names.update(rbac.get("permission_denies", {}).keys())
            role_names.update(rbac.get("role_inherits", {}).keys())
            role_names.update(rbac.get("role_scope_access", {}).keys())
            role_names.update(rbac.get("username_roles", {}).values())
            role_names.update(rbac.get("user_key_roles", {}).values())
        items: list[dict[str, Any]] = []
        for role in sorted(str(x).strip().lower() for x in role_names if str(x).strip()):
            base_permissions = sorted(ROLE_PERMISSIONS.get(role, set()))
            effective_permissions = cls._resolve_permissions(gw, ctx, role)
            scope_access, scope_level = cls._resolve_scope_profile(gw, ctx, role)
            items.append(
                {
                    "role": role,
                    "permissions": base_permissions,
                    "effective_permissions": effective_permissions,
                    "inherits": cls._role_lineage(gw, ctx, role)[1:],
                    "scope_access": scope_access,
                    "scope_level": scope_level,
                }
            )
        return items

    @classmethod
    def _resolve_bound_role(cls, gw, auth_ctx: dict[str, Any], base_role: str) -> str:
        role = str(base_role or "user").strip().lower() or "user"
        username = str(auth_ctx.get("username") or "").strip()
        user_key = str(auth_ctx.get("user_key") or "").strip()
        for rbac in cls._scope_rbac_layers(gw, auth_ctx):
            if user_key and user_key in rbac.get("user_key_roles", {}):
                role = str(rbac["user_key_roles"][user_key]).strip().lower() or role
            if username and username in rbac.get("username_roles", {}):
                role = str(rbac["username_roles"][username]).strip().lower() or role
        return role

    @classmethod
    def _resolve_permissions(cls, gw, auth_ctx: dict[str, Any], role: str) -> list[str]:
        lineage = cls._role_lineage(gw, auth_ctx, role)
        perms: set[str] = set()
        for inherited_role in reversed(lineage):
            perms.update(ROLE_PERMISSIONS.get(inherited_role, set()))
        if "*" in perms:
            return ["*"]
        for inherited_role in lineage:
            for rbac in cls._scope_rbac_layers(gw, auth_ctx):
                perms.update(str(x).strip() for x in (rbac.get("permission_grants", {}).get(inherited_role, []) or []) if str(x).strip())
                perms.difference_update(str(x).strip() for x in (rbac.get("permission_denies", {}).get(inherited_role, []) or []) if str(x).strip())
        return sorted(perms)

    @classmethod
    def _resolve_scope_profile(cls, gw, auth_ctx: dict[str, Any], role: str) -> tuple[str, str]:
        scope_access = None
        scope_level = None
        for inherited_role in cls._role_lineage(gw, auth_ctx, role):
            inherited_access = ROLE_SCOPE_ACCESS.get(inherited_role)
            inherited_level = ROLE_SCOPE_LEVEL.get(inherited_role)
            if scope_access is None and inherited_access in VALID_SCOPE_ACCESS:
                scope_access = inherited_access
            if scope_level is None and inherited_level in VALID_SCOPE_LEVEL:
                scope_level = inherited_level
        if scope_access is None:
            scope_access = "scoped"
        if scope_level is None:
            scope_level = "workspace"
        for rbac in cls._scope_rbac_layers(gw, auth_ctx):
            configured = str((rbac.get("role_scope_access", {}) or {}).get(role, "")).strip().lower()
            if configured in VALID_SCOPE_ACCESS:
                scope_access = configured
                scope_level = {"global": "global", "tenant": "tenant", "scoped": "workspace"}[configured]
        if auth_ctx.get("bound_environment") and scope_access == "scoped":
            scope_level = "environment"
        return scope_access, scope_level

    @classmethod
    def _enforce_requested_scope(cls, auth_ctx: dict[str, Any]) -> None:
        scope_access = str(auth_ctx.get("scope_access") or "scoped")
        scope_level = str(auth_ctx.get("scope_level") or "workspace")

        bound_tenant = auth_ctx.get("bound_tenant_id", auth_ctx.get("tenant_id"))
        bound_workspace = auth_ctx.get("bound_workspace_id", auth_ctx.get("workspace_id"))
        bound_environment = auth_ctx.get("bound_environment", auth_ctx.get("environment"))
        requested_tenant = auth_ctx.get("tenant_id")
        requested_workspace = auth_ctx.get("workspace_id")
        requested_environment = auth_ctx.get("environment")

        if scope_access == "global":
            return

        if bound_tenant and requested_tenant and str(bound_tenant) != str(requested_tenant):
            raise PermissionError("Tenant scope escalation denied")

        if scope_access == "tenant":
            return

        if bound_workspace and requested_workspace and str(bound_workspace) != str(requested_workspace):
            raise PermissionError("Workspace scope escalation denied")

        if scope_level == "environment" and bound_environment and requested_environment and str(bound_environment) != str(requested_environment):
            raise PermissionError("Environment scope escalation denied")

    @classmethod
    def _role_lineage(cls, gw, auth_ctx: dict[str, Any], role: str) -> list[str]:
        role_key = str(role or "user").strip().lower() or "user"
        order: list[str] = []
        seen: set[str] = set()

        inherited_map: dict[str, list[str]] = {k: list(v) for k, v in ROLE_INHERITS.items()}
        for rbac in cls._scope_rbac_layers(gw, auth_ctx):
            for key, values in (rbac.get("role_inherits", {}) or {}).items():
                inherited_map.setdefault(str(key).strip().lower(), [])
                inherited_map[str(key).strip().lower()].extend(str(v).strip().lower() for v in (values or []) if str(v).strip())

        def walk(current: str) -> None:
            current = str(current or "").strip().lower()
            if not current or current in seen:
                return
            seen.add(current)
            order.append(current)
            for parent in inherited_map.get(current, []):
                walk(parent)

        walk(role_key)
        if role_key not in order:
            order.insert(0, role_key)
        return order

    @classmethod
    def _scope_rbac_layers(cls, gw, auth_ctx: dict[str, Any]) -> list[dict[str, Any]]:
        settings = getattr(gw, "settings", None)
        tenancy = getattr(settings, "tenancy", None)
        tenant_id = auth_ctx.get("tenant_id")
        workspace_id = auth_ctx.get("workspace_id")
        environment = auth_ctx.get("environment")
        layers: list[dict[str, Any]] = []
        tenants = getattr(tenancy, "tenants", {}) or {}
        tenant_cfg = tenants.get(tenant_id)
        if tenant_cfg is None:
            return layers
        layers.append(cls._rbac_to_dict(getattr(tenant_cfg, "rbac", None)))
        workspace_cfg = (getattr(tenant_cfg, "workspaces", {}) or {}).get(workspace_id)
        if workspace_cfg is None:
            return layers
        layers.append(cls._rbac_to_dict(getattr(workspace_cfg, "rbac", None)))
        env_cfg = (getattr(workspace_cfg, "environment_settings", {}) or {}).get(environment)
        if env_cfg is not None:
            layers.append(cls._rbac_to_dict(getattr(env_cfg, "rbac", None)))
        return layers

    @staticmethod
    def _rbac_to_dict(rbac: Any) -> dict[str, Any]:
        if rbac is None:
            return {
                "username_roles": {},
                "user_key_roles": {},
                "permission_grants": {},
                "permission_denies": {},
                "role_inherits": {},
                "role_scope_access": {},
            }
        return {
            "username_roles": dict(getattr(rbac, "username_roles", {}) or {}),
            "user_key_roles": dict(getattr(rbac, "user_key_roles", {}) or {}),
            "permission_grants": {str(k).strip().lower(): [str(x).strip() for x in list(v or []) if str(x).strip()] for k, v in dict(getattr(rbac, "permission_grants", {}) or {}).items()},
            "permission_denies": {str(k).strip().lower(): [str(x).strip() for x in list(v or []) if str(x).strip()] for k, v in dict(getattr(rbac, "permission_denies", {}) or {}).items()},
            "role_inherits": {str(k).strip().lower(): [str(x).strip().lower() for x in list(v or []) if str(x).strip()] for k, v in dict(getattr(rbac, "role_inherits", {}) or {}).items()},
            "role_scope_access": {str(k).strip().lower(): str(v).strip().lower() for k, v in dict(getattr(rbac, "role_scope_access", {}) or {}).items() if str(k).strip() and str(v).strip()},
        }


__all__ = ["AuthService", "ROLE_PERMISSIONS", "ROLE_INHERITS", "ROLE_SCOPE_ACCESS", "ROLE_SCOPE_LEVEL"]
