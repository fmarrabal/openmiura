from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from openmiura.application.evaluations import EvaluationService
from openmiura.core.audit import AuditStore


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
        )


def test_evaluation_service_runs_suite_and_persists_results(tmp_path: Path):
    suites_path = tmp_path / "evaluations.yaml"
    suites_path.write_text(
        """
suites:
  regression:
    description: regression suite
    cases:
      - id: greet_case
        name: Greeting case
        assertions:
          - type: contains
            expected: hello
          - type: latency_max_ms
            max_ms: 100
      - id: tool_case
        name: Tool usage case
        assertions:
          - type: tool_used
            tool_name: time_now
          - type: policy_adherence
            expected: true
""",
        encoding="utf-8",
    )
    audit = AuditStore(":memory:")
    audit.init_db()
    gw = _FakeGateway(audit=audit, suites_path=str(suites_path))

    payload = EvaluationService().run_suite(
        gw,
        suite_name="regression",
        requested_by="ci",
        observations=[
            {"case_id": "greet_case", "response_text": "hello there", "latency_ms": 40.0, "cost": 0.02},
            {"case_id": "tool_case", "response_text": "done", "tools_used": ["time_now"], "policy_ok": True, "latency_ms": 10.0},
        ],
        tenant_id="t1",
        workspace_id="w1",
        environment="prod",
    )

    assert payload["ok"] is True
    assert payload["status"] == "passed"
    assert payload["scorecard"]["total_cases"] == 2
    assert payload["scorecard"]["passed_cases"] == 2
    assert audit.count_evaluation_runs(tenant_id="t1", workspace_id="w1", environment="prod") == 1
    assert audit.count_evaluation_case_results(tenant_id="t1", workspace_id="w1", environment="prod") == 2

    saved = audit.get_evaluation_run(payload["run_id"])
    assert saved is not None
    assert saved["suite_name"] == "regression"
    assert saved["passed_cases"] == 2
    case_results = audit.list_evaluation_case_results(run_id=payload["run_id"])
    assert [item["case_id"] for item in case_results] == ["greet_case", "tool_case"]
    assert all(item["passed"] for item in case_results)


def test_evaluation_service_compares_runs_and_builds_scorecards(tmp_path: Path):
    suites_path = tmp_path / "evaluations.yaml"
    suites_path.write_text(
        """
suites:
  regression:
    agent_name: ops-agent
    provider: ollama
    model: qwen2.5:7b-instruct
    cases:
      - id: greet_case
        assertions:
          - type: contains
            expected: hello
      - id: tool_case
        assertions:
          - type: tool_used
            tool_name: time_now
""",
        encoding="utf-8",
    )
    audit = AuditStore(":memory:")
    audit.init_db()
    gw = _FakeGateway(audit=audit, suites_path=str(suites_path))

    first = EvaluationService().run_suite(
        gw,
        suite_name="regression",
        requested_by="ci",
        observations=[
            {"case_id": "greet_case", "response_text": "hello there"},
            {"case_id": "tool_case", "tools_used": ["time_now"], "latency_ms": 10.0},
        ],
        tenant_id="t1",
        workspace_id="w1",
        environment="prod",
    )
    second = EvaluationService().run_suite(
        gw,
        suite_name="regression",
        requested_by="ci",
        observations=[
            {"case_id": "greet_case", "response_text": "goodbye"},
            {"case_id": "tool_case", "tools_used": [], "latency_ms": 25.0},
        ],
        tenant_id="t1",
        workspace_id="w1",
        environment="prod",
    )

    comparison = EvaluationService().compare_runs(gw, run_id=second["run_id"])
    assert comparison["ok"] is True
    assert comparison["summary"]["has_baseline"] is True
    assert comparison["summary"]["regression_count"] == 2
    assert comparison["summary"]["is_regression"] is True
    assert {item["case_id"] for item in comparison["regressions"]} == {"greet_case", "tool_case"}

    regressions = EvaluationService().list_regressions(gw, limit=10, tenant_id="t1", workspace_id="w1", environment="prod")
    assert regressions["ok"] is True
    assert len(regressions["items"]) == 1
    assert regressions["items"][0]["run_id"] == second["run_id"]

    scorecards = EvaluationService().scorecards(gw, group_by="agent_provider_model", limit=10, tenant_id="t1", workspace_id="w1", environment="prod")
    assert scorecards["ok"] is True
    assert len(scorecards["items"]) == 1
    assert scorecards["items"][0]["group"] == "ops-agent / ollama / qwen2.5:7b-instruct"
    assert scorecards["items"][0]["run_count"] == 2
    assert scorecards["items"][0]["failed_cases"] == 2
    assert first["scorecard"]["pass_rate"] == 1.0



def test_evaluation_service_builds_leaderboard_and_use_case_comparison(tmp_path: Path):
    suites_path = tmp_path / "evaluations.yaml"
    suites_path.write_text(
        """
suites:
  support_regression:
    use_case: support-triage
    agent_name: ops-agent
    provider: ollama
    model: qwen2.5:7b-instruct
    cases:
      - id: support_case
        assertions:
          - type: contains
            expected: ticket
  finance_regression:
    tags: [finance, regression]
    agent_name: finance-agent
    provider: ollama
    model: llama3.1:8b
    cases:
      - id: finance_case
        assertions:
          - type: contains
            expected: invoice
""",
        encoding="utf-8",
    )
    audit = AuditStore(":memory:")
    audit.init_db()
    gw = _FakeGateway(audit=audit, suites_path=str(suites_path))

    EvaluationService().run_suite(
        gw,
        suite_name="support_regression",
        requested_by="ci",
        observations=[{"case_id": "support_case", "response_text": "ticket triaged"}],
        tenant_id="t1",
        workspace_id="w1",
        environment="prod",
    )
    EvaluationService().run_suite(
        gw,
        suite_name="support_regression",
        requested_by="ci",
        observations=[{"case_id": "support_case", "response_text": "nope"}],
        tenant_id="t1",
        workspace_id="w1",
        environment="prod",
    )
    EvaluationService().run_suite(
        gw,
        suite_name="finance_regression",
        requested_by="ci",
        observations=[{"case_id": "finance_case", "response_text": "invoice approved"}],
        tenant_id="t1",
        workspace_id="w1",
        environment="prod",
    )

    leaderboard = EvaluationService().leaderboard(
        gw,
        group_by="agent_provider_model",
        rank_by="stability_score",
        limit=10,
        tenant_id="t1",
        workspace_id="w1",
        environment="prod",
    )
    assert leaderboard["ok"] is True
    assert leaderboard["summary"]["entity_count"] == 2
    assert leaderboard["items"][0]["group"] == "finance-agent / ollama / llama3.1:8b"
    assert leaderboard["items"][0]["rank"] == 1
    assert leaderboard["items"][1]["latest_regression"] is True
    assert leaderboard["items"][1]["use_cases"] == ["support-triage"]

    comparison = EvaluationService().comparison(
        gw,
        split_by="use_case",
        compare_by="agent_provider_model",
        rank_by="stability_score",
        tenant_id="t1",
        workspace_id="w1",
        environment="prod",
    )
    assert comparison["ok"] is True
    assert comparison["split_by"] == "use_case"
    groups = {item["group"]: item for item in comparison["groups"]}
    assert set(groups) == {"support-triage", "finance"}
    assert groups["support-triage"]["leader"]["group"] == "ops-agent / ollama / qwen2.5:7b-instruct"
    assert groups["finance"]["leader"]["group"] == "finance-agent / ollama / llama3.1:8b"
