from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ScopeRBACInfo:
    username_roles: dict[str, str] = field(default_factory=dict)
    user_key_roles: dict[str, str] = field(default_factory=dict)
    permission_grants: dict[str, list[str]] = field(default_factory=dict)
    permission_denies: dict[str, list[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class EnvironmentInfo:
    environment: str
    display_name: str = ""
    settings_overrides: dict[str, Any] = field(default_factory=dict)
    rbac: ScopeRBACInfo = field(default_factory=ScopeRBACInfo)


@dataclass(frozen=True)
class WorkspaceInfo:
    workspace_id: str
    display_name: str = ""
    environments: list[str] = field(default_factory=list)
    default_environment: str = "prod"
    settings_overrides: dict[str, Any] = field(default_factory=dict)
    environment_settings: dict[str, EnvironmentInfo] = field(default_factory=dict)
    rbac: ScopeRBACInfo = field(default_factory=ScopeRBACInfo)


@dataclass(frozen=True)
class TenantInfo:
    tenant_id: str
    display_name: str = ""
    settings_overrides: dict[str, Any] = field(default_factory=dict)
    workspaces: dict[str, WorkspaceInfo] = field(default_factory=dict)
    rbac: ScopeRBACInfo = field(default_factory=ScopeRBACInfo)


@dataclass(frozen=True)
class TenantContext:
    tenant_id: str
    workspace_id: str
    environment: str

    def as_dict(self) -> dict[str, str]:
        return {
            "tenant_id": self.tenant_id,
            "workspace_id": self.workspace_id,
            "environment": self.environment,
        }
