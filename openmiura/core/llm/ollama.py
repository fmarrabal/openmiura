from __future__ import annotations

import json
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from .types import ChatResponse, LlmStreamEvent, ToolCall


def _parse_tool_call(item: Any) -> ToolCall | None:
    """Normalise one Ollama tool_call entry into our ToolCall.

    Ollama returns ``message.tool_calls = [{"function": {"name": "...",
    "arguments": {...}}, "id": "..."}]``. The arguments field
    sometimes arrives as a JSON-encoded string instead of a
    dict — accept both.

    Returns ``None`` for malformed entries (e.g. missing
    function name) so the caller can skip them silently.
    """
    if not isinstance(item, dict):
        return None
    fn = item.get('function') or {}
    name = str(fn.get('name') or '').strip()
    if not name:
        return None
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
    return ToolCall(name=name, arguments=args, id=str(item.get('id') or '') or None)


def _usage_from_payload(data: dict[str, Any]) -> dict[str, int] | None:
    """Extract token-usage stats from a final Ollama message.

    Two layouts are seen in the wild:
      - Modern: ``usage = {"prompt_tokens": ..., "completion_tokens": ..., ...}``
      - Legacy: top-level ``prompt_eval_count`` + ``eval_count``.

    Returns ``None`` if neither layout has data.
    """
    if isinstance(data.get('usage'), dict):
        return {k: int(v) for k, v in data['usage'].items() if isinstance(v, (int, float))}
    prompt_tokens = int(data.get('prompt_eval_count') or 0)
    completion_tokens = int(data.get('eval_count') or 0)
    total_tokens = prompt_tokens + completion_tokens
    if total_tokens:
        return {
            'prompt_tokens':     prompt_tokens,
            'completion_tokens': completion_tokens,
            'total_tokens':      total_tokens,
        }
    return None


