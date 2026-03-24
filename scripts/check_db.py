from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any


def _safe_count(cur: sqlite3.Cursor, table: str) -> int | str:
    try:
        return int(cur.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    except Exception as exc:
        return f"ERROR: {exc}"


TABLES = [
    "memory_items",
    "sessions",
    "messages",
    "events",
    "telegram_state",
    "tool_calls",
    "identity_map",
]


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check openMiura SQLite operational tables.")
    parser.add_argument("--db", default="data/audit.db", help="Path to the SQLite database.")
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    args = parser.parse_args(argv)

    db_path = Path(args.db)
    if not db_path.exists():
        message = {"ok": False, "db": str(db_path), "error": "database file not found"}
        if args.json:
            print(json.dumps(message, ensure_ascii=False, indent=2))
        else:
            print(f"ERROR: database file not found: {db_path}", file=sys.stderr)
        return 2

    payload: dict[str, Any] = {"ok": True, "db": str(db_path), "tables": {}, "sample_memory": []}
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        for table in TABLES:
            payload["tables"][table] = _safe_count(cur, table)

        try:
            rows = cur.execute(
                """
                SELECT id, user_key, kind, substr(text,1,60) AS preview, length(embedding) AS embedding_len
                FROM memory_items
                WHERE user_key=?
                ORDER BY id DESC
                LIMIT 5
                """,
                ("test_user",),
            ).fetchall()
            payload["sample_memory"] = [dict(row) for row in rows]
        except Exception as exc:
            payload["sample_memory_error"] = str(exc)
    finally:
        conn.close()

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(f"openMiura DB check: {db_path}")
    for table, value in payload["tables"].items():
        print(f"{table} => {value}")
    if payload.get("sample_memory"):
        print("\nLast memory_items for test_user:")
        for row in payload["sample_memory"]:
            print(tuple(row.values()))
    elif payload.get("sample_memory_error"):
        print(f"\nERROR reading memory_items: {payload['sample_memory_error']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
