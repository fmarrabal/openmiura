"""openmiura.application.admin.service._memory_mixin

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


class _AdminServiceMemoryMixin:
    """Mixin: memory methods on AdminService."""

    def search_memory_semantic_or_table(
        self,
        gw: AdminGatewayLike,
        *,
        q: str | None,
        user_key: str | None,
        top_k: int,
    ) -> dict[str, Any]:
        return self.memory_service.semantic_or_table_search(gw, q=q, user_key=user_key, top_k=top_k)

    def search_memory(
        self,
        gw: AdminGatewayLike,
        *,
        user_key: str | None,
        kind: str | None,
        text_contains: str | None,
        limit: int,
    ) -> dict[str, Any]:
        admin_cfg = getattr(getattr(gw, "settings", None), "admin", None)
        max_rows = int(getattr(admin_cfg, "max_search_results", 100) or 100)
        return self.memory_service.search(
            gw,
            user_key=user_key,
            kind=kind,
            text_contains=text_contains,
            limit=limit,
            max_rows=max_rows,
        )

    def delete_memory(
        self,
        gw: AdminGatewayLike,
        *,
        user_key: str,
        kind: str | None,
        dry_run: bool,
    ) -> dict[str, Any]:
        return self.memory_service.delete(gw, user_key=user_key, kind=kind, dry_run=dry_run)

    def delete_memory_by_id(self, gw: AdminGatewayLike, *, item_id: int) -> dict[str, Any]:
        return self.memory_service.delete_by_id(gw, item_id=item_id)

