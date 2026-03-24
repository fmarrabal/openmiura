# Phase 2 PR2 / PR3 — Workspaces, environments, inherited overrides, and SSO/OIDC

This iteration continues the agreed roadmap without leaving the Phase 2 sequence.

## Scope delivered

### Workspaces and environments with inherited configuration overrides

Added support for scoped configuration inheritance in `tenancy`:

- tenant-level `settings_overrides`
- workspace-level `settings_overrides`
- environment-level `settings_overrides`
- environment definitions either as a list or as a map with metadata
- effective scoped configuration resolution via `TenancyService.effective_config(...)`

New broker admin endpoint:

- `GET /broker/admin/tenancy/effective-config`

This endpoint resolves the effective runtime-facing configuration for a given:

- tenant
- workspace
- environment

Sensitive values are masked in the returned payload.

### SSO / OIDC foundation

Added OIDC support under broker auth:

- `GET /broker/auth/oidc/config`
- `GET /broker/auth/oidc/login`
- `GET /broker/auth/oidc/callback`
- `POST /broker/auth/oidc/logout`

Implemented pieces:

- OIDC configuration in `openmiura.core.config`
- authorization URL generation with optional PKCE
- signed state handling
- signed flow cookie for callback validation
- token exchange and userinfo retrieval hooks
- group-to-role mapping
- tenant/workspace/environment mapping from claims
- auto-provisioning of auth users
- local auth session creation after OIDC callback

## Files added

- `openmiura/application/auth/oidc_service.py`
- `tests/test_phase2_workspaces_oidc.py`
- `docs/phase2_pr2_workspaces_oidc.md`

## Files updated

- `openmiura/core/config.py`
- `openmiura/core/tenancy/models.py`
- `openmiura/application/tenancy/service.py`
- `openmiura/application/auth/service.py`
- `openmiura/application/auth/__init__.py`
- `openmiura/core/audit.py`
- `openmiura/interfaces/broker/routes/auth.py`
- `openmiura/interfaces/broker/routes/admin.py`

## Notes

This is still an incremental Phase 2 step, not the final enterprise closure.

What is now true:

- workspaces and environments can carry inherited config overrides
- the broker can expose the effective scoped configuration safely
- OIDC can bootstrap a broker auth session with mapped role and scope
- auth sessions and rotated tokens preserve scope more consistently

What still remains for later Phase 2 steps:

- stricter scoped reads/writes across all admin and memory flows
- workspace-scoped RBAC beyond the current role model
- full SSO/OIDC reverse-proxy hardening and logout federation nuances
- stronger segregation rules across exports and destructive operations
