"""Broker admin release approval — authorization bypasses.

Two defects found by an adversarial audit, both reproduced end to end before
the fix:

  * the broker approve route called the LEGACY single-approver path
    unconditionally, so a release governed by an approval quorum could be
    approved there by its own creator — 200, status `approved`, and zero
    signature-grade votes recorded. The same call is refused with 403 on the
    HTTP admin route, which dispatches on the quorum.
  * the route took tenant/workspace scope from the request BODY with
    `payload.get("tenant_id") or auth_ctx.get("tenant_id")`, short-circuiting
    the scope validation, which only ever sees the header-derived scope.

The service-level guard is the load-bearing half: signature-grade approval is
now a property of `approve_release` rather than a dispatch decision each route
has to remember, so a caller that has not been updated fails closed.
"""
from __future__ import annotations

import pytest

from openmiura.application.releases.service import ReleaseService


class _FakeAudit:
    def __init__(self, quorum):
        self._quorum = quorum
        self.approved_via_legacy = False

    def get_release_quorum(self, *, release_id: str, action: str):
        return self._quorum

    def approve_release_bundle(self, release_id, **kw):
        self.approved_via_legacy = True
        return {"release_id": release_id, "status": "approved"}


class _FakeGw:
    def __init__(self, quorum):
        self.audit = _FakeAudit(quorum)


def test_legacy_approve_is_refused_when_a_quorum_is_configured() -> None:
    """The bypass: any caller reaching the legacy path must fail closed."""
    gw = _FakeGw(quorum={"required_n": 2, "allow_self": False})
    with pytest.raises(PermissionError) as excinfo:
        ReleaseService().approve_release(
            gw, release_id="rel-1", actor="user:alice", reason="",
        )
    assert "signature-grade" in str(excinfo.value)
    assert gw.audit.approved_via_legacy is False, "the release was approved anyway"


def test_legacy_approve_still_works_without_a_quorum() -> None:
    """Deployments that never opted in must be unchanged."""
    gw = _FakeGw(quorum=None)
    result = ReleaseService().approve_release(
        gw, release_id="rel-1", actor="admin", reason="",
    )
    assert result["ok"] is True
    assert gw.audit.approved_via_legacy is True


# ----------------------------------------------------------------------
# Scope: a body-supplied scope must be validated, not trusted.
# ----------------------------------------------------------------------


def _ctx(**over):
    ctx = {
        "tenant_id": "acme", "workspace_id": "ops", "environment": "prod",
        "bound_tenant_id": "acme", "bound_workspace_id": "ops",
        "scope_access": "scoped", "scope_level": "workspace",
    }
    ctx.update(over)
    return ctx


def test_body_scope_escalation_is_rejected() -> None:
    from fastapi import HTTPException

    from openmiura.interfaces.broker.common import resolve_request_scope

    with pytest.raises(HTTPException) as excinfo:
        resolve_request_scope(_ctx(), {"workspace_id": "research"})
    assert excinfo.value.status_code == 403
    assert "escalation" in str(excinfo.value.detail).lower()


def test_body_scope_within_the_binding_is_allowed() -> None:
    from openmiura.interfaces.broker.common import resolve_request_scope

    tenant, workspace, _env = resolve_request_scope(_ctx(), {"workspace_id": "ops"})
    assert (tenant, workspace) == ("acme", "ops")


def test_absent_body_scope_falls_back_to_the_validated_header_scope() -> None:
    from openmiura.interfaces.broker.common import resolve_request_scope

    tenant, workspace, env = resolve_request_scope(_ctx(), {})
    assert (tenant, workspace, env) == ("acme", "ops", "prod")


def test_globally_scoped_principal_may_still_target_another_tenant() -> None:
    """The fix must not break a legitimately global operator."""
    from openmiura.interfaces.broker.common import resolve_request_scope

    tenant, _w, _e = resolve_request_scope(
        _ctx(scope_access="global"), {"tenant_id": "other"}
    )
    assert tenant == "other"
