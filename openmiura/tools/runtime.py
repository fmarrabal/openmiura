from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from openmiura.infrastructure.persistence.audit_store import AuditStore
from openmiura.core.config import Settings
from openmiura.core.memory import MemoryEngine
from openmiura.core.policy import PolicyEngine
from openmiura.observability import record_error, record_tool_call, update_memory_metrics
from openmiura.core.secrets import SecretBroker
from openmiura.core.sandbox import SandboxManager, SandboxProfileDecision


class ToolError(Exception):
    """Generic tool runtime error."""


class ToolConfirmationRequired(Exception):
    """Raised when a tool call is allowed but requires explicit user confirmation."""

    def __init__(
        self,
        tool_name: str,
        args: dict | None = None,
        message: str | None = None,
    ) -> None:
        self.tool_name = tool_name
        self.args = args or {}
        super().__init__(message or f"La tool '{tool_name}' requiere confirmación explícita.")


@dataclass
class ToolContext:
    settings: Settings
    audit: AuditStore
    memory: Optional[MemoryEngine]
    sandbox_dir: Path
    user_key: str = ""
    user_role: str = "user"
    secret_broker: SecretBroker | None = None
    tenant_id: str | None = None
    workspace_id: str | None = None
    environment: str | None = None
    session_id: str = ""
    sandbox_decision: SandboxProfileDecision | None = None

    def resolve_secret(self, ref: str, *, tool_name: str, domain: str | None = None, required: bool = True) -> str:
        if self.secret_broker is None:
            if required:
                raise RuntimeError("Secret broker is not available")
            return ""
        return self.secret_broker.resolve(
            ref,
            tool_name=tool_name,
            user_role=self.user_role,
            user_key=self.user_key,
            session_id=self.session_id or "system",
            tenant_id=self.tenant_id,
            workspace_id=self.workspace_id,
            environment=self.environment,
            domain=domain,
        )


class Tool:
    name: str = ""
    description: str = ""
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }

    def run(self, ctx: ToolContext, **kwargs) -> str:
        raise NotImplementedError


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if not tool.name:
            raise ValueError("Tool must have a non-empty name")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise ToolError(f"Unknown tool: {name}")
        return self._tools[name]

    def names(self):
        return sorted(self._tools.keys())

    def tool_schemas(self, allowed_names: set[str] | None = None) -> list[dict[str, Any]]:
        names = sorted(self._tools.keys())
        if allowed_names is not None:
            names = [name for name in names if name in allowed_names]
        out: list[dict[str, Any]] = []
        for name in names:
            tool = self._tools[name]
            out.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters_schema,
                    },
                }
            )
        return out


