from __future__ import annotations

import json
import time

from openmiura.application.canvas import LiveCanvasService
from openmiura.core.audit import AuditStore


class _GW:
    def __init__(self, audit: AuditStore):
        self.audit = audit
        self.policy = None


def test_phase8_pr6_canvas_operational_overlays_reuse_backend_signals(tmp_path):
    audit = AuditStore(str(tmp_path / 'audit.db'))
    audit.init_db()
    gw = _GW(audit)
    service = LiveCanvasService()

    workflow = audit.create_workflow(
        name='ops_workflow',
        definition={'steps': [{'id': 'step-1', 'type': 'approval'}]},
        created_by='alice',
        tenant_id='tenant-ops',
        workspace_id='ws-ops',
        environment='prod',
    )
    audit.update_workflow_state(
        workflow['workflow_id'],
        status='failed',
        updated_at=time.time(),
        tenant_id='tenant-ops',
        workspace_id='ws-ops',
        environment='prod',
        error='policy blocked',
    )
    approval = audit.create_approval(
        workflow_id=workflow['workflow_id'],
        step_id='step-1',
        requested_role='approver',
        requested_by='alice',
        tenant_id='tenant-ops',
        workspace_id='ws-ops',
        environment='prod',
    )
    audit.log_decision_trace(
        trace_id='trace-1',
        session_id=f"workflow:{workflow['workflow_id']}",
        user_key='operator:alice',
        channel='workflow',
        agent_id='default',
        request_text='run workflow',
        response_text='blocked',
        status='blocked',
        provider='ollama',
        model='qwen2.5:7b-instruct',
        latency_ms=321.0,
        estimated_cost=0.42,
        tools_used_json=json.dumps([{'tool_name': 'web_fetch'}]),
        policies_json=json.dumps([{'name': 'tool_rules[1]', 'effect': 'deny', 'reason': 'tool denied'}]),
        tenant_id='tenant-ops',
        workspace_id='ws-ops',
        environment='prod',
    )
    audit.log_tool_call(
        f"workflow:{workflow['workflow_id']}",
        'operator:alice',
        'default',
        'web_fetch',
        json.dumps({'url': 'https://example.com'}),
        False,
        '',
        'timeout',
        88.0,
        tenant_id='tenant-ops',
        workspace_id='ws-ops',
        environment='prod',
    )
    audit.log_event(
        'admin',
        'operator',
        'alice',
        workflow['workflow_id'],
        {'event': 'secret_resolved', 'ref': 'sec://provider/openai', 'tool_name': 'web_fetch', 'domain': 'api.openai.com'},
        tenant_id='tenant-ops',
        workspace_id='ws-ops',
        environment='prod',
    )
    audit.log_evaluation_run(
        run_id='run-1',
        suite_name='ops_workflow',
        status='completed',
        requested_by='alice',
        provider='ollama',
        model='qwen2.5:7b-instruct',
        agent_name='default',
        started_at=time.time() - 5,
        completed_at=time.time(),
        total_cases=4,
        passed_cases=3,
        failed_cases=1,
        average_latency_ms=210.0,
        total_cost=1.75,
        tenant_id='tenant-ops',
        workspace_id='ws-ops',
        environment='prod',
    )

    created = service.create_document(
        gw,
        actor='alice',
        title='Ops canvas',
        tenant_id='tenant-ops',
        workspace_id='ws-ops',
        environment='prod',
    )
    canvas_id = created['document']['canvas_id']
    workflow_node = service.upsert_node(
        gw,
        canvas_id=canvas_id,
        actor='alice',
        node_type='workflow',
        label='Workflow node',
        data={'workflow_id': workflow['workflow_id']},
        tenant_id='tenant-ops',
        workspace_id='ws-ops',
        environment='prod',
    )
    service.upsert_node(
        gw,
        canvas_id=canvas_id,
        actor='alice',
        node_type='approval',
        label='Approval node',
        data={'approval_id': approval['approval_id'], 'workflow_id': workflow['workflow_id']},
        tenant_id='tenant-ops',
        workspace_id='ws-ops',
        environment='prod',
    )
    service.upsert_node(
        gw,
        canvas_id=canvas_id,
        actor='alice',
        node_type='tool',
        label='web_fetch',
        data={'tool_name': 'web_fetch', 'secret_ref': 'sec://provider/openai'},
        tenant_id='tenant-ops',
        workspace_id='ws-ops',
        environment='prod',
    )

    state = service.save_overlay_state(
        gw,
        canvas_id=canvas_id,
        actor='alice',
        toggles={'policy': True, 'cost': True, 'traces': True, 'failures': True, 'approvals': True, 'secrets': True},
        inspector={'selected_node_id': workflow_node['node']['node_id']},
        tenant_id='tenant-ops',
        workspace_id='ws-ops',
        environment='prod',
    )
    assert state['state']['state_key'] == 'default'

    overlays = service.get_operational_overlays(
        gw,
        canvas_id=canvas_id,
        selected_node_id=workflow_node['node']['node_id'],
        tenant_id='tenant-ops',
        workspace_id='ws-ops',
        environment='prod',
    )
    assert overlays['ok'] is True
    assert overlays['overlays']['approvals']['summary']['pending'] == 1
    assert overlays['overlays']['failures']['summary']['failure_count'] >= 1
    assert overlays['overlays']['traces']['summary']['trace_count'] >= 1
    assert overlays['overlays']['cost']['summary']['total_spend'] >= 1.75
    secret_items = overlays['overlays']['secrets']['items']
    assert secret_items and secret_items[0]['ref'] == 'sec://provider/openai'
    assert overlays['states'][0]['state_key'] == 'default'
