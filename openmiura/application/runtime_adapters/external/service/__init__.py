"""``OpenClawAdapterService`` aggregator (originally a 2,579-line class)."""
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



from ._alerts_mixin import _OpenClawAdapterServiceAlertsMixin
from ._core_mixin import _OpenClawAdapterServiceCoreMixin
from ._dispatch_mixin import _OpenClawAdapterServiceDispatchMixin
from ._events_mixin import _OpenClawAdapterServiceEventsMixin
from ._health_mixin import _OpenClawAdapterServiceHealthMixin
from ._policy_mixin import _OpenClawAdapterServicePolicyMixin
from ._recovery_mixin import _OpenClawAdapterServiceRecoveryMixin
from ._runtimes_mixin import _OpenClawAdapterServiceRuntimesMixin


class OpenClawAdapterService(
    _OpenClawAdapterServiceAlertsMixin,
    _OpenClawAdapterServiceCoreMixin,
    _OpenClawAdapterServiceDispatchMixin,
    _OpenClawAdapterServiceEventsMixin,
    _OpenClawAdapterServiceHealthMixin,
    _OpenClawAdapterServicePolicyMixin,
    _OpenClawAdapterServiceRecoveryMixin,
    _OpenClawAdapterServiceRuntimesMixin,
):
    """Governed adapter for delegating execution to external OpenClaw runtimes."""

    TOOL_NAME = 'openclaw_adapter'

    TERMINAL_CANONICAL_STATUSES = {'completed', 'failed', 'cancelled', 'timed_out'}

    POLICY_PACKS: dict[str, dict[str, Any]] = {
        'generic_async_worker': {
            'description': 'Balanced defaults for async external runtimes with event bridge and automatic stale-run recovery.',
            'runtime_classes': ['generic_async_worker', 'generic', 'worker'],
            'metadata': {
                'dispatch_policy': {
                    'dispatch_mode': 'async',
                    'timeout_s': 20,
                    'max_retries': 1,
                    'retry_backoff_ms': 250,
                    'poll_after_s': 2.0,
                    'operator_retry_limit': 2,
                    'max_active_runs': 25,
                    'max_active_runs_per_workspace': 100,
                    'allow_cancel': True,
                    'allow_manual_close': True,
                    'allow_reconcile': True,
                    'allow_cancel_local_fallback': True,
                },
                'heartbeat_policy': {
                    'runtime_stale_after_s': 300,
                    'active_run_stale_after_s': 120,
                    'auto_reconcile_after_s': 300,
                    'poll_interval_s': 10,
                    'max_poll_retries': 2,
                    'auto_poll_enabled': True,
                    'auto_reconcile_enabled': True,
                    'stale_target_status': 'timed_out',
                },
                'session_bridge': {
                    'enabled': True,
                    'event_bridge_enabled': True,
                },
                'event_bridge': {
                    'accepted_sources': ['openclaw'],
                    'accepted_event_types': ['run.accepted', 'run.queued', 'run.progress', 'run.completed', 'run.failed', 'run.cancelled', 'run.timed_out'],
                },
            },
            'scheduler': {'schedule_kind': 'interval', 'interval_s': 60, 'limit': 50, 'lease_ttl_s': 120, 'idempotency_ttl_s': 1800, 'workspace_backpressure_limit': 1, 'runtime_exclusive': True},
        },
        'browser_automation': {
            'description': 'Longer polling windows for browser-led automation with higher latency and explicit timeout recovery.',
            'runtime_classes': ['browser_automation', 'browser', 'web'],
            'metadata': {
                'dispatch_policy': {
                    'dispatch_mode': 'async',
                    'timeout_s': 30,
                    'max_retries': 1,
                    'retry_backoff_ms': 500,
                    'poll_after_s': 3.0,
                    'operator_retry_limit': 1,
                    'max_active_runs': 6,
                    'max_active_runs_per_workspace': 25,
                },
                'heartbeat_policy': {
                    'runtime_stale_after_s': 420,
                    'active_run_stale_after_s': 180,
                    'auto_reconcile_after_s': 600,
                    'poll_interval_s': 15,
                    'max_poll_retries': 3,
                    'auto_poll_enabled': True,
                    'auto_reconcile_enabled': True,
                    'stale_target_status': 'timed_out',
                },
                'session_bridge': {'enabled': True, 'event_bridge_enabled': True},
                'event_bridge': {'accepted_sources': ['openclaw'], 'accepted_event_types': ['run.accepted', 'run.queued', 'run.progress', 'run.completed', 'run.failed', 'run.cancelled', 'run.timeout']},
            },
            'scheduler': {'schedule_kind': 'interval', 'interval_s': 120, 'limit': 30, 'lease_ttl_s': 180, 'idempotency_ttl_s': 2400, 'workspace_backpressure_limit': 1, 'runtime_exclusive': True},
        },
        'terminal_ops': {
            'description': 'More aggressive recovery defaults for terminal-oriented operational runtimes.',
            'runtime_classes': ['terminal_ops', 'terminal', 'shell'],
            'metadata': {
                'dispatch_policy': {
                    'dispatch_mode': 'async',
                    'timeout_s': 15,
                    'max_retries': 1,
                    'retry_backoff_ms': 250,
                    'poll_after_s': 1.0,
                    'operator_retry_limit': 1,
                    'max_active_runs': 10,
                    'max_active_runs_per_workspace': 20,
                },
                'heartbeat_policy': {
                    'runtime_stale_after_s': 180,
                    'active_run_stale_after_s': 60,
                    'auto_reconcile_after_s': 180,
                    'poll_interval_s': 5,
                    'max_poll_retries': 2,
                    'auto_poll_enabled': True,
                    'auto_reconcile_enabled': True,
                    'stale_target_status': 'failed',
                },
                'session_bridge': {'enabled': True, 'event_bridge_enabled': True},
                'event_bridge': {'accepted_sources': ['openclaw'], 'accepted_event_types': ['run.accepted', 'run.queued', 'run.progress', 'run.completed', 'run.failed', 'run.cancelled']},
            },
            'scheduler': {'schedule_kind': 'interval', 'interval_s': 45, 'limit': 50, 'lease_ttl_s': 120, 'idempotency_ttl_s': 1800, 'workspace_backpressure_limit': 1, 'runtime_exclusive': True},
        },
        'document_pipeline': {
            'description': 'Conservative polling and reconcile windows for document-heavy asynchronous workflows.',
            'runtime_classes': ['document_pipeline', 'document', 'pipeline'],
            'metadata': {
                'dispatch_policy': {
                    'dispatch_mode': 'async',
                    'timeout_s': 45,
                    'max_retries': 2,
                    'retry_backoff_ms': 500,
                    'poll_after_s': 5.0,
                    'operator_retry_limit': 2,
                    'max_active_runs': 8,
                    'max_active_runs_per_workspace': 25,
                },
                'heartbeat_policy': {
                    'runtime_stale_after_s': 600,
                    'active_run_stale_after_s': 300,
                    'auto_reconcile_after_s': 900,
                    'poll_interval_s': 30,
                    'max_poll_retries': 3,
                    'auto_poll_enabled': True,
                    'auto_reconcile_enabled': True,
                    'stale_target_status': 'timed_out',
                },
                'session_bridge': {'enabled': True, 'event_bridge_enabled': True},
                'event_bridge': {'accepted_sources': ['openclaw'], 'accepted_event_types': ['run.accepted', 'run.queued', 'run.progress', 'run.completed', 'run.failed']},
            },
            'scheduler': {'schedule_kind': 'interval', 'interval_s': 180, 'limit': 20, 'lease_ttl_s': 240, 'idempotency_ttl_s': 3600, 'workspace_backpressure_limit': 1, 'runtime_exclusive': True},
        },
        'incident_triage': {
            'description': 'Fast heartbeat and reconcile loop for incident-response and triage runtimes.',
            'runtime_classes': ['incident_triage', 'incident', 'triage'],
            'metadata': {
                'dispatch_policy': {
                    'dispatch_mode': 'async',
                    'timeout_s': 15,
                    'max_retries': 1,
                    'retry_backoff_ms': 200,
                    'poll_after_s': 1.0,
                    'operator_retry_limit': 2,
                    'max_active_runs': 20,
                    'max_active_runs_per_workspace': 50,
                },
                'heartbeat_policy': {
                    'runtime_stale_after_s': 120,
                    'active_run_stale_after_s': 30,
                    'auto_reconcile_after_s': 120,
                    'poll_interval_s': 5,
                    'max_poll_retries': 2,
                    'auto_poll_enabled': True,
                    'auto_reconcile_enabled': True,
                    'stale_target_status': 'timed_out',
                },
                'session_bridge': {'enabled': True, 'event_bridge_enabled': True},
                'event_bridge': {'accepted_sources': ['openclaw'], 'accepted_event_types': ['run.accepted', 'run.queued', 'run.progress', 'run.completed', 'run.failed', 'run.cancelled']},
            },
            'scheduler': {'schedule_kind': 'interval', 'interval_s': 30, 'limit': 100, 'lease_ttl_s': 120, 'idempotency_ttl_s': 1200, 'workspace_backpressure_limit': 1, 'runtime_exclusive': True},
        },
        'simulated_lab': {
            'description': 'Fast feedback defaults for simulated or local lab runtimes.',
            'runtime_classes': ['simulated_lab', 'simulated', 'lab'],
            'metadata': {
                'dispatch_policy': {
                    'dispatch_mode': 'async',
                    'timeout_s': 5,
                    'max_retries': 0,
                    'retry_backoff_ms': 50,
                    'poll_after_s': 0.25,
                    'operator_retry_limit': 3,
                    'max_active_runs': 50,
                    'max_active_runs_per_workspace': 200,
                },
                'heartbeat_policy': {
                    'runtime_stale_after_s': 60,
                    'active_run_stale_after_s': 5,
                    'auto_reconcile_after_s': 15,
                    'poll_interval_s': 1,
                    'max_poll_retries': 1,
                    'auto_poll_enabled': True,
                    'auto_reconcile_enabled': True,
                    'stale_target_status': 'timed_out',
                },
                'session_bridge': {'enabled': True, 'event_bridge_enabled': True},
                'event_bridge': {'accepted_sources': ['openclaw'], 'accepted_event_types': ['run.accepted', 'run.queued', 'run.progress', 'run.completed', 'run.failed', 'run.cancelled', 'run.timed_out']},
            },
            'scheduler': {'schedule_kind': 'interval', 'interval_s': 10, 'limit': 200, 'lease_ttl_s': 30, 'idempotency_ttl_s': 300, 'workspace_backpressure_limit': 2, 'runtime_exclusive': True},
        },
    }

    RUNTIME_CLASS_ALIASES = {
        'generic': 'generic_async_worker',
        'worker': 'generic_async_worker',
        'browser': 'browser_automation',
        'web': 'browser_automation',
        'terminal': 'terminal_ops',
        'shell': 'terminal_ops',
        'document': 'document_pipeline',
        'pipeline': 'document_pipeline',
        'incident': 'incident_triage',
        'triage': 'incident_triage',
        'simulated': 'simulated_lab',
        'lab': 'simulated_lab',
    }



from openmiura.application.runtime_adapters.external.service import _alerts_mixin
from openmiura.application.runtime_adapters.external.service import _core_mixin
from openmiura.application.runtime_adapters.external.service import _dispatch_mixin
from openmiura.application.runtime_adapters.external.service import _events_mixin
from openmiura.application.runtime_adapters.external.service import _health_mixin
from openmiura.application.runtime_adapters.external.service import _policy_mixin
from openmiura.application.runtime_adapters.external.service import _recovery_mixin
from openmiura.application.runtime_adapters.external.service import _runtimes_mixin
for _mod in (
    _alerts_mixin,
    _core_mixin,
    _dispatch_mixin,
    _events_mixin,
    _health_mixin,
    _policy_mixin,
    _recovery_mixin,
    _runtimes_mixin,
):
    _mod.OpenClawAdapterService = OpenClawAdapterService
del _mod
