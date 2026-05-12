# Admin service

`AdminService` is the application-layer service that orchestrates
every admin-side operation: memory and session inspection, runtime
adapter (openclaw) management, canvas operations, voice runtime,
evaluations, workflow / approval governance, cost governance,
secret governance, release / packaging, observability and replay,
policy / sandbox / security explainability, app installations,
and the configuration / channel / environment wizards.

It lives under
[`openmiura/application/admin/service/`](../../openmiura/application/admin/service/).
External callers (the HTTP routes under
`openmiura/interfaces/http/routes/admin/` and the broker routes
under `openmiura/interfaces/broker/routes/admin/`) instantiate
exactly one `AdminService()` per application and call methods on
it directly.

## Why a mixin package

The original implementation was a single file `service.py` of
**6,734 lines** (one class, 280 methods). After Phase 1.2 split
the HTTP route layer into sub-routers, the `AdminService` class
itself remained the orchestration god-class.

The post-cleanup layout splits the single class into a package
where `__init__.py` defines `AdminService` as a thin shell that
inherits from 17 domain-specific mixins, one module each. The
constructor, the injected services and the method surface are
unchanged; external callers are untouched.

## Layout

```
openmiura/application/admin/service/
    __init__.py                            # constructor (10 injected services)
                                            #   + late-binding rebind
    _apps_mixin.py                         # app_deep_links / installations / notifications
    _canvas_mixin.py                       # canvas-related admin operations
    _core_mixin.py                         # status_snapshot, memory, sessions,
                                            #   identities, reload, generic admin
    _cost_governance_mixin.py              # cost dashboards and budgets
    _evaluations_mixin.py                  # evaluation runs and case results
    _governance_mixin.py                   # policy / security / sandbox / compliance
                                            #   explainability
    _helpers_mixin.py                      # private utilities (_safe_call etc.)
    _memory_mixin.py                       # memory store admin operations
    _operator_mixin.py                     # operator inspector, traces, replay
    _release_packaging_mixin.py            # release governance + packaging hardening
    _runtime_adapters_a_mixin.py           # 51 openclaw admin methods (half)
    _runtime_adapters_b_mixin.py           # 46 openclaw admin methods (other half)
    _secrets_mixin.py                      # secret governance admin operations
    _sessions_mixin.py                     # session inspection
    _system_mixin.py                       # config-center / channel-wizard / env-wizard
    _voice_mixin.py                        # voice runtime admin operations
    _workflows_mixin.py                    # workflows and approvals
```

Every file is under the **1,500-line ceiling**. The largest mixin
is `_runtime_adapters_a_mixin.py` at 1,190 lines.

## Constructor — injected services

`AdminService.__init__` wires together 11 collaborating services.
This wiring is the source of truth for how the admin layer
composes; the mixins themselves are stateless behaviour groupings.

```python
def __init__(self, *,
    memory_service: MemoryService | None = None,
    session_service: SessionService | None = None,
    evaluation_service: EvaluationService | None = None,
    cost_governance_service: CostGovernanceService | None = None,
) -> None:
    self.memory_service       = memory_service or MemoryService()
    self.session_service      = session_service or SessionService()
    self.evaluation_service   = evaluation_service or EvaluationService()
    self.cost_governance_service = cost_governance_service or CostGovernanceService()
    self.tenancy_service      = TenancyService()
    self.replay_service       = ReplayService()
    self.operator_console_service = OperatorConsoleService(replay_service=self.replay_service)
    self.secret_governance_service = SecretGovernanceService()
    self.release_service      = ReleaseService()
    self.voice_runtime_service = VoiceRuntimeService()
    self.pwa_foundation_service = PWAFoundationService()
    self.openclaw_adapter_service = OpenClawAdapterService()
    self.openclaw_recovery_scheduler_service = OpenClawRecoverySchedulerService(
        openclaw_adapter_service=self.openclaw_adapter_service,
    )
    self.live_canvas_service  = LiveCanvasService(
        cost_governance_service=self.cost_governance_service,
        operator_console_service=self.operator_console_service,
        secret_governance_service=self.secret_governance_service,
        openclaw_adapter_service=self.openclaw_adapter_service,
        openclaw_recovery_scheduler_service=self.openclaw_recovery_scheduler_service,
    )
    self.packaging_hardening_service = PackagingHardeningService()
```

Mixins access these attributes via `self.<attribute>`; no further
wiring lives inside the mixin modules.

## Late-binding

Only two of the 280 admin methods reference `AdminService` by
class name (vs the 162 in the canvas case). The late-binding
sentinel and rebind block are nevertheless applied uniformly from
the start so the pattern stays consistent across the codebase.

## Status

| Metric | Value |
|---|---:|
| Files in `openmiura/application/admin/service/` over 1,500 lines | 0 |
| Largest file | 1,190 (`_runtime_adapters_a_mixin.py`) |
| Methods on the public class | 280 (unchanged) |
| Original god-class size | 6,734 lines |
| Reduction in largest file | 82% |
