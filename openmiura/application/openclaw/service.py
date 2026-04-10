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


class OpenClawAdapterService:
    """Governed adapter for delegating execution to external OpenClaw runtimes."""

    TOOL_NAME = 'openclaw_adapter'
    TERMINAL_CANONICAL_STATUSES = {'completed', 'failed', 'cancelled', 'timed_out'}
    POLICY_PACKS: dict[str, dict[str, Any]] = {
        'generic_async_worker': {
            'description': 'Balanced defaults for async external runtimes with event bridge and automatic stale-run recovery.',
            'runtime_classes': ['generic_async_worker', 'generic', 'worker'],
            'metadata': {
                'dispatch_policy': {
                    'dispatch_mode': 'async',
                    'timeout_s': 20,
                    'max_retries': 1,
                    'retry_backoff_ms': 250,
                    'poll_after_s': 2.0,
                    'operator_retry_limit': 2,
                    'max_active_runs': 25,
                    'max_active_runs_per_workspace': 100,
                    'allow_cancel': True,
                    'allow_manual_close': True,
                    'allow_reconcile': True,
                    'allow_cancel_local_fallback': True,
                },
                'heartbeat_policy': {
                    'runtime_stale_after_s': 300,
                    'active_run_stale_after_s': 120,
                    'auto_reconcile_after_s': 300,
                    'poll_interval_s': 10,
                    'max_poll_retries': 2,
                    'auto_poll_enabled': True,
                    'auto_reconcile_enabled': True,
                    'stale_target_status': 'timed_out',
                },
                'session_bridge': {
                    'enabled': True,
                    'event_bridge_enabled': True,
                },
                'event_bridge': {
                    'accepted_sources': ['openclaw'],
                    'accepted_event_types': ['run.accepted', 'run.queued', 'run.progress', 'run.completed', 'run.failed', 'run.cancelled', 'run.timed_out'],
                },
            },
            'scheduler': {'schedule_kind': 'interval', 'interval_s': 60, 'limit': 50, 'lease_ttl_s': 120, 'idempotency_ttl_s': 1800, 'workspace_backpressure_limit': 1, 'runtime_exclusive': True},
        },
        'browser_automation': {
            'description': 'Longer polling windows for browser-led automation with higher latency and explicit timeout recovery.',
            'runtime_classes': ['browser_automation', 'browser', 'web'],
            'metadata': {
                'dispatch_policy': {
                    'dispatch_mode': 'async',
                    'timeout_s': 30,
                    'max_retries': 1,
                    'retry_backoff_ms': 500,
                    'poll_after_s': 3.0,
                    'operator_retry_limit': 1,
                    'max_active_runs': 6,
                    'max_active_runs_per_workspace': 25,
                },
                'heartbeat_policy': {
                    'runtime_stale_after_s': 420,
                    'active_run_stale_after_s': 180,
                    'auto_reconcile_after_s': 600,
                    'poll_interval_s': 15,
                    'max_poll_retries': 3,
                    'auto_poll_enabled': True,
                    'auto_reconcile_enabled': True,
                    'stale_target_status': 'timed_out',
                },
                'session_bridge': {'enabled': True, 'event_bridge_enabled': True},
                'event_bridge': {'accepted_sources': ['openclaw'], 'accepted_event_types': ['run.accepted', 'run.queued', 'run.progress', 'run.completed', 'run.failed', 'run.cancelled', 'run.timeout']},
            },
            'scheduler': {'schedule_kind': 'interval', 'interval_s': 120, 'limit': 30, 'lease_ttl_s': 180, 'idempotency_ttl_s': 2400, 'workspace_backpressure_limit': 1, 'runtime_exclusive': True},
        },
        'terminal_ops': {
            'description': 'More aggressive recovery defaults for terminal-oriented operational runtimes.',
            'runtime_classes': ['terminal_ops', 'terminal', 'shell'],
            'metadata': {
                'dispatch_policy': {
                    'dispatch_mode': 'async',
                    'timeout_s': 15,
                    'max_retries': 1,
                    'retry_backoff_ms': 250,
                    'poll_after_s': 1.0,
                    'operator_retry_limit': 1,
                    'max_active_runs': 10,
                    'max_active_runs_per_workspace': 20,
                },
                'heartbeat_policy': {
                    'runtime_stale_after_s': 180,
                    'active_run_stale_after_s': 60,
                    'auto_reconcile_after_s': 180,
                    'poll_interval_s': 5,
                    'max_poll_retries': 2,
                    'auto_poll_enabled': True,
                    'auto_reconcile_enabled': True,
                    'stale_target_status': 'failed',
                },
                'session_bridge': {'enabled': True, 'event_bridge_enabled': True},
                'event_bridge': {'accepted_sources': ['openclaw'], 'accepted_event_types': ['run.accepted', 'run.queued', 'run.progress', 'run.completed', 'run.failed', 'run.cancelled']},
            },
            'scheduler': {'schedule_kind': 'interval', 'interval_s': 45, 'limit': 50, 'lease_ttl_s': 120, 'idempotency_ttl_s': 1800, 'workspace_backpressure_limit': 1, 'runtime_exclusive': True},
        },
        'document_pipeline': {
            'description': 'Conservative polling and reconcile windows for document-heavy asynchronous workflows.',
            'runtime_classes': ['document_pipeline', 'document', 'pipeline'],
            'metadata': {
                'dispatch_policy': {
                    'dispatch_mode': 'async',
                    'timeout_s': 45,
                    'max_retries': 2,
                    'retry_backoff_ms': 500,
                    'poll_after_s': 5.0,
                    'operator_retry_limit': 2,
                    'max_active_runs': 8,
                    'max_active_runs_per_workspace': 25,
                },
                'heartbeat_policy': {
                    'runtime_stale_after_s': 600,
                    'active_run_stale_after_s': 300,
                    'auto_reconcile_after_s': 900,
                    'poll_interval_s': 30,
                    'max_poll_retries': 3,
                    'auto_poll_enabled': True,
                    'auto_reconcile_enabled': True,
                    'stale_target_status': 'timed_out',
                },
                'session_bridge': {'enabled': True, 'event_bridge_enabled': True},
                'event_bridge': {'accepted_sources': ['openclaw'], 'accepted_event_types': ['run.accepted', 'run.queued', 'run.progress', 'run.completed', 'run.failed']},
            },
            'scheduler': {'schedule_kind': 'interval', 'interval_s': 180, 'limit': 20, 'lease_ttl_s': 240, 'idempotency_ttl_s': 3600, 'workspace_backpressure_limit': 1, 'runtime_exclusive': True},
        },
        'incident_triage': {
            'description': 'Fast heartbeat and reconcile loop for incident-response and triage runtimes.',
            'runtime_classes': ['incident_triage', 'incident', 'triage'],
            'metadata': {
                'dispatch_policy': {
                    'dispatch_mode': 'async',
                    'timeout_s': 15,
                    'max_retries': 1,
                    'retry_backoff_ms': 200,
                    'poll_after_s': 1.0,
                    'operator_retry_limit': 2,
                    'max_active_runs': 20,
                    'max_active_runs_per_workspace': 50,
                },
                'heartbeat_policy': {
                    'runtime_stale_after_s': 120,
                    'active_run_stale_after_s': 30,
                    'auto_reconcile_after_s': 120,
                    'poll_interval_s': 5,
                    'max_poll_retries': 2,
                    'auto_poll_enabled': True,
                    'auto_reconcile_enabled': True,
                    'stale_target_status': 'timed_out',
                },
                'session_bridge': {'enabled': True, 'event_bridge_enabled': True},
                'event_bridge': {'accepted_sources': ['openclaw'], 'accepted_event_types': ['run.accepted', 'run.queued', 'run.progress', 'run.completed', 'run.failed', 'run.cancelled']},
            },
            'scheduler': {'schedule_kind': 'interval', 'interval_s': 30, 'limit': 100, 'lease_ttl_s': 120, 'idempotency_ttl_s': 1200, 'workspace_backpressure_limit': 1, 'runtime_exclusive': True},
        },
        'simulated_lab': {
            'description': 'Fast feedback defaults for simulated or local lab runtimes.',
            'runtime_classes': ['simulated_lab', 'simulated', 'lab'],
            'metadata': {
                'dispatch_policy': {
                    'dispatch_mode': 'async',
                    'timeout_s': 5,
                    'max_retries': 0,
                    'retry_backoff_ms': 50,
                    'poll_after_s': 0.25,
                    'operator_retry_limit': 3,
                    'max_active_runs': 50,
                    'max_active_runs_per_workspace': 200,
                },
                'heartbeat_policy': {
                    'runtime_stale_after_s': 60,
                    'active_run_stale_after_s': 5,
                    'auto_reconcile_after_s': 15,
                    'poll_interval_s': 1,
                    'max_poll_retries': 1,
                    'auto_poll_enabled': True,
                    'auto_reconcile_enabled': True,
                    'stale_target_status': 'timed_out',
                },
                'session_bridge': {'enabled': True, 'event_bridge_enabled': True},
                'event_bridge': {'accepted_sources': ['openclaw'], 'accepted_event_types': ['run.accepted', 'run.queued', 'run.progress', 'run.completed', 'run.failed', 'run.cancelled', 'run.timed_out']},
            },
            'scheduler': {'schedule_kind': 'interval', 'interval_s': 10, 'limit': 200, 'lease_ttl_s': 30, 'idempotency_ttl_s': 300, 'workspace_backpressure_limit': 2, 'runtime_exclusive': True},
        },
    }
    RUNTIME_CLASS_ALIASES = {
        'generic': 'generic_async_worker',
        'worker': 'generic_async_worker',
        'browser': 'browser_automation',
        'web': 'browser_automation',
        'terminal': 'terminal_ops',
        'shell': 'terminal_ops',
        'document': 'document_pipeline',
        'pipeline': 'document_pipeline',
        'incident': 'incident_triage',
        'triage': 'incident_triage',
        'simulated': 'simulated_lab',
        'lab': 'simulated_lab',
    }

    @staticmethod
    def _normalize_scope(*, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, str | None]:
        return {
            'tenant_id': str(tenant_id).strip() if tenant_id is not None else None,
            'workspace_id': str(workspace_id).strip() if workspace_id is not None else None,
            'environment': str(environment).strip() if environment is not None else None,
        }

    @staticmethod
    def _validate_base_url(base_url: str, *, transport: str) -> str:
        raw = str(base_url or '').strip()
        mode = str(transport or 'http').strip().lower() or 'http'
        if mode == 'simulated':
            return raw or 'simulated://openclaw'
        if not raw:
            raise ValueError('base_url is required')
        parsed = urllib.parse.urlparse(raw)
        if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
            raise ValueError('base_url must be a valid http/https URL')
        return raw.rstrip('/')

    @classmethod
    def _normalize_runtime_class(cls, runtime_class: str | None, *, transport: str = 'http') -> str:
        raw = str(runtime_class or '').strip().lower()
        if not raw:
            raw = 'simulated_lab' if str(transport or '').strip().lower() == 'simulated' else 'generic_async_worker'
        return cls.RUNTIME_CLASS_ALIASES.get(raw, raw)

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

    @staticmethod
    def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        merged = copy.deepcopy(base)
        for key, value in dict(override or {}).items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = OpenClawAdapterService._deep_merge(dict(merged.get(key) or {}), value)
            else:
                merged[key] = copy.deepcopy(value)
        return merged

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

    @classmethod
    def _recommended_recovery_schedule(cls, runtime: dict[str, Any]) -> dict[str, Any]:
        metadata = cls._runtime_metadata(runtime)
        pack = cls._policy_pack_spec(metadata.get('policy_pack'), runtime_class=metadata.get('runtime_class') or metadata.get('kind'), transport=str(runtime.get('transport') or 'http'))
        scheduler = dict(pack.get('scheduler') or {})
        heartbeat_policy = cls._heartbeat_policy(runtime)
        interval_s = scheduler.get('interval_s')
        if interval_s is None:
            try:
                interval_s = max(10, min(int(float(heartbeat_policy.get('active_run_stale_after_s') or 120.0) / 2.0) or 60, 3600))
            except Exception:
                interval_s = 60
        try:
            interval_s = int(interval_s)
        except Exception:
            interval_s = 60
        return {
            'schedule_kind': str(scheduler.get('schedule_kind') or 'interval'),
            'interval_s': max(1, interval_s),
            'limit': int(scheduler.get('limit') or 50),
            'pack_name': str(pack.get('id') or 'generic_async_worker'),
            'lease_ttl_s': max(5, int(scheduler.get('lease_ttl_s') or max(interval_s * 2, 30))),
            'idempotency_ttl_s': max(30, int(scheduler.get('idempotency_ttl_s') or max(interval_s * 10, 300))),
            'workspace_backpressure_limit': max(1, int(scheduler.get('workspace_backpressure_limit') or 1)),
            'runtime_exclusive': bool(scheduler.get('runtime_exclusive', True)),
        }

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

    @staticmethod
    def _runtime_metadata(runtime: dict[str, Any]) -> dict[str, Any]:
        metadata = runtime.get('metadata') or {}
        return dict(metadata) if isinstance(metadata, dict) else {}

    @staticmethod
    def _runtime_domain(runtime: dict[str, Any]) -> str | None:
        try:
            parsed = urllib.parse.urlparse(str(runtime.get('base_url') or ''))
        except Exception:
            return None
        return parsed.netloc or None

    @classmethod
    def _dispatch_url(cls, runtime: dict[str, Any]) -> str:
        base = str(runtime.get('base_url') or '').rstrip('/')
        metadata = cls._runtime_metadata(runtime)
        dispatch_path = str(metadata.get('dispatch_path') or '/runtime/dispatch').strip() or '/runtime/dispatch'
        if not dispatch_path.startswith('/'):
            dispatch_path = '/' + dispatch_path
        if str(runtime.get('transport') or '').strip().lower() == 'simulated':
            return base or 'simulated://openclaw/dispatch'
        return f"{base}{dispatch_path}"

    @classmethod
    def _health_url(cls, runtime: dict[str, Any]) -> str:
        base = str(runtime.get('base_url') or '').rstrip('/')
        metadata = cls._runtime_metadata(runtime)
        health_path = str(metadata.get('health_path') or '/runtime/health').strip() or '/runtime/health'
        if not health_path.startswith('/'):
            health_path = '/' + health_path
        if str(runtime.get('transport') or '').strip().lower() == 'simulated':
            return (base or 'simulated://openclaw').rstrip('/') + '/health'
        return f"{base}{health_path}"

    @classmethod
    def _operation_url(cls, runtime: dict[str, Any], *, operation: str, dispatch_id: str) -> str:
        base = str(runtime.get('base_url') or '').rstrip('/')
        metadata = cls._runtime_metadata(runtime)
        defaults = {
            'cancel': f'/runtime/dispatch/{dispatch_id}/cancel',
            'reconcile': f'/runtime/dispatch/{dispatch_id}/reconcile',
            'status': f'/runtime/dispatch/{dispatch_id}',
        }
        configured = str(metadata.get(f'{operation}_path') or defaults.get(operation) or '').strip()
        path = configured.replace('{dispatch_id}', str(dispatch_id or '').strip())
        if path and not path.startswith('/') and not path.startswith('simulated://'):
            path = '/' + path
        if str(runtime.get('transport') or '').strip().lower() == 'simulated':
            suffix = path if path.startswith('/') else f'/{operation}'
            return (base or 'simulated://openclaw').rstrip('/') + suffix
        if path.startswith('http://') or path.startswith('https://'):
            return path
        return f"{base}{path}"

    @staticmethod
    def _safe_json(value: Any) -> Any:
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        if isinstance(value, dict):
            return {str(k): OpenClawAdapterService._safe_json(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [OpenClawAdapterService._safe_json(v) for v in value]
        return str(value)

    @classmethod
    def _append_operator_action(cls, response_payload: dict[str, Any] | None, *, action: str, actor: str, reason: str = '', details: dict[str, Any] | None = None) -> dict[str, Any]:
        enriched = dict(response_payload or {})
        history = list(enriched.get('operator_actions') or [])
        history.append({
            'action': str(action or '').strip().lower(),
            'actor': str(actor or 'system'),
            'reason': str(reason or '').strip(),
            'ts': time.time(),
            'details': cls._safe_json(details or {}),
        })
        enriched['operator_actions'] = history[-20:]
        return enriched

    @classmethod
    def _retry_count(cls, dispatch: dict[str, Any] | None) -> int:
        dispatch = dict(dispatch or {})
        response_payload = dict(dispatch.get('response') or {})
        lifecycle = dict(response_payload.get('lifecycle') or {})
        correlation = dict((dispatch.get('request') or {}).get('correlation') or {})
        raw = lifecycle.get('retry_count', correlation.get('retry_count', 0))
        try:
            return int(raw or 0)
        except Exception:
            return 0

    @classmethod
    def _root_dispatch_id(cls, dispatch: dict[str, Any] | None) -> str:
        dispatch = dict(dispatch or {})
        correlation = dict((dispatch.get('request') or {}).get('correlation') or {})
        return str(correlation.get('root_dispatch_id') or dispatch.get('dispatch_id') or '').strip()

    @classmethod
    def _allowed_actions(cls, runtime: dict[str, Any]) -> set[str]:
        metadata = cls._runtime_metadata(runtime)
        explicit = metadata.get('allowed_actions')
        if explicit is None:
            explicit = runtime.get('capabilities') or []
        return {str(item).strip().lower() for item in list(explicit or []) if str(item).strip()}

    @classmethod
    def _dispatch_policy(cls, runtime: dict[str, Any]) -> dict[str, Any]:
        metadata = cls._runtime_metadata(runtime)
        policy = dict(metadata.get('dispatch_policy') or {})
        timeout_s = float(policy.get('timeout_s') or metadata.get('timeout_s') or 15.0)
        max_retries = int(policy.get('max_retries') or metadata.get('max_retries') or 0)
        retry_backoff_ms = int(policy.get('retry_backoff_ms') or metadata.get('retry_backoff_ms') or 250)
        dispatch_mode = str(policy.get('dispatch_mode') or metadata.get('dispatch_mode') or 'sync').strip().lower() or 'sync'
        if dispatch_mode not in {'sync', 'async'}:
            dispatch_mode = 'sync'
        poll_after_s = float(policy.get('poll_after_s') or metadata.get('poll_after_s') or 2.0)
        quota_per_hour = policy.get('quota_per_hour', metadata.get('quota_per_hour'))
        try:
            quota_per_hour = int(quota_per_hour) if quota_per_hour is not None else None
        except Exception:
            quota_per_hour = None
        operator_retry_limit = policy.get('operator_retry_limit', metadata.get('operator_retry_limit'))
        try:
            operator_retry_limit = int(operator_retry_limit) if operator_retry_limit is not None else 1
        except Exception:
            operator_retry_limit = 1
        max_active_runs = policy.get('max_active_runs', metadata.get('max_active_runs'))
        try:
            max_active_runs = int(max_active_runs) if max_active_runs is not None else None
        except Exception:
            max_active_runs = None
        max_active_runs_per_workspace = policy.get('max_active_runs_per_workspace', metadata.get('max_active_runs_per_workspace'))
        try:
            max_active_runs_per_workspace = int(max_active_runs_per_workspace) if max_active_runs_per_workspace is not None else None
        except Exception:
            max_active_runs_per_workspace = None
        return {
            'timeout_s': max(1.0, timeout_s),
            'max_retries': max(0, max_retries),
            'retry_backoff_ms': max(0, retry_backoff_ms),
            'dispatch_mode': dispatch_mode,
            'poll_after_s': max(0.0, poll_after_s),
            'quota_per_hour': quota_per_hour if quota_per_hour and quota_per_hour > 0 else None,
            'operator_retry_limit': max(0, operator_retry_limit),
            'max_active_runs': max_active_runs if max_active_runs and max_active_runs > 0 else None,
            'max_active_runs_per_workspace': max_active_runs_per_workspace if max_active_runs_per_workspace and max_active_runs_per_workspace > 0 else None,
            'allow_cancel': bool(policy.get('allow_cancel', metadata.get('allow_cancel', True))),
            'allow_manual_close': bool(policy.get('allow_manual_close', metadata.get('allow_manual_close', True))),
            'allow_reconcile': bool(policy.get('allow_reconcile', metadata.get('allow_reconcile', True))),
            'allow_cancel_local_fallback': bool(policy.get('allow_cancel_local_fallback', metadata.get('allow_cancel_local_fallback', True))),
        }


    @classmethod
    def _active_dispatch_count(cls, gw, *, runtime_id: str | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None, limit: int = 500) -> int:
        items = gw.audit.list_openclaw_dispatches(runtime_id=runtime_id, limit=limit, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        count = 0
        for item in items:
            canonical = cls._canonical_dispatch_status(str(item.get('status') or ''), dict(item.get('response') or {}))
            if not cls._is_terminal_canonical_status(canonical):
                count += 1
        return count

    @classmethod
    def _session_bridge(cls, runtime: dict[str, Any]) -> dict[str, Any]:
        metadata = cls._runtime_metadata(runtime)
        bridge = dict(metadata.get('session_bridge') or {})
        workspace_connection = bridge.get('workspace_connection') or metadata.get('workspace_connection') or runtime.get('workspace_id')
        return {
            'enabled': bool(bridge.get('enabled', True)),
            'workspace_connection': str(workspace_connection or '').strip(),
            'external_workspace_id': str(bridge.get('external_workspace_id') or metadata.get('external_workspace_id') or '').strip(),
            'external_environment': str(bridge.get('external_environment') or metadata.get('external_environment') or '').strip(),
            'event_bridge_enabled': bool(bridge.get('event_bridge_enabled', metadata.get('event_bridge_enabled', False))),
        }

    @classmethod
    def _event_bridge(cls, runtime: dict[str, Any]) -> dict[str, Any]:
        metadata = cls._runtime_metadata(runtime)
        raw = dict(metadata.get('event_bridge') or {})
        session_bridge = cls._session_bridge(runtime)
        accepted_sources = [str(item).strip() for item in list(raw.get('accepted_sources') or metadata.get('accepted_event_sources') or ['openclaw']) if str(item).strip()]
        accepted_event_types = [str(item).strip().lower() for item in list(raw.get('accepted_event_types') or metadata.get('accepted_event_types') or []) if str(item).strip()]
        return {
            'enabled': bool(session_bridge.get('event_bridge_enabled')),
            'token_configured': bool(str(raw.get('token') or metadata.get('event_bridge_token') or '').strip()),
            'accepted_sources': accepted_sources,
            'accepted_event_types': accepted_event_types,
            'source_label': str(raw.get('source_label') or metadata.get('event_bridge_source_label') or 'openclaw').strip() or 'openclaw',
        }

    @classmethod
    def _event_bridge_token(cls, runtime: dict[str, Any]) -> str:
        metadata = cls._runtime_metadata(runtime)
        raw = dict(metadata.get('event_bridge') or {})
        return str(raw.get('token') or metadata.get('event_bridge_token') or '').strip()

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
    def _alert_notification_targets(cls, runtime: dict[str, Any]) -> list[dict[str, Any]]:
        metadata = cls._runtime_metadata(runtime)
        items = list(metadata.get('alert_notification_targets') or metadata.get('notification_targets') or [])
        out: list[dict[str, Any]] = []
        for idx, raw_item in enumerate(items):
            if not isinstance(raw_item, dict):
                continue
            target_type = str(raw_item.get('type') or raw_item.get('target_type') or '').strip().lower()
            if target_type not in {'slack', 'webhook', 'app', 'queue', 'email'}:
                continue
            target_id = str(raw_item.get('target_id') or raw_item.get('id') or f'{target_type}-{idx + 1}').strip()
            item = {
                'target_id': target_id,
                'type': target_type,
                'enabled': bool(raw_item.get('enabled', True)),
                'channel': str(raw_item.get('channel') or '').strip(),
                'thread_ts': str(raw_item.get('thread_ts') or '').strip(),
                'url': str(raw_item.get('url') or raw_item.get('webhook_url') or '').strip(),
                'headers': cls._safe_json(raw_item.get('headers') or {}),
                'installation_id': str(raw_item.get('installation_id') or '').strip(),
                'target_path': str(raw_item.get('target_path') or '').strip(),
                'queue_name': str(raw_item.get('queue_name') or raw_item.get('queue') or '').strip(),
                'email_to': str(raw_item.get('email_to') or raw_item.get('to') or '').strip(),
                'subject_prefix': str(raw_item.get('subject_prefix') or '').strip(),
                'min_escalation_level': int(raw_item.get('min_escalation_level') or 1),
                'severities': [str(item).strip().lower() for item in list(raw_item.get('severities') or []) if str(item).strip()],
                'alert_codes': [str(item).strip() for item in list(raw_item.get('alert_codes') or []) if str(item).strip()],
                'workflow_actions': [str(item).strip().lower() for item in list(raw_item.get('workflow_actions') or ['escalate']) if str(item).strip()],
                'auth_secret_ref': str(raw_item.get('auth_secret_ref') or '').strip(),
                'metadata': cls._safe_json(raw_item.get('metadata') or {}),
            }
            out.append(item)
        return out


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

    @staticmethod
    def _dispatch_signal_ts(dispatch: dict[str, Any] | None) -> float:
        dispatch = dict(dispatch or {})
        response_payload = dict(dispatch.get('response') or {})
        lifecycle = dict(response_payload.get('lifecycle') or {})
        candidates = [
            lifecycle.get('last_observed_at'),
            lifecycle.get('last_polled_at'),
            lifecycle.get('cancelled_at'),
            lifecycle.get('reconciled_at'),
            dispatch.get('created_at'),
        ]
        for value in candidates:
            try:
                ts = float(value or 0.0)
            except Exception:
                ts = 0.0
            if ts > 0.0:
                return ts
        return 0.0

    def _refresh_runtime_heartbeat(self, gw, *, runtime_id: str, scope: dict[str, Any], health_status: str = 'healthy', observed_at: float | None = None) -> dict[str, Any] | None:
        try:
            return gw.audit.update_openclaw_runtime_health(
                runtime_id,
                health_status=str(health_status or 'healthy'),
                health_at=float(observed_at if observed_at is not None else time.time()),
                tenant_id=scope.get('tenant_id'),
                workspace_id=scope.get('workspace_id'),
                environment=scope.get('environment'),
            )
        except Exception:
            return None

    @staticmethod
    def _map_event_to_dispatch_status(*, event_type: str, event_status: str = '') -> str:
        status = str(event_status or '').strip().lower()
        kind = str(event_type or '').strip().lower()
        if status in {'failed', 'error', 'denied'} or kind.endswith('.failed') or kind.endswith('.error'):
            return 'error'
        if status in {'completed', 'succeeded', 'success', 'ok'} or kind.endswith('.completed') or kind.endswith('.succeeded'):
            return 'completed'
        if status in {'accepted'} or kind.endswith('.accepted'):
            return 'accepted'
        if status in {'queued'} or kind.endswith('.queued'):
            return 'queued'
        if status in {'cancelled'} or kind.endswith('.cancelled'):
            return 'cancelled'
        if status in {'timed_out', 'timeout'} or kind.endswith('.timed_out') or kind.endswith('.timeout'):
            return 'timed_out'
        if status in {'running', 'progress', 'started'} or kind.endswith('.started') or kind.endswith('.progress'):
            return 'running'
        return ''

    @classmethod
    def _canonical_dispatch_status(cls, status: str, response_payload: dict[str, Any] | None = None) -> str:
        raw = str(status or '').strip().lower()
        if raw in {'requested', 'accepted', 'queued', 'running', 'completed', 'cancelled', 'timed_out'}:
            return raw
        if raw in {'ok', 'success', 'succeeded'}:
            return 'completed'
        if raw in {'error', 'failed', 'failure'}:
            return 'failed'
        if raw == 'pending':
            response_payload = dict(response_payload or {})
            lifecycle = dict(response_payload.get('lifecycle') or {})
            hinted = str(lifecycle.get('canonical_status') or response_payload.get('canonical_status') or '').strip().lower()
            if hinted in {'requested', 'accepted', 'queued', 'running'}:
                return hinted
            return 'requested'
        return 'unknown'

    @classmethod
    def _is_terminal_canonical_status(cls, canonical_status: str) -> bool:
        return str(canonical_status or '').strip().lower() in cls.TERMINAL_CANONICAL_STATUSES

    @classmethod
    def _is_valid_dispatch_transition(cls, current_status: str, next_status: str) -> bool:
        current = str(current_status or '').strip().lower() or 'requested'
        nxt = str(next_status or '').strip().lower()
        if not nxt:
            return False
        if current == nxt:
            return True
        allowed = {
            'unknown': {'requested', 'accepted', 'queued', 'running', 'completed', 'failed', 'cancelled', 'timed_out'},
            'requested': {'accepted', 'queued', 'running', 'completed', 'failed', 'cancelled', 'timed_out'},
            'accepted': {'queued', 'running', 'completed', 'failed', 'cancelled', 'timed_out'},
            'queued': {'running', 'completed', 'failed', 'cancelled', 'timed_out'},
            'running': {'completed', 'failed', 'cancelled', 'timed_out'},
            'completed': set(),
            'failed': set(),
            'cancelled': set(),
            'timed_out': set(),
        }
        return nxt in allowed.get(current, set())

    @classmethod
    def _canonical_dispatch_view(cls, dispatch: dict[str, Any] | None) -> dict[str, Any] | None:
        if not dispatch:
            return dispatch
        response_payload = dict(dispatch.get('response') or {})
        canonical_status = cls._canonical_dispatch_status(str(dispatch.get('status') or ''), response_payload)
        lifecycle = dict(response_payload.get('lifecycle') or {})
        lifecycle.setdefault('canonical_status', canonical_status)
        lifecycle.setdefault('terminal', cls._is_terminal_canonical_status(canonical_status))
        lifecycle.setdefault('legacy_status', str(dispatch.get('status') or ''))
        lifecycle.setdefault('dispatch_mode', str(((((dispatch.get('request') or {}).get('policy') or {}).get('dispatch_mode')) or '')).strip().lower() or 'sync')
        enriched = dict(dispatch)
        enriched['canonical_status'] = canonical_status
        enriched['terminal'] = bool(lifecycle['terminal'])
        enriched['response'] = dict(response_payload)
        enriched['response']['lifecycle'] = lifecycle
        return enriched

    @staticmethod
    def _should_retry_http_error(exc: urllib.error.HTTPError) -> bool:
        try:
            code = int(getattr(exc, 'code', 0) or 0)
        except Exception:
            code = 0
        return code == 429 or code >= 500

    @classmethod
    def _build_runtime_summary(cls, runtime: dict[str, Any]) -> dict[str, Any]:
        metadata = cls._runtime_metadata(runtime)
        dispatch_policy = cls._dispatch_policy(runtime)
        session_bridge = cls._session_bridge(runtime)
        return {
            'runtime_id': runtime.get('runtime_id'),
            'name': runtime.get('name'),
            'transport': runtime.get('transport'),
            'scope': {
                'tenant_id': runtime.get('tenant_id'),
                'workspace_id': runtime.get('workspace_id'),
                'environment': runtime.get('environment'),
            },
            'allowed_actions': sorted(cls._allowed_actions(runtime)),
            'allowed_agents': sorted([str(item).strip() for item in list(runtime.get('allowed_agents') or []) if str(item).strip()]),
            'dispatch_policy': dispatch_policy,
            'operator_controls': {
                'retry_limit': dispatch_policy.get('operator_retry_limit'),
                'allow_cancel': dispatch_policy.get('allow_cancel'),
                'allow_manual_close': dispatch_policy.get('allow_manual_close'),
                'allow_reconcile': dispatch_policy.get('allow_reconcile'),
            },
            'session_bridge': session_bridge,
            'event_bridge': cls._event_bridge(runtime),
            'alert_notification_policy': cls._alert_notification_policy(runtime),
            'alert_notification_targets': cls._alert_notification_targets(runtime),
            'alert_escalation_policy': cls._alert_escalation_policy(runtime),
            'notification_budget_policy': cls._notification_budget_policy(runtime),
            'alert_routing_policy': cls._alert_routing_policy(runtime),
            'alert_governance_policy': cls._alert_governance_policy(runtime),
            'governance_release_policy': cls._governance_release_policy(runtime),
            'heartbeat_policy': cls._heartbeat_policy(runtime),
            'slo_policy': cls._slo_policy(runtime),
            'canonical_states': {
                'dispatch': ['requested', 'accepted', 'queued', 'running', 'completed', 'failed', 'cancelled', 'timed_out'],
                'runtime_health': ['unknown', 'healthy', 'degraded', 'unhealthy'],
            },
            'metadata': {
                'kind': metadata.get('kind'),
                'runtime_class': metadata.get('runtime_class'),
                'policy_pack': metadata.get('policy_pack'),
                'labels': cls._safe_json(metadata.get('labels') or {}),
            },
            'recovery_schedule': cls._recommended_recovery_schedule(runtime),
        }

    def register_runtime(
        self,
        gw,
        *,
        actor: str,
        name: str,
        base_url: str,
        transport: str = 'http',
        auth_secret_ref: str = '',
        capabilities: list[str] | None = None,
        allowed_agents: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        runtime_id: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        scope = self._normalize_scope(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        cleaned_name = str(name or '').strip()
        if not cleaned_name:
            raise ValueError('name is required')
        mode = str(transport or 'http').strip().lower() or 'http'
        if mode not in {'http', 'simulated'}:
            raise ValueError('transport must be http or simulated')
        cleaned_url = self._validate_base_url(base_url, transport=mode)
        incoming_metadata = dict(metadata or {})
        if any(key in incoming_metadata for key in ('policy_pack', 'runtime_class', 'kind')):
            normalized_metadata = self._apply_policy_pack_defaults(incoming_metadata, transport=mode)
        else:
            normalized_metadata = incoming_metadata
        normalized_metadata.setdefault('openclaw_compat_version', 'v2')
        runtime = gw.audit.upsert_openclaw_runtime(
            runtime_id=runtime_id,
            name=cleaned_name,
            base_url=cleaned_url,
            transport=mode,
            auth_secret_ref=str(auth_secret_ref or '').strip(),
            capabilities=[str(item).strip() for item in (capabilities or []) if str(item).strip()],
            allowed_agents=[str(item).strip() for item in (allowed_agents or []) if str(item).strip()],
            metadata=normalized_metadata,
            created_by=str(actor or 'system'),
            **scope,
        )
        gw.audit.log_event(
            'system',
            'broker',
            str(actor or 'system'),
            'system',
            {
                'action': 'openclaw_runtime_registered',
                'runtime_id': runtime.get('runtime_id'),
                'name': runtime.get('name'),
                'transport': runtime.get('transport'),
                'auth_secret_ref': runtime.get('auth_secret_ref'),
                'compat_version': normalized_metadata.get('openclaw_compat_version'),
            },
            **scope,
        )
        return {'ok': True, 'runtime': runtime, 'runtime_summary': self._build_runtime_summary(runtime)}

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

    def list_runtimes(self, gw, *, limit: int = 100, status: str | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any]:
        items = gw.audit.list_openclaw_runtimes(limit=limit, status=status, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        return {'ok': True, 'items': items, 'summary': {'count': len(items), 'status': status}}

    def get_runtime(self, gw, *, runtime_id: str, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any]:
        runtime = gw.audit.get_openclaw_runtime(runtime_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if runtime is None:
            return {'ok': False, 'error': 'runtime_not_found', 'runtime_id': runtime_id}
        dispatches = [
            self._canonical_dispatch_view(item)
            for item in gw.audit.list_openclaw_dispatches(runtime_id=runtime_id, limit=20, tenant_id=tenant_id or runtime.get('tenant_id'), workspace_id=workspace_id or runtime.get('workspace_id'), environment=environment or runtime.get('environment'))
        ]
        heartbeat_policy = self._heartbeat_policy(runtime)
        health = {
            'status': str(runtime.get('last_health_status') or 'unknown'),
            'checked_at': runtime.get('last_health_at'),
            'stale': False,
            'runtime_stale_after_s': heartbeat_policy.get('runtime_stale_after_s'),
        }
        try:
            checked_at = float(runtime.get('last_health_at') or 0.0)
        except Exception:
            checked_at = 0.0
        if checked_at > 0.0:
            health['stale'] = (time.time() - checked_at) > float(heartbeat_policy.get('runtime_stale_after_s') or 300.0)
        else:
            health['stale'] = True
        dispatch_summary: dict[str, int] = {}
        for item in dispatches:
            key = str((item or {}).get('canonical_status') or 'unknown')
            dispatch_summary[key] = dispatch_summary.get(key, 0) + 1
        return {'ok': True, 'runtime': runtime, 'runtime_summary': self._build_runtime_summary(runtime), 'dispatches': dispatches, 'dispatch_summary': dispatch_summary, 'health': health}

    def get_dispatch(self, gw, *, dispatch_id: str, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any]:
        dispatch = gw.audit.get_openclaw_dispatch(dispatch_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if dispatch is None:
            return {'ok': False, 'error': 'dispatch_not_found', 'dispatch_id': dispatch_id}
        runtime = gw.audit.get_openclaw_runtime(
            str(dispatch.get('runtime_id') or ''),
            tenant_id=tenant_id or dispatch.get('tenant_id'),
            workspace_id=workspace_id or dispatch.get('workspace_id'),
            environment=environment or dispatch.get('environment'),
        )
        scoped = self._canonical_dispatch_view(dispatch)
        return {
            'ok': True,
            'dispatch': scoped,
            'runtime': runtime,
            'runtime_summary': self._build_runtime_summary(runtime) if runtime else None,
        }

    def list_dispatches(self, gw, *, runtime_id: str | None = None, action: str | None = None, status: str | None = None, limit: int = 100, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any]:
        items = [
            self._canonical_dispatch_view(item)
            for item in gw.audit.list_openclaw_dispatches(runtime_id=runtime_id, action=action, status=status, limit=limit, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        ]
        canonical_state_counts: dict[str, int] = {}
        for item in items:
            canonical = str((item or {}).get('canonical_status') or 'unknown')
            canonical_state_counts[canonical] = canonical_state_counts.get(canonical, 0) + 1
        return {'ok': True, 'items': items, 'summary': {'count': len(items), 'status': status, 'action': action, 'canonical_state_counts': canonical_state_counts}}

    def get_runtime_timeline(
        self,
        gw,
        *,
        runtime_id: str,
        limit: int = 50,
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
        broker_events = gw.audit.get_recent_events(limit=max(limit * 4, 100), channel='broker', **scope)
        items: list[dict[str, Any]] = []
        for event in broker_events:
            payload = dict(event.get('payload') or {})
            if str(payload.get('runtime_id') or '') != str(runtime_id):
                continue
            items.append(
                {
                    'kind': 'event',
                    'ts': event.get('ts'),
                    'session_id': event.get('session_id'),
                    'user_id': event.get('user_id'),
                    'action': payload.get('action'),
                    'event_type': payload.get('event_type'),
                    'event_status': payload.get('event_status'),
                    'dispatch_id': payload.get('dispatch_id'),
                    'payload': self._safe_json(payload),
                }
            )
        dispatches = gw.audit.list_openclaw_dispatches(runtime_id=runtime_id, limit=limit, **scope)
        for dispatch in dispatches:
            enriched_dispatch = self._canonical_dispatch_view(dispatch)
            items.append(
                {
                    'kind': 'dispatch',
                    'ts': dispatch.get('created_at'),
                    'dispatch_id': dispatch.get('dispatch_id'),
                    'session_id': ((dispatch.get('request') or {}).get('correlation') or {}).get('openmiura_session_id'),
                    'action': dispatch.get('action'),
                    'status': dispatch.get('status'),
                    'canonical_status': (enriched_dispatch or {}).get('canonical_status'),
                    'terminal': (enriched_dispatch or {}).get('terminal'),
                    'payload': self._safe_json(enriched_dispatch),
                }
            )
        items.sort(key=lambda item: float(item.get('ts') or 0.0), reverse=True)
        items = items[:limit]
        return {
            'ok': True,
            'runtime': runtime,
            'runtime_summary': self._build_runtime_summary(runtime),
            'health': detail.get('health') or {},
            'timeline': items,
            'summary': {
                'count': len(items),
                'limit': int(limit),
                'session_bridge_enabled': self._session_bridge(runtime).get('enabled', True),
            },
        }


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

    def ingest_runtime_event(
        self,
        gw,
        *,
        runtime_id: str,
        actor: str = 'openclaw',
        source: str = 'openclaw',
        event_type: str,
        event_status: str = '',
        source_event_id: str = '',
        dispatch_id: str = '',
        session_id: str = '',
        user_key: str = '',
        message: str = '',
        payload: dict[str, Any] | None = None,
        observed_at: float | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        auth_mode: str = 'admin',
        event_token: str = '',
        require_token: bool = False,
    ) -> dict[str, Any]:
        runtime = gw.audit.get_openclaw_runtime(runtime_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if runtime is None:
            return {'ok': False, 'error': 'runtime_not_found', 'runtime_id': runtime_id}
        scope = self._normalize_scope(
            tenant_id=tenant_id or runtime.get('tenant_id'),
            workspace_id=workspace_id or runtime.get('workspace_id'),
            environment=environment or runtime.get('environment'),
        )
        bridge = self._event_bridge(runtime)
        if not bridge.get('enabled'):
            raise PermissionError(f"event bridge is disabled for runtime '{runtime_id}'")
        configured_token = self._event_bridge_token(runtime)
        if require_token:
            if not configured_token:
                raise PermissionError(f"runtime '{runtime_id}' has no event bridge token configured")
            if not event_token or not secrets.compare_digest(str(event_token), configured_token):
                raise PermissionError('invalid runtime event token')
        source_name = str(source or bridge.get('source_label') or actor or 'openclaw').strip() or 'openclaw'
        accepted_sources = {str(item).strip() for item in list(bridge.get('accepted_sources') or []) if str(item).strip()}
        if accepted_sources and source_name not in accepted_sources:
            raise PermissionError(f"source '{source_name}' not allowed for runtime '{runtime_id}'")
        event_name = str(event_type or '').strip().lower()
        if not event_name:
            raise ValueError('event_type is required')
        accepted_types = {str(item).strip().lower() for item in list(bridge.get('accepted_event_types') or []) if str(item).strip()}
        if accepted_types and event_name not in accepted_types:
            raise PermissionError(f"event_type '{event_name}' not allowed for runtime '{runtime_id}'")
        duplicate: dict[str, Any] | None = None
        source_event_key = str(source_event_id or '').strip()
        if source_event_key:
            for item in gw.audit.get_recent_events(limit=200, channel='broker', **scope):
                payload_row = dict(item.get('payload') or {})
                if str(payload_row.get('action') or '') != 'openclaw_event_bridged':
                    continue
                if str(payload_row.get('runtime_id') or '') != str(runtime_id):
                    continue
                if str(payload_row.get('source') or '') != source_name:
                    continue
                if str(payload_row.get('source_event_id') or '') != source_event_key:
                    continue
                duplicate = item
                break
        if duplicate is not None:
            return {'ok': True, 'duplicate': True, 'event': duplicate, 'runtime': runtime, 'runtime_summary': self._build_runtime_summary(runtime)}
        dispatch = None
        dispatch_key = str(dispatch_id or '').strip()
        if dispatch_key:
            dispatch = gw.audit.get_openclaw_dispatch(dispatch_key, **scope)
            if dispatch is None or str(dispatch.get('runtime_id') or '') != str(runtime_id):
                raise ValueError(f"dispatch '{dispatch_key}' not found for runtime '{runtime_id}'")
        inferred_session = str(session_id or '').strip()
        if not inferred_session and dispatch is not None:
            inferred_session = str((((dispatch.get('request') or {}).get('correlation') or {}).get('openmiura_session_id')) or '').strip()
        observed = float(observed_at if observed_at is not None else time.time())
        event_payload = {
            'action': 'openclaw_event_bridged',
            'runtime_id': runtime_id,
            'dispatch_id': dispatch_key,
            'source': source_name,
            'event_type': event_name,
            'event_status': str(event_status or '').strip().lower(),
            'source_event_id': source_event_key,
            'message': str(message or '').strip(),
            'observed_at': observed,
            'ingested_via': str(auth_mode or 'admin'),
            'payload': self._safe_json(payload or {}),
        }
        event_id = gw.audit.log_event(
            'inbound',
            'broker',
            str(actor or source_name),
            inferred_session or dispatch_key or 'system',
            event_payload,
            **scope,
        )
        updated_dispatch = dispatch
        mapped_status = self._map_event_to_dispatch_status(event_type=event_name, event_status=event_status)
        if dispatch is not None and mapped_status:
            current_canonical = self._canonical_dispatch_status(str(dispatch.get('status') or ''), dict(dispatch.get('response') or {}))
            next_canonical = self._canonical_dispatch_status(mapped_status, dict(dispatch.get('response') or {}))
            response_payload = dict(dispatch.get('response') or {})
            lifecycle = dict(response_payload.get('lifecycle') or {})
            response_payload['event_bridge'] = {
                'event_id': event_id,
                'source': source_name,
                'event_type': event_name,
                'event_status': str(event_status or '').strip().lower(),
                'source_event_id': source_event_key,
                'message': str(message or '').strip(),
                'observed_at': observed,
                'payload': self._safe_json(payload or {}),
            }
            if self._is_valid_dispatch_transition(current_canonical, next_canonical):
                lifecycle.update(
                    {
                        'canonical_status': next_canonical,
                        'terminal': self._is_terminal_canonical_status(next_canonical),
                        'last_event_type': event_name,
                        'last_event_status': str(event_status or '').strip().lower(),
                        'last_observed_at': observed,
                    }
                )
                response_payload['lifecycle'] = lifecycle
                updated_dispatch = gw.audit.update_openclaw_dispatch(
                    dispatch_key,
                    status=mapped_status,
                    response_payload=response_payload,
                    error_text=str(message or dispatch.get('error_text') or '') if mapped_status == 'error' else str(dispatch.get('error_text') or ''),
                    latency_ms=dispatch.get('latency_ms'),
                    **scope,
                ) or dispatch
                updated_dispatch = self._canonical_dispatch_view(updated_dispatch)
            else:
                lifecycle.update(
                    {
                        'canonical_status': current_canonical,
                        'terminal': self._is_terminal_canonical_status(current_canonical),
                        'transition_conflict': {
                            'current': current_canonical,
                            'attempted': next_canonical,
                            'event_type': event_name,
                            'event_status': str(event_status or '').strip().lower(),
                        },
                    }
                )
                response_payload['lifecycle'] = lifecycle
                updated_dispatch = gw.audit.update_openclaw_dispatch(
                    dispatch_key,
                    status=str(dispatch.get('status') or ''),
                    response_payload=response_payload,
                    error_text=str(dispatch.get('error_text') or ''),
                    latency_ms=dispatch.get('latency_ms'),
                    **scope,
                ) or dispatch
                updated_dispatch = self._canonical_dispatch_view(updated_dispatch)
        runtime = self._refresh_runtime_heartbeat(
            gw,
            runtime_id=runtime_id,
            scope=scope,
            health_status='healthy',
            observed_at=observed,
        ) or runtime
        return {
            'ok': True,
            'runtime': runtime,
            'runtime_summary': self._build_runtime_summary(runtime),
            'event': {
                'event_id': event_id,
                'runtime_id': runtime_id,
                'dispatch_id': dispatch_key,
                'source': source_name,
                'event_type': event_name,
                'event_status': str(event_status or '').strip().lower(),
                'source_event_id': source_event_key,
                'message': str(message or '').strip(),
                'observed_at': observed,
                'session_id': inferred_session,
                'payload': self._safe_json(payload or {}),
            },
            'dispatch': updated_dispatch,
        }


    def poll_dispatch(
        self,
        gw,
        *,
        dispatch_id: str,
        actor: str,
        reason: str = '',
        user_role: str = 'operator',
        user_key: str = '',
        session_id: str = 'system',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        detail = self.get_dispatch(gw, dispatch_id=dispatch_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if not detail.get('ok'):
            return detail
        dispatch = dict(detail.get('dispatch') or {})
        runtime = dict(detail.get('runtime') or {})
        scope = self._normalize_scope(
            tenant_id=tenant_id or dispatch.get('tenant_id') or runtime.get('tenant_id'),
            workspace_id=workspace_id or dispatch.get('workspace_id') or runtime.get('workspace_id'),
            environment=environment or dispatch.get('environment') or runtime.get('environment'),
        )
        current = str(dispatch.get('canonical_status') or self._canonical_dispatch_status(str(dispatch.get('status') or ''), dict(dispatch.get('response') or {}))).strip().lower()
        response_payload = dict(dispatch.get('response') or {})
        lifecycle = dict(response_payload.get('lifecycle') or {})
        poll_count = int(lifecycle.get('poll_count') or 0) + 1
        heartbeat_policy = self._heartbeat_policy(runtime)
        remote: dict[str, Any] = {'attempted': False}
        mapped_status = ''
        observed = time.time()
        if str(runtime.get('transport') or '').strip().lower() == 'simulated':
            remote = {
                'attempted': True,
                'mode': 'simulated',
                'target_url': self._operation_url(runtime, operation='status', dispatch_id=dispatch_id),
                'accepted': True,
                'response': {'status': current or 'accepted'},
            }
            mapped_status = current
        else:
            target_url = self._operation_url(runtime, operation='status', dispatch_id=dispatch_id)
            headers = {'Content-Type': 'application/json'}
            secret_ref = str(runtime.get('auth_secret_ref') or '').strip()
            if secret_ref:
                broker = getattr(gw, 'secret_broker', None)
                if broker is None:
                    raise SecretAccessDenied('secret broker not configured')
                secret_value = broker.resolve(
                    secret_ref,
                    tool_name=self.TOOL_NAME,
                    user_role=str(user_role or 'operator'),
                    user_key=str(user_key or actor or ''),
                    session_id=str(session_id or 'system'),
                    tenant_id=scope['tenant_id'],
                    workspace_id=scope['workspace_id'],
                    environment=scope['environment'],
                    domain=self._runtime_domain(runtime),
                )
                headers['Authorization'] = f'Bearer {secret_value}'
            attempts = 0
            last_exc: Exception | None = None
            max_attempts = max(0, int(heartbeat_policy.get('max_poll_retries') or 0))
            for attempt in range(max_attempts + 1):
                attempts = attempt + 1
                req = urllib.request.Request(target_url, headers=headers, method='GET')
                try:
                    with urllib.request.urlopen(req, timeout=float(self._dispatch_policy(runtime).get('timeout_s') or 15.0)) as resp:  # nosec - controlled admin path
                        raw = resp.read().decode('utf-8', errors='replace')
                        try:
                            parsed = json.loads(raw) if raw else {}
                        except Exception:
                            parsed = {'raw': raw}
                        parsed_status = str(parsed.get('status') or parsed.get('state') or parsed.get('run_status') or '').strip().lower()
                        mapped_status = self._canonical_dispatch_status(parsed_status, parsed if isinstance(parsed, dict) else {})
                        remote = {
                            'attempted': True,
                            'mode': 'http',
                            'target_url': target_url,
                            'accepted': 200 <= int(getattr(resp, 'status', 200) or 200) < 300,
                            'status_code': int(getattr(resp, 'status', 200) or 200),
                            'response': self._safe_json(parsed),
                            'attempts': attempts,
                        }
                        break
                except urllib.error.HTTPError as exc:
                    last_exc = exc
                    if attempt >= max_attempts or not self._should_retry_http_error(exc):
                        raise
                except Exception as exc:
                    last_exc = exc
                    if attempt >= max_attempts:
                        raise
                time.sleep(float(self._dispatch_policy(runtime).get('retry_backoff_ms') or 0) / 1000.0)
            else:
                raise last_exc or RuntimeError('dispatch_poll_failed')
        lifecycle.update({
            'last_polled_at': observed,
            'last_polled_by': str(actor or 'system'),
            'poll_count': poll_count,
            'last_poll_reason': str(reason or '').strip(),
        })
        next_canonical = self._canonical_dispatch_status(mapped_status or current, remote.get('response') if isinstance(remote.get('response'), dict) else {})
        if mapped_status and self._is_valid_dispatch_transition(current, next_canonical):
            lifecycle.update({
                'canonical_status': next_canonical,
                'terminal': self._is_terminal_canonical_status(next_canonical),
                'legacy_status': 'error' if next_canonical == 'failed' else next_canonical,
                'last_polled_status': next_canonical,
            })
            storage_status = 'error' if next_canonical == 'failed' else next_canonical
        else:
            lifecycle.update({
                'canonical_status': current,
                'terminal': self._is_terminal_canonical_status(current),
                'last_polled_status': next_canonical or current,
            })
            storage_status = str(dispatch.get('status') or '')
        response_payload['lifecycle'] = lifecycle
        response_payload['poll'] = {
            'requested_by': str(actor or 'system'),
            'reason': str(reason or '').strip(),
            'session_id': str(session_id or 'system'),
            'remote': self._safe_json(remote),
        }
        response_payload = self._append_operator_action(response_payload, action='poll', actor=actor, reason=reason, details={'dispatch_id': dispatch_id, 'remote': remote})
        updated = gw.audit.update_openclaw_dispatch(
            dispatch_id,
            status=storage_status,
            response_payload=response_payload,
            error_text=str(dispatch.get('error_text') or ''),
            latency_ms=dispatch.get('latency_ms'),
            **scope,
        )
        runtime = self._refresh_runtime_heartbeat(gw, runtime_id=str(runtime.get('runtime_id') or ''), scope=scope, health_status='healthy', observed_at=observed) or runtime
        gw.audit.log_event('system', 'broker', str(actor or 'system'), str(session_id or 'system'), {'action': 'openclaw_dispatch_polled', 'runtime_id': runtime.get('runtime_id'), 'dispatch_id': dispatch_id, 'current_status': current, 'next_status': next_canonical, 'reason': str(reason or '').strip()}, **scope)
        return {'ok': True, 'dispatch': self._canonical_dispatch_view(updated), 'runtime': runtime, 'runtime_summary': self._build_runtime_summary(runtime), 'operation': {'kind': 'poll', 'remote': self._safe_json(remote)}}

    def recover_stale_dispatches(
        self,
        gw,
        *,
        runtime_id: str,
        actor: str,
        reason: str = '',
        limit: int = 50,
        user_role: str = 'operator',
        user_key: str = '',
        session_id: str = 'system',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        runtime_detail = self.get_runtime(gw, runtime_id=runtime_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if not runtime_detail.get('ok'):
            return runtime_detail
        runtime = dict(runtime_detail.get('runtime') or {})
        scope = self._normalize_scope(
            tenant_id=tenant_id or runtime.get('tenant_id'),
            workspace_id=workspace_id or runtime.get('workspace_id'),
            environment=environment or runtime.get('environment'),
        )
        heartbeat_policy = self._heartbeat_policy(runtime)
        dispatches = self.list_dispatches(gw, runtime_id=runtime_id, limit=max(1, int(limit)), tenant_id=scope['tenant_id'], workspace_id=scope['workspace_id'], environment=scope['environment'])
        items = list(dispatches.get('items') or [])
        active_statuses = {'requested', 'accepted', 'queued', 'running'}
        scanned = 0
        stale_candidates = 0
        polled_count = 0
        reconciled_count = 0
        outputs: list[dict[str, Any]] = []
        now = time.time()
        for item in items:
            canonical = str(item.get('canonical_status') or '').strip().lower()
            if canonical not in active_statuses:
                continue
            scanned += 1
            signal_ts = self._dispatch_signal_ts(item)
            age_s = max(0.0, now - signal_ts) if signal_ts > 0.0 else float('inf')
            is_stale = age_s >= float(heartbeat_policy.get('active_run_stale_after_s') or 0.0)
            if not is_stale:
                continue
            stale_candidates += 1
            current_detail = self.get_dispatch(gw, dispatch_id=str(item.get('dispatch_id') or ''), tenant_id=scope['tenant_id'], workspace_id=scope['workspace_id'], environment=scope['environment'])
            current_dispatch = dict(current_detail.get('dispatch') or item)
            if bool(heartbeat_policy.get('auto_poll_enabled')):
                polled = self.poll_dispatch(
                    gw,
                    dispatch_id=str(item.get('dispatch_id') or ''),
                    actor=actor,
                    reason=str(reason or 'automatic stale-run recovery poll'),
                    user_role=user_role,
                    user_key=user_key,
                    session_id=session_id,
                    tenant_id=scope['tenant_id'],
                    workspace_id=scope['workspace_id'],
                    environment=scope['environment'],
                )
                polled_count += 1
                current_dispatch = dict(polled.get('dispatch') or current_dispatch)
            current_canonical = str(current_dispatch.get('canonical_status') or '').strip().lower()
            current_signal_ts = self._dispatch_signal_ts(current_dispatch)
            current_age_s = max(0.0, time.time() - current_signal_ts) if current_signal_ts > 0.0 else age_s
            auto_reconciled = False
            if current_canonical in active_statuses and bool(heartbeat_policy.get('auto_reconcile_enabled')) and current_age_s >= float(heartbeat_policy.get('auto_reconcile_after_s') or 0.0):
                reconciled = self.reconcile_dispatch(
                    gw,
                    dispatch_id=str(item.get('dispatch_id') or ''),
                    actor=actor,
                    target_status=str(heartbeat_policy.get('stale_target_status') or 'timed_out'),
                    reason=str(reason or 'automatic stale-run recovery'),
                    user_role=user_role,
                    user_key=user_key,
                    session_id=session_id,
                    tenant_id=scope['tenant_id'],
                    workspace_id=scope['workspace_id'],
                    environment=scope['environment'],
                )
                current_dispatch = dict(reconciled.get('dispatch') or current_dispatch)
                reconciled_count += 1
                auto_reconciled = True
            outputs.append({
                'dispatch_id': str(item.get('dispatch_id') or ''),
                'was_stale': True,
                'age_s': round(current_age_s, 3),
                'canonical_status': str(current_dispatch.get('canonical_status') or current_canonical or canonical),
                'polled': True if is_stale and bool(heartbeat_policy.get('auto_poll_enabled')) else False,
                'auto_reconciled': auto_reconciled,
            })
        gw.audit.log_event('system', 'broker', str(actor or 'system'), str(session_id or 'system'), {'action': 'openclaw_runtime_stale_recovery', 'runtime_id': runtime_id, 'scanned': scanned, 'stale_candidates': stale_candidates, 'polled_count': polled_count, 'reconciled_count': reconciled_count, 'reason': str(reason or '').strip()}, **scope)
        refreshed_runtime = self.get_runtime(gw, runtime_id=runtime_id, tenant_id=scope['tenant_id'], workspace_id=scope['workspace_id'], environment=scope['environment'])
        return {
            'ok': True,
            'runtime': refreshed_runtime.get('runtime') or runtime,
            'runtime_summary': refreshed_runtime.get('runtime_summary') or self._build_runtime_summary(runtime),
            'health': refreshed_runtime.get('health') or runtime_detail.get('health') or {},
            'items': outputs,
            'summary': {
                'runtime_id': runtime_id,
                'scanned': scanned,
                'stale_candidates': stale_candidates,
                'polled_count': polled_count,
                'reconciled_count': reconciled_count,
                'active_run_stale_after_s': heartbeat_policy.get('active_run_stale_after_s'),
                'auto_reconcile_after_s': heartbeat_policy.get('auto_reconcile_after_s'),
                'stale_target_status': heartbeat_policy.get('stale_target_status'),
            },
        }

    def check_runtime_health(
        self,
        gw,
        *,
        runtime_id: str,
        actor: str = 'system',
        probe: str = 'ready',
        user_role: str = 'operator',
        user_key: str = '',
        session_id: str = 'system',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        runtime = gw.audit.get_openclaw_runtime(runtime_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if runtime is None:
            return {'ok': False, 'error': 'runtime_not_found', 'runtime_id': runtime_id}
        scope = self._normalize_scope(
            tenant_id=tenant_id or runtime.get('tenant_id'),
            workspace_id=workspace_id or runtime.get('workspace_id'),
            environment=environment or runtime.get('environment'),
        )
        mode = str(runtime.get('transport') or 'http').strip().lower() or 'http'
        dispatch_policy = self._dispatch_policy(runtime)
        started_at = time.time()
        status = 'unknown'
        detail: dict[str, Any]
        secret_ref = str(runtime.get('auth_secret_ref') or '').strip()
        secret_value = ''
        redacted_headers: dict[str, Any] = {}
        if secret_ref:
            broker = getattr(gw, 'secret_broker', None)
            if broker is None:
                raise SecretAccessDenied('secret broker not configured')
            secret_value = broker.resolve(
                secret_ref,
                tool_name=self.TOOL_NAME,
                user_role=str(user_role or 'operator'),
                user_key=str(user_key or actor or ''),
                session_id=str(session_id or 'system'),
                tenant_id=scope['tenant_id'],
                workspace_id=scope['workspace_id'],
                environment=scope['environment'],
                domain=self._runtime_domain(runtime),
            )
            redacted_headers['Authorization'] = f'[secret:{secret_ref}]'
        attempts = 0
        last_error: str | None = None
        try:
            if mode == 'simulated':
                status = 'healthy'
                detail = {'probe': probe, 'mode': 'simulated', 'target_url': self._health_url(runtime), 'headers': redacted_headers, 'accepted': True, 'attempts': 1}
            else:
                target_url = self._health_url(runtime)
                headers = {}
                if secret_value:
                    headers['Authorization'] = f'Bearer {secret_value}'
                last_exc: Exception | None = None
                for attempt in range(dispatch_policy['max_retries'] + 1):
                    attempts = attempt + 1
                    req = urllib.request.Request(target_url, headers=headers, method='GET')
                    try:
                        with urllib.request.urlopen(req, timeout=float(dispatch_policy['timeout_s'])) as resp:  # nosec - controlled admin path
                            raw = resp.read().decode('utf-8', errors='replace')
                            try:
                                parsed = json.loads(raw) if raw else {}
                            except Exception:
                                parsed = {'raw': raw}
                            accepted = 200 <= int(getattr(resp, 'status', 200) or 200) < 300
                            status = 'healthy' if accepted else 'degraded'
                            detail = {
                                'probe': probe,
                                'mode': 'http',
                                'target_url': target_url,
                                'status_code': int(getattr(resp, 'status', 200) or 200),
                                'headers': redacted_headers,
                                'response': self._safe_json(parsed),
                                'accepted': accepted,
                                'attempts': attempts,
                            }
                            break
                    except urllib.error.HTTPError as exc:
                        last_exc = exc
                        if attempt >= dispatch_policy['max_retries'] or not self._should_retry_http_error(exc):
                            raise
                    except Exception as exc:
                        last_exc = exc
                        if attempt >= dispatch_policy['max_retries']:
                            raise
                    time.sleep(float(dispatch_policy['retry_backoff_ms']) / 1000.0)
                else:
                    raise last_exc or RuntimeError('health_check_failed')
        except urllib.error.HTTPError as exc:
            body = exc.read().decode('utf-8', errors='replace') if hasattr(exc, 'read') else ''
            status = 'unhealthy'
            last_error = str(exc)
            detail = {'probe': probe, 'mode': mode, 'target_url': self._health_url(runtime), 'status_code': int(exc.code), 'body': body[:4000], 'headers': redacted_headers, 'accepted': False, 'attempts': max(1, attempts)}
        except Exception as exc:
            status = 'unhealthy'
            last_error = str(exc)
            detail = {'probe': probe, 'mode': mode, 'target_url': self._health_url(runtime), 'error': str(exc), 'headers': redacted_headers, 'accepted': False, 'attempts': max(1, attempts)}
        checked_at = time.time()
        updated_runtime = self._safe_json(
            gw.audit.update_openclaw_runtime_health(
                runtime_id,
                health_status=status,
                health_at=checked_at,
                tenant_id=scope['tenant_id'],
                workspace_id=scope['workspace_id'],
                environment=scope['environment'],
            )
            or runtime
        )
        latency_ms = max(0.0, (checked_at - started_at) * 1000.0)
        gw.audit.log_event(
            'system',
            'broker',
            str(actor or 'system'),
            str(session_id or 'system'),
            {
                'action': 'openclaw_runtime_health_checked',
                'runtime_id': runtime_id,
                'probe': probe,
                'health_status': status,
                'latency_ms': latency_ms,
                'attempts': detail.get('attempts'),
                'error': last_error,
            },
            **scope,
        )
        return {'ok': status != 'unhealthy', 'runtime': updated_runtime, 'runtime_summary': self._build_runtime_summary(runtime), 'health': {'status': status, 'checked_at': checked_at, 'latency_ms': latency_ms, 'detail': detail}}

    def dispatch(
        self,
        gw,
        *,
        runtime_id: str,
        actor: str,
        action: str,
        payload: dict[str, Any] | None = None,
        agent_id: str = '',
        user_role: str = 'operator',
        user_key: str = '',
        session_id: str = 'system',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        dry_run: bool = False,
        correlation_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        runtime = gw.audit.get_openclaw_runtime(runtime_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if runtime is None:
            return {'ok': False, 'error': 'runtime_not_found', 'runtime_id': runtime_id}
        requested_action = str(action or '').strip().lower()
        if not requested_action:
            raise ValueError('action is required')
        requested_agent = str(agent_id or '').strip()
        allowed_agents = {str(item).strip() for item in list(runtime.get('allowed_agents') or []) if str(item).strip()}
        if requested_agent and allowed_agents and requested_agent not in allowed_agents:
            raise PermissionError(f"agent '{requested_agent}' not allowed for runtime '{runtime_id}'")
        allowed_actions = self._allowed_actions(runtime)
        if allowed_actions and requested_action not in allowed_actions:
            raise PermissionError(f"action '{requested_action}' not allowed for runtime '{runtime_id}'")
        scope = self._normalize_scope(
            tenant_id=tenant_id or runtime.get('tenant_id'),
            workspace_id=workspace_id or runtime.get('workspace_id'),
            environment=environment or runtime.get('environment'),
        )
        dispatch_policy = self._dispatch_policy(runtime)
        quota_per_hour = dispatch_policy.get('quota_per_hour')
        if quota_per_hour:
            recent = gw.audit.count_openclaw_dispatches(
                runtime_id=runtime_id,
                since_ts=time.time() - 3600.0,
                tenant_id=scope['tenant_id'],
                workspace_id=scope['workspace_id'],
                environment=scope['environment'],
            )
            if int(recent) >= int(quota_per_hour):
                raise PermissionError(f"runtime '{runtime_id}' exceeded hourly dispatch quota ({quota_per_hour})")
        max_active_runs = dispatch_policy.get('max_active_runs')
        if max_active_runs:
            active_for_runtime = self._active_dispatch_count(
                gw,
                runtime_id=runtime_id,
                tenant_id=scope['tenant_id'],
                workspace_id=scope['workspace_id'],
                environment=scope['environment'],
            )
            if int(active_for_runtime) >= int(max_active_runs):
                raise PermissionError(f"runtime '{runtime_id}' exceeded active-run backpressure limit ({max_active_runs})")
        max_active_runs_per_workspace = dispatch_policy.get('max_active_runs_per_workspace')
        if max_active_runs_per_workspace:
            active_for_workspace = self._active_dispatch_count(
                gw,
                tenant_id=scope['tenant_id'],
                workspace_id=scope['workspace_id'],
                environment=scope['environment'],
            )
            if int(active_for_workspace) >= int(max_active_runs_per_workspace):
                raise PermissionError(f"workspace '{scope['workspace_id'] or '-'}' exceeded active-run backpressure limit ({max_active_runs_per_workspace})")
        session_bridge = self._session_bridge(runtime)
        correlation = {
            'openmiura_session_id': str(session_id or 'system'),
            'openmiura_user_key': str(user_key or actor or ''),
            'tenant_id': scope['tenant_id'],
            'workspace_id': scope['workspace_id'],
            'environment': scope['environment'],
            'workspace_connection': session_bridge.get('workspace_connection'),
            'external_workspace_id': session_bridge.get('external_workspace_id'),
            'external_environment': session_bridge.get('external_environment'),
            'event_bridge_enabled': bool(session_bridge.get('event_bridge_enabled')),
        }
        for key, value in dict(correlation_overrides or {}).items():
            if value is not None:
                correlation[str(key)] = self._safe_json(value)
        request_payload = {
            'runtime_id': runtime_id,
            'runtime_name': runtime.get('name'),
            'action': requested_action,
            'agent_id': requested_agent,
            'payload': self._safe_json(payload or {}),
            'requested_by': str(actor or 'system'),
            'scope': scope,
            'correlation': correlation,
            'policy': {
                'allowed_actions': sorted(allowed_actions),
                'allowed_agents': sorted(allowed_agents),
                'quota_per_hour': quota_per_hour,
                'dispatch_mode': dispatch_policy.get('dispatch_mode') or 'sync',
                'poll_after_s': dispatch_policy.get('poll_after_s') or 0.0,
            },
        }
        secret_ref = str(runtime.get('auth_secret_ref') or '').strip()
        redacted_headers: dict[str, Any] = {}
        secret_value = ''
        if secret_ref:
            broker = getattr(gw, 'secret_broker', None)
            if broker is None:
                raise SecretAccessDenied('secret broker not configured')
            secret_value = broker.resolve(
                secret_ref,
                tool_name=self.TOOL_NAME,
                user_role=str(user_role or 'operator'),
                user_key=str(user_key or actor or ''),
                session_id=str(session_id or 'system'),
                tenant_id=scope['tenant_id'],
                workspace_id=scope['workspace_id'],
                environment=scope['environment'],
                domain=self._runtime_domain(runtime),
            )
            redacted_headers['Authorization'] = f'[secret:{secret_ref}]'
        dispatch_row = gw.audit.create_openclaw_dispatch(
            runtime_id=runtime_id,
            action=requested_action,
            agent_id=requested_agent,
            status='pending',
            request_payload=request_payload,
            response_payload={
                'lifecycle': {
                    'canonical_status': 'requested',
                    'terminal': False,
                    'legacy_status': 'pending',
                    'dispatch_mode': dispatch_policy.get('dispatch_mode') or 'sync',
                    'retry_count': int((dict(correlation_overrides or {}).get('retry_count') or 0)),
                }
            },
            secret_ref=secret_ref,
            created_by=str(actor or 'system'),
            **scope,
        )
        request_payload['correlation']['dispatch_id'] = dispatch_row.get('dispatch_id')
        gw.audit.log_event(
            'system',
            'broker',
            str(actor or 'system'),
            str(session_id or 'system'),
            {
                'action': 'openclaw_dispatch_requested',
                'runtime_id': runtime_id,
                'dispatch_id': dispatch_row.get('dispatch_id'),
                'dispatch_action': requested_action,
                'agent_id': requested_agent,
                'dry_run': bool(dry_run),
                'workspace_connection': session_bridge.get('workspace_connection'),
            },
            **scope,
        )
        started_at = time.time()
        try:
            mode = str(runtime.get('transport') or 'http').strip().lower() or 'http'
            response_payload: dict[str, Any]
            status = 'ok'
            canonical_status = 'completed'
            terminal = True
            if dry_run or mode == 'simulated':
                dispatch_mode = str(dispatch_policy.get('dispatch_mode') or 'sync')
                if dispatch_mode == 'async' and not dry_run:
                    status = 'accepted'
                    canonical_status = 'accepted'
                    terminal = False
                response_payload = {
                    'accepted': True,
                    'mode': 'dry-run' if dry_run else 'simulated',
                    'target_url': self._dispatch_url(runtime),
                    'headers': redacted_headers,
                    'request': request_payload,
                    'attempts': 1,
                    'lifecycle': {
                        'canonical_status': canonical_status,
                        'terminal': terminal,
                        'legacy_status': status,
                        'dispatch_mode': dispatch_mode,
                        'poll_after_s': dispatch_policy.get('poll_after_s') or 0.0,
                        'retry_count': int((dict(correlation_overrides or {}).get('retry_count') or 0)),
                    },
                }
                if mode == 'simulated' and not dry_run:
                    response_payload['result'] = {'runtime': 'openclaw', 'status': 'accepted' if dispatch_mode == 'async' else 'completed', 'capabilities': runtime.get('capabilities') or []}
            else:
                target_url = self._dispatch_url(runtime)
                body = json.dumps(request_payload, ensure_ascii=False).encode('utf-8')
                headers = {'Content-Type': 'application/json'}
                if secret_value:
                    headers['Authorization'] = f'Bearer {secret_value}'
                last_exc: Exception | None = None
                attempts = 0
                for attempt in range(dispatch_policy['max_retries'] + 1):
                    attempts = attempt + 1
                    req = urllib.request.Request(target_url, data=body, headers=headers, method='POST')
                    try:
                        with urllib.request.urlopen(req, timeout=float(dispatch_policy['timeout_s'])) as resp:  # nosec - controlled admin path
                            raw = resp.read().decode('utf-8', errors='replace')
                            try:
                                parsed = json.loads(raw) if raw else {}
                            except Exception:
                                parsed = {'raw': raw}
                            parsed_status = str(parsed.get('status') or parsed.get('state') or parsed.get('run_status') or '').strip().lower()
                            dispatch_mode = str(dispatch_policy.get('dispatch_mode') or 'sync')
                            if dispatch_mode == 'async':
                                if parsed_status in {'queued', 'running'}:
                                    status = parsed_status
                                elif parsed_status in {'accepted', 'pending'}:
                                    status = 'accepted'
                                elif parsed_status in {'completed', 'ok', 'success', 'succeeded'}:
                                    status = 'completed'
                                elif parsed_status in {'failed', 'error'}:
                                    status = 'error'
                                elif parsed_status in {'cancelled', 'timed_out'}:
                                    status = parsed_status
                                else:
                                    status = 'accepted'
                            canonical_status = self._canonical_dispatch_status(status, parsed if isinstance(parsed, dict) else {})
                            terminal = self._is_terminal_canonical_status(canonical_status)
                            response_payload = {
                                'accepted': 200 <= int(getattr(resp, 'status', 200) or 200) < 300,
                                'mode': 'http',
                                'target_url': target_url,
                                'status_code': int(getattr(resp, 'status', 200) or 200),
                                'headers': redacted_headers,
                                'response': self._safe_json(parsed),
                                'attempts': attempts,
                                'lifecycle': {
                                    'canonical_status': canonical_status,
                                    'terminal': terminal,
                                    'legacy_status': status,
                                    'dispatch_mode': dispatch_policy.get('dispatch_mode') or 'sync',
                                    'poll_after_s': dispatch_policy.get('poll_after_s') or 0.0,
                                    'retry_count': int((dict(correlation_overrides or {}).get('retry_count') or 0)),
                                },
                            }
                            break
                    except urllib.error.HTTPError as exc:
                        last_exc = exc
                        if attempt >= dispatch_policy['max_retries'] or not self._should_retry_http_error(exc):
                            raise
                    except Exception as exc:
                        last_exc = exc
                        if attempt >= dispatch_policy['max_retries']:
                            raise
                    time.sleep(float(dispatch_policy['retry_backoff_ms']) / 1000.0)
                else:
                    raise last_exc or RuntimeError('dispatch_failed')
            latency_ms = max(0.0, (time.time() - started_at) * 1000.0)
            updated = gw.audit.update_openclaw_dispatch(
                dispatch_row['dispatch_id'],
                status=status,
                response_payload=response_payload,
                error_text='',
                latency_ms=latency_ms,
                **scope,
            )
            gw.audit.log_event(
                'system',
                'broker',
                str(actor or 'system'),
                str(session_id or 'system'),
                {
                    'action': 'openclaw_dispatch_completed',
                    'runtime_id': runtime_id,
                    'dispatch_id': dispatch_row.get('dispatch_id'),
                    'dispatch_action': requested_action,
                    'latency_ms': latency_ms,
                    'status': status,
                    'canonical_status': canonical_status,
                    'terminal': terminal,
                    'attempts': response_payload.get('attempts'),
                },
                **scope,
            )
            updated = self._canonical_dispatch_view(updated)
            return {
                'ok': True,
                'runtime': runtime,
                'runtime_summary': self._build_runtime_summary(runtime),
                'dispatch': updated,
                'request': {'target_url': self._dispatch_url(runtime), 'headers': redacted_headers, 'body': request_payload},
                'response': response_payload,
            }
        except (SecretBrokerError, PermissionError, ValueError):
            raise
        except urllib.error.HTTPError as exc:
            latency_ms = max(0.0, (time.time() - started_at) * 1000.0)
            body = exc.read().decode('utf-8', errors='replace') if hasattr(exc, 'read') else ''
            updated = gw.audit.update_openclaw_dispatch(dispatch_row['dispatch_id'], status='error', response_payload={'status_code': int(exc.code), 'body': body[:4000]}, error_text=str(exc), latency_ms=latency_ms, **scope)
            gw.audit.log_event('system', 'broker', str(actor or 'system'), str(session_id or 'system'), {'action': 'openclaw_dispatch_failed', 'runtime_id': runtime_id, 'dispatch_id': dispatch_row.get('dispatch_id'), 'dispatch_action': requested_action, 'latency_ms': latency_ms, 'error': str(exc)}, **scope)
            return {'ok': False, 'runtime': runtime, 'runtime_summary': self._build_runtime_summary(runtime), 'dispatch': updated, 'error': str(exc)}
        except Exception as exc:
            latency_ms = max(0.0, (time.time() - started_at) * 1000.0)
            updated = gw.audit.update_openclaw_dispatch(dispatch_row['dispatch_id'], status='error', response_payload={}, error_text=str(exc), latency_ms=latency_ms, **scope)
            gw.audit.log_event('system', 'broker', str(actor or 'system'), str(session_id or 'system'), {'action': 'openclaw_dispatch_failed', 'runtime_id': runtime_id, 'dispatch_id': dispatch_row.get('dispatch_id'), 'dispatch_action': requested_action, 'latency_ms': latency_ms, 'error': str(exc)}, **scope)
            return {'ok': False, 'runtime': runtime, 'runtime_summary': self._build_runtime_summary(runtime), 'dispatch': updated, 'error': str(exc)}

    def cancel_dispatch(
        self,
        gw,
        *,
        dispatch_id: str,
        actor: str,
        reason: str = '',
        user_role: str = 'operator',
        user_key: str = '',
        session_id: str = 'system',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        detail = self.get_dispatch(gw, dispatch_id=dispatch_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if not detail.get('ok'):
            return detail
        dispatch = dict(detail.get('dispatch') or {})
        runtime = dict(detail.get('runtime') or {})
        scope = self._normalize_scope(
            tenant_id=tenant_id or dispatch.get('tenant_id') or runtime.get('tenant_id'),
            workspace_id=workspace_id or dispatch.get('workspace_id') or runtime.get('workspace_id'),
            environment=environment or dispatch.get('environment') or runtime.get('environment'),
        )
        dispatch_policy = self._dispatch_policy(runtime)
        if not bool(dispatch_policy.get('allow_cancel', True)):
            raise PermissionError(f"runtime '{runtime.get('runtime_id')}' does not allow operator cancellation")
        current = str(dispatch.get('canonical_status') or self._canonical_dispatch_status(str(dispatch.get('status') or ''), dict(dispatch.get('response') or {}))).strip().lower()
        if self._is_terminal_canonical_status(current):
            return {'ok': False, 'error': 'dispatch_not_cancellable', 'dispatch': dispatch, 'runtime': runtime, 'runtime_summary': self._build_runtime_summary(runtime)}
        response_payload = dict(dispatch.get('response') or {})
        lifecycle = dict(response_payload.get('lifecycle') or {})
        remote = {'attempted': False}
        if str(runtime.get('transport') or '').strip().lower() not in {'simulated'}:
            target_url = self._operation_url(runtime, operation='cancel', dispatch_id=dispatch_id)
            remote = {'attempted': True, 'target_url': target_url, 'accepted': False}
            try:
                headers = {'Content-Type': 'application/json'}
                secret_ref = str(runtime.get('auth_secret_ref') or '').strip()
                if secret_ref:
                    broker = getattr(gw, 'secret_broker', None)
                    if broker is None:
                        raise SecretAccessDenied('secret broker not configured')
                    secret_value = broker.resolve(
                        secret_ref,
                        tool_name=self.TOOL_NAME,
                        user_role=str(user_role or 'operator'),
                        user_key=str(user_key or actor or ''),
                        session_id=str(session_id or 'system'),
                        tenant_id=scope['tenant_id'],
                        workspace_id=scope['workspace_id'],
                        environment=scope['environment'],
                        domain=self._runtime_domain(runtime),
                    )
                    headers['Authorization'] = f'Bearer {secret_value}'
                body = json.dumps({'dispatch_id': dispatch_id, 'reason': str(reason or '').strip(), 'requested_by': str(actor or 'system')}, ensure_ascii=False).encode('utf-8')
                req = urllib.request.Request(target_url, data=body, headers=headers, method='POST')
                with urllib.request.urlopen(req, timeout=float(dispatch_policy['timeout_s'])) as resp:  # nosec - controlled admin path
                    raw = resp.read().decode('utf-8', errors='replace')
                    parsed = json.loads(raw) if raw else {}
                    remote.update({'accepted': 200 <= int(getattr(resp, 'status', 200) or 200) < 300, 'status_code': int(getattr(resp, 'status', 200) or 200), 'response': self._safe_json(parsed)})
            except Exception as exc:
                remote.update({'accepted': False, 'error': str(exc)})
                if not bool(dispatch_policy.get('allow_cancel_local_fallback', True)):
                    raise
        lifecycle.update({
            'canonical_status': 'cancelled',
            'terminal': True,
            'legacy_status': 'cancelled',
            'cancelled_at': time.time(),
            'cancelled_by': str(actor or 'system'),
            'cancel_reason': str(reason or '').strip(),
        })
        response_payload['lifecycle'] = lifecycle
        response_payload['cancel'] = {
            'requested_by': str(actor or 'system'),
            'reason': str(reason or '').strip(),
            'session_id': str(session_id or 'system'),
            'remote': self._safe_json(remote),
        }
        response_payload = self._append_operator_action(response_payload, action='cancel', actor=actor, reason=reason, details={'dispatch_id': dispatch_id, 'remote': remote})
        updated = gw.audit.update_openclaw_dispatch(
            dispatch_id,
            status='cancelled',
            response_payload=response_payload,
            error_text=str(reason or dispatch.get('error_text') or ''),
            latency_ms=dispatch.get('latency_ms'),
            **scope,
        )
        gw.audit.log_event('system', 'broker', str(actor or 'system'), str(session_id or 'system'), {'action': 'openclaw_dispatch_cancelled', 'runtime_id': runtime.get('runtime_id'), 'dispatch_id': dispatch_id, 'reason': str(reason or '').strip(), 'remote_attempted': remote.get('attempted'), 'remote_accepted': remote.get('accepted')}, **scope)
        return {'ok': True, 'dispatch': self._canonical_dispatch_view(updated), 'runtime': runtime, 'runtime_summary': self._build_runtime_summary(runtime), 'operation': {'kind': 'cancel', 'remote': self._safe_json(remote)}}

    def retry_dispatch(
        self,
        gw,
        *,
        dispatch_id: str,
        actor: str,
        reason: str = '',
        payload_override: dict[str, Any] | None = None,
        action_override: str = '',
        agent_id_override: str = '',
        user_role: str = 'operator',
        user_key: str = '',
        session_id: str = 'system',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        detail = self.get_dispatch(gw, dispatch_id=dispatch_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if not detail.get('ok'):
            return detail
        original_dispatch = dict(detail.get('dispatch') or {})
        runtime = dict(detail.get('runtime') or {})
        current = str(original_dispatch.get('canonical_status') or self._canonical_dispatch_status(str(original_dispatch.get('status') or ''), dict(original_dispatch.get('response') or {}))).strip().lower()
        if current not in {'failed', 'cancelled', 'timed_out'}:
            return {'ok': False, 'error': 'dispatch_not_retryable', 'dispatch': original_dispatch, 'runtime': runtime, 'runtime_summary': self._build_runtime_summary(runtime)}
        dispatch_policy = self._dispatch_policy(runtime)
        retry_count = self._retry_count(original_dispatch)
        retry_limit = int(dispatch_policy.get('operator_retry_limit') or 0)
        if retry_count >= retry_limit:
            raise PermissionError(f"dispatch '{dispatch_id}' exceeded operator retry limit ({retry_limit})")
        original_request = dict(original_dispatch.get('request') or {})
        correlation = dict(original_request.get('correlation') or {})
        overrides = {
            'retry_of_dispatch_id': str(dispatch_id),
            'root_dispatch_id': self._root_dispatch_id(original_dispatch),
            'retry_count': retry_count + 1,
            'retry_requested_by': str(actor or 'system'),
            'retry_reason': str(reason or '').strip(),
        }
        result = self.dispatch(
            gw,
            runtime_id=str(runtime.get('runtime_id') or original_dispatch.get('runtime_id') or ''),
            actor=actor,
            action=str(action_override or original_request.get('action') or original_dispatch.get('action') or ''),
            payload=dict(payload_override) if payload_override is not None else dict(original_request.get('payload') or {}),
            agent_id=str(agent_id_override or original_request.get('agent_id') or original_dispatch.get('agent_id') or ''),
            user_role=user_role,
            user_key=user_key,
            session_id=str(session_id or correlation.get('openmiura_session_id') or 'system'),
            tenant_id=tenant_id or original_dispatch.get('tenant_id') or runtime.get('tenant_id'),
            workspace_id=workspace_id or original_dispatch.get('workspace_id') or runtime.get('workspace_id'),
            environment=environment or original_dispatch.get('environment') or runtime.get('environment'),
            dry_run=False,
            correlation_overrides=overrides,
        )
        if not result.get('ok'):
            return result
        original_response = self._append_operator_action(
            dict(original_dispatch.get('response') or {}),
            action='retry',
            actor=actor,
            reason=reason,
            details={'dispatch_id': dispatch_id, 'new_dispatch_id': (result.get('dispatch') or {}).get('dispatch_id')},
        )
        original_lifecycle = dict(original_response.get('lifecycle') or {})
        original_lifecycle['last_retry_dispatch_id'] = (result.get('dispatch') or {}).get('dispatch_id')
        original_lifecycle['last_retry_requested_at'] = time.time()
        original_response['lifecycle'] = original_lifecycle
        scope = self._normalize_scope(
            tenant_id=tenant_id or original_dispatch.get('tenant_id') or runtime.get('tenant_id'),
            workspace_id=workspace_id or original_dispatch.get('workspace_id') or runtime.get('workspace_id'),
            environment=environment or original_dispatch.get('environment') or runtime.get('environment'),
        )
        gw.audit.update_openclaw_dispatch(
            dispatch_id,
            status=str(original_dispatch.get('status') or ''),
            response_payload=original_response,
            error_text=str(original_dispatch.get('error_text') or ''),
            latency_ms=original_dispatch.get('latency_ms'),
            **scope,
        )
        gw.audit.log_event('system', 'broker', str(actor or 'system'), str(session_id or 'system'), {'action': 'openclaw_dispatch_retried', 'runtime_id': runtime.get('runtime_id'), 'dispatch_id': dispatch_id, 'new_dispatch_id': (result.get('dispatch') or {}).get('dispatch_id'), 'retry_count': retry_count + 1, 'reason': str(reason or '').strip()}, **scope)
        return {'ok': True, 'runtime': runtime, 'runtime_summary': self._build_runtime_summary(runtime), 'original_dispatch': self._canonical_dispatch_view(gw.audit.get_openclaw_dispatch(dispatch_id, **scope)), 'dispatch': result.get('dispatch'), 'request': result.get('request'), 'response': result.get('response'), 'operation': {'kind': 'retry', 'retry_count': retry_count + 1}}

    def reconcile_dispatch(
        self,
        gw,
        *,
        dispatch_id: str,
        actor: str,
        target_status: str,
        reason: str = '',
        user_role: str = 'operator',
        user_key: str = '',
        session_id: str = 'system',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        detail = self.get_dispatch(gw, dispatch_id=dispatch_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if not detail.get('ok'):
            return detail
        dispatch = dict(detail.get('dispatch') or {})
        runtime = dict(detail.get('runtime') or {})
        dispatch_policy = self._dispatch_policy(runtime)
        if not bool(dispatch_policy.get('allow_manual_close', True)) or not bool(dispatch_policy.get('allow_reconcile', True)):
            raise PermissionError(f"runtime '{runtime.get('runtime_id')}' does not allow operator reconcile/manual close")
        current = str(dispatch.get('canonical_status') or self._canonical_dispatch_status(str(dispatch.get('status') or ''), dict(dispatch.get('response') or {}))).strip().lower()
        if self._is_terminal_canonical_status(current):
            return {'ok': False, 'error': 'dispatch_already_terminal', 'dispatch': dispatch, 'runtime': runtime, 'runtime_summary': self._build_runtime_summary(runtime)}
        desired = str(target_status or '').strip().lower()
        if desired not in {'completed', 'failed', 'cancelled', 'timed_out'}:
            raise ValueError('target_status must be one of completed, failed, cancelled, timed_out')
        scope = self._normalize_scope(
            tenant_id=tenant_id or dispatch.get('tenant_id') or runtime.get('tenant_id'),
            workspace_id=workspace_id or dispatch.get('workspace_id') or runtime.get('workspace_id'),
            environment=environment or dispatch.get('environment') or runtime.get('environment'),
        )
        response_payload = dict(dispatch.get('response') or {})
        lifecycle = dict(response_payload.get('lifecycle') or {})
        lifecycle.update({
            'canonical_status': desired,
            'terminal': True,
            'legacy_status': 'error' if desired == 'failed' else desired,
            'reconciled_at': time.time(),
            'reconciled_by': str(actor or 'system'),
            'reconcile_reason': str(reason or '').strip(),
        })
        response_payload['lifecycle'] = lifecycle
        response_payload['manual_reconcile'] = {
            'target_status': desired,
            'previous_status': current,
            'actor': str(actor or 'system'),
            'reason': str(reason or '').strip(),
            'session_id': str(session_id or 'system'),
        }
        response_payload = self._append_operator_action(response_payload, action='reconcile', actor=actor, reason=reason, details={'dispatch_id': dispatch_id, 'target_status': desired, 'previous_status': current})
        storage_status = 'error' if desired == 'failed' else desired
        updated = gw.audit.update_openclaw_dispatch(
            dispatch_id,
            status=storage_status,
            response_payload=response_payload,
            error_text=str(reason or dispatch.get('error_text') or '') if desired in {'failed', 'timed_out', 'cancelled'} else str(dispatch.get('error_text') or ''),
            latency_ms=dispatch.get('latency_ms'),
            **scope,
        )
        gw.audit.log_event('system', 'broker', str(actor or 'system'), str(session_id or 'system'), {'action': 'openclaw_dispatch_reconciled', 'runtime_id': runtime.get('runtime_id'), 'dispatch_id': dispatch_id, 'target_status': desired, 'previous_status': current, 'reason': str(reason or '').strip()}, **scope)
        return {'ok': True, 'dispatch': self._canonical_dispatch_view(updated), 'runtime': runtime, 'runtime_summary': self._build_runtime_summary(runtime), 'operation': {'kind': 'reconcile', 'target_status': desired, 'previous_status': current}}
