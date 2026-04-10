from __future__ import annotations

import time
from typing import Any


class OpenClawBaselineRolloutJobsMixin:
    def _disable_baseline_promotion_wave_advance_jobs(
        self,
        gw,
        *,
        promotion_id: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        source_wave_no: int | None = None,
        reason: str = '',
    ) -> dict[str, Any]:
        items = self._iter_all_job_schedules(gw, enabled=None, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, batch_size=200)
        disabled = []
        for item in items:
            if not self._is_baseline_wave_advance_job(item, promotion_id=promotion_id):
                continue
            definition = dict(item.get('workflow_definition') or {})
            if source_wave_no is not None and int(definition.get('source_wave_no') or 0) != int(source_wave_no or 0):
                continue
            if not bool(item.get('enabled', True)):
                continue
            updated = gw.audit.update_job_schedule(
                str(item.get('job_id') or ''),
                enabled=False,
                updated_at=time.time(),
                last_error='',
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                environment=environment,
            ) or item
            disabled.append(updated)
        return {'count': len(disabled), 'items': disabled, 'reason': str(reason or '').strip()}


    @staticmethod
    def _baseline_promotion_retry_delay(retry_policy: dict[str, Any] | None, *, retry_attempt: int) -> int:
        policy = dict(retry_policy or {})
        try:
            base_delay = max(0, int(policy.get('backoff_s') or 0))
        except Exception:
            base_delay = 0
        try:
            max_backoff_s = max(base_delay, int(policy.get('max_backoff_s') or base_delay))
        except Exception:
            max_backoff_s = base_delay
        try:
            multiplier = max(1.0, float(policy.get('backoff_multiplier') or 1.0))
        except Exception:
            multiplier = 1.0
        if retry_attempt <= 0:
            return base_delay
        delay = float(base_delay) * (multiplier ** max(0, retry_attempt - 1))
        return max(0, min(int(delay), max_backoff_s))

    def _schedule_baseline_promotion_wave_advance_job(
        self,
        gw,
        *,
        promotion_release: dict[str, Any],
        source_wave: dict[str, Any],
        actor: str,
        reason: str = '',
        requested_advance_after: float | None = None,
    ) -> dict[str, Any] | None:
        metadata = dict(promotion_release.get('metadata') or {})
        promotion = dict(metadata.get('baseline_promotion') or {})
        promotion_policy = self._normalize_baseline_catalog_promotion_policy(dict(promotion.get('promotion_policy') or {}))
        rollout_policy = self._normalize_baseline_catalog_rollout_policy(dict(promotion_policy.get('rollout_policy') or {}))
        if not bool(rollout_policy.get('enabled', False)) or not bool(rollout_policy.get('auto_advance', False)):
            return None
        rollout_plan = self._refresh_baseline_promotion_rollout_plan(dict(promotion.get('rollout_plan') or {}))
        waves = [dict(item) for item in list(rollout_plan.get('items') or [])]
        source_wave_no = int(source_wave.get('wave_no') or 0)
        next_wave_no = source_wave_no + 1
        next_wave = next((wave for wave in waves if int(wave.get('wave_no') or 0) == next_wave_no and str(wave.get('status') or 'planned') == 'planned'), None)
        if next_wave is None:
            return None
        delay_s = max(0, int(rollout_policy.get('auto_advance_window_s') or 0))
        requested_advance_after = max(time.time(), float(requested_advance_after)) if requested_advance_after is not None else time.time() + delay_s
        calendar_decision = self._baseline_rollout_wave_calendar_decision(
            gw,
            promotion_release=promotion_release,
            rollout_policy=rollout_policy,
            requested_at=float(requested_advance_after),
            wave=next_wave,
        )
        advance_after = float(calendar_decision.get('next_allowed_at') or requested_advance_after)
        retry_policy = self._normalize_baseline_catalog_retry_policy(dict(rollout_policy.get('retry_policy') or {}))
        max_runs = max(1, int(retry_policy.get('max_retries') or 0) + 1) if bool(retry_policy.get('enabled', True)) and bool(retry_policy.get('retry_on_advance_failure', True)) else 1
        scope = self._scope(tenant_id=promotion_release.get('tenant_id'), workspace_id=promotion_release.get('workspace_id'), environment=promotion_release.get('environment'))
        job_name = self._baseline_wave_job_id(str(promotion_release.get('release_id') or ''), source_wave_no)
        definition = self._baseline_wave_advance_job_definition(
            promotion_id=str(promotion_release.get('release_id') or ''),
            source_wave_no=source_wave_no,
            next_wave_no=next_wave_no,
            actor=actor,
            reason=reason or f'baseline promotion {promotion_release.get("release_id")} wave {source_wave_no} advance window',
        )
        definition.update({
            'retry_attempt': 0,
            'requested_advance_after': float(requested_advance_after),
            'scheduled_advance_after': float(advance_after),
            'calendar_blockers': list(calendar_decision.get('blockers') or []),
            'portfolio_calendar': [dict(item) for item in list(calendar_decision.get('portfolio_decisions') or [])],
        })
        existing = self._find_job_schedule(
            gw,
            predicate=lambda item: self._is_baseline_wave_advance_job(item, promotion_id=str(promotion_release.get('release_id') or '')) and str((item.get('workflow_definition') or {}).get('source_wave_no') or '') == str(source_wave_no),
            enabled=None,
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
            batch_size=200,
        )
        if existing is not None:
            gw.audit.update_job_schedule(
                str(existing.get('job_id') or ''),
                workflow_definition=definition,
                next_run_at=float(advance_after),
                not_before=float(advance_after),
                updated_at=time.time(),
                last_error='',
                enabled=True,
                max_runs=max_runs,
                tenant_id=scope.get('tenant_id'),
                workspace_id=scope.get('workspace_id'),
                environment=scope.get('environment'),
            )
            job = self.job_service.get_job(gw, str(existing.get('job_id') or ''), tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'))
        else:
            job = self.job_service.create_job(
                gw,
                name=job_name,
                workflow_definition=definition,
                created_by=str(actor or 'system'),
                input_payload={'promotion_id': str(promotion_release.get('release_id') or ''), 'source_wave_no': source_wave_no, 'next_wave_no': next_wave_no},
                next_run_at=float(advance_after),
                enabled=True,
                tenant_id=scope.get('tenant_id'),
                workspace_id=scope.get('workspace_id'),
                environment=scope.get('environment'),
                playbook_id=job_name,
                schedule_kind='once',
                not_before=float(advance_after),
                max_runs=max_runs,
            )
        refreshed_release = gw.audit.get_release_bundle(str(promotion_release.get('release_id') or ''), tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment')) or promotion_release
        refreshed_meta = dict(refreshed_release.get('metadata') or {})
        refreshed_promotion = dict(refreshed_meta.get('baseline_promotion') or {})
        refreshed_plan = self._refresh_baseline_promotion_rollout_plan(dict(refreshed_promotion.get('rollout_plan') or {}))
        refreshed_waves = [dict(item) for item in list(refreshed_plan.get('items') or [])]
        for idx, wave in enumerate(refreshed_waves):
            if int(wave.get('wave_no') or 0) != source_wave_no:
                continue
            scheduled = dict(wave.get('scheduled_advance') or {})
            scheduled.update({
                'status': 'scheduled',
                'scheduled_at': time.time(),
                'scheduled_by': str(actor or 'system'),
                'requested_advance_after': float(requested_advance_after),
                'advance_after': float(advance_after),
                'advance_window_s': delay_s,
                'calendar_blockers': list(calendar_decision.get('blockers') or []),
                'calendar_blocker_windows': [dict(item) for item in list(calendar_decision.get('blocker_windows') or [])][-20:],
                'portfolio_calendar': [dict(item) for item in list(calendar_decision.get('portfolio_decisions') or [])],
                'job_id': str((job or {}).get('job_id') or ''),
                'next_wave_no': next_wave_no,
            })
            wave['scheduled_advance'] = scheduled
            refreshed_waves[idx] = wave
            break
        refreshed_plan['items'] = refreshed_waves
        refreshed_promotion['rollout_plan'] = self._refresh_baseline_promotion_rollout_plan(refreshed_plan)
        refreshed_promotion = self._append_baseline_promotion_timeline_event(
            refreshed_promotion,
            kind='scheduler',
            label='baseline_promotion_wave_auto_advance_scheduled',
            actor=str(actor or 'system'),
            wave_no=source_wave_no,
            next_wave_no=next_wave_no,
            requested_advance_after=float(requested_advance_after),
            advance_after=float(advance_after),
            job_id=str((job or {}).get('job_id') or ''),
            advance_window_s=delay_s,
            calendar_blockers=list(calendar_decision.get('blockers') or []),
            portfolio_calendar=[dict(item) for item in list(calendar_decision.get('portfolio_decisions') or [])],
        )
        refreshed_meta['baseline_promotion'] = refreshed_promotion
        gw.audit.update_release_bundle(
            str(refreshed_release.get('release_id') or ''),
            metadata=refreshed_meta,
            status='awaiting_advance_window',
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        )
        return job

    def list_baseline_promotion_wave_advance_jobs(
        self,
        gw,
        *,
        limit: int = 100,
        promotion_id: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        items = self._iter_all_job_schedules(
            gw,
            enabled=None,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            batch_size=max(limit, 50),
        )
        filtered_all = []
        due_count = 0
        for item in items:
            if not self._is_baseline_wave_advance_job(item, promotion_id=promotion_id):
                continue
            enriched = self.job_service._with_operational_state(item)
            filtered_all.append(enriched)
            if enriched.get('is_due'):
                due_count += 1
        safe_limit = max(0, int(limit))
        return {
            'ok': True,
            'items': filtered_all[:safe_limit],
            'summary': {
                'count': len(filtered_all),
                'returned': min(len(filtered_all), safe_limit),
                'due': due_count,
                'promotion_id': promotion_id,
            },
        }

    def _run_single_baseline_promotion_wave_advance_job(
        self,
        gw,
        *,
        item: dict[str, Any],
        actor: str,
    ) -> dict[str, Any]:
        if not self._is_baseline_wave_advance_job(item):
            raise ValueError('job is not a baseline promotion wave-advance job')
        now_ts = time.time()
        if not self.job_service._is_due(item, now=now_ts):
            raise ValueError('job is not due')
        definition = dict(item.get('workflow_definition') or {})
        promotion_id = str(definition.get('promotion_id') or '').strip()
        source_wave_no = int(definition.get('source_wave_no') or 0)
        next_wave_no = int(definition.get('next_wave_no') or 0) if definition.get('next_wave_no') else None
        retry_attempt = int(definition.get('retry_attempt') or 0)
        detail = self.get_runtime_alert_governance_baseline_promotion(gw, promotion_id=promotion_id, tenant_id=item.get('tenant_id'), workspace_id=item.get('workspace_id'), environment=item.get('environment'))
        if not detail.get('ok'):
            raise LookupError(detail.get('error') or 'baseline_promotion_not_found')
        release = dict(detail.get('release') or {})
        promotion = dict(((release.get('metadata') or {}).get('baseline_promotion') or {}) or {})
        promotion_policy = self._normalize_baseline_catalog_promotion_policy(dict(promotion.get('promotion_policy') or {}))
        rollout_policy = self._normalize_baseline_catalog_rollout_policy(dict(promotion_policy.get('rollout_policy') or {}))
        retry_policy = self._normalize_baseline_catalog_retry_policy(dict(rollout_policy.get('retry_policy') or {}))
        release_status = str(release.get('status') or '')

        def _finalize_job(*, enabled: bool, next_run_at: float | None, run_count: int, last_error: str, workflow_definition: dict[str, Any] | None = None) -> dict[str, Any] | None:
            gw.audit.update_job_schedule(
                str(item.get('job_id') or ''),
                enabled=enabled,
                next_run_at=next_run_at,
                not_before=next_run_at,
                last_run_at=now_ts,
                run_count=run_count,
                updated_at=now_ts,
                workflow_definition=workflow_definition if workflow_definition is not None else dict(item.get('workflow_definition') or {}),
                last_error=last_error,
                tenant_id=item.get('tenant_id'),
                workspace_id=item.get('workspace_id'),
                environment=item.get('environment'),
            )
            return self.job_service.get_job(gw, str(item.get('job_id') or ''), tenant_id=item.get('tenant_id'), workspace_id=item.get('workspace_id'), environment=item.get('environment'))

        pause_state = dict(promotion.get('pause_state') or {})
        if bool(pause_state.get('paused', False)) or release_status == 'paused':
            self._mark_baseline_promotion_wave_advance_state(gw, promotion_release=release, source_wave_no=source_wave_no, actor=actor, status='skipped', reason='promotion_paused', next_wave_no=next_wave_no, job_id=str(item.get('job_id') or ''))
            refreshed = _finalize_job(enabled=False, next_run_at=item.get('next_run_at'), run_count=int(item.get('run_count') or 0), last_error='')
            result = {'ok': True, 'promotion_id': promotion_id, 'wave_no': source_wave_no, 'status': 'skipped', 'reason': 'paused'}
            return {'job': refreshed, 'result': result}
        if release_status in {'completed', 'rolled_back', 'rejected', 'gate_failed'}:
            self._mark_baseline_promotion_wave_advance_state(gw, promotion_release=release, source_wave_no=source_wave_no, actor=actor, status='skipped', reason=f'promotion_{release_status}', next_wave_no=next_wave_no, job_id=str(item.get('job_id') or ''))
            refreshed = _finalize_job(enabled=False, next_run_at=None, run_count=int(item.get('run_count') or 0) + 1, last_error='')
            result = {'ok': True, 'promotion_id': promotion_id, 'wave_no': source_wave_no, 'status': 'skipped', 'reason': release_status}
            return {'job': refreshed, 'result': result}

        rollout_plan = self._refresh_baseline_promotion_rollout_plan(dict(promotion.get('rollout_plan') or {}))
        target_wave = next((wave for wave in list(rollout_plan.get('items') or []) if int(wave.get('wave_no') or 0) == int(next_wave_no or 0)), None)
        calendar_decision = self._baseline_rollout_wave_calendar_decision(gw, promotion_release=release, rollout_policy=rollout_policy, requested_at=float(now_ts), wave=target_wave)
        if not bool(calendar_decision.get('allowed', False)) or float(calendar_decision.get('next_allowed_at') or now_ts) > float(now_ts):
            deferred_until = calendar_decision.get('next_allowed_at')
            reason = str(calendar_decision.get('reason') or ','.join(list(calendar_decision.get('blockers') or [])) or 'window_blocked')
            if deferred_until is None:
                self._mark_baseline_promotion_wave_advance_state(gw, promotion_release=release, source_wave_no=source_wave_no, actor=actor, status='failed', reason=reason, next_wave_no=next_wave_no, job_id=str(item.get('job_id') or ''))
                refreshed = _finalize_job(enabled=False, next_run_at=None, run_count=int(item.get('run_count') or 0) + 1, last_error=reason)
                result = {'ok': False, 'promotion_id': promotion_id, 'wave_no': source_wave_no, 'status': 'failed', 'error': reason}
                return {'job': refreshed, 'result': result}
            deferred_definition = dict(definition)
            deferred_definition['scheduled_advance_after'] = float(deferred_until)
            deferred_definition['calendar_blockers'] = list(calendar_decision.get('blockers') or [])
            deferred_definition['portfolio_calendar'] = [dict(item) for item in list(calendar_decision.get('portfolio_decisions') or [])]
            gw.audit.update_job_schedule(
                str(item.get('job_id') or ''),
                workflow_definition=deferred_definition,
                next_run_at=float(deferred_until),
                not_before=float(deferred_until),
                updated_at=now_ts,
                last_error='',
                enabled=True,
                tenant_id=item.get('tenant_id'),
                workspace_id=item.get('workspace_id'),
                environment=item.get('environment'),
            )
            refreshed_release = gw.audit.get_release_bundle(promotion_id, tenant_id=item.get('tenant_id'), workspace_id=item.get('workspace_id'), environment=item.get('environment')) or release
            self._mark_baseline_promotion_wave_advance_state(gw, promotion_release=refreshed_release, source_wave_no=source_wave_no, actor=actor, status='deferred', reason=reason, next_wave_no=next_wave_no, job_id=str(item.get('job_id') or ''))
            refreshed = self.job_service.get_job(gw, str(item.get('job_id') or ''), tenant_id=item.get('tenant_id'), workspace_id=item.get('workspace_id'), environment=item.get('environment'))
            result = {'ok': True, 'promotion_id': promotion_id, 'wave_no': source_wave_no, 'status': 'deferred', 'reason': reason, 'deferred_until': float(deferred_until), 'blockers': list(calendar_decision.get('blockers') or [])}
            return {'job': refreshed, 'result': result}

        self._mark_baseline_promotion_wave_advance_state(gw, promotion_release=release, source_wave_no=source_wave_no, actor=actor, status='executing', reason='due job execution', next_wave_no=next_wave_no, job_id=str(item.get('job_id') or ''))
        advanced = self._run_baseline_promotion_wave(gw, promotion_release=release, actor=actor, reason=f'auto-advanced after wave {source_wave_no} advance window', wave_no=next_wave_no)
        if advanced.get('ok'):
            refreshed_release = dict(advanced.get('release') or release)
            self._mark_baseline_promotion_wave_advance_state(gw, promotion_release=refreshed_release, source_wave_no=source_wave_no, actor=actor, status='advanced', reason='due job executed', next_wave_no=next_wave_no, job_id=str(item.get('job_id') or ''))
            refreshed = _finalize_job(enabled=False, next_run_at=None, run_count=int(item.get('run_count') or 0) + 1, last_error='')
            result = {'ok': True, 'promotion_id': promotion_id, 'wave_no': source_wave_no, 'status': 'advanced', 'advanced': advanced}
            return {'job': refreshed, 'result': result}

        error_text = str(advanced.get('error') or 'advance_failed')
        retry_enabled = bool(retry_policy.get('enabled', True)) and bool(retry_policy.get('retry_on_advance_failure', True))
        max_retries = int(retry_policy.get('max_retries') or 0)
        if retry_enabled and retry_attempt < max_retries:
            next_retry_attempt = retry_attempt + 1
            retry_delay_s = self._baseline_promotion_retry_delay(retry_policy, retry_attempt=next_retry_attempt)
            retry_requested_at = now_ts + retry_delay_s
            retry_calendar = self._baseline_rollout_wave_calendar_decision(gw, promotion_release=release, rollout_policy=rollout_policy, requested_at=float(retry_requested_at), wave=target_wave)
            retry_at = float(retry_calendar.get('next_allowed_at') or retry_requested_at)
            retry_definition = dict(definition)
            retry_definition['retry_attempt'] = int(next_retry_attempt)
            retry_definition['last_retry_scheduled_at'] = float(now_ts)
            retry_definition['scheduled_advance_after'] = float(retry_at)
            retry_definition['calendar_blockers'] = list(retry_calendar.get('blockers') or [])
            retry_definition['portfolio_calendar'] = [dict(item) for item in list(retry_calendar.get('portfolio_decisions') or [])]
            gw.audit.update_job_schedule(
                str(item.get('job_id') or ''),
                workflow_definition=retry_definition,
                next_run_at=float(retry_at),
                not_before=float(retry_at),
                last_run_at=now_ts,
                run_count=int(item.get('run_count') or 0) + 1,
                updated_at=now_ts,
                last_error='',
                enabled=True,
                tenant_id=item.get('tenant_id'),
                workspace_id=item.get('workspace_id'),
                environment=item.get('environment'),
            )
            refreshed_release = gw.audit.get_release_bundle(promotion_id, tenant_id=item.get('tenant_id'), workspace_id=item.get('workspace_id'), environment=item.get('environment')) or release
            self._mark_baseline_promotion_wave_advance_state(gw, promotion_release=refreshed_release, source_wave_no=source_wave_no, actor=actor, status='retry_scheduled', reason=error_text, next_wave_no=next_wave_no, job_id=str(item.get('job_id') or ''))
            refreshed = self.job_service.get_job(gw, str(item.get('job_id') or ''), tenant_id=item.get('tenant_id'), workspace_id=item.get('workspace_id'), environment=item.get('environment'))
            result = {'ok': True, 'promotion_id': promotion_id, 'wave_no': source_wave_no, 'status': 'retry_scheduled', 'error': error_text, 'retry_attempt': int(next_retry_attempt), 'retry_at': float(retry_at), 'retry_backoff_s': int(retry_delay_s), 'advanced': advanced}
            return {'job': refreshed, 'result': result}

        refreshed_release = gw.audit.get_release_bundle(promotion_id, tenant_id=item.get('tenant_id'), workspace_id=item.get('workspace_id'), environment=item.get('environment')) or release
        self._mark_baseline_promotion_wave_advance_state(gw, promotion_release=refreshed_release, source_wave_no=source_wave_no, actor=actor, status='failed', reason=error_text, next_wave_no=next_wave_no, job_id=str(item.get('job_id') or ''))
        refreshed = _finalize_job(enabled=False, next_run_at=None, run_count=int(item.get('run_count') or 0) + 1, last_error=error_text)
        result = {'ok': False, 'promotion_id': promotion_id, 'wave_no': source_wave_no, 'status': 'failed', 'error': error_text, 'advanced': advanced}
        return {'job': refreshed, 'result': result}

    def run_due_baseline_promotion_wave_advance_jobs(
        self,
        gw,
        *,
        actor: str,
        limit: int = 20,
        promotion_id: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        items = self._iter_all_job_schedules(
            gw,
            enabled=True,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            batch_size=max(limit, 50),
        )
        executed = []
        scanned = 0
        now_ts = time.time()
        for item in items:
            if not self._is_baseline_wave_advance_job(item, promotion_id=promotion_id):
                continue
            scanned += 1
            if not self.job_service._is_due(item, now=now_ts):
                continue
            executed.append(self._run_single_baseline_promotion_wave_advance_job(gw, item=item, actor=actor))
            if len(executed) >= limit:
                break
        return {'ok': True, 'items': executed, 'summary': {'count': len(executed), 'executed': len(executed), 'scanned': scanned, 'promotion_id': promotion_id}}



    def _schedule_baseline_promotion_simulation_custody_job(
        self,
        gw,
        *,
        promotion_release: dict[str, Any],
        actor: str,
        reason: str = '',
    ) -> dict[str, Any] | None:
        policy = self._baseline_promotion_simulation_custody_monitoring_policy_for_release(promotion_release)
        if not bool(policy.get('enabled')) or not bool(policy.get('auto_schedule')):
            return None
        scope = self._scope(
            tenant_id=promotion_release.get('tenant_id'),
            workspace_id=promotion_release.get('workspace_id'),
            environment=promotion_release.get('environment'),
        )
        promotion_id = str(promotion_release.get('release_id') or '').strip()
        interval_s = max(60, int(policy.get('interval_s') or 3600))
        definition = self._baseline_simulation_custody_job_definition(
            promotion_id=promotion_id,
            actor=actor,
            interval_s=interval_s,
            reason=reason or f'baseline promotion {promotion_id} simulation custody reconciliation',
        )
        existing = self._find_job_schedule(
            gw,
            predicate=lambda item: self._is_baseline_simulation_custody_job(item, promotion_id=promotion_id),
            enabled=None,
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
            batch_size=200,
        )
        next_run_at = time.time() + interval_s
        if existing is not None:
            gw.audit.update_job_schedule(
                str(existing.get('job_id') or ''),
                workflow_definition=definition,
                enabled=True,
                next_run_at=float(next_run_at),
                not_before=float(next_run_at),
                updated_at=time.time(),
                last_error='',
                schedule_kind='interval',
                interval_s=interval_s,
                tenant_id=scope.get('tenant_id'),
                workspace_id=scope.get('workspace_id'),
                environment=scope.get('environment'),
            )
            return self.job_service.get_job(gw, str(existing.get('job_id') or ''), tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'))
        return self.job_service.create_job(
            gw,
            name=self._baseline_simulation_custody_job_id(promotion_id),
            workflow_definition=definition,
            created_by=str(actor or 'system'),
            input_payload={'promotion_id': promotion_id},
            next_run_at=float(next_run_at),
            enabled=True,
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
            playbook_id=self._baseline_simulation_custody_job_id(promotion_id),
            schedule_kind='interval',
            interval_s=interval_s,
            not_before=float(next_run_at),
            max_runs=None,
        )

    def list_baseline_promotion_simulation_custody_jobs(
        self,
        gw,
        *,
        limit: int = 20,
        promotion_id: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        items = self._iter_all_job_schedules(gw, enabled=None, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment, batch_size=max(limit, 50))
        results = []
        due = 0
        now_ts = time.time()
        for item in items:
            if not self._is_baseline_simulation_custody_job(item, promotion_id=promotion_id):
                continue
            record = dict(item)
            if self.job_service._is_due(record, now=now_ts):
                due += 1
            results.append(record)
            if len(results) >= limit:
                break
        return {'ok': True, 'items': results, 'summary': {'count': len(results), 'due': due, 'promotion_id': promotion_id}}

    def _run_single_baseline_promotion_simulation_custody_job(self, gw, *, item: dict[str, Any], actor: str) -> dict[str, Any]:
        definition = dict(item.get('workflow_definition') or {})
        promotion_id = str(definition.get('promotion_id') or '').strip()
        result = self.reconcile_runtime_alert_governance_baseline_promotion_simulation_evidence_custody(
            gw,
            promotion_id=promotion_id,
            actor=actor,
            tenant_id=item.get('tenant_id'),
            workspace_id=item.get('workspace_id'),
            environment=item.get('environment'),
        )
        refreshed = self._complete_job_execution(
            gw,
            item=item,
            last_error='' if bool(result.get('ok')) else str(result.get('error') or 'simulation_custody_reconciliation_failed'),
            enabled=True,
        )
        return {
            'job': refreshed,
            'result': result,
            'reconciliation': dict(result.get('reconciliation') or {}),
            'custody_guard': dict(((result.get('custody_monitoring') or {}).get('guard')) or {}),
            'alerts': list(((result.get('custody_monitoring') or {}).get('alerts')) or []),
        }

    def run_due_baseline_promotion_simulation_custody_jobs(
        self,
        gw,
        *,
        actor: str,
        limit: int = 20,
        promotion_id: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        items = self._iter_all_job_schedules(
            gw,
            enabled=True,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            batch_size=max(limit, 50),
        )
        executed = []
        scanned = 0
        now_ts = time.time()
        for item in items:
            if not self._is_baseline_simulation_custody_job(item, promotion_id=promotion_id):
                continue
            scanned += 1
            if not self.job_service._is_due(item, now=now_ts):
                continue
            executed.append(self._run_single_baseline_promotion_simulation_custody_job(gw, item=item, actor=actor))
            if len(executed) >= limit:
                break
        return {'ok': True, 'items': executed, 'summary': {'count': len(executed), 'executed': len(executed), 'scanned': scanned, 'promotion_id': promotion_id}}
