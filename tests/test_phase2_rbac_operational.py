from __future__ import annotations

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
broker:
  enabled: true
  token: "broker-secret"
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
      rbac:
        username_roles:
          tina: tenant_admin
      workspaces:
        research:
          display_name: "Research"
          environments: [dev, prod]
          default_environment: "prod"
          rbac:
            username_roles:
              ivy: analyst
            role_inherits:
              analyst: [viewer]
            permission_grants:
              analyst: [events.read, sessions.read]
            role_scope_access:
              analyst: scoped
        ops:
          display_name: "Operations"
          environments: [staging, prod]
          default_environment: "staging"
    beta:
      display_name: "Beta LLC"
      workspaces:
        sales:
          display_name: "Sales"
          environments: [prod]
          default_environment: "prod"
''',
        encoding='utf-8',
    )


def _login(client: TestClient, username: str, password: str) -> str:
    response = client.post('/broker/auth/login', json={'username': username, 'password': password})
    assert response.status_code == 200, response.text
    return response.json()['token']


def test_tenant_admin_can_cross_workspace_within_tenant_but_not_cross_tenant(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    with TestClient(app) as client:
        gw = app.state.gw
        gw.audit.ensure_auth_user(
            username='tina',
            password='pw1',
            user_key='user:tina',
            role='user',
            tenant_id='acme',
            workspace_id=None,
        )

        token = _login(client, 'tina', 'pw1')
        headers = {'Authorization': f'Bearer {token}'}

        me = client.get('/broker/auth/me', headers=headers)
        assert me.status_code == 200, me.text
        payload = me.json()
        assert payload['role'] == 'tenant_admin'
        assert payload['scope_access'] == 'tenant'
        assert payload['scope_level'] == 'tenant'
        assert payload['tenant_id'] == 'acme'
        assert payload['workspace_id'] == 'research'

        allowed = client.post(
            '/broker/auth/authorize',
            headers={**headers, 'X-Tenant-Id': 'acme', 'X-Workspace-Id': 'ops', 'X-Environment': 'staging'},
            json={'permission': 'auth.manage', 'tenant_id': 'acme', 'workspace_id': 'ops', 'environment': 'staging'},
        )
        assert allowed.status_code == 200, allowed.text
        assert allowed.json()['allowed'] is True
        assert allowed.json()['scope']['workspace_id'] == 'ops'

        create_user = client.post(
            '/broker/auth/users',
            headers={**headers, 'X-Tenant-Id': 'acme', 'X-Workspace-Id': 'ops'},
            json={'username': 'oscar', 'password': 'pw2', 'role': 'user', 'tenant_id': 'acme', 'workspace_id': 'ops'},
        )
        assert create_user.status_code == 200, create_user.text
        assert create_user.json()['user']['workspace_id'] == 'ops'

        denied = client.post(
            '/broker/auth/authorize',
            headers=headers,
            json={'permission': 'auth.manage', 'tenant_id': 'beta', 'workspace_id': 'sales', 'environment': 'prod'},
        )
        assert denied.status_code == 403

        denied_create = client.post(
            '/broker/auth/users',
            headers=headers,
            json={'username': 'mallory', 'password': 'pw3', 'role': 'user', 'tenant_id': 'beta', 'workspace_id': 'sales'},
        )
        assert denied_create.status_code == 403


def test_custom_role_matrix_and_authorization_endpoint(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    with TestClient(app) as client:
        gw = app.state.gw
        gw.audit.ensure_auth_user(
            username='ivy',
            password='pw1',
            user_key='user:ivy',
            role='user',
            tenant_id='acme',
            workspace_id='research',
        )

        broker_headers = {'Authorization': 'Bearer broker-secret', 'X-Tenant-Id': 'acme', 'X-Workspace-Id': 'research'}
        matrix = client.get('/broker/auth/rbac/matrix', headers=broker_headers)
        assert matrix.status_code == 200, matrix.text
        payload = matrix.json()
        assert payload['current_scope_access'] == 'global'
        analyst = next(item for item in payload['items'] if item['role'] == 'analyst')
        assert 'viewer' in analyst['inherits']
        assert 'workspace.read' in analyst['effective_permissions']
        assert 'events.read' in analyst['effective_permissions']
        assert analyst['scope_access'] == 'scoped'
        assert analyst['scope_level'] == 'workspace'

        token = _login(client, 'ivy', 'pw1')
        headers = {'Authorization': f'Bearer {token}'}
        me = client.get('/broker/auth/me', headers=headers)
        assert me.status_code == 200, me.text
        me_payload = me.json()
        assert me_payload['role'] == 'analyst'
        assert me_payload['base_role'] == 'user'
        assert me_payload['scope_access'] == 'scoped'
        assert me_payload['scope_level'] == 'environment'

        can_read_events = client.post('/broker/auth/authorize', headers=headers, json={'permission': 'events.read'})
        assert can_read_events.status_code == 200, can_read_events.text
        assert can_read_events.json()['allowed'] is True
        assert can_read_events.json()['role'] == 'analyst'

        cannot_write_admin = client.post('/broker/auth/authorize', headers=headers, json={'permission': 'admin.write'})
        assert cannot_write_admin.status_code == 200, cannot_write_admin.text
        assert cannot_write_admin.json()['allowed'] is False
