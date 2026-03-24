from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .context import AuthRequestContext, ExtensionLifecycleContext
from .manifests import ExtensionManifest


@runtime_checkable
class AuthProviderExtension(Protocol):
    manifest: ExtensionManifest

    def initialize(self, ctx: ExtensionLifecycleContext) -> None: ...

    def authenticate(self, credentials: dict[str, Any], ctx: AuthRequestContext) -> Any: ...

    def shutdown(self) -> None: ...
