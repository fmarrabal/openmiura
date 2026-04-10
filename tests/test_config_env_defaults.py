from __future__ import annotations

from pathlib import Path

from openmiura.core.config import load_settings


def test_load_settings_supports_env_default_syntax(tmp_path: Path) -> None:
    cfg = tmp_path / "openmiura.yaml"
    cfg.write_text(
        """
server:
  host: "env:OPENMIURA_SERVER_HOST|0.0.0.0"
  port: "env:OPENMIURA_SERVER_PORT|8081"
storage:
  db_path: "env:OPENMIURA_DB_PATH|data/audit.db"
llm:
  provider: "env:OPENMIURA_LLM_PROVIDER|ollama"
  base_url: "env:OPENMIURA_LLM_BASE_URL|http://ollama:11434"
  model: "env:OPENMIURA_LLM_MODEL|qwen2.5:7b-instruct"
runtime:
  worker_mode: "env:OPENMIURA_WORKER_MODE|inline"
agents:
  default:
    system_prompt: "hola"
memory:
  embed_base_url: "env:OPENMIURA_EMBED_BASE_URL|http://ollama:11434"
""",
        encoding="utf-8",
    )

    settings = load_settings(str(cfg))

    assert settings.server.host == "0.0.0.0"
    assert settings.server.port == 8081
    assert settings.storage.db_path == "data/audit.db"
    assert settings.llm.provider == "ollama"
    assert settings.llm.base_url == "http://ollama:11434"
    assert settings.runtime.worker_mode == "inline"
    assert settings.memory is not None
    assert settings.memory.embed_base_url == "http://ollama:11434"


def test_load_settings_env_default_syntax_prefers_env_value(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPENMIURA_SERVER_HOST", "127.0.0.1")
    monkeypatch.setenv("OPENMIURA_LLM_BASE_URL", "https://api.openai.com/v1")
    cfg = tmp_path / "openmiura.yaml"
    cfg.write_text(
        """
server:
  host: "env:OPENMIURA_SERVER_HOST|0.0.0.0"
  port: 8081
storage: {}
llm:
  provider: openai
  base_url: "env:OPENMIURA_LLM_BASE_URL|http://ollama:11434"
  model: gpt-4o-mini
runtime: {}
agents:
  default:
    system_prompt: "hola"
""",
        encoding="utf-8",
    )

    settings = load_settings(str(cfg))

    assert settings.server.host == "127.0.0.1"
    assert settings.llm.base_url == "https://api.openai.com/v1"
