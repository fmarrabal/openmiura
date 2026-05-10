"""service._policy_mixin"""
from __future__ import annotations

import copy
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from openmiura.core.secrets import SecretAccessDenied, SecretBrokerError



OpenClawAdapterService: type | None = None  # late-bound


class _OpenClawAdapterServicePolicyMixin:
    """Sub-mixin: policy."""

    @classmethod
    def _policy_pack_spec(cls, pack_name: str | None = None, *, runtime_class: str | None = None, transport: str = 'http') -> dict[str, Any]:
        candidate = cls._normalize_runtime_class(pack_name or runtime_class, transport=transport)
        spec = cls.POLICY_PACKS.get(candidate)
        if spec is None:
            fallback = cls._normalize_runtime_class(runtime_class, transport=transport)
            spec = cls.POLICY_PACKS.get(fallback) or cls.POLICY_PACKS['generic_async_worker']
            candidate = fallback if fallback in cls.POLICY_PACKS else 'generic_async_worker'
        enriched = copy.deepcopy(spec)
        enriched['id'] = candidate
        return enriched

    @classmethod
    def _policy_pack_id_from_metadata(cls, metadata: dict[str, Any] | None, *, transport: str = 'http') -> str:
        payload = dict(metadata or {})
        runtime_class = payload.get('runtime_class') or payload.get('kind')
        requested = payload.get('policy_pack') or runtime_class
        return cls._policy_pack_spec(requested, runtime_class=runtime_class, transport=transport).get('id', 'generic_async_worker')

    @classmethod
    def _apply_policy_pack_defaults(cls, metadata: dict[str, Any] | None, *, transport: str = 'http') -> dict[str, Any]:
        payload = copy.deepcopy(dict(metadata or {}))
        runtime_class = cls._normalize_runtime_class(payload.get('runtime_class') or payload.get('kind'), transport=transport)
        pack = cls._policy_pack_spec(payload.get('policy_pack'), runtime_class=runtime_class, transport=transport)
        merged = cls._deep_merge(dict(pack.get('metadata') or {}), payload)
        merged['runtime_class'] = runtime_class
        merged['policy_pack'] = str(pack.get('id') or runtime_class)
        return merged

    def list_policy_packs(self, *, runtime_class: str | None = None, transport: str = 'http') -> dict[str, Any]:
        items = []
        selected = self._normalize_runtime_class(runtime_class, transport=transport) if runtime_class else ''
        for pack_id, spec in sorted(self.POLICY_PACKS.items()):
            if selected and pack_id != selected and selected not in set(spec.get('runtime_classes') or []):
                continue
            items.append({
                'pack_id': pack_id,
                'description': spec.get('description'),
                'runtime_classes': list(spec.get('runtime_classes') or []),
                'scheduler': copy.deepcopy(spec.get('scheduler') or {}),
                'metadata': copy.deepcopy(spec.get('metadata') or {}),
            })
        return {'ok': True, 'items': items, 'summary': {'count': len(items), 'runtime_class': selected or None}}

    def preview_policy_pack(self, *, pack_name: str | None = None, runtime_class: str | None = None, transport: str = 'http', metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        current = dict(metadata or {})
        runtime_seed = runtime_class or pack_name or current.get('runtime_class') or current.get('kind')
        runtime_class_id = self._normalize_runtime_class(runtime_seed, transport=transport)
        pack = self._policy_pack_spec(pack_name or current.get('policy_pack'), runtime_class=runtime_class_id, transport=transport)
        merged = self._deep_merge(dict(pack.get('metadata') or {}), current)
        merged['runtime_class'] = runtime_class_id
        merged['policy_pack'] = str(pack.get('id') or runtime_class_id)
        return {
            'ok': True,
            'pack': {
                'pack_id': str(pack.get('id') or runtime_class_id),
                'description': pack.get('description'),
                'runtime_classes': list(pack.get('runtime_classes') or []),
                'scheduler': copy.deepcopy(pack.get('scheduler') or {}),
            },
            'metadata': merged,
        }

    @classmethod
    def _alert_notification_policy(cls, runtime: dict[str, Any]) -> dict[str, Any]:
        metadata = cls._runtime_metadata(runtime)
        raw = dict(metadata.get('alert_notification_policy') or {})
        try:
            dedupe_window_s = int(raw.get('dedupe_window_s') or 300)
        except Exception:
            dedupe_window_s = 300
        try:
            max_targets_per_dispatch = int(raw.get('max_targets_per_dispatch') or 10)
        except Exception:
            max_targets_per_dispatch = 10
        return {
            **raw,
            'dispatch_on_escalate': bool(raw.get('dispatch_on_escalate', True)),
            'dispatch_on_ack': bool(raw.get('dispatch_on_ack', False)),
            'dispatch_on_silence': bool(raw.get('dispatch_on_silence', False)),
            'queue_fallback_enabled': bool(raw.get('queue_fallback_enabled', True)),
            'dedupe_window_s': max(0, dedupe_window_s),
            'max_targets_per_dispatch': max(1, max_targets_per_dispatch),
            'default_queue_name': str(raw.get('default_queue_name') or 'runtime-alerts').strip() or 'runtime-alerts',
            'default_app_target_path': str(raw.get('default_app_target_path') or '/ui/?tab=operator').strip() or '/ui/?tab=operator',
            'default_target_types': [str(item).strip().lower() for item in list(raw.get('default_target_types') or []) if str(item).strip()],
        }

    @classmethod
    def _alert_escalation_policy(cls, runtime: dict[str, Any]) -> dict[str, Any]:
        metadata = cls._runtime_metadata(runtime)
        raw = dict(metadata.get('alert_escalation_policy') or {})
        try:
            min_escalation_level = int(raw.get('min_escalation_level') or 1)
        except Exception:
            min_escalation_level = 1
        try:
            ttl_s = int(raw.get('ttl_s') or 1800)
        except Exception:
            ttl_s = 1800
        return {
            **raw,
            'enabled': bool(raw.get('enabled', bool(raw))),
            'default_requires_approval': bool(raw.get('default_requires_approval', False)),
            'required_severities': [str(item).strip().lower() for item in list(raw.get('required_severities') or []) if str(item).strip()],
            'required_alert_codes': [str(item).strip() for item in list(raw.get('required_alert_codes') or []) if str(item).strip()],
            'required_target_ids': [str(item).strip() for item in list(raw.get('required_target_ids') or []) if str(item).strip()],
            'required_target_types': [str(item).strip().lower() for item in list(raw.get('required_target_types') or []) if str(item).strip()],
            'min_escalation_level': max(1, min_escalation_level),
            'requested_role': str(raw.get('requested_role') or 'admin').strip() or 'admin',
            'ttl_s': max(60, ttl_s),
            'auto_dispatch_on_approval': bool(raw.get('auto_dispatch_on_approval', True)),
        }

    @classmethod
    def _notification_budget_policy(cls, runtime: dict[str, Any]) -> dict[str, Any]:
        metadata = cls._runtime_metadata(runtime)
        raw = dict(metadata.get('alert_notification_budget_policy') or metadata.get('notification_budget_policy') or {})
        try:
            window_s = int(raw.get('window_s') or 300)
        except Exception:
            window_s = 300
        try:
            runtime_limit = int(raw.get('runtime_limit') or 0)
        except Exception:
            runtime_limit = 0
        try:
            workspace_limit = int(raw.get('workspace_limit') or 0)
        except Exception:
            workspace_limit = 0
        try:
            schedule_after_s = int(raw.get('schedule_after_s') or 60)
        except Exception:
            schedule_after_s = 60
        on_limit = str(raw.get('on_limit') or 'schedule').strip().lower() or 'schedule'
        if on_limit not in {'schedule', 'drop'}:
            on_limit = 'schedule'
        count_statuses = [str(item).strip().lower() for item in list(raw.get('count_statuses') or ['delivered', 'queued', 'pending', 'scheduled']) if str(item).strip()]
        target_type_limits = {}
        for key, value in dict(raw.get('target_type_limits') or {}).items():
            try:
                target_type_limits[str(key).strip().lower()] = max(0, int(value or 0))
            except Exception:
                continue
        target_id_limits = {}
        for key, value in dict(raw.get('target_id_limits') or {}).items():
            try:
                target_id_limits[str(key).strip()] = max(0, int(value or 0))
            except Exception:
                continue
        return {
            **raw,
            'enabled': bool(raw.get('enabled', bool(raw))),
            'window_s': max(1, window_s),
            'runtime_limit': max(0, runtime_limit),
            'workspace_limit': max(0, workspace_limit),
            'on_limit': on_limit,
            'schedule_after_s': max(0, schedule_after_s),
            'count_statuses': count_statuses,
            'target_type_limits': target_type_limits,
            'target_id_limits': target_id_limits,
        }

    @classmethod
    def _alert_routing_policy(cls, runtime: dict[str, Any]) -> dict[str, Any]:
        metadata = cls._runtime_metadata(runtime)
        raw = dict(metadata.get('alert_routing_policy') or metadata.get('notification_routing') or {})
        try:
            default_max_retries = int(raw.get('default_max_retries') or 0)
        except Exception:
            default_max_retries = 0
        try:
            default_retry_backoff_s = int(raw.get('default_retry_backoff_s') or 300)
        except Exception:
            default_retry_backoff_s = 300
        rules: list[dict[str, Any]] = []
        for idx, item in enumerate(list(raw.get('rules') or [])):
            if not isinstance(item, dict):
                continue
            rules.append(cls._safe_json(item))
            rules[-1].setdefault('rule_id', f'route-rule-{idx + 1}')
            rules[-1].setdefault('enabled', True)
            rules[-1].setdefault('priority', len(rules))
        chains: list[dict[str, Any]] = []
        for idx, item in enumerate(list(raw.get('escalation_chains') or raw.get('chains') or [])):
            if not isinstance(item, dict):
                continue
            chains.append(cls._safe_json(item))
            chains[-1].setdefault('chain_id', f'chain-{idx + 1}')
            chains[-1].setdefault('enabled', True)
        return {
            **raw,
            'enabled': bool(raw.get('enabled', True)),
            'default_timezone': str(raw.get('default_timezone') or 'UTC').strip() or 'UTC',
            'default_max_retries': max(0, default_max_retries),
            'default_retry_backoff_s': max(0, default_retry_backoff_s),
            'rules': rules,
            'escalation_chains': chains,
        }

    @classmethod
    def _governance_release_policy(cls, runtime: dict[str, Any]) -> dict[str, Any]:
        metadata = cls._runtime_metadata(runtime)
        raw = dict(metadata.get('governance_release_policy') or metadata.get('alert_governance_release_policy') or {})
        critical_keys = [
            str(item).strip()
            for item in list(raw.get('critical_changed_keys') or ['quiet_hours', 'maintenance_windows', 'storm_policy', 'override_policies'])
            if str(item).strip()
        ]
        try:
            ttl_s = int(raw.get('ttl_s') or 3600)
        except Exception:
            ttl_s = 3600
        try:
            affected_threshold = int(raw.get('approval_on_affected_count_ge') or 0)
        except Exception:
            affected_threshold = 0
        return {
            **raw,
            'approval_required': bool(raw.get('approval_required', False)),
            'requested_role': str(raw.get('requested_role') or 'admin').strip() or 'admin',
            'ttl_s': max(60, ttl_s),
            'auto_activate_on_approval': bool(raw.get('auto_activate_on_approval', True)),
            'require_signature': bool(raw.get('require_signature', True)),
            'signer_key_id': str(raw.get('signer_key_id') or 'openmiura-local').strip() or 'openmiura-local',
            'approval_on_affected_count_ge': max(0, affected_threshold),
            'approval_on_critical_change': bool(raw.get('approval_on_critical_change', False)),
            'critical_changed_keys': critical_keys,
        }

    @classmethod
    def _alert_governance_policy(cls, runtime: dict[str, Any]) -> dict[str, Any]:
        metadata = cls._runtime_metadata(runtime)
        raw = dict(metadata.get('alert_governance_policy') or metadata.get('escalation_governance_policy') or {})
        default_timezone = str(raw.get('default_timezone') or 'UTC').strip() or 'UTC'
        quiet_raw = dict(raw.get('quiet_hours') or {})
        quiet_action = str(quiet_raw.get('action') or 'schedule').strip().lower() or 'schedule'
        if quiet_action not in {'allow', 'schedule', 'suppress'}:
            quiet_action = 'schedule'
        try:
            quiet_suppress_for_s = int(quiet_raw.get('suppress_for_s') or 900)
        except Exception:
            quiet_suppress_for_s = 900
        maintenance_windows: list[dict[str, Any]] = []
        for idx, item in enumerate(list(raw.get('maintenance_windows') or [])):
            if not isinstance(item, dict):
                continue
            window = cls._safe_json(item)
            window.setdefault('window_id', f'maintenance-{idx + 1}')
            window.setdefault('enabled', True)
            action = str(window.get('action') or 'suppress').strip().lower() or 'suppress'
            if action not in {'allow', 'schedule', 'suppress'}:
                action = 'suppress'
            window['action'] = action
            window['timezone'] = str(window.get('timezone') or default_timezone).strip() or default_timezone
            maintenance_windows.append(window)
        overrides: list[dict[str, Any]] = []
        for idx, item in enumerate(list(raw.get('override_policies') or raw.get('overrides') or [])):
            if not isinstance(item, dict):
                continue
            override = cls._safe_json(item)
            override.setdefault('policy_id', f'override-{idx + 1}')
            override.setdefault('enabled', True)
            overrides.append(override)
        storm_raw = dict(raw.get('alert_storm_policy') or raw.get('storm_policy') or {})
        storm_action = str(storm_raw.get('action') or 'suppress').strip().lower() or 'suppress'
        if storm_action not in {'allow', 'schedule', 'suppress'}:
            storm_action = 'suppress'
        try:
            active_alert_threshold = int(storm_raw.get('active_alert_threshold') or 0)
        except Exception:
            active_alert_threshold = 0
        try:
            suppress_for_s = int(storm_raw.get('suppress_for_s') or 600)
        except Exception:
            suppress_for_s = 600
        per_severity_thresholds: dict[str, int] = {}
        for key, value in dict(storm_raw.get('per_severity_thresholds') or {}).items():
            try:
                per_severity_thresholds[str(key).strip().lower()] = max(0, int(value or 0))
            except Exception:
                continue
        return {
            **raw,
            'enabled': bool(raw.get('enabled', True)),
            'default_timezone': default_timezone,
            'quiet_hours': {
                **quiet_raw,
                'enabled': bool(quiet_raw.get('enabled', bool(quiet_raw))),
                'timezone': str(quiet_raw.get('timezone') or default_timezone).strip() or default_timezone,
                'weekdays': list(quiet_raw.get('weekdays') or quiet_raw.get('days') or []),
                'start_time': str(quiet_raw.get('start_time') or '22:00').strip() or '22:00',
                'end_time': str(quiet_raw.get('end_time') or '06:00').strip() or '06:00',
                'action': quiet_action,
                'allow_severities': [str(item).strip().lower() for item in list(quiet_raw.get('allow_severities') or []) if str(item).strip()],
                'allow_alert_codes': [str(item).strip() for item in list(quiet_raw.get('allow_alert_codes') or []) if str(item).strip()],
                'suppress_for_s': max(60, quiet_suppress_for_s),
            },
            'maintenance_windows': maintenance_windows,
            'override_policies': overrides,
            'storm_policy': {
                **storm_raw,
                'enabled': bool(storm_raw.get('enabled', bool(storm_raw))),
                'action': storm_action,
                'active_alert_threshold': max(0, active_alert_threshold),
                'per_severity_thresholds': per_severity_thresholds,
                'suppress_severities': [str(item).strip().lower() for item in list(storm_raw.get('suppress_severities') or ['warn', 'info']) if str(item).strip()],
                'allow_alert_codes': [str(item).strip() for item in list(storm_raw.get('allow_alert_codes') or []) if str(item).strip()],
                'suppress_for_s': max(60, suppress_for_s),
            },
        }

    @classmethod
    def _heartbeat_policy(cls, runtime: dict[str, Any]) -> dict[str, Any]:
        metadata = cls._runtime_metadata(runtime)
        raw = dict(metadata.get('heartbeat_policy') or metadata.get('polling_policy') or {})
        dispatch_policy = cls._dispatch_policy(runtime)
        runtime_stale_after_s = raw.get('runtime_stale_after_s', metadata.get('runtime_stale_after_s'))
        active_run_stale_after_s = raw.get('active_run_stale_after_s', metadata.get('active_run_stale_after_s'))
        auto_reconcile_after_s = raw.get('auto_reconcile_after_s', metadata.get('auto_reconcile_after_s'))
        poll_interval_s = raw.get('poll_interval_s', metadata.get('poll_interval_s', dispatch_policy.get('poll_after_s') or 2.0))
        max_poll_retries = raw.get('max_poll_retries', metadata.get('max_poll_retries', dispatch_policy.get('max_retries') or 0))
        target_status = str(raw.get('stale_target_status') or metadata.get('stale_target_status') or 'timed_out').strip().lower() or 'timed_out'
        if target_status not in {'completed', 'failed', 'cancelled', 'timed_out'}:
            target_status = 'timed_out'
        try:
            runtime_stale_after_s = float(runtime_stale_after_s if runtime_stale_after_s is not None else 300.0)
        except Exception:
            runtime_stale_after_s = 300.0
        try:
            active_run_stale_after_s = float(active_run_stale_after_s if active_run_stale_after_s is not None else max(float(dispatch_policy.get('poll_after_s') or 2.0) * 3.0, 120.0))
        except Exception:
            active_run_stale_after_s = max(float(dispatch_policy.get('poll_after_s') or 2.0) * 3.0, 120.0)
        try:
            auto_reconcile_after_s = float(auto_reconcile_after_s if auto_reconcile_after_s is not None else max(active_run_stale_after_s * 2.0, active_run_stale_after_s))
        except Exception:
            auto_reconcile_after_s = max(active_run_stale_after_s * 2.0, active_run_stale_after_s)
        try:
            poll_interval_s = float(poll_interval_s if poll_interval_s is not None else (dispatch_policy.get('poll_after_s') or 2.0))
        except Exception:
            poll_interval_s = float(dispatch_policy.get('poll_after_s') or 2.0)
        try:
            max_poll_retries = int(max_poll_retries if max_poll_retries is not None else 0)
        except Exception:
            max_poll_retries = 0
        return {
            'runtime_stale_after_s': max(1.0, runtime_stale_after_s),
            'active_run_stale_after_s': max(0.0, active_run_stale_after_s),
            'auto_reconcile_after_s': max(0.0, auto_reconcile_after_s),
            'poll_interval_s': max(0.0, poll_interval_s),
            'max_poll_retries': max(0, max_poll_retries),
            'auto_poll_enabled': bool(raw.get('auto_poll_enabled', metadata.get('auto_poll_enabled', dispatch_policy.get('dispatch_mode') == 'async'))),
            'auto_reconcile_enabled': bool(raw.get('auto_reconcile_enabled', metadata.get('auto_reconcile_enabled', True))),
            'stale_target_status': target_status,
        }

    @classmethod
    def _slo_policy(cls, runtime: dict[str, Any]) -> dict[str, Any]:
        metadata = cls._runtime_metadata(runtime)
        raw = dict(metadata.get('slo_policy') or {})
        dispatch_policy = cls._dispatch_policy(runtime)
        heartbeat_policy = cls._heartbeat_policy(runtime)
        recovery_schedule = cls._recommended_recovery_schedule(runtime)

        def _float(name: str, default: float) -> float:
            try:
                return float(raw.get(name, default))
            except Exception:
                return float(default)

        def _int(name: str, default: int) -> int:
            try:
                return int(raw.get(name, default))
            except Exception:
                return int(default)

        runtime_stale_warn_after_s = _float('runtime_stale_warn_after_s', float(heartbeat_policy.get('runtime_stale_after_s') or 300.0))
        runtime_stale_critical_after_s = _float('runtime_stale_critical_after_s', max(runtime_stale_warn_after_s * 2.0, runtime_stale_warn_after_s))
        long_lease_warn_after_s = _float('long_lease_warn_after_s', max(float(recovery_schedule.get('interval_s') or 60) * 3.0, 60.0))
        long_lease_critical_after_s = _float('long_lease_critical_after_s', max(long_lease_warn_after_s * 2.0, long_lease_warn_after_s))
        stuck_idempotency_warn_after_s = _float('stuck_idempotency_warn_after_s', max(float(recovery_schedule.get('interval_s') or 60) * 2.0, 120.0))
        stuck_idempotency_critical_after_s = _float('stuck_idempotency_critical_after_s', max(stuck_idempotency_warn_after_s * 2.0, stuck_idempotency_warn_after_s))
        stale_active_warn_count = _int('stale_active_warn_count', 1)
        stale_active_critical_count = _int('stale_active_critical_count', max(2, stale_active_warn_count))
        stale_active_warn_ratio = _float('stale_active_warn_ratio', 0.25)
        stale_active_critical_ratio = _float('stale_active_critical_ratio', 0.5)
        runtime_run_warn_ratio = _float('runtime_run_warn_ratio', 0.8)
        runtime_run_critical_ratio = _float('runtime_run_critical_ratio', 1.0)
        workspace_run_warn_ratio = _float('workspace_run_warn_ratio', 0.8)
        workspace_run_critical_ratio = _float('workspace_run_critical_ratio', 1.0)
        workspace_slot_warn_ratio = _float('workspace_slot_warn_ratio', 0.8)
        workspace_slot_critical_ratio = _float('workspace_slot_critical_ratio', 1.0)
        idempotency_warn_count = _int('idempotency_warn_count', 1)
        idempotency_critical_count = _int('idempotency_critical_count', max(2, idempotency_warn_count))
        long_lease_warn_count = _int('long_lease_warn_count', 1)
        long_lease_critical_count = _int('long_lease_critical_count', max(2, long_lease_warn_count))
        degraded_severity = str(raw.get('health_degraded_severity') or 'warn').strip().lower() or 'warn'
        unhealthy_severity = str(raw.get('health_unhealthy_severity') or 'critical').strip().lower() or 'critical'
        if degraded_severity not in {'warn', 'critical'}:
            degraded_severity = 'warn'
        if unhealthy_severity not in {'warn', 'critical'}:
            unhealthy_severity = 'critical'
        return {
            'runtime_run_warn_ratio': max(0.0, runtime_run_warn_ratio),
            'runtime_run_critical_ratio': max(runtime_run_warn_ratio, runtime_run_critical_ratio),
            'workspace_run_warn_ratio': max(0.0, workspace_run_warn_ratio),
            'workspace_run_critical_ratio': max(workspace_run_warn_ratio, workspace_run_critical_ratio),
            'workspace_slot_warn_ratio': max(0.0, workspace_slot_warn_ratio),
            'workspace_slot_critical_ratio': max(workspace_slot_warn_ratio, workspace_slot_critical_ratio),
            'stale_active_warn_count': max(1, stale_active_warn_count),
            'stale_active_critical_count': max(max(1, stale_active_warn_count), stale_active_critical_count),
            'stale_active_warn_ratio': max(0.0, stale_active_warn_ratio),
            'stale_active_critical_ratio': max(stale_active_warn_ratio, stale_active_critical_ratio),
            'runtime_stale_warn_after_s': max(1.0, runtime_stale_warn_after_s),
            'runtime_stale_critical_after_s': max(max(1.0, runtime_stale_warn_after_s), runtime_stale_critical_after_s),
            'long_lease_warn_after_s': max(0.0, long_lease_warn_after_s),
            'long_lease_critical_after_s': max(max(0.0, long_lease_warn_after_s), long_lease_critical_after_s),
            'stuck_idempotency_warn_after_s': max(0.0, stuck_idempotency_warn_after_s),
            'stuck_idempotency_critical_after_s': max(max(0.0, stuck_idempotency_warn_after_s), stuck_idempotency_critical_after_s),
            'idempotency_warn_count': max(1, idempotency_warn_count),
            'idempotency_critical_count': max(max(1, idempotency_warn_count), idempotency_critical_count),
            'long_lease_warn_count': max(1, long_lease_warn_count),
            'long_lease_critical_count': max(max(1, long_lease_warn_count), long_lease_critical_count),
            'health_degraded_severity': degraded_severity,
            'health_unhealthy_severity': unhealthy_severity,
            'dispatch_mode': str(dispatch_policy.get('dispatch_mode') or 'sync'),
        }

    def apply_policy_pack(
        self,
        gw,
        *,
        runtime_id: str,
        actor: str = 'system',
        pack_name: str | None = None,
        runtime_class: str | None = None,
        overrides: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        detail = self.get_runtime(gw, runtime_id=runtime_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if not detail.get('ok'):
            return detail
        runtime = detail['runtime']
        scope = self._normalize_scope(
            tenant_id=tenant_id or runtime.get('tenant_id'),
            workspace_id=workspace_id or runtime.get('workspace_id'),
            environment=environment or runtime.get('environment'),
        )
        preview = self.preview_policy_pack(
            pack_name=pack_name,
            runtime_class=runtime_class or pack_name or ((runtime.get('metadata') or {}).get('runtime_class')),
            transport=str(runtime.get('transport') or 'http'),
            metadata=self._deep_merge(self._runtime_metadata(runtime), dict(overrides or {})),
        )
        merged_metadata = dict(preview.get('metadata') or {})
        updated = gw.audit.upsert_openclaw_runtime(
            runtime_id=str(runtime.get('runtime_id') or runtime_id),
            name=str(runtime.get('name') or ''),
            base_url=str(runtime.get('base_url') or ''),
            transport=str(runtime.get('transport') or 'http'),
            auth_secret_ref=str(runtime.get('auth_secret_ref') or ''),
            status=str(runtime.get('status') or 'registered'),
            capabilities=list(runtime.get('capabilities') or []),
            allowed_agents=list(runtime.get('allowed_agents') or []),
            metadata=merged_metadata,
            created_by=str(actor or 'system'),
            **scope,
        )
        gw.audit.log_event('system', 'broker', str(actor or 'system'), 'system', {'action': 'openclaw_runtime_policy_pack_applied', 'runtime_id': runtime_id, 'policy_pack': merged_metadata.get('policy_pack'), 'runtime_class': merged_metadata.get('runtime_class')}, **scope)
        return {'ok': True, 'runtime': updated, 'runtime_summary': self._build_runtime_summary(updated), 'policy_pack': preview.get('pack')}

    def run_conformance_check(
        self,
        gw,
        *,
        runtime_id: str,
        actor: str = 'system',
        user_role: str = 'operator',
        user_key: str = '',
        session_id: str = 'system',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        detail = self.get_runtime(gw, runtime_id=runtime_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if not detail.get('ok'):
            return detail
        runtime = detail['runtime']
        scope = self._normalize_scope(
            tenant_id=tenant_id or runtime.get('tenant_id'),
            workspace_id=workspace_id or runtime.get('workspace_id'),
            environment=environment or runtime.get('environment'),
        )
        metadata = self._runtime_metadata(runtime)
        summary = self._build_runtime_summary(runtime)
        bridge = summary.get('event_bridge') or {}
        findings: list[dict[str, Any]] = []

        def add(check_id: str, state: str, reason: str, details: dict[str, Any] | None = None) -> None:
            findings.append({'check_id': check_id, 'state': state, 'reason': reason, 'details': self._safe_json(details or {})})

        compat_version = str(metadata.get('openclaw_compat_version') or '').strip().lower()
        add('compat_version', 'pass' if compat_version == 'v2' else 'fail', 'runtime declares OpenClaw compatibility v2' if compat_version == 'v2' else 'runtime does not declare openclaw_compat_version=v2', {'value': compat_version})
        policy_pack = str(metadata.get('policy_pack') or '').strip()
        runtime_class = str(metadata.get('runtime_class') or '').strip()
        add('policy_pack', 'pass' if policy_pack and runtime_class else 'warn', 'runtime declares policy pack and runtime class' if policy_pack and runtime_class else 'runtime lacks explicit policy_pack/runtime_class metadata', {'policy_pack': policy_pack, 'runtime_class': runtime_class})
        scoped = all(str(scope.get(key) or '').strip() for key in ('tenant_id', 'workspace_id', 'environment'))
        add('scoped_runtime', 'pass' if scoped else 'fail', 'runtime is fully scoped to tenant/workspace/environment' if scoped else 'runtime scope is incomplete', scope)
        allowed_actions = summary.get('allowed_actions') or []
        add('allowed_actions_declared', 'pass' if allowed_actions else 'fail', 'runtime declares allowed actions' if allowed_actions else 'runtime has no explicit allowed actions', {'allowed_actions': allowed_actions})
        allowed_agents = summary.get('allowed_agents') or []
        add('allowed_agents_declared', 'pass' if allowed_agents else 'warn', 'runtime restricts dispatch to explicit agents' if allowed_agents else 'runtime does not restrict agents explicitly', {'allowed_agents': allowed_agents})
        policy = summary.get('dispatch_policy') or {}
        sane_policy = float(policy.get('timeout_s') or 0.0) >= 1.0 and int(policy.get('max_retries') or 0) >= 0
        add('dispatch_policy', 'pass' if sane_policy else 'fail', 'dispatch policy is structurally valid' if sane_policy else 'dispatch policy is invalid', policy)
        session_bridge = summary.get('session_bridge') or {}
        if session_bridge.get('enabled'):
            add('session_bridge', 'pass' if session_bridge.get('workspace_connection') else 'fail', 'session bridge is configured' if session_bridge.get('workspace_connection') else 'session bridge enabled without workspace connection', session_bridge)
        else:
            add('session_bridge', 'warn', 'session bridge disabled', session_bridge)
        if bridge.get('enabled'):
            token_ok = bool(bridge.get('token_configured'))
            source_ok = bool(bridge.get('accepted_sources'))
            state = 'pass' if token_ok and source_ok else 'fail'
            reason = 'event bridge is secured and source-scoped' if state == 'pass' else 'event bridge requires token and accepted source configuration'
            add('event_bridge', state, reason, bridge)
        else:
            add('event_bridge', 'warn', 'event bridge disabled', bridge)
        secret_ref = str(runtime.get('auth_secret_ref') or '').strip()
        if secret_ref:
            broker = getattr(gw, 'secret_broker', None)
            if broker is None or not hasattr(broker, 'explain_access'):
                add('auth_secret', 'fail', 'secret broker not configured for runtime auth secret', {'ref': secret_ref})
            else:
                secret_state = broker.explain_access(
                    secret_ref,
                    tool_name=self.TOOL_NAME,
                    user_role=str(user_role or 'operator'),
                    tenant_id=scope['tenant_id'],
                    workspace_id=scope['workspace_id'],
                    environment=scope['environment'],
                    domain=self._runtime_domain(runtime),
                )
                add('auth_secret', 'pass' if secret_state.get('allowed') else 'fail', str(secret_state.get('reason') or 'secret access evaluated'), {'ref': secret_ref, 'allowed': bool(secret_state.get('allowed')), 'configured': bool(secret_state.get('configured'))})
        else:
            add('auth_secret', 'warn', 'runtime has no auth secret configured', {})
        health = detail.get('health') or {}
        health_status = str(health.get('status') or 'unknown').strip().lower()
        health_state = 'pass' if health_status == 'healthy' else ('warn' if health_status in {'degraded', 'unknown'} else 'fail')
        add('health_status', health_state, f"runtime health status is {health_status or 'unknown'}", health)

        passed = sum(1 for item in findings if item['state'] == 'pass')
        failed = sum(1 for item in findings if item['state'] == 'fail')
        warnings = sum(1 for item in findings if item['state'] == 'warn')
        total = len(findings)
        score_percent = round((passed / total) * 100.0, 2) if total else 0.0
        ready = failed == 0
        gw.audit.log_event(
            'system',
            'broker',
            str(actor or 'system'),
            str(session_id or 'system'),
            {
                'action': 'openclaw_runtime_conformance_checked',
                'runtime_id': runtime_id,
                'score_percent': score_percent,
                'passed': passed,
                'failed': failed,
                'warnings': warnings,
                'ready': ready,
            },
            **scope,
        )
        return {
            'ok': True,
            'runtime': runtime,
            'runtime_summary': summary,
            'conformance': {
                'ready': ready,
                'score_percent': score_percent,
                'passed': passed,
                'failed': failed,
                'warnings': warnings,
                'checks': findings,
            },
        }

