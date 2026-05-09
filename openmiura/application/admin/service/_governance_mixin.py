"""openmiura.application.admin.service._governance_mixin

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


class _AdminServiceGovernanceMixin:
    """Mixin: governance methods on AdminService."""

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

