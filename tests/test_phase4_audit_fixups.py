from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

import app as app_module
from openmiura.core.audit import AuditStore
from openmiura.core.policy import PolicyEngine


MIN_CONFIG = """\
server:
  host: "127.0.0.1"
  port: 8081
storage:
  db_path: ":memory:"
memory:
  enabled: false
tools:
  sandbox_dir: "data/sandbox"
broker:
  enabled: false
mcp:
  enabled: false
agents:
  default:
    system_prompt: "base"
"""


class _MinimalGateway:
    def __init__(self):
        self.settings = SimpleNamespace(runtime=SimpleNamespace(confirmation_cleanup_interval_s=60))
        self.audit = None

    def cleanup_expired_tool_confirmations(self):
        return 0


def test_create_app_initializes_gateway_once(tmp_path: Path):
    cfg = tmp_path / "openmiura.yaml"
    cfg.write_text(MIN_CONFIG, encoding="utf-8")

    calls: list[str | None] = []

    def _factory(config_path: str | None):
        calls.append(config_path)
        return _MinimalGateway()

    app = app_module.create_app(config_path=str(cfg), gateway_factory=_factory)
    assert calls == []

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert calls == [str(cfg)]


def test_compliance_summary_filters_old_sessions_and_tool_calls(tmp_path: Path):
    audit = AuditStore(":memory:")
    audit.init_db()
    now = time.time()
    old_ts = now - 10 * 24 * 3600

    recent_session = audit.get_or_create_session("http", "user:recent", "sess-recent", tenant_id="t1", workspace_id="w1", environment="prod")
    old_session = audit.get_or_create_session("http", "user:old", "sess-old", tenant_id="t1", workspace_id="w1", environment="prod")

    audit.log_tool_call(
        session_id=recent_session,
        user_key="user:recent",
        agent_id="default",
        tool_name="web_fetch",
        args_json='{}',
        ok=True,
        result_excerpt="ok",
        error="",
        duration_ms=5.0,
        tenant_id="t1",
        workspace_id="w1",
        environment="prod",
    )
    audit.log_tool_call(
        session_id=old_session,
        user_key="user:old",
        agent_id="default",
        tool_name="web_fetch",
        args_json='{}',
        ok=True,
        result_excerpt="ok",
        error="",
        duration_ms=5.0,
        tenant_id="t1",
        workspace_id="w1",
        environment="prod",
    )

    cur = audit._conn.cursor()
    cur.execute("UPDATE sessions SET updated_at=?, created_at=? WHERE session_id=?", (old_ts, old_ts, old_session))
    cur.execute("UPDATE tool_calls SET ts=? WHERE session_id=? AND user_key=?", (old_ts, old_session, "user:old"))
    audit._conn.commit()

    gw = SimpleNamespace(
        audit=audit,
        policy=None,
        sandbox=SimpleNamespace(profiles_catalog=lambda: {"local-safe": {}}),
        secret_broker=SimpleNamespace(is_enabled=lambda: True),
    )

    # Keep the test independent from routing; instantiate the service directly.
    from openmiura.application.admin.service import AdminService

    payload = AdminService().compliance_summary(
        gw,
        tenant_id="t1",
        workspace_id="w1",
        environment="prod",
        window_hours=24,
        limit_per_section=10,
    )

    assert payload["counts"]["tool_calls"] == 1
    assert payload["counts"]["sessions"] == 1
    assert payload["recent"]["tool_calls"][0]["user_key"] == "user:recent"
    assert payload["recent"]["sessions"][0]["user_id"] == "user:recent"


POLICIES_YAML = """\
defaults:
  tools: true
  memory: true
  secrets: true
secret_rules:
  - name: deny_terminal_secret
    ref: github_pat
    tool: terminal_exec
    effect: deny
    reason: terminal cannot resolve github secrets
  - name: allow_web_fetch_secret
    ref: github_pat
    tool: web_fetch
    effect: allow
"""


def test_policy_explain_request_uses_explicit_tool_name_for_secret_scope(tmp_path: Path):
    p = tmp_path / "policies.yaml"
    p.write_text(POLICIES_YAML, encoding="utf-8")
    pe = PolicyEngine(str(p))

    explained = pe.explain_request(
        scope="secret",
        resource_name="github_pat",
        agent_name="researcher",
        tool_name="web_fetch",
        user_role="admin",
    )

    assert explained["decision"]["allowed"] is True
    assert explained["context"]["tool_name"] == "web_fetch"
