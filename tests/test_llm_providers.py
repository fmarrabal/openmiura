from __future__ import annotations

from types import SimpleNamespace

from openmiura.core.agent_runtime import AgentRuntime
from openmiura.core.audit import AuditStore
from openmiura.core.config import (
    AdminSettings,
    LLMSettings,
    MCPSettings,
    MemorySettings,
    RuntimeSettings,
    ServerSettings,
    Settings,
    StorageSettings,
    ToolsSettings,
)


def _settings(provider: str, **kwargs):
    llm = LLMSettings(provider='ollama', model='qwen2.5:7b-instruct', base_url='http://127.0.0.1:11434', timeout_s=30)
    if provider == 'openai':
        llm = LLMSettings(provider='openai', model='gpt-4o-mini', base_url='https://api.openai.com/v1', timeout_s=30, api_key_env_var='OPENAI_API_KEY')
    elif provider == 'kimi':
        llm = LLMSettings(provider='kimi', model='kimi-k2.5', base_url='https://api.moonshot.ai/v1', timeout_s=30, api_key_env_var='OPENMIURA_KIMI_API_KEY')
    elif provider == 'anthropic':
        llm = LLMSettings(provider='anthropic', model='claude-sonnet', base_url='https://api.anthropic.com/v1', timeout_s=30, api_key_env_var='ANTHROPIC_API_KEY', anthropic_version='2023-06-01', max_output_tokens=1024)
    return Settings(
        server=ServerSettings(),
        storage=StorageSettings(db_path=':memory:'),
        llm=llm,
        runtime=RuntimeSettings(),
        agents={'default': {'name': 'default', 'system_prompt': 'test', 'tools': []}},
        memory=MemorySettings(enabled=False),
        tools=ToolsSettings(),
        admin=AdminSettings(),
        mcp=MCPSettings(),
    )


def test_agent_runtime_supports_openai_provider(monkeypatch):
    from openmiura.core import agent_runtime as ar
    created = {}

    class FakeClient:
        def __init__(self, **kwargs):
            created.update(kwargs)
            self.model = kwargs['model']

        def chat(self, messages, *, tools=None):
            return SimpleNamespace(content='ok', tool_calls=[], usage={'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2})

    monkeypatch.setattr(ar, 'OpenAICompatibleClient', FakeClient)
    audit = AuditStore(':memory:')
    audit.init_db()
    rt = AgentRuntime(_settings('openai'), audit)
    assert created['base_url'] == 'https://api.openai.com/v1'
    assert created['api_key_env_var'] == 'OPENAI_API_KEY'
    assert rt.generate_reply('default', 's1', 'hola') == 'ok'


def test_agent_runtime_supports_kimi_provider(monkeypatch):
    from openmiura.core import agent_runtime as ar
    created = {}

    class FakeClient:
        def __init__(self, **kwargs):
            created.update(kwargs)
            self.model = kwargs['model']

        def chat(self, messages, *, tools=None):
            return SimpleNamespace(content='kimi', tool_calls=[], usage=None)

    monkeypatch.setattr(ar, 'OpenAICompatibleClient', FakeClient)
    audit = AuditStore(':memory:')
    audit.init_db()
    rt = AgentRuntime(_settings('kimi'), audit)
    assert created['base_url'] == 'https://api.moonshot.ai/v1'
    assert created['api_key_env_var'] == 'OPENMIURA_KIMI_API_KEY'
    assert rt.generate_reply('default', 's1', 'hola') == 'kimi'


def test_agent_runtime_supports_anthropic_provider(monkeypatch):
    from openmiura.core import agent_runtime as ar
    created = {}

    class FakeClient:
        def __init__(self, **kwargs):
            created.update(kwargs)
            self.model = kwargs['model']

        def chat(self, messages, *, tools=None):
            return SimpleNamespace(content='claude', tool_calls=[], usage=None)

    monkeypatch.setattr(ar, 'AnthropicClient', FakeClient)
    audit = AuditStore(':memory:')
    audit.init_db()
    rt = AgentRuntime(_settings('anthropic'), audit)
    assert created['base_url'] == 'https://api.anthropic.com/v1'
    assert created['api_key_env_var'] == 'ANTHROPIC_API_KEY'
    assert rt.generate_reply('default', 's1', 'hola') == 'claude'
