"""Audit hash-chain — PR 4 (append-only triggers).

Migration 24 makes append-only a DB-enforced guarantee on the two chained
tables: any UPDATE or DELETE on events / tool_calls aborts at the engine.
The write path only INSERTs, so logging is unaffected; decision_traces is
deliberately NOT guarded (it upserts until option-A lands).
"""
from __future__ import annotations

import sqlite3

import pytest

from openmiura.core.db import DBConnection
from openmiura.core.migrations import apply_migrations
from openmiura.persistence.sessions_repo import SessionsRepo
from openmiura.persistence.tools_repo import ToolsRepo


def _conn(tmp_path):
    c = DBConnection(backend="sqlite", db_path=(tmp_path / "audit.db").as_posix(), database_url="")
    apply_migrations(c)
    return c


def test_write_path_insert_still_works(tmp_path):
    """The triggers fire on UPDATE/DELETE only — INSERT (the write path) is
    unaffected, so logging keeps working and keeps chaining."""
    conn = _conn(tmp_path)
    SessionsRepo(conn).log_event("in", "http", "u", "s", {"i": 1}, tenant_id="acme", workspace_id="w", environment="prod")
    ToolsRepo(conn).log_tool_call("s", "u", "default", "lookup", "{}", True, "ok", "", 1.0,
                                  tenant_id="acme", workspace_id="w", environment="prod")
    assert conn.cursor().execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
    assert conn.cursor().execute("SELECT COUNT(*) FROM tool_calls").fetchone()[0] == 1


@pytest.mark.parametrize("table", ["events", "tool_calls"])
def test_update_is_rejected(tmp_path, table):
    conn = _conn(tmp_path)
    SessionsRepo(conn).log_event("in", "http", "u", "s", {"i": 1})
    ToolsRepo(conn).log_tool_call("s", "u", "default", "lookup", "{}", True, "ok", "", 1.0)
    with pytest.raises(sqlite3.IntegrityError):
        conn.cursor().execute(f"UPDATE {table} SET session_id='x'")


@pytest.mark.parametrize("table", ["events", "tool_calls"])
def test_delete_is_rejected(tmp_path, table):
    conn = _conn(tmp_path)
    SessionsRepo(conn).log_event("in", "http", "u", "s", {"i": 1})
    ToolsRepo(conn).log_tool_call("s", "u", "default", "lookup", "{}", True, "ok", "", 1.0)
    with pytest.raises(sqlite3.IntegrityError):
        conn.cursor().execute(f"DELETE FROM {table}")


def test_all_three_audit_tables_are_guarded(tmp_path):
    """events + tool_calls (migration 24) and decision_traces (migration 26,
    after it became append-only) all carry the UPDATE/DELETE-reject guard."""
    conn = _conn(tmp_path)
    triggers = {
        r[0] for r in conn.cursor().execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        ).fetchall()
    }
    assert "trg_events_no_update" in triggers
    assert "trg_tool_calls_no_delete" in triggers
    assert "trg_decision_traces_no_update" in triggers
    assert "trg_decision_traces_no_delete" in triggers


def test_triggers_dropped_on_downgrade(tmp_path):
    from openmiura.core.migrations import downgrade_migrations

    conn = _conn(tmp_path)
    downgrade_migrations(conn, target_version=23)  # undo migration 24 only
    triggers = {
        r[0] for r in conn.cursor().execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        ).fetchall()
    }
    assert not any(t.startswith("trg_events_") or t.startswith("trg_tool_calls_") for t in triggers)
    # And UPDATE works again once the guard is gone.
    SessionsRepo(conn).log_event("in", "http", "u", "s", {"i": 1})
    conn.cursor().execute("UPDATE events SET session_id='x'")
    conn.commit()
