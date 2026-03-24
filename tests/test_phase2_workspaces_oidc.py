from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

import app as app_module
from openmiura.application.auth.oidc_service import OIDCService
from openmiura.core.config import load_settings
from openmiura.gateway import Gateway


def _write_workspace_cfg(path: Path) -> None:
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
  model: "base-model"
runtime:
  history_limit: 6
memory:
  enabled: false
tools:
  sandbox_dir: "{sandbox_dir}"
  terminal:
    enabled: true
    timeout_s: 60
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
      settings_overrides:
        llm:
          model: "tenant-model"
        tools:
          terminal:
            timeout_s: 20
      workspaces:
        research:
          display_name: "Research"
          settings_overrides:
            tools:
              terminal:
                enabled: false
          environment_settings:
            dev:
              display_name: "Development"
              settings_overrides:
                llm:
                  model: "dev-model"
                memory:
                  enabled: true
          environments: [dev, prod]
          default_environment: "prod"
''',
        encoding='utf-8',
    )


def _write_oidc_cfg(path: Path) -> None:
    db_path = (path.parent / 'audit.db').as_posix()
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
broker:
  enabled: true
  token: ""
auth:
  enabled: true
  session_cookie_enabled: true
  oidc:
    enabled: true
    client_id: "client-123"
    client_secret: "top-secret"
    authorize_url: "https://issuer.example/authorize"
    token_url: "https://issuer.example/token"
    userinfo_url: "https://issuer.example/userinfo"
    scopes: [openid, profile, email]
    allowed_email_domains: [acme.com]
    group_role_mapping:
      miura-ops: operator
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
''',
        encoding='utf-8',
    )


def test_workspace_effective_config_inherits_and_overrides(tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_workspace_cfg(cfg)
    settings = load_settings(str(cfg))
    assert settings.tenancy is not None
    assert settings.tenancy.tenants['acme'].settings_overrides['llm']['model'] == 'tenant-model'
    assert settings.tenancy.tenants['acme'].workspaces['research'].environment_settings['dev'].settings_overrides['llm']['model'] == 'dev-model'

    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    with TestClient(app) as client:
        response = client.get(
            '/broker/admin/tenancy/effective-config',
            params={'tenant_id': 'acme', 'workspace_id': 'research', 'environment': 'dev'},
            headers={'Authorization': 'Bearer broker-secret'},
        )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload['scope'] == {'tenant_id': 'acme', 'workspace_id': 'research', 'environment': 'dev'}
    assert payload['effective']['llm']['model'] == 'dev-model'
    assert payload['effective']['tools']['terminal']['timeout_s'] == 20
    assert payload['effective']['tools']['terminal']['enabled'] is False
    assert payload['effective']['memory']['enabled'] is True


def test_oidc_login_callback_provisions_session_and_scope(monkeypatch, tmp_path: Path) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    _write_oidc_cfg(cfg)

    monkeypatch.setattr(
        OIDCService,
        'provider_metadata',
        lambda self, oidc_cfg: {
            'issuer': 'https://issuer.example',
            'authorization_endpoint': 'https://issuer.example/authorize',
            'token_endpoint': 'https://issuer.example/token',
            'userinfo_endpoint': 'https://issuer.example/userinfo',
        },
    )
    monkeypatch.setattr(
        OIDCService,
        'exchange_code_for_tokens',
        lambda self, metadata, oidc_cfg, *, code, redirect_uri, code_verifier='': {
            'access_token': 'access-123',
            'claims': {'sub': 'sub-001'},
        },
    )
    monkeypatch.setattr(
        OIDCService,
        'fetch_userinfo',
        lambda self, metadata, access_token: {
            'sub': 'sub-001',
            'email': 'alice@acme.com',
            'preferred_username': 'alice',
            'groups': ['miura-ops'],
            'tenant_id': 'acme',
            'workspace_id': 'research',
            'environment': 'prod',
        },
    )

    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    with TestClient(app) as client:
        start = client.get('/broker/auth/oidc/login')
        assert start.status_code == 200, start.text
        start_payload = start.json()
        qs = parse_qs(urlparse(start_payload['authorize_url']).query)
        assert qs['client_id'] == ['client-123']
        state = start_payload['state']

        callback = client.get('/broker/auth/oidc/callback', params={'code': 'code-123', 'state': state})
        assert callback.status_code == 200, callback.text
        body = callback.json()
        assert body['user']['username'] == 'alice'
        assert body['user']['user_key'] == 'oidc:sub-001'
        assert body['user']['role'] == 'operator'
        assert body['scope'] == {'tenant_id': 'acme', 'workspace_id': 'research', 'environment': 'prod'}
        assert 'workspace.read' in body['permissions']

        me = client.get('/broker/auth/me', headers={'Authorization': f'Bearer {body["token"]}'})
        assert me.status_code == 200, me.text
        me_payload = me.json()
        assert me_payload['username'] == 'alice'
        assert me_payload['role'] == 'operator'
        assert me_payload['tenant_id'] == 'acme'
        assert me_payload['workspace_id'] == 'research'
        assert me_payload['environment'] == 'prod'
        assert me_payload['oidc']['enabled'] is True
