from __future__ import annotations

from openmiura.core.audit import AuditStore
from openmiura.application.releases import ReleaseService


def test_phase8_release_service_lifecycle_with_promotion_and_rollback(tmp_path):
    audit = AuditStore(str(tmp_path / 'audit.db'))
    audit.init_db()
    service = ReleaseService()

    class _GW:
        def __init__(self, audit):
            self.audit = audit

    gw = _GW(audit)

    first = service.create_release(
        gw,
        kind='workflow',
        name='invoice-ops',
        version='1.0.0',
        created_by='alice',
        environment='dev',
        tenant_id='tenant-a',
        workspace_id='ws-1',
        items=[{'item_kind': 'workflow', 'item_key': 'invoice-flow', 'item_version': '1.0.0', 'payload': {'steps': 3}}],
    )
    release_id_1 = first['release']['release_id']
    service.submit_release(gw, release_id=release_id_1, actor='alice', tenant_id='tenant-a', workspace_id='ws-1')
    approved_1 = service.approve_release(gw, release_id=release_id_1, actor='bob', tenant_id='tenant-a', workspace_id='ws-1')
    assert approved_1['release']['status'] == 'approved'

    promoted_1 = service.promote_release(
        gw,
        release_id=release_id_1,
        to_environment='staging',
        actor='bob',
        tenant_id='tenant-a',
        workspace_id='ws-1',
    )
    assert promoted_1['release']['status'] == 'promoted'
    assert promoted_1['release']['environment'] == 'staging'

    second = service.create_release(
        gw,
        kind='workflow',
        name='invoice-ops',
        version='1.1.0',
        created_by='alice',
        environment='dev',
        tenant_id='tenant-a',
        workspace_id='ws-1',
        items=[{'item_kind': 'workflow', 'item_key': 'invoice-flow', 'item_version': '1.1.0', 'payload': {'steps': 4}}],
    )
    release_id_2 = second['release']['release_id']
    service.submit_release(gw, release_id=release_id_2, actor='alice', tenant_id='tenant-a', workspace_id='ws-1')
    service.approve_release(gw, release_id=release_id_2, actor='bob', tenant_id='tenant-a', workspace_id='ws-1')
    promoted_2 = service.promote_release(
        gw,
        release_id=release_id_2,
        to_environment='staging',
        actor='bob',
        reason='promote new patch',
        tenant_id='tenant-a',
        workspace_id='ws-1',
    )
    assert promoted_2['release']['status'] == 'promoted'

    detail = service.get_release(gw, release_id=release_id_2, tenant_id='tenant-a', workspace_id='ws-1')
    assert detail['ok'] is True
    assert detail['items'][0]['item_version'] == '1.1.0'
    assert detail['promotions'][0]['to_environment'] == 'staging'
    assert detail['approvals'][0]['action'] == 'promote'
    assert detail['available_actions'] == ['rollback']

    rolled_back = service.rollback_release(gw, release_id=release_id_2, actor='carol', reason='restore stable', tenant_id='tenant-a', workspace_id='ws-1')
    assert rolled_back['ok'] is True
    assert rolled_back['restored_release_id'] == release_id_1

    release_1 = audit.get_release_bundle(release_id_1, tenant_id='tenant-a', workspace_id='ws-1')
    release_2 = audit.get_release_bundle(release_id_2, tenant_id='tenant-a', workspace_id='ws-1')
    assert release_1 is not None and release_1['status'] == 'promoted'
    assert release_2 is not None and release_2['status'] == 'rolled_back'

    listed = service.list_releases(gw, tenant_id='tenant-a', workspace_id='ws-1', environment='staging')
    assert listed['ok'] is True
    assert len(listed['items']) == 2
    promoted_ids = {item['release_id'] for item in listed['items'] if item['status'] == 'promoted'}
    assert promoted_ids == {release_id_1}
