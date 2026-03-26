from __future__ import annotations

from collections import Counter
import json
import uuid
from typing import Any

from openmiura.application.packaging import PackagingHardeningService

from openmiura.application.costs import CostGovernanceService
from openmiura.application.operator import OperatorConsoleService
from openmiura.application.openclaw import OpenClawAdapterService
from openmiura.application.secrets import SecretGovernanceService
from openmiura.core.contracts import AdminGatewayLike


class LiveCanvasService:
    _CANVAS_LIMITS = PackagingHardeningService.DEFAULT_HARDENING['canvas']
    MAX_DOCUMENTS_PER_SCOPE = int(_CANVAS_LIMITS['max_documents_per_scope'])
    MAX_NODES_PER_CANVAS = int(_CANVAS_LIMITS['max_nodes_per_canvas'])
    MAX_EDGES_PER_CANVAS = int(_CANVAS_LIMITS['max_edges_per_canvas'])
    MAX_VIEWS_PER_CANVAS = int(_CANVAS_LIMITS['max_views_per_canvas'])
    MAX_PAYLOAD_CHARS = int(_CANVAS_LIMITS['max_payload_chars'])
    MAX_COMMENT_CHARS = int(_CANVAS_LIMITS['max_comment_chars'])
    MAX_SNAPSHOT_BYTES = int(_CANVAS_LIMITS['max_snapshot_bytes'])

    _DEFAULT_TOGGLES = {
        'policy': True,
        'cost': True,
        'traces': True,
        'failures': True,
        'approvals': True,
        'secrets': True,
    }

    def __init__(
        self,
        *,
        cost_governance_service: CostGovernanceService | None = None,
        operator_console_service: OperatorConsoleService | None = None,
        secret_governance_service: SecretGovernanceService | None = None,
        openclaw_adapter_service: OpenClawAdapterService | None = None,
    ) -> None:
        self.cost_governance_service = cost_governance_service or CostGovernanceService()
        self.operator_console_service = operator_console_service or OperatorConsoleService()
        self.secret_governance_service = secret_governance_service or SecretGovernanceService()
        self.openclaw_adapter_service = openclaw_adapter_service or OpenClawAdapterService()

    @staticmethod
    def _payload_size(payload: Any) -> int:
        try:
            return len(json.dumps(payload, ensure_ascii=False))
        except Exception:
            return len(str(payload))

    def _enforce_scope_limits(self, gw: AdminGatewayLike, *, scope: dict[str, Any]) -> None:
        count = int(gw.audit.count_canvas_documents(tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')) or 0)
        if count >= self.MAX_DOCUMENTS_PER_SCOPE:
            raise ValueError('canvas document scope limit exceeded')

    def _enforce_canvas_payload(self, *, payload: Any) -> None:
        if self._payload_size(payload) > self.MAX_PAYLOAD_CHARS:
            raise ValueError('canvas payload exceeds max size')

    def _enforce_canvas_counts(self, gw: AdminGatewayLike, *, canvas_id: str, kind: str, tenant_id: str | None, workspace_id: str | None, environment: str | None) -> None:
        if kind == 'node':
            current = int(gw.audit.count_canvas_nodes(canvas_id=canvas_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment) or 0)
            if current >= self.MAX_NODES_PER_CANVAS:
                raise ValueError('canvas node limit exceeded')
        elif kind == 'edge':
            current = int(gw.audit.count_canvas_edges(canvas_id=canvas_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment) or 0)
            if current >= self.MAX_EDGES_PER_CANVAS:
                raise ValueError('canvas edge limit exceeded')
        elif kind == 'view':
            current = int(gw.audit.count_canvas_views(canvas_id=canvas_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment) or 0)
            if current >= self.MAX_VIEWS_PER_CANVAS:
                raise ValueError('canvas view limit exceeded')


    def _sanitize_scope(
        self,
        gw: AdminGatewayLike,
        *,
        tenant_id: str | None,
        workspace_id: str | None,
        environment: str | None,
    ) -> dict[str, Any]:
        tenancy = getattr(gw, 'tenancy', None)
        if tenancy is not None and hasattr(tenancy, 'normalize_scope'):
            try:
                return tenancy.normalize_scope(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
            except Exception:
                pass
        return {
            'tenant_id': tenant_id,
            'workspace_id': workspace_id,
            'environment': environment,
        }

    def _normalize_toggles(self, toggles: dict[str, Any] | None) -> dict[str, bool]:
        normalized = dict(self._DEFAULT_TOGGLES)
        for key, value in dict(toggles or {}).items():
            if key in normalized:
                normalized[key] = bool(value)
        return normalized

    @staticmethod
    def _safe_call(obj: Any, method_name: str, default: Any, /, *args: Any, **kwargs: Any) -> Any:
        method = getattr(obj, method_name, None)
        if not callable(method):
            return default
        try:
            return method(*args, **kwargs)
        except Exception:
            return default

    @staticmethod
    def _redact_sensitive(value: Any) -> Any:
        if isinstance(value, dict):
            redacted: dict[str, Any] = {}
            for key, item in value.items():
                lowered = str(key).lower()
                if any(token in lowered for token in ('secret', 'token', 'password', 'value', 'credential')):
                    redacted[key] = '***redacted***'
                else:
                    redacted[key] = LiveCanvasService._redact_sensitive(item)
            return redacted
        if isinstance(value, list):
            return [LiveCanvasService._redact_sensitive(item) for item in value]
        return value

    def list_documents(
        self,
        gw: AdminGatewayLike,
        *,
        limit: int = 50,
        status: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        scope = self._sanitize_scope(gw, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        items = gw.audit.list_canvas_documents(limit=limit, status=status, **scope)
        return {'ok': True, 'items': items, 'scope': scope}

    def create_document(
        self,
        gw: AdminGatewayLike,
        *,
        actor: str,
        title: str,
        description: str = '',
        status: str = 'active',
        metadata: dict[str, Any] | None = None,
        share_token: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        if not str(title or '').strip():
            raise ValueError('canvas title is required')
        scope = self._sanitize_scope(gw, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        self._enforce_scope_limits(gw, scope=scope)
        self._enforce_canvas_payload(payload=dict(metadata or {}))
        document = gw.audit.create_canvas_document(
            title=str(title).strip(),
            description=str(description or ''),
            status=str(status or 'active').strip() or 'active',
            created_by=str(actor or 'admin'),
            metadata=dict(metadata or {}),
            **scope,
        )
        gw.audit.log_event('admin', 'canvas', actor or 'operator', document['canvas_id'], {
            'action': 'canvas_document_created',
            'title': document['title'],
            **scope,
        }, **scope)
        return {'ok': True, 'document': document, 'scope': scope}

    def get_document(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        scope = self._sanitize_scope(gw, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        document = gw.audit.get_canvas_document(canvas_id, **scope)
        if document is None:
            return {'ok': False, 'reason': 'not_found', 'canvas_id': canvas_id, 'scope': scope}
        return {
            'ok': True,
            'document': document,
            'nodes': gw.audit.list_canvas_nodes(canvas_id=canvas_id, **scope),
            'edges': gw.audit.list_canvas_edges(canvas_id=canvas_id, **scope),
            'views': gw.audit.list_canvas_views(canvas_id=canvas_id, **scope),
            'presence': gw.audit.list_canvas_presence(canvas_id=canvas_id, **scope),
            'events': gw.audit.list_canvas_events(canvas_id=canvas_id, limit=50, **scope),
            'comments': self.list_comments(gw, canvas_id=canvas_id, **scope).get('items', []),
            'snapshots': self.list_snapshots(gw, canvas_id=canvas_id, **scope).get('items', []),
            'presence_events': self.list_presence_events(gw, canvas_id=canvas_id, **scope).get('items', []),
            'overlay_states': self.list_overlay_states(gw, canvas_id=canvas_id, **scope).get('items', []),
            'scope': scope,
        }

    def upsert_node(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        actor: str,
        node_id: str | None = None,
        node_type: str,
        label: str,
        position_x: float = 0.0,
        position_y: float = 0.0,
        width: float = 240.0,
        height: float = 120.0,
        data: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        scope = self._sanitize_scope(gw, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        document = gw.audit.get_canvas_document(canvas_id, **scope)
        if document is None:
            raise KeyError(canvas_id)
        self._enforce_canvas_payload(payload={'label': label, 'data': data})
        if not node_id:
            self._enforce_canvas_counts(gw, canvas_id=canvas_id, kind='node', tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'))
        node = gw.audit.upsert_canvas_node(
            canvas_id=canvas_id,
            node_id=node_id,
            node_type=str(node_type or 'note').strip() or 'note',
            label=str(label or '').strip(),
            position_x=float(position_x or 0.0),
            position_y=float(position_y or 0.0),
            width=float(width or 240.0),
            height=float(height or 120.0),
            data=dict(data or {}),
            created_by=str(actor or 'admin'),
            tenant_id=document.get('tenant_id'),
            workspace_id=document.get('workspace_id'),
            environment=document.get('environment'),
        )
        gw.audit.log_event('admin', 'canvas', actor or 'operator', canvas_id, {
            'action': 'canvas_node_upserted',
            'node_id': node['node_id'],
            'node_type': node['node_type'],
        }, tenant_id=document.get('tenant_id'), workspace_id=document.get('workspace_id'), environment=document.get('environment'))
        return {'ok': True, 'node': node, 'scope': scope}

    def upsert_edge(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        actor: str,
        edge_id: str | None = None,
        source_node_id: str,
        target_node_id: str,
        label: str = '',
        edge_type: str = 'default',
        data: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        scope = self._sanitize_scope(gw, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        document = gw.audit.get_canvas_document(canvas_id, **scope)
        if document is None:
            raise KeyError(canvas_id)
        self._enforce_canvas_payload(payload={'label': label, 'data': data, 'source_node_id': source_node_id, 'target_node_id': target_node_id})
        if not edge_id:
            self._enforce_canvas_counts(gw, canvas_id=canvas_id, kind='edge', tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'))
        edge = gw.audit.upsert_canvas_edge(
            canvas_id=canvas_id,
            edge_id=edge_id,
            source_node_id=str(source_node_id or ''),
            target_node_id=str(target_node_id or ''),
            label=str(label or ''),
            edge_type=str(edge_type or 'default'),
            data=dict(data or {}),
            created_by=str(actor or 'admin'),
            tenant_id=document.get('tenant_id'),
            workspace_id=document.get('workspace_id'),
            environment=document.get('environment'),
        )
        gw.audit.log_event('admin', 'canvas', actor or 'operator', canvas_id, {
            'action': 'canvas_edge_upserted',
            'edge_id': edge['edge_id'],
            'source_node_id': edge['source_node_id'],
            'target_node_id': edge['target_node_id'],
        }, tenant_id=document.get('tenant_id'), workspace_id=document.get('workspace_id'), environment=document.get('environment'))
        return {'ok': True, 'edge': edge, 'scope': scope}

    def save_view(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        actor: str,
        name: str,
        view_id: str | None = None,
        layout: dict[str, Any] | None = None,
        filters: dict[str, Any] | None = None,
        is_default: bool = False,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        scope = self._sanitize_scope(gw, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        document = gw.audit.get_canvas_document(canvas_id, **scope)
        if document is None:
            raise KeyError(canvas_id)
        self._enforce_canvas_payload(payload={'name': name, 'layout': layout, 'filters': filters})
        if not view_id:
            self._enforce_canvas_counts(gw, canvas_id=canvas_id, kind='view', tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'))
        view = gw.audit.save_canvas_view(
            canvas_id=canvas_id,
            view_id=view_id,
            name=str(name or 'Default').strip() or 'Default',
            layout=dict(layout or {}),
            filters=dict(filters or {}),
            is_default=bool(is_default),
            created_by=str(actor or 'admin'),
            tenant_id=document.get('tenant_id'),
            workspace_id=document.get('workspace_id'),
            environment=document.get('environment'),
        )
        gw.audit.log_event('admin', 'canvas', actor or 'operator', canvas_id, {
            'action': 'canvas_view_saved',
            'view_id': view['view_id'],
            'name': view['name'],
        }, tenant_id=document.get('tenant_id'), workspace_id=document.get('workspace_id'), environment=document.get('environment'))
        return {'ok': True, 'view': view, 'scope': scope}

    def update_presence(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        actor: str,
        user_key: str,
        cursor_x: float = 0.0,
        cursor_y: float = 0.0,
        selected_node_id: str | None = None,
        status: str = 'active',
        metadata: dict[str, Any] | None = None,
        share_token: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        scope = self._sanitize_scope(gw, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        document = gw.audit.get_canvas_document(canvas_id, **scope)
        if document is None:
            raise KeyError(canvas_id)
        presence = gw.audit.upsert_canvas_presence(
            canvas_id=canvas_id,
            user_key=str(user_key or actor or 'operator'),
            cursor_x=float(cursor_x or 0.0),
            cursor_y=float(cursor_y or 0.0),
            selected_node_id=selected_node_id,
            status=str(status or 'active'),
            metadata=dict(metadata or {}),
            tenant_id=document.get('tenant_id'),
            workspace_id=document.get('workspace_id'),
            environment=document.get('environment'),
        )
        self._safe_call(
            gw.audit,
            'record_canvas_presence_event',
            None,
            canvas_id=canvas_id,
            user_key=str(user_key or actor or 'operator'),
            event_type='presence_updated',
            payload={
                'cursor_x': float(cursor_x or 0.0),
                'cursor_y': float(cursor_y or 0.0),
                'selected_node_id': selected_node_id,
                'status': str(status or 'active'),
                'metadata': dict(metadata or {}),
            },
            tenant_id=document.get('tenant_id'),
            workspace_id=document.get('workspace_id'),
            environment=document.get('environment'),
        )
        gw.audit.log_event('admin', 'canvas', actor or user_key or 'operator', canvas_id, {
            'action': 'canvas_presence_updated',
            'user_key': user_key,
            'selected_node_id': selected_node_id,
        }, tenant_id=document.get('tenant_id'), workspace_id=document.get('workspace_id'), environment=document.get('environment'))
        return {'ok': True, 'presence': presence, 'scope': scope}

    def list_events(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        limit: int = 50,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        scope = self._sanitize_scope(gw, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        return {
            'ok': True,
            'canvas_id': canvas_id,
            'items': gw.audit.list_canvas_events(canvas_id=canvas_id, limit=limit, **scope),
            'scope': scope,
        }

    def add_comment(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        actor: str,
        body: str,
        node_id: str | None = None,
        status: str = 'active',
        metadata: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        if not str(body or '').strip():
            raise ValueError('comment body is required')
        scope = self._sanitize_scope(gw, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        document = gw.audit.get_canvas_document(canvas_id, **scope)
        if document is None:
            raise KeyError(canvas_id)
        comment = self._safe_call(
            gw.audit,
            'create_canvas_comment',
            None,
            canvas_id=canvas_id,
            body=str(body or '').strip(),
            author=str(actor or 'admin'),
            node_id=node_id,
            status=str(status or 'active'),
            metadata=dict(metadata or {}),
            tenant_id=document.get('tenant_id'),
            workspace_id=document.get('workspace_id'),
            environment=document.get('environment'),
        )
        gw.audit.log_event('admin', 'canvas', actor or 'operator', canvas_id, {
            'action': 'canvas_comment_created',
            'comment_id': (comment or {}).get('comment_id'),
            'node_id': node_id,
        }, tenant_id=document.get('tenant_id'), workspace_id=document.get('workspace_id'), environment=document.get('environment'))
        return {'ok': True, 'comment': comment, 'scope': scope}

    def list_comments(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        limit: int = 50,
        status: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        scope = self._sanitize_scope(gw, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        return {
            'ok': True,
            'canvas_id': canvas_id,
            'items': self._safe_call(gw.audit, 'list_canvas_comments', [], canvas_id=canvas_id, limit=limit, status=status, **scope),
            'scope': scope,
        }

    def create_snapshot(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        actor: str,
        label: str = '',
        snapshot_kind: str = 'manual',
        view_id: str | None = None,
        selected_node_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        share_token: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        scope = self._sanitize_scope(gw, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        detail = self.get_document(gw, canvas_id=canvas_id, **scope)
        if not detail.get('ok'):
            raise KeyError(canvas_id)
        document = dict(detail.get('document') or {})
        snapshot_payload = {
            'document': document,
            'nodes': list(detail.get('nodes') or []),
            'edges': list(detail.get('edges') or []),
            'views': list(detail.get('views') or []),
            'presence': list(detail.get('presence') or []),
            'comments': list(detail.get('comments') or []),
            'overlay_states': list(detail.get('overlay_states') or []),
            'selected_node_id': selected_node_id,
            'metadata': dict(metadata or {}),
            'summary': {
                'node_count': len(list(detail.get('nodes') or [])),
                'edge_count': len(list(detail.get('edges') or [])),
                'view_count': len(list(detail.get('views') or [])),
                'comment_count': len(list(detail.get('comments') or [])),
                'presence_count': len(list(detail.get('presence') or [])),
            },
        }
        if self._payload_size(snapshot_payload) > self.MAX_SNAPSHOT_BYTES:
            raise ValueError('canvas snapshot exceeds max size')
        snapshot = self._safe_call(
            gw.audit,
            'create_canvas_snapshot',
            None,
            canvas_id=canvas_id,
            snapshot_kind=str(snapshot_kind or 'manual').strip() or 'manual',
            label=str(label or document.get('title') or 'Snapshot').strip() or 'Snapshot',
            snapshot=snapshot_payload,
            metadata=dict(metadata or {}),
            created_by=str(actor or 'admin'),
            view_id=view_id,
            share_token=share_token,
            tenant_id=document.get('tenant_id'),
            workspace_id=document.get('workspace_id'),
            environment=document.get('environment'),
        )
        gw.audit.log_event('admin', 'canvas', actor or 'operator', canvas_id, {
            'action': 'canvas_snapshot_created',
            'snapshot_id': (snapshot or {}).get('snapshot_id'),
            'snapshot_kind': (snapshot or {}).get('snapshot_kind'),
        }, tenant_id=document.get('tenant_id'), workspace_id=document.get('workspace_id'), environment=document.get('environment'))
        return {'ok': True, 'snapshot': snapshot, 'scope': scope}

    def list_snapshots(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        limit: int = 50,
        snapshot_kind: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        scope = self._sanitize_scope(gw, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        return {
            'ok': True,
            'canvas_id': canvas_id,
            'items': self._safe_call(gw.audit, 'list_canvas_snapshots', [], canvas_id=canvas_id, limit=limit, snapshot_kind=snapshot_kind, **scope),
            'scope': scope,
        }

    def share_view(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        actor: str,
        view_id: str | None = None,
        label: str = '',
        selected_node_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        scope = self._sanitize_scope(gw, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        share_token = uuid.uuid4().hex[:16]
        payload = dict(metadata or {})
        payload['shared'] = True
        payload['share_token'] = share_token
        created = self.create_snapshot(
            gw,
            canvas_id=canvas_id,
            actor=actor,
            label=label or 'Shared view',
            snapshot_kind='shared_view',
            view_id=view_id,
            selected_node_id=selected_node_id,
            metadata=payload,
            share_token=share_token,
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        )
        snapshot = dict(created.get('snapshot') or {})
        snapshot['share_token'] = snapshot.get('share_token') or share_token
        return {'ok': True, 'snapshot': snapshot, 'share_token': snapshot['share_token'], 'scope': scope}

    def compare_snapshots(
        self,
        gw: AdminGatewayLike,
        *,
        snapshot_a_id: str,
        snapshot_b_id: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        scope = self._sanitize_scope(gw, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        snapshot_a = self._safe_call(gw.audit, 'get_canvas_snapshot', None, snapshot_a_id, **scope)
        snapshot_b = self._safe_call(gw.audit, 'get_canvas_snapshot', None, snapshot_b_id, **scope)
        if snapshot_a is None or snapshot_b is None:
            return {'ok': False, 'reason': 'not_found', 'snapshot_a_id': snapshot_a_id, 'snapshot_b_id': snapshot_b_id, 'scope': scope}
        data_a = dict(snapshot_a.get('snapshot') or {})
        data_b = dict(snapshot_b.get('snapshot') or {})
        nodes_a = {str(item.get('node_id') or '') for item in list(data_a.get('nodes') or [])}
        nodes_b = {str(item.get('node_id') or '') for item in list(data_b.get('nodes') or [])}
        edges_a = {str(item.get('edge_id') or '') for item in list(data_a.get('edges') or [])}
        edges_b = {str(item.get('edge_id') or '') for item in list(data_b.get('edges') or [])}
        summary = {
            'node_count_delta': len(nodes_b) - len(nodes_a),
            'edge_count_delta': len(edges_b) - len(edges_a),
            'comment_count_delta': len(list(data_b.get('comments') or [])) - len(list(data_a.get('comments') or [])),
            'presence_count_delta': len(list(data_b.get('presence') or [])) - len(list(data_a.get('presence') or [])),
        }
        diff = {
            'added_node_ids': sorted(nodes_b - nodes_a),
            'removed_node_ids': sorted(nodes_a - nodes_b),
            'added_edge_ids': sorted(edges_b - edges_a),
            'removed_edge_ids': sorted(edges_a - edges_b),
        }
        return {'ok': True, 'snapshot_a': snapshot_a, 'snapshot_b': snapshot_b, 'summary': summary, 'diff': diff, 'scope': scope}

    def list_presence_events(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        limit: int = 50,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        scope = self._sanitize_scope(gw, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        return {
            'ok': True,
            'canvas_id': canvas_id,
            'items': self._safe_call(gw.audit, 'list_canvas_presence_events', [], canvas_id=canvas_id, limit=limit, **scope),
            'scope': scope,
        }

    def save_overlay_state(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        actor: str,
        state_key: str = 'default',
        toggles: dict[str, Any] | None = None,
        inspector: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        scope = self._sanitize_scope(gw, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        document = gw.audit.get_canvas_document(canvas_id, **scope)
        if document is None:
            raise KeyError(canvas_id)
        state = gw.audit.upsert_canvas_overlay_state(
            canvas_id=canvas_id,
            state_key=str(state_key or 'default').strip() or 'default',
            toggles=self._normalize_toggles(toggles),
            inspector=dict(inspector or {}),
            created_by=str(actor or 'admin'),
            tenant_id=document.get('tenant_id'),
            workspace_id=document.get('workspace_id'),
            environment=document.get('environment'),
        )
        gw.audit.log_event('admin', 'canvas', actor or 'operator', canvas_id, {
            'action': 'canvas_overlay_state_saved',
            'state_key': state.get('state_key'),
            'toggles': state.get('toggles'),
        }, tenant_id=document.get('tenant_id'), workspace_id=document.get('workspace_id'), environment=document.get('environment'))
        return {'ok': True, 'state': state, 'scope': scope}

    def list_overlay_states(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        scope = self._sanitize_scope(gw, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        return {
            'ok': True,
            'canvas_id': canvas_id,
            'items': self._safe_call(gw.audit, 'list_canvas_overlay_states', [], canvas_id=canvas_id, **scope),
            'scope': scope,
        }

    def get_operational_overlays(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        selected_node_id: str | None = None,
        toggles: dict[str, Any] | None = None,
        state_key: str = 'default',
        limit: int = 50,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        detail = self.get_document(
            gw,
            canvas_id=canvas_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        if not detail.get('ok'):
            return detail
        scope = dict(detail.get('scope') or {})
        normalized_toggles = self._normalize_toggles(toggles)
        nodes = list(detail.get('nodes') or [])
        refs = self._collect_refs(nodes, selected_node_id=selected_node_id)
        fetch_limit = max(int(limit or 50), 1)

        traces_all = self._safe_call(gw.audit, 'list_decision_traces', [], limit=max(fetch_limit * 4, 100), **scope)
        approvals_all = self._safe_call(gw.audit, 'list_approvals', [], limit=max(fetch_limit * 4, 100), **scope)
        events_all = self._safe_call(gw.audit, 'list_events_filtered', [], limit=max(fetch_limit * 6, 150), **scope)
        operator_overview = self.operator_console_service.overview(gw, limit=max(fetch_limit * 2, 50), **scope)
        secret_usage = self.secret_governance_service.usage(gw, limit=max(fetch_limit * 2, 50), **scope)
        secret_catalog = self.secret_governance_service.catalog(gw, limit=max(fetch_limit * 2, 50), **scope)
        cost_summary = self.cost_governance_service.summary(gw, group_by='workflow', limit=max(fetch_limit * 2, 50), **scope)
        cost_budgets = self.cost_governance_service.budgets(gw, limit=max(fetch_limit * 2, 50), **scope)

        traces = [item for item in list(traces_all or []) if self._trace_matches(item, refs)][:fetch_limit]
        approvals = [self._compact_approval(item) for item in list(approvals_all or []) if self._approval_matches(item, refs)][:fetch_limit]
        failures = [item for item in list((operator_overview.get('recent_failures') or [])) if self._failure_matches(item, refs)][:fetch_limit]
        secret_items = [self._sanitize_secret_usage(item) for item in list(secret_usage.get('items') or []) if self._secret_usage_matches(item, refs)][:fetch_limit]
        secret_catalog_items = [self._sanitize_secret_catalog(item) for item in list(secret_catalog.get('items') or []) if self._secret_catalog_matches(item, refs)][:fetch_limit]
        cost_items = [self._compact_cost_item(item) for item in list(cost_summary.get('items') or []) if self._cost_matches(item, refs)][:fetch_limit]
        budget_items = [self._compact_budget_item(item) for item in list(cost_budgets.get('items') or []) if self._budget_matches(item, refs)][:fetch_limit]
        policy_items = self._policy_overlay_items(gw, refs=refs, traces=traces, approvals=approvals, events=list(events_all or []), scope=scope, limit=fetch_limit)

        overlays = {
            'policy': {
                'enabled': normalized_toggles.get('policy', True),
                'items': policy_items if normalized_toggles.get('policy', True) else [],
                'summary': {
                    'policy_hits': len(policy_items),
                    'policy_signature': self._safe_call(getattr(gw, 'policy', None), 'signature', None) if getattr(gw, 'policy', None) is not None else None,
                },
            },
            'cost': {
                'enabled': normalized_toggles.get('cost', True),
                'items': cost_items if normalized_toggles.get('cost', True) else [],
                'budgets': budget_items if normalized_toggles.get('cost', True) else [],
                'summary': {
                    'workflow_groups': len(cost_items),
                    'total_spend': round(
                        sum(float(item.get('total_spend') or 0.0) for item in cost_items)
                        if cost_items
                        else float(((cost_summary.get('summary') or {}).get('total_spend') or 0.0)),
                        6,
                    ),
                    'budget_alerts': sum(1 for item in budget_items if str(item.get('status') or '') in {'warning', 'critical'}),
                },
            },
            'traces': {
                'enabled': normalized_toggles.get('traces', True),
                'items': [self._compact_trace(item) for item in traces] if normalized_toggles.get('traces', True) else [],
                'summary': {
                    'trace_count': len(traces),
                    'average_latency_ms': round((sum(float(item.get('latency_ms') or 0.0) for item in traces) / len(traces)) if traces else 0.0, 3),
                    'estimated_cost': round(sum(float(item.get('estimated_cost') or 0.0) for item in traces), 6),
                },
            },
            'failures': {
                'enabled': normalized_toggles.get('failures', True),
                'items': failures if normalized_toggles.get('failures', True) else [],
                'summary': {
                    'failure_count': len(failures),
                    'by_kind': dict(Counter(str(item.get('kind') or 'unknown') for item in failures)),
                },
            },
            'approvals': {
                'enabled': normalized_toggles.get('approvals', True),
                'items': approvals if normalized_toggles.get('approvals', True) else [],
                'summary': {
                    'approval_count': len(approvals),
                    'pending': sum(1 for item in approvals if str(item.get('status') or '') == 'pending'),
                },
            },
            'secrets': {
                'enabled': normalized_toggles.get('secrets', True),
                'items': secret_items if normalized_toggles.get('secrets', True) else [],
                'catalog': secret_catalog_items if normalized_toggles.get('secrets', True) else [],
                'summary': {
                    'usage_groups': len(secret_items),
                    'catalog_refs': len(secret_catalog_items),
                },
            },
        }
        states = self.list_overlay_states(gw, canvas_id=canvas_id, **scope).get('items', [])
        active_state = next((item for item in states if str(item.get('state_key') or '') == str(state_key or 'default')), None)
        selected_node = next((node for node in nodes if str(node.get('node_id') or '') == str(selected_node_id or '')), None)
        inspector = {
            'selected_node_id': selected_node_id,
            'selected_node': selected_node,
            'references': refs,
            'overlay_state': active_state,
            'node_count': len(nodes),
            'edge_count': len(list(detail.get('edges') or [])),
            'event_count': len(list(detail.get('events') or [])),
        }
        return {
            'ok': True,
            'canvas_id': canvas_id,
            'document': detail.get('document'),
            'selected_node_id': selected_node_id,
            'toggles': normalized_toggles,
            'states': states,
            'state_key': str(state_key or 'default').strip() or 'default',
            'overlays': overlays,
            'inspector': inspector,
            'scope': scope,
        }

    def list_operational_views(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        detail = self.get_document(
            gw,
            canvas_id=canvas_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        if not detail.get('ok'):
            return detail
        scope = dict(detail.get('scope') or {})
        nodes = list(detail.get('nodes') or [])
        saved_views = list(detail.get('views') or [])
        by_kind = Counter(str(node.get('node_type') or 'note').strip().lower() or 'note' for node in nodes)
        suggestions: list[dict[str, Any]] = [
            {
                'view_key': 'overview',
                'name': 'Overview',
                'kind': 'overview',
                'description': 'Vista operacional general del canvas.',
                'filters': {'node_types': sorted(k for k, v in by_kind.items() if v)},
                'toggles': dict(self._DEFAULT_TOGGLES),
                'layout': {'fit': 'all', 'focus': 'document'},
            }
        ]
        if by_kind.get('workflow') or by_kind.get('approval'):
            suggestions.append({
                'view_key': 'workflow-control',
                'name': 'Workflow control',
                'kind': 'workflow',
                'description': 'Foco en workflows, aprobaciones y fallos.',
                'filters': {'node_types': [item for item in ('workflow', 'approval') if by_kind.get(item)]},
                'toggles': {'policy': True, 'cost': False, 'traces': True, 'failures': True, 'approvals': True, 'secrets': False},
                'layout': {'fit': 'filtered', 'focus': 'workflow'},
            })
        if by_kind.get('runtime') or by_kind.get('openclaw_runtime'):
            suggestions.append({
                'view_key': 'runtime-ops',
                'name': 'Runtime ops',
                'kind': 'runtime',
                'description': 'Monitorización y acciones sobre runtimes externos.',
                'filters': {'node_types': [item for item in ('runtime', 'openclaw_runtime') if by_kind.get(item)]},
                'toggles': {'policy': False, 'cost': False, 'traces': True, 'failures': True, 'approvals': False, 'secrets': True},
                'layout': {'fit': 'filtered', 'focus': 'runtime'},
            })
        if by_kind.get('tool') or by_kind.get('policy'):
            suggestions.append({
                'view_key': 'risk-hotspots',
                'name': 'Risk hotspots',
                'kind': 'risk',
                'description': 'Herramientas, políticas y secretos más sensibles.',
                'filters': {'node_types': [item for item in ('tool', 'policy') if by_kind.get(item)]},
                'toggles': {'policy': True, 'cost': False, 'traces': True, 'failures': True, 'approvals': False, 'secrets': True},
                'layout': {'fit': 'filtered', 'focus': 'risk'},
            })
        return {
            'ok': True,
            'canvas_id': canvas_id,
            'saved_views': saved_views,
            'suggested_views': suggestions,
            'summary': {
                'saved_count': len(saved_views),
                'suggested_count': len(suggestions),
                'node_types': dict(by_kind),
            },
            'scope': scope,
        }

    def get_node_inspector(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        node_id: str,
        state_key: str = 'default',
        limit: int = 50,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        actor: str = '',
    ) -> dict[str, Any]:
        detail = self.get_document(
            gw,
            canvas_id=canvas_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        if not detail.get('ok'):
            return detail
        scope = dict(detail.get('scope') or {})
        nodes = list(detail.get('nodes') or [])
        node = next((item for item in nodes if str(item.get('node_id') or '') == str(node_id or '')), None)
        if node is None:
            return {'ok': False, 'reason': 'node_not_found', 'canvas_id': canvas_id, 'node_id': node_id, 'scope': scope}
        refs = self._collect_refs(nodes, selected_node_id=node_id)
        overlays = self.get_operational_overlays(
            gw,
            canvas_id=canvas_id,
            selected_node_id=node_id,
            state_key=state_key,
            limit=limit,
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        )
        node_type = str(node.get('node_type') or '').strip().lower()
        data = dict(node.get('data') or {})
        related: dict[str, Any] = {}
        if node_type == 'workflow':
            workflow_id = str(data.get('workflow_id') or (refs.get('workflow_ids') or [''])[0] or '').strip()
            if workflow_id:
                related['workflow'] = self.operator_console_service.workflow_console(
                    gw,
                    workflow_id=workflow_id,
                    limit=limit,
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                )
        elif node_type == 'approval':
            approval_id = str(data.get('approval_id') or (refs.get('approval_ids') or [''])[0] or '').strip()
            if approval_id:
                related['approval'] = self._safe_call(
                    gw.audit, 'get_approval', None, approval_id,
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                )
        elif node_type in {'runtime', 'openclaw_runtime'}:
            runtime_id = str(data.get('runtime_id') or '').strip()
            if runtime_id:
                related['runtime'] = self.openclaw_adapter_service.get_runtime(
                    gw,
                    runtime_id=runtime_id,
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                )
        available_actions = self._node_available_actions(node, related=related)
        action_prechecks = {
            action_name: self._node_action_precheck(node=node, related=related, action=action_name, actor=actor)
            for action_name in available_actions
        }
        node_timeline = self.get_node_timeline(
            gw,
            canvas_id=canvas_id,
            node_id=node_id,
            limit=limit,
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        )
        return {
            'ok': True,
            'canvas_id': canvas_id,
            'node': node,
            'references': refs,
            'related': related,
            'available_actions': available_actions,
            'action_prechecks': action_prechecks,
            'overlay_focus': overlays.get('overlays') if overlays.get('ok') else {},
            'node_timeline': node_timeline.get('items') if node_timeline.get('ok') else [],
            'scope': scope,
        }

    def execute_node_action(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        node_id: str,
        action: str,
        actor: str,
        reason: str = '',
        payload: dict[str, Any] | None = None,
        user_role: str = 'operator',
        user_key: str = '',
        session_id: str = 'canvas',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        inspected = self.get_node_inspector(
            gw,
            canvas_id=canvas_id,
            node_id=node_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            actor=actor,
        )
        if not inspected.get('ok'):
            return inspected
        scope = dict(inspected.get('scope') or {})
        node = dict(inspected.get('node') or {})
        node_type = str(node.get('node_type') or '').strip().lower()
        data = dict(node.get('data') or {})
        normalized_action = str(action or '').strip().lower()
        raw_payload = dict(payload or {})
        precheck = self._node_action_precheck(node=node, related=dict(inspected.get('related') or {}), action=normalized_action, actor=actor)
        if not precheck.get('allowed'):
            self._safe_call(
                gw.audit, 'log_event', None, 'admin', 'canvas', str(actor or 'operator'), canvas_id,
                {'action': 'canvas_node_action_blocked', 'node_id': node_id, 'node_type': node_type, 'operator_action': normalized_action, 'reason': precheck.get('reason') or reason},
                tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'),
            )
            return {'ok': False, 'canvas_id': canvas_id, 'node_id': node_id, 'action': normalized_action, 'error': 'action_blocked', 'precheck': precheck, 'scope': scope}
        if precheck.get('requires_confirmation') and not bool(raw_payload.get('confirmed', False)):
            self._safe_call(
                gw.audit, 'log_event', None, 'admin', 'canvas', str(actor or 'operator'), canvas_id,
                {'action': 'canvas_node_action_confirmation_required', 'node_id': node_id, 'node_type': node_type, 'operator_action': normalized_action, 'reason': reason},
                tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'),
            )
            return {'ok': False, 'canvas_id': canvas_id, 'node_id': node_id, 'action': normalized_action, 'error': 'confirmation_required', 'precheck': precheck, 'scope': scope}
        result: dict[str, Any]
        if node_type == 'workflow':
            workflow_id = str(data.get('workflow_id') or (inspected.get('references') or {}).get('workflow_ids', [''])[0] or '').strip()
            if not workflow_id:
                raise ValueError('workflow node missing workflow_id')
            result = self.operator_console_service.workflow_action(
                gw, workflow_id=workflow_id, action=normalized_action, actor=actor, reason=reason,
                tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'),
            )
        elif node_type == 'approval':
            approval_id = str(data.get('approval_id') or (inspected.get('references') or {}).get('approval_ids', [''])[0] or '').strip()
            if not approval_id:
                raise ValueError('approval node missing approval_id')
            result = self.operator_console_service.approval_action(
                gw, approval_id=approval_id, action=normalized_action, actor=actor, reason=reason,
                tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'),
            )
        elif node_type in {'runtime', 'openclaw_runtime'}:
            runtime_id = str(data.get('runtime_id') or '').strip()
            if not runtime_id:
                raise ValueError('runtime node missing runtime_id')
            if normalized_action == 'health_check':
                result = self.openclaw_adapter_service.check_runtime_health(
                    gw, runtime_id=runtime_id, actor=actor, probe=str(raw_payload.get('probe') or 'ready'),
                    user_role=str(user_role or 'operator'), user_key=str(user_key or actor or ''),
                    session_id=str(session_id or f'canvas:{canvas_id}'), tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'),
                )
            else:
                dispatch_payload = dict(raw_payload.get('payload') or raw_payload)
                dispatch_action = normalized_action
                dry_run = bool(raw_payload.get('dry_run', False))
                if normalized_action in {'dry_run', 'preview'}:
                    dry_run = True
                    dispatch_action = str(raw_payload.get('dispatch_action') or 'health_check')
                result = self.openclaw_adapter_service.dispatch(
                    gw, runtime_id=runtime_id, actor=actor, action=dispatch_action, payload=dispatch_payload,
                    agent_id=str(raw_payload.get('agent_id') or data.get('agent_id') or ''),
                    user_role=str(user_role or 'operator'),
                    user_key=str(user_key or actor or ''),
                    session_id=str(session_id or f'canvas:{canvas_id}'),
                    tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'),
                    dry_run=dry_run,
                )
        else:
            raise ValueError('Unsupported node action')
        refreshed = self.get_node_inspector(
            gw,
            canvas_id=canvas_id,
            node_id=node_id,
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
            actor=actor,
        )
        self._safe_call(
            gw.audit, 'log_event', None, 'admin', 'canvas', str(actor or 'operator'), canvas_id,
            {'action': 'canvas_node_action_executed', 'node_id': node_id, 'node_type': node_type, 'operator_action': normalized_action, 'reason': reason, 'reconciled': bool(refreshed.get('ok'))},
            tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'),
        )
        return {
            'ok': True,
            'canvas_id': canvas_id,
            'node_id': node_id,
            'action': normalized_action,
            'precheck': precheck,
            'result': result,
            'reconciled': bool(refreshed.get('ok')),
            'refresh': refreshed if refreshed.get('ok') else {},
            'scope': scope,
        }

    def _node_available_actions(self, node: dict[str, Any], *, related: dict[str, Any] | None = None) -> list[str]:
        node_type = str(node.get('node_type') or '').strip().lower()
        if node_type == 'workflow':
            workflow = dict((related or {}).get('workflow', {}).get('workflow') or {})
            status = str(workflow.get('status') or '').strip().lower()
            if status in {'succeeded', 'failed', 'rejected', 'cancelled'}:
                return ['run']
            available = list(workflow.get('available_actions') or [])
            return available or ['cancel']
        if node_type == 'approval':
            approval = dict((related or {}).get('approval') or {})
            available = list(approval.get('available_actions') or [])
            return available or ['claim', 'approve', 'reject']
        if node_type in {'runtime', 'openclaw_runtime'}:
            return ['health_check', 'ping', 'dry_run']
        return []

    def get_node_timeline(
        self,
        gw: AdminGatewayLike,
        *,
        canvas_id: str,
        node_id: str,
        limit: int = 50,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        detail = self.get_document(gw, canvas_id=canvas_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if not detail.get('ok'):
            return detail
        scope = dict(detail.get('scope') or {})
        nodes = list(detail.get('nodes') or [])
        node = next((item for item in nodes if str(item.get('node_id') or '') == str(node_id or '')), None)
        if node is None:
            return {'ok': False, 'reason': 'node_not_found', 'canvas_id': canvas_id, 'node_id': node_id, 'scope': scope}
        refs = self._collect_refs(nodes, selected_node_id=node_id)
        node_type = str(node.get('node_type') or '').strip().lower()
        items: list[dict[str, Any]] = []
        if node_type == 'workflow':
            workflow_id = str(((node.get('data') or {}).get('workflow_id')) or (refs.get('workflow_ids') or [''])[0] or '').strip()
            timeline = self.operator_console_service.workflow_service.unified_timeline(
                gw, workflow_id=workflow_id or None, limit=limit, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')
            )
            for event in list(timeline.get('items') or []):
                payload = dict(event.get('payload') or {})
                items.append({'kind': 'event', 'ts': float(event.get('ts') or 0.0), 'label': str(payload.get('event') or payload.get('action') or 'workflow_event'), 'status': str(payload.get('status') or ''), 'event': event})
        elif node_type == 'approval':
            approval_id = str(((node.get('data') or {}).get('approval_id')) or (refs.get('approval_ids') or [''])[0] or '').strip()
            timeline = self.operator_console_service.workflow_service.unified_timeline(
                gw, approval_id=approval_id or None, limit=limit, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')
            )
            for event in list(timeline.get('items') or []):
                payload = dict(event.get('payload') or {})
                items.append({'kind': 'event', 'ts': float(event.get('ts') or 0.0), 'label': str(payload.get('event') or payload.get('action') or 'approval_event'), 'status': str(payload.get('status') or ''), 'event': event})
        elif node_type in {'runtime', 'openclaw_runtime'}:
            runtime_id = str(((node.get('data') or {}).get('runtime_id')) or '').strip()
            events = self._safe_call(gw.audit, 'list_events_filtered', [], limit=max(limit * 5, 100), channels=['broker'], tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'))
            for event in list(events or []):
                payload = dict(event.get('payload') or {})
                if str(payload.get('runtime_id') or '') != runtime_id:
                    continue
                items.append({'kind': 'event', 'ts': float(event.get('ts') or 0.0), 'label': str(payload.get('action') or payload.get('event') or 'runtime_event'), 'status': str(payload.get('status') or payload.get('health_status') or ''), 'event': event})
            dispatches = self._safe_call(gw.audit, 'list_openclaw_dispatches', [], runtime_id=runtime_id, limit=limit, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'))
            for dispatch in list(dispatches or []):
                items.append({'kind': 'dispatch', 'ts': float(dispatch.get('created_at') or 0.0), 'label': str(dispatch.get('action') or 'dispatch'), 'status': str(dispatch.get('status') or ''), 'dispatch': dispatch})
        items.sort(key=lambda item: float(item.get('ts') or 0.0))
        return {'ok': True, 'canvas_id': canvas_id, 'node_id': node_id, 'items': items[-limit:], 'scope': scope}

    def _node_action_precheck(self, *, node: dict[str, Any], related: dict[str, Any] | None, action: str, actor: str = '') -> dict[str, Any]:
        normalized_action = str(action or '').strip().lower()
        node_type = str(node.get('node_type') or '').strip().lower()
        available = set(self._node_available_actions(node, related=related))
        if normalized_action not in available:
            return {'allowed': False, 'reason': 'action_not_available', 'requires_confirmation': False, 'warnings': []}
        warnings: list[str] = []
        if node_type == 'workflow':
            workflow = dict((related or {}).get('workflow', {}).get('workflow') or {})
            status = str(workflow.get('status') or '').strip().lower()
            if normalized_action == 'run' and status in {'running', 'waiting_approval'}:
                return {'allowed': False, 'reason': 'workflow_already_active', 'requires_confirmation': False, 'warnings': []}
            if normalized_action == 'cancel' and status not in {'created', 'pending', 'running', 'waiting_approval'}:
                return {'allowed': False, 'reason': 'workflow_not_cancellable', 'requires_confirmation': False, 'warnings': []}
        elif node_type == 'approval':
            approval = dict((related or {}).get('approval') or {})
            status = str(approval.get('status') or '').strip().lower()
            assigned_to = str(approval.get('assigned_to') or '').strip()
            actor_key = str(actor or '').strip()
            if status != 'pending':
                return {'allowed': False, 'reason': 'approval_not_pending', 'requires_confirmation': False, 'warnings': []}
            if assigned_to and actor_key and assigned_to != actor_key:
                return {'allowed': False, 'reason': 'approval_claimed_by_other', 'requires_confirmation': False, 'warnings': []}
        elif node_type in {'runtime', 'openclaw_runtime'}:
            runtime = dict((related or {}).get('runtime', {}).get('runtime') or {})
            health = dict((related or {}).get('runtime', {}).get('health') or {})
            if str(health.get('status') or '') in {'unhealthy', 'degraded'}:
                warnings.append(f"runtime_health:{health.get('status')}")
            if bool(health.get('stale')):
                warnings.append('runtime_health:stale')
            if not runtime:
                return {'allowed': False, 'reason': 'runtime_not_found', 'requires_confirmation': False, 'warnings': warnings}
        return {'allowed': True, 'reason': '', 'requires_confirmation': normalized_action in {'cancel', 'reject'}, 'warnings': warnings}

    @staticmethod
    def _node_references(node: dict[str, Any]) -> dict[str, set[str]]:
        data = dict(node.get('data') or {})
        refs = {
            'workflow_ids': set(),
            'approval_ids': set(),
            'session_ids': set(),
            'trace_ids': set(),
            'tool_names': set(),
            'secret_refs': set(),
            'policy_names': set(),
        }
        mapping = {
            'workflow_id': 'workflow_ids',
            'approval_id': 'approval_ids',
            'session_id': 'session_ids',
            'trace_id': 'trace_ids',
            'tool_name': 'tool_names',
            'secret_ref': 'secret_refs',
            'policy_name': 'policy_names',
        }
        for key, bucket_name in mapping.items():
            value = str(data.get(key) or '').strip()
            if value:
                refs[bucket_name].add(value)
        node_type = str(node.get('node_type') or '').strip().lower()
        label = str(node.get('label') or '').strip()
        if node_type == 'workflow' and label and not refs['workflow_ids']:
            refs['workflow_ids'].add(label)
        if node_type == 'approval' and label and not refs['approval_ids']:
            refs['approval_ids'].add(label)
        if node_type == 'tool' and label and not refs['tool_names']:
            refs['tool_names'].add(label)
        if node_type == 'policy' and label and not refs['policy_names']:
            refs['policy_names'].add(label)
        return refs

    def _collect_refs(self, nodes: list[dict[str, Any]], *, selected_node_id: str | None = None) -> dict[str, list[str]]:
        buckets = {key: set() for key in self._node_references({}).keys()}
        chosen = [node for node in nodes if not selected_node_id or str(node.get('node_id') or '') == str(selected_node_id)]
        if not chosen:
            chosen = list(nodes or [])
        for node in chosen:
            refs = self._node_references(node)
            for key, values in refs.items():
                buckets.setdefault(key, set()).update(str(item).strip() for item in values if str(item).strip())
        return {key: sorted(values) for key, values in buckets.items()}

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

    def _policy_overlay_items(
        self,
        gw: AdminGatewayLike,
        *,
        refs: dict[str, list[str]],
        traces: list[dict[str, Any]],
        approvals: list[dict[str, Any]],
        events: list[dict[str, Any]],
        scope: dict[str, Any],
        limit: int,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        policy_engine = getattr(gw, 'policy', None)
        for trace in traces:
            for raw in list(trace.get('policies') or []):
                if not isinstance(raw, dict):
                    continue
                key = f"trace:{trace.get('trace_id')}:{raw.get('name')}:{raw.get('effect')}"
                if key in seen:
                    continue
                seen.add(key)
                items.append({
                    'source': 'trace',
                    'trace_id': trace.get('trace_id'),
                    'name': raw.get('name') or 'policy',
                    'effect': raw.get('effect') or 'unknown',
                    'reason': raw.get('reason') or '',
                })
        for tool_name in list(refs.get('tool_names') or []):
            if policy_engine is None or not hasattr(policy_engine, 'explain_request'):
                continue
            key = f'tool:{tool_name}'
            if key in seen:
                continue
            seen.add(key)
            try:
                explanation = policy_engine.explain_request(
                    scope='tool',
                    resource_name=tool_name,
                    agent_name='default',
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                )
            except Exception:
                continue
            items.append({
                'source': 'explain_request',
                'resource': tool_name,
                'decision': (explanation.get('decision') or {}),
            })
        for approval in approvals:
            key = f"approval:{approval.get('approval_id')}"
            if key in seen:
                continue
            seen.add(key)
            items.append({
                'source': 'approval',
                'approval_id': approval.get('approval_id'),
                'workflow_id': approval.get('workflow_id'),
                'status': approval.get('status'),
                'requested_role': approval.get('requested_role'),
            })
        for event in list(events or []):
            payload = dict(event.get('payload') or {})
            action = str(payload.get('action') or '').strip()
            if action not in {'policy_blocked', 'policy_allowed', 'approval_required'}:
                continue
            items.append({
                'source': 'event',
                'action': action,
                'ts': event.get('ts'),
                'payload': payload,
            })
            if len(items) >= limit:
                break
        return items[:max(1, int(limit))]
