from __future__ import annotations

from openmiura.core.audit import AuditStore
from openmiura.core.config import AdminSettings, LLMSettings, MCPSettings, MemorySettings, RuntimeSettings, ServerSettings, Settings, StorageSettings, ToolsSettings
from openmiura.core.policy import PolicyEngine
from openmiura.tools.runtime import ToolRegistry, ToolRuntime, ToolError
from openmiura.tools.terminal_exec import TerminalExecTool


def test_terminal_exec_not_allowed_when_agent_tools_omit_it(tmp_path):
    audit = AuditStore(':memory:')
    audit.init_db()
    settings = Settings(
        server=ServerSettings(),
        storage=StorageSettings(db_path=':memory:'),
        llm=LLMSettings(),
        runtime=RuntimeSettings(),
        agents={'default': {'name': 'default', 'tools': ['time_now']}},
        memory=MemorySettings(enabled=False),
        tools=ToolsSettings(sandbox_dir=str(tmp_path)),
        admin=AdminSettings(),
        mcp=MCPSettings(),
    )
    reg = ToolRegistry()
    reg.register(TerminalExecTool())
    runtime = ToolRuntime(settings=settings, audit=audit, memory=None, registry=reg, policy=None)
    try:
        runtime.run_tool(agent_id='default', session_id='s1', user_key='u1', tool_name='terminal_exec', args={'command': 'echo hi'})
        assert False, 'expected ToolError'
    except ToolError:
        pass
