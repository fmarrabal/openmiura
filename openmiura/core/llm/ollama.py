from __future__ import annotations

import json
from typing import Any, Dict, List

import httpx

from .types import ChatResponse, ToolCall


class OllamaClient:
    def __init__(self, base_url: str, model: str, timeout_s: int = 60):
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.timeout_s = timeout_s

    def chat(
        self,
        messages: List[Dict[str, Any]],
        *,
        tools: List[Dict[str, Any]] | None = None,
    ) -> ChatResponse:
        url = f"{self.base_url}/api/chat"
        payload: Dict[str, Any] = {
            'model': self.model,
            'messages': messages,
            'stream': False,
        }
        if tools:
            payload['tools'] = tools

        try:
            with httpx.Client(timeout=self.timeout_s) as client:
                r = client.post(url, json=payload)
                r.raise_for_status()
                data = r.json()

            msg = data.get('message') or {}
            content = msg.get('content', '')
            if not isinstance(content, str):
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

            usage_dict = None
            if isinstance(data.get('usage'), dict):
                usage_dict = {k: int(v) for k, v in data.get('usage', {}).items() if isinstance(v, (int, float))}
            else:
                prompt_tokens = int(data.get('prompt_eval_count') or 0)
                completion_tokens = int(data.get('eval_count') or 0)
                total_tokens = prompt_tokens + completion_tokens
                if total_tokens:
                    usage_dict = {
                        'prompt_tokens': prompt_tokens,
                        'completion_tokens': completion_tokens,
                        'total_tokens': total_tokens,
                    }
            return ChatResponse(content=content.strip(), tool_calls=parsed_calls, usage=usage_dict)

        except httpx.ConnectError as e:
            raise RuntimeError(
                'Cannot connect to Ollama. Is it running on '
                f'{self.base_url}? Error: {e!r}'
            )
        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f'Ollama HTTP error: {e.response.status_code} {e.response.text}'
            )
