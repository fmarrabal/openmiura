from __future__ import annotations

from openmiura.application.canvas import LiveCanvasService
from openmiura.core.audit import AuditStore


class _GW:
    def __init__(self, audit: AuditStore):
        self.audit = audit
        self.policy = None


def test_phase8_pr7_canvas_collaboration_comments_snapshots_presence_events_and_compare(tmp_path):
    audit = AuditStore(str(tmp_path / 'audit.db'))
    audit.init_db()
    gw = _GW(audit)
    service = LiveCanvasService()

    created = service.create_document(
        gw,
        actor='alice',
        title='Collab canvas',
        tenant_id='tenant-collab',
        workspace_id='ws-shared',
        environment='prod',
    )
    canvas_id = created['document']['canvas_id']

    node_a = service.upsert_node(
        gw,
        canvas_id=canvas_id,
        actor='alice',
        node_type='workflow',
        label='Workflow node',
        tenant_id='tenant-collab',
        workspace_id='ws-shared',
        environment='prod',
    )
    view = service.save_view(
        gw,
        canvas_id=canvas_id,
        actor='alice',
        name='Operator view',
        is_default=True,
        tenant_id='tenant-collab',
        workspace_id='ws-shared',
        environment='prod',
    )
    presence = service.update_presence(
        gw,
        canvas_id=canvas_id,
        actor='alice',
        user_key='operator:alice',
        selected_node_id=node_a['node']['node_id'],
        tenant_id='tenant-collab',
        workspace_id='ws-shared',
        environment='prod',
    )
    assert presence['presence']['user_key'] == 'operator:alice'

    comment = service.add_comment(
        gw,
        canvas_id=canvas_id,
        actor='alice',
        body='Review the approval path before promotion.',
        node_id=node_a['node']['node_id'],
        tenant_id='tenant-collab',
        workspace_id='ws-shared',
        environment='prod',
    )
    assert comment['comment']['body'].startswith('Review')

    snapshot_a = service.create_snapshot(
        gw,
        canvas_id=canvas_id,
        actor='alice',
        label='Snapshot A',
        view_id=view['view']['view_id'],
        selected_node_id=node_a['node']['node_id'],
        tenant_id='tenant-collab',
        workspace_id='ws-shared',
        environment='prod',
    )
    assert snapshot_a['snapshot']['snapshot_kind'] == 'manual'

    node_b = service.upsert_node(
        gw,
        canvas_id=canvas_id,
        actor='bob',
        node_type='approval',
        label='Approval node',
        tenant_id='tenant-collab',
        workspace_id='ws-shared',
        environment='prod',
    )
    service.add_comment(
        gw,
        canvas_id=canvas_id,
        actor='bob',
        body='Approved to proceed to staging.',
        node_id=node_b['node']['node_id'],
        tenant_id='tenant-collab',
        workspace_id='ws-shared',
        environment='prod',
    )
    snapshot_b = service.create_snapshot(
        gw,
        canvas_id=canvas_id,
        actor='bob',
        label='Snapshot B',
        view_id=view['view']['view_id'],
        selected_node_id=node_b['node']['node_id'],
        tenant_id='tenant-collab',
        workspace_id='ws-shared',
        environment='prod',
    )

    shared = service.share_view(
        gw,
        canvas_id=canvas_id,
        actor='bob',
        view_id=view['view']['view_id'],
        label='Shared mobile view',
        selected_node_id=node_b['node']['node_id'],
        tenant_id='tenant-collab',
        workspace_id='ws-shared',
        environment='prod',
    )
    assert shared['share_token']

    comments = service.list_comments(
        gw,
        canvas_id=canvas_id,
        tenant_id='tenant-collab',
        workspace_id='ws-shared',
        environment='prod',
    )
    snapshots = service.list_snapshots(
        gw,
        canvas_id=canvas_id,
        tenant_id='tenant-collab',
        workspace_id='ws-shared',
        environment='prod',
    )
    presence_events = service.list_presence_events(
        gw,
        canvas_id=canvas_id,
        tenant_id='tenant-collab',
        workspace_id='ws-shared',
        environment='prod',
    )
    comparison = service.compare_snapshots(
        gw,
        snapshot_a_id=snapshot_a['snapshot']['snapshot_id'],
        snapshot_b_id=snapshot_b['snapshot']['snapshot_id'],
        tenant_id='tenant-collab',
        workspace_id='ws-shared',
        environment='prod',
    )
    detail = service.get_document(
        gw,
        canvas_id=canvas_id,
        tenant_id='tenant-collab',
        workspace_id='ws-shared',
        environment='prod',
    )

    assert len(comments['items']) == 2
    assert len(snapshots['items']) >= 3
    assert len(presence_events['items']) >= 1
    assert comparison['ok'] is True
    assert comparison['summary']['node_count_delta'] == 1
    assert node_b['node']['node_id'] in comparison['diff']['added_node_ids']
    assert len(detail['comments']) == 2
    assert len(detail['snapshots']) >= 3
    assert len(detail['presence_events']) >= 1
