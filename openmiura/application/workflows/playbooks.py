from __future__ import annotations

import copy
import re
import time
from typing import Any


_PLAYBOOKS: dict[str, dict[str, Any]] = {
    'summary_daily': {
        'playbook_id': 'summary_daily',
        'version': '1.1.0',
        'name': 'Summary Daily',
        'name_template': 'Daily summary · {{input.subject}}',
        'description': 'Daily summary workflow with templated note and a time tool call.',
        'category': 'reporting',
        'tags': ['daily', 'summary', 'starter'],
        'defaults': {'subject': 'general'},
        'input_schema': {
            'type': 'object',
            'properties': {
                'subject': {'type': 'string', 'description': 'Topic of the summary'},
                'audience': {'type': 'string', 'description': 'Target audience label'},
            },
            'required': [],
        },
        'schedule_hints': [{'kind': 'cron', 'expr': '0 9 * * 1-5', 'timezone': 'Europe/Madrid'}],
        'examples': [{'input': {'subject': 'ops', 'audience': 'team'}}],
        'definition': {
            'steps': [
                {'id': 'intro', 'kind': 'note', 'note': 'Daily summary started for {{input.subject}}'},
                {'id': 'clock', 'kind': 'tool', 'tool_name': 'time_now', 'args': {}},
                {'id': 'outro', 'kind': 'note', 'note': 'Audience: {{input.audience}}'},
            ]
        },
    },
    'approval_gate': {
        'playbook_id': 'approval_gate',
        'version': '1.0.0',
        'name': 'Approval Gate',
        'description': 'Demonstrates a workflow paused on approval before continuing.',
        'category': 'governance',
        'tags': ['approval', 'review'],
        'defaults': {'requested_role': 'operator'},
        'input_schema': {
            'type': 'object',
            'properties': {
                'requested_role': {'type': 'string'},
                'message': {'type': 'string'},
            },
            'required': [],
        },
        'definition': {
            'steps': [
                {'id': 'intro', 'kind': 'note', 'note': '{{input.message}}'},
                {'id': 'approval', 'kind': 'approval', 'requested_role': '{{input.requested_role}}'},
                {'id': 'clock', 'kind': 'tool', 'tool_name': 'time_now', 'args': {}},
            ]
        },
    },
    'ticket_triage': {
        'playbook_id': 'ticket_triage',
        'version': '1.0.0',
        'name': 'Ticket Triage',
        'name_template': 'Ticket triage · {{input.subject}}',
        'description': 'Routes low-severity tickets automatically and gates high-severity ones with approval.',
        'category': 'operations',
        'tags': ['triage', 'branching', 'approval'],
        'defaults': {'severity': 'low', 'subject': 'ticket'},
        'input_schema': {
            'type': 'object',
            'properties': {
                'subject': {'type': 'string'},
                'severity': {'type': 'string', 'enum': ['low', 'medium', 'high']},
                'owner': {'type': 'string'},
            },
            'required': ['subject'],
        },
        'examples': [{'input': {'subject': 'payment mismatch', 'severity': 'high', 'owner': 'ops'}}],
        'definition': {
            'steps': [
                {'id': 'announce', 'kind': 'note', 'note': 'Triaging {{input.subject}} with severity {{input.severity}}'},
                {
                    'id': 'severity_branch',
                    'kind': 'branch',
                    'condition': {'left': '$input.severity', 'op': 'contains', 'right': 'high'},
                    'if_true_step_id': 'approval',
                    'if_false_step_id': 'auto_route',
                },
                {'id': 'auto_route', 'kind': 'note', 'note': 'Auto-routed to {{input.owner}}'},
                {'id': 'approval', 'kind': 'approval', 'requested_role': 'operator', 'expires_in_s': 900},
                {'id': 'stamp', 'kind': 'tool', 'tool_name': 'time_now', 'args': {}},
            ]
        },
    },
    'document_validation': {
        'playbook_id': 'document_validation',
        'version': '1.0.0',
        'name': 'Document Validation',
        'name_template': 'Document validation · {{input.document_id}}',
        'description': 'Collects a document identifier, asks for review and records a timestamp.',
        'category': 'compliance',
        'tags': ['documents', 'review', 'compliance'],
        'defaults': {'document_id': 'unknown', 'reviewer_role': 'auditor'},
        'input_schema': {
            'type': 'object',
            'properties': {
                'document_id': {'type': 'string'},
                'reviewer_role': {'type': 'string'},
            },
            'required': ['document_id'],
        },
        'definition': {
            'steps': [
                {'id': 'collect', 'kind': 'note', 'note': 'Validating document {{input.document_id}}'},
                {'id': 'review', 'kind': 'approval', 'requested_role': '{{input.reviewer_role}}'},
                {'id': 'stamp', 'kind': 'tool', 'tool_name': 'time_now', 'args': {}},
            ]
        },
    },
}


