"""WorkflowsRepo: persistence for the workflows domain of openMiura.

Owns the persistence logic for the workflows-related tables. The class
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


class WorkflowsRepo:
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

    def _workflow_row_to_dict(self, row: CompatRow | Any) -> dict[str, Any]:
        try:
            definition = json.loads(row['definition_json']) if row['definition_json'] else {}
        except Exception:
            definition = {'_raw': row['definition_json']}
        try:
            input_payload = json.loads(row['input_json']) if row['input_json'] else {}
        except Exception:
            input_payload = {'_raw': row['input_json']}
        try:
            context = json.loads(row['context_json']) if row['context_json'] else {}
        except Exception:
            context = {'_raw': row['context_json']}
        return {
            'workflow_id': row['workflow_id'],
            'name': row['name'],
            'status': row['status'],
            'created_by': row['created_by'],
            'definition': definition,
            'input': input_payload,
            'context': context,
            'current_step_index': int(row['current_step_index'] or 0),
            'current_step_id': row['current_step_id'],
            'waiting_for_approval': bool(row['waiting_for_approval']),
            'created_at': float(row['created_at']),
            'updated_at': float(row['updated_at']),
            'started_at': float(row['started_at']) if row['started_at'] is not None else None,
            'finished_at': float(row['finished_at']) if row['finished_at'] is not None else None,
            'error': row['error'] or '',
            'source_job_id': row['source_job_id'],
            'playbook_id': row['playbook_id'],
            'tenant_id': row['tenant_id'],
            'workspace_id': row['workspace_id'],
            'environment': row['environment'],
        }

    def create_workflow(
        self,
        *,
        name: str,
        definition: dict[str, Any],
        created_by: str,
        input_payload: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        source_job_id: str | None = None,
        playbook_id: str | None = None,
    ) -> dict[str, Any]:
        workflow_id = str(uuid.uuid4())
        now = time.time()
        cur = self._conn.cursor()
        cur.execute(
            "INSERT INTO workflows(workflow_id, name, status, created_by, definition_json, input_json, context_json, current_step_index, current_step_id, waiting_for_approval, created_at, updated_at, started_at, finished_at, error, source_job_id, playbook_id, tenant_id, workspace_id, environment) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                workflow_id,
                name,
                'created',
                created_by,
                json.dumps(definition or {}, ensure_ascii=False),
                json.dumps(input_payload or {}, ensure_ascii=False),
                json.dumps(context or {}, ensure_ascii=False),
                0,
                None,
                0,
                now,
                now,
                None,
                None,
                '',
                source_job_id,
                playbook_id,
                tenant_id,
                workspace_id,
                environment,
            ),
        )
        self._conn.commit()
        return self.get_workflow(workflow_id) or {'workflow_id': workflow_id, 'name': name}

    def get_workflow(self, workflow_id: str, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any] | None:
        cur = self._conn.cursor()
        clauses = ['workflow_id=?']
        params: list[Any] = [workflow_id]
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        row = cur.execute(
            'SELECT workflow_id, name, status, created_by, definition_json, input_json, context_json, current_step_index, current_step_id, waiting_for_approval, created_at, updated_at, started_at, finished_at, error, source_job_id, playbook_id, tenant_id, workspace_id, environment FROM workflows WHERE ' + ' AND '.join(clauses),
            tuple(params),
        ).fetchone()
        if row is None:
            return None
        return self._workflow_row_to_dict(row)

    def list_workflows(self, *, limit: int = 50, status: str | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        if status is not None:
            clauses.append('status=?')
            params.append(status)
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = 'SELECT workflow_id, name, status, created_by, definition_json, input_json, context_json, current_step_index, current_step_id, waiting_for_approval, created_at, updated_at, started_at, finished_at, error, source_job_id, playbook_id, tenant_id, workspace_id, environment FROM workflows'
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        sql += ' ORDER BY created_at DESC LIMIT ?'
        params.append(int(limit))
        rows = cur.execute(sql, tuple(params)).fetchall()
        return [self._workflow_row_to_dict(r) for r in rows]

    def update_workflow_state(self, workflow_id: str, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None, **updates: Any) -> int:
        allowed = {
            'name': 'name',
            'status': 'status',
            'context': 'context_json',
            'current_step_index': 'current_step_index',
            'current_step_id': 'current_step_id',
            'waiting_for_approval': 'waiting_for_approval',
            'updated_at': 'updated_at',
            'started_at': 'started_at',
            'finished_at': 'finished_at',
            'error': 'error',
            'source_job_id': 'source_job_id',
            'playbook_id': 'playbook_id',
        }
        sets: list[str] = []
        params: list[Any] = []
        for key, column in allowed.items():
            if key not in updates:
                continue
            value = updates[key]
            if key == 'context':
                value = json.dumps(value or {}, ensure_ascii=False)
            if key == 'waiting_for_approval':
                value = 1 if bool(value) else 0
            sets.append(f'{column}=?')
            params.append(value)
        if not sets:
            return 0
        clauses = ['workflow_id=?']
        params.append(workflow_id)
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        cur = self._conn.cursor()
        cur.execute('UPDATE workflows SET ' + ', '.join(sets) + ' WHERE ' + ' AND '.join(clauses), tuple(params))
        updated = cur.rowcount
        self._conn.commit()
        return int(updated)

    def _approval_row_to_dict(self, row: CompatRow | Any) -> dict[str, Any]:
        try:
            payload = json.loads(row['payload_json']) if row['payload_json'] else {}
        except Exception:
            payload = {'_raw': row['payload_json']}
        return {
            'approval_id': row['approval_id'],
            'workflow_id': row['workflow_id'],
            'step_id': row['step_id'],
            'requested_role': row['requested_role'],
            'requested_by': row['requested_by'],
            'status': row['status'],
            'reason': row['reason'] or '',
            'payload': payload,
            'created_at': float(row['created_at']),
            'updated_at': float(row['updated_at']),
            'expires_at': float(row['expires_at']) if row['expires_at'] is not None else None,
            'decided_at': float(row['decided_at']) if row['decided_at'] is not None else None,
            'decided_by': row['decided_by'],
            'assigned_to': row['assigned_to'] if 'assigned_to' in row.keys() else None,
            'claimed_at': float(row['claimed_at']) if ('claimed_at' in row.keys() and row['claimed_at'] is not None) else None,
            'tenant_id': row['tenant_id'],
            'workspace_id': row['workspace_id'],
            'environment': row['environment'],
        }

    def create_approval(self, *, workflow_id: str, step_id: str, requested_role: str, requested_by: str, payload: dict[str, Any] | None = None, expires_at: float | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any]:
        approval_id = str(uuid.uuid4())
        now = time.time()
        cur = self._conn.cursor()
        cur.execute(
            'INSERT INTO approvals(approval_id, workflow_id, step_id, requested_role, requested_by, status, reason, payload_json, created_at, updated_at, expires_at, decided_at, decided_by, assigned_to, claimed_at, tenant_id, workspace_id, environment) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (
                approval_id,
                workflow_id,
                step_id,
                requested_role,
                requested_by,
                'pending',
                '',
                json.dumps(payload or {}, ensure_ascii=False),
                now,
                now,
                expires_at,
                None,
                None,
                None,
                None,
                tenant_id,
                workspace_id,
                environment,
            ),
        )
        self._conn.commit()
        return self.get_approval(approval_id) or {'approval_id': approval_id}

    def get_pending_approval_for_step(self, workflow_id: str, step_id: str, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any] | None:
        cur = self._conn.cursor()
        clauses = ['workflow_id=?', 'step_id=?', 'status=?']
        params: list[Any] = [workflow_id, step_id, 'pending']
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        row = cur.execute('SELECT approval_id, workflow_id, step_id, requested_role, requested_by, status, reason, payload_json, created_at, updated_at, expires_at, decided_at, decided_by, assigned_to, claimed_at, tenant_id, workspace_id, environment FROM approvals WHERE ' + ' AND '.join(clauses) + ' ORDER BY created_at DESC LIMIT 1', tuple(params)).fetchone()
        return self._approval_row_to_dict(row) if row is not None else None

    def get_approval(self, approval_id: str, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any] | None:
        cur = self._conn.cursor()
        clauses = ['approval_id=?']
        params: list[Any] = [approval_id]
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        row = cur.execute('SELECT approval_id, workflow_id, step_id, requested_role, requested_by, status, reason, payload_json, created_at, updated_at, expires_at, decided_at, decided_by, assigned_to, claimed_at, tenant_id, workspace_id, environment FROM approvals WHERE ' + ' AND '.join(clauses), tuple(params)).fetchone()
        return self._approval_row_to_dict(row) if row is not None else None

    def list_approvals(self, *, limit: int = 100, status: str | None = None, workflow_id: str | None = None, requested_role: str | None = None, requested_by: str | None = None, assignee: str | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        if status is not None:
            clauses.append('status=?')
            params.append(status)
        if workflow_id is not None:
            clauses.append('workflow_id=?')
            params.append(workflow_id)
        if requested_role is not None:
            clauses.append('requested_role=?')
            params.append(requested_role)
        if requested_by is not None:
            clauses.append('requested_by=?')
            params.append(requested_by)
        if assignee is not None:
            clauses.append('assigned_to=?')
            params.append(assignee)
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = 'SELECT approval_id, workflow_id, step_id, requested_role, requested_by, status, reason, payload_json, created_at, updated_at, expires_at, decided_at, decided_by, assigned_to, claimed_at, tenant_id, workspace_id, environment FROM approvals'
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        sql += ' ORDER BY created_at DESC LIMIT ?'
        params.append(int(limit))
        rows = cur.execute(sql, tuple(params)).fetchall()
        return [self._approval_row_to_dict(r) for r in rows]

    def decide_approval(self, approval_id: str, *, decision: str, decided_by: str, reason: str = '', tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any] | None:
        status = str(decision or '').strip().lower()
        if status not in {'approve', 'approved', 'reject', 'rejected', 'expire', 'expired'}:
            raise ValueError('Unsupported approval decision')
        if status.startswith('approve'):
            normalized = 'approved'
        elif status.startswith('expire'):
            normalized = 'expired'
        else:
            normalized = 'rejected'
        cur = self._conn.cursor()
        clauses = ['approval_id=?', 'status=?']
        params: list[Any] = [approval_id, 'pending']
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        cur.execute('UPDATE approvals SET status=?, reason=?, decided_at=?, decided_by=?, assigned_to=COALESCE(assigned_to, ?), updated_at=? WHERE ' + ' AND '.join(clauses), (normalized, reason, time.time(), decided_by, decided_by, time.time(), *params))
        self._conn.commit()
        return self.get_approval(approval_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def update_approval_assignment(self, approval_id: str, *, assigned_to: str | None = None, claimed_at: float | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        clauses = ['approval_id=?', 'status=?']
        params: list[Any] = [approval_id, 'pending']
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        cur = self._conn.cursor()
        cur.execute('UPDATE approvals SET assigned_to=?, claimed_at=?, updated_at=? WHERE ' + ' AND '.join(clauses), (assigned_to, claimed_at, time.time(), *params))
        updated = cur.rowcount
        self._conn.commit()
        return int(updated)

    def _job_row_to_dict(self, row: CompatRow | Any) -> dict[str, Any]:
        try:
            definition = json.loads(row['workflow_definition_json']) if row['workflow_definition_json'] else {}
        except Exception:
            definition = {'_raw': row['workflow_definition_json']}
        try:
            input_payload = json.loads(row['input_json']) if row['input_json'] else {}
        except Exception:
            input_payload = {'_raw': row['input_json']}
        return {
            'job_id': row['job_id'],
            'name': row['name'],
            'enabled': bool(row['enabled']),
            'interval_s': int(row['interval_s']) if row['interval_s'] is not None else None,
            'next_run_at': float(row['next_run_at']) if row['next_run_at'] is not None else None,
            'last_run_at': float(row['last_run_at']) if row['last_run_at'] is not None else None,
            'workflow_definition': definition,
            'input': input_payload,
            'created_by': row['created_by'],
            'created_at': float(row['created_at']),
            'updated_at': float(row['updated_at']),
            'playbook_id': row['playbook_id'],
            'schedule_kind': row['schedule_kind'] if 'schedule_kind' in row.keys() else 'interval',
            'schedule_expr': row['schedule_expr'] if 'schedule_expr' in row.keys() else None,
            'timezone': row['timezone'] if 'timezone' in row.keys() else 'UTC',
            'not_before': float(row['not_before']) if ('not_before' in row.keys() and row['not_before'] is not None) else None,
            'not_after': float(row['not_after']) if ('not_after' in row.keys() and row['not_after'] is not None) else None,
            'max_runs': int(row['max_runs']) if ('max_runs' in row.keys() and row['max_runs'] is not None) else None,
            'run_count': int(row['run_count']) if 'run_count' in row.keys() else 0,
            'last_error': row['last_error'] if 'last_error' in row.keys() else '',
            'tenant_id': row['tenant_id'],
            'workspace_id': row['workspace_id'],
            'environment': row['environment'],
        }

    def create_job_schedule(self, *, name: str, workflow_definition: dict[str, Any], created_by: str, input_payload: dict[str, Any] | None = None, interval_s: int | None = None, next_run_at: float | None = None, enabled: bool = True, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None, playbook_id: str | None = None, schedule_kind: str = 'interval', schedule_expr: str | None = None, timezone: str | None = 'UTC', not_before: float | None = None, not_after: float | None = None, max_runs: int | None = None) -> dict[str, Any]:
        job_id = str(uuid.uuid4())
        now = time.time()
        cur = self._conn.cursor()
        cur.execute(
            'INSERT INTO job_schedules(job_id, name, enabled, interval_s, next_run_at, last_run_at, workflow_definition_json, input_json, created_by, created_at, updated_at, playbook_id, tenant_id, workspace_id, environment, schedule_kind, schedule_expr, timezone, not_before, not_after, max_runs, run_count, last_error) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (job_id, name, 1 if enabled else 0, interval_s, next_run_at, None, json.dumps(workflow_definition or {}, ensure_ascii=False), json.dumps(input_payload or {}, ensure_ascii=False), created_by, now, now, playbook_id, tenant_id, workspace_id, environment, schedule_kind, schedule_expr, timezone or 'UTC', not_before, not_after, max_runs, 0, ''),
        )
        self._conn.commit()
        return self.get_job_schedule(job_id) or {'job_id': job_id}

    def get_job_schedule(self, job_id: str, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any] | None:
        cur = self._conn.cursor()
        clauses = ['job_id=?']
        params: list[Any] = [job_id]
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        row = cur.execute('SELECT job_id, name, enabled, interval_s, next_run_at, last_run_at, workflow_definition_json, input_json, created_by, created_at, updated_at, playbook_id, tenant_id, workspace_id, environment, schedule_kind, schedule_expr, timezone, not_before, not_after, max_runs, run_count, last_error FROM job_schedules WHERE ' + ' AND '.join(clauses), tuple(params)).fetchone()
        return self._job_row_to_dict(row) if row is not None else None

    def list_job_schedules(self, *, limit: int = 100, enabled: bool | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        if enabled is not None:
            clauses.append('enabled=?')
            params.append(1 if enabled else 0)
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = 'SELECT job_id, name, enabled, interval_s, next_run_at, last_run_at, workflow_definition_json, input_json, created_by, created_at, updated_at, playbook_id, tenant_id, workspace_id, environment, schedule_kind, schedule_expr, timezone, not_before, not_after, max_runs, run_count, last_error FROM job_schedules'
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        sql += ' ORDER BY created_at DESC LIMIT ?'
        params.append(int(limit))
        rows = cur.execute(sql, tuple(params)).fetchall()
        return [self._job_row_to_dict(r) for r in rows]

    def update_job_schedule(self, job_id: str, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None, **updates: Any) -> int:
        allowed = {
            'name': 'name',
            'enabled': 'enabled',
            'interval_s': 'interval_s',
            'next_run_at': 'next_run_at',
            'last_run_at': 'last_run_at',
            'workflow_definition': 'workflow_definition_json',
            'input': 'input_json',
            'updated_at': 'updated_at',
            'playbook_id': 'playbook_id',
            'schedule_kind': 'schedule_kind',
            'schedule_expr': 'schedule_expr',
            'timezone': 'timezone',
            'not_before': 'not_before',
            'not_after': 'not_after',
            'max_runs': 'max_runs',
            'run_count': 'run_count',
            'last_error': 'last_error',
        }
        sets: list[str] = []
        params: list[Any] = []
        for key, column in allowed.items():
            if key not in updates:
                continue
            value = updates[key]
            if key in {'workflow_definition', 'input'}:
                value = json.dumps(value or {}, ensure_ascii=False)
            if key == 'enabled':
                value = 1 if bool(value) else 0
            sets.append(f'{column}=?')
            params.append(value)
        if not sets:
            return 0
        clauses = ['job_id=?']
        params.append(job_id)
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        cur = self._conn.cursor()
        cur.execute('UPDATE job_schedules SET ' + ', '.join(sets) + ' WHERE ' + ' AND '.join(clauses), tuple(params))
        updated = cur.rowcount
        self._conn.commit()
        return int(updated)
