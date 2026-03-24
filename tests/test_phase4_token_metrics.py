from __future__ import annotations

from types import SimpleNamespace

from openmiura.core.agent_runtime import AgentRuntime
from openmiura.core.llm.ollama import ChatResponse, ToolCall


class _FakeAudit:
    def get_recent_messages(self, session_id: str, limit: int):
        return []


class _FakeTools:
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
        return "2026-03-17T12:00:00+01:00"


class _FakeLLM:
    def __init__(self) -> None:
        self.calls = 0
        self.model = "qwen"

    def chat(self, messages, *, tools=None):
        self.calls += 1
        if self.calls == 1:
            return ChatResponse(
                content="",
                tool_calls=[ToolCall(name="time_now", arguments={})],
                usage={"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
            )
        return ChatResponse(
            content="Son las 12:00.",
            tool_calls=[],
            usage={"prompt_tokens": 14, "completion_tokens": 4, "total_tokens": 18},
        )


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


def test_record_tokens_not_double_counted_on_first_tool_round(monkeypatch) -> None:
    runtime = AgentRuntime(settings=_settings(), audit=_FakeAudit())
    runtime.llm = _FakeLLM()
    tools = _FakeTools()
    recorded: list[dict] = []

    monkeypatch.setattr("openmiura.core.agent_runtime.record_tokens", lambda model, **usage: recorded.append({"model": model, **usage}))

    out = runtime.generate_reply(
        agent_id="default",
        session_id="s1",
        user_text="¿Qué hora es?",
        extra_system="",
        tools_runtime=tools,
        user_key="u1",
    )

    assert out == "Son las 12:00."
    assert recorded == [
        {"model": "qwen", "prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
        {"model": "qwen", "prompt_tokens": 14, "completion_tokens": 4, "total_tokens": 18},
    ]
