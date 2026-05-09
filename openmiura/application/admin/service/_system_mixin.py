"""openmiura.application.admin.service._system_mixin

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


class _AdminServiceSystemMixin:
    """Mixin: system methods on AdminService."""

    def reload(self, gw: AdminGatewayLike) -> dict[str, Any]:
        reload_fn = getattr(gw, "reload_dynamic_configs", None)
        result = {"agents": {"changed": False, "agents": []}, "policies": {"changed": False}}
        if callable(reload_fn):
            try:
                maybe = reload_fn(force=True)
            except TypeError:
                maybe = reload_fn()
            if isinstance(maybe, dict):
                result.update(maybe)
        return {"ok": True, **result}

    def config_center_snapshot(self, gw: AdminGatewayLike) -> dict[str, Any]:
        config_path = self._gateway_config_path(gw)
        snapshots: dict[str, dict[str, Any]] = {}
        sections: list[dict[str, Any]] = []
        for spec in self._config_section_specs(gw, config_path):
            snapshot = self._read_config_snapshot(gw, spec)
            snapshots[spec['name']] = snapshot
            sections.append(
                {
                    'name': spec['name'],
                    'title': spec['title'],
                    'path': snapshot['path'],
                    'exists': snapshot['exists'],
                    'reload_supported': spec['reload_supported'],
                    'restart_required': spec['restart_required'],
                    'summary': snapshot['summary'],
                }
            )
        status = self.status_snapshot(gw)
        return {
            'ok': True,
            'config_path': self._display_path(config_path),
            'sections': sections,
            'files': snapshots,
            'quick_settings': self._config_quick_settings(status),
            'channel_wizard': self.channel_setup_wizard_snapshot(gw),
            'secret_env_wizard': self.secret_env_reference_wizard_snapshot(gw),
            'reload_assistant': self.reload_assistant_snapshot(gw),
        }

    def reload_assistant_snapshot(self, gw: AdminGatewayLike) -> dict[str, Any]:
        config_path = self._gateway_config_path(gw)
        sections: list[dict[str, Any]] = []
        for spec in self._config_section_specs(gw, config_path):
            snapshot = self._read_config_snapshot(gw, spec)
            sections.append(
                {
                    'name': spec['name'],
                    'title': spec['title'],
                    'path': snapshot['path'],
                    'exists': snapshot['exists'],
                    'valid': snapshot['valid'],
                    'parse_error': snapshot['parse_error'],
                    'reload_supported': bool(spec['reload_supported']),
                    'restart_required': bool(spec['restart_required']),
                    'summary': snapshot['summary'],
                    'metadata': snapshot.get('metadata') or {},
                }
            )
        hook = self._restart_hook_status()
        recent = self._recent_restart_requests(gw)
        operational_state = self._reload_assistant_operational_state(gw, config_path=config_path, sections=sections, recent_restart_requests=recent)
        return {
            'ok': True,
            'config_path': self._display_path(config_path),
            'sections': sections,
            'defaults': {
                'apply_live_reload': True,
                'request_restart': False,
                'execute_restart_hook': False,
            },
            'capabilities': {
                'live_reload_sections': [item['name'] for item in sections if item.get('reload_supported')],
                'restart_required_sections': [item['name'] for item in sections if item.get('restart_required')],
            },
            'restart_hook': hook,
            'operational_state': operational_state,
            'recent_restart_requests': recent,
            'pending_restart_requests': [item for item in recent if str(item.get('status') or '') in {'queued', 'hook_failed'}],
        }

    def apply_reload_assistant(
        self,
        gw: AdminGatewayLike,
        *,
        sections: list[str] | None = None,
        apply_live_reload: bool = False,
        request_restart: bool = False,
        execute_restart_hook: bool = False,
        actor: str = 'admin',
    ) -> dict[str, Any]:
        config_path = self._gateway_config_path(gw)
        specs = {spec['name']: spec for spec in self._config_section_specs(gw, config_path)}
        normalized_sections: list[str] = []
        for raw in list(sections or []):
            name = str(raw or '').strip().lower()
            if name and name in specs and name not in normalized_sections:
                normalized_sections.append(name)
        if not normalized_sections and not request_restart:
            raise ValueError('reload_assistant_requires_sections_or_restart')

        live_reload_sections = [name for name in normalized_sections if bool(specs[name]['reload_supported'])]
        restart_trigger_sections = [name for name in normalized_sections if bool(specs[name]['restart_required'])]
        live_reload_applied = False
        reload_result: dict[str, Any] | None = None
        if apply_live_reload and live_reload_sections:
            reload_result = self.reload(gw)
            live_reload_applied = True

        restart_required = bool(restart_trigger_sections)
        restart_requested = bool(request_restart or restart_required)
        hook_status = self._restart_hook_status()
        hook_result: dict[str, Any] | None = None
        restart_request: dict[str, Any] | None = None

        if restart_requested:
            request_id = str(uuid.uuid4())
            status = 'queued'
            if execute_restart_hook:
                if hook_status.get('configured'):
                    hook_result = self._execute_restart_hook(str(hook_status.get('command') or ''), cwd=config_path.parent)
                    status = 'executed' if hook_result.get('ok') else 'hook_failed'
                else:
                    hook_result = {
                        'configured': False,
                        'executed': False,
                        'ok': False,
                        'reason': 'restart_hook_not_configured',
                    }
                    status = 'queued'
            restart_request = {
                'request_id': request_id,
                'created_at': time.time(),
                'actor': str(actor or 'admin'),
                'sections': normalized_sections,
                'restart_required_sections': restart_trigger_sections,
                'live_reload_sections': live_reload_sections,
                'request_restart': bool(request_restart),
                'restart_required': restart_required,
                'execute_restart_hook': bool(execute_restart_hook),
                'status': status,
                'hook': hook_result,
            }
            try:
                gw.audit.log_event(
                    direction='system',
                    channel='system',
                    user_id=str(actor or 'admin'),
                    session_id='system',
                    payload={
                        'event': 'assistant_restart_request',
                        **restart_request,
                    },
                )
            except Exception:
                pass
        elif live_reload_applied:
            try:
                gw.audit.log_event(
                    direction='system',
                    channel='system',
                    user_id=str(actor or 'admin'),
                    session_id='system',
                    payload={
                        'event': 'assistant_reload_applied',
                        'sections': normalized_sections,
                        'live_reload_sections': live_reload_sections,
                        'actor': str(actor or 'admin'),
                    },
                )
            except Exception:
                pass

        return {
            'ok': True,
            'selected_sections': normalized_sections,
            'apply_live_reload': bool(apply_live_reload),
            'live_reload_sections': live_reload_sections,
            'live_reload_applied': live_reload_applied,
            'reload_result': reload_result,
            'request_restart': bool(request_restart),
            'restart_required': restart_required,
            'restart_request': restart_request,
            'restart_hook': hook_status,
            'hook_result': hook_result,
            'recent_restart_requests': self._recent_restart_requests(gw),
        }

    def save_config_content(
        self,
        gw: AdminGatewayLike,
        *,
        section: str,
        content: str,
        reload_after_save: bool = False,
        actor: str = 'admin',
        form_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        spec = self._config_section_spec(gw, section)
        validation = self.validate_config_content(gw, section=section, content=content, form_payload=form_payload)
        target_path = Path(spec['path'])
        target_path.parent.mkdir(parents=True, exist_ok=True)
        backup_path = None
        if target_path.exists():
            backup_root = self._config_backup_root(gw, self._gateway_config_path(gw))
            backup_root.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime('%Y%m%d-%H%M%S', time.gmtime())
            backup_name = f"{section}-{stamp}-{target_path.name}.bak"
            backup_path = backup_root / backup_name
            backup_path.write_text(target_path.read_text(encoding='utf-8'), encoding='utf-8')
        final_content = validation.get('normalized_yaml') or str(content or '')
        if final_content and not final_content.endswith('\n'):
            final_content += '\n'
        target_path.write_text(final_content, encoding='utf-8')

        reload_result: dict[str, Any] | None = None
        reload_applied = False
        restart_required = bool(spec['restart_required'])
        if reload_after_save and spec['reload_supported']:
            reload_result = self.reload(gw)
            reload_applied = True
        elif reload_after_save and restart_required:
            reload_result = {'ok': True, 'restart_required': True, 'reason': 'service_restart_required'}

        try:
            gw.audit.log_event(
                direction='security',
                channel='system',
                user_id=str(actor or 'admin'),
                session_id='system',
                payload={
                    'event': 'config_file_saved',
                    'section': section,
                    'path': self._display_path(target_path),
                    'reload_applied': reload_applied,
                    'restart_required': restart_required,
                    'backup_path': self._display_path(backup_path) if backup_path else '',
                },
            )
        except Exception:
            pass

        snapshot = self._read_config_snapshot(gw, spec)
        return {
            'ok': True,
            'section': section,
            'path': self._display_path(target_path),
            'backup_path': self._display_path(backup_path) if backup_path else None,
            'reload_supported': spec['reload_supported'],
            'reload_applied': reload_applied,
            'restart_required': restart_required,
            'reload_result': reload_result,
            'validation': validation,
            'snapshot': snapshot,
        }

    @staticmethod
    def _channel_wizard_channel_names() -> list[str]:
        return ['telegram', 'slack', 'discord']

    @staticmethod
    def _channel_wizard_channel_title(channel: str) -> str:
        titles = {'telegram': 'Telegram', 'slack': 'Slack', 'discord': 'Discord'}
        return titles.get(str(channel or '').strip().lower(), str(channel or '').strip().title() or 'Channel')

    def _channel_wizard_fields(self, channel: str) -> list[dict[str, Any]]:
        normalized = self._normalize_channel_name(channel)
        if normalized == 'telegram':
            return [
                {'group': 'Authentication', 'name': 'telegram.bot_token.mode', 'label': 'Bot token source', 'type': 'select', 'options': ['disabled', 'env', 'literal']},
                {'group': 'Authentication', 'name': 'telegram.bot_token.value', 'label': 'Bot token / env var', 'type': 'string', 'placeholder': 'OPENMIURA_TELEGRAM_BOT_TOKEN'},
                {'group': 'Transport', 'name': 'telegram.mode', 'label': 'Mode', 'type': 'select', 'options': ['polling', 'webhook']},
                {'group': 'Transport', 'name': 'telegram.webhook_secret.mode', 'label': 'Webhook secret source', 'type': 'select', 'options': ['disabled', 'env', 'literal']},
                {'group': 'Transport', 'name': 'telegram.webhook_secret.value', 'label': 'Webhook secret / env var', 'type': 'string', 'placeholder': 'OPENMIURA_TELEGRAM_WEBHOOK_SECRET'},
                {'group': 'Allowlist', 'name': 'telegram.allowlist.enabled', 'label': 'Allowlist enabled', 'type': 'bool'},
                {'group': 'Allowlist', 'name': 'telegram.allowlist.allow_user_ids', 'label': 'Allowed user IDs', 'type': 'csv_int', 'placeholder': '12345,67890'},
                {'group': 'Allowlist', 'name': 'telegram.allowlist.allow_chat_ids', 'label': 'Allowed chat IDs', 'type': 'csv_int', 'placeholder': '-10012345,-10067890'},
                {'group': 'Allowlist', 'name': 'telegram.allowlist.allow_groups', 'label': 'Allow groups', 'type': 'bool'},
                {'group': 'Allowlist', 'name': 'telegram.allowlist.deny_message', 'label': 'Deny message', 'type': 'string', 'placeholder': '⛔ No autorizado. Pide acceso al administrador.'},
            ]
        if normalized == 'slack':
            return [
                {'group': 'Authentication', 'name': 'slack.bot_token.mode', 'label': 'Bot token source', 'type': 'select', 'options': ['disabled', 'env', 'literal']},
                {'group': 'Authentication', 'name': 'slack.bot_token.value', 'label': 'Bot token / env var', 'type': 'string', 'placeholder': 'OPENMIURA_SLACK_BOT_TOKEN'},
                {'group': 'Authentication', 'name': 'slack.signing_secret.mode', 'label': 'Signing secret source', 'type': 'select', 'options': ['disabled', 'env', 'literal']},
                {'group': 'Authentication', 'name': 'slack.signing_secret.value', 'label': 'Signing secret / env var', 'type': 'string', 'placeholder': 'OPENMIURA_SLACK_SIGNING_SECRET'},
                {'group': 'Transport', 'name': 'slack.bot_user_id', 'label': 'Bot user ID', 'type': 'string', 'placeholder': 'U012345'},
                {'group': 'Transport', 'name': 'slack.reply_in_thread', 'label': 'Reply in thread', 'type': 'bool'},
                {'group': 'Allowlist', 'name': 'slack.allowlist.enabled', 'label': 'Allowlist enabled', 'type': 'bool'},
                {'group': 'Allowlist', 'name': 'slack.allowlist.allow_team_ids', 'label': 'Allowed team IDs', 'type': 'csv_str', 'placeholder': 'T123,T456'},
                {'group': 'Allowlist', 'name': 'slack.allowlist.allow_channel_ids', 'label': 'Allowed channel IDs', 'type': 'csv_str', 'placeholder': 'C123,C456'},
                {'group': 'Allowlist', 'name': 'slack.allowlist.allow_im', 'label': 'Allow direct messages', 'type': 'bool'},
                {'group': 'Allowlist', 'name': 'slack.allowlist.deny_message', 'label': 'Deny message', 'type': 'string', 'placeholder': '⛔ No autorizado. Pide acceso al administrador.'},
            ]
        return [
            {'group': 'Authentication', 'name': 'discord.bot_token.mode', 'label': 'Bot token source', 'type': 'select', 'options': ['disabled', 'env', 'literal']},
            {'group': 'Authentication', 'name': 'discord.bot_token.value', 'label': 'Bot token / env var', 'type': 'string', 'placeholder': 'OPENMIURA_DISCORD_BOT_TOKEN'},
            {'group': 'Authentication', 'name': 'discord.application_id', 'label': 'Application ID', 'type': 'string', 'placeholder': '1234567890'},
            {'group': 'Transport', 'name': 'discord.mention_only', 'label': 'Mention only', 'type': 'bool'},
            {'group': 'Transport', 'name': 'discord.reply_as_reply', 'label': 'Reply as reply', 'type': 'bool'},
            {'group': 'Transport', 'name': 'discord.slash_enabled', 'label': 'Slash commands enabled', 'type': 'bool'},
            {'group': 'Transport', 'name': 'discord.slash_command_name', 'label': 'Slash command name', 'type': 'string', 'placeholder': 'miura'},
            {'group': 'Transport', 'name': 'discord.sync_on_startup', 'label': 'Sync on startup', 'type': 'bool'},
            {'group': 'Transport', 'name': 'discord.sync_guild_ids', 'label': 'Sync guild IDs', 'type': 'csv_int', 'placeholder': '111,222'},
            {'group': 'Transport', 'name': 'discord.expose_native_commands', 'label': 'Expose native commands', 'type': 'bool'},
            {'group': 'Transport', 'name': 'discord.include_attachments_in_text', 'label': 'Include attachments in text', 'type': 'bool'},
            {'group': 'Transport', 'name': 'discord.max_attachment_items', 'label': 'Max attachment items', 'type': 'int', 'min': 0},
            {'group': 'Allowlist', 'name': 'discord.allowlist.enabled', 'label': 'Allowlist enabled', 'type': 'bool'},
            {'group': 'Allowlist', 'name': 'discord.allowlist.allow_user_ids', 'label': 'Allowed user IDs', 'type': 'csv_int', 'placeholder': '1,2'},
            {'group': 'Allowlist', 'name': 'discord.allowlist.allow_channel_ids', 'label': 'Allowed channel IDs', 'type': 'csv_int', 'placeholder': '10,20'},
            {'group': 'Allowlist', 'name': 'discord.allowlist.allow_guild_ids', 'label': 'Allowed guild IDs', 'type': 'csv_int', 'placeholder': '100,200'},
            {'group': 'Allowlist', 'name': 'discord.allowlist.allow_dm', 'label': 'Allow direct messages', 'type': 'bool'},
            {'group': 'Allowlist', 'name': 'discord.allowlist.deny_message', 'label': 'Deny message', 'type': 'string', 'placeholder': '⛔ No autorizado. Pide acceso al administrador.'},
        ]

    def _channel_wizard_schema(self) -> dict[str, list[dict[str, Any]]]:
        output: dict[str, list[dict[str, Any]]] = {}
        for channel in self._channel_wizard_channel_names():
            groups: dict[str, list[dict[str, Any]]] = {}
            for field in self._channel_wizard_fields(channel):
                groups.setdefault(str(field['group']), []).append({k: v for k, v in field.items() if k != 'group'})
            output[channel] = [{'group': group, 'fields': fields} for group, fields in groups.items()]
        return output

    def _extract_channel_wizard_values(self, parsed: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
        payload = parsed if isinstance(parsed, dict) else {}
        defaults: dict[str, dict[str, Any]] = {
            'telegram': {
                'telegram.bot_token.mode': 'disabled',
                'telegram.bot_token.value': '',
                'telegram.mode': 'polling',
                'telegram.webhook_secret.mode': 'disabled',
                'telegram.webhook_secret.value': '',
                'telegram.allowlist.enabled': False,
                'telegram.allowlist.allow_user_ids': [],
                'telegram.allowlist.allow_chat_ids': [],
                'telegram.allowlist.allow_groups': False,
                'telegram.allowlist.deny_message': '⛔ No autorizado. Pide acceso al administrador.',
            },
            'slack': {
                'slack.bot_token.mode': 'disabled',
                'slack.bot_token.value': '',
                'slack.signing_secret.mode': 'disabled',
                'slack.signing_secret.value': '',
                'slack.bot_user_id': '',
                'slack.reply_in_thread': True,
                'slack.allowlist.enabled': False,
                'slack.allowlist.allow_team_ids': [],
                'slack.allowlist.allow_channel_ids': [],
                'slack.allowlist.allow_im': True,
                'slack.allowlist.deny_message': '⛔ No autorizado. Pide acceso al administrador.',
            },
            'discord': {
                'discord.bot_token.mode': 'disabled',
                'discord.bot_token.value': '',
                'discord.application_id': '',
                'discord.mention_only': True,
                'discord.reply_as_reply': True,
                'discord.slash_enabled': True,
                'discord.slash_command_name': 'miura',
                'discord.sync_on_startup': True,
                'discord.sync_guild_ids': [],
                'discord.expose_native_commands': True,
                'discord.include_attachments_in_text': True,
                'discord.max_attachment_items': 4,
                'discord.allowlist.enabled': False,
                'discord.allowlist.allow_user_ids': [],
                'discord.allowlist.allow_channel_ids': [],
                'discord.allowlist.allow_guild_ids': [],
                'discord.allowlist.allow_dm': True,
                'discord.allowlist.deny_message': '⛔ No autorizado. Pide acceso al administrador.',
            },
        }
        result = copy.deepcopy(defaults)
        for channel in self._channel_wizard_channel_names():
            values = result[channel]
            for field in self._channel_wizard_fields(channel):
                name = str(field['name'])
                field_type = str(field.get('type') or 'string')
                if name.endswith('.mode') and name[:-5] in self._secret_storage_fields():
                    mode, _ = self._extract_secret_storage(self._config_get_path(payload, name[:-5], ''))
                    values[name] = mode
                    continue
                if name.endswith('.value') and name[:-6] in self._secret_storage_fields():
                    _, stored = self._extract_secret_storage(self._config_get_path(payload, name[:-6], ''))
                    values[name] = stored
                    continue
                values[name] = self._config_get_path(payload, name, copy.deepcopy(values.get(name)))
                if field_type in {'csv_int', 'csv_str'} and not isinstance(values[name], list):
                    values[name] = []
        return result

    @staticmethod
    def _coerce_channel_wizard_value(field_type: str, value: Any) -> Any:
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
        if field_type == 'float':
            try:
                return float(value)
            except Exception:
                return 0.0
        if field_type in {'csv_int', 'csv_str'}:
            if isinstance(value, list):
                items = value
            else:
                raw = str(value or '')
                items = [part.strip() for chunk in raw.splitlines() for part in chunk.split(',')]
            cleaned = [item for item in items if str(item).strip()]
            if field_type == 'csv_int':
                numbers: list[int] = []
                for item in cleaned:
                    try:
                        numbers.append(int(str(item).strip()))
                    except Exception:
                        continue
                return numbers
            return [str(item).strip() for item in cleaned if str(item).strip()]
        return str(value or '')

    def _apply_channel_wizard_values(self, base_payload: dict[str, Any], channel: str, wizard_payload: dict[str, Any]) -> dict[str, Any]:
        normalized = self._normalize_channel_name(channel)
        merged = copy.deepcopy(base_payload) if isinstance(base_payload, dict) else {}
        for field in self._channel_wizard_fields(normalized):
            name = str(field['name'])
            if name.endswith('.mode') and name[:-5] in self._secret_storage_fields():
                secret_path = name[:-5]
                composed = self._compose_secret_storage(
                    wizard_payload.get(name),
                    wizard_payload.get(f'{secret_path}.value'),
                )
                self._config_set_path(merged, secret_path, composed)
                continue
            if name.endswith('.value') and name[:-6] in self._secret_storage_fields():
                continue
            if name not in wizard_payload:
                continue
            value = self._coerce_channel_wizard_value(str(field.get('type') or 'string'), wizard_payload.get(name))
            self._config_set_path(merged, name, value)
        return merged

    def _materialize_channel_wizard_content(
        self,
        gw: AdminGatewayLike,
        *,
        channel: str,
        content: str,
        wizard_payload: dict[str, Any] | None = None,
    ) -> str:
        normalized = self._normalize_channel_name(channel)
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
            raise ValueError('channel_wizard_requires_mapping_yaml')
        if not wizard_payload:
            return yaml.safe_dump(base_payload, sort_keys=False, allow_unicode=True)
        merged = self._apply_channel_wizard_values(base_payload, normalized, wizard_payload)
        return yaml.safe_dump(merged, sort_keys=False, allow_unicode=True)

    def _channel_wizard_status(self, channel: str, values: dict[str, Any]) -> dict[str, Any]:
        normalized = self._normalize_channel_name(channel)
        if normalized == 'telegram':
            configured = str(values.get('telegram.bot_token.mode') or 'disabled') != 'disabled'
            webhook = str(values.get('telegram.webhook_secret.mode') or 'disabled') != 'disabled'
            return {
                'configured': configured,
                'transport': str(values.get('telegram.mode') or 'polling'),
                'secret_sources': {
                    'bot_token': values.get('telegram.bot_token.mode'),
                    'webhook_secret': values.get('telegram.webhook_secret.mode'),
                },
                'allowlist_enabled': bool(values.get('telegram.allowlist.enabled')),
                'allow_user_count': len(list(values.get('telegram.allowlist.allow_user_ids') or [])),
                'allow_chat_count': len(list(values.get('telegram.allowlist.allow_chat_ids') or [])),
                'webhook_secret_configured': webhook,
            }
        if normalized == 'slack':
            configured = str(values.get('slack.bot_token.mode') or 'disabled') != 'disabled'
            return {
                'configured': configured,
                'transport': 'events-api',
                'secret_sources': {
                    'bot_token': values.get('slack.bot_token.mode'),
                    'signing_secret': values.get('slack.signing_secret.mode'),
                },
                'reply_in_thread': bool(values.get('slack.reply_in_thread')),
                'allowlist_enabled': bool(values.get('slack.allowlist.enabled')),
                'allow_team_count': len(list(values.get('slack.allowlist.allow_team_ids') or [])),
                'allow_channel_count': len(list(values.get('slack.allowlist.allow_channel_ids') or [])),
            }
        configured = str(values.get('discord.bot_token.mode') or 'disabled') != 'disabled'
        return {
            'configured': configured,
            'transport': 'gateway',
            'secret_sources': {
                'bot_token': values.get('discord.bot_token.mode'),
            },
            'application_id_present': bool(str(values.get('discord.application_id') or '').strip()),
            'slash_enabled': bool(values.get('discord.slash_enabled')),
            'allowlist_enabled': bool(values.get('discord.allowlist.enabled')),
            'allow_guild_count': len(list(values.get('discord.allowlist.allow_guild_ids') or [])),
            'sync_guild_count': len(list(values.get('discord.sync_guild_ids') or [])),
        }

    def _reload_assistant_operational_state(
        self,
        gw: AdminGatewayLike,
        *,
        config_path: Path,
        sections: list[dict[str, Any]],
        recent_restart_requests: list[dict[str, Any]],
    ) -> dict[str, Any]:
        started_at = float(getattr(gw, 'started_at', time.time()) or time.time())
        now = time.time()
        uptime_s = max(0.0, now - started_at)
        latest_request = dict(recent_restart_requests[0]) if recent_restart_requests else {}
        latest_request_ts = float(latest_request.get('ts') or 0.0)
        latest_hook_result = dict(latest_request.get('hook') or {}) if isinstance(latest_request.get('hook'), dict) else {}
        latest_startup_event = self._latest_startup_event(gw)
        latest_startup_payload = dict(latest_startup_event.get('payload') or {}) if latest_startup_event else {}
        latest_startup_started_at = float(latest_startup_payload.get('started_at') or latest_startup_event.get('ts') or 0.0) if latest_startup_event else 0.0
        observed_new_process = bool(latest_request and max(started_at, latest_startup_started_at) > latest_request_ts > 0.0)
        if not latest_request:
            restart_state = 'not_requested'
            restart_summary = 'No restart request has been recorded yet.'
        elif observed_new_process:
            restart_state = 'confirmed'
            restart_summary = 'Current process started after the latest restart request.'
        elif str(latest_request.get('status') or '') == 'queued':
            restart_state = 'pending'
            restart_summary = 'A restart request is queued but a newer process has not been observed yet.'
        elif str(latest_request.get('status') or '') == 'hook_failed':
            restart_state = 'hook_failed'
            restart_summary = 'The latest restart hook execution failed.'
        else:
            restart_state = 'awaiting_observation'
            restart_summary = 'A restart was requested, but this process has not changed since that request.'

        main_config = self._file_runtime_metadata(config_path)
        section_files = []
        missing_files = []
        invalid_files = []
        for item in sections:
            metadata = self._file_runtime_metadata(Path(str(item.get('path') or '')))
            record = {
                'name': item.get('name'),
                'title': item.get('title'),
                'reload_supported': bool(item.get('reload_supported')),
                'restart_required': bool(item.get('restart_required')),
                'exists': bool(item.get('exists')),
                'valid': bool(item.get('valid', True)),
                'metadata': metadata,
                'summary': dict(item.get('summary') or {}),
            }
            if not bool(item.get('exists')):
                missing_files.append(str(item.get('name') or ''))
            if not bool(item.get('valid', True)) or str(item.get('parse_error') or '').strip():
                invalid_files.append(str(item.get('name') or ''))
            section_files.append(record)

        health_checks = {
            'gateway_loaded': True,
            'main_config_present': bool(main_config.get('exists')),
            'policy_engine_loaded': bool(getattr(gw, 'policy', None) is not None),
            'router_loaded': bool(getattr(gw, 'router', None) is not None),
            'audit_store_ready': bool(getattr(gw, 'audit', None) is not None),
        }
        health_status = 'healthy'
        health_issues: list[str] = []
        if not main_config.get('exists'):
            health_status = 'degraded'
            health_issues.append('main_config_missing')
        if missing_files:
            health_status = 'degraded'
            health_issues.append('config_section_missing')
        if invalid_files:
            health_status = 'degraded'
            health_issues.append('config_section_invalid')
        if restart_state == 'hook_failed':
            health_status = 'degraded'
            health_issues.append('restart_hook_failed')

        runtime_summary = self.status_snapshot(gw)
        current_boot_id = str(getattr(gw, 'boot_instance_id', '') or '')
        current_boot = {
            'boot_instance_id': current_boot_id,
            'pid': os.getpid(),
            'service': 'openMiura',
            'version': __version__,
            'started_at': started_at,
            'started_at_iso': self._iso_timestamp(started_at),
            'uptime_s': uptime_s,
            'uptime_human': self._format_duration(uptime_s),
            'config_path': self._display_path(config_path),
            'config_sha256': main_config.get('sha256'),
        }
        latest_boot_evidence: dict[str, Any]
        if latest_startup_event:
            latest_boot_instance_id = str(latest_startup_payload.get('boot_instance_id') or '')
            latest_boot_pid = int(latest_startup_payload.get('pid') or 0) if str(latest_startup_payload.get('pid') or '').strip() else 0
            current_process_matches = bool(
                (current_boot_id and latest_boot_instance_id and latest_boot_instance_id == current_boot_id)
                or (latest_boot_pid and latest_boot_pid == os.getpid() and latest_startup_started_at and abs(latest_startup_started_at - started_at) < 5.0)
            )
            latest_boot_evidence = {
                'source': 'audit_event',
                'event_id': latest_startup_event.get('id'),
                'event_ts': float(latest_startup_event.get('ts') or 0.0),
                'event_ts_iso': self._iso_timestamp(float(latest_startup_event.get('ts') or 0.0)),
                'boot_instance_id': latest_boot_instance_id,
                'pid': latest_boot_pid,
                'started_at': latest_startup_started_at,
                'started_at_iso': self._iso_timestamp(latest_startup_started_at),
                'config_path': self._display_path(latest_startup_payload.get('config_path') or config_path),
                'current_process_matches': current_process_matches,
                'observed_after_latest_restart_request': bool(latest_request and latest_startup_started_at > latest_request_ts > 0.0),
                'summary': 'Latest startup event matches the current running process.' if current_process_matches else 'Latest startup event differs from the current in-memory process.',
            }
        else:
            latest_boot_evidence = {
                'source': 'runtime_only',
                'event_id': None,
                'event_ts': None,
                'event_ts_iso': '',
                'boot_instance_id': current_boot_id,
                'pid': os.getpid(),
                'started_at': started_at,
                'started_at_iso': self._iso_timestamp(started_at),
                'config_path': self._display_path(config_path),
                'current_process_matches': True,
                'observed_after_latest_restart_request': bool(latest_request and started_at > latest_request_ts > 0.0),
                'summary': 'No startup audit event was found; using the current runtime as the boot evidence.',
            }
        process = {
            'pid': os.getpid(),
            'service': 'openMiura',
            'version': __version__,
            'started_at': started_at,
            'started_at_iso': self._iso_timestamp(started_at),
            'uptime_s': uptime_s,
            'uptime_human': self._format_duration(uptime_s),
            'boot_instance_id': current_boot_id,
        }
        restart_hook_result = {
            'available': bool(latest_hook_result),
            'request_id': latest_request.get('request_id') if latest_request else None,
            'request_status': latest_request.get('status') if latest_request else None,
            'requested_execution': bool(latest_request.get('execute_restart_hook')) if latest_request else False,
            'configured': bool(latest_hook_result.get('configured')) if latest_hook_result else False,
            'executed': bool(latest_hook_result.get('executed')) if latest_hook_result else False,
            'ok': bool(latest_hook_result.get('ok')) if latest_hook_result else False,
            'exit_code': latest_hook_result.get('exit_code') if latest_hook_result else None,
            'error': latest_hook_result.get('error') if latest_hook_result else '',
            'stdout_excerpt': latest_hook_result.get('stdout_excerpt') if latest_hook_result else '',
            'stderr_excerpt': latest_hook_result.get('stderr_excerpt') if latest_hook_result else '',
            'started_at': latest_hook_result.get('started_at') if latest_hook_result else None,
            'started_at_iso': self._iso_timestamp(float(latest_hook_result.get('started_at') or 0.0)) if latest_hook_result else '',
            'finished_at': latest_hook_result.get('finished_at') if latest_hook_result else None,
            'finished_at_iso': self._iso_timestamp(float(latest_hook_result.get('finished_at') or 0.0)) if latest_hook_result else '',
            'summary': 'No restart hook result is available yet.',
        }
        if latest_hook_result:
            if restart_hook_result['ok']:
                restart_hook_result['summary'] = 'The latest restart hook execution completed successfully.'
            elif restart_hook_result['executed']:
                restart_hook_result['summary'] = 'The latest restart hook execution finished with an error.'
            else:
                restart_hook_result['summary'] = 'The latest restart request did not execute the restart hook.'
        elif latest_request and not bool(latest_request.get('execute_restart_hook')):
            restart_hook_result['summary'] = 'The latest restart request was queued without executing the external hook.'

        restart_observation = {
            'state': restart_state,
            'summary': restart_summary,
            'latest_request_id': latest_request.get('request_id') if latest_request else None,
            'latest_request_status': latest_request.get('status') if latest_request else None,
            'latest_request_ts': latest_request_ts if latest_request else None,
            'latest_request_ts_iso': self._iso_timestamp(latest_request_ts) if latest_request else '',
            'observed_new_process_since_request': observed_new_process,
            'current_boot_instance_id': current_boot_id,
            'latest_boot_instance_id': latest_boot_evidence.get('boot_instance_id'),
        }
        startup_config = {
            'main_config': main_config,
            'router': dict(runtime_summary.get('router') or {}),
            'policy': dict(runtime_summary.get('policy') or {}),
            'channels': dict(runtime_summary.get('channels') or {}),
            'llm': dict(runtime_summary.get('llm') or {}),
            'db': {'path': ((runtime_summary.get('db') or {}).get('path')), 'counts': dict(((runtime_summary.get('db') or {}).get('counts') or {}))},
            'tenancy': dict(runtime_summary.get('tenancy') or {}),
            'section_files': section_files,
        }
        return {
            'process': process,
            'health': {
                'status': health_status,
                'checked_at': now,
                'checked_at_iso': self._iso_timestamp(now),
                'issues': health_issues,
                'checks': health_checks,
            },
            'startup_config': startup_config,
            'current_boot': current_boot,
            'latest_boot_evidence': latest_boot_evidence,
            'restart_hook_result': restart_hook_result,
            'restart_observation': restart_observation,
        }

