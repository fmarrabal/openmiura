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


# Migration 24 — append-only triggers. events and tool_calls are pure
# append-only (verified: no production path UPDATEs/DELETEs them), so we make
# that a DB-enforced guarantee rather than a convention. decision_traces is
# NOT covered here — it legitimately upserts and is only guarded once option-A
# immutable versions land. Genesis re-anchor means no historic-row UPDATE, so
# the triggers can be created without conflicting with any backfill.
_TRIGGER_TABLES = ("events", "tool_calls")


def _sqlite_triggers_up() -> tuple[str, ...]:
    out: list[str] = []
    for table in _TRIGGER_TABLES:
        msg = f"{table} is append-only (audit hash-chain)"
        out.append(
            f"CREATE TRIGGER IF NOT EXISTS trg_{table}_no_update BEFORE UPDATE ON {table} "
            f"BEGIN SELECT RAISE(ABORT, '{msg}'); END"
        )
        out.append(
            f"CREATE TRIGGER IF NOT EXISTS trg_{table}_no_delete BEFORE DELETE ON {table} "
            f"BEGIN SELECT RAISE(ABORT, '{msg}'); END"
        )
    return tuple(out)


def _postgres_triggers_up() -> tuple[str, ...]:
    out: list[str] = [
        "CREATE OR REPLACE FUNCTION openmiura_reject_audit_write() RETURNS trigger "
        "LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'append-only (audit hash-chain): % on %', TG_OP, TG_TABLE_NAME; END; $$",
    ]
    for table in _TRIGGER_TABLES:
        for op in ("update", "delete"):
            out.append(f"DROP TRIGGER IF EXISTS trg_{table}_no_{op} ON {table}")
            out.append(
                f"CREATE TRIGGER trg_{table}_no_{op} BEFORE {op.upper()} ON {table} "
                f"FOR EACH ROW EXECUTE FUNCTION openmiura_reject_audit_write()"
            )
    return tuple(out)


def _sqlite_triggers_down() -> tuple[str, ...]:
    return tuple(
        f"DROP TRIGGER IF EXISTS trg_{table}_no_{op}"
        for table in _TRIGGER_TABLES
        for op in ("update", "delete")
    )


def _postgres_triggers_down() -> tuple[str, ...]:
    out = [
        f"DROP TRIGGER IF EXISTS trg_{table}_no_{op} ON {table}"
        for table in _TRIGGER_TABLES
        for op in ("update", "delete")
    ]
    out.append("DROP FUNCTION IF EXISTS openmiura_reject_audit_write()")
    return tuple(out)


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
    Migration(
        24,
        "audit_chain_append_only_triggers",
        _sqlite_triggers_up(),
        _postgres_triggers_up(),
        _sqlite_triggers_down(),
        _postgres_triggers_down(),
    ),
)
