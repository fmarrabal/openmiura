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
    # Extended thinking is off by default — the factory passes 0.
    assert created['thinking_budget_tokens'] == 0
    assert rt.generate_reply('default', 's1', 'hola') == 'claude'


def test_agent_runtime_passes_thinking_budget_to_anthropic(monkeypatch):
    """The factory must forward LLMSettings.thinking_budget_tokens
    to the Anthropic client (H3.4/H3.8 was unreachable from config
    until this wiring existed)."""
    from openmiura.core import agent_runtime as ar
    created = {}

    class FakeClient:
        def __init__(self, **kwargs):
            created.update(kwargs)
            self.model = kwargs.get('model')

        def chat(self, messages, *, tools=None):
            return SimpleNamespace(content='claude', tool_calls=[], usage=None)

    monkeypatch.setattr(ar, 'AnthropicClient', FakeClient)
    llm = LLMSettings(
        provider='anthropic', model='claude-sonnet',
        base_url='https://api.anthropic.com/v1', timeout_s=30,
        api_key_env_var='ANTHROPIC_API_KEY',
        max_output_tokens=4096, thinking_budget_tokens=2048,
    )
    settings = _settings('anthropic')
    settings = Settings(
        server=settings.server, storage=settings.storage, llm=llm,
        runtime=settings.runtime, agents=settings.agents,
        memory=settings.memory, tools=settings.tools,
        admin=settings.admin, mcp=settings.mcp,
    )
    audit = AuditStore(':memory:')
    audit.init_db()
    AgentRuntime(settings, audit)
    assert created['thinking_budget_tokens'] == 2048
    assert created['max_output_tokens'] == 4096


def test_load_settings_parses_thinking_budget_tokens(tmp_path):
    """The yaml loader must surface llm.thinking_budget_tokens
    (default 0 when absent)."""
    import yaml
    from openmiura.core.config import load_settings

    cfg = {
        'server':  {'host': '127.0.0.1', 'port': 8081},
        'storage': {'db_path': ':memory:'},
        'llm': {
            'provider': 'anthropic',
            'model': 'claude-sonnet',
            'max_output_tokens': 4096,
            'thinking_budget_tokens': 2048,
        },
    }
    p = tmp_path / 'cfg.yaml'
    p.write_text(yaml.safe_dump(cfg), encoding='utf-8')
    settings = load_settings(str(p))
    assert settings.llm.thinking_budget_tokens == 2048

    cfg['llm'].pop('thinking_budget_tokens')
    p2 = tmp_path / 'cfg2.yaml'
    p2.write_text(yaml.safe_dump(cfg), encoding='utf-8')
    settings2 = load_settings(str(p2))
    assert settings2.llm.thinking_budget_tokens == 0
