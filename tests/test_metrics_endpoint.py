from __future__ import annotations

from fastapi.testclient import TestClient

import app as app_module
from openmiura.gateway import Gateway


def test_metrics_endpoint_exposes_prometheus_text(tmp_path):
    cfg = tmp_path / "openmiura.yaml"
    cfg.write_text(
        """
server:
  host: "127.0.0.1"
  port: 8081
storage:
  db_path: "./audit.db"
llm:
  provider: "ollama"
  base_url: "http://127.0.0.1:11434"
  model: "qwen2.5:7b-instruct"
runtime:
  history_limit: 4
agents:
  default:
    system_prompt: "base"
memory:
  enabled: false
tools:
  sandbox_dir: "./sandbox"
""",
        encoding="utf-8",
    )
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    with TestClient(app) as client:
        response = client.get("/metrics")
    assert response.status_code == 200
    assert "openmiura_requests_total" in response.text
    assert "openmiura_active_sessions" in response.text
