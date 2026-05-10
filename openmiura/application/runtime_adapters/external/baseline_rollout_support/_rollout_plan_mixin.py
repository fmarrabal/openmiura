"""baseline_rollout_support._rollout_plan_mixin

Sub-mixin extracted from
``openmiura.application.runtime_adapters.external.baseline_rollout_support``
so that no individual file in the package exceeds 1,500 lines. The
public class ``OpenClawBaselineRolloutSupportMixin`` continues to
inherit from this sub-mixin.

The module-level ``OpenClawBaselineRolloutSupportMixin = None`` sentinel
is rebound by ``baseline_rollout_support/__init__.py`` so that the few
``@staticmethod`` call sites that reference the class by name resolve
correctly at call time.
"""

from __future__ import annotations

import copy
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any


OpenClawBaselineRolloutSupportMixin: type | None = None  # late-bound by __init__.py


class _OpenClawBaselineRolloutSupportRolloutPlanMixin:
    """Sub-mixin: rollout plan methods on OpenClawBaselineRolloutSupportMixin."""

    def _refresh_baseline_promotion_rollout_plan(self, rollout_plan: dict[str, Any] | None) -> dict[str, Any]:
        plan = dict(rollout_plan or {})
        items = [dict(item) for item in list(plan.get('items') or [])]
        status_counts: dict[str, int] = {}
        applied_portfolio_ids: list[str] = []
        rolled_back_portfolio_ids: list[str] = []
        pending_portfolio_ids: list[str] = []
        completed_wave_count = 0
        current_wave_no = 0
        gate_failed_wave_no = None
        group_ids: list[str] = []
        dependency_edge_count = 0
        dependency_blocked_wave_count = 0
        for wave in items:
            status = str(wave.get('status') or 'planned').strip() or 'planned'
            status_counts[status] = status_counts.get(status, 0) + 1
            portfolio_ids = self._baseline_promotion_unique_ids(list(wave.get('portfolio_ids') or []))
            group_ids.extend([str(item).strip() for item in list(wave.get('group_ids') or []) if str(item).strip()])
            dep_summary = dict(wave.get('dependency_summary') or {})
            dependency_edge_count += len(list(dep_summary.get('depends_on_group_ids') or [])) + len(list(dep_summary.get('depends_on_wave_nos') or []))
            if str(status) in {'dependency_blocked'}:
                dependency_blocked_wave_count += 1
            if status in {'applied', 'completed', 'gate_failed', 'rolled_back'}:
                applied_portfolio_ids.extend(portfolio_ids)
                current_wave_no = max(current_wave_no, int(wave.get('wave_no') or 0))
            if status == 'completed':
                completed_wave_count += 1
            if status == 'rolled_back':
                rolled_back_portfolio_ids.extend(portfolio_ids)
            if status == 'planned':
                pending_portfolio_ids.extend(portfolio_ids)
            if status == 'gate_failed' and gate_failed_wave_no is None:
                gate_failed_wave_no = int(wave.get('wave_no') or 0)
        applied_portfolio_ids = self._baseline_promotion_unique_ids(applied_portfolio_ids)
        rolled_back_portfolio_ids = self._baseline_promotion_unique_ids(rolled_back_portfolio_ids)
        pending_portfolio_ids = self._baseline_promotion_unique_ids(pending_portfolio_ids)
        group_summary = dict(plan.get('group_summary') or {})
        validation = dict(plan.get('validation') or {})
        plan['items'] = items
        plan['wave_count'] = len(items)
        plan['current_wave_no'] = current_wave_no
        plan['completed_wave_count'] = completed_wave_count
        plan['applied_portfolio_ids'] = applied_portfolio_ids
        plan['rolled_back_portfolio_ids'] = rolled_back_portfolio_ids
        plan['pending_portfolio_ids'] = pending_portfolio_ids
        plan['group_summary'] = {
            **group_summary,
            'group_count': int(group_summary.get('group_count') or len(self._baseline_promotion_unique_ids(group_ids))),
            'group_ids': self._baseline_promotion_unique_ids(list(group_summary.get('group_ids') or group_ids)),
            'dependency_edge_count': int(group_summary.get('dependency_edge_count') or dependency_edge_count),
            'dependency_cycle_detected': bool(group_summary.get('dependency_cycle_detected', False)),
            'cyclic_group_ids': self._baseline_promotion_unique_ids(list(group_summary.get('cyclic_group_ids') or [])),
            'exclusive_conflict_count': int(group_summary.get('exclusive_conflict_count') or 0),
        }
        validation_errors = [dict(item) for item in list(validation.get('errors') or [])]
        validation_status = str(validation.get('status') or ('failed' if validation_errors else 'passed')).strip() or ('failed' if validation_errors else 'passed')
        plan['validation'] = {
            **validation,
            'status': validation_status,
            'valid': validation_status == 'passed',
            'errors': validation_errors,
        }
        plan['summary'] = {
            'wave_count': len(items),
            'completed_wave_count': completed_wave_count,
            'current_wave_no': current_wave_no,
            'applied_count': len(applied_portfolio_ids),
            'rolled_back_count': len(rolled_back_portfolio_ids),
            'pending_count': len(pending_portfolio_ids),
            'status_counts': status_counts,
            'gate_failed': gate_failed_wave_no is not None,
            'gate_failed_wave_no': gate_failed_wave_no,
            'group_count': int((plan.get('group_summary') or {}).get('group_count') or 0),
            'dependency_edge_count': int((plan.get('group_summary') or {}).get('dependency_edge_count') or 0),
            'dependency_blocked_wave_count': dependency_blocked_wave_count,
            'dependency_cycle_detected': bool((plan.get('group_summary') or {}).get('dependency_cycle_detected', False)),
            'exclusive_conflict_count': int((plan.get('group_summary') or {}).get('exclusive_conflict_count') or 0),
            'validation_status': validation_status,
            'validation_failed': validation_status != 'passed',
            'validation_error_count': len(validation_errors),
        }
        return plan

    def _build_baseline_promotion_rollout_plan(self, *, promotion_id: str, impact: dict[str, Any], rollout_policy: dict[str, Any]) -> dict[str, Any]:
        impact_items = [dict(item) for item in list((impact or {}).get('items') or [])]
        impact_items.sort(key=lambda item: (str(item.get('environment') or ''), str(item.get('name') or ''), str(item.get('portfolio_id') or '')))
        items_by_portfolio = {str(item.get('portfolio_id') or ''): item for item in impact_items if str(item.get('portfolio_id') or '').strip()}
        ordered_ids = self._baseline_promotion_unique_ids([str(item.get('portfolio_id') or '') for item in impact_items])
        waves: list[dict[str, Any]] = []
        used: set[str] = set()
        explicit_waves = [dict(item) for item in list((rollout_policy or {}).get('waves') or [])]
        if explicit_waves:
            for wave in explicit_waves:
                portfolio_ids = [portfolio_id for portfolio_id in self._baseline_promotion_unique_ids(list(wave.get('portfolio_ids') or [])) if portfolio_id in items_by_portfolio and portfolio_id not in used]
                if not portfolio_ids:
                    continue
                used.update(portfolio_ids)
                wave_no = len(waves) + 1
                waves.append({
                    'wave_id': f'wave-{wave_no}-{uuid.uuid4().hex[:8]}',
                    'wave_no': wave_no,
                    'wave_label': str(wave.get('wave_label') or f'wave-{wave_no}').strip() or f'wave-{wave_no}',
                    'portfolio_ids': portfolio_ids,
                    'group_ids': [],
                    'group_labels': [],
                    'items': [dict(items_by_portfolio[portfolio_id]) for portfolio_id in portfolio_ids],
                    'status': 'planned',
                    'gate_evaluation': {},
                    'dependency_summary': {'depends_on_group_ids': [], 'depends_on_wave_nos': [], 'dependency_portfolio_ids': [], 'cycle_detected': False},
                })
            remaining_ids = [portfolio_id for portfolio_id in ordered_ids if portfolio_id not in used]
            wave_size = int((rollout_policy or {}).get('wave_size') or 0)
            if wave_size <= 0:
                wave_size = len(remaining_ids) or len(ordered_ids) or 1
            for index in range(0, len(remaining_ids), wave_size):
                portfolio_ids = remaining_ids[index:index + wave_size]
                if not portfolio_ids:
                    continue
                wave_no = len(waves) + 1
                waves.append({
                    'wave_id': f'wave-{wave_no}-{uuid.uuid4().hex[:8]}',
                    'wave_no': wave_no,
                    'wave_label': f'wave-{wave_no}',
                    'portfolio_ids': portfolio_ids,
                    'group_ids': [],
                    'group_labels': [],
                    'items': [dict(items_by_portfolio[portfolio_id]) for portfolio_id in portfolio_ids if portfolio_id in items_by_portfolio],
                    'status': 'planned',
                    'gate_evaluation': {},
                    'dependency_summary': {'depends_on_group_ids': [], 'depends_on_wave_nos': [], 'dependency_portfolio_ids': [], 'cycle_detected': False},
                })
            plan = {
                'promotion_id': str(promotion_id or '').strip(),
                'enabled': bool((rollout_policy or {}).get('enabled', False)) and bool(waves),
                'items': waves,
                'group_summary': {'group_count': 0, 'group_ids': [], 'dependency_edge_count': 0, 'dependency_cycle_detected': False, 'cyclic_group_ids': []},
            }
            return self._refresh_baseline_promotion_rollout_plan(plan)

        dependency_graph = self._normalize_portfolio_dependency_graph((rollout_policy or {}).get('dependency_graph') or {})
        explicit_groups = self._normalize_baseline_rollout_group_specs((rollout_policy or {}).get('portfolio_groups') or [])
        if explicit_groups or dependency_graph:
            group_specs = [dict(item) for item in explicit_groups]
            portfolio_to_group: dict[str, str] = {}
            for spec in group_specs:
                valid_ids = [pid for pid in self._baseline_promotion_unique_ids(list(spec.get('portfolio_ids') or [])) if pid in items_by_portfolio and pid not in portfolio_to_group]
                spec['portfolio_ids'] = valid_ids
                for pid in valid_ids:
                    portfolio_to_group[pid] = str(spec.get('group_id') or '')
            synthetic_idx = 0
            for portfolio_id in ordered_ids:
                if portfolio_id in portfolio_to_group or portfolio_id not in items_by_portfolio:
                    continue
                synthetic_idx += 1
                group_id = f'portfolio-{synthetic_idx}' if dependency_graph else 'ungrouped'
                if not dependency_graph:
                    existing = next((item for item in group_specs if str(item.get('group_id') or '') == group_id), None)
                    if existing is not None:
                        existing['portfolio_ids'] = self._baseline_promotion_unique_ids(list(existing.get('portfolio_ids') or []) + [portfolio_id])
                        portfolio_to_group[portfolio_id] = group_id
                        continue
                spec = {'group_id': group_id, 'group_label': group_id, 'portfolio_ids': [portfolio_id], 'depends_on_groups': [], 'exclusive_with_groups': [], 'wave_size': 0, 'metadata': {'synthetic': True}}
                group_specs.append(spec)
                portfolio_to_group[portfolio_id] = group_id
            if dependency_graph:
                for portfolio_id, dep_ids in dependency_graph.items():
                    group_id = portfolio_to_group.get(portfolio_id)
                    if not group_id:
                        continue
                    spec = next((item for item in group_specs if str(item.get('group_id') or '') == group_id), None)
                    if spec is None:
                        continue
                    existing_dep_groups = list(spec.get('depends_on_groups') or [])
                    for dep_id in dep_ids:
                        dep_group_id = portfolio_to_group.get(dep_id)
                        if dep_group_id and dep_group_id != group_id:
                            existing_dep_groups.append(dep_group_id)
                    spec['depends_on_groups'] = self._baseline_promotion_unique_ids(existing_dep_groups)
            group_specs = [spec for spec in group_specs if list(spec.get('portfolio_ids') or [])]
            ordered_groups_state = self._topological_sort_baseline_group_specs(group_specs)
            ordered_groups = [dict(item) for item in list(ordered_groups_state.get('items') or [])]
            group_ids_set = {str(item.get('group_id') or '') for item in ordered_groups}
            validation_errors: list[dict[str, Any]] = []
            if bool(ordered_groups_state.get('cycle_detected')):
                validation_errors.append({
                    'code': 'dependency_cycle_detected',
                    'reason': 'baseline rollout group dependency graph contains a cycle',
                    'cyclic_group_ids': [str(item) for item in list(ordered_groups_state.get('cyclic_group_ids') or [])],
                })
            exclusive_conflict_count = 0
            for spec in ordered_groups:
                group_id = str(spec.get('group_id') or '')
                missing_dependencies = [dep for dep in list(spec.get('depends_on_groups') or []) if dep not in group_ids_set]
                if missing_dependencies:
                    validation_errors.append({
                        'code': 'unknown_dependency_group',
                        'reason': 'baseline rollout group depends on an unknown group',
                        'group_id': group_id,
                        'unknown_group_ids': self._baseline_promotion_unique_ids(missing_dependencies),
                    })
                exclusive_groups = [dep for dep in list(spec.get('exclusive_with_groups') or []) if dep]
                missing_exclusive = [dep for dep in exclusive_groups if dep not in group_ids_set]
                if missing_exclusive:
                    validation_errors.append({
                        'code': 'unknown_exclusive_group',
                        'reason': 'baseline rollout group excludes an unknown group',
                        'group_id': group_id,
                        'unknown_group_ids': self._baseline_promotion_unique_ids(missing_exclusive),
                    })
                    exclusive_conflict_count += len(missing_exclusive)
                if group_id in exclusive_groups:
                    validation_errors.append({
                        'code': 'self_exclusive_group',
                        'reason': 'baseline rollout group cannot exclude itself',
                        'group_id': group_id,
                    })
                    exclusive_conflict_count += 1
            group_last_wave_no: dict[str, int] = {}
            group_wave_numbers: dict[str, list[int]] = {}
            group_first_portfolios: dict[str, list[str]] = {str(item.get('group_id') or ''): self._baseline_promotion_unique_ids(list(item.get('portfolio_ids') or [])) for item in ordered_groups}
            for spec in ordered_groups:
                group_id = str(spec.get('group_id') or '')
                group_label = str(spec.get('group_label') or group_id)
                portfolio_ids = [pid for pid in self._baseline_promotion_unique_ids(list(spec.get('portfolio_ids') or [])) if pid in items_by_portfolio]
                if not portfolio_ids:
                    continue
                chunk_size = int(spec.get('wave_size') or (rollout_policy or {}).get('wave_size') or 0)
                if chunk_size <= 0:
                    chunk_size = len(portfolio_ids)
                previous_chunk_wave_no = None
                for chunk_index in range(0, len(portfolio_ids), chunk_size):
                    chunk_ids = portfolio_ids[chunk_index:chunk_index + chunk_size]
                    wave_no = len(waves) + 1
                    depends_on_wave_nos = [group_last_wave_no[dep_gid] for dep_gid in list(spec.get('depends_on_groups') or []) if dep_gid in group_last_wave_no]
                    exclusive_depends_on_wave_nos = [group_last_wave_no[dep_gid] for dep_gid in list(spec.get('exclusive_with_groups') or []) if dep_gid in group_last_wave_no]
                    if previous_chunk_wave_no is not None:
                        depends_on_wave_nos.append(previous_chunk_wave_no)
                    depends_on_wave_nos.extend(exclusive_depends_on_wave_nos)
                    dependency_portfolio_ids: list[str] = []
                    for dep_gid in list(spec.get('depends_on_groups') or []):
                        dependency_portfolio_ids.extend(list(group_first_portfolios.get(dep_gid) or []))
                    wave = {
                        'wave_id': f'wave-{wave_no}-{uuid.uuid4().hex[:8]}',
                        'wave_no': wave_no,
                        'wave_label': str(spec.get('metadata', {}).get('wave_label') or group_label or f'wave-{wave_no}'),
                        'portfolio_ids': chunk_ids,
                        'group_ids': [group_id],
                        'group_labels': [group_label],
                        'items': [dict(items_by_portfolio[portfolio_id]) for portfolio_id in chunk_ids if portfolio_id in items_by_portfolio],
                        'status': 'planned',
                        'gate_evaluation': {},
                        'dependency_summary': {
                            'depends_on_group_ids': list(spec.get('depends_on_groups') or []),
                            'depends_on_wave_nos': sorted(set(int(item) for item in depends_on_wave_nos if item is not None)),
                            'dependency_portfolio_ids': self._baseline_promotion_unique_ids(dependency_portfolio_ids),
                            'cycle_detected': bool(ordered_groups_state.get('cycle_detected')),
                            'exclusive_with_groups': list(spec.get('exclusive_with_groups') or []),
                            'exclusive_depends_on_wave_nos': sorted(set(int(item) for item in exclusive_depends_on_wave_nos if item is not None)),
                        },
                    }
                    waves.append(wave)
                    group_wave_numbers.setdefault(group_id, []).append(wave_no)
                    group_last_wave_no[group_id] = wave_no
                    previous_chunk_wave_no = wave_no
            plan = {
                'promotion_id': str(promotion_id or '').strip(),
                'enabled': bool((rollout_policy or {}).get('enabled', False)) and bool(waves),
                'items': waves,
                'group_summary': {
                    'group_count': len(ordered_groups),
                    'group_ids': [str(item.get('group_id') or '') for item in ordered_groups],
                    'dependency_edge_count': sum(len(list(item.get('depends_on_groups') or [])) for item in ordered_groups),
                    'dependency_cycle_detected': bool(ordered_groups_state.get('cycle_detected')),
                    'cyclic_group_ids': [str(item) for item in list(ordered_groups_state.get('cyclic_group_ids') or [])],
                    'group_wave_numbers': {gid: list(nums) for gid, nums in group_wave_numbers.items()},
                    'exclusive_conflict_count': exclusive_conflict_count,
                },
                'validation': {
                    'status': 'failed' if validation_errors else 'passed',
                    'errors': validation_errors,
                },
            }
            return self._refresh_baseline_promotion_rollout_plan(plan)

        remaining_ids = [portfolio_id for portfolio_id in ordered_ids if portfolio_id in items_by_portfolio]
        wave_size = int((rollout_policy or {}).get('wave_size') or 0)
        if wave_size <= 0:
            wave_size = len(remaining_ids) or len(ordered_ids) or 1
        for index in range(0, len(remaining_ids), wave_size):
            portfolio_ids = remaining_ids[index:index + wave_size]
            if not portfolio_ids:
                continue
            wave_no = len(waves) + 1
            waves.append({
                'wave_id': f'wave-{wave_no}-{uuid.uuid4().hex[:8]}',
                'wave_no': wave_no,
                'wave_label': f'wave-{wave_no}',
                'portfolio_ids': portfolio_ids,
                'group_ids': [],
                'group_labels': [],
                'items': [dict(items_by_portfolio[portfolio_id]) for portfolio_id in portfolio_ids if portfolio_id in items_by_portfolio],
                'status': 'planned',
                'gate_evaluation': {},
                'dependency_summary': {'depends_on_group_ids': [], 'depends_on_wave_nos': [], 'dependency_portfolio_ids': [], 'cycle_detected': False},
            })
        plan = {
            'promotion_id': str(promotion_id or '').strip(),
            'enabled': bool((rollout_policy or {}).get('enabled', False)) and bool(waves),
            'items': waves,
            'group_summary': {'group_count': 0, 'group_ids': [], 'dependency_edge_count': 0, 'dependency_cycle_detected': False, 'cyclic_group_ids': []},
        }
        return self._refresh_baseline_promotion_rollout_plan(plan)

