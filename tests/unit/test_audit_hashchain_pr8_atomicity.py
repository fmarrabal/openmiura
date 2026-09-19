"""Audit hash-chain — PR 8 (atomicity, orphan heads, serializer parity).

Regression tests for five defects found by an adversarial audit. Every one of
them was reproducible on the previous implementation, and three of them broke
the chain on a perfectly honest system — no attacker involved — which is worse
than a missed tamper: it makes `verify-chain` cry wolf forever.

  * concurrent writers were handed the same chain_seq (unsynchronised
    read-modify-write of the per-scope head on a connection shared across
    threads);
  * a failed row INSERT left the head advanced, so the next writer committed
    an orphan and opened a permanent gap;
  * deleting every row of a scope left an orphan head the verifier never
    looked at, so wholesale deletion reported "intact";
  * `events` hashed the pre-serialization payload while the verifier hashed
    the JSON round-trip, so a payload with non-string keys failed verification
    untampered;
  * `decision_traces` filtered unchained rows out of the verifier's own query,
    so a forged row was invisible even as preexisting_count.
"""
from __future__ import annotations

import threading

from openmiura.core.db import DBConnection
from openmiura.core.migrations import apply_migrations
from openmiura.persistence.hashchain import verify_audit_chain
from openmiura.persistence.sessions_repo import SessionsRepo
from openmiura.persistence.tools_repo import ToolsRepo


def _conn(tmp_path):
    c = DBConnection(backend="sqlite", db_path=(tmp_path / "audit.db").as_posix(), database_url="")
    apply_migrations(c)
    return c


def _scope(**over):
    base = {"tenant_id": "acme", "workspace_id": "w", "environment": "prod"}
    base.update(over)
    return base


def _drop_triggers(conn, table):
    cur = conn.cursor()
    for (name,) in cur.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (table,)
    ).fetchall():
        cur.execute(f"DROP TRIGGER {name}")
    conn.commit()


# ======================================================================
# Concurrency: the chain must survive parallel writers.
# ======================================================================


