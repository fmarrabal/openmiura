from __future__ import annotations

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


def _create_runtime(client: TestClient, headers: dict[str, str], *, name: str, metadata: dict[str, object]) -> str:
    runtime_resp = client.post(
        '/admin/openclaw/runtimes',
        headers=headers,
        json={
            'actor': 'admin',
            'name': name,
            'base_url': 'simulated://openclaw',
            'transport': 'simulated',
            'allowed_agents': ['default'],
            'tenant_id': 'tenant-a',
            'workspace_id': 'ws-a',
            'environment': 'prod',
            'metadata': metadata,
        },
    )
    assert runtime_resp.status_code == 200, runtime_resp.text
    return runtime_resp.json()['runtime']['runtime_id']


def _create_canvas_runtime_node(client: TestClient, headers: dict[str, str], runtime_id: str) -> tuple[str, str]:
    canvas_resp = client.post(
        '/admin/canvas/documents',
        headers=headers,
        json={
            'actor': 'admin',
            'title': 'Alert approval canvas',
            'tenant_id': 'tenant-a',
            'workspace_id': 'ws-a',
            'environment': 'prod',
        },
    )
    assert canvas_resp.status_code == 200, canvas_resp.text
    canvas_id = canvas_resp.json()['document']['canvas_id']
    node_resp = client.post(
        f'/admin/canvas/documents/{canvas_id}/nodes',
        headers=headers,
        json={
            'actor': 'admin',
            'node_type': 'openclaw_runtime',
            'label': 'Runtime node',
            'data': {'runtime_id': runtime_id},
            'tenant_id': 'tenant-a',
            'workspace_id': 'ws-a',
            'environment': 'prod',
        },
    )
    assert node_resp.status_code == 200, node_resp.text
    return canvas_id, node_resp.json()['node']['node_id']


