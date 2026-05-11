# Persistence layer

The persistence layer of openMiura lives under
[`openmiura/persistence/`](../../openmiura/persistence/). Each module
in that package owns one bounded domain and its tables. The
`AuditStore` class in
[`openmiura/core/audit.py`](../../openmiura/core/audit.py) is now a
thin facade: it instantiates one repository per domain and exposes
the same public methods as before, each delegating to the
corresponding repository.

## Why this layout

Until Phase 1 of the master plan, all persistence sat inside a single
`AuditStore` class — 5,693 lines, 277 methods, 16 mixed domains.
That made the class hard to read and almost impossible for a new
contributor to extend safely.

Phase 1 (and the follow-up Phase 1.1) splits the persistence logic
into specialized repositories without changing the public API.
Existing callers (`VoiceService`, `EvaluationService`,
`AdminService`, `AuditStore.get_audit_store_overview`, …) continue
to work because `AuditStore` keeps every previous method as a
one-line delegator.

## Layout

```
openmiura/persistence/
    __init__.py
    base.py                   # pure helpers shared by every repo
    apps_repo.py              # app_deep_links, app_installations, app_notifications
    auth_repo.py              # api_tokens, auth_users, auth_sessions
    canvas_repo.py            # canvas docs/nodes/edges/views/presence/comments/snapshots
    evaluations_repo.py       # evaluation_runs, evaluation_case_results
    memory_repo.py            # memory_items
    release_repo.py           # release_bundles + 8 sibling tables (promotions,
                              #   rollbacks, canaries, gate_runs, change_reports,
                              #   routing_decisions, environment_snapshots,
                              #   package_builds, release_approvals)
    runtime_adapters_repo.py  # openclaw_runtime, openclaw_dispatch (legacy DB names)
    runtime_repo.py           # worker_leases, idempotency, runtime_state,
                              #   runtime_alert_states, runtime_governance_policy,
                              #   runtime_alert_notification
    sessions_repo.py          # sessions, messages, events, identity_map,
                              #   telegram_state, slack_event_dedupe
    tools_repo.py             # tool_calls, decision_traces
    voice_repo.py             # voice_sessions/transcripts/outputs/commands/
                              #   audio_assets/provider_calls
    workflows_repo.py         # workflows, approvals, job_schedules
```

**12 repository modules** in total.

## Dependency direction

```
                +------------------------+
                |       AuditStore       |  (facade, openmiura/core/audit.py)
                +-----------+------------+
                            |
                            | one instance per domain
                            v
                +------------------------+
                |  XxxRepo (one per      |
                |  module under          |
                |  openmiura/persistence)|
                +-----------+------------+
                            |
                            v
                +------------------------+
                |   DBConnection         |  (shared)
                +------------------------+
                            ^
                            |
                +-----------+------------+
                |     base.py helpers    |  (pure, stateless)
                +------------------------+
```

`AuditStore` owns the only `DBConnection` and passes it to every
repository in `__init__`. Repositories share that connection, so
transactions and SQLite cursors behave exactly as before the split.

## What the facade still owns

After Phases 1 and 1.1, the facade keeps only the structural plumbing:

- `__init__` (instantiates the 12 repositories with the shared
  `DBConnection`).
- `init_db` and `_ensure_memory_columns` (migration plumbing).
- `table_counts` and `table_counts_scoped` (cross-domain read
  aggregators that call into the per-domain repos through the
  existing facade).
- The static / instance scope helpers (`_scope_payload`,
  `_row_scope`, `_scope_where`, `_infer_scope_from_session`).
  These are one-line wrappers over `base.py` so both the facade
  and any repository can use them.
- 268 one-line delegators — every previously-public method on
  `AuditStore` is preserved here as
  `def x(self, ...) -> ...: return self._<repo>.x(...)`.

The compaction of those delegators to a single line each (Phase 1.1)
brings `audit.py` from 2,145 lines down to **755 lines**.

## Adding a new persistence domain

1. Create `openmiura/persistence/<domain>_repo.py` with a class that
   takes a `DBConnection` in `__init__`. Mirror the
   `_scope_payload` / `_row_scope` / `_scope_where` shims from any
   existing repo.
2. Move the methods from `AuditStore` into the new class verbatim.
3. In `AuditStore.__init__`, instantiate
   `self._<attr> = <Class>(self._conn)` next to the other repos.
4. Replace each method on `AuditStore` with a one-line delegator
   `def x(self, ...) -> ...: return self._<attr>.x(...)`.
5. Run `pytest -q` and the canonical demo
   (`python scripts/run_canonical_demo.py`) and confirm both pass.

## Compatibility constraints

- The `AuditStore` public API is part of the contract used by the
  HTTP and broker layers, by `application/voice/service.py`,
  `application/evaluations/service.py`, and the canonical demo.
  Keep all existing method names and signatures on the facade.
- The `openclaw_*` table names persist in the schema and inside
  `RuntimeAdaptersRepo` for backwards compatibility, even though
  the public-facing module was renamed in Phase 0.
  See [`docs/_archive/refactor/`](../_archive/refactor/) for
  historical context.

## Status

Phase 1 (sprints 1–4) and Phase 1.1 are complete:

| Metric | Value |
|---|---:|
| Repository modules | 12 |
| Methods extracted from AuditStore | 268 (now delegators) |
| Real methods left on AuditStore | 9 (init, scope helpers, structural) |
| `openmiura/core/audit.py` | 755 lines (down from 5,693) |
| Files in `openmiura/persistence/` over 1,500 lines | 0 |

The DoD literal "no production .py over 1,500 lines" is met
across the persistence layer.
