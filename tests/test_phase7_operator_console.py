from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

import app as app_module
from openmiura.gateway import Gateway


POLICIES_YAML = """defaults:
  tools: true
tool_rules:
  - name: allow_time_now
    tool: time_now
    effect: allow
approval_rules:
  - name: approval_for_approval_step
    action_name: approval
    effect: require_approval
    reason: approval step should stay governed
"""


def _write_config(path: Path, policies_path: Path) -> None:
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
  session_ttl_s: 3600
policies_path: "{policies_path.as_posix()}"
''',
        encoding='utf-8',
    )


def _login(client: TestClient) -> str:
    response = client.post('/broker/auth/login', json={'username': 'admin', 'password': 'secret123'})
    assert response.status_code == 200, response.text
    return response.json()['token']


def test_phase7_operator_console_unifies_overview_replay_inspector_and_policy(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv('OPENMIURA_UI_ADMIN_USERNAME', 'admin')
    monkeypatch.setenv('OPENMIURA_UI_ADMIN_PASSWORD', 'secret123')
    policies_path = tmp_path / 'policies.yaml'
    policies_path.write_text(POLICIES_YAML, encoding='utf-8')
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg, policies_path)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    with TestClient(app) as client:
        token = _login(client)
        headers = {'Authorization': f'Bearer {token}'}
        gw = app.state.gw

        session_id = gw.audit.get_or_create_session('broker', 'user:alice', 'operator-session-1')
        gw.audit.append_message(session_id, 'user', 'hola operador')
        gw.audit.append_message(session_id, 'assistant', 'respuesta operador')
        gw.audit.log_event('out', 'broker', 'user:alice', session_id, {'event': 'chat_done', 'text': 'respuesta operador'})
        gw.audit.log_tool_call(session_id, 'user:alice', 'default', 'time_now', '{}', True, '12:00', '', 4.0)
        gw.audit.log_decision_trace(
            trace_id='trace-operator-1',
            session_id=session_id,
            user_key='user:alice',
            channel='broker',
            agent_id='default',
            request_text='hola operador',
            response_text='respuesta operador',
            provider='ollama',
            model='qwen2.5:7b-instruct',
            latency_ms=20.0,
            memory_json=json.dumps({'items': [{'text': 'memoria operador'}]}),
            tools_used_json=json.dumps([{'tool_name': 'time_now', 'ok': True}]),
        )
        gw.audit.log_tool_call(session_id, 'user:alice', 'default', 'time_now', '{}', False, '', 'clock failed', 9.0)

        created = client.post(
            '/broker/workflows',
            headers=headers,
            json={
                'name': 'wf-operator-demo',
                'autorun': True,
                'definition': {
                    'steps': [
                        {'id': 'clock', 'kind': 'tool', 'tool_name': 'time_now', 'args': {}},
                        {'id': 'approval', 'kind': 'approval', 'requested_role': 'operator'},
                    ]
                },
            },
        )
        assert created.status_code == 200, created.text
        workflow_id = created.json()['workflow']['workflow_id']

        ui = client.get('/ui')
        assert ui.status_code == 200
        assert 'Operator Console' in ui.text
        assert 'operatorTimelineBox' in ui.text

        overview = client.get('/broker/admin/operator/overview', headers=headers)
        assert overview.status_code == 200, overview.text
        overview_payload = overview.json()
        assert overview_payload['ok'] is True
        assert overview_payload['summary']['sessions'] >= 1
        assert overview_payload['summary']['workflows'] >= 1
        assert overview_payload['summary']['tool_failures'] >= 1
        assert 'tool_rules' in overview_payload['policy']['sections']

        session_console = client.get(f'/broker/admin/operator/sessions/{session_id}', headers=headers)
        assert session_console.status_code == 200, session_console.text
        session_payload = session_console.json()
        assert session_payload['ok'] is True
        assert session_payload['summary']['message_count'] == 2
        assert session_payload['inspector']['trace_count'] == 1
        assert session_payload['policy_hints']['observed_tools'] == ['time_now']
        assert session_payload['policy_hints']['tool_rules'][0]['decision']['allowed'] is True
        assert any(item['kind'] == 'tool_call' for item in session_payload['timeline'])

        workflow_console = client.get(f'/broker/admin/operator/workflows/{workflow_id}', headers=headers)
        assert workflow_console.status_code == 200, workflow_console.text
        workflow_payload = workflow_console.json()
        assert workflow_payload['ok'] is True
        assert workflow_payload['workflow']['status'] == 'waiting_approval'
        assert workflow_payload['inspector']['approval_count'] == 1
        assert workflow_payload['policy_hints']['observed_approval_actions'] == ['approval']
        assert workflow_payload['policy_hints']['approval_rules'][0]['decision']['requires_approval'] is True
        assert any(item['kind'] == 'approval' for item in workflow_payload['timeline'])
