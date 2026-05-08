"""MemoryRepo: persistence for the memory domain of openMiura.

Owns the persistence logic for the memory-related tables. The class
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


class MemoryRepo:
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
