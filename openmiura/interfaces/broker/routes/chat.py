from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from openmiura.core.schema import InboundMessage
from openmiura.core.tenancy.scope import build_scoped_session_id
from openmiura.interfaces.broker.common import (
    audit_sensitive,
    broker_auth_context,
    chunk_text,
    enforce_rate_limit,
    get_process_message,
    publish,
    require_csrf,
    resolve_user_key,
    session_event,
)
from openmiura.interfaces.broker.schemas import (
    BrokerChatRequest,
    BrokerChatResponse,
    BrokerTerminalStreamRequest,
)
from openmiura.tools.fs import _resolve_in_sandbox
from openmiura.tools.runtime import ToolError
from openmiura.tools.terminal_exec import validate_terminal_command_policy


def build_chat_router() -> APIRouter:
    router = APIRouter(tags=["broker"])

    @router.post("/chat/stream")
    def broker_chat_stream(payload: BrokerChatRequest, request: Request):
        gw, auth_ctx = broker_auth_context(request)
        require_csrf(request, auth_ctx)
        enforce_rate_limit(request, auth_ctx, bucket="chat_stream", limit_per_minute=int(getattr(gw.settings.broker, "rate_limit_per_minute", 120) or 120))
        effective_user = resolve_user_key(auth_ctx, payload.user_id)
        effective_agent = payload.agent_id or "default"
        scope = {"tenant_id": auth_ctx.get("tenant_id"), "workspace_id": auth_ctx.get("workspace_id"), "environment": auth_ctx.get("environment")}
        tenancy_enabled = bool(getattr(getattr(gw.settings, "tenancy", None), "enabled", False))
        session_id = payload.session_id or (
            build_scoped_session_id(prefix="broker", user_key=effective_user, agent_id=effective_agent, **scope)
            if tenancy_enabled else f"broker:{effective_user}:{effective_agent}"
        )
        if payload.session_id and gw.audit.get_session_scope(session_id) is not None:
            try:
                gw.audit.assert_session_scope(session_id, **scope)
            except ValueError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
        if payload.agent_id:
            try:
                gw.router.select_agent(session_id, payload.agent_id)
            except Exception:
                pass
        metadata = dict(payload.metadata or {})
        metadata.setdefault("_scope", scope)
        inbound = InboundMessage(
            channel="broker",
            user_id=effective_user,
            session_id=session_id,
            text=payload.message,
            metadata=metadata,
        )

        q: queue.Queue[tuple[str, Any]] = queue.Queue()

        def _run() -> None:
            try:
                result = get_process_message()(gw, inbound)
                q.put(("result", result))
            except Exception as exc:
                q.put(("error", exc))

        threading.Thread(target=_run, daemon=True).start()

        def _gen():
            yield session_event("accepted", session_id=session_id, agent_id=effective_agent, user_id=effective_user)
            while True:
                try:
                    kind, payload_obj = q.get(timeout=0.25)
                except queue.Empty:
                    yield session_event("status", stage="working", session_id=session_id)
                    continue
                if kind == "error":
                    yield session_event("error", session_id=session_id, detail=str(payload_obj))
                    break
                text_out = str(getattr(payload_obj, "text", "") or "")
                cumulative = ""
                for chunk in chunk_text(text_out):
                    cumulative += chunk
                    yield session_event("delta", session_id=session_id, delta=chunk, text=cumulative)
                publish(gw, "chat_done", session_id=session_id, user_key=effective_user, agent_id=getattr(payload_obj, "agent_id", effective_agent), text=text_out)
                yield session_event("done", session_id=session_id, text=text_out, agent_id=getattr(payload_obj, "agent_id", effective_agent), transport="http-broker")
                break

        return StreamingResponse(_gen(), media_type="text/event-stream")

    @router.post("/terminal/stream")
    def broker_terminal_stream(payload: BrokerTerminalStreamRequest, request: Request):
        gw, auth_ctx = broker_auth_context(request)
        require_csrf(request, auth_ctx)
        tools_runtime = getattr(gw, "tools", None)
        if tools_runtime is None:
            raise HTTPException(status_code=503, detail="Tool runtime not configured")
        user_key = resolve_user_key(auth_ctx, payload.user_key)
        role = str(auth_ctx.get("role") or "user")
        scope = {
            "tenant_id": auth_ctx.get("tenant_id"),
            "workspace_id": auth_ctx.get("workspace_id"),
            "environment": auth_ctx.get("environment"),
        }

        access = tools_runtime.tool_access(
            payload.agent_id,
            "terminal_exec",
            user_role=role,
            tenant_id=scope.get("tenant_id"),
            workspace_id=scope.get("workspace_id"),
            environment=scope.get("environment"),
            channel="broker",
        )
        if not bool(access.get("allowed", True)):
            raise HTTPException(status_code=403, detail=str(access.get("reason") or "terminal_exec not allowed"))
        if bool(access.get("requires_confirmation", False)) and not payload.confirmed:
            raise HTTPException(status_code=409, detail="terminal_exec requires confirmation")

        ctx = tools_runtime.sandbox_dir
        terminal_cfg = getattr(getattr(gw.settings, "tools", None), "terminal", None)
        enforce_rate_limit(
            request,
            auth_ctx,
            bucket="terminal_stream",
            limit_per_minute=max(5, int(getattr(gw.settings.broker, "rate_limit_per_minute", 120) or 120) // 4),
        )

        sandbox_decision = None
        sandbox_manager = getattr(tools_runtime, "sandbox_manager", None)
        if sandbox_manager is not None:
            sandbox_decision = sandbox_manager.resolve(
                user_role=role,
                tenant_id=scope.get("tenant_id"),
                workspace_id=scope.get("workspace_id"),
                environment=scope.get("environment"),
                channel="broker",
                agent_name=payload.agent_id,
                tool_name="terminal_exec",
            )

        try:
            parts, executable, policy = validate_terminal_command_policy(
                payload.command,
                terminal_cfg,
                role,
                sandbox_decision=sandbox_decision,
            )
        except ToolError as exc:
            audit_sensitive(gw, action="terminal_stream_denied", auth_ctx=auth_ctx, status="denied", target=payload.command, details={"reason": str(exc)})
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        timeout_s = int(payload.timeout_s or policy.get("timeout_s", 30) or 30)
        timeout_s = min(timeout_s, int(policy.get("max_timeout_s", 120) or 120))
        max_chars = int(policy.get("max_output_chars", 12000) or 12000)
        shell_executable = policy.get("shell_executable")
        allow_shell = bool(policy.get("allow_shell", True))
        workdir: Path = ctx
        if payload.cwd:
            workdir = _resolve_in_sandbox(ctx, payload.cwd)
            if not workdir.exists() or not workdir.is_dir():
                raise HTTPException(status_code=404, detail="Working directory not found")
        
        tenancy_enabled = bool(getattr(getattr(gw.settings, "tenancy", None), "enabled", False))
        session_id = payload.session_id or (
            build_scoped_session_id(prefix="broker-terminal", user_key=user_key, agent_id=payload.agent_id, **scope)
            if tenancy_enabled else f"broker:{user_key}:{payload.agent_id}:terminal"
        )
        if payload.session_id and gw.audit.get_session_scope(session_id) is not None:
            try:
                gw.audit.assert_session_scope(session_id, **scope)
            except ValueError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
        command = payload.command.strip()

        def _event(data: dict[str, Any]) -> bytes:
            return f"data: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")

        def _stream():
            t0 = time.time()
            stdout_total = 0
            proc = subprocess.Popen(
                command if allow_shell else parts,
                shell=allow_shell,
                cwd=str(workdir),
                executable=shell_executable if allow_shell else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            publish(gw, "terminal_start", session_id=session_id, user_key=user_key, agent_id=payload.agent_id, command=command, cwd=str(workdir))
            audit_sensitive(gw, action="terminal_stream_start", auth_ctx=auth_ctx, status="ok", target=command, session_id=session_id, details={"cwd": str(workdir), "role": role})
            yield _event({"type": "start", "command": command, "cwd": str(workdir), "session_id": session_id})
            try:
                if proc.stdout is not None:
                    for line in proc.stdout:
                        stdout_total += len(line)
                        if stdout_total <= max_chars:
                            yield _event({"type": "stdout", "chunk": line})
                        if time.time() - t0 > timeout_s:
                            proc.kill()
                            yield _event({"type": "error", "error": f"Command timed out after {timeout_s}s"})
                            break
                exit_code = proc.wait(timeout=2)
                gw.audit.log_tool_call(
                    session_id=session_id,
                    user_key=user_key,
                    agent_id=payload.agent_id,
                    tool_name="terminal_exec",
                    args_json=json.dumps({"command": command, "executable": executable, "cwd": payload.cwd, "timeout_s": timeout_s}, ensure_ascii=False),
                    ok=(exit_code == 0),
                    result_excerpt=f"streamed terminal output (exit={exit_code})",
                    error="" if exit_code == 0 else f"exit_code={exit_code}",
                    duration_ms=(time.time() - t0) * 1000.0,
                    tenant_id=scope.get("tenant_id"),
                    workspace_id=scope.get("workspace_id"),
                    environment=scope.get("environment"),
                )
                publish(gw, "terminal_end", session_id=session_id, user_key=user_key, agent_id=payload.agent_id, command=command, exit_code=exit_code)
                audit_sensitive(gw, action="terminal_stream_end", auth_ctx=auth_ctx, status="ok" if exit_code == 0 else "error", target=command, session_id=session_id, details={"exit_code": exit_code})
                yield _event({"type": "end", "exit_code": exit_code})
            finally:
                if proc.poll() is None:
                    proc.kill()

        return StreamingResponse(_stream(), media_type="text/event-stream")

    @router.post("/chat", response_model=BrokerChatResponse)
    def broker_chat(payload: BrokerChatRequest, request: Request):
        gw, auth_ctx = broker_auth_context(request)
        require_csrf(request, auth_ctx)
        enforce_rate_limit(request, auth_ctx, bucket="chat", limit_per_minute=int(getattr(gw.settings.broker, "rate_limit_per_minute", 120) or 120))
        effective_user = str(payload.user_id or auth_ctx.get("user_key") or "broker:local")
        scope = {"tenant_id": auth_ctx.get("tenant_id"), "workspace_id": auth_ctx.get("workspace_id"), "environment": auth_ctx.get("environment")}
        tenancy_enabled = bool(getattr(getattr(gw.settings, "tenancy", None), "enabled", False))
        session_id = payload.session_id or (
            build_scoped_session_id(prefix="broker", user_key=effective_user, agent_id=payload.agent_id or "default", **scope)
            if tenancy_enabled else f"broker:{effective_user}"
        )
        if payload.session_id and gw.audit.get_session_scope(session_id) is not None:
            try:
                gw.audit.assert_session_scope(session_id, **scope)
            except ValueError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
        if payload.agent_id:
            try:
                gw.router.select_agent(session_id, payload.agent_id)
            except Exception:
                pass
        outbound = get_process_message()(
            gw,
            InboundMessage(
                channel="broker",
                user_id=effective_user,
                text=payload.message,
                session_id=session_id,
                metadata={**dict(payload.metadata or {}), "_scope": scope},
            ),
        )
        return BrokerChatResponse(
            channel=outbound.channel,
            user_id=outbound.user_id,
            session_id=outbound.session_id,
            agent_id=outbound.agent_id,
            text=outbound.text,
        )

    return router
