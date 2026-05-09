"""openmiura.application.canvas.service._helpers_mixin

Part of the canvas service split. Methods originally lived on
``openmiura.application.canvas.service.LiveCanvasService``; they
have been moved verbatim into this mixin so that no individual
file in the package exceeds the project's ``max 1,500 lines``
ceiling. The public class still inherits from this mixin and
exposes every method unchanged.
"""

from __future__ import annotations

import json
import time
import uuid
from collections import Counter
from typing import Any

from openmiura.application.canvas.helpers import (
    enforce_canvas_counts as canvas_enforce_counts,
    enforce_canvas_payload as canvas_enforce_payload,
    enforce_scope_limits as canvas_enforce_scope_limits,
    normalize_toggles as canvas_normalize_toggles,
    payload_size as canvas_payload_size,
    redact_sensitive as canvas_redact_sensitive,
    safe_call as canvas_safe_call,
    sanitize_scope as canvas_sanitize_scope,
)
from openmiura.application.packaging import PackagingHardeningService
from openmiura.core.contracts import AdminGatewayLike


class _LiveCanvasHelpersMixin:
    """Mixin: helpers methods on LiveCanvasService."""

    @staticmethod
    def _payload_size(payload: Any) -> int:
        return canvas_payload_size(payload)

    def _enforce_scope_limits(self, gw: AdminGatewayLike, *, scope: dict[str, Any]) -> None:
        canvas_enforce_scope_limits(gw, scope=scope, max_documents_per_scope=self.MAX_DOCUMENTS_PER_SCOPE)

    def _enforce_canvas_payload(self, *, payload: Any) -> None:
        canvas_enforce_payload(payload=payload, max_payload_chars=self.MAX_PAYLOAD_CHARS)

    def _enforce_canvas_counts(self, gw: AdminGatewayLike, *, canvas_id: str, kind: str, tenant_id: str | None, workspace_id: str | None, environment: str | None) -> None:
        canvas_enforce_counts(
            gw,
            canvas_id=canvas_id,
            kind=kind,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            max_nodes_per_canvas=self.MAX_NODES_PER_CANVAS,
            max_edges_per_canvas=self.MAX_EDGES_PER_CANVAS,
            max_views_per_canvas=self.MAX_VIEWS_PER_CANVAS,
        )

    def _sanitize_scope(
        self,
        gw: AdminGatewayLike,
        *,
        tenant_id: str | None,
        workspace_id: str | None,
        environment: str | None,
    ) -> dict[str, Any]:
        return canvas_sanitize_scope(
            gw,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def _normalize_toggles(self, toggles: dict[str, Any] | None) -> dict[str, bool]:
        return canvas_normalize_toggles(toggles, defaults=self._DEFAULT_TOGGLES)

    @staticmethod
    def _safe_call(obj: Any, method_name: str, default: Any, /, *args: Any, **kwargs: Any) -> Any:
        return canvas_safe_call(obj, method_name, default, *args, **kwargs)

    @staticmethod
    def _redact_sensitive(value: Any) -> Any:
        return canvas_redact_sensitive(value)

    @staticmethod
    def _prune_canvas_payload(value: Any) -> Any:
        if isinstance(value, dict):
            pruned: dict[str, Any] = {}
            for key, raw_item in value.items():
                item = LiveCanvasService._prune_canvas_payload(raw_item)
                if item in (None, '', [], {}):
                    continue
                if isinstance(item, (int, float)) and not isinstance(item, bool) and item == 0:
                    continue
                pruned[str(key)] = item
            return pruned
        if isinstance(value, list):
            items = [LiveCanvasService._prune_canvas_payload(item) for item in value]
            return [item for item in items if item not in (None, '', [], {})]
        return value

    @staticmethod
    def _trace_matches(item: dict[str, Any], refs: dict[str, list[str]]) -> bool:
        trace_id = str(item.get('trace_id') or '')
        session_id = str(item.get('session_id') or '')
        tools_used = {str(tool.get('tool_name') or tool.get('name') or tool or '').strip() for tool in list(item.get('tools_used') or []) if str(tool)}
        policy_names = {str(pol.get('name') or '').strip() for pol in list(item.get('policies') or []) if isinstance(pol, dict)}
        if refs.get('trace_ids') and trace_id in set(refs.get('trace_ids') or []):
            return True
        workflow_sessions = {f"workflow:{workflow_id}" for workflow_id in list(refs.get('workflow_ids') or [])}
        if refs.get('session_ids') and session_id in set(refs.get('session_ids') or []):
            return True
        if workflow_sessions and session_id in workflow_sessions:
            return True
        if refs.get('tool_names') and tools_used.intersection(set(refs.get('tool_names') or [])):
            return True
        if refs.get('policy_names') and policy_names.intersection(set(refs.get('policy_names') or [])):
            return True
        if any(list(refs.get(key) or []) for key in ('trace_ids', 'workflow_ids', 'session_ids', 'tool_names', 'policy_names')):
            return False
        return True

    @staticmethod
    def _approval_matches(item: dict[str, Any], refs: dict[str, list[str]]) -> bool:
        approval_id = str(item.get('approval_id') or '')
        workflow_id = str(item.get('workflow_id') or '')
        if refs.get('approval_ids') and approval_id in set(refs.get('approval_ids') or []):
            return True
        if refs.get('workflow_ids') and workflow_id in set(refs.get('workflow_ids') or []):
            return True
        if any(list(refs.get(key) or []) for key in ('approval_ids', 'workflow_ids')):
            return False
        return True

    @staticmethod
    def _failure_matches(item: dict[str, Any], refs: dict[str, list[str]]) -> bool:
        kind = str(item.get('kind') or '')
        item_id = str(item.get('id') or '')
        label = str(item.get('label') or '')
        if kind == 'workflow' and refs.get('workflow_ids'):
            return item_id in set(refs.get('workflow_ids') or []) or label in set(refs.get('workflow_ids') or [])
        if kind == 'trace' and refs.get('trace_ids'):
            return item_id in set(refs.get('trace_ids') or [])
        if kind == 'tool_call' and refs.get('tool_names'):
            return label in set(refs.get('tool_names') or [])
        if any(list(refs.get(key) or []) for key in ('workflow_ids', 'trace_ids', 'tool_names')):
            return False
        return True

    @staticmethod
    def _secret_usage_matches(item: dict[str, Any], refs: dict[str, list[str]]) -> bool:
        ref = str(item.get('ref') or '')
        tools = {str(tool).strip() for tool in list(item.get('tools') or [])}
        if refs.get('secret_refs') and ref in set(refs.get('secret_refs') or []):
            return True
        if refs.get('tool_names') and tools.intersection(set(refs.get('tool_names') or [])):
            return True
        if any(list(refs.get(key) or []) for key in ('secret_refs', 'tool_names')):
            return False
        return True

    @staticmethod
    def _secret_catalog_matches(item: dict[str, Any], refs: dict[str, list[str]]) -> bool:
        ref = str(item.get('ref') or '')
        if refs.get('secret_refs') and ref in set(refs.get('secret_refs') or []):
            return True
        if any(list(refs.get(key) or []) for key in ('secret_refs',)):
            return False
        return True

    @staticmethod
    def _cost_matches(item: dict[str, Any], refs: dict[str, list[str]]) -> bool:
        workflows = {str(value).strip() for value in list(item.get('workflows') or [])}
        group = str(item.get('group') or '').strip()
        if refs.get('workflow_ids') and (workflows.intersection(set(refs.get('workflow_ids') or [])) or group in set(refs.get('workflow_ids') or [])):
            return True
        if any(list(refs.get(key) or []) for key in ('workflow_ids',)):
            return False
        return True

    @staticmethod
    def _budget_matches(item: dict[str, Any], refs: dict[str, list[str]]) -> bool:
        workflow_name = str(item.get('workflow_name') or '').strip()
        if refs.get('workflow_ids') and workflow_name in set(refs.get('workflow_ids') or []):
            return True
        if any(list(refs.get(key) or []) for key in ('workflow_ids',)):
            return False
        return True

    @staticmethod
    def _compact_trace(item: dict[str, Any]) -> dict[str, Any]:
        return {
            'trace_id': item.get('trace_id'),
            'session_id': item.get('session_id'),
            'agent_id': item.get('agent_id'),
            'status': item.get('status'),
            'provider': item.get('provider'),
            'model': item.get('model'),
            'latency_ms': float(item.get('latency_ms') or 0.0),
            'estimated_cost': float(item.get('estimated_cost') or 0.0),
            'tools_used': item.get('tools_used') or [],
            'policies': item.get('policies') or [],
            'ts': float(item.get('ts') or 0.0),
        }

    @staticmethod
    def _compact_approval(item: dict[str, Any]) -> dict[str, Any]:
        return {
            'approval_id': item.get('approval_id'),
            'workflow_id': item.get('workflow_id'),
            'step_id': item.get('step_id'),
            'requested_role': item.get('requested_role'),
            'requested_by': item.get('requested_by'),
            'status': item.get('status'),
            'reason': item.get('reason') or '',
            'updated_at': float(item.get('updated_at') or item.get('created_at') or 0.0),
        }

    @staticmethod
    def _sanitize_secret_usage(item: dict[str, Any]) -> dict[str, Any]:
        return {
            'ref': item.get('ref'),
            'count': int(item.get('count') or 0),
            'last_used_at': item.get('last_used_at'),
            'last_used_tool': item.get('last_used_tool'),
            'last_used_domain': item.get('last_used_domain'),
            'tools': list(item.get('tools') or []),
            'domains': list(item.get('domains') or []),
            'tenants': list(item.get('tenants') or []),
            'workspaces': list(item.get('workspaces') or []),
            'environments': list(item.get('environments') or []),
        }

    def _sanitize_secret_catalog(self, item: dict[str, Any]) -> dict[str, Any]:
        return self._redact_sensitive({
            'ref': item.get('ref'),
            'configured': bool(item.get('configured')),
            'usage_count': int(item.get('usage_count') or 0),
            'last_used_at': item.get('last_used_at'),
            'last_used_tool': item.get('last_used_tool'),
            'rotation': item.get('rotation') or {},
            'visibility': item.get('visibility') or {},
            'allowed_tenants': item.get('allowed_tenants') or [],
            'allowed_workspaces': item.get('allowed_workspaces') or [],
            'allowed_environments': item.get('allowed_environments') or [],
            'metadata': item.get('metadata') or {},
        })

    @staticmethod
    def _compact_cost_item(item: dict[str, Any]) -> dict[str, Any]:
        return {
            'group': item.get('group'),
            'run_count': int(item.get('run_count') or 0),
            'total_spend': float(item.get('total_spend') or 0.0),
            'average_spend_per_run': float(item.get('average_spend_per_run') or 0.0),
            'total_cases': int(item.get('total_cases') or 0),
            'latest_run_id': item.get('latest_run_id'),
            'latest_started_at': item.get('latest_started_at'),
            'workflows': list(item.get('workflows') or []),
            'agents': list(item.get('agents') or []),
        }

    @staticmethod
    def _compact_budget_item(item: dict[str, Any]) -> dict[str, Any]:
        return {
            'budget_name': item.get('budget_name'),
            'status': item.get('status'),
            'workflow_name': item.get('workflow_name'),
            'current_spend': float(item.get('current_spend') or 0.0),
            'budget_amount': float(item.get('budget_amount') or 0.0),
            'utilization': float(item.get('utilization') or 0.0),
            'window_hours': int(item.get('window_hours') or 0),
        }

