from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from openmiura.application.costs import CostGovernanceService
from openmiura.application.evaluations import EvaluationService
from openmiura.core.audit import AuditStore
from openmiura.core.config import load_settings


class _FakeGateway:
    def __init__(self, *, audit: AuditStore, suites_path: str):
        self.audit = audit
        self.settings = SimpleNamespace(
            llm=SimpleNamespace(provider="ollama", model="qwen2.5:7b-instruct"),
            evaluations=SimpleNamespace(
                enabled=True,
                suites_path=suites_path,
                persist_results=True,
                max_cases_per_run=50,
                default_latency_budget_ms=2500.0,
            ),
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
                        workspace_id="",
                        environment="prod",
                        agent_name="",
                        workflow_name="",
                        provider="",
                        model="",
                    ),
                    SimpleNamespace(
                        name="ops-agent-provider-budget",
                        enabled=True,
                        group_by="agent_provider_model",
                        budget_amount=0.03,
                        window_hours=24 * 30,
                        warning_threshold=0.7,
                        critical_threshold=1.0,
                        tenant_id="t1",
                        workspace_id="w1",
                        environment="prod",
                        agent_name="ops-agent",
                        workflow_name="",
                        provider="ollama",
                        model="qwen2.5:7b-instruct",
                    ),
                ],
            ),
        )


def test_cost_governance_service_aggregates_and_alerts(tmp_path: Path):
    suites_path = tmp_path / "evaluations.yaml"
    suites_path.write_text(
        """
suites:
  smoke:
    agent_name: ops-agent
    provider: ollama
    model: qwen2.5:7b-instruct
    cases:
      - id: greet_case
        assertions:
          - type: contains
            expected: hello
  reconciliation:
    agent_name: finance-agent
    provider: openai
    model: gpt-4.1-mini
    cases:
      - id: reconcile_case
        assertions:
          - type: contains
            expected: ok
""",
        encoding="utf-8",
    )
    audit = AuditStore(":memory:")
    audit.init_db()
    gw = _FakeGateway(audit=audit, suites_path=str(suites_path))
    evals = EvaluationService()

    evals.run_suite(
        gw,
        suite_name="smoke",
        requested_by="ci",
        observations=[{"case_id": "greet_case", "response_text": "hello there", "cost": 0.02}],
        tenant_id="t1",
        workspace_id="w1",
        environment="prod",
    )
    evals.run_suite(
        gw,
        suite_name="smoke",
        requested_by="ci",
        observations=[{"case_id": "greet_case", "response_text": "hello again", "cost": 0.025}],
        tenant_id="t1",
        workspace_id="w1",
        environment="prod",
    )
    evals.run_suite(
        gw,
        suite_name="reconciliation",
        requested_by="ci",
        observations=[{"case_id": "reconcile_case", "response_text": "ok", "cost": 0.5}],
        tenant_id="t2",
        workspace_id="w2",
        environment="staging",
    )

    service = CostGovernanceService()
    tenant_summary = service.summary(gw, group_by="tenant", limit=10, tenant_id=None, workspace_id=None, environment=None)
    assert tenant_summary["ok"] is True
    assert tenant_summary["group_by"] == "tenant"
    assert tenant_summary["summary"]["run_count"] == 3
    assert tenant_summary["items"][0]["group"] == "t2"
    workflow_summary = service.summary(gw, group_by="workflow", limit=10, tenant_id="t1", workspace_id="w1", environment="prod")
    assert workflow_summary["items"][0]["group"] == "smoke"
    assert workflow_summary["items"][0]["total_spend"] == 0.045

    provider_summary = service.summary(gw, group_by="provider", limit=10, tenant_id="t1", workspace_id="w1", environment="prod")
    assert provider_summary["items"][0]["group"] == "ollama"
    assert provider_summary["items"][0]["total_spend"] == 0.045

    budgets = service.budgets(gw, tenant_id="t1", workspace_id="w1", environment="prod")
    assert budgets["ok"] is True
    assert len(budgets["items"]) == 2
    by_name = {item["name"]: item for item in budgets["items"]}
    assert by_name["tenant-t1-monthly"]["status"] == "critical"
    assert by_name["tenant-t1-monthly"]["current_spend"] == 0.045
    assert by_name["ops-agent-provider-budget"]["status"] == "critical"

    alerts = service.alerts(gw, severity="critical", tenant_id="t1", workspace_id="w1", environment="prod")
    assert alerts["ok"] is True
    assert len(alerts["items"]) == 2
    assert all(item["severity"] == "critical" for item in alerts["items"])


def test_load_settings_parses_cost_governance_config(tmp_path: Path):
    cfg = tmp_path / "openmiura.yaml"
    cfg.write_text(
        """
server:
  host: 127.0.0.1
  port: 8081
storage:
  db_path: data/audit.db
llm:
  provider: ollama
  model: qwen2.5:7b-instruct
runtime:
  history_limit: 12
cost_governance:
  enabled: true
  default_window_hours: 168
  default_scan_limit: 250
  budgets:
    - name: tenant-weekly
      group_by: tenant
      budget_amount: 15.5
      window_hours: 168
      warning_threshold: 0.75
      critical_threshold: 0.95
      tenant_id: acme
      workspace_id: ops
      environment: prod
      provider: ollama
      model: qwen2.5:7b-instruct
""",
        encoding="utf-8",
    )
    settings = load_settings(str(cfg))
    assert settings.cost_governance is not None
    assert settings.cost_governance.enabled is True
    assert settings.cost_governance.default_window_hours == 168
    assert settings.cost_governance.default_scan_limit == 250
    assert len(settings.cost_governance.budgets) == 1
    budget = settings.cost_governance.budgets[0]
    assert budget.name == "tenant-weekly"
    assert budget.budget_amount == 15.5
    assert budget.tenant_id == "acme"
    assert budget.workspace_id == "ops"
    assert budget.environment == "prod"
