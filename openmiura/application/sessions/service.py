from __future__ import annotations

from typing import Any

from openmiura.core.contracts import AdminGatewayLike


class SessionService:
    def list_sessions(
        self,
        gw: AdminGatewayLike,
        *,
        limit: int,
        channel: str | None = None,
    ) -> dict[str, Any]:
        items = gw.audit.list_sessions(limit=limit, channel=channel)
        return {"ok": True, "items": items}
