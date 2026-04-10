from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from openmiura.application.workflows.service import WorkflowService
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


def test_workflow_retries_and_branching(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    with TestClient(app) as client:
        gw = app.state.gw
        gw.audit.ensure_auth_user(username='alice', password='pw1', user_key='user:alice', role='user', tenant_id='acme', workspace_id='research')
        token = _login(client, 'alice', 'pw1')
        headers = {'Authorization': f'Bearer {token}'}

        calls = {'flaky': 0}
        original = gw.tools.run_tool

        def fake_run_tool(**kwargs):
            if kwargs.get('tool_name') == 'flaky_tool':
                calls['flaky'] += 1
                if calls['flaky'] == 1:
                    raise RuntimeError('transient boom')
                return {'ok': True, 'attempt': calls['flaky']}
            return original(**kwargs)

        gw.tools.run_tool = fake_run_tool
        try:
            create = client.post(
                '/broker/workflows',
                headers=headers,
                json={
                    'name': 'retry-branch',
                    'input': {'run_main': True},
                    'definition': {
                        'steps': [
                            {
                                'id': 'branch',
                                'kind': 'branch',
                                'condition': {'left': '$input.run_main', 'op': 'eq', 'right': True},
                                'if_true_step_id': 'flaky',
                                'if_false_step_id': 'fallback',
                            },
                            {
                                'id': 'flaky',
                                'kind': 'tool',
                                'tool_name': 'flaky_tool',
                                'args': {},
                                'retry_limit': 1,
                                'backoff_s': 0.001,
                            },
                            {'id': 'fallback', 'kind': 'note', 'note': 'should-not-run'},
                        ]
                    },
                    'autorun': True,
                },
            )
        finally:
            gw.tools.run_tool = original
        assert create.status_code == 200, create.text
        workflow = create.json()['workflow']
        assert workflow['status'] == 'succeeded'
        assert workflow['context']['step_attempts']['flaky'] == 2
        assert workflow['context']['branches'][0]['target_step_id'] == 'flaky'
        timeline = client.get(f"/broker/workflows/{workflow['workflow_id']}/timeline", headers=headers)
        assert timeline.status_code == 200, timeline.text
        event_names = [item['payload'].get('event') for item in timeline.json()['items']]
        assert 'step_retry_scheduled' in event_names
        assert calls['flaky'] == 2


def test_workflow_timeout_and_compensation(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    workflow_service = WorkflowService()

    with TestClient(app):
        gw = app.state.gw
        original = gw.tools.run_tool

        def slow_run_tool(**kwargs):
            if kwargs.get('tool_name') == 'slow_tool':
                time.sleep(0.02)
                return {'ok': True}
            return original(**kwargs)

        gw.tools.run_tool = slow_run_tool
        try:
            item = workflow_service.create_workflow(
                gw,
                name='timeout-compensation',
                definition={
                    'steps': [
                        {
                            'id': 'slow',
                            'kind': 'tool',
                            'tool_name': 'slow_tool',
                            'args': {},
                            'timeout_s': 0.001,
                            'compensate': [
                                {'id': 'rollback-note', 'kind': 'note', 'note': 'rolled back'},
                            ],
                        },
                    ]
                },
                created_by='user:alice',
                tenant_id='acme',
                workspace_id='research',
                environment='prod',
            )
            try:
                workflow_service.run_workflow(gw, item['workflow_id'], actor='user:alice', tenant_id='acme', workspace_id='research', environment='prod')
                raise AssertionError('timeout expected')
            except TimeoutError:
                pass
        finally:
            gw.tools.run_tool = original

        stored = gw.audit.get_workflow(item['workflow_id'], tenant_id='acme', workspace_id='research', environment='prod')
        assert stored is not None
        assert stored['status'] == 'failed'
        assert stored['context']['compensations'][0]['step_id'] == 'rollback-note'


def test_approval_filters_and_claim_and_scheduler_controls(tmp_path: Path) -> None:
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
                'name': 'approval-inbox',
                'definition': {
                    'steps': [
                        {'id': 'approval', 'kind': 'approval', 'requested_role': 'operator', 'expires_in_s': 60},
                        {'id': 'clock', 'kind': 'tool', 'tool_name': 'time_now', 'args': {}},
                    ]
                },
                'autorun': True,
            },
        )
        assert create.status_code == 200, create.text
        workflow = create.json()['workflow']
        assert workflow['status'] == 'waiting_approval'

        approvals = client.get('/broker/approvals?requested_role=operator', headers=op_headers)
        assert approvals.status_code == 200, approvals.text
        pending = approvals.json()['items']
        assert len(pending) == 1
        approval_id = pending[0]['approval_id']

        claim = client.post(f'/broker/approvals/{approval_id}/claim', headers=op_headers)
        assert claim.status_code == 200, claim.text
        assert claim.json()['approval']['assigned_to'] == 'user:opal'

        detail = client.get(f'/broker/approvals/{approval_id}', headers=op_headers)
        assert detail.status_code == 200, detail.text
        assert detail.json()['approval']['assigned_to'] == 'user:opal'

        decision = client.post(f'/broker/approvals/{approval_id}/decision', headers=op_headers, json={'decision': 'approve'})
        assert decision.status_code == 200, decision.text
        assert decision.json()['approval']['status'] == 'approved'

        job_resp = client.post(
            '/broker/jobs',
            headers=op_headers,
            json={
                'name': 'once-job',
                'workflow_definition': {'steps': [{'id': 'clock', 'kind': 'tool', 'tool_name': 'time_now', 'args': {}}]},
                'schedule_kind': 'once',
                'not_before': time.time() - 1,
                'enabled': True,
                'max_runs': 1,
            },
        )
        assert job_resp.status_code == 200, job_resp.text
        job = job_resp.json()['job']
        assert job['schedule_kind'] == 'once'

        paused = client.post(f"/broker/jobs/{job['job_id']}/pause", headers=op_headers)
        assert paused.status_code == 200, paused.text
        assert paused.json()['job']['enabled'] is False

        resumed = client.post(f"/broker/jobs/{job['job_id']}/resume", headers=op_headers)
        assert resumed.status_code == 200, resumed.text
        assert resumed.json()['job']['enabled'] is True

        due = client.post('/broker/jobs/run-due', headers=op_headers)
        assert due.status_code == 200, due.text
        assert len(due.json()['items']) == 1

        refreshed = client.get(f"/broker/jobs/{job['job_id']}", headers=op_headers)
        assert refreshed.status_code == 200, refreshed.text
        job_data = refreshed.json()['job']
        assert job_data['run_count'] == 1
        assert job_data['next_run_at'] is None

        cron_job = client.post(
            '/broker/jobs',
            headers=op_headers,
            json={
                'name': 'cron-job',
                'workflow_definition': {'steps': [{'id': 'clock', 'kind': 'tool', 'tool_name': 'time_now', 'args': {}}]},
                'schedule_kind': 'cron',
                'schedule_expr': '*/5 * * * *',
                'timezone': 'UTC',
                'enabled': True,
            },
        )
        assert cron_job.status_code == 200, cron_job.text
        assert cron_job.json()['job']['schedule_kind'] == 'cron'
        assert cron_job.json()['job']['next_run_at'] is not None


