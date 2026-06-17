"""ToolsRepo: persistence for the tools domain of openMiura.

Owns the persistence logic for the tools-related tables. The class
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
    parse_json_column,
    row_scope,
    scope_payload,
    scope_where,
)


class ToolsRepo:
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

    def log_tool_call(self, session_id: str, user_key: str, agent_id: str, tool_name: str, args_json: str, ok: bool, result_excerpt: str, error: str, duration_ms: float, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> None:
        if tenant_id is None and workspace_id is None and environment is None:
            inferred = self._infer_scope_from_session(session_id)
            tenant_id = inferred.get("tenant_id")
            workspace_id = inferred.get("workspace_id")
            environment = inferred.get("environment")
        cur = self._conn.cursor()
        ts = time.time()
        # Tamper-evident hash-chain link (same transaction as the row INSERT).
        prev_hash, row_hash, chain_seq = compute_chain_link(
            self._conn,
            chain_table="tool_calls",
            row_fields={
                "ts": ts,
                "session_id": session_id,
                "user_key": user_key,
                "agent_id": agent_id,
                "tool_name": tool_name,
                "args": parse_json_column(args_json),
                "ok": bool(ok),
                "result_excerpt": result_excerpt,
                "error": error,
                "duration_ms": float(duration_ms),
            },
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            now_ts=ts,
        )
        cur.execute(
            """
            INSERT INTO tool_calls(ts, session_id, user_key, agent_id, tool_name, args_json, ok, result_excerpt, error, duration_ms, tenant_id, workspace_id, environment, row_hash, prev_hash, chain_seq)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (ts, session_id, user_key, agent_id, tool_name, args_json, 1 if ok else 0, result_excerpt, error, float(duration_ms), tenant_id, workspace_id, environment, row_hash, prev_hash, chain_seq),
        )
        self._conn.commit()

    def count_tool_calls(self, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = "SELECT COUNT(*) FROM tool_calls"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        return int(cur.execute(sql, tuple(params)).fetchone()[0])

    def list_tool_calls(self, *, limit: int = 100, session_id: str | None = None, user_key: str | None = None, agent_id: str | None = None, tool_name: str | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        if session_id is not None:
            clauses.append("session_id=?")
            params.append(session_id)
        if user_key is not None:
            clauses.append("user_key=?")
            params.append(user_key)
        if agent_id is not None:
            clauses.append("agent_id=?")
            params.append(agent_id)
        if tool_name is not None:
            clauses.append("tool_name=?")
            params.append(tool_name)
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = "SELECT id, ts, session_id, user_key, agent_id, tool_name, args_json, ok, result_excerpt, error, duration_ms, tenant_id, workspace_id, environment FROM tool_calls"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(int(limit))
        rows = cur.execute(sql, tuple(params)).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            try:
                args = json.loads(r["args_json"] or "{}")
            except Exception:
                args = {}
            out.append({
                "id": int(r["id"]),
                "ts": float(r["ts"]),
                "session_id": r["session_id"],
                "user_key": r["user_key"],
                "agent_id": r["agent_id"],
                "tool_name": r["tool_name"],
                "args": args,
                "ok": bool(r["ok"]),
                "result_excerpt": r["result_excerpt"],
                "error": r["error"],
                "duration_ms": float(r["duration_ms"]),
                "tenant_id": r["tenant_id"],
                "workspace_id": r["workspace_id"],
                "environment": r["environment"],
            })
        return out

    def log_decision_trace(
        self,
        *,
        trace_id: str,
        session_id: str,
        user_key: str,
        channel: str,
        agent_id: str,
        request_text: str,
        response_text: str = "",
        status: str = "completed",
        provider: str = "",
        model: str = "",
        latency_ms: float = 0.0,
        estimated_cost: float = 0.0,
        llm_calls: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        total_tokens: int = 0,
        context_json: str = "{}",
        memory_json: str = "{}",
        tools_considered_json: str = "[]",
        tools_used_json: str = "[]",
        policies_json: str = "[]",
        decisions_json: str = "{}",
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> None:
        if tenant_id is None and workspace_id is None and environment is None:
            inferred = self._infer_scope_from_session(session_id)
            tenant_id = inferred.get("tenant_id")
            workspace_id = inferred.get("workspace_id")
            environment = inferred.get("environment")
        cur = self._conn.cursor()
        # decision_traces is append-only immutable versions (option A): a turn
        # may log the same trace_id more than once as its status progresses, so
        # instead of an in-place upsert we append a new version. Readers
        # (get/list) return the latest version per trace_id, so external
        # behaviour is unchanged. The composite PK (trace_id, version) makes the
        # table truly append-only (a prerequisite for chaining it).
        ver_row = cur.execute(
            "SELECT MAX(version) FROM decision_traces WHERE trace_id=?",
            (trace_id,),
        ).fetchone()
        version = (int(ver_row[0]) + 1) if (ver_row and ver_row[0] is not None) else 1
        values = (
            trace_id,
            time.time(),
            session_id,
            user_key,
            channel,
            agent_id,
            request_text or "",
            response_text or "",
            status or "completed",
            provider or "",
            model or "",
            float(latency_ms),
            float(estimated_cost),
            int(llm_calls),
            int(input_tokens),
            int(output_tokens),
            int(total_tokens),
            context_json or "{}",
            memory_json or "{}",
            tools_considered_json or "[]",
            tools_used_json or "[]",
            policies_json or "[]",
            decisions_json or "{}",
            tenant_id,
            workspace_id,
            environment,
            version,
        )
        cur.execute(
            """
            INSERT INTO decision_traces(trace_id, ts, session_id, user_key, channel, agent_id, request_text, response_text, status, provider, model, latency_ms, estimated_cost, llm_calls, input_tokens, output_tokens, total_tokens, context_json, memory_json, tools_considered_json, tools_used_json, policies_json, decisions_json, tenant_id, workspace_id, environment, version)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            values,
        )
        self._conn.commit()

    def _decision_trace_row_to_dict(self, row: Any) -> dict[str, Any]:
        def _loads(raw: Any, fallback: Any):
            try:
                return json.loads(raw or json.dumps(fallback))
            except Exception:
                return fallback

        return {
            "trace_id": row["trace_id"],
            "ts": float(row["ts"]),
            "session_id": row["session_id"],
            "user_key": row["user_key"],
            "channel": row["channel"],
            "agent_id": row["agent_id"],
            "request_text": row["request_text"],
            "response_text": row["response_text"],
            "status": row["status"],
            "provider": row["provider"],
            "model": row["model"],
            "latency_ms": float(row["latency_ms"]),
            "estimated_cost": float(row["estimated_cost"]),
            "llm_calls": int(row["llm_calls"]),
            "input_tokens": int(row["input_tokens"]),
            "output_tokens": int(row["output_tokens"]),
            "total_tokens": int(row["total_tokens"]),
            "context": _loads(row["context_json"], {}),
            "memory": _loads(row["memory_json"], {}),
            "tools_considered": _loads(row["tools_considered_json"], []),
            "tools_used": _loads(row["tools_used_json"], []),
            "policies": _loads(row["policies_json"], []),
            "decisions": _loads(row["decisions_json"], {}),
            "tenant_id": row["tenant_id"],
            "workspace_id": row["workspace_id"],
            "environment": row["environment"],
        }

    def list_decision_traces(
        self,
        *,
        limit: int = 50,
        session_id: str | None = None,
        user_key: str | None = None,
        agent_id: str | None = None,
        channel: str | None = None,
        status: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        if session_id is not None:
            clauses.append("session_id=?")
            params.append(session_id)
        if user_key is not None:
            clauses.append("user_key=?")
            params.append(user_key)
        if agent_id is not None:
            clauses.append("agent_id=?")
            params.append(agent_id)
        if channel is not None:
            clauses.append("channel=?")
            params.append(channel)
        if status is not None:
            clauses.append("status=?")
            params.append(status)
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        # Return only the latest version of each trace_id (decision_traces is
        # append-only immutable versions); older versions are internal history.
        clauses.append("version = (SELECT MAX(d2.version) FROM decision_traces d2 WHERE d2.trace_id = decision_traces.trace_id)")
        sql = "SELECT trace_id, ts, session_id, user_key, channel, agent_id, request_text, response_text, status, provider, model, latency_ms, estimated_cost, llm_calls, input_tokens, output_tokens, total_tokens, context_json, memory_json, tools_considered_json, tools_used_json, policies_json, decisions_json, tenant_id, workspace_id, environment FROM decision_traces"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY ts DESC LIMIT ?"
        params.append(int(limit))
        rows = cur.execute(sql, tuple(params)).fetchall()
        return [self._decision_trace_row_to_dict(r) for r in rows]

    def get_decision_trace(self, trace_id: str) -> dict[str, Any] | None:
        cur = self._conn.cursor()
        # Latest version of the trace (append-only immutable versions).
        row = cur.execute(
            "SELECT trace_id, ts, session_id, user_key, channel, agent_id, request_text, response_text, status, provider, model, latency_ms, estimated_cost, llm_calls, input_tokens, output_tokens, total_tokens, context_json, memory_json, tools_considered_json, tools_used_json, policies_json, decisions_json, tenant_id, workspace_id, environment FROM decision_traces WHERE trace_id=? ORDER BY version DESC LIMIT 1",
            (trace_id,),
        ).fetchone()
        return self._decision_trace_row_to_dict(row) if row is not None else None
