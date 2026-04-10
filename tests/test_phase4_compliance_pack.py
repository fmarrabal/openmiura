from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

import app as app_module
from openmiura.core.audit import AuditStore


class _GatewayForCompliance:
    def __init__(self, audit: AuditStore):
        self.settings = SimpleNamespace(
            llm=SimpleNamespace(provider="ollama", model="qwen", base_url="http://127.0.0.1:11434"),
            memory=SimpleNamespace(enabled=False, embed_model=""),
            storage=SimpleNamespace(db_path=":memory:"),
            admin=SimpleNamespace(enabled=True, token="secret", max_search_results=5),
            sandbox=SimpleNamespace(enabled=True, default_profile="local-safe"),
        )
        self.telegram = None
        self.slack = None
        self.audit = audit
        self.tools = SimpleNamespace(registry=SimpleNamespace(_tools={}))
        self.policy = None
        self.router = None
        self.identity = None
        self.sandbox = SimpleNamespace(profiles_catalog=lambda: {"local-safe": {}})
        self.secret_broker = SimpleNamespace(is_enabled=lambda: True)
        self.started_at = 0.0


def test_admin_compliance_summary_and_export(tmp_path: Path):
    audit = AuditStore(":memory:")
    audit.init_db()
    session_id = audit.get_or_create_session("http", "user:alice", "sess-1", tenant_id="t1", workspace_id="w1", environment="prod")
    audit.log_event(
        direction="system",
        channel="security",
        user_id="user:alice",
        session_id=session_id,
        payload={"event": "secret_resolved", "ref": "crm.api_key", "tool_name": "web_fetch"},
        tenant_id="t1",
        workspace_id="w1",
        environment="prod",
    )
    audit.log_event(
        direction="security",
        channel="broker",
        user_id="user:alice",
        session_id=session_id,
        payload={"event": "approval_requested", "approval_id": "ap-1"},
        tenant_id="t1",
        workspace_id="w1",
        environment="prod",
    )
    audit.log_event(
        direction="system",
        channel="admin",
        user_id="admin",
        session_id="admin",
        payload={"action": "reload"},
        tenant_id="t1",
        workspace_id="w1",
        environment="prod",
    )
    audit.log_tool_call(
        session_id=session_id,
        user_key="user:alice",
        agent_id="default",
        tool_name="web_fetch",
        args_json='{"url": "https://example.com"}',
        ok=True,
        result_excerpt="ok",
        error="",
        duration_ms=12.0,
        tenant_id="t1",
        workspace_id="w1",
        environment="prod",
    )

    gw = _GatewayForCompliance(audit)
    app = app_module.create_app(gateway_factory=lambda _config: gw)
    with TestClient(app) as client:
        response = client.get(
            "/admin/compliance/summary",
            headers={"Authorization": "Bearer secret"},
            params={"tenant_id": "t1", "workspace_id": "w1", "environment": "prod", "window_hours": 24},
        )
        export_response = client.post(
            "/admin/compliance/export",
            headers={"Authorization": "Bearer secret"},
            json={
                "tenant_id": "t1",
                "workspace_id": "w1",
                "environment": "prod",
                "window_hours": 24,
                "sections": ["overview", "security", "secret_usage", "approvals", "config_changes", "tool_calls", "sessions"],
            },
        )

    assert response.status_code == 200
    summary = response.json()
    assert summary["counts"]["secret_usages"] == 1
    assert summary["counts"]["approval_events"] == 1
    assert summary["counts"]["config_changes"] == 1

    assert export_response.status_code == 200
    export_data = export_response.json()
    assert export_data["report"]["report_type"] == "openmiura-compliance-pack-initial"
    assert export_data["integrity"]["algorithm"] == "sha256"
    assert len(export_data["integrity"]["sha256"]) == 64
    assert export_data["report"]["sections"]["secret_usage"][0]["payload"]["event"] == "secret_resolved"
