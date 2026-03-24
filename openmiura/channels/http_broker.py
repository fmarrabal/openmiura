from __future__ import annotations

"""Legacy compatibility shim for the HTTP broker.

The broker transport has been split into vertical route modules under
``openmiura.interfaces.broker`` following the roadmap's Phase 1 broker HTTP v1
workstream. This module intentionally preserves the historic import surface:

- ``build_broker_router`` remains available here for existing imports.
- request/response models remain re-exported for compatibility.
- ``process_message`` stays patchable from tests and callers.

New code should import from ``openmiura.interfaces.broker``.
"""

from openmiura.pipeline import process_message
from openmiura.interfaces.broker.router import build_broker_router
from openmiura.interfaces.broker.schemas import (
    BrokerAuthSessionRevokeRequest,
    BrokerAuthSessionRotateRequest,
    BrokerAuthUserCreateRequest,
    BrokerChatRequest,
    BrokerChatResponse,
    BrokerLoginRequest,
    BrokerPendingDecisionRequest,
    BrokerTerminalStreamRequest,
    BrokerTokenCreateRequest,
    BrokerTokenRevokeRequest,
    BrokerTokenRotateRequest,
    BrokerToolCallRequest,
)

__all__ = [
    "BrokerAuthSessionRevokeRequest",
    "BrokerAuthSessionRotateRequest",
    "BrokerAuthUserCreateRequest",
    "BrokerChatRequest",
    "BrokerChatResponse",
    "BrokerLoginRequest",
    "BrokerPendingDecisionRequest",
    "BrokerTerminalStreamRequest",
    "BrokerTokenCreateRequest",
    "BrokerTokenRevokeRequest",
    "BrokerTokenRotateRequest",
    "BrokerToolCallRequest",
    "build_broker_router",
    "process_message",
]
