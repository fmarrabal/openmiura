from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import app as app_module
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
      metadata:
        owner: "platform"
        provider: "github"
        expires_at: "2030-01-01T00:00:00Z"
        labels: ["source-control", "prod"]
''',
        encoding='utf-8',
    )


def _login(client: TestClient) -> str:
    response = client.post('/broker/auth/login', json={'username': 'admin', 'password': 'secret123'})
    assert response.status_code == 200, response.text
    return response.json()['token']


def test_phase7_secret_governance_catalog_usage_and_ui(tmp_path: Path, monkeypatch) -> None:
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
            domain='https://api.github.com/repos/openai/openmiura',
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

        ui = client.get('/ui')
        assert ui.status_code == 200
        assert 'Secrets' in ui.text
        assert 'secretCatalogBox' in ui.text
        assert 'runSecretExplainBtn' in ui.text

        catalog = client.get(
            '/broker/admin/secrets/catalog',
            headers=headers,
            params={'tenant_id': 'tenant-a', 'workspace_id': 'ops', 'environment': 'prod', 'limit': 20},
        )
        assert catalog.status_code == 200, catalog.text
        catalog_payload = catalog.json()
        assert catalog_payload['ok'] is True
        assert catalog_payload['summary']['enabled'] is True
        assert catalog_payload['summary']['visible_refs'] == 1
        assert catalog_payload['items'][0]['ref'] == 'github_pat'
        assert catalog_payload['items'][0]['usage_count'] == 2
        assert catalog_payload['items'][0]['rotation']['status'] == 'ok'

        usage = client.get(
            '/broker/admin/secrets/usage',
            headers=headers,
            params={'ref': 'github_pat', 'tenant_id': 'tenant-a', 'workspace_id': 'ops', 'environment': 'prod'},
        )
        assert usage.status_code == 200, usage.text
        usage_payload = usage.json()
        assert usage_payload['ok'] is True
        assert usage_payload['items'][0]['ref'] == 'github_pat'
        assert usage_payload['items'][0]['count'] == 2
        assert 'web_fetch' in usage_payload['items'][0]['tools']
        assert 'api.github.com' in usage_payload['items'][0]['domains']

        explain_allowed = client.post(
            '/broker/admin/secrets/explain',
            headers=headers,
            json={
                'ref': 'github_pat',
                'tool_name': 'web_fetch',
                'user_role': 'admin',
                'tenant_id': 'tenant-a',
                'workspace_id': 'ops',
                'environment': 'prod',
                'domain': 'https://api.github.com/repos/openai/openmiura',
            },
        )
        assert explain_allowed.status_code == 200, explain_allowed.text
        explain_allowed_payload = explain_allowed.json()
        assert explain_allowed_payload['ok'] is True
        assert explain_allowed_payload['allowed'] is True
        assert explain_allowed_payload['recent_usage']['count'] == 2

        explain_denied = client.post(
            '/broker/admin/secrets/explain',
            headers=headers,
            json={
                'ref': 'github_pat',
                'tool_name': 'terminal_exec',
                'user_role': 'admin',
                'tenant_id': 'tenant-a',
                'workspace_id': 'ops',
                'environment': 'prod',
                'domain': 'https://api.github.com/repos/openai/openmiura',
            },
        )
        assert explain_denied.status_code == 200, explain_denied.text
        explain_denied_payload = explain_denied.json()
        assert explain_denied_payload['ok'] is True
        assert explain_denied_payload['allowed'] is False
        assert 'not allowed for tool' in explain_denied_payload['reason']
