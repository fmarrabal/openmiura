from __future__ import annotations

import time
from typing import Any




class OpenClawRuntimeRolloutSummariesMixin:
    @staticmethod
    def _alert_workflow_policy(runtime_summary: dict[str, Any] | None) -> dict[str, Any]:
        metadata = dict((runtime_summary or {}).get('metadata') or {})
        raw = dict(metadata.get('alert_workflow_policy') or {})
        try:
            max_silence_s = int(raw.get('max_silence_s') or 86400)
        except Exception:
            max_silence_s = 86400
        try:
            default_silence_s = int(raw.get('default_silence_s') or min(3600, max_silence_s))
        except Exception:
            default_silence_s = min(3600, max_silence_s)
        try:
            escalation_max_level = int(raw.get('escalation_max_level') or 3)
        except Exception:
            escalation_max_level = 3
        return {
            **raw,
            'max_silence_s': max(60, max_silence_s),
            'default_silence_s': max(60, min(max_silence_s, default_silence_s)),
            'escalation_max_level': max(1, escalation_max_level),
            'allow_ack': bool(raw.get('allow_ack', True)),
            'allow_silence': bool(raw.get('allow_silence', True)),
            'allow_escalate': bool(raw.get('allow_escalate', True)),
        }


    @staticmethod
    def _alert_escalation_policy(runtime_summary: dict[str, Any] | None) -> dict[str, Any]:
        raw = dict((runtime_summary or {}).get('alert_escalation_policy') or {})
        try:
            min_escalation_level = int(raw.get('min_escalation_level') or 1)
        except Exception:
            min_escalation_level = 1
        try:
            ttl_s = int(raw.get('ttl_s') or 1800)
        except Exception:
            ttl_s = 1800
        return {
            **raw,
            'enabled': bool(raw.get('enabled', bool(raw))),
            'default_requires_approval': bool(raw.get('default_requires_approval', False)),
            'required_severities': [str(item).strip().lower() for item in list(raw.get('required_severities') or []) if str(item).strip()],
            'required_alert_codes': [str(item).strip() for item in list(raw.get('required_alert_codes') or []) if str(item).strip()],
            'required_target_ids': [str(item).strip() for item in list(raw.get('required_target_ids') or []) if str(item).strip()],
            'required_target_types': [str(item).strip().lower() for item in list(raw.get('required_target_types') or []) if str(item).strip()],
            'min_escalation_level': max(1, min_escalation_level),
            'requested_role': str(raw.get('requested_role') or 'admin').strip() or 'admin',
            'ttl_s': max(60, ttl_s),
            'auto_dispatch_on_approval': bool(raw.get('auto_dispatch_on_approval', True)),
        }


    @staticmethod
    def _notification_budget_policy(runtime_summary: dict[str, Any] | None) -> dict[str, Any]:
        raw = dict((runtime_summary or {}).get('notification_budget_policy') or {})
        try:
            window_s = int(raw.get('window_s') or 300)
        except Exception:
            window_s = 300
        try:
            runtime_limit = int(raw.get('runtime_limit') or 0)
        except Exception:
            runtime_limit = 0
        try:
            workspace_limit = int(raw.get('workspace_limit') or 0)
        except Exception:
            workspace_limit = 0
        try:
            schedule_after_s = int(raw.get('schedule_after_s') or 60)
        except Exception:
            schedule_after_s = 60
        on_limit = str(raw.get('on_limit') or 'schedule').strip().lower() or 'schedule'
        if on_limit not in {'schedule', 'drop'}:
            on_limit = 'schedule'
        count_statuses = [str(item).strip().lower() for item in list(raw.get('count_statuses') or ['delivered', 'queued', 'pending', 'scheduled']) if str(item).strip()]
        target_type_limits = {}
        for key, value in dict(raw.get('target_type_limits') or {}).items():
            try:
                target_type_limits[str(key).strip().lower()] = max(0, int(value or 0))
            except Exception:
                continue
        target_id_limits = {}
        for key, value in dict(raw.get('target_id_limits') or {}).items():
            try:
                target_id_limits[str(key).strip()] = max(0, int(value or 0))
            except Exception:
                continue
        return {
            **raw,
            'enabled': bool(raw.get('enabled', bool(raw))),
            'window_s': max(1, window_s),
            'runtime_limit': max(0, runtime_limit),
            'workspace_limit': max(0, workspace_limit),
            'on_limit': on_limit,
            'schedule_after_s': max(0, schedule_after_s),
            'count_statuses': count_statuses,
            'target_type_limits': target_type_limits,
            'target_id_limits': target_id_limits,
        }


    @classmethod
    def _alert_governance_policy(cls, runtime_summary: dict[str, Any] | None) -> dict[str, Any]:
        raw = dict((runtime_summary or {}).get('alert_governance_policy') or {})
        quiet = dict(raw.get('quiet_hours') or {})
        quiet_action = str(quiet.get('action') or 'schedule').strip().lower() or 'schedule'
        if quiet_action not in {'allow', 'schedule', 'suppress'}:
            quiet_action = 'schedule'
        maintenance_windows: list[dict[str, Any]] = []
        for idx, item in enumerate(list(raw.get('maintenance_windows') or [])):
            if not isinstance(item, dict):
                continue
            window = dict(item)
            window.setdefault('window_id', f'maintenance-{idx + 1}')
            action = str(window.get('action') or 'suppress').strip().lower() or 'suppress'
            if action not in {'allow', 'schedule', 'suppress'}:
                action = 'suppress'
            window['action'] = action
            maintenance_windows.append(window)
        overrides: list[dict[str, Any]] = []
        for idx, item in enumerate(list(raw.get('override_policies') or raw.get('overrides') or [])):
            if not isinstance(item, dict):
                continue
            entry = dict(item)
            entry.setdefault('policy_id', f'override-{idx + 1}')
            entry.setdefault('enabled', True)
            overrides.append(entry)
        storm = dict(raw.get('storm_policy') or {})
        storm_action = str(storm.get('action') or 'suppress').strip().lower() or 'suppress'
        if storm_action not in {'allow', 'schedule', 'suppress'}:
            storm_action = 'suppress'
        return {
            **raw,
            'enabled': bool(raw.get('enabled', True)),
            'default_timezone': str(raw.get('default_timezone') or 'UTC').strip() or 'UTC',
            'quiet_hours': {
                **quiet,
                'enabled': bool(quiet.get('enabled', bool(quiet))),
                'timezone': str(quiet.get('timezone') or raw.get('default_timezone') or 'UTC').strip() or 'UTC',
                'weekdays': cls._normalize_weekdays(list(quiet.get('weekdays') or quiet.get('days') or [])),
                'start_time': str(quiet.get('start_time') or '22:00').strip() or '22:00',
                'end_time': str(quiet.get('end_time') or '06:00').strip() or '06:00',
                'action': quiet_action,
                'allow_severities': [str(item).strip().lower() for item in list(quiet.get('allow_severities') or []) if str(item).strip()],
                'allow_alert_codes': [str(item).strip() for item in list(quiet.get('allow_alert_codes') or []) if str(item).strip()],
                'suppress_for_s': max(60, int(quiet.get('suppress_for_s') or 900)),
            },
            'maintenance_windows': maintenance_windows,
            'override_policies': overrides,
            'storm_policy': {
                **storm,
                'enabled': bool(storm.get('enabled', bool(storm))),
                'action': storm_action,
                'active_alert_threshold': max(0, int(storm.get('active_alert_threshold') or 0)),
                'per_severity_thresholds': {str(k).strip().lower(): max(0, int(v or 0)) for k, v in dict(storm.get('per_severity_thresholds') or {}).items() if str(k).strip()},
                'suppress_severities': [str(item).strip().lower() for item in list(storm.get('suppress_severities') or ['warn', 'info']) if str(item).strip()],
                'allow_alert_codes': [str(item).strip() for item in list(storm.get('allow_alert_codes') or []) if str(item).strip()],
                'suppress_for_s': max(60, int(storm.get('suppress_for_s') or 600)),
            },
        }


    def _effective_alert_governance_policy(self, *, runtime_summary: dict[str, Any] | None, scope: dict[str, Any] | None) -> dict[str, Any]:
        base = self._alert_governance_policy(runtime_summary)
        effective = dict(base)
        applied: list[str] = []
        match_scope = dict(scope or {})
        match_scope.setdefault('runtime_class', str((((runtime_summary or {}).get('metadata') or {}).get('runtime_class')) or '').strip())
        for item in list(base.get('override_policies') or []):
            if not bool(item.get('enabled', True)):
                continue
            if not self._scope_matches(dict(item.get('match') or {}), match_scope):
                continue
            patch: dict[str, Any] = {}
            for key in ('quiet_hours', 'storm_policy', 'default_timezone'):
                if key in item:
                    patch[key] = item.get(key)
            if 'maintenance_windows' in item:
                patch['maintenance_windows'] = list(item.get('maintenance_windows') or [])
            if patch:
                effective = self.openclaw_adapter_service._deep_merge(effective, patch)
                applied.append(str(item.get('policy_id') or 'override').strip())
        normalized = self._alert_governance_policy({'alert_governance_policy': effective})
        normalized['applied_overrides'] = applied
        return normalized


    def _alert_governance_decision(self, *, runtime_summary: dict[str, Any], scope: dict[str, Any], alert: dict[str, Any], alerts: list[dict[str, Any]], now_ts: float) -> dict[str, Any]:
        policy = self._effective_alert_governance_policy(runtime_summary=runtime_summary, scope=scope)
        if not bool(policy.get('enabled', True)):
            return {'policy': policy, 'status': 'allow', 'suppressed': False, 'scheduled': False, 'next_allowed_at': None, 'reasons': [], 'quiet_hours': {'active': False}, 'maintenance': {'active': False, 'windows': []}, 'storm': {'active': False}, 'active_override_count': len(list(policy.get('applied_overrides') or []))}
        quiet = self._quiet_hours_decision(policy=policy, alert=alert, now_ts=now_ts)
        maintenance = self._maintenance_decision(policy=policy, alert=alert, now_ts=now_ts)
        storm = self._storm_decision(policy=policy, alert=alert, alerts=alerts, now_ts=now_ts)
        suppressed = bool(maintenance.get('suppressed')) or bool(quiet.get('suppressed')) or bool(storm.get('suppressed'))
        scheduled = (not suppressed) and (bool(maintenance.get('scheduled')) or bool(quiet.get('scheduled')) or bool(storm.get('scheduled')))
        next_candidates = [item for item in [maintenance.get('next_allowed_at'), quiet.get('next_allowed_at'), storm.get('next_allowed_at')] if item]
        next_allowed_at = max(next_candidates) if next_candidates and scheduled else None
        reasons: list[str] = []
        for source in (maintenance, quiet, storm):
            for reason in list(source.get('reasons') or []):
                if reason not in reasons:
                    reasons.append(reason)
        status = 'suppressed' if suppressed else ('scheduled' if scheduled else 'allow')
        return {
            'policy': policy,
            'status': status,
            'suppressed': suppressed,
            'scheduled': scheduled,
            'next_allowed_at': next_allowed_at,
            'reasons': reasons,
            'quiet_hours': quiet,
            'maintenance': maintenance,
            'storm': storm,
            'active_override_count': len(list(policy.get('applied_overrides') or [])),
        }


    @staticmethod
    def _governance_release_policy(runtime_summary: dict[str, Any] | None) -> dict[str, Any]:
        raw = dict((runtime_summary or {}).get('governance_release_policy') or {})
        try:
            ttl_s = int(raw.get('ttl_s') or 3600)
        except Exception:
            ttl_s = 3600
        try:
            affected_threshold = int(raw.get('approval_on_affected_count_ge') or 0)
        except Exception:
            affected_threshold = 0
        return {
            **raw,
            'approval_required': bool(raw.get('approval_required', False)),
            'requested_role': str(raw.get('requested_role') or 'admin').strip() or 'admin',
            'ttl_s': max(60, ttl_s),
            'auto_activate_on_approval': bool(raw.get('auto_activate_on_approval', True)),
            'require_signature': bool(raw.get('require_signature', True)),
            'signer_key_id': str(raw.get('signer_key_id') or 'openmiura-local').strip() or 'openmiura-local',
            'approval_on_affected_count_ge': max(0, affected_threshold),
            'approval_on_critical_change': bool(raw.get('approval_on_critical_change', False)),
            'critical_changed_keys': [
                str(item).strip()
                for item in list(raw.get('critical_changed_keys') or ['quiet_hours', 'maintenance_windows', 'storm_policy', 'override_policies'])
                if str(item).strip()
            ],
        }


    @staticmethod
    def _notification_policy(runtime_summary: dict[str, Any] | None) -> dict[str, Any]:
        raw = dict((runtime_summary or {}).get('alert_notification_policy') or {})
        try:
            dedupe_window_s = int(raw.get('dedupe_window_s') or 300)
        except Exception:
            dedupe_window_s = 300
        try:
            max_targets_per_dispatch = int(raw.get('max_targets_per_dispatch') or 10)
        except Exception:
            max_targets_per_dispatch = 10
        return {
            **raw,
            'dispatch_on_escalate': bool(raw.get('dispatch_on_escalate', True)),
            'dispatch_on_ack': bool(raw.get('dispatch_on_ack', False)),
            'dispatch_on_silence': bool(raw.get('dispatch_on_silence', False)),
            'queue_fallback_enabled': bool(raw.get('queue_fallback_enabled', True)),
            'dedupe_window_s': max(0, dedupe_window_s),
            'max_targets_per_dispatch': max(1, max_targets_per_dispatch),
            'default_queue_name': str(raw.get('default_queue_name') or 'runtime-alerts').strip() or 'runtime-alerts',
            'default_app_target_path': str(raw.get('default_app_target_path') or '/ui/?tab=operator').strip() or '/ui/?tab=operator',
            'default_target_types': [str(item).strip().lower() for item in list(raw.get('default_target_types') or []) if str(item).strip()],
        }


    @staticmethod
    def _notification_targets(runtime_summary: dict[str, Any] | None) -> list[dict[str, Any]]:
        items = list((runtime_summary or {}).get('alert_notification_targets') or [])
        out: list[dict[str, Any]] = []
        for idx, raw in enumerate(items):
            if not isinstance(raw, dict):
                continue
            target_type = str(raw.get('type') or raw.get('target_type') or '').strip().lower()
            if target_type not in {'slack', 'webhook', 'app', 'queue', 'email'}:
                continue
            out.append({
                'target_id': str(raw.get('target_id') or raw.get('id') or f'{target_type}-{idx + 1}').strip(),
                'type': target_type,
                'enabled': bool(raw.get('enabled', True)),
                'channel': str(raw.get('channel') or '').strip(),
                'thread_ts': str(raw.get('thread_ts') or '').strip(),
                'url': str(raw.get('url') or raw.get('webhook_url') or '').strip(),
                'headers': dict(raw.get('headers') or {}),
                'installation_id': str(raw.get('installation_id') or '').strip(),
                'target_path': str(raw.get('target_path') or '').strip(),
                'queue_name': str(raw.get('queue_name') or raw.get('queue') or '').strip(),
                'email_to': str(raw.get('email_to') or raw.get('to') or '').strip(),
                'subject_prefix': str(raw.get('subject_prefix') or '').strip(),
                'min_escalation_level': max(0, int(raw.get('min_escalation_level') or 0)),
                'severities': [str(item).strip().lower() for item in list(raw.get('severities') or []) if str(item).strip()],
                'alert_codes': [str(item).strip() for item in list(raw.get('alert_codes') or []) if str(item).strip()],
                'workflow_actions': [str(item).strip().lower() for item in list(raw.get('workflow_actions') or ['escalate']) if str(item).strip()],
                'auth_secret_ref': str(raw.get('auth_secret_ref') or '').strip(),
                'metadata': dict(raw.get('metadata') or {}),
            })
        return out


    @staticmethod
    def _alert_routing_policy(runtime_summary: dict[str, Any] | None) -> dict[str, Any]:
        raw = dict((runtime_summary or {}).get('alert_routing_policy') or {})
        try:
            default_max_retries = int(raw.get('default_max_retries') or 0)
        except Exception:
            default_max_retries = 0
        try:
            default_retry_backoff_s = int(raw.get('default_retry_backoff_s') or 300)
        except Exception:
            default_retry_backoff_s = 300
        def _list_str(values: Any, *, lower: bool = False) -> list[str]:
            out: list[str] = []
            for item in list(values or []):
                value = str(item).strip()
                if not value:
                    continue
                out.append(value.lower() if lower else value)
            return out
        rules: list[dict[str, Any]] = []
        for idx, item in enumerate(list(raw.get('rules') or [])):
            if not isinstance(item, dict):
                continue
            try:
                priority = int(item.get('priority') or (idx + 1))
            except Exception:
                priority = idx + 1
            try:
                min_level = int(item.get('min_escalation_level') or 0)
            except Exception:
                min_level = 0
            max_level_raw = item.get('max_escalation_level')
            try:
                max_level = int(max_level_raw) if max_level_raw is not None else None
            except Exception:
                max_level = None
            try:
                delay_s = int(item.get('delay_s') or 0)
            except Exception:
                delay_s = 0
            try:
                max_retries = int(item.get('max_retries') if item.get('max_retries') is not None else default_max_retries)
            except Exception:
                max_retries = default_max_retries
            try:
                retry_backoff_s = int(item.get('retry_backoff_s') if item.get('retry_backoff_s') is not None else default_retry_backoff_s)
            except Exception:
                retry_backoff_s = default_retry_backoff_s
            rules.append({
                **dict(item or {}),
                'rule_id': str(item.get('rule_id') or f'route-rule-{idx + 1}').strip(),
                'enabled': bool(item.get('enabled', True)),
                'priority': priority,
                'workflow_actions': _list_str(item.get('workflow_actions') or [], lower=True),
                'severities': _list_str(item.get('severities') or [], lower=True),
                'alert_codes': _list_str(item.get('alert_codes') or []),
                'tenant_ids': _list_str(item.get('tenant_ids') or []),
                'workspace_ids': _list_str(item.get('workspace_ids') or []),
                'environments': _list_str(item.get('environments') or []),
                'target_ids': _list_str(item.get('target_ids') or []),
                'target_types': _list_str(item.get('target_types') or [], lower=True),
                'chain_id': str(item.get('chain_id') or '').strip(),
                'min_escalation_level': max(0, min_level),
                'max_escalation_level': max_level,
                'delay_s': max(0, delay_s),
                'max_retries': max(0, max_retries),
                'retry_backoff_s': max(0, retry_backoff_s),
                'stop_after_match': bool(item.get('stop_after_match', False)),
                'time_windows': list(item.get('time_windows') or []),
            })
        chains: list[dict[str, Any]] = []
        for idx, item in enumerate(list(raw.get('escalation_chains') or raw.get('chains') or [])):
            if not isinstance(item, dict):
                continue
            steps: list[dict[str, Any]] = []
            for step_idx, raw_step in enumerate(list(item.get('steps') or [])):
                if not isinstance(raw_step, dict):
                    continue
                try:
                    step_delay_s = int(raw_step.get('delay_s') or 0)
                except Exception:
                    step_delay_s = 0
                try:
                    step_max_retries = int(raw_step.get('max_retries') if raw_step.get('max_retries') is not None else default_max_retries)
                except Exception:
                    step_max_retries = default_max_retries
                try:
                    step_retry_backoff_s = int(raw_step.get('retry_backoff_s') if raw_step.get('retry_backoff_s') is not None else default_retry_backoff_s)
                except Exception:
                    step_retry_backoff_s = default_retry_backoff_s
                steps.append({
                    **dict(raw_step or {}),
                    'step_id': str(raw_step.get('step_id') or f'step-{step_idx + 1}').strip(),
                    'enabled': bool(raw_step.get('enabled', True)),
                    'workflow_action': str(raw_step.get('workflow_action') or '').strip().lower(),
                    'target_ids': _list_str(raw_step.get('target_ids') or []),
                    'target_types': _list_str(raw_step.get('target_types') or [], lower=True),
                    'delay_s': max(0, step_delay_s),
                    'max_retries': max(0, step_max_retries),
                    'retry_backoff_s': max(0, step_retry_backoff_s),
                    'time_windows': list(raw_step.get('time_windows') or []),
                })
            chains.append({
                **dict(item or {}),
                'chain_id': str(item.get('chain_id') or f'chain-{idx + 1}').strip(),
                'enabled': bool(item.get('enabled', True)),
                'steps': steps,
            })
        return {
            **raw,
            'enabled': bool(raw.get('enabled', True)),
            'default_timezone': str(raw.get('default_timezone') or 'UTC').strip() or 'UTC',
            'default_max_retries': max(0, default_max_retries),
            'default_retry_backoff_s': max(0, default_retry_backoff_s),
            'rules': rules,
            'escalation_chains': chains,
        }


    @staticmethod
    def _notification_payload(*, alert: dict[str, Any], runtime_summary: dict[str, Any], workflow_action: str, actor: str, reason: str = '', escalation_level: int = 0) -> dict[str, Any]:
        scope = dict(alert.get('scope') or {})
        runtime_scope = dict((runtime_summary or {}).get('scope') or {})
        runtime_name = str((runtime_summary or {}).get('name') or (runtime_summary or {}).get('runtime_id') or '').strip()
        severity = str(alert.get('severity') or '').strip().upper() or 'WARN'
        title = str(alert.get('title') or alert.get('code') or 'Runtime alert').strip()
        subject = f'[{severity}] {runtime_name}: {title}'
        lines = [subject]
        lines.append(f"Runtime: {runtime_name} ({(runtime_summary or {}).get('runtime_id') or ''})")
        lines.append(f"Scope: {runtime_scope.get('tenant_id') or scope.get('tenant_id') or '-'} / {runtime_scope.get('workspace_id') or scope.get('workspace_id') or '-'} / {runtime_scope.get('environment') or scope.get('environment') or '-'}")
        lines.append(f"Workflow: {workflow_action}")
        if escalation_level:
            lines.append(f"Escalation level: {escalation_level}")
        if reason:
            lines.append(f"Reason: {reason}")
        lines.append(f"Actor: {actor}")
        return {
            'subject': subject,
            'title': title,
            'text': '\n'.join(lines),
            'body': '\n'.join(lines + [''] + ([str(alert.get('message') or '').strip()] if str(alert.get('message') or '').strip() else [])),
            'json': {
                'alert': {
                    'alert_key': str(alert.get('alert_key') or ''),
                    'code': str(alert.get('code') or ''),
                    'title': title,
                    'severity': str(alert.get('severity') or ''),
                    'message': str(alert.get('message') or ''),
                    'observed_at': alert.get('observed_at'),
                    'workflow': dict(alert.get('workflow') or {}),
                },
                'runtime': {
                    'runtime_id': (runtime_summary or {}).get('runtime_id'),
                    'name': (runtime_summary or {}).get('name'),
                    'scope': runtime_scope or scope,
                    'transport': (runtime_summary or {}).get('transport'),
                    'dispatch_policy': dict((runtime_summary or {}).get('dispatch_policy') or {}),
                },
                'workflow_action': workflow_action,
                'escalation_level': escalation_level,
                'actor': actor,
                'reason': reason,
                'generated_at': time.time(),
            },
        }
