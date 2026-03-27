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

    def init_db(self) -> None:
        apply_migrations(self._conn)

    def _ensure_memory_columns(self, cur) -> None:
        # Kept for backward compatibility; migrations now own schema evolution.
        return None

    @staticmethod
    def _scope_payload(*, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any]:
        return {
            "tenant_id": str(tenant_id).strip() if tenant_id is not None else None,
            "workspace_id": str(workspace_id).strip() if workspace_id is not None else None,
            "environment": str(environment).strip() if environment is not None else None,
        }

    @staticmethod
    def _row_scope(row: Any) -> dict[str, Any]:
        scope: dict[str, Any] = {}
        for key in ("tenant_id", "workspace_id", "environment"):
            try:
                scope[key] = row[key]
            except Exception:
                scope[key] = None
        return scope

    def _scope_where(self, clauses: list[str], params: list[Any], *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None, prefix: str = "") -> tuple[list[str], list[Any]]:
        lead = f"{prefix}." if prefix else ""
        if tenant_id is not None:
            clauses.append(f"{lead}tenant_id=?")
            params.append(tenant_id)
        if workspace_id is not None:
            clauses.append(f"{lead}workspace_id=?")
            params.append(workspace_id)
        if environment is not None:
            clauses.append(f"{lead}environment=?")
            params.append(environment)
        return clauses, params

    def _infer_scope_from_session(self, session_id: str) -> dict[str, Any]:
        if not session_id:
            return {"tenant_id": None, "workspace_id": None, "environment": None}
        cur = self._conn.cursor()
        row = cur.execute("SELECT tenant_id, workspace_id, environment FROM sessions WHERE session_id=?", (session_id,)).fetchone()
        if row is None:
            return {"tenant_id": None, "workspace_id": None, "environment": None}
        return self._row_scope(row)

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
        cur = self._conn.cursor()
        clauses: list[str] = ["revoked_at IS NULL"]
        params: list[Any] = []
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = "SELECT COUNT(*) FROM api_tokens WHERE " + " AND ".join(clauses)
        return int(cur.execute(sql, tuple(params)).fetchone()[0])

    def count_auth_users(
        self,
        *,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
    ) -> int:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id)
        sql = "SELECT COUNT(*) FROM auth_users"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        return int(cur.execute(sql, tuple(params)).fetchone()[0])

    def count_auth_sessions(
        self,
        *,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> int:
        cur = self._conn.cursor()
        clauses: list[str] = ["revoked_at IS NULL"]
        params: list[Any] = []
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = "SELECT COUNT(*) FROM auth_sessions WHERE " + " AND ".join(clauses)
        return int(cur.execute(sql, tuple(params)).fetchone()[0])

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
        now = time.time()
        cur = self._conn.cursor()
        cur.execute(
            "INSERT INTO memory_items(user_key, kind, text, embedding, meta_json, created_at, tier, access_count, repeat_count, last_accessed_at, tenant_id, workspace_id, environment) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                user_key,
                kind,
                text,
                embedding_blob,
                meta_json,
                now,
                tier,
                int(access_count),
                int(repeat_count),
                float(last_accessed_at if last_accessed_at is not None else now),
                tenant_id,
                workspace_id,
                environment,
            ),
        )
        self._conn.commit()

    def get_recent_memory_items(self, user_key: str, limit: int) -> list[tuple[int, str, str, bytes, str, float]]:
        cur = self._conn.cursor()
        rows = cur.execute(
            "SELECT id, kind, text, embedding, meta_json, created_at FROM memory_items WHERE user_key=? ORDER BY id DESC LIMIT ?",
            (user_key, int(limit)),
        ).fetchall()
        return [(int(r[0]), r[1], r[2], r[3], r[4], float(r[5])) for r in rows]

    def get_recent_memory_records(self, user_key: str, limit: int, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        clauses = ["user_key=?"]
        params: list[Any] = [user_key]
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = "SELECT id, user_key, kind, text, embedding, meta_json, created_at, tier, access_count, repeat_count, last_accessed_at, tenant_id, workspace_id, environment FROM memory_items WHERE " + " AND ".join(clauses) + " ORDER BY id DESC LIMIT ?"
        params.append(int(limit))
        rows = cur.execute(sql, tuple(params)).fetchall()
        return [self._memory_row_to_dict(r) for r in rows]

    def iter_memory_records(self, *, user_key: str | None = None, limit: int | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        sql = "SELECT id, user_key, kind, text, embedding, meta_json, created_at, tier, access_count, repeat_count, last_accessed_at, tenant_id, workspace_id, environment FROM memory_items"
        params: list[Any] = []
        clauses: list[str] = []
        if user_key is not None:
            clauses.append("user_key=?")
            params.append(user_key)
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        rows = cur.execute(sql, tuple(params)).fetchall()
        return [self._memory_row_to_dict(r) for r in rows]

    def delete_memory_items(self, user_key: str, kind: str | None = None, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        cur = self._conn.cursor()
        clauses = ["user_key=?"]
        params: list[Any] = [user_key]
        if kind is not None:
            clauses.append("kind=?")
            params.append(kind)
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        cur.execute("DELETE FROM memory_items WHERE " + " AND ".join(clauses), tuple(params))
        deleted = cur.rowcount
        self._conn.commit()
        return int(deleted)

    def count_memory_items(self, user_key: str | None = None, kind: str | None = None, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        if user_key is not None:
            clauses.append("user_key=?")
            params.append(user_key)
        if kind is not None:
            clauses.append("kind=?")
            params.append(kind)
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = "SELECT COUNT(*) FROM memory_items"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        return int(cur.execute(sql, tuple(params)).fetchone()[0])

    def count_memory_items_by_kind(self, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, int]:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = "SELECT kind, COUNT(*) AS total FROM memory_items"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " GROUP BY kind"
        rows = cur.execute(sql, tuple(params)).fetchall()
        return {str(r[0]): int(r[1]) for r in rows}

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
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        if user_key:
            clauses.append("user_key=?")
            params.append(user_key)
        if kind:
            clauses.append("kind=?")
            params.append(kind)
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        sql = (
            "SELECT id, user_key, kind, text, embedding, meta_json, created_at, tier, access_count, repeat_count, last_accessed_at, tenant_id, workspace_id, environment "
            f"FROM memory_items{where} ORDER BY id DESC"
        )
        rows = cur.execute(sql, tuple(params)).fetchall()
        items: list[dict[str, Any]] = []
        needle = (text_contains or "").lower().strip()
        for r in rows:
            item = self._memory_row_to_dict(r)
            if callable(text_resolver):
                try:
                    item["text"] = text_resolver(item)
                except Exception:
                    pass
            if needle and needle not in str(item.get("text") or "").lower():
                continue
            items.append(item)
            if len(items) >= int(limit):
                break
        return items

    def get_memory_item(self, item_id: int, *, user_key: str | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any] | None:
        cur = self._conn.cursor()
        params: list[Any] = [int(item_id)]
        sql = "SELECT id, user_key, kind, text, embedding, meta_json, created_at, tier, access_count, repeat_count, last_accessed_at, tenant_id, workspace_id, environment FROM memory_items WHERE id=?"
        if user_key is not None:
            sql += " AND user_key=?"
            params.append(user_key)
        if tenant_id is not None:
            sql += " AND tenant_id=?"
            params.append(tenant_id)
        if workspace_id is not None:
            sql += " AND workspace_id=?"
            params.append(workspace_id)
        if environment is not None:
            sql += " AND environment=?"
            params.append(environment)
        row = cur.execute(sql, tuple(params)).fetchone()
        if row is None:
            return None
        return self._memory_row_to_dict(row)

    def delete_memory_item_by_id(self, item_id: int, *, user_key: str | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        cur = self._conn.cursor()
        clauses = ["id=?"]
        params: list[Any] = [int(item_id)]
        if user_key is not None:
            clauses.append("user_key=?")
            params.append(user_key)
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        cur.execute("DELETE FROM memory_items WHERE " + " AND ".join(clauses), tuple(params))
        deleted = cur.rowcount
        self._conn.commit()
        return int(deleted)

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
        cur = self._conn.cursor()
        existing = cur.execute(
            "SELECT tier, repeat_count, access_count, last_accessed_at FROM memory_items WHERE id=?",
            (int(item_id),),
        ).fetchone()
        if existing is None:
            return 0
        cur.execute(
            "UPDATE memory_items SET kind=?, text=?, embedding=?, meta_json=?, created_at=?, tier=?, repeat_count=?, access_count=?, last_accessed_at=? WHERE id=?",
            (
                kind,
                text,
                embedding_blob,
                meta_json,
                time.time(),
                tier if tier is not None else existing[0],
                int(repeat_count) if repeat_count is not None else int(existing[1]),
                int(access_count) if access_count is not None else int(existing[2]),
                float(last_accessed_at) if last_accessed_at is not None else float(existing[3] or time.time()),
                int(item_id),
            ),
        )
        updated = cur.rowcount
        self._conn.commit()
        return int(updated)

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
        cur = self._conn.cursor()
        row = cur.execute(
            "SELECT repeat_count, access_count, tier FROM memory_items WHERE id=?",
            (int(item_id),),
        ).fetchone()
        if row is None:
            return 0
        return self.update_memory_item(
            item_id=int(item_id),
            kind=kind,
            text=text,
            embedding_blob=embedding_blob,
            meta_json=meta_json,
            tier=tier if tier is not None else row[2],
            repeat_count=int(row[0]) + 1,
            access_count=int(row[1]),
            last_accessed_at=time.time(),
        )

    def note_memory_access(self, item_ids: Iterable[int]) -> int:
        ids = [int(x) for x in item_ids if int(x) > 0]
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        now = time.time()
        cur = self._conn.cursor()
        cur.execute(
            f"UPDATE memory_items SET access_count=COALESCE(access_count, 0)+1, last_accessed_at=? WHERE id IN ({placeholders})",
            (now, *ids),
        )
        updated = cur.rowcount
        self._conn.commit()
        return int(updated)

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
        cur = self._conn.cursor()
        now_ts = float(now if now is not None else time.time())
        filters = ""
        params: list[Any] = []
        if user_key is not None:
            filters = " AND user_key=?"
            params.append(user_key)

        cur.execute(
            f"UPDATE memory_items SET tier='medium' WHERE tier='short' AND repeat_count>?{filters}",
            (int(short_promote_repeat), *params),
        )
        promoted_to_medium = int(cur.rowcount)

        cur.execute(
            f"UPDATE memory_items SET tier='long' WHERE tier='medium' AND access_count>?{filters}",
            (int(medium_promote_access), *params),
        )
        promoted_to_long = int(cur.rowcount)

        cur.execute(
            f"DELETE FROM memory_items WHERE tier='short' AND COALESCE(last_accessed_at, created_at) < ?{filters}",
            (now_ts - float(short_ttl_s), *params),
        )
        deleted_short = int(cur.rowcount)

        cur.execute(
            f"UPDATE memory_items SET tier='short' WHERE tier='medium' AND COALESCE(last_accessed_at, created_at) < ?{filters}",
            (now_ts - float(medium_ttl_s), *params),
        )
        degraded_to_short = int(cur.rowcount)

        self._conn.commit()
        return {
            "promoted_to_medium": promoted_to_medium,
            "promoted_to_long": promoted_to_long,
            "deleted_short": deleted_short,
            "degraded_to_short": degraded_to_short,
        }

    def list_user_memory_items(self, user_key: str, *, limit: int = 5) -> list[dict[str, Any]]:
        return self.search_memory_items(user_key=user_key, limit=limit)

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
        cur = self._conn.cursor()
        clauses = ["user_key=?"]
        params: list[Any] = [user_key]
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        where = " AND ".join(clauses)
        cur.execute(
            f"""
            DELETE FROM memory_items
            WHERE id IN (
                SELECT id FROM memory_items
                WHERE {where}
                ORDER BY created_at DESC
                LIMIT -1 OFFSET ?
            )
            """,
            tuple(params + [int(keep_last)]),
        )
        self._conn.commit()

    # tool calls

    def log_tool_call(self, session_id: str, user_key: str, agent_id: str, tool_name: str, args_json: str, ok: bool, result_excerpt: str, error: str, duration_ms: float, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> None:
        if tenant_id is None and workspace_id is None and environment is None:
            inferred = self._infer_scope_from_session(session_id)
            tenant_id = inferred.get("tenant_id")
            workspace_id = inferred.get("workspace_id")
            environment = inferred.get("environment")
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO tool_calls(ts, session_id, user_key, agent_id, tool_name, args_json, ok, result_excerpt, error, duration_ms, tenant_id, workspace_id, environment)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (time.time(), session_id, user_key, agent_id, tool_name, args_json, 1 if ok else 0, result_excerpt, error, float(duration_ms), tenant_id, workspace_id, environment),
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
        backend = getattr(self._conn, "backend", "sqlite")
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
        )
        if backend == "postgresql":
            cur.execute(
                """
                INSERT INTO decision_traces(trace_id, ts, session_id, user_key, channel, agent_id, request_text, response_text, status, provider, model, latency_ms, estimated_cost, llm_calls, input_tokens, output_tokens, total_tokens, context_json, memory_json, tools_considered_json, tools_used_json, policies_json, decisions_json, tenant_id, workspace_id, environment)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(trace_id) DO UPDATE SET
                    ts=EXCLUDED.ts,
                    session_id=EXCLUDED.session_id,
                    user_key=EXCLUDED.user_key,
                    channel=EXCLUDED.channel,
                    agent_id=EXCLUDED.agent_id,
                    request_text=EXCLUDED.request_text,
                    response_text=EXCLUDED.response_text,
                    status=EXCLUDED.status,
                    provider=EXCLUDED.provider,
                    model=EXCLUDED.model,
                    latency_ms=EXCLUDED.latency_ms,
                    estimated_cost=EXCLUDED.estimated_cost,
                    llm_calls=EXCLUDED.llm_calls,
                    input_tokens=EXCLUDED.input_tokens,
                    output_tokens=EXCLUDED.output_tokens,
                    total_tokens=EXCLUDED.total_tokens,
                    context_json=EXCLUDED.context_json,
                    memory_json=EXCLUDED.memory_json,
                    tools_considered_json=EXCLUDED.tools_considered_json,
                    tools_used_json=EXCLUDED.tools_used_json,
                    policies_json=EXCLUDED.policies_json,
                    decisions_json=EXCLUDED.decisions_json,
                    tenant_id=EXCLUDED.tenant_id,
                    workspace_id=EXCLUDED.workspace_id,
                    environment=EXCLUDED.environment
                """,
                values,
            )
        else:
            cur.execute(
                """
                INSERT INTO decision_traces(trace_id, ts, session_id, user_key, channel, agent_id, request_text, response_text, status, provider, model, latency_ms, estimated_cost, llm_calls, input_tokens, output_tokens, total_tokens, context_json, memory_json, tools_considered_json, tools_used_json, policies_json, decisions_json, tenant_id, workspace_id, environment)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(trace_id) DO UPDATE SET
                    ts=excluded.ts,
                    session_id=excluded.session_id,
                    user_key=excluded.user_key,
                    channel=excluded.channel,
                    agent_id=excluded.agent_id,
                    request_text=excluded.request_text,
                    response_text=excluded.response_text,
                    status=excluded.status,
                    provider=excluded.provider,
                    model=excluded.model,
                    latency_ms=excluded.latency_ms,
                    estimated_cost=excluded.estimated_cost,
                    llm_calls=excluded.llm_calls,
                    input_tokens=excluded.input_tokens,
                    output_tokens=excluded.output_tokens,
                    total_tokens=excluded.total_tokens,
                    context_json=excluded.context_json,
                    memory_json=excluded.memory_json,
                    tools_considered_json=excluded.tools_considered_json,
                    tools_used_json=excluded.tools_used_json,
                    policies_json=excluded.policies_json,
                    decisions_json=excluded.decisions_json,
                    tenant_id=excluded.tenant_id,
                    workspace_id=excluded.workspace_id,
                    environment=excluded.environment
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
        sql = "SELECT trace_id, ts, session_id, user_key, channel, agent_id, request_text, response_text, status, provider, model, latency_ms, estimated_cost, llm_calls, input_tokens, output_tokens, total_tokens, context_json, memory_json, tools_considered_json, tools_used_json, policies_json, decisions_json, tenant_id, workspace_id, environment FROM decision_traces"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY ts DESC LIMIT ?"
        params.append(int(limit))
        rows = cur.execute(sql, tuple(params)).fetchall()
        return [self._decision_trace_row_to_dict(r) for r in rows]

    def get_decision_trace(self, trace_id: str) -> dict[str, Any] | None:
        cur = self._conn.cursor()
        row = cur.execute(
            "SELECT trace_id, ts, session_id, user_key, channel, agent_id, request_text, response_text, status, provider, model, latency_ms, estimated_cost, llm_calls, input_tokens, output_tokens, total_tokens, context_json, memory_json, tools_considered_json, tools_used_json, policies_json, decisions_json, tenant_id, workspace_id, environment FROM decision_traces WHERE trace_id=?",
            (trace_id,),
        ).fetchone()
        return self._decision_trace_row_to_dict(row) if row is not None else None

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
        raw_token = secrets.token_urlsafe(32)
        now = time.time()
        expires_at = now + int(ttl_s) if ttl_s else None
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        token_prefix = raw_token[:10]
        cur = self._conn.cursor()
        cur.execute(
            "INSERT INTO api_tokens(user_key, label, token_hash, token_prefix, scopes_json, created_at, expires_at, last_used_at, revoked_at, tenant_id, workspace_id, environment) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (user_key, label.strip() or "token", token_hash, token_prefix, json.dumps(list(scopes or ["broker"]), ensure_ascii=False), now, expires_at, None, None, tenant_id, workspace_id, environment),
        )
        token_id = int(cur.lastrowid)
        self._conn.commit()
        return {"id": token_id, "user_key": user_key, "label": label.strip() or "token", "token": raw_token, "token_prefix": token_prefix, "scopes": list(scopes or ["broker"]), "created_at": float(now), "expires_at": float(expires_at) if expires_at is not None else None, "tenant_id": tenant_id, "workspace_id": workspace_id, "environment": environment}

    def list_api_tokens(self, *, user_key: str | None = None, include_revoked: bool = False, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        if user_key is not None:
            clauses.append("user_key=?")
            params.append(user_key)
        if not include_revoked:
            clauses.append("revoked_at IS NULL")
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = "SELECT id, user_key, label, token_prefix, scopes_json, created_at, expires_at, last_used_at, revoked_at, tenant_id, workspace_id, environment FROM api_tokens"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC"
        rows = cur.execute(sql, tuple(params)).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            try:
                scopes = json.loads(r["scopes_json"]) if r["scopes_json"] else []
            except Exception:
                scopes = []
            out.append({"id": int(r["id"]), "user_key": r["user_key"], "label": r["label"], "token_prefix": r["token_prefix"], "scopes": scopes, "created_at": float(r["created_at"]), "expires_at": float(r["expires_at"]) if r["expires_at"] is not None else None, "last_used_at": float(r["last_used_at"]) if r["last_used_at"] is not None else None, "revoked_at": float(r["revoked_at"]) if r["revoked_at"] is not None else None, "tenant_id": r["tenant_id"], "workspace_id": r["workspace_id"], "environment": r["environment"]})
        return out

    def get_api_token(self, raw_token: str, *, idle_ttl_s: int | None = None) -> dict[str, Any] | None:
        if not raw_token:
            return None
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        cur = self._conn.cursor()
        row = cur.execute("SELECT id, user_key, label, token_prefix, scopes_json, created_at, expires_at, last_used_at, revoked_at, tenant_id, workspace_id, environment FROM api_tokens WHERE token_hash=?", (token_hash,)).fetchone()
        if row is None or row["revoked_at"] is not None:
            return None
        now_ts = time.time()
        if row["expires_at"] is not None and float(row["expires_at"]) <= now_ts:
            return None
        if idle_ttl_s is not None and int(idle_ttl_s or 0) > 0:
            last_seen = float(row["last_used_at"]) if row["last_used_at"] is not None else float(row["created_at"])
            if last_seen + int(idle_ttl_s) <= now_ts:
                return None
        try:
            scopes = json.loads(row["scopes_json"]) if row["scopes_json"] else []
        except Exception:
            scopes = []
        return {"id": int(row["id"]), "user_key": row["user_key"], "label": row["label"], "token_prefix": row["token_prefix"], "scopes": scopes, "created_at": float(row["created_at"]), "expires_at": float(row["expires_at"]) if row["expires_at"] is not None else None, "last_used_at": float(row["last_used_at"]) if row["last_used_at"] is not None else None, "tenant_id": row["tenant_id"], "workspace_id": row["workspace_id"], "environment": row["environment"]}

    def touch_api_token(self, raw_token: str) -> int:
        if not raw_token:
            return 0
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        cur = self._conn.cursor()
        cur.execute("UPDATE api_tokens SET last_used_at=? WHERE token_hash=?", (time.time(), token_hash))
        updated = cur.rowcount
        self._conn.commit()
        return int(updated)

    def revoke_api_token(self, *, token_id: int | None = None, raw_token: str | None = None) -> int:
        if token_id is None and not raw_token:
            return 0
        cur = self._conn.cursor()
        if token_id is not None:
            cur.execute("UPDATE api_tokens SET revoked_at=? WHERE id=? AND revoked_at IS NULL", (time.time(), int(token_id)))
        else:
            token_hash = hashlib.sha256(str(raw_token).encode("utf-8")).hexdigest()
            cur.execute("UPDATE api_tokens SET revoked_at=? WHERE token_hash=? AND revoked_at IS NULL", (time.time(), token_hash))
        updated = cur.rowcount
        self._conn.commit()
        return int(updated)

    def rotate_api_token(self, *, token_id: int, ttl_s: int | None = None, user_key: str | None = None) -> dict[str, Any] | None:
        cur = self._conn.cursor()
        row = cur.execute(
            "SELECT id, user_key, label, scopes_json, tenant_id, workspace_id, environment FROM api_tokens WHERE id=? AND revoked_at IS NULL",
            (int(token_id),),
        ).fetchone()
        if row is None:
            return None
        token_user_key = str(row["user_key"])
        if user_key is not None and token_user_key != str(user_key):
            return None
        try:
            scopes = json.loads(row["scopes_json"]) if row["scopes_json"] else []
        except Exception:
            scopes = []
        rotated = self.create_api_token(
            user_key=token_user_key,
            label=str(row["label"]),
            scopes=list(scopes),
            ttl_s=ttl_s,
            tenant_id=row["tenant_id"],
            workspace_id=row["workspace_id"],
            environment=row["environment"],
        )
        cur.execute("UPDATE api_tokens SET revoked_at=? WHERE id=? AND revoked_at IS NULL", (time.time(), int(token_id)))
        self._conn.commit()
        return rotated

    def cleanup_api_tokens(self, *, idle_ttl_s: int | None = None) -> dict[str, int]:
        now = time.time()
        cur = self._conn.cursor()
        cur.execute("UPDATE api_tokens SET revoked_at=? WHERE revoked_at IS NULL AND expires_at IS NOT NULL AND expires_at<=?", (now, now))
        expired = int(cur.rowcount)
        idle_revoked = 0
        if idle_ttl_s is not None and int(idle_ttl_s or 0) > 0:
            threshold = now - int(idle_ttl_s)
            cur.execute(
                "UPDATE api_tokens SET revoked_at=? WHERE revoked_at IS NULL AND COALESCE(last_used_at, created_at)<=?",
                (now, threshold),
            )
            idle_revoked = int(cur.rowcount)
        self._conn.commit()
        return {"expired": expired, "idle_revoked": idle_revoked}

    # auth users / sessions

    def _hash_password(self, password: str, salt_hex: str | None = None, iterations: int = 200000) -> tuple[str, str]:
        import hashlib
        salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", str(password).encode("utf-8"), salt, int(iterations))
        return salt.hex(), digest.hex()

    def has_auth_users(self) -> bool:
        cur = self._conn.cursor()
        return bool(cur.execute("SELECT COUNT(*) FROM auth_users").fetchone()[0])

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
        username = str(username).strip()
        if not username:
            raise ValueError("username is required")
        user_key = str(user_key or f"user:{username}").strip()
        salt_hex, hash_hex = self._hash_password(password)
        now = time.time()
        cur = self._conn.cursor()
        existing = cur.execute("SELECT id FROM auth_users WHERE username=?", (username,)).fetchone()
        if existing is None:
            cur.execute(
                "INSERT INTO auth_users(username, user_key, password_salt, password_hash, role, is_active, created_at, updated_at, last_login_at, tenant_id, workspace_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (username, user_key, salt_hex, hash_hex, str(role or 'user'), 1, now, now, None, tenant_id, workspace_id),
            )
            user_id = int(cur.lastrowid)
        else:
            user_id = int(existing[0])
            cur.execute(
                "UPDATE auth_users SET user_key=?, password_salt=?, password_hash=?, role=?, is_active=1, updated_at=?, tenant_id=COALESCE(tenant_id, ?), workspace_id=COALESCE(workspace_id, ?) WHERE id=?",
                (user_key, salt_hex, hash_hex, str(role or 'user'), now, tenant_id, workspace_id, user_id),
            )
        self._conn.commit()
        return self.get_auth_user(user_id=user_id) or {"id": user_id, "username": username, "user_key": user_key, "role": role, "tenant_id": tenant_id, "workspace_id": workspace_id}

    def get_auth_user(self, *, user_id: int | None = None, username: str | None = None, user_key: str | None = None) -> dict[str, Any] | None:
        cur = self._conn.cursor()
        if user_id is not None:
            row = cur.execute("SELECT id, username, user_key, role, is_active, created_at, updated_at, last_login_at, tenant_id, workspace_id FROM auth_users WHERE id=?", (int(user_id),)).fetchone()
        elif username is not None:
            row = cur.execute("SELECT id, username, user_key, role, is_active, created_at, updated_at, last_login_at, tenant_id, workspace_id FROM auth_users WHERE username=?", (str(username),)).fetchone()
        elif user_key is not None:
            row = cur.execute("SELECT id, username, user_key, role, is_active, created_at, updated_at, last_login_at, tenant_id, workspace_id FROM auth_users WHERE user_key=?", (str(user_key),)).fetchone()
        else:
            return None
        if row is None:
            return None
        return {
            "id": int(row["id"]),
            "username": row["username"],
            "user_key": row["user_key"],
            "role": row["role"],
            "is_active": bool(row["is_active"]),
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
            "last_login_at": float(row["last_login_at"]) if row["last_login_at"] is not None else None,
            "tenant_id": row["tenant_id"],
            "workspace_id": row["workspace_id"],
        }

    def list_auth_users(self, *, tenant_id: str | None = None, workspace_id: str | None = None) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id)
        sql = "SELECT id, username, user_key, role, is_active, created_at, updated_at, last_login_at, tenant_id, workspace_id FROM auth_users"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at ASC"
        rows = cur.execute(sql, tuple(params)).fetchall()
        return [
            {
                "id": int(r["id"]),
                "username": r["username"],
                "user_key": r["user_key"],
                "role": r["role"],
                "is_active": bool(r["is_active"]),
                "created_at": float(r["created_at"]),
                "updated_at": float(r["updated_at"]),
                "last_login_at": float(r["last_login_at"]) if r["last_login_at"] is not None else None,
                "tenant_id": r["tenant_id"],
                "workspace_id": r["workspace_id"],
            }
            for r in rows
        ]

    def verify_auth_user(self, *, username: str, password: str) -> dict[str, Any] | None:
        cur = self._conn.cursor()
        row = cur.execute(
            "SELECT id, username, user_key, password_salt, password_hash, role, is_active, created_at, updated_at, last_login_at, tenant_id, workspace_id FROM auth_users WHERE username=?",
            (str(username).strip(),),
        ).fetchone()
        if row is None or not bool(row["is_active"]):
            return None
        _, digest_hex = self._hash_password(password, salt_hex=row["password_salt"])
        if not secrets.compare_digest(digest_hex, row["password_hash"]):
            return None
        now = time.time()
        cur.execute("UPDATE auth_users SET last_login_at=?, updated_at=? WHERE id=?", (now, now, int(row["id"])))
        self._conn.commit()
        return self.get_auth_user(user_id=int(row["id"]))

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
        raw_token = secrets.token_urlsafe(32)
        now = time.time()
        expires_at = now + int(ttl_s) if ttl_s else None
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        token_prefix = raw_token[:10]
        user = self.get_auth_user(user_id=int(user_id)) or {}
        cur = self._conn.cursor()
        effective_tenant = tenant_id if tenant_id is not None else user.get("tenant_id")
        effective_workspace = workspace_id if workspace_id is not None else user.get("workspace_id")
        effective_environment = environment
        cur.execute(
            "INSERT INTO auth_sessions(user_id, label, token_hash, token_prefix, created_at, expires_at, last_used_at, revoked_at, tenant_id, workspace_id, environment) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (int(user_id), str(label or 'ui'), token_hash, token_prefix, now, expires_at, None, None, effective_tenant, effective_workspace, effective_environment),
        )
        session_id = int(cur.lastrowid)
        self._conn.commit()
        return {
            "id": session_id,
            "token": raw_token,
            "token_prefix": token_prefix,
            "label": str(label or 'ui'),
            "created_at": float(now),
            "expires_at": float(expires_at) if expires_at is not None else None,
            "tenant_id": effective_tenant,
            "workspace_id": effective_workspace,
            "environment": effective_environment,
            "user": user,
        }

    def list_auth_sessions(self, *, user_id: int | None = None, include_revoked: bool = False, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        if user_id is not None:
            clauses.append("s.user_id=?")
            params.append(int(user_id))
        if not include_revoked:
            clauses.append("s.revoked_at IS NULL")
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, prefix="s")
        sql = (
            "SELECT s.id, s.user_id, s.label, s.token_prefix, s.created_at, s.expires_at, s.last_used_at, s.revoked_at, s.tenant_id, s.workspace_id, s.environment, "
            "u.username, u.user_key, u.role, u.is_active "
            "FROM auth_sessions s JOIN auth_users u ON u.id=s.user_id"
        )
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY s.created_at DESC"
        rows = cur.execute(sql, tuple(params)).fetchall()
        return [
            {
                "id": int(r["id"]),
                "user_id": int(r["user_id"]),
                "label": r["label"],
                "token_prefix": r["token_prefix"],
                "created_at": float(r["created_at"]),
                "expires_at": float(r["expires_at"]) if r["expires_at"] is not None else None,
                "last_used_at": float(r["last_used_at"]) if r["last_used_at"] is not None else None,
                "revoked_at": float(r["revoked_at"]) if r["revoked_at"] is not None else None,
                "username": r["username"],
                "user_key": r["user_key"],
                "role": r["role"],
                "is_active": bool(r["is_active"]),
                "tenant_id": r["tenant_id"],
                "workspace_id": r["workspace_id"],
                "environment": r["environment"],
            }
            for r in rows
        ]

    def get_auth_session(self, raw_token: str, *, idle_ttl_s: int | None = None) -> dict[str, Any] | None:
        if not raw_token:
            return None
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        cur = self._conn.cursor()
        row = cur.execute(
            "SELECT s.id, s.user_id, s.label, s.token_prefix, s.created_at, s.expires_at, s.last_used_at, s.revoked_at, s.tenant_id, s.workspace_id, s.environment, u.username, u.user_key, u.role, u.is_active FROM auth_sessions s JOIN auth_users u ON u.id=s.user_id WHERE s.token_hash=?",
            (token_hash,),
        ).fetchone()
        if row is None or row["revoked_at"] is not None or not bool(row["is_active"]):
            return None
        now_ts = time.time()
        if row["expires_at"] is not None and float(row["expires_at"]) <= now_ts:
            return None
        if idle_ttl_s is not None and int(idle_ttl_s or 0) > 0:
            last_seen = float(row["last_used_at"]) if row["last_used_at"] is not None else float(row["created_at"])
            if last_seen + int(idle_ttl_s) <= now_ts:
                return None
        return {
            "id": int(row["id"]),
            "user_id": int(row["user_id"]),
            "label": row["label"],
            "token_prefix": row["token_prefix"],
            "created_at": float(row["created_at"]),
            "expires_at": float(row["expires_at"]) if row["expires_at"] is not None else None,
            "last_used_at": float(row["last_used_at"]) if row["last_used_at"] is not None else None,
            "username": row["username"],
            "user_key": row["user_key"],
            "role": row["role"],
            "tenant_id": row["tenant_id"],
            "workspace_id": row["workspace_id"],
            "environment": row["environment"],
        }

    def touch_auth_session(self, raw_token: str) -> int:
        if not raw_token:
            return 0
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        cur = self._conn.cursor()
        cur.execute("UPDATE auth_sessions SET last_used_at=? WHERE token_hash=?", (time.time(), token_hash))
        updated = cur.rowcount
        self._conn.commit()
        return int(updated)

    def revoke_auth_session(self, *, raw_token: str | None = None, session_id: int | None = None) -> int:
        if not raw_token and session_id is None:
            return 0
        cur = self._conn.cursor()
        if raw_token:
            token_hash = hashlib.sha256(str(raw_token).encode("utf-8")).hexdigest()
            cur.execute("UPDATE auth_sessions SET revoked_at=? WHERE token_hash=? AND revoked_at IS NULL", (time.time(), token_hash))
        else:
            cur.execute("UPDATE auth_sessions SET revoked_at=? WHERE id=? AND revoked_at IS NULL", (time.time(), int(session_id)))
        updated = cur.rowcount
        self._conn.commit()
        return int(updated)

    def revoke_auth_sessions_for_user(self, *, user_id: int, keep_session_id: int | None = None) -> int:
        cur = self._conn.cursor()
        if keep_session_id is None:
            cur.execute("UPDATE auth_sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL", (time.time(), int(user_id)))
        else:
            cur.execute(
                "UPDATE auth_sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL AND id<>?",
                (time.time(), int(user_id), int(keep_session_id)),
            )
        updated = cur.rowcount
        self._conn.commit()
        return int(updated)

    def rotate_auth_session(self, *, raw_token: str | None = None, session_id: int | None = None, ttl_s: int | None = None) -> dict[str, Any] | None:
        cur = self._conn.cursor()
        row = None
        if raw_token:
            token_hash = hashlib.sha256(str(raw_token).encode("utf-8")).hexdigest()
            row = cur.execute("SELECT id, user_id, label, tenant_id, workspace_id, environment FROM auth_sessions WHERE token_hash=? AND revoked_at IS NULL", (token_hash,)).fetchone()
        elif session_id is not None:
            row = cur.execute("SELECT id, user_id, label, tenant_id, workspace_id, environment FROM auth_sessions WHERE id=? AND revoked_at IS NULL", (int(session_id),)).fetchone()
        if row is None:
            return None
        rotated = self.create_auth_session(
            user_id=int(row["user_id"]),
            label=str(row["label"] or "ui"),
            ttl_s=ttl_s,
            tenant_id=row["tenant_id"],
            workspace_id=row["workspace_id"],
            environment=row["environment"],
        )
        cur.execute("UPDATE auth_sessions SET revoked_at=? WHERE id=? AND revoked_at IS NULL", (time.time(), int(row["id"])))
        self._conn.commit()
        return rotated

    def cleanup_auth_sessions(self, *, idle_ttl_s: int | None = None) -> dict[str, int]:
        now = time.time()
        cur = self._conn.cursor()
        cur.execute("UPDATE auth_sessions SET revoked_at=? WHERE revoked_at IS NULL AND expires_at IS NOT NULL AND expires_at<=?", (now, now))
        expired = int(cur.rowcount)
        idle_revoked = 0
        if idle_ttl_s is not None and int(idle_ttl_s or 0) > 0:
            threshold = now - int(idle_ttl_s)
            cur.execute(
                "UPDATE auth_sessions SET revoked_at=? WHERE revoked_at IS NULL AND COALESCE(last_used_at, created_at)<=?",
                (now, threshold),
            )
            idle_revoked = int(cur.rowcount)
        self._conn.commit()
        return {"expired": expired, "idle_revoked": idle_revoked}

    def _memory_row_to_dict(self, row: CompatRow | Any) -> dict[str, Any]:
        try:
            meta = json.loads(row["meta_json"]) if row["meta_json"] else {}
        except Exception:
            meta = {"_raw": row["meta_json"]}
        return {
            "id": int(row["id"]),
            "user_key": row["user_key"],
            "kind": row["kind"],
            "text": row["text"],
            "embedding": row["embedding"],
            "meta": meta,
            "created_at": float(row["created_at"]),
            "tier": row["tier"] or "medium",
            "access_count": int(row["access_count"] or 0),
            "repeat_count": int(row["repeat_count"] or 1),
            "last_accessed_at": float(row["last_accessed_at"] or row["created_at"]),
            "tenant_id": getattr(row, "__getitem__", lambda *_: None)("tenant_id") if isinstance(row, dict) or hasattr(row, "keys") else None,
            "workspace_id": getattr(row, "__getitem__", lambda *_: None)("workspace_id") if isinstance(row, dict) or hasattr(row, "keys") else None,
            "environment": getattr(row, "__getitem__", lambda *_: None)("environment") if isinstance(row, dict) or hasattr(row, "keys") else None,
        }

    # workflows / approvals / jobs

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
        if bundle['status'] not in {'candidate', 'approved'}:
            raise ValueError('release must be in candidate before approval')
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
        try:
            metadata = json.loads(row['metadata_json'] or '{}')
        except Exception:
            metadata = {}
        return {
            'voice_session_id': row['voice_session_id'],
            'channel': row['channel'],
            'user_key': row['user_key'],
            'status': row['status'],
            'locale': row['locale'],
            'stt_provider': row['stt_provider'],
            'tts_provider': row['tts_provider'],
            'started_at': float(row['started_at']),
            'updated_at': float(row['updated_at']),
            'closed_at': float(row['closed_at']) if row['closed_at'] is not None else None,
            'last_transcript_text': row['last_transcript_text'] or '',
            'last_output_text': row['last_output_text'] or '',
            'metadata': metadata,
            'tenant_id': row['tenant_id'],
            'workspace_id': row['workspace_id'],
            'environment': row['environment'],
        }

    def _voice_transcript_row_to_dict(self, row: Any) -> dict[str, Any]:
        try:
            metadata = json.loads(row['metadata_json'] or '{}')
        except Exception:
            metadata = {}
        return {
            'id': int(row['id']),
            'voice_session_id': row['voice_session_id'],
            'direction': row['direction'],
            'stage': row['stage'],
            'text': row['text'],
            'confidence': float(row['confidence']) if row['confidence'] is not None else None,
            'language': row['language'] or '',
            'created_by': row['created_by'] or '',
            'created_at': float(row['created_at']),
            'metadata': metadata,
            'tenant_id': row['tenant_id'],
            'workspace_id': row['workspace_id'],
            'environment': row['environment'],
        }

    def _voice_output_row_to_dict(self, row: Any) -> dict[str, Any]:
        try:
            metadata = json.loads(row['metadata_json'] or '{}')
        except Exception:
            metadata = {}
        return {
            'output_id': row['output_id'],
            'voice_session_id': row['voice_session_id'],
            'text': row['text'],
            'status': row['status'],
            'voice_name': row['voice_name'],
            'audio_ref': row['audio_ref'] or '',
            'created_by': row['created_by'] or '',
            'created_at': float(row['created_at']),
            'metadata': metadata,
            'tenant_id': row['tenant_id'],
            'workspace_id': row['workspace_id'],
            'environment': row['environment'],
        }

    def _voice_command_row_to_dict(self, row: Any) -> dict[str, Any]:
        try:
            payload = json.loads(row['command_payload_json'] or '{}')
        except Exception:
            payload = {}
        try:
            metadata = json.loads(row['metadata_json'] or '{}')
        except Exception:
            metadata = {}
        return {
            'command_id': row['command_id'],
            'voice_session_id': row['voice_session_id'],
            'command_name': row['command_name'],
            'command_payload': payload,
            'status': row['status'],
            'requires_confirmation': bool(row['requires_confirmation']),
            'confirmed_by': row['confirmed_by'] or '',
            'confirmed_at': float(row['confirmed_at']) if row['confirmed_at'] is not None else None,
            'created_at': float(row['created_at']),
            'updated_at': float(row['updated_at']),
            'metadata': metadata,
            'tenant_id': row['tenant_id'],
            'workspace_id': row['workspace_id'],
            'environment': row['environment'],
        }

    def count_voice_sessions(self, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = 'SELECT COUNT(*) FROM voice_sessions'
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        return int(cur.execute(sql, tuple(params)).fetchone()[0])

    def count_voice_transcripts(self, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = 'SELECT COUNT(*) FROM voice_transcripts'
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        return int(cur.execute(sql, tuple(params)).fetchone()[0])

    def count_voice_outputs(self, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = 'SELECT COUNT(*) FROM voice_outputs'
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        return int(cur.execute(sql, tuple(params)).fetchone()[0])

    def count_voice_commands(self, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = 'SELECT COUNT(*) FROM voice_commands'
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        return int(cur.execute(sql, tuple(params)).fetchone()[0])

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
        voice_session_id = str(uuid.uuid4())
        now = time.time()
        cur = self._conn.cursor()
        cur.execute(
            'INSERT INTO voice_sessions(voice_session_id, channel, user_key, status, locale, stt_provider, tts_provider, started_at, updated_at, closed_at, last_transcript_text, last_output_text, metadata_json, tenant_id, workspace_id, environment) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (voice_session_id, channel, user_key, 'active', locale, stt_provider, tts_provider, now, now, None, '', '', json.dumps(metadata or {}, ensure_ascii=False), tenant_id, workspace_id, environment),
        )
        self._conn.commit()
        return self.get_voice_session(voice_session_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment) or {
            'voice_session_id': voice_session_id,
            'channel': channel,
            'user_key': user_key,
            'status': 'active',
            'locale': locale,
            'stt_provider': stt_provider,
            'tts_provider': tts_provider,
            'started_at': float(now),
            'updated_at': float(now),
            'closed_at': None,
            'last_transcript_text': '',
            'last_output_text': '',
            'metadata': dict(metadata or {}),
            'tenant_id': tenant_id,
            'workspace_id': workspace_id,
            'environment': environment,
        }

    def list_voice_sessions(self, *, limit: int = 50, status: str | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if status is not None:
            clauses.append('status=?')
            params.append(status)
        sql = 'SELECT voice_session_id, channel, user_key, status, locale, stt_provider, tts_provider, started_at, updated_at, closed_at, last_transcript_text, last_output_text, metadata_json, tenant_id, workspace_id, environment FROM voice_sessions'
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        sql += ' ORDER BY updated_at DESC LIMIT ?'
        params.append(int(limit))
        return [self._voice_session_row_to_dict(row) for row in cur.execute(sql, tuple(params)).fetchall()]

    def get_voice_session(self, voice_session_id: str, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any] | None:
        cur = self._conn.cursor()
        clauses = ['voice_session_id=?']
        params: list[Any] = [voice_session_id]
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        row = cur.execute(
            'SELECT voice_session_id, channel, user_key, status, locale, stt_provider, tts_provider, started_at, updated_at, closed_at, last_transcript_text, last_output_text, metadata_json, tenant_id, workspace_id, environment FROM voice_sessions WHERE ' + ' AND '.join(clauses) + ' LIMIT 1',
            tuple(params),
        ).fetchone()
        return self._voice_session_row_to_dict(row) if row is not None else None

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
        current = self.get_voice_session(voice_session_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if current is None:
            return None
        next_metadata = dict(current.get('metadata') or {})
        next_metadata.update(dict(metadata or {}))
        now = time.time()
        cur = self._conn.cursor()
        cur.execute(
            'UPDATE voice_sessions SET status=?, updated_at=?, closed_at=?, last_transcript_text=?, last_output_text=?, metadata_json=? WHERE voice_session_id=?',
            (
                status or current.get('status') or 'active',
                now,
                now if closed else current.get('closed_at'),
                last_transcript_text if last_transcript_text is not None else current.get('last_transcript_text') or '',
                last_output_text if last_output_text is not None else current.get('last_output_text') or '',
                json.dumps(next_metadata, ensure_ascii=False),
                voice_session_id,
            ),
        )
        self._conn.commit()
        return self.get_voice_session(voice_session_id, tenant_id=current.get('tenant_id'), workspace_id=current.get('workspace_id'), environment=current.get('environment'))

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
        now = time.time()
        cur = self._conn.cursor()
        cur.execute(
            'INSERT INTO voice_transcripts(voice_session_id, direction, stage, text, confidence, language, created_by, created_at, metadata_json, tenant_id, workspace_id, environment) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
            (voice_session_id, direction, stage, text, confidence, language or '', created_by or '', now, json.dumps(metadata or {}, ensure_ascii=False), tenant_id, workspace_id, environment),
        )
        row_id = int(cur.lastrowid)
        cur.execute('UPDATE voice_sessions SET updated_at=?, last_transcript_text=? WHERE voice_session_id=?', (now, text, voice_session_id))
        self._conn.commit()
        row = cur.execute('SELECT id, voice_session_id, direction, stage, text, confidence, language, created_by, created_at, metadata_json, tenant_id, workspace_id, environment FROM voice_transcripts WHERE id=?', (row_id,)).fetchone()
        return self._voice_transcript_row_to_dict(row)

    def list_voice_transcripts(self, voice_session_id: str, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        clauses = ['voice_session_id=?']
        params: list[Any] = [voice_session_id]
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = 'SELECT id, voice_session_id, direction, stage, text, confidence, language, created_by, created_at, metadata_json, tenant_id, workspace_id, environment FROM voice_transcripts WHERE ' + ' AND '.join(clauses) + ' ORDER BY id ASC LIMIT ?'
        params.append(int(limit))
        return [self._voice_transcript_row_to_dict(row) for row in cur.execute(sql, tuple(params)).fetchall()]

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
        output_id = str(uuid.uuid4())
        now = time.time()
        cur = self._conn.cursor()
        cur.execute(
            'INSERT INTO voice_outputs(output_id, voice_session_id, text, status, voice_name, audio_ref, created_by, created_at, metadata_json, tenant_id, workspace_id, environment) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
            (output_id, voice_session_id, text, status, voice_name, audio_ref or '', created_by or '', now, json.dumps(metadata or {}, ensure_ascii=False), tenant_id, workspace_id, environment),
        )
        cur.execute('UPDATE voice_sessions SET updated_at=?, last_output_text=? WHERE voice_session_id=?', (now, text, voice_session_id))
        self._conn.commit()
        row = cur.execute('SELECT output_id, voice_session_id, text, status, voice_name, audio_ref, created_by, created_at, metadata_json, tenant_id, workspace_id, environment FROM voice_outputs WHERE output_id=?', (output_id,)).fetchone()
        return self._voice_output_row_to_dict(row)

    def list_voice_outputs(self, voice_session_id: str, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        clauses = ['voice_session_id=?']
        params: list[Any] = [voice_session_id]
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = 'SELECT output_id, voice_session_id, text, status, voice_name, audio_ref, created_by, created_at, metadata_json, tenant_id, workspace_id, environment FROM voice_outputs WHERE ' + ' AND '.join(clauses) + ' ORDER BY created_at ASC LIMIT ?'
        params.append(int(limit))
        return [self._voice_output_row_to_dict(row) for row in cur.execute(sql, tuple(params)).fetchall()]

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
        command_id = str(uuid.uuid4())
        now = time.time()
        confirmed_at = now if confirmed_by else None
        cur = self._conn.cursor()
        cur.execute(
            'INSERT INTO voice_commands(command_id, voice_session_id, command_name, command_payload_json, status, requires_confirmation, confirmed_by, confirmed_at, created_at, updated_at, metadata_json, tenant_id, workspace_id, environment) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (command_id, voice_session_id, command_name, json.dumps(command_payload or {}, ensure_ascii=False), status, 1 if requires_confirmation else 0, confirmed_by or None, confirmed_at, now, now, json.dumps(metadata or {}, ensure_ascii=False), tenant_id, workspace_id, environment),
        )
        self._conn.commit()
        row = cur.execute('SELECT command_id, voice_session_id, command_name, command_payload_json, status, requires_confirmation, confirmed_by, confirmed_at, created_at, updated_at, metadata_json, tenant_id, workspace_id, environment FROM voice_commands WHERE command_id=?', (command_id,)).fetchone()
        return self._voice_command_row_to_dict(row)

    def list_voice_commands(self, voice_session_id: str, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        clauses = ['voice_session_id=?']
        params: list[Any] = [voice_session_id]
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = 'SELECT command_id, voice_session_id, command_name, command_payload_json, status, requires_confirmation, confirmed_by, confirmed_at, created_at, updated_at, metadata_json, tenant_id, workspace_id, environment FROM voice_commands WHERE ' + ' AND '.join(clauses) + ' ORDER BY created_at ASC LIMIT ?'
        params.append(int(limit))
        return [self._voice_command_row_to_dict(row) for row in cur.execute(sql, tuple(params)).fetchall()]

    def get_latest_pending_voice_command(self, voice_session_id: str, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any] | None:
        cur = self._conn.cursor()
        clauses = ['voice_session_id=?', 'status=?']
        params: list[Any] = [voice_session_id, 'pending_confirmation']
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        row = cur.execute(
            'SELECT command_id, voice_session_id, command_name, command_payload_json, status, requires_confirmation, confirmed_by, confirmed_at, created_at, updated_at, metadata_json, tenant_id, workspace_id, environment FROM voice_commands WHERE ' + ' AND '.join(clauses) + ' ORDER BY created_at DESC LIMIT 1',
            tuple(params),
        ).fetchone()
        return self._voice_command_row_to_dict(row) if row is not None else None

    def resolve_voice_command(self, command_id: str, *, decision: str, actor: str, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any] | None:
        cur = self._conn.cursor()
        clauses = ['command_id=?']
        params: list[Any] = [command_id]
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        row = cur.execute(
            'SELECT command_id, voice_session_id, command_name, command_payload_json, status, requires_confirmation, confirmed_by, confirmed_at, created_at, updated_at, metadata_json, tenant_id, workspace_id, environment FROM voice_commands WHERE ' + ' AND '.join(clauses) + ' LIMIT 1',
            tuple(params),
        ).fetchone()
        if row is None:
            return None
        current = self._voice_command_row_to_dict(row)
        now = time.time()
        next_status = 'confirmed' if decision == 'confirm' else 'cancelled'
        cur.execute(
            'UPDATE voice_commands SET status=?, confirmed_by=?, confirmed_at=?, updated_at=? WHERE command_id=?',
            (next_status, actor, now, now, command_id),
        )
        self._conn.commit()
        return self.get_latest_voice_command(command_id)

    def get_latest_voice_command(self, command_id: str) -> dict[str, Any] | None:
        cur = self._conn.cursor()
        row = cur.execute(
            'SELECT command_id, voice_session_id, command_name, command_payload_json, status, requires_confirmation, confirmed_by, confirmed_at, created_at, updated_at, metadata_json, tenant_id, workspace_id, environment FROM voice_commands WHERE command_id=? LIMIT 1',
            (command_id,),
        ).fetchone()
        return self._voice_command_row_to_dict(row) if row is not None else None


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
        items = self.get_recent_events(limit=max(int(limit or 50), 1) * 3, channel='canvas', tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        filtered = [item for item in items if str(item.get('session_id') or '') == str(canvas_id)]
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


    def _voice_audio_asset_row_to_dict(self, row: Any) -> dict[str, Any]:
        try:
            metadata = json.loads(row['metadata_json'] or '{}')
        except Exception:
            metadata = {}
        return {
            'asset_id': row['asset_id'],
            'voice_session_id': row['voice_session_id'],
            'direction': row['direction'],
            'asset_kind': row['asset_kind'],
            'mime_type': row['mime_type'],
            'sample_rate_hz': int(row['sample_rate_hz'] or 0),
            'byte_count': int(row['byte_count'] or 0),
            'sha256': row['sha256'] or '',
            'storage_ref': row['storage_ref'] or '',
            'created_by': row['created_by'] or '',
            'created_at': float(row['created_at']),
            'metadata': metadata,
            'tenant_id': row['tenant_id'],
            'workspace_id': row['workspace_id'],
            'environment': row['environment'],
        }

    def _voice_provider_call_row_to_dict(self, row: Any) -> dict[str, Any]:
        try:
            request = json.loads(row['request_json'] or '{}')
        except Exception:
            request = {}
        try:
            response = json.loads(row['response_json'] or '{}')
        except Exception:
            response = {}
        return {
            'provider_call_id': row['provider_call_id'],
            'voice_session_id': row['voice_session_id'],
            'provider_kind': row['provider_kind'],
            'provider_name': row['provider_name'],
            'status': row['status'],
            'request': request,
            'response': response,
            'error_text': row['error_text'] or '',
            'latency_ms': float(row['latency_ms']) if row['latency_ms'] is not None else None,
            'created_by': row['created_by'] or '',
            'created_at': float(row['created_at']),
            'tenant_id': row['tenant_id'],
            'workspace_id': row['workspace_id'],
            'environment': row['environment'],
        }

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
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = 'SELECT COUNT(*) FROM voice_audio_assets'
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        return int(cur.execute(sql, tuple(params)).fetchone()[0])

    def count_voice_provider_calls(self, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> int:
        cur = self._conn.cursor()
        clauses: list[str] = []
        params: list[Any] = []
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = 'SELECT COUNT(*) FROM voice_provider_calls'
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        return int(cur.execute(sql, tuple(params)).fetchone()[0])

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
        asset_id = str(uuid.uuid4())
        now = time.time()
        cur = self._conn.cursor()
        cur.execute('INSERT INTO voice_audio_assets(asset_id, voice_session_id, direction, asset_kind, mime_type, sample_rate_hz, byte_count, sha256, storage_ref, created_by, created_at, metadata_json, tenant_id, workspace_id, environment) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (asset_id, voice_session_id, direction, asset_kind, mime_type, int(sample_rate_hz or 0), int(byte_count or 0), sha256 or '', storage_ref or '', created_by or '', now, json.dumps(metadata or {}, ensure_ascii=False), tenant_id, workspace_id, environment))
        self._conn.commit()
        row = cur.execute('SELECT asset_id, voice_session_id, direction, asset_kind, mime_type, sample_rate_hz, byte_count, sha256, storage_ref, created_by, created_at, metadata_json, tenant_id, workspace_id, environment FROM voice_audio_assets WHERE asset_id=?', (asset_id,)).fetchone()
        return self._voice_audio_asset_row_to_dict(row)

    def list_voice_audio_assets(self, voice_session_id: str, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        clauses = ['voice_session_id=?']
        params: list[Any] = [voice_session_id]
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = 'SELECT asset_id, voice_session_id, direction, asset_kind, mime_type, sample_rate_hz, byte_count, sha256, storage_ref, created_by, created_at, metadata_json, tenant_id, workspace_id, environment FROM voice_audio_assets WHERE ' + ' AND '.join(clauses) + ' ORDER BY created_at ASC LIMIT ?'
        params.append(int(limit))
        return [self._voice_audio_asset_row_to_dict(row) for row in cur.execute(sql, tuple(params)).fetchall()]

    def create_voice_provider_call(self, voice_session_id: str, *, provider_kind: str, provider_name: str, status: str, request: dict[str, Any] | None = None, response: dict[str, Any] | None = None, error_text: str = '', latency_ms: float | None = None, created_by: str = '', tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any]:
        provider_call_id = str(uuid.uuid4())
        now = time.time()
        cur = self._conn.cursor()
        cur.execute('INSERT INTO voice_provider_calls(provider_call_id, voice_session_id, provider_kind, provider_name, status, request_json, response_json, error_text, latency_ms, created_by, created_at, tenant_id, workspace_id, environment) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (provider_call_id, voice_session_id, provider_kind, provider_name, status, json.dumps(request or {}, ensure_ascii=False), json.dumps(response or {}, ensure_ascii=False), error_text or '', latency_ms, created_by or '', now, tenant_id, workspace_id, environment))
        self._conn.commit()
        row = cur.execute('SELECT provider_call_id, voice_session_id, provider_kind, provider_name, status, request_json, response_json, error_text, latency_ms, created_by, created_at, tenant_id, workspace_id, environment FROM voice_provider_calls WHERE provider_call_id=?', (provider_call_id,)).fetchone()
        return self._voice_provider_call_row_to_dict(row)

    def list_voice_provider_calls(self, voice_session_id: str, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        clauses = ['voice_session_id=?']
        params: list[Any] = [voice_session_id]
        self._scope_where(clauses, params, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        sql = 'SELECT provider_call_id, voice_session_id, provider_kind, provider_name, status, request_json, response_json, error_text, latency_ms, created_by, created_at, tenant_id, workspace_id, environment FROM voice_provider_calls WHERE ' + ' AND '.join(clauses) + ' ORDER BY created_at ASC LIMIT ?'
        params.append(int(limit))
        return [self._voice_provider_call_row_to_dict(row) for row in cur.execute(sql, tuple(params)).fetchall()]

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
