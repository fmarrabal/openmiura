from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

import app as app_module
from openmiura.core.audit import AuditStore


class _RecordingMemory:
    def __init__(self):
        self.remembered: list[tuple[str, str]] = []

    def recall(self, user_key: str, query: str):
        return []

    def format_context(self, hits):
        return ""

    def maybe_remember_user_text(self, user_key: str, user_text: str):
        self.remembered.append((user_key, user_text))
        return True


class _FakeRuntime:
    def generate_reply(self, **kwargs):
        return "respuesta desde runtime"


class _FakeRouter:
    def __init__(self):
        self._session_agent = {}

    def route(self, **kwargs):
        return {"agent_id": "default"}

    def available_agents(self):
        return ["default"]

    def clear_agent(self, session_id):
        self._session_agent.pop(session_id, None)


class _FakeGW:
    def __init__(self):
        self.audit = AuditStore(":memory:")
        self.audit.init_db()
        self.settings = SimpleNamespace(
            llm=SimpleNamespace(model="m", provider="ollama", base_url="http://127.0.0.1:11434", timeout_s=5),
            memory=SimpleNamespace(embed_model="e"),
            runtime=SimpleNamespace(default_session_prefix={"http": "http"}, confirmation_cleanup_interval_s=60),
            telegram=None,
            slack=None,
            discord=None,
            admin=SimpleNamespace(enabled=False),
        )
        self.router = _FakeRouter()
        self.runtime = _FakeRuntime()
        self.memory = _RecordingMemory()
        self.tools = None
        self.policy = None
        self.identity = None
        self.started_at = 0
        self._cleaned = 0

    def effective_user_key(self, channel_user_key):
        return channel_user_key

    def derive_session_id(self, msg, user_key):
        return f"http-{user_key}"

    def link_hint(self, channel_user_key):
        return ""

    def has_identity_link(self, channel_user_key):
        return False

    def is_telegram_allowed(self, *args, **kwargs):
        return True

    def cleanup_expired_tool_confirmations(self):
        self._cleaned += 1
        return 0


def test_http_message_flow_records_session_memory_and_audit():
    gw = _FakeGW()
    with TestClient(app_module.create_app(gateway_factory=lambda _config: gw)) as client:
        response = client.post(
            "/http/message",
            json={"channel": "http", "user_id": "u1", "text": "Vivo en Almería desde hace años"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["text"] == "respuesta desde runtime"

    assert gw.audit.count_sessions() == 1
    last = gw.audit.get_last_message("http-u1")
    assert last is not None
    assert "respuesta desde runtime" in last["content"]

    events = gw.audit.get_recent_events(limit=10, channel="http")
    directions = {event["direction"] for event in events}
    assert {"in", "out"}.issubset(directions)
    assert gw.memory.remembered == [("u1", "Vivo en Almería desde hace años")]
