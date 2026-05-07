from __future__ import annotations

from typing import Any


class OpenClawAlertGovernanceBundleGatesMixin:
    @staticmethod
    def _default_bundle_wave_gate_policy() -> dict[str, Any]:
        return {
            'enabled': True,
            'auto_halt_on_failure': True,
            'auto_rollback_on_failure': False,
            'halt_scope': 'bundle',
            'max_runtime_errors': 0,
            'max_pending_approvals': 1000000,
            'max_unhealthy_runtimes': 0,
            'max_stale_runtimes': 1000000,
            'max_critical_alerts': 1000000,
            'max_warn_alerts': 1000000,
            'max_total_alerts': 1000000,
        }

    def _effective_bundle_wave_gate_policy(
        self,
        *,
        bundle: dict[str, Any] | None = None,
        wave: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        policy = self._default_bundle_wave_gate_policy()
        policy.update(dict((bundle or {}).get('wave_gates') or {}))
        policy.update(dict((wave or {}).get('gate_policy') or {}))
        policy['enabled'] = bool(policy.get('enabled', True))
        for key, default in {
            'max_runtime_errors': 0,
            'max_pending_approvals': 1000000,
            'max_unhealthy_runtimes': 0,
            'max_stale_runtimes': 1000000,
            'max_critical_alerts': 1000000,
            'max_warn_alerts': 1000000,
            'max_total_alerts': 1000000,
        }.items():
            try:
                policy[key] = int(policy.get(key) if policy.get(key) is not None else default)
            except Exception:
                policy[key] = int(default)
        policy['auto_halt_on_failure'] = bool(policy.get('auto_halt_on_failure', True))
        policy['auto_rollback_on_failure'] = bool(policy.get('auto_rollback_on_failure', False))
        policy['halt_scope'] = str(policy.get('halt_scope') or 'bundle').strip().lower() or 'bundle'
        if policy['halt_scope'] not in {'bundle', 'wave'}:
            policy['halt_scope'] = 'bundle'
        return policy

    @staticmethod
    def _default_bundle_wave_timing_policy() -> dict[str, Any]:
        return {
            'health_window_s': 0,
            'bake_time_s': 0,
            'auto_advance': False,
            'auto_advance_delay_s': 0,
        }

    def _effective_bundle_wave_timing_policy(
        self,
        *,
        bundle: dict[str, Any] | None = None,
        wave: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        policy = self._default_bundle_wave_timing_policy()
        policy.update(dict((bundle or {}).get('wave_timing_policy') or {}))
        wave_policy = {
            'health_window_s': (wave or {}).get('health_window_s'),
            'bake_time_s': (wave or {}).get('bake_time_s'),
            'auto_advance': (wave or {}).get('auto_advance'),
            'auto_advance_delay_s': (wave or {}).get('auto_advance_delay_s'),
        }
        for key, value in wave_policy.items():
            if value is not None:
                policy[key] = value
        try:
            policy['health_window_s'] = max(0, int(policy.get('health_window_s') or 0))
        except Exception:
            policy['health_window_s'] = 0
        try:
            policy['bake_time_s'] = max(0, int(policy.get('bake_time_s') or 0))
        except Exception:
            policy['bake_time_s'] = 0
        try:
            policy['auto_advance_delay_s'] = max(0, int(policy.get('auto_advance_delay_s') or 0))
        except Exception:
            policy['auto_advance_delay_s'] = 0
        policy['auto_advance'] = bool(policy.get('auto_advance', False))
        return policy

    @staticmethod
    def _default_promotion_slo_policy() -> dict[str, Any]:
        return {
            'enabled': False,
            'min_success_ratio': 1.0,
            'max_error_ratio': 0.0,
            'max_pending_approval_ratio': 1.0,
            'max_critical_alerts_per_runtime': 1000000.0,
            'max_warn_alerts_per_runtime': 1000000.0,
            'max_total_alerts_per_runtime': 1000000.0,
            'max_stale_runtime_ratio': 1.0,
            'max_unhealthy_runtime_ratio': 1.0,
            'auto_halt_on_failure': True,
            'auto_rollback_on_failure': False,
            'warning_on_alert_presence': False,
        }

    def _effective_promotion_slo_policy(
        self,
        *,
        bundle: dict[str, Any] | None = None,
        wave: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        policy = self._default_promotion_slo_policy()
        policy.update(dict((bundle or {}).get('promotion_slo_policy') or {}))
        policy.update(dict((wave or {}).get('promotion_slo_policy') or {}))
        policy['enabled'] = bool(policy.get('enabled', False))
        for key, default in {
            'min_success_ratio': 1.0,
            'max_error_ratio': 0.0,
            'max_pending_approval_ratio': 1.0,
            'max_critical_alerts_per_runtime': 1000000.0,
            'max_warn_alerts_per_runtime': 1000000.0,
            'max_total_alerts_per_runtime': 1000000.0,
            'max_stale_runtime_ratio': 1.0,
            'max_unhealthy_runtime_ratio': 1.0,
        }.items():
            try:
                policy[key] = float(policy.get(key) if policy.get(key) is not None else default)
            except Exception:
                policy[key] = float(default)
        policy['auto_halt_on_failure'] = bool(policy.get('auto_halt_on_failure', True))
        policy['auto_rollback_on_failure'] = bool(policy.get('auto_rollback_on_failure', False))
        policy['warning_on_alert_presence'] = bool(policy.get('warning_on_alert_presence', False))
        return policy

    def _evaluate_bundle_wave_promotion_slo(
        self,
        *,
        bundle: dict[str, Any],
        wave: dict[str, Any],
        results: list[dict[str, Any]],
        gate_evaluation: dict[str, Any],
    ) -> dict[str, Any]:
        policy = self._effective_promotion_slo_policy(bundle=bundle, wave=wave)
        total = max(1, len(list(results or [])))
        success_count = sum(1 for item in list(results or []) if str(item.get('status') or '').strip() == 'active' and bool(item.get('ok')))
        error_count = sum(1 for item in list(results or []) if not bool(item.get('ok')) or str(item.get('status') or '').strip() in {'error', 'failed', 'rejected'})
        pending_count = sum(1 for item in list(results or []) if str(item.get('status') or '').strip() == 'pending_approval')
        metrics = dict(gate_evaluation.get('metrics') or {})
        success_ratio = success_count / total
        error_ratio = error_count / total
        pending_ratio = pending_count / total
        critical_per_runtime = float(metrics.get('critical_alerts') or 0) / total
        warn_per_runtime = float(metrics.get('warn_alerts') or 0) / total
        total_alerts_per_runtime = float(metrics.get('total_alerts') or 0) / total
        stale_ratio = float(metrics.get('stale_runtimes') or 0) / total
        unhealthy_ratio = float(metrics.get('unhealthy_runtimes') or 0) / total
        failures: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        if policy.get('enabled'):
            if success_ratio < float(policy.get('min_success_ratio') or 0.0):
                failures.append({'metric': 'success_ratio', 'value': round(success_ratio, 4), 'threshold': float(policy.get('min_success_ratio') or 0.0), 'reason': f'success_ratio={success_ratio:.4f} below min_success_ratio={float(policy.get("min_success_ratio") or 0.0):.4f}'})
            if error_ratio > float(policy.get('max_error_ratio') or 0.0):
                failures.append({'metric': 'error_ratio', 'value': round(error_ratio, 4), 'threshold': float(policy.get('max_error_ratio') or 0.0), 'reason': f'error_ratio={error_ratio:.4f} exceeded max_error_ratio={float(policy.get("max_error_ratio") or 0.0):.4f}'})
            if pending_ratio > float(policy.get('max_pending_approval_ratio') or 0.0):
                failures.append({'metric': 'pending_approval_ratio', 'value': round(pending_ratio, 4), 'threshold': float(policy.get('max_pending_approval_ratio') or 0.0), 'reason': f'pending_approval_ratio={pending_ratio:.4f} exceeded max_pending_approval_ratio={float(policy.get("max_pending_approval_ratio") or 0.0):.4f}'})
            checks = {
                'critical_alerts_per_runtime': (critical_per_runtime, float(policy.get('max_critical_alerts_per_runtime') or 0.0)),
                'warn_alerts_per_runtime': (warn_per_runtime, float(policy.get('max_warn_alerts_per_runtime') or 0.0)),
                'total_alerts_per_runtime': (total_alerts_per_runtime, float(policy.get('max_total_alerts_per_runtime') or 0.0)),
                'stale_runtime_ratio': (stale_ratio, float(policy.get('max_stale_runtime_ratio') or 0.0)),
                'unhealthy_runtime_ratio': (unhealthy_ratio, float(policy.get('max_unhealthy_runtime_ratio') or 0.0)),
            }
            for metric_key, pair in checks.items():
                value, threshold = pair
                if value > threshold:
                    failures.append({'metric': metric_key, 'value': round(value, 4), 'threshold': threshold, 'reason': f'{metric_key}={value:.4f} exceeded threshold={threshold:.4f}'})
        elif bool(policy.get('warning_on_alert_presence')) and (critical_per_runtime > 0 or warn_per_runtime > 0):
            warnings.append({'metric': 'alerts_present', 'value': {'critical_per_runtime': round(critical_per_runtime, 4), 'warn_per_runtime': round(warn_per_runtime, 4)}, 'reason': 'alerts present during rollout observation'})
        status = 'passed'
        if failures:
            status = 'failed'
        elif warnings:
            status = 'warning'
        return {
            'status': status,
            'policy': policy,
            'metrics': {
                'runtime_count': total,
                'success_count': success_count,
                'error_count': error_count,
                'pending_approval_count': pending_count,
                'success_ratio': round(success_ratio, 4),
                'error_ratio': round(error_ratio, 4),
                'pending_approval_ratio': round(pending_ratio, 4),
                'critical_alerts_per_runtime': round(critical_per_runtime, 4),
                'warn_alerts_per_runtime': round(warn_per_runtime, 4),
                'total_alerts_per_runtime': round(total_alerts_per_runtime, 4),
                'stale_runtime_ratio': round(stale_ratio, 4),
                'unhealthy_runtime_ratio': round(unhealthy_ratio, 4),
            },
            'failures': failures,
            'warnings': warnings,
            'should_halt': bool(status == 'failed' and policy.get('auto_halt_on_failure', True)),
            'should_rollback': bool(status == 'failed' and policy.get('auto_rollback_on_failure', False)),
        }

    def _runtime_governance_release_signal_summary(
        self,
        gw,
        *,
        runtime_id: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        detail = self.openclaw_adapter_service.get_runtime(
            gw,
            runtime_id=runtime_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        if not detail.get('ok'):
            return {
                'runtime_id': runtime_id,
                'gate_state': 'fail',
                'reasons': ['runtime_lookup_failed'],
                'metrics': {'runtime_errors': 1},
                'runtime_summary': {},
                'health': {},
                'alerts': {'summary': {}},
            }
        runtime = dict(detail.get('runtime') or {})
        runtime_summary = dict(detail.get('runtime_summary') or self.openclaw_adapter_service._build_runtime_summary(runtime))
        health = dict(detail.get('health') or {})
        alerts_payload = self.evaluate_runtime_alerts(
            gw,
            runtime_id=runtime_id,
            limit=max(10, int(limit)),
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        alerts_summary = dict(alerts_payload.get('summary') or {})
        metadata = dict(runtime.get('metadata') or {})
        overrides = dict(metadata.get('governance_release_signals') or {})
        metrics = {
            'runtime_errors': 0,
            'pending_approvals': 0,
            'unhealthy_runtimes': 1 if str(health.get('status') or '').strip().lower() == 'unhealthy' else 0,
            'stale_runtimes': 1 if bool(health.get('stale')) else 0,
            'critical_alerts': int(alerts_summary.get('critical_count') or 0),
            'warn_alerts': int(alerts_summary.get('warn_count') or 0),
            'total_alerts': int(alerts_summary.get('count') or 0),
        }
        for key in list(metrics):
            if overrides.get(key) is not None:
                try:
                    metrics[key] = int(overrides.get(key) or 0)
                except Exception:
                    pass
        forced_state = str(overrides.get('gate_state') or '').strip().lower()
        reasons = [str(item) for item in list(overrides.get('reasons') or []) if str(item).strip()]
        gate_state = forced_state if forced_state in {'pass', 'warn', 'fail'} else 'pass'
        if not forced_state:
            if metrics['runtime_errors'] > 0 or metrics['unhealthy_runtimes'] > 0:
                gate_state = 'fail'
            elif metrics['stale_runtimes'] > 0 or metrics['critical_alerts'] > 0 or metrics['warn_alerts'] > 0:
                gate_state = 'warn'
        return {
            'runtime_id': runtime_id,
            'gate_state': gate_state,
            'reasons': reasons,
            'metrics': metrics,
            'runtime_summary': runtime_summary,
            'health': health,
            'alerts': {'summary': alerts_summary},
        }

    def _evaluate_bundle_wave_gates(
        self,
        gw,
        *,
        release: dict[str, Any],
        bundle: dict[str, Any],
        wave: dict[str, Any],
        results: list[dict[str, Any]],
        limit: int = 50,
    ) -> dict[str, Any]:
        gate_policy = self._effective_bundle_wave_gate_policy(bundle=bundle, wave=wave)
        scope = self._scope(tenant_id=release.get('tenant_id'), workspace_id=release.get('workspace_id'), environment=release.get('environment'))
        signal_items = []
        aggregated = {
            'runtime_errors': 0,
            'pending_approvals': 0,
            'unhealthy_runtimes': 0,
            'stale_runtimes': 0,
            'critical_alerts': 0,
            'warn_alerts': 0,
            'total_alerts': 0,
        }
        for result in list(results or []):
            rid = str(result.get('runtime_id') or '').strip()
            if not rid:
                continue
            signal = self._runtime_governance_release_signal_summary(
                gw,
                runtime_id=rid,
                tenant_id=scope.get('tenant_id'),
                workspace_id=scope.get('workspace_id'),
                environment=scope.get('environment'),
                limit=limit,
            )
            signal_metrics = dict(signal.get('metrics') or {})
            if not bool(result.get('ok')):
                signal_metrics['runtime_errors'] = int(signal_metrics.get('runtime_errors') or 0) + 1
            if str(result.get('status') or '') == 'pending_approval':
                signal_metrics['pending_approvals'] = int(signal_metrics.get('pending_approvals') or 0) + 1
            signal['metrics'] = signal_metrics
            for key in aggregated:
                aggregated[key] += int(signal_metrics.get(key) or 0)
            signal_items.append(signal)
        failures = []
        if gate_policy.get('enabled', True):
            for signal in signal_items:
                gate_state = str(signal.get('gate_state') or '').strip().lower()
                if gate_state == 'fail':
                    failures.append({
                        'metric': 'gate_state',
                        'value': gate_state,
                        'threshold': 'pass',
                        'reason': '; '.join(list(signal.get('reasons') or [])) or f"runtime {signal.get('runtime_id')} reported gate_state=fail",
                    })
            mapping = {
                'runtime_errors': 'max_runtime_errors',
                'pending_approvals': 'max_pending_approvals',
                'unhealthy_runtimes': 'max_unhealthy_runtimes',
                'stale_runtimes': 'max_stale_runtimes',
                'critical_alerts': 'max_critical_alerts',
                'warn_alerts': 'max_warn_alerts',
                'total_alerts': 'max_total_alerts',
            }
            for metric_key, threshold_key in mapping.items():
                threshold = int(gate_policy.get(threshold_key) or 0)
                value = int(aggregated.get(metric_key) or 0)
                if value > threshold:
                    failures.append({
                        'metric': metric_key,
                        'value': value,
                        'threshold': threshold,
                        'reason': f'{metric_key}={value} exceeded {threshold_key}={threshold}',
                    })
        status = 'passed'
        if failures:
            status = 'failed'
        elif any(str(item.get('gate_state') or '') == 'warn' for item in signal_items):
            status = 'warning'
        return {
            'status': status,
            'canary': bool(wave.get('canary', False)),
            'policy': gate_policy,
            'metrics': aggregated,
            'signals': signal_items,
            'failures': failures,
            'should_halt': bool(status == 'failed' and gate_policy.get('auto_halt_on_failure', True)),
            'should_rollback': bool(status == 'failed' and gate_policy.get('auto_rollback_on_failure', False)),
        }

    def _rollback_bundle_wave_results(
        self,
        gw,
        *,
        release: dict[str, Any],
        results: list[dict[str, Any]],
        actor: str,
        reason: str,
    ) -> dict[str, Any]:
        rollback_results = []
        for item in list(results or []):
            version_id = str(item.get('version_id') or '').strip()
            runtime_id = str(item.get('runtime_id') or '').strip()
            status = str(item.get('status') or '').strip()
            if not version_id or not runtime_id or status != 'active':
                continue
            rollback = self.rollback_runtime_alert_governance_version(
                gw,
                runtime_id=runtime_id,
                version_id=version_id,
                actor=actor,
                reason=reason,
                tenant_id=release.get('tenant_id'),
                workspace_id=release.get('workspace_id'),
                environment=release.get('environment'),
            )
            rollback_results.append({
                'runtime_id': runtime_id,
                'ok': bool(rollback.get('ok')),
                'rollback_version_id': ((rollback.get('version') or {}).get('version_id')),
                'rollback_of_version_id': version_id,
                'error': rollback.get('error'),
            })
        return {
            'count': len(rollback_results),
            'items': rollback_results,
            'error_count': sum(1 for item in rollback_results if not item.get('ok')),
        }

    def _runtime_bundle_state(
        self,
        gw,
        *,
        runtime_id: str,
        bundle_id: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        versions = gw.audit.list_runtime_governance_policy_versions(
            runtime_id=runtime_id,
            policy_kind='alert_governance',
            limit=20,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        matching = []
        for item in versions:
            view = self._runtime_alert_governance_version_view(item)
            bundle = dict(view.get('bundle') or {})
            if str(bundle.get('release_bundle_id') or '').strip() == str(bundle_id or '').strip():
                matching.append(view)
        latest = matching[0] if matching else None
        approval = dict((latest or {}).get('approval') or {}) if latest else {}
        return {
            'runtime_id': runtime_id,
            'status': str((latest or {}).get('status') or 'not_started'),
            'version_id': (latest or {}).get('version_id'),
            'version_no': (latest or {}).get('version_no'),
            'approval': approval,
            'release': dict((latest or {}).get('release') or {}),
            'bundle': dict((latest or {}).get('bundle') or {}),
            'latest_version': latest,
        }

    def _bundle_rollout_analytics(self, *, bundle: dict[str, Any], runtime_details: list[dict[str, Any]], enriched_waves: list[dict[str, Any]], summary: dict[str, Any]) -> dict[str, Any]:
        total = max(1, len(runtime_details))
        active = int(summary.get('active_runtime_count') or 0)
        pending = int(summary.get('pending_runtime_approval_count') or 0)
        started = sum(1 for item in runtime_details if str(item.get('status') or '') not in {'not_started'})
        completion_ratio = round((summary.get('completed_wave_count') or 0) / max(1, int(summary.get('wave_count') or 0)), 4)
        current_exposure_ratio = round(started / total, 4)
        active_exposure_ratio = round(active / total, 4)
        pending_ratio = round(pending / total, 4)
        wave_exposure_curve = []
        cumulative_actual = 0
        for wave in enriched_waves:
            ids = list(wave.get('runtime_ids') or [])
            statuses = dict(wave.get('runtime_status_counts') or {})
            active_in_wave = int(statuses.get('active', 0) or 0)
            started_in_wave = sum(int(statuses.get(key) or 0) for key in statuses if key not in {'not_started'})
            cumulative_actual += started_in_wave
            wave_exposure_curve.append({
                'wave_no': int(wave.get('wave_no') or 0),
                'label': str(wave.get('label') or ''),
                'canary': bool(wave.get('canary')),
                'planned_target_count': int(wave.get('planned_target_count') or min(total, cumulative_actual or len(ids))),
                'planned_exposure_ratio': round(float(wave.get('planned_exposure_ratio') or 0.0), 4),
                'actual_started_count': started_in_wave,
                'actual_started_ratio': round(started_in_wave / max(1, len(ids)), 4),
                'actual_active_count': active_in_wave,
                'actual_active_ratio': round(active_in_wave / max(1, len(ids)), 4),
                'observation_status': str((wave.get('observation') or {}).get('status') or ''),
                'gate_status': str((wave.get('gate_evaluation') or {}).get('status') or 'not_evaluated'),
                'slo_status': str((wave.get('promotion_slo_evaluation') or {}).get('status') or 'not_evaluated'),
                'status': str(wave.get('status') or ''),
            })
        progressive = dict(bundle.get('progressive_exposure_policy') or {})
        analytics = self._governance_analytics_shape(
            curve=wave_exposure_curve,
            latest=wave_exposure_curve[-1] if wave_exposure_curve else None,
            extras={
                'current_exposure_ratio': current_exposure_ratio,
                'active_exposure_ratio': active_exposure_ratio,
                'pending_runtime_approval_ratio': pending_ratio,
                'wave_completion_ratio': completion_ratio,
                'runtime_start_ratio': current_exposure_ratio,
                'runtime_activation_ratio': active_exposure_ratio,
                'average_wave_size': round(sum(len(list(w.get('runtime_ids') or [])) for w in enriched_waves) / max(1, len(enriched_waves)), 2) if enriched_waves else 0.0,
                'progressive_exposure_policy': progressive,
                'rollout_health': {
                    'gate_failed_wave_count': int(summary.get('gate_failed_wave_count') or 0),
                    'slo_failed_wave_count': int(summary.get('slo_failed_wave_count') or 0),
                    'rollback_wave_count': int(summary.get('rollback_wave_count') or 0),
                    'halted': bool(summary.get('halted')),
                    'rollout_status': str(summary.get('rollout_status') or ''),
                },
            },
        )
        analytics['wave_exposure_curve'] = list(analytics.pop('curve', []))
        analytics['latest_wave'] = analytics.pop('latest', None)
        return analytics
