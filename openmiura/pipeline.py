from __future__ import annotations

import json
import time
import uuid

from fastapi import HTTPException

from openmiura.commands import handle_commands, handle_tool_commands
from openmiura.core.schema import InboundMessage, OutboundMessage
from openmiura.gateway import Gateway, telegram_ids_from_msg
from openmiura.observability import observe_request, record_error

_ALIASES_HELP = frozenset([
    "palabras clave",
    "comandos",
    "dime los comandos",
    "lista de comandos",
    "qué comandos",
    "que comandos",
    "help",
    "ayuda",
    "commands",
])


def _memory_trace_payload(hits: list[dict[str, object]] | None) -> dict[str, object]:
    rows = list(hits or [])
    return {
        "hit_count": len(rows),
        "items": [
            {
                "id": item.get("id"),
                "kind": item.get("kind"),
                "score": round(float(item.get("score") or 0.0), 6),
                "tier": item.get("tier"),
                "text_excerpt": str(item.get("text") or "")[:240],
            }
            for item in rows
        ],
    }


def _persist_decision_trace(
    gw: Gateway,
    *,
    trace_id: str,
    session_id: str,
    user_key: str,
    channel: str,
    agent_id: str,
    tenant_id: str | None,
    workspace_id: str | None,
    environment: str | None,
    trace: dict[str, object],
) -> None:
    audit = getattr(gw, "audit", None)
    if audit is None or not hasattr(audit, "log_decision_trace"):
        return
    usage = dict(trace.get("usage") or {})
    audit.log_decision_trace(
        trace_id=trace_id,
        session_id=session_id,
        user_key=user_key,
        channel=channel,
        agent_id=agent_id,
        request_text=str(trace.get("request_text") or ""),
        response_text=str(trace.get("response_text") or ""),
        status=str(trace.get("status") or "completed"),
        provider=str(trace.get("provider") or ""),
        model=str(trace.get("model") or ""),
        latency_ms=float(trace.get("latency_ms") or 0.0),
        estimated_cost=float(trace.get("estimated_cost") or 0.0),
        llm_calls=len(list(trace.get("llm_calls") or [])),
        input_tokens=int(usage.get("prompt_tokens") or 0),
        output_tokens=int(usage.get("completion_tokens") or 0),
        total_tokens=int(usage.get("total_tokens") or 0),
        context_json=json.dumps(trace.get("context") or {}, ensure_ascii=False),
        memory_json=json.dumps(trace.get("memory") or {}, ensure_ascii=False),
        tools_considered_json=json.dumps(trace.get("tools_considered") or [], ensure_ascii=False),
        tools_used_json=json.dumps(trace.get("tools_used") or [], ensure_ascii=False),
        policies_json=json.dumps(trace.get("policies_applied") or [], ensure_ascii=False),
        decisions_json=json.dumps(trace.get("decisions") or {}, ensure_ascii=False),
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        environment=environment,
    )
    realtime = getattr(gw, "realtime_bus", None)
    if realtime is not None:
        try:
            realtime.publish(
                "decision_trace_recorded",
                trace_id=trace_id,
                session_id=session_id,
                user_key=user_key,
                channel=channel,
                agent_id=agent_id,
                status=str(trace.get("status") or "completed"),
                latency_ms=float(trace.get("latency_ms") or 0.0),
                estimated_cost=float(trace.get("estimated_cost") or 0.0),
            )
        except Exception:
            pass


