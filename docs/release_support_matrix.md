# Release support matrix for RC1

This matrix is intentionally pragmatic. It distinguishes what is suitable for controlled pilot use from what remains preview or operator-only.

| Area | Status in RC1 | Notes |
|---|---|---|
| Core HTTP service and `/health` | Supported for pilot | Base runtime entrypoint and health checks are part of the standard validation path. |
| Web UI and operator console | Supported for pilot | Includes Config Center, setup wizards and admin/operator surfaces already covered by automated tests. |
| Tenant/workspace/environment scoping | Supported for pilot | Intended for deliberate scoped operation, not casual multi-tenant exposure. |
| Policy, approvals and audit trails | Supported for pilot | Core differentiator of the product thesis. |
| Baseline governance and policy-pack promotion | Supported for pilot | Suitable for controlled evaluation and demos. |
| Secret governance and custody/evidence flows | Supported for pilot | Requires secure operator handling and environment-specific hardening. |
| Tiny runtime trust/certificate UI | Supported for pilot | Appropriate for lab and internal operational scenarios. |
| Slack/Telegram/Discord setup wizards | Supported for pilot | Channel-specific production readiness still depends on external infrastructure and secrets handling. |
| Reproducible packaging and release manifests | Supported for pilot | Full release validation still expects the `build` dependency in the execution environment. |
| Voice runtime | Preview | Kept out of the frozen RC bundle as runtime artifacts; use only in controlled evaluation. |
| External provider edge cases | Preview | Validate provider-specific behavior in the target environment. |
| GA-grade HA / clustered deployment | Not in scope | RC1 is positioned as self-hosted single-node or small-team pilot infrastructure. |

## Operational constraints

RC1 assumes:

- deliberate environment configuration
- secure credentials rotation before sharing
- reverse-proxy/TLS posture for non-localhost use
- explicit review before enabling permissive terminal or fetch settings

## Release-blocking vs non-blocking

The following are no longer considered RC1 blockers:

- deeper module decomposition beyond the Sprint 5 surgical refactor
- broader platform expansion
- new macrofeatures outside the audited product thesis

The following still remain mandatory before broadening distribution:

- green quality gate in a release-capable environment
- clean RC bundle freeze
- explicit support expectations for the receiving team
