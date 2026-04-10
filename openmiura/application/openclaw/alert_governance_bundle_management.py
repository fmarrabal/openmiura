from __future__ import annotations

import math
import time
from typing import Any


class OpenClawAlertGovernanceBundleManagementMixin:
    @staticmethod
    def _is_alert_governance_bundle_release(release: dict[str, Any] | None) -> bool:
        record = dict(release or {})
        if str(record.get('kind') or '').strip() != 'policy_bundle':
            return False
        metadata = dict(record.get('metadata') or {})
        bundle = dict(metadata.get('governance_bundle') or {})
        return str(bundle.get('kind') or '').strip() == 'openclaw_alert_governance'

    @staticmethod
    def _default_progressive_exposure_policy() -> dict[str, Any]:
        return {
            'enabled': False,
            'steps': [10, 25, 50, 100],
            'canary_count': 1,
            'min_wave_size': 1,
            'max_wave_size': None,
            'max_parallel_ratio': 1.0,
            'label_prefix': 'Exposure',
            'auto_advance': False,
            'apply_only_when_waves_missing': True,
        }

    @classmethod
    def _normalize_progressive_exposure_policy(cls, policy: dict[str, Any] | None, *, total_runtimes: int) -> dict[str, Any]:
        normalized = cls._default_progressive_exposure_policy()
        normalized.update(dict(policy or {}))
        normalized['enabled'] = bool(normalized.get('enabled', False))
        steps_raw = list(normalized.get('steps') or [100])
        steps: list[int] = []
        for item in steps_raw:
            try:
                value = int(item)
            except Exception:
                continue
            value = max(1, min(100, value))
            if value not in steps:
                steps.append(value)
        if 100 not in steps:
            steps.append(100)
        steps.sort()
        normalized['steps'] = steps
        try:
            normalized['canary_count'] = max(1, min(max(1, total_runtimes), int(normalized.get('canary_count') or 1)))
        except Exception:
            normalized['canary_count'] = 1 if total_runtimes > 0 else 0
        try:
            normalized['min_wave_size'] = max(1, int(normalized.get('min_wave_size') or 1))
        except Exception:
            normalized['min_wave_size'] = 1
        max_wave_size = normalized.get('max_wave_size')
        try:
            normalized['max_wave_size'] = max(1, int(max_wave_size)) if max_wave_size is not None else None
        except Exception:
            normalized['max_wave_size'] = None
        try:
            normalized['max_parallel_ratio'] = max(0.05, min(1.0, float(normalized.get('max_parallel_ratio') or 1.0)))
        except Exception:
            normalized['max_parallel_ratio'] = 1.0
        normalized['label_prefix'] = str(normalized.get('label_prefix') or 'Exposure').strip() or 'Exposure'
        normalized['auto_advance'] = bool(normalized.get('auto_advance', False))
        normalized['apply_only_when_waves_missing'] = bool(normalized.get('apply_only_when_waves_missing', True))
        return normalized

    @classmethod
    def _progressive_waves_from_policy(cls, *, runtime_ids: list[str], policy: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        target_ids = [str(item or '').strip() for item in list(runtime_ids or []) if str(item or '').strip()]
        if not target_ids:
            return []
        normalized = cls._normalize_progressive_exposure_policy(policy, total_runtimes=len(target_ids))
        if not normalized.get('enabled'):
            return []
        total = len(target_ids)
        canary_count = min(total, int(normalized.get('canary_count') or 1))
        min_wave_size = int(normalized.get('min_wave_size') or 1)
        max_wave_size = normalized.get('max_wave_size')
        max_parallel_ratio = float(normalized.get('max_parallel_ratio') or 1.0)
        auto_advance = bool(normalized.get('auto_advance', False))
        label_prefix = str(normalized.get('label_prefix') or 'Exposure').strip() or 'Exposure'
        waves: list[dict[str, Any]] = []
        exposed = 0
        if canary_count > 0:
            canary_ids = target_ids[:canary_count]
            exposed = len(canary_ids)
            waves.append({
                'wave_id': 'wave-1',
                'wave_no': 1,
                'label': 'Canary',
                'runtime_ids': canary_ids,
                'max_parallel': max(1, min(len(canary_ids), math.ceil(len(canary_ids) * max_parallel_ratio))),
                'halt_on_error': True,
                'canary': True,
                'gate_policy': {},
                'health_window_s': None,
                'bake_time_s': None,
                'auto_advance': auto_advance,
                'auto_advance_delay_s': None,
                'planned_exposure_ratio': round(exposed / total, 4),
                'planned_target_count': exposed,
                'exposure_step_percent': round((exposed / total) * 100, 2),
                'started_at': None,
                'completed_at': None,
                'run_count': 0,
                'last_run_at': None,
            })
        wave_no = len(waves)
        for pct in list(normalized.get('steps') or [100]):
            target_count = max(exposed, min(total, max(min_wave_size, math.ceil(total * (int(pct) / 100.0)))))
            if target_count <= exposed:
                continue
            chunk = target_ids[exposed:target_count]
            if max_wave_size is not None and len(chunk) > int(max_wave_size):
                while chunk:
                    take = chunk[: int(max_wave_size)]
                    chunk = chunk[int(max_wave_size):]
                    wave_no += 1
                    cumulative = exposed + len(take)
                    waves.append({
                        'wave_id': f'wave-{wave_no}',
                        'wave_no': wave_no,
                        'label': f'{label_prefix} {round((cumulative / total) * 100, 1)}%',
                        'runtime_ids': take,
                        'max_parallel': max(1, min(len(take), math.ceil(len(take) * max_parallel_ratio))),
                        'halt_on_error': True,
                        'canary': False,
                        'gate_policy': {},
                        'health_window_s': None,
                        'bake_time_s': None,
                        'auto_advance': auto_advance,
                        'auto_advance_delay_s': None,
                        'planned_exposure_ratio': round(cumulative / total, 4),
                        'planned_target_count': cumulative,
                        'exposure_step_percent': round((cumulative / total) * 100, 2),
                        'started_at': None,
                        'completed_at': None,
                        'run_count': 0,
                        'last_run_at': None,
                    })
                    exposed = cumulative
            else:
                wave_no += 1
                exposed = target_count
                waves.append({
                    'wave_id': f'wave-{wave_no}',
                    'wave_no': wave_no,
                    'label': f'{label_prefix} {pct}%',
                    'runtime_ids': chunk,
                    'max_parallel': max(1, min(len(chunk), math.ceil(len(chunk) * max_parallel_ratio))),
                    'halt_on_error': True,
                    'canary': False,
                    'gate_policy': {},
                    'health_window_s': None,
                    'bake_time_s': None,
                    'auto_advance': auto_advance,
                    'auto_advance_delay_s': None,
                    'planned_exposure_ratio': round(exposed / total, 4),
                    'planned_target_count': exposed,
                    'exposure_step_percent': round((exposed / total) * 100, 2),
                    'started_at': None,
                    'completed_at': None,
                    'run_count': 0,
                    'last_run_at': None,
                })
        return waves

    @classmethod
    def _normalize_alert_governance_bundle_waves(
        cls,
        *,
        runtime_ids: list[str],
        waves: list[dict[str, Any]] | list[list[str]] | None = None,
        wave_size: int | None = None,
        progressive_exposure_policy: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        target_ids = [str(item or '').strip() for item in runtime_ids if str(item or '').strip()]
        if not target_ids:
            return []
        normalized: list[dict[str, Any]] = []
        progressive_policy = cls._normalize_progressive_exposure_policy(progressive_exposure_policy, total_runtimes=len(target_ids))
        if waves:
            for idx, raw in enumerate(list(waves or []), start=1):
                entry = dict(raw) if isinstance(raw, dict) else {'runtime_ids': list(raw or [])}
                wave_ids = []
                for rid in list(entry.get('runtime_ids') or []):
                    rid_text = str(rid or '').strip()
                    if rid_text and rid_text in target_ids and rid_text not in wave_ids:
                        wave_ids.append(rid_text)
                if not wave_ids:
                    continue
                normalized.append({
                    'wave_id': str(entry.get('wave_id') or f'wave-{idx}').strip() or f'wave-{idx}',
                    'wave_no': idx,
                    'label': str(entry.get('label') or f'Wave {idx}').strip() or f'Wave {idx}',
                    'runtime_ids': wave_ids,
                    'max_parallel': max(1, int(entry.get('max_parallel') or len(wave_ids) or 1)),
                    'halt_on_error': bool(entry.get('halt_on_error', True)),
                    'canary': bool(entry.get('canary', False)),
                    'gate_policy': dict(entry.get('gate_policy') or {}),
                    'promotion_slo_policy': dict(entry.get('promotion_slo_policy') or {}),
                    'health_window_s': int(entry.get('health_window_s') or 0) if entry.get('health_window_s') is not None else None,
                    'bake_time_s': int(entry.get('bake_time_s') or 0) if entry.get('bake_time_s') is not None else None,
                    'auto_advance': bool(entry.get('auto_advance')) if entry.get('auto_advance') is not None else None,
                    'auto_advance_delay_s': int(entry.get('auto_advance_delay_s') or 0) if entry.get('auto_advance_delay_s') is not None else None,
                    'planned_exposure_ratio': entry.get('planned_exposure_ratio'),
                    'planned_target_count': entry.get('planned_target_count'),
                    'exposure_step_percent': entry.get('exposure_step_percent'),
                    'started_at': None,
                    'completed_at': None,
                    'run_count': 0,
                    'last_run_at': None,
                })
        elif progressive_policy.get('enabled'):
            normalized = cls._progressive_waves_from_policy(runtime_ids=target_ids, policy=progressive_policy)
        else:
            size = max(1, int(wave_size or len(target_ids) or 1))
            for idx, start in enumerate(range(0, len(target_ids), size), start=1):
                chunk = target_ids[start:start + size]
                normalized.append({
                    'wave_id': f'wave-{idx}',
                    'wave_no': idx,
                    'label': f'Wave {idx}',
                    'runtime_ids': chunk,
                    'max_parallel': max(1, len(chunk)),
                    'halt_on_error': True,
                    'canary': False,
                    'gate_policy': {},
                    'promotion_slo_policy': {},
                    'health_window_s': None,
                    'bake_time_s': None,
                    'auto_advance': None,
                    'auto_advance_delay_s': None,
                    'planned_exposure_ratio': round((start + len(chunk)) / len(target_ids), 4),
                    'planned_target_count': start + len(chunk),
                    'exposure_step_percent': round(((start + len(chunk)) / len(target_ids)) * 100, 2),
                    'started_at': None,
                    'completed_at': None,
                    'run_count': 0,
                    'last_run_at': None,
                })
        seen: set[str] = set()
        final: list[dict[str, Any]] = []
        total = len(target_ids)
        for idx, wave in enumerate(normalized, start=1):
            ids = []
            for rid in list(wave.get('runtime_ids') or []):
                rid_text = str(rid or '').strip()
                if rid_text and rid_text not in seen:
                    ids.append(rid_text)
                    seen.add(rid_text)
            if not ids:
                continue
            wave = dict(wave)
            wave['wave_no'] = idx
            wave['wave_id'] = str(wave.get('wave_id') or f'wave-{idx}').strip() or f'wave-{idx}'
            wave['label'] = str(wave.get('label') or f'Wave {idx}').strip() or f'Wave {idx}'
            wave['runtime_ids'] = ids
            wave['canary'] = bool(wave.get('canary', False))
            wave['gate_policy'] = dict(wave.get('gate_policy') or {})
            wave['promotion_slo_policy'] = dict(wave.get('promotion_slo_policy') or {})
            wave['health_window_s'] = int(wave.get('health_window_s') or 0) if wave.get('health_window_s') is not None else None
            wave['bake_time_s'] = int(wave.get('bake_time_s') or 0) if wave.get('bake_time_s') is not None else None
            wave['auto_advance'] = bool(wave.get('auto_advance')) if wave.get('auto_advance') is not None else None
            wave['auto_advance_delay_s'] = int(wave.get('auto_advance_delay_s') or 0) if wave.get('auto_advance_delay_s') is not None else None
            cumulative = len(seen)
            try:
                wave['planned_target_count'] = int(wave.get('planned_target_count') or cumulative)
            except Exception:
                wave['planned_target_count'] = cumulative
            try:
                planned_ratio = wave.get('planned_exposure_ratio')
                wave['planned_exposure_ratio'] = round(float(planned_ratio), 4) if planned_ratio is not None else round(cumulative / total, 4)
            except Exception:
                wave['planned_exposure_ratio'] = round(cumulative / total, 4)
            try:
                wave['exposure_step_percent'] = round(float(wave.get('exposure_step_percent') or (wave['planned_exposure_ratio'] * 100)), 2)
            except Exception:
                wave['exposure_step_percent'] = round(wave['planned_exposure_ratio'] * 100, 2)
            final.append(wave)
        missing = [rid for rid in target_ids if rid not in seen]
        if missing:
            idx = len(final) + 1
            cumulative = len(seen) + len(missing)
            final.append({
                'wave_id': f'wave-{idx}',
                'wave_no': idx,
                'label': f'Wave {idx}',
                'runtime_ids': missing,
                'max_parallel': max(1, len(missing)),
                'halt_on_error': True,
                'canary': False,
                'gate_policy': {},
                'promotion_slo_policy': {},
                'health_window_s': None,
                'bake_time_s': None,
                'auto_advance': None,
                'auto_advance_delay_s': None,
                'planned_exposure_ratio': round(cumulative / total, 4),
                'planned_target_count': cumulative,
                'exposure_step_percent': round((cumulative / total) * 100, 2),
                'started_at': None,
                'completed_at': None,
                'run_count': 0,
                'last_run_at': None,
            })
        return final

    def _alert_governance_bundle_detail_view(
        self,
        gw,
        *,
        release: dict[str, Any],
    ) -> dict[str, Any]:
        metadata = dict(release.get('metadata') or {})
        bundle = dict(metadata.get('governance_bundle') or {})
        scope = self._scope(
            tenant_id=release.get('tenant_id'),
            workspace_id=release.get('workspace_id'),
            environment=release.get('environment'),
        )
        items = gw.audit.list_release_bundle_items(str(release.get('release_id') or ''))
        target_ids = [str(item.get('item_key') or '').strip() for item in items if str(item.get('item_kind') or '').strip() == 'openclaw_runtime']
        wave_plan = [dict(item) for item in list(bundle.get('wave_plan') or [])]
        halt_state = dict(bundle.get('halt_state') or {})
        runtime_states: dict[str, dict[str, Any]] = {}
        runtime_details: list[dict[str, Any]] = []
        for rid in target_ids:
            state = self._runtime_bundle_state(
                gw,
                runtime_id=rid,
                bundle_id=str(release.get('release_id') or ''),
                tenant_id=scope.get('tenant_id'),
                workspace_id=scope.get('workspace_id'),
                environment=scope.get('environment'),
            )
            runtime_states[rid] = state
            detail = self.openclaw_adapter_service.get_runtime(
                gw,
                runtime_id=rid,
                tenant_id=scope.get('tenant_id'),
                workspace_id=scope.get('workspace_id'),
                environment=scope.get('environment'),
            )
            runtime_details.append({
                'runtime_id': rid,
                'runtime_name': ((detail.get('runtime') or {}).get('name')) if detail.get('ok') else rid,
                'status': state.get('status'),
                'version_id': state.get('version_id'),
                'version_no': state.get('version_no'),
                'approval': state.get('approval'),
                'release': state.get('release'),
                'wave_id': next((str(w.get('wave_id') or '') for w in wave_plan if rid in list(w.get('runtime_ids') or [])), ''),
                'wave_no': next((int(w.get('wave_no') or 0) for w in wave_plan if rid in list(w.get('runtime_ids') or [])), 0),
            })
        status_counts: dict[str, int] = {}
        for item in runtime_details:
            key = str(item.get('status') or 'not_started')
            status_counts[key] = status_counts.get(key, 0) + 1
        enriched_waves: list[dict[str, Any]] = []
        completed_waves = 0
        canary_wave_count = 0
        gate_failed_wave_count = 0
        rollback_wave_count = 0
        slo_failed_wave_count = 0
        for wave in wave_plan:
            ids = [str(rid or '').strip() for rid in list(wave.get('runtime_ids') or []) if str(rid or '').strip()]
            per_runtime = [dict(runtime_states.get(rid) or {'runtime_id': rid, 'status': 'not_started'}) for rid in ids]
            counts: dict[str, int] = {}
            for state in per_runtime:
                key = str(state.get('status') or 'not_started')
                counts[key] = counts.get(key, 0) + 1
            gate_evaluation = dict(wave.get('gate_evaluation') or {})
            promotion_slo_evaluation = dict(wave.get('promotion_slo_evaluation') or {})
            gate_status = str(gate_evaluation.get('status') or '').strip()
            slo_status = str(promotion_slo_evaluation.get('status') or '').strip()
            rollback = dict(gate_evaluation.get('rollback') or {})
            observation = dict(wave.get('observation') or {})
            observation_status = str(observation.get('status') or '').strip()
            wave_status = 'pending'
            if gate_status == 'failed':
                wave_status = 'gate_failed'
                gate_failed_wave_count += 1
            if slo_status == 'failed' and wave_status not in {'gate_failed', 'canary_failed'}:
                wave_status = 'slo_failed'
                slo_failed_wave_count += 1
            elif ids and counts.get('active', 0) == len(ids):
                wave_status = 'completed'
                completed_waves += 1
            elif counts.get('pending_approval', 0) > 0:
                wave_status = 'awaiting_runtime_approvals'
            elif any(counts.get(key, 0) > 0 for key in ('failed', 'error', 'rejected')):
                wave_status = 'blocked'
            elif any(counts.get(key, 0) > 0 for key in ('active', 'pending_approval')):
                wave_status = 'in_progress'
            if observation_status == 'pending' and wave_status in {'completed', 'canary_passed'}:
                wave_status = 'baking'
            elif observation_status == 'ready' and wave_status in {'completed', 'canary_passed'}:
                wave_status = 'ready_for_advance'
            elif observation_status == 'advanced':
                wave_status = 'advanced'
            if bool(wave.get('canary')):
                canary_wave_count += 1
                if gate_status == 'passed' and wave_status in {'completed', 'ready_for_advance', 'baking', 'advanced'}:
                    wave_status = 'canary_passed' if wave_status == 'completed' else wave_status
                elif gate_status == 'failed':
                    wave_status = 'canary_failed'
            if bool(rollback.get('count')):
                rollback_wave_count += 1
            enriched_waves.append({
                **wave,
                'status': wave_status,
                'runtime_status_counts': counts,
                'runtimes': per_runtime,
                'gate_evaluation': gate_evaluation,
                'promotion_slo_evaluation': promotion_slo_evaluation,
                'observation': observation,
            })
        rollout_status = 'draft'
        if bool(halt_state.get('active')):
            rollout_status = 'halted'
        elif str(release.get('status') or '') == 'candidate':
            rollout_status = 'candidate'
        elif str(release.get('status') or '') in {'approved', 'promoted'}:
            if status_counts.get('pending_approval', 0) > 0:
                rollout_status = 'awaiting_runtime_approvals'
            elif status_counts.get('active', 0) == len(runtime_details) and runtime_details:
                rollout_status = 'completed'
            elif gate_failed_wave_count > 0 or slo_failed_wave_count > 0:
                rollout_status = 'blocked'
            elif any(status_counts.get(key, 0) > 0 for key in ('failed', 'error', 'rejected')):
                rollout_status = 'blocked'
            elif any(status_counts.get(key, 0) > 0 for key in ('active', 'pending_approval')):
                rollout_status = 'in_progress'
            else:
                rollout_status = 'approved'
        next_wave_no = None
        if not bool(halt_state.get('active')):
            for wave in enriched_waves:
                if str(wave.get('status') or '') in {'pending', 'blocked'}:
                    next_wave_no = int(wave.get('wave_no') or 0)
                    break
        pending_observation_count = sum(1 for wave in enriched_waves if str((wave.get('observation') or {}).get('status') or '') == 'pending')
        ready_for_advance_count = sum(1 for wave in enriched_waves if str((wave.get('observation') or {}).get('status') or '') == 'ready')
        gate_status_counts: dict[str, int] = {}
        for wave in enriched_waves:
            key = str((wave.get('gate_evaluation') or {}).get('status') or 'not_evaluated')
            gate_status_counts[key] = gate_status_counts.get(key, 0) + 1
        slo_status_counts: dict[str, int] = {}
        for wave in enriched_waves:
            key = str((wave.get('promotion_slo_evaluation') or {}).get('status') or 'not_evaluated')
            slo_status_counts[key] = slo_status_counts.get(key, 0) + 1
        summary = {
            'target_count': len(runtime_details),
            'wave_count': len(enriched_waves),
            'completed_wave_count': completed_waves,
            'canary_wave_count': canary_wave_count,
            'gate_failed_wave_count': gate_failed_wave_count,
            'slo_failed_wave_count': slo_failed_wave_count,
            'rollback_wave_count': rollback_wave_count,
            'active_runtime_count': int(status_counts.get('active', 0) or 0),
            'pending_runtime_approval_count': int(status_counts.get('pending_approval', 0) or 0),
            'status_counts': status_counts,
            'gate_status_counts': gate_status_counts,
            'slo_status_counts': slo_status_counts,
            'rollout_status': rollout_status,
            'next_wave_no': next_wave_no,
            'pending_observation_count': pending_observation_count,
            'ready_for_advance_count': ready_for_advance_count,
            'halted': bool(halt_state.get('active')),
            'halted_wave_no': halt_state.get('halted_wave_no'),
            'halt_reason': halt_state.get('reason'),
            'rollback_executed': bool(halt_state.get('rollback_executed')),
            'changed_keys': list((bundle.get('simulation_summary') or {}).get('changed_keys') or []),
            'affected_count': int((bundle.get('simulation_summary') or {}).get('affected_count') or 0),
        }
        analytics = self._bundle_rollout_analytics(bundle=bundle, runtime_details=runtime_details, enriched_waves=enriched_waves, summary=summary)
        return {
            'ok': True,
            'bundle_id': str(release.get('release_id') or ''),
            'release': dict(release),
            'bundle': {
                **bundle,
                'wave_plan': enriched_waves,
                'wave_gates': dict(bundle.get('wave_gates') or {}),
                'wave_timing_policy': dict(bundle.get('wave_timing_policy') or {}),
                'promotion_slo_policy': dict(bundle.get('promotion_slo_policy') or {}),
                'progressive_exposure_policy': dict(bundle.get('progressive_exposure_policy') or {}),
                'halt_state': halt_state,
                'created_from': dict(bundle.get('created_from') or {}),
            },
            'targets': runtime_details,
            'summary': summary,
            'analytics': analytics,
            'scope': scope,
        }

    def create_runtime_alert_governance_bundle(
        self,
        gw,
        *,
        name: str,
        version: str,
        runtime_ids: list[str],
        actor: str,
        candidate_policy: dict[str, Any] | None = None,
        merge_with_current: bool = True,
        waves: list[dict[str, Any]] | list[list[str]] | None = None,
        wave_size: int | None = None,
        wave_gates: dict[str, Any] | None = None,
        wave_timing_policy: dict[str, Any] | None = None,
        promotion_slo_policy: dict[str, Any] | None = None,
        progressive_exposure_policy: dict[str, Any] | None = None,
        reason: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        normalized_ids: list[str] = []
        for item in list(runtime_ids or []):
            rid = str(item or '').strip()
            if rid and rid not in normalized_ids:
                normalized_ids.append(rid)
        if not normalized_ids:
            return {'ok': False, 'error': 'runtime_ids_required'}
        runtime_items: list[dict[str, Any]] = []
        base_scope: dict[str, Any] | None = None
        affected_total = 0
        changed_keys: set[str] = set()
        for rid in normalized_ids:
            detail = self.openclaw_adapter_service.get_runtime(gw, runtime_id=rid, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
            if not detail.get('ok'):
                return {**detail, 'runtime_id': rid}
            runtime = dict(detail.get('runtime') or {})
            runtime_scope = self._scope(
                tenant_id=runtime.get('tenant_id'),
                workspace_id=runtime.get('workspace_id'),
                environment=runtime.get('environment'),
            )
            if base_scope is None:
                base_scope = runtime_scope
            elif runtime_scope != base_scope:
                return {'ok': False, 'error': 'mixed_runtime_scope_not_supported', 'runtime_id': rid, 'expected_scope': base_scope, 'runtime_scope': runtime_scope}
            simulation = self.simulate_runtime_alert_governance(
                gw,
                runtime_id=rid,
                candidate_policy=candidate_policy,
                merge_with_current=merge_with_current,
                tenant_id=runtime_scope.get('tenant_id'),
                workspace_id=runtime_scope.get('workspace_id'),
                environment=runtime_scope.get('environment'),
                limit=limit,
            )
            if not simulation.get('ok'):
                return {**simulation, 'runtime_id': rid}
            changed_keys.update(list((simulation.get('policy_diff') or {}).get('changed_keys') or []))
            affected_total += int((simulation.get('summary') or {}).get('affected_count') or 0)
            runtime_items.append({
                'runtime_id': rid,
                'runtime_name': str(runtime.get('name') or rid),
                'summary': dict(simulation.get('summary') or {}),
                'policy_diff': dict(simulation.get('policy_diff') or {}),
            })
        scope = base_scope or self._scope(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        wave_plan = self._normalize_alert_governance_bundle_waves(runtime_ids=normalized_ids, waves=waves, wave_size=wave_size, progressive_exposure_policy=progressive_exposure_policy)
        default_gates = self._default_bundle_wave_gate_policy()
        normalized_wave_gates = self._effective_bundle_wave_gate_policy(bundle={'wave_gates': dict(wave_gates or {})}, wave={})
        default_timing = self._default_bundle_wave_timing_policy()
        normalized_wave_timing = self._effective_bundle_wave_timing_policy(bundle={'wave_timing_policy': dict(wave_timing_policy or {})}, wave={})
        default_promotion_slo = self._default_promotion_slo_policy()
        normalized_promotion_slo = self._effective_promotion_slo_policy(bundle={'promotion_slo_policy': dict(promotion_slo_policy or {})}, wave={})
        normalized_progressive_exposure = self._normalize_progressive_exposure_policy(progressive_exposure_policy, total_runtimes=len(normalized_ids))
        release = gw.audit.create_release_bundle(
            kind='policy_bundle',
            name=str(name or 'openclaw-alert-governance').strip() or 'openclaw-alert-governance',
            version=str(version or f'bundle-{int(time.time())}').strip() or f'bundle-{int(time.time())}',
            created_by=str(actor or 'admin'),
            items=[{'item_kind': 'openclaw_runtime', 'item_key': item['runtime_id'], 'item_version': '', 'payload': item} for item in runtime_items],
            environment=scope.get('environment'),
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            notes=str(reason or '').strip(),
            metadata={
                'governance_bundle': {
                    'kind': 'openclaw_alert_governance',
                    'policy_kind': 'alert_governance',
                    'candidate_policy': dict(candidate_policy or {}),
                    'merge_with_current': bool(merge_with_current),
                    'wave_plan': wave_plan,
                    'wave_gates': normalized_wave_gates,
                    'default_wave_gates': default_gates,
                    'wave_timing_policy': normalized_wave_timing,
                    'default_wave_timing_policy': default_timing,
                    'promotion_slo_policy': normalized_promotion_slo,
                    'default_promotion_slo_policy': default_promotion_slo,
                    'progressive_exposure_policy': normalized_progressive_exposure,
                    'simulation_summary': {
                        'affected_count': affected_total,
                        'changed_keys': sorted(changed_keys),
                    },
                    'created_from': {'reason': str(reason or '').strip(), 'actor': str(actor or 'admin')},
                    'halt_state': {
                        'active': False,
                        'halted_at': None,
                        'halted_wave_no': None,
                        'reason': '',
                        'rollback_executed': False,
                    },
                },
            },
            status='draft',
        )
        return self._alert_governance_bundle_detail_view(gw, release=release)

    def list_runtime_alert_governance_bundles(
        self,
        gw,
        *,
        limit: int = 50,
        status: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        runtime_id: str | None = None,
    ) -> dict[str, Any]:
        releases = gw.audit.list_release_bundles(
            limit=max(limit * 5, limit),
            kind='policy_bundle',
            status=status,
            environment=environment,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )
        items = []
        for release in releases:
            if not self._is_alert_governance_bundle_release(release):
                continue
            detail = self._alert_governance_bundle_detail_view(gw, release=release)
            if runtime_id is not None:
                targets = list(detail.get('targets') or [])
                if not any(str(item.get('runtime_id') or '').strip() == str(runtime_id or '').strip() for item in targets):
                    continue
            items.append({
                'bundle_id': detail.get('bundle_id'),
                'release': detail.get('release'),
                'summary': detail.get('summary'),
                'analytics': detail.get('analytics'),
                'bundle': detail.get('bundle'),
            })
            if len(items) >= limit:
                break
        return {
            'ok': True,
            'items': items,
            'summary': {
                'count': len(items),
                'status': status,
                'runtime_id': runtime_id,
            },
            'scope': self._scope(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment),
        }

    def get_runtime_alert_governance_bundle(
        self,
        gw,
        *,
        bundle_id: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        release = gw.audit.get_release_bundle(bundle_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if release is None or not self._is_alert_governance_bundle_release(release):
            return {'ok': False, 'error': 'governance_bundle_not_found', 'bundle_id': str(bundle_id or '').strip()}
        return self._alert_governance_bundle_detail_view(gw, release=release)

    def get_runtime_alert_governance_bundle_analytics(
        self,
        gw,
        *,
        bundle_id: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        detail = self.get_runtime_alert_governance_bundle(gw, bundle_id=bundle_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if not detail.get('ok'):
            return detail
        return {
            'ok': True,
            'bundle_id': detail.get('bundle_id'),
            'summary': detail.get('summary'),
            'analytics': detail.get('analytics'),
            'bundle': detail.get('bundle'),
            'scope': detail.get('scope'),
        }

    def submit_runtime_alert_governance_bundle(
        self,
        gw,
        *,
        bundle_id: str,
        actor: str,
        reason: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        release = gw.audit.submit_release_bundle(bundle_id, actor=str(actor or 'admin'), reason=str(reason or '').strip(), tenant_id=tenant_id, workspace_id=workspace_id)
        metadata = dict(release.get('metadata') or {})
        bundle = dict(metadata.get('governance_bundle') or {})
        bundle['submitted_by'] = str(actor or 'admin')
        bundle['submitted_reason'] = str(reason or '').strip()
        metadata['governance_bundle'] = bundle
        gw.audit.update_release_bundle(bundle_id, status=release.get('status'), notes=release.get('notes'), metadata=metadata, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        release = gw.audit.get_release_bundle(bundle_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment) or release
        return self._alert_governance_bundle_detail_view(gw, release=release)

    def approve_runtime_alert_governance_bundle(
        self,
        gw,
        *,
        bundle_id: str,
        actor: str,
        reason: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        release = gw.audit.approve_release_bundle(bundle_id, actor=str(actor or 'admin'), reason=str(reason or '').strip(), tenant_id=tenant_id, workspace_id=workspace_id)
        metadata = dict(release.get('metadata') or {})
        bundle = dict(metadata.get('governance_bundle') or {})
        bundle['approved_by'] = str(actor or 'admin')
        bundle['approved_reason'] = str(reason or '').strip()
        metadata['governance_bundle'] = bundle
        gw.audit.update_release_bundle(bundle_id, status=release.get('status'), notes=release.get('notes'), metadata=metadata, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        release = gw.audit.get_release_bundle(bundle_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment) or release
        return self._alert_governance_bundle_detail_view(gw, release=release)

    def run_runtime_alert_governance_bundle_wave(
        self,
        gw,
        *,
        bundle_id: str,
        wave_no: int,
        actor: str,
        reason: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        detail = self.get_runtime_alert_governance_bundle(gw, bundle_id=bundle_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if not detail.get('ok'):
            return detail
        release = dict(detail.get('release') or {})
        if str(release.get('status') or '') not in {'approved', 'promoted'}:
            return {'ok': False, 'error': 'bundle_not_approved', 'bundle_id': bundle_id, 'release_status': release.get('status')}
        bundle = dict(detail.get('bundle') or {})
        halt_state = dict(bundle.get('halt_state') or {})
        if bool(halt_state.get('active')):
            return {'ok': False, 'error': 'bundle_halted', 'bundle_id': bundle_id, 'halt_state': halt_state}
        candidate_policy = dict(bundle.get('candidate_policy') or {})
        merge_with_current = bool(bundle.get('merge_with_current', True))
        waves = [dict(item) for item in list(bundle.get('wave_plan') or [])]
        target_wave = next((item for item in waves if int(item.get('wave_no') or 0) == int(wave_no or 0)), None)
        if target_wave is None:
            return {'ok': False, 'error': 'bundle_wave_not_found', 'bundle_id': bundle_id, 'wave_no': int(wave_no or 0)}
        for prev in waves:
            prev_no = int(prev.get('wave_no') or 0)
            if prev_no >= int(wave_no or 0):
                break
            prev_status = str(prev.get('status') or '').strip()
            prev_gate = dict(prev.get('gate_evaluation') or {})
            if bool(prev.get('canary')) and str(prev_gate.get('status') or '') not in {'passed', 'warning'}:
                return {'ok': False, 'error': 'bundle_wave_blocked_by_canary', 'bundle_id': bundle_id, 'wave_no': int(wave_no or 0), 'blocked_by_wave_no': prev_no, 'blocked_by_status': prev_status, 'gate_status': prev_gate.get('status')}
            if prev_status in {'gate_failed', 'canary_failed', 'halted', 'blocked'}:
                return {'ok': False, 'error': 'bundle_wave_blocked_by_prior_wave', 'bundle_id': bundle_id, 'wave_no': int(wave_no or 0), 'blocked_by_wave_no': prev_no, 'blocked_by_status': prev_status}
        results: list[dict[str, Any]] = []
        errors = 0
        pending_approvals = 0
        max_parallel = max(1, int(target_wave.get('max_parallel') or len(list(target_wave.get('runtime_ids') or [])) or 1))
        runtime_ids = list(target_wave.get('runtime_ids') or [])[:max_parallel]
        for rid in runtime_ids:
            activation = self.activate_runtime_alert_governance(
                gw,
                runtime_id=str(rid or '').strip(),
                actor=str(actor or 'admin'),
                candidate_policy=candidate_policy,
                merge_with_current=merge_with_current,
                reason=str(reason or f'bundle {bundle_id} wave {wave_no}').strip(),
                tenant_id=release.get('tenant_id'),
                workspace_id=release.get('workspace_id'),
                environment=release.get('environment'),
                limit=limit,
                release_bundle_id=bundle_id,
                release_wave_id=str(target_wave.get('wave_id') or ''),
                release_wave_no=int(target_wave.get('wave_no') or 0),
                release_wave_label=str(target_wave.get('label') or ''),
            )
            result_item = {
                'runtime_id': rid,
                'ok': bool(activation.get('ok')),
                'status': str(((activation.get('version') or {}).get('status')) or ('error' if not activation.get('ok') else 'active')),
                'version_id': ((activation.get('version') or {}).get('version_id')),
                'approval_required': bool(activation.get('approval_required')),
                'approval_id': ((activation.get('approval') or {}).get('approval_id')),
                'error': activation.get('error'),
            }
            if result_item['status'] == 'pending_approval':
                pending_approvals += 1
            if not result_item['ok']:
                errors += 1
            results.append(result_item)
            if not result_item['ok'] and bool(target_wave.get('halt_on_error', True)):
                break
        gate_evaluation = self._evaluate_bundle_wave_gates(
            gw,
            release=release,
            bundle=bundle,
            wave=target_wave,
            results=results,
            limit=limit,
        )
        promotion_slo_evaluation = self._evaluate_bundle_wave_promotion_slo(
            bundle=bundle,
            wave=target_wave,
            results=results,
            gate_evaluation=gate_evaluation,
        )
        rollback_summary = {'count': 0, 'items': [], 'error_count': 0}
        should_rollback = bool(gate_evaluation.get('should_rollback')) or bool(promotion_slo_evaluation.get('should_rollback'))
        if should_rollback:
            rollback_summary = self._rollback_bundle_wave_results(
                gw,
                release=release,
                results=results,
                actor=str(actor or 'admin'),
                reason=str(reason or f'bundle {bundle_id} wave {wave_no} automatic rollback').strip(),
            )
            gate_evaluation['rollback'] = rollback_summary
            promotion_slo_evaluation['rollback'] = rollback_summary
        metadata = dict(release.get('metadata') or {})
        stored_bundle = dict(metadata.get('governance_bundle') or {})
        stored_waves = [dict(item) for item in list(stored_bundle.get('wave_plan') or [])]
        now_value = time.time()
        for idx, wave in enumerate(stored_waves):
            if int(wave.get('wave_no') or 0) == int(wave_no or 0):
                updated = dict(wave)
                updated['started_at'] = updated.get('started_at') or now_value
                updated['completed_at'] = now_value
                updated['run_count'] = int(updated.get('run_count') or 0) + 1
                updated['last_run_at'] = now_value
                updated['last_results'] = results
                updated['gate_evaluation'] = gate_evaluation
                updated['promotion_slo_evaluation'] = promotion_slo_evaluation
                timing_policy = self._effective_bundle_wave_timing_policy(bundle=stored_bundle, wave=updated)
                if gate_evaluation.get('status') in {'passed', 'warning'} and pending_approvals == 0:
                    observe_for = int(timing_policy.get('health_window_s') or 0)
                    bake_for = int(timing_policy.get('bake_time_s') or 0)
                    auto_delay = int(timing_policy.get('auto_advance_delay_s') or 0)
                    if observe_for > 0 or bake_for > 0 or auto_delay > 0 or bool(timing_policy.get('auto_advance')):
                        observe_until = now_value + observe_for
                        advance_after = observe_until + bake_for + auto_delay
                        updated['observation'] = {
                            'status': 'pending',
                            'started_at': now_value,
                            'health_window_s': observe_for,
                            'bake_time_s': bake_for,
                            'auto_advance_delay_s': auto_delay,
                            'observe_until': observe_until,
                            'advance_after': advance_after,
                            'auto_advance': bool(timing_policy.get('auto_advance')),
                        }
                stored_waves[idx] = updated
                break
        stored_bundle['wave_plan'] = stored_waves
        stored_bundle['last_wave_run'] = {
            'wave_no': int(wave_no or 0),
            'wave_id': str(target_wave.get('wave_id') or ''),
            'actor': str(actor or 'admin'),
            'reason': str(reason or '').strip(),
            'results': results,
            'errors': errors,
            'pending_approvals': pending_approvals,
            'gate_evaluation': gate_evaluation,
        }
        should_halt = bool(gate_evaluation.get('should_halt')) or bool(promotion_slo_evaluation.get('should_halt'))
        if should_halt:
            failure_reasons = list(gate_evaluation.get('failures') or []) + list(promotion_slo_evaluation.get('failures') or [])
            stored_bundle['halt_state'] = {
                'active': True,
                'halted_at': now_value,
                'halted_wave_no': int(wave_no or 0),
                'reason': '; '.join(str(item.get('reason') or '') for item in failure_reasons)[:500],
                'rollback_executed': bool(rollback_summary.get('count')),
                'rollback': rollback_summary,
                'trigger': 'wave_gate_failure' if gate_evaluation.get('status') == 'failed' else 'wave_promotion_slo_failure',
            }
        metadata['governance_bundle'] = stored_bundle
        gw.audit.update_release_bundle(bundle_id, metadata=metadata, tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=release.get('environment'))
        updated_release = gw.audit.get_release_bundle(bundle_id, tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=release.get('environment')) or release
        updated_bundle = dict((updated_release.get('metadata') or {}).get('governance_bundle') or {})
        source_wave_for_job = next((dict(w) for w in list(updated_bundle.get('wave_plan') or []) if int(w.get('wave_no') or 0) == int(wave_no or 0)), None)
        scheduled_advance_job = None
        if source_wave_for_job is not None and bool((dict(source_wave_for_job.get('observation') or {})).get('auto_advance')) and not should_halt and pending_approvals == 0:
            scheduled_advance_job = self._schedule_bundle_wave_advance_job(gw, release=updated_release, source_wave=source_wave_for_job, actor=str(actor or 'admin'), reason=str(reason or f'bundle {bundle_id} wave {wave_no} post-wave bake advance').strip())
        gw.audit.log_event('system', 'broker', str(actor or 'admin'), 'system', {
            'action': 'openclaw_alert_governance_bundle_wave_run',
            'bundle_id': bundle_id,
            'wave_no': int(wave_no or 0),
            'runtime_count': len(results),
            'errors': errors,
            'pending_approvals': pending_approvals,
            'gate_status': gate_evaluation.get('status'),
            'promotion_slo_status': promotion_slo_evaluation.get('status'),
            'halted': bool(should_halt),
            'rollback_count': int(rollback_summary.get('count') or 0),
        }, tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=release.get('environment'))
        detail = self._alert_governance_bundle_detail_view(gw, release=updated_release)
        detail['wave_execution'] = {
            'wave_no': int(wave_no or 0),
            'wave_id': str(target_wave.get('wave_id') or ''),
            'results': results,
            'errors': errors,
            'pending_approvals': pending_approvals,
            'gate_evaluation': gate_evaluation,
            'promotion_slo_evaluation': promotion_slo_evaluation,
            'rollback': rollback_summary,
            'scheduled_advance_job': scheduled_advance_job,
        }
        return detail
