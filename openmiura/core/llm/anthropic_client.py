from __future__ import annotations

import json
import os
from collections import defaultdict, deque
from typing import Any, AsyncIterator, Optional

import httpx

from .types import ChatResponse, LlmStreamEvent, ToolCall, ToolCallDelta


# ------------------------------------------------------------------
# Shared parsing helpers
# ------------------------------------------------------------------


def _usage_from_anthropic(payload: Any) -> Optional[dict[str, int]]:
    """Convert Anthropic's usage shape into our canonical
    ``{prompt_tokens, completion_tokens, total_tokens}`` (plus
    optional cache buckets).

    H3.6 — Anthropic reports prompt-cache tokens SEPARATELY from
    ``input_tokens`` (``input_tokens`` is already the non-cached
    portion), so ``cache_read_input_tokens`` /
    ``cache_creation_input_tokens`` add to the total rather than
    overlapping it. The cache keys are only included when
    non-zero so a plain (uncached) call keeps the canonical
    3-key shape."""
    if not isinstance(payload, dict):
        return None
    prompt_tokens = int(payload.get('input_tokens') or 0)
    completion_tokens = int(payload.get('output_tokens') or 0)
    cache_read = int(payload.get('cache_read_input_tokens') or 0)
    cache_write = int(payload.get('cache_creation_input_tokens') or 0)
    total_tokens = prompt_tokens + completion_tokens + cache_read + cache_write
    if total_tokens:
        usage: dict[str, int] = {
            'prompt_tokens':     prompt_tokens,
            'completion_tokens': completion_tokens,
            'total_tokens':      total_tokens,
        }
        if cache_read:
            usage['cache_read_tokens'] = cache_read
        if cache_write:
            usage['cache_write_tokens'] = cache_write
        return usage
    return None


def _parse_content_block(block: Any) -> tuple[str | None, ToolCall | None]:
    """Parse a single Anthropic content block (text or
    tool_use) into our shape. Returns ``(text, tool_call)``
    where exactly one may be non-None."""
    if not isinstance(block, dict):
        return (None, None)
    btype = block.get('type')
    if btype == 'text':
        return (str(block.get('text') or ''), None)
    if btype == 'tool_use':
        name = str(block.get('name') or '').strip()
        if not name:
            return (None, None)
        inp = block.get('input')
        args = inp if isinstance(inp, dict) else {}
        return (None, ToolCall(name=name, arguments=args, id=str(block.get('id') or '') or None))
    return (None, None)


