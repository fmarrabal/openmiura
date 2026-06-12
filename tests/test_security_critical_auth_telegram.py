"""Regression tests for two critical findings closed together.

A. /broker/auth privilege escalation — the previously-unwired
   ``validate_role_assignment`` guard is now enforced on user and token
   creation, and the ``ensure_auth_user`` upsert can no longer be used to
   clobber a higher-privileged account.

B. Telegram webhook fail-open — the webhook now refuses anonymous POSTs
   when no shared secret is configured, and compares the secret in
   constant time.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

import app as app_module
from openmiura.gateway import Gateway


# ==================================================================
# A. /broker/auth privilege escalation
# ==================================================================


def _write_config(path: Path) -> None:
    db_path = (path.parent / "audit.db").as_posix()
    sandbox_dir = (path.parent / "sandbox").as_posix()
    path.write_text(
        f"""\
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
          svc_admin: admin
        user_key_roles:
          "user:ghost_admin": admin
      workspaces:
        research:
          display_name: "Research"
          environments: [dev, prod]
          default_environment: "prod"
        ops:
          display_name: "Operations"
          environments: [staging, prod]
          default_environment: "staging"
""",
        encoding="utf-8",
    )


def _login(client: TestClient, username: str, password: str) -> str:
    response = client.post("/broker/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["token"]


def _setup(tmp_path: Path):
    cfg = tmp_path / "openmiura.yaml"
    _write_config(cfg)
    app = app_module.create_app(config_path=str(cfg), gateway_factory=Gateway.from_config)
    return app


def test_auth_manager_cannot_assign_admin_role(tmp_path: Path) -> None:
    app = _setup(tmp_path)
    with TestClient(app) as client:
        gw = app.state.gw
        # tina maps to tenant_admin (has auth.manage within acme).
        gw.audit.ensure_auth_user(username="tina", password="pw1", user_key="user:tina", role="user", tenant_id="acme", workspace_id=None)
        token = _login(client, "tina", "pw1")
        headers = {"Authorization": f"Bearer {token}", "X-Tenant-Id": "acme", "X-Workspace-Id": "research"}

        resp = client.post(
            "/broker/auth/users",
            headers=headers,
            json={"username": "mallory", "password": "pw", "role": "admin", "tenant_id": "acme", "workspace_id": "research"},
        )
        assert resp.status_code == 403, resp.text


def test_auth_manager_cannot_clobber_existing_admin(tmp_path: Path) -> None:
    app = _setup(tmp_path)
    with TestClient(app) as client:
        gw = app.state.gw
        gw.audit.ensure_auth_user(username="tina", password="pw1", user_key="user:tina", role="user", tenant_id="acme", workspace_id=None)
        # A pre-existing admin in the same tenant.
        gw.audit.ensure_auth_user(username="victim_admin", password="pw2", user_key="user:victim_admin", role="admin", tenant_id="acme", workspace_id="research")
        token = _login(client, "tina", "pw1")
        headers = {"Authorization": f"Bearer {token}", "X-Tenant-Id": "acme", "X-Workspace-Id": "research"}

        # Attempt to overwrite the admin's row (downgrade role + reset password).
        resp = client.post(
            "/broker/auth/users",
            headers=headers,
            json={"username": "victim_admin", "password": "pw3", "role": "operator", "tenant_id": "acme", "workspace_id": "research"},
        )
        assert resp.status_code == 403, resp.text
        # The admin's password is unchanged: the original still authenticates.
        assert _login(client, "victim_admin", "pw2")


def test_auth_manager_cannot_mint_token_for_admin(tmp_path: Path) -> None:
    app = _setup(tmp_path)
    with TestClient(app) as client:
        gw = app.state.gw
        gw.audit.ensure_auth_user(username="tina", password="pw1", user_key="user:tina", role="user", tenant_id="acme", workspace_id=None)
        gw.audit.ensure_auth_user(username="victim_admin", password="pw2", user_key="user:victim_admin", role="admin", tenant_id="acme", workspace_id="research")
        token = _login(client, "tina", "pw1")
        headers = {"Authorization": f"Bearer {token}", "X-Tenant-Id": "acme", "X-Workspace-Id": "research"}

        resp = client.post(
            "/broker/auth/tokens",
            headers=headers,
            json={"user_key": "user:victim_admin", "label": "impersonation", "tenant_id": "acme", "workspace_id": "research"},
        )
        assert resp.status_code == 403, resp.text


def test_auth_manager_cannot_mint_token_for_config_elevated_identity(tmp_path: Path) -> None:
    """The decisive gap: a user_key elevated to admin purely by config
    (user_key_roles, no auth_users row) must still be protected. The guard
    has to resolve the EFFECTIVE role, not just look for a DB row."""
    app = _setup(tmp_path)
    with TestClient(app) as client:
        gw = app.state.gw
        gw.audit.ensure_auth_user(username="tina", password="pw1", user_key="user:tina", role="user", tenant_id="acme", workspace_id=None)
        token = _login(client, "tina", "pw1")
        headers = {"Authorization": f"Bearer {token}", "X-Tenant-Id": "acme", "X-Workspace-Id": "research"}

        resp = client.post(
            "/broker/auth/tokens",
            headers=headers,
            json={"user_key": "user:ghost_admin", "label": "config-impersonation", "tenant_id": "acme", "workspace_id": "research"},
        )
        assert resp.status_code == 403, resp.text


def test_auth_manager_cannot_create_config_mapped_admin_username(tmp_path: Path) -> None:
    """username_roles maps 'svc_admin' -> admin, so creating that username —
    even requesting role='user' — must be rejected, because at use time the
    account resolves to admin."""
    app = _setup(tmp_path)
    with TestClient(app) as client:
        gw = app.state.gw
        gw.audit.ensure_auth_user(username="tina", password="pw1", user_key="user:tina", role="user", tenant_id="acme", workspace_id=None)
        token = _login(client, "tina", "pw1")
        headers = {"Authorization": f"Bearer {token}", "X-Tenant-Id": "acme", "X-Workspace-Id": "research"}

        resp = client.post(
            "/broker/auth/users",
            headers=headers,
            json={"username": "svc_admin", "password": "pw", "role": "user", "tenant_id": "acme", "workspace_id": "research"},
        )
        assert resp.status_code == 403, resp.text


def test_legitimate_user_creation_still_works(tmp_path: Path) -> None:
    """Regression: the new guards must not block a tenant_admin creating an
    ordinary user within their own tenant."""
    app = _setup(tmp_path)
    with TestClient(app) as client:
        gw = app.state.gw
        gw.audit.ensure_auth_user(username="tina", password="pw1", user_key="user:tina", role="user", tenant_id="acme", workspace_id=None)
        token = _login(client, "tina", "pw1")
        headers = {"Authorization": f"Bearer {token}", "X-Tenant-Id": "acme", "X-Workspace-Id": "research"}

        resp = client.post(
            "/broker/auth/users",
            headers=headers,
            json={"username": "newbie", "password": "pw", "role": "user", "tenant_id": "acme", "workspace_id": "research"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["user"]["username"] == "newbie"


def test_admin_can_still_assign_admin(tmp_path: Path) -> None:
    """Regression: the broker-token admin retains full authority."""
    app = _setup(tmp_path)
    with TestClient(app) as client:
        resp = client.post(
            "/broker/auth/users",
            headers={"Authorization": "Bearer broker-secret"},
            json={"username": "ops_admin", "password": "pw", "role": "admin", "tenant_id": "acme", "workspace_id": "research"},
        )
        assert resp.status_code == 200, resp.text


# ==================================================================
# B. Telegram webhook fail-closed
# ==================================================================


class _FakeTelegramClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def send_message_chunked(self, *, chat_id, text, reply_to_message_id=None) -> None:
        self.calls.append({"chat_id": chat_id, "text": text})


class _FakeGateway:
    def __init__(self, *, secret: str) -> None:
        self.settings = SimpleNamespace(telegram=SimpleNamespace(webhook_secret=secret, allowlist=SimpleNamespace(deny_message="no")))
        self.telegram = _FakeTelegramClient()

    def is_telegram_allowed(self, chat_id, from_id) -> bool:
        return True

    def telegram_deny_message(self) -> str:
        return "no"


def _payload() -> dict:
    return {"message": {"message_id": 1, "text": "hi", "chat": {"id": 1}, "from": {"id": 2}}}


def test_telegram_webhook_without_secret_fails_closed() -> None:
    gw = _FakeGateway(secret="")
    app = app_module.create_app(gateway_factory=lambda _c: gw)
    with TestClient(app) as client:
        resp = client.post("/telegram/webhook", json=_payload())
    # No anonymous processing: the agent must never run.
    assert resp.status_code == 401, resp.text
    assert gw.telegram.calls == []


def test_telegram_webhook_wrong_secret_rejected_before_processing() -> None:
    gw = _FakeGateway(secret="tg-secret")
    app = app_module.create_app(gateway_factory=lambda _c: gw)
    with TestClient(app) as client:
        bad = client.post("/telegram/webhook", headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"}, json=_payload())
    assert bad.status_code == 401
    assert gw.telegram.calls == []
    # (The valid-secret happy path is covered end-to-end by
    # tests/test_telegram_integration.py.)
