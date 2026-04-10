from __future__ import annotations

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
auth:
  enabled: true
  session_ttl_s: 3600
''',
        encoding='utf-8',
    )


def test_phase5_live_events_and_tool_calls(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv('OPENMIURA_UI_ADMIN_USERNAME', 'admin')
    monkeypatch.setenv('OPENMIURA_UI_ADMIN_PASSWORD', 'secret123')
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    with TestClient(app) as client:
        login = client.post('/broker/auth/login', json={'username': 'admin', 'password': 'secret123'})
        headers = {'Authorization': f"Bearer {login.json()['token']}"}

        with client.stream('GET', '/broker/stream/live?once=true', headers=headers) as response:
            assert response.status_code == 200
            text = ''.join(response.iter_text())
        assert 'event: connected' in text

        gw = client.app.state.gw
        q = gw.realtime_bus.subscribe()
        gw.realtime_bus.publish('tool_call_finished', session_id='s-live', user_key='user:admin', agent_id='default', tool_name='time_now', ok=True, result_excerpt='2026-01-01', duration_ms=1.2)
        event = q.get(timeout=1.0)
        gw.realtime_bus.unsubscribe(q)
        assert event['type'] == 'tool_call_finished'
        gw.audit.log_tool_call(
            session_id='s-live',
            user_key='user:admin',
            agent_id='default',
            tool_name='time_now',
            args_json='{}',
            ok=True,
            result_excerpt='2026-01-01',
            error='',
            duration_ms=5.0,
        )
        tool_calls = client.get('/broker/admin/tool-calls', headers=headers)
        assert tool_calls.status_code == 200
        assert tool_calls.json()['items'][0]['tool_name'] == 'time_now'


def test_phase5_operator_permissions_and_ui_surface(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv('OPENMIURA_UI_ADMIN_USERNAME', 'admin')
    monkeypatch.setenv('OPENMIURA_UI_ADMIN_PASSWORD', 'secret123')
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    with TestClient(app) as client:
        admin_login = client.post('/broker/auth/login', json={'username': 'admin', 'password': 'secret123'})
        admin_headers = {'Authorization': f"Bearer {admin_login.json()['token']}"}
        created = client.post('/broker/auth/users', headers=admin_headers, json={'username': 'operator1', 'password': 'pw1', 'role': 'operator'})
        assert created.status_code == 200

        op_login = client.post('/broker/auth/login', json={'username': 'operator1', 'password': 'pw1'})
        op_headers = {'Authorization': f"Bearer {op_login.json()['token']}"}
        me = client.get('/broker/auth/me', headers=op_headers)
        assert me.status_code == 200
        assert me.json()['role'] == 'operator'
        assert 'admin.read' in me.json()['permissions']

        overview = client.get('/broker/admin/overview', headers=op_headers)
        assert overview.status_code == 200
        reload_resp = client.post('/broker/admin/reload', headers=op_headers)
        assert reload_resp.status_code == 403

        ui = client.get('/ui')
        assert ui.status_code == 200
        assert 'Tool calls' in ui.text
        assert 'Live events' in ui.text
        assert 'Role catalog' in ui.text
