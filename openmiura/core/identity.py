from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from openmiura.core.audit import AuditStore


@dataclass
class IdentityManager:
    audit: AuditStore

    def resolve(self, channel_key: str) -> str | None:
        return self.audit.get_identity(channel_key)

    def link(self, channel_key: str, global_user_key: str, linked_by: str = "system") -> None:
        self.audit.set_identity(channel_user_key=channel_key, global_user_key=global_user_key, linked_by=linked_by)

    def unlink(self, channel_key: str) -> int:
        return self.audit.delete_identity(channel_user_key=channel_key)

    def list_links(self, global_user_key: str | None = None) -> list[dict[str, Any]]:
        return self.audit.list_identities(global_user_key=global_user_key)
