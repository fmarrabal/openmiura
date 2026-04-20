from __future__ import annotations

from types import SimpleNamespace

import pytest

from openmiura.application.admin.status_snapshot import build_status_snapshot, collect_registered_tool_names
from openmiura.application.canvas.helpers import (
    enforce_canvas_counts,
    enforce_canvas_payload,
    normalize_toggles,
    payload_size,
    redact_sensitive,
    sanitize_scope,
)
from openmiura.application.canvas.service import LiveCanvasService
from openmiura.application.openclaw.scheduler import OpenClawRecoverySchedulerService
from openmiura.application.openclaw.scheduler_primitives import (
    alert_delivery_job_definition,
    baseline_simulation_custody_job_definition,
    baseline_simulation_custody_job_id,
    decorate_idempotency_record,
    decorate_worker_lease,
    governance_wave_job_id,
    holder_id,
    is_workflow_job,
    recovery_job_definition,
    scheduler_policy,
    scope,
)


class _AuditStub:
    def table_counts(self):
        return {'events': 5}

    def count_memory_items(self):
        return 7

    def count_sessions(self):
        return 3

    def count_active_sessions(self, *, window_s: int):
        assert window_s == 86400
        return 2

    def get_last_event(self):
        return {'kind': 'message'}

    def count_canvas_nodes(self, **_: object):
        return 1

    def count_canvas_edges(self, **_: object):
        return 1

    def count_canvas_views(self, **_: object):
        return 1


class _TenancyStub:
    def normalize_scope(self, **kwargs):
        return {**kwargs, 'environment': kwargs.get('environment') or 'dev'}


def _safe_call(obj, method_name, default, /, *args, **kwargs):
    method = getattr(obj, method_name, None)
    if not callable(method):
        return default
    return method(*args, **kwargs)


def test_collect_registered_tool_names_is_sorted():
    tools = SimpleNamespace(registry=SimpleNamespace(_tools={'zeta': object(), 'alpha': object()}))
    assert collect_registered_tool_names(tools) == ['alpha', 'zeta']


def test_build_status_snapshot_produces_expected_structure():
    settings = SimpleNamespace(
        agents_path='configs/agents.yaml',
        policies_path='configs/policies.yaml',
        memory=SimpleNamespace(enabled=True, embed_model='nomic-embed'),
        llm=SimpleNamespace(provider='ollama', model='qwen', base_url='http://127.0.0.1:11434'),
        storage=SimpleNamespace(db_path='data/audit.db'),
        sandbox=SimpleNamespace(enabled=True, default_profile='local-safe'),
    )
    gw = SimpleNamespace(
        audit=_AuditStub(),
        router=SimpleNamespace(available_agents=lambda: ['assistant']),
        policy=SimpleNamespace(signature=lambda: 'abc123'),
        sandbox=SimpleNamespace(profiles_catalog=lambda: {'local-safe': {}, 'strict': {}}),
        settings=settings,
        telegram=object(),
        slack=None,
        started_at=10.0,
    )

    snapshot = build_status_snapshot(
        gw,
        safe_call=_safe_call,
        tenancy_catalog={'modes': ['single-tenant']},
        tool_names=['calculator', 'web_fetch'],
    )

    assert snapshot['ok'] is True
    assert snapshot['tools']['registered'] == ['calculator', 'web_fetch']
    assert snapshot['router']['agents'] == ['assistant']
    assert snapshot['policy']['signature'] == 'abc123'
    assert snapshot['memory']['total_items'] == 7
    assert snapshot['channels']['telegram_configured'] is True
    assert snapshot['channels']['slack_configured'] is False
    assert snapshot['tenancy'] == {'modes': ['single-tenant']}


