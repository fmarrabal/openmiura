from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from openmiura.core.audit import AuditStore
from openmiura.core.tenancy.scope import build_scoped_identity_key, parse_scoped_identity_key


@dataclass
class IdentityManager:
    audit: AuditStore

    def resolve(
        self,
        channel_key: str,
        *,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> str | None:
        del environment
        scoped_key = build_scoped_identity_key(channel_key, tenant_id=tenant_id, workspace_id=workspace_id)
        value = self.audit.get_identity(scoped_key, tenant_id=tenant_id, workspace_id=workspace_id)
        if value is not None:
            return value
        if scoped_key != channel_key:
            return None
        return self.audit.get_identity(channel_key, tenant_id=tenant_id, workspace_id=workspace_id)

    def link(
        self,
        channel_key: str,
        global_user_key: str,
        linked_by: str = "system",
        *,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> None:
        del environment
        scoped_key = build_scoped_identity_key(channel_key, tenant_id=tenant_id, workspace_id=workspace_id)
        self.audit.set_identity(
            channel_user_key=scoped_key,
            global_user_key=global_user_key,
            linked_by=linked_by,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )

    def unlink(
        self,
        channel_key: str,
        *,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> int:
        del environment
        scoped_key = build_scoped_identity_key(channel_key, tenant_id=tenant_id, workspace_id=workspace_id)
        return self.audit.delete_identity(scoped_key, tenant_id=tenant_id, workspace_id=workspace_id)

    def list_links(
        self,
        global_user_key: str | None = None,
        *,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> list[dict[str, Any]]:
        del environment
        items = self.audit.list_identities(global_user_key=global_user_key, tenant_id=tenant_id, workspace_id=workspace_id)
        out: list[dict[str, Any]] = []
        for item in items:
            _, _, channel_key = parse_scoped_identity_key(str(item.get("channel_user_key") or ""))
            out.append({**item, "channel_user_key": channel_key})
        return out
