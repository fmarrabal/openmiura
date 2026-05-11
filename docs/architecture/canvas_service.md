# Canvas service

The canvas service implements the operations canvas that an
operator sees inside the admin UI: live documents, nodes, edges,
views, presence, comments, snapshots, the runtime / baseline
promotion board, the node inspector, the timeline, and the node
actions that an operator can execute.

It lives under
[`openmiura/application/canvas/service/`](../../openmiura/application/canvas/service/).
The public class is `LiveCanvasService`; external callers
(`AdminService` and the two openclaw portfolio tests) continue to
import it from
`openmiura.application.canvas` unchanged.

## Why a mixin package

The original implementation was a single file `service.py` of
**11,519 lines** (one class, 141 methods). That file was the
largest god-object remaining in the repo after Phase 1.2.

The post-cleanup layout splits the single class into a package
where `__init__.py` defines `LiveCanvasService` as a thin shell
inheriting from a set of domain-specific mixins, one module each.
Every method keeps the same signature; the constructor is identical;
external callers are untouched.

## Layout

```
openmiura/application/canvas/service/
    __init__.py                              # constructor + late-binding rebind
    _helpers_mixin.py                        # shared private helpers
    _data_mixin.py                           # documents / nodes / edges / views /
                                             #   presence / comments / snapshots /
                                             #   overlays / events / sharing
    _board_mixin.py                          # get_runtime_board, get_baseline_promotion_board
    _timeline_mixin.py                       # get_node_timeline + helpers
    _node_inspector_mixin.py                 # get_node_inspector + node references
    _node_data_mixin.py                      # _replace_node_data, _minimize_node_data_for_storage
    _baseline_promotion_compactors_mixin.py  # serialise baseline-promotion payloads
    _baseline_promotion_state_mixin.py       # simulation state machinery
    _baseline_promotion_exports_mixin.py     # attestation / compliance / reconciliation exports
    _baseline_promotion_other_mixin.py       # residual baseline_promotion helpers
    _baseline_promotion_catalog_a_mixin.py   # 36 of the 57 catalog methods
    _baseline_promotion_catalog_b_mixin.py   # the remaining 21 catalog methods
    _node_actions_mixin/                     # sub-package (see below)
        __init__.py                          # aggregator + late-binding proxy
        _dispatch_mixin.py                   # execute_node_action + 4 outer handlers
                                             #   + _node_action_precheck
        _baseline_promotion_a_mixin.py       # 6 baseline_promotion sub-handlers
        _baseline_promotion_b_mixin.py       # 5 baseline_promotion sub-handlers
        _baseline_promotion_c_mixin.py       # 8 baseline_promotion sub-handlers
```

Every file under the canvas service package is **under the
1,500-line ceiling** (the master plan's DoD for production code).
The largest is `_node_data_mixin.py` at 1,326 lines.

## execute_node_action — internal dispatcher

The original `execute_node_action` method was **2,957 lines** in
itself (one method, one giant `if node_type == ... elif ...` with
a deeply nested `if normalized_action == ... elif ...` inside the
baseline_promotion branch — 19 sub-branches).

The current layout rewrites the method as a two-stage dispatcher:

1. **Outer dispatch** (in `_dispatch_mixin.py`):

   ```
   execute_node_action(self, gw, ...) -> dict
     if node_type == 'workflow':         _execute_workflow_action(...)
     elif node_type == 'approval':       _execute_approval_action(...)
     elif node_type in {'runtime', ...}: _execute_runtime_action(...)
     elif node_type in {'baseline_*'}:   _execute_baseline_promotion_action(...)
     else:                                raise ValueError(...)
   ```

   Each outer handler is a regular method on the `_dispatch_mixin`.

2. **Inner dispatch** (still in `_dispatch_mixin.py`):

   ```
   _execute_baseline_promotion_action(self, gw, ...) -> dict
     if normalized_action in {'simulate', ...}:                       _baseline_promotion_action_simulate(...)
     elif normalized_action in {'approve_simulation', ...}:           _baseline_promotion_action_approve_simulation(...)
     elif normalized_action in {'export_simulation_attestation', ...}: _baseline_promotion_action_export_simulation_attestation(...)
     # ... 19 sub-handlers in total ...
   ```

   The 19 sub-handlers are split across the three
   `_baseline_promotion_<a|b|c>_mixin.py` files inside the
   `_node_actions_mixin/` sub-package.

Each handler receives the outer-scope locals as `**ctx` kwargs —
no analysis of which Names a branch uses was needed. The result is
returned by the handler instead of being assigned to a local
`result` in the dispatcher's body.

After this refactor, the largest method in the canvas service is
449 lines.

## Late-binding propagation

A handful of the canvas mixins contain `@staticmethod`s that
reference `LiveCanvasService` by name (e.g.
`LiveCanvasService._compact_baseline_promotion_simulation_export_report(...)`).
That reference does not resolve at import time because the class
is defined in `service/__init__.py` and the mixin modules are
imported first.

To fix this without circular imports, each mixin module declares
`LiveCanvasService: type | None = None` at module scope as a
sentinel. `service/__init__.py`, after defining the class,
rebinds the symbol on every mixin module:

```python
for _mod in (_m1, _m2, ...):
    _mod.LiveCanvasService = LiveCanvasService
```

For the `_node_actions_mixin/` sub-package the same mechanism is
applied one level deeper: the sub-package `__init__.py` exposes a
`_PackageProxy` class that intercepts assignments and propagates
them down to every sub-module. When `service/__init__.py` does
`_node_actions_mixin.LiveCanvasService = LiveCanvasService`, the
proxy pushes the value to `_dispatch_mixin`,
`_baseline_promotion_a_mixin`, `_baseline_promotion_b_mixin` and
`_baseline_promotion_c_mixin`.

## Compatibility constraints

- `LiveCanvasService`'s constructor signature is unchanged: five
  optional injected services (`cost_governance_service`,
  `operator_console_service`, `secret_governance_service`,
  `openclaw_adapter_service`,
  `openclaw_recovery_scheduler_service`).
- Class constants (`MAX_DOCUMENTS_PER_SCOPE`, `MAX_NODES_PER_CANVAS`,
  `MAX_EDGES_PER_CANVAS`, `MAX_VIEWS_PER_CANVAS`, `MAX_PAYLOAD_CHARS`,
  `MAX_COMMENT_CHARS`, `MAX_SNAPSHOT_BYTES`, `_DEFAULT_TOGGLES`)
  are preserved on the final class.
- The method surface is identical — 141 methods on the class are
  all reachable via `self.method_name(...)`.

## Status

| Metric | Value |
|---|---:|
| Files in `openmiura/application/canvas/service/` over 1,500 lines | 0 |
| Largest file | 1,326 (`_node_data_mixin.py`) |
| Largest method | 449 (a sub-handler in `_baseline_promotion_b_mixin.py`) |
| Original god-class size | 11,519 lines |
| Reduction in largest file | 88% |
