from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

import app as app_module
from openmiura.core.audit import AuditStore


class _GatewayForEvaluationAdmin:
    def __init__(self, *, audit: AuditStore, suites_path: str):
        self.settings = SimpleNamespace(
            llm=SimpleNamespace(provider="ollama", model="qwen2.5:7b-instruct", base_url="http://127.0.0.1:11434"),
            memory=SimpleNamespace(enabled=False, embed_model=""),
            storage=SimpleNamespace(db_path=":memory:"),
            admin=SimpleNamespace(enabled=True, token="secret", max_search_results=5, rate_limit_per_minute=60),
            sandbox=SimpleNamespace(enabled=True, default_profile="local-safe"),
            evaluations=SimpleNamespace(enabled=True, suites_path=suites_path, persist_results=True, max_cases_per_run=20, default_latency_budget_ms=2000.0),
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


def test_admin_evaluation_endpoints_list_run_and_detail(tmp_path: Path):
    suites_path = tmp_path / "evaluations.yaml"
    suites_path.write_text(
        """
suites:
  smoke:
    description: smoke suite
    cases:
      - id: greeting_contains_hello
        assertions:
          - type: contains
            expected: hello
      - id: time_tool_used
        assertions:
          - type: tool_used
            tool_name: time_now
""",
        encoding="utf-8",
    )
    audit = AuditStore(":memory:")
    audit.init_db()
    gw = _GatewayForEvaluationAdmin(audit=audit, suites_path=str(suites_path))
    app = app_module.create_app(gateway_factory=lambda _config: gw)

    with TestClient(app) as client:
        suites_response = client.get("/admin/evals/suites", headers={"Authorization": "Bearer secret"})
        run_response = client.post(
            "/admin/evals/run",
            headers={"Authorization": "Bearer secret"},
            json={
                "suite_name": "smoke",
                "requested_by": "admin",
                "observations": [
                    {"case_id": "greeting_contains_hello", "response_text": "well hello there"},
                    {"case_id": "time_tool_used", "tools_used": ["time_now"]},
                ],
            },
        )
        runs_response = client.get("/admin/evals/runs", headers={"Authorization": "Bearer secret"})
        run_id = run_response.json()["run_id"]
        detail_response = client.get(f"/admin/evals/runs/{run_id}", headers={"Authorization": "Bearer secret"})

    assert suites_response.status_code == 200
    suites = suites_response.json()
    assert suites["suites"][0]["name"] == "smoke"
    assert suites["suites"][0]["case_count"] == 2

    assert run_response.status_code == 200
    run_payload = run_response.json()
    assert run_payload["status"] == "passed"
    assert run_payload["scorecard"]["passed_cases"] == 2

    assert runs_response.status_code == 200
    runs = runs_response.json()["items"]
    assert len(runs) == 1
    assert runs[0]["run_id"] == run_id

    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["run"]["run_id"] == run_id
    assert len(detail["results"]) == 2


def test_admin_evaluation_compare_regressions_and_scorecards(tmp_path: Path):
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
      - id: time_tool_used
        assertions:
          - type: tool_used
            tool_name: time_now
""",
        encoding="utf-8",
    )
    audit = AuditStore(":memory:")
    audit.init_db()
    gw = _GatewayForEvaluationAdmin(audit=audit, suites_path=str(suites_path))
    app = app_module.create_app(gateway_factory=lambda _config: gw)

    with TestClient(app) as client:
        first = client.post(
            "/admin/evals/run",
            headers={"Authorization": "Bearer secret"},
            json={
                "suite_name": "smoke",
                "requested_by": "admin",
                "observations": [
                    {"case_id": "greeting_contains_hello", "response_text": "well hello there"},
                    {"case_id": "time_tool_used", "tools_used": ["time_now"]},
                ],
            },
        )
        second = client.post(
            "/admin/evals/run",
            headers={"Authorization": "Bearer secret"},
            json={
                "suite_name": "smoke",
                "requested_by": "admin",
                "observations": [
                    {"case_id": "greeting_contains_hello", "response_text": "bye"},
                    {"case_id": "time_tool_used", "tools_used": []},
                ],
            },
        )
        second_run_id = second.json()["run_id"]
        compare = client.get(f"/admin/evals/runs/{second_run_id}/compare", headers={"Authorization": "Bearer secret"})
        regressions = client.get("/admin/evals/regressions", headers={"Authorization": "Bearer secret"})
        scorecards = client.get("/admin/evals/scorecards?group_by=agent_provider_model", headers={"Authorization": "Bearer secret"})

    assert first.status_code == 200
    assert second.status_code == 200

    assert compare.status_code == 200
    compare_payload = compare.json()
    assert compare_payload["summary"]["has_baseline"] is True
    assert compare_payload["summary"]["regression_count"] == 2
    assert compare_payload["summary"]["is_regression"] is True

    assert regressions.status_code == 200
    regressions_payload = regressions.json()
    assert len(regressions_payload["items"]) == 1
    assert regressions_payload["items"][0]["run_id"] == second_run_id

    assert scorecards.status_code == 200
    scorecards_payload = scorecards.json()
    assert scorecards_payload["group_by"] == "agent_provider_model"
    assert len(scorecards_payload["items"]) == 1
    assert scorecards_payload["items"][0]["run_count"] == 2
    assert scorecards_payload["items"][0]["group"] == "ops-agent / ollama / qwen2.5:7b-instruct"



def test_admin_evaluation_leaderboard_and_comparison(tmp_path: Path):
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
    gw = _GatewayForEvaluationAdmin(audit=audit, suites_path=str(suites_path))
    app = app_module.create_app(gateway_factory=lambda _config: gw)

    with TestClient(app) as client:
        client.post(
            "/admin/evals/run",
            headers={"Authorization": "Bearer secret"},
            json={
                "suite_name": "support_regression",
                "requested_by": "admin",
                "observations": [{"case_id": "support_case", "response_text": "ticket triaged"}],
            },
        )
        client.post(
            "/admin/evals/run",
            headers={"Authorization": "Bearer secret"},
            json={
                "suite_name": "support_regression",
                "requested_by": "admin",
                "observations": [{"case_id": "support_case", "response_text": "bad answer"}],
            },
        )
        client.post(
            "/admin/evals/run",
            headers={"Authorization": "Bearer secret"},
            json={
                "suite_name": "finance_regression",
                "requested_by": "admin",
                "observations": [{"case_id": "finance_case", "response_text": "invoice approved"}],
            },
        )
        leaderboard = client.get(
            "/admin/evals/leaderboard?group_by=agent_provider_model&rank_by=stability_score",
            headers={"Authorization": "Bearer secret"},
        )
        comparison = client.get(
            "/admin/evals/comparison?split_by=use_case&compare_by=agent_provider_model&rank_by=stability_score",
            headers={"Authorization": "Bearer secret"},
        )

    assert leaderboard.status_code == 200
    leaderboard_payload = leaderboard.json()
    assert leaderboard_payload["rank_by"] == "stability_score"
    assert leaderboard_payload["items"][0]["group"] == "finance-agent / ollama / llama3.1:8b"
    assert leaderboard_payload["items"][0]["rank"] == 1
    assert leaderboard_payload["items"][1]["latest_regression"] is True

    assert comparison.status_code == 200
    comparison_payload = comparison.json()
    assert comparison_payload["split_by"] == "use_case"
    groups = {item["group"]: item for item in comparison_payload["groups"]}
    assert set(groups) == {"support-triage", "finance"}
    assert groups["finance"]["leader"]["group"] == "finance-agent / ollama / llama3.1:8b"
