from __future__ import annotations

import json
import os
from typing import Any

import httpx

from .types import ChatResponse, ToolCall


class OpenAICompatibleClient:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key_env_var: str,
        timeout_s: int = 60,
    ) -> None:
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.api_key_env_var = api_key_env_var
        self.timeout_s = timeout_s

    def _api_key(self) -> str:
        key = os.environ.get(self.api_key_env_var, '').strip()
        if not key:
            raise RuntimeError(
                f"Missing API key. Set environment variable {self.api_key_env_var}."
            )
        return key

    def chat(self, messages: list[dict[str, Any]], *, tools: list[dict[str, Any]] | None = None) -> ChatResponse:
        url = f"{self.base_url}/chat/completions"
        payload: dict[str, Any] = {
            'model': self.model,
            'messages': messages,
        }
        if tools:
            payload['tools'] = tools
            payload['tool_choice'] = 'auto'

        headers = {
            'Authorization': f"Bearer {self._api_key()}",
            'Content-Type': 'application/json',
        }

        try:
            with httpx.Client(timeout=self.timeout_s) as client:
                r = client.post(url, json=payload, headers=headers)
                r.raise_for_status()
                data = r.json()
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"OpenAI-compatible HTTP error: {e.response.status_code} {e.response.text}")
        except httpx.ConnectError as e:
            raise RuntimeError(f"Cannot connect to {self.base_url}: {e!r}")

        choices = data.get('choices') or []
        if not choices or not isinstance(choices[0], dict):
            raise RuntimeError(f"Unexpected chat completion response: {data}")
        msg = choices[0].get('message') or {}
        content = msg.get('content', '')
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict) and block.get('type') in {'text', 'output_text'}:
                    parts.append(str(block.get('text') or block.get('content') or ''))
            content = '\n'.join(p for p in parts if p)
        elif content is None:
            content = ''
        elif not isinstance(content, str):
            content = str(content)

        parsed_calls: list[ToolCall] = []
        raw_calls = msg.get('tool_calls') or []
        if isinstance(raw_calls, list):
            for item in raw_calls:
                if not isinstance(item, dict):
                    continue
                fn = item.get('function') or {}
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
                parsed_calls.append(ToolCall(name=name, arguments=args, id=str(item.get('id') or '') or None))

        usage = data.get('usage') or {}
        usage_dict = None
        if isinstance(usage, dict):
            prompt_tokens = int(usage.get('prompt_tokens') or 0)
            completion_tokens = int(usage.get('completion_tokens') or 0)
            total_tokens = int(usage.get('total_tokens') or (prompt_tokens + completion_tokens))
            if total_tokens:
                usage_dict = {
                    'prompt_tokens': prompt_tokens,
                    'completion_tokens': completion_tokens,
                    'total_tokens': total_tokens,
                }
        return ChatResponse(content=str(content).strip(), tool_calls=parsed_calls, usage=usage_dict)
