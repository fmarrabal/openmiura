"""Audit hash-chain — PR 1 (additive schema + canonicalization helper).

This PR only lays the foundation: the link columns, the chain-heads cache
table, the indexes, and the shared hashing helper. No write path computes
links yet and no triggers exist; these tests pin that the migration is
additive, idempotent, and applies on a real schema, and that the helper's
digest is the one serializer of record (and dodges the two-serializer trap).
"""
from __future__ import annotations

import hashlib
import json
import sqlite3

from openmiura.core.migrations import MIGRATIONS, apply_migrations
from openmiura.core.db import DBConnection
from openmiura.persistence.base import (
    canonical_chain_scope,
    canonical_row_digest,
    parse_json_column,
)
from openmiura.evidence_verify import stable_digest


# ============================ migration ============================


def _columns(conn, table: str) -> set[str]:
    cur = conn.cursor()
    return {row[1] for row in cur.execute(f"PRAGMA table_info({table})").fetchall()}


def _table_exists(conn, name: str) -> bool:
    cur = conn.cursor()
    return cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _migrated_conn(tmp_path):
    db_path = (tmp_path / "audit.db").as_posix()
    conn = DBConnection(backend="sqlite", db_path=db_path, database_url="")
    apply_migrations(conn)
    return conn


def test_migration_23_is_registered():
    by_version = {m.version: m for m in MIGRATIONS}
    assert 23 in by_version
    assert by_version[23].name == "audit_hash_chain"
    # versions stay contiguous (no gaps) up to the latest
    assert sorted(by_version) == list(range(1, max(by_version) + 1))


def test_chain_columns_added_to_all_three_tables(tmp_path):
    conn = _migrated_conn(tmp_path)
    for table in ("events", "tool_calls", "decision_traces"):
        cols = _columns(conn, table)
        assert {"row_hash", "prev_hash", "chain_seq"}.issubset(cols), table


def test_chain_heads_table_and_indexes_exist(tmp_path):
    conn = _migrated_conn(tmp_path)
    assert _table_exists(conn, "audit_chain_heads")
    idx = {
        row[0]
        for row in conn.cursor().execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
    }
    assert {"idx_events_chain", "idx_tool_calls_chain", "idx_decision_traces_chain"}.issubset(idx)


def test_migration_is_idempotent(tmp_path):
    db_path = (tmp_path / "audit.db").as_posix()
    conn = DBConnection(backend="sqlite", db_path=db_path, database_url="")
    apply_migrations(conn)
    # Re-running must not raise (ADD COLUMN duplicates swallowed by _safe_execute).
    apply_migrations(conn)
    assert {"row_hash", "prev_hash", "chain_seq"}.issubset(_columns(conn, "events"))


def test_existing_inserts_still_work_with_null_link_columns(tmp_path):
    """The columns are nullable and no write path fills them yet, so a plain
    INSERT (the shape the repos use today) still succeeds."""
    conn = _migrated_conn(tmp_path)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO events(ts, direction, channel, user_id, session_id, payload_json) VALUES(?,?,?,?,?,?)",
        (1.0, "in", "http", "u1", "s1", json.dumps({"a": 1})),
    )
    conn.commit()
    row = cur.execute("SELECT row_hash, prev_hash, chain_seq FROM events").fetchone()
    assert tuple(row) == (None, None, None)


# ====================== canonicalization helper ======================


def test_canonical_row_digest_is_the_one_serializer():
    obj = {"b": 1, "a": 2, "z": {"k": [3, 2, 1]}, "u": "café ± δ"}
    # Same function as the offline verifier's stable_digest...
    assert canonical_row_digest(obj) == stable_digest(obj)
    # ...and equals an independent compact, sorted, UTF-8 SHA-256.
    expected = hashlib.sha256(
        json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert canonical_row_digest(obj) == expected


def test_two_serializer_trap_handled_by_reparsing():
    """A *_json column stored WITHOUT sort_keys must still produce a stable
    hash, because the chain hashes the re-parsed object, not the raw text."""
    payload = {"z": 1, "a": 2}
    stored = json.dumps(payload, ensure_ascii=False)  # NOT sort_keys → "{\"z\": 1, \"a\": 2}"
    # Re-parsing yields the object; hashing it is order-independent.
    assert canonical_row_digest(parse_json_column(stored)) == canonical_row_digest(payload)
    # Hashing the raw column text would NOT (proves why we re-parse).
    assert canonical_row_digest(stored) != canonical_row_digest(payload)


def test_parse_json_column_malformed_falls_back_to_raw():
    assert parse_json_column("{not json") == {"_raw": "{not json"}
    assert parse_json_column(None) is None


def test_canonical_chain_scope_collapses_nulls_and_is_collision_safe():
    unscoped = canonical_chain_scope(None, None, None)
    assert unscoped == canonical_chain_scope("", "", "")
    # Distinct scopes → distinct keys; a delimiter-bearing value can't collide.
    a = canonical_chain_scope("t|w", "x", "prod")
    b = canonical_chain_scope("t", "w|x", "prod")
    assert a != b
