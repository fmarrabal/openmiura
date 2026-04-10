from __future__ import annotations

import time
from typing import Any


class OpenClawAlertGovernanceBundleJobsMixin:
    def _schedule_bundle_wave_advance_job(
        self,
        gw,
        *,
        release: dict[str, Any],
        source_wave: dict[str, Any],
        actor: str,
        reason: str = '',
    ) -> dict[str, Any] | None:
        next_wave_no = int(source_wave.get('wave_no') or 0) + 1
        detail = self._alert_governance_bundle_detail_view(gw, release=release)
        bundle = dict(detail.get('bundle') or {})
        waves = [dict(item) for item in list(bundle.get('wave_plan') or [])]
        if next((wave for wave in waves if int(wave.get('wave_no') or 0) == next_wave_no), None) is None:
            return None
        observation = dict(source_wave.get('observation') or {})
        advance_after = observation.get('advance_after')
        if advance_after is None:
            return None
        scope = self._scope(tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=release.get('environment'))
        job_name = self._governance_wave_job_id(str(release.get('release_id') or ''), int(source_wave.get('wave_no') or 0))
        existing = self._find_job_schedule(
            gw,
            predicate=lambda item: self._is_governance_wave_advance_job(item, bundle_id=str(release.get('release_id') or '')) and str((item.get('workflow_definition') or {}).get('source_wave_no') or '') == str(int(source_wave.get('wave_no') or 0)),
            enabled=True,
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
            batch_size=200,
        )
        definition = self._governance_wave_advance_job_definition(bundle_id=str(release.get('release_id') or ''), source_wave_no=int(source_wave.get('wave_no') or 0), next_wave_no=next_wave_no, actor=actor, reason=reason or f'bundle {release.get("release_id")} wave {source_wave.get("wave_no")} observation complete')
        if existing is not None:
            gw.audit.update_job_schedule(str(existing.get('job_id') or ''), workflow_definition=definition, next_run_at=float(advance_after), updated_at=time.time(), last_error='', enabled=True, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'))
            return self.job_service.get_job(gw, str(existing.get('job_id') or ''), tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'))
        return self.job_service.create_job(
            gw,
            name=job_name,
            workflow_definition=definition,
            created_by=str(actor or 'system'),
            input_payload={'bundle_id': str(release.get('release_id') or ''), 'source_wave_no': int(source_wave.get('wave_no') or 0), 'next_wave_no': next_wave_no},
            next_run_at=float(advance_after),
            enabled=True,
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
            playbook_id=job_name,
            schedule_kind='once',
            not_before=float(advance_after),
            max_runs=1,
        )

    def _mark_bundle_wave_observation(
        self,
        gw,
        *,
        release: dict[str, Any],
        wave_no: int,
        actor: str,
        reason: str,
        gate_evaluation: dict[str, Any] | None = None,
        advance_status: str | None = None,
    ) -> dict[str, Any]:
        current_release = gw.audit.get_release_bundle(str(release.get('release_id') or ''), tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=release.get('environment')) or release
        metadata = dict(current_release.get('metadata') or {})
        bundle = dict(metadata.get('governance_bundle') or {})
        waves = [dict(item) for item in list(bundle.get('wave_plan') or [])]
        now_ts = time.time()
        updated_wave = None
        for idx, wave in enumerate(waves):
            if int(wave.get('wave_no') or 0) != int(wave_no or 0):
                continue
            wave = dict(wave)
            observation = dict(wave.get('observation') or {})
            if advance_status is not None:
                observation['status'] = str(advance_status or '').strip()
            else:
                observation['status'] = 'completed'
            observation['observed_at'] = now_ts
            observation['observed_by'] = str(actor or 'system')
            observation['reason'] = str(reason or '').strip()
            wave['observation'] = observation
            if gate_evaluation is not None:
                wave['gate_evaluation'] = dict(gate_evaluation or {})
            waves[idx] = wave
            updated_wave = wave
            break
        bundle['wave_plan'] = waves
        metadata['governance_bundle'] = bundle
        gw.audit.update_release_bundle(str(release.get('release_id') or ''), metadata=metadata, tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=release.get('environment'))
        return updated_wave or {}

    def _run_single_governance_wave_advance_job(
        self,
        gw,
        *,
        item: dict[str, Any],
        actor: str,
    ) -> dict[str, Any]:
        if not self._is_governance_wave_advance_job(item):
            raise ValueError('job is not a governance wave-advance job')
        if not self.job_service._is_due(item, now=time.time()):
            raise ValueError('job is not due')
        definition = dict(item.get('workflow_definition') or {})
        bundle_id = str(definition.get('bundle_id') or '').strip()
        source_wave_no = int(definition.get('source_wave_no') or 0)
        next_wave_no = int(definition.get('next_wave_no') or 0) if definition.get('next_wave_no') else None
        detail = self.get_runtime_alert_governance_bundle(gw, bundle_id=bundle_id, tenant_id=item.get('tenant_id'), workspace_id=item.get('workspace_id'), environment=item.get('environment'))
        if not detail.get('ok'):
            raise LookupError(detail.get('error') or 'bundle_not_found')
        release = dict(detail.get('release') or {})
        bundle = dict(detail.get('bundle') or {})
        if bool((bundle.get('halt_state') or {}).get('active')):
            result = {'ok': False, 'error': 'bundle_halted'}
            last_error = 'bundle_halted'
        else:
            source_wave = next((dict(w) for w in list(bundle.get('wave_plan') or []) if int(w.get('wave_no') or 0) == source_wave_no), None)
            if source_wave is None:
                raise LookupError('source_wave_not_found')
            gate_evaluation = self._evaluate_bundle_wave_gates(gw, release=release, bundle=bundle, wave=source_wave, results=list(source_wave.get('last_results') or []), limit=200)
            promotion_slo_evaluation = self._evaluate_bundle_wave_promotion_slo(bundle=bundle, wave=source_wave, results=list(source_wave.get('last_results') or []), gate_evaluation=gate_evaluation)
            rollback_summary = {'count': 0, 'items': [], 'error_count': 0}
            should_rollback = bool(gate_evaluation.get('should_rollback')) or bool(promotion_slo_evaluation.get('should_rollback'))
            should_halt = bool(gate_evaluation.get('should_halt')) or bool(promotion_slo_evaluation.get('should_halt'))
            if should_rollback:
                rollback_summary = self._rollback_bundle_wave_results(gw, release=release, results=list(source_wave.get('last_results') or []), actor=str(actor or 'system'), reason=f'bundle {bundle_id} wave {source_wave_no} automatic rollback after bake window')
                gate_evaluation['rollback'] = rollback_summary
                promotion_slo_evaluation['rollback'] = rollback_summary
            if should_halt:
                metadata = dict(release.get('metadata') or {})
                stored_bundle = dict(metadata.get('governance_bundle') or {})
                failure_reasons = list(gate_evaluation.get('failures') or []) + list(promotion_slo_evaluation.get('failures') or [])
                trigger = 'post_wave_bake_gate_failure' if gate_evaluation.get('status') == 'failed' else 'post_wave_bake_promotion_slo_failure'
                stored_bundle['halt_state'] = {
                    'active': True,
                    'halted_at': time.time(),
                    'halted_wave_no': source_wave_no,
                    'reason': '; '.join(str(x.get('reason') or '') for x in failure_reasons)[:500],
                    'rollback_executed': bool(rollback_summary.get('count')),
                    'rollback': rollback_summary,
                    'trigger': trigger,
                }
                metadata['governance_bundle'] = stored_bundle
                gw.audit.update_release_bundle(bundle_id, metadata=metadata, tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=release.get('environment'))
                self._mark_bundle_wave_observation(gw, release=release, wave_no=source_wave_no, actor=actor, reason='post_wave_gate_failed' if gate_evaluation.get('status') == 'failed' else 'post_wave_promotion_slo_failed', gate_evaluation=gate_evaluation, advance_status='failed')
                result = {'ok': True, 'bundle_id': bundle_id, 'wave_no': source_wave_no, 'status': 'halted', 'gate_evaluation': gate_evaluation, 'promotion_slo_evaluation': promotion_slo_evaluation, 'rollback': rollback_summary}
                last_error = ''
            else:
                self._mark_bundle_wave_observation(gw, release=release, wave_no=source_wave_no, actor=actor, reason='post_wave_gate_passed', gate_evaluation=gate_evaluation, advance_status='ready')
                # persist latest slo observation on the wave
                metadata = dict(release.get('metadata') or {})
                stored_bundle = dict(metadata.get('governance_bundle') or {})
                stored_waves = [dict(w) for w in list(stored_bundle.get('wave_plan') or [])]
                for idx, wave_item in enumerate(stored_waves):
                    if int(wave_item.get('wave_no') or 0) == int(source_wave_no or 0):
                        updated = dict(wave_item)
                        updated['promotion_slo_evaluation'] = promotion_slo_evaluation
                        stored_waves[idx] = updated
                        break
                stored_bundle['wave_plan'] = stored_waves
                metadata['governance_bundle'] = stored_bundle
                gw.audit.update_release_bundle(bundle_id, metadata=metadata, tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=release.get('environment'))
                advanced = None
                if next_wave_no:
                    advanced = self.run_runtime_alert_governance_bundle_wave(gw, bundle_id=bundle_id, wave_no=next_wave_no, actor=actor, reason=f'auto-advanced after wave {source_wave_no} bake window', tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=release.get('environment'), limit=200)
                    self._mark_bundle_wave_observation(gw, release=release, wave_no=source_wave_no, actor=actor, reason='auto_advanced', advance_status='advanced')
                result = {'ok': True, 'bundle_id': bundle_id, 'wave_no': source_wave_no, 'status': 'advanced' if advanced and advanced.get('ok') else 'ready', 'gate_evaluation': gate_evaluation, 'promotion_slo_evaluation': promotion_slo_evaluation, 'advanced': advanced}
                last_error = '' if result.get('ok') else str(result.get('error') or '')
        refreshed = self._complete_job_execution(gw, item=item, last_error=last_error)
        return {'job': refreshed, 'result': result}

    def list_governance_wave_advance_jobs(
        self,
        gw,
        *,
        limit: int = 100,
        bundle_id: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        payload = self._list_jobs_by_family(
            gw,
            matcher=lambda item: self._is_governance_wave_advance_job(item, bundle_id=bundle_id),
            limit=limit,
            enabled=None,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            batch_size=max(limit, 50),
        )
        return {'ok': True, 'items': payload['items'], 'summary': {**payload['summary'], 'bundle_id': bundle_id}}

    def run_due_governance_wave_advance_jobs(
        self,
        gw,
        *,
        actor: str,
        limit: int = 20,
        bundle_id: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        payload = self._run_due_jobs_by_family(
            gw,
            matcher=lambda item: self._is_governance_wave_advance_job(item, bundle_id=bundle_id),
            runner=self._run_single_governance_wave_advance_job,
            actor=actor,
            limit=limit,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            batch_size=max(limit, 50),
        )
        return {'ok': True, 'items': payload['items'], 'summary': {**payload['summary'], 'bundle_id': bundle_id}}
