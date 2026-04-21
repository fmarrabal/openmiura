# Sprint 5: surgical refactor of critical monoliths

This sprint reduces maintenance pressure on three high-risk service modules without reopening a macro-refactor:

- `openmiura/application/admin/service.py`
- `openmiura/application/canvas/service.py`
- `openmiura/application/openclaw/scheduler.py`

## What was extracted

### Admin
- `openmiura/application/admin/status_snapshot.py`
- isolates tool-registry discovery and status snapshot assembly

### Canvas
- `openmiura/application/canvas/helpers.py`
- isolates payload sizing, scope normalization, limit enforcement, safe calls, toggle normalization, and redaction helpers

### OpenClaw scheduler
- `openmiura/application/openclaw/scheduler_primitives.py`
- isolates workflow job descriptors, lease/idempotency keys, worker lease decoration, and scheduler policy normalization

## Goal

Keep the public behavior stable while reducing local cognitive load in the biggest operational files and making the extracted logic directly unit-testable.