class _StreamingBlockAssembler:
    """Reassemble Anthropic streaming content blocks.

    Anthropic streams typed events:
      - content_block_start  carries block ``index``, ``type``,
                             and for tool_use the name + id.
      - content_block_delta  for text blocks: ``delta.text_delta.text``;
                             for tool_use blocks:
                             ``delta.input_json_delta.partial_json``.
      - content_block_stop   signals end-of-block.

    The assembler keeps a slot per index and exposes
    ``ingest_start``, ``ingest_delta``, ``finalise_block`` so
    the streaming method can yield events at the right
    moments. Text deltas are yielded by the caller as they
    arrive; tool_use blocks are only emitted when their
    ``stop`` event arrives so the input JSON is complete.
    """

    def __init__(self) -> None:
        self._slots: dict[int, dict[str, Any]] = {}

    def ingest_start(self, idx: int, block: dict[str, Any]) -> ToolCallDelta | None:
        """Register a content block. For tool_use blocks,
        return an opening ``ToolCallDelta`` carrying the call's
        id + name (no args yet) so the caller can announce the
        call before its argument JSON streams in (H3.2).

        H3.4 — ``thinking`` blocks register a slot that buffers
        the extended-thinking reasoning trace; their text
        arrives as ``thinking_delta`` fragments (see
        ``ingest_delta``). ``redacted_thinking`` blocks (whose
        reasoning is encrypted server-side) register a slot too
        so a stray stop/delta never KeyErrors, but their
        content is never surfaced. Neither thinking variant is
        ever folded into ``text_accum`` — the assistant answer
        stays clean."""
        btype = block.get('type')
        if btype == 'text':
            self._slots[idx] = {'type': 'text', 'text': str(block.get('text') or '')}
        elif btype == 'thinking':
            self._slots[idx] = {'type': 'thinking', 'thinking': str(block.get('thinking') or ''), 'signature': ''}
        elif btype == 'redacted_thinking':
            # H3.8 — keep the encrypted payload so the block can be
            # echoed back verbatim on a follow-up tool-use request.
            self._slots[idx] = {'type': 'redacted_thinking', 'data': str(block.get('data') or '')}
        elif btype == 'tool_use':
            cid = str(block.get('id') or '') or None
            name = str(block.get('name') or '').strip()
            self._slots[idx] = {
                'type':         'tool_use',
                'id':           cid,
                'name':         name,
                'partial_json': '',
            }
            return ToolCallDelta(index=idx, id=cid, name=name or None, arguments_delta='')
        return None

    def ingest_delta(self, idx: int, delta: dict[str, Any]) -> tuple[str | None, ToolCallDelta | None, str | None]:
        """Apply a content_block_delta. Returns
        ``(text_fragment, tool_call_delta, thinking_fragment)``
        where at most one is non-None:

          - text blocks (``text_delta``) yield the text
            fragment to emit as a ``delta`` event;
          - tool_use blocks (``input_json_delta``) buffer the
            partial JSON AND return a ``ToolCallDelta`` carrying
            that raw fragment (H3.2) so the UI sees args
            forming;
          - thinking blocks (``thinking_delta``) buffer the
            reasoning AND return the raw thinking fragment
            (H3.4) so the UI can stream the trace.

        ``signature_delta`` (the cryptographic signature
        Anthropic appends to a thinking block) is buffered for
        completeness but never surfaced — it carries no
        human-readable reasoning."""
        if idx not in self._slots:
            return (None, None, None)
        slot = self._slots[idx]
        dtype = delta.get('type')
        if slot['type'] == 'text' and dtype == 'text_delta':
            text = str(delta.get('text') or '')
            if text:
                slot['text'] += text
                return (text, None, None)
        elif slot['type'] == 'tool_use' and dtype == 'input_json_delta':
            piece = str(delta.get('partial_json') or '')
            slot['partial_json'] += piece
            if piece:
                # id + name already delivered on the opening
                # delta; argument-only fragments carry None for
                # both (mirrors the OpenAI fragment shape).
                return (None, ToolCallDelta(index=idx, arguments_delta=piece), None)
        elif slot['type'] == 'thinking':
            if dtype == 'thinking_delta':
                piece = str(delta.get('thinking') or '')
                if piece:
                    slot['thinking'] += piece
                    return (None, None, piece)
            elif dtype == 'signature_delta':
                slot['signature'] += str(delta.get('signature') or '')
        return (None, None, None)

    def finalise_block(self, idx: int) -> ToolCall | None:
        """Mark a block as complete. Returns the ToolCall to
        emit (for tool_use blocks) or None (for text blocks
        — their content already streamed as deltas)."""
        slot = self._slots.get(idx)
        if not slot:
            return None
        if slot['type'] != 'tool_use':
            return None
        name = slot.get('name') or ''
        if not name:
            return None
        raw = slot.get('partial_json') or ''
        try:
            args = json.loads(raw) if raw.strip() else {}
        except Exception:
            args = {}
        return ToolCall(name=name, arguments=args, id=slot.get('id'))

    def text_accum(self) -> str:
        """Concatenate all text blocks (in index order) into
        the final ChatResponse content."""
        parts: list[str] = []
        for _, slot in sorted(self._slots.items(), key=lambda kv: kv[0]):
            if slot.get('type') == 'text':
                parts.append(slot.get('text') or '')
        return '\n'.join(p for p in parts if p).strip()

    def thinking_blocks(self) -> list[dict[str, Any]]:
        """Return the completed thinking / redacted_thinking blocks
        in index order, in Anthropic content-block shape, for
        multi-turn round-tripping (H3.8).

        A ``thinking`` block is emitted only once it carries a
        signature: Anthropic rejects an unsigned thinking block on
        a follow-up request, so an unsigned one (which shouldn't
        occur in practice) is dropped rather than sent and refused.
        ``redacted_thinking`` blocks are self-contained (the
        encrypted ``data``) and always pass through."""
        blocks: list[dict[str, Any]] = []
        for _, slot in sorted(self._slots.items(), key=lambda kv: kv[0]):
            t = slot.get('type')
            if t == 'thinking':
                sig = slot.get('signature') or ''
                if sig:
                    blocks.append({
                        'type':      'thinking',
                        'thinking':  slot.get('thinking') or '',
                        'signature': sig,
                    })
            elif t == 'redacted_thinking':
                blocks.append({'type': 'redacted_thinking', 'data': slot.get('data') or ''})
        return blocks


