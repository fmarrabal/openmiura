"""openmiura.application.admin.service._helpers_mixin

Part of the AdminService split. Methods originally lived on
``openmiura.application.admin.service.AdminService``; they have been
moved verbatim into this mixin so that no individual file in the
package exceeds the project's ``max 1,500 lines`` ceiling. The
public class still inherits from this mixin and exposes every
method unchanged.

The module-level ``AdminService = None`` sentinel is rebound by
``service/__init__.py`` once the final class is defined; this lets
the mixin's ``@staticmethod`` call sites that reference
``AdminService.foo(...)`` resolve correctly at call time without
introducing a circular import.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from openmiura.application.admin.status_snapshot import (
    build_status_snapshot,
    collect_registered_tool_names,
)
from openmiura.application.canvas import LiveCanvasService
from openmiura.application.costs import CostGovernanceService
from openmiura.application.evaluations import EvaluationService
from openmiura.application.memory import MemoryService
from openmiura.application.operator import OperatorConsoleService
from openmiura.application.packaging import PackagingHardeningService
from openmiura.application.pwa import PWAFoundationService
from openmiura.application.releases import ReleaseService
from openmiura.application.replay import ReplayService
from openmiura.application.runtime_adapters.external import (
    OpenClawAdapterService,
    OpenClawRecoverySchedulerService,
)
from openmiura.application.secrets import SecretGovernanceService
from openmiura.application.sessions import SessionService
from openmiura.application.tenancy import TenancyService
from openmiura.application.voice import VoiceRuntimeService
from openmiura import __version__
from openmiura.core.config import resolve_config_related_path
from openmiura.core.contracts import AdminGatewayLike
from openmiura.core.policies.engine import PolicyEngine


AdminService: type | None = None  # late-bound by service/__init__.py


class _AdminServiceHelpersMixin:
    """Mixin: helpers methods on AdminService."""

    def _normalize_policy_request(self, raw: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(raw or {})
        return {
            "scope": str(payload.get("scope") or "tool"),
            "resource_name": str(payload.get("resource_name") or payload.get("tool_name") or ""),
            "action": str(payload.get("action") or "use"),
            "agent_name": payload.get("agent_name"),
            "user_role": payload.get("user_role"),
            "tenant_id": payload.get("tenant_id"),
            "workspace_id": payload.get("workspace_id"),
            "environment": payload.get("environment"),
            "channel": payload.get("channel"),
            "domain": payload.get("domain"),
            "extra": dict(payload.get("extra") or {}),
            "tool_name": payload.get("tool_name"),
        }

    @staticmethod
    def _safe_call(obj: object, method_name: str, default: Any, *args: Any, **kwargs: Any) -> Any:
        fn = getattr(obj, method_name, None)
        if callable(fn):
            try:
                return fn(*args, **kwargs)
            except Exception:
                return default
        return default

    @staticmethod
    def _resolve_config_related_path(base_config_path: Path, raw_path: str, *, default_path: str = '.') -> Path:
        return resolve_config_related_path(base_config_path, raw_path, default_path=default_path)

    def _normalize_channel_name(self, channel: str) -> str:
        normalized = str(channel or '').strip().lower()
        if normalized not in self._channel_wizard_channel_names():
            raise ValueError('unsupported_channel_wizard_channel')
        return normalized

