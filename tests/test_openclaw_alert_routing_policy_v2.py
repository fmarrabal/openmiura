from __future__ import annotations

import json
import time
import urllib.error
from pathlib import Path

from fastapi.testclient import TestClient

import app as app_module
from openmiura.channels.slack import SlackClient
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
slack:
  bot_token: "xoxb-test"
  signing_secret: "slack-signing-secret"
''',
        encoding='utf-8',
    )


class _FakeWebhookResponse:
    def __init__(self, payload: dict[str, object] | None = None, status: int = 200) -> None:
        self.status = status
        self._payload = payload or {'ok': True}

    def read(self) -> bytes:
        return json.dumps(self._payload).encode('utf-8')

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class _FakeMailer:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []

    def send_email(self, *, to: str, subject: str, body: str, metadata: dict[str, object] | None = None):
        item = {'to': to, 'subject': subject, 'body': body, 'metadata': dict(metadata or {})}
        self.sent.append(item)
        return {'queued': False, 'message_id': f'msg-{len(self.sent)}'}


def test_alert_routing_policy_and_escalation_chain_schedule_targets_and_surface_in_canvas(tmp_path: Path, monkeypatch) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    slack_calls: list[dict[str, object]] = []

    def _fake_post_message(self, *, channel: str, text: str, thread_ts: str | None = None) -> None:
        slack_calls.append({'channel': channel, 'text': text, 'thread_ts': thread_ts})

    monkeypatch.setattr(SlackClient, 'post_message', _fake_post_message)

    next_weekday = (time.gmtime().tm_wday + 1) % 7

    with TestClient(app) as client:
        client.app.state.gw.mailer = _FakeMailer()
        headers = {'Authorization': 'Bearer secret-admin'}
        runtime_resp = client.post(
            '/admin/openclaw/runtimes',
            headers=headers,
            json={
                'actor': 'admin',
                'name': 'runtime-alert-routing',
                'base_url': 'simulated://openclaw',
                'transport': 'simulated',
                'allowed_agents': ['default'],
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
                'metadata': {
                    'runtime_class': 'incident',
                    'allowed_actions': ['chat'],
                    'dispatch_policy': {
                        'dispatch_mode': 'async',
                        'poll_after_s': 0.1,
                        'max_active_runs': 1,
                        'max_active_runs_per_workspace': 1,
                    },
                    'heartbeat_policy': {
                        'runtime_stale_after_s': 120,
                        'active_run_stale_after_s': 60,
                        'auto_reconcile_after_s': 600,
                        'poll_interval_s': 5,
                        'max_poll_retries': 1,
                        'auto_poll_enabled': False,
                        'auto_reconcile_enabled': False,
                        'stale_target_status': 'timed_out',
                    },
                    'slo_policy': {
                        'runtime_run_warn_ratio': 0.5,
                        'runtime_run_critical_ratio': 1.0,
                    },
                    'alert_workflow_policy': {
                        'default_silence_s': 300,
                        'max_silence_s': 7200,
                        'escalation_max_level': 3,
                    },
                    'alert_notification_policy': {
                        'dispatch_on_escalate': True,
                        'dedupe_window_s': 0,
                        'default_target_types': ['queue'],
                        'default_queue_name': 'runtime-alerts',
                    },
                    'alert_notification_targets': [
                        {'target_id': 'slack-oncall', 'type': 'slack', 'channel': 'C-oncall', 'workflow_actions': ['escalate']},
                        {'target_id': 'email-oncall', 'type': 'email', 'email_to': 'ops@example.com', 'workflow_actions': ['escalate']},
                        {'target_id': 'queue-oncall', 'type': 'queue', 'queue_name': 'ops-escalations', 'workflow_actions': ['escalate']},
                    ],
                    'alert_routing_policy': {
                        'enabled': True,
                        'default_timezone': 'UTC',
                        'rules': [
                            {'rule_id': 'route-slack', 'alert_codes': ['runtime_run_saturation'], 'workflow_actions': ['escalate'], 'tenant_ids': ['tenant-a'], 'workspace_ids': ['ws-a'], 'target_ids': ['slack-oncall']},
                            {'rule_id': 'route-chain', 'alert_codes': ['runtime_run_saturation'], 'workflow_actions': ['escalate'], 'chain_id': 'sev-chain'},
                        ],
                        'escalation_chains': [
                            {
                                'chain_id': 'sev-chain',
                                'steps': [
                                    {'step_id': 'delayed-email', 'target_ids': ['email-oncall'], 'delay_s': 120},
                                    {'step_id': 'windowed-queue', 'target_ids': ['queue-oncall'], 'time_windows': [{'days': [next_weekday], 'start_hour': 0, 'end_hour': 1}]},
                                ],
                            }
                        ],
                    },
                    'session_bridge': {
                        'enabled': True,
                        'workspace_connection': 'primary-conn',
                        'external_workspace_id': 'oc-ws-a',
                        'external_environment': 'prod',
                        'event_bridge_enabled': True,
                    },
                },
            },
        )
        assert runtime_resp.status_code == 200, runtime_resp.text
        runtime_id = runtime_resp.json()['runtime']['runtime_id']

        canvas_resp = client.post(
            '/admin/canvas/documents',
            headers=headers,
            json={'actor': 'admin', 'title': 'Alert routing canvas', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        canvas_id = canvas_resp.json()['document']['canvas_id']
        node_resp = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes',
            headers=headers,
            json={'actor': 'admin', 'node_type': 'openclaw_runtime', 'label': 'Routing runtime', 'data': {'runtime_id': runtime_id}, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        node_id = node_resp.json()['node']['node_id']

        dispatch_resp = client.post(
            f'/admin/openclaw/runtimes/{runtime_id}/dispatch',
            headers=headers,
            json={'actor': 'admin', 'action': 'chat', 'agent_id': 'default', 'payload': {'message': 'hola'}, 'session_id': 'route-001', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert dispatch_resp.status_code == 200, dispatch_resp.text

        escalate_resp = client.post(
            f'/admin/openclaw/runtimes/{runtime_id}/alerts/runtime_run_saturation/escalate',
            headers=headers,
            json={'actor': 'admin', 'reason': 'route escalation', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert escalate_resp.status_code == 200, escalate_resp.text
        payload = escalate_resp.json()
        assert payload['notifications']['summary']['count'] == 3
        assert payload['notifications']['summary']['status_counts']['delivered'] == 1
        assert payload['notifications']['summary']['scheduled_count'] == 2
        assert len(slack_calls) == 1
        assert slack_calls[0]['channel'] == 'C-oncall'

        routing_resp = client.get(
            f'/admin/openclaw/runtimes/{runtime_id}/alert-routing?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert routing_resp.status_code == 200, routing_resp.text
        routing_payload = routing_resp.json()
        assert routing_payload['summary']['rule_count'] == 2
        assert routing_payload['summary']['escalation_chain_count'] == 1

        jobs_resp = client.get(
            f'/admin/openclaw/alert-delivery-jobs?runtime_id={runtime_id}&tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert jobs_resp.status_code == 200, jobs_resp.text
        jobs_payload = jobs_resp.json()
        assert jobs_payload['summary']['count'] == 2
        assert jobs_payload['summary']['due'] == 0

        dispatches_resp = client.get(
            f'/admin/openclaw/alert-dispatches?runtime_id={runtime_id}&tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert dispatches_resp.status_code == 200, dispatches_resp.text
        status_counts = dispatches_resp.json()['summary']['status_counts']
        assert status_counts['delivered'] == 1
        assert status_counts['scheduled'] == 2

        board = client.get(
            f'/admin/canvas/documents/{canvas_id}/views/runtime-board?tenant_id=tenant-a&workspace_id=ws-a&environment=prod&limit=10',
            headers=headers,
        )
        assert board.status_code == 200, board.text
        entry = board.json()['items'][0]
        assert entry['summary']['routing_rule_count'] == 2
        assert entry['summary']['escalation_chain_count'] == 1
        assert entry['summary']['alert_delivery_job_count'] == 2

        inspector = client.get(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert inspector.status_code == 200, inspector.text
        related = inspector.json()['related']
        assert related['runtime_alert_routing']['summary']['rule_count'] == 2
        assert len((related['runtime_alert_delivery_jobs'] or {}).get('items', [])) == 2


def test_alert_routing_retry_job_runs_due_and_delivers_on_second_attempt(tmp_path: Path, monkeypatch) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    calls = {'count': 0}

    def _fake_urlopen(req, timeout=10.0):
        calls['count'] += 1
        if calls['count'] == 1:
            raise urllib.error.URLError('temporary-failure')
        return _FakeWebhookResponse({'accepted': True}, status=202)

    monkeypatch.setattr('openmiura.application.openclaw.scheduler.urllib.request.urlopen', _fake_urlopen)

    with TestClient(app) as client:
        headers = {'Authorization': 'Bearer secret-admin'}
        runtime_resp = client.post(
            '/admin/openclaw/runtimes',
            headers=headers,
            json={
                'actor': 'admin',
                'name': 'runtime-alert-retry-routing',
                'base_url': 'simulated://openclaw',
                'transport': 'simulated',
                'allowed_agents': ['default'],
                'tenant_id': 'tenant-a',
                'workspace_id': 'ws-a',
                'environment': 'prod',
                'metadata': {
                    'runtime_class': 'incident',
                    'allowed_actions': ['chat'],
                    'dispatch_policy': {'dispatch_mode': 'async', 'max_active_runs': 1, 'max_active_runs_per_workspace': 1},
                    'heartbeat_policy': {'runtime_stale_after_s': 120, 'active_run_stale_after_s': 60, 'auto_reconcile_after_s': 600, 'poll_interval_s': 5, 'max_poll_retries': 1, 'auto_poll_enabled': False, 'auto_reconcile_enabled': False},
                    'slo_policy': {'runtime_run_warn_ratio': 0.5, 'runtime_run_critical_ratio': 1.0},
                    'alert_notification_policy': {'dispatch_on_escalate': True, 'dedupe_window_s': 0, 'default_target_types': ['queue'], 'default_queue_name': 'runtime-alerts'},
                    'alert_notification_targets': [
                        {'target_id': 'webhook-oncall', 'type': 'webhook', 'url': 'https://hooks.example.test/runtime-alert', 'workflow_actions': ['escalate']},
                    ],
                    'alert_routing_policy': {
                        'enabled': True,
                        'default_timezone': 'UTC',
                        'rules': [
                            {'rule_id': 'webhook-retry', 'alert_codes': ['runtime_run_saturation'], 'workflow_actions': ['escalate'], 'target_ids': ['webhook-oncall'], 'max_retries': 1, 'retry_backoff_s': 0},
                        ],
                    },
                    'session_bridge': {'enabled': True, 'workspace_connection': 'primary-conn', 'external_workspace_id': 'oc-ws-a', 'external_environment': 'prod', 'event_bridge_enabled': True},
                },
            },
        )
        assert runtime_resp.status_code == 200, runtime_resp.text
        runtime_id = runtime_resp.json()['runtime']['runtime_id']

        dispatch_resp = client.post(
            f'/admin/openclaw/runtimes/{runtime_id}/dispatch',
            headers=headers,
            json={'actor': 'admin', 'action': 'chat', 'agent_id': 'default', 'payload': {'message': 'hola'}, 'session_id': 'route-002', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert dispatch_resp.status_code == 200, dispatch_resp.text

        escalate_resp = client.post(
            f'/admin/openclaw/runtimes/{runtime_id}/alerts/runtime_run_saturation/escalate',
            headers=headers,
            json={'actor': 'admin', 'reason': 'retry escalation', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert escalate_resp.status_code == 200, escalate_resp.text
        payload = escalate_resp.json()
        assert payload['notifications']['summary']['count'] == 1
        assert payload['notifications']['summary']['retry_job_count'] == 1

        jobs_resp = client.get(
            f'/admin/openclaw/alert-delivery-jobs?runtime_id={runtime_id}&tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert jobs_resp.status_code == 200, jobs_resp.text
        jobs_payload = jobs_resp.json()
        assert jobs_payload['summary']['count'] == 1
        assert jobs_payload['summary']['due'] == 1

        run_due_resp = client.post(
            '/admin/openclaw/alert-delivery-jobs/run-due',
            headers=headers,
            json={'actor': 'admin', 'runtime_id': runtime_id, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert run_due_resp.status_code == 200, run_due_resp.text
        assert run_due_resp.json()['summary']['executed'] == 1

        deliveries_resp = client.get(
            f'/admin/openclaw/alert-dispatches?runtime_id={runtime_id}&tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert deliveries_resp.status_code == 200, deliveries_resp.text
        deliveries_payload = deliveries_resp.json()
        assert deliveries_payload['summary']['status_counts']['failed'] >= 1
        assert deliveries_payload['summary']['status_counts']['delivered'] >= 1
        assert calls['count'] == 2
