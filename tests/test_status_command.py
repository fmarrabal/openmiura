from __future__ import annotations

from types import SimpleNamespace

from openmiura.commands import handle_commands


class _FakeAudit:
    def __init__(self) -> None:
        self.appended: list[tuple[str, str, str]] = []

    def count_memory_items(self, user_key=None):
        return 3 if user_key else 9

    def count_sessions(self):
        return 4

    def count_active_sessions(self, window_s=86400):
        return 2

    def get_last_message(self, session_id: str):
        return {"role": "assistant", "content": "Última respuesta bastante larga para probar status"}

    def append_message(self, session_id: str, role: str, content: str) -> None:
        self.appended.append((session_id, role, content))


class _FakeGateway:
    def __init__(self) -> None:
        self.audit = _FakeAudit()
        self.started_at = 1000.0
        self.settings = SimpleNamespace(
            llm=SimpleNamespace(model="qwen2.5:7b-instruct"),
            memory=SimpleNamespace(embed_model="nomic-embed-text"),
        )


def test_status_command_includes_uptime_sessions_and_last_message(monkeypatch) -> None:
    gw = _FakeGateway()
    monkeypatch.setattr("openmiura.commands.time.time", lambda: 1125.0)

    out = handle_commands(
        gw,
        channel="telegram",
        channel_user_id="tg:456",
        user_key="curro",
        session_id="tg-123-curro",
        text="/status",
        metadata={"chat_id": 123, "from_id": 456},
    )

    assert out is not None
    assert "uptime:" in out.text
    assert "active_sessions(24h): 2" in out.text
    assert "sessions(total): 4" in out.text
    assert "last_message: assistant:" in out.text
    assert "telegram.from_id: 456" in out.text
    assert gw.audit.appended
