"""``AdminService`` aggregates a set of mixins, one per bounded admin
sub-domain.

The original implementation was a single 6,734-line class file.
After the split:

- ``__init__.py`` (this file) keeps the class signature, the
  constructor and the wiring of the injected services.
- Each ``_<domain>_mixin.py`` module owns the methods of one
  sub-domain.

External callers are unaffected: ``AdminService`` exposes the same
method surface, instantiated the same way, with the same constructor
parameters.

Following the late-binding pattern from the canvas split, each
mixin module declares ``AdminService = None`` at module scope; this
file rebinds it once the final class is defined, so internal
``AdminService.foo(...)`` references resolve at call time without
circular imports.
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

from openmiura.application.admin.service._apps_mixin import _AdminServiceAppsMixin
from openmiura.application.admin.service._canvas_mixin import _AdminServiceCanvasMixin
from openmiura.application.admin.service._core_mixin import _AdminServiceCoreMixin
from openmiura.application.admin.service._cost_governance_mixin import _AdminServiceCostGovernanceMixin
from openmiura.application.admin.service._evaluations_mixin import _AdminServiceEvaluationsMixin
from openmiura.application.admin.service._governance_mixin import _AdminServiceGovernanceMixin
from openmiura.application.admin.service._helpers_mixin import _AdminServiceHelpersMixin
from openmiura.application.admin.service._memory_mixin import _AdminServiceMemoryMixin
from openmiura.application.admin.service._operator_mixin import _AdminServiceOperatorMixin
from openmiura.application.admin.service._release_packaging_mixin import _AdminServiceReleasePackagingMixin
from openmiura.application.admin.service._runtime_adapters_a_mixin import _AdminServiceRuntimeAdaptersAMixin
from openmiura.application.admin.service._runtime_adapters_b_mixin import _AdminServiceRuntimeAdaptersBMixin
from openmiura.application.admin.service._secrets_mixin import _AdminServiceSecretsMixin
from openmiura.application.admin.service._sessions_mixin import _AdminServiceSessionsMixin
from openmiura.application.admin.service._system_mixin import _AdminServiceSystemMixin
from openmiura.application.admin.service._voice_mixin import _AdminServiceVoiceMixin
from openmiura.application.admin.service._workflows_mixin import _AdminServiceWorkflowsMixin


class AdminService(
    _AdminServiceAppsMixin,
    _AdminServiceCanvasMixin,
    _AdminServiceCoreMixin,
    _AdminServiceCostGovernanceMixin,
    _AdminServiceEvaluationsMixin,
    _AdminServiceGovernanceMixin,
    _AdminServiceHelpersMixin,
    _AdminServiceMemoryMixin,
    _AdminServiceOperatorMixin,
    _AdminServiceReleasePackagingMixin,
    _AdminServiceRuntimeAdaptersAMixin,
    _AdminServiceRuntimeAdaptersBMixin,
    _AdminServiceSecretsMixin,
    _AdminServiceSessionsMixin,
    _AdminServiceSystemMixin,
    _AdminServiceVoiceMixin,
    _AdminServiceWorkflowsMixin
):
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



from openmiura.application.admin.service import _apps_mixin
from openmiura.application.admin.service import _canvas_mixin
from openmiura.application.admin.service import _core_mixin
from openmiura.application.admin.service import _cost_governance_mixin
from openmiura.application.admin.service import _evaluations_mixin
from openmiura.application.admin.service import _governance_mixin
from openmiura.application.admin.service import _helpers_mixin
from openmiura.application.admin.service import _memory_mixin
from openmiura.application.admin.service import _operator_mixin
from openmiura.application.admin.service import _release_packaging_mixin
from openmiura.application.admin.service import _runtime_adapters_a_mixin
from openmiura.application.admin.service import _runtime_adapters_b_mixin
from openmiura.application.admin.service import _secrets_mixin
from openmiura.application.admin.service import _sessions_mixin
from openmiura.application.admin.service import _system_mixin
from openmiura.application.admin.service import _voice_mixin
from openmiura.application.admin.service import _workflows_mixin

# Late-bind AdminService into each mixin module so the
# ``@staticmethod``s that internally call ``AdminService.foo(...)``
# resolve the reference at call time.
for _mod in (
    _apps_mixin,
    _canvas_mixin,
    _core_mixin,
    _cost_governance_mixin,
    _evaluations_mixin,
    _governance_mixin,
    _helpers_mixin,
    _memory_mixin,
    _operator_mixin,
    _release_packaging_mixin,
    _runtime_adapters_a_mixin,
    _runtime_adapters_b_mixin,
    _secrets_mixin,
    _sessions_mixin,
    _system_mixin,
    _voice_mixin,
    _workflows_mixin
):
    _mod.AdminService = AdminService
del _mod
