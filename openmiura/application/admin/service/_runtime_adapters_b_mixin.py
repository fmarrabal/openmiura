"""openmiura.application.admin.service._runtime_adapters_b_mixin

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


class _AdminServiceRuntimeAdaptersBMixin:
    """Mixin: runtime adapters b methods on AdminService."""

    def decide_openclaw_alert_governance_baseline_promotion(
        self,
        gw: AdminGatewayLike,
        *,
        promotion_id: str,
        actor: str,
        decision: str,
        reason: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.decide_runtime_alert_governance_baseline_promotion(
            gw,
            promotion_id=promotion_id,
            actor=actor,
            decision=decision,
            reason=reason,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def validate_openclaw_alert_governance_portfolio_provider_integrations(
        self,
        gw: AdminGatewayLike,
        *,
        portfolio_id: str,
        actor: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.validate_runtime_alert_governance_portfolio_provider_integrations(
            gw,
            portfolio_id=portfolio_id,
            actor=actor,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def attest_openclaw_alert_governance_portfolio_custody_anchor(
        self,
        gw: AdminGatewayLike,
        *,
        portfolio_id: str,
        actor: str,
        package_id: str | None = None,
        control_plane_id: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.attest_runtime_alert_governance_portfolio_custody_anchor(
            gw,
            portfolio_id=portfolio_id,
            actor=actor,
            package_id=package_id,
            control_plane_id=control_plane_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def export_openclaw_alert_governance_portfolio_attestation(
        self,
        gw: AdminGatewayLike,
        *,
        portfolio_id: str,
        actor: str,
        attestation_id: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.export_runtime_alert_governance_portfolio_attestation(
            gw,
            portfolio_id=portfolio_id,
            actor=actor,
            attestation_id=attestation_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def export_openclaw_alert_governance_portfolio_postmortem(
        self,
        gw: AdminGatewayLike,
        *,
        portfolio_id: str,
        actor: str,
        attestation_id: str | None = None,
        timeline_limit: int | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.export_runtime_alert_governance_portfolio_postmortem(
            gw,
            portfolio_id=portfolio_id,
            actor=actor,
            attestation_id=attestation_id,
            timeline_limit=timeline_limit,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def list_openclaw_alert_governance_portfolio_evidence_packages(
        self,
        gw: AdminGatewayLike,
        *,
        portfolio_id: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.list_runtime_alert_governance_portfolio_evidence_packages(
            gw,
            portfolio_id=portfolio_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def export_openclaw_alert_governance_portfolio_evidence_package(
        self,
        gw: AdminGatewayLike,
        *,
        portfolio_id: str,
        actor: str,
        attestation_id: str | None = None,
        timeline_limit: int | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.export_runtime_alert_governance_portfolio_evidence_package(
            gw,
            portfolio_id=portfolio_id,
            actor=actor,
            attestation_id=attestation_id,
            timeline_limit=timeline_limit,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def prune_openclaw_alert_governance_portfolio_evidence_packages(
        self,
        gw: AdminGatewayLike,
        *,
        portfolio_id: str,
        actor: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.prune_runtime_alert_governance_portfolio_evidence_packages(
            gw,
            portfolio_id=portfolio_id,
            actor=actor,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def verify_openclaw_alert_governance_portfolio_evidence_artifact(
        self,
        gw: AdminGatewayLike,
        *,
        portfolio_id: str,
        actor: str,
        package_id: str | None = None,
        artifact: dict[str, Any] | None = None,
        artifact_b64: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.verify_runtime_alert_governance_portfolio_evidence_artifact(
            gw,
            portfolio_id=portfolio_id,
            actor=actor,
            package_id=package_id,
            artifact=artifact,
            artifact_b64=artifact_b64,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def restore_openclaw_alert_governance_portfolio_evidence_artifact(
        self,
        gw: AdminGatewayLike,
        *,
        portfolio_id: str,
        actor: str,
        package_id: str | None = None,
        artifact: dict[str, Any] | None = None,
        artifact_b64: str | None = None,
        persist_restore_session: bool = False,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.restore_runtime_alert_governance_portfolio_evidence_artifact(
            gw,
            portfolio_id=portfolio_id,
            actor=actor,
            package_id=package_id,
            artifact=artifact,
            artifact_b64=artifact_b64,
            persist_restore_session=persist_restore_session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def list_openclaw_alert_governance_portfolio_approvals(
        self,
        gw: AdminGatewayLike,
        *,
        portfolio_id: str | None = None,
        limit: int = 100,
        status: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.list_runtime_alert_governance_portfolio_approvals(
            gw,
            portfolio_id=portfolio_id,
            limit=limit,
            status=status,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def decide_openclaw_alert_governance_portfolio_approval(
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
        return self.openclaw_recovery_scheduler_service.decide_runtime_alert_governance_portfolio_approval(
            gw,
            approval_id=approval_id,
            actor=actor,
            decision=decision,
            reason=reason,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def list_openclaw_release_train_jobs(
        self,
        gw: AdminGatewayLike,
        *,
        limit: int = 100,
        portfolio_id: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.list_release_train_jobs(
            gw,
            limit=limit,
            portfolio_id=portfolio_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def run_due_openclaw_release_train_jobs(
        self,
        gw: AdminGatewayLike,
        *,
        actor: str,
        limit: int = 20,
        portfolio_id: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.run_due_release_train_jobs(
            gw,
            actor=actor,
            limit=limit,
            portfolio_id=portfolio_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def list_openclaw_alert_governance_advance_jobs(
        self,
        gw: AdminGatewayLike,
        *,
        limit: int = 100,
        bundle_id: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.list_governance_wave_advance_jobs(
            gw,
            limit=limit,
            bundle_id=bundle_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def run_due_openclaw_alert_governance_advance_jobs(
        self,
        gw: AdminGatewayLike,
        *,
        actor: str,
        limit: int = 20,
        bundle_id: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.run_due_governance_wave_advance_jobs(
            gw,
            actor=actor,
            limit=limit,
            bundle_id=bundle_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def get_openclaw_alert_governance(
        self,
        gw: AdminGatewayLike,
        *,
        runtime_id: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.get_runtime_alert_governance(
            gw,
            runtime_id=runtime_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            limit=limit,
        )

    def list_openclaw_alert_governance_promotion_approvals(
        self,
        gw: AdminGatewayLike,
        *,
        runtime_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.list_runtime_alert_governance_promotion_approvals(
            gw,
            runtime_id=runtime_id,
            status=status,
            limit=limit,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def decide_openclaw_alert_governance_promotion_approval(
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
        return self.openclaw_recovery_scheduler_service.decide_runtime_alert_governance_promotion_approval(
            gw,
            approval_id=approval_id,
            actor=actor,
            decision=decision,
            reason=reason,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def simulate_openclaw_alert_governance(
        self,
        gw: AdminGatewayLike,
        *,
        runtime_id: str,
        candidate_policy: dict[str, Any] | None = None,
        merge_with_current: bool = True,
        alert_code: str | None = None,
        include_unchanged: bool = True,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        limit: int = 200,
        now_ts: float | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.simulate_runtime_alert_governance(
            gw,
            runtime_id=runtime_id,
            candidate_policy=candidate_policy,
            merge_with_current=merge_with_current,
            alert_code=alert_code,
            include_unchanged=include_unchanged,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            limit=limit,
            now_ts=now_ts,
        )

    def list_openclaw_alert_governance_versions(
        self,
        gw: AdminGatewayLike,
        *,
        runtime_id: str,
        limit: int = 50,
        status: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.list_runtime_alert_governance_versions(
            gw,
            runtime_id=runtime_id,
            limit=limit,
            status=status,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def activate_openclaw_alert_governance(
        self,
        gw: AdminGatewayLike,
        *,
        runtime_id: str,
        actor: str,
        candidate_policy: dict[str, Any] | None = None,
        merge_with_current: bool = True,
        reason: str = '',
        alert_code: str | None = None,
        include_unchanged: bool = True,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        limit: int = 200,
        now_ts: float | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.activate_runtime_alert_governance(
            gw,
            runtime_id=runtime_id,
            actor=actor,
            candidate_policy=candidate_policy,
            merge_with_current=merge_with_current,
            reason=reason,
            alert_code=alert_code,
            include_unchanged=include_unchanged,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            limit=limit,
            now_ts=now_ts,
        )

    def rollback_openclaw_alert_governance_version(
        self,
        gw: AdminGatewayLike,
        *,
        runtime_id: str,
        version_id: str,
        actor: str,
        reason: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.rollback_runtime_alert_governance_version(
            gw,
            runtime_id=runtime_id,
            version_id=version_id,
            actor=actor,
            reason=reason,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def list_openclaw_alert_delivery_jobs(
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
        return self.openclaw_recovery_scheduler_service.list_alert_delivery_jobs(
            gw,
            limit=limit,
            enabled=enabled,
            runtime_id=runtime_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def dispatch_openclaw_runtime_alert_notifications(
        self,
        gw: AdminGatewayLike,
        *,
        runtime_id: str,
        alert_code: str,
        actor: str,
        workflow_action: str = 'escalate',
        target_id: str = '',
        reason: str = '',
        level: int | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.dispatch_runtime_alert_notifications(
            gw,
            runtime_id=runtime_id,
            alert_code=alert_code,
            actor=actor,
            workflow_action=workflow_action,
            target_id=target_id,
            reason=reason,
            escalation_level=level,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def ack_openclaw_runtime_alert(
        self,
        gw: AdminGatewayLike,
        *,
        runtime_id: str,
        alert_code: str,
        actor: str,
        note: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.ack_runtime_alert(
            gw,
            runtime_id=runtime_id,
            alert_code=alert_code,
            actor=actor,
            note=note,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def silence_openclaw_runtime_alert(
        self,
        gw: AdminGatewayLike,
        *,
        runtime_id: str,
        alert_code: str,
        actor: str,
        silence_for_s: int | None = None,
        reason: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.silence_runtime_alert(
            gw,
            runtime_id=runtime_id,
            alert_code=alert_code,
            actor=actor,
            silence_for_s=silence_for_s,
            reason=reason,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def escalate_openclaw_runtime_alert(
        self,
        gw: AdminGatewayLike,
        *,
        runtime_id: str,
        alert_code: str,
        actor: str,
        target: str = '',
        reason: str = '',
        level: int | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.escalate_runtime_alert(
            gw,
            runtime_id=runtime_id,
            alert_code=alert_code,
            actor=actor,
            target=target,
            reason=reason,
            level=level,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def decide_openclaw_alert_escalation_approval(
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
        return self.openclaw_recovery_scheduler_service.decide_alert_escalation_approval(
            gw,
            approval_id=approval_id,
            actor=actor,
            decision=decision,
            reason=reason,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def run_due_openclaw_recovery_jobs(
        self,
        gw: AdminGatewayLike,
        *,
        actor: str,
        limit: int = 20,
        runtime_id: str | None = None,
        user_role: str = 'operator',
        user_key: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.run_due_recovery_jobs(
            gw,
            actor=actor,
            limit=limit,
            runtime_id=runtime_id,
            user_role=user_role,
            user_key=user_key,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def run_due_openclaw_alert_delivery_jobs(
        self,
        gw: AdminGatewayLike,
        *,
        actor: str,
        limit: int = 20,
        runtime_id: str | None = None,
        user_key: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_recovery_scheduler_service.run_due_alert_delivery_jobs(
            gw,
            actor=actor,
            limit=limit,
            runtime_id=runtime_id,
            user_key=user_key,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def list_openclaw_runtimes(
        self,
        gw: AdminGatewayLike,
        *,
        limit: int = 100,
        status: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_adapter_service.list_runtimes(
            gw,
            limit=limit,
            status=status,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def register_openclaw_runtime(
        self,
        gw: AdminGatewayLike,
        *,
        actor: str,
        name: str,
        base_url: str,
        transport: str = 'http',
        auth_secret_ref: str = '',
        capabilities: list[str] | None = None,
        allowed_agents: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        runtime_id: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_adapter_service.register_runtime(
            gw,
            actor=actor,
            name=name,
            base_url=base_url,
            transport=transport,
            auth_secret_ref=auth_secret_ref,
            capabilities=capabilities,
            allowed_agents=allowed_agents,
            metadata=metadata,
            runtime_id=runtime_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def get_openclaw_runtime(
        self,
        gw: AdminGatewayLike,
        *,
        runtime_id: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_adapter_service.get_runtime(
            gw,
            runtime_id=runtime_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def list_openclaw_dispatches(
        self,
        gw: AdminGatewayLike,
        *,
        runtime_id: str | None = None,
        action: str | None = None,
        status: str | None = None,
        limit: int = 100,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_adapter_service.list_dispatches(
            gw,
            runtime_id=runtime_id,
            action=action,
            status=status,
            limit=limit,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def get_openclaw_dispatch(
        self,
        gw: AdminGatewayLike,
        *,
        dispatch_id: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_adapter_service.get_dispatch(
            gw,
            dispatch_id=dispatch_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def get_openclaw_runtime_timeline(
        self,
        gw: AdminGatewayLike,
        *,
        runtime_id: str,
        limit: int = 50,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_adapter_service.get_runtime_timeline(
            gw,
            runtime_id=runtime_id,
            limit=limit,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def check_openclaw_runtime_health(
        self,
        gw: AdminGatewayLike,
        *,
        runtime_id: str,
        actor: str,
        probe: str = 'ready',
        user_role: str = 'operator',
        user_key: str = '',
        session_id: str = 'system',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_adapter_service.check_runtime_health(
            gw,
            runtime_id=runtime_id,
            actor=actor,
            probe=probe,
            user_role=user_role,
            user_key=user_key,
            session_id=session_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def dispatch_openclaw_runtime(
        self,
        gw: AdminGatewayLike,
        *,
        runtime_id: str,
        actor: str,
        action: str,
        payload: dict[str, Any] | None = None,
        agent_id: str = '',
        user_role: str = 'operator',
        user_key: str = '',
        session_id: str = 'system',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        return self.openclaw_adapter_service.dispatch(
            gw,
            runtime_id=runtime_id,
            actor=actor,
            action=action,
            payload=payload,
            agent_id=agent_id,
            user_role=user_role,
            user_key=user_key,
            session_id=session_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            dry_run=dry_run,
        )

    def ingest_openclaw_runtime_event(
        self,
        gw: AdminGatewayLike,
        *,
        runtime_id: str,
        actor: str = 'openclaw',
        source: str = 'openclaw',
        event_type: str,
        event_status: str = '',
        source_event_id: str = '',
        dispatch_id: str = '',
        session_id: str = '',
        user_key: str = '',
        message: str = '',
        payload: dict[str, Any] | None = None,
        observed_at: float | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        auth_mode: str = 'admin',
        event_token: str = '',
        require_token: bool = False,
    ) -> dict[str, Any]:
        return self.openclaw_adapter_service.ingest_runtime_event(
            gw,
            runtime_id=runtime_id,
            actor=actor,
            source=source,
            event_type=event_type,
            event_status=event_status,
            source_event_id=source_event_id,
            dispatch_id=dispatch_id,
            session_id=session_id,
            user_key=user_key,
            message=message,
            payload=payload,
            observed_at=observed_at,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            auth_mode=auth_mode,
            event_token=event_token,
            require_token=require_token,
        )

    def cancel_openclaw_dispatch(
        self,
        gw: AdminGatewayLike,
        *,
        dispatch_id: str,
        actor: str,
        reason: str = '',
        user_role: str = 'operator',
        user_key: str = '',
        session_id: str = 'system',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_adapter_service.cancel_dispatch(
            gw,
            dispatch_id=dispatch_id,
            actor=actor,
            reason=reason,
            user_role=user_role,
            user_key=user_key,
            session_id=session_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def retry_openclaw_dispatch(
        self,
        gw: AdminGatewayLike,
        *,
        dispatch_id: str,
        actor: str,
        reason: str = '',
        payload_override: dict[str, Any] | None = None,
        action_override: str = '',
        agent_id_override: str = '',
        user_role: str = 'operator',
        user_key: str = '',
        session_id: str = 'system',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_adapter_service.retry_dispatch(
            gw,
            dispatch_id=dispatch_id,
            actor=actor,
            reason=reason,
            payload_override=payload_override,
            action_override=action_override,
            agent_id_override=agent_id_override,
            user_role=user_role,
            user_key=user_key,
            session_id=session_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def reconcile_openclaw_dispatch(
        self,
        gw: AdminGatewayLike,
        *,
        dispatch_id: str,
        actor: str,
        target_status: str,
        reason: str = '',
        user_role: str = 'operator',
        user_key: str = '',
        session_id: str = 'system',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_adapter_service.reconcile_dispatch(
            gw,
            dispatch_id=dispatch_id,
            actor=actor,
            target_status=target_status,
            reason=reason,
            user_role=user_role,
            user_key=user_key,
            session_id=session_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def poll_openclaw_dispatch(
        self,
        gw: AdminGatewayLike,
        *,
        dispatch_id: str,
        actor: str,
        reason: str = '',
        user_role: str = 'operator',
        user_key: str = '',
        session_id: str = 'system',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_adapter_service.poll_dispatch(
            gw,
            dispatch_id=dispatch_id,
            actor=actor,
            reason=reason,
            user_role=user_role,
            user_key=user_key,
            session_id=session_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def recover_openclaw_runtime(
        self,
        gw: AdminGatewayLike,
        *,
        runtime_id: str,
        actor: str,
        reason: str = '',
        limit: int = 50,
        user_role: str = 'operator',
        user_key: str = '',
        session_id: str = 'system',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_adapter_service.recover_stale_dispatches(
            gw,
            runtime_id=runtime_id,
            actor=actor,
            reason=reason,
            limit=limit,
            user_role=user_role,
            user_key=user_key,
            session_id=session_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def run_openclaw_runtime_conformance(
        self,
        gw: AdminGatewayLike,
        *,
        runtime_id: str,
        actor: str = 'admin',
        user_role: str = 'operator',
        user_key: str = '',
        session_id: str = 'system',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.openclaw_adapter_service.run_conformance_check(
            gw,
            runtime_id=runtime_id,
            actor=actor,
            user_role=user_role,
            user_key=user_key,
            session_id=session_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

