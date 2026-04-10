from __future__ import annotations

import time
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
''',
        encoding='utf-8',
    )


def _login(client: TestClient, username: str, password: str) -> str:
    response = client.post('/broker/auth/login', json={'username': username, 'password': password})
    assert response.status_code == 200, response.text
    return response.json()['token']


def test_playbook_versions_publish_and_deprecate(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    with TestClient(app) as client:
        gw = app.state.gw
        gw.audit.ensure_auth_user(username='alice', password='pw1', user_key='user:alice', role='user', tenant_id='acme', workspace_id='research')
        headers = {'Authorization': f'Bearer {_login(client, "alice", "pw1")}' }

        listed = client.get('/broker/playbooks?published_only=true&include_versions=true', headers=headers)
        assert listed.status_code == 200, listed.text
        assert any(item['playbook_id'] == 'ticket_triage' for item in listed.json()['items'])

        versions = client.get('/broker/playbooks/ticket_triage/versions', headers=headers)
        assert versions.status_code == 200, versions.text
        assert versions.json()['items'][0]['publication_status'] == 'published'

        deprecated = client.post('/broker/playbooks/ticket_triage/deprecate', headers=headers, json={'notes': 'temporary hold'})
        assert deprecated.status_code == 200, deprecated.text
        assert deprecated.json()['playbook']['publication_status'] == 'deprecated'

        listed = client.get('/broker/playbooks?published_only=true', headers=headers)
        assert listed.status_code == 200, listed.text
        assert all(item['playbook_id'] != 'ticket_triage' for item in listed.json()['items'])

        blocked = client.post(
            '/broker/playbooks/ticket_triage/instantiate',
            headers=headers,
            json={'autorun': False, 'input': {'subject': 'p1', 'severity': 'high', 'owner': 'ops'}},
        )
        assert blocked.status_code == 400, blocked.text

        republished = client.post('/broker/playbooks/ticket_triage/publish', headers=headers, json={'notes': 'approved again'})
        assert republished.status_code == 200, republished.text
        assert republished.json()['playbook']['publication_status'] == 'published'
        assert republished.json()['playbook']['change_log'][-1]['notes'] == 'approved again'


def test_jobs_summary_and_unified_timeline_stream(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    with TestClient(app) as client:
        gw = app.state.gw
        gw.audit.ensure_auth_user(username='opal', password='pw2', user_key='user:opal', role='user', tenant_id='acme', workspace_id='research')
        headers = {'Authorization': f'Bearer {_login(client, "opal", "pw2")}' }

        due_resp = client.post(
            '/broker/jobs',
            headers=headers,
            json={
                'name': 'due-heartbeat',
                'workflow_definition': {'steps': [{'id': 'clock', 'kind': 'tool', 'tool_name': 'time_now', 'args': {}}]},
                'schedule_kind': 'once',
                'not_before': time.time() - 1,
                'enabled': True,
            },
        )
        assert due_resp.status_code == 200, due_resp.text
        due_job = due_resp.json()['job']
        assert due_job['operational_state'] == 'due'

        paused_resp = client.post(
            '/broker/jobs',
            headers=headers,
            json={
                'name': 'paused-heartbeat',
                'workflow_definition': {'steps': [{'id': 'clock', 'kind': 'tool', 'tool_name': 'time_now', 'args': {}}]},
                'interval_s': 60,
                'enabled': False,
            },
        )
        assert paused_resp.status_code == 200, paused_resp.text
        paused_job = paused_resp.json()['job']
        assert paused_job['operational_state'] == 'paused'

        summary = client.get('/broker/jobs/summary', headers=headers)
        assert summary.status_code == 200, summary.text
        payload = summary.json()
        assert payload['summary']['by_state']['due'] >= 1
        assert payload['summary']['by_state']['paused'] >= 1

        run = client.post(f"/broker/jobs/{due_job['job_id']}/run", headers=headers)
        assert run.status_code == 200, run.text
        workflow = run.json()['workflow']
        assert workflow['status'] == 'succeeded'

        job_timeline = client.get(f"/broker/jobs/{due_job['job_id']}/timeline", headers=headers)
        assert job_timeline.status_code == 200, job_timeline.text
        names = [item['payload'].get('event') for item in job_timeline.json()['items']]
        assert 'job_created' in names
        assert 'job_run_started' in names
        assert 'job_run_completed' in names
        assert 'workflow_created' in names
        assert 'workflow_succeeded' in names

        generic = client.get(f"/broker/timeline?job_id={due_job['job_id']}", headers=headers)
        assert generic.status_code == 200, generic.text
        assert len(generic.json()['items']) >= len(job_timeline.json()['items'])

        stream = client.get(f"/broker/timeline/stream?job_id={due_job['job_id']}&once=true&replay_last=50", headers=headers)
        assert stream.status_code == 200, stream.text
        body = stream.text
        assert 'event: job_created' in body
        assert 'event: job_run_completed' in body


def test_unified_timeline_for_approval_entities(tmp_path: Path) -> None:
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
                'name': 'approval-demo',
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
        approval_id = client.get('/broker/approvals', headers=op_headers).json()['items'][0]['approval_id']
        assert client.post(f'/broker/approvals/{approval_id}/claim', headers=op_headers).status_code == 200
        assert client.post(f'/broker/approvals/{approval_id}/decision', headers=op_headers, json={'decision': 'approve'}).status_code == 200

        approval_timeline = client.get(f'/broker/approvals/{approval_id}/timeline', headers=op_headers)
        assert approval_timeline.status_code == 200, approval_timeline.text
        events = [item['payload'].get('event') for item in approval_timeline.json()['items']]
        assert 'approval_claimed' in events
        assert 'approval_decided' in events

        stream = client.get(f'/broker/timeline/stream?approval_id={approval_id}&once=true&replay_last=20', headers=op_headers)
        assert stream.status_code == 200, stream.text
        assert 'event: approval_claimed' in stream.text
        assert 'event: approval_decided' in stream.text
