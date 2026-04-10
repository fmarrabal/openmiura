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
  history_limit: 6
memory:
  enabled: false
tools:
  sandbox_dir: "{sandbox_dir}"
admin:
  enabled: true
  token: secret-admin
broker:
  enabled: true
  base_path: "/broker"
auth:
  enabled: true
  session_ttl_s: 3600
''',
        encoding='utf-8',
    )


def _create_runtime(client: TestClient) -> str:
    response = client.post(
        '/admin/openclaw/runtimes',
        headers={'Authorization': 'Bearer secret-admin'},
        json={
            'actor': 'admin',
            'name': 'runtime-scheduler-pack',
            'base_url': 'simulated://openclaw',
            'transport': 'simulated',
            'allowed_agents': ['default'],
            'tenant_id': 'tenant-a',
            'workspace_id': 'ws-a',
            'environment': 'prod',
            'metadata': {
                'runtime_class': 'browser',
                'allowed_actions': ['chat'],
                'dispatch_policy': {
                    'poll_after_s': 0.1,
                },
                'heartbeat_policy': {
                    'active_run_stale_after_s': 0,
                    'auto_reconcile_after_s': 0,
                    'auto_poll_enabled': True,
                    'auto_reconcile_enabled': True,
                },
                'session_bridge': {
                    'enabled': True,
                    'workspace_connection': 'primary-conn',
                    'external_workspace_id': 'oc-ws-a',
                    'external_environment': 'prod',
                    'event_bridge_enabled': True,
                },
                'event_bridge': {
                    'token': 'evt-policy-pack',
                    'accepted_sources': ['openclaw'],
                    'accepted_event_types': ['run.progress', 'run.completed', 'run.failed'],
                },
            },
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload['runtime_summary']['metadata']['runtime_class'] == 'browser_automation'
    assert payload['runtime_summary']['metadata']['policy_pack'] == 'browser_automation'
    assert payload['runtime_summary']['dispatch_policy']['dispatch_mode'] == 'async'
    return payload['runtime']['runtime_id']


def _dispatch_async_run(client: TestClient, runtime_id: str, session_id: str) -> str:
    response = client.post(
        f'/admin/openclaw/runtimes/{runtime_id}/dispatch',
        headers={'Authorization': 'Bearer secret-admin'},
        json={
            'actor': 'admin',
            'action': 'chat',
            'agent_id': 'default',
            'payload': {'message': 'hola'},
            'session_id': session_id,
            'tenant_id': 'tenant-a',
            'workspace_id': 'ws-a',
            'environment': 'prod',
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload['dispatch']['canonical_status'] == 'accepted'
    return payload['dispatch']['dispatch_id']


def test_openclaw_policy_packs_and_periodic_recovery_worker(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    with TestClient(app) as client:
        packs = client.get(
            '/admin/openclaw/policy-packs?runtime_class=browser',
            headers={'Authorization': 'Bearer secret-admin'},
        )
        assert packs.status_code == 200, packs.text
        pack_items = packs.json()['items']
        assert len(pack_items) == 1
        assert pack_items[0]['pack_id'] == 'browser_automation'

        runtime_id = _create_runtime(client)

        applied = client.post(
            f'/admin/openclaw/runtimes/{runtime_id}/policy-pack',
            headers={'Authorization': 'Bearer secret-admin'},
            json={
                'actor': 'admin',
                'pack_name': 'incident_triage',
                'overrides': {
                    'heartbeat_policy': {
                        'active_run_stale_after_s': 0,
                        'auto_reconcile_after_s': 0,
                    },
                },
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert applied.status_code == 200, applied.text
        applied_payload = applied.json()
        assert applied_payload['runtime_summary']['metadata']['policy_pack'] == 'incident_triage'
        assert applied_payload['runtime_summary']['metadata']['runtime_class'] == 'incident_triage'
        assert applied_payload['runtime_summary']['recovery_schedule']['pack_name'] == 'incident_triage'

        scheduled = client.post(
            f'/admin/openclaw/runtimes/{runtime_id}/recovery-jobs',
            headers={'Authorization': 'Bearer secret-admin'},
            json={
                'actor': 'admin',
                'reason': 'periodic recovery worker',
                'schedule_kind': 'interval',
                'interval_s': 5,
                'not_before': time.time() - 1,
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert scheduled.status_code == 200, scheduled.text
        scheduled_payload = scheduled.json()
        job_id = scheduled_payload['job']['job_id']
        assert scheduled_payload['scheduler_policy']['pack_name'] == 'incident_triage'

        dispatch_id = _dispatch_async_run(client, runtime_id, 'sched-pack-001')

        worker = client.post(
            '/admin/openclaw/recovery-jobs/run-due',
            headers={'Authorization': 'Bearer secret-admin'},
            json={
                'actor': 'admin',
                'limit': 10,
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert worker.status_code == 200, worker.text
        worker_payload = worker.json()
        assert worker_payload['summary']['executed'] == 1
        assert worker_payload['items'][0]['job']['job_id'] == job_id
        assert worker_payload['items'][0]['recovery']['summary']['reconciled_count'] == 1

        detail = client.get(
            f'/admin/openclaw/dispatches/{dispatch_id}?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers={'Authorization': 'Bearer secret-admin'},
        )
        assert detail.status_code == 200, detail.text
        assert detail.json()['dispatch']['canonical_status'] == 'timed_out'

        jobs = client.get(
            '/admin/openclaw/recovery-jobs?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers={'Authorization': 'Bearer secret-admin'},
        )
        assert jobs.status_code == 200, jobs.text
        jobs_payload = jobs.json()
        assert jobs_payload['summary']['count'] == 1
        assert jobs_payload['items'][0]['runtime_id'] == runtime_id
        assert jobs_payload['items'][0]['run_count'] == 1
        assert jobs_payload['items'][0]['next_run_at'] is not None


def test_canvas_runtime_board_surfaces_recovery_jobs(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    with TestClient(app) as client:
        headers = {'Authorization': 'Bearer secret-admin'}
        canvas = client.post(
            '/admin/canvas/documents',
            headers=headers,
            json={'actor': 'admin', 'title': 'Runtime recovery board', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert canvas.status_code == 200, canvas.text
        canvas_id = canvas.json()['document']['canvas_id']

        runtime_id = _create_runtime(client)
        node = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes',
            headers=headers,
            json={
                'actor': 'admin',
                'node_type': 'openclaw_runtime',
                'label': 'Runtime recovery node',
                'data': {'runtime_id': runtime_id},
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert node.status_code == 200, node.text

        scheduled = client.post(
            f'/admin/openclaw/runtimes/{runtime_id}/recovery-jobs',
            headers=headers,
            json={
                'actor': 'admin',
                'reason': 'surface scheduled recovery in canvas',
                'schedule_kind': 'interval',
                'interval_s': 10,
                'not_before': time.time() + 120,
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert scheduled.status_code == 200, scheduled.text

        board = client.get(
            f'/admin/canvas/documents/{canvas_id}/views/runtime-board?tenant_id=tenant-a&workspace_id=ws-a&environment=prod&limit=10',
            headers=headers,
        )
        assert board.status_code == 200, board.text
        item = board.json()['items'][0]
        assert item['summary']['recovery_jobs_count'] == 1
        assert len(item['recovery_jobs']) == 1
        assert item['recovery_jobs'][0]['runtime_id'] == runtime_id
