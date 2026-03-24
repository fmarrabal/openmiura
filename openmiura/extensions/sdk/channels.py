from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .context import ChannelAdapterContext, ChannelMessage, ExtensionLifecycleContext
from .manifests import ExtensionManifest


@runtime_checkable
class ChannelAdapterExtension(Protocol):
    manifest: ExtensionManifest

    def initialize(self, ctx: ExtensionLifecycleContext) -> None: ...

    def normalize_inbound(self, payload: Any, ctx: ChannelAdapterContext) -> ChannelMessage: ...

    def format_outbound(self, response: Any, ctx: ChannelAdapterContext) -> Any: ...

    def shutdown(self) -> None: ...
