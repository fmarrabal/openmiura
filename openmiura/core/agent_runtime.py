from __future__ import annotations

import json
from typing import Any

try:
    from openmiura.agents.skills import SkillLoader
except Exception:  # pragma: no cover
    SkillLoader = None  # type: ignore

from openmiura.tools.runtime import ToolConfirmationRequired
from openmiura.observability import record_error, record_tokens

from .audit import AuditStore
from .config import Settings, resolve_config_related_path
from .llm import AnthropicClient, OllamaClient, OpenAICompatibleClient

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
            messages.append({'role': 'user', 'content': user_text})

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
    ) -> str:
        import time

        start_ts = time.perf_counter()
        messages = self._build_messages(
            agent_id=agent_id,
            session_id=session_id,
            user_text=user_text,
            extra_system=extra_system,
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
                record_tokens(getattr(self.llm, 'model', self.settings.llm.model), **usage)
                if trace_collector is not None:
                    target = trace_collector.setdefault('usage', {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0})
                    target['prompt_tokens'] = int(target.get('prompt_tokens', 0) + int(usage.get('prompt_tokens') or 0))
                    target['completion_tokens'] = int(target.get('completion_tokens', 0) + int(usage.get('completion_tokens') or 0))
                    total = int(usage.get('total_tokens') or (int(usage.get('prompt_tokens') or 0) + int(usage.get('completion_tokens') or 0)))
                    target['total_tokens'] = int(target.get('total_tokens', 0) + total)

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
