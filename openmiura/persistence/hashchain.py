"""Offline verification of the audit hash-chain (read-only).

Walks the per-(table, scope) chains written by ``compute_chain_link`` and
checks every invariant: ``chain_seq`` is contiguous from 1, each row's
``prev_hash`` equals the previous row's ``row_hash``, each ``row_hash``
recomputes from the canonical row, and the per-scope head in
``audit_chain_heads`` matches the last row. Any mismatch is tamper.

The per-table ``row_fields`` reconstruction MUST mirror the writer
(``sessions_repo.log_event`` / ``tools_repo.log_tool_call``) exactly — the
writer and verifier hash the same canonical dict. A cross-check test
(a freshly written chain must verify) pins them together.

decision_traces is intentionally absent: it legitimately upserts and needs
option-A immutable versions before it can be chained (a later PR).
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from openmiura.persistence.base import (
    canonical_chain_scope,
    canonical_row_digest,
    parse_json_column,
)


def _events_row_fields(row: Any) -> dict[str, Any]:
    return {
        "ts": row["ts"],
        "direction": row["direction"],
        "channel": row["channel"],
        "user_id": row["user_id"],
        "session_id": row["session_id"],
        "payload": parse_json_column(row["payload_json"]),
    }


def _tool_calls_row_fields(row: Any) -> dict[str, Any]:
    return {
        "ts": row["ts"],
        "session_id": row["session_id"],
        "user_key": row["user_key"],
        "agent_id": row["agent_id"],
        "tool_name": row["tool_name"],
        "args": parse_json_column(row["args_json"]),
        "ok": bool(row["ok"]),
        "result_excerpt": row["result_excerpt"],
        "error": row["error"],
        "duration_ms": float(row["duration_ms"]),
    }


_SPECS: dict[str, dict[str, Any]] = {
    "events": {
        "select": (
            "SELECT chain_seq, prev_hash, row_hash, tenant_id, workspace_id, environment, "
            "ts, direction, channel, user_id, session_id, payload_json FROM events"
        ),
        "fields": _events_row_fields,
    },
    "tool_calls": {
        "select": (
            "SELECT chain_seq, prev_hash, row_hash, tenant_id, workspace_id, environment, "
            "ts, session_id, user_key, agent_id, tool_name, args_json, ok, result_excerpt, error, duration_ms FROM tool_calls"
        ),
        "fields": _tool_calls_row_fields,
    },
}

# Tables whose write path computes a chain link today (decision_traces is not
# chained yet — see module docstring).
CHAINED_TABLES: tuple[str, ...] = tuple(_SPECS.keys())


def audit_chain_head_events(
    conn: Any,
    *,
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    environment: str | None = None,
) -> list[dict[str, Any]]:
    """One chain-of-custody event per chained table that has a head for this
    scope, ready to embed in a portfolio evidence pack.

    Embedding the chain HEAD (not every row) as a signed custody event makes
    ``openmiura verify`` transitively attest *what the head hash was and who
    signed it* at export time, with no change to the offline verifier. An
    auditor then runs ``openmiura db verify-chain`` to prove the live DB
    still hashes to that head. Returns ``[]`` when no chain exists for the
    scope (e.g. nothing was logged), so packs for un-exercised scopes are
    unchanged.
    """
    scope = canonical_chain_scope(tenant_id, workspace_id, environment)
    cur = conn.cursor()
    out: list[dict[str, Any]] = []
    for table in CHAINED_TABLES:
        row = cur.execute(
            "SELECT head_hash, head_seq FROM audit_chain_heads WHERE chain_table=? AND chain_scope=?",
            (table, scope),
        ).fetchone()
        if row is None:
            continue
        out.append({
            "event_type": "audit_chain_head",
            "metadata": {
                "chain_table": table,
                "chain_scope": scope,
                "head_hash": str(row["head_hash"]),
                "head_seq": int(row["head_seq"]),
            },
        })
    return out


def verify_audit_chain(conn: Any, *, chain_table: str) -> dict[str, Any]:
    """Verify every per-scope chain for one table. Returns a structured
    result; never raises for a tamper (it is reported, not thrown)."""
    if chain_table not in _SPECS:
        raise KeyError(f"{chain_table} is not a chained audit table")
    spec = _SPECS[chain_table]
    cur = conn.cursor()
    rows = cur.execute(spec["select"]).fetchall()

    chains: dict[str, list[Any]] = defaultdict(list)
    preexisting: dict[str, int] = defaultdict(int)
    for r in rows:
        scope = canonical_chain_scope(r["tenant_id"], r["workspace_id"], r["environment"])
        if r["chain_seq"] is None:
            preexisting[scope] += 1
        else:
            chains[scope].append(r)

    heads_rows = cur.execute(
        "SELECT chain_scope, head_hash, head_seq FROM audit_chain_heads WHERE chain_table=?",
        (chain_table,),
    ).fetchall()
    heads = {hr["chain_scope"]: (hr["head_hash"], int(hr["head_seq"])) for hr in heads_rows}

    results: list[dict[str, Any]] = []
    any_tamper = False
    for scope in sorted(set(chains) | set(preexisting)):
        crows = sorted(chains.get(scope, []), key=lambda r: int(r["chain_seq"]))
        chain_valid = True
        first_bad_seq: int | None = None
        prev = ""
        for idx, r in enumerate(crows):
            expected_seq = idx + 1
            recomputed = canonical_row_digest({
                "chain_table": chain_table,
                "chain_scope": scope,
                "chain_seq": int(r["chain_seq"]),
                "prev_hash": str(r["prev_hash"] or ""),
                "row": spec["fields"](r),
            })
            if (
                int(r["chain_seq"]) != expected_seq
                or str(r["prev_hash"] or "") != prev
                or str(r["row_hash"] or "") != recomputed
            ):
                chain_valid = False
                first_bad_seq = int(r["chain_seq"])
                break
            prev = str(r["row_hash"])

        head_hash, head_seq = heads.get(scope, (None, None))
        head_matches = (
            not crows
            or (chain_valid and head_hash == crows[-1]["row_hash"] and head_seq == int(crows[-1]["chain_seq"]))
        )
        ok = chain_valid and head_matches
        if not ok:
            any_tamper = True
        results.append({
            "scope": scope,
            "count": len(crows),
            "preexisting_count": preexisting.get(scope, 0),
            "head_hash": head_hash,
            "head_seq": head_seq,
            "chain_valid": chain_valid,
            "head_matches": bool(head_matches),
            "first_bad_seq": first_bad_seq,
        })

    return {"table": chain_table, "chains": results, "any_tamper": any_tamper}
