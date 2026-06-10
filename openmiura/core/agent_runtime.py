from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator, Callable

try:
    from openmiura.agents.skills import SkillLoader
except Exception:  # pragma: no cover
    SkillLoader = None  # type: ignore

from openmiura.tools.runtime import ToolConfirmationRequired
from openmiura.observability import record_cost, record_error, record_tokens

from .audit import AuditStore
from .config import Settings, resolve_config_related_path
from .llm import AnthropicClient, OllamaClient, OpenAICompatibleClient
from .llm.pricing import estimate_cost
from .llm.types import (
    ChatResponse,
    LlmStreamEvent,
    ToolCall,
    ToolResult,
)

_MAX_EXTRA_SYSTEM_CHARS = 3000
_MAX_TOOL_ROUNDS = 3


class AgentRuntime:
    def __init__(self, settings: Settings, audit: AuditStore):
        self.settings = settings
        self.audit = audit
        self.llm = self._build_llm_client(settings)

        skills_path = resolve_config_related_path(
            getattr(settings, 'config_path', None),
            getattr(settings, 'skills_path', '../skills'),
            default_path='../skills',
        ).as_posix()
        self.skills_path = skills_path
        if SkillLoader is not None:
            self.skill_loader = SkillLoader(skills_path)
            try:
                self.skill_loader.load_all()
            except Exception:
                pass
        else:
            self.skill_loader = None

    def _build_llm_client(self, settings: Settings):
        provider = str(settings.llm.provider or 'ollama').strip().lower()
        if provider == 'ollama':
            return OllamaClient(
                base_url=settings.llm.base_url,
                model=settings.llm.model,
                timeout_s=settings.llm.timeout_s,
            )
        if provider in {'openai', 'kimi'}:
            return OpenAICompatibleClient(
                base_url=settings.llm.base_url,
                model=settings.llm.model,
                api_key_env_var=settings.llm.api_key_env_var,
                timeout_s=settings.llm.timeout_s,
            )
        if provider == 'anthropic':
            return AnthropicClient(
                base_url=settings.llm.base_url,
                model=settings.llm.model,
                api_key_env_var=settings.llm.api_key_env_var,
                anthropic_version=settings.llm.anthropic_version,
                max_output_tokens=settings.llm.max_output_tokens,
                # H3.4/H3.8 — extended thinking is config-driven;
                # getattr keeps older Settings doubles working.
                thinking_budget_tokens=getattr(settings.llm, 'thinking_budget_tokens', 0),
                timeout_s=settings.llm.timeout_s,
            )
        raise ValueError(f'Unsupported LLM provider: {settings.llm.provider}')

    def _agent_cfg(self, agent_id: str) -> dict[str, Any]:
        base = dict((self.settings.agents.get(agent_id, {}) or {}))
        if self.skill_loader is not None:
            try:
                return self.skill_loader.extend_agent_config(base)
            except Exception:
                return base
        return base

    def _build_messages(
        self,
        agent_id: str,
        session_id: str,
        user_text: str,
        extra_system: str | None = None,
        attachments: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        agent_cfg = self._agent_cfg(agent_id)
        system_prompt = agent_cfg.get('system_prompt', 'You are openMiura.')

        if extra_system:
            extra = extra_system.strip()
            if len(extra) > _MAX_EXTRA_SYSTEM_CHARS:
                extra = extra[:_MAX_EXTRA_SYSTEM_CHARS] + '\n...(truncated)'
            system_prompt = system_prompt.rstrip() + '\n\n' + extra

        messages: list[dict[str, Any]] = [
            {'role': 'system', 'content': system_prompt}
        ]

        history = self.audit.get_recent_messages(
            session_id=session_id,
            limit=self.settings.runtime.history_limit,
        )
        for role, content in history:
            if role not in ('user', 'assistant', 'system', 'tool'):
                role = 'user'
            messages.append({'role': role, 'content': content})

        if (
            not messages
            or messages[-1]['role'] != 'user'
            or messages[-1]['content'] != user_text
        ):
            user_msg: dict[str, Any] = {'role': 'user', 'content': user_text}
            # H3.3c — attach the multi-modal blobs to the live
            # user turn only. History is text-only (we don't
            # round-trip bytes through the audit DB), so
            # attachments don't leak into prior turns. The
            # per-provider translators in ``openmiura.core.llm.*``
            # know how to lift this into their wire shape (Ollama
            # ``images: []``, OpenAI ``image_url`` blocks,
            # Anthropic ``image source`` blocks).
            if attachments:
                user_msg['attachments'] = attachments
            messages.append(user_msg)

        return messages

    def generate_reply(
        self,
        agent_id: str,
        session_id: str,
        user_text: str,
        extra_system: str | None = None,
        *,
        tools_runtime=None,
        user_key: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        channel: str | None = None,
        trace_collector: dict[str, Any] | None = None,
        attachments: list[dict[str, Any]] | None = None,
    ) -> str:
        import time

        start_ts = time.perf_counter()
        messages = self._build_messages(
            agent_id=agent_id,
            session_id=session_id,
            user_text=user_text,
            extra_system=extra_system,
            attachments=attachments,
        )

        agent_cfg = self._agent_cfg(agent_id)

        had_model_attr = hasattr(self.llm, 'model')
        original_model = getattr(self.llm, 'model', None)
        agent_model = str(agent_cfg.get('model') or '').strip()
        if agent_model and had_model_attr:
            self.llm.model = agent_model

        if trace_collector is not None:
            trace_collector.setdefault('llm_calls', [])
            trace_collector.setdefault('tools_considered', [])
            trace_collector.setdefault('policies_applied', [])
            trace_collector.setdefault('tools_used', [])
            trace_collector['provider'] = str(getattr(self.settings.llm, 'provider', '') or '')
            trace_collector['model'] = str(agent_model or getattr(self.llm, 'model', self.settings.llm.model) or '')
            trace_collector['request_text'] = user_text
            trace_collector['context'] = {
                'session_id': session_id,
                'history_messages': max(0, len(messages) - 2),
                'extra_system_chars': len((extra_system or '').strip()),
                'channel': channel or '',
                'tenant_id': tenant_id,
                'workspace_id': workspace_id,
                'environment': environment,
            }
            trace_collector['decisions'] = {'tool_rounds': 0}
            trace_collector['usage'] = {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}

        tool_schemas: list[dict[str, Any]] = []
        if tools_runtime is not None and user_key:
            try:
                tool_schemas = tools_runtime.available_tool_schemas(
                    agent_id,
                    user_key=user_key,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    environment=environment,
                    channel=channel,
                    trace_collector=trace_collector,
                )
            except TypeError:
                try:
                    tool_schemas = tools_runtime.available_tool_schemas(agent_id, user_key=user_key)
                except TypeError:
                    try:
                        tool_schemas = tools_runtime.available_tool_schemas(agent_id)
                    except Exception:
                        tool_schemas = []
                except Exception:
                    tool_schemas = []
            except Exception:
                tool_schemas = []

        def _record_usage(result_obj: Any) -> None:
            usage = getattr(result_obj, 'usage', None) or {}
            if usage:
                model_name = getattr(self.llm, 'model', self.settings.llm.model)
                try:
                    # Explicit kwargs (NOT **usage): H3.6 may add
                    # cache_read/cache_write keys that record_tokens
                    # doesn't accept, which would raise on **usage.
                    record_tokens(
                        model_name,
                        prompt_tokens=usage.get('prompt_tokens'),
                        completion_tokens=usage.get('completion_tokens'),
                        total_tokens=usage.get('total_tokens'),
                    )
                    # H3.9 — estimate + record USD cost and any
                    # prompt-cache tokens so the synchronous
                    # /http/message path feeds /http/budget just like
                    # the streaming path does.
                    breakdown = estimate_cost(model_name, usage)
                    record_cost(
                        model_name,
                        cost_usd=breakdown.get('total_usd'),
                        cache_read_tokens=usage.get('cache_read_tokens'),
                        cache_write_tokens=usage.get('cache_write_tokens'),
                    )
                except Exception:
                    pass
                if trace_collector is not None:
                    target = trace_collector.setdefault('usage', {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0})
                    target['prompt_tokens'] = int(target.get('prompt_tokens', 0) + int(usage.get('prompt_tokens') or 0))
                    target['completion_tokens'] = int(target.get('completion_tokens', 0) + int(usage.get('completion_tokens') or 0))
                    total = int(usage.get('total_tokens') or (int(usage.get('prompt_tokens') or 0) + int(usage.get('completion_tokens') or 0)))
                    target['total_tokens'] = int(target.get('total_tokens', 0) + total)
                    # H3.10 — carry cache tokens so the decision-trace
                    # cost estimate reflects the cache discount (the
                    # persisted input/output/total columns are unchanged).
                    cr = int(usage.get('cache_read_tokens') or 0)
                    cw = int(usage.get('cache_write_tokens') or 0)
                    if cr:
                        target['cache_read_tokens'] = int(target.get('cache_read_tokens', 0) + cr)
                    if cw:
                        target['cache_write_tokens'] = int(target.get('cache_write_tokens', 0) + cw)

        def _chat_with_trace(messages_payload, *, tools=None):
            llm_t0 = time.perf_counter()
            result_obj = self.llm.chat(messages_payload, tools=tools) if tools is not None else self.llm.chat(messages_payload)
            _record_usage(result_obj)
            if trace_collector is not None:
                trace_collector.setdefault('llm_calls', []).append(
                    {
                        'latency_ms': round((time.perf_counter() - llm_t0) * 1000.0, 3),
                        'tool_calls_requested': [
                            {'name': tc.name, 'arguments': tc.arguments, 'id': tc.id}
                            for tc in (getattr(result_obj, 'tool_calls', None) or [])
                        ],
                        'usage': dict(getattr(result_obj, 'usage', None) or {}),
                        'content_excerpt': str(getattr(result_obj, 'content', '') or '')[:240],
                    }
                )
            return result_obj

        try:
            if tool_schemas and tools_runtime is not None and user_key:
                result = _chat_with_trace(messages, tools=tool_schemas)
            else:
                result = _chat_with_trace(messages)

            rounds = 0
            while getattr(result, 'tool_calls', None) and rounds < _MAX_TOOL_ROUNDS:
                rounds += 1
                if trace_collector is not None:
                    trace_collector.setdefault('decisions', {})['tool_rounds'] = rounds

                messages.append(
                    {
                        'role': 'assistant',
                        'content': result.content or '',
                        'tool_calls': [
                            {
                                'id': tc.id,
                                'function': {
                                    'name': tc.name,
                                    'arguments': json.dumps(tc.arguments, ensure_ascii=False),
                                }
                            }
                            for tc in result.tool_calls
                        ],
                    }
                )

                for tc in result.tool_calls:
                    try:
                        tool_output = tools_runtime.run_tool(
                            agent_id=agent_id,
                            session_id=session_id,
                            user_key=user_key,
                            tool_name=tc.name,
                            args=tc.arguments or {},
                            tenant_id=tenant_id,
                            workspace_id=workspace_id,
                            environment=environment,
                            channel=channel,
                            trace_collector=trace_collector,
                        )
                    except TypeError:
                        try:
                            tool_output = tools_runtime.run_tool(
                                agent_id=agent_id,
                                session_id=session_id,
                                user_key=user_key,
                                tool_name=tc.name,
                                args=tc.arguments or {},
                            )
                        except ToolConfirmationRequired as e:
                            tool_output = str(e)
                        except Exception as e:
                            record_error(type(e).__name__)
                            tool_output = f'Tool {tc.name} failed: {e!r}'
                    except ToolConfirmationRequired as e:
                        tool_output = str(e)
                    except Exception as e:
                        record_error(type(e).__name__)
                        tool_output = f'Tool {tc.name} failed: {e!r}'

                    messages.append(
                        {
                            'role': 'tool',
                            'name': tc.name,
                            'content': tool_output,
                        }
                    )

                result = _chat_with_trace(messages, tools=tool_schemas)

            final = (result.content or '').strip()
            if trace_collector is not None:
                trace_collector['response_text'] = final if final else '(empty response)'
                trace_collector['latency_ms'] = round((time.perf_counter() - start_ts) * 1000.0, 3)
                trace_collector['status'] = 'completed'
                trace_collector.setdefault('decisions', {})['tool_round_limit_reached'] = bool(getattr(result, 'tool_calls', None) and rounds >= _MAX_TOOL_ROUNDS)
            return final if final else '(empty response)'
        finally:
            if had_model_attr:
                self.llm.model = original_model

    # ------------------------------------------------------------------
    # H1.4 — Async streaming reply with tool loop
    # ------------------------------------------------------------------

    def supports_streaming(self) -> bool:
        """Whether the underlying LLM client exposes a
        ``chat_stream`` method (i.e. native streaming is
        available end-to-end). Consumers (the HTTP SSE
        endpoint) should call this to decide whether to flip
        ``streaming_mode`` to ``"native"`` or fall back to
        the pseudo path."""
        return callable(getattr(self.llm, 'chat_stream', None))

    async def generate_reply_stream(
        self,
        agent_id: str,
        session_id: str,
        user_text: str,
        extra_system: str | None = None,
        *,
        tools_runtime=None,
        user_key: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        channel: str | None = None,
        attachments: list[dict[str, Any]] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> AsyncIterator[LlmStreamEvent]:
        """Async-generator sibling of ``generate_reply``.

        Streams ``LlmStreamEvent``s through the full tool loop:

          1. Build the same message list as the sync path.
          2. Open an LLM stream (``llm.chat_stream``).
          3. Forward delta / tool_call / usage events to the
             caller as they arrive.
          4. When the LLM's per-round stream finishes
             (``kind="done"``) AND yielded tool calls, execute
             those tools in a threadpool (so we don't block
             the event loop), emit a ``tool_result`` event
             per tool, append tool messages to the
             conversation, and re-open the LLM stream.
          5. Repeat until the LLM round finishes with no tool
             calls, or ``_MAX_TOOL_ROUNDS`` is hit.
          6. Emit a final ``kind="done"`` event with the
             concatenated ChatResponse.

        Raises ``RuntimeError`` if the configured LLM client
        does not expose a ``chat_stream`` method — the SSE
        endpoint catches this and falls back to the
        pseudo-streaming path.

        Errors at LLM level surface as ``kind="error"``
        events; tool execution failures surface as
        ``tool_result`` events with the ``error`` field set
        (the loop continues so the LLM can recover).

        H3.5 — cooperative cancellation. ``cancel_check`` is an
        optional zero-arg predicate; when it returns truthy the
        generator stops at the next checkpoint (between LLM
        rounds and between streamed events), emits a single
        terminal ``kind="cancelled"`` event and returns — no
        ``done`` follows. This is *cooperative*: it fires at
        event boundaries, not mid-token, so a stalled upstream
        read is interrupted only when its next chunk arrives
        (or when the whole task is cancelled by the transport
        on client disconnect). The check is cheap and is only
        consulted when supplied, so existing callers that omit
        it see no behaviour change.
        """
        if not self.supports_streaming():
            raise RuntimeError(
                "Configured LLM client does not support chat_stream; "
                "use generate_reply (sync) instead."
            )

        messages = self._build_messages(
            agent_id=agent_id,
            session_id=session_id,
            user_text=user_text,
            extra_system=extra_system,
            attachments=attachments,
        )
        agent_cfg = self._agent_cfg(agent_id)

        had_model_attr = hasattr(self.llm, 'model')
        original_model = getattr(self.llm, 'model', None)
        agent_model = str(agent_cfg.get('model') or '').strip()
        if agent_model and had_model_attr:
            self.llm.model = agent_model

        # Tool schemas (reuse the same fallback chain as the
        # sync path so a misbehaving tools_runtime doesn't
        # break the stream).
        tool_schemas: list[dict[str, Any]] = []
        if tools_runtime is not None and user_key:
            try:
                tool_schemas = tools_runtime.available_tool_schemas(
                    agent_id,
                    user_key=user_key,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    environment=environment,
                    channel=channel,
                )
            except TypeError:
                try:
                    tool_schemas = tools_runtime.available_tool_schemas(agent_id, user_key=user_key)
                except TypeError:
                    try:
                        tool_schemas = tools_runtime.available_tool_schemas(agent_id)
                    except Exception:
                        tool_schemas = []
                except Exception:
                    tool_schemas = []
            except Exception:
                tool_schemas = []

        content_accum = ''
        usage_accum = {
            'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0,
            'cache_read_tokens': 0, 'cache_write_tokens': 0,
        }
        loop = asyncio.get_running_loop()

        def _should_cancel() -> bool:
            # H3.5 — consult the caller's cancel predicate, if any.
            # Defensive: a predicate that raises must not crash the
            # stream, so swallow and treat as "not cancelled".
            if cancel_check is None:
                return False
            try:
                return bool(cancel_check())
            except Exception:
                return False

        try:
            rounds = 0
            while True:
                # H3.5 — cancel between rounds, before opening a
                # new (potentially expensive) LLM round.
                if _should_cancel():
                    yield LlmStreamEvent.make_cancelled()
                    return
                # Open a stream for this round.
                stream = (
                    self.llm.chat_stream(messages, tools=tool_schemas)
                    if tool_schemas else
                    self.llm.chat_stream(messages)
                )

                round_tool_calls: list[ToolCall] = []
                round_content = ''
                round_thinking_blocks: list[dict[str, Any]] | None = None
                stream_failed = False

                async for ev in stream:
                    # H3.5 — cancel between streamed events. The
                    # partial content_accum so far is preserved by
                    # the transport layer for the audit trail.
                    if _should_cancel():
                        yield LlmStreamEvent.make_cancelled()
                        return
                    if ev.kind == "delta":
                        round_content += ev.delta or ''
                        content_accum += ev.delta or ''
                        yield ev
                    elif ev.kind == "tool_call" and ev.tool_call is not None:
                        round_tool_calls.append(ev.tool_call)
                        yield ev
                    elif ev.kind == "tool_call_delta" and ev.tool_call_delta is not None:
                        # H3.2 — incremental tool-argument fragment.
                        # Pure visibility: forward as-is, never
                        # accumulate into round_tool_calls (the
                        # complete tool_call event does that).
                        yield ev
                    elif ev.kind == "thinking" and ev.thinking is not None:
                        # H3.4 — extended-thinking fragment. Pure
                        # visibility: forward as-is; never folded
                        # into round_content or content_accum (it
                        # is the model's private reasoning, not the
                        # assistant answer the audit trail records).
                        yield ev
                    elif ev.kind == "usage" and ev.usage:
                        # Accumulate across rounds — emit at the
                        # end as one consolidated usage event.
                        for k in ('prompt_tokens', 'completion_tokens', 'total_tokens',
                                  'cache_read_tokens', 'cache_write_tokens'):
                            usage_accum[k] += int(ev.usage.get(k) or 0)
                        try:
                            model_name = getattr(self.llm, 'model', self.settings.llm.model)
                            record_tokens(
                                model_name,
                                prompt_tokens=ev.usage.get('prompt_tokens'),
                                completion_tokens=ev.usage.get('completion_tokens'),
                                total_tokens=ev.usage.get('total_tokens'),
                            )
                            # H3.6 — estimate + record USD cost and any
                            # prompt-cache tokens for this round's usage.
                            breakdown = estimate_cost(model_name, ev.usage)
                            record_cost(
                                model_name,
                                cost_usd=breakdown.get('total_usd'),
                                cache_read_tokens=ev.usage.get('cache_read_tokens'),
                                cache_write_tokens=ev.usage.get('cache_write_tokens'),
                            )
                        except Exception:
                            pass
                        # Don't forward intermediate usage events —
                        # the consumer gets one rolled-up usage at
                        # the end.
                    elif ev.kind == "error":
                        yield ev
                        stream_failed = True
                        break
                    elif ev.kind == "done":
                        # End of this round. H3.8 — capture any signed
                        # thinking blocks so they can be echoed back in
                        # the assistant turn that precedes the tool_result.
                        if ev.final is not None:
                            round_thinking_blocks = getattr(ev.final, 'thinking_blocks', None)
                        break

                if stream_failed:
                    return

                # No tool calls → we're done with the whole
                # interaction.
                if not round_tool_calls:
                    break

                rounds += 1
                if rounds > _MAX_TOOL_ROUNDS:
                    # Same behaviour as sync path: we stop
                    # looping but DON'T treat this as an error
                    # — the partial content is the best we
                    # have. Emit a marker tool_result.
                    yield LlmStreamEvent.make_tool_result(
                        ToolResult(
                            name='_loop_limit',
                            output=(
                                f'Tool-call loop limit ({_MAX_TOOL_ROUNDS}) '
                                f'reached; further calls dropped.'
                            ),
                            call_id=None,
                            error='tool_round_limit',
                        )
                    )
                    break

                # Append assistant turn with the tool calls to
                # the conversation.
                assistant_turn: dict[str, Any] = {
                    'role':    'assistant',
                    'content': round_content,
                    'tool_calls': [
                        {
                            'id':       tc.id,
                            'function': {
                                'name':      tc.name,
                                'arguments': json.dumps(tc.arguments, ensure_ascii=False),
                            },
                        }
                        for tc in round_tool_calls
                    ],
                }
                # H3.8 — carry the signed thinking blocks (Anthropic)
                # so _convert_messages can echo them back ahead of the
                # tool_use on the next round. Other providers ignore it.
                if round_thinking_blocks:
                    assistant_turn['_thinking_blocks'] = round_thinking_blocks
                messages.append(assistant_turn)

                # H3.1 — Execute all tool calls in the round
                # concurrently via ``asyncio.gather`` so a round
                # with 3 tools that each take 2 s completes in
                # ~2 s instead of 6 s.
                #
                # ``asyncio.gather`` preserves INPUT order in its
                # returned list, so the audit + UI streams still
                # see deterministic ordering (matches the
                # request order, not the completion order). The
                # legacy ``test_multiple_parallel_tool_calls_in_one_round``
                # test pins this contract.
                async def _execute_tool(
                    tc=None,  # captured per-task below
                ) -> tuple[ToolCall, str, str | None]:
                    """Run one tool, return (tc, output, error_msg).
                    Never raises — wraps every exception as the
                    error_msg field so ``gather`` doesn't abort
                    sibling tasks."""
                    assert tc is not None
                    if tools_runtime is None or not user_key:
                        msg = 'No tools_runtime / user_key configured'
                        return tc, msg, msg
                    def _run():
                        return tools_runtime.run_tool(
                            agent_id=agent_id,
                            session_id=session_id,
                            user_key=user_key,
                            tool_name=tc.name,
                            args=tc.arguments or {},
                            tenant_id=tenant_id,
                            workspace_id=workspace_id,
                            environment=environment,
                            channel=channel,
                        )
                    def _run_legacy():
                        return tools_runtime.run_tool(
                            agent_id=agent_id,
                            session_id=session_id,
                            user_key=user_key,
                            tool_name=tc.name,
                            args=tc.arguments or {},
                        )
                    try:
                        out = await loop.run_in_executor(None, _run)
                        return tc, str(out), None
                    except TypeError:
                        try:
                            out = await loop.run_in_executor(None, _run_legacy)
                            return tc, str(out), None
                        except ToolConfirmationRequired as e:
                            return tc, str(e), None
                        except Exception as e:
                            record_error(type(e).__name__)
                            return tc, f'Tool {tc.name} failed: {e!r}', f'{type(e).__name__}: {e!r}'
                    except ToolConfirmationRequired as e:
                        return tc, str(e), None
                    except Exception as e:
                        record_error(type(e).__name__)
                        return tc, f'Tool {tc.name} failed: {e!r}', f'{type(e).__name__}: {e!r}'

                results = await asyncio.gather(
                    *[_execute_tool(tc=tc) for tc in round_tool_calls]
                )
                for tc, output, error_msg in results:
                    yield LlmStreamEvent.make_tool_result(
                        ToolResult(
                            name=tc.name,
                            output=str(output),
                            call_id=tc.id,
                            error=error_msg,
                        )
                    )
                    messages.append({
                        'role':    'tool',
                        'name':    tc.name,
                        'content': str(output),
                    })

            # End of all rounds — emit consolidated usage + done.
            # H3.6 — keep the canonical 3-key shape unless prompt
            # caching actually happened, so consumers/tests that pin
            # {prompt,completion,total} are unaffected.
            consolidated_usage = {
                'prompt_tokens':     usage_accum['prompt_tokens'],
                'completion_tokens': usage_accum['completion_tokens'],
                'total_tokens':      usage_accum['total_tokens'],
            }
            if usage_accum['cache_read_tokens'] > 0:
                consolidated_usage['cache_read_tokens'] = usage_accum['cache_read_tokens']
            if usage_accum['cache_write_tokens'] > 0:
                consolidated_usage['cache_write_tokens'] = usage_accum['cache_write_tokens']
            if usage_accum['total_tokens'] > 0:
                # H3.7 — attach the estimated USD cost breakdown so
                # the UI can surface per-turn spend. The token dict
                # shape is untouched; cost rides alongside it.
                resolved_model = getattr(self.llm, 'model', self.settings.llm.model)
                yield LlmStreamEvent.make_usage(
                    dict(consolidated_usage),
                    cost=estimate_cost(resolved_model, consolidated_usage),
                )
            final = ChatResponse(
                content=(content_accum or '').strip() or '(empty response)',
                tool_calls=[],
                usage=dict(consolidated_usage) if usage_accum['total_tokens'] > 0 else None,
            )
            yield LlmStreamEvent.make_done(final)

        finally:
            if had_model_attr:
                self.llm.model = original_model
