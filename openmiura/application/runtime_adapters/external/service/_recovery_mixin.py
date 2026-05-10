"""service._recovery_mixin"""
from __future__ import annotations

import copy
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from openmiura.core.secrets import SecretAccessDenied, SecretBrokerError



OpenClawAdapterService: type | None = None  # late-bound


class _OpenClawAdapterServiceRecoveryMixin:
    """Sub-mixin: recovery."""

    @classmethod
    def _recommended_recovery_schedule(cls, runtime: dict[str, Any]) -> dict[str, Any]:
        metadata = cls._runtime_metadata(runtime)
        pack = cls._policy_pack_spec(metadata.get('policy_pack'), runtime_class=metadata.get('runtime_class') or metadata.get('kind'), transport=str(runtime.get('transport') or 'http'))
        scheduler = dict(pack.get('scheduler') or {})
        heartbeat_policy = cls._heartbeat_policy(runtime)
        interval_s = scheduler.get('interval_s')
        if interval_s is None:
            try:
                interval_s = max(10, min(int(float(heartbeat_policy.get('active_run_stale_after_s') or 120.0) / 2.0) or 60, 3600))
            except Exception:
                interval_s = 60
        try:
            interval_s = int(interval_s)
        except Exception:
            interval_s = 60
        return {
            'schedule_kind': str(scheduler.get('schedule_kind') or 'interval'),
            'interval_s': max(1, interval_s),
            'limit': int(scheduler.get('limit') or 50),
            'pack_name': str(pack.get('id') or 'generic_async_worker'),
            'lease_ttl_s': max(5, int(scheduler.get('lease_ttl_s') or max(interval_s * 2, 30))),
            'idempotency_ttl_s': max(30, int(scheduler.get('idempotency_ttl_s') or max(interval_s * 10, 300))),
            'workspace_backpressure_limit': max(1, int(scheduler.get('workspace_backpressure_limit') or 1)),
            'runtime_exclusive': bool(scheduler.get('runtime_exclusive', True)),
        }

