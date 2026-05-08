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

Phase 1 splits the persistence logic into specialized repositories
without changing the public API. Existing callers
(`VoiceService`, `EvaluationService`, `AdminService`,
`AuditStore.get_audit_store_overview`, …) continue to work because
`AuditStore` keeps every previous method as a one-line delegator.

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
    tools_repo.py             # tool_calls, decision_traces
    voice_repo.py             # voice_sessions/transcripts/outputs/commands/
                              #   audio_assets/provider_calls
    workflows_repo.py         # workflows, approvals, job_schedules
```

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

Phase 1 deliberately did **not** extract:

- `sessions`, `messages`, `events`, `identity_map`, `telegram_state`,
  `slack_event_dedupe` — about 26 methods. These are the source of
  truth for scope inference (`tenant_id`, `workspace_id`,
  `environment` are read from `sessions` to enrich any other event)
  and several other repos still call `_infer_scope_from_session`
  through the shared `base.infer_scope_from_session(conn, …)`
  helper. Extracting them is a separate sprint.
- The init / migration plumbing (`__init__`, `init_db`,
  `_ensure_memory_columns`).
- The high-level read aggregator `get_audit_store_overview` /
  `table_counts` / `table_counts_scoped` — they call into the
  per-domain repos through the existing facade.
- The static / instance scope helpers (`_scope_payload`, `_row_scope`,
  `_scope_where`, `_infer_scope_from_session`). These are now
  one-line wrappers over `base.py` so both the facade and any
  repository can use them.

## Adding a new persistence domain

1. Create `openmiura/persistence/<domain>_repo.py` with a class that
   takes a `DBConnection` in `__init__`. Mirror the
   `_scope_payload` / `_row_scope` / `_scope_where` /
   `_infer_scope_from_session` shims from any existing repo.
2. Move the methods from `AuditStore` into the new class verbatim.
3. In `AuditStore.__init__`, instantiate
   `self._<attr> = <Class>(self._conn)` next to the other repos.
4. Replace each method on `AuditStore` with a one-line delegator
   `return self._<attr>.<name>(...)`.
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

Phase 1 sprints 1–4 are complete: 11 repositories, 252 methods
extracted, audit.py down from 5,693 to about 2,100 lines. Remaining
work tracked under `docs/_workjournal/` and the master plan in
[`CLAUDE.md`](../../CLAUDE.md).