def test_expired_approval_rejects_waiting_workflow(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    with TestClient(app) as client:
        gw = app.state.gw
        gw.audit.ensure_auth_user(username='alice', password='pw1', user_key='user:alice', role='user', tenant_id='acme', workspace_id='research')
        gw.audit.ensure_auth_user(username='opal', password='pw2', user_key='user:opal', role='operator', tenant_id='acme', workspace_id='research')
        headers = {'Authorization': f'Bearer {_login(client, "alice", "pw1")}' }
        op_headers = {'Authorization': f'Bearer {_login(client, "opal", "pw2")}' }

        create = client.post(
            '/broker/workflows',
            headers=headers,
            json={
                'name': 'approval-expiry',
                'definition': {
                    'steps': [
                        {'id': 'approval', 'kind': 'approval', 'requested_role': 'operator', 'expires_in_s': 0.01},
                        {'id': 'clock', 'kind': 'tool', 'tool_name': 'time_now', 'args': {}},
                    ]
                },
                'autorun': True,
            },
        )
        assert create.status_code == 200, create.text
        workflow_id = create.json()['workflow']['workflow_id']
        time.sleep(0.03)

        approvals = client.get('/broker/approvals?status=pending', headers=op_headers)
        assert approvals.status_code == 200, approvals.text
        assert approvals.json()['items'] == []

        expired = client.get('/broker/approvals?status=expired', headers=op_headers)
        assert expired.status_code == 200, expired.text
        assert len(expired.json()['items']) == 1

        stored = gw.audit.get_workflow(workflow_id, tenant_id='acme', workspace_id='research', environment='prod')
        assert stored is not None
        assert stored['status'] == 'rejected'
        assert stored['error'] == 'approval_expired'


def test_claimed_approval_cannot_be_stolen(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    with TestClient(app) as client:
        gw = app.state.gw
        gw.audit.ensure_auth_user(username='alice', password='pw1', user_key='user:alice', role='user', tenant_id='acme', workspace_id='research')
        gw.audit.ensure_auth_user(username='opal', password='pw2', user_key='user:opal', role='operator', tenant_id='acme', workspace_id='research')
        gw.audit.ensure_auth_user(username='otto', password='pw3', user_key='user:otto', role='operator', tenant_id='acme', workspace_id='research')
        alice_headers = {'Authorization': f'Bearer {_login(client, "alice", "pw1")}' }
        opal_headers = {'Authorization': f'Bearer {_login(client, "opal", "pw2")}' }
        otto_headers = {'Authorization': f'Bearer {_login(client, "otto", "pw3")}' }

        create = client.post(
            '/broker/workflows',
            headers=alice_headers,
            json={
                'name': 'approval-claim-lock',
                'definition': {
                    'steps': [
                        {'id': 'approval', 'kind': 'approval', 'requested_role': 'operator', 'expires_in_s': 60},
                    ]
                },
                'autorun': True,
            },
        )
        assert create.status_code == 200, create.text

        approvals = client.get('/broker/approvals?requested_role=operator', headers=opal_headers)
        approval_id = approvals.json()['items'][0]['approval_id']
        claim = client.post(f'/broker/approvals/{approval_id}/claim', headers=opal_headers)
        assert claim.status_code == 200, claim.text
        steal = client.post(f'/broker/approvals/{approval_id}/claim', headers=otto_headers)
        assert steal.status_code == 409, steal.text
        assert 'already claimed' in steal.json()['error']


def test_job_failure_records_single_workflow_failed_event(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    with TestClient(app) as client:
        gw = app.state.gw
        gw.audit.ensure_auth_user(username='opal', password='pw2', user_key='user:opal', role='operator', tenant_id='acme', workspace_id='research')
        headers = {'Authorization': f'Bearer {_login(client, "opal", "pw2")}' }
        original = gw.tools.run_tool

        def failing_tool(**kwargs):
            if kwargs.get('tool_name') == 'boom_tool':
                raise RuntimeError('boom')
            return original(**kwargs)

        gw.tools.run_tool = failing_tool
        try:
            create = client.post(
                '/broker/jobs',
                headers=headers,
                json={
                    'name': 'failing-job',
                    'workflow_definition': {'steps': [{'id': 'boom', 'kind': 'tool', 'tool_name': 'boom_tool', 'args': {}}]},
                    'schedule_kind': 'once',
                    'not_before': time.time() - 1,
                    'enabled': True,
                    'max_runs': 1,
                },
            )
            assert create.status_code == 200, create.text
            job_id = create.json()['job']['job_id']
            due = client.post('/broker/jobs/run-due', headers=headers)
            assert due.status_code == 200, due.text
        finally:
            gw.tools.run_tool = original

        payload = due.json()['items']
        assert len(payload) == 1
        workflow_id = payload[0]['workflow']['workflow_id']
        timeline = client.get(f'/broker/workflows/{workflow_id}/timeline', headers=headers)
        assert timeline.status_code == 200, timeline.text
        event_names = [item['payload'].get('event') for item in timeline.json()['items']]
        assert event_names.count('workflow_failed') == 1
        assert event_names.count('step_failed') == 1

        job_detail = client.get(f'/broker/jobs/{job_id}', headers=headers)
        assert job_detail.status_code == 200, job_detail.text
        assert job_detail.json()['job']['last_error'] == 'boom'


def test_invalid_cron_expression_is_rejected(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    with TestClient(app) as client:
        gw = app.state.gw
        gw.audit.ensure_auth_user(username='opal', password='pw2', user_key='user:opal', role='operator', tenant_id='acme', workspace_id='research')
        headers = {'Authorization': f'Bearer {_login(client, "opal", "pw2")}' }
        response = client.post(
            '/broker/jobs',
            headers=headers,
            json={
                'name': 'bad-cron',
                'workflow_definition': {'steps': [{'id': 'clock', 'kind': 'tool', 'tool_name': 'time_now', 'args': {}}]},
                'schedule_kind': 'cron',
                'schedule_expr': '61 * * * *',
                'enabled': True,
            },
        )
        assert response.status_code == 400, response.text
        assert 'out of range' in response.json()['error']


def test_claimed_approval_cannot_be_decided_by_other_actor(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    with TestClient(app) as client:
        gw = app.state.gw
        gw.audit.ensure_auth_user(username='alice', password='pw1', user_key='user:alice', role='user', tenant_id='acme', workspace_id='research')
        gw.audit.ensure_auth_user(username='opal', password='pw2', user_key='user:opal', role='operator', tenant_id='acme', workspace_id='research')
        gw.audit.ensure_auth_user(username='otto', password='pw3', user_key='user:otto', role='operator', tenant_id='acme', workspace_id='research')
        alice_headers = {'Authorization': f'Bearer {_login(client, "alice", "pw1")}' }
        opal_headers = {'Authorization': f'Bearer {_login(client, "opal", "pw2")}' }
        otto_headers = {'Authorization': f'Bearer {_login(client, "otto", "pw3")}' }

        create = client.post(
            '/broker/workflows',
            headers=alice_headers,
            json={
                'name': 'approval-decision-lock',
                'definition': {
                    'steps': [
                        {'id': 'approval', 'kind': 'approval', 'requested_role': 'operator', 'expires_in_s': 60},
                    ]
                },
                'autorun': True,
            },
        )
        assert create.status_code == 200, create.text

        approvals = client.get('/broker/approvals?requested_role=operator', headers=opal_headers)
        approval_id = approvals.json()['items'][0]['approval_id']
        claim = client.post(f'/broker/approvals/{approval_id}/claim', headers=opal_headers)
        assert claim.status_code == 200, claim.text

        decide = client.post(
            f'/broker/approvals/{approval_id}/decision',
            headers=otto_headers,
            json={'decision': 'approve'},
        )
        assert decide.status_code == 409, decide.text
        assert 'already claimed' in decide.json()['error']

        current = gw.audit.get_approval(approval_id, tenant_id='acme', workspace_id='research', environment='prod')
        assert current is not None
        assert current['status'] == 'pending'
        assert current['assigned_to'] == 'user:opal'


def test_workflow_tool_step_uses_current_actor_for_tool_audit(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    with TestClient(app) as client:
        gw = app.state.gw
        gw.audit.ensure_auth_user(username='alice', password='pw1', user_key='user:alice', role='user', tenant_id='acme', workspace_id='research')
        gw.audit.ensure_auth_user(username='opal', password='pw2', user_key='user:opal', role='operator', tenant_id='acme', workspace_id='research')
        alice_headers = {'Authorization': f'Bearer {_login(client, "alice", "pw1")}' }
        opal_headers = {'Authorization': f'Bearer {_login(client, "opal", "pw2")}' }

        create = client.post(
            '/broker/workflows',
            headers=alice_headers,
            json={
                'name': 'approval-to-tool',
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
        workflow_id = create.json()['workflow']['workflow_id']

        approvals = client.get('/broker/approvals?requested_role=operator', headers=opal_headers)
        approval_id = approvals.json()['items'][0]['approval_id']
        assert client.post(f'/broker/approvals/{approval_id}/claim', headers=opal_headers).status_code == 200
        decision = client.post(
            f'/broker/approvals/{approval_id}/decision',
            headers=opal_headers,
            json={'decision': 'approve'},
        )
        assert decision.status_code == 200, decision.text

        tool_calls = gw.audit.list_tool_calls(session_id=f'workflow:{workflow_id}', tenant_id='acme', workspace_id='research', environment='prod')
        assert len(tool_calls) == 1
        assert tool_calls[0]['tool_name'] == 'time_now'
        assert tool_calls[0]['user_key'] == 'user:opal'



def test_job_pause_resume_audit_uses_request_actor(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    with TestClient(app) as client:
        gw = app.state.gw
        gw.audit.ensure_auth_user(username='opal', password='pw2', user_key='user:opal', role='operator', tenant_id='acme', workspace_id='research')
        headers = {'Authorization': f'Bearer {_login(client, "opal", "pw2")}' }

        create = client.post(
            '/broker/jobs',
            headers=headers,
            json={
                'name': 'audited-job',
                'workflow_definition': {'steps': [{'id': 'note', 'kind': 'note', 'note': 'hello'}]},
                'schedule_kind': 'interval',
                'interval_s': 60,
            },
        )
        assert create.status_code == 200, create.text
        job_id = create.json()['job']['job_id']

        pause = client.post(f'/broker/jobs/{job_id}/pause', headers=headers)
        assert pause.status_code == 200, pause.text
        resume = client.post(f'/broker/jobs/{job_id}/resume', headers=headers)
        assert resume.status_code == 200, resume.text

        timeline = gw.audit.get_recent_events(limit=20, channel='workflow', tenant_id='acme', workspace_id='research', environment='prod')
        job_events = [
            item for item in timeline
            if item.get('session_id') == f'job:{job_id}' and item.get('payload', {}).get('event') in {'job_paused', 'job_resumed'}
        ]
        assert {entry['payload']['event'] for entry in job_events} == {'job_paused', 'job_resumed'}
        assert all(entry['user_id'] == 'user:opal' for entry in job_events)
