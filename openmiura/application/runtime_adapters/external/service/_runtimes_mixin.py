"""service._runtimes_mixin"""
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


class _OpenClawAdapterServiceRuntimesMixin:
    """Sub-mixin: runtimes."""

    @classmethod
    def _normalize_runtime_class(cls, runtime_class: str | None, *, transport: str = 'http') -> str:
        raw = str(runtime_class or '').strip().lower()
        if not raw:
            raw = 'simulated_lab' if str(transport or '').strip().lower() == 'simulated' else 'generic_async_worker'
        return cls.RUNTIME_CLASS_ALIASES.get(raw, raw)

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

