from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .context import ExtensionLifecycleContext, ProviderExecutionContext
from .manifests import ExtensionManifest


@runtime_checkable
class LLMProviderExtension(Protocol):
    manifest: ExtensionManifest

    def initialize(self, ctx: ExtensionLifecycleContext) -> None: ...

    def complete(self, prompt: str, ctx: ProviderExecutionContext, **kwargs: Any) -> Any: ...

    def shutdown(self) -> None: ...
