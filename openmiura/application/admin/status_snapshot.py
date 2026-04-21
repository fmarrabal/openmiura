from __future__ import annotations

import time
from typing import Any, Callable

from openmiura.core.contracts import AdminGatewayLike

SafeCall = Callable[..., Any]


def collect_registered_tool_names(tools_obj: Any) -> list[str]:
    registry = getattr(tools_obj, 'registry', None)
    if registry is None:
        return []
    raw_tools = getattr(registry, '_tools', {}) or {}
    try:
        return sorted(raw_tools.keys())
    except Exception:
        return []


def build_status_snapshot(
    gw: AdminGatewayLike,
    *,
    safe_call: SafeCall,
    tenancy_catalog: dict[str, Any],
    tool_names: list[str],
) -> dict[str, Any]:
    counts = safe_call(gw.audit, 'table_counts', {})
    router_obj = getattr(gw, 'router', None)
    policy_obj = getattr(gw, 'policy', None)
    started_at = float(getattr(gw, 'started_at', time.time()))
    uptime_s = time.time() - started_at
    settings = getattr(gw, 'settings', None)
    memory_cfg = getattr(settings, 'memory', None)
    llm_cfg = getattr(settings, 'llm', None)
    storage_cfg = getattr(settings, 'storage', None)
    sandbox_obj = getattr(gw, 'sandbox', None)
    sandbox_profiles = getattr(sandbox_obj, 'profiles_catalog', lambda: {})() or {}

    return {
        'ok': True,
        'service': 'openMiura',
        'uptime_s': uptime_s,
        'llm': {
            'provider': getattr(llm_cfg, 'provider', ''),
            'model': getattr(llm_cfg, 'model', ''),
            'base_url': getattr(llm_cfg, 'base_url', ''),
        },
        'router': {
            'agents': router_obj.available_agents() if router_obj and hasattr(router_obj, 'available_agents') else [],
            'agents_path': getattr(settings, 'agents_path', 'agents.yaml'),
        },
        'policy': {
            'enabled': policy_obj is not None,
            'policies_path': getattr(settings, 'policies_path', 'policies.yaml'),
            'signature': safe_call(policy_obj, 'signature', None),
        },
        'sandbox': {
            'enabled': bool(getattr(getattr(settings, 'sandbox', None), 'enabled', True)),
            'default_profile': getattr(getattr(settings, 'sandbox', None), 'default_profile', 'local-safe'),
            'profiles': sorted(list(sandbox_profiles.keys())),
        },
        'memory': {
            'enabled': bool(memory_cfg and getattr(memory_cfg, 'enabled', False)),
            'embed_model': getattr(memory_cfg, 'embed_model', ''),
            'total_items': safe_call(gw.audit, 'count_memory_items', 0),
        },
        'tools': {
            'registered': tool_names,
        },
        'channels': {
            'telegram_configured': getattr(gw, 'telegram', None) is not None,
            'slack_configured': getattr(gw, 'slack', None) is not None,
        },
        'sessions': {
            'total': safe_call(gw.audit, 'count_sessions', 0),
            'active_24h': safe_call(gw.audit, 'count_active_sessions', 0, window_s=86400),
        },
        'events': {
            'last': safe_call(gw.audit, 'get_last_event', None),
        },
        'db': {
            'path': getattr(storage_cfg, 'db_path', ''),
            'counts': counts,
        },
        'tenancy': tenancy_catalog,
    }


__all__ = ['collect_registered_tool_names', 'build_status_snapshot']
