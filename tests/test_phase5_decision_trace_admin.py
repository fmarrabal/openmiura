from __future__ import annotations

import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

import app as app_module
from openmiura.core.audit import AuditStore


class _GatewayForTraceAdmin:
    def __init__(self, *, audit: AuditStore):
        self.settings = SimpleNamespace(
            llm=SimpleNamespace(provider="ollama", model="qwen2.5:7b-instruct", base_url="http://127.0.0.1:11434"),
            memory=SimpleNamespace(enabled=False, embed_model=""),
            storage=SimpleNamespace(db_path=":memory:"),
            admin=SimpleNamespace(enabled=True, token="secret", max_search_results=5, rate_limit_per_minute=60),
            sandbox=SimpleNamespace(enabled=True, default_profile="local-safe"),
        )
        self.telegram = None
        self.slack = None
        self.audit = audit
        self.tools = SimpleNamespace(registry=SimpleNamespace(_tools={"time_now": object()}))
        self.policy = None
        self.router = None
        self.identity = None
        self.sandbox = SimpleNamespace(profiles_catalog=lambda: {"local-safe": {}})
        self.secret_broker = SimpleNamespace(is_enabled=lambda: False)
        self.started_at = 0.0


def test_admin_trace_endpoints_and_session_inspector() -> None:
    audit = AuditStore(":memory:")
    audit.init_db()
    session_id = audit.get_or_create_session("http", "user:1", "sess-1")
    audit.append_message(session_id, "user", "hola")
    audit.append_message(session_id, "assistant", "respuesta trazada")
    audit.log_decision_trace(
        trace_id="trace-1",
        session_id=session_id,
        user_key="user:1",
        channel="http",
        agent_id="default",
        request_text="hola",
        response_text="respuesta trazada",
        status="completed",
        provider="ollama",
        model="qwen2.5:7b-instruct",
        latency_ms=41.5,
        estimated_cost=0.0,
        llm_calls=2,
        input_tokens=21,
        output_tokens=9,
        total_tokens=30,
        context_json=json.dumps({"channel": "http"}),
        memory_json=json.dumps({"hit_count": 1, "items": [{"kind": "fact", "text_excerpt": "algo"}]}),
        tools_considered_json=json.dumps([{"name": "time_now", "allowed": True}]),
        tools_used_json=json.dumps([{"tool_name": "time_now", "ok": True}]),
        policies_json=json.dumps([{"tool_name": "time_now", "allowed": True}]),
        decisions_json=json.dumps({"agent_access": {"allowed": True}}),
    )

    gw = _GatewayForTraceAdmin(audit=audit)
    app = app_module.create_app(gateway_factory=lambda _config: gw)

    with TestClient(app) as client:
        traces = client.get("/admin/traces", headers={"Authorization": "Bearer secret"})
        detail = client.get("/admin/traces/trace-1", headers={"Authorization": "Bearer secret"})
        inspector = client.get("/admin/inspector/sessions/sess-1", headers={"Authorization": "Bearer secret"})

    assert traces.status_code == 200
    traces_payload = traces.json()
    assert len(traces_payload["items"]) == 1
    assert traces_payload["items"][0]["trace_id"] == "trace-1"

    assert detail.status_code == 200
    detail_payload = detail.json()
    assert detail_payload["summary"]["memory_hits"] == 1
    assert detail_payload["summary"]["tools_used"] == 1
    assert detail_payload["trace"]["policies"][0]["tool_name"] == "time_now"

    assert inspector.status_code == 200
    inspector_payload = inspector.json()
    assert inspector_payload["summary"]["trace_count"] == 1
    assert inspector_payload["summary"]["message_count"] == 2
    assert inspector_payload["traces"][0]["trace_id"] == "trace-1"
