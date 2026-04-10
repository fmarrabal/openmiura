from __future__ import annotations

from types import SimpleNamespace

from openmiura.core.audit import AuditStore
from openmiura.core.schema import InboundMessage
from openmiura.pipeline import process_message


class _FakeRouter:
    def route(self, *, channel: str, user_id: str, text: str, session_id: str):
        return {"agent_id": "default"}


class _FakeMemory:
    def recall(self, *, user_key: str, query: str, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None):
        return [
            {
                "id": 7,
                "kind": "fact",
                "text": "El usuario trabaja en espectroscopía",
                "score": 0.91,
                "tier": "medium",
            }
        ]

    def format_context(self, hits):
        return "contexto"

    def maybe_remember_user_text(self, *, user_key: str, user_text: str, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None):
        return True


class _FakeRuntime:
    def generate_reply(self, **kwargs):
        trace = kwargs.get("trace_collector") or {}
        trace["provider"] = "ollama"
        trace["model"] = "qwen2.5:7b-instruct"
        trace["latency_ms"] = 33.3
        trace["usage"] = {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}
        trace["tools_considered"] = [
            {
                "name": "time_now",
                "allowed": True,
                "requires_confirmation": False,
                "reason": "matched allow rule",
                "matched_rules": [{"scope": "tool", "name": "allow_time"}],
                "sandbox_profile": "local-safe",
            }
        ]
        trace["policies_applied"] = [
            {
                "tool_name": "time_now",
                "allowed": True,
                "requires_confirmation": False,
                "reason": "matched allow rule",
                "matched_rules": [{"scope": "tool", "name": "allow_time"}],
                "sandbox_profile": "local-safe",
            }
        ]
        trace["tools_used"] = [
            {
                "tool_name": "time_now",
                "args": {},
                "ok": True,
                "duration_ms": 12.5,
                "result_excerpt": "2026-03-20T12:00:00Z",
                "error": "",
                "sandbox_profile": "local-safe",
            }
        ]
        trace["decisions"] = {"agent_access": {"allowed": True, "agent_id": "default"}, "tool_rounds": 1}
        trace["status"] = "completed"
        trace["response_text"] = "respuesta trazada"
        return "respuesta trazada"


class _FakeRealtime:
    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    def publish(self, event_name: str, **payload):
        self.events.append((event_name, payload))


class _GatewayForTracePipeline:
    def __init__(self):
        self.audit = AuditStore(":memory:")
        self.audit.init_db()
        self.settings = SimpleNamespace(
            llm=SimpleNamespace(provider="ollama", model="qwen2.5:7b-instruct"),
            runtime=SimpleNamespace(history_limit=4),
            admin=SimpleNamespace(enabled=False, token=""),
        )
        self.router = _FakeRouter()
        self.runtime = _FakeRuntime()
        self.memory = _FakeMemory()
        self.tools = object()
        self.policy = None
        self.realtime_bus = _FakeRealtime()

    def effective_user_key(self, channel_user_key: str) -> str:
        return channel_user_key

    def derive_session_id(self, msg, user_key: str) -> str:
        return str(msg.session_id or "sess-1")

    def link_hint(self, channel_user_key: str) -> str:
        return ""


def test_process_message_persists_decision_trace_with_memory_tools_and_usage() -> None:
    gw = _GatewayForTracePipeline()
    outbound = process_message(
        gw,
        InboundMessage(channel="http", user_id="user:1", text="hola", session_id="sess-1"),
    )

    assert outbound.text == "respuesta trazada"

    traces = gw.audit.list_decision_traces(limit=10)
    assert len(traces) == 1
    item = traces[0]
    assert item["session_id"] == "sess-1"
    assert item["agent_id"] == "default"
    assert item["provider"] == "ollama"
    assert item["model"] == "qwen2.5:7b-instruct"
    assert item["latency_ms"] == 33.3
    assert item["input_tokens"] == 11
    assert item["output_tokens"] == 7
    assert item["total_tokens"] == 18
    assert item["memory"]["hit_count"] == 1
    assert item["memory"]["items"][0]["kind"] == "fact"
    assert item["tools_considered"][0]["name"] == "time_now"
    assert item["tools_used"][0]["tool_name"] == "time_now"
    assert item["policies"][0]["tool_name"] == "time_now"
    assert item["decisions"]["tool_rounds"] == 1
    assert any(name == "decision_trace_recorded" for name, _ in gw.realtime_bus.events)
