"""AppsRepo: persistence for the apps domain of openMiura.

Owns the persistence logic for the apps-related tables. The class
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


class AppsRepo:
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

    def _app_installation_row_to_dict(self, row: Any) -> dict[str, Any]:
        try:
            metadata = json.loads(row['metadata_json'] or '{}')
        except Exception:
            metadata = {}
        return {
            'installation_id': row['installation_id'],
            'user_key': row['user_key'] or '',
            'platform': row['platform'] or 'pwa',
            'device_label': row['device_label'] or '',
            'status': row['status'] or 'active',
            'push_capable': bool(row['push_capable']),
            'notification_permission': row['notification_permission'] or 'default',
            'deep_link_base': row['deep_link_base'] or '/ui/',
            'created_at': float(row['created_at']),
            'updated_at': float(row['updated_at']),
            'last_seen_at': float(row['last_seen_at']) if row['last_seen_at'] is not None else None,
            'metadata': metadata,
            'tenant_id': row['tenant_id'],
            'workspace_id': row['workspace_id'],
            'environment': row['environment'],
        }

    def _app_notification_row_to_dict(self, row: Any) -> dict[str, Any]:
        try:
            metadata = json.loads(row['metadata_json'] or '{}')
        except Exception:
            metadata = {}
        return {
            'notification_id': row['notification_id'],
            'installation_id': row['installation_id'] or '',
            'category': row['category'] or 'operator',
            'title': row['title'] or '',
            'body': row['body'] or '',
            'target_path': row['target_path'] or '/ui/?tab=operator',
            'status': row['status'] or 'ready',
            'created_by': row['created_by'] or '',
            'created_at': float(row['created_at']),
            'delivered_at': float(row['delivered_at']) if row['delivered_at'] is not None else None,
            'metadata': metadata,
            'tenant_id': row['tenant_id'],
            'workspace_id': row['workspace_id'],
            'environment': row['environment'],
        }

    def _app_deep_link_row_to_dict(self, row: Any) -> dict[str, Any]:
        try:
            params = json.loads(row['target_params_json'] or '{}')
        except Exception:
            params = {}
        try:
            metadata = json.loads(row['metadata_json'] or '{}')
        except Exception:
            metadata = {}
        return {
            'link_token': row['link_token'],
            'view': row['view'] or 'operator',
            'target_type': row['target_type'] or 'record',
            'target_id': row['target_id'] or '',
            'target_params': params,
            'status': row['status'] or 'active',
            'created_by': row['created_by'] or '',
            'created_at': float(row['created_at']),
            'updated_at': float(row['updated_at']),
            'expires_at': float(row['expires_at']) if row['expires_at'] is not None else None,
            'resolved_at': float(row['resolved_at']) if row['resolved_at'] is not None else None,
            'metadata': metadata,
            'tenant_id': row['tenant_id'],
            'workspace_id': row['workspace_id'],
            'environment': row['environment'],
        }

    def count_app_installations(self, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = 'SELECT COUNT(*) FROM app_installations'
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        return int(cur.execute(sql, tuple(params)).fetchone()[0])

    def count_app_notifications(self, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = 'SELECT COUNT(*) FROM app_notifications'
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        return int(cur.execute(sql, tuple(params)).fetchone()[0])

    def count_app_deep_links(self, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = 'SELECT COUNT(*) FROM app_deep_links'
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        return int(cur.execute(sql, tuple(params)).fetchone()[0])

    def register_app_installation(
        self,
        *,
        user_key: str,
        platform: str = 'pwa',
        device_label: str = '',
        status: str = 'active',
        push_capable: bool = False,
        notification_permission: str = 'default',
        deep_link_base: str = '/ui/',
        metadata: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        installation_id = str(uuid.uuid4())
        now = time.time()
        cur = self._conn.cursor()
        cur.execute(
            'INSERT INTO app_installations(installation_id, user_key, platform, device_label, status, push_capable, notification_permission, deep_link_base, created_at, updated_at, last_seen_at, metadata_json, tenant_id, workspace_id, environment) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (installation_id, user_key, platform, device_label, status, 1 if push_capable else 0, notification_permission, deep_link_base, now, now, now, json.dumps(metadata or {}, ensure_ascii=False), tenant_id, workspace_id, environment),
        )
        self._conn.commit()
        row = cur.execute('SELECT installation_id, user_key, platform, device_label, status, push_capable, notification_permission, deep_link_base, created_at, updated_at, last_seen_at, metadata_json, tenant_id, workspace_id, environment FROM app_installations WHERE installation_id=?', (installation_id,)).fetchone()
        return self._app_installation_row_to_dict(row)

    def list_app_installations(self, *, limit: int = 50, status: str | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if status is not None:
            clauses.append('status=?')
            params.append(status)
        sql = 'SELECT installation_id, user_key, platform, device_label, status, push_capable, notification_permission, deep_link_base, created_at, updated_at, last_seen_at, metadata_json, tenant_id, workspace_id, environment FROM app_installations'
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        sql += ' ORDER BY updated_at DESC LIMIT ?'
        params.append(int(limit))
        return [self._app_installation_row_to_dict(row) for row in cur.execute(sql, tuple(params)).fetchall()]

    def create_app_notification(
        self,
        *,
        installation_id: str | None = None,
        category: str = 'operator',
        title: str,
        body: str = '',
        target_path: str = '/ui/?tab=operator',
        status: str = 'ready',
        created_by: str = '',
        metadata: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        notification_id = str(uuid.uuid4())
        now = time.time()
        cur = self._conn.cursor()
        cur.execute(
            'INSERT INTO app_notifications(notification_id, installation_id, category, title, body, target_path, status, created_by, created_at, delivered_at, metadata_json, tenant_id, workspace_id, environment) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (notification_id, installation_id, category, title, body, target_path, status, created_by, now, None, json.dumps(metadata or {}, ensure_ascii=False), tenant_id, workspace_id, environment),
        )
        self._conn.commit()
        row = cur.execute('SELECT notification_id, installation_id, category, title, body, target_path, status, created_by, created_at, delivered_at, metadata_json, tenant_id, workspace_id, environment FROM app_notifications WHERE notification_id=?', (notification_id,)).fetchone()
        return self._app_notification_row_to_dict(row)

    def list_app_notifications(self, *, limit: int = 50, installation_id: str | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if installation_id is not None:
            clauses.append('installation_id=?')
            params.append(installation_id)
        sql = 'SELECT notification_id, installation_id, category, title, body, target_path, status, created_by, created_at, delivered_at, metadata_json, tenant_id, workspace_id, environment FROM app_notifications'
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        sql += ' ORDER BY created_at DESC LIMIT ?'
        params.append(int(limit))
        return [self._app_notification_row_to_dict(row) for row in cur.execute(sql, tuple(params)).fetchall()]

    def create_app_deep_link(
        self,
        *,
        view: str,
        target_type: str,
        target_id: str,
        target_params: dict[str, Any] | None = None,
        status: str = 'active',
        created_by: str = '',
        expires_at: float | None = None,
        metadata: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        link_token = secrets.token_urlsafe(18)
        now = time.time()
        cur = self._conn.cursor()
        cur.execute(
            'INSERT INTO app_deep_links(link_token, view, target_type, target_id, target_params_json, status, created_by, created_at, updated_at, expires_at, resolved_at, metadata_json, tenant_id, workspace_id, environment) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (link_token, view, target_type, target_id, json.dumps(target_params or {}, ensure_ascii=False), status, created_by, now, now, expires_at, None, json.dumps(metadata or {}, ensure_ascii=False), tenant_id, workspace_id, environment),
        )
        self._conn.commit()
        row = cur.execute('SELECT link_token, view, target_type, target_id, target_params_json, status, created_by, created_at, updated_at, expires_at, resolved_at, metadata_json, tenant_id, workspace_id, environment FROM app_deep_links WHERE link_token=?', (link_token,)).fetchone()
        return self._app_deep_link_row_to_dict(row)

    def list_app_deep_links(self, *, limit: int = 50, status: str | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if status is not None:
            clauses.append('status=?')
            params.append(status)
        sql = 'SELECT link_token, view, target_type, target_id, target_params_json, status, created_by, created_at, updated_at, expires_at, resolved_at, metadata_json, tenant_id, workspace_id, environment FROM app_deep_links'
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        sql += ' ORDER BY updated_at DESC LIMIT ?'
        params.append(int(limit))
        return [self._app_deep_link_row_to_dict(row) for row in cur.execute(sql, tuple(params)).fetchall()]

    def get_app_deep_link(self, link_token: str) -> dict[str, Any] | None:
        cur = self._conn.cursor()
        row = cur.execute('SELECT link_token, view, target_type, target_id, target_params_json, status, created_by, created_at, updated_at, expires_at, resolved_at, metadata_json, tenant_id, workspace_id, environment FROM app_deep_links WHERE link_token=? LIMIT 1', (link_token,)).fetchone()
        return self._app_deep_link_row_to_dict(row) if row is not None else None

    def resolve_app_deep_link(self, link_token: str) -> dict[str, Any] | None:
        current = self.get_app_deep_link(link_token)
        if current is None:
            return None
        now = time.time()
        next_status = current.get('status') or 'active'
        if current.get('expires_at') is not None and float(current['expires_at']) < now:
            next_status = 'expired'
        cur = self._conn.cursor()
        cur.execute('UPDATE app_deep_links SET status=?, updated_at=?, resolved_at=? WHERE link_token=?', (next_status, now, now if next_status != 'expired' else current.get('resolved_at'), link_token))
        self._conn.commit()
        return self.get_app_deep_link(link_token)
