from __future__ import annotations

from openmiura.application.releases import ReleaseService
from openmiura.core.audit import AuditStore


class _GW:
    def __init__(self, audit: AuditStore):
        self.audit = audit


def test_phase8_pr2_release_governance_artifacts_are_modeled_persisted_and_audited(tmp_path):
    audit = AuditStore(str(tmp_path / 'audit.db'))
    audit.init_db()
    gw = _GW(audit)
    service = ReleaseService()

    created = service.create_release(
        gw,
        kind='workflow',
        name='triage-flow',
        version='1.2.0',
        created_by='alice',
        environment='dev',
        tenant_id='tenant-a',
        workspace_id='ws-1',
        items=[{'item_kind': 'workflow', 'item_key': 'triage', 'item_version': '1.2.0', 'payload': {'steps': 5}}],
    )
    release_id = created['release']['release_id']
    service.submit_release(gw, release_id=release_id, actor='alice', tenant_id='tenant-a', workspace_id='ws-1')
    service.approve_release(gw, release_id=release_id, actor='bob', tenant_id='tenant-a', workspace_id='ws-1')

    canary = service.configure_canary(
        gw,
        release_id=release_id,
        actor='bob',
        target_environment='staging',
        strategy='percentage',
        traffic_percent=10,
        step_percent=10,
        bake_minutes=30,
        status='draft',
        metric_guardrails={'error_rate_max': 0.01, 'p95_latency_ms_max': 1400},
        analysis_summary={'mode': 'governed_artifact_only', 'real_rollout': False},
        tenant_id='tenant-a',
        workspace_id='ws-1',
    )
    assert canary['canary']['traffic_percent'] == 10
    assert canary['canary']['analysis_summary']['real_rollout'] is False

    gate_run = service.record_gate_run(
        gw,
        release_id=release_id,
        gate_name='offline_eval_regression',
        status='passed',
        actor='qa-bot',
        score=0.93,
        threshold=0.90,
        details={'suite': 'release-smoke', 'cases': 24},
        tenant_id='tenant-a',
        workspace_id='ws-1',
        environment='staging',
    )
    assert gate_run['gate_run']['status'] == 'passed'

    change_report = service.set_change_report(
        gw,
        release_id=release_id,
        risk_level='medium',
        actor='alice',
        summary={'breaking_changes': 0, 'changed_items': 1},
        diff={'workflow_steps_delta': 2, 'prompt_hash_changed': True},
        tenant_id='tenant-a',
        workspace_id='ws-1',
    )
    assert change_report['change_report']['risk_level'] == 'medium'

    promoted = service.promote_release(
        gw,
        release_id=release_id,
        to_environment='staging',
        actor='bob',
        reason='gate passed and canary prepared',
        tenant_id='tenant-a',
        workspace_id='ws-1',
    )
    assert promoted['release']['status'] == 'promoted'

    detail = service.get_release(gw, release_id=release_id, tenant_id='tenant-a', workspace_id='ws-1')
    assert detail['ok'] is True
    assert detail['canary'] is not None
    assert detail['canary']['target_environment'] == 'staging'
    assert detail['canary']['metric_guardrails']['error_rate_max'] == 0.01
    assert detail['gate_runs'][0]['gate_name'] == 'offline_eval_regression'
    assert detail['change_report']['summary']['changed_items'] == 1
    assert detail['promotions'][0]['gate_result']['latest_gate']['gate_name'] == 'offline_eval_regression'
    assert detail['promotions'][0]['summary']['canary']['analysis_summary']['real_rollout'] is False
    assert detail['promotions'][0]['summary']['change_report']['risk_level'] == 'medium'
