"""service._dispatch_mixin"""
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


class _OpenClawAdapterServiceDispatchMixin:
    """Sub-mixin: dispatch."""

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
    def _root_dispatch_id(cls, dispatch: dict[str, Any] | None) -> str:
        dispatch = dict(dispatch or {})
        correlation = dict((dispatch.get('request') or {}).get('correlation') or {})
        return str(correlation.get('root_dispatch_id') or dispatch.get('dispatch_id') or '').strip()

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

