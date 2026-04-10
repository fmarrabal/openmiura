from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatch
from typing import Any


def _norm(value: Any) -> str:
    return str(value or "").strip()


def _norm_lower(value: Any) -> str:
    return _norm(value).lower()


def _norm_list(value: Any, *, lower: bool = False) -> list[str]:
    out: list[str] = []
    for item in list(value or []):
        text = _norm_lower(item) if lower else _norm(item)
        if text:
            out.append(text)
    return out


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base or {})
    for key, value in dict(override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(dict(merged.get(key) or {}), dict(value or {}))
        else:
            merged[key] = value
    return merged


@dataclass(slots=True)
class SandboxTrace:
    scope: str
    name: str
    reason: str = ""
    matched: bool = True


@dataclass(slots=True)
class SandboxProfileDecision:
    profile_name: str
    profile: dict[str, Any]
    source: str
    matched_selector: str = ""
    explanation: list[SandboxTrace] = field(default_factory=list)

    def tool_permissions(self) -> dict[str, bool]:
        raw = dict(self.profile.get("tool_permissions") or {})
        return {str(k): bool(v) for k, v in raw.items()}

    def allows_tool(self, tool_name: str) -> bool:
        tool = _norm_lower(tool_name)
        permissions = self.tool_permissions()
        direct = permissions.get(tool)
        if direct is not None:
            return bool(direct)
        if tool == "terminal_exec":
            return bool(permissions.get("terminal_exec", permissions.get("terminal", True)))
        if tool == "web_fetch":
            if permissions.get("network") is False:
                return False
            return bool(permissions.get("web_fetch", True))
        if tool == "fs_read":
            return bool(permissions.get("fs_read", permissions.get("filesystem_read", True)))
        if tool == "fs_write":
            return bool(permissions.get("fs_write", permissions.get("filesystem_write", True)))
        return True

    def network_enabled(self) -> bool:
        network = dict(self.profile.get("network") or {})
        permissions = self.tool_permissions()
        if permissions.get("network") is False:
            return False
        return bool(network.get("enabled", True))

    def terminal_overrides(self) -> dict[str, Any]:
        return dict(self.profile.get("terminal") or {})

    def web_fetch_overrides(self) -> dict[str, Any]:
        return dict(self.profile.get("web_fetch") or {})

    def filesystem_overrides(self) -> dict[str, Any]:
        return dict(self.profile.get("filesystem") or {})

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_name": self.profile_name,
            "source": self.source,
            "matched_selector": self.matched_selector,
            "profile": dict(self.profile),
            "explanation": [
                {
                    "scope": item.scope,
                    "name": item.name,
                    "reason": item.reason,
                    "matched": item.matched,
                }
                for item in self.explanation
            ],
        }


