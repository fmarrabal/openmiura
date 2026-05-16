from __future__ import annotations

import json
import os
from typing import Any, AsyncIterator, Optional

import httpx

from .types import ChatResponse, LlmStreamEvent, ToolCall


# ------------------------------------------------------------------
# Shared parsing helpers
# ------------------------------------------------------------------


def _normalise_content(raw: Any) -> str:
    """Convert OpenAI's content field into a plain string.

    The field is usually a string, but tool-augmented
    completions can return a list of blocks
    ``[{"type": "text", "text": "..."}]``. We collapse those
    by concatenating the text fields with newlines.
    """
    if raw is None:
        return ''
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        parts: list[str] = []
        for block in raw:
            if isinstance(block, dict) and block.get('type') in {'text', 'output_text'}:
                parts.append(str(block.get('text') or block.get('content') or ''))
        return '\n'.join(p for p in parts if p)
    return str(raw)


def _parse_tool_call_dict(item: Any) -> ToolCall | None:
    """Parse a *complete* tool_call dict into ToolCall.

    Used by the synchronous ``chat`` path and by the
    streaming assembler when a call is flushed. Returns
    ``None`` for malformed entries so the caller can skip
    silently.
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
            args = json.loads(raw_args) if raw_args.strip() else {}
        except Exception:
            args = {}
    elif isinstance(raw_args, dict):
        args = raw_args
    else:
        args = {}
    return ToolCall(name=name, arguments=args, id=str(item.get('id') or '') or None)


def _usage_from_payload(payload: Any) -> Optional[dict[str, int]]:
    """Extract token-usage stats from an OpenAI ``usage`` block."""
    if not isinstance(payload, dict):
        return None
    prompt_tokens = int(payload.get('prompt_tokens') or 0)
    completion_tokens = int(payload.get('completion_tokens') or 0)
    total_tokens = int(payload.get('total_tokens') or (prompt_tokens + completion_tokens))
    if total_tokens:
        return {
            'prompt_tokens':     prompt_tokens,
            'completion_tokens': completion_tokens,
            'total_tokens':      total_tokens,
        }
    return None


class _ToolCallAssembler:
    """Reassemble OpenAI-style streamed tool calls.

    The OpenAI streaming format emits tool calls in pieces:
    the ``function.name`` arrives in the first chunk with
    ``id`` and ``index``; subsequent chunks for the same
    index append to ``function.arguments`` as a JSON string.
    The chunk with ``finish_reason="tool_calls"`` signals
    that all calls are complete.

    The assembler accumulates pieces per ``index`` and lets
    the caller flush completed calls when the stream signals
    end-of-tool-block.
    """

    def __init__(self) -> None:
        self._slots: dict[int, dict[str, Any]] = {}

    def absorb(self, deltas: Any) -> None:
        if not isinstance(deltas, list):
            return
        for d in deltas:
            if not isinstance(d, dict):
                continue
            idx = d.get('index')
            if not isinstance(idx, int):
                # Fallback: append at the next free index.
                idx = len(self._slots)
            slot = self._slots.setdefault(idx, {
                'id': None,
                'function': {'name': None, 'arguments': ''},
            })
            if d.get('id'):
                slot['id'] = str(d['id'])
            fn = d.get('function') or {}
            if isinstance(fn, dict):
                if fn.get('name'):
                    slot['function']['name'] = str(fn['name'])
                args = fn.get('arguments')
                if isinstance(args, str):
                    slot['function']['arguments'] += args
                elif isinstance(args, dict):
                    # Some providers send a complete dict in
                    # a single chunk. Marshal back to a
                    # JSON string so the final json.loads
                    # call in _parse_tool_call_dict yields
                    # the dict we want.
                    slot['function']['arguments'] = json.dumps(args)

    def flush(self) -> list[ToolCall]:
        """Drain the assembler, returning all complete tool
        calls in index order. Calls without a function name
        are skipped silently (matches sync ``chat`` behaviour)."""
        out: list[ToolCall] = []
        for _, slot in sorted(self._slots.items(), key=lambda kv: kv[0]):
            tc = _parse_tool_call_dict(slot)
            if tc is not None:
                out.append(tc)
        self._slots.clear()
        return out

    def has_partial(self) -> bool:
        return bool(self._slots)


class OpenAICompatibleClient:
    """HTTP client for the OpenAI Chat Completions API plus
    compatible providers (Kimi/Moonshot, etc.).

    Two methods are exposed:

      - ``chat(messages, *, tools)``       — synchronous,
                                              single-shot,
                                              returns ChatResponse.
                                              (unchanged contract)
      - ``chat_stream(messages, *, tools)`` — async generator,
                                              yields LlmStreamEvent.
                                              (H1.2, new)

    The shared parsing helpers (``_normalise_content``,
    ``_parse_tool_call_dict``, ``_usage_from_payload``) keep
    the two methods consistent; ``_ToolCallAssembler`` is
    only used by the streaming path.

    The optional ``transport`` constructor arg accepts an
    httpx transport for tests to inject ``MockTransport``.
    """

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key_env_var: str,
        timeout_s: int = 60,
        transport: httpx.BaseTransport | httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.api_key_env_var = api_key_env_var
        self.timeout_s = timeout_s
        self._transport = transport

    def _api_key(self) -> str:
        key = os.environ.get(self.api_key_env_var, '').strip()
        if not key:
            raise RuntimeError(
                f"Missing API key. Set environment variable {self.api_key_env_var}."
            )
        return key

    # ------------------------------------------------------------------
    # Synchronous single-shot — unchanged contract
    # ------------------------------------------------------------------

    def chat(self, messages: list[dict[str, Any]], *, tools: list[dict[str, Any]] | None = None) -> ChatResponse:
        url = f"{self.base_url}/chat/completions"
        payload: dict[str, Any] = {
            'model':    self.model,
            'messages': messages,
        }
        if tools:
            payload['tools'] = tools
            payload['tool_choice'] = 'auto'

        headers = {
            'Authorization': f"Bearer {self._api_key()}",
            'Content-Type':  'application/json',
        }

        try:
            client_kwargs: dict[str, Any] = {'timeout': self.timeout_s}
            if isinstance(self._transport, httpx.BaseTransport):
                client_kwargs['transport'] = self._transport
            with httpx.Client(**client_kwargs) as client:
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
        content = _normalise_content(msg.get('content', ''))

        parsed_calls: list[ToolCall] = []
        for item in (msg.get('tool_calls') or []):
            tc = _parse_tool_call_dict(item)
            if tc is not None:
                parsed_calls.append(tc)

        return ChatResponse(
            content=content.strip(),
            tool_calls=parsed_calls,
            usage=_usage_from_payload(data.get('usage')),
        )

    # ------------------------------------------------------------------
    # H1.2 — Async streaming
    # ------------------------------------------------------------------

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[LlmStreamEvent]:
        """Async generator yielding canonical ``LlmStreamEvent``
        events for the OpenAI streaming Chat Completions API.

        Wire format: SSE. Each line is ``data: <json>`` (or
        ``data: [DONE]`` for the terminator). Content deltas
        are streamed as ``choices[0].delta.content``; tool
        calls arrive piecewise via
        ``choices[0].delta.tool_calls[].function.arguments``
        and must be reassembled per ``index``.

        Usage info arrives in the final pre-[DONE] chunk only
        when the request was sent with
        ``stream_options.include_usage=True`` — we always set
        it so the canonical ``usage`` event fires.

        Errors land as ``kind="error"`` events; the generator
        returns after yielding the error. It never raises.
        """
        url = f"{self.base_url}/chat/completions"
        payload: dict[str, Any] = {
            'model':          self.model,
            'messages':       messages,
            'stream':         True,
            'stream_options': {'include_usage': True},
        }
        if tools:
            payload['tools']       = tools
            payload['tool_choice'] = 'auto'

        try:
            headers = {
                'Authorization': f"Bearer {self._api_key()}",
                'Content-Type':  'application/json',
                'Accept':        'text/event-stream',
            }
        except RuntimeError as e:
            yield LlmStreamEvent.make_error(str(e))
            return

        content_accum = ''
        assembler = _ToolCallAssembler()
        usage: Optional[dict[str, int]] = None
        finish_reason: Optional[str] = None
        flushed_tools = False

        client_kwargs: dict[str, Any] = {'timeout': self.timeout_s}
        if isinstance(self._transport, httpx.AsyncBaseTransport):
            client_kwargs['transport'] = self._transport

        try:
            async with httpx.AsyncClient(**client_kwargs) as client:
                async with client.stream('POST', url, json=payload, headers=headers) as response:
                    if response.status_code >= 400:
                        body = await response.aread()
                        yield LlmStreamEvent.make_error(
                            f'OpenAI-compatible HTTP error: {response.status_code} '
                            f'{body.decode("utf-8", errors="replace")[:500]}'
                        )
                        return
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        # SSE comment lines (start with ":")
                        # are heartbeats — skip silently.
                        if line.startswith(':'):
                            continue
                        if not line.startswith('data: '):
                            continue
                        payload_str = line[len('data: '):].strip()
                        if payload_str == '[DONE]':
                            # Terminator — flush any remaining
                            # tool calls in case the provider
                            # didn't set finish_reason.
                            if not flushed_tools and assembler.has_partial():
                                for tc in assembler.flush():
                                    yield LlmStreamEvent.make_tool_call(tc)
                                flushed_tools = True
                            if usage:
                                yield LlmStreamEvent.make_usage(usage)
                            final = ChatResponse(
                                content=content_accum.strip(),
                                tool_calls=[],  # filled below
                                usage=usage,
                            )
                            # Re-create the tool_calls list by
                            # absorbing nothing and flushing
                            # (assembler is already drained;
                            # we keep the events we yielded).
                            yield LlmStreamEvent.make_done(final)
                            return
                        try:
                            obj = json.loads(payload_str)
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(obj, dict):
                            continue

                        # Usage chunk (sent as the very last
                        # message when stream_options includes it).
                        chunk_usage = _usage_from_payload(obj.get('usage'))
                        if chunk_usage:
                            usage = chunk_usage

                        choices = obj.get('choices') or []
                        if not choices or not isinstance(choices[0], dict):
                            continue
                        choice = choices[0]
                        delta = choice.get('delta') or {}

                        # Content delta
                        c = delta.get('content')
                        if isinstance(c, str) and c:
                            content_accum += c
                            yield LlmStreamEvent.make_delta(c)
                        elif isinstance(c, list):
                            text = _normalise_content(c)
                            if text:
                                content_accum += text
                                yield LlmStreamEvent.make_delta(text)

                        # Tool call deltas — absorb piecewise.
                        if 'tool_calls' in delta and delta['tool_calls']:
                            assembler.absorb(delta['tool_calls'])

                        # finish_reason signals the end of a
                        # message. "tool_calls" is the right
                        # moment to flush the assembled calls.
                        fr = choice.get('finish_reason')
                        if isinstance(fr, str):
                            finish_reason = fr
                            if fr in ('tool_calls', 'stop', 'length', 'content_filter'):
                                if not flushed_tools and assembler.has_partial():
                                    for tc in assembler.flush():
                                        yield LlmStreamEvent.make_tool_call(tc)
                                    flushed_tools = True

            # Fell out of the stream without [DONE] — emit a
            # graceful done with whatever we accumulated.
            if not flushed_tools and assembler.has_partial():
                for tc in assembler.flush():
                    yield LlmStreamEvent.make_tool_call(tc)
            if usage:
                yield LlmStreamEvent.make_usage(usage)
            yield LlmStreamEvent.make_done(ChatResponse(
                content=content_accum.strip(),
                tool_calls=[],
                usage=usage,
            ))

        except httpx.ConnectError as e:
            yield LlmStreamEvent.make_error(f'Cannot connect to {self.base_url}: {e!r}')
        except httpx.HTTPStatusError as e:
            yield LlmStreamEvent.make_error(
                f'OpenAI-compatible HTTP error during stream: {e.response.status_code}'
            )
        except Exception as e:
            yield LlmStreamEvent.make_error(f'OpenAI-compatible stream error: {e!r}')
