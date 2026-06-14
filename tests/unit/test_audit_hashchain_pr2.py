"""Audit hash-chain — PR 2 (write-path wiring for events + tool_calls).

PR 1 added the columns + the canonicalization helper; this PR makes the
two genuinely append-only tables actually chain on write. Each row now
carries (prev_hash, row_hash, chain_seq); the chain is per-(table, scope),
genesis-anchored with prev_hash="" at chain_seq=1, and the per-scope head
advances atomically with the row insert.

(decision_traces — which legitimately upserts — needs option A immutable
versions and is wired in a separate PR.)
"""
from __future__ import annotations

from openmiura.core.db import DBConnection
from openmiura.core.migrations import apply_migrations
from openmiura.persistence.sessions_repo import SessionsRepo
from openmiura.persistence.tools_repo import ToolsRepo
from openmiura.persistence.base import (
    canonical_chain_scope,
    canonical_row_digest,
    parse_json_column,
)


def _conn(tmp_path):
    c = DBConnection(backend="sqlite", db_path=(tmp_path / "audit.db").as_posix(), database_url="")
    apply_migrations(c)
    return c


def _events(conn, scope=None):
    where = ""
    params: tuple = ()
    if scope is not None:
        where = " WHERE tenant_id=?"
        params = (scope,)
    return conn.cursor().execute(
        f"SELECT chain_seq, prev_hash, row_hash, ts, direction, channel, user_id, session_id, payload_json FROM events{where} ORDER BY chain_seq",
        params,
    ).fetchall()


def test_events_chain_links_and_increments_per_scope(tmp_path):
    conn = _conn(tmp_path)
    repo = SessionsRepo(conn)
    # Two distinct tenants → two independent chains.
    for i in range(3):
        repo.log_event("in", "http", "u", "s", {"i": i}, tenant_id="acme", workspace_id="w", environment="prod")
    for i in range(2):
        repo.log_event("in", "http", "u", "s", {"i": i}, tenant_id="beta", workspace_id="w", environment="prod")

    acme = _events(conn, "acme")
    beta = _events(conn, "beta")
    assert [r[0] for r in acme] == [1, 2, 3]      # chain_seq per scope
    assert [r[0] for r in beta] == [1, 2]
    # Genesis prev_hash is "" and each link points at the previous row_hash.
    assert acme[0][1] == ""
    assert acme[1][1] == acme[0][2]
    assert acme[2][1] == acme[1][2]
    assert beta[0][1] == ""
    assert beta[1][1] == beta[0][2]
    # Chains are independent: beta's genesis is not acme's head.
    assert beta[0][2] != acme[0][2]


def test_event_row_hash_is_reproducible_from_canonical(tmp_path):
    conn = _conn(tmp_path)
    SessionsRepo(conn).log_event("in", "http", "u1", "s1", {"k": "v"}, tenant_id="acme", workspace_id="w", environment="prod")
    seq, prev_hash, row_hash, ts, direction, channel, user_id, session_id, payload_json = _events(conn, "acme")[0]
    expected = canonical_row_digest({
        "chain_table": "events",
        "chain_scope": canonical_chain_scope("acme", "w", "prod"),
        "chain_seq": seq,
        "prev_hash": prev_hash,
        "row": {
            "ts": ts, "direction": direction, "channel": channel,
            "user_id": user_id, "session_id": session_id,
            "payload": parse_json_column(payload_json),
        },
    })
    assert row_hash == expected


def test_chain_head_advances_and_matches_last_row(tmp_path):
    conn = _conn(tmp_path)
    repo = SessionsRepo(conn)
    for i in range(3):
        repo.log_event("in", "http", "u", "s", {"i": i}, tenant_id="acme", workspace_id="w", environment="prod")
    scope = canonical_chain_scope("acme", "w", "prod")
    head = conn.cursor().execute(
        "SELECT head_hash, head_seq FROM audit_chain_heads WHERE chain_table='events' AND chain_scope=?",
        (scope,),
    ).fetchone()
    last = _events(conn, "acme")[-1]
    assert head[1] == 3                 # head_seq == last chain_seq
    assert head[0] == last[2]           # head_hash == last row_hash


def test_tool_calls_chain_and_reparse_args(tmp_path):
    conn = _conn(tmp_path)
    repo = ToolsRepo(conn)
    repo.log_tool_call("s", "u", "default", "lookup", '{"q": "x"}', True, "ok", "", 1.5,
                       tenant_id="acme", workspace_id="w", environment="prod")
    repo.log_tool_call("s", "u", "default", "lookup", '{"q": "y"}', True, "ok", "", 2.0,
                       tenant_id="acme", workspace_id="w", environment="prod")
    rows = conn.cursor().execute(
        "SELECT chain_seq, prev_hash, row_hash, ts, session_id, user_key, agent_id, tool_name, args_json, ok, result_excerpt, error, duration_ms FROM tool_calls ORDER BY chain_seq"
    ).fetchall()
    assert [r[0] for r in rows] == [1, 2]
    assert rows[0][1] == ""
    assert rows[1][1] == rows[0][2]
    # row_hash hashes the RE-PARSED args object, not the raw column text.
    r = rows[0]
    expected = canonical_row_digest({
        "chain_table": "tool_calls",
        "chain_scope": canonical_chain_scope("acme", "w", "prod"),
        "chain_seq": r[0],
        "prev_hash": r[1],
        "row": {
            "ts": r[3], "session_id": r[4], "user_key": r[5], "agent_id": r[6],
            "tool_name": r[7], "args": parse_json_column(r[8]),
            "ok": bool(r[9]), "result_excerpt": r[10], "error": r[11], "duration_ms": float(r[12]),
        },
    })
    assert r[2] == expected


def test_unscoped_rows_collapse_to_one_chain(tmp_path):
    conn = _conn(tmp_path)
    repo = SessionsRepo(conn)
    # No scope passed and the session row doesn't exist → inferred all-NULL.
    repo.log_event("in", "http", "u", "missing-session", {"i": 1})
    repo.log_event("in", "http", "u", "missing-session", {"i": 2})
    rows = conn.cursor().execute(
        "SELECT chain_seq, prev_hash, row_hash FROM events ORDER BY chain_seq"
    ).fetchall()
    assert [r[0] for r in rows] == [1, 2]
    assert rows[0][1] == ""
    assert rows[1][1] == rows[0][2]
    # One "unscoped" head exists.
    heads = conn.cursor().execute(
        "SELECT COUNT(*) FROM audit_chain_heads WHERE chain_table='events'"
    ).fetchone()[0]
    assert heads == 1
