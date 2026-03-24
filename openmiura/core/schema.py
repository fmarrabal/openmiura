from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class InboundMessage(BaseModel):
    channel: str = "http"
    user_id: str
    text: str
    session_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class OutboundMessage(BaseModel):
    channel: str = "http"
    user_id: str
    session_id: str
    agent_id: str
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)
