"""openmiura.application.admin.service._runtime_adapters_a_mixin

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


class _AdminServiceRuntimeAdaptersAMixin:
    """Mixin: runtime adapters a methods on AdminService."""

    def list_openclaw_policy_packs(
        self,
        gw: AdminGatewayLike,
        *,
        runtime_class: str | None = None,
        transport: str = 'http',
    ) -> dict[str, Any]:
        return self.openclaw_adapter_service.list_policy_packs(runtime_class=runtime_class, transport=transport)

    def apply_openclaw_policy_pack(
        self,
        gw: AdminGatewayLike,
        *,
        runtime_id: str,
        actor: str,
        pack_name: str | None = None,
        runtime_class: str | None = None,
        overrides: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_adapter_service.apply_policy_pack(
            gw,
            runtime_id=runtime_id,
            actor=actor,
            pack_name=pack_name,
            runtime_class=runtime_class,
            overrides=overrides,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def schedule_openclaw_runtime_recovery_job(
        self,
        gw: AdminGatewayLike,
        *,
        runtime_id: str,
        actor: str,
        reason: str = '',
        limit: int | None = None,
        schedule_kind: str | None = None,
        interval_s: int | None = None,
        schedule_expr: str | None = None,
        timezone_name: str | None = 'UTC',
        not_before: float | None = None,
        not_after: float | None = None,
        max_runs: int | None = None,
        enabled: bool = True,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.schedule_runtime_recovery_job(
            gw,
            runtime_id=runtime_id,
            actor=actor,
            reason=reason,
            limit=limit,
            schedule_kind=schedule_kind,
            interval_s=interval_s,
            schedule_expr=schedule_expr,
            timezone_name=timezone_name,
            not_before=not_before,
            not_after=not_after,
            max_runs=max_runs,
            enabled=enabled,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def list_openclaw_recovery_jobs(
        self,
        gw: AdminGatewayLike,
        *,
        limit: int = 100,
        enabled: bool | None = None,
        runtime_id: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.list_recovery_jobs(
            gw,
            limit=limit,
            enabled=enabled,
            runtime_id=runtime_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def list_openclaw_worker_leases(
        self,
        gw: AdminGatewayLike,
        *,
        limit: int = 100,
        active_only: bool | None = None,
        lease_type: str | None = None,
        runtime_id: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.list_worker_leases(
            gw,
            limit=limit,
            active_only=active_only,
            lease_type=lease_type,
            runtime_id=runtime_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def list_openclaw_idempotency_records(
        self,
        gw: AdminGatewayLike,
        *,
        limit: int = 100,
        active_only: bool | None = None,
        status: str | None = None,
        runtime_id: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.list_idempotency_records(
            gw,
            limit=limit,
            active_only=active_only,
            status=status,
            runtime_id=runtime_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def get_openclaw_runtime_concurrency(
        self,
        gw: AdminGatewayLike,
        *,
        runtime_id: str,
        limit: int = 20,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.get_runtime_concurrency(
            gw,
            runtime_id=runtime_id,
            limit=limit,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def get_openclaw_runtime_alerts(
        self,
        gw: AdminGatewayLike,
        *,
        runtime_id: str,
        limit: int = 50,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.evaluate_runtime_alerts(
            gw,
            runtime_id=runtime_id,
            limit=limit,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def list_openclaw_runtime_alerts(
        self,
        gw: AdminGatewayLike,
        *,
        limit: int = 100,
        severity: str | None = None,
        runtime_id: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.list_runtime_alerts(
            gw,
            limit=limit,
            severity=severity,
            runtime_id=runtime_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def list_openclaw_alert_states(
        self,
        gw: AdminGatewayLike,
        *,
        limit: int = 100,
        runtime_id: str | None = None,
        workflow_status: str | None = None,
        severity: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.list_runtime_alert_states(
            gw,
            limit=limit,
            runtime_id=runtime_id,
            workflow_status=workflow_status,
            severity=severity,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def list_openclaw_alert_escalation_approvals(
        self,
        gw: AdminGatewayLike,
        *,
        limit: int = 100,
        runtime_id: str | None = None,
        status: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.list_alert_escalation_approvals(
            gw,
            limit=limit,
            runtime_id=runtime_id,
            status=status,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def list_openclaw_notification_targets(
        self,
        gw: AdminGatewayLike,
        *,
        runtime_id: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.list_runtime_notification_targets(
            gw,
            runtime_id=runtime_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def list_openclaw_alert_notification_dispatches(
        self,
        gw: AdminGatewayLike,
        *,
        runtime_id: str | None = None,
        alert_code: str | None = None,
        target_type: str | None = None,
        delivery_status: str | None = None,
        workflow_action: str | None = None,
        limit: int = 100,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.list_runtime_alert_notification_dispatches(
            gw,
            runtime_id=runtime_id,
            alert_code=alert_code,
            target_type=target_type,
            delivery_status=delivery_status,
            workflow_action=workflow_action,
            limit=limit,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def get_openclaw_alert_routing(
        self,
        gw: AdminGatewayLike,
        *,
        runtime_id: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.get_runtime_alert_routing(
            gw,
            runtime_id=runtime_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def create_openclaw_alert_governance_bundle(
        self,
        gw: AdminGatewayLike,
        *,
        name: str,
        version: str,
        runtime_ids: list[str],
        actor: str,
        candidate_policy: dict[str, Any] | None = None,
        merge_with_current: bool = True,
        waves: list[dict[str, Any]] | list[list[str]] | None = None,
        wave_size: int | None = None,
        wave_gates: dict[str, Any] | None = None,
        wave_timing_policy: dict[str, Any] | None = None,
        promotion_slo_policy: dict[str, Any] | None = None,
        progressive_exposure_policy: dict[str, Any] | None = None,
        reason: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.create_runtime_alert_governance_bundle(
            gw,
            name=name,
            version=version,
            runtime_ids=runtime_ids,
            actor=actor,
            candidate_policy=candidate_policy,
            merge_with_current=merge_with_current,
            waves=waves,
            wave_size=wave_size,
            wave_gates=wave_gates,
            wave_timing_policy=wave_timing_policy,
            promotion_slo_policy=promotion_slo_policy,
            progressive_exposure_policy=progressive_exposure_policy,
            reason=reason,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            limit=limit,
        )

    def list_openclaw_alert_governance_bundles(
        self,
        gw: AdminGatewayLike,
        *,
        limit: int = 50,
        status: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        runtime_id: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.list_runtime_alert_governance_bundles(
            gw,
            limit=limit,
            status=status,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            runtime_id=runtime_id,
        )

    def get_openclaw_alert_governance_bundle_analytics(
        self,
        gw: AdminGatewayLike,
        *,
        bundle_id: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.get_runtime_alert_governance_bundle_analytics(
            gw,
            bundle_id=bundle_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def get_openclaw_alert_governance_bundle(
        self,
        gw: AdminGatewayLike,
        *,
        bundle_id: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.get_runtime_alert_governance_bundle(
            gw,
            bundle_id=bundle_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def submit_openclaw_alert_governance_bundle(
        self,
        gw: AdminGatewayLike,
        *,
        bundle_id: str,
        actor: str,
        reason: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.submit_runtime_alert_governance_bundle(
            gw,
            bundle_id=bundle_id,
            actor=actor,
            reason=reason,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def approve_openclaw_alert_governance_bundle(
        self,
        gw: AdminGatewayLike,
        *,
        bundle_id: str,
        actor: str,
        reason: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.approve_runtime_alert_governance_bundle(
            gw,
            bundle_id=bundle_id,
            actor=actor,
            reason=reason,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def run_openclaw_alert_governance_bundle_wave(
        self,
        gw: AdminGatewayLike,
        *,
        bundle_id: str,
        wave_no: int,
        actor: str,
        reason: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.run_runtime_alert_governance_bundle_wave(
            gw,
            bundle_id=bundle_id,
            wave_no=wave_no,
            actor=actor,
            reason=reason,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            limit=limit,
        )

    def create_openclaw_alert_governance_portfolio(
        self,
        gw: AdminGatewayLike,
        *,
        name: str,
        version: str,
        bundle_ids: list[str],
        actor: str,
        train_calendar: list[dict[str, Any]] | None = None,
        train_policy: dict[str, Any] | None = None,
        reason: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.create_runtime_alert_governance_portfolio(
            gw,
            name=name,
            version=version,
            bundle_ids=bundle_ids,
            actor=actor,
            train_calendar=train_calendar,
            train_policy=train_policy,
            reason=reason,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def list_openclaw_alert_governance_portfolios(
        self,
        gw: AdminGatewayLike,
        *,
        limit: int = 50,
        status: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        runtime_id: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.list_runtime_alert_governance_portfolios(
            gw,
            limit=limit,
            status=status,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            runtime_id=runtime_id,
        )

    def get_openclaw_alert_governance_portfolio(
        self,
        gw: AdminGatewayLike,
        *,
        portfolio_id: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.get_runtime_alert_governance_portfolio(
            gw,
            portfolio_id=portfolio_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def submit_openclaw_alert_governance_portfolio(
        self,
        gw: AdminGatewayLike,
        *,
        portfolio_id: str,
        actor: str,
        reason: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.submit_runtime_alert_governance_portfolio(
            gw,
            portfolio_id=portfolio_id,
            actor=actor,
            reason=reason,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def approve_openclaw_alert_governance_portfolio(
        self,
        gw: AdminGatewayLike,
        *,
        portfolio_id: str,
        actor: str,
        reason: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.approve_runtime_alert_governance_portfolio(
            gw,
            portfolio_id=portfolio_id,
            actor=actor,
            reason=reason,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def get_openclaw_alert_governance_portfolio_calendar(
        self,
        gw: AdminGatewayLike,
        *,
        portfolio_id: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.get_runtime_alert_governance_portfolio_calendar(
            gw,
            portfolio_id=portfolio_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def simulate_openclaw_alert_governance_portfolio(
        self,
        gw: AdminGatewayLike,
        *,
        portfolio_id: str,
        actor: str,
        now_ts: float | None = None,
        dry_run: bool = True,
        auto_reschedule: bool | None = None,
        persist_schedule: bool = False,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.simulate_runtime_alert_governance_portfolio(
            gw,
            portfolio_id=portfolio_id,
            actor=actor,
            now_ts=now_ts,
            dry_run=dry_run,
            auto_reschedule=auto_reschedule,
            persist_schedule=persist_schedule,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def list_openclaw_alert_governance_portfolio_attestations(
        self,
        gw: AdminGatewayLike,
        *,
        portfolio_id: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.list_runtime_alert_governance_portfolio_attestations(
            gw,
            portfolio_id=portfolio_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def detect_openclaw_alert_governance_portfolio_drift(
        self,
        gw: AdminGatewayLike,
        *,
        portfolio_id: str,
        actor: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        persist_metadata: bool = True,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.detect_runtime_alert_governance_portfolio_drift(
            gw,
            portfolio_id=portfolio_id,
            actor=actor,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            persist_metadata=persist_metadata,
        )

    def list_openclaw_alert_governance_portfolio_chain_of_custody(
        self,
        gw: AdminGatewayLike,
        *,
        portfolio_id: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.list_runtime_alert_governance_portfolio_chain_of_custody(
            gw,
            portfolio_id=portfolio_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def list_openclaw_alert_governance_portfolio_custody_anchors(
        self,
        gw: AdminGatewayLike,
        *,
        portfolio_id: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.list_runtime_alert_governance_portfolio_custody_anchors(
            gw,
            portfolio_id=portfolio_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def reconcile_openclaw_alert_governance_portfolio_custody_anchors(
        self,
        gw: AdminGatewayLike,
        *,
        portfolio_id: str,
        actor: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.reconcile_runtime_alert_governance_portfolio_custody_anchors(
            gw,
            portfolio_id=portfolio_id,
            actor=actor,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def get_openclaw_alert_governance_portfolio_policy_conformance(
        self,
        gw: AdminGatewayLike,
        *,
        portfolio_id: str,
        actor: str = 'system',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        persist_metadata: bool = True,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.get_runtime_alert_governance_portfolio_policy_conformance(
            gw,
            portfolio_id=portfolio_id,
            actor=actor,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            persist_metadata=persist_metadata,
        )

    def get_openclaw_alert_governance_portfolio_policy_baseline_drift(
        self,
        gw: AdminGatewayLike,
        *,
        portfolio_id: str,
        actor: str = 'system',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        persist_metadata: bool = True,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.get_runtime_alert_governance_portfolio_policy_baseline_drift(
            gw,
            portfolio_id=portfolio_id,
            actor=actor,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            persist_metadata=persist_metadata,
        )

    def list_openclaw_alert_governance_portfolio_policy_deviation_exceptions(
        self,
        gw: AdminGatewayLike,
        *,
        portfolio_id: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.list_runtime_alert_governance_portfolio_policy_deviation_exceptions(
            gw,
            portfolio_id=portfolio_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def request_openclaw_alert_governance_portfolio_policy_deviation_exception(
        self,
        gw: AdminGatewayLike,
        *,
        portfolio_id: str,
        deviation_id: str,
        actor: str,
        reason: str = '',
        ttl_s: int | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.request_runtime_alert_governance_portfolio_policy_deviation_exception(
            gw,
            portfolio_id=portfolio_id,
            deviation_id=deviation_id,
            actor=actor,
            reason=reason,
            ttl_s=ttl_s,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def decide_openclaw_alert_governance_portfolio_policy_deviation_exception(
        self,
        gw: AdminGatewayLike,
        *,
        approval_id: str,
        actor: str,
        decision: str,
        reason: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.decide_runtime_alert_governance_portfolio_policy_deviation_exception(
            gw,
            approval_id=approval_id,
            actor=actor,
            decision=decision,
            reason=reason,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def create_openclaw_alert_governance_baseline_catalog(
        self,
        gw: AdminGatewayLike,
        *,
        name: str,
        version: str,
        actor: str,
        environment_policy_baselines: dict[str, Any] | None = None,
        promotion_policy: dict[str, Any] | None = None,
        parent_catalog_id: str | None = None,
        reason: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.create_runtime_alert_governance_baseline_catalog(
            gw,
            name=name,
            version=version,
            actor=actor,
            environment_policy_baselines=environment_policy_baselines,
            promotion_policy=promotion_policy,
            parent_catalog_id=parent_catalog_id,
            reason=reason,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def list_openclaw_alert_governance_baseline_catalogs(
        self,
        gw: AdminGatewayLike,
        *,
        limit: int = 50,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.list_runtime_alert_governance_baseline_catalogs(
            gw, limit=limit, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment
        )

    def get_openclaw_alert_governance_baseline_catalog(
        self,
        gw: AdminGatewayLike,
        *,
        catalog_id: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.get_runtime_alert_governance_baseline_catalog(
            gw, catalog_id=catalog_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment
        )

    def get_openclaw_alert_governance_baseline_promotion(
        self,
        gw: AdminGatewayLike,
        *,
        promotion_id: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.get_runtime_alert_governance_baseline_promotion(
            gw, promotion_id=promotion_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment
        )

    def get_openclaw_alert_governance_baseline_promotion_timeline(
        self,
        gw: AdminGatewayLike,
        *,
        promotion_id: str,
        limit: int = 200,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.get_runtime_alert_governance_baseline_promotion_timeline(
            gw, promotion_id=promotion_id, limit=limit, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment
        )

    def export_openclaw_alert_governance_baseline_promotion_attestation(
        self,
        gw: AdminGatewayLike,
        *,
        promotion_id: str,
        actor: str,
        timeline_limit: int | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.export_runtime_alert_governance_baseline_promotion_attestation(
            gw,
            promotion_id=promotion_id,
            actor=actor,
            timeline_limit=timeline_limit,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def export_openclaw_alert_governance_baseline_promotion_postmortem(
        self,
        gw: AdminGatewayLike,
        *,
        promotion_id: str,
        actor: str,
        timeline_limit: int | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.export_runtime_alert_governance_baseline_promotion_postmortem(
            gw,
            promotion_id=promotion_id,
            actor=actor,
            timeline_limit=timeline_limit,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def list_openclaw_alert_governance_baseline_advance_jobs(
        self,
        gw: AdminGatewayLike,
        *,
        limit: int = 100,
        promotion_id: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.list_baseline_promotion_wave_advance_jobs(
            gw,
            limit=limit,
            promotion_id=promotion_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def run_due_openclaw_alert_governance_baseline_advance_jobs(
        self,
        gw: AdminGatewayLike,
        *,
        actor: str,
        limit: int = 20,
        promotion_id: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.run_due_baseline_promotion_wave_advance_jobs(
            gw,
            actor=actor,
            limit=limit,
            promotion_id=promotion_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def get_openclaw_alert_governance_baseline_simulation_custody_dashboard(
        self,
        gw: AdminGatewayLike,
        *,
        limit: int = 100,
        only_active: bool = False,
        only_blocked: bool = False,
        only_escalated: bool = False,
        only_suppressed: bool = False,
        only_unowned: bool = False,
        only_claimed: bool = False,
        only_sla_breached: bool = False,
        only_handoff_pending: bool = False,
        only_sla_rerouted: bool = False,
        queue_id: str | None = None,
        team_queue_id: str | None = None,
        owner_id: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.get_runtime_alert_governance_baseline_simulation_custody_dashboard(
            gw,
            limit=limit,
            only_active=only_active,
            only_blocked=only_blocked,
            only_escalated=only_escalated,
            only_suppressed=only_suppressed,
            only_unowned=only_unowned,
            only_claimed=only_claimed,
            only_sla_breached=only_sla_breached,
            only_handoff_pending=only_handoff_pending,
            only_sla_rerouted=only_sla_rerouted,
            queue_id=queue_id,
            team_queue_id=team_queue_id,
            owner_id=owner_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def update_openclaw_alert_governance_baseline_simulation_custody_alert(
        self,
        gw: AdminGatewayLike,
        *,
        promotion_id: str,
        actor: str,
        action: str,
        alert_id: str | None = None,
        reason: str = '',
        mute_for_s: int | None = None,
        owner_id: str | None = None,
        owner_role: str | None = None,
        queue_id: str | None = None,
        queue_label: str | None = None,
        route_id: str | None = None,
        route_label: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.update_runtime_alert_governance_baseline_promotion_simulation_custody_alert(
            gw,
            promotion_id=promotion_id,
            actor=actor,
            action=action,
            alert_id=alert_id,
            reason=reason,
            mute_for_s=mute_for_s,
            owner_id=owner_id,
            owner_role=owner_role,
            queue_id=queue_id,
            queue_label=queue_label,
            route_id=route_id,
            route_label=route_label,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def simulate_openclaw_alert_governance_baseline_promotion(
        self,
        gw: AdminGatewayLike,
        *,
        catalog_id: str,
        actor: str,
        candidate_baselines: dict[str, Any] | None = None,
        version: str | None = None,
        rollout_policy: dict[str, Any] | None = None,
        gate_policy: dict[str, Any] | None = None,
        rollback_policy: dict[str, Any] | None = None,
        reason: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.simulate_runtime_alert_governance_baseline_promotion(
            gw,
            catalog_id=catalog_id,
            actor=actor,
            candidate_baselines=candidate_baselines,
            version=version,
            rollout_policy=rollout_policy,
            gate_policy=gate_policy,
            rollback_policy=rollback_policy,
            reason=reason,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def create_openclaw_alert_governance_baseline_promotion(
        self,
        gw: AdminGatewayLike,
        *,
        catalog_id: str,
        actor: str,
        candidate_baselines: dict[str, Any] | None = None,
        version: str | None = None,
        rollout_policy: dict[str, Any] | None = None,
        gate_policy: dict[str, Any] | None = None,
        rollback_policy: dict[str, Any] | None = None,
        reason: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.create_runtime_alert_governance_baseline_promotion(
            gw,
            catalog_id=catalog_id,
            actor=actor,
            candidate_baselines=candidate_baselines,
            version=version,
            rollout_policy=rollout_policy,
            gate_policy=gate_policy,
            rollback_policy=rollback_policy,
            reason=reason,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

