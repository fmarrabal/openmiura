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


def decision_trace_chain_fields(
    *,
    ts: float,
    session_id: str,
    user_key: str,
    channel: str,
    agent_id: str,
    request_text: str,
    response_text: str,
    status: str,
    provider: str,
    model: str,
    latency_ms: float,
    estimated_cost: float,
    llm_calls: int,
    input_tokens: int,
    output_tokens: int,
    total_tokens: int,
    context_json: str,
    memory_json: str,
    tools_considered_json: str,
    tools_used_json: str,
    policies_json: str,
    decisions_json: str,
    version: int,
) -> dict[str, Any]:
    """Canonical hashable fields for one decision_traces version row.

    Defined once and used by BOTH the write path (``log_decision_trace``)
    and the chain verifier, so a row_hash is reproducible. The ``*_json``
    columns are re-parsed (the two-serializer trap) and ``version`` is part
    of the hashed content. Pass the SAME (sanitized) values that are written
    to the row.
    """
    return {
        "ts": float(ts),
        "session_id": session_id,
        "user_key": user_key,
        "channel": channel,
        "agent_id": agent_id,
        "request_text": request_text,
        "response_text": response_text,
        "status": status,
        "provider": provider,
        "model": model,
        "latency_ms": float(latency_ms),
        "estimated_cost": float(estimated_cost),
        "llm_calls": int(llm_calls),
        "input_tokens": int(input_tokens),
        "output_tokens": int(output_tokens),
        "total_tokens": int(total_tokens),
        "context": parse_json_column(context_json),
        "memory": parse_json_column(memory_json),
        "tools_considered": parse_json_column(tools_considered_json),
        "tools_used": parse_json_column(tools_used_json),
        "policies": parse_json_column(policies_json),
        "decisions": parse_json_column(decisions_json),
        "version": int(version),
    }


def compute_chain_link(
    conn: Any,
    *,
    chain_table: str,
    row_fields: dict[str, Any],
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    environment: str | None = None,
    now_ts: float,
) -> tuple[str, str, int]:
    """Compute ``(prev_hash, row_hash, chain_seq)`` for a NEW append-only row
    and advance the per-(table, scope) head pointer.

    MUST be called inside the same transaction as the row INSERT (before the
    repo's ``commit()``) so the row and the head it produces commit
    atomically — a crash can never leave a row without a link or a head
    pointing past a missing row.

    The chain is partitioned per (table, scope); the first row of each chain
    is the genesis row with ``prev_hash == ""`` and ``chain_seq == 1`` (this
    matches the chain-of-custody initialiser in ``evidence_verify``). Rows
    written before this feature existed keep NULL link columns and are simply
    not part of the chain — pre-feature history is explicitly never claimed
    as verified.

    ``row_fields`` must hold the row's stable, hashable content with any
    ``*_json`` text already parsed via :func:`parse_json_column` (never raw
    column text — see the two-serializer trap). The verifier rebuilds the
    identical canonical dict, so the writer and verifier hash the same bytes.
    """
    scope = canonical_chain_scope(tenant_id, workspace_id, environment)
    cur = conn.cursor()
    head = cur.execute(
        "SELECT head_hash, head_seq FROM audit_chain_heads WHERE chain_table=? AND chain_scope=?",
        (chain_table, scope),
    ).fetchone()
    if head is None:
        prev_hash = ""
        chain_seq = 1
    else:
        prev_hash = str(head[0] or "")
        chain_seq = int(head[1]) + 1
    row_hash = canonical_row_digest({
        "chain_table": chain_table,
        "chain_scope": scope,
        "chain_seq": chain_seq,
        "prev_hash": prev_hash,
        "row": row_fields,
    })
    if head is None:
        cur.execute(
            "INSERT INTO audit_chain_heads(chain_table, chain_scope, head_hash, head_seq, updated_at) VALUES(?,?,?,?,?)",
            (chain_table, scope, row_hash, chain_seq, float(now_ts)),
        )
    else:
        cur.execute(
            "UPDATE audit_chain_heads SET head_hash=?, head_seq=?, updated_at=? WHERE chain_table=? AND chain_scope=?",
            (row_hash, chain_seq, float(now_ts), chain_table, scope),
        )
    return prev_hash, row_hash, chain_seq


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
