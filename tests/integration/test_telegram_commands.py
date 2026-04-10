from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from openmiura.commands import handle_commands
from openmiura.core.audit import AuditStore


class _FakeGW:
    def __init__(self):
        self.audit = AuditStore(":memory:")
        self.audit.init_db()
        self.audit.get_or_create_session("telegram", "tg:1", "s1")
        self.settings = SimpleNamespace(llm=SimpleNamespace(model="m"), memory=SimpleNamespace(embed_model="e"))
        self.started_at = 0
        self.router = SimpleNamespace(
            available_agents=lambda: ["default"],
            clear_agent=Mock(),
        )
        self.reset_pending_tool_confirmations = Mock(return_value=True)


def test_telegram_commands_status_reset_and_forget():
    gw = _FakeGW()
    gw.audit.append_message("s1", "user", "hola")
    gw.audit.add_memory_item("tg:1", "fact", "Dato", b"1234", "{}")

    out = handle_commands(
        gw,
        channel="telegram",
        channel_user_id="tg:1",
        user_key="tg:1",
        session_id="s1",
        text="/status",
        metadata={"chat_id": 1, "from_id": 1},
    )
    assert out is not None and "openMiura status" in out.text

    out = handle_commands(
        gw,
        channel="telegram",
        channel_user_id="tg:1",
        user_key="tg:1",
        session_id="s1",
        text="/forget",
        metadata={"chat_id": 1, "from_id": 1},
    )
    assert out is not None and "Últimas 5 memorias" in out.text

    out = handle_commands(
        gw,
        channel="telegram",
        channel_user_id="tg:1",
        user_key="tg:1",
        session_id="s1",
        text="/reset",
        metadata={"chat_id": 1, "from_id": 1},
    )
    assert out is not None and "Sesión reseteada" in out.text
    gw.router.clear_agent.assert_called_once_with("s1")
    gw.reset_pending_tool_confirmations.assert_called_once_with("s1")
