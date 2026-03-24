from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from openmiura.core.policies.models import PolicyDecision, PolicyTrace, ToolAccessDecision


def _norm(value: Any) -> str:
    return str(value or "").strip()


def _norm_lower(value: Any) -> str:
    return _norm(value).lower()


def _listify(value: Any, *, lower: bool = False) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str) and not value.strip():
        return []
    if isinstance(value, (list, tuple, set)):
        items = value
    else:
        items = [value]
    out: list[str] = []
    for item in items:
        text = _norm_lower(item) if lower else _norm(item)
        if text:
            out.append(text)
    return out


class PolicyEngine:
    def __init__(self, policies_path: str | None = None):
        self.policies_path = str(policies_path or "configs/policies.yaml")
        self._in_memory = False
        self._signature: str | None = None
        self._data: dict[str, Any] = self._empty_data()
        self.reload(force=True)

    @staticmethod
    def _empty_data() -> dict[str, Any]:
        return {
            "defaults": {},
            "agent_rules": [],
            "user_rules": [],
            "tool_rules": [],
            "memory_rules": [],
            "secret_rules": [],
            "channel_rules": [],
            "approval_rules": [],
        }

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> "PolicyEngine":
        inst = cls.__new__(cls)
        inst.policies_path = "<in-memory>"
        inst._in_memory = True
        inst._data = cls.normalize_data(data)
        inst._signature = cls.data_signature(inst._data)
        return inst

    @classmethod
    def normalize_data(cls, loaded: dict[str, Any] | None) -> dict[str, Any]:
        base = cls._empty_data()
        raw_data = dict(loaded or {})
        for key in base:
            raw = raw_data.get(key, base[key])
            if isinstance(base[key], list):
                base[key] = [dict(item or {}) if isinstance(item, dict) else item for item in list(raw or [])]
            else:
                base[key] = dict(raw or {})
        return base

    @staticmethod
    def data_signature(data: dict[str, Any] | None) -> str:
        payload = json.dumps(data or {}, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _file_signature(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def signature(self) -> str | None:
        self.reload_if_changed()
        return self._signature

    def snapshot(self) -> dict[str, Any]:
        self.reload_if_changed()
        return copy.deepcopy(self._data)

    def reload(self, force: bool = False) -> dict[str, Any]:
        if getattr(self, "_in_memory", False):
            return {"changed": False, "reason": "in_memory"}
        p = Path(self.policies_path)
        if not p.exists():
            self._data = self._empty_data()
            self._signature = None
            return {"changed": False, "reason": "missing_file"}

        sig = self._file_signature(p)
        if not force and self._signature == sig:
            return {"changed": False, "reason": "unchanged"}

        previous = dict(self._data)
        try:
            loaded = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            self._data = self.normalize_data(loaded)
            self._signature = sig
            return {"changed": True, "reason": "reloaded"}
        except Exception as e:
            self._data = previous
            return {"changed": False, "reason": f"reload_failed: {e!r}"}

    def reload_if_changed(self) -> None:
        if getattr(self, "_in_memory", False):
            return
        self.reload(force=False)

    def check_agent_access(self, user_key: str, agent_name: str) -> bool:
        self.reload_if_changed()
        allowed = True
        for rule in self._data.get("user_rules", []):
            if _norm(rule.get("user")) != _norm(user_key):
                continue
            allow_agents = _listify(rule.get("allow_agents") or rule.get("can_access_agents"))
            deny_agents = _listify(rule.get("deny_agents") or rule.get("cannot_access_agents"))
            if "*" in allow_agents or _norm(agent_name) in allow_agents:
                allowed = True
            if _norm(agent_name) in deny_agents:
                return False
        return allowed

    def check_tool_access(
        self,
        agent_name: str,
        tool_name: str,
        *,
        user_role: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        channel: str | None = None,
        dry_run: bool = False,
    ) -> ToolAccessDecision:
        self.reload_if_changed()
        traces: list[PolicyTrace] = []
        matched: list[str] = []
        allowed = self._default_allow("tools", default=True)
        requires_confirmation = False
        reason = ""

        agent = _norm(agent_name)
        tool = _norm(tool_name)
        role = _norm_lower(user_role or "user") or "user"
        ctx = self._build_context(
            resource_kind="tool",
            resource_name=tool,
            action="use",
            user_role=role,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            channel=channel,
            agent_name=agent,
            extra_keys={"tool": tool},
        )

        explicit_agent_allow = False
        for idx, rule in enumerate(self._data.get("agent_rules", []), start=1):
            if _norm(rule.get("agent")) != agent:
                continue
            rule_name = _norm(rule.get("name")) or f"agent_rules[{idx}]"
            allow_tools = _listify(rule.get("allow_tools") or rule.get("can_use_tools"))
            deny_tools = _listify(rule.get("deny_tools") or rule.get("cannot_use_tools"))
            if allow_tools:
                explicit_agent_allow = True
                if tool in allow_tools or "*" in allow_tools:
                    traces.append(PolicyTrace(scope="agent", name=rule_name, effect="allow", reason=f"tool '{tool}' allowed for agent '{agent}'"))
                    matched.append(rule_name)
                else:
                    allowed = False
                    reason = f"tool '{tool}' not allowed for agent '{agent}'"
                    traces.append(PolicyTrace(scope="agent", name=rule_name, effect="deny", reason=reason))
                    matched.append(rule_name)
            if tool in deny_tools or "*" in deny_tools:
                allowed = False
                reason = f"tool '{tool}' denied for agent '{agent}'"
                traces.append(PolicyTrace(scope="agent", name=rule_name, effect="deny", reason=reason))
                matched.append(rule_name)

        if explicit_agent_allow and not any(t.effect == "allow" and t.scope == "agent" for t in traces):
            allowed = False
            if not reason:
                reason = f"tool '{tool}' not allowed for agent '{agent}'"

        for idx, rule in enumerate(self._data.get("tool_rules", []), start=1):
            if not self._rule_matches(rule, ctx, fallback_key="tool"):
                continue
            rule_name = _norm(rule.get("name")) or f"tool_rules[{idx}]"
            matched.append(rule_name)
            effect = _norm_lower(rule.get("effect") or rule.get("decision"))
            if not effect:
                effect = "allow"
            if effect == "deny":
                allowed = False
                reason = _norm(rule.get("reason")) or f"tool '{tool}' denied by policy"
            elif effect == "allow":
                if not any(t.effect == "deny" for t in traces):
                    allowed = True
                    if not reason:
                        reason = _norm(rule.get("reason")) or f"tool '{tool}' allowed by policy"
            if bool(rule.get("requires_confirmation", False)):
                requires_confirmation = True
            traces.append(PolicyTrace(scope="tool", name=rule_name, effect=effect, reason=_norm(rule.get("reason")) or "matched tool rule", rule=dict(rule or {})))

        if dry_run:
            reason = reason or "dry-run"
        return ToolAccessDecision(
            allowed=allowed,
            requires_confirmation=requires_confirmation,
            reason=reason,
            matched_rules=matched,
            explanation=traces,
        )

    def check_channel_access(
        self,
        channel: str,
        *,
        action: str = "use",
        user_role: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        agent_name: str | None = None,
    ) -> PolicyDecision:
        self.reload_if_changed()
        return self._evaluate_rules(
            section="channel_rules",
            resource_kind="channel",
            resource_name=_norm_lower(channel),
            action=action,
            default=self._default_allow("channels", default=True),
            user_role=user_role,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            channel=channel,
            agent_name=agent_name,
            fallback_key="channel",
        )

    def check_memory_access(
        self,
        action: str,
        *,
        kind: str | None = None,
        user_role: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        channel: str | None = None,
        agent_name: str | None = None,
    ) -> PolicyDecision:
        self.reload_if_changed()
        return self._evaluate_rules(
            section="memory_rules",
            resource_kind="memory",
            resource_name=_norm(kind or "*"),
            action=action,
            default=self._default_allow("memory", default=True),
            user_role=user_role,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            channel=channel,
            agent_name=agent_name,
            fallback_key="kind",
        )

    def check_secret_access(
        self,
        ref: str,
        *,
        tool_name: str | None = None,
        user_role: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        channel: str | None = None,
        domain: str | None = None,
    ) -> PolicyDecision:
        self.reload_if_changed()
        return self._evaluate_rules(
            section="secret_rules",
            resource_kind="secret",
            resource_name=_norm(ref),
            action="resolve",
            default=self._default_allow("secrets", default=True),
            user_role=user_role,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            channel=channel,
            agent_name=tool_name,
            domain=domain,
            fallback_key="ref",
            extra_keys={"tool": _norm(tool_name)},
        )

    def check_approval_requirement(
        self,
        action: str,
        *,
        user_role: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        channel: str | None = None,
        agent_name: str | None = None,
    ) -> PolicyDecision:
        self.reload_if_changed()
        decision = self._evaluate_rules(
            section="approval_rules",
            resource_kind="approval",
            resource_name=_norm(action),
            action="require",
            default=self._default_allow("approvals", default=True),
            user_role=user_role,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            channel=channel,
            agent_name=agent_name,
            fallback_key="action_name",
        )
        decision.requires_approval = any(item.effect in {"require", "require_approval"} for item in decision.explanation)
        if decision.requires_approval and not decision.reason:
            decision.reason = f"approval required for '{action}'"
        return decision

    def explain_request(
        self,
        *,
        scope: str,
        resource_name: str,
        action: str = "use",
        agent_name: str | None = None,
        user_role: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        channel: str | None = None,
        domain: str | None = None,
        extra: dict[str, Any] | None = None,
        tool_name: str | None = None,
    ) -> dict[str, Any]:
        normalized_scope = _norm_lower(scope)
        if normalized_scope == "tool":
            decision = self.check_tool_access(
                agent_name or "default",
                resource_name,
                user_role=user_role,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                environment=environment,
                channel=channel,
                dry_run=True,
            )
        elif normalized_scope == "memory":
            decision = self.check_memory_access(
                action,
                kind=resource_name,
                user_role=user_role,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                environment=environment,
                channel=channel,
                agent_name=agent_name,
            )
        elif normalized_scope == "secret":
            resolved_tool_name = str(tool_name or (extra or {}).get("tool_name") or agent_name or "").strip() or None
            decision = self.check_secret_access(
                resource_name,
                tool_name=resolved_tool_name,
                user_role=user_role,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                environment=environment,
                channel=channel,
                domain=domain,
            )
        elif normalized_scope == "channel":
            decision = self.check_channel_access(
                resource_name,
                action=action,
                user_role=user_role,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                environment=environment,
                agent_name=agent_name,
            )
        elif normalized_scope == "approval":
            decision = self.check_approval_requirement(
                resource_name,
                user_role=user_role,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                environment=environment,
                channel=channel,
                agent_name=agent_name,
            )
        else:
            decision = PolicyDecision(allowed=False, reason=f"unknown scope '{scope}'")
        return {
            "ok": True,
            "scope": normalized_scope,
            "resource_name": resource_name,
            "action": action,
            "decision": decision.to_dict(),
            "context": {
                "agent_name": agent_name,
                "user_role": _norm_lower(user_role or "user") or "user",
                "tenant_id": tenant_id,
                "workspace_id": workspace_id,
                "environment": environment,
                "channel": channel,
                "domain": domain,
                "tool_name": tool_name,
                "extra": dict(extra or {}),
            },
            "signature": self._signature,
        }

    def _build_context(
        self,
        *,
        resource_kind: str,
        resource_name: str,
        action: str,
        user_role: str | None,
        tenant_id: str | None,
        workspace_id: str | None,
        environment: str | None,
        channel: str | None,
        agent_name: str | None,
        domain: str | None = None,
        extra_keys: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        ctx = {
            "resource_kind": _norm_lower(resource_kind),
            "resource_name": _norm(resource_name),
            "action": _norm_lower(action),
            "user_role": _norm_lower(user_role or "user") or "user",
            "tenant_id": _norm(tenant_id),
            "workspace_id": _norm(workspace_id),
            "environment": _norm(environment),
            "channel": _norm_lower(channel),
            "agent_name": _norm(agent_name),
            "domain": _norm_lower(domain),
        }
        for key, value in dict(extra_keys or {}).items():
            ctx[_norm_lower(key)] = _norm_lower(value) if key in {"tool", "channel", "domain", "user_role"} else _norm(value)
        return ctx

    def _default_allow(self, key: str, *, default: bool) -> bool:
        defaults = dict(self._data.get("defaults") or {})
        raw = defaults.get(key)
        if raw is None:
            return default
        return bool(raw)

    def _rule_matches(self, rule: dict[str, Any], ctx: dict[str, str], *, fallback_key: str) -> bool:
        if not isinstance(rule, dict):
            return False
        resource_name = ctx.get("resource_name", "")
        action = ctx.get("action", "")
        if any(
            not self._matches_value(ctx.get(name, ""), rule.get(name))
            for name in ("user_role", "tenant_id", "workspace_id", "environment", "channel", "agent_name", "domain")
            if rule.get(name) is not None
        ):
            return False
        if rule.get("actions") is not None and not self._matches_value(action, rule.get("actions")):
            return False
        if rule.get("action") is not None and not self._matches_value(action, rule.get("action")):
            return False
        if rule.get("resource") is not None and not self._matches_value(resource_name, rule.get("resource")):
            return False
        if rule.get("resources") is not None and not self._matches_value(resource_name, rule.get("resources")):
            return False
        specific = rule.get(fallback_key)
        if specific is not None and not self._matches_value(resource_name, specific):
            return False
        # alternate legacy keys
        if fallback_key == "kind" and rule.get("memory_kind") is not None and not self._matches_value(resource_name, rule.get("memory_kind")):
            return False
        if fallback_key == "ref" and rule.get("secret_ref") is not None and not self._matches_value(resource_name, rule.get("secret_ref")):
            return False
        if rule.get("tool") is not None and ctx.get("tool", ctx.get("agent_name", "")) and not self._matches_value(ctx.get("tool", ctx.get("agent_name", "")), rule.get("tool")):
            return False
        return True

    def _matches_value(self, actual: str, expected: Any) -> bool:
        allowed = _listify(expected, lower=False)
        if not allowed:
            return False
        normalized_actual = _norm(actual)
        lowered_actual = _norm_lower(actual)
        for item in allowed:
            lowered_item = item.lower()
            if item == "*":
                return True
            if lowered_item == lowered_actual or item == normalized_actual:
                return True
            if lowered_item.startswith("*.") and lowered_actual.endswith(lowered_item[1:]):
                return True
        return False

    def _evaluate_rules(
        self,
        *,
        section: str,
        resource_kind: str,
        resource_name: str,
        action: str,
        default: bool,
        user_role: str | None,
        tenant_id: str | None,
        workspace_id: str | None,
        environment: str | None,
        channel: str | None,
        agent_name: str | None,
        domain: str | None = None,
        fallback_key: str,
        extra_keys: dict[str, Any] | None = None,
    ) -> PolicyDecision:
        traces: list[PolicyTrace] = []
        matched: list[str] = []
        allowed = default
        reason = ""
        requires_confirmation = False
        requires_approval = False
        ctx = self._build_context(
            resource_kind=resource_kind,
            resource_name=resource_name,
            action=action,
            user_role=user_role,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            channel=channel,
            agent_name=agent_name,
            domain=domain,
            extra_keys=extra_keys,
        )

        for idx, rule in enumerate(self._data.get(section, []), start=1):
            if not self._rule_matches(rule, ctx, fallback_key=fallback_key):
                continue
            rule_name = _norm(rule.get("name")) or f"{section}[{idx}]"
            matched.append(rule_name)
            effect = _norm_lower(rule.get("effect") or rule.get("decision") or "allow")
            trace_reason = _norm(rule.get("reason")) or f"matched {section} rule"
            traces.append(PolicyTrace(scope=resource_kind, name=rule_name, effect=effect, reason=trace_reason, rule=dict(rule or {})))
            if effect == "deny":
                allowed = False
                reason = trace_reason
            elif effect in {"require", "require_approval"}:
                requires_approval = True
                reason = trace_reason
            elif effect == "allow" and not any(item.effect == "deny" for item in traces):
                allowed = True
                if not reason:
                    reason = trace_reason
            if bool(rule.get("requires_confirmation", False)):
                requires_confirmation = True

        return PolicyDecision(
            allowed=allowed,
            requires_confirmation=requires_confirmation,
            requires_approval=requires_approval,
            reason=reason,
            matched_rules=matched,
            explanation=traces,
        )
