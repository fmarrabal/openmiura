from __future__ import annotations

from typing import Any


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_scope(*, tenant_id: Any = None, workspace_id: Any = None, environment: Any = None) -> tuple[str | None, str | None, str | None]:
    return (_clean(tenant_id), _clean(workspace_id), _clean(environment))


def scope_dict(*, tenant_id: Any = None, workspace_id: Any = None, environment: Any = None) -> dict[str, str | None]:
    tenant, workspace, env = normalize_scope(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
    return {"tenant_id": tenant, "workspace_id": workspace, "environment": env}


def scope_key(*, tenant_id: Any = None, workspace_id: Any = None, environment: Any = None) -> str:
    tenant, workspace, env = normalize_scope(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
    return "::".join((tenant or "_", workspace or "_", env or "_"))


def scope_matches(
    actual: dict[str, Any] | None,
    expected: dict[str, Any] | None,
    *,
    strict: bool = False,
) -> bool:
    actual = actual or {}
    expected = expected or {}
    keys = ("tenant_id", "workspace_id", "environment")
    if strict:
        a = normalize_scope(
            tenant_id=actual.get("tenant_id"),
            workspace_id=actual.get("workspace_id"),
            environment=actual.get("environment"),
        )
        e = normalize_scope(
            tenant_id=expected.get("tenant_id"),
            workspace_id=expected.get("workspace_id"),
            environment=expected.get("environment"),
        )
        return a == e
    for key in keys:
        exp = _clean(expected.get(key))
        if exp is None:
            continue
        if _clean(actual.get(key)) != exp:
            return False
    return True


def assert_scope_match(actual: dict[str, Any] | None, expected: dict[str, Any] | None, *, subject: str = "resource") -> None:
    if not scope_matches(actual, expected, strict=True):
        raise ValueError(f"{subject} scope mismatch")


def build_scoped_session_id(
    *,
    prefix: str,
    user_key: str,
    tenant_id: Any = None,
    workspace_id: Any = None,
    environment: Any = None,
    agent_id: str | None = None,
) -> str:
    tenant, workspace, env = normalize_scope(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
    parts = [str(prefix or "session").strip() or "session"]
    if tenant is not None or workspace is not None or env is not None:
        parts.extend([tenant or "_", workspace or "_", env or "_"])
    if agent_id:
        parts.append(str(agent_id).strip())
    parts.append(str(user_key).strip())
    return ":".join(parts)


_IDENTITY_PREFIX = "scope-id"


def build_scoped_identity_key(channel_user_key: str, *, tenant_id: Any = None, workspace_id: Any = None) -> str:
    tenant, workspace, _ = normalize_scope(tenant_id=tenant_id, workspace_id=workspace_id, environment=None)
    if tenant is None and workspace is None:
        return str(channel_user_key)
    return f"{_IDENTITY_PREFIX}::{tenant or '_'}::{workspace or '_'}::{str(channel_user_key)}"


def parse_scoped_identity_key(stored_key: str) -> tuple[str | None, str | None, str]:
    raw = str(stored_key)
    marker = f"{_IDENTITY_PREFIX}::"
    if not raw.startswith(marker):
        return None, None, raw
    _, tenant, workspace, channel_user_key = raw.split("::", 3)
    return (None if tenant == "_" else tenant, None if workspace == "_" else workspace, channel_user_key)
