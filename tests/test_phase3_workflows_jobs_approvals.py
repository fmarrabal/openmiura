from __future__ import annotations

import time
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


def test_workflow_runs_tool_and_timeline_is_recorded(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    with TestClient(app) as client:
        gw = app.state.gw
        gw.audit.ensure_auth_user(username='alice', password='pw1', user_key='user:alice', role='user', tenant_id='acme', workspace_id='research')
        token = _login(client, 'alice', 'pw1')
        headers = {'Authorization': f'Bearer {token}'}

        create = client.post(
            '/broker/workflows',
            headers=headers,
            json={
                'name': 'simple',
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
        assert workflow['status'] == 'succeeded'
        assert workflow['context']['step_results'][0]['step_id'] == 'clock'

        listed = client.get('/broker/workflows', headers=headers)
        assert listed.status_code == 200, listed.text
        assert any(item['workflow_id'] == workflow['workflow_id'] for item in listed.json()['items'])

        timeline = client.get(f"/broker/workflows/{workflow['workflow_id']}/timeline", headers=headers)
        assert timeline.status_code == 200, timeline.text
        event_names = [item['payload'].get('event') for item in timeline.json()['items']]
        assert 'workflow_created' in event_names
        assert 'workflow_started' in event_names
        assert 'workflow_succeeded' in event_names


def test_workflow_approval_flow_and_jobs(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    with TestClient(app) as client:
        gw = app.state.gw
        gw.audit.ensure_auth_user(username='alice', password='pw1', user_key='user:alice', role='user', tenant_id='acme', workspace_id='research')
        gw.audit.ensure_auth_user(username='opal', password='pw2', user_key='user:opal', role='user', tenant_id='acme', workspace_id='research')

        alice_headers = {'Authorization': f'Bearer {_login(client, "alice", "pw1")}' }
        op_headers = {'Authorization': f'Bearer {_login(client, "opal", "pw2")}' }

        create = client.post(
            '/broker/workflows',
            headers=alice_headers,
            json={
                'name': 'needs approval',
                'definition': {
                    'steps': [
                        {'id': 'approval', 'kind': 'approval', 'requested_role': 'operator'},
                        {'id': 'clock', 'kind': 'tool', 'tool_name': 'time_now', 'args': {}},
                    ]
                },
                'autorun': True,
            },
        )
        assert create.status_code == 200, create.text
        workflow = create.json()['workflow']
        assert workflow['status'] == 'waiting_approval'
        assert workflow['waiting_for_approval'] is True

        approvals = client.get('/broker/approvals', headers=op_headers)
        assert approvals.status_code == 200, approvals.text
        pending = approvals.json()['items']
        assert len(pending) == 1
        approval_id = pending[0]['approval_id']

        decision = client.post(
            f'/broker/approvals/{approval_id}/decision',
            headers=op_headers,
            json={'decision': 'approve'},
        )
        assert decision.status_code == 200, decision.text
        assert decision.json()['approval']['status'] == 'approved'

        resolved = client.get(f"/broker/workflows/{workflow['workflow_id']}", headers=alice_headers)
        assert resolved.status_code == 200, resolved.text
        assert resolved.json()['workflow']['status'] == 'succeeded'
        assert resolved.json()['workflow']['waiting_for_approval'] is False

        job_resp = client.post(
            '/broker/jobs',
            headers=op_headers,
            json={
                'name': 'heartbeat',
                'workflow_definition': {'steps': [{'id': 'clock', 'kind': 'tool', 'tool_name': 'time_now', 'args': {}}]},
                'interval_s': 60,
                'next_run_at': time.time() - 1,
                'enabled': True,
            },
        )
        assert job_resp.status_code == 200, job_resp.text
        job = job_resp.json()['job']
        assert job['enabled'] is True

        run_due = client.post('/broker/jobs/run-due', headers=op_headers)
        assert run_due.status_code == 200, run_due.text
        items = run_due.json()['items']
        assert len(items) == 1
        assert items[0]['job']['job_id'] == job['job_id']
        assert items[0]['workflow']['status'] == 'succeeded'

        jobs = client.get('/broker/jobs', headers=op_headers)
        assert jobs.status_code == 200, jobs.text
        refreshed = next(item for item in jobs.json()['items'] if item['job_id'] == job['job_id'])
        assert refreshed['last_run_at'] is not None
        assert refreshed['next_run_at'] is not None


def test_playbooks_and_scope_filtering(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    with TestClient(app) as client:
        gw = app.state.gw
        gw.audit.ensure_auth_user(username='alice', password='pw1', user_key='user:alice', role='user', tenant_id='acme', workspace_id='research')
        gw.audit.ensure_auth_user(username='oscar', password='pw2', user_key='user:oscar', role='user', tenant_id='acme', workspace_id='ops')

        alice_headers = {'Authorization': f'Bearer {_login(client, "alice", "pw1")}' }
        oscar_headers = {'Authorization': f'Bearer {_login(client, "oscar", "pw2")}' }

        playbooks = client.get('/broker/playbooks', headers=alice_headers)
        assert playbooks.status_code == 200, playbooks.text
        ids = {item['playbook_id'] for item in playbooks.json()['items']}
        assert 'summary_daily' in ids

        instantiate = client.post('/broker/playbooks/summary_daily/instantiate', headers=alice_headers, json={'autorun': True})
        assert instantiate.status_code == 200, instantiate.text
        workflow = instantiate.json()['workflow']
        assert workflow['playbook_id'] == 'summary_daily'
        assert workflow['status'] == 'succeeded'

        alice_list = client.get('/broker/workflows', headers=alice_headers)
        assert alice_list.status_code == 200, alice_list.text
        assert len(alice_list.json()['items']) == 1

        oscar_list = client.get('/broker/workflows', headers=oscar_headers)
        assert oscar_list.status_code == 200, oscar_list.text
        assert oscar_list.json()['items'] == []
