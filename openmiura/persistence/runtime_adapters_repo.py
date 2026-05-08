"""Runtime_adaptersRepo: persistence for the runtime_adapters domain of openMiura.

Owns the persistence logic for the runtime_adapters-related tables. The class
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


class RuntimeAdaptersRepo:
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

    def _openclaw_runtime_row_to_dict(self, row: Any) -> dict[str, Any]:
        if row is None:
            return {}
        try:
            capabilities = json.loads(row['capabilities_json'] or '[]')
        except Exception:
            capabilities = []
        try:
            allowed_agents = json.loads(row['allowed_agents_json'] or '[]')
        except Exception:
            allowed_agents = []
        try:
            metadata = json.loads(row['metadata_json'] or '{}')
        except Exception:
            metadata = {}
        return {
            'runtime_id': row['runtime_id'],
            'name': row['name'],
            'base_url': row['base_url'],
            'transport': row['transport'],
            'auth_secret_ref': row['auth_secret_ref'],
            'status': row['status'],
            'capabilities': capabilities,
            'allowed_agents': allowed_agents,
            'metadata': metadata,
            'last_health_at': row['last_health_at'],
            'last_health_status': row['last_health_status'],
            'created_by': row['created_by'],
            'created_at': row['created_at'],
            'updated_at': row['updated_at'],
            'tenant_id': row['tenant_id'],
            'workspace_id': row['workspace_id'],
            'environment': row['environment'],
        }

    def upsert_openclaw_runtime(self, *, runtime_id: str | None = None, name: str, base_url: str, transport: str = 'http', auth_secret_ref: str = '', status: str = 'registered', capabilities: list[str] | None = None, allowed_agents: list[str] | None = None, metadata: dict[str, Any] | None = None, created_by: str = '', tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any]:
        cur = self._conn.cursor()
        runtime_key = str(runtime_id or uuid.uuid4())
        now = time.time()
        existing = cur.execute('SELECT runtime_id FROM openclaw_runtimes WHERE runtime_id=?', (runtime_key,)).fetchone()
        if existing is None:
            cur.execute('INSERT INTO openclaw_runtimes(runtime_id, name, base_url, transport, auth_secret_ref, status, capabilities_json, allowed_agents_json, metadata_json, last_health_at, last_health_status, created_by, created_at, updated_at, tenant_id, workspace_id, environment) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (runtime_key, name, base_url, transport, auth_secret_ref or '', status or 'registered', json.dumps(list(capabilities or []), ensure_ascii=False), json.dumps(list(allowed_agents or []), ensure_ascii=False), json.dumps(metadata or {}, ensure_ascii=False), None, '', created_by or '', now, now, tenant_id, workspace_id, environment))
        else:
            cur.execute('UPDATE openclaw_runtimes SET name=?, base_url=?, transport=?, auth_secret_ref=?, status=?, capabilities_json=?, allowed_agents_json=?, metadata_json=?, updated_at=?, tenant_id=?, workspace_id=?, environment=? WHERE runtime_id=?', (name, base_url, transport, auth_secret_ref or '', status or 'registered', json.dumps(list(capabilities or []), ensure_ascii=False), json.dumps(list(allowed_agents or []), ensure_ascii=False), json.dumps(metadata or {}, ensure_ascii=False), now, tenant_id, workspace_id, environment, runtime_key))
        self._conn.commit()
        row = cur.execute('SELECT runtime_id, name, base_url, transport, auth_secret_ref, status, capabilities_json, allowed_agents_json, metadata_json, last_health_at, last_health_status, created_by, created_at, updated_at, tenant_id, workspace_id, environment FROM openclaw_runtimes WHERE runtime_id=?', (runtime_key,)).fetchone()
        return self._openclaw_runtime_row_to_dict(row)

    def get_openclaw_runtime(self, runtime_id: str, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any] | None:
        cur = self._conn.cursor()
        clauses = ['runtime_id=?']
        params: list[Any] = [runtime_id]
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        row = cur.execute('SELECT runtime_id, name, base_url, transport, auth_secret_ref, status, capabilities_json, allowed_agents_json, metadata_json, last_health_at, last_health_status, created_by, created_at, updated_at, tenant_id, workspace_id, environment FROM openclaw_runtimes WHERE ' + ' AND '.join(clauses) + ' LIMIT 1', tuple(params)).fetchone()
        return self._openclaw_runtime_row_to_dict(row) if row is not None else None

    def list_openclaw_runtimes(self, *, limit: int = 100, status: str | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        if status is not None:
            clauses.append('status=?')
            params.append(status)
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = 'SELECT runtime_id, name, base_url, transport, auth_secret_ref, status, capabilities_json, allowed_agents_json, metadata_json, last_health_at, last_health_status, created_by, created_at, updated_at, tenant_id, workspace_id, environment FROM openclaw_runtimes'
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        sql += ' ORDER BY updated_at DESC LIMIT ?'
        params.append(int(limit))
        return [self._openclaw_runtime_row_to_dict(row) for row in cur.execute(sql, tuple(params)).fetchall()]

    def update_openclaw_runtime_health(
        self,
        runtime_id: str,
        *,
        health_status: str,
        health_at: float | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any] | None:
        cur = self._conn.cursor()
        clauses = ['runtime_id=?']
        params: list[Any] = [runtime_id]
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        current = cur.execute('SELECT runtime_id FROM openclaw_runtimes WHERE ' + ' AND '.join(clauses) + ' LIMIT 1', tuple(params)).fetchone()
        if current is None:
            return None
        now = float(health_at if health_at is not None else time.time())
        cur.execute(
            'UPDATE openclaw_runtimes SET last_health_at=?, last_health_status=?, updated_at=? WHERE runtime_id=?',
            (now, str(health_status or ''), now, runtime_id),
        )
        self._conn.commit()
        row = cur.execute('SELECT runtime_id, name, base_url, transport, auth_secret_ref, status, capabilities_json, allowed_agents_json, metadata_json, last_health_at, last_health_status, created_by, created_at, updated_at, tenant_id, workspace_id, environment FROM openclaw_runtimes WHERE runtime_id=?', (runtime_id,)).fetchone()
        return self._openclaw_runtime_row_to_dict(row) if row is not None else None

    def _openclaw_dispatch_row_to_dict(self, row: Any) -> dict[str, Any]:
        if row is None:
            return {}
        try:
            request_payload = json.loads(row['request_json'] or '{}')
        except Exception:
            request_payload = {}
        try:
            response_payload = json.loads(row['response_json'] or '{}')
        except Exception:
            response_payload = {}
        return {
            'dispatch_id': row['dispatch_id'],
            'runtime_id': row['runtime_id'],
            'action': row['action'],
            'agent_id': row['agent_id'],
            'status': row['status'],
            'request': request_payload,
            'response': response_payload,
            'error_text': row['error_text'],
            'secret_ref': row['secret_ref'],
            'latency_ms': row['latency_ms'],
            'created_by': row['created_by'],
            'created_at': row['created_at'],
            'tenant_id': row['tenant_id'],
            'workspace_id': row['workspace_id'],
            'environment': row['environment'],
        }

    def create_openclaw_dispatch(self, *, runtime_id: str, action: str, agent_id: str = '', status: str = 'pending', request_payload: dict[str, Any] | None = None, response_payload: dict[str, Any] | None = None, secret_ref: str = '', created_by: str = '', tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any]:
        dispatch_id = str(uuid.uuid4())
        now = time.time()
        cur = self._conn.cursor()
        cur.execute('INSERT INTO openclaw_dispatches(dispatch_id, runtime_id, action, agent_id, status, request_json, response_json, error_text, secret_ref, latency_ms, created_by, created_at, tenant_id, workspace_id, environment) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (dispatch_id, runtime_id, action, agent_id or '', status, json.dumps(request_payload or {}, ensure_ascii=False), json.dumps(response_payload or {}, ensure_ascii=False), '', secret_ref or '', None, created_by or '', now, tenant_id, workspace_id, environment))
        self._conn.commit()
        row = cur.execute('SELECT dispatch_id, runtime_id, action, agent_id, status, request_json, response_json, error_text, secret_ref, latency_ms, created_by, created_at, tenant_id, workspace_id, environment FROM openclaw_dispatches WHERE dispatch_id=?', (dispatch_id,)).fetchone()
        return self._openclaw_dispatch_row_to_dict(row)

    def update_openclaw_dispatch(self, dispatch_id: str, *, status: str, response_payload: dict[str, Any] | None = None, error_text: str = '', latency_ms: float | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any] | None:
        cur = self._conn.cursor()
        clauses = ['dispatch_id=?']
        params: list[Any] = [dispatch_id]
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        current = cur.execute('SELECT dispatch_id FROM openclaw_dispatches WHERE ' + ' AND '.join(clauses) + ' LIMIT 1', tuple(params)).fetchone()
        if current is None:
            return None
        cur.execute('UPDATE openclaw_dispatches SET status=?, response_json=?, error_text=?, latency_ms=? WHERE dispatch_id=?', (status, json.dumps(response_payload or {}, ensure_ascii=False), error_text or '', latency_ms, dispatch_id))
        self._conn.commit()
        row = cur.execute('SELECT dispatch_id, runtime_id, action, agent_id, status, request_json, response_json, error_text, secret_ref, latency_ms, created_by, created_at, tenant_id, workspace_id, environment FROM openclaw_dispatches WHERE dispatch_id=?', (dispatch_id,)).fetchone()
        return self._openclaw_dispatch_row_to_dict(row) if row is not None else None

    def get_openclaw_dispatch(self, dispatch_id: str, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any] | None:
        cur = self._conn.cursor()
        clauses = ['dispatch_id=?']
        params: list[Any] = [dispatch_id]
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        row = cur.execute('SELECT dispatch_id, runtime_id, action, agent_id, status, request_json, response_json, error_text, secret_ref, latency_ms, created_by, created_at, tenant_id, workspace_id, environment FROM openclaw_dispatches WHERE ' + ' AND '.join(clauses) + ' LIMIT 1', tuple(params)).fetchone()
        return self._openclaw_dispatch_row_to_dict(row) if row is not None else None

    def list_openclaw_dispatches(self, *, runtime_id: str | None = None, action: str | None = None, status: str | None = None, limit: int = 100, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        if runtime_id is not None:
            clauses.append('runtime_id=?')
            params.append(runtime_id)
        if action is not None:
            clauses.append('action=?')
            params.append(action)
        if status is not None:
            clauses.append('status=?')
            params.append(status)
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = 'SELECT dispatch_id, runtime_id, action, agent_id, status, request_json, response_json, error_text, secret_ref, latency_ms, created_by, created_at, tenant_id, workspace_id, environment FROM openclaw_dispatches'
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        sql += ' ORDER BY created_at DESC LIMIT ?'
        params.append(int(limit))
        return [self._openclaw_dispatch_row_to_dict(row) for row in cur.execute(sql, tuple(params)).fetchall()]

    def count_openclaw_dispatches(self, *, runtime_id: str | None = None, action: str | None = None, status: str | None = None, since_ts: float | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        if runtime_id is not None:
            clauses.append('runtime_id=?')
            params.append(runtime_id)
        if action is not None:
            clauses.append('action=?')
            params.append(action)
        if status is not None:
            clauses.append('status=?')
            params.append(status)
        if since_ts is not None:
            clauses.append('created_at>=?')
            params.append(float(since_ts))
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = 'SELECT COUNT(*) FROM openclaw_dispatches'
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        row = cur.execute(sql, tuple(params)).fetchone()
        return int(row[0] if row is not None else 0)
