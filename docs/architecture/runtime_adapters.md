# Runtime adapters

`openmiura/application/runtime_adapters/` is the home of the
external-agent-runtime supervision code. The legacy internal name
is `openclaw`; the public-facing path was renamed to
`runtime_adapters/external/` during Phase 0 of the master plan.
Database table names (`openclaw_runtime`, `openclaw_dispatch`),
some persistence-layer identifiers and the HTTP routes
(`/admin/openclaw/*`) keep the legacy name for backwards
compatibility with the persisted state and the public API contract.

## Top-level layout

```
openmiura/application/runtime_adapters/
    __init__.py
    external/
        __init__.py
        alert_governance_bundle_gates.py
        alert_governance_bundle_jobs.py
        alert_governance_bundle_management.py
        approval_common.py
        baseline_rollout_gates.py
        baseline_rollout_jobs.py
        baseline_rollout_management/    # sub-package (see below)
        baseline_rollout_state.py
        baseline_rollout_support/        # sub-package (see below)
        evidence_builders/               # sub-package (see below)
        governance_explainability.py
        job_family_common.py
        policy_normalization.py
        runtime_alert_common.py
        runtime_alert_escalations.py
        runtime_alert_execution.py
        runtime_alert_notifications.py
        runtime_context.py
        runtime_rollout_summaries.py
        scheduler/                       # sub-package (see below)
        service/                         # sub-package (see below)
        temporal_windows.py
```

Each top-level file (`alert_governance_bundle_*`,
`baseline_rollout_*`, `runtime_alert_*`, …) defines a single
"Mixin" class that contributes a slice of behaviour to the main
`OpenClawAdapterService` and `OpenClawRecoverySchedulerService`
classes. The five sub-packages below were extracted when their
parent file exceeded 1,500 lines.

## Sub-packages

### `service/`

Public class: `OpenClawAdapterService` (the external-runtime
adapter that receives dispatches, polls completions, runs
conformance checks and manages alerts). Originally 2,579 lines /
59 methods on a single class; now split into 8 sub-mixins
(alerts, core, dispatch, events, health, policy, recovery,
runtimes). Largest sub-mixin: 976 lines.

### `scheduler/`

Public class: `OpenClawRecoverySchedulerService` (orchestrates
recovery jobs, baseline-promotion lifecycles, portfolio reviews,
attestation exports). Originally 7,263 lines / 186 methods;
inherits from 20 external mixins plus, after the split, 8 new
sub-mixins. The 8 sub-mixins are:

- `_core_mixin.py` (889 lines)
- `_alerts_mixin.py` (571)
- `_policy_mixin.py` (50)
- `_recovery_jobs_mixin.py` (422)
- `_portfolio_a_mixin.py` (1,296)
- `_portfolio_b_mixin.py` (1,253)
- `_portfolio_c_mixin.py` (1,276)
- `_portfolio_d_mixin.py` (1,118)

### `baseline_rollout_support/`

Public class: `OpenClawBaselineRolloutSupportMixin` (shared
support for baseline-rollout monitoring, alerting and evidence).
Originally 7,961 lines / 93 methods; now 11 sub-mixins. Splits
that exceeded the threshold were sub-split into `_a`/`_b` halves.
Largest sub-mixin: 1,482 lines.

### `baseline_rollout_management/`

Public class: `OpenClawBaselineRolloutManagementMixin`
(simulation, approval, rollout, dashboard, evidence). Originally
2,709 lines / 41 methods; now 5 sub-mixins. Largest: 1,260 lines.

### `evidence_builders/`

Public class: `OpenClawEvidenceBuildersMixin` (archive, build,
prune, verify of baseline-promotion evidence packages).
Originally 1,629 lines / 20 methods; now 5 sub-mixins. Largest:
612 lines.

## Late-binding

All five sub-packages apply the same late-binding pattern: each
sub-mixin module declares
`<PublicClassName>: type | None = None` at module scope, and
the package `__init__.py` rebinds the symbol on every sub-mixin
module after defining the aggregating class. A handful of
`@staticmethod`s in each package reference the public class by
name (e.g.
`OpenClawBaselineRolloutSupportMixin._baseline_promotion_simulation_custody_policy_delta_keys(...)`).
Without the rebind those would raise `NameError` at call time.

## Status

All sub-packages are under the 1,500-line ceiling on every
individual file. The 9 god-files flagged at the end of Phase 1.2
have all been resolved; the residual debt list is empty.
