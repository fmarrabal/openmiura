from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from openmiura.interfaces.broker.common import (
    audit_sensitive,
    broker_auth_context,
    enforce_rate_limit,
    publish,
    require_csrf,
    resolve_user_key,
)
from openmiura.interfaces.broker.schemas import BrokerPendingDecisionRequest


def build_state_router() -> APIRouter:
    router = APIRouter(tags=["broker"])

    @router.get("/memory/search")
    def broker_memory_search(request: Request, q: str = Query(..., min_length=1), user_key: str | None = Query(default=None), top_k: int = Query(default=10, ge=1, le=100)):
        gw, auth_ctx = broker_auth_context(request)
        enforce_rate_limit(request, auth_ctx, bucket="memory_search", limit_per_minute=int(getattr(gw.settings.broker, "rate_limit_per_minute", 120) or 120))
        memory = getattr(gw, "memory", None)
        effective_user_key = resolve_user_key(auth_ctx, user_key)
        if memory is None:
            return {"ok": True, "disabled": True, "items": []}
        return {"ok": True, "transport": "http-broker", "resource_uri": f"memory://search?q={q}", "items": memory.recall(user_key=effective_user_key, query=q, top_k=top_k)}

    @router.get("/sessions")
    def broker_sessions(request: Request, user_key: str | None = Query(default=None), limit: int = Query(default=50, ge=1, le=200), channel: str | None = Query(default=None)):
        gw, auth_ctx = broker_auth_context(request)
        effective_user_key = resolve_user_key(auth_ctx, user_key, fallback="")
        sessions = gw.audit.list_sessions(limit=limit, channel=channel)
        if effective_user_key:
            sessions = [s for s in sessions if s.get("user_id") == effective_user_key]
        return {"ok": True, "items": sessions}

    @router.get("/sessions/{session_id}/messages")
    def broker_session_messages(session_id: str, request: Request, limit: int = Query(default=200, ge=1, le=500)):
        gw, auth_ctx = broker_auth_context(request)
        sessions = {item["session_id"]: item for item in gw.audit.list_sessions(limit=500)}
        session_meta = sessions.get(session_id)
        if session_meta is None:
            raise HTTPException(status_code=404, detail="Unknown session_id")
        token_user = auth_ctx.get("user_key")
        if token_user and session_meta.get("user_id") != token_user:
            raise HTTPException(status_code=403, detail="Cannot inspect another user's session")
        items = gw.audit.get_session_messages(session_id, limit=limit)
        return {"ok": True, "session": session_meta, "items": items}

    @router.get("/confirmations")
    def broker_confirmations(request: Request, user_key: str | None = Query(default=None)):
        gw, auth_ctx = broker_auth_context(request)
        audit_sensitive(gw, action="confirmations_list", auth_ctx=auth_ctx, status="ok", target=str(user_key or auth_ctx.get("user_key") or ""))
        effective_user_key = resolve_user_key(auth_ctx, user_key, fallback="")
        pending = getattr(gw, "pending_confirmations", None)
        items = pending.list_items(user_key=effective_user_key or None) if pending is not None else []
        if auth_ctx.get("mode") == "user-token" and not effective_user_key:
            items = []
        return {"ok": True, "items": items}

    @router.post("/confirmations/{session_id}/confirm")
    def broker_confirm(session_id: str, payload: BrokerPendingDecisionRequest, request: Request):
        gw, auth_ctx = broker_auth_context(request)
        require_csrf(request, auth_ctx)
        pending = getattr(gw, "pending_confirmations", None)
        runtime = getattr(gw, "tools", None)
        if pending is None or runtime is None:
            raise HTTPException(status_code=503, detail="Pending confirmations not configured")
        item = pending.get(session_id)
        if item is None:
            raise HTTPException(status_code=404, detail="No pending confirmation")
        token_user = auth_ctx.get("user_key")
        if token_user and item.get("user_key") != token_user:
            raise HTTPException(status_code=403, detail="Cannot confirm another user's action")
        item = pending.consume(session_id, user_key=token_user or item.get("user_key"))
        if item is None:
            raise HTTPException(status_code=404, detail="No pending confirmation")
        result = runtime.run_tool(
            agent_id=str(payload.agent_id or item.get("agent_id") or "default"),
            session_id=session_id,
            user_key=str(item.get("user_key") or token_user or "broker:local"),
            tool_name=str(item.get("tool_name") or ""),
            args=dict(item.get("args") or {}),
            confirmed=True,
        )
        publish(gw, "confirmation_resolved", session_id=session_id, user_key=str(item.get("user_key") or token_user or ""), decision="confirm", result=result)
        audit_sensitive(gw, action="confirmation_confirm", auth_ctx=auth_ctx, status="ok", target=session_id, session_id=session_id, details={"tool_name": item.get("tool_name")})
        return {"ok": True, "session_id": session_id, "result": result}

    @router.post("/confirmations/{session_id}/cancel")
    def broker_cancel_confirmation(session_id: str, request: Request):
        gw, auth_ctx = broker_auth_context(request)
        require_csrf(request, auth_ctx)
        pending = getattr(gw, "pending_confirmations", None)
        if pending is None:
            raise HTTPException(status_code=503, detail="Pending confirmations not configured")
        token_user = auth_ctx.get("user_key")
        cancelled = pending.cancel(session_id, user_key=token_user) if token_user else pending.cancel(session_id)
        if not cancelled:
            raise HTTPException(status_code=404, detail="No pending confirmation")
        publish(gw, "confirmation_resolved", session_id=session_id, user_key=token_user, decision="cancel")
        audit_sensitive(gw, action="confirmation_cancel", auth_ctx=auth_ctx, status="ok", target=session_id, session_id=session_id)
        return {"ok": True, "session_id": session_id, "cancelled": True}

    return router
