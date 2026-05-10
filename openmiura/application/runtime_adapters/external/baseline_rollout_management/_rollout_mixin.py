"""baseline_rollout_management._rollout_mixin"""
from __future__ import annotations

import time
import uuid
from typing import Any




OpenClawBaselineRolloutManagementMixin: type | None = None  # late-bound by __init__.py


class _OpenClawBaselineRolloutManagementMixinRolloutMixin:
    """Sub-mixin: rollout."""

    def _baseline_catalog_rollout_impact(
        self,
        gw,
        *,
        catalog_release: dict[str, Any],
        previous_baselines: dict[str, Any],
        candidate_baselines: dict[str, Any],
    ) -> dict[str, Any]:
        catalog_id = str(catalog_release.get('release_id') or '')
        releases = gw.audit.list_release_bundles(limit=500, kind='policy_portfolio', tenant_id=catalog_release.get('tenant_id'), workspace_id=catalog_release.get('workspace_id'))
        items: list[dict[str, Any]] = []
        env_counts: dict[str, int] = {}
        for release in releases:
            if not self._is_alert_governance_portfolio_release(release) or not self._portfolio_references_baseline_catalog(release, catalog_id=catalog_id):
                continue
            env_key = self._normalize_portfolio_environment_name(release.get('environment'))
            before = dict(previous_baselines.get(env_key) or {})
            after = dict(candidate_baselines.get(env_key) or {})
            diff = self._portfolio_policy_baseline_compare_view(baseline=before, effective=after)
            if not bool(diff.get('items')):
                continue
            item = {
                'portfolio_id': str(release.get('release_id') or ''),
                'name': str(release.get('name') or ''),
                'environment': env_key,
                'change_count': len(list(diff.get('items') or [])),
                'changes': list(diff.get('items') or []),
            }
            items.append(item)
            env_counts[env_key] = env_counts.get(env_key, 0) + 1
        return {
            'items': items,
            'summary': {
                'count': len(items),
                'environment_counts': env_counts,
                'portfolio_ids': [item.get('portfolio_id') for item in items],
            },
        }

    def _run_baseline_promotion_wave(
        self,
        gw,
        *,
        promotion_release: dict[str, Any],
        actor: str,
        reason: str = '',
        wave_no: int | None = None,
    ) -> dict[str, Any]:
        metadata = dict(promotion_release.get('metadata') or {})
        promotion = dict(metadata.get('baseline_promotion') or {})
        promotion_policy = self._normalize_baseline_catalog_promotion_policy(dict(promotion.get('promotion_policy') or {}))
        rollout_policy = self._normalize_baseline_catalog_rollout_policy(dict(promotion_policy.get('rollout_policy') or {}))
        gate_policy = self._normalize_baseline_catalog_gate_policy(dict(promotion_policy.get('gate_policy') or {}))
        rollback_policy = self._normalize_baseline_catalog_rollback_policy(dict(promotion_policy.get('rollback_policy') or {}))
        rollout_plan = self._refresh_baseline_promotion_rollout_plan(dict(promotion.get('rollout_plan') or {}))
        self._disable_baseline_promotion_wave_advance_jobs(gw, promotion_id=str(promotion_release.get('release_id') or ''), tenant_id=promotion_release.get('tenant_id'), workspace_id=promotion_release.get('workspace_id'), environment=promotion_release.get('environment'), reason='wave_execution_started')
        waves = [dict(item) for item in list(rollout_plan.get('items') or [])]
        target_wave = None
        if wave_no is None:
            for wave in waves:
                if str(wave.get('status') or 'planned') == 'planned':
                    target_wave = wave
                    break
        else:
            for wave in waves:
                if int(wave.get('wave_no') or 0) == int(wave_no):
                    target_wave = wave
                    break
        if target_wave is None:
            return {'ok': False, 'error': 'baseline_promotion_wave_not_found', 'promotion_id': str(promotion_release.get('release_id') or ''), 'wave_no': wave_no}
        if str(target_wave.get('status') or 'planned') != 'planned':
            return {'ok': False, 'error': 'baseline_promotion_wave_not_planned', 'promotion_id': str(promotion_release.get('release_id') or ''), 'wave_no': int(target_wave.get('wave_no') or 0), 'status': target_wave.get('status')}
        dependency_summary = dict(target_wave.get('dependency_summary') or {})
        required_wave_nos = [int(item) for item in list(dependency_summary.get('depends_on_wave_nos') or []) if int(item)]
        incomplete_dependencies = []
        for dep_wave_no in required_wave_nos:
            dep_wave = next((dict(item) for item in waves if int(item.get('wave_no') or 0) == dep_wave_no), None)
            if dep_wave is None or str(dep_wave.get('status') or '') != 'completed':
                incomplete_dependencies.append(dep_wave_no)
        if incomplete_dependencies:
            promotion = self._append_baseline_promotion_timeline_event(promotion, kind='wave', label='baseline_promotion_wave_dependency_blocked', actor=str(actor or 'admin'), wave_no=int(target_wave.get('wave_no') or 0), depends_on_wave_nos=incomplete_dependencies)
            promotion['status'] = 'awaiting_dependencies'
            metadata['baseline_promotion'] = promotion
            promotion_release = gw.audit.update_release_bundle(str(promotion_release.get('release_id') or ''), status='awaiting_dependencies', metadata=metadata, tenant_id=promotion_release.get('tenant_id'), workspace_id=promotion_release.get('workspace_id'), environment=promotion_release.get('environment')) or promotion_release
            return self._baseline_promotion_detail_view(gw, release=promotion_release)
        exclusive_groups = [str(item).strip() for item in list(dependency_summary.get('exclusive_with_groups') or []) if str(item).strip()]
        if exclusive_groups:
            exclusive_blocked_wave_nos: list[int] = []
            for wave in waves:
                other_wave_no = int(wave.get('wave_no') or 0)
                if other_wave_no == int(target_wave.get('wave_no') or 0):
                    continue
                if not set(exclusive_groups).intersection({str(item).strip() for item in list(wave.get('group_ids') or []) if str(item).strip()}):
                    continue
                if str(wave.get('status') or 'planned') not in {'completed', 'rolled_back'}:
                    exclusive_blocked_wave_nos.append(other_wave_no)
            if exclusive_blocked_wave_nos:
                promotion = self._append_baseline_promotion_timeline_event(promotion, kind='wave', label='baseline_promotion_wave_exclusivity_blocked', actor=str(actor or 'admin'), wave_no=int(target_wave.get('wave_no') or 0), blocked_by_wave_nos=sorted(set(exclusive_blocked_wave_nos)), exclusive_with_groups=exclusive_groups)
                promotion['status'] = 'awaiting_dependencies'
                target_wave['status'] = 'dependency_blocked'
                target_wave['dependency_summary'] = {**dependency_summary, 'exclusive_blocked_by_wave_nos': sorted(set(exclusive_blocked_wave_nos))}
                rollout_plan['items'] = waves
                promotion['rollout_plan'] = self._refresh_baseline_promotion_rollout_plan(rollout_plan)
                metadata['baseline_promotion'] = promotion
                promotion_release = gw.audit.update_release_bundle(str(promotion_release.get('release_id') or ''), status='awaiting_dependencies', metadata=metadata, tenant_id=promotion_release.get('tenant_id'), workspace_id=promotion_release.get('workspace_id'), environment=promotion_release.get('environment')) or promotion_release
                return self._baseline_promotion_detail_view(gw, release=promotion_release)
        for portfolio_id in self._baseline_promotion_unique_ids(list(target_wave.get('portfolio_ids') or [])):
            portfolio_release = gw.audit.get_release_bundle(str(portfolio_id or ''), tenant_id=promotion_release.get('tenant_id'), workspace_id=promotion_release.get('workspace_id'), environment=None)
            if portfolio_release is None or not self._is_alert_governance_portfolio_release(portfolio_release):
                continue
            self._set_portfolio_baseline_catalog_rollout_state(gw, portfolio_release=portfolio_release, promotion_release=promotion_release, actor=actor, status='candidate_active', active=True, wave_no=int(target_wave.get('wave_no') or 0), wave_id=str(target_wave.get('wave_id') or ''), reason=reason)
        target_wave['status'] = 'applied'
        target_wave['applied_at'] = time.time()
        target_wave['applied_by'] = str(actor or 'admin')
        existing_rollout_plan = dict(promotion.get('rollout_plan') or {})
        existing_rollout_plan['items'] = waves
        promotion['rollout_plan'] = self._refresh_baseline_promotion_rollout_plan(existing_rollout_plan)
        promotion['status'] = 'in_progress'
        promotion = self._append_baseline_promotion_timeline_event(promotion, kind='wave', label='baseline_promotion_wave_applied', actor=str(actor or 'admin'), wave_no=int(target_wave.get('wave_no') or 0), wave_id=str(target_wave.get('wave_id') or ''), portfolio_count=len(list(target_wave.get('portfolio_ids') or [])))
        metadata['baseline_promotion'] = promotion
        promotion_release = gw.audit.update_release_bundle(str(promotion_release.get('release_id') or ''), status='in_progress', metadata=metadata, tenant_id=promotion_release.get('tenant_id'), workspace_id=promotion_release.get('workspace_id'), environment=promotion_release.get('environment')) or promotion_release
        gate_evaluation = self._evaluate_baseline_promotion_wave_gate(gw, promotion_release=promotion_release, wave=target_wave, gate_policy=gate_policy)
        metadata = dict(promotion_release.get('metadata') or {})
        promotion = dict(metadata.get('baseline_promotion') or {})
        rollout_plan = self._refresh_baseline_promotion_rollout_plan(dict(promotion.get('rollout_plan') or {}))
        waves = [dict(item) for item in list(rollout_plan.get('items') or [])]
        for idx, wave in enumerate(waves):
            if int(wave.get('wave_no') or 0) == int(target_wave.get('wave_no') or 0):
                waves[idx]['gate_evaluation'] = gate_evaluation
                if bool(gate_evaluation.get('passed')):
                    waves[idx]['status'] = 'completed'
                    waves[idx]['completed_at'] = time.time()
                    waves[idx]['completed_by'] = str(actor or 'admin')
                else:
                    waves[idx]['status'] = 'gate_failed'
                    waves[idx]['gate_failed_at'] = time.time()
                    waves[idx]['gate_failed_by'] = str(actor or 'admin')
                target_wave = waves[idx]
                break
        existing_rollout_plan = dict(promotion.get('rollout_plan') or {})
        existing_rollout_plan['items'] = waves
        promotion['rollout_plan'] = self._refresh_baseline_promotion_rollout_plan(existing_rollout_plan)
        if bool(gate_evaluation.get('passed')):
            promotion = self._append_baseline_promotion_timeline_event(promotion, kind='gate', label='baseline_promotion_wave_gate_passed', actor=str(actor or 'admin'), wave_no=int(target_wave.get('wave_no') or 0), portfolio_count=len(list(target_wave.get('portfolio_ids') or [])))
            metadata['baseline_promotion'] = promotion
            promotion_release = gw.audit.update_release_bundle(str(promotion_release.get('release_id') or ''), status='in_progress', metadata=metadata, tenant_id=promotion_release.get('tenant_id'), workspace_id=promotion_release.get('workspace_id'), environment=promotion_release.get('environment')) or promotion_release
            has_remaining = any(str(item.get('status') or 'planned') == 'planned' for item in list((promotion.get('rollout_plan') or {}).get('items') or []))
            if not has_remaining:
                return self._complete_baseline_promotion(gw, promotion_release=promotion_release, actor=actor, reason=reason)
            promotion = dict((promotion_release.get('metadata') or {}).get('baseline_promotion') or {})
            auto_advance_enabled = bool(rollout_policy.get('auto_advance', False))
            if auto_advance_enabled:
                next_status = 'awaiting_advance_window'
            else:
                next_status = 'awaiting_advance' if bool(rollout_policy.get('require_manual_advance', True)) else 'in_progress'
            promotion['status'] = next_status
            metadata = dict(promotion_release.get('metadata') or {})
            metadata['baseline_promotion'] = promotion
            promotion_release = gw.audit.update_release_bundle(str(promotion_release.get('release_id') or ''), status=next_status, metadata=metadata, tenant_id=promotion_release.get('tenant_id'), workspace_id=promotion_release.get('workspace_id'), environment=promotion_release.get('environment')) or promotion_release
            scheduled_job = None
            if auto_advance_enabled:
                scheduled_job = self._schedule_baseline_promotion_wave_advance_job(gw, promotion_release=promotion_release, source_wave=target_wave, actor=actor, reason=reason or 'baseline wave passed and awaiting advance window')
                promotion_release = gw.audit.get_release_bundle(str(promotion_release.get('release_id') or ''), tenant_id=promotion_release.get('tenant_id'), workspace_id=promotion_release.get('workspace_id'), environment=promotion_release.get('environment')) or promotion_release
                detail = self._baseline_promotion_detail_view(gw, release=promotion_release)
                detail['scheduled_advance_job'] = scheduled_job
                return detail
            if not bool(rollout_policy.get('require_manual_advance', True)):
                return self._run_baseline_promotion_wave(gw, promotion_release=promotion_release, actor=actor, reason='auto-advance', wave_no=None)
            return self._baseline_promotion_detail_view(gw, release=promotion_release)
        promotion['status'] = 'gate_failed'
        promotion = self._append_baseline_promotion_timeline_event(promotion, kind='gate', label='baseline_promotion_wave_gate_failed', actor=str(actor or 'admin'), wave_no=int(target_wave.get('wave_no') or 0), reasons=list(gate_evaluation.get('reasons') or []), summary=dict(gate_evaluation.get('summary') or {}))
        metadata['baseline_promotion'] = promotion
        promotion_release = gw.audit.update_release_bundle(str(promotion_release.get('release_id') or ''), status='gate_failed', metadata=metadata, tenant_id=promotion_release.get('tenant_id'), workspace_id=promotion_release.get('workspace_id'), environment=promotion_release.get('environment')) or promotion_release
        self._disable_baseline_promotion_wave_advance_jobs(gw, promotion_id=str(promotion_release.get('release_id') or ''), tenant_id=promotion_release.get('tenant_id'), workspace_id=promotion_release.get('workspace_id'), environment=promotion_release.get('environment'), reason='gate_failed')
        if bool(rollback_policy.get('enabled', True)) and bool(rollback_policy.get('rollback_on_gate_failure', True)):
            return self._rollback_baseline_promotion(gw, promotion_release=promotion_release, actor=actor, reason=reason or 'gate failure rollback', trigger='gate_failure', wave_no=int(target_wave.get('wave_no') or 0))
        return self._baseline_promotion_detail_view(gw, release=promotion_release)

