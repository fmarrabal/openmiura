"""openmiura.interfaces.http.routes.science

Public HTTP surface for the **science** profile — the operator
who interacts with the agent day-to-day, not the SRE who
configures the platform.

Currently exposes a single sub-domain (uploads); future
additions (chat-history exports, draft pinning, …) live here.

Authentication: every endpoint under ``/science/*`` reuses the
admin-token gate. The UI v2 admin auth dropdown already supplies
the token; if a future deployment wants a softer auth on
``/science/*`` it should land as a dedicated session-token check
here, not as a relaxation of the existing admin policy.
"""

from __future__ import annotations

from fastapi import APIRouter

from .uploads import router as _uploads_router

router = APIRouter()
router.include_router(_uploads_router)

__all__ = ["router"]
