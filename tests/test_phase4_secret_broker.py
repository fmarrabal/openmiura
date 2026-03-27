from __future__ import annotations

from pathlib import Path

import pytest

from openmiura.core.audit import AuditStore
from openmiura.core.config import (
    AdminSettings,
    BrokerSettings,
    LLMSettings,
    MCPSettings,
    MemorySettings,
    RuntimeSettings,
    SecretRefSettings,
    SecretsSettings,
    ServerSettings,
    Settings,
    StorageSettings,
    ToolsSettings,
    load_settings,
)
from openmiura.core.secrets import SecretAccessDenied, SecretBroker
from openmiura.tools.runtime import Tool, ToolRegistry, ToolRuntime


class _EchoSecretTool(Tool):
    name = 'echo_secret'
    description = 'Resolve a secret ref and echo a redacted trace.'
    parameters_schema = {
        'type': 'object',
        'properties': {
            'secret_ref': {'type': 'string'},
            'literal': {'type': 'string'},
            'domain': {'type': 'string'},
        },
        'required': ['secret_ref'],
        'additionalProperties': False,
    }

    def run(self, ctx, **kwargs) -> str:
        secret = ctx.resolve_secret(kwargs['secret_ref'], tool_name=self.name, domain=kwargs.get('domain'))
        literal = str(kwargs.get('literal') or '')
        return f"resolved={secret}; literal={literal}"


def _base_settings(tmp_path: Path) -> Settings:
    return Settings(
        server=ServerSettings(),
        storage=StorageSettings(db_path=':memory:'),
        llm=LLMSettings(),
        runtime=RuntimeSettings(),
        agents={'default': {'allowed_tools': ['echo_secret'], 'system_prompt': 'base'}},
        memory=MemorySettings(enabled=False),
        tools=ToolsSettings(sandbox_dir=str(tmp_path)),
        admin=AdminSettings(),
        mcp=MCPSettings(),
        broker=BrokerSettings(),
    )


def test_load_settings_parses_secret_broker_refs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = tmp_path / 'openmiura.yaml'
    cfg.write_text(
        '''
server:
  host: 127.0.0.1
  port: 8081
storage:
  db_path: data/audit.db
llm:
  provider: ollama
  base_url: http://127.0.0.1:11434
  model: qwen
runtime: {}
memory:
  enabled: false
tools:
  sandbox_dir: data/sandbox
secrets:
  enabled: true
  redact_logs: true
  refs:
    github_pat:
      value_env_var: OPENMIURA_GITHUB_PAT
      description: GitHub token
      allowed_tools: [web_fetch]
      allowed_roles: [admin]
      allowed_tenants: [acme]
      allowed_domains: [api.github.com]
''',
        encoding='utf-8',
    )
    monkeypatch.setenv('OPENMIURA_GITHUB_PAT', 'synthetic_test_token')

    settings = load_settings(str(cfg))

    assert settings.secrets is not None
    assert settings.secrets.enabled is True
    ref = settings.secrets.refs['github_pat']
    assert ref.value == 'synthetic_test_token'
    assert ref.allowed_tools == ['web_fetch']
    assert ref.allowed_roles == ['admin']
    assert ref.allowed_tenants == ['acme']
    assert ref.allowed_domains == ['api.github.com']


def test_secret_broker_enforces_scope_and_audits(audit_store: AuditStore) -> None:
    broker = SecretBroker(
        settings=SecretsSettings(
            enabled=True,
            refs={
                'github_pat': SecretRefSettings(
                    ref='github_pat',
                    value='synthetic_test_token',
                    allowed_tools=['web_fetch'],
                    allowed_roles=['admin'],
                    allowed_tenants=['acme'],
                    allowed_workspaces=['research'],
                    allowed_environments=['prod'],
                    allowed_domains=['api.github.com'],
                )
            },
        ),
        audit=audit_store,
    )

    value = broker.resolve(
        'github_pat',
        tool_name='web_fetch',
        user_role='admin',
        user_key='user:admin',
        session_id='sess-1',
        tenant_id='acme',
        workspace_id='research',
        environment='prod',
        domain='https://api.github.com/repos/openai/openai-python',
    )
    assert value == 'synthetic_test_token'

    events = audit_store.get_recent_events(limit=5, channel='security')
    assert events
    payload = events[0]['payload']
    assert payload['event'] == 'secret_resolved'
    assert payload['ref'] == 'github_pat'
    assert payload['tool_name'] == 'web_fetch'
    assert payload['domain'] == 'api.github.com'

    with pytest.raises(SecretAccessDenied):
        broker.resolve(
            'github_pat',
            tool_name='terminal_exec',
            user_role='admin',
            tenant_id='acme',
            workspace_id='research',
            environment='prod',
            domain='api.github.com',
        )
    with pytest.raises(SecretAccessDenied):
        broker.resolve(
            'github_pat',
            tool_name='web_fetch',
            user_role='user',
            tenant_id='acme',
            workspace_id='research',
            environment='prod',
            domain='api.github.com',
        )
    with pytest.raises(SecretAccessDenied):
        broker.resolve(
            'github_pat',
            tool_name='web_fetch',
            user_role='admin',
            tenant_id='acme',
            workspace_id='research',
            environment='prod',
            domain='example.com',
        )


def test_tool_runtime_redacts_secret_values_in_output_and_audit(tmp_path: Path) -> None:
    audit = AuditStore(':memory:')
    audit.init_db()
    audit.ensure_auth_user(username='admin', password='pw', user_key='user:admin', role='admin')

    broker = SecretBroker(
        settings=SecretsSettings(
            enabled=True,
            refs={
                'service_token': SecretRefSettings(
                    ref='service_token',
                    value='real-token-123',
                    allowed_tools=['echo_secret'],
                    allowed_roles=['admin'],
                    allowed_domains=['api.example.com'],
                )
            },
        ),
        audit=audit,
    )
    registry = ToolRegistry()
    registry.register(_EchoSecretTool())
    runtime = ToolRuntime(
        settings=_base_settings(tmp_path),
        audit=audit,
        memory=None,
        registry=registry,
        secret_broker=broker,
    )

    out = runtime.run_tool(
        agent_id='default',
        session_id='sess-1',
        user_key='user:admin',
        tool_name='echo_secret',
        args={
            'secret_ref': 'service_token',
            'literal': 'real-token-123',
            'domain': 'https://api.example.com/v1/items',
        },
    )

    assert 'real-token-123' not in out
    assert '[secret:redacted:service_token]' in out

    calls = audit.list_tool_calls(limit=5, tool_name='echo_secret')
    assert len(calls) == 1
    call = calls[0]
    assert 'real-token-123' not in str(call)
    assert '[secret:redacted:service_token]' in call['result_excerpt']
    assert call['args']['literal'] == '[secret:redacted:service_token]'

    security_events = audit.get_recent_events(limit=5, channel='security')
    assert any(evt['payload'].get('ref') == 'service_token' for evt in security_events)
