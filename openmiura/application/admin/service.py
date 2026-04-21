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

from openmiura.application.costs import CostGovernanceService
from openmiura.application.evaluations import EvaluationService
from openmiura.application.memory import MemoryService
from openmiura.application.openclaw import OpenClawAdapterService, OpenClawRecoverySchedulerService
from openmiura.application.operator import OperatorConsoleService
from openmiura.application.replay import ReplayService
from openmiura.application.releases import ReleaseService
from openmiura.application.sessions import SessionService
from openmiura.application.secrets import SecretGovernanceService
from openmiura.application.tenancy import TenancyService
from openmiura.application.voice import VoiceRuntimeService
from openmiura.application.pwa import PWAFoundationService
from openmiura.application.canvas import LiveCanvasService
from openmiura.application.packaging import PackagingHardeningService
from openmiura.application.admin.status_snapshot import build_status_snapshot, collect_registered_tool_names
from openmiura import __version__
from openmiura.core.config import resolve_config_related_path
from openmiura.core.contracts import AdminGatewayLike
from openmiura.core.policies.engine import PolicyEngine


class AdminService:
    def __init__(
        self,
        *,
        memory_service: MemoryService | None = None,
        session_service: SessionService | None = None,
        evaluation_service: EvaluationService | None = None,
        cost_governance_service: CostGovernanceService | None = None,
    ) -> None:
        self.memory_service = memory_service or MemoryService()
        self.session_service = session_service or SessionService()
        self.evaluation_service = evaluation_service or EvaluationService()
        self.cost_governance_service = cost_governance_service or CostGovernanceService()
        self.tenancy_service = TenancyService()
        self.replay_service = ReplayService()
        self.operator_console_service = OperatorConsoleService(replay_service=self.replay_service)
        self.secret_governance_service = SecretGovernanceService()
        self.release_service = ReleaseService()
        self.voice_runtime_service = VoiceRuntimeService()
        self.pwa_foundation_service = PWAFoundationService()
        self.openclaw_adapter_service = OpenClawAdapterService()
        self.openclaw_recovery_scheduler_service = OpenClawRecoverySchedulerService(openclaw_adapter_service=self.openclaw_adapter_service)
        self.live_canvas_service = LiveCanvasService(
            cost_governance_service=self.cost_governance_service,
            operator_console_service=self.operator_console_service,
            secret_governance_service=self.secret_governance_service,
            openclaw_adapter_service=self.openclaw_adapter_service,
            openclaw_recovery_scheduler_service=self.openclaw_recovery_scheduler_service,
        )
        self.packaging_hardening_service = PackagingHardeningService()

    def status_snapshot(self, gw: AdminGatewayLike) -> dict[str, Any]:
        tool_names = collect_registered_tool_names(getattr(gw, "tools", None))
        return build_status_snapshot(
            gw,
            safe_call=self._safe_call,
            tenancy_catalog=self.tenancy_service.catalog(getattr(gw, "settings", None)),
            tool_names=tool_names,
        )

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

    def list_sessions(
        self,
        gw: AdminGatewayLike,
        *,
        limit: int,
        channel: str | None,
    ) -> dict[str, Any]:
        return self.session_service.list_sessions(gw, limit=limit, channel=channel)

    def list_events(
        self,
        gw: AdminGatewayLike,
        *,
        limit: int,
        channel: str | None,
    ) -> dict[str, Any]:
        items = self._safe_call(gw.audit, "get_recent_events", [], limit=limit, channel=channel)
        return {"ok": True, "items": items}


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

    def cost_summary(
        self,
        gw: AdminGatewayLike,
        *,
        group_by: str = "tenant",
        limit: int = 20,
        window_hours: int | None = None,
        workflow_name: str | None = None,
        agent_name: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.cost_governance_service.summary(
            gw,
            group_by=group_by,
            limit=limit,
            window_hours=window_hours,
            workflow_name=workflow_name,
            agent_name=agent_name,
            provider=provider,
            model=model,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def cost_budgets(
        self,
        gw: AdminGatewayLike,
        *,
        limit: int = 50,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.cost_governance_service.budgets(
            gw,
            limit=limit,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def cost_alerts(
        self,
        gw: AdminGatewayLike,
        *,
        severity: str = "all",
        limit: int = 50,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.cost_governance_service.alerts(
            gw,
            severity=severity,
            limit=limit,
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

    def list_decision_traces(
        self,
        gw: AdminGatewayLike,
        *,
        limit: int = 50,
        session_id: str | None = None,
        user_key: str | None = None,
        agent_id: str | None = None,
        channel: str | None = None,
        status: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        items = self._safe_call(
            gw.audit,
            "list_decision_traces",
            [],
            limit=limit,
            session_id=session_id,
            user_key=user_key,
            agent_id=agent_id,
            channel=channel,
            status=status,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        return {"ok": True, "items": items}

    def get_decision_trace(self, gw: AdminGatewayLike, *, trace_id: str) -> dict[str, Any]:
        item = self._safe_call(gw.audit, "get_decision_trace", None, trace_id)
        if item is None:
            return {"ok": False, "reason": "trace_not_found", "trace_id": trace_id}
        summary = {
            "trace_id": item.get("trace_id"),
            "session_id": item.get("session_id"),
            "agent_id": item.get("agent_id"),
            "status": item.get("status"),
            "provider": item.get("provider"),
            "model": item.get("model"),
            "latency_ms": item.get("latency_ms"),
            "estimated_cost": item.get("estimated_cost"),
            "memory_hits": len(list((item.get("memory") or {}).get("items") or [])),
            "tools_considered": len(list(item.get("tools_considered") or [])),
            "tools_used": len(list(item.get("tools_used") or [])),
            "policies": len(list(item.get("policies") or [])),
        }
        return {"ok": True, "trace": item, "summary": summary}

    def session_inspector(
        self,
        gw: AdminGatewayLike,
        *,
        session_id: str,
        limit: int = 20,
    ) -> dict[str, Any]:
        sessions = self._safe_call(gw.audit, "list_sessions", [], limit=max(limit, 200))
        session = next((item for item in sessions if item.get("session_id") == session_id), None)
        messages = self._safe_call(gw.audit, "get_session_messages", [], session_id, limit=200)
        traces = self._safe_call(gw.audit, "list_decision_traces", [], limit=limit, session_id=session_id)
        return {
            "ok": True,
            "session": session,
            "messages": messages,
            "traces": traces,
            "summary": {
                "session_id": session_id,
                "message_count": len(messages),
                "trace_count": len(traces),
                "tools_used": sum(len(list(item.get("tools_used") or [])) for item in traces),
                "memory_hits": sum(len(list((item.get("memory") or {}).get("items") or [])) for item in traces),
            },
        }

    def session_replay(
        self,
        gw: AdminGatewayLike,
        *,
        session_id: str,
        limit: int = 200,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.replay_service.session_replay(
            gw,
            session_id=session_id,
            limit=limit,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def workflow_replay(
        self,
        gw: AdminGatewayLike,
        *,
        workflow_id: str,
        limit: int = 200,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.replay_service.workflow_replay(
            gw,
            workflow_id=workflow_id,
            limit=limit,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def replay_compare(
        self,
        gw: AdminGatewayLike,
        *,
        left_kind: str,
        left_id: str,
        right_kind: str,
        right_id: str,
        limit: int = 200,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.replay_service.compare_replays(
            gw,
            left_kind=left_kind,
            left_id=left_id,
            right_kind=right_kind,
            right_id=right_id,
            limit=limit,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def operator_console_overview(
        self,
        gw: AdminGatewayLike,
        *,
        limit: int = 20,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        q: str | None = None,
        status: str | None = None,
        kind: str | None = None,
        only_failures: bool = False,
    ) -> dict[str, Any]:
        return self.operator_console_service.overview(
            gw,
            limit=limit,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            q=q,
            status=status,
            kind=kind,
            only_failures=only_failures,
        )

    def operator_console_session(
        self,
        gw: AdminGatewayLike,
        *,
        session_id: str,
        limit: int = 200,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        q: str | None = None,
        status: str | None = None,
        kind: str | None = None,
        only_failures: bool = False,
    ) -> dict[str, Any]:
        return self.operator_console_service.session_console(
            gw,
            session_id=session_id,
            limit=limit,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            q=q,
            status=status,
            kind=kind,
            only_failures=only_failures,
        )

    def operator_console_workflow(
        self,
        gw: AdminGatewayLike,
        *,
        workflow_id: str,
        limit: int = 200,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        q: str | None = None,
        status: str | None = None,
        kind: str | None = None,
        only_failures: bool = False,
    ) -> dict[str, Any]:
        return self.operator_console_service.workflow_console(
            gw,
            workflow_id=workflow_id,
            limit=limit,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            q=q,
            status=status,
            kind=kind,
            only_failures=only_failures,
        )

    def operator_console_workflow_action(
        self,
        gw: AdminGatewayLike,
        *,
        workflow_id: str,
        action: str,
        actor: str,
        reason: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.operator_console_service.workflow_action(
            gw,
            workflow_id=workflow_id,
            action=action,
            actor=actor,
            reason=reason,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def operator_console_approval_action(
        self,
        gw: AdminGatewayLike,
        *,
        approval_id: str,
        action: str,
        actor: str,
        reason: str = '',
        auth_ctx: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.operator_console_service.approval_action(
            gw,
            approval_id=approval_id,
            action=action,
            actor=actor,
            reason=reason,
            auth_ctx=auth_ctx,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def secret_governance_catalog(
        self,
        gw: AdminGatewayLike,
        *,
        q: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        return self.secret_governance_service.catalog(
            gw,
            q=q,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            limit=limit,
        )

    def secret_governance_usage(
        self,
        gw: AdminGatewayLike,
        *,
        q: str | None = None,
        ref: str | None = None,
        tool_name: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        return self.secret_governance_service.usage(
            gw,
            q=q,
            ref=ref,
            tool_name=tool_name,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            limit=limit,
        )

    def secret_governance_summary(
        self,
        gw: AdminGatewayLike,
        *,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        return self.secret_governance_service.summary(
            gw,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            limit=limit,
        )

    def secret_governance_timeline(
        self,
        gw: AdminGatewayLike,
        *,
        q: str | None = None,
        ref: str | None = None,
        tool_name: str | None = None,
        outcome: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        return self.secret_governance_service.timeline(
            gw,
            q=q,
            ref=ref,
            tool_name=tool_name,
            outcome=outcome,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            limit=limit,
        )

    def secret_governance_explain(
        self,
        gw: AdminGatewayLike,
        *,
        ref: str,
        tool_name: str,
        user_role: str = 'user',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        domain: str | None = None,
    ) -> dict[str, Any]:
        return self.secret_governance_service.explain_access(
            gw,
            ref=ref,
            tool_name=tool_name,
            user_role=user_role,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            domain=domain,
        )

    def explain_policy(
        self,
        gw: AdminGatewayLike,
        *,
        scope: str,
        resource_name: str,
        action: str = "use",
        agent_name: str | None = None,
        user_role: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        channel: str | None = None,
        domain: str | None = None,
        extra: dict[str, Any] | None = None,
        tool_name: str | None = None,
    outcome: str | None = None,
    ) -> dict[str, Any]:
        policy = getattr(gw, "policy", None)
        if policy is None or not hasattr(policy, "explain_request"):
            return {"ok": False, "reason": "policy_not_configured"}
        return policy.explain_request(
            scope=scope,
            resource_name=resource_name,
            action=action,
            agent_name=agent_name,
            user_role=user_role,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            channel=channel,
            domain=domain,
            extra=extra,
            tool_name=tool_name,
        )

    def explain_sandbox(
        self,
        gw: AdminGatewayLike,
        *,
        user_role: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        channel: str | None = None,
        agent_name: str | None = None,
        tool_name: str | None = None,
    ) -> dict[str, Any]:
        sandbox = getattr(gw, "sandbox", None)
        if sandbox is None or not hasattr(sandbox, "explain"):
            return {"ok": False, "reason": "sandbox_not_configured"}
        return sandbox.explain(
            user_role=user_role,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            channel=channel,
            agent_name=agent_name,
            tool_name=tool_name,
        )

    def explain_security(
        self,
        gw: AdminGatewayLike,
        *,
        scope: str,
        resource_name: str,
        action: str = "use",
        agent_name: str | None = None,
        user_role: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        channel: str | None = None,
        domain: str | None = None,
        extra: dict[str, Any] | None = None,
        tool_name: str | None = None,
    ) -> dict[str, Any]:
        normalized_scope = str(scope or "").strip().lower()
        policy_payload = self.explain_policy(
            gw,
            scope=normalized_scope,
            resource_name=resource_name,
            action=action,
            agent_name=agent_name,
            user_role=user_role,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            channel=channel,
            domain=domain,
            extra=extra,
            tool_name=tool_name,
        )
        policy_decision = dict(policy_payload.get("decision") or {}) if policy_payload.get("ok") else {}
        sandbox_payload: dict[str, Any] | None = None
        secret_payload: dict[str, Any] | None = None
        allowed = bool(policy_decision.get("allowed", True)) if policy_decision else True
        requires_confirmation = bool(policy_decision.get("requires_confirmation", False))
        requires_approval = bool(policy_decision.get("requires_approval", False))
        reasons: list[str] = []

        if policy_decision.get("reason"):
            reasons.append(str(policy_decision.get("reason")))

        effective_tool_name = str(tool_name or (extra or {}).get("tool_name") or agent_name or "").strip() or None

        if normalized_scope == "tool":
            sandbox_payload = self.explain_sandbox(
                gw,
                user_role=user_role,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                environment=environment,
                channel=channel,
                agent_name=agent_name,
                tool_name=resource_name,
            )
            if sandbox_payload.get("ok"):
                tool_allowed = bool(sandbox_payload.get("tool_allowed", True))
                if not tool_allowed:
                    allowed = False
                    reasons.append(
                        f"sandbox profile '{sandbox_payload.get('profile_name', 'unknown')}' denies tool '{resource_name}'"
                    )
        elif normalized_scope == "secret":
            broker = getattr(gw, "secret_broker", None)
            if broker is None or not hasattr(broker, "explain_access"):
                secret_payload = {"ok": False, "reason": "secret_broker_not_configured"}
            else:
                secret_payload = broker.explain_access(
                    resource_name,
                    tool_name=effective_tool_name or "",
                    user_role=user_role or "user",
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    environment=environment,
                    domain=domain,
                )
                if not bool(secret_payload.get("allowed", False)):
                    allowed = False
                    if secret_payload.get("reason"):
                        reasons.append(str(secret_payload.get("reason")))

        final_state = "allowed"
        if not allowed:
            final_state = "denied"
        elif requires_approval:
            final_state = "approval_required"
        elif requires_confirmation:
            final_state = "confirmation_required"

        concise_reason = reasons[0] if reasons else (policy_decision.get("reason") or "security policy evaluated")
        user_message = self._user_security_message(
            scope=normalized_scope,
            resource_name=resource_name,
            final_state=final_state,
            concise_reason=concise_reason,
        )
        admin_message = self._admin_security_message(
            scope=normalized_scope,
            resource_name=resource_name,
            final_state=final_state,
            concise_reason=concise_reason,
            policy_decision=policy_decision,
            sandbox_payload=sandbox_payload,
            secret_payload=secret_payload,
        )
        return {
            "ok": True,
            "scope": normalized_scope,
            "resource_name": resource_name,
            "action": action,
            "final_state": final_state,
            "allowed": allowed,
            "requires_confirmation": requires_confirmation,
            "requires_approval": requires_approval,
            "user_explanation": {
                "message": user_message,
                "reason": concise_reason,
            },
            "admin_explanation": {
                "message": admin_message,
                "reasons": reasons or [concise_reason],
                "policy_rules": list(policy_decision.get("matched_rules") or []),
                "sandbox_profile": sandbox_payload.get("profile_name") if isinstance(sandbox_payload, dict) else None,
                "secret_ref": secret_payload.get("ref") if isinstance(secret_payload, dict) else None,
            },
            "components": {
                "policy": policy_payload,
                "sandbox": sandbox_payload,
                "secret": secret_payload,
            },
            "audit_hints": {
                "channels": [item for item in ["security", "sandbox", "admin", channel] if item],
                "event_names": ["secret_resolved", "sandbox_tool_denied", "reload", "admin_reload", "policy_explain", "sandbox_explain", "security_explain"],
            },
        }

    def policy_explorer_snapshot(self, gw: AdminGatewayLike) -> dict[str, Any]:
        policy = getattr(gw, "policy", None)
        if policy is None:
            return {"ok": False, "reason": "policy_not_configured"}
        snapshot = copy.deepcopy(self._safe_call(policy, "snapshot", {}) or {})
        sections: dict[str, Any] = {}
        for key, value in snapshot.items():
            if isinstance(value, list):
                sections[key] = {"count": len(value), "rule_names": [str((item or {}).get("name") or f"{key}[{idx + 1}]") for idx, item in enumerate(value)]}
            elif isinstance(value, dict):
                sections[key] = {"count": len(value), "keys": sorted(list(value.keys()))}
            else:
                sections[key] = {"count": 0}
        return {
            "ok": True,
            "signature": self._safe_call(policy, "signature", None),
            "policy": snapshot,
            "sections": sections,
            "supported_scopes": ["tool", "memory", "secret", "channel", "approval"],
            "supported_sections": list(snapshot.keys()),
            "sample_requests": [
                {"scope": "tool", "resource_name": "web_fetch", "action": "use", "agent_name": "researcher", "user_role": "user"},
                {"scope": "secret", "resource_name": "github_pat", "action": "resolve", "tool_name": "web_fetch", "user_role": "admin"},
                {"scope": "approval", "resource_name": "fs_write", "action": "require", "user_role": "operator"},
            ],
        }

    def policy_explorer_simulate(
        self,
        gw: AdminGatewayLike,
        *,
        scope: str,
        resource_name: str,
        action: str = "use",
        agent_name: str | None = None,
        tool_name: str | None = None,
        user_role: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        channel: str | None = None,
        domain: str | None = None,
        extra: dict[str, Any] | None = None,
        candidate_policy: dict[str, Any] | None = None,
        candidate_policy_yaml: str | None = None,
    ) -> dict[str, Any]:
        current = self.explain_policy(
            gw,
            scope=scope,
            resource_name=resource_name,
            action=action,
            agent_name=agent_name,
            tool_name=tool_name,
            user_role=user_role,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            channel=channel,
            domain=domain,
            extra=extra,
        )
        candidate_engine = self._policy_engine_from_payload(
            current_policy=getattr(gw, "policy", None),
            explicit_policy=candidate_policy,
            explicit_policy_yaml=candidate_policy_yaml,
        )
        candidate_payload = None
        changed = False
        if candidate_engine is not None:
            candidate_payload = candidate_engine.explain_request(
                scope=scope,
                resource_name=resource_name,
                action=action,
                agent_name=agent_name,
                user_role=user_role,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                environment=environment,
                channel=channel,
                domain=domain,
                extra=extra,
                tool_name=tool_name,
            )
            changed = dict(current.get("decision") or {}) != dict(candidate_payload.get("decision") or {})
        return {
            "ok": True,
            "request": {
                "scope": scope,
                "resource_name": resource_name,
                "action": action,
                "agent_name": agent_name,
                "tool_name": tool_name,
                "user_role": user_role,
                "tenant_id": tenant_id,
                "workspace_id": workspace_id,
                "environment": environment,
                "channel": channel,
                "domain": domain,
                "extra": dict(extra or {}),
            },
            "baseline": current,
            "candidate": candidate_payload,
            "changed": changed,
            "change_summary": self._compare_policy_decisions(
                dict(current.get("decision") or {}),
                dict((candidate_payload or {}).get("decision") or {}),
            ) if candidate_payload is not None else None,
        }

    def policy_explorer_diff(
        self,
        gw: AdminGatewayLike,
        *,
        candidate_policy: dict[str, Any] | None = None,
        candidate_policy_yaml: str | None = None,
        baseline_policy: dict[str, Any] | None = None,
        baseline_policy_yaml: str | None = None,
        samples: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        current_policy = getattr(gw, "policy", None)
        baseline_engine = self._policy_engine_from_payload(
            current_policy=current_policy,
            explicit_policy=baseline_policy,
            explicit_policy_yaml=baseline_policy_yaml,
            allow_current_fallback=True,
        )
        candidate_engine = self._policy_engine_from_payload(
            current_policy=current_policy,
            explicit_policy=candidate_policy,
            explicit_policy_yaml=candidate_policy_yaml,
            allow_current_fallback=False,
        )
        if baseline_engine is None:
            return {"ok": False, "reason": "baseline_policy_unavailable"}
        if candidate_engine is None:
            return {"ok": False, "reason": "candidate_policy_missing"}

        baseline_snapshot = baseline_engine.snapshot()
        candidate_snapshot = candidate_engine.snapshot()
        diff = self._diff_policy_documents(baseline_snapshot, candidate_snapshot)
        sample_results: list[dict[str, Any]] = []
        for raw in list(samples or [])[:50]:
            request_payload = self._normalize_policy_request(raw)
            baseline_decision = baseline_engine.explain_request(**request_payload)
            candidate_decision = candidate_engine.explain_request(**request_payload)
            sample_results.append(
                {
                    "request": request_payload,
                    "baseline": baseline_decision,
                    "candidate": candidate_decision,
                    "changed": dict(baseline_decision.get("decision") or {}) != dict(candidate_decision.get("decision") or {}),
                    "change_summary": self._compare_policy_decisions(
                        dict(baseline_decision.get("decision") or {}),
                        dict(candidate_decision.get("decision") or {}),
                    ),
                }
            )
        return {
            "ok": True,
            "baseline_signature": PolicyEngine.data_signature(baseline_snapshot),
            "candidate_signature": PolicyEngine.data_signature(candidate_snapshot),
            "baseline": {"sections": self._policy_section_summary(baseline_snapshot)},
            "candidate": {"sections": self._policy_section_summary(candidate_snapshot)},
            "diff": diff,
            "sample_results": sample_results,
        }

    def _policy_engine_from_payload(
        self,
        *,
        current_policy: Any | None,
        explicit_policy: dict[str, Any] | None = None,
        explicit_policy_yaml: str | None = None,
        allow_current_fallback: bool = True,
    ) -> PolicyEngine | None:
        payload = None
        if explicit_policy_yaml and str(explicit_policy_yaml).strip():
            payload = yaml.safe_load(str(explicit_policy_yaml)) or {}
        elif explicit_policy:
            payload = explicit_policy
        elif allow_current_fallback and current_policy is not None and hasattr(current_policy, "snapshot"):
            payload = current_policy.snapshot()
        if payload is None:
            return None
        return PolicyEngine.from_mapping(payload)

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

    def _policy_section_summary(self, policy: dict[str, Any]) -> dict[str, Any]:
        summary: dict[str, Any] = {}
        for key, value in dict(policy or {}).items():
            if isinstance(value, list):
                summary[key] = len(value)
            elif isinstance(value, dict):
                summary[key] = len(value.keys())
            else:
                summary[key] = 0
        return summary

    def _rule_identity(self, section: str, rule: Any, idx: int) -> str:
        if isinstance(rule, dict) and str(rule.get("name") or "").strip():
            return f"{section}:{str(rule.get('name')).strip()}"
        payload = json.dumps(rule, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
        return f"{section}:{idx}:{digest}"

    def _diff_policy_documents(self, baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
        section_names = sorted(set(dict(baseline or {}).keys()) | set(dict(candidate or {}).keys()))
        sections: dict[str, Any] = {}
        added_total = removed_total = changed_total = 0
        for section in section_names:
            base_value = (baseline or {}).get(section, [] if section != "defaults" else {})
            cand_value = (candidate or {}).get(section, [] if section != "defaults" else {})
            if isinstance(base_value, dict) or isinstance(cand_value, dict):
                base_dict = dict(base_value or {})
                cand_dict = dict(cand_value or {})
                added_keys = sorted([key for key in cand_dict.keys() if key not in base_dict])
                removed_keys = sorted([key for key in base_dict.keys() if key not in cand_dict])
                changed_keys = sorted([key for key in set(base_dict.keys()) & set(cand_dict.keys()) if base_dict.get(key) != cand_dict.get(key)])
                sections[section] = {
                    "type": "mapping",
                    "added": [{"key": key, "value": cand_dict.get(key)} for key in added_keys],
                    "removed": [{"key": key, "value": base_dict.get(key)} for key in removed_keys],
                    "changed": [{"key": key, "before": base_dict.get(key), "after": cand_dict.get(key)} for key in changed_keys],
                }
                added_total += len(added_keys)
                removed_total += len(removed_keys)
                changed_total += len(changed_keys)
                continue
            base_items = list(base_value or [])
            cand_items = list(cand_value or [])
            base_index = {self._rule_identity(section, item, idx): item for idx, item in enumerate(base_items)}
            cand_index = {self._rule_identity(section, item, idx): item for idx, item in enumerate(cand_items)}
            shared = sorted(set(base_index.keys()) & set(cand_index.keys()))
            changed = []
            for key in shared:
                if base_index[key] != cand_index[key]:
                    changed.append({"id": key, "before": base_index[key], "after": cand_index[key]})
            added = [{"id": key, "rule": cand_index[key]} for key in sorted(set(cand_index.keys()) - set(base_index.keys()))]
            removed = [{"id": key, "rule": base_index[key]} for key in sorted(set(base_index.keys()) - set(cand_index.keys()))]
            sections[section] = {"type": "rules", "added": added, "removed": removed, "changed": changed}
            added_total += len(added)
            removed_total += len(removed)
            changed_total += len(changed)
        return {
            "summary": {
                "section_count": len(section_names),
                "added": added_total,
                "removed": removed_total,
                "changed": changed_total,
            },
            "sections": sections,
        }

    def _compare_policy_decisions(self, baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
        if not candidate:
            return {"changed": False, "fields": []}
        changed_fields = []
        for key in ["allowed", "requires_confirmation", "requires_approval", "reason", "matched_rules"]:
            if baseline.get(key) != candidate.get(key):
                changed_fields.append(key)
        return {
            "changed": bool(changed_fields),
            "fields": changed_fields,
            "baseline": {key: baseline.get(key) for key in ["allowed", "requires_confirmation", "requires_approval", "reason", "matched_rules"]},
            "candidate": {key: candidate.get(key) for key in ["allowed", "requires_confirmation", "requires_approval", "reason", "matched_rules"]},
        }

    def compliance_summary(
        self,
        gw: AdminGatewayLike,
        *,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        window_hours: int = 72,
        limit_per_section: int = 20,
    ) -> dict[str, Any]:
        now_ts = time.time()
        since_ts = now_ts - max(1, int(window_hours)) * 3600.0
        filters = {
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
            "environment": environment,
        }
        recent_events = self._event_window(gw, limit=max(limit_per_section * 20, 200), since_ts=since_ts, **filters)
        classified = self._classify_events(recent_events)
        tool_calls = self._filter_tool_calls_window(
            self._safe_call(
                gw.audit,
                "list_tool_calls",
                [],
                limit=max(limit_per_section, 1) * 10,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                environment=environment,
            ),
            since_ts=since_ts,
        )
        sessions = self._filter_sessions_window(
            self._safe_call(
                gw.audit,
                "list_sessions",
                [],
                limit=max(limit_per_section, 1) * 10,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                environment=environment,
            ),
            since_ts=since_ts,
        )
        return {
            "ok": True,
            "generated_at": now_ts,
            "window_hours": int(window_hours),
            "scope": filters,
            "counts": {
                "security_events": len(classified["security"]),
                "secret_usages": len(classified["secret_usage"]),
                "approval_events": len(classified["approvals"]),
                "config_changes": len(classified["config_changes"]),
                "tool_calls": len(tool_calls),
                "sessions": len(sessions),
            },
            "recent": {
                "security": classified["security"][:limit_per_section],
                "secret_usage": classified["secret_usage"][:limit_per_section],
                "approvals": classified["approvals"][:limit_per_section],
                "config_changes": classified["config_changes"][:limit_per_section],
                "tool_calls": tool_calls[:limit_per_section],
                "sessions": sessions[:limit_per_section],
            },
        }

    def export_compliance_report(
        self,
        gw: AdminGatewayLike,
        *,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        window_hours: int = 72,
        limit_per_section: int = 100,
        sections: list[str] | None = None,
        report_label: str = "initial",
    ) -> dict[str, Any]:
        normalized_sections = [
            str(item).strip().lower()
            for item in (sections or ["overview", "security", "secret_usage", "approvals", "config_changes", "tool_calls", "sessions"])
            if str(item).strip()
        ]
        summary = self.compliance_summary(
            gw,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            window_hours=window_hours,
            limit_per_section=limit_per_section,
        )
        report: dict[str, Any] = {
            "report_type": "openmiura-compliance-pack-initial",
            "label": str(report_label or "initial"),
            "generated_at": summary["generated_at"],
            "window_hours": summary["window_hours"],
            "scope": summary["scope"],
            "counts": summary["counts"],
            "sections": {},
        }
        if "overview" in normalized_sections:
            report["sections"]["overview"] = {
                "service": "openMiura",
                "policy_signature": self._safe_call(getattr(gw, "policy", None), "signature", None),
                "sandbox_profiles": sorted(list((getattr(getattr(gw, "sandbox", None), "profiles_catalog", lambda: {})() or {}).keys())),
                "secrets_enabled": bool(getattr(getattr(gw, "secret_broker", None), "is_enabled", lambda: False)()),
            }
        for section_name in ("security", "secret_usage", "approvals", "config_changes", "tool_calls", "sessions"):
            if section_name not in normalized_sections:
                continue
            key = section_name
            if section_name in summary["recent"]:
                report["sections"][key] = summary["recent"][section_name][:limit_per_section]
            else:
                report["sections"][key] = []
        canonical = json.dumps(report, ensure_ascii=False, sort_keys=True)
        report_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return {
            "ok": True,
            "format": "json",
            "report": report,
            "integrity": {
                "sha256": report_hash,
                "signed": False,
                "algorithm": "sha256",
            },
        }

    def reload(self, gw: AdminGatewayLike) -> dict[str, Any]:
        reload_fn = getattr(gw, "reload_dynamic_configs", None)
        result = {"agents": {"changed": False, "agents": []}, "policies": {"changed": False}}
        if callable(reload_fn):
            try:
                maybe = reload_fn(force=True)
            except TypeError:
                maybe = reload_fn()
            if isinstance(maybe, dict):
                result.update(maybe)
        return {"ok": True, **result}


    def config_center_snapshot(self, gw: AdminGatewayLike) -> dict[str, Any]:
        config_path = self._gateway_config_path(gw)
        snapshots: dict[str, dict[str, Any]] = {}
        sections: list[dict[str, Any]] = []
        for spec in self._config_section_specs(gw, config_path):
            snapshot = self._read_config_snapshot(gw, spec)
            snapshots[spec['name']] = snapshot
            sections.append(
                {
                    'name': spec['name'],
                    'title': spec['title'],
                    'path': snapshot['path'],
                    'exists': snapshot['exists'],
                    'reload_supported': spec['reload_supported'],
                    'restart_required': spec['restart_required'],
                    'summary': snapshot['summary'],
                }
            )
        status = self.status_snapshot(gw)
        return {
            'ok': True,
            'config_path': self._display_path(config_path),
            'sections': sections,
            'files': snapshots,
            'quick_settings': self._config_quick_settings(status),
            'channel_wizard': self.channel_setup_wizard_snapshot(gw),
            'secret_env_wizard': self.secret_env_reference_wizard_snapshot(gw),
            'reload_assistant': self.reload_assistant_snapshot(gw),
        }


    def reload_assistant_snapshot(self, gw: AdminGatewayLike) -> dict[str, Any]:
        config_path = self._gateway_config_path(gw)
        sections: list[dict[str, Any]] = []
        for spec in self._config_section_specs(gw, config_path):
            snapshot = self._read_config_snapshot(gw, spec)
            sections.append(
                {
                    'name': spec['name'],
                    'title': spec['title'],
                    'path': snapshot['path'],
                    'exists': snapshot['exists'],
                    'valid': snapshot['valid'],
                    'parse_error': snapshot['parse_error'],
                    'reload_supported': bool(spec['reload_supported']),
                    'restart_required': bool(spec['restart_required']),
                    'summary': snapshot['summary'],
                    'metadata': snapshot.get('metadata') or {},
                }
            )
        hook = self._restart_hook_status()
        recent = self._recent_restart_requests(gw)
        operational_state = self._reload_assistant_operational_state(gw, config_path=config_path, sections=sections, recent_restart_requests=recent)
        return {
            'ok': True,
            'config_path': self._display_path(config_path),
            'sections': sections,
            'defaults': {
                'apply_live_reload': True,
                'request_restart': False,
                'execute_restart_hook': False,
            },
            'capabilities': {
                'live_reload_sections': [item['name'] for item in sections if item.get('reload_supported')],
                'restart_required_sections': [item['name'] for item in sections if item.get('restart_required')],
            },
            'restart_hook': hook,
            'operational_state': operational_state,
            'recent_restart_requests': recent,
            'pending_restart_requests': [item for item in recent if str(item.get('status') or '') in {'queued', 'hook_failed'}],
        }

    def apply_reload_assistant(
        self,
        gw: AdminGatewayLike,
        *,
        sections: list[str] | None = None,
        apply_live_reload: bool = False,
        request_restart: bool = False,
        execute_restart_hook: bool = False,
        actor: str = 'admin',
    ) -> dict[str, Any]:
        config_path = self._gateway_config_path(gw)
        specs = {spec['name']: spec for spec in self._config_section_specs(gw, config_path)}
        normalized_sections: list[str] = []
        for raw in list(sections or []):
            name = str(raw or '').strip().lower()
            if name and name in specs and name not in normalized_sections:
                normalized_sections.append(name)
        if not normalized_sections and not request_restart:
            raise ValueError('reload_assistant_requires_sections_or_restart')

        live_reload_sections = [name for name in normalized_sections if bool(specs[name]['reload_supported'])]
        restart_trigger_sections = [name for name in normalized_sections if bool(specs[name]['restart_required'])]
        live_reload_applied = False
        reload_result: dict[str, Any] | None = None
        if apply_live_reload and live_reload_sections:
            reload_result = self.reload(gw)
            live_reload_applied = True

        restart_required = bool(restart_trigger_sections)
        restart_requested = bool(request_restart or restart_required)
        hook_status = self._restart_hook_status()
        hook_result: dict[str, Any] | None = None
        restart_request: dict[str, Any] | None = None

        if restart_requested:
            request_id = str(uuid.uuid4())
            status = 'queued'
            if execute_restart_hook:
                if hook_status.get('configured'):
                    hook_result = self._execute_restart_hook(str(hook_status.get('command') or ''), cwd=config_path.parent)
                    status = 'executed' if hook_result.get('ok') else 'hook_failed'
                else:
                    hook_result = {
                        'configured': False,
                        'executed': False,
                        'ok': False,
                        'reason': 'restart_hook_not_configured',
                    }
                    status = 'queued'
            restart_request = {
                'request_id': request_id,
                'created_at': time.time(),
                'actor': str(actor or 'admin'),
                'sections': normalized_sections,
                'restart_required_sections': restart_trigger_sections,
                'live_reload_sections': live_reload_sections,
                'request_restart': bool(request_restart),
                'restart_required': restart_required,
                'execute_restart_hook': bool(execute_restart_hook),
                'status': status,
                'hook': hook_result,
            }
            try:
                gw.audit.log_event(
                    direction='system',
                    channel='system',
                    user_id=str(actor or 'admin'),
                    session_id='system',
                    payload={
                        'event': 'assistant_restart_request',
                        **restart_request,
                    },
                )
            except Exception:
                pass
        elif live_reload_applied:
            try:
                gw.audit.log_event(
                    direction='system',
                    channel='system',
                    user_id=str(actor or 'admin'),
                    session_id='system',
                    payload={
                        'event': 'assistant_reload_applied',
                        'sections': normalized_sections,
                        'live_reload_sections': live_reload_sections,
                        'actor': str(actor or 'admin'),
                    },
                )
            except Exception:
                pass

        return {
            'ok': True,
            'selected_sections': normalized_sections,
            'apply_live_reload': bool(apply_live_reload),
            'live_reload_sections': live_reload_sections,
            'live_reload_applied': live_reload_applied,
            'reload_result': reload_result,
            'request_restart': bool(request_restart),
            'restart_required': restart_required,
            'restart_request': restart_request,
            'restart_hook': hook_status,
            'hook_result': hook_result,
            'recent_restart_requests': self._recent_restart_requests(gw),
        }

    def validate_config_content(
        self,
        gw: AdminGatewayLike,
        *,
        section: str,
        content: str,
        form_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        spec = self._config_section_spec(gw, section)
        rendered_content = self._materialize_config_content(gw, section=section, content=content, form_payload=form_payload)
        parsed = yaml.safe_load(str(rendered_content or ''))
        warnings: list[str] = []
        if parsed is None:
            parsed = {}
            warnings.append('empty_yaml_document')
        top_level_keys: list[str] = []
        if isinstance(parsed, dict):
            top_level_keys = [str(k) for k in parsed.keys()]
        elif isinstance(parsed, list):
            top_level_keys = [f'item[{idx}]' for idx, _ in enumerate(parsed[:10])]
        if section == 'openmiura' and isinstance(parsed, dict):
            llm = parsed.get('llm') or {}
            if not llm:
                warnings.append('llm_section_missing')
            elif not (llm.get('provider') and llm.get('model')):
                warnings.append('llm_provider_or_model_missing')
        normalized = yaml.safe_dump(parsed, sort_keys=False, allow_unicode=True)
        response = {
            'ok': True,
            'section': section,
            'path': self._display_path(spec['path']),
            'valid': True,
            'warnings': warnings,
            'top_level_keys': top_level_keys,
            'summary': self._build_config_file_summary(section, parsed),
            'normalized_yaml': normalized,
        }
        if section == 'openmiura' and isinstance(parsed, dict):
            response['form_values'] = self._extract_openmiura_form_values(parsed)
            response['form_schema'] = self._openmiura_form_schema()
        return response

    def save_config_content(
        self,
        gw: AdminGatewayLike,
        *,
        section: str,
        content: str,
        reload_after_save: bool = False,
        actor: str = 'admin',
        form_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        spec = self._config_section_spec(gw, section)
        validation = self.validate_config_content(gw, section=section, content=content, form_payload=form_payload)
        target_path = Path(spec['path'])
        target_path.parent.mkdir(parents=True, exist_ok=True)
        backup_path = None
        if target_path.exists():
            backup_root = self._config_backup_root(gw, self._gateway_config_path(gw))
            backup_root.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime('%Y%m%d-%H%M%S', time.gmtime())
            backup_name = f"{section}-{stamp}-{target_path.name}.bak"
            backup_path = backup_root / backup_name
            backup_path.write_text(target_path.read_text(encoding='utf-8'), encoding='utf-8')
        final_content = validation.get('normalized_yaml') or str(content or '')
        if final_content and not final_content.endswith('\n'):
            final_content += '\n'
        target_path.write_text(final_content, encoding='utf-8')

        reload_result: dict[str, Any] | None = None
        reload_applied = False
        restart_required = bool(spec['restart_required'])
        if reload_after_save and spec['reload_supported']:
            reload_result = self.reload(gw)
            reload_applied = True
        elif reload_after_save and restart_required:
            reload_result = {'ok': True, 'restart_required': True, 'reason': 'service_restart_required'}

        try:
            gw.audit.log_event(
                direction='security',
                channel='system',
                user_id=str(actor or 'admin'),
                session_id='system',
                payload={
                    'event': 'config_file_saved',
                    'section': section,
                    'path': self._display_path(target_path),
                    'reload_applied': reload_applied,
                    'restart_required': restart_required,
                    'backup_path': self._display_path(backup_path) if backup_path else '',
                },
            )
        except Exception:
            pass

        snapshot = self._read_config_snapshot(gw, spec)
        return {
            'ok': True,
            'section': section,
            'path': self._display_path(target_path),
            'backup_path': self._display_path(backup_path) if backup_path else None,
            'reload_supported': spec['reload_supported'],
            'reload_applied': reload_applied,
            'restart_required': restart_required,
            'reload_result': reload_result,
            'validation': validation,
            'snapshot': snapshot,
        }

    def channel_setup_wizard_snapshot(self, gw: AdminGatewayLike) -> dict[str, Any]:
        spec = self._config_section_spec(gw, 'openmiura')
        snapshot = self._read_config_snapshot(gw, spec)
        parsed = yaml.safe_load(snapshot.get('raw') or '') if str(snapshot.get('raw') or '').strip() else {}
        if parsed is None:
            parsed = {}
        if not isinstance(parsed, dict):
            parsed = {}
        values = self._extract_channel_wizard_values(parsed)
        channels = []
        for name in self._channel_wizard_channel_names():
            channels.append(
                {
                    'name': name,
                    'title': self._channel_wizard_channel_title(name),
                    'status': self._channel_wizard_status(name, values.get(name) or {}),
                }
            )
        return {
            'ok': True,
            'path': self._display_path(spec['path']),
            'schemas': self._channel_wizard_schema(),
            'values': values,
            'channels': channels,
            'raw': snapshot.get('raw') or '',
        }

    def validate_channel_setup(
        self,
        gw: AdminGatewayLike,
        *,
        channel: str,
        wizard_payload: dict[str, Any] | None = None,
        content: str = '',
    ) -> dict[str, Any]:
        normalized_channel = self._normalize_channel_name(channel)
        rendered_content = self._materialize_channel_wizard_content(
            gw,
            channel=normalized_channel,
            content=content,
            wizard_payload=wizard_payload,
        )
        parsed = yaml.safe_load(str(rendered_content or ''))
        warnings: list[str] = []
        if parsed is None:
            parsed = {}
            warnings.append('empty_yaml_document')
        if not isinstance(parsed, dict):
            raise ValueError('channel_wizard_requires_mapping_yaml')
        values = self._extract_channel_wizard_values(parsed)
        status = self._channel_wizard_status(normalized_channel, values.get(normalized_channel) or {})
        normalized_yaml = yaml.safe_dump(parsed, sort_keys=False, allow_unicode=True)
        return {
            'ok': True,
            'channel': normalized_channel,
            'path': str(self._config_section_spec(gw, 'openmiura')['path']),
            'warnings': warnings,
            'summary': self._build_config_file_summary('openmiura', parsed),
            'normalized_yaml': normalized_yaml,
            'wizard_schema': self._channel_wizard_schema().get(normalized_channel, []),
            'wizard_values': values.get(normalized_channel) or {},
            'channel_status': status,
        }

    def save_channel_setup(
        self,
        gw: AdminGatewayLike,
        *,
        channel: str,
        wizard_payload: dict[str, Any] | None = None,
        content: str = '',
        reload_after_save: bool = False,
        actor: str = 'admin',
    ) -> dict[str, Any]:
        validation = self.validate_channel_setup(gw, channel=channel, wizard_payload=wizard_payload, content=content)
        response = self.save_config_content(
            gw,
            section='openmiura',
            content=str(validation.get('normalized_yaml') or ''),
            reload_after_save=reload_after_save,
            actor=actor,
        )
        response['channel'] = validation['channel']
        response['channel_validation'] = validation
        response['channel_status'] = validation['channel_status']
        return response


    @staticmethod
    def _secret_env_profile_names() -> list[str]:
        return ['llm', 'telegram', 'slack', 'discord']

    @staticmethod
    def _secret_env_profile_title(profile: str) -> str:
        titles = {'llm': 'LLM provider', 'telegram': 'Telegram', 'slack': 'Slack', 'discord': 'Discord'}
        return titles.get(str(profile or '').strip().lower(), str(profile or '').strip().title() or 'Secret profile')

    def _normalize_secret_env_profile(self, profile: str) -> str:
        normalized = str(profile or '').strip().lower()
        if normalized not in self._secret_env_profile_names():
            raise ValueError('unsupported_secret_env_profile')
        return normalized

    @staticmethod
    def _env_reference_fields() -> set[str]:
        return {'llm.api_key_env_var'}

    def _secret_env_fields(self, profile: str) -> list[dict[str, Any]]:
        normalized = self._normalize_secret_env_profile(profile)
        if normalized == 'llm':
            return [
                {'group': 'Provider authentication', 'name': 'llm.api_key_env_var.mode', 'label': 'API key source', 'type': 'select', 'options': ['disabled', 'env']},
                {'group': 'Provider authentication', 'name': 'llm.api_key_env_var.value', 'label': 'API key env var', 'type': 'string', 'placeholder': 'OPENMIURA_LLM_API_KEY'},
            ]
        if normalized == 'telegram':
            return [
                {'group': 'Authentication', 'name': 'telegram.bot_token.mode', 'label': 'Bot token source', 'type': 'select', 'options': ['disabled', 'env', 'literal']},
                {'group': 'Authentication', 'name': 'telegram.bot_token.value', 'label': 'Bot token / env var', 'type': 'string', 'placeholder': 'OPENMIURA_TELEGRAM_BOT_TOKEN'},
                {'group': 'Authentication', 'name': 'telegram.webhook_secret.mode', 'label': 'Webhook secret source', 'type': 'select', 'options': ['disabled', 'env', 'literal']},
                {'group': 'Authentication', 'name': 'telegram.webhook_secret.value', 'label': 'Webhook secret / env var', 'type': 'string', 'placeholder': 'OPENMIURA_TELEGRAM_WEBHOOK_SECRET'},
            ]
        if normalized == 'slack':
            return [
                {'group': 'Authentication', 'name': 'slack.bot_token.mode', 'label': 'Bot token source', 'type': 'select', 'options': ['disabled', 'env', 'literal']},
                {'group': 'Authentication', 'name': 'slack.bot_token.value', 'label': 'Bot token / env var', 'type': 'string', 'placeholder': 'OPENMIURA_SLACK_BOT_TOKEN'},
                {'group': 'Authentication', 'name': 'slack.signing_secret.mode', 'label': 'Signing secret source', 'type': 'select', 'options': ['disabled', 'env', 'literal']},
                {'group': 'Authentication', 'name': 'slack.signing_secret.value', 'label': 'Signing secret / env var', 'type': 'string', 'placeholder': 'OPENMIURA_SLACK_SIGNING_SECRET'},
            ]
        return [
            {'group': 'Authentication', 'name': 'discord.bot_token.mode', 'label': 'Bot token source', 'type': 'select', 'options': ['disabled', 'env', 'literal']},
            {'group': 'Authentication', 'name': 'discord.bot_token.value', 'label': 'Bot token / env var', 'type': 'string', 'placeholder': 'OPENMIURA_DISCORD_BOT_TOKEN'},
        ]

    def _secret_env_schema(self) -> dict[str, list[dict[str, Any]]]:
        output: dict[str, list[dict[str, Any]]] = {}
        for profile in self._secret_env_profile_names():
            groups: dict[str, list[dict[str, Any]]] = {}
            for field in self._secret_env_fields(profile):
                groups.setdefault(str(field['group']), []).append({k: v for k, v in field.items() if k != 'group'})
            output[profile] = [{'group': group, 'fields': fields} for group, fields in groups.items()]
        return output

    @staticmethod
    def _extract_env_reference(raw_value: Any) -> tuple[str, str]:
        value = str(raw_value or '').strip()
        return ('env', value) if value else ('disabled', '')

    @staticmethod
    def _compose_env_reference(mode: Any, value: Any) -> str:
        normalized_mode = str(mode or 'disabled').strip().lower()
        raw_value = str(value or '').strip()
        if normalized_mode == 'env' and raw_value:
            return raw_value
        return ''

    @staticmethod
    def _default_secret_env_name(field_path: str, env_prefix: str = 'OPENMIURA') -> str:
        prefix = str(env_prefix or 'OPENMIURA').strip().upper().replace('-', '_').replace(' ', '_')
        mapping = {
            'llm.api_key_env_var': 'LLM_API_KEY',
            'telegram.bot_token': 'TELEGRAM_BOT_TOKEN',
            'telegram.webhook_secret': 'TELEGRAM_WEBHOOK_SECRET',
            'slack.bot_token': 'SLACK_BOT_TOKEN',
            'slack.signing_secret': 'SLACK_SIGNING_SECRET',
            'discord.bot_token': 'DISCORD_BOT_TOKEN',
        }
        suffix = mapping.get(field_path, field_path.replace('.', '_').upper())
        return f'{prefix}_{suffix}' if prefix else suffix

    def _secret_env_suggestions(self, env_prefix: str = 'OPENMIURA') -> dict[str, dict[str, str]]:
        return {
            'llm': {'llm.api_key_env_var': self._default_secret_env_name('llm.api_key_env_var', env_prefix)},
            'telegram': {
                'telegram.bot_token': self._default_secret_env_name('telegram.bot_token', env_prefix),
                'telegram.webhook_secret': self._default_secret_env_name('telegram.webhook_secret', env_prefix),
            },
            'slack': {
                'slack.bot_token': self._default_secret_env_name('slack.bot_token', env_prefix),
                'slack.signing_secret': self._default_secret_env_name('slack.signing_secret', env_prefix),
            },
            'discord': {'discord.bot_token': self._default_secret_env_name('discord.bot_token', env_prefix)},
        }

    def _extract_secret_env_values(self, parsed: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
        payload = parsed if isinstance(parsed, dict) else {}
        defaults: dict[str, dict[str, Any]] = {
            'llm': {
                'llm.api_key_env_var.mode': 'disabled',
                'llm.api_key_env_var.value': '',
            },
            'telegram': {
                'telegram.bot_token.mode': 'disabled',
                'telegram.bot_token.value': '',
                'telegram.webhook_secret.mode': 'disabled',
                'telegram.webhook_secret.value': '',
            },
            'slack': {
                'slack.bot_token.mode': 'disabled',
                'slack.bot_token.value': '',
                'slack.signing_secret.mode': 'disabled',
                'slack.signing_secret.value': '',
            },
            'discord': {
                'discord.bot_token.mode': 'disabled',
                'discord.bot_token.value': '',
            },
        }
        result = copy.deepcopy(defaults)
        for profile in self._secret_env_profile_names():
            values = result[profile]
            for field in self._secret_env_fields(profile):
                name = str(field['name'])
                if name.endswith('.mode') and name[:-5] in self._secret_storage_fields():
                    mode, _ = self._extract_secret_storage(self._config_get_path(payload, name[:-5], ''))
                    values[name] = mode
                    continue
                if name.endswith('.value') and name[:-6] in self._secret_storage_fields():
                    _, stored = self._extract_secret_storage(self._config_get_path(payload, name[:-6], ''))
                    values[name] = stored
                    continue
                if name.endswith('.mode') and name[:-5] in self._env_reference_fields():
                    mode, _ = self._extract_env_reference(self._config_get_path(payload, name[:-5], ''))
                    values[name] = mode
                    continue
                if name.endswith('.value') and name[:-6] in self._env_reference_fields():
                    _, stored = self._extract_env_reference(self._config_get_path(payload, name[:-6], ''))
                    values[name] = stored
                    continue
                values[name] = self._config_get_path(payload, name, copy.deepcopy(values.get(name)))
        return result

    @staticmethod
    def _coerce_secret_env_value(field_type: str, value: Any) -> Any:
        if field_type == 'bool':
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return bool(value)
            return str(value or '').strip().lower() in {'1', 'true', 'yes', 'on', 'y'}
        if field_type == 'int':
            try:
                return int(value)
            except Exception:
                return 0
        return str(value or '')

    def _apply_secret_env_values(
        self,
        base_payload: dict[str, Any],
        profile: str,
        wizard_payload: dict[str, Any],
        *,
        env_prefix: str = 'OPENMIURA',
    ) -> dict[str, Any]:
        normalized = self._normalize_secret_env_profile(profile)
        merged = copy.deepcopy(base_payload) if isinstance(base_payload, dict) else {}
        suggestions = self._secret_env_suggestions(env_prefix).get(normalized, {})
        for field in self._secret_env_fields(normalized):
            name = str(field['name'])
            if name.endswith('.mode') and name[:-5] in self._secret_storage_fields():
                secret_path = name[:-5]
                ref_value = wizard_payload.get(f'{secret_path}.value')
                if str(wizard_payload.get(name) or '').strip().lower() == 'env' and not str(ref_value or '').strip():
                    ref_value = suggestions.get(secret_path, '')
                composed = self._compose_secret_storage(wizard_payload.get(name), ref_value)
                self._config_set_path(merged, secret_path, composed)
                continue
            if name.endswith('.value') and name[:-6] in self._secret_storage_fields():
                continue
            if name.endswith('.mode') and name[:-5] in self._env_reference_fields():
                ref_path = name[:-5]
                ref_value = wizard_payload.get(f'{ref_path}.value')
                if str(wizard_payload.get(name) or '').strip().lower() == 'env' and not str(ref_value or '').strip():
                    ref_value = suggestions.get(ref_path, '')
                self._config_set_path(merged, ref_path, self._compose_env_reference(wizard_payload.get(name), ref_value))
                continue
            if name.endswith('.value') and name[:-6] in self._env_reference_fields():
                continue
            if name not in wizard_payload:
                continue
            value = self._coerce_secret_env_value(str(field.get('type') or 'string'), wizard_payload.get(name))
            self._config_set_path(merged, name, value)
        return merged

    def _materialize_secret_env_content(
        self,
        gw: AdminGatewayLike,
        *,
        profile: str,
        content: str,
        wizard_payload: dict[str, Any] | None = None,
        env_prefix: str = 'OPENMIURA',
    ) -> str:
        normalized = self._normalize_secret_env_profile(profile)
        base_raw = str(content or '')
        if not base_raw.strip():
            spec = self._config_section_spec(gw, 'openmiura')
            base_path = Path(spec['path'])
            if base_path.exists():
                base_raw = base_path.read_text(encoding='utf-8')
        base_payload = yaml.safe_load(base_raw) if str(base_raw or '').strip() else {}
        if base_payload is None:
            base_payload = {}
        if not isinstance(base_payload, dict):
            raise ValueError('secret_env_wizard_requires_mapping_yaml')
        if not wizard_payload:
            return yaml.safe_dump(base_payload, sort_keys=False, allow_unicode=True)
        merged = self._apply_secret_env_values(base_payload, normalized, wizard_payload, env_prefix=env_prefix)
        return yaml.safe_dump(merged, sort_keys=False, allow_unicode=True)

    def _secret_env_paths_for_profile(self, profile: str) -> list[str]:
        normalized = self._normalize_secret_env_profile(profile)
        if normalized == 'llm':
            return ['llm.api_key_env_var']
        if normalized == 'telegram':
            return ['telegram.bot_token', 'telegram.webhook_secret']
        if normalized == 'slack':
            return ['slack.bot_token', 'slack.signing_secret']
        return ['discord.bot_token']

    def _secret_env_profile_status(self, profile: str, values: dict[str, Any], *, env_prefix: str = 'OPENMIURA') -> dict[str, Any]:
        normalized = self._normalize_secret_env_profile(profile)
        paths = self._secret_env_paths_for_profile(normalized)
        suggestions = self._secret_env_suggestions(env_prefix).get(normalized, {})
        env_vars: list[str] = []
        env_fields = 0
        literal_fields = 0
        disabled_fields = 0
        for path in paths:
            mode_key = f'{path}.mode'
            value_key = f'{path}.value'
            mode = str(values.get(mode_key) or 'disabled').strip().lower()
            value = str(values.get(value_key) or '').strip()
            if mode == 'env':
                env_fields += 1
                env_vars.append(value or suggestions.get(path, ''))
            elif mode == 'literal':
                literal_fields += 1
            else:
                disabled_fields += 1
        env_lines = [f'{name}=' for name in env_vars if name]
        return {
            'configured': (env_fields + literal_fields) > 0,
            'profile': normalized,
            'env_prefix': str(env_prefix or 'OPENMIURA').strip() or 'OPENMIURA',
            'env_fields': env_fields,
            'literal_fields': literal_fields,
            'disabled_fields': disabled_fields,
            'env_vars': env_vars,
            'env_example': '\n'.join(env_lines),
            'suggestions': suggestions,
        }

    def secret_env_reference_wizard_snapshot(self, gw: AdminGatewayLike, *, env_prefix: str = 'OPENMIURA') -> dict[str, Any]:
        spec = self._config_section_spec(gw, 'openmiura')
        snapshot = self._read_config_snapshot(gw, spec)
        parsed = yaml.safe_load(snapshot.get('raw') or '') if str(snapshot.get('raw') or '').strip() else {}
        if parsed is None:
            parsed = {}
        if not isinstance(parsed, dict):
            parsed = {}
        values = self._extract_secret_env_values(parsed)
        profiles = []
        for name in self._secret_env_profile_names():
            profiles.append(
                {
                    'name': name,
                    'title': self._secret_env_profile_title(name),
                    'status': self._secret_env_profile_status(name, values.get(name) or {}, env_prefix=env_prefix),
                }
            )
        return {
            'ok': True,
            'path': self._display_path(spec['path']),
            'schemas': self._secret_env_schema(),
            'values': values,
            'profiles': profiles,
            'suggestions': self._secret_env_suggestions(env_prefix),
            'env_prefix': str(env_prefix or 'OPENMIURA').strip() or 'OPENMIURA',
            'raw': snapshot.get('raw') or '',
        }

    def validate_secret_env_references(
        self,
        gw: AdminGatewayLike,
        *,
        profile: str,
        wizard_payload: dict[str, Any] | None = None,
        content: str = '',
        env_prefix: str = 'OPENMIURA',
    ) -> dict[str, Any]:
        normalized_profile = self._normalize_secret_env_profile(profile)
        rendered_content = self._materialize_secret_env_content(
            gw,
            profile=normalized_profile,
            content=content,
            wizard_payload=wizard_payload,
            env_prefix=env_prefix,
        )
        parsed = yaml.safe_load(str(rendered_content or ''))
        warnings: list[str] = []
        if parsed is None:
            parsed = {}
            warnings.append('empty_yaml_document')
        if not isinstance(parsed, dict):
            raise ValueError('secret_env_wizard_requires_mapping_yaml')
        values = self._extract_secret_env_values(parsed)
        status = self._secret_env_profile_status(normalized_profile, values.get(normalized_profile) or {}, env_prefix=env_prefix)
        normalized_yaml = yaml.safe_dump(parsed, sort_keys=False, allow_unicode=True)
        return {
            'ok': True,
            'profile': normalized_profile,
            'path': str(self._config_section_spec(gw, 'openmiura')['path']),
            'warnings': warnings,
            'summary': self._build_config_file_summary('openmiura', parsed),
            'normalized_yaml': normalized_yaml,
            'wizard_schema': self._secret_env_schema().get(normalized_profile, []),
            'wizard_values': values.get(normalized_profile) or {},
            'profile_status': status,
            'env_prefix': str(env_prefix or 'OPENMIURA').strip() or 'OPENMIURA',
            'env_example': status.get('env_example') or '',
            'suggestions': self._secret_env_suggestions(env_prefix).get(normalized_profile, {}),
        }

    def save_secret_env_references(
        self,
        gw: AdminGatewayLike,
        *,
        profile: str,
        wizard_payload: dict[str, Any] | None = None,
        content: str = '',
        env_prefix: str = 'OPENMIURA',
        reload_after_save: bool = False,
        actor: str = 'admin',
    ) -> dict[str, Any]:
        validation = self.validate_secret_env_references(
            gw,
            profile=profile,
            wizard_payload=wizard_payload,
            content=content,
            env_prefix=env_prefix,
        )
        response = self.save_config_content(
            gw,
            section='openmiura',
            content=str(validation.get('normalized_yaml') or ''),
            reload_after_save=reload_after_save,
            actor=actor,
        )
        response['profile'] = validation['profile']
        response['secret_env_validation'] = validation
        response['profile_status'] = validation['profile_status']
        response['env_example'] = validation.get('env_example') or ''
        return response


    def list_identities(self, gw: AdminGatewayLike, *, global_user_key: str | None) -> dict[str, Any]:
        manager = getattr(gw, "identity", None)
        if manager is not None and hasattr(manager, "list_links"):
            items = manager.list_links(global_user_key)
        else:
            items = self._safe_call(gw.audit, "list_identities", [], global_user_key)
        return {"ok": True, "items": items}

    def link_identity(
        self,
        gw: AdminGatewayLike,
        *,
        channel_user_key: str,
        global_user_key: str,
        linked_by: str,
    ) -> dict[str, Any]:
        manager = getattr(gw, "identity", None)
        if manager is not None and hasattr(manager, "link"):
            manager.link(channel_user_key, global_user_key, linked_by=linked_by)
        else:
            try:
                gw.audit.set_identity(channel_user_key, global_user_key, linked_by=linked_by)
            except TypeError:
                gw.audit.set_identity(channel_user_key, global_user_key)
        return {"ok": True, "channel_user_key": channel_user_key, "global_user_key": global_user_key}

    def _event_window(
        self,
        gw: AdminGatewayLike,
        *,
        since_ts: float,
        limit: int,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> list[dict[str, Any]]:
        items = self._safe_call(
            gw.audit,
            "list_events_filtered",
            None,
            since_ts=since_ts,
            limit=limit,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        if items is not None:
            return list(items)
        fallback = self._safe_call(
            gw.audit,
            "get_recent_events",
            [],
            limit=limit,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        return [item for item in list(fallback) if float(item.get("ts") or 0.0) >= since_ts]

    def _classify_events(self, items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        buckets = {
            "security": [],
            "secret_usage": [],
            "approvals": [],
            "config_changes": [],
        }
        for item in items:
            payload = dict(item.get("payload") or {})
            event_name = str(payload.get("event") or payload.get("action") or "").strip().lower()
            channel = str(item.get("channel") or "").strip().lower()
            direction = str(item.get("direction") or "").strip().lower()
            if channel in {"security", "sandbox", "admin", "broker"} or direction == "security" or event_name.startswith("admin_"):
                buckets["security"].append(item)
            if event_name == "secret_resolved":
                buckets["secret_usage"].append(item)
            if event_name.startswith("approval_") or payload.get("approval_id") is not None:
                buckets["approvals"].append(item)
            if event_name in {"reload", "admin_reload", "config_changed", "policies_reloaded"} or "config" in event_name:
                buckets["config_changes"].append(item)
        return buckets

    @staticmethod
    def _filter_tool_calls_window(items: list[dict[str, Any]], *, since_ts: float) -> list[dict[str, Any]]:
        filtered: list[dict[str, Any]] = []
        for item in list(items or []):
            try:
                ts = float(item.get("ts") or 0.0)
            except Exception:
                ts = 0.0
            if ts >= since_ts:
                filtered.append(item)
        return filtered

    @staticmethod
    def _filter_sessions_window(items: list[dict[str, Any]], *, since_ts: float) -> list[dict[str, Any]]:
        filtered: list[dict[str, Any]] = []
        for item in list(items or []):
            raw_ts = item.get("updated_at", item.get("created_at"))
            try:
                ts = float(raw_ts or 0.0)
            except Exception:
                ts = 0.0
            if ts >= since_ts:
                filtered.append(item)
        return filtered

    @staticmethod
    def _user_security_message(*, scope: str, resource_name: str, final_state: str, concise_reason: str) -> str:
        if final_state == "denied":
            return f"Action denied for {scope} '{resource_name}'."
        if final_state == "approval_required":
            return f"Action for {scope} '{resource_name}' requires approval before execution."
        if final_state == "confirmation_required":
            return f"Action for {scope} '{resource_name}' requires explicit confirmation."
        return f"Action allowed for {scope} '{resource_name}'."

    @staticmethod
    def _admin_security_message(
        *,
        scope: str,
        resource_name: str,
        final_state: str,
        concise_reason: str,
        policy_decision: dict[str, Any],
        sandbox_payload: dict[str, Any] | None,
        secret_payload: dict[str, Any] | None,
    ) -> str:
        parts = [f"scope={scope}", f"resource={resource_name}", f"state={final_state}"]
        if concise_reason:
            parts.append(f"reason={concise_reason}")
        matched = list(policy_decision.get("matched_rules") or [])
        if matched:
            parts.append("policy_rules=" + ",".join(matched))
        if sandbox_payload and sandbox_payload.get("profile_name"):
            parts.append(f"sandbox_profile={sandbox_payload.get('profile_name')}")
        if secret_payload and secret_payload.get("ref"):
            parts.append(f"secret_ref={secret_payload.get('ref')}")
        return " | ".join(parts)

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

    def approve_release(
        self,
        gw: AdminGatewayLike,
        *,
        release_id: str,
        actor: str,
        reason: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        return self.release_service.approve_release(
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
    def _gateway_config_path(gw: AdminGatewayLike) -> Path:
        raw = str(getattr(gw, 'config_path', '') or os.environ.get('OPENMIURA_CONFIG', 'configs/openmiura.yaml'))
        return Path(raw).expanduser().resolve()

    @staticmethod
    def _resolve_config_related_path(base_config_path: Path, raw_path: str, *, default_path: str = '.') -> Path:
        return resolve_config_related_path(base_config_path, raw_path, default_path=default_path)

    @staticmethod
    def _display_path(path: str | Path | None) -> str:
        if path is None:
            return ''
        try:
            return Path(path).as_posix()
        except Exception:
            return str(path).replace('\\', '/')

    def _config_section_specs(self, gw: AdminGatewayLike, config_path: Path) -> list[dict[str, Any]]:
        settings = getattr(gw, 'settings', None)
        evaluations = getattr(settings, 'evaluations', None)
        return [
            {'name': 'openmiura', 'title': 'Main settings', 'path': config_path, 'reload_supported': False, 'restart_required': True},
            {'name': 'agents', 'title': 'Agents catalog', 'path': self._resolve_config_related_path(config_path, str(getattr(settings, 'agents_path', 'agents.yaml') or 'agents.yaml')), 'reload_supported': True, 'restart_required': False},
            {'name': 'policies', 'title': 'Policies', 'path': self._resolve_config_related_path(config_path, str(getattr(settings, 'policies_path', 'policies.yaml') or 'policies.yaml')), 'reload_supported': True, 'restart_required': False},
            {'name': 'evaluations', 'title': 'Evaluation suites', 'path': self._resolve_config_related_path(config_path, str(getattr(evaluations, 'suites_path', 'evaluations.yaml') or 'evaluations.yaml')), 'reload_supported': False, 'restart_required': False},
        ]

    def _config_section_spec(self, gw: AdminGatewayLike, section: str) -> dict[str, Any]:
        config_path = self._gateway_config_path(gw)
        for spec in self._config_section_specs(gw, config_path):
            if spec['name'] == section:
                return spec
        raise ValueError('unsupported_config_section')

    @staticmethod
    def _config_get_path(payload: dict[str, Any], dotted_path: str, default: Any = None) -> Any:
        current: Any = payload
        for part in dotted_path.split('.'):
            if not isinstance(current, dict) or part not in current:
                return copy.deepcopy(default)
            current = current.get(part)
        return copy.deepcopy(current)

    @staticmethod
    def _config_set_path(payload: dict[str, Any], dotted_path: str, value: Any) -> None:
        current = payload
        parts = dotted_path.split('.')
        for part in parts[:-1]:
            child = current.get(part)
            if not isinstance(child, dict):
                child = {}
                current[part] = child
            current = child
        current[parts[-1]] = value

    @staticmethod
    def _openmiura_form_fields() -> list[dict[str, Any]]:
        return [
            {'group': 'Server', 'name': 'server.host', 'label': 'Host', 'type': 'string', 'placeholder': '127.0.0.1'},
            {'group': 'Server', 'name': 'server.port', 'label': 'Port', 'type': 'int', 'min': 1},
            {'group': 'Storage', 'name': 'storage.backend', 'label': 'Backend', 'type': 'select', 'options': ['sqlite', 'postgres', 'custom']},
            {'group': 'Storage', 'name': 'storage.db_path', 'label': 'DB path', 'type': 'string', 'placeholder': 'data/audit.db'},
            {'group': 'Storage', 'name': 'storage.backup_dir', 'label': 'Backup dir', 'type': 'string', 'placeholder': 'data/backups'},
            {'group': 'Storage', 'name': 'storage.auto_migrate', 'label': 'Auto migrate', 'type': 'bool'},
            {'group': 'LLM', 'name': 'llm.provider', 'label': 'Provider', 'type': 'select', 'options': ['ollama', 'openai', 'openai_compat', 'local_openai_compat', 'lmstudio', 'vllm', 'kimi', 'anthropic']},
            {'group': 'LLM', 'name': 'llm.base_url', 'label': 'Base URL', 'type': 'string', 'placeholder': 'http://127.0.0.1:11434'},
            {'group': 'LLM', 'name': 'llm.model', 'label': 'Model', 'type': 'string', 'placeholder': 'qwen2.5:7b-instruct'},
            {'group': 'LLM', 'name': 'llm.timeout_s', 'label': 'Timeout (s)', 'type': 'int', 'min': 1},
            {'group': 'LLM', 'name': 'llm.max_output_tokens', 'label': 'Max output tokens', 'type': 'int', 'min': 1},
            {'group': 'LLM', 'name': 'llm.api_key_env_var', 'label': 'API key env var', 'type': 'string', 'placeholder': 'OPENAI_API_KEY'},
            {'group': 'Runtime', 'name': 'runtime.history_limit', 'label': 'History limit', 'type': 'int', 'min': 1},
            {'group': 'Runtime', 'name': 'runtime.worker_mode', 'label': 'Worker mode', 'type': 'select', 'options': ['external', 'inline']},
            {'group': 'Memory', 'name': 'memory.enabled', 'label': 'Memory enabled', 'type': 'bool'},
            {'group': 'Memory', 'name': 'memory.embed_model', 'label': 'Embedding model', 'type': 'string', 'placeholder': 'nomic-embed-text'},
            {'group': 'Memory', 'name': 'memory.embed_base_url', 'label': 'Embedding URL', 'type': 'string', 'placeholder': 'http://127.0.0.1:11434'},
            {'group': 'Memory', 'name': 'memory.top_k', 'label': 'Top K', 'type': 'int', 'min': 1},
            {'group': 'Memory', 'name': 'memory.min_score', 'label': 'Min score', 'type': 'float', 'step': '0.01'},
            {'group': 'Tools', 'name': 'tools.sandbox_dir', 'label': 'Sandbox dir', 'type': 'string', 'placeholder': 'data/sandbox'},
            {'group': 'Broker', 'name': 'broker.enabled', 'label': 'Broker enabled', 'type': 'bool'},
            {'group': 'Broker', 'name': 'broker.base_path', 'label': 'Broker base path', 'type': 'string', 'placeholder': '/broker'},
            {'group': 'Auth', 'name': 'auth.enabled', 'label': 'Auth enabled', 'type': 'bool'},
            {'group': 'Auth', 'name': 'auth.session_ttl_s', 'label': 'Session TTL (s)', 'type': 'int', 'min': 0},
            {'group': 'Tenancy', 'name': 'tenancy.enabled', 'label': 'Tenancy enabled', 'type': 'bool'},
            {'group': 'Tenancy', 'name': 'tenancy.default_tenant_id', 'label': 'Default tenant', 'type': 'string', 'placeholder': 'default'},
            {'group': 'Tenancy', 'name': 'tenancy.default_workspace_id', 'label': 'Default workspace', 'type': 'string', 'placeholder': 'main'},
            {'group': 'Tenancy', 'name': 'tenancy.default_environment', 'label': 'Default environment', 'type': 'string', 'placeholder': 'prod'},
            {'group': 'Paths', 'name': 'agents_path', 'label': 'Agents path', 'type': 'string', 'placeholder': 'agents.yaml'},
            {'group': 'Paths', 'name': 'policies_path', 'label': 'Policies path', 'type': 'string', 'placeholder': 'policies.yaml'},
            {'group': 'Paths', 'name': 'evaluations.suites_path', 'label': 'Evaluation suites path', 'type': 'string', 'placeholder': 'evaluations.yaml'},
        ]

    def _openmiura_form_schema(self) -> list[dict[str, Any]]:
        groups: dict[str, list[dict[str, Any]]] = {}
        for field in self._openmiura_form_fields():
            groups.setdefault(str(field['group']), []).append({k: v for k, v in field.items() if k != 'group'})
        return [{'group': group, 'fields': fields} for group, fields in groups.items()]

    def _extract_openmiura_form_values(self, parsed: dict[str, Any] | None) -> dict[str, Any]:
        payload = parsed if isinstance(parsed, dict) else {}
        defaults: dict[str, Any] = {
            'server.host': '127.0.0.1',
            'server.port': 8081,
            'storage.backend': 'sqlite',
            'storage.db_path': 'data/audit.db',
            'storage.backup_dir': 'data/backups',
            'storage.auto_migrate': True,
            'llm.provider': 'ollama',
            'llm.base_url': 'http://127.0.0.1:11434',
            'llm.model': 'qwen2.5:7b-instruct',
            'llm.timeout_s': 60,
            'llm.max_output_tokens': 2048,
            'llm.api_key_env_var': '',
            'runtime.history_limit': 12,
            'runtime.worker_mode': 'external',
            'memory.enabled': True,
            'memory.embed_model': 'nomic-embed-text',
            'memory.embed_base_url': 'http://127.0.0.1:11434',
            'memory.top_k': 6,
            'memory.min_score': 0.25,
            'tools.sandbox_dir': 'data/sandbox',
            'broker.enabled': False,
            'broker.base_path': '/broker',
            'auth.enabled': False,
            'auth.session_ttl_s': 3600,
            'tenancy.enabled': False,
            'tenancy.default_tenant_id': 'default',
            'tenancy.default_workspace_id': 'main',
            'tenancy.default_environment': 'prod',
            'agents_path': 'agents.yaml',
            'policies_path': 'policies.yaml',
            'evaluations.suites_path': 'evaluations.yaml',
        }
        return {name: self._config_get_path(payload, name, default) for name, default in defaults.items()}

    @staticmethod
    def _coerce_openmiura_form_value(field_type: str, value: Any) -> Any:
        if field_type == 'bool':
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return bool(value)
            return str(value or '').strip().lower() in {'1', 'true', 'yes', 'on', 'y'}
        if field_type == 'int':
            try:
                return int(value)
            except Exception:
                return 0
        if field_type == 'float':
            try:
                return float(value)
            except Exception:
                return 0.0
        return str(value or '')

    def _apply_openmiura_form_values(self, base_payload: dict[str, Any], form_payload: dict[str, Any]) -> dict[str, Any]:
        merged = copy.deepcopy(base_payload) if isinstance(base_payload, dict) else {}
        field_specs = {field['name']: field for field in self._openmiura_form_fields()}
        for name, field in field_specs.items():
            if name not in form_payload:
                continue
            value = self._coerce_openmiura_form_value(str(field.get('type') or 'string'), form_payload.get(name))
            self._config_set_path(merged, name, value)
        return merged

    @staticmethod
    def _channel_wizard_channel_names() -> list[str]:
        return ['telegram', 'slack', 'discord']

    @staticmethod
    def _channel_wizard_channel_title(channel: str) -> str:
        titles = {'telegram': 'Telegram', 'slack': 'Slack', 'discord': 'Discord'}
        return titles.get(str(channel or '').strip().lower(), str(channel or '').strip().title() or 'Channel')

    def _normalize_channel_name(self, channel: str) -> str:
        normalized = str(channel or '').strip().lower()
        if normalized not in self._channel_wizard_channel_names():
            raise ValueError('unsupported_channel_wizard_channel')
        return normalized

    @staticmethod
    def _secret_storage_fields() -> set[str]:
        return {
            'telegram.bot_token',
            'telegram.webhook_secret',
            'slack.bot_token',
            'slack.signing_secret',
            'discord.bot_token',
        }

    def _channel_wizard_fields(self, channel: str) -> list[dict[str, Any]]:
        normalized = self._normalize_channel_name(channel)
        if normalized == 'telegram':
            return [
                {'group': 'Authentication', 'name': 'telegram.bot_token.mode', 'label': 'Bot token source', 'type': 'select', 'options': ['disabled', 'env', 'literal']},
                {'group': 'Authentication', 'name': 'telegram.bot_token.value', 'label': 'Bot token / env var', 'type': 'string', 'placeholder': 'OPENMIURA_TELEGRAM_BOT_TOKEN'},
                {'group': 'Transport', 'name': 'telegram.mode', 'label': 'Mode', 'type': 'select', 'options': ['polling', 'webhook']},
                {'group': 'Transport', 'name': 'telegram.webhook_secret.mode', 'label': 'Webhook secret source', 'type': 'select', 'options': ['disabled', 'env', 'literal']},
                {'group': 'Transport', 'name': 'telegram.webhook_secret.value', 'label': 'Webhook secret / env var', 'type': 'string', 'placeholder': 'OPENMIURA_TELEGRAM_WEBHOOK_SECRET'},
                {'group': 'Allowlist', 'name': 'telegram.allowlist.enabled', 'label': 'Allowlist enabled', 'type': 'bool'},
                {'group': 'Allowlist', 'name': 'telegram.allowlist.allow_user_ids', 'label': 'Allowed user IDs', 'type': 'csv_int', 'placeholder': '12345,67890'},
                {'group': 'Allowlist', 'name': 'telegram.allowlist.allow_chat_ids', 'label': 'Allowed chat IDs', 'type': 'csv_int', 'placeholder': '-10012345,-10067890'},
                {'group': 'Allowlist', 'name': 'telegram.allowlist.allow_groups', 'label': 'Allow groups', 'type': 'bool'},
                {'group': 'Allowlist', 'name': 'telegram.allowlist.deny_message', 'label': 'Deny message', 'type': 'string', 'placeholder': '⛔ No autorizado. Pide acceso al administrador.'},
            ]
        if normalized == 'slack':
            return [
                {'group': 'Authentication', 'name': 'slack.bot_token.mode', 'label': 'Bot token source', 'type': 'select', 'options': ['disabled', 'env', 'literal']},
                {'group': 'Authentication', 'name': 'slack.bot_token.value', 'label': 'Bot token / env var', 'type': 'string', 'placeholder': 'OPENMIURA_SLACK_BOT_TOKEN'},
                {'group': 'Authentication', 'name': 'slack.signing_secret.mode', 'label': 'Signing secret source', 'type': 'select', 'options': ['disabled', 'env', 'literal']},
                {'group': 'Authentication', 'name': 'slack.signing_secret.value', 'label': 'Signing secret / env var', 'type': 'string', 'placeholder': 'OPENMIURA_SLACK_SIGNING_SECRET'},
                {'group': 'Transport', 'name': 'slack.bot_user_id', 'label': 'Bot user ID', 'type': 'string', 'placeholder': 'U012345'},
                {'group': 'Transport', 'name': 'slack.reply_in_thread', 'label': 'Reply in thread', 'type': 'bool'},
                {'group': 'Allowlist', 'name': 'slack.allowlist.enabled', 'label': 'Allowlist enabled', 'type': 'bool'},
                {'group': 'Allowlist', 'name': 'slack.allowlist.allow_team_ids', 'label': 'Allowed team IDs', 'type': 'csv_str', 'placeholder': 'T123,T456'},
                {'group': 'Allowlist', 'name': 'slack.allowlist.allow_channel_ids', 'label': 'Allowed channel IDs', 'type': 'csv_str', 'placeholder': 'C123,C456'},
                {'group': 'Allowlist', 'name': 'slack.allowlist.allow_im', 'label': 'Allow direct messages', 'type': 'bool'},
                {'group': 'Allowlist', 'name': 'slack.allowlist.deny_message', 'label': 'Deny message', 'type': 'string', 'placeholder': '⛔ No autorizado. Pide acceso al administrador.'},
            ]
        return [
            {'group': 'Authentication', 'name': 'discord.bot_token.mode', 'label': 'Bot token source', 'type': 'select', 'options': ['disabled', 'env', 'literal']},
            {'group': 'Authentication', 'name': 'discord.bot_token.value', 'label': 'Bot token / env var', 'type': 'string', 'placeholder': 'OPENMIURA_DISCORD_BOT_TOKEN'},
            {'group': 'Authentication', 'name': 'discord.application_id', 'label': 'Application ID', 'type': 'string', 'placeholder': '1234567890'},
            {'group': 'Transport', 'name': 'discord.mention_only', 'label': 'Mention only', 'type': 'bool'},
            {'group': 'Transport', 'name': 'discord.reply_as_reply', 'label': 'Reply as reply', 'type': 'bool'},
            {'group': 'Transport', 'name': 'discord.slash_enabled', 'label': 'Slash commands enabled', 'type': 'bool'},
            {'group': 'Transport', 'name': 'discord.slash_command_name', 'label': 'Slash command name', 'type': 'string', 'placeholder': 'miura'},
            {'group': 'Transport', 'name': 'discord.sync_on_startup', 'label': 'Sync on startup', 'type': 'bool'},
            {'group': 'Transport', 'name': 'discord.sync_guild_ids', 'label': 'Sync guild IDs', 'type': 'csv_int', 'placeholder': '111,222'},
            {'group': 'Transport', 'name': 'discord.expose_native_commands', 'label': 'Expose native commands', 'type': 'bool'},
            {'group': 'Transport', 'name': 'discord.include_attachments_in_text', 'label': 'Include attachments in text', 'type': 'bool'},
            {'group': 'Transport', 'name': 'discord.max_attachment_items', 'label': 'Max attachment items', 'type': 'int', 'min': 0},
            {'group': 'Allowlist', 'name': 'discord.allowlist.enabled', 'label': 'Allowlist enabled', 'type': 'bool'},
            {'group': 'Allowlist', 'name': 'discord.allowlist.allow_user_ids', 'label': 'Allowed user IDs', 'type': 'csv_int', 'placeholder': '1,2'},
            {'group': 'Allowlist', 'name': 'discord.allowlist.allow_channel_ids', 'label': 'Allowed channel IDs', 'type': 'csv_int', 'placeholder': '10,20'},
            {'group': 'Allowlist', 'name': 'discord.allowlist.allow_guild_ids', 'label': 'Allowed guild IDs', 'type': 'csv_int', 'placeholder': '100,200'},
            {'group': 'Allowlist', 'name': 'discord.allowlist.allow_dm', 'label': 'Allow direct messages', 'type': 'bool'},
            {'group': 'Allowlist', 'name': 'discord.allowlist.deny_message', 'label': 'Deny message', 'type': 'string', 'placeholder': '⛔ No autorizado. Pide acceso al administrador.'},
        ]

    def _channel_wizard_schema(self) -> dict[str, list[dict[str, Any]]]:
        output: dict[str, list[dict[str, Any]]] = {}
        for channel in self._channel_wizard_channel_names():
            groups: dict[str, list[dict[str, Any]]] = {}
            for field in self._channel_wizard_fields(channel):
                groups.setdefault(str(field['group']), []).append({k: v for k, v in field.items() if k != 'group'})
            output[channel] = [{'group': group, 'fields': fields} for group, fields in groups.items()]
        return output

    @staticmethod
    def _extract_secret_storage(raw_value: Any) -> tuple[str, str]:
        if isinstance(raw_value, str):
            value = raw_value.strip()
            if value.startswith('env:'):
                env_name = value[4:].split('|', 1)[0].strip()
                return 'env', env_name
            if value:
                return 'literal', value
        return 'disabled', ''

    @staticmethod
    def _compose_secret_storage(mode: Any, value: Any) -> str:
        normalized_mode = str(mode or 'disabled').strip().lower()
        raw_value = str(value or '').strip()
        if normalized_mode == 'env':
            return f'env:{raw_value}' if raw_value else ''
        if normalized_mode == 'literal':
            return raw_value
        return ''

    def _extract_channel_wizard_values(self, parsed: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
        payload = parsed if isinstance(parsed, dict) else {}
        defaults: dict[str, dict[str, Any]] = {
            'telegram': {
                'telegram.bot_token.mode': 'disabled',
                'telegram.bot_token.value': '',
                'telegram.mode': 'polling',
                'telegram.webhook_secret.mode': 'disabled',
                'telegram.webhook_secret.value': '',
                'telegram.allowlist.enabled': False,
                'telegram.allowlist.allow_user_ids': [],
                'telegram.allowlist.allow_chat_ids': [],
                'telegram.allowlist.allow_groups': False,
                'telegram.allowlist.deny_message': '⛔ No autorizado. Pide acceso al administrador.',
            },
            'slack': {
                'slack.bot_token.mode': 'disabled',
                'slack.bot_token.value': '',
                'slack.signing_secret.mode': 'disabled',
                'slack.signing_secret.value': '',
                'slack.bot_user_id': '',
                'slack.reply_in_thread': True,
                'slack.allowlist.enabled': False,
                'slack.allowlist.allow_team_ids': [],
                'slack.allowlist.allow_channel_ids': [],
                'slack.allowlist.allow_im': True,
                'slack.allowlist.deny_message': '⛔ No autorizado. Pide acceso al administrador.',
            },
            'discord': {
                'discord.bot_token.mode': 'disabled',
                'discord.bot_token.value': '',
                'discord.application_id': '',
                'discord.mention_only': True,
                'discord.reply_as_reply': True,
                'discord.slash_enabled': True,
                'discord.slash_command_name': 'miura',
                'discord.sync_on_startup': True,
                'discord.sync_guild_ids': [],
                'discord.expose_native_commands': True,
                'discord.include_attachments_in_text': True,
                'discord.max_attachment_items': 4,
                'discord.allowlist.enabled': False,
                'discord.allowlist.allow_user_ids': [],
                'discord.allowlist.allow_channel_ids': [],
                'discord.allowlist.allow_guild_ids': [],
                'discord.allowlist.allow_dm': True,
                'discord.allowlist.deny_message': '⛔ No autorizado. Pide acceso al administrador.',
            },
        }
        result = copy.deepcopy(defaults)
        for channel in self._channel_wizard_channel_names():
            values = result[channel]
            for field in self._channel_wizard_fields(channel):
                name = str(field['name'])
                field_type = str(field.get('type') or 'string')
                if name.endswith('.mode') and name[:-5] in self._secret_storage_fields():
                    mode, _ = self._extract_secret_storage(self._config_get_path(payload, name[:-5], ''))
                    values[name] = mode
                    continue
                if name.endswith('.value') and name[:-6] in self._secret_storage_fields():
                    _, stored = self._extract_secret_storage(self._config_get_path(payload, name[:-6], ''))
                    values[name] = stored
                    continue
                values[name] = self._config_get_path(payload, name, copy.deepcopy(values.get(name)))
                if field_type in {'csv_int', 'csv_str'} and not isinstance(values[name], list):
                    values[name] = []
        return result

    @staticmethod
    def _coerce_channel_wizard_value(field_type: str, value: Any) -> Any:
        if field_type == 'bool':
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return bool(value)
            return str(value or '').strip().lower() in {'1', 'true', 'yes', 'on', 'y'}
        if field_type == 'int':
            try:
                return int(value)
            except Exception:
                return 0
        if field_type == 'float':
            try:
                return float(value)
            except Exception:
                return 0.0
        if field_type in {'csv_int', 'csv_str'}:
            if isinstance(value, list):
                items = value
            else:
                raw = str(value or '')
                items = [part.strip() for chunk in raw.splitlines() for part in chunk.split(',')]
            cleaned = [item for item in items if str(item).strip()]
            if field_type == 'csv_int':
                numbers: list[int] = []
                for item in cleaned:
                    try:
                        numbers.append(int(str(item).strip()))
                    except Exception:
                        continue
                return numbers
            return [str(item).strip() for item in cleaned if str(item).strip()]
        return str(value or '')

    def _apply_channel_wizard_values(self, base_payload: dict[str, Any], channel: str, wizard_payload: dict[str, Any]) -> dict[str, Any]:
        normalized = self._normalize_channel_name(channel)
        merged = copy.deepcopy(base_payload) if isinstance(base_payload, dict) else {}
        for field in self._channel_wizard_fields(normalized):
            name = str(field['name'])
            if name.endswith('.mode') and name[:-5] in self._secret_storage_fields():
                secret_path = name[:-5]
                composed = self._compose_secret_storage(
                    wizard_payload.get(name),
                    wizard_payload.get(f'{secret_path}.value'),
                )
                self._config_set_path(merged, secret_path, composed)
                continue
            if name.endswith('.value') and name[:-6] in self._secret_storage_fields():
                continue
            if name not in wizard_payload:
                continue
            value = self._coerce_channel_wizard_value(str(field.get('type') or 'string'), wizard_payload.get(name))
            self._config_set_path(merged, name, value)
        return merged

    def _materialize_channel_wizard_content(
        self,
        gw: AdminGatewayLike,
        *,
        channel: str,
        content: str,
        wizard_payload: dict[str, Any] | None = None,
    ) -> str:
        normalized = self._normalize_channel_name(channel)
        base_raw = str(content or '')
        if not base_raw.strip():
            spec = self._config_section_spec(gw, 'openmiura')
            base_path = Path(spec['path'])
            if base_path.exists():
                base_raw = base_path.read_text(encoding='utf-8')
        base_payload = yaml.safe_load(base_raw) if str(base_raw or '').strip() else {}
        if base_payload is None:
            base_payload = {}
        if not isinstance(base_payload, dict):
            raise ValueError('channel_wizard_requires_mapping_yaml')
        if not wizard_payload:
            return yaml.safe_dump(base_payload, sort_keys=False, allow_unicode=True)
        merged = self._apply_channel_wizard_values(base_payload, normalized, wizard_payload)
        return yaml.safe_dump(merged, sort_keys=False, allow_unicode=True)

    def _channel_wizard_status(self, channel: str, values: dict[str, Any]) -> dict[str, Any]:
        normalized = self._normalize_channel_name(channel)
        if normalized == 'telegram':
            configured = str(values.get('telegram.bot_token.mode') or 'disabled') != 'disabled'
            webhook = str(values.get('telegram.webhook_secret.mode') or 'disabled') != 'disabled'
            return {
                'configured': configured,
                'transport': str(values.get('telegram.mode') or 'polling'),
                'secret_sources': {
                    'bot_token': values.get('telegram.bot_token.mode'),
                    'webhook_secret': values.get('telegram.webhook_secret.mode'),
                },
                'allowlist_enabled': bool(values.get('telegram.allowlist.enabled')),
                'allow_user_count': len(list(values.get('telegram.allowlist.allow_user_ids') or [])),
                'allow_chat_count': len(list(values.get('telegram.allowlist.allow_chat_ids') or [])),
                'webhook_secret_configured': webhook,
            }
        if normalized == 'slack':
            configured = str(values.get('slack.bot_token.mode') or 'disabled') != 'disabled'
            return {
                'configured': configured,
                'transport': 'events-api',
                'secret_sources': {
                    'bot_token': values.get('slack.bot_token.mode'),
                    'signing_secret': values.get('slack.signing_secret.mode'),
                },
                'reply_in_thread': bool(values.get('slack.reply_in_thread')),
                'allowlist_enabled': bool(values.get('slack.allowlist.enabled')),
                'allow_team_count': len(list(values.get('slack.allowlist.allow_team_ids') or [])),
                'allow_channel_count': len(list(values.get('slack.allowlist.allow_channel_ids') or [])),
            }
        configured = str(values.get('discord.bot_token.mode') or 'disabled') != 'disabled'
        return {
            'configured': configured,
            'transport': 'gateway',
            'secret_sources': {
                'bot_token': values.get('discord.bot_token.mode'),
            },
            'application_id_present': bool(str(values.get('discord.application_id') or '').strip()),
            'slash_enabled': bool(values.get('discord.slash_enabled')),
            'allowlist_enabled': bool(values.get('discord.allowlist.enabled')),
            'allow_guild_count': len(list(values.get('discord.allowlist.allow_guild_ids') or [])),
            'sync_guild_count': len(list(values.get('discord.sync_guild_ids') or [])),
        }


    def _materialize_config_content(
        self,
        gw: AdminGatewayLike,
        *,
        section: str,
        content: str,
        form_payload: dict[str, Any] | None = None,
    ) -> str:
        if section != 'openmiura' or not form_payload:
            return str(content or '')
        base_raw = str(content or '')
        if not base_raw.strip():
            spec = self._config_section_spec(gw, section)
            base_path = Path(spec['path'])
            if base_path.exists():
                base_raw = base_path.read_text(encoding='utf-8')
        base_payload = yaml.safe_load(base_raw) if str(base_raw or '').strip() else {}
        if base_payload is None:
            base_payload = {}
        if not isinstance(base_payload, dict):
            raise ValueError('openmiura_form_requires_mapping_yaml')
        merged = self._apply_openmiura_form_values(base_payload, form_payload)
        return yaml.safe_dump(merged, sort_keys=False, allow_unicode=True)

    def _read_config_snapshot(self, gw: AdminGatewayLike, spec: dict[str, Any]) -> dict[str, Any]:
        path = Path(spec['path'])
        exists = path.exists()
        raw = path.read_text(encoding='utf-8') if exists else ''
        valid = True
        parse_error = ''
        parsed: Any = {}
        if raw.strip():
            try:
                parsed = yaml.safe_load(raw)
            except Exception as exc:
                valid = False
                parse_error = str(exc)
                parsed = {}
        elif exists:
            parsed = {}
        top_level_keys = [str(k) for k in parsed.keys()] if isinstance(parsed, dict) else []
        metadata = self._file_runtime_metadata(path)
        snapshot = {
            'section': spec['name'],
            'title': spec['title'],
            'path': self._display_path(path),
            'exists': exists,
            'valid': valid,
            'parse_error': parse_error,
            'raw': raw,
            'top_level_keys': top_level_keys,
            'reload_supported': bool(spec['reload_supported']),
            'restart_required': bool(spec['restart_required']),
            'summary': self._build_config_file_summary(spec['name'], parsed),
            'metadata': metadata,
        }
        if spec['name'] == 'openmiura':
            snapshot['form_schema'] = self._openmiura_form_schema()
            snapshot['form_values'] = self._extract_openmiura_form_values(parsed if isinstance(parsed, dict) else {})
        return snapshot

    @staticmethod
    def _config_quick_settings(status: dict[str, Any]) -> dict[str, Any]:
        return {
            'llm': dict(status.get('llm') or {}),
            'sessions': dict(status.get('sessions') or {}),
            'memory': dict(status.get('memory') or {}),
            'sandbox': dict(status.get('sandbox') or {}),
            'router': dict(status.get('router') or {}),
            'channels': dict(status.get('channels') or {}),
            'policy': dict(status.get('policy') or {}),
            'db': dict(status.get('db') or {}),
        }


    @staticmethod
    def _restart_hook_status() -> dict[str, Any]:
        allow_self_restart = str(os.environ.get('OPENMIURA_CONTROL_ALLOW_SELF_RESTART', '') or '').strip().lower() in {'1', 'true', 'yes', 'on'}
        command = str(os.environ.get('OPENMIURA_CONTROL_SELF_RESTART_COMMAND', '') or '').strip()
        configured = bool(allow_self_restart and command)
        return {
            'allow_self_restart': allow_self_restart,
            'configured': configured,
            'command': command,
            'command_preview': command if configured else '',
        }

    def _reload_assistant_operational_state(
        self,
        gw: AdminGatewayLike,
        *,
        config_path: Path,
        sections: list[dict[str, Any]],
        recent_restart_requests: list[dict[str, Any]],
    ) -> dict[str, Any]:
        started_at = float(getattr(gw, 'started_at', time.time()) or time.time())
        now = time.time()
        uptime_s = max(0.0, now - started_at)
        latest_request = dict(recent_restart_requests[0]) if recent_restart_requests else {}
        latest_request_ts = float(latest_request.get('ts') or 0.0)
        latest_hook_result = dict(latest_request.get('hook') or {}) if isinstance(latest_request.get('hook'), dict) else {}
        latest_startup_event = self._latest_startup_event(gw)
        latest_startup_payload = dict(latest_startup_event.get('payload') or {}) if latest_startup_event else {}
        latest_startup_started_at = float(latest_startup_payload.get('started_at') or latest_startup_event.get('ts') or 0.0) if latest_startup_event else 0.0
        observed_new_process = bool(latest_request and max(started_at, latest_startup_started_at) > latest_request_ts > 0.0)
        if not latest_request:
            restart_state = 'not_requested'
            restart_summary = 'No restart request has been recorded yet.'
        elif observed_new_process:
            restart_state = 'confirmed'
            restart_summary = 'Current process started after the latest restart request.'
        elif str(latest_request.get('status') or '') == 'queued':
            restart_state = 'pending'
            restart_summary = 'A restart request is queued but a newer process has not been observed yet.'
        elif str(latest_request.get('status') or '') == 'hook_failed':
            restart_state = 'hook_failed'
            restart_summary = 'The latest restart hook execution failed.'
        else:
            restart_state = 'awaiting_observation'
            restart_summary = 'A restart was requested, but this process has not changed since that request.'

        main_config = self._file_runtime_metadata(config_path)
        section_files = []
        missing_files = []
        invalid_files = []
        for item in sections:
            metadata = self._file_runtime_metadata(Path(str(item.get('path') or '')))
            record = {
                'name': item.get('name'),
                'title': item.get('title'),
                'reload_supported': bool(item.get('reload_supported')),
                'restart_required': bool(item.get('restart_required')),
                'exists': bool(item.get('exists')),
                'valid': bool(item.get('valid', True)),
                'metadata': metadata,
                'summary': dict(item.get('summary') or {}),
            }
            if not bool(item.get('exists')):
                missing_files.append(str(item.get('name') or ''))
            if not bool(item.get('valid', True)) or str(item.get('parse_error') or '').strip():
                invalid_files.append(str(item.get('name') or ''))
            section_files.append(record)

        health_checks = {
            'gateway_loaded': True,
            'main_config_present': bool(main_config.get('exists')),
            'policy_engine_loaded': bool(getattr(gw, 'policy', None) is not None),
            'router_loaded': bool(getattr(gw, 'router', None) is not None),
            'audit_store_ready': bool(getattr(gw, 'audit', None) is not None),
        }
        health_status = 'healthy'
        health_issues: list[str] = []
        if not main_config.get('exists'):
            health_status = 'degraded'
            health_issues.append('main_config_missing')
        if missing_files:
            health_status = 'degraded'
            health_issues.append('config_section_missing')
        if invalid_files:
            health_status = 'degraded'
            health_issues.append('config_section_invalid')
        if restart_state == 'hook_failed':
            health_status = 'degraded'
            health_issues.append('restart_hook_failed')

        runtime_summary = self.status_snapshot(gw)
        current_boot_id = str(getattr(gw, 'boot_instance_id', '') or '')
        current_boot = {
            'boot_instance_id': current_boot_id,
            'pid': os.getpid(),
            'service': 'openMiura',
            'version': __version__,
            'started_at': started_at,
            'started_at_iso': self._iso_timestamp(started_at),
            'uptime_s': uptime_s,
            'uptime_human': self._format_duration(uptime_s),
            'config_path': self._display_path(config_path),
            'config_sha256': main_config.get('sha256'),
        }
        latest_boot_evidence: dict[str, Any]
        if latest_startup_event:
            latest_boot_instance_id = str(latest_startup_payload.get('boot_instance_id') or '')
            latest_boot_pid = int(latest_startup_payload.get('pid') or 0) if str(latest_startup_payload.get('pid') or '').strip() else 0
            current_process_matches = bool(
                (current_boot_id and latest_boot_instance_id and latest_boot_instance_id == current_boot_id)
                or (latest_boot_pid and latest_boot_pid == os.getpid() and latest_startup_started_at and abs(latest_startup_started_at - started_at) < 5.0)
            )
            latest_boot_evidence = {
                'source': 'audit_event',
                'event_id': latest_startup_event.get('id'),
                'event_ts': float(latest_startup_event.get('ts') or 0.0),
                'event_ts_iso': self._iso_timestamp(float(latest_startup_event.get('ts') or 0.0)),
                'boot_instance_id': latest_boot_instance_id,
                'pid': latest_boot_pid,
                'started_at': latest_startup_started_at,
                'started_at_iso': self._iso_timestamp(latest_startup_started_at),
                'config_path': self._display_path(latest_startup_payload.get('config_path') or config_path),
                'current_process_matches': current_process_matches,
                'observed_after_latest_restart_request': bool(latest_request and latest_startup_started_at > latest_request_ts > 0.0),
                'summary': 'Latest startup event matches the current running process.' if current_process_matches else 'Latest startup event differs from the current in-memory process.',
            }
        else:
            latest_boot_evidence = {
                'source': 'runtime_only',
                'event_id': None,
                'event_ts': None,
                'event_ts_iso': '',
                'boot_instance_id': current_boot_id,
                'pid': os.getpid(),
                'started_at': started_at,
                'started_at_iso': self._iso_timestamp(started_at),
                'config_path': self._display_path(config_path),
                'current_process_matches': True,
                'observed_after_latest_restart_request': bool(latest_request and started_at > latest_request_ts > 0.0),
                'summary': 'No startup audit event was found; using the current runtime as the boot evidence.',
            }
        process = {
            'pid': os.getpid(),
            'service': 'openMiura',
            'version': __version__,
            'started_at': started_at,
            'started_at_iso': self._iso_timestamp(started_at),
            'uptime_s': uptime_s,
            'uptime_human': self._format_duration(uptime_s),
            'boot_instance_id': current_boot_id,
        }
        restart_hook_result = {
            'available': bool(latest_hook_result),
            'request_id': latest_request.get('request_id') if latest_request else None,
            'request_status': latest_request.get('status') if latest_request else None,
            'requested_execution': bool(latest_request.get('execute_restart_hook')) if latest_request else False,
            'configured': bool(latest_hook_result.get('configured')) if latest_hook_result else False,
            'executed': bool(latest_hook_result.get('executed')) if latest_hook_result else False,
            'ok': bool(latest_hook_result.get('ok')) if latest_hook_result else False,
            'exit_code': latest_hook_result.get('exit_code') if latest_hook_result else None,
            'error': latest_hook_result.get('error') if latest_hook_result else '',
            'stdout_excerpt': latest_hook_result.get('stdout_excerpt') if latest_hook_result else '',
            'stderr_excerpt': latest_hook_result.get('stderr_excerpt') if latest_hook_result else '',
            'started_at': latest_hook_result.get('started_at') if latest_hook_result else None,
            'started_at_iso': self._iso_timestamp(float(latest_hook_result.get('started_at') or 0.0)) if latest_hook_result else '',
            'finished_at': latest_hook_result.get('finished_at') if latest_hook_result else None,
            'finished_at_iso': self._iso_timestamp(float(latest_hook_result.get('finished_at') or 0.0)) if latest_hook_result else '',
            'summary': 'No restart hook result is available yet.',
        }
        if latest_hook_result:
            if restart_hook_result['ok']:
                restart_hook_result['summary'] = 'The latest restart hook execution completed successfully.'
            elif restart_hook_result['executed']:
                restart_hook_result['summary'] = 'The latest restart hook execution finished with an error.'
            else:
                restart_hook_result['summary'] = 'The latest restart request did not execute the restart hook.'
        elif latest_request and not bool(latest_request.get('execute_restart_hook')):
            restart_hook_result['summary'] = 'The latest restart request was queued without executing the external hook.'

        restart_observation = {
            'state': restart_state,
            'summary': restart_summary,
            'latest_request_id': latest_request.get('request_id') if latest_request else None,
            'latest_request_status': latest_request.get('status') if latest_request else None,
            'latest_request_ts': latest_request_ts if latest_request else None,
            'latest_request_ts_iso': self._iso_timestamp(latest_request_ts) if latest_request else '',
            'observed_new_process_since_request': observed_new_process,
            'current_boot_instance_id': current_boot_id,
            'latest_boot_instance_id': latest_boot_evidence.get('boot_instance_id'),
        }
        startup_config = {
            'main_config': main_config,
            'router': dict(runtime_summary.get('router') or {}),
            'policy': dict(runtime_summary.get('policy') or {}),
            'channels': dict(runtime_summary.get('channels') or {}),
            'llm': dict(runtime_summary.get('llm') or {}),
            'db': {'path': ((runtime_summary.get('db') or {}).get('path')), 'counts': dict(((runtime_summary.get('db') or {}).get('counts') or {}))},
            'tenancy': dict(runtime_summary.get('tenancy') or {}),
            'section_files': section_files,
        }
        return {
            'process': process,
            'health': {
                'status': health_status,
                'checked_at': now,
                'checked_at_iso': self._iso_timestamp(now),
                'issues': health_issues,
                'checks': health_checks,
            },
            'startup_config': startup_config,
            'current_boot': current_boot,
            'latest_boot_evidence': latest_boot_evidence,
            'restart_hook_result': restart_hook_result,
            'restart_observation': restart_observation,
        }

    def _latest_startup_event(self, gw: AdminGatewayLike) -> dict[str, Any]:
        try:
            events = list(gw.audit.get_recent_events(limit=25, channel='system'))
        except Exception:
            events = []
        for event in events:
            payload = dict(event.get('payload') or {})
            if str(payload.get('event') or '') == 'startup':
                return event
        return {}

    @staticmethod
    def _file_runtime_metadata(path: Path) -> dict[str, Any]:
        candidate = Path(path).expanduser().resolve()
        exists = candidate.exists()
        metadata = {
            'path': AdminService._display_path(candidate),
            'exists': exists,
            'size_bytes': int(candidate.stat().st_size) if exists else 0,
            'mtime': float(candidate.stat().st_mtime) if exists else 0.0,
            'mtime_iso': AdminService._iso_timestamp(float(candidate.stat().st_mtime)) if exists else '',
            'sha256': '',
            'parse_error': '',
        }
        if exists and candidate.is_file():
            try:
                raw = candidate.read_bytes()
                metadata['sha256'] = hashlib.sha256(raw).hexdigest()
            except Exception as exc:
                metadata['parse_error'] = str(exc)
        return metadata

    @staticmethod
    def _format_duration(seconds: float) -> str:
        total = max(0, int(seconds))
        hours, remainder = divmod(total, 3600)
        minutes, secs = divmod(remainder, 60)
        if hours:
            return f'{hours}h {minutes}m {secs}s'
        if minutes:
            return f'{minutes}m {secs}s'
        return f'{secs}s'

    @staticmethod
    def _iso_timestamp(ts: float | None) -> str:
        if not ts:
            return ''
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).astimezone().isoformat(timespec='seconds')

    def _execute_restart_hook(self, command: str, *, cwd: Path) -> dict[str, Any]:
        started_at = time.time()
        try:
            proc = subprocess.run(
                command,
                cwd=str(cwd),
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            stdout = str(proc.stdout or '')
            stderr = str(proc.stderr or '')
            return {
                'configured': True,
                'executed': True,
                'ok': proc.returncode == 0,
                'exit_code': int(proc.returncode),
                'stdout_excerpt': stdout[-1000:],
                'stderr_excerpt': stderr[-1000:],
                'started_at': started_at,
                'finished_at': time.time(),
            }
        except Exception as exc:
            return {
                'configured': True,
                'executed': True,
                'ok': False,
                'error': str(exc),
                'started_at': started_at,
                'finished_at': time.time(),
            }

    def _recent_restart_requests(self, gw: AdminGatewayLike, *, limit: int = 10) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        try:
            events = list(gw.audit.get_recent_events(limit=max(50, limit * 10), channel='system'))
        except Exception:
            events = []
        for event in events:
            payload = dict(event.get('payload') or {})
            if str(payload.get('event') or '') != 'assistant_restart_request':
                continue
            hook = dict(payload.get('hook') or {}) if isinstance(payload.get('hook'), dict) else {}
            items.append(
                {
                    'request_id': payload.get('request_id'),
                    'ts': float(event.get('ts') or payload.get('created_at') or 0.0),
                    'actor': payload.get('actor') or event.get('user_id'),
                    'sections': list(payload.get('sections') or []),
                    'restart_required_sections': list(payload.get('restart_required_sections') or []),
                    'status': str(payload.get('status') or 'queued'),
                    'execute_restart_hook': bool(payload.get('execute_restart_hook')),
                    'hook_ok': bool(hook.get('ok')) if hook else False,
                    'hook': hook,
                }
            )
            if len(items) >= limit:
                break
        return items

    def _config_backup_root(self, gw: AdminGatewayLike, config_path: Path) -> Path:
        backup_dir = str(getattr(getattr(getattr(gw, 'settings', None), 'storage', None), 'backup_dir', '') or 'data/backups')
        return self._resolve_config_related_path(config_path, backup_dir) / 'ui-config'

    @staticmethod
    def _build_config_file_summary(section: str, parsed: Any) -> dict[str, Any]:
        if not isinstance(parsed, dict):
            return {'type': type(parsed).__name__}
        if section == 'openmiura':
            llm = dict(parsed.get('llm') or {})
            memory = dict(parsed.get('memory') or {})
            broker = dict(parsed.get('broker') or {})
            auth = dict(parsed.get('auth') or {})
            server = dict(parsed.get('server') or {})
            storage = dict(parsed.get('storage') or {})
            telegram = dict(parsed.get('telegram') or {})
            slack = dict(parsed.get('slack') or {})
            discord = dict(parsed.get('discord') or {})
            return {
                'server': {'host': server.get('host'), 'port': server.get('port')},
                'llm': {'provider': llm.get('provider'), 'model': llm.get('model'), 'base_url': llm.get('base_url')},
                'memory_enabled': bool(memory.get('enabled', False)),
                'broker_enabled': bool(broker.get('enabled', False)),
                'auth_enabled': bool(auth.get('enabled', False)),
                'db_path': storage.get('db_path'),
                'channels': {
                    'telegram': {'configured': bool(str(telegram.get('bot_token') or '').strip()), 'mode': telegram.get('mode', 'polling')},
                    'slack': {'configured': bool(str(slack.get('bot_token') or '').strip()), 'reply_in_thread': bool(slack.get('reply_in_thread', True))},
                    'discord': {'configured': bool(str(discord.get('bot_token') or '').strip()), 'slash_enabled': bool(discord.get('slash_enabled', True))},
                },
            }
        if section == 'agents':
            raw_agents = parsed.get('agents')
            if isinstance(raw_agents, dict):
                agent_ids = [str(k) for k in raw_agents.keys()]
                return {'agent_count': len(raw_agents), 'agent_ids': sorted(agent_ids)[:20], 'catalog_shape': 'mapping'}
            if isinstance(raw_agents, list):
                agent_ids: list[str] = []
                for index, item in enumerate(raw_agents):
                    if isinstance(item, dict):
                        candidate = item.get('name') or item.get('agent_id') or item.get('id')
                        if candidate is not None and str(candidate).strip():
                            agent_ids.append(str(candidate))
                            continue
                    agent_ids.append(f'item_{index}')
                return {'agent_count': len(raw_agents), 'agent_ids': sorted(agent_ids)[:20], 'catalog_shape': 'list'}
            agent_ids = [str(k) for k in parsed.keys()]
            return {'agent_count': len(agent_ids), 'agent_ids': sorted(agent_ids)[:20], 'catalog_shape': 'mapping'}
        if section == 'policies':
            return {
                'tool_rules': len(list(parsed.get('tool_rules') or [])),
                'memory_rules': len(list(parsed.get('memory_rules') or [])),
                'secret_rules': len(list(parsed.get('secret_rules') or [])),
                'channel_rules': len(list(parsed.get('channel_rules') or [])),
                'approval_rules': len(list(parsed.get('approval_rules') or [])),
            }
        if section == 'evaluations':
            suites = dict(parsed.get('suites') or {})
            return {'suite_count': len(suites), 'suite_names': sorted([str(k) for k in suites.keys()])[:20]}
        return {'keys': [str(k) for k in parsed.keys()]}


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


    def list_voice_sessions(
        self,
        gw: AdminGatewayLike,
        *,
        limit: int = 50,
        status: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.voice_runtime_service.list_sessions(
            gw,
            limit=limit,
            status=status,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def get_voice_session(
        self,
        gw: AdminGatewayLike,
        *,
        voice_session_id: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.voice_runtime_service.get_session(
            gw,
            voice_session_id=voice_session_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def start_voice_session(
        self,
        gw: AdminGatewayLike,
        *,
        actor: str,
        user_key: str,
        locale: str = 'es-ES',
        stt_provider: str = 'simulated-stt',
        tts_provider: str = 'simulated-tts',
        metadata: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.voice_runtime_service.start_session(
            gw,
            actor=actor,
            user_key=user_key,
            locale=locale,
            stt_provider=stt_provider,
            tts_provider=tts_provider,
            metadata=metadata,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def transcribe_voice_turn(
        self,
        gw: AdminGatewayLike,
        *,
        voice_session_id: str,
        actor: str,
        transcript_text: str,
        confidence: float = 1.0,
        language: str = '',
        metadata: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.voice_runtime_service.transcribe(
            gw,
            voice_session_id=voice_session_id,
            actor=actor,
            transcript_text=transcript_text,
            confidence=confidence,
            language=language,
            metadata=metadata,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def transcribe_voice_audio(
        self,
        gw: AdminGatewayLike,
        *,
        voice_session_id: str,
        actor: str,
        audio_b64: str,
        mime_type: str = 'audio/wav',
        sample_rate_hz: int = 16000,
        language: str = '',
        metadata: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.voice_runtime_service.transcribe_audio(
            gw,
            voice_session_id=voice_session_id,
            actor=actor,
            audio_b64=audio_b64,
            mime_type=mime_type,
            sample_rate_hz=sample_rate_hz,
            language=language,
            metadata=metadata,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def respond_voice_turn(
        self,
        gw: AdminGatewayLike,
        *,
        voice_session_id: str,
        actor: str,
        text: str,
        voice_name: str = 'assistant',
        metadata: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.voice_runtime_service.respond(
            gw,
            voice_session_id=voice_session_id,
            actor=actor,
            text=text,
            voice_name=voice_name,
            metadata=metadata,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def confirm_voice_turn(
        self,
        gw: AdminGatewayLike,
        *,
        voice_session_id: str,
        actor: str,
        decision: str = 'confirm',
        confirmation_text: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.voice_runtime_service.confirm(
            gw,
            voice_session_id=voice_session_id,
            actor=actor,
            decision=decision,
            confirmation_text=confirmation_text,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def close_voice_session(
        self,
        gw: AdminGatewayLike,
        *,
        voice_session_id: str,
        actor: str,
        reason: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.voice_runtime_service.close_session(
            gw,
            voice_session_id=voice_session_id,
            actor=actor,
            reason=reason,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )


    def list_app_installations(
        self,
        gw: AdminGatewayLike,
        *,
        limit: int = 50,
        status: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.pwa_foundation_service.list_installations(
            gw,
            limit=limit,
            status=status,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def register_app_installation(
        self,
        gw: AdminGatewayLike,
        *,
        actor: str = 'admin',
        user_key: str,
        platform: str = 'pwa',
        device_label: str = '',
        push_capable: bool = False,
        notification_permission: str = 'default',
        deep_link_base: str = '/ui/',
        metadata: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.pwa_foundation_service.register_installation(
            gw,
            actor=actor,
            user_key=user_key,
            platform=platform,
            device_label=device_label,
            push_capable=push_capable,
            notification_permission=notification_permission,
            deep_link_base=deep_link_base,
            metadata=metadata or {},
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def list_app_notifications(
        self,
        gw: AdminGatewayLike,
        *,
        limit: int = 50,
        installation_id: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.pwa_foundation_service.list_notifications(
            gw,
            limit=limit,
            installation_id=installation_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def create_app_notification(
        self,
        gw: AdminGatewayLike,
        *,
        actor: str = 'admin',
        title: str,
        body: str,
        category: str = 'operator',
        installation_id: str | None = None,
        target_path: str = '/ui/?tab=operator',
        require_interaction: bool = False,
        metadata: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.pwa_foundation_service.create_notification(
            gw,
            actor=actor,
            title=title,
            body=body,
            category=category,
            installation_id=installation_id,
            target_path=target_path,
            require_interaction=require_interaction,
            metadata=metadata or {},
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def list_app_deep_links(
        self,
        gw: AdminGatewayLike,
        *,
        limit: int = 50,
        status: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.pwa_foundation_service.list_deep_links(
            gw,
            limit=limit,
            status=status,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def create_app_deep_link(
        self,
        gw: AdminGatewayLike,
        *,
        actor: str = 'admin',
        view: str,
        target_type: str,
        target_id: str,
        params: dict[str, Any] | None = None,
        expires_in_s: int = 3600,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.pwa_foundation_service.create_deep_link(
            gw,
            actor=actor,
            view=view,
            target_type=target_type,
            target_id=target_id,
            params=params or {},
            expires_in_s=expires_in_s,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def resolve_app_deep_link(self, gw: AdminGatewayLike, *, link_token: str) -> dict[str, Any]:
        return self.pwa_foundation_service.resolve_deep_link(gw, link_token=link_token)


    def list_canvas_documents(
        self,
        gw: AdminGatewayLike,
        *,
        limit: int = 50,
        status: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.live_canvas_service.list_documents(
            gw,
            limit=limit,
            status=status,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def create_canvas_document(
        self,
        gw: AdminGatewayLike,
        *,
        actor: str = 'admin',
        title: str,
        description: str = '',
        status: str = 'active',
        metadata: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.live_canvas_service.create_document(
            gw,
            actor=actor,
            title=title,
            description=description,
            status=status,
            metadata=metadata or {},
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def get_canvas_document(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.live_canvas_service.get_document(
            gw,
            canvas_id=canvas_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def upsert_canvas_node(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        actor: str = 'admin',
        node_id: str | None = None,
        node_type: str,
        label: str,
        position_x: float = 0.0,
        position_y: float = 0.0,
        width: float = 240.0,
        height: float = 120.0,
        data: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.live_canvas_service.upsert_node(
            gw,
            canvas_id=canvas_id,
            actor=actor,
            node_id=node_id,
            node_type=node_type,
            label=label,
            position_x=position_x,
            position_y=position_y,
            width=width,
            height=height,
            data=data or {},
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def upsert_canvas_edge(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        actor: str = 'admin',
        edge_id: str | None = None,
        source_node_id: str,
        target_node_id: str,
        label: str = '',
        edge_type: str = 'default',
        data: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.live_canvas_service.upsert_edge(
            gw,
            canvas_id=canvas_id,
            actor=actor,
            edge_id=edge_id,
            source_node_id=source_node_id,
            target_node_id=target_node_id,
            label=label,
            edge_type=edge_type,
            data=data or {},
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def save_canvas_view(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        actor: str = 'admin',
        name: str,
        view_id: str | None = None,
        layout: dict[str, Any] | None = None,
        filters: dict[str, Any] | None = None,
        is_default: bool = False,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.live_canvas_service.save_view(
            gw,
            canvas_id=canvas_id,
            actor=actor,
            name=name,
            view_id=view_id,
            layout=layout or {},
            filters=filters or {},
            is_default=is_default,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def update_canvas_presence(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        actor: str = 'admin',
        user_key: str,
        cursor_x: float = 0.0,
        cursor_y: float = 0.0,
        selected_node_id: str | None = None,
        status: str = 'active',
        metadata: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.live_canvas_service.update_presence(
            gw,
            canvas_id=canvas_id,
            actor=actor,
            user_key=user_key,
            cursor_x=cursor_x,
            cursor_y=cursor_y,
            selected_node_id=selected_node_id,
            status=status,
            metadata=metadata or {},
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def list_canvas_events(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        limit: int = 50,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.live_canvas_service.list_events(
            gw,
            canvas_id=canvas_id,
            limit=limit,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def add_canvas_comment(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        actor: str = 'admin',
        body: str,
        node_id: str | None = None,
        status: str = 'active',
        metadata: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.live_canvas_service.add_comment(
            gw,
            canvas_id=canvas_id,
            actor=actor,
            body=body,
            node_id=node_id,
            status=status,
            metadata=metadata or {},
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def list_canvas_comments(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        limit: int = 50,
        status: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.live_canvas_service.list_comments(
            gw,
            canvas_id=canvas_id,
            limit=limit,
            status=status,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def create_canvas_snapshot(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        actor: str = 'admin',
        label: str = '',
        snapshot_kind: str = 'manual',
        view_id: str | None = None,
        selected_node_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.live_canvas_service.create_snapshot(
            gw,
            canvas_id=canvas_id,
            actor=actor,
            label=label,
            snapshot_kind=snapshot_kind,
            view_id=view_id,
            selected_node_id=selected_node_id,
            metadata=metadata or {},
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def list_canvas_snapshots(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        limit: int = 50,
        snapshot_kind: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.live_canvas_service.list_snapshots(
            gw,
            canvas_id=canvas_id,
            limit=limit,
            snapshot_kind=snapshot_kind,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def share_canvas_view(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        actor: str = 'admin',
        view_id: str | None = None,
        label: str = '',
        selected_node_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.live_canvas_service.share_view(
            gw,
            canvas_id=canvas_id,
            actor=actor,
            view_id=view_id,
            label=label,
            selected_node_id=selected_node_id,
            metadata=metadata or {},
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def compare_canvas_snapshots(
        self,
        gw: AdminGatewayLike,
        *,
        snapshot_a_id: str,
        snapshot_b_id: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.live_canvas_service.compare_snapshots(
            gw,
            snapshot_a_id=snapshot_a_id,
            snapshot_b_id=snapshot_b_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def list_canvas_presence_events(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        limit: int = 50,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.live_canvas_service.list_presence_events(
            gw,
            canvas_id=canvas_id,
            limit=limit,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def save_canvas_overlay_state(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        actor: str = 'admin',
        state_key: str = 'default',
        toggles: dict[str, Any] | None = None,
        inspector: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.live_canvas_service.save_overlay_state(
            gw,
            canvas_id=canvas_id,
            actor=actor,
            state_key=state_key,
            toggles=toggles or {},
            inspector=inspector or {},
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def get_canvas_operational_overlays(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        selected_node_id: str | None = None,
        state_key: str = 'default',
        limit: int = 50,
        toggles: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.live_canvas_service.get_operational_overlays(
            gw,
            canvas_id=canvas_id,
            selected_node_id=selected_node_id,
            state_key=state_key,
            limit=limit,
            toggles=toggles,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def list_canvas_operational_views(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.live_canvas_service.list_operational_views(
            gw,
            canvas_id=canvas_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def get_canvas_baseline_promotion_board(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        limit: int = 10,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.live_canvas_service.get_baseline_promotion_board(
            gw,
            canvas_id=canvas_id,
            limit=limit,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def get_canvas_runtime_board(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        limit: int = 10,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.live_canvas_service.get_runtime_board(
            gw,
            canvas_id=canvas_id,
            limit=limit,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def inspect_canvas_node(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        node_id: str,
        state_key: str = 'default',
        limit: int = 50,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.live_canvas_service.get_node_inspector(
            gw,
            canvas_id=canvas_id,
            node_id=node_id,
            state_key=state_key,
            limit=limit,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def execute_canvas_node_action(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        node_id: str,
        action: str,
        actor: str = 'admin',
        reason: str = '',
        payload: dict[str, Any] | None = None,
        user_role: str = 'operator',
        user_key: str = '',
        session_id: str = 'canvas',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.live_canvas_service.execute_node_action(
            gw,
            canvas_id=canvas_id,
            node_id=node_id,
            action=action,
            actor=actor,
            reason=reason,
            payload=payload or {},
            user_role=user_role,
            user_key=user_key,
            session_id=session_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def canvas_node_timeline(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        node_id: str,
        limit: int = 50,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self.live_canvas_service.get_node_timeline(
            gw,
            canvas_id=canvas_id,
            node_id=node_id,
            limit=limit,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
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

    def verify_reproducible_package_manifest(self, *, manifest_path: str) -> dict[str, Any]:
        return self.packaging_hardening_service.verify_reproducible_manifest(manifest_path=manifest_path)

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
