from __future__ import annotations

from types import SimpleNamespace

from openmiura.commands import handle_commands, handle_tool_commands
from openmiura.core.policy import PolicyEngine
from openmiura.tools.runtime import ToolConfirmationRequired


class _FakeAudit:
    def __init__(self) -> None:
        self.appended = []
    def append_message(self, session_id, role, content):
        self.appended.append((session_id, role, content))


class _FakeTools:
    def __init__(self):
        self.calls = []
    def run_tool(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get('tool_name') == 'fs_write' and not kwargs.get('confirmed', False):
            raise ToolConfirmationRequired('fs_write', kwargs.get('args') or {})
        return 'OK write'


class _FakeGateway:
    def __init__(self):
        self.audit = _FakeAudit()
        self.tools = _FakeTools()
        self._pending = {}
        self.policy = None
        self.settings = SimpleNamespace(llm=SimpleNamespace(model='qwen'), memory=SimpleNamespace(embed_model='embed'))
    def set_pending_tool_confirmation(self, session_id, **payload):
        self._pending[session_id] = payload
    def get_pending_tool_confirmation(self, session_id):
        return self._pending.get(session_id)
    def pop_pending_tool_confirmation(self, session_id):
        return self._pending.pop(session_id, None)
    def clear_pending_tool_confirmation(self, session_id):
        return self._pending.pop(session_id, None) is not None


def test_tool_requires_confirmation_then_confirm_executes():
    gw = _FakeGateway()
    out = handle_tool_commands(
        gw,
        channel='telegram',
        agent_id='writer',
        session_id='s1',
        channel_user_id='tg:1',
        user_key='tg:1',
        text='/write notes.txt hola',
    )
    assert out is not None
    assert 'requiere confirmación' in out.text
    assert gw.get_pending_tool_confirmation('s1') is not None

    out2 = handle_commands(
        gw,
        channel='telegram',
        channel_user_id='tg:1',
        user_key='tg:1',
        session_id='s1',
        text='/confirm',
        metadata=None,
    )
    assert out2 is not None
    assert out2.text == 'OK write'
    assert gw.get_pending_tool_confirmation('s1') is None
    assert any(call.get('confirmed') is True for call in gw.tools.calls)


def test_cancel_discards_pending_confirmation():
    gw = _FakeGateway()
    gw.set_pending_tool_confirmation('s1', channel='telegram', channel_user_id='tg:1', user_key='tg:1', agent_id='writer', tool_name='fs_write', args={'path': 'x', 'content': 'y'})
    out = handle_commands(
        gw,
        channel='telegram',
        channel_user_id='tg:1',
        user_key='tg:1',
        session_id='s1',
        text='/cancel',
        metadata=None,
    )
    assert out is not None
    assert 'cancelada' in out.text
    assert gw.get_pending_tool_confirmation('s1') is None
