from __future__ import annotations

import copy
import time
from typing import Any


class WorkflowService:
    def _publish(self, gw, event_type: str, **payload: Any) -> None:
        bus = getattr(gw, 'realtime_bus', None)
        if bus is None:
            return
        normalized = dict(payload or {})
        normalized.setdefault('topic', 'workflow')
        normalized.setdefault('entity_kind', 'workflow')
        if normalized.get('workflow_id') is not None:
            normalized.setdefault('entity_id', normalized.get('workflow_id'))
            normalized.setdefault('session_id', self._session_id(str(normalized.get('workflow_id'))))
        try:
            bus.publish(event_type, **normalized)
        except Exception:
            pass

    def _session_id(self, workflow_id: str) -> str:
        return f'workflow:{workflow_id}'

    def _log(self, gw, workflow_id: str, user_key: str, payload: dict[str, Any], *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> None:
        gw.audit.log_event(
            direction='workflow',
            channel='workflow',
            user_id=str(user_key or 'system'),
            session_id=self._session_id(workflow_id),
            payload=payload,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )

    def _normalize_step(self, raw: dict[str, Any], idx: int) -> dict[str, Any]:
        item = dict(raw or {})
        item['id'] = str(item.get('id') or f'step-{idx + 1}')
        item['kind'] = str(item.get('kind') or 'note').strip().lower() or 'note'
        item['name'] = str(item.get('name') or item['id'])
        item['retry_limit'] = max(0, int(item.get('retry_limit', item.get('retries', 0)) or 0))
        item['backoff_s'] = max(0.0, float(item.get('backoff_s', item.get('retry_backoff_s', 0.0)) or 0.0))
        item['timeout_s'] = float(item.get('timeout_s')) if item.get('timeout_s') is not None else None
        compensate = item.get('compensate') or item.get('compensations') or []
        item['compensate'] = [self._normalize_step(entry, j) for j, entry in enumerate(list(compensate))]
        if item['kind'] == 'tool':
            item['tool_name'] = str(item.get('tool_name') or item.get('name') or '').strip()
            item['args'] = dict(item.get('args') or {})
            if not item['tool_name']:
                raise ValueError(f"Workflow tool step '{item['id']}' requires tool_name")
        elif item['kind'] == 'approval':
            item['requested_role'] = str(item.get('requested_role') or 'operator').strip().lower() or 'operator'
            item['expires_in_s'] = float(item.get('expires_in_s')) if item.get('expires_in_s') is not None else None
        elif item['kind'] == 'branch':
            item['condition'] = dict(item.get('condition') or {})
            item['if_true_step_id'] = item.get('if_true_step_id') or item.get('then_step_id') or item.get('true_step_id')
            item['if_false_step_id'] = item.get('if_false_step_id') or item.get('else_step_id') or item.get('false_step_id')
        else:
            item['note'] = str(item.get('note') or item.get('message') or '')
        return item

    def _normalize_definition(self, definition: dict[str, Any]) -> dict[str, Any]:
        data = copy.deepcopy(dict(definition or {}))
        steps = list(data.get('steps') or [])
        normalized_steps: list[dict[str, Any]] = [self._normalize_step(raw, idx) for idx, raw in enumerate(steps)]
        if not normalized_steps:
            raise ValueError('Workflow definition must contain at least one step')
        data['steps'] = normalized_steps
        failure_compensations = list(data.get('on_failure') or data.get('failure_compensations') or [])
        data['on_failure'] = [self._normalize_step(raw, idx) for idx, raw in enumerate(failure_compensations)]
        return data

    def _step_result_lookup(self, context: dict[str, Any]) -> dict[str, Any]:
        lookup: dict[str, Any] = {}
        for entry in list(context.get('step_results') or []):
            step_id = str(entry.get('step_id') or '').strip()
            if step_id:
                lookup[step_id] = entry.get('result')
        return lookup

    def _resolve_structure(self, value: Any, context: dict[str, Any]) -> Any:
        if isinstance(value, dict):
            return {str(key): self._resolve_structure(item, context) for key, item in value.items()}
        if isinstance(value, list):
            return [self._resolve_structure(item, context) for item in value]
        return self._resolve_ref(value, context)

    def _resolve_ref(self, value: Any, context: dict[str, Any]) -> Any:
        if not isinstance(value, str) or not value.startswith('$'):
            return value
        token = value[1:]
        if token == 'last_result':
            results = list(context.get('step_results') or [])
            return results[-1].get('result') if results else None
        parts = token.split('.')
        if not parts:
            return None
        root: Any = None
        if parts[0] == 'input':
            root = context.get('input') or {}
            parts = parts[1:]
        elif parts[0] == 'context':
            root = context
            parts = parts[1:]
        elif parts[0] == 'step' and len(parts) >= 2:
            root = self._step_result_lookup(context).get(parts[1])
            parts = parts[2:]
        else:
            root = context
        current = root
        for part in parts:
            if current is None:
                return None
            if isinstance(current, dict):
                current = current.get(part)
                continue
            if isinstance(current, list) and part.isdigit():
                index = int(part)
                if 0 <= index < len(current):
                    current = current[index]
                    continue
                return None
            return None
        return current

    def _condition_matches(self, condition: dict[str, Any], context: dict[str, Any]) -> bool:
        if not condition:
            return False
        left = self._resolve_ref(condition.get('left'), context)
        right = self._resolve_ref(condition.get('right'), context)
        op = str(condition.get('op') or condition.get('operator') or 'eq').strip().lower()
        if op in {'truthy', 'exists'}:
            return bool(left)
        if op == 'falsy':
            return not bool(left)
        if op in {'eq', '==', 'equals'}:
            return left == right
        if op in {'ne', '!=', 'not_equals'}:
            return left != right
        if op in {'gt', '>'}:
            return left is not None and right is not None and left > right
        if op in {'gte', '>='}:
            return left is not None and right is not None and left >= right
        if op in {'lt', '<'}:
            return left is not None and right is not None and left < right
        if op in {'lte', '<='}:
            return left is not None and right is not None and left <= right
        if op == 'contains':
            try:
                return right in left
            except Exception:
                return False
        raise ValueError(f'Unsupported branch operator: {op}')

    def _find_step_index(self, steps: list[dict[str, Any]], step_id: str | None) -> int | None:
        if not step_id:
            return None
        needle = str(step_id).strip()
        for idx, step in enumerate(steps):
            if str(step.get('id') or '') == needle:
                return idx
        return None

    def _bounded_sleep(self, seconds: float) -> None:
        if seconds <= 0:
            return
        time.sleep(min(float(seconds), 0.05))

    def _run_compensation_steps(self, gw, workflow_id: str, actor: str, steps: list[dict[str, Any]], context: dict[str, Any], scope: dict[str, Any]) -> None:
        if not steps:
            return
        for raw in steps:
            step = dict(raw or {})
            step_id = str(step.get('id') or 'compensate')
            kind = str(step.get('kind') or 'note').strip().lower() or 'note'
            self._log(gw, workflow_id, actor, {'event': 'compensation_started', 'step_id': step_id, 'kind': kind}, **scope)
            self._publish(gw, 'workflow_compensation_started', workflow_id=workflow_id, step_id=step_id, kind=kind, **scope)
            try:
                if kind == 'note':
                    note = str(step.get('note') or step.get('name') or step_id)
                    context.setdefault('compensations', []).append({'step_id': step_id, 'kind': kind, 'note': note, 'ok': True})
                elif kind == 'tool':
                    result = gw.tools.run_tool(
                        agent_id='default',
                        session_id=self._session_id(workflow_id),
                        user_key=str(actor or 'system'),
                        tool_name=str(step.get('tool_name') or ''),
                        args=self._resolve_structure(dict(step.get('args') or {}), context),
                        confirmed=True,
                        tenant_id=scope.get('tenant_id'),
                        workspace_id=scope.get('workspace_id'),
                        environment=scope.get('environment'),
                    )
                    context.setdefault('compensations', []).append({'step_id': step_id, 'kind': kind, 'tool_name': step.get('tool_name'), 'result': result, 'ok': True})
                else:
                    context.setdefault('compensations', []).append({'step_id': step_id, 'kind': kind, 'ok': False, 'error': 'unsupported compensation kind'})
                self._log(gw, workflow_id, actor, {'event': 'compensation_completed', 'step_id': step_id, 'kind': kind}, **scope)
                self._publish(gw, 'workflow_compensation_completed', workflow_id=workflow_id, step_id=step_id, kind=kind, **scope)
            except Exception as exc:
                context.setdefault('compensations', []).append({'step_id': step_id, 'kind': kind, 'ok': False, 'error': str(exc)})
                self._log(gw, workflow_id, actor, {'event': 'compensation_failed', 'step_id': step_id, 'kind': kind, 'error': str(exc)}, **scope)
                self._publish(gw, 'workflow_compensation_failed', workflow_id=workflow_id, step_id=step_id, kind=kind, error=str(exc), **scope)

    def _execute_tool_step(self, gw, workflow_id: str, actor: str, item: dict[str, Any], step: dict[str, Any], context: dict[str, Any], scope: dict[str, Any]) -> Any:
        if getattr(gw, 'tools', None) is None:
            raise RuntimeError('Tool runtime not configured')
        retry_limit = max(0, int(step.get('retry_limit') or 0))
        max_attempts = retry_limit + 1
        backoff_s = max(0.0, float(step.get('backoff_s') or 0.0))
        timeout_s = step.get('timeout_s')
        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            started = time.time()
            self._log(gw, workflow_id, actor, {'event': 'tool_attempt_started', 'step_id': step['id'], 'tool_name': step.get('tool_name'), 'attempt': attempt}, **scope)
            try:
                result = gw.tools.run_tool(
                    agent_id='default',
                    session_id=self._session_id(workflow_id),
                    user_key=str(actor or item.get('created_by') or 'system'),
                    tool_name=str(step.get('tool_name') or ''),
                    args=self._resolve_structure(dict(step.get('args') or {}), context),
                    confirmed=True,
                    tenant_id=scope.get('tenant_id'),
                    workspace_id=scope.get('workspace_id'),
                    environment=scope.get('environment'),
                )
                duration = time.time() - started
                if timeout_s is not None and duration > float(timeout_s):
                    raise TimeoutError(f"Step '{step['id']}' exceeded timeout of {float(timeout_s):g}s")
                context.setdefault('step_attempts', {})[step['id']] = attempt
                context.setdefault('step_results', []).append({'step_id': step['id'], 'tool_name': step.get('tool_name'), 'attempt': attempt, 'result': result, 'duration_s': duration})
                return result
            except Exception as exc:
                last_error = exc
                context.setdefault('step_attempts', {})[step['id']] = attempt
                if attempt < max_attempts:
                    delay = backoff_s * (2 ** (attempt - 1)) if backoff_s else 0.0
                    self._log(gw, workflow_id, actor, {'event': 'step_retry_scheduled', 'step_id': step['id'], 'attempt': attempt, 'retry_in_s': delay, 'error': str(exc)}, **scope)
                    self._publish(gw, 'workflow_step_retry_scheduled', workflow_id=workflow_id, step_id=step['id'], attempt=attempt, retry_in_s=delay, error=str(exc), **scope)
                    self._bounded_sleep(delay)
                    continue
                raise
        if last_error is not None:
            raise last_error
        raise RuntimeError('Tool step failed without error')

    def create_workflow(
        self,
        gw,
        *,
        name: str,
        definition: dict[str, Any],
        created_by: str,
        input_payload: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        source_job_id: str | None = None,
        playbook_id: str | None = None,
    ) -> dict[str, Any]:
        normalized = self._normalize_definition(definition)
        context = {'input': dict(input_payload or {}), 'step_results': [], 'notes': [], 'step_attempts': {}, 'branches': [], 'compensations': []}
        item = gw.audit.create_workflow(
            name=str(name or 'workflow'),
            definition=normalized,
            created_by=str(created_by or 'system'),
            input_payload=dict(input_payload or {}),
            context=context,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            source_job_id=source_job_id,
            playbook_id=playbook_id,
        )
        self._log(
            gw,
            item['workflow_id'],
            created_by,
            {'event': 'workflow_created', 'workflow_id': item['workflow_id'], 'name': item['name'], 'source_job_id': item.get('source_job_id'), 'playbook_id': item.get('playbook_id')},
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        self._publish(
            gw,
            'workflow_created',
            workflow_id=item['workflow_id'],
            name=item['name'],
            source_job_id=item.get('source_job_id'),
            playbook_id=item.get('playbook_id'),
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
        )
        return item

    def list_workflows(self, gw, *, limit: int = 50, status: str | None = None, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any]:
        return {'ok': True, 'items': gw.audit.list_workflows(limit=limit, status=status, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)}

    def get_workflow(self, gw, workflow_id: str, *, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any] | None:
        return gw.audit.get_workflow(workflow_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)

    def timeline(self, gw, workflow_id: str, *, limit: int = 200, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any]:
        session_id = self._session_id(workflow_id)
        items = [
            event for event in gw.audit.get_recent_events(limit=limit, channel='workflow', tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
            if event.get('session_id') == session_id
        ]
        items.reverse()
        return {'ok': True, 'items': items}

    def unified_timeline(
        self,
        gw,
        *,
        limit: int = 200,
        workflow_id: str | None = None,
        approval_id: str | None = None,
        job_id: str | None = None,
        entity_kind: str | None = None,
        entity_id: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        items = gw.audit.get_recent_events(limit=max(limit * 4, 200), channel='workflow', tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        filtered: list[dict[str, Any]] = []
        for event in items:
            payload = dict(event.get('payload') or {})
            session_id = str(event.get('session_id') or '')
            if workflow_id and workflow_id not in {str(payload.get('workflow_id') or ''), session_id.removeprefix('workflow:')}:
                continue
            if approval_id and approval_id != str(payload.get('approval_id') or ''):
                continue
            if job_id and job_id not in {str(payload.get('job_id') or ''), str(payload.get('source_job_id') or ''), session_id.removeprefix('job:')}:
                continue
            derived_kind = entity_kind
            if derived_kind and derived_kind not in {'workflow', 'approval', 'job'}:
                continue
            if entity_kind == 'workflow' and not (str(payload.get('workflow_id') or '') or session_id.startswith('workflow:')):
                continue
            if entity_kind == 'approval' and not str(payload.get('approval_id') or ''):
                continue
            if entity_kind == 'job' and not (str(payload.get('job_id') or '') or str(payload.get('source_job_id') or '') or session_id.startswith('job:')):
                continue
            if entity_id:
                candidate_ids = {str(payload.get('workflow_id') or ''), str(payload.get('approval_id') or ''), str(payload.get('job_id') or ''), str(payload.get('source_job_id') or ''), session_id.removeprefix('workflow:'), session_id.removeprefix('job:')}
                if str(entity_id) not in candidate_ids:
                    continue
            filtered.append(event)
        filtered = filtered[:max(0, int(limit))]
        filtered.reverse()
        return {'ok': True, 'items': filtered}

    def run_workflow(self, gw, workflow_id: str, *, actor: str, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any]:
        item = self.get_workflow(gw, workflow_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if item is None:
            raise LookupError('Unknown workflow')
        if item.get('status') in {'succeeded', 'failed', 'rejected', 'cancelled'}:
            return item

        scope = {
            'tenant_id': item.get('tenant_id'),
            'workspace_id': item.get('workspace_id'),
            'environment': item.get('environment'),
        }
        context = dict(item.get('context') or {})
        context.setdefault('input', dict(item.get('input') or {}))
        context.setdefault('step_results', [])
        context.setdefault('notes', [])
        context.setdefault('step_attempts', {})
        context.setdefault('branches', [])
        context.setdefault('compensations', [])
        definition = dict(item.get('definition') or {})
        steps = list(definition.get('steps') or [])
        idx = int(item.get('current_step_index') or 0)
        now = time.time()
        if not item.get('started_at'):
            gw.audit.update_workflow_state(workflow_id, status='running', started_at=now, updated_at=now, **scope)
            self._log(gw, workflow_id, actor, {'event': 'workflow_started', 'workflow_id': workflow_id, 'source_job_id': item.get('source_job_id'), 'playbook_id': item.get('playbook_id')}, **scope)
            self._publish(gw, 'workflow_started', workflow_id=workflow_id, source_job_id=item.get('source_job_id'), playbook_id=item.get('playbook_id'), **scope)
        else:
            gw.audit.update_workflow_state(workflow_id, status='running', waiting_for_approval=False, updated_at=now, **scope)

        max_iterations = max(20, len(steps) * 20)
        iterations = 0
        while idx < len(steps):
            iterations += 1
            if iterations > max_iterations:
                error = 'Workflow exceeded maximum step iterations'
                self.fail_workflow(gw, workflow_id, actor=actor, error=error, **scope)
                raise RuntimeError(error)
            step = dict(steps[idx])
            step_id = str(step.get('id') or f'step-{idx + 1}')
            step_kind = str(step.get('kind') or 'note').strip().lower() or 'note'
            gw.audit.update_workflow_state(workflow_id, current_step_index=idx, current_step_id=step_id, waiting_for_approval=False, context=context, updated_at=time.time(), **scope)
            self._log(gw, workflow_id, actor, {'event': 'step_started', 'step_id': step_id, 'kind': step_kind}, **scope)
            self._publish(gw, 'workflow_step_started', workflow_id=workflow_id, step_id=step_id, kind=step_kind, **scope)

            try:
                if step_kind == 'note':
                    note = str(step.get('note') or step.get('name') or step_id)
                    context.setdefault('notes', []).append({'step_id': step_id, 'note': note})
                    self._log(gw, workflow_id, actor, {'event': 'step_completed', 'step_id': step_id, 'note': note}, **scope)
                    self._publish(gw, 'workflow_step_completed', workflow_id=workflow_id, step_id=step_id, kind=step_kind, source_job_id=item.get('source_job_id'), playbook_id=item.get('playbook_id'), **scope)
                    idx += 1
                    continue

                if step_kind == 'branch':
                    matched = self._condition_matches(dict(step.get('condition') or {}), context)
                    target = step.get('if_true_step_id') if matched else step.get('if_false_step_id')
                    next_idx = self._find_step_index(steps, target) if target else None
                    context.setdefault('branches', []).append({'step_id': step_id, 'matched': matched, 'target_step_id': target})
                    self._log(gw, workflow_id, actor, {'event': 'branch_evaluated', 'step_id': step_id, 'matched': matched, 'target_step_id': target}, **scope)
                    self._publish(gw, 'workflow_branch_evaluated', workflow_id=workflow_id, step_id=step_id, matched=matched, target_step_id=target, source_job_id=item.get('source_job_id'), playbook_id=item.get('playbook_id'), **scope)
                    self._log(gw, workflow_id, actor, {'event': 'step_completed', 'step_id': step_id, 'kind': step_kind}, **scope)
                    self._publish(gw, 'workflow_step_completed', workflow_id=workflow_id, step_id=step_id, kind=step_kind, source_job_id=item.get('source_job_id'), playbook_id=item.get('playbook_id'), **scope)
                    idx = next_idx if next_idx is not None else idx + 1
                    continue

                if step_kind == 'approval':
                    existing = [
                        entry for entry in gw.audit.list_approvals(limit=25, workflow_id=workflow_id, tenant_id=scope['tenant_id'], workspace_id=scope['workspace_id'], environment=scope['environment'])
                        if entry.get('step_id') == step_id
                    ]
                    latest = existing[0] if existing else None
                    if latest is not None and latest.get('status') == 'approved':
                        self._log(gw, workflow_id, actor, {'event': 'step_completed', 'step_id': step_id, 'kind': step_kind}, **scope)
                        self._publish(gw, 'workflow_step_completed', workflow_id=workflow_id, step_id=step_id, kind=step_kind, source_job_id=item.get('source_job_id'), playbook_id=item.get('playbook_id'), **scope)
                        idx += 1
                        continue
                    if latest is not None and latest.get('status') in {'rejected', 'expired'}:
                        return self.reject_workflow(gw, workflow_id, actor=actor, reason=str(latest.get('reason') or 'approval_rejected'), **scope) or item
                    pending = gw.audit.get_pending_approval_for_step(workflow_id, step_id, tenant_id=scope['tenant_id'], workspace_id=scope['workspace_id'], environment=scope['environment'])
                    if pending is not None and pending.get('expires_at') is not None and float(pending['expires_at']) <= time.time():
                        gw.audit.decide_approval(pending['approval_id'], decision='expire', decided_by='system', reason='approval_expired', tenant_id=scope['tenant_id'], workspace_id=scope['workspace_id'], environment=scope['environment'])
                        pending = None
                    if pending is None:
                        expires_at = None
                        if step.get('expires_in_s') is not None:
                            expires_at = time.time() + float(step.get('expires_in_s') or 0.0)
                        pending = gw.audit.create_approval(
                            workflow_id=workflow_id,
                            step_id=step_id,
                            requested_role=str(step.get('requested_role') or 'operator'),
                            requested_by=str(actor or item.get('created_by') or 'system'),
                            payload={'step': step, 'workflow_id': workflow_id},
                            expires_at=expires_at,
                            tenant_id=scope['tenant_id'],
                            workspace_id=scope['workspace_id'],
                            environment=scope['environment'],
                        )
                    gw.audit.update_workflow_state(workflow_id, status='waiting_approval', waiting_for_approval=True, current_step_index=idx, current_step_id=step_id, context=context, updated_at=time.time(), **scope)
                    self._log(gw, workflow_id, actor, {'event': 'waiting_for_approval', 'step_id': step_id, 'approval_id': pending['approval_id'], 'requested_role': pending['requested_role']}, **scope)
                    self._publish(gw, 'workflow_waiting_for_approval', workflow_id=workflow_id, step_id=step_id, approval_id=pending['approval_id'], requested_role=pending['requested_role'], source_job_id=item.get('source_job_id'), playbook_id=item.get('playbook_id'), **scope)
                    return gw.audit.get_workflow(workflow_id, **scope) or item

                if step_kind == 'tool':
                    self._execute_tool_step(gw, workflow_id, actor, item, step, context, scope)
                    self._log(gw, workflow_id, actor, {'event': 'step_completed', 'step_id': step_id, 'tool_name': step.get('tool_name')}, **scope)
                    self._publish(gw, 'workflow_step_completed', workflow_id=workflow_id, step_id=step_id, kind=step_kind, source_job_id=item.get('source_job_id'), playbook_id=item.get('playbook_id'), **scope)
                    idx += 1
                    continue

                raise ValueError(f'Unsupported workflow step kind: {step_kind}')
            except Exception as exc:
                self._log(gw, workflow_id, actor, {'event': 'step_failed', 'step_id': step_id, 'kind': step_kind, 'error': str(exc)}, **scope)
                self._publish(gw, 'workflow_step_failed', workflow_id=workflow_id, step_id=step_id, kind=step_kind, error=str(exc), source_job_id=item.get('source_job_id'), playbook_id=item.get('playbook_id'), **scope)
                compensation_steps = list(step.get('compensate') or []) + list(definition.get('on_failure') or [])
                if compensation_steps:
                    self._run_compensation_steps(gw, workflow_id, actor, compensation_steps, context, scope)
                    gw.audit.update_workflow_state(workflow_id, context=context, updated_at=time.time(), **scope)
                self.fail_workflow(gw, workflow_id, actor=actor, error=str(exc), **scope)
                raise

        gw.audit.update_workflow_state(workflow_id, status='succeeded', waiting_for_approval=False, current_step_index=len(steps), current_step_id=None, context=context, finished_at=time.time(), updated_at=time.time(), error='', **scope)
        self._log(gw, workflow_id, actor, {'event': 'workflow_succeeded', 'workflow_id': workflow_id, 'source_job_id': item.get('source_job_id'), 'playbook_id': item.get('playbook_id')}, **scope)
        self._publish(gw, 'workflow_succeeded', workflow_id=workflow_id, source_job_id=item.get('source_job_id'), playbook_id=item.get('playbook_id'), **scope)
        return gw.audit.get_workflow(workflow_id, **scope) or item

    def reject_workflow(self, gw, workflow_id: str, *, actor: str, reason: str = '', tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any] | None:
        item = self.get_workflow(gw, workflow_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if item is None:
            return None
        scope = {'tenant_id': item.get('tenant_id'), 'workspace_id': item.get('workspace_id'), 'environment': item.get('environment')}
        gw.audit.update_workflow_state(workflow_id, status='rejected', waiting_for_approval=False, finished_at=time.time(), updated_at=time.time(), error=str(reason or ''), **scope)
        self._log(gw, workflow_id, actor, {'event': 'workflow_rejected', 'workflow_id': workflow_id, 'reason': reason, 'source_job_id': item.get('source_job_id'), 'playbook_id': item.get('playbook_id')}, **scope)
        self._publish(gw, 'workflow_rejected', workflow_id=workflow_id, reason=reason, source_job_id=item.get('source_job_id'), playbook_id=item.get('playbook_id'), **scope)
        return gw.audit.get_workflow(workflow_id, **scope)

    def cancel_workflow(self, gw, workflow_id: str, *, actor: str, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any] | None:
        item = self.get_workflow(gw, workflow_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if item is None:
            return None
        scope = {'tenant_id': item.get('tenant_id'), 'workspace_id': item.get('workspace_id'), 'environment': item.get('environment')}
        gw.audit.update_workflow_state(workflow_id, status='cancelled', waiting_for_approval=False, finished_at=time.time(), updated_at=time.time(), **scope)
        self._log(gw, workflow_id, actor, {'event': 'workflow_cancelled', 'workflow_id': workflow_id, 'source_job_id': item.get('source_job_id'), 'playbook_id': item.get('playbook_id')}, **scope)
        self._publish(gw, 'workflow_cancelled', workflow_id=workflow_id, source_job_id=item.get('source_job_id'), playbook_id=item.get('playbook_id'), **scope)
        return gw.audit.get_workflow(workflow_id, **scope)

    def fail_workflow(self, gw, workflow_id: str, *, actor: str, error: str, tenant_id: str | None = None, workspace_id: str | None = None, environment: str | None = None) -> dict[str, Any] | None:
        item = self.get_workflow(gw, workflow_id, tenant_id=tenant_id, workspace_id=workspace_id, environment=environment)
        if item is None:
            return None
        scope = {'tenant_id': item.get('tenant_id'), 'workspace_id': item.get('workspace_id'), 'environment': item.get('environment')}
        gw.audit.update_workflow_state(workflow_id, status='failed', waiting_for_approval=False, finished_at=time.time(), updated_at=time.time(), error=str(error or ''), **scope)
        self._log(gw, workflow_id, actor, {'event': 'workflow_failed', 'workflow_id': workflow_id, 'error': error, 'source_job_id': item.get('source_job_id'), 'playbook_id': item.get('playbook_id')}, **scope)
        self._publish(gw, 'workflow_failed', workflow_id=workflow_id, error=error, source_job_id=item.get('source_job_id'), playbook_id=item.get('playbook_id'), **scope)
        return gw.audit.get_workflow(workflow_id, **scope)
