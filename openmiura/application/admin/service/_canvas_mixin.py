"""openmiura.application.admin.service._canvas_mixin

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


class _AdminServiceCanvasMixin:
    """Mixin: canvas methods on AdminService."""

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

