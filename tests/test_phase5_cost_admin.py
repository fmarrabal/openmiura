from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

import app as app_module
from openmiura.core.audit import AuditStore


class _GatewayForCostAdmin:
    def __init__(self, *, audit: AuditStore, suites_path: str):
        self.settings = SimpleNamespace(
            llm=SimpleNamespace(provider="ollama", model="qwen2.5:7b-instruct", base_url="http://127.0.0.1:11434"),
            memory=SimpleNamespace(enabled=False, embed_model=""),
            storage=SimpleNamespace(db_path=":memory:"),
            admin=SimpleNamespace(enabled=True, token="secret", max_search_results=5, rate_limit_per_minute=60),
            sandbox=SimpleNamespace(enabled=True, default_profile="local-safe"),
            evaluations=SimpleNamespace(enabled=True, suites_path=suites_path, persist_results=True, max_cases_per_run=20, default_latency_budget_ms=2000.0),
            cost_governance=SimpleNamespace(
                enabled=True,
                default_window_hours=24 * 30,
                default_scan_limit=2000,
                budgets=[
                    SimpleNamespace(
                        name="tenant-t1-monthly",
                        enabled=True,
                        group_by="tenant",
                        budget_amount=0.04,
                        window_hours=24 * 30,
                        warning_threshold=0.8,
                        critical_threshold=1.0,
                        tenant_id="t1",
                        workspace_id="w1",
                        environment="prod",
                        agent_name="",
                        workflow_name="",
                        provider="",
                        model="",
                    )
                ],
            ),
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


def test_admin_cost_endpoints_summary_budgets_and_alerts(tmp_path: Path):
    suites_path = tmp_path / "evaluations.yaml"
    suites_path.write_text(
        """
suites:
  smoke:
    agent_name: ops-agent
    provider: ollama
    model: qwen2.5:7b-instruct
    cases:
      - id: greeting_contains_hello
        assertions:
          - type: contains
            expected: hello
""",
        encoding="utf-8",
    )
    audit = AuditStore(":memory:")
    audit.init_db()
    gw = _GatewayForCostAdmin(audit=audit, suites_path=str(suites_path))
    app = app_module.create_app(gateway_factory=lambda _config: gw)

    with TestClient(app) as client:
        first = client.post(
            "/admin/evals/run",
            headers={"Authorization": "Bearer secret"},
            json={
                "suite_name": "smoke",
                "requested_by": "admin",
                "tenant_id": "t1",
                "workspace_id": "w1",
                "environment": "prod",
                "observations": [{"case_id": "greeting_contains_hello", "response_text": "well hello there", "cost": 0.02}],
            },
        )
        second = client.post(
            "/admin/evals/run",
            headers={"Authorization": "Bearer secret"},
            json={
                "suite_name": "smoke",
                "requested_by": "admin",
                "tenant_id": "t1",
                "workspace_id": "w1",
                "environment": "prod",
                "observations": [{"case_id": "greeting_contains_hello", "response_text": "hello again", "cost": 0.03}],
            },
        )
        summary = client.get(
            "/admin/costs/summary?group_by=tenant&tenant_id=t1&workspace_id=w1&environment=prod",
            headers={"Authorization": "Bearer secret"},
        )
        budgets = client.get(
            "/admin/costs/budgets?tenant_id=t1&workspace_id=w1&environment=prod",
            headers={"Authorization": "Bearer secret"},
        )
        alerts = client.get(
            "/admin/costs/alerts?severity=critical&tenant_id=t1&workspace_id=w1&environment=prod",
            headers={"Authorization": "Bearer secret"},
        )

    assert first.status_code == 200
    assert second.status_code == 200

    assert summary.status_code == 200
    summary_payload = summary.json()
    assert summary_payload["group_by"] == "tenant"
    assert summary_payload["summary"]["total_spend"] == 0.05
    assert summary_payload["items"][0]["group"] == "t1"

    assert budgets.status_code == 200
    budgets_payload = budgets.json()
    assert len(budgets_payload["items"]) == 1
    assert budgets_payload["items"][0]["status"] == "critical"
    assert budgets_payload["items"][0]["current_spend"] == 0.05

    assert alerts.status_code == 200
    alerts_payload = alerts.json()
    assert alerts_payload["severity"] == "critical"
    assert len(alerts_payload["items"]) == 1
    assert alerts_payload["items"][0]["budget_name"] == "tenant-t1-monthly"
