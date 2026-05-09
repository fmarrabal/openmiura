"""openmiura.application.admin.service._evaluations_mixin

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


class _AdminServiceEvaluationsMixin:
    """Mixin: evaluations methods on AdminService."""

    def list_evaluation_suites(self, gw: AdminGatewayLike) -> dict[str, Any]:
        return self.evaluation_service.list_suites(gw)

    def run_evaluation_suite(
        self,
        gw: AdminGatewayLike,
        *,
        suite_name: str,
        observations: list[dict[str, Any]],
        requested_by: str = "admin",
        provider: str | None = None,
        model: str | None = None,
        agent_name: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.evaluation_service.run_suite(
            gw,
            suite_name=suite_name,
            observations=observations,
            requested_by=requested_by,
            provider=provider,
            model=model,
            agent_name=agent_name,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def list_evaluation_runs(
        self,
        gw: AdminGatewayLike,
        *,
        limit: int = 20,
        suite_name: str | None = None,
        status: str | None = None,
        agent_name: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.evaluation_service.list_runs(
            gw,
            limit=limit,
            suite_name=suite_name,
            status=status,
            agent_name=agent_name,
            provider=provider,
            model=model,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def get_evaluation_run(self, gw: AdminGatewayLike, *, run_id: str) -> dict[str, Any]:
        return self.evaluation_service.get_run(gw, run_id=run_id)

    def compare_evaluation_run(self, gw: AdminGatewayLike, *, run_id: str, baseline_run_id: str | None = None) -> dict[str, Any]:
        return self.evaluation_service.compare_runs(gw, run_id=run_id, baseline_run_id=baseline_run_id)

    def list_evaluation_regressions(
        self,
        gw: AdminGatewayLike,
        *,
        limit: int = 20,
        suite_name: str | None = None,
        agent_name: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.evaluation_service.list_regressions(
            gw,
            limit=limit,
            suite_name=suite_name,
            agent_name=agent_name,
            provider=provider,
            model=model,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def evaluation_scorecards(
        self,
        gw: AdminGatewayLike,
        *,
        group_by: str = "agent_provider_model",
        limit: int = 20,
        suite_name: str | None = None,
        agent_name: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.evaluation_service.scorecards(
            gw,
            group_by=group_by,
            limit=limit,
            suite_name=suite_name,
            agent_name=agent_name,
            provider=provider,
            model=model,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def evaluation_leaderboard(
        self,
        gw: AdminGatewayLike,
        *,
        group_by: str = "agent_provider_model",
        rank_by: str = "stability_score",
        limit: int = 20,
        use_case: str | None = None,
        suite_name: str | None = None,
        agent_name: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.evaluation_service.leaderboard(
            gw,
            group_by=group_by,
            rank_by=rank_by,
            limit=limit,
            use_case=use_case,
            suite_name=suite_name,
            agent_name=agent_name,
            provider=provider,
            model=model,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def evaluation_comparison(
        self,
        gw: AdminGatewayLike,
        *,
        split_by: str = "use_case",
        compare_by: str = "agent_provider_model",
        rank_by: str = "stability_score",
        limit_groups: int = 20,
        limit_per_group: int = 5,
        suite_name: str | None = None,
        agent_name: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.evaluation_service.comparison(
            gw,
            split_by=split_by,
            compare_by=compare_by,
            rank_by=rank_by,
            limit_groups=limit_groups,
            limit_per_group=limit_per_group,
            suite_name=suite_name,
            agent_name=agent_name,
            provider=provider,
            model=model,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

