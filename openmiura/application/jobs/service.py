from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from openmiura.application.workflows.service import WorkflowService


class JobService:
    def __init__(self, *, workflow_service: WorkflowService | None = None) -> None:
        self.workflow_service = workflow_service or WorkflowService()

    def _publish(self, gw, event_type: str, **payload: Any) -> None:
        bus = getattr(gw, 'realtime_bus', None)
        if bus is None:
            return
        normalized = dict(payload or {})
        normalized.setdefault('topic', 'workflow')
        normalized.setdefault('entity_kind', 'job')
        if normalized.get('job_id') is not None:
            normalized.setdefault('entity_id', normalized.get('job_id'))
            normalized.setdefault('session_id', self._session_id(str(normalized.get('job_id'))))
        try:
            bus.publish(event_type, **normalized)
        except Exception:
            pass

    def _session_id(self, job_id: str) -> str:
        return f'job:{job_id}'

    def _log(self, gw, job_id: str, actor: str, payload: dict[str, Any], *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> None:
        gw.audit.log_event(
            direction='workflow',
            channel='workflow',
            user_id=str(actor or 'system'),
            session_id=self._session_id(job_id),
            payload=payload,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def _with_operational_state(self, item: dict[str, Any] | None, *, now: float | None = None) -> dict[str, Any] | None:
        if item is None:
            return None
        now_ts = float(now if now is not None else time.time())
        payload = dict(item)
        state = 'scheduled'
        if not payload.get('enabled', True):
            state = 'paused'
        elif payload.get('not_before') is not None and now_ts < float(payload['not_before']):
            state = 'waiting_window'
        elif payload.get('not_after') is not None and now_ts > float(payload['not_after']):
            state = 'window_closed'
        elif payload.get('max_runs') is not None and int(payload.get('run_count') or 0) >= int(payload.get('max_runs') or 0):
            state = 'exhausted'
        elif str(payload.get('last_error') or '').strip():
            state = 'error'
        elif self._is_due(payload, now=now_ts):
            state = 'due'
        payload['operational_state'] = state
        payload['is_due'] = self._is_due(payload, now=now_ts)
        payload['next_run_in_s'] = None if payload.get('next_run_at') is None else max(0.0, float(payload['next_run_at']) - now_ts)
        return payload

    def _summary(self, items: list[dict[str, Any]], *, now: float | None = None) -> dict[str, Any]:
        out = {
            'total': 0,
            'by_state': {},
            'due': 0,
            'enabled': 0,
            'paused': 0,
            'error': 0,
        }
        for item in items:
            enriched = self._with_operational_state(item, now=now) or {}
            state = str(enriched.get('operational_state') or 'scheduled')
            out['total'] += 1
            out['by_state'][state] = int(out['by_state'].get(state) or 0) + 1
            if enriched.get('enabled'):
                out['enabled'] += 1
            else:
                out['paused'] += 1
            if enriched.get('is_due'):
                out['due'] += 1
            if state == 'error':
                out['error'] += 1
        return out

    def _tzinfo(self, timezone_name: str | None):
        if not timezone_name:
            return timezone.utc
        try:
            return ZoneInfo(str(timezone_name))
        except Exception:
            return timezone.utc

    def _parse_cron_field(self, value: int, expr: str, *, minimum: int, maximum: int) -> bool:
        def _parse_int(raw: str) -> int:
            number = int(raw)
            if number < minimum or number > maximum:
                raise ValueError(f'cron field value out of range: {number} not in [{minimum}, {maximum}]')
            return number

        text = str(expr).strip()
        if text == '*':
            return True
        if text.startswith('*/'):
            step = int(text[2:])
            if step <= 0:
                raise ValueError('cron step must be > 0')
            return (value - minimum) % step == 0
        for part in text.split(','):
            part = part.strip()
            if not part:
                continue
            if '-' in part:
                left_raw, right_raw = part.split('-', 1)
                left = _parse_int(left_raw)
                right = _parse_int(right_raw)
                if left > right:
                    raise ValueError('cron range start must be <= end')
                if left <= value <= right:
                    return True
                continue
            if _parse_int(part) == value:
                return True
        return False

    def _next_cron_run(self, cron_expr: str, *, after_ts: float, timezone_name: str | None = None) -> float | None:
        parts = str(cron_expr or '').strip().split()
        if len(parts) != 5:
            raise ValueError('cron_expr must have 5 fields: minute hour day month weekday')
        minute_expr, hour_expr, day_expr, month_expr, weekday_expr = parts
        tz = self._tzinfo(timezone_name)
        current = datetime.fromtimestamp(float(after_ts), tz=tz).replace(second=0, microsecond=0) + timedelta(minutes=1)
        for _ in range(0, 60 * 24 * 370):
            weekday = current.weekday()
            if not self._parse_cron_field(current.minute, minute_expr, minimum=0, maximum=59):
                current += timedelta(minutes=1)
                continue
            if not self._parse_cron_field(current.hour, hour_expr, minimum=0, maximum=23):
                current += timedelta(minutes=1)
                continue
            if not self._parse_cron_field(current.day, day_expr, minimum=1, maximum=31):
                current += timedelta(minutes=1)
                continue
            if not self._parse_cron_field(current.month, month_expr, minimum=1, maximum=12):
                current += timedelta(minutes=1)
                continue
            cron_weekday = (weekday + 1) % 7
            if not self._parse_cron_field(cron_weekday, weekday_expr, minimum=0, maximum=6):
                current += timedelta(minutes=1)
                continue
            return current.timestamp()
        return None

    def _compute_next_run_at(self, item: dict[str, Any], *, now: float | None = None) -> float | None:
        now_ts = float(now if now is not None else time.time())
        if not item.get('enabled', True):
            return None
        if item.get('not_after') is not None and now_ts > float(item['not_after']):
            return None
        max_runs = item.get('max_runs')
        if max_runs is not None and int(item.get('run_count') or 0) >= int(max_runs):
            return None
        schedule_kind = str(item.get('schedule_kind') or 'interval').strip().lower() or 'interval'
        if schedule_kind == 'once':
            return None
        if schedule_kind == 'cron':
            expr = item.get('schedule_expr') or item.get('cron_expr')
            if not expr:
                return None
            return self._next_cron_run(str(expr), after_ts=now_ts, timezone_name=item.get('timezone'))
        interval_s = item.get('interval_s')
        if interval_s is None:
            return None
        return now_ts + int(interval_s)

    def _is_due(self, item: dict[str, Any], *, now: float | None = None) -> bool:
        now_ts = float(now if now is not None else time.time())
        if not item.get('enabled', True):
            return False
        if item.get('not_before') is not None and now_ts < float(item['not_before']):
            return False
        if item.get('not_after') is not None and now_ts > float(item['not_after']):
            return False
        max_runs = item.get('max_runs')
        if max_runs is not None and int(item.get('run_count') or 0) >= int(max_runs):
            return False
        next_run_at = item.get('next_run_at')
        if next_run_at is None:
            return True if str(item.get('schedule_kind') or 'interval') == 'once' and int(item.get('run_count') or 0) == 0 else False
        return float(next_run_at) <= now_ts

    def create_job(
        self,
        gw,
        *,
        name: str,
        workflow_definition: dict[str, Any],
        created_by: str,
        input_payload: dict[str, Any] | None = None,
        interval_s: int | None = None,
        next_run_at: float | None = None,
        enabled: bool = True,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        playbook_id: str | None = None,
        schedule_kind: str = 'interval',
        schedule_expr: str | None = None,
        timezone_name: str | None = 'UTC',
        not_before: float | None = None,
        not_after: float | None = None,
        max_runs: int | None = None,
    ) -> dict[str, Any]:
        normalized_kind = str(schedule_kind or 'interval').strip().lower() or 'interval'
        if normalized_kind not in {'interval', 'cron', 'once'}:
            raise ValueError('Unsupported schedule_kind')
        if normalized_kind == 'interval' and interval_s is None:
            raise ValueError('interval_s is required for interval schedules')
        if normalized_kind == 'cron' and not schedule_expr:
            raise ValueError('schedule_expr is required for cron schedules')
        if next_run_at is None:
            if normalized_kind == 'once':
                next_run_at = float(not_before if not_before is not None else time.time())
            elif normalized_kind == 'cron':
                next_run_at = self._next_cron_run(str(schedule_expr), after_ts=time.time() - 60.0, timezone_name=timezone_name)
            elif interval_s is not None:
                next_run_at = time.time() + int(interval_s)
        created = gw.audit.create_job_schedule(
            name=str(name or 'job'),
            workflow_definition=workflow_definition,
            created_by=str(created_by or 'system'),
            input_payload=dict(input_payload or {}),
            interval_s=interval_s,
            next_run_at=next_run_at,
            enabled=enabled,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            playbook_id=playbook_id,
            schedule_kind=normalized_kind,
            schedule_expr=schedule_expr,
            timezone=timezone_name,
            not_before=not_before,
            not_after=not_after,
            max_runs=max_runs,
        )
        self._log(gw, created['job_id'], created_by, {'event': 'job_created', 'job_id': created['job_id'], 'name': created['name'], 'schedule_kind': normalized_kind}, tenant_id=created.get('tenant_id'), workspace_id=created.get('workspace_id'), environment=created.get('environment'))
        self._publish(gw, 'job_created', job_id=created['job_id'], name=created['name'], schedule_kind=normalized_kind, tenant_id=created.get('tenant_id'), workspace_id=created.get('workspace_id'), environment=created.get('environment'))
        return self._with_operational_state(created)

    def list_jobs(self, gw, *, limit: int = 100, enabled: bool | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any]:
        items = gw.audit.list_job_schedules(limit=limit, enabled=enabled, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        enriched = [self._with_operational_state(item) for item in items]
        return {'ok': True, 'items': enriched, 'summary': self._summary([item for item in items])}

    def jobs_summary(self, gw, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None, limit: int = 200) -> dict[str, Any]:
        items = gw.audit.list_job_schedules(limit=limit, enabled=None, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        enriched = [self._with_operational_state(item) for item in items]
        due_items = [item for item in enriched if item and item.get('is_due')]
        due_items.sort(key=lambda item: float(item.get('next_run_at') or 0.0))
        return {'ok': True, 'summary': self._summary([item for item in items]), 'due_items': due_items[:20], 'items': enriched[:20]}

    def get_job(self, gw, job_id: str, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any] | None:
        return self._with_operational_state(gw.audit.get_job_schedule(job_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment))

    def pause_job(self, gw, job_id: str, *, actor: str = 'system', tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any] | None:
        item = self.get_job(gw, job_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if item is None:
            return None
        gw.audit.update_job_schedule(job_id, enabled=False, updated_at=time.time(), tenant_id=item.get('tenant_id'), workspace_id=item.get('workspace_id'), environment=item.get('environment'))
        refreshed = self.get_job(gw, job_id, tenant_id=item.get('tenant_id'), workspace_id=item.get('workspace_id'), environment=item.get('environment'))
        if refreshed is not None:
            self._log(gw, job_id, actor, {'event': 'job_paused', 'job_id': job_id}, tenant_id=refreshed.get('tenant_id'), workspace_id=refreshed.get('workspace_id'), environment=refreshed.get('environment'))
            self._publish(gw, 'job_paused', job_id=job_id, tenant_id=refreshed.get('tenant_id'), workspace_id=refreshed.get('workspace_id'), environment=refreshed.get('environment'))
        return refreshed

    def resume_job(self, gw, job_id: str, *, actor: str = 'system', tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any] | None:
        item = self.get_job(gw, job_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if item is None:
            return None
        next_run_at = item.get('next_run_at')
        if next_run_at is None:
            next_run_at = self._compute_next_run_at(item, now=time.time())
        gw.audit.update_job_schedule(job_id, enabled=True, next_run_at=next_run_at, updated_at=time.time(), tenant_id=item.get('tenant_id'), workspace_id=item.get('workspace_id'), environment=item.get('environment'))
        refreshed = self.get_job(gw, job_id, tenant_id=item.get('tenant_id'), workspace_id=item.get('workspace_id'), environment=item.get('environment'))
        if refreshed is not None:
            self._log(gw, job_id, actor, {'event': 'job_resumed', 'job_id': job_id, 'next_run_at': refreshed.get('next_run_at')}, tenant_id=refreshed.get('tenant_id'), workspace_id=refreshed.get('workspace_id'), environment=refreshed.get('environment'))
            self._publish(gw, 'job_resumed', job_id=job_id, next_run_at=refreshed.get('next_run_at'), tenant_id=refreshed.get('tenant_id'), workspace_id=refreshed.get('workspace_id'), environment=refreshed.get('environment'))
        return refreshed

    def run_job(self, gw, job_id: str, *, actor: str, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any]:
        item = gw.audit.get_job_schedule(job_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if item is None:
            raise LookupError('Unknown job')
        if not self._is_due(item, now=time.time()):
            raise ValueError('Job is not due or cannot run in current window')
        self._log(gw, job_id, actor, {'event': 'job_run_started', 'job_id': job_id}, tenant_id=item.get('tenant_id'), workspace_id=item.get('workspace_id'), environment=item.get('environment'))
        self._publish(gw, 'job_run_started', job_id=job_id, tenant_id=item.get('tenant_id'), workspace_id=item.get('workspace_id'), environment=item.get('environment'))
        workflow = self.workflow_service.create_workflow(
            gw,
            name=f"job:{item['name']}",
            definition=dict(item.get('workflow_definition') or {}),
            created_by=str(actor or item.get('created_by') or 'system'),
            input_payload=dict(item.get('input') or {}),
            tenant_id=item.get('tenant_id'),
            workspace_id=item.get('workspace_id'),
            environment=item.get('environment'),
            source_job_id=item['job_id'],
            playbook_id=item.get('playbook_id'),
        )
        try:
            run = self.workflow_service.run_workflow(
                gw,
                workflow['workflow_id'],
                actor=actor,
                tenant_id=item.get('tenant_id'),
                workspace_id=item.get('workspace_id'),
                environment=item.get('environment'),
            )
            last_error = ''
        except Exception as exc:
            run = gw.audit.get_workflow(
                workflow['workflow_id'],
                tenant_id=item.get('tenant_id'),
                workspace_id=item.get('workspace_id'),
                environment=item.get('environment'),
            ) or workflow
            last_error = str(exc)
        now_ts = time.time()
        current_runs = int(item.get('run_count') or 0) + 1
        refreshed_item = dict(item)
        refreshed_item['run_count'] = current_runs
        next_run_at = self._compute_next_run_at(refreshed_item, now=now_ts)
        gw.audit.update_job_schedule(
            job_id,
            last_run_at=now_ts,
            next_run_at=next_run_at,
            run_count=current_runs,
            updated_at=now_ts,
            last_error=last_error,
            tenant_id=item.get('tenant_id'),
            workspace_id=item.get('workspace_id'),
            environment=item.get('environment'),
        )
        refreshed = self.get_job(gw, job_id, tenant_id=item.get('tenant_id'), workspace_id=item.get('workspace_id'), environment=item.get('environment'))
        event_name = 'job_run_failed' if last_error else 'job_run_completed'
        self._log(gw, job_id, actor, {'event': event_name, 'job_id': job_id, 'workflow_id': workflow['workflow_id'], 'error': last_error}, tenant_id=item.get('tenant_id'), workspace_id=item.get('workspace_id'), environment=item.get('environment'))
        self._publish(gw, event_name, job_id=job_id, workflow_id=workflow['workflow_id'], error=last_error, tenant_id=item.get('tenant_id'), workspace_id=item.get('workspace_id'), environment=item.get('environment'))
        return {'job': refreshed, 'workflow': run}

    def run_due_jobs(self, gw, *, actor: str, limit: int = 20, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any]:
        now_ts = time.time()
        jobs = gw.audit.list_job_schedules(limit=limit, enabled=True, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        executed: list[dict[str, Any]] = []
        for item in jobs:
            if not self._is_due(item, now=now_ts):
                continue
            executed.append(self.run_job(gw, item['job_id'], actor=actor, tenant_id=item.get('tenant_id'), workspace_id=item.get('workspace_id'), environment=item.get('environment')))
        return {'ok': True, 'items': executed, 'summary': self._summary([entry['job'] for entry in executed if entry.get('job')])}
