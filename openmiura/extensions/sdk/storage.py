from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .context import ExtensionLifecycleContext, StorageContext
from .manifests import ExtensionManifest


@runtime_checkable
class StorageBackendExtension(Protocol):
    manifest: ExtensionManifest

    def initialize(self, ctx: ExtensionLifecycleContext) -> None: ...

    def get(self, key: str, ctx: StorageContext) -> Any: ...

    def put(self, key: str, value: Any, ctx: StorageContext) -> None: ...

    def delete(self, key: str, ctx: StorageContext) -> None: ...

    def shutdown(self) -> None: ...
