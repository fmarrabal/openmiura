from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

import app as app_module


class _FakePolicy:
    def explain_request(self, **kwargs):
        return {
            "ok": True,
            "scope": kwargs["scope"],
            "resource_name": kwargs["resource_name"],
            "decision": {
                "allowed": False,
                "requires_confirmation": False,
                "requires_approval": True,
                "reason": "write operations require approval",
                "matched_rules": ["require_fs_write_admin_approval"],
                "explanation": [
                    {
                        "scope": "approval",
                        "name": "require_fs_write_admin_approval",
                        "effect": "require_approval",
                        "reason": "write operations require approval",
                    }
                ],
                "metadata": {},
            },
            "context": kwargs,
            "signature": "abc123",
        }

    def signature(self):
        return "abc123"


class _FakeAudit:
    def __init__(self):
        self.logged = []

    def table_counts(self):
        return {"memory_items": 0}

    def count_memory_items(self, *args, **kwargs):
        return 0

    def count_sessions(self, **kwargs):
        return 0

    def count_active_sessions(self, **kwargs):
        return 0

    def get_last_event(self, **kwargs):
        return None

    def log_event(self, **kwargs):
        self.logged.append(kwargs)


class _FakeGateway:
    def __init__(self):
        self.settings = SimpleNamespace(
            llm=SimpleNamespace(provider="ollama", model="qwen", base_url="http://127.0.0.1:11434"),
            memory=SimpleNamespace(enabled=False, embed_model=""),
            storage=SimpleNamespace(db_path=":memory:"),
            admin=SimpleNamespace(enabled=True, token="secret", max_search_results=5),
        )
        self.telegram = None
        self.slack = None
        self.audit = _FakeAudit()
        self.tools = SimpleNamespace(registry=SimpleNamespace(_tools={}))
        self.policy = _FakePolicy()
        self.router = None
        self.identity = None
        self.started_at = 0.0


def test_admin_policy_explain_endpoint_returns_decision():
    gw = _FakeGateway()
    app = app_module.create_app(gateway_factory=lambda _config: gw)
    with TestClient(app) as client:
        response = client.post(
            "/admin/policies/explain",
            headers={"Authorization": "Bearer secret"},
            json={
                "scope": "approval",
                "resource_name": "fs_write",
                "user_role": "operator",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["decision"]["requires_approval"] is True
    assert data["decision"]["matched_rules"] == ["require_fs_write_admin_approval"]
    assert any(item["payload"].get("action") == "policy_explain" for item in gw.audit.logged)