def _seed_registry() -> dict[str, dict[str, Any]]:
    registry: dict[str, dict[str, Any]] = {}
    now = time.time()
    for playbook_id, item in _PLAYBOOKS.items():
        version = str(item.get('version') or '1.0.0')
        entry = copy.deepcopy(item)
        entry.setdefault('publication_status', 'published')
        entry.setdefault('published_by', 'system')
        entry.setdefault('published_at', now)
        entry.setdefault('publication_notes', 'Built-in starter playbook')
        entry.setdefault('visibility', 'catalog')
        entry.setdefault('change_log', [{'version': version, 'notes': 'Initial built-in release', 'ts': now, 'actor': 'system'}])
        registry[playbook_id] = {
            'current_version': version,
            'versions': {version: entry},
            'default_version': version,
        }
    return registry


_PLAYBOOK_REGISTRY: dict[str, dict[str, Any]] = _seed_registry()


class PlaybookService:
    _TOKEN_RE = re.compile(r'\{\{\s*([^{}]+?)\s*\}\}')

    def _resolve_registry_entry(self, playbook_id: str, version: str | None = None) -> tuple[dict[str, Any], dict[str, Any]] | tuple[None, None]:
        key = str(playbook_id or '').strip()
        registry = _PLAYBOOK_REGISTRY.get(key)
        if registry is None:
            return None, None
        selected = str(version or registry.get('current_version') or registry.get('default_version') or '').strip()
        entry = registry.get('versions', {}).get(selected)
        if entry is None:
            return registry, None
        return registry, entry

    def _summary(self, item: dict[str, Any], *, registry: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = {
            'playbook_id': item['playbook_id'],
            'version': item.get('version', '1.0.0'),
            'name': item.get('name') or item['playbook_id'],
            'description': item.get('description') or '',
            'category': item.get('category') or 'general',
            'tags': list(item.get('tags') or []),
            'input_schema': copy.deepcopy(item.get('input_schema') or {'type': 'object', 'properties': {}}),
            'defaults': copy.deepcopy(item.get('defaults') or {}),
            'schedule_hints': copy.deepcopy(item.get('schedule_hints') or []),
            'examples': copy.deepcopy(item.get('examples') or []),
            'publication_status': item.get('publication_status', 'published'),
            'published_at': item.get('published_at'),
            'published_by': item.get('published_by'),
            'publication_notes': item.get('publication_notes') or '',
            'visibility': item.get('visibility', 'catalog'),
        }
        if registry is not None:
            payload['current_version'] = registry.get('current_version')
            payload['available_versions'] = sorted(list((registry.get('versions') or {}).keys()))
        return payload

    def list_playbooks(self, *, published_only: bool = False, include_versions: bool = False) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for playbook_id in sorted(_PLAYBOOK_REGISTRY.keys()):
            registry, entry = self._resolve_registry_entry(playbook_id)
            if entry is None:
                continue
            if published_only and str(entry.get('publication_status') or '') != 'published':
                continue
            payload = self._summary(entry, registry=registry)
            if include_versions:
                payload['versions'] = self.list_versions(playbook_id)
            items.append(payload)
        return items

    def get_playbook(self, playbook_id: str, *, version: str | None = None) -> dict[str, Any] | None:
        registry, item = self._resolve_registry_entry(playbook_id, version=version)
        if item is None:
            return None
        payload = self._summary(item, registry=registry)
        payload['definition'] = copy.deepcopy(item.get('definition') or {})
        payload['name_template'] = item.get('name_template')
        payload['change_log'] = copy.deepcopy(item.get('change_log') or [])
        return payload

    def list_versions(self, playbook_id: str) -> list[dict[str, Any]]:
        registry = _PLAYBOOK_REGISTRY.get(str(playbook_id or '').strip())
        if registry is None:
            return []
        versions = []
        for version, item in sorted((registry.get('versions') or {}).items()):
            versions.append(
                {
                    'version': version,
                    'name': item.get('name') or playbook_id,
                    'publication_status': item.get('publication_status', 'published'),
                    'published_at': item.get('published_at'),
                    'published_by': item.get('published_by'),
                    'publication_notes': item.get('publication_notes') or '',
                    'is_current': version == registry.get('current_version'),
                }
            )
        return versions

    def publish(self, playbook_id: str, *, actor: str, version: str | None = None, notes: str = '') -> dict[str, Any]:
        registry, item = self._resolve_registry_entry(playbook_id, version=version)
        if item is None or registry is None:
            raise LookupError('Unknown playbook')
        now = time.time()
        selected = str(item.get('version') or version or registry.get('current_version') or '1.0.0')
        entry = registry['versions'][selected]
        entry['publication_status'] = 'published'
        entry['published_at'] = now
        entry['published_by'] = str(actor or 'system')
        if notes:
            entry['publication_notes'] = str(notes)
            change_log = list(entry.get('change_log') or [])
            change_log.append({'version': selected, 'notes': str(notes), 'ts': now, 'actor': str(actor or 'system')})
            entry['change_log'] = change_log
        registry['current_version'] = selected
        return self.get_playbook(playbook_id, version=selected) or self._summary(entry, registry=registry)

    def deprecate(self, playbook_id: str, *, actor: str, version: str | None = None, notes: str = '') -> dict[str, Any]:
        registry, item = self._resolve_registry_entry(playbook_id, version=version)
        if item is None or registry is None:
            raise LookupError('Unknown playbook')
        selected = str(item.get('version') or version or registry.get('current_version') or '1.0.0')
        entry = registry['versions'][selected]
        entry['publication_status'] = 'deprecated'
        if notes:
            entry['publication_notes'] = str(notes)
            change_log = list(entry.get('change_log') or [])
            change_log.append({'version': selected, 'notes': str(notes), 'ts': time.time(), 'actor': str(actor or 'system')})
            entry['change_log'] = change_log
        return self.get_playbook(playbook_id, version=selected) or self._summary(entry, registry=registry)

    def _validate_type(self, value: Any, expected: str) -> bool:
        if expected == 'string':
            return isinstance(value, str)
        if expected == 'number':
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        if expected == 'integer':
            return isinstance(value, int) and not isinstance(value, bool)
        if expected == 'boolean':
            return isinstance(value, bool)
        if expected == 'array':
            return isinstance(value, list)
        if expected == 'object':
            return isinstance(value, dict)
        return True

    def _validate_input(self, schema: dict[str, Any], payload: dict[str, Any]) -> None:
        properties = dict(schema.get('properties') or {})
        required = [str(item) for item in list(schema.get('required') or [])]
        for key in required:
            if payload.get(key) in {None, ''}:
                raise ValueError(f"Missing required playbook input: {key}")
        for key, value in payload.items():
            spec = dict(properties.get(key) or {})
            expected = str(spec.get('type') or '').strip().lower()
            if expected and not self._validate_type(value, expected):
                raise ValueError(f"Invalid type for playbook input '{key}': expected {expected}")
            enum = list(spec.get('enum') or [])
            if enum and value not in enum:
                raise ValueError(f"Invalid value for playbook input '{key}': {value!r}")

    def _lookup(self, token: str, *, input_payload: dict[str, Any], scope: dict[str, Any]) -> Any:
        parts = [part for part in str(token or '').split('.') if part]
        if not parts:
            return ''
        if parts[0] == 'input':
            current: Any = input_payload
            parts = parts[1:]
        elif parts[0] == 'scope':
            current = scope
            parts = parts[1:]
        else:
            current = input_payload
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list) and part.isdigit():
                idx = int(part)
                current = current[idx] if 0 <= idx < len(current) else None
            else:
                return ''
            if current is None:
                return ''
        return current

    def _render_text(self, text: str, *, input_payload: dict[str, Any], scope: dict[str, Any]) -> str:
        def _replace(match: re.Match[str]) -> str:
            value = self._lookup(match.group(1), input_payload=input_payload, scope=scope)
            return '' if value is None else str(value)
        return self._TOKEN_RE.sub(_replace, str(text or ''))

    def _render_structure(self, value: Any, *, input_payload: dict[str, Any], scope: dict[str, Any]) -> Any:
        if isinstance(value, dict):
            return {str(key): self._render_structure(item, input_payload=input_payload, scope=scope) for key, item in value.items()}
        if isinstance(value, list):
            return [self._render_structure(item, input_payload=input_payload, scope=scope) for item in value]
        if isinstance(value, str):
            return self._render_text(value, input_payload=input_payload, scope=scope)
        return value

    def instantiate(
        self,
        gw,
        playbook_id: str,
        *,
        actor: str,
        name: str | None = None,
        input_payload: dict[str, Any] | None = None,
        autorun: bool = True,
        workflow_service,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        version: str | None = None,
    ) -> dict[str, Any]:
        registry, item = self._resolve_registry_entry(playbook_id, version=version)
        if item is None or registry is None:
            raise LookupError('Unknown playbook')
        if str(item.get('publication_status') or 'published') not in {'published', 'catalog'}:
            raise ValueError('Playbook version is not published')
        merged_input = dict(item.get('defaults') or {})
        merged_input.update(dict(input_payload or {}))
        self._validate_input(dict(item.get('input_schema') or {}), merged_input)
        scope = {'tenant_id': tenant_id or '', 'workspace_id': workspace_id or '', 'environment': environment or ''}
        rendered_definition = self._render_structure(copy.deepcopy(item.get('definition') or {}), input_payload=merged_input, scope=scope)
        rendered_name = str(name or self._render_text(str(item.get('name_template') or item.get('name') or playbook_id), input_payload=merged_input, scope=scope) or playbook_id)
        workflow = workflow_service.create_workflow(
            gw,
            name=rendered_name,
            definition=rendered_definition,
            created_by=actor,
            input_payload=merged_input,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            playbook_id=str(item.get('playbook_id') or playbook_id),
        )
        if autorun:
            return workflow_service.run_workflow(
                gw,
                workflow['workflow_id'],
                actor=actor,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                environment=environment,
            )
        return workflow
