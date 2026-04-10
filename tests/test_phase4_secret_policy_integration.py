from __future__ import annotations

import pytest

from openmiura.core.config import SecretRefSettings, SecretsSettings
from openmiura.core.policy import PolicyEngine
from openmiura.core.secrets import SecretAccessDenied, SecretBroker


def test_secret_broker_applies_formal_policy_engine(tmp_path):
    policies = tmp_path / "policies.yaml"
    policies.write_text(
        """secret_rules:
  - name: deny_for_terminal
    ref: github_pat
    tool: terminal_exec
    effect: deny
    reason: terminal cannot use github token
""",
        encoding="utf-8",
    )
    broker = SecretBroker(
        settings=SecretsSettings(
            enabled=True,
            refs={
                "github_pat": SecretRefSettings(
                    ref="github_pat",
                    value="test_secret_value",
                    allowed_tools=["web_fetch", "terminal_exec"],
                    allowed_roles=["admin"],
                )
            },
        ),
        policy=PolicyEngine(str(policies)),
    )

    with pytest.raises(SecretAccessDenied, match="terminal cannot use github token"):
        broker.resolve("github_pat", tool_name="terminal_exec", user_role="admin")

    assert broker.resolve("github_pat", tool_name="web_fetch", user_role="admin") == "test_secret_value"
