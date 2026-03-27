from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app as app_module
from openmiura.core.audit import AuditStore
from openmiura.core.config import SecretRefSettings, SecretsSettings
from openmiura.core.secrets import SecretAccessDenied, SecretBroker
from openmiura.gateway import Gateway


POLICIES_YAML = """defaults:
  tools: true
"""


def _write_config(path: Path, policies_path: Path) -> None:
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
agents:
  default:
    system_prompt: "base"
    tools: ["time_now", "web_fetch"]
memory:
  enabled: false
tools:
  sandbox_dir: "{sandbox_dir}"
broker:
  enabled: true
  base_path: "/broker"
auth:
  enabled: true
  session_ttl_s: 3600
policies_path: "{policies_path.as_posix()}"
secrets:
  enabled: true
  redact_logs: true
  refs:
    github_pat:
      value: "synthetic_github_token_for_tests_only"
      description: "GitHub PAT"
      allowed_tools: ["web_fetch"]
      allowed_roles: ["admin"]
      allowed_tenants: ["tenant-a"]
      allowed_workspaces: ["ops"]
      allowed_environments: ["prod"]
      allowed_domains: ["api.github.com"]
''',
        encoding='utf-8',
    )


def _login(client: TestClient) -> str:
    response = client.post('/broker/auth/login', json={'username': 'admin', 'password': 'secret123'})
    assert response.status_code == 200, response.text
    return response.json()['token']


def test_secret_broker_audits_denied_resolution_attempts(audit_store: AuditStore) -> None:
    broker = SecretBroker(
        settings=SecretsSettings(
            enabled=True,
            refs={
                'github_pat': SecretRefSettings(
                    ref='github_pat',
                    value='synthetic_test_token',
                    allowed_tools=['web_fetch'],
                    allowed_roles=['admin'],
                    allowed_tenants=['acme'],
                    allowed_workspaces=['research'],
                    allowed_environments=['prod'],
                    allowed_domains=['api.github.com'],
                )
            },
        ),
        audit=audit_store,
    )

    with pytest.raises(SecretAccessDenied):
        broker.resolve(
            'github_pat',
            tool_name='terminal_exec',
            user_role='admin',
            user_key='user:alice',
            session_id='sess-1',
            tenant_id='acme',
            workspace_id='research',
            environment='prod',
            domain='api.github.com',
        )

    events = audit_store.list_events_filtered(limit=10, channels=['security'], event_names=['secret_access_denied'])
    assert len(events) == 1
    payload = events[0]['payload']
    assert payload['ref'] == 'github_pat'
    assert payload['tool_name'] == 'terminal_exec'
    assert payload['allowed'] is False
    assert 'not allowed for tool' in payload['reason']
    assert payload['domain'] == 'api.github.com'


def test_secret_governance_summary_and_timeline_include_denied_attempts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv('OPENMIURA_UI_ADMIN_USERNAME', 'admin')
    monkeypatch.setenv('OPENMIURA_UI_ADMIN_PASSWORD', 'secret123')
    policies_path = tmp_path / 'policies.yaml'
    policies_path.write_text(POLICIES_YAML, encoding='utf-8')
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg, policies_path)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    with TestClient(app) as client:
        token = _login(client)
        headers = {'Authorization': f'Bearer {token}'}
        gw = app.state.gw

        session_id = gw.audit.get_or_create_session(
            'security',
            'user:admin',
            'secret-session-1',
            tenant_id='tenant-a',
            workspace_id='ops',
            environment='prod',
        )
        gw.secret_broker.resolve(
            'github_pat',
            tool_name='web_fetch',
            user_role='admin',
            user_key='user:admin',
            session_id=session_id,
            tenant_id='tenant-a',
            workspace_id='ops',
            environment='prod',
            domain='api.github.com',
        )
        with pytest.raises(SecretAccessDenied):
            gw.secret_broker.resolve(
                'github_pat',
                tool_name='terminal_exec',
                user_role='admin',
                user_key='user:admin',
                session_id=session_id,
                tenant_id='tenant-a',
                workspace_id='ops',
                environment='prod',
                domain='api.github.com',
            )

        summary = client.get(
            '/broker/admin/secrets/summary',
            headers=headers,
            params={'tenant_id': 'tenant-a', 'workspace_id': 'ops', 'environment': 'prod', 'limit': 20},
        )
        assert summary.status_code == 200, summary.text
        summary_payload = summary.json()
        assert summary_payload['ok'] is True
        assert summary_payload['summary']['resolved_events'] == 1
        assert summary_payload['summary']['denied_events'] == 1
        assert summary_payload['summary']['top_denied_refs'][0]['value'] == 'github_pat'
        assert summary_payload['recent_denied'][0]['tool_name'] == 'terminal_exec'

        timeline = client.get(
            '/broker/admin/secrets/timeline',
            headers=headers,
            params={
                'tenant_id': 'tenant-a',
                'workspace_id': 'ops',
                'environment': 'prod',
                'ref': 'github_pat',
                'outcome': 'denied',
                'limit': 20,
            },
        )
        assert timeline.status_code == 200, timeline.text
        timeline_payload = timeline.json()
        assert timeline_payload['ok'] is True
        assert len(timeline_payload['items']) == 1
        assert timeline_payload['items'][0]['event'] == 'secret_access_denied'
        assert timeline_payload['items'][0]['reason']

        catalog = client.get(
            '/broker/admin/secrets/catalog',
            headers=headers,
            params={'tenant_id': 'tenant-a', 'workspace_id': 'ops', 'environment': 'prod', 'limit': 20},
        )
        assert catalog.status_code == 200, catalog.text
        catalog_payload = catalog.json()
        assert catalog_payload['items'][0]['usage_count'] == 1
        assert catalog_payload['items'][0]['denied_count'] == 1
