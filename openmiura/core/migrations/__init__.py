"""``openmiura.core.migrations`` — schema migrations for the audit store.

The ``MIGRATIONS`` tuple is concatenated from a number of ``_batch_NNN`` modules (split mechanically to keep each file under the 1,500-line ceiling). The ``Migration`` dataclass and the lifecycle helpers (`apply_migrations`, `backup_database`, etc.) live here.
"""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openmiura.core.db import DBConnection, _normalize_backend


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sqlite_sql: tuple[str, ...]
    postgres_sql: tuple[str, ...]
    sqlite_down_sql: tuple[str, ...] = ()
    postgres_down_sql: tuple[str, ...] = ()

    def sql_for(self, backend: str) -> tuple[str, ...]:
        return self.postgres_sql if _normalize_backend(backend) == "postgresql" else self.sqlite_sql

    def down_sql_for(self, backend: str) -> tuple[str, ...]:
        return self.postgres_down_sql if _normalize_backend(backend) == "postgresql" else self.sqlite_down_sql


from openmiura.core.migrations._batch_001 import BATCH_001_MIGRATIONS
from openmiura.core.migrations._batch_002 import BATCH_002_MIGRATIONS
from openmiura.core.migrations._batch_003 import BATCH_003_MIGRATIONS


MIGRATIONS: tuple[Migration, ...] = (
    *BATCH_001_MIGRATIONS,
    *BATCH_002_MIGRATIONS,
    *BATCH_003_MIGRATIONS,
)

def _safe_execute(cursor, backend: str, sql: str, params: tuple[Any, ...] | None = None) -> None:
    try:
        cursor.execute(sql, params or ()) if params else cursor.execute(sql)
    except Exception as exc:
        text = str(exc).lower()
        ignorable = [
            "duplicate column",
            "already exists",
            "duplicate_table",
            "duplicate object",
            "no such table",
            "does not exist",
        ]
        if any(mark in text for mark in ignorable):
            return
        raise


def ensure_migration_table(conn: DBConnection) -> None:
    cur = conn.cursor()
    if conn.backend == "postgresql":
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at DOUBLE PRECISION NOT NULL
            )
            """
        )
    else:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at REAL NOT NULL
            )
            """
        )
    conn.commit()


def applied_versions(conn: DBConnection) -> set[int]:
    ensure_migration_table(conn)
    rows = conn.cursor().execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
    return {int(r[0]) for r in rows}


def current_schema_version(conn: DBConnection) -> int:
    versions = applied_versions(conn)
    return max(versions) if versions else 0


def _migration_by_version(version: int) -> Migration:
    for migration in MIGRATIONS:
        if migration.version == int(version):
            return migration
    raise KeyError(f"Unknown migration version: {version}")


