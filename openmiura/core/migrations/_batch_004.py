"""``openmiura.core.migrations._batch_004`` — signature-grade release approvals.

Schema foundation for turning a release approval from a bare
``actor + action + timestamp`` audit row into a Part-11 §11.50 / §11.200
*signature manifestation*: an authenticated signer, a stated meaning, a
verified second factor (TOTP), an ed25519 signature, and a per-(table,scope)
hash-chain link — plus an n-of-m quorum policy of distinct approvers.

Migration 27 is intentionally **additive and reversible**: it only adds
nullable columns (and one new table + index). It does NOT change any write
path, compute any signature, verify any TOTP, or enforce any quorum — those
land in later PRs. Existing rows keep NULL on every new column and are
explicitly outside the new chain (genesis re-anchor, same convention as the
audit hash-chain in _batch_003). The legacy single-actor flow keeps working
unchanged: with no quorum row present the approval policy defaults to n=1.
"""
from __future__ import annotations

from openmiura.core.migrations._migration import Migration


# --- auth_users: opt-in TOTP second factor ---------------------------------
# otp_secret_enc is the app-layer-encrypted (NOT plaintext base32) TOTP secret;
# nullable => 2FA is opt-in and existing rows are unaffected. No change to the
# password_hash / session contract, so existing auth tests keep passing.
_AUTH_USERS_COLUMNS_SQLITE = (
    "ALTER TABLE auth_users ADD COLUMN otp_secret_enc TEXT",
    "ALTER TABLE auth_users ADD COLUMN otp_enabled INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE auth_users ADD COLUMN otp_confirmed_at REAL",
)
_AUTH_USERS_COLUMNS_POSTGRES = (
    "ALTER TABLE auth_users ADD COLUMN IF NOT EXISTS otp_secret_enc TEXT",
    "ALTER TABLE auth_users ADD COLUMN IF NOT EXISTS otp_enabled INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE auth_users ADD COLUMN IF NOT EXISTS otp_confirmed_at DOUBLE PRECISION",
)


# --- release_approvals: signature manifestation + chain link ---------------
# meaning      §11.50(b) intent of the signature (defaults to the action)
# signer_user_key   the AUTHENTICATED identity (not the free-form `actor`)
# second_factor_method / otp_verified_at   §11.200 second factor evidence
# signature / signature_scheme / signer_key_id / signature_input_hash
#              the ed25519 signature over the canonical approval tuple
# row_hash / prev_hash / chain_seq   per-(table,scope) tamper-evident chain
_RELEASE_APPROVAL_COLUMNS = (
    ("meaning", "TEXT"),
    ("signer_user_key", "TEXT"),
    ("second_factor_method", "TEXT"),
    ("otp_verified_at", "REAL", "DOUBLE PRECISION"),
    ("signature", "TEXT"),
    ("signature_scheme", "TEXT"),
    ("signer_key_id", "TEXT"),
    ("signature_input_hash", "TEXT"),
    ("row_hash", "TEXT"),
    ("prev_hash", "TEXT"),
    ("chain_seq", "INTEGER"),
)


def _release_approval_add(*, postgres: bool) -> tuple[str, ...]:
    out: list[str] = []
    for col in _RELEASE_APPROVAL_COLUMNS:
        name = col[0]
        coltype = col[2] if (postgres and len(col) == 3) else col[1]
        if postgres:
            out.append(f"ALTER TABLE release_approvals ADD COLUMN IF NOT EXISTS {name} {coltype}")
        else:
            out.append(f"ALTER TABLE release_approvals ADD COLUMN {name} {coltype}")
    return tuple(out)


def _release_approval_drop_postgres() -> tuple[str, ...]:
    return tuple(
        f"ALTER TABLE release_approvals DROP COLUMN IF EXISTS {col[0]}"
        for col in _RELEASE_APPROVAL_COLUMNS
    )


# --- release_approval_quorum: per-(release, action) n-of-m policy -----------
# Absence of a row => the policy layer defaults to n=1 (legacy single-approver
# behaviour preserved). A written row opts a release/action into a stricter
# quorum (regulated default n=2, distinct approvers, no self-approval).
_QUORUM_TABLE_SQLITE = """
CREATE TABLE IF NOT EXISTS release_approval_quorum (
    release_id        TEXT NOT NULL,
    action            TEXT NOT NULL,
    required_n        INTEGER NOT NULL DEFAULT 2,
    distinct_required INTEGER NOT NULL DEFAULT 1,
    allow_self        INTEGER NOT NULL DEFAULT 0,
    tenant_id         TEXT,
    workspace_id      TEXT,
    environment       TEXT,
    created_at        REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (release_id, action)
)
"""
_QUORUM_TABLE_POSTGRES = """
CREATE TABLE IF NOT EXISTS release_approval_quorum (
    release_id        TEXT NOT NULL,
    action            TEXT NOT NULL,
    required_n        INTEGER NOT NULL DEFAULT 2,
    distinct_required INTEGER NOT NULL DEFAULT 1,
    allow_self        INTEGER NOT NULL DEFAULT 0,
    tenant_id         TEXT,
    workspace_id      TEXT,
    environment       TEXT,
    created_at        DOUBLE PRECISION NOT NULL DEFAULT 0,
    PRIMARY KEY (release_id, action)
)
"""

_CHAIN_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_release_approvals_chain "
    "ON release_approvals(tenant_id, workspace_id, environment, chain_seq)"
)


BATCH_004_MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        27,
        "signature_grade_release_approvals",
        # ---- SQLite up ----
        (
            *_AUTH_USERS_COLUMNS_SQLITE,
            *_release_approval_add(postgres=False),
            _QUORUM_TABLE_SQLITE,
            _CHAIN_INDEX,
        ),
        # ---- Postgres up ----
        (
            *_AUTH_USERS_COLUMNS_POSTGRES,
            *_release_approval_add(postgres=True),
            _QUORUM_TABLE_POSTGRES,
            _CHAIN_INDEX,
        ),
        # ---- SQLite down ----
        # SQLite cannot reliably DROP COLUMN across deployed versions (mirrors
        # migration 23): drop the new index + quorum table and leave the
        # nullable columns in place (harmless — they stay NULL).
        (
            "DROP INDEX IF EXISTS idx_release_approvals_chain",
            "DROP TABLE IF EXISTS release_approval_quorum",
        ),
        # ---- Postgres down ----
        (
            "DROP INDEX IF EXISTS idx_release_approvals_chain",
            "DROP TABLE IF EXISTS release_approval_quorum",
            *_release_approval_drop_postgres(),
            "ALTER TABLE auth_users DROP COLUMN IF EXISTS otp_secret_enc",
            "ALTER TABLE auth_users DROP COLUMN IF EXISTS otp_enabled",
            "ALTER TABLE auth_users DROP COLUMN IF EXISTS otp_confirmed_at",
        ),
    ),
)
