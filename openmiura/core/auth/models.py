from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class AuthContext:
    mode: str = "anonymous"
    user_key: str | None = None
    token: dict[str, Any] | None = None
    role: str | None = None
    username: str | None = None
    permissions: list[str] = field(default_factory=list)
    tenant_id: str | None = None
    workspace_id: str | None = None
    environment: str | None = None
    base_role: str | None = None
    bound_tenant_id: str | None = None
    bound_workspace_id: str | None = None
    bound_environment: str | None = None
    scope_access: str | None = None
    scope_level: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "user_key": self.user_key,
            "token": self.token,
            "role": self.role,
            "username": self.username,
            "permissions": list(self.permissions),
            "tenant_id": self.tenant_id,
            "workspace_id": self.workspace_id,
            "environment": self.environment,
            "base_role": self.base_role,
            "bound_tenant_id": self.bound_tenant_id,
            "bound_workspace_id": self.bound_workspace_id,
            "bound_environment": self.bound_environment,
            "scope_access": self.scope_access,
            "scope_level": self.scope_level,
        }
