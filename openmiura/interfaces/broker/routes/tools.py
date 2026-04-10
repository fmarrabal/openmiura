from __future__ import annotations

import queue
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from openmiura.interfaces.broker.common import (
    audit_sensitive,
    broker_auth_context,
    enforce_rate_limit,
    metrics_summary,
    publish,
    require_broker,
    resolve_user_key,
    session_event,
    tool_catalog,
)
from openmiura.interfaces.broker.schemas import BrokerToolCallRequest
from openmiura.tools.runtime import ToolConfirmationRequired, ToolError


def build_tools_router() -> APIRouter:
    router = APIRouter(tags=["broker"])

    @router.get("/capabilities")
    def broker_capabilities(request: Request, agent_id: str = Query(default="default")):
        gw = require_broker(request)
        broker_cfg = gw.settings.broker
        mcp_cfg = getattr(gw.settings, "mcp", None)
        return {
            "ok": True,
            "transport": "http-broker",
            "mcp_compatible": True,
            "agent_id": agent_id,
            "tools": tool_catalog(gw, agent_id),
            "resources": [
                {
                    "name": "memory_search",
                    "uri_template": "memory://search?q={query}",
                    "http_path": f"{getattr(broker_cfg, 'base_path', '/broker')}/memory/search",
                }
            ],
            "surfaces": {
                "http_broker": bool(getattr(broker_cfg, "enabled", False)),
                "mcp": bool(mcp_cfg and getattr(mcp_cfg, "enabled", False)),
            },
            "ui": {
                "sessions": True,
                "history": True,
                "pending_confirmations": True,
                "metrics_summary": True,
                "agents": True,
                "skills": True,
                "terminal_stream": True,
                "tool_calls": True,
                "live_events": True,
                "rbac": True,
            },
        }

    @router.get("/metrics/summary")
    def broker_metrics_summary(request: Request):
        gw, auth_ctx = broker_auth_context(request)
        audit_sensitive(gw, action="metrics_summary", auth_ctx=auth_ctx, status="ok")
        return metrics_summary(gw)

    @router.get("/agents")
    def broker_agents(request: Request):
        gw, auth_ctx = broker_auth_context(request)
        audit_sensitive(gw, action="agents_list", auth_ctx=auth_ctx, status="ok")
        router_obj = getattr(gw, "router", None)
        runtime = getattr(gw, "runtime", None)
        skill_loader = getattr(runtime, "skill_loader", None)
        items: list[dict[str, Any]] = []
        for agent_id in (router_obj.available_agents() if router_obj else []):
            base = dict(gw.settings.agents.get(agent_id, {}) or {})
            extended = runtime._agent_cfg(agent_id) if runtime is not None else base
            items.append(
                {
                    "agent_id": agent_id,
                    "description": str(base.get("description") or ""),
                    "model": str(base.get("model") or gw.settings.llm.model),
                    "skills": list(base.get("skills") or []),
                    "required_permissions": list(extended.get("required_permissions") or []),
                    "tools": list(extended.get("allowed_tools") or extended.get("tools") or []),
                }
            )
        return {
            "ok": True,
            "items": items,
            "skills": skill_loader.catalog() if skill_loader is not None else [],
        }

    @router.get("/agents/{agent_id}/tools")
    def broker_agent_tools(agent_id: str, request: Request):
        gw, auth_ctx = broker_auth_context(request)
        audit_sensitive(gw, action="agent_tools_list", auth_ctx=auth_ctx, status="ok", target=agent_id)
        return {"ok": True, "agent_id": agent_id, "tools": tool_catalog(gw, agent_id, auth_ctx)}

    @router.get("/tools")
    def broker_tools(request: Request, agent_id: str = Query(default="default")):
        gw, auth_ctx = broker_auth_context(request)
        audit_sensitive(gw, action="tools_list", auth_ctx=auth_ctx, status="ok", target=agent_id)
        return {"ok": True, "transport": "http-broker", "agent_id": agent_id, "tools": tool_catalog(gw, agent_id, auth_ctx)}

    @router.post("/tools/call")
    def broker_tool_call(payload: BrokerToolCallRequest, request: Request):
        gw, auth_ctx = broker_auth_context(request)
        from openmiura.interfaces.broker.common import require_csrf

        require_csrf(request, auth_ctx)
        enforce_rate_limit(request, auth_ctx, bucket="tools_call", limit_per_minute=int(getattr(gw.settings.broker, "rate_limit_per_minute", 120) or 120))
        runtime = getattr(gw, "tools", None)
        if runtime is None:
            raise HTTPException(status_code=503, detail="Tool runtime not configured")
        tool_name = str(payload.tool_name or payload.name or "").strip()
        if not tool_name:
            raise HTTPException(status_code=422, detail="tool_name is required")
        args = payload.arguments if payload.arguments else (payload.args or {})
        user_key = resolve_user_key(auth_ctx, payload.user_key)
        session_id = payload.session_id or f"broker:{user_key}:{payload.agent_id}"
        try:
            result = runtime.run_tool(
                agent_id=payload.agent_id,
                session_id=session_id,
                user_key=user_key,
                tool_name=tool_name,
                args=args,
                confirmed=bool(payload.confirmed),
            )
            publish(gw, "tool_call_result", session_id=session_id, user_key=user_key, agent_id=payload.agent_id, tool_name=tool_name, ok=True, result=result)
            audit_sensitive(gw, action="tool_call", auth_ctx=auth_ctx, status="ok", target=tool_name, session_id=session_id, details={"agent_id": payload.agent_id})
            return {"ok": True, "transport": "http-broker", "tool_name": tool_name, "session_id": session_id, "result": result}
        except ToolConfirmationRequired as exc:
            pending = getattr(gw, "pending_confirmations", None)
            if pending is not None:
                pending.set(
                    session_id,
                    user_key=user_key,
                    agent_id=payload.agent_id,
                    tool_name=exc.tool_name,
                    args=exc.args,
                    channel="broker",
                    channel_user_id=user_key,
                )
            publish(gw, "confirmation_pending", session_id=session_id, user_key=user_key, agent_id=payload.agent_id, tool_name=exc.tool_name, args=exc.args)
            audit_sensitive(gw, action="tool_call_confirmation_required", auth_ctx=auth_ctx, status="pending", target=exc.tool_name, session_id=session_id, details={"agent_id": payload.agent_id})
            return JSONResponse(status_code=409, content={"ok": False, "requires_confirmation": True, "tool_name": exc.tool_name, "session_id": session_id, "arguments": exc.args})
        except ToolError as exc:
            audit_sensitive(gw, action="tool_call_denied", auth_ctx=auth_ctx, status="denied", target=tool_name, session_id=session_id, details={"reason": str(exc)})
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    @router.get("/tool-calls")
    def broker_tool_calls(request: Request, user_key: str | None = Query(default=None), session_id: str | None = Query(default=None), limit: int = Query(default=100, ge=1, le=300)):
        gw, auth_ctx = broker_auth_context(request)
        effective_user_key = resolve_user_key(auth_ctx, user_key, fallback="")
        if auth_ctx.get("role") not in {"admin", "operator"}:
            effective_user_key = auth_ctx.get("user_key") or effective_user_key
        items = gw.audit.list_tool_calls(limit=limit, session_id=session_id, user_key=effective_user_key or None)
        return {"ok": True, "items": items}

    @router.get("/stream/live")
    def broker_live_stream(request: Request, session_id: str | None = Query(default=None), user_key: str | None = Query(default=None), once: bool = Query(default=False)):
        gw, auth_ctx = broker_auth_context(request)
        bus = getattr(gw, "realtime_bus", None)
        if bus is None:
            raise HTTPException(status_code=503, detail="Realtime bus not configured")
        token_user = auth_ctx.get("user_key")
        is_admin_like = auth_ctx.get("role") in {"admin", "operator"} or auth_ctx.get("mode") == "broker-token"
        q = bus.subscribe()

        def _allowed(event: dict[str, Any]) -> bool:
            if session_id and event.get("session_id") != session_id:
                return False
            filter_user = user_key or token_user
            if filter_user and event.get("user_key") not in {None, filter_user}:
                return False
            if not is_admin_like and token_user and event.get("user_key") not in {None, token_user}:
                return False
            return True

        def _gen():
            yield session_event("connected", role=auth_ctx.get("role"), user_key=token_user, permissions=list(auth_ctx.get("permissions") or []))
            if once:
                bus.unsubscribe(q)
                return
            try:
                while True:
                    try:
                        event = q.get(timeout=15.0)
                    except queue.Empty:
                        yield session_event("heartbeat", ts=time.time())
                        continue
                    if _allowed(event):
                        yield session_event(event.get("type", "message"), **event)
                        if once:
                            break
            finally:
                bus.unsubscribe(q)

        return StreamingResponse(_gen(), media_type="text/event-stream")

    return router
