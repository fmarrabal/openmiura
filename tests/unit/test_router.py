from __future__ import annotations

from openmiura.core.audit import AuditStore
from openmiura.core.router import AgentRouter


def test_router_routes_by_command_keyword_and_default(settings_factory, tmp_path):
    settings = settings_factory(
        agents={
            "default": {"name": "default", "system_prompt": "base"},
            "researcher": {"name": "researcher", "keywords": ["paper", "study"], "priority": 5},
            "writer": {"name": "writer", "keywords": ["draft"], "priority": 3},
        }
    )
    audit = AuditStore(str(tmp_path / "router.db"))
    audit.init_db()
    router = AgentRouter(settings, audit)

    assert router.route("http", "u1", "hola")["agent_id"] == "default"
    assert router.route("http", "u1", "quiero un paper sobre IA")["agent_id"] == "researcher"
    assert router.route("http", "u1", "/agent writer")["agent_id"] == "writer"


def test_router_priority_breaks_keyword_ties(settings_factory, tmp_path):
    settings = settings_factory(
        agents={
            "default": {"name": "default", "system_prompt": "base"},
            "alpha": {"name": "alpha", "keywords": ["nmr"], "priority": 1},
            "beta": {"name": "beta", "keywords": ["nmr"], "priority": 10},
        }
    )
    audit = AuditStore(str(tmp_path / "router-priority.db"))
    audit.init_db()
    router = AgentRouter(settings, audit)

    routed = router.route("http", "u1", "nmr diffusion")
    assert routed["agent_id"] == "beta"
    assert routed["reason"] == "keyword"
