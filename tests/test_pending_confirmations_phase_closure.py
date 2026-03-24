from __future__ import annotations

import time
from types import SimpleNamespace

from openmiura.commands import handle_commands
from openmiura.core.pending_confirmations import PendingToolConfirmationStore


class _FakeAudit:
    def __init__(self) -> None:
        self.cleared_sessions: list[str] = []
        self.appended: list[tuple[str, str, str]] = []

    def append_message(self, session_id, role, content):
        self.appended.append((session_id, role, content))

    def clear_session_messages(self, session_id):
        self.cleared_sessions.append(session_id)
        return 3


class _FakeRouter:
    def __init__(self) -> None:
        self._session_agent = {"s1": "writer"}

    def clear_agent(self, session_id: str) -> None:
        self._session_agent.pop(session_id, None)

    def select_agent(self, session_id: str, agent_name: str) -> bool:
        self._session_agent[session_id] = agent_name
        return True


class _FakeGateway:
    def __init__(self, ttl_s: int = 60) -> None:
        self.audit = _FakeAudit()
        self.router = _FakeRouter()
        self.pending_confirmations = PendingToolConfirmationStore(default_ttl_s=ttl_s)
        self.settings = SimpleNamespace(
            llm=SimpleNamespace(model="qwen"),
            memory=SimpleNamespace(embed_model="embed"),
        )
        self.policy = None
        self.tools = SimpleNamespace(run_tool=lambda **kwargs: "OK")

    def set_pending_tool_confirmation(self, session_id: str, **payload) -> None:
        self.pending_confirmations.set(session_id, **payload)

    def get_pending_tool_confirmation(self, session_id: str):
        return self.pending_confirmations.get(session_id)

    def consume_pending_tool_confirmation(self, session_id: str, *, user_key: str | None = None):
        return self.pending_confirmations.consume(session_id, user_key=user_key)

    def cancel_pending_tool_confirmation(self, session_id: str, *, user_key: str | None = None) -> bool:
        return self.pending_confirmations.cancel(session_id, user_key=user_key)

    def reset_pending_tool_confirmations(self, session_id: str) -> int:
        return self.pending_confirmations.reset_session(session_id)

    def invalidate_pending_tool_confirmation_for_agent(self, session_id: str, agent_id: str | None) -> int:
        return self.pending_confirmations.invalidate_agent(session_id, agent_id)


def _set_pending(gw: _FakeGateway, *, session_id: str = "s1", agent_id: str = "writer") -> None:
    gw.set_pending_tool_confirmation(
        session_id,
        channel="telegram",
        channel_user_id="tg:1",
        user_key="tg:1",
        agent_id=agent_id,
        tool_name="fs_write",
        args={"path": "x.txt", "content": "hola"},
    )


def test_reset_clears_pending_tool_confirmation() -> None:
    gw = _FakeGateway()
    _set_pending(gw)

    out = handle_commands(
        gw,
        channel="telegram",
        channel_user_id="tg:1",
        user_key="tg:1",
        session_id="s1",
        text="/reset",
        metadata=None,
    )

    assert out is not None
    assert "confirmación(es) pendiente(s)" in out.text
    assert gw.get_pending_tool_confirmation("s1") is None


def test_switching_agent_invalidates_pending_confirmation_from_previous_agent() -> None:
    gw = _FakeGateway()
    _set_pending(gw, agent_id="writer")

    out = handle_commands(
        gw,
        channel="telegram",
        channel_user_id="tg:1",
        user_key="tg:1",
        session_id="s1",
        text="/agent researcher",
        metadata=None,
    )

    assert out is not None
    assert "Agente activo: researcher" in out.text
    assert "confirmación(es) pendiente(s)" in out.text
    assert gw.get_pending_tool_confirmation("s1") is None


def test_confirm_after_ttl_returns_no_pending_action() -> None:
    gw = _FakeGateway(ttl_s=1)
    _set_pending(gw)
    time.sleep(1.1)

    out = handle_commands(
        gw,
        channel="telegram",
        channel_user_id="tg:1",
        user_key="tg:1",
        session_id="s1",
        text="/confirm",
        metadata=None,
    )

    assert out is not None
    assert "No hay ninguna acción pendiente" in out.text
    assert gw.get_pending_tool_confirmation("s1") is None
