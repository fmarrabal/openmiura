"""openmiura.application.admin.service._sessions_mixin

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


class _AdminServiceSessionsMixin:
    """Mixin: sessions methods on AdminService."""

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

    def _rule_identity(self, section: str, rule: Any, idx: int) -> str:
        if isinstance(rule, dict) and str(rule.get("name") or "").strip():
            return f"{section}:{str(rule.get('name')).strip()}"
        payload = json.dumps(rule, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
        return f"{section}:{idx}:{digest}"

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

