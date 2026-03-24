from __future__ import annotations

import json
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
      workspaces:
        research:
          display_name: "Research"
          environments: [dev, prod]
          default_environment: "prod"
          rbac:
            username_roles:
              alice: operator
            permission_denies:
              operator: [auth.manage]
        ops:
          display_name: "Operations"
          environments: [staging, prod]
          default_environment: "staging"
''',
        encoding='utf-8',
    )


def _headers(**extra: str) -> dict[str, str]:
    base = {'Authorization': 'Bearer broker-secret'}
    base.update(extra)
    return base


def _seed_scoped_data(gw) -> None:
    research_user = gw.audit.ensure_auth_user(
        username='alice',
        password='pw1',
        user_key='user:alice',
        role='user',
        tenant_id='acme',
        workspace_id='research',
    )
    ops_user = gw.audit.ensure_auth_user(
        username='bob',
        password='pw2',
        user_key='user:bob',
        role='user',
        tenant_id='acme',
        workspace_id='ops',
    )
    gw.audit.create_auth_session(user_id=int(research_user['id']), tenant_id='acme', workspace_id='research', environment='prod')
    gw.audit.create_auth_session(user_id=int(ops_user['id']), tenant_id='acme', workspace_id='ops', environment='staging')
    gw.audit.create_api_token(user_key='user:alice', label='research-token', tenant_id='acme', workspace_id='research', environment='prod')
    gw.audit.create_api_token(user_key='user:bob', label='ops-token', tenant_id='acme', workspace_id='ops', environment='staging')

    research_session = gw.audit.get_or_create_session('broker', 'user:alice', 'research-session', tenant_id='acme', workspace_id='research', environment='prod')
    ops_session = gw.audit.get_or_create_session('broker', 'user:bob', 'ops-session', tenant_id='acme', workspace_id='ops', environment='staging')

    gw.audit.log_event('in', 'broker', 'user:alice', research_session, {'scope': 'research'}, tenant_id='acme', workspace_id='research', environment='prod')
    gw.audit.log_event('in', 'broker', 'user:bob', ops_session, {'scope': 'ops'}, tenant_id='acme', workspace_id='ops', environment='staging')

    gw.audit.add_memory_item(
        user_key='user:alice',
        kind='fact',
        text='research memory',
        embedding_blob=b'\x00\x00\x00\x00',
        meta_json=json.dumps({'scope': 'research'}),
        tenant_id='acme',
        workspace_id='research',
        environment='prod',
    )
    gw.audit.add_memory_item(
        user_key='user:bob',
        kind='fact',
        text='ops memory',
        embedding_blob=b'\x00\x00\x00\x00',
        meta_json=json.dumps({'scope': 'ops'}),
        tenant_id='acme',
        workspace_id='ops',
        environment='staging',
    )

    gw.audit.log_tool_call(
        session_id=research_session,
        user_key='user:alice',
        agent_id='default',
        tool_name='time_now',
        args_json='{}',
        ok=True,
        result_excerpt='research tool call',
        error='',
        duration_ms=1.0,
    )
    gw.audit.log_tool_call(
        session_id=ops_session,
        user_key='user:bob',
        agent_id='default',
        tool_name='time_now',
        args_json='{}',
        ok=True,
        result_excerpt='ops tool call',
        error='',
        duration_ms=1.0,
    )


def test_workspace_rbac_binding_and_permission_override(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    with TestClient(app) as client:
        gw = app.state.gw
        gw.audit.ensure_auth_user(
            username='alice',
            password='pw1',
            user_key='user:alice',
            role='user',
            tenant_id='acme',
            workspace_id='research',
        )

        login = client.post('/broker/auth/login', json={'username': 'alice', 'password': 'pw1'})
        assert login.status_code == 200, login.text
        token = login.json()['token']

        me = client.get('/broker/auth/me', headers={'Authorization': f'Bearer {token}'})
        assert me.status_code == 200, me.text
        payload = me.json()
        assert payload['base_role'] == 'user'
        assert payload['role'] == 'operator'
        assert payload['scope_access'] == 'scoped'
        assert 'sessions.read' in payload['permissions']
        assert 'auth.manage' not in payload['permissions']
        assert payload['tenant_id'] == 'acme'
        assert payload['workspace_id'] == 'research'

        denied = client.post(
            '/broker/auth/users',
            headers={'Authorization': f'Bearer {token}'},
            json={'username': 'mallory', 'password': 'pw3', 'role': 'user'},
        )
        assert denied.status_code == 403


def test_scope_segregation_filters_admin_and_auth_views(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    with TestClient(app) as client:
        _seed_scoped_data(app.state.gw)

        research_headers = _headers(**{'X-Tenant-Id': 'acme', 'X-Workspace-Id': 'research', 'X-Environment': 'prod'})

        users = client.get('/broker/auth/users', headers=research_headers)
        assert users.status_code == 200, users.text
        usernames = [item['username'] for item in users.json()['items']]
        assert usernames == ['alice']

        sessions = client.get('/broker/auth/sessions', headers=research_headers)
        assert sessions.status_code == 200, sessions.text
        session_items = sessions.json()['items']
        assert len(session_items) == 1
        assert session_items[0]['workspace_id'] == 'research'

        tokens = client.get('/broker/auth/tokens', headers=research_headers)
        assert tokens.status_code == 200, tokens.text
        token_items = tokens.json()['items']
        assert len(token_items) == 1
        assert token_items[0]['workspace_id'] == 'research'
        assert token_items[0]['label'] == 'research-token'

        admin_sessions = client.get('/broker/admin/sessions', headers=research_headers)
        assert admin_sessions.status_code == 200, admin_sessions.text
        assert [item['session_id'] for item in admin_sessions.json()['items']] == ['research-session']

        events = client.get('/broker/admin/events', headers=research_headers)
        assert events.status_code == 200, events.text
        event_items = events.json()['items']
        assert len(event_items) >= 1
        assert all(item['workspace_id'] == 'research' for item in event_items)
        assert any(item['payload'].get('scope') == 'research' for item in event_items)
        assert all(item['payload'].get('scope') != 'ops' for item in event_items)

        memory = client.get('/broker/admin/memory/search', headers=research_headers, params={'q': 'memory', 'limit': 10})
        assert memory.status_code == 200, memory.text
        mem_items = memory.json()['items']
        assert len(mem_items) == 1
        assert mem_items[0]['workspace_id'] == 'research'
        assert mem_items[0]['text'] == 'research memory'

        tool_calls = client.get('/broker/admin/tool-calls', headers=research_headers)
        assert tool_calls.status_code == 200, tool_calls.text
        tool_items = tool_calls.json()['items']
        assert len(tool_items) == 1
        assert tool_items[0]['workspace_id'] == 'research'
        assert tool_items[0]['result_excerpt'] == 'research tool call'

        overview = client.get('/broker/admin/overview', headers=research_headers)
        assert overview.status_code == 200, overview.text
        summary = overview.json()['summary']
        assert summary['sessions'] == 1
        assert summary['memory']['total'] == 1
        assert summary['tool_calls'] == 1
        assert summary['events'] >= 1
        assert summary['scope']['workspace_id'] == 'research'
