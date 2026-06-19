"""Audit hash-chain — PR 2c (chain decision_traces + trigger).

With decision_traces append-only (PR 2b), every version row now computes a
chain link on write, `openmiura db verify-chain` covers it, and migration 26
makes it engine-level tamper-proof. This completes tamper-evidence for all
three audit tables.
"""
from __future__ import annotations

import sqlite3

import pytest

from openmiura.core.db import DBConnection
from openmiura.core.migrations import apply_migrations
from openmiura.persistence.tools_repo import ToolsRepo
from openmiura.persistence.hashchain import CHAINED_TABLES, verify_audit_chain
from openmiura.persistence.base import canonical_chain_scope


def _conn(tmp_path):
    c = DBConnection(backend="sqlite", db_path=(tmp_path / "audit.db").as_posix(), database_url="")
    apply_migrations(c)
    return c


def _log(repo, trace_id, **over):
    kw = dict(trace_id=trace_id, session_id="s", user_key="u", channel="http", agent_id="default",
              request_text="q", response_text="", status="completed",
              tenant_id="acme", workspace_id="w", environment="prod")
    kw.update(over)
    repo.log_decision_trace(**kw)


def test_decision_traces_is_a_chained_table():
    assert "decision_traces" in CHAINED_TABLES


def test_decision_trace_rows_are_chained(tmp_path):
    conn = _conn(tmp_path)
    repo = ToolsRepo(conn)
    _log(repo, "t1")
    _log(repo, "t2")
    rows = conn.cursor().execute(
        "SELECT chain_seq, prev_hash, row_hash FROM decision_traces ORDER BY chain_seq"
    ).fetchall()
    assert [r[0] for r in rows] == [1, 2]          # chain_seq per scope
    assert rows[0][1] == ""                          # genesis prev_hash
    assert rows[1][1] == rows[0][2]                  # links to previous row_hash
    assert all(r[2] for r in rows)                   # row_hash populated


def test_each_version_is_a_distinct_chained_row(tmp_path):
    conn = _conn(tmp_path)
    repo = ToolsRepo(conn)
    _log(repo, "t1", status="started")
    _log(repo, "t1", status="completed")
    # Both versions are chained entries (chain covers every streamed update).
    rows = conn.cursor().execute(
        "SELECT version, chain_seq FROM decision_traces WHERE trace_id='t1' ORDER BY version"
    ).fetchall()
    assert [(r[0], r[1]) for r in rows] == [(1, 1), (2, 2)]


def test_verify_chain_covers_decision_traces_intact(tmp_path):
    conn = _conn(tmp_path)
    repo = ToolsRepo(conn)
    _log(repo, "t1", status="started")
    _log(repo, "t1", status="completed")
    _log(repo, "t2")
    res = verify_audit_chain(conn, chain_table="decision_traces")
    assert res["any_tamper"] is False
    for chain in res["chains"]:
        assert chain["chain_valid"] and chain["head_matches"]


def test_trigger_rejects_update_and_delete(tmp_path):
    conn = _conn(tmp_path)
    _log(ToolsRepo(conn), "t1")
    with pytest.raises(sqlite3.IntegrityError):
        conn.cursor().execute("UPDATE decision_traces SET status='x'")
    with pytest.raises(sqlite3.IntegrityError):
        conn.cursor().execute("DELETE FROM decision_traces")


def test_verify_chain_detects_tamper_after_dropping_trigger(tmp_path):
    conn = _conn(tmp_path)
    repo = ToolsRepo(conn)
    _log(repo, "t1")
    _log(repo, "t2")
    # Tampering requires first dropping the guard (an auditable schema change).
    cur = conn.cursor()
    cur.execute("DROP TRIGGER IF EXISTS trg_decision_traces_no_update")
    cur.execute("UPDATE decision_traces SET response_text='forged' WHERE chain_seq=1")
    conn.commit()
    res = verify_audit_chain(conn, chain_table="decision_traces")
    assert res["any_tamper"] is True
    assert any(c["first_bad_seq"] == 1 for c in res["chains"])
