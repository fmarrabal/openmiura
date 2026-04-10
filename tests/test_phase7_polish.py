from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

import app as app_module
from openmiura.gateway import Gateway


POLICIES_YAML = """defaults:
  tools: true
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


def test_phase7_polish_operator_filters_quick_actions_and_replay_compare(tmp_path: Path, monkeypatch) -> None:
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

        session_id = gw.audit.get_or_create_session('broker', 'user:alice', 'session-polish-1')
        gw.audit.append_message(session_id, 'user', 'hola con error')
        gw.audit.log_tool_call(session_id, 'user:alice', 'default', 'time_now', '{}', False, '', 'clock exploded', 8.0)
        gw.audit.log_decision_trace(
            trace_id='trace-polish-1',
            session_id=session_id,
            user_key='user:alice',
            channel='broker',
            agent_id='default',
            request_text='hola con error',
            response_text='falló',
            provider='ollama',
            model='qwen2.5:7b-instruct',
            latency_ms=14.0,
            status='failed',
            memory_json=json.dumps({'items': []}),
            tools_used_json=json.dumps([{'tool_name': 'time_now', 'ok': False}]),
        )

        waiting = client.post(
            '/broker/workflows',
            headers=headers,
            json={
                'name': 'wf-polish-approval',
                'autorun': True,
                'definition': {
                    'steps': [
                        {'id': 'approval', 'kind': 'approval', 'requested_role': 'operator'},
                        {'id': 'clock', 'kind': 'tool', 'tool_name': 'time_now', 'args': {}},
                    ]
                },
            },
        )
        assert waiting.status_code == 200, waiting.text
        workflow_id = waiting.json()['workflow']['workflow_id']
        approval_id = client.get('/broker/approvals', headers=headers).json()['items'][0]['approval_id']

        waiting2 = client.post(
            '/broker/workflows',
            headers=headers,
            json={
                'name': 'wf-polish-cancel',
                'autorun': True,
                'definition': {
                    'steps': [
                        {'id': 'approval', 'kind': 'approval', 'requested_role': 'operator'},
                    ]
                },
            },
        )
        assert waiting2.status_code == 200, waiting2.text
        cancel_workflow_id = waiting2.json()['workflow']['workflow_id']

        ui = client.get('/ui')
        assert ui.status_code == 200
        assert 'applyOperatorFiltersBtn' in ui.text
        assert 'operatorActionResultBox' in ui.text
        assert 'replayCompareSummary' in ui.text

        overview = client.get(
            '/broker/admin/operator/overview',
            headers=headers,
            params={'q': 'clock exploded', 'kind': 'failure', 'only_failures': 'true', 'limit': 20},
        )
        assert overview.status_code == 200, overview.text
        overview_payload = overview.json()
        assert overview_payload['ok'] is True
        assert overview_payload['filters']['only_failures'] is True
        assert overview_payload['filtered_counts']['recent_failures'] >= 1
        assert overview_payload['recent_failures'][0]['kind'] == 'tool_call'

        session_console = client.get(
            f'/broker/admin/operator/sessions/{session_id}',
            headers=headers,
            params={'kind': 'tool_call', 'only_failures': 'true', 'limit': 50},
        )
        assert session_console.status_code == 200, session_console.text
        session_payload = session_console.json()
        assert session_payload['filters']['kind'] == 'tool_call'
        assert len(session_payload['timeline']) == 1
        assert session_payload['timeline'][0]['kind'] == 'tool_call'
        assert session_payload['timeline'][0]['ok'] is False

        claim = client.post(
            f'/broker/admin/operator/approvals/{approval_id}/actions/claim',
            headers=headers,
            json={'reason': 'take ownership'},
        )
        assert claim.status_code == 200, claim.text
        assert claim.json()['approval']['assigned_to']

        approve = client.post(
            f'/broker/admin/operator/approvals/{approval_id}/actions/approve',
            headers=headers,
            json={'reason': 'looks good'},
        )
        assert approve.status_code == 200, approve.text
        assert approve.json()['approval']['status'] == 'approved'

        workflow_console = client.get(f'/broker/admin/operator/workflows/{workflow_id}', headers=headers)
        assert workflow_console.status_code == 200, workflow_console.text
        workflow_payload = workflow_console.json()
        assert workflow_payload['workflow']['status'] == 'succeeded'

        cancel = client.post(
            f'/broker/admin/operator/workflows/{cancel_workflow_id}/actions/cancel',
            headers=headers,
            json={'reason': 'abort'},
        )
        assert cancel.status_code == 200, cancel.text
        assert cancel.json()['workflow']['status'] == 'cancelled'

        other_session = gw.audit.get_or_create_session('broker', 'user:bob', 'session-polish-2')
        gw.audit.append_message(other_session, 'user', 'hola simple')
        gw.audit.log_event('out', 'broker', 'user:bob', other_session, {'event': 'chat_done', 'text': 'ok'})

        compare = client.post(
            '/broker/admin/replay/compare',
            headers=headers,
            json={
                'left_kind': 'session',
                'left_id': session_id,
                'right_kind': 'session',
                'right_id': other_session,
                'limit': 100,
            },
        )
        assert compare.status_code == 200, compare.text
        compare_payload = compare.json()
        assert compare_payload['ok'] is True
        assert 'timeline_kind_diff' in compare_payload
        assert 'timeline_status_diff' in compare_payload
        assert 'timeline_signature_diff' in compare_payload
        assert any(item['name'] == 'tool_call' for item in compare_payload['timeline_kind_diff']['items'])
        assert compare_payload['timeline_signature_diff']['items']
