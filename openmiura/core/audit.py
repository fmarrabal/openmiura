from __future__ import annotations

import hashlib
import json
import secrets
import time
import uuid
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from .db import DBConnection, CompatRow
from .migrations import apply_migrations
from .tenancy.scope import assert_scope_match, normalize_scope
from openmiura.persistence.base import infer_scope_from_session as _infer_scope_from_session_fn
from openmiura.persistence.base import row_scope as _row_scope_fn
from openmiura.persistence.base import scope_payload as _scope_payload_fn
from openmiura.persistence.base import scope_where as _scope_where_fn
from openmiura.persistence.apps_repo import AppsRepo
from openmiura.persistence.auth_repo import AuthRepo
from openmiura.persistence.canvas_repo import CanvasRepo
from openmiura.persistence.evaluations_repo import EvaluationsRepo
from openmiura.persistence.memory_repo import MemoryRepo
from openmiura.persistence.tools_repo import ToolsRepo
from openmiura.persistence.voice_repo import VoiceRepo
from openmiura.persistence.workflows_repo import WorkflowsRepo


class AuditStore:
    """
    Persistent operational store for openMiura.

    Tables:
        sessions, messages, events, memory_items, identity_map,
        tool_calls, telegram_state, slack_event_dedupe, api_tokens, auth_users, auth_sessions,
        evaluation_runs, evaluation_case_results
    """

    def __init__(self, db_path: str, *, backend: str = "sqlite", database_url: str = "") -> None:
        self.db_path = db_path
        self.backend = str(backend or "sqlite").strip().lower()
        self.database_url = database_url
        self._conn = DBConnection(backend=self.backend, db_path=self.db_path, database_url=self.database_url)
        self._apps = AppsRepo(self._conn)
        self._auth = AuthRepo(self._conn)
        self._canvas = CanvasRepo(self._conn)
        self._evaluations = EvaluationsRepo(self._conn)
        self._memory = MemoryRepo(self._conn)
        self._tools = ToolsRepo(self._conn)
        self._voice = VoiceRepo(self._conn)
        self._workflows = WorkflowsRepo(self._conn)

    def init_db(self) -> None:
        apply_migrations(self._conn)

    def _ensure_memory_columns(self, cur) -> None:
        # Kept for backward compatibility; migrations now own schema evolution.
        return None

    @staticmethod
    def _scope_payload(*, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any]:
        return _scope_payload_fn(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    @staticmethod
    def _row_scope(row: Any) -> dict[str, Any]:
        return _row_scope_fn(row)

    def _scope_where(self, clauses: list[str], params: list[Any], *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None, prefix: str = "") -> tuple[list[str], list[Any]]:
        return _scope_where_fn(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, prefix=prefix)

    def _infer_scope_from_session(self, session_id: str) -> dict[str, Any]:
        return _infer_scope_from_session_fn(self._conn, session_id)

    def get_session_scope(self, session_id: str) -> dict[str, Any] | None:
        if not session_id:
            return None
        cur = self._conn.cursor()
        row = cur.execute("SELECT tenant_id, workspace_id, environment FROM sessions WHERE session_id=?", (session_id,)).fetchone()
        if row is None:
            return None
        return self._row_scope(row)

    def get_session_meta(self, session_id: str) -> dict[str, Any] | None:
        if not session_id:
            return None
        cur = self._conn.cursor()
        row = cur.execute(
            "SELECT session_id, channel, user_id, created_at, updated_at, tenant_id, workspace_id, environment FROM sessions WHERE session_id=?",
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "session_id": row["session_id"],
            "channel": row["channel"],
            "user_id": row["user_id"],
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
            "tenant_id": row["tenant_id"],
            "workspace_id": row["workspace_id"],
            "environment": row["environment"],
        }

    def assert_session_scope(self, session_id: str, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any]:
        scope = self.get_session_scope(session_id)
        if scope is None:
            raise ValueError(f"Unknown session_id: {session_id}")
        assert_scope_match(scope, self._scope_payload(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment), subject="session")
        return scope

    # sessions

    def get_or_create_session(
        self,
        channel: str,
        user_id: str,
        session_id: Optional[str],
        *,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> str:
        now = time.time()
        if session_id is None or session_id.strip() == "":
            session_id = str(uuid.uuid4())

        tenant_id, workspace_id, environment = normalize_scope(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        requested_scope = self._scope_payload(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        cur = self._conn.cursor()
        row = cur.execute(
            "SELECT session_id, channel, user_id, tenant_id, workspace_id, environment FROM sessions WHERE session_id=?",
            (session_id,),
        ).fetchone()

        if row is None:
            cur.execute(
                "INSERT INTO sessions(session_id, channel, user_id, created_at, updated_at, tenant_id, workspace_id, environment) VALUES(?,?,?,?,?,?,?,?)",
                (session_id, channel, user_id, now, now, tenant_id, workspace_id, environment),
            )
        else:
            existing_scope = self._row_scope(row)
            existing_has_scope = any(existing_scope.get(key) is not None for key in ("tenant_id", "workspace_id", "environment"))
            requested_has_scope = any(requested_scope.get(key) is not None for key in ("tenant_id", "workspace_id", "environment"))
            if requested_has_scope and existing_has_scope:
                assert_scope_match(existing_scope, requested_scope, subject="session")
            elif requested_has_scope and not existing_has_scope:
                cur.execute(
                    "UPDATE sessions SET updated_at=?, tenant_id=?, workspace_id=?, environment=? WHERE session_id=?",
                    (now, tenant_id, workspace_id, environment, session_id),
                )
                self._conn.commit()
                return session_id
            cur.execute("UPDATE sessions SET updated_at=? WHERE session_id=?", (now, session_id))
        self._conn.commit()
        return session_id

    def count_sessions(
        self,
        *,
        channel: str | None = None,
        user_id: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> int:
        cur = self._conn.cursor()
        clauses = []
        params: list[Any] = []
        if channel is not None:
            clauses.append("channel=?")
            params.append(channel)
        if user_id is not None:
            clauses.append("user_id=?")
            params.append(user_id)
        if tenant_id is not None:
            clauses.append("tenant_id=?")
            params.append(tenant_id)
        if workspace_id is not None:
            clauses.append("workspace_id=?")
            params.append(workspace_id)
        if environment is not None:
            clauses.append("environment=?")
            params.append(environment)
        sql = "SELECT COUNT(*) FROM sessions"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        return int(cur.execute(sql, tuple(params)).fetchone()[0])

    def count_active_sessions(
        self,
        *,
        window_s: float = 86400.0,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> int:
        threshold = time.time() - float(window_s)
        cur = self._conn.cursor()
        clauses = ["updated_at>=?"]
        params: list[Any] = [threshold]
        if tenant_id is not None:
            clauses.append("tenant_id=?")
            params.append(tenant_id)
        if workspace_id is not None:
            clauses.append("workspace_id=?")
            params.append(workspace_id)
        if environment is not None:
            clauses.append("environment=?")
            params.append(environment)
        sql = "SELECT COUNT(*) FROM sessions WHERE " + " AND ".join(clauses)
        return int(cur.execute(sql, tuple(params)).fetchone()[0])

    def count_messages(
        self,
        *,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> int:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, prefix="s")
        sql = "SELECT COUNT(*) FROM messages m JOIN sessions s ON s.session_id=m.session_id"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        return int(cur.execute(sql, tuple(params)).fetchone()[0])

    def count_identities(
        self,
        *,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
    ) -> int:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id)
        sql = "SELECT COUNT(*) FROM identity_map"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        return int(cur.execute(sql, tuple(params)).fetchone()[0])

    def count_api_tokens(
        self,
        *,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> int:
        return self._auth.count_api_tokens(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def count_auth_users(
        self,
        *,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
    ) -> int:
        return self._auth.count_auth_users(tenant_id=tenant_id, workspace_id=workspace_id)

    def count_auth_sessions(
        self,
        *,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> int:
        return self._auth.count_auth_sessions(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def list_sessions(
        self,
        *,
        limit: int = 50,
        channel: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        params: list[Any] = []
        clauses: list[str] = []
        sql = (
            "SELECT s.session_id, s.channel, s.user_id, s.created_at, s.updated_at, s.tenant_id, s.workspace_id, s.environment, "
            "m.role as last_role, m.content as last_content, m.ts as last_ts "
            "FROM sessions s "
            "LEFT JOIN messages m ON m.id = (SELECT id FROM messages WHERE session_id=s.session_id ORDER BY id DESC LIMIT 1)"
        )
        if channel:
            clauses.append("s.channel=?")
            params.append(channel)
        if tenant_id is not None:
            clauses.append("s.tenant_id=?")
            params.append(tenant_id)
        if workspace_id is not None:
            clauses.append("s.workspace_id=?")
            params.append(workspace_id)
        if environment is not None:
            clauses.append("s.environment=?")
            params.append(environment)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY s.updated_at DESC LIMIT ?"
        params.append(int(limit))
        rows = cur.execute(sql, tuple(params)).fetchall()
        out = []
        for r in rows:
            out.append(
                {
                    "session_id": r["session_id"],
                    "channel": r["channel"],
                    "user_id": r["user_id"],
                    "tenant_id": r["tenant_id"],
                    "workspace_id": r["workspace_id"],
                    "environment": r["environment"],
                    "created_at": float(r["created_at"]),
                    "updated_at": float(r["updated_at"]),
                    "last_message": {
                        "role": r["last_role"],
                        "content": r["last_content"],
                        "ts": float(r["last_ts"]) if r["last_ts"] is not None else None,
                    } if r["last_role"] is not None else None,
                }
            )
        return out

    # messages

    def append_message(self, session_id: str, role: str, content: str) -> None:
        now = time.time()
        cur = self._conn.cursor()
        cur.execute("INSERT INTO messages(ts, session_id, role, content) VALUES(?,?,?,?)", (now, session_id, role, content))
        cur.execute("UPDATE sessions SET updated_at=? WHERE session_id=?", (now, session_id))
        self._conn.commit()

    def get_recent_messages(self, session_id: str, limit: int) -> List[Tuple[str, str]]:
        cur = self._conn.cursor()
        rows = cur.execute(
            "SELECT role, content FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?",
            (session_id, int(limit)),
        ).fetchall()
        rows = list(rows)
        rows.reverse()
        return [(r[0], r[1]) for r in rows]

    def get_session_messages(
        self,
        session_id: str,
        *,
        limit: int = 200,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> list[dict[str, Any]]:
        if tenant_id is not None or workspace_id is not None or environment is not None:
            self.assert_session_scope(
                session_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                environment=environment,
            )
        cur = self._conn.cursor()
        rows = cur.execute(
            "SELECT id, ts, role, content FROM messages WHERE session_id=? ORDER BY id ASC LIMIT ?",
            (session_id, int(limit)),
        ).fetchall()
        return [
            {
                "id": int(r["id"]),
                "ts": float(r["ts"]),
                "role": r["role"],
                "content": r["content"],
            }
            for r in rows
        ]

    def get_last_message(self, session_id: str) -> dict[str, Any] | None:
        cur = self._conn.cursor()
        row = cur.execute(
            "SELECT role, content, ts FROM messages WHERE session_id=? ORDER BY id DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        return {"role": row["role"], "content": row["content"], "ts": float(row["ts"])}

    def clear_session_messages(self, session_id: str) -> int:
        cur = self._conn.cursor()
        cur.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
        deleted = cur.rowcount
        self._conn.commit()
        return int(deleted)

    # events

    def log_event(
        self,
        direction: str,
        channel: str,
        user_id: str,
        session_id: str,
        payload: Dict[str, Any],
        *,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> int | None:
        if tenant_id is None and workspace_id is None and environment is None:
            inferred = self._infer_scope_from_session(session_id)
            tenant_id = inferred.get("tenant_id")
            workspace_id = inferred.get("workspace_id")
            environment = inferred.get("environment")
        cur = self._conn.cursor()
        cur.execute(
            "INSERT INTO events(ts, direction, channel, user_id, session_id, payload_json, tenant_id, workspace_id, environment) VALUES(?,?,?,?,?,?,?,?,?)",
            (time.time(), direction, channel, user_id, session_id, json.dumps(payload, ensure_ascii=False), tenant_id, workspace_id, environment),
        )
        event_id = getattr(cur, 'lastrowid', None)
        self._conn.commit()
        try:
            return int(event_id) if event_id is not None else None
        except Exception:
            return None

    def get_recent_events(
        self,
        *,
        limit: int = 50,
        channel: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        params: list[Any] = []
        clauses: list[str] = []
        sql = "SELECT id, ts, direction, channel, user_id, session_id, payload_json, tenant_id, workspace_id, environment FROM events"
        if channel:
            clauses.append("channel=?")
            params.append(channel)
        if tenant_id is not None:
            clauses.append("tenant_id=?")
            params.append(tenant_id)
        if workspace_id is not None:
            clauses.append("workspace_id=?")
            params.append(workspace_id)
        if environment is not None:
            clauses.append("environment=?")
            params.append(environment)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(int(limit))
        rows = cur.execute(sql, tuple(params)).fetchall()
        out = []
        for r in rows:
            try:
                payload = json.loads(r["payload_json"]) if r["payload_json"] else {}
            except Exception:
                payload = {"_raw": r["payload_json"]}
            out.append(
                {
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
                }
            )
        return out

    def count_events(
        self,
        *,
        channel: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> int:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        if channel is not None:
            clauses.append("channel=?")
            params.append(channel)
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = "SELECT COUNT(*) FROM events"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        return int(cur.execute(sql, tuple(params)).fetchone()[0])

    def get_last_event(
        self,
        *,
        channel: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any] | None:
        items = self.get_recent_events(limit=1, channel=channel, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        return items[0] if items else None

    def list_events_filtered(
        self,
        *,
        limit: int = 200,
        channels: list[str] | None = None,
        direction: str | None = None,
        since_ts: float | None = None,
        until_ts: float | None = None,
        event_names: list[str] | None = None,
        action_names: list[str] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        params: list[Any] = []
        clauses: list[str] = []
        sql = "SELECT id, ts, direction, channel, user_id, session_id, payload_json, tenant_id, workspace_id, environment FROM events"
        normalized_channels = [str(item).strip() for item in list(channels or []) if str(item).strip()]
        if normalized_channels:
            placeholders = ",".join("?" for _ in normalized_channels)
            clauses.append(f"channel IN ({placeholders})")
            params.extend(normalized_channels)
        if direction is not None:
            clauses.append("direction=?")
            params.append(direction)
        if since_ts is not None:
            clauses.append("ts>=?")
            params.append(float(since_ts))
        if until_ts is not None:
            clauses.append("ts<=?")
            params.append(float(until_ts))
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(max(1, int(limit)))
        rows = cur.execute(sql, tuple(params)).fetchall()
        normalized_events = {str(item).strip() for item in list(event_names or []) if str(item).strip()}
        normalized_actions = {str(item).strip() for item in list(action_names or []) if str(item).strip()}
        out: list[dict[str, Any]] = []
        for r in rows:
            try:
                payload = json.loads(r["payload_json"]) if r["payload_json"] else {}
            except Exception:
                payload = {"_raw": r["payload_json"]}
            payload_event = str(payload.get("event") or "").strip()
            payload_action = str(payload.get("action") or "").strip()
            if normalized_events and payload_event not in normalized_events:
                continue
            if normalized_actions and payload_action not in normalized_actions:
                continue
            out.append(
                {
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
                }
            )
        return out

    # identity

    def set_identity(
        self,
        channel_user_key: str,
        global_user_key: str,
        linked_by: str = "system",
        *,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
    ) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO identity_map(channel_user_key, global_user_key, linked_at, linked_by, tenant_id, workspace_id)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(channel_user_key) DO UPDATE SET
                global_user_key=excluded.global_user_key,
                linked_at=excluded.linked_at,
                linked_by=excluded.linked_by,
                tenant_id=excluded.tenant_id,
                workspace_id=excluded.workspace_id
            """,
            (channel_user_key, global_user_key, time.time(), linked_by, tenant_id, workspace_id),
        )
        self._conn.commit()

    def get_identity(self, channel_user_key: str, *, tenant_id: str | None = None, workspace_id: str | None = None) -> str | None:
        cur = self._conn.cursor()
        clauses = ["channel_user_key=?"]
        params: list[Any] = [channel_user_key]
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id)
        row = cur.execute("SELECT global_user_key FROM identity_map WHERE " + " AND ".join(clauses), tuple(params)).fetchone()
        return row[0] if row else None

    def delete_identity(self, channel_user_key: str, *, tenant_id: str | None = None, workspace_id: str | None = None) -> int:
        cur = self._conn.cursor()
        clauses = ["channel_user_key=?"]
        params: list[Any] = [channel_user_key]
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id)
        cur.execute("DELETE FROM identity_map WHERE " + " AND ".join(clauses), tuple(params))
        deleted = cur.rowcount
        self._conn.commit()
        return int(deleted)

    def list_identities(
        self,
        global_user_key: str | None = None,
        *,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
    ) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        if global_user_key is not None:
            clauses.append("global_user_key=?")
            params.append(global_user_key)
        if tenant_id is not None:
            clauses.append("tenant_id=?")
            params.append(tenant_id)
        if workspace_id is not None:
            clauses.append("workspace_id=?")
            params.append(workspace_id)
        sql = "SELECT channel_user_key, global_user_key, linked_at, linked_by, tenant_id, workspace_id FROM identity_map"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY linked_at DESC"
        rows = cur.execute(sql, tuple(params)).fetchall()
        return [
            {
                "channel_user_key": r["channel_user_key"],
                "global_user_key": r["global_user_key"],
                "linked_at": float(r["linked_at"]),
                "linked_by": r["linked_by"],
                "tenant_id": r["tenant_id"],
                "workspace_id": r["workspace_id"],
            }
            for r in rows
        ]

    # memory

    def add_memory_item(
        self,
        user_key: str,
        kind: str,
        text: str,
        embedding_blob: bytes,
        meta_json: str,
        *,
        tier: str = "medium",
        repeat_count: int = 1,
        access_count: int = 0,
        last_accessed_at: float | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> None:
        return self._memory.add_memory_item(user_key, kind, text, embedding_blob, meta_json, tier=tier, repeat_count=repeat_count, access_count=access_count, last_accessed_at=last_accessed_at, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def get_recent_memory_items(self, user_key: str, limit: int) -> list[tuple[int, str, str, bytes, str, float]]:
        return self._memory.get_recent_memory_items(user_key, limit)

    def get_recent_memory_records(self, user_key: str, limit: int, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        return self._memory.get_recent_memory_records(user_key, limit, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def iter_memory_records(self, *, user_key: str | None = None, limit: int | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        return self._memory.iter_memory_records(user_key=user_key, limit=limit, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def delete_memory_items(self, user_key: str, kind: str | None = None, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        return self._memory.delete_memory_items(user_key, kind, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def count_memory_items(self, user_key: str | None = None, kind: str | None = None, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        return self._memory.count_memory_items(user_key, kind, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def count_memory_items_by_kind(self, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, int]:
        return self._memory.count_memory_items_by_kind(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def search_memory_items(
        self,
        *,
        user_key: str | None = None,
        kind: str | None = None,
        text_contains: str | None = None,
        limit: int = 20,
        text_resolver: Callable[[dict[str, Any]], str] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> list[dict[str, Any]]:
        return self._memory.search_memory_items(user_key=user_key, kind=kind, text_contains=text_contains, limit=limit, text_resolver=text_resolver, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def get_memory_item(self, item_id: int, *, user_key: str | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any] | None:
        return self._memory.get_memory_item(item_id, user_key=user_key, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def delete_memory_item_by_id(self, item_id: int, *, user_key: str | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        return self._memory.delete_memory_item_by_id(item_id, user_key=user_key, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def update_memory_item(
        self,
        *,
        item_id: int,
        kind: str,
        text: str,
        embedding_blob: bytes,
        meta_json: str,
        tier: str | None = None,
        repeat_count: int | None = None,
        access_count: int | None = None,
        last_accessed_at: float | None = None,
    ) -> int:
        return self._memory.update_memory_item(item_id=item_id, kind=kind, text=text, embedding_blob=embedding_blob, meta_json=meta_json, tier=tier, repeat_count=repeat_count, access_count=access_count, last_accessed_at=last_accessed_at)

    def increment_memory_repeat(
        self,
        *,
        item_id: int,
        kind: str,
        text: str,
        embedding_blob: bytes,
        meta_json: str,
        tier: str | None = None,
    ) -> int:
        return self._memory.increment_memory_repeat(item_id=item_id, kind=kind, text=text, embedding_blob=embedding_blob, meta_json=meta_json, tier=tier)

    def note_memory_access(self, item_ids: Iterable[int]) -> int:
        return self._memory.note_memory_access(item_ids)

    def consolidate_memory(
        self,
        *,
        user_key: str | None = None,
        short_ttl_s: float = 86400.0,
        medium_ttl_s: float = 30.0 * 86400.0,
        short_promote_repeat: int = 3,
        medium_promote_access: int = 5,
        now: float | None = None,
    ) -> dict[str, int]:
        return self._memory.consolidate_memory(user_key=user_key, short_ttl_s=short_ttl_s, medium_ttl_s=medium_ttl_s, short_promote_repeat=short_promote_repeat, medium_promote_access=medium_promote_access, now=now)

    def list_user_memory_items(self, user_key: str, *, limit: int = 5) -> list[dict[str, Any]]:
        return self._memory.list_user_memory_items(user_key, limit=limit)

    def table_counts(self) -> dict[str, int]:
        cur = self._conn.cursor()
        tables = [
            "sessions",
            "messages",
            "events",
            "memory_items",
            "telegram_state",
            "identity_map",
            "tool_calls",
            "slack_event_dedupe",
            "api_tokens",
            "auth_users",
            "auth_sessions",
            "evaluation_runs",
            "evaluation_case_results",
            "release_bundles",
            "release_bundle_items",
            "release_promotions",
            "release_approvals",
            "release_rollbacks",
            "environment_snapshots",
            "voice_sessions",
            "voice_transcripts",
            "voice_outputs",
            "voice_commands",
            "app_installations",
            "app_notifications",
            "app_deep_links",
            "canvas_documents",
            "canvas_nodes",
            "canvas_edges",
            "canvas_views",
            "canvas_presence",
            "canvas_overlay_states",
            "canvas_comments",
            "canvas_snapshots",
            "canvas_presence_events",
            "package_builds",
            "voice_audio_assets",
            "voice_provider_calls",
            "release_routing_decisions",
        ]
        return {table: int(cur.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) for table in tables}

    def table_counts_scoped(
        self,
        *,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, int]:
        if tenant_id is None and workspace_id is None and environment is None:
            return self.table_counts()
        return {
            "sessions": self.count_sessions(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment),
            "messages": self.count_messages(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment),
            "events": self.count_events(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment),
            "memory_items": self.count_memory_items(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment),
            "telegram_state": self.count_sessions(channel="telegram", tenant_id=tenant_id, workspace_id=workspace_id, environment=environment),
            "identity_map": self.count_identities(tenant_id=tenant_id, workspace_id=workspace_id),
            "tool_calls": self.count_tool_calls(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment),
            "slack_event_dedupe": self.count_events(channel="slack", tenant_id=tenant_id, workspace_id=workspace_id, environment=environment),
            "api_tokens": self.count_api_tokens(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment),
            "auth_users": self.count_auth_users(tenant_id=tenant_id, workspace_id=workspace_id),
            "auth_sessions": self.count_auth_sessions(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment),
            "evaluation_runs": self.count_evaluation_runs(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment),
            "evaluation_case_results": self.count_evaluation_case_results(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment),
            "release_bundles": self.count_release_bundles(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment),
            "release_bundle_items": self.count_release_bundle_items(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment),
            "release_promotions": self.count_release_promotions(tenant_id=tenant_id, workspace_id=workspace_id),
            "release_approvals": self.count_release_approvals(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment),
            "release_rollbacks": self.count_release_rollbacks(tenant_id=tenant_id, workspace_id=workspace_id),
            "environment_snapshots": self.count_environment_snapshots(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment),
            "voice_sessions": self.count_voice_sessions(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment),
            "voice_transcripts": self.count_voice_transcripts(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment),
            "voice_outputs": self.count_voice_outputs(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment),
            "voice_commands": self.count_voice_commands(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment),
            "app_installations": self.count_app_installations(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment),
            "app_notifications": self.count_app_notifications(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment),
            "app_deep_links": self.count_app_deep_links(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment),
            "canvas_documents": self.count_canvas_documents(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment),
            "canvas_nodes": self.count_canvas_nodes(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment),
            "canvas_edges": self.count_canvas_edges(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment),
            "canvas_views": self.count_canvas_views(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment),
            "canvas_presence": self.count_canvas_presence(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment),
            "canvas_overlay_states": self.count_canvas_overlay_states(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment),
            "canvas_comments": self.count_canvas_comments(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment),
            "canvas_snapshots": self.count_canvas_snapshots(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment),
            "canvas_presence_events": self.count_canvas_presence_events(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment),
            "package_builds": self.count_package_builds(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment),
            "voice_audio_assets": self.count_voice_audio_assets(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment),
            "voice_provider_calls": self.count_voice_provider_calls(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment),
            "release_routing_decisions": self.count_release_routing_decisions(tenant_id=tenant_id, workspace_id=workspace_id, target_environment=environment),
        }

    def prune_memory(
        self,
        user_key: str,
        keep_last: int,
        *,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> None:
        return self._memory.prune_memory(user_key, keep_last, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    # tool calls

    def log_tool_call(self, session_id: str, user_key: str, agent_id: str, tool_name: str, args_json: str, ok: bool, result_excerpt: str, error: str, duration_ms: float, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> None:
        return self._tools.log_tool_call(session_id, user_key, agent_id, tool_name, args_json, ok, result_excerpt, error, duration_ms, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def count_tool_calls(self, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        return self._tools.count_tool_calls(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def list_tool_calls(self, *, limit: int = 100, session_id: str | None = None, user_key: str | None = None, agent_id: str | None = None, tool_name: str | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        return self._tools.list_tool_calls(limit=limit, session_id=session_id, user_key=user_key, agent_id=agent_id, tool_name=tool_name, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

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
        return self._tools.log_decision_trace(trace_id=trace_id, session_id=session_id, user_key=user_key, channel=channel, agent_id=agent_id, request_text=request_text, response_text=response_text, status=status, provider=provider, model=model, latency_ms=latency_ms, estimated_cost=estimated_cost, llm_calls=llm_calls, input_tokens=input_tokens, output_tokens=output_tokens, total_tokens=total_tokens, context_json=context_json, memory_json=memory_json, tools_considered_json=tools_considered_json, tools_used_json=tools_used_json, policies_json=policies_json, decisions_json=decisions_json, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def _decision_trace_row_to_dict(self, row: Any) -> dict[str, Any]:
        return self._tools._decision_trace_row_to_dict(row)

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
        return self._tools.list_decision_traces(limit=limit, session_id=session_id, user_key=user_key, agent_id=agent_id, channel=channel, status=status, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def get_decision_trace(self, trace_id: str) -> dict[str, Any] | None:
        return self._tools.get_decision_trace(trace_id)

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
        return self._evaluations.log_evaluation_run(run_id=run_id, suite_name=suite_name, status=status, requested_by=requested_by, provider=provider, model=model, agent_name=agent_name, started_at=started_at, completed_at=completed_at, total_cases=total_cases, passed_cases=passed_cases, failed_cases=failed_cases, average_latency_ms=average_latency_ms, total_cost=total_cost, scorecard_json=scorecard_json, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

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
        return self._evaluations.log_evaluation_case_result(run_id=run_id, case_id=case_id, case_name=case_name, status=status, passed=passed, score=score, latency_ms=latency_ms, cost=cost, assertions_total=assertions_total, assertions_passed=assertions_passed, details_json=details_json, observed_json=observed_json, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def count_evaluation_runs(self, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        return self._evaluations.count_evaluation_runs(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def count_evaluation_case_results(self, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        return self._evaluations.count_evaluation_case_results(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

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
        return self._evaluations.list_evaluation_runs(limit=limit, suite_name=suite_name, status=status, agent_name=agent_name, provider=provider, model=model, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def get_evaluation_run(self, run_id: str) -> dict[str, Any] | None:
        return self._evaluations.get_evaluation_run(run_id)

    def list_evaluation_case_results(
        self,
        *,
        run_id: str,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        return self._evaluations.list_evaluation_case_results(run_id=run_id, limit=limit)

    # telegram state

    def get_telegram_offset(self, bot_key: str) -> int:
        cur = self._conn.cursor()
        row = cur.execute(
            "SELECT last_update_id FROM telegram_state WHERE bot_key=?",
            (bot_key,),
        ).fetchone()
        return int(row[0]) if row else 0

    def set_telegram_offset(self, bot_key: str, last_update_id: int) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO telegram_state(bot_key, last_update_id, updated_at)
            VALUES(?,?,?)
            ON CONFLICT(bot_key) DO UPDATE SET
                last_update_id=excluded.last_update_id,
                updated_at=excluded.updated_at
            """,
            (bot_key, int(last_update_id), time.time()),
        )
        self._conn.commit()

    # slack dedupe

    def mark_slack_event_once(self, event_id: str, team_id: str, channel_id: str, user_id: str) -> bool:
        cur = self._conn.cursor()
        if getattr(self._conn, "backend", "sqlite") == "postgresql":
            cur.execute(
                """
                INSERT INTO slack_event_dedupe(event_id, ts, team_id, channel_id, user_id)
                VALUES(?,?,?,?,?)
                ON CONFLICT(event_id) DO NOTHING
                """,
                (event_id, time.time(), team_id or "", channel_id or "", user_id or ""),
            )
        else:
            cur.execute(
                """
                INSERT OR IGNORE INTO slack_event_dedupe(event_id, ts, team_id, channel_id, user_id)
                VALUES(?,?,?,?,?)
                """,
                (event_id, time.time(), team_id or "", channel_id or "", user_id or ""),
            )
        self._conn.commit()
        return cur.rowcount == 1

    # api tokens

    def create_api_token(
        self,
        *,
        user_key: str,
        label: str,
        scopes: list[str] | None = None,
        ttl_s: int | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self._auth.create_api_token(user_key=user_key, label=label, scopes=scopes, ttl_s=ttl_s, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def list_api_tokens(self, *, user_key: str | None = None, include_revoked: bool = False, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        return self._auth.list_api_tokens(user_key=user_key, include_revoked=include_revoked, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def get_api_token(self, raw_token: str, *, idle_ttl_s: int | None = None) -> dict[str, Any] | None:
        return self._auth.get_api_token(raw_token, idle_ttl_s=idle_ttl_s)

    def touch_api_token(self, raw_token: str) -> int:
        return self._auth.touch_api_token(raw_token)

    def revoke_api_token(self, *, token_id: int | None = None, raw_token: str | None = None) -> int:
        return self._auth.revoke_api_token(token_id=token_id, raw_token=raw_token)

    def rotate_api_token(self, *, token_id: int, ttl_s: int | None = None, user_key: str | None = None) -> dict[str, Any] | None:
        return self._auth.rotate_api_token(token_id=token_id, ttl_s=ttl_s, user_key=user_key)

    def cleanup_api_tokens(self, *, idle_ttl_s: int | None = None) -> dict[str, int]:
        return self._auth.cleanup_api_tokens(idle_ttl_s=idle_ttl_s)

    # auth users / sessions

    def _hash_password(self, password: str, salt_hex: str | None = None, iterations: int = 200000) -> tuple[str, str]:
        return self._auth._hash_password(password, salt_hex, iterations)

    def has_auth_users(self) -> bool:
        return self._auth.has_auth_users()

    def ensure_auth_user(
        self,
        *,
        username: str,
        password: str,
        user_key: str | None = None,
        role: str = "user",
        tenant_id: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        return self._auth.ensure_auth_user(username=username, password=password, user_key=user_key, role=role, tenant_id=tenant_id, workspace_id=workspace_id)

    def get_auth_user(self, *, user_id: int | None = None, username: str | None = None, user_key: str | None = None) -> dict[str, Any] | None:
        return self._auth.get_auth_user(user_id=user_id, username=username, user_key=user_key)

    def list_auth_users(self, *, tenant_id: str | None = None, workspace_id: str | None = None) -> list[dict[str, Any]]:
        return self._auth.list_auth_users(tenant_id=tenant_id, workspace_id=workspace_id)

    def verify_auth_user(self, *, username: str, password: str) -> dict[str, Any] | None:
        return self._auth.verify_auth_user(username=username, password=password)

    def create_auth_session(
        self,
        *,
        user_id: int,
        label: str = "ui",
        ttl_s: int | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self._auth.create_auth_session(user_id=user_id, label=label, ttl_s=ttl_s, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def list_auth_sessions(self, *, user_id: int | None = None, include_revoked: bool = False, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        return self._auth.list_auth_sessions(user_id=user_id, include_revoked=include_revoked, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def get_auth_session(self, raw_token: str, *, idle_ttl_s: int | None = None) -> dict[str, Any] | None:
        return self._auth.get_auth_session(raw_token, idle_ttl_s=idle_ttl_s)

    def touch_auth_session(self, raw_token: str) -> int:
        return self._auth.touch_auth_session(raw_token)

    def revoke_auth_session(self, *, raw_token: str | None = None, session_id: int | None = None) -> int:
        return self._auth.revoke_auth_session(raw_token=raw_token, session_id=session_id)

    def revoke_auth_sessions_for_user(self, *, user_id: int, keep_session_id: int | None = None) -> int:
        return self._auth.revoke_auth_sessions_for_user(user_id=user_id, keep_session_id=keep_session_id)

    def rotate_auth_session(self, *, raw_token: str | None = None, session_id: int | None = None, ttl_s: int | None = None) -> dict[str, Any] | None:
        return self._auth.rotate_auth_session(raw_token=raw_token, session_id=session_id, ttl_s=ttl_s)

    def cleanup_auth_sessions(self, *, idle_ttl_s: int | None = None) -> dict[str, int]:
        return self._auth.cleanup_auth_sessions(idle_ttl_s=idle_ttl_s)

    def _memory_row_to_dict(self, row: CompatRow | Any) -> dict[str, Any]:
        return self._memory._memory_row_to_dict(row)

    # workflows / approvals / jobs

    def _workflow_row_to_dict(self, row: CompatRow | Any) -> dict[str, Any]:
        return self._workflows._workflow_row_to_dict(row)

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
        return self._workflows.create_workflow(name=name, definition=definition, created_by=created_by, input_payload=input_payload, context=context, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, source_job_id=source_job_id, playbook_id=playbook_id)

    def get_workflow(self, workflow_id: str, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any] | None:
        return self._workflows.get_workflow(workflow_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def list_workflows(self, *, limit: int = 50, status: str | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        return self._workflows.list_workflows(limit=limit, status=status, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def update_workflow_state(self, workflow_id: str, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None, **updates: Any) -> int:
        return self._workflows.update_workflow_state(workflow_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, **updates)

    def _approval_row_to_dict(self, row: CompatRow | Any) -> dict[str, Any]:
        return self._workflows._approval_row_to_dict(row)

    def create_approval(self, *, workflow_id: str, step_id: str, requested_role: str, requested_by: str, payload: dict[str, Any] | None = None, expires_at: float | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any]:
        return self._workflows.create_approval(workflow_id=workflow_id, step_id=step_id, requested_role=requested_role, requested_by=requested_by, payload=payload, expires_at=expires_at, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def get_pending_approval_for_step(self, workflow_id: str, step_id: str, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any] | None:
        return self._workflows.get_pending_approval_for_step(workflow_id, step_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def get_approval(self, approval_id: str, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any] | None:
        return self._workflows.get_approval(approval_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def list_approvals(self, *, limit: int = 100, status: str | None = None, workflow_id: str | None = None, requested_role: str | None = None, requested_by: str | None = None, assignee: str | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        return self._workflows.list_approvals(limit=limit, status=status, workflow_id=workflow_id, requested_role=requested_role, requested_by=requested_by, assignee=assignee, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def decide_approval(self, approval_id: str, *, decision: str, decided_by: str, reason: str = '', tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any] | None:
        return self._workflows.decide_approval(approval_id, decision=decision, decided_by=decided_by, reason=reason, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def update_approval_assignment(self, approval_id: str, *, assigned_to: str | None = None, claimed_at: float | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        return self._workflows.update_approval_assignment(approval_id, assigned_to=assigned_to, claimed_at=claimed_at, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def _job_row_to_dict(self, row: CompatRow | Any) -> dict[str, Any]:
        return self._workflows._job_row_to_dict(row)

    def create_job_schedule(self, *, name: str, workflow_definition: dict[str, Any], created_by: str, input_payload: dict[str, Any] | None = None, interval_s: int | None = None, next_run_at: float | None = None, enabled: bool = True, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None, playbook_id: str | None = None, schedule_kind: str = 'interval', schedule_expr: str | None = None, timezone: str | None = 'UTC', not_before: float | None = None, not_after: float | None = None, max_runs: int | None = None) -> dict[str, Any]:
        return self._workflows.create_job_schedule(name=name, workflow_definition=workflow_definition, created_by=created_by, input_payload=input_payload, interval_s=interval_s, next_run_at=next_run_at, enabled=enabled, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, playbook_id=playbook_id, schedule_kind=schedule_kind, schedule_expr=schedule_expr, timezone=timezone, not_before=not_before, not_after=not_after, max_runs=max_runs)

    def get_job_schedule(self, job_id: str, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any] | None:
        return self._workflows.get_job_schedule(job_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def list_job_schedules(self, *, limit: int = 100, enabled: bool | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        return self._workflows.list_job_schedules(limit=limit, enabled=enabled, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def update_job_schedule(self, job_id: str, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None, **updates: Any) -> int:
        return self._workflows.update_job_schedule(job_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, **updates)

    # worker leases / idempotency

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

    # release governance

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

    def _record_release_action(self, *, release_id: str, actor: str, action: str, reason: str = '', tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any]:
        approval_id = str(uuid.uuid4())
        now = time.time()
        cur = self._conn.cursor()
        cur.execute(
            'INSERT INTO release_approvals(approval_id, release_id, actor, action, reason, created_at, tenant_id, workspace_id, environment) VALUES(?,?,?,?,?,?,?,?,?)',
            (approval_id, release_id, actor, action, reason or '', now, tenant_id, workspace_id, environment),
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

    def approve_release_bundle(self, release_id: str, *, actor: str, reason: str = '', tenant_id: str | None = None, workspace_id: str | None = None) -> dict[str, Any]:
        bundle = self.get_release_bundle(release_id, tenant_id=tenant_id, workspace_id=workspace_id)
        if bundle is None:
            raise KeyError(release_id)
        if bundle['status'] not in {'candidate', 'pending_approval', 'approved'}:
            raise ValueError('release must be in candidate or pending_approval before approval')
        now = time.time()
        cur = self._conn.cursor()
        cur.execute('UPDATE release_bundles SET status=?, approved_at=COALESCE(approved_at, ?), updated_at=?, notes=? WHERE release_id=?', ('approved', now, now, reason or bundle.get('notes') or '', release_id))
        self._conn.commit()
        self._record_release_action(release_id=release_id, actor=actor, action='approve', reason=reason, tenant_id=bundle.get('tenant_id'), workspace_id=bundle.get('workspace_id'), environment=bundle.get('environment'))
        return self.get_release_bundle(release_id, tenant_id=tenant_id, workspace_id=workspace_id) or bundle

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


    # voice runtime

    def _voice_session_row_to_dict(self, row: Any) -> dict[str, Any]:
        return self._voice._voice_session_row_to_dict(row)

    def _voice_transcript_row_to_dict(self, row: Any) -> dict[str, Any]:
        return self._voice._voice_transcript_row_to_dict(row)

    def _voice_output_row_to_dict(self, row: Any) -> dict[str, Any]:
        return self._voice._voice_output_row_to_dict(row)

    def _voice_command_row_to_dict(self, row: Any) -> dict[str, Any]:
        return self._voice._voice_command_row_to_dict(row)

    def count_voice_sessions(self, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        return self._voice.count_voice_sessions(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def count_voice_transcripts(self, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        return self._voice.count_voice_transcripts(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def count_voice_outputs(self, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        return self._voice.count_voice_outputs(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def count_voice_commands(self, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        return self._voice.count_voice_commands(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def create_voice_session(
        self,
        *,
        channel: str = 'voice',
        user_key: str,
        locale: str = 'es-ES',
        stt_provider: str = 'simulated-stt',
        tts_provider: str = 'simulated-tts',
        metadata: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self._voice.create_voice_session(channel=channel, user_key=user_key, locale=locale, stt_provider=stt_provider, tts_provider=tts_provider, metadata=metadata, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def list_voice_sessions(self, *, limit: int = 50, status: str | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        return self._voice.list_voice_sessions(limit=limit, status=status, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def get_voice_session(self, voice_session_id: str, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any] | None:
        return self._voice.get_voice_session(voice_session_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def update_voice_session(
        self,
        voice_session_id: str,
        *,
        status: str | None = None,
        last_transcript_text: str | None = None,
        last_output_text: str | None = None,
        metadata: dict[str, Any] | None = None,
        closed: bool = False,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any] | None:
        return self._voice.update_voice_session(voice_session_id, status=status, last_transcript_text=last_transcript_text, last_output_text=last_output_text, metadata=metadata, closed=closed, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def add_voice_transcript(
        self,
        voice_session_id: str,
        *,
        direction: str,
        stage: str,
        text: str,
        confidence: float | None = None,
        language: str = '',
        created_by: str = '',
        metadata: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self._voice.add_voice_transcript(voice_session_id, direction=direction, stage=stage, text=text, confidence=confidence, language=language, created_by=created_by, metadata=metadata, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def list_voice_transcripts(self, voice_session_id: str, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        return self._voice.list_voice_transcripts(voice_session_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, limit=limit)

    def add_voice_output(
        self,
        voice_session_id: str,
        *,
        text: str,
        status: str = 'ready',
        voice_name: str = 'assistant',
        audio_ref: str = '',
        created_by: str = '',
        metadata: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self._voice.add_voice_output(voice_session_id, text=text, status=status, voice_name=voice_name, audio_ref=audio_ref, created_by=created_by, metadata=metadata, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def list_voice_outputs(self, voice_session_id: str, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        return self._voice.list_voice_outputs(voice_session_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, limit=limit)

    def create_voice_command(
        self,
        voice_session_id: str,
        *,
        command_name: str,
        command_payload: dict[str, Any] | None = None,
        status: str = 'detected',
        requires_confirmation: bool = False,
        confirmed_by: str = '',
        metadata: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        return self._voice.create_voice_command(voice_session_id, command_name=command_name, command_payload=command_payload, status=status, requires_confirmation=requires_confirmation, confirmed_by=confirmed_by, metadata=metadata, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def list_voice_commands(self, voice_session_id: str, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        return self._voice.list_voice_commands(voice_session_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, limit=limit)

    def get_latest_pending_voice_command(self, voice_session_id: str, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any] | None:
        return self._voice.get_latest_pending_voice_command(voice_session_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def resolve_voice_command(self, command_id: str, *, decision: str, actor: str, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any] | None:
        return self._voice.resolve_voice_command(command_id, decision=decision, actor=actor, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def get_latest_voice_command(self, command_id: str) -> dict[str, Any] | None:
        return self._voice.get_latest_voice_command(command_id)


    # packaging & hardening

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


    # pwa foundation

    def _app_installation_row_to_dict(self, row: Any) -> dict[str, Any]:
        return self._apps._app_installation_row_to_dict(row)

    def _app_notification_row_to_dict(self, row: Any) -> dict[str, Any]:
        return self._apps._app_notification_row_to_dict(row)

    def _app_deep_link_row_to_dict(self, row: Any) -> dict[str, Any]:
        return self._apps._app_deep_link_row_to_dict(row)


    def _canvas_document_row_to_dict(self, row: Any) -> dict[str, Any]:
        return self._canvas._canvas_document_row_to_dict(row)

    def _canvas_node_row_to_dict(self, row: Any) -> dict[str, Any]:
        return self._canvas._canvas_node_row_to_dict(row)

    def _canvas_edge_row_to_dict(self, row: Any) -> dict[str, Any]:
        return self._canvas._canvas_edge_row_to_dict(row)

    def _canvas_view_row_to_dict(self, row: Any) -> dict[str, Any]:
        return self._canvas._canvas_view_row_to_dict(row)

    def _canvas_presence_row_to_dict(self, row: Any) -> dict[str, Any]:
        return self._canvas._canvas_presence_row_to_dict(row)

    def _canvas_overlay_state_row_to_dict(self, row: Any) -> dict[str, Any]:
        return self._canvas._canvas_overlay_state_row_to_dict(row)

    def _canvas_comment_row_to_dict(self, row: Any) -> dict[str, Any]:
        return self._canvas._canvas_comment_row_to_dict(row)

    def _canvas_snapshot_row_to_dict(self, row: Any) -> dict[str, Any]:
        return self._canvas._canvas_snapshot_row_to_dict(row)

    def _canvas_presence_event_row_to_dict(self, row: Any) -> dict[str, Any]:
        return self._canvas._canvas_presence_event_row_to_dict(row)

    def count_canvas_overlay_states(self, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        return self._canvas.count_canvas_overlay_states(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

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
        return self._canvas.upsert_canvas_overlay_state(canvas_id=canvas_id, state_key=state_key, toggles=toggles, inspector=inspector, created_by=created_by, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def list_canvas_overlay_states(self, *, canvas_id: str, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        return self._canvas.list_canvas_overlay_states(canvas_id=canvas_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def count_canvas_documents(self, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        return self._canvas.count_canvas_documents(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def count_canvas_nodes(self, *, canvas_id: str | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        return self._canvas.count_canvas_nodes(canvas_id=canvas_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def count_canvas_edges(self, *, canvas_id: str | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        return self._canvas.count_canvas_edges(canvas_id=canvas_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def count_canvas_views(self, *, canvas_id: str | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        return self._canvas.count_canvas_views(canvas_id=canvas_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def count_canvas_presence(self, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        return self._canvas.count_canvas_presence(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

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
        return self._canvas.create_canvas_document(title=title, description=description, status=status, created_by=created_by, metadata=metadata, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def list_canvas_documents(self, *, limit: int = 50, status: str | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        return self._canvas.list_canvas_documents(limit=limit, status=status, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def get_canvas_document(self, canvas_id: str, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any] | None:
        return self._canvas.get_canvas_document(canvas_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

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
        return self._canvas.upsert_canvas_node(canvas_id=canvas_id, node_id=node_id, node_type=node_type, label=label, position_x=position_x, position_y=position_y, width=width, height=height, data=data, created_by=created_by, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def list_canvas_nodes(self, *, canvas_id: str, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        return self._canvas.list_canvas_nodes(canvas_id=canvas_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

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
        return self._canvas.upsert_canvas_edge(canvas_id=canvas_id, edge_id=edge_id, source_node_id=source_node_id, target_node_id=target_node_id, label=label, edge_type=edge_type, data=data, created_by=created_by, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def list_canvas_edges(self, *, canvas_id: str, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        return self._canvas.list_canvas_edges(canvas_id=canvas_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

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
        return self._canvas.save_canvas_view(canvas_id=canvas_id, name=name, layout=layout, filters=filters, is_default=is_default, created_by=created_by, view_id=view_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def list_canvas_views(self, *, canvas_id: str, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        return self._canvas.list_canvas_views(canvas_id=canvas_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

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
        return self._canvas.upsert_canvas_presence(canvas_id=canvas_id, user_key=user_key, cursor_x=cursor_x, cursor_y=cursor_y, selected_node_id=selected_node_id, status=status, metadata=metadata, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def list_canvas_presence(self, *, canvas_id: str, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        return self._canvas.list_canvas_presence(canvas_id=canvas_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def list_canvas_events(self, *, canvas_id: str, limit: int = 50, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        return self._canvas.list_canvas_events(canvas_id=canvas_id, limit=limit, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def count_canvas_comments(self, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        return self._canvas.count_canvas_comments(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def count_canvas_snapshots(self, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        return self._canvas.count_canvas_snapshots(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def count_canvas_presence_events(self, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        return self._canvas.count_canvas_presence_events(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

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
        return self._canvas.create_canvas_comment(canvas_id=canvas_id, body=body, author=author, node_id=node_id, status=status, metadata=metadata, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def list_canvas_comments(self, *, canvas_id: str, limit: int = 50, status: str | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        return self._canvas.list_canvas_comments(canvas_id=canvas_id, limit=limit, status=status, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

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
        return self._canvas.create_canvas_snapshot(canvas_id=canvas_id, snapshot_kind=snapshot_kind, label=label, snapshot=snapshot, metadata=metadata, created_by=created_by, view_id=view_id, share_token=share_token, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def list_canvas_snapshots(self, *, canvas_id: str, limit: int = 50, snapshot_kind: str | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        return self._canvas.list_canvas_snapshots(canvas_id=canvas_id, limit=limit, snapshot_kind=snapshot_kind, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def get_canvas_snapshot(self, snapshot_id: str, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any] | None:
        return self._canvas.get_canvas_snapshot(snapshot_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

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
        return self._canvas.record_canvas_presence_event(canvas_id=canvas_id, user_key=user_key, event_type=event_type, payload=payload, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def list_canvas_presence_events(self, *, canvas_id: str, limit: int = 50, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        return self._canvas.list_canvas_presence_events(canvas_id=canvas_id, limit=limit, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

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

    def count_app_installations(self, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        return self._apps.count_app_installations(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def count_app_notifications(self, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        return self._apps.count_app_notifications(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def count_app_deep_links(self, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        return self._apps.count_app_deep_links(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

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
        return self._apps.register_app_installation(user_key=user_key, platform=platform, device_label=device_label, status=status, push_capable=push_capable, notification_permission=notification_permission, deep_link_base=deep_link_base, metadata=metadata, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def list_app_installations(self, *, limit: int = 50, status: str | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        return self._apps.list_app_installations(limit=limit, status=status, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

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
        return self._apps.create_app_notification(installation_id=installation_id, category=category, title=title, body=body, target_path=target_path, status=status, created_by=created_by, metadata=metadata, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def list_app_notifications(self, *, limit: int = 50, installation_id: str | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        return self._apps.list_app_notifications(limit=limit, installation_id=installation_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

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
        return self._apps.create_app_deep_link(view=view, target_type=target_type, target_id=target_id, target_params=target_params, status=status, created_by=created_by, expires_at=expires_at, metadata=metadata, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def list_app_deep_links(self, *, limit: int = 50, status: str | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        return self._apps.list_app_deep_links(limit=limit, status=status, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def get_app_deep_link(self, link_token: str) -> dict[str, Any] | None:
        return self._apps.get_app_deep_link(link_token)

    def resolve_app_deep_link(self, link_token: str) -> dict[str, Any] | None:
        return self._apps.resolve_app_deep_link(link_token)


    def _voice_audio_asset_row_to_dict(self, row: Any) -> dict[str, Any]:
        return self._voice._voice_audio_asset_row_to_dict(row)

    def _voice_provider_call_row_to_dict(self, row: Any) -> dict[str, Any]:
        return self._voice._voice_provider_call_row_to_dict(row)

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

    def count_voice_audio_assets(self, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        return self._voice.count_voice_audio_assets(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def count_voice_provider_calls(self, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        return self._voice.count_voice_provider_calls(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

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

    def create_voice_audio_asset(self, voice_session_id: str, *, direction: str, asset_kind: str, mime_type: str, sample_rate_hz: int = 0, byte_count: int = 0, sha256: str = '', storage_ref: str = '', created_by: str = '', metadata: dict[str, Any] | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any]:
        return self._voice.create_voice_audio_asset(voice_session_id, direction=direction, asset_kind=asset_kind, mime_type=mime_type, sample_rate_hz=sample_rate_hz, byte_count=byte_count, sha256=sha256, storage_ref=storage_ref, created_by=created_by, metadata=metadata, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def list_voice_audio_assets(self, voice_session_id: str, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        return self._voice.list_voice_audio_assets(voice_session_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, limit=limit)

    def create_voice_provider_call(self, voice_session_id: str, *, provider_kind: str, provider_name: str, status: str, request: dict[str, Any] | None = None, response: dict[str, Any] | None = None, error_text: str = '', latency_ms: float | None = None, created_by: str = '', tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any]:
        return self._voice.create_voice_provider_call(voice_session_id, provider_kind=provider_kind, provider_name=provider_name, status=status, request=request, response=response, error_text=error_text, latency_ms=latency_ms, created_by=created_by, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def list_voice_provider_calls(self, voice_session_id: str, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        return self._voice.list_voice_provider_calls(voice_session_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, limit=limit)

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


    # runtime alert workflows

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
