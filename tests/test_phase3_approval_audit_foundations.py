from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from openmiura.interfaces.http import app as app_module
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
  history_limit: 4
memory:
  enabled: false
tools:
  sandbox_dir: "{sandbox_dir}"
broker:
  enabled: true
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
              opal: operator
              oscar: operator
              rita: reviewer
            role_inherits:
              reviewer: [viewer]
            permission_grants:
              reviewer: [approvals.read, approvals.write]
''',
        encoding='utf-8',
    )


def _login(client: TestClient, username: str, password: str) -> str:
    response = client.post('/broker/auth/login', json={'username': username, 'password': password})
    assert response.status_code == 200, response.text
    return response.json()['token']


def _headers(client: TestClient, username: str, password: str) -> dict[str, str]:
    return {'Authorization': f'Bearer {_login(client, username, password)}'}


def _create_waiting_workflow(client: TestClient, headers: dict[str, str]) -> tuple[str, str]:
    create = client.post(
        '/broker/workflows',
        headers=headers,
        json={
            'name': 'needs-approval',
            'definition': {
                'steps': [
                    {'id': 'approval', 'kind': 'approval', 'requested_role': 'operator'},
                    {'id': 'after', 'kind': 'note', 'note': 'done'},
                ]
            },
            'autorun': True,
        },
    )
    assert create.status_code == 200, create.text
    workflow_id = create.json()['workflow']['workflow_id']
    approvals = client.get('/broker/approvals?requested_role=operator', headers=headers)
    assert approvals.status_code == 200, approvals.text
    items = approvals.json()['items']
    assert items
    return workflow_id, items[0]['approval_id']


def test_requested_role_is_enforced_for_claim_and_decision(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    with TestClient(app) as client:
        gw = app.state.gw
        gw.audit.ensure_auth_user(username='alice', password='pw1', user_key='user:alice', role='user', tenant_id='acme', workspace_id='research')
        gw.audit.ensure_auth_user(username='rita', password='pw2', user_key='user:rita', role='user', tenant_id='acme', workspace_id='research')
        gw.audit.ensure_auth_user(username='opal', password='pw3', user_key='user:opal', role='user', tenant_id='acme', workspace_id='research')

        alice_headers = _headers(client, 'alice', 'pw1')
        rita_headers = _headers(client, 'rita', 'pw2')
        opal_headers = _headers(client, 'opal', 'pw3')

        _, approval_id = _create_waiting_workflow(client, alice_headers)

        denied_claim = client.post(f'/broker/approvals/{approval_id}/claim', headers=rita_headers)
        assert denied_claim.status_code == 403, denied_claim.text
        assert "requires role 'operator'" in (denied_claim.json().get('detail') or denied_claim.json().get('error') or '')

        denied_decision = client.post(
            f'/broker/approvals/{approval_id}/decision',
            headers=rita_headers,
            json={'decision': 'approve', 'reason': 'not enough authority'},
        )
        assert denied_decision.status_code == 403, denied_decision.text
        assert "requires role 'operator'" in (denied_decision.json().get('detail') or denied_decision.json().get('error') or '')

        allowed_claim = client.post(f'/broker/approvals/{approval_id}/claim', headers=opal_headers)
        assert allowed_claim.status_code == 200, allowed_claim.text
        allowed_decision = client.post(
            f'/broker/approvals/{approval_id}/decision',
            headers=opal_headers,
            json={'decision': 'approve', 'reason': 'operator approved'},
        )
        assert allowed_decision.status_code == 200, allowed_decision.text
        assert allowed_decision.json()['approval']['status'] == 'approved'


def test_requester_cannot_self_approve_and_evidence_is_available(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)

    with TestClient(app) as client:
        gw = app.state.gw
        gw.audit.ensure_auth_user(username='opal', password='pw1', user_key='user:opal', role='user', tenant_id='acme', workspace_id='research')
        gw.audit.ensure_auth_user(username='oscar', password='pw2', user_key='user:oscar', role='user', tenant_id='acme', workspace_id='research')

        opal_headers = _headers(client, 'opal', 'pw1')
        oscar_headers = _headers(client, 'oscar', 'pw2')

        workflow_id, approval_id = _create_waiting_workflow(client, opal_headers)

        self_claim = client.post(f'/broker/approvals/{approval_id}/claim', headers=opal_headers)
        assert self_claim.status_code == 403, self_claim.text
        assert 'own approval' in (self_claim.json().get('detail') or self_claim.json().get('error') or '')

        claim = client.post(f'/broker/approvals/{approval_id}/claim', headers=oscar_headers)
        assert claim.status_code == 200, claim.text
        decide = client.post(
            f'/broker/approvals/{approval_id}/decision',
            headers=oscar_headers,
            json={'decision': 'approve', 'reason': 'separation of duties'},
        )
        assert decide.status_code == 200, decide.text

        evidence = client.get(f'/broker/approvals/{approval_id}/evidence', headers=oscar_headers)
        assert evidence.status_code == 200, evidence.text
        payload = evidence.json()
        assert payload['approval']['approval_id'] == approval_id
        assert payload['evidence']['workflow_id'] == workflow_id
        assert payload['evidence']['requested_by'] == 'user:opal'
        assert payload['evidence']['decided_by'] == 'user:oscar'
        assert 'approval_requested' in payload['evidence']['timeline_events']
        assert 'approval_claimed' in payload['evidence']['timeline_events']
        assert 'approval_decided' in payload['evidence']['timeline_events']
        assert payload['evidence']['workflow_status'] == 'succeeded'