class ToolRuntime:
    def __init__(
        self,
        settings: Settings,
        audit: AuditStore,
        memory: Optional[MemoryEngine],
        registry: ToolRegistry,
        policy: Optional[PolicyEngine] = None,
        skill_loader = None,
        event_publisher = None,
        secret_broker: SecretBroker | None = None,
        sandbox_manager: SandboxManager | None = None,
    ):
        self.settings = settings
        self.audit = audit
        self.memory = memory
        self.registry = registry
        self.policy = policy
        self.skill_loader = skill_loader
        self.event_publisher = event_publisher
        self.secret_broker = secret_broker
        self.sandbox_manager = sandbox_manager or SandboxManager(settings=settings, audit=audit)
        sandbox = settings.tools.sandbox_dir if settings.tools else "data/sandbox"
        self.sandbox_dir = Path(sandbox)
        self.sandbox_dir.mkdir(parents=True, exist_ok=True)

    def _agent_cfg(self, agent_id: str) -> dict[str, Any]:
        cfg = dict(self.settings.agents.get(agent_id, {}) or {})
        if self.skill_loader is not None:
            try:
                cfg = self.skill_loader.extend_agent_config(cfg)
            except Exception:
                pass
        if cfg.get('allowed_tools') is None and cfg.get('tools') is not None:
            cfg['allowed_tools'] = list(cfg.get('tools') or [])
        return cfg


    def _resolve_user_role(self, user_key: str | None = None, user_role: str | None = None) -> str:
        if user_role:
            return str(user_role).strip().lower() or "user"
        if user_key:
            try:
                user = self.audit.get_auth_user(user_key=user_key)
            except Exception:
                user = None
            if user and user.get("role"):
                return str(user.get("role")).strip().lower() or "user"
        return "user"

    def _role_tool_policy(self, user_role: str | None) -> dict[str, set[str]]:
        tools_cfg = getattr(self.settings, "tools", None)
        policies = dict(getattr(tools_cfg, "tool_role_policies", {}) or {}) if tools_cfg is not None else {}
        role_key = str(user_role or "user").strip().lower() or "user"
        raw = dict(policies.get(role_key) or {})
        return {
            "allowed_tools": {str(x).strip() for x in (raw.get("allowed_tools") or []) if str(x).strip()},
            "blocked_tools": {str(x).strip() for x in (raw.get("blocked_tools") or []) if str(x).strip()},
        }

    def _tool_allowed_for_role(self, tool_name: str, user_role: str | None) -> bool:
        policy = self._role_tool_policy(user_role)
        blocked = policy["blocked_tools"]
        allowed = policy["allowed_tools"]
        if blocked and tool_name in blocked:
            return False
        if allowed and tool_name not in allowed:
            return False
        return True

    def _sandbox_decision(
        self,
        *,
        user_role: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        channel: str | None = None,
        agent_id: str | None = None,
        tool_name: str | None = None,
    ) -> SandboxProfileDecision:
        return self.sandbox_manager.resolve(
            user_role=user_role,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            channel=channel,
            agent_name=agent_id,
            tool_name=tool_name,
        )

    def _tool_allowed_for_sandbox(
        self,
        tool_name: str,
        *,
        user_role: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        channel: str | None = None,
        agent_id: str | None = None,
    ) -> tuple[bool, SandboxProfileDecision]:
        decision = self._sandbox_decision(
            user_role=user_role,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            channel=channel,
            agent_id=agent_id,
            tool_name=tool_name,
        )
        return decision.allows_tool(tool_name), decision

    def _decision(
        self,
        agent_id: str,
        tool_name: str,
        *,
        user_role: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        channel: str | None = None,
    ):
        if self.policy is None:
            return True, False, ""
        decision = self.policy.check_tool_access(
            agent_id,
            tool_name,
            user_role=user_role,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            channel=channel,
        )
        allowed = bool(getattr(decision, "allowed", decision.get("allowed", True) if isinstance(decision, dict) else True))
        requires_confirmation = bool(
            getattr(
                decision,
                "requires_confirmation",
                decision.get("requires_confirmation", False) if isinstance(decision, dict) else False,
            )
        )
        reason = getattr(decision, "reason", decision.get("reason", "") if isinstance(decision, dict) else "")
        return allowed, requires_confirmation, reason

    def tool_access(
        self,
        agent_id: str,
        tool_name: str,
        *,
        user_role: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        channel: str | None = None,
    ) -> dict[str, Any]:
        allowed, requires_confirmation, reason = self._decision(
            agent_id,
            tool_name,
            user_role=user_role,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            channel=channel,
        )
        return {
            "allowed": allowed,
            "requires_confirmation": requires_confirmation,
            "reason": reason,
        }

    def is_allowed(self, agent_id: str, tool_name: str, *, user_key: str | None = None, user_role: str | None = None) -> bool:
        agent_cfg = self._agent_cfg(agent_id)
        allowed = agent_cfg.get("allowed_tools", None)
        if allowed is not None and tool_name not in set(allowed):
            return False
        resolved_role = self._resolve_user_role(user_key=user_key, user_role=user_role)
        if not self._tool_allowed_for_role(tool_name, resolved_role):
            return False
        if not self._tool_allowed_for_sandbox(tool_name, user_role=resolved_role, agent_id=agent_id)[0]:
            return False
        dec = self.tool_access(agent_id, tool_name, user_role=resolved_role)
        return bool(dec["allowed"])

    def requires_confirmation(self, agent_id: str, tool_name: str) -> bool:
        dec = self.tool_access(agent_id, tool_name)
        return bool(dec["requires_confirmation"])

    def inspect_tools_for_agent(
        self,
        agent_id: str,
        *,
        user_key: str | None = None,
        user_role: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        channel: str | None = None,
    ) -> list[dict[str, Any]]:
        agent_cfg = self._agent_cfg(agent_id)
        allowed = agent_cfg.get("allowed_tools", None)
        candidate_names = sorted(set(allowed) if allowed is not None else set(self.registry.names()))
        resolved_role = self._resolve_user_role(user_key=user_key, user_role=user_role)
        items: list[dict[str, Any]] = []
        for name in candidate_names:
            role_allowed = self._tool_allowed_for_role(name, resolved_role)
            sandbox_allowed, sandbox_decision = self._tool_allowed_for_sandbox(
                name,
                user_role=resolved_role,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                environment=environment,
                channel=channel,
                agent_id=agent_id,
            )
            policy_allowed = True
            requires_confirmation = False
            policy_reason = ""
            matched_rules: list[dict[str, Any]] = []
            if self.policy is not None and hasattr(self.policy, "explain_request"):
                try:
                    payload = self.policy.explain_request(
                        scope="tool",
                        resource_name=name,
                        action="use",
                        agent_name=agent_id,
                        user_role=resolved_role,
                        tenant_id=tenant_id,
                        workspace_id=workspace_id,
                        environment=environment,
                        channel=channel,
                        extra={"tool_name": name},
                        tool_name=name,
                    )
                    decision = dict(payload.get("decision") or {})
                    policy_allowed = bool(decision.get("allowed", True))
                    requires_confirmation = bool(decision.get("requires_confirmation", False))
                    policy_reason = str(decision.get("reason") or "")
                    matched_rules = list(decision.get("matched_rules") or [])
                except Exception:
                    pass
            final_allowed = bool(role_allowed and sandbox_allowed and policy_allowed)
            reason = policy_reason
            if not role_allowed:
                reason = f"role '{resolved_role}' does not allow tool '{name}'"
            elif not sandbox_allowed:
                reason = f"sandbox profile '{sandbox_decision.profile_name}' denies tool '{name}'"
            items.append(
                {
                    "name": name,
                    "allowed": final_allowed,
                    "role_allowed": bool(role_allowed),
                    "sandbox_allowed": bool(sandbox_allowed),
                    "policy_allowed": bool(policy_allowed),
                    "requires_confirmation": bool(requires_confirmation),
                    "reason": reason,
                    "sandbox_profile": sandbox_decision.profile_name,
                    "matched_rules": matched_rules,
                }
            )
        return items

    def available_tool_schemas(
        self,
        agent_id: str,
        *,
        user_key: str | None = None,
        user_role: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        channel: str | None = None,
        trace_collector: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        inspected = self.inspect_tools_for_agent(
            agent_id,
            user_key=user_key,
            user_role=user_role,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            channel=channel,
        )
        if trace_collector is not None:
            trace_collector["tools_considered"] = [dict(item) for item in inspected]
            trace_collector["policies_applied"] = [
                {
                    "tool_name": item.get("name"),
                    "allowed": item.get("allowed"),
                    "requires_confirmation": item.get("requires_confirmation"),
                    "reason": item.get("reason"),
                    "matched_rules": list(item.get("matched_rules") or []),
                    "sandbox_profile": item.get("sandbox_profile"),
                }
                for item in inspected
            ]
        allowed_names = {str(item.get("name")) for item in inspected if item.get("allowed")}
        return self.registry.tool_schemas(allowed_names)

    def _redact_text(self, text: str | None) -> str:
        raw = str(text or "")
        if self.secret_broker is None:
            return raw
        return self.secret_broker.redact_text(raw)

    def _redact_value(self, value: Any) -> Any:
        if self.secret_broker is None:
            return value
        return self.secret_broker.redact_value(value)

    def run_tool(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_key: str,
        tool_name: str,
        args: Dict[str, Any],
        confirmed: bool = False,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        channel: str | None = None,
        trace_collector: dict[str, Any] | None = None,
    ) -> str:
        agent_cfg = self._agent_cfg(agent_id)
        allowed_tools = agent_cfg.get("allowed_tools", None)

        if allowed_tools is not None and tool_name not in set(allowed_tools):
            raise ToolError(f"Tool not allowed for agent '{agent_id}': {tool_name}")

        resolved_role = self._resolve_user_role(user_key=user_key)
        if not self._tool_allowed_for_role(tool_name, resolved_role):
            raise ToolError(f"Tool not allowed for role '{resolved_role}': {tool_name}")

        sandbox_allowed, sandbox_decision = self._tool_allowed_for_sandbox(
            tool_name,
            user_role=resolved_role,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            channel=channel,
            agent_id=agent_id,
        )
        if not sandbox_allowed:
            try:
                self.audit.log_event(
                    direction="security",
                    channel="sandbox",
                    user_id=user_key,
                    session_id=session_id,
                    payload={
                        "event": "sandbox_tool_denied",
                        "tool_name": tool_name,
                        "profile_name": sandbox_decision.profile_name,
                        "user_role": resolved_role,
                        "tenant_id": tenant_id,
                        "workspace_id": workspace_id,
                        "environment": environment,
                    },
                )
            except Exception:
                pass
            raise ToolError(f"Tool '{tool_name}' denied by sandbox profile '{sandbox_decision.profile_name}'")

        allowed, requires_confirmation, reason = self._decision(
            agent_id,
            tool_name,
            user_role=resolved_role,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            channel=channel,
        )
        if not allowed:
            raise ToolError(reason or f"Tool not allowed for agent '{agent_id}': {tool_name}")
        if requires_confirmation and not confirmed:
            raise ToolConfirmationRequired(tool_name=tool_name, args=args)

        tool = self.registry.get(tool_name)
        ctx = ToolContext(
            settings=self.settings,
            audit=self.audit,
            memory=self.memory,
            sandbox_dir=self.sandbox_dir,
            user_key=user_key,
            user_role=resolved_role,
            secret_broker=self.secret_broker,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            session_id=session_id,
            sandbox_decision=sandbox_decision,
        )

        t0 = time.perf_counter()
        ok = True
        error = ""
        out = ""

        safe_args = self._redact_value(args)

        if trace_collector is not None:
            trace_collector.setdefault("tools_used", [])

        if self.event_publisher is not None:
            try:
                self.event_publisher(
                    "tool_call_started",
                    session_id=session_id,
                    user_key=user_key,
                    agent_id=agent_id,
                    tool_name=tool_name,
                    args=safe_args,
                    sandbox_profile=sandbox_decision.profile_name,
                )
            except Exception:
                pass

        try:
            out = tool.run(ctx, **args)
            out = self._redact_text(out)
            return out
        except Exception as e:
            ok = False
            error = self._redact_text(repr(e))
            record_error(type(e).__name__)
            raise
        finally:
            dt_ms = (time.perf_counter() - t0) * 1000.0
            excerpt = self._redact_text(out or "")
            if len(excerpt) > 500:
                excerpt = excerpt[:500] + " ..."
            record_tool_call(tool_name, ok)
            self.audit.log_tool_call(
                session_id=session_id,
                user_key=user_key,
                agent_id=agent_id,
                tool_name=tool_name,
                args_json=json.dumps(safe_args, ensure_ascii=False),
                ok=ok,
                result_excerpt=excerpt,
                error=self._redact_text(error),
                duration_ms=dt_ms,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                environment=environment,
            )
            if self.event_publisher is not None:
                try:
                    self.event_publisher(
                        "tool_call_finished",
                        session_id=session_id,
                        user_key=user_key,
                        agent_id=agent_id,
                        tool_name=tool_name,
                        args=safe_args,
                        ok=ok,
                        result_excerpt=excerpt,
                        error=self._redact_text(error),
                        duration_ms=dt_ms,
                        sandbox_profile=sandbox_decision.profile_name,
                    )
                except Exception:
                    pass
            if trace_collector is not None:
                trace_collector.setdefault("tools_used", []).append(
                    {
                        "tool_name": tool_name,
                        "args": safe_args,
                        "ok": bool(ok),
                        "error": self._redact_text(error),
                        "result_excerpt": excerpt,
                        "duration_ms": round(float(dt_ms), 3),
                        "sandbox_profile": sandbox_decision.profile_name,
                    }
                )
            if ok and self.memory is not None and out:
                mem_text = f"[{tool_name}] {json.dumps(safe_args, ensure_ascii=False)}\n{excerpt}"
                try:
                    self.memory.remember_text(
                        user_key=user_key,
                        kind="tool_result",
                        text=mem_text,
                        meta={"tool": tool_name},
                    )
                    update_memory_metrics(self.audit)
                except Exception:
                    pass
