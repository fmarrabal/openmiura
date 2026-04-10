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
auth:
  enabled: true
''',
        encoding='utf-8',
    )


def _login(client: TestClient, username: str, password: str) -> str:
    response = client.post('/broker/auth/login', json={'username': username, 'password': password})
    assert response.status_code == 200, response.text
    return response.json()['token']


def test_phase7_replay_session_workflow_and_compare(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv('OPENMIURA_UI_ADMIN_USERNAME', 'admin')
    monkeypatch.setenv('OPENMIURA_UI_ADMIN_PASSWORD', 'secret123')
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    with TestClient(app) as client:
        token = _login(client, 'admin', 'secret123')
        headers = {'Authorization': f'Bearer {token}'}
        gw = app.state.gw

        session_id = gw.audit.get_or_create_session('broker', 'user:alice', 'session-replay-1')
        gw.audit.append_message(session_id, 'user', 'hola')
        gw.audit.append_message(session_id, 'assistant', 'respuesta')
        gw.audit.log_event('out', 'broker', 'user:alice', session_id, {'event': 'chat_done', 'text': 'respuesta'})
        gw.audit.log_tool_call(session_id, 'user:alice', 'default', 'time_now', '{}', True, '12:00', '', 3.2)
        gw.audit.log_decision_trace(
            trace_id='trace-session-1',
            session_id=session_id,
            user_key='user:alice',
            channel='broker',
            agent_id='default',
            request_text='hola',
            response_text='respuesta',
            provider='ollama',
            model='qwen2.5:7b-instruct',
            latency_ms=12.5,
            memory_json=json.dumps({'items': [{'text': 'memoria'}]}),
            tools_used_json=json.dumps(['time_now']),
        )

        session_id_2 = gw.audit.get_or_create_session('broker', 'user:bob', 'session-replay-2')
        gw.audit.append_message(session_id_2, 'user', 'solo una')
        gw.audit.log_event('out', 'broker', 'user:bob', session_id_2, {'event': 'chat_done', 'text': 'ok'})

        created = client.post(
            '/broker/workflows',
            headers=headers,
            json={
                'name': 'wf-replay-demo',
                'autorun': True,
                'definition': {
                    'steps': [
                        {'id': 'note1', 'kind': 'note', 'note': 'hello'},
                        {'id': 'clock', 'kind': 'tool', 'tool_name': 'time_now', 'args': {}},
                    ]
                },
            },
        )
        assert created.status_code == 200, created.text
        workflow_id = created.json()['workflow']['workflow_id']

        ui = client.get('/ui')
        assert ui.status_code == 200
        assert 'Replay Explorer' in ui.text
        assert 'replayCompareBox' in ui.text

        session_replay = client.get(f'/broker/admin/replay/sessions/{session_id}', headers=headers)
        assert session_replay.status_code == 200, session_replay.text
        session_payload = session_replay.json()
        assert session_payload['ok'] is True
        assert session_payload['summary']['message_count'] == 2
        assert session_payload['summary']['tool_call_count'] == 1
        assert session_payload['summary']['trace_count'] == 1
        assert any(item['kind'] == 'trace' for item in session_payload['timeline'])

        workflow_replay = client.get(f'/broker/admin/replay/workflows/{workflow_id}', headers=headers)
        assert workflow_replay.status_code == 200, workflow_replay.text
        workflow_payload = workflow_replay.json()
        assert workflow_payload['ok'] is True
        assert workflow_payload['workflow']['status'] == 'succeeded'
        assert workflow_payload['summary']['step_count'] == 2
        assert any(item['kind'] == 'event' and 'workflow_started' in (item.get('event_name') or item.get('label') or '') for item in workflow_payload['timeline'])

        compare = client.post(
            '/broker/admin/replay/compare',
            headers=headers,
            json={
                'left_kind': 'session',
                'left_id': session_id,
                'right_kind': 'session',
                'right_id': session_id_2,
                'limit': 100,
            },
        )
        assert compare.status_code == 200, compare.text
        compare_payload = compare.json()
        assert compare_payload['ok'] is True
        assert compare_payload['changed'] is True
        assert compare_payload['metrics_diff']['message_count']['left'] == 2
        assert compare_payload['metrics_diff']['message_count']['right'] == 1
        assert 'chat_done' in {item['name'] for item in compare_payload['event_name_diff']['items']}
