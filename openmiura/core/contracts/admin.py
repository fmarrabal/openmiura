from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable


@runtime_checkable
class AuditStoreLike(Protocol):
    def table_counts(self) -> dict[str, int]: ...
    def count_memory_items(self, user_key: str | None = None, kind: str | None = None) -> int: ...
    def count_sessions(self, **kwargs: Any) -> int: ...
    def count_active_sessions(self, **kwargs: Any) -> int: ...
    def get_last_event(self, **kwargs: Any) -> Any: ...
    def get_recent_events(self, **kwargs: Any) -> list[dict[str, Any]]: ...
    def list_sessions(self, **kwargs: Any) -> list[dict[str, Any]]: ...
    def search_memory_items(self, **kwargs: Any) -> list[dict[str, Any]]: ...
    def delete_memory_items(self, **kwargs: Any) -> int: ...
    def delete_memory_item_by_id(self, item_id: int, user_key: str | None = None) -> int: ...
    def list_identities(self, global_user_key: str | None = None) -> list[dict[str, Any]]: ...
    def log_event(self, **kwargs: Any) -> None: ...


@runtime_checkable
class RouterLike(Protocol):
    def available_agents(self) -> list[str]: ...


@runtime_checkable
class ToolRegistryLike(Protocol):
    _tools: dict[str, Any]


@runtime_checkable
class ToolRuntimeLike(Protocol):
    registry: ToolRegistryLike


@runtime_checkable
class IdentityManagerLike(Protocol):
    def list_links(self, global_user_key: str | None = None) -> list[dict[str, Any]]: ...
    def link(self, channel_user_key: str, global_user_key: str, linked_by: str = "admin") -> None: ...


@runtime_checkable
class PolicyLike(Protocol):
    pass


@runtime_checkable
class AdminGatewayLike(Protocol):
    settings: Any
    audit: AuditStoreLike
    router: RouterLike | None
    tools: ToolRuntimeLike | None
    telegram: Any
    slack: Any
    policy: PolicyLike | None
    identity: IdentityManagerLike | None
    started_at: float

    def reload_dynamic_configs(self, force: bool = False) -> dict[str, Any]: ...
