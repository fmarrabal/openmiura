"""baseline_rollout_support._core_mixin

Sub-mixin extracted from
``openmiura.application.runtime_adapters.external.baseline_rollout_support``
so that no individual file in the package exceeds 1,500 lines. The
public class ``OpenClawBaselineRolloutSupportMixin`` continues to
inherit from this sub-mixin.

The module-level ``OpenClawBaselineRolloutSupportMixin = None`` sentinel
is rebound by ``baseline_rollout_support/__init__.py`` so that the few
``@staticmethod`` call sites that reference the class by name resolve
correctly at call time.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


OpenClawBaselineRolloutSupportMixin: type | None = None  # late-bound by __init__.py


class _OpenClawBaselineRolloutSupportCoreMixinA:
    """Sub-mixin: core methods on OpenClawBaselineRolloutSupportMixin."""

    @staticmethod
    def _normalize_portfolio_baseline_catalog_ref(raw_ref: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(raw_ref or {})
        catalog_id = str(payload.get('catalog_id') or payload.get('baseline_catalog_id') or payload.get('release_id') or '').strip()
        if not catalog_id:
            return {}
        return {
            'catalog_id': catalog_id,
            'catalog_version': str(payload.get('catalog_version') or payload.get('version') or '').strip() or None,
            'inherit_mode': str(payload.get('inherit_mode') or 'merge').strip() or 'merge',
            'enforce_catalog': bool(payload.get('enforce_catalog', True)),
        }

    def _normalize_baseline_catalog_environment_entries(self, raw_policies: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(raw_policies or {})
        normalized: dict[str, Any] = {}
        for env_name, env_payload in payload.items():
            env_key = self._normalize_portfolio_environment_name(env_name)
            if not env_key:
                continue
            entry = dict(env_payload or {})
            base = self._normalize_portfolio_environment_policy_baselines({env_key: entry}).get(env_key) or {}
            if 'approval_policy' not in entry:
                base.pop('approval_policy', None)
            if 'security_gate_policy' not in entry and 'security_envelope' not in entry:
                base.pop('security_gate_policy', None)
            if 'escrow_policy' not in entry:
                base.pop('escrow_policy', None)
            if 'signing_policy' not in entry:
                base.pop('signing_policy', None)
            if 'verification_gate_policy' not in entry:
                base.pop('verification_gate_policy', None)
            if 'operational_tier' not in entry:
                base.pop('operational_tier', None)
            if 'evidence_classification' not in entry and 'classification' not in entry:
                base.pop('evidence_classification', None)
            base['inherits_from'] = self._normalize_portfolio_environment_name(entry.get('inherits_from') or entry.get('parent_environment') or entry.get('extends')) or None
            base['override_mode'] = str(entry.get('override_mode') or 'merge').strip() or 'merge'
            normalized[env_key] = base
        return normalized

    @staticmethod
    def _normalize_baseline_rollout_timezone_mapping(raw_mapping: Any) -> dict[str, str]:
        normalized: dict[str, str] = {}
        if isinstance(raw_mapping, dict):
            iterable = raw_mapping.items()
        else:
            iterable = []
            for entry in list(raw_mapping or []):
                if not isinstance(entry, dict):
                    continue
                iterable.append((entry.get('id') or entry.get('scope_id') or entry.get('portfolio_id') or entry.get('workspace_id') or entry.get('tenant_id') or entry.get('environment'), entry.get('timezone') or entry.get('timezone_name')))
        for key, value in iterable:
            normalized_key = str(key or '').strip()
            timezone_name = str(value or '').strip()
            if normalized_key and timezone_name:
                normalized[normalized_key] = timezone_name
        return normalized

    def _normalize_baseline_rollout_windows(self, raw_windows: Any, *, prefix: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []

        def _window_time(value: Any, *, default: str) -> str:
            hh, mm = self._parse_clock(str(value or default), default=default)
            return f'{hh:02d}:{mm:02d}'

        def _normalize_entry(entry: dict[str, Any], *, idx: int, scope_kind: str = 'global', scope_id: str | None = None) -> dict[str, Any] | None:
            if not isinstance(entry, dict):
                return None
            start_at = entry.get('start_at')
            end_at = entry.get('end_at')
            try:
                normalized_start = float(start_at) if start_at is not None else None
            except Exception:
                normalized_start = None
            try:
                normalized_end = float(end_at) if end_at is not None else None
            except Exception:
                normalized_end = None
            if normalized_start is not None and normalized_end is not None and normalized_end < normalized_start:
                normalized_start, normalized_end = normalized_end, normalized_start
            weekdays = self._normalize_weekdays(entry.get('weekdays') or entry.get('days') or [])
            explicit_window_kind = str(entry.get('window_kind') or '').strip().lower()
            has_clock_fields = entry.get('start_time') is not None or entry.get('end_time') is not None or entry.get('from_time') is not None or entry.get('to_time') is not None
            if explicit_window_kind in {'absolute', 'recurring'}:
                recurring = explicit_window_kind == 'recurring'
            else:
                recurring = bool(entry.get('recurring')) or bool(weekdays) or (has_clock_fields and normalized_start is None and normalized_end is None)
            if not recurring and normalized_start is None and normalized_end is None:
                return None
            tenant_ids = [str(item).strip() for item in list(entry.get('tenant_ids') or []) if str(item).strip()]
            workspace_ids = [str(item).strip() for item in list(entry.get('workspace_ids') or []) if str(item).strip()]
            environments = [self._normalize_portfolio_environment_name(item) for item in list(entry.get('environments') or entry.get('environment_ids') or []) if self._normalize_portfolio_environment_name(item)]
            portfolio_ids = [str(item).strip() for item in list(entry.get('portfolio_ids') or []) if str(item).strip()]
            normalized_scope_id = str(scope_id or entry.get('scope_id') or '').strip()
            if normalized_scope_id:
                if scope_kind == 'tenant' and normalized_scope_id not in tenant_ids:
                    tenant_ids.append(normalized_scope_id)
                elif scope_kind == 'workspace' and normalized_scope_id not in workspace_ids:
                    workspace_ids.append(normalized_scope_id)
                elif scope_kind == 'environment':
                    env_key = self._normalize_portfolio_environment_name(normalized_scope_id)
                    if env_key and env_key not in environments:
                        environments.append(env_key)
                elif scope_kind == 'portfolio' and normalized_scope_id not in portfolio_ids:
                    portfolio_ids.append(normalized_scope_id)
            return {
                'window_id': str(entry.get('window_id') or f'{prefix}-{idx}').strip() or f'{prefix}-{idx}',
                'label': str(entry.get('label') or entry.get('name') or f'{prefix}-{idx}').strip() or f'{prefix}-{idx}',
                'window_kind': 'recurring' if recurring else 'absolute',
                'start_at': normalized_start,
                'end_at': normalized_end,
                'weekdays': weekdays,
                'start_time': _window_time(entry.get('start_time') or entry.get('from_time'), default='00:00'),
                'end_time': _window_time(entry.get('end_time') or entry.get('to_time'), default='23:59'),
                'timezone': str(entry.get('timezone') or entry.get('timezone_name') or '').strip() or None,
                'reason': str(entry.get('reason') or '').strip(),
                'scope_kind': str(scope_kind or 'global').strip() or 'global',
                'scope_id': normalized_scope_id or None,
                'tenant_ids': tenant_ids,
                'workspace_ids': workspace_ids,
                'environments': environments,
                'portfolio_ids': portfolio_ids,
            }

        def _append_from_list(values: Any, *, scope_kind: str = 'global', scope_id: str | None = None, start_index: int = 1) -> int:
            next_index = start_index
            for entry in list(values or []):
                normalized = _normalize_entry(dict(entry or {}), idx=next_index, scope_kind=scope_kind, scope_id=scope_id) if isinstance(entry, dict) else None
                if normalized is None:
                    continue
                items.append(normalized)
                next_index += 1
            return next_index

        index = 1
        if isinstance(raw_windows, dict):
            index = _append_from_list(raw_windows.get('global') or raw_windows.get('default') or raw_windows.get('promotion') or raw_windows.get('all'), scope_kind='global', start_index=index)
            for scope_kind in ('tenant', 'workspace', 'environment', 'portfolio'):
                scoped_values = raw_windows.get(scope_kind)
                if isinstance(scoped_values, dict):
                    for scope_id, scoped_entries in scoped_values.items():
                        index = _append_from_list(scoped_entries, scope_kind=scope_kind, scope_id=str(scope_id or '').strip(), start_index=index)
                else:
                    index = _append_from_list(scoped_values, scope_kind=scope_kind, start_index=index)
        else:
            _append_from_list(raw_windows, scope_kind='global', start_index=index)
        items.sort(key=lambda item: (str(item.get('scope_kind') or ''), str(item.get('scope_id') or ''), 0 if str(item.get('window_kind') or '') == 'absolute' else 1, float(item.get('start_at') or 0.0), str(item.get('start_time') or ''), str(item.get('window_id') or '')))
        return items

    def _validate_raw_baseline_rollout_windows(self, raw_windows: Any, *, field_name: str) -> list[dict[str, Any]]:
        errors: list[dict[str, Any]] = []

        def _append_error(path: str, code: str, *, value: Any = None, reason: str | None = None) -> None:
            errors.append({
                'field': field_name,
                'path': path,
                'code': code,
                'value': value,
                'reason': str(reason or code).strip(),
            })

        def _visit(value: Any, path: str) -> None:
            if isinstance(value, dict) and any(key in value for key in ('global', 'default', 'promotion', 'all', 'tenant', 'workspace', 'environment', 'portfolio')):
                for key in ('global', 'default', 'promotion', 'all'):
                    if key in value:
                        _visit(value.get(key), f'{path}.{key}')
                for scope_key in ('tenant', 'workspace', 'environment', 'portfolio'):
                    scoped = value.get(scope_key)
                    if isinstance(scoped, dict):
                        for scope_id, scoped_entries in scoped.items():
                            _visit(scoped_entries, f'{path}.{scope_key}[{scope_id}]')
                    elif scoped is not None:
                        _visit(scoped, f'{path}.{scope_key}')
                return
            if isinstance(value, dict):
                entries = [value]
            else:
                entries = list(value or [])
            for idx, entry in enumerate(entries, start=1):
                entry_path = f'{path}[{idx}]'
                if not isinstance(entry, dict):
                    _append_error(entry_path, 'window_must_be_object', value=entry)
                    continue
                timezone_name = str(entry.get('timezone') or entry.get('timezone_name') or '').strip()
                if timezone_name and not self._valid_timezone_name(timezone_name):
                    _append_error(f'{entry_path}.timezone', 'invalid_timezone', value=timezone_name)
                start_time = entry.get('start_time') if entry.get('start_time') is not None else entry.get('from_time')
                end_time = entry.get('end_time') if entry.get('end_time') is not None else entry.get('to_time')
                weekdays = entry.get('weekdays') or entry.get('days') or []
                explicit_kind = str(entry.get('window_kind') or '').strip().lower()
                has_clock_fields = start_time is not None or end_time is not None
                is_recurring = explicit_kind == 'recurring' or bool(entry.get('recurring')) or bool(weekdays) or (has_clock_fields and entry.get('start_at') is None and entry.get('end_at') is None)
                if is_recurring:
                    if start_time is None or not self._valid_clock_string(start_time):
                        _append_error(f'{entry_path}.start_time', 'invalid_start_time', value=start_time)
                    if end_time is None or not self._valid_clock_string(end_time):
                        _append_error(f'{entry_path}.end_time', 'invalid_end_time', value=end_time)
                    if self._valid_clock_string(start_time) and self._valid_clock_string(end_time) and str(start_time).strip() == str(end_time).strip():
                        _append_error(entry_path, 'empty_recurring_window', value={'start_time': start_time, 'end_time': end_time})
                    continue
                start_at = entry.get('start_at')
                end_at = entry.get('end_at')
                if start_at is None and end_at is None:
                    _append_error(entry_path, 'window_requires_bounds')
                    continue
                try:
                    normalized_start = float(start_at) if start_at is not None else None
                except Exception:
                    normalized_start = None
                    _append_error(f'{entry_path}.start_at', 'invalid_start_at', value=start_at)
                try:
                    normalized_end = float(end_at) if end_at is not None else None
                except Exception:
                    normalized_end = None
                    _append_error(f'{entry_path}.end_at', 'invalid_end_at', value=end_at)
                if normalized_start is not None and normalized_end is not None and normalized_end < normalized_start:
                    _append_error(entry_path, 'window_end_before_start', value={'start_at': normalized_start, 'end_at': normalized_end})

        _visit(raw_windows, field_name)
        return errors

    def _validate_baseline_rollout_policy(self, raw_policy: dict[str, Any] | None) -> list[dict[str, Any]]:
        payload = dict(raw_policy or {})
        errors: list[dict[str, Any]] = []
        default_timezone = str(payload.get('default_timezone') or payload.get('timezone') or '').strip()
        if default_timezone and not self._valid_timezone_name(default_timezone):
            errors.append({'field': 'default_timezone', 'path': 'rollout_policy.default_timezone', 'code': 'invalid_timezone', 'value': default_timezone, 'reason': 'invalid_timezone'})
        for mapping_field in ('timezone_by_tenant', 'timezone_by_workspace', 'timezone_by_environment', 'timezone_by_portfolio', 'tenant_timezones', 'workspace_timezones', 'environment_timezones', 'portfolio_timezones'):
            mapping = payload.get(mapping_field)
            if isinstance(mapping, dict):
                iterable = mapping.items()
            else:
                iterable = []
                for idx, entry in enumerate(list(mapping or []), start=1):
                    if not isinstance(entry, dict):
                        continue
                    iterable.append((entry.get('id') or entry.get('scope_id') or entry.get('portfolio_id') or entry.get('workspace_id') or entry.get('tenant_id') or entry.get('environment') or idx, entry.get('timezone') or entry.get('timezone_name')))
            for key, value in iterable:
                timezone_name = str(value or '').strip()
                if timezone_name and not self._valid_timezone_name(timezone_name):
                    errors.append({'field': mapping_field, 'path': f'rollout_policy.{mapping_field}[{key}]', 'code': 'invalid_timezone', 'value': timezone_name, 'reason': 'invalid_timezone'})
        errors.extend(self._validate_raw_baseline_rollout_windows(payload.get('maintenance_windows') or payload.get('rollout_windows') or payload.get('calendar_windows') or [], field_name='maintenance_windows'))
        errors.extend(self._validate_raw_baseline_rollout_windows(payload.get('freeze_windows') or [], field_name='freeze_windows'))
        errors.extend(self._validate_raw_baseline_rollout_windows(payload.get('blackout_windows') or payload.get('blackout_calendar') or payload.get('blackout_windows_by_scope') or [], field_name='blackout_windows'))
        return errors

    def _validate_portfolio_train_policy(self, train_policy: dict[str, Any] | None) -> list[dict[str, Any]]:
        payload = dict(train_policy or {})
        errors: list[dict[str, Any]] = []
        for field_name in ('default_timezone', 'rollout_timezone', 'timezone'):
            timezone_name = str(payload.get(field_name) or '').strip()
            if timezone_name and not self._valid_timezone_name(timezone_name):
                errors.append({'field': field_name, 'path': f'train_policy.{field_name}', 'code': 'invalid_timezone', 'value': timezone_name, 'reason': 'invalid_timezone'})
        errors.extend(self._validate_raw_baseline_rollout_windows(payload.get('freeze_windows') or [], field_name='freeze_windows'))
        errors.extend(self._validate_raw_baseline_rollout_windows(payload.get('blackout_windows') or [], field_name='blackout_windows'))
        return errors

    @staticmethod
    def _normalize_baseline_catalog_retry_policy(raw_policy: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(raw_policy or {})
        if isinstance(payload.get('retry_policy'), dict):
            merged = dict(payload)
            merged.update(dict(payload.get('retry_policy') or {}))
            payload = merged
        try:
            max_retries = int(payload.get('max_retries') or payload.get('retry_count') or payload.get('attempts') or 0)
        except Exception:
            max_retries = 0
        try:
            backoff_s = int(payload.get('backoff_s') or payload.get('retry_backoff_s') or payload.get('initial_backoff_s') or 60)
        except Exception:
            backoff_s = 60
        try:
            max_backoff_s = int(payload.get('max_backoff_s') or payload.get('retry_backoff_cap_s') or backoff_s)
        except Exception:
            max_backoff_s = backoff_s
        try:
            backoff_multiplier = float(payload.get('backoff_multiplier') or payload.get('multiplier') or 2.0)
        except Exception:
            backoff_multiplier = 2.0
        return {
            'enabled': bool(payload.get('enabled', True)),
            'max_retries': max(0, max_retries),
            'backoff_s': max(0, backoff_s),
            'max_backoff_s': max(max(0, backoff_s), max_backoff_s),
            'backoff_multiplier': max(1.0, backoff_multiplier),
            'retry_on_advance_failure': bool(payload.get('retry_on_advance_failure', True)),
        }

    def _normalize_baseline_rollout_group_specs(self, raw_groups: Any) -> list[dict[str, Any]]:
        groups: list[dict[str, Any]] = []
        iterable: list[Any]
        if isinstance(raw_groups, dict):
            iterable = []
            for group_id, payload in raw_groups.items():
                if isinstance(payload, dict):
                    entry = dict(payload)
                    entry.setdefault('group_id', group_id)
                else:
                    entry = {'group_id': group_id, 'portfolio_ids': list(payload or [])}
                iterable.append(entry)
        else:
            iterable = list(raw_groups or [])
        for idx, raw_group in enumerate(iterable, start=1):
            if not isinstance(raw_group, dict):
                raw_group = {'portfolio_ids': list(raw_group or [])}
            group_id = str(raw_group.get('group_id') or raw_group.get('id') or raw_group.get('name') or f'group-{idx}').strip() or f'group-{idx}'
            group_label = str(raw_group.get('group_label') or raw_group.get('label') or group_id).strip() or group_id
            portfolio_ids = self._baseline_promotion_unique_ids([str(item).strip() for item in list(raw_group.get('portfolio_ids') or raw_group.get('items') or []) if str(item).strip()])
            if not portfolio_ids:
                continue
            try:
                group_wave_size = int(raw_group.get('wave_size') or raw_group.get('batch_size') or 0)
            except Exception:
                group_wave_size = 0
            groups.append({
                'group_id': group_id,
                'group_label': group_label,
                'portfolio_ids': portfolio_ids,
                'depends_on_groups': self._baseline_promotion_unique_ids([str(item).strip() for item in list(raw_group.get('depends_on_groups') or raw_group.get('depends_on') or []) if str(item).strip()]),
                'exclusive_with_groups': self._baseline_promotion_unique_ids([str(item).strip() for item in list(raw_group.get('exclusive_with_groups') or raw_group.get('excludes') or []) if str(item).strip()]),
                'wave_size': max(0, group_wave_size),
                'metadata': {str(k): v for k, v in dict(raw_group).items() if str(k) not in {'group_id', 'id', 'name', 'group_label', 'label', 'portfolio_ids', 'items', 'depends_on_groups', 'depends_on', 'exclusive_with_groups', 'excludes', 'wave_size', 'batch_size'}},
            })
        return groups

    @staticmethod
    def _baseline_promotion_ratio(value: Any) -> float | None:
        if value in (None, ''):
            return None
        try:
            ratio = float(value)
        except Exception:
            return None
        return max(0.0, min(1.0, ratio))

    def _topological_sort_baseline_group_specs(self, group_specs: list[dict[str, Any]]) -> dict[str, Any]:
        specs = [dict(item) for item in list(group_specs or [])]
        if not specs:
            return {'items': [], 'cycle_detected': False, 'cyclic_group_ids': []}
        order_index = {str(item.get('group_id') or ''): idx for idx, item in enumerate(specs)}
        deps = {
            str(item.get('group_id') or ''): [
                dep for dep in self._baseline_promotion_unique_ids(list(item.get('depends_on_groups') or []))
                if dep and dep != str(item.get('group_id') or '') and dep in order_index
            ]
            for item in specs
        }
        dependents: dict[str, list[str]] = {gid: [] for gid in order_index}
        indegree: dict[str, int] = {gid: len(dep_ids) for gid, dep_ids in deps.items()}
        for gid, dep_ids in deps.items():
            for dep in dep_ids:
                dependents.setdefault(dep, []).append(gid)
        ready = sorted([gid for gid, deg in indegree.items() if deg == 0], key=lambda gid: order_index.get(gid, 0))
        ordered_ids: list[str] = []
        while ready:
            gid = ready.pop(0)
            ordered_ids.append(gid)
            for child in sorted(dependents.get(gid) or [], key=lambda item: order_index.get(item, 0)):
                indegree[child] = max(0, int(indegree.get(child, 0)) - 1)
                if indegree[child] == 0 and child not in ready and child not in ordered_ids:
                    ready.append(child)
            ready.sort(key=lambda item: order_index.get(item, 0))
        remaining = [gid for gid in order_index if gid not in ordered_ids]
        cycle_detected = bool(remaining)
        if remaining:
            ordered_ids.extend(sorted(remaining, key=lambda gid: order_index.get(gid, 0)))
        ordered = []
        by_id = {str(item.get('group_id') or ''): dict(item) for item in specs}
        for gid in ordered_ids:
            spec = dict(by_id.get(gid) or {})
            spec['depends_on_groups'] = [dep for dep in list(spec.get('depends_on_groups') or []) if dep in by_id and dep != gid]
            ordered.append(spec)
        return {'items': ordered, 'cycle_detected': cycle_detected, 'cyclic_group_ids': remaining}

    def _normalize_baseline_catalog_rollout_policy(self, raw_policy: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(raw_policy or {})
        try:
            wave_size = int(payload.get('wave_size') or payload.get('batch_size') or 0)
        except Exception:
            wave_size = 0
        try:
            auto_advance_window_s = int(payload.get('auto_advance_window_s') or payload.get('advance_window_s') or payload.get('advance_after_s') or 0)
        except Exception:
            auto_advance_window_s = 0
        explicit_waves: list[dict[str, Any]] = []
        for idx, raw_wave in enumerate(list(payload.get('waves') or []), start=1):
            if isinstance(raw_wave, dict):
                portfolio_ids = [str(item).strip() for item in list(raw_wave.get('portfolio_ids') or raw_wave.get('items') or []) if str(item).strip()]
                wave_label = str(raw_wave.get('wave_label') or raw_wave.get('name') or f'wave-{idx}').strip() or f'wave-{idx}'
            else:
                portfolio_ids = [str(item).strip() for item in list(raw_wave or []) if str(item).strip()]
                wave_label = f'wave-{idx}'
            if not portfolio_ids:
                continue
            explicit_waves.append({'wave_no': idx, 'wave_label': wave_label, 'portfolio_ids': portfolio_ids})
        auto_advance_enabled = bool(payload.get('auto_advance', payload.get('auto_advance_enabled', False)))
        if auto_advance_window_s > 0:
            auto_advance_enabled = True
        maintenance_windows = self._normalize_baseline_rollout_windows(payload.get('maintenance_windows') or payload.get('rollout_windows') or payload.get('calendar_windows') or [], prefix='maintenance')
        freeze_windows = self._normalize_baseline_rollout_windows(payload.get('freeze_windows') or [], prefix='freeze')
        blackout_windows = self._normalize_baseline_rollout_windows(payload.get('blackout_windows') or payload.get('blackout_calendar') or payload.get('blackout_windows_by_scope') or [], prefix='blackout')
        return {
            'enabled': bool(payload.get('enabled', False)),
            'wave_size': max(0, wave_size),
            'waves': explicit_waves,
            'portfolio_groups': self._normalize_baseline_rollout_group_specs(payload.get('portfolio_groups') or payload.get('groups') or []),
            'dependency_graph': self._normalize_portfolio_dependency_graph(payload.get('dependency_graph') or payload.get('portfolio_dependencies') or {}),
            'auto_apply_first_wave': bool(payload.get('auto_apply_first_wave', True)),
            'require_manual_advance': bool(payload.get('require_manual_advance', True)),
            'auto_advance': auto_advance_enabled,
            'auto_advance_window_s': max(0, auto_advance_window_s),
            'default_timezone': str(payload.get('default_timezone') or payload.get('timezone') or 'UTC').strip() or 'UTC',
            'timezone_by_tenant': self._normalize_baseline_rollout_timezone_mapping(payload.get('timezone_by_tenant') or payload.get('tenant_timezones') or {}),
            'timezone_by_workspace': self._normalize_baseline_rollout_timezone_mapping(payload.get('timezone_by_workspace') or payload.get('workspace_timezones') or {}),
            'timezone_by_environment': self._normalize_baseline_rollout_timezone_mapping(payload.get('timezone_by_environment') or payload.get('environment_timezones') or {}),
            'timezone_by_portfolio': self._normalize_baseline_rollout_timezone_mapping(payload.get('timezone_by_portfolio') or payload.get('portfolio_timezones') or {}),
            'maintenance_windows': maintenance_windows,
            'freeze_windows': freeze_windows + blackout_windows,
            'blackout_windows': blackout_windows,
            'retry_policy': self._normalize_baseline_catalog_retry_policy(dict(payload.get('retry_policy') or payload)),
        }

    def _normalize_baseline_catalog_gate_policy(self, raw_policy: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(raw_policy or {})
        try:
            max_nonconformant_count = int(payload.get('max_nonconformant_count') or 0)
        except Exception:
            max_nonconformant_count = 0
        try:
            max_blocking_baseline_drift_count = int(payload.get('max_blocking_baseline_drift_count') or payload.get('max_baseline_drift_count') or 0)
        except Exception:
            max_blocking_baseline_drift_count = 0
        try:
            max_warning_count = int(payload.get('max_warning_count') or 0)
        except Exception:
            max_warning_count = 0
        try:
            max_warning_portfolio_count = int(payload.get('max_warning_portfolio_count') or 0)
        except Exception:
            max_warning_portfolio_count = 0
        try:
            max_total_fail_count = int(payload.get('max_total_fail_count') or 0)
        except Exception:
            max_total_fail_count = 0
        try:
            max_nonconformant_delta = int(payload.get('max_nonconformant_delta') or 0)
        except Exception:
            max_nonconformant_delta = 0
        try:
            max_blocking_baseline_drift_delta = int(payload.get('max_blocking_baseline_drift_delta') or 0)
        except Exception:
            max_blocking_baseline_drift_delta = 0
        try:
            max_warning_delta = int(payload.get('max_warning_delta') or 0)
        except Exception:
            max_warning_delta = 0
        max_nonconformant_ratio = self._baseline_promotion_ratio(payload.get('max_nonconformant_ratio'))
        min_conformance_ratio = self._baseline_promotion_ratio(payload.get('min_conformance_ratio'))
        if min_conformance_ratio is not None:
            implied = round(max(0.0, 1.0 - float(min_conformance_ratio)), 4)
            if max_nonconformant_ratio is None:
                max_nonconformant_ratio = implied
        return {
            'enabled': bool(payload.get('enabled', True)),
            'block_on_nonconformant': bool(payload.get('block_on_nonconformant', True)),
            'max_nonconformant_count': max(0, max_nonconformant_count),
            'max_nonconformant_ratio': max_nonconformant_ratio,
            'block_on_baseline_drift': bool(payload.get('block_on_baseline_drift', True)),
            'max_blocking_baseline_drift_count': max(0, max_blocking_baseline_drift_count),
            'max_blocking_baseline_drift_ratio': self._baseline_promotion_ratio(payload.get('max_blocking_baseline_drift_ratio')),
            'block_on_warning': bool(payload.get('block_on_warning', False)),
            'max_warning_count': max(0, max_warning_count),
            'max_warning_ratio': self._baseline_promotion_ratio(payload.get('max_warning_ratio')),
            'max_warning_portfolio_count': max(0, max_warning_portfolio_count),
            'max_warning_portfolio_ratio': self._baseline_promotion_ratio(payload.get('max_warning_portfolio_ratio')),
            'max_total_fail_count': max(0, max_total_fail_count),
            'block_on_health_regression': bool(payload.get('block_on_health_regression', False)),
            'max_nonconformant_delta': max(0, max_nonconformant_delta),
            'max_blocking_baseline_drift_delta': max(0, max_blocking_baseline_drift_delta),
            'max_warning_delta': max(0, max_warning_delta),
        }

    def _normalize_baseline_catalog_rollback_policy(self, raw_policy: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(raw_policy or {})
        return {
            'enabled': bool(payload.get('enabled', True)),
            'scope': str(payload.get('scope') or 'applied_waves').strip() or 'applied_waves',
            'rollback_on_gate_failure': bool(payload.get('rollback_on_gate_failure', True)),
            'rollback_on_manual_trigger': bool(payload.get('rollback_on_manual_trigger', True)),
        }

    def _normalize_baseline_catalog_promotion_policy(self, raw_policy: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(raw_policy or {})
        approval_policy = self._normalize_portfolio_approval_policy(dict(payload.get('approval_policy') or payload))
        try:
            simulation_ttl_s = int(payload.get('simulation_ttl_s') or dict(payload.get('simulation_policy') or {}).get('ttl_s') or 0)
        except Exception:
            simulation_ttl_s = 0
        simulation_review_raw = dict(
            payload.get('simulation_review_policy')
            or payload.get('simulation_approval_policy')
            or {}
        )
        if not simulation_review_raw and isinstance(payload.get('simulation_policy'), dict):
            simulation_review_raw = dict((payload.get('simulation_policy') or {}).get('approval_policy') or {})
        simulation_review_settings = dict(simulation_review_raw or {})
        simulation_review_approval_policy = self._normalize_portfolio_approval_policy(
            dict(simulation_review_settings.get('approval_policy') or simulation_review_settings)
        )
        simulation_review_policy = {
            'enabled': bool(simulation_review_approval_policy.get('enabled')),
            'approval_policy': simulation_review_approval_policy,
            'allow_self_review': bool(simulation_review_settings.get('allow_self_review', True)),
            'require_reason': bool(simulation_review_settings.get('require_reason', False)),
            'block_on_rejection': bool(
                simulation_review_settings.get(
                    'block_on_rejection',
                    simulation_review_approval_policy.get('block_on_rejection', True),
                )
            ),
        }
        simulation_custody_monitoring_policy = self._normalize_baseline_promotion_simulation_custody_monitoring_policy(
            dict(
                payload.get('simulation_custody_monitoring_policy')
                or payload.get('simulation_monitoring_policy')
                or payload.get('custody_monitoring_policy')
                or payload.get('simulation_evidence_monitoring_policy')
                or {}
            )
        )
        return {
            'enabled': bool(payload.get('enabled', True)),
            'approval_policy': approval_policy,
            'simulation_review_policy': simulation_review_policy,
            'rollout_evidence_required': bool(payload.get('rollout_evidence_required', True)),
            'simulation_ttl_s': max(0, simulation_ttl_s),
            'simulation_custody_monitoring_policy': simulation_custody_monitoring_policy,
            'rollout_policy': self._normalize_baseline_catalog_rollout_policy(dict(payload.get('rollout_policy') or payload.get('release_train_policy') or {})),
            'gate_policy': self._normalize_baseline_catalog_gate_policy(dict(payload.get('gate_policy') or payload.get('slo_policy') or {})),
            'rollback_policy': self._normalize_baseline_catalog_rollback_policy(dict(payload.get('rollback_policy') or {})),
        }

    @staticmethod
    def _append_baseline_promotion_timeline_event(promotion: dict[str, Any], *, kind: str, label: str, ts: float | None = None, **extra: Any) -> dict[str, Any]:
        updated = dict(promotion or {})
        timeline = [dict(item) for item in list(updated.get('timeline') or [])]
        timeline.append({
            'ts': float(ts if ts is not None else time.time()),
            'kind': str(kind or '').strip() or 'event',
            'label': str(label or '').strip() or 'baseline_promotion_event',
            **{str(key): value for key, value in extra.items() if value is not None},
        })
        timeline.sort(key=lambda item: (float(item.get('ts') or 0.0), str(item.get('kind') or ''), str(item.get('label') or '')))
        updated['timeline'] = timeline[-250:]
        return updated

    @staticmethod
    def _baseline_promotion_unique_ids(values: list[str] | None) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for raw in list(values or []):
            value = str(raw or '').strip()
            if not value or value in seen:
                continue
            seen.add(value)
            result.append(value)
        return result

    def _baseline_rollout_window_contains(window: dict[str, Any], ts: float) -> bool:
        start_at = window.get('start_at')
        end_at = window.get('end_at')
        if start_at is not None and float(ts) < float(start_at):
            return False
        if end_at is not None and float(ts) >= float(end_at):
            return False
        return True

    def _baseline_rollout_resolved_timezone(
        self,
        *,
        rollout_policy: dict[str, Any] | None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        portfolio_release: dict[str, Any] | None = None,
    ) -> str:
        policy = self._normalize_baseline_catalog_rollout_policy(dict(rollout_policy or {}))
        timezone_name = str(policy.get('default_timezone') or 'UTC').strip() or 'UTC'
        tenant_map = dict(policy.get('timezone_by_tenant') or {})
        workspace_map = dict(policy.get('timezone_by_workspace') or {})
        environment_map = dict(policy.get('timezone_by_environment') or {})
        portfolio_map = dict(policy.get('timezone_by_portfolio') or {})
        if tenant_id and tenant_map.get(str(tenant_id)):
            timezone_name = str(tenant_map.get(str(tenant_id)) or timezone_name)
        if workspace_id and workspace_map.get(str(workspace_id)):
            timezone_name = str(workspace_map.get(str(workspace_id)) or timezone_name)
        env_key = self._normalize_portfolio_environment_name(environment or (portfolio_release or {}).get('environment'))
        if env_key and environment_map.get(env_key):
            timezone_name = str(environment_map.get(env_key) or timezone_name)
        portfolio_id = str((portfolio_release or {}).get('release_id') or '').strip()
        if portfolio_id and portfolio_map.get(portfolio_id):
            timezone_name = str(portfolio_map.get(portfolio_id) or timezone_name)
        if portfolio_release is not None:
            portfolio = dict(((portfolio_release.get('metadata') or {}).get('portfolio') or {}) or {})
            raw_train_policy = dict(portfolio.get('train_policy') or {})
            portfolio_timezone = str(raw_train_policy.get('rollout_timezone') or '').strip()
            if portfolio_timezone:
                timezone_name = portfolio_timezone
        return timezone_name or 'UTC'

    def _baseline_rollout_window_applies(
        self,
        window: dict[str, Any] | None,
        *,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        portfolio_id: str | None = None,
    ) -> bool:
        payload = dict(window or {})
        tenant_ids = [str(item).strip() for item in list(payload.get('tenant_ids') or []) if str(item).strip()]
        workspace_ids = [str(item).strip() for item in list(payload.get('workspace_ids') or []) if str(item).strip()]
        environments = [self._normalize_portfolio_environment_name(item) for item in list(payload.get('environments') or []) if self._normalize_portfolio_environment_name(item)]
        portfolio_ids = [str(item).strip() for item in list(payload.get('portfolio_ids') or []) if str(item).strip()]
        env_key = self._normalize_portfolio_environment_name(environment)
        if tenant_ids and str(tenant_id or '').strip() not in tenant_ids:
            return False
        if workspace_ids and str(workspace_id or '').strip() not in workspace_ids:
            return False
        if environments and env_key not in environments:
            return False
        if portfolio_ids and str(portfolio_id or '').strip() not in portfolio_ids:
            return False
        return True

    def _baseline_rollout_window_state(
        self,
        window: dict[str, Any] | None,
        *,
        now_ts: float,
        default_timezone: str = 'UTC',
    ) -> dict[str, Any]:
        payload = dict(window or {})
        timezone_name = str(payload.get('timezone') or default_timezone or 'UTC').strip() or 'UTC'
        if str(payload.get('window_kind') or 'absolute') == 'recurring':
            state = self._recurring_window_state(
                weekdays=list(payload.get('weekdays') or []),
                start_time=str(payload.get('start_time') or '00:00'),
                end_time=str(payload.get('end_time') or '23:59'),
                timezone_name=timezone_name,
                now_ts=float(now_ts),
            )
        else:
            state = self._absolute_window_state(starts_at=payload.get('start_at'), ends_at=payload.get('end_at'), now_ts=float(now_ts))
            state['timezone'] = timezone_name
        return {
            **payload,
            **state,
            'timezone': timezone_name,
        }

    def _baseline_rollout_next_allowed_time(
        self,
        *,
        rollout_policy: dict[str, Any] | None,
        requested_at: float,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        portfolio_release: dict[str, Any] | None = None,
        maintenance_already_satisfied: bool = False,
    ) -> dict[str, Any]:
        policy = self._normalize_baseline_catalog_rollout_policy(dict(rollout_policy or {}))
        portfolio_id = str((portfolio_release or {}).get('release_id') or '').strip() or None
        resolved_timezone = self._baseline_rollout_resolved_timezone(
            rollout_policy=policy,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment or (portfolio_release or {}).get('environment'),
            portfolio_release=portfolio_release,
        )
        maintenance_windows = [
            dict(item)
            for item in list(policy.get('maintenance_windows') or [])
            if self._baseline_rollout_window_applies(item, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment or (portfolio_release or {}).get('environment'), portfolio_id=portfolio_id)
        ]
        freeze_windows = [
            dict(item)
            for item in list(policy.get('freeze_windows') or [])
            if self._baseline_rollout_window_applies(item, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment or (portfolio_release or {}).get('environment'), portfolio_id=portfolio_id)
        ]
        candidate = float(requested_at)
        blockers: list[str] = []
        blocker_windows: list[dict[str, Any]] = []
        maintenance_satisfied = bool(maintenance_already_satisfied) or not bool(maintenance_windows)
        selected_maintenance_windows: list[dict[str, Any]] = []
        for _ in range(0, 20):
            active_maintenance: list[dict[str, Any]] = []
            if not maintenance_satisfied:
                active_maintenance = [self._baseline_rollout_window_state(window, now_ts=candidate, default_timezone=resolved_timezone) for window in maintenance_windows]
                active_maintenance = [window for window in active_maintenance if bool(window.get('active'))]
                if maintenance_windows and not active_maintenance:
                    future_starts = []
                    future_windows: list[dict[str, Any]] = []
                    for window in maintenance_windows:
                        state = self._baseline_rollout_window_state(window, now_ts=candidate, default_timezone=resolved_timezone)
                        next_start = state.get('next_start_at')
                        if next_start is None or float(next_start) <= candidate:
                            continue
                        future_starts.append(float(next_start))
                        future_windows.append(state)
                    if not future_starts:
                        return {
                            'allowed': False,
                            'reason': 'outside_maintenance_window',
                            'requested_at': float(requested_at),
                            'next_allowed_at': None,
                            'maintenance_windows': maintenance_windows,
                            'freeze_windows': freeze_windows,
                            'blockers': self._baseline_promotion_unique_ids(blockers + ['maintenance_window']),
                            'blocker_windows': blocker_windows + future_windows,
                            'resolved_timezone': resolved_timezone,
                            'maintenance_satisfied': maintenance_satisfied,
                        }
                    blockers.append('maintenance_window')
                    blocker_windows.extend(future_windows)
                    selected_maintenance_windows = future_windows
                    candidate = min(future_starts)
                    maintenance_satisfied = True
                    continue
                selected_maintenance_windows = active_maintenance
                maintenance_satisfied = True
            active_freezes = [self._baseline_rollout_window_state(window, now_ts=candidate, default_timezone=resolved_timezone) for window in freeze_windows]
            active_freezes = [window for window in active_freezes if bool(window.get('active'))]
            if active_freezes:
                freeze_ends = [float(window.get('active_until')) for window in active_freezes if window.get('active_until') is not None]
                if len(freeze_ends) != len(active_freezes):
                    return {
                        'allowed': False,
                        'reason': 'freeze_window_active_without_end',
                        'requested_at': float(requested_at),
                        'next_allowed_at': None,
                        'maintenance_windows': selected_maintenance_windows,
                        'freeze_windows': active_freezes,
                        'blockers': self._baseline_promotion_unique_ids(blockers + ['freeze_window']),
                        'blocker_windows': blocker_windows + active_freezes,
                        'resolved_timezone': resolved_timezone,
                        'maintenance_satisfied': maintenance_satisfied,
                    }
                blockers.append('freeze_window')
                blocker_windows.extend(active_freezes)
                candidate = max(freeze_ends)
                continue
            return {
                'allowed': True,
                'requested_at': float(requested_at),
                'next_allowed_at': float(candidate),
                'maintenance_windows': selected_maintenance_windows,
                'freeze_windows': [],
                'blockers': self._baseline_promotion_unique_ids(blockers),
                'blocker_windows': blocker_windows,
                'resolved_timezone': resolved_timezone,
                'maintenance_satisfied': maintenance_satisfied,
            }
        return {
            'allowed': False,
            'reason': 'window_resolution_exceeded',
            'requested_at': float(requested_at),
            'next_allowed_at': None,
            'maintenance_windows': selected_maintenance_windows or maintenance_windows,
            'freeze_windows': freeze_windows,
            'blockers': self._baseline_promotion_unique_ids(blockers),
            'blocker_windows': blocker_windows,
            'resolved_timezone': resolved_timezone,
            'maintenance_satisfied': maintenance_satisfied,
        }