def _sqlite_rebuild_memory_without_tiers(conn: DBConnection) -> None:
    cur = conn.cursor()
    cur.execute("DROP INDEX IF EXISTS idx_memory_user_tier")
    cur.execute("ALTER TABLE memory_items RENAME TO memory_items__old")
    cur.execute(
        """
        CREATE TABLE memory_items (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            user_key          TEXT NOT NULL,
            kind              TEXT NOT NULL,
            text              TEXT NOT NULL,
            embedding         BLOB NOT NULL,
            meta_json         TEXT NOT NULL,
            created_at        REAL NOT NULL
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_memory_user_created ON memory_items(user_key, created_at)")
    cur.execute(
        "INSERT INTO memory_items(id, user_key, kind, text, embedding, meta_json, created_at) SELECT id, user_key, kind, text, embedding, meta_json, created_at FROM memory_items__old"
    )
    cur.execute("DROP TABLE memory_items__old")
    conn.commit()




def _rollback_one(conn: DBConnection, migration: Migration) -> None:
    if migration.version == 2 and conn.backend == "sqlite":
        _sqlite_rebuild_memory_without_tiers(conn)
    else:
        cur = conn.cursor()
        for sql in migration.down_sql_for(conn.backend):
            _safe_execute(cur, conn.backend, sql)
        conn.commit()
    conn.cursor().execute("DELETE FROM schema_migrations WHERE version=?", (migration.version,))
    conn.commit()


def apply_migrations(conn: DBConnection) -> list[int]:
    ensure_migration_table(conn)
    already = applied_versions(conn)
    cur = conn.cursor()
    applied: list[int] = []
    for migration in MIGRATIONS:
        if migration.version in already:
            continue
        for sql in migration.sql_for(conn.backend):
            _safe_execute(cur, conn.backend, sql)
        if migration.version == 2:
            try:
                cur.execute(
                    "UPDATE memory_items SET last_accessed_at = COALESCE(last_accessed_at, created_at) WHERE last_accessed_at IS NULL"
                )
                cur.execute("UPDATE memory_items SET repeat_count = COALESCE(repeat_count, 1)")
                cur.execute("UPDATE memory_items SET access_count = COALESCE(access_count, 0)")
                cur.execute("UPDATE memory_items SET tier = COALESCE(NULLIF(TRIM(tier), ''), 'medium')")
            except Exception:
                pass
        cur.execute(
            "INSERT INTO schema_migrations(version, name, applied_at) VALUES(?,?,?)",
            (migration.version, migration.name, time.time()),
        )
        conn.commit()
        applied.append(migration.version)
    return applied


def downgrade_migrations(conn: DBConnection, *, target_version: int | None = None, steps: int | None = None) -> list[int]:
    ensure_migration_table(conn)
    current = current_schema_version(conn)
    if target_version is None:
        if steps is None or int(steps) <= 0:
            raise ValueError("Provide target_version or a positive steps value")
        target_version = max(0, current - int(steps))
    target = max(0, int(target_version))
    available = max((m.version for m in MIGRATIONS), default=0)
    if target > available:
        raise ValueError(f"Target version {target} exceeds available version {available}")
    if target >= current:
        return []
    rolled_back: list[int] = []
    for version in sorted((v for v in applied_versions(conn) if v > target), reverse=True):
        _rollback_one(conn, _migration_by_version(version))
        rolled_back.append(version)
    return rolled_back


def schema_status(conn: DBConnection) -> dict[str, Any]:
    ensure_migration_table(conn)
    rows = conn.cursor().execute(
        "SELECT version, name, applied_at FROM schema_migrations ORDER BY version"
    ).fetchall()
    return {
        "backend": conn.backend,
        "current_version": max((int(r[0]) for r in rows), default=0),
        "available_version": max((m.version for m in MIGRATIONS), default=0),
        "applied": [
            {"version": int(r[0]), "name": str(r[1]), "applied_at": float(r[2])}
            for r in rows
        ],
    }


def backup_database(*, backend: str, db_path: str, database_url: str, backup_dir: str) -> dict[str, Any]:
    backend = _normalize_backend(backend)
    target_dir = Path(backup_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    if backend == "sqlite":
        source_path = Path(db_path)
        backup_path = target_dir / f"openmiura-{stamp}.sqlite3"
        source = sqlite3.connect(str(source_path))
        dest = sqlite3.connect(str(backup_path))
        source.backup(dest)
        dest.close()
        source.close()
        return {"backend": backend, "backup_path": str(backup_path)}
    exe = shutil.which("pg_dump")
    if exe is None:
        raise RuntimeError("pg_dump not found in PATH; required for PostgreSQL backups")
    backup_path = target_dir / f"openmiura-{stamp}.sql"
    subprocess.run([exe, database_url, "-f", str(backup_path)], check=True)
    return {"backend": backend, "backup_path": str(backup_path)}


def restore_database(*, backend: str, db_path: str, database_url: str, backup_path: str) -> dict[str, Any]:
    backend = _normalize_backend(backend)
    source = Path(backup_path)
    if not source.exists():
        raise FileNotFoundError(f"Backup not found: {backup_path}")
    if backend == "sqlite":
        target = Path(db_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        src_conn = sqlite3.connect(str(source))
        dst_conn = sqlite3.connect(str(target))
        src_conn.backup(dst_conn)
        dst_conn.close()
        src_conn.close()
        return {"backend": backend, "restored_from": str(source), "db_path": str(target)}
    psql = shutil.which("psql")
    if psql is None:
        raise RuntimeError("psql not found in PATH; required for PostgreSQL restores")
    subprocess.run([psql, database_url, "-f", str(source)], check=True)
    return {"backend": backend, "restored_from": str(source), "database_url": database_url}
