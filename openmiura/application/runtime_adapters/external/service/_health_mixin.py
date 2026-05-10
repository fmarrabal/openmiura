"""service._health_mixin"""
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


class _OpenClawAdapterServiceHealthMixin:
    """Sub-mixin: health."""

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

