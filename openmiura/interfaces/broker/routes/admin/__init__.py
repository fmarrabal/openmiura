"""``build_admin_router`` aggregates broker admin sub-routes,
one module per bounded domain.
"""
from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from openmiura.application.admin import AdminService
from openmiura.application.auth.service import AuthService
from openmiura.application.tenancy.service import TenancyService
from openmiura.interfaces.broker.common import (
    audit_sensitive,
    metrics_summary,
    require_csrf,
    require_permission,
)


from . import _apps
from . import _canvas
from . import _config_center
from . import _core
from . import _costs
from . import _evaluations
from . import _governance
from . import _openclaw_a
from . import _openclaw_b
from . import _operator
from . import _releases
from . import _replay
from . import _secrets
from . import _system
from . import _voice


def build_admin_router() -> APIRouter:
    router = APIRouter(tags=["broker"])
    tenancy_service = TenancyService()
    _apps.register_routes(router, tenancy_service)
    _canvas.register_routes(router, tenancy_service)
    _config_center.register_routes(router, tenancy_service)
    _core.register_routes(router, tenancy_service)
    _costs.register_routes(router, tenancy_service)
    _evaluations.register_routes(router, tenancy_service)
    _governance.register_routes(router, tenancy_service)
    _openclaw_a.register_routes(router, tenancy_service)
    _openclaw_b.register_routes(router, tenancy_service)
    _operator.register_routes(router, tenancy_service)
    _releases.register_routes(router, tenancy_service)
    _replay.register_routes(router, tenancy_service)
    _secrets.register_routes(router, tenancy_service)
    _system.register_routes(router, tenancy_service)
    _voice.register_routes(router, tenancy_service)
    return router
