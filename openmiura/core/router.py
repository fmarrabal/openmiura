from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict

import yaml

from .config import Settings
from .audit import AuditStore


class AgentRouter:
    def __init__(self, settings: Settings, audit: AuditStore):
        self.settings = settings
        self.audit = audit
        self.agents_path = str(getattr(settings, "agents_path", "configs/agents.yaml"))
        self._signature: str | None = None
        self._session_agent: dict[str, str] = {}
        self.agents = dict(settings.agents or {})
        self.reload_agents(force=True)

    def _file_signature(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def reload_agents(self, force: bool = False) -> dict[str, Any]:
        p = Path(self.agents_path)
        if not p.exists():
            if not self.agents:
                self.agents = {"default": {"name": "default", "system_prompt": "You are openMiura.", "tools": []}}
            return {"changed": False, "count": len(self.agents), "reason": "missing_file", "agents": sorted(self.agents.keys())}

        sig = self._file_signature(p)
        if not force and self._signature == sig:
            return {"changed": False, "count": len(self.agents), "reason": "unchanged", "agents": sorted(self.agents.keys())}

        previous = dict(self.agents)
        try:
            raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            agents_list = raw.get("agents", raw if isinstance(raw, list) else [])
            parsed: dict[str, dict[str, Any]] = {}
            for item in agents_list:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                row = dict(item)
                row.setdefault("keywords", [])
                row.setdefault("priority", 0)
                row.setdefault("tools", row.get("allowed_tools", row.get("tools", [])))
                row.setdefault("system_prompt", "You are openMiura.")
                parsed[name] = row
            if not parsed:
                parsed = dict(self.settings.agents or previous or {"default": {"name": "default", "system_prompt": "You are openMiura.", "tools": []}})
            if "default" not in parsed:
                first_name = sorted(parsed, key=lambda n: int(parsed[n].get("priority", 0) or 0), reverse=True)[0]
                parsed["default"] = {**parsed[first_name], "name": "default"}
            self.agents = parsed
            try:
                self.settings.agents.clear()
                self.settings.agents.update(parsed)
            except Exception:
                pass
            self._signature = sig
            valid = set(parsed.keys())
            self._session_agent = {k: v for k, v in self._session_agent.items() if v in valid}
            return {"changed": True, "count": len(self.agents), "reason": "reloaded", "agents": sorted(self.agents.keys())}
        except Exception as e:
            self.agents = previous
            return {"changed": False, "count": len(self.agents), "reason": f"reload_failed: {e!r}", "agents": sorted(self.agents.keys())}

    def available_agents(self) -> list[str]:
        self.reload_agents()
        return sorted(self.agents.keys())

    def select_agent(self, session_id: str, agent_name: str) -> bool:
        self.reload_agents()
        if agent_name not in self.agents:
            return False
        self._session_agent[session_id] = agent_name
        return True

    def clear_agent(self, session_id: str) -> None:
        self._session_agent.pop(session_id, None)

    def route(self, channel: str, user_id: str, text: str, session_id: str | None = None) -> Dict[str, str]:
        self.reload_agents()
        if session_id and session_id in self._session_agent:
            return {"agent_id": self._session_agent[session_id], "reason": "session_override"}

        low = (text or "").lower()
        if low.startswith("/agent "):
            parts = low.split(maxsplit=2)
            if len(parts) > 1:
                candidate = parts[1].strip()
                if candidate in self.agents:
                    return {"agent_id": candidate, "reason": "explicit"}

        best_name = "default"
        best_score = -1
        best_priority = -(10**9)
        for name, cfg in self.agents.items():
            if name == "default":
                continue
            keywords = [str(k).strip().lower() for k in (cfg.get("keywords") or []) if str(k).strip()]
            score = sum(1 for k in keywords if k in low)
            priority = int(cfg.get("priority", 0) or 0)
            if score > 0 and (score > best_score or (score == best_score and priority > best_priority)):
                best_name = name
                best_score = score
                best_priority = priority

        return {"agent_id": best_name, "reason": "keyword" if best_score > 0 else "default"}


Router = AgentRouter