class AnthropicClient:
    """HTTP client for the Anthropic Messages API.

    Two methods:
      - ``chat(messages, *, tools)``       — synchronous,
                                              single-shot,
                                              returns ChatResponse.
                                              (unchanged contract)
      - ``chat_stream(messages, *, tools)`` — async generator,
                                              yields LlmStreamEvent.
                                              (H1.3, new)

    The streaming method follows the same canonical event
    sequence as the Ollama (H1.1) and OpenAI-compat (H1.2)
    clients:
        delta*  → (tool_call | usage)*  → done
                                        OR error

    Anthropic's wire format is typed SSE: each event carries
    an ``event: <name>`` header line followed by a single
    ``data: <json>`` line. We parse both. Tool-use input
    arrives as ``input_json_delta`` fragments under a
    ``content_block_delta`` event and is reassembled by
    ``_StreamingBlockAssembler``; the tool_call event is
    emitted once the block's ``content_block_stop`` arrives
    so consumers see a complete ToolCall, not a half-parsed
    JSON snippet.
    """

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key_env_var: str,
        anthropic_version: str = '2023-06-01',
        max_output_tokens: int = 2048,
        thinking_budget_tokens: int = 0,
        prompt_caching: bool = True,
        timeout_s: int = 60,
        transport: httpx.BaseTransport | httpx.AsyncBaseTransport | None = None,
    ) -> None:
        # H3.4 — extended thinking. ``thinking_budget_tokens``
        # is opt-in (0 = disabled, the default). When > 0 the
        # request asks Anthropic to emit a ``thinking`` content
        # block budgeted to that many tokens, surfaced to the
        # consumer as ``thinking`` stream events. Anthropic
        # imposes two hard constraints we validate up-front so a
        # misconfiguration fails loudly here rather than as an
        # opaque 400 mid-stream:
        #   - the budget must be at least 1024 tokens;
        #   - ``max_output_tokens`` must exceed the budget
        #     (the thinking tokens are drawn from the same
        #     output allowance as the answer).
        #
        # NOTE: extended thinking now works with the agent
        # runtime's multi-round tool loop (H3.8). Anthropic
        # requires the signed thinking block to be echoed back in
        # the assistant turn that precedes a tool_result; the
        # streaming/sync responses surface those blocks on
        # ``ChatResponse.thinking_blocks``, the runtime carries
        # them on the assistant turn it appends, and
        # ``_convert_messages`` re-emits them verbatim (signature
        # intact) ahead of the tool_use.
        if thinking_budget_tokens:
            if thinking_budget_tokens < 1024:
                raise ValueError(
                    'thinking_budget_tokens must be >= 1024 when enabled '
                    f'(got {thinking_budget_tokens})'
                )
            if max_output_tokens <= thinking_budget_tokens:
                raise ValueError(
                    'max_output_tokens must exceed thinking_budget_tokens '
                    f'(max_output_tokens={max_output_tokens}, '
                    f'thinking_budget_tokens={thinking_budget_tokens})'
                )
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.api_key_env_var = api_key_env_var
        self.anthropic_version = anthropic_version
        self.max_output_tokens = max_output_tokens
        self.thinking_budget_tokens = thinking_budget_tokens
        self.prompt_caching = prompt_caching
        self.timeout_s = timeout_s
        self._transport = transport

    def _apply_prompt_cache(self, payload: dict[str, Any]) -> None:
        """Place a single ephemeral prompt-cache breakpoint on the
        stable system+tools prefix.

        Anthropic renders ``tools`` -> ``system`` -> ``messages``, so a
        ``cache_control`` marker on the (last) system block also caches
        the tool definitions that precede it. The system+tools prefix is
        re-sent byte-identical on every round of the tool loop and on
        every turn of a session, so caching it lets those re-sends read
        at ~0.1x input price instead of full price. With no system we
        fall back to marking the last tool definition; with neither
        there is nothing stable to cache.

        Placement only — never changes the prompt content. A prefix below
        the model's minimum cacheable size simply isn't cached (no error,
        no extra cost). Caching is GA, so no beta header is required.
        """
        if not self.prompt_caching:
            return
        system = payload.get('system')
        if isinstance(system, str) and system.strip():
            payload['system'] = [{
                'type': 'text',
                'text': system,
                'cache_control': {'type': 'ephemeral'},
            }]
            return
        tools = payload.get('tools')
        if isinstance(tools, list) and tools and isinstance(tools[-1], dict):
            tools[-1] = {**tools[-1], 'cache_control': {'type': 'ephemeral'}}

    def _thinking_config(self) -> dict[str, Any] | None:
        """The ``thinking`` request field when extended thinking
        is enabled, else ``None`` (so the key is omitted)."""
        if self.thinking_budget_tokens:
            return {'type': 'enabled', 'budget_tokens': self.thinking_budget_tokens}
        return None

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
            out.append({
                'name':         name,
                'description':  str(fn.get('description') or ''),
                'input_schema': fn.get('parameters') or {'type': 'object', 'properties': {}},
            })
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
                # H3.8 — when extended thinking produced signed
                # thinking blocks for this turn, echo them back
                # verbatim FIRST: Anthropic requires the signed
                # thinking block ahead of the tool_use it justified,
                # or it rejects the follow-up request.
                for tb in msg.get('_thinking_blocks') or []:
                    if isinstance(tb, dict) and tb.get('type') in ('thinking', 'redacted_thinking'):
                        blocks.append(tb)
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
                anthropic_messages.append({
                    'role': 'user',
                    'content': [{
                        'type':         'tool_result',
                        'tool_use_id':  tool_id,
                        'content':      str(msg.get('content') or ''),
                    }],
                })
                continue

            # H3.3b — multi-modal attachments. When the
            # message carries an ``attachments`` field, promote
            # ``content`` to a list of blocks: text block first
            # (if any), then one ``image`` source-block per
            # image attachment. Non-image kinds are silently
            # dropped here — audit layer is the source of
            # truth for what *was* attached.
            attachments = msg.get('attachments') or []
            if attachments:
                blocks: list[dict[str, Any]] = []
                content = msg.get('content')
                if isinstance(content, str) and content:
                    blocks.append({'type': 'text', 'text': content})
                elif isinstance(content, list):
                    blocks.extend(b for b in content if isinstance(b, dict))
                for a in attachments:
                    if isinstance(a, dict):
                        kind = str(a.get('kind') or '').lower()
                        media = str(a.get('media_type') or '').strip()
                        data = str(a.get('data_b64') or '')
                    else:
                        kind = getattr(a, 'kind', '')
                        media = getattr(a, 'media_type', '')
                        data = getattr(a, 'data_b64', '')
                    if kind != 'image' or not data or not media.startswith('image/'):
                        continue
                    blocks.append({
                        'type':   'image',
                        'source': {
                            'type':       'base64',
                            'media_type': media,
                            'data':       data,
                        },
                    })
                anthropic_messages.append({
                    'role':    role if role in {'user', 'assistant'} else 'user',
                    'content': blocks,
                })
                continue

            content = msg.get('content')
            if isinstance(content, list):
                anthropic_messages.append({'role': role if role in {'user', 'assistant'} else 'user', 'content': content})
            else:
                anthropic_messages.append({'role': role if role in {'user', 'assistant'} else 'user', 'content': str(content or '')})

        system = '\n\n'.join(part for part in system_parts if part) or None
        return system, anthropic_messages

    def _headers(self) -> dict[str, str]:
        return {
            'x-api-key':         self._api_key(),
            'anthropic-version': self.anthropic_version,
            'content-type':      'application/json',
        }

    # ------------------------------------------------------------------
    # Synchronous single-shot — unchanged contract
    # ------------------------------------------------------------------

    def chat(self, messages: list[dict[str, Any]], *, tools: list[dict[str, Any]] | None = None) -> ChatResponse:
        url = f"{self.base_url}/messages"
        system, anthropic_messages = self._convert_messages(messages)
        payload: dict[str, Any] = {
            'model':      self.model,
            'max_tokens': self.max_output_tokens,
            'messages':   anthropic_messages,
        }
        if system:
            payload['system'] = system
        tool_defs = self._anthropic_tools(tools)
        if tool_defs:
            payload['tools'] = tool_defs
        thinking = self._thinking_config()
        if thinking:
            payload['thinking'] = thinking
        self._apply_prompt_cache(payload)

        try:
            client_kwargs: dict[str, Any] = {'timeout': self.timeout_s}
            if isinstance(self._transport, httpx.BaseTransport):
                client_kwargs['transport'] = self._transport
            with httpx.Client(**client_kwargs) as client:
                r = client.post(url, json=payload, headers=self._headers())
                r.raise_for_status()
                data = r.json()
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"Anthropic HTTP error: {e.response.status_code} {e.response.text}")
        except httpx.ConnectError as e:
            raise RuntimeError(f"Cannot connect to {self.base_url}: {e!r}")

        content_blocks = data.get('content') or []
        text_parts: list[str] = []
        calls: list[ToolCall] = []
        thinking_blocks: list[dict[str, Any]] = []
        if isinstance(content_blocks, list):
            for block in content_blocks:
                # H3.8 — keep raw thinking / redacted_thinking blocks
                # (signature/data intact) for multi-turn round-trip.
                if isinstance(block, dict) and block.get('type') in ('thinking', 'redacted_thinking'):
                    thinking_blocks.append(block)
                text, tc = _parse_content_block(block)
                if text:
                    text_parts.append(text)
                if tc is not None:
                    calls.append(tc)

        return ChatResponse(
            content='\n'.join(p for p in text_parts if p).strip(),
            tool_calls=calls,
            usage=_usage_from_anthropic(data.get('usage')),
            thinking_blocks=thinking_blocks or None,
        )

    # ------------------------------------------------------------------
    # H1.3 — Async streaming
    # ------------------------------------------------------------------

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[LlmStreamEvent]:
        """Async generator yielding canonical LlmStreamEvent
        events for the Anthropic Messages streaming API.

        Wire format: typed SSE. Pairs of ``event: <name>`` +
        ``data: <json>`` separated by blank lines. The parser
        tracks the current event name and pairs it with the
        next data payload.

        Events handled:
          - message_start         carries the initial usage
                                  (input_tokens; output may
                                  be 0 here)
          - content_block_start   registers a block with the
                                  assembler
          - content_block_delta   text_delta → yield delta event;
                                  thinking_delta → yield thinking
                                  event (H3.4); input_json_delta
                                  → buffer + yield tool_call_delta
          - content_block_stop    if tool_use → flush ToolCall
          - message_delta         carries final output_tokens
          - message_stop          emit usage + done
          - error                 emit kind="error", return

        Errors land as ``kind="error"`` events. The generator
        never raises out.
        """
        url = f"{self.base_url}/messages"
        system, anthropic_messages = self._convert_messages(messages)
        payload: dict[str, Any] = {
            'model':      self.model,
            'max_tokens': self.max_output_tokens,
            'messages':   anthropic_messages,
            'stream':     True,
        }
        if system:
            payload['system'] = system
        tool_defs = self._anthropic_tools(tools)
        if tool_defs:
            payload['tools'] = tool_defs
        thinking = self._thinking_config()
        if thinking:
            payload['thinking'] = thinking
        self._apply_prompt_cache(payload)

        try:
            headers = self._headers()
        except RuntimeError as e:
            yield LlmStreamEvent.make_error(str(e))
            return

        assembler = _StreamingBlockAssembler()
        # Native Anthropic usage keys accumulate here; the
        # _usage_from_anthropic conversion at message_stop turns
        # them into the canonical shape (incl. H3.6 cache buckets).
        usage_partial: dict[str, int] = {
            'input_tokens': 0, 'output_tokens': 0,
            'cache_read_input_tokens': 0, 'cache_creation_input_tokens': 0,
        }

        client_kwargs: dict[str, Any] = {'timeout': self.timeout_s}
        if isinstance(self._transport, httpx.AsyncBaseTransport):
            client_kwargs['transport'] = self._transport

        try:
            async with httpx.AsyncClient(**client_kwargs) as client:
                async with client.stream('POST', url, json=payload, headers=headers) as response:
                    if response.status_code >= 400:
                        body = await response.aread()
                        yield LlmStreamEvent.make_error(
                            f'Anthropic HTTP error: {response.status_code} '
                            f'{body.decode("utf-8", errors="replace")[:500]}'
                        )
                        return

                    current_event: str | None = None
                    async for line in response.aiter_lines():
                        if not line:
                            current_event = None
                            continue
                        if line.startswith('event: '):
                            current_event = line[len('event: '):].strip()
                            continue
                        if not line.startswith('data: '):
                            continue
                        payload_str = line[len('data: '):].strip()
                        if not payload_str:
                            continue
                        try:
                            obj = json.loads(payload_str)
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(obj, dict):
                            continue

                        ev = current_event or obj.get('type')
                        if ev == 'message_start':
                            msg = obj.get('message') or {}
                            mu = msg.get('usage') or {}
                            if isinstance(mu, dict):
                                # H3.6 — copy native usage keys (incl. the
                                # cache buckets) verbatim so message_stop can
                                # surface them. message_start carries the
                                # input + cache counts; output may be 0 here.
                                for _k in ('input_tokens', 'output_tokens',
                                           'cache_read_input_tokens', 'cache_creation_input_tokens'):
                                    if mu.get(_k) is not None:
                                        usage_partial[_k] = int(mu.get(_k) or 0)
                        elif ev == 'content_block_start':
                            idx = obj.get('index', 0)
                            block = obj.get('content_block') or {}
                            tcd = assembler.ingest_start(int(idx), block)
                            if tcd is not None:
                                yield LlmStreamEvent.make_tool_call_delta(tcd)
                        elif ev == 'content_block_delta':
                            idx = obj.get('index', 0)
                            delta = obj.get('delta') or {}
                            text_piece, tcd, thinking_piece = assembler.ingest_delta(int(idx), delta)
                            if text_piece:
                                yield LlmStreamEvent.make_delta(text_piece)
                            if thinking_piece:
                                yield LlmStreamEvent.make_thinking(thinking_piece)
                            if tcd is not None:
                                yield LlmStreamEvent.make_tool_call_delta(tcd)
                        elif ev == 'content_block_stop':
                            idx = obj.get('index', 0)
                            tc = assembler.finalise_block(int(idx))
                            if tc is not None:
                                yield LlmStreamEvent.make_tool_call(tc)
                        elif ev == 'message_delta':
                            # Carries running usage updates.
                            u_obj = obj.get('usage') or {}
                            if isinstance(u_obj, dict):
                                for _k in ('input_tokens', 'output_tokens',
                                           'cache_read_input_tokens', 'cache_creation_input_tokens'):
                                    if _k in u_obj:
                                        usage_partial[_k] = int(u_obj.get(_k) or 0)
                        elif ev == 'message_stop':
                            usage = _usage_from_anthropic(usage_partial)
                            if usage:
                                yield LlmStreamEvent.make_usage(usage)
                            yield LlmStreamEvent.make_done(ChatResponse(
                                content=assembler.text_accum(),
                                tool_calls=[],
                                usage=usage,
                                thinking_blocks=assembler.thinking_blocks() or None,
                            ))
                            return
                        elif ev == 'error':
                            err = (obj.get('error') or {}).get('message') or 'unknown error'
                            yield LlmStreamEvent.make_error(f'Anthropic stream error: {err}')
                            return

            # Stream ended without message_stop — emit a
            # graceful done with whatever accumulated.
            usage = _usage_from_anthropic(usage_partial)
            if usage:
                yield LlmStreamEvent.make_usage(usage)
            yield LlmStreamEvent.make_done(ChatResponse(
                content=assembler.text_accum(),
                tool_calls=[],
                usage=usage,
                thinking_blocks=assembler.thinking_blocks() or None,
            ))

        except httpx.ConnectError as e:
            yield LlmStreamEvent.make_error(f'Cannot connect to {self.base_url}: {e!r}')
        except httpx.HTTPStatusError as e:
            yield LlmStreamEvent.make_error(
                f'Anthropic HTTP error during stream: {e.response.status_code}'
            )
        except Exception as e:
            yield LlmStreamEvent.make_error(f'Anthropic stream error: {e!r}')
