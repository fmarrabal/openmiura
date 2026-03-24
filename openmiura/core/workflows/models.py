from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class WorkflowStep:
    id: str
    kind: str = 'note'
    name: str = ''
    tool_name: str | None = None
    args: dict[str, Any] = field(default_factory=dict)
    requested_role: str | None = None
    note: str = ''


@dataclass(frozen=True)
class WorkflowDefinition:
    name: str
    steps: list[WorkflowStep] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ApprovalDecision:
    approval_id: str
    decision: str
    decided_by: str
    reason: str = ''


@dataclass(frozen=True)
class JobSchedule:
    name: str
    workflow_definition: dict[str, Any]
    interval_s: int | None = None
    enabled: bool = True
    input: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
