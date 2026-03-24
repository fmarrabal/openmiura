from __future__ import annotations

from pathlib import Path

from openmiura.core.config import load_settings


def test_load_settings_parses_evaluation_harness_config(tmp_path: Path):
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
evaluations:
  enabled: true
  suites_path: configs/evaluations.yaml
  persist_results: false
  max_cases_per_run: 33
  default_latency_budget_ms: 1234.5
""",
        encoding="utf-8",
    )

    settings = load_settings(str(cfg))

    assert settings.evaluations is not None
    assert settings.evaluations.enabled is True
    assert settings.evaluations.suites_path == "configs/evaluations.yaml"
    assert settings.evaluations.persist_results is False
    assert settings.evaluations.max_cases_per_run == 33
    assert settings.evaluations.default_latency_budget_ms == 1234.5
