"""admin — aggregating package for the openMiura admin HTTP API.

Sub-routers under this package implement one bounded domain each
(canvas, runtime, runtime_adapters, voice, evaluations, release,
workflows, approvals, cost_governance, governance, operator, secrets,
apps, system, core). The package-level ``router`` mounts all of them.
"""

from __future__ import annotations

from fastapi import APIRouter

from . import (
    apps,
    approvals,
    canvas,
    channels_test,
    core,
    cost_governance,
    evaluations,
    governance,
    operator,
    release,
    runtime,
    runtime_adapters,
    secrets,
    system,
    voice,
    workflows
)
from ._models import (
    AdminMemoryDeleteRequest,
    AdminMemorySearchBody,
    EvaluationRunRequest,
    IdentityLinkRequest,
    PolicyExplainRequest,
)

router = APIRouter()
router.include_router(apps.router)
router.include_router(approvals.router)
router.include_router(canvas.router)
router.include_router(channels_test.router)
router.include_router(core.router)
router.include_router(cost_governance.router)
router.include_router(evaluations.router)
router.include_router(governance.router)
router.include_router(operator.router)
router.include_router(release.router)
router.include_router(runtime.router)
router.include_router(runtime_adapters.router)
router.include_router(secrets.router)
router.include_router(system.router)
router.include_router(voice.router)
router.include_router(workflows.router)

__all__ = [
    "router",
    "AdminMemoryDeleteRequest",
    "AdminMemorySearchBody",
    "EvaluationRunRequest",
    "IdentityLinkRequest",
    "PolicyExplainRequest",
]
