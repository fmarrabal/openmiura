"""Signature-grade approvals — PR 1 (additive schema).

Migration 27 only lays the foundation: the second-factor columns on
auth_users, the signature-manifestation + chain-link columns on
release_approvals, the per-(release,action) quorum table, and the chain
index. No write path fills any of it and no behaviour changes yet. These
tests pin that the migration is additive, idempotent, reversible, and that
the legacy single-actor approval insert still works untouched.
"""
from __future__ import annotations

from openmiura.core.db import DBConnection
from openmiura.core.migrations import (
    MIGRATIONS,
    apply_migrations,
    downgrade_migrations,
)


def _columns(conn, table: str) -> set[str]:
    return {row[1] for row in conn.cursor().execute(f"PRAGMA table_info({table})").fetchall()}


def _table_exists(conn, name: str) -> bool:
    return conn.cursor().execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _index_exists(conn, name: str) -> bool:
    return conn.cursor().execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?", (name,)
    ).fetchone() is not None


def _migrated_conn(tmp_path):
    conn = DBConnection(backend="sqlite", db_path=(tmp_path / "audit.db").as_posix(), database_url="")
    apply_migrations(conn)
    return conn


def test_migration_27_is_registered_and_latest():
    by_version = {m.version: m for m in MIGRATIONS}
    assert 27 in by_version
    assert by_version[27].name == "signature_grade_release_approvals"
    assert max(by_version) == 27
    # versions stay contiguous (no gaps) up to the latest
    assert sorted(by_version) == list(range(1, 28))


def test_auth_users_gains_totp_columns(tmp_path):
    cols = _columns(_migrated_conn(tmp_path), "auth_users")
    assert {"otp_secret_enc", "otp_enabled", "otp_confirmed_at"}.issubset(cols)


def test_release_approvals_gains_signature_columns(tmp_path):
    cols = _columns(_migrated_conn(tmp_path), "release_approvals")
    assert {
        "meaning",
        "signer_user_key",
        "second_factor_method",
        "otp_verified_at",
        "signature",
        "signature_scheme",
        "signer_key_id",
        "signature_input_hash",
        "row_hash",
        "prev_hash",
        "chain_seq",
    }.issubset(cols)


def test_quorum_table_and_chain_index_exist(tmp_path):
    conn = _migrated_conn(tmp_path)
    assert _table_exists(conn, "release_approval_quorum")
    assert {
        "release_id",
        "action",
        "required_n",
        "distinct_required",
        "allow_self",
        "tenant_id",
        "workspace_id",
        "environment",
    }.issubset(_columns(conn, "release_approval_quorum"))
    assert _index_exists(conn, "idx_release_approvals_chain")


def test_quorum_row_defaults(tmp_path):
    """A quorum row written with only the keys takes the regulated defaults:
    n=2, distinct approvers, no self-approval."""
    conn = _migrated_conn(tmp_path)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO release_approval_quorum(release_id, action, created_at) VALUES(?,?,?)",
        ("rel-1", "approve", 1.0),
    )
    conn.commit()
    row = cur.execute(
        "SELECT required_n, distinct_required, allow_self FROM release_approval_quorum"
    ).fetchone()
    assert tuple(row) == (2, 1, 0)


def test_migration_is_idempotent(tmp_path):
    conn = _migrated_conn(tmp_path)
    apply_migrations(conn)  # re-run must not raise
    assert {"otp_secret_enc"}.issubset(_columns(conn, "auth_users"))
    assert _table_exists(conn, "release_approval_quorum")


def test_legacy_release_approval_insert_still_works(tmp_path):
    """The legacy flat insert (actor + action + reason + created_at + scope)
    keeps working with every new column NULL — no write path fills them yet."""
    conn = _migrated_conn(tmp_path)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO release_approvals(approval_id, release_id, actor, action, reason, created_at) "
        "VALUES(?,?,?,?,?,?)",
        ("a1", "rel-1", "alice", "approve", "looks good", 1.0),
    )
    conn.commit()
    row = cur.execute(
        "SELECT signature, signer_user_key, row_hash, chain_seq FROM release_approvals"
    ).fetchone()
    assert tuple(row) == (None, None, None, None)


def test_downgrade_to_26_drops_quorum_and_index(tmp_path):
    conn = _migrated_conn(tmp_path)
    rolled = downgrade_migrations(conn, target_version=26)
    assert 27 in rolled
    assert not _table_exists(conn, "release_approval_quorum")
    assert not _index_exists(conn, "idx_release_approvals_chain")
    # Re-applying restores the schema.
    apply_migrations(conn)
    assert _table_exists(conn, "release_approval_quorum")
    assert _index_exists(conn, "idx_release_approvals_chain")
