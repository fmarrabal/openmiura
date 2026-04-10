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
                "allowed": True,
                "requires_confirmation": True,
                "requires_approval": False,
                "reason": "tool use requires confirmation",
                "matched_rules": ["confirm_sensitive_tool"],
                "explanation": [
                    {
                        "scope": "tool",
                        "name": "confirm_sensitive_tool",
                        "effect": "allow",
                        "reason": "tool use requires confirmation",
                    }
                ],
                "metadata": {},
            },
            "context": kwargs,
            "signature": "abc123",
        }

    def signature(self):
        return "abc123"


class _FakeSandbox:
    def profiles_catalog(self):
        return {"restricted": {}, "local-safe": {}}

    def explain(self, **kwargs):
        return {
            "ok": True,
            "profile_name": "restricted",
            "source": "role_profile",
            "matched_selector": "",
            "profile": {"tool_permissions": {"fs_write": False}},
            "tool_allowed": False,
            "network_enabled": False,
            "explanation": [{"scope": "role", "name": "user", "reason": "role mapped", "matched": True}],
        }


class _FakeAudit:
    def __init__(self):
        self.logged = []
        self._next_id = 1

    def table_counts(self):
        return {"events": 0}

    def count_memory_items(self, *args, **kwargs):
        return 0

    def count_sessions(self, **kwargs):
        return 0

    def count_active_sessions(self, **kwargs):
        return 0

    def get_last_event(self, **kwargs):
        return None

    def log_event(self, **kwargs):
        payload = dict(kwargs)
        payload["id"] = self._next_id
        self.logged.append(payload)
        self._next_id += 1
        return payload["id"]


class _FakeGateway:
    def __init__(self):
        self.settings = SimpleNamespace(
            llm=SimpleNamespace(provider="ollama", model="qwen", base_url="http://127.0.0.1:11434"),
            memory=SimpleNamespace(enabled=False, embed_model=""),
            storage=SimpleNamespace(db_path=":memory:"),
            admin=SimpleNamespace(enabled=True, token="secret", max_search_results=5),
            sandbox=SimpleNamespace(enabled=True, default_profile="restricted"),
        )
        self.telegram = None
        self.slack = None
        self.audit = _FakeAudit()
        self.tools = SimpleNamespace(registry=SimpleNamespace(_tools={}))
        self.policy = _FakePolicy()
        self.router = None
        self.identity = None
        self.sandbox = _FakeSandbox()
        self.secret_broker = None
        self.started_at = 0.0


def test_admin_security_explain_combines_policy_and_sandbox():
    gw = _FakeGateway()
    app = app_module.create_app(gateway_factory=lambda _config: gw)
    with TestClient(app) as client:
        response = client.post(
            "/admin/security/explain",
            headers={"Authorization": "Bearer secret"},
            json={
                "scope": "tool",
                "resource_name": "fs_write",
                "agent_name": "default",
                "user_role": "user",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["final_state"] == "denied"
    assert data["allowed"] is False
    assert data["requires_confirmation"] is True
    assert data["components"]["sandbox"]["profile_name"] == "restricted"
    assert data["user_explanation"]["message"] == "Action denied for tool 'fs_write'."
    assert data["audit_event_id"] == 1
    assert any(item["payload"].get("action") == "security_explain" for item in gw.audit.logged)
