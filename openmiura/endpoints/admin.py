"""Compatibility shim for the admin HTTP routes.

The canonical implementation now lives under ``openmiura.interfaces.http.routes``.
"""

from openmiura.interfaces.http.routes.admin import (
    AdminMemoryDeleteRequest,
    AdminMemorySearchBody,
    EvaluationRunRequest,
    IdentityLinkRequest,
    PolicyExplainRequest,
    router,
)

__all__ = [
    "router",
    "AdminMemorySearchBody",
    "AdminMemoryDeleteRequest",
    "EvaluationRunRequest",
    "IdentityLinkRequest",
    "PolicyExplainRequest",
]
