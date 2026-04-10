from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from openmiura.interfaces.http import app as app_module
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
  history_limit: 4
memory:
  enabled: false
tools:
  sandbox_dir: "{sandbox_dir}"
broker:
  enabled: true
auth:
  enabled: true
tenancy:
  enabled: true
  default_tenant_id: "acme"
  default_workspace_id: "research"
  default_environment: "prod"
  tenants:
    acme:
      display_name: "Acme Corp"
      workspaces:
        research:
          display_name: "Research"
          environments: [dev, prod]
          default_environment: "prod"
          rbac:
            username_roles:
              opal: operator
        ops:
          display_name: "Operations"
          environments: [prod]
          default_environment: "prod"
''',
        encoding='utf-8',
    )


def _login(client: TestClient, username: str, password: str) -> str:
    response = client.post('/broker/auth/login', json={'username': username, 'password': password})
    assert response.status_code == 200, response.text
    return response.json()['token']


def test_playbook_detail_templating_and_approval_timeline(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    with TestClient(app) as client:
        gw = app.state.gw
        gw.audit.ensure_auth_user(username='alice', password='pw1', user_key='user:alice', role='user', tenant_id='acme', workspace_id='research')
        gw.audit.ensure_auth_user(username='opal', password='pw2', user_key='user:opal', role='user', tenant_id='acme', workspace_id='research')
        alice_headers = {'Authorization': f'Bearer {_login(client, "alice", "pw1")}' }
        op_headers = {'Authorization': f'Bearer {_login(client, "opal", "pw2")}' }

        detail = client.get('/broker/playbooks/ticket_triage', headers=alice_headers)
        assert detail.status_code == 200, detail.text
        playbook = detail.json()['playbook']
        assert playbook['category'] == 'operations'
        assert 'triage' in playbook['tags']
        assert playbook['input_schema']['properties']['severity']['enum'] == ['low', 'medium', 'high']

        invalid = client.post(
            '/broker/playbooks/ticket_triage/instantiate',
            headers=alice_headers,
            json={'autorun': False, 'input': {'subject': 'broken', 'severity': 'urgent'}},
        )
        assert invalid.status_code == 400, invalid.text

        create = client.post(
            '/broker/playbooks/ticket_triage/instantiate',
            headers=alice_headers,
            json={'autorun': True, 'input': {'subject': 'payment mismatch', 'severity': 'high', 'owner': 'ops'}},
        )
        assert create.status_code == 200, create.text
        workflow = create.json()['workflow']
        assert workflow['status'] == 'waiting_approval'
        assert workflow['playbook_id'] == 'ticket_triage'
        assert workflow['name'] == 'Ticket triage · payment mismatch'

        approvals = client.get('/broker/approvals?requested_role=operator', headers=op_headers)
        approval_id = approvals.json()['items'][0]['approval_id']
        claim = client.post(f'/broker/approvals/{approval_id}/claim', headers=op_headers)
        assert claim.status_code == 200, claim.text
        decide = client.post(f'/broker/approvals/{approval_id}/decision', headers=op_headers, json={'decision': 'approve'})
        assert decide.status_code == 200, decide.text

        resolved = client.get(f"/broker/workflows/{workflow['workflow_id']}", headers=alice_headers)
        assert resolved.status_code == 200, resolved.text
        assert resolved.json()['workflow']['status'] == 'succeeded'

        timeline = client.get(f"/broker/workflows/{workflow['workflow_id']}/timeline", headers=alice_headers)
        assert timeline.status_code == 200, timeline.text
        names = [item['payload'].get('event') for item in timeline.json()['items']]
        assert 'approval_claimed' in names
        assert 'approval_decided' in names


def test_realtime_event_history_and_stream_scope(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    with TestClient(app) as client:
        gw = app.state.gw
        gw.audit.ensure_auth_user(username='alice', password='pw1', user_key='user:alice', role='user', tenant_id='acme', workspace_id='research')
        gw.audit.ensure_auth_user(username='opal', password='pw2', user_key='user:opal', role='user', tenant_id='acme', workspace_id='research')
        gw.audit.ensure_auth_user(username='oscar', password='pw3', user_key='user:oscar', role='user', tenant_id='acme', workspace_id='ops')
        alice_headers = {'Authorization': f'Bearer {_login(client, "alice", "pw1")}' }
        op_headers = {'Authorization': f'Bearer {_login(client, "opal", "pw2")}' }
        oscar_headers = {'Authorization': f'Bearer {_login(client, "oscar", "pw3")}' }

        create = client.post(
            '/broker/workflows',
            headers=alice_headers,
            json={
                'name': 'simple-stream',
                'definition': {
                    'steps': [
                        {'id': 'intro', 'kind': 'note', 'note': 'hello'},
                        {'id': 'clock', 'kind': 'tool', 'tool_name': 'time_now', 'args': {}},
                    ]
                },
                'autorun': True,
            },
        )
        assert create.status_code == 200, create.text
        workflow = create.json()['workflow']

        events = client.get(f"/broker/realtime/events?topic=workflow&workflow_id={workflow['workflow_id']}", headers=op_headers)
        assert events.status_code == 200, events.text
        payload = events.json()
        event_types = [item['type'] for item in payload['items']]
        assert 'workflow_started' in event_types
        assert 'workflow_succeeded' in event_types
        assert payload['stats']['history_size'] >= len(payload['items'])

        stream = client.get(f"/broker/workflows/{workflow['workflow_id']}/stream?once=true&replay_last=20", headers=alice_headers)
        assert stream.status_code == 200, stream.text
        body = stream.text
        assert 'event: connected' in body
        assert 'event: workflow_started' in body
        assert 'event: workflow_succeeded' in body

        denied = client.get(f"/broker/workflows/{workflow['workflow_id']}/stream?once=true&replay_last=20", headers=oscar_headers)
        assert denied.status_code == 404, denied.text
