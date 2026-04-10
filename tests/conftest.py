from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from openmiura.core.audit import AuditStore
from openmiura.core.config import LLMSettings, RuntimeSettings, ServerSettings, Settings, StorageSettings

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def isolate_test_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Keep tests hermetic and independent from local developer state."""
    monkeypatch.delenv("OPENMIURA_CONFIG", raising=False)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    monkeypatch.delenv("OPENMIURA_ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("OPENMIURA_MCP_ENABLED", raising=False)
    monkeypatch.delenv("OPENMIURA_VAULT_ENABLED", raising=False)
    monkeypatch.delenv("OPENMIURA_VAULT_PASSPHRASE", raising=False)
    monkeypatch.chdir(tmp_path)


@pytest.fixture()
def db_path() -> str:
    return ":memory:"


@pytest.fixture()
def audit_store(db_path: str) -> AuditStore:
    audit = AuditStore(db_path)
    audit.init_db()
    return audit


@pytest.fixture()
def settings_factory(tmp_path: Path):
    def _factory(*, agents: dict | None = None) -> Settings:
        return Settings(
            server=ServerSettings(),
            storage=StorageSettings(db_path=str(tmp_path / "audit.db")),
            llm=LLMSettings(),
            runtime=RuntimeSettings(),
            agents=agents or {"default": {"name": "default", "system_prompt": "base"}},
        )

    return _factory
