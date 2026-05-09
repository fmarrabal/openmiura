"""openmiura.application.admin.service._operator_mixin

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


class _AdminServiceOperatorMixin:
    """Mixin: operator methods on AdminService."""

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

