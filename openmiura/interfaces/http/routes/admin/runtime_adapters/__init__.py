"""admin.runtime_adapters — sub-package aggregator."""

from __future__ import annotations

from fastapi import APIRouter

from . import dispatches, governance, recovery, runtimes

router = APIRouter()
router.include_router(dispatches.router)
router.include_router(governance.router)
router.include_router(recovery.router)
router.include_router(runtimes.router)