def test_concurrent_writers_get_distinct_chain_seq(tmp_path) -> None:
    """8 threads logging at once must produce 8 distinct, contiguous links.

    Before the fix they raced on `SELECT head` -> `UPDATE head`, so several
    rows shared a chain_seq. The append-only triggers then make that duplicate
    impossible to repair, and verify-chain reports TAMPER for the life of the
    database.
    """
    conn = _conn(tmp_path)
    repo = SessionsRepo(conn)
    errors: list[str] = []

    def write(i: int) -> None:
        try:
            repo.log_event("in", "http", "u", "s", {"i": i}, **_scope())
        except Exception as exc:  # pragma: no cover - only on regression
            errors.append(f"{type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=write, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"writers lost audit events: {errors}"
    seqs = [r[0] for r in conn.cursor().execute("SELECT chain_seq FROM events").fetchall()]
    assert len(seqs) == 8
    assert sorted(seqs) == list(range(1, 9)), f"duplicate/gapped chain_seq: {sorted(seqs)}"
    assert verify_audit_chain(conn, chain_table="events")["any_tamper"] is False


def test_concurrent_decision_traces_do_not_collide_on_version(tmp_path) -> None:
    """Same trace_id logged concurrently must version cleanly, not raise.

    MAX(version)+1 computed outside the serialised block collided on the
    composite PK, and the loser had already advanced the chain head.
    """
    conn = _conn(tmp_path)
    repo = ToolsRepo(conn)
    errors: list[str] = []

    def write(i: int) -> None:
        try:
            repo.log_decision_trace(
                trace_id="same-turn", session_id="s", user_key="u", channel="http",
                agent_id="default", request_text="q", response_text=f"r{i}",
                status="completed", **_scope(),
            )
        except Exception as exc:  # pragma: no cover - only on regression
            errors.append(f"{type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=write, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"decision-trace writes collided: {errors}"
    versions = [r[0] for r in conn.cursor().execute(
        "SELECT version FROM decision_traces WHERE trace_id='same-turn'").fetchall()]
    assert sorted(versions) == list(range(1, 7)), f"version collision: {sorted(versions)}"
    assert verify_audit_chain(conn, chain_table="decision_traces")["any_tamper"] is False


# ======================================================================
# Atomicity: a failed write must not poison the chain.
# ======================================================================


def test_failed_insert_does_not_advance_the_head(tmp_path) -> None:
    """A benign failed write (here a NOT NULL violation) must roll back.

    Before the fix the head advanced first, the INSERT failed, and the next
    successful write committed the orphan — a permanent chain_seq gap from an
    ordinary application bug.
    """
    conn = _conn(tmp_path)
    repo = SessionsRepo(conn)
    repo.log_event("in", "http", "u", "s", {"i": 1}, **_scope())

    try:
        repo.log_event("in", "http", None, "s", {"i": 2}, **_scope())
    except Exception:
        pass  # the write is expected to fail; the chain must not care

    repo.log_event("in", "http", "u", "s", {"i": 3}, **_scope())

    seqs = [r[0] for r in conn.cursor().execute(
        "SELECT chain_seq FROM events ORDER BY chain_seq").fetchall()]
    assert seqs == [1, 2], f"failed write left a gap: {seqs}"
    assert verify_audit_chain(conn, chain_table="events")["any_tamper"] is False


# ======================================================================
# Orphan heads: deleting everything is still tamper.
# ======================================================================


def test_deleting_every_row_of_a_scope_is_detected(tmp_path) -> None:
    """Wholesale deletion of a scope must not read as intact.

    The verifier used to derive its scope set from surviving rows only, so a
    scope with zero rows left was never visited — while its head sat in
    audit_chain_heads, unread, contradicting it.
    """
    conn = _conn(tmp_path)
    repo = SessionsRepo(conn)
    for i in range(3):
        repo.log_event("in", "http", "u", "s", {"i": i}, **_scope(tenant_id="acme"))
    for i in range(2):
        repo.log_event("in", "http", "u", "s", {"i": i}, **_scope(tenant_id="other"))

    assert verify_audit_chain(conn, chain_table="events")["any_tamper"] is False

    _drop_triggers(conn, "events")
    conn.cursor().execute("DELETE FROM events WHERE tenant_id='acme'")
    conn.commit()

    result = verify_audit_chain(conn, chain_table="events")
    assert result["any_tamper"] is True, "an erased scope reported intact"
    erased = [c for c in result["chains"] if c["count"] == 0]
    assert erased, "the erased scope was not reported at all"
    assert erased[0]["head_matches"] is False


def test_truncating_a_table_entirely_is_detected(tmp_path) -> None:
    conn = _conn(tmp_path)
    repo = SessionsRepo(conn)
    for i in range(3):
        repo.log_event("in", "http", "u", "s", {"i": i}, **_scope())

    _drop_triggers(conn, "events")
    conn.cursor().execute("DELETE FROM events")
    conn.commit()

    assert verify_audit_chain(conn, chain_table="events")["any_tamper"] is True


# ======================================================================
# Serializer parity: an honest chain must verify.
# ======================================================================


def test_payload_with_non_string_keys_still_verifies(tmp_path) -> None:
    """The writer must hash what it stores.

    `events` hashed the in-memory payload while the verifier could only rebuild
    it by re-parsing payload_json. {2: 'b', 10: 'a'} sorts numerically before
    the round-trip and lexicographically after, so an untampered chain failed.
    """
    conn = _conn(tmp_path)
    SessionsRepo(conn).log_event("in", "http", "u", "s", {"steps": {2: "b", 10: "a"}}, **_scope())
    assert verify_audit_chain(conn, chain_table="events")["any_tamper"] is False


def test_payload_tamper_is_still_detected(tmp_path) -> None:
    """The parity fix must not blunt detection."""
    conn = _conn(tmp_path)
    SessionsRepo(conn).log_event("in", "http", "u", "s", {"amount": 10}, **_scope())
    _drop_triggers(conn, "events")
    conn.cursor().execute("UPDATE events SET payload_json='{\"amount\": 999}'")
    conn.commit()
    assert verify_audit_chain(conn, chain_table="events")["any_tamper"] is True


# ======================================================================
# Visibility: an unchained row must never be invisible.
# ======================================================================


def test_unchained_decision_trace_row_is_surfaced(tmp_path) -> None:
    """A row inserted with NULL chain columns must at least be counted.

    The verifier's own SELECT filtered `chain_seq IS NOT NULL`, so a forged
    decision_traces row was not merely unverified — it did not appear in the
    report at all, while the application read it as a genuine record.
    """
    conn = _conn(tmp_path)
    conn.cursor().execute(
        "INSERT INTO decision_traces(trace_id, ts, session_id, user_key, channel, agent_id, "
        "request_text, response_text, status, tenant_id, workspace_id, environment) "
        "VALUES('forged', 1.0, 's', 'u', 'http', 'default', 'q', 'approved', 'ok', 'acme', 'w', 'prod')"
    )
    conn.commit()

    result = verify_audit_chain(conn, chain_table="decision_traces")
    total_seen = sum(c["count"] + c["preexisting_count"] for c in result["chains"])
    assert total_seen == 1, f"the unchained row was invisible to the verifier: {result}"
    assert result["chains"][0]["preexisting_count"] == 1
