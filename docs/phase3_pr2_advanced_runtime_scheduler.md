# Phase 3 PR2 — advanced workflow runtime, approvals inbox, and scheduler hardening

This iteration continues Phase 3 of the roadmap and adds the next execution capabilities on top of the base workflow engine:

- workflow retries and bounded backoff
- timeout handling for tool steps
- branching steps with simple conditional routing
- compensation steps on failure
- richer approvals inbox operations
- more formal scheduler metadata for jobs

## Workflow runtime

Workflow definitions now support:

- `retry_limit`
- `backoff_s`
- `timeout_s`
- `branch` steps with `condition`, `if_true_step_id`, `if_false_step_id`
- step-local `compensate` blocks
- top-level `on_failure` compensation blocks
- approval expiration via `expires_in_s`

The workflow timeline now emits additional events such as:

- `step_retry_scheduled`
- `branch_evaluated`
- `step_failed`
- `compensation_started`
- `compensation_completed`
- `compensation_failed`

## Approvals inbox

Approvals support:

- filtering by `requested_role`
- filtering by `requested_by`
- filtering by `assignee`
- `GET /broker/approvals/{approval_id}`
- `POST /broker/approvals/{approval_id}/claim`
- automatic expiration of pending approvals when `expires_at` is reached

## Scheduler

Jobs now support a more formal schedule model:

- `schedule_kind`: `interval`, `cron`, `once`
- `schedule_expr` for cron schedules
- `timezone`
- `not_before`
- `not_after`
- `max_runs`
- `run_count`
- `last_error`

Additional endpoints:

- `GET /broker/jobs/{job_id}`
- `POST /broker/jobs/{job_id}/pause`
- `POST /broker/jobs/{job_id}/resume`

## Migration

This iteration adds migration:

- `v6 workflow_runtime_scheduler`

## Validation

Added tests cover:

- retry + branching success path
- timeout + compensation path
- approval claim and filtering
- once jobs, pause/resume, max runs
- cron schedule creation
- migration version updates
