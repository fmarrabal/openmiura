from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

import app as app_module
from openmiura.core.audit import AuditStore
from openmiura.core.identity import IdentityManager
from openmiura.core.pending_confirmations import PendingToolConfirmationStore
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
        ops:
          display_name: "Operations"
          environments: [staging, prod]
          default_environment: "staging"
''',
        encoding='utf-8',
    )


def _headers(*, workspace: str, environment: str) -> dict[str, str]:
    return {
        'Authorization': 'Bearer broker-secret',
        'X-Tenant-Id': 'acme',
        'X-Workspace-Id': workspace,
        'X-Environment': environment,
    }


def test_session_scope_reuse_is_rejected(tmp_path: Path) -> None:
    store = AuditStore(str(tmp_path / 'audit.db'))
    store.init_db()
    store.get_or_create_session('broker', 'user:alice', 'shared-session', tenant_id='acme', workspace_id='research', environment='prod')
    try:
        store.get_or_create_session('broker', 'user:alice', 'shared-session', tenant_id='acme', workspace_id='ops', environment='staging')
        assert False, 'cross-scope session reuse should fail'
    except ValueError as exc:
        assert 'scope mismatch' in str(exc)


def test_identity_manager_is_scoped_by_workspace(tmp_path: Path) -> None:
    store = AuditStore(str(tmp_path / 'audit.db'))
    store.init_db()
    identity = IdentityManager(store)

    identity.link('tg:1', 'user:research', linked_by='test', tenant_id='acme', workspace_id='research')
    identity.link('tg:1', 'user:ops', linked_by='test', tenant_id='acme', workspace_id='ops')

    assert identity.resolve('tg:1', tenant_id='acme', workspace_id='research') == 'user:research'
    assert identity.resolve('tg:1', tenant_id='acme', workspace_id='ops') == 'user:ops'
    assert identity.resolve('tg:1', tenant_id='acme', workspace_id='missing') is None


def test_pending_confirmations_are_scoped() -> None:
    store = PendingToolConfirmationStore()
    store.set(
        's-1',
        user_key='user:alice',
        agent_id='default',
        tool_name='fs_write',
        args={'path': 'x.txt'},
        tenant_id='acme',
        workspace_id='research',
        environment='prod',
    )
    assert store.get('s-1', tenant_id='acme', workspace_id='ops', environment='staging') is None
    assert store.consume('s-1', user_key='user:alice', tenant_id='acme', workspace_id='ops', environment='staging') is None
    item = store.consume('s-1', user_key='user:alice', tenant_id='acme', workspace_id='research', environment='prod')
    assert item is not None
    assert item['workspace_id'] == 'research'


def test_broker_state_routes_are_scope_filtered(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    with TestClient(app) as client:
        gw = app.state.gw
        research_session = gw.audit.get_or_create_session('broker', 'user:alice', 'research-session', tenant_id='acme', workspace_id='research', environment='prod')
        ops_session = gw.audit.get_or_create_session('broker', 'user:bob', 'ops-session', tenant_id='acme', workspace_id='ops', environment='staging')
        gw.audit.append_message(research_session, 'user', 'research hello')
        gw.audit.append_message(ops_session, 'user', 'ops hello')
        gw.pending_confirmations.set('research-session', user_key='user:alice', agent_id='default', tool_name='time_now', args={}, tenant_id='acme', workspace_id='research', environment='prod')
        gw.pending_confirmations.set('ops-session', user_key='user:bob', agent_id='default', tool_name='time_now', args={}, tenant_id='acme', workspace_id='ops', environment='staging')
        gw.audit.add_memory_item('user:alice', 'fact', 'research memory', b'\x00\x00\x00\x00', json.dumps({'scope': 'research'}), tenant_id='acme', workspace_id='research', environment='prod')
        gw.audit.add_memory_item('user:bob', 'fact', 'ops memory', b'\x00\x00\x00\x00', json.dumps({'scope': 'ops'}), tenant_id='acme', workspace_id='ops', environment='staging')

        sessions = client.get('/broker/sessions', headers=_headers(workspace='research', environment='prod'))
        assert sessions.status_code == 200, sessions.text
        assert [item['session_id'] for item in sessions.json()['items']] == ['research-session']

        msgs = client.get('/broker/sessions/ops-session/messages', headers=_headers(workspace='research', environment='prod'))
        assert msgs.status_code == 404, msgs.text

        confirmations = client.get('/broker/confirmations', headers=_headers(workspace='research', environment='prod'))
        assert confirmations.status_code == 200, confirmations.text
        assert [item['session_id'] for item in confirmations.json()['items']] == ['research-session']

        memory = client.get('/broker/admin/memory/search', headers=_headers(workspace='research', environment='prod'), params={'q': 'memory', 'limit': 10})
        assert memory.status_code == 200, memory.text
        items = memory.json()['items']
        assert len(items) == 1
        assert items[0]['workspace_id'] == 'research'
        assert items[0]['text'] == 'research memory'


def test_broker_chat_rejects_cross_scope_session_id(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    with TestClient(app) as client:
        gw = app.state.gw
        gw.audit.get_or_create_session('broker', 'user:alice', 'shared-session', tenant_id='acme', workspace_id='research', environment='prod')
        response = client.post(
            '/broker/chat',
            headers={**_headers(workspace='ops', environment='staging'), 'X-CSRF-Token': 'unused'},
            json={'message': 'hola', 'session_id': 'shared-session', 'user_id': 'user:bob'},
        )
        assert response.status_code == 409, response.text
        assert 'scope mismatch' in response.text
