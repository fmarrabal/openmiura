from __future__ import annotations

import time
from typing import Any


class OpenClawBaselineRolloutStateMixin:
    def _mark_baseline_promotion_wave_advance_state(
        self,
        gw,
        *,
        promotion_release: dict[str, Any],
        source_wave_no: int,
        actor: str,
        status: str,
        reason: str = '',
        next_wave_no: int | None = None,
        job_id: str | None = None,
    ) -> dict[str, Any]:
        refreshed_release = gw.audit.get_release_bundle(str(promotion_release.get('release_id') or ''), tenant_id=promotion_release.get('tenant_id'), workspace_id=promotion_release.get('workspace_id'), environment=promotion_release.get('environment')) or promotion_release
        metadata = dict(refreshed_release.get('metadata') or {})
        promotion = dict(metadata.get('baseline_promotion') or {})
        rollout_plan = self._refresh_baseline_promotion_rollout_plan(dict(promotion.get('rollout_plan') or {}))
        waves = [dict(item) for item in list(rollout_plan.get('items') or [])]
        for idx, wave in enumerate(waves):
            if int(wave.get('wave_no') or 0) != int(source_wave_no or 0):
                continue
            scheduled = dict(wave.get('scheduled_advance') or {})
            scheduled['status'] = str(status or '').strip() or 'unknown'
            scheduled['updated_at'] = time.time()
            scheduled['updated_by'] = str(actor or 'system')
            if reason:
                scheduled['reason'] = str(reason or '').strip()
            if next_wave_no is not None:
                scheduled['next_wave_no'] = int(next_wave_no or 0)
            if job_id is not None:
                scheduled['job_id'] = str(job_id or '')
            wave['scheduled_advance'] = scheduled
            waves[idx] = wave
            break
        rollout_plan['items'] = waves
        promotion['rollout_plan'] = self._refresh_baseline_promotion_rollout_plan(rollout_plan)
        promotion = self._append_baseline_promotion_timeline_event(
            promotion,
            kind='scheduler',
            label=f'baseline_promotion_wave_auto_advance_{str(status or "updated").strip() or "updated"}',
            actor=str(actor or 'system'),
            wave_no=int(source_wave_no or 0),
            next_wave_no=int(next_wave_no or 0) if next_wave_no is not None else None,
            reason=str(reason or '').strip() or None,
            job_id=str(job_id or '').strip() or None,
        )
        metadata['baseline_promotion'] = promotion
        updated = gw.audit.update_release_bundle(
            str(refreshed_release.get('release_id') or ''),
            metadata=metadata,
            tenant_id=refreshed_release.get('tenant_id'),
            workspace_id=refreshed_release.get('workspace_id'),
            environment=refreshed_release.get('environment'),
        ) or refreshed_release
        return updated

    def _set_baseline_promotion_status(
        self,
        gw,
        *,
        promotion_release: dict[str, Any],
        status: str,
    ) -> dict[str, Any]:
        refreshed_release = gw.audit.get_release_bundle(str(promotion_release.get('release_id') or ''), tenant_id=promotion_release.get('tenant_id'), workspace_id=promotion_release.get('workspace_id'), environment=promotion_release.get('environment')) or promotion_release
        metadata = dict(refreshed_release.get('metadata') or {})
        promotion = dict(metadata.get('baseline_promotion') or {})
        promotion['status'] = str(status or '').strip() or promotion.get('status')
        metadata['baseline_promotion'] = promotion
        return gw.audit.update_release_bundle(
            str(refreshed_release.get('release_id') or ''),
            status=str(status or '').strip() or refreshed_release.get('status'),
            metadata=metadata,
            tenant_id=refreshed_release.get('tenant_id'),
            workspace_id=refreshed_release.get('workspace_id'),
            environment=refreshed_release.get('environment'),
        ) or refreshed_release

    def _pause_baseline_promotion(
        self,
        gw,
        *,
        promotion_release: dict[str, Any],
        actor: str,
        reason: str = '',
    ) -> dict[str, Any]:
        release_status = str(promotion_release.get('status') or '')
        if release_status in {'completed', 'rolled_back', 'rejected'}:
            return {'ok': False, 'error': 'baseline_promotion_not_pausable', 'promotion_id': str(promotion_release.get('release_id') or ''), 'status': release_status}
        metadata = dict(promotion_release.get('metadata') or {})
        promotion = dict(metadata.get('baseline_promotion') or {})
        pause_state = dict(promotion.get('pause_state') or {})
        if bool(pause_state.get('paused', False)) or release_status == 'paused':
            return self._baseline_promotion_detail_view(gw, release=promotion_release)
        disabled = self._disable_baseline_promotion_wave_advance_jobs(
            gw,
            promotion_id=str(promotion_release.get('release_id') or ''),
            tenant_id=promotion_release.get('tenant_id'),
            workspace_id=promotion_release.get('workspace_id'),
            environment=promotion_release.get('environment'),
            reason='promotion_paused',
        )
        pause_record = {
            'paused': True,
            'paused_at': time.time(),
            'paused_by': str(actor or 'admin'),
            'reason': str(reason or '').strip(),
            'previous_status': release_status or str(promotion.get('status') or 'awaiting_advance_window'),
            'disabled_job_count': int(disabled.get('count') or 0),
        }
        history = [dict(item) for item in list(promotion.get('pause_history') or [])]
        history.append(dict(pause_record))
        promotion['pause_state'] = pause_record
        promotion['pause_history'] = history[-20:]
        promotion['status'] = 'paused'
        promotion = self._append_baseline_promotion_timeline_event(
            promotion,
            kind='promotion',
            label='baseline_promotion_paused',
            actor=str(actor or 'admin'),
            reason=str(reason or '').strip() or None,
            disabled_job_count=int(disabled.get('count') or 0),
            previous_status=release_status or None,
        )
        metadata['baseline_promotion'] = promotion
        updated_release = gw.audit.update_release_bundle(
            str(promotion_release.get('release_id') or ''),
            status='paused',
            metadata=metadata,
            tenant_id=promotion_release.get('tenant_id'),
            workspace_id=promotion_release.get('workspace_id'),
            environment=promotion_release.get('environment'),
        ) or promotion_release
        return self._baseline_promotion_detail_view(gw, release=updated_release)

    def _resume_baseline_promotion(
        self,
        gw,
        *,
        promotion_release: dict[str, Any],
        actor: str,
        reason: str = '',
    ) -> dict[str, Any]:
        metadata = dict(promotion_release.get('metadata') or {})
        promotion = dict(metadata.get('baseline_promotion') or {})
        pause_state = dict(promotion.get('pause_state') or {})
        if not bool(pause_state.get('paused', False)) and str(promotion_release.get('status') or '') != 'paused':
            return {'ok': False, 'error': 'baseline_promotion_not_paused', 'promotion_id': str(promotion_release.get('release_id') or '')}
        rollout_policy = self._normalize_baseline_catalog_rollout_policy(dict(((promotion.get('promotion_policy') or {}).get('rollout_policy') or {})))
        rollout_plan = self._refresh_baseline_promotion_rollout_plan(dict(promotion.get('rollout_plan') or {}))
        waves = [dict(item) for item in list(rollout_plan.get('items') or [])]
        source_wave = None
        next_planned_wave = None
        for wave in waves:
            if str(wave.get('status') or '') == 'planned' and next_planned_wave is None:
                next_planned_wave = wave
        if next_planned_wave is not None:
            prior_candidates = [wave for wave in waves if int(wave.get('wave_no') or 0) < int(next_planned_wave.get('wave_no') or 0) and str(wave.get('status') or '') in {'completed', 'applied'}]
            if prior_candidates:
                source_wave = sorted(prior_candidates, key=lambda item: int(item.get('wave_no') or 0))[-1]
        resume_status = str(pause_state.get('previous_status') or promotion.get('status') or 'awaiting_advance').strip() or 'awaiting_advance'
        if resume_status == 'paused':
            resume_status = 'awaiting_advance_window' if bool(rollout_policy.get('auto_advance', False)) else 'awaiting_advance'
        pause_state.update({
            'paused': False,
            'resumed_at': time.time(),
            'resumed_by': str(actor or 'admin'),
            'resume_reason': str(reason or '').strip(),
            'resumed_status': resume_status,
        })
        history = [dict(item) for item in list(promotion.get('pause_history') or [])]
        history.append({
            'paused': False,
            'resumed_at': float(pause_state.get('resumed_at') or time.time()),
            'resumed_by': str(actor or 'admin'),
            'reason': str(reason or '').strip(),
            'resumed_status': resume_status,
        })
        promotion['pause_state'] = pause_state
        promotion['pause_history'] = history[-20:]
        promotion['status'] = resume_status
        promotion = self._append_baseline_promotion_timeline_event(
            promotion,
            kind='promotion',
            label='baseline_promotion_resumed',
            actor=str(actor or 'admin'),
            reason=str(reason or '').strip() or None,
            resumed_status=resume_status,
        )
        metadata['baseline_promotion'] = promotion
        updated_release = gw.audit.update_release_bundle(
            str(promotion_release.get('release_id') or ''),
            status=resume_status,
            metadata=metadata,
            tenant_id=promotion_release.get('tenant_id'),
            workspace_id=promotion_release.get('workspace_id'),
            environment=promotion_release.get('environment'),
        ) or promotion_release
        if bool(rollout_policy.get('auto_advance', False)) and source_wave is not None and next_planned_wave is not None:
            scheduled = dict(source_wave.get('scheduled_advance') or {})
            requested_after = scheduled.get('advance_after') or scheduled.get('requested_advance_after') or time.time()
            requested_after = max(time.time(), float(requested_after))
            self._schedule_baseline_promotion_wave_advance_job(
                gw,
                promotion_release=updated_release,
                source_wave=source_wave,
                actor=actor,
                reason=reason or 'promotion resumed',
                requested_advance_after=float(requested_after),
            )
            updated_release = gw.audit.get_release_bundle(
                str(updated_release.get('release_id') or ''),
                tenant_id=updated_release.get('tenant_id'),
                workspace_id=updated_release.get('workspace_id'),
                environment=updated_release.get('environment'),
            ) or updated_release
        return self._baseline_promotion_detail_view(gw, release=updated_release)