class SandboxManager:
    def __init__(self, settings: Any, audit: Any | None = None) -> None:
        self.settings = settings
        self.audit = audit

    @staticmethod
    def builtin_profiles() -> dict[str, dict[str, Any]]:
        return {
            "local-safe": {
                "description": "Balanced local execution profile.",
                "tool_permissions": {
                    "terminal_exec": True,
                    "web_fetch": True,
                    "network": True,
                    "fs_read": True,
                    "fs_write": True,
                },
                "network": {"enabled": True},
                "filesystem": {"read_only": False, "max_write_chars": 1000000},
                "terminal": {
                    "allow_shell": True,
                    "allow_shell_metacharacters": True,
                    "allow_multiline": False,
                    "require_explicit_allowlist": False,
                    "max_timeout_s": 120,
                },
                "web_fetch": {
                    "enabled": True,
                    "timeout_s": 20,
                    "max_bytes": 250000,
                },
            },
            "corporate-safe": {
                "description": "Constrained enterprise-safe profile with network and shell restrictions.",
                "tool_permissions": {
                    "terminal_exec": True,
                    "web_fetch": True,
                    "network": True,
                    "fs_read": True,
                    "fs_write": True,
                },
                "network": {"enabled": True},
                "filesystem": {"read_only": False, "max_write_chars": 250000},
                "terminal": {
                    "allow_shell": False,
                    "allow_shell_metacharacters": False,
                    "allow_multiline": False,
                    "require_explicit_allowlist": False,
                    "max_timeout_s": 30,
                },
                "web_fetch": {
                    "enabled": True,
                    "allow_all_domains": False,
                    "timeout_s": 15,
                    "max_bytes": 200000,
                },
            },
            "restricted": {
                "description": "Read-mostly profile for sensitive environments.",
                "tool_permissions": {
                    "terminal_exec": False,
                    "web_fetch": False,
                    "network": False,
                    "fs_read": True,
                    "fs_write": False,
                },
                "network": {"enabled": False},
                "filesystem": {"read_only": True, "max_write_chars": 0},
                "terminal": {
                    "allow_shell": False,
                    "allow_shell_metacharacters": False,
                    "allow_multiline": False,
                    "require_explicit_allowlist": True,
                    "max_timeout_s": 5,
                },
                "web_fetch": {
                    "enabled": False,
                    "allow_all_domains": False,
                    "timeout_s": 5,
                    "max_bytes": 50000,
                },
            },
            "air-gapped-like": {
                "description": "No-network profile for isolated operation with constrained local execution.",
                "tool_permissions": {
                    "terminal_exec": True,
                    "web_fetch": False,
                    "network": False,
                    "fs_read": True,
                    "fs_write": True,
                },
                "network": {"enabled": False},
                "filesystem": {"read_only": False, "max_write_chars": 250000},
                "terminal": {
                    "allow_shell": False,
                    "allow_shell_metacharacters": False,
                    "allow_multiline": False,
                    "require_explicit_allowlist": True,
                    "max_timeout_s": 20,
                },
                "web_fetch": {
                    "enabled": False,
                    "allow_all_domains": False,
                    "timeout_s": 5,
                    "max_bytes": 50000,
                },
            },
        }

    def profiles_catalog(self) -> dict[str, dict[str, Any]]:
        sandbox_cfg = getattr(self.settings, "sandbox", None)
        configured = dict(getattr(sandbox_cfg, "profiles", {}) or {}) if sandbox_cfg is not None else {}
        catalog = {name: dict(profile) for name, profile in self.builtin_profiles().items()}
        for name, override in configured.items():
            key = _norm(name)
            if not key:
                continue
            base = dict(catalog.get(key) or {})
            catalog[key] = _deep_merge(base, dict(override or {}))
        return catalog

    def _match_selector_values(self, actual: str, candidates: list[str], *, lower: bool = False) -> bool:
        if not candidates:
            return True
        value = _norm_lower(actual) if lower else _norm(actual)
        if not value:
            return False
        for candidate in candidates:
            pattern = _norm_lower(candidate) if lower else _norm(candidate)
            if not pattern:
                continue
            if pattern == "*" or value == pattern or fnmatch(value, pattern):
                return True
        return False

    def _selector_matches(
        self,
        selector: dict[str, Any],
        *,
        user_role: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        channel: str | None = None,
        agent_name: str | None = None,
        tool_name: str | None = None,
    ) -> bool:
        return (
            self._match_selector_values(user_role or "", _norm_list(selector.get("roles"), lower=True), lower=True)
            and self._match_selector_values(tenant_id or "", _norm_list(selector.get("tenants")))
            and self._match_selector_values(workspace_id or "", _norm_list(selector.get("workspaces")))
            and self._match_selector_values(environment or "", _norm_list(selector.get("environments"), lower=True), lower=True)
            and self._match_selector_values(channel or "", _norm_list(selector.get("channels"), lower=True), lower=True)
            and self._match_selector_values(agent_name or "", _norm_list(selector.get("agents"), lower=True), lower=True)
            and self._match_selector_values(tool_name or "", _norm_list(selector.get("tools"), lower=True), lower=True)
        )

    def resolve(
        self,
        *,
        user_role: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        channel: str | None = None,
        agent_name: str | None = None,
        tool_name: str | None = None,
    ) -> SandboxProfileDecision:
        sandbox_cfg = getattr(self.settings, "sandbox", None)
        catalog = self.profiles_catalog()
        enabled = bool(getattr(sandbox_cfg, "enabled", True) if sandbox_cfg is not None else True)
        default_profile = _norm(getattr(sandbox_cfg, "default_profile", "local-safe") if sandbox_cfg is not None else "local-safe") or "local-safe"
        role_key = _norm_lower(user_role or "user") or "user"
        role_profiles = dict(getattr(sandbox_cfg, "role_profiles", {}) or {}) if sandbox_cfg is not None else {}
        selectors = list(getattr(sandbox_cfg, "selectors", []) or []) if sandbox_cfg is not None else []

        selected_name = default_profile
        source = "default_profile"
        explanation = [SandboxTrace(scope="sandbox", name=default_profile, reason="default profile")]
        matched_selector = ""

        if not enabled:
            selected_name = default_profile
            source = "disabled"
            explanation.append(SandboxTrace(scope="sandbox", name="sandbox_disabled", reason="sandbox layer disabled"))
        else:
            role_profile = _norm(role_profiles.get(role_key))
            if role_profile:
                selected_name = role_profile
                source = "role_profile"
                explanation.append(SandboxTrace(scope="role", name=role_key, reason=f"role mapped to '{role_profile}'"))

            for idx, raw_selector in enumerate(selectors, start=1):
                if isinstance(raw_selector, dict):
                    selector = dict(raw_selector or {})
                else:
                    selector = {
                        "name": getattr(raw_selector, "name", ""),
                        "profile": getattr(raw_selector, "profile", ""),
                        "roles": list(getattr(raw_selector, "roles", []) or []),
                        "tenants": list(getattr(raw_selector, "tenants", []) or []),
                        "workspaces": list(getattr(raw_selector, "workspaces", []) or []),
                        "environments": list(getattr(raw_selector, "environments", []) or []),
                        "channels": list(getattr(raw_selector, "channels", []) or []),
                        "agents": list(getattr(raw_selector, "agents", []) or []),
                        "tools": list(getattr(raw_selector, "tools", []) or []),
                    }
                if not self._selector_matches(
                    selector,
                    user_role=user_role,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    environment=environment,
                    channel=channel,
                    agent_name=agent_name,
                    tool_name=tool_name,
                ):
                    continue
                profile_name = _norm(selector.get("profile"))
                if not profile_name:
                    continue
                selector_name = _norm(selector.get("name")) or f"selector[{idx}]"
                selected_name = profile_name
                source = "selector"
                matched_selector = selector_name
                explanation.append(SandboxTrace(scope="selector", name=selector_name, reason=f"selector chose '{profile_name}'"))

        profile = dict(catalog.get(selected_name) or catalog.get(default_profile) or self.builtin_profiles()["local-safe"])
        if selected_name not in catalog:
            explanation.append(SandboxTrace(scope="sandbox", name=selected_name, reason="profile not found; fallback applied"))
            selected_name = default_profile if default_profile in catalog else "local-safe"
            profile = dict(catalog.get(selected_name) or self.builtin_profiles()["local-safe"])
            source = f"{source}:fallback"

        return SandboxProfileDecision(
            profile_name=selected_name,
            profile=profile,
            source=source,
            matched_selector=matched_selector,
            explanation=explanation,
        )

    def explain(
        self,
        *,
        user_role: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        channel: str | None = None,
        agent_name: str | None = None,
        tool_name: str | None = None,
    ) -> dict[str, Any]:
        decision = self.resolve(
            user_role=user_role,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            channel=channel,
            agent_name=agent_name,
            tool_name=tool_name,
        )
        return {
            "ok": True,
            "profile_name": decision.profile_name,
            "source": decision.source,
            "matched_selector": decision.matched_selector,
            "profile": dict(decision.profile),
            "tool_allowed": decision.allows_tool(tool_name or "") if tool_name else None,
            "network_enabled": decision.network_enabled(),
            "explanation": [
                {
                    "scope": item.scope,
                    "name": item.name,
                    "reason": item.reason,
                    "matched": item.matched,
                }
                for item in decision.explanation
            ],
        }
