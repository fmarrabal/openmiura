from __future__ import annotations

from openmiura.core.policy import PolicyEngine


POLICIES_YAML = """defaults:
  tools: true
  memory: true
  secrets: true
  channels: true
agent_rules:
  - agent: researcher
    allow_tools: [web_fetch, time_now]
tool_rules:
  - name: deny_terminal_for_user
    tool: terminal_exec
    user_role: user
    effect: deny
    reason: terminal blocked for user
  - name: confirm_web_fetch_prod
    tool: web_fetch
    tenant_id: acme
    workspace_id: research
    environment: prod
    effect: allow
    requires_confirmation: true
memory_rules:
  - name: deny_memory_delete_user
    action: delete
    user_role: user
    effect: deny
    reason: memory deletion reserved to admins
secret_rules:
  - name: deny_terminal_secret
    ref: github_pat
    tool: terminal_exec
    effect: deny
    reason: terminal cannot resolve github secrets
  - name: allow_web_fetch_secret
    ref: github_pat
    tool: web_fetch
    tenant_id: acme
    effect: allow
channel_rules:
  - name: deny_discord_prod
    channel: discord
    environment: prod
    effect: deny
    reason: discord disabled in prod
approval_rules:
  - name: require_fs_write_admin_approval
    action_name: fs_write
    effect: require_approval
    reason: write operations require approval
"""


def test_unified_policy_engine_evaluates_tool_memory_secret_channel_and_approval(tmp_path):
    p = tmp_path / "policies.yaml"
    p.write_text(POLICIES_YAML, encoding="utf-8")
    pe = PolicyEngine(str(p))

    web_fetch = pe.check_tool_access(
        "researcher",
        "web_fetch",
        user_role="user",
        tenant_id="acme",
        workspace_id="research",
        environment="prod",
    )
    assert web_fetch.allowed is True
    assert web_fetch.requires_confirmation is True
    assert "confirm_web_fetch_prod" in web_fetch.matched_rules

    terminal = pe.check_tool_access("researcher", "terminal_exec", user_role="user")
    assert terminal.allowed is False
    assert "terminal blocked for user" in terminal.reason

    memory_delete = pe.check_memory_access("delete", kind="tool_result", user_role="user")
    assert memory_delete.allowed is False
    assert "reserved to admins" in memory_delete.reason

    secret_terminal = pe.check_secret_access("github_pat", tool_name="terminal_exec", user_role="admin")
    assert secret_terminal.allowed is False

    secret_web_fetch = pe.check_secret_access("github_pat", tool_name="web_fetch", user_role="admin", tenant_id="acme")
    assert secret_web_fetch.allowed is True

    discord_prod = pe.check_channel_access("discord", environment="prod")
    assert discord_prod.allowed is False

    approval = pe.check_approval_requirement("fs_write", user_role="operator")
    assert approval.requires_approval is True
    assert "approval" in approval.reason


def test_policy_explain_request_returns_traces(tmp_path):
    p = tmp_path / "policies.yaml"
    p.write_text(POLICIES_YAML, encoding="utf-8")
    pe = PolicyEngine(str(p))

    explained = pe.explain_request(
        scope="tool",
        resource_name="web_fetch",
        agent_name="researcher",
        user_role="user",
        tenant_id="acme",
        workspace_id="research",
        environment="prod",
    )

    assert explained["ok"] is True
    assert explained["decision"]["allowed"] is True
    assert explained["decision"]["requires_confirmation"] is True
    names = [item["name"] for item in explained["decision"]["explanation"]]
    assert "confirm_web_fetch_prod" in names
