from __future__ import annotations

import json
import os
from collections import defaultdict, deque
from typing import Any

import httpx

from .types import ChatResponse, ToolCall


class AnthropicClient:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key_env_var: str,
        anthropic_version: str = '2023-06-01',
        max_output_tokens: int = 2048,
        timeout_s: int = 60,
    ) -> None:
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.api_key_env_var = api_key_env_var
        self.anthropic_version = anthropic_version
        self.max_output_tokens = max_output_tokens
        self.timeout_s = timeout_s

    def _api_key(self) -> str:
        key = os.environ.get(self.api_key_env_var, '').strip()
        if not key:
            raise RuntimeError(
                f"Missing API key. Set environment variable {self.api_key_env_var}."
            )
        return key

    def _anthropic_tools(self, tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
        if not tools:
            return None
        out: list[dict[str, Any]] = []
        for item in tools:
            fn = (item or {}).get('function') or {}
            name = str(fn.get('name') or '').strip()
            if not name:
                continue
            out.append(
                {
                    'name': name,
                    'description': str(fn.get('description') or ''),
                    'input_schema': fn.get('parameters') or {'type': 'object', 'properties': {}},
                }
            )
        return out or None

    def _convert_messages(self, messages: list[dict[str, Any]]) -> tuple[str | None, list[dict[str, Any]]]:
        system_parts: list[str] = []
        anthropic_messages: list[dict[str, Any]] = []
        pending_tool_ids: dict[str, deque[str]] = defaultdict(deque)
        seq = 0

        for msg in messages:
            role = str(msg.get('role') or 'user')
            if role == 'system':
                text = msg.get('content')
                if text:
                    system_parts.append(str(text))
                continue

            if role == 'assistant' and msg.get('tool_calls'):
                blocks: list[dict[str, Any]] = []
                text = msg.get('content')
                if text:
                    blocks.append({'type': 'text', 'text': str(text)})
                for call in msg.get('tool_calls') or []:
                    fn = (call or {}).get('function') or {}
                    name = str(fn.get('name') or '').strip()
                    if not name:
                        continue
                    raw_args = fn.get('arguments')
                    if isinstance(raw_args, str):
                        try:
                            args = json.loads(raw_args)
                        except Exception:
                            args = {}
                    elif isinstance(raw_args, dict):
                        args = raw_args
                    else:
                        args = {}
                    seq += 1
                    tool_id = str(call.get('id') or f'toolu_{seq}')
                    pending_tool_ids[name].append(tool_id)
                    blocks.append({'type': 'tool_use', 'id': tool_id, 'name': name, 'input': args})
                anthropic_messages.append({'role': 'assistant', 'content': blocks})
                continue

            if role == 'tool':
                name = str(msg.get('name') or '').strip() or 'tool'
                tool_id = pending_tool_ids[name].popleft() if pending_tool_ids[name] else f'toolu_{name}'
                anthropic_messages.append(
                    {
                        'role': 'user',
                        'content': [
                            {
                                'type': 'tool_result',
                                'tool_use_id': tool_id,
                                'content': str(msg.get('content') or ''),
                            }
                        ],
                    }
                )
                continue

            content = msg.get('content')
            if isinstance(content, list):
                anthropic_messages.append({'role': role if role in {'user', 'assistant'} else 'user', 'content': content})
            else:
                anthropic_messages.append({'role': role if role in {'user', 'assistant'} else 'user', 'content': str(content or '')})

        system = '\n\n'.join(part for part in system_parts if part) or None
        return system, anthropic_messages

    def chat(self, messages: list[dict[str, Any]], *, tools: list[dict[str, Any]] | None = None) -> ChatResponse:
        url = f"{self.base_url}/messages"
        system, anthropic_messages = self._convert_messages(messages)
        payload: dict[str, Any] = {
            'model': self.model,
            'max_tokens': self.max_output_tokens,
            'messages': anthropic_messages,
        }
        if system:
            payload['system'] = system
        tool_defs = self._anthropic_tools(tools)
        if tool_defs:
            payload['tools'] = tool_defs

        headers = {
            'x-api-key': self._api_key(),
            'anthropic-version': self.anthropic_version,
            'content-type': 'application/json',
        }

        try:
            with httpx.Client(timeout=self.timeout_s) as client:
                r = client.post(url, json=payload, headers=headers)
                r.raise_for_status()
                data = r.json()
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"Anthropic HTTP error: {e.response.status_code} {e.response.text}")
        except httpx.ConnectError as e:
            raise RuntimeError(f"Cannot connect to {self.base_url}: {e!r}")

        content_blocks = data.get('content') or []
        text_parts: list[str] = []
        calls: list[ToolCall] = []
        if isinstance(content_blocks, list):
            for block in content_blocks:
                if not isinstance(block, dict):
                    continue
                btype = block.get('type')
                if btype == 'text':
                    text_parts.append(str(block.get('text') or ''))
                elif btype == 'tool_use':
                    name = str(block.get('name') or '').strip()
                    if name:
                        inp = block.get('input')
                        args = inp if isinstance(inp, dict) else {}
                        calls.append(ToolCall(name=name, arguments=args, id=str(block.get('id') or '') or None))

        usage = data.get('usage') or {}
        usage_dict = None
        if isinstance(usage, dict):
            prompt_tokens = int(usage.get('input_tokens') or 0)
            completion_tokens = int(usage.get('output_tokens') or 0)
            total_tokens = prompt_tokens + completion_tokens
            if total_tokens:
                usage_dict = {
                    'prompt_tokens': prompt_tokens,
                    'completion_tokens': completion_tokens,
                    'total_tokens': total_tokens,
                }
        return ChatResponse(content='\n'.join(p for p in text_parts if p).strip(), tool_calls=calls, usage=usage_dict)
