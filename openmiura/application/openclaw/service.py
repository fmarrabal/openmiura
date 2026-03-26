from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from openmiura.core.secrets import SecretAccessDenied, SecretBrokerError, SecretNotConfigured


class OpenClawAdapterService:
    """Governed adapter for delegating execution to external OpenClaw runtimes."""

    TOOL_NAME = 'openclaw_adapter'

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
    def _runtime_domain(runtime: dict[str, Any]) -> str | None:
        try:
            parsed = urllib.parse.urlparse(str(runtime.get('base_url') or ''))
        except Exception:
            return None
        return parsed.netloc or None

    @staticmethod
    def _dispatch_url(runtime: dict[str, Any]) -> str:
        base = str(runtime.get('base_url') or '').rstrip('/')
        if str(runtime.get('transport') or '').strip().lower() == 'simulated':
            return base or 'simulated://openclaw/dispatch'
        return f"{base}/runtime/dispatch"

    @staticmethod
    def _health_url(runtime: dict[str, Any]) -> str:
        base = str(runtime.get('base_url') or '').rstrip('/')
        if str(runtime.get('transport') or '').strip().lower() == 'simulated':
            return (base or 'simulated://openclaw').rstrip('/') + '/health'
        return f"{base}/runtime/health"

    @staticmethod
    def _safe_json(value: Any) -> Any:
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        if isinstance(value, dict):
            return {str(k): OpenClawAdapterService._safe_json(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [OpenClawAdapterService._safe_json(v) for v in value]
        return str(value)

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
        runtime = gw.audit.upsert_openclaw_runtime(
            runtime_id=runtime_id,
            name=cleaned_name,
            base_url=cleaned_url,
            transport=mode,
            auth_secret_ref=str(auth_secret_ref or '').strip(),
            capabilities=[str(item).strip() for item in (capabilities or []) if str(item).strip()],
            allowed_agents=[str(item).strip() for item in (allowed_agents or []) if str(item).strip()],
            metadata=dict(metadata or {}),
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
            },
            **scope,
        )
        return {'ok': True, 'runtime': runtime}

    def list_runtimes(self, gw, *, limit: int = 100, status: str | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any]:
        items = gw.audit.list_openclaw_runtimes(limit=limit, status=status, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        return {'ok': True, 'items': items, 'summary': {'count': len(items), 'status': status}}

    def get_runtime(self, gw, *, runtime_id: str, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any]:
        runtime = gw.audit.get_openclaw_runtime(runtime_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if runtime is None:
            return {'ok': False, 'error': 'runtime_not_found', 'runtime_id': runtime_id}
        dispatches = gw.audit.list_openclaw_dispatches(runtime_id=runtime_id, limit=20, tenant_id=tenant_id or runtime.get('tenant_id'), workspace_id=workspace_id or runtime.get('workspace_id'), environment=environment or runtime.get('environment'))
        health = {
            'status': str(runtime.get('last_health_status') or 'unknown'),
            'checked_at': runtime.get('last_health_at'),
            'stale': False,
        }
        try:
            checked_at = float(runtime.get('last_health_at') or 0.0)
        except Exception:
            checked_at = 0.0
        if checked_at > 0.0:
            health['stale'] = (time.time() - checked_at) > 300.0
        else:
            health['stale'] = True
        return {'ok': True, 'runtime': runtime, 'dispatches': dispatches, 'health': health}

    def list_dispatches(self, gw, *, runtime_id: str | None = None, action: str | None = None, status: str | None = None, limit: int = 100, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any]:
        items = gw.audit.list_openclaw_dispatches(runtime_id=runtime_id, action=action, status=status, limit=limit, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        return {'ok': True, 'items': items, 'summary': {'count': len(items), 'status': status, 'action': action}}

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
        try:
            if mode == 'simulated':
                status = 'healthy'
                detail = {'probe': probe, 'mode': 'simulated', 'target_url': self._health_url(runtime), 'headers': redacted_headers, 'accepted': True}
            else:
                target_url = self._health_url(runtime)
                headers = {}
                if secret_value:
                    headers['Authorization'] = f'Bearer {secret_value}'
                req = urllib.request.Request(target_url, headers=headers, method='GET')
                with urllib.request.urlopen(req, timeout=10.0) as resp:  # nosec - controlled admin path
                    raw = resp.read().decode('utf-8', errors='replace')
                    try:
                        parsed = json.loads(raw) if raw else {}
                    except Exception:
                        parsed = {'raw': raw}
                    accepted = 200 <= int(getattr(resp, 'status', 200) or 200) < 300
                    status = 'healthy' if accepted else 'degraded'
                    detail = {'probe': probe, 'mode': 'http', 'target_url': target_url, 'status_code': int(getattr(resp, 'status', 200) or 200), 'headers': redacted_headers, 'response': self._safe_json(parsed), 'accepted': accepted}
        except urllib.error.HTTPError as exc:
            body = exc.read().decode('utf-8', errors='replace') if hasattr(exc, 'read') else ''
            status = 'unhealthy'
            detail = {'probe': probe, 'mode': mode, 'target_url': self._health_url(runtime), 'status_code': int(exc.code), 'body': body[:4000], 'headers': redacted_headers, 'accepted': False}
        except Exception as exc:
            status = 'unhealthy'
            detail = {'probe': probe, 'mode': mode, 'target_url': self._health_url(runtime), 'error': str(exc), 'headers': redacted_headers, 'accepted': False}
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
        gw.audit.log_event('system', 'broker', str(actor or 'system'), str(session_id or 'system'), {'action': 'openclaw_runtime_health_checked', 'runtime_id': runtime_id, 'probe': probe, 'health_status': status, 'latency_ms': latency_ms}, **scope)
        return {'ok': status != 'unhealthy', 'runtime': updated_runtime, 'health': {'status': status, 'checked_at': checked_at, 'latency_ms': latency_ms, 'detail': detail}}

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
    ) -> dict[str, Any]:
        runtime = gw.audit.get_openclaw_runtime(runtime_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if runtime is None:
            return {'ok': False, 'error': 'runtime_not_found', 'runtime_id': runtime_id}
        requested_action = str(action or '').strip().lower()
        if not requested_action:
            raise ValueError('action is required')
        requested_agent = str(agent_id or '').strip()
        allowed_agents = set(runtime.get('allowed_agents') or [])
        if requested_agent and allowed_agents and requested_agent not in allowed_agents:
            raise PermissionError(f"agent '{requested_agent}' not allowed for runtime '{runtime_id}'")
        scope = self._normalize_scope(
            tenant_id=tenant_id or runtime.get('tenant_id'),
            workspace_id=workspace_id or runtime.get('workspace_id'),
            environment=environment or runtime.get('environment'),
        )
        request_payload = {
            'runtime_id': runtime_id,
            'runtime_name': runtime.get('name'),
            'action': requested_action,
            'agent_id': requested_agent,
            'payload': self._safe_json(payload or {}),
            'requested_by': str(actor or 'system'),
            'scope': scope,
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
            response_payload={},
            secret_ref=secret_ref,
            created_by=str(actor or 'system'),
            **scope,
        )
        gw.audit.log_event('system', 'broker', str(actor or 'system'), str(session_id or 'system'), {'action': 'openclaw_dispatch_requested', 'runtime_id': runtime_id, 'dispatch_id': dispatch_row.get('dispatch_id'), 'dispatch_action': requested_action, 'agent_id': requested_agent, 'dry_run': bool(dry_run)}, **scope)
        started_at = time.time()
        try:
            mode = str(runtime.get('transport') or 'http').strip().lower() or 'http'
            response_payload: dict[str, Any]
            status = 'ok'
            if dry_run or mode == 'simulated':
                response_payload = {
                    'accepted': True,
                    'mode': 'dry-run' if dry_run else 'simulated',
                    'target_url': self._dispatch_url(runtime),
                    'headers': redacted_headers,
                    'request': request_payload,
                }
                if mode == 'simulated' and not dry_run:
                    response_payload['result'] = {'runtime': 'openclaw', 'status': 'accepted', 'capabilities': runtime.get('capabilities') or []}
            else:
                target_url = self._dispatch_url(runtime)
                body = json.dumps(request_payload, ensure_ascii=False).encode('utf-8')
                headers = {'Content-Type': 'application/json'}
                if secret_value:
                    headers['Authorization'] = f'Bearer {secret_value}'
                req = urllib.request.Request(target_url, data=body, headers=headers, method='POST')
                with urllib.request.urlopen(req, timeout=15.0) as resp:  # nosec - controlled admin path
                    raw = resp.read().decode('utf-8', errors='replace')
                    try:
                        parsed = json.loads(raw) if raw else {}
                    except Exception:
                        parsed = {'raw': raw}
                    response_payload = {
                        'accepted': 200 <= int(getattr(resp, 'status', 200) or 200) < 300,
                        'mode': 'http',
                        'target_url': target_url,
                        'status_code': int(getattr(resp, 'status', 200) or 200),
                        'headers': redacted_headers,
                        'response': self._safe_json(parsed),
                    }
            latency_ms = max(0.0, (time.time() - started_at) * 1000.0)
            updated = gw.audit.update_openclaw_dispatch(
                dispatch_row['dispatch_id'],
                status=status,
                response_payload=response_payload,
                error_text='',
                latency_ms=latency_ms,
                **scope,
            )
            gw.audit.log_event('system', 'broker', str(actor or 'system'), str(session_id or 'system'), {'action': 'openclaw_dispatch_completed', 'runtime_id': runtime_id, 'dispatch_id': dispatch_row.get('dispatch_id'), 'dispatch_action': requested_action, 'latency_ms': latency_ms, 'status': status}, **scope)
            return {'ok': True, 'runtime': runtime, 'dispatch': updated, 'request': {'target_url': self._dispatch_url(runtime), 'headers': redacted_headers, 'body': request_payload}, 'response': response_payload}
        except (SecretBrokerError, PermissionError, ValueError):
            raise
        except urllib.error.HTTPError as exc:
            latency_ms = max(0.0, (time.time() - started_at) * 1000.0)
            body = exc.read().decode('utf-8', errors='replace') if hasattr(exc, 'read') else ''
            updated = gw.audit.update_openclaw_dispatch(dispatch_row['dispatch_id'], status='error', response_payload={'status_code': int(exc.code), 'body': body[:4000]}, error_text=str(exc), latency_ms=latency_ms, **scope)
            gw.audit.log_event('system', 'broker', str(actor or 'system'), str(session_id or 'system'), {'action': 'openclaw_dispatch_failed', 'runtime_id': runtime_id, 'dispatch_id': dispatch_row.get('dispatch_id'), 'dispatch_action': requested_action, 'latency_ms': latency_ms, 'error': str(exc)}, **scope)
            return {'ok': False, 'runtime': runtime, 'dispatch': updated, 'error': str(exc)}
        except Exception as exc:
            latency_ms = max(0.0, (time.time() - started_at) * 1000.0)
            updated = gw.audit.update_openclaw_dispatch(dispatch_row['dispatch_id'], status='error', response_payload={}, error_text=str(exc), latency_ms=latency_ms, **scope)
            gw.audit.log_event('system', 'broker', str(actor or 'system'), str(session_id or 'system'), {'action': 'openclaw_dispatch_failed', 'runtime_id': runtime_id, 'dispatch_id': dispatch_row.get('dispatch_id'), 'dispatch_action': requested_action, 'latency_ms': latency_ms, 'error': str(exc)}, **scope)
            return {'ok': False, 'runtime': runtime, 'dispatch': updated, 'error': str(exc)}
