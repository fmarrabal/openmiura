"""openmiura.application.admin.service._secrets_mixin

Part of the AdminService split. Methods originally lived on
``openmiura.application.admin.service.AdminService``; they have been
moved verbatim into this mixin so that no individual file in the
package exceeds the project's ``max 1,500 lines`` ceiling. The
public class still inherits from this mixin and exposes every
method unchanged.

The module-level ``AdminService = None`` sentinel is rebound by
``service/__init__.py`` once the final class is defined; this lets
the mixin's ``@staticmethod`` call sites that reference
``AdminService.foo(...)`` resolve correctly at call time without
introducing a circular import.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from openmiura.application.admin.status_snapshot import (
    build_status_snapshot,
    collect_registered_tool_names,
)
from openmiura.application.canvas import LiveCanvasService
from openmiura.application.costs import CostGovernanceService
from openmiura.application.evaluations import EvaluationService
from openmiura.application.memory import MemoryService
from openmiura.application.operator import OperatorConsoleService
from openmiura.application.packaging import PackagingHardeningService
from openmiura.application.pwa import PWAFoundationService
from openmiura.application.releases import ReleaseService
from openmiura.application.replay import ReplayService
from openmiura.application.runtime_adapters.external import (
    OpenClawAdapterService,
    OpenClawRecoverySchedulerService,
)
from openmiura.application.secrets import SecretGovernanceService
from openmiura.application.sessions import SessionService
from openmiura.application.tenancy import TenancyService
from openmiura.application.voice import VoiceRuntimeService
from openmiura import __version__
from openmiura.core.config import resolve_config_related_path
from openmiura.core.contracts import AdminGatewayLike
from openmiura.core.policies.engine import PolicyEngine


AdminService: type | None = None  # late-bound by service/__init__.py


class _AdminServiceSecretsMixin:
    """Mixin: secrets methods on AdminService."""

    def secret_governance_catalog(
        self,
        gw: AdminGatewayLike,
        *,
        q: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        return self.secret_governance_service.catalog(
            gw,
            q=q,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            limit=limit,
        )

    def secret_governance_usage(
        self,
        gw: AdminGatewayLike,
        *,
        q: str | None = None,
        ref: str | None = None,
        tool_name: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        return self.secret_governance_service.usage(
            gw,
            q=q,
            ref=ref,
            tool_name=tool_name,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            limit=limit,
        )

    def secret_governance_summary(
        self,
        gw: AdminGatewayLike,
        *,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        return self.secret_governance_service.summary(
            gw,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            limit=limit,
        )

    def secret_governance_timeline(
        self,
        gw: AdminGatewayLike,
        *,
        q: str | None = None,
        ref: str | None = None,
        tool_name: str | None = None,
        outcome: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        return self.secret_governance_service.timeline(
            gw,
            q=q,
            ref=ref,
            tool_name=tool_name,
            outcome=outcome,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            limit=limit,
        )

    def secret_governance_explain(
        self,
        gw: AdminGatewayLike,
        *,
        ref: str,
        tool_name: str,
        user_role: str = 'user',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        domain: str | None = None,
    ) -> dict[str, Any]:
        return self.secret_governance_service.explain_access(
            gw,
            ref=ref,
            tool_name=tool_name,
            user_role=user_role,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            domain=domain,
        )

    @staticmethod
    def _secret_env_profile_names() -> list[str]:
        return ['llm', 'telegram', 'slack', 'discord']

    @staticmethod
    def _secret_env_profile_title(profile: str) -> str:
        titles = {'llm': 'LLM provider', 'telegram': 'Telegram', 'slack': 'Slack', 'discord': 'Discord'}
        return titles.get(str(profile or '').strip().lower(), str(profile or '').strip().title() or 'Secret profile')

    def _normalize_secret_env_profile(self, profile: str) -> str:
        normalized = str(profile or '').strip().lower()
        if normalized not in self._secret_env_profile_names():
            raise ValueError('unsupported_secret_env_profile')
        return normalized

    def _secret_env_fields(self, profile: str) -> list[dict[str, Any]]:
        normalized = self._normalize_secret_env_profile(profile)
        if normalized == 'llm':
            return [
                {'group': 'Provider authentication', 'name': 'llm.api_key_env_var.mode', 'label': 'API key source', 'type': 'select', 'options': ['disabled', 'env']},
                {'group': 'Provider authentication', 'name': 'llm.api_key_env_var.value', 'label': 'API key env var', 'type': 'string', 'placeholder': 'OPENMIURA_LLM_API_KEY'},
            ]
        if normalized == 'telegram':
            return [
                {'group': 'Authentication', 'name': 'telegram.bot_token.mode', 'label': 'Bot token source', 'type': 'select', 'options': ['disabled', 'env', 'literal']},
                {'group': 'Authentication', 'name': 'telegram.bot_token.value', 'label': 'Bot token / env var', 'type': 'string', 'placeholder': 'OPENMIURA_TELEGRAM_BOT_TOKEN'},
                {'group': 'Authentication', 'name': 'telegram.webhook_secret.mode', 'label': 'Webhook secret source', 'type': 'select', 'options': ['disabled', 'env', 'literal']},
                {'group': 'Authentication', 'name': 'telegram.webhook_secret.value', 'label': 'Webhook secret / env var', 'type': 'string', 'placeholder': 'OPENMIURA_TELEGRAM_WEBHOOK_SECRET'},
            ]
        if normalized == 'slack':
            return [
                {'group': 'Authentication', 'name': 'slack.bot_token.mode', 'label': 'Bot token source', 'type': 'select', 'options': ['disabled', 'env', 'literal']},
                {'group': 'Authentication', 'name': 'slack.bot_token.value', 'label': 'Bot token / env var', 'type': 'string', 'placeholder': 'OPENMIURA_SLACK_BOT_TOKEN'},
                {'group': 'Authentication', 'name': 'slack.signing_secret.mode', 'label': 'Signing secret source', 'type': 'select', 'options': ['disabled', 'env', 'literal']},
                {'group': 'Authentication', 'name': 'slack.signing_secret.value', 'label': 'Signing secret / env var', 'type': 'string', 'placeholder': 'OPENMIURA_SLACK_SIGNING_SECRET'},
            ]
        return [
            {'group': 'Authentication', 'name': 'discord.bot_token.mode', 'label': 'Bot token source', 'type': 'select', 'options': ['disabled', 'env', 'literal']},
            {'group': 'Authentication', 'name': 'discord.bot_token.value', 'label': 'Bot token / env var', 'type': 'string', 'placeholder': 'OPENMIURA_DISCORD_BOT_TOKEN'},
        ]

    def _secret_env_schema(self) -> dict[str, list[dict[str, Any]]]:
        output: dict[str, list[dict[str, Any]]] = {}
        for profile in self._secret_env_profile_names():
            groups: dict[str, list[dict[str, Any]]] = {}
            for field in self._secret_env_fields(profile):
                groups.setdefault(str(field['group']), []).append({k: v for k, v in field.items() if k != 'group'})
            output[profile] = [{'group': group, 'fields': fields} for group, fields in groups.items()]
        return output

    @staticmethod
    def _default_secret_env_name(field_path: str, env_prefix: str = 'OPENMIURA') -> str:
        prefix = str(env_prefix or 'OPENMIURA').strip().upper().replace('-', '_').replace(' ', '_')
        mapping = {
            'llm.api_key_env_var': 'LLM_API_KEY',
            'telegram.bot_token': 'TELEGRAM_BOT_TOKEN',
            'telegram.webhook_secret': 'TELEGRAM_WEBHOOK_SECRET',
            'slack.bot_token': 'SLACK_BOT_TOKEN',
            'slack.signing_secret': 'SLACK_SIGNING_SECRET',
            'discord.bot_token': 'DISCORD_BOT_TOKEN',
        }
        suffix = mapping.get(field_path, field_path.replace('.', '_').upper())
        return f'{prefix}_{suffix}' if prefix else suffix

    def _secret_env_suggestions(self, env_prefix: str = 'OPENMIURA') -> dict[str, dict[str, str]]:
        return {
            'llm': {'llm.api_key_env_var': self._default_secret_env_name('llm.api_key_env_var', env_prefix)},
            'telegram': {
                'telegram.bot_token': self._default_secret_env_name('telegram.bot_token', env_prefix),
                'telegram.webhook_secret': self._default_secret_env_name('telegram.webhook_secret', env_prefix),
            },
            'slack': {
                'slack.bot_token': self._default_secret_env_name('slack.bot_token', env_prefix),
                'slack.signing_secret': self._default_secret_env_name('slack.signing_secret', env_prefix),
            },
            'discord': {'discord.bot_token': self._default_secret_env_name('discord.bot_token', env_prefix)},
        }

    def _extract_secret_env_values(self, parsed: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
        payload = parsed if isinstance(parsed, dict) else {}
        defaults: dict[str, dict[str, Any]] = {
            'llm': {
                'llm.api_key_env_var.mode': 'disabled',
                'llm.api_key_env_var.value': '',
            },
            'telegram': {
                'telegram.bot_token.mode': 'disabled',
                'telegram.bot_token.value': '',
                'telegram.webhook_secret.mode': 'disabled',
                'telegram.webhook_secret.value': '',
            },
            'slack': {
                'slack.bot_token.mode': 'disabled',
                'slack.bot_token.value': '',
                'slack.signing_secret.mode': 'disabled',
                'slack.signing_secret.value': '',
            },
            'discord': {
                'discord.bot_token.mode': 'disabled',
                'discord.bot_token.value': '',
            },
        }
        result = copy.deepcopy(defaults)
        for profile in self._secret_env_profile_names():
            values = result[profile]
            for field in self._secret_env_fields(profile):
                name = str(field['name'])
                if name.endswith('.mode') and name[:-5] in self._secret_storage_fields():
                    mode, _ = self._extract_secret_storage(self._config_get_path(payload, name[:-5], ''))
                    values[name] = mode
                    continue
                if name.endswith('.value') and name[:-6] in self._secret_storage_fields():
                    _, stored = self._extract_secret_storage(self._config_get_path(payload, name[:-6], ''))
                    values[name] = stored
                    continue
                if name.endswith('.mode') and name[:-5] in self._env_reference_fields():
                    mode, _ = self._extract_env_reference(self._config_get_path(payload, name[:-5], ''))
                    values[name] = mode
                    continue
                if name.endswith('.value') and name[:-6] in self._env_reference_fields():
                    _, stored = self._extract_env_reference(self._config_get_path(payload, name[:-6], ''))
                    values[name] = stored
                    continue
                values[name] = self._config_get_path(payload, name, copy.deepcopy(values.get(name)))
        return result

    @staticmethod
    def _coerce_secret_env_value(field_type: str, value: Any) -> Any:
        if field_type == 'bool':
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return bool(value)
            return str(value or '').strip().lower() in {'1', 'true', 'yes', 'on', 'y'}
        if field_type == 'int':
            try:
                return int(value)
            except Exception:
                return 0
        return str(value or '')

    def _apply_secret_env_values(
        self,
        base_payload: dict[str, Any],
        profile: str,
        wizard_payload: dict[str, Any],
        *,
        env_prefix: str = 'OPENMIURA',
    ) -> dict[str, Any]:
        normalized = self._normalize_secret_env_profile(profile)
        merged = copy.deepcopy(base_payload) if isinstance(base_payload, dict) else {}
        suggestions = self._secret_env_suggestions(env_prefix).get(normalized, {})
        for field in self._secret_env_fields(normalized):
            name = str(field['name'])
            if name.endswith('.mode') and name[:-5] in self._secret_storage_fields():
                secret_path = name[:-5]
                ref_value = wizard_payload.get(f'{secret_path}.value')
                if str(wizard_payload.get(name) or '').strip().lower() == 'env' and not str(ref_value or '').strip():
                    ref_value = suggestions.get(secret_path, '')
                composed = self._compose_secret_storage(wizard_payload.get(name), ref_value)
                self._config_set_path(merged, secret_path, composed)
                continue
            if name.endswith('.value') and name[:-6] in self._secret_storage_fields():
                continue
            if name.endswith('.mode') and name[:-5] in self._env_reference_fields():
                ref_path = name[:-5]
                ref_value = wizard_payload.get(f'{ref_path}.value')
                if str(wizard_payload.get(name) or '').strip().lower() == 'env' and not str(ref_value or '').strip():
                    ref_value = suggestions.get(ref_path, '')
                self._config_set_path(merged, ref_path, self._compose_env_reference(wizard_payload.get(name), ref_value))
                continue
            if name.endswith('.value') and name[:-6] in self._env_reference_fields():
                continue
            if name not in wizard_payload:
                continue
            value = self._coerce_secret_env_value(str(field.get('type') or 'string'), wizard_payload.get(name))
            self._config_set_path(merged, name, value)
        return merged

    def _materialize_secret_env_content(
        self,
        gw: AdminGatewayLike,
        *,
        profile: str,
        content: str,
        wizard_payload: dict[str, Any] | None = None,
        env_prefix: str = 'OPENMIURA',
    ) -> str:
        normalized = self._normalize_secret_env_profile(profile)
        base_raw = str(content or '')
        if not base_raw.strip():
            spec = self._config_section_spec(gw, 'openmiura')
            base_path = Path(spec['path'])
            if base_path.exists():
                base_raw = base_path.read_text(encoding='utf-8')
        base_payload = yaml.safe_load(base_raw) if str(base_raw or '').strip() else {}
        if base_payload is None:
            base_payload = {}
        if not isinstance(base_payload, dict):
            raise ValueError('secret_env_wizard_requires_mapping_yaml')
        if not wizard_payload:
            return yaml.safe_dump(base_payload, sort_keys=False, allow_unicode=True)
        merged = self._apply_secret_env_values(base_payload, normalized, wizard_payload, env_prefix=env_prefix)
        return yaml.safe_dump(merged, sort_keys=False, allow_unicode=True)

    def _secret_env_paths_for_profile(self, profile: str) -> list[str]:
        normalized = self._normalize_secret_env_profile(profile)
        if normalized == 'llm':
            return ['llm.api_key_env_var']
        if normalized == 'telegram':
            return ['telegram.bot_token', 'telegram.webhook_secret']
        if normalized == 'slack':
            return ['slack.bot_token', 'slack.signing_secret']
        return ['discord.bot_token']

    def _secret_env_profile_status(self, profile: str, values: dict[str, Any], *, env_prefix: str = 'OPENMIURA') -> dict[str, Any]:
        normalized = self._normalize_secret_env_profile(profile)
        paths = self._secret_env_paths_for_profile(normalized)
        suggestions = self._secret_env_suggestions(env_prefix).get(normalized, {})
        env_vars: list[str] = []
        env_fields = 0
        literal_fields = 0
        disabled_fields = 0
        for path in paths:
            mode_key = f'{path}.mode'
            value_key = f'{path}.value'
            mode = str(values.get(mode_key) or 'disabled').strip().lower()
            value = str(values.get(value_key) or '').strip()
            if mode == 'env':
                env_fields += 1
                env_vars.append(value or suggestions.get(path, ''))
            elif mode == 'literal':
                literal_fields += 1
            else:
                disabled_fields += 1
        env_lines = [f'{name}=' for name in env_vars if name]
        return {
            'configured': (env_fields + literal_fields) > 0,
            'profile': normalized,
            'env_prefix': str(env_prefix or 'OPENMIURA').strip() or 'OPENMIURA',
            'env_fields': env_fields,
            'literal_fields': literal_fields,
            'disabled_fields': disabled_fields,
            'env_vars': env_vars,
            'env_example': '\n'.join(env_lines),
            'suggestions': suggestions,
        }

    def secret_env_reference_wizard_snapshot(self, gw: AdminGatewayLike, *, env_prefix: str = 'OPENMIURA') -> dict[str, Any]:
        spec = self._config_section_spec(gw, 'openmiura')
        snapshot = self._read_config_snapshot(gw, spec)
        parsed = yaml.safe_load(snapshot.get('raw') or '') if str(snapshot.get('raw') or '').strip() else {}
        if parsed is None:
            parsed = {}
        if not isinstance(parsed, dict):
            parsed = {}
        values = self._extract_secret_env_values(parsed)
        profiles = []
        for name in self._secret_env_profile_names():
            profiles.append(
                {
                    'name': name,
                    'title': self._secret_env_profile_title(name),
                    'status': self._secret_env_profile_status(name, values.get(name) or {}, env_prefix=env_prefix),
                }
            )
        return {
            'ok': True,
            'path': self._display_path(spec['path']),
            'schemas': self._secret_env_schema(),
            'values': values,
            'profiles': profiles,
            'suggestions': self._secret_env_suggestions(env_prefix),
            'env_prefix': str(env_prefix or 'OPENMIURA').strip() or 'OPENMIURA',
            'raw': snapshot.get('raw') or '',
        }

    def validate_secret_env_references(
        self,
        gw: AdminGatewayLike,
        *,
        profile: str,
        wizard_payload: dict[str, Any] | None = None,
        content: str = '',
        env_prefix: str = 'OPENMIURA',
    ) -> dict[str, Any]:
        normalized_profile = self._normalize_secret_env_profile(profile)
        rendered_content = self._materialize_secret_env_content(
            gw,
            profile=normalized_profile,
            content=content,
            wizard_payload=wizard_payload,
            env_prefix=env_prefix,
        )
        parsed = yaml.safe_load(str(rendered_content or ''))
        warnings: list[str] = []
        if parsed is None:
            parsed = {}
            warnings.append('empty_yaml_document')
        if not isinstance(parsed, dict):
            raise ValueError('secret_env_wizard_requires_mapping_yaml')
        values = self._extract_secret_env_values(parsed)
        status = self._secret_env_profile_status(normalized_profile, values.get(normalized_profile) or {}, env_prefix=env_prefix)
        normalized_yaml = yaml.safe_dump(parsed, sort_keys=False, allow_unicode=True)
        return {
            'ok': True,
            'profile': normalized_profile,
            'path': str(self._config_section_spec(gw, 'openmiura')['path']),
            'warnings': warnings,
            'summary': self._build_config_file_summary('openmiura', parsed),
            'normalized_yaml': normalized_yaml,
            'wizard_schema': self._secret_env_schema().get(normalized_profile, []),
            'wizard_values': values.get(normalized_profile) or {},
            'profile_status': status,
            'env_prefix': str(env_prefix or 'OPENMIURA').strip() or 'OPENMIURA',
            'env_example': status.get('env_example') or '',
            'suggestions': self._secret_env_suggestions(env_prefix).get(normalized_profile, {}),
        }

    def save_secret_env_references(
        self,
        gw: AdminGatewayLike,
        *,
        profile: str,
        wizard_payload: dict[str, Any] | None = None,
        content: str = '',
        env_prefix: str = 'OPENMIURA',
        reload_after_save: bool = False,
        actor: str = 'admin',
    ) -> dict[str, Any]:
        validation = self.validate_secret_env_references(
            gw,
            profile=profile,
            wizard_payload=wizard_payload,
            content=content,
            env_prefix=env_prefix,
        )
        response = self.save_config_content(
            gw,
            section='openmiura',
            content=str(validation.get('normalized_yaml') or ''),
            reload_after_save=reload_after_save,
            actor=actor,
        )
        response['profile'] = validation['profile']
        response['secret_env_validation'] = validation
        response['profile_status'] = validation['profile_status']
        response['env_example'] = validation.get('env_example') or ''
        return response

    @staticmethod
    def _secret_storage_fields() -> set[str]:
        return {
            'telegram.bot_token',
            'telegram.webhook_secret',
            'slack.bot_token',
            'slack.signing_secret',
            'discord.bot_token',
        }

    @staticmethod
    def _extract_secret_storage(raw_value: Any) -> tuple[str, str]:
        if isinstance(raw_value, str):
            value = raw_value.strip()
            if value.startswith('env:'):
                env_name = value[4:].split('|', 1)[0].strip()
                return 'env', env_name
            if value:
                return 'literal', value
        return 'disabled', ''

    @staticmethod
    def _compose_secret_storage(mode: Any, value: Any) -> str:
        normalized_mode = str(mode or 'disabled').strip().lower()
        raw_value = str(value or '').strip()
        if normalized_mode == 'env':
            return f'env:{raw_value}' if raw_value else ''
        if normalized_mode == 'literal':
            return raw_value
        return ''