class OllamaClient:
    """HTTP client for the Ollama server.

    Two methods are exposed:

      - ``chat(messages, *, tools)``       — synchronous,
                                              single-shot,
                                              returns ChatResponse.
                                              (unchanged since v1)
      - ``chat_stream(messages, *, tools)`` — async generator,
                                              yields LlmStreamEvent.
                                              (H1.1, new)

    Both methods share the tool-call and usage parsing
    helpers so a future change to the Ollama response shape
    only needs to be made once.

    The optional ``transport`` constructor arg accepts an
    ``httpx.AsyncBaseTransport`` (or a sync one for ``chat``);
    tests inject ``httpx.MockTransport`` to fake the wire.
    Production code never passes it.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_s: int = 60,
        *,
        transport: httpx.BaseTransport | httpx.AsyncBaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.timeout_s = timeout_s
        self._transport = transport

    # ------------------------------------------------------------------
    # Synchronous single-shot — unchanged contract
    # ------------------------------------------------------------------

    def chat(
        self,
        messages: List[Dict[str, Any]],
        *,
        tools: List[Dict[str, Any]] | None = None,
    ) -> ChatResponse:
        url = f"{self.base_url}/api/chat"
        payload: Dict[str, Any] = {
            'model':    self.model,
            'messages': messages,
            'stream':   False,
        }
        if tools:
            payload['tools'] = tools

        try:
            client_kwargs: Dict[str, Any] = {'timeout': self.timeout_s}
            if isinstance(self._transport, httpx.BaseTransport):
                client_kwargs['transport'] = self._transport
            with httpx.Client(**client_kwargs) as client:
                r = client.post(url, json=payload)
                r.raise_for_status()
                data = r.json()

            msg = data.get('message') or {}
            content = msg.get('content', '')
            if not isinstance(content, str):
                content = str(content)

            parsed_calls: list[ToolCall] = []
            for item in (msg.get('tool_calls') or []):
                tc = _parse_tool_call(item)
                if tc is not None:
                    parsed_calls.append(tc)

            return ChatResponse(
                content=content.strip(),
                tool_calls=parsed_calls,
                usage=_usage_from_payload(data),
            )

        except httpx.ConnectError as e:
            raise RuntimeError(
                'Cannot connect to Ollama. Is it running on '
                f'{self.base_url}? Error: {e!r}'
            )
        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f'Ollama HTTP error: {e.response.status_code} {e.response.text}'
            )

    # ------------------------------------------------------------------
    # H1.1 — Async streaming
    # ------------------------------------------------------------------

    async def chat_stream(
        self,
        messages: List[Dict[str, Any]],
        *,
        tools: List[Dict[str, Any]] | None = None,
    ) -> AsyncIterator[LlmStreamEvent]:
        """Async generator that yields a canonical
        ``LlmStreamEvent`` sequence.

        Ollama's wire format for ``/api/chat`` with
        ``stream: true`` is newline-delimited JSON. Each line
        is a complete ``{"message": {"content": "<delta>"},
        "done": false}`` object. The final line carries
        ``done: true`` plus the token-usage fields and, when
        relevant, a ``tool_calls`` array on the message.

        Content deltas yield ``kind="delta"`` events as they
        arrive. Tool calls yield ``kind="tool_call"`` events
        (Ollama emits the full call in one shot, no argument
        streaming to assemble). The final ``kind="done"``
        event carries the materialised ``ChatResponse`` so a
        consumer that wants the single-shot contract can
        wait for ``done`` and ignore everything else.

        Errors are surfaced as ``kind="error"`` events; the
        generator then returns (it never raises out).
        """
        url = f"{self.base_url}/api/chat"
        payload: Dict[str, Any] = {
            'model':    self.model,
            'messages': messages,
            'stream':   True,
        }
        if tools:
            payload['tools'] = tools

        content_accum = ''
        tool_calls_accum: list[ToolCall] = []
        usage: Optional[dict[str, int]] = None

        client_kwargs: Dict[str, Any] = {'timeout': self.timeout_s}
        if isinstance(self._transport, httpx.AsyncBaseTransport):
            client_kwargs['transport'] = self._transport

        try:
            async with httpx.AsyncClient(**client_kwargs) as client:
                async with client.stream('POST', url, json=payload) as response:
                    if response.status_code >= 400:
                        # We need to read the body before the
                        # context manager closes; aread() returns
                        # bytes.
                        body = await response.aread()
                        yield LlmStreamEvent.make_error(
                            f'Ollama HTTP error: {response.status_code} '
                            f'{body.decode("utf-8", errors="replace")[:500]}'
                        )
                        return
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                        except json.JSONDecodeError:
                            # A partial / corrupt line — skip
                            # silently. The next valid line
                            # will continue the stream.
                            continue
                        if not isinstance(data, dict):
                            continue

                        msg = data.get('message') or {}
                        # Content delta
                        content_delta = msg.get('content', '')
                        if isinstance(content_delta, str) and content_delta:
                            content_accum += content_delta
                            yield LlmStreamEvent.make_delta(content_delta)

                        # Tool calls (Ollama emits them whole)
                        for item in (msg.get('tool_calls') or []):
                            tc = _parse_tool_call(item)
                            if tc is not None:
                                tool_calls_accum.append(tc)
                                yield LlmStreamEvent.make_tool_call(tc)

                        if data.get('done', False):
                            usage = _usage_from_payload(data)
                            if usage:
                                yield LlmStreamEvent.make_usage(usage)
                            final = ChatResponse(
                                content=content_accum.strip(),
                                tool_calls=tool_calls_accum,
                                usage=usage,
                            )
                            yield LlmStreamEvent.make_done(final)
                            return

        except httpx.ConnectError as e:
            yield LlmStreamEvent.make_error(
                f'Cannot connect to Ollama at {self.base_url}: {e!r}'
            )
        except httpx.HTTPStatusError as e:
            # raise_for_status() isn't called inside the
            # stream block (we check status_code manually
            # above), but a network-level HTTPStatusError can
            # still surface during a chunked read.
            yield LlmStreamEvent.make_error(
                f'Ollama HTTP error during stream: {e.response.status_code}'
            )
        except Exception as e:
            yield LlmStreamEvent.make_error(f'Ollama stream error: {e!r}')
