from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

import app as app_module
from openmiura.application.openclaw import OpenClawRecoverySchedulerService
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


def _create_runtime(client: TestClient, *, name: str = 'runtime-concurrency', workspace_id: str = 'ws-a') -> str:
    response = client.post(
        '/admin/openclaw/runtimes',
        headers={'Authorization': 'Bearer secret-admin'},
        json={
            'actor': 'admin',
            'name': name,
            'base_url': 'simulated://openclaw',
            'transport': 'simulated',
            'allowed_agents': ['default'],
            'tenant_id': 'tenant-a',
            'workspace_id': workspace_id,
            'environment': 'prod',
            'metadata': {
                'runtime_class': 'browser',
                'allowed_actions': ['chat'],
                'dispatch_policy': {
                    'dispatch_mode': 'async',
                    'poll_after_s': 0.1,
                    'max_active_runs': 1,
                    'max_active_runs_per_workspace': 1,
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
                    'external_workspace_id': f'oc-{workspace_id}',
                    'external_environment': 'prod',
                    'event_bridge_enabled': True,
                },
                'event_bridge': {
                    'token': 'evt-concurrency',
                    'accepted_sources': ['openclaw'],
                    'accepted_event_types': ['run.progress', 'run.completed', 'run.failed'],
                },
            },
        },
    )
    assert response.status_code == 200, response.text
    return response.json()['runtime']['runtime_id']


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


def _schedule_due_job(client: TestClient, runtime_id: str) -> str:
    response = client.post(
        f'/admin/openclaw/runtimes/{runtime_id}/recovery-jobs',
        headers={'Authorization': 'Bearer secret-admin'},
        json={
            'actor': 'admin',
            'reason': 'concurrency job',
            'schedule_kind': 'interval',
            'interval_s': 5,
            'not_before': time.time() - 1,
            'tenant_id': 'tenant-a',
            'workspace_id': 'ws-a',
            'environment': 'prod',
        },
    )
    assert response.status_code == 200, response.text
    return response.json()['job']['job_id']


def test_dispatch_active_run_backpressure_blocks_second_async_run(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    with TestClient(app) as client:
        runtime_id = _create_runtime(client)
        _dispatch_async_run(client, runtime_id, 'bp-001')

        blocked = client.post(
            f'/admin/openclaw/runtimes/{runtime_id}/dispatch',
            headers={'Authorization': 'Bearer secret-admin'},
            json={
                'actor': 'admin',
                'action': 'chat',
                'agent_id': 'default',
                'payload': {'message': 'otra vez'},
                'session_id': 'bp-002',
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
            },
        )
        assert blocked.status_code == 403, blocked.text
        assert 'backpressure limit' in blocked.text


def test_scheduler_idempotency_prevents_duplicate_due_slot_recovery(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    scheduler = OpenClawRecoverySchedulerService()

    with TestClient(app) as client:
        runtime_id = _create_runtime(client)
        dispatch_id = _dispatch_async_run(client, runtime_id, 'idem-001')
        job_id = _schedule_due_job(client, runtime_id)
        gw = app.state.gw
        item = gw.audit.get_job_schedule(job_id, tenant_id='tenant-a', workspace_id='ws-a', environment='prod')
        assert item is not None

        first = scheduler._run_single_recovery_job(
            gw,
            item=item,
            actor='worker-a',
            user_role='system',
            user_key='worker-a',
            holder_id='worker-a-holder',
        )
        assert first.get('skipped') is not True
        assert (first.get('recovery') or {}).get('summary', {}).get('reconciled_count') == 1

        second = scheduler._run_single_recovery_job(
            gw,
            item=item,
            actor='worker-b',
            user_role='system',
            user_key='worker-b',
            holder_id='worker-b-holder',
        )
        assert second['skipped'] is True
        assert second['skip_reason'] == 'duplicate_completed'

        job = gw.audit.get_job_schedule(job_id, tenant_id='tenant-a', workspace_id='ws-a', environment='prod')
        assert job is not None and int(job['run_count']) == 1
        dispatch = gw.audit.get_openclaw_dispatch(dispatch_id, tenant_id='tenant-a', workspace_id='ws-a', environment='prod')
        assert dispatch is not None
        assert dispatch['status'] == 'timed_out'


def test_scheduler_workspace_backpressure_skips_due_job_when_slot_is_held(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    scheduler = OpenClawRecoverySchedulerService()

    with TestClient(app) as client:
        runtime_id = _create_runtime(client)
        _dispatch_async_run(client, runtime_id, 'lease-001')
        _schedule_due_job(client, runtime_id)
        gw = app.state.gw
        scope = {'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'}
        workspace_lease_key = scheduler._workspace_lease_keys(scope, limit=1)[0]
        acquired = gw.audit.acquire_worker_lease(
            lease_key=workspace_lease_key,
            holder_id='other-worker',
            lease_ttl_s=60,
            metadata={'kind': 'workspace-test'},
            **scope,
        )
        assert acquired['acquired'] is True

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
        summary = worker.json()['summary']
        assert summary['executed'] == 0
        assert summary['skipped_backpressure'] == 1
