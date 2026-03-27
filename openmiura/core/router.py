from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict

import yaml

from .audit import AuditStore
from .config import Settings


class AgentRouter:
    def __init__(self, settings: Settings, audit: AuditStore):
        self.settings = settings
        self.audit = audit
        self.agents_path = str(getattr(settings, "agents_path", "configs/agents.yaml"))
        self._signature: str | None = None
        self._session_agent: dict[str, str] = {}
        self.agents: dict[str, dict[str, Any]] = {}
        self.reload_agents(force=True)

    def _file_signature(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def _normalize_agent(name: str, cfg: Any) -> dict[str, Any]:
        if isinstance(cfg, dict):
            row = dict(cfg)
        elif hasattr(cfg, "model_dump"):
            row = dict(cfg.model_dump())
        elif hasattr(cfg, "__dict__"):
            row = dict(vars(cfg))
        else:
            row = {}

        row["name"] = str(row.get("name") or name).strip() or name
        row["keywords"] = [
            str(k).strip()
            for k in (row.get("keywords") or [])
            if str(k).strip()
        ]
        row["priority"] = int(row.get("priority", 0) or 0)
        row["tools"] = list(row.get("allowed_tools", row.get("tools", [])) or [])
        row["system_prompt"] = str(
            row.get("system_prompt") or "You are openMiura."
        )
        return row

    def _normalize_agents_map(self, source: dict[str, Any]) -> dict[str, dict[str, Any]]:
        parsed: dict[str, dict[str, Any]] = {}

        for name, cfg in (source or {}).items():
            agent_name = str(name or "").strip()
            if not agent_name:
                continue
            parsed[agent_name] = self._normalize_agent(agent_name, cfg)

        if not parsed:
            parsed = {
                "default": self._normalize_agent(
                    "default",
                    {
                        "name": "default",
                        "system_prompt": "You are openMiura.",
                        "tools": [],
                        "keywords": [],
                        "priority": 0,
                    },
                )
            }

        if "default" not in parsed:
            first_name = sorted(
                parsed,
                key=lambda n: int(parsed[n].get("priority", 0) or 0),
                reverse=True,
            )[0]
            parsed["default"] = {
                **parsed[first_name],
                "name": "default",
                "keywords": [],
                "priority": -1,
            }

        return parsed

    def reload_agents(self, force: bool = False) -> dict[str, Any]:
        inline_agents = dict(getattr(self.settings, "agents", {}) or {})
        p = Path(self.agents_path)

        normalized_path = str(p).replace("\\", "/").strip()
        is_default_agents_path = normalized_path in {
            "configs/agents.yaml",
            "./configs/agents.yaml",
        }

        # Regla:
        # - Si el path es el por defecto y ya vienen agentes inline en settings,
        #   usamos settings.agents para no depender del repo local.
        # - Si el path es específico/custom y el fichero existe, manda el fichero.
        # - Si el fichero no existe, fallback a settings.agents.
        if inline_agents and (is_default_agents_path or not p.exists()):
            normalized = self._normalize_agents_map(inline_agents)
            changed = normalized != self.agents
            self.agents = normalized
            valid = set(normalized.keys())
            self._session_agent = {
                k: v for k, v in self._session_agent.items() if v in valid
            }
            return {
                "changed": changed,
                "count": len(self.agents),
                "reason": "settings_agents",
                "agents": sorted(self.agents.keys()),
            }

        if not p.exists():
            self.agents = self._normalize_agents_map({})
            return {
                "changed": False,
                "count": len(self.agents),
                "reason": "missing_file",
                "agents": sorted(self.agents.keys()),
            }

        sig = self._file_signature(p)
        if not force and self._signature == sig:
            return {
                "changed": False,
                "count": len(self.agents),
                "reason": "unchanged",
                "agents": sorted(self.agents.keys()),
            }

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
                parsed[name] = self._normalize_agent(name, item)

            parsed = self._normalize_agents_map(parsed)

            changed = parsed != self.agents
            self.agents = parsed

            try:
                self.settings.agents.clear()
                self.settings.agents.update(parsed)
            except Exception:
                pass

            self._signature = sig
            valid = set(parsed.keys())
            self._session_agent = {
                k: v for k, v in self._session_agent.items() if v in valid
            }

            return {
                "changed": changed,
                "count": len(self.agents),
                "reason": "reloaded",
                "agents": sorted(self.agents.keys()),
            }
        except Exception as e:
            self.agents = previous
            return {
                "changed": False,
                "count": len(self.agents),
                "reason": f"reload_failed: {e!r}",
                "agents": sorted(self.agents.keys()),
            }
        
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

    def route(
        self,
        channel: str,
        user_id: str,
        text: str,
        session_id: str | None = None,
    ) -> Dict[str, str]:
        self.reload_agents()

        if session_id and session_id in self._session_agent:
            return {
                "agent_id": self._session_agent[session_id],
                "reason": "session_override",
            }

        low = (text or "").lower().strip()

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

            keywords = [
                str(k).strip().lower()
                for k in (cfg.get("keywords") or [])
                if str(k).strip()
            ]
            score = sum(1 for k in keywords if k in low)
            priority = int(cfg.get("priority", 0) or 0)

            if score > 0 and (
                score > best_score
                or (score == best_score and priority > best_priority)
            ):
                best_name = name
                best_score = score
                best_priority = priority

        return {
            "agent_id": best_name,
            "reason": "keyword" if best_score > 0 else "default",
        }


Router = AgentRouter