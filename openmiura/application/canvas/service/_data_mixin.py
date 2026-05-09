"""openmiura.application.canvas.service._data_mixin

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


class _LiveCanvasDataMixin:
    """Mixin: data methods on LiveCanvasService."""

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
        runtime_board = self.get_runtime_board(
            gw,
            canvas_id=canvas_id,
            limit=5,
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        ) if by_kind.get('runtime') or by_kind.get('openclaw_runtime') else {'ok': True, 'items': [], 'summary': {}}
        runtime_summary = dict(runtime_board.get('summary') or {})
        baseline_promotion_board = self.get_baseline_promotion_board(
            gw,
            canvas_id=canvas_id,
            limit=5,
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        ) if by_kind.get('baseline_promotion') or by_kind.get('policy_baseline_promotion') else {'ok': True, 'items': [], 'summary': {}}
        baseline_promotion_summary = dict(baseline_promotion_board.get('summary') or {})
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
                'description': 'MonitorizaciÃ³n y acciones sobre runtimes externos.',
                'filters': {'node_types': [item for item in ('runtime', 'openclaw_runtime') if by_kind.get(item)]},
                'toggles': {'policy': False, 'cost': False, 'traces': True, 'failures': True, 'approvals': False, 'secrets': True},
                'layout': {'fit': 'filtered', 'focus': 'runtime'},
                'summary': runtime_summary,
            })
            if int(runtime_summary.get('async_runtime_count') or 0) > 0 or int(runtime_summary.get('total_active_runs') or 0) > 0:
                suggestions.append({
                    'view_key': 'async-governed-runs',
                    'name': 'Async governed runs',
                    'kind': 'runtime_async',
                    'description': 'Seguimiento de runs asÃ­ncronos, estados canÃ³nicos y alertas por runtime.',
                    'filters': {'node_types': [item for item in ('runtime', 'openclaw_runtime') if by_kind.get(item)]},
                    'toggles': {'policy': False, 'cost': False, 'traces': True, 'failures': True, 'approvals': False, 'secrets': False},
                    'layout': {'fit': 'filtered', 'focus': 'runtime_async'},
                    'summary': runtime_summary,
                })
        if by_kind.get('baseline_promotion') or by_kind.get('policy_baseline_promotion'):
            suggestions.append({
                'view_key': 'baseline-rollouts',
                'name': 'Baseline rollouts',
                'kind': 'baseline_promotion',
                'description': 'Seguimiento de promociones de baseline, waves, gates y rollbacks.',
                'filters': {'node_types': [item for item in ('baseline_promotion', 'policy_baseline_promotion') if by_kind.get(item)]},
                'toggles': {'policy': True, 'cost': False, 'traces': True, 'failures': True, 'approvals': True, 'secrets': False},
                'layout': {'fit': 'filtered', 'focus': 'baseline_promotion'},
                'summary': baseline_promotion_summary,
            })
        if by_kind.get('tool') or by_kind.get('policy'):
            suggestions.append({
                'view_key': 'risk-hotspots',
                'name': 'Risk hotspots',
                'kind': 'risk',
                'description': 'Herramientas, polÃ­ticas y secretos mÃ¡s sensibles.',
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
                'runtime_board': runtime_summary,
                'baseline_promotion_board': baseline_promotion_summary,
            },
            'scope': scope,
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

