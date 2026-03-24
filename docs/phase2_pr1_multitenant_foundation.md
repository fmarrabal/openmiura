# Phase 2 PR1 — Multi-tenant foundation

This iteration starts the enterprise foundation roadmap without leaving the agreed sequence.

## Scope delivered

- tenancy settings in `openmiura.core.config`
- core tenancy model in `openmiura.core.tenancy`
- tenancy resolution service in `openmiura.application.tenancy`
- broker auth context enriched with:
  - `tenant_id`
  - `workspace_id`
  - `environment`
- broker `/auth/me` now exposes scope and scope header names
- broker admin overview now exposes tenancy catalog
- broker admin endpoint `/broker/admin/tenancy`
- persistence migration `v4 tenancy_foundation`
- audit/session/event/auth token/auth session storage now carries scope metadata

## Default request headers

- `X-Tenant-Id`
- `X-Workspace-Id`
- `X-Environment`

## Notes

This is a **foundation step**, not full hard isolation yet.

What is now true:
- the platform has an explicit tenant/workspace/environment model
- HTTP broker requests can resolve scope consistently
- persisted operational records can carry scope metadata
- auth users, auth sessions and API tokens can be associated with scope

What remains for next phase-2 steps:
- stricter scoped reads/writes across all admin and broker flows
- workspace/environment inheritance and overrides
- SSO/OIDC mapping into tenant/workspace roles
- finer RBAC scoped by tenant/workspace
- stronger segregation for memory/audit exports and deletion workflows
