from __future__ import annotations

import json
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


def test_runtime_alert_escalation_dispatches_real_targets_and_surfaces_them_in_canvas(tmp_path: Path, monkeypatch) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    slack_calls: list[dict[str, object]] = []
    webhook_calls: list[dict[str, object]] = []

    def _fake_post_message(self, *, channel: str, text: str, thread_ts: str | None = None) -> None:
        slack_calls.append({'channel': channel, 'text': text, 'thread_ts': thread_ts})

    def _fake_urlopen(req, timeout=10.0):
        body = req.data.decode('utf-8') if getattr(req, 'data', None) else ''
        webhook_calls.append({'url': req.full_url, 'timeout': timeout, 'body': json.loads(body or '{}'), 'headers': dict(req.header_items())})
        return _FakeWebhookResponse({'accepted': True}, status=202)

    monkeypatch.setattr(SlackClient, 'post_message', _fake_post_message)
    monkeypatch.setattr('openmiura.application.openclaw.scheduler.urllib.request.urlopen', _fake_urlopen)

    with TestClient(app) as client:
        client.app.state.gw.mailer = _FakeMailer()
        headers = {'Authorization': 'Bearer secret-admin'}

        runtime_resp = client.post(
            '/admin/openclaw/runtimes',
            headers=headers,
            json={
                'actor': 'admin',
                'name': 'runtime-alert-dispatches',
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
                        {'target_id': 'slack-oncall', 'type': 'slack', 'channel': 'C-oncall', 'workflow_actions': ['escalate', 'manual']},
                        {'target_id': 'webhook-oncall', 'type': 'webhook', 'url': 'https://hooks.example.test/runtime-alert', 'workflow_actions': ['escalate', 'manual']},
                        {'target_id': 'app-oncall', 'type': 'app', 'target_path': '/ui/?tab=operator', 'workflow_actions': ['escalate']},
                        {'target_id': 'queue-oncall', 'type': 'queue', 'queue_name': 'ops-escalations', 'workflow_actions': ['escalate', 'manual']},
                        {'target_id': 'email-oncall', 'type': 'email', 'email_to': 'ops@example.com', 'workflow_actions': ['escalate']},
                    ],
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
            json={'actor': 'admin', 'title': 'Alert dispatch canvas', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert canvas_resp.status_code == 200, canvas_resp.text
        canvas_id = canvas_resp.json()['document']['canvas_id']
        node_resp = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes',
            headers=headers,
            json={'actor': 'admin', 'node_type': 'openclaw_runtime', 'label': 'Dispatch runtime', 'data': {'runtime_id': runtime_id}, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert node_resp.status_code == 200, node_resp.text
        node_id = node_resp.json()['node']['node_id']

        dispatch_resp = client.post(
            f'/admin/openclaw/runtimes/{runtime_id}/dispatch',
            headers=headers,
            json={'actor': 'admin', 'action': 'chat', 'agent_id': 'default', 'payload': {'message': 'hola'}, 'session_id': 'notif-001', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert dispatch_resp.status_code == 200, dispatch_resp.text

        escalate_resp = client.post(
            f'/admin/openclaw/runtimes/{runtime_id}/alerts/runtime_run_saturation/escalate',
            headers=headers,
            json={'actor': 'admin', 'reason': 'page oncall', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert escalate_resp.status_code == 200, escalate_resp.text
        escalate_payload = escalate_resp.json()
        assert escalate_payload['state']['workflow_status'] == 'escalated'
        notifications = escalate_payload['notifications']
        assert notifications['summary']['count'] == 5
        assert notifications['summary']['status_counts']['delivered'] == 4
        assert notifications['summary']['status_counts']['queued'] == 1

        assert len(slack_calls) == 1
        assert slack_calls[0]['channel'] == 'C-oncall'
        assert len(webhook_calls) == 1
        assert webhook_calls[0]['url'] == 'https://hooks.example.test/runtime-alert'
        assert len(client.app.state.gw.mailer.sent) == 1
        assert client.app.state.gw.mailer.sent[0]['to'] == 'ops@example.com'

        targets_resp = client.get(
            f'/admin/openclaw/runtimes/{runtime_id}/notification-targets?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert targets_resp.status_code == 200, targets_resp.text
        assert targets_resp.json()['summary']['count'] == 5

        deliveries_resp = client.get(
            f'/admin/openclaw/alert-dispatches?runtime_id={runtime_id}&tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert deliveries_resp.status_code == 200, deliveries_resp.text
        deliveries_payload = deliveries_resp.json()
        assert deliveries_payload['summary']['count'] == 5
        assert deliveries_payload['summary']['status_counts']['delivered'] == 4
        assert deliveries_payload['summary']['type_counts']['slack'] == 1
        assert deliveries_payload['summary']['type_counts']['webhook'] == 1
        assert deliveries_payload['summary']['type_counts']['app'] == 1
        assert deliveries_payload['summary']['type_counts']['queue'] == 1
        assert deliveries_payload['summary']['type_counts']['email'] == 1

        board = client.get(
            f'/admin/canvas/documents/{canvas_id}/views/runtime-board?tenant_id=tenant-a&workspace_id=ws-a&environment=prod&limit=10',
            headers=headers,
        )
        assert board.status_code == 200, board.text
        board_payload = board.json()
        entry = board_payload['items'][0]
        assert entry['summary']['notification_target_count'] == 5
        assert entry['summary']['alert_dispatch_count'] == 5
        assert entry['summary']['alert_dispatch_status_counts']['delivered'] == 4
        assert board_payload['summary']['alert_dispatch_count'] >= 5

        inspector = client.get(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert inspector.status_code == 200, inspector.text
        inspector_payload = inspector.json()
        assert 'dispatch_alert_notification' in inspector_payload['available_actions']
        assert len((inspector_payload['related']['runtime_alert_dispatches'] or {}).get('items', [])) == 5
        assert len((inspector_payload['related']['runtime_notification_targets'] or {}).get('items', [])) == 5

        timeline = client.get(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/timeline?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert timeline.status_code == 200, timeline.text
        kinds = {item['kind'] for item in timeline.json()['items']}
        assert 'alert_dispatch' in kinds


def test_runtime_alert_manual_dispatch_via_canvas_can_target_single_queue(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    with TestClient(app) as client:
        headers = {'Authorization': 'Bearer secret-admin'}
        runtime_resp = client.post(
            '/admin/openclaw/runtimes',
            headers=headers,
            json={
                'actor': 'admin',
                'name': 'runtime-alert-manual-dispatch',
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
                    'alert_notification_policy': {'dispatch_on_escalate': False, 'dedupe_window_s': 0, 'default_target_types': ['queue'], 'default_queue_name': 'runtime-alerts'},
                    'alert_notification_targets': [
                        {'target_id': 'queue-oncall', 'type': 'queue', 'queue_name': 'ops-escalations', 'workflow_actions': ['manual']},
                    ],
                    'session_bridge': {'enabled': True, 'workspace_connection': 'primary-conn', 'external_workspace_id': 'oc-ws-a', 'external_environment': 'prod', 'event_bridge_enabled': True},
                },
            },
        )
        assert runtime_resp.status_code == 200, runtime_resp.text
        runtime_id = runtime_resp.json()['runtime']['runtime_id']

        canvas_resp = client.post(
            '/admin/canvas/documents',
            headers=headers,
            json={'actor': 'admin', 'title': 'Manual dispatch canvas', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        canvas_id = canvas_resp.json()['document']['canvas_id']
        node_resp = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes',
            headers=headers,
            json={'actor': 'admin', 'node_type': 'openclaw_runtime', 'label': 'Dispatch runtime', 'data': {'runtime_id': runtime_id}, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        node_id = node_resp.json()['node']['node_id']

        dispatch_resp = client.post(
            f'/admin/openclaw/runtimes/{runtime_id}/dispatch',
            headers=headers,
            json={'actor': 'admin', 'action': 'chat', 'agent_id': 'default', 'payload': {'message': 'hola'}, 'session_id': 'notif-002', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert dispatch_resp.status_code == 200, dispatch_resp.text

        action_resp = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/dispatch_alert_notification?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={'actor': 'admin', 'reason': 'manual queue dispatch', 'payload': {'alert_code': 'runtime_run_saturation', 'workflow_action': 'manual', 'target_id': 'queue-oncall'}},
        )
        assert action_resp.status_code == 200, action_resp.text
        result = action_resp.json()['result']
        assert result['summary']['count'] == 1
        delivery = result['items'][0]['delivery']
        assert delivery['target_id'] == 'queue-oncall'
        assert delivery['delivery_status'] == 'queued'

        deliveries_resp = client.get(
            f'/admin/openclaw/alert-dispatches?runtime_id={runtime_id}&tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert deliveries_resp.status_code == 200, deliveries_resp.text
        assert deliveries_resp.json()['summary']['count'] >= 1
