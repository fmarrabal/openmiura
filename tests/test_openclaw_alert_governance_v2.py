from __future__ import annotations

from datetime import datetime, timezone
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
  bot_token: "slack-bot-token-test"
  signing_secret: "slack-signing-secret"
''',
        encoding='utf-8',
    )


def _weekday_utc() -> int:
    return datetime.now(timezone.utc).weekday()


def _create_runtime(client: TestClient, headers: dict[str, str], *, name: str, metadata: dict[str, object]) -> str:
    resp = client.post(
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
    assert resp.status_code == 200, resp.text
    return resp.json()['runtime']['runtime_id']


def _dispatch_active_run(client: TestClient, headers: dict[str, str], runtime_id: str, *, session_id: str) -> None:
    resp = client.post(
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
    assert resp.status_code == 200, resp.text


def _base_metadata() -> dict[str, object]:
    return {
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
            'workspace_run_warn_ratio': 0.5,
            'workspace_run_critical_ratio': 1.0,
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


def test_alert_governance_applies_quiet_hours_schedule_and_maintenance_suppression(tmp_path: Path, monkeypatch) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}
    slack_calls: list[dict[str, object]] = []

    def _fake_post_message(self, *, channel: str, text: str, thread_ts: str | None = None) -> None:
        slack_calls.append({'channel': channel, 'text': text, 'thread_ts': thread_ts})

    monkeypatch.setattr(SlackClient, 'post_message', _fake_post_message)

    metadata = _base_metadata()
    metadata['alert_governance_policy'] = {
        'default_timezone': 'UTC',
        'quiet_hours': {
            'enabled': True,
            'timezone': 'UTC',
            'weekdays': [_weekday_utc()],
            'start_time': '00:00',
            'end_time': '23:59',
            'action': 'schedule',
        },
        'maintenance_windows': [
            {
                'window_id': 'maint-1',
                'enabled': True,
                'timezone': 'UTC',
                'weekdays': [_weekday_utc()],
                'start_time': '00:00',
                'end_time': '23:59',
                'action': 'suppress',
                'allow_alert_codes': ['runtime_run_saturation'],
            }
        ],
    }

    with TestClient(app) as client:
        runtime_id = _create_runtime(client, headers, name='runtime-governance', metadata=metadata)
        _dispatch_active_run(client, headers, runtime_id, session_id='gov-001')

        governance_resp = client.get(
            f'/admin/openclaw/runtimes/{runtime_id}/alert-governance?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert governance_resp.status_code == 200, governance_resp.text
        governance_payload = governance_resp.json()
        assert governance_payload['current']['quiet_hours_active'] is True
        assert governance_payload['current']['maintenance_active'] is True

        runtime_alerts = client.get(
            f'/admin/openclaw/runtimes/{runtime_id}/alerts?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert runtime_alerts.status_code == 200, runtime_alerts.text
        alerts_payload = runtime_alerts.json()
        codes = {item['code'] for item in alerts_payload['items']}
        assert 'runtime_run_saturation' in codes
        assert 'workspace_run_saturation' in codes

        scheduled_dispatch = client.post(
            f'/admin/openclaw/runtimes/{runtime_id}/alerts/runtime_run_saturation/dispatch',
            headers=headers,
            json={'actor': 'admin', 'workflow_action': 'escalate', 'target_id': 'slack-oncall', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert scheduled_dispatch.status_code == 200, scheduled_dispatch.text
        scheduled_payload = scheduled_dispatch.json()
        assert scheduled_payload['summary']['scheduled_count'] == 1
        assert scheduled_payload['summary']['suppressed_count'] == 0
        assert slack_calls == []

        suppressed_dispatch = client.post(
            f'/admin/openclaw/runtimes/{runtime_id}/alerts/workspace_run_saturation/dispatch',
            headers=headers,
            json={'actor': 'admin', 'workflow_action': 'escalate', 'target_id': 'slack-oncall', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert suppressed_dispatch.status_code == 200, suppressed_dispatch.text
        suppressed_payload = suppressed_dispatch.json()
        assert suppressed_payload['summary']['suppressed_count'] == 1
        assert suppressed_payload['items'][0]['delivery']['delivery_status'] == 'suppressed'
        assert slack_calls == []


def test_alert_governance_override_can_disable_quiet_hours_and_allow_delivery(tmp_path: Path, monkeypatch) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}
    slack_calls: list[dict[str, object]] = []

    def _fake_post_message(self, *, channel: str, text: str, thread_ts: str | None = None) -> None:
        slack_calls.append({'channel': channel, 'text': text, 'thread_ts': thread_ts})

    monkeypatch.setattr(SlackClient, 'post_message', _fake_post_message)

    metadata = _base_metadata()
    metadata['alert_governance_policy'] = {
        'default_timezone': 'UTC',
        'quiet_hours': {
            'enabled': True,
            'timezone': 'UTC',
            'weekdays': [_weekday_utc()],
            'start_time': '00:00',
            'end_time': '23:59',
            'action': 'schedule',
        },
        'override_policies': [
            {
                'policy_id': 'ws-prod-override',
                'match': {'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
                'quiet_hours': {'enabled': False},
            }
        ],
    }

    with TestClient(app) as client:
        runtime_id = _create_runtime(client, headers, name='runtime-governance-override', metadata=metadata)
        _dispatch_active_run(client, headers, runtime_id, session_id='gov-override-001')

        governance_resp = client.get(
            f'/admin/openclaw/runtimes/{runtime_id}/alert-governance?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert governance_resp.status_code == 200, governance_resp.text
        governance_payload = governance_resp.json()
        assert governance_payload['current']['quiet_hours_active'] is False
        assert governance_payload['summary']['active_override_count'] == 1

        dispatch_resp = client.post(
            f'/admin/openclaw/runtimes/{runtime_id}/alerts/runtime_run_saturation/dispatch',
            headers=headers,
            json={'actor': 'admin', 'workflow_action': 'escalate', 'target_id': 'slack-oncall', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert dispatch_resp.status_code == 200, dispatch_resp.text
        payload = dispatch_resp.json()
        assert payload['summary']['status_counts']['delivered'] == 1
        assert payload['summary']['scheduled_count'] == 0
        assert slack_calls and slack_calls[0]['channel'] == 'C-oncall'


def test_alert_governance_storm_suppression_is_visible_in_canvas(tmp_path: Path, monkeypatch) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    headers = {'Authorization': 'Bearer secret-admin'}
    slack_calls: list[dict[str, object]] = []

    def _fake_post_message(self, *, channel: str, text: str, thread_ts: str | None = None) -> None:
        slack_calls.append({'channel': channel, 'text': text, 'thread_ts': thread_ts})

    monkeypatch.setattr(SlackClient, 'post_message', _fake_post_message)

    metadata = _base_metadata()
    metadata['dispatch_policy'] = {
        'dispatch_mode': 'async',
        'poll_after_s': 0.1,
        'max_active_runs': 2,
        'max_active_runs_per_workspace': 2,
    }
    metadata['slo_policy'] = {
        'runtime_run_warn_ratio': 0.5,
        'runtime_run_critical_ratio': 10.0,
        'workspace_run_warn_ratio': 0.5,
        'workspace_run_critical_ratio': 10.0,
    }
    metadata['alert_governance_policy'] = {
        'storm_policy': {
            'enabled': True,
            'active_alert_threshold': 2,
            'suppress_severities': ['warn'],
            'action': 'suppress',
            'suppress_for_s': 900,
        }
    }

    with TestClient(app) as client:
        runtime_id = _create_runtime(client, headers, name='runtime-governance-storm', metadata=metadata)
        canvas_resp = client.post(
            '/admin/canvas/documents',
            headers=headers,
            json={'actor': 'admin', 'title': 'Governance canvas', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert canvas_resp.status_code == 200, canvas_resp.text
        canvas_id = canvas_resp.json()['document']['canvas_id']
        node_resp = client.post(
            f'/admin/canvas/documents/{canvas_id}/nodes',
            headers=headers,
            json={'actor': 'admin', 'node_type': 'openclaw_runtime', 'label': 'Runtime node', 'data': {'runtime_id': runtime_id}, 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert node_resp.status_code == 200, node_resp.text
        node_id = node_resp.json()['node']['node_id']

        _dispatch_active_run(client, headers, runtime_id, session_id='gov-storm-001')

        governance_resp = client.get(
            f'/admin/openclaw/runtimes/{runtime_id}/alert-governance?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert governance_resp.status_code == 200, governance_resp.text
        governance_payload = governance_resp.json()
        assert governance_payload['summary']['suppressed_alert_count'] >= 2

        board_resp = client.get(
            f'/admin/canvas/documents/{canvas_id}/views/runtime-board?tenant_id=tenant-a&workspace_id=ws-a&environment=prod&limit=10',
            headers=headers,
        )
        assert board_resp.status_code == 200, board_resp.text
        board_payload = board_resp.json()
        assert board_payload['summary']['storm_active_count'] == 1
        assert board_payload['summary']['governance_suppressed_alert_count'] >= 2
        entry = board_payload['items'][0]
        assert entry['summary']['storm_active'] is True
        assert entry['summary']['governance_suppressed_alert_count'] >= 2

        inspector_resp = client.get(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/inspector?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert inspector_resp.status_code == 200, inspector_resp.text
        related = inspector_resp.json()['related']
        assert related['runtime_alert_governance']['summary']['suppressed_alert_count'] >= 2

        timeline_resp = client.get(
            f'/admin/canvas/documents/{canvas_id}/nodes/{node_id}/timeline?tenant_id=tenant-a&workspace_id=ws-a&environment=prod',
            headers=headers,
        )
        assert timeline_resp.status_code == 200, timeline_resp.text
        kinds = {item['kind'] for item in timeline_resp.json()['items']}
        assert 'alert_governance' in kinds

        dispatch_resp = client.post(
            f'/admin/openclaw/runtimes/{runtime_id}/alerts/runtime_run_saturation/dispatch',
            headers=headers,
            json={'actor': 'admin', 'workflow_action': 'escalate', 'tenant_id': 'tenant-a', 'workspace_id': 'ws-a', 'environment': 'prod'},
        )
        assert dispatch_resp.status_code == 200, dispatch_resp.text
        payload = dispatch_resp.json()
        assert payload['summary']['suppressed_count'] == 1
        assert payload['items'][0]['delivery']['delivery_status'] == 'suppressed'
        assert slack_calls == []
