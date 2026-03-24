from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .context import ExtensionLifecycleContext
from .manifests import ExtensionManifest


@runtime_checkable
class ObservabilityExporterExtension(Protocol):
    manifest: ExtensionManifest

    def initialize(self, ctx: ExtensionLifecycleContext) -> None: ...

    def emit(self, event: dict[str, Any]) -> None: ...

    def shutdown(self) -> None: ...
