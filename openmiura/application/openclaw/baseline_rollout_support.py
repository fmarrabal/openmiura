from __future__ import annotations

import base64
import hashlib
import io
import json
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class OpenClawBaselineRolloutSupportMixin:
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

    def _normalize_baseline_promotion_simulation_custody_monitoring_policy(self, raw_policy: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(raw_policy or {})
        fallback_target_path = str(payload.get('target_path') or '/ui/?tab=operator').strip() or '/ui/?tab=operator'
        try:
            interval_s = int(payload.get('interval_s') or payload.get('reconcile_every_s') or 3600)
        except Exception:
            interval_s = 3600
        try:
            max_alerts = int(payload.get('max_alerts') or 20)
        except Exception:
            max_alerts = 20
        try:
            dedupe_window_s = int(payload.get('dedupe_window_s') or 0)
        except Exception:
            dedupe_window_s = 0
        try:
            default_mute_s = int(payload.get('default_mute_s') or payload.get('mute_default_s') or 3600)
        except Exception:
            default_mute_s = 3600
        try:
            suppression_window_s = int(payload.get('suppression_window_s') or payload.get('notification_suppression_window_s') or 0)
        except Exception:
            suppression_window_s = 0
        raw_levels = list(payload.get('escalation_levels') or payload.get('escalations') or [])
        if not raw_levels:
            fallback_after_s = payload.get('escalate_after_s') or payload.get('ack_timeout_s') or payload.get('escalation_after_s')
            if fallback_after_s is not None:
                raw_levels = [{
                    'after_s': fallback_after_s,
                    'severity': payload.get('escalation_severity') or payload.get('severity') or 'critical',
                    'label': payload.get('escalation_label') or 'Escalated custody drift',
                    'route_id': payload.get('escalation_route_id') or 'escalation-route-1',
                    'queue_id': payload.get('escalation_queue_id') or payload.get('queue_id') or '',
                    'queue_label': payload.get('escalation_queue_label') or payload.get('queue_label') or payload.get('queue_name') or '',
                    'owner_role': payload.get('escalation_owner_role') or payload.get('owner_role') or payload.get('default_owner_role') or '',
                    'owner_id': payload.get('escalation_owner_id') or payload.get('owner_id') or payload.get('default_owner_id') or '',
                }]
        levels = []
        for index, raw_level in enumerate(raw_levels, start=1):
            level_payload = dict(raw_level or {})
            try:
                after_s = int(level_payload.get('after_s') or level_payload.get('delay_s') or level_payload.get('ack_timeout_s') or 0)
            except Exception:
                after_s = 0
            try:
                level_no = int(level_payload.get('level') or index)
            except Exception:
                level_no = index
            levels.append({
                'level': max(1, level_no),
                'after_s': max(0, after_s),
                'severity': str(level_payload.get('severity') or payload.get('escalation_severity') or 'critical').strip() or 'critical',
                'label': str(level_payload.get('label') or f'Escalation level {index}').strip() or f'Escalation level {index}',
                'target_path': str(level_payload.get('target_path') or payload.get('escalation_target_path') or fallback_target_path).strip() or fallback_target_path,
                'route_id': str(level_payload.get('route_id') or level_payload.get('id') or f'escalation-route-{index}').strip() or f'escalation-route-{index}',
                'queue_id': str(level_payload.get('queue_id') or level_payload.get('queue') or payload.get('escalation_queue_id') or payload.get('default_queue_id') or '').strip(),
                'queue_label': str(level_payload.get('queue_label') or level_payload.get('queue_name') or level_payload.get('queue') or payload.get('escalation_queue_label') or payload.get('default_queue_label') or payload.get('queue_label') or '').strip(),
                'owner_role': str(level_payload.get('owner_role') or level_payload.get('requested_role') or payload.get('escalation_owner_role') or payload.get('default_owner_role') or '').strip(),
                'owner_id': str(level_payload.get('owner_id') or level_payload.get('assignee') or payload.get('escalation_owner_id') or payload.get('default_owner_id') or '').strip(),
            })
        levels.sort(key=lambda item: (int(item.get('after_s') or 0), int(item.get('level') or 0)))
        for index, item in enumerate(levels, start=1):
            item['level'] = max(index, int(item.get('level') or index))
        raw_default_route = dict(payload.get('default_route') or {})
        if not raw_default_route:
            raw_default_route = {
                'route_id': payload.get('default_route_id') or 'default-route',
                'label': payload.get('default_route_label') or 'Default custody route',
                'queue_id': payload.get('default_queue_id') or payload.get('queue_id') or '',
                'queue_label': payload.get('default_queue_label') or payload.get('queue_label') or payload.get('queue_name') or '',
                'owner_role': payload.get('default_owner_role') or payload.get('owner_role') or '',
                'owner_id': payload.get('default_owner_id') or payload.get('owner_id') or '',
                'target_path': payload.get('target_path') or fallback_target_path,
                'severity': payload.get('severity') or 'warning',
                'min_escalation_level': 0,
            }
        default_route = self._normalize_baseline_promotion_simulation_custody_route(raw_default_route, index=0, fallback_target_path=fallback_target_path)
        raw_routes = list(payload.get('routing_routes') or payload.get('routes') or payload.get('ownership_routes') or payload.get('escalation_routes') or [])
        routes = [
            self._normalize_baseline_promotion_simulation_custody_route(raw_route, index=index, fallback_target_path=fallback_target_path)
            for index, raw_route in enumerate(raw_routes, start=1)
        ]
        if any(default_route.get(key) for key in ('queue_id', 'owner_role', 'owner_id', 'target_path')):
            routes.append(default_route)
        for level in levels:
            if any(level.get(key) for key in ('queue_id', 'owner_role', 'owner_id')):
                routes.append(self._normalize_baseline_promotion_simulation_custody_route({
                    'route_id': level.get('route_id') or f'escalation-route-{int(level.get("level") or 0)}',
                    'label': level.get('label') or f'Escalation level {int(level.get("level") or 0)}',
                    'min_escalation_level': int(level.get('level') or 0),
                    'queue_id': level.get('queue_id') or '',
                    'queue_label': level.get('queue_label') or '',
                    'owner_role': level.get('owner_role') or '',
                    'owner_id': level.get('owner_id') or '',
                    'target_path': level.get('target_path') or fallback_target_path,
                    'severity': level.get('severity') or '',
                }, index=int(level.get('level') or 0), fallback_target_path=fallback_target_path))
        unique_routes: list[dict[str, Any]] = []
        seen_route_ids: set[str] = set()
        for route in sorted(routes, key=lambda item: (int(item.get('min_escalation_level') or 0), str(item.get('route_id') or ''))):
            route_id = str(route.get('route_id') or '').strip()
            if not route_id or route_id in seen_route_ids:
                continue
            seen_route_ids.add(route_id)
            unique_routes.append(route)
        routes = unique_routes
        escalation_enabled = bool(payload.get('escalation_enabled', bool(levels)))
        try:
            max_escalations = int(payload.get('max_escalations') or len(levels) or 3)
        except Exception:
            max_escalations = max(len(levels), 3)
        routing_enabled = bool(payload.get('routing_enabled', bool(routes)))
        routing_enabled = bool(payload.get('routing_enabled', bool(routes)))
        ownership_enabled = bool(payload.get('ownership_enabled', routing_enabled or bool(default_route.get('owner_role')) or bool(default_route.get('owner_id'))))
        handoff_enabled = bool(payload.get('handoff_enabled', ownership_enabled))
        handoff_require_reason = bool(payload.get('handoff_require_reason', False))
        sla_payload = dict(payload.get('sla_policy') or payload.get('sla') or {})
        def _sla_int(*keys: str, default: int = 0) -> int:
            for key in keys:
                value = sla_payload.get(key) if key in sla_payload else payload.get(key)
                if value is None:
                    continue
                try:
                    return max(0, int(value))
                except Exception:
                    continue
            return max(0, int(default or 0))
        try:
            warning_ratio = float(sla_payload.get('warning_ratio') if 'warning_ratio' in sla_payload else payload.get('sla_warning_ratio', payload.get('warning_ratio', 0.8)))
        except Exception:
            warning_ratio = 0.8
        warning_ratio = min(0.95, max(0.0, warning_ratio))
        acknowledge_s = _sla_int('acknowledge_s', 'ack_s', 'first_response_s', default=0)
        claim_s = _sla_int('claim_s', 'ownership_s', 'owner_claim_s', default=0)
        resolve_s = _sla_int('resolve_s', 'resolution_s', 'clear_s', default=0)
        handoff_accept_s = _sla_int('handoff_accept_s', 'handoff_s', 'handoff_ack_s', default=0)
        sla_enabled = bool(sla_payload.get('enabled', payload.get('sla_enabled', any([acknowledge_s, claim_s, resolve_s, handoff_accept_s]))))
        sla_policy = {
            'enabled': sla_enabled,
            'acknowledge_s': acknowledge_s,
            'claim_s': claim_s,
            'resolve_s': resolve_s,
            'handoff_accept_s': handoff_accept_s,
            'warning_ratio': warning_ratio,
            'notify_on_breach': bool(sla_payload.get('notify_on_breach', payload.get('notify_on_sla_breach', True))),
            'severity': str(sla_payload.get('severity') or payload.get('sla_severity') or 'high').strip() or 'high',
            'target_path': str(sla_payload.get('target_path') or payload.get('sla_target_path') or fallback_target_path).strip() or fallback_target_path,
        }
        raw_team_escalation_queues = list(
            payload.get('team_escalation_queues')
            or payload.get('sla_team_queues')
            or payload.get('sla_breach_routes')
            or []
        )
        team_escalation_queues = []
        for index, raw_route in enumerate(raw_team_escalation_queues, start=1):
            route_payload = dict(raw_route or {})
            normalized_route = self._normalize_baseline_promotion_simulation_custody_route({
                **route_payload,
                'route_id': route_payload.get('route_id') or route_payload.get('id') or f'sla-team-route-{index}',
                'label': route_payload.get('label') or route_payload.get('name') or f'SLA team queue {index}',
                'target_path': route_payload.get('target_path') or sla_policy.get('target_path') or fallback_target_path,
                'severity': route_payload.get('severity') or sla_policy.get('severity') or payload.get('severity') or '',
            }, index=index, fallback_target_path=sla_policy.get('target_path') or fallback_target_path)
            normalized_route['breach_targets'] = [
                str(item).strip()
                for item in list(route_payload.get('breach_targets') or route_payload.get('on_targets') or route_payload.get('targets') or [])
                if str(item).strip()
            ]
            normalized_route['queue_type'] = str(route_payload.get('queue_type') or route_payload.get('type') or 'team_escalation').strip() or 'team_escalation'
            team_escalation_queues.append(normalized_route)
        raw_sla_breach_route = dict(payload.get('sla_breach_route') or {})
        if not raw_sla_breach_route and any(payload.get(key) is not None for key in ('sla_breach_route_id', 'sla_breach_queue_id', 'sla_breach_owner_role', 'sla_breach_owner_id')):
            raw_sla_breach_route = {
                'route_id': payload.get('sla_breach_route_id') or 'sla-breach-route',
                'label': payload.get('sla_breach_route_label') or 'SLA breach route',
                'queue_id': payload.get('sla_breach_queue_id') or '',
                'queue_label': payload.get('sla_breach_queue_label') or payload.get('sla_breach_queue_id') or '',
                'owner_role': payload.get('sla_breach_owner_role') or '',
                'owner_id': payload.get('sla_breach_owner_id') or '',
                'target_path': payload.get('sla_breach_target_path') or sla_policy.get('target_path') or fallback_target_path,
                'severity': payload.get('sla_breach_severity') or sla_policy.get('severity') or '',
            }
        sla_breach_route = self._normalize_baseline_promotion_simulation_custody_route(raw_sla_breach_route, index=0, fallback_target_path=sla_policy.get('target_path') or fallback_target_path) if raw_sla_breach_route else {}
        auto_reroute_on_sla_breach = bool(payload.get('auto_reroute_on_sla_breach', bool(team_escalation_queues) or bool(sla_breach_route)))
        raw_queue_capacities = list(payload.get('queue_capacities') or payload.get('queue_capacity_map') or payload.get('queue_capacity_routes') or [])
        if isinstance(payload.get('queue_capacity_map'), dict):
            raw_queue_capacities = [
                {'queue_id': key, **(dict(value or {}) if isinstance(value, dict) else {'capacity': value})}
                for key, value in dict(payload.get('queue_capacity_map') or {}).items()
            ]
        queue_capacities = []
        for index, raw_queue in enumerate(raw_queue_capacities, start=1):
            queue_payload = dict(raw_queue or {})
            queue_id = str(queue_payload.get('queue_id') or queue_payload.get('queue') or '').strip()
            if not queue_id:
                continue
            try:
                queue_capacity = int(queue_payload.get('capacity') or queue_payload.get('queue_capacity') or queue_payload.get('max_active_alerts') or 0)
            except Exception:
                queue_capacity = 0
            try:
                queue_warning = int(queue_payload.get('warning_capacity') or queue_payload.get('warning_threshold') or max(0, queue_capacity - 1)) if queue_capacity > 0 else 0
            except Exception:
                queue_warning = max(0, queue_capacity - 1)
            reserved_for_queue_types = [
                str(item).strip()
                for item in list(queue_payload.get('reserved_for_queue_types') or queue_payload.get('reserved_queue_types') or [])
                if str(item).strip()
            ]
            reserved_for_severities = [
                str(item).strip().lower()
                for item in list(queue_payload.get('reserved_for_severities') or queue_payload.get('reserved_severities') or [])
                if str(item).strip()
            ]
            try:
                reserved_capacity = int(queue_payload.get('reserved_capacity') or queue_payload.get('queue_reserved_capacity') or 0)
            except Exception:
                reserved_capacity = 0
            leased_for_queue_types = [
                str(item).strip()
                for item in list(queue_payload.get('leased_for_queue_types') or queue_payload.get('lease_for_queue_types') or queue_payload.get('leased_queue_types') or [])
                if str(item).strip()
            ]
            leased_for_severities = [
                str(item).strip().lower()
                for item in list(queue_payload.get('leased_for_severities') or queue_payload.get('lease_for_severities') or queue_payload.get('leased_severities') or [])
                if str(item).strip()
            ]
            try:
                leased_capacity = int(queue_payload.get('leased_capacity') or queue_payload.get('lease_capacity') or 0)
            except Exception:
                leased_capacity = 0
            lease_expires_at = queue_payload.get('lease_expires_at') or queue_payload.get('leased_until') or queue_payload.get('lease_until')
            temporary_holds = [
                dict(item or {})
                for item in list(queue_payload.get('temporary_holds') or queue_payload.get('queue_holds') or queue_payload.get('holds') or [])
                if isinstance(item, dict)
            ]
            queue_capacities.append({
                'queue_id': queue_id,
                'queue_label': str(queue_payload.get('queue_label') or queue_payload.get('label') or queue_id).strip() or queue_id,
                'capacity': max(0, int(queue_capacity or 0)),
                'warning_capacity': max(0, int(queue_warning or 0)),
                'hard_limit': bool(queue_payload.get('hard_limit', queue_payload.get('queue_hard_limit', False))),
                'queue_type': str(queue_payload.get('queue_type') or queue_payload.get('type') or '').strip(),
                'target_path': str(queue_payload.get('target_path') or fallback_target_path).strip() or fallback_target_path,
                'owner_role': str(queue_payload.get('owner_role') or '').strip(),
                'owner_id': str(queue_payload.get('owner_id') or '').strip(),
                'queue_family_id': str(queue_payload.get('queue_family_id') or queue_payload.get('family_id') or queue_payload.get('family') or '').strip(),
                'queue_family_label': str(queue_payload.get('queue_family_label') or queue_payload.get('family_label') or queue_payload.get('queue_family_id') or queue_payload.get('family_id') or queue_payload.get('family') or '').strip(),
                'load_weight': max(0.1, float(queue_payload.get('load_weight') or queue_payload.get('queue_weight') or 1.0)),
                'reserved_capacity': max(0, int(reserved_capacity or 0)),
                'reserved_for_queue_types': reserved_for_queue_types,
                'reserved_for_severities': reserved_for_severities,
                'leased_capacity': max(0, int(leased_capacity or 0)),
                'lease_expires_at': lease_expires_at,
                'lease_reason': str(queue_payload.get('lease_reason') or queue_payload.get('leased_reason') or '').strip(),
                'lease_holder': str(queue_payload.get('lease_holder') or queue_payload.get('lease_owner') or '').strip(),
                'lease_id': str(queue_payload.get('lease_id') or '').strip(),
                'leased_for_queue_types': leased_for_queue_types,
                'leased_for_severities': leased_for_severities,
                'temporary_holds': temporary_holds,
                'forecast_arrivals': queue_payload.get('forecast_arrivals'),
                'forecast_arrivals_per_hour': queue_payload.get('forecast_arrivals_per_hour'),
                'forecast_window_s': queue_payload.get('forecast_window_s'),
            })
        queue_capacity_payload = dict(payload.get('queue_capacity_policy') or payload.get('queue_load_policy') or {})
        default_queue_capacity_raw = queue_capacity_payload.get('default_capacity') if 'default_capacity' in queue_capacity_payload else payload.get('default_queue_capacity')
        try:
            default_queue_capacity = int(default_queue_capacity_raw) if default_queue_capacity_raw is not None else 0
        except Exception:
            default_queue_capacity = 0
        default_queue_warning_raw = queue_capacity_payload.get('warning_capacity') if 'warning_capacity' in queue_capacity_payload else payload.get('default_queue_warning_capacity')
        try:
            default_queue_warning = int(default_queue_warning_raw) if default_queue_warning_raw is not None else max(0, default_queue_capacity - 1)
        except Exception:
            default_queue_warning = max(0, default_queue_capacity - 1)
        try:
            default_reserved_capacity = int(queue_capacity_payload.get('default_reserved_capacity') or payload.get('default_reserved_capacity') or 0)
        except Exception:
            default_reserved_capacity = 0
        try:
            default_leased_capacity = int(queue_capacity_payload.get('default_leased_capacity') or payload.get('default_leased_capacity') or 0)
        except Exception:
            default_leased_capacity = 0
        try:
            default_lease_ttl_s = int(queue_capacity_payload.get('default_lease_ttl_s') or payload.get('default_lease_ttl_s') or 0)
        except Exception:
            default_lease_ttl_s = 0
        try:
            default_hold_ttl_s = int(queue_capacity_payload.get('default_hold_ttl_s') or payload.get('default_hold_ttl_s') or 0)
        except Exception:
            default_hold_ttl_s = 0
        reserved_for_queue_types = [
            str(item).strip()
            for item in list(queue_capacity_payload.get('reserved_for_queue_types') or payload.get('reserved_for_queue_types') or [])
            if str(item).strip()
        ]
        reserved_for_severities = [
            str(item).strip().lower()
            for item in list(queue_capacity_payload.get('reserved_for_severities') or payload.get('reserved_for_severities') or [])
            if str(item).strip()
        ]
        try:
            reroute_cooldown_s = int(queue_capacity_payload.get('reroute_cooldown_s') or payload.get('reroute_cooldown_s') or 0)
        except Exception:
            reroute_cooldown_s = 0
        try:
            anti_thrashing_min_active_delta = int(queue_capacity_payload.get('anti_thrashing_min_active_delta') or payload.get('anti_thrashing_min_active_delta') or 0)
        except Exception:
            anti_thrashing_min_active_delta = 0
        try:
            anti_thrashing_min_load_delta = float(queue_capacity_payload.get('anti_thrashing_min_load_delta') or payload.get('anti_thrashing_min_load_delta') or 0.0)
        except Exception:
            anti_thrashing_min_load_delta = 0.0
        try:
            aging_after_s = int(queue_capacity_payload.get('aging_after_s') or queue_capacity_payload.get('queue_aging_after_s') or payload.get('aging_after_s') or payload.get('queue_aging_after_s') or 0)
        except Exception:
            aging_after_s = 0
        try:
            starvation_after_s = int(queue_capacity_payload.get('starvation_after_s') or queue_capacity_payload.get('starvation_threshold_s') or queue_capacity_payload.get('queue_starvation_after_s') or payload.get('starvation_after_s') or payload.get('starvation_threshold_s') or payload.get('queue_starvation_after_s') or 0)
        except Exception:
            starvation_after_s = 0
        try:
            expected_service_time_s = int(queue_capacity_payload.get('expected_service_time_s') or queue_capacity_payload.get('service_time_s') or payload.get('expected_service_time_s') or payload.get('service_time_s') or 300)
        except Exception:
            expected_service_time_s = 300
        try:
            expedite_threshold_s = int(queue_capacity_payload.get('expedite_threshold_s') or payload.get('expedite_threshold_s') or 900)
        except Exception:
            expedite_threshold_s = 900
        try:
            expedite_min_risk_score = float(queue_capacity_payload.get('expedite_min_risk_score') or payload.get('expedite_min_risk_score') or 0.85)
        except Exception:
            expedite_min_risk_score = 0.85
        try:
            forecast_window_s = int(queue_capacity_payload.get('forecast_window_s') or payload.get('forecast_window_s') or 1800)
        except Exception:
            forecast_window_s = 1800
        try:
            proactive_min_projected_load_delta = float(queue_capacity_payload.get('proactive_min_projected_load_delta') or payload.get('proactive_min_projected_load_delta') or 0.15)
        except Exception:
            proactive_min_projected_load_delta = 0.15
        try:
            proactive_wait_buffer_s = int(queue_capacity_payload.get('proactive_wait_buffer_s') or payload.get('proactive_wait_buffer_s') or 180)
        except Exception:
            proactive_wait_buffer_s = 180
        try:
            surge_load_ratio_threshold = float(queue_capacity_payload.get('surge_load_ratio_threshold') or payload.get('surge_load_ratio_threshold') or 0.85)
        except Exception:
            surge_load_ratio_threshold = 0.85
        try:
            overload_projected_load_ratio_threshold = float(queue_capacity_payload.get('overload_projected_load_ratio_threshold') or payload.get('overload_projected_load_ratio_threshold') or surge_load_ratio_threshold or 0.95)
        except Exception:
            overload_projected_load_ratio_threshold = float(surge_load_ratio_threshold or 0.95)
        try:
            overload_projected_wait_time_threshold_s = int(queue_capacity_payload.get('overload_projected_wait_time_threshold_s') or payload.get('overload_projected_wait_time_threshold_s') or max(300, int(expected_service_time_s or 300) * 2))
        except Exception:
            overload_projected_wait_time_threshold_s = max(300, int(expected_service_time_s or 300) * 2)
        def _normalize_admission_action(raw_value: Any, default: str = 'defer') -> str:
            value = str(raw_value or default).strip().lower().replace('-', '_')
            return value if value in {'admit', 'defer', 'manual_gate', 'park', 'reject'} else default
        admission_default_action = _normalize_admission_action(queue_capacity_payload.get('admission_default_action') or payload.get('admission_default_action') or queue_capacity_payload.get('overload_default_action') or payload.get('overload_default_action') or 'defer')
        overload_global_action = _normalize_admission_action(queue_capacity_payload.get('overload_global_action') or payload.get('overload_global_action') or admission_default_action, admission_default_action)
        admission_exempt_severities = [
            str(item).strip().lower()
            for item in list(queue_capacity_payload.get('admission_exempt_severities') or payload.get('admission_exempt_severities') or [])
            if str(item).strip()
        ]
        admission_exempt_queue_types = [
            str(item).strip()
            for item in list(queue_capacity_payload.get('admission_exempt_queue_types') or payload.get('admission_exempt_queue_types') or [])
            if str(item).strip()
        ]
        default_queue_family = str(queue_capacity_payload.get('default_queue_family') or payload.get('default_queue_family') or '').strip()
        queue_families_enabled = bool(
            queue_capacity_payload.get(
                'queue_families_enabled',
                payload.get(
                    'queue_families_enabled',
                    bool(default_queue_family)
                    or any(str(dict(item or {}).get('queue_family_id') or dict(item or {}).get('family_id') or dict(item or {}).get('family') or '').strip() for item in queue_capacities),
                ),
            )
        )
        family_reroute_cooldown_default = queue_capacity_payload.get('family_reroute_cooldown_s') or payload.get('family_reroute_cooldown_s') or reroute_cooldown_s or 300
        try:
            family_reroute_cooldown_s = int(family_reroute_cooldown_default)
        except Exception:
            family_reroute_cooldown_s = int(reroute_cooldown_s or 300)
        try:
            family_min_active_delta = int(queue_capacity_payload.get('family_min_active_delta') or payload.get('family_min_active_delta') or anti_thrashing_min_active_delta or 1)
        except Exception:
            family_min_active_delta = int(anti_thrashing_min_active_delta or 1)
        try:
            family_min_load_delta = float(queue_capacity_payload.get('family_min_load_delta') or payload.get('family_min_load_delta') or proactive_min_projected_load_delta or anti_thrashing_min_load_delta or 0.1)
        except Exception:
            family_min_load_delta = float(proactive_min_projected_load_delta or anti_thrashing_min_load_delta or 0.1)
        try:
            family_min_projected_wait_delta_s = int(queue_capacity_payload.get('family_min_projected_wait_delta_s') or payload.get('family_min_projected_wait_delta_s') or proactive_wait_buffer_s or 120)
        except Exception:
            family_min_projected_wait_delta_s = int(proactive_wait_buffer_s or 120)
        try:
            family_recent_hops_threshold = int(queue_capacity_payload.get('family_recent_hops_threshold') or payload.get('family_recent_hops_threshold') or 2)
        except Exception:
            family_recent_hops_threshold = 2
        try:
            family_history_limit = int(queue_capacity_payload.get('family_history_limit') or payload.get('family_history_limit') or 8)
        except Exception:
            family_history_limit = 8
        multi_hop_hysteresis_enabled = bool(queue_capacity_payload.get('multi_hop_hysteresis_enabled', payload.get('multi_hop_hysteresis_enabled', queue_families_enabled)))
        starvation_prevention_enabled = bool(queue_capacity_payload.get('starvation_prevention_enabled', payload.get('starvation_prevention_enabled', starvation_after_s > 0)))
        queue_capacity_policy = {
            'enabled': bool(queue_capacity_payload.get('enabled', payload.get('queue_capacity_enabled', bool(queue_capacities) or default_queue_capacity > 0))),
            'default_capacity': max(0, int(default_queue_capacity or 0)),
            'warning_capacity': max(0, int(default_queue_warning or 0)),
            'hard_limit': bool(queue_capacity_payload.get('hard_limit', payload.get('queue_capacity_hard_limit', False))),
            'prefer_lowest_load': bool(queue_capacity_payload.get('prefer_lowest_load', payload.get('prefer_lowest_load', True))),
            'rebalance_on_over_capacity': bool(queue_capacity_payload.get('rebalance_on_over_capacity', payload.get('rebalance_on_over_capacity', True))),
            'load_metric': str(queue_capacity_payload.get('load_metric') or payload.get('queue_load_metric') or 'active_alerts').strip() or 'active_alerts',
            'reservation_enabled': bool(queue_capacity_payload.get('reservation_enabled', payload.get('reservation_enabled', default_reserved_capacity > 0))),
            'default_reserved_capacity': max(0, int(default_reserved_capacity or 0)),
            'reserved_for_queue_types': reserved_for_queue_types,
            'reserved_for_severities': reserved_for_severities,
            'reservation_lease_enabled': bool(queue_capacity_payload.get('reservation_lease_enabled', payload.get('reservation_lease_enabled', default_leased_capacity > 0 or any(int(dict(item or {}).get('leased_capacity') or 0) > 0 for item in queue_capacities)))),
            'default_leased_capacity': max(0, int(default_leased_capacity or 0)),
            'default_lease_ttl_s': max(0, int(default_lease_ttl_s or 0)),
            'lease_reclaim_enabled': bool(queue_capacity_payload.get('lease_reclaim_enabled', payload.get('lease_reclaim_enabled', True))),
            'temporary_holds_enabled': bool(queue_capacity_payload.get('temporary_holds_enabled', payload.get('temporary_holds_enabled', any(list(dict(item or {}).get('temporary_holds') or [] ) for item in queue_capacities)))),
            'default_hold_ttl_s': max(0, int(default_hold_ttl_s or 0)),
            'starvation_lease_capacity_borrow_enabled': bool(queue_capacity_payload.get('starvation_lease_capacity_borrow_enabled', payload.get('starvation_lease_capacity_borrow_enabled', starvation_prevention_enabled))),
            'starvation_hold_capacity_borrow_enabled': bool(queue_capacity_payload.get('starvation_hold_capacity_borrow_enabled', payload.get('starvation_hold_capacity_borrow_enabled', starvation_prevention_enabled))),
            'expedite_lease_capacity_borrow_enabled': bool(queue_capacity_payload.get('expedite_lease_capacity_borrow_enabled', payload.get('expedite_lease_capacity_borrow_enabled', True))),
            'expedite_hold_capacity_borrow_enabled': bool(queue_capacity_payload.get('expedite_hold_capacity_borrow_enabled', payload.get('expedite_hold_capacity_borrow_enabled', True))),
            'anti_thrashing_enabled': bool(queue_capacity_payload.get('anti_thrashing_enabled', payload.get('anti_thrashing_enabled', False))),
            'reroute_cooldown_s': max(0, int(reroute_cooldown_s or 0)),
            'anti_thrashing_min_active_delta': max(0, int(anti_thrashing_min_active_delta or 0)),
            'anti_thrashing_min_load_delta': max(0.0, float(anti_thrashing_min_load_delta or 0.0)),
            'aging_enabled': bool(queue_capacity_payload.get('aging_enabled', payload.get('aging_enabled', aging_after_s > 0))),
            'aging_after_s': max(0, int(aging_after_s or 0)),
            'starvation_prevention_enabled': starvation_prevention_enabled,
            'starvation_after_s': max(0, int(starvation_after_s or 0)),
            'starvation_reserved_capacity_borrow_enabled': bool(queue_capacity_payload.get('starvation_reserved_capacity_borrow_enabled', payload.get('starvation_reserved_capacity_borrow_enabled', starvation_prevention_enabled))),
            'starvation_bypass_anti_thrashing': bool(queue_capacity_payload.get('starvation_bypass_anti_thrashing', payload.get('starvation_bypass_anti_thrashing', starvation_prevention_enabled))),
            'breach_prediction_enabled': bool(queue_capacity_payload.get('breach_prediction_enabled', payload.get('breach_prediction_enabled', bool(payload.get('sla_policy') or payload.get('sla'))))),
            'expected_service_time_s': max(60, int(expected_service_time_s or 300)),
            'expedite_enabled': bool(queue_capacity_payload.get('expedite_enabled', payload.get('expedite_enabled', bool(payload.get('sla_policy') or payload.get('sla'))))),
            'expedite_threshold_s': max(0, int(expedite_threshold_s or 0)),
            'expedite_min_risk_score': max(0.0, float(expedite_min_risk_score or 0.0)),
            'expedite_reserved_capacity_borrow_enabled': bool(queue_capacity_payload.get('expedite_reserved_capacity_borrow_enabled', payload.get('expedite_reserved_capacity_borrow_enabled', True))),
            'expedite_bypass_anti_thrashing': bool(queue_capacity_payload.get('expedite_bypass_anti_thrashing', payload.get('expedite_bypass_anti_thrashing', True))),
            'predictive_forecasting_enabled': bool(queue_capacity_payload.get('predictive_forecasting_enabled', queue_capacity_payload.get('forecasting_enabled', payload.get('predictive_forecasting_enabled', payload.get('forecasting_enabled', False))))),
            'forecast_window_s': max(300, int(forecast_window_s or 1800)),
            'surge_load_ratio_threshold': min(2.0, max(0.25, float(surge_load_ratio_threshold or 0.85))),
            'proactive_routing_enabled': bool(queue_capacity_payload.get('proactive_routing_enabled', payload.get('proactive_routing_enabled', bool(queue_capacity_payload.get('predictive_forecasting_enabled', queue_capacity_payload.get('forecasting_enabled', payload.get('predictive_forecasting_enabled', payload.get('forecasting_enabled', False)))))))),
            'proactive_min_projected_load_delta': max(0.0, float(proactive_min_projected_load_delta or 0.0)),
            'proactive_wait_buffer_s': max(0, int(proactive_wait_buffer_s or 0)),
            'proactive_bypass_anti_thrashing': bool(queue_capacity_payload.get('proactive_bypass_anti_thrashing', payload.get('proactive_bypass_anti_thrashing', False))),
            'admission_control_enabled': bool(queue_capacity_payload.get('admission_control_enabled', payload.get('admission_control_enabled', bool(queue_capacity_payload.get('overload_governance_enabled', payload.get('overload_governance_enabled', False)))))),
            'admission_default_action': admission_default_action,
            'admission_exempt_severities': admission_exempt_severities,
            'admission_exempt_queue_types': admission_exempt_queue_types,
            'queue_families_enabled': queue_families_enabled,
            'default_queue_family': default_queue_family,
            'multi_hop_hysteresis_enabled': multi_hop_hysteresis_enabled,
            'family_reroute_cooldown_s': max(0, int(family_reroute_cooldown_s or 0)),
            'family_min_active_delta': max(0, int(family_min_active_delta or 0)),
            'family_min_load_delta': max(0.0, float(family_min_load_delta or 0.0)),
            'family_min_projected_wait_delta_s': max(0, int(family_min_projected_wait_delta_s or 0)),
            'family_recent_hops_threshold': max(1, int(family_recent_hops_threshold or 1)),
            'family_history_limit': max(2, int(family_history_limit or 2)),
            'expedite_bypass_family_hysteresis': bool(queue_capacity_payload.get('expedite_bypass_family_hysteresis', payload.get('expedite_bypass_family_hysteresis', True))),
            'proactive_bypass_family_hysteresis': bool(queue_capacity_payload.get('proactive_bypass_family_hysteresis', payload.get('proactive_bypass_family_hysteresis', True))),
            'starvation_bypass_family_hysteresis': bool(queue_capacity_payload.get('starvation_bypass_family_hysteresis', payload.get('starvation_bypass_family_hysteresis', True))),
            'admission_bypass_family_hysteresis': bool(queue_capacity_payload.get('admission_bypass_family_hysteresis', payload.get('admission_bypass_family_hysteresis', True))),
            'admit_expedite_on_overload': bool(queue_capacity_payload.get('admit_expedite_on_overload', payload.get('admit_expedite_on_overload', True))),
            'admit_starving_on_overload': bool(queue_capacity_payload.get('admit_starving_on_overload', payload.get('admit_starving_on_overload', True))),
            'overload_governance_enabled': bool(queue_capacity_payload.get('overload_governance_enabled', payload.get('overload_governance_enabled', bool(queue_capacity_payload.get('predictive_forecasting_enabled', queue_capacity_payload.get('forecasting_enabled', payload.get('predictive_forecasting_enabled', payload.get('forecasting_enabled', False)))))))),
            'overload_projected_load_ratio_threshold': min(3.0, max(0.25, float(overload_projected_load_ratio_threshold or surge_load_ratio_threshold or 0.95))),
            'overload_projected_wait_time_threshold_s': max(0, int(overload_projected_wait_time_threshold_s or 0)),
            'overload_global_action': overload_global_action,
        }
        load_aware_routing_enabled = bool(payload.get('load_aware_routing_enabled', queue_capacity_policy.get('enabled')))
        return {
            'enabled': bool(payload.get('enabled', False)),
            'auto_schedule': bool(payload.get('auto_schedule', True)),
            'interval_s': max(60, int(interval_s or 3600)),
            'notify_on_drift': bool(payload.get('notify_on_drift', True)),
            'notify_on_recovery': bool(payload.get('notify_on_recovery', True)),
            'notify_on_escalation': bool(payload.get('notify_on_escalation', True)),
            'block_on_drift': bool(payload.get('block_on_drift', False)),
            'target_path': fallback_target_path,
            'severity': str(payload.get('severity') or 'warning').strip() or 'warning',
            'max_alerts': max(1, int(max_alerts or 20)),
            'dedupe_window_s': max(0, int(dedupe_window_s or 0)),
            'default_mute_s': max(0, int(default_mute_s or 0)),
            'escalation_enabled': escalation_enabled,
            'escalation_levels': levels,
            'max_escalations': max(1, int(max_escalations or max(len(levels), 1))),
            'suppression_window_s': max(0, int(suppression_window_s or 0)),
            'suppress_while_acknowledged': bool(payload.get('suppress_while_acknowledged', True)),
            'suppress_while_muted': bool(payload.get('suppress_while_muted', True)),
            'escalation_target_path': str(payload.get('escalation_target_path') or payload.get('target_path') or fallback_target_path).strip() or fallback_target_path,
            'routing_enabled': routing_enabled,
            'ownership_enabled': ownership_enabled,
            'handoff_enabled': handoff_enabled,
            'handoff_require_reason': handoff_require_reason,
            'auto_assign_owner': bool(payload.get('auto_assign_owner', False)),
            'default_route': default_route,
            'routing_routes': routes,
            'sla_policy': sla_policy,
            'auto_reroute_on_sla_breach': auto_reroute_on_sla_breach,
            'notify_on_sla_reroute': bool(payload.get('notify_on_sla_reroute', True)),
            'team_escalation_queues': team_escalation_queues,
            'sla_breach_route': sla_breach_route,
            'queue_capacities': queue_capacities,
            'queue_capacity_policy': queue_capacity_policy,
            'load_aware_routing_enabled': load_aware_routing_enabled,
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

    def _refresh_baseline_promotion_rollout_plan(self, rollout_plan: dict[str, Any] | None) -> dict[str, Any]:
        plan = dict(rollout_plan or {})
        items = [dict(item) for item in list(plan.get('items') or [])]
        status_counts: dict[str, int] = {}
        applied_portfolio_ids: list[str] = []
        rolled_back_portfolio_ids: list[str] = []
        pending_portfolio_ids: list[str] = []
        completed_wave_count = 0
        current_wave_no = 0
        gate_failed_wave_no = None
        group_ids: list[str] = []
        dependency_edge_count = 0
        dependency_blocked_wave_count = 0
        for wave in items:
            status = str(wave.get('status') or 'planned').strip() or 'planned'
            status_counts[status] = status_counts.get(status, 0) + 1
            portfolio_ids = self._baseline_promotion_unique_ids(list(wave.get('portfolio_ids') or []))
            group_ids.extend([str(item).strip() for item in list(wave.get('group_ids') or []) if str(item).strip()])
            dep_summary = dict(wave.get('dependency_summary') or {})
            dependency_edge_count += len(list(dep_summary.get('depends_on_group_ids') or [])) + len(list(dep_summary.get('depends_on_wave_nos') or []))
            if str(status) in {'dependency_blocked'}:
                dependency_blocked_wave_count += 1
            if status in {'applied', 'completed', 'gate_failed', 'rolled_back'}:
                applied_portfolio_ids.extend(portfolio_ids)
                current_wave_no = max(current_wave_no, int(wave.get('wave_no') or 0))
            if status == 'completed':
                completed_wave_count += 1
            if status == 'rolled_back':
                rolled_back_portfolio_ids.extend(portfolio_ids)
            if status == 'planned':
                pending_portfolio_ids.extend(portfolio_ids)
            if status == 'gate_failed' and gate_failed_wave_no is None:
                gate_failed_wave_no = int(wave.get('wave_no') or 0)
        applied_portfolio_ids = self._baseline_promotion_unique_ids(applied_portfolio_ids)
        rolled_back_portfolio_ids = self._baseline_promotion_unique_ids(rolled_back_portfolio_ids)
        pending_portfolio_ids = self._baseline_promotion_unique_ids(pending_portfolio_ids)
        group_summary = dict(plan.get('group_summary') or {})
        validation = dict(plan.get('validation') or {})
        plan['items'] = items
        plan['wave_count'] = len(items)
        plan['current_wave_no'] = current_wave_no
        plan['completed_wave_count'] = completed_wave_count
        plan['applied_portfolio_ids'] = applied_portfolio_ids
        plan['rolled_back_portfolio_ids'] = rolled_back_portfolio_ids
        plan['pending_portfolio_ids'] = pending_portfolio_ids
        plan['group_summary'] = {
            **group_summary,
            'group_count': int(group_summary.get('group_count') or len(self._baseline_promotion_unique_ids(group_ids))),
            'group_ids': self._baseline_promotion_unique_ids(list(group_summary.get('group_ids') or group_ids)),
            'dependency_edge_count': int(group_summary.get('dependency_edge_count') or dependency_edge_count),
            'dependency_cycle_detected': bool(group_summary.get('dependency_cycle_detected', False)),
            'cyclic_group_ids': self._baseline_promotion_unique_ids(list(group_summary.get('cyclic_group_ids') or [])),
            'exclusive_conflict_count': int(group_summary.get('exclusive_conflict_count') or 0),
        }
        validation_errors = [dict(item) for item in list(validation.get('errors') or [])]
        validation_status = str(validation.get('status') or ('failed' if validation_errors else 'passed')).strip() or ('failed' if validation_errors else 'passed')
        plan['validation'] = {
            **validation,
            'status': validation_status,
            'valid': validation_status == 'passed',
            'errors': validation_errors,
        }
        plan['summary'] = {
            'wave_count': len(items),
            'completed_wave_count': completed_wave_count,
            'current_wave_no': current_wave_no,
            'applied_count': len(applied_portfolio_ids),
            'rolled_back_count': len(rolled_back_portfolio_ids),
            'pending_count': len(pending_portfolio_ids),
            'status_counts': status_counts,
            'gate_failed': gate_failed_wave_no is not None,
            'gate_failed_wave_no': gate_failed_wave_no,
            'group_count': int((plan.get('group_summary') or {}).get('group_count') or 0),
            'dependency_edge_count': int((plan.get('group_summary') or {}).get('dependency_edge_count') or 0),
            'dependency_blocked_wave_count': dependency_blocked_wave_count,
            'dependency_cycle_detected': bool((plan.get('group_summary') or {}).get('dependency_cycle_detected', False)),
            'exclusive_conflict_count': int((plan.get('group_summary') or {}).get('exclusive_conflict_count') or 0),
            'validation_status': validation_status,
            'validation_failed': validation_status != 'passed',
            'validation_error_count': len(validation_errors),
        }
        return plan

    def _build_baseline_promotion_rollout_plan(self, *, promotion_id: str, impact: dict[str, Any], rollout_policy: dict[str, Any]) -> dict[str, Any]:
        impact_items = [dict(item) for item in list((impact or {}).get('items') or [])]
        impact_items.sort(key=lambda item: (str(item.get('environment') or ''), str(item.get('name') or ''), str(item.get('portfolio_id') or '')))
        items_by_portfolio = {str(item.get('portfolio_id') or ''): item for item in impact_items if str(item.get('portfolio_id') or '').strip()}
        ordered_ids = self._baseline_promotion_unique_ids([str(item.get('portfolio_id') or '') for item in impact_items])
        waves: list[dict[str, Any]] = []
        used: set[str] = set()
        explicit_waves = [dict(item) for item in list((rollout_policy or {}).get('waves') or [])]
        if explicit_waves:
            for wave in explicit_waves:
                portfolio_ids = [portfolio_id for portfolio_id in self._baseline_promotion_unique_ids(list(wave.get('portfolio_ids') or [])) if portfolio_id in items_by_portfolio and portfolio_id not in used]
                if not portfolio_ids:
                    continue
                used.update(portfolio_ids)
                wave_no = len(waves) + 1
                waves.append({
                    'wave_id': f'wave-{wave_no}-{uuid.uuid4().hex[:8]}',
                    'wave_no': wave_no,
                    'wave_label': str(wave.get('wave_label') or f'wave-{wave_no}').strip() or f'wave-{wave_no}',
                    'portfolio_ids': portfolio_ids,
                    'group_ids': [],
                    'group_labels': [],
                    'items': [dict(items_by_portfolio[portfolio_id]) for portfolio_id in portfolio_ids],
                    'status': 'planned',
                    'gate_evaluation': {},
                    'dependency_summary': {'depends_on_group_ids': [], 'depends_on_wave_nos': [], 'dependency_portfolio_ids': [], 'cycle_detected': False},
                })
            remaining_ids = [portfolio_id for portfolio_id in ordered_ids if portfolio_id not in used]
            wave_size = int((rollout_policy or {}).get('wave_size') or 0)
            if wave_size <= 0:
                wave_size = len(remaining_ids) or len(ordered_ids) or 1
            for index in range(0, len(remaining_ids), wave_size):
                portfolio_ids = remaining_ids[index:index + wave_size]
                if not portfolio_ids:
                    continue
                wave_no = len(waves) + 1
                waves.append({
                    'wave_id': f'wave-{wave_no}-{uuid.uuid4().hex[:8]}',
                    'wave_no': wave_no,
                    'wave_label': f'wave-{wave_no}',
                    'portfolio_ids': portfolio_ids,
                    'group_ids': [],
                    'group_labels': [],
                    'items': [dict(items_by_portfolio[portfolio_id]) for portfolio_id in portfolio_ids if portfolio_id in items_by_portfolio],
                    'status': 'planned',
                    'gate_evaluation': {},
                    'dependency_summary': {'depends_on_group_ids': [], 'depends_on_wave_nos': [], 'dependency_portfolio_ids': [], 'cycle_detected': False},
                })
            plan = {
                'promotion_id': str(promotion_id or '').strip(),
                'enabled': bool((rollout_policy or {}).get('enabled', False)) and bool(waves),
                'items': waves,
                'group_summary': {'group_count': 0, 'group_ids': [], 'dependency_edge_count': 0, 'dependency_cycle_detected': False, 'cyclic_group_ids': []},
            }
            return self._refresh_baseline_promotion_rollout_plan(plan)

        dependency_graph = self._normalize_portfolio_dependency_graph((rollout_policy or {}).get('dependency_graph') or {})
        explicit_groups = self._normalize_baseline_rollout_group_specs((rollout_policy or {}).get('portfolio_groups') or [])
        if explicit_groups or dependency_graph:
            group_specs = [dict(item) for item in explicit_groups]
            portfolio_to_group: dict[str, str] = {}
            for spec in group_specs:
                valid_ids = [pid for pid in self._baseline_promotion_unique_ids(list(spec.get('portfolio_ids') or [])) if pid in items_by_portfolio and pid not in portfolio_to_group]
                spec['portfolio_ids'] = valid_ids
                for pid in valid_ids:
                    portfolio_to_group[pid] = str(spec.get('group_id') or '')
            synthetic_idx = 0
            for portfolio_id in ordered_ids:
                if portfolio_id in portfolio_to_group or portfolio_id not in items_by_portfolio:
                    continue
                synthetic_idx += 1
                group_id = f'portfolio-{synthetic_idx}' if dependency_graph else 'ungrouped'
                if not dependency_graph:
                    existing = next((item for item in group_specs if str(item.get('group_id') or '') == group_id), None)
                    if existing is not None:
                        existing['portfolio_ids'] = self._baseline_promotion_unique_ids(list(existing.get('portfolio_ids') or []) + [portfolio_id])
                        portfolio_to_group[portfolio_id] = group_id
                        continue
                spec = {'group_id': group_id, 'group_label': group_id, 'portfolio_ids': [portfolio_id], 'depends_on_groups': [], 'exclusive_with_groups': [], 'wave_size': 0, 'metadata': {'synthetic': True}}
                group_specs.append(spec)
                portfolio_to_group[portfolio_id] = group_id
            if dependency_graph:
                for portfolio_id, dep_ids in dependency_graph.items():
                    group_id = portfolio_to_group.get(portfolio_id)
                    if not group_id:
                        continue
                    spec = next((item for item in group_specs if str(item.get('group_id') or '') == group_id), None)
                    if spec is None:
                        continue
                    existing_dep_groups = list(spec.get('depends_on_groups') or [])
                    for dep_id in dep_ids:
                        dep_group_id = portfolio_to_group.get(dep_id)
                        if dep_group_id and dep_group_id != group_id:
                            existing_dep_groups.append(dep_group_id)
                    spec['depends_on_groups'] = self._baseline_promotion_unique_ids(existing_dep_groups)
            group_specs = [spec for spec in group_specs if list(spec.get('portfolio_ids') or [])]
            ordered_groups_state = self._topological_sort_baseline_group_specs(group_specs)
            ordered_groups = [dict(item) for item in list(ordered_groups_state.get('items') or [])]
            group_ids_set = {str(item.get('group_id') or '') for item in ordered_groups}
            validation_errors: list[dict[str, Any]] = []
            if bool(ordered_groups_state.get('cycle_detected')):
                validation_errors.append({
                    'code': 'dependency_cycle_detected',
                    'reason': 'baseline rollout group dependency graph contains a cycle',
                    'cyclic_group_ids': [str(item) for item in list(ordered_groups_state.get('cyclic_group_ids') or [])],
                })
            exclusive_conflict_count = 0
            for spec in ordered_groups:
                group_id = str(spec.get('group_id') or '')
                missing_dependencies = [dep for dep in list(spec.get('depends_on_groups') or []) if dep not in group_ids_set]
                if missing_dependencies:
                    validation_errors.append({
                        'code': 'unknown_dependency_group',
                        'reason': 'baseline rollout group depends on an unknown group',
                        'group_id': group_id,
                        'unknown_group_ids': self._baseline_promotion_unique_ids(missing_dependencies),
                    })
                exclusive_groups = [dep for dep in list(spec.get('exclusive_with_groups') or []) if dep]
                missing_exclusive = [dep for dep in exclusive_groups if dep not in group_ids_set]
                if missing_exclusive:
                    validation_errors.append({
                        'code': 'unknown_exclusive_group',
                        'reason': 'baseline rollout group excludes an unknown group',
                        'group_id': group_id,
                        'unknown_group_ids': self._baseline_promotion_unique_ids(missing_exclusive),
                    })
                    exclusive_conflict_count += len(missing_exclusive)
                if group_id in exclusive_groups:
                    validation_errors.append({
                        'code': 'self_exclusive_group',
                        'reason': 'baseline rollout group cannot exclude itself',
                        'group_id': group_id,
                    })
                    exclusive_conflict_count += 1
            group_last_wave_no: dict[str, int] = {}
            group_wave_numbers: dict[str, list[int]] = {}
            group_first_portfolios: dict[str, list[str]] = {str(item.get('group_id') or ''): self._baseline_promotion_unique_ids(list(item.get('portfolio_ids') or [])) for item in ordered_groups}
            for spec in ordered_groups:
                group_id = str(spec.get('group_id') or '')
                group_label = str(spec.get('group_label') or group_id)
                portfolio_ids = [pid for pid in self._baseline_promotion_unique_ids(list(spec.get('portfolio_ids') or [])) if pid in items_by_portfolio]
                if not portfolio_ids:
                    continue
                chunk_size = int(spec.get('wave_size') or (rollout_policy or {}).get('wave_size') or 0)
                if chunk_size <= 0:
                    chunk_size = len(portfolio_ids)
                previous_chunk_wave_no = None
                for chunk_index in range(0, len(portfolio_ids), chunk_size):
                    chunk_ids = portfolio_ids[chunk_index:chunk_index + chunk_size]
                    wave_no = len(waves) + 1
                    depends_on_wave_nos = [group_last_wave_no[dep_gid] for dep_gid in list(spec.get('depends_on_groups') or []) if dep_gid in group_last_wave_no]
                    exclusive_depends_on_wave_nos = [group_last_wave_no[dep_gid] for dep_gid in list(spec.get('exclusive_with_groups') or []) if dep_gid in group_last_wave_no]
                    if previous_chunk_wave_no is not None:
                        depends_on_wave_nos.append(previous_chunk_wave_no)
                    depends_on_wave_nos.extend(exclusive_depends_on_wave_nos)
                    dependency_portfolio_ids: list[str] = []
                    for dep_gid in list(spec.get('depends_on_groups') or []):
                        dependency_portfolio_ids.extend(list(group_first_portfolios.get(dep_gid) or []))
                    wave = {
                        'wave_id': f'wave-{wave_no}-{uuid.uuid4().hex[:8]}',
                        'wave_no': wave_no,
                        'wave_label': str(spec.get('metadata', {}).get('wave_label') or group_label or f'wave-{wave_no}'),
                        'portfolio_ids': chunk_ids,
                        'group_ids': [group_id],
                        'group_labels': [group_label],
                        'items': [dict(items_by_portfolio[portfolio_id]) for portfolio_id in chunk_ids if portfolio_id in items_by_portfolio],
                        'status': 'planned',
                        'gate_evaluation': {},
                        'dependency_summary': {
                            'depends_on_group_ids': list(spec.get('depends_on_groups') or []),
                            'depends_on_wave_nos': sorted(set(int(item) for item in depends_on_wave_nos if item is not None)),
                            'dependency_portfolio_ids': self._baseline_promotion_unique_ids(dependency_portfolio_ids),
                            'cycle_detected': bool(ordered_groups_state.get('cycle_detected')),
                            'exclusive_with_groups': list(spec.get('exclusive_with_groups') or []),
                            'exclusive_depends_on_wave_nos': sorted(set(int(item) for item in exclusive_depends_on_wave_nos if item is not None)),
                        },
                    }
                    waves.append(wave)
                    group_wave_numbers.setdefault(group_id, []).append(wave_no)
                    group_last_wave_no[group_id] = wave_no
                    previous_chunk_wave_no = wave_no
            plan = {
                'promotion_id': str(promotion_id or '').strip(),
                'enabled': bool((rollout_policy or {}).get('enabled', False)) and bool(waves),
                'items': waves,
                'group_summary': {
                    'group_count': len(ordered_groups),
                    'group_ids': [str(item.get('group_id') or '') for item in ordered_groups],
                    'dependency_edge_count': sum(len(list(item.get('depends_on_groups') or [])) for item in ordered_groups),
                    'dependency_cycle_detected': bool(ordered_groups_state.get('cycle_detected')),
                    'cyclic_group_ids': [str(item) for item in list(ordered_groups_state.get('cyclic_group_ids') or [])],
                    'group_wave_numbers': {gid: list(nums) for gid, nums in group_wave_numbers.items()},
                    'exclusive_conflict_count': exclusive_conflict_count,
                },
                'validation': {
                    'status': 'failed' if validation_errors else 'passed',
                    'errors': validation_errors,
                },
            }
            return self._refresh_baseline_promotion_rollout_plan(plan)

        remaining_ids = [portfolio_id for portfolio_id in ordered_ids if portfolio_id in items_by_portfolio]
        wave_size = int((rollout_policy or {}).get('wave_size') or 0)
        if wave_size <= 0:
            wave_size = len(remaining_ids) or len(ordered_ids) or 1
        for index in range(0, len(remaining_ids), wave_size):
            portfolio_ids = remaining_ids[index:index + wave_size]
            if not portfolio_ids:
                continue
            wave_no = len(waves) + 1
            waves.append({
                'wave_id': f'wave-{wave_no}-{uuid.uuid4().hex[:8]}',
                'wave_no': wave_no,
                'wave_label': f'wave-{wave_no}',
                'portfolio_ids': portfolio_ids,
                'group_ids': [],
                'group_labels': [],
                'items': [dict(items_by_portfolio[portfolio_id]) for portfolio_id in portfolio_ids if portfolio_id in items_by_portfolio],
                'status': 'planned',
                'gate_evaluation': {},
                'dependency_summary': {'depends_on_group_ids': [], 'depends_on_wave_nos': [], 'dependency_portfolio_ids': [], 'cycle_detected': False},
            })
        plan = {
            'promotion_id': str(promotion_id or '').strip(),
            'enabled': bool((rollout_policy or {}).get('enabled', False)) and bool(waves),
            'items': waves,
            'group_summary': {'group_count': 0, 'group_ids': [], 'dependency_edge_count': 0, 'dependency_cycle_detected': False, 'cyclic_group_ids': []},
        }
        return self._refresh_baseline_promotion_rollout_plan(plan)

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

    def _baseline_rollout_wave_calendar_decision(
        self,
        gw,
        *,
        promotion_release: dict[str, Any],
        rollout_policy: dict[str, Any] | None,
        requested_at: float,
        wave: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        policy = self._normalize_baseline_catalog_rollout_policy(dict(rollout_policy or {}))
        candidate = float(requested_at)
        last_decisions: list[dict[str, Any]] = []
        combined_blockers: list[str] = []
        combined_windows: list[dict[str, Any]] = []
        unique_portfolio_ids = self._baseline_promotion_unique_ids(list((wave or {}).get('portfolio_ids') or []))
        portfolios: list[dict[str, Any] | None] = []
        for portfolio_id in unique_portfolio_ids:
            portfolio_release = gw.audit.get_release_bundle(str(portfolio_id or ''), tenant_id=promotion_release.get('tenant_id'), workspace_id=promotion_release.get('workspace_id'), environment=None)
            portfolios.append(portfolio_release if self._is_alert_governance_portfolio_release(portfolio_release) else None)
        if not portfolios:
            portfolios = [None]
        maintenance_state_by_portfolio: dict[str | None, bool] = {}
        for _ in range(0, 20):
            decisions: list[dict[str, Any]] = []
            next_candidates: list[float] = [candidate]
            fatal_reason: str | None = None
            fatal = False
            all_allowed = True
            for portfolio_release in portfolios:
                portfolio_environment = (portfolio_release or {}).get('environment') or promotion_release.get('environment')
                portfolio_id = str((portfolio_release or {}).get('release_id') or '') or None
                decision = self._baseline_rollout_next_allowed_time(
                    rollout_policy=policy,
                    requested_at=float(candidate),
                    tenant_id=promotion_release.get('tenant_id'),
                    workspace_id=promotion_release.get('workspace_id'),
                    environment=portfolio_environment,
                    portfolio_release=portfolio_release,
                    maintenance_already_satisfied=bool(maintenance_state_by_portfolio.get(portfolio_id)),
                )
                maintenance_state_by_portfolio[portfolio_id] = bool(decision.get('maintenance_satisfied', False))
                decision['portfolio_id'] = portfolio_id
                decision['portfolio_name'] = str((portfolio_release or {}).get('name') or '') or None
                decision['environment'] = self._normalize_portfolio_environment_name(portfolio_environment)
                decisions.append(decision)
                combined_blockers.extend(list(decision.get('blockers') or []))
                combined_windows.extend([dict(item) for item in list(decision.get('blocker_windows') or [])])
                next_allowed_at = decision.get('next_allowed_at')
                if next_allowed_at is None:
                    if not bool(decision.get('allowed', False)):
                        fatal = True
                        fatal_reason = str(decision.get('reason') or 'window_blocked')
                    continue
                next_candidates.append(float(next_allowed_at))
                if float(next_allowed_at) > candidate + 1e-6 or not bool(decision.get('allowed', False)):
                    all_allowed = False
            last_decisions = decisions
            if fatal:
                return {
                    'allowed': False,
                    'reason': fatal_reason or 'window_blocked',
                    'requested_at': float(requested_at),
                    'next_allowed_at': None,
                    'blockers': self._baseline_promotion_unique_ids(combined_blockers),
                    'blocker_windows': combined_windows[-50:],
                    'portfolio_decisions': last_decisions,
                }
            next_candidate = max(next_candidates) if next_candidates else candidate
            if all_allowed and next_candidate <= candidate + 1e-6:
                return {
                    'allowed': True,
                    'requested_at': float(requested_at),
                    'next_allowed_at': float(candidate),
                    'blockers': self._baseline_promotion_unique_ids(combined_blockers),
                    'blocker_windows': combined_windows[-50:],
                    'portfolio_decisions': last_decisions,
                }
            if next_candidate <= candidate + 1e-6:
                return {
                    'allowed': False,
                    'reason': 'window_resolution_exceeded',
                    'requested_at': float(requested_at),
                    'next_allowed_at': None,
                    'blockers': self._baseline_promotion_unique_ids(combined_blockers),
                    'blocker_windows': combined_windows[-50:],
                    'portfolio_decisions': last_decisions,
                }
            candidate = float(next_candidate)
        return {
            'allowed': False,
            'reason': 'window_resolution_exceeded',
            'requested_at': float(requested_at),
            'next_allowed_at': None,
            'blockers': self._baseline_promotion_unique_ids(combined_blockers),
            'blocker_windows': combined_windows[-50:],
            'portfolio_decisions': last_decisions,
        }

    def _set_portfolio_baseline_catalog_rollout_state(
        self,
        gw,
        *,
        portfolio_release: dict[str, Any],
        promotion_release: dict[str, Any],
        actor: str,
        status: str,
        active: bool,
        wave_no: int | None = None,
        wave_id: str | None = None,
        reason: str = '',
    ) -> dict[str, Any]:
        promotion = dict(((promotion_release.get('metadata') or {}).get('baseline_promotion') or {}) or {})
        env_key = self._normalize_portfolio_environment_name(portfolio_release.get('environment'))
        candidate_baselines = self._normalize_baseline_catalog_environment_entries(dict(promotion.get('candidate_baselines') or {}))
        candidate_entry = dict(candidate_baselines.get(env_key) or {})
        metadata = dict(portfolio_release.get('metadata') or {})
        portfolio = dict(metadata.get('portfolio') or {})
        history = [dict(item) for item in list(portfolio.get('baseline_catalog_rollout_history') or [])]
        record = {
            'promotion_id': str(promotion_release.get('release_id') or ''),
            'catalog_id': str(promotion.get('catalog_id') or ''),
            'catalog_version': str(promotion.get('candidate_catalog_version') or promotion_release.get('version') or ''),
            'recorded_at': time.time(),
            'recorded_by': str(actor or 'admin'),
            'status': str(status or '').strip() or 'unknown',
            'active': bool(active),
            'wave_no': int(wave_no or 0) if wave_no is not None else None,
            'wave_id': str(wave_id or '').strip() or None,
            'reason': str(reason or '').strip(),
            'candidate_baselines': {env_key: candidate_entry} if candidate_entry else {},
        }
        history.append(dict(record))
        portfolio['baseline_catalog_rollout_history'] = history[-50:]
        portfolio['current_baseline_catalog_rollout'] = record
        metadata['portfolio'] = portfolio
        return gw.audit.update_release_bundle(
            str(portfolio_release.get('release_id') or ''),
            metadata=metadata,
            tenant_id=portfolio_release.get('tenant_id'),
            workspace_id=portfolio_release.get('workspace_id'),
            environment=portfolio_release.get('environment'),
        ) or portfolio_release


    def _simulate_portfolio_baseline_catalog_rollout_state(
        self,
        *,
        portfolio_release: dict[str, Any],
        promotion_release: dict[str, Any],
        actor: str,
        status: str,
        active: bool,
        wave_no: int | None = None,
        wave_id: str | None = None,
        reason: str = '',
    ) -> dict[str, Any]:
        promotion = dict(((promotion_release.get('metadata') or {}).get('baseline_promotion') or {}) or {})
        env_key = self._normalize_portfolio_environment_name(portfolio_release.get('environment'))
        candidate_baselines = self._normalize_baseline_catalog_environment_entries(dict(promotion.get('candidate_baselines') or {}))
        candidate_entry = dict(candidate_baselines.get(env_key) or {})
        cloned_release = dict(portfolio_release or {})
        metadata = dict(cloned_release.get('metadata') or {})
        portfolio = dict(metadata.get('portfolio') or {})
        history = [dict(item) for item in list(portfolio.get('baseline_catalog_rollout_history') or [])]
        record = {
            'promotion_id': str(promotion_release.get('release_id') or ''),
            'catalog_id': str(promotion.get('catalog_id') or ''),
            'catalog_version': str(promotion.get('candidate_catalog_version') or promotion_release.get('version') or ''),
            'recorded_at': time.time(),
            'recorded_by': str(actor or 'admin'),
            'status': str(status or '').strip() or 'simulated',
            'active': bool(active),
            'wave_no': int(wave_no or 0) if wave_no is not None else None,
            'wave_id': str(wave_id or '').strip() or None,
            'reason': str(reason or '').strip(),
            'candidate_baselines': {env_key: candidate_entry} if candidate_entry else {},
            'simulated': True,
        }
        history.append(dict(record))
        portfolio['baseline_catalog_rollout_history'] = history[-50:]
        portfolio['current_baseline_catalog_rollout'] = record
        metadata['portfolio'] = portfolio
        cloned_release['metadata'] = metadata
        return cloned_release

    def _baseline_promotion_effective_signing_policy(
        self,
        *,
        promotion_release: dict[str, Any],
        promotion: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = dict(promotion or ((promotion_release.get('metadata') or {}).get('baseline_promotion') or {}) or {})
        environment_key = str(promotion_release.get('environment') or 'prod').strip().lower() or 'prod'
        candidate_baselines = self._normalize_baseline_catalog_environment_entries(dict(payload.get('candidate_baselines') or {}))
        previous_baselines = self._normalize_baseline_catalog_environment_entries(dict(payload.get('previous_baselines') or {}))
        candidate_entry = dict(candidate_baselines.get(environment_key) or candidate_baselines.get('default') or {})
        previous_entry = dict(previous_baselines.get(environment_key) or previous_baselines.get('default') or {})
        signing_policy = dict(candidate_entry.get('signing_policy') or previous_entry.get('signing_policy') or {})
        return self._normalize_portfolio_signing_policy(signing_policy)

    def _baseline_promotion_export_policy(
        self,
        *,
        promotion_release: dict[str, Any],
        promotion: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        signing_policy = self._baseline_promotion_effective_signing_policy(promotion_release=promotion_release, promotion=promotion)
        return {
            'enabled': True,
            'require_signature': True,
            'timeline_limit': 250,
            'signer_key_id': str(signing_policy.get('key_id') or 'openmiura-local').strip() or 'openmiura-local',
        }


    def _baseline_promotion_simulation_effective_signing_policy(
        self,
        *,
        simulation: dict[str, Any] | None,
    ) -> dict[str, Any]:
        payload = dict(simulation or {})
        scope = dict(payload.get('scope') or {})
        environment_key = self._normalize_portfolio_environment_name(
            scope.get('environment')
            or ((payload.get('observed_context') or {}).get('catalog') or {}).get('environment')
            or 'prod'
        )
        candidate_baselines = self._normalize_baseline_catalog_environment_entries(dict(payload.get('candidate_baselines') or {}))
        previous_baselines = self._normalize_baseline_catalog_environment_entries(dict(payload.get('previous_baselines') or {}))
        candidate_entry = dict(candidate_baselines.get(environment_key) or candidate_baselines.get('default') or {})
        previous_entry = dict(previous_baselines.get(environment_key) or previous_baselines.get('default') or {})
        if not candidate_entry and candidate_baselines:
            candidate_entry = dict(next(iter(candidate_baselines.values())) or {})
        if not previous_entry and previous_baselines:
            previous_entry = dict(next(iter(previous_baselines.values())) or {})
        signing_policy = dict(candidate_entry.get('signing_policy') or previous_entry.get('signing_policy') or {})
        return self._normalize_portfolio_signing_policy(signing_policy)

    def _baseline_promotion_simulation_export_policy(
        self,
        *,
        simulation: dict[str, Any] | None,
    ) -> dict[str, Any]:
        signing_policy = self._baseline_promotion_simulation_effective_signing_policy(simulation=simulation)
        return {
            'enabled': True,
            'require_signature': True,
            'timeline_limit': 250,
            'signer_key_id': str(signing_policy.get('key_id') or 'openmiura-local').strip() or 'openmiura-local',
        }

    @staticmethod
    def _baseline_promotion_simulation_timeline_view(
        simulation: dict[str, Any] | None,
        *,
        limit: int = 250,
    ) -> dict[str, Any]:
        payload = dict(simulation or {})
        items: list[dict[str, Any]] = []
        simulated_at = payload.get('simulated_at')
        if simulated_at is not None:
            items.append({
                'ts': float(simulated_at),
                'kind': 'simulation',
                'label': 'baseline_promotion_simulated',
                'actor': str(payload.get('simulated_by') or ''),
                'simulation_id': str(payload.get('simulation_id') or ''),
                'simulation_status': str(payload.get('simulation_status') or ''),
            })
        for review in list(((payload.get('review_state') or {}).get('items') or [])):
            review_item = dict(review or {})
            items.append({
                'ts': float(review_item.get('decided_at') or review_item.get('created_at') or 0.0),
                'kind': 'review',
                'label': 'baseline_promotion_simulation_reviewed',
                'review_id': str(review_item.get('review_id') or ''),
                'layer_id': str(review_item.get('layer_id') or ''),
                'requested_role': str(review_item.get('requested_role') or ''),
                'decision': str(review_item.get('decision') or ''),
                'actor': str(review_item.get('actor') or ''),
                'reason': str(review_item.get('reason') or ''),
            })
        for created in list(payload.get('created_promotions') or []):
            created_item = dict(created or {})
            items.append({
                'ts': float(created_item.get('created_at') or 0.0),
                'kind': 'promotion',
                'label': 'baseline_promotion_created_from_simulation',
                'promotion_id': str(created_item.get('promotion_id') or ''),
                'status': str(created_item.get('status') or ''),
                'actor': str(created_item.get('created_by') or ''),
                'auto_approved': bool(created_item.get('auto_approved')),
                'diverged': bool(created_item.get('diverged')),
            })
        items.sort(key=lambda item: (float(item.get('ts') or 0.0), str(item.get('kind') or ''), str(item.get('label') or ''), str(item.get('review_id') or item.get('promotion_id') or '')))
        capped = items[-max(1, int(limit or 250)):]
        return {
            'items': capped,
            'summary': {
                'count': len(capped),
                'review_count': len([item for item in capped if str(item.get('kind') or '') == 'review']),
                'promotion_count': len([item for item in capped if str(item.get('kind') or '') == 'promotion']),
                'latest_label': capped[-1].get('label') if capped else None,
            },
        }

    def _build_baseline_promotion_simulation_attestation_export_payload(
        self,
        *,
        simulation: dict[str, Any],
        actor: str,
        timeline_limit: int | None = None,
    ) -> dict[str, Any]:
        payload = dict(simulation or {})
        simulation_id = str(payload.get('simulation_id') or '').strip()
        scope = dict(payload.get('scope') or {})
        export_policy = self._baseline_promotion_simulation_export_policy(simulation=payload)
        signing_policy = self._baseline_promotion_simulation_effective_signing_policy(simulation=payload)
        timeline = self._baseline_promotion_simulation_timeline_view(payload, limit=max(25, int(timeline_limit or export_policy.get('timeline_limit') or 250)))
        review_state = dict(payload.get('review_state') or {})
        diff = dict(payload.get('diff') or {})
        report_id = str(self._stable_digest({
            'report_type': 'openmiura_baseline_promotion_simulation_attestation_v1',
            'simulation_id': simulation_id,
            'generated_by': str(actor or 'system'),
            'request_hash': str((payload.get('fingerprints') or {}).get('request_hash') or ''),
            'review_fingerprint': self._stable_digest(list(review_state.get('items') or [])),
        })[:24])
        report = {
            'report_id': report_id,
            'report_type': 'openmiura_baseline_promotion_simulation_attestation_v1',
            'generated_at': time.time(),
            'generated_by': str(actor or 'system'),
            'simulation': {
                'simulation_id': simulation_id,
                'mode': str(payload.get('mode') or ''),
                'simulation_status': str(payload.get('simulation_status') or ''),
                'simulated_at': payload.get('simulated_at'),
                'simulated_by': payload.get('simulated_by'),
                'reviewed_at': payload.get('reviewed_at'),
                'stale': bool(payload.get('stale')),
                'expired': bool(payload.get('expired')),
                'blocked': bool(payload.get('blocked')),
                'why_blocked': str(payload.get('why_blocked') or ''),
                'candidate_catalog_version': str(payload.get('candidate_catalog_version') or ''),
                'catalog_id': str(payload.get('catalog_id') or ''),
                'catalog_name': str(payload.get('catalog_name') or ''),
            },
            'scope': scope,
            'source': dict(payload.get('simulation_source') or {}),
            'request': dict(payload.get('request') or {}),
            'summary': dict(payload.get('summary') or {}),
            'validation': dict(payload.get('validation') or {}),
            'approval_preview': dict(payload.get('approval_preview') or {}),
            'simulation_policy': dict(payload.get('simulation_policy') or {}),
            'review': dict(payload.get('review') or {}),
            'review_state': {
                'overall_status': str(review_state.get('overall_status') or ''),
                'required': bool(review_state.get('required')),
                'approved': bool(review_state.get('approved')),
                'rejected': bool(review_state.get('rejected')),
                'review_count': int(review_state.get('review_count') or 0),
                'pending_layers': [str(item) for item in list(review_state.get('pending_layers') or []) if str(item)],
                'next_layer': dict(review_state.get('next_layer') or {}),
                'layers': [dict(item) for item in list(review_state.get('layers') or [])],
                'items': [dict(item) for item in list(review_state.get('items') or [])],
            },
            'observed_context': dict(payload.get('observed_context') or {}),
            'observed_versions': dict(payload.get('observed_versions') or payload.get('source_observed_versions') or {}),
            'fingerprints': dict(payload.get('fingerprints') or payload.get('source_fingerprints') or {}),
            'diff': {
                'summary': dict(diff.get('summary') or {}),
                'items': [
                    {
                        'environment': str(item.get('environment') or ''),
                        'changed': bool(item.get('changed')),
                        'change_type': str(item.get('change_type') or ''),
                        'compare': dict(item.get('compare') or {}),
                        'baseline_fingerprint': str(item.get('baseline_fingerprint') or ''),
                        'candidate_fingerprint': str(item.get('candidate_fingerprint') or ''),
                    }
                    for item in list(diff.get('items') or [])
                ],
            },
            'explainability': dict(payload.get('explainability') or {}),
            'created_promotions': [dict(item) for item in list(payload.get('created_promotions') or [])],
            'timeline': timeline,
        }
        integrity = self._portfolio_evidence_integrity(
            report_type=report['report_type'],
            scope=scope,
            payload=report,
            actor=actor,
            export_policy=export_policy,
            signing_policy=signing_policy,
        )
        return {
            'ok': True,
            'simulation_id': simulation_id,
            'report': report,
            'integrity': integrity,
            'scope': scope,
        }

    def _build_baseline_promotion_simulation_review_audit_export_payload(
        self,
        *,
        simulation: dict[str, Any],
        actor: str,
        timeline_limit: int | None = None,
    ) -> dict[str, Any]:
        payload = dict(simulation or {})
        simulation_id = str(payload.get('simulation_id') or '').strip()
        scope = dict(payload.get('scope') or {})
        export_policy = self._baseline_promotion_simulation_export_policy(simulation=payload)
        signing_policy = self._baseline_promotion_simulation_effective_signing_policy(simulation=payload)
        review_state = dict(payload.get('review_state') or {})
        review_items = [dict(item) for item in list(review_state.get('items') or [])]
        ordered_reviews = sorted(
            review_items,
            key=lambda item: (
                float(item.get('decided_at') or item.get('created_at') or 0.0),
                str(item.get('layer_id') or ''),
                str(item.get('review_id') or ''),
            ),
        )
        timeline = self._baseline_promotion_simulation_timeline_view(payload, limit=max(25, int(timeline_limit or export_policy.get('timeline_limit') or 250)))
        effective_policy = dict(payload.get('simulation_policy') or {})
        approval_policy = dict(effective_policy.get('approval_policy') or {})
        reviewer_ids = sorted({str(item.get('actor') or '').strip() for item in ordered_reviews if str(item.get('actor') or '').strip()})
        self_review_detected = str(payload.get('simulated_by') or '').strip() in reviewer_ids if reviewer_ids else False
        report_id = str(self._stable_digest({
            'report_type': 'openmiura_baseline_promotion_simulation_review_audit_v1',
            'simulation_id': simulation_id,
            'generated_by': str(actor or 'system'),
            'review_hash': self._stable_digest(ordered_reviews),
            'policy_hash': self._stable_digest(effective_policy),
        })[:24])
        report = {
            'report_id': report_id,
            'report_type': 'openmiura_baseline_promotion_simulation_review_audit_v1',
            'generated_at': time.time(),
            'generated_by': str(actor or 'system'),
            'simulation': {
                'simulation_id': simulation_id,
                'simulation_status': str(payload.get('simulation_status') or ''),
                'simulated_at': payload.get('simulated_at'),
                'simulated_by': payload.get('simulated_by'),
                'reviewed_at': payload.get('reviewed_at'),
                'catalog_id': str(payload.get('catalog_id') or ''),
                'candidate_catalog_version': str(payload.get('candidate_catalog_version') or ''),
            },
            'scope': scope,
            'effective_policy': {
                'simulation_policy': effective_policy,
                'approval_policy': approval_policy,
                'policy_fingerprint': self._stable_digest(effective_policy),
            },
            'review_sequence': {
                'mode': str(review_state.get('mode') or approval_policy.get('mode') or ''),
                'required': bool(review_state.get('required')),
                'overall_status': str(review_state.get('overall_status') or ''),
                'approved': bool(review_state.get('approved')),
                'rejected': bool(review_state.get('rejected')),
                'review_count': int(review_state.get('review_count') or 0),
                'approved_count': int(review_state.get('approved_count') or 0),
                'rejected_count': int(review_state.get('rejected_count') or 0),
                'pending_count': int(review_state.get('pending_count') or 0),
                'pending_layers': [str(item) for item in list(review_state.get('pending_layers') or []) if str(item)],
                'next_layer': dict(review_state.get('next_layer') or {}),
                'layers': [dict(item) for item in list(review_state.get('layers') or [])],
            },
            'separation_of_duties': {
                'allow_self_review': bool(effective_policy.get('allow_self_review', True)),
                'require_reason': bool(effective_policy.get('require_reason', False)),
                'block_on_rejection': bool(effective_policy.get('block_on_rejection', True)),
                'self_review_detected': self_review_detected,
                'distinct_reviewer_count': len(reviewer_ids),
                'reviewers': reviewer_ids,
            },
            'ordered_reviews': [
                {
                    'ordinal': idx + 1,
                    'review_id': str(item.get('review_id') or ''),
                    'layer_id': str(item.get('layer_id') or ''),
                    'label': str(item.get('label') or ''),
                    'requested_role': str(item.get('requested_role') or ''),
                    'decision': str(item.get('decision') or ''),
                    'actor': str(item.get('actor') or ''),
                    'reason': str(item.get('reason') or ''),
                    'created_at': item.get('created_at'),
                    'decided_at': item.get('decided_at'),
                }
                for idx, item in enumerate(ordered_reviews)
            ],
            'review_summary': dict(payload.get('review') or {}),
            'observed_versions': dict(payload.get('observed_versions') or payload.get('source_observed_versions') or {}),
            'fingerprints': dict(payload.get('fingerprints') or payload.get('source_fingerprints') or {}),
            'created_promotions': [dict(item) for item in list(payload.get('created_promotions') or [])],
            'timeline': timeline,
        }
        integrity = self._portfolio_evidence_integrity(
            report_type=report['report_type'],
            scope=scope,
            payload=report,
            actor=actor,
            export_policy=export_policy,
            signing_policy=signing_policy,
        )
        return {
            'ok': True,
            'simulation_id': simulation_id,
            'report': report,
            'integrity': integrity,
            'scope': scope,
        }

    @staticmethod
    def _baseline_promotion_simulation_evidence_retention_days(simulation: dict[str, Any] | None) -> int:
        payload = dict((simulation or {}).get('simulation_policy') or {})
        raw = payload.get('immutable_retention_days')
        if raw is None:
            raw = payload.get('retention_days')
        try:
            value = int(raw or 365)
        except Exception:
            value = 365
        return max(7, value)

    @staticmethod
    def _baseline_promotion_simulation_evidence_max_packages(simulation: dict[str, Any] | None) -> int:
        payload = dict((simulation or {}).get('simulation_policy') or {})
        raw = payload.get('max_evidence_packages')
        if raw is None:
            raw = payload.get('max_packages')
        try:
            value = int(raw or 50)
        except Exception:
            value = 50
        return max(1, value)

    def _baseline_promotion_simulation_effective_escrow_policy(
        self,
        *,
        simulation: dict[str, Any] | None,
        release: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        simulation_payload = dict(simulation or {})
        simulation_policy = dict(simulation_payload.get('simulation_policy') or {})
        scope = dict(simulation_payload.get('scope') or {})
        environment_key = self._normalize_portfolio_environment_name(
            scope.get('environment')
            or (release or {}).get('environment')
            or 'default'
        )
        raw_policy = dict(simulation_policy.get('escrow_policy') or {})
        if not raw_policy:
            candidate_baselines = self._normalize_baseline_catalog_environment_entries(dict(simulation_payload.get('candidate_baselines') or {}))
            candidate_entry = dict(candidate_baselines.get(environment_key) or candidate_baselines.get('default') or {})
            raw_policy = dict(candidate_entry.get('escrow_policy') or {})
        if not raw_policy and release:
            promotion = dict(((release.get('metadata') or {}).get('baseline_promotion')) or {})
            candidate_baselines = self._normalize_baseline_catalog_environment_entries(dict(promotion.get('candidate_baselines') or {}))
            candidate_entry = dict(candidate_baselines.get(environment_key) or candidate_baselines.get('default') or {})
            raw_policy = dict(candidate_entry.get('escrow_policy') or {})
            if not raw_policy:
                raw_policy = dict(((promotion.get('promotion_policy') or {}).get('escrow_policy')) or {})
        normalized = self._normalize_portfolio_escrow_policy(raw_policy)
        if normalized.get('enabled') and not str(normalized.get('archive_namespace') or '').strip():
            normalized['archive_namespace'] = 'baseline-promotion-simulation-evidence'
        elif not str(normalized.get('archive_namespace') or '').strip():
            normalized['archive_namespace'] = 'baseline-promotion-simulation-evidence'
        return normalized

    def _baseline_promotion_simulation_evidence_classification(
        self,
        *,
        simulation: dict[str, Any] | None,
        release: dict[str, Any] | None = None,
    ) -> str:
        simulation_payload = dict(simulation or {})
        simulation_policy = dict(simulation_payload.get('simulation_policy') or {})
        classification = str(
            simulation_policy.get('evidence_classification')
            or simulation_policy.get('classification')
            or ''
        ).strip()
        if classification:
            return classification
        scope = dict(simulation_payload.get('scope') or {})
        environment_key = self._normalize_portfolio_environment_name(
            scope.get('environment')
            or (release or {}).get('environment')
            or 'default'
        )
        candidate_baselines = self._normalize_baseline_catalog_environment_entries(dict(simulation_payload.get('candidate_baselines') or {}))
        candidate_entry = dict(candidate_baselines.get(environment_key) or candidate_baselines.get('default') or {})
        classification = str(candidate_entry.get('evidence_classification') or candidate_entry.get('classification') or '').strip()
        if classification:
            return classification
        if release:
            promotion = dict(((release.get('metadata') or {}).get('baseline_promotion')) or {})
            candidate_baselines = self._normalize_baseline_catalog_environment_entries(dict(promotion.get('candidate_baselines') or {}))
            candidate_entry = dict(candidate_baselines.get(environment_key) or candidate_baselines.get('default') or {})
            classification = str(candidate_entry.get('evidence_classification') or candidate_entry.get('classification') or '').strip()
            if classification:
                return classification
        return 'regulated-enterprise-evidence'

    def _baseline_promotion_simulation_evidence_export_policy(
        self,
        *,
        simulation: dict[str, Any] | None,
        release: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        signing_policy = self._baseline_promotion_simulation_effective_signing_policy(simulation=simulation)
        escrow_policy = self._baseline_promotion_simulation_effective_escrow_policy(simulation=simulation, release=release)
        embed_artifact_content = True
        if bool(escrow_policy.get('enabled')) and not bool(escrow_policy.get('allow_inline_fallback', True)):
            embed_artifact_content = False
        return {
            'enabled': True,
            'require_signature': True,
            'embed_artifact_content': embed_artifact_content,
            'timeline_limit': 250,
            'artifact_format': 'zip',
            'retention_days': self._baseline_promotion_simulation_evidence_retention_days(simulation),
            'max_packages': self._baseline_promotion_simulation_evidence_max_packages(simulation),
            'registry_mode': 'append_only_hash_chain',
            'signer_key_id': str(signing_policy.get('key_id') or 'openmiura-local').strip() or 'openmiura-local',
            'escrow_enabled': bool(escrow_policy.get('enabled')),
        }

    def _baseline_promotion_simulation_evidence_package_manifest(
        self,
        *,
        package_id: str,
        attestation_export: dict[str, Any],
        review_audit_export: dict[str, Any],
        simulation: dict[str, Any],
        export_policy: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], str]:
        artifacts = [
            {
                'artifact_id': str(((attestation_export.get('report') or {}).get('report_id') or '')),
                'kind': 'simulation_attestation',
                'report_type': str(((attestation_export.get('report') or {}).get('report_type') or '')),
                'payload_hash': str((attestation_export.get('integrity') or {}).get('payload_hash') or self._stable_digest(dict(attestation_export.get('report') or {}))),
            },
            {
                'artifact_id': str(((review_audit_export.get('report') or {}).get('report_id') or '')),
                'kind': 'simulation_review_audit',
                'report_type': str(((review_audit_export.get('report') or {}).get('report_type') or '')),
                'payload_hash': str((review_audit_export.get('integrity') or {}).get('payload_hash') or self._stable_digest(dict(review_audit_export.get('report') or {}))),
            },
        ]
        manifest = {
            'package_id': package_id,
            'report_type': 'openmiura_baseline_promotion_simulation_evidence_package_manifest_v1',
            'generated_at': time.time(),
            'registry_mode': str((export_policy or {}).get('registry_mode') or 'append_only_hash_chain'),
            'simulation_id': str(simulation.get('simulation_id') or ''),
            'catalog_id': str(simulation.get('catalog_id') or ''),
            'candidate_catalog_version': str(simulation.get('candidate_catalog_version') or ''),
            'artifact_count': len(artifacts),
            'artifacts': artifacts,
            'simulation_fingerprint': str((simulation.get('fingerprints') or {}).get('request_hash') or self._stable_digest(dict(simulation.get('request') or {}))),
        }
        return manifest, self._stable_digest(manifest)

    def _build_baseline_promotion_simulation_evidence_artifact_archive(
        self,
        *,
        package_payload: dict[str, Any],
        integrity: dict[str, Any],
        export_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        package_id = str(package_payload.get('package_id') or '').strip()
        promotion_id = str(((package_payload.get('source_promotion') or {}).get('promotion_id')) or '').strip()
        simulation_id = str(((package_payload.get('simulation') or {}).get('simulation_id')) or '').strip()
        generated_at = float(package_payload.get('generated_at') or time.time())
        entries_payload = {
            'manifest.json': dict(package_payload.get('manifest') or {}),
            'package.json': package_payload,
            'integrity.json': integrity,
            'simulation_attestation_export.json': dict(((package_payload.get('artifacts') or {}).get('simulation_attestation_export') or {})),
            'simulation_review_audit_export.json': dict(((package_payload.get('artifacts') or {}).get('simulation_review_audit_export') or {})),
            'registry_entry.json': dict(package_payload.get('registry_entry_preview') or {}),
        }
        entry_bytes = {name: self._canonical_json_bytes(payload) for name, payload in entries_payload.items()}
        zip_buffer = io.BytesIO()
        dt = datetime.fromtimestamp(generated_at, tz=timezone.utc)
        zip_dt = (max(1980, dt.year), dt.month, dt.day, dt.hour, dt.minute, dt.second)
        with zipfile.ZipFile(zip_buffer, mode='w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            for name in sorted(entry_bytes):
                info = zipfile.ZipInfo(filename=name, date_time=zip_dt)
                info.compress_type = zipfile.ZIP_DEFLATED
                zf.writestr(info, entry_bytes[name])
        archive_bytes = zip_buffer.getvalue()
        archive_sha256 = hashlib.sha256(archive_bytes).hexdigest()
        filename_prefix = f'openmiura-baseline-promotion-simulation-{promotion_id or simulation_id or "simulation"}-{package_id or "artifact"}'
        return {
            'artifact_type': 'openmiura_baseline_promotion_simulation_evidence_artifact_v1',
            'package_id': package_id,
            'promotion_id': promotion_id or None,
            'simulation_id': simulation_id or None,
            'filename': f'{filename_prefix}.zip',
            'media_type': 'application/zip',
            'format': str((export_policy or {}).get('artifact_format') or 'zip'),
            'sha256': archive_sha256,
            'size_bytes': len(archive_bytes),
            'encoding': 'base64',
            'content_b64': base64.b64encode(archive_bytes).decode('ascii'),
            'entries': [
                {
                    'name': name,
                    'sha256': hashlib.sha256(payload).hexdigest(),
                    'size_bytes': len(payload),
                }
                for name, payload in sorted(entry_bytes.items())
            ],
        }

    def _archive_baseline_promotion_simulation_evidence_artifact_external(
        self,
        *,
        artifact: dict[str, Any],
        package_payload: dict[str, Any],
        integrity: dict[str, Any],
        retention: dict[str, Any],
        actor: str,
        escrow_policy: dict[str, Any] | None = None,
        signing_policy: dict[str, Any] | None = None,
        generated_at: float | None = None,
    ) -> dict[str, Any]:
        normalized = self._normalize_portfolio_escrow_policy(dict(escrow_policy or {}))
        if not bool(normalized.get('enabled')):
            return {
                'enabled': False,
                'archived': False,
                'provider': normalized.get('provider'),
                'reason': 'escrow_disabled',
            }
        provider = str(normalized.get('provider') or 'filesystem-governed').strip() or 'filesystem-governed'
        if provider not in {'filesystem-governed', 'filesystem-object-lock', 'object-lock-filesystem'}:
            return {
                'enabled': True,
                'archived': False,
                'provider': provider,
                'reason': 'provider_not_supported_for_simulation_evidence',
            }
        content_b64 = str(artifact.get('content_b64') or '').strip()
        if not content_b64:
            return {
                'enabled': True,
                'archived': False,
                'provider': provider,
                'reason': 'artifact_content_missing',
            }
        generated_ts = float(generated_at) if generated_at is not None else float(package_payload.get('generated_at') or time.time())
        scope = dict(package_payload.get('scope') or {})
        archive_bytes = base64.b64decode(content_b64.encode('ascii'))
        artifact_sha256 = hashlib.sha256(archive_bytes).hexdigest()
        receipt_id = str(uuid.uuid4())
        filename = str(artifact.get('filename') or f'{package_payload.get("package_id")}.zip').strip() or f'{package_payload.get("package_id")}.zip'
        promotion_id = str(((package_payload.get('source_promotion') or {}).get('promotion_id')) or '').strip() or 'promotion'
        simulation_id = str(((package_payload.get('simulation') or {}).get('simulation_id')) or '').strip() or 'simulation'
        package_id = str(package_payload.get('package_id') or '').strip() or 'package'
        manifest_payload = dict((package_payload.get('manifest') or {}))
        manifest_bytes = self._canonical_json_bytes(manifest_payload)
        immutable_until = retention.get('retain_until')
        if immutable_until is None:
            immutable_until = generated_ts + (max(1, int(normalized.get('immutable_retention_days') or 365)) * 86400.0)
        root_dir = Path(str(normalized.get('root_dir') or 'data/openclaw_evidence_escrow'))
        archive_dir = root_dir.joinpath(
            str(normalized.get('archive_namespace') or 'baseline-promotion-simulation-evidence'),
            str(scope.get('tenant_id') or 'global'),
            str(scope.get('workspace_id') or 'default'),
            str(scope.get('environment') or 'default'),
            str(promotion_id or 'promotion'),
            str(package_id or 'package'),
        )
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive_path = archive_dir.joinpath(filename)
        manifest_path = archive_dir.joinpath('manifest.json')
        receipt_path = archive_dir.joinpath(f'{filename}.receipt.json')
        lock_path = archive_dir.joinpath(f'{filename}.lock.json')

        archive_path_public = self._filesystem_path(archive_path)
        manifest_path_public = self._filesystem_path(manifest_path)
        receipt_path_public = self._filesystem_path(receipt_path)
        lock_path_public = self._filesystem_path(lock_path)

        if self._path_exists(archive_path):
            existing_bytes = self._read_file_bytes(archive_path)
            if hashlib.sha256(existing_bytes).hexdigest() != artifact_sha256:
                return {
                    'enabled': True,
                    'archived': False,
                    'provider': provider,
                    'reason': 'immutable_archive_conflict',
                    'archive_path': archive_path_public,
                }
        else:
            self._write_file_if_absent(archive_path, archive_bytes)
        if not self._path_exists(manifest_path):
            self._write_file_if_absent(manifest_path, manifest_bytes)
        object_lock_enabled = bool(normalized.get('object_lock_enabled'))
        if object_lock_enabled:
            lock_payload = {
                'lock_type': 'openmiura_baseline_promotion_simulation_object_lock_v1',
                'provider': provider,
                'archive_path': archive_path_public,
                'artifact_sha256': artifact_sha256,
                'package_id': package_id,
                'promotion_id': promotion_id,
                'simulation_id': simulation_id,
                'immutable_until': immutable_until,
                'retention_mode': str(normalized.get('retention_mode') or 'GOVERNANCE'),
                'legal_hold': bool(retention.get('legal_hold', False)),
                'locked_at': generated_ts,
            }
            if lock_path.exists():
                existing_lock = json.loads(self._read_file_text(lock_path, encoding='utf-8'))
                if str(existing_lock.get('artifact_sha256') or '') != artifact_sha256:
                    return {
                        'enabled': True,
                        'archived': False,
                        'provider': provider,
                        'reason': 'object_lock_conflict',
                        'lock_path': lock_path_public,
                    }
            elif bool(normalized.get('lock_sidecar', True)):
                self._write_file_if_absent(lock_path, self._canonical_json_bytes(lock_payload))
        receipt_payload = {
            'receipt_type': 'openmiura_baseline_promotion_simulation_evidence_escrow_receipt_v1',
            'receipt_id': receipt_id,
            'provider': provider,
            'mode': str(normalized.get('mode') or 'filesystem_external'),
            'archived': True,
            'archived_at': generated_ts,
            'archived_by': str(actor or 'system').strip() or 'system',
            'package_id': package_id,
            'promotion_id': promotion_id,
            'simulation_id': simulation_id,
            'scope': scope,
            'archive_path': archive_path_public,
            'archive_uri': f'file://{archive_path_public}',
            'receipt_path': receipt_path_public,
            'manifest_path': manifest_path_public,
            'artifact_sha256': artifact_sha256,
            'manifest_hash': ((package_payload.get('manifest') or {}).get('manifest_hash')),
            'immutable_until': immutable_until,
            'classification': retention.get('classification'),
            'legal_hold': bool(retention.get('legal_hold', False)),
            'object_lock_enabled': object_lock_enabled,
            'retention_mode': str(normalized.get('retention_mode') or 'none'),
            'lock_path': lock_path_public if object_lock_enabled and bool(normalized.get('lock_sidecar', True)) else None,
            'delete_protection': bool(normalized.get('delete_protection', object_lock_enabled)),
        }
        crypto = self._sign_portfolio_payload_crypto_v2(
            report_type='openmiura_baseline_promotion_simulation_evidence_escrow_receipt_v1',
            scope=scope,
            payload=receipt_payload,
            signer_key_id=str(normalized.get('escrow_key_id') or 'openmiura-escrow').strip() or 'openmiura-escrow',
            signing_policy=signing_policy,
        )
        receipt_payload.update({
            'signature': crypto.get('signature'),
            'signature_scheme': crypto.get('signature_scheme'),
            'signature_input': crypto.get('signature_input'),
            'public_key': crypto.get('public_key'),
            'crypto_v2': True,
            'signer_provider': crypto.get('signer_provider'),
            'key_origin': crypto.get('key_origin'),
        })
        receipt_bytes = self._canonical_json_bytes(receipt_payload)
        if receipt_path.exists():
            existing_receipt = json.loads(self._read_file_text(receipt_path, encoding='utf-8'))
            if str(existing_receipt.get('artifact_sha256') or '') != artifact_sha256:
                return {
                    'enabled': True,
                    'archived': False,
                    'provider': provider,
                    'reason': 'immutable_receipt_conflict',
                    'receipt_path': receipt_path_public,
                }
        else:
            self._write_file_if_absent(receipt_path, receipt_bytes)
        return receipt_payload

    def _load_baseline_promotion_simulation_evidence_artifact_from_escrow(self, *, escrow: dict[str, Any] | None = None) -> dict[str, Any] | None:
        receipt = dict(escrow or {})
        archive_path = str(receipt.get('archive_path') or '').strip()
        if not archive_path:
            return None
        path = Path(archive_path)
        if not self._path_exists(path) or not self._path_is_file(path):
            return None
        archive_bytes = self._read_file_bytes(path)
        return {
            'artifact_type': 'openmiura_baseline_promotion_simulation_evidence_artifact_v1',
            'package_id': receipt.get('package_id'),
            'promotion_id': receipt.get('promotion_id'),
            'simulation_id': receipt.get('simulation_id'),
            'filename': path.name,
            'media_type': 'application/zip',
            'format': 'zip',
            'sha256': hashlib.sha256(archive_bytes).hexdigest(),
            'size_bytes': len(archive_bytes),
            'encoding': 'base64',
            'content_b64': base64.b64encode(archive_bytes).decode('ascii'),
            'escrow': self._redact_large_blob(receipt),
        }

    def _verify_baseline_promotion_simulation_escrow_receipt(
        self,
        *,
        escrow: dict[str, Any] | None,
        now_ts: float | None = None,
    ) -> dict[str, Any]:
        receipt = dict(escrow or {})
        if not bool(receipt.get('archived')):
            return {'required': False, 'valid': True, 'status': 'not_archived'}
        archive_path = str(receipt.get('archive_path') or '').strip()
        if not archive_path:
            return {'required': True, 'valid': False, 'status': 'missing_archive_path'}
        path = Path(archive_path)
        if not self._path_exists(path) or not self._path_is_file(path):
            return {'required': True, 'valid': False, 'status': 'archive_missing'}
        archive_bytes = self._read_file_bytes(path)
        archive_sha256 = hashlib.sha256(archive_bytes).hexdigest()
        canonical = {
            'receipt_type': 'openmiura_baseline_promotion_simulation_evidence_escrow_receipt_v1',
            'receipt_id': receipt.get('receipt_id'),
            'provider': receipt.get('provider'),
            'mode': receipt.get('mode'),
            'archived': True,
            'archived_at': receipt.get('archived_at'),
            'archived_by': receipt.get('archived_by'),
            'package_id': receipt.get('package_id'),
            'promotion_id': receipt.get('promotion_id'),
            'simulation_id': receipt.get('simulation_id'),
            'scope': dict(receipt.get('scope') or {}),
            'archive_path': archive_path,
            'archive_uri': receipt.get('archive_uri'),
            'receipt_path': receipt.get('receipt_path'),
            'manifest_path': receipt.get('manifest_path'),
            'artifact_sha256': receipt.get('artifact_sha256'),
            'manifest_hash': receipt.get('manifest_hash'),
            'immutable_until': receipt.get('immutable_until'),
            'classification': receipt.get('classification'),
            'legal_hold': bool(receipt.get('legal_hold', False)),
            'object_lock_enabled': bool(receipt.get('object_lock_enabled', False)),
            'retention_mode': receipt.get('retention_mode'),
            'lock_path': receipt.get('lock_path'),
            'delete_protection': bool(receipt.get('delete_protection', False)),
        }
        crypto_verify = self._verify_portfolio_crypto_signature(
            report_type='openmiura_baseline_promotion_simulation_evidence_escrow_receipt_v1',
            scope=dict(receipt.get('scope') or {}),
            payload=canonical,
            integrity={
                'signed': True,
                'signature': receipt.get('signature'),
                'signature_scheme': receipt.get('signature_scheme'),
                'signature_input': receipt.get('signature_input'),
                'public_key': receipt.get('public_key'),
                'signer_key_id': str(((receipt.get('signature_input') or {}).get('signer_key_id')) or ''),
                'payload_hash': self._stable_digest(canonical),
                'crypto_v2': True,
            },
        )
        resolved_now = float(now_ts) if now_ts is not None else time.time()
        immutable_active = receipt.get('immutable_until') is not None and float(receipt.get('immutable_until') or 0.0) >= resolved_now
        archive_hash_valid = str(receipt.get('artifact_sha256') or '') == archive_sha256
        receipt_path = str(receipt.get('receipt_path') or '').strip()
        receipt_file_present = True
        receipt_file_valid = True
        if receipt_path:
            receipt_file = Path(receipt_path)
            if not self._path_exists(receipt_file) or not self._path_is_file(receipt_file):
                receipt_file_present = False
                receipt_file_valid = False
            else:
                try:
                    receipt_payload = json.loads(self._read_file_text(receipt_file, encoding='utf-8'))
                except Exception:
                    receipt_payload = {}
                compare_keys = [
                    'receipt_id',
                    'provider',
                    'mode',
                    'package_id',
                    'promotion_id',
                    'simulation_id',
                    'archive_path',
                    'artifact_sha256',
                    'manifest_hash',
                    'immutable_until',
                    'retention_mode',
                ]
                receipt_file_valid = all(receipt_payload.get(key) == receipt.get(key) for key in compare_keys)
                receipt_file_valid = receipt_file_valid and str(receipt_payload.get('signature') or '') == str(receipt.get('signature') or '')
        manifest_path = str(receipt.get('manifest_path') or '').strip()
        manifest_present = True
        manifest_hash_valid = True
        if manifest_path:
            manifest_file = Path(manifest_path)
            if not self._path_exists(manifest_file) or not self._path_is_file(manifest_file):
                manifest_present = False
                manifest_hash_valid = False
            else:
                try:
                    manifest_payload = json.loads(self._read_file_text(manifest_file, encoding='utf-8'))
                except Exception:
                    manifest_payload = {}
                manifest_payload_for_hash = dict(manifest_payload)
                manifest_payload_for_hash.pop('manifest_hash', None)
                manifest_hash_valid = str(receipt.get('manifest_hash') or '') == self._stable_digest(manifest_payload_for_hash)
        object_lock_valid = True
        if bool(receipt.get('object_lock_enabled')):
            lock_path = str(receipt.get('lock_path') or '').strip()
            object_lock_valid = False
            if lock_path:
                lock_file = Path(lock_path)
                if self._path_exists(lock_file) and self._path_is_file(lock_file):
                    try:
                        lock_payload = json.loads(self._read_file_text(lock_file, encoding='utf-8'))
                    except Exception:
                        lock_payload = {}
                    object_lock_valid = (
                        str(lock_payload.get('artifact_sha256') or '') == archive_sha256
                        and str(lock_payload.get('archive_path') or '') == archive_path
                        and str(lock_payload.get('retention_mode') or '') == str(receipt.get('retention_mode') or '')
                    )
            if not object_lock_valid and not lock_path:
                object_lock_valid = False
        valid = (
            archive_hash_valid
            and bool(crypto_verify.get('valid'))
            and receipt_file_valid
            and manifest_hash_valid
            and (object_lock_valid or not bool(receipt.get('object_lock_enabled')))
        )
        status = 'verified' if valid else 'failed'
        if not archive_hash_valid:
            status = 'artifact_hash_mismatch'
        elif not bool(crypto_verify.get('valid')):
            status = 'signature_invalid'
        elif not receipt_file_present:
            status = 'receipt_missing'
        elif not receipt_file_valid:
            status = 'receipt_mismatch'
        elif not manifest_present:
            status = 'manifest_missing'
        elif not manifest_hash_valid:
            status = 'manifest_hash_mismatch'
        elif bool(receipt.get('object_lock_enabled')) and not object_lock_valid:
            status = 'object_lock_invalid'
        return {
            'required': True,
            'valid': valid,
            'status': status,
            'archive_hash_valid': archive_hash_valid,
            'artifact_sha256': archive_sha256,
            'immutable_active': immutable_active,
            'object_lock_valid': object_lock_valid,
            'receipt_file_present': receipt_file_present,
            'receipt_file_valid': receipt_file_valid,
            'manifest_present': manifest_present,
            'manifest_hash_valid': manifest_hash_valid,
            'crypto': crypto_verify,
            'receipt': self._redact_large_blob(receipt),
        }


    def _baseline_promotion_simulation_evidence_registry_consistency(
        self,
        *,
        stored_package: dict[str, Any] | None,
        registry_entries: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        package = dict(stored_package or {})
        stored_registry = dict(package.get('registry_entry') or {})
        entries = [dict(item) for item in list(registry_entries or [])]
        entries.sort(key=lambda item: (int(item.get('sequence') or 0), float(item.get('appended_at') or 0.0), str(item.get('entry_id') or '')))
        chain_valid = True
        previous_hash = ''
        expected_sequence = 1
        for item in entries:
            item_core = dict(item.get('entry_core') or {k: v for k, v in item.items() if k not in {'entry_hash', 'entry_core'}})
            if int(item.get('sequence') or 0) != expected_sequence:
                chain_valid = False
                expected_sequence = int(item.get('sequence') or expected_sequence)
            if str(item.get('previous_entry_hash') or '') != previous_hash:
                chain_valid = False
            if self._stable_digest(item_core) != str(item.get('entry_hash') or ''):
                chain_valid = False
            previous_hash = str(item.get('entry_hash') or '')
            expected_sequence += 1
        target_entry_id = str(stored_registry.get('entry_id') or '').strip()
        target_package_id = str(package.get('package_id') or '').strip()
        matching = None
        if target_entry_id:
            for item in entries:
                if str(item.get('entry_id') or '') == target_entry_id:
                    matching = dict(item)
                    break
        if matching is None and target_package_id:
            for item in entries:
                if str(item.get('package_id') or '') == target_package_id:
                    matching = dict(item)
                    break
        membership_valid = matching is not None if (target_entry_id or target_package_id) else not bool(entries)
        match_valid = True
        if matching is not None:
            compare_keys = ['entry_id', 'sequence', 'entry_hash', 'previous_entry_hash']
            for key in compare_keys:
                if stored_registry.get(key) not in (None, '', 0) and matching.get(key) != stored_registry.get(key):
                    match_valid = False
            if str(package.get('manifest_hash') or '').strip() and str(matching.get('manifest_hash') or '').strip() != str(package.get('manifest_hash') or '').strip():
                match_valid = False
        elif target_entry_id or target_package_id:
            match_valid = False
        latest = dict(entries[-1] or {}) if entries else {}
        return {
            'entry_id': str((matching or stored_registry).get('entry_id') or ''),
            'sequence': int((matching or stored_registry).get('sequence') or 0),
            'entry_hash': str((matching or stored_registry).get('entry_hash') or ''),
            'previous_entry_hash': str((matching or stored_registry).get('previous_entry_hash') or ''),
            'membership_valid': membership_valid,
            'match_valid': match_valid,
            'chain_valid': chain_valid,
            'latest_entry_id': str(latest.get('entry_id') or ''),
            'latest_entry_hash': str(latest.get('entry_hash') or ''),
            'count': len(entries),
        }

    def _baseline_promotion_simulation_evidence_reconciliation_item(
        self,
        *,
        stored_package: dict[str, Any],
        registry_entries: list[dict[str, Any]] | None = None,
        now_ts: float | None = None,
    ) -> dict[str, Any]:
        package = dict(stored_package or {})
        escrow = dict(package.get('escrow') or {})
        verification = self._verify_baseline_promotion_simulation_evidence_artifact_payload(
            artifact=dict(package.get('artifact') or {}),
            registry_entries=registry_entries,
            stored_package=package,
            now_ts=now_ts,
        )
        registry = self._baseline_promotion_simulation_evidence_registry_consistency(
            stored_package=package,
            registry_entries=registry_entries,
        )
        drift_reasons: list[str] = []
        verification_status = str(verification.get('error') or 'verification_unavailable')
        verification_valid = False
        checks: dict[str, Any] = {}
        escrow_status = 'not_archived'
        escrow_verify = self._verify_baseline_promotion_simulation_escrow_receipt(escrow=escrow, now_ts=now_ts) if escrow else {'required': False, 'valid': True, 'status': 'not_archived'}
        if verification.get('ok'):
            verification_payload = dict(verification.get('verification') or {})
            verification_status = str(verification_payload.get('status') or '')
            verification_valid = bool(verification_payload.get('valid'))
            checks = dict(verification_payload.get('checks') or {})
            escrow_verify = dict(verification_payload.get('escrow') or escrow_verify)
            escrow_status = str(escrow_verify.get('status') or 'not_archived')
            if not bool(checks.get('archive_hash_valid', True)):
                drift_reasons.append('artifact_hash_mismatch')
            if not bool(checks.get('manifest_hash_valid', True)):
                drift_reasons.append('manifest_hash_mismatch')
            if not bool(checks.get('manifest_links_valid', True)):
                drift_reasons.append('manifest_links_invalid')
            if not bool(checks.get('package_integrity_valid', True)):
                drift_reasons.append('package_integrity_invalid')
            if not bool(checks.get('attestation_export_valid', True)):
                drift_reasons.append('attestation_export_invalid')
            if not bool(checks.get('review_audit_export_valid', True)):
                drift_reasons.append('review_audit_export_invalid')
            if not bool(checks.get('stored_package_match_valid', True)):
                drift_reasons.append('stored_package_mismatch')
        else:
            escrow_status = str(escrow_verify.get('status') or 'not_archived')
            drift_reasons.append(str(verification.get('error') or 'verification_failed'))
        if escrow and bool(escrow.get('archived')):
            if not bool(escrow_verify.get('valid')):
                drift_reasons.append(str(escrow_status or 'escrow_receipt_invalid'))
            elif str(escrow_status or '') != 'verified':
                drift_reasons.append(str(escrow_status or 'escrow_receipt_invalid'))
            lock_expected = bool(escrow.get('object_lock_enabled')) and bool(escrow.get('immutable_until'))
            if lock_expected:
                try:
                    lock_expected = float(escrow.get('immutable_until') or 0.0) >= float(now_ts if now_ts is not None else time.time())
                except Exception:
                    lock_expected = True
            if lock_expected and not (bool(escrow_verify.get('object_lock_valid')) and bool(escrow_verify.get('immutable_active'))):
                drift_reasons.append('immutable_lock_inactive')
            if not bool(escrow_verify.get('receipt_file_valid', True)):
                drift_reasons.append('receipt_sidecar_invalid')
            if not bool(escrow_verify.get('manifest_hash_valid', True)):
                drift_reasons.append('manifest_sidecar_invalid')
        if not bool(registry.get('membership_valid')):
            drift_reasons.append('registry_entry_missing')
        if not bool(registry.get('match_valid')):
            drift_reasons.append('registry_entry_mismatch')
        if not bool(registry.get('chain_valid')):
            drift_reasons.append('registry_chain_invalid')
        unique_reasons: list[str] = []
        for reason in drift_reasons:
            normalized = str(reason or '').strip()
            if normalized and normalized not in unique_reasons:
                unique_reasons.append(normalized)
        status = 'aligned' if not unique_reasons else 'drifted'
        artifact_meta = dict(package.get('artifact') or {})
        if verification.get('ok'):
            artifact_meta = dict(verification.get('artifact') or artifact_meta)
        return {
            'package_id': str(package.get('package_id') or ''),
            'simulation_id': str(package.get('simulation_id') or ''),
            'created_at': package.get('created_at'),
            'reconciliation_status': status,
            'verification_status': verification_status,
            'verification_valid': verification_valid,
            'drift_reasons': unique_reasons,
            'artifact': {
                'artifact_type': str(artifact_meta.get('artifact_type') or ''),
                'sha256': str(artifact_meta.get('sha256') or ''),
                'size_bytes': int(artifact_meta.get('size_bytes') or 0),
                'filename': str(artifact_meta.get('filename') or ''),
                'source': str(artifact_meta.get('source') or ('escrow' if bool(escrow.get('archived')) else 'inline')),
            },
            'escrow': {
                'archived': bool(escrow.get('archived')),
                'status': escrow_status,
                'receipt_id': str(escrow.get('receipt_id') or ''),
                'archive_path': str(escrow.get('archive_path') or ''),
                'immutable_until': escrow.get('immutable_until'),
                'immutable_active': bool(escrow_verify.get('immutable_active')),
                'object_lock_enabled': bool(escrow.get('object_lock_enabled')),
                'object_lock_valid': bool(escrow_verify.get('object_lock_valid', True)),
                'receipt_file_valid': bool(escrow_verify.get('receipt_file_valid', True)),
                'manifest_hash_valid': bool(escrow_verify.get('manifest_hash_valid', True)),
                'archive_hash_valid': bool(escrow_verify.get('archive_hash_valid', True)),
            },
            'registry': registry,
            'checks': {
                'verification_ok': bool(verification.get('ok')),
                'verification_valid': verification_valid,
                'escrow_receipt_valid': bool(escrow_verify.get('valid', True)),
                'registry_membership_valid': bool(registry.get('membership_valid')),
                'registry_match_valid': bool(registry.get('match_valid')),
                'registry_chain_valid': bool(registry.get('chain_valid')),
                'stored_package_match_valid': bool(checks.get('stored_package_match_valid', True)),
            },
        }

    @staticmethod
    def _baseline_promotion_simulation_evidence_reconciliation_summary(items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        payload = [dict(item) for item in list(items or [])]
        aligned_count = sum(1 for item in payload if str(item.get('reconciliation_status') or '') == 'aligned')
        drifted_count = sum(1 for item in payload if str(item.get('reconciliation_status') or '') == 'drifted')
        escrowed_count = sum(1 for item in payload if bool((item.get('escrow') or {}).get('archived')))
        missing_archive_count = sum(1 for item in payload if str(((item.get('escrow') or {}).get('status')) or '') == 'archive_missing')
        lock_drift_count = sum(1 for item in payload if 'immutable_lock_inactive' in list(item.get('drift_reasons') or []))
        registry_drift_count = sum(1 for item in payload if any(reason.startswith('registry_') for reason in list(item.get('drift_reasons') or [])))
        receipt_drift_count = sum(1 for item in payload if any(reason in {'receipt_sidecar_invalid', 'manifest_sidecar_invalid', 'receipt_missing', 'receipt_mismatch', 'manifest_missing', 'manifest_hash_mismatch'} for reason in list(item.get('drift_reasons') or [])))
        overall_status = 'aligned' if drifted_count == 0 else 'drifted'
        latest = dict(payload[0] or {}) if payload else {}
        return {
            'count': len(payload),
            'aligned_count': aligned_count,
            'drifted_count': drifted_count,
            'escrowed_count': escrowed_count,
            'missing_archive_count': missing_archive_count,
            'lock_drift_count': lock_drift_count,
            'registry_drift_count': registry_drift_count,
            'receipt_drift_count': receipt_drift_count,
            'overall_status': overall_status,
            'latest_package_id': str(latest.get('package_id') or ''),
            'latest_status': str(latest.get('reconciliation_status') or ''),
            'latest_archive_path': str((((latest.get('escrow') or {}).get('archive_path')) or '')),
        }

    def _baseline_promotion_simulation_custody_monitoring_policy_for_release(self, release: dict[str, Any] | None, simulation: dict[str, Any] | None = None) -> dict[str, Any]:
        metadata = dict((release or {}).get('metadata') or {})
        promotion = dict(metadata.get('baseline_promotion') or {})
        promotion_policy = self._normalize_baseline_catalog_promotion_policy(dict(promotion.get('promotion_policy') or {}))
        policy = self._normalize_baseline_promotion_simulation_custody_monitoring_policy(dict(promotion_policy.get('simulation_custody_monitoring_policy') or {}))
        sim_policy = dict((dict(simulation or {}).get('simulation_policy') or {}))
        if sim_policy:
            policy = {
                **policy,
                **self._normalize_baseline_promotion_simulation_custody_monitoring_policy(dict(sim_policy.get('custody_monitoring_policy') or {})),
            }
        return self._normalize_baseline_promotion_simulation_custody_monitoring_policy(policy)


    @staticmethod
    def _baseline_promotion_simulation_custody_capacity_tier_state(
        *,
        active_count: int,
        capacity: int,
        general_capacity: int,
        reserved_capacity: int = 0,
        leased_capacity: int = 0,
        hold_capacity: int = 0,
    ) -> dict[str, int | None]:
        total_capacity = max(0, int(capacity or 0))
        general_capacity_value = max(0, min(total_capacity, int(general_capacity or 0)))
        remaining_capacity = max(0, total_capacity - general_capacity_value)
        reserved_capacity_value = max(0, min(remaining_capacity, int(reserved_capacity or 0)))
        remaining_capacity = max(0, remaining_capacity - reserved_capacity_value)
        leased_capacity_value = max(0, min(remaining_capacity, int(leased_capacity or 0)))
        remaining_capacity = max(0, remaining_capacity - leased_capacity_value)
        hold_capacity_value = max(0, min(remaining_capacity, int(hold_capacity or 0)))
        active_value = max(0, int(active_count or 0))
        general_used = min(active_value, general_capacity_value)
        remaining_active = max(0, active_value - general_used)
        reserved_used = min(remaining_active, reserved_capacity_value)
        remaining_active = max(0, remaining_active - reserved_used)
        leased_used = min(remaining_active, leased_capacity_value)
        remaining_active = max(0, remaining_active - leased_used)
        hold_used = min(remaining_active, hold_capacity_value)
        return {
            'general_capacity': general_capacity_value,
            'reserved_capacity': reserved_capacity_value,
            'leased_capacity': leased_capacity_value,
            'hold_capacity': hold_capacity_value,
            'general_available': (max(0, general_capacity_value - general_used) if total_capacity > 0 else None),
            'reserved_available': (max(0, reserved_capacity_value - reserved_used) if total_capacity > 0 else None),
            'lease_available': (max(0, leased_capacity_value - leased_used) if total_capacity > 0 else None),
            'hold_available': (max(0, hold_capacity_value - hold_used) if total_capacity > 0 else None),
        }

    @staticmethod
    def _baseline_promotion_simulation_custody_normalize_temporary_hold(
        raw_hold: dict[str, Any] | None,
        *,
        default_ttl_s: int = 0,
        now_ts: float | None = None,
        index: int = 1,
    ) -> dict[str, Any]:
        payload = dict(raw_hold or {})
        try:
            hold_capacity = int(payload.get('capacity') or payload.get('hold_capacity') or payload.get('reserved_capacity') or 0)
        except Exception:
            hold_capacity = 0
        hold_created_at = payload.get('created_at')
        hold_expires_at = payload.get('expires_at') or payload.get('hold_expires_at') or payload.get('until')
        try:
            hold_created_at_value = float(hold_created_at) if hold_created_at is not None else None
        except Exception:
            hold_created_at_value = None
        try:
            hold_expires_at_value = float(hold_expires_at) if hold_expires_at is not None else None
        except Exception:
            hold_expires_at_value = None
        if hold_expires_at_value is None and default_ttl_s > 0:
            base_ts = hold_created_at_value if hold_created_at_value is not None else float(now_ts if now_ts is not None else time.time())
            hold_expires_at_value = float(base_ts + max(0, int(default_ttl_s or 0)))
        queue_types = [
            str(item).strip()
            for item in list(payload.get('for_queue_types') or payload.get('queue_types') or payload.get('eligible_queue_types') or [])
            if str(item).strip()
        ]
        severities = [
            str(item).strip().lower()
            for item in list(payload.get('for_severities') or payload.get('severities') or payload.get('eligible_severities') or [])
            if str(item).strip()
        ]
        active = bool(max(0, hold_capacity) > 0 and (hold_expires_at_value is None or hold_expires_at_value > float(now_ts if now_ts is not None else time.time())))
        return {
            'hold_id': str(payload.get('hold_id') or payload.get('id') or f'temporary-hold-{index}').strip() or f'temporary-hold-{index}',
            'label': str(payload.get('label') or payload.get('name') or f'Temporary hold {index}').strip() or f'Temporary hold {index}',
            'capacity': max(0, int(hold_capacity or 0)),
            'reason': str(payload.get('reason') or payload.get('hold_reason') or '').strip(),
            'holder': str(payload.get('holder') or payload.get('owner') or '').strip(),
            'created_at': hold_created_at_value,
            'expires_at': hold_expires_at_value,
            'for_queue_types': queue_types,
            'for_severities': severities,
            'active': active,
            'expired': bool(max(0, hold_capacity) > 0 and hold_expires_at_value is not None and hold_expires_at_value <= float(now_ts if now_ts is not None else time.time())),
        }


    def _baseline_promotion_simulation_custody_queue_capacity_state(
        self,
        gw,
        *,
        release: dict[str, Any] | None = None,
        policy: dict[str, Any] | None = None,
        exclude_alert_id: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        normalized_policy = self._normalize_baseline_promotion_simulation_custody_monitoring_policy(
            dict(policy or self._baseline_promotion_simulation_custody_monitoring_policy_for_release(release))
        )
        scope_tenant = tenant_id if tenant_id is not None else (release or {}).get('tenant_id')
        scope_workspace = workspace_id if workspace_id is not None else (release or {}).get('workspace_id')
        scope_environment = environment if environment is not None else (release or {}).get('environment')
        queue_capacity_policy = dict(normalized_policy.get('queue_capacity_policy') or {})
        default_capacity = max(0, int(queue_capacity_policy.get('default_capacity') or 0))
        default_warning = max(0, int(queue_capacity_policy.get('warning_capacity') or max(0, default_capacity - 1)))
        aging_enabled = bool(queue_capacity_policy.get('aging_enabled'))
        aging_after_s = max(0, int(queue_capacity_policy.get('aging_after_s') or 0))
        starvation_prevention_enabled = bool(queue_capacity_policy.get('starvation_prevention_enabled'))
        starvation_after_s = max(0, int(queue_capacity_policy.get('starvation_after_s') or 0))
        reservation_lease_enabled = bool(queue_capacity_policy.get('reservation_lease_enabled'))
        lease_reclaim_enabled = bool(queue_capacity_policy.get('lease_reclaim_enabled', True))
        temporary_holds_enabled = bool(queue_capacity_policy.get('temporary_holds_enabled'))
        default_leased_capacity = max(0, int(queue_capacity_policy.get('default_leased_capacity') or 0))
        default_lease_ttl_s = max(0, int(queue_capacity_policy.get('default_lease_ttl_s') or 0))
        default_hold_ttl_s = max(0, int(queue_capacity_policy.get('default_hold_ttl_s') or 0))
        now_ts = time.time()
        queues: dict[str, dict[str, Any]] = {}

        def _ensure_queue(queue_id: str, **updates: Any) -> dict[str, Any]:
            normalized_queue_id = str(queue_id or '').strip()
            if not normalized_queue_id:
                return {}
            item = queues.setdefault(normalized_queue_id, {
                'queue_id': normalized_queue_id,
                'queue_label': '',
                'capacity': 0,
                'warning_capacity': 0,
                'hard_limit': False,
                'queue_type': '',
                'owner_role': '',
                'owner_id': '',
                'queue_family_id': '',
                'queue_family_label': '',
                'load_weight': 1.0,
                'reserved_capacity': 0,
                'reservation_enabled': False,
                'reserved_for_queue_types': [],
                'reserved_for_severities': [],
                'leased_capacity': 0,
                'lease_expires_at': None,
                'lease_reason': '',
                'lease_holder': '',
                'lease_id': '',
                'leased_for_queue_types': [],
                'leased_for_severities': [],
                'temporary_holds': [],
                'active_count': 0,
                'active_alert_ids': [],
                'promotion_ids': [],
                'sla_rerouted_count': 0,
                'source_count': 0,
                'oldest_alert_age_s': 0,
                'newest_alert_age_s': 0,
                'aged_alert_count': 0,
                'starving_alert_count': 0,
                'expected_service_time_s': max(60, int(queue_capacity_policy.get('expected_service_time_s') or 300)),
                'forecast_arrivals': 0,
                'forecast_arrivals_per_hour': 0.0,
                'forecast_window_s': max(300, int(queue_capacity_policy.get('forecast_window_s') or 1800)),
                'admission_control_enabled': bool(queue_capacity_policy.get('admission_control_enabled')),
                'admission_action': str(queue_capacity_policy.get('admission_default_action') or ''),
                'admission_exempt_severities': list(queue_capacity_policy.get('admission_exempt_severities') or []),
                'admission_exempt_queue_types': list(queue_capacity_policy.get('admission_exempt_queue_types') or []),
                'overload_governance_enabled': bool(queue_capacity_policy.get('overload_governance_enabled')),
                'overload_projected_load_ratio_threshold': float(queue_capacity_policy.get('overload_projected_load_ratio_threshold') or 0.0),
                'overload_projected_wait_time_threshold_s': int(queue_capacity_policy.get('overload_projected_wait_time_threshold_s') or 0),
                'overload_action': str(queue_capacity_policy.get('overload_global_action') or queue_capacity_policy.get('admission_default_action') or ''),
            })
            for key, value in updates.items():
                if key in {'capacity', 'warning_capacity'}:
                    try:
                        numeric = int(value) if value is not None else 0
                    except Exception:
                        numeric = 0
                    item[key] = max(int(item.get(key) or 0), max(0, numeric))
                elif key == 'hard_limit':
                    item['hard_limit'] = bool(item.get('hard_limit')) or bool(value)
                elif key == 'load_weight':
                    try:
                        numeric = float(value) if value is not None else 1.0
                    except Exception:
                        numeric = 1.0
                    item['load_weight'] = max(0.1, float(item.get('load_weight') or 1.0), max(0.1, numeric))
                elif key == 'source_count':
                    item['source_count'] = int(item.get('source_count') or 0) + int(value or 0)
                elif key == 'reserved_capacity':
                    try:
                        numeric = int(value) if value is not None else 0
                    except Exception:
                        numeric = 0
                    item['reserved_capacity'] = max(int(item.get('reserved_capacity') or 0), max(0, numeric))
                    if int(item.get('reserved_capacity') or 0) > 0:
                        item['reservation_enabled'] = True
                elif key == 'leased_capacity':
                    try:
                        numeric = int(value) if value is not None else 0
                    except Exception:
                        numeric = 0
                    item['leased_capacity'] = max(int(item.get('leased_capacity') or 0), max(0, numeric))
                elif key == 'lease_expires_at':
                    try:
                        candidate = float(value) if value is not None else None
                    except Exception:
                        candidate = None
                    existing = item.get('lease_expires_at')
                    item['lease_expires_at'] = candidate if existing in {None, ''} else (max(float(existing), candidate) if candidate is not None else existing)
                elif key == 'expected_service_time_s':
                    try:
                        numeric = int(value) if value is not None else int(queue_capacity_policy.get('expected_service_time_s') or 300)
                    except Exception:
                        numeric = int(queue_capacity_policy.get('expected_service_time_s') or 300)
                    item['expected_service_time_s'] = max(60, int(numeric or 300))
                elif key == 'forecast_arrivals':
                    try:
                        numeric = int(value) if value is not None else 0
                    except Exception:
                        numeric = 0
                    item['forecast_arrivals'] = max(int(item.get('forecast_arrivals') or 0), max(0, numeric))
                elif key == 'forecast_arrivals_per_hour':
                    try:
                        numeric = float(value) if value is not None else 0.0
                    except Exception:
                        numeric = 0.0
                    item['forecast_arrivals_per_hour'] = max(float(item.get('forecast_arrivals_per_hour') or 0.0), max(0.0, numeric))
                elif key == 'forecast_window_s':
                    try:
                        numeric = int(value) if value is not None else int(queue_capacity_policy.get('forecast_window_s') or 1800)
                    except Exception:
                        numeric = int(queue_capacity_policy.get('forecast_window_s') or 1800)
                    item['forecast_window_s'] = max(300, int(numeric or 1800))
                elif key == 'reservation_enabled':
                    item['reservation_enabled'] = bool(item.get('reservation_enabled')) or bool(value)
                elif key in {'reserved_for_queue_types', 'reserved_for_severities', 'leased_for_queue_types', 'leased_for_severities', 'admission_exempt_queue_types', 'admission_exempt_severities'}:
                    lower_keys = {'reserved_for_severities', 'leased_for_severities', 'admission_exempt_severities'}
                    existing = [str(v).strip().lower() if key in lower_keys else str(v).strip() for v in list(item.get(key) or []) if str(v).strip()]
                    incoming = [str(v).strip().lower() if key in lower_keys else str(v).strip() for v in list(value or []) if str(v).strip()]
                    item[key] = list(dict.fromkeys(existing + incoming))
                elif key in {'queue_family_id', 'queue_family_label'}:
                    candidate = str(value or '').strip()
                    if candidate:
                        existing = str(item.get(key) or '').strip()
                        item[key] = existing or candidate
                elif key in {'admission_control_enabled', 'overload_governance_enabled'}:
                    item[key] = bool(item.get(key)) or bool(value)
                elif key in {'overload_projected_load_ratio_threshold'}:
                    try:
                        numeric = float(value) if value is not None else 0.0
                    except Exception:
                        numeric = 0.0
                    item[key] = max(float(item.get(key) or 0.0), max(0.0, numeric))
                elif key in {'overload_projected_wait_time_threshold_s'}:
                    try:
                        numeric = int(value) if value is not None else 0
                    except Exception:
                        numeric = 0
                    item[key] = max(int(item.get(key) or 0), max(0, numeric))
                elif key == 'temporary_holds':
                    existing = [dict(v or {}) for v in list(item.get('temporary_holds') or []) if isinstance(v, dict)]
                    incoming = [dict(v or {}) for v in list(value or []) if isinstance(v, dict)]
                    merged = {str(v.get('hold_id') or ''): v for v in existing if str(v.get('hold_id') or '')}
                    for hold in incoming:
                        hold_id = str(hold.get('hold_id') or '')
                        if hold_id:
                            merged[hold_id] = hold
                        else:
                            existing.append(hold)
                    item['temporary_holds'] = list(merged.values()) + [hold for hold in existing if not str(hold.get('hold_id') or '')]
                elif value and not item.get(key):
                    item[key] = value
            return item

        def _register_route(raw_route: dict[str, Any] | None) -> None:
            route = self._normalize_baseline_promotion_simulation_custody_route(dict(raw_route or {}), index=0, fallback_target_path=str(normalized_policy.get('target_path') or '/ui/?tab=operator'))
            queue_id = str(route.get('queue_id') or '').strip()
            if not queue_id:
                return
            _ensure_queue(
                queue_id,
                queue_label=str(route.get('queue_label') or queue_id),
                capacity=int(route.get('queue_capacity') or 0),
                hard_limit=bool(route.get('queue_hard_limit')),
                queue_type=str(route.get('queue_type') or ''),
                owner_role=str(route.get('owner_role') or ''),
                owner_id=str(route.get('owner_id') or ''),
                queue_family_id=str(route.get('queue_family_id') or route.get('queue_type') or ''),
                queue_family_label=str(route.get('queue_family_label') or route.get('queue_family_id') or route.get('queue_type') or ''),
                load_weight=float(route.get('load_weight') or 1.0),
                source_count=1,
            )

        def _register_policy(raw_policy: dict[str, Any] | None) -> None:
            candidate = self._normalize_baseline_promotion_simulation_custody_monitoring_policy(dict(raw_policy or {}))
            _register_route(candidate.get('default_route') or {})
            for route in list(candidate.get('routing_routes') or []):
                _register_route(route)
            for route in list(candidate.get('team_escalation_queues') or []):
                _register_route(route)
            _register_route(candidate.get('sla_breach_route') or {})
            for queue_payload in list(candidate.get('queue_capacities') or []):
                queue_data = dict(queue_payload or {})
                queue_id = str(queue_data.get('queue_id') or '').strip()
                if not queue_id:
                    continue
                _ensure_queue(
                    queue_id,
                    queue_label=str(queue_data.get('queue_label') or queue_id),
                    capacity=int(queue_data.get('capacity') or 0),
                    warning_capacity=int(queue_data.get('warning_capacity') or 0),
                    hard_limit=bool(queue_data.get('hard_limit')),
                    queue_type=str(queue_data.get('queue_type') or ''),
                    owner_role=str(queue_data.get('owner_role') or ''),
                    owner_id=str(queue_data.get('owner_id') or ''),
                    queue_family_id=str(queue_data.get('queue_family_id') or queue_data.get('family_id') or queue_data.get('family') or queue_data.get('queue_type') or ''),
                    queue_family_label=str(queue_data.get('queue_family_label') or queue_data.get('family_label') or queue_data.get('queue_family_id') or queue_data.get('family_id') or queue_data.get('family') or queue_data.get('queue_type') or ''),
                    load_weight=float(queue_data.get('load_weight') or 1.0),
                    reserved_capacity=int(queue_data.get('reserved_capacity') or 0),
                    reservation_enabled=bool(queue_data.get('reserved_capacity') or queue_data.get('reservation_enabled')),
                    reserved_for_queue_types=list(queue_data.get('reserved_for_queue_types') or []),
                    reserved_for_severities=list(queue_data.get('reserved_for_severities') or []),
                    leased_capacity=int(queue_data.get('leased_capacity') or 0),
                    lease_expires_at=queue_data.get('lease_expires_at'),
                    lease_reason=str(queue_data.get('lease_reason') or ''),
                    lease_holder=str(queue_data.get('lease_holder') or ''),
                    lease_id=str(queue_data.get('lease_id') or ''),
                    leased_for_queue_types=list(queue_data.get('leased_for_queue_types') or []),
                    leased_for_severities=list(queue_data.get('leased_for_severities') or []),
                    temporary_holds=list(queue_data.get('temporary_holds') or []),
                    expected_service_time_s=int(queue_data.get('expected_service_time_s') or queue_data.get('service_time_s') or queue_capacity_policy.get('expected_service_time_s') or 300),
                    forecast_arrivals=queue_data.get('forecast_arrivals'),
                    forecast_arrivals_per_hour=queue_data.get('forecast_arrivals_per_hour'),
                    forecast_window_s=queue_data.get('forecast_window_s') or queue_capacity_policy.get('forecast_window_s'),
                    admission_control_enabled=bool(queue_data.get('admission_control_enabled', queue_capacity_policy.get('admission_control_enabled'))),
                    admission_action=str(queue_data.get('admission_action') or queue_data.get('overload_action') or queue_capacity_policy.get('admission_default_action') or ''),
                    admission_exempt_severities=list(queue_data.get('admission_exempt_severities') or []),
                    admission_exempt_queue_types=list(queue_data.get('admission_exempt_queue_types') or []),
                    overload_governance_enabled=bool(queue_data.get('overload_governance_enabled', queue_capacity_policy.get('overload_governance_enabled'))),
                    overload_projected_load_ratio_threshold=queue_data.get('overload_projected_load_ratio_threshold') or queue_capacity_policy.get('overload_projected_load_ratio_threshold'),
                    overload_projected_wait_time_threshold_s=queue_data.get('overload_projected_wait_time_threshold_s') or queue_capacity_policy.get('overload_projected_wait_time_threshold_s'),
                    overload_action=str(queue_data.get('overload_action') or queue_data.get('admission_action') or queue_capacity_policy.get('overload_global_action') or queue_capacity_policy.get('admission_default_action') or ''),
                    source_count=1,
                )

        _register_policy(normalized_policy)
        releases = list(gw.audit.list_release_bundles(
            limit=500,
            kind='policy_baseline_promotion',
            tenant_id=scope_tenant,
            workspace_id=scope_workspace,
            environment=scope_environment,
        ) or [])
        for candidate_release in releases:
            if not self._is_baseline_promotion_release(candidate_release):
                continue
            candidate_policy = self._baseline_promotion_simulation_custody_monitoring_policy_for_release(candidate_release)
            _register_policy(candidate_policy)
            alerts = self._baseline_promotion_simulation_custody_alerts(candidate_release)
            active_alert = next((item for item in alerts if bool(item.get('active'))), None)
            if not active_alert:
                continue
            if exclude_alert_id and str(active_alert.get('alert_id') or '') == str(exclude_alert_id or ''):
                continue
            ownership = self._baseline_promotion_simulation_custody_ownership_projection(active_alert)
            routing = self._baseline_promotion_simulation_custody_routing_projection(active_alert)
            queue_id = str(ownership.get('queue_id') or routing.get('queue_id') or '').strip()
            if not queue_id:
                continue
            item = _ensure_queue(
                queue_id,
                queue_label=str(ownership.get('queue_label') or routing.get('queue_label') or queue_id),
                owner_role=str(ownership.get('owner_role') or routing.get('owner_role') or ''),
                owner_id=str(routing.get('owner_id') or ''),
                queue_family_id=str(routing.get('queue_family_id') or routing.get('queue_type') or ''),
                queue_family_label=str(routing.get('queue_family_label') or routing.get('queue_family_id') or routing.get('queue_type') or ''),
            )
            item['active_count'] = int(item.get('active_count') or 0) + 1
            item['active_alert_ids'] = list(item.get('active_alert_ids') or []) + [str(active_alert.get('alert_id') or '')]
            item['promotion_ids'] = list(item.get('promotion_ids') or []) + [str(candidate_release.get('release_id') or '')]
            alert_created_at = None
            try:
                alert_created_at = float(active_alert.get('created_at')) if active_alert.get('created_at') is not None else None
            except Exception:
                alert_created_at = None
            queue_assigned_at = None
            try:
                queue_assigned_at = float(routing.get('updated_at')) if routing.get('updated_at') is not None else None
            except Exception:
                queue_assigned_at = None
            queue_age_s = max(0, int(now_ts - (queue_assigned_at if queue_assigned_at is not None else (alert_created_at if alert_created_at is not None else now_ts))))
            previous_oldest_age = int(item.get('oldest_alert_age_s') or 0)
            item['oldest_alert_age_s'] = max(previous_oldest_age, queue_age_s)
            if int(item.get('newest_alert_age_s') or 0) <= 0:
                item['newest_alert_age_s'] = queue_age_s
            else:
                item['newest_alert_age_s'] = min(int(item.get('newest_alert_age_s') or 0), queue_age_s)
            if aging_enabled and aging_after_s > 0 and queue_age_s >= aging_after_s:
                item['aged_alert_count'] = int(item.get('aged_alert_count') or 0) + 1
            if starvation_prevention_enabled and starvation_after_s > 0 and queue_age_s >= starvation_after_s:
                item['starving_alert_count'] = int(item.get('starving_alert_count') or 0) + 1
            if str(routing.get('source') or '') == 'sla_breach_routing':
                item['sla_rerouted_count'] = int(item.get('sla_rerouted_count') or 0) + 1
        queue_items = []
        saturated_count = 0
        over_capacity_count = 0
        total_active = 0
        aged_alert_count = 0
        starving_alert_count = 0
        starving_queue_count = 0
        oldest_alert_age_s = 0
        leased_queue_count = 0
        active_leased_capacity = 0
        expired_lease_count = 0
        hold_queue_count = 0
        active_temporary_hold_count = 0
        active_temporary_hold_capacity = 0
        expired_hold_count = 0
        forecasted_surge_queue_count = 0
        overloaded_queue_count = 0
        admission_blocked_queue_count = 0
        hottest_projected_load_ratio = 0.0
        hottest_projected_queue_id = ''
        hottest_projected_queue_label = ''
        queue_family_ids: set[str] = set()
        family_queue_counts: dict[str, int] = {}
        largest_queue_family_id = ''
        largest_queue_family_label = ''
        largest_queue_family_size = 0
        policy_reserved_capacity = max(0, int(queue_capacity_policy.get('default_reserved_capacity') or 0))
        policy_reservation_enabled = bool(queue_capacity_policy.get('reservation_enabled'))
        policy_reserved_for_queue_types = [str(item).strip() for item in list(queue_capacity_policy.get('reserved_for_queue_types') or []) if str(item).strip()]
        policy_reserved_for_severities = [str(item).strip().lower() for item in list(queue_capacity_policy.get('reserved_for_severities') or []) if str(item).strip()]
        for queue_id, item in queues.items():
            capacity = max(0, int(item.get('capacity') or default_capacity or 0))
            warning_capacity = max(0, int(item.get('warning_capacity') or default_warning or (capacity - 1 if capacity > 0 else 0)))
            active_count = int(item.get('active_count') or 0)
            configured_reserved_capacity = int(item.get('reserved_capacity') or 0)
            reservation_enabled = bool(item.get('reservation_enabled')) or bool(policy_reservation_enabled and configured_reserved_capacity <= 0 and policy_reserved_capacity > 0)
            reserved_capacity = max(0, min(capacity, configured_reserved_capacity or (policy_reserved_capacity if reservation_enabled else 0)))
            raw_lease_expires_at = item.get('lease_expires_at')
            try:
                lease_expires_at = float(raw_lease_expires_at) if raw_lease_expires_at is not None else None
            except Exception:
                lease_expires_at = None
            lease_expired = bool((int(item.get('leased_capacity') or default_leased_capacity or 0) > 0) and lease_expires_at is not None and lease_expires_at <= now_ts)
            lease_active = bool(reservation_lease_enabled and (int(item.get('leased_capacity') or default_leased_capacity or 0) > 0) and (lease_expires_at is None or lease_expires_at > now_ts))
            leased_capacity = max(0, min(capacity, int(item.get('leased_capacity') or (default_leased_capacity if lease_active else 0) or 0))) if lease_active else 0
            normalized_holds = [
                self._baseline_promotion_simulation_custody_normalize_temporary_hold(dict(hold or {}), default_ttl_s=default_hold_ttl_s, now_ts=now_ts, index=index + 1)
                for index, hold in enumerate(list(item.get('temporary_holds') or []))
                if isinstance(hold, dict)
            ]
            active_holds = [hold for hold in normalized_holds if bool(hold.get('active'))]
            expired_holds = [hold for hold in normalized_holds if bool(hold.get('expired'))]
            hold_capacity = max(0, sum(int(hold.get('capacity') or 0) for hold in active_holds)) if temporary_holds_enabled else 0
            general_capacity = max(0, capacity - reserved_capacity - leased_capacity - hold_capacity)
            tier_state = self._baseline_promotion_simulation_custody_capacity_tier_state(
                active_count=active_count,
                capacity=capacity,
                general_capacity=general_capacity,
                reserved_capacity=reserved_capacity,
                leased_capacity=leased_capacity,
                hold_capacity=hold_capacity,
            )
            general_available = tier_state.get('general_available')
            reserved_available = tier_state.get('reserved_available')
            lease_available = tier_state.get('lease_available')
            hold_available = tier_state.get('hold_available')
            available = (max(0, capacity - active_count) if capacity > 0 else None)
            load_ratio = (float(active_count) / float(capacity) if capacity > 0 else 0.0)
            at_capacity = bool(capacity > 0 and active_count >= capacity)
            over_capacity = bool(capacity > 0 and active_count > capacity)
            warning = bool(capacity > 0 and active_count >= max(1, warning_capacity))
            oldest_queue_age_s = max(0, int(item.get('oldest_alert_age_s') or 0))
            queue_aged_alert_count = int(item.get('aged_alert_count') or 0)
            queue_starving_alert_count = int(item.get('starving_alert_count') or 0)
            queue_forecast_window_s = max(300, int(item.get('forecast_window_s') or queue_capacity_policy.get('forecast_window_s') or 1800))
            forecast_arrivals_count = max(0, int(item.get('forecast_arrivals') or 0))
            try:
                forecast_arrivals_per_hour = max(0.0, float(item.get('forecast_arrivals_per_hour') or 0.0))
            except Exception:
                forecast_arrivals_per_hour = 0.0
            if forecast_arrivals_count <= 0 and forecast_arrivals_per_hour > 0.0:
                forecast_arrivals_count = max(0, int(round(forecast_arrivals_per_hour * (float(queue_forecast_window_s) / 3600.0))))
            forecast_service_capacity = max(0, int((float(max(capacity, 0)) * float(queue_forecast_window_s)) / float(max(60, int(item.get('expected_service_time_s') or queue_capacity_policy.get('expected_service_time_s') or 300))))) if capacity > 0 else 0
            projected_active_count = max(0, int(active_count + forecast_arrivals_count - forecast_service_capacity))
            projected_load_ratio = (float(projected_active_count) / float(capacity) if capacity > 0 else 0.0)
            projected_wait_time_s = int(round((float(max(projected_active_count, 0)) * float(max(60, int(item.get('expected_service_time_s') or queue_capacity_policy.get('expected_service_time_s') or 300)))) / float(max(capacity, 1)))) if capacity > 0 else 0
            forecasted_over_capacity = bool(capacity > 0 and projected_active_count > capacity)
            surge_predicted = bool(queue_capacity_policy.get('predictive_forecasting_enabled') and (forecasted_over_capacity or projected_load_ratio >= float(queue_capacity_policy.get('surge_load_ratio_threshold') or 0.85)))
            overload_projected_load_ratio_threshold = max(0.25, float(item.get('overload_projected_load_ratio_threshold') or queue_capacity_policy.get('overload_projected_load_ratio_threshold') or queue_capacity_policy.get('surge_load_ratio_threshold') or 0.95))
            overload_projected_wait_time_threshold_s = max(0, int(item.get('overload_projected_wait_time_threshold_s') or queue_capacity_policy.get('overload_projected_wait_time_threshold_s') or max(300, int(item.get('expected_service_time_s') or queue_capacity_policy.get('expected_service_time_s') or 300) * 2)))
            overload_predicted = bool(
                (capacity > 0 and active_count >= capacity and bool(item.get('hard_limit')))
                or forecasted_over_capacity
                or projected_load_ratio >= overload_projected_load_ratio_threshold
                or (overload_projected_wait_time_threshold_s > 0 and projected_wait_time_s >= overload_projected_wait_time_threshold_s)
            )
            admission_control_enabled = bool(item.get('admission_control_enabled', queue_capacity_policy.get('admission_control_enabled')))
            overload_governance_enabled = bool(item.get('overload_governance_enabled', queue_capacity_policy.get('overload_governance_enabled')))
            admission_action = str(item.get('admission_action') or queue_capacity_policy.get('admission_default_action') or 'defer').strip() or 'defer'
            overload_action = str(item.get('overload_action') or admission_action or queue_capacity_policy.get('overload_global_action') or 'defer').strip() or 'defer'
            queue_family_id = str(item.get('queue_family_id') or queue_capacity_policy.get('default_queue_family') or item.get('queue_type') or '').strip()
            queue_family_label = str(item.get('queue_family_label') or queue_family_id or item.get('queue_label') or item.get('queue_type') or '').strip()
            record = {
                **item,
                'capacity': capacity,
                'warning_capacity': warning_capacity,
                'queue_family_id': queue_family_id,
                'queue_family_label': queue_family_label,
                'queue_family_enabled': bool(queue_capacity_policy.get('queue_families_enabled')),
                'active_count': active_count,
                'available': available,
                'load_ratio': load_ratio,
                'warning': warning,
                'at_capacity': at_capacity,
                'over_capacity': over_capacity,
                'reservation_enabled': reservation_enabled,
                'reserved_capacity': reserved_capacity,
                'general_capacity': general_capacity,
                'general_available': general_available,
                'reserved_available': reserved_available,
                'lease_active': lease_active,
                'lease_expired': lease_expired,
                'leased_capacity': leased_capacity,
                'lease_available': lease_available,
                'lease_expires_at': lease_expires_at,
                'lease_reason': str(item.get('lease_reason') or ''),
                'lease_holder': str(item.get('lease_holder') or ''),
                'lease_id': str(item.get('lease_id') or ''),
                'leased_for_queue_types': list(item.get('leased_for_queue_types') or []),
                'leased_for_severities': list(item.get('leased_for_severities') or []),
                'temporary_hold_count': len(active_holds),
                'temporary_hold_capacity': hold_capacity,
                'temporary_hold_available': hold_available,
                'temporary_hold_ids': [str(hold.get('hold_id') or '') for hold in active_holds if str(hold.get('hold_id') or '')],
                'temporary_hold_reasons': [str(hold.get('reason') or '') for hold in active_holds if str(hold.get('reason') or '')],
                'temporary_holds': active_holds,
                'expired_temporary_hold_count': len(expired_holds),
                'expired_temporary_hold_ids': [str(hold.get('hold_id') or '') for hold in expired_holds if str(hold.get('hold_id') or '')],
                'reserved_for_queue_types': list(item.get('reserved_for_queue_types') or policy_reserved_for_queue_types),
                'reserved_for_severities': list(item.get('reserved_for_severities') or policy_reserved_for_severities),
                'expected_service_time_s': max(60, int(item.get('expected_service_time_s') or queue_capacity_policy.get('expected_service_time_s') or 300)),
                'promotion_ids': sorted({str(x) for x in list(item.get('promotion_ids') or []) if str(x)}),
                'active_alert_ids': sorted({str(x) for x in list(item.get('active_alert_ids') or []) if str(x)}),
                'oldest_alert_age_s': oldest_queue_age_s,
                'newest_alert_age_s': max(0, int(item.get('newest_alert_age_s') or 0)),
                'aged_alert_count': queue_aged_alert_count,
                'starving_alert_count': queue_starving_alert_count,
                'aging_enabled': aging_enabled,
                'starvation_prevention_enabled': starvation_prevention_enabled,
                'starving': bool(queue_starving_alert_count > 0),
                'forecast_window_s': queue_forecast_window_s,
                'forecast_arrivals_count': forecast_arrivals_count,
                'forecast_arrivals_per_hour': forecast_arrivals_per_hour,
                'forecast_service_capacity': forecast_service_capacity,
                'projected_active_count': projected_active_count,
                'projected_load_ratio': projected_load_ratio,
                'projected_wait_time_s': projected_wait_time_s,
                'forecasted_over_capacity': forecasted_over_capacity,
                'surge_predicted': surge_predicted,
                'admission_control_enabled': admission_control_enabled,
                'admission_action': admission_action,
                'admission_exempt_severities': list(item.get('admission_exempt_severities') or queue_capacity_policy.get('admission_exempt_severities') or []),
                'admission_exempt_queue_types': list(item.get('admission_exempt_queue_types') or queue_capacity_policy.get('admission_exempt_queue_types') or []),
                'overload_governance_enabled': overload_governance_enabled,
                'overload_action': overload_action,
                'overload_projected_load_ratio_threshold': overload_projected_load_ratio_threshold,
                'overload_projected_wait_time_threshold_s': overload_projected_wait_time_threshold_s,
                'overload_predicted': overload_predicted,
                'admission_blocked': bool(admission_control_enabled and overload_governance_enabled and overload_predicted and overload_action in {'defer', 'manual_gate', 'park', 'reject'}),
            }
            if queue_family_id:
                queue_family_ids.add(queue_family_id)
                family_queue_counts[queue_family_id] = family_queue_counts.get(queue_family_id, 0) + 1
                if family_queue_counts[queue_family_id] >= largest_queue_family_size:
                    largest_queue_family_size = family_queue_counts[queue_family_id]
                    largest_queue_family_id = queue_family_id
                    largest_queue_family_label = queue_family_label or queue_family_id
            if at_capacity:
                saturated_count += 1
            if over_capacity:
                over_capacity_count += 1
            if queue_starving_alert_count > 0:
                starving_queue_count += 1
            if surge_predicted:
                forecasted_surge_queue_count += 1
            if overload_predicted:
                overloaded_queue_count += 1
            if bool(record.get('admission_blocked')):
                admission_blocked_queue_count += 1
            if projected_load_ratio >= hottest_projected_load_ratio:
                hottest_projected_load_ratio = projected_load_ratio
                hottest_projected_queue_id = str(record.get('queue_id') or '')
                hottest_projected_queue_label = str(record.get('queue_label') or '')
            if lease_active:
                leased_queue_count += 1
                active_leased_capacity += leased_capacity
            if lease_expired and lease_reclaim_enabled:
                expired_lease_count += 1
            if active_holds:
                hold_queue_count += 1
                active_temporary_hold_count += len(active_holds)
                active_temporary_hold_capacity += hold_capacity
            expired_hold_count += len(expired_holds)
            aged_alert_count += queue_aged_alert_count
            starving_alert_count += queue_starving_alert_count
            oldest_alert_age_s = max(oldest_alert_age_s, oldest_queue_age_s)
            total_active += active_count
            queue_items.append(record)
        queue_items.sort(key=lambda item: (bool(item.get('at_capacity')), float(item.get('load_ratio') or 0.0), int(item.get('active_count') or 0), str(item.get('queue_id') or '')), reverse=True)
        hottest = dict(queue_items[0] or {}) if queue_items else {}
        return {
            'policy': queue_capacity_policy,
            'queues': {str(item.get('queue_id') or ''): item for item in queue_items},
            'items': queue_items,
            'summary': {
                'queue_count': len(queue_items),
                'active_alert_count': total_active,
                'saturated_count': saturated_count,
                'over_capacity_count': over_capacity_count,
                'aged_alert_count': aged_alert_count,
                'starving_alert_count': starving_alert_count,
                'starving_queue_count': starving_queue_count,
                'leased_queue_count': leased_queue_count,
                'active_leased_capacity': active_leased_capacity,
                'expired_lease_count': expired_lease_count,
                'hold_queue_count': hold_queue_count,
                'active_temporary_hold_count': active_temporary_hold_count,
                'active_temporary_hold_capacity': active_temporary_hold_capacity,
                'expired_hold_count': expired_hold_count,
                'forecasted_surge_queue_count': forecasted_surge_queue_count,
                'overloaded_queue_count': overloaded_queue_count,
                'admission_blocked_queue_count': admission_blocked_queue_count,
                'forecast_window_s': max(300, int(queue_capacity_policy.get('forecast_window_s') or 1800)),
                'queue_family_count': len(queue_family_ids),
                'family_queue_counts': dict(family_queue_counts),
                'largest_queue_family_id': largest_queue_family_id,
                'largest_queue_family_label': largest_queue_family_label,
                'largest_queue_family_size': largest_queue_family_size,
                'hottest_projected_queue_id': hottest_projected_queue_id,
                'hottest_projected_queue_label': hottest_projected_queue_label,
                'hottest_projected_load_ratio': float(hottest_projected_load_ratio or 0.0),
                'oldest_alert_age_s': oldest_alert_age_s,
                'hottest_queue_id': str(hottest.get('queue_id') or ''),
                'hottest_queue_label': str(hottest.get('queue_label') or ''),
                'hottest_load_ratio': float(hottest.get('load_ratio') or 0.0),
            },
        }

    def _select_baseline_promotion_simulation_custody_route_by_load(
        self,
        *,
        routes: list[dict[str, Any]],
        queue_state: dict[str, Any] | None,
        current_queue_id: str | None = None,
        prefer_lowest_load: bool = True,
        alert: dict[str, Any] | None = None,
        policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        candidates = []
        for index, item in enumerate(list(routes or [])):
            normalized = self._normalize_baseline_promotion_simulation_custody_route(dict(item or {}), index=index + 1)
            normalized['_route_index'] = index
            candidates.append(normalized)
        if not candidates:
            return {}
        queues = dict((queue_state or {}).get('queues') or {})
        normalized_current_queue_id = str(current_queue_id or '').strip() or str((((alert or {}).get('routing') or {}).get('queue_id') or '')).strip()
        normalized_policy = self._normalize_baseline_promotion_simulation_custody_monitoring_policy(dict(policy or {})) if policy is not None else {}
        queue_policy = dict(((queue_state or {}).get('policy')) or normalized_policy.get('queue_capacity_policy') or {})
        anti_thrashing_enabled = bool(queue_policy.get('anti_thrashing_enabled'))
        reroute_cooldown_s = max(0, int(queue_policy.get('reroute_cooldown_s') or 0))
        min_active_delta = max(0, int(queue_policy.get('anti_thrashing_min_active_delta') or 0))
        min_load_delta = max(0.0, float(queue_policy.get('anti_thrashing_min_load_delta') or 0.0))
        aging_enabled = bool(queue_policy.get('aging_enabled'))
        aging_after_s = max(0, int(queue_policy.get('aging_after_s') or 0))
        starvation_prevention_enabled = bool(queue_policy.get('starvation_prevention_enabled'))
        starvation_after_s = max(0, int(queue_policy.get('starvation_after_s') or 0))
        starvation_reserved_capacity_borrow_enabled = bool(queue_policy.get('starvation_reserved_capacity_borrow_enabled'))
        starvation_bypass_anti_thrashing = bool(queue_policy.get('starvation_bypass_anti_thrashing'))
        starvation_lease_capacity_borrow_enabled = bool(queue_policy.get('starvation_lease_capacity_borrow_enabled'))
        starvation_hold_capacity_borrow_enabled = bool(queue_policy.get('starvation_hold_capacity_borrow_enabled'))
        breach_prediction_enabled = bool(queue_policy.get('breach_prediction_enabled'))
        default_service_time_s = max(60, int(queue_policy.get('expected_service_time_s') or 300))
        expedite_enabled = bool(queue_policy.get('expedite_enabled'))
        expedite_threshold_s = max(0, int(queue_policy.get('expedite_threshold_s') or 0))
        expedite_min_risk_score = max(0.0, float(queue_policy.get('expedite_min_risk_score') or 0.0))
        expedite_reserved_capacity_borrow_enabled = bool(queue_policy.get('expedite_reserved_capacity_borrow_enabled'))
        expedite_lease_capacity_borrow_enabled = bool(queue_policy.get('expedite_lease_capacity_borrow_enabled'))
        expedite_hold_capacity_borrow_enabled = bool(queue_policy.get('expedite_hold_capacity_borrow_enabled'))
        expedite_bypass_anti_thrashing = bool(queue_policy.get('expedite_bypass_anti_thrashing'))
        predictive_forecasting_enabled = bool(queue_policy.get('predictive_forecasting_enabled'))
        forecast_window_s = max(300, int(queue_policy.get('forecast_window_s') or 1800))
        surge_load_ratio_threshold = max(0.25, float(queue_policy.get('surge_load_ratio_threshold') or 0.85))
        proactive_routing_enabled = bool(queue_policy.get('proactive_routing_enabled'))
        proactive_min_projected_load_delta = max(0.0, float(queue_policy.get('proactive_min_projected_load_delta') or 0.0))
        proactive_wait_buffer_s = max(0, int(queue_policy.get('proactive_wait_buffer_s') or 0))
        proactive_bypass_anti_thrashing = bool(queue_policy.get('proactive_bypass_anti_thrashing'))
        admission_control_enabled = bool(queue_policy.get('admission_control_enabled'))
        overload_governance_enabled = bool(queue_policy.get('overload_governance_enabled'))
        overload_projected_load_ratio_threshold = max(0.25, float(queue_policy.get('overload_projected_load_ratio_threshold') or queue_policy.get('surge_load_ratio_threshold') or 0.95))
        overload_projected_wait_time_threshold_s = max(0, int(queue_policy.get('overload_projected_wait_time_threshold_s') or max(300, default_service_time_s * 2)))
        admission_default_action = str(queue_policy.get('admission_default_action') or 'defer').strip().lower().replace('-', '_') or 'defer'
        overload_global_action = str(queue_policy.get('overload_global_action') or admission_default_action or 'defer').strip().lower().replace('-', '_') or 'defer'
        admission_exempt_severities = [str(item).strip().lower() for item in list(queue_policy.get('admission_exempt_severities') or []) if str(item).strip()]
        admission_exempt_queue_types = [str(item).strip() for item in list(queue_policy.get('admission_exempt_queue_types') or []) if str(item).strip()]
        admit_expedite_on_overload = bool(queue_policy.get('admit_expedite_on_overload', True))
        admit_starving_on_overload = bool(queue_policy.get('admit_starving_on_overload', True))
        queue_families_enabled = bool(queue_policy.get('queue_families_enabled'))
        multi_hop_hysteresis_enabled = bool(queue_policy.get('multi_hop_hysteresis_enabled', queue_families_enabled))
        family_reroute_cooldown_s = max(0, int(queue_policy.get('family_reroute_cooldown_s') or reroute_cooldown_s or 300))
        family_min_active_delta = max(0, int(queue_policy.get('family_min_active_delta') or min_active_delta or 1))
        family_min_load_delta = max(0.0, float(queue_policy.get('family_min_load_delta') or proactive_min_projected_load_delta or min_load_delta or 0.1))
        family_min_projected_wait_delta_s = max(0, int(queue_policy.get('family_min_projected_wait_delta_s') or proactive_wait_buffer_s or 120))
        family_recent_hops_threshold = max(1, int(queue_policy.get('family_recent_hops_threshold') or 2))
        family_history_limit = max(2, int(queue_policy.get('family_history_limit') or 8))
        expedite_bypass_family_hysteresis = bool(queue_policy.get('expedite_bypass_family_hysteresis', True))
        proactive_bypass_family_hysteresis = bool(queue_policy.get('proactive_bypass_family_hysteresis', True))
        starvation_bypass_family_hysteresis = bool(queue_policy.get('starvation_bypass_family_hysteresis', True))
        admission_bypass_family_hysteresis = bool(queue_policy.get('admission_bypass_family_hysteresis', True))
        alert_payload = dict(alert or {})
        alert_routing = dict(alert_payload.get('routing') or {})
        alert_route_history = [dict(item or {}) for item in list(alert_routing.get('route_history') or alert_payload.get('routing_history') or alert_payload.get('route_history') or []) if isinstance(item, dict)]
        if family_history_limit > 0:
            alert_route_history = alert_route_history[-family_history_limit:]
        now_ts = time.time()
        def _queue_family_id_for(queue_id: str, route: dict[str, Any] | None = None) -> str:
            metrics = dict(queues.get(str(queue_id or '').strip()) or {})
            payload = dict(route or {})
            return str(metrics.get('queue_family_id') or payload.get('queue_family_id') or metrics.get('queue_type') or payload.get('queue_type') or queue_policy.get('default_queue_family') or '').strip()
        history_cutoff_ts = now_ts - float(family_reroute_cooldown_s or 0) if family_reroute_cooldown_s > 0 else None
        recent_history = []
        for entry in alert_route_history:
            try:
                entry_ts = float(entry.get('at')) if entry.get('at') is not None else None
            except Exception:
                entry_ts = None
            if history_cutoff_ts is not None and entry_ts is not None and entry_ts < history_cutoff_ts:
                continue
            queue_id = str(entry.get('queue_id') or '').strip()
            if not queue_id:
                continue
            family_id = str(entry.get('queue_family_id') or _queue_family_id_for(queue_id) or '').strip()
            recent_history.append({'at': entry_ts, 'queue_id': queue_id, 'queue_family_id': family_id})
        if normalized_current_queue_id:
            current_family_id = _queue_family_id_for(normalized_current_queue_id)
        else:
            current_family_id = ''
        recent_queue_ids = [str(item.get('queue_id') or '') for item in recent_history if str(item.get('queue_id') or '')]
        recent_family_ids = [str(item.get('queue_family_id') or '') for item in recent_history if str(item.get('queue_family_id') or '')]
        recent_queue_hop_count = sum(1 for idx in range(1, len(recent_queue_ids)) if recent_queue_ids[idx] != recent_queue_ids[idx - 1])
        alert_severity = str(alert_payload.get('severity') or '').strip().lower()
        alert_created_at = None
        try:
            alert_created_at = float(alert_payload.get('created_at')) if alert_payload.get('created_at') is not None else None
        except Exception:
            alert_created_at = None
        alert_queue_updated_at = None
        try:
            alert_queue_updated_at = float(alert_routing.get('updated_at')) if alert_routing.get('updated_at') is not None else None
        except Exception:
            alert_queue_updated_at = None
        alert_wait_age_s = max(0, int(now_ts - (alert_created_at if alert_created_at is not None else (alert_queue_updated_at if alert_queue_updated_at is not None else now_ts))))
        aging_applied = bool(aging_enabled and aging_after_s > 0 and alert_wait_age_s >= aging_after_s)
        starving = bool(starvation_prevention_enabled and starvation_after_s > 0 and alert_wait_age_s >= starvation_after_s)
        sla_snapshot = dict(alert_payload.get('sla_state') or alert_payload.get('sla') or {})
        if alert_payload and bool((normalized_policy.get('sla_policy') or {}).get('enabled')):
            try:
                computed_sla = self._baseline_promotion_simulation_custody_sla_projection(alert_payload, normalized_policy, now_ts=now_ts)
            except Exception:
                computed_sla = {}
            if computed_sla:
                sla_snapshot = computed_sla
        def _extract_sla_target(snapshot: dict[str, Any]) -> tuple[str, int | None, str]:
            targets = dict(snapshot.get('targets') or {})
            candidate_items = []
            for name, raw_target in targets.items():
                target = dict(raw_target or {})
                if not bool(target.get('enabled')):
                    continue
                status = str(target.get('status') or '')
                if status in {'disabled', 'not_applicable', 'met'}:
                    continue
                remaining = target.get('remaining_s')
                try:
                    remaining_value = int(remaining) if remaining is not None else None
                except Exception:
                    remaining_value = None
                candidate_items.append((name, remaining_value, status))
            if not candidate_items:
                return '', None, str(snapshot.get('status') or '')
            name, remaining_value, status = sorted(candidate_items, key=lambda item: (0 if item[1] is not None and int(item[1]) < 0 else 1, float('inf') if item[1] is None else float(item[1]), str(item[0] or '')))[0]
            return str(name or ''), remaining_value, str(status or snapshot.get('status') or '')
        sla_target_name, time_to_breach_s, sla_target_status = _extract_sla_target(sla_snapshot)
        alert_at_risk = bool(expedite_enabled and time_to_breach_s is not None and ((expedite_threshold_s > 0 and time_to_breach_s <= expedite_threshold_s) or str(sla_snapshot.get('status') or '') in {'warning', 'breached'} or str(sla_target_status or '') in {'warning', 'breached'}))
        def _risk_level(score: float, predicted_breach: bool) -> str:
            if predicted_breach or score >= 1.0:
                return 'critical'
            if score >= 0.85:
                return 'high'
            if score >= 0.5:
                return 'medium'
            return 'low'
        def _annotate(route: dict[str, Any], *, reason: str, anti_thrashing_applied: bool = False, anti_thrashing_reason: str = '', starvation_prevention_applied: bool = False, starvation_prevention_reason: str = '', expedite_applied: bool = False, expedite_reason: str = '') -> dict[str, Any]:
            updated = dict(route or {})
            queue_metrics = dict(queues.get(str(updated.get('queue_id') or '').strip()) or {})
            base_active_count = int(queue_metrics.get('active_count') or 0)
            capacity = int(queue_metrics.get('capacity') or updated.get('queue_capacity') or 0)
            reserved_capacity = max(0, int(queue_metrics.get('reserved_capacity') or 0))
            leased_capacity = max(0, int(queue_metrics.get('leased_capacity') or 0))
            hold_capacity = max(0, int(queue_metrics.get('temporary_hold_capacity') or 0))
            general_capacity = max(0, int(queue_metrics.get('general_capacity') or max(0, capacity - reserved_capacity - leased_capacity - hold_capacity)))
            general_available = queue_metrics.get('general_available')
            reserved_available = queue_metrics.get('reserved_available')
            lease_available = queue_metrics.get('lease_available')
            hold_available = queue_metrics.get('temporary_hold_available')
            reservation_enabled = bool(queue_metrics.get('reservation_enabled'))
            lease_active = bool(queue_metrics.get('lease_active'))
            lease_expired = bool(queue_metrics.get('lease_expired'))
            route_queue_type = str(updated.get('queue_type') or queue_metrics.get('queue_type') or '').strip()
            route_queue_id = str(updated.get('queue_id') or queue_metrics.get('queue_id') or '').strip()
            route_queue_family_id = str(queue_metrics.get('queue_family_id') or updated.get('queue_family_id') or route_queue_type or queue_policy.get('default_queue_family') or '').strip()
            route_queue_family_label = str(queue_metrics.get('queue_family_label') or updated.get('queue_family_label') or route_queue_family_id or route_queue_type or '').strip()
            family_member_count = sum(1 for metrics in queues.values() if str(metrics.get('queue_family_id') or metrics.get('queue_type') or queue_policy.get('default_queue_family') or '').strip() == route_queue_family_id) if route_queue_family_id else 0
            family_history_queue_ids = [str(entry.get('queue_id') or '') for entry in recent_history if str(entry.get('queue_family_id') or '') == route_queue_family_id and str(entry.get('queue_id') or '')]
            recent_family_hop_count = sum(1 for idx in range(1, len(family_history_queue_ids)) if family_history_queue_ids[idx] != family_history_queue_ids[idx - 1])
            reserved_for_queue_types = [str(item).strip() for item in list(queue_metrics.get('reserved_for_queue_types') or []) if str(item).strip()]
            reserved_for_severities = [str(item).strip().lower() for item in list(queue_metrics.get('reserved_for_severities') or []) if str(item).strip()]
            leased_for_queue_types = [str(item).strip() for item in list(queue_metrics.get('leased_for_queue_types') or []) if str(item).strip()]
            leased_for_severities = [str(item).strip().lower() for item in list(queue_metrics.get('leased_for_severities') or []) if str(item).strip()]
            active_holds = [dict(item or {}) for item in list(queue_metrics.get('temporary_holds') or []) if isinstance(item, dict)]
            eligible_holds = []
            for hold in active_holds:
                hold_queue_types = [str(item).strip() for item in list(hold.get('for_queue_types') or []) if str(item).strip()]
                hold_severities = [str(item).strip().lower() for item in list(hold.get('for_severities') or []) if str(item).strip()]
                hold_type_match = (not hold_queue_types) or (route_queue_type and route_queue_type in hold_queue_types)
                hold_severity_match = (not hold_severities) or (alert_severity and alert_severity in hold_severities)
                if hold_type_match and hold_severity_match:
                    eligible_holds.append(hold)
            eligible_hold_capacity = max(0, sum(int(hold.get('capacity') or 0) for hold in eligible_holds))
            reservation_eligible = False
            if reservation_enabled:
                severity_match = (not reserved_for_severities) or (alert_severity and alert_severity in reserved_for_severities)
                type_match = (not reserved_for_queue_types) or (route_queue_type and route_queue_type in reserved_for_queue_types)
                reservation_eligible = bool(severity_match and type_match)
            lease_eligible = False
            if lease_active:
                lease_severity_match = (not leased_for_severities) or (alert_severity and alert_severity in leased_for_severities)
                lease_type_match = (not leased_for_queue_types) or (route_queue_type and route_queue_type in leased_for_queue_types)
                lease_eligible = bool(lease_severity_match and lease_type_match)
            temporary_hold_eligible = bool(eligible_holds and eligible_hold_capacity > 0)
            starvation_reserved_capacity_borrowed = bool(reservation_enabled and starving and starvation_reserved_capacity_borrow_enabled and (not reservation_eligible) and int(reserved_available or 0) > 0)
            starvation_lease_capacity_borrowed = bool(lease_active and starving and starvation_lease_capacity_borrow_enabled and (not lease_eligible) and int(lease_available or 0) > 0)
            starvation_temporary_hold_borrowed = bool(active_holds and starving and starvation_hold_capacity_borrow_enabled and (not temporary_hold_eligible) and int(hold_available or 0) > 0)
            expedite_reserved_capacity_borrowed = bool(reservation_enabled and expedite_enabled and alert_at_risk and expedite_reserved_capacity_borrow_enabled and (not reservation_eligible) and (not starvation_reserved_capacity_borrowed) and int(reserved_available or 0) > 0)
            expedite_lease_capacity_borrowed = bool(lease_active and expedite_enabled and alert_at_risk and expedite_lease_capacity_borrow_enabled and (not lease_eligible) and (not starvation_lease_capacity_borrowed) and int(lease_available or 0) > 0)
            expedite_temporary_hold_borrowed = bool(active_holds and expedite_enabled and alert_at_risk and expedite_hold_capacity_borrow_enabled and (not temporary_hold_eligible) and (not starvation_temporary_hold_borrowed) and int(hold_available or 0) > 0)
            projected_active_count = (base_active_count + 1) if str(updated.get('queue_id') or '').strip() else base_active_count
            effective_capacity = general_capacity
            if reservation_enabled and (reservation_eligible or starvation_reserved_capacity_borrowed or expedite_reserved_capacity_borrowed):
                effective_capacity += reserved_capacity
            if lease_active and (lease_eligible or starvation_lease_capacity_borrowed or expedite_lease_capacity_borrowed):
                effective_capacity += leased_capacity
            if active_holds and (temporary_hold_eligible or starvation_temporary_hold_borrowed or expedite_temporary_hold_borrowed):
                effective_capacity += hold_capacity if (starvation_temporary_hold_borrowed or expedite_temporary_hold_borrowed) else eligible_hold_capacity
            if effective_capacity <= 0 and not any([reservation_enabled, lease_active, active_holds]):
                effective_capacity = capacity
            if general_available is None:
                effective_available = (max(0, effective_capacity - base_active_count) if effective_capacity > 0 else None)
            else:
                effective_available = int(general_available or 0)
                if reservation_enabled and (reservation_eligible or starvation_reserved_capacity_borrowed or expedite_reserved_capacity_borrowed):
                    effective_available += int(reserved_available or 0)
                if lease_active and (lease_eligible or starvation_lease_capacity_borrowed or expedite_lease_capacity_borrowed):
                    effective_available += int(lease_available or 0)
                if active_holds and (temporary_hold_eligible or starvation_temporary_hold_borrowed or expedite_temporary_hold_borrowed):
                    effective_available += int(hold_available or 0) if (starvation_temporary_hold_borrowed or expedite_temporary_hold_borrowed) else min(int(hold_available or 0), eligible_hold_capacity)
            reservation_applied = bool(reservation_enabled and reservation_eligible and int(reserved_available or 0) > 0 and int(general_available or 0) <= 0 and capacity > 0)
            lease_applied = bool(lease_active and lease_eligible and int(lease_available or 0) > 0 and int(general_available or 0) <= 0 and capacity > 0)
            temporary_hold_applied = bool(active_holds and temporary_hold_eligible and int(hold_available or 0) > 0 and int(general_available or 0) <= 0 and capacity > 0)
            if starvation_reserved_capacity_borrowed and not starvation_prevention_applied:
                starvation_prevention_applied = True
                starvation_prevention_reason = 'borrow_reserved_capacity'
            elif starvation_lease_capacity_borrowed and not starvation_prevention_applied:
                starvation_prevention_applied = True
                starvation_prevention_reason = 'borrow_leased_capacity'
            elif starvation_temporary_hold_borrowed and not starvation_prevention_applied:
                starvation_prevention_applied = True
                starvation_prevention_reason = 'borrow_temporary_hold_capacity'
            current_projected_active_count = (base_active_count + 1) if str(updated.get('queue_id') or '').strip() else base_active_count
            projected_available = (max(0, effective_capacity - current_projected_active_count) if effective_capacity > 0 else None)
            current_queue_load_ratio = (float(current_projected_active_count) / float(effective_capacity) if effective_capacity > 0 else 0.0)
            service_time_s = max(60, int(queue_metrics.get('expected_service_time_s') or default_service_time_s or 300))
            route_forecast_window_s = max(300, int(queue_metrics.get('forecast_window_s') or forecast_window_s or 1800))
            forecast_arrivals_count = max(0, int(queue_metrics.get('forecast_arrivals_count') or queue_metrics.get('forecast_arrivals') or 0))
            try:
                forecast_arrivals_per_hour = max(0.0, float(queue_metrics.get('forecast_arrivals_per_hour') or 0.0))
            except Exception:
                forecast_arrivals_per_hour = 0.0
            if forecast_arrivals_count <= 0 and forecast_arrivals_per_hour > 0.0:
                forecast_arrivals_count = max(0, int(round(forecast_arrivals_per_hour * (float(route_forecast_window_s) / 3600.0))))
            forecast_departures_count = max(0, int((float(max(effective_capacity, 0)) * float(route_forecast_window_s)) / float(max(service_time_s, 1)))) if effective_capacity > 0 else 0
            projected_active_count = max(0, int(base_active_count + forecast_arrivals_count - forecast_departures_count + 1)) if effective_capacity > 0 else max(0, int(base_active_count + forecast_arrivals_count + 1))
            projected_load_ratio = (float(projected_active_count) / float(effective_capacity) if effective_capacity > 0 else 0.0)
            projected_wait_time_s = int(round((float(max(projected_active_count - 1, 0)) * float(service_time_s)) / float(max(effective_capacity, 1)))) if effective_capacity > 0 else int(round(float(base_active_count + forecast_arrivals_count) * float(service_time_s)))
            forecasted_over_capacity = bool(effective_capacity > 0 and projected_active_count > effective_capacity)
            surge_predicted = bool(predictive_forecasting_enabled and (forecasted_over_capacity or projected_load_ratio >= surge_load_ratio_threshold))
            predicted_wait_time_s = None
            if breach_prediction_enabled and time_to_breach_s is not None and effective_capacity > 0:
                predicted_wait_time_s = int(round(float(service_time_s) * float(max(base_active_count, 0)) / float(max(effective_capacity, 1))))
            elif breach_prediction_enabled and time_to_breach_s is not None:
                predicted_wait_time_s = int(round(float(service_time_s) * float(max(base_active_count, 0))))
            predicted_sla_margin_s = None
            predicted_sla_breach = False
            breach_risk_score = 0.0
            if time_to_breach_s is not None:
                if predicted_wait_time_s is not None:
                    predicted_sla_margin_s = int(time_to_breach_s - predicted_wait_time_s)
                    predicted_sla_breach = bool(predicted_sla_margin_s < 0)
                    denominator = max(float(abs(time_to_breach_s) if time_to_breach_s != 0 else 1.0), 1.0)
                    breach_risk_score = max(0.0, float(predicted_wait_time_s) / denominator)
                elif time_to_breach_s <= 0:
                    predicted_sla_breach = True
                    predicted_sla_margin_s = int(time_to_breach_s)
                    breach_risk_score = 1.0
            breach_risk_level = _risk_level(breach_risk_score, predicted_sla_breach)
            expedite_eligible = bool(expedite_enabled and time_to_breach_s is not None and (alert_at_risk or predicted_sla_breach or breach_risk_score >= expedite_min_risk_score))
            proactive_routing_eligible = bool(proactive_routing_enabled and predictive_forecasting_enabled and surge_predicted)
            route_admission_control_enabled = bool(queue_metrics.get('admission_control_enabled', admission_control_enabled))
            route_overload_governance_enabled = bool(queue_metrics.get('overload_governance_enabled', overload_governance_enabled))
            route_overload_projected_load_ratio_threshold = max(0.25, float(queue_metrics.get('overload_projected_load_ratio_threshold') or overload_projected_load_ratio_threshold or surge_load_ratio_threshold))
            route_overload_projected_wait_time_threshold_s = max(0, int(queue_metrics.get('overload_projected_wait_time_threshold_s') or overload_projected_wait_time_threshold_s or max(300, service_time_s * 2)))
            route_admission_action = str(queue_metrics.get('admission_action') or updated.get('admission_action') or admission_default_action or 'defer').strip().lower().replace('-', '_') or 'defer'
            route_overload_action = str(queue_metrics.get('overload_action') or updated.get('overload_action') or overload_global_action or route_admission_action or 'defer').strip().lower().replace('-', '_') or 'defer'
            route_admission_exempt_severities = [str(item).strip().lower() for item in list(queue_metrics.get('admission_exempt_severities') or admission_exempt_severities or []) if str(item).strip()]
            route_admission_exempt_queue_types = [str(item).strip() for item in list(queue_metrics.get('admission_exempt_queue_types') or admission_exempt_queue_types or []) if str(item).strip()]
            overload_predicted = bool(
                (effective_capacity > 0 and current_projected_active_count >= effective_capacity and bool(queue_metrics.get('hard_limit')))
                or forecasted_over_capacity
                or projected_load_ratio >= route_overload_projected_load_ratio_threshold
                or (route_overload_projected_wait_time_threshold_s > 0 and projected_wait_time_s >= route_overload_projected_wait_time_threshold_s)
            )
            overload_reasons = []
            if effective_capacity > 0 and current_projected_active_count >= effective_capacity and bool(queue_metrics.get('hard_limit')):
                overload_reasons.append('hard_limit_capacity')
            if forecasted_over_capacity:
                overload_reasons.append('forecasted_over_capacity')
            if projected_load_ratio >= route_overload_projected_load_ratio_threshold:
                overload_reasons.append('projected_load_threshold')
            if route_overload_projected_wait_time_threshold_s > 0 and projected_wait_time_s >= route_overload_projected_wait_time_threshold_s:
                overload_reasons.append('projected_wait_threshold')
            admission_exempt = bool(
                (alert_severity and alert_severity in route_admission_exempt_severities)
                or (route_queue_type and route_queue_type in route_admission_exempt_queue_types)
                or (expedite_eligible and admit_expedite_on_overload)
                or (starving and admit_starving_on_overload)
            )
            if expedite_eligible and admit_expedite_on_overload:
                admission_exempt_reason = 'expedite'
            elif starving and admit_starving_on_overload:
                admission_exempt_reason = 'starvation'
            elif alert_severity and alert_severity in route_admission_exempt_severities:
                admission_exempt_reason = 'severity_exempt'
            elif route_queue_type and route_queue_type in route_admission_exempt_queue_types:
                admission_exempt_reason = 'queue_type_exempt'
            else:
                admission_exempt_reason = ''
            admission_decision = 'admit'
            admission_blocked = False
            overload_governance_applied = False
            admission_reason = ''
            overload_reason = ','.join(overload_reasons)
            if route_admission_control_enabled and route_overload_governance_enabled and overload_predicted:
                overload_governance_applied = True
                if admission_exempt:
                    admission_decision = 'admit'
                    admission_reason = f'admit_exempt:{admission_exempt_reason}' if admission_exempt_reason else 'admit_exempt'
                else:
                    admission_decision = route_overload_action if route_overload_action in {'defer', 'manual_gate', 'park', 'reject', 'admit'} else route_admission_action
                    admission_blocked = admission_decision in {'defer', 'manual_gate', 'park', 'reject'}
                    admission_reason = overload_reason or 'overload_predicted'
            updated.update({
                'load_aware': bool(queue_metrics), 'selection_reason': reason, 'queue_active_count': current_projected_active_count, 'queue_capacity': capacity, 'queue_available': projected_available, 'queue_load_ratio': current_queue_load_ratio, 'queue_at_capacity': bool(effective_capacity > 0 and current_projected_active_count >= effective_capacity), 'queue_over_capacity': bool(effective_capacity > 0 and current_projected_active_count > effective_capacity), 'queue_warning': bool(capacity > 0 and current_projected_active_count >= max(1, int(queue_metrics.get('warning_capacity') or max(0, capacity - 1)))), 'team_queue_id': str(queue_metrics.get('queue_id') or updated.get('queue_id') or ''), 'reservation_enabled': reservation_enabled, 'reserved_capacity': reserved_capacity, 'general_capacity': general_capacity, 'general_available': general_available, 'reserved_available': reserved_available, 'reservation_eligible': reservation_eligible, 'reservation_applied': reservation_applied, 'lease_active': lease_active, 'lease_expired': lease_expired, 'leased_capacity': leased_capacity, 'lease_available': lease_available, 'lease_expires_at': queue_metrics.get('lease_expires_at'), 'lease_reason': str(queue_metrics.get('lease_reason') or ''), 'lease_holder': str(queue_metrics.get('lease_holder') or ''), 'lease_id': str(queue_metrics.get('lease_id') or ''), 'lease_eligible': lease_eligible, 'lease_applied': lease_applied, 'starvation_lease_capacity_borrowed': starvation_lease_capacity_borrowed, 'expedite_lease_capacity_borrowed': expedite_lease_capacity_borrowed, 'temporary_hold_count': int(queue_metrics.get('temporary_hold_count') or 0), 'temporary_hold_capacity': hold_capacity, 'temporary_hold_available': hold_available, 'temporary_hold_ids': list(queue_metrics.get('temporary_hold_ids') or []), 'temporary_hold_reasons': list(queue_metrics.get('temporary_hold_reasons') or []), 'temporary_hold_eligible': temporary_hold_eligible, 'temporary_hold_applied': temporary_hold_applied, 'starvation_temporary_hold_borrowed': starvation_temporary_hold_borrowed, 'expedite_temporary_hold_borrowed': expedite_temporary_hold_borrowed, 'expired_temporary_hold_count': int(queue_metrics.get('expired_temporary_hold_count') or 0), 'expired_temporary_hold_ids': list(queue_metrics.get('expired_temporary_hold_ids') or []), 'effective_capacity': effective_capacity, 'alert_wait_age_s': alert_wait_age_s, 'aging_applied': aging_applied, 'starving': starving, 'queue_oldest_alert_age_s': int(queue_metrics.get('oldest_alert_age_s') or 0), 'queue_aged_alert_count': int(queue_metrics.get('aged_alert_count') or 0), 'queue_starving_alert_count': int(queue_metrics.get('starving_alert_count') or 0), 'starvation_reserved_capacity_borrowed': starvation_reserved_capacity_borrowed, 'starvation_prevention_applied': starvation_prevention_applied, 'starvation_prevention_reason': str(starvation_prevention_reason or ''), 'anti_thrashing_applied': anti_thrashing_applied, 'anti_thrashing_reason': str(anti_thrashing_reason or ''), 'queue_family_id': route_queue_family_id, 'queue_family_label': route_queue_family_label, 'queue_family_enabled': bool(queue_families_enabled and route_queue_family_id), 'queue_family_member_count': family_member_count, 'recent_queue_hop_count': recent_queue_hop_count, 'recent_family_hop_count': recent_family_hop_count, 'family_hysteresis_applied': bool(updated.get('family_hysteresis_applied', False)), 'family_hysteresis_reason': str(updated.get('family_hysteresis_reason') or ''), 'route_history_queue_ids': recent_queue_ids[-family_history_limit:], 'route_history_family_ids': recent_family_ids[-family_history_limit:], 'sla_deadline_target': str(sla_target_name or ''), 'time_to_breach_s': time_to_breach_s, 'predicted_wait_time_s': predicted_wait_time_s, 'predicted_sla_margin_s': predicted_sla_margin_s, 'predicted_sla_breach': predicted_sla_breach, 'breach_risk_score': float(round(breach_risk_score, 4)), 'breach_risk_level': breach_risk_level, 'expected_service_time_s': service_time_s, 'forecast_window_s': route_forecast_window_s, 'forecast_arrivals_count': forecast_arrivals_count, 'forecast_departures_count': forecast_departures_count, 'projected_active_count': projected_active_count, 'projected_load_ratio': float(round(projected_load_ratio, 4)), 'projected_wait_time_s': projected_wait_time_s, 'forecasted_over_capacity': forecasted_over_capacity, 'surge_predicted': surge_predicted, 'proactive_routing_eligible': proactive_routing_eligible, 'proactive_routing_applied': bool(updated.get('proactive_routing_applied', False)), 'proactive_reason': str(updated.get('proactive_reason') or ''), 'expedite_eligible': expedite_eligible, 'expedite_reserved_capacity_borrowed': expedite_reserved_capacity_borrowed, 'expedite_applied': expedite_applied, 'expedite_reason': str(expedite_reason or ''), 'admission_control_enabled': route_admission_control_enabled, 'admission_action': route_admission_action, 'admission_exempt_severities': route_admission_exempt_severities, 'admission_exempt_queue_types': route_admission_exempt_queue_types, 'admission_exempt': admission_exempt, 'admission_exempt_reason': admission_exempt_reason, 'admission_decision': admission_decision, 'admission_blocked': admission_blocked, 'admission_reason': admission_reason, 'admission_review_required': admission_decision == 'manual_gate', 'overload_governance_enabled': route_overload_governance_enabled, 'overload_governance_applied': overload_governance_applied, 'overload_action': route_overload_action, 'overload_projected_load_ratio_threshold': route_overload_projected_load_ratio_threshold, 'overload_projected_wait_time_threshold_s': route_overload_projected_wait_time_threshold_s, 'overload_predicted': overload_predicted, 'overload_reason': overload_reason, '_base_active_count': base_active_count, '_effective_available': effective_available,
            })
            return updated
        if not bool((queue_state or {}).get('queues')) or not prefer_lowest_load:
            baseline = sorted(candidates, key=lambda item: (int(item.get('min_escalation_level') or 0), -int(item.get('_route_index') or 0)), reverse=True)[0]
            return _annotate(baseline, reason='policy_order')
        annotated = [_annotate(item, reason='candidate') for item in candidates]
        expedite_candidates = [item for item in annotated if bool(item.get('expedite_eligible'))]
        unblocked_expedite_candidates = [item for item in expedite_candidates if not bool(item.get('admission_blocked'))]
        def _score(route: dict[str, Any]) -> tuple[Any, ...]:
            queue_id = str(route.get('queue_id') or '').strip()
            if not queue_id:
                return (2, 2, float('inf'), float('inf'), float('inf'), float('inf'), int(route.get('_route_index') or 0))
            effective_available = route.get('_effective_available')
            effective_available_value = int(effective_available or 0) if effective_available is not None else 0
            hard_limit = bool(route.get('queue_hard_limit') or (queues.get(queue_id) or {}).get('hard_limit'))
            capacity_blocked = bool(route.get('effective_capacity') and int(route.get('queue_active_count') or 0) > int(route.get('effective_capacity') or 0))
            saturation_blocked = bool(route.get('effective_capacity') and int(route.get('queue_active_count') or 0) >= int(route.get('effective_capacity') or 0))
            hard_rank = 1 if hard_limit and saturation_blocked else 0
            availability_rank = 1 if effective_available is not None and effective_available_value <= 0 else 0
            admission_rank = 1 if bool(route.get('admission_blocked')) else 0
            return (admission_rank, hard_rank, availability_rank, int(route.get('queue_starving_alert_count') or 0), float(route.get('queue_oldest_alert_age_s') or 0.0), int(route.get('_base_active_count') or 0), float(route.get('queue_load_ratio') or 0.0), 0 if not capacity_blocked else 1, int(route.get('_route_index') or 0))
        def _proactive_score(route: dict[str, Any]) -> tuple[Any, ...]:
            queue_id = str(route.get('queue_id') or '').strip()
            if not queue_id:
                return (2, 2, float('inf'), float('inf'), float('inf'), int(route.get('_route_index') or 0))
            hard_limit = bool(route.get('queue_hard_limit') or (queues.get(queue_id) or {}).get('hard_limit'))
            projected_over_capacity_rank = 1 if bool(route.get('forecasted_over_capacity')) else 0
            surge_rank = 1 if bool(route.get('surge_predicted')) else 0
            projected_wait = float(route.get('projected_wait_time_s') if route.get('projected_wait_time_s') is not None else float('inf'))
            projected_load = float(route.get('projected_load_ratio') or 0.0)
            hard_rank = 1 if hard_limit and projected_over_capacity_rank else 0
            admission_rank = 1 if bool(route.get('admission_blocked')) else 0
            return (admission_rank, hard_rank, projected_over_capacity_rank, surge_rank, projected_wait, projected_load, int(route.get('_route_index') or 0))
        if unblocked_expedite_candidates:
            best = sorted(unblocked_expedite_candidates, key=lambda route: (0 if not bool(route.get('predicted_sla_breach')) else 1, -float(route.get('predicted_sla_margin_s') if route.get('predicted_sla_margin_s') is not None else -10**9), float(route.get('predicted_wait_time_s') if route.get('predicted_wait_time_s') is not None else float('inf')), int(route.get('_base_active_count') or 0), float(route.get('queue_load_ratio') or 0.0), int(route.get('_route_index') or 0)))[0]
        elif expedite_candidates:
            best = sorted(expedite_candidates, key=lambda route: (0 if not bool(route.get('predicted_sla_breach')) else 1, -float(route.get('predicted_sla_margin_s') if route.get('predicted_sla_margin_s') is not None else -10**9), float(route.get('predicted_wait_time_s') if route.get('predicted_wait_time_s') is not None else float('inf')), int(route.get('_base_active_count') or 0), float(route.get('queue_load_ratio') or 0.0), int(route.get('_route_index') or 0)))[0]
        else:
            baseline_best = sorted(annotated, key=_score)[0]
            if proactive_routing_enabled and predictive_forecasting_enabled:
                proactive_best = sorted(annotated, key=_proactive_score)[0]
                baseline_projected_load = float(baseline_best.get('projected_load_ratio') or 0.0)
                proactive_projected_load = float(proactive_best.get('projected_load_ratio') or 0.0)
                baseline_projected_wait = int(baseline_best.get('projected_wait_time_s') or 0)
                proactive_projected_wait = int(proactive_best.get('projected_wait_time_s') or 0)
                proactive_improves = bool(
                    str(proactive_best.get('queue_id') or '') != str(baseline_best.get('queue_id') or '') and (
                        (bool(baseline_best.get('surge_predicted')) and not bool(proactive_best.get('surge_predicted'))) or
                        (baseline_projected_load - proactive_projected_load) >= proactive_min_projected_load_delta or
                        (baseline_projected_wait - proactive_projected_wait) >= proactive_wait_buffer_s
                    )
                )
                if proactive_improves:
                    proactive_best = dict(proactive_best)
                    proactive_best['proactive_routing_applied'] = True
                    proactive_best['proactive_reason'] = 'avoid_forecasted_surge' if bool(baseline_best.get('surge_predicted')) and not bool(proactive_best.get('surge_predicted')) else 'lower_projected_wait'
                    best = proactive_best
                else:
                    best = baseline_best
            else:
                best = baseline_best
        queue_id = str(best.get('queue_id') or '').strip(); metrics = dict(queues.get(queue_id) or {}) if queue_id else {}
        reason = 'lowest_load_queue'
        if best.get('expedite_temporary_hold_borrowed'): reason = 'expedite_temporary_hold_queue'
        elif best.get('expedite_lease_capacity_borrowed'): reason = 'expedite_leased_capacity_queue'
        elif best.get('expedite_reserved_capacity_borrowed'): reason = 'expedite_reserved_capacity_queue'
        elif best.get('starvation_temporary_hold_borrowed'): reason = 'starvation_temporary_hold_queue'
        elif best.get('starvation_lease_capacity_borrowed'): reason = 'starvation_leased_capacity_queue'
        elif best.get('starvation_reserved_capacity_borrowed'): reason = 'starvation_reserved_capacity_queue'
        elif bool(best.get('expedite_eligible')): reason = 'expedite_predicted_breach_queue' if bool(best.get('predicted_sla_breach')) else 'expedite_deadline_queue'
        elif bool(best.get('proactive_routing_applied')) and bool(best.get('surge_predicted')): reason = 'proactive_surge_avoidance_queue'
        elif bool(best.get('proactive_routing_applied')): reason = 'proactive_forecast_queue'
        elif best.get('temporary_hold_applied'): reason = 'temporary_hold_queue'
        elif best.get('lease_applied'): reason = 'leased_capacity_queue'
        elif best.get('reservation_applied'): reason = 'reserved_capacity_queue'
        elif bool(best.get('admission_blocked')) and str(best.get('admission_decision') or '') == 'manual_gate': reason = 'overload_manual_gate_queue'
        elif bool(best.get('admission_blocked')) and str(best.get('admission_decision') or '') == 'park': reason = 'overload_park_queue'
        elif bool(best.get('admission_blocked')) and str(best.get('admission_decision') or '') == 'reject': reason = 'overload_reject_queue'
        elif bool(best.get('admission_blocked')): reason = 'overload_defer_queue'
        elif queue_id and int(best.get('queue_starving_alert_count') or 0) > 0: reason = 'avoid_starving_queue'
        elif queue_id and int(best.get('_base_active_count') or 0) == 0: reason = 'empty_queue'
        elif queue_id and bool(best.get('queue_at_capacity')): reason = 'least_loaded_available_queue' if not bool(metrics.get('hard_limit')) else 'least_loaded_hard_limit_queue'
        anti_thrashing_bypassed = False; expedite_bypass_applied = False; proactive_bypass_applied = False; overload_bypass_applied = False
        if anti_thrashing_enabled and normalized_current_queue_id:
            current = next((item for item in annotated if str(item.get('queue_id') or '').strip() == normalized_current_queue_id), None)
            if current and str(current.get('queue_id') or '') != str(best.get('queue_id') or ''):
                try: last_updated_at = float(alert_routing.get('updated_at')) if alert_routing.get('updated_at') is not None else None
                except Exception: last_updated_at = None
                within_cooldown = bool(last_updated_at is not None and reroute_cooldown_s > 0 and (now_ts - last_updated_at) < reroute_cooldown_s)
                active_delta = max(0, int(current.get('_base_active_count') or 0) - int(best.get('_base_active_count') or 0))
                load_delta = max(0.0, float(current.get('queue_load_ratio') or 0.0) - float(best.get('queue_load_ratio') or 0.0))
                current_predicted_breach = bool(current.get('predicted_sla_breach')); best_predicted_breach = bool(best.get('predicted_sla_breach')); current_risk = float(current.get('breach_risk_score') or 0.0); best_risk = float(best.get('breach_risk_score') or 0.0)
                if within_cooldown and active_delta <= min_active_delta and load_delta <= min_load_delta:
                    if bool(current.get('admission_blocked')) and not bool(best.get('admission_blocked')):
                        anti_thrashing_bypassed = True; overload_bypass_applied = True
                    elif starving and starvation_bypass_anti_thrashing: anti_thrashing_bypassed = True
                    elif bool(best.get('expedite_eligible')) and expedite_bypass_anti_thrashing and ((current_predicted_breach and not best_predicted_breach) or (best_risk + 0.1) < current_risk): anti_thrashing_bypassed = True; expedite_bypass_applied = True
                    elif bool(best.get('proactive_routing_applied')) and proactive_bypass_anti_thrashing and ((bool(current.get('surge_predicted')) and not bool(best.get('surge_predicted'))) or (float(current.get('projected_load_ratio') or 0.0) - float(best.get('projected_load_ratio') or 0.0)) >= proactive_min_projected_load_delta or (int(current.get('projected_wait_time_s') or 0) - int(best.get('projected_wait_time_s') or 0)) >= proactive_wait_buffer_s): anti_thrashing_bypassed = True; proactive_bypass_applied = True
                    else:
                        current_reason = 'anti_thrashing_keep_current_queue'
                        if current.get('temporary_hold_applied'):
                            current_reason = 'anti_thrashing_keep_temporary_hold_queue'
                        elif current.get('lease_applied'):
                            current_reason = 'anti_thrashing_keep_leased_queue'
                        elif current.get('reservation_applied'):
                            current_reason = 'anti_thrashing_keep_reserved_queue'
                        return _annotate(current, reason=current_reason, anti_thrashing_applied=True, anti_thrashing_reason='reroute_cooldown_min_delta')
        if anti_thrashing_bypassed:
            if expedite_bypass_applied:
                reason = 'expedite_bypass_anti_thrashing'
            elif proactive_bypass_applied:
                reason = 'proactive_bypass_anti_thrashing'
            elif overload_bypass_applied:
                reason = 'admission_bypass_anti_thrashing'
            else:
                reason = 'starvation_bypass_anti_thrashing'
        family_hysteresis_bypassed = False
        family_hysteresis_reason = ''
        family_expedite_bypass = False
        family_proactive_bypass = False
        family_starvation_bypass = False
        family_admission_bypass = False
        if multi_hop_hysteresis_enabled and queue_families_enabled and normalized_current_queue_id:
            current_family_candidate = next((item for item in annotated if str(item.get('queue_id') or '').strip() == normalized_current_queue_id), None)
            if current_family_candidate and str(current_family_candidate.get('queue_id') or '') != str(best.get('queue_id') or ''):
                current_family = str(current_family_candidate.get('queue_family_id') or _queue_family_id_for(str(current_family_candidate.get('queue_id') or ''), current_family_candidate) or '')
                best_family = str(best.get('queue_family_id') or _queue_family_id_for(str(best.get('queue_id') or ''), best) or '')
                same_family = bool(current_family and best_family and current_family == best_family)
                same_family_history_queue_ids = [str(item.get('queue_id') or '') for item in recent_history if str(item.get('queue_family_id') or '') == current_family and str(item.get('queue_id') or '')]
                same_family_hops = sum(1 for idx in range(1, len(same_family_history_queue_ids)) if same_family_history_queue_ids[idx] != same_family_history_queue_ids[idx - 1])
                recent_return_to_best = bool(str(best.get('queue_id') or '') and str(best.get('queue_id') or '') in same_family_history_queue_ids[:-1])
                family_active_delta = max(0, int(current_family_candidate.get('_base_active_count') or 0) - int(best.get('_base_active_count') or 0))
                family_load_delta = max(0.0, float(current_family_candidate.get('projected_load_ratio') or current_family_candidate.get('queue_load_ratio') or 0.0) - float(best.get('projected_load_ratio') or best.get('queue_load_ratio') or 0.0))
                family_wait_delta = max(0, int(current_family_candidate.get('projected_wait_time_s') or 0) - int(best.get('projected_wait_time_s') or 0))
                family_pressure = bool(same_family and (same_family_hops >= family_recent_hops_threshold or recent_return_to_best or recent_queue_hop_count >= family_recent_hops_threshold + 1))
                family_improvement_small = bool(family_active_delta <= family_min_active_delta and family_load_delta <= family_min_load_delta and family_wait_delta <= family_min_projected_wait_delta_s)
                if family_pressure and family_improvement_small:
                    if bool(current_family_candidate.get('admission_blocked')) and not bool(best.get('admission_blocked')) and admission_bypass_family_hysteresis:
                        family_hysteresis_bypassed = True; family_admission_bypass = True; family_hysteresis_reason = 'bypass_admission_blocked_queue'
                    elif starving and starvation_bypass_family_hysteresis:
                        family_hysteresis_bypassed = True; family_starvation_bypass = True; family_hysteresis_reason = 'bypass_starving_alert'
                    elif bool(best.get('expedite_eligible')) and expedite_bypass_family_hysteresis:
                        family_hysteresis_bypassed = True; family_expedite_bypass = True; family_hysteresis_reason = 'bypass_expedite_alert'
                    elif bool(best.get('proactive_routing_applied')) and proactive_bypass_family_hysteresis:
                        family_hysteresis_bypassed = True; family_proactive_bypass = True; family_hysteresis_reason = 'bypass_proactive_routing'
                    else:
                        kept = _annotate(current_family_candidate, reason='family_hysteresis_keep_current_queue')
                        kept['family_hysteresis_applied'] = True
                        kept['family_hysteresis_reason'] = 'recent_same_family_multi_hop'
                        return kept
        if family_hysteresis_bypassed and not anti_thrashing_bypassed:
            if family_expedite_bypass:
                reason = 'expedite_bypass_family_hysteresis'
            elif family_proactive_bypass:
                reason = 'proactive_bypass_family_hysteresis'
            elif family_admission_bypass:
                reason = 'admission_bypass_family_hysteresis'
            else:
                reason = 'starvation_bypass_family_hysteresis'
        starvation_applied = bool(best.get('starvation_reserved_capacity_borrowed') or best.get('starvation_lease_capacity_borrowed') or best.get('starvation_temporary_hold_borrowed') or (anti_thrashing_bypassed and not expedite_bypass_applied and not proactive_bypass_applied and not overload_bypass_applied))
        if best.get('starvation_temporary_hold_borrowed'):
            starvation_reason = 'borrow_temporary_hold_capacity'
        elif best.get('starvation_lease_capacity_borrowed'):
            starvation_reason = 'borrow_leased_capacity'
        elif best.get('starvation_reserved_capacity_borrowed'):
            starvation_reason = 'borrow_reserved_capacity'
        elif anti_thrashing_bypassed and not expedite_bypass_applied and not proactive_bypass_applied and not overload_bypass_applied:
            starvation_reason = 'bypass_anti_thrashing'
        else:
            starvation_reason = ''
        if best.get('expedite_temporary_hold_borrowed'):
            expedite_reason_value = 'borrow_temporary_hold_capacity'
        elif best.get('expedite_lease_capacity_borrowed'):
            expedite_reason_value = 'borrow_leased_capacity'
        elif best.get('expedite_reserved_capacity_borrowed'):
            expedite_reason_value = 'borrow_reserved_capacity'
        elif expedite_bypass_applied:
            expedite_reason_value = 'bypass_anti_thrashing'
        elif proactive_bypass_applied:
            expedite_reason_value = ''
        elif best.get('predicted_sla_breach'):
            expedite_reason_value = 'predicted_breach'
        elif best.get('expedite_eligible'):
            expedite_reason_value = 'deadline_threshold'
        else:
            expedite_reason_value = ''
        annotated_best = _annotate(best, reason=reason, starvation_prevention_applied=starvation_applied, starvation_prevention_reason=starvation_reason, expedite_applied=bool(best.get('expedite_eligible')), expedite_reason=expedite_reason_value)
        if family_hysteresis_bypassed:
            annotated_best['family_hysteresis_applied'] = False
            annotated_best['family_hysteresis_reason'] = family_hysteresis_reason
        if bool(best.get('proactive_routing_applied')):
            annotated_best['proactive_routing_applied'] = True
            annotated_best['proactive_reason'] = 'bypass_anti_thrashing' if proactive_bypass_applied else str(best.get('proactive_reason') or ('avoid_forecasted_surge' if bool(best.get('surge_predicted')) else 'lower_projected_wait'))
        return annotated_best

    @staticmethod
    def _baseline_promotion_simulation_custody_merge_policy_overrides(
        base: dict[str, Any] | None,
        overrides: dict[str, Any] | None,
    ) -> dict[str, Any]:
        merged = dict(base or {})
        for key, value in dict(overrides or {}).items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = OpenClawBaselineRolloutSupportMixin._baseline_promotion_simulation_custody_merge_policy_overrides(
                    dict(merged.get(key) or {}),
                    value,
                )
            else:
                merged[key] = value
        return merged

    @staticmethod
    def _baseline_promotion_simulation_custody_policy_delta_keys(
        overrides: dict[str, Any] | None,
        *,
        prefix: str = '',
    ) -> list[str]:
        keys: list[str] = []
        for key, value in dict(overrides or {}).items():
            dotted = f'{prefix}.{key}' if prefix else str(key)
            if isinstance(value, dict):
                nested = OpenClawBaselineRolloutSupportMixin._baseline_promotion_simulation_custody_policy_delta_keys(value, prefix=dotted)
                if nested:
                    keys.extend(nested)
                else:
                    keys.append(dotted)
            else:
                keys.append(dotted)
        return keys

    @staticmethod
    def _normalize_baseline_promotion_simulation_custody_policy_what_if_pack(
        raw_pack: dict[str, Any] | None,
        *,
        actor: str = '',
        index: int = 1,
        source: str = 'saved',
    ) -> dict[str, Any]:
        payload = dict(raw_pack or {})
        pack_id = str(payload.get('pack_id') or payload.get('policy_pack_id') or payload.get('scenario_pack_id') or f'routing_policy_pack_{index}').strip() or f'routing_policy_pack_{index}'
        pack_label = str(payload.get('pack_label') or payload.get('label') or payload.get('scenario_pack_label') or pack_id.replace('_', ' ').title()).strip() or pack_id
        comparison_policies: list[dict[str, Any]] = []
        for scenario_index, raw_item in enumerate(list(payload.get('comparison_policies') or payload.get('scenarios') or []), start=1):
            item = dict(raw_item or {})
            overrides = dict(item.get('policy_overrides') or item.get('overrides') or {})
            if not overrides:
                overrides = {
                    key: value
                    for key, value in item.items()
                    if key not in {'scenario_id', 'scenario_label', 'label', 'policy_overrides', 'overrides'}
                }
            scenario_id = str(item.get('scenario_id') or f'{pack_id}_scenario_{scenario_index}').strip() or f'{pack_id}_scenario_{scenario_index}'
            scenario_label = str(item.get('scenario_label') or item.get('label') or scenario_id.replace('_', ' ').title()).strip() or scenario_id
            comparison_policies.append({
                'scenario_id': scenario_id,
                'scenario_label': scenario_label,
                'policy_overrides': overrides,
                'policy_delta_keys': OpenClawBaselineRolloutSupportMixin._baseline_promotion_simulation_custody_policy_delta_keys(overrides),
            })
        return {
            'pack_id': pack_id,
            'pack_label': pack_label,
            'description': str(payload.get('description') or payload.get('summary') or ''),
            'source': str(payload.get('source') or source or 'saved'),
            'category_keys': [str(item).strip() for item in list(payload.get('category_keys') or payload.get('categories') or payload.get('domains') or []) if str(item).strip()],
            'tags': [str(item).strip() for item in list(payload.get('tags') or []) if str(item).strip()],
            'comparison_policies': comparison_policies,
            'scenario_count': len(comparison_policies),
            'created_at': payload.get('created_at') or time.time(),
            'created_by': str(payload.get('created_by') or actor or ''),
            'last_used_at': payload.get('last_used_at'),
            'use_count': int(payload.get('use_count') or 0),
            'registry_entry_id': str(payload.get('registry_entry_id') or payload.get('registry_id') or ''),
            'registry_scope': str(payload.get('registry_scope') or payload.get('share_scope') or '').strip(),
            'promoted_at': payload.get('promoted_at'),
            'promoted_by': str(payload.get('promoted_by') or ''),
            'promoted_from_pack_id': str(payload.get('promoted_from_pack_id') or ''),
            'promoted_from_source': str(payload.get('promoted_from_source') or ''),
            'shared_from_pack_id': str(payload.get('shared_from_pack_id') or ''),
            'shared_from_source': str(payload.get('shared_from_source') or ''),
            'last_shared_at': payload.get('last_shared_at'),
            'last_shared_by': str(payload.get('last_shared_by') or ''),
            'share_count': int(payload.get('share_count') or 0),
            'share_targets': [str(item).strip() for item in list(payload.get('share_targets') or []) if str(item).strip()][:8],
            'catalog_entry_id': str(payload.get('catalog_entry_id') or payload.get('catalog_id') or payload.get('registry_entry_id') or ''),
            'catalog_scope': str(payload.get('catalog_scope') or payload.get('registry_scope') or '').strip(),
            'catalog_scope_key': str(payload.get('catalog_scope_key') or ''),
            'promotion_id': str(payload.get('promotion_id') or ''),
            'workspace_id': str(payload.get('workspace_id') or ''),
            'environment': str(payload.get('environment') or ''),
            'portfolio_family_id': str(payload.get('portfolio_family_id') or ''),
            'runtime_family_id': str(payload.get('runtime_family_id') or ''),
            'catalog_promoted_at': payload.get('catalog_promoted_at') or payload.get('promoted_at'),
            'catalog_promoted_by': str(payload.get('catalog_promoted_by') or payload.get('promoted_by') or ''),
            'catalog_share_count': int(payload.get('catalog_share_count') or payload.get('share_count') or 0),
            'catalog_last_shared_at': payload.get('catalog_last_shared_at') or payload.get('last_shared_at'),
            'catalog_last_shared_by': str(payload.get('catalog_last_shared_by') or payload.get('last_shared_by') or ''),
            'catalog_version_key': str(payload.get('catalog_version_key') or payload.get('version_key') or ''),
            'catalog_version': int(payload.get('catalog_version') or payload.get('version') or 0),
            'catalog_lifecycle_state': str(payload.get('catalog_lifecycle_state') or payload.get('catalog_status') or 'draft').strip() or 'draft',
            'catalog_curated_at': payload.get('catalog_curated_at'),
            'catalog_curated_by': str(payload.get('catalog_curated_by') or ''),
            'catalog_approved_at': payload.get('catalog_approved_at'),
            'catalog_approved_by': str(payload.get('catalog_approved_by') or ''),
            'catalog_deprecated_at': payload.get('catalog_deprecated_at'),
            'catalog_deprecated_by': str(payload.get('catalog_deprecated_by') or ''),
            'catalog_replaced_by_version': int(payload.get('catalog_replaced_by_version') or 0),
            'catalog_is_latest': bool(payload.get('catalog_is_latest', False)),
            'catalog_approval_required': bool(payload.get('catalog_approval_required', False)),
            'catalog_required_approvals': max(0, int(payload.get('catalog_required_approvals') or 0)),
            'catalog_approval_count': int(payload.get('catalog_approval_count') or 0),
            'catalog_approval_state': str(payload.get('catalog_approval_state') or ''),
            'catalog_approval_requested_at': payload.get('catalog_approval_requested_at'),
            'catalog_approval_requested_by': str(payload.get('catalog_approval_requested_by') or ''),
            'catalog_approval_rejected_at': payload.get('catalog_approval_rejected_at'),
            'catalog_approval_rejected_by': str(payload.get('catalog_approval_rejected_by') or ''),
            'catalog_approvals': [
                {
                    'approval_id': str(item.get('approval_id') or item.get('id') or ''),
                    'decision': str(item.get('decision') or ''),
                    'actor': str(item.get('actor') or item.get('approved_by') or item.get('requested_by') or ''),
                    'role': str(item.get('role') or item.get('requested_role') or ''),
                    'at': item.get('at') or item.get('approved_at') or item.get('requested_at'),
                    'note': str(item.get('note') or item.get('reason') or ''),
                }
                for item in list(payload.get('catalog_approvals') or [])[:12]
                if isinstance(item, dict)
            ],
            'catalog_review_state': str(payload.get('catalog_review_state') or '').strip(),
            'catalog_review_requested_at': payload.get('catalog_review_requested_at'),
            'catalog_review_requested_by': str(payload.get('catalog_review_requested_by') or ''),
            'catalog_review_assigned_reviewer': str(payload.get('catalog_review_assigned_reviewer') or ''),
            'catalog_review_assigned_role': str(payload.get('catalog_review_assigned_role') or ''),
            'catalog_review_claimed_by': str(payload.get('catalog_review_claimed_by') or ''),
            'catalog_review_claimed_at': payload.get('catalog_review_claimed_at'),
            'catalog_review_last_transition_at': payload.get('catalog_review_last_transition_at'),
            'catalog_review_last_transition_by': str(payload.get('catalog_review_last_transition_by') or ''),
            'catalog_review_last_transition_action': str(payload.get('catalog_review_last_transition_action') or ''),
            'catalog_review_decision_at': payload.get('catalog_review_decision_at'),
            'catalog_review_decision_by': str(payload.get('catalog_review_decision_by') or ''),
            'catalog_review_decision': str(payload.get('catalog_review_decision') or ''),
            'catalog_review_note_count': int(payload.get('catalog_review_note_count') or len(list(payload.get('catalog_review_events') or payload.get('catalog_review_timeline') or [])) or 0),
            'catalog_review_events': [
                {
                    'event_id': str(item.get('event_id') or item.get('review_event_id') or ''),
                    'event_type': str(item.get('event_type') or ''),
                    'state': str(item.get('state') or ''),
                    'actor': str(item.get('actor') or ''),
                    'role': str(item.get('role') or ''),
                    'at': item.get('at'),
                    'note': str(item.get('note') or ''),
                    'decision': str(item.get('decision') or ''),
                }
                for item in list(payload.get('catalog_review_events') or payload.get('catalog_review_timeline') or [])[:12]
                if isinstance(item, dict)
            ],
            'catalog_dependency_refs': [
                {
                    'dependency_id': str(item.get('dependency_id') or f'dependency-{index}').strip() or f'dependency-{index}',
                    'catalog_entry_id': str(item.get('catalog_entry_id') or item.get('entry_id') or '').strip(),
                    'catalog_version_key': str(item.get('catalog_version_key') or item.get('version_key') or '').strip(),
                    'min_catalog_version': max(0, int(item.get('min_catalog_version') or item.get('min_version') or 0)),
                    'required_lifecycle_state': str(item.get('required_lifecycle_state') or item.get('required_state') or 'approved').strip() or 'approved',
                    'required_release_state': str(item.get('required_release_state') or 'released').strip() or 'released',
                    'reason': str(item.get('reason') or item.get('note') or '').strip(),
                }
                for index, item in enumerate(list(payload.get('catalog_dependency_refs') or [])[:12], start=1)
                if isinstance(item, dict) and (str(item.get('catalog_entry_id') or item.get('entry_id') or '').strip() or str(item.get('catalog_version_key') or item.get('version_key') or '').strip())
            ],
            'catalog_conflict_rules': {
                'conflict_entry_ids': [str(item).strip() for item in list((payload.get('catalog_conflict_rules') or {}).get('conflict_entry_ids') or (payload.get('catalog_conflict_rules') or {}).get('entry_ids') or []) if str(item).strip()][:16],
                'conflict_version_keys': [str(item).strip() for item in list((payload.get('catalog_conflict_rules') or {}).get('conflict_version_keys') or (payload.get('catalog_conflict_rules') or {}).get('version_keys') or []) if str(item).strip()][:16],
                'conflict_category_keys': [str(item).strip() for item in list((payload.get('catalog_conflict_rules') or {}).get('conflict_category_keys') or (payload.get('catalog_conflict_rules') or {}).get('category_keys') or []) if str(item).strip()][:16],
                'conflict_tags': [str(item).strip() for item in list((payload.get('catalog_conflict_rules') or {}).get('conflict_tags') or (payload.get('catalog_conflict_rules') or {}).get('tags') or []) if str(item).strip()][:16],
                'enforce_same_scope': bool((payload.get('catalog_conflict_rules') or {}).get('enforce_same_scope', True)),
            },
            'catalog_freeze_windows': [
                {
                    'window_id': str(item.get('window_id') or f'catalog-freeze-{index}').strip() or f'catalog-freeze-{index}',
                    'label': str(item.get('label') or item.get('name') or f'catalog-freeze-{index}').strip() or f'catalog-freeze-{index}',
                    'start_at': float(item.get('start_at')) if item.get('start_at') is not None else None,
                    'end_at': float(item.get('end_at')) if item.get('end_at') is not None else None,
                    'reason': str(item.get('reason') or '').strip(),
                    'block_stage': bool(item.get('block_stage', True)),
                    'block_release': bool(item.get('block_release', True)),
                    'block_advance': bool(item.get('block_advance', True)),
                }
                for index, item in enumerate(list(payload.get('catalog_freeze_windows') or [])[:12], start=1)
                if isinstance(item, dict)
            ],
            'catalog_release_state': str(payload.get('catalog_release_state') or 'draft').strip() or 'draft',
            'catalog_release_notes': str(payload.get('catalog_release_notes') or ''),
            'catalog_release_train_id': str(payload.get('catalog_release_train_id') or ''),
            'catalog_release_staged_at': payload.get('catalog_release_staged_at'),
            'catalog_release_staged_by': str(payload.get('catalog_release_staged_by') or ''),
            'catalog_released_at': payload.get('catalog_released_at'),
            'catalog_released_by': str(payload.get('catalog_released_by') or ''),
            'catalog_withdrawn_at': payload.get('catalog_withdrawn_at'),
            'catalog_withdrawn_by': str(payload.get('catalog_withdrawn_by') or ''),
            'catalog_withdrawn_reason': str(payload.get('catalog_withdrawn_reason') or ''),
            'catalog_supersedence_state': str(payload.get('catalog_supersedence_state') or ''),
            'catalog_superseded_at': payload.get('catalog_superseded_at'),
            'catalog_superseded_by': str(payload.get('catalog_superseded_by') or ''),
            'catalog_superseded_reason': str(payload.get('catalog_superseded_reason') or ''),
            'catalog_superseded_by_entry_id': str(payload.get('catalog_superseded_by_entry_id') or ''),
            'catalog_superseded_by_version': int(payload.get('catalog_superseded_by_version') or 0),
            'catalog_superseded_by_bundle_id': str(payload.get('catalog_superseded_by_bundle_id') or ''),
            'catalog_supersedes_entry_id': str(payload.get('catalog_supersedes_entry_id') or ''),
            'catalog_supersedes_version': int(payload.get('catalog_supersedes_version') or 0),
            'catalog_restored_from_entry_id': str(payload.get('catalog_restored_from_entry_id') or ''),
            'catalog_restored_from_version': int(payload.get('catalog_restored_from_version') or 0),
            'catalog_restored_at': payload.get('catalog_restored_at'),
            'catalog_restored_by': str(payload.get('catalog_restored_by') or ''),
            'catalog_restored_reason': str(payload.get('catalog_restored_reason') or ''),
            'catalog_rollback_release_state': str(payload.get('catalog_rollback_release_state') or ''),
            'catalog_rollback_release_at': payload.get('catalog_rollback_release_at'),
            'catalog_rollback_release_by': str(payload.get('catalog_rollback_release_by') or ''),
            'catalog_rollback_release_reason': str(payload.get('catalog_rollback_release_reason') or ''),
            'catalog_rollback_target_entry_id': str(payload.get('catalog_rollback_target_entry_id') or ''),
            'catalog_rollback_target_version': int(payload.get('catalog_rollback_target_version') or 0),
            'catalog_emergency_withdrawal_active': bool(payload.get('catalog_emergency_withdrawal_active', False)),
            'catalog_emergency_withdrawal_at': payload.get('catalog_emergency_withdrawal_at'),
            'catalog_emergency_withdrawal_by': str(payload.get('catalog_emergency_withdrawal_by') or ''),
            'catalog_emergency_withdrawal_reason': str(payload.get('catalog_emergency_withdrawal_reason') or ''),
            'catalog_emergency_withdrawal_incident_id': str(payload.get('catalog_emergency_withdrawal_incident_id') or ''),
            'catalog_emergency_withdrawal_severity': str(payload.get('catalog_emergency_withdrawal_severity') or ''),
            'catalog_rollout_enabled': bool(payload.get('catalog_rollout_enabled', False)),
            'catalog_rollout_policy': {
                'enabled': bool((payload.get('catalog_rollout_policy') or {}).get('enabled', False)),
                'wave_size': max(1, int(((payload.get('catalog_rollout_policy') or {}).get('wave_size') or 1))),
                'require_manual_advance': bool((payload.get('catalog_rollout_policy') or {}).get('require_manual_advance', True)),
                'require_evidence_package': bool((payload.get('catalog_rollout_policy') or {}).get('require_evidence_package', False)),
                'require_signed_bundle': bool((payload.get('catalog_rollout_policy') or {}).get('require_signed_bundle', False)),
            },
            'catalog_rollout_train_id': str(payload.get('catalog_rollout_train_id') or ''),
            'catalog_rollout_state': str(payload.get('catalog_rollout_state') or ''),
            'catalog_rollout_current_wave_index': int(payload.get('catalog_rollout_current_wave_index') or 0),
            'catalog_rollout_completed_wave_count': int(payload.get('catalog_rollout_completed_wave_count') or 0),
            'catalog_rollout_paused': bool(payload.get('catalog_rollout_paused', False)),
            'catalog_rollout_frozen': bool(payload.get('catalog_rollout_frozen', False)),
            'catalog_rollout_started_at': payload.get('catalog_rollout_started_at'),
            'catalog_rollout_started_by': str(payload.get('catalog_rollout_started_by') or ''),
            'catalog_rollout_completed_at': payload.get('catalog_rollout_completed_at'),
            'catalog_rollout_completed_by': str(payload.get('catalog_rollout_completed_by') or ''),
            'catalog_rollout_rolled_back_at': payload.get('catalog_rollout_rolled_back_at'),
            'catalog_rollout_rolled_back_by': str(payload.get('catalog_rollout_rolled_back_by') or ''),
            'catalog_rollout_rolled_back_reason': str(payload.get('catalog_rollout_rolled_back_reason') or ''),
            'catalog_rollout_last_transition_at': payload.get('catalog_rollout_last_transition_at'),
            'catalog_rollout_last_transition_by': str(payload.get('catalog_rollout_last_transition_by') or ''),
            'catalog_rollout_last_transition_action': str(payload.get('catalog_rollout_last_transition_action') or ''),
            'catalog_rollout_latest_gate': dict(payload.get('catalog_rollout_latest_gate') or {}),
            'catalog_rollout_targets': [
                {
                    'target_key': str(item.get('target_key') or ''),
                    'promotion_id': str(item.get('promotion_id') or ''),
                    'workspace_id': str(item.get('workspace_id') or ''),
                    'environment': str(item.get('environment') or ''),
                    'released': bool(item.get('released', False)),
                    'released_wave_index': int(item.get('released_wave_index') or 0),
                    'released_at': item.get('released_at'),
                    'released_by': str(item.get('released_by') or ''),
                }
                for item in list(payload.get('catalog_rollout_targets') or [])[:24]
                if isinstance(item, dict)
            ],
            'catalog_rollout_waves': [
                {
                    'wave_index': int(item.get('wave_index') or 0),
                    'status': str(item.get('status') or ''),
                    'target_keys': [str(key) for key in list(item.get('target_keys') or []) if str(key)][:24],
                    'released_at': item.get('released_at'),
                    'released_by': str(item.get('released_by') or ''),
                    'gate_evaluation': dict(item.get('gate_evaluation') or {}),
                }
                for item in list(payload.get('catalog_rollout_waves') or [])[:12]
                if isinstance(item, dict)
            ],
            'catalog_attestation_count': int(payload.get('catalog_attestation_count') or 0),
            'catalog_latest_attestation': dict(payload.get('catalog_latest_attestation') or {}),
            'catalog_evidence_package_count': int(payload.get('catalog_evidence_package_count') or 0),
            'catalog_latest_evidence_package': dict(payload.get('catalog_latest_evidence_package') or {}),
            'catalog_release_bundle_count': int(payload.get('catalog_release_bundle_count') or 0),
            'catalog_latest_release_bundle': dict(payload.get('catalog_latest_release_bundle') or {}),
            'catalog_compliance_summary': dict(payload.get('catalog_compliance_summary') or {}),
            'catalog_compliance_report_count': int(payload.get('catalog_compliance_report_count') or 0),
            'catalog_latest_compliance_report': dict(payload.get('catalog_latest_compliance_report') or {}),
            'catalog_replay_count': int(payload.get('catalog_replay_count') or 0),
            'catalog_last_replayed_at': payload.get('catalog_last_replayed_at'),
            'catalog_last_replayed_by': str(payload.get('catalog_last_replayed_by') or ''),
            'catalog_last_replay_source': str(payload.get('catalog_last_replay_source') or ''),
            'catalog_binding_count': int(payload.get('catalog_binding_count') or 0),
            'catalog_last_bound_at': payload.get('catalog_last_bound_at'),
            'catalog_last_bound_by': str(payload.get('catalog_last_bound_by') or ''),
            'catalog_analytics_summary': dict(payload.get('catalog_analytics_summary') or {}),
            'catalog_analytics_report_count': int(payload.get('catalog_analytics_report_count') or 0),
            'catalog_latest_analytics_report': dict(payload.get('catalog_latest_analytics_report') or {}),
            'organizational_service_id': str(payload.get('organizational_service_id') or payload.get('organizational_catalog_service_id') or ''),
            'organizational_service_entry_id': str(payload.get('organizational_service_entry_id') or payload.get('organizational_catalog_service_entry_id') or ''),
            'organizational_publish_state': str(payload.get('organizational_publish_state') or payload.get('organizational_state') or ''),
            'organizational_visibility': str(payload.get('organizational_visibility') or 'tenant').strip() or 'tenant',
            'organizational_service_scope_key': str(payload.get('organizational_service_scope_key') or ''),
            'organizational_published_at': payload.get('organizational_published_at'),
            'organizational_published_by': str(payload.get('organizational_published_by') or ''),
            'organizational_withdrawn_at': payload.get('organizational_withdrawn_at'),
            'organizational_withdrawn_by': str(payload.get('organizational_withdrawn_by') or ''),
            'organizational_withdrawn_reason': str(payload.get('organizational_withdrawn_reason') or ''),
            'organizational_publication_manifest': dict(payload.get('organizational_publication_manifest') or {}),
            'organizational_publication_health': dict(payload.get('organizational_publication_health') or {}),
            'organizational_reconciliation_report_count': int(payload.get('organizational_reconciliation_report_count') or 0),
            'organizational_latest_reconciliation_report': dict(payload.get('organizational_latest_reconciliation_report') or {}),
        }

    def _baseline_promotion_simulation_custody_builtin_policy_what_if_packs(
        self,
        policy: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        normalized_policy = self._normalize_baseline_promotion_simulation_custody_monitoring_policy(dict(policy or {}))
        queue_policy = dict(normalized_policy.get('queue_capacity_policy') or {})
        expedite_threshold = int(queue_policy.get('expedite_threshold_s') or 300)
        overload_load_threshold = float(queue_policy.get('overload_projected_load_ratio_threshold') or 1.0)
        overload_wait_threshold = int(queue_policy.get('overload_projected_wait_time_threshold_s') or 900)
        builtins = [
            {
                'pack_id': 'family_hysteresis_presets',
                'pack_label': 'Families + hysteresis presets',
                'description': 'Compare queue families and family hysteresis behaviour under equivalent routing options.',
                'source': 'builtin',
                'category_keys': ['families', 'hysteresis'],
                'tags': ['queue-families', 'hysteresis'],
                'comparison_policies': [
                    {'scenario_id': 'disable_family_hysteresis', 'scenario_label': 'Disable family hysteresis', 'policy_overrides': {'queue_capacity_policy': {'multi_hop_hysteresis_enabled': False}}},
                    {'scenario_id': 'disable_queue_families', 'scenario_label': 'Disable queue families', 'policy_overrides': {'queue_capacity_policy': {'queue_families_enabled': False}}},
                    {'scenario_id': 'relax_family_hysteresis', 'scenario_label': 'Relax family hysteresis thresholds', 'policy_overrides': {'queue_capacity_policy': {'multi_hop_hysteresis_enabled': True, 'family_min_active_delta': max(0, int(queue_policy.get('family_min_active_delta') or 1) - 1), 'family_min_load_delta': max(0.0, float(queue_policy.get('family_min_load_delta') or 0.2) / 2.0), 'family_min_projected_wait_delta_s': max(30, int(queue_policy.get('family_min_projected_wait_delta_s') or 120) // 2)}}},
                ],
            },
            {
                'pack_id': 'sla_expedite_presets',
                'pack_label': 'SLA + expedite presets',
                'description': 'Compare deadline protection, breach prediction and expedite sensitivity.',
                'source': 'builtin',
                'category_keys': ['sla', 'expedite'],
                'tags': ['sla', 'expedite'],
                'comparison_policies': [
                    {'scenario_id': 'disable_expedite', 'scenario_label': 'Disable expedite', 'policy_overrides': {'queue_capacity_policy': {'expedite_enabled': False}}},
                    {'scenario_id': 'aggressive_expedite', 'scenario_label': 'Aggressive expedite thresholds', 'policy_overrides': {'queue_capacity_policy': {'breach_prediction_enabled': True, 'expedite_enabled': True, 'expedite_threshold_s': max(expedite_threshold, 600)}}},
                    {'scenario_id': 'disable_breach_prediction', 'scenario_label': 'Disable breach prediction', 'policy_overrides': {'queue_capacity_policy': {'breach_prediction_enabled': False}}},
                ],
            },
            {
                'pack_id': 'admission_overload_presets',
                'pack_label': 'Admission + overload presets',
                'description': 'Compare admission control and overload governance under stricter or more lenient thresholds.',
                'source': 'builtin',
                'category_keys': ['admission', 'overload'],
                'tags': ['admission', 'overload'],
                'comparison_policies': [
                    {'scenario_id': 'disable_admission_control', 'scenario_label': 'Disable admission control', 'policy_overrides': {'queue_capacity_policy': {'admission_control_enabled': False}}},
                    {'scenario_id': 'disable_overload_governance', 'scenario_label': 'Disable overload governance', 'policy_overrides': {'queue_capacity_policy': {'overload_governance_enabled': False}}},
                    {'scenario_id': 'lenient_overload_thresholds', 'scenario_label': 'Lenient overload thresholds', 'policy_overrides': {'queue_capacity_policy': {'overload_governance_enabled': True, 'overload_projected_load_ratio_threshold': max(overload_load_threshold, 1.25), 'overload_projected_wait_time_threshold_s': max(overload_wait_threshold, 1200)}}},
                ],
            },
        ]
        return [self._normalize_baseline_promotion_simulation_custody_policy_what_if_pack(item, actor='system', index=index, source='builtin') for index, item in enumerate(builtins, start=1)]

    def _baseline_promotion_simulation_custody_route_explainability(
        self,
        *,
        current_route: dict[str, Any] | None,
        replayed_route: dict[str, Any] | None,
        scenario_label: str,
        policy_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        current_payload = dict(current_route or {})
        replay_payload = dict(replayed_route or {})
        current_queue_id = str(current_payload.get('queue_id') or '').strip()
        replay_queue_id = str(replay_payload.get('queue_id') or '').strip()
        current_family_id = str(current_payload.get('queue_family_id') or current_payload.get('queue_type') or '').strip()
        replay_family_id = str(replay_payload.get('queue_family_id') or replay_payload.get('queue_type') or '').strip()
        kept_current_queue = bool(current_queue_id and replay_queue_id and current_queue_id == replay_queue_id)
        queue_changed = bool(current_queue_id and replay_queue_id and current_queue_id != replay_queue_id)
        maintained_by = ''
        if kept_current_queue:
            if bool(replay_payload.get('manual_override')):
                maintained_by = 'manual_override'
            elif bool(replay_payload.get('family_hysteresis_applied')):
                maintained_by = 'family_hysteresis'
            elif bool(replay_payload.get('anti_thrashing_applied')):
                maintained_by = 'anti_thrashing'
            elif str(replay_payload.get('admission_decision') or '') == 'manual_gate':
                maintained_by = 'manual_gate'
            else:
                maintained_by = 'policy_preference'
        bypass_reason = ''
        selection_reason = str(replay_payload.get('selection_reason') or '').strip()
        if selection_reason.startswith('expedite_bypass_'):
            bypass_reason = 'expedite'
        elif selection_reason.startswith('proactive_bypass_'):
            bypass_reason = 'proactive_routing'
        elif selection_reason.startswith('starvation_bypass_'):
            bypass_reason = 'starvation_prevention'
        elif selection_reason.startswith('admission_bypass_'):
            bypass_reason = 'admission_control'
        blocking_reasons = [
            str(item)
            for item in [
                replay_payload.get('anti_thrashing_reason'),
                replay_payload.get('family_hysteresis_reason'),
                replay_payload.get('admission_reason'),
                replay_payload.get('starvation_prevention_reason'),
                replay_payload.get('expedite_reason'),
                replay_payload.get('proactive_reason'),
                replay_payload.get('overload_reason'),
            ]
            if str(item).strip()
        ]
        current_wait = int(current_payload.get('projected_wait_time_s') or current_payload.get('predicted_wait_time_s') or 0)
        replay_wait = int(replay_payload.get('projected_wait_time_s') or replay_payload.get('predicted_wait_time_s') or 0)
        policy_delta_keys = self._baseline_promotion_simulation_custody_policy_delta_keys(policy_overrides or {})
        return {
            'scenario_label': str(scenario_label or 'current_policy'),
            'kept_current_queue': kept_current_queue,
            'queue_changed': queue_changed,
            'why_kept_current_queue': maintained_by,
            'bypassed_hysteresis': bool(bypass_reason),
            'why_bypassed_hysteresis': bypass_reason,
            'selection_reason': selection_reason,
            'blocking_reasons': blocking_reasons[:6],
            'current_queue_id': current_queue_id,
            'current_queue_label': str(current_payload.get('queue_label') or current_queue_id),
            'current_queue_family_id': current_family_id,
            'replayed_queue_id': replay_queue_id,
            'replayed_queue_label': str(replay_payload.get('queue_label') or replay_queue_id),
            'replayed_queue_family_id': replay_family_id,
            'current_load_ratio': float(current_payload.get('queue_load_ratio') or 0.0),
            'replayed_load_ratio': float(replay_payload.get('queue_load_ratio') or 0.0),
            'current_projected_wait_time_s': current_wait,
            'replayed_projected_wait_time_s': replay_wait,
            'current_projected_load_ratio': float(current_payload.get('projected_load_ratio') or current_payload.get('queue_load_ratio') or 0.0),
            'replayed_projected_load_ratio': float(replay_payload.get('projected_load_ratio') or replay_payload.get('queue_load_ratio') or 0.0),
            'policy_delta_keys': policy_delta_keys[:12],
        }

    def _baseline_promotion_simulation_custody_route_replay(
        self,
        *,
        alert: dict[str, Any] | None,
        policy: dict[str, Any] | None,
        queue_state: dict[str, Any] | None,
        current_route: dict[str, Any] | None = None,
        comparison_policies: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        alert_payload = dict(alert or {})
        normalized_policy = self._normalize_baseline_promotion_simulation_custody_monitoring_policy(dict(policy or {}))
        current_route_payload = dict(current_route or self._baseline_promotion_simulation_custody_routing_projection(alert_payload))
        scenario_specs = [{'scenario_id': 'current_policy', 'scenario_label': 'Current policy', 'policy_overrides': {}}]
        for index, raw_item in enumerate(list(comparison_policies or []), start=1):
            item = dict(raw_item or {})
            overrides = dict(item.get('policy_overrides') or item.get('overrides') or {})
            if not overrides:
                overrides = {key: value for key, value in item.items() if key not in {'scenario_id', 'scenario_label', 'label', 'policy_overrides', 'overrides'}}
            scenario_label = str(item.get('scenario_label') or item.get('label') or f'comparison_policy_{index}').strip() or f'comparison_policy_{index}'
            scenario_id = str(item.get('scenario_id') or f'comparison_policy_{index}').strip() or f'comparison_policy_{index}'
            scenario_specs.append({'scenario_id': scenario_id, 'scenario_label': scenario_label, 'policy_overrides': overrides})
        scenarios: list[dict[str, Any]] = []
        for spec in scenario_specs:
            overrides = dict(spec.get('policy_overrides') or {})
            effective_policy = self._baseline_promotion_simulation_custody_merge_policy_overrides(normalized_policy, overrides)
            scenario_queue_state = {'policy': dict(effective_policy.get('queue_capacity_policy') or ((queue_state or {}).get('policy')) or {}), 'queues': dict((queue_state or {}).get('queues') or {}), 'summary': dict((queue_state or {}).get('summary') or {})}
            simulated_route = self._baseline_promotion_simulation_custody_route_for_alert(effective_policy, alert_payload, queue_state=scenario_queue_state)
            scenarios.append({
                'scenario_id': str(spec.get('scenario_id') or ''),
                'scenario_label': str(spec.get('scenario_label') or ''),
                'policy_overrides': overrides,
                'policy_delta_keys': self._baseline_promotion_simulation_custody_policy_delta_keys(overrides),
                'route': dict(simulated_route or {}),
                'explainability': self._baseline_promotion_simulation_custody_route_explainability(
                    current_route=current_route_payload,
                    replayed_route=simulated_route,
                    scenario_label=str(spec.get('scenario_label') or ''),
                    policy_overrides=overrides,
                ),
            })
        current_policy_result = next((item for item in scenarios if str(item.get('scenario_id') or '') == 'current_policy'), dict(scenarios[0] or {}) if scenarios else {})
        return {
            'ok': True,
            'alert_id': str(alert_payload.get('alert_id') or ''),
            'current_route': dict(current_route_payload or {}),
            'current_policy': current_policy_result,
            'scenarios': scenarios,
        }

    def simulate_runtime_alert_governance_baseline_promotion_simulation_custody_routing(
        self,
        gw,
        *,
        promotion_id: str,
        actor: str,
        alert_id: str | None = None,
        policy_overrides: dict[str, Any] | None = None,
        comparison_policies: list[dict[str, Any]] | None = None,
        alert_overrides: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        detail = self.get_runtime_alert_governance_baseline_promotion(
            gw,
            promotion_id=promotion_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        if not detail.get('ok'):
            return detail
        release = dict(detail.get('release') or {})
        monitoring = dict(detail.get('simulation_custody_monitoring') or {})
        alert_items = [dict(item or {}) for item in list(((monitoring.get('alerts') or {}).get('items')) or []) if isinstance(item, dict)]
        target = {}
        normalized_alert_id = str(alert_id or '').strip()
        if normalized_alert_id:
            target = next((item for item in alert_items if str(item.get('alert_id') or '').strip() == normalized_alert_id), {})
        if not target:
            target = next((item for item in alert_items if bool(item.get('active'))), {})
        if not target:
            target = dict(alert_items[0] or {}) if alert_items else {}
        if not target:
            synthetic_route = dict((dict(alert_overrides or {}).get('routing') or {}))
            if not synthetic_route:
                default_route = dict((dict(monitoring.get('default_route') or self._baseline_promotion_simulation_custody_monitoring_policy_for_release(release).get('default_route') or {})))
                synthetic_route = {
                    'route_id': str(default_route.get('route_id') or ''),
                    'queue_id': str(default_route.get('queue_id') or ''),
                    'queue_label': str(default_route.get('queue_label') or ''),
                    'queue_family_id': str(default_route.get('queue_family_id') or ''),
                    'owner_role': str(default_route.get('owner_role') or ''),
                    'selection_reason': 'synthetic_replay',
                    'source': 'synthetic_replay',
                }
            target = {
                'alert_id': normalized_alert_id or 'simulation-custody-routing-replay',
                'kind': 'routing_replay',
                'active': False,
                'status': 'simulated',
                'created_at': time.time(),
                'created_by': str(actor or 'operator'),
                'severity': str((dict(alert_overrides or {}).get('severity') or '')).strip() or 'warning',
                'escalation_level': int(dict(alert_overrides or {}).get('escalation_level') or 0),
                'routing': synthetic_route,
                'ownership': {'queue_id': str(synthetic_route.get('queue_id') or ''), 'queue_label': str(synthetic_route.get('queue_label') or ''), 'owner_role': str(synthetic_route.get('owner_role') or '')},
                'route_history': [
                    {
                        'at': time.time(),
                        'route_id': str(synthetic_route.get('route_id') or ''),
                        'queue_id': str(synthetic_route.get('queue_id') or ''),
                        'queue_family_id': str(synthetic_route.get('queue_family_id') or ''),
                        'selection_reason': str(synthetic_route.get('selection_reason') or 'synthetic_replay'),
                        'source': str(synthetic_route.get('source') or 'synthetic_replay'),
                    }
                ] if synthetic_route else [],
            }
        if alert_overrides:
            target = self._baseline_promotion_simulation_custody_merge_policy_overrides(target, dict(alert_overrides or {}))
        base_policy = self._baseline_promotion_simulation_custody_merge_policy_overrides(
            dict(monitoring.get('policy') or self._baseline_promotion_simulation_custody_monitoring_policy_for_release(release)),
            dict(policy_overrides or {}),
        )
        target_alert_id = str(target.get('alert_id') or '')
        current_route = self._baseline_promotion_simulation_custody_routing_projection(target)
        base_queue_state = self._baseline_promotion_simulation_custody_queue_capacity_state(
            gw,
            release=release,
            policy=base_policy,
            exclude_alert_id=target_alert_id or None,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        replay = self._baseline_promotion_simulation_custody_route_replay(
            alert=target,
            policy=base_policy,
            queue_state=base_queue_state,
            current_route=current_route,
            comparison_policies=comparison_policies,
        )
        return {
            'ok': True,
            'promotion_id': str(release.get('release_id') or promotion_id),
            'alert_id': str(target.get('alert_id') or ''),
            'alert': target,
            'routing_replay': replay,
            'scope': detail.get('scope'),
        }

    @staticmethod
    def _normalize_baseline_promotion_simulation_custody_route(raw_route: dict[str, Any] | None, *, index: int = 1, fallback_target_path: str = '/ui/?tab=operator') -> dict[str, Any]:
        payload = dict(raw_route or {})
        try:
            min_level = int(payload.get('min_escalation_level') or payload.get('min_level') or payload.get('level') or payload.get('escalation_level') or 0)
        except Exception:
            min_level = 0
        max_level_raw = payload.get('max_escalation_level') or payload.get('max_level')
        try:
            max_level = int(max_level_raw) if max_level_raw is not None else None
        except Exception:
            max_level = None
        capacity_raw = payload.get('queue_capacity')
        if capacity_raw is None:
            capacity_raw = payload.get('capacity')
        try:
            queue_capacity = int(capacity_raw) if capacity_raw is not None else 0
        except Exception:
            queue_capacity = 0
        try:
            load_weight = float(payload.get('load_weight') or payload.get('queue_weight') or 1.0)
        except Exception:
            load_weight = 1.0
        return {
            'route_id': str(payload.get('route_id') or payload.get('id') or f'route-{index}').strip() or f'route-{index}',
            'label': str(payload.get('label') or payload.get('name') or f'Route {index}').strip() or f'Route {index}',
            'min_escalation_level': max(0, int(min_level or 0)),
            'max_escalation_level': None if max_level is None else max(0, int(max_level or 0)),
            'queue_id': str(payload.get('queue_id') or payload.get('queue') or '').strip(),
            'queue_label': str(payload.get('queue_label') or payload.get('queue_name') or payload.get('queue') or '').strip(),
            'owner_role': str(payload.get('owner_role') or payload.get('requested_role') or '').strip(),
            'owner_id': str(payload.get('owner_id') or payload.get('assignee') or '').strip(),
            'target_path': str(payload.get('target_path') or fallback_target_path).strip() or fallback_target_path,
            'severity': str(payload.get('severity') or '').strip(),
            'breach_targets': [str(item).strip() for item in list(payload.get('breach_targets') or payload.get('on_targets') or payload.get('targets') or []) if str(item).strip()],
            'queue_type': str(payload.get('queue_type') or payload.get('type') or '').strip(),
            'queue_family_id': str(payload.get('queue_family_id') or payload.get('family_id') or payload.get('family') or payload.get('queue_type') or payload.get('type') or '').strip(),
            'queue_family_label': str(payload.get('queue_family_label') or payload.get('family_label') or payload.get('queue_family_id') or payload.get('family_id') or payload.get('family') or payload.get('queue_type') or payload.get('type') or '').strip(),
            'queue_capacity': max(0, int(queue_capacity or 0)),
            'queue_hard_limit': bool(payload.get('queue_hard_limit', payload.get('hard_limit', False))),
            'load_weight': max(0.1, float(load_weight or 1.0)),
            'load_aware': bool(payload.get('load_aware')),
            'selection_reason': str(payload.get('selection_reason') or '').strip(),
            'queue_active_count': int(payload.get('queue_active_count') or 0),
            'queue_available': payload.get('queue_available'),
            'queue_load_ratio': float(payload.get('queue_load_ratio') or 0.0),
            'queue_at_capacity': bool(payload.get('queue_at_capacity')),
            'queue_over_capacity': bool(payload.get('queue_over_capacity')),
            'queue_warning': bool(payload.get('queue_warning')),
            'reservation_enabled': bool(payload.get('reservation_enabled')),
            'reserved_capacity': int(payload.get('reserved_capacity') or 0),
            'general_capacity': int(payload.get('general_capacity') or 0),
            'general_available': payload.get('general_available'),
            'reserved_available': payload.get('reserved_available'),
            'reservation_eligible': bool(payload.get('reservation_eligible')),
            'reservation_applied': bool(payload.get('reservation_applied')),
            'lease_active': bool(payload.get('lease_active')),
            'lease_expired': bool(payload.get('lease_expired')),
            'leased_capacity': int(payload.get('leased_capacity') or 0),
            'lease_available': payload.get('lease_available'),
            'lease_expires_at': payload.get('lease_expires_at'),
            'lease_reason': str(payload.get('lease_reason') or '').strip(),
            'lease_holder': str(payload.get('lease_holder') or '').strip(),
            'lease_id': str(payload.get('lease_id') or '').strip(),
            'lease_eligible': bool(payload.get('lease_eligible')),
            'lease_applied': bool(payload.get('lease_applied')),
            'starvation_lease_capacity_borrowed': bool(payload.get('starvation_lease_capacity_borrowed')),
            'expedite_lease_capacity_borrowed': bool(payload.get('expedite_lease_capacity_borrowed')),
            'temporary_hold_count': int(payload.get('temporary_hold_count') or 0),
            'temporary_hold_capacity': int(payload.get('temporary_hold_capacity') or 0),
            'temporary_hold_available': payload.get('temporary_hold_available'),
            'temporary_hold_ids': [str(item) for item in list(payload.get('temporary_hold_ids') or []) if str(item)],
            'temporary_hold_reasons': [str(item) for item in list(payload.get('temporary_hold_reasons') or []) if str(item)],
            'temporary_hold_eligible': bool(payload.get('temporary_hold_eligible')),
            'temporary_hold_applied': bool(payload.get('temporary_hold_applied')),
            'starvation_temporary_hold_borrowed': bool(payload.get('starvation_temporary_hold_borrowed')),
            'expedite_temporary_hold_borrowed': bool(payload.get('expedite_temporary_hold_borrowed')),
            'expired_temporary_hold_count': int(payload.get('expired_temporary_hold_count') or 0),
            'expired_temporary_hold_ids': [str(item) for item in list(payload.get('expired_temporary_hold_ids') or []) if str(item)],
            'effective_capacity': int(payload.get('effective_capacity') or 0),
            'alert_wait_age_s': int(payload.get('alert_wait_age_s') or 0),
            'aging_applied': bool(payload.get('aging_applied')),
            'starving': bool(payload.get('starving')),
            'queue_oldest_alert_age_s': int(payload.get('queue_oldest_alert_age_s') or 0),
            'queue_aged_alert_count': int(payload.get('queue_aged_alert_count') or 0),
            'queue_starving_alert_count': int(payload.get('queue_starving_alert_count') or 0),
            'starvation_reserved_capacity_borrowed': bool(payload.get('starvation_reserved_capacity_borrowed')),
            'starvation_prevention_applied': bool(payload.get('starvation_prevention_applied')),
            'starvation_prevention_reason': str(payload.get('starvation_prevention_reason') or '').strip(),
            'anti_thrashing_applied': bool(payload.get('anti_thrashing_applied')),
            'anti_thrashing_reason': str(payload.get('anti_thrashing_reason') or '').strip(),
            'queue_family_enabled': bool(payload.get('queue_family_enabled')),
            'queue_family_member_count': int(payload.get('queue_family_member_count') or 0),
            'recent_queue_hop_count': int(payload.get('recent_queue_hop_count') or 0),
            'recent_family_hop_count': int(payload.get('recent_family_hop_count') or 0),
            'family_hysteresis_applied': bool(payload.get('family_hysteresis_applied')),
            'family_hysteresis_reason': str(payload.get('family_hysteresis_reason') or '').strip(),
            'route_history_queue_ids': [str(item) for item in list(payload.get('route_history_queue_ids') or []) if str(item)],
            'route_history_family_ids': [str(item) for item in list(payload.get('route_history_family_ids') or []) if str(item)],
            'sla_deadline_target': str(payload.get('sla_deadline_target') or '').strip(),
            'time_to_breach_s': payload.get('time_to_breach_s'),
            'predicted_wait_time_s': payload.get('predicted_wait_time_s'),
            'predicted_sla_margin_s': payload.get('predicted_sla_margin_s'),
            'predicted_sla_breach': bool(payload.get('predicted_sla_breach')),
            'breach_risk_score': float(payload.get('breach_risk_score') or 0.0),
            'breach_risk_level': str(payload.get('breach_risk_level') or '').strip(),
            'expected_service_time_s': int(payload.get('expected_service_time_s') or 0),
            'forecast_window_s': int(payload.get('forecast_window_s') or 0),
            'forecast_arrivals_count': int(payload.get('forecast_arrivals_count') or 0),
            'forecast_departures_count': int(payload.get('forecast_departures_count') or 0),
            'projected_active_count': int(payload.get('projected_active_count') or 0),
            'projected_load_ratio': float(payload.get('projected_load_ratio') or 0.0),
            'projected_wait_time_s': int(payload.get('projected_wait_time_s') or 0),
            'forecasted_over_capacity': bool(payload.get('forecasted_over_capacity')),
            'surge_predicted': bool(payload.get('surge_predicted')),
            'proactive_routing_eligible': bool(payload.get('proactive_routing_eligible')),
            'proactive_routing_applied': bool(payload.get('proactive_routing_applied')),
            'proactive_reason': str(payload.get('proactive_reason') or '').strip(),
            'expedite_eligible': bool(payload.get('expedite_eligible')),
            'expedite_reserved_capacity_borrowed': bool(payload.get('expedite_reserved_capacity_borrowed')),
            'expedite_applied': bool(payload.get('expedite_applied')),
            'expedite_reason': str(payload.get('expedite_reason') or '').strip(),
            '_route_index': int(payload.get('_route_index') or 0),
        }

    def _baseline_promotion_simulation_custody_route_for_alert(
        self,
        policy: dict[str, Any] | None,
        alert: dict[str, Any] | None,
        *,
        preferred_route_id: str | None = None,
        queue_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_policy = self._normalize_baseline_promotion_simulation_custody_monitoring_policy(dict(policy or {}))
        fallback_target_path = str(normalized_policy.get('target_path') or '/ui/?tab=operator').strip() or '/ui/?tab=operator'
        routes = [dict(item) for item in list(normalized_policy.get('routing_routes') or [])]
        default_route = dict(normalized_policy.get('default_route') or {})
        manual_routing = dict((dict(alert or {}).get('routing') or {}))
        preferred = str(preferred_route_id or '').strip()
        if not preferred and bool(manual_routing.get('manual_override')):
            if any(str(manual_routing.get(key) or '').strip() for key in ('route_id', 'queue_id', 'owner_role', 'owner_id')):
                manual_route = self._normalize_baseline_promotion_simulation_custody_route({
                    'route_id': manual_routing.get('route_id') or 'manual-route',
                    'label': manual_routing.get('route_label') or manual_routing.get('label') or 'Manual route',
                    'queue_id': manual_routing.get('queue_id') or '',
                    'queue_label': manual_routing.get('queue_label') or '',
                    'owner_role': manual_routing.get('owner_role') or '',
                    'owner_id': manual_routing.get('owner_id') or '',
                    'target_path': manual_routing.get('target_path') or normalized_policy.get('target_path') or fallback_target_path,
                    'severity': manual_routing.get('severity') or '',
                    'queue_type': manual_routing.get('queue_type') or '',
                }, index=0, fallback_target_path=normalized_policy.get('target_path') or fallback_target_path)
                return self._select_baseline_promotion_simulation_custody_route_by_load(
                    routes=[manual_route],
                    queue_state=queue_state,
                    current_queue_id=str(manual_routing.get('queue_id') or ''),
                    prefer_lowest_load=False,
                    alert=alert,
                    policy=normalized_policy,
                )
        if preferred:
            explicit = next((item for item in routes if str(item.get('route_id') or '') == preferred), None)
            if explicit is not None:
                return self._select_baseline_promotion_simulation_custody_route_by_load(
                    routes=[explicit],
                    queue_state=queue_state,
                    current_queue_id=str(manual_routing.get('queue_id') or ''),
                    prefer_lowest_load=bool(normalized_policy.get('load_aware_routing_enabled')),
                    alert=alert,
                    policy=normalized_policy,
                )
            if str(default_route.get('route_id') or '') == preferred:
                return self._select_baseline_promotion_simulation_custody_route_by_load(
                    routes=[default_route],
                    queue_state=queue_state,
                    current_queue_id=str(manual_routing.get('queue_id') or ''),
                    prefer_lowest_load=bool(normalized_policy.get('load_aware_routing_enabled')),
                    alert=alert,
                    policy=normalized_policy,
                )
        level = max(0, int((dict(alert or {}).get('escalation_level') or 0)))
        severity = str((dict(alert or {}).get('severity') or '')).strip().lower()
        matching = []
        for route in routes:
            min_level = max(0, int(route.get('min_escalation_level') or 0))
            max_level = route.get('max_escalation_level')
            if level < min_level:
                continue
            if max_level is not None and level > int(max_level or 0):
                continue
            route_severity = str(route.get('severity') or '').strip().lower()
            if route_severity and severity and route_severity != severity:
                continue
            matching.append(route)
        candidates = matching or ([default_route] if any(default_route.get(key) for key in ('route_id', 'queue_id', 'owner_role', 'owner_id')) else [])
        if candidates:
            return self._select_baseline_promotion_simulation_custody_route_by_load(
                routes=candidates,
                queue_state=queue_state,
                current_queue_id=str(manual_routing.get('queue_id') or ''),
                prefer_lowest_load=bool(normalized_policy.get('load_aware_routing_enabled', False)),
                alert=alert,
                policy=normalized_policy,
            )
        return {}

    def _baseline_promotion_simulation_custody_sla_route_for_alert(
        self,
        policy: dict[str, Any] | None,
        alert: dict[str, Any] | None,
        sla: dict[str, Any] | None,
        *,
        breached_targets: list[str] | None = None,
        queue_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_policy = self._normalize_baseline_promotion_simulation_custody_monitoring_policy(dict(policy or {}))
        if not bool(normalized_policy.get('auto_reroute_on_sla_breach')):
            return {}
        normalized_targets = [str(item).strip() for item in list(breached_targets or (dict(sla or {}).get('breached_targets') or [])) if str(item).strip()]
        level = max(0, int((dict(alert or {}).get('escalation_level') or 0)))
        severity = str(((normalized_policy.get('sla_policy') or {}).get('severity') or dict(alert or {}).get('severity') or '')).strip().lower()
        candidates = []
        for raw_route in list(normalized_policy.get('team_escalation_queues') or []):
            route = self._normalize_baseline_promotion_simulation_custody_route(dict(raw_route or {}), index=0, fallback_target_path=str((normalized_policy.get('sla_policy') or {}).get('target_path') or normalized_policy.get('target_path') or '/ui/?tab=operator'))
            route_targets = [str(item).strip() for item in list(route.get('breach_targets') or []) if str(item).strip()]
            if route_targets and normalized_targets and not set(route_targets).intersection(normalized_targets):
                continue
            min_level = max(0, int(route.get('min_escalation_level') or 0))
            max_level = route.get('max_escalation_level')
            if level < min_level:
                continue
            if max_level is not None and level > int(max_level or 0):
                continue
            route_severity = str(route.get('severity') or '').strip().lower()
            if route_severity and severity and route_severity != severity:
                continue
            candidates.append(route)
        if candidates:
            candidates.sort(key=lambda item: (len(list(item.get('breach_targets') or [])), int(item.get('min_escalation_level') or 0), str(item.get('route_id') or '')), reverse=True)
            return self._select_baseline_promotion_simulation_custody_route_by_load(
                routes=candidates,
                queue_state=queue_state,
                current_queue_id=str(((alert or {}).get('routing') or {}).get('queue_id') or ''),
                prefer_lowest_load=bool(normalized_policy.get('load_aware_routing_enabled', False)),
                alert=alert,
                policy=normalized_policy,
            )
        fallback_route = dict(normalized_policy.get('sla_breach_route') or {})
        if fallback_route:
            fallback_targets = [str(item).strip() for item in list(fallback_route.get('breach_targets') or []) if str(item).strip()]
            if not fallback_targets or not normalized_targets or set(fallback_targets).intersection(normalized_targets):
                return self._select_baseline_promotion_simulation_custody_route_by_load(
                    routes=[fallback_route],
                    queue_state=queue_state,
                    current_queue_id=str(((alert or {}).get('routing') or {}).get('queue_id') or ''),
                    prefer_lowest_load=bool(normalized_policy.get('load_aware_routing_enabled', False)),
                    alert=alert,
                    policy=normalized_policy,
                )
        return {}

    @staticmethod
    def _baseline_promotion_simulation_custody_ownership_projection(alert: dict[str, Any] | None) -> dict[str, Any]:
        ownership = dict((dict(alert or {}).get('ownership') or {}))
        owner_id = str(ownership.get('owner_id') or '').strip()
        owner_role = str(ownership.get('owner_role') or '').strip()
        queue_id = str(ownership.get('queue_id') or '').strip()
        status = str(ownership.get('status') or '').strip() or ('claimed' if owner_id and str(ownership.get('claimed_by') or '') == owner_id else ('assigned' if owner_id else ('queued' if queue_id or owner_role else 'unassigned')))
        return {
            'status': status,
            'owner_id': owner_id,
            'owner_display': str(ownership.get('owner_display') or owner_id or '').strip(),
            'owner_role': owner_role,
            'queue_id': queue_id,
            'queue_label': str(ownership.get('queue_label') or '').strip(),
            'claimed': status == 'claimed',
            'assigned': bool(owner_id),
            'queued': status == 'queued' or bool(queue_id or owner_role),
            'assigned_at': ownership.get('assigned_at'),
            'assigned_by': str(ownership.get('assigned_by') or '').strip(),
            'claimed_at': ownership.get('claimed_at'),
            'claimed_by': str(ownership.get('claimed_by') or '').strip(),
            'released_at': ownership.get('released_at'),
            'released_by': str(ownership.get('released_by') or '').strip(),
        }

    @staticmethod
    def _baseline_promotion_simulation_custody_routing_projection(alert: dict[str, Any] | None) -> dict[str, Any]:
        routing = dict((dict(alert or {}).get('routing') or {}))
        return {
            'route_id': str(routing.get('route_id') or '').strip(),
            'route_label': str(routing.get('route_label') or routing.get('label') or '').strip(),
            'queue_id': str(routing.get('queue_id') or '').strip(),
            'queue_label': str(routing.get('queue_label') or '').strip(),
            'owner_role': str(routing.get('owner_role') or '').strip(),
            'owner_id': str(routing.get('owner_id') or '').strip(),
            'target_path': str(routing.get('target_path') or '').strip(),
            'updated_at': routing.get('updated_at'),
            'updated_by': str(routing.get('updated_by') or '').strip(),
            'source': str(routing.get('source') or '').strip(),
            'manual_override': bool(routing.get('manual_override')),
            'load_aware': bool(routing.get('load_aware')),
            'selection_reason': str(routing.get('selection_reason') or '').strip(),
            'queue_active_count': int(routing.get('queue_active_count') or 0),
            'queue_capacity': int(routing.get('queue_capacity') or 0),
            'queue_available': routing.get('queue_available'),
            'queue_load_ratio': float(routing.get('queue_load_ratio') or 0.0),
            'queue_at_capacity': bool(routing.get('queue_at_capacity')),
            'queue_over_capacity': bool(routing.get('queue_over_capacity')),
            'queue_warning': bool(routing.get('queue_warning')),
            'reservation_enabled': bool(routing.get('reservation_enabled')),
            'reserved_capacity': int(routing.get('reserved_capacity') or 0),
            'general_capacity': int(routing.get('general_capacity') or 0),
            'general_available': routing.get('general_available'),
            'reserved_available': routing.get('reserved_available'),
            'reservation_eligible': bool(routing.get('reservation_eligible')),
            'reservation_applied': bool(routing.get('reservation_applied')),
            'lease_active': bool(routing.get('lease_active')),
            'lease_expired': bool(routing.get('lease_expired')),
            'leased_capacity': int(routing.get('leased_capacity') or 0),
            'lease_available': routing.get('lease_available'),
            'lease_expires_at': routing.get('lease_expires_at'),
            'lease_reason': str(routing.get('lease_reason') or '').strip(),
            'lease_holder': str(routing.get('lease_holder') or '').strip(),
            'lease_id': str(routing.get('lease_id') or '').strip(),
            'lease_eligible': bool(routing.get('lease_eligible')),
            'lease_applied': bool(routing.get('lease_applied')),
            'starvation_lease_capacity_borrowed': bool(routing.get('starvation_lease_capacity_borrowed')),
            'expedite_lease_capacity_borrowed': bool(routing.get('expedite_lease_capacity_borrowed')),
            'temporary_hold_count': int(routing.get('temporary_hold_count') or 0),
            'temporary_hold_capacity': int(routing.get('temporary_hold_capacity') or 0),
            'temporary_hold_available': routing.get('temporary_hold_available'),
            'temporary_hold_ids': [str(item) for item in list(routing.get('temporary_hold_ids') or []) if str(item)],
            'temporary_hold_reasons': [str(item) for item in list(routing.get('temporary_hold_reasons') or []) if str(item)],
            'temporary_hold_eligible': bool(routing.get('temporary_hold_eligible')),
            'temporary_hold_applied': bool(routing.get('temporary_hold_applied')),
            'starvation_temporary_hold_borrowed': bool(routing.get('starvation_temporary_hold_borrowed')),
            'expedite_temporary_hold_borrowed': bool(routing.get('expedite_temporary_hold_borrowed')),
            'expired_temporary_hold_count': int(routing.get('expired_temporary_hold_count') or 0),
            'expired_temporary_hold_ids': [str(item) for item in list(routing.get('expired_temporary_hold_ids') or []) if str(item)],
            'effective_capacity': int(routing.get('effective_capacity') or 0),
            'alert_wait_age_s': int(routing.get('alert_wait_age_s') or 0),
            'aging_applied': bool(routing.get('aging_applied')),
            'starving': bool(routing.get('starving')),
            'queue_oldest_alert_age_s': int(routing.get('queue_oldest_alert_age_s') or 0),
            'queue_aged_alert_count': int(routing.get('queue_aged_alert_count') or 0),
            'queue_starving_alert_count': int(routing.get('queue_starving_alert_count') or 0),
            'starvation_reserved_capacity_borrowed': bool(routing.get('starvation_reserved_capacity_borrowed')),
            'starvation_prevention_applied': bool(routing.get('starvation_prevention_applied')),
            'starvation_prevention_reason': str(routing.get('starvation_prevention_reason') or '').strip(),
            'anti_thrashing_applied': bool(routing.get('anti_thrashing_applied')),
            'anti_thrashing_reason': str(routing.get('anti_thrashing_reason') or '').strip(),
            'queue_family_id': str(routing.get('queue_family_id') or routing.get('queue_type') or '').strip(),
            'queue_family_label': str(routing.get('queue_family_label') or routing.get('queue_family_id') or routing.get('queue_type') or '').strip(),
            'queue_family_enabled': bool(routing.get('queue_family_enabled')),
            'queue_family_member_count': int(routing.get('queue_family_member_count') or 0),
            'recent_queue_hop_count': int(routing.get('recent_queue_hop_count') or 0),
            'recent_family_hop_count': int(routing.get('recent_family_hop_count') or 0),
            'family_hysteresis_applied': bool(routing.get('family_hysteresis_applied')),
            'family_hysteresis_reason': str(routing.get('family_hysteresis_reason') or '').strip(),
            'route_history_queue_ids': [str(item) for item in list(routing.get('route_history_queue_ids') or []) if str(item)],
            'route_history_family_ids': [str(item) for item in list(routing.get('route_history_family_ids') or []) if str(item)],
            'sla_deadline_target': str(routing.get('sla_deadline_target') or '').strip(),
            'time_to_breach_s': routing.get('time_to_breach_s'),
            'predicted_wait_time_s': routing.get('predicted_wait_time_s'),
            'predicted_sla_margin_s': routing.get('predicted_sla_margin_s'),
            'predicted_sla_breach': bool(routing.get('predicted_sla_breach')),
            'breach_risk_score': float(routing.get('breach_risk_score') or 0.0),
            'breach_risk_level': str(routing.get('breach_risk_level') or '').strip(),
            'expected_service_time_s': int(routing.get('expected_service_time_s') or 0),
            'forecast_window_s': int(routing.get('forecast_window_s') or 0),
            'forecast_arrivals_count': int(routing.get('forecast_arrivals_count') or 0),
            'forecast_departures_count': int(routing.get('forecast_departures_count') or 0),
            'projected_active_count': int(routing.get('projected_active_count') or 0),
            'projected_load_ratio': float(routing.get('projected_load_ratio') or 0.0),
            'projected_wait_time_s': int(routing.get('projected_wait_time_s') or 0),
            'forecasted_over_capacity': bool(routing.get('forecasted_over_capacity')),
            'surge_predicted': bool(routing.get('surge_predicted')),
            'proactive_routing_eligible': bool(routing.get('proactive_routing_eligible')),
            'proactive_routing_applied': bool(routing.get('proactive_routing_applied')),
            'proactive_reason': str(routing.get('proactive_reason') or '').strip(),
            'expedite_eligible': bool(routing.get('expedite_eligible')),
            'expedite_reserved_capacity_borrowed': bool(routing.get('expedite_reserved_capacity_borrowed')),
            'expedite_applied': bool(routing.get('expedite_applied')),
            'expedite_reason': str(routing.get('expedite_reason') or '').strip(),
        }

    @staticmethod
    def _baseline_promotion_simulation_custody_handoff_projection(alert: dict[str, Any] | None) -> dict[str, Any]:
        handoffs = [dict(item) for item in list((dict(alert or {}).get('handoffs') or []))]
        handoffs.sort(key=lambda item: (float(item.get('handoff_at') or 0.0), str(item.get('handoff_id') or '')), reverse=True)
        pending_items = [item for item in handoffs if item.get('accepted_at') is None]
        latest = dict(handoffs[0] or {}) if handoffs else {}
        pending = dict(pending_items[0] or {}) if pending_items else {}
        accepted_count = sum(1 for item in handoffs if item.get('accepted_at') is not None)
        return {
            'count': len(handoffs),
            'accepted_count': accepted_count,
            'pending_count': len(pending_items),
            'pending': bool(pending),
            'latest_handoff_id': str(latest.get('handoff_id') or ''),
            'latest_handoff_at': latest.get('handoff_at'),
            'latest_handed_off_by': str(latest.get('handed_off_by') or ''),
            'latest_from_owner_id': str(latest.get('from_owner_id') or ''),
            'latest_to_owner_id': str(latest.get('to_owner_id') or ''),
            'latest_to_owner_role': str(latest.get('to_owner_role') or ''),
            'latest_to_queue_id': str(latest.get('to_queue_id') or ''),
            'latest_to_route_id': str(latest.get('to_route_id') or ''),
            'latest_reason': str(latest.get('reason') or ''),
            'active_handoff_id': str(pending.get('handoff_id') or ''),
            'pending_to_owner_id': str(pending.get('to_owner_id') or ''),
            'pending_to_owner_role': str(pending.get('to_owner_role') or ''),
            'pending_to_queue_id': str(pending.get('to_queue_id') or ''),
            'pending_to_route_id': str(pending.get('to_route_id') or ''),
            'pending_since': pending.get('handoff_at'),
            'accepted_at': latest.get('accepted_at'),
            'accepted_by': str(latest.get('accepted_by') or ''),
        }

    @staticmethod
    def _baseline_promotion_simulation_custody_sla_projection(
        alert: dict[str, Any] | None,
        policy: dict[str, Any] | None = None,
        *,
        now_ts: float | None = None,
    ) -> dict[str, Any]:
        payload = dict(alert or {})
        monitoring_policy = dict(policy or {})
        sla_policy = dict(monitoring_policy.get('sla_policy') or payload.get('sla_policy') or {})
        enabled = bool(sla_policy.get('enabled'))
        now_ts = float(now_ts if now_ts is not None else time.time())

        def _ts(value: Any) -> float | None:
            if value is None:
                return None
            try:
                return float(value)
            except Exception:
                return None

        def _first(values: list[Any]) -> float | None:
            numeric = [ts for ts in (_ts(value) for value in values) if ts is not None]
            return min(numeric) if numeric else None

        created_at = _ts(payload.get('created_at')) or now_ts
        acknowledged_at = _ts(payload.get('acknowledged_at'))
        claimed_at = _ts(((payload.get('ownership') or {}).get('claimed_at')) or payload.get('claimed_at'))
        assigned_at = _ts(((payload.get('ownership') or {}).get('assigned_at')) or payload.get('assigned_at'))
        resolved_at = _first([payload.get('resolved_at'), payload.get('recovered_at'), payload.get('cleared_at')])
        handoffs = [dict(item) for item in list(payload.get('handoffs') or [])]
        handoffs.sort(key=lambda item: (float(item.get('handoff_at') or 0.0), str(item.get('handoff_id') or '')), reverse=True)
        pending_handoff = next((item for item in handoffs if item.get('accepted_at') is None), {})
        warning_ratio = min(0.95, max(0.0, float(sla_policy.get('warning_ratio') or 0.8))) if enabled else 0.8

        def _target(name: str, target_s: int, *, start_ts: float | None, met_ts: float | None, applicable: bool = True) -> dict[str, Any]:
            result = {
                'name': name,
                'enabled': bool(enabled and target_s > 0 and applicable and start_ts is not None),
                'target_s': max(0, int(target_s or 0)),
                'status': 'disabled',
                'deadline': None,
                'met_at': met_ts,
                'remaining_s': None,
                'breached': False,
                'warning': False,
            }
            if not result['enabled']:
                result['status'] = 'disabled' if target_s <= 0 or not enabled else 'not_applicable'
                return result
            deadline = float(start_ts or now_ts) + float(target_s or 0)
            result['deadline'] = deadline
            if met_ts is not None:
                breached = float(met_ts) > deadline
                result['breached'] = breached
                result['status'] = 'breached' if breached else 'met'
                result['remaining_s'] = int(round(deadline - float(met_ts)))
                return result
            remaining = int(round(deadline - now_ts))
            result['remaining_s'] = remaining
            if remaining < 0:
                result['breached'] = True
                result['status'] = 'breached'
                return result
            elapsed_ratio = 0.0 if target_s <= 0 else max(0.0, min(1.0, (now_ts - float(start_ts or now_ts)) / float(target_s or 1)))
            if elapsed_ratio >= warning_ratio:
                result['warning'] = True
                result['status'] = 'warning'
            else:
                result['status'] = 'pending'
            return result

        acknowledge_target = _target(
            'acknowledge',
            int(sla_policy.get('acknowledge_s') or 0),
            start_ts=created_at,
            met_ts=_first([acknowledged_at, claimed_at]),
            applicable=bool(payload.get('active', False)),
        )
        claim_target = _target(
            'claim',
            int(sla_policy.get('claim_s') or 0),
            start_ts=created_at,
            met_ts=_first([claimed_at, assigned_at]) if str(((payload.get('ownership') or {}).get('owner_id') or '')).strip() else claimed_at,
            applicable=bool(payload.get('active', False)),
        )
        resolve_target = _target(
            'resolve',
            int(sla_policy.get('resolve_s') or 0),
            start_ts=created_at,
            met_ts=resolved_at,
            applicable=True,
        )
        handoff_target = _target(
            'handoff_accept',
            int(sla_policy.get('handoff_accept_s') or 0),
            start_ts=_ts(pending_handoff.get('handoff_at')),
            met_ts=_ts(pending_handoff.get('accepted_at')),
            applicable=bool(pending_handoff),
        )
        targets = [acknowledge_target, claim_target, resolve_target, handoff_target]
        breached_targets = [item['name'] for item in targets if bool(item.get('breached'))]
        warning_targets = [item['name'] for item in targets if bool(item.get('warning'))]
        pending_targets = [item['name'] for item in targets if str(item.get('status') or '') in {'pending', 'warning'}]
        next_deadlines = [float(item.get('deadline')) for item in targets if item.get('deadline') is not None and str(item.get('status') or '') in {'pending', 'warning'}]
        status = 'disabled'
        if enabled:
            if breached_targets:
                status = 'breached'
            elif warning_targets:
                status = 'warning'
            elif any(str(item.get('status') or '') == 'pending' for item in targets):
                status = 'pending'
            elif any(str(item.get('status') or '') == 'met' for item in targets):
                status = 'met'
            else:
                status = 'disabled'
        return {
            'enabled': enabled,
            'status': status,
            'evaluated_at': now_ts,
            'age_s': max(0, int(now_ts - created_at)),
            'breached': bool(breached_targets),
            'breached_targets': breached_targets,
            'warning_targets': warning_targets,
            'pending_targets': pending_targets,
            'next_deadline': (min(next_deadlines) if next_deadlines else None),
            'targets': {
                'acknowledge': acknowledge_target,
                'claim': claim_target,
                'resolve': resolve_target,
                'handoff_accept': handoff_target,
            },
        }

    def _apply_baseline_promotion_simulation_custody_route_to_alert(
        self,
        alert: dict[str, Any] | None,
        *,
        route: dict[str, Any] | None,
        actor: str,
        auto_assign: bool = False,
        preserve_owner: bool = True,
        source: str = 'routing_policy',
        manual_override: bool = False,
    ) -> tuple[dict[str, Any], bool]:
        updated = dict(alert or {})
        normalized_route = self._normalize_baseline_promotion_simulation_custody_route(dict(route or {}), index=0)
        ownership = dict(updated.get('ownership') or {})
        routing = dict(updated.get('routing') or {})
        previous_key = (
            str(routing.get('route_id') or ''),
            str(routing.get('queue_id') or ''),
            str(routing.get('owner_role') or ''),
            str(routing.get('owner_id') or ''),
            str(routing.get('target_path') or ''),
        )
        now_ts = time.time()
        if normalized_route:
            routing.update({
                'route_id': str(normalized_route.get('route_id') or ''),
                'route_label': str(normalized_route.get('label') or ''),
                'queue_id': str(normalized_route.get('queue_id') or ''),
                'queue_label': str(normalized_route.get('queue_label') or ''),
                'owner_role': str(normalized_route.get('owner_role') or ''),
                'owner_id': str(normalized_route.get('owner_id') or ''),
                'target_path': str(normalized_route.get('target_path') or ''),
                'severity': str(normalized_route.get('severity') or ''),
                'updated_at': now_ts,
                'updated_by': str(actor or 'system'),
                'source': str(source or 'routing_policy'),
                'manual_override': bool(manual_override),
                'load_aware': bool(normalized_route.get('load_aware')),
                'selection_reason': str(normalized_route.get('selection_reason') or ''),
                'queue_active_count': int(normalized_route.get('queue_active_count') or 0),
                'queue_capacity': int(normalized_route.get('queue_capacity') or 0),
                'queue_available': normalized_route.get('queue_available'),
                'queue_load_ratio': float(normalized_route.get('queue_load_ratio') or 0.0),
                'queue_at_capacity': bool(normalized_route.get('queue_at_capacity')),
                'queue_over_capacity': bool(normalized_route.get('queue_over_capacity')),
                'queue_warning': bool(normalized_route.get('queue_warning')),
                'reservation_enabled': bool(normalized_route.get('reservation_enabled')),
                'reserved_capacity': int(normalized_route.get('reserved_capacity') or 0),
                'general_capacity': int(normalized_route.get('general_capacity') or 0),
                'general_available': normalized_route.get('general_available'),
                'reserved_available': normalized_route.get('reserved_available'),
                'reservation_eligible': bool(normalized_route.get('reservation_eligible')),
                'reservation_applied': bool(normalized_route.get('reservation_applied')),
                'lease_active': bool(normalized_route.get('lease_active')),
                'lease_expired': bool(normalized_route.get('lease_expired')),
                'leased_capacity': int(normalized_route.get('leased_capacity') or 0),
                'lease_available': normalized_route.get('lease_available'),
                'lease_expires_at': normalized_route.get('lease_expires_at'),
                'lease_reason': str(normalized_route.get('lease_reason') or ''),
                'lease_holder': str(normalized_route.get('lease_holder') or ''),
                'lease_id': str(normalized_route.get('lease_id') or ''),
                'lease_eligible': bool(normalized_route.get('lease_eligible')),
                'lease_applied': bool(normalized_route.get('lease_applied')),
                'starvation_lease_capacity_borrowed': bool(normalized_route.get('starvation_lease_capacity_borrowed')),
                'expedite_lease_capacity_borrowed': bool(normalized_route.get('expedite_lease_capacity_borrowed')),
                'temporary_hold_count': int(normalized_route.get('temporary_hold_count') or 0),
                'temporary_hold_capacity': int(normalized_route.get('temporary_hold_capacity') or 0),
                'temporary_hold_available': normalized_route.get('temporary_hold_available'),
                'temporary_hold_ids': [str(item) for item in list(normalized_route.get('temporary_hold_ids') or []) if str(item)],
                'temporary_hold_reasons': [str(item) for item in list(normalized_route.get('temporary_hold_reasons') or []) if str(item)],
                'temporary_hold_eligible': bool(normalized_route.get('temporary_hold_eligible')),
                'temporary_hold_applied': bool(normalized_route.get('temporary_hold_applied')),
                'starvation_temporary_hold_borrowed': bool(normalized_route.get('starvation_temporary_hold_borrowed')),
                'expedite_temporary_hold_borrowed': bool(normalized_route.get('expedite_temporary_hold_borrowed')),
                'expired_temporary_hold_count': int(normalized_route.get('expired_temporary_hold_count') or 0),
                'expired_temporary_hold_ids': [str(item) for item in list(normalized_route.get('expired_temporary_hold_ids') or []) if str(item)],
                'effective_capacity': int(normalized_route.get('effective_capacity') or 0),
                'alert_wait_age_s': int(normalized_route.get('alert_wait_age_s') or 0),
                'aging_applied': bool(normalized_route.get('aging_applied')),
                'starving': bool(normalized_route.get('starving')),
                'queue_oldest_alert_age_s': int(normalized_route.get('queue_oldest_alert_age_s') or 0),
                'queue_aged_alert_count': int(normalized_route.get('queue_aged_alert_count') or 0),
                'queue_starving_alert_count': int(normalized_route.get('queue_starving_alert_count') or 0),
                'starvation_reserved_capacity_borrowed': bool(normalized_route.get('starvation_reserved_capacity_borrowed')),
                'starvation_prevention_applied': bool(normalized_route.get('starvation_prevention_applied')),
                'starvation_prevention_reason': str(normalized_route.get('starvation_prevention_reason') or ''),
                'anti_thrashing_applied': bool(normalized_route.get('anti_thrashing_applied')),
                'anti_thrashing_reason': str(normalized_route.get('anti_thrashing_reason') or ''),
                'queue_family_id': str(normalized_route.get('queue_family_id') or normalized_route.get('queue_type') or ''),
                'queue_family_label': str(normalized_route.get('queue_family_label') or normalized_route.get('queue_family_id') or normalized_route.get('queue_type') or ''),
                'queue_family_enabled': bool(normalized_route.get('queue_family_enabled')),
                'queue_family_member_count': int(normalized_route.get('queue_family_member_count') or 0),
                'recent_queue_hop_count': int(normalized_route.get('recent_queue_hop_count') or 0),
                'recent_family_hop_count': int(normalized_route.get('recent_family_hop_count') or 0),
                'family_hysteresis_applied': bool(normalized_route.get('family_hysteresis_applied')),
                'family_hysteresis_reason': str(normalized_route.get('family_hysteresis_reason') or ''),
                'route_history_queue_ids': [str(item) for item in list(normalized_route.get('route_history_queue_ids') or []) if str(item)],
                'route_history_family_ids': [str(item) for item in list(normalized_route.get('route_history_family_ids') or []) if str(item)],
                'sla_deadline_target': str(normalized_route.get('sla_deadline_target') or ''),
                'time_to_breach_s': normalized_route.get('time_to_breach_s'),
                'predicted_wait_time_s': normalized_route.get('predicted_wait_time_s'),
                'predicted_sla_margin_s': normalized_route.get('predicted_sla_margin_s'),
                'predicted_sla_breach': bool(normalized_route.get('predicted_sla_breach')),
                'breach_risk_score': float(normalized_route.get('breach_risk_score') or 0.0),
                'breach_risk_level': str(normalized_route.get('breach_risk_level') or ''),
                'expected_service_time_s': int(normalized_route.get('expected_service_time_s') or 0),
                'expedite_eligible': bool(normalized_route.get('expedite_eligible')),
                'expedite_reserved_capacity_borrowed': bool(normalized_route.get('expedite_reserved_capacity_borrowed')),
                'expedite_applied': bool(normalized_route.get('expedite_applied')),
                'expedite_reason': str(normalized_route.get('expedite_reason') or ''),
            })
            if normalized_route.get('queue_id'):
                ownership['queue_id'] = str(normalized_route.get('queue_id') or '')
                ownership['queue_label'] = str(normalized_route.get('queue_label') or normalized_route.get('queue_id') or '')
            if normalized_route.get('owner_role'):
                ownership['owner_role'] = str(normalized_route.get('owner_role') or '')
            if not preserve_owner or not str(ownership.get('owner_id') or '').strip():
                owner_id = str(normalized_route.get('owner_id') or '').strip()
                if owner_id:
                    ownership['owner_id'] = owner_id
                    ownership['owner_display'] = str(normalized_route.get('owner_id') or owner_id)
                    ownership['assigned_at'] = ownership.get('assigned_at') or now_ts
                    ownership['assigned_by'] = ownership.get('assigned_by') or str(actor or 'system')
                    ownership['status'] = 'assigned'
                elif not str(ownership.get('owner_id') or '').strip():
                    ownership['status'] = 'queued' if str(ownership.get('queue_id') or ownership.get('owner_role') or '').strip() else 'unassigned'
            updated['routing'] = routing
        ownership.setdefault('status', 'queued' if str(ownership.get('queue_id') or ownership.get('owner_role') or '').strip() else ('assigned' if str(ownership.get('owner_id') or '').strip() else 'unassigned'))
        updated['ownership'] = ownership
        current_key = (
            str((updated.get('routing') or {}).get('route_id') or ''),
            str((updated.get('routing') or {}).get('queue_id') or ''),
            str((updated.get('routing') or {}).get('owner_role') or ''),
            str((updated.get('routing') or {}).get('owner_id') or ''),
            str((updated.get('routing') or {}).get('target_path') or ''),
        )
        route_changed = current_key != previous_key
        if route_changed:
            routing_state = dict(updated.get('routing') or {})
            history_limit = max(2, int(routing_state.get('family_history_limit') or 8))
            previous_history = [dict(item or {}) for item in list(routing_state.get('route_history') or []) if isinstance(item, dict)]
            history_entry = {
                'at': now_ts,
                'route_id': str(routing_state.get('route_id') or ''),
                'queue_id': str(routing_state.get('queue_id') or ''),
                'queue_family_id': str(routing_state.get('queue_family_id') or routing_state.get('queue_type') or ''),
                'selection_reason': str(routing_state.get('selection_reason') or ''),
                'source': str(routing_state.get('source') or ''),
            }
            previous_history.append(history_entry)
            routing_state['route_history'] = previous_history[-history_limit:]
            updated['routing'] = routing_state
        return updated, route_changed


    def _baseline_promotion_simulation_custody_guard(self, release: dict[str, Any] | None) -> dict[str, Any]:
        metadata = dict((release or {}).get('metadata') or {})
        promotion = dict(metadata.get('baseline_promotion') or {})
        guard = dict(promotion.get('simulation_custody_guard') or {})
        alerts = [dict(item) for item in list(promotion.get('simulation_custody_alerts') or [])]
        active_alert = next((item for item in alerts if bool(item.get('active'))), {})
        ownership = self._baseline_promotion_simulation_custody_ownership_projection(active_alert)
        routing = self._baseline_promotion_simulation_custody_routing_projection(active_alert)
        handoff = self._baseline_promotion_simulation_custody_handoff_projection(active_alert)
        sla = dict(active_alert.get('sla_state') or {})
        return {
            'blocked': bool(guard.get('blocked')),
            'reason': str(guard.get('reason') or ''),
            'reasons': [str(item) for item in list(guard.get('reasons') or []) if str(item)],
            'status': str(guard.get('status') or ('blocked' if guard.get('blocked') else 'clear')),
            'updated_at': guard.get('updated_at'),
            'updated_by': str(guard.get('updated_by') or ''),
            'active_alert_id': str(active_alert.get('alert_id') or ''),
            'notification_id': str(active_alert.get('notification_id') or ''),
            'alert_status': str(guard.get('alert_status') or self._baseline_promotion_simulation_custody_alert_status(active_alert) if active_alert else ''),
            'escalated': bool(guard.get('escalated')),
            'escalation_level': int(guard.get('escalation_level') or 0),
            'severity': str(guard.get('severity') or active_alert.get('severity') or ''),
            'suppressed': bool(guard.get('suppressed')),
            'suppression_reasons': [str(item) for item in list(guard.get('suppression_reasons') or []) if str(item)],
            'pending_escalation_level': int(guard.get('pending_escalation_level') or 0),
            'owner_id': str(guard.get('owner_id') or ownership.get('owner_id') or ''),
            'owner_role': str(guard.get('owner_role') or ownership.get('owner_role') or ''),
            'ownership_status': str(guard.get('ownership_status') or ownership.get('status') or ''),
            'queue_id': str(guard.get('queue_id') or ownership.get('queue_id') or routing.get('queue_id') or ''),
            'queue_label': str(guard.get('queue_label') or ownership.get('queue_label') or routing.get('queue_label') or ''),
            'route_id': str(guard.get('route_id') or routing.get('route_id') or ''),
            'route_label': str(guard.get('route_label') or routing.get('route_label') or ''),
            'queue_active_count': int(guard.get('queue_active_count') or routing.get('queue_active_count') or 0),
            'queue_capacity': int(guard.get('queue_capacity') or routing.get('queue_capacity') or 0),
            'queue_available': guard.get('queue_available', routing.get('queue_available')),
            'queue_load_ratio': float(guard.get('queue_load_ratio') or routing.get('queue_load_ratio') or 0.0),
            'queue_at_capacity': bool(guard.get('queue_at_capacity', routing.get('queue_at_capacity'))),
            'queue_over_capacity': bool(guard.get('queue_over_capacity', routing.get('queue_over_capacity'))),
            'queue_warning': bool(guard.get('queue_warning', routing.get('queue_warning'))),
            'reservation_enabled': bool(guard.get('reservation_enabled', routing.get('reservation_enabled'))),
            'reserved_capacity': int(guard.get('reserved_capacity') or routing.get('reserved_capacity') or 0),
            'general_capacity': int(guard.get('general_capacity') or routing.get('general_capacity') or 0),
            'general_available': guard.get('general_available', routing.get('general_available')),
            'reserved_available': guard.get('reserved_available', routing.get('reserved_available')),
            'reservation_eligible': bool(guard.get('reservation_eligible', routing.get('reservation_eligible'))),
            'reservation_applied': bool(guard.get('reservation_applied', routing.get('reservation_applied'))),
            'lease_active': bool(guard.get('lease_active', routing.get('lease_active'))),
            'lease_expired': bool(guard.get('lease_expired', routing.get('lease_expired'))),
            'leased_capacity': int(guard.get('leased_capacity') or routing.get('leased_capacity') or 0),
            'lease_available': guard.get('lease_available', routing.get('lease_available')),
            'lease_expires_at': guard.get('lease_expires_at', routing.get('lease_expires_at')),
            'lease_reason': str(guard.get('lease_reason') or routing.get('lease_reason') or ''),
            'lease_holder': str(guard.get('lease_holder') or routing.get('lease_holder') or ''),
            'lease_id': str(guard.get('lease_id') or routing.get('lease_id') or ''),
            'lease_eligible': bool(guard.get('lease_eligible', routing.get('lease_eligible'))),
            'lease_applied': bool(guard.get('lease_applied', routing.get('lease_applied'))),
            'starvation_lease_capacity_borrowed': bool(guard.get('starvation_lease_capacity_borrowed', routing.get('starvation_lease_capacity_borrowed'))),
            'expedite_lease_capacity_borrowed': bool(guard.get('expedite_lease_capacity_borrowed', routing.get('expedite_lease_capacity_borrowed'))),
            'temporary_hold_count': int(guard.get('temporary_hold_count') or routing.get('temporary_hold_count') or 0),
            'temporary_hold_capacity': int(guard.get('temporary_hold_capacity') or routing.get('temporary_hold_capacity') or 0),
            'temporary_hold_available': guard.get('temporary_hold_available', routing.get('temporary_hold_available')),
            'temporary_hold_ids': [str(item) for item in list(guard.get('temporary_hold_ids') or routing.get('temporary_hold_ids') or []) if str(item)],
            'temporary_hold_reasons': [str(item) for item in list(guard.get('temporary_hold_reasons') or routing.get('temporary_hold_reasons') or []) if str(item)],
            'temporary_hold_eligible': bool(guard.get('temporary_hold_eligible', routing.get('temporary_hold_eligible'))),
            'temporary_hold_applied': bool(guard.get('temporary_hold_applied', routing.get('temporary_hold_applied'))),
            'starvation_temporary_hold_borrowed': bool(guard.get('starvation_temporary_hold_borrowed', routing.get('starvation_temporary_hold_borrowed'))),
            'expedite_temporary_hold_borrowed': bool(guard.get('expedite_temporary_hold_borrowed', routing.get('expedite_temporary_hold_borrowed'))),
            'expired_temporary_hold_count': int(guard.get('expired_temporary_hold_count') or routing.get('expired_temporary_hold_count') or 0),
            'expired_temporary_hold_ids': [str(item) for item in list(guard.get('expired_temporary_hold_ids') or routing.get('expired_temporary_hold_ids') or []) if str(item)],
            'effective_capacity': int(guard.get('effective_capacity') or routing.get('effective_capacity') or 0),
            'alert_wait_age_s': int(guard.get('alert_wait_age_s') or routing.get('alert_wait_age_s') or 0),
            'aging_applied': bool(guard.get('aging_applied', routing.get('aging_applied'))),
            'starving': bool(guard.get('starving', routing.get('starving'))),
            'queue_oldest_alert_age_s': int(guard.get('queue_oldest_alert_age_s') or routing.get('queue_oldest_alert_age_s') or 0),
            'queue_aged_alert_count': int(guard.get('queue_aged_alert_count') or routing.get('queue_aged_alert_count') or 0),
            'queue_starving_alert_count': int(guard.get('queue_starving_alert_count') or routing.get('queue_starving_alert_count') or 0),
            'starvation_reserved_capacity_borrowed': bool(guard.get('starvation_reserved_capacity_borrowed', routing.get('starvation_reserved_capacity_borrowed'))),
            'starvation_prevention_applied': bool(guard.get('starvation_prevention_applied', routing.get('starvation_prevention_applied'))),
            'starvation_prevention_reason': str(guard.get('starvation_prevention_reason') or routing.get('starvation_prevention_reason') or ''),
            'load_aware_routing': bool(guard.get('load_aware_routing', routing.get('load_aware'))),
            'selection_reason': str(guard.get('selection_reason') or routing.get('selection_reason') or ''),
            'anti_thrashing_applied': bool(guard.get('anti_thrashing_applied', routing.get('anti_thrashing_applied'))),
            'anti_thrashing_reason': str(guard.get('anti_thrashing_reason') or routing.get('anti_thrashing_reason') or ''),
            'queue_family_id': str(guard.get('queue_family_id') or routing.get('queue_family_id') or routing.get('queue_type') or ''),
            'queue_family_label': str(guard.get('queue_family_label') or routing.get('queue_family_label') or routing.get('queue_family_id') or routing.get('queue_type') or ''),
            'queue_family_enabled': bool(guard.get('queue_family_enabled', routing.get('queue_family_enabled'))),
            'queue_family_member_count': int(guard.get('queue_family_member_count') or routing.get('queue_family_member_count') or 0),
            'recent_queue_hop_count': int(guard.get('recent_queue_hop_count') or routing.get('recent_queue_hop_count') or 0),
            'recent_family_hop_count': int(guard.get('recent_family_hop_count') or routing.get('recent_family_hop_count') or 0),
            'family_hysteresis_applied': bool(guard.get('family_hysteresis_applied', routing.get('family_hysteresis_applied'))),
            'family_hysteresis_reason': str(guard.get('family_hysteresis_reason') or routing.get('family_hysteresis_reason') or ''),
            'route_history_queue_ids': [str(item) for item in list(guard.get('route_history_queue_ids') or routing.get('route_history_queue_ids') or []) if str(item)],
            'route_history_family_ids': [str(item) for item in list(guard.get('route_history_family_ids') or routing.get('route_history_family_ids') or []) if str(item)],
            'sla_deadline_target': str(guard.get('sla_deadline_target') or routing.get('sla_deadline_target') or ''),
            'time_to_breach_s': guard.get('time_to_breach_s', routing.get('time_to_breach_s')),
            'predicted_wait_time_s': guard.get('predicted_wait_time_s', routing.get('predicted_wait_time_s')),
            'predicted_sla_margin_s': guard.get('predicted_sla_margin_s', routing.get('predicted_sla_margin_s')),
            'predicted_sla_breach': bool(guard.get('predicted_sla_breach', routing.get('predicted_sla_breach'))),
            'breach_risk_score': float(guard.get('breach_risk_score') or routing.get('breach_risk_score') or 0.0),
            'breach_risk_level': str(guard.get('breach_risk_level') or routing.get('breach_risk_level') or ''),
            'expected_service_time_s': int(guard.get('expected_service_time_s') or routing.get('expected_service_time_s') or 0),
            'expedite_eligible': bool(guard.get('expedite_eligible', routing.get('expedite_eligible'))),
            'expedite_reserved_capacity_borrowed': bool(guard.get('expedite_reserved_capacity_borrowed', routing.get('expedite_reserved_capacity_borrowed'))),
            'expedite_applied': bool(guard.get('expedite_applied', routing.get('expedite_applied'))),
            'expedite_reason': str(guard.get('expedite_reason') or routing.get('expedite_reason') or ''),
            'handoff_pending': bool(guard.get('handoff_pending', handoff.get('pending'))),
            'handoff_count': int(guard.get('handoff_count') or handoff.get('count') or 0),
            'sla_status': str(guard.get('sla_status') or sla.get('status') or ''),
            'sla_breached': bool(guard.get('sla_breached', sla.get('breached'))),
            'sla_breached_targets': [str(item) for item in list(guard.get('sla_breached_targets') or sla.get('breached_targets') or []) if str(item)],
            'sla_warning_targets': [str(item) for item in list(guard.get('sla_warning_targets') or sla.get('warning_targets') or []) if str(item)],
            'sla_rerouted': bool(guard.get('sla_rerouted')),
            'sla_reroute_status': str(guard.get('sla_reroute_status') or ''),
            'sla_reroute_count': int(guard.get('sla_reroute_count') or 0),
            'team_queue_id': str(guard.get('team_queue_id') or ''),
        }

    def _baseline_promotion_simulation_custody_alerts(self, release: dict[str, Any] | None) -> list[dict[str, Any]]:
        metadata = dict((release or {}).get('metadata') or {})
        promotion = dict(metadata.get('baseline_promotion') or {})
        alerts = [dict(item) for item in list(promotion.get('simulation_custody_alerts') or [])]
        policy = self._baseline_promotion_simulation_custody_monitoring_policy_for_release(release)
        now_ts = time.time()
        for item in alerts:
            item['status'] = self._baseline_promotion_simulation_custody_alert_status(item, now_ts=now_ts)
            item['ownership'] = self._baseline_promotion_simulation_custody_ownership_projection(item)
            item['routing'] = self._baseline_promotion_simulation_custody_routing_projection(item)
            item['handoff'] = self._baseline_promotion_simulation_custody_handoff_projection(item)
            item['sla'] = self._baseline_promotion_simulation_custody_sla_projection(item, policy, now_ts=now_ts)
            item['sla_state'] = dict(item.get('sla_state') or item['sla'])
            item['sla_routing_state'] = dict(item.get('sla_routing_state') or {})
        alerts.sort(key=lambda item: (float(item.get('created_at') or 0.0), str(item.get('alert_id') or '')), reverse=True)
        return alerts

    @staticmethod
    def _baseline_promotion_simulation_custody_alert_status(alert: dict[str, Any] | None, *, now_ts: float | None = None) -> str:
        payload = dict(alert or {})
        now_ts = float(now_ts if now_ts is not None else time.time())
        if bool(payload.get('active')):
            muted_until = payload.get('muted_until')
            try:
                muted_until_ts = float(muted_until) if muted_until is not None else None
            except Exception:
                muted_until_ts = None
            if muted_until_ts is not None and muted_until_ts > now_ts:
                return 'muted'
            if payload.get('acknowledged_at') is not None:
                return 'acknowledged'
            return str(payload.get('status') or 'open').strip() or 'open'
        if payload.get('recovered_at') is not None:
            return 'recovered'
        if payload.get('resolved_at') is not None or payload.get('cleared_at') is not None:
            return 'resolved'
        return str(payload.get('status') or 'closed').strip() or 'closed'

    def _baseline_promotion_simulation_custody_alerts_summary(self, alerts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        payload = [dict(item) for item in list(alerts or [])]
        active_count = sum(1 for item in payload if bool(item.get('active')))
        open_count = 0
        acknowledged_count = 0
        muted_count = 0
        resolved_count = 0
        recovered_count = 0
        suppressed_count = 0
        escalated_count = 0
        active_escalated_count = 0
        active_suppressed_count = 0
        critical_count = 0
        pending_escalation_count = 0
        owned_count = 0
        active_owned_count = 0
        claimed_count = 0
        active_claimed_count = 0
        unassigned_count = 0
        active_unowned_count = 0
        routed_count = 0
        queued_count = 0
        handoff_count = 0
        pending_handoff_count = 0
        active_handoff_pending_count = 0
        sla_breached_count = 0
        active_sla_breached_count = 0
        sla_warning_count = 0
        sla_rerouted_count = 0
        active_sla_rerouted_count = 0
        team_queue_alert_count = 0
        active_team_queue_alert_count = 0
        queue_at_capacity_count = 0
        active_queue_at_capacity_count = 0
        queue_over_capacity_count = 0
        active_queue_over_capacity_count = 0
        load_aware_routed_count = 0
        active_load_aware_routed_count = 0
        reservation_protected_alert_count = 0
        active_reservation_protected_alert_count = 0
        lease_protected_alert_count = 0
        active_lease_protected_alert_count = 0
        temporary_hold_protected_alert_count = 0
        active_temporary_hold_protected_alert_count = 0
        anti_thrashing_kept_alert_count = 0
        active_anti_thrashing_kept_alert_count = 0
        queue_family_alert_count = 0
        active_queue_family_alert_count = 0
        family_hysteresis_kept_alert_count = 0
        active_family_hysteresis_kept_alert_count = 0
        aging_alert_count = 0
        active_aging_alert_count = 0
        starving_alert_count = 0
        active_starving_alert_count = 0
        starvation_prevented_alert_count = 0
        active_starvation_prevented_alert_count = 0
        alerts_at_risk_count = 0
        active_alerts_at_risk_count = 0
        predicted_sla_breach_count = 0
        active_predicted_sla_breach_count = 0
        expedite_routed_alert_count = 0
        active_expedite_routed_alert_count = 0
        proactive_routed_alert_count = 0
        active_proactive_routed_alert_count = 0
        forecasted_surge_alert_count = 0
        active_forecasted_surge_alert_count = 0
        overload_governed_alert_count = 0
        active_overload_governed_alert_count = 0
        overload_blocked_alert_count = 0
        active_overload_blocked_alert_count = 0
        admission_deferred_alert_count = 0
        active_admission_deferred_alert_count = 0
        manual_gate_alert_count = 0
        active_manual_gate_alert_count = 0
        queue_counts: dict[str, int] = {}
        owner_counts: dict[str, int] = {}
        for item in payload:
            status = self._baseline_promotion_simulation_custody_alert_status(item)
            if status == 'muted':
                muted_count += 1
            elif status == 'acknowledged':
                acknowledged_count += 1
            elif status == 'recovered':
                recovered_count += 1
            elif status == 'resolved':
                resolved_count += 1
            elif status == 'open':
                open_count += 1
            suppression_state = dict(item.get('suppression_state') or {})
            suppressed = bool(suppression_state.get('suppressed')) or bool(item.get('notification_suppressed'))
            if suppressed:
                suppressed_count += 1
                if bool(item.get('active')):
                    active_suppressed_count += 1
            escalation_count = int(item.get('escalation_count') or len(list(item.get('escalations') or [])) or 0)
            if escalation_count > 0 or int(item.get('escalation_level') or 0) > 0:
                escalated_count += 1
                if bool(item.get('active')):
                    active_escalated_count += 1
            if str(item.get('severity') or '').strip().lower() in {'critical', 'high'}:
                critical_count += 1
            if int(suppression_state.get('pending_escalation_level') or 0) > 0:
                pending_escalation_count += 1
            ownership = self._baseline_promotion_simulation_custody_ownership_projection(item)
            routing = self._baseline_promotion_simulation_custody_routing_projection(item)
            handoff = dict(item.get('handoff') or self._baseline_promotion_simulation_custody_handoff_projection(item))
            sla = dict(item.get('sla') or item.get('sla_state') or {})
            sla_routing = dict(item.get('sla_routing_state') or {})
            if int(handoff.get('count') or 0) > 0:
                handoff_count += 1
            if bool(handoff.get('pending')):
                pending_handoff_count += 1
                if bool(item.get('active')):
                    active_handoff_pending_count += 1
            if bool(sla.get('breached')):
                sla_breached_count += 1
                if bool(item.get('active')):
                    active_sla_breached_count += 1
            if str(sla.get('status') or '') == 'warning':
                sla_warning_count += 1
            if int(sla_routing.get('reroute_count') or 0) > 0 or str(routing.get('source') or '') == 'sla_breach_routing':
                sla_rerouted_count += 1
                if bool(item.get('active')):
                    active_sla_rerouted_count += 1
            if str(routing.get('source') or '') == 'sla_breach_routing':
                team_queue_alert_count += 1
                if bool(item.get('active')):
                    active_team_queue_alert_count += 1
            if bool(routing.get('queue_at_capacity')):
                queue_at_capacity_count += 1
                if bool(item.get('active')):
                    active_queue_at_capacity_count += 1
            if bool(routing.get('queue_over_capacity')):
                queue_over_capacity_count += 1
                if bool(item.get('active')):
                    active_queue_over_capacity_count += 1
            if bool(routing.get('load_aware')):
                load_aware_routed_count += 1
                if bool(item.get('active')):
                    active_load_aware_routed_count += 1
            if bool(routing.get('reservation_applied')):
                reservation_protected_alert_count += 1
                if bool(item.get('active')):
                    active_reservation_protected_alert_count += 1
            if bool(routing.get('lease_applied')):
                lease_protected_alert_count += 1
                if bool(item.get('active')):
                    active_lease_protected_alert_count += 1
            if bool(routing.get('temporary_hold_applied')):
                temporary_hold_protected_alert_count += 1
                if bool(item.get('active')):
                    active_temporary_hold_protected_alert_count += 1
            if bool(routing.get('anti_thrashing_applied')):
                anti_thrashing_kept_alert_count += 1
                if bool(item.get('active')):
                    active_anti_thrashing_kept_alert_count += 1
            if str(routing.get('queue_family_id') or '').strip():
                queue_family_alert_count += 1
                if bool(item.get('active')):
                    active_queue_family_alert_count += 1
            if bool(routing.get('family_hysteresis_applied')):
                family_hysteresis_kept_alert_count += 1
                if bool(item.get('active')):
                    active_family_hysteresis_kept_alert_count += 1
            if bool(routing.get('aging_applied')):
                aging_alert_count += 1
                if bool(item.get('active')):
                    active_aging_alert_count += 1
            if bool(routing.get('starving')):
                starving_alert_count += 1
                if bool(item.get('active')):
                    active_starving_alert_count += 1
            if bool(routing.get('starvation_prevention_applied')):
                starvation_prevented_alert_count += 1
                if bool(item.get('active')):
                    active_starvation_prevented_alert_count += 1
            if bool(sla.get('status') in {'warning', 'breached'} or routing.get('expedite_eligible')):
                alerts_at_risk_count += 1
                if bool(item.get('active')):
                    active_alerts_at_risk_count += 1
            if bool(routing.get('predicted_sla_breach')):
                predicted_sla_breach_count += 1
                if bool(item.get('active')):
                    active_predicted_sla_breach_count += 1
            if bool(routing.get('expedite_applied')):
                expedite_routed_alert_count += 1
                if bool(item.get('active')):
                    active_expedite_routed_alert_count += 1
            if bool(routing.get('proactive_routing_applied')):
                proactive_routed_alert_count += 1
                if bool(item.get('active')):
                    active_proactive_routed_alert_count += 1
            if bool(routing.get('surge_predicted')):
                forecasted_surge_alert_count += 1
                if bool(item.get('active')):
                    active_forecasted_surge_alert_count += 1
            if bool(routing.get('overload_governance_applied')):
                overload_governed_alert_count += 1
                if bool(item.get('active')):
                    active_overload_governed_alert_count += 1
            if bool(routing.get('admission_blocked')):
                overload_blocked_alert_count += 1
                if bool(item.get('active')):
                    active_overload_blocked_alert_count += 1
            if str(routing.get('admission_decision') or '') == 'defer':
                admission_deferred_alert_count += 1
                if bool(item.get('active')):
                    active_admission_deferred_alert_count += 1
            if str(routing.get('admission_decision') or '') == 'manual_gate':
                manual_gate_alert_count += 1
                if bool(item.get('active')):
                    active_manual_gate_alert_count += 1
            owner_id = str(ownership.get('owner_id') or '').strip()
            queue_id = str(ownership.get('queue_id') or routing.get('queue_id') or '').strip()
            owned = bool(owner_id)
            if owned:
                owned_count += 1
                owner_counts[owner_id] = owner_counts.get(owner_id, 0) + 1
                if bool(item.get('active')):
                    active_owned_count += 1
            else:
                unassigned_count += 1
                if bool(item.get('active')):
                    active_unowned_count += 1
            if ownership.get('status') == 'claimed':
                claimed_count += 1
                if bool(item.get('active')):
                    active_claimed_count += 1
            if queue_id:
                queued_count += 1
                queue_counts[queue_id] = queue_counts.get(queue_id, 0) + 1
            if str(routing.get('route_id') or '').strip() or queue_id:
                routed_count += 1
        latest = dict(payload[0] or {}) if payload else {}
        latest_suppression = dict(latest.get('suppression_state') or {}) if latest else {}
        latest_ownership = self._baseline_promotion_simulation_custody_ownership_projection(latest) if latest else {}
        latest_routing = self._baseline_promotion_simulation_custody_routing_projection(latest) if latest else {}
        latest_handoff = dict(latest.get('handoff') or self._baseline_promotion_simulation_custody_handoff_projection(latest)) if latest else {}
        latest_sla = dict(latest.get('sla') or latest.get('sla_state') or {}) if latest else {}
        return {
            'count': len(payload),
            'active_count': active_count,
            'open_count': open_count,
            'acknowledged_count': acknowledged_count,
            'muted_count': muted_count,
            'resolved_count': resolved_count,
            'recovered_count': recovered_count,
            'suppressed_count': suppressed_count,
            'active_suppressed_count': active_suppressed_count,
            'escalated_count': escalated_count,
            'active_escalated_count': active_escalated_count,
            'critical_count': critical_count,
            'pending_escalation_count': pending_escalation_count,
            'owned_count': owned_count,
            'active_owned_count': active_owned_count,
            'claimed_count': claimed_count,
            'active_claimed_count': active_claimed_count,
            'unassigned_count': unassigned_count,
            'active_unowned_count': active_unowned_count,
            'queued_count': queued_count,
            'routed_count': routed_count,
            'handoff_count': handoff_count,
            'pending_handoff_count': pending_handoff_count,
            'active_handoff_pending_count': active_handoff_pending_count,
            'sla_breached_count': sla_breached_count,
            'active_sla_breached_count': active_sla_breached_count,
            'sla_warning_count': sla_warning_count,
            'sla_rerouted_count': sla_rerouted_count,
            'active_sla_rerouted_count': active_sla_rerouted_count,
            'team_queue_alert_count': team_queue_alert_count,
            'active_team_queue_alert_count': active_team_queue_alert_count,
            'queue_at_capacity_count': queue_at_capacity_count,
            'active_queue_at_capacity_count': active_queue_at_capacity_count,
            'queue_over_capacity_count': queue_over_capacity_count,
            'active_queue_over_capacity_count': active_queue_over_capacity_count,
            'load_aware_routed_count': load_aware_routed_count,
            'active_load_aware_routed_count': active_load_aware_routed_count,
            'reservation_protected_alert_count': reservation_protected_alert_count,
            'active_reservation_protected_alert_count': active_reservation_protected_alert_count,
            'lease_protected_alert_count': lease_protected_alert_count,
            'active_lease_protected_alert_count': active_lease_protected_alert_count,
            'temporary_hold_protected_alert_count': temporary_hold_protected_alert_count,
            'active_temporary_hold_protected_alert_count': active_temporary_hold_protected_alert_count,
            'anti_thrashing_kept_alert_count': anti_thrashing_kept_alert_count,
            'active_anti_thrashing_kept_alert_count': active_anti_thrashing_kept_alert_count,
            'queue_family_alert_count': queue_family_alert_count,
            'active_queue_family_alert_count': active_queue_family_alert_count,
            'family_hysteresis_kept_alert_count': family_hysteresis_kept_alert_count,
            'active_family_hysteresis_kept_alert_count': active_family_hysteresis_kept_alert_count,
            'aging_alert_count': aging_alert_count,
            'active_aging_alert_count': active_aging_alert_count,
            'starving_alert_count': starving_alert_count,
            'active_starving_alert_count': active_starving_alert_count,
            'starvation_prevented_alert_count': starvation_prevented_alert_count,
            'active_starvation_prevented_alert_count': active_starvation_prevented_alert_count,
            'alerts_at_risk_count': alerts_at_risk_count,
            'active_alerts_at_risk_count': active_alerts_at_risk_count,
            'predicted_sla_breach_count': predicted_sla_breach_count,
            'active_predicted_sla_breach_count': active_predicted_sla_breach_count,
            'expedite_routed_alert_count': expedite_routed_alert_count,
            'active_expedite_routed_alert_count': active_expedite_routed_alert_count,
            'proactive_routed_alert_count': proactive_routed_alert_count,
            'active_proactive_routed_alert_count': active_proactive_routed_alert_count,
            'forecasted_surge_alert_count': forecasted_surge_alert_count,
            'active_forecasted_surge_alert_count': active_forecasted_surge_alert_count,
            'overload_governed_alert_count': overload_governed_alert_count,
            'active_overload_governed_alert_count': active_overload_governed_alert_count,
            'overload_blocked_alert_count': overload_blocked_alert_count,
            'active_overload_blocked_alert_count': active_overload_blocked_alert_count,
            'admission_deferred_alert_count': admission_deferred_alert_count,
            'active_admission_deferred_alert_count': active_admission_deferred_alert_count,
            'manual_gate_alert_count': manual_gate_alert_count,
            'active_manual_gate_alert_count': active_manual_gate_alert_count,
            'queue_counts': queue_counts,
            'owner_counts': owner_counts,
            'latest_alert_id': str(latest.get('alert_id') or ''),
            'latest_status': self._baseline_promotion_simulation_custody_alert_status(latest) if latest else '',
            'latest_notification_id': str(latest.get('last_notification_id') or latest.get('notification_id') or ''),
            'latest_escalation_level': int(latest.get('escalation_level') or 0),
            'latest_severity': str(latest.get('severity') or ''),
            'latest_suppressed': bool(latest_suppression.get('suppressed')),
            'latest_owner_id': str(latest_ownership.get('owner_id') or ''),
            'latest_owner_role': str(latest_ownership.get('owner_role') or ''),
            'latest_queue_id': str(latest_ownership.get('queue_id') or latest_routing.get('queue_id') or ''),
            'latest_route_id': str(latest_routing.get('route_id') or ''),
            'latest_handoff_pending': bool(latest_handoff.get('pending')),
            'latest_handoff_id': str(latest_handoff.get('active_handoff_id') or latest_handoff.get('latest_handoff_id') or ''),
            'latest_sla_status': str(latest_sla.get('status') or ''),
            'latest_sla_breached': bool(latest_sla.get('breached')),
            'latest_sla_rerouted': bool((dict(latest.get('sla_routing_state') or {}).get('reroute_count')) or str((latest.get('routing') or {}).get('source') or '') == 'sla_breach_routing'),
            'latest_team_queue_id': str((latest.get('sla_routing_state') or {}).get('last_queue_id') or (latest_routing.get('queue_id') or '')),
        }

    def _evaluate_baseline_promotion_simulation_custody_alert_governance(
        self,
        gw,
        *,
        release: dict[str, Any],
        actor: str,
        policy: dict[str, Any] | None = None,
        reconciliation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        policy = self._normalize_baseline_promotion_simulation_custody_monitoring_policy(
            dict(policy or self._baseline_promotion_simulation_custody_monitoring_policy_for_release(release))
        )
        metadata = dict((release or {}).get('metadata') or {})
        promotion = dict(metadata.get('baseline_promotion') or {})
        alerts = [dict(item) for item in list(promotion.get('simulation_custody_alerts') or [])]
        current_reconciliation = dict(reconciliation or promotion.get('current_simulation_evidence_reconciliation') or {})
        summary = dict(current_reconciliation.get('summary') or {})
        drifted = str(summary.get('overall_status') or '') == 'drifted'
        now_ts = time.time()
        active_alert_index = next((index for index, item in enumerate(alerts) if bool(item.get('active'))), None)
        if active_alert_index is None or not bool(policy.get('enabled')) or not drifted:
            guard = dict(promotion.get('simulation_custody_guard') or {})
            return {
                'release': release,
                'policy': policy,
                'alerts': alerts,
                'alerts_summary': self._baseline_promotion_simulation_custody_alerts_summary(alerts),
                'guard': guard,
                'updated': False,
                'escalated': False,
                'routed': False,
            }
        alert = dict(alerts[active_alert_index] or {})
        queue_state = self._baseline_promotion_simulation_custody_queue_capacity_state(
            gw,
            release=release,
            policy=policy,
            exclude_alert_id=str(alert.get('alert_id') or ''),
        )
        current_status = self._baseline_promotion_simulation_custody_alert_status(alert, now_ts=now_ts)
        suppression_reasons: list[str] = []
        if current_status == 'muted' and bool(policy.get('suppress_while_muted')):
            suppression_reasons.append('muted')
        if current_status == 'acknowledged' and bool(policy.get('suppress_while_acknowledged')):
            suppression_reasons.append('acknowledged')
        suppression_window_s = max(0, int(policy.get('suppression_window_s') or 0))
        last_notification_at = None
        try:
            last_notification_at = float(alert.get('last_notification_at')) if alert.get('last_notification_at') is not None else None
        except Exception:
            last_notification_at = None
        window_until = None
        if suppression_window_s > 0 and last_notification_at is not None and (now_ts - last_notification_at) < suppression_window_s:
            suppression_reasons.append('notification_window')
            window_until = last_notification_at + suppression_window_s
        suppression_state = dict(alert.get('suppression_state') or {})
        previously_suppressed = bool(suppression_state.get('suppressed'))
        suppression_state.update({
            'suppressed': bool(suppression_reasons),
            'reasons': suppression_reasons,
            'evaluated_at': now_ts,
            'window_until': window_until,
            'last_notification_at': last_notification_at,
        })
        if bool(suppression_reasons):
            suppression_state['last_suppressed_at'] = now_ts
        levels = [dict(item) for item in list(policy.get('escalation_levels') or [])]
        eligible_level = {}
        highest_recorded_level = max([int((item or {}).get('level') or 0) for item in list(alert.get('escalations') or [])] + [int(alert.get('escalation_level') or 0)])
        if bool(policy.get('escalation_enabled')) and levels:
            try:
                alert_created_at = float(alert.get('created_at') or now_ts)
            except Exception:
                alert_created_at = now_ts
            alert_age_s = max(0, int(now_ts - alert_created_at))
            for level in levels:
                if alert_age_s >= int(level.get('after_s') or 0):
                    eligible_level = level
            eligible_level_no = int(eligible_level.get('level') or 0)
            if eligible_level_no > highest_recorded_level:
                pending_route = self._baseline_promotion_simulation_custody_route_for_alert(
                    policy,
                    {
                        **alert,
                        'escalation_level': eligible_level_no,
                        'severity': str(eligible_level.get('severity') or alert.get('severity') or ''),
                    },
                    queue_state=queue_state,
                )
                suppression_state['pending_escalation_level'] = eligible_level_no
                suppression_state['pending_escalation_label'] = str(eligible_level.get('label') or '')
                suppression_state['pending_route_id'] = str(pending_route.get('route_id') or '')
                suppression_state['pending_queue_id'] = str(pending_route.get('queue_id') or '')
                suppression_state['pending_owner_role'] = str(pending_route.get('owner_role') or '')
            else:
                for key in ('pending_escalation_level', 'pending_escalation_label', 'pending_route_id', 'pending_queue_id', 'pending_owner_role'):
                    suppression_state.pop(key, None)
        else:
            for key in ('pending_escalation_level', 'pending_escalation_label', 'pending_route_id', 'pending_queue_id', 'pending_owner_role'):
                suppression_state.pop(key, None)
        alert['notification_suppressed'] = bool(suppression_reasons)
        alert['suppression_state'] = suppression_state
        if bool(suppression_reasons) and not previously_suppressed:
            promotion = self._append_baseline_promotion_timeline_event(
                promotion,
                kind='monitoring',
                label='baseline_promotion_simulation_custody_alert_suppressed',
                actor=str(actor or 'system'),
                alert_id=str(alert.get('alert_id') or ''),
                reasons=list(suppression_reasons),
            )
        if (not bool(suppression_reasons)) and previously_suppressed:
            promotion = self._append_baseline_promotion_timeline_event(
                promotion,
                kind='monitoring',
                label='baseline_promotion_simulation_custody_alert_unsuppressed',
                actor=str(actor or 'system'),
                alert_id=str(alert.get('alert_id') or ''),
            )
        escalated = False
        if bool(policy.get('escalation_enabled')) and eligible_level and int(eligible_level.get('level') or 0) > highest_recorded_level:
            escalation_count = len(list(alert.get('escalations') or []))
            max_escalations = max(1, int(policy.get('max_escalations') or max(len(levels), 1)))
            if escalation_count < max_escalations and not bool(suppression_reasons) and bool(policy.get('notify_on_escalation', True)):
                route_preview = self._baseline_promotion_simulation_custody_route_for_alert(
                    policy,
                    {
                        **alert,
                        'escalation_level': int(eligible_level.get('level') or 0),
                        'severity': str(eligible_level.get('severity') or alert.get('severity') or 'critical'),
                    },
                    queue_state=queue_state,
                )
                notification = gw.audit.create_app_notification(
                    category='operator',
                    title='Baseline simulation custody drift escalated',
                    body=f"Custody drift escalated for baseline promotion {str(release.get('release_id') or '').strip()} to {str(eligible_level.get('label') or '').strip() or 'an elevated severity' }.",
                    target_path=str(route_preview.get('target_path') or eligible_level.get('target_path') or policy.get('escalation_target_path') or policy.get('target_path') or '/ui/?tab=operator'),
                    created_by=str(actor or 'system'),
                    metadata={
                        'kind': 'baseline_promotion_simulation_custody_escalated',
                        'promotion_id': str(release.get('release_id') or ''),
                        'reconciliation_id': str(current_reconciliation.get('reconciliation_id') or ''),
                        'alert_id': str(alert.get('alert_id') or ''),
                        'escalation_level': int(eligible_level.get('level') or 0),
                        'severity': str(eligible_level.get('severity') or alert.get('severity') or 'critical'),
                        'route_id': str(route_preview.get('route_id') or ''),
                        'queue_id': str(route_preview.get('queue_id') or ''),
                        'owner_role': str(route_preview.get('owner_role') or ''),
                    },
                    tenant_id=release.get('tenant_id'),
                    workspace_id=release.get('workspace_id'),
                    environment=release.get('environment'),
                )
                escalations = [dict(item) for item in list(alert.get('escalations') or [])]
                escalation_entry = {
                    'level': int(eligible_level.get('level') or 0),
                    'label': str(eligible_level.get('label') or ''),
                    'severity': str(eligible_level.get('severity') or alert.get('severity') or 'critical'),
                    'after_s': int(eligible_level.get('after_s') or 0),
                    'escalated_at': now_ts,
                    'escalated_by': str(actor or 'system'),
                    'notification_id': str((notification or {}).get('notification_id') or ''),
                }
                escalations.append(escalation_entry)
                alert['escalations'] = escalations[-max_escalations:]
                alert['escalation_count'] = len(alert['escalations'])
                alert['escalation_level'] = int(eligible_level.get('level') or 0)
                alert['last_escalated_at'] = now_ts
                alert['last_escalated_by'] = str(actor or 'system')
                alert['severity'] = str(eligible_level.get('severity') or alert.get('severity') or 'critical')
                alert['last_notification_id'] = str((notification or {}).get('notification_id') or '')
                alert['last_notification_at'] = now_ts
                for key in ('pending_escalation_level', 'pending_escalation_label', 'pending_route_id', 'pending_queue_id', 'pending_owner_role'):
                    suppression_state.pop(key, None)
                alert['suppression_state'] = suppression_state
                promotion = self._append_baseline_promotion_timeline_event(
                    promotion,
                    kind='monitoring',
                    label='baseline_promotion_simulation_custody_escalated',
                    actor=str(actor or 'system'),
                    alert_id=str(alert.get('alert_id') or ''),
                    escalation_level=int(eligible_level.get('level') or 0),
                    severity=str(eligible_level.get('severity') or alert.get('severity') or 'critical'),
                    notification_id=str((notification or {}).get('notification_id') or ''),
                    route_id=str(route_preview.get('route_id') or ''),
                    queue_id=str(route_preview.get('queue_id') or ''),
                    owner_role=str(route_preview.get('owner_role') or ''),
                )
                escalated = True
        manual_override_active = bool(((alert.get('routing') or {}).get('manual_override')))
        route = self._baseline_promotion_simulation_custody_route_for_alert(policy, alert, queue_state=queue_state)
        alert, routed = self._apply_baseline_promotion_simulation_custody_route_to_alert(
            alert,
            route=route,
            actor=actor,
            auto_assign=False,
            preserve_owner=True,
            source=('manual_routing' if manual_override_active else ('escalation_routing' if escalated else 'routing_policy')),
            manual_override=manual_override_active,
        )
        if routed:
            promotion = self._append_baseline_promotion_timeline_event(
                promotion,
                kind='monitoring',
                label='baseline_promotion_simulation_custody_routed',
                actor=str(actor or 'system'),
                alert_id=str(alert.get('alert_id') or ''),
                route_id=str((alert.get('routing') or {}).get('route_id') or ''),
                queue_id=str((alert.get('routing') or {}).get('queue_id') or ''),
                owner_role=str((alert.get('routing') or {}).get('owner_role') or ''),
                source=str((alert.get('routing') or {}).get('source') or 'routing_policy'),
            )
        handoff = self._baseline_promotion_simulation_custody_handoff_projection(alert)
        previous_sla = dict(alert.get('sla_state') or {})
        sla = self._baseline_promotion_simulation_custody_sla_projection(alert, policy, now_ts=now_ts)
        alert['handoff_count'] = int(handoff.get('count') or 0)
        alert['sla_state'] = sla
        newly_breached_targets = [
            str(item) for item in list(sla.get('breached_targets') or [])
            if str(item) and str(item) not in {str(existing) for existing in list(previous_sla.get('breached_targets') or []) if str(existing)}
        ]
        if bool((policy.get('sla_policy') or {}).get('enabled')) and newly_breached_targets and not bool((alert.get('suppression_state') or {}).get('suppressed')) and bool((policy.get('sla_policy') or {}).get('notify_on_breach', True)):
            notification = gw.audit.create_app_notification(
                category='operator',
                title='Baseline simulation custody SLA breached',
                body=f"SLA breached for baseline promotion {str(release.get('release_id') or '').strip()} ({', '.join(newly_breached_targets)}).",
                target_path=str(((policy.get('sla_policy') or {}).get('target_path')) or policy.get('target_path') or '/ui/?tab=operator'),
                created_by=str(actor or 'system'),
                metadata={
                    'kind': 'baseline_promotion_simulation_custody_sla_breached',
                    'promotion_id': str(release.get('release_id') or ''),
                    'reconciliation_id': str(current_reconciliation.get('reconciliation_id') or ''),
                    'alert_id': str(alert.get('alert_id') or ''),
                    'targets': newly_breached_targets,
                    'severity': str(((policy.get('sla_policy') or {}).get('severity')) or 'high'),
                },
                tenant_id=release.get('tenant_id'),
                workspace_id=release.get('workspace_id'),
                environment=release.get('environment'),
            )
            sla_notifications = [dict(item) for item in list(alert.get('sla_notifications') or [])]
            sla_notifications.append({
                'notification_id': str((notification or {}).get('notification_id') or ''),
                'targets': newly_breached_targets,
                'created_at': now_ts,
                'created_by': str(actor or 'system'),
            })
            alert['sla_notifications'] = sla_notifications[-10:]
            alert['last_sla_notification_id'] = str((notification or {}).get('notification_id') or '')
            alert['last_sla_notification_at'] = now_ts
            promotion = self._append_baseline_promotion_timeline_event(
                promotion,
                kind='monitoring',
                label='baseline_promotion_simulation_custody_sla_breached',
                actor=str(actor or 'system'),
                alert_id=str(alert.get('alert_id') or ''),
                targets=newly_breached_targets,
                notification_id=str((notification or {}).get('notification_id') or ''),
            )
        elif bool(previous_sla.get('breached_targets')) and not bool(sla.get('breached_targets')):
            promotion = self._append_baseline_promotion_timeline_event(
                promotion,
                kind='monitoring',
                label='baseline_promotion_simulation_custody_sla_recovered',
                actor=str(actor or 'system'),
                alert_id=str(alert.get('alert_id') or ''),
            )
        sla_routing_state = dict(alert.get('sla_routing_state') or {})
        if bool(policy.get('auto_reroute_on_sla_breach')) and bool(sla.get('breached')):
            breached_targets_for_route = [str(item) for item in list(sla.get('breached_targets') or newly_breached_targets or []) if str(item)]
            if bool((alert.get('suppression_state') or {}).get('suppressed')):
                sla_routing_state.update({
                    'pending': True,
                    'status': 'suppressed',
                    'pending_targets': breached_targets_for_route,
                    'updated_at': now_ts,
                    'updated_by': str(actor or 'system'),
                })
            elif manual_override_active:
                sla_routing_state.update({
                    'pending': True,
                    'status': 'manual_override_blocked',
                    'pending_targets': breached_targets_for_route,
                    'updated_at': now_ts,
                    'updated_by': str(actor or 'system'),
                })
            else:
                sla_route = self._baseline_promotion_simulation_custody_sla_route_for_alert(
                    policy,
                    alert,
                    sla,
                    breached_targets=breached_targets_for_route,
                    queue_state=queue_state,
                )
                desired_key = ''
                if sla_route:
                    desired_key = self._stable_digest({
                        'route_id': str(sla_route.get('route_id') or ''),
                        'queue_id': str(sla_route.get('queue_id') or ''),
                        'owner_role': str(sla_route.get('owner_role') or ''),
                        'owner_id': str(sla_route.get('owner_id') or ''),
                        'targets': sorted(breached_targets_for_route),
                    })
                current_route = dict(alert.get('routing') or {})
                already_routed = bool(sla_route) and (
                    str(current_route.get('route_id') or '') == str(sla_route.get('route_id') or '')
                    and str(current_route.get('queue_id') or '') == str(sla_route.get('queue_id') or '')
                    and str(current_route.get('source') or '') == 'sla_breach_routing'
                    and str(sla_routing_state.get('last_reroute_key') or '') == desired_key
                )
                if sla_route and not already_routed:
                    alert, sla_routed = self._apply_baseline_promotion_simulation_custody_route_to_alert(
                        alert,
                        route=sla_route,
                        actor=actor,
                        auto_assign=False,
                        preserve_owner=False,
                        source='sla_breach_routing',
                        manual_override=False,
                    )
                    if sla_routed:
                        notification = {}
                        if bool(policy.get('notify_on_sla_reroute', True)):
                            notification = gw.audit.create_app_notification(
                                category='operator',
                                title='Baseline simulation custody SLA rerouted',
                                body=f"SLA breach rerouted baseline promotion {str(release.get('release_id') or '').strip()} to {str(sla_route.get('label') or sla_route.get('queue_label') or sla_route.get('route_id') or '').strip() or 'an escalation queue' }.",
                                target_path=str(sla_route.get('target_path') or ((policy.get('sla_policy') or {}).get('target_path')) or policy.get('target_path') or '/ui/?tab=operator'),
                                created_by=str(actor or 'system'),
                                metadata={
                                    'kind': 'baseline_promotion_simulation_custody_sla_rerouted',
                                    'promotion_id': str(release.get('release_id') or ''),
                                    'reconciliation_id': str(current_reconciliation.get('reconciliation_id') or ''),
                                    'alert_id': str(alert.get('alert_id') or ''),
                                    'targets': breached_targets_for_route,
                                    'route_id': str((alert.get('routing') or {}).get('route_id') or ''),
                                    'queue_id': str((alert.get('routing') or {}).get('queue_id') or ''),
                                    'owner_role': str((alert.get('routing') or {}).get('owner_role') or ''),
                                },
                                tenant_id=release.get('tenant_id'),
                                workspace_id=release.get('workspace_id'),
                                environment=release.get('environment'),
                            )
                        sla_routing_state.update({
                            'pending': False,
                            'status': 'routed',
                            'reroute_count': int(sla_routing_state.get('reroute_count') or 0) + 1,
                            'last_rerouted_at': now_ts,
                            'last_rerouted_by': str(actor or 'system'),
                            'last_route_id': str((alert.get('routing') or {}).get('route_id') or ''),
                            'last_queue_id': str((alert.get('routing') or {}).get('queue_id') or ''),
                            'last_owner_role': str((alert.get('routing') or {}).get('owner_role') or ''),
                            'last_owner_id': str((alert.get('routing') or {}).get('owner_id') or ''),
                            'last_breached_targets': breached_targets_for_route,
                            'last_reroute_key': desired_key,
                            'last_notification_id': str((notification or {}).get('notification_id') or ''),
                            'updated_at': now_ts,
                            'updated_by': str(actor or 'system'),
                        })
                        promotion = self._append_baseline_promotion_timeline_event(
                            promotion,
                            kind='monitoring',
                            label='baseline_promotion_simulation_custody_sla_rerouted',
                            actor=str(actor or 'system'),
                            alert_id=str(alert.get('alert_id') or ''),
                            targets=breached_targets_for_route,
                            route_id=str((alert.get('routing') or {}).get('route_id') or ''),
                            queue_id=str((alert.get('routing') or {}).get('queue_id') or ''),
                            owner_role=str((alert.get('routing') or {}).get('owner_role') or ''),
                            notification_id=str((notification or {}).get('notification_id') or ''),
                        )
                elif sla_route:
                    sla_routing_state.update({
                        'pending': False,
                        'status': 'already_routed',
                        'last_route_id': str(current_route.get('route_id') or ''),
                        'last_queue_id': str(current_route.get('queue_id') or ''),
                        'last_owner_role': str(current_route.get('owner_role') or ''),
                        'last_owner_id': str(current_route.get('owner_id') or ''),
                        'last_breached_targets': breached_targets_for_route,
                        'last_reroute_key': desired_key,
                        'updated_at': now_ts,
                        'updated_by': str(actor or 'system'),
                    })
                else:
                    sla_routing_state.update({
                        'pending': True,
                        'status': 'no_route',
                        'pending_targets': breached_targets_for_route,
                        'updated_at': now_ts,
                        'updated_by': str(actor or 'system'),
                    })
        elif sla_routing_state:
            sla_routing_state.update({
                'pending': False,
                'status': 'clear',
                'updated_at': now_ts,
                'updated_by': str(actor or 'system'),
            })
        alert['sla_routing_state'] = sla_routing_state
        alerts[active_alert_index] = alert
        current_status = self._baseline_promotion_simulation_custody_alert_status(alert, now_ts=now_ts)
        ownership = self._baseline_promotion_simulation_custody_ownership_projection(alert)
        routing = self._baseline_promotion_simulation_custody_routing_projection(alert)
        guard = dict(promotion.get('simulation_custody_guard') or {})
        sla_routing = dict(alert.get('sla_routing_state') or {})
        guard.update({
            'alert_status': current_status,
            'escalated': bool(int(alert.get('escalation_level') or 0) > 0),
            'escalation_level': int(alert.get('escalation_level') or 0),
            'severity': str(alert.get('severity') or guard.get('severity') or ''),
            'suppressed': bool((alert.get('suppression_state') or {}).get('suppressed')),
            'suppression_reasons': [str(item) for item in list((alert.get('suppression_state') or {}).get('reasons') or []) if str(item)],
            'pending_escalation_level': int(((alert.get('suppression_state') or {}).get('pending_escalation_level')) or 0),
            'owner_id': str(ownership.get('owner_id') or ''),
            'owner_role': str(ownership.get('owner_role') or ''),
            'ownership_status': str(ownership.get('status') or ''),
            'queue_id': str(ownership.get('queue_id') or routing.get('queue_id') or ''),
            'queue_label': str(ownership.get('queue_label') or routing.get('queue_label') or ''),
            'route_id': str(routing.get('route_id') or ''),
            'route_label': str(routing.get('route_label') or ''),
            'handoff_pending': bool(handoff.get('pending')),
            'handoff_count': int(handoff.get('count') or 0),
            'sla_status': str(sla.get('status') or ''),
            'sla_breached': bool(sla.get('breached')),
            'sla_breached_targets': [str(item) for item in list(sla.get('breached_targets') or []) if str(item)],
            'sla_warning_targets': [str(item) for item in list(sla.get('warning_targets') or []) if str(item)],
            'sla_rerouted': bool(int(sla_routing.get('reroute_count') or 0) > 0 or str(routing.get('source') or '') == 'sla_breach_routing'),
            'sla_reroute_status': str(sla_routing.get('status') or ''),
            'sla_reroute_count': int(sla_routing.get('reroute_count') or 0),
            'team_queue_id': str(sla_routing.get('last_queue_id') or routing.get('queue_id') or ''),
            'alert_wait_age_s': int(routing.get('alert_wait_age_s') or 0),
            'aging_applied': bool(routing.get('aging_applied')),
            'starving': bool(routing.get('starving')),
            'queue_oldest_alert_age_s': int(routing.get('queue_oldest_alert_age_s') or 0),
            'queue_aged_alert_count': int(routing.get('queue_aged_alert_count') or 0),
            'queue_starving_alert_count': int(routing.get('queue_starving_alert_count') or 0),
            'starvation_reserved_capacity_borrowed': bool(routing.get('starvation_reserved_capacity_borrowed')),
            'starvation_prevention_applied': bool(routing.get('starvation_prevention_applied')),
            'starvation_prevention_reason': str(routing.get('starvation_prevention_reason') or ''),
            'sla_deadline_target': str(routing.get('sla_deadline_target') or ''),
            'time_to_breach_s': routing.get('time_to_breach_s'),
            'predicted_wait_time_s': routing.get('predicted_wait_time_s'),
            'predicted_sla_margin_s': routing.get('predicted_sla_margin_s'),
            'predicted_sla_breach': bool(routing.get('predicted_sla_breach')),
            'breach_risk_score': float(routing.get('breach_risk_score') or 0.0),
            'breach_risk_level': str(routing.get('breach_risk_level') or ''),
            'expected_service_time_s': int(routing.get('expected_service_time_s') or 0),
            'expedite_eligible': bool(routing.get('expedite_eligible')),
            'expedite_reserved_capacity_borrowed': bool(routing.get('expedite_reserved_capacity_borrowed')),
            'expedite_applied': bool(routing.get('expedite_applied')),
            'expedite_reason': str(routing.get('expedite_reason') or ''),
            'updated_at': now_ts,
            'updated_by': str(actor or 'system'),
        })
        promotion['simulation_custody_alerts'] = alerts
        promotion['simulation_custody_guard'] = guard
        metadata['baseline_promotion'] = promotion
        updated = gw.audit.update_release_bundle(
            str(release.get('release_id') or ''),
            metadata=metadata,
            tenant_id=release.get('tenant_id'),
            workspace_id=release.get('workspace_id'),
            environment=release.get('environment'),
        ) or release
        updated_alerts = self._baseline_promotion_simulation_custody_alerts(updated)
        return {
            'release': updated,
            'policy': policy,
            'alerts': updated_alerts,
            'alerts_summary': self._baseline_promotion_simulation_custody_alerts_summary(updated_alerts),
            'guard': self._baseline_promotion_simulation_custody_guard(updated),
            'updated': True,
            'escalated': escalated,
            'routed': routed,
        }

    def _apply_baseline_promotion_simulation_custody_monitoring(self, gw, *, release: dict[str, Any], reconciliation: dict[str, Any], actor: str) -> dict[str, Any]:
        policy = self._baseline_promotion_simulation_custody_monitoring_policy_for_release(release)
        metadata = dict((release or {}).get('metadata') or {})
        promotion = dict(metadata.get('baseline_promotion') or {})
        alerts = [dict(item) for item in list(promotion.get('simulation_custody_alerts') or [])]
        summary = dict((reconciliation or {}).get('summary') or {})
        drifted = str(summary.get('overall_status') or '') == 'drifted'
        now_ts = time.time()
        active_alert = next((item for item in alerts if bool(item.get('active'))), None)
        queue_state = self._baseline_promotion_simulation_custody_queue_capacity_state(
            gw,
            release=release,
            policy=policy,
        )
        new_alert = None
        if bool(policy.get('enabled')) and drifted and bool(policy.get('notify_on_drift')) and active_alert is None:
            latest_closed = next((item for item in alerts if not bool(item.get('active'))), None)
            dedupe_window_s = max(0, int(policy.get('dedupe_window_s') or 0))
            within_dedupe_window = False
            if latest_closed is not None and dedupe_window_s > 0:
                closed_at = latest_closed.get('recovered_at') or latest_closed.get('resolved_at') or latest_closed.get('cleared_at')
                try:
                    within_dedupe_window = closed_at is not None and (now_ts - float(closed_at)) <= float(dedupe_window_s)
                except Exception:
                    within_dedupe_window = False
            preview_alert = {
                'severity': str(policy.get('severity') or 'warning'),
                'escalation_level': 0,
            }
            route = self._baseline_promotion_simulation_custody_route_for_alert(policy, preview_alert, queue_state=queue_state)
            target_path = str(route.get('target_path') or policy.get('target_path') or '/ui/?tab=operator')
            notification = {}
            if not within_dedupe_window:
                notification = gw.audit.create_app_notification(
                    category='operator',
                    title='Baseline simulation custody drift detected',
                    body=f"Custody drift detected for baseline promotion {str(release.get('release_id') or '').strip()}.",
                    target_path=target_path,
                    created_by=str(actor or 'system'),
                    metadata={
                        'kind': 'baseline_promotion_simulation_custody_drift',
                        'promotion_id': str(release.get('release_id') or ''),
                        'reconciliation_id': str(reconciliation.get('reconciliation_id') or ''),
                        'drifted_count': int(summary.get('drifted_count') or 0),
                        'severity': str(policy.get('severity') or 'warning'),
                        'route_id': str(route.get('route_id') or ''),
                        'queue_id': str(route.get('queue_id') or ''),
                        'owner_role': str(route.get('owner_role') or ''),
                    },
                    tenant_id=release.get('tenant_id'),
                    workspace_id=release.get('workspace_id'),
                    environment=release.get('environment'),
                )
            new_alert = {
                'alert_id': self._stable_digest({'promotion_id': str(release.get('release_id') or ''), 'reconciliation_id': str(reconciliation.get('reconciliation_id') or ''), 'kind': 'drift'})[:24],
                'kind': 'drift',
                'active': True,
                'status': 'open',
                'created_at': now_ts,
                'created_by': str(actor or 'system'),
                'notification_id': str((notification or {}).get('notification_id') or ''),
                'last_notification_id': str((notification or {}).get('notification_id') or ''),
                'last_notification_at': (None if within_dedupe_window else now_ts),
                'notification_suppressed': within_dedupe_window,
                'reconciliation_id': str(reconciliation.get('reconciliation_id') or ''),
                'severity': str(policy.get('severity') or 'warning'),
                'escalation_level': 0,
                'escalation_count': 0,
                'escalations': [],
                'suppression_state': {
                    'suppressed': bool(within_dedupe_window),
                    'reasons': (['dedupe_window'] if within_dedupe_window else []),
                    'evaluated_at': now_ts,
                    'window_until': None,
                    'last_notification_at': (None if within_dedupe_window else now_ts),
                },
                'summary': {
                    'overall_status': str(summary.get('overall_status') or ''),
                    'drifted_count': int(summary.get('drifted_count') or 0),
                    'latest_package_id': str(summary.get('latest_package_id') or ''),
                },
                'ownership': {},
                'routing': {},
                'handoffs': [],
                'handoff_count': 0,
                'sla_state': {},
                'sla_notifications': [],
            }
            new_alert, routed = self._apply_baseline_promotion_simulation_custody_route_to_alert(
                new_alert,
                route=route,
                actor=actor,
                auto_assign=bool(policy.get('auto_assign_owner')),
                preserve_owner=False,
                source='default_route',
                manual_override=False,
            )
            alerts.append(new_alert)
            promotion = self._append_baseline_promotion_timeline_event(
                promotion,
                kind='monitoring',
                label='baseline_promotion_simulation_custody_drift_alerted',
                actor=str(actor or 'system'),
                reconciliation_id=str(reconciliation.get('reconciliation_id') or ''),
                drifted_count=int(summary.get('drifted_count') or 0),
                notification_id=str((notification or {}).get('notification_id') or ''),
                notification_suppressed=within_dedupe_window,
                route_id=str((new_alert.get('routing') or {}).get('route_id') or ''),
                queue_id=str((new_alert.get('routing') or {}).get('queue_id') or ''),
                owner_role=str((new_alert.get('routing') or {}).get('owner_role') or ''),
            )
            if routed:
                promotion = self._append_baseline_promotion_timeline_event(
                    promotion,
                    kind='monitoring',
                    label='baseline_promotion_simulation_custody_routed',
                    actor=str(actor or 'system'),
                    alert_id=str(new_alert.get('alert_id') or ''),
                    route_id=str((new_alert.get('routing') or {}).get('route_id') or ''),
                    queue_id=str((new_alert.get('routing') or {}).get('queue_id') or ''),
                    owner_role=str((new_alert.get('routing') or {}).get('owner_role') or ''),
                    source='default_route',
                )
        elif bool(policy.get('enabled')) and not drifted and active_alert is not None:
            for item in alerts:
                if str(item.get('alert_id') or '') == str(active_alert.get('alert_id') or ''):
                    item['active'] = False
                    item['cleared_at'] = now_ts
                    item['cleared_by'] = str(actor or 'system')
                    item['recovered_at'] = now_ts
                    item['recovered_by'] = str(actor or 'system')
                    item['status'] = 'recovered'
                    item['suppression_state'] = {
                        **dict(item.get('suppression_state') or {}),
                        'suppressed': False,
                        'reasons': [],
                        'evaluated_at': now_ts,
                    }
                    break
            notification = {}
            if bool(policy.get('notify_on_recovery')):
                notification = gw.audit.create_app_notification(
                    category='operator',
                    title='Baseline simulation custody drift recovered',
                    body=f"Custody drift cleared for baseline promotion {str(release.get('release_id') or '').strip()}.",
                    target_path=str(policy.get('target_path') or '/ui/?tab=operator'),
                    created_by=str(actor or 'system'),
                    metadata={
                        'kind': 'baseline_promotion_simulation_custody_recovered',
                        'promotion_id': str(release.get('release_id') or ''),
                        'reconciliation_id': str(reconciliation.get('reconciliation_id') or ''),
                        'severity': 'info',
                    },
                    tenant_id=release.get('tenant_id'),
                    workspace_id=release.get('workspace_id'),
                    environment=release.get('environment'),
                )
            promotion = self._append_baseline_promotion_timeline_event(
                promotion,
                kind='monitoring',
                label='baseline_promotion_simulation_custody_recovered',
                actor=str(actor or 'system'),
                reconciliation_id=str(reconciliation.get('reconciliation_id') or ''),
                notification_id=str((notification or {}).get('notification_id') or ''),
            )
        max_alerts = max(1, int(policy.get('max_alerts') or 20))
        alerts.sort(key=lambda item: (float(item.get('created_at') or 0.0), str(item.get('alert_id') or '')), reverse=True)
        alerts = alerts[:max_alerts]
        active_alert = next((item for item in alerts if bool(item.get('active'))), {})
        blocked = bool(policy.get('enabled')) and bool(policy.get('block_on_drift')) and drifted
        active_ownership = self._baseline_promotion_simulation_custody_ownership_projection(active_alert)
        active_routing = self._baseline_promotion_simulation_custody_routing_projection(active_alert)
        guard = {
            'blocked': blocked,
            'reason': 'baseline_promotion_simulation_custody_drift_detected' if blocked else '',
            'reasons': ['baseline_promotion_simulation_custody_drift_detected'] if blocked else [],
            'status': 'blocked' if blocked else 'clear',
            'updated_at': now_ts,
            'updated_by': str(actor or 'system'),
            'reconciliation_id': str(reconciliation.get('reconciliation_id') or ''),
            'drifted_count': int(summary.get('drifted_count') or 0),
            'active_alert_id': str(active_alert.get('alert_id') or ''),
            'notification_id': str(active_alert.get('notification_id') or ''),
            'alert_status': self._baseline_promotion_simulation_custody_alert_status(active_alert, now_ts=now_ts) if active_alert else '',
            'escalated': bool(int(active_alert.get('escalation_level') or 0) > 0),
            'escalation_level': int(active_alert.get('escalation_level') or 0),
            'severity': str(active_alert.get('severity') or ''),
            'suppressed': bool(((active_alert.get('suppression_state') or {}).get('suppressed'))),
            'suppression_reasons': [str(item) for item in list(((active_alert.get('suppression_state') or {}).get('reasons')) or []) if str(item)],
            'pending_escalation_level': int((((active_alert.get('suppression_state') or {}).get('pending_escalation_level')) or 0)),
            'owner_id': str(active_ownership.get('owner_id') or ''),
            'owner_role': str(active_ownership.get('owner_role') or ''),
            'ownership_status': str(active_ownership.get('status') or ''),
            'queue_id': str(active_ownership.get('queue_id') or active_routing.get('queue_id') or ''),
            'queue_label': str(active_ownership.get('queue_label') or active_routing.get('queue_label') or ''),
            'route_id': str(active_routing.get('route_id') or ''),
            'route_label': str(active_routing.get('route_label') or ''),
        }
        promotion['simulation_custody_alerts'] = alerts
        promotion['simulation_custody_guard'] = guard
        metadata['baseline_promotion'] = promotion
        updated = gw.audit.update_release_bundle(
            str(release.get('release_id') or ''),
            metadata=metadata,
            tenant_id=release.get('tenant_id'),
            workspace_id=release.get('workspace_id'),
            environment=release.get('environment'),
        ) or release
        governance = self._evaluate_baseline_promotion_simulation_custody_alert_governance(
            gw,
            release=updated,
            actor=actor,
            policy=policy,
            reconciliation=reconciliation,
        )
        updated_release = dict(governance.get('release') or updated)
        updated_alerts = [dict(item) for item in list(governance.get('alerts') or self._baseline_promotion_simulation_custody_alerts(updated_release))]
        updated_guard = dict(governance.get('guard') or self._baseline_promotion_simulation_custody_guard(updated_release))
        return {
            'release': updated_release,
            'policy': policy,
            'guard': updated_guard,
            'alerts': updated_alerts,
            'alerts_summary': self._baseline_promotion_simulation_custody_alerts_summary(updated_alerts),
            'new_alert': new_alert or {},
            'governance': {
                'escalated': bool(governance.get('escalated')),
            },
        }

    def _update_baseline_promotion_simulation_custody_alert_lifecycle(
        self,
        gw,
        *,
        release: dict[str, Any],
        actor: str,
        action: str,
        alert_id: str | None = None,
        reason: str = '',
        mute_for_s: int | None = None,
        owner_id: str | None = None,
        owner_role: str | None = None,
        queue_id: str | None = None,
        queue_label: str | None = None,
        route_id: str | None = None,
        route_label: str | None = None,
    ) -> dict[str, Any]:
        normalized_action = str(action or '').strip().lower()
        metadata = dict((release or {}).get('metadata') or {})
        promotion = dict(metadata.get('baseline_promotion') or {})
        alerts = [dict(item) for item in list(promotion.get('simulation_custody_alerts') or [])]
        if not alerts:
            return {'ok': False, 'error': 'baseline_promotion_simulation_custody_alert_missing'}
        target = None
        if alert_id:
            target = next((item for item in alerts if str(item.get('alert_id') or '') == str(alert_id or '').strip()), None)
        if target is None:
            target = next((item for item in alerts if bool(item.get('active'))), None)
        if target is None:
            return {'ok': False, 'error': 'baseline_promotion_simulation_custody_alert_missing'}
        now_ts = time.time()
        target_id = str(target.get('alert_id') or '')
        current_status = self._baseline_promotion_simulation_custody_alert_status(target, now_ts=now_ts)
        policy = self._baseline_promotion_simulation_custody_monitoring_policy_for_release(release)
        queue_state = self._baseline_promotion_simulation_custody_queue_capacity_state(
            gw,
            release=release,
            policy=policy,
            exclude_alert_id=target_id,
        )
        current_reconciliation = dict(promotion.get('current_simulation_evidence_reconciliation') or {})
        current_summary = dict(current_reconciliation.get('summary') or {})
        drifted = str(current_summary.get('overall_status') or '') == 'drifted'
        ownership = dict(target.get('ownership') or {})
        routing = dict(target.get('routing') or {})
        normalized_owner_id = str(owner_id or '').strip()
        normalized_owner_role = str(owner_role or '').strip()
        normalized_queue_id = str(queue_id or '').strip()
        normalized_queue_label = str(queue_label or '').strip()
        normalized_route_id = str(route_id or '').strip()
        normalized_route_label = str(route_label or '').strip()
        if normalized_action == 'acknowledge':
            if not bool(target.get('active')):
                return {'ok': False, 'error': 'baseline_promotion_simulation_custody_alert_not_active', 'alert': target}
            target['acknowledged_at'] = now_ts
            target['acknowledged_by'] = str(actor or 'system')
            target['status'] = 'acknowledged'
            label = 'baseline_promotion_simulation_custody_alert_acknowledged'
        elif normalized_action == 'mute':
            if not bool(target.get('active')):
                return {'ok': False, 'error': 'baseline_promotion_simulation_custody_alert_not_active', 'alert': target}
            try:
                mute_window_s = int(mute_for_s) if mute_for_s is not None else int(policy.get('default_mute_s') or 0)
            except Exception:
                mute_window_s = int(policy.get('default_mute_s') or 0)
            mute_window_s = max(0, int(mute_window_s or 0))
            target['muted_at'] = now_ts
            target['muted_by'] = str(actor or 'system')
            target['muted_until'] = (now_ts + mute_window_s) if mute_window_s > 0 else None
            target['mute_reason'] = str(reason or '').strip()
            target['status'] = 'muted'
            label = 'baseline_promotion_simulation_custody_alert_muted'
        elif normalized_action == 'unmute':
            if current_status != 'muted':
                return {'ok': False, 'error': 'baseline_promotion_simulation_custody_alert_not_muted', 'alert': target}
            target.pop('muted_at', None)
            target.pop('muted_by', None)
            target.pop('muted_until', None)
            target.pop('mute_reason', None)
            target['status'] = 'acknowledged' if target.get('acknowledged_at') is not None else 'open'
            label = 'baseline_promotion_simulation_custody_alert_unmuted'
        elif normalized_action == 'resolve':
            if bool(target.get('active')) and drifted:
                return {'ok': False, 'error': 'baseline_promotion_simulation_custody_alert_still_drifted', 'alert': target, 'reconciliation': current_reconciliation}
            target['active'] = False
            target['resolved_at'] = now_ts
            target['resolved_by'] = str(actor or 'system')
            target['resolve_reason'] = str(reason or '').strip()
            target['status'] = 'resolved'
            label = 'baseline_promotion_simulation_custody_alert_resolved'
        elif normalized_action == 'claim':
            if not bool(target.get('active')):
                return {'ok': False, 'error': 'baseline_promotion_simulation_custody_alert_not_active', 'alert': target}
            current_owner_id = str(ownership.get('owner_id') or '').strip()
            if current_owner_id and current_owner_id != str(actor or 'system'):
                return {'ok': False, 'error': 'baseline_promotion_simulation_custody_alert_already_owned', 'alert': target}
            ownership['owner_id'] = str(actor or 'system')
            ownership['owner_display'] = str(actor or 'system')
            ownership['assigned_at'] = ownership.get('assigned_at') or now_ts
            ownership['assigned_by'] = ownership.get('assigned_by') or str(actor or 'system')
            ownership['claimed_at'] = now_ts
            ownership['claimed_by'] = str(actor or 'system')
            ownership['updated_at'] = now_ts
            ownership['updated_by'] = str(actor or 'system')
            ownership['status'] = 'claimed'
            handoffs = [dict(item) for item in list(target.get('handoffs') or [])]
            if handoffs:
                latest_handoff = dict(handoffs[-1] or {})
                target_owner = str(latest_handoff.get('to_owner_id') or '').strip()
                if latest_handoff.get('accepted_at') is None and (not target_owner or target_owner == str(actor or 'system')):
                    latest_handoff['accepted_at'] = now_ts
                    latest_handoff['accepted_by'] = str(actor or 'system')
                    latest_handoff['status'] = 'accepted'
                    handoffs[-1] = latest_handoff
                    target['handoffs'] = handoffs
                    target['handoff_count'] = len(handoffs)
            target['ownership'] = ownership
            label = 'baseline_promotion_simulation_custody_alert_claimed'
        elif normalized_action == 'assign':
            if not bool(target.get('active')):
                return {'ok': False, 'error': 'baseline_promotion_simulation_custody_alert_not_active', 'alert': target}
            if not any([normalized_owner_id, normalized_owner_role, normalized_queue_id, normalized_route_id]):
                return {'ok': False, 'error': 'baseline_promotion_simulation_custody_alert_assignment_missing', 'alert': target}
            if normalized_route_id or normalized_queue_id or normalized_owner_role:
                route = self._baseline_promotion_simulation_custody_route_for_alert(policy, target, preferred_route_id=normalized_route_id, queue_state=queue_state)
                if normalized_queue_id or normalized_owner_role or normalized_route_label:
                    route = self._normalize_baseline_promotion_simulation_custody_route({
                        **route,
                        'route_id': normalized_route_id or route.get('route_id') or self._stable_digest({'promotion_id': str(release.get('release_id') or ''), 'queue_id': normalized_queue_id, 'owner_role': normalized_owner_role})[:16],
                        'label': normalized_route_label or route.get('label') or 'Manual routing',
                        'queue_id': normalized_queue_id or route.get('queue_id') or '',
                        'queue_label': normalized_queue_label or route.get('queue_label') or normalized_queue_id or '',
                        'owner_role': normalized_owner_role or route.get('owner_role') or '',
                        'owner_id': normalized_owner_id or route.get('owner_id') or '',
                        'target_path': route.get('target_path') or policy.get('target_path') or '/ui/?tab=operator',
                    }, index=0)
                route = self._select_baseline_promotion_simulation_custody_route_by_load(
                    routes=[route],
                    queue_state=queue_state,
                    current_queue_id=str((target.get('routing') or {}).get('queue_id') or ''),
                    prefer_lowest_load=False,
                    alert=target,
                    policy=policy,
                )
                target, _ = self._apply_baseline_promotion_simulation_custody_route_to_alert(
                    target,
                    route=route,
                    actor=actor,
                    auto_assign=False,
                    preserve_owner=not bool(normalized_owner_id),
                    source='manual_assignment',
                    manual_override=True,
                )
                ownership = dict(target.get('ownership') or {})
                routing = dict(target.get('routing') or {})
            if normalized_owner_id:
                ownership['owner_id'] = normalized_owner_id
                ownership['owner_display'] = normalized_owner_id
            if normalized_owner_role:
                ownership['owner_role'] = normalized_owner_role
            if normalized_queue_id:
                ownership['queue_id'] = normalized_queue_id
                ownership['queue_label'] = normalized_queue_label or normalized_queue_id
            ownership['assigned_at'] = now_ts
            ownership['assigned_by'] = str(actor or 'system')
            ownership.pop('claimed_at', None)
            ownership.pop('claimed_by', None)
            ownership['status'] = 'assigned' if str(ownership.get('owner_id') or '').strip() else ('queued' if str(ownership.get('queue_id') or ownership.get('owner_role') or '').strip() else 'unassigned')
            target['ownership'] = ownership
            if normalized_route_id:
                routing['route_id'] = normalized_route_id
            if normalized_route_label:
                routing['route_label'] = normalized_route_label
            if normalized_queue_id:
                routing['queue_id'] = normalized_queue_id
                routing['queue_label'] = normalized_queue_label or normalized_queue_id
            if normalized_owner_role:
                routing['owner_role'] = normalized_owner_role
            if normalized_owner_id:
                routing['owner_id'] = normalized_owner_id
            routing['updated_at'] = now_ts
            routing['updated_by'] = str(actor or 'system')
            routing['source'] = 'manual_assignment'
            routing['manual_override'] = True
            target['routing'] = routing
            label = 'baseline_promotion_simulation_custody_alert_assigned'
        elif normalized_action == 'release':
            if not str(ownership.get('owner_id') or '').strip():
                return {'ok': False, 'error': 'baseline_promotion_simulation_custody_alert_not_owned', 'alert': target}
            ownership.pop('owner_id', None)
            ownership.pop('owner_display', None)
            ownership.pop('claimed_at', None)
            ownership.pop('claimed_by', None)
            ownership['released_at'] = now_ts
            ownership['released_by'] = str(actor or 'system')
            ownership['status'] = 'queued' if str(ownership.get('queue_id') or ownership.get('owner_role') or '').strip() else 'unassigned'
            target['ownership'] = ownership
            label = 'baseline_promotion_simulation_custody_alert_released'
        elif normalized_action == 'reroute':
            if not bool(target.get('active')):
                return {'ok': False, 'error': 'baseline_promotion_simulation_custody_alert_not_active', 'alert': target}
            route = self._baseline_promotion_simulation_custody_route_for_alert(policy, target, preferred_route_id=normalized_route_id, queue_state=queue_state)
            if normalized_route_id and not route:
                route = {}
            route = self._normalize_baseline_promotion_simulation_custody_route({
                **route,
                'route_id': normalized_route_id or route.get('route_id') or self._stable_digest({'promotion_id': str(release.get('release_id') or ''), 'queue_id': normalized_queue_id or routing.get('queue_id') or ''})[:16],
                'label': normalized_route_label or route.get('label') or 'Manual reroute',
                'queue_id': normalized_queue_id or route.get('queue_id') or routing.get('queue_id') or '',
                'queue_label': normalized_queue_label or route.get('queue_label') or routing.get('queue_label') or normalized_queue_id or '',
                'owner_role': normalized_owner_role or route.get('owner_role') or routing.get('owner_role') or ownership.get('owner_role') or '',
                'owner_id': route.get('owner_id') or routing.get('owner_id') or '',
                'target_path': route.get('target_path') or policy.get('target_path') or '/ui/?tab=operator',
            }, index=0)
            if not any(route.get(key) for key in ('queue_id', 'owner_role', 'owner_id', 'route_id')):
                return {'ok': False, 'error': 'baseline_promotion_simulation_custody_alert_route_missing', 'alert': target}
            route = self._select_baseline_promotion_simulation_custody_route_by_load(
                routes=[route],
                queue_state=queue_state,
                current_queue_id=str((target.get('routing') or {}).get('queue_id') or ''),
                prefer_lowest_load=False,
                alert=target,
                policy=policy,
            )
            target, _ = self._apply_baseline_promotion_simulation_custody_route_to_alert(
                target,
                route=route,
                actor=actor,
                auto_assign=False,
                preserve_owner=True,
                source='manual_reroute',
                manual_override=True,
            )
            label = 'baseline_promotion_simulation_custody_alert_rerouted'
        elif normalized_action == 'handoff':
            if not bool(policy.get('handoff_enabled', True)):
                return {'ok': False, 'error': 'baseline_promotion_simulation_custody_handoff_disabled', 'alert': target}
            if not bool(target.get('active')):
                return {'ok': False, 'error': 'baseline_promotion_simulation_custody_alert_not_active', 'alert': target}
            if bool(policy.get('handoff_require_reason')) and not str(reason or '').strip():
                return {'ok': False, 'error': 'baseline_promotion_simulation_custody_handoff_reason_required', 'alert': target}
            if not any([normalized_owner_id, normalized_owner_role, normalized_queue_id, normalized_route_id]):
                return {'ok': False, 'error': 'baseline_promotion_simulation_custody_handoff_missing', 'alert': target}
            previous_ownership = self._baseline_promotion_simulation_custody_ownership_projection(target)
            previous_routing = self._baseline_promotion_simulation_custody_routing_projection(target)
            route = self._baseline_promotion_simulation_custody_route_for_alert(policy, target, preferred_route_id=normalized_route_id, queue_state=queue_state)
            if normalized_route_id and not route:
                route = {}
            route = self._normalize_baseline_promotion_simulation_custody_route({
                **route,
                'route_id': normalized_route_id or route.get('route_id') or self._stable_digest({'promotion_id': str(release.get('release_id') or ''), 'owner_id': normalized_owner_id, 'queue_id': normalized_queue_id})[:16],
                'label': normalized_route_label or route.get('label') or 'Manual handoff',
                'queue_id': normalized_queue_id or route.get('queue_id') or previous_routing.get('queue_id') or '',
                'queue_label': normalized_queue_label or route.get('queue_label') or previous_routing.get('queue_label') or normalized_queue_id or '',
                'owner_role': normalized_owner_role or route.get('owner_role') or previous_routing.get('owner_role') or previous_ownership.get('owner_role') or '',
                'owner_id': normalized_owner_id or route.get('owner_id') or '',
                'target_path': route.get('target_path') or policy.get('target_path') or '/ui/?tab=operator',
            }, index=0)
            route = self._select_baseline_promotion_simulation_custody_route_by_load(
                routes=[route],
                queue_state=queue_state,
                current_queue_id=str((target.get('routing') or {}).get('queue_id') or ''),
                prefer_lowest_load=False,
                alert=target,
                policy=policy,
            )
            target, _ = self._apply_baseline_promotion_simulation_custody_route_to_alert(
                target,
                route=route,
                actor=actor,
                auto_assign=False,
                preserve_owner=False,
                source='manual_handoff',
                manual_override=True,
            )
            ownership = dict(target.get('ownership') or {})
            routing = dict(target.get('routing') or {})
            ownership['assigned_at'] = now_ts
            ownership['assigned_by'] = str(actor or 'system')
            ownership['updated_at'] = now_ts
            ownership['updated_by'] = str(actor or 'system')
            ownership.pop('claimed_at', None)
            ownership.pop('claimed_by', None)
            ownership['status'] = 'assigned' if str(ownership.get('owner_id') or '').strip() else ('queued' if str(ownership.get('queue_id') or ownership.get('owner_role') or '').strip() else 'unassigned')
            target['ownership'] = ownership
            handoffs = [dict(item) for item in list(target.get('handoffs') or [])]
            entry = {
                'handoff_id': self._stable_digest({'promotion_id': str(release.get('release_id') or ''), 'alert_id': target_id, 'handoff_at': now_ts, 'to_owner_id': str(ownership.get('owner_id') or ''), 'to_queue_id': str(ownership.get('queue_id') or routing.get('queue_id') or '')})[:24],
                'handoff_at': now_ts,
                'handed_off_by': str(actor or 'system'),
                'reason': str(reason or '').strip(),
                'from_owner_id': str(previous_ownership.get('owner_id') or ''),
                'from_owner_role': str(previous_ownership.get('owner_role') or ''),
                'from_queue_id': str(previous_ownership.get('queue_id') or previous_routing.get('queue_id') or ''),
                'from_route_id': str(previous_routing.get('route_id') or ''),
                'to_owner_id': str(ownership.get('owner_id') or ''),
                'to_owner_role': str(ownership.get('owner_role') or ''),
                'to_queue_id': str(ownership.get('queue_id') or routing.get('queue_id') or ''),
                'to_route_id': str(routing.get('route_id') or ''),
                'status': 'pending',
            }
            if str(entry.get('to_owner_id') or '') == str(actor or 'system'):
                entry['accepted_at'] = now_ts
                entry['accepted_by'] = str(actor or 'system')
                entry['status'] = 'accepted'
            handoffs.append(entry)
            target['handoffs'] = handoffs[-20:]
            target['handoff_count'] = len(target['handoffs'])
            label = 'baseline_promotion_simulation_custody_alert_handed_off'
        else:
            return {'ok': False, 'error': 'baseline_promotion_simulation_custody_alert_action_unsupported', 'action': normalized_action}
        for item in alerts:
            if str(item.get('alert_id') or '') == target_id:
                item.update(target)
                break
        promotion['simulation_custody_alerts'] = alerts
        promotion = self._append_baseline_promotion_timeline_event(
            promotion,
            kind='monitoring',
            label=label,
            actor=str(actor or 'system'),
            alert_id=target_id,
            reason=str(reason or '').strip(),
            mute_for_s=(None if mute_for_s is None else max(0, int(mute_for_s or 0))),
            owner_id=str((target.get('ownership') or {}).get('owner_id') or ''),
            owner_role=str((target.get('ownership') or {}).get('owner_role') or ''),
            queue_id=str((target.get('ownership') or {}).get('queue_id') or ((target.get('routing') or {}).get('queue_id')) or ''),
            route_id=str((target.get('routing') or {}).get('route_id') or ''),
        )
        metadata['baseline_promotion'] = promotion
        updated = gw.audit.update_release_bundle(
            str(release.get('release_id') or ''),
            metadata=metadata,
            tenant_id=release.get('tenant_id'),
            workspace_id=release.get('workspace_id'),
            environment=release.get('environment'),
        ) or release
        governance = self._evaluate_baseline_promotion_simulation_custody_alert_governance(
            gw,
            release=updated,
            actor=actor,
            policy=policy,
            reconciliation=current_reconciliation,
        )
        updated_release = dict(governance.get('release') or updated)
        updated_alerts = [dict(item) for item in list(governance.get('alerts') or self._baseline_promotion_simulation_custody_alerts(updated_release))]
        return {
            'ok': True,
            'action': normalized_action,
            'alert': next((item for item in updated_alerts if str(item.get('alert_id') or '') == target_id), {}),
            'alerts': updated_alerts,
            'alerts_summary': self._baseline_promotion_simulation_custody_alerts_summary(updated_alerts),
            'release': updated_release,
        }

    def _list_baseline_promotion_simulation_evidence_reconciliation_sessions(self, release: dict[str, Any] | None) -> list[dict[str, Any]]:
        metadata = dict((release or {}).get('metadata') or {})
        promotion = dict(metadata.get('baseline_promotion') or {})
        items = [dict(item) for item in list(promotion.get('simulation_evidence_reconciliation_sessions') or [])]
        items.sort(key=lambda item: (float(item.get('reconciled_at') or 0.0), str(item.get('reconciliation_id') or '')), reverse=True)
        return items

    def _store_baseline_promotion_simulation_evidence_reconciliation_session(
        self,
        gw,
        *,
        release: dict[str, Any],
        session_record: dict[str, Any],
        history_limit: int = 20,
    ) -> dict[str, Any]:
        metadata = dict(release.get('metadata') or {})
        promotion = dict(metadata.get('baseline_promotion') or {})
        sessions = [dict(item) for item in list(promotion.get('simulation_evidence_reconciliation_sessions') or [])]
        sessions = [item for item in sessions if str(item.get('reconciliation_id') or '') != str(session_record.get('reconciliation_id') or '')]
        sessions.append(dict(session_record))
        sessions.sort(key=lambda item: (float(item.get('reconciled_at') or 0.0), str(item.get('reconciliation_id') or '')), reverse=True)
        promotion['simulation_evidence_reconciliation_sessions'] = sessions[: max(1, int(history_limit or 20))]
        promotion['current_simulation_evidence_reconciliation'] = dict(session_record)
        promotion = self._append_baseline_promotion_timeline_event(
            promotion,
            kind='evidence',
            label='baseline_promotion_simulation_evidence_reconciled',
            actor=str(session_record.get('reconciled_by') or 'system'),
            reconciliation_id=str(session_record.get('reconciliation_id') or ''),
            package_count=int((session_record.get('summary') or {}).get('count') or 0),
            drifted_count=int((session_record.get('summary') or {}).get('drifted_count') or 0),
            overall_status=str((session_record.get('summary') or {}).get('overall_status') or ''),
            latest_package_id=str((session_record.get('summary') or {}).get('latest_package_id') or ''),
        )
        metadata['baseline_promotion'] = promotion
        return gw.audit.update_release_bundle(
            str(release.get('release_id') or ''),
            status=release.get('status'),
            notes=release.get('notes'),
            metadata=metadata,
            tenant_id=release.get('tenant_id'),
            workspace_id=release.get('workspace_id'),
            environment=release.get('environment'),
        ) or release

    def _list_baseline_promotion_simulation_evidence_packages(self, release: dict[str, Any] | None, *, include_content: bool = False) -> list[dict[str, Any]]:
        metadata = dict((release or {}).get('metadata') or {})
        promotion = dict(metadata.get('baseline_promotion') or {})
        items = [dict(item) for item in list(promotion.get('simulation_evidence_packages') or [])]
        sanitized: list[dict[str, Any]] = []
        for item in items:
            record = dict(item)
            artifact = dict(record.get('artifact') or {})
            if artifact and not include_content:
                artifact.pop('content_b64', None)
                record['artifact'] = artifact
            sanitized.append(record)
        sanitized.sort(key=lambda item: float(item.get('created_at') or 0.0), reverse=True)
        return sanitized

    def _baseline_promotion_simulation_export_registry_entries(self, release: dict[str, Any] | None) -> list[dict[str, Any]]:
        metadata = dict((release or {}).get('metadata') or {})
        promotion = dict(metadata.get('baseline_promotion') or {})
        items = [dict(item) for item in list(promotion.get('simulation_export_registry') or [])]
        items.sort(key=lambda item: (int(item.get('sequence') or 0), float(item.get('appended_at') or 0.0), str(item.get('entry_id') or '')))
        return items

    def _baseline_promotion_simulation_export_registry_summary(self, release: dict[str, Any] | None) -> dict[str, Any]:
        entries = self._baseline_promotion_simulation_export_registry_entries(release)
        packages = self._list_baseline_promotion_simulation_evidence_packages(release)
        chain_ok = True
        broken_sequences = 0
        previous_hash = ''
        expected_sequence = 1
        immutable_count = 0
        escrowed_count = 0
        immutable_archive_count = 0
        latest_archive_path = None
        latest_receipt_id = None
        for package in packages:
            escrow = dict(package.get('escrow') or {})
            if bool(escrow.get('archived')):
                escrowed_count += 1
                latest_archive_path = latest_archive_path or escrow.get('archive_path')
                latest_receipt_id = latest_receipt_id or escrow.get('receipt_id')
                if escrow.get('immutable_until') is not None:
                    immutable_archive_count += 1
        for entry in entries:
            if int(entry.get('sequence') or 0) != expected_sequence:
                broken_sequences += 1
                chain_ok = False
                expected_sequence = int(entry.get('sequence') or expected_sequence)
            core = dict(entry.get('entry_core') or {})
            actual_hash = self._stable_digest(core)
            if str(entry.get('previous_entry_hash') or '') != previous_hash:
                chain_ok = False
            if str(entry.get('entry_hash') or '') != actual_hash:
                chain_ok = False
            if bool(entry.get('immutable')):
                immutable_count += 1
            previous_hash = str(entry.get('entry_hash') or '')
            expected_sequence += 1
        latest = entries[-1] if entries else {}
        return {
            'count': len(entries),
            'package_count': len(packages),
            'latest_entry_id': str(latest.get('entry_id') or ''),
            'latest_package_id': str(latest.get('package_id') or ''),
            'latest_entry_hash': str(latest.get('entry_hash') or ''),
            'chain_ok': chain_ok,
            'broken_sequence_count': broken_sequences,
            'immutable_count': immutable_count,
            'escrowed_count': escrowed_count,
            'immutable_archive_count': immutable_archive_count,
            'latest_archive_path': latest_archive_path,
            'latest_receipt_id': latest_receipt_id,
        }

    def _store_baseline_promotion_simulation_evidence_package(
        self,
        gw,
        *,
        release: dict[str, Any],
        package_record: dict[str, Any],
        registry_entry: dict[str, Any],
    ) -> dict[str, Any]:
        metadata = dict(release.get('metadata') or {})
        promotion = dict(metadata.get('baseline_promotion') or {})
        packages = [dict(item) for item in list(promotion.get('simulation_evidence_packages') or [])]
        packages = [item for item in packages if str(item.get('package_id') or '') != str(package_record.get('package_id') or '')]
        packages.append(dict(package_record))
        packages.sort(key=lambda item: float(item.get('created_at') or 0.0), reverse=True)
        max_packages = max(1, int((package_record.get('retention') or {}).get('max_packages') or self._baseline_promotion_simulation_evidence_max_packages(package_record.get('source_simulation'))))
        promotion['simulation_evidence_packages'] = packages[: max(1, max_packages * 3)]
        registry = [dict(item) for item in list(promotion.get('simulation_export_registry') or [])]
        registry.append(dict(registry_entry))
        registry.sort(key=lambda item: (int(item.get('sequence') or 0), float(item.get('appended_at') or 0.0), str(item.get('entry_id') or '')))
        promotion['simulation_export_registry'] = registry
        promotion = self._append_baseline_promotion_timeline_event(
            promotion,
            kind='evidence',
            label='baseline_promotion_simulation_evidence_packaged',
            actor=str(package_record.get('created_by') or 'system'),
            simulation_id=str(package_record.get('simulation_id') or ''),
            package_id=str(package_record.get('package_id') or ''),
            registry_entry_id=str(registry_entry.get('entry_id') or ''),
            immutable=True,
            artifact_sha256=str(((package_record.get('artifact') or {}).get('sha256')) or ''),
        )
        escrow = dict(package_record.get('escrow') or {})
        if bool(escrow.get('archived')):
            promotion = self._append_baseline_promotion_timeline_event(
                promotion,
                kind='evidence',
                label='baseline_promotion_simulation_evidence_escrowed',
                actor=str(package_record.get('created_by') or 'system'),
                simulation_id=str(package_record.get('simulation_id') or ''),
                package_id=str(package_record.get('package_id') or ''),
                receipt_id=str(escrow.get('receipt_id') or ''),
                archive_path=str(escrow.get('archive_path') or ''),
                immutable_until=escrow.get('immutable_until'),
                object_lock_enabled=bool(escrow.get('object_lock_enabled')),
            )
        metadata['baseline_promotion'] = promotion
        return gw.audit.update_release_bundle(
            str(release.get('release_id') or ''),
            status=release.get('status'),
            notes=release.get('notes'),
            metadata=metadata,
            tenant_id=release.get('tenant_id'),
            workspace_id=release.get('workspace_id'),
            environment=release.get('environment'),
        ) or release

    def _build_baseline_promotion_simulation_evidence_package_export_payload(
        self,
        *,
        release: dict[str, Any],
        simulation: dict[str, Any],
        actor: str,
        timeline_limit: int | None = None,
    ) -> dict[str, Any]:
        attestation_export = self._build_baseline_promotion_simulation_attestation_export_payload(
            simulation=simulation,
            actor=actor,
            timeline_limit=timeline_limit,
        )
        review_audit_export = self._build_baseline_promotion_simulation_review_audit_export_payload(
            simulation=simulation,
            actor=actor,
            timeline_limit=timeline_limit,
        )
        export_policy = self._baseline_promotion_simulation_evidence_export_policy(simulation=simulation, release=release)
        escrow_policy = self._baseline_promotion_simulation_effective_escrow_policy(simulation=simulation, release=release)
        retention_days = self._baseline_promotion_simulation_evidence_retention_days(simulation)
        retention_until = time.time() + (retention_days * 86400.0)
        generated_at = time.time()
        package_id = f'sim-evidence-{uuid.uuid4().hex[:24]}'
        manifest, manifest_hash = self._baseline_promotion_simulation_evidence_package_manifest(
            package_id=package_id,
            attestation_export=attestation_export,
            review_audit_export=review_audit_export,
            simulation=simulation,
            export_policy=export_policy,
        )
        entries = self._baseline_promotion_simulation_export_registry_entries(release)
        previous = dict(entries[-1] or {}) if entries else {}
        sequence = (int(previous.get('sequence') or 0) + 1) if previous else 1
        registry_core = {
            'entry_id': f'sim-export-reg-{str(release.get("release_id") or "")[:8]}-{sequence:06d}',
            'sequence': sequence,
            'package_id': package_id,
            'simulation_id': str(simulation.get('simulation_id') or ''),
            'report_type': 'openmiura_baseline_promotion_simulation_evidence_package_v1',
            'payload_fingerprint': str((simulation.get('fingerprints') or {}).get('request_hash') or ''),
            'manifest_hash': manifest_hash,
            'scope': self._scope(tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=release.get('environment')),
            'appended_at': generated_at,
            'appended_by': str(actor or 'system'),
            'previous_entry_hash': str(previous.get('entry_hash') or ''),
            'immutable': True,
            'immutable_until': retention_until,
            'registry_mode': str(export_policy.get('registry_mode') or 'append_only_hash_chain'),
        }
        registry_entry = {
            **registry_core,
            'entry_core': dict(registry_core),
            'entry_hash': self._stable_digest(registry_core),
        }
        retention = {
            'immutable_retention_days': retention_days,
            'retain_until': retention_until,
            'max_packages': self._baseline_promotion_simulation_evidence_max_packages(simulation),
            'classification': self._baseline_promotion_simulation_evidence_classification(simulation=simulation, release=release),
            'legal_hold': bool(escrow_policy.get('object_lock_enabled')) and bool(escrow_policy.get('delete_protection', False)),
        }
        package_payload = {
            'report_type': 'openmiura_baseline_promotion_simulation_evidence_package_v1',
            'generated_at': generated_at,
            'generated_by': str(actor or 'system'),
            'package_id': package_id,
            'simulation': {
                'simulation_id': str(simulation.get('simulation_id') or ''),
                'simulation_status': str(simulation.get('simulation_status') or ''),
                'simulated_at': simulation.get('simulated_at'),
                'simulated_by': simulation.get('simulated_by'),
                'reviewed_at': simulation.get('reviewed_at'),
                'catalog_id': str(simulation.get('catalog_id') or ''),
                'catalog_name': str(simulation.get('catalog_name') or ''),
                'candidate_catalog_version': str(simulation.get('candidate_catalog_version') or ''),
            },
            'source_promotion': {
                'promotion_id': str(release.get('release_id') or ''),
                'name': str(release.get('name') or ''),
                'version': str(release.get('version') or ''),
                'status': str(release.get('status') or ''),
            },
            'scope': self._scope(tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=release.get('environment')),
            'manifest': {**manifest, 'manifest_hash': manifest_hash},
            'artifacts': {
                'simulation_attestation_export': attestation_export,
                'simulation_review_audit_export': review_audit_export,
            },
            'observed_versions': dict(simulation.get('observed_versions') or {}),
            'fingerprints': dict(simulation.get('fingerprints') or {}),
            'simulation_policy': dict(simulation.get('simulation_policy') or {}),
            'review_state': dict(simulation.get('review_state') or {}),
            'created_promotions': [dict(item) for item in list(simulation.get('created_promotions') or [])],
            'registry_entry_preview': dict(registry_entry),
            'retention': retention,
            'escrow_policy': dict(escrow_policy),
        }
        integrity = self._portfolio_evidence_integrity(
            report_type=package_payload['report_type'],
            scope=dict(package_payload.get('scope') or {}),
            payload=package_payload,
            actor=actor,
            export_policy=export_policy,
            signing_policy=self._baseline_promotion_simulation_effective_signing_policy(simulation=simulation),
        )
        artifact = self._build_baseline_promotion_simulation_evidence_artifact_archive(
            package_payload=package_payload,
            integrity=integrity,
            export_policy=export_policy,
        )
        escrow = self._archive_baseline_promotion_simulation_evidence_artifact_external(
            artifact=artifact,
            package_payload=package_payload,
            integrity=integrity,
            retention=retention,
            actor=actor,
            escrow_policy=escrow_policy,
            signing_policy=self._baseline_promotion_simulation_effective_signing_policy(simulation=simulation),
            generated_at=generated_at,
        )
        if bool(escrow_policy.get('enabled')) and bool(escrow_policy.get('require_archive_on_export', True)) and not bool(escrow.get('archived')):
            if not bool(escrow_policy.get('allow_inline_fallback', True)):
                return {
                    'ok': False,
                    'error': 'baseline_promotion_simulation_evidence_escrow_failed',
                    'promotion_id': str(release.get('release_id') or ''),
                    'package_id': package_id,
                    'escrow': escrow,
                }
        artifact_record = dict(artifact)
        if not bool(export_policy.get('embed_artifact_content', True)):
            artifact_record.pop('content_b64', None)
        if escrow.get('archived'):
            artifact_record['escrow'] = self._redact_large_blob(dict(escrow or {}))
        package_record = {
            'package_id': package_id,
            'created_at': float(package_payload.get('generated_at') or time.time()),
            'created_by': str(actor or 'system'),
            'report_type': package_payload['report_type'],
            'simulation_id': str(simulation.get('simulation_id') or ''),
            'manifest_hash': manifest_hash,
            'payload_hash': integrity.get('payload_hash'),
            'signature': integrity.get('signature'),
            'signature_scheme': integrity.get('signature_scheme'),
            'signer_key_id': integrity.get('signer_key_id'),
            'signer_provider': integrity.get('signer_provider'),
            'retention': dict(package_payload.get('retention') or {}),
            'source_simulation': {
                'simulation_id': str(simulation.get('simulation_id') or ''),
            },
            'source_promotion': dict(package_payload.get('source_promotion') or {}),
            'artifact': artifact_record,
            'escrow': self._redact_large_blob(dict(escrow or {})) if escrow else {},
            'registry_entry': {
                'entry_id': str(registry_entry.get('entry_id') or ''),
                'sequence': int(registry_entry.get('sequence') or 0),
                'entry_hash': str(registry_entry.get('entry_hash') or ''),
                'previous_entry_hash': str(registry_entry.get('previous_entry_hash') or ''),
                'immutable': True,
                'immutable_until': registry_entry.get('immutable_until'),
            },
            'attestation': {
                'report_id': str(((attestation_export.get('report') or {}).get('report_id') or '')),
                'report_type': str(((attestation_export.get('report') or {}).get('report_type') or '')),
            },
            'review_audit': {
                'report_id': str(((review_audit_export.get('report') or {}).get('report_id') or '')),
                'report_type': str(((review_audit_export.get('report') or {}).get('report_type') or '')),
            },
        }
        return {
            'ok': True,
            'package_id': package_id,
            'package': package_payload,
            'integrity': integrity,
            'artifact': artifact,
            'escrow': self._redact_large_blob(dict(escrow or {})) if escrow else {},
            'registry_entry': registry_entry,
            'package_record': package_record,
            'scope': dict(package_payload.get('scope') or {}),
        }

    def _find_baseline_promotion_simulation_evidence_package(
        self,
        release: dict[str, Any] | None,
        *,
        package_id: str | None = None,
        include_content: bool = False,
    ) -> dict[str, Any] | None:
        packages = self._list_baseline_promotion_simulation_evidence_packages(release, include_content=include_content)
        target_package_id = str(package_id or '').strip()
        if not packages:
            return None
        if not target_package_id:
            return dict(packages[0])
        for item in packages:
            if str(item.get('package_id') or '') == target_package_id:
                return dict(item)
        return None

    def _decode_baseline_promotion_simulation_evidence_artifact_input(
        self,
        *,
        artifact: dict[str, Any] | None = None,
        artifact_b64: str | None = None,
    ) -> dict[str, Any]:
        source = dict(artifact or {})
        encoded = artifact_b64 if artifact_b64 is not None else source.get('content_b64')
        if not encoded:
            return {'ok': False, 'error': 'baseline_promotion_simulation_evidence_artifact_missing'}
        try:
            archive_bytes = base64.b64decode(str(encoded).encode('ascii'))
        except Exception:
            return {'ok': False, 'error': 'baseline_promotion_simulation_evidence_artifact_decode_failed'}
        archive_sha256 = hashlib.sha256(archive_bytes).hexdigest()
        try:
            with zipfile.ZipFile(io.BytesIO(archive_bytes), mode='r') as zf:
                parsed_entries: dict[str, Any] = {}
                for name in zf.namelist():
                    try:
                        parsed_entries[name] = json.loads(zf.read(name).decode('utf-8'))
                    except Exception:
                        parsed_entries[name] = None
        except Exception:
            return {'ok': False, 'error': 'baseline_promotion_simulation_evidence_artifact_invalid_archive'}
        return {
            'ok': True,
            'archive_bytes': archive_bytes,
            'archive_sha256': archive_sha256,
            'artifact': source,
            'entries': parsed_entries,
        }

    def _verify_baseline_promotion_simulation_evidence_artifact_payload(
        self,
        *,
        artifact: dict[str, Any] | None = None,
        artifact_b64: str | None = None,
        registry_entries: list[dict[str, Any]] | None = None,
        stored_package: dict[str, Any] | None = None,
        now_ts: float | None = None,
    ) -> dict[str, Any]:
        resolved_artifact = dict(artifact or {})
        stored = dict(stored_package or {})
        escrow_meta = dict(resolved_artifact.get('escrow') or stored.get('escrow') or {})
        artifact_source = 'inline'
        if artifact_b64 is None and not str(resolved_artifact.get('content_b64') or '').strip() and escrow_meta:
            loaded_artifact = self._load_baseline_promotion_simulation_evidence_artifact_from_escrow(escrow=escrow_meta)
            if loaded_artifact is not None:
                resolved_artifact = loaded_artifact
                artifact_source = 'escrow'
        decoded = self._decode_baseline_promotion_simulation_evidence_artifact_input(artifact=resolved_artifact, artifact_b64=artifact_b64)
        if not decoded.get('ok'):
            return decoded
        artifact_meta = dict(decoded.get('artifact') or {})
        entries = dict(decoded.get('entries') or {})
        package_payload = dict(entries.get('package.json') or {})
        integrity = dict(entries.get('integrity.json') or {})
        manifest_entry = dict(entries.get('manifest.json') or {})
        attestation_export = dict(entries.get('simulation_attestation_export.json') or {})
        review_audit_export = dict(entries.get('simulation_review_audit_export.json') or {})
        registry_entry = dict(entries.get('registry_entry.json') or (package_payload.get('registry_entry_preview') or {}))
        if not package_payload or not integrity or not manifest_entry or not attestation_export or not review_audit_export or not registry_entry:
            return {'ok': False, 'error': 'baseline_promotion_simulation_evidence_artifact_incomplete'}

        provided_archive_hash = str(artifact_meta.get('sha256') or '').strip()
        archive_hash_valid = not provided_archive_hash or provided_archive_hash == str(decoded.get('archive_sha256') or '')
        archive_size_valid = artifact_meta.get('size_bytes') is None or int(artifact_meta.get('size_bytes') or 0) == len(decoded.get('archive_bytes') or b'')

        manifest_from_package = dict(package_payload.get('manifest') or {})
        manifest_hash = str(manifest_from_package.get('manifest_hash') or manifest_entry.get('manifest_hash') or '').strip()
        manifest_payload = dict(manifest_entry)
        manifest_payload.pop('manifest_hash', None)
        package_manifest_payload = dict(manifest_from_package)
        package_manifest_payload.pop('manifest_hash', None)
        expected_manifest_hash = self._stable_digest(manifest_payload)
        manifest_hash_valid = bool(manifest_hash) and manifest_hash == expected_manifest_hash and package_manifest_payload == manifest_payload

        attestation_verify = self._verify_portfolio_export_integrity(
            report_type=str(((attestation_export.get('report') or {}).get('report_type')) or ''),
            scope=dict(attestation_export.get('scope') or {}),
            payload=dict(attestation_export.get('report') or {}),
            integrity=dict(attestation_export.get('integrity') or {}),
        )
        review_audit_verify = self._verify_portfolio_export_integrity(
            report_type=str(((review_audit_export.get('report') or {}).get('report_type')) or ''),
            scope=dict(review_audit_export.get('scope') or {}),
            payload=dict(review_audit_export.get('report') or {}),
            integrity=dict(review_audit_export.get('integrity') or {}),
        )
        package_verify = self._verify_portfolio_export_integrity(
            report_type=str(package_payload.get('report_type') or ''),
            scope=dict(package_payload.get('scope') or {}),
            payload=dict(package_payload),
            integrity=integrity,
        )

        manifest_artifacts = {str(item.get('artifact_id') or ''): dict(item) for item in list(manifest_payload.get('artifacts') or [])}
        attestation_report = dict(attestation_export.get('report') or {})
        review_audit_report = dict(review_audit_export.get('report') or {})
        manifest_links_valid = (
            manifest_artifacts.get(str(attestation_report.get('report_id') or ''), {}).get('payload_hash') == ((attestation_export.get('integrity') or {}).get('payload_hash'))
            and manifest_artifacts.get(str(review_audit_report.get('report_id') or ''), {}).get('payload_hash') == ((review_audit_export.get('integrity') or {}).get('payload_hash'))
        )

        registry_entry_preview = dict(package_payload.get('registry_entry_preview') or {})
        registry_payload_match_valid = not registry_entry_preview or registry_entry_preview == registry_entry
        entry_core = dict(registry_entry.get('entry_core') or {})
        if not entry_core:
            entry_core = {
                key: value
                for key, value in registry_entry.items()
                if key not in {'entry_hash', 'entry_core'}
            }
        expected_entry_hash = self._stable_digest(entry_core) if entry_core else ''
        registry_entry_hash_valid = bool(expected_entry_hash) and str(registry_entry.get('entry_hash') or '') == expected_entry_hash

        sorted_registry_entries = [dict(item) for item in list(registry_entries or [])]
        sorted_registry_entries.sort(key=lambda item: (int(item.get('sequence') or 0), float(item.get('appended_at') or 0.0), str(item.get('entry_id') or '')))
        registry_chain_valid = True
        previous_hash = ''
        for pos, item in enumerate(sorted_registry_entries, start=1):
            item_core = dict(item.get('entry_core') or {
                key: value for key, value in item.items() if key not in {'entry_hash', 'entry_core'}
            })
            if int(item.get('sequence') or 0) != pos:
                registry_chain_valid = False
            if str(item.get('previous_entry_hash') or '') != previous_hash:
                registry_chain_valid = False
            if self._stable_digest(item_core) != str(item.get('entry_hash') or ''):
                registry_chain_valid = False
            previous_hash = str(item.get('entry_hash') or '')

        matching_registry_entry = None
        for item in sorted_registry_entries:
            if str(item.get('entry_id') or '') == str(registry_entry.get('entry_id') or ''):
                matching_registry_entry = dict(item)
                break
        registry_membership_valid = matching_registry_entry is not None if sorted_registry_entries else True
        registry_match_valid = True
        if matching_registry_entry is not None:
            compare_keys = ['entry_id', 'sequence', 'package_id', 'simulation_id', 'manifest_hash', 'entry_hash', 'previous_entry_hash', 'immutable', 'registry_mode']
            registry_match_valid = all(matching_registry_entry.get(key) == registry_entry.get(key) for key in compare_keys)
            registry_match_valid = registry_match_valid and dict(matching_registry_entry.get('entry_core') or entry_core) == dict(entry_core)

        stored_package_match_valid = True
        if stored:
            stored_package_match_valid = str(stored.get('package_id') or '') == str(package_payload.get('package_id') or '')
            stored_package_match_valid = stored_package_match_valid and str(stored.get('manifest_hash') or '') == str(manifest_hash or '')
            stored_artifact = dict(stored.get('artifact') or {})
            stored_sha = str(stored_artifact.get('sha256') or '').strip()
            if stored_sha:
                stored_package_match_valid = stored_package_match_valid and stored_sha == str(decoded.get('archive_sha256') or '')
        escrow_verify = self._verify_baseline_promotion_simulation_escrow_receipt(escrow=escrow_meta, now_ts=now_ts) if escrow_meta else {'required': False, 'valid': True, 'status': 'not_archived'}

        checks = {
            'archive_hash_valid': archive_hash_valid,
            'archive_size_valid': archive_size_valid,
            'manifest_hash_valid': manifest_hash_valid,
            'manifest_links_valid': manifest_links_valid,
            'attestation_export_valid': bool(attestation_verify.get('valid')),
            'review_audit_export_valid': bool(review_audit_verify.get('valid')),
            'package_integrity_valid': bool(package_verify.get('valid')),
            'escrow_receipt_valid': bool(escrow_verify.get('valid', True)),
            'registry_payload_match_valid': registry_payload_match_valid,
            'registry_entry_hash_valid': registry_entry_hash_valid,
            'registry_membership_valid': registry_membership_valid,
            'registry_match_valid': registry_match_valid,
            'registry_chain_valid': registry_chain_valid,
            'stored_package_match_valid': stored_package_match_valid,
        }
        failures = [name for name, value in checks.items() if not value]
        status = 'verified' if not failures else 'failed'
        immutable_until = registry_entry.get('immutable_until')
        try:
            immutable_active = bool(registry_entry.get('immutable')) and immutable_until is not None and float(immutable_until) >= float(now_ts if now_ts is not None else time.time())
        except Exception:
            immutable_active = bool(registry_entry.get('immutable'))
        return {
            'ok': True,
            'package_id': str(package_payload.get('package_id') or '').strip() or None,
            'simulation_id': str(((package_payload.get('simulation') or {}).get('simulation_id')) or '').strip() or None,
            'artifact': {
                **{k: v for k, v in artifact_meta.items() if k != 'content_b64'},
                'sha256': decoded.get('archive_sha256'),
                'size_bytes': len(decoded.get('archive_bytes') or b''),
                'source': artifact_source,
            },
            'package': package_payload,
            'integrity': integrity,
            'verification': {
                'status': status,
                'valid': status == 'verified',
                'restorable': status == 'verified',
                'checks': checks,
                'failures': failures,
                'manifest': {
                    'manifest_hash': manifest_hash,
                    'expected_manifest_hash': expected_manifest_hash,
                    'valid': manifest_hash_valid,
                    'artifact_links_valid': manifest_links_valid,
                },
                'attestation_export': attestation_verify,
                'review_audit_export': review_audit_verify,
                'package_integrity': package_verify,
                'escrow': escrow_verify,
                'registry': {
                    'entry_id': str(registry_entry.get('entry_id') or ''),
                    'sequence': int(registry_entry.get('sequence') or 0),
                    'entry_hash': str(registry_entry.get('entry_hash') or ''),
                    'previous_entry_hash': str(registry_entry.get('previous_entry_hash') or ''),
                    'manifest_hash': str(registry_entry.get('manifest_hash') or ''),
                    'immutable': bool(registry_entry.get('immutable')),
                    'immutable_until': immutable_until,
                    'immutable_active': immutable_active,
                    'membership_valid': registry_membership_valid,
                    'match_valid': registry_match_valid,
                    'chain_valid': registry_chain_valid,
                },
                'stored_package_match_valid': stored_package_match_valid,
            },
            'restored_entries': {
                'simulation_attestation_export': attestation_export,
                'simulation_review_audit_export': review_audit_export,
                'registry_entry': registry_entry,
            },
            'registry_entry': registry_entry,
            'escrow': self._redact_large_blob(escrow_meta) if escrow_meta else {},
            'stored_package': {k: v for k, v in stored.items() if k != 'artifact'} if stored else {},
        }

    def _restore_baseline_promotion_simulation_from_evidence_verification(
        self,
        *,
        verification: dict[str, Any],
    ) -> dict[str, Any]:
        attestation_export = dict(((verification.get('restored_entries') or {}).get('simulation_attestation_export')) or {})
        review_audit_export = dict(((verification.get('restored_entries') or {}).get('simulation_review_audit_export')) or {})
        package_payload = dict(verification.get('package') or {})
        attestation_report = dict(attestation_export.get('report') or {})
        review_audit_report = dict(review_audit_export.get('report') or {})
        simulation_meta = dict(attestation_report.get('simulation') or {})
        review_state = dict(attestation_report.get('review_state') or {})
        review_state.setdefault('overall_status', str((review_audit_report.get('review_sequence') or {}).get('overall_status') or review_state.get('overall_status') or ''))
        review_state.setdefault('items', [dict(item) for item in list((review_audit_report.get('ordered_reviews') or []))])
        restored = {
            'simulation_id': str(simulation_meta.get('simulation_id') or ((package_payload.get('simulation') or {}).get('simulation_id')) or ''),
            'mode': str(simulation_meta.get('mode') or ''),
            'simulation_status': str(simulation_meta.get('simulation_status') or ''),
            'simulated_at': simulation_meta.get('simulated_at'),
            'simulated_by': simulation_meta.get('simulated_by'),
            'reviewed_at': simulation_meta.get('reviewed_at') or ((review_audit_report.get('simulation') or {}).get('reviewed_at')),
            'stale': bool(simulation_meta.get('stale')),
            'expired': bool(simulation_meta.get('expired')),
            'blocked': bool(simulation_meta.get('blocked')),
            'why_blocked': str(simulation_meta.get('why_blocked') or ''),
            'catalog_id': str(simulation_meta.get('catalog_id') or ((package_payload.get('simulation') or {}).get('catalog_id')) or ''),
            'catalog_name': str(simulation_meta.get('catalog_name') or ''),
            'candidate_catalog_version': str(simulation_meta.get('candidate_catalog_version') or ((package_payload.get('simulation') or {}).get('candidate_catalog_version')) or ''),
            'scope': dict(attestation_report.get('scope') or package_payload.get('scope') or {}),
            'simulation_source': dict(attestation_report.get('source') or {}),
            'request': dict(attestation_report.get('request') or {}),
            'candidate_baselines': dict(((attestation_report.get('request') or {}).get('candidate_baselines') or {})),
            'summary': dict(attestation_report.get('summary') or {}),
            'validation': dict(attestation_report.get('validation') or {}),
            'approval_preview': dict(attestation_report.get('approval_preview') or {}),
            'simulation_policy': dict(attestation_report.get('simulation_policy') or {}),
            'review': dict(attestation_report.get('review') or review_audit_report.get('review_summary') or {}),
            'review_state': review_state,
            'observed_context': dict(attestation_report.get('observed_context') or {}),
            'observed_versions': dict(attestation_report.get('observed_versions') or {}),
            'source_observed_versions': dict(attestation_report.get('observed_versions') or {}),
            'fingerprints': dict(attestation_report.get('fingerprints') or {}),
            'source_fingerprints': dict(attestation_report.get('fingerprints') or {}),
            'diff': dict(attestation_report.get('diff') or {}),
            'explainability': dict(attestation_report.get('explainability') or {}),
            'created_promotions': [dict(item) for item in list(attestation_report.get('created_promotions') or package_payload.get('created_promotions') or [])],
            'timeline': [
                dict(item)
                for item in list(((attestation_report.get('timeline') or {}).get('items') if isinstance(attestation_report.get('timeline'), dict) else attestation_report.get('timeline')) or [])
            ],
            'export_state': {
                'attestation_count': 1,
                'review_audit_count': 1,
                'evidence_package_count': 1,
                'latest_attestation': {
                    'report_id': str(attestation_report.get('report_id') or ''),
                    'report_type': str(attestation_report.get('report_type') or ''),
                    'generated_at': attestation_report.get('generated_at'),
                    'generated_by': attestation_report.get('generated_by'),
                    'integrity': dict(attestation_export.get('integrity') or {}),
                },
                'latest_review_audit': {
                    'report_id': str(review_audit_report.get('report_id') or ''),
                    'report_type': str(review_audit_report.get('report_type') or ''),
                    'generated_at': review_audit_report.get('generated_at'),
                    'generated_by': review_audit_report.get('generated_by'),
                    'integrity': dict(review_audit_export.get('integrity') or {}),
                },
                'latest_evidence_package': {
                    'package_id': str(package_payload.get('package_id') or ''),
                    'report_type': str(package_payload.get('report_type') or ''),
                    'generated_at': package_payload.get('generated_at'),
                    'generated_by': package_payload.get('generated_by'),
                    'integrity': dict(verification.get('integrity') or {}),
                    'artifact': {
                        'artifact_type': str(((verification.get('artifact') or {}).get('artifact_type')) or ''),
                        'sha256': str(((verification.get('artifact') or {}).get('sha256')) or ''),
                        'size_bytes': int(((verification.get('artifact') or {}).get('size_bytes')) or 0),
                        'filename': str(((verification.get('artifact') or {}).get('filename')) or ''),
                        'source': str(((verification.get('artifact') or {}).get('source')) or ''),
                    },
                    'registry_entry': {
                        'entry_id': str(((verification.get('registry_entry') or {}).get('entry_id')) or ''),
                        'sequence': int(((verification.get('registry_entry') or {}).get('sequence')) or 0),
                        'entry_hash': str(((verification.get('registry_entry') or {}).get('entry_hash')) or ''),
                        'previous_entry_hash': str(((verification.get('registry_entry') or {}).get('previous_entry_hash')) or ''),
                        'immutable': bool(((verification.get('registry_entry') or {}).get('immutable'))),
                    },
                    'escrow': dict(verification.get('escrow') or {}),
                },
                'registry_summary': {
                    'count': int(((verification.get('verification') or {}).get('registry') or {}).get('sequence') or 0),
                    'latest_entry_id': str(((verification.get('registry_entry') or {}).get('entry_id')) or ''),
                    'latest_package_id': str(package_payload.get('package_id') or ''),
                    'latest_entry_hash': str(((verification.get('registry_entry') or {}).get('entry_hash')) or ''),
                    'chain_ok': bool((((verification.get('verification') or {}).get('registry') or {}).get('chain_valid'))),
                },
            },
            'restore_context': {
                'restored_from_package_id': str(package_payload.get('package_id') or ''),
                'artifact_sha256': str(((verification.get('artifact') or {}).get('sha256')) or ''),
                'registry_entry_id': str(((verification.get('registry_entry') or {}).get('entry_id')) or ''),
                'registry_sequence': int(((verification.get('registry_entry') or {}).get('sequence')) or 0),
            },
        }
        return restored

    def _list_baseline_promotion_simulation_restore_sessions(self, release: dict[str, Any] | None) -> list[dict[str, Any]]:
        metadata = dict((release or {}).get('metadata') or {})
        promotion = dict(metadata.get('baseline_promotion') or {})
        items = [dict(item) for item in list(promotion.get('simulation_restore_sessions') or [])]
        items.sort(key=lambda item: (float(item.get('restored_at') or 0.0), str(item.get('restore_id') or '')), reverse=True)
        return items

    def _store_baseline_promotion_simulation_restore_session(
        self,
        gw,
        *,
        release: dict[str, Any],
        session_record: dict[str, Any],
        restore_history_limit: int = 20,
    ) -> dict[str, Any]:
        metadata = dict(release.get('metadata') or {})
        promotion = dict(metadata.get('baseline_promotion') or {})
        sessions = [dict(item) for item in list(promotion.get('simulation_restore_sessions') or [])]
        sessions = [item for item in sessions if str(item.get('restore_id') or '') != str(session_record.get('restore_id') or '')]
        sessions.append(dict(session_record))
        sessions.sort(key=lambda item: (float(item.get('restored_at') or 0.0), str(item.get('restore_id') or '')), reverse=True)
        promotion['simulation_restore_sessions'] = sessions[: max(1, int(restore_history_limit or 20))]
        promotion = self._append_baseline_promotion_timeline_event(
            promotion,
            kind='evidence',
            label='baseline_promotion_simulation_evidence_restored',
            actor=str(session_record.get('restored_by') or 'system'),
            restore_id=str(session_record.get('restore_id') or ''),
            package_id=str(session_record.get('package_id') or ''),
            simulation_id=str(session_record.get('simulation_id') or ''),
            replay_status=str(((session_record.get('replay') or {}).get('simulation_status')) or ''),
            artifact_sha256=str(session_record.get('artifact_sha256') or ''),
        )
        metadata['baseline_promotion'] = promotion
        return gw.audit.update_release_bundle(
            str(release.get('release_id') or ''),
            status=release.get('status'),
            notes=release.get('notes'),
            metadata=metadata,
            tenant_id=release.get('tenant_id'),
            workspace_id=release.get('workspace_id'),
            environment=release.get('environment'),
        ) or release

    def _build_baseline_promotion_rollback_attestation(
        self,
        *,
        promotion_release: dict[str, Any],
        promotion: dict[str, Any],
        actor: str,
        reason: str = '',
        trigger: str = 'manual',
        wave_no: int | None = None,
        affected_portfolio_ids: list[str] | None = None,
        rollout_plan: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        created_at = time.time()
        resolved_promotion = dict(promotion or {})
        resolved_rollout_plan = self._refresh_baseline_promotion_rollout_plan(dict(rollout_plan or resolved_promotion.get('rollout_plan') or {}))
        affected_ids = self._baseline_promotion_unique_ids(list(affected_portfolio_ids or []))
        attestation = {
            'attestation_id': f'baseline-rollback-{str(promotion_release.get("release_id") or "")}-{int(created_at)}',
            'report_type': 'openmiura_baseline_promotion_rollback_attestation_v1',
            'generated_at': created_at,
            'generated_by': str(actor or 'admin'),
            'created_at': created_at,
            'created_by': str(actor or 'admin'),
            'trigger': str(trigger or 'manual'),
            'reason': str(reason or '').strip(),
            'wave_no': int(wave_no or 0) if wave_no is not None else None,
            'promotion_id': str(promotion_release.get('release_id') or ''),
            'promotion_status_before': str(promotion_release.get('status') or ''),
            'catalog_id': str(resolved_promotion.get('catalog_id') or ''),
            'catalog_name': str(resolved_promotion.get('catalog_name') or ''),
            'candidate_catalog_version': str(resolved_promotion.get('candidate_catalog_version') or promotion_release.get('version') or ''),
            'previous_catalog_version': str(resolved_promotion.get('previous_catalog_version') or ''),
            'scope': self._scope(tenant_id=promotion_release.get('tenant_id'), workspace_id=promotion_release.get('workspace_id'), environment=promotion_release.get('environment')),
            'affected_portfolio_ids': affected_ids,
            'affected_portfolio_count': len(affected_ids),
            'rollout': {
                'wave_count': int(resolved_rollout_plan.get('wave_count') or 0),
                'completed_wave_count': int(resolved_rollout_plan.get('completed_wave_count') or 0),
                'applied_portfolio_ids': list(resolved_rollout_plan.get('applied_portfolio_ids') or []),
                'rolled_back_portfolio_ids': affected_ids,
                'summary': dict(resolved_rollout_plan.get('summary') or {}),
            },
            'rollback_policy': dict(((resolved_promotion.get('promotion_policy') or {}).get('rollback_policy') or {})),
            'timeline_summary': {
                'count': len(list(resolved_promotion.get('timeline') or [])),
                'last_label': ((list(resolved_promotion.get('timeline') or []) or [{}])[-1].get('label')) if list(resolved_promotion.get('timeline') or []) else None,
            },
        }
        attestation['integrity'] = self._portfolio_evidence_integrity(
            report_type=str(attestation.get('report_type') or 'openmiura_baseline_promotion_rollback_attestation_v1'),
            scope=dict(attestation.get('scope') or {}),
            payload=dict(attestation),
            actor=actor,
            export_policy=self._baseline_promotion_export_policy(promotion_release=promotion_release, promotion=resolved_promotion),
            signing_policy=self._baseline_promotion_effective_signing_policy(promotion_release=promotion_release, promotion=resolved_promotion),
        )
        return attestation

    def _build_baseline_promotion_attestation_export_payload(
        self,
        *,
        detail: dict[str, Any],
        actor: str,
        timeline_limit: int | None = None,
    ) -> dict[str, Any]:
        release = dict(detail.get('release') or {})
        promotion = dict(detail.get('baseline_promotion') or {})
        export_policy = self._baseline_promotion_export_policy(promotion_release=release, promotion=promotion)
        signing_policy = self._baseline_promotion_effective_signing_policy(promotion_release=release, promotion=promotion)
        timeline = self._baseline_promotion_timeline_view(release, limit=max(25, int(timeline_limit or export_policy.get('timeline_limit') or 250)))
        report = {
            'report_type': 'openmiura_baseline_promotion_attestation_export_v1',
            'generated_at': time.time(),
            'generated_by': str(actor or 'system'),
            'promotion': {
                'promotion_id': str(detail.get('promotion_id') or release.get('release_id') or ''),
                'name': release.get('name'),
                'version': release.get('version'),
                'status': release.get('status'),
                'catalog_id': promotion.get('catalog_id'),
                'catalog_name': promotion.get('catalog_name'),
                'previous_catalog_version': promotion.get('previous_catalog_version'),
                'candidate_catalog_version': promotion.get('candidate_catalog_version'),
            },
            'scope': dict(detail.get('scope') or {}),
            'approvals': dict(detail.get('approvals') or {}),
            'rollout_plan': dict(promotion.get('rollout_plan') or {}),
            'rollout_impact': dict(promotion.get('rollout_impact') or {}),
            'promotion_policy': dict(promotion.get('promotion_policy') or {}),
            'analytics': dict(detail.get('analytics') or {}),
            'advance_jobs': dict(detail.get('advance_jobs') or {}),
            'rollback_attestations': dict(detail.get('rollback_attestations') or {}),
            'timeline': timeline,
            'catalog': {
                'catalog_id': ((detail.get('catalog') or {}).get('catalog_id')),
                'current_version': (((detail.get('catalog') or {}).get('baseline_catalog') or {}).get('current_version')),
            },
            'created_from_simulation': dict(promotion.get('created_from_simulation') or {}),
        }
        integrity = self._portfolio_evidence_integrity(
            report_type=report['report_type'],
            scope=dict(detail.get('scope') or {}),
            payload=report,
            actor=actor,
            export_policy=export_policy,
            signing_policy=signing_policy,
        )
        return {
            'ok': True,
            'promotion_id': detail.get('promotion_id') or release.get('release_id'),
            'report': report,
            'integrity': integrity,
            'scope': detail.get('scope'),
        }

    def _build_baseline_promotion_postmortem_export_payload(
        self,
        *,
        detail: dict[str, Any],
        actor: str,
        timeline_limit: int | None = None,
    ) -> dict[str, Any]:
        release = dict(detail.get('release') or {})
        promotion = dict(detail.get('baseline_promotion') or {})
        analytics = dict(detail.get('analytics') or {})
        export_policy = self._baseline_promotion_export_policy(promotion_release=release, promotion=promotion)
        signing_policy = self._baseline_promotion_effective_signing_policy(promotion_release=release, promotion=promotion)
        replay_limit = max(25, int(timeline_limit or export_policy.get('timeline_limit') or 250))
        timeline = self._baseline_promotion_timeline_view(release, limit=replay_limit)
        rollback_items = [dict(item) for item in list(((detail.get('rollback_attestations') or {}).get('items') or []))]
        latest_rollback = rollback_items[-1] if rollback_items else None
        report = {
            'report_type': 'openmiura_baseline_promotion_postmortem_v1',
            'generated_at': time.time(),
            'generated_by': str(actor or 'system'),
            'promotion': {
                'promotion_id': str(detail.get('promotion_id') or release.get('release_id') or ''),
                'name': release.get('name'),
                'version': release.get('version'),
                'status': release.get('status'),
                'catalog_id': promotion.get('catalog_id'),
                'catalog_name': promotion.get('catalog_name'),
                'previous_catalog_version': promotion.get('previous_catalog_version'),
                'candidate_catalog_version': promotion.get('candidate_catalog_version'),
            },
            'scope': dict(detail.get('scope') or {}),
            'summary': {
                'final_status': str(release.get('status') or ''),
                'gate_failed': bool(analytics.get('gate_failed')),
                'gate_failed_wave_no': analytics.get('gate_failed_wave_no'),
                'completed_wave_count': int(analytics.get('completed_wave_count') or 0),
                'wave_count': int(analytics.get('wave_count') or 0),
                'rollback_attestation_count': len(rollback_items),
                'dependency_blocked_wave_count': int(analytics.get('dependency_blocked_wave_count') or 0),
                'due_advance_job_count': int(analytics.get('due_advance_job_count') or 0),
            },
            'analytics': analytics,
            'approvals': dict(detail.get('approvals') or {}),
            'advance_jobs': dict(detail.get('advance_jobs') or {}),
            'rollout_plan': dict(promotion.get('rollout_plan') or {}),
            'rollout_impact': dict(promotion.get('rollout_impact') or {}),
            'timeline': timeline,
            'rollback': {
                'rolled_back': str(release.get('status') or '') == 'rolled_back',
                'latest_attestation': latest_rollback,
                'attestation_ids': [item.get('attestation_id') for item in rollback_items],
                'items': rollback_items,
            },
            'latest_health': analytics.get('latest_health'),
            'wave_health_curve': list(analytics.get('wave_health_curve') or []),
            'gate_reason_counts': dict(analytics.get('gate_reason_counts') or {}),
            'catalog': detail.get('catalog'),
        }
        integrity = self._portfolio_evidence_integrity(
            report_type=report['report_type'],
            scope=dict(detail.get('scope') or {}),
            payload=report,
            actor=actor,
            export_policy=export_policy,
            signing_policy=signing_policy,
        )
        return {
            'ok': True,
            'promotion_id': detail.get('promotion_id') or release.get('release_id'),
            'report': report,
            'integrity': integrity,
            'scope': detail.get('scope'),
        }

    def export_runtime_alert_governance_baseline_promotion_attestation(
        self,
        gw,
        *,
        promotion_id: str,
        actor: str,
        timeline_limit: int | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        detail = self.get_runtime_alert_governance_baseline_promotion(
            gw,
            promotion_id=promotion_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        if not detail.get('ok'):
            return detail
        return self._build_baseline_promotion_attestation_export_payload(detail=detail, actor=actor, timeline_limit=timeline_limit)

    def export_runtime_alert_governance_baseline_promotion_postmortem(
        self,
        gw,
        *,
        promotion_id: str,
        actor: str,
        timeline_limit: int | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        detail = self.get_runtime_alert_governance_baseline_promotion(
            gw,
            promotion_id=promotion_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        if not detail.get('ok'):
            return detail
        return self._build_baseline_promotion_postmortem_export_payload(detail=detail, actor=actor, timeline_limit=timeline_limit)



