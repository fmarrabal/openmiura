from __future__ import annotations

import time
from typing import Any, Callable


class OpenClawJobFamilyCommonMixin:
    def _iter_all_job_schedules(
        self,
        gw,
        *,
        enabled: bool | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        batch_size: int = 200,
        max_limit: int = 131072,
    ) -> list[dict[str, Any]]:
        limit = max(1, int(batch_size or 1))
        hard_cap = max(limit, int(max_limit or limit))
        while True:
            items = gw.audit.list_job_schedules(
                limit=limit,
                enabled=enabled,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                environment=environment,
            )
            if len(items) < limit or limit >= hard_cap:
                return items
            limit = min(limit * 2, hard_cap)

    def _find_job_schedule(
        self,
        gw,
        *,
        predicate: Callable[[dict[str, Any]], bool],
        enabled: bool | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        batch_size: int = 200,
    ) -> dict[str, Any] | None:
        for item in self._iter_all_job_schedules(
            gw,
            enabled=enabled,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            batch_size=batch_size,
        ):
            if predicate(item):
                return item
        return None

    def _list_jobs_by_family(
        self,
        gw,
        *,
        matcher: Callable[[dict[str, Any]], bool],
        limit: int = 100,
        enabled: bool | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        batch_size: int | None = None,
        transform: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        items = self._iter_all_job_schedules(
            gw,
            enabled=enabled,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            batch_size=max(int(batch_size or 0), max(int(limit or 0), 50)) if batch_size or limit else 50,
        )
        matched: list[dict[str, Any]] = []
        due_count = 0
        enabled_count = 0
        for item in items:
            if not matcher(item):
                continue
            enriched = self.job_service._with_operational_state(item)
            if enriched is None:
                continue
            if bool(enriched.get('is_due')):
                due_count += 1
            if bool(enriched.get('enabled', True)):
                enabled_count += 1
            view = transform(item, enriched) if transform is not None else dict(enriched)
            matched.append(view)
        safe_limit = max(0, int(limit or 0))
        return {
            'items': matched[:safe_limit],
            'summary': {
                'count': len(matched),
                'returned': min(len(matched), safe_limit),
                'due': due_count,
                'enabled': enabled_count,
            },
        }

    def _run_due_jobs_by_family(
        self,
        gw,
        *,
        matcher: Callable[[dict[str, Any]], bool],
        runner: Callable[..., dict[str, Any]],
        actor: str,
        limit: int = 20,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        batch_size: int | None = None,
        **runner_kwargs,
    ) -> dict[str, Any]:
        items = self._iter_all_job_schedules(
            gw,
            enabled=True,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            batch_size=max(int(batch_size or 0), max(int(limit or 0), 50)) if batch_size or limit else 50,
        )
        executed: list[dict[str, Any]] = []
        scanned = 0
        now_ts = time.time()
        for item in items:
            if not matcher(item):
                continue
            scanned += 1
            if not self.job_service._is_due(item, now=now_ts):
                continue
            executed.append(runner(gw, item=item, actor=actor, **runner_kwargs))
            if len(executed) >= max(0, int(limit or 0)):
                break
        return {
            'items': executed,
            'summary': {
                'count': len(executed),
                'executed': len(executed),
                'scanned': scanned,
            },
        }

    def _complete_job_execution(
        self,
        gw,
        *,
        item: dict[str, Any],
        last_error: str = '',
        next_run_at_override: float | None = None,
        enabled: bool | None = None,
    ) -> dict[str, Any] | None:
        job_id = str(item.get('job_id') or '').strip()
        if not job_id:
            return None
        tenant_id = item.get('tenant_id')
        workspace_id = item.get('workspace_id')
        environment = item.get('environment')
        now_ts = time.time()
        refreshed_item = dict(item)
        refreshed_item['run_count'] = int(item.get('run_count') or 0) + 1
        next_run_at = next_run_at_override if next_run_at_override is not None else self.job_service._compute_next_run_at(refreshed_item, now=now_ts)
        update_payload: dict[str, Any] = {
            'last_run_at': now_ts,
            'next_run_at': next_run_at,
            'run_count': int(refreshed_item['run_count']),
            'updated_at': now_ts,
            'last_error': str(last_error or ''),
            'tenant_id': tenant_id,
            'workspace_id': workspace_id,
            'environment': environment,
        }
        if enabled is not None:
            update_payload['enabled'] = bool(enabled)
        gw.audit.update_job_schedule(job_id, **update_payload)
        return self.job_service.get_job(
            gw,
            job_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
