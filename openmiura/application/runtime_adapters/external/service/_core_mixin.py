"""service._core_mixin"""
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


class _OpenClawAdapterServiceCoreMixin:
    """Sub-mixin: core."""

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
    def _allowed_actions(cls, runtime: dict[str, Any]) -> set[str]:
        metadata = cls._runtime_metadata(runtime)
        explicit = metadata.get('allowed_actions')
        if explicit is None:
            explicit = runtime.get('capabilities') or []
        return {str(item).strip().lower() for item in list(explicit or []) if str(item).strip()}

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
    def _is_terminal_canonical_status(cls, canonical_status: str) -> bool:
        return str(canonical_status or '').strip().lower() in cls.TERMINAL_CANONICAL_STATUSES

    @staticmethod
    def _should_retry_http_error(exc: urllib.error.HTTPError) -> bool:
        try:
            code = int(getattr(exc, 'code', 0) or 0)
        except Exception:
            code = 0
        return code == 429 or code >= 500

