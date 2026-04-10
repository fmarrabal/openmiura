from __future__ import annotations

from openmiura.core.audit import AuditStore
from openmiura.core.config import (
    LLMSettings,
    RuntimeSettings,
    ServerSettings,
    Settings,
    StorageSettings,
)
from openmiura.core.router import Router


def make_settings() -> Settings:
    return Settings(
        server=ServerSettings(),
        storage=StorageSettings(db_path="data/test_router.db"),
        llm=LLMSettings(),
        runtime=RuntimeSettings(),
        agents={"default": {"system_prompt": "You are helpful."}},
    )


def test_router_returns_default_agent(tmp_path):
    store = AuditStore(str(tmp_path / "router.db"))
    store.init_db()
    router = Router(settings=make_settings(), audit=store)

    result = router.route(channel="telegram", user_id="tg:123", text="hola")

    assert isinstance(result, dict)
    assert result["agent_id"] == "default"
