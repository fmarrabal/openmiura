from __future__ import annotations

from fastapi import APIRouter

from openmiura.interfaces.broker.routes.admin import build_admin_router
from openmiura.interfaces.broker.routes.auth import build_auth_router
from openmiura.interfaces.broker.routes.chat import build_chat_router
from openmiura.interfaces.broker.routes.state import build_state_router
from openmiura.interfaces.broker.routes.tools import build_tools_router
from openmiura.interfaces.broker.routes.workflows import build_workflow_router


def build_broker_router() -> APIRouter:
    router = APIRouter(tags=["broker"])
    router.include_router(build_auth_router())
    router.include_router(build_tools_router())
    router.include_router(build_state_router())
    router.include_router(build_chat_router())
    router.include_router(build_workflow_router())
    router.include_router(build_admin_router())
    return router
