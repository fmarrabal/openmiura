from __future__ import annotations

from typing import Any


class OpenClawBaselineRolloutGatesMixin:
    def _evaluate_baseline_promotion_wave_gate(
        self,
        gw,
        *,
        promotion_release: dict[str, Any],
        wave: dict[str, Any],
        gate_policy: dict[str, Any],
        portfolio_release_overrides: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        promotion = dict(((promotion_release.get('metadata') or {}).get('baseline_promotion') or {}) or {})
        items: list[dict[str, Any]] = []
        nonconformant_count = 0
        warning_count = 0
        warning_portfolio_count = 0
        blocking_baseline_drift_count = 0
        total_fail_count = 0
        portfolio_release_overrides = {str(key): dict(value) for key, value in dict(portfolio_release_overrides or {}).items() if str(key).strip()}
        for portfolio_id in self._baseline_promotion_unique_ids(list(wave.get('portfolio_ids') or [])):
            portfolio_release = dict(portfolio_release_overrides.get(str(portfolio_id or '')) or {})
            if not portfolio_release:
                portfolio_release = gw.audit.get_release_bundle(
                    str(portfolio_id or ''),
                    tenant_id=promotion_release.get('tenant_id'),
                    workspace_id=promotion_release.get('workspace_id'),
                    environment=None,
                )
            if portfolio_release is None or not self._is_alert_governance_portfolio_release(portfolio_release):
                continue
            conformance = self._portfolio_policy_conformance_report(gw, release=portfolio_release, persist_metadata=False)
            baseline_drift = self._portfolio_policy_baseline_drift_report(gw, release=portfolio_release, persist_metadata=False)
            conformance_status = str(conformance.get('overall_status') or 'unknown')
            baseline_drift_status = str(baseline_drift.get('overall_status') or 'unknown')
            is_nonconformant = conformance_status == 'nonconformant'
            wave_warning_count = int((conformance.get('summary') or {}).get('warning_count') or 0)
            fail_count = int((conformance.get('summary') or {}).get('fail_count') or 0)
            is_blocking_baseline_drift = bool(baseline_drift.get('blocking', False))
            if is_nonconformant:
                nonconformant_count += 1
            warning_count += wave_warning_count
            total_fail_count += fail_count
            if wave_warning_count > 0:
                warning_portfolio_count += 1
            if is_blocking_baseline_drift:
                blocking_baseline_drift_count += 1
            items.append({
                'portfolio_id': str(portfolio_release.get('release_id') or ''),
                'name': str(portfolio_release.get('name') or ''),
                'environment': self._normalize_portfolio_environment_name(portfolio_release.get('environment')),
                'policy_conformance_status': conformance_status,
                'baseline_drift_status': baseline_drift_status,
                'baseline_drift_blocking': is_blocking_baseline_drift,
                'warning_count': wave_warning_count,
                'fail_count': fail_count,
                'baseline_catalog_rollout': dict((((portfolio_release.get('metadata') or {}).get('portfolio') or {}).get('current_baseline_catalog_rollout') or {}) or {}),
            })
        portfolio_count = len(items)
        denominator = max(1, portfolio_count)
        nonconformant_ratio = round(nonconformant_count / denominator, 4)
        warning_ratio = round(warning_count / denominator, 4)
        warning_portfolio_ratio = round(warning_portfolio_count / denominator, 4)
        blocking_baseline_drift_ratio = round(blocking_baseline_drift_count / denominator, 4)
        conformance_ratio = round((portfolio_count - nonconformant_count) / denominator, 4)
        previous_summary = None
        previous_wave_no = None
        rollout_plan = self._refresh_baseline_promotion_rollout_plan(dict(promotion.get('rollout_plan') or {}))
        for candidate in sorted([dict(item) for item in list(rollout_plan.get('items') or []) if int(item.get('wave_no') or 0) < int(wave.get('wave_no') or 0)], key=lambda item: int(item.get('wave_no') or 0), reverse=True):
            gate_eval = dict(candidate.get('gate_evaluation') or {})
            summary = dict(gate_eval.get('summary') or {})
            if summary:
                previous_summary = summary
                previous_wave_no = int(candidate.get('wave_no') or 0)
                break
        deltas = {
            'previous_wave_no': previous_wave_no,
            'nonconformant_delta': nonconformant_count - int((previous_summary or {}).get('nonconformant_count') or 0) if previous_summary else None,
            'blocking_baseline_drift_delta': blocking_baseline_drift_count - int((previous_summary or {}).get('blocking_baseline_drift_count') or 0) if previous_summary else None,
            'warning_delta': warning_count - int((previous_summary or {}).get('warning_count') or 0) if previous_summary else None,
        }
        passed = True
        reasons: list[str] = []
        if bool(gate_policy.get('enabled', True)):
            if bool(gate_policy.get('block_on_nonconformant', True)) and nonconformant_count > int(gate_policy.get('max_nonconformant_count') or 0):
                passed = False
                reasons.append('nonconformant_portfolios')
            max_nonconformant_ratio = gate_policy.get('max_nonconformant_ratio')
            if bool(gate_policy.get('block_on_nonconformant', True)) and max_nonconformant_ratio is not None and nonconformant_ratio > float(max_nonconformant_ratio):
                passed = False
                reasons.append('nonconformant_ratio_exceeded')
            if bool(gate_policy.get('block_on_baseline_drift', True)) and blocking_baseline_drift_count > int(gate_policy.get('max_blocking_baseline_drift_count') or 0):
                passed = False
                reasons.append('blocking_baseline_drift')
            max_blocking_baseline_drift_ratio = gate_policy.get('max_blocking_baseline_drift_ratio')
            if bool(gate_policy.get('block_on_baseline_drift', True)) and max_blocking_baseline_drift_ratio is not None and blocking_baseline_drift_ratio > float(max_blocking_baseline_drift_ratio):
                passed = False
                reasons.append('blocking_baseline_drift_ratio_exceeded')
            if bool(gate_policy.get('block_on_warning', False)) and warning_count > int(gate_policy.get('max_warning_count') or 0):
                passed = False
                reasons.append('warning_threshold_exceeded')
            max_warning_ratio = gate_policy.get('max_warning_ratio')
            if bool(gate_policy.get('block_on_warning', False)) and max_warning_ratio is not None and warning_ratio > float(max_warning_ratio):
                passed = False
                reasons.append('warning_ratio_exceeded')
            if bool(gate_policy.get('block_on_warning', False)) and warning_portfolio_count > int(gate_policy.get('max_warning_portfolio_count') or 0):
                passed = False
                reasons.append('warning_portfolio_threshold_exceeded')
            max_warning_portfolio_ratio = gate_policy.get('max_warning_portfolio_ratio')
            if bool(gate_policy.get('block_on_warning', False)) and max_warning_portfolio_ratio is not None and warning_portfolio_ratio > float(max_warning_portfolio_ratio):
                passed = False
                reasons.append('warning_portfolio_ratio_exceeded')
            if int(gate_policy.get('max_total_fail_count') or 0) >= 0 and total_fail_count > int(gate_policy.get('max_total_fail_count') or 0):
                passed = False
                reasons.append('conformance_fail_threshold_exceeded')
            if bool(gate_policy.get('block_on_health_regression', False)) and previous_summary is not None:
                if int(deltas.get('nonconformant_delta') or 0) > int(gate_policy.get('max_nonconformant_delta') or 0):
                    passed = False
                    reasons.append('nonconformant_regression')
                if int(deltas.get('blocking_baseline_drift_delta') or 0) > int(gate_policy.get('max_blocking_baseline_drift_delta') or 0):
                    passed = False
                    reasons.append('blocking_baseline_drift_regression')
                if int(deltas.get('warning_delta') or 0) > int(gate_policy.get('max_warning_delta') or 0):
                    passed = False
                    reasons.append('warning_regression')
        summary = {
            'count': portfolio_count,
            'nonconformant_count': nonconformant_count,
            'warning_count': warning_count,
            'warning_portfolio_count': warning_portfolio_count,
            'total_fail_count': total_fail_count,
            'blocking_baseline_drift_count': blocking_baseline_drift_count,
            'candidate_catalog_version': str(promotion.get('candidate_catalog_version') or promotion_release.get('version') or ''),
            'nonconformant_ratio': nonconformant_ratio,
            'warning_ratio': warning_ratio,
            'warning_portfolio_ratio': warning_portfolio_ratio,
            'blocking_baseline_drift_ratio': blocking_baseline_drift_ratio,
            'conformance_ratio': conformance_ratio,
            'previous_wave_no': previous_wave_no,
        }
        return {
            'status': 'passed' if passed else 'failed',
            'gate_policy': dict(gate_policy or {}),
            'passed': passed,
            'reasons': self._baseline_promotion_unique_ids(reasons),
            'summary': summary,
            'health': {
                'portfolio_count': portfolio_count,
                'nonconformant_ratio': nonconformant_ratio,
                'warning_ratio': warning_ratio,
                'warning_portfolio_ratio': warning_portfolio_ratio,
                'blocking_baseline_drift_ratio': blocking_baseline_drift_ratio,
                'conformance_ratio': conformance_ratio,
                'deltas': deltas,
            },
            'items': items,
        }

    def _baseline_promotion_timeline_view(self, release: dict[str, Any], *, limit: int = 200) -> dict[str, Any]:
        promotion = dict(((release.get('metadata') or {}).get('baseline_promotion') or {}) or {})
        timeline = [dict(item) for item in list(promotion.get('timeline') or [])]
        timeline.sort(key=lambda item: (float(item.get('ts') or 0.0), str(item.get('kind') or ''), str(item.get('label') or '')))
        trimmed = timeline[-max(1, int(limit)):]
        return {
            'items': trimmed,
            'summary': {
                'count': len(trimmed),
                'first_ts': trimmed[0].get('ts') if trimmed else None,
                'last_ts': trimmed[-1].get('ts') if trimmed else None,
            },
        }

    def _baseline_promotion_analytics_view(self, release: dict[str, Any]) -> dict[str, Any]:
        promotion = dict(((release.get('metadata') or {}).get('baseline_promotion') or {}) or {})
        rollout_plan = self._refresh_baseline_promotion_rollout_plan(dict(promotion.get('rollout_plan') or {}))
        rollback_attestations = [dict(item) for item in list(promotion.get('rollback_attestations') or [])]
        timeline = list((promotion.get('timeline') or []))
        summary = dict(rollout_plan.get('summary') or {})
        group_summary = dict(rollout_plan.get('group_summary') or {})
        wave_health_curve: list[dict[str, Any]] = []
        latest_health: dict[str, Any] | None = None
        for wave in [dict(item) for item in list(rollout_plan.get('items') or [])]:
            gate = dict(wave.get('gate_evaluation') or {})
            gate_summary = dict(gate.get('summary') or {})
            gate_health = dict(gate.get('health') or {})
            curve_item = {
                'wave_no': int(wave.get('wave_no') or 0),
                'wave_id': str(wave.get('wave_id') or ''),
                'wave_label': str(wave.get('wave_label') or ''),
                'status': str(wave.get('status') or 'planned'),
                'group_ids': list(wave.get('group_ids') or []),
                'group_labels': list(wave.get('group_labels') or []),
                'depends_on_wave_nos': list((wave.get('dependency_summary') or {}).get('depends_on_wave_nos') or []),
                'gate_status': str(gate.get('status') or ('passed' if gate.get('passed') else 'not_evaluated')),
                'nonconformant_count': int(gate_summary.get('nonconformant_count') or 0),
                'warning_count': int(gate_summary.get('warning_count') or 0),
                'warning_portfolio_count': int(gate_summary.get('warning_portfolio_count') or 0),
                'blocking_baseline_drift_count': int(gate_summary.get('blocking_baseline_drift_count') or 0),
                'total_fail_count': int(gate_summary.get('total_fail_count') or 0),
                'nonconformant_ratio': float(gate_summary.get('nonconformant_ratio') or gate_health.get('nonconformant_ratio') or 0.0),
                'warning_ratio': float(gate_summary.get('warning_ratio') or gate_health.get('warning_ratio') or 0.0),
                'warning_portfolio_ratio': float(gate_summary.get('warning_portfolio_ratio') or gate_health.get('warning_portfolio_ratio') or 0.0),
                'blocking_baseline_drift_ratio': float(gate_summary.get('blocking_baseline_drift_ratio') or gate_health.get('blocking_baseline_drift_ratio') or 0.0),
                'conformance_ratio': float(gate_summary.get('conformance_ratio') or gate_health.get('conformance_ratio') or 0.0),
                'reasons': list(gate.get('reasons') or []),
                'deltas': dict(gate_health.get('deltas') or {}),
            }
            wave_health_curve.append(curve_item)
            if gate_health:
                latest_health = curve_item
        gate_reason_counts = self._governance_reason_counts(wave_health_curve)
        analytics = self._governance_analytics_shape(
            reason_counts=gate_reason_counts,
            curve=wave_health_curve,
            latest=latest_health,
            extras={
                'wave_count': int(rollout_plan.get('wave_count') or 0),
                'completed_wave_count': int(rollout_plan.get('completed_wave_count') or 0),
                'applied_portfolio_count': len(list(rollout_plan.get('applied_portfolio_ids') or [])),
                'rolled_back_portfolio_count': len(list(rollout_plan.get('rolled_back_portfolio_ids') or [])),
                'pending_portfolio_count': len(list(rollout_plan.get('pending_portfolio_ids') or [])),
                'gate_failed': bool(summary.get('gate_failed')),
                'gate_failed_wave_no': summary.get('gate_failed_wave_no'),
                'rollback_attestation_count': len(rollback_attestations),
                'timeline_count': len(timeline),
                'group_count': int(group_summary.get('group_count') or 0),
                'group_ids': list(group_summary.get('group_ids') or []),
                'dependency_edge_count': int(group_summary.get('dependency_edge_count') or 0),
                'dependency_cycle_detected': bool(group_summary.get('dependency_cycle_detected', False)),
                'dependency_blocked_wave_count': int(summary.get('dependency_blocked_wave_count') or 0),
                'slo_gate_policy': dict(((promotion.get('promotion_policy') or {}).get('gate_policy') or {})),
            },
        )
        analytics['gate_reason_counts'] = analytics.pop('reason_counts', {})
        analytics['wave_health_curve'] = analytics.pop('curve', [])
        analytics['latest_health'] = analytics.pop('latest', None)
        return analytics

