from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any


class SecretGovernanceService:
    def catalog(
        self,
        gw,
        *,
        q: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        broker = getattr(gw, 'secret_broker', None)
        if broker is None:
            return {'ok': False, 'reason': 'secret_broker_not_configured', 'items': []}
        refs = list(getattr(broker, 'list_refs', lambda: [])() or [])
        usage_map, raw_usage = self._usage_index(
            gw,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            limit=max(limit * 8, 400),
        )
        denied_map, raw_denied = self._denied_index(
            gw,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            limit=max(limit * 8, 400),
        )
        query = str(q or '').strip().lower()
        items: list[dict[str, Any]] = []
        for item in refs:
            ref = str(item.get('ref') or '').strip()
            merged = dict(item)
            usage = dict(usage_map.get(ref) or {})
            denied = dict(denied_map.get(ref) or {})
            merged['usage_count'] = int(usage.get('count') or 0)
            merged['denied_count'] = int(denied.get('count') or 0)
            merged['last_used_at'] = usage.get('last_used_at')
            merged['last_used_domain'] = usage.get('last_used_domain')
            merged['last_used_tool'] = usage.get('last_used_tool')
            merged['last_denied_at'] = denied.get('last_denied_at')
            merged['last_denied_domain'] = denied.get('last_denied_domain')
            merged['last_denied_tool'] = denied.get('last_denied_tool')
            merged['last_denied_reason'] = denied.get('last_denied_reason')
            merged['rotation'] = self._rotation_summary(item)
            merged['visibility'] = {
                'tenant_count': len(list(item.get('allowed_tenants') or [])),
                'workspace_count': len(list(item.get('allowed_workspaces') or [])),
                'environment_count': len(list(item.get('allowed_environments') or [])),
                'open_scope': not bool(item.get('allowed_tenants') or item.get('allowed_workspaces') or item.get('allowed_environments')),
            }
            if query and query not in self._search_blob(merged):
                continue
            items.append(merged)
        items.sort(key=lambda x: (-int(x.get('usage_count') or 0), str(x.get('ref') or '')))
        items = items[: max(1, int(limit))]
        configured = sum(1 for item in refs if bool(item.get('configured')))
        rotation_status = Counter(str((item.get('rotation') or {}).get('status') or 'unknown') for item in items)
        return {
            'ok': True,
            'summary': {
                'enabled': bool(getattr(broker, 'is_enabled', lambda: False)()),
                'total_refs': len(refs),
                'configured_refs': configured,
                'visible_refs': len(items),
                'usage_events': len(raw_usage),
                'denied_events': len(raw_denied),
                'rotation_status': dict(rotation_status),
            },
            'filters': {
                'q': query or None,
                'tenant_id': tenant_id,
                'workspace_id': workspace_id,
                'environment': environment,
                'limit': int(limit),
            },
            'items': items,
        }

    def usage(
        self,
        gw,
        *,
        q: str | None = None,
        ref: str | None = None,
        tool_name: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        usage_map, raw_usage = self._usage_index(
            gw,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            limit=max(limit * 10, 500),
        )
        query = str(q or '').strip().lower()
        ref_filter = str(ref or '').strip()
        tool_filter = str(tool_name or '').strip()
        items: list[dict[str, Any]] = []
        for item in usage_map.values():
            entry = dict(item)
            if ref_filter and str(entry.get('ref') or '') != ref_filter:
                continue
            if tool_filter and str(entry.get('last_used_tool') or '') != tool_filter and tool_filter not in set(entry.get('tools') or []):
                continue
            if query and query not in self._search_blob(entry):
                continue
            items.append(entry)
        items.sort(key=lambda x: (-int(x.get('count') or 0), -(float(x.get('last_used_at') or 0.0)), str(x.get('ref') or '')))
        items = items[: max(1, int(limit))]
        return {
            'ok': True,
            'summary': {
                'usage_groups': len(items),
                'raw_events': len(raw_usage),
                'refs_observed': len({str(item.get('ref') or '') for item in items if str(item.get('ref') or '').strip()}),
            },
            'filters': {
                'q': query or None,
                'ref': ref_filter or None,
                'tool_name': tool_filter or None,
                'tenant_id': tenant_id,
                'workspace_id': workspace_id,
                'environment': environment,
                'limit': int(limit),
            },
            'items': items,
        }


    def summary(
        self,
        gw,
        *,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        usage_map, raw_usage = self._usage_index(
            gw,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            limit=max(limit * 10, 500),
        )
        denied_map, raw_denied = self._denied_index(
            gw,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            limit=max(limit * 10, 500),
        )

        refs_used = Counter()
        refs_denied = Counter()
        tools = Counter()
        domains = Counter()
        recent_denied: list[dict[str, Any]] = []

        for item in raw_usage:
            payload = dict(item.get('payload') or {})
            ref = str(payload.get('ref') or '').strip()
            tool_name = str(payload.get('tool_name') or '').strip()
            domain = str(payload.get('domain') or '').strip()
            if ref:
                refs_used[ref] += 1
            if tool_name:
                tools[tool_name] += 1
            if domain:
                domains[domain] += 1

        for item in raw_denied:
            payload = dict(item.get('payload') or {})
            ref = str(payload.get('ref') or '').strip()
            tool_name = str(payload.get('tool_name') or '').strip()
            domain = str(payload.get('domain') or '').strip()
            reason = str(payload.get('reason') or '').strip() or None
            if ref:
                refs_denied[ref] += 1
            if tool_name:
                tools[tool_name] += 1
            if domain:
                domains[domain] += 1
            recent_denied.append(
                {
                    'ts': float(item.get('ts') or 0.0),
                    'ref': ref or None,
                    'tool_name': tool_name or None,
                    'domain': domain or None,
                    'reason': reason,
                    'tenant_id': item.get('tenant_id'),
                    'workspace_id': item.get('workspace_id'),
                    'environment': item.get('environment'),
                    'session_id': item.get('session_id'),
                    'channel': item.get('channel'),
                }
            )

        recent_denied.sort(key=lambda x: float(x.get('ts') or 0.0), reverse=True)

        recent_denied_limited = recent_denied[: max(1, int(limit))]
        return {
            'ok': True,
            'filters': {
                'tenant_id': tenant_id,
                'workspace_id': workspace_id,
                'environment': environment,
                'limit': int(limit),
            },
            'summary': {
                'total_events': len(raw_usage) + len(raw_denied),
                'resolved_events': len(raw_usage),
                'denied_events': len(raw_denied),
                'refs_observed': len(set(usage_map.keys()) | set(denied_map.keys())),
                'top_refs_used': [{'ref': k, 'value': k, 'count': v} for k, v in refs_used.most_common(max(1, int(limit)))],
                'top_used_refs': [{'ref': k, 'value': k, 'count': v} for k, v in refs_used.most_common(max(1, int(limit)))],
                'top_refs_denied': [{'ref': k, 'value': k, 'count': v} for k, v in refs_denied.most_common(max(1, int(limit)))],
                'top_denied_refs': [{'ref': k, 'value': k, 'count': v} for k, v in refs_denied.most_common(max(1, int(limit)))],
                'top_tools': [{'tool_name': k, 'value': k, 'count': v} for k, v in tools.most_common(max(1, int(limit)))],
                'top_domains': [{'domain': k, 'value': k, 'count': v} for k, v in domains.most_common(max(1, int(limit)))],
                'recent_denied': recent_denied_limited,
            },
            'recent_denied': recent_denied_limited,
        }

    def timeline(
        self,
        gw,
        *,
        q: str | None = None,
        ref: str | None = None,
        tool_name: str | None = None,
        outcome: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        audit = getattr(gw, 'audit', None)
        if audit is None:
            return {'ok': True, 'filters': {}, 'items': []}

        event_names = ['secret_resolved', 'secret_access_denied']
        items = list(
            getattr(audit, 'list_events_filtered', lambda **_: [])(
                limit=max(1, int(limit) * 10),
                event_names=event_names,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                environment=environment,
            )
            or []
        )

        query = str(q or '').strip().lower()
        ref_filter = str(ref or '').strip()
        tool_filter = str(tool_name or '').strip()
        outcome_filter = str(outcome or '').strip().lower()

        normalized: list[dict[str, Any]] = []
        for item in items:
            payload = dict(item.get('payload') or {})
            event_name = str(payload.get('event') or item.get('event') or '').strip()
            normalized_outcome = 'resolved' if event_name == 'secret_resolved' else 'denied'
            entry = {
                'ts': float(item.get('ts') or 0.0),
                'event': event_name,
                'outcome': normalized_outcome,
                'ref': str(payload.get('ref') or '').strip() or None,
                'tool_name': str(payload.get('tool_name') or '').strip() or None,
                'user_role': str(payload.get('user_role') or '').strip() or None,
                'domain': str(payload.get('domain') or '').strip() or None,
                'reason': str(payload.get('reason') or '').strip() or None,
                'allowed': payload.get('allowed'),
                'duration_ms': payload.get('duration_ms'),
                'session_id': item.get('session_id'),
                'channel': item.get('channel'),
                'tenant_id': item.get('tenant_id'),
                'workspace_id': item.get('workspace_id'),
                'environment': item.get('environment'),
            }
            if ref_filter and entry['ref'] != ref_filter:
                continue
            if tool_filter and entry['tool_name'] != tool_filter:
                continue
            if outcome_filter and entry['outcome'] != outcome_filter:
                continue
            if query:
                blob = ' '.join(str(v) for v in entry.values()).lower()
                if query not in blob:
                    continue
            normalized.append(entry)

        normalized.sort(key=lambda x: float(x.get('ts') or 0.0), reverse=True)
        normalized = normalized[: max(1, int(limit))]

        return {
            'ok': True,
            'filters': {
                'q': query or None,
                'ref': ref_filter or None,
                'tool_name': tool_filter or None,
                'outcome': outcome_filter or None,
                'tenant_id': tenant_id,
                'workspace_id': workspace_id,
                'environment': environment,
                'limit': int(limit),
            },
            'items': normalized,
        }

    def _denied_index(
        self,
        gw,
        *,
        tenant_id: str | None,
        workspace_id: str | None,
        environment: str | None,
        limit: int,
    ) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
        audit = getattr(gw, 'audit', None)
        if audit is None:
            return {}, []
        items = list(
            getattr(audit, 'list_events_filtered', lambda **_: [])(
                limit=max(1, int(limit)),
                event_names=['secret_access_denied'],
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                environment=environment,
            )
            or []
        )
        grouped: dict[str, dict[str, Any]] = {}
        for item in items:
            payload = dict(item.get('payload') or {})
            ref = str(payload.get('ref') or '').strip()
            if not ref:
                continue
            ts = float(item.get('ts') or 0.0)
            domain = str(payload.get('domain') or '').strip() or None
            tool_name = str(payload.get('tool_name') or '').strip() or None
            reason = str(payload.get('reason') or '').strip() or None
            bucket = grouped.setdefault(
                ref,
                {
                    'ref': ref,
                    'count': 0,
                    'last_denied_at': 0.0,
                    'last_denied_tool': None,
                    'last_denied_domain': None,
                    'last_denied_reason': None,
                    'tools': [],
                    'domains': [],
                    'reasons': [],
                },
            )
            bucket['count'] = int(bucket.get('count') or 0) + 1
            if ts >= float(bucket.get('last_denied_at') or 0.0):
                bucket['last_denied_at'] = ts
                bucket['last_denied_tool'] = tool_name
                bucket['last_denied_domain'] = domain
                bucket['last_denied_reason'] = reason
            self._add_unique(bucket, 'tools', tool_name)
            self._add_unique(bucket, 'domains', domain)
            self._add_unique(bucket, 'reasons', reason)
        return grouped, items

    def explain_access(
        self,
        gw,
        *,
        ref: str,
        tool_name: str,
        user_role: str = 'user',
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        environment: str | None = None,
        domain: str | None = None,
    ) -> dict[str, Any]:
        broker = getattr(gw, 'secret_broker', None)
        if broker is None:
            return {'ok': False, 'reason': 'secret_broker_not_configured'}
        response = broker.explain_access(
            ref,
            tool_name=tool_name,
            user_role=user_role,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            domain=domain,
        )
        usage_map, _ = self._usage_index(
            gw,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            environment=environment,
            limit=200,
        )
        response['recent_usage'] = usage_map.get(str(ref or '').strip())
        if isinstance(response.get('metadata'), dict):
            response['rotation'] = self._rotation_summary({'metadata': dict(response.get('metadata', {}).get('custom') or {})})
        return response

    def _usage_index(
        self,
        gw,
        *,
        tenant_id: str | None,
        workspace_id: str | None,
        environment: str | None,
        limit: int,
    ) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
        audit = getattr(gw, 'audit', None)
        if audit is None:
            return {}, []
        items = list(
            getattr(audit, 'list_events_filtered', lambda **_: [])(
                limit=max(1, int(limit)),
                event_names=['secret_resolved'],
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                environment=environment,
            )
            or []
        )
        grouped: dict[str, dict[str, Any]] = {}
        for item in items:
            payload = dict(item.get('payload') or {})
            ref = str(payload.get('ref') or '').strip()
            if not ref:
                continue
            ts = float(item.get('ts') or 0.0)
            domain = str(payload.get('domain') or '').strip() or None
            tool_name = str(payload.get('tool_name') or '').strip() or None
            bucket = grouped.setdefault(
                ref,
                {
                    'ref': ref,
                    'count': 0,
                    'last_used_at': 0.0,
                    'last_used_tool': None,
                    'last_used_domain': None,
                    'tools': [],
                    'domains': [],
                    'channels': [],
                    'tenants': [],
                    'workspaces': [],
                    'environments': [],
                },
            )
            bucket['count'] = int(bucket.get('count') or 0) + 1
            if ts >= float(bucket.get('last_used_at') or 0.0):
                bucket['last_used_at'] = ts
                bucket['last_used_tool'] = tool_name
                bucket['last_used_domain'] = domain
            self._add_unique(bucket, 'tools', tool_name)
            self._add_unique(bucket, 'domains', domain)
            self._add_unique(bucket, 'channels', item.get('channel'))
            self._add_unique(bucket, 'tenants', item.get('tenant_id'))
            self._add_unique(bucket, 'workspaces', item.get('workspace_id'))
            self._add_unique(bucket, 'environments', item.get('environment'))
        return grouped, items

    @staticmethod
    def _add_unique(bucket: dict[str, Any], key: str, value: Any) -> None:
        raw = str(value or '').strip()
        if not raw:
            return
        values = list(bucket.get(key) or [])
        if raw not in values:
            values.append(raw)
        bucket[key] = values

    def _rotation_summary(self, item: dict[str, Any]) -> dict[str, Any]:
        metadata = dict(item.get('metadata') or {})
        if 'custom' in metadata and isinstance(metadata.get('custom'), dict):
            metadata = dict(metadata.get('custom') or {})
        expires_ts = self._coerce_ts(metadata.get('expires_at'))
        rotated_ts = self._coerce_ts(metadata.get('last_rotated_at') or metadata.get('rotated_at'))
        now = datetime.now(timezone.utc).timestamp()
        status = 'unknown'
        if expires_ts is not None:
            if expires_ts <= now:
                status = 'expired'
            elif expires_ts - now <= 7 * 24 * 3600:
                status = 'expiring_soon'
            else:
                status = 'ok'
        elif rotated_ts is not None:
            status = 'tracked'
        return {
            'status': status,
            'owner': metadata.get('owner'),
            'provider': metadata.get('provider'),
            'last_rotated_at': rotated_ts,
            'expires_at': expires_ts,
            'rotation_days': metadata.get('rotation_days'),
            'labels': list(metadata.get('labels') or metadata.get('tags') or []),
        }

    @staticmethod
    def _coerce_ts(value: Any) -> float | None:
        if value in (None, ''):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        raw = str(value).strip()
        if not raw:
            return None
        try:
            return float(raw)
        except Exception:
            pass
        normalized = raw.replace('Z', '+00:00')
        try:
            return datetime.fromisoformat(normalized).astimezone(timezone.utc).timestamp()
        except Exception:
            return None

    @staticmethod
    def _search_blob(item: dict[str, Any]) -> str:
        parts: list[str] = []
        for key, value in dict(item or {}).items():
            if isinstance(value, dict):
                parts.append(SecretGovernanceService._search_blob(value))
            elif isinstance(value, list):
                parts.extend(str(v) for v in value)
            else:
                parts.append(str(value))
        return ' '.join(parts).lower()
