from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .context import ExtensionLifecycleContext, ToolExecutionContext
from .manifests import ExtensionManifest


@runtime_checkable
class ToolExtension(Protocol):
    manifest: ExtensionManifest

    def initialize(self, ctx: ExtensionLifecycleContext) -> None: ...

    def execute(self, arguments: dict[str, Any], ctx: ToolExecutionContext) -> Any: ...

    def shutdown(self) -> None: ...
