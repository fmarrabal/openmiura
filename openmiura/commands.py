from __future__ import annotations

import time
from typing import TYPE_CHECKING

from openmiura.core.schema import OutboundMessage
from openmiura.tools.runtime import ToolConfirmationRequired, ToolError

if TYPE_CHECKING:
    from openmiura.gateway import Gateway


def _format_uptime(seconds: float) -> str:
    secs = max(0, int(seconds))
    days, rem = divmod(secs, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours or parts:
        parts.append(f"{hours}h")
    if minutes or parts:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return " ".join(parts)


def _status_reply(
    gw: Gateway,
    *,
    channel: str,
    channel_user_id: str,
    user_key: str,
    session_id: str,
    metadata: dict | None,
) -> str:
    mem_user = gw.audit.count_memory_items(user_key=user_key)
    mem_total = gw.audit.count_memory_items(user_key=None)
    total_sessions = gw.audit.count_sessions()
    active_sessions = gw.audit.count_active_sessions(window_s=86400)
    last_message = gw.audit.get_last_message(session_id)
    uptime = _format_uptime(time.time() - float(getattr(gw, "started_at", time.time())))

    last_msg_text = "n/a"
    if last_message:
        content = (last_message.get("content") or "").strip().replace("\n", " ")
        if len(content) > 120:
            content = content[:120] + "…"
        last_msg_text = f"{last_message.get('role')}: {content}"

    router = getattr(gw, "router", None)
    current_agent = getattr(getattr(router, "_session_agent", {}), "get", lambda *_: "default")(session_id, "default")

    llm_model = getattr(getattr(gw.settings, "llm", None), "model", "n/a")
    memory_cfg = getattr(gw.settings, "memory", None)
    embed_model = getattr(memory_cfg, "embed_model", "n/a") if memory_cfg else "n/a"

    reply = (
        "🧩 openMiura status\n"
        f"- uptime: {uptime}\n"
        f"- active_sessions(24h): {active_sessions}\n"
        f"- sessions(total): {total_sessions}\n"
        f"- memory_items(user): {mem_user}\n"
        f"- memory_items(total): {mem_total}\n"
        f"- last_message: {last_msg_text}\n"
        f"- current_agent: {current_agent}\n"
        f"- channel: {channel}\n"
        f"- channel_user_id: {channel_user_id}\n"
        f"- user_key (effective): {user_key}\n"
        f"- session_id: {session_id}\n"
        f"- llm_model: {llm_model}\n"
        f"- embed_model: {embed_model}\n"
    )

    if channel == "telegram":
        md = metadata or {}
        reply += (
            f"- telegram.from_id: {md.get('from_id')}\n"
            f"- telegram.chat_id: {md.get('chat_id')}\n"
        )

    return reply


def _msg(
    gw: Gateway,
    *,
    channel: str,
    channel_user_id: str,
    session_id: str,
    text: str,
    agent_id: str = "system",
) -> OutboundMessage:
    try:
        append_message = getattr(getattr(gw, "audit", None), "append_message", None)
        if callable(append_message):
            append_message(session_id, "assistant", text)
    except Exception:
        pass

    return OutboundMessage(
        channel=channel,
        user_id=channel_user_id,
        session_id=session_id,
        agent_id=agent_id,
        text=text,
    )


def _forget_reply(
    gw: Gateway,
    *,
    channel: str,
    channel_user_id: str,
    user_key: str,
    session_id: str,
    raw: str,
) -> OutboundMessage:
    parts = raw.split(maxsplit=2)

    if len(parts) == 1:
        items = gw.audit.search_memory_items(user_key=user_key, limit=5)
        if not items:
            return _msg(
                gw,
                channel=channel,
                channel_user_id=channel_user_id,
                session_id=session_id,
                text="ℹ️ No tengo memorias guardadas para ti.",
            )

        lines = ["🧠 Últimas 5 memorias:"]
        for item in items:
            text = (item.get("text") or "").replace("\n", " ").strip()
            if len(text) > 80:
                text = text[:80] + "…"
            lines.append(f"- #{item['id']} ({item['kind']}) {text}")

        lines.append("")
        lines.append("Usa /forget <id> para borrar una memoria.")
        lines.append("Usa /forget all confirm para borrar todo.")

        return _msg(
            gw,
            channel=channel,
            channel_user_id=channel_user_id,
            session_id=session_id,
            text="\n".join(lines),
        )

    arg1 = parts[1].strip().lower()

    if arg1 == "all":
        if len(parts) < 3 or parts[2].strip().lower() != "confirm":
            return _msg(
                gw,
                channel=channel,
                channel_user_id=channel_user_id,
                session_id=session_id,
                text="⚠️ Confirmación requerida. Usa /forget all confirm para borrar toda tu memoria long-term.",
            )

        deleted_mem = gw.audit.delete_memory_items(user_key=user_key, kind=None)
        deleted_ctx = gw.audit.clear_session_messages(session_id=session_id)

        return _msg(
            gw,
            channel=channel,
            channel_user_id=channel_user_id,
            session_id=session_id,
            text=(
                f"✅ He borrado tu memoria a largo plazo ({deleted_mem} items) "
                f"y he reseteado el contexto de esta sesión ({deleted_ctx} mensajes)."
            ),
        )

    try:
        item_id = int(parts[1].strip())
    except Exception:
        return _msg(
            gw,
            channel=channel,
            channel_user_id=channel_user_id,
            session_id=session_id,
            text="ℹ️ Uso: /forget | /forget <id> | /forget all confirm",
        )

    deleted = gw.audit.delete_memory_item_by_id(user_key=user_key, item_id=item_id)

    return _msg(
        gw,
        channel=channel,
        channel_user_id=channel_user_id,
        session_id=session_id,
        text=(
            f"✅ Memoria #{item_id} borrada."
            if deleted
            else f"ℹ️ No encontré ninguna memoria #{item_id} para tu usuario."
        ),
    )


def handle_commands(
    gw: Gateway,
    *,
    channel: str,
    channel_user_id: str,
    user_key: str,
    session_id: str,
    text: str,
    metadata: dict | None,
) -> OutboundMessage | None:
    raw = (text or "").strip()
    if not raw.startswith("/"):
        return None

    low = raw.lower()

    if low.startswith("/help") or low.startswith("/ayuda"):
        router = getattr(gw, "router", None)
        agents = ", ".join(router.available_agents()) if router and hasattr(router, "available_agents") else "default"
        return _msg(
            gw,
            channel=channel,
            channel_user_id=channel_user_id,
            session_id=session_id,
            text=(
                "🧩 openMiura — ayuda\n\n"
                "Comandos core:\n"
                "- /help\n- /status\n- /reset\n- /forget\n- /link <id_global>\n- /agent <name>\n- /confirm\n- /cancel\n\n"
                "Tools:\n- /time\n- /fetch <url>\n- /read <path>\n- /write <path> <texto>\n\n"
                f"Agentes disponibles: {agents}"
            ),
        )

    if low.startswith("/status"):
        return _msg(
            gw,
            channel=channel,
            channel_user_id=channel_user_id,
            session_id=session_id,
            text=_status_reply(
                gw,
                channel=channel,
                channel_user_id=channel_user_id,
                user_key=user_key,
                session_id=session_id,
                metadata=metadata,
            ),
        )

    if low.startswith("/reset"):
        deleted = gw.audit.clear_session_messages(session_id=session_id)
        router = getattr(gw, "router", None)
        if router is not None and hasattr(router, "clear_agent"):
            try:
                router.clear_agent(session_id)
            except Exception:
                pass
        pending_cleared = False
        reset_pending = getattr(gw, "reset_pending_tool_confirmations", None)
        if callable(reset_pending):
            pending_cleared = bool(reset_pending(session_id))
        pending_note = ""
        if pending_cleared:
            pending_note = " También he limpiado 1 confirmación(es) pendiente(s)."
        return _msg(
            gw,
            channel=channel,
            channel_user_id=channel_user_id,
            session_id=session_id,
            text=(
                f"✅ Sesión reseteada. He borrado {deleted} mensajes de contexto "
                "(la memoria a largo plazo se mantiene)."
                + pending_note
            ),
        )

    if low.startswith("/forget"):
        return _forget_reply(
            gw,
            channel=channel,
            channel_user_id=channel_user_id,
            user_key=user_key,
            session_id=session_id,
            raw=raw,
        )

    if low.startswith("/confirm"):
        pending = None
        getter = getattr(gw, "pop_pending_tool_confirmation", None)
        if callable(getter):
            pending = getter(session_id)
        if pending is None:
            consumer = getattr(gw, "consume_pending_tool_confirmation", None)
            if callable(consumer):
                pending = consumer(session_id, user_key=user_key)
        if not pending:
            return _msg(
                gw,
                channel=channel,
                channel_user_id=channel_user_id,
                session_id=session_id,
                text="ℹ️ No hay ninguna acción pendiente de confirmación o ya ha caducado.",
            )
        try:
            result = gw.tools.run_tool(
                agent_id=pending["agent_id"],
                session_id=session_id,
                user_key=pending["user_key"],
                tool_name=pending["tool_name"],
                args=pending["args"],
                confirmed=True,
            )
            return _msg(
                gw,
                channel=channel,
                channel_user_id=channel_user_id,
                session_id=session_id,
                text=result,
                agent_id=f"tool:{pending['tool_name']}",
            )
        except Exception as e:
            return _msg(
                gw,
                channel=channel,
                channel_user_id=channel_user_id,
                session_id=session_id,
                text=f"⛔ Confirmed tool failed: {e!r}",
            )

    if low.startswith("/cancel"):
        cleared = False
        clearer = getattr(gw, "clear_pending_tool_confirmation", None)
        if callable(clearer):
            cleared = bool(clearer(session_id))
        if not cleared:
            canceller = getattr(gw, "cancel_pending_tool_confirmation", None)
            if callable(canceller):
                cleared = bool(canceller(session_id, user_key=user_key))
        if cleared:
            return _msg(
                gw,
                channel=channel,
                channel_user_id=channel_user_id,
                session_id=session_id,
                text="✅ Acción pendiente cancelada.",
            )
        return _msg(
            gw,
            channel=channel,
            channel_user_id=channel_user_id,
            session_id=session_id,
            text="ℹ️ No había ninguna acción pendiente.",
        )

    if low.startswith("/link"):
        parts = raw.split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            return _msg(
                gw,
                channel=channel,
                channel_user_id=channel_user_id,
                session_id=session_id,
                text="ℹ️ Uso: /link <global_user_key>\nEj: /link curro",
            )

        global_key = parts[1].strip()
        if getattr(gw, "identity", None) is not None:
            gw.identity.link(channel_user_id, global_key, linked_by="user")
        else:
            try:
                gw.audit.set_identity(
                    channel_user_key=channel_user_id,
                    global_user_key=global_key,
                    linked_by=channel_user_id,
                )
            except TypeError:
                gw.audit.set_identity(
                    channel_user_key=channel_user_id,
                    global_user_key=global_key,
                )

        return _msg(
            gw,
            channel=channel,
            channel_user_id=channel_user_id,
            session_id=session_id,
            text=f"✅ Identidad enlazada: {channel_user_id} → {global_key}",
        )

    if low.startswith("/agent"):
        parts = raw.split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            return _msg(
                gw,
                channel=channel,
                channel_user_id=channel_user_id,
                session_id=session_id,
                text="ℹ️ Uso: /agent <name>",
            )

        router = getattr(gw, "router", None)
        if router is None:
            return _msg(
                gw,
                channel=channel,
                channel_user_id=channel_user_id,
                session_id=session_id,
                text="ℹ️ Router no disponible en este entorno.",
            )

        agent_name = parts[1].strip()
        policy = getattr(gw, "policy", None)
        if policy is not None:
            try:
                if not policy.check_agent_access(user_key, agent_name):
                    return _msg(
                        gw,
                        channel=channel,
                        channel_user_id=channel_user_id,
                        session_id=session_id,
                        text=f"⛔ No tienes acceso al agente '{agent_name}'.",
                    )
            except Exception:
                pass

        invalidated = 0
        invalidator = getattr(gw, "invalidate_pending_confirmation_for_agent_change", None)
        if callable(invalidator):
            try:
                invalidated = int(bool(invalidator(session_id, agent_name)))
            except Exception:
                invalidated = 0
        else:
            legacy_invalidator = getattr(gw, "invalidate_pending_tool_confirmation_for_agent", None)
            if callable(legacy_invalidator):
                try:
                    invalidated = int(legacy_invalidator(session_id, getattr(router, "_session_agent", {}).get(session_id)))
                except Exception:
                    invalidated = 0
        ok = router.select_agent(session_id, agent_name)
        suffix = f" También he invalidado {invalidated} confirmación(es) pendiente(s)." if invalidated else ""
        return _msg(
            gw,
            channel=channel,
            channel_user_id=channel_user_id,
            session_id=session_id,
            text=(
                (f"✅ Agente activo: {agent_name}" if ok else f"⛔ Agente desconocido: {agent_name}")
                + suffix
            ),
        )

    return None


def handle_tool_commands(
    gw: Gateway,
    *,
    channel: str,
    agent_id: str,
    session_id: str,
    channel_user_id: str,
    user_key: str,
    text: str,
) -> OutboundMessage | None:
    if gw.tools is None:
        return None

    raw = (text or "").strip()
    if not raw.startswith("/"):
        return None

    parts = raw.split(maxsplit=2)
    cmd = parts[0].lower()

    def _out(aid: str, txt: str) -> OutboundMessage:
        return OutboundMessage(
            channel=channel,
            user_id=channel_user_id,
            session_id=session_id,
            agent_id=aid,
            text=txt,
        )

    def _run(tool_name: str, args: dict) -> OutboundMessage:
        try:
            result = gw.tools.run_tool(
                agent_id=agent_id,
                session_id=session_id,
                user_key=user_key,
                tool_name=tool_name,
                args=args,
            )
            return _out(f"tool:{tool_name}", result)
        except ToolConfirmationRequired as e:
            setter = getattr(gw, "set_pending_tool_confirmation", None)
            if callable(setter):
                setter(
                    session_id,
                    channel=channel,
                    channel_user_id=channel_user_id,
                    user_key=user_key,
                    agent_id=agent_id,
                    tool_name=tool_name,
                    args=args,
                )
            return _out("system", f"⚠️ La herramienta '{tool_name}' requiere confirmación. Usa /confirm o /cancel.")
        except ToolError as e:
            return _out("system", f"⛔ Tool error: {e}")
        except Exception as e:
            return _out("system", f"⛔ Tool failed: {e!r}")

    if cmd in ("/time", "/hora", "/fecha"):
        return _run("time_now", {})
    if cmd == "/fetch":
        if len(parts) < 2:
            return _out("system", "ℹ️ Uso: /fetch <url>")
        return _run("web_fetch", {"url": parts[1]})
    if cmd == "/read":
        if len(parts) < 2:
            return _out("system", "ℹ️ Uso: /read <path_relativo_en_sandbox>")
        return _run("fs_read", {"path": parts[1]})
    if cmd == "/write":
        if len(parts) < 3:
            return _out("system", "ℹ️ Uso: /write <path> <texto>")
        return _run("fs_write", {"path": parts[1], "content": parts[2]})

    return None
