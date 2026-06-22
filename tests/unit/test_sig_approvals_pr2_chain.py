"""Signature-grade approvals — PR 2 (hash-chain release_approvals).

Every release action (submit / approve / promote / rollback) now computes a
per-(table,scope) chain link on write, mirroring events / tool_calls, and
`openmiura db verify-chain` covers the release_approvals table. This makes
the approval audit trail tamper-evident: any in-place edit or deletion
breaks the recomputed chain.

PR 2 adds NO append-only trigger (release_approvals is append-only by
convention; a DB-enforced guard is a later step), so these tests can mutate
rows directly to simulate tamper.
"""
from __future__ import annotations

from openmiura.core.db import DBConnection
from openmiura.core.migrations import apply_migrations
from openmiura.persistence.release_repo import ReleaseRepo
from openmiura.persistence.hashchain import CHAINED_TABLES, verify_audit_chain


def _conn(tmp_path):
    c = DBConnection(backend="sqlite", db_path=(tmp_path / "audit.db").as_posix(), database_url="")
    apply_migrations(c)
    return c


def _record(repo, action, **over):
    kw = dict(release_id="rel-1", actor="alice", action=action, reason="ok",
              tenant_id="acme", workspace_id="w", environment="prod")
    kw.update(over)
    return repo._record_release_action(**kw)


def test_release_approvals_is_a_chained_table():
    assert "release_approvals" in CHAINED_TABLES


def test_release_approval_rows_are_chained(tmp_path):
    conn = _conn(tmp_path)
    repo = ReleaseRepo(conn)
    _record(repo, "submit")
    _record(repo, "approve")
    rows = conn.cursor().execute(
        "SELECT chain_seq, prev_hash, row_hash FROM release_approvals ORDER BY chain_seq"
    ).fetchall()
    assert [r[0] for r in rows] == [1, 2]      # chain_seq per scope
    assert rows[0][1] == ""                      # genesis prev_hash
    assert rows[1][1] == rows[0][2]              # links to previous row_hash
    assert all(r[2] for r in rows)               # row_hash populated


def test_verify_chain_covers_release_approvals_intact(tmp_path):
    conn = _conn(tmp_path)
    repo = ReleaseRepo(conn)
    _record(repo, "submit")
    _record(repo, "approve")
    res = verify_audit_chain(conn, chain_table="release_approvals")
    assert res["any_tamper"] is False
    for chain in res["chains"]:
        assert chain["chain_valid"] and chain["head_matches"]


def test_verify_chain_detects_tampered_approval(tmp_path):
    conn = _conn(tmp_path)
    repo = ReleaseRepo(conn)
    _record(repo, "submit")
    _record(repo, "approve")
    # Mutate a row's content directly (no append-only trigger here yet).
    conn.cursor().execute("UPDATE release_approvals SET reason='forged' WHERE chain_seq=1")
    conn.commit()
    res = verify_audit_chain(conn, chain_table="release_approvals")
    assert res["any_tamper"] is True
    assert any(c["first_bad_seq"] == 1 for c in res["chains"])


def test_per_scope_chains_are_independent(tmp_path):
    conn = _conn(tmp_path)
    repo = ReleaseRepo(conn)
    _record(repo, "submit", release_id="rel-1", environment="prod")
    _record(repo, "submit", release_id="rel-2", environment="staging")
    # Each scope is a genesis chain of its own (chain_seq restarts at 1).
    seqs = {
        r[0]: r[1]
        for r in conn.cursor().execute(
            "SELECT environment, chain_seq FROM release_approvals"
        ).fetchall()
    }
    assert seqs == {"prod": 1, "staging": 1}
    assert verify_audit_chain(conn, chain_table="release_approvals")["any_tamper"] is False


def test_preexisting_unchained_row_is_outside_the_chain(tmp_path):
    """A legacy row written before this feature (NULL link columns) is counted
    as pre-existing and does not break or join the genesis-re-anchored chain."""
    conn = _conn(tmp_path)
    conn.cursor().execute(
        "INSERT INTO release_approvals(approval_id, release_id, actor, action, reason, created_at, "
        "tenant_id, workspace_id, environment) VALUES(?,?,?,?,?,?,?,?,?)",
        ("legacy-1", "rel-1", "bob", "approve", "", 1.0, "acme", "w", "prod"),
    )
    conn.commit()
    repo = ReleaseRepo(conn)
    _record(repo, "approve")  # first CHAINED row → genesis, seq 1
    res = verify_audit_chain(conn, chain_table="release_approvals")
    assert res["any_tamper"] is False
    chain = next(c for c in res["chains"] if c["count"] >= 1)
    assert chain["preexisting_count"] == 1
    assert chain["count"] == 1
