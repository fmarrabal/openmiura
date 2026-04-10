from __future__ import annotations

from openmiura.application.canvas import LiveCanvasService
from openmiura.core.audit import AuditStore


class _GW:
    def __init__(self, audit: AuditStore):
        self.audit = audit
        self.policy = None
        self.realtime_bus = None
        self.secret_broker = None


def test_phase8_pr6_canvas_prechecks_confirmation_health_and_timeline(tmp_path):
    audit = AuditStore(str(tmp_path / 'audit.db'))
    audit.init_db()
    gw = _GW(audit)
    service = LiveCanvasService()

    workflow = audit.create_workflow(
        name='ops-flow',
        definition={'steps': [{'id': 'approval-step', 'kind': 'approval', 'requested_role': 'approver'}]},
        created_by='alice',
        tenant_id='tenant-canvas',
        workspace_id='ws-ops',
        environment='prod',
    )
    workflow = service.operator_console_service.workflow_service.run_workflow(
        gw,
        workflow['workflow_id'],
        actor='alice',
        tenant_id='tenant-canvas',
        workspace_id='ws-ops',
        environment='prod',
    )
    approval = audit.get_pending_approval_for_step(
        workflow['workflow_id'],
        'approval-step',
        tenant_id='tenant-canvas',
        workspace_id='ws-ops',
        environment='prod',
    )
    runtime = audit.upsert_openclaw_runtime(
        name='Remote runtime',
        base_url='simulated://openclaw',
        transport='simulated',
        auth_secret_ref='',
        capabilities=['dispatch'],
        allowed_agents=['default'],
        metadata={'kind': 'openclaw'},
        created_by='alice',
        tenant_id='tenant-canvas',
        workspace_id='ws-ops',
        environment='prod',
    )

    created = service.create_document(
        gw,
        actor='alice',
        title='Operational canvas',
        tenant_id='tenant-canvas',
        workspace_id='ws-ops',
        environment='prod',
    )
    canvas_id = created['document']['canvas_id']

    workflow_node = service.upsert_node(
        gw,
        canvas_id=canvas_id,
        actor='alice',
        node_type='workflow',
        label='Workflow',
        data={'workflow_id': workflow['workflow_id']},
        tenant_id='tenant-canvas',
        workspace_id='ws-ops',
        environment='prod',
    )['node']
    approval_node = service.upsert_node(
        gw,
        canvas_id=canvas_id,
        actor='alice',
        node_type='approval',
        label='Approval',
        data={'approval_id': approval['approval_id'], 'workflow_id': workflow['workflow_id']},
        tenant_id='tenant-canvas',
        workspace_id='ws-ops',
        environment='prod',
    )['node']
    runtime_node = service.upsert_node(
        gw,
        canvas_id=canvas_id,
        actor='alice',
        node_type='openclaw_runtime',
        label='Runtime',
        data={'runtime_id': runtime['runtime_id'], 'agent_id': 'default'},
        tenant_id='tenant-canvas',
        workspace_id='ws-ops',
        environment='prod',
    )['node']

    inspector = service.get_node_inspector(
        gw,
        canvas_id=canvas_id,
        node_id=workflow_node['node_id'],
        tenant_id='tenant-canvas',
        workspace_id='ws-ops',
        environment='prod',
        actor='operator:bob',
    )
    assert inspector['ok'] is True
    assert inspector['action_prechecks']['cancel']['allowed'] is True
    assert inspector['action_prechecks']['cancel']['requires_confirmation'] is True
    assert inspector['node_timeline']

    blocked = service.execute_node_action(
        gw,
        canvas_id=canvas_id,
        node_id=workflow_node['node_id'],
        action='cancel',
        actor='operator:bob',
        tenant_id='tenant-canvas',
        workspace_id='ws-ops',
        environment='prod',
    )
    assert blocked['ok'] is False
    assert blocked['error'] == 'confirmation_required'

    cancelled = service.execute_node_action(
        gw,
        canvas_id=canvas_id,
        node_id=workflow_node['node_id'],
        action='cancel',
        actor='operator:bob',
        payload={'confirmed': True},
        tenant_id='tenant-canvas',
        workspace_id='ws-ops',
        environment='prod',
    )
    assert cancelled['ok'] is True
    assert cancelled['reconciled'] is True
    assert cancelled['refresh']['related']['workflow']['workflow']['status'] == 'cancelled'

    approval_inspector = service.get_node_inspector(
        gw,
        canvas_id=canvas_id,
        node_id=approval_node['node_id'],
        tenant_id='tenant-canvas',
        workspace_id='ws-ops',
        environment='prod',
        actor='approver:jane',
    )
    assert approval_inspector['action_prechecks']['approve']['allowed'] is True
    reject_precheck = approval_inspector['action_prechecks']['reject']
    assert reject_precheck['allowed'] is True
    assert reject_precheck['requires_confirmation'] is True

    health = service.execute_node_action(
        gw,
        canvas_id=canvas_id,
        node_id=runtime_node['node_id'],
        action='health_check',
        actor='operator:bob',
        payload={'probe': 'ready'},
        user_role='workspace_admin',
        user_key='operator:bob',
        session_id='canvas-session',
        tenant_id='tenant-canvas',
        workspace_id='ws-ops',
        environment='prod',
    )
    assert health['ok'] is True
    assert health['result']['health']['status'] == 'healthy'
    assert health['refresh']['related']['runtime']['runtime']['last_health_status'] == 'healthy'

    runtime_timeline = service.get_node_timeline(
        gw,
        canvas_id=canvas_id,
        node_id=runtime_node['node_id'],
        tenant_id='tenant-canvas',
        workspace_id='ws-ops',
        environment='prod',
    )
    assert runtime_timeline['ok'] is True
    labels = {item['label'] for item in runtime_timeline['items']}
    assert 'openclaw_runtime_health_checked' in labels
