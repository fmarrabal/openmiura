from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from typing import Any


class OpenClawRuntimeAlertNotificationsMixin:
    @staticmethod
    def _notification_urlopen(req, timeout: float = 10.0):
        scheduler_module = sys.modules.get('openmiura.application.openclaw.scheduler')
        if scheduler_module is not None:
            scheduler_urllib = getattr(scheduler_module, 'urllib', None)
            if scheduler_urllib is not None and hasattr(getattr(scheduler_urllib, 'request', None), 'urlopen'):
                return scheduler_urllib.request.urlopen(req, timeout=timeout)
        return urllib.request.urlopen(req, timeout=timeout)

    @staticmethod
    def _notification_target_public_view(target: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(target or {})
        return {
            'target_id': str(payload.get('target_id') or ''),
            'type': str(payload.get('type') or ''),
            'enabled': bool(payload.get('enabled', True)),
            'channel': str(payload.get('channel') or ''),
            'url': str(payload.get('url') or ''),
            'installation_id': str(payload.get('installation_id') or ''),
            'target_path': str(payload.get('target_path') or ''),
            'queue_name': str(payload.get('queue_name') or ''),
            'email_to': str(payload.get('email_to') or ''),
            'subject_prefix': str(payload.get('subject_prefix') or ''),
            'min_escalation_level': int(payload.get('min_escalation_level') or 0),
            'severities': list(payload.get('severities') or []),
            'alert_codes': list(payload.get('alert_codes') or []),
            'workflow_actions': list(payload.get('workflow_actions') or []),
            'auth_secret_ref_configured': bool(str(payload.get('auth_secret_ref') or '').strip()),
            'metadata': dict(payload.get('metadata') or {}),
        }

    def _notification_budget_guard(
        self,
        gw,
        *,
        runtime_summary: dict[str, Any],
        alert: dict[str, Any],
        target: dict[str, Any],
    ) -> dict[str, Any]:
        policy = self._notification_budget_policy(runtime_summary)
        if not bool(policy.get('enabled')):
            return {'allowed': True, 'policy': policy, 'counts': {}}
        scope = dict((runtime_summary or {}).get('scope') or {})
        now = time.time()
        window_s = int(policy.get('window_s') or 300)
        statuses = {str(item).strip().lower() for item in list(policy.get('count_statuses') or []) if str(item).strip()}
        if not statuses:
            statuses = {'delivered', 'queued', 'pending', 'scheduled'}
        records = gw.audit.list_runtime_alert_notification_dispatches(limit=1000, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'))
        records = [item for item in records if float(item.get('created_at') or 0.0) >= (now - window_s) and str(item.get('delivery_status') or '').strip().lower() in statuses]
        runtime_id = str((runtime_summary or {}).get('runtime_id') or '').strip()
        target_type = str(target.get('type') or '').strip().lower()
        target_id = str(target.get('target_id') or '').strip()
        runtime_records = [item for item in records if str(item.get('runtime_id') or '').strip() == runtime_id]
        workspace_records = list(records)
        target_type_records = [item for item in runtime_records if str(item.get('target_type') or '').strip().lower() == target_type]
        target_id_records = [item for item in runtime_records if str(item.get('target_id') or '').strip() == target_id]
        limits = {
            'runtime_limit': int(policy.get('runtime_limit') or 0),
            'workspace_limit': int(policy.get('workspace_limit') or 0),
            'target_type_limit': int(dict(policy.get('target_type_limits') or {}).get(target_type) or 0),
            'target_id_limit': int(dict(policy.get('target_id_limits') or {}).get(target_id) or 0),
        }
        counts = {
            'runtime_count': len(runtime_records),
            'workspace_count': len(workspace_records),
            'target_type_count': len(target_type_records),
            'target_id_count': len(target_id_records),
            'window_s': window_s,
        }
        breaches: list[str] = []
        if limits['runtime_limit'] > 0 and counts['runtime_count'] >= limits['runtime_limit']:
            breaches.append('runtime_limit')
        if limits['workspace_limit'] > 0 and counts['workspace_count'] >= limits['workspace_limit']:
            breaches.append('workspace_limit')
        if limits['target_type_limit'] > 0 and counts['target_type_count'] >= limits['target_type_limit']:
            breaches.append('target_type_limit')
        if limits['target_id_limit'] > 0 and counts['target_id_count'] >= limits['target_id_limit']:
            breaches.append('target_id_limit')
        if not breaches:
            return {'allowed': True, 'policy': policy, 'counts': counts, 'limits': limits, 'breaches': []}
        relevant = runtime_records + workspace_records + target_type_records + target_id_records
        oldest = min((float(item.get('created_at') or now) for item in relevant), default=now)
        retry_after_s = max(int(policy.get('schedule_after_s') or 0), int(max(0.0, (oldest + window_s) - now)) + 1)
        return {
            'allowed': False,
            'policy': policy,
            'counts': counts,
            'limits': limits,
            'breaches': breaches,
            'on_limit': str(policy.get('on_limit') or 'schedule'),
            'retry_after_s': max(1, retry_after_s),
            'next_run_at': now + max(1, retry_after_s),
        }

    @staticmethod
    def _route_rule_matches(*, rule: dict[str, Any], alert: dict[str, Any], workflow_action: str, escalation_level: int) -> bool:
        if not bool(rule.get('enabled', True)):
            return False
        scope = dict(alert.get('scope') or {})
        workflow_actions = {str(item).strip().lower() for item in list(rule.get('workflow_actions') or []) if str(item).strip()}
        if workflow_actions and str(workflow_action or '').strip().lower() not in workflow_actions:
            return False
        severities = {str(item).strip().lower() for item in list(rule.get('severities') or []) if str(item).strip()}
        if severities and str(alert.get('severity') or '').strip().lower() not in severities:
            return False
        alert_codes = {str(item).strip() for item in list(rule.get('alert_codes') or []) if str(item).strip()}
        if alert_codes and str(alert.get('code') or '').strip() not in alert_codes:
            return False
        tenant_ids = {str(item).strip() for item in list(rule.get('tenant_ids') or []) if str(item).strip()}
        if tenant_ids and str(scope.get('tenant_id') or '').strip() not in tenant_ids:
            return False
        workspace_ids = {str(item).strip() for item in list(rule.get('workspace_ids') or []) if str(item).strip()}
        if workspace_ids and str(scope.get('workspace_id') or '').strip() not in workspace_ids:
            return False
        environments = {str(item).strip() for item in list(rule.get('environments') or []) if str(item).strip()}
        if environments and str(scope.get('environment') or '').strip() not in environments:
            return False
        if int(escalation_level or 0) < int(rule.get('min_escalation_level') or 0):
            return False
        max_level = rule.get('max_escalation_level')
        if max_level is not None and int(escalation_level or 0) > int(max_level):
            return False
        return True

    def _resolve_notification_targets(
        self,
        *,
        targets: list[dict[str, Any]],
        alert: dict[str, Any],
        workflow_action: str,
        escalation_level: int,
        target_ids: list[str] | None = None,
        target_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        ids = {str(item).strip() for item in list(target_ids or []) if str(item).strip()}
        types = {str(item).strip().lower() for item in list(target_types or []) if str(item).strip()}
        matched: list[dict[str, Any]] = []
        for target in list(targets or []):
            if ids and str(target.get('target_id') or '').strip() not in ids:
                continue
            if types and str(target.get('type') or '').strip().lower() not in types:
                continue
            if not self._notification_matches(target=target, alert=alert, workflow_action=workflow_action, escalation_level=escalation_level, selected_target_id=''):
                continue
            matched.append(target)
        return matched

    def _route_notification_plan(
        self,
        *,
        runtime_summary: dict[str, Any],
        alert: dict[str, Any],
        workflow_action: str,
        escalation_level: int,
        selected_target_id: str = '',
    ) -> list[dict[str, Any]]:
        targets = self._notification_targets(runtime_summary)
        if selected_target_id:
            return [{
                'target': item,
                'rule_id': 'manual-target',
                'chain_id': '',
                'step_id': '',
                'delay_s': 0,
                'time_windows': [],
                'max_retries': 0,
                'retry_backoff_s': 0,
                'selected_by': 'manual_target',
            } for item in targets if str(item.get('target_id') or '') == selected_target_id]
        routing = self._alert_routing_policy(runtime_summary)
        if not bool(routing.get('enabled', True)):
            return []
        chains_by_id = {str(item.get('chain_id') or '').strip(): item for item in list(routing.get('escalation_chains') or []) if str(item.get('chain_id') or '').strip()}
        routes: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str, int]] = set()
        rules = sorted(list(routing.get('rules') or []), key=lambda item: int(item.get('priority') or 0))
        for rule in rules:
            if not self._route_rule_matches(rule=rule, alert=alert, workflow_action=workflow_action, escalation_level=escalation_level):
                continue
            if str(rule.get('chain_id') or '').strip():
                chain = chains_by_id.get(str(rule.get('chain_id') or '').strip())
                if chain and bool(chain.get('enabled', True)):
                    for step in list(chain.get('steps') or []):
                        if not bool(step.get('enabled', True)):
                            continue
                        step_action = str(step.get('workflow_action') or workflow_action).strip().lower() or str(workflow_action or 'escalate').strip().lower()
                        matched_targets = self._resolve_notification_targets(targets=targets, alert=alert, workflow_action=step_action, escalation_level=escalation_level, target_ids=list(step.get('target_ids') or rule.get('target_ids') or []), target_types=list(step.get('target_types') or rule.get('target_types') or []))
                        for target in matched_targets:
                            key = (str(target.get('target_id') or ''), str(rule.get('rule_id') or ''), str(step.get('step_id') or ''), int(step.get('delay_s') or 0))
                            if key in seen:
                                continue
                            seen.add(key)
                            routes.append({
                                'target': target,
                                'rule_id': str(rule.get('rule_id') or ''),
                                'chain_id': str(chain.get('chain_id') or ''),
                                'step_id': str(step.get('step_id') or ''),
                                'workflow_action': step_action,
                                'delay_s': int(step.get('delay_s') or 0),
                                'time_windows': list(step.get('time_windows') or rule.get('time_windows') or []),
                                'max_retries': int(step.get('max_retries') if step.get('max_retries') is not None else (rule.get('max_retries') if rule.get('max_retries') is not None else routing.get('default_max_retries') or 0)),
                                'retry_backoff_s': int(step.get('retry_backoff_s') if step.get('retry_backoff_s') is not None else (rule.get('retry_backoff_s') if rule.get('retry_backoff_s') is not None else routing.get('default_retry_backoff_s') or 0)),
                                'selected_by': 'routing_chain',
                            })
            direct_targets: list[dict[str, Any]] = []
            if list(rule.get('target_ids') or []) or list(rule.get('target_types') or []):
                direct_targets = self._resolve_notification_targets(targets=targets, alert=alert, workflow_action=workflow_action, escalation_level=escalation_level, target_ids=list(rule.get('target_ids') or []), target_types=list(rule.get('target_types') or []))
            for target in direct_targets:
                key = (str(target.get('target_id') or ''), str(rule.get('rule_id') or ''), '', int(rule.get('delay_s') or 0))
                if key in seen:
                    continue
                seen.add(key)
                routes.append({
                    'target': target,
                    'rule_id': str(rule.get('rule_id') or ''),
                    'chain_id': '',
                    'step_id': '',
                    'workflow_action': str(workflow_action or 'escalate').strip().lower() or 'escalate',
                    'delay_s': int(rule.get('delay_s') or 0),
                    'time_windows': list(rule.get('time_windows') or []),
                    'max_retries': int(rule.get('max_retries') if rule.get('max_retries') is not None else routing.get('default_max_retries') or 0),
                    'retry_backoff_s': int(rule.get('retry_backoff_s') if rule.get('retry_backoff_s') is not None else routing.get('default_retry_backoff_s') or 0),
                    'selected_by': 'routing_rule',
                })
            if bool(rule.get('stop_after_match')) and routes:
                break
        return routes

    def get_runtime_alert_routing(
        self,
        gw,
        *,
        runtime_id: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        context = self._load_runtime_context(gw, runtime_id=runtime_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if not context.get('ok'):
            return context
        runtime_summary = dict(context.get('runtime_summary') or {})
        routing = self._alert_routing_policy(runtime_summary)
        targets = [self._notification_target_public_view(item) for item in self._notification_targets(runtime_summary)]
        return {
            'ok': True,
            'runtime_id': runtime_id,
            'routing_policy': routing,
            'targets': targets,
            'summary': {
                'rule_count': len(list(routing.get('rules') or [])),
                'enabled_rule_count': sum(1 for item in list(routing.get('rules') or []) if bool(item.get('enabled', True))),
                'escalation_chain_count': len(list(routing.get('escalation_chains') or [])),
                'step_count': sum(len(list((item or {}).get('steps') or [])) for item in list(routing.get('escalation_chains') or [])),
                'notification_target_count': len(targets),
            },
            'scope': dict((runtime_summary.get('scope') or {})),
        }

    @staticmethod
    def _notification_matches(*, target: dict[str, Any], alert: dict[str, Any], workflow_action: str, escalation_level: int, selected_target_id: str = '') -> bool:
        if not bool(target.get('enabled', True)):
            return False
        if selected_target_id:
            return str(target.get('target_id') or '') == selected_target_id
        if workflow_action and str(workflow_action).strip().lower() not in {str(item).strip().lower() for item in list(target.get('workflow_actions') or [])}:
            return False
        severities = {str(item).strip().lower() for item in list(target.get('severities') or []) if str(item).strip()}
        if severities and str(alert.get('severity') or '').strip().lower() not in severities:
            return False
        alert_codes = {str(item).strip() for item in list(target.get('alert_codes') or []) if str(item).strip()}
        if alert_codes and str(alert.get('code') or '').strip() not in alert_codes:
            return False
        if escalation_level < int(target.get('min_escalation_level') or 0):
            return False
        return True

    def list_runtime_notification_targets(
        self,
        gw,
        *,
        runtime_id: str,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        context = self._load_runtime_context(gw, runtime_id=runtime_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if not context.get('ok'):
            return context
        runtime_summary = dict(context.get('runtime_summary') or {})
        policy = self._notification_policy(runtime_summary)
        targets = [self._notification_target_public_view(item) for item in self._notification_targets(runtime_summary)]
        type_counts: dict[str, int] = {}
        for item in targets:
            tt = str(item.get('type') or 'unknown')
            type_counts[tt] = type_counts.get(tt, 0) + 1
        return {'ok': True, 'runtime_id': runtime_id, 'items': targets, 'policy': policy, 'budget_policy': self._notification_budget_policy(runtime_summary), 'escalation_policy': self._alert_escalation_policy(runtime_summary), 'summary': {'count': len(targets), 'type_counts': type_counts}, 'scope': dict(runtime_summary.get('scope') or {})}

    def list_runtime_alert_notification_dispatches(
        self,
        gw,
        *,
        runtime_id: str | None = None,
        alert_code: str | None = None,
        target_type: str | None = None,
        delivery_status: str | None = None,
        workflow_action: str | None = None,
        limit: int = 100,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        items = list(gw.audit.list_runtime_alert_notification_dispatches(runtime_id=runtime_id, alert_code=alert_code, target_type=target_type, delivery_status=delivery_status, workflow_action=workflow_action, limit=limit, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment) or [])
        status_counts: dict[str, int] = {}
        type_counts: dict[str, int] = {}
        for item in items:
            status_key = str(item.get('delivery_status') or 'unknown')
            type_key = str(item.get('target_type') or 'unknown')
            status_counts[status_key] = status_counts.get(status_key, 0) + 1
            type_counts[type_key] = type_counts.get(type_key, 0) + 1
        return {'ok': True, 'items': items, 'summary': {'count': len(items), 'status_counts': status_counts, 'type_counts': type_counts}, 'scope': self._scope(tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)}

    def _deliver_notification_to_target(
        self,
        gw,
        *,
        runtime_summary: dict[str, Any],
        alert: dict[str, Any],
        target: dict[str, Any],
        workflow_action: str,
        actor: str,
        reason: str = '',
        escalation_level: int = 0,
        session_id: str = '',
        user_key: str = '',
        notification_dispatch_id: str = '',
        route_context: dict[str, Any] | None = None,
        attempt_no: int = 0,
    ) -> dict[str, Any]:
        scope = dict((runtime_summary or {}).get('scope') or {})
        payload = self._notification_payload(alert=alert, runtime_summary=runtime_summary, workflow_action=workflow_action, actor=actor, reason=reason, escalation_level=escalation_level)
        dispatch_id = str(notification_dispatch_id or uuid.uuid4())
        target_view = self._notification_target_public_view(target)
        request_payload = {'target': target_view, 'payload': payload['json'], 'route': dict(route_context or {}), 'attempt_no': int(attempt_no or 0)}
        existing = gw.audit.get_runtime_alert_notification_dispatch(dispatch_id)
        if existing is None:
            record = gw.audit.create_runtime_alert_notification_dispatch(**self._runtime_alert_dispatch_create_kwargs(
                alert=alert,
                runtime_id=str((runtime_summary or {}).get('runtime_id') or ''),
                alert_code=str(alert.get('code') or ''),
                target=target,
                workflow_action=str(workflow_action or ''),
                escalation_level=int(escalation_level or 0),
                delivery_status='queued' if str(target.get('type') or '') in {'queue', 'email'} else 'pending',
                request=request_payload,
                response=None,
                created_by=str(actor or '').strip(),
                notification_dispatch_id=dispatch_id,
            ))
        else:
            record = dict(existing or {})
        target_type = str(target.get('type') or '').strip().lower()
        try:
            if target_type == 'slack':
                slack_client = getattr(gw, 'slack_client', None) or getattr(gw, 'slack', None)
                if slack_client is None:
                    raise RuntimeError('slack_not_configured')
                channel = str(target.get('channel') or '').strip()
                if not channel:
                    raise ValueError('slack_channel_required')
                slack_client.post_message(channel=channel, text=payload['text'], thread_ts=str(target.get('thread_ts') or '').strip() or None)
                response_payload = {'channel': channel, 'thread_ts': str(target.get('thread_ts') or '').strip() or None, 'attempt_no': int(attempt_no or 0), 'route': dict(route_context or {})}
                updated = gw.audit.update_runtime_alert_notification_dispatch(dispatch_id, delivery_status='delivered', response=response_payload, delivered_at=time.time())
            elif target_type == 'webhook':
                url = str(target.get('url') or '').strip()
                if not url:
                    raise ValueError('webhook_url_required')
                body = json.dumps(payload['json'], ensure_ascii=False).encode('utf-8')
                headers = {'Content-Type': 'application/json'}
                for key, value in dict(target.get('headers') or {}).items():
                    if str(key).strip():
                        headers[str(key)] = str(value)
                auth_secret_ref = str(target.get('auth_secret_ref') or '').strip()
                if auth_secret_ref:
                    broker = getattr(gw, 'secret_broker', None)
                    if broker is None:
                        raise RuntimeError('secret_broker_not_configured')
                    token = broker.resolve(auth_secret_ref, tool_name='openclaw_alert_notification', user_role='admin', user_key=str(user_key or actor or 'system'), session_id=str(session_id or f'alert:{(runtime_summary or {}).get("runtime_id") or ""}'), tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'))
                    headers['Authorization'] = f'Bearer {token}'
                req = urllib.request.Request(url, data=body, headers=headers, method='POST')
                with self._notification_urlopen(req, timeout=10.0) as resp:  # nosec - governed admin notification path
                    status_code = int(getattr(resp, 'status', 200) or 200)
                    response_body = resp.read().decode('utf-8', errors='replace')
                updated = gw.audit.update_runtime_alert_notification_dispatch(dispatch_id, delivery_status='delivered', response={'status_code': status_code, 'body': response_body[:1000], 'attempt_no': int(attempt_no or 0), 'route': dict(route_context or {})}, delivered_at=time.time())
            elif target_type == 'app':
                notification = gw.audit.create_app_notification(
                    title=payload['subject'],
                    body=payload['body'],
                    category='operator',
                    status='ready',
                    created_by=str(actor or 'system'),
                    target_path=str(target.get('target_path') or self._notification_policy(runtime_summary).get('default_app_target_path') or '/ui/?tab=operator'),
                    metadata={'runtime_id': (runtime_summary or {}).get('runtime_id'), 'alert_code': alert.get('code'), 'workflow_action': workflow_action, 'route': dict(route_context or {})},
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                )
                updated = gw.audit.update_runtime_alert_notification_dispatch(dispatch_id, delivery_status='delivered', response={'notification_id': notification.get('notification_id'), 'attempt_no': int(attempt_no or 0), 'route': dict(route_context or {})}, delivered_at=time.time())
            elif target_type == 'queue':
                queue_name = str(target.get('queue_name') or self._notification_policy(runtime_summary).get('default_queue_name') or 'runtime-alerts').strip() or 'runtime-alerts'
                updated = gw.audit.update_runtime_alert_notification_dispatch(dispatch_id, delivery_status='queued', response={'queue_name': queue_name, 'queued': True, 'attempt_no': int(attempt_no or 0), 'route': dict(route_context or {})}, delivered_at=time.time())
            elif target_type == 'email':
                mailer = getattr(gw, 'mailer', None)
                if mailer is not None:
                    result = mailer.send_email(to=str(target.get('email_to') or '').strip(), subject=f"{str(target.get('subject_prefix') or '').strip()} {payload['subject']}".strip(), body=payload['body'], metadata={'runtime_id': (runtime_summary or {}).get('runtime_id'), 'alert_code': alert.get('code'), 'workflow_action': workflow_action, 'route': dict(route_context or {}), 'attempt_no': int(attempt_no or 0)})
                    updated = gw.audit.update_runtime_alert_notification_dispatch(dispatch_id, delivery_status='delivered', response={'mailer_result': result, 'attempt_no': int(attempt_no or 0), 'route': dict(route_context or {})}, delivered_at=time.time())
                elif self._notification_policy(runtime_summary).get('queue_fallback_enabled', True):
                    queue_name = str(target.get('queue_name') or self._notification_policy(runtime_summary).get('default_queue_name') or 'runtime-alerts').strip() or 'runtime-alerts'
                    updated = gw.audit.update_runtime_alert_notification_dispatch(dispatch_id, delivery_status='queued', response={'queue_name': queue_name, 'queued': True, 'reason': 'mailer_not_configured', 'attempt_no': int(attempt_no or 0), 'route': dict(route_context or {})}, delivered_at=time.time())
                else:
                    raise RuntimeError('mailer_not_configured')
            else:
                raise RuntimeError('unsupported_notification_target')
            self._runtime_alert_log_event(
                gw,
                actor=str(actor or 'operator'),
                runtime_id=str((runtime_summary or {}).get('runtime_id') or ''),
                alert=alert,
                action='openclaw_alert_notification_dispatched',
                details={
                    'target_id': str(target.get('target_id') or ''),
                    'target_type': target_type,
                    'workflow_action': workflow_action,
                    'delivery_status': str((updated or {}).get('delivery_status') or ''),
                    'attempt_no': int(attempt_no or 0),
                },
            )
            return {'ok': True, 'delivery': updated, 'target': target_view}
        except Exception as exc:
            current_response = dict((record or {}).get('response') or {})
            current_response.update({'error': str(exc), 'attempt_no': int(attempt_no or 0), 'route': dict(route_context or {})})
            updated = gw.audit.update_runtime_alert_notification_dispatch(dispatch_id, delivery_status='failed', response=current_response, error_text=str(exc)) or record
            self._runtime_alert_log_event(
                gw,
                actor=str(actor or 'operator'),
                runtime_id=str((runtime_summary or {}).get('runtime_id') or ''),
                alert=alert,
                action='openclaw_alert_notification_failed',
                details={
                    'target_id': str(target.get('target_id') or ''),
                    'target_type': target_type,
                    'workflow_action': workflow_action,
                    'error': str(exc),
                    'attempt_no': int(attempt_no or 0),
                },
            )
            return {'ok': False, 'delivery': updated, 'error': str(exc), 'target': target_view}

    def _schedule_alert_delivery_job(
        self,
        gw,
        *,
        runtime_summary: dict[str, Any],
        alert: dict[str, Any],
        target: dict[str, Any],
        workflow_action: str,
        actor: str,
        next_run_at: float,
        reason: str = '',
        escalation_level: int = 0,
        route: dict[str, Any] | None = None,
        attempt_no: int = 0,
    ) -> dict[str, Any]:
        scope = dict((runtime_summary or {}).get('scope') or {})
        notification_dispatch_id = str(uuid.uuid4())
        payload = self._notification_payload(alert=alert, runtime_summary=runtime_summary, workflow_action=workflow_action, actor=actor, reason=reason, escalation_level=escalation_level)
        placeholder = gw.audit.create_runtime_alert_notification_dispatch(**self._runtime_alert_dispatch_create_kwargs(
            alert=alert,
            runtime_id=str((runtime_summary or {}).get('runtime_id') or ''),
            alert_code=str(alert.get('code') or ''),
            target=target,
            workflow_action=str(workflow_action or ''),
            escalation_level=int(escalation_level or 0),
            delivery_status='scheduled',
            request={'target': self._notification_target_public_view(target), 'payload': payload['json'], 'route': dict(route or {}), 'attempt_no': int(attempt_no or 0)},
            response={'scheduled_for': float(next_run_at), 'route': dict(route or {}), 'attempt_no': int(attempt_no or 0)},
            created_by=str(actor or '').strip(),
            notification_dispatch_id=notification_dispatch_id,
        ))
        definition = self._alert_delivery_job_definition(runtime_id=str((runtime_summary or {}).get('runtime_id') or ''), alert_code=str(alert.get('code') or ''), workflow_action=workflow_action, actor=actor, target=self._notification_target_public_view(target), reason=reason, escalation_level=int(escalation_level or 0), attempt_no=int(attempt_no or 0), notification_dispatch_id=notification_dispatch_id, route=dict(route or {}))
        created = self.job_service.create_job(gw, name=f"openclaw-alert-delivery:{(runtime_summary or {}).get('name') or (runtime_summary or {}).get('runtime_id') or ''}:{alert.get('code') or ''}:{target.get('target_id') or ''}", workflow_definition=definition, created_by=str(actor or 'system'), input_payload={'runtime_id': (runtime_summary or {}).get('runtime_id'), 'alert_code': alert.get('code'), 'target_id': target.get('target_id')}, next_run_at=float(next_run_at), enabled=True, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'), playbook_id=f"openclaw-alert-delivery:{(runtime_summary or {}).get('runtime_id') or ''}:{alert.get('code') or ''}", schedule_kind='once', not_before=float(next_run_at), max_runs=1)
        response_payload = dict(placeholder.get('response') or {})
        response_payload['job_id'] = created.get('job_id')
        response_payload['scheduled_for'] = float(next_run_at)
        gw.audit.update_runtime_alert_notification_dispatch(notification_dispatch_id, delivery_status='scheduled', response=response_payload)
        return {'ok': True, 'scheduled': True, 'delivery': gw.audit.get_runtime_alert_notification_dispatch(notification_dispatch_id), 'job': created, 'route': dict(route or {})}

    def _maybe_retry_notification_delivery(
        self,
        gw,
        *,
        runtime_summary: dict[str, Any],
        alert: dict[str, Any],
        target: dict[str, Any],
        workflow_action: str,
        actor: str,
        reason: str,
        escalation_level: int,
        route: dict[str, Any],
        attempt_no: int,
        failed_result: dict[str, Any],
    ) -> dict[str, Any] | None:
        max_retries = int(route.get('max_retries') or 0)
        if int(attempt_no or 0) >= max_retries:
            return None
        backoff_s = max(0, int(route.get('retry_backoff_s') or 0))
        next_route = dict(route or {})
        next_route['attempt_no'] = int(attempt_no or 0) + 1
        next_route['retry_of_dispatch_id'] = str(((failed_result.get('delivery') or {}).get('notification_dispatch_id')) or '')
        next_run_at = time.time() + backoff_s
        if backoff_s <= 0:
            next_run_at = time.time() - 0.01
        return self._schedule_alert_delivery_job(gw, runtime_summary=runtime_summary, alert=alert, target=target, workflow_action=workflow_action, actor=actor, next_run_at=next_run_at, reason=reason or str(failed_result.get('error') or 'retry'), escalation_level=escalation_level, route=next_route, attempt_no=int(attempt_no or 0) + 1)

    def list_alert_delivery_jobs(
        self,
        gw,
        *,
        limit: int = 100,
        enabled: bool | None = None,
        runtime_id: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        payload = self._list_jobs_by_family(
            gw,
            matcher=lambda item: self._is_alert_delivery_job(item, runtime_id=runtime_id),
            limit=limit,
            enabled=enabled,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            batch_size=max(limit, 50),
            transform=lambda _item, enriched: {
                **dict(enriched or {}),
                'runtime_id': str(((enriched or {}).get('workflow_definition') or {}).get('runtime_id') or ''),
                'alert_code': str(((enriched or {}).get('workflow_definition') or {}).get('alert_code') or ''),
                'workflow_action': str(((enriched or {}).get('workflow_definition') or {}).get('workflow_action') or ''),
                'target': dict((((enriched or {}).get('workflow_definition') or {}).get('target') or {})),
                'route': dict((((enriched or {}).get('workflow_definition') or {}).get('route') or {})),
                'notification_dispatch_id': str(((enriched or {}).get('workflow_definition') or {}).get('notification_dispatch_id') or ''),
            },
        )
        return {'ok': True, 'items': payload['items'], 'summary': {**payload['summary'], 'runtime_id': runtime_id}}

    def _run_single_alert_delivery_job(
        self,
        gw,
        *,
        item: dict[str, Any],
        actor: str,
        user_key: str,
    ) -> dict[str, Any]:
        job_id = str(item.get('job_id') or '').strip()
        if not job_id:
            raise ValueError('job_id is required')
        if not self.job_service._is_due(item, now=time.time()):
            raise ValueError('Job is not due or cannot run in current window')
        if not self._is_alert_delivery_job(item):
            raise ValueError('Job is not an OpenClaw alert-delivery job')
        definition = dict(item.get('workflow_definition') or {})
        scope = self._scope(tenant_id=item.get('tenant_id'), workspace_id=item.get('workspace_id'), environment=item.get('environment'))
        runtime_id = str(definition.get('runtime_id') or '').strip()
        alert_code = str(definition.get('alert_code') or '').strip()
        workflow_action = str(definition.get('workflow_action') or 'escalate').strip().lower() or 'escalate'
        reason = str(definition.get('reason') or '').strip()
        escalation_level = int(definition.get('escalation_level') or 0)
        attempt_no = int(definition.get('attempt_no') or 0)
        notification_dispatch_id = str(definition.get('notification_dispatch_id') or '').strip()
        target = dict(definition.get('target') or {})
        route = dict(definition.get('route') or {})
        context = self._load_runtime_context(gw, runtime_id=runtime_id, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'))
        if not context.get('ok'):
            raise LookupError('runtime_not_found')
        runtime_summary = dict(context.get('runtime_summary') or {})
        alerts_payload = self.evaluate_runtime_alerts(gw, runtime_id=runtime_id, limit=200, tenant_id=scope.get('tenant_id'), workspace_id=scope.get('workspace_id'), environment=scope.get('environment'))
        alert = self._alert_by_code(alerts_payload, alert_code)
        if alert is None:
            if notification_dispatch_id:
                gw.audit.update_runtime_alert_notification_dispatch(notification_dispatch_id, delivery_status='failed', response={'reason': 'alert_not_active'}, error_text='alert_not_active')
            last_error = 'alert_not_active'
            result = {'ok': False, 'error': last_error}
        else:
            result = self._deliver_notification_to_target(gw, runtime_summary=runtime_summary, alert=alert, target=target, workflow_action=workflow_action, actor=actor, reason=reason, escalation_level=escalation_level, session_id=self.job_service._session_id(job_id), user_key=user_key, notification_dispatch_id=notification_dispatch_id, route_context=route, attempt_no=attempt_no)
            last_error = '' if result.get('ok') else str(result.get('error') or 'delivery_failed')
            retry_job = None
            if alert is not None and not result.get('ok'):
                retry_job = self._maybe_retry_notification_delivery(gw, runtime_summary=runtime_summary, alert=alert, target=target, workflow_action=workflow_action, actor=actor, reason=reason or last_error, escalation_level=escalation_level, route=route, attempt_no=attempt_no, failed_result=result)
                if retry_job is not None:
                    result['retry_scheduled'] = retry_job
        refreshed = self._complete_job_execution(gw, item=item, last_error=last_error)
        return {'job': refreshed, 'delivery': result}

    def run_due_alert_delivery_jobs(
        self,
        gw,
        *,
        actor: str,
        limit: int = 20,
        runtime_id: str | None = None,
        user_key: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        payload = self._run_due_jobs_by_family(
            gw,
            matcher=lambda item: self._is_alert_delivery_job(item, runtime_id=runtime_id),
            runner=self._run_single_alert_delivery_job,
            actor=actor,
            limit=limit,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            batch_size=max(limit, 50),
            user_key=user_key,
        )
        return {'ok': True, 'items': payload['items'], 'summary': {**payload['summary'], 'runtime_id': runtime_id}}

    def dispatch_runtime_alert_notifications(
        self,
        gw,
        *,
        runtime_id: str,
        alert_code: str,
        actor: str,
        workflow_action: str = 'escalate',
        target_id: str = '',
        reason: str = '',
        escalation_level: int | None = None,
        session_id: str = '',
        user_key: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        context = self._load_runtime_context(gw, runtime_id=runtime_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if not context.get('ok'):
            return context
        runtime_summary = dict(context.get('runtime_summary') or {})
        policy = self._notification_policy(runtime_summary)
        routing_policy = self._alert_routing_policy(runtime_summary)
        alerts_payload = self.evaluate_runtime_alerts(gw, runtime_id=runtime_id, limit=200, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if not alerts_payload.get('ok'):
            return alerts_payload
        alert = self._alert_by_code(alerts_payload, alert_code)
        if alert is None:
            return {'ok': False, 'error': 'alert_not_active', 'runtime_id': runtime_id, 'alert_code': str(alert_code or '').strip()}
        governance = dict(((alert.get('workflow') or {}).get('governance') or alert.get('governance') or {}))
        workflow_action_id = str(workflow_action or 'escalate').strip().lower() or 'escalate'
        effective_level = int(escalation_level if escalation_level is not None else (((alert.get('workflow') or {}).get('state') or {}).get('escalation_level') or 0))
        selected_target_id = str(target_id or '').strip()
        routes = self._route_notification_plan(runtime_summary=runtime_summary, alert=alert, workflow_action=workflow_action_id, escalation_level=effective_level, selected_target_id=selected_target_id)
        matched = [dict(item.get('target') or {}) for item in routes]
        if not routes:
            targets = self._notification_targets(runtime_summary)
            matched_targets = [item for item in targets if self._notification_matches(target=item, alert=alert, workflow_action=workflow_action_id, escalation_level=effective_level, selected_target_id=selected_target_id)]
            if not matched_targets and policy.get('queue_fallback_enabled', True):
                fallback_types = list(policy.get('default_target_types') or []) or ['queue']
                for idx, fallback_type in enumerate(fallback_types):
                    matched_targets.append({'target_id': f'fallback-{fallback_type}-{idx + 1}', 'type': str(fallback_type).strip().lower(), 'enabled': True, 'queue_name': policy.get('default_queue_name'), 'target_path': policy.get('default_app_target_path'), 'workflow_actions': [workflow_action_id], 'severities': [], 'alert_codes': [], 'min_escalation_level': 0, 'headers': {}, 'metadata': {}})
            routes = [{'target': target, 'rule_id': 'legacy', 'chain_id': '', 'step_id': '', 'delay_s': 0, 'time_windows': [], 'max_retries': 0, 'retry_backoff_s': 0, 'workflow_action': workflow_action_id, 'selected_by': 'legacy'} for target in matched_targets]
            matched = matched_targets
        dedupe_window_s = int(policy.get('dedupe_window_s') or 0)
        now = time.time()
        items: list[dict[str, Any]] = []
        for route in routes[: int(policy.get('max_targets_per_dispatch') or len(routes) or 1)]:
            target = dict(route.get('target') or {})
            if dedupe_window_s > 0:
                recent = gw.audit.list_runtime_alert_notification_dispatches(runtime_id=runtime_id, alert_code=str(alert.get('code') or ''), target_id=str(target.get('target_id') or ''), workflow_action=str(route.get('workflow_action') or workflow_action_id), limit=10, tenant_id=(alert.get('scope') or {}).get('tenant_id'), workspace_id=(alert.get('scope') or {}).get('workspace_id'), environment=(alert.get('scope') or {}).get('environment'))
                duplicate = next((entry for entry in recent if float(entry.get('created_at') or 0.0) >= (now - dedupe_window_s) and str(entry.get('delivery_status') or '') in {'delivered', 'queued', 'pending', 'scheduled'}), None)
                if duplicate is not None:
                    skip = gw.audit.create_runtime_alert_notification_dispatch(**self._runtime_alert_dispatch_create_kwargs(
                        alert=alert,
                        runtime_id=runtime_id,
                        alert_code=alert_code,
                        target=target,
                        workflow_action=str(route.get('workflow_action') or workflow_action_id),
                        escalation_level=effective_level,
                        delivery_status='skipped',
                        request={'target': self._notification_target_public_view(target), 'duplicate_of': duplicate.get('notification_dispatch_id'), 'route': dict(route)},
                        response={'reason': 'dedupe_window', 'duplicate_of': duplicate.get('notification_dispatch_id')},
                        created_by=str(actor or ''),
                        notification_dispatch_id=str(uuid.uuid4()),
                        delivered_at=time.time(),
                    ))
                    items.append({'ok': True, 'delivery': skip, 'duplicate': True})
                    continue
            if bool(governance.get('suppressed')):
                response_payload = {'reason': 'governance_suppressed', 'governance': {'status': governance.get('status'), 'reasons': list(governance.get('reasons') or []), 'next_allowed_at': governance.get('next_allowed_at')}}
                suppressed_delivery = gw.audit.create_runtime_alert_notification_dispatch(**self._runtime_alert_dispatch_create_kwargs(
                    alert=alert,
                    runtime_id=runtime_id,
                    alert_code=alert_code,
                    target=target,
                    workflow_action=str(route.get('workflow_action') or workflow_action_id),
                    escalation_level=effective_level,
                    delivery_status='suppressed',
                    request={'target': self._notification_target_public_view(target), 'route': dict(route), 'governance': governance},
                    response=response_payload,
                    created_by=str(actor or '').strip(),
                    notification_dispatch_id=str(uuid.uuid4()),
                    delivered_at=time.time(),
                ))
                items.append({'ok': True, 'delivery': suppressed_delivery, 'suppressed': True, 'target': self._notification_target_public_view(target), 'governance': governance})
                continue
            scheduled_for, schedule_reasons = self._route_schedule_ts(route=route, routing_policy=routing_policy, now=now)
            if bool(governance.get('scheduled')):
                governance_ts = float(governance.get('next_allowed_at') or (now + 60.0))
                if governance_ts > scheduled_for:
                    scheduled_for = governance_ts
                schedule_reasons = list(schedule_reasons or []) + [f'governance:{reason}' for reason in list(governance.get('reasons') or [])]
            if scheduled_for > now + 0.5 or schedule_reasons:
                scheduled = self._schedule_alert_delivery_job(gw, runtime_summary=runtime_summary, alert=alert, target=target, workflow_action=str(route.get('workflow_action') or workflow_action_id), actor=actor, next_run_at=scheduled_for, reason=reason or ','.join(schedule_reasons), escalation_level=effective_level, route={**dict(route), 'schedule_reasons': schedule_reasons, 'governance': governance}, attempt_no=int(route.get('attempt_no') or 0))
                items.append(scheduled)
                continue
            budget_guard = self._notification_budget_guard(gw, runtime_summary=runtime_summary, alert=alert, target=target)
            if not bool(budget_guard.get('allowed', True)):
                budget_route = {**dict(route), 'budget': {k: v for k, v in dict(budget_guard).items() if k in {'counts', 'limits', 'breaches', 'retry_after_s', 'on_limit'}}}
                if str(budget_guard.get('on_limit') or 'schedule') == 'schedule':
                    scheduled = self._schedule_alert_delivery_job(gw, runtime_summary=runtime_summary, alert=alert, target=target, workflow_action=str(route.get('workflow_action') or workflow_action_id), actor=actor, next_run_at=float(budget_guard.get('next_run_at') or (time.time() + 60)), reason='notification_budget_exceeded', escalation_level=effective_level, route=budget_route, attempt_no=int(route.get('attempt_no') or 0))
                    if scheduled.get('delivery') is not None:
                        response_payload = dict((scheduled.get('delivery') or {}).get('response') or {})
                        response_payload['budget'] = {k: v for k, v in dict(budget_guard).items() if k != 'policy'}
                        gw.audit.update_runtime_alert_notification_dispatch(str((scheduled.get('delivery') or {}).get('notification_dispatch_id') or ''), response=response_payload)
                        scheduled['delivery'] = gw.audit.get_runtime_alert_notification_dispatch(str((scheduled.get('delivery') or {}).get('notification_dispatch_id') or ''))
                    scheduled['rate_limited'] = True
                    items.append(scheduled)
                    continue
                throttled = gw.audit.create_runtime_alert_notification_dispatch(**self._runtime_alert_dispatch_create_kwargs(
                    alert=alert,
                    runtime_id=runtime_id,
                    alert_code=alert_code,
                    target=target,
                    workflow_action=str(route.get('workflow_action') or workflow_action_id),
                    escalation_level=effective_level,
                    delivery_status='rate_limited',
                    request={'target': self._notification_target_public_view(target), 'route': budget_route},
                    response={'budget': {k: v for k, v in dict(budget_guard).items() if k != 'policy'}},
                    created_by=str(actor or '').strip(),
                    notification_dispatch_id=str(uuid.uuid4()),
                    delivered_at=time.time(),
                ))
                items.append({'ok': True, 'delivery': throttled, 'rate_limited': True, 'target': self._notification_target_public_view(target)})
                continue
            delivery = self._deliver_notification_to_target(gw, runtime_summary=runtime_summary, alert=alert, target=target, workflow_action=str(route.get('workflow_action') or workflow_action_id), actor=actor, reason=reason, escalation_level=effective_level, session_id=session_id, user_key=user_key, route_context=route, attempt_no=int(route.get('attempt_no') or 0))
            if not delivery.get('ok'):
                retry_job = self._maybe_retry_notification_delivery(gw, runtime_summary=runtime_summary, alert=alert, target=target, workflow_action=str(route.get('workflow_action') or workflow_action_id), actor=actor, reason=reason or str(delivery.get('error') or ''), escalation_level=effective_level, route=route, attempt_no=int(route.get('attempt_no') or 0), failed_result=delivery)
                if retry_job is not None:
                    delivery['retry_scheduled'] = retry_job
            items.append(delivery)
        status_counts: dict[str, int] = {}
        scheduled_count = 0
        retry_job_count = 0
        for item in items:
            key = str(((item.get('delivery') or {}).get('delivery_status')) or ('failed' if not item.get('ok') else 'unknown'))
            status_counts[key] = status_counts.get(key, 0) + 1
            if bool(item.get('scheduled')):
                scheduled_count += 1
            if item.get('retry_scheduled') is not None:
                retry_job_count += 1
        return {'ok': True, 'runtime_id': runtime_id, 'alert_code': str(alert.get('code') or ''), 'items': items, 'summary': {'count': len(items), 'status_counts': status_counts, 'target_count': len(matched), 'scheduled_count': scheduled_count, 'retry_job_count': retry_job_count, 'suppressed_count': sum(1 for item in items if bool(item.get('suppressed')))}, 'policy': policy, 'routing_policy': routing_policy, 'governance': governance, 'scope': dict(alert.get('scope') or {})}

