from __future__ import annotations

from openmiura.application.canvas import LiveCanvasService
from openmiura.core.audit import AuditStore


class _GW:
    def __init__(self, audit: AuditStore):
        self.audit = audit


def test_phase8_pr5_live_canvas_core_persists_documents_nodes_edges_views_and_presence(tmp_path):
    audit = AuditStore(str(tmp_path / 'audit.db'))
    audit.init_db()
    gw = _GW(audit)
    service = LiveCanvasService()

    created = service.create_document(
        gw,
        actor='alice',
        title='Ops canvas',
        description='Runtime overview',
        tenant_id='tenant-canvas',
        workspace_id='ws-live',
        environment='staging',
    )
    canvas_id = created['document']['canvas_id']
    assert created['document']['title'] == 'Ops canvas'

    first_node = service.upsert_node(
        gw,
        canvas_id=canvas_id,
        actor='alice',
        node_type='workflow',
        label='Workflow root',
        position_x=100,
        position_y=50,
        tenant_id='tenant-canvas',
        workspace_id='ws-live',
        environment='staging',
    )
    second_node = service.upsert_node(
        gw,
        canvas_id=canvas_id,
        actor='alice',
        node_type='approval',
        label='Approval gate',
        position_x=300,
        position_y=50,
        tenant_id='tenant-canvas',
        workspace_id='ws-live',
        environment='staging',
    )
    assert first_node['node']['node_type'] == 'workflow'

    edge = service.upsert_edge(
        gw,
        canvas_id=canvas_id,
        actor='alice',
        source_node_id=first_node['node']['node_id'],
        target_node_id=second_node['node']['node_id'],
        label='flows_to',
        tenant_id='tenant-canvas',
        workspace_id='ws-live',
        environment='staging',
    )
    assert edge['edge']['label'] == 'flows_to'

    view = service.save_view(
        gw,
        canvas_id=canvas_id,
        actor='alice',
        name='Default live view',
        layout={'zoom': 1.2},
        filters={'overlay': 'policy'},
        is_default=True,
        tenant_id='tenant-canvas',
        workspace_id='ws-live',
        environment='staging',
    )
    assert view['view']['is_default'] is True

    presence = service.update_presence(
        gw,
        canvas_id=canvas_id,
        actor='alice',
        user_key='operator:alice',
        cursor_x=42,
        cursor_y=21,
        selected_node_id=first_node['node']['node_id'],
        tenant_id='tenant-canvas',
        workspace_id='ws-live',
        environment='staging',
    )
    assert presence['presence']['user_key'] == 'operator:alice'

    detail = service.get_document(
        gw,
        canvas_id=canvas_id,
        tenant_id='tenant-canvas',
        workspace_id='ws-live',
        environment='staging',
    )
    assert detail['ok'] is True
    assert len(detail['nodes']) == 2
    assert len(detail['edges']) == 1
    assert len(detail['views']) == 1
    assert len(detail['presence']) == 1
    assert len(detail['events']) >= 4
