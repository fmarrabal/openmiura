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


def test_admin_and_canvas_surface_concurrency_observability(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    scheduler = OpenClawRecoverySchedulerService()

    with TestClient(app) as client:
        headers = {'Authorization': 'Bearer secret-admin'}
        runtime_resp = client.post(
            '/admin/openclaw/runtimes',
            headers=headers,
            json={
                'actor': 'admin',
                'name': 'runtime-observability',
                'base_url': 'simulated://openclaw',
                'transport': 'simulated',
                'allowed_agents': ['default'],
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
                'metadata': {
                    'runtime_class': 'browser',
                    'allowed_actions': ['chat'],
                    'dispatch_policy': {'dispatch_mode': 'async', 'poll_after_s': 0.1, 'max_active_runs': 1, 'max_active_runs_per_workspace': 1},
                    'session_bridge': {'enabled': True, 'workspace_connection': 'primary-conn', 'external_workspace_id': 'oc-ws-a', 'external_environment': 'prod', 'event_bridge_enabled': True},
                    'event_bridge': {'token': 'evt-observe', 'accepted_sources': ['openclaw'], 'accepted_event_types': ['run.progress', 'run.completed']},
                },
            },
        )
        assert runtime_resp.status_code == 200, runtime_resp.text
        runtime_id = runtime_resp.json()['runtime']['runtime_id']

        canvas_resp = client.post(
            '/admin/canvas/documents',
            headers=headers,
            json={'actor': 'admin', 'title': 'Concurrency canvas', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert canvas_resp.status_code == 200, canvas_resp.text
        canvas_id = canvas_resp.json()['document']['canvas_id']
        node_resp = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes',
            headers=headers,
            json={'actor': 'admin', 'node_type': 'openclaw_runtime', 'label': 'Observable runtime', 'data': {'runtime_id': runtime_id}, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert node_resp.status_code == 200, node_resp.text
        node_id = node_resp.json()['node']['node_id']

        dispatch_resp = client.post(
            f'/admin/openclaw/runtimes/{runtime_id}/dispatch',
            headers=headers,
            json={'actor': 'admin', 'action': 'chat', 'agent_id': 'default', 'payload': {'message': 'hola'}, 'session_id': 'obs-001', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert dispatch_resp.status_code == 200, dispatch_resp.text

        job_resp = client.post(
            f'/admin/openclaw/runtimes/{runtime_id}/recovery-jobs',
            headers=headers,
            json={'actor': 'admin', 'reason': 'observe', 'schedule_kind': 'interval', 'interval_s': 5, 'not_before': time.time() - 1, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert job_resp.status_code == 200, job_resp.text
        job_id = job_resp.json()['job']['job_id']

        gw = app.state.gw
        scope = {'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'}
        runtime_lease = gw.audit.acquire_worker_lease(lease_key=scheduler._runtime_lease_key(runtime_id), holder_id='worker-a', lease_ttl_s=60, metadata={'kind': 'runtime'}, **scope)
        assert runtime_lease['acquired'] is True
        workspace_lease = gw.audit.acquire_worker_lease(lease_key=scheduler._workspace_lease_keys(scope, limit=1)[0], holder_id='worker-a', lease_ttl_s=60, metadata={'kind': 'workspace'}, **scope)
        assert workspace_lease['acquired'] is True
        idem = gw.audit.claim_idempotency_record(idempotency_key=scheduler._job_idempotency_key(job_id, int(time.time())), holder_id='worker-a', ttl_s=300, scope_kind='openclaw_runtime_recovery', metadata={'runtime_id': runtime_id}, **scope)
        assert idem['claimed'] is True

        leases = client.get(
            f'/admin/openclaw/worker-leases?runtime_id={runtime_id}&tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert leases.status_code == 200, leases.text
        lease_payload = leases.json()
        assert lease_payload['summary']['active_count'] >= 2
        assert lease_payload['summary']['active_type_counts']['runtime'] >= 1
        assert lease_payload['summary']['active_type_counts']['workspace'] >= 1

        idempotency = client.get(
            f'/admin/openclaw/idempotency-records?runtime_id={runtime_id}&tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert idempotency.status_code == 200, idempotency.text
        idem_payload = idempotency.json()
        assert idem_payload['summary']['active_count'] >= 1
        assert idem_payload['summary']['status_counts']['in_progress'] >= 1

        concurrency = client.get(
            f'/admin/openclaw/runtimes/{runtime_id}/concurrency?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert concurrency.status_code == 200, concurrency.text
        conc_payload = concurrency.json()
        assert conc_payload['summary']['runtime_lock_active'] is True
        assert conc_payload['summary']['workspace_slot_pressure_ratio'] >= 1.0
        assert conc_payload['summary']['runtime_run_pressure_ratio'] >= 1.0
        assert conc_payload['summary']['in_progress_idempotency_count'] >= 1

        board = client.get(
            f'/admin/canvas/documents/{canvas_id}/views/runtime-board?tenant_id=tenant-a&workspace_id=ws-a&environment=prod&limit=10',
            headers=headers,
        )
        assert board.status_code == 200, board.text
        board_payload = board.json()
        assert board_payload['summary']['active_leases'] >= 2
        assert board_payload['summary']['in_progress_idempotency_count'] >= 1
        entry = board_payload['items'][0]
        assert entry['concurrency']['summary']['runtime_lock_active'] is True
        assert entry['summary']['active_leases'] >= 2
        assert 'scheduler:workspace_slot_saturated' in entry['summary']['warnings']

        inspector = client.get(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert inspector.status_code == 200, inspector.text
        inspector_payload = inspector.json()
        assert inspector_payload['related']['runtime_concurrency']['summary']['runtime_lock_active'] is True

        timeline = client.get(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/timeline?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert timeline.status_code == 200, timeline.text
        kinds = {item['kind'] for item in timeline.json()['items']}
        assert 'lease' in kinds
        assert 'idempotency' in kinds
