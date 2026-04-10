from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from openmiura.core.agent_runtime import AgentRuntime
from openmiura.core.llm.ollama import ChatResponse, ToolCall


class _FakeAudit:
    def get_recent_messages(self, session_id: str, limit: int):
        return []


class _FakeTools:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def available_tool_schemas(self, agent_id: str):
        return [
            {
                "type": "function",
                "function": {
                    "name": "time_now",
                    "description": "Return current time",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]

    def run_tool(self, *, agent_id: str, session_id: str, user_key: str, tool_name: str, args: dict):
        self.calls.append(
            {
                "agent_id": agent_id,
                "session_id": session_id,
                "user_key": user_key,
                "tool_name": tool_name,
                "args": args,
            }
        )
        return "2026-03-15T10:00:00+01:00"


class _FakeLLM:
    def __init__(self) -> None:
        self.calls = 0
        self.last_messages = None

    def chat(self, messages, *, tools=None):
        self.calls += 1
        self.last_messages = messages
        if self.calls == 1:
            assert tools and tools[0]["function"]["name"] == "time_now"
            return ChatResponse(
                content="",
                tool_calls=[ToolCall(name="time_now", arguments={})],
            )
        assert any(m.get("role") == "tool" for m in messages)
        return ChatResponse(content="Son las 10:00 en Madrid.", tool_calls=[])


def _settings():
    return SimpleNamespace(
        llm=SimpleNamespace(provider="ollama", base_url="http://127.0.0.1:11434", model="qwen", timeout_s=30),
        runtime=SimpleNamespace(history_limit=6),
        agents={
            "default": {
                "system_prompt": "You are openMiura.",
                "allowed_tools": ["time_now"],
            }
        },
    )


def test_agent_runtime_executes_tool_calls_and_returns_final_text(monkeypatch) -> None:
    runtime = AgentRuntime(settings=_settings(), audit=_FakeAudit())
    runtime.llm = _FakeLLM()
    tools = _FakeTools()

    out = runtime.generate_reply(
        agent_id="default",
        session_id="s1",
        user_text="¿Qué hora es?",
        extra_system="",
        tools_runtime=tools,
        user_key="u1",
    )

    assert out == "Son las 10:00 en Madrid."
    assert tools.calls == [
        {
            "agent_id": "default",
            "session_id": "s1",
            "user_key": "u1",
            "tool_name": "time_now",
            "args": {},
        }
    ]
