from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class PolicyTrace:
    scope: str
    name: str
    effect: str
    reason: str = ""
    rule: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PolicyDecision:
    allowed: bool
    requires_confirmation: bool = False
    requires_approval: bool = False
    reason: str = ""
    matched_rules: list[str] = field(default_factory=list)
    explanation: list[PolicyTrace] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "requires_confirmation": self.requires_confirmation,
            "requires_approval": self.requires_approval,
            "reason": self.reason,
            "matched_rules": list(self.matched_rules),
            "explanation": [
                {
                    "scope": item.scope,
                    "name": item.name,
                    "effect": item.effect,
                    "reason": item.reason,
                }
                for item in self.explanation
            ],
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class ToolAccessDecision(PolicyDecision):
    pass
