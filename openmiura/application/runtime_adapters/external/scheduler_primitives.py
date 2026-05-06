from __future__ import annotations

import os
import socket
import time
import uuid
from typing import Any


def scope(*, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any]:
    return {
        'tenant_id': str(tenant_id).strip() if tenant_id is not None else None,
        'workspace_id': str(workspace_id).strip() if workspace_id is not None else None,
        'environment': str(environment).strip() if environment is not None else None,
    }


def is_workflow_job(item: dict[str, Any] | None, *, kind: str, field_name: str | None = None, field_value: str | None = None) -> bool:
    definition = dict((item or {}).get('workflow_definition') or {})
    if str(definition.get('kind') or '').strip().lower() != str(kind or '').strip().lower():
        return False
    if field_name is None or field_value is None:
        return True
    return str(definition.get(field_name) or '').strip() == str(field_value or '').strip()


def recovery_job_definition(*, runtime_id: str, actor: str, limit: int, reason: str, scheduler_policy: dict[str, Any] | None = None, kind: str) -> dict[str, Any]:
    return {
        'kind': str(kind or '').strip(),
        'runtime_id': str(runtime_id or '').strip(),
        'limit': int(limit),
        'reason': str(reason or '').strip(),
        'scheduler_policy': dict(scheduler_policy or {}),
        'created_by': str(actor or 'system'),
    }


def alert_delivery_job_definition(
    *,
    runtime_id: str,
    alert_code: str,
    workflow_action: str,
    actor: str,
    target: dict[str, Any],
    reason: str,
    escalation_level: int,
    attempt_no: int = 0,
    notification_dispatch_id: str = '',
    route: dict[str, Any] | None = None,
    kind: str,
) -> dict[str, Any]:
    return {
        'kind': str(kind or '').strip(),
        'runtime_id': str(runtime_id or '').strip(),
        'alert_code': str(alert_code or '').strip(),
        'workflow_action': str(workflow_action or 'escalate').strip().lower() or 'escalate',
        'reason': str(reason or '').strip(),
        'escalation_level': int(escalation_level or 0),
        'attempt_no': max(0, int(attempt_no or 0)),
        'notification_dispatch_id': str(notification_dispatch_id or '').strip(),
        'target': dict(target or {}),
        'route': dict(route or {}),
        'created_by': str(actor or 'system'),
    }


def governance_wave_advance_job_definition(*, bundle_id: str, source_wave_no: int, next_wave_no: int | None, actor: str, reason: str, kind: str) -> dict[str, Any]:
    return {
        'kind': str(kind or '').strip(),
        'bundle_id': str(bundle_id or '').strip(),
        'source_wave_no': int(source_wave_no or 0),
        'next_wave_no': int(next_wave_no or 0) if next_wave_no else None,
        'reason': str(reason or '').strip(),
        'created_by': str(actor or 'system'),
    }


def governance_wave_job_id(bundle_id: str, source_wave_no: int) -> str:
    return f'openclaw-governance-wave-advance:{str(bundle_id or "").strip()}:{int(source_wave_no or 0)}'


def baseline_wave_advance_job_definition(*, promotion_id: str, source_wave_no: int, next_wave_no: int | None, actor: str, reason: str, kind: str) -> dict[str, Any]:
    return {
        'kind': str(kind or '').strip(),
        'promotion_id': str(promotion_id or '').strip(),
        'source_wave_no': int(source_wave_no or 0),
        'next_wave_no': int(next_wave_no or 0) if next_wave_no else None,
        'reason': str(reason or '').strip(),
        'created_by': str(actor or 'system'),
    }


def baseline_wave_job_id(promotion_id: str, source_wave_no: int) -> str:
    return f'openclaw-baseline-wave-advance:{str(promotion_id or "").strip()}:{int(source_wave_no or 0)}'


def baseline_simulation_custody_job_definition(*, promotion_id: str, actor: str, interval_s: int, reason: str, kind: str) -> dict[str, Any]:
    return {
        'kind': str(kind or '').strip(),
        'promotion_id': str(promotion_id or '').strip(),
        'interval_s': max(60, int(interval_s or 3600)),
        'reason': str(reason or '').strip(),
        'created_by': str(actor or 'system'),
    }


def baseline_simulation_custody_job_id(promotion_id: str) -> str:
    return f'openclaw-baseline-simulation-custody:{str(promotion_id or "").strip()}'


def holder_id(actor: str) -> str:
    host = socket.gethostname() or 'localhost'
    return f'{str(actor or "worker").strip()}:{host}:{os.getpid()}:{uuid.uuid4().hex[:8]}'


