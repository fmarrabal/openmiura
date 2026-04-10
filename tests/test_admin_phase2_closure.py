from fastapi import FastAPI
from fastapi.testclient import TestClient

from openmiura.endpoints.admin import router


class _Obj:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _FakeAudit:
    def __init__(self):
        self.logged = []
    def table_counts(self):
        return {"sessions": 1, "messages": 2, "events": 3, "memory_items": 4, "telegram_state": 0, "identity_map": 1, "tool_calls": 0, "slack_event_dedupe": 0}
    def count_memory_items(self, user_key=None, kind=None):
        return 4 if user_key is None else 2
    def count_sessions(self, **kwargs):
        return 1
    def count_active_sessions(self, **kwargs):
        return 1
    def get_last_event(self, **kwargs):
        return {"channel": "system"}
    def get_recent_events(self, **kwargs):
        return [{"id": 1, "channel": "admin"}]
    def list_sessions(self, **kwargs):
        return [{"session_id": "s1", "channel": "http", "user_id": "u1", "last_message": None}]
    def search_memory_items(self, **kwargs):
        return [{"id": 1, "user_key": "u1", "kind": "fact", "text": "x", "meta": {}, "created_at": 0.0}]
    def delete_memory_item_by_id(self, item_id, user_key=None):
        return 1
    def list_identities(self, global_user_key=None):
        return [{"channel_user_key": "tg:1", "global_user_key": "curro", "linked_by": "admin", "linked_at": 0.0}]
    def log_event(self, **kwargs):
        self.logged.append(kwargs)


class _FakeRouter:
    def available_agents(self):
        return ["default", "researcher"]


class _FakeGW:
    def __init__(self):
        self.settings = _Obj(
            admin=_Obj(enabled=True, token="secret", max_search_results=100, rate_limit_per_minute=60),
            llm=_Obj(provider="ollama", model="qwen", base_url="http://127.0.0.1:11434"),
            memory=_Obj(enabled=True, embed_model="nomic"),
            storage=_Obj(db_path="data/audit.db"),
            agents_path="configs/agents.yaml",
            policies_path="configs/policies.yaml",
        )
        self.audit = _FakeAudit()
        self.router = _FakeRouter()
        self.policy = _Obj()
        self.telegram = None
        self.slack = None
        self.identity = _Obj(list_links=lambda g=None: [{"channel_user_key": "tg:1", "global_user_key": "curro", "linked_by": "admin", "linked_at": 0.0}], link=lambda c,g,linked_by="admin": None)
        self.started_at = 0.0
        self.tools = None
    def reload_dynamic_configs(self, force=False):
        return {"agents": {"changed": True}, "policies": {"changed": True}}


def _client():
    app = FastAPI()
    app.include_router(router)
    app.state.gw = _FakeGW()
    return TestClient(app)


def test_admin_status_and_reload_and_identities():
    with _client() as client:
        headers = {"Authorization": "Bearer secret"}
        r = client.get("/admin/status", headers=headers)
        assert r.status_code == 200
        assert r.json()["router"]["agents"] == ["default", "researcher"]

        r = client.post("/admin/reload", headers=headers)
        assert r.status_code == 200
        assert r.json()["agents"]["changed"] is True

        r = client.get("/admin/identities", headers=headers)
        assert r.status_code == 200
        assert r.json()["items"][0]["global_user_key"] == "curro"

        r = client.delete("/admin/memory/1", headers=headers)
        assert r.status_code == 200
        assert r.json()["deleted"] == 1

        r = client.get("/admin/sessions", headers=headers)
        assert r.status_code == 200

        r = client.get("/admin/events", headers=headers)
        assert r.status_code == 200
