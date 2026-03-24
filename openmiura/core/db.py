from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


class CompatRow:
    def __init__(self, columns: list[str], values: Iterable[Any]):
        self._columns = list(columns)
        self._values = list(values)
        self._map = {name: self._values[idx] for idx, name in enumerate(self._columns)}

    def __getitem__(self, key: int | str) -> Any:
        if isinstance(key, int):
            return self._values[key]
        return self._map[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self._map.get(key, default)

    def keys(self):
        return self._map.keys()

    def items(self):
        return self._map.items()

    def __iter__(self):
        return iter(self._values)


def _normalize_backend(value: str | None) -> str:
    backend = str(value or "sqlite").strip().lower()
    if backend in {"postgres", "postgresql", "psql"}:
        return "postgresql"
    return "sqlite"


@dataclass
class StorageSpec:
    backend: str = "sqlite"
    db_path: str = "data/audit.db"
    database_url: str = ""

    @property
    def normalized_backend(self) -> str:
        return _normalize_backend(self.backend)

    def effective_url(self) -> str:
        if self.normalized_backend == "sqlite":
            path = self.db_path or ":memory:"
            if path == ":memory:":
                return "sqlite:///:memory:"
            return f"sqlite:///{path}"
        return self.database_url


class DBConnection:
    def __init__(self, *, backend: str = "sqlite", db_path: str = "data/audit.db", database_url: str = "") -> None:
        self.backend = _normalize_backend(backend)
        self.db_path = db_path
        self.database_url = database_url
        if self.backend == "sqlite":
            if self.db_path != ":memory:":
                Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            try:
                self._conn.execute("PRAGMA journal_mode=WAL;")
                self._conn.execute("PRAGMA synchronous=NORMAL;")
            except Exception:
                pass
        else:
            try:
                import psycopg  # type: ignore
            except Exception as exc:
                raise RuntimeError(
                    "psycopg is required when storage.backend=postgresql. Install it with: pip install psycopg[binary]"
                ) from exc
            self._conn = psycopg.connect(self.database_url)

    def cursor(self):
        if self.backend == "sqlite":
            return self._conn.cursor()
        return PostgresCursorAdapter(self._conn.cursor())

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()


class PostgresCursorAdapter:
    def __init__(self, cursor) -> None:
        self._cursor = cursor
        self.rowcount = -1

    def execute(self, sql: str, params: Iterable[Any] | None = None):
        sql = self._translate_sql(sql)
        self._cursor.execute(sql, list(params or []))
        self.rowcount = getattr(self._cursor, "rowcount", -1)
        return self

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        cols = [d.name if hasattr(d, 'name') else d[0] for d in self._cursor.description]
        return CompatRow(cols, row)

    def fetchall(self):
        rows = self._cursor.fetchall()
        cols = [d.name if hasattr(d, 'name') else d[0] for d in self._cursor.description]
        return [CompatRow(cols, row) for row in rows]

    def _translate_sql(self, sql: str) -> str:
        translated = []
        in_single = False
        in_double = False
        for ch in sql:
            if ch == "'" and not in_double:
                in_single = not in_single
                translated.append(ch)
                continue
            if ch == '"' and not in_single:
                in_double = not in_double
                translated.append(ch)
                continue
            if ch == '?' and not in_single and not in_double:
                translated.append('%s')
            else:
                translated.append(ch)
        sql = ''.join(translated)
        sql = re.sub(r"INSERT\s+OR\s+IGNORE\s+INTO\s+slack_event_dedupe", "INSERT INTO slack_event_dedupe", sql, flags=re.IGNORECASE)
        if "INSERT INTO slack_event_dedupe" in sql and "ON CONFLICT" not in sql:
            sql = sql.rstrip().rstrip(';') + " ON CONFLICT (event_id) DO NOTHING"
        return sql
