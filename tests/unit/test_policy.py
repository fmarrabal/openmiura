from __future__ import annotations

from openmiura.core.policy import PolicyEngine


POLICIES_YAML = """agent_rules:
  - agent: researcher
    allow_tools: [web_fetch, time_now]
    deny_tools: [fs_write]
user_rules:
  - user: tg:123
    allow_agents: ['*']
  - user: tg:999
    deny_agents: [admin_agent]
tool_rules:
  - tool: fs_write
    requires_confirmation: true
  - tool: web_fetch
    requires_confirmation: false
"""


def test_policy_allow_deny_and_confirmation(tmp_path):
    p = tmp_path / "policies.yaml"
    p.write_text(POLICIES_YAML, encoding="utf-8")
    pe = PolicyEngine(str(p))

    assert pe.check_agent_access("tg:123", "researcher") is True
    assert pe.check_agent_access("tg:999", "admin_agent") is False

    ok = pe.check_tool_access("researcher", "web_fetch")
    assert ok.allowed is True
    assert ok.requires_confirmation is False

    denied = pe.check_tool_access("researcher", "fs_write")
    assert denied.allowed is False
    assert denied.requires_confirmation is True
    assert "denied" in denied.reason


def test_policy_edge_case_unspecified_tool_is_blocked_by_allowlist(tmp_path):
    p = tmp_path / "policies.yaml"
    p.write_text(POLICIES_YAML, encoding="utf-8")
    pe = PolicyEngine(str(p))

    unknown = pe.check_tool_access("researcher", "fs_read")
    assert unknown.allowed is False
    assert unknown.requires_confirmation is False
    assert "not allowed" in unknown.reason