def scheduler_policy(item: dict[str, Any] | None) -> dict[str, Any]:
    definition = dict((item or {}).get('workflow_definition') or {})
    raw = dict(definition.get('scheduler_policy') or {})
    try:
        lease_ttl_s = int(raw.get('lease_ttl_s') or 120)
    except Exception:
        lease_ttl_s = 120
    try:
        idempotency_ttl_s = int(raw.get('idempotency_ttl_s') or 1800)
    except Exception:
        idempotency_ttl_s = 1800
    try:
        workspace_backpressure_limit = int(raw.get('workspace_backpressure_limit') or 1)
    except Exception:
        workspace_backpressure_limit = 1
    return {
        **raw,
        'lease_ttl_s': max(5, lease_ttl_s),
        'idempotency_ttl_s': max(30, idempotency_ttl_s),
        'workspace_backpressure_limit': max(1, workspace_backpressure_limit),
        'runtime_exclusive': bool(raw.get('runtime_exclusive', True)),
    }


def due_slot(item: dict[str, Any] | None, *, now: float | None = None) -> int:
    base = (item or {}).get('next_run_at')
    if base is None:
        base = now if now is not None else time.time()
    try:
        return int(float(base))
    except Exception:
        return int(now if now is not None else time.time())


def job_lease_key(job_id: str) -> str:
    return f'openclaw-recovery:job:{str(job_id or "").strip()}'


def runtime_lease_key(runtime_id: str) -> str:
    return f'openclaw-recovery:runtime:{str(runtime_id or "").strip()}'


def workspace_lease_prefix(scope_data: dict[str, Any]) -> str:
    return 'openclaw-recovery:workspace:{tenant}:{workspace}:{environment}:'.format(
        tenant=str(scope_data.get('tenant_id') or '-').strip() or '-',
        workspace=str(scope_data.get('workspace_id') or '-').strip() or '-',
        environment=str(scope_data.get('environment') or '-').strip() or '-',
    )


def workspace_lease_keys(scope_data: dict[str, Any], *, limit: int) -> list[str]:
    prefix = workspace_lease_prefix(scope_data)
    return [f'{prefix}{idx}' for idx in range(max(1, int(limit)))]


def job_idempotency_key(job_id: str, due_slot_value: int) -> str:
    return f'openclaw-recovery:idempotency:{str(job_id or "").strip()}:{int(due_slot_value)}'


def lease_type(lease_key: str) -> str:
    raw = str(lease_key or '').strip()
    if raw.startswith('openclaw-recovery:job:'):
        return 'job'
    if raw.startswith('openclaw-recovery:runtime:'):
        return 'runtime'
    if raw.startswith('openclaw-recovery:workspace:'):
        return 'workspace'
    return 'other'


def decorate_worker_lease(item: dict[str, Any] | None, *, now: float | None = None) -> dict[str, Any]:
    record = dict(item or {})
    ts = float(now if now is not None else time.time())
    lease_until = float(record.get('lease_until') or 0.0)
    created_at = float(record.get('created_at') or 0.0)
    updated_at = float(record.get('updated_at') or created_at or 0.0)
    lease_key = str(record.get('lease_key') or '').strip()
    record['lease_type'] = lease_type(lease_key)
    record['active'] = lease_until > ts
    record['lease_remaining_s'] = max(0.0, lease_until - ts) if lease_until else 0.0
    record['held_for_s'] = max(0.0, ts - created_at) if created_at else 0.0
    record['updated_age_s'] = max(0.0, ts - updated_at) if updated_at else 0.0
    return record


def decorate_idempotency_record(item: dict[str, Any] | None, *, now: float | None = None) -> dict[str, Any]:
    record = dict(item or {})
    ts = float(now if now is not None else time.time())
    expires_at = record.get('expires_at')
    expires_value = float(expires_at) if expires_at is not None else None
    updated_at = float(record.get('updated_at') or record.get('created_at') or 0.0)
    record['active'] = str(record.get('status') or '').strip().lower() == 'in_progress' and (
        expires_value is None or expires_value > ts
    )
    record['expires_in_s'] = None if expires_value is None else max(0.0, expires_value - ts)
    record['updated_age_s'] = max(0.0, ts - updated_at) if updated_at else 0.0
    key = str(record.get('idempotency_key') or '').strip()
    parts = key.split(':')
    if len(parts) >= 4:
        record['job_id'] = parts[-2]
        record['due_slot'] = int(parts[-1]) if parts[-1].isdigit() else parts[-1]
    else:
        record['job_id'] = ''
        record['due_slot'] = None
    return record


__all__ = [
    'scope',
    'is_workflow_job',
    'recovery_job_definition',
    'alert_delivery_job_definition',
    'governance_wave_advance_job_definition',
    'governance_wave_job_id',
    'baseline_wave_advance_job_definition',
    'baseline_wave_job_id',
    'baseline_simulation_custody_job_definition',
    'baseline_simulation_custody_job_id',
    'holder_id',
    'scheduler_policy',
    'due_slot',
    'job_lease_key',
    'runtime_lease_key',
    'workspace_lease_prefix',
    'workspace_lease_keys',
    'job_idempotency_key',
    'lease_type',
    'decorate_worker_lease',
    'decorate_idempotency_record',
]
