"""ReleaseRepo: persistence for the release domain of openMiura.

Owns the persistence logic for the release-related tables. The class
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
    compute_chain_link,
    infer_scope_from_session,
    release_approval_chain_fields,
    row_scope,
    scope_payload,
    scope_where,
)


class ReleaseRepo:
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

    def _release_bundle_row_to_dict(self, row: Any) -> dict[str, Any]:
        def _loads(raw: Any, fallback: Any):
            try:
                return json.loads(raw or json.dumps(fallback))
            except Exception:
                return fallback

        return {
            'release_id': row['release_id'],
            'kind': row['kind'],
            'name': row['name'],
            'version': row['version'],
            'status': row['status'],
            'environment': row['environment'],
            'created_by': row['created_by'],
            'created_at': float(row['created_at']),
            'updated_at': float(row['updated_at']),
            'submitted_at': float(row['submitted_at']) if row['submitted_at'] is not None else None,
            'approved_at': float(row['approved_at']) if row['approved_at'] is not None else None,
            'promoted_at': float(row['promoted_at']) if row['promoted_at'] is not None else None,
            'rejected_at': float(row['rejected_at']) if row['rejected_at'] is not None else None,
            'notes': row['notes'] or '',
            'metadata': _loads(row['metadata_json'], {}),
            'tenant_id': row['tenant_id'],
            'workspace_id': row['workspace_id'],
        }

    def _release_item_row_to_dict(self, row: Any) -> dict[str, Any]:
        try:
            payload = json.loads(row['payload_json'] or '{}')
        except Exception:
            payload = {}
        return {
            'id': int(row['id']),
            'release_id': row['release_id'],
            'item_kind': row['item_kind'],
            'item_key': row['item_key'],
            'item_version': row['item_version'] or '',
            'payload': payload,
        }

    def _release_promotion_row_to_dict(self, row: Any) -> dict[str, Any]:
        def _loads(raw: Any):
            try:
                return json.loads(raw or '{}')
            except Exception:
                return {}
        return {
            'promotion_id': row['promotion_id'],
            'release_id': row['release_id'],
            'from_environment': row['from_environment'],
            'to_environment': row['to_environment'],
            'status': row['status'],
            'requested_by': row['requested_by'],
            'requested_at': float(row['requested_at']),
            'approved_by': row['approved_by'] or '',
            'approved_at': float(row['approved_at']) if row['approved_at'] is not None else None,
            'completed_at': float(row['completed_at']) if row['completed_at'] is not None else None,
            'gate_result': _loads(row['gate_result_json']),
            'summary': _loads(row['summary_json']),
            'tenant_id': row['tenant_id'],
            'workspace_id': row['workspace_id'],
        }

    def _release_approval_row_to_dict(self, row: Any) -> dict[str, Any]:
        return {
            'approval_id': row['approval_id'],
            'release_id': row['release_id'],
            'actor': row['actor'],
            'action': row['action'],
            'reason': row['reason'] or '',
            'created_at': float(row['created_at']),
            'tenant_id': row['tenant_id'],
            'workspace_id': row['workspace_id'],
            'environment': row['environment'],
        }

    def _release_rollback_row_to_dict(self, row: Any) -> dict[str, Any]:
        return {
            'rollback_id': row['rollback_id'],
            'release_id': row['release_id'],
            'rolled_back_release_id': row['rolled_back_release_id'],
            'environment': row['environment'],
            'requested_by': row['requested_by'],
            'reason': row['reason'] or '',
            'created_at': float(row['created_at']),
            'snapshot_id': row['snapshot_id'],
            'tenant_id': row['tenant_id'],
            'workspace_id': row['workspace_id'],
        }

    def _release_canary_row_to_dict(self, row: Any) -> dict[str, Any]:
        def _loads(raw: Any):
            try:
                return json.loads(raw or '{}')
            except Exception:
                return {}
        return {
            'canary_id': row['canary_id'],
            'release_id': row['release_id'],
            'target_environment': row['target_environment'],
            'strategy': row['strategy'],
            'traffic_percent': float(row['traffic_percent'] or 0),
            'step_percent': float(row['step_percent'] or 0),
            'bake_minutes': int(row['bake_minutes'] or 0),
            'status': row['status'],
            'metric_guardrails': _loads(row['metric_guardrails_json']),
            'analysis_summary': _loads(row['analysis_summary_json']),
            'created_by': row['created_by'],
            'created_at': float(row['created_at']),
            'updated_at': float(row['updated_at']),
            'activated_at': float(row['activated_at']) if row['activated_at'] is not None else None,
            'completed_at': float(row['completed_at']) if row['completed_at'] is not None else None,
            'tenant_id': row['tenant_id'],
            'workspace_id': row['workspace_id'],
        }

    def _release_gate_run_row_to_dict(self, row: Any) -> dict[str, Any]:
        try:
            details = json.loads(row['details_json'] or '{}')
        except Exception:
            details = {}
        return {
            'gate_run_id': row['gate_run_id'],
            'release_id': row['release_id'],
            'gate_name': row['gate_name'],
            'status': row['status'],
            'score': float(row['score']) if row['score'] is not None else None,
            'threshold': float(row['threshold']) if row['threshold'] is not None else None,
            'details': details,
            'executed_by': row['executed_by'] or '',
            'created_at': float(row['created_at']),
            'tenant_id': row['tenant_id'],
            'workspace_id': row['workspace_id'],
            'environment': row['environment'],
        }

    def _release_change_report_row_to_dict(self, row: Any) -> dict[str, Any]:
        def _loads(raw: Any):
            try:
                return json.loads(raw or '{}')
            except Exception:
                return {}
        return {
            'report_id': row['report_id'],
            'release_id': row['release_id'],
            'risk_level': row['risk_level'],
            'summary': _loads(row['summary_json']),
            'diff': _loads(row['diff_json']),
            'created_by': row['created_by'] or '',
            'created_at': float(row['created_at']),
            'updated_at': float(row['updated_at']),
            'tenant_id': row['tenant_id'],
            'workspace_id': row['workspace_id'],
        }

    def _environment_snapshot_row_to_dict(self, row: Any) -> dict[str, Any]:
        try:
            metadata = json.loads(row['metadata_json'] or '{}')
        except Exception:
            metadata = {}
        return {
            'snapshot_id': row['snapshot_id'],
            'kind': row['kind'],
            'name': row['name'],
            'environment': row['environment'],
            'active_release_id': row['active_release_id'],
            'previous_release_id': row['previous_release_id'],
            'ts': float(row['ts']),
            'reason': row['reason'] or '',
            'tenant_id': row['tenant_id'],
            'workspace_id': row['workspace_id'],
            'metadata': metadata,
        }

    def count_release_bundles(self, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = 'SELECT COUNT(*) FROM release_bundles'
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        return int(cur.execute(sql, tuple(params)).fetchone()[0])

    def count_release_bundle_items(self, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, prefix='b')
        sql = 'SELECT COUNT(*) FROM release_bundle_items i JOIN release_bundles b ON b.release_id=i.release_id'
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        return int(cur.execute(sql, tuple(params)).fetchone()[0])

    def count_release_promotions(self, *, tenant_id: str | None = None, workspace_id: str | None = None) -> int:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        if tenant_id is not None:
            clauses.append('tenant_id=?')
            params.append(tenant_id)
        if workspace_id is not None:
            clauses.append('workspace_id=?')
            params.append(workspace_id)
        sql = 'SELECT COUNT(*) FROM release_promotions'
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        return int(cur.execute(sql, tuple(params)).fetchone()[0])

    def count_release_approvals(self, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = 'SELECT COUNT(*) FROM release_approvals'
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        return int(cur.execute(sql, tuple(params)).fetchone()[0])

    def count_release_rollbacks(self, *, tenant_id: str | None = None, workspace_id: str | None = None) -> int:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        if tenant_id is not None:
            clauses.append('tenant_id=?')
            params.append(tenant_id)
        if workspace_id is not None:
            clauses.append('workspace_id=?')
            params.append(workspace_id)
        sql = 'SELECT COUNT(*) FROM release_rollbacks'
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        return int(cur.execute(sql, tuple(params)).fetchone()[0])

    def count_environment_snapshots(self, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = 'SELECT COUNT(*) FROM environment_snapshots'
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        return int(cur.execute(sql, tuple(params)).fetchone()[0])

    def create_release_bundle(
        self,
        *,
        kind: str,
        name: str,
        version: str,
        created_by: str,
        items: list[dict[str, Any]] | None = None,
        environment: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        notes: str = '',
        metadata: dict[str, Any] | None = None,
        status: str = 'draft',
    ) -> dict[str, Any]:
        release_id = str(uuid.uuid4())
        now = time.time()
        cur = self._conn.cursor()
        cur.execute(
            'INSERT INTO release_bundles(release_id, kind, name, version, status, environment, created_by, created_at, updated_at, submitted_at, approved_at, promoted_at, rejected_at, notes, metadata_json, tenant_id, workspace_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (release_id, kind, name, version, status, environment, created_by, now, now, None, None, None, None, notes or '', json.dumps(metadata or {}, ensure_ascii=False), tenant_id, workspace_id),
        )
        for item in list(items or []):
            cur.execute(
                'INSERT INTO release_bundle_items(release_id, item_kind, item_key, item_version, payload_json) VALUES(?,?,?,?,?)',
                (release_id, str(item.get('item_kind') or item.get('kind') or 'artifact'), str(item.get('item_key') or item.get('key') or ''), str(item.get('item_version') or item.get('version') or ''), json.dumps(item.get('payload') or {}, ensure_ascii=False)),
            )
        self._conn.commit()
        return self.get_release_bundle(release_id, tenant_id=tenant_id, workspace_id=workspace_id) or {'release_id': release_id}

    def list_release_bundles(
        self,
        *,
        limit: int = 50,
        status: str | None = None,
        kind: str | None = None,
        name: str | None = None,
        environment: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
    ) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        if status is not None:
            clauses.append('status=?')
            params.append(status)
        if kind is not None:
            clauses.append('kind=?')
            params.append(kind)
        if name is not None:
            clauses.append('name=?')
            params.append(name)
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = 'SELECT release_id, kind, name, version, status, environment, created_by, created_at, updated_at, submitted_at, approved_at, promoted_at, rejected_at, notes, metadata_json, tenant_id, workspace_id FROM release_bundles'
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        sql += ' ORDER BY created_at DESC LIMIT ?'
        params.append(int(limit))
        rows = cur.execute(sql, tuple(params)).fetchall()
        return [self._release_bundle_row_to_dict(row) for row in rows]

    def get_release_bundle(self, release_id: str, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any] | None:
        cur = self._conn.cursor()
        clauses = ['release_id=?']
        params: list[Any] = [release_id]
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        row = cur.execute('SELECT release_id, kind, name, version, status, environment, created_by, created_at, updated_at, submitted_at, approved_at, promoted_at, rejected_at, notes, metadata_json, tenant_id, workspace_id FROM release_bundles WHERE ' + ' AND '.join(clauses), tuple(params)).fetchone()
        return self._release_bundle_row_to_dict(row) if row is not None else None

    def list_release_bundle_items(self, release_id: str) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        rows = cur.execute('SELECT id, release_id, item_kind, item_key, item_version, payload_json FROM release_bundle_items WHERE release_id=? ORDER BY id ASC', (release_id,)).fetchall()
        return [self._release_item_row_to_dict(row) for row in rows]

    def update_release_bundle(
        self,
        release_id: str,
        *,
        status: str | None = None,
        notes: str | None = None,
        metadata: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any] | None:
        bundle = self.get_release_bundle(release_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if bundle is None:
            return None
        now = time.time()
        new_status = str(status or bundle.get('status') or 'draft')
        new_notes = bundle.get('notes') if notes is None else str(notes)
        new_metadata = dict(bundle.get('metadata') or {}) if metadata is None else dict(metadata or {})
        cur = self._conn.cursor()
        cur.execute(
            'UPDATE release_bundles SET status=?, notes=?, metadata_json=?, updated_at=? WHERE release_id=?',
            (new_status, new_notes or '', json.dumps(new_metadata, ensure_ascii=False), now, release_id),
        )
        self._conn.commit()
        return self.get_release_bundle(release_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment) or bundle

    def list_release_promotions(self, *, release_id: str | None = None, limit: int = 50, tenant_id: str | None = None, workspace_id: str | None = None) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        if release_id is not None:
            clauses.append('release_id=?')
            params.append(release_id)
        if tenant_id is not None:
            clauses.append('tenant_id=?')
            params.append(tenant_id)
        if workspace_id is not None:
            clauses.append('workspace_id=?')
            params.append(workspace_id)
        sql = 'SELECT promotion_id, release_id, from_environment, to_environment, status, requested_by, requested_at, approved_by, approved_at, completed_at, gate_result_json, summary_json, tenant_id, workspace_id FROM release_promotions'
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        sql += ' ORDER BY requested_at DESC LIMIT ?'
        params.append(int(limit))
        rows = cur.execute(sql, tuple(params)).fetchall()
        return [self._release_promotion_row_to_dict(row) for row in rows]

    def list_release_approvals(self, *, release_id: str | None = None, limit: int = 50, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        if release_id is not None:
            clauses.append('release_id=?')
            params.append(release_id)
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = 'SELECT approval_id, release_id, actor, action, reason, created_at, tenant_id, workspace_id, environment FROM release_approvals'
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        sql += ' ORDER BY created_at DESC LIMIT ?'
        params.append(int(limit))
        rows = cur.execute(sql, tuple(params)).fetchall()
        return [self._release_approval_row_to_dict(row) for row in rows]

    def list_release_rollbacks(self, *, release_id: str | None = None, limit: int = 50, tenant_id: str | None = None, workspace_id: str | None = None) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        if release_id is not None:
            clauses.append('release_id=?')
            params.append(release_id)
        if tenant_id is not None:
            clauses.append('tenant_id=?')
            params.append(tenant_id)
        if workspace_id is not None:
            clauses.append('workspace_id=?')
            params.append(workspace_id)
        sql = 'SELECT rollback_id, release_id, rolled_back_release_id, environment, requested_by, reason, created_at, snapshot_id, tenant_id, workspace_id FROM release_rollbacks'
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        sql += ' ORDER BY created_at DESC LIMIT ?'
        params.append(int(limit))
        rows = cur.execute(sql, tuple(params)).fetchall()
        return [self._release_rollback_row_to_dict(row) for row in rows]

    def list_environment_snapshots(self, *, kind: str | None = None, name: str | None = None, environment: str | None = None, limit: int = 50, tenant_id: str | None = None, workspace_id: str | None = None) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        if kind is not None:
            clauses.append('kind=?')
            params.append(kind)
        if name is not None:
            clauses.append('name=?')
            params.append(name)
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = 'SELECT snapshot_id, kind, name, environment, active_release_id, previous_release_id, ts, reason, tenant_id, workspace_id, metadata_json FROM environment_snapshots'
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        sql += ' ORDER BY ts DESC LIMIT ?'
        params.append(int(limit))
        rows = cur.execute(sql, tuple(params)).fetchall()
        return [self._environment_snapshot_row_to_dict(row) for row in rows]

    def get_release_canary(self, release_id: str, *, tenant_id: str | None = None, workspace_id: str | None = None) -> dict[str, Any] | None:
        cur = self._conn.cursor()
        clauses = ['release_id=?']
        params: list[Any] = [release_id]
        if tenant_id is not None:
            clauses.append('tenant_id=?')
            params.append(tenant_id)
        if workspace_id is not None:
            clauses.append('workspace_id=?')
            params.append(workspace_id)
        row = cur.execute(
            'SELECT canary_id, release_id, target_environment, strategy, traffic_percent, step_percent, bake_minutes, status, metric_guardrails_json, analysis_summary_json, created_by, created_at, updated_at, activated_at, completed_at, tenant_id, workspace_id FROM release_canaries WHERE ' + ' AND '.join(clauses) + ' LIMIT 1',
            tuple(params),
        ).fetchone()
        return self._release_canary_row_to_dict(row) if row is not None else None

    def upsert_release_canary(
        self,
        release_id: str,
        *,
        target_environment: str,
        strategy: str = 'percentage',
        traffic_percent: float = 0,
        step_percent: float = 0,
        bake_minutes: int = 0,
        metric_guardrails: dict[str, Any] | None = None,
        analysis_summary: dict[str, Any] | None = None,
        created_by: str = 'admin',
        status: str = 'draft',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        existing = self.get_release_canary(release_id, tenant_id=tenant_id, workspace_id=workspace_id)
        now = time.time()
        cur = self._conn.cursor()
        if existing is None:
            canary_id = str(uuid.uuid4())
            cur.execute(
                'INSERT INTO release_canaries(canary_id, release_id, target_environment, strategy, traffic_percent, step_percent, bake_minutes, status, metric_guardrails_json, analysis_summary_json, created_by, created_at, updated_at, activated_at, completed_at, tenant_id, workspace_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (canary_id, release_id, target_environment, strategy, float(traffic_percent), float(step_percent), int(bake_minutes), status, json.dumps(metric_guardrails or {}, ensure_ascii=False), json.dumps(analysis_summary or {}, ensure_ascii=False), created_by, now, now, None, None, tenant_id, workspace_id),
            )
        else:
            activated_at = existing.get('activated_at')
            completed_at = existing.get('completed_at')
            if status == 'active' and activated_at is None:
                activated_at = now
            if status == 'completed' and completed_at is None:
                completed_at = now
            cur.execute(
                'UPDATE release_canaries SET target_environment=?, strategy=?, traffic_percent=?, step_percent=?, bake_minutes=?, status=?, metric_guardrails_json=?, analysis_summary_json=?, created_by=?, updated_at=?, activated_at=?, completed_at=? WHERE canary_id=?',
                (target_environment, strategy, float(traffic_percent), float(step_percent), int(bake_minutes), status, json.dumps(metric_guardrails or {}, ensure_ascii=False), json.dumps(analysis_summary or {}, ensure_ascii=False), created_by, now, activated_at, completed_at, existing['canary_id']),
            )
        self._conn.commit()
        return self.get_release_canary(release_id, tenant_id=tenant_id, workspace_id=workspace_id) or {'release_id': release_id}

    def list_release_gate_runs(self, *, release_id: str, limit: int = 50, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        clauses = ['release_id=?']
        params: list[Any] = [release_id]
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        rows = cur.execute(
            'SELECT gate_run_id, release_id, gate_name, status, score, threshold, details_json, executed_by, created_at, tenant_id, workspace_id, environment FROM release_gate_runs WHERE ' + ' AND '.join(clauses) + ' ORDER BY created_at DESC LIMIT ?',
            tuple(params + [int(limit)]),
        ).fetchall()
        return [self._release_gate_run_row_to_dict(row) for row in rows]

    def record_release_gate_run(
        self,
        release_id: str,
        *,
        gate_name: str,
        status: str,
        score: float | None = None,
        threshold: float | None = None,
        details: dict[str, Any] | None = None,
        executed_by: str = 'system',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        gate_run_id = str(uuid.uuid4())
        now = time.time()
        cur = self._conn.cursor()
        cur.execute(
            'INSERT INTO release_gate_runs(gate_run_id, release_id, gate_name, status, score, threshold, details_json, executed_by, created_at, tenant_id, workspace_id, environment) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
            (gate_run_id, release_id, gate_name, status, score, threshold, json.dumps(details or {}, ensure_ascii=False), executed_by, now, tenant_id, workspace_id, environment),
        )
        self._conn.commit()
        rows = self.list_release_gate_runs(release_id=release_id, limit=1, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        return rows[0] if rows else {'gate_run_id': gate_run_id, 'release_id': release_id}

    def get_release_change_report(self, release_id: str, *, tenant_id: str | None = None, workspace_id: str | None = None) -> dict[str, Any] | None:
        cur = self._conn.cursor()
        clauses = ['release_id=?']
        params: list[Any] = [release_id]
        if tenant_id is not None:
            clauses.append('tenant_id=?')
            params.append(tenant_id)
        if workspace_id is not None:
            clauses.append('workspace_id=?')
            params.append(workspace_id)
        row = cur.execute(
            'SELECT report_id, release_id, risk_level, summary_json, diff_json, created_by, created_at, updated_at, tenant_id, workspace_id FROM release_change_reports WHERE ' + ' AND '.join(clauses) + ' LIMIT 1',
            tuple(params),
        ).fetchone()
        return self._release_change_report_row_to_dict(row) if row is not None else None

    def upsert_release_change_report(
        self,
        release_id: str,
        *,
        risk_level: str,
        summary: dict[str, Any] | None = None,
        diff: dict[str, Any] | None = None,
        created_by: str = 'system',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        existing = self.get_release_change_report(release_id, tenant_id=tenant_id, workspace_id=workspace_id)
        now = time.time()
        cur = self._conn.cursor()
        if existing is None:
            report_id = str(uuid.uuid4())
            cur.execute(
                'INSERT INTO release_change_reports(report_id, release_id, risk_level, summary_json, diff_json, created_by, created_at, updated_at, tenant_id, workspace_id) VALUES(?,?,?,?,?,?,?,?,?,?)',
                (report_id, release_id, risk_level, json.dumps(summary or {}, ensure_ascii=False), json.dumps(diff or {}, ensure_ascii=False), created_by, now, now, tenant_id, workspace_id),
            )
        else:
            cur.execute(
                'UPDATE release_change_reports SET risk_level=?, summary_json=?, diff_json=?, created_by=?, updated_at=? WHERE report_id=?',
                (risk_level, json.dumps(summary or {}, ensure_ascii=False), json.dumps(diff or {}, ensure_ascii=False), created_by, now, existing['report_id']),
            )
        self._conn.commit()
        return self.get_release_change_report(release_id, tenant_id=tenant_id, workspace_id=workspace_id) or {'release_id': release_id}

    def _record_release_action(
        self,
        *,
        release_id: str,
        actor: str,
        action: str,
        reason: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        signer_user_key: str | None = None,
        meaning: str | None = None,
        second_factor_method: str | None = None,
        otp_verified_at: float | None = None,
        signature: str | None = None,
        signature_scheme: str | None = None,
        signer_key_id: str | None = None,
        signature_input_hash: str | None = None,
    ) -> dict[str, Any]:
        approval_id = str(uuid.uuid4())
        now = time.time()
        cur = self._conn.cursor()
        # Tamper-evident hash-chain link (same transaction as the row INSERT),
        # mirroring sessions_repo.log_event. The signature-grade columns are
        # part of the canonical row, so filling them (signature-grade vote) vs
        # leaving them NULL (legacy action) both hash consistently.
        prev_hash, row_hash, chain_seq = compute_chain_link(
            self._conn,
            chain_table='release_approvals',
            row_fields=release_approval_chain_fields(
                release_id=release_id,
                action=action,
                actor=actor,
                reason=reason or '',
                created_at=now,
                signer_user_key=signer_user_key,
                meaning=meaning,
                second_factor_method=second_factor_method,
                otp_verified_at=otp_verified_at,
                signature=signature,
                signature_scheme=signature_scheme,
                signer_key_id=signer_key_id,
                signature_input_hash=signature_input_hash,
            ),
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            now_ts=now,
        )
        cur.execute(
            'INSERT INTO release_approvals(approval_id, release_id, actor, action, reason, created_at, '
            'tenant_id, workspace_id, environment, signer_user_key, meaning, second_factor_method, '
            'otp_verified_at, signature, signature_scheme, signer_key_id, signature_input_hash, '
            'row_hash, prev_hash, chain_seq) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (
                approval_id, release_id, actor, action, reason or '', now,
                tenant_id, workspace_id, environment, signer_user_key, meaning, second_factor_method,
                otp_verified_at, signature, signature_scheme, signer_key_id, signature_input_hash,
                row_hash, prev_hash, chain_seq,
            ),
        )
        self._conn.commit()
        return {
            'approval_id': approval_id,
            'release_id': release_id,
            'actor': actor,
            'action': action,
            'reason': reason or '',
            'created_at': float(now),
            'tenant_id': tenant_id,
            'workspace_id': workspace_id,
            'environment': environment,
            'signer_user_key': signer_user_key,
            'meaning': meaning,
            'second_factor_method': second_factor_method,
            'otp_verified_at': float(otp_verified_at) if otp_verified_at is not None else None,
            'signature': signature,
            'signature_scheme': signature_scheme,
            'signer_key_id': signer_key_id,
            'signature_input_hash': signature_input_hash,
        }

    def submit_release_bundle(self, release_id: str, *, actor: str, reason: str = '', tenant_id: str | None = None, workspace_id: str | None = None) -> dict[str, Any]:
        bundle = self.get_release_bundle(release_id, tenant_id=tenant_id, workspace_id=workspace_id)
        if bundle is None:
            raise KeyError(release_id)
        if bundle['status'] not in {'draft', 'candidate'}:
            raise ValueError('release is not submittable from current status')
        now = time.time()
        cur = self._conn.cursor()
        cur.execute('UPDATE release_bundles SET status=?, submitted_at=COALESCE(submitted_at, ?), updated_at=?, notes=? WHERE release_id=?', ('candidate', now, now, reason or bundle.get('notes') or '', release_id))
        self._conn.commit()
        self._record_release_action(release_id=release_id, actor=actor, action='submit', reason=reason, tenant_id=bundle.get('tenant_id'), workspace_id=bundle.get('workspace_id'), environment=bundle.get('environment'))
        return self.get_release_bundle(release_id, tenant_id=tenant_id, workspace_id=workspace_id) or bundle

    def approve_release_bundle(
        self,
        release_id: str,
        *,
        actor: str,
        reason: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        signer_user_key: str | None = None,
        meaning: str | None = None,
        second_factor_method: str | None = None,
        otp_verified_at: float | None = None,
        signature: str | None = None,
        signature_scheme: str | None = None,
        signer_key_id: str | None = None,
        signature_input_hash: str | None = None,
        vote_only: bool = False,
    ) -> dict[str, Any]:
        bundle = self.get_release_bundle(release_id, tenant_id=tenant_id, workspace_id=workspace_id)
        if bundle is None:
            raise KeyError(release_id)
        if bundle['status'] not in {'candidate', 'pending_approval', 'approved'}:
            raise ValueError('release must be in candidate or pending_approval before approval')
        now = time.time()
        cur = self._conn.cursor()
        # vote_only records an approval VOTE that does not yet meet quorum: the
        # release advances to (or stays at) pending_approval. A final approval
        # (legacy single-approver, or the vote that meets quorum) flips it to
        # approved. Legacy callers (vote_only=False) behave exactly as before.
        if vote_only:
            target_status = 'pending_approval' if bundle['status'] == 'candidate' else bundle['status']
            cur.execute('UPDATE release_bundles SET status=?, updated_at=?, notes=? WHERE release_id=?', (target_status, now, reason or bundle.get('notes') or '', release_id))
        else:
            cur.execute('UPDATE release_bundles SET status=?, approved_at=COALESCE(approved_at, ?), updated_at=?, notes=? WHERE release_id=?', ('approved', now, now, reason or bundle.get('notes') or '', release_id))
        self._conn.commit()
        self._record_release_action(
            release_id=release_id, actor=actor, action='approve', reason=reason,
            tenant_id=bundle.get('tenant_id'), workspace_id=bundle.get('workspace_id'), environment=bundle.get('environment'),
            signer_user_key=signer_user_key, meaning=meaning, second_factor_method=second_factor_method,
            otp_verified_at=otp_verified_at, signature=signature, signature_scheme=signature_scheme,
            signer_key_id=signer_key_id, signature_input_hash=signature_input_hash,
        )
        return self.get_release_bundle(release_id, tenant_id=tenant_id, workspace_id=workspace_id) or bundle

    # --- signature-grade quorum (per release, per action) ------------------
    def set_release_quorum(
        self,
        *,
        release_id: str,
        action: str = 'approve',
        required_n: int = 2,
        distinct_required: bool = True,
        allow_self: bool = False,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        cur = self._conn.cursor()
        cur.execute('DELETE FROM release_approval_quorum WHERE release_id=? AND action=?', (release_id, action))
        cur.execute(
            'INSERT INTO release_approval_quorum(release_id, action, required_n, distinct_required, allow_self, tenant_id, workspace_id, environment, created_at) VALUES(?,?,?,?,?,?,?,?,?)',
            (release_id, action, int(required_n), 1 if distinct_required else 0, 1 if allow_self else 0, tenant_id, workspace_id, environment, now),
        )
        self._conn.commit()
        return self.get_release_quorum(release_id=release_id, action=action) or {}

    def get_release_quorum(self, *, release_id: str, action: str = 'approve') -> dict[str, Any] | None:
        cur = self._conn.cursor()
        row = cur.execute(
            'SELECT release_id, action, required_n, distinct_required, allow_self, tenant_id, workspace_id, environment FROM release_approval_quorum WHERE release_id=? AND action=?',
            (release_id, action),
        ).fetchone()
        if row is None:
            return None
        return {
            'release_id': row['release_id'],
            'action': row['action'],
            'required_n': int(row['required_n']),
            'distinct_required': bool(row['distinct_required']),
            'allow_self': bool(row['allow_self']),
            'tenant_id': row['tenant_id'],
            'workspace_id': row['workspace_id'],
            'environment': row['environment'],
        }

    def list_release_approval_votes(self, *, release_id: str, action: str = 'approve') -> list[dict[str, Any]]:
        """Signature-grade votes for a release/action (rows carrying a resolved
        ``signer_user_key`` — i.e. cast through the strict path). Used to count
        DISTINCT approvers for quorum."""
        cur = self._conn.cursor()
        rows = cur.execute(
            'SELECT approval_id, release_id, actor, action, signer_user_key, meaning, second_factor_method, '
            'otp_verified_at, signature, signature_scheme, signer_key_id, signature_input_hash, created_at '
            'FROM release_approvals WHERE release_id=? AND action=? AND signer_user_key IS NOT NULL ORDER BY created_at ASC',
            (release_id, action),
        ).fetchall()
        return [
            {
                'approval_id': r['approval_id'],
                'release_id': r['release_id'],
                'actor': r['actor'],
                'action': r['action'],
                'signer_user_key': r['signer_user_key'],
                'meaning': r['meaning'],
                'second_factor_method': r['second_factor_method'],
                'otp_verified_at': float(r['otp_verified_at']) if r['otp_verified_at'] is not None else None,
                'signature': r['signature'],
                'signature_scheme': r['signature_scheme'],
                'signer_key_id': r['signer_key_id'],
                'signature_input_hash': r['signature_input_hash'],
                'created_at': float(r['created_at']),
            }
            for r in rows
        ]

    def promote_release_bundle(self, release_id: str, *, to_environment: str, actor: str, reason: str = '', tenant_id: str | None = None, workspace_id: str | None = None) -> dict[str, Any]:
        bundle = self.get_release_bundle(release_id, tenant_id=tenant_id, workspace_id=workspace_id)
        if bundle is None:
            raise KeyError(release_id)
        if bundle['status'] != 'approved':
            raise ValueError('release must be approved before promotion')
        now = time.time()
        target_env = str(to_environment or bundle.get('environment') or '').strip()
        if not target_env:
            raise ValueError('target environment is required')
        cur = self._conn.cursor()
        previous = cur.execute(
            'SELECT release_id, kind, name, version, status, environment, created_by, created_at, updated_at, submitted_at, approved_at, promoted_at, rejected_at, notes, metadata_json, tenant_id, workspace_id FROM release_bundles WHERE kind=? AND name=? AND environment=? AND status=? AND release_id<>? AND (? IS NULL OR tenant_id=?) AND (? IS NULL OR workspace_id=?) ORDER BY promoted_at DESC, updated_at DESC LIMIT 1',
            (bundle['kind'], bundle['name'], target_env, 'promoted', release_id, bundle.get('tenant_id'), bundle.get('tenant_id'), bundle.get('workspace_id'), bundle.get('workspace_id')),
        ).fetchone()
        previous_id = previous['release_id'] if previous is not None else None
        snapshot_id = str(uuid.uuid4())
        cur.execute(
            'INSERT INTO environment_snapshots(snapshot_id, kind, name, environment, active_release_id, previous_release_id, ts, reason, tenant_id, workspace_id, metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            (snapshot_id, bundle['kind'], bundle['name'], target_env, previous_id, release_id, now, reason or 'pre_promotion', bundle.get('tenant_id'), bundle.get('workspace_id'), json.dumps({'from_environment': bundle.get('environment'), 'actor': actor}, ensure_ascii=False)),
        )
        if previous_id is not None:
            cur.execute('UPDATE release_bundles SET status=?, updated_at=? WHERE release_id=?', ('approved', now, previous_id))
        gate_runs = self.list_release_gate_runs(release_id=release_id, limit=20, tenant_id=bundle.get('tenant_id'), workspace_id=bundle.get('workspace_id'))
        latest_gate = gate_runs[0] if gate_runs else None
        canary = self.get_release_canary(release_id, tenant_id=bundle.get('tenant_id'), workspace_id=bundle.get('workspace_id'))
        change_report = self.get_release_change_report(release_id, tenant_id=bundle.get('tenant_id'), workspace_id=bundle.get('workspace_id'))
        promotion_id = str(uuid.uuid4())
        cur.execute(
            'INSERT INTO release_promotions(promotion_id, release_id, from_environment, to_environment, status, requested_by, requested_at, approved_by, approved_at, completed_at, gate_result_json, summary_json, tenant_id, workspace_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (
                promotion_id,
                release_id,
                bundle.get('environment'),
                target_env,
                'completed',
                actor,
                now,
                actor,
                now,
                now,
                json.dumps({
                    'latest_gate': latest_gate,
                    'gate_count': len(gate_runs),
                }, ensure_ascii=False),
                json.dumps({
                    'reason': reason or '',
                    'previous_active_release_id': previous_id,
                    'canary': canary,
                    'change_report': change_report,
                }, ensure_ascii=False),
                bundle.get('tenant_id'),
                bundle.get('workspace_id'),
            ),
        )
        cur.execute('UPDATE release_bundles SET status=?, environment=?, promoted_at=?, updated_at=?, notes=? WHERE release_id=?', ('promoted', target_env, now, now, reason or bundle.get('notes') or '', release_id))
        self._conn.commit()
        self._record_release_action(release_id=release_id, actor=actor, action='promote', reason=reason or f'promoted to {target_env}', tenant_id=bundle.get('tenant_id'), workspace_id=bundle.get('workspace_id'), environment=target_env)
        return self.get_release_bundle(release_id, tenant_id=tenant_id, workspace_id=workspace_id) or bundle

    def rollback_release_bundle(self, release_id: str, *, actor: str, reason: str = '', tenant_id: str | None = None, workspace_id: str | None = None) -> dict[str, Any]:
        bundle = self.get_release_bundle(release_id, tenant_id=tenant_id, workspace_id=workspace_id)
        if bundle is None:
            raise KeyError(release_id)
        if bundle['status'] != 'promoted':
            raise ValueError('only promoted releases can be rolled back')
        cur = self._conn.cursor()
        snapshot = cur.execute(
            'SELECT snapshot_id, kind, name, environment, active_release_id, previous_release_id, ts, reason, tenant_id, workspace_id, metadata_json FROM environment_snapshots WHERE previous_release_id=? ORDER BY ts DESC LIMIT 1',
            (release_id,),
        ).fetchone()
        if snapshot is None or not snapshot['active_release_id']:
            raise ValueError('no rollback snapshot available for release')
        restored_release_id = snapshot['active_release_id']
        now = time.time()
        cur.execute('UPDATE release_bundles SET status=?, updated_at=? WHERE release_id=?', ('rolled_back', now, release_id))
        cur.execute('UPDATE release_bundles SET status=?, environment=?, promoted_at=?, updated_at=? WHERE release_id=?', ('promoted', bundle.get('environment'), now, now, restored_release_id))
        rollback_id = str(uuid.uuid4())
        cur.execute(
            'INSERT INTO release_rollbacks(rollback_id, release_id, rolled_back_release_id, environment, requested_by, reason, created_at, snapshot_id, tenant_id, workspace_id) VALUES(?,?,?,?,?,?,?,?,?,?)',
            (rollback_id, release_id, restored_release_id, bundle.get('environment') or '', actor, reason or '', now, snapshot['snapshot_id'], bundle.get('tenant_id'), bundle.get('workspace_id')),
        )
        self._conn.commit()
        self._record_release_action(release_id=release_id, actor=actor, action='rollback', reason=reason or f'rollback to {restored_release_id}', tenant_id=bundle.get('tenant_id'), workspace_id=bundle.get('workspace_id'), environment=bundle.get('environment'))
        return {
            'rollback_id': rollback_id,
            'release_id': release_id,
            'restored_release_id': restored_release_id,
            'environment': bundle.get('environment'),
            'created_at': float(now),
        }

    def _package_build_row_to_dict(self, row: Any) -> dict[str, Any]:
        try:
            metadata = json.loads(row['metadata_json'] or '{}')
        except Exception:
            metadata = {}
        return {
            'build_id': row['build_id'],
            'target': row['target'] or '',
            'label': row['label'] or '',
            'version': row['version'] or '',
            'artifact_path': row['artifact_path'] or '',
            'status': row['status'] or 'ready',
            'created_by': row['created_by'] or '',
            'created_at': float(row['created_at']),
            'metadata': metadata,
            'tenant_id': row['tenant_id'],
            'workspace_id': row['workspace_id'],
            'environment': row['environment'],
        }

    def count_package_builds(self, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = 'SELECT COUNT(*) FROM package_builds'
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        return int(cur.execute(sql, tuple(params)).fetchone()[0])

    def create_package_build(
        self,
        *,
        target: str,
        label: str,
        version: str,
        artifact_path: str,
        status: str,
        created_by: str,
        metadata: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        build_id = str(uuid.uuid4())
        now = time.time()
        cur = self._conn.cursor()
        cur.execute(
            'INSERT INTO package_builds(build_id, target, label, version, artifact_path, status, created_by, created_at, metadata_json, tenant_id, workspace_id, environment) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
            (build_id, target, label, version, artifact_path, status, created_by, now, json.dumps(metadata or {}, ensure_ascii=False), tenant_id, workspace_id, environment),
        )
        self._conn.commit()
        row = cur.execute('SELECT build_id, target, label, version, artifact_path, status, created_by, created_at, metadata_json, tenant_id, workspace_id, environment FROM package_builds WHERE build_id=?', (build_id,)).fetchone()
        return self._package_build_row_to_dict(row)

    def list_package_builds(self, *, limit: int = 50, target: str | None = None, status: str | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if target is not None:
            clauses.append('target=?')
            params.append(target)
        if status is not None:
            clauses.append('status=?')
            params.append(status)
        sql = 'SELECT build_id, target, label, version, artifact_path, status, created_by, created_at, metadata_json, tenant_id, workspace_id, environment FROM package_builds'
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        sql += ' ORDER BY created_at DESC LIMIT ?'
        params.append(int(limit))
        return [self._package_build_row_to_dict(row) for row in cur.execute(sql, tuple(params)).fetchall()]

    def _release_routing_decision_row_to_dict(self, row: Any) -> dict[str, Any]:
        try:
            observation = json.loads(row['observation_json'] or '{}')
        except Exception:
            observation = {}
        return {
            'decision_id': row['decision_id'],
            'release_id': row['release_id'],
            'canary_id': row['canary_id'] or '',
            'baseline_release_id': row['baseline_release_id'] or '',
            'target_environment': row['target_environment'] or '',
            'routing_key_hash': row['routing_key_hash'] or '',
            'bucket': float(row['bucket'] or 0),
            'selected_release_id': row['selected_release_id'] or '',
            'selected_version': row['selected_version'] or '',
            'route_kind': row['route_kind'] or '',
            'success': None if row['success'] is None else bool(row['success']),
            'latency_ms': float(row['latency_ms']) if row['latency_ms'] is not None else None,
            'cost_estimate': float(row['cost_estimate']) if row['cost_estimate'] is not None else None,
            'observation': observation,
            'created_by': row['created_by'] or '',
            'created_at': float(row['created_at']),
            'updated_at': float(row['updated_at']),
            'completed_at': float(row['completed_at']) if row['completed_at'] is not None else None,
            'tenant_id': row['tenant_id'],
            'workspace_id': row['workspace_id'],
        }

    def count_release_routing_decisions(self, *, tenant_id: str | None = None, workspace_id: str | None = None, target_environment: str | None = None) -> int:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        if tenant_id is not None:
            clauses.append('tenant_id=?')
            params.append(tenant_id)
        if workspace_id is not None:
            clauses.append('workspace_id=?')
            params.append(workspace_id)
        if target_environment is not None:
            clauses.append('target_environment=?')
            params.append(target_environment)
        sql = 'SELECT COUNT(*) FROM release_routing_decisions'
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        return int(cur.execute(sql, tuple(params)).fetchone()[0])

    def create_release_routing_decision(self, *, release_id: str, canary_id: str, baseline_release_id: str, target_environment: str, routing_key_hash: str, bucket: float, selected_release_id: str, selected_version: str = '', route_kind: str, created_by: str = '', tenant_id: str | None = None, workspace_id: str | None = None) -> dict[str, Any]:
        decision_id = str(uuid.uuid4())
        now = time.time()
        cur = self._conn.cursor()
        cur.execute('INSERT INTO release_routing_decisions(decision_id, release_id, canary_id, baseline_release_id, target_environment, routing_key_hash, bucket, selected_release_id, selected_version, route_kind, success, latency_ms, cost_estimate, observation_json, created_by, created_at, updated_at, completed_at, tenant_id, workspace_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (decision_id, release_id, canary_id or '', baseline_release_id or '', target_environment or '', routing_key_hash, float(bucket), selected_release_id, selected_version or '', route_kind, None, None, None, json.dumps({}, ensure_ascii=False), created_by or '', now, now, None, tenant_id, workspace_id))
        self._conn.commit()
        row = cur.execute('SELECT decision_id, release_id, canary_id, baseline_release_id, target_environment, routing_key_hash, bucket, selected_release_id, selected_version, route_kind, success, latency_ms, cost_estimate, observation_json, created_by, created_at, updated_at, completed_at, tenant_id, workspace_id FROM release_routing_decisions WHERE decision_id=?', (decision_id,)).fetchone()
        return self._release_routing_decision_row_to_dict(row)

    def get_release_routing_decision(self, decision_id: str, *, tenant_id: str | None = None, workspace_id: str | None = None) -> dict[str, Any] | None:
        cur = self._conn.cursor()
        clauses = ['decision_id=?']
        params: list[Any] = [decision_id]
        if tenant_id is not None:
            clauses.append('tenant_id=?')
            params.append(tenant_id)
        if workspace_id is not None:
            clauses.append('workspace_id=?')
            params.append(workspace_id)
        row = cur.execute('SELECT decision_id, release_id, canary_id, baseline_release_id, target_environment, routing_key_hash, bucket, selected_release_id, selected_version, route_kind, success, latency_ms, cost_estimate, observation_json, created_by, created_at, updated_at, completed_at, tenant_id, workspace_id FROM release_routing_decisions WHERE ' + ' AND '.join(clauses) + ' LIMIT 1', tuple(params)).fetchone()
        return self._release_routing_decision_row_to_dict(row) if row is not None else None

    def update_release_routing_decision_observation(self, decision_id: str, *, success: bool, latency_ms: float | None = None, cost_estimate: float | None = None, metadata: dict[str, Any] | None = None, actor: str = '', tenant_id: str | None = None, workspace_id: str | None = None) -> dict[str, Any] | None:
        current = self.get_release_routing_decision(decision_id, tenant_id=tenant_id, workspace_id=workspace_id)
        if current is None:
            return None
        now = time.time()
        merged = dict(current.get('observation') or {})
        merged.update(dict(metadata or {}))
        cur = self._conn.cursor()
        cur.execute('UPDATE release_routing_decisions SET success=?, latency_ms=?, cost_estimate=?, observation_json=?, updated_at=?, completed_at=? WHERE decision_id=?', (1 if success else 0, latency_ms, cost_estimate, json.dumps(merged, ensure_ascii=False), now, now, decision_id))
        self._conn.commit()
        return self.get_release_routing_decision(decision_id, tenant_id=current.get('tenant_id'), workspace_id=current.get('workspace_id'))

    def list_release_routing_decisions(self, *, release_id: str | None = None, limit: int = 100, tenant_id: str | None = None, workspace_id: str | None = None, target_environment: str | None = None) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        if release_id is not None:
            clauses.append('release_id=?')
            params.append(release_id)
        if tenant_id is not None:
            clauses.append('tenant_id=?')
            params.append(tenant_id)
        if workspace_id is not None:
            clauses.append('workspace_id=?')
            params.append(workspace_id)
        if target_environment is not None:
            clauses.append('target_environment=?')
            params.append(target_environment)
        sql = 'SELECT decision_id, release_id, canary_id, baseline_release_id, target_environment, routing_key_hash, bucket, selected_release_id, selected_version, route_kind, success, latency_ms, cost_estimate, observation_json, created_by, created_at, updated_at, completed_at, tenant_id, workspace_id FROM release_routing_decisions'
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        sql += ' ORDER BY created_at DESC LIMIT ?'
        params.append(int(limit))
        return [self._release_routing_decision_row_to_dict(row) for row in cur.execute(sql, tuple(params)).fetchall()]
