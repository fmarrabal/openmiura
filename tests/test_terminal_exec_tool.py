from __future__ import annotations

import json
import sys
from pathlib import Path

from openmiura.core.audit import AuditStore
from openmiura.core.config import AdminSettings, LLMSettings, MCPSettings, MemorySettings, RuntimeSettings, ServerSettings, Settings, StorageSettings, ToolsSettings
from openmiura.tools.runtime import ToolContext
from openmiura.tools.terminal_exec import TerminalExecTool


def _ctx(tmp_path: Path):
    settings = Settings(
        server=ServerSettings(),
        storage=StorageSettings(db_path=':memory:'),
        llm=LLMSettings(),
        runtime=RuntimeSettings(),
        agents={},
        memory=MemorySettings(enabled=False),
        tools=ToolsSettings(sandbox_dir=str(tmp_path)),
        admin=AdminSettings(),
        mcp=MCPSettings(),
    )
    return ToolContext(settings=settings, audit=AuditStore(':memory:'), memory=None, sandbox_dir=tmp_path)


def test_terminal_exec_runs_command(tmp_path: Path):
    ctx = _ctx(tmp_path)
    tool = TerminalExecTool()
    cmd = f'"{sys.executable}" -c "print(123)"'
    result = tool.run(ctx, command=cmd)
    payload = json.loads(result)
    assert payload['exit_code'] == 0
    assert '123' in payload['stdout']


def test_terminal_exec_uses_sandbox_cwd(tmp_path: Path):
    work = tmp_path / 'work'
    work.mkdir()
    ctx = _ctx(tmp_path)
    tool = TerminalExecTool()
    cmd = f'"{sys.executable}" -c "import pathlib; print(pathlib.Path().resolve().name)"'
    result = tool.run(ctx, command=cmd, cwd='work')
    payload = json.loads(result)
    assert payload['exit_code'] == 0
    assert payload['cwd'].endswith('work')
