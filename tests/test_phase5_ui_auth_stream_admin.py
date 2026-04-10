from __future__ import annotations

import json
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
memory:
  enabled: false
tools:
  sandbox_dir: "{sandbox_dir}"
broker:
  enabled: true
  base_path: "/broker"
  token: "broker-secret"
auth:
  enabled: true
  session_ttl_s: 3600
''',
        encoding='utf-8',
    )


def test_formal_auth_login_chat_stream_and_admin_console(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv('OPENMIURA_UI_ADMIN_USERNAME', 'admin')
    monkeypatch.setenv('OPENMIURA_UI_ADMIN_PASSWORD', 'secret123')
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)

    def _fake_process_message(gw, inbound):
        gw.audit.get_or_create_session(inbound.channel, inbound.user_id, inbound.session_id)
        gw.audit.append_message(inbound.session_id, 'user', inbound.text)
        gw.audit.append_message(inbound.session_id, 'assistant', f'reply:{inbound.text}')
        gw.audit.log_event(direction='out', channel='broker', user_id=inbound.user_id, session_id=inbound.session_id, payload={'reply': inbound.text})
        from openmiura.core.schema import OutboundMessage
        return OutboundMessage(channel='broker', user_id=inbound.user_id, session_id=inbound.session_id, agent_id='default', text=f'reply:{inbound.text}')

    monkeypatch.setattr('openmiura.channels.http_broker.process_message', _fake_process_message)
    monkeypatch.setattr('app.process_message', _fake_process_message)

    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    with TestClient(app) as client:
        login = client.post('/broker/auth/login', json={'username': 'admin', 'password': 'secret123'})
        assert login.status_code == 200, login.text
        session_token = login.json()['token']
        headers = {'Authorization': f'Bearer {session_token}'}

        me = client.get('/broker/auth/me', headers=headers)
        assert me.status_code == 200
        assert me.json()['auth_mode'] == 'auth-session'
        assert me.json()['role'] == 'admin'
        assert me.json()['username'] == 'admin'

        created = client.post('/broker/auth/users', headers=headers, json={'username': 'alice', 'password': 'pw1', 'role': 'user'})
        assert created.status_code == 200
        assert created.json()['user']['username'] == 'alice'

        users = client.get('/broker/auth/users', headers=headers)
        assert users.status_code == 200
        usernames = {item['username'] for item in users.json()['items']}
        assert {'admin', 'alice'} <= usernames

        app.state.gw.audit.set_identity('tg:123', 'user:admin', linked_by='admin')

        with client.stream('POST', '/broker/chat/stream', headers=headers, json={'message': 'hola', 'agent_id': 'default', 'session_id': 's1'}) as response:
            assert response.status_code == 200
            body = ''.join(response.iter_text())
        assert 'event: accepted' in body
        assert 'event: delta' in body
        assert 'event: done' in body
        assert 'reply:hola' in body

        overview = client.get('/broker/admin/overview', headers=headers)
        assert overview.status_code == 200
        assert overview.json()['auth_users'] >= 2

        events = client.get('/broker/admin/events', headers=headers)
        assert events.status_code == 200
        assert isinstance(events.json()['items'], list)

        identities = client.get('/broker/admin/identities', headers=headers)
        assert identities.status_code == 200
        assert identities.json()['items'][0]['global_user_key'] == 'user:admin'

        reload_resp = client.post('/broker/admin/reload', headers=headers)
        assert reload_resp.status_code == 200
        assert reload_resp.json()['ok'] is True
