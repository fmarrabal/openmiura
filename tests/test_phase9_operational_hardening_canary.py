from __future__ import annotations

from openmiura.application.releases import ReleaseService
from openmiura.core.audit import AuditStore


class _GW:
    def __init__(self, audit: AuditStore):
        self.audit = audit


def test_phase9_canary_percentage_routing_is_stable_and_observable(tmp_path):
    audit = AuditStore(str(tmp_path / 'audit.db'))
    audit.init_db()
    gw = _GW(audit)
    service = ReleaseService()

    baseline = service.create_release(
        gw,
        kind='workflow',
        name='ops-flow',
        version='1.0.0',
        created_by='alice',
        environment='prod',
        tenant_id='tenant-r',
        workspace_id='ws-r',
    )['release']
    service.submit_release(gw, release_id=baseline['release_id'], actor='alice', tenant_id='tenant-r', workspace_id='ws-r')
    service.approve_release(gw, release_id=baseline['release_id'], actor='bob', tenant_id='tenant-r', workspace_id='ws-r')
    service.promote_release(gw, release_id=baseline['release_id'], to_environment='prod', actor='bob', tenant_id='tenant-r', workspace_id='ws-r')

    candidate = service.create_release(
        gw,
        kind='workflow',
        name='ops-flow',
        version='1.1.0',
        created_by='alice',
        environment='staging',
        tenant_id='tenant-r',
        workspace_id='ws-r',
    )['release']
    service.submit_release(gw, release_id=candidate['release_id'], actor='alice', tenant_id='tenant-r', workspace_id='ws-r')
    service.approve_release(gw, release_id=candidate['release_id'], actor='bob', tenant_id='tenant-r', workspace_id='ws-r')
    service.configure_canary(
        gw,
        release_id=candidate['release_id'],
        actor='bob',
        target_environment='prod',
        traffic_percent=25,
        step_percent=25,
        bake_minutes=15,
        status='draft',
        tenant_id='tenant-r',
        workspace_id='ws-r',
    )
    service.record_gate_run(
        gw,
        release_id=candidate['release_id'],
        gate_name='shadow-regression',
        status='passed',
        actor='qa-bot',
        tenant_id='tenant-r',
        workspace_id='ws-r',
        environment='prod',
    )
    activated = service.activate_canary(
        gw,
        release_id=candidate['release_id'],
        actor='bob',
        baseline_release_id=baseline['release_id'],
        tenant_id='tenant-r',
        workspace_id='ws-r',
    )
    assert activated['canary']['status'] == 'active'

    decisions = []
    for idx in range(200):
        item = service.resolve_canary_route(
            gw,
            release_id=candidate['release_id'],
            routing_key=f'user-{idx}',
            actor='router',
            tenant_id='tenant-r',
            workspace_id='ws-r',
        )['decision']
        decisions.append(item)

    canary_count = sum(1 for item in decisions if item['route_kind'] == 'canary')
    assert 30 <= canary_count <= 70

    observed = service.record_canary_observation(
        gw,
        decision_id=decisions[0]['decision_id'],
        actor='router',
        success=True,
        latency_ms=120.0,
        cost_estimate=0.004,
        metadata={'trace_id': 'trace-1'},
        tenant_id='tenant-r',
        workspace_id='ws-r',
    )
    assert observed['decision']['success'] is True
    assert observed['decision']['observation']['trace_id'] == 'trace-1'

    summary = service.routing_summary(
        gw,
        release_id=candidate['release_id'],
        tenant_id='tenant-r',
        workspace_id='ws-r',
        target_environment='prod',
    )['summary']
    assert summary['total_decisions'] == 200
    assert 0.15 <= summary['canary_ratio'] <= 0.35
    assert audit.count_release_routing_decisions(tenant_id='tenant-r', workspace_id='ws-r', target_environment='prod') == 200
