"""Prompt caching for the Anthropic client.

All the cost-saving plumbing (cache-token parsing, cache rates, UI
surfacing) already existed, but no request ever asked for caching — so a
multi-round tool loop re-paid full input price on the stable system+tools
prefix every round. These tests pin that the client now places a single
ephemeral cache breakpoint on that prefix (system, or the last tool when
there's no system), and that it can be turned off.
"""
from __future__ import annotations

import json

import httpx
import pytest

from openmiura.core.llm import AnthropicClient


@pytest.fixture(autouse=True)
def _stamp_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_KEY", "sk-ant-test")


def _client(**kw) -> tuple[AnthropicClient, list[dict]]:
    seen: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(json.loads(req.content))
        return httpx.Response(200, json={
            "content": [{"type": "text", "text": "ok"}],
            "usage": {"input_tokens": 5, "output_tokens": 1},
        })

    client = AnthropicClient(
        base_url="http://test", model="claude-opus-4-8",
        api_key_env_var="ANTHROPIC_KEY",
        transport=httpx.MockTransport(handler), **kw,
    )
    return client, seen


_TOOLS = [{"type": "function", "function": {"name": "lookup", "parameters": {"type": "object", "properties": {}}}}]


def test_system_prefix_gets_cache_breakpoint() -> None:
    client, seen = _client()
    client.chat([
        {"role": "system", "content": "You are a careful lab assistant."},
        {"role": "user", "content": "hi"},
    ], tools=_TOOLS)
    system = seen[0]["system"]
    # system becomes a list of blocks carrying the breakpoint.
    assert isinstance(system, list)
    assert system[0]["type"] == "text"
    assert system[0]["text"] == "You are a careful lab assistant."
    assert system[0]["cache_control"] == {"type": "ephemeral"}
    # A breakpoint on system also caches the tools that render before it,
    # so we don't (need to) double-mark the tools.
    assert "cache_control" not in seen[0]["tools"][-1]


def test_tools_get_breakpoint_when_no_system() -> None:
    client, seen = _client()
    client.chat([{"role": "user", "content": "hi"}], tools=_TOOLS)
    assert "system" not in seen[0]
    assert seen[0]["tools"][-1]["cache_control"] == {"type": "ephemeral"}


def test_no_breakpoint_when_disabled() -> None:
    client, seen = _client(prompt_caching=False)
    client.chat([
        {"role": "system", "content": "You are a careful lab assistant."},
        {"role": "user", "content": "hi"},
    ], tools=_TOOLS)
    # system stays a plain string; no cache_control anywhere.
    assert isinstance(seen[0]["system"], str)
    assert "cache_control" not in seen[0]["tools"][-1]


def test_no_system_no_tools_is_a_noop() -> None:
    client, seen = _client()
    client.chat([{"role": "user", "content": "hi"}])
    assert "system" not in seen[0]
    assert "tools" not in seen[0]