def _trigger_runtime_saturation(client: TestClient, headers: dict[str, str], runtime_id: str, session_id: str) -> None:
    dispatch_resp = client.post(
        f'/admin/openclaw/runtimes/{runtime_id}/dispatch',
        headers=headers,
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
    assert dispatch_resp.status_code == 200, dispatch_resp.text


def test_alert_escalation_can_be_gated_by_approval_and_completed_from_canvas(tmp_path: Path, monkeypatch) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    slack_calls: list[dict[str, object]] = []

    def _fake_post_message(self, *, channel: str, text: str, thread_ts: str | None = None) -> None:
        slack_calls.append({'channel': channel, 'text': text, 'thread_ts': thread_ts})

    monkeypatch.setattr(SlackClient, 'post_message', _fake_post_message)

    with TestClient(app) as client:
        headers = {'Authorization': 'Bearer secret-admin'}
        metadata = {
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
            'alert_escalation_policy': {
                'enabled': True,
                'auto_dispatch_on_approval': True,
                'default_requires_approval': False,
                'required_alert_codes': ['runtime_run_saturation'],
                'requested_role': 'ops-approver',
                'ttl_s': 900,
            },
            'alert_notification_policy': {
                'dispatch_on_escalate': True,
                'dedupe_window_s': 0,
                'default_target_types': ['slack'],
                'max_targets_per_dispatch': 5,
            },
            'alert_notification_targets': [
                {'target_id': 'slack-oncall', 'type': 'slack', 'channel': 'C-oncall', 'workflow_actions': ['escalate']},
            ],
            'session_bridge': {
                'enabled': True,
                'workspace_connection': 'primary-conn',
                'external_workspace_id': 'oc-ws-a',
                'external_environment': 'prod',
                'event_bridge_enabled': True,
            },
        }
        runtime_id = _create_runtime(client, headers, name='runtime-alert-approval', metadata=metadata)
        canvas_id, node_id = _create_canvas_runtime_node(client, headers, runtime_id)
        _trigger_runtime_saturation(client, headers, runtime_id, 'approval-001')

        escalate_resp = client.post(
            f'/admin/openclaw/runtimes/{runtime_id}/alerts/runtime_run_saturation/escalate',
            headers=headers,
            json={'actor': 'admin', 'reason': 'requires approval', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert escalate_resp.status_code == 200, escalate_resp.text
        escalate_payload = escalate_resp.json()
        assert escalate_payload['approval_required'] is True
        assert escalate_payload['notifications'] is None
        assert escalate_payload['state']['workflow_status'] == 'approval_pending'
        approval_id = escalate_payload['approval']['approval_id']
        assert slack_calls == []

        approvals_resp = client.get(
            f'/admin/openclaw/alert-escalation-approvals?runtime_id={runtime_id}&tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert approvals_resp.status_code == 200, approvals_resp.text
        approvals_payload = approvals_resp.json()
        assert approvals_payload['summary']['pending_count'] == 1
        assert approvals_payload['items'][0]['approval_id'] == approval_id

        board_before = client.get(
            f'/admin/canvas/documents/{canvas_id}/views/runtime-board?tenant_id=tenant-a&workspace_id=ws-a&environment=prod&limit=10',
            headers=headers,
        )
        assert board_before.status_code == 200, board_before.text
        entry_before = board_before.json()['items'][0]
        assert entry_before['summary']['pending_alert_approval_count'] == 1
        assert 'approve_alert_escalation' in entry_before['summary']['available_operations']

        inspector = client.get(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert inspector.status_code == 200, inspector.text
        related = inspector.json()['related']
        assert related['runtime_alert_approvals']['summary']['pending_count'] == 1

        approve_action = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/approve_alert_escalation?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={
                'actor': 'admin',
                'reason': 'approved from canvas',
                'payload': {'approval_id': approval_id, 'alert_code': 'runtime_run_saturation'},
                'session_id': 'canvas-alert-approval',
            },
        )
        assert approve_action.status_code == 200, approve_action.text
        result = approve_action.json()['result']
        assert result['approval']['status'] == 'approved'
        assert result['state']['workflow_status'] == 'escalated'
        assert result['notifications']['summary']['status_counts']['delivered'] == 1
        assert len(slack_calls) == 1
        assert slack_calls[0]['channel'] == 'C-oncall'

        board_after = client.get(
            f'/admin/canvas/documents/{canvas_id}/views/runtime-board?tenant_id=tenant-a&workspace_id=ws-a&environment=prod&limit=10',
            headers=headers,
        )
        assert board_after.status_code == 200, board_after.text
        entry_after = board_after.json()['items'][0]
        assert entry_after['summary']['pending_alert_approval_count'] == 0
        assert entry_after['summary']['escalated_alert_count'] >= 1

        timeline = client.get(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/timeline?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert timeline.status_code == 200, timeline.text
        kinds = {item['kind'] for item in timeline.json()['items']}
        assert 'alert_approval' in kinds
        assert 'alert_workflow' in kinds


def test_notification_budget_rate_limits_dispatches_and_surfaces_in_admin_and_canvas(tmp_path: Path, monkeypatch) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    slack_calls: list[dict[str, object]] = []

    def _fake_post_message(self, *, channel: str, text: str, thread_ts: str | None = None) -> None:
        slack_calls.append({'channel': channel, 'text': text, 'thread_ts': thread_ts})

    monkeypatch.setattr(SlackClient, 'post_message', _fake_post_message)

    with TestClient(app) as client:
        headers = {'Authorization': 'Bearer secret-admin'}
        metadata = {
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
                'dispatch_on_escalate': False,
                'dedupe_window_s': 0,
                'default_target_types': ['slack'],
                'max_targets_per_dispatch': 5,
            },
            'alert_notification_budget_policy': {
                'enabled': True,
                'window_s': 300,
                'target_type_limits': {'slack': 1},
                'count_statuses': ['delivered', 'queued', 'pending', 'scheduled'],
                'on_limit': 'drop',
            },
            'alert_notification_targets': [
                {'target_id': 'slack-oncall', 'type': 'slack', 'channel': 'C-oncall', 'workflow_actions': ['manual', 'escalate']},
            ],
            'session_bridge': {
                'enabled': True,
                'workspace_connection': 'primary-conn',
                'external_workspace_id': 'oc-ws-a',
                'external_environment': 'prod',
                'event_bridge_enabled': True,
            },
        }
        runtime_id = _create_runtime(client, headers, name='runtime-alert-budget', metadata=metadata)
        canvas_id, node_id = _create_canvas_runtime_node(client, headers, runtime_id)
        _trigger_runtime_saturation(client, headers, runtime_id, 'budget-001')

        first_dispatch = client.post(
            f'/admin/openclaw/runtimes/{runtime_id}/alerts/runtime_run_saturation/dispatch',
            headers=headers,
            json={'actor': 'admin', 'workflow_action': 'manual', 'target_id': 'slack-oncall', 'reason': 'first page', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert first_dispatch.status_code == 200, first_dispatch.text
        assert first_dispatch.json()['summary']['status_counts']['delivered'] == 1
        assert len(slack_calls) == 1

        second_dispatch = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/actions/dispatch_alert_notification?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
            json={
                'actor': 'admin',
                'reason': 'second page should be limited',
                'payload': {'alert_code': 'runtime_run_saturation', 'workflow_action': 'escalate', 'target_id': 'slack-oncall'},
                'session_id': 'canvas-alert-dispatch',
            },
        )
        assert second_dispatch.status_code == 200, second_dispatch.text
        second_result = second_dispatch.json()['result']
        assert second_result['summary']['status_counts']['rate_limited'] == 1
        assert second_result['items'][0]['rate_limited'] is True
        assert len(slack_calls) == 1

        targets_resp = client.get(
            f'/admin/openclaw/runtimes/{runtime_id}/notification-targets?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert targets_resp.status_code == 200, targets_resp.text
        targets_payload = targets_resp.json()
        assert targets_payload['budget_policy']['enabled'] is True
        assert targets_payload['budget_policy']['on_limit'] == 'drop'
        assert targets_payload['summary']['count'] == 1

        deliveries_resp = client.get(
            f'/admin/openclaw/alert-dispatches?runtime_id={runtime_id}&tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert deliveries_resp.status_code == 200, deliveries_resp.text
        deliveries_payload = deliveries_resp.json()
        assert deliveries_payload['summary']['status_counts']['delivered'] == 1
        assert deliveries_payload['summary']['status_counts']['rate_limited'] == 1

        board = client.get(
            f'/admin/canvas/documents/{canvas_id}/views/runtime-board?tenant_id=tenant-a&workspace_id=ws-a&environment=prod&limit=10',
            headers=headers,
        )
        assert board.status_code == 200, board.text
        entry = board.json()['items'][0]
        assert entry['summary']['rate_limited_dispatch_count'] == 1
        assert entry['summary']['notification_target_count'] == 1
        assert 'dispatch_alert_notification' in entry['summary']['available_operations']
