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
''',
        encoding='utf-8',
    )


def _login(client: TestClient, username: str, password: str) -> str:
    response = client.post('/broker/auth/login', json={'username': username, 'password': password})
    assert response.status_code == 200, response.text
    return response.json()['token']


def test_phase7_workflow_builder_schema_playbook_and_ui_surface(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    with TestClient(app) as client:
        gw = app.state.gw
        gw.audit.ensure_auth_user(username='alice', password='pw1', user_key='user:alice', role='user', tenant_id='acme', workspace_id='research')
        headers = {'Authorization': f'Bearer {_login(client, "alice", "pw1")}' }

        ui = client.get('/ui')
        assert ui.status_code == 200
        assert 'Workflow Builder' in ui.text
        assert 'builderDefinition' in ui.text

        schema = client.get('/broker/workflow-builder/schema', headers=headers)
        assert schema.status_code == 200, schema.text
        payload = schema.json()
        assert payload['ok'] is True
        assert 'branch' in payload['kinds']
        assert any(item['playbook_id'] == 'ticket_triage' for item in payload['starter_playbooks'])

        playbook = client.get('/broker/workflow-builder/playbooks/ticket_triage', headers=headers)
        assert playbook.status_code == 200, playbook.text
        body = playbook.json()
        assert body['playbook']['playbook_id'] == 'ticket_triage'
        graph = body['builder']['graph']
        assert any(node['id'] == 'severity_branch' and node['kind'] == 'branch' for node in graph['nodes'])
        labels = {(edge['source'], edge['target'], edge['label']) for edge in graph['edges']}
        assert ('severity_branch', 'approval', 'true') in labels
        assert ('severity_branch', 'auto_route', 'false') in labels


def test_phase7_workflow_builder_validation_and_create(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    with TestClient(app) as client:
        gw = app.state.gw
        gw.audit.ensure_auth_user(username='alice', password='pw1', user_key='user:alice', role='user', tenant_id='acme', workspace_id='research')
        headers = {'Authorization': f'Bearer {_login(client, "alice", "pw1")}' }

        invalid = client.post(
            '/broker/workflow-builder/validate',
            headers=headers,
            json={
                'definition': {
                    'steps': [
                        {'id': 'intro', 'kind': 'note', 'note': 'hello'},
                        {
                            'id': 'branch1',
                            'kind': 'branch',
                            'condition': {'left': '$input.flag', 'op': 'truthy'},
                            'if_true_step_id': 'missing-step',
                            'if_false_step_id': 'intro',
                        },
                    ]
                }
            },
        )
        assert invalid.status_code == 200, invalid.text
        invalid_payload = invalid.json()
        assert invalid_payload['ok'] is False
        assert any('missing true target' in item for item in invalid_payload['errors'])

        create = client.post(
            '/broker/workflow-builder/create',
            headers=headers,
            json={
                'name': 'builder-demo',
                'autorun': True,
                'input': {'message': 'hello'},
                'definition': {
                    'steps': [
                        {'id': 'intro', 'kind': 'note', 'note': 'hello'},
                        {'id': 'clock', 'kind': 'tool', 'tool_name': 'time_now', 'args': {}},
                    ]
                },
            },
        )
        assert create.status_code == 200, create.text
        created = create.json()
        assert created['ok'] is True
        assert created['workflow']['status'] == 'succeeded'
        assert created['builder']['stats']['step_count'] == 2
        assert created['builder']['graph']['edges'][0]['label'] == 'next'
