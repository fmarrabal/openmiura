from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .context import ExtensionLifecycleContext, ToolExecutionContext
from .manifests import ExtensionManifest


@dataclass(slots=True)
class FakeToolRegistry:
    tools: dict[str, Any] = field(default_factory=dict)

    def register(self, tool: Any) -> None:
        name = getattr(tool, "name", None) or getattr(getattr(tool, "manifest", None), "name", None)
        if not name:
            raise ValueError("Registered tool must expose a name")
        self.tools[str(name)] = tool

    def names(self) -> list[str]:
        return sorted(self.tools)


class NoopTool:
    manifest = ExtensionManifest(name="noop", kind="tool")

    def initialize(self, ctx: ExtensionLifecycleContext) -> None:
        self._ctx = ctx

    def execute(self, arguments: dict[str, Any], ctx: ToolExecutionContext) -> Any:
        return {"ok": True, "arguments": dict(arguments), "agent_name": ctx.agent_name}

    def shutdown(self) -> None:
        self._ctx = None
