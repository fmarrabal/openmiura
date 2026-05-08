"""SessionsRepo: persistence for the sessions domain of openMiura.

Owns the persistence logic for the sessions-related tables. The class
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


class SessionsRepo:
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
