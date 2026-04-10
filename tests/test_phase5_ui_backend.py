from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

import app as app_module
from openmiura.gateway import Gateway


def _write_config(path: Path) -> None:
    db_path = (path.parent / 'audit.db').as_posix()
    sandbox_dir = (path.parent / 'sandbox').as_posix()
    path.write_text(
        f'''\
server:
  host: "127.0.0.1"
  port: 8081
storage:
  db_path: "{db_path}"
llm:
  provider: "ollama"
  base_url: "http://127.0.0.1:11434"
  model: "qwen2.5:7b-instruct"
runtime:
  history_limit: 6
agents:
  default:
    system_prompt: "base"
    tools: ["time_now"]
  admin_agent:
    system_prompt: "admin"
    tools: ["terminal_exec", "time_now"]
memory:
  enabled: false
tools:
  sandbox_dir: "{sandbox_dir}"
broker:
  enabled: true
  base_path: "/broker"
  token: "broker-secret"
''',
        encoding='utf-8',
    )


def test_phase5_broker_user_tokens_sessions_history_and_ui(tmp_path: Path, monkeypatch) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)

    def _fake_process_message(gw, inbound):
        gw.audit.get_or_create_session(inbound.channel, inbound.user_id, inbound.session_id)
        gw.audit.append_message(inbound.session_id, 'user', inbound.text)
        gw.audit.append_message(inbound.session_id, 'assistant', f'reply:{inbound.text}')
        from openmiura.core.schema import OutboundMessage
        return OutboundMessage(
            channel='broker',
            user_id=inbound.user_id,
            session_id=inbound.session_id,
            agent_id='default',
            text=f'reply:{inbound.text}',
        )

    monkeypatch.setattr('openmiura.channels.http_broker.process_message', _fake_process_message)
    monkeypatch.setattr('app.process_message', _fake_process_message)

    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    with TestClient(app) as client:
        token_resp = client.post(
            '/broker/auth/tokens',
            headers={'Authorization': 'Bearer broker-secret'},
            json={'user_key': 'ui:user', 'label': 'phase5'},
        )
        assert token_resp.status_code == 200
        user_token = token_resp.json()['token']['token']

        me = client.get('/broker/auth/me', headers={'Authorization': f'Bearer {user_token}'})
        assert me.status_code == 401  # broker token required when static broker token is configured

        session_id = 'broker:ui-session'
        chat = client.post(
            '/broker/chat',
            headers={'Authorization': 'Bearer broker-secret'},
            json={'message': 'hola', 'user_id': 'ui:user', 'agent_id': 'default', 'session_id': session_id},
        )
        assert chat.status_code == 200
        assert chat.json()['text'] == 'reply:hola'

        sessions = client.get('/broker/sessions?user_key=ui:user', headers={'Authorization': 'Bearer broker-secret'})
        assert sessions.status_code == 200
        assert any(item['session_id'] == session_id for item in sessions.json()['items'])

        history = client.get(f'/broker/sessions/{session_id}/messages', headers={'Authorization': 'Bearer broker-secret'})
        assert history.status_code == 200
        roles = [item['role'] for item in history.json()['items']]
        assert roles == ['user', 'assistant']

        ui = client.get('/ui')
        assert ui.status_code == 200
        assert 'openMiura' in ui.text


def test_phase5_pending_metrics_agents_tools_and_terminal_stream(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    with TestClient(app) as client:
        gw = client.app.state.gw
        gw.pending_confirmations.set(
            'broker:pending',
            channel='broker',
            channel_user_id='ui:user',
            user_key='ui:user',
            agent_id='default',
            tool_name='time_now',
            args={},
        )

        pending = client.get('/broker/confirmations?user_key=ui:user', headers={'Authorization': 'Bearer broker-secret'})
        assert pending.status_code == 200
        assert pending.json()['items'][0]['session_id'] == 'broker:pending'

        confirm = client.post('/broker/confirmations/broker:pending/confirm', headers={'Authorization': 'Bearer broker-secret'}, json={})
        assert confirm.status_code == 200
        assert confirm.json()['ok'] is True

        metrics = client.get('/broker/metrics/summary', headers={'Authorization': 'Bearer broker-secret'})
        assert metrics.status_code == 200
        assert metrics.json()['ok'] is True
        assert 'memory' in metrics.json()

        agents = client.get('/broker/agents', headers={'Authorization': 'Bearer broker-secret'})
        assert agents.status_code == 200
        agent_ids = {item['agent_id'] for item in agents.json()['items']}
        assert {'default', 'admin_agent'} <= agent_ids

        tools = client.get('/broker/agents/admin_agent/tools', headers={'Authorization': 'Bearer broker-secret'})
        assert tools.status_code == 200
        tool_names = {item['name'] for item in tools.json()['tools']}
        assert 'terminal_exec' in tool_names

        command = f'"{sys.executable}" -c "print(12345)"'
        with client.stream(
            'POST',
            '/broker/terminal/stream',
            headers={'Authorization': 'Bearer broker-secret'},
            json={'command': command, 'agent_id': 'admin_agent', 'confirmed': True},
        ) as response:
            assert response.status_code == 200
            body = ''.join(response.iter_text())
        assert '12345' in body
