from __future__ import annotations

import hashlib
from collections import Counter
from typing import Any

from openmiura.application.workflows import WorkflowService


class ReplayService:
    def __init__(self, *, workflow_service: WorkflowService | None = None) -> None:
        self.workflow_service = workflow_service or WorkflowService()

    def session_replay(
        self,
        gw,
        *,
        session_id: str,
        limit: int = 200,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        session = self._find_session(
            gw,
            session_id=session_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            limit=max(limit * 3, 500),
        )
        messages = self._safe_call(gw.audit, 'get_session_messages', [], session_id, limit=limit)
        tool_calls = self._safe_call(
            gw.audit,
            'list_tool_calls',
            [],
            limit=limit,
            session_id=session_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        traces = self._safe_call(
            gw.audit,
            'list_decision_traces',
            [],
            limit=limit,
            session_id=session_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        events = [
            event
            for event in self._safe_call(
                gw.audit,
                'list_events_filtered',
                [],
                limit=max(limit * 8, 600),
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                environment=environment,
            )
            if str(event.get('session_id') or '') == str(session_id)
        ]
        events = list(reversed(events[:limit]))
        timeline = self._session_timeline(messages=messages, events=events, tool_calls=tool_calls, traces=traces)
        summary = self._timeline_summary(kind='session', entity_id=session_id, timeline=timeline, session=session, messages=messages, tool_calls=tool_calls, traces=traces)
        return {
            'ok': True,
            'kind': 'session',
            'session_id': session_id,
            'session': session,
            'messages': messages,
            'events': events,
            'tool_calls': tool_calls,
            'traces': traces,
            'timeline': timeline,
            'summary': summary,
        }

    def workflow_replay(
        self,
        gw,
        *,
        workflow_id: str,
        limit: int = 200,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        workflow = self.workflow_service.get_workflow(
            gw,
            workflow_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        if workflow is None:
            return {'ok': False, 'reason': 'workflow_not_found', 'workflow_id': workflow_id}
        session_id = f'workflow:{workflow_id}'
        messages = self._safe_call(gw.audit, 'get_session_messages', [], session_id, limit=limit)
        tool_calls = self._safe_call(
            gw.audit,
            'list_tool_calls',
            [],
            limit=limit,
            session_id=session_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        traces = self._safe_call(
            gw.audit,
            'list_decision_traces',
            [],
            limit=limit,
            session_id=session_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        approvals = self._safe_call(
            gw.audit,
            'list_approvals',
            [],
            limit=limit,
            workflow_id=workflow_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        event_payload = self.workflow_service.unified_timeline(
            gw,
            limit=limit,
            workflow_id=workflow_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        events = list(event_payload.get('items') or [])
        timeline = self._workflow_timeline(messages=messages, events=events, tool_calls=tool_calls, traces=traces, approvals=approvals)
        summary = self._timeline_summary(kind='workflow', entity_id=workflow_id, timeline=timeline, workflow=workflow, messages=messages, tool_calls=tool_calls, traces=traces)
        summary['approval_count'] = len(approvals)
        summary['step_count'] = len(list((workflow.get('definition') or {}).get('steps') or []))
        return {
            'ok': True,
            'kind': 'workflow',
            'workflow_id': workflow_id,
            'workflow': workflow,
            'session_id': session_id,
            'messages': messages,
            'events': events,
            'tool_calls': tool_calls,
            'traces': traces,
            'approvals': approvals,
            'timeline': timeline,
            'summary': summary,
        }

    def compare_replays(
        self,
        gw,
        *,
        left_kind: str,
        left_id: str,
        right_kind: str,
        right_id: str,
        limit: int = 200,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        left = self._load_replay(
            gw,
            kind=left_kind,
            entity_id=left_id,
            limit=limit,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        right = self._load_replay(
            gw,
            kind=right_kind,
            entity_id=right_id,
            limit=limit,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        if not left.get('ok'):
            return {'ok': False, 'reason': 'left_not_found', 'left': left}
        if not right.get('ok'):
            return {'ok': False, 'reason': 'right_not_found', 'right': right}

        left_summary = dict(left.get('summary') or {})
        right_summary = dict(right.get('summary') or {})
        numeric_fields = [
            'message_count',
            'event_count',
            'tool_call_count',
            'trace_count',
            'memory_hits',
            'duration_ms',
            'approval_count',
            'step_count',
        ]
        metrics_diff: dict[str, Any] = {}
        for field in numeric_fields:
            lv = left_summary.get(field)
            rv = right_summary.get(field)
            if isinstance(lv, (int, float)) and isinstance(rv, (int, float)):
                metrics_diff[field] = {'left': lv, 'right': rv, 'delta': rv - lv}

        left_timeline = list(left.get('timeline') or [])
        right_timeline = list(right.get('timeline') or [])
        left_event_names = Counter(item.get('event_name') or item.get('label') for item in left_timeline if item.get('kind') == 'event')
        right_event_names = Counter(item.get('event_name') or item.get('label') for item in right_timeline if item.get('kind') == 'event')
        left_tools = Counter(str(item.get('tool_name') or '') for item in (left.get('tool_calls') or []) if str(item.get('tool_name') or '').strip())
        right_tools = Counter(str(item.get('tool_name') or '') for item in (right.get('tool_calls') or []) if str(item.get('tool_name') or '').strip())
        left_kinds = Counter(str(item.get('kind') or '') for item in left_timeline if str(item.get('kind') or '').strip())
        right_kinds = Counter(str(item.get('kind') or '') for item in right_timeline if str(item.get('kind') or '').strip())
        left_statuses = Counter(self._timeline_status(item) for item in left_timeline if self._timeline_status(item))
        right_statuses = Counter(self._timeline_status(item) for item in right_timeline if self._timeline_status(item))
        left_signatures = Counter(self._timeline_signature(item) for item in left_timeline if self._timeline_signature(item))
        right_signatures = Counter(self._timeline_signature(item) for item in right_timeline if self._timeline_signature(item))

        left_fingerprint = self._timeline_fingerprint(left_timeline)
        right_fingerprint = self._timeline_fingerprint(right_timeline)
        changed = left_fingerprint != right_fingerprint or any(abs((entry.get('delta') or 0)) > 0 for entry in metrics_diff.values())
        return {
            'ok': True,
            'left': {'kind': left_kind, 'id': left_id, 'summary': left_summary, 'fingerprint': left_fingerprint},
            'right': {'kind': right_kind, 'id': right_id, 'summary': right_summary, 'fingerprint': right_fingerprint},
            'changed': changed,
            'metrics_diff': metrics_diff,
            'event_name_diff': self._counter_diff(left_event_names, right_event_names),
            'tool_diff': self._counter_diff(left_tools, right_tools),
            'timeline_kind_diff': self._counter_diff(left_kinds, right_kinds),
            'timeline_status_diff': self._counter_diff(left_statuses, right_statuses),
            'timeline_signature_diff': self._counter_diff(left_signatures, right_signatures, limit=12),
            'status': {
                'left': left_summary.get('status') or (left.get('workflow') or {}).get('status'),
                'right': right_summary.get('status') or (right.get('workflow') or {}).get('status'),
                'changed': (left_summary.get('status') or (left.get('workflow') or {}).get('status')) != (right_summary.get('status') or (right.get('workflow') or {}).get('status')),
            },
            'agents': {
                'left': sorted({str(item.get('agent_id') or '') for item in (left.get('traces') or []) if str(item.get('agent_id') or '').strip()}),
                'right': sorted({str(item.get('agent_id') or '') for item in (right.get('traces') or []) if str(item.get('agent_id') or '').strip()}),
            },
            'providers': {
                'left': sorted({f"{item.get('provider') or ''}:{item.get('model') or ''}" for item in (left.get('traces') or []) if (item.get('provider') or item.get('model'))}),
                'right': sorted({f"{item.get('provider') or ''}:{item.get('model') or ''}" for item in (right.get('traces') or []) if (item.get('provider') or item.get('model'))}),
            },
        }

    def _load_replay(self, gw, *, kind: str, entity_id: str, limit: int, tenant_id: str | None, workspace_id: str | None, environment: str | None) -> dict[str, Any]:
        normalized = str(kind or '').strip().lower()
        if normalized == 'session':
            return self.session_replay(gw, session_id=entity_id, limit=limit, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if normalized == 'workflow':
            return self.workflow_replay(gw, workflow_id=entity_id, limit=limit, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        return {'ok': False, 'reason': 'unsupported_kind', 'kind': normalized}

    @staticmethod
    def _find_session(gw, *, session_id: str, tenant_id: str | None, workspace_id: str | None, environment: str | None, limit: int) -> dict[str, Any] | None:
        sessions = ReplayService._safe_call(
            gw.audit,
            'list_sessions',
            [],
            limit=limit,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        return next((item for item in sessions if str(item.get('session_id') or '') == str(session_id)), None)

    @staticmethod
    def _session_timeline(*, messages: list[dict[str, Any]], events: list[dict[str, Any]], tool_calls: list[dict[str, Any]], traces: list[dict[str, Any]]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for msg in list(messages or []):
            items.append({
                'kind': 'message',
                'ts': float(msg.get('ts') or 0.0),
                'label': str(msg.get('role') or 'message'),
                'content': str(msg.get('content') or ''),
                'message_id': msg.get('id'),
            })
        for event in list(events or []):
            payload = dict(event.get('payload') or {})
            items.append({
                'kind': 'event',
                'ts': float(event.get('ts') or 0.0),
                'label': str(payload.get('event') or f"{event.get('channel')}:{event.get('direction')}").strip(),
                'event_name': str(payload.get('event') or ''),
                'event_id': event.get('id'),
                'payload': payload,
            })
        for tool in list(tool_calls or []):
            items.append({
                'kind': 'tool_call',
                'ts': float(tool.get('ts') or 0.0),
                'label': str(tool.get('tool_name') or 'tool'),
                'tool_name': str(tool.get('tool_name') or ''),
                'ok': bool(tool.get('ok')),
                'duration_ms': float(tool.get('duration_ms') or 0.0),
                'agent_id': tool.get('agent_id'),
            })
        for trace in list(traces or []):
            items.append({
                'kind': 'trace',
                'ts': float(trace.get('ts') or 0.0),
                'label': str(trace.get('agent_id') or 'trace'),
                'trace_id': trace.get('trace_id'),
                'status': trace.get('status'),
                'provider': trace.get('provider'),
                'model': trace.get('model'),
                'latency_ms': float(trace.get('latency_ms') or 0.0),
            })
        items.sort(key=lambda entry: (float(entry.get('ts') or 0.0), str(entry.get('kind') or '')))
        return items

    def _workflow_timeline(self, *, messages: list[dict[str, Any]], events: list[dict[str, Any]], tool_calls: list[dict[str, Any]], traces: list[dict[str, Any]], approvals: list[dict[str, Any]]) -> list[dict[str, Any]]:
        items = self._session_timeline(messages=messages, events=events, tool_calls=tool_calls, traces=traces)
        for approval in list(approvals or []):
            items.append({
                'kind': 'approval',
                'ts': float(approval.get('updated_at') or approval.get('created_at') or 0.0),
                'label': str(approval.get('approval_id') or 'approval'),
                'approval_id': approval.get('approval_id'),
                'status': approval.get('status'),
                'requested_role': approval.get('requested_role'),
            })
        items.sort(key=lambda entry: (float(entry.get('ts') or 0.0), str(entry.get('kind') or '')))
        return items

    @staticmethod
    def _timeline_summary(*, kind: str, entity_id: str, timeline: list[dict[str, Any]], session: dict[str, Any] | None = None, workflow: dict[str, Any] | None = None, messages: list[dict[str, Any]] | None = None, tool_calls: list[dict[str, Any]] | None = None, traces: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        message_count = len(list(messages or []))
        tool_count = len(list(tool_calls or []))
        trace_count = len(list(traces or []))
        first_ts = float(timeline[0].get('ts') or 0.0) if timeline else 0.0
        last_ts = float(timeline[-1].get('ts') or 0.0) if timeline else 0.0
        memory_hits = sum(len(list((item.get('memory') or {}).get('items') or [])) for item in (traces or []))
        event_names = [str(item.get('event_name') or item.get('label') or '') for item in timeline if item.get('kind') == 'event']
        summary = {
            'kind': kind,
            'entity_id': entity_id,
            'status': (workflow or {}).get('status') or None,
            'message_count': message_count,
            'event_count': len([item for item in timeline if item.get('kind') == 'event']),
            'tool_call_count': tool_count,
            'trace_count': trace_count,
            'memory_hits': memory_hits,
            'duration_ms': max(0.0, (last_ts - first_ts) * 1000.0) if timeline else 0.0,
            'first_ts': first_ts or None,
            'last_ts': last_ts or None,
            'event_names': [item for item in event_names if item],
            'tools_used': sorted({str(item.get('tool_name') or '') for item in (tool_calls or []) if str(item.get('tool_name') or '').strip()}),
            'fingerprint': ReplayService._timeline_fingerprint(timeline),
        }
        if session is not None:
            summary['channel'] = session.get('channel')
            summary['user_id'] = session.get('user_id')
        if workflow is not None:
            summary['workflow_name'] = workflow.get('name')
            summary['playbook_id'] = workflow.get('playbook_id')
        return summary

    @staticmethod
    def _timeline_fingerprint(timeline: list[dict[str, Any]]) -> str:
        normalized = [f"{item.get('kind')}|{item.get('label')}|{item.get('status') or item.get('ok') or ''}" for item in timeline]
        return hashlib.sha256("\n".join(normalized).encode('utf-8')).hexdigest()[:16]

    @staticmethod
    def _counter_diff(left: Counter[str], right: Counter[str], *, limit: int | None = None) -> dict[str, Any]:
        keys = sorted({*left.keys(), *right.keys()})
        items = [
            {'name': key, 'left': int(left.get(key, 0)), 'right': int(right.get(key, 0)), 'delta': int(right.get(key, 0) - left.get(key, 0))}
            for key in keys
            if key
        ]
        if limit is not None:
            items = sorted(items, key=lambda item: abs(int(item.get('delta') or 0)), reverse=True)[:limit]
        return {
            'items': items,
            'changed': [key for key in keys if left.get(key, 0) != right.get(key, 0)],
        }

    @staticmethod
    def _timeline_status(item: dict[str, Any]) -> str:
        if item.get('status') is not None:
            return str(item.get('status') or '').strip().lower()
        if item.get('ok') is True:
            return 'ok'
        if item.get('ok') is False:
            return 'failed'
        return ''

    @staticmethod
    def _timeline_signature(item: dict[str, Any]) -> str:
        kind = str(item.get('kind') or '').strip()
        label = str(item.get('label') or '').strip()
        status = ReplayService._timeline_status(item)
        if not kind and not label:
            return ''
        return f"{kind}|{label}|{status}"

    @staticmethod
    def _safe_call(obj: object, method_name: str, default: Any, *args: Any, **kwargs: Any) -> Any:
        method = getattr(obj, method_name, None)
        if callable(method):
            return method(*args, **kwargs)
        return default
