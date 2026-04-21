from __future__ import annotations

import json
from typing import Any

from openmiura.core.contracts import AdminGatewayLike


def payload_size(payload: Any) -> int:
    try:
        return len(json.dumps(payload, ensure_ascii=False))
    except Exception:
        return len(str(payload))


def enforce_scope_limits(gw: AdminGatewayLike, *, scope: dict[str, Any], max_documents_per_scope: int) -> None:
    count = int(
        gw.audit.count_canvas_documents(
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        )
        or 0
    )
    if count >= int(max_documents_per_scope):
        raise ValueError('canvas document scope limit exceeded')


def enforce_canvas_payload(*, payload: Any, max_payload_chars: int) -> None:
    if payload_size(payload) > int(max_payload_chars):
        raise ValueError('canvas payload exceeds max size')


def enforce_canvas_counts(
    gw: AdminGatewayLike,
    *,
    canvas_id: str,
    kind: str,
    tenant_id: str | None,
    workspace_id: str | None,
    environment: str | None,
    max_nodes_per_canvas: int,
    max_edges_per_canvas: int,
    max_views_per_canvas: int,
) -> None:
    if kind == 'node':
        current = int(
            gw.audit.count_canvas_nodes(
                canvas_id=canvas_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                environment=environment,
            )
            or 0
        )
        if current >= int(max_nodes_per_canvas):
            raise ValueError('canvas node limit exceeded')
    elif kind == 'edge':
        current = int(
            gw.audit.count_canvas_edges(
                canvas_id=canvas_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                environment=environment,
            )
            or 0
        )
        if current >= int(max_edges_per_canvas):
            raise ValueError('canvas edge limit exceeded')
    elif kind == 'view':
        current = int(
            gw.audit.count_canvas_views(
                canvas_id=canvas_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                environment=environment,
            )
            or 0
        )
        if current >= int(max_views_per_canvas):
            raise ValueError('canvas view limit exceeded')


def sanitize_scope(
    gw: AdminGatewayLike,
    *,
    tenant_id: str | None,
    workspace_id: str | None,
    environment: str | None,
) -> dict[str, Any]:
    tenancy = getattr(gw, 'tenancy', None)
    if tenancy is not None and hasattr(tenancy, 'normalize_scope'):
        try:
            return tenancy.normalize_scope(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                environment=environment,
            )
        except Exception:
            pass
    return {
        'tenant_id': tenant_id,
        'workspace_id': workspace_id,
        'environment': environment,
    }


def normalize_toggles(toggles: dict[str, Any] | None, *, defaults: dict[str, bool]) -> dict[str, bool]:
    normalized = dict(defaults)
    for key, value in dict(toggles or {}).items():
        if key in normalized:
            normalized[key] = bool(value)
    return normalized


def safe_call(obj: Any, method_name: str, default: Any, /, *args: Any, **kwargs: Any) -> Any:
    method = getattr(obj, method_name, None)
    if not callable(method):
        return default
    try:
        return method(*args, **kwargs)
    except Exception:
        return default


def redact_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(token in lowered for token in ('secret', 'token', 'password', 'value', 'credential')):
                redacted[key] = '***redacted***'
            else:
                redacted[key] = redact_sensitive(item)
        return redacted
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    return value


__all__ = [
    'payload_size',
    'enforce_scope_limits',
    'enforce_canvas_payload',
    'enforce_canvas_counts',
    'sanitize_scope',
    'normalize_toggles',
    'safe_call',
    'redact_sensitive',
]
