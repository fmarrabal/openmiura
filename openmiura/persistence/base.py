"""Shared persistence-layer primitives used by repository classes.

These functions are intentionally pure (no instance state) so that
both the legacy ``AuditStore`` facade and the new repository classes
can call them without requiring the same object identity.
"""

from __future__ import annotations

from typing import Any


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
