from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from openmiura.core.config import SecretRefSettings, SecretsSettings
from openmiura.core.policy import PolicyEngine


class SecretBrokerError(RuntimeError):
    """Base secret broker error."""


class SecretNotConfigured(SecretBrokerError):
    """Raised when a secret reference exists but has no value."""


class SecretAccessDenied(SecretBrokerError):
    """Raised when a caller is not authorized to resolve a secret reference."""


@dataclass(frozen=True)
class SecretResolution:
    ref: str
    value: str
    tool_name: str
    user_role: str
    tenant_id: str | None = None
    workspace_id: str | None = None
    environment: str | None = None
    domain: str | None = None


class SecretBroker:
    def __init__(self, *, settings: SecretsSettings | None = None, audit: Any | None = None, policy: PolicyEngine | None = None) -> None:
        self.settings = settings or SecretsSettings(enabled=False)
        self.audit = audit
        self.policy = policy

    def is_enabled(self) -> bool:
        return bool(getattr(self.settings, 'enabled', False))

    def list_refs(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for ref_name, ref in sorted((self.settings.refs or {}).items()):
            out.append(
                {
                    'ref': ref_name,
                    'configured': bool(ref.value),
                    'description': ref.description,
                    'allowed_tools': list(ref.allowed_tools),
                    'allowed_roles': list(ref.allowed_roles),
                    'allowed_tenants': list(ref.allowed_tenants),
                    'allowed_workspaces': list(ref.allowed_workspaces),
                    'allowed_environments': list(ref.allowed_environments),
                    'allowed_domains': list(ref.allowed_domains),
                    'metadata': dict(ref.metadata or {}),
                }
            )
        return out

    def explain_access(
        self,
        ref: str,
        *,
        tool_name: str,
        user_role: str = 'user',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        domain: str | None = None,
    ) -> dict[str, Any]:
        response: dict[str, Any] = {
            'ok': True,
            'enabled': self.is_enabled(),
            'ref': str(ref or '').strip(),
            'tool_name': str(tool_name or '').strip(),
            'user_role': str(user_role or 'user').strip().lower() or 'user',
            'tenant_id': tenant_id,
            'workspace_id': workspace_id,
            'environment': environment,
            'domain': self._normalize_domain(domain) or None,
            'configured': False,
            'allowed': False,
            'reason': '',
            'policy': None,
            'metadata': {},
        }
        if not self.is_enabled():
            response['reason'] = 'secret broker disabled'
            return response
        try:
            spec = self._get_ref(ref)
        except SecretBrokerError as exc:
            response['reason'] = str(exc)
            return response
        response['configured'] = bool(spec.value)
        response['metadata'] = {
            'description': spec.description,
            'allowed_tools': list(spec.allowed_tools),
            'denied_tools': list(spec.denied_tools),
            'allowed_roles': list(spec.allowed_roles),
            'denied_roles': list(spec.denied_roles),
            'allowed_tenants': list(spec.allowed_tenants),
            'allowed_workspaces': list(spec.allowed_workspaces),
            'allowed_environments': list(spec.allowed_environments),
            'allowed_domains': list(spec.allowed_domains),
            'custom': dict(spec.metadata or {}),
        }
        try:
            self._authorize(
                spec,
                tool_name=tool_name,
                user_role=user_role,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                environment=environment,
                domain=domain,
            )
        except SecretBrokerError as exc:
            response['reason'] = str(exc)
            return response
        if self.policy is not None:
            decision = self.policy.check_secret_access(
                ref,
                tool_name=tool_name,
                user_role=user_role,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                environment=environment,
                domain=domain,
            )
            response['policy'] = decision.to_dict() if hasattr(decision, 'to_dict') else getattr(decision, '__dict__', {})
            if not bool(getattr(decision, 'allowed', True)):
                response['reason'] = getattr(decision, 'reason', '') or f"Secret ref '{ref}' denied by policy"
                return response
        response['allowed'] = True
        response['reason'] = 'secret access allowed'
        return response

    def resolve(
        self,
        ref: str,
        *,
        tool_name: str,
        user_role: str = 'user',
        user_key: str = '',
        session_id: str = 'system',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        domain: str | None = None,
    ) -> str:
        if not self.is_enabled():
            raise SecretAccessDenied('Secret broker is disabled')
        spec = self._get_ref(ref)
        self._authorize(
            spec,
            tool_name=tool_name,
            user_role=user_role,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            domain=domain,
        )
        if self.policy is not None:
            decision = self.policy.check_secret_access(
                ref,
                tool_name=tool_name,
                user_role=user_role,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                environment=environment,
                domain=domain,
            )
            if not bool(getattr(decision, 'allowed', True)):
                raise SecretAccessDenied(getattr(decision, 'reason', '') or f"Secret ref '{ref}' denied by policy")
        value = str(spec.value or '')
        if not value:
            raise SecretNotConfigured(f"Secret ref '{ref}' is not configured")
        self._audit_resolution(
            ref=ref,
            tool_name=tool_name,
            user_role=user_role,
            user_key=user_key,
            session_id=session_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            domain=domain,
        )
        return value

    def redact_text(self, text: str | None) -> str:
        raw = str(text or '')
        if not raw or not bool(getattr(self.settings, 'redact_logs', True)):
            return raw
        out = raw
        for ref_name, spec in sorted((self.settings.refs or {}).items(), key=lambda item: len(str(item[1].value or '')), reverse=True):
            secret = str(spec.value or '')
            if len(secret) < 3:
                continue
            out = out.replace(secret, f'[secret:redacted:{ref_name}]')
        return out

    def redact_value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.redact_text(value)
        if isinstance(value, dict):
            return {k: self.redact_value(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.redact_value(v) for v in value]
        if isinstance(value, tuple):
            return tuple(self.redact_value(v) for v in value)
        return value

    def _get_ref(self, ref: str) -> SecretRefSettings:
        ref_name = str(ref or '').strip()
        spec = (self.settings.refs or {}).get(ref_name)
        if spec is None:
            raise SecretAccessDenied(f"Unknown secret ref '{ref_name}'")
        return spec

    def _authorize(
        self,
        spec: SecretRefSettings,
        *,
        tool_name: str,
        user_role: str,
        tenant_id: str | None,
        workspace_id: str | None,
        environment: str | None,
        domain: str | None,
    ) -> None:
        role = str(user_role or 'user').strip().lower() or 'user'
        tool = str(tool_name or '').strip()
        if spec.denied_tools and tool in set(spec.denied_tools):
            raise SecretAccessDenied(f"Secret ref '{spec.ref}' denied for tool '{tool}'")
        if spec.allowed_tools and tool not in set(spec.allowed_tools):
            raise SecretAccessDenied(f"Secret ref '{spec.ref}' not allowed for tool '{tool}'")
        if spec.denied_roles and role in set(spec.denied_roles):
            raise SecretAccessDenied(f"Secret ref '{spec.ref}' denied for role '{role}'")
        if spec.allowed_roles and role not in set(spec.allowed_roles):
            raise SecretAccessDenied(f"Secret ref '{spec.ref}' not allowed for role '{role}'")
        self._check_scope('tenant', tenant_id, spec.allowed_tenants, spec.ref)
        self._check_scope('workspace', workspace_id, spec.allowed_workspaces, spec.ref)
        self._check_scope('environment', environment, spec.allowed_environments, spec.ref)
        if spec.allowed_domains:
            host = self._normalize_domain(domain)
            if not host:
                raise SecretAccessDenied(f"Secret ref '{spec.ref}' requires an allowed domain")
            allowed = False
            for item in spec.allowed_domains:
                rule = self._normalize_domain(item)
                if not rule:
                    continue
                if host == rule or host.endswith('.' + rule):
                    allowed = True
                    break
            if not allowed:
                raise SecretAccessDenied(f"Secret ref '{spec.ref}' not allowed for domain '{host}'")

    def _check_scope(self, label: str, actual: str | None, allowed: list[str], ref: str) -> None:
        if not allowed:
            return
        candidate = str(actual or '').strip()
        if candidate and candidate in set(allowed):
            return
        raise SecretAccessDenied(f"Secret ref '{ref}' not allowed for {label} '{candidate or '<none>'}'")

    def _normalize_domain(self, value: str | None) -> str:
        raw = str(value or '').strip().lower()
        if not raw:
            return ''
        if '://' in raw:
            return (urlparse(raw).hostname or '').strip().lower()
        return raw.split('/')[0].split(':')[0].strip().lower()

    def _audit_resolution(
        self,
        *,
        ref: str,
        tool_name: str,
        user_role: str,
        user_key: str,
        session_id: str,
        tenant_id: str | None,
        workspace_id: str | None,
        environment: str | None,
        domain: str | None,
    ) -> None:
        if self.audit is None:
            return
        try:
            self.audit.log_event(
                direction='system',
                channel='security',
                user_id=str(user_key or 'system'),
                session_id=str(session_id or 'system'),
                payload={
                    'event': 'secret_resolved',
                    'ref': ref,
                    'tool_name': tool_name,
                    'user_role': str(user_role or 'user'),
                    'domain': self._normalize_domain(domain) or None,
                },
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                environment=environment,
            )
        except Exception:
            pass
