"""EvaluationsRepo: persistence for the evaluations domain of openMiura.

Owns the persistence logic for the evaluations-related tables. The class
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
from openmiura.persistence.base import row_scope, scope_payload, scope_where


class EvaluationsRepo:
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

    def log_evaluation_run(
        self,
        *,
        run_id: str,
        suite_name: str,
        status: str,
        requested_by: str,
        provider: str = "",
        model: str = "",
        agent_name: str = "",
        started_at: float,
        completed_at: float | None = None,
        total_cases: int = 0,
        passed_cases: int = 0,
        failed_cases: int = 0,
        average_latency_ms: float = 0.0,
        total_cost: float = 0.0,
        scorecard_json: str = "{}",
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> None:
        cur = self._conn.cursor()
        backend = getattr(self._conn, "backend", "sqlite")
        values = (
            run_id,
            suite_name,
            status,
            requested_by,
            provider,
            model,
            agent_name,
            float(started_at),
            float(completed_at) if completed_at is not None else None,
            int(total_cases),
            int(passed_cases),
            int(failed_cases),
            float(average_latency_ms),
            float(total_cost),
            scorecard_json or "{}",
            tenant_id,
            workspace_id,
            environment,
        )
        if backend == "postgresql":
            cur.execute(
                """
                INSERT INTO evaluation_runs(run_id, suite_name, status, requested_by, provider, model, agent_name, started_at, completed_at, total_cases, passed_cases, failed_cases, average_latency_ms, total_cost, scorecard_json, tenant_id, workspace_id, environment)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(run_id) DO UPDATE SET
                    suite_name=EXCLUDED.suite_name,
                    status=EXCLUDED.status,
                    requested_by=EXCLUDED.requested_by,
                    provider=EXCLUDED.provider,
                    model=EXCLUDED.model,
                    agent_name=EXCLUDED.agent_name,
                    started_at=EXCLUDED.started_at,
                    completed_at=EXCLUDED.completed_at,
                    total_cases=EXCLUDED.total_cases,
                    passed_cases=EXCLUDED.passed_cases,
                    failed_cases=EXCLUDED.failed_cases,
                    average_latency_ms=EXCLUDED.average_latency_ms,
                    total_cost=EXCLUDED.total_cost,
                    scorecard_json=EXCLUDED.scorecard_json,
                    tenant_id=EXCLUDED.tenant_id,
                    workspace_id=EXCLUDED.workspace_id,
                    environment=EXCLUDED.environment
                """,
                values,
            )
        else:
            cur.execute(
                """
                INSERT INTO evaluation_runs(run_id, suite_name, status, requested_by, provider, model, agent_name, started_at, completed_at, total_cases, passed_cases, failed_cases, average_latency_ms, total_cost, scorecard_json, tenant_id, workspace_id, environment)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(run_id) DO UPDATE SET
                    suite_name=excluded.suite_name,
                    status=excluded.status,
                    requested_by=excluded.requested_by,
                    provider=excluded.provider,
                    model=excluded.model,
                    agent_name=excluded.agent_name,
                    started_at=excluded.started_at,
                    completed_at=excluded.completed_at,
                    total_cases=excluded.total_cases,
                    passed_cases=excluded.passed_cases,
                    failed_cases=excluded.failed_cases,
                    average_latency_ms=excluded.average_latency_ms,
                    total_cost=excluded.total_cost,
                    scorecard_json=excluded.scorecard_json,
                    tenant_id=excluded.tenant_id,
                    workspace_id=excluded.workspace_id,
                    environment=excluded.environment
                """,
                values,
            )
        self._conn.commit()

    def log_evaluation_case_result(
        self,
        *,
        run_id: str,
        case_id: str,
        case_name: str,
        status: str,
        passed: bool,
        score: float,
        latency_ms: float,
        cost: float,
        assertions_total: int,
        assertions_passed: int,
        details_json: str = "{}",
        observed_json: str = "{}",
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> int | None:
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO evaluation_case_results(run_id, case_id, case_name, status, passed, score, latency_ms, cost, assertions_total, assertions_passed, details_json, observed_json, tenant_id, workspace_id, environment)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (run_id, case_id, case_name, status, 1 if passed else 0, float(score), float(latency_ms), float(cost), int(assertions_total), int(assertions_passed), details_json or "{}", observed_json or "{}", tenant_id, workspace_id, environment),
        )
        row_id = getattr(cur, "lastrowid", None)
        self._conn.commit()
        try:
            return int(row_id) if row_id is not None else None
        except Exception:
            return None

    def count_evaluation_runs(self, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = "SELECT COUNT(*) FROM evaluation_runs"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        return int(cur.execute(sql, tuple(params)).fetchone()[0])

    def count_evaluation_case_results(self, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = "SELECT COUNT(*) FROM evaluation_case_results"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        return int(cur.execute(sql, tuple(params)).fetchone()[0])

    def list_evaluation_runs(
        self,
        *,
        limit: int = 20,
        suite_name: str | None = None,
        status: str | None = None,
        agent_name: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        if suite_name is not None:
            clauses.append("suite_name=?")
            params.append(suite_name)
        if status is not None:
            clauses.append("status=?")
            params.append(status)
        if agent_name is not None:
            clauses.append("agent_name=?")
            params.append(agent_name)
        if provider is not None:
            clauses.append("provider=?")
            params.append(provider)
        if model is not None:
            clauses.append("model=?")
            params.append(model)
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = "SELECT run_id, suite_name, status, requested_by, provider, model, agent_name, started_at, completed_at, total_cases, passed_cases, failed_cases, average_latency_ms, total_cost, scorecard_json, tenant_id, workspace_id, environment FROM evaluation_runs"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY started_at DESC LIMIT ?"
        params.append(int(limit))
        rows = cur.execute(sql, tuple(params)).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            try:
                scorecard = json.loads(r["scorecard_json"] or "{}")
            except Exception:
                scorecard = {}
            out.append({
                "run_id": r["run_id"],
                "suite_name": r["suite_name"],
                "status": r["status"],
                "requested_by": r["requested_by"],
                "provider": r["provider"],
                "model": r["model"],
                "agent_name": r["agent_name"],
                "started_at": float(r["started_at"]),
                "completed_at": float(r["completed_at"]) if r["completed_at"] is not None else None,
                "total_cases": int(r["total_cases"]),
                "passed_cases": int(r["passed_cases"]),
                "failed_cases": int(r["failed_cases"]),
                "average_latency_ms": float(r["average_latency_ms"]),
                "total_cost": float(r["total_cost"]),
                "scorecard": scorecard,
                "tenant_id": r["tenant_id"],
                "workspace_id": r["workspace_id"],
                "environment": r["environment"],
            })
        return out

    def get_evaluation_run(self, run_id: str) -> dict[str, Any] | None:
        cur = self._conn.cursor()
        row = cur.execute(
            "SELECT run_id, suite_name, status, requested_by, provider, model, agent_name, started_at, completed_at, total_cases, passed_cases, failed_cases, average_latency_ms, total_cost, scorecard_json, tenant_id, workspace_id, environment FROM evaluation_runs WHERE run_id=?",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        try:
            scorecard = json.loads(row["scorecard_json"] or "{}")
        except Exception:
            scorecard = {}
        return {
            "run_id": row["run_id"],
            "suite_name": row["suite_name"],
            "status": row["status"],
            "requested_by": row["requested_by"],
            "provider": row["provider"],
            "model": row["model"],
            "agent_name": row["agent_name"],
            "started_at": float(row["started_at"]),
            "completed_at": float(row["completed_at"]) if row["completed_at"] is not None else None,
            "total_cases": int(row["total_cases"]),
            "passed_cases": int(row["passed_cases"]),
            "failed_cases": int(row["failed_cases"]),
            "average_latency_ms": float(row["average_latency_ms"]),
            "total_cost": float(row["total_cost"]),
            "scorecard": scorecard,
            "tenant_id": row["tenant_id"],
            "workspace_id": row["workspace_id"],
            "environment": row["environment"],
        }

    def list_evaluation_case_results(
        self,
        *,
        run_id: str,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        rows = cur.execute(
            "SELECT id, run_id, case_id, case_name, status, passed, score, latency_ms, cost, assertions_total, assertions_passed, details_json, observed_json, tenant_id, workspace_id, environment FROM evaluation_case_results WHERE run_id=? ORDER BY id ASC LIMIT ?",
            (run_id, int(limit)),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            try:
                details = json.loads(r["details_json"] or "{}")
            except Exception:
                details = {}
            try:
                observed = json.loads(r["observed_json"] or "{}")
            except Exception:
                observed = {}
            out.append({
                "id": int(r["id"]),
                "run_id": r["run_id"],
                "case_id": r["case_id"],
                "case_name": r["case_name"],
                "status": r["status"],
                "passed": bool(r["passed"]),
                "score": float(r["score"]),
                "latency_ms": float(r["latency_ms"]),
                "cost": float(r["cost"]),
                "assertions_total": int(r["assertions_total"]),
                "assertions_passed": int(r["assertions_passed"]),
                "details": details,
                "observed": observed,
                "tenant_id": r["tenant_id"],
                "workspace_id": r["workspace_id"],
                "environment": r["environment"],
            })
        return out
