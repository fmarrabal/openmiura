from __future__ import annotations

import time
from typing import Any


class OpenClawRuntimeAlertExecutionMixin:
    def get_runtime_alert_governance(
        self,
        gw,
        *,
        runtime_id: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        alerts_payload = self.evaluate_runtime_alerts(gw, runtime_id=runtime_id, limit=limit, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if not alerts_payload.get('ok'):
            return alerts_payload
        runtime_summary = dict(alerts_payload.get('runtime_summary') or {})
        scope = dict(alerts_payload.get('scope') or {})
        policy = self._effective_alert_governance_policy(runtime_summary=runtime_summary, scope={**scope, 'runtime_class': str((((runtime_summary.get('metadata') or {}).get('runtime_class')) or ''))})
        now_ts = time.time()
        quiet = self._quiet_hours_decision(policy=policy, alert={'severity': '', 'code': ''}, now_ts=now_ts)
        maintenance = self._maintenance_decision(policy=policy, alert={'severity': '', 'code': ''}, now_ts=now_ts)
        alerts = list(alerts_payload.get('items') or [])
        storm_summary = self._storm_decision(policy=policy, alert={'severity': 'warn', 'code': ''}, alerts=alerts, now_ts=now_ts)
        suppressed_alerts = [item for item in alerts if bool(((item.get('governance') or {}).get('suppressed')))]
        scheduled_alerts = [item for item in alerts if bool(((item.get('governance') or {}).get('scheduled')))]
        versions_payload = self.list_runtime_alert_governance_versions(
            gw,
            runtime_id=runtime_id,
            limit=20,
            tenant_id=scope.get('tenant_id'),
            workspace_id=scope.get('workspace_id'),
            environment=scope.get('environment'),
        )
        return {
            'ok': True,
            'runtime_id': runtime_id,
            'runtime_summary': runtime_summary,
            'policy': policy,
            'current': {
                'quiet_hours_active': bool(quiet.get('active')),
                'maintenance_active': bool(maintenance.get('active')),
                'storm_active': bool(storm_summary.get('active')),
                'active_maintenance_windows': list(maintenance.get('windows') or []),
                'applied_overrides': list(policy.get('applied_overrides') or []),
            },
            'summary': {
                'suppressed_alert_count': len(suppressed_alerts),
                'scheduled_alert_count': len(scheduled_alerts),
                'alert_count': len(alerts),
                'active_override_count': len(list(policy.get('applied_overrides') or [])),
            },
            'alerts': alerts_payload,
            'versions': versions_payload,
            'scope': scope,
        }

    @staticmethod
    def _alert_by_code(payload: dict[str, Any] | None, alert_code: str) -> dict[str, Any] | None:
        code = str(alert_code or '').strip()
        for item in list((payload or {}).get('items') or []):
            if str((item or {}).get('code') or '').strip() == code:
                return dict(item or {})
        return None

    def _runtime_job_ids(self, gw, *, runtime_id: str, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> set[str]:
        jobs = self.list_recovery_jobs(gw, limit=500, runtime_id=runtime_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        return {str(item.get('job_id') or '').strip() for item in list(jobs.get('items') or []) if str(item.get('job_id') or '').strip()}

    def list_worker_leases(
        self,
        gw,
        *,
        limit: int = 100,
        active_only: bool | None = None,
        lease_type: str | None = None,
        runtime_id: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        scope = self._scope(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        now = time.time()
        items = [
            self._decorate_worker_lease(item, now=now)
            for item in gw.audit.list_worker_leases(limit=max(limit * 5, limit), active_only=active_only, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'))
        ]
        runtime_job_ids: set[str] = set()
        runtime_workspace_prefix = ''
        runtime_runtime_key = ''
        if runtime_id:
            detail = self.openclaw_adapter_service.get_runtime(gw, runtime_id=runtime_id, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'))
            if not detail.get('ok'):
                return detail
            runtime = dict(detail.get('runtime') or {})
            scope = self._scope(tenant_id=runtime.get('tenant_id'), workspace_id=runtime.get('workspace_id'), environment=runtime.get('environment'))
            runtime_job_ids = self._runtime_job_ids(gw, runtime_id=runtime_id, **scope)
            runtime_workspace_prefix = self._workspace_lease_prefix(scope)
            runtime_runtime_key = self._runtime_lease_key(runtime_id)
        filtered: list[dict[str, Any]] = []
        requested_type = str(lease_type or '').strip().lower()
        for item in items:
            current_type = str(item.get('lease_type') or '')
            if requested_type and current_type != requested_type:
                continue
            if runtime_id:
                key = str(item.get('lease_key') or '')
                if current_type == 'runtime' and key != runtime_runtime_key:
                    continue
                if current_type == 'workspace' and not key.startswith(runtime_workspace_prefix):
                    continue
                if current_type == 'job':
                    job_id = key.rsplit(':', 1)[-1]
                    if job_id not in runtime_job_ids:
                        continue
            filtered.append(item)
            if len(filtered) >= limit:
                break
        type_counts: dict[str, int] = {}
        active_counts: dict[str, int] = {}
        for item in filtered:
            lt = str(item.get('lease_type') or 'other')
            type_counts[lt] = type_counts.get(lt, 0) + 1
            if bool(item.get('active')):
                active_counts[lt] = active_counts.get(lt, 0) + 1
        return {
            'ok': True,
            'items': filtered,
            'summary': {
                'count': len(filtered),
                'active_count': sum(1 for item in filtered if bool(item.get('active'))),
                'type_counts': type_counts,
                'active_type_counts': active_counts,
                'runtime_id': runtime_id,
                'lease_type': lease_type,
            },
            'scope': scope,
        }

    def list_idempotency_records(
        self,
        gw,
        *,
        limit: int = 100,
        active_only: bool | None = None,
        status: str | None = None,
        runtime_id: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        scope = self._scope(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        now = time.time()
        items = [
            self._decorate_idempotency_record(item, now=now)
            for item in gw.audit.list_idempotency_records(limit=max(limit * 5, limit), active_only=active_only, key_prefix='openclaw-recovery:idempotency:', status=status, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'))
        ]
        runtime_job_ids: set[str] = set()
        if runtime_id:
            detail = self.openclaw_adapter_service.get_runtime(gw, runtime_id=runtime_id, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'))
            if not detail.get('ok'):
                return detail
            runtime = dict(detail.get('runtime') or {})
            scope = self._scope(tenant_id=runtime.get('tenant_id'), workspace_id=runtime.get('workspace_id'), environment=runtime.get('environment'))
            runtime_job_ids = self._runtime_job_ids(gw, runtime_id=runtime_id, **scope)
        filtered: list[dict[str, Any]] = []
        for item in items:
            if runtime_id and str(item.get('job_id') or '') not in runtime_job_ids:
                continue
            filtered.append(item)
            if len(filtered) >= limit:
                break
        status_counts: dict[str, int] = {}
        for item in filtered:
            key = str(item.get('status') or 'unknown')
            status_counts[key] = status_counts.get(key, 0) + 1
        return {
            'ok': True,
            'items': filtered,
            'summary': {
                'count': len(filtered),
                'active_count': sum(1 for item in filtered if bool(item.get('active'))),
                'status_counts': status_counts,
                'runtime_id': runtime_id,
                'status': status,
            },
            'scope': scope,
        }

    def get_runtime_concurrency(
        self,
        gw,
        *,
        runtime_id: str,
        limit: int = 20,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        detail = self.openclaw_adapter_service.get_runtime(gw, runtime_id=runtime_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if not detail.get('ok'):
            return detail
        runtime = dict(detail.get('runtime') or {})
        scope = self._scope(tenant_id=runtime.get('tenant_id'), workspace_id=runtime.get('workspace_id'), environment=runtime.get('environment'))
        runtime_summary = dict(detail.get('runtime_summary') or {})
        dispatch_policy = dict(runtime_summary.get('dispatch_policy') or {})
        recovery_schedule = dict(runtime_summary.get('recovery_schedule') or {})
        runtime_dispatches = self.openclaw_adapter_service.list_dispatches(gw, runtime_id=runtime_id, limit=max(limit * 5, 200), **scope)
        runtime_items = list(runtime_dispatches.get('items') or [])
        active_statuses = {'requested', 'accepted', 'queued', 'running'}
        runtime_active_runs = sum(1 for item in runtime_items if str(item.get('canonical_status') or '').strip().lower() in active_statuses)
        workspace_dispatches = self.openclaw_adapter_service.list_dispatches(gw, limit=500, **scope)
        workspace_items = list(workspace_dispatches.get('items') or [])
        workspace_active_runs = sum(1 for item in workspace_items if str(item.get('canonical_status') or '').strip().lower() in active_statuses)
        leases_payload = self.list_worker_leases(gw, runtime_id=runtime_id, limit=limit, active_only=None, **scope)
        idempotency_payload = self.list_idempotency_records(gw, runtime_id=runtime_id, limit=limit, active_only=None, **scope)
        leases = list(leases_payload.get('items') or [])
        idempotency = list(idempotency_payload.get('items') or [])
        active_leases = [item for item in leases if bool(item.get('active'))]
        runtime_lock_active = any(str(item.get('lease_type') or '') == 'runtime' and bool(item.get('active')) for item in leases)
        workspace_slots_in_use = sum(1 for item in leases if str(item.get('lease_type') or '') == 'workspace' and bool(item.get('active')))
        in_progress_idempotency = sum(1 for item in idempotency if bool(item.get('active')))
        runtime_run_limit = dispatch_policy.get('max_active_runs')
        workspace_run_limit = dispatch_policy.get('max_active_runs_per_workspace')
        workspace_slot_limit = recovery_schedule.get('workspace_backpressure_limit')

        def _ratio(current: Any, limit_value: Any) -> float | None:
            try:
                if limit_value in (None, 0, '', False):
                    return None
                return float(current) / float(limit_value)
            except Exception:
                return None

        runtime_run_ratio = _ratio(runtime_active_runs, runtime_run_limit)
        workspace_run_ratio = _ratio(workspace_active_runs, workspace_run_limit)
        workspace_slot_ratio = _ratio(workspace_slots_in_use, workspace_slot_limit)
        warnings: list[str] = []
        if runtime_lock_active:
            warnings.append('scheduler:runtime_lock_active')
        if workspace_slot_ratio is not None and workspace_slot_ratio >= 1.0:
            warnings.append('scheduler:workspace_slot_saturated')
        if runtime_run_ratio is not None and runtime_run_ratio >= 1.0:
            warnings.append('dispatch:runtime_backpressure')
        if workspace_run_ratio is not None and workspace_run_ratio >= 1.0:
            warnings.append('dispatch:workspace_backpressure')
        if in_progress_idempotency > 0:
            warnings.append('scheduler:idempotency_in_progress')
        return {
            'ok': True,
            'runtime_id': runtime_id,
            'runtime': runtime,
            'runtime_summary': runtime_summary,
            'leases': leases,
            'idempotency_records': idempotency,
            'summary': {
                'active_leases': len(active_leases),
                'active_job_leases': sum(1 for item in active_leases if str(item.get('lease_type') or '') == 'job'),
                'active_workspace_leases': sum(1 for item in active_leases if str(item.get('lease_type') or '') == 'workspace'),
                'active_runtime_leases': sum(1 for item in active_leases if str(item.get('lease_type') or '') == 'runtime'),
                'runtime_lock_active': runtime_lock_active,
                'workspace_slots_in_use': workspace_slots_in_use,
                'workspace_slot_limit': workspace_slot_limit,
                'workspace_slot_pressure_ratio': workspace_slot_ratio,
                'runtime_active_runs': runtime_active_runs,
                'runtime_run_limit': runtime_run_limit,
                'runtime_run_pressure_ratio': runtime_run_ratio,
                'workspace_active_runs': workspace_active_runs,
                'workspace_run_limit': workspace_run_limit,
                'workspace_run_pressure_ratio': workspace_run_ratio,
                'in_progress_idempotency_count': in_progress_idempotency,
                'idempotency_status_counts': dict((idempotency_payload.get('summary') or {}).get('status_counts') or {}),
                'warnings': warnings,
            },
            'scope': scope,
        }

    @staticmethod
    def _severity_rank(severity: str) -> int:
        normalized = str(severity or '').strip().lower()
        if normalized == 'critical':
            return 3
        if normalized == 'warn':
            return 2
        return 1

    @classmethod
    def _build_alert(
        cls,
        *,
        runtime: dict[str, Any],
        runtime_summary: dict[str, Any],
        severity: str,
        code: str,
        category: str,
        title: str,
        message: str,
        observed_at: float,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        scope = {
            'tenant_id': runtime.get('tenant_id'),
            'workspace_id': runtime.get('workspace_id'),
            'environment': runtime.get('environment'),
        }
        runtime_id = str(runtime.get('runtime_id') or '')
        alert_id = f"{runtime_id}:{code}:{str(int(observed_at))}"
        return {
            'alert_id': alert_id,
            'source': 'openclaw_runtime_slo',
            'status': 'firing',
            'severity': str(severity or 'warn').strip().lower() or 'warn',
            'category': str(category or 'runtime').strip().lower() or 'runtime',
            'code': str(code or '').strip(),
            'title': str(title or code or 'runtime_alert').strip(),
            'message': str(message or '').strip(),
            'runtime_id': runtime_id,
            'runtime_name': str(runtime.get('name') or runtime_id).strip() or runtime_id,
            'runtime_class': str(((runtime_summary.get('metadata') or {}).get('runtime_class')) or '').strip(),
            'policy_pack': str(((runtime_summary.get('metadata') or {}).get('policy_pack')) or '').strip(),
            'scope': scope,
            'observed_at': float(observed_at or time.time()),
            'details': dict(details or {}),
        }

    def evaluate_runtime_alerts(
        self,
        gw,
        *,
        runtime_id: str,
        limit: int = 50,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        detail = self.openclaw_adapter_service.get_runtime(
            gw,
            runtime_id=runtime_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        if not detail.get('ok'):
            return detail
        runtime = dict(detail.get('runtime') or {})
        runtime_summary = dict(detail.get('runtime_summary') or {})
        scope = self._scope(
            tenant_id=runtime.get('tenant_id'),
            workspace_id=runtime.get('workspace_id'),
            environment=runtime.get('environment'),
        )
        health = dict(detail.get('health') or {})
        dispatches = list(detail.get('dispatches') or [])
        concurrency = self.get_runtime_concurrency(gw, runtime_id=runtime_id, limit=max(limit * 3, 30), **scope)
        if not concurrency.get('ok'):
            return concurrency
        concurrency_summary = dict(concurrency.get('summary') or {})
        slo_policy = dict(runtime_summary.get('slo_policy') or {})
        heartbeat_policy = dict(runtime_summary.get('heartbeat_policy') or {})
        now_ts = time.time()
        active_statuses = {'requested', 'accepted', 'queued', 'running'}
        active_runs = [
            item for item in dispatches
            if str(item.get('canonical_status') or '').strip().lower() in active_statuses
        ]
        stale_active_runs = []
        for item in active_runs:
            signal_ts = float(self.openclaw_adapter_service._dispatch_signal_ts(item) or 0.0)
            age_s = max(0.0, now_ts - signal_ts) if signal_ts else now_ts
            if age_s >= float(heartbeat_policy.get('active_run_stale_after_s') or 0.0):
                stale_active_runs.append({'dispatch': item, 'age_s': age_s})
        stale_active_count = len(stale_active_runs)
        stale_active_ratio = (float(stale_active_count) / float(len(active_runs))) if active_runs else 0.0
        alerts: list[dict[str, Any]] = []

        def add_alert(severity: str, code: str, category: str, title: str, message: str, details: dict[str, Any] | None = None, *, observed_at: float | None = None) -> None:
            alerts.append(
                self._build_alert(
                    runtime=runtime,
                    runtime_summary=runtime_summary,
                    severity=severity,
                    code=code,
                    category=category,
                    title=title,
                    message=message,
                    observed_at=float(observed_at if observed_at is not None else now_ts),
                    details=details,
                )
            )

        health_status = str(health.get('status') or 'unknown').strip().lower() or 'unknown'
        checked_at = float(health.get('checked_at') or 0.0)
        heartbeat_age_s = max(0.0, now_ts - checked_at) if checked_at else now_ts
        if health_status == 'degraded':
            severity = str(slo_policy.get('health_degraded_severity') or 'warn')
            add_alert(severity, 'runtime_health_degraded', 'health', 'Runtime degraded', 'El runtime reporta estado degraded.', {'health_status': health_status, 'heartbeat_age_s': heartbeat_age_s})
        elif health_status == 'unhealthy':
            severity = str(slo_policy.get('health_unhealthy_severity') or 'critical')
            add_alert(severity, 'runtime_health_unhealthy', 'health', 'Runtime unhealthy', 'El runtime reporta estado unhealthy.', {'health_status': health_status, 'heartbeat_age_s': heartbeat_age_s})
        if bool(health.get('stale')):
            critical_after = float(slo_policy.get('runtime_stale_critical_after_s') or heartbeat_age_s)
            severity = 'critical' if heartbeat_age_s >= critical_after else 'warn'
            add_alert(
                severity,
                'runtime_heartbeat_stale',
                'health',
                'Runtime heartbeat stale',
                'No hay heartbeat reciente del runtime dentro del SLO esperado.',
                {'heartbeat_age_s': heartbeat_age_s, 'warn_after_s': float(slo_policy.get('runtime_stale_warn_after_s') or 0.0), 'critical_after_s': critical_after},
                observed_at=checked_at or now_ts,
            )

        def _maybe_ratio_alert(value: Any, warn_threshold: Any, critical_threshold: Any, *, code: str, category: str, title: str, message: str, details: dict[str, Any] | None = None) -> None:
            try:
                ratio = float(value)
            except Exception:
                return
            try:
                warn = float(warn_threshold)
            except Exception:
                warn = None
            try:
                critical = float(critical_threshold)
            except Exception:
                critical = None
            if critical is not None and ratio >= critical:
                add_alert('critical', code, category, title, message, {**dict(details or {}), 'ratio': ratio, 'threshold': critical})
            elif warn is not None and ratio >= warn:
                add_alert('warn', code, category, title, message, {**dict(details or {}), 'ratio': ratio, 'threshold': warn})

        _maybe_ratio_alert(
            concurrency_summary.get('runtime_run_pressure_ratio'),
            slo_policy.get('runtime_run_warn_ratio'),
            slo_policy.get('runtime_run_critical_ratio'),
            code='runtime_run_saturation',
            category='saturation',
            title='Runtime saturation',
            message='El runtime ha alcanzado presión elevada de runs activos.',
            details={'active_runs': concurrency_summary.get('runtime_active_runs'), 'limit': concurrency_summary.get('runtime_run_limit')},
        )
        _maybe_ratio_alert(
            concurrency_summary.get('workspace_run_pressure_ratio'),
            slo_policy.get('workspace_run_warn_ratio'),
            slo_policy.get('workspace_run_critical_ratio'),
            code='workspace_run_saturation',
            category='saturation',
            title='Workspace saturation',
            message='El workspace ha alcanzado presión elevada de runs activos para este runtime.',
            details={'active_runs': concurrency_summary.get('workspace_active_runs'), 'limit': concurrency_summary.get('workspace_run_limit')},
        )
        _maybe_ratio_alert(
            concurrency_summary.get('workspace_slot_pressure_ratio'),
            slo_policy.get('workspace_slot_warn_ratio'),
            slo_policy.get('workspace_slot_critical_ratio'),
            code='workspace_scheduler_saturation',
            category='saturation',
            title='Workspace scheduler saturation',
            message='Los slots de scheduler del workspace están bajo presión.',
            details={'slots_in_use': concurrency_summary.get('workspace_slots_in_use'), 'limit': concurrency_summary.get('workspace_slot_limit')},
        )

        stale_warn_ratio = float(slo_policy.get('stale_active_warn_ratio') or 0.0)
        stale_critical_ratio = float(slo_policy.get('stale_active_critical_ratio') or stale_warn_ratio)
        stale_warn_count = int(slo_policy.get('stale_active_warn_count') or 1)
        stale_critical_count = int(slo_policy.get('stale_active_critical_count') or stale_warn_count)
        if stale_active_count >= stale_critical_count or (active_runs and stale_active_ratio >= stale_critical_ratio):
            add_alert('critical', 'stale_run_pressure', 'staleness', 'Stale-run pressure', 'Hay demasiados runs activos sin señales recientes.', {'stale_active_count': stale_active_count, 'active_count': len(active_runs), 'stale_active_ratio': stale_active_ratio, 'sample_dispatch_ids': [str(item['dispatch'].get('dispatch_id') or '') for item in stale_active_runs[:5]]})
        elif stale_active_count >= stale_warn_count or (active_runs and stale_active_ratio >= stale_warn_ratio):
            add_alert('warn', 'stale_run_pressure', 'staleness', 'Stale-run pressure', 'Hay runs activos acercándose al umbral de staleness.', {'stale_active_count': stale_active_count, 'active_count': len(active_runs), 'stale_active_ratio': stale_active_ratio, 'sample_dispatch_ids': [str(item['dispatch'].get('dispatch_id') or '') for item in stale_active_runs[:5]]})

        active_leases = [item for item in list(concurrency.get('leases') or []) if bool(item.get('active'))]
        long_warn_after = float(slo_policy.get('long_lease_warn_after_s') or 0.0)
        long_critical_after = float(slo_policy.get('long_lease_critical_after_s') or long_warn_after)
        long_warn = [
            item for item in active_leases
            if max(float(item.get('held_for_s') or 0.0), float(item.get('updated_age_s') or 0.0)) >= long_warn_after
        ]
        long_critical = [
            item for item in active_leases
            if max(float(item.get('held_for_s') or 0.0), float(item.get('updated_age_s') or 0.0)) >= long_critical_after
        ]
        if len(long_critical) >= int(slo_policy.get('long_lease_critical_count') or 1):
            add_alert('critical', 'worker_leases_too_long', 'locking', 'Long-held worker leases', 'Hay locks de worker activos durante demasiado tiempo.', {'count': len(long_critical), 'lease_types': sorted({str(item.get('lease_type') or 'other') for item in long_critical}), 'max_held_for_s': max((float(item.get('held_for_s') or 0.0) for item in long_critical), default=0.0)})
        elif len(long_warn) >= int(slo_policy.get('long_lease_warn_count') or 1):
            add_alert('warn', 'worker_leases_too_long', 'locking', 'Long-held worker leases', 'Hay locks de worker que se están prolongando más de lo esperado.', {'count': len(long_warn), 'lease_types': sorted({str(item.get('lease_type') or 'other') for item in long_warn}), 'max_held_for_s': max((float(item.get('held_for_s') or 0.0) for item in long_warn), default=0.0)})

        active_records = [item for item in list(concurrency.get('idempotency_records') or []) if bool(item.get('active'))]
        idem_warn_after = float(slo_policy.get('stuck_idempotency_warn_after_s') or 0.0)
        idem_critical_after = float(slo_policy.get('stuck_idempotency_critical_after_s') or idem_warn_after)
        idem_warn = [item for item in active_records if float(item.get('updated_age_s') or 0.0) >= idem_warn_after]
        idem_critical = [item for item in active_records if float(item.get('updated_age_s') or 0.0) >= idem_critical_after]
        if len(idem_critical) >= int(slo_policy.get('idempotency_critical_count') or 1):
            add_alert('critical', 'idempotency_records_stuck', 'idempotency', 'Idempotency records stuck', 'Hay registros de idempotencia in_progress atascados.', {'count': len(idem_critical), 'max_updated_age_s': max((float(item.get('updated_age_s') or 0.0) for item in idem_critical), default=0.0), 'keys': [str(item.get('idempotency_key') or '') for item in idem_critical[:5]]})
        elif len(idem_warn) >= int(slo_policy.get('idempotency_warn_count') or 1):
            add_alert('warn', 'idempotency_records_stuck', 'idempotency', 'Idempotency records stuck', 'Hay registros de idempotencia in_progress que superan el SLO de actualización.', {'count': len(idem_warn), 'max_updated_age_s': max((float(item.get('updated_age_s') or 0.0) for item in idem_warn), default=0.0), 'keys': [str(item.get('idempotency_key') or '') for item in idem_warn[:5]]})

        alerts.sort(key=lambda item: (-self._severity_rank(str(item.get('severity') or 'info')), -float(item.get('observed_at') or 0.0), str(item.get('code') or '')))
        alerts = alerts[: max(1, int(limit))]
        governance_policy = self._effective_alert_governance_policy(runtime_summary=runtime_summary, scope={**scope, 'runtime_class': str((((runtime_summary.get('metadata') or {}).get('runtime_class')) or ''))})
        governed_alerts: list[dict[str, Any]] = []
        for item in alerts:
            governed = dict(item)
            governed['governance'] = self._alert_governance_decision(runtime_summary=runtime_summary, scope=scope, alert=governed, alerts=alerts, now_ts=now_ts)
            governed_alerts.append(governed)
        alerts = [self._enrich_alert_workflow(gw, alert=item, runtime_summary=runtime_summary) for item in governed_alerts]
        severity_counts: dict[str, int] = {}
        category_counts: dict[str, int] = {}
        code_counts: dict[str, int] = {}
        workflow_status_counts: dict[str, int] = {}
        for item in alerts:
            severity = str(item.get('severity') or 'warn')
            category = str(item.get('category') or 'runtime')
            code = str(item.get('code') or 'runtime_alert')
            workflow_status = str(((item.get('workflow') or {}).get('status')) or 'open')
            severity_counts[severity] = severity_counts.get(severity, 0) + 1
            category_counts[category] = category_counts.get(category, 0) + 1
            code_counts[code] = code_counts.get(code, 0) + 1
            workflow_status_counts[workflow_status] = workflow_status_counts.get(workflow_status, 0) + 1
        highest_severity = None
        if alerts:
            highest_severity = sorted([str(item.get('severity') or 'warn') for item in alerts], key=self._severity_rank, reverse=True)[0]
        governance_reason_counts: dict[str, int] = {}
        for item in alerts:
            for reason in list((((item.get('workflow') or {}).get('governance') or {}).get('reasons') or [])):
                governance_reason_counts[str(reason)] = governance_reason_counts.get(str(reason), 0) + 1
        return {
            'ok': True,
            'runtime_id': runtime_id,
            'runtime': runtime,
            'runtime_summary': runtime_summary,
            'items': alerts,
            'summary': {
                'count': len(alerts),
                'critical_count': severity_counts.get('critical', 0),
                'warn_count': severity_counts.get('warn', 0),
                'highest_severity': highest_severity,
                'severity_counts': severity_counts,
                'category_counts': category_counts,
                'code_counts': code_counts,
                'workflow_status_counts': workflow_status_counts,
                'acked_count': sum(1 for item in alerts if bool(((item.get('workflow') or {}).get('acked')))),
                'silenced_count': sum(1 for item in alerts if bool(((item.get('workflow') or {}).get('silenced')))),
                'suppressed_count': sum(1 for item in alerts if bool(((item.get('workflow') or {}).get('suppressed')))),
                'escalated_count': sum(1 for item in alerts if bool(((item.get('workflow') or {}).get('escalated')))),
                'governance_suppressed_count': sum(1 for item in alerts if bool((((item.get('workflow') or {}).get('governance') or {}).get('suppressed')))),
                'governance_scheduled_count': sum(1 for item in alerts if bool((((item.get('workflow') or {}).get('governance') or {}).get('scheduled')))),
                'governance_reason_counts': governance_reason_counts,
                'active_override_count': len(list(governance_policy.get('applied_overrides') or [])),
                'quiet_hours_active': bool(any(bool((((item.get('workflow') or {}).get('governance') or {}).get('quiet_hours') or {}).get('active')) for item in alerts)),
                'maintenance_active': bool(any(bool((((item.get('workflow') or {}).get('governance') or {}).get('maintenance') or {}).get('active')) for item in alerts)),
                'storm_active': bool(any(bool((((item.get('workflow') or {}).get('governance') or {}).get('storm') or {}).get('active')) for item in alerts)),
                'stale_active_count': stale_active_count,
                'stale_active_ratio': stale_active_ratio,
            },
            'governance_policy': governance_policy,
            'scope': scope,
        }

    def list_runtime_alerts(
        self,
        gw,
        *,
        limit: int = 100,
        severity: str | None = None,
        runtime_id: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        if runtime_id:
            payload = self.evaluate_runtime_alerts(gw, runtime_id=runtime_id, limit=limit, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
            if not payload.get('ok'):
                return payload
            items = list(payload.get('items') or [])
        else:
            runtimes_payload = self.openclaw_adapter_service.list_runtimes(gw, limit=max(limit, 100), tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
            items = []
            for runtime in list(runtimes_payload.get('items') or []):
                rid = str(runtime.get('runtime_id') or '').strip()
                if not rid:
                    continue
                payload = self.evaluate_runtime_alerts(
                    gw,
                    runtime_id=rid,
                    limit=max(10, min(limit, 50)),
                    tenant_id=runtime.get('tenant_id') or tenant_id,
                    workspace_id=runtime.get('workspace_id') or workspace_id,
                    environment=runtime.get('environment') or environment,
                )
                if not payload.get('ok'):
                    continue
                items.extend(list(payload.get('items') or []))
            items.sort(key=lambda item: (-self._severity_rank(str(item.get('severity') or 'info')), -float(item.get('observed_at') or 0.0), str(item.get('runtime_name') or '')))
            items = items[: max(1, int(limit))]
        normalized_severity = str(severity or '').strip().lower()
        if normalized_severity:
            items = [item for item in items if str(item.get('severity') or '').strip().lower() == normalized_severity]
        severity_counts: dict[str, int] = {}
        runtime_counts: dict[str, int] = {}
        code_counts: dict[str, int] = {}
        workflow_status_counts: dict[str, int] = {}
        for item in items:
            sev = str(item.get('severity') or 'warn')
            rid = str(item.get('runtime_id') or '')
            code = str(item.get('code') or 'runtime_alert')
            workflow_status = str(((item.get('workflow') or {}).get('status')) or 'open')
            severity_counts[sev] = severity_counts.get(sev, 0) + 1
            runtime_counts[rid] = runtime_counts.get(rid, 0) + 1
            code_counts[code] = code_counts.get(code, 0) + 1
            workflow_status_counts[workflow_status] = workflow_status_counts.get(workflow_status, 0) + 1
        return {
            'ok': True,
            'items': items,
            'summary': {
                'count': len(items),
                'critical_count': severity_counts.get('critical', 0),
                'warn_count': severity_counts.get('warn', 0),
                'severity_counts': severity_counts,
                'runtime_count': len(runtime_counts),
                'code_counts': code_counts,
                'workflow_status_counts': workflow_status_counts,
                'acked_count': sum(1 for item in items if bool(((item.get('workflow') or {}).get('acked')))),
                'silenced_count': sum(1 for item in items if bool(((item.get('workflow') or {}).get('silenced')))),
                'suppressed_count': sum(1 for item in items if bool(((item.get('workflow') or {}).get('suppressed')))),
                'escalated_count': sum(1 for item in items if bool(((item.get('workflow') or {}).get('escalated')))),
                'runtime_id': runtime_id,
                'severity': normalized_severity or None,
            },
            'scope': self._scope(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment),
        }

    def list_runtime_alert_states(
        self,
        gw,
        *,
        limit: int = 100,
        runtime_id: str | None = None,
        workflow_status: str | None = None,
        severity: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        scope = self._scope(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        items = [
            self._decorate_alert_state(item)
            for item in gw.audit.list_runtime_alert_states(
                runtime_id=runtime_id,
                workflow_status=workflow_status,
                severity=severity,
                limit=limit,
                tenant_id=scope.get('tenant_id'),
                workspace_id=scope.get('workspace_id'),
                environment=scope.get('environment'),
            )
        ]
        status_counts: dict[str, int] = {}
        for item in items:
            status_key = str(item.get('workflow_status') or 'open')
            status_counts[status_key] = status_counts.get(status_key, 0) + 1
        return {
            'ok': True,
            'items': items,
            'summary': {
                'count': len(items),
                'runtime_id': runtime_id,
                'workflow_status': workflow_status,
                'severity': severity,
                'status_counts': status_counts,
                'silenced_count': sum(1 for item in items if bool(item.get('silenced'))),
                'escalated_count': sum(1 for item in items if bool(item.get('escalated'))),
                'acked_count': sum(1 for item in items if bool(item.get('acked'))),
            },
            'scope': scope,
        }

