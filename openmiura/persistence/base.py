"""Shared persistence-layer primitives used by repository classes.

These functions are intentionally pure (no instance state) so that
both the legacy ``AuditStore`` facade and the new repository classes
can call them without requiring the same object identity.
"""

from __future__ import annotations

import json
from typing import Any

# One serializer of record for the audit hash-chain. Reuse the offline
# verifier's compact canonical digest so a row_hash computed here in the
# persistence layer is byte-for-byte reproducible by `openmiura verify` and
# `openmiura db verify-chain`. Do NOT re-implement the JSON canonicalization.
from openmiura.evidence_verify import stable_digest as canonical_row_digest


def parse_json_column(text: Any) -> Any:
    """Re-parse a stored ``*_json`` TEXT column back to its Python object
    for hashing.

    THE TWO-SERIALIZER TRAP: the ``payload_json`` / ``args_json`` / ``*_json``
    columns are written with ``json.dumps(..., ensure_ascii=False)`` — WITHOUT
    ``sort_keys`` — so their raw bytes are not the canonical form. A hash-chain
    must therefore re-parse the column and hash the resulting OBJECT through
    :func:`canonical_row_digest` (which sorts keys + uses compact separators),
    never the raw text. On malformed JSON we fall back to ``{"_raw": text}``,
    matching the existing readers (sessions_repo / tools_repo) so the writer
    and the verifier always agree.
    """
    if text is None:
        return None
    if not isinstance(text, str):
        return text
    try:
        return json.loads(text)
    except Exception:
        return {"_raw": text}


def canonical_chain_scope(
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    environment: str | None = None,
) -> str:
    """Canonical chain-partition key for a (tenant, workspace, environment)
    scope. NULL components collapse to ``""`` so an all-unscoped row lands in a
    single well-defined ``"unscoped"`` chain. A digest (not a delimiter join)
    is used so a value containing the delimiter cannot collide two scopes.
    """
    return canonical_row_digest({
        "tenant_id": tenant_id or "",
        "workspace_id": workspace_id or "",
        "environment": environment or "",
    })


def scope_payload(
    *,
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    environment: str | None = None,
) -> dict[str, Any]:
    """Return a normalized tenant/workspace/environment payload."""
    return {
        "tenant_id": str(tenant_id).strip() if tenant_id is not None else None,
        "workspace_id": str(workspace_id).strip() if workspace_id is not None else None,
        "environment": str(environment).strip() if environment is not None else None,
    }


def row_scope(row: Any) -> dict[str, Any]:
    """Extract tenant/workspace/environment columns from a DB row."""
    scope: dict[str, Any] = {}
    for key in ("tenant_id", "workspace_id", "environment"):
        try:
            scope[key] = row[key]
        except Exception:
            scope[key] = None
    return scope


def scope_where(
    clauses: list[str],
    params: list[Any],
    *,
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    environment: str | None = None,
    prefix: str = "",
) -> tuple[list[str], list[Any]]:
    """Append scope filtering clauses to an existing WHERE list.

    Returns the (clauses, params) pair as it received them, mutated
    in place. Ergonomic to chain in repository methods.
    """
    lead = f"{prefix}." if prefix else ""
    if tenant_id is not None:
        clauses.append(f"{lead}tenant_id=?")
        params.append(tenant_id)
    if workspace_id is not None:
        clauses.append(f"{lead}workspace_id=?")
        params.append(workspace_id)
    if environment is not None:
        clauses.append(f"{lead}environment=?")
        params.append(environment)
    return clauses, params


def infer_scope_from_session(conn: Any, session_id: str) -> dict[str, Any]:
    """Look up tenant/workspace/environment for a given session_id."""
    if not session_id:
        return {"tenant_id": None, "workspace_id": None, "environment": None}
    cur = conn.cursor()
    row = cur.execute(
        "SELECT tenant_id, workspace_id, environment FROM sessions WHERE session_id=?",
        (session_id,),
    ).fetchone()
    if row is None:
        return {"tenant_id": None, "workspace_id": None, "environment": None}
    return row_scope(row)
