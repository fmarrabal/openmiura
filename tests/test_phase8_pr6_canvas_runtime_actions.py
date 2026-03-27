from __future__ import annotations

from openmiura.application.canvas import LiveCanvasService
from openmiura.core.audit import AuditStore


class _GW:
    def __init__(self, audit: AuditStore):
        self.audit = audit
        self.policy = None
        self.realtime_bus = None
        self.secret_broker = None


def test_phase8_pr6_canvas_operational_views_and_node_actions(tmp_path):
    audit = AuditStore(str(tmp_path / 'audit.db'))
    audit.init_db()
    gw = _GW(audit)
    service = LiveCanvasService()

    workflow = audit.create_workflow(
        name='ops-flow',
        definition={'steps': [{'id': 'approval-step', 'type': 'approval'}]},
        created_by='alice',
        tenant_id='tenant-canvas',
        workspace_id='ws-ops',
        environment='prod',
    )
    approval = audit.create_approval(
        workflow_id=workflow['workflow_id'],
        step_id='approval-step',
        requested_role='approver',
        requested_by='alice',
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
        title='Runtime ops canvas',
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

    views = service.list_operational_views(
        gw,
        canvas_id=canvas_id,
        tenant_id='tenant-canvas',
        workspace_id='ws-ops',
        environment='prod',
    )
    assert views['ok'] is True
    suggested_keys = {item['view_key'] for item in views['suggested_views']}
    assert 'overview' in suggested_keys
    assert 'workflow-control' in suggested_keys
    assert 'runtime-ops' in suggested_keys

    workflow_inspector = service.get_node_inspector(
        gw,
        canvas_id=canvas_id,
        node_id=workflow_node['node_id'],
        tenant_id='tenant-canvas',
        workspace_id='ws-ops',
        environment='prod',
    )
    assert workflow_inspector['ok'] is True
    assert 'cancel' in workflow_inspector['available_actions']

    workflow_action = service.execute_node_action(
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
    assert workflow_action['ok'] is True
    assert workflow_action['result']['workflow']['status'] == 'cancelled'

    approval_action = service.execute_node_action(
        gw,
        canvas_id=canvas_id,
        node_id=approval_node['node_id'],
        action='claim',
        actor='operator:bob',
        tenant_id='tenant-canvas',
        workspace_id='ws-ops',
        environment='prod',
    )
    assert approval_action['ok'] is True
    assert approval_action['result']['approval']['assigned_to'] == 'operator:bob'

    runtime_inspector = service.get_node_inspector(
        gw,
        canvas_id=canvas_id,
        node_id=runtime_node['node_id'],
        tenant_id='tenant-canvas',
        workspace_id='ws-ops',
        environment='prod',
    )
    assert runtime_inspector['ok'] is True
    assert 'dry_run' in runtime_inspector['available_actions']
    assert runtime_inspector['related']['runtime']['runtime']['runtime_id'] == runtime['runtime_id']

    runtime_action = service.execute_node_action(
        gw,
        canvas_id=canvas_id,
        node_id=runtime_node['node_id'],
        action='dry_run',
        actor='operator:bob',
        payload={'dispatch_action': 'health_check', 'payload': {'probe': 'liveness'}},
        user_role='workspace_admin',
        user_key='operator:bob',
        session_id='canvas-session',
        tenant_id='tenant-canvas',
        workspace_id='ws-ops',
        environment='prod',
    )
    assert runtime_action['ok'] is True
    assert runtime_action['result']['ok'] is True
    assert runtime_action['result']['response']['mode'] == 'dry-run'
