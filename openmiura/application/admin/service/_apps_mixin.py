"""openmiura.application.admin.service._apps_mixin

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


class _AdminServiceAppsMixin:
    """Mixin: apps methods on AdminService."""

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

