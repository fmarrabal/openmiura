"""``openmiura.core.migrations._batch_003`` — audit hash-chain.

Schema foundation for tamper-evident audit tables (strategic bet #2).
Migration 23 is intentionally **additive and reversible**: it adds the
chain link columns (``row_hash`` / ``prev_hash`` / ``chain_seq``) to the
three operational audit tables, a ``audit_chain_heads`` cache table, and
the scope-leading indexes the writer and verifier will need.

This migration does NOT compute any hashes, change any write path, or add
any triggers — those land in later PRs. Existing rows keep NULL link
columns (the chain is genesis-re-anchored from the first NEW row per
scope, so pre-feature history is explicitly never claimed as verified).
"""
from __future__ import annotations

from openmiura.core.migrations._migration import Migration


# Columns added to each of the three append-only audit tables. Nullable so
# the migration is idempotent on existing rows (a DB DEFAULT cannot compute
# a chain link; the write path fills these in a later PR).
_CHAIN_COLUMNS = ("row_hash TEXT", "prev_hash TEXT", "chain_seq INTEGER")
_CHAINED_TABLES = ("events", "tool_calls", "decision_traces")


def _sqlite_add_columns() -> tuple[str, ...]:
    return tuple(
        f"ALTER TABLE {table} ADD COLUMN {col}"
        for table in _CHAINED_TABLES
        for col in _CHAIN_COLUMNS
    )


def _postgres_add_columns() -> tuple[str, ...]:
    return tuple(
        f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col}"
        for table in _CHAINED_TABLES
        for col in _CHAIN_COLUMNS
    )


_CHAIN_INDEXES = tuple(
    f"CREATE INDEX IF NOT EXISTS idx_{table}_chain ON {table}(tenant_id, workspace_id, environment, chain_seq)"
    for table in _CHAINED_TABLES
)


BATCH_003_MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        23,
        "audit_hash_chain",
        # ---- SQLite up ----
        (
            *_sqlite_add_columns(),
            """
            CREATE TABLE IF NOT EXISTS audit_chain_heads (
                chain_table  TEXT NOT NULL,
                chain_scope  TEXT NOT NULL,
                head_hash    TEXT NOT NULL,
                head_seq     INTEGER NOT NULL,
                updated_at   REAL NOT NULL,
                PRIMARY KEY (chain_table, chain_scope)
            )
            """,
            *_CHAIN_INDEXES,
        ),
        # ---- Postgres up ----
        (
            *_postgres_add_columns(),
            """
            CREATE TABLE IF NOT EXISTS audit_chain_heads (
                chain_table  TEXT NOT NULL,
                chain_scope  TEXT NOT NULL,
                head_hash    TEXT NOT NULL,
                head_seq     INTEGER NOT NULL,
                updated_at   DOUBLE PRECISION NOT NULL,
                PRIMARY KEY (chain_table, chain_scope)
            )
            """,
            *_CHAIN_INDEXES,
        ),
        # ---- SQLite down ----
        # SQLite cannot reliably DROP COLUMN across deployed versions, so we
        # drop the indexes + the heads cache (a no-op rebuild of the chain)
        # and leave the nullable link columns in place (harmless).
        (
            "DROP INDEX IF EXISTS idx_events_chain",
            "DROP INDEX IF EXISTS idx_tool_calls_chain",
            "DROP INDEX IF EXISTS idx_decision_traces_chain",
            "DROP TABLE IF EXISTS audit_chain_heads",
        ),
        # ---- Postgres down ----
        (
            "DROP INDEX IF EXISTS idx_events_chain",
            "DROP INDEX IF EXISTS idx_tool_calls_chain",
            "DROP INDEX IF EXISTS idx_decision_traces_chain",
            "DROP TABLE IF EXISTS audit_chain_heads",
            "ALTER TABLE events DROP COLUMN IF EXISTS row_hash",
            "ALTER TABLE events DROP COLUMN IF EXISTS prev_hash",
            "ALTER TABLE events DROP COLUMN IF EXISTS chain_seq",
            "ALTER TABLE tool_calls DROP COLUMN IF EXISTS row_hash",
            "ALTER TABLE tool_calls DROP COLUMN IF EXISTS prev_hash",
            "ALTER TABLE tool_calls DROP COLUMN IF EXISTS chain_seq",
            "ALTER TABLE decision_traces DROP COLUMN IF EXISTS row_hash",
            "ALTER TABLE decision_traces DROP COLUMN IF EXISTS prev_hash",
            "ALTER TABLE decision_traces DROP COLUMN IF EXISTS chain_seq",
        ),
    ),
)
