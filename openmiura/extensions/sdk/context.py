from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ExtensionLifecycleContext:
    settings: Any | None = None
    logger: Any | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ToolExecutionContext:
    agent_name: str
    user_key: str | None = None
    tenant_id: str | None = None
    workspace_id: str | None = None
    permissions: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SkillExecutionContext:
    agent_name: str
    requested_skills: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ProviderExecutionContext:
    model: str
    tenant_id: str | None = None
    workspace_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ChannelMessage:
    channel: str
    channel_user_id: str
    text: str
    conversation_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ChannelAdapterContext:
    tenant_id: str | None = None
    workspace_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class StorageContext:
    tenant_id: str | None = None
    workspace_id: str | None = None
    environment: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AuthRequestContext:
    channel: str | None = None
    tenant_id: str | None = None
    workspace_id: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
