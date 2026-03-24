from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .context import ExtensionLifecycleContext, SkillExecutionContext
from .manifests import ExtensionManifest


@runtime_checkable
class SkillExtension(Protocol):
    manifest: ExtensionManifest

    def initialize(self, ctx: ExtensionLifecycleContext) -> None: ...

    def extend_agent_config(self, agent_cfg: dict[str, Any], ctx: SkillExecutionContext) -> dict[str, Any]: ...

    def shutdown(self) -> None: ...
