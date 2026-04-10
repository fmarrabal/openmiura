from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

import app as app_module
from openmiura.core.audit import AuditStore
from openmiura.core.config import LLMSettings, RuntimeSettings, ServerSettings, Settings, StorageSettings
from openmiura.core.identity import IdentityManager
from openmiura.core.memory import MemoryEngine
from openmiura.core.policy import PolicyEngine
from openmiura.core.router import AgentRouter


class FakeEmbedder:
    def embed_one(self, text: str):
        t = (text or "").lower()
        if "almería" in t:
            return [1.0, 0.0, 0.0]
        return [0.2, 0.2, 0.2]


def _make_settings(tmp_path: Path) -> Settings:
    return Settings(
        server=ServerSettings(),
        storage=StorageSettings(db_path=str(tmp_path / "audit.db")),
        llm=LLMSettings(),
        runtime=RuntimeSettings(),
        agents={"default": {"name": "default", "system_prompt": "Base", "tools": []}},
        agents_path=str(tmp_path / "agents.yaml"),
        policies_path=str(tmp_path / "policies.yaml"),
    )


def test_agent_router_keyword_and_session_override(tmp_path: Path):
    (tmp_path / "agents.yaml").write_text(
        """
agents:
  - name: default
    system_prompt: base
    tools: []
    priority: 0
  - name: researcher
    system_prompt: research
    tools: [web_fetch]
    priority: 10
    keywords: [paper, review]
""",
        encoding="utf-8",
    )
    settings = _make_settings(tmp_path)
    store = AuditStore(str(tmp_path / "router.db"))
    store.init_db()
    router = AgentRouter(settings=settings, audit=store)

    assert router.route(channel="http", user_id="u1", text="please review this paper")["agent_id"] == "researcher"
    assert router.select_agent("s1", "researcher") is True
    assert router.route(channel="http", user_id="u1", text="hola", session_id="s1")["agent_id"] == "researcher"


def test_policy_engine_enforces_user_and_tool_rules(tmp_path: Path):
    (tmp_path / "policies.yaml").write_text(
        """
agent_rules:
  - agent: writer
    deny_tools: [fs_write]
user_rules:
  - user: "tg:99999"
    deny_agents: [admin_agent]
tool_rules:
  - tool: fs_write
    requires_confirmation: true
""",
        encoding="utf-8",
    )
    policy = PolicyEngine(str(tmp_path / "policies.yaml"))

    assert policy.check_agent_access("tg:99999", "admin_agent") is False
    decision = policy.check_tool_access("writer", "fs_write")
    assert decision.allowed is False
    assert decision.requires_confirmation is True


def test_identity_link_shares_memory_across_channels(tmp_path: Path):
    store = AuditStore(str(tmp_path / "identity.db"))
    store.init_db()
    identity = IdentityManager(store)
    mem = MemoryEngine(
        audit=store,
        base_url="http://127.0.0.1:11434",
        embed_model="fake-embed",
        top_k=5,
        min_score=0.1,
        scan_limit=50,
        max_items_per_user=100,
        dedupe_threshold=0.92,
    )
    mem.embedder = FakeEmbedder()

    identity.link("tg:1", "curro", linked_by="tg:1")
    identity.link("slack:T1:U2", "curro", linked_by="admin")

    mem.remember_text("curro", "fact", "Vivo en Almería")
    hits = mem.recall(user_key=identity.resolve("slack:T1:U2") or "", query="Almería")

    assert len(hits) == 1
    assert hits[0]["text"] == "Vivo en Almería"


class _FakeAuditAdmin:
    def __init__(self) -> None:
        self.logged = []
        self._identities = []

    def log_event(self, *args, **kwargs):
        self.logged.append({"args": args, "kwargs": kwargs})

    def list_identities(self, global_user_key=None):
        return list(self._identities)

    def set_identity(self, channel_user_key, global_user_key, linked_by="admin"):
        self._identities.append({
            "channel_user_key": channel_user_key,
            "global_user_key": global_user_key,
            "linked_by": linked_by,
            "linked_at": 0.0,
        })

    def count_memory_items(self, *args, **kwargs):
        return 0

    def table_counts(self):
        return {}


class _FakeGatewayAdmin:
    def __init__(self):
        self.settings = SimpleNamespace(
            llm=SimpleNamespace(provider="ollama", model="qwen", base_url="http://127.0.0.1:11434"),
            storage=SimpleNamespace(db_path="data/test.db"),
            admin=SimpleNamespace(enabled=True, token="secret", rate_limit_per_minute=60),
        )
        self.audit = _FakeAuditAdmin()
        self.identity = SimpleNamespace(
            list_links=lambda global_user_key=None: self.audit.list_identities(global_user_key),
            link=lambda c, g, linked_by="admin": self.audit.set_identity(c, g, linked_by),
        )
        self.telegram = None
        self.slack = None
        self.tools = None
        self.started_at = 0.0
        self.reload_dynamic_configs = lambda: {"agents": True, "policies": True}


def test_admin_identity_link_and_reload():
    gw = _FakeGatewayAdmin()
    app = app_module.create_app(gateway_factory=lambda _config: gw)
    with TestClient(app) as client:
        response = client.post(
            "/admin/identities/link",
            headers={"Authorization": "Bearer secret"},
            json={"channel_user_key": "tg:1", "global_user_key": "curro", "linked_by": "admin"},
        )
        assert response.status_code == 200
        reload_resp = client.post("/admin/reload", headers={"Authorization": "Bearer secret"})
        assert reload_resp.status_code == 200
        identities = client.get("/admin/identities", headers={"Authorization": "Bearer secret"})
        assert identities.status_code == 200
        assert identities.json()["items"][0]["global_user_key"] == "curro"
