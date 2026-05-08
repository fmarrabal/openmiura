"""RuntimeRepo: persistence for the runtime domain of openMiura.

Owns the persistence logic for the runtime-related tables. The class
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


class RuntimeRepo:
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

    def _worker_lease_row_to_dict(self, row: Any) -> dict[str, Any]:
        try:
            metadata = json.loads(row['metadata_json']) if row['metadata_json'] else {}
        except Exception:
            metadata = {}
        return {
            'lease_key': row['lease_key'],
            'holder_id': row['holder_id'],
            'lease_until': float(row['lease_until']),
            'heartbeat_at': float(row['heartbeat_at']),
            'metadata': metadata,
            'created_at': float(row['created_at']),
            'updated_at': float(row['updated_at']),
            'tenant_id': row['tenant_id'],
            'workspace_id': row['workspace_id'],
            'environment': row['environment'],
        }

    def get_worker_lease(self, lease_key: str, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any] | None:
        cur = self._conn.cursor()
        clauses = ['lease_key=?']
        params: list[Any] = [lease_key]
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        row = cur.execute('SELECT lease_key, holder_id, lease_until, heartbeat_at, metadata_json, created_at, updated_at, tenant_id, workspace_id, environment FROM worker_leases WHERE ' + ' AND '.join(clauses), tuple(params)).fetchone()
        return self._worker_lease_row_to_dict(row) if row is not None else None

    def list_worker_leases(self, *, limit: int = 100, active_only: bool | None = None, key_prefix: str | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        if active_only is not None:
            clauses.append('lease_until ' + ('>' if active_only else '<=') + ' ?')
            params.append(time.time())
        if key_prefix:
            clauses.append('lease_key LIKE ?')
            params.append(f"{str(key_prefix)}%")
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = 'SELECT lease_key, holder_id, lease_until, heartbeat_at, metadata_json, created_at, updated_at, tenant_id, workspace_id, environment FROM worker_leases'
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        sql += ' ORDER BY updated_at DESC LIMIT ?'
        params.append(int(limit))
        return [self._worker_lease_row_to_dict(r) for r in cur.execute(sql, tuple(params)).fetchall()]

    def count_worker_leases(self, *, active_only: bool | None = None, key_prefix: str | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        if active_only is not None:
            clauses.append('lease_until ' + ('>' if active_only else '<=') + ' ?')
            params.append(time.time())
        if key_prefix:
            clauses.append('lease_key LIKE ?')
            params.append(f"{str(key_prefix)}%")
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = 'SELECT COUNT(*) FROM worker_leases'
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        return int(cur.execute(sql, tuple(params)).fetchone()[0])

    def acquire_worker_lease(self, *, lease_key: str, holder_id: str, lease_ttl_s: float, metadata: dict[str, Any] | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any]:
        if not str(lease_key or '').strip():
            raise ValueError('lease_key is required')
        if not str(holder_id or '').strip():
            raise ValueError('holder_id is required')
        now = time.time()
        lease_until = now + max(float(lease_ttl_s or 0.0), 1.0)
        payload = json.dumps(dict(metadata or {}), ensure_ascii=False)
        scope = {'tenant_id': tenant_id, 'workspace_id': workspace_id, 'environment': environment}
        current = self.get_worker_lease(str(lease_key).strip(), **scope)
        if current is None:
            cur = self._conn.cursor()
            try:
                cur.execute(
                    'INSERT INTO worker_leases(lease_key, holder_id, lease_until, heartbeat_at, metadata_json, created_at, updated_at, tenant_id, workspace_id, environment) VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (str(lease_key).strip(), str(holder_id).strip(), lease_until, now, payload, now, now, tenant_id, workspace_id, environment),
                )
                self._conn.commit()
                return {'acquired': True, 'lease': self.get_worker_lease(str(lease_key).strip(), **scope)}
            except Exception as exc:
                text = str(exc).lower()
                if 'unique' not in text and 'duplicate' not in text and 'conflict' not in text:
                    raise
        cur = self._conn.cursor()
        clauses = ['lease_key=?', '(holder_id=? OR lease_until<=?)']
        params: list[Any] = [str(holder_id).strip(), lease_until, now, str(lease_key).strip(), str(holder_id).strip(), now]
        # params order must match sets first then where clauses
        clauses = ['lease_key=?', '(holder_id=? OR lease_until<=?)']
        params = [str(holder_id).strip(), lease_until, now, payload, now, str(lease_key).strip(), str(holder_id).strip(), now]
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        cur.execute('UPDATE worker_leases SET holder_id=?, lease_until=?, heartbeat_at=?, metadata_json=?, updated_at=? WHERE ' + ' AND '.join(clauses), tuple(params))
        updated = int(cur.rowcount)
        self._conn.commit()
        lease = self.get_worker_lease(str(lease_key).strip(), **scope)
        return {'acquired': updated == 1, 'lease': lease}

    def renew_worker_lease(self, *, lease_key: str, holder_id: str, lease_ttl_s: float, metadata: dict[str, Any] | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any]:
        now = time.time()
        lease_until = now + max(float(lease_ttl_s or 0.0), 1.0)
        payload = json.dumps(dict(metadata or {}), ensure_ascii=False)
        clauses = ['lease_key=?', 'holder_id=?']
        params: list[Any] = [lease_until, now, payload, now, str(lease_key).strip(), str(holder_id).strip()]
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        cur = self._conn.cursor()
        cur.execute('UPDATE worker_leases SET lease_until=?, heartbeat_at=?, metadata_json=?, updated_at=? WHERE ' + ' AND '.join(clauses), tuple(params))
        updated = int(cur.rowcount)
        self._conn.commit()
        return {'renewed': updated == 1, 'lease': self.get_worker_lease(str(lease_key).strip(), tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)}

    def release_worker_lease(self, lease_key: str, *, holder_id: str | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        clauses = ['lease_key=?']
        params: list[Any] = [str(lease_key).strip()]
        if holder_id is not None:
            clauses.append('holder_id=?')
            params.append(str(holder_id).strip())
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        cur = self._conn.cursor()
        cur.execute('DELETE FROM worker_leases WHERE ' + ' AND '.join(clauses), tuple(params))
        removed = int(cur.rowcount)
        self._conn.commit()
        return removed

    def cleanup_worker_leases(self, *, now: float | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        clauses: list[str] = ['lease_until<=?']
        params: list[Any] = [float(now if now is not None else time.time())]
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        cur = self._conn.cursor()
        cur.execute('DELETE FROM worker_leases WHERE ' + ' AND '.join(clauses), tuple(params))
        removed = int(cur.rowcount)
        self._conn.commit()
        return removed

    def _idempotency_row_to_dict(self, row: Any) -> dict[str, Any]:
        def _loads(raw: Any) -> dict[str, Any]:
            try:
                return json.loads(raw or '{}')
            except Exception:
                return {}
        return {
            'idempotency_key': row['idempotency_key'],
            'scope_kind': row['scope_kind'],
            'status': row['status'],
            'holder_id': row['holder_id'],
            'expires_at': float(row['expires_at']) if row['expires_at'] is not None else None,
            'result': _loads(row['result_json']),
            'metadata': _loads(row['metadata_json']),
            'created_at': float(row['created_at']),
            'updated_at': float(row['updated_at']),
            'tenant_id': row['tenant_id'],
            'workspace_id': row['workspace_id'],
            'environment': row['environment'],
        }

    def list_idempotency_records(self, *, limit: int = 100, active_only: bool | None = None, key_prefix: str | None = None, status: str | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        now = time.time()
        if active_only is True:
            clauses.extend(['status=?', '(expires_at IS NULL OR expires_at>?)'])
            params.extend(['in_progress', now])
        elif active_only is False:
            clauses.append('(status!=? OR (expires_at IS NOT NULL AND expires_at<=?))')
            params.extend(['in_progress', now])
        if key_prefix:
            clauses.append('idempotency_key LIKE ?')
            params.append(f"{str(key_prefix)}%")
        if status:
            clauses.append('status=?')
            params.append(str(status).strip())
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = 'SELECT idempotency_key, scope_kind, status, holder_id, expires_at, result_json, metadata_json, created_at, updated_at, tenant_id, workspace_id, environment FROM idempotency_records'
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        sql += ' ORDER BY updated_at DESC LIMIT ?'
        params.append(int(limit))
        return [self._idempotency_row_to_dict(r) for r in cur.execute(sql, tuple(params)).fetchall()]

    def count_idempotency_records(self, *, active_only: bool | None = None, key_prefix: str | None = None, status: str | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        now = time.time()
        if active_only is True:
            clauses.extend(['status=?', '(expires_at IS NULL OR expires_at>?)'])
            params.extend(['in_progress', now])
        elif active_only is False:
            clauses.append('(status!=? OR (expires_at IS NOT NULL AND expires_at<=?))')
            params.extend(['in_progress', now])
        if key_prefix:
            clauses.append('idempotency_key LIKE ?')
            params.append(f"{str(key_prefix)}%")
        if status:
            clauses.append('status=?')
            params.append(str(status).strip())
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = 'SELECT COUNT(*) FROM idempotency_records'
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        return int(cur.execute(sql, tuple(params)).fetchone()[0])

    def get_idempotency_record(self, idempotency_key: str, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any] | None:
        cur = self._conn.cursor()
        clauses = ['idempotency_key=?']
        params: list[Any] = [str(idempotency_key).strip()]
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        row = cur.execute('SELECT idempotency_key, scope_kind, status, holder_id, expires_at, result_json, metadata_json, created_at, updated_at, tenant_id, workspace_id, environment FROM idempotency_records WHERE ' + ' AND '.join(clauses), tuple(params)).fetchone()
        return self._idempotency_row_to_dict(row) if row is not None else None

    def claim_idempotency_record(self, *, idempotency_key: str, holder_id: str, ttl_s: float, scope_kind: str = '', metadata: dict[str, Any] | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any]:
        if not str(idempotency_key or '').strip():
            raise ValueError('idempotency_key is required')
        if not str(holder_id or '').strip():
            raise ValueError('holder_id is required')
        now = time.time()
        expires_at = now + max(float(ttl_s or 0.0), 1.0)
        result_payload = json.dumps({}, ensure_ascii=False)
        metadata_payload = json.dumps(dict(metadata or {}), ensure_ascii=False)
        scope = {'tenant_id': tenant_id, 'workspace_id': workspace_id, 'environment': environment}
        current = self.get_idempotency_record(str(idempotency_key).strip(), **scope)
        if current is None:
            cur = self._conn.cursor()
            try:
                cur.execute(
                    'INSERT INTO idempotency_records(idempotency_key, scope_kind, status, holder_id, expires_at, result_json, metadata_json, created_at, updated_at, tenant_id, workspace_id, environment) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                    (str(idempotency_key).strip(), str(scope_kind or '').strip(), 'in_progress', str(holder_id).strip(), expires_at, result_payload, metadata_payload, now, now, tenant_id, workspace_id, environment),
                )
                self._conn.commit()
                return {'claimed': True, 'record': self.get_idempotency_record(str(idempotency_key).strip(), **scope)}
            except Exception as exc:
                text = str(exc).lower()
                if 'unique' not in text and 'duplicate' not in text and 'conflict' not in text:
                    raise
        clauses = ['idempotency_key=?', '(holder_id=? OR expires_at IS NULL OR expires_at<=?)']
        params: list[Any] = [str(scope_kind or '').strip(), 'in_progress', str(holder_id).strip(), expires_at, result_payload, metadata_payload, now, str(idempotency_key).strip(), str(holder_id).strip(), now]
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        cur = self._conn.cursor()
        cur.execute('UPDATE idempotency_records SET scope_kind=?, status=?, holder_id=?, expires_at=?, result_json=?, metadata_json=?, updated_at=? WHERE ' + ' AND '.join(clauses), tuple(params))
        claimed = int(cur.rowcount) == 1
        self._conn.commit()
        record = self.get_idempotency_record(str(idempotency_key).strip(), **scope)
        return {'claimed': claimed, 'record': record}

    def complete_idempotency_record(self, idempotency_key: str, *, holder_id: str | None = None, status: str = 'completed', result: dict[str, Any] | None = None, metadata: dict[str, Any] | None = None, ttl_s: float | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any] | None:
        now = time.time()
        expires_at = None if ttl_s is None else now + max(float(ttl_s or 0.0), 1.0)
        sets = ['status=?', 'result_json=?', 'updated_at=?']
        params: list[Any] = [str(status or 'completed').strip(), json.dumps(dict(result or {}), ensure_ascii=False), now]
        if metadata is not None:
            sets.append('metadata_json=?')
            params.append(json.dumps(dict(metadata or {}), ensure_ascii=False))
        if ttl_s is not None:
            sets.append('expires_at=?')
            params.append(expires_at)
        clauses = ['idempotency_key=?']
        params.append(str(idempotency_key).strip())
        if holder_id is not None:
            clauses.append('holder_id=?')
            params.append(str(holder_id).strip())
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        cur = self._conn.cursor()
        cur.execute('UPDATE idempotency_records SET ' + ', '.join(sets) + ' WHERE ' + ' AND '.join(clauses), tuple(params))
        updated = int(cur.rowcount)
        self._conn.commit()
        if updated <= 0:
            return None
        return self.get_idempotency_record(str(idempotency_key).strip(), tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def cleanup_idempotency_records(self, *, now: float | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        clauses: list[str] = ['expires_at IS NOT NULL', 'expires_at<=?']
        params: list[Any] = [float(now if now is not None else time.time())]
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        cur = self._conn.cursor()
        cur.execute('DELETE FROM idempotency_records WHERE ' + ' AND '.join(clauses), tuple(params))
        removed = int(cur.rowcount)
        self._conn.commit()
        return removed

    def _runtime_alert_state_row_to_dict(self, row: Any) -> dict[str, Any]:
        if row is None:
            return {}
        try:
            state = json.loads(row['state_json'] or '{}')
        except Exception:
            state = {}
        return {
            'alert_key': row['alert_key'],
            'runtime_id': row['runtime_id'],
            'alert_code': row['alert_code'],
            'title': row['title'],
            'severity': row['severity'],
            'workflow_status': row['workflow_status'],
            'acked_by': row['acked_by'],
            'acked_at': float(row['acked_at']) if row['acked_at'] is not None else None,
            'silence_until': float(row['silence_until']) if row['silence_until'] is not None else None,
            'silenced_by': row['silenced_by'],
            'silence_reason': row['silence_reason'],
            'escalation_level': int(row['escalation_level'] or 0),
            'escalation_target': row['escalation_target'],
            'escalated_by': row['escalated_by'],
            'escalated_at': float(row['escalated_at']) if row['escalated_at'] is not None else None,
            'state': state,
            'observed_at': float(row['observed_at']),
            'created_at': float(row['created_at']),
            'updated_at': float(row['updated_at']),
            'tenant_id': row['tenant_id'],
            'workspace_id': row['workspace_id'],
            'environment': row['environment'],
        }

    def get_runtime_alert_state(self, *, alert_key: str | None = None, runtime_id: str | None = None, alert_code: str | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any] | None:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        if alert_key:
            clauses.append('alert_key=?')
            params.append(str(alert_key).strip())
        else:
            clauses.extend(['runtime_id=?', 'alert_code=?'])
            params.extend([str(runtime_id or '').strip(), str(alert_code or '').strip()])
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = 'SELECT alert_key, runtime_id, alert_code, title, severity, workflow_status, acked_by, acked_at, silence_until, silenced_by, silence_reason, escalation_level, escalation_target, escalated_by, escalated_at, state_json, observed_at, created_at, updated_at, tenant_id, workspace_id, environment FROM runtime_alert_states WHERE ' + ' AND '.join(clauses) + ' LIMIT 1'
        row = cur.execute(sql, tuple(params)).fetchone()
        return self._runtime_alert_state_row_to_dict(row) if row is not None else None

    def list_runtime_alert_states(self, *, runtime_id: str | None = None, workflow_status: str | None = None, severity: str | None = None, limit: int = 100, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        if runtime_id is not None:
            clauses.append('runtime_id=?')
            params.append(str(runtime_id).strip())
        if workflow_status is not None:
            clauses.append('workflow_status=?')
            params.append(str(workflow_status).strip())
        if severity is not None:
            clauses.append('severity=?')
            params.append(str(severity).strip())
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = 'SELECT alert_key, runtime_id, alert_code, title, severity, workflow_status, acked_by, acked_at, silence_until, silenced_by, silence_reason, escalation_level, escalation_target, escalated_by, escalated_at, state_json, observed_at, created_at, updated_at, tenant_id, workspace_id, environment FROM runtime_alert_states'
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        sql += ' ORDER BY updated_at DESC LIMIT ?'
        params.append(int(limit))
        return [self._runtime_alert_state_row_to_dict(row) for row in cur.execute(sql, tuple(params)).fetchall()]

    def upsert_runtime_alert_state(
        self,
        *,
        alert_key: str,
        runtime_id: str,
        alert_code: str,
        title: str = '',
        severity: str = '',
        workflow_status: str = 'open',
        acked_by: str = '',
        acked_at: float | None = None,
        silence_until: float | None = None,
        silenced_by: str = '',
        silence_reason: str = '',
        escalation_level: int = 0,
        escalation_target: str = '',
        escalated_by: str = '',
        escalated_at: float | None = None,
        state: dict[str, Any] | None = None,
        observed_at: float | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        key = str(alert_key or '').strip()
        if not key:
            raise ValueError('alert_key is required')
        now = time.time()
        observed = float(observed_at if observed_at is not None else now)
        payload = json.dumps(dict(state or {}), ensure_ascii=False)
        current = self.get_runtime_alert_state(alert_key=key, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        cur = self._conn.cursor()
        if current is None:
            cur.execute(
                'INSERT INTO runtime_alert_states(alert_key, runtime_id, alert_code, title, severity, workflow_status, acked_by, acked_at, silence_until, silenced_by, silence_reason, escalation_level, escalation_target, escalated_by, escalated_at, state_json, observed_at, created_at, updated_at, tenant_id, workspace_id, environment) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (key, str(runtime_id or '').strip(), str(alert_code or '').strip(), str(title or '').strip(), str(severity or '').strip(), str(workflow_status or 'open').strip(), str(acked_by or '').strip(), acked_at, silence_until, str(silenced_by or '').strip(), str(silence_reason or '').strip(), int(escalation_level or 0), str(escalation_target or '').strip(), str(escalated_by or '').strip(), escalated_at, payload, observed, now, now, tenant_id, workspace_id, environment),
            )
        else:
            cur.execute(
                'UPDATE runtime_alert_states SET runtime_id=?, alert_code=?, title=?, severity=?, workflow_status=?, acked_by=?, acked_at=?, silence_until=?, silenced_by=?, silence_reason=?, escalation_level=?, escalation_target=?, escalated_by=?, escalated_at=?, state_json=?, observed_at=?, updated_at=? WHERE alert_key=?',
                (str(runtime_id or '').strip(), str(alert_code or '').strip(), str(title or '').strip(), str(severity or '').strip(), str(workflow_status or 'open').strip(), str(acked_by or '').strip(), acked_at, silence_until, str(silenced_by or '').strip(), str(silence_reason or '').strip(), int(escalation_level or 0), str(escalation_target or '').strip(), str(escalated_by or '').strip(), escalated_at, payload, observed, now, key),
            )
        self._conn.commit()
        return self.get_runtime_alert_state(alert_key=key, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment) or {}

    @staticmethod
    def _runtime_governance_policy_version_row_to_dict(row: Any) -> dict[str, Any]:
        if row is None:
            return {}
        try:
            policy_payload = json.loads(row['policy_json'] or '{}')
        except Exception:
            policy_payload = {}
        try:
            previous_policy = json.loads(row['previous_policy_json'] or '{}')
        except Exception:
            previous_policy = {}
        try:
            diff_payload = json.loads(row['diff_json'] or '{}')
        except Exception:
            diff_payload = {}
        try:
            simulation_payload = json.loads(row['simulation_json'] or '{}')
        except Exception:
            simulation_payload = {}
        return {
            'version_id': row['version_id'],
            'runtime_id': row['runtime_id'],
            'policy_kind': row['policy_kind'],
            'version_no': int(row['version_no'] or 0),
            'version_label': row['version_label'],
            'change_kind': row['change_kind'],
            'status': row['status'],
            'based_on_version_id': row['based_on_version_id'],
            'rollback_of_version_id': row['rollback_of_version_id'],
            'activated_by': row['activated_by'],
            'activation_reason': row['activation_reason'],
            'policy': policy_payload,
            'previous_policy': previous_policy,
            'diff': diff_payload,
            'simulation': simulation_payload,
            'created_at': float(row['created_at']),
            'activated_at': float(row['activated_at']) if row['activated_at'] is not None else None,
            'updated_at': float(row['updated_at']),
            'tenant_id': row['tenant_id'],
            'workspace_id': row['workspace_id'],
            'environment': row['environment'],
        }

    def get_runtime_governance_policy_version(self, version_id: str, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any] | None:
        key = str(version_id or '').strip()
        if not key:
            return None
        cur = self._conn.cursor()
        clauses = ['version_id=?']
        params: list[Any] = [key]
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        row = cur.execute('SELECT version_id, runtime_id, policy_kind, version_no, version_label, change_kind, status, based_on_version_id, rollback_of_version_id, activated_by, activation_reason, policy_json, previous_policy_json, diff_json, simulation_json, created_at, activated_at, updated_at, tenant_id, workspace_id, environment FROM runtime_governance_policy_versions WHERE ' + ' AND '.join(clauses) + ' LIMIT 1', tuple(params)).fetchone()
        return self._runtime_governance_policy_version_row_to_dict(row) if row is not None else None

    def list_runtime_governance_policy_versions(self, *, runtime_id: str | None = None, policy_kind: str | None = None, status: str | None = None, limit: int = 100, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        if runtime_id is not None:
            clauses.append('runtime_id=?')
            params.append(str(runtime_id).strip())
        if policy_kind is not None:
            clauses.append('policy_kind=?')
            params.append(str(policy_kind).strip())
        if status is not None:
            clauses.append('status=?')
            params.append(str(status).strip())
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = 'SELECT version_id, runtime_id, policy_kind, version_no, version_label, change_kind, status, based_on_version_id, rollback_of_version_id, activated_by, activation_reason, policy_json, previous_policy_json, diff_json, simulation_json, created_at, activated_at, updated_at, tenant_id, workspace_id, environment FROM runtime_governance_policy_versions'
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        sql += ' ORDER BY version_no DESC, updated_at DESC LIMIT ?'
        params.append(int(limit))
        return [self._runtime_governance_policy_version_row_to_dict(row) for row in cur.execute(sql, tuple(params)).fetchall()]

    def count_runtime_governance_policy_versions(self, *, runtime_id: str | None = None, policy_kind: str | None = None, status: str | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        if runtime_id is not None:
            clauses.append('runtime_id=?')
            params.append(str(runtime_id).strip())
        if policy_kind is not None:
            clauses.append('policy_kind=?')
            params.append(str(policy_kind).strip())
        if status is not None:
            clauses.append('status=?')
            params.append(str(status).strip())
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = 'SELECT COUNT(*) FROM runtime_governance_policy_versions'
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        row = cur.execute(sql, tuple(params)).fetchone()
        return int(row[0] if row is not None else 0)

    def create_runtime_governance_policy_version(
        self,
        *,
        version_id: str,
        runtime_id: str,
        policy_kind: str = 'alert_governance',
        version_no: int = 1,
        version_label: str = '',
        change_kind: str = 'activation',
        status: str = 'active',
        based_on_version_id: str = '',
        rollback_of_version_id: str = '',
        activated_by: str = '',
        activation_reason: str = '',
        policy: dict[str, Any] | None = None,
        previous_policy: dict[str, Any] | None = None,
        diff: dict[str, Any] | None = None,
        simulation: dict[str, Any] | None = None,
        activated_at: float | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        key = str(version_id or '').strip()
        if not key:
            raise ValueError('version_id is required')
        now = time.time()
        cur = self._conn.cursor()
        cur.execute(
            'INSERT INTO runtime_governance_policy_versions(version_id, runtime_id, policy_kind, version_no, version_label, change_kind, status, based_on_version_id, rollback_of_version_id, activated_by, activation_reason, policy_json, previous_policy_json, diff_json, simulation_json, created_at, activated_at, updated_at, tenant_id, workspace_id, environment) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (key, str(runtime_id or '').strip(), str(policy_kind or 'alert_governance').strip(), int(version_no or 1), str(version_label or '').strip(), str(change_kind or 'activation').strip(), str(status or 'active').strip(), str(based_on_version_id or '').strip(), str(rollback_of_version_id or '').strip(), str(activated_by or '').strip(), str(activation_reason or '').strip(), json.dumps(dict(policy or {}), ensure_ascii=False), json.dumps(dict(previous_policy or {}), ensure_ascii=False), json.dumps(dict(diff or {}), ensure_ascii=False), json.dumps(dict(simulation or {}), ensure_ascii=False), now, activated_at, now, tenant_id, workspace_id, environment),
        )
        self._conn.commit()
        return self.get_runtime_governance_policy_version(key, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment) or {}

    def update_runtime_governance_policy_version(self, version_id: str, *, status: str | None = None, activated_at: float | None = None, activation_reason: str | None = None, simulation: dict[str, Any] | None = None) -> dict[str, Any] | None:
        key = str(version_id or '').strip()
        if not key:
            return None
        current = self.get_runtime_governance_policy_version(key)
        if current is None:
            return None
        next_status = str(status if status is not None else current.get('status') or '').strip() or str(current.get('status') or 'active')
        next_activated_at = activated_at if activated_at is not None else current.get('activated_at')
        next_reason = str(activation_reason) if activation_reason is not None else str(current.get('activation_reason') or '')
        next_simulation = dict(current.get('simulation') or {})
        if simulation is not None:
            next_simulation = dict(simulation or {})
        now = time.time()
        cur = self._conn.cursor()
        cur.execute(
            'UPDATE runtime_governance_policy_versions SET status=?, activated_at=?, activation_reason=?, simulation_json=?, updated_at=? WHERE version_id=?',
            (next_status, next_activated_at, next_reason, json.dumps(next_simulation, ensure_ascii=False), now, key),
        )
        self._conn.commit()
        return self.get_runtime_governance_policy_version(key)

    def mark_runtime_governance_policy_versions(self, *, runtime_id: str, policy_kind: str = 'alert_governance', from_status: str | None = None, to_status: str = 'superseded', exclude_version_id: str | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        cur = self._conn.cursor()
        clauses = ['runtime_id=?', 'policy_kind=?']
        params: list[Any] = [str(runtime_id or '').strip(), str(policy_kind or 'alert_governance').strip()]
        if from_status is not None:
            clauses.append('status=?')
            params.append(str(from_status).strip())
        if exclude_version_id is not None:
            clauses.append('version_id<>?')
            params.append(str(exclude_version_id).strip())
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = 'UPDATE runtime_governance_policy_versions SET status=?, updated_at=? WHERE ' + ' AND '.join(clauses)
        now = time.time()
        params = [str(to_status or 'superseded').strip(), now, *params]
        cur.execute(sql, tuple(params))
        self._conn.commit()
        return int(cur.rowcount or 0)

    def latest_runtime_governance_policy_version(self, *, runtime_id: str, policy_kind: str = 'alert_governance', tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any] | None:
        items = self.list_runtime_governance_policy_versions(runtime_id=runtime_id, policy_kind=policy_kind, limit=1, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        return items[0] if items else None

    @staticmethod
    def _runtime_alert_notification_dispatch_row_to_dict(row: Any) -> dict[str, Any]:
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
            'notification_dispatch_id': row['notification_dispatch_id'],
            'alert_key': row['alert_key'],
            'runtime_id': row['runtime_id'],
            'alert_code': row['alert_code'],
            'target_id': row['target_id'],
            'target_type': row['target_type'],
            'workflow_action': row['workflow_action'],
            'severity': row['severity'],
            'escalation_level': int(row['escalation_level'] or 0),
            'delivery_status': row['delivery_status'],
            'request': request_payload,
            'response': response_payload,
            'error_text': row['error_text'],
            'created_by': row['created_by'],
            'delivered_at': float(row['delivered_at']) if row['delivered_at'] is not None else None,
            'created_at': float(row['created_at']),
            'updated_at': float(row['updated_at']),
            'tenant_id': row['tenant_id'],
            'workspace_id': row['workspace_id'],
            'environment': row['environment'],
        }

    def create_runtime_alert_notification_dispatch(
        self,
        *,
        notification_dispatch_id: str,
        alert_key: str,
        runtime_id: str,
        alert_code: str,
        target_id: str,
        target_type: str,
        workflow_action: str = '',
        severity: str = '',
        escalation_level: int = 0,
        delivery_status: str = 'queued',
        request: dict[str, Any] | None = None,
        response: dict[str, Any] | None = None,
        error_text: str = '',
        created_by: str = '',
        delivered_at: float | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        dispatch_id = str(notification_dispatch_id or '').strip()
        if not dispatch_id:
            raise ValueError('notification_dispatch_id is required')
        now = time.time()
        cur = self._conn.cursor()
        cur.execute(
            'INSERT INTO runtime_alert_notification_dispatches(notification_dispatch_id, alert_key, runtime_id, alert_code, target_id, target_type, workflow_action, severity, escalation_level, delivery_status, request_json, response_json, error_text, created_by, delivered_at, created_at, updated_at, tenant_id, workspace_id, environment) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (dispatch_id, str(alert_key or '').strip(), str(runtime_id or '').strip(), str(alert_code or '').strip(), str(target_id or '').strip(), str(target_type or '').strip(), str(workflow_action or '').strip(), str(severity or '').strip(), int(escalation_level or 0), str(delivery_status or 'queued').strip(), json.dumps(dict(request or {}), ensure_ascii=False), json.dumps(dict(response or {}), ensure_ascii=False), str(error_text or '').strip(), str(created_by or '').strip(), delivered_at, now, now, tenant_id, workspace_id, environment),
        )
        self._conn.commit()
        row = cur.execute('SELECT notification_dispatch_id, alert_key, runtime_id, alert_code, target_id, target_type, workflow_action, severity, escalation_level, delivery_status, request_json, response_json, error_text, created_by, delivered_at, created_at, updated_at, tenant_id, workspace_id, environment FROM runtime_alert_notification_dispatches WHERE notification_dispatch_id=?', (dispatch_id,)).fetchone()
        return self._runtime_alert_notification_dispatch_row_to_dict(row)

    def update_runtime_alert_notification_dispatch(
        self,
        notification_dispatch_id: str,
        *,
        delivery_status: str | None = None,
        response: dict[str, Any] | None = None,
        error_text: str | None = None,
        delivered_at: float | None = None,
    ) -> dict[str, Any] | None:
        dispatch_id = str(notification_dispatch_id or '').strip()
        if not dispatch_id:
            return None
        current = self.get_runtime_alert_notification_dispatch(dispatch_id)
        if current is None:
            return None
        next_response = dict(current.get('response') or {})
        if response is not None:
            next_response = dict(response or {})
        next_status = str(delivery_status or current.get('delivery_status') or '').strip() or current.get('delivery_status') or 'queued'
        next_error = str(error_text) if error_text is not None else str(current.get('error_text') or '')
        next_delivered_at = delivered_at if delivered_at is not None else current.get('delivered_at')
        now = time.time()
        cur = self._conn.cursor()
        cur.execute(
            'UPDATE runtime_alert_notification_dispatches SET delivery_status=?, response_json=?, error_text=?, delivered_at=?, updated_at=? WHERE notification_dispatch_id=?',
            (next_status, json.dumps(next_response, ensure_ascii=False), next_error, next_delivered_at, now, dispatch_id),
        )
        self._conn.commit()
        return self.get_runtime_alert_notification_dispatch(dispatch_id)

    def get_runtime_alert_notification_dispatch(self, notification_dispatch_id: str) -> dict[str, Any] | None:
        dispatch_id = str(notification_dispatch_id or '').strip()
        if not dispatch_id:
            return None
        cur = self._conn.cursor()
        row = cur.execute('SELECT notification_dispatch_id, alert_key, runtime_id, alert_code, target_id, target_type, workflow_action, severity, escalation_level, delivery_status, request_json, response_json, error_text, created_by, delivered_at, created_at, updated_at, tenant_id, workspace_id, environment FROM runtime_alert_notification_dispatches WHERE notification_dispatch_id=? LIMIT 1', (dispatch_id,)).fetchone()
        return self._runtime_alert_notification_dispatch_row_to_dict(row) if row is not None else None

    def list_runtime_alert_notification_dispatches(self, *, runtime_id: str | None = None, alert_code: str | None = None, alert_key: str | None = None, target_id: str | None = None, target_type: str | None = None, delivery_status: str | None = None, workflow_action: str | None = None, limit: int = 100, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        if runtime_id is not None:
            clauses.append('runtime_id=?')
            params.append(str(runtime_id).strip())
        if alert_code is not None:
            clauses.append('alert_code=?')
            params.append(str(alert_code).strip())
        if alert_key is not None:
            clauses.append('alert_key=?')
            params.append(str(alert_key).strip())
        if target_id is not None:
            clauses.append('target_id=?')
            params.append(str(target_id).strip())
        if target_type is not None:
            clauses.append('target_type=?')
            params.append(str(target_type).strip())
        if delivery_status is not None:
            clauses.append('delivery_status=?')
            params.append(str(delivery_status).strip())
        if workflow_action is not None:
            clauses.append('workflow_action=?')
            params.append(str(workflow_action).strip())
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = 'SELECT notification_dispatch_id, alert_key, runtime_id, alert_code, target_id, target_type, workflow_action, severity, escalation_level, delivery_status, request_json, response_json, error_text, created_by, delivered_at, created_at, updated_at, tenant_id, workspace_id, environment FROM runtime_alert_notification_dispatches'
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        sql += ' ORDER BY created_at DESC LIMIT ?'
        params.append(int(limit))
        return [self._runtime_alert_notification_dispatch_row_to_dict(row) for row in cur.execute(sql, tuple(params)).fetchall()]