def test_canvas_helper_functions_cover_limits_and_redaction():
    gw = SimpleNamespace(audit=_AuditStub(), tenancy=_TenancyStub())

    assert payload_size({'hola': 'mundo'}) > 0
    assert normalize_toggles({'policy': False, 'unknown': True}, defaults={'policy': True, 'cost': True}) == {
        'policy': False,
        'cost': True,
    }
    assert sanitize_scope(gw, tenant_id='t1', workspace_id='w1', environment=None) == {
        'tenant_id': 't1',
        'workspace_id': 'w1',
        'environment': 'dev',
    }
    assert redact_sensitive({'token': 'x', 'nested': {'password': 'y', 'safe': 1}}) == {
        'token': '***redacted***',
        'nested': {'password': '***redacted***', 'safe': 1},
    }
    enforce_canvas_payload(payload={'small': 'ok'}, max_payload_chars=100)
    enforce_canvas_counts(
        gw,
        canvas_id='canvas-1',
        kind='node',
        tenant_id='t1',
        workspace_id='w1',
        environment='dev',
        max_nodes_per_canvas=5,
        max_edges_per_canvas=5,
        max_views_per_canvas=5,
    )
    with pytest.raises(ValueError):
        enforce_canvas_payload(payload='x' * 101, max_payload_chars=100)


def test_canvas_service_wrappers_stay_consistent():
    service = LiveCanvasService()
    assert service._payload_size({'a': 1}) == payload_size({'a': 1})
    assert service._normalize_toggles({'policy': False})['policy'] is False


def test_scheduler_primitives_cover_job_shapes_and_lease_decorators():
    assert scope(tenant_id='tenant', workspace_id='workspace', environment='prod') == {
        'tenant_id': 'tenant',
        'workspace_id': 'workspace',
        'environment': 'prod',
    }
    recovery = recovery_job_definition(
        runtime_id='rt-1',
        actor='alice',
        limit=3,
        reason='manual',
        scheduler_policy={'lease_ttl_s': 1},
        kind='openclaw_runtime_recovery',
    )
    assert recovery['kind'] == 'openclaw_runtime_recovery'
    assert is_workflow_job({'workflow_definition': recovery}, kind='openclaw_runtime_recovery', field_name='runtime_id', field_value='rt-1') is True
    alert = alert_delivery_job_definition(
        runtime_id='rt-1',
        alert_code='CPU_HIGH',
        workflow_action='ESCALATE',
        actor='alice',
        target={'type': 'slack'},
        reason='breach',
        escalation_level=2,
        kind='openclaw_alert_delivery',
    )
    assert alert['workflow_action'] == 'escalate'
    assert governance_wave_job_id('bundle', 2) == 'openclaw-governance-wave-advance:bundle:2'
    assert baseline_simulation_custody_job_definition(
        promotion_id='promo', actor='alice', interval_s=1, reason='watch', kind='baseline-job'
    )['interval_s'] == 60
    assert baseline_simulation_custody_job_id('promo') == 'openclaw-baseline-simulation-custody:promo'
    assert scheduler_policy({'workflow_definition': {'scheduler_policy': {'lease_ttl_s': 1, 'idempotency_ttl_s': 1}}})['lease_ttl_s'] == 5
    lease_view = decorate_worker_lease({'lease_key': 'openclaw-recovery:job:abc', 'lease_until': 200, 'created_at': 100, 'updated_at': 150}, now=180)
    assert lease_view['lease_type'] == 'job'
    assert lease_view['active'] is True
    idem_view = decorate_idempotency_record(
        {'status': 'in_progress', 'expires_at': 200, 'updated_at': 150, 'idempotency_key': 'openclaw-recovery:idempotency:job-7:42'},
        now=180,
    )
    assert idem_view['active'] is True
    assert idem_view['job_id'] == 'job-7'
    assert idem_view['due_slot'] == 42
    assert holder_id('alice').startswith('alice:')


def test_scheduler_service_wrappers_delegate_to_primitives():
    assert OpenClawRecoverySchedulerService._scope(tenant_id='t', workspace_id='w', environment='e') == scope(
        tenant_id='t', workspace_id='w', environment='e'
    )
    assert OpenClawRecoverySchedulerService._job_definition(
        runtime_id='rt-1',
        actor='alice',
        limit=2,
        reason='manual',
        scheduler_policy={'lease_ttl_s': 120},
    ) == recovery_job_definition(
        runtime_id='rt-1',
        actor='alice',
        limit=2,
        reason='manual',
        scheduler_policy={'lease_ttl_s': 120},
        kind=OpenClawRecoverySchedulerService.JOB_KIND,
    )
