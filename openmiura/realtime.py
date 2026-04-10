from __future__ import annotations

import queue
import threading
import time
from collections import deque
from typing import Any


class RealtimeBus:
    def __init__(self, *, history_limit: int = 2000) -> None:
        self._subscribers: list[queue.Queue[dict[str, Any]]] = []
        self._lock = threading.Lock()
        self._seq = 0
        self._history: deque[dict[str, Any]] = deque(maxlen=max(100, int(history_limit or 0)))

    def _normalize_event(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(payload or {})
        topic = normalized.get('topic') or str(event_type).split('_', 1)[0] or 'system'
        normalized.setdefault('topic', str(topic))
        normalized.setdefault('event_name', str(event_type))
        if 'entity_id' not in normalized:
            for key in ('workflow_id', 'approval_id', 'job_id', 'session_id'):
                if normalized.get(key) is not None:
                    normalized['entity_id'] = normalized.get(key)
                    break
        if 'entity_kind' not in normalized:
            if normalized.get('workflow_id') is not None:
                normalized['entity_kind'] = 'workflow'
            elif normalized.get('approval_id') is not None:
                normalized['entity_kind'] = 'approval'
            elif normalized.get('job_id') is not None:
                normalized['entity_kind'] = 'job'
            elif normalized.get('session_id') is not None:
                normalized['entity_kind'] = 'session'
        return normalized

    def publish(self, event_type: str, **payload: Any) -> dict[str, Any]:
        with self._lock:
            self._seq += 1
            normalized = self._normalize_event(event_type, payload)
            event = {'id': self._seq, 'seq': self._seq, 'ts': time.time(), 'type': event_type, **normalized}
            self._history.append(event)
            subscribers = list(self._subscribers)
        for q in subscribers:
            try:
                q.put_nowait(event)
            except queue.Full:
                pass
        return event

    def _matches(
        self,
        event: dict[str, Any],
        *,
        event_types: set[str] | None = None,
        topic: str | None = None,
        workflow_id: str | None = None,
        approval_id: str | None = None,
        job_id: str | None = None,
        entity_kind: str | None = None,
        entity_id: str | None = None,
        session_id: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        user_key: str | None = None,
        since_id: int | None = None,
    ) -> bool:
        if since_id is not None and int(event.get('id') or 0) <= int(since_id):
            return False
        if event_types and str(event.get('type') or '') not in event_types:
            return False
        if topic and str(event.get('topic') or '') != str(topic):
            return False
        if workflow_id and str(event.get('workflow_id') or '') != str(workflow_id):
            return False
        if approval_id and str(event.get('approval_id') or '') != str(approval_id):
            return False
        if job_id and str(event.get('job_id') or '') != str(job_id):
            return False
        if entity_kind and str(event.get('entity_kind') or '') != str(entity_kind):
            return False
        if entity_id and str(event.get('entity_id') or '') != str(entity_id):
            return False
        if session_id and str(event.get('session_id') or '') != str(session_id):
            return False
        if tenant_id and str(event.get('tenant_id') or '') != str(tenant_id):
            return False
        if workspace_id and str(event.get('workspace_id') or '') != str(workspace_id):
            return False
        if environment and str(event.get('environment') or '') != str(environment):
            return False
        if user_key and str(event.get('user_key') or '') not in {'', str(user_key)}:
            return False
        return True

    def recent(
        self,
        *,
        limit: int = 100,
        event_types: list[str] | None = None,
        topic: str | None = None,
        workflow_id: str | None = None,
        approval_id: str | None = None,
        job_id: str | None = None,
        entity_kind: str | None = None,
        entity_id: str | None = None,
        session_id: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        user_key: str | None = None,
        since_id: int | None = None,
    ) -> list[dict[str, Any]]:
        kinds = {str(item).strip() for item in (event_types or []) if str(item).strip()} or None
        with self._lock:
            items = list(self._history)
        filtered = [
            dict(event)
            for event in items
            if self._matches(
                event,
                event_types=kinds,
                topic=topic,
                workflow_id=workflow_id,
                approval_id=approval_id,
                job_id=job_id,
                entity_kind=entity_kind,
                entity_id=entity_id,
                session_id=session_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                environment=environment,
                user_key=user_key,
                since_id=since_id,
            )
        ]
        if limit > 0:
            filtered = filtered[-int(limit):]
        return filtered

    def subscribe(
        self,
        maxsize: int = 200,
        *,
        replay_last: int = 0,
        event_types: list[str] | None = None,
        topic: str | None = None,
        workflow_id: str | None = None,
        approval_id: str | None = None,
        job_id: str | None = None,
        entity_kind: str | None = None,
        entity_id: str | None = None,
        session_id: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        user_key: str | None = None,
        since_id: int | None = None,
    ) -> queue.Queue[dict[str, Any]]:
        q: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=maxsize)
        replay_items = self.recent(
            limit=max(0, int(replay_last or 0)),
            event_types=event_types,
            topic=topic,
            workflow_id=workflow_id,
            approval_id=approval_id,
            job_id=job_id,
            entity_kind=entity_kind,
            entity_id=entity_id,
            session_id=session_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            user_key=user_key,
            since_id=since_id,
        ) if replay_last or since_id is not None else []
        for item in replay_items:
            try:
                q.put_nowait(dict(item))
            except queue.Full:
                break
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue[dict[str, Any]]) -> None:
        with self._lock:
            self._subscribers = [item for item in self._subscribers if item is not q]

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                'subscribers': len(self._subscribers),
                'history_size': len(self._history),
                'last_event_id': self._seq,
            }
