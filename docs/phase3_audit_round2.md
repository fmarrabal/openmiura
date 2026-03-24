# Phase 3 audit round 2

This audit pass focused on workflow/approval/job traceability and concurrency correctness.

## Findings fixed

1. **Expired approvals could still be acted upon through claim/decision paths**
   - `ApprovalService.claim(...)` and `ApprovalService.decide(...)` now refresh and expire pending approvals before acting.
   - Result: an approval that crossed `expires_at` cannot be silently claimed or approved afterward.

2. **A claimed approval could still be decided by another actor**
   - `ApprovalService.decide(...)` now enforces assignee ownership, matching the existing claim lock semantics.
   - Broker route now returns `409 Conflict` for this concurrency case.

3. **Workflow tool calls were audited under the workflow creator instead of the actual actor resuming/executing the workflow**
   - `WorkflowService._execute_tool_step(...)` now runs tools with the current actor identity.
   - This closes an audit-traceability gap for approval-driven resumes and manual reruns.

4. **Scoped workflow tool calls were not persisted with tenancy scope**
   - `ToolRuntime.run_tool(...)` now accepts optional `tenant_id`, `workspace_id`, and `environment` and persists them to `tool_calls`.
   - Workflow tool steps and compensation tool steps now pass the resolved scope.
   - Result: scoped admin queries and audits can see workflow-originated tool calls correctly.

5. **Job pause/resume audit events were attributed to `system` even when initiated by a user**
   - `JobService.pause_job(...)` and `JobService.resume_job(...)` now accept `actor` and broker routes pass the authenticated actor through.
   - Result: job operational actions have correct user attribution in the audit trail.

## Tests added

- `test_claimed_approval_cannot_be_decided_by_other_actor`
- `test_workflow_tool_step_uses_current_actor_for_tool_audit`
- `test_job_pause_resume_audit_uses_request_actor`

## Validation

- `pytest -q` → OK
- `python -m compileall -q app.py openmiura tests` → OK
