from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from openmiura.core.tenancy.models import TenantContext


class TenancyService:
    _EXPORTED_SECTIONS = ("runtime", "llm", "memory", "tools", "broker", "auth", "admin")

    def default_context(self, settings: Any) -> TenantContext:
        tenancy = getattr(settings, "tenancy", None)
        tenant_id = str(getattr(tenancy, "default_tenant_id", "default") or "default")
        workspace_id = str(getattr(tenancy, "default_workspace_id", "main") or "main")
        environment = str(getattr(tenancy, "default_environment", "prod") or "prod")
        tenants = getattr(tenancy, "tenants", {}) or {}
        tenant_cfg = tenants.get(tenant_id)
        if tenant_cfg is not None:
            workspaces = getattr(tenant_cfg, "workspaces", {}) or {}
            workspace_cfg = workspaces.get(workspace_id)
            if workspace_cfg is not None:
                environment = str(getattr(workspace_cfg, "default_environment", environment) or environment)
        return TenantContext(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def resolve(self, settings: Any, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> TenantContext:
        base = self.default_context(settings)
        tenancy = getattr(settings, "tenancy", None)
        if tenancy is None or not bool(getattr(tenancy, "enabled", False)):
            return base

        allow_override = bool(getattr(tenancy, "allow_request_scope_override", True))
        resolved_tenant = base.tenant_id
        resolved_workspace = base.workspace_id
        resolved_environment = base.environment
        if allow_override:
            if tenant_id:
                resolved_tenant = str(tenant_id).strip() or base.tenant_id
            if workspace_id:
                resolved_workspace = str(workspace_id).strip() or base.workspace_id
            if environment:
                resolved_environment = str(environment).strip() or base.environment

        tenants = getattr(tenancy, "tenants", {}) or {}
        tenant_cfg = tenants.get(resolved_tenant)
        if tenant_cfg is None:
            if tenants:
                raise ValueError(f"Unknown tenant_id: {resolved_tenant}")
            return TenantContext(tenant_id=resolved_tenant, workspace_id=resolved_workspace, environment=resolved_environment)

        workspaces = getattr(tenant_cfg, "workspaces", {}) or {}
        workspace_cfg = workspaces.get(resolved_workspace)
        if workspace_cfg is None:
            if workspaces:
                raise ValueError(f"Unknown workspace_id '{resolved_workspace}' for tenant '{resolved_tenant}'")
            return TenantContext(tenant_id=resolved_tenant, workspace_id=resolved_workspace, environment=resolved_environment)

        default_workspace_env = str(getattr(workspace_cfg, "default_environment", base.environment) or base.environment)
        if environment is None or not str(environment).strip():
            resolved_environment = default_workspace_env
        allowed_envs = [str(x).strip() for x in (getattr(workspace_cfg, "environments", []) or []) if str(x).strip()]
        if allowed_envs and resolved_environment not in allowed_envs:
            raise ValueError(
                f"Unknown environment '{resolved_environment}' for tenant '{resolved_tenant}' workspace '{resolved_workspace}'"
            )
        if not resolved_environment:
            resolved_environment = default_workspace_env
        return TenantContext(tenant_id=resolved_tenant, workspace_id=resolved_workspace, environment=resolved_environment)

    def headers(self, settings: Any) -> dict[str, str]:
        tenancy = getattr(settings, "tenancy", None)
        return {
            "tenant": str(getattr(tenancy, "tenant_header_name", "X-Tenant-Id") or "X-Tenant-Id"),
            "workspace": str(getattr(tenancy, "workspace_header_name", "X-Workspace-Id") or "X-Workspace-Id"),
            "environment": str(getattr(tenancy, "environment_header_name", "X-Environment") or "X-Environment"),
        }

    def catalog(
        self,
        settings: Any,
        *,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        tenancy = getattr(settings, "tenancy", None)
        default_ctx = self.default_context(settings)
        tenants = getattr(tenancy, "tenants", {}) or {}
        filter_tenant = str(tenant_id or "").strip() or None
        filter_workspace = str(workspace_id or "").strip() or None
        filter_environment = str(environment or "").strip() or None
        items: list[dict[str, Any]] = []
        for raw_tenant_id, tenant_cfg in tenants.items():
            tenant_key = str(raw_tenant_id)
            if filter_tenant and tenant_key != filter_tenant:
                continue
            workspaces = []
            for raw_workspace_id, workspace_cfg in (getattr(tenant_cfg, "workspaces", {}) or {}).items():
                workspace_key = str(raw_workspace_id)
                if filter_workspace and workspace_key != filter_workspace:
                    continue
                env_settings = getattr(workspace_cfg, "environment_settings", {}) or {}
                environment_items = []
                for env_name, env_cfg in env_settings.items():
                    if filter_environment and str(env_name) != filter_environment:
                        continue
                    environment_items.append(
                        {
                            "environment": env_name,
                            "display_name": str(getattr(env_cfg, "display_name", "") or ""),
                            "settings_overrides": self._mask_sensitive(dict(getattr(env_cfg, "settings_overrides", {}) or {})),
                        }
                    )
                environments = [str(x) for x in (getattr(workspace_cfg, "environments", []) or []) if not filter_environment or str(x) == filter_environment]
                if filter_environment and not environments and not environment_items:
                    continue
                workspaces.append(
                    {
                        "workspace_id": workspace_key,
                        "display_name": str(getattr(workspace_cfg, "display_name", "") or ""),
                        "environments": environments,
                        "default_environment": str(getattr(workspace_cfg, "default_environment", default_ctx.environment) or default_ctx.environment),
                        "settings_overrides": self._mask_sensitive(dict(getattr(workspace_cfg, "settings_overrides", {}) or {})),
                        "environment_settings": environment_items,
                    }
                )
            if filter_workspace and not workspaces:
                continue
            items.append(
                {
                    "tenant_id": tenant_key,
                    "display_name": str(getattr(tenant_cfg, "display_name", "") or ""),
                    "settings_overrides": self._mask_sensitive(dict(getattr(tenant_cfg, "settings_overrides", {}) or {})),
                    "workspaces": workspaces,
                }
            )
        return {
            "enabled": bool(getattr(tenancy, "enabled", False)),
            "headers": self.headers(settings),
            "default_scope": default_ctx.as_dict(),
            "scope": {"tenant_id": filter_tenant, "workspace_id": filter_workspace, "environment": filter_environment},
            "tenants": items,
        }

    def effective_config(
        self,
        settings: Any,
        *,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        scope = self.resolve(settings, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        tenancy = getattr(settings, "tenancy", None)
        tenants = getattr(tenancy, "tenants", {}) or {}
        tenant_cfg = tenants.get(scope.tenant_id)
        workspace_cfg = None if tenant_cfg is None else (getattr(tenant_cfg, "workspaces", {}) or {}).get(scope.workspace_id)
        env_cfg = None if workspace_cfg is None else (getattr(workspace_cfg, "environment_settings", {}) or {}).get(scope.environment)

        effective: dict[str, Any] = {}
        for section in self._EXPORTED_SECTIONS:
            value = getattr(settings, section, None)
            if value is not None:
                effective[section] = self._to_plain(value)

        layers = {
            "tenant": self._to_plain(getattr(tenant_cfg, "settings_overrides", {}) or {}),
            "workspace": self._to_plain(getattr(workspace_cfg, "settings_overrides", {}) or {}),
            "environment": self._to_plain(getattr(env_cfg, "settings_overrides", {}) or {}),
        }
        for layer_name in ("tenant", "workspace", "environment"):
            self._deep_merge(effective, layers[layer_name])

        return {
            "scope": scope.as_dict(),
            "effective": self._mask_sensitive(effective),
            "applied_overrides": {k: self._mask_sensitive(v) for k, v in layers.items() if v},
        }

    def _to_plain(self, value: Any) -> Any:
        if is_dataclass(value):
            return asdict(value)
        if isinstance(value, dict):
            return {str(k): self._to_plain(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._to_plain(v) for v in value]
        return value

    def _deep_merge(self, target: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
        for key, value in incoming.items():
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                self._deep_merge(target[key], value)
            else:
                target[key] = value
        return target

    def _mask_sensitive(self, value: Any) -> Any:
        if isinstance(value, dict):
            out: dict[str, Any] = {}
            for key, item in value.items():
                lowered = str(key).lower()
                if any(mark in lowered for mark in ("secret", "token", "password", "passphrase", "api_key")):
                    out[str(key)] = "***"
                else:
                    out[str(key)] = self._mask_sensitive(item)
            return out
        if isinstance(value, list):
            return [self._mask_sensitive(v) for v in value]
        return value
