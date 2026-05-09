"""openmiura.application.admin.service._release_packaging_mixin

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


class _AdminServiceReleasePackagingMixin:
    """Mixin: release packaging methods on AdminService."""

    def list_releases(
        self,
        gw: AdminGatewayLike,
        *,
        limit: int = 50,
        status: str | None = None,
        kind: str | None = None,
        name: str | None = None,
        environment: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        return self.release_service.list_releases(
            gw,
            limit=limit,
            status=status,
            kind=kind,
            name=name,
            environment=environment,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )

    def get_release(
        self,
        gw: AdminGatewayLike,
        *,
        release_id: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.release_service.get_release(
            gw,
            release_id=release_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def create_release(
        self,
        gw: AdminGatewayLike,
        *,
        kind: str,
        name: str,
        version: str,
        created_by: str,
        items: list[dict[str, Any]] | None = None,
        environment: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        notes: str = '',
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.release_service.create_release(
            gw,
            kind=kind,
            name=name,
            version=version,
            created_by=created_by,
            items=items,
            environment=environment,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            notes=notes,
            metadata=metadata,
        )

    def submit_release(
        self,
        gw: AdminGatewayLike,
        *,
        release_id: str,
        actor: str,
        reason: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        return self.release_service.submit_release(
            gw,
            release_id=release_id,
            actor=actor,
            reason=reason,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )

    def promote_release(
        self,
        gw: AdminGatewayLike,
        *,
        release_id: str,
        to_environment: str,
        actor: str,
        reason: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        return self.release_service.promote_release(
            gw,
            release_id=release_id,
            to_environment=to_environment,
            actor=actor,
            reason=reason,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )

    def configure_release_canary(
        self,
        gw: AdminGatewayLike,
        *,
        release_id: str,
        target_environment: str,
        actor: str,
        strategy: str = 'percentage',
        traffic_percent: float = 0,
        step_percent: float = 0,
        bake_minutes: int = 0,
        metric_guardrails: dict[str, Any] | None = None,
        analysis_summary: dict[str, Any] | None = None,
        status: str = 'draft',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        return self.release_service.configure_canary(
            gw,
            release_id=release_id,
            target_environment=target_environment,
            actor=actor,
            strategy=strategy,
            traffic_percent=traffic_percent,
            step_percent=step_percent,
            bake_minutes=bake_minutes,
            metric_guardrails=metric_guardrails,
            analysis_summary=analysis_summary,
            status=status,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )

    def activate_release_canary(
        self,
        gw: AdminGatewayLike,
        *,
        release_id: str,
        actor: str,
        baseline_release_id: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        return self.release_service.activate_canary(
            gw,
            release_id=release_id,
            actor=actor,
            baseline_release_id=baseline_release_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )

    def resolve_release_canary_route(
        self,
        gw: AdminGatewayLike,
        *,
        release_id: str,
        routing_key: str,
        actor: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        return self.release_service.resolve_canary_route(
            gw,
            release_id=release_id,
            routing_key=routing_key,
            actor=actor,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )

    def record_release_canary_observation(
        self,
        gw: AdminGatewayLike,
        *,
        decision_id: str,
        actor: str,
        success: bool,
        latency_ms: float | None = None,
        cost_estimate: float | None = None,
        metadata: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        return self.release_service.record_canary_observation(
            gw,
            decision_id=decision_id,
            actor=actor,
            success=success,
            latency_ms=latency_ms,
            cost_estimate=cost_estimate,
            metadata=metadata,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )

    def release_canary_routing_summary(
        self,
        gw: AdminGatewayLike,
        *,
        release_id: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        target_environment: str | None = None,
    ) -> dict[str, Any]:
        return self.release_service.routing_summary(
            gw,
            release_id=release_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            target_environment=target_environment,
        )

    def record_release_gate_run(
        self,
        gw: AdminGatewayLike,
        *,
        release_id: str,
        gate_name: str,
        status: str,
        actor: str,
        score: float | None = None,
        threshold: float | None = None,
        details: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.release_service.record_gate_run(
            gw,
            release_id=release_id,
            gate_name=gate_name,
            status=status,
            actor=actor,
            score=score,
            threshold=threshold,
            details=details,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def set_release_change_report(
        self,
        gw: AdminGatewayLike,
        *,
        release_id: str,
        risk_level: str,
        actor: str,
        summary: dict[str, Any] | None = None,
        diff: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        return self.release_service.set_change_report(
            gw,
            release_id=release_id,
            risk_level=risk_level,
            actor=actor,
            summary=summary,
            diff=diff,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )

    def rollback_release(
        self,
        gw: AdminGatewayLike,
        *,
        release_id: str,
        actor: str,
        reason: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        return self.release_service.rollback_release(
            gw,
            release_id=release_id,
            actor=actor,
            reason=reason,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )

    def phase8_packaging_summary(self, gw: AdminGatewayLike) -> dict[str, Any]:
        return self.packaging_hardening_service.packaging_summary(gw)

    def phase8_hardening_summary(self, gw: AdminGatewayLike) -> dict[str, Any]:
        return self.packaging_hardening_service.hardening_summary(gw)

    def create_reproducible_package_build(
        self,
        gw: AdminGatewayLike,
        *,
        actor: str,
        target: str,
        label: str,
        version: str = 'phase9-operational-hardening',
        source_root: str | None = None,
        output_dir: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.packaging_hardening_service.create_reproducible_build(
            gw,
            actor=actor,
            target=target,
            label=label,
            version=version,
            source_root=source_root,
            output_dir=output_dir,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def list_package_builds(
        self,
        gw: AdminGatewayLike,
        *,
        limit: int = 50,
        target: str | None = None,
        status: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.packaging_hardening_service.list_package_builds(
            gw,
            limit=limit,
            target=target,
            status=status,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def create_package_build(
        self,
        gw: AdminGatewayLike,
        *,
        actor: str,
        target: str,
        label: str,
        version: str = 'phase8-pr8',
        artifact_path: str = '',
        status: str = 'ready',
        metadata: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.packaging_hardening_service.create_package_build(
            gw,
            actor=actor,
            target=target,
            label=label,
            version=version,
            artifact_path=artifact_path,
            status=status,
            metadata=metadata,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

