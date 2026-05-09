"""openmiura.application.admin.service._core_mixin

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


class _AdminServiceCoreMixin:
    """Mixin: core methods on AdminService."""

    def status_snapshot(self, gw: AdminGatewayLike) -> dict[str, Any]:
        tool_names = collect_registered_tool_names(getattr(gw, "tools", None))
        return build_status_snapshot(
            gw,
            safe_call=self._safe_call,
            tenancy_catalog=self.tenancy_service.catalog(getattr(gw, "settings", None)),
            tool_names=tool_names,
        )

    def _policy_engine_from_payload(
        self,
        *,
        current_policy: Any | None,
        explicit_policy: dict[str, Any] | None = None,
        explicit_policy_yaml: str | None = None,
        allow_current_fallback: bool = True,
    ) -> PolicyEngine | None:
        payload = None
        if explicit_policy_yaml and str(explicit_policy_yaml).strip():
            payload = yaml.safe_load(str(explicit_policy_yaml)) or {}
        elif explicit_policy:
            payload = explicit_policy
        elif allow_current_fallback and current_policy is not None and hasattr(current_policy, "snapshot"):
            payload = current_policy.snapshot()
        if payload is None:
            return None
        return PolicyEngine.from_mapping(payload)

    def _policy_section_summary(self, policy: dict[str, Any]) -> dict[str, Any]:
        summary: dict[str, Any] = {}
        for key, value in dict(policy or {}).items():
            if isinstance(value, list):
                summary[key] = len(value)
            elif isinstance(value, dict):
                summary[key] = len(value.keys())
            else:
                summary[key] = 0
        return summary

    def _diff_policy_documents(self, baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
        section_names = sorted(set(dict(baseline or {}).keys()) | set(dict(candidate or {}).keys()))
        sections: dict[str, Any] = {}
        added_total = removed_total = changed_total = 0
        for section in section_names:
            base_value = (baseline or {}).get(section, [] if section != "defaults" else {})
            cand_value = (candidate or {}).get(section, [] if section != "defaults" else {})
            if isinstance(base_value, dict) or isinstance(cand_value, dict):
                base_dict = dict(base_value or {})
                cand_dict = dict(cand_value or {})
                added_keys = sorted([key for key in cand_dict.keys() if key not in base_dict])
                removed_keys = sorted([key for key in base_dict.keys() if key not in cand_dict])
                changed_keys = sorted([key for key in set(base_dict.keys()) & set(cand_dict.keys()) if base_dict.get(key) != cand_dict.get(key)])
                sections[section] = {
                    "type": "mapping",
                    "added": [{"key": key, "value": cand_dict.get(key)} for key in added_keys],
                    "removed": [{"key": key, "value": base_dict.get(key)} for key in removed_keys],
                    "changed": [{"key": key, "before": base_dict.get(key), "after": cand_dict.get(key)} for key in changed_keys],
                }
                added_total += len(added_keys)
                removed_total += len(removed_keys)
                changed_total += len(changed_keys)
                continue
            base_items = list(base_value or [])
            cand_items = list(cand_value or [])
            base_index = {self._rule_identity(section, item, idx): item for idx, item in enumerate(base_items)}
            cand_index = {self._rule_identity(section, item, idx): item for idx, item in enumerate(cand_items)}
            shared = sorted(set(base_index.keys()) & set(cand_index.keys()))
            changed = []
            for key in shared:
                if base_index[key] != cand_index[key]:
                    changed.append({"id": key, "before": base_index[key], "after": cand_index[key]})
            added = [{"id": key, "rule": cand_index[key]} for key in sorted(set(cand_index.keys()) - set(base_index.keys()))]
            removed = [{"id": key, "rule": base_index[key]} for key in sorted(set(base_index.keys()) - set(cand_index.keys()))]
            sections[section] = {"type": "rules", "added": added, "removed": removed, "changed": changed}
            added_total += len(added)
            removed_total += len(removed)
            changed_total += len(changed)
        return {
            "summary": {
                "section_count": len(section_names),
                "added": added_total,
                "removed": removed_total,
                "changed": changed_total,
            },
            "sections": sections,
        }

    def _compare_policy_decisions(self, baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
        if not candidate:
            return {"changed": False, "fields": []}
        changed_fields = []
        for key in ["allowed", "requires_confirmation", "requires_approval", "reason", "matched_rules"]:
            if baseline.get(key) != candidate.get(key):
                changed_fields.append(key)
        return {
            "changed": bool(changed_fields),
            "fields": changed_fields,
            "baseline": {key: baseline.get(key) for key in ["allowed", "requires_confirmation", "requires_approval", "reason", "matched_rules"]},
            "candidate": {key: candidate.get(key) for key in ["allowed", "requires_confirmation", "requires_approval", "reason", "matched_rules"]},
        }

    def validate_config_content(
        self,
        gw: AdminGatewayLike,
        *,
        section: str,
        content: str,
        form_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        spec = self._config_section_spec(gw, section)
        rendered_content = self._materialize_config_content(gw, section=section, content=content, form_payload=form_payload)
        parsed = yaml.safe_load(str(rendered_content or ''))
        warnings: list[str] = []
        if parsed is None:
            parsed = {}
            warnings.append('empty_yaml_document')
        top_level_keys: list[str] = []
        if isinstance(parsed, dict):
            top_level_keys = [str(k) for k in parsed.keys()]
        elif isinstance(parsed, list):
            top_level_keys = [f'item[{idx}]' for idx, _ in enumerate(parsed[:10])]
        if section == 'openmiura' and isinstance(parsed, dict):
            llm = parsed.get('llm') or {}
            if not llm:
                warnings.append('llm_section_missing')
            elif not (llm.get('provider') and llm.get('model')):
                warnings.append('llm_provider_or_model_missing')
        normalized = yaml.safe_dump(parsed, sort_keys=False, allow_unicode=True)
        response = {
            'ok': True,
            'section': section,
            'path': self._display_path(spec['path']),
            'valid': True,
            'warnings': warnings,
            'top_level_keys': top_level_keys,
            'summary': self._build_config_file_summary(section, parsed),
            'normalized_yaml': normalized,
        }
        if section == 'openmiura' and isinstance(parsed, dict):
            response['form_values'] = self._extract_openmiura_form_values(parsed)
            response['form_schema'] = self._openmiura_form_schema()
        return response

    def channel_setup_wizard_snapshot(self, gw: AdminGatewayLike) -> dict[str, Any]:
        spec = self._config_section_spec(gw, 'openmiura')
        snapshot = self._read_config_snapshot(gw, spec)
        parsed = yaml.safe_load(snapshot.get('raw') or '') if str(snapshot.get('raw') or '').strip() else {}
        if parsed is None:
            parsed = {}
        if not isinstance(parsed, dict):
            parsed = {}
        values = self._extract_channel_wizard_values(parsed)
        channels = []
        for name in self._channel_wizard_channel_names():
            channels.append(
                {
                    'name': name,
                    'title': self._channel_wizard_channel_title(name),
                    'status': self._channel_wizard_status(name, values.get(name) or {}),
                }
            )
        return {
            'ok': True,
            'path': self._display_path(spec['path']),
            'schemas': self._channel_wizard_schema(),
            'values': values,
            'channels': channels,
            'raw': snapshot.get('raw') or '',
        }

    def validate_channel_setup(
        self,
        gw: AdminGatewayLike,
        *,
        channel: str,
        wizard_payload: dict[str, Any] | None = None,
        content: str = '',
    ) -> dict[str, Any]:
        normalized_channel = self._normalize_channel_name(channel)
        rendered_content = self._materialize_channel_wizard_content(
            gw,
            channel=normalized_channel,
            content=content,
            wizard_payload=wizard_payload,
        )
        parsed = yaml.safe_load(str(rendered_content or ''))
        warnings: list[str] = []
        if parsed is None:
            parsed = {}
            warnings.append('empty_yaml_document')
        if not isinstance(parsed, dict):
            raise ValueError('channel_wizard_requires_mapping_yaml')
        values = self._extract_channel_wizard_values(parsed)
        status = self._channel_wizard_status(normalized_channel, values.get(normalized_channel) or {})
        normalized_yaml = yaml.safe_dump(parsed, sort_keys=False, allow_unicode=True)
        return {
            'ok': True,
            'channel': normalized_channel,
            'path': str(self._config_section_spec(gw, 'openmiura')['path']),
            'warnings': warnings,
            'summary': self._build_config_file_summary('openmiura', parsed),
            'normalized_yaml': normalized_yaml,
            'wizard_schema': self._channel_wizard_schema().get(normalized_channel, []),
            'wizard_values': values.get(normalized_channel) or {},
            'channel_status': status,
        }

    def save_channel_setup(
        self,
        gw: AdminGatewayLike,
        *,
        channel: str,
        wizard_payload: dict[str, Any] | None = None,
        content: str = '',
        reload_after_save: bool = False,
        actor: str = 'admin',
    ) -> dict[str, Any]:
        validation = self.validate_channel_setup(gw, channel=channel, wizard_payload=wizard_payload, content=content)
        response = self.save_config_content(
            gw,
            section='openmiura',
            content=str(validation.get('normalized_yaml') or ''),
            reload_after_save=reload_after_save,
            actor=actor,
        )
        response['channel'] = validation['channel']
        response['channel_validation'] = validation
        response['channel_status'] = validation['channel_status']
        return response

    @staticmethod
    def _env_reference_fields() -> set[str]:
        return {'llm.api_key_env_var'}

    @staticmethod
    def _extract_env_reference(raw_value: Any) -> tuple[str, str]:
        value = str(raw_value or '').strip()
        return ('env', value) if value else ('disabled', '')

    @staticmethod
    def _compose_env_reference(mode: Any, value: Any) -> str:
        normalized_mode = str(mode or 'disabled').strip().lower()
        raw_value = str(value or '').strip()
        if normalized_mode == 'env' and raw_value:
            return raw_value
        return ''

    def list_identities(self, gw: AdminGatewayLike, *, global_user_key: str | None) -> dict[str, Any]:
        manager = getattr(gw, "identity", None)
        if manager is not None and hasattr(manager, "list_links"):
            items = manager.list_links(global_user_key)
        else:
            items = self._safe_call(gw.audit, "list_identities", [], global_user_key)
        return {"ok": True, "items": items}

    @staticmethod
    def _filter_tool_calls_window(items: list[dict[str, Any]], *, since_ts: float) -> list[dict[str, Any]]:
        filtered: list[dict[str, Any]] = []
        for item in list(items or []):
            try:
                ts = float(item.get("ts") or 0.0)
            except Exception:
                ts = 0.0
            if ts >= since_ts:
                filtered.append(item)
        return filtered

    @staticmethod
    def _gateway_config_path(gw: AdminGatewayLike) -> Path:
        raw = str(getattr(gw, 'config_path', '') or os.environ.get('OPENMIURA_CONFIG', 'configs/openmiura.yaml'))
        return Path(raw).expanduser().resolve()

    @staticmethod
    def _display_path(path: str | Path | None) -> str:
        if path is None:
            return ''
        try:
            return Path(path).as_posix()
        except Exception:
            return str(path).replace('\\', '/')

    def _config_section_specs(self, gw: AdminGatewayLike, config_path: Path) -> list[dict[str, Any]]:
        settings = getattr(gw, 'settings', None)
        evaluations = getattr(settings, 'evaluations', None)
        return [
            {'name': 'openmiura', 'title': 'Main settings', 'path': config_path, 'reload_supported': False, 'restart_required': True},
            {'name': 'agents', 'title': 'Agents catalog', 'path': self._resolve_config_related_path(config_path, str(getattr(settings, 'agents_path', 'agents.yaml') or 'agents.yaml')), 'reload_supported': True, 'restart_required': False},
            {'name': 'policies', 'title': 'Policies', 'path': self._resolve_config_related_path(config_path, str(getattr(settings, 'policies_path', 'policies.yaml') or 'policies.yaml')), 'reload_supported': True, 'restart_required': False},
            {'name': 'evaluations', 'title': 'Evaluation suites', 'path': self._resolve_config_related_path(config_path, str(getattr(evaluations, 'suites_path', 'evaluations.yaml') or 'evaluations.yaml')), 'reload_supported': False, 'restart_required': False},
        ]

    def _config_section_spec(self, gw: AdminGatewayLike, section: str) -> dict[str, Any]:
        config_path = self._gateway_config_path(gw)
        for spec in self._config_section_specs(gw, config_path):
            if spec['name'] == section:
                return spec
        raise ValueError('unsupported_config_section')

    @staticmethod
    def _config_get_path(payload: dict[str, Any], dotted_path: str, default: Any = None) -> Any:
        current: Any = payload
        for part in dotted_path.split('.'):
            if not isinstance(current, dict) or part not in current:
                return copy.deepcopy(default)
            current = current.get(part)
        return copy.deepcopy(current)

    @staticmethod
    def _config_set_path(payload: dict[str, Any], dotted_path: str, value: Any) -> None:
        current = payload
        parts = dotted_path.split('.')
        for part in parts[:-1]:
            child = current.get(part)
            if not isinstance(child, dict):
                child = {}
                current[part] = child
            current = child
        current[parts[-1]] = value

    @staticmethod
    def _openmiura_form_fields() -> list[dict[str, Any]]:
        return [
            {'group': 'Server', 'name': 'server.host', 'label': 'Host', 'type': 'string', 'placeholder': '127.0.0.1'},
            {'group': 'Server', 'name': 'server.port', 'label': 'Port', 'type': 'int', 'min': 1},
            {'group': 'Storage', 'name': 'storage.backend', 'label': 'Backend', 'type': 'select', 'options': ['sqlite', 'postgres', 'custom']},
            {'group': 'Storage', 'name': 'storage.db_path', 'label': 'DB path', 'type': 'string', 'placeholder': 'data/audit.db'},
            {'group': 'Storage', 'name': 'storage.backup_dir', 'label': 'Backup dir', 'type': 'string', 'placeholder': 'data/backups'},
            {'group': 'Storage', 'name': 'storage.auto_migrate', 'label': 'Auto migrate', 'type': 'bool'},
            {'group': 'LLM', 'name': 'llm.provider', 'label': 'Provider', 'type': 'select', 'options': ['ollama', 'openai', 'openai_compat', 'local_openai_compat', 'lmstudio', 'vllm', 'kimi', 'anthropic']},
            {'group': 'LLM', 'name': 'llm.base_url', 'label': 'Base URL', 'type': 'string', 'placeholder': 'http://127.0.0.1:11434'},
            {'group': 'LLM', 'name': 'llm.model', 'label': 'Model', 'type': 'string', 'placeholder': 'qwen2.5:7b-instruct'},
            {'group': 'LLM', 'name': 'llm.timeout_s', 'label': 'Timeout (s)', 'type': 'int', 'min': 1},
            {'group': 'LLM', 'name': 'llm.max_output_tokens', 'label': 'Max output tokens', 'type': 'int', 'min': 1},
            {'group': 'LLM', 'name': 'llm.api_key_env_var', 'label': 'API key env var', 'type': 'string', 'placeholder': 'OPENAI_API_KEY'},
            {'group': 'Runtime', 'name': 'runtime.history_limit', 'label': 'History limit', 'type': 'int', 'min': 1},
            {'group': 'Runtime', 'name': 'runtime.worker_mode', 'label': 'Worker mode', 'type': 'select', 'options': ['external', 'inline']},
            {'group': 'Memory', 'name': 'memory.enabled', 'label': 'Memory enabled', 'type': 'bool'},
            {'group': 'Memory', 'name': 'memory.embed_model', 'label': 'Embedding model', 'type': 'string', 'placeholder': 'nomic-embed-text'},
            {'group': 'Memory', 'name': 'memory.embed_base_url', 'label': 'Embedding URL', 'type': 'string', 'placeholder': 'http://127.0.0.1:11434'},
            {'group': 'Memory', 'name': 'memory.top_k', 'label': 'Top K', 'type': 'int', 'min': 1},
            {'group': 'Memory', 'name': 'memory.min_score', 'label': 'Min score', 'type': 'float', 'step': '0.01'},
            {'group': 'Tools', 'name': 'tools.sandbox_dir', 'label': 'Sandbox dir', 'type': 'string', 'placeholder': 'data/sandbox'},
            {'group': 'Broker', 'name': 'broker.enabled', 'label': 'Broker enabled', 'type': 'bool'},
            {'group': 'Broker', 'name': 'broker.base_path', 'label': 'Broker base path', 'type': 'string', 'placeholder': '/broker'},
            {'group': 'Auth', 'name': 'auth.enabled', 'label': 'Auth enabled', 'type': 'bool'},
            {'group': 'Auth', 'name': 'auth.session_ttl_s', 'label': 'Session TTL (s)', 'type': 'int', 'min': 0},
            {'group': 'Tenancy', 'name': 'tenancy.enabled', 'label': 'Tenancy enabled', 'type': 'bool'},
            {'group': 'Tenancy', 'name': 'tenancy.default_tenant_id', 'label': 'Default tenant', 'type': 'string', 'placeholder': 'default'},
            {'group': 'Tenancy', 'name': 'tenancy.default_workspace_id', 'label': 'Default workspace', 'type': 'string', 'placeholder': 'main'},
            {'group': 'Tenancy', 'name': 'tenancy.default_environment', 'label': 'Default environment', 'type': 'string', 'placeholder': 'prod'},
            {'group': 'Paths', 'name': 'agents_path', 'label': 'Agents path', 'type': 'string', 'placeholder': 'agents.yaml'},
            {'group': 'Paths', 'name': 'policies_path', 'label': 'Policies path', 'type': 'string', 'placeholder': 'policies.yaml'},
            {'group': 'Paths', 'name': 'evaluations.suites_path', 'label': 'Evaluation suites path', 'type': 'string', 'placeholder': 'evaluations.yaml'},
        ]

    def _openmiura_form_schema(self) -> list[dict[str, Any]]:
        groups: dict[str, list[dict[str, Any]]] = {}
        for field in self._openmiura_form_fields():
            groups.setdefault(str(field['group']), []).append({k: v for k, v in field.items() if k != 'group'})
        return [{'group': group, 'fields': fields} for group, fields in groups.items()]

    def _extract_openmiura_form_values(self, parsed: dict[str, Any] | None) -> dict[str, Any]:
        payload = parsed if isinstance(parsed, dict) else {}
        defaults: dict[str, Any] = {
            'server.host': '127.0.0.1',
            'server.port': 8081,
            'storage.backend': 'sqlite',
            'storage.db_path': 'data/audit.db',
            'storage.backup_dir': 'data/backups',
            'storage.auto_migrate': True,
            'llm.provider': 'ollama',
            'llm.base_url': 'http://127.0.0.1:11434',
            'llm.model': 'qwen2.5:7b-instruct',
            'llm.timeout_s': 60,
            'llm.max_output_tokens': 2048,
            'llm.api_key_env_var': '',
            'runtime.history_limit': 12,
            'runtime.worker_mode': 'external',
            'memory.enabled': True,
            'memory.embed_model': 'nomic-embed-text',
            'memory.embed_base_url': 'http://127.0.0.1:11434',
            'memory.top_k': 6,
            'memory.min_score': 0.25,
            'tools.sandbox_dir': 'data/sandbox',
            'broker.enabled': False,
            'broker.base_path': '/broker',
            'auth.enabled': False,
            'auth.session_ttl_s': 3600,
            'tenancy.enabled': False,
            'tenancy.default_tenant_id': 'default',
            'tenancy.default_workspace_id': 'main',
            'tenancy.default_environment': 'prod',
            'agents_path': 'agents.yaml',
            'policies_path': 'policies.yaml',
            'evaluations.suites_path': 'evaluations.yaml',
        }
        return {name: self._config_get_path(payload, name, default) for name, default in defaults.items()}

    @staticmethod
    def _coerce_openmiura_form_value(field_type: str, value: Any) -> Any:
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
        return str(value or '')

    def _apply_openmiura_form_values(self, base_payload: dict[str, Any], form_payload: dict[str, Any]) -> dict[str, Any]:
        merged = copy.deepcopy(base_payload) if isinstance(base_payload, dict) else {}
        field_specs = {field['name']: field for field in self._openmiura_form_fields()}
        for name, field in field_specs.items():
            if name not in form_payload:
                continue
            value = self._coerce_openmiura_form_value(str(field.get('type') or 'string'), form_payload.get(name))
            self._config_set_path(merged, name, value)
        return merged

    def _materialize_config_content(
        self,
        gw: AdminGatewayLike,
        *,
        section: str,
        content: str,
        form_payload: dict[str, Any] | None = None,
    ) -> str:
        if section != 'openmiura' or not form_payload:
            return str(content or '')
        base_raw = str(content or '')
        if not base_raw.strip():
            spec = self._config_section_spec(gw, section)
            base_path = Path(spec['path'])
            if base_path.exists():
                base_raw = base_path.read_text(encoding='utf-8')
        base_payload = yaml.safe_load(base_raw) if str(base_raw or '').strip() else {}
        if base_payload is None:
            base_payload = {}
        if not isinstance(base_payload, dict):
            raise ValueError('openmiura_form_requires_mapping_yaml')
        merged = self._apply_openmiura_form_values(base_payload, form_payload)
        return yaml.safe_dump(merged, sort_keys=False, allow_unicode=True)

    def _read_config_snapshot(self, gw: AdminGatewayLike, spec: dict[str, Any]) -> dict[str, Any]:
        path = Path(spec['path'])
        exists = path.exists()
        raw = path.read_text(encoding='utf-8') if exists else ''
        valid = True
        parse_error = ''
        parsed: Any = {}
        if raw.strip():
            try:
                parsed = yaml.safe_load(raw)
            except Exception as exc:
                valid = False
                parse_error = str(exc)
                parsed = {}
        elif exists:
            parsed = {}
        top_level_keys = [str(k) for k in parsed.keys()] if isinstance(parsed, dict) else []
        metadata = self._file_runtime_metadata(path)
        snapshot = {
            'section': spec['name'],
            'title': spec['title'],
            'path': self._display_path(path),
            'exists': exists,
            'valid': valid,
            'parse_error': parse_error,
            'raw': raw,
            'top_level_keys': top_level_keys,
            'reload_supported': bool(spec['reload_supported']),
            'restart_required': bool(spec['restart_required']),
            'summary': self._build_config_file_summary(spec['name'], parsed),
            'metadata': metadata,
        }
        if spec['name'] == 'openmiura':
            snapshot['form_schema'] = self._openmiura_form_schema()
            snapshot['form_values'] = self._extract_openmiura_form_values(parsed if isinstance(parsed, dict) else {})
        return snapshot

    @staticmethod
    def _config_quick_settings(status: dict[str, Any]) -> dict[str, Any]:
        return {
            'llm': dict(status.get('llm') or {}),
            'sessions': dict(status.get('sessions') or {}),
            'memory': dict(status.get('memory') or {}),
            'sandbox': dict(status.get('sandbox') or {}),
            'router': dict(status.get('router') or {}),
            'channels': dict(status.get('channels') or {}),
            'policy': dict(status.get('policy') or {}),
            'db': dict(status.get('db') or {}),
        }

    @staticmethod
    def _restart_hook_status() -> dict[str, Any]:
        allow_self_restart = str(os.environ.get('OPENMIURA_CONTROL_ALLOW_SELF_RESTART', '') or '').strip().lower() in {'1', 'true', 'yes', 'on'}
        command = str(os.environ.get('OPENMIURA_CONTROL_SELF_RESTART_COMMAND', '') or '').strip()
        configured = bool(allow_self_restart and command)
        return {
            'allow_self_restart': allow_self_restart,
            'configured': configured,
            'command': command,
            'command_preview': command if configured else '',
        }

    @staticmethod
    def _file_runtime_metadata(path: Path) -> dict[str, Any]:
        candidate = Path(path).expanduser().resolve()
        exists = candidate.exists()
        metadata = {
            'path': AdminService._display_path(candidate),
            'exists': exists,
            'size_bytes': int(candidate.stat().st_size) if exists else 0,
            'mtime': float(candidate.stat().st_mtime) if exists else 0.0,
            'mtime_iso': AdminService._iso_timestamp(float(candidate.stat().st_mtime)) if exists else '',
            'sha256': '',
            'parse_error': '',
        }
        if exists and candidate.is_file():
            try:
                raw = candidate.read_bytes()
                metadata['sha256'] = hashlib.sha256(raw).hexdigest()
            except Exception as exc:
                metadata['parse_error'] = str(exc)
        return metadata

    @staticmethod
    def _format_duration(seconds: float) -> str:
        total = max(0, int(seconds))
        hours, remainder = divmod(total, 3600)
        minutes, secs = divmod(remainder, 60)
        if hours:
            return f'{hours}h {minutes}m {secs}s'
        if minutes:
            return f'{minutes}m {secs}s'
        return f'{secs}s'

    @staticmethod
    def _iso_timestamp(ts: float | None) -> str:
        if not ts:
            return ''
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).astimezone().isoformat(timespec='seconds')

    def _execute_restart_hook(self, command: str, *, cwd: Path) -> dict[str, Any]:
        started_at = time.time()
        try:
            proc = subprocess.run(
                command,
                cwd=str(cwd),
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            stdout = str(proc.stdout or '')
            stderr = str(proc.stderr or '')
            return {
                'configured': True,
                'executed': True,
                'ok': proc.returncode == 0,
                'exit_code': int(proc.returncode),
                'stdout_excerpt': stdout[-1000:],
                'stderr_excerpt': stderr[-1000:],
                'started_at': started_at,
                'finished_at': time.time(),
            }
        except Exception as exc:
            return {
                'configured': True,
                'executed': True,
                'ok': False,
                'error': str(exc),
                'started_at': started_at,
                'finished_at': time.time(),
            }

    def _recent_restart_requests(self, gw: AdminGatewayLike, *, limit: int = 10) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        try:
            events = list(gw.audit.get_recent_events(limit=max(50, limit * 10), channel='system'))
        except Exception:
            events = []
        for event in events:
            payload = dict(event.get('payload') or {})
            if str(payload.get('event') or '') != 'assistant_restart_request':
                continue
            hook = dict(payload.get('hook') or {}) if isinstance(payload.get('hook'), dict) else {}
            items.append(
                {
                    'request_id': payload.get('request_id'),
                    'ts': float(event.get('ts') or payload.get('created_at') or 0.0),
                    'actor': payload.get('actor') or event.get('user_id'),
                    'sections': list(payload.get('sections') or []),
                    'restart_required_sections': list(payload.get('restart_required_sections') or []),
                    'status': str(payload.get('status') or 'queued'),
                    'execute_restart_hook': bool(payload.get('execute_restart_hook')),
                    'hook_ok': bool(hook.get('ok')) if hook else False,
                    'hook': hook,
                }
            )
            if len(items) >= limit:
                break
        return items

    def _config_backup_root(self, gw: AdminGatewayLike, config_path: Path) -> Path:
        backup_dir = str(getattr(getattr(getattr(gw, 'settings', None), 'storage', None), 'backup_dir', '') or 'data/backups')
        return self._resolve_config_related_path(config_path, backup_dir) / 'ui-config'

    @staticmethod
    def _build_config_file_summary(section: str, parsed: Any) -> dict[str, Any]:
        if not isinstance(parsed, dict):
            return {'type': type(parsed).__name__}
        if section == 'openmiura':
            llm = dict(parsed.get('llm') or {})
            memory = dict(parsed.get('memory') or {})
            broker = dict(parsed.get('broker') or {})
            auth = dict(parsed.get('auth') or {})
            server = dict(parsed.get('server') or {})
            storage = dict(parsed.get('storage') or {})
            telegram = dict(parsed.get('telegram') or {})
            slack = dict(parsed.get('slack') or {})
            discord = dict(parsed.get('discord') or {})
            return {
                'server': {'host': server.get('host'), 'port': server.get('port')},
                'llm': {'provider': llm.get('provider'), 'model': llm.get('model'), 'base_url': llm.get('base_url')},
                'memory_enabled': bool(memory.get('enabled', False)),
                'broker_enabled': bool(broker.get('enabled', False)),
                'auth_enabled': bool(auth.get('enabled', False)),
                'db_path': storage.get('db_path'),
                'channels': {
                    'telegram': {'configured': bool(str(telegram.get('bot_token') or '').strip()), 'mode': telegram.get('mode', 'polling')},
                    'slack': {'configured': bool(str(slack.get('bot_token') or '').strip()), 'reply_in_thread': bool(slack.get('reply_in_thread', True))},
                    'discord': {'configured': bool(str(discord.get('bot_token') or '').strip()), 'slash_enabled': bool(discord.get('slash_enabled', True))},
                },
            }
        if section == 'agents':
            raw_agents = parsed.get('agents')
            if isinstance(raw_agents, dict):
                agent_ids = [str(k) for k in raw_agents.keys()]
                return {'agent_count': len(raw_agents), 'agent_ids': sorted(agent_ids)[:20], 'catalog_shape': 'mapping'}
            if isinstance(raw_agents, list):
                agent_ids: list[str] = []
                for index, item in enumerate(raw_agents):
                    if isinstance(item, dict):
                        candidate = item.get('name') or item.get('agent_id') or item.get('id')
                        if candidate is not None and str(candidate).strip():
                            agent_ids.append(str(candidate))
                            continue
                    agent_ids.append(f'item_{index}')
                return {'agent_count': len(raw_agents), 'agent_ids': sorted(agent_ids)[:20], 'catalog_shape': 'list'}
            agent_ids = [str(k) for k in parsed.keys()]
            return {'agent_count': len(agent_ids), 'agent_ids': sorted(agent_ids)[:20], 'catalog_shape': 'mapping'}
        if section == 'policies':
            return {
                'tool_rules': len(list(parsed.get('tool_rules') or [])),
                'memory_rules': len(list(parsed.get('memory_rules') or [])),
                'secret_rules': len(list(parsed.get('secret_rules') or [])),
                'channel_rules': len(list(parsed.get('channel_rules') or [])),
                'approval_rules': len(list(parsed.get('approval_rules') or [])),
            }
        if section == 'evaluations':
            suites = dict(parsed.get('suites') or {})
            return {'suite_count': len(suites), 'suite_names': sorted([str(k) for k in suites.keys()])[:20]}
        return {'keys': [str(k) for k in parsed.keys()]}

    def verify_reproducible_package_manifest(self, *, manifest_path: str) -> dict[str, Any]:
        return self.packaging_hardening_service.verify_reproducible_manifest(manifest_path=manifest_path)

