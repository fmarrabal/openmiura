from __future__ import annotations

from pathlib import Path

import openmiura.cli as cli


def test_doctor_payload_openai_provider_reports_api_key(tmp_path, monkeypatch):
    cfg = tmp_path / 'openmiura.yaml'
    cfg.write_text(
        """server:
  host: 127.0.0.1
  port: 8081
storage:
  db_path: ":memory:"
llm:
  provider: openai
  base_url: https://api.openai.com/v1
  model: gpt-4o-mini
  api_key_env_var: OPENAI_API_KEY
runtime:
  history_limit: 2
memory:
  enabled: false
tools:
  sandbox_dir: data/sandbox
admin:
  enabled: false
mcp:
  enabled: false
""",
        encoding='utf-8'
    )
    monkeypatch.setenv('OPENAI_API_KEY', 'test-openai-key')
    payload, exit_code = cli._doctor_payload(str(cfg))
    assert exit_code == 0
    names = {row['name']: row for row in payload['checks']}
    assert names['llm_api_key']['ok'] is True
    assert payload['summary']['llm_provider'] == 'openai'