def process_message(gw: Gateway, msg: InboundMessage) -> OutboundMessage:
    if gw is None:
        raise HTTPException(status_code=503, detail="Service not initialized")

    channel_name = msg.channel or "http"
    try:
        with observe_request(channel_name):
            msg.channel = msg.channel or "http"

            if msg.channel == "telegram":
                chat_id, from_id = telegram_ids_from_msg(msg)
                if not gw.is_telegram_allowed(chat_id, from_id):
                    gw.audit.log_event(
                        direction="security",
                        channel="telegram",
                        user_id=msg.user_id,
                        session_id=msg.session_id or "unknown",
                        payload={"reason": "not_allowlisted", "chat_id": chat_id, "from_id": from_id, "text": msg.text},
                    )
                    return OutboundMessage(
                        channel=msg.channel,
                        user_id=msg.user_id,
                        session_id=msg.session_id or "denied",
                        agent_id="system",
                        text=gw.telegram_deny_message(),
                    )

            channel_user_id = msg.user_id
            user_key = gw.effective_user_key(channel_user_id)

            scope_meta = dict((msg.metadata or {}).get("_scope") or {})
            tenant_id = str(scope_meta.get("tenant_id") or "").strip() or None
            workspace_id = str(scope_meta.get("workspace_id") or "").strip() or None
            environment = str(scope_meta.get("environment") or "").strip() or None

            derived_session_id = gw.derive_session_id(msg, user_key)
            session_id = gw.audit.get_or_create_session(channel=msg.channel, user_id=user_key, session_id=derived_session_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

            trace_id = str(uuid.uuid4())
            llm_cfg = getattr(getattr(gw, "settings", None), "llm", None)
            trace_payload: dict[str, object] = {
                "request_text": msg.text,
                "response_text": "",
                "status": "received",
                "provider": str(getattr(llm_cfg, "provider", "") or ""),
                "model": str(getattr(llm_cfg, "model", "") or ""),
                "latency_ms": 0.0,
                "estimated_cost": 0.0,
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                "memory": {"hit_count": 0, "items": []},
                "tools_considered": [],
                "tools_used": [],
                "policies_applied": [],
                "llm_calls": [],
                "decisions": {},
                "context": {
                    "channel": msg.channel,
                    "tenant_id": tenant_id,
                    "workspace_id": workspace_id,
                    "environment": environment,
                    "message_length": len(msg.text or ""),
                    "metadata_keys": sorted(list((msg.metadata or {}).keys())),
                },
            }

            gw.audit.log_event(
                direction="in",
                channel=msg.channel,
                user_id=user_key,
                session_id=session_id,
                payload=msg.model_dump(),
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                environment=environment,
            )

            low_text = (msg.text or "").strip().lower()
            if any(alias in low_text for alias in _ALIASES_HELP):
                cmd_out = handle_commands(
                    gw,
                    channel=msg.channel,
                    channel_user_id=msg.user_id,
                    user_key=user_key,
                    session_id=session_id,
                    text="/help",
                    metadata=msg.metadata,
                )
                if cmd_out is not None:
                    gw.audit.log_event("out", msg.channel, msg.user_id, session_id, cmd_out.model_dump(), tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
                    return cmd_out

            cmd_out = handle_commands(
                gw,
                channel=msg.channel,
                channel_user_id=msg.user_id,
                user_key=user_key,
                session_id=session_id,
                text=msg.text,
                metadata=msg.metadata,
            )
            if cmd_out is not None:
                gw.audit.log_event("out", msg.channel, msg.user_id, session_id, cmd_out.model_dump(), tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
                return cmd_out

            gw.audit.append_message(session_id=session_id, role="user", content=msg.text)

            route_info = gw.router.route(channel=msg.channel, user_id=msg.user_id, text=msg.text, session_id=session_id)
            agent_id = route_info["agent_id"]

            policy = getattr(gw, "policy", None)
            if policy is not None:
                try:
                    agent_allowed = bool(policy.check_agent_access(user_key, agent_id))
                    trace_payload.setdefault("decisions", {})["agent_access"] = {"allowed": agent_allowed, "agent_id": agent_id}
                    if not agent_allowed:
                        trace_payload["status"] = "denied"
                        trace_payload["response_text"] = f"⛔ No tienes acceso al agente '{agent_id}'."
                        _persist_decision_trace(
                            gw,
                            trace_id=trace_id,
                            session_id=session_id,
                            user_key=user_key,
                            channel=msg.channel,
                            agent_id=agent_id,
                            tenant_id=tenant_id,
                            workspace_id=workspace_id,
                            environment=environment,
                            trace=trace_payload,
                        )
                        text = f"⛔ No tienes acceso al agente '{agent_id}'." + gw.link_hint(channel_user_id)
                        out = OutboundMessage(
                            channel=msg.channel,
                            user_id=msg.user_id,
                            session_id=session_id,
                            agent_id="system",
                            text=text,
                        )
                        gw.audit.append_message(session_id=session_id, role="assistant", content=out.text)
                        gw.audit.log_event("out", msg.channel, msg.user_id, session_id, out.model_dump(), tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
                        return out
                except Exception:
                    pass

            if "hora" in low_text and ("qué" in low_text or "que" in low_text) and not low_text.startswith("/"):
                msg.text = "/time"

            tool_out = handle_tool_commands(
                gw,
                channel=msg.channel,
                agent_id=agent_id,
                session_id=session_id,
                channel_user_id=msg.user_id,
                user_key=user_key,
                text=msg.text,
            )
            if tool_out is not None:
                trace_payload["status"] = "tool_command"
                trace_payload["response_text"] = tool_out.text
                _persist_decision_trace(
                    gw,
                    trace_id=trace_id,
                    session_id=session_id,
                    user_key=user_key,
                    channel=msg.channel,
                    agent_id=agent_id,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    environment=environment,
                    trace=trace_payload,
                )
                gw.audit.append_message(session_id=session_id, role="assistant", content=tool_out.text)
                gw.audit.log_event("out", msg.channel, msg.user_id, session_id, tool_out.model_dump(), tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
                return tool_out

            extra_system = ""
            hits = []
            if gw.memory is not None:
                try:
                    hits = gw.memory.recall(
                        user_key=user_key,
                        query=msg.text,
                        tenant_id=tenant_id,
                        workspace_id=workspace_id,
                        environment=environment,
                    )
                except TypeError:
                    hits = gw.memory.recall(user_key=user_key, query=msg.text)
                trace_payload["memory"] = _memory_trace_payload(hits)
                extra_system = gw.memory.format_context(hits)

            runtime_t0 = time.perf_counter()
            try:
                reply_text = gw.runtime.generate_reply(
                    agent_id=agent_id,
                    session_id=session_id,
                    user_text=msg.text,
                    extra_system=extra_system,
                    tools_runtime=gw.tools,
                    user_key=user_key,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    environment=environment,
                    channel=msg.channel,
                    trace_collector=trace_payload,
                ) + gw.link_hint(channel_user_id)
            except TypeError:
                reply_text = gw.runtime.generate_reply(
                    agent_id=agent_id,
                    session_id=session_id,
                    user_text=msg.text,
                    extra_system=extra_system,
                    tools_runtime=gw.tools,
                    user_key=user_key,
                ) + gw.link_hint(channel_user_id)
            trace_payload["response_text"] = reply_text
            trace_payload["latency_ms"] = round(float(trace_payload.get("latency_ms") or (time.perf_counter() - runtime_t0) * 1000.0), 3)
            trace_payload["status"] = str(trace_payload.get("status") or "completed")

            if gw.memory is not None:
                try:
                    gw.memory.maybe_remember_user_text(
                        user_key=user_key,
                        user_text=msg.text,
                        tenant_id=tenant_id,
                        workspace_id=workspace_id,
                        environment=environment,
                    )
                except TypeError:
                    gw.memory.maybe_remember_user_text(user_key=user_key, user_text=msg.text)

            _persist_decision_trace(
                gw,
                trace_id=trace_id,
                session_id=session_id,
                user_key=user_key,
                channel=msg.channel,
                agent_id=agent_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                environment=environment,
                trace=trace_payload,
            )

            gw.audit.append_message(session_id=session_id, role="assistant", content=reply_text)

            out = OutboundMessage(
                channel=msg.channel,
                user_id=msg.user_id,
                session_id=session_id,
                agent_id=agent_id,
                text=reply_text,
            )
            gw.audit.log_event("out", msg.channel, msg.user_id, session_id, out.model_dump(), tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
            return out

    except HTTPException:
        record_error("http_exception")
        raise
    except Exception as e:
        try:
            if 'trace_payload' in locals() and 'trace_id' in locals() and 'session_id' in locals() and 'user_key' in locals():
                trace_payload["status"] = "error"
                trace_payload["response_text"] = repr(e)
                trace_payload["decisions"] = {**dict(trace_payload.get("decisions") or {}), "error": repr(e)}
                _persist_decision_trace(
                    gw,
                    trace_id=trace_id,
                    session_id=session_id,
                    user_key=user_key,
                    channel=msg.channel or "http",
                    agent_id=locals().get("agent_id", "system"),
                    tenant_id=locals().get("tenant_id"),
                    workspace_id=locals().get("workspace_id"),
                    environment=locals().get("environment"),
                    trace=trace_payload,
                )
        except Exception:
            pass
        record_error(type(e).__name__)
        gw.audit.log_event(
            direction="error",
            channel=msg.channel or "http",
            user_id=msg.user_id,
            session_id=msg.session_id or "unknown",
            payload={"error": repr(e)},
            tenant_id=((msg.metadata or {}).get("_scope") or {}).get("tenant_id"),
            workspace_id=((msg.metadata or {}).get("_scope") or {}).get("workspace_id"),
            environment=((msg.metadata or {}).get("_scope") or {}).get("environment"),
        )
        raise HTTPException(status_code=500, detail=repr(e))
