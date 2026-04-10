from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]
    id: str | None = None


@dataclass
class ChatResponse:
    content: str
    tool_calls: list[ToolCall]
    usage: dict[str, int] | None = None
