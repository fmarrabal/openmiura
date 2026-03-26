from __future__ import annotations

from collections import Counter
from typing import Any

from openmiura.application.approvals import ApprovalService
from openmiura.application.replay import ReplayService
from openmiura.application.workflows import WorkflowService


class OperatorConsoleService:
    def __init__(
        self,
        *,
        replay_service: ReplayService | None = None,
        workflow_service: WorkflowService | None = None,
        approval_service: ApprovalService | None = None,
    ) -> None:
        self.workflow_service = workflow_service or WorkflowService()
        self.replay_service = replay_service or ReplayService(workflow_service=self.workflow_service)
        self.approval_service = approval_service or ApprovalService(workflow_service=self.workflow_service)

    def overview(
        self,
        gw,
        *,
        limit: int = 20,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        q: str | None = None,
        status: str | None = None,
        kind: str | None = None,
        only_failures: bool = False,
    ) -> dict[str, Any]:
        scope = {
            'tenant_id': tenant_id,
            'workspace_id': workspace_id,
            'environment': environment,
        }
        fetch_limit = max(limit * 5, 100)
        sessions = self._safe_call(gw.audit, 'list_sessions', [], limit=fetch_limit, **scope)
        workflows = self._safe_call(gw.audit, 'list_workflows', [], limit=fetch_limit, **scope)
        approvals = self._safe_call(gw.audit, 'list_approvals', [], limit=fetch_limit, **scope)
        traces = self._safe_call(gw.audit, 'list_decision_traces', [], limit=fetch_limit, **scope)
        tool_calls = self._safe_call(gw.audit, 'list_tool_calls', [], limit=max(fetch_limit * 2, 120), **scope)
        events = self._safe_call(gw.audit, 'list_events_filtered', [], limit=max(fetch_limit * 3, 180), **scope)

        counts = self._safe_table_counts(gw, scope)
        workflow_status = Counter(str(item.get('status') or 'unknown') for item in (workflows or []))
        trace_status = Counter(str(item.get('status') or 'unknown') for item in (traces or []))
        failed_tool_calls = [item for item in (tool_calls or []) if not bool(item.get('ok'))]
        recent_failures = self._recent_failures(workflows=workflows, traces=traces, tool_calls=tool_calls, limit=fetch_limit)

        filters = {
            'q': str(q or '').strip(),
            'status': str(status or '').strip().lower() or None,
            'kind': str(kind or '').strip().lower() or None,
            'only_failures': bool(only_failures),
            'limit': int(limit),
        }
        sessions_filtered = self._filter_sessions(list(sessions or []), q=filters['q'], kind=filters['kind'])[:limit]
        workflows_filtered = self._annotate_workflows(
            self._filter_workflows(list(workflows or []), q=filters['q'], status=filters['status'], kind=filters['kind'], only_failures=filters['only_failures'])[:limit]
        )
        approvals_filtered = self._annotate_approvals(
            self._filter_approvals(list(approvals or []), q=filters['q'], status=filters['status'], kind=filters['kind'], only_failures=filters['only_failures'])[:limit]
        )
        traces_filtered = self._filter_traces(list(traces or []), q=filters['q'], status=filters['status'], kind=filters['kind'], only_failures=filters['only_failures'])[:limit]
        failures_filtered = self._filter_failures(list(recent_failures or []), q=filters['q'], status=filters['status'], kind=filters['kind'])[:limit]
        events_filtered = self._filter_events(list(events or []), q=filters['q'], kind=filters['kind'])[:limit]

        policy_snapshot = self._policy_snapshot(gw)
        return {
            'ok': True,
            'scope': scope,
            'filters': filters,
            'summary': {
                'sessions': int(counts.get('sessions') or len(sessions or [])),
                'events': int(counts.get('events') or len(events or [])),
                'tool_calls': int(counts.get('tool_calls') or len(tool_calls or [])),
                'workflows': int(counts.get('workflows') or len(workflows or [])),
                'approvals_pending': len([item for item in (approvals or []) if str(item.get('status') or '') == 'pending']),
                'decision_traces': int(counts.get('decision_traces') or len(traces or [])),
                'workflow_failures': int(workflow_status.get('failed', 0) + workflow_status.get('rejected', 0) + workflow_status.get('cancelled', 0)),
                'trace_failures': int(sum(v for k, v in trace_status.items() if k not in {'completed', 'succeeded', 'ok', 'unknown'})),
                'tool_failures': len(failed_tool_calls),
            },
            'filtered_counts': {
                'recent_sessions': len(sessions_filtered),
                'recent_workflows': len(workflows_filtered),
                'approvals': len(approvals_filtered),
                'recent_traces': len(traces_filtered),
                'recent_failures': len(failures_filtered),
                'recent_events': len(events_filtered),
            },
            'recent_sessions': sessions_filtered,
            'recent_workflows': workflows_filtered,
            'pending_approvals': [item for item in approvals_filtered if str(item.get('status') or '') == 'pending'],
            'recent_traces': traces_filtered,
            'recent_events': events_filtered,
            'recent_failures': failures_filtered,
            'policy': policy_snapshot,
            'queues': {
                'approvals_pending': len([item for item in approvals_filtered if str(item.get('status') or '') == 'pending']),
                'workflows_active': sum(1 for item in workflows_filtered if str(item.get('status') or '') in {'pending', 'running', 'waiting_approval'}),
                'sessions_active': sum(1 for item in sessions_filtered if item.get('last_message')),
            },
        }

    def session_console(
        self,
        gw,
        *,
        session_id: str,
        limit: int = 200,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        q: str | None = None,
        status: str | None = None,
        kind: str | None = None,
        only_failures: bool = False,
    ) -> dict[str, Any]:
        replay = self.replay_service.session_replay(
            gw,
            session_id=session_id,
            limit=limit,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        if not replay.get('ok'):
            return replay
        traces = list(replay.get('traces') or [])
        observed_tools = self._observed_tools(replay)
        filtered = self._filter_replay_payload(
            replay,
            q=q,
            status=status,
            kind=kind,
            only_failures=only_failures,
            include_approvals=False,
        )
        inspector = {
            'message_count': len(list(filtered.get('messages') or [])),
            'trace_count': len(list(filtered.get('traces') or [])),
            'tool_call_count': len(list(filtered.get('tool_calls') or [])),
            'memory_hits': sum(len(list((item.get('memory') or {}).get('items') or [])) for item in list(filtered.get('traces') or [])),
            'agents': sorted({str(item.get('agent_id') or '') for item in traces if str(item.get('agent_id') or '').strip()}),
            'providers': sorted({f"{item.get('provider') or ''}:{item.get('model') or ''}" for item in traces if (item.get('provider') or item.get('model'))}),
        }
        return {
            'ok': True,
            'kind': 'session',
            'entity_id': session_id,
            'filters': filtered.get('filters') or {},
            'summary': dict(filtered.get('summary') or replay.get('summary') or {}),
            'session': replay.get('session'),
            'timeline': filtered.get('timeline') or [],
            'messages': filtered.get('messages') or [],
            'tool_calls': filtered.get('tool_calls') or [],
            'traces': filtered.get('traces') or [],
            'inspector': inspector,
            'policy_hints': self._policy_hints(gw, observed_tools=observed_tools, traces=traces),
        }

    def workflow_console(
        self,
        gw,
        *,
        workflow_id: str,
        limit: int = 200,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        q: str | None = None,
        status: str | None = None,
        kind: str | None = None,
        only_failures: bool = False,
    ) -> dict[str, Any]:
        replay = self.replay_service.workflow_replay(
            gw,
            workflow_id=workflow_id,
            limit=limit,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        if not replay.get('ok'):
            return replay
        approvals = self._annotate_approvals(list(replay.get('approvals') or []))
        traces = list(replay.get('traces') or [])
        observed_tools = self._observed_tools(replay)
        observed_actions = self._approval_actions(approvals)
        filtered = self._filter_replay_payload(
            replay | {'approvals': approvals},
            q=q,
            status=status,
            kind=kind,
            only_failures=only_failures,
            include_approvals=True,
        )
        filtered_approvals = self._annotate_approvals(list(filtered.get('approvals') or []))
        inspector = {
            'approval_count': len(filtered_approvals),
            'pending_approvals': sum(1 for item in filtered_approvals if str(item.get('status') or '') == 'pending'),
            'trace_count': len(list(filtered.get('traces') or [])),
            'tool_call_count': len(list(filtered.get('tool_calls') or [])),
            'step_count': len(list(((replay.get('workflow') or {}).get('definition') or {}).get('steps') or [])),
        }
        workflow_item = dict(replay.get('workflow') or {})
        workflow_item['available_actions'] = self._workflow_available_actions(workflow_item)
        return {
            'ok': True,
            'kind': 'workflow',
            'entity_id': workflow_id,
            'filters': filtered.get('filters') or {},
            'summary': dict(filtered.get('summary') or replay.get('summary') or {}),
            'workflow': workflow_item,
            'timeline': filtered.get('timeline') or [],
            'messages': filtered.get('messages') or [],
            'tool_calls': filtered.get('tool_calls') or [],
            'traces': filtered.get('traces') or [],
            'approvals': filtered_approvals,
            'inspector': inspector,
            'policy_hints': self._policy_hints(gw, observed_tools=observed_tools, approval_actions=observed_actions, traces=traces),
        }

    def workflow_action(
        self,
        gw,
        *,
        workflow_id: str,
        action: str,
        actor: str,
        reason: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        normalized = str(action or '').strip().lower()
        if normalized == 'cancel':
            item = self.workflow_service.cancel_workflow(
                gw,
                workflow_id,
                actor=actor,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                environment=environment,
            )
        elif normalized == 'run':
            item = self.workflow_service.run_workflow(
                gw,
                workflow_id,
                actor=actor,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                environment=environment,
            )
        else:
            raise ValueError('Unsupported workflow action')
        if item is None:
            raise LookupError('Unknown workflow')
        workflow = dict(item)
        workflow['available_actions'] = self._workflow_available_actions(workflow)
        return {'ok': True, 'action': normalized, 'reason': reason, 'workflow': workflow}

    def approval_action(
        self,
        gw,
        *,
        approval_id: str,
        action: str,
        actor: str,
        reason: str = '',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        normalized = str(action or '').strip().lower()
        if normalized == 'claim':
            item = self.approval_service.claim(
                gw,
                approval_id,
                actor=actor,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                environment=environment,
            )
        elif normalized in {'approve', 'reject'}:
            item = self.approval_service.decide(
                gw,
                approval_id,
                actor=actor,
                decision=normalized,
                reason=reason,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                environment=environment,
            )
        else:
            raise ValueError('Unsupported approval action')
        approval = dict(item)
        approval['available_actions'] = self._approval_available_actions(approval)
        return {'ok': True, 'action': normalized, 'reason': reason, 'approval': approval}

    def _filter_replay_payload(
        self,
        replay: dict[str, Any],
        *,
        q: str | None,
        status: str | None,
        kind: str | None,
        only_failures: bool,
        include_approvals: bool,
    ) -> dict[str, Any]:
        q_norm = str(q or '').strip().lower()
        status_norm = str(status or '').strip().lower() or None
        kind_norm = str(kind or '').strip().lower() or None
        timeline = [
            item for item in list(replay.get('timeline') or [])
            if self._timeline_item_matches(item, q=q_norm, status=status_norm, kind=kind_norm, only_failures=only_failures)
        ]
        message_ids = {item.get('message_id') for item in timeline if item.get('kind') == 'message' and item.get('message_id') is not None}
        trace_ids = {item.get('trace_id') for item in timeline if item.get('kind') == 'trace' and item.get('trace_id')}
        tool_ids = {item.get('id') for item in timeline if item.get('kind') == 'tool_call' and item.get('id') is not None}
        approval_ids = {item.get('approval_id') for item in timeline if item.get('kind') == 'approval' and item.get('approval_id')}

        messages = [item for item in list(replay.get('messages') or []) if not message_ids or item.get('id') in message_ids]
        traces = [item for item in list(replay.get('traces') or []) if not trace_ids or item.get('trace_id') in trace_ids]
        tool_calls = [item for item in list(replay.get('tool_calls') or []) if not tool_ids or item.get('id') in tool_ids]
        approvals = []
        if include_approvals:
            approvals = [item for item in list(replay.get('approvals') or []) if not approval_ids or item.get('approval_id') in approval_ids]

        summary = dict(replay.get('summary') or {})
        summary.update({
            'message_count': len(messages),
            'event_count': len([item for item in timeline if item.get('kind') == 'event']),
            'tool_call_count': len(tool_calls),
            'trace_count': len(traces),
            'approval_count': len(approvals) if include_approvals else summary.get('approval_count', 0),
        })
        summary['filters_applied'] = {
            'q': q_norm,
            'status': status_norm,
            'kind': kind_norm,
            'only_failures': bool(only_failures),
        }
        return {
            'timeline': timeline,
            'messages': messages,
            'traces': traces,
            'tool_calls': tool_calls,
            'approvals': approvals,
            'summary': summary,
            'filters': summary['filters_applied'],
        }

    def _policy_hints(
        self,
        gw,
        *,
        observed_tools: list[str],
        traces: list[dict[str, Any]],
        approval_actions: list[str] | None = None,
    ) -> dict[str, Any]:
        policy = getattr(gw, 'policy', None)
        agent_name = next((str(item.get('agent_id') or '').strip() for item in traces if str(item.get('agent_id') or '').strip()), None)
        user_role = None
        tool_rules: list[dict[str, Any]] = []
        approval_rules: list[dict[str, Any]] = []
        if policy is not None and hasattr(policy, 'explain_request'):
            for tool_name in observed_tools[:20]:
                try:
                    decision = policy.explain_request(
                        scope='tool',
                        resource_name=tool_name,
                        action='use',
                        agent_name=agent_name,
                        user_role=user_role,
                        tenant_id=None,
                        workspace_id=None,
                        environment=None,
                        channel=None,
                        domain=None,
                        extra={},
                        tool_name=tool_name,
                    )
                except Exception:
                    decision = {'ok': False, 'decision': {'allowed': True, 'reason': 'policy_explain_failed'}}
                tool_rules.append({'tool_name': tool_name, 'decision': decision.get('decision') or {}})
            for action_name in (approval_actions or [])[:20]:
                try:
                    decision = policy.explain_request(
                        scope='approval',
                        resource_name=action_name,
                        action='require',
                        agent_name=agent_name,
                        user_role=user_role,
                        tenant_id=None,
                        workspace_id=None,
                        environment=None,
                        channel=None,
                        domain=None,
                        extra={},
                        tool_name=None,
                    )
                except Exception:
                    decision = {'ok': False, 'decision': {}}
                approval_rules.append({'action_name': action_name, 'decision': decision.get('decision') or {}})
        snapshot = self._policy_snapshot(gw)
        return {
            'signature': snapshot.get('signature'),
            'sections': snapshot.get('sections') or {},
            'tool_rules': tool_rules,
            'approval_rules': approval_rules,
            'observed_tools': observed_tools,
            'observed_approval_actions': list(approval_actions or []),
        }

    def _policy_snapshot(self, gw) -> dict[str, Any]:
        policy = getattr(gw, 'policy', None)
        if policy is None or not hasattr(policy, 'snapshot'):
            return {'ok': False, 'reason': 'policy_not_configured', 'signature': None, 'sections': {}}
        snapshot = policy.snapshot() or {}
        sections: dict[str, Any] = {}
        for key, value in dict(snapshot).items():
            if isinstance(value, list):
                sections[key] = len(value)
            elif isinstance(value, dict):
                sections[key] = len(value.keys())
            else:
                sections[key] = 0
        return {
            'ok': True,
            'signature': self._safe_call(policy, 'signature', None),
            'sections': sections,
        }

    @staticmethod
    def _approval_actions(approvals: list[dict[str, Any]]) -> list[str]:
        actions: list[str] = []
        for approval in approvals:
            payload = dict(approval.get('payload') or {})
            candidate = str(payload.get('action_name') or payload.get('tool_name') or approval.get('step_id') or '').strip()
            if candidate and candidate not in actions:
                actions.append(candidate)
        return actions

    @staticmethod
    def _workflow_available_actions(item: dict[str, Any]) -> list[str]:
        status = str(item.get('status') or '').strip().lower()
        if status in {'pending', 'running', 'waiting_approval'}:
            return ['cancel']
        return []

    @staticmethod
    def _approval_available_actions(item: dict[str, Any]) -> list[str]:
        status = str(item.get('status') or '').strip().lower()
        if status == 'pending':
            return ['claim', 'approve', 'reject']
        return []

    def _annotate_workflows(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for item in items:
            enriched = dict(item)
            enriched['available_actions'] = self._workflow_available_actions(enriched)
            out.append(enriched)
        return out

    def _annotate_approvals(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for item in items:
            enriched = dict(item)
            enriched['available_actions'] = self._approval_available_actions(enriched)
            out.append(enriched)
        return out

    @staticmethod
    def _observed_tools(replay: dict[str, Any]) -> list[str]:
        tools = []
        for item in list(replay.get('tool_calls') or []):
            name = str(item.get('tool_name') or '').strip()
            if name and name not in tools:
                tools.append(name)
        for trace in list(replay.get('traces') or []):
            for tool_item in list(trace.get('tools_used') or []):
                if isinstance(tool_item, dict):
                    name = str(tool_item.get('tool_name') or tool_item.get('name') or '').strip()
                else:
                    name = str(tool_item or '').strip()
                if name and name not in tools:
                    tools.append(name)
        return tools

    @staticmethod
    def _recent_failures(*, workflows: list[dict[str, Any]], traces: list[dict[str, Any]], tool_calls: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for workflow in list(workflows or []):
            status = str(workflow.get('status') or '')
            if status in {'failed', 'rejected', 'cancelled'}:
                items.append({
                    'kind': 'workflow',
                    'id': workflow.get('workflow_id'),
                    'label': workflow.get('name') or workflow.get('workflow_id'),
                    'status': status,
                    'ts': float(workflow.get('updated_at') or workflow.get('created_at') or 0.0),
                })
        for trace in list(traces or []):
            status = str(trace.get('status') or '')
            if status and status not in {'completed', 'succeeded', 'ok'}:
                items.append({
                    'kind': 'trace',
                    'id': trace.get('trace_id'),
                    'label': trace.get('agent_id') or trace.get('trace_id'),
                    'status': status,
                    'ts': float(trace.get('ts') or 0.0),
                })
        for tool in list(tool_calls or []):
            if not bool(tool.get('ok')):
                items.append({
                    'kind': 'tool_call',
                    'id': tool.get('id'),
                    'label': tool.get('tool_name') or 'tool',
                    'status': 'failed',
                    'ts': float(tool.get('ts') or 0.0),
                    'error': tool.get('error'),
                })
        items.sort(key=lambda item: float(item.get('ts') or 0.0), reverse=True)
        return items[:max(1, int(limit))]

    @staticmethod
    def _safe_table_counts(gw, scope: dict[str, Any]) -> dict[str, Any]:
        table_counts_scoped = getattr(gw.audit, 'table_counts_scoped', None)
        if callable(table_counts_scoped):
            try:
                return dict(table_counts_scoped(**scope) or {})
            except Exception:
                return {}
        table_counts = getattr(gw.audit, 'table_counts', None)
        if callable(table_counts):
            try:
                return dict(table_counts() or {})
            except Exception:
                return {}
        return {}

    @staticmethod
    def _match_text(item: dict[str, Any], q: str, fields: list[str]) -> bool:
        if not q:
            return True
        haystacks: list[str] = []
        for field in fields:
            value = item.get(field)
            if isinstance(value, dict):
                haystacks.append(' '.join(str(v) for v in value.values() if v is not None))
            elif isinstance(value, list):
                haystacks.append(' '.join(str(v) for v in value if v is not None))
            elif value is not None:
                haystacks.append(str(value))
        return q in ' '.join(haystacks).lower()

    @staticmethod
    def _filter_sessions(items: list[dict[str, Any]], *, q: str, kind: str | None) -> list[dict[str, Any]]:
        if kind and kind not in {'session', 'all'}:
            return []
        return [item for item in items if OperatorConsoleService._match_text(item, q, ['session_id', 'channel', 'user_id', 'last_message'])]

    @staticmethod
    def _filter_workflows(items: list[dict[str, Any]], *, q: str, status: str | None, kind: str | None, only_failures: bool) -> list[dict[str, Any]]:
        if kind and kind not in {'workflow', 'failure', 'all'}:
            return []
        out: list[dict[str, Any]] = []
        for item in items:
            item_status = str(item.get('status') or '').lower()
            if status and item_status != status:
                continue
            if only_failures and item_status not in {'failed', 'rejected', 'cancelled'}:
                continue
            if not OperatorConsoleService._match_text(item, q, ['workflow_id', 'name', 'status', 'error', 'playbook_id']):
                continue
            out.append(item)
        return out

    @staticmethod
    def _filter_approvals(items: list[dict[str, Any]], *, q: str, status: str | None, kind: str | None, only_failures: bool) -> list[dict[str, Any]]:
        if kind and kind not in {'approval', 'all'}:
            return []
        out: list[dict[str, Any]] = []
        for item in items:
            item_status = str(item.get('status') or '').lower()
            if status and item_status != status:
                continue
            if only_failures and item_status not in {'rejected', 'expired'}:
                continue
            if not OperatorConsoleService._match_text(item, q, ['approval_id', 'workflow_id', 'requested_role', 'requested_by', 'assigned_to', 'status', 'reason', 'payload']):
                continue
            out.append(item)
        return out

    @staticmethod
    def _filter_traces(items: list[dict[str, Any]], *, q: str, status: str | None, kind: str | None, only_failures: bool) -> list[dict[str, Any]]:
        if kind and kind not in {'trace', 'failure', 'all'}:
            return []
        out: list[dict[str, Any]] = []
        for item in items:
            item_status = str(item.get('status') or '').lower()
            if status and item_status != status:
                continue
            if only_failures and item_status in {'completed', 'succeeded', 'ok', 'unknown'}:
                continue
            if not OperatorConsoleService._match_text(item, q, ['trace_id', 'agent_id', 'provider', 'model', 'status', 'request_text', 'response_text']):
                continue
            out.append(item)
        return out

    @staticmethod
    def _filter_events(items: list[dict[str, Any]], *, q: str, kind: str | None) -> list[dict[str, Any]]:
        if kind and kind not in {'event', 'all'}:
            return []
        out: list[dict[str, Any]] = []
        for item in items:
            payload = dict(item.get('payload') or {})
            merged = dict(item)
            merged['event_name'] = payload.get('event')
            merged['payload_text'] = payload
            if OperatorConsoleService._match_text(merged, q, ['channel', 'direction', 'user_id', 'session_id', 'event_name', 'payload_text']):
                out.append(item)
        return out

    @staticmethod
    def _filter_failures(items: list[dict[str, Any]], *, q: str, status: str | None, kind: str | None) -> list[dict[str, Any]]:
        if kind and kind not in {'failure', 'workflow', 'trace', 'tool_call', 'all'}:
            return []
        out: list[dict[str, Any]] = []
        for item in items:
            item_status = str(item.get('status') or '').lower()
            item_kind = str(item.get('kind') or '').lower()
            if kind and kind not in {'failure', 'all'} and item_kind != kind:
                continue
            if status and item_status != status:
                continue
            if not OperatorConsoleService._match_text(item, q, ['kind', 'id', 'label', 'status', 'error']):
                continue
            out.append(item)
        return out

    @staticmethod
    def _timeline_item_matches(item: dict[str, Any], *, q: str, status: str | None, kind: str | None, only_failures: bool) -> bool:
        item_kind = str(item.get('kind') or '').strip().lower()
        item_status = str(item.get('status') or ('failed' if item.get('ok') is False else 'ok' if item.get('ok') is True else '')).strip().lower()
        if kind and item_kind != kind:
            return False
        if status and item_status != status:
            return False
        if only_failures and item_status not in {'failed', 'rejected', 'cancelled', 'expired', 'error'} and item.get('ok') is not False:
            return False
        if not q:
            return True
        probe = dict(item)
        return OperatorConsoleService._match_text(probe, q, ['kind', 'label', 'content', 'event_name', 'tool_name', 'status', 'requested_role', 'approval_id', 'provider', 'model'])

    @staticmethod
    def _safe_call(obj: object, method_name: str, default: Any, *args: Any, **kwargs: Any) -> Any:
        method = getattr(obj, method_name, None)
        if callable(method):
            return method(*args, **kwargs)
        return default
