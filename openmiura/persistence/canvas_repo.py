"""CanvasRepo: persistence for the canvas domain of openMiura.

Owns the persistence logic for the canvas-related tables. The class
is instantiated by ``AuditStore`` so existing public callers remain
unaffected; ``AuditStore`` keeps thin one-line delegators on its API.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import time
import uuid
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from openmiura.core.db import DBConnection, CompatRow
from openmiura.core.tenancy.scope import assert_scope_match, normalize_scope
from openmiura.persistence.base import (
    infer_scope_from_session,
    row_scope,
    scope_payload,
    scope_where,
)


class CanvasRepo:
    def __init__(self, conn: DBConnection) -> None:
        self._conn = conn

    @staticmethod
    def _scope_payload(*, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any]:
        return scope_payload(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    @staticmethod
    def _row_scope(row: Any) -> dict[str, Any]:
        return row_scope(row)

    def _scope_where(self, clauses: list[str], params: list[Any], *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None, prefix: str = "") -> tuple[list[str], list[Any]]:
        return scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, prefix=prefix)

    def _infer_scope_from_session(self, session_id: str) -> dict[str, Any]:
        return infer_scope_from_session(self._conn, session_id)

    def _canvas_document_row_to_dict(self, row: Any) -> dict[str, Any]:
        try:
            metadata = json.loads(row['metadata_json'] or '{}')
        except Exception:
            metadata = {}
        return {
            'canvas_id': row['canvas_id'],
            'title': row['title'],
            'description': row['description'] or '',
            'status': row['status'],
            'created_by': row['created_by'] or '',
            'created_at': float(row['created_at']),
            'updated_at': float(row['updated_at']),
            'metadata': metadata,
            'tenant_id': row['tenant_id'],
            'workspace_id': row['workspace_id'],
            'environment': row['environment'],
        }

    def _canvas_node_row_to_dict(self, row: Any) -> dict[str, Any]:
        try:
            data = json.loads(row['data_json'] or '{}')
        except Exception:
            data = {}
        return {
            'node_id': row['node_id'],
            'canvas_id': row['canvas_id'],
            'node_type': row['node_type'],
            'label': row['label'] or '',
            'position_x': float(row['position_x']),
            'position_y': float(row['position_y']),
            'width': float(row['width']),
            'height': float(row['height']),
            'data': data,
            'created_by': row['created_by'] or '',
            'created_at': float(row['created_at']),
            'updated_at': float(row['updated_at']),
            'tenant_id': row['tenant_id'],
            'workspace_id': row['workspace_id'],
            'environment': row['environment'],
        }

    def _canvas_edge_row_to_dict(self, row: Any) -> dict[str, Any]:
        try:
            data = json.loads(row['data_json'] or '{}')
        except Exception:
            data = {}
        return {
            'edge_id': row['edge_id'],
            'canvas_id': row['canvas_id'],
            'source_node_id': row['source_node_id'],
            'target_node_id': row['target_node_id'],
            'label': row['label'] or '',
            'edge_type': row['edge_type'] or 'default',
            'data': data,
            'created_by': row['created_by'] or '',
            'created_at': float(row['created_at']),
            'updated_at': float(row['updated_at']),
            'tenant_id': row['tenant_id'],
            'workspace_id': row['workspace_id'],
            'environment': row['environment'],
        }

    def _canvas_view_row_to_dict(self, row: Any) -> dict[str, Any]:
        try:
            layout = json.loads(row['layout_json'] or '{}')
        except Exception:
            layout = {}
        try:
            filters = json.loads(row['filters_json'] or '{}')
        except Exception:
            filters = {}
        return {
            'view_id': row['view_id'],
            'canvas_id': row['canvas_id'],
            'name': row['name'] or '',
            'layout': layout,
            'filters': filters,
            'is_default': bool(row['is_default']),
            'created_by': row['created_by'] or '',
            'created_at': float(row['created_at']),
            'updated_at': float(row['updated_at']),
            'tenant_id': row['tenant_id'],
            'workspace_id': row['workspace_id'],
            'environment': row['environment'],
        }

    def _canvas_presence_row_to_dict(self, row: Any) -> dict[str, Any]:
        try:
            metadata = json.loads(row['metadata_json'] or '{}')
        except Exception:
            metadata = {}
        return {
            'presence_id': row['presence_id'],
            'canvas_id': row['canvas_id'],
            'user_key': row['user_key'],
            'cursor_x': float(row['cursor_x']),
            'cursor_y': float(row['cursor_y']),
            'selected_node_id': row['selected_node_id'] or '',
            'status': row['status'],
            'metadata': metadata,
            'updated_at': float(row['updated_at']),
            'tenant_id': row['tenant_id'],
            'workspace_id': row['workspace_id'],
            'environment': row['environment'],
        }

    def _canvas_overlay_state_row_to_dict(self, row: Any) -> dict[str, Any]:
        try:
            toggles = json.loads(row['toggles_json'] or '{}')
        except Exception:
            toggles = {}
        try:
            inspector = json.loads(row['inspector_json'] or '{}')
        except Exception:
            inspector = {}
        return {
            'overlay_state_id': row['overlay_state_id'],
            'canvas_id': row['canvas_id'],
            'state_key': row['state_key'] or 'default',
            'toggles': toggles,
            'inspector': inspector,
            'created_by': row['created_by'] or '',
            'created_at': float(row['created_at']),
            'updated_at': float(row['updated_at']),
            'tenant_id': row['tenant_id'],
            'workspace_id': row['workspace_id'],
            'environment': row['environment'],
        }

    def _canvas_comment_row_to_dict(self, row: Any) -> dict[str, Any]:
        try:
            metadata = json.loads(row['metadata_json'] or '{}')
        except Exception:
            metadata = {}
        return {
            'comment_id': row['comment_id'],
            'canvas_id': row['canvas_id'],
            'node_id': row['node_id'] or '',
            'body': row['body'] or '',
            'author': row['author'] or '',
            'status': row['status'] or 'active',
            'metadata': metadata,
            'created_at': float(row['created_at']),
            'updated_at': float(row['updated_at']),
            'tenant_id': row['tenant_id'],
            'workspace_id': row['workspace_id'],
            'environment': row['environment'],
        }

    def _canvas_snapshot_row_to_dict(self, row: Any) -> dict[str, Any]:
        try:
            snapshot = json.loads(row['snapshot_json'] or '{}')
        except Exception:
            snapshot = {}
        try:
            metadata = json.loads(row['metadata_json'] or '{}')
        except Exception:
            metadata = {}
        return {
            'snapshot_id': row['snapshot_id'],
            'canvas_id': row['canvas_id'],
            'snapshot_kind': row['snapshot_kind'] or 'manual',
            'label': row['label'] or '',
            'view_id': row['view_id'] or '',
            'share_token': row['share_token'] or '',
            'snapshot': snapshot,
            'metadata': metadata,
            'created_by': row['created_by'] or '',
            'created_at': float(row['created_at']),
            'tenant_id': row['tenant_id'],
            'workspace_id': row['workspace_id'],
            'environment': row['environment'],
        }

    def _canvas_presence_event_row_to_dict(self, row: Any) -> dict[str, Any]:
        try:
            payload = json.loads(row['payload_json'] or '{}')
        except Exception:
            payload = {}
        return {
            'presence_event_id': row['presence_event_id'],
            'canvas_id': row['canvas_id'],
            'user_key': row['user_key'] or '',
            'event_type': row['event_type'] or 'presence',
            'payload': payload,
            'created_at': float(row['created_at']),
            'tenant_id': row['tenant_id'],
            'workspace_id': row['workspace_id'],
            'environment': row['environment'],
        }

    def count_canvas_overlay_states(self, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        cur = self._conn.cursor(); clauses=[]; params=[]
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql='SELECT COUNT(*) FROM canvas_overlay_states'
        if clauses: sql += ' WHERE ' + ' AND '.join(clauses)
        return int(cur.execute(sql, tuple(params)).fetchone()[0])

    def upsert_canvas_overlay_state(
        self,
        *,
        canvas_id: str,
        state_key: str = 'default',
        toggles: dict[str, Any] | None = None,
        inspector: dict[str, Any] | None = None,
        created_by: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        cur = self._conn.cursor(); now = time.time()
        existing = cur.execute('SELECT overlay_state_id, created_at FROM canvas_overlay_states WHERE canvas_id=? AND state_key=? LIMIT 1', (canvas_id, state_key)).fetchone()
        if existing is None:
            overlay_state_id = str(uuid.uuid4())
            created_at = now
            cur.execute('INSERT INTO canvas_overlay_states(overlay_state_id, canvas_id, state_key, toggles_json, inspector_json, created_by, created_at, updated_at, tenant_id, workspace_id, environment) VALUES(?,?,?,?,?,?,?,?,?,?,?)', (overlay_state_id, canvas_id, state_key, json.dumps(toggles or {}, ensure_ascii=False), json.dumps(inspector or {}, ensure_ascii=False), created_by, created_at, now, tenant_id, workspace_id, environment))
        else:
            overlay_state_id = existing['overlay_state_id']
            created_at = float(existing['created_at'])
            cur.execute('UPDATE canvas_overlay_states SET toggles_json=?, inspector_json=?, created_by=?, created_at=?, updated_at=?, tenant_id=?, workspace_id=?, environment=? WHERE overlay_state_id=?', (json.dumps(toggles or {}, ensure_ascii=False), json.dumps(inspector or {}, ensure_ascii=False), created_by, created_at, now, tenant_id, workspace_id, environment, overlay_state_id))
        cur.execute('UPDATE canvas_documents SET updated_at=? WHERE canvas_id=?', (now, canvas_id))
        self._conn.commit()
        return next((item for item in self.list_canvas_overlay_states(canvas_id=canvas_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment) if item['overlay_state_id']==overlay_state_id), {'overlay_state_id': overlay_state_id})

    def list_canvas_overlay_states(self, *, canvas_id: str, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        cur = self._conn.cursor(); clauses=['canvas_id=?']; params=[canvas_id]
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql='SELECT overlay_state_id, canvas_id, state_key, toggles_json, inspector_json, created_by, created_at, updated_at, tenant_id, workspace_id, environment FROM canvas_overlay_states WHERE ' + ' AND '.join(clauses) + ' ORDER BY updated_at DESC'
        return [self._canvas_overlay_state_row_to_dict(row) for row in cur.execute(sql, tuple(params)).fetchall()]

    def count_canvas_documents(self, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        cur = self._conn.cursor(); clauses=[]; params=[]
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql='SELECT COUNT(*) FROM canvas_documents'
        if clauses: sql += ' WHERE ' + ' AND '.join(clauses)
        return int(cur.execute(sql, tuple(params)).fetchone()[0])

    def count_canvas_nodes(self, *, canvas_id: str | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        cur = self._conn.cursor(); clauses=[]; params=[]
        if canvas_id is not None:
            clauses.append('canvas_id=?'); params.append(canvas_id)
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql='SELECT COUNT(*) FROM canvas_nodes'
        if clauses: sql += ' WHERE ' + ' AND '.join(clauses)
        return int(cur.execute(sql, tuple(params)).fetchone()[0])

    def count_canvas_edges(self, *, canvas_id: str | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        cur = self._conn.cursor(); clauses=[]; params=[]
        if canvas_id is not None:
            clauses.append('canvas_id=?'); params.append(canvas_id)
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql='SELECT COUNT(*) FROM canvas_edges'
        if clauses: sql += ' WHERE ' + ' AND '.join(clauses)
        return int(cur.execute(sql, tuple(params)).fetchone()[0])

    def count_canvas_views(self, *, canvas_id: str | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        cur = self._conn.cursor(); clauses=[]; params=[]
        if canvas_id is not None:
            clauses.append('canvas_id=?'); params.append(canvas_id)
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql='SELECT COUNT(*) FROM canvas_views'
        if clauses: sql += ' WHERE ' + ' AND '.join(clauses)
        return int(cur.execute(sql, tuple(params)).fetchone()[0])

    def count_canvas_presence(self, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        cur = self._conn.cursor(); clauses=[]; params=[]
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql='SELECT COUNT(*) FROM canvas_presence'
        if clauses: sql += ' WHERE ' + ' AND '.join(clauses)
        return int(cur.execute(sql, tuple(params)).fetchone()[0])

    def create_canvas_document(
        self,
        *,
        title: str,
        description: str = '',
        status: str = 'active',
        created_by: str = '',
        metadata: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        canvas_id = str(uuid.uuid4())
        now = time.time()
        cur = self._conn.cursor()
        cur.execute(
            'INSERT INTO canvas_documents(canvas_id, title, description, status, created_by, created_at, updated_at, metadata_json, tenant_id, workspace_id, environment) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            (canvas_id, title, description, status, created_by, now, now, json.dumps(metadata or {}, ensure_ascii=False), tenant_id, workspace_id, environment),
        )
        self._conn.commit()
        return self.get_canvas_document(canvas_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment) or {'canvas_id': canvas_id}

    def list_canvas_documents(self, *, limit: int = 50, status: str | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        cur = self._conn.cursor(); clauses=[]; params=[]
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if status is not None:
            clauses.append('status=?'); params.append(status)
        sql='SELECT canvas_id, title, description, status, created_by, created_at, updated_at, metadata_json, tenant_id, workspace_id, environment FROM canvas_documents'
        if clauses: sql += ' WHERE ' + ' AND '.join(clauses)
        sql += ' ORDER BY updated_at DESC LIMIT ?'; params.append(int(limit))
        return [self._canvas_document_row_to_dict(row) for row in cur.execute(sql, tuple(params)).fetchall()]

    def get_canvas_document(self, canvas_id: str, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any] | None:
        cur = self._conn.cursor(); clauses=['canvas_id=?']; params=[canvas_id]
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        row = cur.execute('SELECT canvas_id, title, description, status, created_by, created_at, updated_at, metadata_json, tenant_id, workspace_id, environment FROM canvas_documents WHERE ' + ' AND '.join(clauses) + ' LIMIT 1', tuple(params)).fetchone()
        return self._canvas_document_row_to_dict(row) if row is not None else None

    def upsert_canvas_node(
        self,
        *,
        canvas_id: str,
        node_id: str | None = None,
        node_type: str,
        label: str,
        position_x: float = 0.0,
        position_y: float = 0.0,
        width: float = 240.0,
        height: float = 120.0,
        data: dict[str, Any] | None = None,
        created_by: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        cur = self._conn.cursor(); now=time.time(); next_id = str(node_id or uuid.uuid4())
        existing = cur.execute('SELECT node_id FROM canvas_nodes WHERE node_id=? LIMIT 1', (next_id,)).fetchone()
        if existing is None:
            cur.execute('INSERT INTO canvas_nodes(node_id, canvas_id, node_type, label, position_x, position_y, width, height, data_json, created_by, created_at, updated_at, tenant_id, workspace_id, environment) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (next_id, canvas_id, node_type, label, float(position_x), float(position_y), float(width), float(height), json.dumps(data or {}, ensure_ascii=False), created_by, now, now, tenant_id, workspace_id, environment))
        else:
            cur.execute('UPDATE canvas_nodes SET canvas_id=?, node_type=?, label=?, position_x=?, position_y=?, width=?, height=?, data_json=?, updated_at=?, tenant_id=?, workspace_id=?, environment=? WHERE node_id=?', (canvas_id, node_type, label, float(position_x), float(position_y), float(width), float(height), json.dumps(data or {}, ensure_ascii=False), now, tenant_id, workspace_id, environment, next_id))
        cur.execute('UPDATE canvas_documents SET updated_at=? WHERE canvas_id=?', (now, canvas_id))
        self._conn.commit()
        return next((item for item in self.list_canvas_nodes(canvas_id=canvas_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment) if item['node_id']==next_id), {'node_id': next_id})

    def list_canvas_nodes(self, *, canvas_id: str, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        cur = self._conn.cursor(); clauses=['canvas_id=?']; params=[canvas_id]
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql='SELECT node_id, canvas_id, node_type, label, position_x, position_y, width, height, data_json, created_by, created_at, updated_at, tenant_id, workspace_id, environment FROM canvas_nodes WHERE ' + ' AND '.join(clauses) + ' ORDER BY updated_at ASC'
        return [self._canvas_node_row_to_dict(row) for row in cur.execute(sql, tuple(params)).fetchall()]

    def upsert_canvas_edge(
        self,
        *,
        canvas_id: str,
        edge_id: str | None = None,
        source_node_id: str,
        target_node_id: str,
        label: str = '',
        edge_type: str = 'default',
        data: dict[str, Any] | None = None,
        created_by: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        cur = self._conn.cursor(); now=time.time(); next_id = str(edge_id or uuid.uuid4())
        existing = cur.execute('SELECT edge_id FROM canvas_edges WHERE edge_id=? LIMIT 1', (next_id,)).fetchone()
        if existing is None:
            cur.execute('INSERT INTO canvas_edges(edge_id, canvas_id, source_node_id, target_node_id, label, edge_type, data_json, created_by, created_at, updated_at, tenant_id, workspace_id, environment) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)', (next_id, canvas_id, source_node_id, target_node_id, label, edge_type, json.dumps(data or {}, ensure_ascii=False), created_by, now, now, tenant_id, workspace_id, environment))
        else:
            cur.execute('UPDATE canvas_edges SET canvas_id=?, source_node_id=?, target_node_id=?, label=?, edge_type=?, data_json=?, updated_at=?, tenant_id=?, workspace_id=?, environment=? WHERE edge_id=?', (canvas_id, source_node_id, target_node_id, label, edge_type, json.dumps(data or {}, ensure_ascii=False), now, tenant_id, workspace_id, environment, next_id))
        cur.execute('UPDATE canvas_documents SET updated_at=? WHERE canvas_id=?', (now, canvas_id))
        self._conn.commit()
        return next((item for item in self.list_canvas_edges(canvas_id=canvas_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment) if item['edge_id']==next_id), {'edge_id': next_id})

    def list_canvas_edges(self, *, canvas_id: str, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        cur = self._conn.cursor(); clauses=['canvas_id=?']; params=[canvas_id]
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql='SELECT edge_id, canvas_id, source_node_id, target_node_id, label, edge_type, data_json, created_by, created_at, updated_at, tenant_id, workspace_id, environment FROM canvas_edges WHERE ' + ' AND '.join(clauses) + ' ORDER BY updated_at ASC'
        return [self._canvas_edge_row_to_dict(row) for row in cur.execute(sql, tuple(params)).fetchall()]

    def save_canvas_view(
        self,
        *,
        canvas_id: str,
        name: str,
        layout: dict[str, Any] | None = None,
        filters: dict[str, Any] | None = None,
        is_default: bool = False,
        created_by: str = '',
        view_id: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        cur = self._conn.cursor(); now=time.time(); next_id=str(view_id or uuid.uuid4())
        if is_default:
            cur.execute('UPDATE canvas_views SET is_default=0 WHERE canvas_id=?', (canvas_id,))
        existing = cur.execute('SELECT view_id FROM canvas_views WHERE view_id=? LIMIT 1', (next_id,)).fetchone()
        if existing is None:
            cur.execute('INSERT INTO canvas_views(view_id, canvas_id, name, layout_json, filters_json, is_default, created_by, created_at, updated_at, tenant_id, workspace_id, environment) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)', (next_id, canvas_id, name, json.dumps(layout or {}, ensure_ascii=False), json.dumps(filters or {}, ensure_ascii=False), 1 if is_default else 0, created_by, now, now, tenant_id, workspace_id, environment))
        else:
            cur.execute('UPDATE canvas_views SET canvas_id=?, name=?, layout_json=?, filters_json=?, is_default=?, updated_at=?, tenant_id=?, workspace_id=?, environment=? WHERE view_id=?', (canvas_id, name, json.dumps(layout or {}, ensure_ascii=False), json.dumps(filters or {}, ensure_ascii=False), 1 if is_default else 0, now, tenant_id, workspace_id, environment, next_id))
        cur.execute('UPDATE canvas_documents SET updated_at=? WHERE canvas_id=?', (now, canvas_id))
        self._conn.commit()
        return next((item for item in self.list_canvas_views(canvas_id=canvas_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment) if item['view_id']==next_id), {'view_id': next_id})

    def list_canvas_views(self, *, canvas_id: str, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        cur = self._conn.cursor(); clauses=['canvas_id=?']; params=[canvas_id]
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql='SELECT view_id, canvas_id, name, layout_json, filters_json, is_default, created_by, created_at, updated_at, tenant_id, workspace_id, environment FROM canvas_views WHERE ' + ' AND '.join(clauses) + ' ORDER BY is_default DESC, updated_at DESC'
        return [self._canvas_view_row_to_dict(row) for row in cur.execute(sql, tuple(params)).fetchall()]

    def upsert_canvas_presence(
        self,
        *,
        canvas_id: str,
        user_key: str,
        cursor_x: float = 0.0,
        cursor_y: float = 0.0,
        selected_node_id: str | None = None,
        status: str = 'active',
        metadata: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        cur = self._conn.cursor(); now=time.time(); presence_id=f"{canvas_id}:{user_key}"
        existing = cur.execute('SELECT presence_id FROM canvas_presence WHERE presence_id=? LIMIT 1', (presence_id,)).fetchone()
        if existing is None:
            cur.execute('INSERT INTO canvas_presence(presence_id, canvas_id, user_key, cursor_x, cursor_y, selected_node_id, status, metadata_json, updated_at, tenant_id, workspace_id, environment) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)', (presence_id, canvas_id, user_key, float(cursor_x), float(cursor_y), selected_node_id, status, json.dumps(metadata or {}, ensure_ascii=False), now, tenant_id, workspace_id, environment))
        else:
            cur.execute('UPDATE canvas_presence SET cursor_x=?, cursor_y=?, selected_node_id=?, status=?, metadata_json=?, updated_at=?, tenant_id=?, workspace_id=?, environment=? WHERE presence_id=?', (float(cursor_x), float(cursor_y), selected_node_id, status, json.dumps(metadata or {}, ensure_ascii=False), now, tenant_id, workspace_id, environment, presence_id))
        self._conn.commit()
        return next((item for item in self.list_canvas_presence(canvas_id=canvas_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment) if item['presence_id']==presence_id), {'presence_id': presence_id})

    def list_canvas_presence(self, *, canvas_id: str, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        cur = self._conn.cursor(); clauses=['canvas_id=?']; params=[canvas_id]
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql='SELECT presence_id, canvas_id, user_key, cursor_x, cursor_y, selected_node_id, status, metadata_json, updated_at, tenant_id, workspace_id, environment FROM canvas_presence WHERE ' + ' AND '.join(clauses) + ' ORDER BY updated_at DESC'
        return [self._canvas_presence_row_to_dict(row) for row in cur.execute(sql, tuple(params)).fetchall()]

    def list_canvas_events(self, *, canvas_id: str, limit: int = 50, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        # Inlined to avoid a cross-domain call into the events table that
        # otherwise lives on AuditStore. We over-fetch by 3x (legacy
        # behavior) and then filter by canvas_id in Python.
        cur = self._conn.cursor()
        clauses: list[str] = ["channel=?"]
        params: list[Any] = ["canvas"]
        scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        over_fetch = max(int(limit or 50), 1) * 3
        sql = (
            "SELECT id, ts, direction, channel, user_id, session_id, payload_json, "
            "tenant_id, workspace_id, environment FROM events WHERE "
            + " AND ".join(clauses)
            + " ORDER BY id DESC LIMIT ?"
        )
        params.append(int(over_fetch))
        rows = cur.execute(sql, tuple(params)).fetchall()
        items: list[dict[str, Any]] = []
        for r in rows:
            try:
                payload = json.loads(r["payload_json"]) if r["payload_json"] else {}
            except Exception:
                payload = {"_raw": r["payload_json"]}
            items.append({
                "id": int(r["id"]),
                "ts": float(r["ts"]),
                "direction": r["direction"],
                "channel": r["channel"],
                "user_id": r["user_id"],
                "session_id": r["session_id"],
                "tenant_id": r["tenant_id"],
                "workspace_id": r["workspace_id"],
                "environment": r["environment"],
                "payload": payload,
            })
        filtered = [item for item in items if str(item.get("session_id") or "") == str(canvas_id)]
        return filtered[: int(limit or 50)]

    def count_canvas_comments(self, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        cur = self._conn.cursor(); clauses=[]; params=[]
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql='SELECT COUNT(*) FROM canvas_comments'
        if clauses: sql += ' WHERE ' + ' AND '.join(clauses)
        return int(cur.execute(sql, tuple(params)).fetchone()[0])

    def count_canvas_snapshots(self, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        cur = self._conn.cursor(); clauses=[]; params=[]
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql='SELECT COUNT(*) FROM canvas_snapshots'
        if clauses: sql += ' WHERE ' + ' AND '.join(clauses)
        return int(cur.execute(sql, tuple(params)).fetchone()[0])

    def count_canvas_presence_events(self, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        cur = self._conn.cursor(); clauses=[]; params=[]
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql='SELECT COUNT(*) FROM canvas_presence_events'
        if clauses: sql += ' WHERE ' + ' AND '.join(clauses)
        return int(cur.execute(sql, tuple(params)).fetchone()[0])

    def create_canvas_comment(
        self,
        *,
        canvas_id: str,
        body: str,
        author: str = '',
        node_id: str | None = None,
        status: str = 'active',
        metadata: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        cur = self._conn.cursor(); now=time.time(); comment_id=str(uuid.uuid4())
        cur.execute('INSERT INTO canvas_comments(comment_id, canvas_id, node_id, body, author, status, metadata_json, created_at, updated_at, tenant_id, workspace_id, environment) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)', (comment_id, canvas_id, node_id, body, author, status, json.dumps(metadata or {}, ensure_ascii=False), now, now, tenant_id, workspace_id, environment))
        cur.execute('UPDATE canvas_documents SET updated_at=? WHERE canvas_id=?', (now, canvas_id))
        self._conn.commit()
        return next((item for item in self.list_canvas_comments(canvas_id=canvas_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment) if item['comment_id']==comment_id), {'comment_id': comment_id})

    def list_canvas_comments(self, *, canvas_id: str, limit: int = 50, status: str | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        cur = self._conn.cursor(); clauses=['canvas_id=?']; params=[canvas_id]
        if status is not None:
            clauses.append('status=?'); params.append(status)
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql='SELECT comment_id, canvas_id, node_id, body, author, status, metadata_json, created_at, updated_at, tenant_id, workspace_id, environment FROM canvas_comments WHERE ' + ' AND '.join(clauses) + ' ORDER BY updated_at DESC LIMIT ?'
        params.append(max(int(limit or 50), 1))
        return [self._canvas_comment_row_to_dict(row) for row in cur.execute(sql, tuple(params)).fetchall()]

    def create_canvas_snapshot(
        self,
        *,
        canvas_id: str,
        snapshot_kind: str = 'manual',
        label: str = '',
        snapshot: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        created_by: str = '',
        view_id: str | None = None,
        share_token: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        cur = self._conn.cursor(); now=time.time(); snapshot_id=str(uuid.uuid4())
        cur.execute('INSERT INTO canvas_snapshots(snapshot_id, canvas_id, snapshot_kind, label, view_id, share_token, snapshot_json, metadata_json, created_by, created_at, tenant_id, workspace_id, environment) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)', (snapshot_id, canvas_id, snapshot_kind, label, view_id, share_token, json.dumps(snapshot or {}, ensure_ascii=False), json.dumps(metadata or {}, ensure_ascii=False), created_by, now, tenant_id, workspace_id, environment))
        cur.execute('UPDATE canvas_documents SET updated_at=? WHERE canvas_id=?', (now, canvas_id))
        self._conn.commit()
        return next((item for item in self.list_canvas_snapshots(canvas_id=canvas_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment) if item['snapshot_id']==snapshot_id), {'snapshot_id': snapshot_id})

    def list_canvas_snapshots(self, *, canvas_id: str, limit: int = 50, snapshot_kind: str | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        cur = self._conn.cursor(); clauses=['canvas_id=?']; params=[canvas_id]
        if snapshot_kind is not None:
            clauses.append('snapshot_kind=?'); params.append(snapshot_kind)
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql='SELECT snapshot_id, canvas_id, snapshot_kind, label, view_id, share_token, snapshot_json, metadata_json, created_by, created_at, tenant_id, workspace_id, environment FROM canvas_snapshots WHERE ' + ' AND '.join(clauses) + ' ORDER BY created_at DESC LIMIT ?'
        params.append(max(int(limit or 50), 1))
        return [self._canvas_snapshot_row_to_dict(row) for row in cur.execute(sql, tuple(params)).fetchall()]

    def get_canvas_snapshot(self, snapshot_id: str, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any] | None:
        cur = self._conn.cursor(); clauses=['snapshot_id=?']; params=[snapshot_id]
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        row = cur.execute('SELECT snapshot_id, canvas_id, snapshot_kind, label, view_id, share_token, snapshot_json, metadata_json, created_by, created_at, tenant_id, workspace_id, environment FROM canvas_snapshots WHERE ' + ' AND '.join(clauses) + ' LIMIT 1', tuple(params)).fetchone()
        return self._canvas_snapshot_row_to_dict(row) if row is not None else None

    def record_canvas_presence_event(
        self,
        *,
        canvas_id: str,
        user_key: str,
        event_type: str = 'presence',
        payload: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        cur = self._conn.cursor(); now=time.time(); presence_event_id=str(uuid.uuid4())
        cur.execute('INSERT INTO canvas_presence_events(presence_event_id, canvas_id, user_key, event_type, payload_json, created_at, tenant_id, workspace_id, environment) VALUES(?,?,?,?,?,?,?,?,?)', (presence_event_id, canvas_id, user_key, event_type, json.dumps(payload or {}, ensure_ascii=False), now, tenant_id, workspace_id, environment))
        self._conn.commit()
        return next((item for item in self.list_canvas_presence_events(canvas_id=canvas_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment) if item['presence_event_id']==presence_event_id), {'presence_event_id': presence_event_id})

    def list_canvas_presence_events(self, *, canvas_id: str, limit: int = 50, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        cur = self._conn.cursor(); clauses=['canvas_id=?']; params=[canvas_id]
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql='SELECT presence_event_id, canvas_id, user_key, event_type, payload_json, created_at, tenant_id, workspace_id, environment FROM canvas_presence_events WHERE ' + ' AND '.join(clauses) + ' ORDER BY created_at DESC LIMIT ?'
        params.append(max(int(limit or 50), 1))
        return [self._canvas_presence_event_row_to_dict(row) for row in cur.execute(sql, tuple(params)).fetchall()]
